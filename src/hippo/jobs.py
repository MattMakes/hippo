"""
A very small background-job runner.

Indexing a source or running an evaluation can take minutes with a local
model, so they run in a thread while the web page keeps polling for progress.
Progress itself is written to the store by the job (on the Source or EvalRun
node), so this class only has to remember what is currently running.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class Jobs:
    def __init__(self) -> None:
        self._running: dict[str, threading.Thread] = {}
        self._cancelled: dict[
            str, threading.Event
        ] = {}  # a job checks its flag between steps and stops early
        self._lock = threading.Lock()

    def start(self, key: str, work: Callable[[], None]) -> bool:
        """Run `work()` in a thread, unless a job with the same key is already running. Returns True if started."""
        with self._lock:
            if self.is_running(key):
                return False

            def runner() -> None:
                try:
                    work()
                except Exception:  # noqa: BLE001 - jobs report their own errors; this is the last resort
                    log.exception("Background job %s crashed", key)
                finally:
                    with self._lock:
                        self._running.pop(key, None)
                        self._cancelled.pop(key, None)

            thread = threading.Thread(target=runner, name=f"job-{key}", daemon=True)
            self._running[key] = thread
            self._cancelled[key] = threading.Event()
            thread.start()
            return True

    def cancel(self, key: str) -> bool:
        """Ask a running job to stop at its next checkpoint. Returns False if no such job is running."""
        with self._lock:
            event = self._cancelled.get(key)
            if event is None or not self.is_running(key):
                return False
            event.set()
            return True

    def is_cancelled(self, key: str) -> bool:
        event = self._cancelled.get(key)
        return event is not None and event.is_set()

    def wait(self, key: str, timeout: float | None = None) -> bool:
        """Block until the job has finished (or the timeout passes). Returns True if it is no longer running."""
        thread = self._running.get(key)
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def is_running(self, key: str) -> bool:
        # No lock here on purpose: start() and cancel() call this while holding it, and a single
        # dict.get is safe without one.
        thread = self._running.get(key)
        return thread is not None and thread.is_alive()

    def running_keys(self) -> list[str]:
        # Under the lock: a job's runner pops from this dict when it finishes, and iterating a
        # dict while another thread changes its size raises RuntimeError.
        with self._lock:
            return [k for k, t in self._running.items() if t.is_alive()]

    def wait_all(self, timeout: float | None = None) -> None:
        """Mostly for tests: block until every job has finished."""
        with self._lock:
            threads = list(self._running.values())
        for thread in threads:  # join outside the lock: the runner needs it to finish
            thread.join(timeout)
