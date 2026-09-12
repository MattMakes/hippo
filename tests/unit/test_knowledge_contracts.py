"""Immutable record and transport contracts, independent of a persistence backend."""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def model():
    try:
        return importlib.import_module("hippo.knowledge.model")
    except ModuleNotFoundError:
        pytest.fail("Task 2 evidence contracts have not been implemented")


def test_complete_required_record_catalog_exists():
    m = model()
    required = "Workspace WorkspaceMembership GroupMembership Connector Artifact ArtifactRevision Generation GenerationMember EvidenceSpan KnowledgeObject ObjectObservation Assertion AssertionVersion AssertionSupport NativeBinding AccessPolicy SyncState SyncRun MaintenanceJob SourceEvent IndexManifest LinkGeneration HistoryManifest DerivedRecord DerivedDependency Suppression PurgeJob IndexEvent ConsumerAck RetrievalView Section SectionMember ConflictSet Alias QueryRequest QueryBudget QuerySnapshot EvidenceEnvelope QueryEnvelope".split()
    assert set(required) <= set(vars(m))
    assert set(required[:-6]) <= set(m.RECORD_TYPES)


@pytest.mark.parametrize(
    "name", ["LinkGeneration", "HistoryManifest", "QuerySnapshot", "DerivedRecord", "IndexEvent"]
)
def test_empty_membership_records_require_an_explicit_identity_namespace(name):
    record_type = model().RECORD_TYPES[name]
    values = {key: value for key, value in record_values()[name].items() if key != "workspace_id"}
    for field in (
        "assertion_version_ids",
        "revision_ids",
        "link_generation_ids",
        "input_revision_ids",
        "sources",
    ):
        if field in values:
            values[field] = ()
    with pytest.raises(ValidationError, match="workspace_id"):
        record_type(**values)
    first = record_type(**values, workspace_id="workspace-a")
    second = record_type(**values, workspace_id="workspace-b")
    assert first.id != second.id
    assert "workspace_id" in first.identity_fields


def test_ids_are_derived_and_records_are_deeply_immutable():
    m = model()
    policy = m.AccessPolicy(workspace_id="w", mode="restricted", allow_users=("u",), verified_at=NOW)
    with pytest.raises(ValidationError):
        policy.allow_users = ("v",)
    with pytest.raises(ValidationError):
        m.AccessPolicy(workspace_id="w", mode="restricted", allow_users=["u"], verified_at=NOW)
    with pytest.raises(ValidationError):
        m.GenerationMember(id="made-up", generation_id="g", artifact_revision_id="r")
    assert (
        m.GenerationMember(generation_id="g", artifact_revision_id="r").id
        == m.GenerationMember(generation_id="g", artifact_revision_id="r").id
    )
    assert (
        m.GenerationMember(generation_id="g", artifact_revision_id="r").id
        != m.GenerationMember(generation_id="g", artifact_revision_id="other").id
    )
    revision = m.ArtifactRevision(
        artifact_id="a",
        content_hash="h",
        raw_uri="blob:a",
        observed_at=NOW,
        lifecycle="active",
        metadata_json='{"b":2,"a":1}',
    )
    assert revision.metadata_json == '{"a":1,"b":2}'
    assert isinstance(revision.metadata_json, str)
    with pytest.raises(ValidationError):
        m.Workspace(name="w", injected=True)


def test_locator_validation_preserves_real_coordinates():
    m = model()
    locator = TypeAdapter(m.SourceLocator)
    assert locator.validate_python({"kind": "file_lines", "path": "a.py", "start": 2, "end": 4}).start == 2
    assert (
        locator.validate_python(
            {
                "kind": "diff_hunk",
                "path": "a.py",
                "base_revision": "a",
                "head_revision": "b",
                "side": "base",
                "start": 2,
                "end": 4,
            }
        ).side
        == "base"
    )
    for value in [
        {"kind": "file_lines", "path": "../private", "start": 1, "end": 2},
        {"kind": "file_lines", "path": "a", "start": 0, "end": 2},
        {"kind": "file_lines", "path": "a", "start": 3, "end": 2},
        {"kind": "page", "page": 0},
        {"kind": "invented"},
        {"kind": "field", "field_path": "description", "invented": 1},
    ]:
        with pytest.raises(ValidationError):
            locator.validate_python(value)


