"""Browsing a rendered candidate keeps its original evidence visible and distinct."""

from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

from hippo.web.app import create_app
from tests.unit.test_answer_original_citations import derived_graph  # noqa: F401


def test_graph_node_exposes_complete_originals_for_a_derived_candidate(ctx, derived_graph, monkeypatch):  # noqa: F811
    index, _ = derived_graph
    monkeypatch.setattr(ctx, "graph_for", lambda *a, **kw: index)
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        response = client.get("/api/graph/node/view-a")
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_derived"] is True
    assert payload["citation_ids"] == ["span-a", "span-b"]
    assert [row["text"] for row in payload["citations"]] == ["def original(): pass", "# Original requirement"]
    assert payload["text"] == "GENERATED PLACEHOLDER A"
    assert all(row["location"] == "original.py, lines 1" for row in payload["citations"])


def test_source_page_labels_rendered_text_and_shows_originals(ctx, derived_graph, monkeypatch):  # noqa: F811
    index, _ = derived_graph
    sid = ctx.store.create_source("text", "Original source")
    index.passages = [replace(p, source_id=sid) for p in index.passages]
    index.original_citations = tuple(replace(c, source_id=sid) for c in index.original_citations)
    monkeypatch.setattr(ctx, "graph_for", lambda *a, **kw: index)
    original = ctx.store._knowledge_rows
    monkeypatch.setattr(
        ctx.store,
        "_knowledge_rows",
        lambda kind: [SimpleNamespace(source_id=sid)] if kind == "Artifact" else original(kind),
    )
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        response = client.get("/sources/" + sid)
    assert response.status_code == 200
    assert "Derived retrieval text" in response.text
    assert "Original evidence" in response.text
    assert "original.py, lines 1" in response.text
    assert "def original(): pass" in response.text
    assert "# Original requirement" in response.text
