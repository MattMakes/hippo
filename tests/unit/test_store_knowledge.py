"""One evidence persistence contract, exercised unchanged on all three backends."""

from datetime import UTC, datetime, timedelta

import pytest

from hippo.access import EVERYTHING, Access
from hippo.knowledge import model as k

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def foundation(store):
    assert hasattr(store, "put_knowledge"), "Task 3 typed persistence is missing"
    workspace = k.Workspace(name="default")
    store.put_knowledge(workspace)
    source = store.create_source("file", "schema.sql")
    policy = k.AccessPolicy(
        workspace_id=workspace.id,
        origin="local_curated",
        scope_key="source:" + source,
        mode="workspace",
        verified_at=NOW - timedelta(days=1),
    )
    store.put_knowledge(policy)
    artifact = k.Artifact(
        workspace_id=workspace.id,
        source_id=source,
        kind="file",
        external_id="schema.sql",
        canonical_uri="source:s/schema.sql",
        policy_id=policy.id,
    )
    store.put_knowledge(artifact)
    revision = k.ArtifactRevision(
        artifact_id=artifact.id, content_hash="hash", raw_uri="blob:r", observed_at=NOW, lifecycle="active"
    )
    store.put_knowledge(revision)
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="file_lines",
        locator_json='{"kind":"file_lines","path":"schema.sql","start":1,"end":2}',
        text='["original"]\n{DDL}',
        policy_id=policy.id,
    )
    store.put_knowledge(span)
    return workspace, source, policy, artifact, revision, span


def reader(store, workspace_id, name):
    store.ensure_roles()
    user = store.create_user(name, "secret1", "individual")
    store.set_meta("reviewed_mapping_authorities", ["reviewed"])
    store.put_knowledge(
        k.WorkspaceMembership(
            workspace_id=workspace_id,
            principal_id=user,
            enabled=True,
            mapping_authority="reviewed",
            policy_epoch=1,
        )
    )
    return user


def test_persist_immutable_evidence_and_required_scoped_read(store):
    workspace, source, policy, artifact, revision, span = foundation(store)
    assert store.get_knowledge("EvidenceSpan", span.id, workspace_id=workspace.id, access=EVERYTHING) == span
    assert store.get_knowledge("EvidenceSpan", span.id, workspace_id="wrong", access=EVERYTHING) is None
    with pytest.raises(TypeError):
        store.get_knowledge("EvidenceSpan", span.id)
    with pytest.raises(TypeError):
        store.get_knowledge("EvidenceSpan", span.id, workspace_id=workspace.id, access=None)
    assert store.put_knowledge(span) == span.id
    with pytest.raises(ValueError):
        store.put_knowledge(revision.replace(raw_uri="blob:tampered"))
    assert store.get_source(source)["workspace_id"] == workspace.id


def test_reject_dangling_and_cross_workspace_references(store):
    workspace, source, policy, artifact, revision, span = foundation(store)
    with pytest.raises(ValueError):
        store.put_knowledge(
            k.ArtifactRevision(
                artifact_id="missing", content_hash="h", raw_uri="b", observed_at=NOW, lifecycle="active"
            )
        )
    other = k.Workspace(name="other")
    store.put_knowledge(other)
    foreign = k.AccessPolicy(workspace_id=other.id, mode="workspace", verified_at=NOW)
    store.put_knowledge(foreign)
    with pytest.raises(ValueError):
        store.put_knowledge(span.replace(policy_id=foreign.id))
    with pytest.raises(ValueError):
        store.put_knowledge(
            k.ObjectObservation(
                object_id="missing",
                revision_id=revision.id,
                span_id=span.id,
                evidence_class="declared",
                recorded_from=NOW,
            )
        )


def test_recorded_interval_can_only_close_monotonically(store):
    workspace, source, policy, artifact, revision, span = foundation(store)
    obj = k.KnowledgeObject(workspace_id=workspace.id, kind="table", canonical_key='["db","table"]')
    store.put_knowledge(obj)
    observation = k.ObjectObservation(
        object_id=obj.id,
        revision_id=revision.id,
        span_id=span.id,
        evidence_class="declared",
        recorded_from=NOW,
    )
    store.put_knowledge(observation)
    closed = store.update_knowledge(observation.replace(recorded_to=NOW + timedelta(days=1)))
    assert closed == observation.id
    with pytest.raises(ValueError):
        store.update_knowledge(observation)
    with pytest.raises(ValueError):
        store.update_knowledge(observation.replace(recorded_to=NOW + timedelta(days=2)))


