"""Policy scope identities and additive v2-to-v3 migration compatibility."""

from datetime import UTC, datetime, timedelta

import pytest

from hippo.knowledge import model as k
from hippo.knowledge.identity import make_identity
from hippo.store import migrations as m

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
V2_CHECKSUM = "f4419a33c505b28fc7239c6aa6ac323c9bbcb926159df457c2a3876f0bbc5b0f"


def test_legacy_policy_ids_remain_readable_without_assuming_curated_origin():
    old_parts = ["workspace", "restricted", ["alice"], [], [], []]
    old_id = make_identity("accesspolicy", old_parts)
    policy = k.AccessPolicy(
        id=old_id, workspace_id="workspace", mode="restricted", allow_users=("alice",), verified_at=NOW
    )
    assert policy.id == old_id
    assert policy.origin == "legacy_unknown"
    assert policy.scope_key is None


def test_policy_scope_and_origin_separate_ids_but_freshness_does_not():
    first = k.AccessPolicy(
        workspace_id="workspace",
        mode="restricted",
        allow_users=("alice",),
        verified_at=NOW,
        origin="provider",
        scope_key="jira:instance/project-A",
    )
    second = first.replace(scope_key="jira:instance/project-B")
    curated = first.replace(origin="local_curated")
    refreshed = first.replace(verified_at=NOW + timedelta(seconds=1))
    assert len({first.id, second.id, curated.id}) == 3
    assert refreshed.id == first.id


@pytest.mark.parametrize(
    "origin,scope", [("provider", None), ("local_curated", ""), ("legacy_unknown", "scope")]
)
def test_policy_origin_requires_an_unambiguous_scope(origin, scope):
    with pytest.raises(ValueError):
        k.AccessPolicy(workspace_id="workspace", verified_at=NOW, origin=origin, scope_key=scope)


def test_v2_descriptor_and_checksum_are_frozen():
    from hippo.knowledge.identity import canonical_json, text_hash

    assert m.V2_CHECKSUM == V2_CHECKSUM
    assert text_hash(canonical_json(m.V2_DESCRIPTOR)) == V2_CHECKSUM
    assert "origin" not in m.V2_DESCRIPTOR[1]["AccessPolicy"]
    assert m.CURRENT_SCHEMA_VERSION == 3
    assert m.MIGRATION_CHECKSUM != V2_CHECKSUM


def v2_fixture(path, monkeypatch):
    """Create actual pre-upgrade columns, then seed an old identity and its evidence."""
    from hippo.store.ladybug import LadybugStore

    with monkeypatch.context() as patch:
        patch.setattr(LadybugStore, "ensure_schema", LadybugStore._ensure_legacy_schema)
        store = LadybugStore(path)
    store._migrating = True
    with store.transaction():
        store.run(
            "CREATE NODE TABLE SchemaVersion(id STRING PRIMARY KEY, version INT64, checksum STRING, state STRING, step INT64)"
        )
        m._record_legacy_version(store)
        for statement in m.schema_steps(store, version=2):
            store.run(statement)
        m._data_transform(store, version=2)
        m._version(store, "complete", len(m.schema_steps(store, version=2)), version=2)
    source = store.create_source("file", "existing.sql")
    policy = k.AccessPolicy(workspace_id=m.DEFAULT_WORKSPACE_ID, mode="workspace", verified_at=NOW)
    store.run(
        "CREATE (:AccessPolicy {id:$id,identity_key:decode($key),workspace_id:$workspace,mode:'workspace',allow_users:[],allow_groups:[],deny_users:[],deny_groups:[],verified_at:$verified})",
        id=policy.id,
        key=policy.identity_key.encode(),
        workspace=policy.workspace_id,
        verified=NOW.replace(tzinfo=None),
    )
    artifact = k.Artifact(
        workspace_id=policy.workspace_id,
        source_id=source,
        kind="file",
        external_id="existing.sql",
        canonical_uri="source:existing.sql",
        policy_id=policy.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        content_hash="original",
        raw_uri="blob:original",
        observed_at=NOW,
        lifecycle="active",
    )
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="file_lines",
        locator_json='{"kind":"file_lines","path":"existing.sql","start":1,"end":1}',
        text="CREATE TABLE original(id INT)",
        policy_id=policy.id,
    )
    for record in (artifact, revision, span):
        store._write_knowledge(record)
    store._migrating = False
    store.close()
    return policy, artifact, span


