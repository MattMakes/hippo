"""
JSON endpoints. The pages' JavaScript uses them, and so can curl or scripts.

Errors come back as {"error": "..."} with a 4xx/5xx status.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ... import ask as ask_service
from ...ollama import OllamaError
from ...status import system_status
from ..auth import principal_of, require
from ..render import ctx_of

router = APIRouter(prefix="/api")


class QuestionBody(BaseModel):
    question: str = Field(min_length=1)
    settings: dict[str, Any] | None = None


# ------------------------------------------------------------------ status


@router.get("/status")
def status(request: Request):
    out = dict(system_status(ctx_of(request), fresh=True))
    principal = principal_of(request)
    if not principal.access.unrestricted:
        # Job keys name source ids ("index:<id>"); a restricted caller only learns how many are running.
        out["jobs"] = [key.split(":", 1)[0] for key in out.get("jobs", [])]
    return out


@router.get("/settings")
def get_settings(request: Request):
    return ctx_of(request).store.get_settings()


@router.put("/settings")
def put_settings(request: Request, changes: dict[str, Any]):
    require(request, "edit_graph")
    try:
        return ctx_of(request).store.update_settings(changes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/models/pull")
def pull_models(request: Request):
    require(request, "edit_graph")
    ctx = ctx_of(request)
    if not ctx.ollama.is_up():
        raise HTTPException(503, f"Ollama at {ctx.config.ollama_url} is not reachable")
    started = ctx.models.start_pull() if ctx.models else False
    return {"started": started, "missing": ctx.models.missing() if ctx.models else []}


# --------------------------------------------------------------- ask/search


@router.post("/ask")
def ask(request: Request, body: QuestionBody):
    ctx = ctx_of(request)
    try:
        trace, answer = ask_service.ask(
            ctx, body.question.strip(), body.settings, access=principal_of(request).access
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OllamaError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return {
        "answer": answer.answer,
        "thought": answer.thought,
        "passage_ids": answer.passage_ids,
        "trace": trace.to_dict(),
    }


@router.post("/search")
def search(request: Request, body: QuestionBody):
    ctx = ctx_of(request)
    try:
        trace = ask_service.search(
            ctx, body.question.strip(), body.settings, access=principal_of(request).access
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OllamaError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return {"trace": trace.to_dict()}


# ------------------------------------------------------------- graph lookups


@router.get("/entities")
def entities(request: Request, q: str = "", limit: int = 20):
    if not q.strip():
        return []
    return ctx_of(request).store.search_entities(
        q.strip(), limit=min(limit, 100), access=principal_of(request).access
    )


@router.get("/graph/neighborhood")
def neighborhood(request: Request, node_id: str, depth: int = 1, limit: int = 60):
    """A small piece of the graph around one node, shaped for Cytoscape: {nodes: [...], edges: [...]}."""
    index = ctx_of(request).graph_for(principal_of(request).access)
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
    nodes = [{"id": index.node_ids[v], "label": index.name_of(v), "kind": index.node_kind[v]} for v in seen]
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
    return {"nodes": nodes, "edges": edges}
