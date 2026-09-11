"""Compatibility guards and crash recovery never rewrite inherited evidence/auth."""

import importlib

import pytest


def migrations():
    try:
        return importlib.import_module("hippo.store.migrations")
    except ModuleNotFoundError:
        pytest.fail("Task 3 versioned migration support is missing")


def test_schema_version_and_repeat_migration_are_idempotent(store):
    m = migrations()
    store.ensure_schema()
    before = store.get_settings(), store.graph_version()
    m.migrate_store(store)
    assert store.schema_version()["version"] == m.CURRENT_SCHEMA_VERSION
    assert store.schema_version()["checksum"] == m.MIGRATION_CHECKSUM
    assert (store.get_settings(), store.graph_version()) == before


def test_new_store_has_all_typed_record_tables_and_explicit_relations(store):
    m = migrations()
    assert set(m.KNOWLEDGE_COLUMNS) >= {
        "Artifact",
        "EvidenceSpan",
        "AssertionSupport",
        "ConsumerAck",
        "QuerySnapshot",
    }
    assert m.KNOWLEDGE_COLUMNS["AssertionVersion"]["recorded_from"] == "TIMESTAMP"
    assert m.KNOWLEDGE_COLUMNS["Suppression"]["epoch"] == "INT64"
    assert m.KNOWLEDGE_COLUMNS["AccessPolicy"]["allow_users"] == "STRING[]"
    assert {name for name, _, _ in m.KNOWLEDGE_RELATIONS} >= {
        "SUBJECT_OBJECT",
        "TARGET_OBJECT",
        "VERSION_OF",
        "SUPPORT_SPAN",
    }


def legacy_contents(store):
    """Populate v1 using public inherited APIs, preserving exact source bytes/auth."""
    store.ensure_roles()
    enabled = store.create_user("legacy", "correct-password", "arch-admin")
    disabled = store.create_user("disabled", "disabled-password", "individual")
    store.update_user(disabled, disabled=True)
    source = store.create_source("file", "v1.sql", owner_id=enabled, access_role_id="local-admin")
    store.add_passages(
        [
            {
                "id": "legacy-p",
                "source_id": source,
                "title": "DDL",
                "text": '{"old":[1]}',
                "ordinal": 0,
                "embedding": [1.0, 0.0],
            }
        ]
    )
    store.add_entities([{"id": "legacy-e", "name": "table", "embedding": [1.0, 0.0]}])
    store.link_passage_entities([("legacy-p", "legacy-e")])
    store.add_symbols(
        [
            {
                "id": "symbol-legacy",
                "source_id": source,
                "name": "f",
                "qualname": "f",
                "kind": "function",
                "lang": "python",
                "path": "a.py",
                "line_start": 1,
                "line_end": 2,
                "signature": "f()",
                "doc": "legacy doc",
            }
        ]
    )
    question_set = store.create_question_set("legacy-eval", source_id=source)
    (question,) = store.add_questions(
        question_set, [{"text": "What?", "expected_answer": "table", "gold_passage_ids": ["legacy-p"]}]
    )
    run = store.create_run(question_set, "baseline", store.get_settings())
    result = store.add_result(
        run,
        question,
        {"answer": "table", "trace": {"passage_ids": ["legacy-p"], "private": "original trace"}},
    )
    store.set_meta("session_secret", "legacy-browser-signing-secret")
    store.set_meta("embed_model", "legacy-model")
    return {
        "enabled": store.get_user(enabled),
        "disabled": store.get_user(disabled),
        "source_id": source,
        "source": store.get_source(source),
        "result_id": result,
        "result": store.get_result(result),
        "graph_version": store.graph_version(),
    }


