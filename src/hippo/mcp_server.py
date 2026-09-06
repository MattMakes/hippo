"""
The MCP server: lets an AI client (Claude Code, Claude Desktop, Cursor, ...)
use hippo's memory as tools.

MCP ("Model Context Protocol") is a small standard for "here are some tools
you can call". We expose four:

    hippo_search    rank passages for a question (no LLM answer)
    hippo_ask       search, then let the local LLM answer from the passages
    hippo_remember  add a text to the memory and index it in the background
    hippo_sources   list what is in the memory and whether it is indexed

The same server can be reached two ways:

* **Over HTTP, inside the web app.** `hippo.web.app.create_app` calls
  `mount(app, ctx)`, which mounts the MCP Starlette app under the FastAPI app so
  clients connect to http://localhost:8000/mcp. The MCP session manager must be
  "running" for as long as the web app is up, so `mount` also wraps the FastAPI
  lifespan. Expected usage:

      app = FastAPI(lifespan=my_lifespan)
      ... include routers ...
      hippo.mcp_server.mount(app, ctx)   # call this LAST: it mounts a catch-all at "/"

* **Over stdio**, for clients that start the server themselves:
  `hippo mcp` calls `run_stdio(ctx)`. Nothing may print to stdout in that mode
  (stdout is the protocol channel), so the CLI sends logging to stderr.

Tool functions are plain synchronous Python and return JSON-friendly dicts and
lists; the mcp library runs them in a worker thread and serialises the result.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .ask import ask, search
from .context import AppContext

log = logging.getLogger(__name__)

MCP_PATH = "/mcp"
DEFAULT_TOP_K = 5
MAX_TOP_K = 20

INSTRUCTIONS = (
    "hippo is a long-term memory built on a knowledge graph (HippoRAG). "
    "Use hippo_search or hippo_ask to recall things that were stored, "
    "hippo_remember to store new text, and hippo_sources to see what is stored."
)


# --------------------------------------------------------------- building


def build_server(ctx: AppContext) -> MCPServer:
    """Create the MCP server with the four hippo tools bound to this AppContext."""
    server = MCPServer(name="hippo", instructions=INSTRUCTIONS)

    @server.tool(
        description=(
            "Search hippo's memory for passages relevant to a question. Returns the top passages "
            "(title, source, full text, score, rank) and the facts the retriever kept. "
            "Use this when you want the raw material and will reason over it yourself."
        )
    )
    def hippo_search(question: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
        return search_tool(ctx, question, top_k)

    @server.tool(
        description=(
            "Ask hippo's memory a question and get a short answer written by the local LLM, "
            "with the passages it read. Use this for a direct answer; use hippo_search for the raw passages."
        )
    )
    def hippo_ask(question: str) -> dict[str, Any]:
        return ask_tool(ctx, question)

    @server.tool(
        description=(
            "Store a piece of text in hippo's memory under a name. Indexing happens in the background; "
            "check hippo_sources for status. Returns the new source id."
        )
    )
    def hippo_remember(name: str, text: str) -> dict[str, Any]:
        return remember_tool(ctx, name, text)

    @server.tool(
        description=(
            "List everything stored in hippo's memory: id, name, kind, indexing status and stage, "
            "passage count, and any error."
        )
    )
    def hippo_sources() -> list[dict[str, Any]]:
        return sources_tool(ctx)

    return server


# ------------------------------------------------------------ the tools
# Kept as plain functions so they are easy to unit test without the MCP plumbing.


def search_tool(ctx: AppContext, question: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    question = _clean_question(question)
    top_k = max(1, min(int(top_k), MAX_TOP_K))
    trace = search(ctx, question)
    graph = ctx.graph()
    passages = []
    for ranked in trace.passages[:top_k]:
        passage = graph.passage_by_id(ranked.passage_id)
        passages.append(
            {
                "passage_id": ranked.passage_id,
                "title": ranked.title,
                "source": ranked.source_name,
                "text": passage.text if passage else ranked.preview,
                "score": round(ranked.score, 6),
                "rank": ranked.rank,
            }
        )
    kept_facts = [c.triple for c in trace.fact_candidates if c.kept]
    return {
        "question": question,
        "passages": passages,
        "kept_facts": kept_facts,
        "used_dpr_fallback": trace.used_dpr_fallback,
    }


def ask_tool(ctx: AppContext, question: str) -> dict[str, Any]:
    question = _clean_question(question)
    trace, answer = ask(ctx, question)
    # Only the passages the LLM actually read count as "sources" of the answer.
    read = set(answer.passage_ids)
    sources = [
        {
            "passage_id": p.passage_id,
            "title": p.title,
            "source": p.source_name,
            "rank": p.rank,
            "score": round(p.score, 6),
        }
        for p in trace.passages
        if p.passage_id in read
    ]
    return {"answer": answer.answer, "thought": answer.thought, "sources": sources}


def remember_tool(ctx: AppContext, name: str, text: str) -> dict[str, Any]:
    pipeline = _load_pipeline()
    try:
        source_id = pipeline.add_text(ctx, name, text)
    except ValueError as exc:  # e.g. empty text: the client should see why, not a generic crash
        raise ToolError(str(exc)) from exc
    return {"source_id": source_id, "status": "queued", "name": name.strip() or "Untitled text"}


def sources_tool(ctx: AppContext) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "status": row["status"],
            "stage": row.get("stage"),
            "progress_done": row.get("progress_done", 0),
            "progress_total": row.get("progress_total", 0),
            "passages": row.get("passages", 0),
            "error": row.get("error"),
            "created_at": row.get("created_at"),
        }
        for row in ctx.store.list_sources()
    ]


def _clean_question(question: str) -> str:
    question = (question or "").strip()
    if not question:
        # ToolError is the one exception the mcp library shows to the client verbatim;
        # anything else is treated as a crash and its message is hidden.
        raise ToolError("the question is empty")
    return question


def _load_pipeline():  # noqa: ANN202 - the return type lives in a module that may not exist yet
    """Import the ingest pipeline only when needed, with a clear message if it is not installed."""
    try:
        from .ingest import pipeline
    except ImportError as exc:
        raise ToolError(
            "hippo.ingest.pipeline is not available, so hippo_remember cannot add text. "
            f"Install the full hippo package. ({exc})"
        ) from exc
    return pipeline


# ------------------------------------------------------------- serving


def mount(app: FastAPI, ctx: AppContext) -> MCPServer:
    """Serve the MCP server at /mcp inside a FastAPI app. Call this after every other route is added."""
    server = build_server(ctx)
    # Stateless: every request stands alone, so no session ids to lose when the container restarts.
    # DNS-rebinding protection is off because inside Docker the Host header is whatever the user
    # typed (localhost:8000, a LAN name, ...) and we would otherwise reject them all.
    mcp_app = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    _wrap_lifespan(app, server)
    # The MCP app's own route is /mcp, so mounting it at "/" keeps the URL http://host:8000/mcp.
    # Starlette tries routes in order, so this catch-all only sees paths nothing else claimed.
    app.mount("/", mcp_app, name="mcp")
    return server


def _wrap_lifespan(app: FastAPI, server: MCPServer) -> None:
    """Keep the MCP session manager running for as long as the FastAPI app is up."""
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        async with inner(app_) as state:
            async with server.session_manager.run():
                log.info("MCP server ready at %s", MCP_PATH)
                yield state

    app.router.lifespan_context = lifespan


def run_stdio(ctx: AppContext) -> None:
    """Run the MCP server over stdin/stdout (for `hippo mcp`). Blocks until the client disconnects."""
    build_server(ctx).run(transport="stdio")
