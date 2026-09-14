"""
A LadybugDB store recycles its driver connection before the driver's per-statement memory grows large.

real_ladybug 0.15.3 prepares a fresh statement for every `Connection.execute(query, parameters)`
and keeps it, with a copy of its parameters, until the connection closes. `gc.collect()` frees
none of it and `Connection.close()` frees most of it. A store that kept one connection for its whole
life grew without bound in a long build or a long-running server. These tests check that the store
swaps in a new connection on the same database once enough parameterised statements have run, only
at a safe boundary (never inside a transaction, never while a result is open, always under the
store's lock), that nothing a caller can see changes across a swap, and that the swap bounds the
process footprint.

They open real Ladybug files under `tmp_path` whatever HIPPO_TEST_STORE says.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time

import pytest
import real_ladybug

from hippo.config import Config, load_config
from hippo.knowledge.lease_heartbeat import LeaseHeartbeat
from hippo.store import ladybug, migrations, open_store
from hippo.store.ladybug import LadybugStore

MiB = 2**20
SETTING = "HIPPO_LADYBUG_CONNECTION_RECYCLE_STATEMENTS"


@pytest.fixture
def connections(monkeypatch):
    """Every `real_ladybug.Connection` opened from here on, still real, with its opens and closes in order."""
    events: list[tuple[str, object]] = []
    real = real_ladybug.Connection

    class Recording(real):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            events.append(("open", self))

        def close(self):
            if not self.is_closed:
                events.append(("close", self))
            super().close()

    monkeypatch.setattr(real_ladybug, "Connection", Recording)
    return events


def closes(events) -> list[object]:
    return [connection for kind, connection in events if kind == "close"]


def open_recycling(tmp_path, statements: int, name: str = "hippo.lbug") -> LadybugStore:
    store = LadybugStore(tmp_path / name, connection_recycle_statements=statements)
    store.run("CREATE NODE TABLE IF NOT EXISTS RecycleItem(id STRING, n INT64, PRIMARY KEY(id))")
    return store


def settle(store: LadybugStore) -> int:
    """Run parameterised statements until the store recycles, so the next count starts from zero."""
    recycles = store.connection_recycles
    for k in range(store.connection_recycle_statements + 1):
        store.run("RETURN $k AS k", k=k)
        if store.connection_recycles > recycles:
            return store.connection_recycles
    raise AssertionError("the store never recycled its connection")


def count_items(store: LadybugStore) -> int:
    return store.run("MATCH (i:RecycleItem) RETURN count(i) AS n")[0]["n"]


# ------------------------------------------------------------------ the setting


def test_the_setting_is_a_statement_count_and_unset_means_the_default(monkeypatch):
    monkeypatch.delenv(SETTING, raising=False)
    assert load_config().ladybug_connection_recycle_statements is None
    monkeypatch.setenv(SETTING, "1500")
    assert load_config().ladybug_connection_recycle_statements == 1500


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "lots", "1e3", " "])
def test_the_setting_refuses_anything_but_a_positive_whole_number(monkeypatch, value):
    monkeypatch.setenv(SETTING, value)
    with pytest.raises(ValueError, match=SETTING):
        load_config()


@pytest.mark.parametrize("statements", [0, -1])
def test_a_zero_or_negative_threshold_is_refused_before_the_file_is_touched(tmp_path, statements):
    path = tmp_path / "nested" / "hippo.lbug"
    with pytest.raises(ValueError, match="positive number of statements"):
        LadybugStore(path, connection_recycle_statements=statements)
    assert not path.parent.exists()


def test_open_store_passes_the_configured_threshold(tmp_path):
    store = open_store(Config(data_dir=tmp_path / "data", ladybug_connection_recycle_statements=321))
    try:
        assert store.connection_recycle_statements == 321
    finally:
        store.close()


def test_a_store_opened_without_a_threshold_takes_the_default(tmp_path):
    store = LadybugStore(tmp_path / "hippo.lbug")
    try:
        assert store.connection_recycle_statements == ladybug.DEFAULT_CONNECTION_RECYCLE_STATEMENTS
    finally:
        store.close()


def test_the_default_keeps_the_retained_statements_within_256_mib():
    budget = ladybug.DEFAULT_CONNECTION_RECYCLE_STATEMENTS * ladybug.STATEMENT_RETAINED_BYTES
    assert 128 * MiB < budget <= 256 * MiB


# ------------------------------------------------------------------ when a recycle happens


def test_the_connection_is_recycled_once_the_parameterised_statements_reach_the_threshold(
    tmp_path, connections
):
    store = open_recycling(tmp_path, statements=3)
    try:
        recycles = settle(store)
        stale = store._conn
        store.run("RETURN $k AS k", k=1)
        store.run("RETURN $k AS k", k=2)
        assert (store.connection_recycles, store._conn) == (recycles, stale)
        store.run("RETURN $k AS k", k=3)
        assert store.connection_recycles == recycles + 1
        assert closes(connections)[-1] is stale and stale.is_closed
        assert store._conn is not stale and not store._conn.is_closed
        assert store._conn.database is store._db
    finally:
        store.close()


def test_statements_without_parameters_never_bring_a_recycle_closer(tmp_path, connections):
    store = open_recycling(tmp_path, statements=2)
    try:
        recycles = settle(store)
        closed = len(closes(connections))
        for k in range(20):
            store.run(f"RETURN {k} AS k")
        assert store.connection_recycles == recycles
        assert len(closes(connections)) == closed
    finally:
        store.close()


def test_a_statement_with_large_parameters_counts_as_more_than_one(tmp_path):
    store = open_recycling(tmp_path, statements=10)
    try:
        recycles = settle(store)
        # About 125 bytes a list element stay behind in the driver: 10,000 of them outweigh ten plain statements.
        assert store.run("RETURN size($ids) AS n", ids=list(range(10_000))) == [{"n": 10_000}]
        assert store.connection_recycles == recycles + 1
    finally:
        store.close()


def test_a_recycle_changes_nothing_a_caller_can_see(tmp_path, monkeypatch):
    store = open_recycling(tmp_path, statements=4)
    try:
        for n in range(6):
            store.run("CREATE (:RecycleItem {id: $id, n: $n})", id=f"item-{n}", n=n)
        database, pool = store._db, store._db.buffer_pool_size
        read = "MATCH (i:RecycleItem) WHERE i.n >= $low RETURN i.id AS id, i.n AS n ORDER BY i.n"
        before = store.run(read, low=0)
        migrated = []
        monkeypatch.setattr(migrations, "migrate_store", lambda s: migrated.append(s))
        recycles = store.connection_recycles
        for _ in range(3):
            settle(store)
        assert store.connection_recycles >= recycles + 3
        assert store.run(read, low=0) == before
        assert store._db is database and store._db.buffer_pool_size == pool
        assert migrated == []
    finally:
        store.close()


# ------------------------------------------------------------------ safe boundaries


def test_a_recycle_due_inside_a_transaction_waits_until_it_commits(tmp_path, connections):
    store = open_recycling(tmp_path, statements=2)
    try:
        recycles = settle(store)
        closed = len(closes(connections))
        with store.transaction():
            for n in range(5):
                store.run("CREATE (:RecycleItem {id: $id, n: $n})", id=f"item-{n}", n=n)
            assert store.connection_recycles == recycles
            assert len(closes(connections)) == closed
        assert store.connection_recycles == recycles + 1
        assert len(closes(connections)) == closed + 1
        assert count_items(store) == 5
    finally:
        store.close()


def test_a_recycle_due_inside_a_transaction_waits_until_it_rolls_back(tmp_path, connections):
    store = open_recycling(tmp_path, statements=2)
    try:
        recycles = settle(store)
        closed = len(closes(connections))
        with pytest.raises(KeyError), store.transaction():
            for n in range(5):
                store.run("CREATE (:RecycleItem {id: $id, n: $n})", id=f"item-{n}", n=n)
            assert len(closes(connections)) == closed
            raise KeyError("abandon the transaction")
        assert store.connection_recycles == recycles + 1
        assert count_items(store) == 0
    finally:
        store.close()


def test_a_nested_transaction_leaves_the_recycle_to_the_outer_one(tmp_path, connections):
    store = open_recycling(tmp_path, statements=2)
    try:
        recycles = settle(store)
        closed = len(closes(connections))
        with store.transaction():
            with store.transaction():
                for n in range(3):
                    store.run("CREATE (:RecycleItem {id: $id, n: $n})", id=f"item-{n}", n=n)
            assert store.connection_recycles == recycles
            assert len(closes(connections)) == closed
            store.run("CREATE (:RecycleItem {id: $id, n: $n})", id="item-outer", n=9)
        assert store.connection_recycles == recycles + 1
        assert count_items(store) == 4
    finally:
        store.close()


def test_a_due_recycle_waits_for_an_open_query_result(tmp_path, connections, monkeypatch):
    store = open_recycling(tmp_path, statements=1)
    try:
        for n in range(3):
            store.run("CREATE (:RecycleItem {id: $id, n: $n})", id=f"item-{n}", n=n)
        settle(store)
        stale = store._conn
        reading, release = threading.Event(), threading.Event()
        order: list[str] = []
        real_next, real_close = real_ladybug.QueryResult.get_next, real_ladybug.QueryResult.close

        def gated_next(result):
            if threading.current_thread().name == "reader" and not reading.is_set():
                reading.set()
                assert release.wait(10), "the test never released the reader"
            return real_next(result)

        def recorded_close(result):
            if threading.current_thread().name == "reader" and not result.is_closed:
                order.append("result closed")
            real_close(result)

        monkeypatch.setattr(real_ladybug.QueryResult, "get_next", gated_next)
        monkeypatch.setattr(real_ladybug.QueryResult, "close", recorded_close)
        rows, errors = [], []

        def read():
            try:
                rows.extend(
                    store.run("MATCH (i:RecycleItem) WHERE i.n >= $low RETURN i.n AS n ORDER BY i.n", low=0)
                )
            except BaseException as error:  # noqa: BLE001 - reported by the assertion below
                errors.append(error)

        def write():
            try:
                store.run("CREATE (:RecycleItem {id: $id, n: $n})", id="item-writer", n=7)
            except BaseException as error:  # noqa: BLE001 - reported by the assertion below
                errors.append(error)

        reader = threading.Thread(target=read, name="reader")
        writer = threading.Thread(target=write, name="writer")
        reader.start()
        assert reading.wait(10)
        writer.start()
        time.sleep(0.2)
        assert writer.is_alive(), "another thread ran a statement while a result was open"
        assert not stale.is_closed and stale not in closes(connections)
        release.set()
        reader.join(10)
        writer.join(10)
        assert errors == []
        assert [row["n"] for row in rows] == [0, 1, 2]
        assert stale.is_closed
        order.append("connection closed")
        assert order == ["result closed", "connection closed"]
        assert count_items(store) == 4
    finally:
        store.close()


def test_a_lease_heartbeat_and_a_writer_never_meet_a_closed_connection(tmp_path):
    store = open_recycling(tmp_path, statements=4)
    try:
        store.run("CREATE NODE TABLE RecycleLease(id STRING, renewals INT64, PRIMARY KEY(id))")
        store.run("CREATE (:RecycleLease {id: $id, renewals: 0})", id="lease")
        renewals = []

        def renew():
            with store.transaction():
                store.run(
                    "MATCH (l:RecycleLease {id: $id}) SET l.renewals = l.renewals + $one", id="lease", one=1
                )
            renewals.append(1)

        heartbeat = LeaseHeartbeat(renew, interval=0.001)
        heartbeat.start()
        recycles = store.connection_recycles
        try:
            for n in range(300):
                with store.transaction():
                    store.run("CREATE (:RecycleItem {id: $id, n: $n})", id=f"item-{n}", n=n)
                    assert store.run("MATCH (i:RecycleItem {id: $id}) RETURN i.n AS n", id=f"item-{n}") == [
                        {"n": n}
                    ]
                store.run("MATCH (i:RecycleItem {id: $id}) SET i.n = i.n + $zero", id=f"item-{n}", zero=0)
        finally:
            heartbeat.close()
        heartbeat.check()
        assert renewals
        assert store.run("MATCH (l:RecycleLease {id: $id}) RETURN l.renewals AS n", id="lease") == [
            {"n": len(renewals)}
        ]
        assert count_items(store) == 300
        assert store.connection_recycles >= recycles + 100
    finally:
        store.close()


# ------------------------------------------------------------------ closing and failures


def test_a_recycled_store_closes_cleanly_and_reopens_with_its_data(tmp_path):
    store = open_recycling(tmp_path, statements=2)
    for n in range(7):
        store.run("CREATE (:RecycleItem {id: $id, n: $n})", id=f"item-{n}", n=n)
    assert store.connection_recycles > 0
    store.close()
    reopened = LadybugStore(tmp_path / "hippo.lbug")
    try:
        assert count_items(reopened) == 7
    finally:
        reopened.close()


def test_a_failed_reopen_keeps_the_open_connection_and_tries_again(tmp_path, monkeypatch, caplog):
    store = open_recycling(tmp_path, statements=2)
    try:
        recycles = settle(store)
        stale = store._conn
        real = real_ladybug.Connection

        def refuse(*args, **kwargs):
            raise RuntimeError("no more connections")

        monkeypatch.setattr(real_ladybug, "Connection", refuse)
        with caplog.at_level(logging.WARNING, logger=ladybug.log.name):
            for n in range(3):
                store.run("CREATE (:RecycleItem {id: $id, n: $n})", id=f"item-{n}", n=n)
        assert store._conn is stale and not stale.is_closed
        assert store.connection_recycles == recycles
        # Two failed attempts, one warning, naming the kind of error only.
        assert [record.levelname for record in caplog.records] == ["WARNING"]
        assert "RuntimeError" in caplog.text
        monkeypatch.setattr(real_ladybug, "Connection", real)
        store.run("RETURN $k AS k", k=1)
        assert store.connection_recycles == recycles + 1
        assert stale.is_closed
        assert count_items(store) == 3
    finally:
        store.close()


def test_recycle_logs_name_neither_the_database_file_nor_the_driver_error(tmp_path, monkeypatch, caplog):
    """hippo's logs carry no filesystem paths and no raw exception text (as the managed activation suite checks)."""
    store = open_recycling(tmp_path, statements=2)
    secret = "/private/var/folders/secret-path sk-live-secret"
    real = real_ladybug.Connection

    class ClosesBadly(real):
        def close(self):
            super().close()
            raise RuntimeError(secret)

    def refuse(*args, **kwargs):
        raise RuntimeError(secret)

    try:
        with caplog.at_level("DEBUG", logger="hippo"):
            monkeypatch.setattr(real_ladybug, "Connection", ClosesBadly)
            settle(store)
            settle(store)  # closes a ClosesBadly connection
            monkeypatch.setattr(real_ladybug, "Connection", refuse)
            for n in range(3):
                store.run("CREATE (:RecycleItem {id: $id, n: $n})", id=f"item-{n}", n=n)
        levels = {record.levelname for record in caplog.records if record.name == ladybug.log.name}
        assert levels == {"DEBUG", "WARNING"}
        for leak in (str(tmp_path), "/private/var", "secret-path", "sk-live-secret"):
            assert leak not in caplog.text
        assert count_items(store) == 3
    finally:
        monkeypatch.setattr(real_ladybug, "Connection", real)
        store.close()