def test_span_validates_locator_json_and_exact_text_hash():
    m = model()
    span = m.EvidenceSpan(
        revision_id="r",
        locator_kind="file_lines",
        locator_json='{"kind":"file_lines","path":"a.py","start":1,"end":2}',
        text="hello",
        policy_id="p",
    )
    assert len(span.text_hash) == 64
    with pytest.raises(ValidationError):
        m.EvidenceSpan(
            revision_id="r", locator_kind="page", locator_json=span.locator_json, text="hello", policy_id="p"
        )
    with pytest.raises(ValidationError):
        m.EvidenceSpan(
            revision_id="r",
            locator_kind="file_lines",
            locator_json=span.locator_json,
            text="hello",
            text_hash="wrong",
            policy_id="p",
        )


def test_temporal_versions_require_aware_instants_and_positive_half_open_intervals():
    m = model()
    values = dict(
        assertion_id="a",
        evidence_class="declared",
        rule_version="v1",
        confidence=1.0,
        status="active",
        validity_kind="explicit_interval",
        valid_from=NOW,
        recorded_from=NOW,
        temporal_basis="source_explicit",
        temporal_precision="instant",
    )
    good = m.AssertionVersion(**values)
    assert good.valid_to is None and good.recorded_to is None
    assert good.model_dump(mode="json")["valid_from"].endswith("Z")
    for change in [
        {"valid_to": NOW},
        {"recorded_to": NOW - timedelta(seconds=1)},
        {"recorded_from": NOW.replace(tzinfo=None)},
        {"confidence": 1.1},
        {"confidence": float("nan")},
        {"confidence": True},
    ]:
        with pytest.raises(ValidationError):
            m.AssertionVersion(**(values | change))
    obs = m.ObjectObservation(
        object_id="o",
        revision_id="r",
        span_id="s",
        evidence_class="declared",
        recorded_from=NOW,
        validity_kind="unknown",
    )
    assert obs.valid_from is None and obs.valid_to is None
    assert "recorded_to" in obs.model_dump()


def test_support_groups_require_every_member_but_accept_independent_groups():
    m = model()
    support = m.SupportGroups(
        groups=(
            m.SupportGroup(derivation_group="mapped", span_ids=("code", "private-manifest")),
            m.SupportGroup(derivation_group="direct", span_ids=("public-declaration",)),
        )
    )
    assert not support.satisfied_by(frozenset({"code"}))
    assert support.satisfied_by(frozenset({"code", "private-manifest"}))
    assert support.satisfied_by(frozenset({"public-declaration"}))
    with pytest.raises(ValidationError):
        m.SupportGroup(derivation_group="empty", span_ids=())
    with pytest.raises(ValidationError):
        m.SupportGroups(groups=())


def test_predicates_validate_real_object_endpoints_and_fk_mapping():
    m = model()
    p = importlib.import_module("hippo.knowledge.predicates")
    assert len(p.PREDICATES) == 32
    for definition in p.PREDICATES.values():
        assert definition.subject_kinds and definition.object_kinds
        assert definition.support_required
        assert definition.direction in {"forward", "both"}
    symbol = m.KnowledgeObject(workspace_id="w", kind="symbol", canonical_key='["repo","f"]')
    table = m.KnowledgeObject(workspace_id="w", kind="table", canonical_key='["db","t"]')
    assertion = m.checked_assertion(symbol, "WRITES_TABLE", table, scope_key="prod")
    assert assertion.subject_id == symbol.id
    with pytest.raises(ValueError):
        m.checked_assertion(table, "WRITES_TABLE", symbol, scope_key="prod")
    with pytest.raises(ValidationError):
        m.Assertion(
            workspace_id="w", subject_id=symbol.id, predicate="MADE_UP", object_id=table.id, scope_key="prod"
        )
    alien = m.KnowledgeObject(workspace_id="other", kind="table", canonical_key='["db","t"]')
    with pytest.raises(ValueError):
        m.checked_assertion(symbol, "WRITES_TABLE", alien, scope_key="prod")
    fk = m.ForeignKeyMapping(
        constraint_id="constraint",
        source_table_id="child",
        target_table_id="parent",
        columns=(
            m.ColumnPair(source_column_id="child.tenant", target_column_id="parent.tenant"),
            m.ColumnPair(source_column_id="child.key", target_column_id="parent.key"),
        ),
    )
    assert fk.columns[0].source_column_id == "child.tenant"
    with pytest.raises(ValidationError):
        m.ForeignKeyMapping(
            constraint_id="constraint", source_table_id="child", target_table_id="parent", columns=()
        )


