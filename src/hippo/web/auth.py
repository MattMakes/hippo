"""
Who is asking? Sessions, sign-in, and the gate in front of every request.

hippo starts *open*: until the first user exists, anyone who reaches the port
acts as the top role (that is how it always worked). Creating a user closes
the door: from then on every page, API call and MCP call must carry either a
session cookie (the sign-in form) or `Authorization: Bearer <token>` (scripts,
Claude Code and other MCP clients; every user has a token on their Account page).

The pieces:

* `AuthGate` (ASGI middleware): works out the Principal for the request and
  stores it on `request.state.principal`. When users exist and nobody is signed
  in it answers 401 for /api and /mcp, a redirect to /login for pages, and an
  htmx redirect for polled partials (so a poll never swaps a login form into a
  status strip).
* `principal_of(request)` / `require(request, capability)`: what routes call.
* A signed cookie, `hippo_session`: "<user id>.<expiry>.<hmac>" with a secret
  kept on the Settings node, so a restart does not sign everyone out. No new
  dependency: hmac + secrets from the standard library.
* The /login, /logout and /account pages.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from ..access import CAPABILITIES, Principal, top_role
from ..context import AppContext
from ..knowledge.build_authority import BuildActor
from ..knowledge.query_access import query_session
from ..status import source_view
from .render import ctx_of, render

log = logging.getLogger(__name__)

SESSION_COOKIE = "hippo_session"
SESSION_SECONDS = 30 * 24 * 3600
SECRET_META_KEY = "session_secret"

# Paths that need no principal at all (the sign-in form itself and the files it loads).
PUBLIC_PREFIXES = ("/login", "/static/")

_secret_cache: dict[int, bytes] = {}  # id(ctx) -> secret, so one Cypher read per process


# ------------------------------------------------------------ the cookie


def session_secret(ctx: AppContext) -> bytes:
    key = id(ctx)
    cached = _secret_cache.get(key)
    if cached:
        return cached
    stored = ctx.store.get_meta(SECRET_META_KEY)
    if not stored:
        stored = secrets.token_hex(32)
        ctx.store.set_meta(SECRET_META_KEY, stored)
    secret = str(stored).encode()
    _secret_cache[key] = secret
    return secret


def sign_session(secret: bytes, user_id: str, now: float | None = None) -> str:
    expires = int((now or time.time()) + SESSION_SECONDS)
    payload = f"{user_id}.{expires}"
    return f"{payload}.{hmac.new(secret, payload.encode(), 'sha256').hexdigest()}"


def read_session(secret: bytes, cookie: str | None, now: float | None = None) -> str | None:
    """The user id inside a valid, unexpired cookie, else None."""
    if not cookie:
        return None
    try:
        user_id, expires, signature = cookie.rsplit(".", 2)
        expires_at = int(expires)
    except ValueError:
        return None
    expected = hmac.new(secret, f"{user_id}.{expires}".encode(), "sha256").hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    if expires_at < (now or time.time()):
        return None
    return user_id


def set_session_cookie(response: Response, ctx: AppContext, user_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(session_secret(ctx), user_id),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# --------------------------------------------------------- the principal


class StoreDown(Exception):
    """Neo4j cannot be reached and users are known to exist: nobody can be identified, so refuse."""


_users_seen: set[int] = set()  # id(ctx) of every context that has ever reported a user


def _gated(ctx: AppContext) -> bool | None:
    """
    True when users exist, False in open mode, None when Neo4j is down and we never saw a user.
    Once a context has seen a user it stays gated even while Neo4j is unreachable: a hiccup must
    fail closed, not hand every request the top role.
    """
    if not ctx.store.ping():
        return True if id(ctx) in _users_seen else None
    if ctx.store.count_users() == 0:
        return False
    _users_seen.add(id(ctx))
    return True


def resolve_principal(ctx: AppContext, headers: Headers, *, require_online: bool = False) -> Principal | None:
    """
    The Principal for a request, or None when users exist and the request carries no valid
    credential. Open mode (no users) always yields the open principal. Raises StoreDown when
    Neo4j is unreachable after users were seen.
    """
    gated = _gated(ctx)
    if gated is None:
        if require_online:
            raise StoreDown()
        # Nothing can be read while Neo4j is down and no user was ever seen; the pages only show
        # status. Treat as open so the header and the Settings page still say what is wrong.
        return Principal.open()
    if gated is False:
        return Principal.open(top_role(ctx.store.list_roles()))
    if not ctx.store.ping():
        raise StoreDown()
    user = None
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        user = ctx.store.get_user_by_token(auth[7:].strip())
    if user is None:
        cookies = _cookies(headers.get("cookie", ""))
        user_id = read_session(session_secret(ctx), cookies.get(SESSION_COOKIE))
        if user_id:
            user = ctx.store.get_user(user_id)
    return _principal_for(ctx, user)


def principal_from_bearer(
    ctx: AppContext, token: str | None, *, require_online: bool = False
) -> Principal | None:
    """The Principal behind a bearer token (MCP, scripts). Same open-mode and outage rules as above."""
    gated = _gated(ctx)
    if gated is None:
        if require_online:
            raise StoreDown()
        return Principal.open()
    if gated is False:
        return Principal.open(top_role(ctx.store.list_roles()))
    if not ctx.store.ping():
        raise StoreDown()
    return _principal_for(ctx, ctx.store.get_user_by_token(token or ""))


def _principal_for(ctx: AppContext, user: dict[str, Any] | None) -> Principal | None:
    if user is None or user.get("disabled"):
        return None
    role = ctx.store.get_role(user.get("role_id"))
    if role is None:
        log.warning("user %s has no role; treating as the lowest tier", user["username"])
        role = {"id": "none", "name": "no role", "rank": 0, "capabilities": []}
    return Principal.for_user(user, role)


def _cookies(header: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in header.split(";"):
        if "=" in part:
            name, value = part.split("=", 1)
            out[name.strip()] = value.strip()
    return out


def principal_of(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        # Only reachable when the gate is not installed (some unit tests build routers alone).
        principal = resolve_principal(ctx_of(request), request.headers) or Principal.open()
        request.state.principal = principal
    return principal


def require(request: Request, capability: str) -> Principal:
    """The principal, if it has `capability`; otherwise 403 with a sentence that names what is missing."""
    principal = principal_of(request)
    if not principal.can(capability):
        raise HTTPException(
            403,
            f"Your role ({principal.role_name}) may not do this: it needs '{capability}' "
            f"({CAPABILITIES[capability].rstrip('.')}). Ask an admin.",
        )
    return principal


def build_actor_of(principal: Principal) -> BuildActor | None:
    """
    The caller's own build actor, or None for an identity that may not build managed evidence.

    Open mode and role previews are not readers: a new source of theirs keeps the legacy
    lane (the dispatch table's "no actor" column), and `plan_dispatch` refuses them before
    it touches an existing managed one. `BuildActor.trusted_local()` is for explicit
    internal calls; web code must never manufacture it as an authentication fallback, so it
    is not reachable from here.
    """
    try:
        return BuildActor.reader(principal)
    except ValueError:
        return None


def require_capability(capability: str):
    """A FastAPI dependency: `APIRouter(dependencies=[Depends(require_capability('run_evals'))])`."""

    def check(request: Request) -> Principal:
        return require(request, capability)

    return check


# ------------------------------------------------------------- the gate


class AuthGate:
    """ASGI middleware: attach the principal, or turn strangers away when users exist."""

    def __init__(self, app: ASGIApp, ctx: AppContext) -> None:
        self.app = app
        self.ctx = ctx

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path.startswith(PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        try:
            principal = resolve_principal(self.ctx, headers)
        except StoreDown:
            await PlainTextResponse("hippo cannot reach Neo4j, so nobody can be signed in right now.", 503)(
                scope, receive, send
            )
            return
        except Exception as exc:  # noqa: BLE001 - a broken store must not take the whole site down
            log.warning("could not resolve the user: %s", exc)
            principal = None
        if principal is None:
            await self.refuse(scope, receive, send, path, headers)
            return
        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)

    @staticmethod
    async def refuse(scope: Scope, receive: Receive, send: Send, path: str, headers: Headers) -> None:
        if path.startswith(("/api", "/mcp")):
            response: Response = JSONResponse(
                {"error": "sign in required: send 'Authorization: Bearer <your token>' (see /account)"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        elif headers.get("hx-request"):
            response = Response(status_code=401, headers={"HX-Redirect": "/login"})
        else:
            query = scope.get("query_string", b"").decode()
            target = path + (f"?{query}" if query else "")
            response = RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
        await response(scope, receive, send)


# ----------------------------------------------------------------- pages

router = APIRouter()


def safe_next(value: str) -> str:
    """Only send people back to a path on this site (never to another host)."""
    return value if value.startswith("/") and not value.startswith("//") else "/"


@router.get("/login")
def login_page(request: Request, next: str = "/", error: str = ""):
    ctx = ctx_of(request)
    if ctx.store.ping() and ctx.store.count_users() == 0:
        # Open mode: there is nothing to sign in to. Say so instead of showing a form that cannot work.
        return render(request, "login.html", nav="", open_mode=True, next=safe_next(next))
    return render(request, "login.html", nav="", open_mode=False, next=safe_next(next), error=error)


@router.post("/login")
def login_submit(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("/")):
    ctx = ctx_of(request)
    user = ctx.store.check_password(username, password) if ctx.store.ping() else None
    if user is None:
        return render(
            request,
            "login.html",
            nav="",
            open_mode=False,
            next=safe_next(next),
            error="That username and password do not match (or the account is disabled).",
            status_code=401,
        )
    response = RedirectResponse(safe_next(next), status_code=303)
    set_session_cookie(response, ctx, user["id"])
    return response


@router.post("/logout")
def logout(request: Request):
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("/account")
def account_page(request: Request, saved: str = "", error: str = ""):
    principal = principal_of(request)
    ctx = ctx_of(request)
    with query_session(ctx, principal.access) as session:
        view = source_view(ctx, principal.access, session=session)
        user = ctx.store.get_user(principal.user_id) if principal.user_id else None
        return render(
            request,
            "account.html",
            session=session,
            nav="account",
            user=public_user(user, sources=view.sources) if user else None,
            token=(user or {}).get("token"),
            role=principal.role,
            capabilities=CAPABILITIES,
            saved=saved,
            error=error,
            mcp_url=str(request.base_url).rstrip("/") + "/mcp",
            authorization_check=view.validate,
        )


@router.post("/account/password")
def change_password(request: Request, current: str = Form(""), new: str = Form(""), again: str = Form("")):
    principal = principal_of(request)
    ctx = ctx_of(request)
    if principal.is_open or not principal.user:
        return RedirectResponse(
            "/account?error=" + quote("No account: hippo is in open mode."), status_code=303
        )
    if ctx.store.check_password(principal.user["username"], current) is None:
        return RedirectResponse("/account?error=" + quote("The current password is wrong."), status_code=303)
    if new != again:
        return RedirectResponse("/account?error=" + quote("The two new passwords differ."), status_code=303)
    try:
        ctx.store.update_user(principal.user_id, password=new)
    except ValueError as exc:
        return RedirectResponse("/account?error=" + quote(str(exc)), status_code=303)
    return RedirectResponse("/account?saved=password", status_code=303)


@router.post("/account/token")
def rotate_own_token(request: Request):
    principal = principal_of(request)
    if principal.is_open or not principal.user_id:
        return RedirectResponse(
            "/account?error=" + quote("No account: hippo is in open mode."), status_code=303
        )
    ctx_of(request).store.rotate_token(principal.user_id)
    return RedirectResponse("/account?saved=token", status_code=303)


@router.get("/api/me")
def me(request: Request) -> dict[str, Any]:
    """Who am I, as the API sees it: role, rank, capabilities, and whether hippo is still open."""
    principal = principal_of(request)
    with query_session(ctx_of(request), principal.access) as session:
        view = source_view(ctx_of(request), principal.access, session=session)
        result = {
            "open_mode": principal.is_open,
            "user": public_user(principal.user, sources=view.sources) if principal.user else None,
            "role": {k: principal.role.get(k) for k in ("id", "name", "rank", "capabilities")},
            "capabilities": sorted(c for c in CAPABILITIES if principal.can(c)),
        }
        view.validate()
        return result


def public_user(
    user: dict[str, Any] | None, *, sources: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """Remove secrets and raw inventory; ownership counts require authorized source DTOs."""
    if user is None:
        return None
    row = {k: v for k, v in user.items() if k not in ("password_hash", "token", "sources")}
    if sources is not None:
        row["sources"] = sum(source.get("owner_id") == user["id"] for source in sources)
    return row


__all__ = [
    "AuthGate",
    "StoreDown",
    "SESSION_COOKIE",
    "build_actor_of",
    "principal_from_bearer",
    "principal_of",
    "public_user",
    "read_session",
    "require",
    "require_capability",
    "resolve_principal",
    "router",
    "set_session_cookie",
    "sign_session",
]