def test_v2_policy_and_span_keep_ids_and_references_after_migration_and_reopen(tmp_path, monkeypatch):
    from hippo.store.ladybug import LadybugStore

    path = tmp_path / "v2.lbug"
    policy, artifact, span = v2_fixture(path, monkeypatch)
    for _ in range(2):
        store = LadybugStore(path)
        try:
            assert store._knowledge_get("AccessPolicy", policy.id) == policy
            assert store._knowledge_get("Artifact", artifact.id) == artifact
            assert store._knowledge_get("EvidenceSpan", span.id) == span
            assert store.schema_version()["version"] == 3
            assert {row["version"]: row["checksum"] for row in store.schema_history()} == {
                1: m.V1_CHECKSUM,
                2: V2_CHECKSUM,
                3: m.MIGRATION_CHECKSUM,
            }
            assert store.run("MATCH (p:AccessPolicy) RETURN p.origin AS origin,p.scope_key AS scope") == [
                {"origin": "legacy_unknown", "scope": None}
            ]
        finally:
            store.close()


@pytest.mark.parametrize("failure", ["schema:0", "schema:1", "data"])
def test_v3_failure_rolls_back_added_columns_and_policy_data_then_recovers(tmp_path, monkeypatch, failure):
    from hippo.store.ladybug import LadybugStore

    path = tmp_path / "rollback.lbug"
    policy, _, span = v2_fixture(path, monkeypatch)
    with monkeypatch.context() as patch:
        patch.setattr(LadybugStore, "ensure_schema", lambda self: None)
        store = LadybugStore(path)

    def fault(step):
        if step == failure:
            raise RuntimeError("injected v3 fault")

    try:
        with pytest.raises(RuntimeError, match="injected v3 fault"):
            m.migrate_store(store, fault_hook=fault)
        store._migrating = True
        assert store.schema_version()["version"] == 2
        assert "origin" not in {row["name"] for row in store.run("CALL table_info('AccessPolicy') RETURN *")}
        assert store._knowledge_get("EvidenceSpan", span.id).policy_id == policy.id
        store._migrating = False
        m.migrate_store(store)
        assert store.schema_version()["version"] == 3
    finally:
        store.close()


def test_new_store_keeps_all_migration_history_and_scope_freshness_is_independent(store):
    store.ensure_schema()
    assert [row["version"] for row in store.schema_history()] == [1, 2, 3]
    first = k.AccessPolicy(
        workspace_id=m.DEFAULT_WORKSPACE_ID, origin="provider", scope_key="provider:A", verified_at=NOW
    )
    second = first.replace(scope_key="provider:B")
    store._write_knowledge(first)
    store._write_knowledge(second)
    refreshed = first.replace(verified_at=NOW + timedelta(seconds=30))
    store._write_knowledge(refreshed)
    assert store._knowledge_get("AccessPolicy", first.id).verified_at == refreshed.verified_at
    assert store._knowledge_get("AccessPolicy", second.id).verified_at == NOW


@pytest.mark.parametrize("version", [1, 2])
def test_corrupt_historical_checksum_is_rejected_even_with_valid_v3_completion(store, version):
    store.ensure_schema()
    source = store.create_source("file", "untouched")
    if store.knowledge_backend == "fake":
        store._schema_history[version]["checksum"] = "corrupt-history"
    else:
        store.run(
            "MATCH (v:SchemaVersion {version:$version}) SET v.checksum='corrupt-history'", version=version
        )
    with pytest.raises(m.SchemaCompatibilityError, match="historical"):
        m.migrate_store(store)
    assert store._migration_blocked
    store._migrating = True
    try:
        assert store.get_source(source)["name"] == "untouched"
        assert store.schema_version()["version"] == 3
        assert (
            next(row for row in store.schema_history() if row["version"] == version)["checksum"]
            == "corrupt-history"
        )
    finally:
        store._migrating = False


def test_v3_transform_fault_keeps_legacy_policy_and_recovery_completes(store):
    """Also runs on Neo4j: the pending journal survives, the data transaction does not."""
    store.ensure_schema()
    policy = k.AccessPolicy(workspace_id=m.DEFAULT_WORKSPACE_ID, verified_at=NOW)
    store._write_knowledge(policy)
    if store.knowledge_backend == "fake":
        store._schema_history.pop(3)
        store._schema_row = dict(store._schema_history[2])
    else:
        store.run("MATCH (v:SchemaVersion {version:3}) DETACH DELETE v")

    def fault(step):
        if step == "data":
            raise RuntimeError("injected v3 transform fault")

    with pytest.raises(RuntimeError, match="injected v3 transform"):
        m.migrate_store(store, fault_hook=fault)
    store._migrating = True
    try:
        current = store.schema_version()
        if store.knowledge_backend == "neo4j":
            assert current["version"] == 3 and current["state"] == "pending"
        else:
            assert current["version"] == 2 and current["state"] == "complete"
        assert store._knowledge_get("AccessPolicy", policy.id) == policy
    finally:
        store._migrating = False
    m.migrate_store(store)
    assert [row["version"] for row in store.schema_history()] == [1, 2, 3]
    assert store.schema_version()["state"] == "complete"
    assert store._knowledge_get("AccessPolicy", policy.id) == policy


