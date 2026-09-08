"""
The code graph over HTTP: name lookup, paths, blast radius, exception routes and history.

    GET /api/code/symbols?q=&limit=            names that match, with where they are defined
    GET /api/code/path?a=&b=                   the relations that lead from one symbol to another
    GET /api/code/blast-radius?symbol=&depth=  who would feel a change here, level by level
    GET /api/code/exception-path?symbol=&exception=   how a function reaches an exception
    GET /api/code/history?symbol=&limit=       the commits that touched a symbol, newest first

Every endpoint reads `ctx.graph_for(access)` - the caller's own slice - and nothing else, so a
symbol whose source is hidden is not merely refused, it is not there to be refused. That is worth
saying twice for `/symbols`: `name_index` is built once on the full index and `scoped()` passes the
*same dict* on, so a hit must be resolved through the scoped `code_node_by_id` (which goes through
the scoped `idx_of`) before it is returned. Filtering on the dict alone would list hidden names.

The payload builders raise the path tools' own errors (`UnknownSymbol`, `AmbiguousSymbol`), mapped
here the way `analyze.py` maps its own: unknown -> 404, ambiguous -> 409 carrying the candidates so
a client can offer them, anything malformed -> 400. The builders themselves are plain functions over
a `GraphIndex`, because `mcp_server.py` serves the last four of these answers as MCP tools and calls
the same builders to do it - the HTTP and MCP shapes are the same objects, not two descriptions of
one shape that could drift apart.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ...hipporag.graph_index import GraphIndex
from ...hipporag.paths import (
    AmbiguousSymbol,
    UnknownSymbol,
    blast_radius,
    display_at,
    display_of,
    exception_path,
    history,
    history_rows,
    render_blast,
    render_triples,
    resolve_symbol,
    shortest_code_path,
    triple_rows,
)
from ..auth import principal_of
from ..render import ctx_of

api = APIRouter(prefix="/api/code")

DEFAULT_SYMBOL_LIMIT = 20
MAX_SYMBOL_LIMIT = 100
MIN_DEPTH = 1
MAX_DEPTH = 4
DEFAULT_DEPTH = 2
DEFAULT_HISTORY_LIMIT = 3
MAX_HISTORY_LIMIT = 50


# ---------------------------------------------------------- payload builders
# Pure: a GraphIndex in, JSON-friendly dicts out, and the path tools' own exceptions raised as
# they come. `mcp_server.py` calls these too, so the MCP and HTTP answers are the same shape.


def symbol_rows(index: GraphIndex, q: str, limit: int = DEFAULT_SYMBOL_LIMIT) -> list[dict[str, Any]]:
    """Code nodes whose name, qualname or one of its tokens contains `q`, by display name."""
    needle = (q or "").strip().lower()
    if not needle:
        return []
    found = {}
    for key, node_ids in index.name_index.items():
        if needle not in key:
            continue
        for node_id in node_ids:
            # Resolves through the scoped `idx_of`: a hidden source's symbol comes back as None.
            node = index.code_node_by_id(node_id)
            if node is not None:
                found[node_id] = node
    ordered = sorted(found.values(), key=lambda n: (display_of(n), n.id))
    return [_symbol_row(node) for node in ordered[: max(0, min(int(limit), MAX_SYMBOL_LIMIT))]]


def _symbol_row(node) -> dict[str, Any]:
    return {
        "id": node.id,
        "display": display_of(node),
        "name": node.name,
        "qualname": node.qualname,
        "kind": node.kind,  # symbol / data / commit
        "code_kind": node.code_kind,  # function / method / table / ...
        "lang": node.lang,
        "path": node.path,
        "line_start": node.line_start,
        "line_end": node.line_end,
    }


def path_payload(index: GraphIndex, a: str, b: str, *, theta: float) -> dict[str, Any]:
    """The fewest relations that lead from `a` to `b`, rendered in the answer block's grammar."""
    a_id, b_id = _required(a, "a"), _required(b, "b")
    a_id, b_id = resolve_symbol(index, a_id), resolve_symbol(index, b_id)
    edges = shortest_code_path(index, index.idx_of[a_id], index.idx_of[b_id], theta=theta)
    rows = triple_rows(index, edges)
    return {
        "a": display_of(index.code_node_by_id(a_id)),
        "b": display_of(index.code_node_by_id(b_id)),
        "a_id": a_id,
        "b_id": b_id,
        "found": bool(edges),
        "edges": rows,
        "lines": render_triples(rows),
    }