def test_temporal_selector_is_discriminated_and_rejects_contradictions():
    m = model()
    selector = TypeAdapter(m.TemporalSelector)
    as_of = selector.validate_python({"mode": "as_of", "valid_at": NOW, "known_at": NOW})
    assert as_of.valid_at == NOW
    assert (
        selector.validate_json(
            '{"mode":"during","valid_during":{"start":"2026-01-01T00:00:00Z","end":"2026-02-01T00:00:00Z"},"interval_predicate":"throughout"}'
        ).interval_predicate
        == "throughout"
    )
    assert selector.json_schema()["discriminator"]["propertyName"] == "mode"
    for value in [
        {"mode": "current", "valid_at": NOW},
        {"mode": "as_of"},
        {"mode": "during", "valid_during": {"start": NOW, "end": NOW}},
        {"mode": "changes", "changes_since": NOW, "changes_until": NOW},
        {"mode": "current", "timezone": "Made/Up"},
        {"mode": "compare", "left": {"mode": "current"}},
        {"mode": "other"},
    ]:
        with pytest.raises(ValidationError):
            selector.validate_python(value)


def test_query_budgets_and_versioned_wire_roundtrips():
    m = model()
    request = m.QueryRequest(
        question="Who owns refunds?", mode="auto", temporal=m.CurrentSelector(), budget=m.QueryBudget()
    )
    envelope = m.QueryEnvelope(payload=request)
    serialized = envelope.model_dump_json()
    assert m.QueryEnvelope.model_validate_json(serialized) == envelope
    assert envelope.version == 1
    for value in [0, -1, True, 1.1, 100_000_000]:
        with pytest.raises(ValidationError):
            m.QueryBudget(max_evidence_tokens=value)
    with pytest.raises(ValidationError):
        m.QueryEnvelope.model_validate_json(serialized.replace('"version":1', '"version":2'))
    with pytest.raises(ValidationError):
        m.QueryRequest(question="q", mode="invented")
    with pytest.raises(ValidationError):
        m.QueryRequest(question="q", snapshot_id="one", temporal=m.CurrentSelector(snapshot_id="two"))
    workspace = m.Workspace(name="default")
    wire = m.EvidenceEnvelope(record_type="Workspace", payload=workspace)
    assert m.EvidenceEnvelope.model_validate_json(wire.model_dump_json()) == wire
    with pytest.raises(ValidationError):
        m.EvidenceEnvelope(record_type="Artifact", payload=workspace)


