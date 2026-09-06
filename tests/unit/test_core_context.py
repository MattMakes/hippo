"""
hippo/context.py: AppContext.graph() reloads the in-memory graph when the store's version moves.

The two things that matter when several threads call it at once:

* a graph is never labelled with a version older than the data it was loaded from
  (a stale label causes a needless full reload on the next call)
* readers keep working on the previous graph while one thread loads the new one
"""

from __future__ import annotations

import threading
import time

import pytest

from hippo.context import AppContext
from hippo.hipporag.graph_index import GraphIndex


def record_loads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Make GraphIndex.load append the version it was asked for to the returned list."""
    loads: list[int] = []
    real_load = GraphIndex.load

    def counting_load(cls, store, version=None):
        loads.append(version)
        return real_load(store, version=version)

    monkeypatch.setattr(GraphIndex, "load", classmethod(counting_load))
    return loads


def slow_loads(monkeypatch: pytest.MonkeyPatch) -> tuple[threading.Event, threading.Event]:
    """Make GraphIndex.load block: it sets `loading` when entered and waits for `finish`."""
    loading, finish = threading.Event(), threading.Event()
    real_load = GraphIndex.load

    def slow_load(cls, store, version=None):
        loading.set()
        assert finish.wait(5), "the test forgot to let the load finish"
        return real_load(store, version=version)

    monkeypatch.setattr(GraphIndex, "load", classmethod(slow_load))
    return loading, finish


def in_a_thread(fn, name: str = "worker") -> threading.Thread:
    thread = threading.Thread(target=fn, name=name)
    thread.start()
    return thread


def test_graph_is_loaded_once_and_reloaded_when_the_version_moves(ctx: AppContext, monkeypatch) -> None:
    loads = record_loads(monkeypatch)
    first = ctx.graph()
    assert ctx.graph() is first
    assert loads == [ctx.store.graph_version()]

    ctx.store.bump_graph_version()
    second = ctx.graph()
    assert second is not first
    assert second.version == ctx.store.graph_version()
    assert loads == [second.version - 1, second.version]


def test_a_slow_version_read_never_labels_the_graph_with_a_stale_version(
    ctx: AppContext, monkeypatch
) -> None:
    store = ctx.store
    ctx.graph()
    loads = record_loads(monkeypatch)
    real_read = store.graph_version
    slow_is_reading, let_slow_go = threading.Event(), threading.Event()

    def graph_version() -> int:
        version = real_read()
        if threading.current_thread().name == "slow":
            # The "slow" thread has read the version but is not done comparing it yet...
            slow_is_reading.set()
            assert let_slow_go.wait(5)
        return version

    monkeypatch.setattr(store, "graph_version", graph_version)

    slow = in_a_thread(ctx.graph, name="slow")
    assert slow_is_reading.wait(5)
    store.bump_graph_version()  # ...when an index job finishes...
    fast = in_a_thread(ctx.graph, name="fast")  # ...and another request comes in.
    let_slow_go.set()
    slow.join(5)
    fast.join(5)

    # The cached graph must carry the store's version (not the slow thread's old one), and the new
    # version must have been loaded exactly once: no reload by the slow thread, none on the next call.
    assert ctx._graph is not None and ctx._graph.version == store.graph_version()
    assert ctx.graph().version == store.graph_version()
    assert loads == [store.graph_version()]


def test_readers_keep_the_previous_graph_while_another_thread_reloads(ctx: AppContext, monkeypatch) -> None:
    previous = ctx.graph()
    loading, finish = slow_loads(monkeypatch)
    ctx.store.bump_graph_version()

    loader = in_a_thread(ctx.graph, name="loader")
    assert loading.wait(5)
    seen: list[GraphIndex] = []
    reader = in_a_thread(lambda: seen.append(ctx.graph()), name="reader")
    reader.join(2)

    assert not reader.is_alive(), "a reader must not wait for the reload"
    assert seen == [previous]  # the old graph, clearly labelled with its old version
    assert previous.version != ctx.store.graph_version()

    finish.set()
    loader.join(5)
    assert ctx.graph().version == ctx.store.graph_version()


def test_only_one_thread_loads_when_many_ask_at_once(ctx: AppContext, monkeypatch) -> None:
    ctx.graph()
    loads = record_loads(monkeypatch)
    loading, finish = slow_loads(monkeypatch)
    ctx.store.bump_graph_version()

    threads = [in_a_thread(ctx.graph, name=f"asker-{i}") for i in range(6)]
    assert loading.wait(5)
    time.sleep(0.05)  # give every thread a chance to arrive while the load is in progress
    finish.set()
    for thread in threads:
        thread.join(5)

    assert loads == [ctx.store.graph_version()]
    assert ctx.graph().version == ctx.store.graph_version()


def test_with_nothing_cached_every_caller_waits_for_the_one_load(ctx: AppContext, monkeypatch) -> None:
    # After invalidate_graph() there is no previous graph to fall back on, so callers must wait
    # rather than get None - and still only one of them loads.
    ctx.graph()
    ctx.invalidate_graph()
    loads = record_loads(monkeypatch)
    loading, finish = slow_loads(monkeypatch)
    results: list[GraphIndex] = []

    threads = [in_a_thread(lambda: results.append(ctx.graph()), name=f"waiter-{i}") for i in range(4)]
    assert loading.wait(5)
    finish.set()
    for thread in threads:
        thread.join(5)

    assert len(results) == 4
    assert {g.version for g in results} == {ctx.store.graph_version()}
    assert loads == [ctx.store.graph_version()]
