"""Materialized source DTOs use the originals actually supplied to the answer."""

from dataclasses import asdict

from .citations import resolve_citations
from .model import LOCATOR_ADAPTER


def _location(citation):
    if citation.locator_json is None:
        return ""
    locator = LOCATOR_ADAPTER.validate_json(citation.locator_json)
    if locator.kind in ("file_lines", "diff_hunk"):
        lines = str(locator.start) if locator.start == locator.end else f"{locator.start}–{locator.end}"
        label = f"{locator.path}, lines {lines}"
        return f"{label} ({locator.side} revision)" if locator.kind == "diff_hunk" else label
    if locator.kind == "section":
        return " / ".join(locator.heading_path) + f", blocks {locator.block_start}–{locator.block_end}"
    if locator.kind == "field":
        return locator.field_path
    if locator.kind == "comment":
        return f"Comment {locator.comment_id}, {locator.field_path}"
    if locator.kind == "page":
        return f"Page {locator.page}"
    return f"Table {locator.table + 1}, row {locator.row + 1}, column {locator.column + 1}"


def retrieval_fields(graph, passage_ids):
    bundle = resolve_citations(graph, tuple(passage_ids))
    return {
        "retrieval_evidence": [dict(asdict(item), is_derived=item.is_derived) for item in bundle.items],
        "citations": [dict(asdict(citation), location=_location(citation)) for citation in bundle.citations],
    }


def answer_sources(graph, trace, answer):
    """Keep ranking IDs separate from original IDs, including many-to-many views."""
    graph.validate_authorization()
    try:
        retrieval_ids = answer.retrieval_passage_ids or answer.passage_ids
        bundle = resolve_citations(graph, tuple(retrieval_ids))
        if [citation.id for citation in bundle.citations] != answer.passage_ids:
            raise ValueError("Answer citations do not match the held original evidence")
        ranked = {passage.passage_id: passage for passage in trace.passages}
        sources = []
        for citation in bundle.citations:
            parents = [item.passage_id for item in bundle.items if citation.id in item.citation_ids]
            if not parents or any(identity not in ranked for identity in parents):
                raise ValueError("Answer source has no ranked retrieval candidate")
            best = min((ranked[identity] for identity in parents), key=lambda row: row.rank)
            sources.append(
                {
                    "passage_id": citation.id,
                    "title": citation.title,
                    "source": best.source_name,
                    "source_id": citation.source_id,
                    "text": citation.text,
                    "rank": best.rank,
                    "score": round(best.score, 6),
                    "dpr_rank": best.dpr_rank,
                    "retrieval_passage_ids": parents,
                    "content_kind": "original" if citation.span_id is not None else "legacy",
                    "span_id": citation.span_id,
                    "revision_id": citation.revision_id,
                    "artifact_id": citation.artifact_id,
                    "locator_kind": citation.locator_kind,
                    "locator_json": citation.locator_json,
                    "location": _location(citation),
                    "text_hash": citation.text_hash,
                }
            )
        return sources
    finally:
        graph.validate_authorization()
