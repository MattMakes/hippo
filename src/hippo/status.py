"""Shared service health and audience-scoped inventory for pages, API and MCP.

Only operational health is cached, on its owning context. Corpus inventory is
recomputed from the authorized graph on every request.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .access import Access
from .codegraph.model import CODE_EDGE_KINDS
from .connectors.base import Classification
from .context import AppContext, legacy_lane
from .hipporag.graph_index import GraphIndex
from .ingest.managed_activation import CONNECTOR_KIND, source_shape
from .knowledge import model as k
from .knowledge.access import AuthorizationChanged
from .knowledge.domain import resolve_domain
from .knowledge.public_errors import OPERATION_FAILED, public_failure_for_code
from .knowledge.query_access import QuerySession, current_access, query_session
from .ollama import OllamaError

CACHE_SECONDS = 8.0

# Plan table 3.4: what a row shows when its Source's own presentation is withheld (P1).
WITHHELD_INVENTORY: dict[str, Any] = {
    "origin": None,
    "origin_detail": None,
    "lane": None,
    "domain": None,
    "domain_natural": None,
    "domain_origin": None,
    "domain_state": None,
    "domain_allowed": [],
    "domain_fixed_reason": None,
    "domain_confirmed_at": None,
    "domain_confirmed_by": None,
    "last_sync_at": None,
    "last_sync_label": None,
    "last_error": None,
    "resync_command": None,
}


@dataclass
class SourceView:
    """Request-local source presentation derived from one authorized graph."""

    graph: GraphIndex
    sources: list[dict[str, Any]]
    legacy_ids: set[str]
    validate: Callable[[], None]
    # Each presented source's generations, newest first, for the source page's Sync card. Kept off
    # the rows, so neither the Library's poll nor `/api/sources` carries the history.
    generations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def source_view(
    ctx: AppContext,
    access: Access,
    *,
    session: QuerySession | None = None,
    descriptor_families: Mapping[str, tuple[str, ...]] | None = None,
) -> SourceView:
    """Keep source controls separate from managed evidence labels and inventory.

    A supplied session is the caller's; when this owns the view it loads a structural one,
    because `selected_managed_generations` is the only proof that an authorized generation
    which produced no evidence at all exists, and nothing else can represent it.

    `descriptor_families` maps a connector kind to the families its descriptor declares. Only
    the source page has it (`app.state.connector_load`); without it a connector source's domain
    reads as fixed, and the listing never loads a connector package (invariant I1).
    """
    epoch = ctx.store.authorization_epoch()
    access = current_access(ctx.store, access)
    graph = session.graph if session is not None else ctx.graph_for(access, structural=True)

    def validate():
        if session is not None:
            session.validate()
        graph.validate_authorization()
        if ctx.store.authorization_epoch() != epoch:
            raise AuthorizationChanged("Authorization changed while computing source inventory")

    validate()
    sources = ctx.store.list_sources(access)
    # The same lane split the graph uses, over this file's own managed-record set. A source
    # converting to managed generations stays in the legacy lane, and so keeps presenting
    # its legacy row and counts, until its first publication; one whose rows are all staged
    # has nothing to present there and waits for that publication in the managed set, where
    # only a proven pair represents it.
    records = {row.source_id for row in ctx.store._knowledge_rows("Artifact")}
    generations = ctx.store._knowledge_rows("Generation")
    records.update(row.source_id for row in generations)
    records.update(
        source["id"]
        for source in sources
        if source.get("active_generation_id")
        or source.get("managed")
        or (source.get("meta") or {}).get("managed")
    )
    legacy_ids, converting = legacy_lane(ctx.store, sources, records)
    legacy_ids = set(legacy_ids)
    managed = {source["id"] for source in sources if source["id"] not in legacy_ids}
    represented = {passage.source_id for passage in graph.passages}
    represented.update(node.source_id for node in graph.code_nodes if node.source_id)
    # A proven selected pair is representation in its own right. This is what keeps an authorized
    # empty generation visible, and omitting a policy-denied or tombstoned one needs no extra rule:
    # neither proves a pair, so neither reaches this set.
    represented.update(source for source, _generation in graph.selected_managed_generations)
    selected = dict(graph.selected_managed_generations)
    rows = [
        _with_code_edges(_managed_source(source, graph), ctx.store, selected.get(source["id"]))
        if source["id"] in managed
        else _legacy_source(source, graph)
        if source["id"] in converting
        else deepcopy(source)
        for source in sources
        if source["id"] in legacy_ids or source["id"] in represented
    ]
    history = _add_inventory(
        ctx.store,
        rows,
        sources,
        generations,
        legacy_ids=legacy_ids,
        proven=legacy_ids | set(selected),
        descriptor_families=descriptor_families,
    )
    validate()
    return SourceView(graph, rows, legacy_ids, validate, history)


def _add_inventory(
    store,
    rows: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    generations: list[k.Generation],
    *,
    legacy_ids: set[str],
    proven: set[str],
    descriptor_families: Mapping[str, tuple[str, ...]] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Write plan table 3.4's keys on every row, and return each presented source's history.

    One pass, with the Generation list `source_view` already holds and at most two new reads:
    `Connector` and `SyncState`, each by `ids=` for every connector row at once, and each skipped
    when no row asks. Per-row work is `source_shape` and `resolve_domain`, which read nothing.

    A row whose Source presentation is withheld (a managed row without a proven pair) gets
    `WITHHELD_INVENTORY` and keeps `kind == "managed"`: its true kind, domain and sync times
    would say what the audience may not see (P1).
    """
    stored = {source["id"]: source for source in sources}
    shown = {row["id"] for row in rows if row["id"] in proven}
    partitions: dict[str, tuple[str, str]] = {}
    for identity in shown:
        source = stored[identity]
        meta = source.get("meta") or {}
        if source.get("kind") == CONNECTOR_KIND and isinstance(meta, Mapping):
            connector_id, partition = meta.get("connector_id"), meta.get("partition")
            if connector_id and partition and isinstance(connector_id, str) and isinstance(partition, str):
                partitions[identity] = (connector_id, partition)
    connector_ids = sorted({connector_id for connector_id, _ in partitions.values()})
    connectors = (
        {row.id: row for row in store._knowledge_rows("Connector", ids=connector_ids)}
        if connector_ids
        else {}
    )
    # The identity `connectors/sync.py` gives one partition's SyncState.
    state_ids = {
        identity: k.SyncState(connector_id=connector_id, partition_key=partition).id
        for identity, (connector_id, partition) in partitions.items()
    }
    states = (
        {row.id: row for row in store._knowledge_rows("SyncState", ids=sorted(set(state_ids.values())))}
        if state_ids
        else {}
    )
    by_id = {generation.id: generation for generation in generations}
    classifications: dict[str, Classification | None] = {}
    for row in rows:
        identity = row["id"]
        if identity not in shown:
            row.update(deepcopy(WITHHELD_INVENTORY))
            continue
        source = stored[identity]
        kind = source.get("kind")
        lane = "connector" if kind == CONNECTOR_KIND else "legacy" if identity in legacy_ids else "managed"
        active = by_id.get(source.get("active_generation_id"))
        connector = state = entry = partition = None
        if identity in partitions:
            connector_id, partition = partitions[identity]
            connector = connectors.get(connector_id)
            state = states.get(state_ids[identity])
            entry = _partition_classification(connector, partition, classifications)
        families = (
            descriptor_families.get(connector.kind)
            if connector is not None and descriptor_families is not None
            else None
        )
        decision = resolve_domain(
            source,
            source_shape(source),
            classification=entry,
            descriptor_families=families,
            active_generation=active,
            sync_state=state,
            connector_kind=connector.kind if connector is not None else None,
        )
        last_sync_at, last_sync_label = _last_sync(lane, source, active, state)
        row.update(
            kind=kind,
            origin=kind,
            origin_detail=f"{connector.kind} · {connector.id} · {partition}" if connector else None,
            lane=lane,
            domain=decision.family,
            domain_natural=decision.natural,
            domain_origin=decision.origin,
            domain_state=decision.state,
            domain_allowed=list(decision.allowed),
            domain_fixed_reason=decision.fixed_reason,
            domain_confirmed_at=decision.confirmed_at,
            domain_confirmed_by=decision.confirmed_by,
            last_sync_at=last_sync_at,
            last_sync_label=last_sync_label,
            last_error=(state.error_code if state is not None else None) or row.get("error") or None,
            # An instance whose Connector row is gone has nothing a sync could run.
            resync_command=f"hippo connector sync {connector.id} --partition {partition}"
            if connector
            else None,
        )
    history: dict[str, list[dict[str, Any]]] = {}
    owned = [generation for generation in generations if generation.source_id in shown]
    for generation in sorted(owned, key=lambda row: row.created_at, reverse=True):
        history.setdefault(generation.source_id, []).append(
            {
                "id": generation.id,
                "version": generation.parser_version,
                "status": generation.status,
                "created_at": _instant(generation.created_at),
                "published_at": _instant(generation.published_at),
                "nodes_by_family": _nodes_by_family(generation) if generation.source_id in partitions else {},
            }
        )
    return history


