"""
Two checks that keep other websites out of hippo.

hippo has no login: whoever can reach the port can read and change the memory.
That is fine on your own machine, but a web page you happen to visit runs in
the same browser and could try to talk to http://localhost:8000 too. Two tricks
make that possible, and one small middleware blocks both:

1. **Cross-site requests (CSRF).** attacker.example can make your browser POST
   a form to /sources/text and plant text in the memory. Browsers label such
   requests: `Sec-Fetch-Site: cross-site`, and an `Origin` (or `Referer`) header
   naming the page that sent it. For every request that changes something
   (POST/PUT/PATCH/DELETE) we refuse `cross-site` and refuse an Origin/Referer
   whose host is not one of ours. Tools like curl, Claude Code and the MCP
   clients send none of these headers and are not affected.

2. **DNS rebinding.** attacker.example first resolves to the attacker's server,
   then (after a short TTL) to 127.0.0.1, so the page can read
   http://attacker.example:8000/api/... as if it were its own site. The browser
   still sends `Host: attacker.example:8000`, so we refuse any Host that is not
   in the allowed list (localhost, 127.0.0.1, [::1], plus HIPPO_ALLOWED_HOSTS).

`host_allowed` is the one rule both checks use; `mcp_server.mount` builds the
MCP library's own settings from the same list so the two never disagree.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ANY_HOST = "*"


def host_name(value: str | None) -> str | None:
    """
    The bare host from a Host header or a URL: 'localhost:8000' -> 'localhost',
    '[::1]:8000' -> '::1', 'https://evil.example/x' -> 'evil.example'. None when unreadable.
    """
    if not value:
        return None
    # urlsplit needs '//' to treat the value as an authority; a Host header has no scheme.
    target = value if "://" in value else "//" + value
    try:
        return urlsplit(target).hostname or None
    except ValueError:  # e.g. an unbalanced '[' in an IPv6 literal
        return None


def host_allowed(value: str | None, allowed_hosts: Iterable[str]) -> bool:
    """True when the Host header (or URL) names one of the allowed hosts. Ports are ignored."""
    allowed = list(allowed_hosts)
    if ANY_HOST in allowed:
        return True
    name = host_name(value)
    if name is None:
        return False
    # host_name() strips the brackets from IPv6 entries, so normalise the list the same way.
    return name in {host_name(item) for item in allowed}


class HostAndOriginGuard:
    """ASGI middleware: refuse foreign Host headers, and foreign origins on state-changing requests."""

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self.allowed_hosts = tuple(allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        problem = self.reject_reason(scope["method"], headers)
        if problem is not None:
            status, message = problem
            await PlainTextResponse(message, status_code=status)(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def reject_reason(self, method: str, headers: Headers) -> tuple[int, str] | None:
        """(status, message) when the request must be refused, else None. Pure, so it is easy to test."""
        host = headers.get("host")
        if not host_allowed(host, self.allowed_hosts):
            return 400, (
                f"Invalid Host header {host!r}. hippo answers only to {', '.join(self.allowed_hosts)}; "
                "set HIPPO_ALLOWED_HOSTS to add a name or IP address."
            )
        if method.upper() in SAFE_METHODS:
            return None
        if headers.get("sec-fetch-site", "").lower() == "cross-site":
            return 403, "Refused: this request was sent by another website."
        # Origin is what browsers send with forms and fetch(); Referer is the older equivalent.
        # 'null' (a sandboxed or file:// page) has no host, so host_allowed refuses it too.
        origin = headers.get("origin") or headers.get("referer")
        if origin and not host_allowed(origin, self.allowed_hosts):
            return 403, f"Refused: {host_name(origin) or origin!r} is not allowed to change this memory."
        return None
