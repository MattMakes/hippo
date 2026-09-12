"""
The FastAPI application.

`create_app()` builds the app: it wires the shared AppContext, guards every
request against other websites (security.py) and against strangers once users
exist (auth.py), serves the static files, includes the page and API routers,
mounts the MCP server at /mcp, and on startup makes sure the store has its
schema and Ollama has its models (pulling them in the background if not).

Run it with `hippo serve` or `uvicorn hippo.web.app:create_app --factory`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..context import AppContext
from ..ingest.managed_activation import ManagedActorRequired, ManagedDispatchError
from ..knowledge.access import AuthorizationChanged
from ..knowledge.dense import DenseUnavailable
from ..knowledge.projection import ProjectionError
from ..ollama import OllamaError
from . import auth
from .render import STATIC_DIR, public_failure_response, render, retrieval_failure
from .routes import analyze, api, code, evals, graph, pages, sources, users
from .security import HostAndOriginGuard

log = logging.getLogger(__name__)

# Failures the closed table in `knowledge/public_errors.py` knows how to say out loud. A
# route that wants to shape its own body still catches them first; this is the net for every
# route that does not, so no activation or retrieval exception can reach a client as a
# traceback or as its own message. `httpx.TransportError` is here because the model client
# is httpx: an unwrapped connection error is still "the model is not answering".
PUBLIC_FAILURES = (
    OllamaError,
    DenseUnavailable,
    ProjectionError,
    ManagedDispatchError,
    httpx.TransportError,
)

# The stable code for the generic permission answer, which is not one of the four retrieval
# codes; see `authorization_changed` below.
AUTHORIZATION_CHANGED = "authorization_changed"


def create_app(ctx: AppContext | None = None) -> FastAPI:
    ctx = ctx or AppContext.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        startup(ctx)
        yield
        ctx.close()

    app = FastAPI(title="hippo", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
    app.state.ctx = ctx
    # Both wrap every route below, the static files and the mounted MCP app. The last one added
    # is the outermost, so the host guard (security.py) runs first: a foreign site is refused
    # before we even look for a user (auth.py).
    app.add_middleware(auth.AuthGate, ctx=ctx)
    app.add_middleware(HostAndOriginGuard, allowed_hosts=ctx.config.allowed_hosts)
    app.add_exception_handler(HTTPException, forbidden_page)
    app.add_exception_handler(AuthorizationChanged, authorization_changed)
    for failure in PUBLIC_FAILURES:
        app.add_exception_handler(failure, public_failure_page)
    # A managed operation an open or preview identity may not perform is a permission answer,
    # not a failure report. Starlette picks the handler by walking the exception's own class
    # first, so this wins over the ManagedDispatchError row above.
    app.add_exception_handler(ManagedActorRequired, authorization_changed)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(users.api)
    app.include_router(graph.router)
    app.include_router(graph.api)
    app.include_router(pages.router)
    app.include_router(sources.router)
    app.include_router(sources.api)
    app.include_router(evals.router)
    app.include_router(evals.api)
    app.include_router(analyze.router)
    app.include_router(analyze.api)
    app.include_router(api.router)
    app.include_router(code.api)
    # Every include_router must come before this: _mount_mcp mounts a catch-all at "/", and
    # Starlette tries routes in order, so anything added after it would never be reached.
    _mount_mcp(app, ctx)
    return app


async def authorization_changed(request: Request, exc: Exception):
    """
    The generic permission answer: the sentence clients already read, plus its stable code.

    `public_errors` maps `AuthorizationChanged` to `None` on purpose — a permission change is
    not a retrieval failure and has no status of its own — so the name lives here rather than
    in the closed table, and it is the same string the managed lane already stores for this
    condition (`public_errors._MANAGED_CODES["authorization_changed"]`). The exception's own
    words are never read: every caller of this response raises it with a different sentence.
    """
    return JSONResponse(
        {"error": "Permissions changed; repeat the query", "code": AUTHORIZATION_CHANGED},
        status_code=409,
    )


async def public_failure_page(request: Request, exc: Exception):
    """
    One stable code and one bounded sentence for a failure no route shaped itself.

    The same two helpers every web surface uses, so a client that moves between the pages,
    the JSON routes and the MCP tools reads one vocabulary: `retrieval_failure` applies the
    mapper's documented caller rule, and `public_failure_response` keeps the `{"error": ...}`
    shape the pages' JavaScript already reads while adding `code`.
    """
    return public_failure_response(retrieval_failure(exc))


async def forbidden_page(request: Request, exc: HTTPException):
    """
    A 403 on a page is rendered as a page that says which capability is missing; everything
    else keeps FastAPI's JSON shape ({"detail": ...}), which the pages' JavaScript already reads.
    """
    wants_html = "text/html" in request.headers.get("accept", "") and not request.url.path.startswith("/api")
    if exc.status_code == 403 and wants_html:
        return render(request, "forbidden.html", nav="", message=str(exc.detail), status_code=403)
    return JSONResponse(
        {"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None)
    )


def startup(ctx: AppContext) -> None:
    """Prepare the database schema and kick off model downloads. Never raises: the UI shows what is missing."""
    # ping() creates the schema and tidies interrupted jobs the first time the store answers,
    # so if Neo4j is not up yet nothing is lost: the first page load after it comes up does it.
    if not ctx.store.ping():
        log.warning(
            "the graph store at %s is not reachable yet; the Settings page will say so",
            ctx.config.store_location,
        )
    if ctx.ollama.is_up():
        missing = ctx.models.missing() if ctx.models else []
        if missing:
            log.info("Pulling missing Ollama models in the background: %s", ", ".join(missing))
            ctx.models.start_pull()
    else:
        log.warning("Ollama at %s is not reachable yet", ctx.config.ollama_url)


def _mount_mcp(app: FastAPI, ctx: AppContext) -> None:
    try:
        from ..mcp_server import mount
    except ImportError as exc:  # pragma: no cover - only while the MCP module is missing
        log.warning("MCP server not mounted: %s", exc)
        return
    mount(app, ctx)
