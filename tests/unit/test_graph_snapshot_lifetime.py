"""Graph detail and inventory own a live snapshot through materialization."""

import pytest
from fastapi import HTTPException

from hippo.knowledge.access import AuthorizationChanged
from hippo.web.routes import graph
from tests.unit.test_lookup_snapshot_lifetime import live_refs, managed  # noqa: F401
from tests.unit.test_query_snapshots import build


@pytest.mark.parametrize("surface", ["full", "node", "unknown"])
def test_graph_lookups_release_selected_generation(ctx, managed, surface):  # noqa: F811
    _, span, acquired, request = managed
    if surface == "full":
        assert graph.full_graph(request)["passages"] == 1
    elif surface == "node":
        assert graph.node_details(request, span.id)["text"] == span.text
    else:
        with pytest.raises(HTTPException):
            graph.node_details(request, "missing")
    assert len(acquired) == 1
    assert not live_refs(ctx)


@pytest.mark.parametrize("surface", ["full", "node"])
@pytest.mark.parametrize("action", ["publish", "revoke"])
def test_graph_dto_keeps_generation_and_withholds_revoked_output(ctx, managed, monkeypatch, surface, action):  # noqa: F811
    generation, span, acquired, request = managed
    original = graph.label_at
    changed = False

    def label(index, vertex):
        nonlocal changed
        assert acquired == [index]
        assert live_refs(ctx)
        if not changed:
            changed = True
            if action == "publish":
                build(ctx, parent=generation, text="new revision")
                assert ctx.store.collect_generation(generation.id).blocked_reason == "snapshot_reference"
            else:
                ctx.store._bump_authorization_epoch()
        return original(index, vertex)

    monkeypatch.setattr(graph, "label_at", label)

    def call():
        return graph.full_graph(request) if surface == "full" else graph.node_details(request, span.id)

    if action == "revoke":
        with pytest.raises(AuthorizationChanged):
            call()
    else:
        payload = call()
        assert payload["passages"] == 1 if surface == "full" else payload["text"] == span.text
    assert changed
    assert len(acquired) == 1
    assert not live_refs(ctx)