def generation(store):
    workspace, source, policy, artifact, revision, span = foundation(store)
    gen = k.Generation(
        source_id=source,
        status="ready",
        parser_version="p1",
        linker_version="l1",
        embedding_profile="none",
        created_at=NOW,
        manifest_hash="manifest",
    )
    store.put_knowledge(gen)
    store.put_knowledge(k.GenerationMember(generation_id=gen.id, artifact_revision_id=revision.id))
    store.put_knowledge(
        k.IndexManifest(
            generation_id=gen.id,
            profile_fingerprint="none",
            config_fingerprint="config",
            required_representations=("lexical",),
            checksums=(k.RepresentationChecksum(kind="lexical", checksum="c", row_count=1, ready=True),),
            ready=True,
        )
    )
    return workspace, source, gen


@pytest.mark.parametrize("fail_at", ["pointer", "version", "event"])
def test_publication_failure_rolls_back_pointer_version_and_outbox(store, fail_at):
    workspace, source, gen = generation(store)
    before = store.graph_version()

    def fault(step):
        if step == fail_at:
            raise RuntimeError("injected publication failure")

    with pytest.raises(RuntimeError, match="injected"):
        store.publish_generation(gen.id, expected_parent_id=None, published_at=NOW, fault_hook=fault)
    assert store.get_source(source)["active_generation_id"] is None
    assert store.graph_version() == before
    assert store.list_knowledge("IndexEvent", workspace_id=workspace.id, access=EVERYTHING) == []
    assert (
        store.get_knowledge("Generation", gen.id, workspace_id=workspace.id, access=EVERYTHING).status
        == "ready"
    )


def test_publication_compare_and_swap_is_atomic_and_idempotent(store):
    workspace, source, gen = generation(store)
    before = store.graph_version()
    event = store.publish_generation(gen.id, expected_parent_id=None, published_at=NOW)
    assert store.get_source(source)["active_generation_id"] == gen.id
    assert store.graph_version() == before + 1
    assert (
        store.get_knowledge("IndexEvent", event, workspace_id=workspace.id, access=EVERYTHING).generation_id
        == gen.id
    )
    assert store.publish_generation(gen.id, expected_parent_id=None, published_at=NOW) == event
    assert store.graph_version() == before + 1
    with pytest.raises(ValueError):
        store.publish_generation(gen.id, expected_parent_id="not-the-parent", published_at=NOW)


def test_unknown_policy_and_source_visibility_fail_closed(store):
    workspace, source, policy, artifact, revision, span = foundation(store)
    user = reader(store, workspace.id, "evidence-reader")
    denied = k.AccessPolicy(workspace_id=workspace.id, mode="unknown", verified_at=NOW)
    store.put_knowledge(denied)
    private_span = span.replace(
        policy_id=denied.id, text="private", text_hash=__import__("hashlib").sha256(b"private").hexdigest()
    )
    store.put_knowledge(private_span)
    assert (
        store.get_knowledge(
            "EvidenceSpan", private_span.id, workspace_id=workspace.id, access=Access(user_id=user)
        )
        is None
    )
    assert (
        store.get_knowledge("EvidenceSpan", span.id, workspace_id=workspace.id, access=Access(user_id=user))
        == span
    )


