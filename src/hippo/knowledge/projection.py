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
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from types import SimpleNamespace

import numpy as np

from hippo.hipporag.graph_index import (
    CODE_KINDS,
    CodeNode,
    DirectedEdge,
    Edge,
    Fact,
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
from .citations import (
    OriginalCitation,
    ProseProvenance,
    RetrievalEvidence,
    provenance_payload,
    resolve_citations,
)
from .dense import (
    DenseCapability,
    DenseVector,
    StructuralCodeEvidence,
    StructuralObjectEvidence,
    StructuralRelationEvidence,
    composed_dense_capability,
    fingerprint_vectors,
    structural_code_payload,
)
from .derivations import validate_prose, validate_view
from .embedding_cache import _vectors
from .identity import canonical_json, make_identity, normalize_relative_path
from .lifecycle import generation_passage_id
from .predicates import PREDICATES


class ProjectionError(ValueError):
    """The supplied graph/evidence cannot establish a coherent current view."""


def _current_generations(store, authorized, embedding_profile, snapshot_bundle=None, source_profiles=None):
    selection = authorized.selection
    if selection.query_mode != "current" or selection.generation_ids is None:
        raise ProjectionError("Managed compatibility projection requires explicit current generations")
    generations = {}
    source_ids = set()
    if snapshot_bundle is not None:
        snapshot_bundle.validate()
    pinned = snapshot_bundle.generation_ids if snapshot_bundle is not None else frozenset()
    for identity in sorted(selection.generation_ids):
        generation = store._knowledge_get("Generation", identity)
        source = store.get_source(generation.source_id) if generation else None
        if (
            generation is None
            or generation.status not in ({"active", "retired"} if identity in pinned else {"active"})
            or generation.embedding_profile
            != (
                source_profiles.get(generation.source_id)
                if source_profiles is not None
                else embedding_profile
            )
            or source is None
            or source.get("workspace_id") != authorized.workspace_id
            or (identity not in pinned and source.get("active_generation_id") != identity)
            or generation.source_id in source_ids
        ):
            raise ProjectionError("Selected generation is not the current compatible workspace generation")
        generations[identity] = generation
        source_ids.add(generation.source_id)
    if source_profiles is not None and set(source_profiles) != source_ids:
        raise ProjectionError("Structural source profiles must exactly match selected sources")
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
        "p.generation_id AS generation_id, p.embedding_profile AS embedding_profile, "
        "p.retrieval_view_id AS retrieval_view_id, p.ordinal AS ordinal",
        generations=sorted(generations),
    )


@dataclass(frozen=True)
class _DenseBinding:
    span_id: str
    text: str
    vector: np.ndarray
    evidence: RetrievalEvidence
    binding_ids: frozenset[str] = frozenset()


def _closure_allowed(closure, authorized):
    return (
        closure.span_ids <= authorized.span_ids
        and closure.revision_ids <= authorized.revision_ids
        and closure.binding_ids <= authorized.native_binding_ids
        and closure.derived_record_ids <= authorized.derived_record_ids
        and closure.dependency_ids <= authorized.derived_dependency_ids
        and closure.view_ids <= authorized.retrieval_view_ids
    )


