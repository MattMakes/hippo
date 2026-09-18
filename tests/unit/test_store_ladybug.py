"""
What is specific to the embedded LadybugDB store: it is a file, it survives a restart,
one process owns it at a time, and `open_store` picks it by default.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from hippo.config import Config, load_config, parse_store_backend
from hippo.store import LadybugStore, Store, StoreLockedError, open_store
from hippo.store.code import SYNONYM_LABELS, TUNED_LABELS, ordered_pairs
from hippo.store.ladybug import NODE_TABLES

# The relationship tables exactly as they were before the code graph: SYNONYM joined entities only
# and TUNED joined entities and passages. Spelled out here rather than imported, because the point
# of the migration test is to start from the *old* shape.
OLD_REL_TABLES = [
    ("FROM", "FROM Passage TO Source", ""),
    ("MENTIONS", "FROM Passage TO Entity", ""),
    ("STATES", "FROM Passage TO Fact", ""),
    ("SUBJECT", "FROM Fact TO Entity", ""),
    ("OBJECT", "FROM Fact TO Entity", ""),
    ("SYNONYM", "FROM Entity TO Entity", ", score DOUBLE, manual BOOLEAN"),
    (
        "TUNED",
        "FROM Entity TO Entity, FROM Entity TO Passage, FROM Passage TO Entity, FROM Passage TO Passage",
        ", weight DOUBLE, updated_at STRING",
    ),
    ("ABOUT", "FROM QuestionSet TO Source", ""),
    ("HAS", "FROM QuestionSet TO Question", ""),
    ("OF", "FROM EvalRun TO QuestionSet", ""),
    ("RESULT", "FROM EvalRun TO EvalResult", ""),
    ("FOR", "FROM EvalResult TO Question", ""),
]


def make_old_database(path: Path) -> None:
    """A file written by the pre-code-graph hippo: today's node tables minus the code ones, the old
    narrow SYNONYM/TUNED, and one row in each so the ALTER runs against a populated table."""
    import real_ladybug as lb

    path.parent.mkdir(parents=True, exist_ok=True)
    db = lb.Database(str(path))
    conn = lb.Connection(db)
    for name, columns in NODE_TABLES.items():
        if name not in ("Symbol", "DataObject", "Commit"):
            conn.execute(f"CREATE NODE TABLE {name}({columns})")
    for name, pairs, extra in OLD_REL_TABLES:
        conn.execute(f"CREATE REL TABLE {name}({pairs}{extra})")
    conn.execute("CREATE (s:Source {id: 'src', name: 'Notes', kind: 'text', min_rank: 0})")
    conn.execute(
        "CREATE (p:Passage {id: 'passage-1', title: 'One', text: 't', ordinal: 0, embedding: [1.0]})"
    )
    conn.execute("MATCH (p:Passage {id: 'passage-1'}), (s:Source {id: 'src'}) CREATE (p)-[:FROM]->(s)")
    for entity_id, name in (("entity-a", "alpha"), ("entity-b", "beta")):
        conn.execute(
            f"CREATE (e:Entity {{id: '{entity_id}', name: '{name}', boost: 1.0, embedding: [1.0], "
            "created_at: '2026-01-01'})"
        )
    conn.execute(
        "MATCH (p:Passage {id: 'passage-1'}), (e:Entity {id: 'entity-a'}) CREATE (p)-[:MENTIONS]->(e)"
    )
    conn.execute(
        "MATCH (p:Passage {id: 'passage-1'}), (e:Entity {id: 'entity-b'}) CREATE (p)-[:MENTIONS]->(e)"
    )
    conn.execute(
        "MATCH (a:Entity {id: 'entity-a'}), (b:Entity {id: 'entity-b'}) "
        "CREATE (a)-[:SYNONYM {score: 0.9, manual: true}]->(b)"
    )
    conn.execute(
        "MATCH (a:Entity {id: 'entity-a'}), (p:Passage {id: 'passage-1'}) "
        "CREATE (a)-[:TUNED {weight: 2.5, updated_at: '2026-01-01'}]->(p)"
    )
    conn.close()
    db.close()


# ---------------------------------------------------------------- migration
# Test 1.5a: the one test that decides whether the ALTER path or a rebuild ships. It passes, so
# `ensure_schema` grows an old file in place and no rebuild contingency exists.


def test_an_old_narrow_database_is_widened_in_place_and_keeps_its_rows(tmp_path: Path) -> None:
    path = tmp_path / "old.lbug"
    make_old_database(path)

    store = LadybugStore(path)  # opening runs ensure_schema, which is the migration
    try:
        assert store.connection_pairs("SYNONYM") == set(ordered_pairs(SYNONYM_LABELS))
        assert store.connection_pairs("TUNED") == set(ordered_pairs(TUNED_LABELS))

        # The rows written before the widening are still there, with their properties.
        assert store.load_synonyms() == [{"a": "entity-a", "b": "entity-b", "score": 0.9, "manual": True}]
        assert store.load_tuned_edges() == [{"a": "entity-a", "b": "passage-1", "weight": 2.5}]
        assert {r["id"] for r in store.load_entities()} == {"entity-a", "entity-b"}

        # And the widened endpoints really accept cross-kind writes.
        symbol_id = "symbol-" + "0" * 32
        store.add_symbols(
            [
                {
                    "id": symbol_id,
                    "source_id": "src",
                    "name": "place",
                    "qualname": "OrderService.place",
                    "kind": "method",
                    "lang": "python",
                    "path": "pyapp/orders.py",
                    "line_start": 1,
                    "line_end": 2,
                    "embedding": [1.0],
                }
            ]
        )
        store.add_synonyms([("entity-a", symbol_id, 0.87)])
        store.set_edge_weight(symbol_id, "passage-1", 4.0)
        store.set_node_boost(symbol_id, 1.5)
        store.ensure_schema()  # calling it again changes nothing
    finally:
        store.close()

    again = LadybugStore(path)
    try:
        assert again.connection_pairs("SYNONYM") == set(ordered_pairs(SYNONYM_LABELS))
        synonyms = {(r["a"], r["b"]): r["score"] for r in again.load_synonyms()}
        assert synonyms[("entity-a", "entity-b")] == 0.9
        assert synonyms[("entity-a", "symbol-" + "0" * 32)] == pytest.approx(0.87)
        assert len(again.load_tuned_edges()) == 2
        assert again.load_symbols()[0]["boost"] == 1.5
    finally:
        again.close()


def test_data_survives_close_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "memory" / "hippo.lbug"  # the folder does not exist yet: the store creates it
    store = LadybugStore(path)
    source_id = store.create_source("text", "Notes")
    store.update_settings({"damping": 0.7})
    store.set_meta("embed_model", "nomic-embed-text")
    version = store.bump_graph_version()
    store.close()

    again = LadybugStore(path)
    try:
        assert again.get_source(source_id)["name"] == "Notes"
        assert again.get_settings()["damping"] == 0.7
        assert again.get_meta("embed_model") == "nomic-embed-text"
        assert again.graph_version() == version
    finally:
        again.close()


def test_a_second_process_cannot_open_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "hippo.lbug"
    store = LadybugStore(path)
    try:
        code = (
            "import sys\n"
            "from hippo.store import LadybugStore, StoreLockedError\n"
            "try:\n"
            f"    LadybugStore({str(path)!r})\n"
            "except StoreLockedError as exc:\n"
            "    print('locked:', exc)\n"
            "    sys.exit(0)\n"
            "sys.exit(1)\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        assert "already open in another hippo process" in result.stdout
    finally:
        store.close()


def test_the_lock_error_is_a_runtime_error_with_advice() -> None:
    assert issubclass(StoreLockedError, RuntimeError)


def test_ping_bootstraps_once_and_marks_interrupted_jobs(tmp_path: Path) -> None:
    store = LadybugStore(tmp_path / "hippo.lbug")
    try:
        stuck = store.create_source("text", "stuck")
        store.update_source(stuck, status="indexing")
        assert store.ping() is True
        assert store.get_source(stuck)["status"] == "failed"
        # A second ping does nothing new: a source that starts indexing after startup is left alone.
        running = store.create_source("text", "running")
        store.update_source(running, status="indexing")
        assert store.ping() is True
        assert store.get_source(running)["status"] == "indexing"
    finally:
        store.close()


def test_open_store_defaults_to_the_embedded_file_under_data_dir(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path / "data")
    assert config.store_backend == "ladybug"
    assert config.database_path == tmp_path / "data" / "hippo.lbug"
    assert config.store_location == str(tmp_path / "data" / "hippo.lbug")
    store = open_store(config)
    try:
        assert isinstance(store, LadybugStore)
        assert (tmp_path / "data" / "hippo.lbug").exists()
    finally:
        store.close()


def test_open_store_can_be_pointed_at_neo4j() -> None:
    pytest.importorskip("neo4j")
    config = Config(store_backend="neo4j", neo4j_uri="bolt://nowhere.invalid:7687")
    assert config.store_location == "bolt://nowhere.invalid:7687"
    store = open_store(config)  # connecting is lazy, so this succeeds without a server
    try:
        assert isinstance(store, Store)
    finally:
        store.close()


def test_store_env_vars_are_read_and_validated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HIPPO_STORE", "Ladybug")
    monkeypatch.setenv("HIPPO_DB_PATH", str(tmp_path / "elsewhere.lbug"))
    config = load_config()
    assert config.store_backend == "ladybug"
    assert config.database_path == tmp_path / "elsewhere.lbug"
    with pytest.raises(ValueError, match="HIPPO_STORE must be one of"):
        parse_store_backend("sqlite")