def test_support_groups_require_and_within_group_or_across_groups(store):
    w, source, policy, artifact, revision, public = foundation(store)
    ordinary = reader(store, w.id, "ordinary")
    privileged = reader(store, w.id, "privileged")
    private_policy = k.AccessPolicy(
        workspace_id=w.id,
        origin="local_curated",
        scope_key="fixture:private",
        mode="restricted",
        allow_users=(privileged,),
        verified_at=NOW - timedelta(days=1),
    )
    store.put_knowledge(private_policy)
    private = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="field",
        locator_json='{"kind":"field","field_path":"secret"}',
        text="private mapping",
        policy_id=private_policy.id,
    )
    store.put_knowledge(private)
    subject = k.KnowledgeObject(workspace_id=w.id, kind="symbol", canonical_key='["s"]')
    target = k.KnowledgeObject(workspace_id=w.id, kind="table", canonical_key='["t"]')
    for obj in (subject, target):
        store.put_knowledge(obj)
        store.put_knowledge(
            k.ObjectObservation(
                object_id=obj.id,
                revision_id=revision.id,
                span_id=public.id,
                evidence_class="declared",
                recorded_from=NOW,
            )
        )
    assertion = k.checked_assertion(subject, "READS_TABLE", target, scope_key="prod")
    store.put_knowledge(assertion)
    version = k.AssertionVersion(
        assertion_id=assertion.id,
        evidence_class="declared",
        rule_version="1",
        confidence=1.0,
        status="active",
        recorded_from=NOW,
    )
    store.put_knowledge(version)
    for span in (public, private):
        store.put_knowledge(
            k.AssertionSupport(assertion_version_id=version.id, span_id=span.id, derivation_group="mapped")
        )
    assert (
        store.get_knowledge("KnowledgeObject", subject.id, workspace_id=w.id, access=Access(user_id=ordinary))
        == subject
    )
    assert (
        store.get_knowledge("Assertion", assertion.id, workspace_id=w.id, access=Access(user_id=ordinary))
        is None
    )
    assert (
        store.get_knowledge("Assertion", assertion.id, workspace_id=w.id, access=Access(user_id=privileged))
        == assertion
    )
    store.put_knowledge(
        k.AssertionSupport(assertion_version_id=version.id, span_id=public.id, derivation_group="independent")
    )
    assert (
        store.get_knowledge("Assertion", assertion.id, workspace_id=w.id, access=Access(user_id=ordinary))
        == assertion
    )


