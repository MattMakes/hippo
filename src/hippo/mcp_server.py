"""
The MCP server: lets an AI client (Claude Code, Claude Desktop, Cursor, ...)
use hippo's memory as tools.

MCP ("Model Context Protocol") is a small standard for "here are some tools
you can call". We expose nine:

    hippo_search          rank passages for a question (no LLM answer)
    hippo_ask             search, then let the local LLM answer from the passages
    hippo_remember        add a text to the memory and index it in the background
    hippo_sources         list what is in the memory and whether it is indexed
    hippo_whoami          who the server thinks you are, and what you may see and do
    hippo_explain_path    the relations that lead from one symbol to another
    hippo_blast_radius    who would feel a change to a symbol, level by level
    hippo_exception_path  how a function reaches an exception class
    hippo_history         the commits that touched a symbol, newest first

The last four walk the code graph a repository source builds. They answer in
the same shapes as `/api/code/*` (`web/routes/code.py` holds the builders both
surfaces call), and a name that could mean several symbols comes back as a
ToolError listing them, because a tool's error message is the only thing an MCP
client is shown.

Who is calling (hippo/access.py): every tool works on the caller's slice of
the memory. Over HTTP the caller is identified by a session cookie or `Authorization: Bearer
<token>` (each user's token is on their Account page; the web app's gate
already refused requests without one once users exist). Over stdio there are
no headers, so the token comes from the HIPPO_TOKEN environment variable. Until
the first user is created hippo is open and everything is visible.

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
import os
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers

from .access import Access, Principal
from .ask import ask, code_block, code_fields, search
from .context import AppContext
from .hipporag.paths import AmbiguousSymbol, UnknownSymbol
from .web.auth import StoreDown, principal_from_bearer, resolve_principal
from .web.routes.code import (
    DEFAULT_DEPTH,
    DEFAULT_HISTORY_LIMIT,
    blast_payload,
    exception_payload,
    history_payload,
    path_payload,
)
from .web.security import ANY_HOST

log = logging.getLogger(__name__)

MCP_PATH = "/mcp"
DEFAULT_TOP_K = 5
MAX_TOP_K = 20

INSTRUCTIONS = (
    "hippo is a long-term memory built on a knowledge graph (HippoRAG). "
    "Use hippo_search or hippo_ask to recall things that were stored, "
    "hippo_remember to store new text, hippo_sources to see what is stored, "
    "and hippo_whoami to learn which part of the memory you may see. "
    "When the memory holds a code repository, hippo_explain_path, hippo_blast_radius, "
    "hippo_exception_path and hippo_history walk its code graph directly."
)
TOKEN_ENV = "HIPPO_TOKEN"


# ---------------------------------------------------------- the caller


CredentialTransport = Literal["http", "stdio"]


def caller(ctx: AppContext, mcp_ctx: Context | None, *, transport: CredentialTransport = "http") -> Principal:
    """Resolve only credentials belonging to the explicitly selected transport."""
    if transport not in ("http", "stdio"):
        raise ValueError("Unknown credential transport")
    try:
        if not ctx.store.ping():
            raise StoreDown()
        if transport == "stdio":
            principal = principal_from_bearer(ctx, os.environ.get(TOKEN_ENV) or None, require_online=True)
        else:
            headers = None
            if mcp_ctx is not None:
                try:
                    headers = mcp_ctx.headers
                except ValueError:  # No HTTP request; never substitute process credentials.
                    pass
            principal = resolve_principal(ctx, Headers(headers or {}), require_online=True)
    except StoreDown as exc:
        raise ToolError("hippo cannot reach its database, so nobody can be signed in right now") from exc
    if principal is None:
        raise ToolError(
            "sign in required: HTTP needs your bearer token or session cookie; "
            "stdio needs HIPPO_TOKEN. Your token is on the Account page."
        )
    return principal


class TransportBoundServer(MCPServer):
    """Prevent a server carrying process credentials from being served over HTTP."""

    def __init__(self, *, credential_transport: CredentialTransport) -> None:
        if credential_transport not in ("http", "stdio"):
            raise ValueError("Unknown credential transport")
        super().__init__(name="hippo", instructions=INSTRUCTIONS)
        self._credential_transport = credential_transport

    def _require_transport(self, expected: CredentialTransport) -> None:
        if self._credential_transport != expected:
            raise ValueError(f"Server credential transport must be {expected}")

    def streamable_http_app(self, **kwargs):
        self._require_transport("http")
        return super().streamable_http_app(**kwargs)

    def sse_app(self, **kwargs):
        self._require_transport("http")
        return super().sse_app(**kwargs)

    async def run_stdio_async(self) -> None:
        self._require_transport("stdio")
        await super().run_stdio_async()


# --------------------------------------------------------------- building


def build_server(ctx: AppContext, *, transport: CredentialTransport = "http") -> MCPServer:
    """Create the MCP server with the nine hippo tools bound to this AppContext."""
    server = TransportBoundServer(credential_transport=transport)

    @server.tool(
        description=(
            "Search hippo's memory for passages relevant to a question. Returns the top passages "
            "(title, source, full text, score, rank) and the facts the retriever kept. "
            "Use this when you want the raw material and will reason over it yourself. "
            "Only passages you are allowed to see take part."
        )
    )
    def hippo_search(
        question: str, top_k: int = DEFAULT_TOP_K, mcp_ctx: Context | None = None
    ) -> dict[str, Any]:
        return search_tool(ctx, question, top_k, principal=caller(ctx, mcp_ctx, transport=transport))

    @server.tool(
        description=(
            "Ask hippo's memory a question and get a short answer written by the local LLM, "
            "with the passages it read. Use this for a direct answer; use hippo_search for the raw passages."
        )
    )
    def hippo_ask(question: str, mcp_ctx: Context | None = None) -> dict[str, Any]:
        return ask_tool(ctx, question, principal=caller(ctx, mcp_ctx, transport=transport))

    @server.tool(
        description=(
            "Store a piece of text in hippo's memory under a name. Indexing happens in the background; "
            "check hippo_sources for status. Returns the new source id. `visibility` is the id of the "
            "lowest role that may see it (see hippo_whoami for the roles you may use); by default "
            "your own tier and above."
        )
    )
    def hippo_remember(
        name: str, text: str, visibility: str | None = None, mcp_ctx: Context | None = None
    ) -> dict[str, Any]:
        return remember_tool(
            ctx, name, text, visibility=visibility, principal=caller(ctx, mcp_ctx, transport=transport)
        )

    @server.tool(
        description=(
            "List everything stored in hippo's memory that you may see: id, name, kind, indexing "
            "status and stage, passage count, who may see it, and any error."
        )
    )
    def hippo_sources(mcp_ctx: Context | None = None) -> list[dict[str, Any]]:
        return sources_tool(ctx, principal=caller(ctx, mcp_ctx, transport=transport))

    @server.tool(
        description=(
            "Who hippo thinks you are: your user, role and rank on the access ladder, what you may do, "
            "how many of the sources you can see, and the roles you may give to text you remember."
        )
    )
    def hippo_whoami(mcp_ctx: Context | None = None) -> dict[str, Any]:
        return whoami_tool(ctx, principal=caller(ctx, mcp_ctx, transport=transport))

    @server.tool(
        description=(
            "Explain how one symbol reaches another in an indexed repository: the fewest calls, "
            "imports, inheritance or data-access relations that lead from `a` to `b`, each with its "
            "confidence and why it was inferred. Names may be fully qualified "
            "(pkg.module.Class.method), module-relative (Class.method) or bare when unambiguous."
        )
    )
    def hippo_explain_path(a: str, b: str, mcp_ctx: Context | None = None) -> dict[str, Any]:
        return explain_path_tool(ctx, a, b, principal=caller(ctx, mcp_ctx, transport=transport))

    @server.tool(
        description=(
            "What a change to this symbol could break: everything that depends on it, `depth` "
            "levels of callers out (1-4, default 2), grouped by subsystem. Use before editing a "
            "function to see who else is affected."
        )
    )
    def hippo_blast_radius(
        symbol: str, depth: int = DEFAULT_DEPTH, mcp_ctx: Context | None = None
    ) -> dict[str, Any]:
        return blast_radius_tool(ctx, symbol, depth, principal=caller(ctx, mcp_ctx, transport=transport))

    @server.tool(
        description=(
            "How a function reaches an exception class: the RAISES relation itself, or the calls "
            "that lead to one. Use to answer 'where does this error come from'."
        )
    )
    def hippo_exception_path(symbol: str, exception: str, mcp_ctx: Context | None = None) -> dict[str, Any]:
        return exception_path_tool(
            ctx, symbol, exception, principal=caller(ctx, mcp_ctx, transport=transport)
        )

    @server.tool(
        description=(
            "The commits that touched this symbol, newest first: sha, date and subject. Needs a "
            "repository source indexed with git history; otherwise the list is empty."
        )
    )
    def hippo_history(
        symbol: str, limit: int = DEFAULT_HISTORY_LIMIT, mcp_ctx: Context | None = None
    ) -> dict[str, Any]:
        return history_tool(ctx, symbol, limit, principal=caller(ctx, mcp_ctx, transport=transport))

    return server


# ------------------------------------------------------------ the tools
# Kept as plain functions so they are easy to unit test without the MCP plumbing.


def search_tool(
    ctx: AppContext, question: str, top_k: int = DEFAULT_TOP_K, principal: Principal | None = None
) -> dict[str, Any]:
    question = _clean_question(question)
    top_k = max(1, min(int(top_k), MAX_TOP_K))
    access = principal.access if principal else None
    trace = search(ctx, question, access=access)
    graph = ctx.graph_for(access)
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
        **code_fields(trace, code_block(graph, trace)),
    }


def ask_tool(ctx: AppContext, question: str, principal: Principal | None = None) -> dict[str, Any]:
    question = _clean_question(question)
    trace, answer = ask(ctx, question, access=principal.access if principal else None)
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
    return {
        "answer": answer.answer,
        "thought": answer.thought,
        "sources": sources,
        **code_fields(trace, answer.context_block),
    }


# ------------------------------------------------------- the code graph tools
# Thin over `web/routes/code.py`'s builders: the shapes MCP returns and the shapes /api/code
# returns are the same objects, so a client can move between the two without relearning anything.


def _code_graph(ctx: AppContext, principal: Principal | None) -> tuple[Any, float]:
    access: Access | None = principal.access if principal else None
    return ctx.graph_for(access), float(ctx.store.get_settings().get("code_theta", 0.5))


def _code_answer(build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """
    ToolError is the one exception an MCP client is shown verbatim, so everything a caller could
    act on has to be inside its message - the candidates of an ambiguous name above all.
    """
    try:
        return build()
    except (AmbiguousSymbol, UnknownSymbol, ValueError) as exc:
        raise ToolError(str(exc)) from exc


def explain_path_tool(ctx: AppContext, a: str, b: str, principal: Principal | None = None) -> dict[str, Any]:
    index, theta = _code_graph(ctx, principal)
    return _code_answer(lambda: path_payload(index, a, b, theta=theta))


def blast_radius_tool(
    ctx: AppContext, symbol: str, depth: int = DEFAULT_DEPTH, principal: Principal | None = None
) -> dict[str, Any]:
    index, theta = _code_graph(ctx, principal)
    return _code_answer(lambda: blast_payload(index, symbol, theta=theta, depth=depth))


def exception_path_tool(
    ctx: AppContext, symbol: str, exception: str, principal: Principal | None = None
) -> dict[str, Any]:
    index, theta = _code_graph(ctx, principal)
    return _code_answer(lambda: exception_payload(index, symbol, exception, theta=theta))


def history_tool(
    ctx: AppContext,
    symbol: str,
    limit: int = DEFAULT_HISTORY_LIMIT,
    principal: Principal | None = None,
) -> dict[str, Any]:
    index, _theta = _code_graph(ctx, principal)
    return _code_answer(lambda: history_payload(index, symbol, limit=limit))


def remember_tool(
    ctx: AppContext,
    name: str,
    text: str,
    visibility: str | None = None,
    principal: Principal | None = None,
) -> dict[str, Any]:
    pipeline = _load_pipeline()
    principal = principal or Principal.open()
    if not principal.can("add_sources"):
        raise ToolError(f"your role ({principal.role_name}) may not add sources")
    role_id = None if principal.is_open else principal.role_id
    if visibility:
        if visibility == "everyone":
            role_id = None
        else:
            role = ctx.store.get_role(visibility)
            if role is None:
                raise ToolError(f"no role with id '{visibility}'; hippo_whoami lists the ones you may use")
            if not principal.may_assign_role(role):
                raise ToolError(f"you cannot restrict text to '{role['name']}': that tier is above yours")
            role_id = role["id"]
    try:
        source_id = pipeline.add_text(ctx, name, text, owner_id=principal.user_id, access_role_id=role_id)
    except ValueError as exc:  # e.g. empty text: the client should see why, not a generic crash
        raise ToolError(str(exc)) from exc
    source = ctx.store.get_source(source_id) or {}
    return {
        "source_id": source_id,
        "status": "queued",
        "name": name.strip() or "Untitled text",
        "visible_to": source.get("access_role_name", "Everyone"),
    }


def sources_tool(ctx: AppContext, principal: Principal | None = None) -> list[dict[str, Any]]:
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
            "visible_to": row.get("access_role_name", "Everyone"),
            "owner": row.get("owner_name") or None,
            "error": row.get("error"),
            "created_at": row.get("created_at"),
        }
        for row in ctx.store.list_sources(principal.access if principal else None)
    ]


def whoami_tool(ctx: AppContext, principal: Principal | None = None) -> dict[str, Any]:
    principal = principal or Principal.open()
    roles = ctx.store.list_roles()
    visible = ctx.store.list_sources(principal.access)
    total = len(ctx.store.list_sources()) if not principal.is_open else len(visible)
    return {
        "open_mode": principal.is_open,
        "user": None
        if principal.user is None
        else {
            "id": principal.user_id,
            "username": principal.user.get("username"),
            "display_name": principal.user.get("display_name", ""),
        },
        "role": {"id": principal.role_id, "name": principal.role_name, "rank": principal.rank},
        "can": sorted(c for c in principal.role.get("capabilities") or []),
        "sources_visible": len(visible),
        "sources_total": total,
        "ladder": [{"id": r["id"], "name": r["name"], "rank": r["rank"]} for r in roles],
        "visibility_you_may_use": ["everyone"] + [r["id"] for r in roles if principal.may_assign_role(r)],
    }


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
    mcp_app = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        transport_security=transport_security(ctx.config.allowed_hosts),
    )
    _wrap_lifespan(app, server)
    # The MCP app's own route is /mcp, so mounting it at "/" keeps the URL http://host:8000/mcp.
    # Starlette tries routes in order, so this catch-all only sees paths nothing else claimed.
    app.mount("/", mcp_app, name="mcp")
    return server


def transport_security(allowed_hosts: Iterable[str]) -> TransportSecuritySettings:
    """
    The MCP library's own DNS-rebinding check, fed the same host list as the web app's guard
    (hippo.web.security) so the two can never disagree. Its lists are exact strings with an
    optional ':*' port wildcard, so every host goes in twice: bare and with any port.
    """
    hosts = list(allowed_hosts)
    if ANY_HOST in hosts:  # the user switched the check off
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts + [f"{h}:*" for h in hosts],
        allowed_origins=[
            f"{scheme}://{h}{port}" for scheme in ("http", "https") for h in hosts for port in ("", ":*")
        ],
    )


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
    build_server(ctx, transport="stdio").run(transport="stdio")
