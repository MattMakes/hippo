"""
Index jobs versus deletes and re-indexes happening at the same time.

The dangerous moment is a job's write phase: entities and facts are written first and linked
to their passages afterwards, and `remove_orphans` (the tail of every delete/reindex) drops
whatever is unlinked. These tests pin down the three defences in ingest/pipeline.py:

* deleting a source cancels its own job and waits for it, and refuses (Busy) while another
  source's job runs;
* a job that finds its Source row gone at the end sweeps the orphans it left; a job that
  fails clears the passages it wrote;
* the write lock (hipporag/indexer.GRAPH_WRITE_LOCK) keeps a sweep from overlapping a write.
"""

from __future__ import annotations

import threading
import time

import pytest

from hippo.context import AppContext
from hippo.hipporag import indexer
from hippo.hipporag.indexer import GRAPH_WRITE_LOCK
from hippo.ingest import pipeline
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.source_lifecycle import tombstone_managed_source
from tests.unit import test_managed_pipeline_activation as managed

WAIT = 30  # seconds; generous so a slow CI box does not flake

# The managed fixture: an authenticated local reader, a mock model and a real coordinator.
setup = managed.setup


class Gate:
    """Lets a test hold the fact-extraction stage of an index job until it says go."""

    def __init__(self) -> None:
        self.armed = False
        self.started = threading.Event()  # a job reached the gate
        self.release = threading.Event()  # the test lets it through


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> Gate:
    gate = Gate()
    real = indexer.openie.extract_many

    def wait_at_gate(*args, **kwargs):
        if gate.armed:
            gate.started.set()
            assert gate.release.wait(WAIT), "the test never released the gate"
        return real(*args, **kwargs)

    monkeypatch.setattr(indexer.openie, "extract_many", wait_at_gate)
    return gate


def wait_until(condition, timeout: float = WAIT) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.01)


def counts(ctx: AppContext) -> tuple[int, int, int]:
    stats = ctx.store.stats()
    return stats["passages"], stats["entities"], stats["facts"]


# ---------------------------------------------------- delete vs own job


def test_deleting_a_source_cancels_its_running_job_and_leaves_nothing_behind(
    ctx, fake_ollama, gate: Gate
) -> None:
    gate.armed = True
    source_id = pipeline.add_sample(ctx)
    assert gate.started.wait(WAIT)
    key = f"index:{source_id}"

    deleter = threading.Thread(target=pipeline.delete_source, args=(ctx, source_id))
    deleter.start()
    wait_until(lambda: ctx.jobs.is_cancelled(key))  # delete asked the job to stop...
    assert ctx.store.get_source(source_id) is not None  # ...and is waiting for it before deleting
    gate.release.set()
    deleter.join(WAIT)
    ctx.jobs.wait_all(WAIT)

    assert ctx.store.get_source(source_id) is None
    assert counts(ctx) == (0, 0, 0)
    assert not pipeline.source_dir(ctx, source_id).exists()
    assert fake_ollama.calls == [], "the cancelled job must not spend LLM calls on a deleted source"
    assert len(ctx.graph().passages) == 0


def test_a_cancelled_job_ends_failed_cancelled_with_its_passages_cleared_and_can_be_reindexed(
    ctx, gate: Gate
) -> None:
    gate.armed = True
    source_id = pipeline.add_sample(ctx)
    assert gate.started.wait(WAIT)
    assert ctx.store.get_source(source_id)["passages"] == 8  # written before the gate

    assert ctx.jobs.cancel(f"index:{source_id}")
    gate.release.set()
    ctx.jobs.wait_all(WAIT)

    source = ctx.store.get_source(source_id)
    assert (source["status"], source["stage"]) == ("failed", "cancelled")
    assert "cancelled" in source["error"] and "Reindex" in source["error"]
    assert source["passages"] == 0, "half-written passages must not linger"

    gate.armed = False
    assert pipeline.reindex(ctx, source_id) is True
    ctx.jobs.wait_all(WAIT)
    assert ctx.store.get_source(source_id)["status"] == "ready"


