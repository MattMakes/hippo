"""An owned renewal worker; a lost lease permanently invalidates its operation."""

from __future__ import annotations

import math
from threading import Event, Lock, Thread

from .access import AuthorizationChanged


class LeaseHeartbeat:
    def __init__(self, renew, *, interval: float):
        if isinstance(interval, bool) or not isinstance(interval, (float, int)):
            raise ValueError("Renewal interval must be finite and positive")
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Renewal interval must be finite and positive")
        self._renew = renew
        self._interval = interval
        self._stop = Event()
        self._lock = Lock()
        self._thread = None
        self._closed = False
        self._error = None

    def start(self):
        with self._lock:
            if self._thread is not None or self._closed:
                raise RuntimeError("Renewal worker cannot restart")
            thread = Thread(target=self._run, name="hippo-lease-renewal", daemon=True)
            self._thread = thread
            try:
                thread.start()
            except BaseException:
                # Startup can be interrupted after the OS thread has begun.
                # Keep ownership so close joins any active renewal. A worker
                # that has not entered _run yet will see stop before renewing.
                self._stop.set()
                raise

    def _run(self):
        while not self._stop.wait(self._interval):
            try:
                self._renew()
            except BaseException as error:
                with self._lock:
                    self._error = error
                self._stop.set()
                return

    def check(self):
        with self._lock:
            error = self._error
        if error is not None:
            raise AuthorizationChanged("Snapshot lease renewal failed; repeat the query") from error

    def close(self):
        with self._lock:
            self._closed = True
            self._stop.set()
            thread = self._thread
        if thread is not None and thread.ident is not None:
            thread.join()
