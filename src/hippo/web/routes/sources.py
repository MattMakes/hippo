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

from contextlib import nullcontext
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ...access import Principal, roles_at_or_below
from ...hipporag import paths
from ...ingest import pipeline
from ...ingest.pipeline import Busy
from ...ingest.repos import RepoError
from ...knowledge.eval_access import EvalAccess
from ...knowledge.query_access import QuerySession, query_session
from ...status import source_view
from ..auth import principal_of, require
from ..render import STOP_POLLING, ctx_of, render
from . import graph as graph_routes

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
    with query_session(ctx, principal.access) if ctx.store.ping() else nullcontext(None) as session:
        view = source_view(ctx, principal.access, session=session) if session is not None else None
        sources = view.sources if view else []
        return render(
            request,
            "library.html",
            session=session,
            nav="library",
            sources=with_manage_flags(sources, principal),
            error=error,
            busy_ids=busy_source_ids(ctx, view),
            principal=principal,
            can_add=principal.can("add_sources"),
            visibility_choices=visibility_choices(ctx, principal),
            default_visibility=default_visibility(principal),
            total_sources=len(sources),
            authorization_check=view.validate if view else None,
        )


@router.get("/partials/sources")
def sources_partial(request: Request):
    """The sources table, polled by the Library page while something is being indexed."""
    ctx = ctx_of(request)
    principal = principal_of(request)
    with query_session(ctx, principal.access) as session:
        view = source_view(ctx, principal.access, session=session)
        sources = view.sources
        busy = any(s["status"] in BUSY_STATUSES for s in sources)
        return render(
            request,
            "partials/source_rows.html",
            session=session,
            sources=with_manage_flags(sources, principal),
            busy_ids=busy_source_ids(ctx, view),
            principal=principal,
            visibility_choices=visibility_choices(ctx, principal),
            status_code=200 if busy else STOP_POLLING,
            authorization_check=view.validate,
        )


def busy_source_ids(ctx, view) -> set[str]:
    """Only legacy source jobs have an audience-safe source-level status."""
    ids = {key[6:] for key in ctx.jobs.running_keys() if key.startswith("index:")}
    if view is None:
        return set()
    view.validate()
    return ids & view.legacy_ids