def _safe_vectors(
    full,
    store,
    generations,
    spans,
    revisions,
    artifacts,
    embedding_profile,
    members,
    authorized,
    *,
    structural=False,
):
    """Reuse only vectors with an exact persisted and cached input binding."""
    positions = {} if structural else {passage.id: index for index, passage in enumerate(full.passages)}
    entries, aliases = {}, {}
    for row in sorted(_passage_bindings(store, generations), key=lambda item: item["id"]):
        view_id = row.get("retrieval_view_id")
        if view_id and view_id not in authorized.retrieval_view_ids:
            continue
        span = spans.get(row.get("span_id"))
        position = positions.get(row["id"])
        generation = generations.get(row.get("generation_id"))
        if span is None or (position is None and not structural) or generation is None:
            if view_id:
                raise ProjectionError("Authorized rendered passage binding is unavailable")
            continue
        expected_profile = generation.embedding_profile if structural else embedding_profile
        original_ids, binding_ids = (span.id,), frozenset()
        identity, expected_text = span.id, span.text
        if view_id:
            view = store._knowledge_get("RetrievalView", view_id)
            try:
                closure = validate_view(store, generation.id, view)
                expected_id = generation_passage_id(
                    generation.id, span.revision_id, span.id, row.get("ordinal"), retrieval_view_id=view_id
                )
            except (ValueError, AttributeError) as exc:
                raise ProjectionError("Rendered passage lineage is invalid") from exc
            if row["id"] != expected_id:
                raise ProjectionError("Rendered passage identity differs from its binding")
            if not _closure_allowed(closure, authorized) or not closure.span_ids <= spans.keys():
                raise ProjectionError("Rendered passage lineage differs from the authorized proof")
            if view.span_id != span.id or view.vector_profile != expected_profile:
                raise ProjectionError("Rendered passage anchor or profile differs")
            identity, expected_text = row["id"], view.text
            original_ids, binding_ids = tuple(sorted(closure.span_ids)), closure.binding_ids
        source_id = artifacts[revisions[span.revision_id].artifact_id].source_id
        passage = None if structural else full.passages[position]
        if (
            row.get("artifact_revision_id") != span.revision_id
            or (generation.id, span.revision_id) not in members
            or row.get("embedding_profile") != expected_profile
            or row.get("source_id") != source_id
            or generation.source_id != source_id
            or (passage is not None and passage.source_id != source_id)
            or row.get("text") != expected_text
            or (passage is not None and passage.text != expected_text)
        ):
            if view_id or structural:
                raise ProjectionError("Rendered passage text or vector profile differs from its binding")
            continue
        try:
            if view_id or structural:
                vector = _vectors(row.get("embedding"), (len(row["embedding"]),))
            else:
                vector = np.asarray(row.get("embedding"), dtype=np.float32)
        except (ValueError, TypeError) as exc:
            if view_id or structural:
                raise ProjectionError("Rendered passage vector is invalid") from exc
            continue
        if vector.ndim != 1 or not vector.size or not np.all(np.isfinite(vector)):
            continue
        if not structural and not np.array_equal(vector, full.passage_embeddings[position]):
            if view_id:
                raise ProjectionError("Rendered passage cached vector differs from its binding")
            continue
        if identity in entries and not np.array_equal(vector, entries[identity].vector):
            raise ProjectionError("One evidence span has conflicting vectors for the same profile")
        entries[identity] = _DenseBinding(
            span.id,
            expected_text,
            vector.copy(),
            RetrievalEvidence(identity, generation.id, view_id, original_ids),
            binding_ids,
        )
        aliases[row["id"]] = identity
    dimensions = defaultdict(set)
    for entry in entries.values():
        dimensions[entry.evidence.generation_id if structural else None].add(len(entry.vector))
    if any(len(values) > 1 for values in dimensions.values()):
        raise ProjectionError("Authorized vectors have incompatible dimensions")
    return entries, aliases


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
    full: GraphIndex | None,
    store,
    authorized: AuthorizedEvidence,
    *,
    embedding_profile: str | None = None,
    source_profiles: Mapping[str, str] | None = None,
    snapshot_bundle=None,
    synonymy_threshold: float = 0.8,
    structural: bool = False,
) -> GraphIndex:
    """Build only the managed lane; no native provenance is inferred from endpoints.

    Original passage IDs remain EvidenceSpan IDs; rendered candidates retain
    their view-aware native IDs and full original citation lineage. Objects use
    KnowledgeObject IDs. Only authorized ProseExtraction supplies inferred facts;
    typed assertions retain their separate channel. Historical generations are
    usable only while a supplied snapshot reference is live.
    """
    if structural:
        if embedding_profile is not None or not isinstance(source_profiles, Mapping):
            raise ProjectionError("Structural projection requires an explicit source profile mapping")
        source_profiles = dict(source_profiles)
        if any(
            type(key) is not str or not key or type(value) is not str or not value
            for key, value in source_profiles.items()
        ):
            raise ProjectionError("Invalid structural source profile mapping")
    elif not embedding_profile or source_profiles is not None:
        raise ProjectionError("An explicit embedding profile is required")
    elif full is None:
        raise ProjectionError("Nonstructural projection requires a cached full graph")
    generations = _current_generations(store, authorized, embedding_profile, snapshot_bundle, source_profiles)

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
    entries, aliases = _safe_vectors(
        full,
        store,
        generations,
        spans,
        revisions,
        artifacts,
        embedding_profile,
        members,
        authorized,
        structural=structural,
    )
    vectors = {identity: entry.vector for identity, entry in entries.items()}
    needed_spans = {identity for entry in entries.values() for identity in entry.evidence.original_span_ids}
    if structural:
        structural_bindings = [
            row
            for row in allowed("NativeBinding", authorized.native_binding_ids).values()
            if row.generation_id in generations
        ]
        needed_spans.update(row.span_id for row in structural_bindings)
        needed_spans.update(
            row.span_id for row in allowed("ObjectObservation", authorized.observation_ids).values()
        )
        needed_spans.update(identity for group in authorized.support_groups for identity in group.span_ids)
    spans = {key: value for key, value in spans.items() if key in needed_spans}
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
    entities, nodes, code_contributions, object_evidence = {}, [], {}, []
    native_kinds = {"Symbol": "symbol", "DataObject": "data", "Commit": "commit"}
    for identity, obj in sorted(objects.items()):
        observed = observations[identity]
        by_source = defaultdict(list)
        for observation in observed:
            by_source[artifacts[revisions[observation.revision_id].artifact_id].source_id].append(observation)
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
            if structural:
                contributions = {}
                for binding in bindings[identity]:
                    generation = generations[binding.generation_id]
                    contributions[generation.source_id] = (generation, by_source[generation.source_id])
                local_nodes = [
                    _code_node(obj, expected, rows, source)
                    for source, (_, rows) in sorted(contributions.items())
                ]
                display = [
                    {
                        key: value
                        for key, value in asdict(node).items()
                        if key not in {"source_id", "source_name", "in_degree"}
                    }
                    for node in local_nodes
                ]
                if any(value != display[0] for value in display[1:]):
                    raise ProjectionError("Shared code has conflicting source display attributes")
                nodes.append(local_nodes[0])
                code_contributions[identity] = contributions
            else:
                nodes.append(_code_node(obj, expected, observed, source_id))
        else:
            if structural:
                values = [_attributes(rows) for rows in by_source.values()]
                if any(value != values[0] for value in values[1:]):
                    raise ProjectionError("Shared typed object has conflicting source attributes")
                selected = {generation.source_id: generation.id for generation in generations.values()}
                object_evidence.extend(
                    StructuralObjectEvidence(
                        identity,
                        selected[source],
                        source,
                        tuple(sorted(row.id for row in rows)),
                        tuple(sorted({row.span_id for row in rows})),
                    )
                    for source, rows in sorted(by_source.items())
                )
            attributes = _attributes(observed)
            entities[identity] = (
                attributes.get("name") if isinstance(attributes.get("name"), str) else obj.kind
            )
    passages, original_citations = [], []
    names_by_span = defaultdict(set)
    for node in nodes:
        for observed in observations[node.id]:
            names_by_span[observed.span_id].add(node.name)
    titles = {}
    for identity, span in sorted(spans.items()):
        names = names_by_span[identity]
        locator = json.loads(span.locator_json)
        title = min(names) if names else locator.get("path") or span.locator_kind
        titles[identity] = title
        revision = revisions[span.revision_id]
        artifact = artifacts[revision.artifact_id]
        original_citations.append(
            OriginalCitation(
                id=identity,
                span_id=identity,
                revision_id=revision.id,
                artifact_id=artifact.id,
                text=span.text,
                title=title,
                source_id=artifact.source_id,
                text_hash=span.text_hash,
                locator_kind=span.locator_kind,
                locator_json=span.locator_json,
            )
        )
    for ordinal, (identity, entry) in enumerate(sorted(entries.items())):
        source_id = generations[entry.evidence.generation_id].source_id
        passages.append(Passage(identity, titles[entry.span_id], entry.text, source_id, "", ordinal))
    edges, arrows, relation_evidence = {}, [], []

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
            for passage_id, entry in entries.items():
                if entry.span_id != span_id:
                    continue
                if entry.evidence.retrieval_view_id and not any(
                    binding.id in entry.binding_ids for binding in bindings[identity]
                ):
                    continue
                relation(identity, passage_id, "DEFINED_IN", 1.0, mention=identity not in code_ids)
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
        if structural and assertion.subject_id != assertion.object_id:
            relation_evidence.append(
                StructuralRelationEvidence(
                    assertion.subject_id,
                    assertion.object_id,
                    assertion.predicate,
                    float(version.confidence),
                    version.id,
                    group.derivation_group,
                    tuple(sorted(group.span_ids)),
                    tuple(
                        sorted(
                            (
                                source,
                                next(
                                    generation.id
                                    for generation in generations.values()
                                    if generation.source_id == source
                                ),
                            )
                            for source in {
                                artifacts[revisions[spans[identity].revision_id].artifact_id].source_id
                                for identity in group.span_ids
                            }
                        )
                    ),
                )
            )
    facts, fact_vectors, prose_provenance = _project_prose(
        store,
        authorized,
        generations,
        entries,
        aliases,
        entities,
        edges,
        synonymy_threshold,
        structural=structural,
    )
    dense_vectors = ()
    code_evidence = ()
    if structural:
        attached_code = {a for a, b, kind, *_ in arrows if kind == "DEFINED_IN" and b in entries}
        code_evidence = tuple(
            StructuralCodeEvidence(
                node.id,
                generation.id,
                source,
                tuple(sorted({row.span_id for row in local_observations})),
            )
            for node in nodes
            if node.id not in attached_code
            or {row.span_id for row in observations[node.id]} - {entry.span_id for entry in entries.values()}
            or len(code_contributions[node.id]) > 1
            for source, (generation, local_observations) in sorted(code_contributions[node.id].items())
        )
        dense_vectors = tuple(
            [
                DenseVector(
                    "passage",
                    identity,
                    entry.evidence.generation_id,
                    generations[entry.evidence.generation_id].embedding_profile,
                    len(entry.vector),
                    tuple(entry.vector.tolist()),
                )
                for identity, entry in sorted(entries.items())
            ]
            + [
                DenseVector(
                    "fact",
                    proof.fact_id,
                    proof.generation_id,
                    generations[proof.generation_id].embedding_profile,
                    len(fact_vectors[proof.fact_id]),
                    tuple(fact_vectors[proof.fact_id].tolist()),
                )
                for proof in prose_provenance
            ]
        )
    result = _assemble(
        entities,
        nodes,
        passages,
        vectors,
        facts,
        fact_vectors,
        edges,
        arrows,
        retrieval_evidence=tuple(entries[key].evidence for key in sorted(entries)),
        original_citations=tuple(original_citations),
        prose_provenance=prose_provenance,
        managed_passage_ids=frozenset(entries),
        dense_capability=DenseCapability("unavailable") if structural else None,
        dense_vectors=dense_vectors,
        structural_code_evidence=code_evidence,
        structural_object_evidence=tuple(object_evidence),
        structural_relations=tuple(relation_evidence),
    )
    if snapshot_bundle is not None:
        snapshot_bundle.validate()
    return result