def test_a_job_whose_source_row_vanished_sweeps_its_own_orphans(ctx, gate: Gate) -> None:
    """The row can disappear without the pipeline's cancel (a CLI, a delete that gave up waiting)."""
    gate.armed = True
    source_id = pipeline.add_sample(ctx)
    assert gate.started.wait(WAIT)
    ctx.store.delete_source(source_id)  # straight at the store: no cancel, no wait
    version = ctx.store.graph_version()

    gate.release.set()
    ctx.jobs.wait_all(WAIT)

    # Neo4j (and the fake) create entities/facts without a Source; the job must notice and sweep them.
    assert counts(ctx) == (0, 0, 0)
    assert ctx.store.graph_version() > version
    assert len(ctx.graph().passages) == 0 and len(ctx.graph().facts) == 0


def test_a_failed_job_clears_the_passages_it_wrote(ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    private = "model fell over reading /Users/someone/private/notes.md"

    def explode(*args, **kwargs):
        raise RuntimeError(private)

    monkeypatch.setattr(indexer.openie, "extract_many", explode)
    source_id = pipeline.add_sample(ctx)
    ctx.jobs.wait_all(WAIT)
    source = ctx.store.get_source(source_id)
    # The row is a public surface: the class an operator greps by, and nothing it was reading.
    assert source["status"] == "failed"
    assert source["error"] == "RuntimeError: indexing failed; inspect local logs"
    assert private not in source["error"]
    assert source["passages"] == 0
    assert counts(ctx) == (0, 0, 0)


# -------------------------------------------------- delete vs other jobs


def test_delete_and_reindex_refuse_while_another_source_is_being_indexed(ctx, gate: Gate) -> None:
    other = pipeline.add_text(ctx, "other", "Zed Corp is located in Austin.")
    ctx.jobs.wait_all(WAIT)
    entities_before = ctx.store.stats()["entities"]

    gate.armed = True
    busy_one = pipeline.add_sample(ctx)
    assert gate.started.wait(WAIT)

    with pytest.raises(pipeline.Busy, match="wait for indexing to finish"):
        pipeline.delete_source(ctx, other)
    with pytest.raises(pipeline.Busy):
        pipeline.reindex(ctx, other)
    with pytest.raises(pipeline.Busy):
        pipeline.reindex_all(ctx)
    # Nothing was touched: no orphan sweep ran while the other job was between its writes.
    assert ctx.store.get_source(other)["passages"] == 1
    assert ctx.store.stats()["entities"] == entities_before
    assert ctx.store.get_source(busy_one)["status"] == "indexing"

    gate.release.set()
    ctx.jobs.wait_all(WAIT)
    assert ctx.store.get_source(busy_one)["status"] == "ready"
    pipeline.delete_source(ctx, other)  # allowed again once nothing is indexing
    assert ctx.store.get_source(other) is None


def test_busy_is_a_value_error_so_existing_handlers_still_catch_it() -> None:
    assert issubclass(pipeline.Busy, ValueError)


# ------------------------------------------------------------- the lock


def test_deletes_wait_for_the_graph_write_lock(ctx) -> None:
    """While an index job holds the lock (its write phase), a delete's orphan sweep must wait."""
    source_id = pipeline.add_text(ctx, "note", "Zed Corp is located in Austin.")
    ctx.jobs.wait_all(WAIT)
    finished = threading.Event()

    def delete_then_signal() -> None:
        pipeline.delete_source(ctx, source_id)
        finished.set()

    with GRAPH_WRITE_LOCK:  # stand in for a job in its write phase
        deleter = threading.Thread(target=delete_then_signal)
        deleter.start()
        assert not finished.wait(0.3), "delete must block while the lock is held"
        assert ctx.store.get_source(source_id) is not None
    assert finished.wait(WAIT)
    assert ctx.store.get_source(source_id) is None


def test_reindex_waits_for_the_graph_write_lock(ctx) -> None:
    source_id = pipeline.add_text(ctx, "note", "Zed Corp is located in Austin.")
    ctx.jobs.wait_all(WAIT)
    cleared = threading.Event()

    def clear_then_signal() -> None:
        pipeline._clear_passages(ctx, source_id)
        cleared.set()

    with GRAPH_WRITE_LOCK:
        threading.Thread(target=clear_then_signal).start()
        assert not cleared.wait(0.3)
        assert ctx.store.get_source(source_id)["passages"] == 1
    assert cleared.wait(WAIT)
    assert ctx.store.get_source(source_id)["passages"] == 0


# ------------------------------------------------ a managed delete vs jobs


def test_a_managed_delete_suppresses_while_another_source_is_being_indexed(setup, monkeypatch) -> None:
    """The Busy precondition guards an orphan sweep; a tombstone sweeps nothing.

    The legacy delete of another source still refuses, which is the behaviour the
    precondition exists for.
    """
    w = setup
    source = managed.managed_source(w)
    legacy = managed.legacy_source(w, monkeypatch)
    release = threading.Event()
    assert w.ctx.jobs.start("index:someone-else", lambda: release.wait(WAIT))
    try:
        with pytest.raises(pipeline.Busy):
            pipeline.delete_source(w.ctx, legacy)
        pipeline.delete_source(w.ctx, source, build_actor=w.actor)
    finally:
        release.set()
        w.ctx.jobs.wait_all(WAIT)
    assert managed.row_of(w, source)["stage"] == "tombstoned"
    assert w.store.get_source(legacy) is not None  # the refused delete changed nothing


def test_a_managed_delete_does_not_wait_for_its_own_blocked_build(setup) -> None:
    w = setup
    source = managed.managed_source(w)
    blocked, finish = threading.Event(), threading.Event()

    def hook(path, body):
        if path == "/api/chat":
            blocked.set()
            assert finish.wait(WAIT), "the test never released the blocked model call"

    (pipeline.source_dir(w.ctx, source) / "text.md").write_text(managed.SECOND_TEXT)
    w.runtime.hook = hook
    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True
    assert blocked.wait(WAIT)

    started = time.monotonic()
    pipeline.delete_source(w.ctx, source, build_actor=w.actor)
    assert time.monotonic() - started < 5, "delete waited for a blocked model call before suppressing"
    assert w.ctx.jobs.is_cancelled(pipeline.job_key(source))
    tombstoned = managed.row_of(w, source)
    assert (tombstoned["status"], tombstoned["stage"]) == ("deleted", "tombstoned")

    finish.set()
    w.ctx.jobs.wait_all(WAIT)
    assert managed.row_of(w, source) == tombstoned  # the late worker never overwrites it


# -------------------------------------- bulk races between plan and worker


def test_a_source_tombstoned_between_the_bulk_preflight_and_its_worker_skips_that_lane(
    setup, monkeypatch
) -> None:
    w = setup
    first = managed.managed_source(w, managed.FIRST_TEXT, "First")
    second = managed.managed_source(w, managed.SECOND_TEXT, "Second")
    held = w.held_jobs()
    seen, prepared = managed.bulk_lanes(monkeypatch)

    assert pipeline.reindex_all(w.ctx, build_actor=w.actor) == 2
    tombstone_managed_source(
        w.ctx, source_id=first, actor=BuildActor.trusted_local(), operation_id="delete.1"
    )
    before = managed.row_of(w, first)
    for _, work in held:
        work()

    assert [entry["source"] for entry in seen] == [second]
    assert prepared == [] and managed.row_of(w, first) == before


def test_an_actor_disabled_between_the_bulk_preflight_and_its_worker_fails_only_that_lane(
    setup, monkeypatch
) -> None:
    w = setup
    first = managed.managed_source(w, managed.FIRST_TEXT, "First")
    second = managed.managed_source(w, managed.SECOND_TEXT, "Second")
    # Rewritten so neither refresh can finish early as `already_current`.
    for source, text in ((first, managed.THIRD_TEXT), (second, managed.THIRD_TEXT + " Austin too.")):
        (pipeline.source_dir(w.ctx, source) / "text.md").write_text(text)
    generations = {source: managed.row_of(w, source)["active_generation_id"] for source in (first, second)}
    held = w.held_jobs()
    prepared: list[str] = []
    monkeypatch.setattr(pipeline, "_prepare_reindex", lambda ctx, source_id: prepared.append(source_id))
    monkeypatch.setattr(
        pipeline, "_read_chunk_index", lambda *a, **k: pytest.fail("a managed lane fell back to legacy")
    )

    assert pipeline.reindex_all(w.ctx, build_actor=w.actor) == 2
    work = dict(held)
    w.store.update_user(w.user, disabled=True)
    work[pipeline.job_key(first)]()
    w.store.update_user(w.user, disabled=False)
    work[pipeline.job_key(second)]()

    raced = managed.row_of(w, first)
    assert (raced["status"], raced["stage"]) == ("ready", "refresh_failed")
    assert raced["error"].startswith("authorization_changed: ")
    assert raced["active_generation_id"] == generations[first]
    assert managed.row_of(w, second)["active_generation_id"] != generations[second]
    assert prepared == []
