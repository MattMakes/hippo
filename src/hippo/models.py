"""
Making sure the Ollama models are installed.

On startup (and from the Settings page) hippo checks that the LLM and the
embedding model are present and pulls the missing ones in the background,
keeping a small progress record per model so the UI can show a bar.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .jobs import Jobs
from .ollama import Ollama, OllamaError

log = logging.getLogger(__name__)

JOB_KEY = "pull-models"


class ModelManager:
    def __init__(self, ollama: Ollama, jobs: Jobs):
        self.ollama = ollama
        self.jobs = jobs
        self.progress: dict[
            str, dict[str, Any]
        ] = {}  # model -> {"status", "completed", "total", "done", "error"}
        self._lock = threading.Lock()

    def missing(self) -> list[str]:
        try:
            return self.ollama.missing_models()
        except OllamaError:
            return list(self.ollama.required_models())

    def start_pull(self) -> bool:
        """Pull every missing model in a background job. Returns False if a pull is already running."""
        return self.jobs.start(JOB_KEY, self.pull_now)

    def is_pulling(self) -> bool:
        return self.jobs.is_running(JOB_KEY)

    def pull_now(self) -> None:
        """Pull missing models right now (blocking). Used by the background job and by `hippo pull-models`."""
        for model in self.missing():
            self._set(model, status="starting", completed=0, total=0, done=False, error=None)
            try:
                self.ollama.ensure_model(model, on_progress=lambda event, m=model: self._on_event(m, event))
                self._set(model, status="installed", done=True)
                log.info("Model %s is ready", model)
            except OllamaError as exc:
                self._set(model, status="failed", done=True, error=str(exc))
                log.error("Could not pull %s: %s", model, exc)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self.progress.items()}

    def _on_event(self, model: str, event: dict[str, Any]) -> None:
        fields: dict[str, Any] = {"status": event.get("status", "")}
        if "completed" in event and "total" in event:
            fields["completed"] = int(event["completed"])
            fields["total"] = int(event["total"])
        self._set(model, **fields)

    def _set(self, model: str, **fields: Any) -> None:
        with self._lock:
            self.progress.setdefault(
                model, {"status": "", "completed": 0, "total": 0, "done": False, "error": None}
            ).update(fields)
