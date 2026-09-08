"""
The Store interface, part 4: the code graph.

Symbols, data objects, commits and the typed edges between them, written and read
back through the `store` fixture, so every case here runs against LadybugDB, the
in-memory FakeStore and (in CI) a real Neo4j. That is what keeps the three
implementations in `store/ladybug.py`, `store/code.py` and `tests/fakes/fake_store.py`
honest: they share no interface, only these tests.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hippo.hipporag.text import make_id

SRC = Path(__file__).resolve().parents[2] / "src" / "hippo"
FAKE_STORE = Path(__file__).resolve().parents[1] / "fakes" / "fake_store.py"

VEC = [1.0, 0.0, 0.0]
VEC2 = [0.0, 1.0, 0.0]


def sid(name: str) -> str:
    return make_id("symbol-", name)


def did(name: str) -> str:
    return make_id("data-", name)


def cid(name: str) -> str:
    return make_id("commit-", name)


PLACE = sid("place")
TOTAL = sid("total")
SAVE = sid("save")
ORDERS = did("orders")
ORDER_ID = did("orders.id")


@pytest.fixture
def source_id(store) -> str:
    return store.create_source("repo", "pyapp")


def symbol(source_id: str, node_id: str, name: str, **fields):
    row = {
        "id": node_id,
        "source_id": source_id,
        "name": name,
        "qualname": f"OrderService.{name}",
        "kind": "method",
        "lang": "python",
        "path": "pyapp/orders.py",
        "line_start": 16,
        "line_end": 23,
        "signature": f"{name}(self, order)",
        "doc": "Place an order.",
        "is_test": False,
        "raises": ["ValueError"],
        "embedding": VEC,
    }
    row.update(fields)
    return row


def data_object(source_id: str, node_id: str, name: str, **fields):
    row = {
        "id": node_id,
        "source_id": source_id,
        "name": name,
        "qualname": name,
        "kind": "table",
        "dialect": "sql",
        "embedding": VEC2,
    }
    row.update(fields)
    return row


def commit(source_id: str, node_id: str, sha: str, ordinal: int, **fields):
    row = {
        "id": node_id,
        "source_id": source_id,
        "sha": sha,
        "author": "Ada",
        "date": "2026-01-01T00:00:00Z",
        "message": "Rework place()",
        "ordinal": ordinal,
    }
    row.update(fields)
    return row


def add_passage(store, source_id: str, pid: str, title: str = "T") -> str:
    store.add_passages(
        [
            {
                "id": pid,
                "source_id": source_id,
                "ordinal": 0,
                "title": title,
                "text": "some text",
                "embedding": VEC,
            }
        ]
    )
    return pid


# ------------------------------------------------------------------ symbols


def test_symbols_round_trip_with_every_field(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place")])
    (row,) = store.get_symbols([PLACE])
    assert (row["id"], row["name"], row["qualname"]) == (PLACE, "place", "OrderService.place")
    assert (row["kind"], row["lang"], row["path"]) == ("method", "python", "pyapp/orders.py")
    assert (row["line_start"], row["line_end"]) == (16, 23)
    assert row["signature"] == "place(self, order)"
    assert row["doc"] == "Place an order."
    assert row["is_test"] is False
    assert row["raises"] == ["ValueError"]
    assert row["name_tokens"] == ["place"]  # the store fills these in from the name
    assert (row["boost"], row["community"]) == (1.0, None)
    assert row["source_id"] == source_id and row["source_name"] == "pyapp"
    assert row["created_at"]


def test_symbol_free_text_may_be_none_or_look_like_json(store, source_id: str) -> None:
    # LadybugDB parses a string parameter starting with { or [ as a struct, and decode() breaks on
    # a bare None: both are silent corruptions, so both get a case.
    store.add_symbols(
        [
            symbol(source_id, PLACE, "place", doc=None, signature="place(**kw)"),
            symbol(source_id, TOTAL, "total", doc="{**kw} and [deprecated]", qualname="billing.total"),
        ]
    )
    rows = {r["id"]: r for r in store.get_symbols([PLACE, TOTAL])}
    assert rows[PLACE]["doc"] == ""
    assert rows[TOTAL]["doc"] == "{**kw} and [deprecated]"
    assert rows[TOTAL]["qualname"] == "billing.total"


def test_name_tokens_split_a_camel_case_identifier(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "OrderService", kind="class")])
    (row,) = store.get_symbols([PLACE])
    assert row["name_tokens"] == ["order", "service"]


def test_re_adding_a_symbol_updates_it_in_place(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place", line_end=23)])
    created = store.get_symbols([PLACE])[0]["created_at"]
    store.add_symbols([symbol(source_id, PLACE, "place", line_end=40, doc="Now longer.")])
    (row,) = store.get_symbols([PLACE])
    assert (row["line_end"], row["doc"]) == (40, "Now longer.")
    assert row["created_at"] == created
    assert store.stats()["symbols"] == 1


def test_a_row_whose_source_is_missing_is_skipped(store, source_id: str) -> None:
    store.add_symbols([symbol("no-such-source", PLACE, "place")])
    store.add_data_objects([data_object("no-such-source", ORDERS, "orders")])
    store.add_commits([commit("no-such-source", cid("a"), "aaa", 0)])
    assert store.get_symbols([PLACE]) == []
    assert (store.stats()["symbols"], store.stats()["data_objects"], store.stats()["commits"]) == (0, 0, 0)


def test_get_symbols_keeps_the_asked_order_and_skips_unknown_ids(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place"), symbol(source_id, TOTAL, "total")])
    rows = store.get_symbols([TOTAL, PLACE, sid("nope")])
    assert [r["id"] for r in rows] == [TOTAL, PLACE]


# ------------------------------------------------------------- data objects


def test_data_objects_round_trip(store, source_id: str) -> None:
    store.add_data_objects([data_object(source_id, ORDERS, "orders")])
    (row,) = store.get_data_objects([ORDERS])
    assert (row["name"], row["qualname"], row["kind"], row["dialect"]) == ("orders", "orders", "table", "sql")
    assert row["name_tokens"] == ["orders"]
    assert (row["boost"], row["source_name"]) == (1.0, "pyapp")


# ----------------------------------------------------------------- commits


def test_commits_round_trip(store, source_id: str) -> None:
    store.add_commits([commit(source_id, cid("a"), "abc1234", 0)])
    (row,) = store.get_commits([cid("a")])
    assert (row["sha"], row["author"], row["ordinal"]) == ("abc1234", "Ada", 0)
    assert row["message"] == "Rework place()"
    assert row["date"] == "2026-01-01T00:00:00Z"


# ------------------------------------------------------------- definitions


def test_link_definitions_shows_up_as_passage_ids(store, source_id: str) -> None:
    add_passage(store, source_id, "passage-1")
    add_passage(store, source_id, "passage-2")
    store.add_symbols([symbol(source_id, PLACE, "place")])
    store.add_data_objects([data_object(source_id, ORDERS, "orders")])
    store.add_commits([commit(source_id, cid("a"), "abc", 0)])
    store.link_definitions(
        [(PLACE, "passage-1"), (ORDERS, "passage-1"), (ORDERS, "passage-2"), (cid("a"), "passage-2")]
    )

    assert store.get_symbols([PLACE])[0]["passage_ids"] == ["passage-1"]
    assert sorted(store.get_data_objects([ORDERS])[0]["passage_ids"]) == ["passage-1", "passage-2"]
    assert store.get_commits([cid("a")])[0]["passage_ids"] == ["passage-2"]
    assert len(store.load_definitions()) == 4


def test_link_definitions_is_idempotent(store, source_id: str) -> None:
    add_passage(store, source_id, "passage-1")
    store.add_symbols([symbol(source_id, PLACE, "place")])
    store.link_definitions([(PLACE, "passage-1")])
    store.link_definitions([(PLACE, "passage-1")])
    assert store.load_definitions() == [{"node_id": PLACE, "passage_id": "passage-1"}]


# --------------------------------------------------------------- code edges


def test_code_edges_are_directed_and_carry_their_provenance(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place"), symbol(source_id, TOTAL, "total")])
    store.add_code_edges(
        [
            {
                "a": PLACE,
                "b": TOTAL,
                "kind": "INVOKES",
                "omega": 1.0,
                "provenance": "same_file",
                "extra": {"call_line": 18, "in_branch": False},
            }
        ]
    )
    (row,) = store.load_code_edges()
    assert (row["a"], row["b"], row["kind"]) == (PLACE, TOTAL, "INVOKES")
    assert row["omega"] == pytest.approx(1.0)
    assert row["provenance"] == "same_file"
    assert row["extra"] == {"call_line": 18, "in_branch": False}


def test_re_adding_a_code_edge_raises_omega_but_never_lowers_it(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place"), symbol(source_id, TOTAL, "total")])
    edge = {"a": PLACE, "b": TOTAL, "kind": "INVOKES", "omega": 0.5, "provenance": "fuzzy_name"}
    store.add_code_edges([edge])
    store.add_code_edges([{**edge, "omega": 0.9, "provenance": "via_import"}])
    store.add_code_edges([{**edge, "omega": 0.5, "provenance": "fuzzy_name"}])

    (row,) = store.load_code_edges()
    assert row["omega"] == pytest.approx(0.9)
    assert row["provenance"] == "via_import"
    assert store.stats()["code_edges"] == 1


def test_one_batch_with_the_same_pair_twice_keeps_the_best_omega(store, source_id: str) -> None:
    # The NOT EXISTS guard cannot see rows its own statement created, so the dedupe is in Python.
    store.add_symbols([symbol(source_id, PLACE, "place"), symbol(source_id, TOTAL, "total")])
    store.add_code_edges(
        [
            {"a": PLACE, "b": TOTAL, "kind": "INVOKES", "omega": 0.5, "provenance": "fuzzy_name"},
            {"a": PLACE, "b": TOTAL, "kind": "INVOKES", "omega": 1.0, "provenance": "same_file"},
        ]
    )
    (row,) = store.load_code_edges()
    assert (row["omega"], row["provenance"]) == (pytest.approx(1.0), "same_file")


def test_two_kinds_between_the_same_pair_are_two_edges(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place"), symbol(source_id, TOTAL, "total")])
    store.add_code_edges(
        [
            {"a": PLACE, "b": TOTAL, "kind": "INVOKES", "omega": 1.0, "provenance": "same_file"},
            {"a": PLACE, "b": TOTAL, "kind": "IMPORTS", "omega": 0.95, "provenance": "import_path"},
        ]
    )
    assert sorted(r["kind"] for r in store.load_code_edges()) == ["IMPORTS", "INVOKES"]


def test_an_unknown_edge_kind_raises(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place"), symbol(source_id, TOTAL, "total")])
    with pytest.raises(ValueError, match="unknown code edge kind"):
        store.add_code_edges([{"a": PLACE, "b": TOTAL, "kind": "SUMMONS", "omega": 1.0}])


def test_self_loops_and_pairs_code_edge_has_no_endpoint_for_are_dropped(store, source_id: str) -> None:
    add_passage(store, source_id, "passage-1")
    store.add_symbols([symbol(source_id, PLACE, "place")])
    store.add_data_objects([data_object(source_id, ORDERS, "orders")])
    store.add_code_edges(
        [
            {"a": PLACE, "b": PLACE, "kind": "INVOKES", "omega": 1.0},  # self loop
            {"a": ORDERS, "b": PLACE, "kind": "READS", "omega": 0.8},  # DataObject -> Symbol
            {"a": "passage-1", "b": PLACE, "kind": "INVOKES", "omega": 1.0},  # not a code node
        ]
    )
    assert store.load_code_edges() == []


def test_the_three_production_pairs_all_write(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place"), symbol(source_id, TOTAL, "total")])
    store.add_data_objects(
        [data_object(source_id, ORDERS, "orders"), data_object(source_id, ORDER_ID, "id", kind="column")]
    )
    store.add_code_edges(
        [
            {"a": PLACE, "b": TOTAL, "kind": "INVOKES", "omega": 1.0, "provenance": "same_file"},
            {"a": PLACE, "b": ORDERS, "kind": "READS", "omega": 0.85, "provenance": "sql_literal"},
            {"a": ORDERS, "b": ORDER_ID, "kind": "CONTAINS", "omega": 1.0, "provenance": "syntax"},
        ]
    )
    assert {(r["a"], r["b"]) for r in store.load_code_edges()} == {
        (PLACE, TOTAL),
        (PLACE, ORDERS),
        (ORDERS, ORDER_ID),
    }


def test_in_degree_counts_invokes_reads_writes_and_ignores_the_rest(store, source_id: str) -> None:
    store.add_symbols(
        [
            symbol(source_id, PLACE, "place"),
            symbol(source_id, TOTAL, "total"),
            symbol(source_id, SAVE, "save"),
        ]
    )
    store.add_data_objects([data_object(source_id, ORDERS, "orders")])
    store.add_commits([commit(source_id, cid("a"), "abc", 0)])
    store.add_code_edges(
        [
            {"a": PLACE, "b": TOTAL, "kind": "INVOKES", "omega": 1.0},
            {"a": SAVE, "b": TOTAL, "kind": "INVOKES", "omega": 0.9},
            {"a": PLACE, "b": SAVE, "kind": "CONTAINS", "omega": 1.0},  # not a specificity kind
            {"a": SAVE, "b": ORDERS, "kind": "WRITES", "omega": 0.85},
        ]
    )
    store.add_modifies([{"commit_id": cid("a"), "symbol_id": TOTAL, "omega": 1.0, "hunk": {}}])

    degrees = {r["id"]: r["in_degree"] for r in store.load_symbols()}
    assert degrees[TOTAL] == 2  # two INVOKES; the MODIFIES edge is deliberately not counted
    assert degrees[SAVE] == 0  # only a CONTAINS points at it
    assert degrees[PLACE] == 0
    assert {r["id"]: r["in_degree"] for r in store.load_data_objects()}[ORDERS] == 1


# ------------------------------------------------------------------ commits


def test_modifies_is_one_edge_per_commit_and_symbol(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place")])
    store.add_commits([commit(source_id, cid("a"), "abc", 0)])
    hunk = {"file": "pyapp/orders.py", "new_range": [16, 23], "churn": 4}
    store.add_modifies([{"commit_id": cid("a"), "symbol_id": PLACE, "omega": 1.0, "hunk": hunk}])
    store.add_modifies([{"commit_id": cid("a"), "symbol_id": PLACE, "omega": 1.0, "hunk": hunk}])

    (row,) = store.load_modifies()
    assert (row["commit_id"], row["symbol_id"]) == (cid("a"), PLACE)
    assert row["omega"] == pytest.approx(1.0)
    assert row["hunk"] == hunk


def test_precedes_comes_back_in_commit_order(store, source_id: str) -> None:
    store.add_commits(
        [
            commit(source_id, cid("c"), "ccc", 2),
            commit(source_id, cid("a"), "aaa", 0),
            commit(source_id, cid("b"), "bbb", 1),
        ]
    )
    store.add_precedes([(cid("b"), cid("c")), (cid("a"), cid("b")), (cid("a"), cid("a"))])
    assert store.load_precedes() == [
        {"a": cid("a"), "b": cid("b")},
        {"a": cid("b"), "b": cid("c")},
    ]


# ---------------------------------------------------------------- refers to


def test_refers_to_keeps_the_best_omega_per_pair(store, source_id: str) -> None:
    add_passage(store, source_id, "passage-1")
    store.add_symbols([symbol(source_id, PLACE, "place")])
    store.add_refers_to([{"passage_id": "passage-1", "node_id": PLACE, "omega": 0.6, "token": "place"}])
    store.add_refers_to(
        [{"passage_id": "passage-1", "node_id": PLACE, "omega": 0.85, "token": "OrderService.place"}]
    )
    store.add_refers_to([{"passage_id": "passage-1", "node_id": PLACE, "omega": 0.6, "token": "place"}])

    (row,) = store.load_refers_to()
    assert row["omega"] == pytest.approx(0.85)
    assert row["token"] == "OrderService.place"


def test_refers_to_needs_a_real_passage_and_a_real_code_node(store, source_id: str) -> None:
    add_passage(store, source_id, "passage-1")
    store.add_symbols([symbol(source_id, PLACE, "place")])
    store.add_commits([commit(source_id, cid("a"), "abc", 0)])
    store.add_refers_to(
        [
            {"passage_id": "passage-nope", "node_id": PLACE, "omega": 0.8, "token": "x"},
            {"passage_id": "passage-1", "node_id": cid("a"), "omega": 0.8, "token": "x"},  # commits: no
        ]
    )
    assert store.load_refers_to() == []


# ------------------------------------------------------------- communities


def test_set_symbol_communities_round_trips(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place"), symbol(source_id, TOTAL, "total")])
    store.set_symbol_communities({PLACE: 3, TOTAL: 3, sid("gone"): 9})
    communities = {r["id"]: r["community"] for r in store.load_symbols()}
    assert communities == {PLACE: 3, TOTAL: 3}


# ------------------------------------------------------------- embeddings


def test_load_code_embeddings_covers_symbols_and_data_objects(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place")])
    store.add_data_objects([data_object(source_id, ORDERS, "orders")])
    ids, vectors = store.load_code_embeddings()
    by_id = dict(zip(ids, vectors, strict=True))
    assert set(by_id) == {PLACE, ORDERS}
    assert list(by_id[PLACE]) == VEC
    assert list(by_id[ORDERS]) == VEC2


def test_a_symbol_with_no_vector_is_left_out_of_the_embeddings(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place", embedding=[])])
    assert store.load_code_embeddings() == ([], [])
    assert len(store.load_symbols()) == 1


# ------------------------------------------------------------------ loading


def test_load_rows_carry_the_source_name(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place")])
    store.add_data_objects([data_object(source_id, ORDERS, "orders")])
    store.add_commits([commit(source_id, cid("a"), "abc", 0)])
    assert store.load_symbols()[0]["source_name"] == "pyapp"
    assert store.load_data_objects()[0]["source_name"] == "pyapp"
    assert store.load_commits()[0]["source_name"] == "pyapp"


def test_an_empty_store_loads_nothing(store) -> None:
    assert store.load_symbols() == []
    assert store.load_data_objects() == []
    assert store.load_commits() == []
    assert store.load_code_edges() == []
    assert store.load_definitions() == []
    assert store.load_modifies() == []
    assert store.load_precedes() == []
    assert store.load_refers_to() == []
    assert store.load_code_embeddings() == ([], [])


# ------------------------------------------------------------ parity guard


def public_methods(path: Path) -> set[str]:
    """Method names one indent deep in a file: the store's own surface, ignoring helpers."""
    names = set(re.findall(r"^    def ([a-z][a-z0-9_]*)\(", path.read_text(), re.MULTILINE))
    return {name for name in names if not name.startswith("_")}