def change_journal(store, version, *, changes=None, delete=False):
    if store.knowledge_backend == "fake":
        if delete:
            store._schema_history.pop(version)
        else:
            store._schema_history[version].update(changes)
        store._schema_row = (
            dict(store._schema_history[max(store._schema_history)]) if store._schema_history else None
        )
        return
    if delete:
        store.run("MATCH (v:SchemaVersion {version:$version}) DETACH DELETE v", version=version)
    else:
        assignment = ",".join(f"v.{field}=${field}" for field in changes)
        store.run(
            f"MATCH (v:SchemaVersion {{version:$version}}) SET {assignment}", version=version, **changes
        )


@pytest.mark.parametrize(
    "damage",
    [
        "unknown_state",
        "missing_v1",
        "missing_v2",
        "prior_pending",
        "v1_pending",
        "negative_step",
        "excessive_step",
        "incomplete_completed",
        "missing_history",
        "duplicate_version",
    ],
)
def test_invalid_journal_is_rejected_before_policy_or_schema_mutation(store, damage):
    store.ensure_schema()
    policy = k.AccessPolicy(
        workspace_id=m.DEFAULT_WORKSPACE_ID,
        origin="provider",
        scope_key="provider:must-survive",
        verified_at=NOW,
    )
    store._write_knowledge(policy)
    if damage == "unknown_state":
        change_journal(store, 3, changes={"state": "corrupt"})
    elif damage.startswith("missing_v"):
        change_journal(store, int(damage[-1]), delete=True)
    elif damage == "prior_pending":
        change_journal(store, 2, changes={"state": "pending", "step": 0})
    elif damage == "v1_pending":
        change_journal(store, 1, changes={"state": "pending", "step": 0})
    elif damage == "incomplete_completed":
        change_journal(store, 2, changes={"step": 1})
    elif damage == "duplicate_version":
        if store.knowledge_backend == "fake":
            store._schema_history[99] = dict(store._schema_history[2])
        else:
            store.run(
                "CREATE (:SchemaVersion {id:'duplicate-v2',version:2,checksum:$checksum,state:'complete',step:$step})",
                checksum=m.V2_CHECKSUM,
                step=len(m.schema_steps(store, version=2)),
            )
    elif damage == "missing_history":
        for version in (3, 2, 1):
            change_journal(store, version, delete=True)
    else:
        change_journal(store, 3, changes={"step": -999 if damage == "negative_step" else 999})
    before = store.schema_history()
    with pytest.raises(m.SchemaCompatibilityError):
        m.migrate_store(store)
    store._migrating = True
    try:
        assert store.schema_history() == before
        assert store._knowledge_get("AccessPolicy", policy.id) == policy
    finally:
        store._migrating = False


@pytest.mark.parametrize("bad_step", [True, "0", 0.0])
def test_journal_steps_require_actual_integers(bad_step):
    from tests.fakes.fake_store import FakeStore

    store = FakeStore()
    store.ensure_schema()
    change_journal(store, 3, changes={"step": bad_step})
    with pytest.raises(m.SchemaCompatibilityError):
        m.migrate_store(store)


@pytest.mark.parametrize("position", ["start", "end"])
def test_pending_v3_recovery_never_rewrites_explicit_policy_identity(store, position):
    store.ensure_schema()
    policy = k.AccessPolicy(
        workspace_id=m.DEFAULT_WORKSPACE_ID,
        origin="provider",
        scope_key="provider:must-survive",
        verified_at=NOW,
    )
    store._write_knowledge(policy)
    step = 0 if position == "start" else len(m.schema_steps(store, version=3))
    change_journal(store, 3, changes={"state": "pending", "step": step})
    m.migrate_store(store)
    assert store.schema_version()["state"] == "complete"
    assert store._knowledge_get("AccessPolicy", policy.id) == policy
