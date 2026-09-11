"""Internal generation inventory, separate from access grants and write counts."""

from dataclasses import dataclass


class GenerationCountsUnavailable(ValueError):
    """The requested generation no longer has a coherent stored inventory."""


@dataclass(frozen=True)
class GenerationCounts:
    source_id: str
    generation_id: str
    state: str
    passages: int
    fact_links: int


def generation_counts(store, generation_id: str) -> GenerationCounts:
    """Count explicit current, retained or staging inventory under collection exclusion.

    This is an internal diagnostic. Public counts come from the audience's
    authorized graph, and an empty inventory does not establish a source delete.
    """
    if not isinstance(generation_id, str) or not generation_id.strip():
        raise ValueError("An explicit generation ID is required")
    with store.transaction():
        store._lock_authorization()
        generation = store._knowledge_get("Generation", generation_id)
        if generation is None or generation.status == "failed":
            raise GenerationCountsUnavailable("Generation inventory is unavailable")
        if store.get_source(generation.source_id) is None:
            raise GenerationCountsUnavailable("Generation source is unavailable")
        store._lock_source(generation.source_id)
        generation = store._generation(generation_id)
        if generation.status == "failed":
            raise GenerationCountsUnavailable("Generation inventory is unavailable")
        if generation.status != "staging":
            try:
                store.validate_generation_seal(generation_id)
            except ValueError as error:
                raise GenerationCountsUnavailable("Generation inventory seal is invalid") from error
        rows = [r for r in store._native_rows("Passage") if r.get("generation_id") == generation_id]
        if any(row.get("source_id") != generation.source_id for row in rows):
            raise GenerationCountsUnavailable("Generation inventory crosses source ownership")
        passage_ids = {row["id"] for row in rows}
        if store.knowledge_backend == "fake":
            links = {(pid, fid) for pid, fid in store.statements if pid in passage_ids}
        else:
            links = store.run(
                "MATCH (p:Passage)-[:STATES]->(f:Fact) WHERE p.id IN $ids "
                "RETURN DISTINCT p.id AS passage_id, f.id AS fact_id",
                ids=sorted(passage_ids),
            )
        return GenerationCounts(
            generation.source_id, generation.id, generation.status, len(passage_ids), len(links)
        )
