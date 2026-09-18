"""Evaluation model work shares one generation pin and live ownership proof."""

import pytest

from hippo.access import Principal
from hippo.evals import runner
from hippo.knowledge.eval_access import EvalAccess
from hippo.knowledge.query_access import query_session
from tests.unit.test_query_snapshots import build
from tests.unit.test_store_knowledge import reader


@pytest.fixture
def evaluation(ctx, monkeypatch):
    generation, span = build(ctx, text="first revision.")
    workspace = ctx.store.get_source(generation.source_id)["workspace_id"]
    user_id = reader(ctx.store, workspace, "evaluator")
    access = Principal.for_user(ctx.store.get_user(user_id), ctx.store.get_role("individual")).access
    service = EvalAccess(ctx, access)
    set_id = service.create_question_set("original questions", generation.source_id, origin="generated")
    question_id = service.add_questions(
        set_id,
        [
            dict(
                text="What was the first revision?",
                expected_answer="first revision",
                gold_passage_ids=[span.id],
            )
        ],
    )[0]
    question = ctx.store.get_question(question_id)
    assert not active_references(ctx)
    acquired = []
    original = ctx.graph_for

    def graph_for(*args, **kwargs):
        graph = original(*args, **kwargs)
        acquired.append(graph)
        return graph

    monkeypatch.setattr(ctx, "graph_for", graph_for)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *args, **kwargs: [1.0, 0.0])
    return generation, span, access, question, acquired


def active_references(ctx):
    return [r for r in ctx.store._knowledge_rows("SnapshotReference") if r.released_at is None]


@pytest.mark.parametrize("boundary", ["embedding", "grading"])
def test_publication_during_evaluation_keeps_one_generation_through_grade(
    ctx, evaluation, monkeypatch, boundary
):
    generation, span, access, question, acquired = evaluation
    published = []
    grading = []
    original_grade = runner._grade

    def publish():
        if not published:
            published.append(build(ctx, parent=generation, text="second revision"))
        assert ctx.store.collect_generation(generation.id).blocked_reason == "snapshot_reference"

    def embed(*args, **kwargs):
        if boundary == "embedding":
            publish()
        return [1.0, 0.0]

    def grade(*args, **kwargs):
        if boundary == "grading":
            publish()
        grading.append(True)
        assert active_references(ctx)
        assert len(acquired) == 1
        return original_grade(*args, **kwargs)

    monkeypatch.setattr(ctx.ollama, "embed_one", embed)
    monkeypatch.setattr(runner, "_grade", grade)
    result = runner.run_question(ctx, question, {"qa_top_k": 1}, access)
    assert result["error"] is None
    assert "first revision" in result["answer"]
    assert [row["passage_id"] for row in result["trace"]["passages"]] == [span.id]
    assert result["recall"]["recall@1"] == 1
    assert result["gold_rank"] == 1
    assert grading and published
    assert len(acquired) == 1
    assert not active_references(ctx)


@pytest.mark.parametrize("boundary", ["embedding", "grading"])
@pytest.mark.parametrize("failure", ["exception", "revocation", "question_deleted"])
def test_failure_or_denial_releases_pin_and_revocation_withholds_partial_output(
    ctx, evaluation, monkeypatch, boundary, failure
):
    _, _, access, question, acquired = evaluation

    def fail(*args, **kwargs):
        if failure == "revocation":
            ctx.store._bump_authorization_epoch()
        elif failure == "question_deleted":
            ctx.store.delete_question(question["id"])
        raise RuntimeError("evaluation model failure")

    monkeypatch.setattr(ctx.ollama, "embed_one" if boundary == "embedding" else "chat_json", fail)
    result = runner.run_question(ctx, question, {}, access)
    assert result["error"]
    assert len(acquired) == 1
    assert not active_references(ctx)
    if failure != "exception":
        assert result["answer"] == result["thought"] == result["judge_reason"] == ""
        assert result["trace"] == {} and result["recall"] == {}


def test_caller_owns_borrowed_session_until_after_result(ctx, evaluation):
    _, _, access, question, acquired = evaluation
    with query_session(ctx, access, settings={"qa_top_k": 1}) as session:
        result = runner.run_question(ctx, question, {"qa_top_k": 1}, access, session=session)
        assert result["error"] is None
        assert active_references(ctx)
        assert len(acquired) == 1
        session.validate()
    assert not active_references(ctx)
