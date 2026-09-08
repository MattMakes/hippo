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
                "id": "passage-1",
                "source_id": source_id,
                "ordinal": 0,
                "title": "One",
                "text": "t1",
                "embedding": VEC,
            },
            {
                "id": "passage-2",
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
            {"id": "entity-a", "name": "alpha", "embedding": VEC},
            {"id": "entity-b", "name": "beta", "embedding": VEC2},
            {"id": "entity-c", "name": "gamma", "embedding": VEC},
        ]
    )
    store.add_facts(
        [
            {
                "id": "fact-1",
                "subject": "entity-a",
                "predicate": "rel",
                "object": "entity-b",
                "subject_id": "entity-a",
                "object_id": "entity-b",
                "embedding": VEC,
            },
            {
                "id": "fact-self",
                "subject": "entity-c",
                "predicate": "is",
                "object": "entity-c",
                "subject_id": "entity-c",
                "object_id": "entity-c",
                "embedding": VEC,
            },
        ]
    )
    store.link_passage_entities([("passage-1", "entity-a"), ("passage-1", "entity-b"), ("passage-2", "entity-a"), ("passage-2", "entity-b"), ("passage-2", "entity-c")])
    store.link_passage_facts([("passage-1", "fact-1"), ("passage-2", "fact-1"), ("passage-2", "fact-self")])
    return source_id


# ------------------------------------------------------------- load_* rows


def test_load_entities_rows(store, small_graph: str) -> None:
    rows = {r["id"]: r for r in store.load_entities()}
    created_at = rows["entity-a"].pop("created_at")  # set on creation; the graph loader sorts by it
    assert created_at
    assert rows["entity-a"] == {"id": "entity-a", "name": "alpha", "boost": 1.0, "passage_count": 2}
    assert rows["entity-c"]["passage_count"] == 1


def test_load_passages_rows(store, small_graph: str) -> None:
    rows = {r["id"]: r for r in store.load_passages()}
    assert set(rows) == {"passage-1", "passage-2"}
    assert rows["passage-1"]["title"] == "One" and rows["passage-1"]["ordinal"] == 0
    assert list(rows["passage-1"]["embedding"]) == VEC
    assert (rows["passage-1"]["source_id"], rows["passage-1"]["source_name"]) == (small_graph, "Src")


def test_load_facts_rows(store, small_graph: str) -> None:
    rows = {r["id"]: r for r in store.load_facts()}
    assert set(rows) == {"fact-1", "fact-self"}
    assert sorted(rows["fact-1"]["passage_ids"]) == ["passage-1", "passage-2"]
    assert list(rows["fact-1"]["embedding"]) == VEC
    assert (rows["fact-1"]["subject_id"], rows["fact-1"]["object_id"]) == ("entity-a", "entity-b")


def test_a_fact_in_two_passages_counts_twice_and_self_loops_are_excluded(store, small_graph: str) -> None:
    assert store.load_fact_edges() == [{"a": "entity-a", "b": "entity-b", "weight": 2}]


def test_load_mentions_rows(store, small_graph: str) -> None:
    mentions = {(m["passage_id"], m["entity_id"]) for m in store.load_mentions()}
    assert mentions == {("passage-1", "entity-a"), ("passage-1", "entity-b"), ("passage-2", "entity-a"), ("passage-2", "entity-b"), ("passage-2", "entity-c")}


def test_load_synonyms_and_tuned_edges_start_empty(store, small_graph: str) -> None:
    assert store.load_synonyms() == []
    assert store.load_tuned_edges() == []


# ------------------------------------------------------------- graph edits


def test_set_node_boost_shows_up_in_load_entities(store, small_graph: str) -> None:
    store.set_node_boost("entity-a", 1.5)
    rows = {r["id"]: r for r in store.load_entities()}
    assert rows["entity-a"]["boost"] == 1.5
    assert rows["entity-b"]["boost"] == 1.0
    assert store.get_entities(["entity-a"])[0]["boost"] == 1.5


def test_set_and_clear_edge_weight(store, small_graph: str) -> None:
    store.set_edge_weight("entity-b", "entity-a", 3.0)
    assert store.load_tuned_edges() == [{"a": "entity-a", "b": "entity-b", "weight": 3.0}]
    store.set_edge_weight("entity-a", "entity-b", 0.0)  # same pair, either order: updated, not duplicated
    assert store.load_tuned_edges() == [{"a": "entity-a", "b": "entity-b", "weight": 0.0}]
    store.clear_edge_weight("entity-b", "entity-a")
    assert store.load_tuned_edges() == []


def test_edge_weights_work_between_an_entity_and_a_passage(store, small_graph: str) -> None:
    store.set_edge_weight("passage-1", "entity-a", 0.5)
    assert store.load_tuned_edges() == [{"a": "entity-a", "b": "passage-1", "weight": 0.5}]


def test_edge_weights_for_unknown_nodes_are_ignored(store, small_graph: str) -> None:
    store.set_edge_weight("entity-a", "nope", 2.0)
    assert store.load_tuned_edges() == []
    store.clear_edge_weight("entity-a", "nope")  # must not raise