# Backend plumbing rather than store surface: running Cypher, and LadybugDB's own schema
# introspection. The FakeStore speaks no query language, so it has none of them.
BACKEND_ONLY = {"run", "run_one", "on_first_connection", "connection_pairs"}


def test_every_backend_implements_the_same_methods() -> None:
    """The three stores share no interface, only this. A method added to one and forgotten on the
    others would otherwise only surface as a mysterious AttributeError in production."""
    neo4j = public_methods(SRC / "store" / "code.py") | public_methods(SRC / "store" / "memory.py")
    ladybug = public_methods(SRC / "store" / "ladybug.py")
    fake = public_methods(FAKE_STORE)
    assert neo4j - ladybug == set()
    assert (neo4j | ladybug) - fake - BACKEND_ONLY == set()


def test_stats_counts_the_code_graph(store, source_id: str) -> None:
    store.add_symbols([symbol(source_id, PLACE, "place"), symbol(source_id, TOTAL, "total")])
    store.add_data_objects([data_object(source_id, ORDERS, "orders")])
    store.add_commits([commit(source_id, cid("a"), "abc", 0)])
    store.add_code_edges([{"a": PLACE, "b": TOTAL, "kind": "INVOKES", "omega": 1.0}])
    stats = store.stats()
    assert (stats["symbols"], stats["data_objects"], stats["commits"], stats["code_edges"]) == (2, 1, 1, 1)
