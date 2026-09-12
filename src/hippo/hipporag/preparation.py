"""Shared model computation with explicit inputs and no store access.

Passage identities and vector selection belong to the caller. These detached
preparation values are transient, not persisted evidence or authorization. Row
builders return fresh containers; adapters must copy mutable rows on handoff to
writers. No helper consults global existing entities/facts or opens a transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..ollama import Ollama
from . import openie
from .text import entity_id, fact_id, label_of, split_identifier

if TYPE_CHECKING:
    from ..codegraph.model import CodeGraph
    from .indexer import Chunk

MIN_OPENIE_DOC_CHARS = 80
_NO_VECTORS = np.zeros((0, 0), dtype=np.float32)


@dataclass(frozen=True)
class PreparedPassages:
    rows: list[dict]
    vectors: np.ndarray


def prepare_passage_vectors(
    ollama: Ollama, source_id: str, passages: list[tuple[str, Chunk]]
) -> PreparedPassages:
    """Embed exactly these texts, retaining caller IDs, order and ordinals."""
    vectors = ollama.embed([chunk.text for _, chunk in passages], kind="document").copy()
    rows = [
        {
            "id": pid,
            "source_id": source_id,
            "ordinal": chunk.ordinal,
            "title": chunk.title,
            "text": chunk.text,
            "embedding": vector.tolist(),
        }
        for (pid, chunk), vector in zip(passages, vectors, strict=True)
    ]
    return PreparedPassages(rows, vectors)


@dataclass(frozen=True)
class PreparedCodeRows:
    symbols: list[dict]
    data_objects: list[dict]
    commits: list[dict]
    modifies: list[dict]
    precedes: list[tuple[str, str]]
    edges: list[dict]
    definitions: list[tuple[str, str]]
    ids: list[str]
    vectors: np.ndarray
    names: dict[str, str]


def prepare_code_rows(ollama: Ollama, code: CodeGraph, passages: list[tuple[str, Chunk]]) -> PreparedCodeRows:
    """Prepare native rows and eligible name vectors without reading any store."""
    embedded = [s for s in code.symbols if enters_synonym_search(s.id, s.name)]
    names = {s.id: name_text_of(s.name) for s in embedded}
    names.update({d.id: name_text_of(d.name) for d in code.data_objects})
    ids = [s.id for s in embedded] + [d.id for d in code.data_objects]
    vectors = ollama.embed([names[i] for i in ids], kind="document").copy() if ids else _NO_VECTORS.copy()
    by_id = dict(zip(ids, vectors, strict=True))
    commits, modifies, precedes = _history_rows(code)
    return PreparedCodeRows(
        symbols=[{**s.row(), "embedding": _vector(by_id, s.id)} for s in code.symbols],
        data_objects=[{**d.row(), "embedding": _vector(by_id, d.id)} for d in code.data_objects],
        commits=commits,
        modifies=modifies,
        precedes=precedes,
        edges=[asdict(edge) for edge in code.edges],
        definitions=[(node, pid) for pid, chunk in passages for node in chunk.defines],
        ids=ids,
        vectors=vectors,
        names=names,
    )


def extract_chunk_prose(
    ollama: Ollama,
    passages: list[tuple[str, Chunk]],
    *,
    workers: int = 2,
    on_progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[openie.Extraction]:
    """Apply the shared prose/doc gate; append empty skipped rows in input order."""
    wanted = [(pid, text) for pid, chunk in passages if (text := _openie_text(chunk)) is not None]
    extractions = openie.extract_many(
        ollama, wanted, workers=workers, on_progress=on_progress, should_stop=should_stop
    )
    wanted_ids = {pid for pid, _ in wanted}
    extractions.extend(openie.Extraction(passage_id=pid) for pid, _ in passages if pid not in wanted_ids)
    return extractions


@dataclass(frozen=True)
class FactPayloads:
    names: dict[str, str]
    triples: dict[str, tuple[str, str, str]]
    mentions: list[tuple[str, str]]
    statements: list[tuple[str, str]]

    def entity_rows(self, ids: list[str], vectors: np.ndarray) -> list[dict]:
        """Materialize only the explicit vector subset; never infer existing IDs."""
        return [
            {"id": eid, "name": self.names[eid], "embedding": vector.tolist()}
            for eid, vector in zip(ids, vectors, strict=True)
        ]

    def fact_rows(self, ids: list[str], vectors: np.ndarray) -> list[dict]:
        return [
            {
                "id": fid,
                "subject": s,
                "predicate": p,
                "object": o,
                "subject_id": entity_id(s),
                "object_id": entity_id(o),
                "embedding": vector.tolist(),
            }
            for fid, vector in zip(ids, vectors, strict=True)
            for s, p, o in [self.triples[fid]]
        ]


def prepare_fact_payloads(extractions: list[openie.Extraction]) -> FactPayloads:
    """Keep the original normalized endpoint identities and first-seen ordering."""
    names: dict[str, str] = {}
    triples: dict[str, tuple[str, str, str]] = {}
    mentions: list[tuple[str, str]] = []
    statements: list[tuple[str, str]] = []
    for extraction in extractions:
        for name in extraction.entity_names:
            eid = entity_id(name)
            names[eid] = name
            mentions.append((extraction.passage_id, eid))
        for s, p, o in extraction.clean_triples:
            fid = fact_id(s, p, o)
            triples[fid] = (s, p, o)
            statements.append((extraction.passage_id, fid))
    return FactPayloads(names, triples, mentions, statements)


def _openie_text(chunk: Chunk) -> str | None:
    """
    What OpenIE should read for this chunk, or None to skip it entirely (S2.7).

    `extract_text is None` is a prose chunk and behaves exactly as it always has -- the whole
    text, however short. A string is a code passage's doc-comment, and it is only worth two LLM
    calls when there is something in it: below `MIN_OPENIE_DOC_CHARS` we skip rather than extract
    a sentence fragment. The one case that must never happen is a body reaching the model, and
    it cannot: the chunker sets `extract_text` on every code passage.
    """
    if chunk.extract_text is None:
        return chunk.text
    return chunk.extract_text if len(chunk.extract_text.strip()) >= MIN_OPENIE_DOC_CHARS else None


def _vector(by_id: dict[str, np.ndarray], node_id: str) -> list[float]:
    """A node with no vector stores none: `enters_synonym_search` says which, and why."""
    found = by_id.get(node_id)
    return found.tolist() if found is not None else []


def _history_rows(code: CodeGraph) -> tuple[list[dict], list[dict], list[tuple[str, str]]]:
    """
    The commits, MODIFIES and PRECEDES of this source.

    WP2b's `read_history` is what fills them; until then a `CodeGraph` carries none and the three
    writers above are called with empty lists, which write nothing. This is the seam WP2b plugs
    into -- it adds the fields and this function starts returning rows.
    """
    commits = [_as_row(c) for c in getattr(code, "commits", ()) or ()]
    modifies = [_as_row(m) for m in getattr(code, "modifies", ()) or ()]
    precedes = [(a, b) for a, b in getattr(code, "precedes", ()) or ()]
    return commits, modifies, precedes


def _as_row(item) -> dict:
    return deepcopy(item.row() if hasattr(item, "row") else dict(item))


def name_text_of(name: str) -> str:
    """`codegraph.model.name_text`, imported late so this module never pulls tree-sitter in."""
    from ..codegraph.model import name_text

    return name_text(name)


def enters_synonym_search(node_id: str, name: str) -> bool:
    """
    Whether a code node's name vector is stored at all -- and it is stored for one purpose only,
    so a node that may not link is simply not embedded (D7: the symbol vector's only job is
    `find_synonyms`).

    Spike 2 measured cross-kind synonyms under the real embedder: of 26,400 symbol-entity pairs
    only 20 reach 0.80 and eight of those are nonsense, and raising the threshold to 0.85 makes
    it worse (43%) because the generic one-word names score highest -- `library` against "the
    library" at 0.94, `main` against "main office" at 0.86. Requiring two split tokens on the
    *symbol* side drops the nonsense rate to 27% and loses none of the ten known-good pairs
    (`OrderService` ~ "order service" is unaffected at 0.9368). Data objects are exempt: table
    names are single nouns, and `table orders` ~ "orders" is exactly the link D9 asks for.

    Not writing the vector is what makes the rule hold on both sides of the search -- the query
    list *and* the key matrix -- for every run, not just the one that wrote the symbol.
    """
    return label_of(node_id) != "Symbol" or len(split_identifier(name)) >= 2
