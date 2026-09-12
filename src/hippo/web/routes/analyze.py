"""
Analyze: the deep dive into one question, plus changesets.

The page shows what the search did (candidate facts, the filter's choice,
seed entities, PPR results), draws the piece of the graph that mattered,
explains each passage, and offers a "tweak & simulate" panel. Simulations
call /api/simulate; the edits you like can be saved as a changeset and
applied to the graph from /changesets.

Ad-hoc analyses (a question typed in, not a stored result) keep their trace
in a small in-memory cache (hippo.web.adhoc) so the page shows the answer
the user just saw and simulations can replay the LLM's fact filter without
paying for it again. Only POST /analyze runs the search and the model: a GET
never does, so a link (or an <img src>) cannot start LLM work.

That split decides which session each route holds. POST /analyze and POST
/api/simulate embed a question, so they dispatch through `retrieval_session`.
The GET pages explain a trace that already exists over a structural
`query_session`, and resolve no embedding profile at all - which is what keeps
reading an analysis possible while the model is unreachable.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ... import ask as ask_service
from ...analysis.changesets import describe as describe_ops
from ...analysis.explain import explain
from ...analysis.simulate import Overrides
from ...analysis.simulate import simulate as run_simulation
from ...hipporag.paths import render_triples
from ...hipporag.retriever import Trace, trace_from_dict
from ...knowledge.access import AuthorizationChanged
from ...knowledge.answer_evidence import retrieval_fields
from ...knowledge.changeset_access import ChangesetAccess, ChangesetUnavailable
from ...knowledge.dense_session import retrieval_session
from ...knowledge.eval_access import EvalAccess
from ...knowledge.query_access import query_session
from ...ollama import OllamaError
from ...store.base import SETTING_RULES
from ..adhoc import ADHOC_LIMIT, recall_adhoc, remember_adhoc
from ..auth import principal_of, require
from ..render import ctx_of, public_failure_page, public_failure_response, render, retrieval_failure

router = APIRouter()
api = APIRouter(prefix="/api")


# ---------------------------------------------------------------- pages


@router.get("/analyze")
def analyze_adhoc(request: Request, question: str = "", key: str = ""):
    """Show the analysis cached under `key` (from the Ask page). Never runs the model: see analyze_submit."""
    principal = principal_of(request)
    try:
        with query_session(ctx_of(request), principal.access) as session:
            index, validate = session.graph, session.validate
            cached = recall_adhoc(key, principal.user_id, graph=index) if key else None
            if cached is None:
                question = question.strip()
                if not question:
                    return RedirectResponse("/ask", status_code=303)
                return render(
                    request,
                    "analyze.html",
                    nav="ask",
                    error=f"That analysis is no longer in memory (hippo keeps the last {ADHOC_LIMIT}, until it restarts).",
                    question=question,
                    retry_question=question,
                    status_code=404,
                    session=session,
                )
            trace = trace_from_dict(cached["trace"])
            return _render_analysis(
                request,
                trace,
                result=None,
                answer=cached["answer"],
                history=[],
                trace_key=key,
                index=index,
                authorization_check=validate,
                session=session,
            )
    except (ValueError, OllamaError, httpx.TransportError) as exc:
        # The page composes its own view, so it maps its own failure, exactly as the
        # form below does and at the status the mapper gives it. `AuthorizationChanged`
        # is a `RuntimeError` and stays uncaught, so a revocation still answers 409.
        return public_failure_page(request, retrieval_failure(exc), "analyze.html", nav="ask")


@router.post("/analyze")
def analyze_submit(request: Request, question: str = Form("")):
    """Run the search and the model for a question typed in right now, then show the analysis."""
    ctx = ctx_of(request)
    principal = principal_of(request)
    question = question.strip()
    if not question:
        return RedirectResponse("/ask", status_code=303)
    try:
        trace, answer = ask_service.ask(ctx, question, access=principal.access)
    except (ValueError, OllamaError, httpx.TransportError) as exc:
        # The provider's own words can name a file, quote source text or carry a token.
        # The page says the one bounded sentence the mapper allows and nothing else, at
        # the status the mapper gives it: a failure rendered at 200 tells a client, a
        # cache and a crawler that the question was answered.
        failure = retrieval_failure(exc)
        return render(
            request,
            "analyze.html",
            nav="ask",
            error=failure.message,
            question=question,
            status_code=failure.http_status,
        )
    key = remember_adhoc(trace, {"answer": answer.answer, "thought": answer.thought}, owner=principal.user_id)
    # The question rides along so an expired key can offer "analyze it again".
    return RedirectResponse(f"/analyze?key={key}&question={quote(question)}", status_code=303)


@router.get("/analyze/{result_id}")
def analyze_result(request: Request, result_id: str):
    require(request, "run_evals")  # stored results belong to the Evals section
    ctx = ctx_of(request)
    principal = principal_of(request)
    try:
        with query_session(ctx, principal.access) as session:
            index, validate = session.graph, session.validate
            evaluation = EvalAccess(ctx, principal.access, session=session)
            result = evaluation.get_result(result_id)
            if result is None:
                raise HTTPException(404, "no such result")
            validate = _saved_result_check(session, evaluation, result_id)
            trace = trace_from_dict(result.get("trace") or {})
            if not trace.question:
                trace.question = result["question"]
            history = evaluation.results_for_question(result["question_id"])
            answer = {"answer": result.get("answer", ""), "thought": result.get("thought", "")}
            return _render_analysis(
                request,
                trace,
                result=result,
                answer=answer,
                history=history,
                trace_key="",
                index=index,
                authorization_check=validate,
                session=session,
            )
    except (ValueError, OllamaError, httpx.TransportError) as exc:
        return public_failure_page(request, retrieval_failure(exc), "analyze.html", nav="evals")


def _saved_result_check(session, evaluation, result_id):
    """Saved questions retain their current ownership and existence checks."""

    def validate():
        session.validate()
        if evaluation.get_result(result_id) is None:
            raise AuthorizationChanged("Evaluation result is no longer available")

    return validate


def _render_analysis(
    request: Request,
    trace: Trace,
    *,
    result,
    answer,
    history,
    trace_key: str,
    index,
    authorization_check,
    session,
):
    principal = principal_of(request)
    # Explained on the caller's own slice of the graph: a stored eval trace may name passages
    # that this caller may not see; they simply go unexplained, with no text shown (below).
    authorization_check()
    explanation = explain(index, trace)
    gold_ids = set((result or {}).get("gold_passage_ids") or [])
    # Text for exactly the passages the explanation covers, so the two can never disagree.
    previews = {ranked.passage_id: ranked.preview for ranked in trace.passages}
    passage_text = {}
    for explained in explanation.passages:
        passage = index.passage_by_id(explained.passage_id)
        if passage is not None:
            passage_text[explained.passage_id] = passage.text
        elif principal.access.unrestricted:
            passage_text[explained.passage_id] = previews.get(explained.passage_id, "")
        else:
            passage_text[explained.passage_id] = "(not visible to you)"
    evidence = retrieval_fields(
        index, [identity for identity in passage_text if index.passage_by_id(identity) is not None]
    )
    originals = {citation["id"]: citation for citation in evidence["citations"]}
    passage_evidence = {
        item["passage_id"]: {
            "is_derived": item["is_derived"],
            "originals": [originals[identity] for identity in item["citation_ids"]],
        }
        for item in evidence["retrieval_evidence"]
    }
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
        passage_evidence=passage_evidence,
        # The S2.15 grammar is rendered here, by the same function the answer block uses, so the
        # page and the block can never drift into two spellings of one relation.
        path_lines=render_triples(trace.paths),
        seed_from=_seed_symbol_sources(index, trace),
        rules=SETTING_RULES,
        trace_key=trace_key,
        graph_changed=trace.graph_version != index.version,
        current_settings=dict(session.settings),
        authorization_check=authorization_check,
        session=session,
        ask_url=f"/ask?q={quote(trace.question)}",
        can_edit=principal.can("edit_graph"),
    )


def _seed_symbol_sources(index, trace: Trace) -> dict[str, str]:
    """
    What to print in the seed-symbols table's "From" column, per `SeedSymbol.matched_by`.

    A lexical anchor's `matched_by` is the token the reader typed and stands on its own. A dense
    seed's is the id of the passage it was pulled from, and `passage-<32 hex>` says nothing - the
    passage's title does. A passage this caller cannot see (a stored eval trace) keeps its id.
    """
    out: dict[str, str] = {}
    for seed in trace.seed_symbols:
        if seed.how != "dense" or not seed.matched_by:
            continue
        passage = index.passage_by_id(seed.matched_by)
        out[seed.matched_by] = passage.title if passage else seed.matched_by
    return out


@router.get("/changesets")
def changesets_page(request: Request, open: str = ""):
    require(request, "edit_graph")
    ctx = ctx_of(request)
    try:
        with query_session(ctx, principal_of(request).access) as session:
            view = ChangesetAccess(ctx, principal_of(request).access, session=session)
            items = view.list()
            for item in items:
                item["described"] = describe_ops(ctx, item["ops"], index=view.graph)
            return render(
                request,
                "changesets.html",
                nav="changesets",
                changesets=items,
                open_id=open,
                authorization_check=view.validate,
                session=session,
            )
    except (ValueError, OllamaError, httpx.TransportError) as exc:
        return public_failure_page(request, retrieval_failure(exc), "changesets.html", nav="changesets")


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
    principal = principal_of(request)
    try:
        return _simulate(request, ctx, principal, body)
    except (ValueError, OllamaError, httpx.TransportError) as exc:
        # `HTTPException` (the caller's own 404/400) and `AuthorizationChanged` are
        # neither, so both keep the response they already had.
        return public_failure_response(retrieval_failure(exc))


def _simulate(request: Request, ctx, principal, body: SimulateBody):
    """One dispatched owner for the whole simulation, from baseline to explanation."""
    with retrieval_session(ctx, principal.access) as session:
        index, validate = session.graph, session.validate
        baseline: Trace | None = None
        if body.result_id:
            require(request, "run_evals")
            evaluation = EvalAccess(ctx, principal.access, session=session)
            stored = evaluation.get_result(body.result_id)
            if stored is None:
                raise HTTPException(404, "no such result")
            validate = _saved_result_check(session, evaluation, body.result_id)
            baseline = trace_from_dict(stored.get("trace") or {})
            if not baseline.question:
                baseline.question = stored["question"]
        elif body.trace_key:
            cached = recall_adhoc(body.trace_key, principal.user_id, graph=index)
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
        # A model failure is mapped by the caller, outside this scope, so that the
        # session's own release still proves the caller's permissions first: a
        # revocation during the failing call must answer 409, not the model's code.
        outcome = run_simulation(
            ctx,
            question,
            overrides,
            baseline,
            access=principal.access,
            authorization_check=validate,
            session=session,
        )
        explanation = explain(index, outcome.trace)
        response = {
            "trace": outcome.trace.to_dict(),
            **retrieval_fields(index, [row.passage_id for row in outcome.trace.passages]),
            "diff": outcome.diff,
            "answer": {"answer": outcome.answer.answer, "thought": outcome.answer.thought}
            if outcome.answer
            else None,
            "explanation": explanation.to_dict(),
            "ops": overrides.to_ops(),
        }
        validate()
        return response


@api.get("/changesets")
def list_changesets(request: Request):
    require(request, "edit_graph")
    return ChangesetAccess(ctx_of(request), principal_of(request).access).list()


@api.post("/changesets")
def create_changeset(request: Request, body: ChangesetBody):
    require(request, "edit_graph")
    ctx = ctx_of(request)
    try:
        changeset_id = ChangesetAccess(ctx, principal_of(request).access).save(
            body.name, body.ops, from_result_id=body.from_result_id, note=body.note
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"changeset_id": changeset_id}


@api.post("/changesets/{changeset_id}/apply")
def apply_changeset(request: Request, changeset_id: str):
    require(request, "edit_graph")
    ctx = ctx_of(request)
    try:
        return ChangesetAccess(ctx, principal_of(request).access).apply(changeset_id)
    except ChangesetUnavailable as exc:
        raise HTTPException(404, "no such changeset") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.delete("/changesets/{changeset_id}")
def delete_changeset(request: Request, changeset_id: str):
    require(request, "edit_graph")
    try:
        ChangesetAccess(ctx_of(request), principal_of(request).access).delete(changeset_id)
    except ChangesetUnavailable as exc:
        raise HTTPException(404, "no such changeset") from exc
    return {"deleted": changeset_id}
