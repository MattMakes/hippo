"""
Pages while work is in progress: a model downloading, a source indexing, a run running.

The other web tests only look at pages after the fakes have finished, which is how
`(a, b) | pct` and `run.summary.accuracy` on an empty summary once crashed every page
for the whole duration of a 6 GB download. These tests freeze the app mid-work.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hippo import status as status_module
from hippo.web.app import create_app
from hippo.web.render import STOP_POLLING, TEMPLATES_DIR, templates


@pytest.fixture
def client(ctx, monkeypatch):
    monkeypatch.setattr(status_module, "CACHE_SECONDS", 0.0)  # the header status must not be stale
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        yield client


def test_every_template_compiles():
    for path in TEMPLATES_DIR.rglob("*.html"):
        templates.env.get_template(str(path.relative_to(TEMPLATES_DIR)))


def test_pages_render_while_a_model_is_downloading(client, ctx, monkeypatch):
    ctx.models.progress["qwen3:8b"] = {
        "status": "downloading",
        "completed": 1_000_000,
        "total": 5_000_000,
        "done": False,
        "error": None,
    }
    monkeypatch.setattr(ctx.models, "is_pulling", lambda: True)
    for path in ("/", "/partials/status", "/ask", "/settings"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "20%" in response.text, path


def test_pages_render_while_a_source_is_indexing(client, ctx):
    # Set the status after startup: startup marks anything still "indexing" as interrupted.
    source_id = ctx.store.create_source("text", "big book")
    ctx.store.update_source(
        source_id, status="indexing", stage="extracting facts", progress_done=2, progress_total=8
    )
    for path in ("/", "/partials/sources", f"/sources/{source_id}", f"/partials/sources/{source_id}/status"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "width: 25%" in response.text and "extracting facts" in response.text, path


def test_pages_render_while_a_run_is_running_or_after_it_failed(client, ctx):
    set_id = ctx.store.create_question_set("mine")
    ctx.store.add_questions(set_id, [{"text": "Where is Acme?", "expected_answer": "Boulder"}] * 4)
    run_id = ctx.store.create_run(set_id, "slow run", ctx.store.get_settings())
    ctx.store.update_run(run_id, progress_done=1)
    for path in ("/evals", f"/evals/sets/{set_id}", f"/evals/runs/{run_id}", f"/partials/runs/{run_id}"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "running" in response.text.lower(), path
    assert "width: 25%" in client.get("/evals").text  # the progress bar in the run history table
    page = client.get(f"/evals/runs/{run_id}").text
    assert "No summary yet" in page and "1/4 questions answered" in page
    assert client.get("/evals").text.count("–") >= 5  # every empty metric cell is a dash, not a crash

    ctx.store.update_run(run_id, status="failed", error="Ollama went away")
    # `partials/run_status.html`'s title attribute renders the closed public reason too, the
    # same as the run page, so the raw string never reaches either list page.
    for path in ("/evals", f"/evals/sets/{set_id}"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Operation failed" in response.text, path
        assert "Ollama went away" not in response.text, path
    # The run page reports the failure from the closed code instead, so a row written by the
    # runner (`"<code>: <private text>"`) says the same thing to every audience. A string with
    # no code prefix is still presenting a failure, so it takes the `operation_failed` sentence
    # rather than falling silent.
    page = client.get(f"/evals/runs/{run_id}")
    assert page.status_code == 200
    assert "The run failed: Operation failed" in page.text
    assert "Ollama went away" not in page.text


def test_partials_tell_htmx_to_stop_polling_when_nothing_is_in_flight(client, ctx):
    assert client.get("/partials/sources").status_code == STOP_POLLING
    assert client.get("/partials/evals/tables").status_code == STOP_POLLING

    source_id = ctx.store.create_source("text", "note")
    ctx.store.update_source(source_id, status="indexing", stage="reading", progress_total=3)
    assert client.get("/partials/sources").status_code == 200
    assert client.get(f"/partials/sources/{source_id}/status").status_code == 200
    ctx.store.update_source(source_id, status="ready", stage="")
    assert client.get("/partials/sources").status_code == STOP_POLLING
    assert client.get(f"/partials/sources/{source_id}/status").status_code == STOP_POLLING

    set_id = ctx.store.create_question_set("mine")
    ctx.store.add_questions(set_id, [{"text": "Where is Acme?", "expected_answer": "Boulder"}])
    run_id = ctx.store.create_run(set_id, "run", ctx.store.get_settings())
    assert client.get("/partials/evals/tables").status_code == 200
    assert client.get(f"/partials/runs/{run_id}").status_code == 200
    ctx.store.update_run(run_id, status="done", summary_json='{"accuracy": 1.0, "correct": 1}')
    assert client.get("/partials/evals/tables").status_code == STOP_POLLING
    assert client.get(f"/partials/runs/{run_id}").status_code == STOP_POLLING

    ctx.store.update_question_set(set_id, status="generating", stage="single-hop")
    assert client.get("/partials/evals/tables").status_code == 200
    assert client.get("/partials/status").status_code == 200  # the header keeps polling: services come and go
