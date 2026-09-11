"""Strict staged storage contracts, shared across all three backends."""

from datetime import UTC, datetime, timedelta

import pytest

from hippo.knowledge import model as k
from hippo.store import migrations

NOW = datetime(2030, 1, 1, tzinfo=UTC)


def generation(store, key="one", parent=None):
    source = store.create_source("text", key) if parent is None else parent.source_id
    row = k.Generation(
        source_id=source,
        parent_id=parent.id if parent else None,
        status="staging",
        parser_version="1",
        linker_version="1",
        embedding_profile="p",
        created_at=NOW,
        manifest_hash=key,
    )
    store.put_knowledge(row)
    store._generation_clock = lambda: NOW
    return row


def claim(store, gen, key="job", owner="worker"):
    return store.claim_generation_build(
        gen.id, job_key=key, lease_owner=owner, lease_expires_at=NOW + timedelta(minutes=5)
    )


def authority(job):
    return dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)


def manifest(store, gen):
    return k.IndexManifest(
        generation_id=gen.id,
        profile_fingerprint="p",
        config_fingerprint="c",
        required_representations=("evidence", "dense", "native"),
        checksums=store.generation_checksums(gen.id),
        ready=True,
    )


def seal(store, gen, job):
    return store.seal_generation(gen.id, manifest(store, gen), **authority(job))


def publish(store, gen, job, **kwargs):
    return store.publish_staged_generation(
        gen.id,
        expected_parent_id=gen.parent_id,
        expected_suppression_epoch=store.suppression_epoch(),
        published_at=NOW,
        **authority(job),
        **kwargs,
    )


def test_schema4_freezes_v3(store):
    assert migrations.CURRENT_SCHEMA_VERSION == 5
    assert (
        migrations.SUPPORTED_CHECKSUMS[3]
        == "ffc12b6f274a5b5573eed4dde9798f8b4abe9d37d68a570247a5c281c10d3ddc"
    )
    assert "GenerationEvidenceMember" in k.RECORD_TYPES
    assert "SnapshotReference" in k.RECORD_TYPES


def test_source_wide_fence_rejects_expired_holder(store):
    assert hasattr(store, "claim_generation_build")
    gen = generation(store)
    job = claim(store, gen)
    other = generation(store, "two", gen)
    with pytest.raises(ValueError):
        claim(store, other)
    store._generation_clock = lambda: NOW + timedelta(minutes=6)
    newer = store.claim_generation_build(
        other.id, job_key="other", lease_owner="new", lease_expires_at=NOW + timedelta(minutes=10)
    )
    assert newer.fencing_token > job.fencing_token
    for operation in (
        lambda: store.check_generation_write(gen.id, **authority(job)),
        lambda: seal(store, gen, job),
        lambda: publish(store, gen, job),
        lambda: store.discard_generation(gen.id, **authority(job)),
    ):
        with pytest.raises(ValueError):
            operation()


def test_seal_publish_epoch_and_immutable_status(store):
    assert hasattr(store, "seal_generation")
    gen = generation(store)
    before = store.authorization_epoch()
    job = claim(store, gen)
    seal(store, gen, job)
    event = publish(store, gen, job)
    assert publish(store, gen, job) == event
    assert store.authorization_epoch() == before
    assert store.content_epoch() > 0
    with pytest.raises(ValueError):
        store.update_knowledge(gen)


@pytest.mark.parametrize("point", ["pointer", "version", "event", "retirement", "lease"])
def test_publish_atomic_rollback(store, point):
    assert hasattr(store, "publish_staged_generation")
    old = generation(store)
    old_job = claim(store, old)
    seal(store, old, old_job)
    publish(store, old, old_job)
    new = generation(store, "new", old)
    job = claim(store, new)
    seal(store, new, job)
    epoch = store.content_epoch()

    def fail(at):
        if at == point:
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        publish(store, new, job, fault_hook=fail)
    assert store.get_source(old.source_id)["active_generation_id"] == old.id
    assert store._knowledge_get("Generation", old.id).status == "active"
    assert store._knowledge_get("MaintenanceJob", job.id).status == "running"
    assert store.content_epoch() == epoch


def test_classifier_is_exhaustive(store):
    from hippo.store import authorization

    assert hasattr(authorization, "RECORD_EPOCHS")
    assert set(authorization.RECORD_EPOCHS) == set(k.RECORD_TYPES)


