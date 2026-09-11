"""
Rendering HTML pages.

`render(request, "page.html", nav="ask", **context)` fills a Jinja2 template
and always adds the things the base layout needs: system status for the
header, the active nav item, and the config.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import Undefined

from ..access import Access
from ..context import AppContext
from ..knowledge.query_access import QuerySession, query_access
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
    # Every signed-in page includes scoped status, even when its own content has
    # no evidence callback (for example Settings or the status partial).
    if session is not None:
        status_check = session.validate
        status_check()
    else:
        status_check = (
            query_access(ctx, access)[2] if store_online and access.audience_kind != "preview" else None
        )
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
