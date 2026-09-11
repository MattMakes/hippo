"""Immutable graph provenance and original citations for a held audience view.

The graph's live proof remains the authority. Serialized provenance and snapshot
IDs cannot authorize an original, and rendered text never replaces source text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .identity import text_hash


@dataclass(frozen=True)
class RetrievalEvidence:
    passage_id: str
    generation_id: str
    retrieval_view_id: str | None
    original_span_ids: tuple[str, ...]


@dataclass(frozen=True)
class OriginalCitation:
    id: str
    text: str
    title: str
    source_id: str
    text_hash: str
    span_id: str | None = None
    revision_id: str | None = None
    artifact_id: str | None = None
    locator_kind: str | None = None
    locator_json: str | None = None


@dataclass(frozen=True)
class ProseProvenance:
    """Support uses projected retrieval IDs; extraction IDs commit native support."""

    fact_id: str
    generation_id: str
    extraction_ids: tuple[str, ...]
    support_passage_ids: tuple[str, ...]


@dataclass(frozen=True)
class CitationItem:
    passage_id: str
    generation_id: str | None
    retrieval_view_id: str | None
    citation_ids: tuple[str, ...]

    @property
    def is_derived(self) -> bool:
        return self.retrieval_view_id is not None


@dataclass(frozen=True)
class CitationBundle:
    items: tuple[CitationItem, ...]
    citations: tuple[OriginalCitation, ...]

    @property
    def retrieval_passage_ids(self) -> tuple[str, ...]:
        return tuple(item.passage_id for item in self.items)


def provenance_payload(graph):
    """Versioned fingerprint extension, absent on original-only/legacy graphs."""
    if not any(item.retrieval_view_id for item in graph.retrieval_evidence) and not graph.prose_provenance:
        return None
    return dict(
        provenance_version=1,
        retrieval_evidence=[asdict(item) for item in graph.retrieval_evidence],
        original_citations=[asdict(item) for item in graph.original_citations],
        prose_provenance=[asdict(item) for item in graph.prose_provenance],
    )


def scoped_provenance(graph, passage_ids, fact_ids):
    """A retained retrieval candidate keeps its full original dependency set."""
    retrieval = tuple(item for item in graph.retrieval_evidence if item.passage_id in passage_ids)
    originals = {identity for item in retrieval for identity in item.original_span_ids}
    prose = tuple(
        item
        for item in graph.prose_provenance
        if item.fact_id in fact_ids and set(item.support_passage_ids) <= passage_ids
    )
    return dict(
        retrieval_evidence=retrieval,
        original_citations=tuple(item for item in graph.original_citations if item.id in originals),
        prose_provenance=prose,
        managed_passage_ids=graph.managed_passage_ids & passage_ids,
    )


def resolve_citations(graph, passage_ids: tuple[str, ...]) -> CitationBundle:
    """Resolve selected retrieval IDs using only this graph's immutable originals."""
    graph.validate_authorization()
    try:
        evidence = {item.passage_id: item for item in graph.retrieval_evidence}
        originals = {item.id: item for item in graph.original_citations}
        if len(evidence) != len(graph.retrieval_evidence) or len(originals) != len(graph.original_citations):
            raise ValueError("Graph citation identities conflict")
        selected, items = {}, []
        for identity in dict.fromkeys(passage_ids):
            passage = graph.passage_by_id(identity)
            if passage is None:
                raise ValueError("Citation retrieval item is unavailable")
            provenance = evidence.get(identity)
            if provenance is None:
                if identity in graph.managed_passage_ids:
                    raise ValueError("Managed retrieval item has no original lineage")
                selected[identity] = OriginalCitation(
                    id=identity,
                    text=passage.text,
                    title=passage.title,
                    source_id=passage.source_id,
                    text_hash=text_hash(passage.text),
                )
                items.append(CitationItem(identity, None, None, (identity,)))
                continue
            if not provenance.original_span_ids:
                raise ValueError("Managed retrieval item has no original citations")
            for span_id in provenance.original_span_ids:
                original = originals.get(span_id)
                if (
                    original is None
                    or original.span_id != span_id
                    or original.source_id != passage.source_id
                    or text_hash(original.text) != original.text_hash
                ):
                    raise ValueError("Managed original citation is unavailable or inconsistent")
                selected[span_id] = original
            items.append(
                CitationItem(
                    identity,
                    provenance.generation_id,
                    provenance.retrieval_view_id,
                    provenance.original_span_ids,
                )
            )
        return CitationBundle(tuple(items), tuple(selected.values()))
    finally:
        graph.validate_authorization()