def record_values():
    """Valid smallest store payloads for every required persisted record."""
    return {
        "Workspace": dict(name="commerce"),
        "WorkspaceMembership": dict(
            workspace_id="w",
            principal_id="u",
            enabled=True,
            mapping_authority="reviewed-map-v1",
            policy_epoch=1,
        ),
        "GroupMembership": dict(
            workspace_id="w",
            group_id="g",
            principal_id="u",
            enabled=True,
            mapping_authority="reviewed-map-v1",
            policy_epoch=1,
        ),
        "Connector": dict(
            workspace_id="w", kind="github", instance_url="https://github.example", enabled=True
        ),
        "Artifact": dict(
            workspace_id="w",
            source_id="s",
            kind="ticket",
            external_id="42",
            canonical_uri="https://jira.example/42",
            policy_id="p",
        ),
        "ArtifactRevision": dict(
            artifact_id="a", content_hash="h", raw_uri="blob:a", observed_at=NOW, lifecycle="active"
        ),
        "Generation": dict(
            source_id="s",
            status="staging",
            parser_version="p1",
            linker_version="l1",
            embedding_profile="e1",
            created_at=NOW,
            manifest_hash="m",
        ),
        "GenerationMember": dict(generation_id="g", artifact_revision_id="r"),
        "EvidenceSpan": dict(
            revision_id="r",
            locator_kind="field",
            locator_json='{"kind":"field","field_path":"description"}',
            text="hello",
            policy_id="p",
        ),
        "KnowledgeObject": dict(workspace_id="w", kind="commit", canonical_key='["repo","sha"]'),
        "ObjectObservation": dict(
            object_id="o", revision_id="r", span_id="s", evidence_class="declared", recorded_from=NOW
        ),
        "Assertion": dict(
            workspace_id="w", subject_id="review", predicate="MERGED_AS", object_id="commit", scope_key="repo"
        ),
        "AssertionVersion": dict(
            assertion_id="a",
            evidence_class="declared",
            rule_version="v1",
            confidence=1.0,
            status="active",
            recorded_from=NOW,
        ),
        "AssertionSupport": dict(assertion_version_id="v", span_id="s", derivation_group="direct"),
        "NativeBinding": dict(
            generation_id="g", object_id="o", native_kind="Commit", native_id="old-commit", span_id="s"
        ),
        "AccessPolicy": dict(workspace_id="w", verified_at=NOW),
        "SyncState": dict(connector_id="c", partition_key="repo"),
        "SyncRun": dict(
            connector_id="c",
            source_id="s",
            scope_key="repo",
            phase="queued",
            run_key="run",
            input_fingerprint="f",
        ),
        "MaintenanceJob": dict(
            source_id="s", scope_key="repo", phase="queued", kind="sync", job_key="job", input_fingerprint="f"
        ),
        "SourceEvent": dict(
            connector_id="c",
            artifact_id="a",
            provider_instance="https://git.example",
            provider_artifact_id="42",
            delivery_id="d",
            operation="upsert",
            received_at=NOW,
            payload_hash="h",
            dedupe_key="k",
        ),
        "IndexManifest": dict(
            generation_id="g",
            profile_fingerprint="p",
            config_fingerprint="c",
            required_representations=(),
            checksums=(),
            ready=False,
        ),
        "LinkGeneration": dict(
            workspace_id="w",
            input_manifest_hash="h",
            linker_version="v1",
            assertion_version_ids=("a",),
            created_at=NOW,
        ),
        "HistoryManifest": dict(
            workspace_id="w",
            revision_ids=("r",),
            assertion_version_ids=("a",),
            link_generation_ids=("l",),
            knowledge_cutoff=NOW,
            temporal_selector_json='{"mode":"current"}',
        ),
        "DerivedRecord": dict(
            workspace_id="w",
            view_kind="summary",
            rule_version="r",
            input_revision_ids=("r",),
            dependency_fingerprint="d",
            state="dirty",
        ),
        "DerivedDependency": dict(
            derived_record_id="d", input_kind="revision", input_id="r", input_version="v"
        ),
        "Suppression": dict(
            workspace_id="w",
            target_kind="artifact",
            target_id="a",
            scope_key="repo",
            view_applicability="all_history",
            reason="access_loss",
            epoch=1,
            created_at=NOW,
            restoration_barrier="canonical-reverify",
        ),
        "PurgeJob": dict(
            workspace_id="w",
            scope_key="repo",
            request_key="request",
            phase="suppress",
            removal_manifest_ids=("a",),
            raw_status="pending",
            derived_status="pending",
            saved_output_status="pending",
            backup_disposition="pending",
            audit_code="user-request",
            created_at=NOW,
        ),
        "IndexEvent": dict(
            workspace_id="w", kind="published", aggregate_id="s", sequence=1, dedupe_key="k", created_at=NOW
        ),
        "ConsumerAck": dict(event_id="e", consumer_id="lexical", state="pending"),
        "RetrievalView": dict(
            span_id="s",
            view_kind="lexical",
            text="hello",
            text_profile="v1",
            source_revision_id="r",
            derivation_version="v1",
            dependency_fingerprint="d",
        ),
        "Section": dict(
            source_revision_id="r",
            original_heading="Refunds",
            ordinal=0,
            breadcrumb=("Billing",),
            original_span_ids=("s",),
        ),
        "SectionMember": dict(section_id="section", child_id="span", child_kind="span", ordinal=0),
        "ConflictSet": dict(
            workspace_id="w",
            scope_key="owner",
            assertion_version_ids=("a", "b"),
            resolution_status="unresolved",
            support_span_ids=("s",),
        ),
        "Alias": dict(
            workspace_id="w",
            namespace="jira",
            alias_key="PROJ-42",
            target_object_id="ticket",
            authority="provider",
            support_span_ids=("s",),
            status="explicit",
        ),
        "QuerySnapshot": dict(
            workspace_id="w",
            sources=(),
            knowledge_cutoff=NOW,
            temporal={"mode": "current"},
            profile_fingerprint="p",
            settings_fingerprint="s",
            policy_fingerprint="acl",
            suppression_epoch=0,
            created_at=NOW,
        ),
    }


@pytest.mark.parametrize("name", record_values())
def test_every_persisted_record_roundtrips_without_type_or_optional_shape_loss(name):
    m = model()
    record = m.RECORD_TYPES[name](**record_values()[name])
    assert record.id != "pending"
    assert m.RECORD_TYPES[name].model_validate_json(record.model_dump_json()) == record
    wire = m.EvidenceEnvelope(record_type=name, payload=record)
    assert m.EvidenceEnvelope.model_validate_json(wire.model_dump_json()) == wire
    assert (
        m.EvidenceEnvelope.model_validate_json(wire.model_dump_json()).payload.model_dump()
        == record.model_dump()
    )


