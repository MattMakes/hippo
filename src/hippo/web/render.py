"""
Rendering HTML pages, and the one JSON body every failing surface answers with.

`render(request, "page.html", nav="ask", **context)` fills a Jinja2 template
and always adds the things the base layout needs: system status for the
header, the active nav item, and the config.

`retrieval_failure`, `public_failure_response` and `public_failure_page` live
here rather than in a route module because every transport in `hippo.web`
returns the same body for the same condition, and one definition is the only way
that stays true. JSON surfaces answer the body; page surfaces answer the same
sentence and the same status as a page.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Undefined

from ..access import Access
from ..context import AppContext
from ..knowledge.public_errors import OPERATION_FAILED, PublicFailure, public_failure
from ..knowledge.query_access import QuerySession, query_session
from ..ollama import OllamaError
from ..status import system_status

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# htmx treats 286 as "swap this, then stop polling". Partials answer with it when nothing is in
# flight, so idle pages stop replacing their tables under the user's cursor every few seconds.
STOP_POLLING = 286

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _pct(done: Any, total: Any) -> int:
    """Percentage for progress bars: {{ done | pct(total) }} -> 0..100 (0 when total is missing)."""
    try:
        done, total = float(done or 0), float(total or 0)
    except (TypeError, ValueError):
        return 0
    return int(round(100 * done / total)) if total > 0 else 0


def _short(text: Any, length: int = 80) -> str:
    text = str(text or "")
    return text if len(text) <= length else text[: length - 1] + "…"


def _fmt(value: Any, digits: int = 3) -> str:
    """Numbers as short strings for tables: 0.1234 -> '0.123', None -> '–'."""
    # A run that is still going has an empty summary, so run.summary.accuracy is Jinja's
    # Undefined: show a dash instead of crashing on float(Undefined).
    if value is None or value == "" or isinstance(value, Undefined):
        return "–"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


templates.env.filters["pct"] = _pct
templates.env.filters["short"] = _short
templates.env.filters["fmt"] = _fmt


def ctx_of(request: Request) -> AppContext:
    return request.app.state.ctx


def retrieval_failure(exc: BaseException) -> PublicFailure:
    """The public failure for anything raised while acquiring, dispatching or reading a session.

    This is the caller rule `knowledge/public_errors.py` documents, spelled once for
    the whole web layer: the closed table when it knows the exception, and
    `operation_failed` when it does not. A route applies it only to the exceptions it
    has already decided are activation failures rather than the caller's own mistake,
    so `GraphIndex.canonical_selected_generations`' bare `ValueError` cannot reach a
    client as a 400 that blames the request, and no exception's own words are read.
    """
    return public_failure(exc) or OPERATION_FAILED


def caller_error(exc: BaseException) -> bool:
    """True only for the exact `ValueError` the closed input validators raise.

    Every managed, retrieval and ingest exception is a `ValueError` *subclass* --
    `ReadError` names the file it was reading, `ProjectionError` describes a selection,
    `ManagedDispatchError` a lane -- so an `except ValueError` that answers
    `HTTPException(4xx, str(exc))` prints any of them at the caller. The exact-type test
    is what keeps them out of a 4xx `detail` and hands them to `retrieval_failure`
    instead. `mcp_server.tool_failure` applies the same rule, so a client moving between
    HTTP and MCP is told the same thing by the same rule.
    """
    return type(exc) is ValueError


def wants_html(request: Request) -> bool:
    """Whether this caller asked for a page rather than a body it can branch on.

    One definition, used by the 403 handler and the public-failure handler, because a
    surface that negotiates and a surface that does not is exactly how a browser ends up
    reading a JSON blob where the page was. Every `/api` path answers JSON whatever the
    browser's `Accept` header says: the pages' own JavaScript sends the browser's header.
    """
    return "text/html" in request.headers.get("accept", "") and not request.url.path.startswith("/api")


def coded_response(message: str, code: str, status_code: int) -> JSONResponse:
    """A bounded message a route owns, in the one body shape every web surface answers.

    `public_failure_response` below is for the closed table's own sentences. This is for
    the routes the plan lets keep their existing text -- the closed input validators and
    the indexing preconditions -- so that adding `code` costs them nothing. It matters
    because `remote.py` branches on `code` first: an uncoded body falls through to the
    generic `operation_failed` sentence and its own actionable text is discarded.
    """
    return JSONResponse({"error": message, "code": code}, status_code=status_code)


def public_failure_response(failure: PublicFailure) -> JSONResponse:
    """One JSON body for every public failure: the `error` clients already read, plus `code`.

    `error` keeps the shape existing clients depend on and carries the mapper's own
    bounded sentence; `code` is the stable value a client branches on. Neither is ever
    derived from the raised exception's text.
    """
    return coded_response(failure.message, failure.code, failure.http_status)


def public_failure_page(request: Request, failure: PublicFailure, template: str, nav: str = ""):
    """The same failure as a page: the mapper's sentence, at the mapper's status.

    A page cannot answer `{error, code}` to a browser, so it says the one bounded
    sentence and nothing else - never the exception's own words, and never at 200, which
    would tell a client, a cache and a crawler that the question was answered.

    It renders directly rather than through `render`, because the failure being reported
    is exactly what `render` would meet again the moment it opened a session of its own.
    For the same reason the header falls back to health alone: the preview audience is
    what this module already uses for "no corpus to prove" (`render` below), and is the
    one branch of `system_status` that reports an inventory without loading a view.
    """
    ctx = ctx_of(request)
    context = {
        "me": getattr(request.state, "principal", None),
        "nav": nav,
        "error": failure.message,
        "failure_code": failure.code,
        "status": system_status(ctx, access=Access(audience_kind="preview")),
        "config": ctx.config,
    }
    return templates.TemplateResponse(request, template, context, status_code=failure.http_status)


def render(
    request: Request,
    template: str,
    nav: str = "",
    status_code: int = 200,
    authorization_check: Callable[[], None] | None = None,
    session: QuerySession | None = None,
    **context: Any,
):
    if authorization_check is not None:
        authorization_check()
    ctx = ctx_of(request)
    # `me` is who is signed in (hippo/access.py); the header shows it and templates gate buttons on it.
    context.setdefault("me", getattr(request.state, "principal", None))
    principal = context["me"]
    access = principal.access if principal is not None else Access(audience_kind="preview")
    store_online = ctx.store.ping()
    # A standalone page owns its status snapshot; callers rendering evidence
    # pass their session so status and page content share the same generation.
    if session is None and store_online and access.audience_kind != "preview":
        try:
            with query_session(ctx, access) as owned:
                return render(
                    request,
                    template,
                    nav=nav,
                    status_code=status_code,
                    authorization_check=authorization_check,
                    session=owned,
                    **context,
                )
        except (ValueError, OllamaError, httpx.TransportError) as exc:
            # The page's own view could not be composed - `canonical_selected_generations`'
            # bare `ValueError` above all - and a page that owns its snapshot has nobody
            # else to map it. `AuthorizationChanged` is a `RuntimeError` and is deliberately
            # not caught, so a revocation still answers with the permission response.
            return public_failure_page(request, retrieval_failure(exc), template, nav=nav)
    status_check = session.validate if session is not None else None
    if status_check is not None:
        status_check()
    context.update(
        nav=nav,
        status=system_status(ctx, access=access, fresh=not store_online, session=session),
        config=ctx.config,
    )
    response = templates.TemplateResponse(request, template, context, status_code=status_code)
    if authorization_check is not None:
        authorization_check()
    if status_check is not None:
        status_check()
    return response