def evidence(store, gen):
    workspace = store.get_source(gen.source_id)["workspace_id"]
    policy = k.AccessPolicy(workspace_id=workspace, mode="workspace", verified_at=NOW)
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=gen.source_id,
        kind="file",
        external_id="a.txt",
        canonical_uri="a.txt",
        policy_id=policy.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id, content_hash="h", raw_uri="blob:h", observed_at=NOW, lifecycle="active"
    )
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="file_lines",
        locator_json='{"kind":"file_lines","path":"a.txt","start":1,"end":1}',
        text="hello",
        policy_id=policy.id,
    )
    for row in (
        policy,
        artifact,
        revision,
        span,
        k.GenerationMember(generation_id=gen.id, artifact_revision_id=revision.id),
        k.GenerationEvidenceMember(generation_id=gen.id, record_kind="EvidenceSpan", record_id=span.id),
    ):
        store.put_knowledge(row)
    return revision, span


def passage(gen, revision, span):
    from hippo.knowledge.lifecycle import generation_passage_id

    return dict(
        id=generation_passage_id(gen.id, revision.id, span.id, 0),
        source_id=gen.source_id,
        generation_id=gen.id,
        artifact_revision_id=revision.id,
        span_id=span.id,
        embedding_profile="p",
        text=span.text,
        title="a",
        ordinal=0,
        embedding=[0.1, 0.2],
    )


def test_managed_passage_preserves_binding_and_cannot_be_overwritten_without_tag(store):
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
        row = passage(gen, revision, span)
        store.add_passages([row])
    assert next(r for r in store.load_passages() if r["id"] == row["id"]).get("generation_id") == gen.id
    seal(store, gen, job)
    epoch = store.content_epoch()
    store.add_passages([row])
    assert store.content_epoch() == epoch
    changed = {key: value for key, value in row.items() if key != "generation_id"}
    changed["text"] = "corrupt"
    with pytest.raises(ValueError):
        store.add_passages([changed])


@pytest.mark.parametrize(
    "field,value",
    [
        ("embedding_profile", "other"),
        ("span_id", "missing"),
        ("artifact_revision_id", "missing"),
        ("embedding", [float("nan")]),
        ("text", "changed"),
    ],
)
def test_invalid_managed_passage_rejected(store, field, value):
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
    row = passage(gen, revision, span)
    row[field] = value
    with pytest.raises(ValueError):
        with store.generation_write(gen.id, **authority(job)):
            store.add_passages([row])


def test_missing_mandatory_representation_rejected(store):
    gen = generation(store)
    job = claim(store, gen)
    candidate = manifest(store, gen).replace(
        required_representations=("dense",),
        checksums=tuple(c for c in store.generation_checksums(gen.id) if c.kind == "dense"),
    )
    with pytest.raises(ValueError):
        store.seal_generation(gen.id, candidate, **authority(job))


def native_fixture(store, gen, job):
    from hippo.codegraph.model import symbol_id
    from hippo.knowledge.lifecycle import generation_namespace

    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
        row = passage(gen, revision, span)
        store.add_passages([row])
        obj = k.KnowledgeObject(
            workspace_id=store.get_source(gen.source_id)["workspace_id"],
            kind="symbol",
            canonical_key='["a","f"]',
        )
        store.put_knowledge(obj)
        observation = k.ObjectObservation(
            object_id=obj.id,
            revision_id=revision.id,
            span_id=span.id,
            evidence_class="declared",
            recorded_from=NOW,
        )
        store.put_knowledge(observation)
        store.put_knowledge(
            k.GenerationEvidenceMember(
                generation_id=gen.id, record_kind="ObjectObservation", record_id=observation.id
            )
        )
        sid = symbol_id(gen.source_id, "a.py", "f", "function", node_namespace=generation_namespace(gen))
        symbol = dict(
            id=sid,
            source_id=gen.source_id,
            generation_id=gen.id,
            name="f",
            qualname="f",
            kind="function",
            path="a.py",
            embedding=[0.1, 0.2],
        )
        store.add_symbols([symbol])
        store.put_knowledge(
            k.NativeBinding(
                generation_id=gen.id, object_id=obj.id, native_kind="Symbol", native_id=sid, span_id=span.id
            )
        )
        store.link_definitions([(sid, row["id"])])
    return symbol, row


