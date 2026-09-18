"""A request renews its lease while model work is blocked, then joins its worker."""

from threading import Event, Thread, current_thread

import pytest

from hippo.access import EVERYTHING
from hippo.knowledge.access import AuthorizationChanged
from tests.unit.test_query_snapshots import build


def test_heartbeat_renews_and_stops_before_close_returns():
    from hippo.knowledge.lease_heartbeat import LeaseHeartbeat

    entered, finish = Event(), Event()
    calls = []

    def renew():
        calls.append(current_thread())
        entered.set()
        assert finish.wait(5)

    heartbeat = LeaseHeartbeat(renew, interval=0.001)
    heartbeat.start()
    try:
        assert entered.wait(5)
        closed = Event()
        closer = Thread(target=lambda: (heartbeat.close(), closed.set()))
        closer.start()
        assert not closed.is_set()
    finally:
        finish.set()
        heartbeat.close()
    closer.join(5)
    assert closed.is_set()
    assert len(calls) == 1
    assert not calls[0].is_alive()


def test_heartbeat_failure_is_sticky_and_cannot_restart():
    from hippo.knowledge.lease_heartbeat import LeaseHeartbeat

    failed = Event()

    def fail():
        failed.set()
        raise ValueError("lost lease")

    heartbeat = LeaseHeartbeat(fail, interval=0.001)
    heartbeat.start()
    assert failed.wait(5)
    heartbeat.close()
    with pytest.raises(AuthorizationChanged, match="renewal"):
        heartbeat.check()
    with pytest.raises(RuntimeError):
        heartbeat.start()


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan"), True])
def test_invalid_renewal_interval_fails_before_start(interval):
    from hippo.knowledge.lease_heartbeat import LeaseHeartbeat

    with pytest.raises(ValueError):
        LeaseHeartbeat(lambda: None, interval=interval)


def test_managed_session_renews_while_foreground_is_blocked(ctx, monkeypatch):
    from hippo.knowledge.query_access import query_session

    build(ctx)
    renewed = Event()
    workers = []
    foreground = current_thread()
    original = ctx.store.renew_snapshot_reference
    graph_for = ctx.graph_for

    def acquire(*args, **kwargs):
        graph = graph_for(*args, **kwargs)
        graph.snapshot_renewal_interval = 0.001
        return graph

    def renew(*args, **kwargs):
        result = original(*args, **kwargs)
        if current_thread() is not foreground:
            workers.append(current_thread())
            renewed.set()
        return result

    monkeypatch.setattr(ctx, "graph_for", acquire)
    monkeypatch.setattr(ctx.store, "renew_snapshot_reference", renew)
    with query_session(ctx, EVERYTHING) as session:
        assert renewed.wait(5), "No renewal occurred while the foreground waited"
        session.validate()
    assert workers and all(not worker.is_alive() for worker in workers)
    assert all(row.released_at for row in ctx.store._knowledge_rows("SnapshotReference"))


