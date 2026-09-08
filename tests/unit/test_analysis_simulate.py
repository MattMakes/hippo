"""simulate(): what-if searches over the sample corpus, and the pure diff/overrides helpers."""

from __future__ import annotations

import json

import pytest

from hippo.analysis.simulate import (
    INGEST_SETTINGS,
    SIMULATABLE_SETTINGS,
    Overrides,
    diff_traces,
    replay_filter,
    replay_select,
    simulate,
    trace_from_dict,
)
from hippo.ask import search
from hippo.hipporag.indexer import Chunk, index_source
from hippo.hipporag.retriever import RankedPassage, Trace
from hippo.store.base import SETTING_RULES
from tests.fakes.code_fixture import build_code_source

QUESTION = "In which state is the company founded by Priya Natarajan headquartered?"


def index_sample(ctx, sample_text: str) -> str:
    """Index samples/acme_robotics.md as one passage per '## ' section. Returns the source id."""
    source_id = ctx.store.create_source("sample", "Acme Robotics")
    chunks = []
    for ordinal, section in enumerate(sample_text.split("## ")[1:]):
        title, _, body = section.partition("\n")
        chunks.append(Chunk(ordinal, title.strip(), body.strip()))
    index_source(ctx.store, ctx.ollama, source_id, chunks, workers=2)
    ctx.store.update_source(source_id, status="ready")
    return source_id


@pytest.fixture
def baseline(ctx, sample_text) -> Trace:
    index_sample(ctx, sample_text)
    return search(ctx, QUESTION)


def ranks(trace: Trace) -> dict[str, int]:
    return {p.title: p.rank for p in trace.passages}


def scores(trace: Trace) -> dict[str, float]:
    return {p.title: p.score for p in trace.passages}


def chat_calls(fake_ollama) -> int:
    """How many chat requests the fake model has answered so far (embeddings do not count)."""
    return len(fake_ollama.calls)


# ------------------------------------------------------------- settings


def test_damping_change_moves_scores_and_the_diff_lists_ranks(ctx, fake_ollama, baseline):
    calls_before = chat_calls(fake_ollama)
    sim = simulate(ctx, QUESTION, Overrides(settings={"damping": 0.9}), baseline)
    assert chat_calls(fake_ollama) == calls_before, "a replayed simulation must not call the LLM"

    assert sim.answer is None
    assert sim.baseline is baseline
    assert sim.trace.settings["damping"] == 0.9
    assert sim.trace.settings["linking_top_k"] == baseline.settings["linking_top_k"]
    assert sim.trace.filter["replayed"] is True
    assert sim.trace.kept_fact_ids() == baseline.kept_fact_ids()
    assert scores(sim.trace) != scores(baseline)
    assert ranks(sim.trace) != ranks(baseline)

    diff = sim.diff
    titles = {row["title"] for row in diff["passages"]}
    assert titles == {p.title for p in baseline.passages[:10]} | {p.title for p in sim.trace.passages[:10]}
    for row in diff["passages"]:
        assert row["before_rank"] == ranks(baseline).get(row["title"])
        assert row["after_rank"] == ranks(sim.trace).get(row["title"])
        assert row["change"] in {"up", "down", "same", "new", "dropped"}
    after_ranks = [row["after_rank"] for row in diff["passages"] if row["after_rank"] is not None]
    assert after_ranks == sorted(after_ranks)
    assert any(row["change"] in {"up", "down"} for row in diff["passages"])
    assert diff["fallback_before"] is False and diff["fallback_after"] is False
    assert diff["kept_facts_before"] == diff["kept_facts_after"]
    assert [s["name"] for s in diff["seeds_before"]] == [s.name for s in baseline.seed_entities if s.kept]
    json.dumps(diff)


# ---------------------------------------------------------- force in/out


