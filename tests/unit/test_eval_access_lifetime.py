"""Standalone evaluation reads and writes own their generation references."""

import json
from contextlib import contextmanager

import pytest

from hippo.knowledge import eval_access
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.eval_access import EvalAccess, EvalAccessDenied
from hippo.knowledge.lease_heartbeat import LeaseHeartbeat
from hippo.knowledge.query_access import query_session
from hippo.knowledge.replay import view_fingerprint
from tests.unit.test_lookup_snapshot_lifetime import live_refs, managed  # noqa: F401


@pytest.fixture
def owned(ctx, managed):  # noqa: F811
    generation, span, acquired, request = managed
    service = EvalAccess(ctx, request.state.principal.access)
    set_id = service.create_question_set("Manual")  # No evidence selection needed.
    question = ctx.store.add_questions(set_id, [{"text": "Question", "gold_passage_ids": [span.id]}])[0]
    run = ctx.store.create_run(set_id, "Run", {})
    result = ctx.store.add_result(run, question, {"answer": "stale answer"})
    assert not acquired and not live_refs(ctx)
    return service, generation, acquired, set_id, question, run, result


@pytest.mark.parametrize("operation", ["source", "set", "question", "run", "result", "require"])
def test_standalone_single_reads_release_exactly_one_snapshot(ctx, owned, operation):
    service, generation, acquired, set_id, question, run, result = owned
    calls = {
        "source": lambda: service.get_source(generation.source_id),
        "set": lambda: service.get_question_set(set_id),
        "question": lambda: service.get_question(question),
        "run": lambda: service.get_run(run),
        "result": lambda: service.get_result(result),
        "require": lambda: service.require_set(set_id),
    }
    assert calls[operation]() is not None
    assert len(acquired) == 1
    assert not live_refs(ctx)


@pytest.mark.parametrize("outcome", ["error", "revoke"])
def test_single_read_failure_keeps_proof_until_dto_and_releases(ctx, owned, monkeypatch, outcome):
    service, _, acquired, _, question, _, _ = owned
    original = ctx.store.get_question

    def load(identity):
        assert live_refs(ctx)
        row = original(identity)
        if outcome == "error":
            raise RuntimeError("question read failed")
        ctx.store._bump_authorization_epoch()
        return row

    monkeypatch.setattr(ctx.store, "get_question", load)
    with pytest.raises(RuntimeError if outcome == "error" else AuthorizationChanged):
        service.get_question(question)
    assert len(acquired) == 1
    assert not live_refs(ctx)


def test_graph_requires_explicit_scope_and_borrowed_graph_remains_owned(ctx, owned):
    service, _, acquired, *_ = owned
    with pytest.raises(RuntimeError, match="scope"):
        service.graph()
    assert not acquired
    with service.read_scope():
        graph = service.graph()
        assert graph is service.graph()
        assert live_refs(ctx)
    assert not live_refs(ctx)


@pytest.mark.parametrize("source_bound", [True, False])
def test_generated_create_uses_one_input_view_and_own_epoch_change_succeeds(
    ctx,
    managed,  # noqa: F811
    monkeypatch,
    source_bound,
):
    generation, _, acquired, request = managed
    service = EvalAccess(ctx, request.state.principal.access)
    epoch = ctx.store.authorization_epoch()
    expected = []
    original = ctx.store.create_question_set

    def create(*args, **kwargs):
        assert len(acquired) == 1 and live_refs(ctx)
        expected.append(view_fingerprint(acquired[0]))
        return original(*args, **kwargs)

    monkeypatch.setattr(ctx.store, "create_question_set", create)
    identity = service.create_question_set(
        "Generated", generation.source_id if source_bound else None, "generated"
    )
    assert len(acquired) == 1
    assert not live_refs(ctx)
    metadata = json.loads(ctx.store.get_meta("eval_owner:" + identity))
    assert metadata["evidence_fingerprint"] == expected[0]
    assert metadata["owner_id"] == request.state.principal.user_id
    assert ctx.store.authorization_epoch() == epoch + 1


def test_generated_creation_denies_prelock_revocation_without_writing(ctx, managed, monkeypatch):  # noqa: F811
    generation, _, acquired, request = managed
    original = eval_access.lock_authorization

    def lock(store):
        original(store)
        store._bump_authorization_epoch()

    monkeypatch.setattr(eval_access, "lock_authorization", lock)
    with pytest.raises(AuthorizationChanged):
        EvalAccess(ctx, request.state.principal.access).create_question_set(
            "Denied", generation.source_id, "generated"
        )
    assert ctx.store.list_question_sets() == []
    assert len(acquired) == 1
    assert not live_refs(ctx)


