"""Running a question set end to end with the fakes, plus the pure summary."""

from __future__ import annotations

import pytest

from hippo.evals import runner
from hippo.evals.question_maker import generate_questions
from hippo.evals.runner import run_question, start_run, summarize
from hippo.hipporag.indexer import Chunk, index_source


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
def set_id(ctx, sample_text) -> str:
    source_id = index_sample(ctx, sample_text)
    # per_passage=3 so the company passage also yields "Acme Robotics is headquartered in what?"
    return generate_questions(ctx, source_id, per_passage=3, max_single=10, max_multihop=3)


def test_run_answers_every_question_and_summarizes(ctx, set_id):
    run_id = start_run(ctx, set_id, name="first run", settings={"damping": 0.6})
    assert ctx.jobs.is_running(f"run:{run_id}") or ctx.store.get_run(run_id)["status"] in ("running", "done")
    ctx.jobs.wait_all()

    run = ctx.store.get_run(run_id)
    questions = ctx.store.list_questions(set_id)
    assert run["status"] == "done"
    assert run["name"] == "first run"
    assert run["finished_at"]
    assert run["progress_done"] == run["progress_total"] == len(questions)
    assert run["settings"]["damping"] == 0.6
    assert run["settings"]["linking_top_k"] == ctx.store.get_settings()["linking_top_k"]

    results = ctx.store.list_results(run_id)
    assert len(results) == len(questions)
    assert all(r["error"] is None for r in results)
    assert all(r["answer"] for r in results)
    assert all(r["latency_ms"] is not None and r["latency_ms"] >= 0 for r in results)
    assert all(r["verdict"] in ("correct", "partially_correct", "incorrect") for r in results)
    assert all(r["recall"] for r in results)  # every generated question has gold passages

    summary = run["summary"]
    assert 0.0 <= summary["accuracy"] <= 1.0
    assert summary["questions"] == len(questions)
    assert summary["correct"] + summary["partial"] + summary["incorrect"] == len(questions)
    assert "recall@5" in summary and summary["gold_in_top5"] is not None

    # A plain single-hop question like "Acme Robotics is headquartered in what?" must come out correct.
    correct_singles = [r for r in results if r["kind"] == "single" and r["verdict"] == "correct"]
    assert correct_singles
    assert any("Acme Robotics" in r["question"] for r in correct_singles)
    headquartered = [r for r in results if r["kind"] == "single" and "headquartered" in r["question"]]
    assert headquartered and headquartered[0]["question"] == "Acme Robotics is headquartered in what?"
    assert headquartered[0]["verdict"] == "correct"
    assert headquartered[0]["gold_rank"] == 1

    # The stored result carries the full trace for the Analyze page.
    full = ctx.store.get_result(results[0]["id"])
    assert full["trace"]["question"] == results[0]["question"]
    assert full["trace"]["passages"]


def test_run_question_returns_every_field_add_result_wants(ctx, set_id):
    question = ctx.store.list_questions(set_id)[0]
    result = run_question(ctx, question, ctx.store.get_settings())
    expected_keys = {
        "answer",
        "thought",
        "verdict",
        "judge_score",
        "judge_reason",
        "exact_match",
        "f1",
        "recall",
        "gold_rank",
        "latency_ms",
        "trace",
        "used_dpr_fallback",
        "error",
    }
    assert expected_keys <= set(result)
    assert result["error"] is None
    assert result["used_dpr_fallback"] is False  # the graph search found seeds
    assert result["trace"]["settings"]["qa_top_k"] == 5
    assert result["judge_score"] in (0.0, 0.5, 1.0)


def test_question_without_expected_answer_is_not_judged(ctx, set_id):
    row = {
        "id": "x",
        "text": "Acme Robotics is headquartered in what?",
        "expected_answer": "",
        "gold_passage_ids": [],
    }
    result = run_question(ctx, row, ctx.store.get_settings())
    assert result["answer"]
    assert result["verdict"] == ""
    assert result["judge_score"] is None
    assert result["exact_match"] is None
    # `code_seeded` describes the trace, not the gold set, so it is written even here. What must
    # stay absent is every gold-derived key: no `recall@k`, no rank, and no place in `summarize`'s
    # gold means (test_evals_code.py::test_summarize_means_the_new_keys pins that half).
    assert result["recall"] == {"code_seeded": 0.0}
    assert result["gold_rank"] is None


