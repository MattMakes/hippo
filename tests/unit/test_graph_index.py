"""
hipporag/graph_index.py: the in-memory graph built from store rows.

We build a tiny hand-made graph through the store's own write methods, so the
same test runs against FakeStore locally and real Neo4j in CI:

    p1 -MENTIONS-> a, b          p1 -STATES-> f1 (a rel b)
    p2 -MENTIONS-> a, b, c       p2 -STATES-> f1, f2 (b rel2 c)
    p3 -MENTIONS-> d             (an island: nothing links d to the rest)
    a ~ c  SYNONYM 0.9           b - c  TUNED 5.0
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from hippo.hipporag.graph_index import ENTITY, PASSAGE, Edge, EdgeEdit, GraphIndex

# Short, distinct unit vectors: fine for the store and easy to read.
VEC_A = [1.0, 0.0, 0.0]
VEC_B = [0.0, 1.0, 0.0]
VEC_C = [0.0, 0.0, 1.0]


@dataclass
class Tiny:
    """Ids of everything the fixture created, for readable assertions."""

    source_id: str
    p1: str
    p2: str
    p3: str
    a: str
    b: str
    c: str
    d: str
    f1: str
    f2: str


@pytest.fixture
def tiny(store) -> Tiny:
    source_id = store.create_source("text", "Tiny corpus")
    ids = Tiny(
        source_id,
        "passage-1",
        "passage-2",
        "passage-3",
        "ent-a",
        "ent-b",
        "ent-c",
        "ent-d",
        "fact-1",
        "fact-2",
    )
    store.add_passages(
        [
            {
                "id": ids.p1,
                "source_id": source_id,
                "ordinal": 0,
                "title": "First",
                "text": "a rel b",
                "embedding": VEC_A,
            },
            {
                "id": ids.p2,
                "source_id": source_id,
                "ordinal": 1,
                "title": "Second",
                "text": "b rel2 c",
                "embedding": VEC_B,
            },
            {
                "id": ids.p3,
                "source_id": source_id,
                "ordinal": 2,
                "title": "Island",
                "text": "d alone",
                "embedding": VEC_C,
            },
        ]
    )
    store.add_entities(
        [
            {"id": ids.a, "name": "alpha", "embedding": VEC_A},
            {"id": ids.b, "name": "beta", "embedding": VEC_B},
            {"id": ids.c, "name": "gamma", "embedding": VEC_C},
            {"id": ids.d, "name": "delta", "embedding": VEC_C},
        ]
    )
    store.add_facts(
        [
            {
                "id": ids.f1,
                "subject": "alpha",
                "predicate": "rel",
                "object": "beta",
                "subject_id": ids.a,
                "object_id": ids.b,
                "embedding": VEC_A,
            },
            {
                "id": ids.f2,
                "subject": "beta",
                "predicate": "rel2",
                "object": "gamma",
                "subject_id": ids.b,
                "object_id": ids.c,
                "embedding": VEC_B,
            },
        ]
    )
    store.link_passage_entities(
        [(ids.p1, ids.a), (ids.p1, ids.b), (ids.p2, ids.a), (ids.p2, ids.b), (ids.p2, ids.c), (ids.p3, ids.d)]
    )
    store.link_passage_facts([(ids.p1, ids.f1), (ids.p2, ids.f1), (ids.p2, ids.f2)])
    store.add_synonyms([(ids.a, ids.c, 0.9)])
    store.set_edge_weight(ids.b, ids.c, 5.0)
    store.bump_graph_version()
    return ids


@pytest.fixture
def index(store, tiny: Tiny) -> GraphIndex:
    return GraphIndex.load(store)


def edge_of(index: GraphIndex, x: str, y: str) -> Edge:
    edge = index.edge_between(index.idx_of[x], index.idx_of[y])
    assert edge is not None, f"no edge between {x} and {y}"
    return edge


# ------------------------------------------------------------- the Edge rule


def test_edge_weight_is_the_max_of_fact_count_mention_and_synonym() -> None:
    assert Edge().weight == 0.0
    assert Edge(fact_count=3).weight == 3.0
    assert Edge(mention=True).weight == 1.0
    assert Edge(synonym_score=0.85).weight == 0.85
    assert Edge(fact_count=1, mention=True, synonym_score=0.95).weight == 1.0
    assert Edge(fact_count=2, synonym_score=0.95).weight == 2.0


def test_a_tuned_weight_replaces_the_computed_one_even_when_zero() -> None:
    assert Edge(fact_count=3, mention=True, tuned=0.25).weight == 0.25
    assert Edge(fact_count=3, tuned=0.0).weight == 0.0


def test_edge_kinds_list_every_reason_the_edge_exists() -> None:
    assert Edge().kinds == []
    assert Edge(fact_count=1, mention=True, synonym_score=0.9, tuned=2.0).kinds == [
        "fact",
        "mention",
        "synonym",
        "tuned",
    ]
    assert Edge(synonym_score=0.0).kinds == []


# ----------------------------------------------------------------- loading


def test_vertices_are_entities_first_then_passages_in_source_order(index: GraphIndex, tiny: Tiny) -> None:
    assert index.num_nodes == 7
    assert index.num_entities == 4
    assert index.node_kind[: index.num_entities] == [ENTITY] * 4
    assert index.node_kind[index.num_entities :] == [PASSAGE] * 3
    assert [p.id for p in index.passages] == [tiny.p1, tiny.p2, tiny.p3]
    assert [index.node_ids[v] for v in index.passage_vertices] == [tiny.p1, tiny.p2, tiny.p3]
    assert all(index.idx_of[node_id] == v for v, node_id in enumerate(index.node_ids))


def test_version_comes_from_the_store_unless_given(store, tiny: Tiny) -> None:
    assert GraphIndex.load(store).version == store.graph_version()
    assert GraphIndex.load(store, version=42).version == 42


def test_passage_and_fact_rows_are_loaded(index: GraphIndex, tiny: Tiny) -> None:
    first = index.passage_by_id(tiny.p1)
    assert first is not None
    assert (first.title, first.text, first.source_id, first.source_name, first.ordinal) == (
        "First",
        "a rel b",
        tiny.source_id,
        "Tiny corpus",
        0,
    )
    assert index.passage_embeddings.shape == (3, 3)
    assert index.fact_embeddings.shape == (2, 3)
    fact = index.facts[index.fact_index_of[tiny.f1]]
    assert fact.triple == ["alpha", "rel", "beta"]
    assert (fact.subject_id, fact.object_id) == (tiny.a, tiny.b)
    assert sorted(fact.passage_ids) == [tiny.p1, tiny.p2]


def test_a_fact_stated_by_two_passages_gives_weight_two(index: GraphIndex, tiny: Tiny) -> None:
    edge = edge_of(index, tiny.a, tiny.b)
    assert edge.fact_count == 2
    assert edge.weight == 2.0
    assert edge.kinds == ["fact"]


def test_a_mention_gives_weight_one(index: GraphIndex, tiny: Tiny) -> None:
    edge = edge_of(index, tiny.p1, tiny.a)
    assert edge.mention is True
    assert edge.weight == 1.0
    assert edge.kinds == ["mention"]


def test_a_synonym_gives_its_score(index: GraphIndex, tiny: Tiny) -> None:
    edge = edge_of(index, tiny.a, tiny.c)
    assert edge.synonym_score == pytest.approx(0.9)
    assert edge.weight == pytest.approx(0.9)
    assert edge.kinds == ["synonym"]


def test_a_tuned_edge_overrides_the_fact_count(index: GraphIndex, tiny: Tiny) -> None:
    edge = edge_of(index, tiny.b, tiny.c)
    assert edge.fact_count == 1
    assert edge.tuned == 5.0
    assert edge.weight == 5.0
    assert edge.kinds == ["fact", "tuned"]


def test_unrelated_nodes_have_no_edge(index: GraphIndex, tiny: Tiny) -> None:
    assert index.edge_between(index.idx_of[tiny.a], index.idx_of[tiny.d]) is None
    assert index.edge_between(index.idx_of[tiny.p1], index.idx_of[tiny.p2]) is None


def test_edge_between_does_not_care_about_order(index: GraphIndex, tiny: Tiny) -> None:
    a, b = index.idx_of[tiny.a], index.idx_of[tiny.b]
    assert index.edge_between(a, b) is index.edge_between(b, a)


def test_igraph_carries_the_same_weights(index: GraphIndex, tiny: Tiny) -> None:
    a = index.idx_of[tiny.a]
    weights = dict(index.neighbors(a))
    assert weights == {
        index.idx_of[tiny.b]: 2.0,
        index.idx_of[tiny.c]: pytest.approx(0.9),
        index.idx_of[tiny.p1]: 1.0,
        index.idx_of[tiny.p2]: 1.0,
    }
    assert index.graph.ecount() == len(index.edges)


def test_passage_count_is_how_many_passages_mention_the_entity(index: GraphIndex, tiny: Tiny) -> None:
    assert index.entity_passage_count[index.idx_of[tiny.a]] == 2
    assert index.entity_passage_count[index.idx_of[tiny.c]] == 1
    assert index.entity_passage_count[index.idx_of[tiny.p1]] == 0


def test_boosts_default_to_one_and_follow_set_node_boost(store, tiny: Tiny) -> None:
    before = GraphIndex.load(store)
    assert before.entity_boost.tolist() == [1.0] * before.num_nodes
    store.set_node_boost(tiny.a, 1.5)
    after = GraphIndex.load(store)
    assert after.entity_boost[after.idx_of[tiny.a]] == 1.5
    assert after.entity_boost[after.idx_of[tiny.b]] == 1.0


# ----------------------------------------------------------------- lookups


def test_name_of_gives_entity_names_and_passage_titles(index: GraphIndex, tiny: Tiny) -> None:
    assert index.name_of(index.idx_of[tiny.a]) == "alpha"
    assert index.name_of(index.idx_of[tiny.p2]) == "Second"
    assert index.entity_names[tiny.d] == "delta"


def test_passage_by_id_returns_none_for_unknown_or_entity_ids(index: GraphIndex, tiny: Tiny) -> None:
    assert index.passage_by_id("passage-nope") is None
    assert index.passage_by_id(tiny.a) is None
    assert index.passage_position(index.idx_of[tiny.p3]) == 2


def test_an_empty_store_loads_an_empty_index(store) -> None:
    index = GraphIndex.load(store)
    assert index.is_empty()
    assert index.num_nodes == 0
    assert index.passage_embeddings.shape == (0, 0)
    assert index.fact_embeddings.shape == (0, 0)
    assert index.graph.ecount() == 0


def test_a_loaded_index_is_not_empty(index: GraphIndex) -> None:
    assert not index.is_empty()


# --------------------------------------------------------------------- PPR


def test_ppr_scores_sum_to_one_and_favour_the_seed_and_its_neighbours(index: GraphIndex, tiny: Tiny) -> None:
    reset = np.zeros(index.num_nodes)
    reset[index.idx_of[tiny.a]] = 1.0

    scores = index.ppr(reset, damping=0.5)

    assert scores.shape == (index.num_nodes,)
    assert scores.sum() == pytest.approx(1.0)
    a, b, c, d = (index.idx_of[x] for x in (tiny.a, tiny.b, tiny.c, tiny.d))
    assert scores[a] == max(scores)
    assert scores[b] > scores[c] > 0  # b is the stronger neighbour (weight 2 vs 0.9)
    assert scores[d] == pytest.approx(0.0)  # the island gets nothing
    assert scores[index.idx_of[tiny.p3]] == pytest.approx(0.0)


def test_ppr_with_no_damping_stays_on_the_seeds(index: GraphIndex, tiny: Tiny) -> None:
    reset = np.zeros(index.num_nodes)
    reset[index.idx_of[tiny.a]] = 3.0
    reset[index.idx_of[tiny.b]] = 1.0
    scores = index.ppr(reset, damping=0.0)
    assert scores[index.idx_of[tiny.a]] == pytest.approx(0.75)
    assert scores[index.idx_of[tiny.b]] == pytest.approx(0.25)


def test_ppr_treats_negative_and_nan_seed_weights_as_zero(index: GraphIndex, tiny: Tiny) -> None:
    reset = np.zeros(index.num_nodes)
    reset[index.idx_of[tiny.a]] = 1.0
    reset[index.idx_of[tiny.d]] = -1.0
    reset[index.idx_of[tiny.c]] = np.nan
    scores = index.ppr(reset, damping=0.5)
    assert scores.sum() == pytest.approx(1.0)
    assert scores[index.idx_of[tiny.d]] == pytest.approx(0.0)


def test_ppr_refuses_an_all_zero_reset(index: GraphIndex) -> None:
    with pytest.raises(ValueError, match="at least one seed"):
        index.ppr(np.zeros(index.num_nodes), damping=0.5)


# ---------------------------------------------------------- what-if edits


def test_graph_with_edits_removes_an_edge_when_the_weight_is_zero(index: GraphIndex, tiny: Tiny) -> None:
    edited = index.graph_with_edits([EdgeEdit(tiny.a, tiny.b, 0.0)])
    a, b = index.idx_of[tiny.a], index.idx_of[tiny.b]
    assert edited.ecount() == index.graph.ecount() - 1
    assert b not in dict(index.neighbors(a, edited))
    assert b in dict(index.neighbors(a))  # the original graph is untouched
    assert index.edge_between(a, b).weight == 2.0


def test_graph_with_edits_changes_and_adds_edges(index: GraphIndex, tiny: Tiny) -> None:
    edited = index.graph_with_edits([EdgeEdit(tiny.a, tiny.b, 0.5), EdgeEdit(tiny.d, tiny.a, 7.0)])
    a = index.idx_of[tiny.a]
    weights = dict(index.neighbors(a, edited))
    assert weights[index.idx_of[tiny.b]] == 0.5
    assert weights[index.idx_of[tiny.d]] == 7.0
    assert edited.ecount() == index.graph.ecount() + 1


def test_graph_with_edits_ignores_unknown_ids_and_self_loops(index: GraphIndex, tiny: Tiny) -> None:
    edited = index.graph_with_edits([EdgeEdit("nope", tiny.a, 1.0), EdgeEdit(tiny.a, tiny.a, 1.0)])
    assert edited.ecount() == index.graph.ecount()


def test_graph_with_no_edits_is_the_original_graph(index: GraphIndex) -> None:
    assert index.graph_with_edits([]) is index.graph


def test_edited_graph_changes_ppr(index: GraphIndex, tiny: Tiny) -> None:
    reset = np.zeros(index.num_nodes)
    reset[index.idx_of[tiny.a]] = 1.0
    before = index.ppr(reset, damping=0.5)
    edited = index.graph_with_edits([EdgeEdit(tiny.a, tiny.b, 0.0)])
    after = index.ppr(reset, damping=0.5, graph=edited)
    assert after[index.idx_of[tiny.b]] < before[index.idx_of[tiny.b]]
    assert after.sum() == pytest.approx(1.0)


# -------------------------------------------------------- stale vertices


def test_neighbors_of_a_vertex_that_is_not_in_the_graph_is_empty(index: GraphIndex) -> None:
    # A trace recorded before a reload can name a vertex that no longer exists. igraph would
    # raise (and an igraph error in a worker thread can abort the process); we answer "none".
    assert index.neighbors(index.num_nodes) == []
    assert index.neighbors(index.num_nodes + 1000) == []
    assert index.neighbors(-1) == []
    assert index.neighbors(index.num_nodes, index.graph_with_edits([])) == []
    assert index.neighbors(0) != []  # a real vertex still has its neighbours