def _project_prose(
    store, authorized, generations, entries, aliases, entities, edges, synonymy_threshold, *, structural=False
):
    """Feed the existing inferred Fact channel only from explicit authorized support."""
    entity_vectors, fact_vectors, triples, supports, contributions, owners = {}, {}, {}, {}, {}, {}
    sources, physical_support = defaultdict(dict), {}
    dimensions = defaultdict(set)
    for entry in entries.values():
        dimensions[generations[entry.evidence.generation_id].source_id if structural else None].add(
            len(entry.vector)
        )

    def vector(identity, value, destination, source):
        try:
            current = _vectors(value, (len(value),))
        except (TypeError, ValueError) as exc:
            raise ProjectionError("Invalid inferred prose vector") from exc
        local_dimensions = dimensions[source if structural else None]
        local_dimensions.add(len(current))
        if len(local_dimensions) > 1:
            raise ProjectionError("Inferred prose vectors have incompatible dimensions")
        previous = destination.get(identity)
        if previous is not None and not np.array_equal(previous, current):
            raise ProjectionError("Equivalent inferred prose has conflicting vectors")
        destination[identity] = current

    extractions = sorted(
        (
            row
            for row in store._knowledge_rows("ProseExtraction")
            if row.id in authorized.prose_extraction_ids
        ),
        key=lambda row: row.id,
    )
    for extraction in extractions:
        generation = generations.get(extraction.generation_id)
        if generation is None:
            raise ProjectionError("Inferred prose belongs to another selected generation")
        try:
            closure = validate_prose(store, generation.id, extraction)
        except ValueError as exc:
            raise ProjectionError("Inferred prose lineage is invalid") from exc
        if not _closure_allowed(closure, authorized):
            raise ProjectionError("Inferred prose differs from its authorized closure")
        shown_in = set()
        for physical_id in extraction.support_passage_ids:
            projected = aliases.get(physical_id)
            if projected not in entries:
                raise ProjectionError("Inferred prose has no bound supporting retrieval item")
            if projected in physical_support and physical_support[projected] != physical_id:
                raise ProjectionError("Distinct prose support aliases collapse to one retrieval item")
            physical_support[projected] = physical_id
            shown_in.add(projected)
        local_ids = {}
        for entity in extraction.payload.entities:
            identity = make_identity("entity", ["inferred-prose-v1", generation.source_id, entity.name])
            local_ids[entity.name] = identity
            if identity in entities and entities[identity] != entity.name:
                raise ProjectionError("Inferred entity identity collides")
            entities[identity] = entity.name
            vector(identity, entity.embedding, entity_vectors, generation.source_id)
            sources[generation.source_id][identity] = entity.name
            for passage_id in shown_in:
                edges.setdefault(tuple(sorted((identity, passage_id))), Edge()).mention = True
        for triple in extraction.payload.triples:
            values = (triple.subject, triple.predicate, triple.object)
            identity = make_identity("fact", ["inferred-prose-v1", generation.source_id, *values])
            triples[identity] = (*values, local_ids[triple.subject], local_ids[triple.object])
            vector(identity, triple.embedding, fact_vectors, generation.source_id)
            supports.setdefault(identity, set()).update(shown_in)
            contributions.setdefault(identity, set()).add(extraction.id)
            owners[identity] = generation.id
    facts, provenance = [], []
    for identity, values in sorted(triples.items()):
        shown_in = sorted(supports[identity])
        facts.append(Fact(identity, *values, shown_in))
        a, b = values[3:]
        if a != b:
            edges.setdefault(tuple(sorted((a, b))), Edge()).fact_count += len(shown_in)
        provenance.append(
            ProseProvenance(
                identity,
                owners[identity],
                tuple(sorted(contributions[identity])),
                tuple(shown_in),
            )
        )
    if sources:
        from hippo.hipporag.indexer import find_synonyms

        for names in sources.values():
            identities = sorted(names)
            # Storage guarantees finite nonzero vectors, not unit length. The
            # existing synonym finder uses dot products, so normalize its copy
            # without changing immutable vector equivalence or Fact embeddings.
            vectors = np.stack([entity_vectors[identity] for identity in identities]).astype(np.float64)
            vectors = (vectors / np.linalg.norm(vectors, axis=1, keepdims=True)).astype(np.float32)
            selected = SimpleNamespace(
                load_entity_embeddings=lambda ids=identities, matrix=vectors: (ids, matrix),
                load_code_embeddings=lambda: ([], []),
            )
            for a, b, score in find_synonyms(
                selected, identities, vectors, names, threshold=synonymy_threshold
            ):
                if a != b:
                    edge = edges.setdefault(tuple(sorted((a, b))), Edge())
                    edge.synonym_score = max(edge.synonym_score, score)
    return facts, fact_vectors, tuple(provenance)


