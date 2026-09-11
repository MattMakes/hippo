"""
Users & roles: the page where the access ladder is managed and explained.

The page has three parts, top to bottom:

1. **The ladder.** Every role, top first, with its rank, the number of users
   and sources at that tier, and what a user at that tier can see (every tier
   at or below). Open mode gets a callout explaining that creating the first
   user closes the door.
2. **Users.** Create one (username, password, role), change role, disable,
   reset password, rotate the token, delete.
3. **Roles.** Rename, move up or down (rank), edit the capabilities, add or
   delete roles.

Who may do what (see hippo/access.py): `manage_users` for part 2 and
`manage_roles` for part 3, and only on users/roles that rank strictly below
the caller, except for callers at the very top of the ladder, who may also
manage their peers (so an arch admin can add another arch admin).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ...access import CAPABILITIES, Principal, top_role
from ...status import source_view
from ..auth import principal_of, public_user, require, set_session_cookie
from ..render import ctx_of, render

router = APIRouter()
api = APIRouter(prefix="/api")


# ---------------------------------------------------------------- rules


def may_touch_rank(principal: Principal, rank: int, roles: list[dict[str, Any]]) -> bool:
    """Below me, or at my level when nobody is above me (the top of the ladder manages its peers)."""
    if principal.is_open:
        return True
    if principal.rank > int(rank):
        return True
    return principal.rank == int(rank) and principal.rank >= top_role(roles)["rank"]


def assignable_roles(principal: Principal, roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in roles if may_touch_rank(principal, r["rank"], roles)]


def check_role_assignable(principal: Principal, role_id: str, roles: list[dict[str, Any]]) -> dict[str, Any]:
    role = next((r for r in roles if r["id"] == role_id), None)
    if role is None:
        raise HTTPException(400, "no such role")
    if not may_touch_rank(principal, role["rank"], roles):
        raise HTTPException(403, f"you may not give someone the role '{role['name']}': it is not below yours")
    return role


def check_user_manageable(principal: Principal, user: dict[str, Any], roles: list[dict[str, Any]]) -> None:
    if principal.user_id == user["id"]:
        raise HTTPException(400, "use the Account page to change your own account")
    if not may_touch_rank(principal, user.get("rank", 0), roles):
        raise HTTPException(403, f"'{user['username']}' ({user.get('role_name')}) does not rank below you")


def _role_rows(ctx, sources) -> list[dict[str, Any]]:
    return [
        {**role, "sources": sum(source.get("access_role_id") == role["id"] for source in sources)}
        for role in ctx.store.list_roles()
    ]


def _user_row(user, sources) -> dict[str, Any]:
    row = public_user(user) or {}
    row["sources"] = sum(source.get("owner_id") == row.get("id") for source in sources)
    return row


def ladder(ctx, principal: Principal, *, view=None) -> list[dict[str, Any]]:
    """Tier estimates intersect the caller's inventory; managed ACLs cannot be inferred from a tier."""
    view = view or source_view(ctx, principal.access)
    roles = _role_rows(ctx, view.sources)
    rows = []
    for role in roles:
        visible = [
            s for s in view.sources if not s.get("managed") and int(s.get("min_rank") or 0) <= role["rank"]
        ]
        rows.append(
            {
                **role,
                "sees_sources": len(visible),
                "sees_passages": sum(int(s.get("passages") or 0) for s in visible),
                "sees_tiers": [r["name"] for r in roles if r["rank"] <= role["rank"]],
                "editable": may_touch_rank(principal, role["rank"], roles),
                "is_mine": role["id"] == principal.role_id,
            }
        )
    view.validate()
    return rows


# ---------------------------------------------------------------- pages


@router.get("/users")
def users_page(request: Request, error: str = "", saved: str = "", show_token: str = ""):
    principal = principal_of(request)
    if not (principal.can("manage_users") or principal.can("manage_roles")):
        raise HTTPException(403, "your role may neither manage users nor roles")
    ctx = ctx_of(request)
    view = source_view(ctx, principal.access)
    roles = _role_rows(ctx, view.sources)
    users = []
    for user in ctx.store.list_users():
        row = _user_row(user, view.sources)
        row["manageable"] = principal.user_id != user["id"] and may_touch_rank(principal, user["rank"], roles)
        row["is_me"] = principal.user_id == user["id"]
        if show_token == user["id"] and row["manageable"]:
            row["token"] = user.get("token")
        users.append(row)
    total_sources = len(view.sources)
    open_sources = sum(not s.get("managed") and not s.get("access_role_id") for s in view.sources)
    tier_rows = ladder(ctx, principal, view=view)
    view.validate()
    return render(
        request,
        "users.html",
        nav="users",
        ladder=tier_rows,
        users=users,
        roles=roles,
        assignable=assignable_roles(principal, roles),
        capabilities=CAPABILITIES,
        open_mode=principal.is_open,
        can_users=principal.can("manage_users"),
        can_roles=principal.can("manage_roles"),
        total_sources=total_sources,
        open_sources=open_sources,
        error=error,
        saved=saved,
        authorization_check=view.validate,
    )


