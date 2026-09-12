"""Reconstruct saved evidence from a current audience view, never saved labels.

The caller must authorize the saved question/owner separately. Generated answers
can be reused only when their original complete input view still matches; old
outputs without a fingerprint are withheld rather than guessed to be safe.
"""

import hashlib
from dataclasses import asdict, replace

from hippo.hipporag import paths
from hippo.hipporag.retriever import Trace
from hippo.store.base import validate_settings

from .citations import provenance_payload
from .dense import fingerprint_vectors
from .identity import canonical_json


def view_fingerprint(graph) -> str:
    graph.validate_authorization()
    passage_vectors, fact_vectors = fingerprint_vectors(graph)
    payload = [
        graph.node_ids,
        graph.node_kind,
        graph.entity_names,
        [asdict(passage) for passage in graph.passages],
        [asdict(node) for node in graph.code_nodes],
        [asdict(fact) for fact in graph.facts],
        passage_vectors,
        fact_vectors,
        graph.entity_boost.tolist(),
        graph.specificity.tolist(),
        [(list(pair), asdict(edge)) for pair, edge in sorted(graph.edges.items())],
        [asdict(edge) for _, arrows in sorted(graph.code_out.items()) for edge in arrows],
    ]
    if extension := provenance_payload(graph):
        payload.append(extension)
    fingerprint = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    graph.validate_authorization()
    return fingerprint


def can_reuse_answer(graph, fingerprint: str) -> bool:
    return bool(fingerprint and fingerprint == view_fingerprint(graph))


def reconstruct_trace(graph, original: Trace, *, question: str) -> Trace:
    """Saved IDs select evidence; saved prose and scores never authorize it."""
    graph.validate_authorization()
    trace = Trace(
        question=question,
        settings=validate_settings(original.settings),
        graph_version=graph.version,
        snapshot_ids=tuple(getattr(graph, "snapshot_ids", ())),
    )
    for row in original.passages:
        passage = graph.passage_by_id(row.passage_id)
        if passage is not None:
            trace.passages.append(
                replace(
                    row,
                    rank=len(trace.passages) + 1,
                    score=0.0,
                    dpr_rank=0,
                    dpr_score=0.0,
                    title=passage.title,
                    source_id=passage.source_id,
                    source_name=passage.source_name,
                    preview=passage.text,
                    community_boosted=False,
                )
            )
    for row in original.fact_candidates:
        position = graph.fact_index_of.get(row.fact_id)
        if position is not None:
            fact = graph.facts[position]
            trace.fact_candidates.append(
                replace(
                    row,
                    triple=fact.triple,
                    score=0.0,
                    rank=len(trace.fact_candidates) + 1,
                    reason="current visible evidence",
                    passage_ids=list(fact.passage_ids),
                )
            )
    fact_ids = {row.fact_id for row in trace.fact_candidates}
    for row in original.seed_entities:
        if row.entity_id in graph.entity_names:
            vertex = graph.idx_of[row.entity_id]
            trace.seed_entities.append(
                replace(
                    row,
                    name=graph.entity_names[row.entity_id],
                    vertex=vertex,
                    weight=0.0,
                    fact_score_sum=0.0,
                    occurrences=0,
                    passage_count=int(graph.specificity[vertex]),
                    boost=float(graph.entity_boost[vertex]),
                    from_fact_ids=[identity for identity in row.from_fact_ids if identity in fact_ids],
                )
            )
    for row in original.seed_passages:
        passage = graph.passage_by_id(row.passage_id)
        if passage is not None:
            trace.seed_passages.append(
                replace(
                    row,
                    title=passage.title,
                    vertex=graph.idx_of[passage.id],
                    dpr_score=0.0,
                    weight=0.0,
                )
            )
    for row in original.seed_symbols:
        node = graph.code_node_by_id(row.node_id)
        if node is not None:
            vertex = graph.idx_of[node.id]
            trace.seed_symbols.append(
                replace(
                    row,
                    name=paths.display_of(node),
                    vertex=vertex,
                    weight=0.0,
                    token="",
                    kind=node.kind,
                    n_matches=1,
                    matched_by="",
                    ambiguous=False,
                    specificity=float(graph.specificity[vertex]),
                    boost=float(graph.entity_boost[vertex]),
                    how="replay",
                )
            )
    for row in original.top_nodes:
        if row.node_id in graph.idx_of:
            vertex = graph.idx_of[row.node_id]
            trace.top_nodes.append(
                replace(
                    row,
                    name=graph.name_of(vertex),
                    vertex=vertex,
                    kind=graph.node_kind[vertex],
                    score=0.0,
                )
            )
    requested = {(row.get("a"), row.get("b"), row.get("kind")) for row in original.paths}
    arrows = [
        edge
        for values in graph.code_out.values()
        for edge in values
        if (graph.node_ids[edge.src], graph.node_ids[edge.dst], edge.kind) in requested
    ]
    trace.paths = paths.triple_rows(graph, arrows)
    vertices = [row.vertex for row in trace.seed_symbols]
    test_ids = {row.get("id") for row in original.tests}
    trace.tests = paths.test_rows(
        graph, [node for node in paths.tests_for(graph, vertices, theta=0.0) if node.id in test_ids]
    )
    history_ids = {row.get("id") for row in original.history}
    commits = {
        node.id: node
        for vertex in vertices
        for node in paths.history(graph, vertex)
        if node.id in history_ids
    }
    trace.history = paths.history_rows(list(commits.values()))
    trace.used_code_seeds = bool(original.used_code_seeds and trace.seed_symbols)
    trace.filter = {
        "kept_triples": [row.triple for row in trace.fact_candidates if row.kept],
        "replayed": True,
    }
    passage_ids = {passage.id for passage in graph.passages}
    trace.select = {
        key: [identity for identity in original.select.get(key, []) if identity in passage_ids]
        for key in ("keep", "drop", "expand")
    }
    graph.validate_authorization()
    return trace