def _assemble(
    entities,
    nodes,
    passages,
    passage_vectors,
    facts,
    fact_vectors,
    edge_ids,
    arrow_ids,
    statistics=None,
    *,
    retrieval_evidence=(),
    original_citations=(),
    prose_provenance=(),
    managed_passage_ids=frozenset(),
    dense_capability=None,
    dense_vectors=(),
    legacy_dense_vectors=(),
    structural_code_evidence=(),
    structural_object_evidence=(),
    structural_relations=(),
):
    nodes = sorted(nodes, key=lambda node: CODE_KINDS.index(node.kind))
    identities = list(entities) + [node.id for node in nodes] + [passage.id for passage in passages]
    if len(identities) != len(set(identities)):
        raise ProjectionError("Projection node identities collide")
    if {item.passage_id for item in retrieval_evidence} != managed_passage_ids:
        raise ProjectionError("Managed passage provenance is incomplete")
    if not managed_passage_ids <= {passage.id for passage in passages}:
        raise ProjectionError("Managed provenance has no retrieval candidate")
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
    capability = dense_capability or DenseCapability()
    width = capability.dimension if capability.mode in ("verified", "tag_compatible") else 0
    passage_matrix = (
        np.stack([passage_vectors[p.id] for p in passages]).astype(np.float32)
        if passages and capability.mode != "unavailable"
        else np.zeros((len(passages), width), dtype=np.float32)
    )
    fact_matrix = (
        np.stack([fact_vectors[f.id] for f in facts]).astype(np.float32)
        if facts and capability.mode != "unavailable"
        else np.zeros((len(facts), width), dtype=np.float32)
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
    result = GraphIndex(
        version=0,
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
        retrieval_evidence=retrieval_evidence,
        original_citations=original_citations,
        prose_provenance=prose_provenance,
        managed_passage_ids=managed_passage_ids,
        dense_capability=capability,
        dense_vectors=dense_vectors,
        legacy_dense_vectors=legacy_dense_vectors,
        structural_code_evidence=structural_code_evidence,
        structural_object_evidence=structural_object_evidence,
        structural_relations=structural_relations,
    )
    payload[3], payload[5] = fingerprint_vectors(result)
    try:
        resolve_citations(result, tuple(sorted(managed_passage_ids)))
    except ValueError as exc:
        raise ProjectionError("Managed citation provenance is invalid") from exc
    if extension := provenance_payload(result):
        payload.append(extension)
    if extension := structural_code_payload(result):
        payload.append(extension)
    result.version = int(hashlib.sha256(canonical_json(payload).encode()).hexdigest()[:15], 16)
    return result


def compose_graphs(*graphs: GraphIndex) -> GraphIndex:
    """Compose already authorized, disjoint lanes; never pass an unscoped graph.

    This deliberately does not copy authorization callbacks. The caller attaches
    a callback validating all input proofs together. No cross-lane edge is inferred.
    """
    capability = composed_dense_capability(graphs)
    dense_vectors = tuple(row for graph in graphs for row in graph.dense_vectors)
    legacy_dense_vectors = tuple(row for graph in graphs for row in graph.legacy_dense_vectors)
    code_evidence = tuple(row for graph in graphs for row in graph.structural_code_evidence)
    object_evidence = tuple(row for graph in graphs for row in graph.structural_object_evidence)
    relation_evidence = tuple(row for graph in graphs for row in graph.structural_relations)
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
    retrieval_evidence, original_citations, prose_provenance, managed_passage_ids = [], {}, [], set()
    for graph in graphs:
        if seen.intersection(graph.node_ids):
            raise ProjectionError("Cannot compose colliding graph node identities")
        seen.update(graph.node_ids)
        entities.update(graph.entity_names)
        retrieval_evidence.extend(graph.retrieval_evidence)
        prose_provenance.extend(graph.prose_provenance)
        managed_passage_ids.update(graph.managed_passage_ids)
        for original in graph.original_citations:
            if original.id in original_citations and original_citations[original.id] != original:
                raise ProjectionError("Cannot compose conflicting original citations")
            original_citations[original.id] = original
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
        canonical_rows = {
            (row.lane, row.projected_id): row.values
            for row in (*graph.dense_vectors, *graph.legacy_dense_vectors)
        }
        for i, passage in enumerate(graph.passages):
            vector = (
                np.array(canonical_rows["passage", passage.id], dtype=np.float32)
                if canonical_rows
                else graph.passage_embeddings[i].copy()
            )
            dimensions.add(len(vector))
            passage_vectors[passage.id] = vector
        for i, fact in enumerate(graph.facts):
            vector = (
                np.array(canonical_rows["fact", fact.id], dtype=np.float32)
                if canonical_rows
                else graph.fact_embeddings[i].copy()
            )
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
    if len(dimensions) > 1 and capability.mode != "unavailable":
        raise ProjectionError("Cannot compose graphs with incompatible vector dimensions")
    result = _assemble(
        entities,
        nodes,
        passages,
        passage_vectors,
        facts,
        fact_vectors,
        edges,
        arrows,
        statistics,
        retrieval_evidence=tuple(sorted(retrieval_evidence, key=lambda item: item.passage_id)),
        original_citations=tuple(original_citations[key] for key in sorted(original_citations)),
        prose_provenance=tuple(sorted(prose_provenance, key=lambda item: item.fact_id)),
        managed_passage_ids=frozenset(managed_passage_ids),
        dense_capability=capability,
        dense_vectors=dense_vectors,
        legacy_dense_vectors=legacy_dense_vectors,
        structural_code_evidence=code_evidence,
        structural_object_evidence=object_evidence,
        structural_relations=relation_evidence,
    )
    populated = [graph for graph in graphs if graph.num_nodes]
    if len(populated) == 1:
        result.version = populated[0].version
    return result
