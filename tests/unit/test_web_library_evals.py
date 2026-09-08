"""The Library and Evals pages, driven the way a browser would drive them."""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from hippo.web.app import create_app
from hippo.web.routes.evals import parse_question_lines


@pytest.fixture
def client(ctx):
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        yield client


def load_sample(client, ctx) -> str:
    assert client.post("/sources/sample", follow_redirects=False).status_code == 303
    ctx.jobs.wait_all()
    (source,) = ctx.store.list_sources()
    assert source["status"] == "ready"
    return source["id"]


def test_empty_library_invites_you_to_add_something(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Load the sample" in response.text
    assert "Nothing here yet" in response.text


def test_loading_the_sample_indexes_it_and_shows_it_ready(client, ctx):
    source_id = load_sample(client, ctx)
    page = client.get("/")
    assert "Acme Robotics (sample)" in page.text and "ready" in page.text
    detail = client.get(f"/sources/{source_id}")
    assert detail.status_code == 200
    assert "What the model extracted" in detail.text
    assert client.get("/sources/nope").status_code == 404


def test_pasting_text_and_uploading_files_create_sources(client, ctx):
    assert (
        client.post(
            "/sources/text",
            data={"name": "note", "text": "Zed Corp is located in Austin."},
            follow_redirects=False,
        ).status_code
        == 303
    )
    files = [("files", ("guide.md", b"# Guide\n\nAcme Robotics builds robots.", "text/markdown"))]
    assert client.post("/sources/upload", files=files, follow_redirects=False).status_code == 303
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("repo/README.md", "Lyra is a gripper.")
        archive.writestr("repo/main.py", "def lift():\n    return 12\n")
    files = [("files", ("repo.zip", buffer.getvalue(), "application/zip"))]
    assert client.post("/sources/upload", files=files, follow_redirects=False).status_code == 303
    ctx.jobs.wait_all()
    kinds = sorted(s["kind"] for s in ctx.store.list_sources())
    assert kinds == ["archive", "file", "text"]
    assert all(s["status"] == "ready" for s in ctx.store.list_sources())


def test_empty_text_and_empty_upload_are_refused_politely(client):
    response = client.post("/sources/text", data={"name": "x", "text": "  "}, follow_redirects=False)
    assert response.status_code == 303 and "error=" in response.headers["location"]
    response = client.post(
        "/sources/upload", files=[("files", ("empty.txt", b"", "text/plain"))], follow_redirects=False
    )
    assert "error=" in response.headers["location"]


def test_bad_repo_url_is_refused(client):
    response = client.post("/sources/repo", data={"url": "/etc/passwd"}, follow_redirects=False)
    assert "error=" in response.headers["location"]
    assert client.post("/api/sources/repo", json={"url": "file:///tmp"}).status_code == 400


def test_source_json_api_lists_deletes_and_reindexes(client, ctx):
    source_id = load_sample(client, ctx)
    assert client.get("/api/sources").json()[0]["id"] == source_id
    assert client.get(f"/api/sources/{source_id}").json()["status"] == "ready"
    assert client.post(f"/api/sources/{source_id}/reindex").json()["started"] is True
    ctx.jobs.wait_all()
    assert ctx.store.get_source(source_id)["status"] == "ready"
    assert client.delete(f"/api/sources/{source_id}").status_code == 200
    assert client.get(f"/api/sources/{source_id}").status_code == 404
    assert ctx.store.stats()["passages"] == 0


def test_question_lines_accept_pipes_tabs_and_json():
    rows = parse_question_lines("Where is X? | Boulder\nWho made Y?\tMarcus\nNo answer here\n\n")
    assert [r["expected_answer"] for r in rows] == ["Boulder", "Marcus", ""]
    rows = parse_question_lines(
        '[{"question": "Q1", "answer": "A1"}, {"text": "Q2", "expected_answer": "A2", "kind": "multihop"}]'
    )
    assert [(r["text"], r["expected_answer"], r["kind"]) for r in rows] == [
        ("Q1", "A1", "single"),
        ("Q2", "A2", "multihop"),
    ]
    assert parse_question_lines("   ") == []


def test_creating_running_and_comparing_a_question_set(client, ctx):
    load_sample(client, ctx)
    response = client.post(
        "/evals/sets",
        data={
            "name": "mine",
            "questions": "Acme Robotics is headquartered in what? | Boulder\nThe Orion arm was designed by what? | Marcus Lee",
        },
        follow_redirects=False,
    )
    set_id = response.headers["location"].rsplit("/", 1)[1]
    page = client.get(f"/evals/sets/{set_id}")
    assert "Run this set" in page.text and "Boulder" in page.text

    response = client.post(f"/evals/sets/{set_id}/run", data={"name": "first"}, follow_redirects=False)
    run_id = response.headers["location"].rsplit("/", 1)[1]
    ctx.jobs.wait_all()
    run = ctx.store.get_run(run_id)
    assert run["status"] == "done" and run["summary"]["accuracy"] == 1.0

    second = client.post(
        f"/api/evals/sets/{set_id}/run", json={"name": "second", "settings": {"damping": 0.9}}
    ).json()["run_id"]
    ctx.jobs.wait_all()
    page = client.get(f"/evals/runs/{run_id}?compare={second}")
    assert page.status_code == 200 and "vs second" in page.text and "/analyze/" in page.text
    assert "vs second" in client.get(f"/partials/runs/{run_id}?compare={second}").text
    assert ">graph<" in page.text and ">embeddings<" not in page.text  # the graph search answered
    assert "first" in client.get("/evals").text
    assert client.get(f"/api/evals/runs/{run_id}").json()["results"][0]["verdict"] == "correct"

    assert client.delete(f"/api/evals/runs/{second}").status_code == 200
    assert client.delete(f"/api/evals/sets/{set_id}").status_code == 200
    assert ctx.store.list_runs() == []


def test_generating_questions_from_a_source(client, ctx):
    source_id = load_sample(client, ctx)
    response = client.post(
        f"/api/sources/{source_id}/generate-questions", json={"max_single": 3, "max_multihop": 2}
    )
    set_id = response.json()["set_id"]
    ctx.jobs.wait_all()
    question_set = ctx.store.get_question_set(set_id)
    assert question_set["status"] == "ready"
    questions = ctx.store.list_questions(set_id)
    assert len(questions) >= 3
    assert all(q["gold_passage_ids"] for q in questions)
    assert set_id in client.get(f"/sources/{source_id}").text


def test_running_an_empty_set_is_refused(client, ctx):
    set_id = ctx.store.create_question_set("empty")
    response = client.post(f"/evals/sets/{set_id}/run", data={"name": "x"}, follow_redirects=False)
    assert "error=" in response.headers["location"]
    assert client.post("/api/evals/sets/nope/run", json={}).status_code == 404


def test_run_table_says_which_questions_fell_back_to_embeddings(client, ctx):
    # An empty memory has no facts, so every question falls back to plain embedding search.
    set_id = client.post(
        "/api/evals/sets",
        json={"name": "empty", "questions": [{"text": "Where is Acme?", "expected_answer": "Boulder"}]},
    ).json()["set_id"]
    run_id = client.post(f"/api/evals/sets/{set_id}/run", json={}).json()["run_id"]
    ctx.jobs.wait_all()
    run = ctx.store.get_run(run_id)
    assert run["summary"]["dpr_fallbacks"] == 1
    page = client.get(f"/evals/runs/{run_id}")
    assert page.status_code == 200
    assert ">embeddings<" in page.text and ">graph<" not in page.text
    assert ctx.store.list_results(run_id)[0]["used_dpr_fallback"] is True


def test_summary_shows_code_seeded_and_path_fidelity_cards(client, ctx):
    # A prose-only run still carries both keys (S2.11): `code_seeded` reads 0.0 for every
    # question and `path_fidelity` has no commit questions to average, so its card must still
    # render rather than crash on a missing key.
    set_id = client.post(
        "/api/evals/sets",
        json={"name": "empty", "questions": [{"text": "Where is Acme?", "expected_answer": "Boulder"}]},
    ).json()["set_id"]
    run_id = client.post(f"/api/evals/sets/{set_id}/run", json={}).json()["run_id"]
    ctx.jobs.wait_all()
    run = ctx.store.get_run(run_id)
    assert run["summary"]["code_seeded"] == 0.0
    assert run["summary"]["path_fidelity"] is None
    page = client.get(f"/evals/runs/{run_id}")
    assert page.status_code == 200
    assert "Code seeded" in page.text
    assert "Path fidelity" in page.text
