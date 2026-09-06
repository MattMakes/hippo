"""The web foundation: app factory, Ask page, Settings page, status and graph endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hippo.hipporag.indexer import Chunk, index_source
from hippo.web.app import create_app
from hippo.web.routes.pages import parse_settings_form


def sample_chunks(sample_text: str) -> list[Chunk]:
    sections = sample_text.split("## ")[1:]
    return [
        Chunk(i, s.splitlines()[0].strip(), "\n".join(s.splitlines()[1:]).strip())
        for i, s in enumerate(sections)
    ]


@pytest.fixture
def client(ctx, sample_text):
    source_id = ctx.store.create_source("sample", "Acme guide")
    index_source(ctx.store, ctx.ollama, source_id, sample_chunks(sample_text))
    with TestClient(create_app(ctx)) as client:
        yield client


def test_ask_page_renders_with_the_question_prefilled(client):
    response = client.get("/ask?q=Who+designed+the+Orion+arm%3F")
    assert response.status_code == 200
    assert "Who designed the Orion arm?" in response.text


def test_asking_returns_an_answer_with_facts_and_passages(client):
    response = client.post("/ask", data={"question": "Where is Acme Robotics headquartered?"})
    assert response.status_code == 200
    assert "Boulder" in response.text
    assert "Facts the model kept" in response.text
    assert "Analyze this question" in response.text


def test_empty_question_shows_a_friendly_error(client):
    response = client.post("/ask", data={"question": "   "})
    assert "Type a question first" in response.text


def test_settings_page_lists_every_setting_with_help(client):
    response = client.get("/settings")
    assert response.status_code == 200
    for key in ("linking_top_k", "passage_node_weight", "damping", "node_specificity"):
        assert key in response.text


def test_saving_settings_changes_what_search_uses(client, ctx):
    response = client.post(
        "/settings",
        data={"damping": "0.7", "linking_top_k": "6", "node_specificity": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    settings = ctx.store.get_settings()
    assert settings["damping"] == 0.7
    assert settings["linking_top_k"] == 6
    assert settings["node_specificity"] is True


def test_unchecked_checkbox_means_false():
    assert parse_settings_form({"damping": "0.5"})["node_specificity"] is False
    assert parse_settings_form({"node_specificity": "on"})["node_specificity"] is True
    assert "damping" not in parse_settings_form({"damping": ""})


def test_status_endpoint_reports_everything_ready(client):
    status = client.get("/api/status").json()
    assert status["neo4j"] is True
    assert status["ollama"] is True
    assert status["models_ready"] is True
    assert status["stats"]["passages"] == 8


def test_settings_api_rejects_unknown_keys(client):
    assert client.put("/api/settings", json={"damping": 0.6}).json()["damping"] == 0.6
    assert client.put("/api/settings", json={"nonsense": 1}).status_code == 400


def test_ask_api_returns_answer_and_trace(client):
    data = client.post("/api/ask", json={"question": "Who designed the Orion arm?"}).json()
    assert data["answer"] == "Marcus Lee"
    assert "The Orion arm" in [p["title"] for p in data["trace"]["passages"][:3]]
    assert any(c["kept"] for c in data["trace"]["fact_candidates"])


def test_search_api_returns_only_a_trace(client):
    data = client.post("/api/search", json={"question": "Who designed the Orion arm?"}).json()
    assert "answer" not in data
    assert data["trace"]["question"] == "Who designed the Orion arm?"


def test_entity_search_and_neighborhood(client):
    entities = client.get("/api/entities?q=acme").json()
    assert entities and entities[0]["name"] == "acme robotics"
    graph = client.get(f"/api/graph/neighborhood?node_id={entities[0]['id']}").json()
    assert any(n["kind"] == "passage" for n in graph["nodes"])
    assert all("kinds" in e for e in graph["edges"])
    assert client.get("/api/graph/neighborhood?node_id=nope").status_code == 404


def test_status_partial_renders_pills(client):
    text = client.get("/partials/status").text
    assert "Neo4j" in text and "Ollama" in text