def _back(message: str = "", saved: str = "", **extra: str) -> RedirectResponse:
    parts = []
    if message:
        parts.append("error=" + quote(message))
    if saved:
        parts.append("saved=" + quote(saved))
    for key, value in extra.items():
        parts.append(f"{key}={quote(value)}")
    return RedirectResponse("/users" + ("?" + "&".join(parts) if parts else ""), status_code=303)


@router.post("/users")
async def create_user_form(request: Request):
    form = dict(await request.form())
    try:
        user, first = _create_user(
            request,
            UserBody(
                username=str(form.get("username", "")),
                password=str(form.get("password", "")),
                role_id=str(form.get("role_id", "")),
                display_name=str(form.get("display_name", "")),
            ),
        )
    except HTTPException as exc:
        return _back(str(exc.detail))
    response = _back(saved=f"Created {user['username']}", show_token=user["id"])
    if first:
        set_session_cookie(response, ctx_of(request), user["id"])
    return response


@router.post("/users/{user_id}")
async def update_user_form(request: Request, user_id: str):
    form = dict(await request.form())
    action = str(form.get("action", "save"))
    try:
        if action == "delete":
            delete_user(request, user_id)
            return _back(saved="User removed")
        if action == "token":
            rotate_token(request, user_id)
            return _back(saved="New token issued", show_token=user_id)
        changes = UserPatch(
            role_id=str(form["role_id"]) if form.get("role_id") else None,
            display_name=str(form["display_name"]) if "display_name" in form else None,
            disabled=str(form.get("disabled", "")).lower() in ("on", "true", "1")
            if action == "save"
            else None,
            password=str(form["password"]) if form.get("password") else None,
        )
        patch_user(request, user_id, changes)
    except HTTPException as exc:
        return _back(str(exc.detail))
    return _back(saved="Saved")


@router.post("/roles")
async def create_role_form(request: Request):
    form = await request.form()
    try:
        create_role(
            request,
            RoleBody(
                name=str(form.get("name", "")),
                rank=int(str(form.get("rank", "0")) or 0),
                description=str(form.get("description", "")),
                capabilities=[c for c in CAPABILITIES if form.get(f"cap_{c}")],
            ),
        )
    except (HTTPException, ValueError) as exc:
        return _back(getattr(exc, "detail", str(exc)))
    return _back(saved="Role added")


@router.post("/roles/{role_id}")
async def update_role_form(request: Request, role_id: str):
    form = await request.form()
    try:
        if str(form.get("action", "save")) == "delete":
            delete_role(request, role_id)
            return _back(saved="Role deleted")
        patch_role(
            request,
            role_id,
            RolePatch(
                name=str(form.get("name", "")) or None,
                rank=int(str(form.get("rank", "")) or 0) if form.get("rank", "") != "" else None,
                description=str(form.get("description", "")),
                capabilities=[c for c in CAPABILITIES if form.get(f"cap_{c}")],
            ),
        )
    except (HTTPException, ValueError) as exc:
        return _back(getattr(exc, "detail", str(exc)))
    return _back(saved="Role saved")


# ------------------------------------------------------------------ JSON


class UserBody(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    role_id: str = ""
    display_name: str = ""


class UserPatch(BaseModel):
    role_id: str | None = None
    display_name: str | None = None
    disabled: bool | None = None
    password: str | None = None


class RoleBody(BaseModel):
    name: str = Field(min_length=1)
    rank: int = 0
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)


class RolePatch(BaseModel):
    name: str | None = None
    rank: int | None = None
    description: str | None = None
    capabilities: list[str] | None = None


@api.get("/users")
def list_users(request: Request):
    principal = require(request, "manage_users")
    ctx = ctx_of(request)
    view = source_view(ctx, principal.access)
    rows = [_user_row(user, view.sources) for user in ctx.store.list_users()]
    view.validate()
    return rows


@api.get("/roles")
def list_roles(request: Request):
    principal = principal_of(request)
    ctx = ctx_of(request)
    view = source_view(ctx, principal.access)
    rows = _role_rows(ctx, view.sources)
    view.validate()
    return rows


@api.post("/users")
def create_user(request: Request, body: UserBody):
    """
    Add a user. The very first user closes open mode, must take the top role, and the browser
    that created it is signed in as it (otherwise creating it would lock that person out).
    """
    user, first = _create_user(request, body)
    response = JSONResponse({"user": public_user(user), "signed_in": first, "token": user.get("token")})
    if first:
        set_session_cookie(response, ctx_of(request), user["id"])
    return response


