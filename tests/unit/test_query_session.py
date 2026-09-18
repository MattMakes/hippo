"""One pinned graph survives model work and rendering, with deterministic release."""

import json
from types import SimpleNamespace

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from hippo import ask, cli, mcp_server
from hippo.access import Principal
from hippo.hipporag.indexer import Chunk, index_source
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.public_errors import OPERATION_FAILED
from hippo.knowledge.replay import view_fingerprint
from hippo.mcp_server import DENIED, DENIED_CODE
from hippo.web.routes import api

QUESTION = "Who designed the Orion arm?"


@pytest.fixture
def observed(ctx, monkeypatch):
    source = ctx.store.create_source("text", "Original revision")
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Orion", "Mira Chen designed the Orion arm.")])
    acquired, released = [], []
    graph_for = ctx.graph_for

    def acquire(access, **kwargs):
        graph = graph_for(access, **kwargs)
        acquired.append(graph)
        close = getattr(graph, "close_snapshot", None)

        def release():
            released.append(graph)
            if close:
                close()

        graph.close_snapshot = release
        return graph

    monkeypatch.setattr(ctx, "graph_for", acquire)
    monkeypatch.setattr(api, "ctx_of", lambda request: ctx)
    monkeypatch.setattr(api, "principal_of", lambda request: Principal.open())
    monkeypatch.setattr(cli, "_context_or_running_server", lambda: (ctx, None))
    return ctx, acquired, released


def invoke(surface, ctx):
    if surface == "ask":
        return ask.ask(ctx, QUESTION)
    if surface == "search":
        return ask.search(ctx, QUESTION)
    if surface == "answer_from_trace":
        from hippo.hipporag.retriever import Trace

        return ask.answer_from_trace(ctx, Trace(question=QUESTION, settings={}, graph_version=0))
    if surface == "cli":
        return cli.cmd_ask(SimpleNamespace(question=QUESTION))
    if surface.startswith("http"):
        return getattr(api, surface.split("_")[1])(None, api.QuestionBody(question=QUESTION))
    return getattr(mcp_server, surface.split("_")[1] + "_tool")(ctx, QUESTION)


SURFACES = ["ask", "search", "answer_from_trace", "http_ask", "http_search", "mcp_ask", "mcp_search", "cli"]


@pytest.mark.parametrize("surface", SURFACES)
def test_one_graph_is_released_after_success(observed, surface):
    ctx, acquired, released = observed
    invoke(surface, ctx)
    assert len(acquired) == 1
    assert released == acquired


@pytest.mark.parametrize("surface", [s for s in SURFACES if s != "answer_from_trace"])
@pytest.mark.parametrize("revoke", [False, True])
def test_model_failure_releases_graph_and_revocation_wins(observed, monkeypatch, surface, revoke):
    ctx, acquired, released = observed

    def fail(*args, **kwargs):
        if revoke:
            ctx.store._bump_authorization_epoch()
        raise RuntimeError("model failed")

    monkeypatch.setattr(ctx.ollama, "embed_one", fail)
    # Each transport now renders a failure in its own closed vocabulary instead of letting the
    # exception out (Task 5, "Safe transport failures"). What the exception *was* is no longer
    # visible at the boundary, so what this test still pins there is which of the two
    # conditions won — a revocation always outranks the model failure — and, on every surface
    # alike, that the graph was acquired once and released once.
    if surface.startswith("http") and not revoke:
        response = invoke(surface, ctx)
        assert response.status_code == OPERATION_FAILED.http_status
        assert json.loads(bytes(response.body)) == {
            "error": OPERATION_FAILED.message,
            "code": OPERATION_FAILED.code,
        }
    elif surface.startswith("mcp"):
        with pytest.raises(ToolError) as raised:
            invoke(surface, ctx)
        expected = (
            f"{DENIED_CODE}: {DENIED}" if revoke else f"{OPERATION_FAILED.code}: {OPERATION_FAILED.message}"
        )
        assert str(raised.value) == expected
        assert "model failed" not in str(raised.value)
    else:
        with pytest.raises(AuthorizationChanged if revoke else RuntimeError):
            invoke(surface, ctx)
    assert len(acquired) == 1
    assert released == acquired


@pytest.mark.parametrize("surface", ["http_search", "mcp_search", "http_ask", "mcp_ask"])
def test_content_publication_during_model_keeps_rendering_on_same_graph(observed, monkeypatch, surface):
    ctx, acquired, released = observed
    embed = ctx.ollama.embed_one
    published = False
    rendered = []

    def publish(*args, **kwargs):
        nonlocal published
        result = embed(*args, **kwargs)
        if not published:
            published = True
            source = ctx.store.create_source("text", "New revision")
            index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Other", "New revision text.")])
        return result

    def render(graph, trace):
        assert not released
        rendered.append(graph)
        return graph.passages[0].text

    monkeypatch.setattr(ctx.ollama, "embed_one", publish)
    monkeypatch.setattr(ask, "code_block", render)
    monkeypatch.setattr(mcp_server, "code_block", render)
    payload = invoke(surface, ctx)
    assert published
    assert len(acquired) == 1
    # Dense dispatch renders on an activation of the pinned view, not on the view
    # object itself, so identity is the wrong test: what must hold is that the
    # rendered evidence is the acquired evidence and not the publication's.
    assert rendered and all(view_fingerprint(graph) == view_fingerprint(acquired[0]) for graph in rendered)
    assert "Mira Chen" in payload["code_graph"]
    if surface.endswith("ask"):
        assert "Mira Chen" in payload["answer"]
    else:
        rows = payload.get("passages", payload.get("trace", {}).get("passages", []))
        assert rows and all(row["title"] == "Orion" for row in rows)
    assert released == acquired