def test_replacements_validate_and_lifecycle_state_does_not_change_identity():
    m = model()
    cases = [
        ("MaintenanceJob", {"phase": "fetch", "attempt_count": 2}),
        ("SourceEvent", {"acceptance_state": "accepted"}),
        ("ConsumerAck", {"state": "running", "attempt_count": 1}),
        ("Generation", {"status": "active", "published_at": NOW}),
        ("Connector", {"enabled": False, "config_json": '{"new":true}'}),
        ("AccessPolicy", {"verified_at": NOW + timedelta(seconds=1)}),
        ("AssertionVersion", {"recorded_to": NOW + timedelta(seconds=1)}),
    ]
    for name, changes in cases:
        original = m.RECORD_TYPES[name](**record_values()[name])
        assert original.replace(**changes).id == original.id
    budget = m.QueryBudget()
    with pytest.raises(ValidationError):
        budget.replace(max_hops=-1)
    with pytest.raises(ValidationError):
        budget.model_copy(update={"max_hops": -1})
    assert budget.model_copy() == budget
    with pytest.raises(ValidationError):
        m.QueryEnvelope(version=True, payload=m.QueryRequest(question="q"))
    with pytest.raises(ValidationError):
        m.EvidenceEnvelope(version=True, record_type="Workspace", payload=m.Workspace(name="w"))
    with pytest.raises(ValidationError):
        m.WorkspaceMembership(**(record_values()["WorkspaceMembership"] | {"policy_epoch": True}))


@pytest.mark.parametrize(
    "name,changes",
    [
        ("Generation", {"status": "active"}),
        ("AccessPolicy", {"expires_at": NOW}),
        ("MaintenanceJob", {"lease_owner": "worker"}),
        ("MaintenanceJob", {"lease_owner": "worker", "lease_expires_at": NOW}),
        ("ConsumerAck", {"state": "acknowledged"}),
        ("ConsumerAck", {"lease_expires_at": NOW}),
        ("SourceEvent", {"operation": "execute_sql"}),
        ("IndexManifest", {"ready": True, "required_representations": ("dense",)}),
        ("Suppression", {"view_applicability": "current_only"}),
        ("Suppression", {"all_principals": False}),
        ("PurgeJob", {"phase": "complete"}),
        ("PurgeJob", {"completed_at": NOW - timedelta(seconds=1)}),
        ("HistoryManifest", {"temporal_selector_json": '{"mode":"invented"}'}),
        ("ConflictSet", {"assertion_version_ids": ("a", "a")}),
        ("ConflictSet", {"resolution_status": "resolved"}),
        ("Section", {"original_span_ids": ()}),
        ("Alias", {"support_span_ids": ()}),
    ],
)
def test_lifecycle_records_reject_inconsistent_state(name, changes):
    m = model()
    with pytest.raises(ValidationError):
        m.RECORD_TYPES[name](**(record_values()[name] | changes))


def test_records_retain_their_canonical_identity_key_and_reject_mismatch():
    m = model()
    record = m.GenerationMember(generation_id="g", artifact_revision_id="r")
    assert record.identity_key == '["g","r"]'
    with pytest.raises(ValidationError):
        m.GenerationMember(generation_id="g", artifact_revision_id="r", identity_key='["other"]')
    remote = m.Artifact(
        **(
            record_values()["Artifact"]
            | {"connector_id": "connector", "provider_instance": "https://provider.example"}
        )
    )
    assert remote.replace(source_id="moved-to-another-logical-source").id == remote.id
    local = m.Artifact(**record_values()["Artifact"])
    assert local.replace(source_id="another-local-source").id != local.id


def test_error_and_purge_audit_fields_are_codes_not_untrusted_messages():
    m = model()
    for name, field in [
        ("SyncState", "error_code"),
        ("MaintenanceJob", "error_code"),
        ("PurgeJob", "audit_code"),
    ]:
        with pytest.raises(ValidationError):
            m.RECORD_TYPES[name](
                **(record_values()[name] | {field: "Failure: secret source content from /private/path"})
            )


def test_evidence_envelope_revalidates_unsafe_constructed_objects():
    m = model()
    forged = m.Workspace.model_construct(name="x", id="forged")
    with pytest.raises(ValidationError):
        m.EvidenceEnvelope(record_type="Workspace", payload=forged)