def visible_source(
    request: Request, source_id: str, *, session: QuerySession | None = None
) -> dict[str, Any]:
    """The source, if the caller may see it; a hidden source looks exactly like a missing one."""
    if session is None:
        with query_session(ctx_of(request), principal_of(request).access) as owned:
            return visible_source(request, source_id, session=owned)
    view = source_view(ctx_of(request), principal_of(request).access, session=session)
    source = next((row for row in view.sources if row["id"] == source_id), None)
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
    with query_session(ctx, principal.access) as session:
        view = source_view(ctx, principal.access, session=session)
        source = next((row for row in view.sources if row["id"] == source_id), None)
        if source is None:
            raise HTTPException(404, "no such source")
        page = max(1, page)
        if source.get("managed"):
            passages = [
                {
                    "id": passage.id,
                    "title": passage.title,
                    "text": passage.text,
                    "ordinal": passage.ordinal,
                    "triples": [],
                    "entities": [],
                    "extraction_error": "",
                }
                for passage in view.graph.passages
                if passage.source_id == source_id
            ][(page - 1) * PASSAGES_PER_PAGE : page * PASSAGES_PER_PAGE]
        else:
            passages = ctx.store.passages_for_source(
                source_id,
                limit=PASSAGES_PER_PAGE,
                offset=(page - 1) * PASSAGES_PER_PAGE,
                access=principal.access,
            )
        question_sets = (
            [
                qs
                for qs in EvalAccess(ctx, principal.access, session=session).list_question_sets()
                if qs.get("source_id") == source_id
            ]
            if principal.can("run_evals")
            else []
        )
        pages = max(1, -(-source["passages"] // PASSAGES_PER_PAGE))
        code_details = code_details_for(ctx, principal, passages, session=session)
        busy = source_id in busy_source_ids(ctx, view)
        view.validate()
        return render(
            request,
            "source.html",
            session=session,
            nav="library",
            source=with_manage_flags([source], principal)[0],
            passages=passages,
            code_details=code_details,
            question_sets=question_sets,
            page=page,
            pages=pages,
            busy=busy,
            principal=principal,
            visibility_choices=visibility_choices(ctx, principal),
            can_evals=principal.can("run_evals"),
            authorization_check=view.validate,
        )


CODE_COMMITS_SHOWN = 5


def code_details_for(
    ctx, principal: Principal, passages: list[dict[str, Any]], *, session: QuerySession | None = None
) -> dict[str, Any]:
    """
    Per passage id: the symbols written down in it and their corner of the code graph.

    A prose source has none of this and gets an empty dict, which the template checks. The
    relations are rendered by `paths.render_triples`, so the page and the block the model reads
    say the same thing in the same S2.15 grammar rather than in two hand-written formats.

    `is_commit` and `touched` are for the one passage kind that is not code: a commit's own
    passage, which the template introduces by what it changed rather than by what it "defines".
    """
    if session is None:
        with query_session(ctx, principal.access) as owned:
            return code_details_for(ctx, principal, passages, session=owned)
    session.validate()
    index = session.graph
    if not index.code_nodes:
        return {}
    theta = float(session.settings["code_theta"])
    out: dict[str, Any] = {}
    for passage in passages:
        vertex = index.idx_of.get(passage["id"])
        if vertex is None:  # still indexing, or hidden from this caller
            continue
        symbols = sorted(index.symbols_defined_in(vertex), key=lambda v: paths.display_at(index, v))
        if not symbols:
            continue
        edges = [e for v in symbols for e in index.out_edges(v) if e.dst != vertex]
        commits: list = []
        for v in symbols:
            for commit in paths.history(index, v, limit=CODE_COMMITS_SHOWN):
                if commit.id not in {c.id for c in commits}:
                    commits.append(commit)
        # `paths.history` is newest-first per symbol, but a passage can define several symbols and
        # the loop above concatenates their histories in display-name order. Sort the merged list
        # before the cut, or the newest commit of the second symbol lands under the oldest of the
        # first - and, once the cut bites, drops off the page entirely. `ordinal` 0 is newest.
        commits.sort(key=lambda c: (c.ordinal, c.sha))
        nodes = [index.code_node_at(v) for v in symbols]
        out[passage["id"]] = {
            # A commit is DEFINED_IN its own passage too, so a commit passage arrives here with the
            # commit as its only "symbol". Saying it *defines* a sha is nonsense; what a reader
            # wants is what the commit touched, which is exactly its MODIFIES targets.
            "is_commit": all(n is not None and n.kind == "commit" for n in nodes),
            "touched": sorted({paths.display_at(index, e.dst) for e in edges if e.kind == "MODIFIES"}),
            "symbols": [
                {
                    "id": index.node_ids[v],
                    "name": paths.display_at(index, v),
                    "node": index.code_node_at(v),
                }
                for v in symbols
            ],
            "relations": paths.render_triples(
                paths.triple_rows(index, graph_routes.sorted_edges(index, edges))
            ),
            "tests": paths.test_rows(index, paths.tests_for(index, symbols, theta=theta)),
            "commits": paths.history_rows(commits[:CODE_COMMITS_SHOWN]),
        }
    return out


@router.get("/partials/sources/{source_id}/status")
def source_status_partial(request: Request, source_id: str):
    ctx = ctx_of(request)
    principal = principal_of(request)
    with query_session(ctx, principal.access) as session:
        view = source_view(ctx, principal.access, session=session)
        source = next((row for row in view.sources if row["id"] == source_id), None)
        if source is None:
            raise HTTPException(404, "no such source")
        busy = source["status"] in BUSY_STATUSES
        return render(
            request,
            "partials/source_status.html",
            session=session,
            source=source,
            status_code=200 if busy else STOP_POLLING,
            authorization_check=view.validate,
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
    with query_session(ctx_of(request), principal_of(request).access) as session:
        return source_view(ctx_of(request), principal_of(request).access, session=session).sources


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
    principal = require(request, "edit_graph")  # retains the existing global operation permission
    ctx = ctx_of(request)
    view = source_view(ctx, principal.access)
    try:
        pipeline.reindex_all(ctx)
    except Busy as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    view.validate()
    source_view(ctx, principal.access).validate()
    # The pipeline reports only a global count, without per-source outcomes.
    # Acknowledge acceptance without claiming which visible jobs started.
    return {"accepted": True}


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
