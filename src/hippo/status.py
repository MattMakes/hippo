"""
"Is everything up?" — one function the header, the Settings page and /api/status all use.

Checks are cached for a few seconds so that rendering a page never waits on
a slow or dead Ollama.
"""

from __future__ import annotations

import time
from typing import Any

from .context import AppContext
from .ollama import OllamaError

CACHE_SECONDS = 8.0
_cache: dict[str, Any] = {"at": 0.0, "value": None}


def system_status(ctx: AppContext, fresh: bool = False) -> dict[str, Any]:
    now = time.time()
    if not fresh and _cache["value"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    value = _compute(ctx)
    _cache.update(at=now, value=value)
    return value


def _compute(ctx: AppContext) -> dict[str, Any]:
    store_ok = ctx.store.ping()
    ollama_ok = ctx.ollama.is_up()
    installed: list[str] = []
    if ollama_ok:
        try:
            installed = ctx.ollama.installed_models()
        except OllamaError:
            ollama_ok = False
    models = {name: _installed(name, installed) for name in ctx.ollama.required_models()}
    stats = ctx.store.stats() if store_ok else {}
    embed_model_built = ctx.store.get_meta("embed_model") if store_ok else None
    return {
        "store": store_ok,
        "store_backend": ctx.config.store_backend,  # "ladybug" (embedded file) or "neo4j"
        "store_location": ctx.config.store_location,  # the .lbug path, or the bolt URI
        "neo4j": store_ok,  # older name for "store", kept for anything that reads /api/status
        "ollama": ollama_ok,
        "ollama_url": ctx.config.ollama_url,
        "models": models,
        "models_ready": all(models.values()),
        "pulling": ctx.models.snapshot() if ctx.models else {},
        "is_pulling": bool(ctx.models and ctx.models.is_pulling()),
        "jobs": ctx.jobs.running_keys(),
        "stats": stats,
        "embed_model_built": embed_model_built,
        "embed_model_mismatch": bool(embed_model_built and embed_model_built != ctx.ollama.embed_model),
        "ready": store_ok and ollama_ok and all(models.values()),
    }


def _installed(name: str, installed: list[str]) -> bool:
    full = name if ":" in name else name + ":latest"
    return name in installed or full in installed