def test_every_required_lifecycle_record_persists_and_roundtrips(store):
    w, source, policy, artifact, revision, span = foundation(store)

    def put(record):
        store.put_knowledge(record)
        assert (
            store.get_knowledge(type(record).__name__, record.id, workspace_id=w.id, access=EVERYTHING)
            == record
        )
        return record

    store.ensure_roles()
    user = store.create_user("typed-user", "test-password", "individual")
    group = put(k.KnowledgeObject(workspace_id=w.id, kind="group", canonical_key='["group"]'))
    put(
        k.WorkspaceMembership(
            workspace_id=w.id, principal_id=user, enabled=True, mapping_authority="reviewed", policy_epoch=1
        )
    )
    put(
        k.GroupMembership(
            workspace_id=w.id,
            group_id=group.id,
            principal_id=user,
            enabled=True,
            mapping_authority="reviewed",
            policy_epoch=1,
        )
    )
    connector = put(
        k.Connector(
            workspace_id=w.id,
            kind="github",
            instance_url="https://git.example",
            config_json='{"prefix":["x"]}',
        )
    )
    remote = put(
        k.Artifact(
            workspace_id=w.id,
            source_id=source,
            connector_id=connector.id,
            provider_instance="https://git.example",
            kind="ticket",
            external_id="42",
            canonical_uri="https://git.example/42",
            policy_id=policy.id,
        )
    )
    gen = put(
        k.Generation(
            source_id=source,
            status="ready",
            parser_version="p",
            linker_version="l",
            embedding_profile="none",
            created_at=NOW,
            manifest_hash="h",
        )
    )
    put(k.GenerationMember(generation_id=gen.id, artifact_revision_id=revision.id))
    obj = put(k.KnowledgeObject(workspace_id=w.id, kind="table", canonical_key='["db","table"]'))
    put(
        k.ObjectObservation(
            object_id=obj.id,
            revision_id=revision.id,
            span_id=span.id,
            evidence_class="declared",
            recorded_from=NOW,
        )
    )
    assertion = put(k.checked_assertion(obj, "CONTRADICTS", obj, scope_key="prod"))
    av = put(
        k.AssertionVersion(
            assertion_id=assertion.id,
            evidence_class="declared",
            rule_version="r",
            confidence=0.7,
            status="active",
            recorded_from=NOW,
        )
    )
    av2 = put(av.replace(recorded_from=NOW + timedelta(seconds=1)))
    put(k.AssertionSupport(assertion_version_id=av.id, span_id=span.id, derivation_group="direct"))
    store.add_symbols(
        [
            {
                "id": "native-s",
                "source_id": source,
                "name": "f",
                "qualname": "f",
                "kind": "function",
                "lang": "python",
                "path": "a.py",
                "line_start": 1,
                "line_end": 2,
            }
        ]
    )
    binding = put(
        k.NativeBinding(
            generation_id=gen.id,
            object_id=obj.id,
            native_kind="Symbol",
            native_id="native-s",
            span_id=span.id,
        )
    )
    put(k.SyncState(connector_id=connector.id, partition_key="repo", cursor_json='{"token":"[opaque]"}'))
    put(
        k.SyncRun(
            connector_id=connector.id,
            source_id=source,
            scope_key="repo",
            phase="fetch",
            run_key="run",
            input_fingerprint="f",
            lease_owner="worker",
            lease_expires_at=NOW + timedelta(days=1),
            fencing_token=1,
        )
    )
    put(
        k.MaintenanceJob(
            source_id=source,
            scope_key="repo",
            phase="queued",
            kind="rebuild",
            job_key="job",
            input_fingerprint="f",
        )
    )
    put(
        k.SourceEvent(
            connector_id=connector.id,
            artifact_id=remote.id,
            provider_instance="https://git.example",
            provider_artifact_id="42",
            delivery_id="d",
            operation="upsert",
            received_at=NOW,
            payload_hash="h",
            dedupe_key="d",
        )
    )
    put(
        k.IndexManifest(
            generation_id=gen.id,
            profile_fingerprint="p",
            config_fingerprint="c",
            required_representations=("lexical",),
            checksums=(k.RepresentationChecksum(kind="lexical", checksum="c", row_count=0, ready=True),),
            ready=True,
        )
    )
    link = put(
        k.LinkGeneration(
            workspace_id=w.id,
            input_manifest_hash="h",
            linker_version="l",
            assertion_version_ids=(av.id,),
            created_at=NOW,
        )
    )
    history = put(
        k.HistoryManifest(
            workspace_id=w.id,
            revision_ids=(revision.id,),
            assertion_version_ids=(av.id,),
            link_generation_ids=(link.id,),
            knowledge_cutoff=NOW,
            temporal_selector_json='{"mode":"current"}',
        )
    )
    derived = put(
        k.DerivedRecord(
            workspace_id=w.id,
            view_kind="summary",
            rule_version="r",
            input_revision_ids=(revision.id,),
            input_binding_ids=(binding.id,),
            dependency_fingerprint="d",
            state="dirty",
        )
    )
    put(
        k.DerivedDependency(
            derived_record_id=derived.id, input_kind="revision", input_id=revision.id, input_version="r"
        )
    )
    put(
        k.Suppression(
            workspace_id=w.id,
            target_kind="artifact",
            target_id=artifact.id,
            scope_key="repo",
            view_applicability="all_history",
            reason="purge",
            epoch=1,
            created_at=NOW,
            restoration_barrier="purge",
        )
    )
    put(
        k.PurgeJob(
            workspace_id=w.id,
            scope_key="repo",
            request_key="q",
            phase="suppress",
            removal_manifest_ids=(artifact.id,),
            raw_status="pending",
            derived_status="pending",
            saved_output_status="pending",
            backup_disposition="pending",
            audit_code="requested",
            created_at=NOW,
        )
    )
    event = put(
        k.IndexEvent(
            workspace_id=w.id,
            generation_id=gen.id,
            kind="invalidated",
            aggregate_id=source,
            sequence=1,
            dedupe_key="e",
            created_at=NOW,
        )
    )
    put(k.ConsumerAck(event_id=event.id, consumer_id="lexical", state="pending"))
    put(
        k.RetrievalView(
            object_id=obj.id,
            span_id=span.id,
            view_kind="lexical",
            text='["exact"]',
            text_profile="p",
            source_revision_id=revision.id,
            derivation_version="v",
            dependency_fingerprint="d",
            derived_record_id=derived.id,
        )
    )
    section = put(
        k.Section(
            source_revision_id=revision.id,
            original_heading="[heading]",
            ordinal=0,
            breadcrumb=("[array]", '{"object"}', "é"),
            original_span_ids=(span.id,),
        )
    )
    put(k.SectionMember(section_id=section.id, child_id=span.id, child_kind="span", ordinal=0))
    put(
        k.ConflictSet(
            workspace_id=w.id,
            scope_key="prod",
            assertion_version_ids=(av.id, av2.id),
            resolution_status="unresolved",
            support_span_ids=(span.id,),
        )
    )
    put(
        k.Alias(
            workspace_id=w.id,
            namespace="db",
            alias_key="old",
            target_object_id=obj.id,
            authority="reviewed",
            support_span_ids=(span.id,),
            status="explicit",
        )
    )
    put(
        k.QuerySnapshot(
            workspace_id=w.id,
            sources=(k.SnapshotSource(source_id=source, generation_id=gen.id),),
            history_manifest_ids=(history.id,),
            link_generation_id=link.id,
            knowledge_cutoff=NOW,
            temporal=k.CurrentSelector(),
            profile_fingerprint="p",
            settings_fingerprint="s",
            policy_fingerprint="a",
            suppression_epoch=1,
            created_at=NOW,
        )
    )