def test_native_payload_and_relationships_freeze_at_seal(store):
    gen = generation(store)
    job = claim(store, gen)
    symbol, row = native_fixture(store, gen, job)
    assert next(r for r in store.load_symbols() if r["id"] == symbol["id"])["generation_id"] == gen.id
    seal(store, gen, job)
    store.add_symbols([symbol])
    with pytest.raises(ValueError):
        store.set_symbol_communities({symbol["id"]: 3})
    with pytest.raises(ValueError):
        store.save_extraction(row["id"], ["tampered"], [], None)


def test_sealed_proof_cannot_gain_support(store):
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
        store.add_passages([passage(gen, revision, span)])
        workspace = store.get_source(gen.source_id)["workspace_id"]
        obj = k.KnowledgeObject(workspace_id=workspace, kind="table", canonical_key='["db","t"]')
        assertion = k.checked_assertion(obj, "CONTRADICTS", obj, scope_key="test")
        version = k.AssertionVersion(
            assertion_id=assertion.id,
            evidence_class="declared",
            rule_version="r",
            confidence=0.9,
            status="active",
            recorded_from=NOW,
        )
        support = k.AssertionSupport(
            assertion_version_id=version.id, span_id=span.id, derivation_group="proof"
        )
        for record in (obj, assertion, version, support):
            store.put_knowledge(record)
        for record in (version, support):
            store.put_knowledge(
                k.GenerationEvidenceMember(
                    generation_id=gen.id, record_kind=type(record).__name__, record_id=record.id
                )
            )
    seal(store, gen, job)
    with pytest.raises(ValueError):
        store.put_knowledge(support.replace(derivation_group="new-proof"))
    with pytest.raises(ValueError):
        store.update_knowledge(version.replace(recorded_to=NOW + timedelta(days=1)))


def test_existing_revision_write_requires_claimed_authority(store):
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        _, span = evidence(store, gen)
    with pytest.raises(ValueError):
        store.put_knowledge(
            span.replace(locator_json='{"kind":"file_lines","path":"a.txt","start":2,"end":2}')
        )


def test_source_wide_cleanup_refuses_managed_source(store):
    gen = generation(store)
    job = claim(store, gen)
    native_fixture(store, gen, job)
    for operation in (
        store.delete_passages_for_source,
        store.delete_code_nodes_for_source,
        store.delete_source,
    ):
        with pytest.raises(ValueError):
            operation(gen.source_id)


def test_binding_cannot_reuse_another_generations_native_row(store):
    old = generation(store)
    job = claim(store, old)
    native_fixture(store, old, job)
    seal(store, old, job)
    publish(store, old, job)
    original = next(b for b in store._knowledge_rows("NativeBinding") if b.generation_id == old.id)
    new = generation(store, "new", old)
    newjob = claim(store, new)
    with pytest.raises(ValueError):
        with store.generation_write(new.id, **authority(newjob)):
            store.put_knowledge(original.replace(generation_id=new.id))


def test_sealed_legacy_graph_contributions_cannot_change(store):
    gen = generation(store)
    job = claim(store, gen)
    symbol, row = native_fixture(store, gen, job)
    seal(store, gen, job)
    with pytest.raises(ValueError):
        store.set_edge_weight(symbol["id"], row["id"], 7.0)
    store.add_entities([dict(id="entity-probe", name="probe", embedding=[0.1, 0.2])])
    with pytest.raises(ValueError):
        store.link_passage_entities([(row["id"], "entity-probe")])


def test_generic_job_update_cannot_resurrect_expired_build(store):
    gen = generation(store)
    job = claim(store, gen)
    store._generation_clock = lambda: NOW + timedelta(minutes=6)
    with pytest.raises(ValueError):
        store.update_knowledge(job.replace(lease_expires_at=NOW + timedelta(minutes=30)))
    with pytest.raises(ValueError):
        store.check_generation_write(gen.id, **authority(job))


def test_exact_membership_requires_claim_even_before_first_job(store):
    gen = generation(store)
    with pytest.raises(ValueError):
        evidence(store, gen)


def test_shared_endpoint_payload_reached_only_by_native_tuning_is_frozen(store):
    gen = generation(store)
    job = claim(store, gen)
    symbol, _ = native_fixture(store, gen, job)
    store.add_entities([dict(id="entity-shared", name="shared", embedding=[0.1, 0.2])])
    with store.generation_write(gen.id, **authority(job)):
        store.set_edge_weight(symbol["id"], "entity-shared", 0.5)
    seal(store, gen, job)
    with pytest.raises(ValueError):
        store.set_node_boost("entity-shared", 2.0)


