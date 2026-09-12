"""Pure execution capabilities and immutable, ID-bound canonical dense rows.

These values attest no storage or remote model identity. Projection must supply
already authorized evidence and its complete provenance. Structural rows retain
that evidence for hashing without offering a joint similarity-search matrix.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from typing import Literal

import numpy as np

from .citations import OriginalCitation, ProseProvenance, RetrievalEvidence
from .embedding_cache import MAX_DIMENSION
from .identity import make_identity, text_hash


class DenseUnavailable(ValueError):
    """This graph cannot perform dense retrieval with the supplied model profile."""


def _dimension(value) -> None:
    if type(value) is not int or not 1 <= value <= MAX_DIMENSION:
        raise ValueError("Dense dimension must be a positive bounded integer")


def _fingerprint(value) -> None:
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("Dense profile fingerprint must be canonical SHA-256")


@dataclass(frozen=True, slots=True)
class DenseSelection:
    fingerprint: str
    dimension: int

    def __post_init__(self) -> None:
        _fingerprint(self.fingerprint)
        _dimension(self.dimension)


@dataclass(frozen=True, slots=True)
class DenseCapability:
    mode: Literal["legacy", "verified", "unavailable"] = "legacy"
    fingerprint: str | None = None
    dimension: int | None = None

    def __post_init__(self) -> None:
        if self.mode == "verified":
            DenseSelection(self.fingerprint, self.dimension)
        elif (
            self.mode not in ("legacy", "unavailable")
            or self.fingerprint is not None
            or self.dimension is not None
        ):
            raise ValueError("Invalid dense capability")


@dataclass(frozen=True, slots=True)
class DenseVector:
    lane: Literal["passage", "fact"]
    projected_id: str
    generation_id: str
    profile: str
    dimension: int
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.lane not in ("passage", "fact") or any(
            type(value) is not str or not value
            for value in (self.projected_id, self.generation_id, self.profile)
        ):
            raise ValueError("Dense rows require a supported lane and explicit immutable binding")
        _dimension(self.dimension)
        _values(self.values, self.dimension, nonzero=True)


def _values(values, dimension, *, nonzero):
    if type(values) is not tuple or len(values) != dimension:
        raise ValueError("Dense values must be an immutable dimension-matched tuple")
    with np.errstate(over="ignore", invalid="ignore"):
        if any(
            type(value) is not float or not math.isfinite(value) or float(np.float32(value)) != value
            for value in values
        ):
            raise ValueError("Dense values must be finite canonical float32 scalars")
    if nonzero and float(np.asarray(values, dtype=np.float64) @ np.asarray(values, dtype=np.float64)) <= 0:
        raise ValueError("Dense values must have positive squared norm")


@dataclass(frozen=True, slots=True)
class LegacyDenseVector:
    """Retained legacy values; never a claim of generation/profile provenance."""

    lane: Literal["passage", "fact"]
    projected_id: str
    dimension: int
    values: tuple[float, ...]
    support_passage_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if (
            self.lane not in ("passage", "fact")
            or type(self.projected_id) is not str
            or not self.projected_id
        ):
            raise ValueError("Legacy vector requires an explicit supported lane and ID")
        _dimension(self.dimension)
        # Legacy eligibility did not reject zero vectors. Retain its accepted
        # finite values without upgrading them to managed vector guarantees.
        _values(self.values, self.dimension, nonzero=False)
        if self.lane == "passage":
            if self.support_passage_ids != () or type(self.support_passage_ids) is not tuple:
                raise ValueError("Legacy passage cannot declare Fact support")
        elif not _unique_strings(self.support_passage_ids):
            raise ValueError("Legacy Fact requires explicit immutable support")


@dataclass(frozen=True, slots=True)
class StructuralObjectEvidence:
    node_id: str
    generation_id: str
    source_id: str
    observation_ids: tuple[str, ...]
    original_span_ids: tuple[str, ...]

    def __post_init__(self):
        if any(
            type(value) is not str or not value
            for value in (self.node_id, self.generation_id, self.source_id)
        ) or any(
            not _unique_strings(values) or values != tuple(sorted(values))
            for values in (self.observation_ids, self.original_span_ids)
        ):
            raise ValueError("Structural objects require canonical immutable observation/original bindings")


def canonical_object_evidence(rows):
    if type(rows) is not tuple or any(type(row) is not StructuralObjectEvidence for row in rows):
        raise ValueError("Structural object evidence must contain immutable records")
    if len({(row.node_id, row.generation_id, row.source_id) for row in rows}) != len(rows):
        raise ValueError("Structural object evidence identities collide")
    return tuple(sorted(rows, key=lambda row: (row.node_id, row.generation_id, row.source_id)))


@dataclass(frozen=True, slots=True)
class StructuralCodeEvidence:
    node_id: str
    generation_id: str
    source_id: str
    original_span_ids: tuple[str, ...]

    def __post_init__(self):
        if any(
            type(value) is not str or not value
            for value in (self.node_id, self.generation_id, self.source_id)
        ) or not _unique_strings(self.original_span_ids):
            raise ValueError("Structural code requires immutable source/generation/original bindings")


@dataclass(frozen=True, slots=True)
class StructuralRelationEvidence:
    subject_id: str
    object_id: str
    predicate: str
    weight: float
    assertion_version_id: str
    derivation_group: str
    original_span_ids: tuple[str, ...]
    source_generations: tuple[tuple[str, str], ...]

    def __post_init__(self):
        from .predicates import PREDICATES

        if any(
            type(value) is not str or not value
            for value in (
                self.subject_id,
                self.object_id,
                self.predicate,
                self.assertion_version_id,
                self.derivation_group,
            )
        ) or not _unique_strings(self.original_span_ids):
            raise ValueError("Structural relation requires complete immutable support")
        if (
            self.subject_id == self.object_id
            or self.predicate not in PREDICATES
            or not PREDICATES[self.predicate].traversal_permitted
            or type(self.weight) is not float
            or not math.isfinite(self.weight)
            or not 0 <= self.weight <= 1
        ):
            raise ValueError("Invalid structural relation predicate or confidence")
        if (
            type(self.source_generations) is not tuple
            or not self.source_generations
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or any(type(value) is not str or not value for value in pair)
                for pair in self.source_generations
            )
        ):
            raise ValueError("Structural relation requires immutable source/generation pairs")
        if (
            len(dict(self.source_generations)) != len(self.source_generations)
            or len({generation for _, generation in self.source_generations}) != len(self.source_generations)
            or self.source_generations != tuple(sorted(self.source_generations))
        ):
            raise ValueError("Structural relation source/generation mapping must be canonical and unique")

    @property
    def key(self):
        return (
            self.subject_id,
            self.object_id,
            self.predicate,
            self.assertion_version_id,
            self.derivation_group,
            self.original_span_ids,
        )


def canonical_relation_evidence(rows):
    if type(rows) is not tuple or any(type(row) is not StructuralRelationEvidence for row in rows):
        raise ValueError("Structural relations must contain immutable records")
    if len({row.key for row in rows}) != len(rows):
        raise ValueError("Structural relation support groups collide")
    return tuple(sorted(rows, key=lambda row: row.key))


def relation_arrow_key(graph, arrow):
    return (
        graph.node_ids[arrow.src],
        graph.node_ids[arrow.dst],
        arrow.kind,
        arrow.extra.get("assertion_version_id"),
        arrow.extra.get("derivation_group"),
        tuple(arrow.extra.get("support_span_ids", ())),
    )


def canonical_code_evidence(rows):
    if type(rows) is not tuple or any(type(row) is not StructuralCodeEvidence for row in rows):
        raise ValueError("Structural code evidence must contain immutable records")
    if len({(row.node_id, row.generation_id, row.source_id) for row in rows}) != len(rows):
        raise ValueError("Structural code evidence identities collide")
    return tuple(sorted(rows, key=lambda row: (row.node_id, row.generation_id, row.source_id)))


def structural_code_payload(graph):
    originals = {identity for row in graph.structural_code_evidence for identity in row.original_span_ids}
    originals.update(identity for row in graph.structural_relations for identity in row.original_span_ids)
    originals.update(
        identity for row in graph.structural_object_evidence for identity in row.original_span_ids
    )
    payload = (
        {
            "structural_code_evidence_v1": [asdict(row) for row in graph.structural_code_evidence],
            "structural_relations_v1": [asdict(row) for row in graph.structural_relations],
            "original_citations": [asdict(row) for row in graph.original_citations if row.id in originals],
        }
        if graph.structural_code_evidence or graph.structural_relations or graph.structural_object_evidence
        else None
    )
    if graph.structural_object_evidence:
        payload["structural_object_evidence_v1"] = [asdict(row) for row in graph.structural_object_evidence]
    return payload


def canonical_legacy_vectors(rows):
    if type(rows) is not tuple or any(type(row) is not LegacyDenseVector for row in rows):
        raise ValueError("Legacy sidecar must contain immutable LegacyDenseVector records")
    keys = [(row.lane, row.projected_id) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Legacy sidecar lane/ID entries collide")
    return tuple(sorted(rows, key=lambda row: (row.lane, row.projected_id)))


def structural_legacy_graph(graph):
    """Adapt only the already-visible legacy inventory, without new provenance."""
    graph.validate_authorization()
    validate_dense_graph(graph)
    if (
        graph.dense_capability.mode != "legacy"
        or graph.managed_passage_ids
        or graph.prose_provenance
        or graph.retrieval_evidence
    ):
        raise ValueError("Only untagged legacy graph evidence may use this adapter")
    rows = tuple(
        LegacyDenseVector(
            lane,
            item.id,
            len(vector),
            tuple(vector.tolist()),
            tuple(item.passage_ids) if lane == "fact" else (),
        )
        for lane, items, matrix in (
            ("passage", graph.passages, graph.passage_embeddings),
            ("fact", graph.facts, graph.fact_embeddings),
        )
        for item, vector in zip(items, matrix, strict=True)
    )
    result = replace(
        deepcopy(graph),
        dense_capability=DenseCapability("unavailable"),
        legacy_dense_vectors=rows,
        passage_embeddings=np.zeros((len(graph.passages), 0), dtype=np.float32),
        fact_embeddings=np.zeros((len(graph.facts), 0), dtype=np.float32),
    )
    graph.validate_authorization()
    return result


def canonical_dense_vectors(rows) -> tuple[DenseVector, ...]:
    if type(rows) is not tuple or any(type(row) is not DenseVector for row in rows):
        raise ValueError("Dense sidecar must be a tuple of immutable DenseVector records")
    keys = [(row.lane, row.projected_id) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Dense sidecar lane/ID entries collide")
    return tuple(sorted(rows, key=lambda row: (row.lane, row.projected_id)))


def _unique_strings(values) -> bool:
    return (
        type(values) is tuple
        and bool(values)
        and all(type(value) is str and value for value in values)
        and len(values) == len(set(values))
    )


def validate_dense_graph(graph) -> None:
    """Check local node/provenance correspondence; never infer an access grant."""
    capability = graph.dense_capability
    if type(capability) is not DenseCapability:
        raise ValueError("Graph requires an immutable dense capability")
    rows = canonical_dense_vectors(graph.dense_vectors)
    legacy_rows = canonical_legacy_vectors(graph.legacy_dense_vectors)
    code_evidence = canonical_code_evidence(graph.structural_code_evidence)
    object_evidence = canonical_object_evidence(graph.structural_object_evidence)
    relations = canonical_relation_evidence(graph.structural_relations)
    if capability.mode == "legacy":
        if rows or legacy_rows or code_evidence or relations or object_evidence:
            raise ValueError("Legacy compatibility graphs cannot relabel canonical bound vectors")
        return
    if (
        len(graph.node_ids) != len(set(graph.node_ids))
        or len(graph.node_kind) != len(graph.node_ids)
        or graph.idx_of != {identity: index for index, identity in enumerate(graph.node_ids)}
    ):
        raise ValueError("Dense graph vertex index is inconsistent")
    if graph.fact_index_of != {fact.id: index for index, fact in enumerate(graph.facts)}:
        raise ValueError("Dense graph Fact index is inconsistent")
    if any(
        p.id not in graph.idx_of or graph.node_kind[graph.idx_of[p.id]] != "passage" for p in graph.passages
    ):
        raise ValueError("Dense passage has no projected passage vertex")
    if any(
        identity not in graph.idx_of or graph.node_kind[graph.idx_of[identity]] != "entity"
        for identity in graph.entity_names
    ):
        raise ValueError("Dense entity has no projected entity vertex")
    if list(graph.passage_vertices) != [graph.idx_of[p.id] for p in graph.passages]:
        raise ValueError("Dense passage vertex positions are inconsistent")
    if any(type(original) is not OriginalCitation for original in graph.original_citations):
        raise ValueError("Dense originals require typed immutable citations")
    originals = {original.id: original for original in graph.original_citations}
    if len(originals) != len(graph.original_citations):
        raise ValueError("Dense original citation identities collide")
    profiles, sources, source_generations = {}, {}, {}
    relation_keys = {row.key: row.weight for row in relations}
    arrow_keys = {}
    for arrows in graph.code_out.values():
        for arrow in arrows:
            if arrow.provenance == "authorized_evidence" and arrow.extra.get("assertion_version_id"):
                key = relation_arrow_key(graph, arrow)
                if key in arrow_keys:
                    raise ValueError("Structural relation arrows collide")
                arrow_keys[key] = arrow.omega
    if arrow_keys != relation_keys:
        raise ValueError("Structural relation arrows differ from their support groups")
    for relation in relations:
        if relation.subject_id not in graph.idx_of or relation.object_id not in graph.idx_of:
            raise ValueError("Structural relation has unavailable endpoints")
        for identity in relation.original_span_ids:
            original = originals.get(identity)
            if (
                original is None
                or original.span_id != identity
                or text_hash(original.text) != original.text_hash
            ):
                raise ValueError("Structural relation original support is unavailable")
        if {originals[identity].source_id for identity in relation.original_span_ids} != {
            source for source, _ in relation.source_generations
        }:
            raise ValueError("Structural relation source mapping differs from original support")
        for source, generation in relation.source_generations:
            if (
                sources.setdefault(generation, source) != source
                or source_generations.setdefault(source, generation) != generation
            ):
                raise ValueError("Structural relation selected generation is inconsistent")
    passages = {passage.id: passage for passage in graph.passages}
    facts = {fact.id: fact for fact in graph.facts}
    if len(passages) != len(graph.passages) or len(facts) != len(graph.facts):
        raise ValueError("Dense projected identities collide")
    if any(type(item) is not RetrievalEvidence for item in graph.retrieval_evidence) or any(
        type(item) is not ProseProvenance for item in graph.prose_provenance
    ):
        raise ValueError("Dense sidecar requires typed projected provenance")
    retrieval = {item.passage_id: item for item in graph.retrieval_evidence}
    prose = {item.fact_id: item for item in graph.prose_provenance}
    if len(retrieval) != len(graph.retrieval_evidence) or len(prose) != len(graph.prose_provenance):
        raise ValueError("Dense provenance identities collide")
    if (
        not graph.managed_passage_ids <= set(passages)
        or set(retrieval) != graph.managed_passage_ids
        or not set(prose) <= set(facts)
    ):
        raise ValueError("Dense sidecar must bind exact managed passages and inferred Facts")
    by_key = {(row.lane, row.projected_id): row for row in rows}
    if set(by_key) != {("passage", identity) for identity in retrieval} | {
        ("fact", identity) for identity in prose
    }:
        raise ValueError("Dense sidecar does not exactly cover projected candidates")
    legacy_keys = {(row.lane, row.projected_id) for row in legacy_rows}
    if legacy_keys != (
        {("passage", identity) for identity in set(passages) - set(retrieval)}
        | {("fact", identity) for identity in set(facts) - set(prose)}
    ):
        raise ValueError("Legacy sidecar does not exactly cover remaining candidates")
    if legacy_rows and capability.mode != "unavailable":
        raise ValueError("Legacy vectors cannot satisfy verified dense capability")
    for row in legacy_rows:
        if row.lane == "fact":
            fact = facts[row.projected_id]
            if (
                set(row.support_passage_ids) != set(fact.passage_ids)
                or len(row.support_passage_ids) != len(fact.passage_ids)
                or not set(row.support_passage_ids) <= set(passages) - set(retrieval)
                or fact.subject_id not in graph.entity_names
                or fact.object_id not in graph.entity_names
            ):
                raise ValueError("Legacy Fact support or endpoints differ from visible evidence")
    code_nodes = {node.id: node for node in graph.code_nodes}
    code_sources = {}
    for evidence in code_evidence:
        code_sources.setdefault(evidence.node_id, set()).add(evidence.source_id)
    for evidence in code_evidence:
        node = code_nodes.get(evidence.node_id)
        if (
            node is None
            or node.source_id != min(code_sources[evidence.node_id])
            or node.id not in graph.idx_of
            or graph.node_kind[graph.idx_of[node.id]] != node.kind
        ):
            raise ValueError("Structural code has no matching projected node/source")
        if sources.setdefault(evidence.generation_id, evidence.source_id) != evidence.source_id:
            raise ValueError("Structural code generation spans sources")
        if (
            source_generations.setdefault(evidence.source_id, evidence.generation_id)
            != evidence.generation_id
        ):
            raise ValueError("Structural source has conflicting selected generations")
        for identity in evidence.original_span_ids:
            original = originals.get(identity)
            if (
                original is None
                or original.span_id != identity
                or original.source_id != evidence.source_id
                or text_hash(original.text) != original.text_hash
            ):
                raise ValueError("Structural code original dependency is invalid")
    for evidence in object_evidence:
        if evidence.node_id not in graph.entity_names:
            raise ValueError("Structural object has no matching projected entity")
        if (
            sources.setdefault(evidence.generation_id, evidence.source_id) != evidence.source_id
            or source_generations.setdefault(evidence.source_id, evidence.generation_id)
            != evidence.generation_id
        ):
            raise ValueError("Structural object selected generation is inconsistent")
        for identity in evidence.original_span_ids:
            original = originals.get(identity)
            if (
                original is None
                or original.span_id != identity
                or original.source_id != evidence.source_id
                or text_hash(original.text) != original.text_hash
            ):
                raise ValueError("Structural object original dependency is invalid")
    for row in rows:
        declared = (row.profile, row.dimension)
        if profiles.setdefault(row.generation_id, declared) != declared:
            raise ValueError("A generation cannot contribute incompatible dense profiles")
        if capability.mode == "verified" and declared != (capability.fingerprint, capability.dimension):
            raise ValueError("Dense row disagrees with the verified capability")
        if row.lane == "passage":
            evidence = retrieval[row.projected_id]
            source = passages[row.projected_id].source_id
            if evidence.generation_id != row.generation_id or not _unique_strings(evidence.original_span_ids):
                raise ValueError("Passage vector generation or original closure is invalid")
            for identity in evidence.original_span_ids:
                original = originals.get(identity)
                if (
                    original is None
                    or original.span_id != identity
                    or original.source_id != source
                    or text_hash(original.text) != original.text_hash
                ):
                    raise ValueError("Dense passage original dependency is unavailable or invalid")
            if sources.setdefault(row.generation_id, source) != source:
                raise ValueError("A generation cannot span source identities")
            if source_generations.setdefault(source, row.generation_id) != row.generation_id:
                raise ValueError("Projected source has conflicting selected generations")
        else:
            fact = facts[row.projected_id]
            evidence = prose[row.projected_id]
            if (
                evidence.generation_id != row.generation_id
                or not _unique_strings(evidence.extraction_ids)
                or not _unique_strings(evidence.support_passage_ids)
                or set(evidence.support_passage_ids) != set(fact.passage_ids)
                or len(fact.passage_ids) != len(evidence.support_passage_ids)
            ):
                raise ValueError("Fact vector generation or complete support is invalid")
            if any(
                identity not in retrieval or retrieval[identity].generation_id != row.generation_id
                for identity in evidence.support_passage_ids
            ):
                raise ValueError("Fact support is outside its selected generation")
            support_sources = {passages[identity].source_id for identity in evidence.support_passage_ids}
            if len(support_sources) != 1:
                raise ValueError("Inferred Fact support must be source local")
            (source,) = support_sources
            if (
                fact.id != make_identity("fact", ["inferred-prose-v1", source, *fact.triple])
                or fact.subject_id != make_identity("entity", ["inferred-prose-v1", source, fact.subject])
                or fact.object_id != make_identity("entity", ["inferred-prose-v1", source, fact.object])
            ):
                raise ValueError("Dense Fact must use canonical source-local inferred identities")
            if (
                graph.entity_names.get(fact.subject_id) != fact.subject
                or graph.entity_names.get(fact.object_id) != fact.object
            ):
                raise ValueError("Dense Fact endpoints are not the authorized projected entities")
    width = capability.dimension if capability.mode == "verified" else 0
    for lane, items, matrix in (
        ("passage", graph.passages, graph.passage_embeddings),
        ("fact", graph.facts, graph.fact_embeddings),
    ):
        if (
            type(matrix) is not np.ndarray
            or matrix.dtype != np.float32
            or matrix.shape != (len(items), width)
        ):
            raise ValueError("Dense search matrix shape does not match its capability")
        if capability.mode == "verified":
            for item, vector in zip(items, matrix, strict=True):
                if tuple(vector.tolist()) != by_key[(lane, item.id)].values:
                    raise ValueError("Dense matrix differs from its canonical bound sidecar")


def fingerprint_vectors(graph) -> tuple[list, list]:
    """Use identical ordered canonical values for verified and structural views."""
    validate_dense_graph(graph)
    if graph.dense_capability.mode != "unavailable":
        return graph.passage_embeddings.tolist(), graph.fact_embeddings.tolist()
    rows = {
        (row.lane, row.projected_id): row.values
        for row in (*graph.dense_vectors, *graph.legacy_dense_vectors)
    }
    return (
        [list(rows["passage", p.id]) for p in graph.passages],
        [list(rows["fact", f.id]) for f in graph.facts],
    )


def composed_dense_capability(graphs) -> DenseCapability:
    """Empty legacy components are neutral; no missing bindings are invented."""
    for graph in graphs:
        validate_dense_graph(graph)
    explicit = [graph.dense_capability for graph in graphs if graph.dense_capability.mode != "legacy"]
    if not explicit:
        return DenseCapability()
    if any(graph.dense_capability.mode == "legacy" and (graph.num_nodes or graph.facts) for graph in graphs):
        raise DenseUnavailable("Structural composition needs faithful bindings for every dense candidate")
    if any(capability.mode == "unavailable" for capability in explicit):
        return DenseCapability("unavailable")
    if len(set(explicit)) != 1:
        raise DenseUnavailable("Verified graphs require one matching profile and dimension")
    return explicit[0]
