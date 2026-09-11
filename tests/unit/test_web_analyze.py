"""The Analyze page, the simulate endpoint, and changesets, as the browser uses them."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hippo.web.app import create_app

MULTIHOP = "In which state is the company founded by Priya Natarajan headquartered?"


@pytest.fixture
def client(ctx):
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.post("/sources/sample", follow_redirects=False)
        ctx.jobs.wait_all()
        yield client


@pytest.fixture
def result_id(client, ctx) -> str:
    """A stored evaluation result for the multi-hop question."""
    set_id = client.post(
        "/api/evals/sets",
        json={
            "name": "s",
            "questions": [{"text": MULTIHOP, "expected_answer": "Colorado", "kind": "multihop"}],
        },
    ).json()["set_id"]
    run_id = client.post(f"/api/evals/sets/{set_id}/run", json={}).json()["run_id"]
    ctx.jobs.wait_all()
    return ctx.store.list_results(run_id)[0]["id"]


def test_adhoc_analysis_redirects_to_a_cached_key_and_renders(client):
    # A POST does the search; the GET it redirects to only shows the cached trace.
    response = client.post("/analyze", data={"question": MULTIHOP}, follow_redirects=False)
    assert response.status_code == 303 and "key=" in response.headers["location"]
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert "ask this again" in page.text and "/ask?q=" in page.text
    for text in (
        "What the search did",
        "candidate facts",
        "seed entities",
        "Tweak",
        "analyze-data",
        "Not from an evaluation",
    ):
        assert text in page.text
    assert client.get("/analyze", follow_redirects=False).status_code == 303  # no question -> back to Ask
    assert client.post("/analyze", data={"question": " "}, follow_redirects=False).status_code == 303


def test_stored_result_analysis_shows_expected_answer_verdict_and_gold(client, result_id):
    page = client.get(f"/analyze/{result_id}")
    assert page.status_code == 200
    assert "Colorado" in page.text and "Expected" in page.text
    assert "gold" in page.text
    assert client.get("/analyze/nope").status_code == 404


def test_simulating_a_setting_change_returns_a_diff_and_ops(client, result_id):
    out = client.post(
        "/api/simulate", json={"result_id": result_id, "overrides": {"settings": {"damping": 0.9}}}
    ).json()
    assert out["trace"]["settings"]["damping"] == 0.9
    assert out["trace"]["filter"]["replayed"] is True
    assert out["diff"]["passages"] and {"before_rank", "after_rank", "title"} <= set(
        out["diff"]["passages"][0]
    )
    assert out["ops"] == [{"op": "set_setting", "name": "damping", "value": 0.9}]
    assert out["answer"] is None
    assert "subgraph" in out["explanation"]


def test_simulating_with_facts_boosts_edges_and_a_new_answer(client, ctx, result_id):
    trace = ctx.store.get_result(result_id)["trace"]
    kept = [c for c in trace["fact_candidates"] if c["kept"]]
    seed = trace["seed_entities"][0]
    overrides = {
        "force_exclude": [kept[0]["fact_id"]],
        "node_boosts": {seed["entity_id"]: 2.0},
        "edge_edits": [{"a": seed["entity_id"], "b": trace["passages"][0]["passage_id"], "weight": 0}],
        "reanswer": True,
    }
    out = client.post("/api/simulate", json={"result_id": result_id, "overrides": overrides}).json()
    assert out["answer"] and out["answer"]["answer"]
    assert not any(c["fact_id"] == kept[0]["fact_id"] and c["kept"] for c in out["trace"]["fact_candidates"])
    ops = {(o["op"]) for o in out["ops"]}
    assert ops == {"set_node_boost", "set_edge_weight"}  # forcing facts is per-question, never an op


def test_simulate_without_a_baseline_runs_the_filter_once(client):
    out = client.post(
        "/api/simulate", json={"question": "Who designed the Lyra gripper?", "overrides": {}}
    ).json()
    assert out["trace"]["passages"][0]["title"].endswith("The Lyra gripper")


def test_simulate_rejects_bad_input(client):
    assert client.post("/api/simulate", json={"question": "", "overrides": {}}).status_code == 400
    assert client.post("/api/simulate", json={"result_id": "nope", "overrides": {}}).status_code == 404
    assert client.post("/api/simulate", json={"trace_key": "expired", "overrides": {}}).status_code == 404


def test_saving_and_applying_a_changeset_changes_the_graph(client, ctx, result_id):
    trace = ctx.store.get_result(result_id)["trace"]
    seed = trace["seed_entities"][0]
    out = client.post(
        "/api/simulate",
        json={
            "result_id": result_id,
            "overrides": {"settings": {"damping": 0.8}, "node_boosts": {seed["entity_id"]: 2.0}},
        },
    ).json()
    saved = client.post(
        "/api/changesets",
        json={"name": "try", "ops": out["ops"], "from_result_id": result_id, "note": "test"},
    ).json()
    page = client.get("/changesets")
    assert "try" in page.text and "draft" in page.text

    version = ctx.store.graph_version()
    applied = client.post(f"/api/changesets/{saved['changeset_id']}/apply")
    assert applied.status_code == 200
    assert ctx.store.graph_version() > version
    assert ctx.store.get_settings()["damping"] == 0.8
    index = ctx.graph()
    assert index.entity_boost[index.idx_of[seed["entity_id"]]] == 2.0
    assert "applied" in client.get("/changesets").text
    assert client.delete(f"/api/changesets/{saved['changeset_id']}").status_code == 200
    assert client.get("/api/changesets").json() == []


def test_changeset_api_validates_ops(client):
    assert (
        client.post("/api/changesets", json={"name": "bad", "ops": [{"op": "nonsense"}]}).status_code == 400
    )
    assert client.post("/api/changesets/nope/apply").status_code == 404


def test_analysis_of_an_old_result_survives_the_graph_changing(client, ctx, result_id):
    """A stored trace remembers vertex numbers that shift when sources come and go; the page must not crash."""
    from hippo.ingest import pipeline

    extra = pipeline.add_text(ctx, "extra", "Zed Corp is located in Austin. Austin is located in Texas.")
    ctx.jobs.wait_all()
    assert client.delete(f"/api/sources/{extra}").status_code == 200
    page = client.get(f"/analyze/{result_id}")
    assert page.status_code == 200
    # Replay now reconstructs vertex references from current evidence IDs. A
    # transient global version bump with unchanged visible evidence is not a
    # reason to expose a corpus-change notification.
    assert "graph has changed" not in page.text
