"""Saved results own durable references independently of active query leases."""

import pytest

from hippo import ask
from hippo.access import EVERYTHING
from hippo.knowledge.query_access import query_session
from tests.unit.test_query_snapshots import build


def evaluation_rows(store):
    question_set = store.create_question_set("snapshot retention")
    question = store.add_questions(question_set, [{"text": "revision"}])[0]
    run = store.create_run(question_set, "retained run", store.get_settings())
    return run, question


def test_saved_result_keeps_old_generation_after_active_query_closes(ctx, monkeypatch):
    from hippo.knowledge import saved_snapshots

    gen, span = build(ctx)
    run, question = evaluation_rows(ctx.store)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *a, **kw: [1.0, 0.0])
    with query_session(ctx, EVERYTHING) as session:
        trace = ask.search(ctx, "revision", session=session)
        result = {"trace": trace.to_dict(), "answer": span.text}
        result_id = saved_snapshots.save_evaluation_result(ctx.store, run, question, result, session=session)
        build(ctx, parent=gen, text="replacement")
    assert ctx.store.collect_generation(gen.id).blocked_reason == "snapshot_reference"
    saved = ctx.store.get_result(result_id)
    assert saved["trace"]["snapshot_ids"] == list(trace.snapshot_ids)
    saved_snapshots.release_saved_evaluations(ctx.store, [result_id])
    assert ctx.store.collect_generation(gen.id).blocked_reason is None


def test_failed_retention_rolls_back_result_and_all_references(ctx, monkeypatch):
    from hippo.knowledge import saved_snapshots

    build(ctx)
    run, question = evaluation_rows(ctx.store)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *a, **kw: [1.0, 0.0])
    retain = ctx.store.retain_snapshot

    def fail_after_retain(*args, **kwargs):
        retain(*args, **kwargs)
        raise ValueError("injected retention failure")

    with query_session(ctx, EVERYTHING) as session:
        trace = ask.search(ctx, "revision", session=session)
        monkeypatch.setattr(ctx.store, "retain_snapshot", fail_after_retain)
        with pytest.raises(ValueError, match="injected retention failure"):
            saved_snapshots.save_evaluation_result(
                ctx.store, run, question, {"trace": trace.to_dict()}, session=session
            )
    assert ctx.store.list_results(run) == []
    assert not [r for r in ctx.store._knowledge_rows("SnapshotReference") if r.kind == "saved"]


def test_snapshot_identity_round_trips_and_old_traces_have_no_history_claim(ctx, monkeypatch):
    from hippo.hipporag.retriever import trace_from_dict

    build(ctx)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *a, **kw: [1.0, 0.0])
    with query_session(ctx, EVERYTHING) as session:
        trace = ask.search(ctx, "revision", session=session)
        assert trace.snapshot_ids == session.graph.snapshot_ids
        assert trace_from_dict(trace.to_dict()).snapshot_ids == trace.snapshot_ids
    assert trace_from_dict({}).snapshot_ids == ()


@pytest.mark.parametrize("delete", ["run", "question", "set"])
def test_authorized_deletion_releases_saved_result_references(ctx, monkeypatch, delete):
    from hippo.knowledge.eval_access import EvalAccess
    from hippo.knowledge.saved_snapshots import save_evaluation_result

    gen, _ = build(ctx)
    run, question = evaluation_rows(ctx.store)
    set_id = ctx.store.get_run(run)["set_id"]
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *a, **kw: [1.0, 0.0])
    with query_session(ctx, EVERYTHING) as session:
        trace = ask.search(ctx, "revision", session=session)
        save_evaluation_result(ctx.store, run, question, {"trace": trace.to_dict()}, session=session)
    build(ctx, parent=gen, text="replacement")
    assert ctx.store.collect_generation(gen.id).blocked_reason == "snapshot_reference"
    service = EvalAccess(ctx, EVERYTHING)
    if delete == "run":
        service.delete_run(run)
    elif delete == "question":
        service.delete_question(question)
    else:
        service.delete_question_set(set_id)
    assert ctx.store.collect_generation(gen.id).blocked_reason is None


