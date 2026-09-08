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
        "code": _code_card(ctx, stats, store_ok),
        "embed_model_built": embed_model_built,
        "embed_model_mismatch": bool(embed_model_built and embed_model_built != ctx.ollama.embed_model),
        "ready": store_ok and ollama_ok and all(models.values()),
    }


def _installed(name: str, installed: list[str]) -> bool:
    full = name if ":" in name else name + ":latest"
    return name in installed or full in installed


def _code_card(ctx: AppContext, stats: dict[str, Any], store_ok: bool) -> dict[str, Any]:
    """
    What the code graph holds. Every value is zero or empty until a repository is indexed.

    The four counts come from the `stats()` call above, so this costs no extra query for them. The
    three things a count cannot carry - which languages were parsed, how many calls went
    unresolved, how many commits a budget skipped - come from each source's `meta["code"]`, which
    the indexer wrote and `list_sources` already returns.

    Deliberately not from `ctx.graph()`: `system_status` runs on every page render, and the first
    render after a restart must not pay for a full `GraphIndex.load`.
    """
    languages: set[str] = set()
    unresolved = skipped = 0
    for source in ctx.store.list_sources() if store_ok else []:
        code = (source.get("meta") or {}).get("code") or {}
        languages.update(code.get("languages") or [])
        unresolved += _tally(code.get("unresolved_calls_total"))
        skipped += _tally(code.get("history_skipped"))
    return {
        "symbols": int(stats.get("symbols", 0)),
        "data_objects": int(stats.get("data_objects", 0)),
        "code_edges": int(stats.get("code_edges", 0)),
        "commits": int(stats.get("commits", 0)),
        "languages": sorted(languages),
        "unresolved_calls": unresolved,
        "history_skipped": skipped,
    }


def _tally(value: Any) -> int:
    """A count out of `meta`, whether it was written as a number or as the list of what was skipped."""
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, list | tuple | set | dict):
        return len(value)
    return 0