@pytest.mark.parametrize("fail", [False, True])
def test_creation_acquires_and_closes_outside_transaction_without_worker(ctx, managed, monkeypatch, fail):  # noqa: F811
    generation, _, _, request = managed
    transaction, graph_for, set_meta = ctx.store.transaction, ctx.graph_for, ctx.store.set_meta
    depth, closed = 0, []
    epoch = ctx.store.authorization_epoch()

    @contextmanager
    def tracked():
        nonlocal depth
        with transaction():
            depth += 1
            try:
                yield
            finally:
                depth -= 1

    def acquire(*args, **kwargs):
        assert depth == 0
        graph = graph_for(*args, **kwargs)
        close_snapshot = graph.close_snapshot

        def close():
            assert depth == 0
            closed.append(True)
            close_snapshot()

        graph.close_snapshot = close
        return graph

    def no_worker(*args):
        pytest.fail("Short creation must not start or join a worker")

    def metadata(key, value):
        if fail and key.startswith("eval_owner:"):
            raise RuntimeError("owner write failed")
        return set_meta(key, value)

    monkeypatch.setattr(ctx.store, "transaction", tracked)
    monkeypatch.setattr(ctx, "graph_for", acquire)
    monkeypatch.setattr(ctx.store, "set_meta", metadata)
    monkeypatch.setattr(LeaseHeartbeat, "start", no_worker)
    monkeypatch.setattr(LeaseHeartbeat, "close", no_worker)
    service = EvalAccess(ctx, request.state.principal.access)
    if fail:
        with pytest.raises(RuntimeError, match="owner write failed"):
            service.create_question_set("Generated", generation.source_id, "generated")
        assert ctx.store.authorization_epoch() == epoch
        assert ctx.store.list_question_sets() == []
    else:
        service.create_question_set("Generated", generation.source_id, "generated")
    assert closed == [True]
    assert not live_refs(ctx)


@pytest.mark.parametrize("operation", ["questions", "run"])
@pytest.mark.parametrize("borrowed", [False, True])
def test_non_epoch_writes_acquire_before_transaction_and_preserve_borrower(
    ctx, owned, monkeypatch, operation, borrowed
):
    service, _, acquired, set_id, *_ = owned
    transaction, graph_for = ctx.store.transaction, ctx.graph_for
    start, close = LeaseHeartbeat.start, LeaseHeartbeat.close
    depth = 0

    @contextmanager
    def tracked():
        nonlocal depth
        with transaction():
            depth += 1
            try:
                yield
            finally:
                depth -= 1

    def acquire(*args, **kwargs):
        assert depth == 0
        return graph_for(*args, **kwargs)

    def start_outside(self):
        assert depth == 0
        return start(self)

    def close_outside(self):
        assert depth == 0
        return close(self)

    def write():
        if operation == "questions":
            assert service.add_questions(set_id, [{"text": "Another"}])
        else:
            assert service.create_run(set_id, "Another", {})

    monkeypatch.setattr(ctx.store, "transaction", tracked)
    monkeypatch.setattr(ctx, "graph_for", acquire)
    monkeypatch.setattr(LeaseHeartbeat, "start", start_outside)
    monkeypatch.setattr(LeaseHeartbeat, "close", close_outside)
    if borrowed:
        with query_session(ctx, service.access) as session:
            service = EvalAccess(ctx, service.access, session=session)
            write()
            assert live_refs(ctx)
            session.validate()
    else:
        write()
    assert len(acquired) == 1
    assert not live_refs(ctx)


def test_creation_refuses_to_invalidate_callers_read_session(ctx, managed):  # noqa: F811
    generation, _, acquired, request = managed
    with query_session(ctx, request.state.principal.access) as session:
        service = EvalAccess(ctx, request.state.principal.access, session=session)
        with pytest.raises(RuntimeError, match="scope"):
            service.create_question_set("Generated", generation.source_id, "generated")
        session.validate()
        assert live_refs(ctx)
    assert len(acquired) == 1
    assert not live_refs(ctx)


def test_stale_generated_set_remains_deletable_without_graph_acquisition(ctx, managed, monkeypatch):  # noqa: F811
    generation, _, _, request = managed
    service = EvalAccess(ctx, request.state.principal.access)
    identity = service.create_question_set("Generated", generation.source_id, "generated")
    assert not live_refs(ctx)
    metadata = json.loads(ctx.store.get_meta("eval_owner:" + identity))
    metadata["evidence_fingerprint"] = "stale"
    ctx.store.set_meta("eval_owner:" + identity, json.dumps(metadata))
    with pytest.raises(EvalAccessDenied):
        service.require_generation_target(identity, generation.source_id)
    assert not live_refs(ctx)

    def no_graph(*args, **kwargs):
        pytest.fail("Deleting a stale owned set must not load its evidence")

    monkeypatch.setattr(ctx, "graph_for", no_graph)
    service.delete_question_set(identity)
    assert ctx.store.get_question_set(identity) is None


@pytest.mark.parametrize("operation", ["questions", "run"])
@pytest.mark.parametrize("failure", ["rollback", "revocation", "during_write"])
def test_non_epoch_write_failure_releases_pin_and_keeps_original_rows(
    ctx, owned, monkeypatch, operation, failure
):
    service, _, acquired, set_id, question, run, _ = owned
    if failure == "revocation":
        original = eval_access.lock_authorization

        def revoke(store):
            original(store)
            store._bump_authorization_epoch()

        monkeypatch.setattr(eval_access, "lock_authorization", revoke)
    else:
        method = "add_questions" if operation == "questions" else "create_run"
        original = getattr(ctx.store, method)

        def fail(*args, **kwargs):
            result = original(*args, **kwargs)
            if failure == "during_write":
                ctx.store._bump_authorization_epoch()
                return result
            raise RuntimeError("write failed")

        monkeypatch.setattr(ctx.store, method, fail)
    with pytest.raises(RuntimeError if failure == "rollback" else AuthorizationChanged):
        if operation == "questions":
            service.add_questions(set_id, [{"text": "Rejected"}])
        else:
            service.create_run(set_id, "Rejected", {})
    assert [row["id"] for row in ctx.store.list_questions(set_id)] == [question]
    assert [row["id"] for row in ctx.store.list_runs(set_id)] == [run]
    assert len(acquired) == 1
    assert not live_refs(ctx)