def test_force_exclude_of_a_kept_fact_removes_its_seed(ctx, baseline):
    lives_in = next(c for c in baseline.fact_candidates if c.kept and c.triple[1] == "lives in")
    assert lives_in.triple == ["priya natarajan", "lives in", "denver"]
    assert "denver" in {s.name for s in baseline.seed_entities if s.kept}

    sim = simulate(ctx, QUESTION, Overrides(force_exclude=[lives_in.fact_id]), baseline)
    excluded = next(c for c in sim.trace.fact_candidates if c.fact_id == lives_in.fact_id)
    assert excluded.kept is False and excluded.reason == "forced out"
    assert "denver" not in {s.name for s in sim.trace.seed_entities}
    assert "denver" in {s["name"] for s in sim.diff["seeds_before"]}
    assert "denver" not in {s["name"] for s in sim.diff["seeds_after"]}
    assert len(sim.diff["kept_facts_after"]) == len(sim.diff["kept_facts_before"]) - 1


def test_force_include_of_a_dropped_fact_adds_its_seed(ctx, baseline):
    hq = next(c for c in baseline.fact_candidates if c.triple[1] == "is headquartered in")
    assert not hq.kept
    sim = simulate(ctx, QUESTION, Overrides(force_include=[hq.fact_id]), baseline)
    included = next(c for c in sim.trace.fact_candidates if c.fact_id == hq.fact_id)
    assert included.kept and included.reason == "forced in"
    assert "boulder" in {s.name for s in sim.trace.seed_entities}


# -------------------------------------------------------------- edge edits


def test_edge_edit_with_weight_zero_drops_the_passage(ctx, baseline):
    seed = max(baseline.seed_entities, key=lambda s: s.weight)  # 'denver'
    index = ctx.graph()
    # The passage this seed is mentioned in that is not already rank 1.
    linked = [
        p
        for p in baseline.passages
        if index.edge_between(seed.vertex, index.idx_of[p.passage_id]) is not None and p.rank > 1
    ]
    victim = linked[0]

    sim = simulate(
        ctx,
        QUESTION,
        Overrides(edge_edits=[{"a": seed.entity_id, "b": victim.passage_id, "weight": 0}]),
        baseline,
    )
    assert ranks(sim.trace)[victim.title] > victim.rank
    row = next(r for r in sim.diff["passages"] if r["passage_id"] == victim.passage_id)
    assert row["before_rank"] == victim.rank
    assert row["change"] in {"down", "dropped"}
    # The real graph is untouched: a plain simulation ranks it where it was.
    again = simulate(ctx, QUESTION, Overrides(), baseline)
    assert ranks(again.trace)[victim.title] == victim.rank


# ------------------------------------------------------------- node boosts


def test_node_boost_changes_the_seed_weight(ctx, baseline):
    seed = min((s for s in baseline.seed_entities if s.kept), key=lambda s: s.weight)
    sim = simulate(ctx, QUESTION, Overrides(node_boosts={seed.entity_id: 3.0}), baseline)
    boosted = next(s for s in sim.trace.seed_entities if s.entity_id == seed.entity_id)
    assert boosted.boost == 3.0
    assert boosted.weight == pytest.approx(seed.weight * 3.0)
    assert sim.trace.seed_entities[0].entity_id == seed.entity_id  # now the strongest seed


# ------------------------------------------------ baseline / filter / answer


def test_without_a_baseline_the_llm_filter_runs_once_and_is_replayed(ctx, fake_ollama, baseline):
    calls_before = chat_calls(fake_ollama)
    sim = simulate(ctx, QUESTION, Overrides(settings={"damping": 0.9}))
    assert chat_calls(fake_ollama) == calls_before + 1  # one filter call for the fresh baseline
    assert sim.baseline is not None and sim.baseline.filter["replayed"] is False
    assert sim.trace.filter["replayed"] is True
    assert sim.baseline.kept_fact_ids() == baseline.kept_fact_ids()
    assert sim.trace.settings["damping"] == 0.9 and sim.baseline.settings["damping"] == 0.5