def test_racing_publications_have_exactly_one_winner(store):
    from concurrent.futures import ThreadPoolExecutor

    w, source, first = generation(store)
    second = first.replace(manifest_hash="other")
    store.put_knowledge(second)
    store.put_knowledge(
        k.IndexManifest(
            generation_id=second.id,
            profile_fingerprint="p",
            config_fingerprint="c",
            required_representations=(),
            checksums=(),
            ready=True,
        )
    )
    other = store
    if store.knowledge_backend == "neo4j":
        import os

        from hippo.store import Store

        other = Store(
            os.environ["NEO4J_URI"], os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]
        )
        other.ensure_schema()

    def attempt(backend, gen):
        try:
            return backend.publish_generation(gen.id, expected_parent_id=None, published_at=NOW)
        except ValueError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt, store, first), executor.submit(attempt, other, second)]
            results = [future.result() for future in futures]
        assert sum(result is not None for result in results) == 1
        assert store.get_source(source)["active_generation_id"] in {first.id, second.id}
        assert len(store.list_knowledge("IndexEvent", workspace_id=w.id, access=EVERYTHING)) == 1
    finally:
        if other is not store:
            other.close()


def test_generation_and_snapshot_cannot_pair_unrelated_sources(store):
    workspace, source, gen = generation(store)
    other_source = store.create_source("file", "other.sql")
    with pytest.raises(ValueError, match="source"):
        store.put_knowledge(gen.replace(source_id=other_source, parent_id=gen.id))
    snapshot = k.QuerySnapshot(
        workspace_id=workspace.id,
        sources=(k.SnapshotSource(source_id=other_source, generation_id=gen.id),),
        knowledge_cutoff=NOW,
        temporal=k.CurrentSelector(),
        profile_fingerprint="p",
        settings_fingerprint="s",
        policy_fingerprint="a",
        suppression_epoch=0,
        created_at=NOW,
    )
    with pytest.raises(ValueError, match="source"):
        store.put_knowledge(snapshot)
    assert store.get_source(source)["active_generation_id"] is None


def test_artifact_provider_must_match_configured_connector(store):
    workspace, source, policy, _, _, _ = foundation(store)
    connector = k.Connector(workspace_id=workspace.id, kind="github", instance_url="https://one.example")
    store.put_knowledge(connector)
    artifact = k.Artifact(
        workspace_id=workspace.id,
        source_id=source,
        connector_id=connector.id,
        provider_instance="https://other.example",
        kind="ticket",
        external_id="42",
        canonical_uri="https://other.example/42",
        policy_id=policy.id,
    )
    with pytest.raises(ValueError, match="provider"):
        store.put_knowledge(artifact)