def assert_legacy_preserved(store, before):
    from types import SimpleNamespace

    from starlette.datastructures import Headers

    from hippo.web.auth import read_session, resolve_principal, sign_session

    assert store.get_user(before["enabled"]["id"]) == before["enabled"]
    assert store.get_user(before["disabled"]["id"]) == before["disabled"]
    assert store.check_password("legacy", "correct-password")["id"] == before["enabled"]["id"]
    assert store.check_password("disabled", "disabled-password") is None
    assert store.get_result(before["result_id"]) == before["result"]
    assert store.get_meta("session_secret") == "legacy-browser-signing-secret"
    assert store.get_meta("embed_model") == "legacy-model"
    assert store.graph_version() == before["graph_version"]
    assert store.get_source(before["source_id"])["owner_id"] == before["source"]["owner_id"]
    assert store.get_source(before["source_id"])["access_role_id"] == "local-admin"
    assert store.get_passages(["legacy-p"])[0]["text"] == '{"old":[1]}'
    secret = store.get_meta("session_secret").encode()
    ctx = SimpleNamespace(store=store)
    cookie = sign_session(secret, before["enabled"]["id"])
    assert read_session(secret, cookie) == before["enabled"]["id"]
    assert (
        resolve_principal(ctx, Headers({"cookie": f"hippo_session={cookie}"})).user_id
        == before["enabled"]["id"]
    )
    assert (
        resolve_principal(ctx, Headers({"authorization": "Bearer " + before["enabled"]["token"]})).user_id
        == before["enabled"]["id"]
    )
    assert resolve_principal(ctx, Headers({"authorization": "Bearer " + before["disabled"]["token"]})) is None
    disabled_cookie = sign_session(secret, before["disabled"]["id"])
    assert resolve_principal(ctx, Headers({"cookie": f"hippo_session={disabled_cookie}"})) is None


def test_populated_v1_ladybug_migrates_reopens_and_preserves_auth(tmp_path, monkeypatch):
    from hippo.store.ladybug import LadybugStore

    m = migrations()
    path = tmp_path / "legacy.lbug"
    with monkeypatch.context() as patch:
        patch.setattr(LadybugStore, "ensure_schema", LadybugStore._ensure_legacy_schema)
        legacy = LadybugStore(path)
        before = legacy_contents(legacy)
        assert not legacy.run("CALL show_tables() WHERE name='SchemaVersion' RETURN name")
        legacy.close()
    migrated = LadybugStore(path)
    assert migrated.schema_version()["version"] == m.CURRENT_SCHEMA_VERSION
    migrated.close()
    reopened = LadybugStore(path)
    try:
        assert_legacy_preserved(reopened, before)
    finally:
        reopened.close()


def test_populated_backend_migration_preserves_legacy_records(store):
    before = legacy_contents(store)
    m = migrations()
    if store.knowledge_backend == "fake":
        store._schema_row = {"version": 1, "checksum": m.V1_CHECKSUM, "state": "complete", "step": 0}
        store._schema_history = {1: dict(store._schema_row)}
    else:
        store.run("MATCH (v:SchemaVersion) DETACH DELETE v")
        store.run(
            "CREATE (v:SchemaVersion {id:'legacy-v1',version:1,checksum:$checksum,state:'complete',step:0})",
            checksum=m.V1_CHECKSUM,
        )
    m.migrate_store(store)
    assert_legacy_preserved(store, before)
    if store.knowledge_backend != "fake":
        assert (
            store.run_one("MATCH (v:SchemaVersion {id:'legacy-v1'}) RETURN v.checksum AS checksum")[
                "checksum"
            ]
            == m.V1_CHECKSUM
        )


@pytest.mark.parametrize("version,checksum", [(999, "unknown"), (2, "wrong-checksum")])
def test_future_schema_and_checksum_fail_before_any_mutation(store, version, checksum):
    m = migrations()
    source = store.create_source("text", "queued survives")
    if store.knowledge_backend == "fake":
        store._schema_row = {"version": version, "checksum": checksum, "state": "complete", "step": 0}
    else:
        store.run(
            "MATCH (v:SchemaVersion) SET v.version=$version, v.checksum=$checksum",
            version=version,
            checksum=checksum,
        )
    with pytest.raises(m.SchemaCompatibilityError):
        m.migrate_store(store)
    # Inspection uses the internal raw boundary; normal application queries must refuse.
    with pytest.raises(RuntimeError):
        store.get_settings()
    store._migrating = True
    assert store.get_source(source)["status"] == "queued"
    if store.knowledge_backend != "fake":
        assert store.run_one(
            "MATCH (v:SchemaVersion) RETURN v.version AS version, v.checksum AS checksum"
        ) == {"version": version, "checksum": checksum}
    store._migrating = False


