"""
Running a question set: ask every question, grade every answer, keep everything.

For each question in the set, in the background:

    search  -> the ranked passages and the full Trace (why they were ranked)
    answer  -> the LLM reads the top passages
    judge   -> correct / partially_correct / incorrect
    metrics -> exact match, F1, recall@k, gold rank

and one EvalResult row is stored per question, with the trace, so the Analyze
page can replay it later. One failing question is recorded with its error
and the run carries on. At the end the run gets a summary (accuracy, EM, F1,
recall, latency...) and is never touched again: runs are history you compare.
"""

from __future__ import annotations

import json
import logging
import time
from statistics import mean
from typing import Any

from ..ask import answer_from_trace, search
from ..context import AppContext
from ..store.base import now_iso
from . import metrics
from .judge import judge

log = logging.getLogger(__name__)

Result = dict[str, Any]

GOLD_TOP = 5  # "gold in top 5" is the retrieval number the Evals page shows


# ----------------------------------------------------------------- starting


def start_run(
    ctx: AppContext, set_id: str, name: str | None = None, settings: dict[str, Any] | None = None
) -> str:
    """Create the run and start answering in the background. Returns the run id straight away."""
    question_set = ctx.store.get_question_set(set_id)
    if question_set is None:
        raise ValueError(f"unknown question set {set_id}")
    merged = ctx.store.get_settings()
    merged.update(settings or {})
    run_name = name or f"{question_set['name']} @ {now_iso()}"
    run_id = ctx.store.create_run(set_id, run_name, merged)
    ctx.jobs.start(f"run:{run_id}", lambda: _run_all(ctx, run_id, set_id, merged))
    return run_id


def _run_all(ctx: AppContext, run_id: str, set_id: str, settings: dict[str, Any]) -> None:
    store = ctx.store
    results: list[Result] = []
    try:
        for done, question in enumerate(store.list_questions(set_id), start=1):
            result = run_question(ctx, question, settings)
            store.add_result(run_id, question["id"], result)
            results.append(result)
            store.update_run(run_id, progress_done=done)
        store.update_run(
            run_id, status="done", finished_at=now_iso(), summary_json=json.dumps(summarize(results))
        )
    except Exception as exc:
        # run_question catches per-question trouble; landing here means the store itself failed.
        log.exception("Eval run %s failed", run_id)
        store.update_run(run_id, status="failed", finished_at=now_iso(), error=str(exc))
        raise


# ------------------------------------------------------------- one question


def run_question(ctx: AppContext, question_row: dict[str, Any], settings: dict[str, Any]) -> Result:
    """Search, answer, judge and score one question. Never raises: trouble lands in `error`."""
    text = question_row["text"]
    expected = (question_row.get("expected_answer") or "").strip()
    gold_ids = list(question_row.get("gold_passage_ids") or [])
    result = _empty_result()
    started = time.time()
    try:
        trace = search(ctx, text, settings)
        result["trace"] = trace.to_dict()
        ranked_ids = trace.passage_ids()
        result["recall"] = metrics.recall_at_k(gold_ids, ranked_ids)
        result["gold_rank"] = metrics.gold_rank(gold_ids, ranked_ids)

        answer = answer_from_trace(ctx, trace)
        # Latency is what a user would wait for: search plus answer, not the grading.
        result["latency_ms"] = round((time.time() - started) * 1000, 1)
        result["answer"] = answer.answer
        result["thought"] = answer.thought

        if expected:
            result.update(_grade(ctx, text, expected, answer.answer))
        else:
            result["judge_reason"] = "no expected answer to compare with"
    except Exception as exc:  # noqa: BLE001 - one broken question must not end the run
        log.exception("Question %r failed", text)
        result["error"] = f"{type(exc).__name__}: {exc}"
        if result["latency_ms"] is None:
            result["latency_ms"] = round((time.time() - started) * 1000, 1)
    return result


def _grade(ctx: AppContext, question: str, expected: str, actual: str) -> dict[str, Any]:
    verdict = judge(ctx.ollama, question, expected, actual)
    return {
        "verdict": verdict.verdict,
        "judge_score": verdict.score,
        "judge_reason": verdict.reason,
        "exact_match": metrics.exact_match(expected, actual),
        "f1": metrics.f1(expected, actual),
    }


def _empty_result() -> Result:
    """Every key store.add_result knows about, so a failed question still stores a complete row."""
    return {
        "answer": "",
        "thought": "",
        "verdict": "",
        "judge_score": None,
        "judge_reason": "",
        "exact_match": None,
        "f1": None,
        "recall": {},
        "gold_rank": None,
        "latency_ms": None,
        "trace": {},
        "error": None,
    }


# ------------------------------------------------------------------ summary


def summarize(results: list[Result]) -> dict[str, Any]:
    """
    Roll a run's results up into the numbers the Evals page shows. Pure: takes the
    result dicts (as returned by run_question or store.list_results), touches nothing.
    Means skip questions where a number is missing (no expected answer, no gold passages, an error).
    """
    scores = [r["judge_score"] for r in results if r.get("judge_score") is not None]
    verdicts = [r.get("verdict") for r in results]
    with_gold = [r for r in results if r.get("recall")]
    gold_ranks = [r["gold_rank"] for r in with_gold if r.get("gold_rank") is not None]
    summary: dict[str, Any] = {
        "questions": len(results),
        "errors": sum(1 for r in results if r.get("error")),
        "accuracy": _mean(scores),
        "correct": verdicts.count("correct"),
        "partial": verdicts.count("partially_correct"),
        "incorrect": verdicts.count("incorrect"),
        "exact_match": _mean([r["exact_match"] for r in results if r.get("exact_match") is not None]),
        "f1": _mean([r["f1"] for r in results if r.get("f1") is not None]),
        "mean_gold_rank": _mean(gold_ranks),
        "gold_in_top5": _mean(
            [1.0 if r.get("gold_rank") and r["gold_rank"] <= GOLD_TOP else 0.0 for r in with_gold]
        ),
        "dpr_fallbacks": sum(1 for r in results if (r.get("trace") or {}).get("used_dpr_fallback")),
        "mean_latency_ms": _mean([r["latency_ms"] for r in results if r.get("latency_ms") is not None]),
    }
    for k in metrics.DEFAULT_KS:
        key = f"recall@{k}"
        summary[key] = _mean([r["recall"][key] for r in with_gold if key in r["recall"]])
    return summary


def _mean(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None