def test_background_runner_retains_exact_snapshot_before_closing_session(ctx, monkeypatch):
    from hippo.evals.runner import _run_all

    gen, span = build(ctx, text="first revision.")
    run, _ = evaluation_rows(ctx.store)
    set_id = ctx.store.get_run(run)["set_id"]
    published = []

    def embed(*args, **kwargs):
        if not published:
            published.append(build(ctx, parent=gen, text="second revision."))
        return [1.0, 0.0]

    monkeypatch.setattr(ctx.ollama, "embed_one", embed)
    _run_all(ctx, run, set_id, ctx.store.get_settings(), EVERYTHING)
    row = ctx.store.get_result(ctx.store.list_results(run)[0]["id"])
    assert row["error"] is None
    assert row["trace"]["passages"][0]["passage_id"] == span.id
    assert row["trace"]["snapshot_ids"]
    refs = ctx.store._knowledge_rows("SnapshotReference")
    assert all(r.released_at is not None for r in refs if r.kind == "active_query")
    assert any(r.released_at is None for r in refs if r.kind == "saved")
    assert ctx.store.collect_generation(gen.id).blocked_reason == "snapshot_reference"


def test_closed_or_mismatched_session_cannot_save(ctx, monkeypatch):
    from dataclasses import replace

    from hippo.knowledge.access import AuthorizationChanged
    from hippo.knowledge.saved_snapshots import save_evaluation_result

    build(ctx)
    run, question = evaluation_rows(ctx.store)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *a, **kw: [1.0, 0.0])
    with query_session(ctx, EVERYTHING) as session:
        trace = ask.search(ctx, "revision", session=session)
        forged = replace(trace, snapshot_ids=("another snapshot",))
        with pytest.raises(ValueError, match="snapshots differ"):
            save_evaluation_result(ctx.store, run, question, {"trace": forged.to_dict()}, session=session)
    with pytest.raises(AuthorizationChanged):
        save_evaluation_result(ctx.store, run, question, {"trace": trace.to_dict()}, session=session)
    assert ctx.store.list_results(run) == []


def test_reconstructed_trace_identifies_its_new_evidence_view(ctx, monkeypatch):
    from hippo.knowledge.replay import reconstruct_trace

    gen, _ = build(ctx)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *a, **kw: [1.0, 0.0])
    original = ask.search(ctx, "revision", access=EVERYTHING)
    build(ctx, parent=gen, text="replacement")
    with query_session(ctx, EVERYTHING) as session:
        rebuilt = reconstruct_trace(session.graph, original, question="revision")
        assert rebuilt.snapshot_ids == session.graph.snapshot_ids
        assert rebuilt.snapshot_ids != original.snapshot_ids


@pytest.mark.parametrize("delete", ["run", "question", "set"])
def test_owner_can_delete_stale_generated_evaluation_without_reading_old_evidence(ctx, monkeypatch, delete):
    from hippo.access import Principal
    from hippo.knowledge.eval_access import EvalAccess
    from hippo.knowledge.saved_snapshots import save_evaluation_result
    from tests.unit.test_store_knowledge import reader

    gen, span = build(ctx)
    workspace = ctx.store.get_source(gen.source_id)["workspace_id"]
    user_id = reader(ctx.store, workspace, "saved-owner")
    access = Principal.for_user(ctx.store.get_user(user_id), ctx.store.get_role("individual")).access
    service = EvalAccess(ctx, access)
    set_id = service.create_question_set("generated questions", gen.source_id, origin="generated")
    question = service.add_questions(set_id, [{"text": "revision", "gold_passage_ids": [span.id]}])[0]
    run = service.create_run(set_id, "saved", ctx.store.get_settings())
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *a, **kw: [1.0, 0.0])
    with query_session(ctx, access) as session:
        trace = ask.search(ctx, "revision", session=session)
        result_id = save_evaluation_result(
            ctx.store, run, question, {"trace": trace.to_dict()}, session=session
        )
    build(ctx, parent=gen, text="replacement")
    assert service.get_question(question) is None
    assert service.get_result(result_id) is None
    assert ctx.store.collect_generation(gen.id).blocked_reason == "snapshot_reference"
    if delete == "run":
        service.delete_run(run)
    elif delete == "question":
        service.delete_question(question)
    else:
        service.delete_question_set(set_id)
    assert not [
        ref
        for ref in ctx.store._knowledge_rows("SnapshotReference")
        if ref.kind == "saved" and ref.released_at is None
    ]