def _partition_classification(connector, partition: str, parsed: dict[str, Classification | None]):
    """One partition's stored probe result, or None when there is none to read (then `custom`).

    Read the way `connectors.sync.load_classification` reads it, but a missing or unreadable
    probe is an answer here, never a refusal: the Library must render every other row.
    """
    if connector is None:
        return None
    if connector.id not in parsed:
        try:
            parsed[connector.id] = Classification.model_validate_json(connector.classification_json)
        except ValueError:
            parsed[connector.id] = None
    classification = parsed[connector.id]
    if classification is None:
        return None
    return next((entry for entry in classification.partitions if entry.partition == partition), None)


def _last_sync(lane: str, source: dict, active: k.Generation | None, state: k.SyncState | None):
    """Design D6: `(instant, label)`, from the record that is each lane's own last sync."""
    if lane == "connector":
        instant, label = (state.last_success_at if state is not None else None), "synced"
    elif lane == "managed":
        instant, label = (active.published_at if active is not None else None), "published"
    else:
        instant, label = source.get("updated_at") or None, "last activity"
    return (_instant(instant), label) if instant is not None else (None, None)


def _instant(value: datetime | str | None) -> str | None:
    """A stored instant in the `now_iso()` shape of `created_at`; Source columns already are."""
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    return value


