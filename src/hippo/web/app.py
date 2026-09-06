"""
The FastAPI application.

`create_app()` builds the app: it wires the shared AppContext, serves the
static files, includes the page and API routers, mounts the MCP server at
/mcp, and on startup makes sure Neo4j has its schema and Ollama has its
models (pulling them in the background if not).

Run it with `hippo serve` or `uvicorn hippo.web.app:create_app --factory`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..context import AppContext
from .render import STATIC_DIR
from .routes import analyze, api, evals, pages, sources

log = logging.getLogger(__name__)


def create_app(ctx: AppContext | None = None) -> FastAPI:
    ctx = ctx or AppContext.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        startup(ctx)
        yield
        ctx.close()

    app = FastAPI(title="hippo", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
    app.state.ctx = ctx
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(pages.router)
    app.include_router(sources.router)
    app.include_router(sources.api)
    app.include_router(evals.router)
    app.include_router(evals.api)
    app.include_router(analyze.router)
    app.include_router(analyze.api)
    app.include_router(api.router)
    _mount_mcp(app, ctx)
    return app


def startup(ctx: AppContext) -> None:
    """Prepare the database schema and kick off model downloads. Never raises: the UI shows what is missing."""
    if ctx.store.ping():
        ctx.store.ensure_schema()
        interrupted = ctx.store.mark_interrupted_jobs()
        if interrupted:
            log.warning("%d job(s) were interrupted by the last shutdown and are marked failed", interrupted)
    else:
        log.warning("Neo4j at %s is not reachable yet; the Settings page will say so", ctx.config.neo4j_uri)
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
