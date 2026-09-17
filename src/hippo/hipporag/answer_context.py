"""Select bounded, source-backed supplemental context for code answers."""

from __future__ import annotations

from collections import deque

from ..knowledge.citations import CitationBundle, resolve_citations
from .graph_index import PASSAGE, SYMBOL, GraphIndex
from .retriever import DENSE, Trace

MAX_CODE_EVIDENCE_PASSAGES = 10
MAX_CODE_EVIDENCE_CHARS = 6_000
MAX_VISITED_SYMBOLS = 64
MAX_INVOKES_HOPS = 2
INITIALIZER_NAMES = frozenset({"constructor", "__init__", "__new__", "init", "new"})


def select_answer_passage_ids(graph: GraphIndex, trace: Trace) -> list[str]:
    """Return the ranked answer slice followed by a bounded lexical-code neighborhood."""
    selected = _base_answer_passage_ids(graph, trace)
    selected_set = set(selected)

    extra_limit = min(
        max(int(trace.settings.get("code_expand_max", MAX_CODE_EVIDENCE_PASSAGES)), 0),
        MAX_CODE_EVIDENCE_PASSAGES,
    )
    if not trace.used_code_seeds or extra_limit == 0:
        return selected

    seed_vertices: list[int] = []
    visited: set[int] = set()
    for seed in trace.seed_symbols:
        vertex = seed.vertex
        if (
            not seed.kept
            or seed.ambiguous
            or seed.how == DENSE
            or seed.kind != SYMBOL
            or vertex < 0
            or vertex >= len(graph.node_kind)
            or graph.node_kind[vertex] != SYMBOL
            or graph.node_ids[vertex] != seed.node_id
            or vertex in visited
        ):
            continue
        visited.add(vertex)
        seed_vertices.append(vertex)
        if len(visited) >= MAX_VISITED_SYMBOLS:
            break

    ordered_symbols = list(seed_vertices)
    for seed_vertex in seed_vertices:
        for initializer in _containing_initializers(graph, seed_vertex):
            if initializer in visited or len(visited) >= MAX_VISITED_SYMBOLS:
                continue
            visited.add(initializer)
            ordered_symbols.append(initializer)

    theta = float(trace.settings.get("code_theta", 0.5))
    queue = deque((vertex, 0) for vertex in seed_vertices)
    while queue and len(visited) < MAX_VISITED_SYMBOLS:
        vertex, hops = queue.popleft()
        if hops >= MAX_INVOKES_HOPS:
            continue
        for edge in sorted(
            graph.out_edges(vertex),
            key=lambda row: (graph.node_ids[row.dst], row.kind, row.provenance, row.omega),
        ):
            target = edge.dst
            if (
                edge.kind != "INVOKES"
                or edge.omega < theta
                or target in visited
                or target < 0
                or target >= len(graph.node_kind)
                or graph.node_kind[target] != SYMBOL
            ):
                continue
            visited.add(target)
            ordered_symbols.append(target)
            queue.append((target, hops + 1))
            if len(visited) >= MAX_VISITED_SYMBOLS:
                break

    extra_chars = 0
    extras = 0
    for vertex in ordered_symbols:
        for passage_vertex in sorted(graph.defining_passages(vertex)):
            if passage_vertex < 0 or passage_vertex >= len(graph.node_kind):
                continue
            if graph.node_kind[passage_vertex] != PASSAGE:
                continue
            passage = graph.passages[graph.passage_position(passage_vertex)]
            if passage.id in selected_set:
                continue
            if extra_chars + len(passage.text) > MAX_CODE_EVIDENCE_CHARS:
                continue
            selected.append(passage.id)
            selected_set.add(passage.id)
            extra_chars += len(passage.text)
            extras += 1
            if extras >= extra_limit:
                return selected
    return selected


def select_answer_citations(graph: GraphIndex, trace: Trace) -> CitationBundle:
    """Resolve once, then admit only complete supplemental original-citation groups."""
    base_ids = _base_answer_passage_ids(graph, trace)
    selected_ids = select_answer_passage_ids(graph, trace)
    if not selected_ids:
        return CitationBundle((), ())

    resolved = resolve_citations(graph, tuple(selected_ids))
    base_id_set = set(base_ids)
    base_items = [item for item in resolved.items if item.passage_id in base_id_set]
    accepted_items = list(base_items)
    seen_citation_ids = {identity for item in base_items for identity in item.citation_ids}
    originals = {citation.id: citation for citation in resolved.citations}
    extra_limit = min(
        max(int(trace.settings.get("code_expand_max", MAX_CODE_EVIDENCE_PASSAGES)), 0),
        MAX_CODE_EVIDENCE_PASSAGES,
    )
    extra_count = 0
    extra_chars = 0

    for item in resolved.items:
        if item.passage_id in base_id_set:
            continue
        novel_ids = [identity for identity in item.citation_ids if identity not in seen_citation_ids]
        novel_chars = sum(len(originals[identity].text) for identity in novel_ids)
        if extra_count + len(novel_ids) > extra_limit:
            continue
        if extra_chars + novel_chars > MAX_CODE_EVIDENCE_CHARS:
            continue
        accepted_items.append(item)
        seen_citation_ids.update(novel_ids)
        extra_count += len(novel_ids)
        extra_chars += novel_chars

    accepted_citations = {
        identity: originals[identity]
        for item in accepted_items
        for identity in item.citation_ids
    }
    return CitationBundle(tuple(accepted_items), tuple(accepted_citations.values()))


def _base_answer_passage_ids(graph: GraphIndex, trace: Trace) -> list[str]:
    """Return the unchanged ranked base slice, omitting unavailable and duplicate rows."""
    qa_top_k = int(trace.settings.get("qa_top_k", 5))
    selected: list[str] = []
    selected_set: set[str] = set()
    base_slice = [passage for passage in trace.passages if not passage.via_expand][:qa_top_k]
    for ranked in base_slice:
        passage = graph.passage_by_id(ranked.passage_id)
        if passage is not None and passage.id not in selected_set:
            selected.append(passage.id)
            selected_set.add(passage.id)
    return selected


def _containing_initializers(graph: GraphIndex, method_vertex: int) -> list[int]:
    """Immediate initializer children of actual type parents, never module siblings."""
    method = graph.code_node_at(method_vertex)
    if method is None or method.code_kind != "method":
        return []
    parents = sorted(
        {
            edge.src
            for edge in graph.in_edges(method_vertex)
            if edge.kind == "CONTAINS"
            and (parent := graph.code_node_at(edge.src)) is not None
            and parent.kind == SYMBOL
            and parent.code_kind == "class"
        },
        key=lambda vertex: graph.node_ids[vertex],
    )
    initializers: set[int] = set()
    for parent in parents:
        for edge in graph.out_edges(parent):
            child = graph.code_node_at(edge.dst)
            if (
                edge.kind == "CONTAINS"
                and child is not None
                and child.kind == SYMBOL
                and child.code_kind == "method"
                and child.name.casefold() in INITIALIZER_NAMES
            ):
                initializers.add(edge.dst)
    return sorted(initializers, key=lambda vertex: graph.node_ids[vertex])
