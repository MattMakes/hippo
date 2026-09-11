"""Shared page status requires a proof through the end of template rendering."""

import pytest
from fastapi.testclient import TestClient

from hippo.hipporag.indexer import Chunk, index_source
from hippo.web.app import create_app
from hippo.web.render import templates


@pytest.mark.parametrize("url", ["/partials/status", "/settings"])
def test_render_without_content_callback_rechecks_status_permissions(ctx, monkeypatch, url):
    ctx.store.ensure_roles()
    user = ctx.store.create_user("status-reader", "secret1", "individual")
    source = ctx.store.create_source("text", "Private later")
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Title", "Mira designed Orion.")])
    original = templates.TemplateResponse

    def revoke_after_render(*args, **kwargs):
        response = original(*args, **kwargs)
        ctx.store.set_source_access(source, "arch-admin")
        return response

    monkeypatch.setattr(templates, "TemplateResponse", revoke_after_render)
    with TestClient(create_app(ctx), base_url="http://localhost", raise_server_exceptions=False) as client:
        client.headers["Authorization"] = "Bearer " + ctx.store.get_user(user)["token"]
        response = client.get(url)
    assert response.status_code == 409
    assert response.json() == {"error": "Permissions changed; repeat the query"}


def test_unavailable_store_login_can_render_without_a_graph(ctx, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An unavailable login page tried to authorize graph evidence")

    with TestClient(create_app(ctx), base_url="http://localhost", raise_server_exceptions=False) as client:
        monkeypatch.setattr(ctx.store, "ping", lambda: False)
        monkeypatch.setattr(ctx, "graph_for", forbidden)
        response = client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text


def test_unavailable_store_error_page_does_not_reuse_cached_online_inventory(ctx, monkeypatch):
    from starlette.requests import Request

    from hippo.access import Principal
    from hippo.status import system_status
    from hippo.web.render import render

    ctx.store.ensure_roles()
    user = ctx.store.create_user("offline-reader", "secret1", "individual")
    principal = Principal.for_user(ctx.store.get_user(user), ctx.store.get_role("individual"))
    assert system_status(ctx, access=principal.access)["store"] is True
    app = create_app(ctx)
    request = Request(
        {
            "type": "http",
            "app": app,
            "router": app.router,
            "headers": [],
            "path": "/login",
            "method": "GET",
            "scheme": "http",
            "server": ("localhost", 80),
            "query_string": b"",
            "state": {"principal": principal},
        }
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline rendering reused an online evidence view")

    monkeypatch.setattr(ctx.store, "ping", lambda: False)
    monkeypatch.setattr(ctx, "graph_for", forbidden)
    response = render(request, "login.html", error="Store unavailable", open_mode=False, next="/")
    assert response.status_code == 200
    assert b"Store unavailable" in response.body