def test_support_and_fk_duplicate_members_are_rejected():
    m = model()
    with pytest.raises(ValidationError):
        m.SupportGroup(derivation_group="d", span_ids=("s", "s"))
    group = m.SupportGroup(derivation_group="d", span_ids=("s",))
    with pytest.raises(ValidationError):
        m.SupportGroups(groups=(group, group))
    pair = m.ColumnPair(source_column_id="a", target_column_id="b")
    with pytest.raises(ValidationError):
        m.ForeignKeyMapping(
            constraint_id="fk", source_table_id="a", target_table_id="b", columns=(pair, pair)
        )


def test_all_query_modes_valid_temporal_variants_and_snapshot_membership():
    m = model()
    variants = [
        m.CurrentSelector(),
        m.AsOfSelector(valid_at=NOW),
        m.DuringSelector(
            valid_during=m.TimeInterval(start=NOW, end=NOW + timedelta(days=1)), interval_predicate="overlaps"
        ),
        m.ChangesSelector(changes_since=NOW, changes_until=NOW + timedelta(days=1)),
        m.AtemporalSelector(),
        m.CompareSelector(left=m.CurrentSelector(), right=m.AsOfSelector(valid_at=NOW)),
    ]
    for temporal in variants:
        for mode in ("legacy", "hybrid", "schema", "code", "traceability", "overview", "auto"):
            request = m.QueryEnvelope(payload=m.QueryRequest(question="q", mode=mode, temporal=temporal))
            assert m.QueryEnvelope.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError):
        m.QuerySnapshot(
            **(
                record_values()["QuerySnapshot"]
                | {
                    "sources": (
                        m.SnapshotSource(source_id="s", generation_id="a"),
                        m.SnapshotSource(source_id="s", generation_id="b"),
                    )
                }
            )
        )
    with pytest.raises(ValidationError):
        m.CompareSelector(
            left=m.AsOfSelector(valid_at=NOW, known_at=NOW),
            right=m.CurrentSelector(),
            known_at=NOW + timedelta(days=1),
        )


@pytest.mark.parametrize("owner_kind", ["team", "person"])
def test_ownership_supports_normalized_team_and_person_kinds(owner_kind):
    m = model()
    service = m.KnowledgeObject(workspace_id="w", kind="service", canonical_key='["catalog","service"]')
    owner = m.KnowledgeObject(workspace_id="w", kind=owner_kind, canonical_key='["directory","owner"]')
    assert m.checked_assertion(service, "OWNED_BY", owner, scope_key="prod").object_id == owner.id


def test_public_identity_helpers_construct_the_corresponding_records():
    m = model()
    i = importlib.import_module("hippo.knowledge.identity")
    artifact_id = i.artifact_identity("w", "https://GIT.example:443/", "ticket", "42")
    artifact = m.Artifact(
        id=artifact_id,
        workspace_id="w",
        source_id="s",
        connector_id="c",
        provider_instance="https://git.example",
        kind="ticket",
        external_id="42",
        canonical_uri="https://git.example/42",
        policy_id="p",
    )
    assert artifact.id == artifact_id
    identifier = i.sql_identifier("Orders", dialect="postgres")
    cases = [
        (
            "table",
            i.database_object_key("db", "prod", "catalog", "public", [identifier]),
            i.database_object_identity("w", "db", "prod", "catalog", "public", [identifier], "table"),
        ),
        (
            "service",
            i.service_key("https://catalog", "component:commerce/billing"),
            i.service_identity("w", "https://catalog", "component:commerce/billing"),
        ),
        (
            "repository",
            i.repository_key("https://git", "repo"),
            i.repository_identity("w", "https://git", "repo"),
        ),
        (
            "review",
            i.review_key("https://git", "repo", "42"),
            i.review_identity("w", "https://git", "repo", "42"),
        ),
        (
            "symbol",
            i.symbol_key("repo", "python", "a.py", "f", "(int)", kind="function"),
            i.symbol_identity("repo", "python", "a.py", "f", "(int)", kind="function", workspace="w"),
        ),
        (
            "endpoint",
            i.endpoint_key("svc", "http", "v1", "GET", "/refunds", api_identity="api"),
            i.endpoint_identity("svc", "http", "v1", "GET", "/refunds", api_identity="api", workspace="w"),
        ),
    ]
    for kind, key, identifier in cases:
        assert (
            m.KnowledgeObject(
                id=identifier, workspace_id="w", kind=kind, canonical_key=i.canonical_json(key)
            ).id
            == identifier
        )
    revision_id = i.revision_identity(artifact.id, "r1", "hash")
    revision = m.ArtifactRevision(
        id=revision_id,
        artifact_id=artifact.id,
        provider_revision="r1",
        content_hash="hash",
        raw_uri="blob:r1",
        observed_at=NOW,
        lifecycle="active",
    )
    locator = {"kind": "field", "field_path": "description"}
    span_id = i.span_identity(revision.id, locator, i.text_hash("hello"))
    assert (
        m.EvidenceSpan(
            id=span_id,
            revision_id=revision.id,
            locator_kind="field",
            locator_json=i.canonical_json(locator),
            text="hello",
            policy_id="p",
        ).id
        == span_id
    )