def test_section_cannot_claim_spans_from_another_revision(store):
    _, _, _, _, revision, span = foundation(store)
    another = revision.replace(content_hash="new-content")
    store.put_knowledge(another)
    section = k.Section(
        source_revision_id=another.id,
        original_heading="Elsewhere",
        ordinal=0,
        breadcrumb=(),
        original_span_ids=(span.id,),
    )
    with pytest.raises(ValueError, match="revision"):
        store.put_knowledge(section)


def test_nested_failure_cannot_commit_partial_outer_transaction(store):
    store.ensure_schema()
    store.set_meta("transaction-proof", "before")
    with pytest.raises(RuntimeError, match="transaction"):
        with store.transaction():
            store.set_meta("transaction-proof", "outer write")
            try:
                with store.transaction():
                    store.set_meta("transaction-proof", "inner write")
                    raise ValueError("caught by caller")
            except ValueError:
                pass
    assert store.get_meta("transaction-proof") == "before"


def test_concurrent_immutable_insert_cannot_overwrite_winning_payload(store, monkeypatch):
    if store.knowledge_backend != "neo4j":
        pytest.skip("Independent writer connections apply to the server backend")
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from hippo.store import Store

    workspace, _, _, _, revision, _ = foundation(store)
    candidates = [revision.replace(content_hash="race", raw_uri=f"blob:{key}") for key in ("a", "b")]
    other = Store(
        os.environ["NEO4J_URI"], os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]
    )
    other.ensure_schema()
    barrier = Barrier(2)

    def insert(backend, record):
        barrier.wait(timeout=15)
        try:
            backend.put_knowledge(record)
            return record
        except ValueError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(insert, backend, record)
                for backend, record in zip((store, other), candidates, strict=True)
            ]
            winners = [record for future in futures if (record := future.result()) is not None]
        assert len(winners) == 1
        assert (
            store.get_knowledge(
                "ArtifactRevision", candidates[0].id, workspace_id=workspace.id, access=EVERYTHING
            )
            == winners[0]
        )
    finally:
        other.close()


def test_artifact_cannot_move_existing_history_to_another_source(store):
    workspace, source, policy, _, _, _ = foundation(store)
    connector = k.Connector(workspace_id=workspace.id, kind="github", instance_url="https://git.example")
    store.put_knowledge(connector)
    artifact = k.Artifact(
        workspace_id=workspace.id,
        source_id=source,
        connector_id=connector.id,
        kind="ticket",
        external_id="42",
        provider_instance="https://git.example",
        canonical_uri="https://git.example/42",
        policy_id=policy.id,
    )
    store.put_knowledge(artifact)
    revision = k.ArtifactRevision(
        artifact_id=artifact.id, content_hash="h", raw_uri="blob:r", observed_at=NOW, lifecycle="active"
    )
    store.put_knowledge(revision)
    another = store.create_source("file", "private.sql", access_role_id="arch-admin")
    with pytest.raises(ValueError, match="immutable"):
        store.update_knowledge(artifact.replace(source_id=another))
    assert (
        store.get_knowledge("Artifact", artifact.id, workspace_id=workspace.id, access=EVERYTHING).source_id
        == source
    )
    assert (
        store.get_knowledge("ArtifactRevision", revision.id, workspace_id=workspace.id, access=EVERYTHING)
        == revision
    )


def test_membership_control_records_require_internal_access(store):
    workspace, *_ = foundation(store)
    store.ensure_roles()
    user = store.create_user("membership-reader", "secret1", "individual")
    membership = k.WorkspaceMembership(
        workspace_id=workspace.id,
        principal_id=user,
        enabled=True,
        mapping_authority="reviewed",
        policy_epoch=1,
    )
    store.put_knowledge(membership)
    assert (
        store.get_knowledge(
            "WorkspaceMembership", membership.id, workspace_id=workspace.id, access=Access(user_id=user)
        )
        is None
    )
    assert (
        store.get_knowledge(
            "WorkspaceMembership", membership.id, workspace_id=workspace.id, access=Access(user_id="other")
        )
        is None
    )
    assert (
        store.get_knowledge(
            "WorkspaceMembership", membership.id, workspace_id=workspace.id, access=EVERYTHING
        )
        == membership
    )


