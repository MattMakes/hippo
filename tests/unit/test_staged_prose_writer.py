"""A complete plain-prose generation is sealed under local epochs and a live fence."""

import importlib
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from threading import Event, Thread

import pytest

from hippo.knowledge import model as k
from hippo.knowledge.identity import text_hash
from tests.unit.test_generation_store import (
    NOW,
    authority,
    claim,
    evidence,
    generation,
    passage,
    publish,
    seal,
)
from tests.unit.test_managed_prose_preparation import inputs, prepare


def rows_for(store, gen_id):
    return [r for r in store._native_rows("Passage") if r.get("generation_id") == gen_id]


def writer():
    try:
        return importlib.import_module("hippo.knowledge.staged_prose")
    except ModuleNotFoundError:
        pytest.fail("Staged prose writer is missing")


def setup(store, tmp_path, text="# Title\n\nACME builds Robot.\n", *, bind=True):
    old = generation(store, "last-good")
    old_job = claim(store, old)
    with store.generation_write(old.id, **authority(old_job)):
        revision, span = evidence(store, old)
        store.add_passages([{**passage(old, revision, span), "embedding": [0.1, 0.2, 0.3]}])
    seal(store, old, old_job)
    publish(store, old, old_job)
    workspace = store.get_source(old.source_id)["workspace_id"]
    policy = k.AccessPolicy(workspace_id=workspace, mode="workspace", verified_at=NOW)
    value = inputs(text, source=old.source_id, workspace=workspace, policy=policy.id, parent=old.id)
    from hippo.ingest.accepted_inputs import ByteInput, CaptureLimits, capture_raw_inputs
    from hippo.knowledge.identity import canonical_json
    from hippo.knowledge.input_binding import AcceptedArtifactBinding, materialize_chunk_evidence
    from hippo.knowledge.lifecycle import generation_for_inputs
    from hippo.knowledge.raw_artifacts import RawArtifactStore

    raw_store = RawArtifactStore(tmp_path / "raw", max_object_bytes=20000)
    captured = capture_raw_inputs(
        raw_store,
        source_id=old.source_id,
        workspace_id=workspace,
        inputs=[ByteInput("notes.md", text.encode(), provider_revision="provider-v1")],
        configuration=json.loads(value.configuration_json),
        limits=CaptureLimits(1000, 2000, 10, 10000),
    )
    manifest = k.Artifact(
        workspace_id=workspace,
        source_id=old.source_id,
        kind="manifest",
        external_id="accepted-inputs-v1",
        canonical_uri=f"source:{old.source_id}/accepted-inputs-v1",
        policy_id=policy.id,
    )
    manifest_revision = k.ArtifactRevision(
        artifact_id=manifest.id,
        content_hash=captured.manifest.sha256,
        raw_uri=captured.manifest.uri,
        observed_at=NOW,
        lifecycle="active",
        metadata_json=canonical_json({"accepted_manifest_v1": json.loads(captured.manifest_bytes)}),
    )
    pairs = (*value.artifacts_and_revisions, (manifest, manifest_revision))
    gen = generation_for_inputs(
        pairs,
        workspace_id=workspace,
        source_id=old.source_id,
        parent_id=old.id,
        parser_version=value.generation.parser_version,
        linker_version=value.generation.linker_version,
        embedding_profile=value.embedding_profile.fingerprint,
        configuration=json.loads(value.configuration_json),
        created_at=NOW,
    )
    a, r = value.artifacts_and_revisions[0]
    mapped = materialize_chunk_evidence(
        tuple(p.chunk for p in value.evidence.passages),
        gen,
        workspace_id=workspace,
        bindings=(AcceptedArtifactBinding(captured.inputs[0], a, r),),
    )
    mapped = replace(
        mapped,
        revision_members=(
            *mapped.revision_members,
            k.GenerationMember(generation_id=gen.id, artifact_revision_id=manifest_revision.id),
        ),
    )
    value = replace(value, generation=gen, evidence=mapped, artifacts_and_revisions=pairs)
    store.put_knowledge(policy)
    store.put_knowledge(value.generation)
    job = claim(store, value.generation, key="next")
    with store.generation_write(value.generation.id, **authority(job)):
        for artifact, revision in value.artifacts_and_revisions:
            store.put_knowledge(artifact)
            store.put_knowledge(revision)
        for member in value.evidence.revision_members:
            store.put_knowledge(member)
    if bind:
        store.bind_generation_embedding_profile(value.generation.id, manifest_revision.id, **authority(job))
    prepared = prepare(value)
    credentials = dict(
        **authority(job),
        expected_authorization_epoch=store.authorization_epoch(),
        expected_suppression_epoch=store.suppression_epoch(),
    )
    return old, job, prepared, credentials


