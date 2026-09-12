"""Standalone rendering borrows one snapshot for status until HTML exists."""

from types import SimpleNamespace

import pytest

from hippo.access import Principal
from hippo.knowledge.access import AuthorizationChanged
from hippo.web import render
from tests.unit.test_query_session import observed  # noqa: F401


@pytest.mark.parametrize("outcome", ["success", "error", "revoke"])
def test_standalone_render_releases_one_status_graph(observed, monkeypatch, outcome):  # noqa: F811
    ctx, acquired, released = observed
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)), state=SimpleNamespace(principal=Principal.open())
    )

    def materialize(request, template, context, **kwargs):
        assert not released
        assert len(acquired) == 1
        assert context["status"]["stats"]["passages"] == 1
        if outcome == "error":
            raise RuntimeError("template failed")
        if outcome == "revoke":
            ctx.store._bump_authorization_epoch()
        return context

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    if outcome == "success":
        render.render(request, "unused.html")
    else:
        with pytest.raises(AuthorizationChanged if outcome == "revoke" else RuntimeError):
            render.render(request, "unused.html")
    assert released == acquired
