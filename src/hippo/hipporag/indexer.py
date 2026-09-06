"""
Step 2 of HippoRAG: turn passages into the graph.

Given the chunks of one source, this file:

1. embeds each passage and stores it as a Passage node
2. runs OpenIE on each passage (see openie.py)
3. stores every new entity and fact (with embeddings) and links
      Passage -MENTIONS-> Entity   and   Passage -STATES-> Fact
4. links entities whose names mean the same thing with SYNONYM edges
   (embedding similarity above `synonymy_threshold`, at most 100 per entity)
5. bumps the graph version so the in-memory graph reloads

The whole thing is one function, `index_source`, called from a background job.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..ollama import Ollama
from . import openie
from .text import entity_id, fact_id, fact_text, is_meaningful_phrase, make_id

log = logging.getLogger(__name__)

SYNONYM_MAX_NEIGHBOURS = 100  # the reference stops after 100 neighbours per entity
SYNONYM_QUERY_BATCH = 1000

# Called as on_progress(stage, done, total). `stage` is a short phrase for the UI.
Progress = Callable[[str, int, int], None]


@dataclass
class Chunk:
    """What the indexer needs to know about one passage of a source."""

    ordinal: int
    title: str
    text: str


def passage_id(source_id: str, chunk: Chunk) -> str:
    return make_id("passage-", f"{source_id}:{chunk.ordinal}:{chunk.text}")


def index_source(
    store,
    ollama: Ollama,
    source_id: str,
    chunks: list[Chunk],
    *,
    synonymy_threshold: float = 0.8,
    workers: int = 2,
    on_progress: Progress | None = None,
) -> dict[str, int]:
    """Index all chunks of one source into the graph. Returns a few counts for the log."""
    progress = on_progress or (lambda stage, done, total: None)
    chunks = [c for c in chunks if c.text.strip()]
    if not chunks:
        return {"passages": 0, "entities": 0, "facts": 0, "synonyms": 0}

    # 1. Passages.
    progress("embedding passages", 0, len(chunks))
    ids = [passage_id(source_id, c) for c in chunks]
    embeddings = ollama.embed([c.text for c in chunks], kind="document")
    store.add_passages(
        [
            {
                "id": pid,
                "source_id": source_id,
                "ordinal": c.ordinal,
                "title": c.title,
                "text": c.text,
                "embedding": emb.tolist(),
            }
            for pid, c, emb in zip(ids, chunks, embeddings, strict=True)
        ]
    )
    progress("embedding passages", len(chunks), len(chunks))

    # 2. OpenIE.
    progress("extracting facts", 0, len(chunks))
    extractions = openie.extract_many(
        ollama,
        list(zip(ids, [c.text for c in chunks], strict=True)),
        workers=workers,
        on_progress=lambda done, total: progress("extracting facts", done, total),
    )
    for ex in extractions:
        store.save_extraction(ex.passage_id, ex.entities, ex.triples, ex.error)

    # 3. Entities and facts.
    progress("saving entities and facts", 0, 1)
    names: dict[str, str] = {}  # entity id -> name
    triples: dict[str, tuple[str, str, str]] = {}  # fact id -> triple
    mentions: list[tuple[str, str]] = []
    statements: list[tuple[str, str]] = []
    for ex in extractions:
        for name in ex.entity_names:
            eid = entity_id(name)
            names[eid] = name
            mentions.append((ex.passage_id, eid))
        for s, p, o in ex.clean_triples:
            fid = fact_id(s, p, o)
            triples[fid] = (s, p, o)
            statements.append((ex.passage_id, fid))

    new_entity_ids = [eid for eid in names if eid not in store.existing_entity_ids(list(names))]
    new_entity_vectors = ollama.embed([names[eid] for eid in new_entity_ids], kind="document")
    store.add_entities(
        [
            {"id": eid, "name": names[eid], "embedding": vec.tolist()}
            for eid, vec in zip(new_entity_ids, new_entity_vectors, strict=True)
        ]
    )

    new_fact_ids = [fid for fid in triples if fid not in store.existing_fact_ids(list(triples))]
    new_fact_vectors = ollama.embed([fact_text(*triples[fid]) for fid in new_fact_ids], kind="document")
    store.add_facts(
        [
            {
                "id": fid,
                "subject": s,
                "predicate": p,
                "object": o,
                "subject_id": entity_id(s),
                "object_id": entity_id(o),
                "embedding": vec.tolist(),
            }
            for fid, vec in zip(new_fact_ids, new_fact_vectors, strict=True)
            for (s, p, o) in [triples[fid]]
        ]
    )
    store.link_passage_entities(mentions)
    store.link_passage_facts(statements)
    progress("saving entities and facts", 1, 1)

    # 4. Synonym edges for the new entities.
    progress("linking synonyms", 0, 1)
    synonyms = find_synonyms(store, new_entity_ids, new_entity_vectors, names, threshold=synonymy_threshold)
    store.add_synonyms(synonyms)
    progress("linking synonyms", 1, 1)

    # 5. Tell the in-memory graph to reload.
    store.set_meta("embed_model", ollama.embed_model)
    store.set_meta("embedding_dim", int(embeddings.shape[1]) if len(embeddings) else None)
    store.bump_graph_version()
    return {
        "passages": len(chunks),
        "entities": len(new_entity_ids),
        "facts": len(new_fact_ids),
        "synonyms": len(synonyms),
    }


def find_synonyms(
    store, new_ids: list[str], new_vectors: np.ndarray, names: dict[str, str], *, threshold: float
) -> list[tuple[str, str, float]]:
    """
    For each new entity, find existing entities whose name embedding is very similar.

    This is the reference's `add_synonymy_edges`: cosine similarity, keep neighbours above
    `threshold` (0.8), at most 100 per entity, skip tiny phrases like "a" or "12".
    """
    if len(new_ids) == 0:
        return []
    all_ids, all_vectors = store.load_entity_embeddings()
    if not all_ids:
        return []
    keys = np.asarray(all_vectors, dtype=np.float32)
    key_index = {eid: i for i, eid in enumerate(all_ids)}
    pairs: list[tuple[str, str, float]] = []
    for start in range(0, len(new_ids), SYNONYM_QUERY_BATCH):
        batch_ids = new_ids[start : start + SYNONYM_QUERY_BATCH]
        sims = new_vectors[start : start + SYNONYM_QUERY_BATCH] @ keys.T
        for row, eid in zip(sims, batch_ids, strict=True):
            if not is_meaningful_phrase(names.get(eid, "")):
                continue
            self_index = key_index.get(eid)
            if self_index is not None:
                row[self_index] = -1.0  # never link an entity to itself
            top = np.argsort(-row)[:SYNONYM_MAX_NEIGHBOURS]
            for j in top:
                score = float(row[j])
                if score < threshold:
                    break
                pairs.append((eid, all_ids[j], score))
    return pairs
