"""
The Library: pages and JSON endpoints for sources (things you uploaded).

Forms post here and redirect back to the page; the /api/sources/* endpoints
return JSON for scripts and for the pages' polling.

Access (hippo/access.py): the list and every lookup are scoped to what the
caller may see; adding needs `add_sources` and records the caller as owner
with their own tier as the default visibility; deleting, re-indexing and
changing who may see a source need `manage_sources` or ownership.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ...access import Principal, roles_at_or_below
from ...ingest import pipeline
from ...ingest.pipeline import Busy
from ...ingest.repos import RepoError
from ..auth import principal_of, require
from ..render import STOP_POLLING, ctx_of, render

router = APIRouter()

PASSAGES_PER_PAGE = 25
BUSY_STATUSES = {"queued", "reading", "indexing"}  # a source in one of these still changes on its own


# ---------------------------------------------------------------- pages


def visibility_choices(ctx, principal: Principal) -> list[dict[str, Any]]:
    """The tiers this caller may give a source: their own and every one below (open mode: all)."""
    roles = ctx.store.list_roles() if ctx.store.ping() else []
    if principal.is_open:
        return sorted(roles, key=lambda r: -r["rank"])
    return roles_at_or_below(roles, principal.rank)


def default_visibility(principal: Principal) -> str | None:
    """New sources are visible to the caller's own tier and above; in open mode, to everyone."""
    return None if principal.is_open else principal.role_id


def with_manage_flags(sources: list[dict[str, Any]], principal: Principal) -> list[dict[str, Any]]:
    for source in sources:
        source["can_manage"] = principal.may_manage_source(source)
        source["is_mine"] = bool(principal.user_id) and source.get("owner_id") == principal.user_id
    return sources


@router.get("/")
def library(request: Request, error: str = ""):
    ctx = ctx_of(request)
    principal = principal_of(request)
    sources = ctx.store.list_sources(principal.access) if ctx.store.ping() else []
    return render(
        request,
        "library.html",
        nav="library",
        sources=with_manage_flags(sources, principal),
        error=error,
        busy_ids=busy_source_ids(ctx),
        principal=principal,
        can_add=principal.can("add_sources"),
        visibility_choices=visibility_choices(ctx, principal),
        default_visibility=default_visibility(principal),
        total_sources=len(ctx.store.list_sources()) if ctx.store.ping() and not principal.is_open else None,
    )


@router.get("/partials/sources")
def sources_partial(request: Request):
    """The sources table, polled by the Library page while something is being indexed."""
    ctx = ctx_of(request)
    principal = principal_of(request)
    sources = ctx.store.list_sources(principal.access)
    busy = any(s["status"] in BUSY_STATUSES for s in sources)
    return render(
        request,
        "partials/source_rows.html",
        sources=with_manage_flags(sources, principal),
        busy_ids=busy_source_ids(ctx),
        principal=principal,
        visibility_choices=visibility_choices(ctx, principal),
        status_code=200 if busy else STOP_POLLING,
    )


def busy_source_ids(ctx) -> set[str]:
    """Ids of sources whose index job is running right now (their Delete/Reindex buttons are disabled)."""
    return {key.split(":", 1)[1] for key in ctx.jobs.running_keys() if key.startswith("index:")}


def visible_source(request: Request, source_id: str) -> dict[str, Any]:
    """The source, if the caller may see it; a hidden source looks exactly like a missing one."""
    source = ctx_of(request).store.get_source(source_id, principal_of(request).access)
    if source is None:
        raise HTTPException(404, "no such source")
    return source


def manageable_source(request: Request, source_id: str) -> dict[str, Any]:
    source = visible_source(request, source_id)
    principal = principal_of(request)
    if not principal.may_manage_source(source):
        raise HTTPException(
            403, f"only the owner or a role with 'manage_sources' may change '{source['name']}'"
        )
    return source


