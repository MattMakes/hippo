"""Rebuild the managed HippoRAG compatibility view from authorized evidence.

Native rows supply only verified, text-bound vectors. Their labels, bodies, facts,
edges, boosts and aggregate statistics never become managed evidence. This module
does not grant access: callers must validate their proof before and after building
and attach its authorization callback to the resulting GraphIndex.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict

import numpy as np

from hippo.hipporag.graph_index import (
    CODE_KINDS,
    CodeNode,
    DirectedEdge,
    Edge,
    GraphIndex,
    Passage,
    _community_labels,
    _name_index,
    _path_index,
    build_igraph,
)
from hippo.hipporag.text import split_identifier
from hippo.store.code import SPECIFICITY_KINDS

from .access import AuthorizedEvidence
from .identity import canonical_json, normalize_relative_path
from .predicates import PREDICATES


class ProjectionError(ValueError):
    """The supplied graph/evidence cannot establish a coherent current view."""


def _current_generations(store, authorized, embedding_profile):
    selection = authorized.selection
    if selection.query_mode != "current" or selection.generation_ids is None:
        raise ProjectionError("Managed compatibility projection requires explicit current generations")
    generations = {}
    source_ids = set()
    for identity in sorted(selection.generation_ids):
        generation = store._knowledge_get("Generation", identity)
        source = store.get_source(generation.source_id) if generation else None
        if (
            generation is None
            or generation.status != "active"
            or generation.embedding_profile != embedding_profile
            or source is None
            or source.get("workspace_id") != authorized.workspace_id
            or source.get("active_generation_id") != identity
            or generation.source_id in source_ids
        ):
            raise ProjectionError("Selected generation is not the current compatible workspace generation")
        generations[identity] = generation
        source_ids.add(generation.source_id)
    return generations


def _passage_bindings(store, generations):
    if not generations:
        return []
    if store.knowledge_backend == "fake":
        return [row for row in store.passages.values() if row.get("generation_id") in generations]
    return store.run(
        "MATCH (p:Passage)-[:FROM]->(s:Source) WHERE p.generation_id IN $generations "
        "RETURN p.id AS id, s.id AS source_id, p.text AS text, p.embedding AS embedding, "
        "p.span_id AS span_id, p.artifact_revision_id AS artifact_revision_id, "
        "p.generation_id AS generation_id, p.embedding_profile AS embedding_profile",
        generations=sorted(generations),
    )


def _safe_vectors(full, store, generations, spans, revisions, artifacts, embedding_profile, members):
    """Reuse only vectors with an exact persisted and cached input binding."""
    positions = {passage.id: index for index, passage in enumerate(full.passages)}
    vectors = {}
    for row in sorted(_passage_bindings(store, generations), key=lambda item: item["id"]):
        span = spans.get(row.get("span_id"))
        position = positions.get(row["id"])
        generation = generations.get(row.get("generation_id"))
        if span is None or position is None or generation is None:
            continue
        source_id = artifacts[revisions[span.revision_id].artifact_id].source_id
        passage = full.passages[position]
        if (
            row.get("artifact_revision_id") != span.revision_id
            or (generation.id, span.revision_id) not in members
            or row.get("embedding_profile") != embedding_profile
            or row.get("source_id") != source_id
            or generation.source_id != source_id
            or passage.source_id != source_id
            or row.get("text") != span.text
            or passage.text != span.text
        ):
            continue
        try:
            vector = np.asarray(row.get("embedding"), dtype=np.float32)
        except (ValueError, TypeError):
            continue
        if vector.ndim != 1 or not vector.size or not np.all(np.isfinite(vector)):
            continue
        if not np.array_equal(vector, full.passage_embeddings[position]):
            continue
        if span.id in vectors and not np.array_equal(vector, vectors[span.id]):
            raise ProjectionError("One evidence span has conflicting vectors for the same profile")
        vectors[span.id] = vector.copy()
    if len({len(vector) for vector in vectors.values()}) > 1:
        raise ProjectionError("Authorized vectors have incompatible dimensions")
    return vectors


def _attributes(observations):
    # Until temporal conflict resolution exists, retain only fields explicitly
    # identical in every current observation. Do not synthesize a merged record
    # or treat observation/ingestion order as supersession authority.
    payloads = [json.loads(observation.attributes_json) for observation in observations]
    if not payloads or any(not isinstance(payload, dict) for payload in payloads):
        return {}
    return {
        key: value
        for key, value in payloads[0].items()
        if all(
            key in payload and canonical_json(payload[key]) == canonical_json(value)
            for payload in payloads[1:]
        )
    }


def _code_node(obj, kind, observations, source_id):
    attributes = _attributes(observations)

    def text(key):
        return attributes.get(key) if isinstance(attributes.get(key), str) else ""

    path = text("path")
    if path:
        try:
            path = normalize_relative_path(path)
        except ValueError:
            path = ""
    name = text("name") or text("qualname") or obj.kind
    node = CodeNode(
        obj.id,
        kind,
        name,
        qualname=text("qualname"),
        code_kind=text("code_kind") or text("kind"),
        lang=text("lang"),
        path=path,
        signature=text("signature"),
        doc=text("doc"),
        dialect=text("dialect"),
        sha=text("sha"),
        author=text("author"),
        date=text("date"),
        message=text("message"),
        source_id=source_id,
        name_tokens=split_identifier(name),
    )
    for key in ("line_start", "line_end", "ordinal"):
        value = attributes.get(key)
        if type(value) is int and value >= 0:
            setattr(node, key, value)
    node.is_test = attributes.get("is_test") is True
    raises = attributes.get("raises")
    if isinstance(raises, list) and all(isinstance(value, str) for value in raises):
        node.raises = list(raises)
    return node


def project_managed_graph(
    full: GraphIndex, store, authorized: AuthorizedEvidence, *, embedding_profile: str
) -> GraphIndex:
    """Build only the managed lane; no native provenance is inferred from endpoints.

    Projected passage IDs are EvidenceSpan IDs and object IDs are KnowledgeObject
    IDs. Unbound vectors are omitted until indexing supplies the required binding.
    Typed assertions stay out of the legacy OpenIE fact-filter slots. Historical
    generation selection belongs to the later snapshot implementation.
    """
    if not embedding_profile:
        raise ProjectionError("An explicit embedding profile is required")
    generations = _current_generations(store, authorized, embedding_profile)

    def allowed(kind, identities):
        return {row.id: row for row in store._knowledge_rows(kind) if row.id in identities}

    artifacts = allowed("Artifact", authorized.artifact_ids)
    revisions = {
        key: value
        for key, value in allowed("ArtifactRevision", authorized.revision_ids).items()
        if value.artifact_id in artifacts
    }
    members = {
        (row.generation_id, row.artifact_revision_id) for row in store._knowledge_rows("GenerationMember")
    }
    selected_revisions = {revision for generation, revision in members if generation in generations}
    spans = {
        key: value
        for key, value in allowed("EvidenceSpan", authorized.span_ids).items()
        if value.revision_id in revisions and value.revision_id in selected_revisions
    }
    vectors = _safe_vectors(full, store, generations, spans, revisions, artifacts, embedding_profile, members)
    spans = {key: value for key, value in spans.items() if key in vectors}
    observations = defaultdict(list)
    for row in allowed("ObjectObservation", authorized.observation_ids).values():
        if (
            row.recorded_to is None
            and row.span_id in spans
            and row.revision_id == spans[row.span_id].revision_id
        ):
            observations[row.object_id].append(row)
    objects = {
        key: value
        for key, value in allowed("KnowledgeObject", authorized.object_ids).items()
        if key in observations and value.workspace_id == authorized.workspace_id
    }
    bindings = defaultdict(list)
    for binding in allowed("NativeBinding", authorized.native_binding_ids).values():
        if (
            binding.generation_id in generations
            and binding.object_id in objects
            and binding.span_id in spans
            and (binding.generation_id, spans[binding.span_id].revision_id) in members
        ):
            bindings[binding.object_id].append(binding)
    entities, nodes = {}, []
    native_kinds = {"Symbol": "symbol", "DataObject": "data", "Commit": "commit"}
    for identity, obj in sorted(objects.items()):
        observed = observations[identity]
        kinds = {native_kinds[binding.native_kind] for binding in bindings[identity]}
        expected = (
            "symbol"
            if obj.kind == "symbol"
            else "commit"
            if obj.kind == "commit"
            else "data"
            if obj.kind in {"database", "schema", "table", "column", "view", "constraint", "index", "routine"}
            else None
        )
        if kinds == {expected}:
            source_id = min(generations[binding.generation_id].source_id for binding in bindings[identity])
            nodes.append(_code_node(obj, expected, observed, source_id))
        else:
            attributes = _attributes(observed)
            entities[identity] = (
                attributes.get("name") if isinstance(attributes.get("name"), str) else obj.kind
            )
    passages = []
    names_by_span = defaultdict(set)
    for node in nodes:
        for observed in observations[node.id]:
            names_by_span[observed.span_id].add(node.name)
    for ordinal, (identity, span) in enumerate(sorted(spans.items())):
        names = names_by_span[identity]
        locator = json.loads(span.locator_json)
        title = min(names) if names else locator.get("path") or span.locator_kind
        source_id = artifacts[revisions[span.revision_id].artifact_id].source_id
        passages.append(Passage(identity, title, span.text, source_id, "", ordinal))
    edges, arrows = {}, []

    def relation(subject, target, kind, weight, extra=None, mention=False):
        if subject == target:
            return
        edge = edges.setdefault(tuple(sorted((subject, target))), Edge())
        if mention:
            edge.mention = True
        else:
            edge.omega = max(edge.omega, weight)
            if kind.lower() not in edge.code_kinds:
                edge.code_kinds.append(kind.lower())
            arrows.append((subject, target, kind, weight, "authorized_evidence", extra or {}))

    code_ids = {node.id for node in nodes}
    for identity, observed in sorted(observations.items()):
        if identity not in objects:
            continue
        for span_id in sorted({row.span_id for row in observed}):
            # DEFINED_IN is the inherited code-to-passage attachment (written down
            # here), not a newly inferred engineering assertion or path step.
            relation(identity, span_id, "DEFINED_IN", 1.0, mention=identity not in code_ids)
    versions = allowed("AssertionVersion", authorized.assertion_version_ids)
    assertions = allowed("Assertion", authorized.assertion_ids)
    for group in authorized.support_groups:
        version = versions.get(group.assertion_version_id)
        assertion = assertions.get(version.assertion_id) if version else None
        if (
            assertion is None
            or version.status != "active"
            or version.recorded_to is not None
            or not group.span_ids <= spans.keys()
            or assertion.subject_id not in objects
            or assertion.object_id not in objects
        ):
            continue
        if not PREDICATES[assertion.predicate].traversal_permitted:
            continue
        relation(
            assertion.subject_id,
            assertion.object_id,
            assertion.predicate,
            version.confidence,
            dict(
                assertion_version_id=version.id,
                support_span_ids=sorted(group.span_ids),
                derivation_group=group.derivation_group,
            ),
        )
    return _assemble(entities, nodes, passages, vectors, [], {}, edges, arrows)


def _assemble(
    entities, nodes, passages, passage_vectors, facts, fact_vectors, edge_ids, arrow_ids, statistics=None
):
    nodes = sorted(nodes, key=lambda node: CODE_KINDS.index(node.kind))
    identities = list(entities) + [node.id for node in nodes] + [passage.id for passage in passages]
    if len(identities) != len(set(identities)):
        raise ProjectionError("Projection node identities collide")
    index = {identity: i for i, identity in enumerate(identities)}
    edges = {
        (min(index[a], index[b]), max(index[a], index[b])): deepcopy(edge)
        for (a, b), edge in edge_ids.items()
        if a in index and b in index and a != b
    }
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for a, b, kind, weight, provenance, extra in arrow_ids:
        if a not in index or b not in index:
            continue
        arrow = DirectedEdge(index[a], index[b], kind, weight, provenance, deepcopy(extra))
        outgoing[arrow.src].append(arrow)
        incoming[arrow.dst].append(arrow)
    graph = build_igraph(len(identities), edges)
    boosts = np.ones(len(identities))
    specificity = np.zeros(len(identities))
    entity_vertices = {index[identity] for identity in entities}
    for pair, edge in edges.items():
        if edge.mention:
            for vertex in pair:
                if vertex in entity_vertices:
                    specificity[vertex] += 1
    code_vertices = [index[node.id] for node in nodes]
    if statistics is None:
        for node in nodes:
            node.in_degree = sum(
                arrow.kind in SPECIFICITY_KINDS or arrow.kind in PREDICATES
                for arrow in incoming[index[node.id]]
            )
            specificity[index[node.id]] = node.in_degree + 1
        components = graph.induced_subgraph(code_vertices).connected_components()
        for component, members in enumerate(components):
            for position in members:
                nodes[position].community = component
    else:
        for identity, (boost, specific) in statistics.items():
            boosts[index[identity]], specificity[index[identity]] = boost, specific
    passage_matrix = (
        np.stack([passage_vectors[p.id] for p in passages]).astype(np.float32)
        if passages
        else np.zeros((0, 0), dtype=np.float32)
    )
    fact_matrix = (
        np.stack([fact_vectors[f.id] for f in facts]).astype(np.float32)
        if facts
        else np.zeros((0, 0), dtype=np.float32)
    )
    payload = [
        entities,
        [asdict(node) for node in nodes],
        [asdict(passage) for passage in passages],
        passage_matrix.tolist(),
        [asdict(fact) for fact in facts],
        fact_matrix.tolist(),
        [(list(pair), asdict(edge)) for pair, edge in sorted(edges.items())],
        arrow_ids,
        boosts.tolist(),
        specificity.tolist(),
    ]
    version = int(hashlib.sha256(canonical_json(payload).encode()).hexdigest()[:15], 16)
    return GraphIndex(
        version=version,
        node_ids=identities,
        node_kind=["entity"] * len(entities) + [node.kind for node in nodes] + ["passage"] * len(passages),
        idx_of=index,
        entity_names=dict(entities),
        entity_boost=boosts,
        specificity=specificity,
        passages=passages,
        passage_vertices=np.array([index[p.id] for p in passages], dtype=np.int64),
        passage_embeddings=passage_matrix,
        facts=facts,
        fact_embeddings=fact_matrix,
        fact_index_of={fact.id: i for i, fact in enumerate(facts)},
        graph=graph,
        edges=edges,
        code_nodes=nodes,
        code_vertices=np.array(code_vertices, dtype=np.int64),
        code_out=dict(outgoing),
        code_in=dict(incoming),
        name_index=_name_index(nodes),
        path_index=_path_index(nodes),
        communities=_community_labels(nodes),
    )


def compose_graphs(*graphs: GraphIndex) -> GraphIndex:
    """Compose already authorized, disjoint lanes; never pass an unscoped graph.

    This deliberately does not copy authorization callbacks. The caller attaches
    a callback validating all input proofs together. No cross-lane edge is inferred.
    """
    entities, nodes, passages, facts, passage_vectors, fact_vectors, edges, arrows = (
        {},
        [],
        [],
        [],
        {},
        {},
        {},
        [],
    )
    seen = set()
    dimensions = set()
    communities = set()
    statistics = {}
    for graph in graphs:
        if seen.intersection(graph.node_ids):
            raise ProjectionError("Cannot compose colliding graph node identities")
        seen.update(graph.node_ids)
        entities.update(graph.entity_names)
        copied_nodes = deepcopy(graph.code_nodes)
        community_map = {}
        for community in sorted({node.community for node in copied_nodes if node.community is not None}):
            mapped = community if community not in communities else max(communities) + 1
            communities.add(mapped)
            community_map[community] = mapped
        for node in copied_nodes:
            if node.community is not None:
                node.community = community_map[node.community]
        nodes.extend(copied_nodes)
        statistics.update(
            {
                identity: (float(graph.entity_boost[i]), float(graph.specificity[i]))
                for i, identity in enumerate(graph.node_ids)
            }
        )
        passages.extend(deepcopy(graph.passages))
        facts.extend(deepcopy(graph.facts))
        for i, passage in enumerate(graph.passages):
            vector = graph.passage_embeddings[i].copy()
            dimensions.add(len(vector))
            passage_vectors[passage.id] = vector
        for i, fact in enumerate(graph.facts):
            vector = graph.fact_embeddings[i].copy()
            dimensions.add(len(vector))
            if fact.id in fact_vectors:
                raise ProjectionError("Cannot compose colliding fact identities")
            fact_vectors[fact.id] = vector
        for (a, b), edge in graph.edges.items():
            edges[tuple(sorted((graph.node_ids[a], graph.node_ids[b])))] = deepcopy(edge)
        for outgoing in graph.code_out.values():
            for arrow in outgoing:
                arrows.append(
                    (
                        graph.node_ids[arrow.src],
                        graph.node_ids[arrow.dst],
                        arrow.kind,
                        arrow.omega,
                        arrow.provenance,
                        deepcopy(arrow.extra),
                    )
                )
    if len(dimensions) > 1:
        raise ProjectionError("Cannot compose graphs with incompatible vector dimensions")
    result = _assemble(
        entities, nodes, passages, passage_vectors, facts, fact_vectors, edges, arrows, statistics
    )
    populated = [graph for graph in graphs if graph.num_nodes]
    if len(populated) == 1:
        result.version = populated[0].version
    return result
