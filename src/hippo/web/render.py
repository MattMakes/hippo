"""
Rendering HTML pages.

`render(request, "page.html", nav="ask", **context)` fills a Jinja2 template
and always adds the things the base layout needs: system status for the
header, the active nav item, and the config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from ..context import AppContext
from ..status import system_status

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _pct(done: Any, total: Any) -> int:
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
    if value is None or value == "":
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


def render(request: Request, template: str, nav: str = "", status_code: int = 200, **context: Any):
    ctx = ctx_of(request)
    context.update(nav=nav, status=system_status(ctx), config=ctx.config)
    return templates.TemplateResponse(request, template, context, status_code=status_code)
