"""
Analyze: the deep dive into one question, plus changesets.

The page shows what the search did (candidate facts, the filter's choice,
seed entities, PPR results), draws the piece of the graph that mattered,
explains each passage, and offers a "tweak & simulate" panel. Simulations
call /api/simulate; the edits you like can be saved as a changeset and
applied to the graph from /changesets.

Ad-hoc analyses (a question typed in, not a stored result) keep their trace
in a small in-memory cache so simulations can replay the LLM's fact filter
without paying for it again.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ... import ask as ask_service
from ...analysis.changesets import apply as apply_changeset_ops
from ...analysis.changesets import describe as describe_ops
from ...analysis.changesets import save as save_changeset_ops
from ...analysis.explain import explain
from ...analysis.simulate import Overrides
from ...analysis.simulate import simulate as run_simulation
from ...hipporag.retriever import Trace, trace_from_dict
from ...ollama import OllamaError
from ...store.base import new_id
from ..render import ctx_of, render

router = APIRouter()
api = APIRouter(prefix="/api")

_ADHOC: OrderedDict[str, dict[str, Any]] = OrderedDict()  # trace_key -> {"trace": dict, "answer": dict}
_ADHOC_LOCK = threading.Lock()
ADHOC_LIMIT = 50


def remember_adhoc(trace: Trace, answer: dict[str, Any] | None) -> str:
    key = new_id()
    with _ADHOC_LOCK:
        _ADHOC[key] = {"trace": trace.to_dict(), "answer": answer}
        while len(_ADHOC) > ADHOC_LIMIT:
            _ADHOC.popitem(last=False)
    return key


def recall_adhoc(key: str) -> dict[str, Any] | None:
    with _ADHOC_LOCK:
        return _ADHOC.get(key)


# ---------------------------------------------------------------- pages


@router.get("/analyze")
def analyze_adhoc(request: Request, question: str = "", key: str = ""):
    """Analyze a question typed in right now (or one analysed a moment ago, by cache key)."""
    ctx = ctx_of(request)
    cached = recall_adhoc(key) if key else None
    if cached is None:
        question = question.strip()
        if not question:
            return RedirectResponse("/ask", status_code=303)
        try:
            trace, answer = ask_service.ask(ctx, question)
        except OllamaError as exc:
            return render(request, "analyze.html", nav="ask", error=str(exc), question=question)
        key = remember_adhoc(trace, {"answer": answer.answer, "thought": answer.thought})
        return RedirectResponse(f"/analyze?key={key}", status_code=303)
    trace = trace_from_dict(cached["trace"])
    return _render_analysis(request, trace, result=None, answer=cached["answer"], history=[], trace_key=key)


@router.get("/analyze/{result_id}")
def analyze_result(request: Request, result_id: str):
    ctx = ctx_of(request)
    result = ctx.store.get_result(result_id)
    if result is None:
        raise HTTPException(404, "no such result")
    trace = trace_from_dict(result.get("trace") or {})
    if not trace.question:
        trace.question = result["question"]
    history = ctx.store.results_for_question(result["question_id"])
    answer = {"answer": result.get("answer", ""), "thought": result.get("thought", "")}
    return _render_analysis(request, trace, result=result, answer=answer, history=history, trace_key="")


def _render_analysis(request: Request, trace: Trace, *, result, answer, history, trace_key: str):
    ctx = ctx_of(request)
    index = ctx.graph()
    explanation = explain(index, trace)
    gold_ids = set((result or {}).get("gold_passage_ids") or [])
    # Text for exactly the passages the explanation covers, so the two can never disagree.
    previews = {ranked.passage_id: ranked.preview for ranked in trace.passages}
    passage_text = {}
    for explained in explanation.passages:
        passage = index.passage_by_id(explained.passage_id)
        passage_text[explained.passage_id] = (
            passage.text if passage else previews.get(explained.passage_id, "")
        )
    return render(
        request,
        "analyze.html",
        nav="evals" if result else "ask",
        question=trace.question,
        result=result,
        answer=answer,
        history=history,
        trace=trace,
        explanation=explanation,
        gold_ids=gold_ids,
        passage_text=passage_text,
        trace_key=trace_key,
        graph_changed=trace.graph_version != index.version,
        current_settings=ctx.store.get_settings(),
        ask_url=f"/ask?q={quote(trace.question)}",
    )


@router.get("/changesets")
def changesets_page(request: Request, open: str = ""):
    ctx = ctx_of(request)
    items = ctx.store.list_changesets()
    for item in items:
        item["described"] = describe_ops(ctx, item["ops"])
    return render(request, "changesets.html", nav="changesets", changesets=items, open_id=open)


# ------------------------------------------------------------------ JSON


class SimulateBody(BaseModel):
    question: str = ""
    result_id: str | None = None
    trace_key: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class ChangesetBody(BaseModel):
    name: str = Field(min_length=1)
    ops: list[dict[str, Any]]
    from_result_id: str | None = None
    note: str = ""


@api.post("/simulate")
def simulate(request: Request, body: SimulateBody):
    ctx = ctx_of(request)
    baseline: Trace | None = None
    if body.result_id:
        stored = ctx.store.get_result(body.result_id)
        if stored is None:
            raise HTTPException(404, "no such result")
        baseline = trace_from_dict(stored.get("trace") or {})
        if not baseline.question:
            baseline.question = stored["question"]
    elif body.trace_key:
        cached = recall_adhoc(body.trace_key)
        if cached is None:
            raise HTTPException(404, "that analysis has expired; analyze the question again")
        baseline = trace_from_dict(cached["trace"])
    question = (baseline.question if baseline else body.question).strip()
    if not question:
        raise HTTPException(400, "question is required")
    try:
        overrides = Overrides.from_dict(body.overrides)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(400, f"bad overrides: {exc}") from exc
    try:
        outcome = run_simulation(ctx, question, overrides, baseline)
    except OllamaError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    index = ctx.graph()
    explanation = explain(index, outcome.trace)
    return {
        "trace": outcome.trace.to_dict(),
        "diff": outcome.diff,
        "answer": {"answer": outcome.answer.answer, "thought": outcome.answer.thought}
        if outcome.answer
        else None,
        "explanation": explanation.to_dict(),
        "ops": overrides.to_ops(),
    }


@api.get("/changesets")
def list_changesets(request: Request):
    return ctx_of(request).store.list_changesets()


@api.post("/changesets")
def create_changeset(request: Request, body: ChangesetBody):
    ctx = ctx_of(request)
    try:
        changeset_id = save_changeset_ops(
            ctx, body.name, body.ops, from_result_id=body.from_result_id, note=body.note
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"changeset_id": changeset_id}


@api.post("/changesets/{changeset_id}/apply")
def apply_changeset(request: Request, changeset_id: str):
    ctx = ctx_of(request)
    if ctx.store.get_changeset(changeset_id) is None:
        raise HTTPException(404, "no such changeset")
    try:
        return apply_changeset_ops(ctx, changeset_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.delete("/changesets/{changeset_id}")
def delete_changeset(request: Request, changeset_id: str):
    ctx_of(request).store.delete_changeset(changeset_id)
    return {"deleted": changeset_id}