def _create_user(request: Request, body: UserBody) -> tuple[dict[str, Any], bool]:
    ctx = ctx_of(request)
    principal = principal_of(request)
    roles = ctx.store.list_roles()
    first = ctx.store.count_users() == 0
    if first:
        role = top_role(roles)
        if body.role_id and body.role_id != role["id"]:
            raise HTTPException(
                400, f"the first user must be a {role['name']}, or nobody could manage anything"
            )
    else:
        require(request, "manage_users")
        role = check_role_assignable(principal, body.role_id, roles)
    try:
        user_id = ctx.store.create_user(body.username, body.password, role["id"], body.display_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ctx.store.get_user(user_id) or {}, first


@api.patch("/users/{user_id}")
def patch_user(request: Request, user_id: str, body: UserPatch) -> dict[str, Any]:
    principal = require(request, "manage_users")
    ctx = ctx_of(request)
    user = ctx.store.get_user(user_id)
    if user is None:
        raise HTTPException(404, "no such user")
    roles = ctx.store.list_roles()
    check_user_manageable(principal, user, roles)
    changes: dict[str, Any] = {}
    if body.role_id is not None and body.role_id != user.get("role_id"):
        check_role_assignable(principal, body.role_id, roles)
        changes["role_id"] = body.role_id
    if body.display_name is not None:
        changes["display_name"] = body.display_name
    if body.disabled is not None:
        changes["disabled"] = body.disabled
    if body.password:
        changes["password"] = body.password
    try:
        updated = ctx.store.update_user(user_id, **changes) if changes else user
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    view = source_view(ctx, principal.access)
    row = _user_row(updated, view.sources)
    view.validate()
    return row


@api.post("/users/{user_id}/token")
def rotate_token(request: Request, user_id: str) -> dict[str, Any]:
    principal = require(request, "manage_users")
    ctx = ctx_of(request)
    user = ctx.store.get_user(user_id)
    if user is None:
        raise HTTPException(404, "no such user")
    check_user_manageable(principal, user, ctx.store.list_roles())
    return {"token": ctx.store.rotate_token(user_id)}


@api.delete("/users/{user_id}")
def delete_user(request: Request, user_id: str) -> dict[str, Any]:
    principal = require(request, "manage_users")
    ctx = ctx_of(request)
    user = ctx.store.get_user(user_id)
    if user is None:
        raise HTTPException(404, "no such user")
    check_user_manageable(principal, user, ctx.store.list_roles())
    ctx.store.delete_user(user_id)
    return {"deleted": user_id}


@api.post("/roles")
def create_role(request: Request, body: RoleBody) -> dict[str, Any]:
    principal = require(request, "manage_roles")
    ctx = ctx_of(request)
    if not may_touch_rank(principal, body.rank, ctx.store.list_roles()):
        raise HTTPException(403, "a new role cannot rank above your own")
    try:
        role_id = ctx.store.create_role(body.name, body.rank, body.description, body.capabilities)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ctx.store.get_role(role_id) or {}


@api.patch("/roles/{role_id}")
def patch_role(request: Request, role_id: str, body: RolePatch) -> dict[str, Any]:
    principal = require(request, "manage_roles")
    ctx = ctx_of(request)
    roles = ctx.store.list_roles()
    role = next((r for r in roles if r["id"] == role_id), None)
    if role is None:
        raise HTTPException(404, "no such role")
    if not may_touch_rank(principal, role["rank"], roles):
        raise HTTPException(403, f"'{role['name']}' does not rank below you")
    changes: dict[str, Any] = {}
    if body.name is not None:
        changes["name"] = body.name
    if body.rank is not None and body.rank != role["rank"]:
        if not may_touch_rank(principal, body.rank, roles):
            raise HTTPException(403, "you cannot move a role above your own")
        changes["rank"] = body.rank
    if body.description is not None:
        changes["description"] = body.description
    if body.capabilities is not None:
        if role["id"] == principal.role_id and "manage_roles" not in body.capabilities:
            raise HTTPException(400, "you cannot take 'manage_roles' away from your own role")
        changes["capabilities"] = body.capabilities
    try:
        if changes:
            ctx.store.update_role(role_id, **changes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    view = source_view(ctx, principal.access)
    updated = next(row for row in _role_rows(ctx, view.sources) if row["id"] == role_id)
    view.validate()
    return updated


@api.delete("/roles/{role_id}")
def delete_role(request: Request, role_id: str) -> dict[str, Any]:
    principal = require(request, "manage_roles")
    ctx = ctx_of(request)
    roles = ctx.store.list_roles()
    role = next((r for r in roles if r["id"] == role_id), None)
    if role is None:
        raise HTTPException(404, "no such role")
    if role["id"] == principal.role_id:
        raise HTTPException(400, "you cannot delete your own role")
    if not may_touch_rank(principal, role["rank"], roles):
        raise HTTPException(403, f"'{role['name']}' does not rank below you")
    try:
        ctx.store.delete_role(role_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": role_id}