def write(store, prepared, credentials, *, check=None, **kwargs):
    def outside():
        assert not getattr(store, "_transaction_depth", 0)
        assert getattr(store, "_transaction", None) is None
        if check:
            check()

    return writer().write_staged_prose(store, prepared, check=outside, **credentials, **kwargs)


@pytest.mark.parametrize("text", ["ACME builds Robot.", "# Title\n\nACME builds Robot.\n", ""])
def test_writer_seals_exact_inventory_without_publishing_or_global_metadata(store, tmp_path, text):
    old, job, prepared, credentials = setup(store, tmp_path, text)
    before = {key: store.get_meta(key) for key in ("embed_model", "embedding_dim", "graph_version")}
    manifest = write(store, prepared, credentials, batch_size=1)
    gen = prepared.inputs.generation
    assert manifest == store.validate_generation_seal(gen.id)
    assert store._generation(gen.id).status == "ready"
    assert store.get_source(old.source_id)["active_generation_id"] == old.id
    assert len(rows_for(store, old.id)) == 1
    assert len(rows_for(store, gen.id)) == len(prepared.dense)
    from hippo.knowledge.graph_loader import load_generation_graph

    held = load_generation_graph(
        store, generations={old.source_id: old.id}, legacy_source_ids=frozenset(), version=1
    )
    assert held.passage_embeddings.shape == (1, 3)
    assert {key: store.get_meta(key) for key in before} == before
    assert not store.load_entities() and not store.load_facts()
    assert store._knowledge_get("MaintenanceJob", job.id).status == "running"


def test_explicit_publication_projects_original_closure_and_inferred_facts(store, tmp_path):
    from hippo.access import EVERYTHING
    from hippo.knowledge.access import EvidenceAccess, EvidenceSelection
    from hippo.knowledge.graph_loader import load_generation_graph
    from hippo.knowledge.projection import project_managed_graph

    old, job, prepared, credentials = setup(store, tmp_path)

    def project(store, gen):
        engine = EvidenceAccess(store, prepared.inputs.evidence.workspace_id, EVERYTHING, clock=lambda: NOW)
        proof = engine.build(
            EvidenceSelection(generation_ids=frozenset({gen.id}), require_exact_membership=True)
        )
        full = load_generation_graph(
            store, generations={gen.source_id: gen.id}, legacy_source_ids=frozenset(), version=1
        )
        return project_managed_graph(full, store, proof, embedding_profile=gen.embedding_profile)

    write(store, prepared, credentials)
    publish(store, prepared.inputs.generation, job)
    graph = project(store, prepared.inputs.generation)
    assert len(graph.facts) == 1
    assert set(graph.entity_names.values()) == {"acme", "robot"}
    assert any(edge.synonym_score == pytest.approx(1.0) for edge in graph.edges.values())
    assert {c.text for c in graph.original_citations} == {s.text for s in prepared.inputs.evidence.spans}
    title = next(s for s in prepared.inputs.evidence.spans if s.text.startswith("# Title"))
    store.put_knowledge(
        k.Suppression(
            workspace_id=prepared.inputs.evidence.workspace_id,
            target_kind="span",
            target_id=title.id,
            scope_key="writer-test",
            created_at=NOW,
            reason="access_loss",
            view_applicability="all_history",
            epoch=1,
            restoration_barrier="review",
        )
    )
    graph = project(store, prepared.inputs.generation)
    assert not graph.passages and not graph.facts and not graph.entity_names


