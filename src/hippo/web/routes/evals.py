"""
Evals: question sets, runs, and the history of results.

Pages render the tables; forms post here and redirect; the /api/evals/*
endpoints return JSON. The work itself (generating questions, running a set)
lives in hippo.evals and runs in background jobs.

Every route requires the `run_evals` capability and evaluation ownership.
Source labels, question inputs and saved output use current evidence permissions.
"""

from __future__ import annotations

import json
from functools import wraps
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ...evals import question_maker, runner
from ...knowledge.eval_access import EvalAccess, EvalAccessDenied
from ...knowledge.public_errors import OPERATION_FAILED, public_failure_for_code
from ...store.base import validate_settings
from ..auth import principal_of, require_capability
from ..render import STOP_POLLING, ctx_of, render

router = APIRouter(dependencies=[Depends(require_capability("run_evals"))])


def _service(request: Request) -> EvalAccess:
    if not hasattr(request.state, "evaluation_access"):
        request.state.evaluation_access = EvalAccess(ctx_of(request), principal_of(request).access)
    return request.state.evaluation_access


def _read_response(function):
    @wraps(function)
    def guarded(request: Request, *args, **kwargs):
        with _service(request).read_scope():
            return function(request, *args, **kwargs)

    return guarded


def _write(request: Request, method: str, *args, **kwargs):
    try:
        return getattr(_service(request), method)(*args, **kwargs)
    except EvalAccessDenied as exc:
        raise HTTPException(404, "no such evaluation") from exc


def public_reason(code: str | None) -> str:
    """The closed sentence for a code `EvalAccess` passed through, never a stored string.

    An evaluation row that is presenting a failure must not fall silent, so a code this
    table does not map takes the caller fallback `public_errors` documents. Only the
    message is read: `invalid_source` covers two HTTP statuses, so a stored code can
    never be turned back into one.
    """
    if not code:
        return ""
    return (public_failure_for_code(code) or OPERATION_FAILED).message


# `errors` first: a reader who cannot tell that retrieval failed cannot read any of the rest.
SUMMARY_CARDS = [
    ("errors", "Errors", "questions whose retrieval or answer failed"),
    ("accuracy", "Accuracy", "mean judge score: correct 1, partial ½, incorrect 0"),
    ("exact_match", "Exact match", "answer equals the expected one after normalising"),
    ("f1", "F1", "word overlap between answer and expected"),
    ("recall@5", "Recall@5", "share of gold passages found in the top 5"),
    ("gold_in_top5", "Gold in top 5", "questions whose gold passage was in the top 5"),
    ("mean_gold_rank", "Mean gold rank", "average rank of the best gold passage (lower is better)"),
    ("code_seeded", "Code seeded", "questions whose search opened a code seed from a lexical anchor"),
    ("path_fidelity", "Path fidelity", "commit questions: share of the touched symbols found in the top 5"),
    ("dpr_fallbacks", "Fallbacks", "questions answered by embedding search only"),
    ("mean_latency_ms", "Latency (ms)", "average time per question"),
]


# ---------------------------------------------------------------- pages


@router.get("/evals")
@_read_response
def evals_page(request: Request, source: str = "", error: str = ""):
    sets = _service(request).list_question_sets()
    if source:
        sets = [qs for qs in sets if qs.get("source_id") == source]
    return render(
        request,
        "evals.html",
        nav="evals",
        sets=sets,
        runs=_service(request).list_runs(),
        error=error,
        cards=SUMMARY_CARDS,
    )


@router.get("/partials/evals/tables")
@_read_response
def evals_tables_partial(request: Request):
    """Both tables, polled by the Evals page while questions are being written or a run is going."""
    sets = _service(request).list_question_sets()
    runs = _service(request).list_runs()
    busy = any(qs["status"] == "generating" for qs in sets) or any(r["status"] == "running" for r in runs)
    return render(
        request, "partials/evals_tables.html", sets=sets, runs=runs, status_code=200 if busy else STOP_POLLING
    )


@router.get("/evals/sets/{set_id}")
@_read_response
def set_page(request: Request, set_id: str, error: str = ""):
    question_set = _service(request).get_question_set(set_id)
    if question_set is None:
        raise HTTPException(404, "no such question set")
    return render(
        request,
        "eval_set.html",
        nav="evals",
        question_set=question_set,
        questions=_service(request).list_questions(set_id),
        runs=_service(request).list_runs(set_id),
        error=error,
        public_reason=public_reason,
    )


