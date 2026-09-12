"""Graph-only lookup responses hold and release one generation without model calls."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from mcp.server.mcpserver.exceptions import ToolError

from hippo import mcp_server
from hippo.access import Principal
from hippo.knowledge.access import AuthorizationChanged
from hippo.web.routes import api, code
from tests.unit.test_query_snapshots import build


@pytest.fixture
def managed(ctx, monkeypatch):
    generation, span = build(ctx)
    ctx.store.ensure_roles()
    ctx.store.set_meta("reviewed_mapping_authorities", ["local"])
    uid = ctx.store.create_user("lookup-reader", "secret1", "individual")
    principal = Principal.for_user(ctx.store.get_user(uid), ctx.store.get_role("individual"))
    # create_user now maps the principal into the local workspace itself.
    acquired = []
    original = ctx.graph_for

    def acquire(*args, **kwargs):
        graph = original(*args, **kwargs)
        acquired.append(graph)
        return graph

    monkeypatch.setattr(ctx, "graph_for", acquire)

    def no_model(*args, **kwargs):
        pytest.fail("Graph-only lookup must not call a model")

    monkeypatch.setattr(ctx.ollama, "embed_one", no_model)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)), state=SimpleNamespace(principal=principal)
    )
    return generation, span, acquired, request


def live_refs(ctx):
    return [r for r in ctx.store._knowledge_rows("SnapshotReference") if r.released_at is None]


def invoke(surface, ctx, request, span):
    calls = {
        "symbols": lambda: code.symbols(request, "missing"),
        "path": lambda: code.code_path(request, "missing", "other"),
        "blast": lambda: code.blast(request, "missing"),
        "exception": lambda: code.raises(request, "missing", "Error"),
        "history": lambda: code.commits(request, "missing"),
        "mcp_path": lambda: mcp_server.explain_path_tool(
            ctx, "missing", "other", principal=request.state.principal
        ),
        "mcp_blast": lambda: mcp_server.blast_radius_tool(ctx, "missing", principal=request.state.principal),
        "mcp_exception": lambda: mcp_server.exception_path_tool(
            ctx, "missing", "Error", principal=request.state.principal
        ),
        "mcp_history": lambda: mcp_server.history_tool(ctx, "missing", principal=request.state.principal),
        "entities": lambda: api.entities(request, "missing"),
        "neighborhood": lambda: api.neighborhood(request, span.id),
        "unknown_node": lambda: api.neighborhood(request, "missing"),
    }
    return calls[surface]()


@pytest.mark.parametrize(
    "surface",
    [
        "symbols",
        "path",
        "blast",
        "exception",
        "history",
        "mcp_path",
        "mcp_blast",
        "mcp_exception",
        "mcp_history",
        "entities",
        "neighborhood",
        "unknown_node",
    ],
)
def test_lookups_release_real_snapshot_on_success_or_error(ctx, managed, surface):
    _, span, acquired, request = managed
    if surface in ("symbols", "entities", "neighborhood"):
        invoke(surface, ctx, request, span)
    else:
        with pytest.raises(ToolError if surface.startswith("mcp") else HTTPException):
            invoke(surface, ctx, request, span)
    assert len(acquired) == 1
    assert not live_refs(ctx)


@pytest.mark.parametrize("surface", ["path", "mcp_path"])
@pytest.mark.parametrize("action", ["publish", "revoke", "error"])
def test_code_builder_holds_snapshot_and_captured_settings(ctx, managed, monkeypatch, surface, action):
    generation, span, acquired, request = managed
    expected_theta = ctx.store.get_settings()["code_theta"]
    original = ctx.graph_for

    def acquire(*args, **kwargs):
        graph = original(*args, **kwargs)
        ctx.store.update_settings({"code_theta": 0.9 if expected_theta != 0.9 else 0.1})
        return graph

    monkeypatch.setattr(ctx, "graph_for", acquire)

    def payload(graph, a, b, *, theta):
        assert acquired == [graph]
        assert theta == expected_theta
        assert live_refs(ctx)
        if action == "publish":
            build(ctx, parent=generation, text="replacement")
            assert ctx.store.collect_generation(generation.id).blocked_reason == "snapshot_reference"
            return {"text": graph.passage_by_id(span.id).text}
        if action == "revoke":
            ctx.store._bump_authorization_epoch()
            return {"text": "must be withheld"}
        raise RuntimeError("construction failed")

    monkeypatch.setattr(mcp_server if surface.startswith("mcp") else code, "path_payload", payload)
    if action == "publish":
        assert invoke(surface, ctx, request, span)["text"] == span.text
    else:
        with pytest.raises(AuthorizationChanged if action == "revoke" else RuntimeError):
            invoke(surface, ctx, request, span)
    assert len(acquired) == 1
    assert not live_refs(ctx)