@pytest.mark.parametrize(
    "kind", ["LinkGeneration", "HistoryManifest", "DerivedRecord", "IndexEvent", "QuerySnapshot"]
)
def test_empty_manifests_and_unbound_events_keep_explicit_workspace(store, kind):
    workspace, *_ = foundation(store)
    other = k.Workspace(name="other-empty-workspace")
    store.put_knowledge(other)
    fields = {
        "LinkGeneration": dict(
            input_manifest_hash="empty", linker_version="l", assertion_version_ids=(), created_at=NOW
        ),
        "HistoryManifest": dict(
            revision_ids=(),
            assertion_version_ids=(),
            link_generation_ids=(),
            knowledge_cutoff=NOW,
            temporal_selector_json='{"mode":"current"}',
        ),
        "DerivedRecord": dict(
            view_kind="summary",
            rule_version="r",
            input_revision_ids=(),
            dependency_fingerprint="empty",
            state="dirty",
        ),
        "IndexEvent": dict(
            kind="invalidated", aggregate_id="workspace", sequence=1, dedupe_key="empty", created_at=NOW
        ),
        "QuerySnapshot": dict(
            sources=(),
            knowledge_cutoff=NOW,
            temporal=k.CurrentSelector(),
            profile_fingerprint="p",
            settings_fingerprint="s",
            policy_fingerprint="a",
            suppression_epoch=0,
            created_at=NOW,
        ),
    }
    record = k.RECORD_TYPES[kind](workspace_id=workspace.id, **fields[kind])
    store.put_knowledge(record)
    assert store.get_knowledge(kind, record.id, workspace_id=workspace.id, access=EVERYTHING) == record
    assert store.get_knowledge(kind, record.id, workspace_id=other.id, access=EVERYTHING) is None
    counterpart = k.RECORD_TYPES[kind](workspace_id=other.id, **fields[kind])
    assert counterpart.id != record.id
    store.put_knowledge(counterpart)
    assert store.list_knowledge(kind, workspace_id=workspace.id, access=EVERYTHING) == [record]


@pytest.mark.parametrize("child_kind", ["span", "section"])
def test_section_member_rejects_child_from_another_revision(store, child_kind):
    _, _, _, _, revision, span = foundation(store)
    other = revision.replace(content_hash="other")
    store.put_knowledge(other)
    other_span = span.replace(revision_id=other.id)
    store.put_knowledge(other_span)
    parent = k.Section(
        source_revision_id=revision.id,
        original_heading="parent",
        ordinal=0,
        breadcrumb=(),
        original_span_ids=(span.id,),
    )
    store.put_knowledge(parent)
    child = k.Section(
        source_revision_id=other.id,
        original_heading="child",
        ordinal=0,
        breadcrumb=(),
        original_span_ids=(other_span.id,),
    )
    store.put_knowledge(child)
    with pytest.raises(ValueError, match="revision"):
        store.put_knowledge(
            k.SectionMember(
                section_id=parent.id,
                child_id=other_span.id if child_kind == "span" else child.id,
                child_kind=child_kind,
                ordinal=0,
            )
        )


@pytest.mark.parametrize("mismatch", ["connector", "provider", "artifact"])
def test_source_event_identity_matches_its_provider_artifact(store, mismatch):
    workspace, source, policy, *_ = foundation(store)
    connector = k.Connector(workspace_id=workspace.id, kind="github", instance_url="https://git.example")
    another = connector.replace(instance_url="https://other.example")
    for record in (connector, another):
        store.put_knowledge(record)
    artifact = k.Artifact(
        workspace_id=workspace.id,
        source_id=source,
        connector_id=connector.id,
        kind="ticket",
        external_id="42",
        provider_instance=connector.instance_url,
        canonical_uri="https://git.example/42",
        policy_id=policy.id,
    )
    store.put_knowledge(artifact)
    event = k.SourceEvent(
        connector_id=another.id if mismatch == "connector" else connector.id,
        artifact_id=artifact.id,
        provider_instance=another.instance_url if mismatch == "provider" else connector.instance_url,
        provider_artifact_id="99" if mismatch == "artifact" else "42",
        delivery_id="d",
        operation="upsert",
        received_at=NOW,
        payload_hash="h",
        dedupe_key="d",
    )
    with pytest.raises(ValueError, match="provider"):
        store.put_knowledge(event)
