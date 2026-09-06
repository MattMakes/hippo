"""
A very small background-job runner.

Indexing a source or running an evaluation can take minutes with a local
model, so they run in a thread while the web page keeps polling for progress.
Progress itself is written to Neo4j by the job (on the Source or EvalRun
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

            thread = threading.Thread(target=runner, name=f"job-{key}", daemon=True)
            self._running[key] = thread
            thread.start()
            return True

    def is_running(self, key: str) -> bool:
        thread = self._running.get(key)
        return thread is not None and thread.is_alive()

    def running_keys(self) -> list[str]:
        return [k for k, t in self._running.items() if t.is_alive()]

    def wait_all(self, timeout: float | None = None) -> None:
        """Mostly for tests: block until every job has finished."""
        for thread in list(self._running.values()):
            thread.join(timeout)