def test_one_broken_question_does_not_kill_the_run(ctx, set_id, monkeypatch):
    real_search = runner.search
    questions = ctx.store.list_questions(set_id)
    poison = questions[0]["text"]

    def flaky_search(ctx_, text, settings, access=None, **kwargs):
        if text == poison:
            raise RuntimeError("boom")
        return real_search(ctx_, text, settings, access, **kwargs)

    monkeypatch.setattr(runner, "search", flaky_search)
    run_id = start_run(ctx, set_id)
    ctx.jobs.wait_all()

    run = ctx.store.get_run(run_id)
    assert run["status"] == "done"
    results = ctx.store.list_results(run_id)
    assert len(results) == len(questions)
    broken = [r for r in results if r["error"]]
    assert len(broken) == 1
    assert "boom" in broken[0]["error"]
    assert broken[0]["question"] == poison
    assert run["summary"]["errors"] == 1
    assert run["summary"]["questions"] == len(questions)


def test_start_run_rejects_unknown_set(ctx):
    with pytest.raises(ValueError):
        start_run(ctx, "nope")


def test_summarize_is_pure_and_skips_missing_numbers():
    results = [
        {
            "verdict": "correct",
            "judge_score": 1.0,
            "exact_match": 1.0,
            "f1": 1.0,
            "recall": {"recall@1": 1.0, "recall@5": 1.0},
            "gold_rank": 1,
            "latency_ms": 100.0,
            "trace": {"used_dpr_fallback": False},
            "used_dpr_fallback": False,
            "error": None,
        },
        {
            "verdict": "incorrect",
            "judge_score": 0.0,
            "exact_match": 0.0,
            "f1": 0.5,
            "recall": {"recall@1": 0.0, "recall@5": 0.0},
            "gold_rank": None,
            "latency_ms": 300.0,
            "trace": None,  # store.list_results rows have no trace; the flag stands on its own
            "used_dpr_fallback": True,
            "error": None,
        },
        {  # no expected answer, no gold passages, and it errored: contributes only to counts
            "verdict": "",
            "judge_score": None,
            "exact_match": None,
            "f1": None,
            "recall": {},
            "gold_rank": None,
            "latency_ms": None,
            "trace": None,
            "error": "boom",
        },
    ]
    before = [dict(r) for r in results]
    summary = summarize(results)
    assert results == before  # nothing was mutated
    assert summary["questions"] == 3
    assert summary["errors"] == 1
    assert summary["accuracy"] == 0.5
    assert (summary["correct"], summary["partial"], summary["incorrect"]) == (1, 0, 1)
    assert summary["exact_match"] == 0.5
    assert summary["f1"] == 0.75
    assert summary["recall@1"] == 0.5
    assert summary["recall@5"] == 0.5
    assert summary["recall@20"] is None
    assert summary["mean_gold_rank"] == 1
    assert summary["gold_in_top5"] == 0.5
    assert summary["dpr_fallbacks"] == 1
    assert summary["mean_latency_ms"] == 200.0


def test_a_question_on_an_empty_memory_is_marked_as_a_fallback(ctx):
    row = {"id": "x", "text": "Where is Acme?", "expected_answer": "", "gold_passage_ids": []}
    result = run_question(ctx, row, ctx.store.get_settings())
    assert result["used_dpr_fallback"] is True
    assert result["trace"]["fallback_reason"] == "the memory is empty"
    assert summarize([result])["dpr_fallbacks"] == 1


def test_summarize_of_nothing():
    summary = summarize([])
    assert summary["questions"] == 0
    assert summary["accuracy"] is None
    assert summary["correct"] == 0