@pytest.mark.parametrize("submit", [False, True])
def test_html_ask_uses_one_graph_through_inventory_and_render(observed, monkeypatch, submit):
    from hippo.web import render
    from hippo.web.routes import pages

    ctx, acquired, released = observed
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)), state=SimpleNamespace(principal=Principal.open())
    )

    def materialize(request, template, context, **kwargs):
        assert not released
        assert "session" not in context
        assert "authorization_check" not in context
        return context

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    result = pages.ask_submit(request, QUESTION) if submit else pages.ask_page(request, QUESTION)
    assert result["status"]["stats"]["passages"] == 1
    if submit:
        assert "Mira Chen" in result["answer"].answer
    assert len(acquired) == 1
    assert released == acquired


def test_shared_render_session_still_checks_status_when_content_guard_is_noop(observed, monkeypatch):
    from hippo.knowledge.query_access import query_session
    from hippo.web import render

    ctx, acquired, released = observed
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)), state=SimpleNamespace(principal=Principal.open())
    )

    def materialize(request, template, context, **kwargs):
        ctx.store._bump_authorization_epoch()
        return context

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    with pytest.raises(AuthorizationChanged):
        with query_session(ctx, request.state.principal.access) as session:
            render.render(request, "unused.html", authorization_check=lambda: None, session=session)
    assert len(acquired) == 1
    assert released == acquired


def test_defaults_changed_after_acquisition_cannot_change_query_settings(observed):
    from hippo.knowledge.query_access import query_session

    ctx, acquired, released = observed
    captured = ctx.store.get_settings()
    with query_session(ctx) as session:
        ctx.store.update_settings({"qa_top_k": 1})
        trace = ask.search(ctx, QUESTION, session=session)
        assert trace.settings == captured
        assert dict(session.settings) == captured
        with pytest.raises(TypeError):
            session.settings["qa_top_k"] = 2
    assert len(acquired) == 1
    assert released == acquired


@pytest.mark.parametrize("method", ["ask", "search", "answer_from_trace"])
def test_borrowed_session_rejects_incompatible_settings_before_model(observed, monkeypatch, method):
    from hippo.hipporag.retriever import Trace
    from hippo.knowledge.query_access import query_session

    ctx, acquired, released = observed

    def unexpected(*args, **kwargs):
        pytest.fail("Mismatched settings must not reach a model")

    monkeypatch.setattr(ctx.ollama, "embed_one", unexpected)
    with query_session(ctx) as session:
        with pytest.raises(ValueError, match="settings.*session"):
            if method == "answer_from_trace":
                trace = Trace(question=QUESTION, settings={"qa_top_k": 1}, graph_version=0)
                ask.answer_from_trace(ctx, trace, session=session)
            else:
                getattr(ask, method)(ctx, QUESTION, {"qa_top_k": 1}, session=session)
    assert len(acquired) == 1
    assert released == acquired


@pytest.mark.parametrize("method", ["ask", "search"])
def test_http_invalid_settings_are_400_before_graph_acquisition(observed, method):
    from fastapi import HTTPException

    _, acquired, released = observed
    with pytest.raises(HTTPException) as error:
        getattr(api, method)(None, api.QuestionBody(question=QUESTION, settings={"qa_top_k": 0}))
    assert error.value.status_code == 400
    assert not acquired and not released


@pytest.mark.parametrize("method", ["ask", "search"])
def test_http_snapshot_receives_the_full_effective_request_settings(observed, monkeypatch, method):
    ctx, acquired, released = observed
    graph_for = ctx.graph_for
    captured = []

    def acquire(access, **kwargs):
        captured.append(dict(kwargs["settings"]))
        return graph_for(access, **kwargs)

    monkeypatch.setattr(ctx, "graph_for", acquire)
    payload = getattr(api, method)(None, api.QuestionBody(question=QUESTION, settings={"qa_top_k": 1}))
    assert captured == [payload["trace"]["settings"]]
    assert captured[0]["qa_top_k"] == 1
    assert len(acquired) == 1
    assert released == acquired


def test_managed_snapshot_and_trace_keep_defaults_captured_before_acquisition(ctx, monkeypatch):
    from hippo.access import EVERYTHING
    from hippo.knowledge.identity import canonical_json, text_hash
    from hippo.knowledge.query_access import query_session
    from tests.unit.test_query_snapshots import build

    build(ctx)
    captured = ctx.store.get_settings()
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *args, **kwargs: [1.0, 0.0])
    with query_session(ctx, EVERYTHING) as session:
        ctx.store.update_settings({"qa_top_k": 1})
        trace = ask.search(ctx, "revision", access=EVERYTHING, session=session)
        snapshot = ctx.store._knowledge_rows("QuerySnapshot")[0]
        assert trace.settings == captured
        assert snapshot.settings_fingerprint == text_hash(canonical_json(trace.settings))
    assert all(ref.released_at is not None for ref in ctx.store._knowledge_rows("SnapshotReference"))
