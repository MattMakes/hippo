"""
Step 2 of HippoRAG: turn passages into the graph.

Given the chunks of one source, this file:

1. embeds each passage and stores it as a Passage node
2. writes the code graph, when the source had one: symbols, data objects, their
   edges and a DEFINED_IN edge from every passage to what it defines
3. runs OpenIE on each passage (see openie.py) -- on the passage text for prose,
   on a symbol's doc-comment for code, and not at all over a body or DDL
4. stores every new entity and fact (with embeddings) and links
      Passage -MENTIONS-> Entity   and   Passage -STATES-> Fact
5. links entities whose names mean the same thing with SYNONYM edges
   (embedding similarity above `synonymy_threshold`, at most 100 per entity);
   symbols and data objects join that search, so "order service" finds
   `OrderService`
6. links prose passages to the symbols they name with REFERS_TO
7. gives every symbol its module's Leiden community
8. bumps the graph version so the in-memory graph reloads

The whole thing is one function, `index_source`, called from a background job.
Steps 2 and 5-7 only happen when the caller passed a `CodeGraph`.

Step 4 writes nodes first and links them afterwards, and the store's
`remove_orphans` deletes any entity or fact that has no link. So writing and
orphan removal must never overlap: see GRAPH_WRITE_LOCK below.
"""

from __future__ import annotations

import logging
import random
import re
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

import igraph as ig
import numpy as np

from ..ollama import Ollama
from . import openie
from .text import (
    entity_id,
    fact_id,
    fact_text,
    is_meaningful_phrase,
    label_of,
    make_id,
    split_identifier,
)

if TYPE_CHECKING:  # importing `codegraph` for real would pull tree-sitter into every indexer run
    from ..codegraph.model import CodeGraph

log = logging.getLogger(__name__)

SYNONYM_MAX_NEIGHBOURS = 100  # the reference stops after 100 neighbours per entity
SYNONYM_QUERY_BATCH = 1000
MAX_REFERS_TO_PER_PASSAGE = 20  # one prose passage may name a lot of code; keep the best 20
LEIDEN_SEED = 0  # Leiden is randomised; a fixed seed plus canonical labels makes it repeatable

# The nine counts `index_source` returns. They are the source's `meta["counts"]`, so the set of
# keys is part of the stored shape: always all nine, zero for what this run did not write.
COUNT_KEYS = (
    "passages",
    "entities",
    "facts",
    "synonyms",
    "symbols",
    "data_objects",
    "code_edges",
    "commits",
    "refers_to",
)

# The rule: hold this lock while you write entities/facts and their links, and hold it
# while you delete passages (which ends with remove_orphans). Then an orphan sweep can never
# run in the gap between "entity written" and "entity linked to its passage", and a delete
# that lands between our "does it exist?" check and our write is seen by the re-check we do
# under the lock. It is an RLock so a holder may call helpers that take it again. Ollama calls
# (embedding) happen *before* taking the lock: the lock is for database writes only.
GRAPH_WRITE_LOCK = threading.RLock()

# Called as on_progress(stage, done, total). `stage` is a short phrase for the UI.
Progress = Callable[[str, int, int], None]


# A doc-comment shorter than this says nothing OpenIE could turn into a fact, so it is skipped
# rather than extracted (S2.7). The chunker applies the same rule when it fills `extract_text`.
MIN_OPENIE_DOC_CHARS = 80


@dataclass
class Chunk:
    """
    What the indexer needs to know about one passage of a source.

    The two fields below the line are the code chunker's; positional `Chunk(ordinal, title, text)`
    still produces a plain prose chunk. `defines` are the code nodes this passage defines, which
    become DEFINED_IN edges. `extract_text` is the only gate on what OpenIE sees, and it is
    three-valued (S2.7): `None` means "extract `text`", today's behaviour and what every prose
    chunk carries; `""` means "skip OpenIE entirely"; a non-empty string is extracted in place of
    `text`, so a function's docstring reaches OpenIE and its body never does.
    """

    ordinal: int
    title: str
    text: str
    defines: list[str] = field(default_factory=list)
    extract_text: str | None = None


def passage_id(source_id: str, chunk: Chunk) -> str:
    return make_id("passage-", f"{source_id}:{chunk.ordinal}:{chunk.text}")