def test_model_call_crosses_original_expiry_without_losing_generation(ctx, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from hippo import ask
    from hippo.knowledge import snapshots

    generation, span = build(ctx, text="first revision.")
    initial = datetime.now(UTC)
    clock = [initial]
    renewed = Event()
    original_acquire = snapshots.acquire_query_snapshots
    original_renew = ctx.store.renew_snapshot_reference
    graph_for = ctx.graph_for
    foreground = current_thread()

    def acquire(*args, **kwargs):
        return original_acquire(*args, **kwargs, clock=lambda: clock[0], lease_duration=timedelta(seconds=9))

    def graph(*args, **kwargs):
        result = graph_for(*args, **kwargs)
        result.snapshot_renewal_interval = 0.001
        return result

    def renew(*args, **kwargs):
        result = original_renew(*args, **kwargs)
        if current_thread() is not foreground and result.lease_expires_at > initial + timedelta(seconds=9):
            renewed.set()
        return result

    def model(*args, **kwargs):
        clock[0] = initial + timedelta(seconds=8)
        assert renewed.wait(5)
        clock[0] = initial + timedelta(seconds=10)
        build(ctx, parent=generation, text="second revision.")
        assert ctx.store.collect_generation(generation.id).blocked_reason == "snapshot_reference"
        return [1.0, 0.0]

    monkeypatch.setattr(ctx.store, "_now", lambda: clock[0])
    monkeypatch.setattr(snapshots, "acquire_query_snapshots", acquire)
    monkeypatch.setattr(ctx, "graph_for", graph)
    monkeypatch.setattr(ctx.store, "renew_snapshot_reference", renew)
    monkeypatch.setattr(ctx.ollama, "embed_one", model)
    trace, answer = ask.ask(ctx, "What was the first revision?", access=EVERYTHING)
    assert answer.passage_ids == [span.id]
    assert trace.snapshot_ids
    assert all(row.released_at for row in ctx.store._knowledge_rows("SnapshotReference"))


def test_failed_background_renewal_denies_output_and_releases_references(ctx, monkeypatch):
    from hippo import ask

    build(ctx)
    failed = Event()
    workers = []
    foreground = current_thread()
    original = ctx.store.renew_snapshot_reference
    graph_for = ctx.graph_for

    def acquire(*args, **kwargs):
        graph = graph_for(*args, **kwargs)
        graph.snapshot_renewal_interval = 0.001
        return graph

    def renew(*args, **kwargs):
        if current_thread() is not foreground:
            workers.append(current_thread())
            failed.set()
            raise ValueError("renewal unavailable")
        return original(*args, **kwargs)

    def model(*args, **kwargs):
        assert failed.wait(5)
        workers[0].join(5)
        return [1.0, 0.0]

    monkeypatch.setattr(ctx, "graph_for", acquire)
    monkeypatch.setattr(ctx.store, "renew_snapshot_reference", renew)
    monkeypatch.setattr(ctx.ollama, "embed_one", model)
    with pytest.raises(AuthorizationChanged, match="renewal"):
        ask.ask(ctx, "revision", access=EVERYTHING)
    assert all(row.released_at for row in ctx.store._knowledge_rows("SnapshotReference"))
    assert all(not worker.is_alive() for worker in workers)


def test_thread_start_failure_releases_acquired_snapshot(ctx, monkeypatch):
    from hippo.knowledge import lease_heartbeat
    from hippo.knowledge.query_access import query_session

    build(ctx)

    def fail(*args, **kwargs):
        raise RuntimeError("thread unavailable")

    monkeypatch.setattr(lease_heartbeat.Thread, "start", fail)
    with pytest.raises(RuntimeError, match="thread unavailable"):
        with query_session(ctx, EVERYTHING):
            pytest.fail("An unrenewed session must not be handed to the caller")
    assert all(row.released_at for row in ctx.store._knowledge_rows("SnapshotReference"))


def test_start_error_after_worker_begins_still_joins_active_renewal(monkeypatch):
    from hippo.knowledge.lease_heartbeat import LeaseHeartbeat

    entered, finish, closed = Event(), Event(), Event()
    workers = []
    original = Thread.start

    def renew():
        workers.append(current_thread())
        entered.set()
        assert finish.wait(5)

    def start(thread):
        original(thread)
        assert entered.wait(5)
        raise RuntimeError("startup interrupted after thread began")

    heartbeat = LeaseHeartbeat(renew, interval=0.001)
    monkeypatch.setattr(Thread, "start", start)
    try:
        with pytest.raises(RuntimeError, match="startup interrupted"):
            heartbeat.start()
        closer = Thread(target=lambda: (heartbeat.close(), closed.set()))
        original(closer)
        assert not closed.is_set()
    finally:
        finish.set()
        heartbeat.close()
    closer.join(5)
    assert closed.is_set()
    assert workers and all(not worker.is_alive() for worker in workers)
