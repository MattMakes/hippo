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

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ... import ask as ask_service
from ...access import EVERYONE_RANK, Principal
from ...analysis.explain import explain
from ...hipporag import paths as path_tools
from ...hipporag.graph_index import CODE_KINDS, DATA, ENTITY, PASSAGE, SYMBOL, GraphIndex
from ...knowledge.access import AuthorizationChanged
from ...knowledge.answer_evidence import retrieval_fields
from ...knowledge.query_access import AuthorizedModel, current_access, query_session
from ...ollama import OllamaError
from ...status import source_view
from ..auth import principal_of
from ..render import ctx_of, render

router = APIRouter()
api = APIRouter(prefix="/api/graph")

DEFAULT_LIMIT = 2500  # nodes drawn at once; the browser stays smooth up to a few thousand
MAX_LIMIT = 8000
EVERYONE_TIER = {"id": "", "name": "Everyone", "rank": EVERYONE_RANK}


# ------------------------------------------------------------ the viewer


def viewer(
    request: Request, as_role: str | None
) -> tuple[Principal, dict[str, Any] | None, Callable[[], None]]:
    """
    The principal the picture is drawn for. `as_role` previews another tier (a role id) and is
    only honoured for callers who manage users or roles: it is a way to check what a tier sees.
    """
    ctx = ctx_of(request)
    epoch = ctx.store.authorization_epoch()
    principal = principal_of(request)

    def validate():
        if ctx.store.authorization_epoch() != epoch:
            raise AuthorizationChanged("The graph viewer's permissions changed")

    access = current_access(ctx.store, principal.access)
    if principal.user is not None:
        user = ctx.store.get_user(principal.user_id)
        role = ctx.store.get_role(user.get("role_id")) if user else None
        if not user or user.get("disabled") or not role:
            raise AuthorizationChanged("The graph viewer is no longer available")
        principal = Principal(user=user, role={**role, "rank": access.rank}, access=access)
    validate()
    if not as_role:
        return principal, None, validate
    if not (principal.can("manage_users") or principal.can("manage_roles")):
        raise HTTPException(403, "previewing another role needs 'manage_users' or 'manage_roles'")
    role = ctx.store.get_role(as_role)
    if role is None:
        raise HTTPException(400, "no such role")
    if not principal.is_open and role["rank"] > principal.rank:
        raise HTTPException(403, "you can only preview tiers at or below your own")
    validate()
    return principal.as_role(role), role, validate


def label_at(index: GraphIndex, vertex: int) -> str:
    """
    What the page calls a node.

    Entities and passages keep `name_of`. A code node gets its **display** name
    (`pyapp.orders.OrderService.place`), because `Symbol.qualname` is module-relative by S2.6 - two
    `Base` classes in two packages would otherwise be two nodes with one label and no way to tell
    them apart in a filter, a tooltip or the side panel.
    """
    if index.node_kind[vertex] in CODE_KINDS:
        return path_tools.display_at(index, vertex)
    return index.name_of(vertex)


