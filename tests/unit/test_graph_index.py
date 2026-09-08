"""
hipporag/graph_index.py: the in-memory graph built from store rows.

We build a tiny hand-made graph through the store's own write methods, so the
same test runs against FakeStore locally and real Neo4j in CI:

    p1 -MENTIONS-> a, b          p1 -STATES-> f1 (a rel b)
    p2 -MENTIONS-> a, b, c       p2 -STATES-> f1, f2 (b rel2 c)
    p3 -MENTIONS-> d             (an island: nothing links d to the rest)
    a ~ c  SYNONYM 0.9           b - c  TUNED 5.0

The code half hangs off the island on purpose, so the existing PPR assertions
(seeded at `a`, nothing reaches `d` or `p3`) keep meaning what they said:

    sym_f -CONTAINS 1.0-> sym_g   sym_f -INVOKES 0.9-> sym_g   sym_g -READS 0.85-> data_t
    sym_f, sym_g, data_t, c1, c2 -DEFINED_IN-> p3
    p3 -REFERS_TO 0.85-> sym_g    c1 -MODIFIES 1.0-> sym_f     c1 -PRECEDES-> c2
    d ~ sym_f  SYNONYM 0.7        (cross-kind: it is a code term, not an entity synonym)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from hippo.hipporag.graph_index import (
    COMMIT,
    DATA,
    ENTITY,
    MAX_SCALED_GRAPHS,
    PASSAGE,
    SYMBOL,
    Edge,
    EdgeEdit,
    GraphIndex,
    build_igraph,
)

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
    sym_f: str
    sym_g: str
    data_t: str
    c1: str
    c2: str


@pytest.fixture
def tiny(store) -> Tiny:
    source_id = store.create_source("text", "Tiny corpus")
    ids = Tiny(
        source_id,
        "passage-1",
        "passage-2",
        "passage-3",
        "entity-a",
        "entity-b",
        "entity-c",
        "entity-d",
        "fact-1",
        "fact-2",
        "symbol-f",
        "symbol-g",
        "data-t",
        "commit-1",
        "commit-2",
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

    store.add_symbols(
        [
            {
                "id": ids.sym_f,
                "source_id": source_id,
                "name": "OrderService",
                "qualname": "pyapp.orders.OrderService",
                "kind": "class",
                "lang": "python",
                "path": "pyapp/orders.py",
                "line_start": 9,
                "line_end": 40,
                "embedding": VEC_A,
            },
            {
                "id": ids.sym_g,
                "source_id": source_id,
                "name": "place",
                "qualname": "pyapp.orders.OrderService.place",
                "kind": "method",
                "lang": "python",
                "path": "pyapp/orders.py",
                "line_start": 16,
                "line_end": 23,
                "embedding": VEC_B,
            },
        ]
    )
    store.add_data_objects(
        [
            {
                "id": ids.data_t,
                "source_id": source_id,
                "name": "orders",
                "qualname": "orders",
                "kind": "table",
                "dialect": "sql",
                "embedding": VEC_C,
            }
        ]
    )
    store.add_commits(
        [
            {"id": ids.c1, "source_id": source_id, "sha": "aaaaaaa", "ordinal": 0, "message": "first"},
            {"id": ids.c2, "source_id": source_id, "sha": "bbbbbbb", "ordinal": 1, "message": "second"},
        ]
    )
    store.add_code_edges(
        [
            # The same pair twice on purpose: the pair's code term is the best of the two.
            {"a": ids.sym_f, "b": ids.sym_g, "kind": "CONTAINS", "omega": 1.0, "provenance": "syntax"},
            {"a": ids.sym_f, "b": ids.sym_g, "kind": "INVOKES", "omega": 0.9, "provenance": "same_file"},
            {"a": ids.sym_g, "b": ids.data_t, "kind": "READS", "omega": 0.85, "provenance": "sql_literal"},
        ]
    )
    store.link_definitions(
        [(ids.sym_f, ids.p3), (ids.sym_g, ids.p3), (ids.data_t, ids.p3), (ids.c1, ids.p3), (ids.c2, ids.p3)]
    )
    store.add_refers_to([{"passage_id": ids.p3, "node_id": ids.sym_g, "omega": 0.85, "token": "place"}])
    store.add_modifies([{"commit_id": ids.c1, "symbol_id": ids.sym_f, "omega": 1.0, "hunk": {"churn": 3}}])
    store.add_precedes([(ids.c1, ids.c2)])
    store.add_synonyms([(ids.d, ids.sym_f, 0.7)])
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


def test_vertices_are_entities_then_code_nodes_then_passages(index: GraphIndex, tiny: Tiny) -> None:
    assert index.num_nodes == 12
    assert index.num_entities == 4  # entities only: not "everything before the passages"
    assert (index.first_code_vertex, index.first_passage_vertex) == (4, 9)
    assert index.node_kind == [ENTITY] * 4 + [SYMBOL, SYMBOL, DATA, COMMIT, COMMIT] + [PASSAGE] * 3
    assert [p.id for p in index.passages] == [tiny.p1, tiny.p2, tiny.p3]
    assert [index.node_ids[v] for v in index.passage_vertices] == [tiny.p1, tiny.p2, tiny.p3]
    assert [index.node_ids[v] for v in index.code_vertices] == [
        tiny.sym_f,
        tiny.sym_g,
        tiny.data_t,
        tiny.c1,
        tiny.c2,
    ]
    assert all(index.idx_of[node_id] == v for v, node_id in enumerate(index.node_ids))


def test_a_passage_vertex_is_still_its_position_after_the_other_vertices(
    index: GraphIndex, tiny: Tiny
) -> None:
    # The arithmetic that makes passages-last safe: put a code vertex after them and this returns a
    # negative index, which serves a passage from the end of the list instead of raising.
    for i, passage in enumerate(index.passages):
        vertex = index.idx_of[passage.id]
        assert vertex == index.first_passage_vertex + i
        assert index.passage_position(vertex) == i
    assert index.passage_by_id(tiny.p3) is index.passages[2]


def test_a_store_with_no_code_puts_passages_straight_after_the_entities(store) -> None:
    source_id = store.create_source("text", "Prose only")
    store.add_passages(
        [
            {
                "id": "passage-1",
                "source_id": source_id,
                "ordinal": 0,
                "title": "One",
                "text": "x",
                "embedding": VEC_A,
            }
        ]
    )
    store.add_entities([{"id": "entity-a", "name": "alpha", "embedding": VEC_A}])
    store.link_passage_entities([("passage-1", "entity-a")])
    index = GraphIndex.load(store)
    assert index.code_nodes == []
    assert index.first_passage_vertex == index.num_entities
    assert index.idx_of["passage-1"] == index.num_entities


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


# ------------------------------------------------------------- code graph


def test_the_weight_rule_is_a_max_so_three_facts_beat_any_code_edge() -> None:
    assert Edge(omega=1.0).weight == 1.0
    assert Edge(fact_count=3, omega=1.0).weight == 3.0
    assert Edge(fact_count=3, omega=1.0).weight_at(3.0) == 3.0  # the cap: a code edge can only tie
    assert Edge(omega=0.9).weight_at(0.0) == 0.0
    assert Edge(omega=0.9).weight_at(2.0) == pytest.approx(1.8)
    assert Edge(tuned=0.25, omega=1.0).weight_at(3.0) == 0.25  # a user set it; nothing scales it


def test_a_pair_keeps_the_best_omega_of_its_relations_and_names_them_all(
    index: GraphIndex, tiny: Tiny
) -> None:
    edge = edge_of(index, tiny.sym_f, tiny.sym_g)
    assert edge.omega == pytest.approx(1.0)  # CONTAINS 1.0 beats INVOKES 0.9
    assert edge.synonym_score == 0.0
    assert sorted(edge.code_kinds) == ["contains", "invokes"]
    assert edge.kinds == ["contains", "invokes"]
    assert edge.weight == pytest.approx(1.0)


def test_defined_in_refers_to_and_modifies_all_reach_the_graph(index: GraphIndex, tiny: Tiny) -> None:
    defined = edge_of(index, tiny.sym_f, tiny.p3)
    assert defined.omega == pytest.approx(1.0)
    assert defined.code_kinds == ["defined_in"]
    assert defined.mention is False  # a weight term of 1.0, not the entity-passage mention flag

    refers = edge_of(index, tiny.p3, tiny.sym_g)
    assert refers.omega == pytest.approx(1.0)  # DEFINED_IN 1.0 beats REFERS_TO 0.85 on the same pair
    assert sorted(refers.code_kinds) == ["defined_in", "refers_to"]

    modifies = edge_of(index, tiny.c1, tiny.sym_f)
    assert modifies.code_kinds == ["modifies"]
    assert modifies.omega == pytest.approx(1.0)


def test_precedes_is_a_directed_edge_only_and_never_reaches_the_graph(index: GraphIndex, tiny: Tiny) -> None:
    # 200 commits would otherwise chain every symbol they touched into one neighbourhood.
    c1, c2 = index.idx_of[tiny.c1], index.idx_of[tiny.c2]
    assert index.edge_between(c1, c2) is None
    assert [e.kind for e in index.out_edges(c1) if e.dst == c2] == ["PRECEDES"]


def test_a_cross_kind_synonym_is_a_code_term_not_an_entity_synonym(index: GraphIndex, tiny: Tiny) -> None:
    edge = edge_of(index, tiny.d, tiny.sym_f)
    assert edge.synonym_score == 0.0  # the unscaled slot stays empty
    assert edge.omega == pytest.approx(0.7)
    assert edge.code_kinds == ["synonym"]
    # An entity-entity synonym is unaffected and still unscaled.
    assert edge_of(index, tiny.a, tiny.c).synonym_score == pytest.approx(0.9)


def test_structural_scale_zero_removes_every_code_vertex_from_the_graph(
    index: GraphIndex, tiny: Tiny
) -> None:
    off = build_igraph(index.num_nodes, index.edges, 0.0)
    for node_id in (tiny.sym_f, tiny.sym_g, tiny.data_t, tiny.c1, tiny.c2):
        assert off.degree(index.idx_of[node_id]) == 0
    # and nothing that was there for prose has moved
    prose_pairs = {(a, b) for (a, b), e in index.edges.items() if e.weight_at(0.0) > 0}
    assert len(off.es) == len(prose_pairs)
    assert dict(index.neighbors(index.idx_of[tiny.a], off)) == dict(index.neighbors(index.idx_of[tiny.a]))


def test_graph_for_scale_returns_the_default_graph_and_memoises_the_rest(index: GraphIndex) -> None:
    assert index.graph_for_scale(1.0) is index.graph
    scaled = index.graph_for_scale(0.5)
    assert scaled is not index.graph
    assert index.graph_for_scale(0.5) is scaled  # memoised per scale


def test_the_per_scale_memo_is_quantized_and_bounded(index: GraphIndex) -> None:
    # AR1 fix 2: `code_structural_scale` is a user-supplied float and the settings form steps it
    # by 0.01, so an unbounded memo keyed by the raw float is one full igraph per slider position.
    assert index.graph_for_scale(0.5) is index.graph_for_scale(0.501)
    assert index.graph_for_scale(0.999) is index.graph  # rounds to the default, no rebuild

    for step in range(0, 90):
        index.graph_for_scale(step / 100)
    assert len(index._scaled) <= MAX_SCALED_GRAPHS

    kept = index.graph_for_scale(0.89)  # the most recent survives, the oldest was evicted
    assert index.graph_for_scale(0.89) is kept
    assert 0.0 not in index._scaled


def test_specificity_is_mention_count_for_entities_and_in_degree_plus_one_for_code(
    index: GraphIndex, tiny: Tiny
) -> None:
    assert index.specificity is index.entity_passage_count  # the old name still works
    assert index.specificity[index.idx_of[tiny.a]] == 2
    assert index.specificity[index.idx_of[tiny.sym_f]] == 1  # nothing INVOKES/READS/WRITES it
    assert index.specificity[index.idx_of[tiny.sym_g]] == 2  # one INVOKES in
    assert index.specificity[index.idx_of[tiny.data_t]] == 2  # one READS in
    assert index.specificity[index.idx_of[tiny.c1]] == 1  # a commit is always 1
    assert index.specificity[index.idx_of[tiny.p3]] == 0  # a passage is never seeded this way


def test_contains_does_not_count_towards_specificity(index: GraphIndex, tiny: Tiny) -> None:
    # sym_g has both a CONTAINS and an INVOKES pointing at it; only the INVOKES damps it.
    assert index.specificity[index.idx_of[tiny.sym_g]] == 2


def test_out_edges_and_in_edges_keep_the_direction(index: GraphIndex, tiny: Tiny) -> None:
    f, g, t = (index.idx_of[x] for x in (tiny.sym_f, tiny.sym_g, tiny.data_t))
    out = {(e.kind, e.dst) for e in index.out_edges(f)}
    assert ("CONTAINS", g) in out and ("INVOKES", g) in out
    assert {(e.kind, e.src) for e in index.in_edges(t)} == {("READS", g)}
    assert index.in_edges(f) and all(e.dst == f for e in index.in_edges(f))
    assert index.out_edges(index.num_nodes + 99) == []


def test_directed_edges_carry_provenance_and_extra(index: GraphIndex, tiny: Tiny) -> None:
    invokes = next(e for e in index.out_edges(index.idx_of[tiny.sym_f]) if e.kind == "INVOKES")
    assert (invokes.omega, invokes.provenance) == (pytest.approx(0.9), "same_file")
    modifies = next(e for e in index.out_edges(index.idx_of[tiny.c1]) if e.kind == "MODIFIES")
    assert modifies.extra == {"churn": 3}


def test_defining_passages_and_symbols_defined_in_are_two_sides_of_one_edge(
    index: GraphIndex, tiny: Tiny
) -> None:
    p3 = index.idx_of[tiny.p3]
    assert index.defining_passages(index.idx_of[tiny.sym_f]) == [p3]
    assert set(index.symbols_defined_in(p3)) == {
        index.idx_of[x] for x in (tiny.sym_f, tiny.sym_g, tiny.data_t, tiny.c1, tiny.c2)
    }


def test_code_nodes_carry_their_stored_fields(index: GraphIndex, tiny: Tiny) -> None:
    node = index.code_node_by_id(tiny.sym_g)
    assert node is not None
    assert (node.kind, node.code_kind, node.name) == (SYMBOL, "method", "place")
    assert node.qualname == "pyapp.orders.OrderService.place"
    assert (node.path, node.line_start, node.line_end) == ("pyapp/orders.py", 16, 23)
    assert index.code_node_by_id(tiny.a) is None  # an entity is not a code node
    assert index.code_node_by_id("symbol-nope") is None
    assert index.code_node_by_id(tiny.data_t).code_kind == "table"
    assert index.code_node_by_id(tiny.c1).name == "aaaaaaa"  # a commit shows its short sha


def test_name_of_a_code_vertex_is_its_qualname(index: GraphIndex, tiny: Tiny) -> None:
    # `full_graph` calls name_of on every vertex; before the passages moved last this read a
    # passage at a negative index instead.
    assert index.name_of(index.idx_of[tiny.sym_g]) == "pyapp.orders.OrderService.place"
    assert index.name_of(index.idx_of[tiny.data_t]) == "orders"
    assert index.name_of(index.idx_of[tiny.a]) == "alpha"
    assert index.name_of(index.idx_of[tiny.p1]) == "First"


def test_name_index_maps_names_qualnames_and_split_tokens(index: GraphIndex, tiny: Tiny) -> None:
    assert index.name_index["place"] == [tiny.sym_g]
    assert index.name_index["orderservice"] == [tiny.sym_f]
    assert index.name_index["pyapp.orders.orderservice.place"] == [tiny.sym_g]
    assert index.name_index["order"] == [tiny.sym_f]  # a split token of OrderService
    assert index.name_index["service"] == [tiny.sym_f]
    assert "nothing" not in index.name_index


def test_graph_with_edits_copies_the_code_fields(index: GraphIndex, tiny: Tiny) -> None:
    # It rebuilds every Edge with `Edge(**vars(v))`, so this is free - but only while omega and
    # code_kinds are real fields; the test is what pins that.
    edited = index.graph_with_edits([EdgeEdit(tiny.a, tiny.b, 0.5)])
    f, g = index.idx_of[tiny.sym_f], index.idx_of[tiny.sym_g]
    assert dict(index.neighbors(f, edited))[g] == pytest.approx(1.0)
    assert dict(index.neighbors(index.idx_of[tiny.a], edited))[index.idx_of[tiny.b]] == 0.5


def test_graph_with_edits_composes_with_the_scale(index: GraphIndex, tiny: Tiny) -> None:
    # Moving the slider and editing an edge in one simulation must apply both.
    edited = index.graph_with_edits([EdgeEdit(tiny.a, tiny.b, 0.5)], 0.0)
    assert edited.degree(index.idx_of[tiny.sym_f]) == 0
    assert dict(index.neighbors(index.idx_of[tiny.a], edited))[index.idx_of[tiny.b]] == 0.5
    assert index.graph_with_edits([], 0.0) is index.graph_for_scale(0.0)


def test_community_labels_come_from_the_smallest_member_qualname(store, tiny: Tiny) -> None:
    store.set_symbol_communities({tiny.sym_f: 2, tiny.sym_g: 2})
    index = GraphIndex.load(store)
    assert index.community_of(index.idx_of[tiny.sym_f]) == 2
    assert index.community_name(2) == "pyapp.orders.OrderService"
    assert index.community_name(None) == ""
    assert index.community_of(index.idx_of[tiny.a]) is None


# -------------------------------------------------------- stale vertices


def test_neighbors_of_a_vertex_that_is_not_in_the_graph_is_empty(index: GraphIndex) -> None:
    # A trace recorded before a reload can name a vertex that no longer exists. igraph would
    # raise (and an igraph error in a worker thread can abort the process); we answer "none".
    assert index.neighbors(index.num_nodes) == []
    assert index.neighbors(index.num_nodes + 1000) == []
    assert index.neighbors(-1) == []
    assert index.neighbors(index.num_nodes, index.graph_with_edits([])) == []
    assert index.neighbors(0) != []  # a real vertex still has its neighbours