@router.get("/evals/runs/{run_id}")
@_read_response
def run_page(request: Request, run_id: str, compare: str = ""):
    run = _service(request).get_run(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    results = _service(request).list_results(run_id)
    siblings = [r for r in _service(request).list_runs(run["set_id"]) if r["id"] != run_id]
    other = _service(request).get_run(compare) if compare else None
    return render(
        request,
        "eval_run.html",
        nav="evals",
        run=run,
        results=results,
        siblings=siblings,
        other=other,
        cards=SUMMARY_CARDS,
        public_reason=public_reason,
    )


@router.get("/partials/runs/{run_id}")
@_read_response
def run_partial(request: Request, run_id: str, compare: str = ""):
    """The run page body, polled while the run is going; answers 286 once it is over so polling stops."""
    run = _service(request).get_run(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    return render(
        request,
        "partials/run_body.html",
        run=run,
        results=_service(request).list_results(run_id),
        cards=SUMMARY_CARDS,
        other=_service(request).get_run(compare) if compare else None,
        public_reason=public_reason,
        status_code=200 if run["status"] == "running" else STOP_POLLING,
    )


# ----------------------------------------------------------- page forms


@router.post("/evals/sets")
def create_set_form(request: Request, name: str = Form(""), questions: str = Form("")):
    rows = parse_question_lines(questions)
    if not rows:
        return RedirectResponse(
            "/evals?error=Add+at+least+one+question+line+like+%27question+%7C+answer%27", status_code=303
        )
    set_id = _write(request, "create_question_set", name.strip() or "My questions")
    _write(request, "add_questions", set_id, rows)
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
    _write(
        request,
        "add_questions",
        set_id,
        [{"text": text.strip(), "expected_answer": expected_answer.strip(), "kind": kind}],
    )
    return RedirectResponse(f"/evals/sets/{set_id}", status_code=303)


@router.post("/evals/sets/{set_id}/run")
def run_form(request: Request, set_id: str, name: str = Form("")):
    ctx = ctx_of(request)
    _write(request, "require_set", set_id)
    if not _service(request).list_questions(set_id):
        return RedirectResponse(f"/evals/sets/{set_id}?error=This+set+has+no+questions+yet", status_code=303)
    run_id = runner.start_run(ctx, set_id, name.strip() or None, access=principal_of(request).access)
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

api = APIRouter(prefix="/api", dependencies=[Depends(require_capability("run_evals"))])


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
@_read_response
def list_sets(request: Request):
    return _service(request).list_question_sets()


@api.post("/evals/sets")
def create_set(request: Request, body: SetBody):
    set_id = _write(request, "create_question_set", body.name)
    ids = (
        _write(request, "add_questions", set_id, [q.model_dump() for q in body.questions])
        if body.questions
        else []
    )
    return {"set_id": set_id, "question_ids": ids}


@api.get("/evals/sets/{set_id}")
@_read_response
def get_set(request: Request, set_id: str):
    question_set = _service(request).get_question_set(set_id)
    if question_set is None:
        raise HTTPException(404, "no such question set")
    question_set["questions"] = _service(request).list_questions(set_id)
    return question_set


@api.delete("/evals/sets/{set_id}")
def delete_set(request: Request, set_id: str):
    _write(request, "delete_question_set", set_id)
    return {"deleted": set_id}


@api.post("/evals/sets/{set_id}/questions")
def add_questions(request: Request, set_id: str, body: QuestionsBody):
    return {
        "question_ids": _write(request, "add_questions", set_id, [q.model_dump() for q in body.questions])
    }


@api.delete("/evals/questions/{question_id}")
def delete_question(request: Request, question_id: str):
    _write(request, "delete_question", question_id)
    return {"deleted": question_id}


@api.post("/sources/{source_id}/generate-questions")
def generate_questions(request: Request, source_id: str, body: GenerateBody | None = None):
    ctx = ctx_of(request)
    principal = principal_of(request)
    source = _service(request).get_source(source_id)
    if source is None:
        raise HTTPException(404, "no such source")
    if source["status"] != "ready":
        return JSONResponse({"error": "wait until this source has finished indexing"}, status_code=409)
    body = body or GenerateBody()
    try:
        set_id = question_maker.start_generation_job(
            ctx,
            source_id,
            max_single=body.max_single,
            max_multihop=body.max_multihop,
            name=body.name,
            access=principal.access,
        )
    except EvalAccessDenied as exc:
        raise HTTPException(404, "no such source") from exc
    return {"set_id": set_id}


@api.post("/evals/sets/{set_id}/run")
def start_run(request: Request, set_id: str, body: RunBody | None = None):
    ctx = ctx_of(request)
    body = body or RunBody()
    try:
        run_id = runner.start_run(
            ctx,
            set_id,
            body.name,
            validate_settings(body.settings or {}),
            access=principal_of(request).access,
        )
    except ValueError as exc:
        raise HTTPException(404 if "unknown question set" in str(exc) else 400, str(exc)) from exc
    return {"run_id": run_id}


@api.get("/evals/runs")
@_read_response
def list_runs(request: Request, set_id: str | None = None):
    return _service(request).list_runs(set_id)


@api.get("/evals/runs/{run_id}")
@_read_response
def get_run(request: Request, run_id: str):
    run = _service(request).get_run(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    run["results"] = _service(request).list_results(run_id)
    return run


@api.delete("/evals/runs/{run_id}")
def delete_run(request: Request, run_id: str):
    _write(request, "delete_run", run_id)
    return {"deleted": run_id}
