"""Account and role inventory responses release their selected evidence view."""

import pytest

from hippo.access import Principal
from hippo.knowledge.access import AuthorizationChanged
from hippo.web import auth, render
from hippo.web.routes import users
from tests.unit.test_lookup_snapshot_lifetime import live_refs, managed  # noqa: F401


@pytest.fixture
def admin(ctx, managed):  # noqa: F811
    _, _, acquired, request = managed
    uid = request.state.principal.user_id
    ctx.store.update_user(uid, role_id="arch-admin")
    request.state.principal = Principal.for_user(ctx.store.get_user(uid), ctx.store.get_role("arch-admin"))
    request.base_url = "http://localhost/"
    return acquired, request


@pytest.mark.parametrize(
    "surface", ["account", "me", "users_page", "users", "roles", "ladder", "patch_user", "patch_role"]
)
def test_account_inventory_has_one_owned_snapshot(ctx, admin, monkeypatch, surface):
    acquired, request = admin
    if surface == "patch_user":
        other = ctx.store.create_user("another-reader", "secret1", "individual")

    def materialize(request, template, context, **kwargs):
        assert len(acquired) == 1
        assert live_refs(ctx)
        return context

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    if surface == "account":
        auth.account_page(request)
    elif surface == "me":
        auth.me(request)
    elif surface == "users_page":
        users.users_page(request)
    elif surface == "users":
        users.list_users(request)
    elif surface == "roles":
        users.list_roles(request)
    elif surface == "ladder":
        users.ladder(ctx, request.state.principal)
    elif surface == "patch_user":
        users.patch_user(request, other, users.UserPatch(display_name="Changed"))
    else:
        users.patch_role(request, "individual", users.RolePatch(description="Changed"))
    assert len(acquired) == 1
    assert not live_refs(ctx)


@pytest.mark.parametrize("surface", ["account", "users_page"])
@pytest.mark.parametrize("failure", ["error", "revoke"])
def test_account_template_error_releases_snapshot_and_rechecks_access(
    ctx, admin, monkeypatch, surface, failure
):
    acquired, request = admin

    def materialize(request, template, context, **kwargs):
        assert live_refs(ctx)
        if failure == "revoke":
            ctx.store.update_user(request.state.principal.user_id, disabled=True)
            return context
        raise RuntimeError("template failed")

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    with pytest.raises(AuthorizationChanged if failure == "revoke" else RuntimeError):
        (auth.account_page if surface == "account" else users.users_page)(request)
    assert len(acquired) == 1
    assert not live_refs(ctx)