@pytest.mark.parametrize("epoch", ["authorization", "suppression"])
def test_revoke_between_external_check_and_fence_denies_before_any_write(store, tmp_path, monkeypatch, epoch):
    old, job, prepared, credentials = setup(store, tmp_path)
    original = store.generation_write

    @contextmanager
    def revoke_then_fence(*args, **kwargs):
        from hippo.store.authorization import bump_epoch

        bump_epoch(store, epoch + "_epoch")
        with original(*args, **kwargs):
            yield

    monkeypatch.setattr(store, "generation_write", revoke_then_fence)
    with pytest.raises(Exception, match="epoch|Authorization|authorization|suppression"):
        write(store, prepared, credentials)
    assert not rows_for(store, prepared.inputs.generation.id)
    assert store.get_source(old.source_id)["active_generation_id"] == old.id


@pytest.mark.parametrize("epoch", ["authorization", "suppression"])
def test_epoch_change_during_dense_batch_rolls_back_that_batch_and_never_seals(
    store, tmp_path, monkeypatch, epoch
):
    old, job, prepared, credentials = setup(store, tmp_path)
    original = store.add_passages

    def revoke(rows):
        from hippo.store.authorization import bump_epoch

        original(rows)
        bump_epoch(store, epoch + "_epoch")

    monkeypatch.setattr(store, "add_passages", revoke)
    with pytest.raises(Exception, match="epoch|Authorization|authorization|suppression"):
        write(store, prepared, credentials, batch_size=1)
    assert not rows_for(store, prepared.inputs.generation.id)
    assert store._generation(prepared.inputs.generation.id).status == "staging"
    assert store.get_source(old.source_id)["active_generation_id"] == old.id


@pytest.mark.parametrize("kind", ["Passage", "ProseExtraction", "GenerationEvidenceMember"])
def test_omitted_persisted_required_output_prevents_seal(store, tmp_path, monkeypatch, kind):
    old, job, prepared, credentials = setup(store, tmp_path)
    if kind == "Passage":
        monkeypatch.setattr(store, "add_passages", lambda rows: None)
    else:
        original = store.put_knowledge

        def omit(record):
            if type(record).__name__ == kind and (
                kind != "GenerationEvidenceMember" or record.record_kind == "ProseExtraction"
            ):
                return record.id
            return original(record)

        monkeypatch.setattr(store, "put_knowledge", omit)
    with pytest.raises(ValueError):
        write(store, prepared, credentials)
    assert store._generation(prepared.inputs.generation.id).status == "staging"
    assert store.get_source(old.source_id)["active_generation_id"] == old.id


def test_lost_fence_after_a_batch_leaves_staging_without_touching_last_good(store, tmp_path):
    old, job, prepared, credentials = setup(store, tmp_path)
    calls = 0

    def expire():
        nonlocal calls
        calls += 1
        if calls == 2:
            store._generation_clock = lambda: NOW + timedelta(minutes=6)

    with pytest.raises(ValueError, match="lease|fence"):
        write(store, prepared, credentials, check=expire, batch_size=1)
    assert store._generation(prepared.inputs.generation.id).status == "staging"
    assert store.get_source(old.source_id)["active_generation_id"] == old.id


def test_standalone_wrapper_rejects_outer_transaction_before_callback(store, tmp_path):
    old, job, prepared, credentials = setup(store, tmp_path)
    with pytest.raises(ValueError, match="outer|transaction"):
        with store.transaction():
            write(store, prepared, credentials)


def test_wrapper_ignores_an_outer_transaction_another_thread_owns(store, tmp_path):
    """Two refreshes in different threads must not reject each other's transaction.

    The store holds one lock for a whole transaction body, so the depth counter beside it
    reads as "in a transaction" from every thread; the wrapper asks the per-thread
    `in_ambient_transaction()` instead. Calling the wrapper directly: the shared `write`
    helper's callback asserts the process-global attributes, which the holder sets.
    """
    old, job, prepared, credentials = setup(store, tmp_path)
    held, release = Event(), Event()
    seen, errors = [], []

    def hold():
        try:
            with store.transaction():
                seen.append(store.in_ambient_transaction())
                held.set()
                assert release.wait(60)
        except BaseException as exc:  # noqa: BLE001 - asserted on the calling thread below
            errors.append(exc)
        finally:
            held.set()

    def past_the_probe():
        # The wrapper is past its entry probe; free the holder so its lock can be taken.
        release.set()

    thread = Thread(target=hold)
    thread.start()
    try:
        assert held.wait(10), "holder must own an open transaction"
        manifest = writer().write_staged_prose(store, prepared, check=past_the_probe, **credentials)
    finally:
        release.set()
        thread.join(60)
    assert not thread.is_alive() and errors == []
    assert seen == [True]
    assert manifest == store.validate_generation_seal(prepared.inputs.generation.id)