@router.get("/sources/{source_id}")
def source_page(request: Request, source_id: str, page: int = 1):
    ctx = ctx_of(request)
    principal = principal_of(request)
    source = visible_source(request, source_id)
    page = max(1, page)
    passages = ctx.store.passages_for_source(
        source_id, limit=PASSAGES_PER_PAGE, offset=(page - 1) * PASSAGES_PER_PAGE, access=principal.access
    )
    question_sets = (
        [qs for qs in ctx.store.list_question_sets() if qs.get("source_id") == source_id]
        if principal.can("run_evals")
        else []
    )
    pages = max(1, -(-source["passages"] // PASSAGES_PER_PAGE))
    return render(
        request,
        "source.html",
        nav="library",
        source=with_manage_flags([source], principal)[0],
        passages=passages,
        question_sets=question_sets,
        page=page,
        pages=pages,
        busy=ctx.jobs.is_running(f"index:{source_id}"),
        principal=principal,
        visibility_choices=visibility_choices(ctx, principal),
        can_evals=principal.can("run_evals"),
    )


@router.get("/partials/sources/{source_id}/status")
def source_status_partial(request: Request, source_id: str):
    source = visible_source(request, source_id)
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


def new_source_access(request: Request, visibility: str | None) -> dict[str, Any]:
    """
    The owner/visibility keyword arguments for pipeline.add_*: needs `add_sources`; the tier is the
    caller's own unless the form picked another one at or below it ("" or "everyone" = everyone).
    """
    principal = require(request, "add_sources")
    ctx = ctx_of(request)
    role_id: str | None = default_visibility(principal)
    if visibility is not None:
        chosen = visibility.strip()
        if chosen in ("", "everyone"):
            role_id = None
        else:
            role = ctx.store.get_role(chosen)
            if role is None:
                raise HTTPException(400, "no such role")
            if not principal.may_assign_role(role):
                raise HTTPException(
                    403, f"you cannot restrict a source to '{role['name']}': that tier is above yours"
                )
            role_id = role["id"]
    return {"owner_id": principal.user_id, "access_role_id": role_id}


@router.post("/sources/upload")
async def upload_form(request: Request, files: list[UploadFile] = File(...), visibility: str = Form(None)):
    ctx = ctx_of(request)
    try:
        access = new_source_access(request, visibility)
    except HTTPException as exc:
        return RedirectResponse(f"/?error={quote(str(exc.detail))}", status_code=303)
    if message := too_big(request, ctx):
        return RedirectResponse(f"/?error={quote(message)}", status_code=303)
    added = 0
    for upload in files:
        data = await upload.read()
        if not data or not upload.filename:
            continue
        try:
            pipeline.add_upload(ctx, upload.filename, data, **access)
            added += 1
        except ValueError as exc:
            return RedirectResponse(f"/?error={exc}", status_code=303)
    if added == 0:
        return RedirectResponse("/?error=No+files+were+uploaded", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/sources/text")
def text_form(request: Request, name: str = Form(""), text: str = Form(""), visibility: str = Form(None)):
    try:
        access = new_source_access(request, visibility)
    except HTTPException as exc:
        return RedirectResponse(f"/?error={quote(str(exc.detail))}", status_code=303)
    if not text.strip():
        return RedirectResponse("/?error=Paste+some+text+first", status_code=303)
    pipeline.add_text(ctx_of(request), name.strip() or "Pasted text", text, **access)
    return RedirectResponse("/", status_code=303)


@router.post("/sources/repo")
def repo_form(request: Request, url: str = Form(""), visibility: str = Form(None)):
    try:
        access = new_source_access(request, visibility)
        pipeline.add_repo(ctx_of(request), url.strip(), **access)
    except HTTPException as exc:
        return RedirectResponse(f"/?error={quote(str(exc.detail))}", status_code=303)
    except (RepoError, ValueError) as exc:
        return RedirectResponse(f"/?error={exc}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/sources/sample")
def sample_form(request: Request, visibility: str = Form(None)):
    try:
        access = new_source_access(request, visibility)
    except HTTPException as exc:
        return RedirectResponse(f"/?error={quote(str(exc.detail))}", status_code=303)
    pipeline.add_sample(ctx_of(request), **access)
    return RedirectResponse("/", status_code=303)


@router.post("/sources/{source_id}/access")
def access_form(request: Request, source_id: str, visibility: str = Form(""), back: str = Form("/")):
    """Change who may see a source (the Library and Source pages both post here)."""
    target = back if back.startswith("/") and not back.startswith("//") else "/"
    try:
        set_access(request, source_id, AccessBody(role_id=visibility or None))
    except HTTPException as exc:
        sep = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{sep}error={quote(str(exc.detail))}", status_code=303)
    return RedirectResponse(target, status_code=303)


# ------------------------------------------------------------------ JSON

api = APIRouter(prefix="/api/sources")


class TextBody(BaseModel):
    name: str = Field(default="Pasted text")
    text: str = Field(
        min_length=1, max_length=pipeline.DEFAULT_MAX_UPLOAD_BYTES
    )  # coarse; add_text does the byte check
    visibility: str | None = None  # a role id, "everyone", or omitted for the caller's own tier


class RepoBody(BaseModel):
    url: str = Field(min_length=1)
    visibility: str | None = None  # a role id, "everyone", or omitted for the caller's own tier


class AccessBody(BaseModel):
    role_id: str | None = None  # None / "everyone": open to every user


@api.get("")
def list_sources(request: Request) -> list[dict[str, Any]]:
    return ctx_of(request).store.list_sources(principal_of(request).access)


@api.post("/text")
def add_text(request: Request, body: TextBody, visibility: str | None = None):
    access = new_source_access(request, body.visibility if body.visibility is not None else visibility)
    try:
        return {"source_id": pipeline.add_text(ctx_of(request), body.name, body.text, **access)}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@api.post("/upload")
async def add_upload(request: Request, file: UploadFile = File(...), visibility: str = Form(None)):
    access = new_source_access(request, visibility)
    if message := too_big(request, ctx_of(request)):
        return JSONResponse({"error": message}, status_code=413)
    data = await file.read()
    try:
        return {"source_id": pipeline.add_upload(ctx_of(request), file.filename or "upload", data, **access)}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@api.post("/repo")
def add_repo(request: Request, body: RepoBody):
    access = new_source_access(request, body.visibility)
    try:
        return {"source_id": pipeline.add_repo(ctx_of(request), body.url, **access)}
    except (RepoError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@api.post("/sample")
def add_sample(request: Request, visibility: str | None = None):
    access = new_source_access(request, visibility)
    return {"source_id": pipeline.add_sample(ctx_of(request), **access)}


@api.post("/reindex-all")
def reindex_all(request: Request):
    """Re-index every source with the current embedding model (the fix for a changed HIPPO_EMBED_MODEL)."""
    require(request, "edit_graph")  # touches every source, including ones the caller may not see
    try:
        return {"started": pipeline.reindex_all(ctx_of(request))}
    except Busy as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


@api.get("/{source_id}")
def get_source(request: Request, source_id: str):
    return visible_source(request, source_id)


@api.put("/{source_id}/access")
def set_access(request: Request, source_id: str, body: AccessBody):
    """Change the lowest role that may see a source (None or 'everyone' opens it to all users)."""
    ctx = ctx_of(request)
    principal = principal_of(request)
    source = manageable_source(request, source_id)
    role_id = None if body.role_id in (None, "", "everyone") else body.role_id
    if role_id:
        role = ctx.store.get_role(role_id)
        if role is None:
            raise HTTPException(400, "no such role")
        if not principal.may_assign_role(role):
            raise HTTPException(
                403, f"you cannot restrict '{source['name']}' to '{role['name']}': that tier is above yours"
            )
    ctx.store.set_source_access(source_id, role_id)
    ctx.invalidate_scoped()
    return visible_source(request, source_id)


@api.delete("/{source_id}")
def delete_source(request: Request, source_id: str):
    ctx = ctx_of(request)
    manageable_source(request, source_id)
    try:
        pipeline.delete_source(ctx, source_id)
    except Busy as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    return {"deleted": source_id}


@api.post("/{source_id}/reindex")
def reindex(request: Request, source_id: str):
    ctx = ctx_of(request)
    manageable_source(request, source_id)
    try:
        return {"started": pipeline.reindex(ctx, source_id)}
    except Busy as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