def blast_payload(index: GraphIndex, symbol: str, *, theta: float, depth: int) -> dict[str, Any]:
    """Who depends on this symbol, `depth` levels of callers out (clamped 1-4)."""
    node_id = resolve_symbol(index, _required(symbol, "symbol"))
    depth = max(MIN_DEPTH, min(int(depth), MAX_DEPTH))
    blast = blast_radius(index, index.idx_of[node_id], theta=theta, depth=depth)
    return {
        "symbol": display_of(index.code_node_by_id(node_id)),
        "symbol_id": node_id,
        "depth": depth,
        "levels": [sorted(display_at(index, v) for v in level) for level in blast.levels],
        "truncated": blast.truncated,
        "lines": render_blast(index, blast),
    }


def exception_payload(index: GraphIndex, symbol: str, exception: str, *, theta: float) -> dict[str, Any]:
    """How a function reaches an exception class: the RAISES edge, or the calls that lead to one."""
    node_id = resolve_symbol(index, _required(symbol, "symbol"))
    wanted = _required(exception, "exception")
    edges = exception_path(index, index.idx_of[node_id], wanted, theta=theta)
    rows = triple_rows(index, edges)
    return {
        "symbol": display_of(index.code_node_by_id(node_id)),
        "symbol_id": node_id,
        "exception": display_of(index.code_node_by_id(resolve_symbol(index, wanted))),
        "found": bool(edges),
        "edges": rows,
        "lines": render_triples(rows),
    }


def history_payload(index: GraphIndex, symbol: str, *, limit: int = DEFAULT_HISTORY_LIMIT) -> dict[str, Any]:
    """The commits that touched a symbol, newest first. Empty when no history was indexed."""
    node_id = resolve_symbol(index, _required(symbol, "symbol"))
    limit = max(1, min(int(limit), MAX_HISTORY_LIMIT))
    rows = history_rows(history(index, index.idx_of[node_id], limit=limit))
    return {
        "symbol": display_of(index.code_node_by_id(node_id)),
        "symbol_id": node_id,
        "commits": rows,
        "lines": [commit_line(row) for row in rows],
    }


def commit_line(row: dict[str, Any]) -> str:
    """One commit as the answer block writes it, minus the `Commits: ` label."""
    return f"{(row.get('sha') or '')[:7]} {row.get('date', '')} {row.get('subject', '')}".rstrip()


def _required(value: str, name: str) -> str:
    """A blank required argument is the caller's mistake (400), not a symbol that does not exist."""
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


# ------------------------------------------------------------------- routes


def _graph(request: Request) -> tuple[GraphIndex, float]:
    """The caller's slice of the graph, and the ω floor the path tools filter by (`code_theta`)."""
    ctx = ctx_of(request)
    index = ctx.graph_for(principal_of(request).access)
    return index, float(ctx.store.get_settings().get("code_theta", 0.5))


def _answer(build: Callable[[], Any]) -> Any:
    """`analyze.py`'s mapping, plus the 409 that carries what the caller could have meant."""
    try:
        return build()
    except AmbiguousSymbol as exc:
        return JSONResponse({"detail": str(exc), "candidates": exc.candidates}, status_code=409)
    except UnknownSymbol as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/symbols")
def symbols(request: Request, q: str = "", limit: int = DEFAULT_SYMBOL_LIMIT):
    index, _theta = _graph(request)
    return _answer(lambda: symbol_rows(index, q, limit))


@api.get("/path")
def code_path(request: Request, a: str, b: str):
    index, theta = _graph(request)
    return _answer(lambda: path_payload(index, a, b, theta=theta))


@api.get("/blast-radius")
def blast(request: Request, symbol: str, depth: int = DEFAULT_DEPTH):
    index, theta = _graph(request)
    return _answer(lambda: blast_payload(index, symbol, theta=theta, depth=depth))


@api.get("/exception-path")
def raises(request: Request, symbol: str, exception: str):
    index, theta = _graph(request)
    return _answer(lambda: exception_payload(index, symbol, exception, theta=theta))


@api.get("/history")
def commits(request: Request, symbol: str, limit: int = DEFAULT_HISTORY_LIMIT):
    index, _theta = _graph(request)
    return _answer(lambda: history_payload(index, symbol, limit=limit))