def test_ladybug_future_version_releases_lock_and_does_not_cleanup(tmp_path):
    import real_ladybug as lb

    from hippo.store.ladybug import LadybugStore

    m = migrations()
    path = tmp_path / "future.lbug"
    original = LadybugStore(path)
    source = original.create_source("text", "queued")
    original.run("MATCH (v:SchemaVersion) SET v.version=999")
    original.close()
    for _ in range(2):
        with pytest.raises(m.SchemaCompatibilityError):
            LadybugStore(path)
    db = lb.Database(str(path))
    connection = lb.Connection(db)
    result = connection.execute("MATCH (s:Source {id:$id}) RETURN s.status", {"id": source})
    assert result.get_next() == ["queued"]
    result.close()
    connection.close()
    db.close()


def test_migration_data_failure_rolls_back_and_recovers(store):
    m = migrations()
    store.ensure_schema()
    if store.knowledge_backend == "fake":
        store._schema_history.pop(m.CURRENT_SCHEMA_VERSION)
        store._schema_row = dict(store._schema_history[m.CURRENT_SCHEMA_VERSION - 1])
    else:
        store.run(
            "MATCH (v:SchemaVersion {version:$version}) DETACH DELETE v", version=m.CURRENT_SCHEMA_VERSION
        )

    def fault(step):
        if step == "data":
            raise RuntimeError("injected migration")

    with pytest.raises(RuntimeError, match="injected migration"):
        m.migrate_store(store, fault_hook=fault)
    m.migrate_store(store)
    assert store.schema_version()["state"] == "complete"


def test_migration_records_legacy_and_current_checksums(store):
    m = migrations()
    store.ensure_schema()
    history = store.schema_history()
    assert {row["version"] for row in history} == {1, 2, 3}
    assert {row["version"]: row["checksum"] for row in history} == m.SUPPORTED_CHECKSUMS
    assert all(row["state"] == "complete" for row in history)


def test_rejects_malformed_schema_version_before_mutation(monkeypatch):
    m = migrations()
    for version in (True, 1.0, "1"):
        monkeypatch.setattr(
            m,
            "schema_version",
            lambda _, value=version: {
                "version": value,
                "checksum": m.V1_CHECKSUM,
                "state": "complete",
                "step": 0,
            },
        )
        with pytest.raises(m.SchemaCompatibilityError):
            m.check_compatibility(object())


def test_declared_complete_schema_is_checked_against_physical_shape(tmp_path):
    from hippo.store.ladybug import LadybugStore

    m = migrations()
    path = tmp_path / "wrong-shape.lbug"
    store = LadybugStore(path)
    store.run("ALTER TABLE Suppression DROP epoch")
    store.close()
    with pytest.raises(m.SchemaCompatibilityError, match="shape"):
        LadybugStore(path)


@pytest.mark.parametrize("version", [2, 3])
def test_recovery_after_each_declared_schema_step(store, version):
    if store.knowledge_backend == "fake":
        pytest.skip("Fake storage has no DDL; its data rollback is tested separately")
    m = migrations()
    for position in range(len(m.schema_steps(store, version=version))):
        store.run("MATCH (v:SchemaVersion) WHERE v.version >= $version DETACH DELETE v", version=version)

        def fail(step, expected=f"schema:{position}"):
            if step == expected:
                raise RuntimeError(f"injected {expected}")

        with pytest.raises(RuntimeError, match="injected schema"):
            m.migrate_store(store, fault_hook=fail)
        with pytest.raises(RuntimeError, match="migration"):
            store.get_settings()
        store._migrating = True
        try:
            row = store.schema_version()
            if store.knowledge_backend == "ladybug":
                assert row["version"] == version - 1  # migration writes rolled back
            else:
                assert row["state"] == "pending" and row["step"] == position + 1
        finally:
            store._migrating = False
        m.migrate_store(store)
        assert store.schema_version()["state"] == "complete"