def index_source(
    store,
    ollama: Ollama,
    source_id: str,
    chunks: list[Chunk],
    *,
    code: CodeGraph | None = None,
    synonymy_threshold: float = 0.8,
    workers: int = 2,
    on_progress: Progress | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, int]:
    """
    Index all chunks of one source into the graph. Returns the nine counts for the log.

    `code` is what `codegraph.extract_code` made of the same documents; without it this is
    exactly the prose indexer it has always been, and the code stages do not run at all.
    `should_stop()` is checked between stages and before every passage; when it says so we raise openie.Stopped.
    """
    progress = on_progress or (lambda stage, done, total: None)

    def checkpoint(stage: str) -> None:
        if should_stop and should_stop():
            raise openie.Stopped(f"stopped before '{stage}'")

    chunks = [c for c in chunks if c.text.strip()]
    if not chunks:
        return empty_counts()

    # 1. Passages.
    progress("embedding passages", 0, len(chunks))
    ids = [passage_id(source_id, c) for c in chunks]
    embeddings = ollama.embed([c.text for c in chunks], kind="document")
    check_embedding_compatibility(store, ollama.embed_model, int(embeddings.shape[1]))
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

    # 2. The code graph, when this source had one.
    code_written = empty_counts()
    code_ids: list[str] = []
    code_vectors: np.ndarray = np.zeros((0, 0), dtype=np.float32)
    code_names: dict[str, str] = {}
    if code is not None:
        checkpoint("writing code graph")
        progress("writing code graph", 0, 1)
        code_ids, code_vectors, code_names, code_written = _write_code_graph(
            store, ollama, code, list(zip(ids, chunks, strict=True))
        )
        progress("writing code graph", 1, 1)

    # 3. OpenIE. `extract_text` decides what the model sees, and whether it is called at all.
    progress("extracting facts", 0, len(chunks))
    checkpoint("extracting facts")
    wanted = [(pid, c) for pid, c in zip(ids, chunks, strict=True) if _openie_text(c) is not None]
    extractions = openie.extract_many(
        ollama,
        [(pid, _openie_text(c)) for pid, c in wanted],
        workers=workers,
        on_progress=lambda done, total: progress("extracting facts", done, total),
        should_stop=should_stop,
    )
    # A passage we deliberately did not extract still gets a row, so the Source page shows an
    # empty extraction rather than a missing one, and re-indexing does not retry it.
    skipped = [pid for pid in ids if pid not in {p for p, _ in wanted}]
    extractions.extend(openie.Extraction(passage_id=pid) for pid in skipped)
    for ex in extractions:
        store.save_extraction(ex.passage_id, ex.entities, ex.triples, ex.error)

    # 3. Entities and facts.
    checkpoint("saving entities and facts")
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

    # Ask the store once which ids it already has (one query, not one per id), then embed
    # only the new ones. Both are done before taking the lock: embedding is the slow part.
    known_entities = store.existing_entity_ids(list(names))
    new_entity_ids = [eid for eid in names if eid not in known_entities]
    new_entity_vectors = ollama.embed([names[eid] for eid in new_entity_ids], kind="document")
    known_facts = store.existing_fact_ids(list(triples))
    new_fact_ids = [fid for fid in triples if fid not in known_facts]
    new_fact_vectors = ollama.embed([fact_text(*triples[fid]) for fid in new_fact_ids], kind="document")

    with GRAPH_WRITE_LOCK:
        # A delete may have pruned some of the "known" ids while we were embedding. Under the
        # lock nothing else can change, so re-check those and write them too.
        new_entity_ids, new_entity_vectors = _add_vanished(
            store.existing_entity_ids, known_entities, new_entity_ids, new_entity_vectors, names, ollama
        )
        store.add_entities(
            [
                {"id": eid, "name": names[eid], "embedding": vec.tolist()}
                for eid, vec in zip(new_entity_ids, new_entity_vectors, strict=True)
            ]
        )
        store.link_passage_entities(mentions)  # link right away: a linked entity is never an orphan

        fact_texts = {fid: fact_text(*triple) for fid, triple in triples.items()}
        new_fact_ids, new_fact_vectors = _add_vanished(
            store.existing_fact_ids, known_facts, new_fact_ids, new_fact_vectors, fact_texts, ollama
        )
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
        store.link_passage_facts(statements)
    progress("saving entities and facts", 1, 1)

    # 5. Synonym edges for the new entities, and for this source's code nodes: one pass over
    #    entity ⊕ code embeddings links "order service" to `OrderService` whichever arrived first.
    progress("linking synonyms", 0, 1)
    synonyms = find_synonyms(
        store,
        new_entity_ids + code_ids,
        _stacked(new_entity_vectors, code_vectors),
        {**names, **code_names},
        threshold=synonymy_threshold,
    )
    store.add_synonyms(synonyms)
    progress("linking synonyms", 1, 1)

    refers: list[dict] = []
    if code is not None:
        # 6. REFERS_TO from every passage OpenIE read as prose to the code it names.
        checkpoint("linking mentions")
        progress("linking mentions", 0, 1)
        refers = refers_to_rows(
            code, [(pid, _scanned(c)) for pid, c in zip(ids, chunks, strict=True) if _is_prose(c)]
        )
        store.add_refers_to(refers)
        progress("linking mentions", 1, 1)

        # 7. The subsystem label every symbol shows.
        checkpoint("communities")
        progress("communities", 0, 1)
        store.set_symbol_communities(module_communities(code))
        progress("communities", 1, 1)

    # 8. Tell the in-memory graph to reload.
    store.set_meta("embed_model", ollama.embed_model)
    store.set_meta("embedding_dim", int(embeddings.shape[1]) if len(embeddings) else None)
    store.bump_graph_version()
    return {
        **code_written,
        "passages": len(chunks),
        "entities": len(new_entity_ids),
        "facts": len(new_fact_ids),
        "synonyms": len(synonyms),
        "refers_to": len(refers),
    }