def tiers_of(ctx, index: GraphIndex, sources) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """
    Per source: its tier {id, name, rank}. Per node id: the most permissive tier it is visible from
    (a passage's or code node's source tier; for an entity, the lowest tier among the visible
    passages mentioning it).
    """
    roles = {r["id"]: r for r in ctx.store.list_roles()}
    source_tier: dict[str, dict[str, Any]] = {}
    for source in sources:
        role = roles.get(source.get("access_role_id") or "")
        source_tier[source["id"]] = (
            {"id": role["id"], "name": role["name"], "rank": role["rank"]} if role else dict(EVERYONE_TIER)
        )
    node_tier: dict[str, dict[str, Any]] = {}
    for p in index.passages:
        node_tier[p.id] = source_tier.get(p.source_id, dict(EVERYONE_TIER))
    # A code node carries its source directly. It has no MENTIONS edge (D1), so the mention loop
    # below never reaches it and it would otherwise render as "Everyone" whatever its repo's tier.
    for node in index.code_nodes:
        node_tier[node.id] = source_tier.get(node.source_id, dict(EVERYONE_TIER))
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
    actor, _, validate_actor = viewer(request, None)
    principal, preview, validate_viewer = (
        viewer(request, as_role) if as_role else (actor, None, validate_actor)
    )
    manager = query_session(ctx, principal.access) if ctx.store.ping() else nullcontext(None)
    with manager as session:
        view = source_view(ctx, principal.access, session=session) if session is not None else None

        def validate():
            validate_actor()
            validate_viewer()
            if view:
                view.validate()

        roles = ctx.store.list_roles() if ctx.store.ping() else []
        can_preview = actor.can("manage_users") or actor.can("manage_roles")
        previewable = [r for r in roles if actor.is_open or r["rank"] <= actor.rank] if can_preview else []
        return render(
            request,
            "graph.html",
            session=session if not preview else None,
            nav="graph",
            principal=principal,
            preview_role=preview,
            previewable=previewable,
            sources=view.sources if view else [],
            authorization_check=validate,
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
    principal, preview, validate_viewer = viewer(request, as_role or None)
    try:
        with query_session(ctx, principal.access) as session:
            view = source_view(ctx, principal.access, session=session)
            index = view.graph
            source_tier, node_tier = tiers_of(ctx, index, view.sources)
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
                    if index.node_kind[v] in CODE_KINDS:
                        # a symbol, table or commit names its own source; it needs no mention edge
                        node = index.code_node_at(v)
                        return bool(node and node.source_id == source)
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
                if text and text not in label_at(index, v).lower():
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
            labels = path_tools.community_labels(index)  # once: it walks every code node
            nodes = []
            for v in shown:
                node_id = index.node_ids[v]
                node: dict[str, Any] = {
                    "id": node_id,
                    "label": label_at(index, v),
                    "kind": index.node_kind[v],
                    "degree": int(degree[v]),
                    "tier": node_tier.get(node_id, EVERYONE_TIER)["name"],
                    "tier_rank": node_tier.get(node_id, EVERYONE_TIER)["rank"],
                }
                if index.node_kind[v] == PASSAGE:
                    p = index.passages[index.passage_position(v)]
                    node["source_id"] = p.source_id
                    node["source_name"] = p.source_name
                elif index.node_kind[v] in CODE_KINDS:
                    code = index.code_node_at(v)
                    node.update(
                        code_kind=code.code_kind or code.kind,
                        lang=code.lang,
                        path=code.path,
                        source_id=code.source_id,
                        source_name=code.source_name,
                        community=code.community,
                        community_label=labels.get(code.community, "") if code.community is not None else "",
                    )
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
            payload = {
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
                    {"id": sid, "tier": tier["name"], "tier_rank": tier["rank"]}
                    for sid, tier in source_tier.items()
                ],
            }
            view.validate()
            validate_viewer()
            return payload
    finally:
        validate_viewer()


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
    principal, _preview, validate_viewer = viewer(request, body.as_role or None)
    try:
        with query_session(ctx, principal.access, settings=body.settings) as session:
            return _light_up_response(ctx, principal, body, session, validate_viewer)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OllamaError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    finally:
        validate_viewer()


