"""Capability reports must stay disposable and distinguish fallback from proof."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/rag_store_capabilities.py"


def module():
    assert SCRIPT.exists(), "Task 3 capability command has not been implemented"
    return importlib.import_module("scripts.rag_store_capabilities")


def test_cli_uses_disposable_database_ignores_live_configuration(tmp_path):
    module()
    live = tmp_path / "live.lbug"
    live.write_bytes(b"NEVER OPEN THIS DATABASE")
    output = tmp_path / "reports" / "capabilities.json"
    env = {**os.environ, "HIPPO_DB_PATH": str(live), "HIPPO_DATA_DIR": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert live.read_bytes() == b"NEVER OPEN THIS DATABASE"
    assert not Path(report["database_path"]).parent.exists()
    assert report["cleanup"]["status"] == "passed"
    assert report["engine"]["distribution"]
    assert report["engine"]["storage_version"] > 0
    assert report["selection"]["native_enabled"] is False
    assert report["selection"]["lexical"] == "authorized_view_bm25"
    assert report["selection"]["dense"] == "authorized_view_numpy_exact"
    assert report["exact_baseline"]["status"] == "passed"
    assert report["exact_baseline"]["initial_ids"] == ["allowed_a", "allowed_b"]
    assert report["exact_baseline"]["after_retirement_ids"] == ["allowed_b"]
    assert report["exact_baseline"]["after_delete_ids"] == []
    assert report["guarantees"]["application_acl"] == "not_run"
    assert report["guarantees"]["bm25_correctness"] == "not_run"
    for native in report["native"].values():
        assert native["load"]["status"] in {"passed", "unavailable", "failed"}
        if native["load"]["status"] != "passed":
            assert all(check["status"] == "not_run" for check in native["checks"].values())


def test_no_database_path_argument_or_database_output(tmp_path):
    module()
    output = tmp_path / "live.lbug"
    output.write_bytes(b"unchanged")
    for args in (["--database", str(output)], ["--output", str(output)]):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, timeout=10)
        assert result.returncode == 2
    assert output.read_bytes() == b"unchanged"


def test_extension_missing_is_not_confused_with_broken_binary():
    probe = module()
    assert probe.extension_unavailable(
        RuntimeError("Binder exception: Extension: fts is an official extension and has not been installed.")
    )
    assert not probe.extension_unavailable(RuntimeError("dlopen failed: incompatible architecture"))
    assert not probe.extension_unavailable(RuntimeError("permission denied"))


def test_native_probe_never_installs_when_loading_is_unavailable():
    probe = module()

    class MissingExtension:
        def execute(self, statement, parameters):
            assert statement == "LOAD fts", (
                "Missing native support must not trigger INSTALL or further queries"
            )
            raise RuntimeError("Extension: fts is an official extension and has not been installed.")

    result = probe.probe_native(MissingExtension(), "fts")
    assert result["load"]["status"] == "unavailable"
    assert all(check["status"] == "not_run" for check in result["checks"].values())


def test_native_stale_distances_fail_even_when_membership_is_correct(monkeypatch):
    probe = module()
    # An updated node can still be returned through a stale ANN entry. IDs alone
    # cannot prove that changing its vector changed the index's distance.
    monkeypatch.setattr(probe, "rows", lambda *_args: [["a", 0.0], ["b", 0.2]])
    with pytest.raises(ValueError, match="distance"):
        probe.native_results(None, "vector", ["a", "b"], vectors={"a": [-1, 0, 0], "b": [0.8, 0.6, 0]})


def test_core_failure_still_cleans_database_and_reports_failure(monkeypatch, tmp_path):
    probe = module()

    def fail(_connection):
        raise RuntimeError("injected core failure")

    monkeypatch.setattr(probe, "probe_exact", fail)
    output = tmp_path / "failed.json"
    assert probe.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["exact_baseline"]["status"] == "failed"
    assert report["cleanup"]["status"] == "passed"
    assert not Path(report["database_path"]).parent.exists()


def test_nonfinite_report_cannot_replace_previous_report(monkeypatch, tmp_path):
    probe = module()
    monkeypatch.setattr(probe, "probe", lambda: {"exit_code": 0, "score": float("nan")})
    output = tmp_path / "report.json"
    output.write_text('{"previous": true}')
    assert probe.main(["--output", str(output)]) == 1
    assert json.loads(output.read_text()) == {"previous": True}
    assert list(tmp_path.iterdir()) == [output]


def test_cleanup_failure_cannot_be_success(monkeypatch, tmp_path):
    probe = module()
    original = probe.cleanup_directory
    paths = []

    def fail(path):
        paths.append(path)
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(probe, "cleanup_directory", fail)
    try:
        output = tmp_path / "failed.json"
        assert probe.main(["--output", str(output)]) == 1
        assert json.loads(output.read_text())["cleanup"]["status"] == "failed"
    finally:
        for path in paths:
            original(path)


@pytest.mark.parametrize("bad", [[0, 0, 0], [float("inf"), 0, 0], [1, 0]])
def test_exact_baseline_rejects_invalid_query_vectors(bad):
    probe = module()
    with pytest.raises(ValueError):
        probe.rank_exact([("id", [1, 0, 0])], bad)


def test_index_restriction_survives_engine_autoabort(monkeypatch):
    probe = module()

    def execute(_connection, statement):
        if statement == "BEGIN TRANSACTION":
            return []
        if statement.startswith("CALL CREATE_VECTOR_INDEX"):
            raise RuntimeError("index creation cannot run in an explicit transaction")
        if statement == "ROLLBACK":
            raise RuntimeError("No active transaction for ROLLBACK")
        assert statement == "CALL SHOW_INDEXES() RETURN *"
        return []

    monkeypatch.setattr(probe, "rows", execute)
    result = probe.probe_index_transaction(None, "CALL CREATE_VECTOR_INDEX('T','probe_index','embedding')")
    assert result["supported"] is False
    assert "index creation cannot run" in result["error"]
    assert result["rollback"]["already_aborted"] is True


def test_rollback_does_not_hide_unrelated_storage_error(monkeypatch):
    probe = module()

    def execute(*_args):
        raise RuntimeError("disk checksum failure")

    monkeypatch.setattr(probe, "rows", execute)
    with pytest.raises(RuntimeError, match="checksum"):
        probe.rollback_if_active(None)


def test_index_transaction_does_not_classify_storage_failure_as_unsupported(monkeypatch):
    probe = module()
    statements = []

    def execute(_connection, statement):
        statements.append(statement)
        if statement.startswith("CALL CREATE_VECTOR_INDEX"):
            raise RuntimeError("disk checksum failure")
        return []

    monkeypatch.setattr(probe, "rows", execute)
    result = probe.checked(
        lambda: probe.probe_index_transaction(None, "CALL CREATE_VECTOR_INDEX('T','probe_index','embedding')")
    )
    assert result["status"] == "failed"
    assert "checksum" in result["error"]
    assert statements[-1] == "ROLLBACK"


@pytest.mark.parametrize("operation", ["insert", "edit", "delete", "transaction", "rollback"])
def test_native_lifecycle_rejects_silently_ignored_mutation(monkeypatch, tmp_path, operation):
    """Native searches can look consistent when the storage mutation was ignored."""
    import real_ladybug as lb

    probe = module()
    original_rows = probe.rows
    targets = {
        "insert": "CREATE (:VectorProbe {id:'c'",
        "edit": "MATCH (p:VectorProbe {id:'a'}) SET",
        "delete": "MATCH (p:VectorProbe {id:'c'}) DELETE",
        "transaction": "MATCH (p:VectorProbe {id:'b'}) SET",
    }
    rollback_results = None
    exact_query = "MATCH (p:VectorProbe) RETURN p.id,1.0-array_cosine_similarity(p.embedding,CAST([1.0,0.0,0.0] AS FLOAT[3])) AS distance ORDER BY distance,p.id"

    def execute(connection, statement, parameters=None):
        nonlocal rollback_results
        if statement == "LOAD vector" or statement.startswith(
            ("CALL CREATE_VECTOR_INDEX", "CALL DROP_VECTOR_INDEX")
        ):
            return []
        if statement.startswith("CALL QUERY_VECTOR_INDEX"):
            if "[1.0,0.0]," in statement:
                raise RuntimeError("wrong dimension")
            return (
                rollback_results if rollback_results is not None else original_rows(connection, exact_query)
            )
        if operation == "rollback" and statement == "BEGIN TRANSACTION":
            # Simulate an incorrectly persisted rollback and an index that keeps
            # returning its old snapshot, hiding the changed source row.
            rollback_results = original_rows(connection, exact_query)
        if operation == "rollback" and statement == "ROLLBACK":
            return original_rows(connection, "COMMIT")
        if statement == "CALL SHOW_INDEXES() RETURN *" or (
            operation in targets and statement.startswith(targets[operation])
        ):
            return []
        return original_rows(connection, statement, parameters)

    monkeypatch.setattr(probe, "rows", execute)
    with lb.Database(
        str(tmp_path / "fixture.lbug"), buffer_pool_size=64 * 1024 * 1024, max_num_threads=1
    ) as database:
        with lb.Connection(database) as connection:
            result = probe.probe_native(connection, "vector")
    check = result["checks"]["transaction" if operation == "rollback" else operation]
    assert check["status"] == "failed"
    assert "postcondition" in check["error"].lower()


def test_rebuild_runs_after_static_native_index_rejects_mutations(monkeypatch, tmp_path):
    """Use real core tables; emulate an index that freezes writes, not its search algorithm."""
    import real_ladybug as lb

    probe = module()
    original_rows = probe.rows
    built = False

    def execute(connection, statement, parameters=None):
        nonlocal built
        if statement == "LOAD vector":
            return []
        if statement.startswith("CALL CREATE_VECTOR_INDEX"):
            built = True
            return []
        if statement.startswith("CALL DROP_VECTOR_INDEX"):
            built = False
            return []
        if statement.startswith("CALL QUERY_VECTOR_INDEX"):
            if "[1.0,0.0]," in statement:
                raise RuntimeError("wrong dimension")
            return original_rows(
                connection,
                "MATCH (p:VectorProbe) RETURN p.id,1.0-array_cosine_similarity(p.embedding,CAST([1.0,0.0,0.0] AS FLOAT[3])) AS distance ORDER BY distance,p.id",
            )
        if statement == "CALL SHOW_INDEXES() RETURN *":
            return []
        if built and statement.startswith(("CREATE (:VectorProbe", "MATCH (p:VectorProbe {id:")):
            raise RuntimeError("node table with a static index cannot be modified")
        return original_rows(connection, statement, parameters)

    monkeypatch.setattr(probe, "rows", execute)
    with lb.Database(
        str(tmp_path / "fixture.lbug"), buffer_pool_size=64 * 1024 * 1024, max_num_threads=1
    ) as database:
        with lb.Connection(database) as connection:
            result = probe.probe_native(connection, "vector")
    assert result["checks"]["insert"]["status"] == "failed"
    assert result["checks"]["edit"]["status"] == "failed"
    assert result["checks"]["rebuild"]["status"] == "passed"
    assert result["checks"]["delete"]["status"] == "not_run"
    assert "insert" in result["checks"]["delete"]["reason"].lower()