def test_local_artifact_factory_enforces_root_and_canonical_path(tmp_path):
    m = model()
    i = importlib.import_module("hippo.knowledge.identity")
    artifact = m.local_artifact(
        workspace_id="w", source_id="s", root=tmp_path, path="folder/./file.sql", policy_id="p"
    )
    assert artifact.external_id == "folder/file.sql"
    assert artifact.id == i.local_artifact_identity("w", "s", tmp_path, "folder/file.sql")
    (tmp_path / "escape").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        m.local_artifact(workspace_id="w", source_id="s", root=tmp_path, path="escape/private", policy_id="p")


def test_span_stores_and_hashes_the_canonical_typed_locator():
    m = model()
    identity = importlib.import_module("hippo.knowledge.identity")
    for locator_kind, first, second in [
        (
            "file_lines",
            {"kind": "file_lines", "path": "a/./b.py", "start": 1, "end": 2},
            {"kind": "file_lines", "path": "a/b.py", "start": 1, "end": 2},
        ),
        (
            "page",
            {"kind": "page", "page": 1},
            {"kind": "page", "page": 1, "offset_start": 0, "offset_end": None},
        ),
    ]:
        original = m.EvidenceSpan(
            revision_id="r",
            locator_kind=locator_kind,
            locator_json=identity.canonical_json(first),
            text="hello",
            policy_id="p",
        )
        equivalent = m.EvidenceSpan(
            revision_id="r",
            locator_kind=locator_kind,
            locator_json=identity.canonical_json(second),
            text="hello",
            policy_id="p",
        )
        assert original == equivalent
        assert original.locator_json == identity.canonical_json(second)
        assert original.id == identity.span_identity("r", first, identity.text_hash("hello"))


@pytest.mark.parametrize("name", ["HistoryManifest", "QuerySnapshot"])
@pytest.mark.parametrize(
    "selector",
    [
        {"mode": "as_of", "valid_at": "2026-09-11T12:00:00Z", "known_at": "2026-09-10T12:00:00Z"},
        {
            "mode": "compare",
            "left": {"mode": "as_of", "valid_at": "2026-09-11T12:00:00Z", "known_at": "2026-09-10T12:00:00Z"},
            "right": {"mode": "current"},
        },
        {
            "mode": "compare",
            "known_at": "2026-09-10T12:00:00Z",
            "left": {"mode": "current"},
            "right": {"mode": "current"},
        },
    ],
)
def test_manifest_knowledge_cutoff_rejects_contradictory_selector(name, selector):
    m = model()
    identity = importlib.import_module("hippo.knowledge.identity")
    change = (
        {"temporal_selector_json": identity.canonical_json(selector)}
        if name == "HistoryManifest"
        else {"temporal": TypeAdapter(m.TemporalSelector).validate_json(identity.canonical_json(selector))}
    )
    with pytest.raises(ValidationError):
        m.RECORD_TYPES[name](**(record_values()[name] | change))


@pytest.mark.parametrize("name", ["HistoryManifest", "QuerySnapshot"])
@pytest.mark.parametrize("known_at", [None, "2026-09-11T12:00:00Z"])
def test_manifest_allows_matching_or_default_latest_knowledge_cutoff(name, known_at):
    m = model()
    identity = importlib.import_module("hippo.knowledge.identity")
    selector = {"mode": "as_of", "valid_at": "2026-09-11T12:00:00Z", "known_at": known_at}
    change = (
        {"temporal_selector_json": identity.canonical_json(selector)}
        if name == "HistoryManifest"
        else {"temporal": TypeAdapter(m.TemporalSelector).validate_json(identity.canonical_json(selector))}
    )
    assert m.RECORD_TYPES[name](**(record_values()[name] | change)).knowledge_cutoff == NOW


