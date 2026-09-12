"""
HTML pages.

Each function renders one page (or a partial that HTMX swaps into a page).
Pages never contain business logic: they call the same functions the API and
the MCP server call, then hand the result to a template.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ... import ask as ask_service
from ...knowledge.access import AuthorizationChanged
from ...knowledge.answer_evidence import answer_sources
from ...knowledge.query_access import QuerySession, query_session
from ...status import system_status
from ...store.base import DEFAULT_SETTINGS, SETTING_RULES, validate_settings
from ..adhoc import remember_adhoc
from ..auth import principal_of, require
from ..render import ctx_of, render, retrieval_failure

log = logging.getLogger(__name__)
router = APIRouter()

SETTING_HELP = {
    "linking_top_k": "How many facts we pull for a question, and how many entities we start the graph search from.",
    "passage_node_weight": "How much a passage's own similarity to the question counts as a starting point (0.05 = a whisper).",
    "damping": "How far activation travels along the graph: 0.5 stays close to the seeds; 0.9 wanders far.",
    "node_specificity": "Entities mentioned in many passages get a smaller starting weight (like IDF for search).",
    "synonymy_threshold": "Embedding similarity above which two entity names get linked as synonyms (used while indexing).",
    "retrieval_top_k": "How many passages a search returns and keeps in the trace.",
    "qa_top_k": "How many passages the model reads before answering.",
    # The code graph. Without a line here a setting renders a blank hint and nobody notices.
    "code_seed_weight": (
        "How strongly a symbol the question names starts the graph search; 0 ignores names entirely."
    ),
    "code_structural_scale": (
        "Multiplier on every weight that exists only because code was indexed; 0 keeps code out of the "
        "graph search altogether. Capped at 3.0 so a code relation can never outrank three facts."
    ),
    "code_theta": "Minimum confidence a relation needs to be shown in a path or the answer block.",
    "code_dense_seeds": (
        "How many of the question's closest passages also start the search from the symbols they "
        "define. Counted over all passages, not just code ones."
    ),
    "code_triples_chars": "Size cap on the Code graph block the model reads.",
    "code_community_boost": "Score bonus for passages in the same subsystem as a symbol the question found.",
    "code_select": "A second pass where the model keeps, drops or expands passages, when the question named a symbol.",
    "code_expand_max": "How many neighbours one “expand” may fetch, confidence 0.75 and above.",
    "code_history_depth": "First-parent commits read per repo source; 0 disables history.",
    "code_git_timeout_s": "Per-commit `git show` budget; a timeout skips that commit.",
    "code_history_total_s": "Whole-pass budget for reading history; stops early and keeps what it read.",
}


# --------------------------------------------------------------- partials


@router.get("/partials/status")
def status_partial(request: Request):
    return render(request, "partials/status.html")


# -------------------------------------------------------------------- ask


def scope_note(ctx, principal, *, session: QuerySession | None = None) -> dict:
    """Describe only the evidence inventory this caller may search."""
    stats = system_status(ctx, access=principal.access, session=session)["stats"]
    visible = stats.get("sources", 0)
    return {
        "visible": visible,
        "total": visible,
        "passages": stats.get("passages", 0),
        "role": principal.role_name,
        "open": principal.is_open,
    }


@router.get("/ask")
def ask_page(request: Request, q: str = ""):
    ctx = ctx_of(request)
    principal = principal_of(request)
    manager = query_session(ctx, principal.access) if ctx.store.ping() else nullcontext(None)
    with manager as session:
        return render(
            request,
            "ask.html",
            nav="ask",
            question=q,
            scope=scope_note(ctx, principal, session=session),
            authorization_check=session.validate if session is not None else None,
            session=session,
        )


def failure_text(exc: BaseException) -> str:
    """What the answer fragment may say about a failure: one closed code, never its words.

    The same helper the JSON routes and the app's handlers use, rendered as the one sentence
    a reader can act on plus the code they can quote. The exception itself goes to the local
    log at DEBUG, where a public-level capture cannot pick up the model's reply body or an
    absolute path.
    """
    failure = retrieval_failure(exc)
    log.warning("ask failed: %s", type(exc).__name__)
    log.debug("ask failure detail", exc_info=True)
    return f"{failure.message} [{failure.code}]"


@router.post("/ask")
def ask_submit(request: Request, question: str = Form("")):
    ctx = ctx_of(request)
    principal = principal_of(request)
    question = question.strip()
    if not question:
        return render(request, "partials/answer.html", error="Type a question first.")
    try:
        with query_session(ctx, principal.access) as session:
            try:
                trace, answer = ask_service.ask(ctx, question, access=principal.access, session=session)
            except AuthorizationChanged:
                raise
            except Exception as exc:  # noqa: BLE001 - HTMX needs a visible error fragment
                return render(request, "partials/answer.html", error=failure_text(exc), session=session)
            passages = answer_sources(session.graph, trace, answer)
            session.validate()
            # Keep the trace so "Analyze this question" explains this answer without asking again.
            trace_key = remember_adhoc(
                trace, {"answer": answer.answer, "thought": answer.thought}, owner=principal.user_id
            )
            return render(
                request,
                "partials/answer.html",
                question=question,
                trace=trace,
                answer=answer,
                passages=passages,
                trace_key=trace_key,
                authorization_check=session.validate,
                session=session,
            )
    except AuthorizationChanged:
        raise
    except Exception as exc:  # noqa: BLE001 - includes failures acquiring the query session
        return render(request, "partials/answer.html", error=failure_text(exc))


# --------------------------------------------------------------- settings


@router.get("/settings")
def settings_page(request: Request, saved: int = 0):
    ctx = ctx_of(request)
    return render(
        request,
        "settings.html",
        nav="settings",
        settings=ctx.store.get_settings() if ctx.store.ping() else DEFAULT_SETTINGS,
        help=SETTING_HELP,
        rules=SETTING_RULES,
        saved=bool(saved),
        status=system_status(ctx, fresh=True, access=principal_of(request).access),
        can_edit=principal_of(request).can("edit_graph"),
    )


@router.post("/settings")
async def settings_submit(request: Request):
    require(request, "edit_graph")  # settings change everyone's answers
    ctx = ctx_of(request)
    form = await request.form()
    try:
        ctx.store.update_settings(parse_settings_form(dict(form)))
    except ValueError as exc:
        return render(
            request,
            "settings.html",
            nav="settings",
            settings=ctx.store.get_settings(),
            help=SETTING_HELP,
            rules=SETTING_RULES,
            saved=False,
            error=str(exc),
            status=system_status(ctx, fresh=True, access=principal_of(request).access),
            can_edit=True,
            status_code=400,
        )
    return RedirectResponse("/settings?saved=1", status_code=303)


def parse_settings_form(form: dict) -> dict:
    """
    Turn form strings into the right types (checkboxes are absent when unticked); ignore anything
    that is not a known setting. Ranges are checked by validate_settings in the store.
    """
    changes: dict = {}
    for key, default in DEFAULT_SETTINGS.items():
        if isinstance(default, bool):
            changes[key] = key in form and str(form[key]).lower() in ("on", "true", "1", "yes")
        elif key in form and str(form[key]).strip() != "":
            changes[key] = validate_settings({key: form[key]})[key]
    return changes
