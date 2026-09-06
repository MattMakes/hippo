"""
The Library: pages and JSON endpoints for sources (things you uploaded).

Forms post here and redirect back to the page; the /api/sources/* endpoints
return JSON for scripts and for the pages' polling.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ...ingest import pipeline
from ...ingest.pipeline import Busy
from ...ingest.repos import RepoError
from ..render import STOP_POLLING, ctx_of, render

router = APIRouter()

PASSAGES_PER_PAGE = 25
BUSY_STATUSES = {"queued", "reading", "indexing"}  # a source in one of these still changes on its own


# ---------------------------------------------------------------- pages


@router.get("/")
def library(request: Request, error: str = ""):
    ctx = ctx_of(request)
    sources = ctx.store.list_sources() if ctx.store.ping() else []
    return render(
        request, "library.html", nav="library", sources=sources, error=error, busy_ids=busy_source_ids(ctx)
    )


@router.get("/partials/sources")
def sources_partial(request: Request):
    """The sources table, polled by the Library page while something is being indexed."""
    ctx = ctx_of(request)
    sources = ctx.store.list_sources()
    busy = any(s["status"] in BUSY_STATUSES for s in sources)
    return render(
        request,
        "partials/source_rows.html",
        sources=sources,
        busy_ids=busy_source_ids(ctx),
        status_code=200 if busy else STOP_POLLING,
    )


def busy_source_ids(ctx) -> set[str]:
    """Ids of sources whose index job is running right now (their Delete/Reindex buttons are disabled)."""
    return {key.split(":", 1)[1] for key in ctx.jobs.running_keys() if key.startswith("index:")}


@router.get("/sources/{source_id}")
def source_page(request: Request, source_id: str, page: int = 1):
    ctx = ctx_of(request)
    source = ctx.store.get_source(source_id)
    if source is None:
        raise HTTPException(404, "no such source")
    page = max(1, page)
    passages = ctx.store.passages_for_source(
        source_id, limit=PASSAGES_PER_PAGE, offset=(page - 1) * PASSAGES_PER_PAGE
    )
    question_sets = [qs for qs in ctx.store.list_question_sets() if qs.get("source_id") == source_id]
    pages = max(1, -(-source["passages"] // PASSAGES_PER_PAGE))
    return render(
        request,
        "source.html",
        nav="library",
        source=source,
        passages=passages,
        question_sets=question_sets,
        page=page,
        pages=pages,
        busy=ctx.jobs.is_running(f"index:{source_id}"),
    )


@router.get("/partials/sources/{source_id}/status")
def source_status_partial(request: Request, source_id: str):
    ctx = ctx_of(request)
    source = ctx.store.get_source(source_id)
    if source is None:
        raise HTTPException(404, "no such source")
    busy = source["status"] in BUSY_STATUSES
    return render(
        request, "partials/source_status.html", source=source, status_code=200 if busy else STOP_POLLING
    )


# ----------------------------------------------------------- page forms


def too_big(request: Request, ctx) -> str | None:
    """A message when the request body is larger than the upload limit, checked before reading it."""
    limit = pipeline.max_upload_bytes(ctx)
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    if length > limit:
        return f"that upload is {length:,} bytes; the limit is {limit:,} bytes (HIPPO_MAX_UPLOAD_BYTES)"
    return None


@router.post("/sources/upload")
async def upload_form(request: Request, files: list[UploadFile] = File(...)):
    ctx = ctx_of(request)
    if message := too_big(request, ctx):
        return RedirectResponse(f"/?error={quote(message)}", status_code=303)
    added = 0
    for upload in files:
        data = await upload.read()
        if not data or not upload.filename:
            continue
        try:
            pipeline.add_upload(ctx, upload.filename, data)
            added += 1
        except ValueError as exc:
            return RedirectResponse(f"/?error={exc}", status_code=303)
    if added == 0:
        return RedirectResponse("/?error=No+files+were+uploaded", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/sources/text")
def text_form(request: Request, name: str = Form(""), text: str = Form("")):
    if not text.strip():
        return RedirectResponse("/?error=Paste+some+text+first", status_code=303)
    pipeline.add_text(ctx_of(request), name.strip() or "Pasted text", text)
    return RedirectResponse("/", status_code=303)


@router.post("/sources/repo")
def repo_form(request: Request, url: str = Form("")):
    try:
        pipeline.add_repo(ctx_of(request), url.strip())
    except (RepoError, ValueError) as exc:
        return RedirectResponse(f"/?error={exc}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/sources/sample")
def sample_form(request: Request):
    pipeline.add_sample(ctx_of(request))
    return RedirectResponse("/", status_code=303)


# ------------------------------------------------------------------ JSON

api = APIRouter(prefix="/api/sources")


class TextBody(BaseModel):
    name: str = Field(default="Pasted text")
    text: str = Field(
        min_length=1, max_length=pipeline.DEFAULT_MAX_UPLOAD_BYTES
    )  # coarse; add_text does the byte check


class RepoBody(BaseModel):
    url: str = Field(min_length=1)


@api.get("")
def list_sources(request: Request) -> list[dict[str, Any]]:
    return ctx_of(request).store.list_sources()


@api.post("/text")
def add_text(request: Request, body: TextBody):
    try:
        return {"source_id": pipeline.add_text(ctx_of(request), body.name, body.text)}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@api.post("/upload")
async def add_upload(request: Request, file: UploadFile = File(...)):
    if message := too_big(request, ctx_of(request)):
        return JSONResponse({"error": message}, status_code=413)
    data = await file.read()
    try:
        return {"source_id": pipeline.add_upload(ctx_of(request), file.filename or "upload", data)}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@api.post("/repo")
def add_repo(request: Request, body: RepoBody):
    try:
        return {"source_id": pipeline.add_repo(ctx_of(request), body.url)}
    except (RepoError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@api.post("/sample")
def add_sample(request: Request):
    return {"source_id": pipeline.add_sample(ctx_of(request))}


@api.post("/reindex-all")
def reindex_all(request: Request):
    """Re-index every source with the current embedding model (the fix for a changed HIPPO_EMBED_MODEL)."""
    try:
        return {"started": pipeline.reindex_all(ctx_of(request))}
    except Busy as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


@api.get("/{source_id}")
def get_source(request: Request, source_id: str):
    source = ctx_of(request).store.get_source(source_id)
    if source is None:
        raise HTTPException(404, "no such source")
    return source


@api.delete("/{source_id}")
def delete_source(request: Request, source_id: str):
    ctx = ctx_of(request)
    if ctx.store.get_source(source_id) is None:
        raise HTTPException(404, "no such source")
    try:
        pipeline.delete_source(ctx, source_id)
    except Busy as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    return {"deleted": source_id}


@api.post("/{source_id}/reindex")
def reindex(request: Request, source_id: str):
    ctx = ctx_of(request)
    if ctx.store.get_source(source_id) is None:
        raise HTTPException(404, "no such source")
    try:
        return {"started": pipeline.reindex(ctx, source_id)}
    except Busy as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