@pytest.mark.parametrize("kind", ["active_query", "saved", "retained"])
def test_snapshot_reference_roundtrip_identity_and_lease_contract(kind):
    m = model()
    lease = (
        dict(lease_owner="reader", lease_expires_at=NOW + timedelta(minutes=1))
        if kind == "active_query"
        else {}
    )
    ref = m.SnapshotReference(
        workspace_id="w", snapshot_id="snapshot", kind=kind, reference_key="request", created_at=NOW, **lease
    )
    assert m.SnapshotReference.model_validate_json(ref.model_dump_json()) == ref
    assert ref.replace(created_at=NOW - timedelta(seconds=1)).id == ref.id
    assert ref.replace(reference_key="another").id != ref.id
    with pytest.raises(ValidationError):
        if kind == "active_query":
            ref.replace(lease_expires_at=NOW)
        else:
            ref.replace(lease_owner="reader", lease_expires_at=NOW + timedelta(minutes=1))
    with pytest.raises(ValidationError):
        ref.replace(released_at=NOW - timedelta(seconds=1))


def test_generation_evidence_membership_roundtrips_and_rejects_arbitrary_labels():
    m = model()
    member = m.GenerationEvidenceMember(generation_id="g", record_kind="EvidenceSpan", record_id="span")
    assert m.GenerationEvidenceMember.model_validate_json(member.model_dump_json()) == member
    assert member.replace(generation_id="new").id != member.id
    with pytest.raises(ValidationError):
        member.replace(record_kind="User")
    with pytest.raises(ValidationError):
        member.replace(record_kind="EvidenceSpan) DETACH DELETE n")


def history_manifest(m, **changes):
    fields = dict(
        workspace_id="w",
        revision_ids=("revision-a", "revision-b"),
        assertion_version_ids=("version-a",),
        link_generation_ids=(),
        knowledge_cutoff=NOW,
        temporal_selector_json='{"mode":"current"}',
    )
    return m.HistoryManifest(**(fields | changes))


def test_history_manifest_requires_sorted_unique_ids_and_keeps_open_selectors():
    m = model()
    manifest = history_manifest(m)
    assert manifest.retention_gaps == ()
    assert m.HistoryManifest.model_validate_json(manifest.model_dump_json()) == manifest
    for field, value in (
        ("revision_ids", ("revision-b", "revision-a")),
        ("revision_ids", ("revision-a", "revision-a")),
        ("assertion_version_ids", ("version-b", "version-a")),
        ("link_generation_ids", ("link-b", "link-a")),
        ("retention_gaps", ("gap-b", "gap-a")),
        ("retention_gaps", ("gap-a", "gap-a")),
    ):
        with pytest.raises(ValidationError, match="sorted and unique"):
            history_manifest(m, **{field: value})


def test_every_pinned_selector_mode_carries_the_knowledge_cutoff_it_was_resolved_at():
    m = model()
    later = NOW + timedelta(days=1)
    for pinned in (m.CurrentSelector(known_at=NOW), m.AtemporalSelector(known_at=NOW)):
        assert TypeAdapter(m.TemporalSelector).validate_json(pinned.model_dump_json()) == pinned
        manifest = history_manifest(m, temporal_selector_json=pinned.model_dump_json())
        assert manifest.knowledge_cutoff == NOW
        snapshot = m.QuerySnapshot(**(record_values()["QuerySnapshot"] | {"temporal": pinned}))
        assert snapshot.temporal.known_at == NOW
        with pytest.raises(ValidationError, match="contradicts its temporal selector"):
            history_manifest(m, temporal_selector_json=pinned.model_dump_json(), knowledge_cutoff=later)
        with pytest.raises(ValidationError, match="contradicts its temporal selector"):
            m.QuerySnapshot(
                **(record_values()["QuerySnapshot"] | {"temporal": pinned, "knowledge_cutoff": later})
            )


def conflict_set(m, **changes):
    fields = dict(
        workspace_id="w",
        scope_key="prod",
        assertion_version_ids=("version-a", "version-b"),
        resolution_status="possible",
        support_span_ids=("span-a", "span-b"),
    )
    return m.ConflictSet(**(fields | changes))


def test_conflict_set_requires_sorted_unique_ids_and_a_proven_lower_bound():
    m = model()
    conflict = conflict_set(m)
    assert conflict.valid_from is None and conflict.valid_to is None
    assert conflict_set(m, valid_from=NOW, resolution_status="unresolved").valid_to is None
    for field, value in (
        ("assertion_version_ids", ("version-b", "version-a")),
        ("support_span_ids", ("span-b", "span-a")),
        ("support_span_ids", ("span-a", "span-a")),
    ):
        with pytest.raises(ValidationError, match="sorted and unique"):
            conflict_set(m, **{field: value})
    with pytest.raises(ValidationError, match="proven lower bound"):
        conflict_set(m, valid_to=NOW)
    with pytest.raises(ValidationError, match="reversed or empty"):
        conflict_set(m, valid_from=NOW, valid_to=NOW)
