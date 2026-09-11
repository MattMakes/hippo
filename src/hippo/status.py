"""Shared service health and audience-scoped inventory for pages, API and MCP.

Only operational health is cached, on its owning context. Corpus inventory is
recomputed from the authorized graph on every request.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .access import Access
from .codegraph.model import CODE_EDGE_KINDS
from .context import AppContext
from .hipporag.graph_index import GraphIndex
from .knowledge.access import AuthorizationChanged
from .knowledge.query_access import current_access
from .ollama import OllamaError

CACHE_SECONDS = 8.0


@dataclass
class SourceView:
    """Request-local source presentation derived from one authorized graph."""

    graph: GraphIndex
    sources: list[dict[str, Any]]
    legacy_ids: set[str]
    validate: Callable[[], None]


def source_view(ctx: AppContext, access: Access) -> SourceView:
    """Keep source controls separate from managed evidence labels and inventory."""
    epoch = ctx.store.authorization_epoch()
    access = current_access(ctx.store, access)
    graph = ctx.graph_for(access)

    def validate():
        graph.validate_authorization()
        if ctx.store.authorization_epoch() != epoch:
            raise AuthorizationChanged("Authorization changed while computing source inventory")

    graph.validate_authorization()
    sources = ctx.store.list_sources(access)
    managed = {row.source_id for row in ctx.store._knowledge_rows("Artifact")}
    managed.update(row.source_id for row in ctx.store._knowledge_rows("Generation"))
    managed.update(
        source["id"]
        for source in sources
        if source.get("active_generation_id")
        or source.get("managed")
        or (source.get("meta") or {}).get("managed")
    )
    legacy_ids = {source["id"] for source in sources if source["id"] not in managed}
    represented = {passage.source_id for passage in graph.passages}
    represented.update(node.source_id for node in graph.code_nodes if node.source_id)
    rows = [
        _managed_source(source, graph) if source["id"] in managed else deepcopy(source)
        for source in sources
        if source["id"] in legacy_ids or source["id"] in represented
    ]
    validate()
    return SourceView(graph, rows, legacy_ids, validate)


def _managed_source(source: dict, graph: GraphIndex) -> dict[str, Any]:
    identity = source["id"]
    passages = [passage for passage in graph.passages if passage.source_id == identity]
    nodes = [node for node in graph.code_nodes if node.source_id == identity]
    node_ids = {node.id for node in nodes}
    edge_counts = Counter(
        edge.kind
        for edges in graph.code_out.values()
        for edge in edges
        if edge.kind in CODE_EDGE_KINDS and graph.node_ids[edge.src] in node_ids
    )
    names = sorted({passage.title for passage in passages if passage.title})
    # These are source administration controls, not inferred upstream ownership.
    controls = {
        key: source.get(key) for key in ("access_role_id", "access_role_name", "min_rank", "owner_id")
    }
    return {
        **controls,
        "id": identity,
        "name": names[0] if names else "Managed source",
        "kind": "managed",
        "managed": True,
        "owner_name": "",
        "created_at": "",
        "status": "ready",
        "stage": "",
        "error": "",
        "progress_done": 0,
        "progress_total": 0,
        "passages": len(passages),
        "fact_links": 0,
        "meta": {
            "code": {
                "symbols": sum(node.kind == "symbol" for node in nodes),
                "data_objects": sum(node.kind == "data" for node in nodes),
                "commits": sum(node.kind == "commit" for node in nodes),
                "edges": sum(edge_counts.values()),
                "edges_by_kind": dict(edge_counts),
                "languages": sorted({node.lang for node in nodes if node.lang}),
            }
        }
        if nodes
        else {},
    }


def system_status(ctx: AppContext, fresh: bool = False, *, access: Access | None = None) -> dict[str, Any]:
    """Omitted access preserves internal diagnostics; transports must pass an audience."""
    now = time.monotonic()
    cached = getattr(ctx, "_status_health_cache", None)
    if not fresh and cached is not None and now - cached[0] < CACHE_SECONDS:
        health = deepcopy(cached[1])
    else:
        health = _health(ctx)
        ctx._status_health_cache = (now, deepcopy(health))

    internal = access is None or access.audience_kind == "internal"
    if not health["store"]:
        stats, code, jobs = {}, _code_card({}, []), []
    elif internal:
        stats = ctx.store.stats()
        code = _code_card(stats, ctx.store.list_sources())
        jobs = ctx.jobs.running_keys()
    else:
        stats, code, jobs = _audience_inventory(ctx, access)
    # The global embedding profile has no audience provenance. Do not expose
    # changes caused solely by a hidden corpus through a mismatch badge.
    built = ctx.store.get_meta("embed_model") if internal and health["store"] else None
    return {
        **health,
        "jobs": jobs,
        "stats": stats,
        "code": code,
        "embed_model_built": built,
        "embed_model_mismatch": bool(built and built != ctx.ollama.embed_model),
    }


def _health(ctx: AppContext) -> dict[str, Any]:
    store_ok = ctx.store.ping()
    ollama_ok = ctx.ollama.is_up()
    installed: list[str] = []
    if ollama_ok:
        try:
            installed = ctx.ollama.installed_models()
        except OllamaError:
            ollama_ok = False
    models = {name: _installed(name, installed) for name in ctx.ollama.required_models()}
    return {
        "store": store_ok,
        "store_backend": ctx.config.store_backend,
        "store_location": ctx.config.store_location,
        "neo4j": store_ok,  # compatibility with older /api/status consumers
        "ollama": ollama_ok,
        "ollama_url": ctx.config.ollama_url,
        "models": models,
        "models_ready": all(models.values()),
        "pulling": ctx.models.snapshot() if ctx.models else {},
        "is_pulling": bool(ctx.models and ctx.models.is_pulling()),
        "ready": store_ok and ollama_ok and all(models.values()),
    }


def _audience_inventory(ctx: AppContext, access: Access) -> tuple[dict, dict, list[str]]:
    stats = dict.fromkeys(
        (
            "sources",
            "passages",
            "entities",
            "facts",
            "symbols",
            "data_objects",
            "code_edges",
            "commits",
            "synonym_edges",
            "mention_edges",
        ),
        0,
    )
    if access.audience_kind == "preview":
        return stats, _code_card(stats, []), []
    view = source_view(ctx, access)
    graph = view.graph
    legacy_sources = [source for source in view.sources if source["id"] in view.legacy_ids]
    stats.update(
        sources=len(view.sources),
        passages=len(graph.passages),
        entities=len(graph.entity_names),
        facts=len(graph.facts),
        symbols=sum(node.kind == "symbol" for node in graph.code_nodes),
        data_objects=sum(node.kind == "data" for node in graph.code_nodes),
        commits=sum(node.kind == "commit" for node in graph.code_nodes),
        code_edges=sum(edge.kind in CODE_EDGE_KINDS for edges in graph.code_out.values() for edge in edges),
        synonym_edges=sum(
            edge.synonym_score > 0 or "synonym" in edge.code_kinds for edge in graph.edges.values()
        ),
        mention_edges=sum(edge.mention for edge in graph.edges.values()),
    )
    code = _code_card(stats, legacy_sources, {node.lang for node in graph.code_nodes if node.lang})
    # Eval/generation jobs require their own evidence authorization. Managed
    # index jobs carry source-wide information beyond the reader's projection.
    jobs = [key for key in ctx.jobs.running_keys() if key.startswith("index:") and key[6:] in view.legacy_ids]
    view.validate()
    return stats, code, jobs


def visible_source_count(ctx: AppContext, access: Access) -> int:
    """MCP identity counts use the same source/evidence boundary as status."""
    if access.audience_kind == "internal":
        return len(ctx.store.list_sources())
    return _audience_inventory(ctx, access)[0]["sources"]


def _installed(name: str, installed: list[str]) -> bool:
    full = name if ":" in name else name + ":latest"
    return name in installed or full in installed


def _code_card(
    stats: dict[str, Any], sources: list[dict], languages: set[str] | None = None
) -> dict[str, Any]:
    """Counts from the projection, supplemented only by authorized legacy metadata."""
    languages = set(languages or ())
    unresolved = skipped = 0
    for source in sources:
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
    """A count out of metadata, stored either as a number or a collection."""
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, list | tuple | set | dict):
        return len(value)
    return 0