def _light_up_response(ctx, principal, body, session, validate_viewer):
    index, model, validate = session.graph, session.model, session.validate
    trace = ask_service._search(
        ctx,
        index,
        AuthorizedModel(model, validate_viewer),
        body.question.strip(),
        body.settings,
        effective_settings=session.settings,
    )
    validate()
    validate_viewer()
    top = max(1, min(int(body.top_passages), 50))
    explanation = explain(index, trace, top_passages=top)
    view = source_view(ctx, principal.access, session=session)
    _source_tier, node_tier = tiers_of(ctx, index, view.sources)

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
    payload = {
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
    view.validate()
    validate()
    validate_viewer()
    return payload


# ------------------------------------------------------------ one node


@api.get("/node/{node_id}")
def node_details(request: Request, node_id: str, as_role: str = ""):
    ctx = ctx_of(request)
    principal, _preview, validate_viewer = viewer(request, as_role or None)
    try:
        with query_session(ctx, principal.access) as session:
            view = source_view(ctx, principal.access, session=session)
            index = view.graph
            vertex = index.idx_of.get(node_id)
            if vertex is None:
                raise HTTPException(404, "unknown node")
            _source_tier, node_tier = tiers_of(ctx, index, view.sources)
            neighbours = sorted(index.neighbors(vertex), key=lambda t: -t[1])
            kind = index.node_kind[vertex]
            out: dict[str, Any] = {
                "id": node_id,
                "kind": kind,
                "label": label_at(index, vertex),
                "tier": node_tier.get(node_id, EVERYONE_TIER)["name"],
                "degree": len(neighbours),
                "neighbours": [
                    {
                        "id": index.node_ids[o],
                        "label": label_at(index, o),
                        "kind": index.node_kind[o],
                        "weight": round(float(w), 3),
                        "kinds": (index.edge_between(vertex, o) or _NO_EDGE).kinds,
                    }
                    for o, w in neighbours[:60]
                ],
            }
            if kind == PASSAGE:
                p = index.passages[index.passage_position(vertex)]
                evidence = retrieval_fields(index, [p.id])
                item = evidence["retrieval_evidence"][0]
                out.update(is_derived=item["is_derived"], citation_ids=item["citation_ids"], **evidence)
                out.update(
                    title=p.title,
                    source_id=p.source_id,
                    source_name=p.source_name,
                    ordinal=p.ordinal,
                    text=p.text,
                    facts=[f.triple for f in index.facts if p.id in f.passage_ids][:40],
                    defines=[
                        {"id": index.node_ids[v], "label": label_at(index, v)}
                        for v in sorted(index.symbols_defined_in(vertex), key=lambda v: label_at(index, v))
                    ],
                )
            elif kind in CODE_KINDS:
                out.update(_code_panel(ctx, index, vertex, settings=session.settings))
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
            view.validate()
            validate_viewer()
            return out
    finally:
        validate_viewer()


MAX_PANEL_EDGES = 60  # a hub symbol has hundreds of callers; the panel shows the first page


def sorted_edges(index: GraphIndex, edges) -> list:
    """
    Code relations in a backend-independent order: (kind, target name, source name).

    `code_out`/`code_in` come back in load order and no graph promises one - Neo4j least of all -
    so a panel that rendered them unsorted would list the same relations differently per backend
    (WP1's handoff, and the same sort `paths._walkable` uses).
    """
    return sorted(
        edges,
        key=lambda e: (e.kind, path_tools.display_at(index, e.dst), path_tools.display_at(index, e.src)),
    )


def _code_panel(ctx, index: GraphIndex, vertex: int, *, settings=None) -> dict[str, Any]:
    """The per-kind body of the side panel for a symbol, data object or commit."""
    node = index.code_node_at(vertex)
    assert node is not None  # the caller checked node_kind
    theta = float((ctx.store.get_settings() if settings is None else settings).get("code_theta", 0.0))
    rows = path_tools.triple_rows
    out: dict[str, Any] = {
        "code_kind": node.code_kind or node.kind,
        "lang": node.lang,
        "path": node.path,
        "source_id": node.source_id,
        "source_name": node.source_name,
        "community": node.community,
        "community_label": path_tools.community_labels(index).get(node.community, "")
        if node.community is not None
        else "",
        "defined_in": [
            {"id": index.node_ids[v], "title": index.name_of(v)}
            for v in sorted(index.defining_passages(vertex), key=lambda v: index.name_of(v))
        ],
    }
    out_edges = sorted_edges(index, index.out_edges(vertex))
    in_edges = sorted_edges(index, index.in_edges(vertex))
    if node.kind == SYMBOL:
        out.update(
            qualname=node.qualname,
            signature=node.signature,
            doc=node.doc,
            line_start=node.line_start,
            line_end=node.line_end,
            is_test=node.is_test,
            raises=list(node.raises),
            callees=rows(index, [e for e in out_edges if index.node_kind[e.dst] in CODE_KINDS])[
                :MAX_PANEL_EDGES
            ],
            callers=rows(index, [e for e in in_edges if index.node_kind[e.src] == SYMBOL])[:MAX_PANEL_EDGES],
            tests=path_tools.test_rows(index, path_tools.tests_for(index, [vertex], theta=theta)),
            commits=path_tools.history_rows(path_tools.history(index, vertex, limit=5)),
        )
    elif node.kind == DATA:
        out.update(
            dialect=node.dialect,
            readers=rows(index, [e for e in in_edges if e.kind == "READS"])[:MAX_PANEL_EDGES],
            writers=rows(index, [e for e in in_edges if e.kind == "WRITES"])[:MAX_PANEL_EDGES],
        )
    else:  # COMMIT
        out.update(
            sha=node.sha,
            author=node.author,
            date=node.date,
            message=node.message,
            ordinal=node.ordinal,
            modifies=rows(index, [e for e in out_edges if e.kind == "MODIFIES"])[:MAX_PANEL_EDGES],
        )
    return out


class _NoEdge:
    kinds: list[str] = []


_NO_EDGE = _NoEdge()
