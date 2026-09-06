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

from hippo.hipporag.graph_index import EdgeEdit, GraphIndex
from hippo.hipporag.indexer import Chunk, index_source
from hippo.hipporag.retriever import (
    TRACE_CANDIDATES,
    Retriever,
    Trace,
    match_triples,
    trace_from_dict,
)
from hippo.store.base import DEFAULT_SETTINGS

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
