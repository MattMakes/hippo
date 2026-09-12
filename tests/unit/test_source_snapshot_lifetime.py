"""Source presentation retains one generation for inventory, details and HTML."""

import pytest
from fastapi import HTTPException

from hippo.knowledge.access import AuthorizationChanged
from hippo.web import render
from hippo.web.routes import sources
from tests.unit.test_lookup_snapshot_lifetime import live_refs, managed  # noqa: F401
from tests.unit.test_query_snapshots import build


def invoke(surface, request, source_id):
    if surface == "library":
        return sources.library(request)
    if surface == "partial":
        return sources.sources_partial(request)
    if surface == "source":
        return sources.source_page(request, source_id)
    if surface == "status":
        return sources.source_status_partial(request, source_id)
    if surface == "list":
        return sources.list_sources(request)
    if surface == "get":
        return sources.get_source(request, source_id)
    return sources.source_page(request, "missing")


@pytest.mark.parametrize("surface", ["library", "partial", "source", "status", "list", "get", "missing"])
def test_source_surfaces_release_one_snapshot(ctx, managed, monkeypatch, surface):  # noqa: F811
    generation, _, acquired, request = managed

    def materialize(request, template, context, **kwargs):
        assert live_refs(ctx)
        assert len(acquired) == 1
        return context

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    if surface == "missing":
        with pytest.raises(HTTPException):
            invoke(surface, request, generation.source_id)
    else:
        invoke(surface, request, generation.source_id)
    assert len(acquired) == 1
    assert not live_refs(ctx)


@pytest.mark.parametrize("action", ["publish", "revoke", "error"])
def test_source_page_keeps_body_and_header_under_one_snapshot(ctx, managed, monkeypatch, action):  # noqa: F811
    generation, span, acquired, request = managed

    def materialize(request, template, context, **kwargs):
        assert len(acquired) == 1
        assert live_refs(ctx)
        if action == "publish":
            build(ctx, parent=generation, text="second revision")
            assert ctx.store.collect_generation(generation.id).blocked_reason == "snapshot_reference"
            assert context["passages"][0]["text"] == span.text
            assert context["status"]["stats"]["passages"] == 1
        elif action == "revoke":
            ctx.store._bump_authorization_epoch()
        else:
            raise RuntimeError("failed template")
        return context

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    if action == "publish":
        sources.source_page(request, generation.source_id)
    else:
        with pytest.raises(AuthorizationChanged if action == "revoke" else RuntimeError):
            sources.source_page(request, generation.source_id)
    assert not live_refs(ctx)
