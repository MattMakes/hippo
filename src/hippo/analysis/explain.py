"""
Explain a search: why did each passage end up where it did?

A `Trace` (from the retriever) records the seeds and the final ranking, but
not the link between them. This module fills that gap for the Analyze page:

* for each top passage, which seed entities it mentions directly, or - when
  it mentions none - the shortest path from the strongest seed to it
* one plain sentence ("why") a person can read without knowing PageRank
* a small subgraph (seeds + most activated nodes + top passages, and every
  edge among them) for the graph picture
* the candidate facts with their passage titles filled in

Nothing here calls the LLM or the database; it only reads the in-memory graph.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import igraph as ig

from ..hipporag.graph_index import PASSAGE, GraphIndex
from ..hipporag.retriever import RankedPassage, SeedEntity, Trace

MAX_PATH_HOPS = 3  # longer paths are not a useful explanation; we say "no short path" instead


@dataclass
class PassageExplanation:
    passage_id: str
    title: str
    rank: int
    score: float
    dpr_rank: int
    # seed entities this passage mentions: {entity_id, name, seed_weight, edge_weight}
    linked_seeds: list[dict[str, Any]] = field(default_factory=list)
    # names along the path, seed first, passage last (empty when directly linked)
    path: list[str] = field(default_factory=list)
    why: str = ""


@dataclass
class Explanation:
    passages: list[PassageExplanation]
    subgraph: dict[str, list[dict[str, Any]]]  # {"nodes": [...], "edges": [...]}
    facts: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def explain(
    index: GraphIndex, trace: Trace, *, top_passages: int = 10, graph: ig.Graph | None = None
) -> Explanation:
    """
    Explain the top passages of `trace` using `index`.

    `graph` is optional: pass the edited graph of a simulation so paths and edge weights
    match what PPR actually ran on. By default the index's own graph is used.
    """
    graph = graph or index.graph
    seeds = [s for s in trace.seed_entities if s.kept and s.weight > 0]
    seeds.sort(key=lambda s: -s.weight)
    passages = [
        _explain_passage(index, graph, trace, seeds, ranked) for ranked in trace.passages[:top_passages]
    ]
    return Explanation(
        passages=passages,
        subgraph=_subgraph(index, graph, trace, passages),
        facts=_facts_with_titles(index, trace),
    )


# ------------------------------------------------------------ one passage


def _explain_passage(
    index: GraphIndex, graph: ig.Graph, trace: Trace, seeds: list[SeedEntity], ranked: RankedPassage
) -> PassageExplanation:
    out = PassageExplanation(ranked.passage_id, ranked.title, ranked.rank, ranked.score, ranked.dpr_rank)
    if trace.used_dpr_fallback:
        out.why = (
            f"Ranked by plain similarity to the question (embedding rank {ranked.dpr_rank}) "
            f"because {trace.fallback_reason or 'the graph search was skipped'}."
        )
        return out

    vertex = index.idx_of.get(ranked.passage_id)
    if vertex is None:  # the graph changed since the trace was recorded
        out.why = "This passage is no longer in the graph."
        return out

    out.linked_seeds = _linked_seeds(index, graph, seeds, vertex)
    if out.linked_seeds:
        out.why = _why_direct(out.linked_seeds)
        return out

    out.path = _path_from_strongest_seed(index, graph, seeds, vertex)
    out.why = _why_path(out.path, ranked)
    return out


def _linked_seeds(
    index: GraphIndex, graph: ig.Graph, seeds: list[SeedEntity], vertex: int
) -> list[dict[str, Any]]:
    """Seeds this passage is directly connected to (normally: it mentions the entity)."""
    weights = {other: w for other, w in index.neighbors(vertex, graph)}
    linked = []
    for seed in seeds:
        weight = weights.get(seed.vertex)
        if weight is None or weight <= 0:
            continue
        linked.append(
            {
                "entity_id": seed.entity_id,
                "name": seed.name,
                "seed_weight": seed.weight,
                "edge_weight": weight,
            }
        )
    return linked


def _path_from_strongest_seed(
    index: GraphIndex, graph: ig.Graph, seeds: list[SeedEntity], vertex: int
) -> list[str]:
    """
    Names along the shortest path (by hop count, which is what people understand) from the
    strongest seed that reaches this passage within MAX_PATH_HOPS. Empty if none does.
    """
    for seed in seeds:  # already sorted strongest first
        paths = graph.get_shortest_paths(seed.vertex, to=vertex, weights=None, output="vpath")
        path = paths[0] if paths else []
        if path and len(path) - 1 <= MAX_PATH_HOPS:
            return [index.name_of(v) for v in path]
    return []


def _why_direct(linked: list[dict[str, Any]]) -> str:
    first = linked[0]
    sentence = f"Directly mentions seed '{first['name']}' (weight {first['seed_weight']:.2f})"
    others = [f"'{s['name']}'" for s in linked[1:]]
    if others:
        sentence += " and " + ", ".join(others)
    return sentence + "."


def _why_path(path: list[str], ranked: RankedPassage) -> str:
    if not path:
        return (
            f"No seed reaches this passage within {MAX_PATH_HOPS} hops; its score comes from its own "
            f"similarity to the question (embedding rank {ranked.dpr_rank})."
        )
    hops = len(path) - 1
    via = " -> ".join(f"'{name}'" for name in path[1:-1])
    return f"Reached in {hops} hop{'s' if hops != 1 else ''} from seed '{path[0]}' via {via}."


# --------------------------------------------------------------- subgraph


def _subgraph(
    index: GraphIndex, graph: ig.Graph, trace: Trace, passages: list[PassageExplanation]
) -> dict[str, list[dict[str, Any]]]:
    """Seeds + top PPR nodes + top passages, with every edge among them."""
    nodes: dict[int, dict[str, Any]] = {}  # vertex -> node dict, first writer wins for the label
    rank_of = {p.passage_id: p.rank for p in passages}
    score_of = {n.vertex: n.score for n in trace.top_nodes}

    def add(vertex: int, node_id: str, label: str, kind: str, *, is_seed: bool, seed_weight: float) -> None:
        node = nodes.setdefault(
            vertex,
            {
                "id": node_id,
                "label": label,
                "kind": kind,
                "score": score_of.get(vertex, 0.0),
                "is_seed": False,
                "seed_weight": 0.0,
                "rank": rank_of.get(node_id),
            },
        )
        node["is_seed"] = node["is_seed"] or is_seed
        node["seed_weight"] = max(node["seed_weight"], seed_weight)

    for seed in trace.seed_entities:
        add(seed.vertex, seed.entity_id, seed.name, "entity", is_seed=seed.kept, seed_weight=seed.weight)
    for top in trace.top_nodes:
        add(top.vertex, top.node_id, top.name, top.kind, is_seed=top.is_seed, seed_weight=0.0)
    for p in passages:
        vertex = index.idx_of.get(p.passage_id)
        if vertex is not None:
            add(vertex, p.passage_id, p.title, PASSAGE, is_seed=False, seed_weight=0.0)
            nodes[vertex]["score"] = max(nodes[vertex]["score"], p.score)

    edges = []
    for vertex in nodes:
        for other, weight in index.neighbors(vertex, graph):
            if other not in nodes or other <= vertex:  # each undirected edge once
                continue
            known = index.edge_between(vertex, other)
            edges.append(
                {
                    "source": nodes[vertex]["id"],
                    "target": nodes[other]["id"],
                    "weight": weight,
                    "kinds": known.kinds if known else ["tuned"],  # only an edit can add a brand-new edge
                }
            )
    return {"nodes": list(nodes.values()), "edges": edges}


# ------------------------------------------------------------------ facts


def _facts_with_titles(index: GraphIndex, trace: Trace) -> list[dict[str, Any]]:
    out = []
    for candidate in trace.fact_candidates:
        row = asdict(candidate)
        row["passages"] = [
            {"passage_id": pid, "title": passage.title if passage else pid}
            for pid in candidate.passage_ids
            for passage in [index.passage_by_id(pid)]
        ]
        out.append(row)
    return out


__all__ = ["Explanation", "PassageExplanation", "explain", "MAX_PATH_HOPS"]
