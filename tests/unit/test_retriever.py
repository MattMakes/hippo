"""
hipporag/retriever.py: question -> facts -> filter -> PPR -> ranked passages.

The sample corpus is indexed for real (FakeStore + FakeOllama), one passage per
"## " section, and then searched. The fake filter keeps facts that share a
content word with the question, which is enough to make the sample questions
land where the paper says they should.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from hippo import prompts
from hippo.ask import answer_from_trace
from hippo.codegraph.model import symbol_id
from hippo.hipporag.graph_index import CODE_KINDS, EdgeEdit, GraphIndex
from hippo.hipporag.indexer import Chunk, index_source
from hippo.hipporag.retriever import (
    MAX_CODE_SEEDS,
    TRACE_CANDIDATES,
    Retriever,
    SelectResult,
    Trace,
    match_triples,
    trace_from_dict,
)
from hippo.hipporag.text import entity_id
from hippo.store.base import DEFAULT_SETTINGS
from tests.conftest import index_code_sample, index_prose_sample
from tests.fakes.code_fixture import write_commit_history

DIRECT = "Where is Acme Robotics headquartered?"
MULTI_HOP = "In which state is the company founded by Priya Natarajan headquartered?"


def sample_chunks(sample_text: str) -> list[Chunk]:
    chunks = []
    for ordinal, section in enumerate(sample_text.split("## ")[1:]):
        title, _, body = section.partition("\n")
        chunks.append(Chunk(ordinal, title.strip(), body.strip()))
    return chunks


@pytest.fixture
def retriever(store, ollama, sample_text: str) -> Retriever:
    source_id = store.create_source("sample", "Acme Robotics")
    index_source(store, ollama, source_id, sample_chunks(sample_text))
    return Retriever(GraphIndex.load(store), ollama)


def settings(**overrides) -> dict:
    return {**DEFAULT_SETTINGS, **overrides}


def titles(trace: Trace) -> list[str]:
    return [p.title for p in trace.passages]


# ----------------------------------------------------------------- ranking


def test_the_direct_question_ranks_the_company_passage_first(retriever: Retriever) -> None:
    trace = retriever.retrieve(DIRECT, settings())
    assert not trace.used_dpr_fallback
    assert titles(trace)[0] == "The company"
    assert trace.passages[0].rank == 1
    assert trace.passages[0].score > trace.passages[1].score


def test_the_multi_hop_question_puts_the_bridge_passage_in_the_top_three(retriever: Retriever) -> None:
    trace = retriever.retrieve(MULTI_HOP, settings())
    assert not trace.used_dpr_fallback
    assert "Where things are" in titles(trace)[:3]
    assert titles(trace)[0] == "The company"


def test_every_passage_is_returned_once_with_consecutive_ranks(retriever: Retriever) -> None:
    trace = retriever.retrieve(DIRECT, settings())
    assert len(trace.passages) == 8
    assert [p.rank for p in trace.passages] == list(range(1, 9))
    assert len({p.passage_id for p in trace.passages}) == 8
    assert sorted(p.dpr_rank for p in trace.passages) == list(range(1, 9))


def test_ranked_passages_carry_source_and_preview(retriever: Retriever) -> None:
    top = retriever.retrieve(DIRECT, settings()).passages[0]
    assert top.source_name == "Acme Robotics"
    assert top.preview.startswith("Acme Robotics was founded in 2015")
    assert len(top.preview) <= 240
    assert 0.0 <= top.dpr_score <= 1.0


def test_retrieval_top_k_limits_the_passages(retriever: Retriever) -> None:
    trace = retriever.retrieve(DIRECT, settings(retrieval_top_k=3))
    assert len(trace.passages) == 3


# ------------------------------------------------------------------- trace


def test_trace_records_candidates_filter_seeds_top_nodes_and_timing(retriever: Retriever) -> None:
    trace = retriever.retrieve(DIRECT, settings())

    assert trace.question == DIRECT
    assert trace.settings == settings()
    assert trace.graph_version == retriever.index.version

    candidates = trace.fact_candidates
    assert 0 < len(candidates) <= TRACE_CANDIDATES
    assert [c.rank for c in candidates] == list(range(1, len(candidates) + 1))
    assert sum(c.sent_to_filter for c in candidates) == settings()["linking_top_k"]
    assert all(c.sent_to_filter for c in candidates[:5])
    assert {c.reason for c in candidates if c.sent_to_filter} <= {"kept by filter", "dropped by filter"}
    assert {c.reason for c in candidates if not c.sent_to_filter} == {"not sent to filter"}
    assert all(not c.kept for c in candidates if not c.sent_to_filter)
    assert candidates[0].triple == ["acme robotics", "is headquartered in", "boulder"]
    assert candidates[0].kept and candidates[0].score == 1.0
    assert all(c.passage_ids for c in candidates)

    assert trace.filter["replayed"] is False
    assert trace.filter["kept_triples"][0] == candidates[0].triple
    assert trace.filter["raw_response"]

    weights = [s.weight for s in trace.seed_entities]
    assert weights == sorted(weights, reverse=True)
    assert all(s.kept for s in trace.seed_entities)
    assert {"acme robotics", "boulder"} <= {s.name for s in trace.seed_entities}
    boulder = next(s for s in trace.seed_entities if s.name == "boulder")
    assert boulder.passage_count == 2 and boulder.boost == 1.0
    assert boulder.weight == pytest.approx(boulder.fact_score_sum / boulder.occurrences)
    assert set(boulder.from_fact_ids) <= set(trace.kept_fact_ids())

    assert len(trace.seed_passages) == 8
    assert trace.seed_passages[0].title == "The company"
    assert trace.seed_passages[0].weight == pytest.approx(trace.seed_passages[0].dpr_score * 0.05)

    assert trace.top_nodes and trace.top_nodes[0].kind in {"entity", "passage"}
    assert any(n.is_seed for n in trace.top_nodes)
    assert {n.kind for n in trace.top_nodes} == {"entity", "passage"}
    assert set(trace.timing_ms) == {"embed", "filter", "ppr", "total"}
    assert trace.timing_ms["total"] >= 0


def test_trace_to_dict_is_json_safe_and_round_trips(retriever: Retriever) -> None:
    trace = retriever.retrieve(DIRECT, settings())
    as_dict = trace.to_dict()
    json.dumps(as_dict)
    again = trace_from_dict(json.loads(json.dumps(as_dict)))
    assert again.passages == trace.passages
    assert again.fact_candidates == trace.fact_candidates
    assert again.seed_entities == trace.seed_entities
    assert again.passage_ids() == trace.passage_ids()


# ------------------------------------------------------------------ knobs


def test_node_specificity_divides_seed_weights_by_passage_count(retriever: Retriever) -> None:
    with_spec = {s.name: s for s in retriever.retrieve(DIRECT, settings()).seed_entities}
    without = {s.name: s for s in retriever.retrieve(DIRECT, settings(node_specificity=False)).seed_entities}
    boulder_with, boulder_without = with_spec["boulder"], without["boulder"]
    assert boulder_with.passage_count == 2
    assert boulder_without.weight == pytest.approx(1.0)
    assert boulder_with.weight == pytest.approx(boulder_without.weight / 2)
    assert boulder_with.weight != boulder_without.weight


def test_linking_top_k_zero_falls_back_to_dpr_with_a_reason(retriever: Retriever) -> None:
    trace = retriever.retrieve(DIRECT, settings(linking_top_k=0))
    assert trace.used_dpr_fallback
    assert "linking_top_k = 0" in trace.fallback_reason
    assert not any(c.sent_to_filter for c in trace.fact_candidates)
    assert trace.seed_entities == [] and trace.top_nodes == []
    # In fallback mode passages are ranked by their own similarity to the question.
    assert [p.rank for p in trace.passages] == [p.dpr_rank for p in trace.passages]
    assert all(p.score == p.dpr_score for p in trace.passages)
    assert titles(trace)[0] == "The company"


def test_a_filter_that_keeps_nothing_falls_back_to_dpr(retriever: Retriever) -> None:
    trace = retriever.retrieve(DIRECT, settings(), fact_filter=lambda q, c: ([], "nothing relevant"))
    assert trace.used_dpr_fallback
    assert trace.fallback_reason == "no facts survived the filter"
    assert trace.filter == {"raw_response": "nothing relevant", "kept_triples": [], "replayed": True}
    assert {c.reason for c in trace.fact_candidates if c.sent_to_filter} == {"dropped by filter"}
    assert trace.passages and trace.top_nodes == []


def test_a_replayed_filter_is_used_instead_of_the_llm(retriever: Retriever, fake_ollama) -> None:
    keep_first = lambda question, candidates: (candidates[:1], "replay")  # noqa: E731
    calls_before = len(fake_ollama.calls)  # indexing already made the OpenIE calls
    trace = retriever.retrieve(DIRECT, settings(), fact_filter=keep_first)
    assert trace.kept_fact_ids() == [trace.fact_candidates[0].fact_id]
    assert len(fake_ollama.calls) == calls_before  # no chat request went to the model


def test_passage_node_weight_zero_still_ranks_by_ppr(retriever: Retriever) -> None:
    trace = retriever.retrieve(DIRECT, settings(passage_node_weight=0.0))
    assert not trace.used_dpr_fallback
    assert all(s.weight == 0.0 for s in trace.seed_passages)
    assert titles(trace)[0] == "The company"
    assert "ppr" in trace.timing_ms


def test_damping_extremes_both_work(retriever: Retriever) -> None:
    close = retriever.retrieve(DIRECT, settings(damping=0.0))
    far = retriever.retrieve(DIRECT, settings(damping=0.99))
    for trace in (close, far):
        assert not trace.used_dpr_fallback
        assert len(trace.passages) == 8
        assert sum(n.score for n in trace.top_nodes) <= 1.0 + 1e-6
    assert titles(close)[0] == "The company"
    # With no damping the activation never leaves the seeds; with a lot it spreads wide.
    assert far.passages[-1].score > close.passages[-1].score


def test_an_edited_graph_is_used_when_given(retriever: Retriever) -> None:
    index = retriever.index
    before = retriever.retrieve(DIRECT, settings())
    company = index.passage_by_id(before.passages[0].passage_id)
    # Cut every mention edge of the winning passage: it should drop from first place.
    edits = [
        EdgeEdit(company.id, index.node_ids[v], 0.0) for v, _ in index.neighbors(index.idx_of[company.id])
    ]
    after = retriever.retrieve(DIRECT, settings(passage_node_weight=0.0), graph=index.graph_with_edits(edits))
    assert titles(after)[0] != "The company"


def test_an_empty_memory_gives_a_fallback_trace(store, ollama) -> None:
    trace = Retriever(GraphIndex.load(store), ollama).retrieve(DIRECT, settings())
    assert trace.used_dpr_fallback
    assert trace.fallback_reason == "the memory is empty"
    assert trace.passages == [] and trace.fact_candidates == []


def test_a_precomputed_question_embedding_is_used(retriever: Retriever, ollama) -> None:
    vector = ollama.embed_one(DIRECT, kind="query")
    trace = retriever.retrieve(DIRECT, settings(), question_embedding=vector)
    assert titles(trace)[0] == "The company"


# ------------------------------------------------------- force in / out


def test_force_include_adds_a_fact_the_filter_never_saw(retriever: Retriever) -> None:
    base = retriever.retrieve(DIRECT, settings())
    unsent = next(c for c in base.fact_candidates if not c.sent_to_filter)

    trace = retriever.retrieve(DIRECT, settings(), force_include={unsent.fact_id})

    forced = next(c for c in trace.fact_candidates if c.fact_id == unsent.fact_id)
    assert forced.kept and forced.reason == "forced in"
    assert unsent.fact_id in trace.kept_fact_ids()
    seeds = {s.entity_id for s in trace.seed_entities}
    fact = retriever.index.facts[retriever.index.fact_index_of[unsent.fact_id]]
    assert fact.subject_id in seeds or fact.object_id in seeds


def test_force_exclude_drops_a_kept_fact(retriever: Retriever) -> None:
    base = retriever.retrieve(DIRECT, settings())
    kept = base.kept_fact_ids()

    trace = retriever.retrieve(DIRECT, settings(), force_exclude={kept[0]})

    excluded = next(c for c in trace.fact_candidates if c.fact_id == kept[0])
    assert not excluded.kept and excluded.reason == "forced out"
    assert kept[0] not in trace.kept_fact_ids()
    assert set(trace.kept_fact_ids()) == set(kept[1:])


def test_excluding_every_kept_fact_falls_back_to_dpr(retriever: Retriever) -> None:
    base = retriever.retrieve(DIRECT, settings())
    trace = retriever.retrieve(DIRECT, settings(), force_exclude=set(base.kept_fact_ids()))
    assert trace.used_dpr_fallback
    assert trace.fallback_reason == "no facts survived the filter"


def test_unknown_fact_ids_in_force_include_are_ignored(retriever: Retriever) -> None:
    base = retriever.retrieve(DIRECT, settings())
    trace = retriever.retrieve(DIRECT, settings(), force_include={"fact-nope"})
    assert trace.kept_fact_ids() == base.kept_fact_ids()


# --------------------------------------------------------------- boosts


def test_node_boosts_scale_seed_weights(retriever: Retriever) -> None:
    base = retriever.retrieve(DIRECT, settings())
    weakest = base.seed_entities[-1]

    trace = retriever.retrieve(DIRECT, settings(), node_boosts={weakest.entity_id: 100.0})

    assert trace.seed_entities[0].entity_id == weakest.entity_id
    assert trace.seed_entities[0].boost == 100.0
    assert trace.seed_entities[0].weight == pytest.approx(weakest.weight * 100.0)


def test_zeroing_every_seed_falls_back_to_dpr(retriever: Retriever) -> None:
    base = retriever.retrieve(DIRECT, settings())
    boosts = {s.entity_id: 0.0 for s in base.seed_entities}
    trace = retriever.retrieve(DIRECT, settings(passage_node_weight=0.0), node_boosts=boosts)
    assert trace.used_dpr_fallback
    assert trace.fallback_reason == "every seed weight is zero"
    assert trace.passages


def test_zero_seed_fallback_trace_still_reports_total_timing(retriever: Retriever) -> None:
    base = retriever.retrieve(DIRECT, settings())
    boosts = {s.entity_id: 0.0 for s in base.seed_entities}
    trace = retriever.retrieve(DIRECT, settings(passage_node_weight=0.0), node_boosts=boosts)
    assert "total" in trace.timing_ms


# --------------------------------------------------------- match_triples


CANDIDATES = [
    ["acme robotics", "is headquartered in", "boulder"],
    ["boulder", "is located in", "colorado"],
    ["priya natarajan", "lives in", "denver"],
]


def test_match_triples_maps_exact_matches_in_the_llm_order() -> None:
    assert match_triples([CANDIDATES[2], CANDIDATES[0]], CANDIDATES) == [2, 0]


def test_match_triples_falls_back_to_the_closest_candidate() -> None:
    typo = ["acme robotic", "headquartered in", "boulder"]
    assert match_triples([typo], CANDIDATES) == [0]
    assert match_triples([["priya", "lives in", "denver"]], CANDIDATES) == [2]


def test_match_triples_never_repeats_a_position() -> None:
    assert match_triples(
        [CANDIDATES[1], ["boulder", "located in", "colorado"], CANDIDATES[1]], CANDIDATES
    ) == [1]


def test_match_triples_with_nothing_to_match() -> None:
    assert match_triples([], CANDIDATES) == []
    assert match_triples([["x", "y", "z"]], []) == []


def test_match_triples_accepts_tuples_from_the_llm() -> None:
    assert match_triples([("boulder", "is located in", "colorado")], CANDIDATES) == [1]


def test_seed_weights_are_plain_floats(retriever: Retriever) -> None:
    trace = retriever.retrieve(DIRECT, settings())
    for seed in trace.seed_entities:
        assert type(seed.weight) is float and not isinstance(seed.vertex, np.integer)


# ------------------------------------------------- candidates vs trace size


def test_a_large_linking_top_k_sends_that_many_facts_to_the_filter(retriever: Retriever) -> None:
    # The reference's rerank_facts shows exactly linking_top_k facts to the LLM; the trace's own
    # cap (TRACE_CANDIDATES) must not shrink that list.
    seen: list[list[list[str]]] = []

    def pass_through(question: str, candidates: list[list[str]]) -> tuple[list[list[str]], str]:
        seen.append(candidates)
        return candidates, "kept all"

    trace = retriever.retrieve(DIRECT, settings(linking_top_k=30), fact_filter=pass_through)

    expected = min(30, len(retriever.index.facts))
    assert expected > TRACE_CANDIDATES, "the sample must have more facts than the trace cap for this test"
    assert len(seen[0]) == expected
    assert sum(c.sent_to_filter for c in trace.fact_candidates) == expected
    # Every fact that went to the filter appears in the trace, so the Analyze page can show it.
    assert len(trace.fact_candidates) == max(TRACE_CANDIDATES, expected)
    assert all(c.sent_to_filter for c in trace.fact_candidates[:expected])
    assert [c.rank for c in trace.fact_candidates] == list(range(1, len(trace.fact_candidates) + 1))


def test_a_small_linking_top_k_still_records_the_trace_cap(retriever: Retriever) -> None:
    trace = retriever.retrieve(DIRECT, settings(linking_top_k=3))
    assert sum(c.sent_to_filter for c in trace.fact_candidates) == 3
    assert len(trace.fact_candidates) == TRACE_CANDIDATES


# ==================================================================== the code graph
# WP3, over `tests/fixtures/code_sample/` indexed through the real pipeline. The first test here is
# the one that matters most: a prose question over a memory that *also* contains code must behave as
# it does on a prose-only memory. Every other "prose stays green" assertion in this file runs on a
# prose-only fixture, which is exactly why the two fidelity defects V2.5 found were invisible.

PLACE = "What does pyapp.orders.OrderService.place do?"
TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "pyapp/cli.py", line 5, in main\n'
    "    service.place(order)\n"
    '  File "pyapp/orders.py", line 18, in place\n'
    "    amount = billing.total(order)\n"
    "OrderError: nope"
)
# The four settings docs/FIDELITY.md's inertness paragraph names.
CODE_OFF = {
    "code_seed_weight": 0.0,
    "code_dense_seeds": 0,
    "code_select": False,
    "code_structural_scale": 0.0,
}


@pytest.fixture
def code_retriever(code_index) -> Retriever:
    ctx, _source_id = code_index
    return Retriever(ctx.graph(), ctx.ollama)


@pytest.fixture
def code_source(code_index) -> str:
    return code_index[1]


@pytest.fixture
def mixed(ctx):
    """The prose sample searched alone, then the code tree added to the *same* memory."""
    index_prose_sample(ctx)
    prose_only = Retriever(ctx.graph(), ctx.ollama).retrieve(DIRECT, settings())
    index_code_sample(ctx)
    return prose_only, Retriever(ctx.graph(), ctx.ollama)


def place_id(index: GraphIndex, source_id: str) -> str:
    return symbol_id(source_id, "pyapp/orders.py", "OrderService.place")


# ------------------------------------------------------- a mixed memory (V2.5)


def test_a_prose_question_over_a_mixed_memory_asks_nothing_extra(mixed, fake_ollama) -> None:
    prose_only, retriever = mixed
    before = len(fake_ollama.calls)
    trace = retriever.retrieve(DIRECT, settings())

    assert trace.used_code_seeds is False
    assert len(fake_ollama.calls) - before == 1, "only the fact filter; no select pass fired"
    assert set(trace.timing_ms) == {"embed", "filter", "ppr", "total"}, "no 'paths' key on prose"
    assert trace.paths == [] and trace.tests == [] and trace.history == []
    assert trace.select == {} and trace.expansions == []
    assert trace.question_prose == DIRECT and trace.question_code == ""
    assert not any(p.via_expand or p.community_boosted for p in trace.passages)
    assert trace.passages[0].title == prose_only.passages[0].title
    # Dense seeds still add reset mass - they are the one thing code contributes to a prose
    # question - but the prose passages keep their order among themselves exactly.
    prose_titles = {p.title for p in prose_only.passages}
    assert [p.title for p in trace.passages if p.title in prose_titles] == [
        p.title for p in prose_only.passages
    ]


def test_one_dense_seed_leaves_the_prose_winner_on_top(mixed) -> None:
    # With code_dense_seeds = 1 a code passage seeds only when it out-ranks every prose passage on
    # dense similarity, which is the strictest reading of Ruling 1b. The default of 5 admits more.
    prose_only, retriever = mixed
    trace = retriever.retrieve(DIRECT, settings(code_dense_seeds=1))
    assert trace.passages[0].title == prose_only.passages[0].title
    prose_titles = {p.title for p in prose_only.passages}
    assert [p.title for p in trace.passages if p.title in prose_titles] == [
        p.title for p in prose_only.passages
    ]


def test_with_the_four_code_settings_off_the_code_graph_contributes_nothing(mixed_index) -> None:
    """
    docs/FIDELITY.md's inertness claim, in its checkable form.

    Not "the same as a prose-only corpus" - a code passage that happens to answer the question is
    an ordinary DPR hit and should rank, and PLAN.md's fixture puts one there on purpose. What must
    be true is that the *graph* contributes nothing: the same passages, searched with and without a
    code graph over them, rank identically. Deleting the code nodes is how the graph goes away
    without the passages going with it.
    """
    ctx, _prose_source_id, code_source_id = mixed_index
    index = GraphIndex.load(ctx.store)
    # A cross-kind SYNONYM is one of the five terms scale 0 has to drop, and neither this fixture
    # nor FakeOllama's OpenIE produces an Entity-Symbol one, so write it by hand.
    symbol = place_id(index, code_source_id)
    ctx.store.add_synonyms([(entity_id("acme robotics"), symbol, 0.87)])
    index = GraphIndex.load(ctx.store)
    assert any(
        {row["a"].split("-")[0], row["b"].split("-")[0]} == {"entity", "symbol"}
        for row in ctx.store.load_synonyms()
    )
    before = Retriever(index, ctx.ollama).retrieve(DIRECT, settings(**CODE_OFF))
    assert index.code_nodes, "the graph really is there"
    # And the mechanism behind it: at scale 0 no code vertex is in the graph PPR runs on at all.
    assert {index.graph_for_scale(0.0).degree(int(v)) for v in index.code_vertices} == {0}

    ctx.store.delete_code_nodes_for_source(code_source_id)
    after_index = GraphIndex.load(ctx.store)
    after = Retriever(after_index, ctx.ollama).retrieve(DIRECT, settings(**CODE_OFF))

    assert after_index.code_nodes == []
    # Same passages, same order, same scores. `approx` on the scores alone: at scale 0 the code
    # vertices are isolated rather than absent, and summing a personalised PageRank over 66 more
    # isolated vertices moves the last few ulps (5e-14 on the winner here). The ranking claim --
    # what the graph contributes -- is unchanged; only float equality is.
    assert [p.passage_id for p in after.passages] == [p.passage_id for p in before.passages]
    assert [p.score for p in after.passages] == pytest.approx([p.score for p in before.passages], rel=1e-9)
    assert before.seed_symbols == [] and before.used_code_seeds is False


# ---------------------------------------------------------------- code seeding


def test_naming_a_symbol_lifts_its_passage_into_what_the_model_reads(
    code_retriever: Retriever, code_source: str
) -> None:
    """
    PLAN.md asks for "in the top 3". What is pinned here is the durable part of that, split by the
    mechanism that carries it.

    **The lexical anchor on its own** (`code_dense_seeds=0`) lifts the passage from rank 25 --
    where dense similarity had it -- into the `qa_top_k` slice the answerer actually reads, at
    rank 5. That is the sentence the docs make, and it is a property of the anchor.

    **At the defaults the exact position is not.** `split_question` leaves "What does do?" as the
    prose half, so `FakeOllama`'s feature-hashed vectors order 63 passages on noise, and every tree
    the fixture adds puts more twins of this passage among the five dense seeds -- three of them
    are `rsapp`'s. What holds at the defaults is the lift itself and the activation: the passage
    ranks better than it does with the anchor off, and the symbol is the most activated node in
    the graph by a factor of three. A real embedder is what would make the literal top 3 hold.
    """
    index = code_retriever.index
    passage_id = index.node_ids[index.defining_passages(index.idx_of[place_id(index, code_source)])[0]]

    without = code_retriever.retrieve(PLACE, settings(code_seed_weight=0.0, code_dense_seeds=0))
    anchor_only = code_retriever.retrieve(PLACE, settings(code_dense_seeds=0))
    trace = code_retriever.retrieve(PLACE, settings())

    assert trace.used_code_seeds is True
    off = {p.passage_id: p.rank for p in without.passages}[passage_id]
    assert {p.passage_id: p.rank for p in anchor_only.passages}[passage_id] <= settings()["qa_top_k"]
    assert off > settings()["qa_top_k"], "the anchor is what puts it there, not dense similarity"
    assert {p.passage_id: p.rank for p in trace.passages}[passage_id] < off
    assert trace.top_nodes[0].name == "OrderService.place"
    assert trace.top_nodes[0].score > 2 * trace.top_nodes[1].score


def test_a_stack_trace_seeds_ppr_even_when_no_fact_survives(code_retriever: Retriever) -> None:
    # The case B's placement could never reach: the DPR fallback returns before its anchor code.
    trace = code_retriever.retrieve(TRACEBACK, settings(), fact_filter=lambda q, c: ([], ""))
    assert trace.used_dpr_fallback is False
    assert trace.kept_fact_ids() == []
    assert "OrderService.place" in {s.name for s in trace.seed_symbols if s.kept}
    assert "ppr" in trace.timing_ms and "paths" in trace.timing_ms


def test_code_seed_weight_zero_restores_the_old_fallback(code_retriever: Retriever) -> None:
    trace = code_retriever.retrieve(
        TRACEBACK, settings(code_seed_weight=0.0), fact_filter=lambda q, c: ([], "")
    )
    assert trace.used_dpr_fallback is True
    assert trace.fallback_reason == "no facts survived the filter"
    assert trace.seed_symbols == [] and trace.used_code_seeds is False


def test_dense_seeds_alone_never_open_the_gate(code_retriever: Retriever) -> None:
    # Ruling 1a: a dense seed adds reset mass and nothing else. It must not disable the fallback,
    # trigger the select pass, write timing["paths"] or add the answer block.
    trace = code_retriever.retrieve(DIRECT, settings(), fact_filter=lambda q, c: ([], ""))
    assert {s.how for s in trace.seed_symbols} <= {"dense"}
    assert trace.used_code_seeds is False
    assert trace.used_dpr_fallback is True
    assert "paths" not in trace.timing_ms


def test_a_seed_records_its_fan_out_specificity_and_boost(code_retriever: Retriever) -> None:
    trace = code_retriever.retrieve(PLACE, settings())
    seed = next(s for s in trace.seed_symbols if s.name == "OrderService.place")
    assert seed.how == "identifier" and seed.kind == "symbol" and seed.kept is True
    assert seed.n_matches == 1 and seed.token == "pyapp.orders.OrderService.place"
    # `place` is invoked by cli.main and by test_place, so in_degree 2 -> specificity 3.
    assert seed.specificity == pytest.approx(3.0)
    assert seed.weight == pytest.approx(1.0 / seed.specificity)
    without = code_retriever.retrieve(PLACE, settings(node_specificity=False))
    assert next(s for s in without.seed_symbols if s.name == "OrderService.place").weight == 1.0


def test_a_node_boost_of_zero_mutes_a_symbol_seed(code_retriever: Retriever, code_source: str) -> None:
    node_id = place_id(code_retriever.index, code_source)
    trace = code_retriever.retrieve(PLACE, settings(), node_boosts={node_id: 0.0})
    seed = next(s for s in trace.seed_symbols if s.node_id == node_id)
    assert seed.boost == 0.0 and seed.weight == 0.0 and seed.kept is False
    assert trace.used_code_seeds is False


def test_symbol_seeds_have_their_own_budget(code_retriever: Retriever) -> None:
    trace = code_retriever.retrieve(PLACE, settings(linking_top_k=1))
    kept = [s for s in trace.seed_symbols if s.kept]
    assert kept, "the linking_top_k cut is about fact entities, never about symbol seeds"
    assert len(kept) <= MAX_CODE_SEEDS


def test_two_searches_give_identical_seeds(code_retriever: Retriever) -> None:
    first = code_retriever.retrieve(TRACEBACK, settings())
    second = code_retriever.retrieve(TRACEBACK, settings())
    assert first.seed_symbols == second.seed_symbols
    assert [p.passage_id for p in first.passages] == [p.passage_id for p in second.passages]


def test_top_nodes_may_be_code_nodes_on_a_code_question(code_retriever: Retriever) -> None:
    trace = code_retriever.retrieve(PLACE, settings())
    assert {n.kind for n in trace.top_nodes} <= {"entity", "passage", "symbol", "data", "commit"}
    assert {n.kind for n in trace.top_nodes} & set(CODE_KINDS)


def test_the_structural_scale_is_a_live_lever(code_retriever: Retriever, code_source: str) -> None:
    index = code_retriever.index
    place = index.idx_of[place_id(index, code_source)]
    assert index.graph_for_scale(1.0).degree(place) > 0
    assert index.graph_for_scale(0.0).degree(place) == 0
    # And a search picks the scaled graph up without being handed one.
    hot = code_retriever.retrieve(PLACE, settings())
    cold = code_retriever.retrieve(PLACE, settings(code_structural_scale=0.0))
    assert [p.passage_id for p in hot.passages] != [p.passage_id for p in cold.passages]


# --------------------------------------------------------- the question split


def test_only_the_prose_half_of_a_question_is_embedded(code_retriever: Retriever, monkeypatch) -> None:
    # S2.12: a forty-line traceback must not swallow the sentence that says what is being asked.
    long_traceback = "Traceback (most recent call last):\n" + "".join(
        f'  File "pyapp/orders.py", line {16 + (i % 8)}, in place\n    amount = billing.total(order)\n'
        for i in range(20)
    )
    question = "Why is the total wrong?\n" + long_traceback

    seen: list[str] = []
    real = code_retriever.ollama.embed_one
    monkeypatch.setattr(
        code_retriever.ollama, "embed_one", lambda text, **kw: (seen.append(text), real(text, **kw))[1]
    )
    trace = code_retriever.retrieve(question, settings())

    assert seen == ["Why is the total wrong?"]
    assert trace.question_prose == "Why is the total wrong?"
    assert trace.question_code.startswith("Traceback")
    assert trace.question == question  # the whole thing is still what the answerer reads


def test_the_fact_filter_sees_the_prose_half_only(code_retriever: Retriever) -> None:
    asked: list[str] = []
    code_retriever.retrieve(
        "Why is the total wrong?\n" + TRACEBACK,
        settings(),
        fact_filter=lambda q, c: (asked.append(q), ([], ""))[1],
    )
    assert asked == ["Why is the total wrong?"]


def test_a_prose_question_takes_the_unchanged_path(code_retriever: Retriever, monkeypatch) -> None:
    seen: list[str] = []
    real = code_retriever.ollama.embed_one
    monkeypatch.setattr(
        code_retriever.ollama, "embed_one", lambda text, **kw: (seen.append(text), real(text, **kw))[1]
    )
    code_retriever.retrieve(DIRECT, settings())
    assert seen == [DIRECT]


# ------------------------------------------------------------- the select pass


def keep_all(question, ranked):
    return SelectResult(keep=[p.passage_id for p in ranked], raw="kept all")


def expand_place(question, ranked):
    """Expand whichever passage defines `place`, wherever the ranking put it."""
    wanted = [p.passage_id for p in ranked if "OrderService.place " in p.title]
    return SelectResult(keep=[p.passage_id for p in ranked], expand=wanted)


def expand_all(question, ranked):
    ids = [p.passage_id for p in ranked]
    return SelectResult(keep=ids, expand=ids)


def test_the_select_pass_is_not_called_unless_it_is_switched_on(code_retriever: Retriever) -> None:
    calls: list[str] = []

    def watcher(question, ranked):
        calls.append(question)
        return keep_all(question, ranked)

    off = code_retriever.retrieve(PLACE, settings(code_select=False), select_fn=watcher)
    assert calls == [] and off.select == {}

    prose = code_retriever.retrieve(DIRECT, settings(), select_fn=watcher)
    assert calls == [], "no lexical anchor, so no second pass"
    assert prose.select == {}

    on = code_retriever.retrieve(PLACE, settings(), select_fn=watcher)
    assert len(calls) == 1
    assert on.select["keep"] and on.select["raw"] == "kept all"


def qa_slice(trace: Trace, qa_top_k: int = 5) -> list[str]:
    """What `ask.answer_from_trace` reads and cites - the slice a `drop` has to be able to move."""
    return [p.passage_id for p in trace.passages if not p.via_expand][:qa_top_k]


def test_a_dropped_passage_is_demoted_and_never_removed(code_retriever: Retriever) -> None:
    base = code_retriever.retrieve(PLACE, settings())
    first = base.passages[0].passage_id
    assert len(base.passages) > 5, "the qa slice has to have somewhere to promote from"

    trace = code_retriever.retrieve(
        PLACE, settings(), select_fn=lambda q, ranked: SelectResult(drop=[first], raw="dropped one")
    )
    assert trace.select["drop"] == [first]
    assert first in {p.passage_id for p in trace.passages}
    assert len(trace.passages) == len(base.passages)
    demoted = next(p for p in trace.passages if p.passage_id == first)
    assert demoted.rank > 1
    assert [p.rank for p in trace.passages] == list(range(1, len(trace.passages) + 1))


def test_a_dropped_passage_changes_what_the_model_reads(code_retriever: Retriever) -> None:
    # AR1 fix 1. The judged window is wider than `qa_top_k`, and a demoted passage falls below
    # everything the model never saw - so a "drop" replaces a passage in the slice `ask.py`
    # answers from instead of only reordering it.
    base = code_retriever.retrieve(PLACE, settings())
    first = base.passages[0].passage_id

    trace = code_retriever.retrieve(
        PLACE, settings(), select_fn=lambda q, ranked: SelectResult(drop=[first], raw="dropped one")
    )
    assert set(qa_slice(trace)) != set(qa_slice(base))
    assert first not in qa_slice(trace)
    assert len(qa_slice(trace)) == len(qa_slice(base)) == 5


def test_the_select_window_is_wider_than_the_slice_the_answerer_reads(code_retriever: Retriever) -> None:
    seen: list[int] = []

    def watcher(question, ranked):
        seen.append(len(ranked))
        return keep_all(question, ranked)

    base = code_retriever.retrieve(PLACE, settings())
    code_retriever.retrieve(PLACE, settings(), select_fn=watcher)
    assert seen == [min(len(base.passages), 10)]  # max(qa_top_k * 2, qa_top_k + 5) at qa_top_k = 5

    seen.clear()
    code_retriever.retrieve(PLACE, settings(qa_top_k=1), select_fn=watcher)
    assert seen == [min(len(base.passages), 6)]  # qa_top_k + 5 wins for a small slice


def test_a_trace_stored_before_the_wider_select_window_still_loads() -> None:
    # The window moved; the *stored* shape did not. A trace written by the narrow-window build
    # (and every simulation replaying it) has to keep loading unchanged.
    stored = {
        "question": "What does place do?",
        "settings": {"qa_top_k": 5},
        "graph_version": 3,
        "used_code_seeds": True,
        "select": {
            "keep": ["passage-a"],
            "drop": ["passage-b"],
            "expand": [],
            "raw": "{'keep': ['passage-a']}",
            "error": "",
        },
    }
    trace = trace_from_dict(json.loads(json.dumps(stored)))
    assert trace.select == stored["select"]
    assert trace.used_code_seeds and trace.passages == []


def test_unknown_passage_ids_in_the_reply_are_ignored(code_retriever: Retriever) -> None:
    trace = code_retriever.retrieve(
        PLACE,
        settings(),
        select_fn=lambda q, ranked: SelectResult(keep=["passage-nope"], drop=["passage-also-nope"]),
    )
    assert trace.select == {"keep": [], "drop": [], "expand": [], "raw": "", "error": ""}
    assert not any(p.passage_id.endswith("nope") for p in trace.passages)


def test_a_failing_select_pass_keeps_every_passage(code_retriever: Retriever) -> None:
    base = code_retriever.retrieve(PLACE, settings())

    def explode(question, ranked):
        raise RuntimeError("the model fell over")

    trace = code_retriever.retrieve(PLACE, settings(), select_fn=explode)
    assert trace.select["error"] == "the model fell over"
    assert [p.passage_id for p in trace.passages] == [p.passage_id for p in base.passages]


def test_expand_appends_neighbours_after_the_kept_list_at_score_zero(code_retriever: Retriever) -> None:
    # `retrieval_top_k` cuts the ranked list, which is the situation "expand" exists for: a
    # neighbour the ranking left out. A neighbour already in the list keeps its own rank and is
    # not duplicated - the expansion is still recorded, and the block is what shows it.
    wide = settings(retrieval_top_k=8, qa_top_k=30)
    base = code_retriever.retrieve(PLACE, wide)

    trace = code_retriever.retrieve(PLACE, wide, select_fn=expand_place)
    added = [p for p in trace.passages if p.via_expand]
    assert added, "place invokes total, so total's passage is a neighbour worth reading"
    assert all(p.score == 0.0 and p.rank > len(base.passages) for p in added)
    assert [p.passage_id for p in trace.passages[-len(added) :]] == [p.passage_id for p in added]
    assert {row["kind"] for row in trace.expansions} <= {"INVOKES", "OVERRIDES", "RAISES"}
    assert len({p.passage_id for p in trace.passages}) == len(trace.passages)
    assert [p.rank for p in trace.passages] == list(range(1, len(trace.passages) + 1))


def test_expanded_passages_are_never_part_of_what_the_model_reads(code_index) -> None:
    # S2.14c: `answer_from_trace`'s slice *is* the citation list, so a neighbour fetched by
    # "expand" must not enter it. It is summarised inside the Code graph block instead.
    ctx, _source_id = code_index
    retriever = Retriever(ctx.graph(), ctx.ollama)
    trace = retriever.retrieve(PLACE, settings(retrieval_top_k=8, qa_top_k=5), select_fn=expand_all)
    assert any(p.via_expand for p in trace.passages)

    answer = answer_from_trace(ctx, trace)
    expanded = {p.passage_id for p in trace.passages if p.via_expand}
    assert set(answer.passage_ids).isdisjoint(expanded)
    assert len(answer.passage_ids) == 5
    assert answer.context_block.startswith(prompts.CODE_GRAPH_HEADER)


def test_expand_max_zero_fetches_nothing(code_retriever: Retriever) -> None:
    trace = code_retriever.retrieve(
        PLACE, settings(retrieval_top_k=8, qa_top_k=30, code_expand_max=0), select_fn=expand_place
    )
    assert not any(p.via_expand for p in trace.passages)


# ------------------------------------------------------- paths, tests, history


def test_a_code_question_carries_its_triples_and_tests(code_retriever: Retriever) -> None:
    trace = code_retriever.retrieve(PLACE, settings())
    assert "paths" in trace.timing_ms
    rendered = {f"{row['a_name']} {row['kind']} {row['b_name']}" for row in trace.paths}
    assert "pyapp.orders.OrderService.place INVOKES pyapp.billing.total" in rendered
    assert "tests.test_orders.test_place" in {row["name"] for row in trace.tests}
    assert all(row["kind"] not in ("DEFINED_IN", "REFERS_TO", "MODIFIES") for row in trace.paths)


def test_a_code_question_carries_the_commits_that_touched_the_symbol(code_index) -> None:
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    trace = Retriever(ctx.graph(), ctx.ollama).retrieve(PLACE, settings())
    assert [row["sha"] for row in trace.history] == ["b2b2b2b"]
    assert trace.history[0]["subject"] == "Total the order in place"


def test_code_theta_filters_what_the_block_will_show(code_retriever: Retriever) -> None:
    loose = code_retriever.retrieve("What does OrderService.graph do?", settings(code_theta=0.5))
    strict = code_retriever.retrieve("What does OrderService.graph do?", settings(code_theta=0.95))
    assert any(row["omega"] == 0.50 for row in loose.paths)
    assert all(row["omega"] >= 0.95 for row in strict.paths)


def test_the_community_boost_is_a_no_op_at_its_default(code_retriever: Retriever) -> None:
    plain = code_retriever.retrieve(PLACE, settings())
    boosted = code_retriever.retrieve(PLACE, settings(code_community_boost=0.5))
    assert not any(p.community_boosted for p in plain.passages)
    assert any(p.community_boosted for p in boosted.passages)
    assert [p.passage_id for p in plain.passages] != [p.passage_id for p in boosted.passages]


# -------------------------------------------------------- stored traces (S2.16)


def test_a_code_trace_round_trips_through_trace_from_dict(code_retriever: Retriever) -> None:
    trace = code_retriever.retrieve(PLACE, settings(), select_fn=keep_all)
    again = trace_from_dict(json.loads(json.dumps(trace.to_dict())))
    assert again.seed_symbols == trace.seed_symbols
    assert again.paths == trace.paths and again.tests == trace.tests
    assert again.history == trace.history and again.select == trace.select
    assert again.used_code_seeds is trace.used_code_seeds
    assert again.question_prose == trace.question_prose
    assert again.passages == trace.passages


def test_a_trace_stored_before_the_code_graph_existed_still_loads() -> None:
    # Copied from the shape evals have been storing since before this work: no code keys at all.
    stored = {
        "question": "Where is Acme Robotics headquartered?",
        "settings": {"linking_top_k": 5, "damping": 0.5},
        "graph_version": 3,
        "used_dpr_fallback": False,
        "fallback_reason": "",
        "fact_candidates": [
            {
                "fact_id": "fact-1",
                "triple": ["acme robotics", "is headquartered in", "boulder"],
                "score": 1.0,
                "rank": 1,
                "sent_to_filter": True,
                "kept": True,
                "reason": "kept by filter",
                "passage_ids": ["passage-1"],
            }
        ],
        "filter": {"raw_response": "{}", "kept_triples": [], "replayed": False},
        "seed_entities": [
            {
                "entity_id": "entity-1",
                "name": "boulder",
                "vertex": 2,
                "weight": 0.5,
                "fact_score_sum": 1.0,
                "occurrences": 2,
                "passage_count": 2,
                "boost": 1.0,
                "from_fact_ids": ["fact-1"],
                "kept": True,
            }
        ],
        "seed_passages": [
            {"passage_id": "passage-1", "title": "The company", "vertex": 9, "dpr_score": 1.0, "weight": 0.05}
        ],
        "top_nodes": [
            {
                "node_id": "passage-1",
                "kind": "passage",
                "name": "The company",
                "vertex": 9,
                "score": 0.2,
                "is_seed": True,
            }
        ],
        "passages": [
            {
                "passage_id": "passage-1",
                "rank": 1,
                "score": 0.2,
                "dpr_rank": 1,
                "dpr_score": 1.0,
                "title": "The company",
                "source_id": "source-1",
                "source_name": "Acme Robotics",
                "preview": "Acme Robotics was founded in 2015",
            }
        ],
        "timing_ms": {"embed": 1.0, "filter": 2.0, "ppr": 3.0, "total": 6.0},
    }
    trace = trace_from_dict(stored)
    assert trace.passages[0].title == "The company"
    assert trace.seed_symbols == [] and trace.paths == [] and trace.select == {}
    assert trace.used_code_seeds is False
    assert trace.passages[0].via_expand is False and trace.passages[0].community_boosted is False
