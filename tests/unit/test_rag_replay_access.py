"""Saved traces contribute IDs; current authorized evidence supplies their text."""

import json

import pytest

from hippo import ask
from hippo.access import Access
from hippo.hipporag.indexer import Chunk, index_source


def test_replay_rebuilds_labels_and_drops_hidden_evidence_and_model_text(ctx):
    from hippo.knowledge import replay

    ctx.store.ensure_roles()
    public = ctx.store.create_source("text", "Public guide")
    private = ctx.store.create_source("text", "PRIVATE PROJECT")
    index_source(ctx.store, ctx.ollama, public, [Chunk(0, "Public", "Mira designed the Orion arm.")])
    index_source(
        ctx.store, ctx.ollama, private, [Chunk(0, "PRIVATE TITLE", "SECRET private project details.")]
    )
    trace = ask.search(ctx, "Who designed Orion?")
    for passage in trace.passages:
        passage.title = "PRIVATE SAVED TITLE"
        passage.preview = "SECRET OLD BODY"
    for candidate in trace.fact_candidates:
        candidate.triple = ["SECRET", "old", "triple"]
        candidate.reason = "SECRET reasoning"
    trace.filter["raw_response"] = "SECRET MODEL RESPONSE"
    trace.select["raw"] = "SECRET SELECT RESPONSE"
    trace.history = [{"id": "unknown", "subject": "SECRET HISTORY"}]
    trace.paths = [{"a": "unknown", "b": "unknown", "kind": "INVOKES", "a_name": "SECRET PATH"}]
    trace.expansions = [{"text": "SECRET EXPANSION"}]
    ctx.store.set_source_access(private, "local-admin")
    graph = ctx.graph_for(Access(rank=0, user_id="reader"))
    safe = replay.reconstruct_trace(graph, trace, question="Who designed Orion?")
    encoded = json.dumps(safe.to_dict())
    assert "SECRET" not in encoded and "PRIVATE" not in encoded
    assert safe.passages and {p.source_id for p in safe.passages} == {public}
    assert all(p.preview == graph.passage_by_id(p.passage_id).text for p in safe.passages)
    assert safe.paths == [] and safe.history == [] and safe.expansions == []
    assert trace.filter["raw_response"] == "SECRET MODEL RESPONSE", "Do not mutate shared saved data"


def test_saved_answer_requires_matching_current_evidence_fingerprint(ctx):
    from hippo.knowledge import replay

    ctx.store.ensure_roles()
    source = ctx.store.create_source("text", "Guide")
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Public", "Mira designed the Orion arm.")])
    graph = ctx.graph_for(Access(rank=0, user_id="reader"))
    stamp = replay.view_fingerprint(graph)
    assert replay.can_reuse_answer(graph, stamp)
    assert not replay.can_reuse_answer(graph, "")
    ctx.store.set_source_access(source, "local-admin")
    assert not replay.can_reuse_answer(ctx.graph_for(Access(rank=0, user_id="reader")), stamp)


def test_new_queries_record_the_exact_audience_input_fingerprint(ctx):
    from hippo.hipporag.retriever import trace_from_dict
    from hippo.knowledge.replay import view_fingerprint

    trace = ask.search(ctx, "anything")
    assert getattr(trace, "evidence_fingerprint", "") == view_fingerprint(ctx.graph_for(None))
    assert trace_from_dict(trace.to_dict()).evidence_fingerprint == trace.evidence_fingerprint


def test_adhoc_recall_withholds_old_answer_and_reconstructs_after_access_loss(ctx):
    from hippo.web.adhoc import recall_adhoc, remember_adhoc

    ctx.store.ensure_roles()
    source = ctx.store.create_source("text", "Guide")
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Private later", "Mira designed Orion.")])
    access = Access(rank=0, user_id="reader")
    trace, _ = ask.ask(ctx, "Who designed Orion?", access=access)
    key = remember_adhoc(
        trace, {"answer": "SECRET CACHED ANSWER", "thought": "SECRET THOUGHT"}, owner="reader"
    )
    before = recall_adhoc(key, "reader", graph=ctx.graph_for(access))
    assert before["answer"]["answer"] == "SECRET CACHED ANSWER"
    ctx.store.set_source_access(source, "local-admin")
    after = recall_adhoc(key, "reader", graph=ctx.graph_for(access))
    assert "SECRET" not in json.dumps(after)
    assert after["trace"]["passages"] == []
    assert recall_adhoc(key, "other", graph=ctx.graph_for(access)) is None