def test_rerun_filter_calls_the_llm_again(ctx, fake_ollama, baseline):
    calls_before = chat_calls(fake_ollama)
    sim = simulate(ctx, QUESTION, Overrides(rerun_filter=True), baseline)
    assert chat_calls(fake_ollama) == calls_before + 1
    assert sim.trace.filter["replayed"] is False
    assert sim.trace.kept_fact_ids() == baseline.kept_fact_ids()  # the fake is deterministic


def test_reanswer_produces_an_answer(ctx, baseline):
    sim = simulate(ctx, QUESTION, Overrides(reanswer=True), baseline)
    assert sim.answer is not None
    assert sim.answer.answer
    assert sim.answer.passage_ids


def test_stored_trace_json_round_trips_into_a_baseline(ctx, baseline):
    restored = trace_from_dict(json.loads(json.dumps(baseline.to_dict())))
    assert restored.to_dict() == baseline.to_dict()
    sim = simulate(ctx, QUESTION, Overrides(), restored)
    assert ranks(sim.trace) == ranks(baseline)


# ------------------------------------------------------------ pure helpers


def test_replay_filter_only_returns_triples_that_are_candidates_again():
    trace = Trace(question="q", settings={}, graph_version=1)
    trace.filter = {"kept_triples": [["a", "r", "b"], ["c", "r", "d"]]}
    kept, raw = replay_filter(trace)("q", [["c", "r", "d"], ["x", "r", "y"]])
    assert kept == [["c", "r", "d"]] and raw == "replayed"


def test_every_setting_is_either_simulatable_or_named_as_ingest_only():
    # An allow-list, so a new setting is not a knob until someone says it is - and the split is
    # checked both ways, or a setting could quietly belong to neither list.
    assert SIMULATABLE_SETTINGS | INGEST_SETTINGS == set(SETTING_RULES)
    assert not SIMULATABLE_SETTINGS & INGEST_SETTINGS


def test_an_ingest_only_setting_is_refused_as_a_simulation_override():
    # It would render as a slider on the page whose whole purpose is explaining a ranking, and
    # moving it could not change one: history depth is read while indexing, never while searching.
    with pytest.raises(ValueError, match="only applies while indexing"):
        Overrides.from_dict({"settings": {"code_history_depth": 10}})
    assert Overrides.from_dict({"settings": {"code_structural_scale": 0.0}}).settings == {
        "code_structural_scale": 0.0
    }


def test_a_structural_scale_override_is_passed_to_the_graph_the_search_runs_on(ctx, baseline, monkeypatch):
    # The scale and an edge edit compose in one rebuild: applying the scale anywhere else would be
    # discarded the moment a simulation also edited an edge, because retrieve(graph=) runs on this
    # igraph and nothing else.
    index = ctx.graph_for(None)
    seen: list[float] = []
    real = index.graph_with_edits
    monkeypatch.setattr(
        index, "graph_with_edits", lambda edits, scale=1.0: (seen.append(scale), real(edits, scale))[1]
    )
    edits = [{"a": index.node_ids[0], "b": index.node_ids[1], "weight": 3.0}]
    overrides = Overrides.from_dict({"settings": {"code_structural_scale": 0.0}, "edge_edits": edits})
    simulate(ctx, QUESTION, overrides, baseline=baseline)
    assert seen == [0.0]


def test_overrides_from_dict_and_to_ops():
    overrides = Overrides.from_dict(
        {
            "settings": {"damping": 0.7},
            "force_include": ["fact-1"],
            "force_exclude": ["fact-2"],
            "node_boosts": {"entity-a": "1.5"},
            "edge_edits": [{"a": "entity-a", "b": "passage-b", "weight": "0"}],
            "rerun_filter": 1,
        }
    )
    assert overrides.node_boosts == {"entity-a": 1.5}
    assert overrides.edge_edits == [{"a": "entity-a", "b": "passage-b", "weight": 0.0}]
    assert overrides.rerun_filter is True and overrides.reanswer is False

    ops = overrides.to_ops()
    assert ops == [
        {"op": "set_setting", "name": "damping", "value": 0.7},
        {"op": "set_node_boost", "entity_id": "entity-a", "boost": 1.5},
        {"op": "set_edge_weight", "a": "entity-a", "b": "passage-b", "weight": 0.0},
    ]
    assert not any("fact" in json.dumps(op) for op in ops)  # force in/out never become ops
    assert Overrides.from_dict(None) == Overrides()