def test_wrapper_still_rejects_a_transaction_the_caller_owns(store, tmp_path):
    """The sibling of the cross-thread case: the caller's own transaction still refuses."""
    old, job, prepared, credentials = setup(store, tmp_path)
    calls = []
    with store.transaction():
        assert store.in_ambient_transaction() is True
        with pytest.raises(ValueError, match="requires no outer transaction"):
            writer().write_staged_prose(store, prepared, check=lambda: calls.append("called"), **credentials)
    assert calls == []


def test_local_core_is_callback_free_inside_existing_transaction(store, tmp_path):
    old, job, prepared, credentials = setup(store, tmp_path)
    module = writer()
    with store.transaction():
        for batch in module._write_batches(prepared, batch_size=1):
            module._write_batch(store, prepared, batch, **credentials)
        manifest = module._seal(store, prepared, **credentials)
    assert manifest == store.validate_generation_seal(prepared.inputs.generation.id)


def test_extra_exact_member_is_not_silently_accepted_or_deleted(store, tmp_path):
    old, job, prepared, credentials = setup(store, tmp_path)
    extra = prepared.inputs.evidence.spans[0].replace(text="extra text", text_hash=text_hash("extra text"))
    with store.generation_write(prepared.inputs.generation.id, **authority(job)):
        for member in prepared.inputs.evidence.revision_members:
            store.put_knowledge(member)
        store.put_knowledge(extra)
        store.put_knowledge(
            k.GenerationEvidenceMember(
                generation_id=prepared.inputs.generation.id, record_kind="EvidenceSpan", record_id=extra.id
            )
        )
    with pytest.raises(ValueError, match="inventory|member"):
        write(store, prepared, credentials)
    assert store._generation(prepared.inputs.generation.id).status == "staging"


def test_new_writer_requires_controlled_verified_profile_before_mutation(store, tmp_path):
    old, job, prepared, credentials = setup(store, tmp_path, bind=False)
    with pytest.raises(ValueError, match="verified|binding|profile"):
        write(store, prepared, credentials)
    assert not rows_for(store, prepared.inputs.generation.id)
    assert not [
        r
        for r in store._knowledge_rows("GenerationEvidenceMember")
        if r.generation_id == prepared.inputs.generation.id
    ]
    assert store.get_source(old.source_id)["active_generation_id"] == old.id


@pytest.mark.parametrize("field", ["profile", "config_fingerprint"])
def test_writer_compares_local_bound_profile_and_configuration_before_mutation(
    store, tmp_path, monkeypatch, field
):
    from hippo.knowledge import generation_profiles

    old, job, prepared, credentials = setup(store, tmp_path)
    original = generation_profiles.validate_generation_profile

    def wrong(*args, **kwargs):
        value = original(*args, **kwargs)
        return replace(value, **{field: None if field == "profile" else "wrong"})

    monkeypatch.setattr(generation_profiles, "validate_generation_profile", wrong)
    with pytest.raises(ValueError, match="profile|configuration"):
        write(store, prepared, credentials)
    assert not rows_for(store, prepared.inputs.generation.id)


def test_controlled_profile_and_sealed_prose_survive_reopen(tmp_path):
    from hippo.knowledge.derivations import validate_prose
    from hippo.knowledge.generation_profiles import validate_generation_profile
    from hippo.store.ladybug import LadybugStore

    path = tmp_path / "prose.lbug"
    store = LadybugStore(path)
    try:
        old, job, prepared, credentials = setup(store, tmp_path)
        manifest = write(store, prepared, credentials)
    finally:
        store.close()
    reopened = LadybugStore(path)
    try:
        gen = reopened._generation(prepared.inputs.generation.id)
        assert reopened.validate_generation_seal(gen.id) == manifest
        assert validate_generation_profile(reopened, gen).profile == prepared.inputs.embedding_profile
        assert validate_prose(reopened, gen.id, prepared.extractions[0]).span_ids == frozenset(
            s.id for s in prepared.inputs.evidence.spans
        )
        assert reopened.get_source(old.source_id)["active_generation_id"] == old.id
    finally:
        reopened.close()
