"""
Evals: question sets, runs, and the history of results.

Pages render the tables; forms post here and redirect; the /api/evals/*
endpoints return JSON. The work itself (generating questions, running a set)
lives in hippo.evals and runs in background jobs.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ...evals import question_maker, runner
from ...store.base import validate_settings
from ..render import ctx_of, render

router = APIRouter()

SUMMARY_CARDS = [
    ("accuracy", "Accuracy", "mean judge score: correct 1, partial ½, incorrect 0"),
    ("exact_match", "Exact match", "answer equals the expected one after normalising"),
    ("f1", "F1", "word overlap between answer and expected"),
    ("recall@5", "Recall@5", "share of gold passages found in the top 5"),
    ("gold_in_top5", "Gold in top 5", "questions whose gold passage was in the top 5"),
    ("mean_gold_rank", "Mean gold rank", "average rank of the best gold passage (lower is better)"),
    ("dpr_fallbacks", "Fallbacks", "questions answered by embedding search only"),
    ("mean_latency_ms", "Latency (ms)", "average time per question"),
]


# ---------------------------------------------------------------- pages


@router.get("/evals")
def evals_page(request: Request, source: str = "", error: str = ""):
    ctx = ctx_of(request)
    sets = ctx.store.list_question_sets()
    if source:
        sets = [qs for qs in sets if qs.get("source_id") == source]
    return render(
        request,
        "evals.html",
        nav="evals",
        sets=sets,
        runs=ctx.store.list_runs(),
        error=error,
        cards=SUMMARY_CARDS,
    )


@router.get("/partials/evals/tables")
def evals_tables_partial(request: Request):
    ctx = ctx_of(request)
    return render(
        request, "partials/evals_tables.html", sets=ctx.store.list_question_sets(), runs=ctx.store.list_runs()
    )


@router.get("/evals/sets/{set_id}")
def set_page(request: Request, set_id: str, error: str = ""):
    ctx = ctx_of(request)
    question_set = ctx.store.get_question_set(set_id)
    if question_set is None:
        raise HTTPException(404, "no such question set")
    return render(
        request,
        "eval_set.html",
        nav="evals",
        question_set=question_set,
        questions=ctx.store.list_questions(set_id),
        runs=ctx.store.list_runs(set_id),
        error=error,
    )


@router.get("/evals/runs/{run_id}")
def run_page(request: Request, run_id: str, compare: str = ""):
    ctx = ctx_of(request)
    run = ctx.store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    results = ctx.store.list_results(run_id)
    siblings = [r for r in ctx.store.list_runs(run["set_id"]) if r["id"] != run_id]
    other = ctx.store.get_run(compare) if compare else None
    return render(
        request,
        "eval_run.html",
        nav="evals",
        run=run,
        results=results,
        siblings=siblings,
        other=other,
        cards=SUMMARY_CARDS,
    )


@router.get("/partials/runs/{run_id}")
def run_partial(request: Request, run_id: str):
    ctx = ctx_of(request)
    run = ctx.store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    return render(
        request,
        "partials/run_body.html",
        run=run,
        results=ctx.store.list_results(run_id),
        cards=SUMMARY_CARDS,
        other=None,
    )


# ----------------------------------------------------------- page forms


@router.post("/evals/sets")
def create_set_form(request: Request, name: str = Form(""), questions: str = Form("")):
    rows = parse_question_lines(questions)
    if not rows:
        return RedirectResponse(
            "/evals?error=Add+at+least+one+question+line+like+%27question+%7C+answer%27", status_code=303
        )
    ctx = ctx_of(request)
    set_id = ctx.store.create_question_set(name.strip() or "My questions")
    ctx.store.add_questions(set_id, rows)
    return RedirectResponse(f"/evals/sets/{set_id}", status_code=303)


@router.post("/evals/sets/{set_id}/questions")
def add_question_form(
    request: Request,
    set_id: str,
    text: str = Form(""),
    expected_answer: str = Form(""),
    kind: str = Form("single"),
):
    if not text.strip():
        return RedirectResponse(f"/evals/sets/{set_id}?error=Type+a+question", status_code=303)
    ctx_of(request).store.add_questions(
        set_id, [{"text": text.strip(), "expected_answer": expected_answer.strip(), "kind": kind}]
    )
    return RedirectResponse(f"/evals/sets/{set_id}", status_code=303)


@router.post("/evals/sets/{set_id}/run")
def run_form(request: Request, set_id: str, name: str = Form("")):
    ctx = ctx_of(request)
    if not ctx.store.list_questions(set_id):
        return RedirectResponse(f"/evals/sets/{set_id}?error=This+set+has+no+questions+yet", status_code=303)
    run_id = runner.start_run(ctx, set_id, name.strip() or None)
    return RedirectResponse(f"/evals/runs/{run_id}", status_code=303)


def parse_question_lines(text: str) -> list[dict[str, Any]]:
    """
    Accept either a JSON list of {text, expected_answer} objects or plain lines
    "question | answer" (a tab works too). Lines without an answer are kept with an empty answer.
    """
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            items = json.loads(text)
            return [
                {
                    "text": str(i.get("text") or i.get("question") or "").strip(),
                    "expected_answer": str(i.get("expected_answer") or i.get("answer") or "").strip(),
                    "kind": i.get("kind", "single"),
                }
                for i in items
                if isinstance(i, dict) and (i.get("text") or i.get("question"))
            ]
        except json.JSONDecodeError:
            pass
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        sep = "\t" if "\t" in line else "|"
        question, _, answer = line.partition(sep)
        rows.append({"text": question.strip(), "expected_answer": answer.strip(), "kind": "single"})
    return [r for r in rows if r["text"]]


# ------------------------------------------------------------------ JSON

api = APIRouter(prefix="/api")


class QuestionIn(BaseModel):
    text: str = Field(min_length=1)
    expected_answer: str = ""
    kind: str = "single"
    gold_passage_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class SetBody(BaseModel):
    name: str = Field(min_length=1)
    questions: list[QuestionIn] = Field(default_factory=list)


class QuestionsBody(BaseModel):
    questions: list[QuestionIn]


class GenerateBody(BaseModel):
    max_single: int = Field(default=8, ge=0, le=100)
    max_multihop: int = Field(default=4, ge=0, le=50)
    name: str | None = None


class RunBody(BaseModel):
    name: str | None = None
    settings: dict[str, Any] | None = None


@api.get("/evals/sets")
def list_sets(request: Request):
    return ctx_of(request).store.list_question_sets()


@api.post("/evals/sets")
def create_set(request: Request, body: SetBody):
    ctx = ctx_of(request)
    set_id = ctx.store.create_question_set(body.name)
    ids = ctx.store.add_questions(set_id, [q.model_dump() for q in body.questions]) if body.questions else []
    return {"set_id": set_id, "question_ids": ids}


@api.get("/evals/sets/{set_id}")
def get_set(request: Request, set_id: str):
    ctx = ctx_of(request)
    question_set = ctx.store.get_question_set(set_id)
    if question_set is None:
        raise HTTPException(404, "no such question set")
    question_set["questions"] = ctx.store.list_questions(set_id)
    return question_set


@api.delete("/evals/sets/{set_id}")
def delete_set(request: Request, set_id: str):
    ctx_of(request).store.delete_question_set(set_id)
    return {"deleted": set_id}


@api.post("/evals/sets/{set_id}/questions")
def add_questions(request: Request, set_id: str, body: QuestionsBody):
    return {
        "question_ids": ctx_of(request).store.add_questions(set_id, [q.model_dump() for q in body.questions])
    }


@api.delete("/evals/questions/{question_id}")
def delete_question(request: Request, question_id: str):
    ctx_of(request).store.delete_question(question_id)
    return {"deleted": question_id}


@api.post("/sources/{source_id}/generate-questions")
def generate_questions(request: Request, source_id: str, body: GenerateBody | None = None):
    ctx = ctx_of(request)
    source = ctx.store.get_source(source_id)
    if source is None:
        raise HTTPException(404, "no such source")
    if source["status"] != "ready":
        return JSONResponse({"error": "wait until this source has finished indexing"}, status_code=409)
    body = body or GenerateBody()
    set_id = question_maker.start_generation_job(
        ctx, source_id, max_single=body.max_single, max_multihop=body.max_multihop, name=body.name
    )
    return {"set_id": set_id}


@api.post("/evals/sets/{set_id}/run")
def start_run(request: Request, set_id: str, body: RunBody | None = None):
    ctx = ctx_of(request)
    body = body or RunBody()
    try:
        run_id = runner.start_run(ctx, set_id, body.name, validate_settings(body.settings or {}))
    except ValueError as exc:
        raise HTTPException(404 if "unknown question set" in str(exc) else 400, str(exc)) from exc
    return {"run_id": run_id}


@api.get("/evals/runs")
def list_runs(request: Request, set_id: str | None = None):
    return ctx_of(request).store.list_runs(set_id)


@api.get("/evals/runs/{run_id}")
def get_run(request: Request, run_id: str):
    ctx = ctx_of(request)
    run = ctx.store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    run["results"] = ctx.store.list_results(run_id)
    return run


@api.delete("/evals/runs/{run_id}")
def delete_run(request: Request, run_id: str):
    ctx_of(request).store.delete_run(run_id)
    return {"deleted": run_id}