# ------------------------------------------------------------------ the footprint stays bounded

FOOTPRINT_SCRIPT = r"""
import ctypes, gc, os, sys
from hippo.config import load_config
from hippo.store import open_store

def footprint():
    if sys.platform == "darwin":
        class Info(ctypes.Structure):
            _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [(f"f{i}", ctypes.c_uint64) for i in range(40)]
        info = Info()
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        assert libc.proc_pid_rusage(os.getpid(), 4, ctypes.byref(info)) == 0
        return info.f7  # ri_phys_footprint
    with open("/proc/self/status") as status:
        return next(int(line.split()[1]) * 1024 for line in status if line.startswith("RssAnon:"))

store = open_store(load_config())
payload = "x" * 10_000
for k in range(500):
    store.run("RETURN size($s) + $k AS n", s=payload, k=k)
gc.collect()
before = footprint()
for k in range(int(sys.argv[1])):
    store.run("RETURN size($s) + $k AS n", s=payload, k=k)
gc.collect()
print(footprint() - before, getattr(store, "connection_recycles", "none"))
store.close()
"""


@pytest.mark.skipif(
    sys.platform not in ("darwin", "linux"), reason="reads phys_footprint (macOS) or RssAnon (Linux)"
)
def test_recycling_bounds_the_native_footprint_of_parameterised_statements(tmp_path, monkeypatch):
    """Two fresh processes, so neither reuses memory the other freed: one never recycles, one recycles often."""

    def grow(tag: str, statements: str) -> tuple[int, str]:
        env = {
            "HIPPO_DATA_DIR": str(tmp_path / tag),
            "HIPPO_LADYBUG_BUFFER_POOL_BYTES": str(64 * MiB),
            SETTING: statements,
            "PATH": "/usr/bin:/bin",
        }
        done = subprocess.run(
            [sys.executable, "-c", FOOTPRINT_SCRIPT, "6000"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        growth, recycles = done.stdout.split()
        return int(growth), recycles

    unbounded, never = grow("never", str(10**12))
    bounded, often = grow("often", "100")
    report = f"never recycling grew {unbounded / MiB:.1f} MiB ({never} recycles); recycling every 100 grew {bounded / MiB:.1f} MiB ({often} recycles)"
    assert unbounded >= 48 * MiB, report
    assert bounded <= min(24 * MiB, unbounded // 4), report