def _nodes_by_family(generation: k.Generation) -> dict[str, int]:
    """The connector emission's per-family node counts (`connectors/emit.py`, `EmissionCoverage`)."""
    try:
        coverage = json.loads(generation.coverage_json or "{}")
    except ValueError:
        return {}
    emission = coverage.get("emission") if isinstance(coverage, dict) else None
    counts = emission.get("nodes_by_family") if isinstance(emission, dict) else None
    return dict(counts) if isinstance(counts, dict) else {}


def _legacy_source(source: dict, graph: GraphIndex) -> dict[str, Any]:
    """One converting source's legacy row, with its passage count taken from the held graph.

    The Store's Source counter spans every passage ever written for the source, staged
    generations included, so a source part way through its conversion would report a
    generation's staged passages as its own while still serving only its legacy ones. The
    managed row already counts from the view's own provenance for the same reason. A legacy
    source with no generation has no staged rows to confuse the counter, and keeps the
    counter it has always presented.
    """
    row = deepcopy(source)
    row["passages"] = sum(1 for passage in graph.passages if passage.source_id == source["id"])
    return row


def _managed_source(source: dict, graph: GraphIndex) -> dict[str, Any]:
    """One managed row, counted from the held graph's own provenance.

    Every count comes from this view's exact provenance, never from the Store's Source
    counters: those span legacy, staged, active and retired generations at once, so a
    refreshed source would report both generations' passages as current. The one count the
    held graph cannot answer, the selected generation's native code relations, is added by
    `_with_code_edges`.

    A shared code object stays one global vertex while being attributed to each selected
    source that contributed evidence for it, which is why the node's own `source_id` (the
    smallest contributor) cannot be the only rule.
    """
    identity = source["id"]
    pair = next((row for row in graph.selected_managed_generations if row[0] == identity), None)
    passages = [passage for passage in graph.passages if passage.source_id == identity]
    passage_ids = {passage.id for passage in passages}
    fact_links = sum(
        1 for fact in graph.facts for passage_id in fact.passage_ids if passage_id in passage_ids
    )
    contributed = {row.node_id for row in graph.structural_code_evidence if row.source_id == identity}
    contributed.update(row.node_id for row in graph.structural_object_evidence if row.source_id == identity)
    nodes = [node for node in graph.code_nodes if node.id in contributed or node.source_id == identity]
    # Relations are counted by the exact selected pair, never from this source's vertices: a vertex
    # carries every arrow that reaches it, whichever generation or contributor wrote it. The native
    # code relations are the selected generation's own rows, which `_with_code_edges` adds.
    edge_counts = Counter(
        row.predicate
        for row in graph.structural_relations
        if pair is not None and pair in row.source_generations
    )
    names = sorted({passage.title for passage in passages if passage.title})
    # These are source administration controls, not inferred upstream ownership.
    controls = {
        key: source.get(key) for key in ("access_role_id", "access_role_name", "min_rank", "owner_id")
    }
    # Without a proven pair the row exists only because some evidence is visible; the Source's own
    # presentation is not authorized by that and stays withheld.
    proven = pair is not None
    return {
        **controls,
        "id": identity,
        "name": (source.get("name") or "") if proven else (names[0] if names else "Managed source"),
        # The lane is `lane`, never the kind (plan table 3.4); withheld, the kind would say too much.
        "kind": source.get("kind") if proven else "managed",
        "managed": True,
        "owner_name": (source.get("owner_name") or "") if proven else "",
        "created_at": (source.get("created_at") or "") if proven else "",
        "status": (source.get("status") or "") if proven else "ready",
        "stage": (source.get("stage") or "") if proven else "",
        "error": _public_error(source) if proven else "",
        "progress_done": int(source.get("progress_done") or 0) if proven else 0,
        "progress_total": int(source.get("progress_total") or 0) if proven else 0,
        "passages": len(passages),
        "fact_links": fact_links,
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
        if nodes or edge_counts
        else {},
    }


