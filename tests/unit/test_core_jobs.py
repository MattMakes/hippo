"""
hippo/jobs.py: the background-job runner is safe to ask "what is running?" while jobs finish.

Every page render calls `running_keys()`, and a job's runner pops itself from the same dict
when it ends, so the two must never trip over each other.
"""

from __future__ import annotations

import threading

from hippo.jobs import Jobs


def test_running_keys_never_raises_while_jobs_start_and_finish() -> None:
    jobs = Jobs()
    errors: list[str] = []
    stop = threading.Event()

    def keep_asking() -> None:
        try:
            while not stop.is_set():
                jobs.running_keys()
        except Exception as exc:  # noqa: BLE001 - the whole point is to catch anything
            errors.append(repr(exc))

    readers = [threading.Thread(target=keep_asking) for _ in range(2)]
    for reader in readers:
        reader.start()
    for i in range(2000):  # short jobs finishing all the time, i.e. the dict shrinking under the readers
        jobs.start(f"job-{i}", lambda: None)
    jobs.wait_all()
    stop.set()
    for reader in readers:
        reader.join(5)

    assert errors == []
    assert jobs.running_keys() == []


def test_running_keys_lists_only_live_jobs() -> None:
    jobs = Jobs()
    release = threading.Event()
    assert jobs.start("slow", release.wait)
    assert jobs.running_keys() == ["slow"]
    assert not jobs.start("slow", release.wait)  # same key: still running
    release.set()
    jobs.wait_all(5)
    assert jobs.running_keys() == []
    assert not jobs.is_running("slow")


def test_wait_all_returns_once_every_job_is_done() -> None:
    jobs = Jobs()
    gate = threading.Event()
    done: list[str] = []
    for key in ("a", "b", "c"):
        assert jobs.start(key, lambda key=key: (gate.wait(5), done.append(key)))
    gate.set()
    jobs.wait_all(5)
    assert sorted(done) == ["a", "b", "c"]