def empty_counts() -> dict[str, int]:
    return dict.fromkeys(COUNT_KEYS, 0)


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


def _scanned(chunk: Chunk) -> str:
    """
    The text the name scanner reads: what a *person* wrote, never what hippo generated.

    For every prose passage that is the passage itself, unchanged. For a commit passage it is
    the message alone, not the `Touched: …` line the chunker appended: those names were built
    from this source's own MODIFIES edges, so scanning them back out would manufacture a
    REFERS_TO for every pair MODIFIES already has -- evidence derived from itself, at a lower
    omega than the edge it came from.
    """
    return chunk.text if chunk.extract_text is None else (chunk.extract_text or chunk.text)


def _is_prose(chunk: Chunk) -> bool:
    """
    Whether this passage is scanned for the code it names.

    The rule is "whatever OpenIE read as prose": a passage with no `extract_text` is prose to
    this file, so it is prose to the name scanner too. Code passages are excluded because their
    symbol already has DEFINED_IN and their body is not prose. A commit passage carries its
    message as `extract_text`, so it is named explicitly -- WP2b writes those chunks.
    """
    return chunk.extract_text is None or any(label_of(node) == "Commit" for node in chunk.defines)


def _stacked(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Concatenate two embedding blocks, either of which may be empty (and so have no width)."""
    if len(first) == 0:
        return second
    if len(second) == 0:
        return first
    return np.concatenate([first, second])


def _add_vanished(
    existing_ids: Callable[[list[str]], set[str]],
    known: set[str],
    new_ids: list[str],
    new_vectors: np.ndarray,
    text_of: dict[str, str],
    ollama: Ollama,
) -> tuple[list[str], np.ndarray]:
    """
    Call with GRAPH_WRITE_LOCK held. `known` are the ids we skipped because the store had them;
    if a delete removed some meanwhile, embed those now and return them along with the new ones.
    Nothing was skipped -> nothing to re-check, no extra query.
    """
    if not known:
        return new_ids, new_vectors
    vanished = sorted(known - existing_ids(sorted(known)))
    if not vanished:
        return new_ids, new_vectors
    log.info("%d ids were deleted while we were embedding; adding them again", len(vanished))
    vectors = ollama.embed([text_of[i] for i in vanished], kind="document")
    return new_ids + vanished, np.concatenate([new_vectors, vectors]) if len(new_ids) else vectors


class EmbeddingMismatch(ValueError):
    """The graph was built with a different embedding model; its vectors cannot be compared with new ones."""


def check_embedding_compatibility(store, embed_model: str, dim: int) -> None:
    """
    Vectors from two different embedding models live in different spaces, so mixing them
    would make similarity scores meaningless. If the graph already holds passages made with
    another model (or another vector size), refuse with a message that says what to do.
    """
    if store.stats().get("passages", 0) == 0:
        return
    built_with = store.get_meta("embed_model")
    built_dim = store.get_meta("embedding_dim")
    if (built_with and built_with != embed_model) or (built_dim and int(built_dim) != dim):
        raise EmbeddingMismatch(
            f"the memory was built with embedding model {built_with!r} ({built_dim} numbers per vector) but this "
            f"server uses {embed_model!r} ({dim}). Use 'Re-index everything' on the Settings page, or set "
            f"HIPPO_EMBED_MODEL back to {built_with!r}."
        )


def find_synonyms(
    store, new_ids: list[str], new_vectors: np.ndarray, names: dict[str, str], *, threshold: float
) -> list[tuple[str, str, float]]:
    """
    For each new node, find existing ones whose name embedding is very similar.

    This is the reference's `add_synonymy_edges`: cosine similarity, keep neighbours above
    `threshold` (0.8), at most 100 per entity, skip tiny phrases like "a" or "12". The keys are
    entity ⊕ code embeddings, so one pass links a new entity to an existing symbol and a new
    symbol to an existing entity. `names` is what each id embedded -- an entity's name, or a code
    node's `name_text`. Which code nodes are in the key matrix at all is decided when they are
    written, by `enters_synonym_search`.
    """
    if len(new_ids) == 0:
        return []
    entity_ids, entity_vectors = store.load_entity_embeddings()
    node_ids, node_vectors = store.load_code_embeddings()
    all_ids = [*entity_ids, *node_ids]
    all_vectors = [*entity_vectors, *node_vectors]
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


# ------------------------------------------------------------- the code graph


def _write_code_graph(
    store, ollama: Ollama, code: CodeGraph, passages: list[tuple[str, Chunk]]
) -> tuple[list[str], np.ndarray, dict[str, str], dict[str, int]]:
    """
    Write one source's symbols, data objects, edges and DEFINED_IN links.

    Embedding happens first and outside the lock, like every other Ollama call in this file.
    Returns what `find_synonyms` needs -- the ids, their vectors and the text each one embeds --
    so the cross-kind search runs once, together with the new entities.
    """
    embedded = [s for s in code.symbols if enters_synonym_search(s.id, s.name)]
    names = {s.id: name_text_of(s.name) for s in embedded}
    names.update({d.id: name_text_of(d.name) for d in code.data_objects})
    ids = [s.id for s in embedded] + [d.id for d in code.data_objects]
    vectors = ollama.embed([names[i] for i in ids], kind="document") if ids else _NO_VECTORS
    by_id = dict(zip(ids, vectors, strict=True))

    commits, modifies, precedes = _history_rows(code)
    definitions = [(node, pid) for pid, chunk in passages for node in chunk.defines]
    with GRAPH_WRITE_LOCK:
        store.add_symbols([{**s.row(), "embedding": _vector(by_id, s.id)} for s in code.symbols])
        store.add_data_objects([{**d.row(), "embedding": _vector(by_id, d.id)} for d in code.data_objects])
        store.add_commits(commits)
        store.add_modifies(modifies)
        store.add_precedes(precedes)
        store.add_code_edges([asdict(edge) for edge in code.edges])
        store.link_definitions(definitions)
    written = {
        "symbols": len(code.symbols),
        "data_objects": len(code.data_objects),
        "code_edges": len(code.edges),
        "commits": len(commits),
    }
    return ids, vectors, names, {**empty_counts(), **written}


_NO_VECTORS = np.zeros((0, 0), dtype=np.float32)


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
    return item.row() if hasattr(item, "row") else dict(item)


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


# ------------------------------------------------------------ REFERS_TO

BACKTICKED = re.compile(r"`([^`\n]+)`")
QUALIFIED = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")
WORD = re.compile(r"[A-Za-z0-9]+")


def refers_to_rows(code: CodeGraph, passages: list[tuple[str, str]]) -> list[dict]:
    """
    REFERS_TO from prose to the code it names: `{passage_id, node_id, omega, token}` rows.

    Two ways in, at the two omegas the table gives. A backticked span or a dotted name that is
    exactly a symbol's name, qualname or display name is a deliberate reference, 0.85. A run of
    ordinary words matching a name's split tokens -- "the order service" reaching `OrderService`
    -- is a guess, 0.60, and only names that split into two or more tokens are offered that way,
    so "run", "place" and "orders" in English prose never link.

    The index is built from `code` rather than from the store: the indexer has no `AppContext`,
    and the in-memory graph does not hold this source yet.
    """
    exact, phrases = _name_index(code)
    lengths = sorted({len(p) for p in phrases})
    rows: list[dict] = []
    for passage_id, text in passages:
        best: dict[str, tuple[float, str]] = {}
        for token in [*BACKTICKED.findall(text), *QUALIFIED.findall(text)]:
            for node_id in exact.get(token.strip(), ()):
                _keep_best(best, node_id, 0.85, token.strip())
        words = [w.lower() for w in WORD.findall(text)]
        for phrase in _phrases_in(words, lengths, phrases):
            for node_id in phrases[phrase]:
                _keep_best(best, node_id, 0.60, " ".join(phrase))
        ranked = sorted(best.items(), key=lambda item: (-item[1][0], item[1][1], item[0]))
        rows.extend(
            {"passage_id": passage_id, "node_id": node_id, "omega": omega, "token": token}
            for node_id, (omega, token) in ranked[:MAX_REFERS_TO_PER_PASSAGE]
        )
    return rows


def _name_index(code: CodeGraph) -> tuple[dict[str, list[str]], dict[tuple[str, ...], list[str]]]:
    exact: dict[str, list[str]] = {}
    phrases: dict[tuple[str, ...], list[str]] = {}
    for node in [*code.symbols, *code.data_objects]:
        for spelling in {node.name, node.qualname, getattr(node, "display", "")}:
            if spelling:
                exact.setdefault(spelling, []).append(node.id)
        tokens = tuple(split_identifier(node.name))
        if len(tokens) >= 2:
            phrases.setdefault(tokens, []).append(node.id)
    return exact, phrases


def _phrases_in(words: list[str], lengths: list[int], phrases: dict) -> list[tuple[str, ...]]:
    """Which known token runs appear in this text, looked up by n-gram rather than scanned."""
    found = []
    for size in lengths:
        for start in range(len(words) - size + 1):
            gram = tuple(words[start : start + size])
            if gram in phrases and gram not in found:
                found.append(gram)
    return found


def _keep_best(best: dict[str, tuple[float, str]], node_id: str, omega: float, token: str) -> None:
    if node_id not in best or best[node_id][0] < omega:
        best[node_id] = (omega, token)


# ----------------------------------------------------------- communities


def module_communities(code: CodeGraph) -> dict[str, int]:
    """
    Every symbol's Leiden community, taken from its module (D11).

    The projection is one vertex per module and one weighted edge wherever a symbol of one module
    relates to a symbol of another, so the label reads as a subsystem rather than as a call
    cluster. S2.10: Leiden is randomised, so the RNG is seeded and the community numbers are then
    relabelled by the lexicographically smallest module in each -- otherwise two runs over the
    same tree would disagree about integers that mean the same thing.
    """
    module_of = {s.id: s.module for s in code.symbols if s.module}
    modules = sorted(set(module_of.values()))
    if not modules:
        return {}
    position = {name: i for i, name in enumerate(modules)}
    weights: Counter[tuple[int, int]] = Counter()
    for edge in code.edges:
        a, b = module_of.get(edge.a), module_of.get(edge.b)
        if a and b and a != b:
            weights[tuple(sorted((position[a], position[b])))] += 1
    pairs = sorted(weights)
    graph = ig.Graph(n=len(modules), edges=pairs, directed=False)
    membership = _leiden(graph, [weights[pair] for pair in pairs])
    labels = _canonical_labels(membership, modules)
    return {node_id: labels[membership[position[module]]] for node_id, module in module_of.items()}


def _leiden(graph: ig.Graph, weights: list[int]) -> list[int]:
    """Seeded, so the same projection always partitions the same way."""
    previous = random.Random(LEIDEN_SEED)
    ig.set_random_number_generator(previous)
    try:
        clustering = graph.community_leiden(
            objective_function="modularity", weights=weights or None, n_iterations=2
        )
    finally:
        ig.set_random_number_generator(random)  # a global; never leave it seeded for someone else
    return list(clustering.membership)


def _canonical_labels(membership: list[int], modules: list[str]) -> dict[int, int]:
    """Number the communities by their smallest module name, so the integers mean something."""
    smallest: dict[int, str] = {}
    for module, community in zip(modules, membership, strict=True):
        smallest[community] = min(smallest.get(community, module), module)
    return {community: i for i, community in enumerate(sorted(smallest, key=lambda c: smallest[c]))}
