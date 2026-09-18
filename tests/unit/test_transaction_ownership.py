"""An open store transaction belongs to the thread that opened it, not to the process.

Every store holds one lock for a whole transaction body, so the depth counter and driver
handle beside it read as "in a transaction" from every thread while any one thread is
inside one. Callers that must refuse to run inside *their own* transaction — the build
authority's external checks, the prose coordinator — ask `in_ambient_transaction()`
instead, which answers for the calling thread only.

The Neo4j store's enter/exit sites (`store/base.py`) cannot run here: these tests use the
shared `store` fixture, which only reaches Neo4j when a disposable database is configured.
Its method body is mirrored from the other two and is exercised against a stand-in self by
`test_the_neo4j_store_mirrors_the_same_ownership_answer`.
"""

from threading import Event, Thread, get_ident
from types import SimpleNamespace

import pytest

from tests.unit.test_build_authority import guard, world


def on_another_thread(work, timeout=10):
    """Run `work()` on a fresh thread; return its result or re-raise its error here.

    A helper thread must never leak an exception: under `-W error` an unhandled one
    becomes a `PytestUnhandledThreadExceptionWarning` and hides the real failure.
    """
    outcome = []

    def run():
        try:
            outcome.append(("value", work()))
        except BaseException as exc:  # noqa: BLE001 - re-raised on the calling thread below
            outcome.append(("error", exc))

    thread = Thread(target=run)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "helper thread did not finish"
    kind, result = outcome[0]
    if kind == "error":
        raise result
    return result


def test_only_the_thread_inside_the_transaction_reports_an_ambient_transaction(store):
    assert store.in_ambient_transaction() is False
    assert on_another_thread(store.in_ambient_transaction) is False
    with store.transaction():
        assert store.in_ambient_transaction() is True
        assert on_another_thread(store.in_ambient_transaction) is False
        with store.transaction():
            assert store.in_ambient_transaction() is True, "nesting keeps the outermost owner"
            assert on_another_thread(store.in_ambient_transaction) is False
        assert store.in_ambient_transaction() is True, "leaving a nested body keeps the owner"
        assert on_another_thread(store.in_ambient_transaction) is False
    assert store.in_ambient_transaction() is False
    assert on_another_thread(store.in_ambient_transaction) is False


def test_a_transaction_another_thread_holds_is_never_the_callers_transaction(store):
    """The probe must not take the store lock, or it would block behind the holder."""
    held, release = Event(), Event()
    seen, errors = [], []

    def hold():
        try:
            with store.transaction():
                seen.append(store.in_ambient_transaction())
                held.set()
                assert release.wait(10)
        except BaseException as exc:  # noqa: BLE001 - asserted on the calling thread below
            errors.append(exc)
        finally:
            held.set()

    thread = Thread(target=hold)
    thread.start()
    try:
        assert held.wait(10)
        assert store.in_ambient_transaction() is False
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and errors == []
    assert seen == [True]
    assert store.in_ambient_transaction() is False


@pytest.mark.parametrize("exit_path", ["commit", "exception", "nested_failure", "auto_abort"])
def test_every_transaction_exit_releases_the_threads_ownership(store, exit_path):
    if exit_path == "auto_abort" and store.knowledge_backend != "ladybug":
        pytest.skip("Only the Ladybug store recovers from a statement its driver auto-aborted")
    if exit_path == "commit":
        with store.transaction():
            assert store.in_ambient_transaction() is True
    elif exit_path == "exception":
        with pytest.raises(ValueError, match="transaction body failed"):
            with store.transaction():
                assert store.in_ambient_transaction() is True
                raise ValueError("transaction body failed")
    elif exit_path == "nested_failure":
        # The only route to the rollback branch without an exception in the outer body.
        with pytest.raises(RuntimeError, match="Nested transaction failed"):
            with store.transaction():
                with pytest.raises(ValueError, match="nested body failed"):
                    with store.transaction():
                        raise ValueError("nested body failed")
                assert store.in_ambient_transaction() is True
    else:
        store.run("CREATE (:Workspace {id:'ownership-duplicate', name:'first'})")
        # The driver aborts the transaction itself, so the store's own ROLLBACK also fails.
        with pytest.raises(RuntimeError, match="duplicated primary key"):
            with store.transaction():
                assert store.in_ambient_transaction() is True
                store.run("CREATE (:Workspace {id:'ownership-duplicate', name:'second'})")
    assert store.in_ambient_transaction() is False
    assert on_another_thread(store.in_ambient_transaction) is False


def test_build_authority_check_ignores_a_transaction_another_thread_owns(store):
    """The coordinator scenario: concurrent managed builds must not reject each other."""
    w = world(store)
    value = guard(w)
    started, errors = Event(), []

    def check():
        started.set()
        try:
            value.check()
        except BaseException as exc:  # noqa: BLE001 - asserted on the calling thread below
            errors.append(exc)

    thread = Thread(target=check)
    with store.transaction():
        thread.start()
        assert started.wait(10)
        # Grace only: with a process-global probe the check has already failed by now, while
        # a thread-owned one either finished or is parked on the store lock until we commit.
        thread.join(0.2)
    thread.join(10)
    assert not thread.is_alive() and errors == []
    value.check_local()


def test_build_authority_check_still_refuses_the_callers_own_transaction(store):
    w = world(store)
    value = guard(w)
    calls = []
    with store.transaction():
        assert store.in_ambient_transaction() is True
        with pytest.raises(RuntimeError, match="require no ambient transaction"):
            value.check(checkpoint=lambda: calls.append("called"))
    assert calls == []
    value.check_local()


def test_the_neo4j_store_mirrors_the_same_ownership_answer():
    """`base.py` has no Neo4j to open here, so its method answers for a stand-in self."""
    from hippo.store.base import Neo4jBase

    assert Neo4jBase.in_ambient_transaction(SimpleNamespace(_transaction_owner=None)) is False
    assert Neo4jBase.in_ambient_transaction(SimpleNamespace(_transaction_owner=get_ident())) is True
    assert Neo4jBase.in_ambient_transaction(SimpleNamespace(_transaction_owner=get_ident() + 1)) is False
