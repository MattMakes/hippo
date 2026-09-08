"""
Running a question set: ask every question, grade every answer, keep everything.

For each question in the set, in the background:

    search  -> the ranked passages and the full Trace (why they were ranked)
    answer  -> the LLM reads the top passages
    judge   -> correct / partially_correct / incorrect
    metrics -> exact match, F1, recall@k, gold rank, and for a memory with a
               code graph: code_seeded and (commit questions) path_fidelity

and one EvalResult row is stored per question, with the trace, so the Analyze
page can replay it later. One failing question is recorded with its error
and the run carries on. At the end the run gets a summary (accuracy, EM, F1,
recall, latency...) and is never touched again: runs are history you compare.

`compare_with_baseline` is the exception that stores nothing: it answers "what
did the code graph buy?" by running one set twice, the second time with the
four `BASELINE_SETTINGS` that switch code retrieval off.
"""

from __future__ import annotations

import json
import logging
import time
from statistics import mean
from typing import Any

from ..access import Access
from ..ask import answer_from_trace, search
from ..context import AppContext
from ..store.base import now_iso
from . import metrics
from .judge import judge

log = logging.getLogger(__name__)

Result = dict[str, Any]

GOLD_TOP = 5  # "gold in top 5" is the retrieval number the Evals page shows

# The memory with code switched off: no anchor seeds, no dense code seeds, no second LLM pass, and
# no code vertex in igraph at all (`code_structural_scale = 0` drops every code-only edge, so every
# code vertex has degree 0). Running a set under these and comparing is how you tell what the code
# graph bought, rather than what the corpus would have scored anyway - see `compare_with_baseline`.
BASELINE_SETTINGS: dict[str, Any] = {
    "code_seed_weight": 0.0,
    "code_dense_seeds": 0,
    "code_select": False,
    "code_structural_scale": 0.0,
}


# ----------------------------------------------------------------- starting


def start_run(
    ctx: AppContext,
    set_id: str,
    name: str | None = None,
    settings: dict[str, Any] | None = None,
    access: Access | None = None,
) -> str:
    """
    Create the run and start answering in the background. Returns the run id straight away.
    `access` is the runner's (hippo/access.py): every question is searched and answered on their
    slice of the memory, so a run can never read a passage the person who started it cannot.
    """
    question_set = ctx.store.get_question_set(set_id)
    if question_set is None:
        raise ValueError(f"unknown question set {set_id}")
    merged = ctx.store.get_settings()
    merged.update(settings or {})
    run_name = name or f"{question_set['name']} @ {now_iso()}"
    run_id = ctx.store.create_run(set_id, run_name, merged)
    ctx.jobs.start(f"run:{run_id}", lambda: _run_all(ctx, run_id, set_id, merged, access))
    return run_id


def _run_all(
    ctx: AppContext, run_id: str, set_id: str, settings: dict[str, Any], access: Access | None = None
) -> None:
    store = ctx.store
    results: list[Result] = []
    try:
        for done, question in enumerate(store.list_questions(set_id), start=1):
            result = run_question(ctx, question, settings, access)
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


def run_question(
    ctx: AppContext, question_row: dict[str, Any], settings: dict[str, Any], access: Access | None = None
) -> Result:
    """
    Search, answer, judge and score one question. Never raises: trouble lands in `error`.

    Two keys join `recall` when there is a code graph to measure (D17):

    * `code_seeded` - 1.0 when a *lexical* anchor in the question seeded a symbol. It describes the
      trace, not the gold set, so it is written for every question, including one with no gold
      passages at all. `summarize` keeps it out of the gold-only means.
    * `path_fidelity` - commit questions only: the share of the *symbol passages* of the symbols
      that commit modified which came back in the top `GOLD_TOP`. It reads `gold_passage_ids`
      positionally, on the contract `question_maker.commit_questions` writes: the commit's own
      message passage first, the modified symbols' passages after it.
    """
    text = question_row["text"]
    expected = (question_row.get("expected_answer") or "").strip()
    gold_ids = list(question_row.get("gold_passage_ids") or [])
    result = _empty_result()
    started = time.time()
    try:
        trace = search(ctx, text, settings, access)
        result["trace"] = trace.to_dict()
        # Stored as its own property too: the run table lists results without their (big) traces.
        result["used_dpr_fallback"] = trace.used_dpr_fallback
        ranked_ids = trace.passage_ids()
        result["recall"] = metrics.recall_at_k(gold_ids, ranked_ids)
        result["recall"]["code_seeded"] = 1.0 if trace.used_code_seeds else 0.0
        if question_row.get("kind") == "commit" and len(gold_ids) > 1:
            touched = metrics.recall_at_k(gold_ids[1:], ranked_ids, ks=(GOLD_TOP,))
            result["recall"]["path_fidelity"] = touched[f"recall@{GOLD_TOP}"]
        result["gold_rank"] = metrics.gold_rank(gold_ids, ranked_ids)

        answer = answer_from_trace(ctx, trace, access)
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
        "used_dpr_fallback": False,
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
    # "Has gold passages" is a `recall@k` key, not a non-empty `recall` dict: `code_seeded` is
    # written for every question, so a truthiness test here would drag questions with no gold at
    # all into `mean_gold_rank` and `gold_in_top5`.
    with_gold = [r for r in results if any(k.startswith("recall@") for k in _recall(r))]
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
        "dpr_fallbacks": sum(1 for r in results if r.get("used_dpr_fallback")),
        "mean_latency_ms": _mean([r["latency_ms"] for r in results if r.get("latency_ms") is not None]),
    }
    for k in metrics.DEFAULT_KS:
        key = f"recall@{k}"
        summary[key] = _mean([r["recall"][key] for r in with_gold if key in r["recall"]])
    # The two code keys average over whoever has them: every answered question for `code_seeded`,
    # only the commit questions for `path_fidelity` (None on a set with none, as every mean is).
    for key in ("code_seeded", "path_fidelity"):
        summary[key] = _mean([_recall(r)[key] for r in results if key in _recall(r)])
    return summary


def _recall(result: Result) -> dict[str, float]:
    """A result's recall dict. Rows loaded from the store can carry None where {} was written."""
    return result.get("recall") or {}


def _mean(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


# -------------------------------------------------------- with code vs without


def compare_with_baseline(
    ctx: AppContext,
    set_id: str,
    settings: dict[str, Any] | None = None,
    access: Access | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Run one question set twice and return `(with_code, baseline)` summaries.

    The baseline is the same memory, the same questions and the same passages, with the four
    `BASELINE_SETTINGS` applied on top: code seeding off, dense code seeds off, no select pass and
    no code vertex in igraph. So the difference between the two summaries is what indexing the code
    graph bought and nothing else - `code_seeded` falls to 0.0 by construction, and `recall@k`,
    `gold_in_top5` and `path_fidelity` are the numbers worth reading.

    Nothing is stored. This is deliberately not a pair of `start_run` calls: a comparison is a
    measurement someone takes, not history to keep beside the runs a user actually made.
    """
    if ctx.store.get_question_set(set_id) is None:
        raise ValueError(f"unknown question set {set_id}")
    merged = ctx.store.get_settings()
    merged.update(settings or {})
    questions = ctx.store.list_questions(set_id)
    with_code = summarize([run_question(ctx, q, merged, access) for q in questions])
    baseline = summarize([run_question(ctx, q, merged | BASELINE_SETTINGS, access) for q in questions])
    return with_code, baseline