def test_custom_iterable_cannot_bypass_sealed_relationship_guard(store):
    gen = generation(store)
    job = claim(store, gen)
    symbol, row = native_fixture(store, gen, job)
    seal(store, gen, job)

    class Rows:
        def __iter__(self):
            yield {"passage_id": row["id"], "node_id": symbol["id"], "omega": 0.9}

    with pytest.raises(ValueError):
        store.add_refers_to(Rows())


def test_new_source_exposes_schema4_defaults(store):
    source = store.get_source(store.create_source("text", "new source"))
    assert source.get("managed") is False
    assert source.get("build_fencing_token") == 0
    assert source.get("active_build_id") is None


def test_nonempty_exact_text_requires_dense_coverage(store):
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        evidence(store, gen)
    with pytest.raises(ValueError, match="dense"):
        seal(store, gen, job)


def test_collection_preserves_published_interpretation_immutability(store):
    old = generation(store)
    job = claim(store, old)
    native_fixture(store, old, job)
    original = store._knowledge_rows("ObjectObservation")[0]
    seal(store, old, job)
    publish(store, old, job)
    new = generation(store, "new", old)
    new_job = claim(store, new)
    seal(store, new, new_job)
    publish(store, new, new_job)
    assert store.collect_generation(old.id).blocked_reason is None
    with pytest.raises(ValueError):
        store.update_knowledge(original.replace(recorded_to=NOW + timedelta(days=1)))


def test_never_published_failed_generation_retries_with_fresh_fence_and_clean_payload(store):
    gen = generation(store)
    old_job = claim(store, gen)
    symbol, row = native_fixture(store, gen, old_job)
    store._generation_clock = lambda: NOW + timedelta(minutes=6)
    store.recover_generation_builds()
    retry = store.claim_generation_build(
        gen.id, job_key="retry", lease_owner="new-worker", lease_expires_at=NOW + timedelta(minutes=12)
    )
    assert retry.fencing_token > old_job.fencing_token
    assert store._knowledge_get("Generation", gen.id).status == "staging"
    assert not any(r["id"] == row["id"] for r in store._native_rows("Passage"))
    assert not any(m.generation_id == gen.id for m in store._knowledge_rows("GenerationEvidenceMember"))
    with pytest.raises(ValueError):
        store.check_generation_write(gen.id, **authority(old_job))
    native_fixture(store, gen, retry)
    seal(store, gen, retry)
    publish(store, gen, retry)


def test_collected_published_generation_never_reopens_for_retry(store):
    old = generation(store)
    old_job = claim(store, old)
    seal(store, old, old_job)
    publish(store, old, old_job)
    new = generation(store, "new", old)
    new_job = claim(store, new)
    seal(store, new, new_job)
    publish(store, new, new_job)
    store.collect_generation(old.id)
    with pytest.raises(ValueError):
        claim(store, old, key="retry")


@pytest.mark.parametrize("operation", ["claim", "write"])
def test_build_state_is_reread_after_durable_source_lock(store, monkeypatch, operation):
    gen = generation(store)
    job = claim(store, gen) if operation == "write" else None
    original_lock = store._lock_source

    def interleave(source_id):
        original_lock(source_id)
        store._write_knowledge(gen.replace(status="active", published_at=NOW))

    monkeypatch.setattr(store, "_lock_source", interleave)
    with pytest.raises(ValueError):
        if operation == "claim":
            claim(store, gen)
        else:
            store.check_generation_write(gen.id, **authority(job))


def test_renewal_uses_job_lease_read_after_lock(store, monkeypatch):
    gen = generation(store)
    job = claim(store, gen)
    original_lock = store._lock_source

    def interleave(source_id):
        original_lock(source_id)
        store._write_knowledge(job.replace(lease_expires_at=NOW + timedelta(minutes=40)))

    monkeypatch.setattr(store, "_lock_source", interleave)
    with pytest.raises(ValueError):
        store.renew_generation_build(
            job.id,
            lease_owner=job.lease_owner,
            fencing_token=job.fencing_token,
            lease_expires_at=NOW + timedelta(minutes=30),
        )