def _with_code_edges(row: dict[str, Any], store, generation_id: str | None) -> dict[str, Any]:
    """Add one managed row's native code relations, read by exact generation membership.

    The count is one scoped `_native_relationships(generation_id=...)` read of the row's proven
    selected pair. It is never taken from the held graph. The structural projection does serve each
    selected generation's sealed `CODE_EDGE` rows as arrows, but a shared vertex carries every
    contributor's arrows, so walking a row's vertices would count other generations' relations too.
    A staged, failed, retired or tombstoned generation is never a selected pair, so it is
    never read, and a publication replaces the pair and its count together. The read refuses an
    edge that crosses generations rather than dropping it, so a count is never taken over one.
    """
    if generation_id is None:
        return row
    counts = Counter(
        relation[3]["kind"]
        for relation in store._native_relationships(generation_id=generation_id)
        if relation[0] == "CODE_EDGE" and relation[3].get("kind") in CODE_EDGE_KINDS
    )
    if not counts:
        return row
    code = row["meta"].setdefault(
        "code",
        {"symbols": 0, "data_objects": 0, "commits": 0, "edges": 0, "edges_by_kind": {}, "languages": []},
    )
    counts.update(code["edges_by_kind"])
    code["edges_by_kind"] = dict(counts)
    code["edges"] = sum(counts.values())
    return row


def _public_error(source: dict) -> str:
    """The managed lane's own classification, read back; never the sentence stored beside it.

    `managed_activation.record_build_failure` classifies a build failure once, where it
    happened, and stores `"<code>: <message>"` on the Source row. The code is the stable
    half, so the row is rendered from `public_failure_for_code` and the stored text is
    never echoed -- not because that text is unsafe today, but because a row is only ever
    as bounded as whoever last wrote it, and this is the only rendering path a managed
    source has.

    A row that is presenting a failure cannot fall silent either: a code this table does
    not map (`authorization_changed`, or anything a future build lane adds) takes the
    caller fallback `public_errors` documents rather than an empty cell.
    """
    stored = source.get("error") or ""
    if not stored:
        return ""
    code = stored.split(":", 1)[0].strip()
    return (public_failure_for_code(code) or OPERATION_FAILED).message


def system_status(
    ctx: AppContext,
    fresh: bool = False,
    *,
    access: Access | None = None,
    session: QuerySession | None = None,
) -> dict[str, Any]:
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
        stats, code, jobs = _audience_inventory(ctx, access, session=session)
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


def _audience_inventory(
    ctx: AppContext, access: Access, *, session: QuerySession | None = None
) -> tuple[dict, dict, list[str]]:
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
    if session is None:
        # Structural, so these aggregates count the same sources `source_view` renders. A
        # non-structural owner here would report fewer sources than the inventory it feeds.
        with query_session(ctx, access, structural=True) as owned:
            return _audience_inventory(ctx, access, session=owned)
    view = source_view(ctx, access, session=session)
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
