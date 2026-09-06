"""
HTML pages.

Each function renders one page (or a partial that HTMX swaps into a page).
Pages never contain business logic: they call the same functions the API and
the MCP server call, then hand the result to a template.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ... import ask as ask_service
from ...ollama import OllamaError
from ...status import system_status
from ...store.base import DEFAULT_SETTINGS, validate_settings
from ..render import ctx_of, render

router = APIRouter()

SETTING_HELP = {
    "linking_top_k": "How many facts we pull for a question, and how many entities we start the graph search from.",
    "passage_node_weight": "How much a passage's own similarity to the question counts as a starting point (0.05 = a whisper).",
    "damping": "How far activation travels along the graph: 0.5 stays close to the seeds; 0.9 wanders far.",
    "node_specificity": "Entities mentioned in many passages get a smaller starting weight (like IDF for search).",
    "synonymy_threshold": "Embedding similarity above which two entity names get linked as synonyms (used while indexing).",
    "retrieval_top_k": "How many passages a search returns and keeps in the trace.",
    "qa_top_k": "How many passages the model reads before answering.",
}


# --------------------------------------------------------------- partials


@router.get("/partials/status")
def status_partial(request: Request):
    return render(request, "partials/status.html")


# -------------------------------------------------------------------- ask


@router.get("/ask")
def ask_page(request: Request, q: str = ""):
    return render(request, "ask.html", nav="ask", question=q)


@router.post("/ask")
def ask_submit(request: Request, question: str = Form("")):
    ctx = ctx_of(request)
    question = question.strip()
    if not question:
        return render(request, "partials/answer.html", error="Type a question first.")
    try:
        trace, answer = ask_service.ask(ctx, question)
    except OllamaError as exc:
        return render(request, "partials/answer.html", error=str(exc))
    graph = ctx.graph()
    passages = []
    for ranked in trace.passages[: int(trace.settings.get("qa_top_k", 5))]:
        passage = graph.passage_by_id(ranked.passage_id)
        passages.append({"ranked": ranked, "text": passage.text if passage else ranked.preview})
    return render(
        request, "partials/answer.html", question=question, trace=trace, answer=answer, passages=passages
    )


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
        saved=bool(saved),
        status=system_status(ctx, fresh=True),
    )


@router.post("/settings")
async def settings_submit(request: Request):
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
            saved=False,
            error=str(exc),
            status=system_status(ctx, fresh=True),
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
