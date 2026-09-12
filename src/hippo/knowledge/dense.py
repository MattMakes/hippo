"""Pure execution capabilities and immutable, ID-bound canonical dense rows.

These values attest no storage or remote model identity. Projection must supply
already authorized evidence and its complete provenance. Structural rows retain
that evidence for hashing without offering a joint similarity-search matrix.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
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
        if type(self.values) is not tuple or len(self.values) != self.dimension:
            raise ValueError("Dense values must be an immutable dimension-matched tuple")
        with np.errstate(over="ignore", invalid="ignore"):
            if any(
                type(value) is not float or not math.isfinite(value) or float(np.float32(value)) != value
                for value in self.values
            ):
                raise ValueError("Dense values must be finite canonical float32 scalars")
        values = np.asarray(self.values, dtype=np.float64)
        if float(values @ values) <= 0:
            raise ValueError("Dense values must have positive squared norm")


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
    if capability.mode == "legacy":
        if rows:
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
        set(passages) != graph.managed_passage_ids
        or set(retrieval) != set(passages)
        or set(prose) != set(facts)
    ):
        raise ValueError("Dense sidecar must bind exact managed passages and inferred Facts")
    by_key = {(row.lane, row.projected_id): row for row in rows}
    if set(by_key) != {("passage", identity) for identity in passages} | {
        ("fact", identity) for identity in facts
    }:
        raise ValueError("Dense sidecar does not exactly cover projected candidates")
    profiles, sources = {}, {}
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
    rows = {(row.lane, row.projected_id): row.values for row in graph.dense_vectors}
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
