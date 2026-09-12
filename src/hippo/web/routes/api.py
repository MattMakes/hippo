"""
JSON endpoints. The pages' JavaScript uses them, and so can curl or scripts.

Errors come back as {"error": "..."} with a 4xx/5xx status.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ... import ask as ask_service
from ...knowledge.access import AuthorizationChanged
from ...knowledge.answer_evidence import answer_sources, retrieval_fields
from ...knowledge.query_access import query_session
from ...ollama import OllamaError
from ...status import system_status
from ...store.base import validate_settings
from ..auth import principal_of, require
from ..render import caller_error, ctx_of, public_failure_response, retrieval_failure

router = APIRouter(prefix="/api")


class QuestionBody(BaseModel):
    question: str = Field(min_length=1)
    settings: dict[str, Any] | None = None


# ------------------------------------------------------------------ status


@router.get("/status")
def status(request: Request):
    return system_status(ctx_of(request), fresh=True, access=principal_of(request).access)


@router.get("/settings")
def get_settings(request: Request):
    return ctx_of(request).store.get_settings()


@router.put("/settings")
def put_settings(request: Request, changes: dict[str, Any]):
    require(request, "edit_graph")
    # The caller's own numbers are refused with the store validator's sentence, which is
    # the one 4xx `detail` the plan protects. `update_settings` validates the same dict
    # again, so past this line nothing it raises is the caller's mistake: a storage
    # failure carries whatever it was reading and belongs to the closed public table.
    checked_settings(changes)
    try:
        return ctx_of(request).store.update_settings(changes)
    except (ValueError, OllamaError, httpx.TransportError) as exc:
        return public_failure_response(retrieval_failure(exc))


@router.post("/models/pull")
def pull_models(request: Request):
    require(request, "edit_graph")
    ctx = ctx_of(request)
    if not ctx.ollama.is_up():
        raise HTTPException(503, f"Ollama at {ctx.config.ollama_url} is not reachable")
    started = ctx.models.start_pull() if ctx.models else False
    return {"started": started, "missing": ctx.models.missing() if ctx.models else []}


# --------------------------------------------------------------- ask/search


# `ask_service.code_fields` is what the MCP tools spread into their own answers, so the five code
# keys mean the same thing over HTTP as over MCP and cannot drift apart. `code_graph` is the one
# thing a caller could not otherwise reconstruct: the trace carries the rows, but the rendered
# `Title: Code graph` block is built during the answer and used to reach no HTTP client at all
# (QA1 surprise 3).


def checked_settings(settings: dict[str, Any] | None) -> None:
    """The caller's own numbers keep the store validator's message; nothing else does.

    Validating them here, before a session exists, is what makes the failure mapping below
    unambiguous: past this line a `ValueError` is never the caller's request, so it can be
    mapped to a closed public code without swallowing "damping must be between 0 and 1".

    `caller_error` is what makes "nothing else does" true rather than hopeful. The store
    validator raises the exact `ValueError`; any subclass reaching this line came from
    somewhere that names a path or quotes stored text, and is re-raised for the mapper.
    """
    try:
        validate_settings(dict(settings or {}))
    except ValueError as exc:
        if not caller_error(exc):
            raise
        raise HTTPException(400, str(exc)) from exc


def query_failure(exc: BaseException) -> JSONResponse:
    """One closed code for a failed query, never the exception's own words.

    A model path must not let an unknown exception reach the client. `retrieval_failure` is
    that caller rule, shared with the page surfaces and the app's own handlers so the three
    cannot drift apart.
    """
    return public_failure_response(retrieval_failure(exc))


@router.post("/ask")
def ask(request: Request, body: QuestionBody):
    ctx = ctx_of(request)
    access = principal_of(request).access
    try:
        # Inside the mapped scope, not before it: the settings check itself answers 400 for
        # the caller's own numbers (an `HTTPException`, re-raised untouched below), and
        # anything else it raises is a failure the closed table has to name.
        checked_settings(body.settings)
        with query_session(ctx, access, settings=body.settings) as session:
            trace, answer = ask_service.ask(
                ctx, body.question.strip(), body.settings, access=access, session=session
            )
            payload = {
                "answer": answer.answer,
                "thought": answer.thought,
                "passage_ids": answer.passage_ids,
                "retrieval_passage_ids": answer.retrieval_passage_ids,
                "sources": answer_sources(session.graph, trace, answer),
                "trace": trace.to_dict(),
                **ask_service.code_fields(trace, answer.context_block),
            }
            session.validate()
            return payload
    # A permission change while the answer was being built outranks whatever failed: it is
    # the only thing a caller must act on, and the app answers it with the same 409 as ever.
    except AuthorizationChanged:
        raise
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - the closed table decides what a client learns
        return query_failure(exc)


@router.post("/search")
def search(request: Request, body: QuestionBody):
    ctx = ctx_of(request)
    access = principal_of(request).access
    try:
        checked_settings(body.settings)  # see `ask` above for why this is inside the scope
        with query_session(ctx, access, settings=body.settings) as session:
            trace = ask_service.search(
                ctx, body.question.strip(), body.settings, access=access, session=session
            )
            block = ask_service.code_block(session.graph, trace)
            payload = {
                "trace": trace.to_dict(),
                **retrieval_fields(session.graph, [row.passage_id for row in trace.passages]),
                **ask_service.code_fields(trace, block),
            }
            session.validate()
            return payload
    except AuthorizationChanged:
        raise
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - the closed table decides what a client learns
        return query_failure(exc)


# ------------------------------------------------------------- graph lookups


@router.get("/entities")
def entities(request: Request, q: str = "", limit: int = 20):
    if not q.strip():
        return []
    with query_session(ctx_of(request), principal_of(request).access) as session:
        index = session.graph
        needle = q.strip().lower()
        rows = [
            {
                "id": identity,
                "name": name,
                "passage_count": int(index.entity_passage_count[index.idx_of[identity]]),
            }
            for identity, name in index.entity_names.items()
            if needle in name.lower()
        ]
        rows.sort(key=lambda row: (-row["passage_count"], row["name"]))
        payload = rows[: max(0, min(limit, 100))]
        session.validate()
        return payload


@router.get("/graph/neighborhood")
def neighborhood(request: Request, node_id: str, depth: int = 1, limit: int = 60):
    """A small piece of the graph around one node, shaped for Cytoscape: {nodes: [...], edges: [...]}."""
    with query_session(ctx_of(request), principal_of(request).access) as session:
        index = session.graph
        start = index.idx_of.get(node_id)
        if start is None:
            raise HTTPException(404, "unknown node")
        seen = {start}
        frontier = [start]
        for _ in range(max(0, min(depth, 3))):
            nxt = []
            for v in frontier:
                for other, _w in sorted(index.neighbors(v), key=lambda t: -t[1]):
                    if other not in seen and len(seen) < limit:
                        seen.add(other)
                        nxt.append(other)
            frontier = nxt
        nodes = [
            {"id": index.node_ids[v], "label": index.name_of(v), "kind": index.node_kind[v]} for v in seen
        ]
        edges = []
        for v in seen:
            for other, w in index.neighbors(v):
                if other in seen and v < other:
                    e = index.edge_between(v, other)
                    edges.append(
                        {
                            "source": index.node_ids[v],
                            "target": index.node_ids[other],
                            "weight": w,
                            "kinds": e.kinds if e else [],
                        }
                    )
        payload = {"nodes": nodes, "edges": edges}
        session.validate()
        return payload