def test_reanswer_cannot_send_saved_hidden_code_paths_to_the_model(ctx, monkeypatch):
    ctx.store.ensure_roles()
    public = ctx.store.create_source("text", "Public")
    private = ctx.store.create_source("text", "Private")
    index_source(ctx.store, ctx.ollama, public, [Chunk(0, "Public", "Mira designed Orion.")])
    index_source(ctx.store, ctx.ollama, private, [Chunk(0, "Private", "Secret project details.")])
    access = Access(rank=0, user_id="reader")
    trace = ask.search(ctx, "Who designed Orion?", access=access)
    trace.used_code_seeds = True
    trace.paths = [
        {
            "a": "hidden-a",
            "b": "hidden-b",
            "kind": "INVOKES",
            "omega": 1.0,
            "a_name": "SECRET PATH",
            "b_name": "SECRET TARGET",
        }
    ]
    ctx.store.set_source_access(private, "local-admin")
    original = ctx.ollama.chat_text
    messages = []

    def capture(*args, **kwargs):
        messages.extend(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(ctx.ollama, "chat_text", capture)
    answer = ask.answer_from_trace(ctx, trace, access)
    assert answer.passage_ids
    assert "SECRET" not in json.dumps(messages)


def test_simulation_diff_does_not_reveal_old_hidden_titles(ctx):
    from hippo.analysis.simulate import Overrides, simulate

    ctx.store.ensure_roles()
    public = ctx.store.create_source("text", "Public")
    private = ctx.store.create_source("text", "SECRET SOURCE")
    index_source(ctx.store, ctx.ollama, public, [Chunk(0, "Public", "Mira designed Orion.")])
    index_source(ctx.store, ctx.ollama, private, [Chunk(0, "SECRET TITLE", "Secret project details.")])
    access = Access(rank=0, user_id="reader")
    baseline = ask.search(ctx, "Who designed Orion?", access=access)
    ctx.store.set_source_access(private, "local-admin")
    outcome = simulate(ctx, baseline.question, Overrides(), baseline, access)
    assert "SECRET" not in json.dumps(outcome.diff)


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
@pytest.mark.parametrize("endpoint", ["analyze", "simulate"])
def test_saved_analysis_routes_require_the_evaluation_owner(ctx, endpoint):
    from fastapi.testclient import TestClient

    from hippo.knowledge.eval_access import EvalAccess
    from hippo.web.app import create_app

    ctx.store.ensure_roles()
    owner = ctx.store.create_user("owner", "secret1", "local-admin")
    ctx.store.create_user("outsider", "secret2", "local-admin")
    evaluation = EvalAccess(ctx, Access(rank=20, user_id=owner))
    set_id = evaluation.create_question_set("SECRET SET")
    question_id = evaluation.add_questions(
        set_id, [{"text": "SECRET QUESTION", "expected_answer": "SECRET"}]
    )[0]
    run_id = evaluation.create_run(set_id, "SECRET RUN", ctx.store.get_settings())
    result_id = ctx.store.add_result(run_id, question_id, {"answer": "SECRET ANSWER", "trace": {}})
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.post("/login", data={"username": "outsider", "password": "secret2"})
        response = (
            client.get("/analyze/" + result_id)
            if endpoint == "analyze"
            else client.post("/api/simulate", json={"result_id": result_id})
        )
    assert response.status_code == 404
    assert "SECRET" not in response.text


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_analysis_revocation_during_html_render_discards_cached_answer(ctx, monkeypatch):
    from fastapi.testclient import TestClient

    from hippo.web.adhoc import remember_adhoc
    from hippo.web.app import create_app
    from hippo.web.render import templates

    ctx.store.ensure_roles()
    source = ctx.store.create_source("text", "Guide")
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Title", "Mira designed Orion.")])
    trace = ask.search(ctx, "Who designed Orion?")
    key = remember_adhoc(trace, {"answer": "SECRET CACHED ANSWER"})
    original = templates.TemplateResponse

    def render_then_revoke(*args, **kwargs):
        response = original(*args, **kwargs)
        ctx.store.set_source_access(source, "local-admin")
        return response

    monkeypatch.setattr(templates, "TemplateResponse", render_then_revoke)
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        response = client.get("/analyze", params={"key": key})
    assert response.status_code == 409
    assert "SECRET" not in response.text


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_saved_question_revoked_before_simulation_never_reaches_model(ctx, monkeypatch):
    from fastapi.testclient import TestClient

    from hippo.knowledge.eval_access import EvalAccess
    from hippo.web.app import create_app
    from hippo.web.routes import analyze

    ctx.store.ensure_roles()
    owner = ctx.store.create_user("simulation-owner", "secret1", "local-admin")
    private = ctx.store.create_source("text", "Private later")
    public = ctx.store.create_source("text", "Still public")
    for source in (private, public):
        index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Title", "Mira designed Orion.")])
    evaluation = EvalAccess(ctx, Access(rank=20, user_id=owner))
    set_id = evaluation.create_question_set("Owned set", source_id=private)
    question_id = evaluation.add_questions(set_id, [{"text": "SECRET SAVED QUESTION"}])[0]
    run_id = evaluation.create_run(set_id, "Owned run", ctx.store.get_settings())
    result_id = ctx.store.add_result(run_id, question_id, {"answer": "SECRET", "trace": {}})
    original = analyze.run_simulation
    calls = []

    def revoke_then_simulate(*args, **kwargs):
        ctx.store.set_source_access(private, "arch-admin")
        return original(*args, **kwargs)

    def capture(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Revoked saved question reached the model")

    monkeypatch.setattr(analyze, "run_simulation", revoke_then_simulate)
    for method in ("embed_one", "chat_json", "chat_text"):
        monkeypatch.setattr(ctx.ollama, method, capture)
    with TestClient(create_app(ctx), base_url="http://localhost", raise_server_exceptions=False) as client:
        client.headers["Authorization"] = "Bearer " + ctx.store.get_user(owner)["token"]
        response = client.post("/api/simulate", json={"result_id": result_id})
    assert response.status_code == 409
    assert calls == []
