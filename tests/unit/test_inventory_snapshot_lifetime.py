"""Inventory DTOs and graph-page status close their selected source snapshots."""

import pytest

from hippo import mcp_server
from hippo.access import Principal
from hippo.knowledge.access import AuthorizationChanged
from hippo.status import system_status
from hippo.web import render
from hippo.web.routes import graph
from tests.unit.test_lookup_snapshot_lifetime import live_refs, managed  # noqa: F401


@pytest.mark.parametrize("surface", ["status", "whoami", "sources", "graph_page"])
def test_inventory_owns_one_snapshot_until_response(ctx, managed, monkeypatch, surface):  # noqa: F811
    _, _, acquired, request = managed
    principal = request.state.principal

    def materialize(request, template, context, **kwargs):
        assert len(acquired) == 1
        assert live_refs(ctx)
        assert context["status"]["stats"]["passages"] == 1
        return context

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    if surface == "status":
        assert system_status(ctx, access=principal.access)["stats"]["passages"] == 1
    elif surface == "whoami":
        assert mcp_server.whoami_tool(ctx, principal)["sources_visible"] == 1
    elif surface == "sources":
        assert mcp_server.sources_tool(ctx, principal)[0]["passages"] == 1
    else:
        graph.graph_page(request)
    assert len(acquired) == 1
    assert not live_refs(ctx)


@pytest.mark.parametrize("surface", ["library", "graph"])
def test_reconnected_page_does_not_leave_an_unowned_inventory_graph(ctx, managed, monkeypatch, surface):  # noqa: F811
    from hippo.web.routes import sources

    _, _, acquired, request = managed
    calls = 0

    def ping():
        nonlocal calls
        calls += 1
        return calls > 1

    monkeypatch.setattr(ctx.store, "ping", ping)
    monkeypatch.setattr(
        render.templates, "TemplateResponse", lambda request, template, context, **kw: context
    )
    result = sources.library(request) if surface == "library" else graph.graph_page(request)
    assert result["sources"] == []  # The inventory was unavailable at acquisition.
    assert len(acquired) == 1  # Render owns the reconnected header view.
    assert not live_refs(ctx)


@pytest.mark.parametrize("outcome", ["success", "error", "revoke"])
def test_preview_graph_and_actor_header_keep_distinct_audiences_until_render(
    ctx,
    managed,  # noqa: F811
    monkeypatch,
    outcome,
):
    _, _, acquired, request = managed
    user_id = request.state.principal.user_id
    ctx.store.update_user(user_id, role_id="arch-admin")
    request.state.principal = Principal.for_user(
        ctx.store.get_user(user_id), ctx.store.get_role("arch-admin")
    )

    def materialize(request, template, context, **kwargs):
        assert len(acquired) == 2
        preview_graph, actor_graph = acquired
        assert preview_graph is not actor_graph
        assert preview_graph.passages == []
        assert len(actor_graph.passages) == 1
        assert context["sources"] == []
        assert context["principal"].role_id == "individual"
        assert context["me"].role_id == "arch-admin"
        assert context["status"]["stats"]["passages"] == 1
        assert live_refs(ctx)
        if outcome == "error":
            raise RuntimeError("preview template failed")
        if outcome == "revoke":
            ctx.store._bump_authorization_epoch()
        return context

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    if outcome == "success":
        graph.graph_page(request, as_role="individual")
    else:
        expected = AuthorizationChanged if outcome == "revoke" else RuntimeError
        with pytest.raises(expected):
            graph.graph_page(request, as_role="individual")
    assert len(acquired) == 2
    assert not live_refs(ctx)
