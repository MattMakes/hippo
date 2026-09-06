"""
The Store interface, part 3: the load_* rows the in-memory graph is built from,
and the graph edits (boosts and tuned edge weights) that must show up in them.
Same fixture as test_store.py: FakeStore locally, Neo4j in CI.
"""

from __future__ import annotations

import pytest

VEC = [1.0, 0.0, 0.0]
VEC2 = [0.0, 1.0, 0.0]


@pytest.fixture
def small_graph(store) -> str:
    """Two passages, three entities, two facts. f1 is stated by both passages; f-self is a self-loop."""
    source_id = store.create_source("text", "Src")
    store.add_passages(
        [
            {
                "id": "p1",
                "source_id": source_id,
                "ordinal": 0,
                "title": "One",
                "text": "t1",
                "embedding": VEC,
            },
            {
                "id": "p2",
                "source_id": source_id,
                "ordinal": 1,
                "title": "Two",
                "text": "t2",
                "embedding": VEC,
            },
        ]
    )
    store.add_entities(
        [
            {"id": "a", "name": "alpha", "embedding": VEC},
            {"id": "b", "name": "beta", "embedding": VEC2},
            {"id": "c", "name": "gamma", "embedding": VEC},
        ]
    )
    store.add_facts(
        [
            {
                "id": "f1",
                "subject": "a",
                "predicate": "rel",
                "object": "b",
                "subject_id": "a",
                "object_id": "b",
                "embedding": VEC,
            },
            {
                "id": "f-self",
                "subject": "c",
                "predicate": "is",
                "object": "c",
                "subject_id": "c",
                "object_id": "c",
                "embedding": VEC,
            },
        ]
    )
    store.link_passage_entities([("p1", "a"), ("p1", "b"), ("p2", "a"), ("p2", "b"), ("p2", "c")])
    store.link_passage_facts([("p1", "f1"), ("p2", "f1"), ("p2", "f-self")])
    return source_id


# ------------------------------------------------------------- load_* rows


def test_load_entities_rows(store, small_graph: str) -> None:
    rows = {r["id"]: r for r in store.load_entities()}
    assert rows["a"] == {"id": "a", "name": "alpha", "boost": 1.0, "passage_count": 2}
    assert rows["c"]["passage_count"] == 1


def test_load_passages_rows(store, small_graph: str) -> None:
    rows = {r["id"]: r for r in store.load_passages()}
    assert set(rows) == {"p1", "p2"}
    assert rows["p1"]["title"] == "One" and rows["p1"]["ordinal"] == 0
    assert list(rows["p1"]["embedding"]) == VEC
    assert (rows["p1"]["source_id"], rows["p1"]["source_name"]) == (small_graph, "Src")


def test_load_facts_rows(store, small_graph: str) -> None:
    rows = {r["id"]: r for r in store.load_facts()}
    assert set(rows) == {"f1", "f-self"}
    assert sorted(rows["f1"]["passage_ids"]) == ["p1", "p2"]
    assert list(rows["f1"]["embedding"]) == VEC
    assert (rows["f1"]["subject_id"], rows["f1"]["object_id"]) == ("a", "b")


def test_a_fact_in_two_passages_counts_twice_and_self_loops_are_excluded(store, small_graph: str) -> None:
    assert store.load_fact_edges() == [{"a": "a", "b": "b", "weight": 2}]


def test_load_mentions_rows(store, small_graph: str) -> None:
    mentions = {(m["passage_id"], m["entity_id"]) for m in store.load_mentions()}
    assert mentions == {("p1", "a"), ("p1", "b"), ("p2", "a"), ("p2", "b"), ("p2", "c")}


def test_load_synonyms_and_tuned_edges_start_empty(store, small_graph: str) -> None:
    assert store.load_synonyms() == []
    assert store.load_tuned_edges() == []


# ------------------------------------------------------------- graph edits


def test_set_node_boost_shows_up_in_load_entities(store, small_graph: str) -> None:
    store.set_node_boost("a", 1.5)
    rows = {r["id"]: r for r in store.load_entities()}
    assert rows["a"]["boost"] == 1.5
    assert rows["b"]["boost"] == 1.0
    assert store.get_entities(["a"])[0]["boost"] == 1.5


def test_set_and_clear_edge_weight(store, small_graph: str) -> None:
    store.set_edge_weight("b", "a", 3.0)
    assert store.load_tuned_edges() == [{"a": "a", "b": "b", "weight": 3.0}]
    store.set_edge_weight("a", "b", 0.0)  # same pair, either order: updated, not duplicated
    assert store.load_tuned_edges() == [{"a": "a", "b": "b", "weight": 0.0}]
    store.clear_edge_weight("b", "a")
    assert store.load_tuned_edges() == []


def test_edge_weights_work_between_an_entity_and_a_passage(store, small_graph: str) -> None:
    store.set_edge_weight("p1", "a", 0.5)
    assert store.load_tuned_edges() == [{"a": "a", "b": "p1", "weight": 0.5}]


def test_edge_weights_for_unknown_nodes_are_ignored(store, small_graph: str) -> None:
    store.set_edge_weight("a", "nope", 2.0)
    assert store.load_tuned_edges() == []
    store.clear_edge_weight("a", "nope")  # must not raise