def test_first_ladybug_schema_failure_rolls_back_actual_new_tables(tmp_path, monkeypatch):
    from hippo.store.ladybug import LadybugStore

    m = migrations()
    with monkeypatch.context() as patch:
        patch.setattr(LadybugStore, "ensure_schema", LadybugStore._ensure_legacy_schema)
        store = LadybugStore(tmp_path / "rollback.lbug")
    try:
        original_tables = store.run("CALL show_tables() RETURN name,type ORDER BY name")
        last_step = f"schema:{len(m.schema_steps(store, version=2)) - 1}"

        def fail(step):
            if step == last_step:
                raise RuntimeError("last schema step")

        with pytest.raises(RuntimeError, match="last schema step"):
            m.migrate_store(store, fault_hook=fail)
        store._migrating = True
        try:
            assert store.run("CALL show_tables() RETURN name,type ORDER BY name") == original_tables
            assert "workspace_id" not in {
                row["name"] for row in store.run("CALL table_info('Source') RETURN *")
            }
        finally:
            store._migrating = False
        m.migrate_store(store)
        assert store.schema_version()["state"] == "complete"
    finally:
        store.close()


def test_caught_statement_failure_cannot_autocommit_later_writes(store):
    if store.knowledge_backend == "fake":
        pytest.skip("FakeStore has no driver statement boundary")
    constraint_error = RuntimeError
    if store.knowledge_backend == "neo4j":
        from neo4j.exceptions import ConstraintError

        constraint_error = ConstraintError
    with pytest.raises(RuntimeError, match="[Tt]ransaction|roll back"):
        with store.transaction():
            store.run("CREATE (:Workspace {id:'transaction-before',name:'before'})")
            with pytest.raises(constraint_error):
                store.run("CREATE (:Workspace {id:'transaction-before',name:'duplicate'})")
            with pytest.raises(RuntimeError, match="[Tt]ransaction.*failed"):
                store.run("CREATE (:Workspace {id:'transaction-after',name:'after'})")
    assert (
        store.run(
            "MATCH (w:Workspace) WHERE w.id IN ['transaction-before','transaction-after'] RETURN w.id AS id"
        )
        == []
    )
    with store.transaction():
        store.run("CREATE (:Workspace {id:'transaction-recovered',name:'recovered'})")
    assert store.run("MATCH (w:Workspace {id:'transaction-recovered'}) RETURN w.name AS name") == [
        {"name": "recovered"}
    ]


@pytest.mark.parametrize("failure", ["materialization", "result_close"])
def test_caught_result_failure_poisons_ladybug_transaction(store, monkeypatch, failure):
    if store.knowledge_backend != "ladybug":
        pytest.skip("Injects failures at the Ladybug result-consumption boundary")
    connection = store._conn
    closed = []

    class FailedResult:
        def __init__(self, result):
            self.result = result

        def get_column_names(self):
            return self.result.get_column_names()

        def has_next(self):
            return self.result.has_next()

        def get_next(self):
            if failure == "materialization":
                raise RuntimeError("injected result failure")
            return self.result.get_next()

        def close(self):
            self.result.close()
            closed.append(True)
            if failure == "result_close":
                raise RuntimeError("injected result failure")

    class ConnectionProxy:
        def execute(self, query, *args):
            result = connection.execute(query, *args)
            return FailedResult(result) if query == "RETURN 1 AS marker" else result

    with monkeypatch.context() as patch:
        patch.setattr(store, "_conn", ConnectionProxy())
        with pytest.raises(RuntimeError, match="[Tt]ransaction|roll back"):
            with store.transaction():
                store.run("CREATE (:Workspace {id:'result-before',name:'before'})")
                with pytest.raises(RuntimeError, match="injected result failure"):
                    store.run("RETURN 1 AS marker")
                with pytest.raises(RuntimeError, match="[Tt]ransaction.*failed"):
                    store.run("CREATE (:Workspace {id:'result-after',name:'after'})")
    assert closed == [True]
    assert (
        store.run("MATCH (w:Workspace) WHERE w.id IN ['result-before','result-after'] RETURN w.id AS id")
        == []
    )