def test_diff_traces_handles_a_missing_baseline():
    after = Trace(question="q", settings={}, graph_version=1)
    diff = diff_traces(None, after)
    assert diff["passages"] == [] and diff["fallback_before"] is None
    assert diff["seeds_before"] == [] and diff["kept_facts_before"] == []


# ==================================================================== the code graph
# The whole reason D10 put the select pass in the retriever rather than in ask.py is that
# `simulate()` re-runs the *entire* retrieval on every slider move. Without a replay, a code
# question would cost one LLM call per move, on the page whose job is explaining a ranking.

CODE_QUESTION = "What does pyapp.orders.OrderService.place do?"


@pytest.fixture
def code_baseline(ctx) -> Trace:
    build_code_source(ctx.store, ctx.ollama)
    return search(ctx, CODE_QUESTION)


def test_the_baseline_of_a_code_question_records_its_select_decisions(code_baseline: Trace) -> None:
    assert code_baseline.used_code_seeds is True
    assert set(code_baseline.select) == {"keep", "drop", "expand", "raw", "error"}
    assert code_baseline.paths and code_baseline.select["error"] == ""


def test_a_slider_move_on_a_code_question_costs_no_llm_call(ctx, fake_ollama, code_baseline) -> None:
    calls_before = chat_calls(fake_ollama)
    sim = simulate(ctx, CODE_QUESTION, Overrides(settings={"code_structural_scale": 0.0}), code_baseline)
    assert chat_calls(fake_ollama) == calls_before, "the filter *and* the select pass are replayed"
    assert sim.trace.filter["replayed"] is True
    assert sim.trace.select["raw"] == "replayed"


def test_replay_select_only_repeats_decisions_about_passages_still_on_the_table() -> None:
    baseline = Trace(question="q", settings={}, graph_version=1)
    baseline.select = {"keep": ["passage-a", "passage-gone"], "drop": ["passage-b"], "expand": []}
    ranked = [
        RankedPassage("passage-a", 1, 1.0, 1, 1.0, "A", "s", "S", ""),
        RankedPassage("passage-b", 2, 0.5, 2, 0.5, "B", "s", "S", ""),
    ]
    result = replay_select(baseline)("q", ranked)
    assert result.keep == ["passage-a"] and result.drop == ["passage-b"]
    assert result.expand == [] and result.raw == "replayed"


def test_the_structural_scale_moves_a_code_ranking_in_a_simulation(ctx, code_baseline) -> None:
    sim = simulate(ctx, CODE_QUESTION, Overrides(settings={"code_structural_scale": 0.0}), code_baseline)
    assert [p.passage_id for p in sim.trace.passages] != [p.passage_id for p in code_baseline.passages]
    assert any(row["change"] != "same" for row in sim.diff["passages"])


def test_the_scale_and_an_edge_edit_compose_in_one_rebuild(ctx, code_baseline) -> None:
    # `simulate()` hands its own igraph to `retrieve(graph=)`, so a scale applied anywhere else
    # would be silently discarded the moment a simulation also edited an edge.
    index = ctx.graph()
    a, b = code_baseline.passages[0].passage_id, code_baseline.passages[1].passage_id
    overrides = Overrides(
        settings={"code_structural_scale": 0.0}, edge_edits=[{"a": a, "b": b, "weight": 5.0}]
    )
    sim = simulate(ctx, CODE_QUESTION, overrides, code_baseline)
    assert sim.trace.settings["code_structural_scale"] == 0.0
    scaled = index.graph_with_edits(overrides.edge_edit_objects(), 0.0)
    assert {scaled.degree(int(v)) for v in index.code_vertices} == {0}
