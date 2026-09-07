"""
The Graph page: the whole memory as a 3D picture you can search, filter and
"light up" with a question.

What it shows is exactly what the caller may see (hippo/access.py): the nodes
come from `ctx.graph_for(access)`, so a hidden passage, and an entity or fact
only hidden passages support, is simply not there. Users who may manage
others can pick a role and see the graph as that tier would.

    GET  /graph                          the page
    GET  /api/graph/full                 nodes + edges (filters: q, source, kind, min_weight, as_role; capped)
    POST /api/graph/light-up             run the search for a question and return what lit up:
                                         seeds, activated nodes with scores, ranked passages, the
                                         paths from seeds to passages, and the lit subgraph
    GET  /api/graph/node/{node_id}       details for the side panel (passage text, entity facts)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ... import ask as ask_service
from ...access import EVERYONE_RANK, Principal
from ...analysis.explain import explain
from ...hipporag.graph_index import ENTITY, PASSAGE, GraphIndex
from ...ollama import OllamaError
from ..auth import principal_of
from ..render import ctx_of, render

router = APIRouter()
api = APIRouter(prefix="/api/graph")

DEFAULT_LIMIT = 2500  # nodes drawn at once; the browser stays smooth up to a few thousand
MAX_LIMIT = 8000
EVERYONE_TIER = {"id": "", "name": "Everyone", "rank": EVERYONE_RANK}


# ------------------------------------------------------------ the viewer


def viewer(request: Request, as_role: str | None) -> tuple[Principal, dict[str, Any] | None]:
    """
    The principal the picture is drawn for. `as_role` previews another tier (a role id) and is
    only honoured for callers who manage users or roles: it is a way to check what a tier sees.
    """
    principal = principal_of(request)
    if not as_role:
        return principal, None
    if not (principal.can("manage_users") or principal.can("manage_roles")):
        raise HTTPException(403, "previewing another role needs 'manage_users' or 'manage_roles'")
    role = ctx_of(request).store.get_role(as_role)
    if role is None:
        raise HTTPException(400, "no such role")
    if not principal.is_open and role["rank"] > principal.rank:
        raise HTTPException(403, "you can only preview tiers at or below your own")
    return principal.as_role(role), role


def tiers_of(ctx, index: GraphIndex, access) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """
    Per source: its tier {id, name, rank}. Per node id: the most permissive tier it is visible from
    (a passage's source tier; for an entity, the lowest tier among the visible passages mentioning it).
    """
    roles = {r["id"]: r for r in ctx.store.list_roles()}
    source_tier: dict[str, dict[str, Any]] = {}
    for source in ctx.store.list_sources(access):
        role = roles.get(source.get("access_role_id") or "")
        source_tier[source["id"]] = (
            {"id": role["id"], "name": role["name"], "rank": role["rank"]} if role else dict(EVERYONE_TIER)
        )
    node_tier: dict[str, dict[str, Any]] = {}
    for p in index.passages:
        node_tier[p.id] = source_tier.get(p.source_id, dict(EVERYONE_TIER))
    for (a, b), e in index.edges.items():
        if not e.mention:
            continue
        ent, pas = (a, b) if index.node_kind[a] == ENTITY else (b, a)
        tier = node_tier.get(index.node_ids[pas])
        if tier is None:
            continue
        current = node_tier.get(index.node_ids[ent])
        if current is None or tier["rank"] < current["rank"]:
            node_tier[index.node_ids[ent]] = tier
    return source_tier, node_tier


# ----------------------------------------------------------------- page


@router.get("/graph")
def graph_page(request: Request, as_role: str = "", q: str = ""):
    ctx = ctx_of(request)
    principal, preview = viewer(request, as_role or None)
    roles = ctx.store.list_roles() if ctx.store.ping() else []
    can_preview = principal_of(request).can("manage_users") or principal_of(request).can("manage_roles")
    me = principal_of(request)
    previewable = [r for r in roles if me.is_open or r["rank"] <= me.rank] if can_preview else []
    return render(
        request,
        "graph.html",
        nav="graph",
        principal=principal,
        preview_role=preview,
        previewable=previewable,
        sources=ctx.store.list_sources(principal.access) if ctx.store.ping() else [],
        roles=roles,
        initial_query=q,
        default_limit=DEFAULT_LIMIT,
    )


# ------------------------------------------------------------ full graph


@api.get("/full")
def full_graph(
    request: Request,
    q: str = "",
    source: str = "",
    kind: str = "",
    min_weight: float = 0.0,
    limit: int = DEFAULT_LIMIT,
    as_role: str = "",
):
    ctx = ctx_of(request)
    principal, preview = viewer(request, as_role or None)
    index = ctx.graph_for(principal.access)
    source_tier, node_tier = tiers_of(ctx, index, principal.access)
    limit = max(10, min(int(limit), MAX_LIMIT))

    degree = index.graph.degree() if index.num_nodes else []
    text = q.strip().lower()
    wanted: set[int] = set()

    def matches(v: int) -> bool:
        if kind and index.node_kind[v] != kind:
            return False
        if source:
            if index.node_kind[v] == PASSAGE:
                return index.passages[index.passage_position(v)].source_id == source
            # an entity belongs to a source when a passage of that source mentions it
            return any(
                index.node_kind[o] == PASSAGE
                and index.passages[index.passage_position(o)].source_id == source
                for o, _w in index.neighbors(v)
            )
        return True

    for v in range(index.num_nodes):
        if not matches(v):
            continue
        if text and text not in index.name_of(v).lower():
            continue
        wanted.add(v)
    if text:
        # A name search shows its matches in context: one hop of neighbours around each hit.
        for v in list(wanted):
            for o, _w in index.neighbors(v):
                if matches(o):
                    wanted.add(o)

    ordered = sorted(wanted, key=lambda v: (-degree[v], v))
    shown = ordered[:limit]
    shown_set = set(shown)
    nodes = []
    for v in shown:
        node_id = index.node_ids[v]
        node: dict[str, Any] = {
            "id": node_id,
            "label": index.name_of(v),
            "kind": index.node_kind[v],
            "degree": int(degree[v]),
            "tier": node_tier.get(node_id, EVERYONE_TIER)["name"],
            "tier_rank": node_tier.get(node_id, EVERYONE_TIER)["rank"],
        }
        if index.node_kind[v] == PASSAGE:
            p = index.passages[index.passage_position(v)]
            node["source_id"] = p.source_id
            node["source_name"] = p.source_name
        else:
            node["passage_count"] = int(index.entity_passage_count[v])
        nodes.append(node)
    edges = []
    for v in shown:
        for o, w in index.neighbors(v):
            if o <= v or o not in shown_set or w < min_weight:
                continue
            e = index.edge_between(v, o)
            edges.append(
                {
                    "source": index.node_ids[v],
                    "target": index.node_ids[o],
                    "weight": round(float(w), 4),
                    "kinds": e.kinds if e else [],
                }
            )
    # The whole ladder (not only the tiers present) so colours mean the same thing on every graph.
    tiers = sorted(
        [{"id": r["id"], "name": r["name"], "rank": r["rank"]} for r in ctx.store.list_roles()]
        + [dict(EVERYONE_TIER)],
        key=lambda t: -t["rank"],
    )
    return {
        "nodes": nodes,
        "edges": edges,
        "total_nodes": index.num_nodes,
        "matched_nodes": len(wanted),
        "shown_nodes": len(shown),
        "truncated": len(wanted) > len(shown),
        "entities": index.num_entities,
        "passages": len(index.passages),
        "facts": len(index.facts),
        "graph_version": index.version,
        "viewer": {"role": principal.role_name, "rank": principal.rank, "preview": bool(preview)},
        "tiers": tiers,
        "sources": [
            {"id": sid, "tier": tier["name"], "tier_rank": tier["rank"]} for sid, tier in source_tier.items()
        ],
    }


# ------------------------------------------------------------- light up


class LightUpBody(BaseModel):
    question: str = Field(min_length=1)
    settings: dict[str, Any] | None = None
    as_role: str | None = None
    top_passages: int = 10


@api.post("/light-up")
def light_up(request: Request, body: LightUpBody):
    """
    Run the search for a question on the viewer's graph and describe what lit up. No answer is
    generated (that costs another model call); the Ask page does that.
    """
    ctx = ctx_of(request)
    principal, _preview = viewer(request, body.as_role or None)
    try:
        trace = ask_service.search(ctx, body.question.strip(), body.settings, access=principal.access)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OllamaError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    index = ctx.graph_for(principal.access)
    top = max(1, min(int(body.top_passages), 50))
    explanation = explain(index, trace, top_passages=top)
    _source_tier, node_tier = tiers_of(ctx, index, principal.access)

    seeds = [
        {"id": s.entity_id, "name": s.name, "weight": round(s.weight, 5), "passage_count": s.passage_count}
        for s in trace.seed_entities
        if s.kept and s.weight > 0
    ]
    paths = []
    for p in explanation.passages:
        if p.path_ids:
            paths.append({"passage_id": p.passage_id, "nodes": p.path_ids})
        for linked in p.linked_seeds:
            paths.append({"passage_id": p.passage_id, "nodes": [linked["entity_id"], p.passage_id]})
    for node in explanation.subgraph["nodes"]:
        node["tier"] = node_tier.get(node["id"], EVERYONE_TIER)["name"]
        node["tier_rank"] = node_tier.get(node["id"], EVERYONE_TIER)["rank"]
    return {
        "question": trace.question,
        "used_dpr_fallback": trace.used_dpr_fallback,
        "fallback_reason": trace.fallback_reason,
        "settings": trace.settings,
        "timing_ms": trace.timing_ms,
        "kept_facts": [
            {"fact_id": c.fact_id, "triple": c.triple, "score": round(c.score, 4)}
            for c in trace.fact_candidates
            if c.kept
        ],
        "seeds": seeds,
        "seed_passages": [
            {"id": s.passage_id, "title": s.title, "weight": round(s.weight, 5)} for s in trace.seed_passages
        ],
        "top_nodes": [
            {"id": n.node_id, "kind": n.kind, "name": n.name, "score": n.score, "is_seed": n.is_seed}
            for n in trace.top_nodes
        ],
        "passages": [
            {
                "id": p.passage_id,
                "title": p.title,
                "rank": p.rank,
                "score": p.score,
                "dpr_rank": p.dpr_rank,
                "why": p.why,
                "path": p.path,
                "linked_seeds": [s["entity_id"] for s in p.linked_seeds],
            }
            for p in explanation.passages
        ],
        "paths": paths,
        "subgraph": explanation.subgraph,
    }


# ------------------------------------------------------------ one node


@api.get("/node/{node_id}")
def node_details(request: Request, node_id: str, as_role: str = ""):
    ctx = ctx_of(request)
    principal, _preview = viewer(request, as_role or None)
    index = ctx.graph_for(principal.access)
    vertex = index.idx_of.get(node_id)
    if vertex is None:
        raise HTTPException(404, "unknown node")
    _source_tier, node_tier = tiers_of(ctx, index, principal.access)
    neighbours = sorted(index.neighbors(vertex), key=lambda t: -t[1])
    out: dict[str, Any] = {
        "id": node_id,
        "kind": index.node_kind[vertex],
        "label": index.name_of(vertex),
        "tier": node_tier.get(node_id, EVERYONE_TIER)["name"],
        "degree": len(neighbours),
        "neighbours": [
            {
                "id": index.node_ids[o],
                "label": index.name_of(o),
                "kind": index.node_kind[o],
                "weight": round(float(w), 3),
                "kinds": (index.edge_between(vertex, o) or _NO_EDGE).kinds,
            }
            for o, w in neighbours[:60]
        ],
    }
    if index.node_kind[vertex] == PASSAGE:
        p = index.passages[index.passage_position(vertex)]
        out.update(
            title=p.title,
            source_id=p.source_id,
            source_name=p.source_name,
            ordinal=p.ordinal,
            text=p.text,
            facts=[f.triple for f in index.facts if p.id in f.passage_ids][:40],
        )
    else:
        facts = [f for f in index.facts if node_id in (f.subject_id, f.object_id)]
        out.update(
            passage_count=int(index.entity_passage_count[vertex]),
            boost=float(index.entity_boost[vertex]),
            facts=[f.triple for f in facts][:60],
            fact_count=len(facts),
            passages=[
                {"id": index.node_ids[o], "title": index.name_of(o)}
                for o, _w in neighbours
                if index.node_kind[o] == PASSAGE
            ][:40],
        )
    return out


class _NoEdge:
    kinds: list[str] = []


_NO_EDGE = _NoEdge()
