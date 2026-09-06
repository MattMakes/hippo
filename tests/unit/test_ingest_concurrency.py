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

WAIT = 30  # seconds; generous so a slow CI box does not flake


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
    def explode(*args, **kwargs):
        raise RuntimeError("model fell over")

    monkeypatch.setattr(indexer.openie, "extract_many", explode)
    source_id = pipeline.add_sample(ctx)
    ctx.jobs.wait_all(WAIT)
    source = ctx.store.get_source(source_id)
    assert source["status"] == "failed" and "model fell over" in source["error"]
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
