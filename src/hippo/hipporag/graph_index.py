"""
Step 3 of HippoRAG: the graph, loaded into memory so search is fast.

Neo4j is where the graph *lives*; this file is where it *runs*. Loading pulls
every entity, passage, fact and link out of Neo4j once and builds:

* an `igraph` graph whose vertices are entities first, then passages
* numpy matrices of fact and passage embeddings (for similarity to a question)
* little lookup tables (id -> vertex index, entity -> how many passages mention it)

The graph is rebuilt whenever Neo4j's `graph_version` counter changes (after
indexing or applying a changeset). Building it is the only slow part; a
search afterwards takes milliseconds.

Edge weights follow the reference exactly: an edge between two nodes gets
    max(number of facts linking them, 1.0 if a passage mentions the entity, best synonym score)
and a TUNED edge (from an applied changeset) replaces that number outright.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import igraph as ig
import numpy as np

log = logging.getLogger(__name__)

ENTITY = "entity"
PASSAGE = "passage"


@dataclass
class Passage:
    id: str
    title: str
    text: str
    source_id: str
    source_name: str
    ordinal: int


@dataclass
class Fact:
    id: str
    subject: str
    predicate: str
    object: str
    subject_id: str
    object_id: str
    passage_ids: list[str]

    @property
    def triple(self) -> list[str]:
        return [self.subject, self.predicate, self.object]


@dataclass
class Edge:
    """Why two nodes are connected. `weight` is what PPR uses."""

    fact_count: int = 0
    mention: bool = False
    synonym_score: float = 0.0
    tuned: float | None = None

    @property
    def weight(self) -> float:
        if self.tuned is not None:
            return self.tuned
        return max(float(self.fact_count), 1.0 if self.mention else 0.0, self.synonym_score)

    @property
    def kinds(self) -> list[str]:
        kinds = []
        if self.fact_count:
            kinds.append("fact")
        if self.mention:
            kinds.append("mention")
        if self.synonym_score > 0:
            kinds.append("synonym")
        if self.tuned is not None:
            kinds.append("tuned")
        return kinds


@dataclass
class EdgeEdit:
    """A temporary edge change for a simulation: set the weight between two node ids (0 removes the edge)."""

    a: str
    b: str
    weight: float


@dataclass
class GraphIndex:
    version: int
    node_ids: list[str]  # vertex index -> node id (entities first, then passages)
    node_kind: list[str]  # vertex index -> "entity" | "passage"
    idx_of: dict[str, int]  # node id -> vertex index
    entity_names: dict[str, str]  # entity id -> display name
    entity_boost: np.ndarray  # per vertex, 1.0 unless someone tuned it
    entity_passage_count: np.ndarray  # per vertex: how many passages mention this entity (node specificity)
    passages: list[Passage]  # passage rows, aligned with `passage_vertices`
    passage_vertices: np.ndarray  # vertex index of each passage
    passage_embeddings: np.ndarray  # (num passages, dim)
    facts: list[Fact]
    fact_embeddings: np.ndarray  # (num facts, dim)
    fact_index_of: dict[str, int]
    graph: ig.Graph
    edges: dict[tuple[int, int], Edge] = field(default_factory=dict)  # (low vertex, high vertex) -> Edge

    # ------------------------------------------------------------- loading

    @classmethod
    def load(cls, store, version: int | None = None) -> GraphIndex:
        started = time.time()
        version = store.graph_version() if version is None else version

        # Neo4j returns nodes in no promised order (deleted node ids get reused), so sort here:
        # vertex numbers are recorded in traces, and a stable numbering keeps old traces readable.
        entity_rows = sorted(store.load_entities(), key=lambda r: (r.get("created_at") or "", r["id"]))
        passage_rows = sorted(store.load_passages(), key=lambda r: (r["source_id"], r["ordinal"] or 0))
        fact_rows = store.load_facts()
        # A row without a usable vector cannot take part in similarity search; drop it here so the
        # embedding matrices stay aligned with the row lists (a misaligned matrix would rank the wrong passage).
        passage_rows = _rows_with_good_vectors(passage_rows, "passage")
        fact_rows = _rows_with_good_vectors(fact_rows, "fact")

        node_ids = [r["id"] for r in entity_rows] + [r["id"] for r in passage_rows]
        node_kind = [ENTITY] * len(entity_rows) + [PASSAGE] * len(passage_rows)
        idx_of = {node_id: i for i, node_id in enumerate(node_ids)}

        boost = np.ones(len(node_ids))
        passage_count = np.zeros(len(node_ids))
        for i, row in enumerate(entity_rows):
            stored_boost = row.get("boost")
            boost[i] = (
                1.0 if stored_boost is None else float(stored_boost)
            )  # 0 is a real value: "mute this entity"
            passage_count[i] = float(row.get("passage_count") or 0)

        passages = [
            Passage(
                r["id"],
                r["title"] or "",
                r["text"] or "",
                r["source_id"],
                r["source_name"] or "",
                int(r["ordinal"] or 0),
            )
            for r in passage_rows
        ]
        passage_vertices = np.array([idx_of[p.id] for p in passages], dtype=np.int64)
        passage_embeddings = _matrix([r["embedding"] for r in passage_rows])

        facts = [
            Fact(
                r["id"],
                r["subject"],
                r["predicate"],
                r["object"],
                r["subject_id"],
                r["object_id"],
                list(r["passage_ids"] or []),
            )
            for r in fact_rows
        ]
        fact_embeddings = _matrix([r["embedding"] for r in fact_rows])
        fact_index_of = {f.id: i for i, f in enumerate(facts)}

        edges: dict[tuple[int, int], Edge] = {}

        def edge(a_id: str, b_id: str) -> Edge | None:
            a, b = idx_of.get(a_id), idx_of.get(b_id)
            if a is None or b is None or a == b:
                return None
            return edges.setdefault((min(a, b), max(a, b)), Edge())

        for row in store.load_fact_edges():
            e = edge(row["a"], row["b"])
            if e is not None:
                e.fact_count += int(row["weight"])
        for row in store.load_mentions():
            e = edge(row["passage_id"], row["entity_id"])
            if e is not None:
                e.mention = True
        for row in store.load_synonyms():
            e = edge(row["a"], row["b"])
            if e is not None:
                e.synonym_score = max(e.synonym_score, float(row["score"] or 0.0))
        for row in store.load_tuned_edges():
            e = edge(row["a"], row["b"])
            if e is not None:
                e.tuned = float(row["weight"])

        graph = build_igraph(len(node_ids), edges)
        log.info(
            "Graph v%s loaded: %d entities, %d passages, %d facts, %d edges in %.1fs",
            version,
            len(entity_rows),
            len(passages),
            len(facts),
            graph.ecount(),
            time.time() - started,
        )
        return cls(
            version=version,
            node_ids=node_ids,
            node_kind=node_kind,
            idx_of=idx_of,
            entity_names={r["id"]: r["name"] for r in entity_rows},
            entity_boost=boost,
            entity_passage_count=passage_count,
            passages=passages,
            passage_vertices=passage_vertices,
            passage_embeddings=passage_embeddings,
            facts=facts,
            fact_embeddings=fact_embeddings,
            fact_index_of=fact_index_of,
            graph=graph,
            edges=edges,
        )

    # ------------------------------------------------------------ queries

    @property
    def num_nodes(self) -> int:
        return len(self.node_ids)

    @property
    def num_entities(self) -> int:
        return len(self.node_ids) - len(self.passages)

    def is_empty(self) -> bool:
        return len(self.passages) == 0

    def name_of(self, vertex: int) -> str:
        node_id = self.node_ids[vertex]
        if self.node_kind[vertex] == ENTITY:
            return self.entity_names.get(node_id, node_id)
        return self.passages[self.passage_position(vertex)].title

    def passage_position(self, vertex: int) -> int:
        """Vertex index -> position in `self.passages` (passages come after all entities)."""
        return vertex - self.num_entities

    def passage_by_id(self, passage_id: str) -> Passage | None:
        vertex = self.idx_of.get(passage_id)
        if vertex is None or self.node_kind[vertex] != PASSAGE:
            return None
        return self.passages[self.passage_position(vertex)]

    def neighbors(self, vertex: int, graph: ig.Graph | None = None) -> list[tuple[int, float]]:
        """(neighbour vertex, edge weight) pairs. An unknown vertex simply has none."""
        graph = graph or self.graph
        if vertex < 0 or vertex >= graph.vcount():
            # A stale trace can name a vertex that no longer exists. igraph would raise, and an igraph
            # error inside a web worker thread can take the whole process down, so say "no neighbours".
            return []
        out = []
        for edge_id in graph.incident(vertex):
            e = graph.es[edge_id]
            other = e.target if e.source == vertex else e.source
            out.append((other, float(e["weight"])))
        return out

    def edge_between(self, a: int, b: int) -> Edge | None:
        return self.edges.get((min(a, b), max(a, b)))

    # ----------------------------------------------------------------- PPR

    def ppr(self, reset: np.ndarray, damping: float, graph: ig.Graph | None = None) -> np.ndarray:
        """
        Personalized PageRank: start "activation" on the seed nodes (`reset`) and let it
        spread along weighted edges. Returns one score per vertex. Same call as the reference.
        """
        graph = graph or self.graph
        reset = np.where(np.isnan(reset) | (reset < 0), 0.0, reset)
        if reset.sum() <= 0:
            raise ValueError("PPR needs at least one seed node with a positive weight")
        scores = graph.personalized_pagerank(
            vertices=range(graph.vcount()),
            damping=damping,
            directed=False,
            weights="weight",
            reset=reset.tolist(),
            implementation="prpack",
        )
        return np.asarray(scores, dtype=np.float64)

    # ------------------------------------------------------ access scope

    def scoped(self, visible_sources: frozenset[str] | set[str]) -> GraphIndex:
        """
        The part of this graph a user may see: passages of `visible_sources`, the entities those
        passages mention, the facts they state, and only the edges among them.

        This is what makes access control hold for search: PPR runs on the returned graph, so
        activation can never pass through a hidden passage, and a hidden passage can never be
        ranked. Edge weights and passage counts are recomputed from the visible passages alone,
        so a fact stated only in a hidden passage neither links its entities nor seeds them.
        """
        visible = set(visible_sources)
        keep_passages = [p for p in self.passages if p.source_id in visible]
        if len(keep_passages) == len(self.passages):
            return self  # nothing hidden: share the full index (and its cache)

        keep_passage_ids = {p.id for p in keep_passages}
        old_passage_vertices = {
            int(self.passage_vertices[i]) for i, p in enumerate(self.passages) if p.id in keep_passage_ids
        }

        # Entities stay only when a visible passage mentions them (a mention edge to a kept passage).
        keep_entity_vertices: set[int] = set()
        mention_count: dict[int, int] = {}
        for (a, b), e in self.edges.items():
            if not e.mention:
                continue
            # Mention edges join a passage and an entity; entities come first in vertex order.
            entity_v, passage_v = (a, b) if self.node_kind[a] == ENTITY else (b, a)
            if passage_v in old_passage_vertices and self.node_kind[entity_v] == ENTITY:
                keep_entity_vertices.add(entity_v)
                mention_count[entity_v] = mention_count.get(entity_v, 0) + 1

        entity_vertices = sorted(keep_entity_vertices)
        entity_ids = [self.node_ids[v] for v in entity_vertices]
        node_ids = entity_ids + [p.id for p in keep_passages]
        node_kind = [ENTITY] * len(entity_ids) + [PASSAGE] * len(keep_passages)
        idx_of = {node_id: i for i, node_id in enumerate(node_ids)}
        old_to_new = {v: i for i, v in enumerate(entity_vertices)}
        for i, p in enumerate(keep_passages):
            old_to_new[self.idx_of[p.id]] = len(entity_ids) + i

        boost = np.ones(len(node_ids))
        passage_count = np.zeros(len(node_ids))
        for old_v, new_v in old_to_new.items():
            if self.node_kind[old_v] == ENTITY:
                boost[new_v] = self.entity_boost[old_v]
                passage_count[new_v] = float(mention_count.get(old_v, 0))

        passage_positions = [i for i, p in enumerate(self.passages) if p.id in keep_passage_ids]
        passage_vertices = np.array([idx_of[p.id] for p in keep_passages], dtype=np.int64)
        passage_embeddings = (
            self.passage_embeddings[passage_positions] if len(passage_positions) else _matrix([])
        )

        # Facts stay when a visible passage states them; their passage lists shrink to the visible ones.
        facts: list[Fact] = []
        fact_positions: list[int] = []
        for i, f in enumerate(self.facts):
            shown_in = [pid for pid in f.passage_ids if pid in keep_passage_ids]
            if shown_in and f.subject_id in idx_of and f.object_id in idx_of:
                facts.append(
                    Fact(f.id, f.subject, f.predicate, f.object, f.subject_id, f.object_id, shown_in)
                )
                fact_positions.append(i)
        fact_embeddings = self.fact_embeddings[fact_positions] if fact_positions else _matrix([])
        fact_index_of = {f.id: i for i, f in enumerate(facts)}

        # Edges among kept nodes. Fact counts are recomputed from the visible (passage, fact) pairs;
        # mention, synonym and tuned values carry over as they are per pair, not per passage.
        edges: dict[tuple[int, int], Edge] = {}
        for (a, b), e in self.edges.items():
            na, nb = old_to_new.get(a), old_to_new.get(b)
            if na is None or nb is None:
                continue
            edges[(min(na, nb), max(na, nb))] = Edge(
                fact_count=0, mention=e.mention, synonym_score=e.synonym_score, tuned=e.tuned
            )
        for f in facts:
            a, b = idx_of[f.subject_id], idx_of[f.object_id]
            if a == b:
                continue
            e = edges.setdefault((min(a, b), max(a, b)), Edge())
            e.fact_count += len(f.passage_ids)

        return GraphIndex(
            version=self.version,
            node_ids=node_ids,
            node_kind=node_kind,
            idx_of=idx_of,
            entity_names={eid: self.entity_names.get(eid, eid) for eid in entity_ids},
            entity_boost=boost,
            entity_passage_count=passage_count,
            passages=list(keep_passages),
            passage_vertices=passage_vertices,
            passage_embeddings=passage_embeddings,
            facts=facts,
            fact_embeddings=fact_embeddings,
            fact_index_of=fact_index_of,
            graph=build_igraph(len(node_ids), edges),
            edges=edges,
        )

    # ---------------------------------------------------- what-if edits

    def graph_with_edits(self, edits: list[EdgeEdit]) -> ig.Graph:
        """A copy of the graph with some edge weights changed/added/removed (for simulations)."""
        if not edits:
            return self.graph
        changed = {k: Edge(**vars(v)) for k, v in self.edges.items()}
        for edit in edits:
            a, b = self.idx_of.get(edit.a), self.idx_of.get(edit.b)
            if a is None or b is None or a == b:
                continue
            e = changed.setdefault((min(a, b), max(a, b)), Edge())
            e.tuned = float(edit.weight)
        return build_igraph(self.num_nodes, changed)


def build_igraph(num_nodes: int, edges: dict[tuple[int, int], Edge]) -> ig.Graph:
    pairs = [(a, b) for (a, b), e in edges.items() if e.weight > 0]
    weights = [e.weight for e in edges.values() if e.weight > 0]
    graph = ig.Graph(n=num_nodes, edges=pairs, directed=False)
    graph.es["weight"] = weights
    return graph


def _rows_with_good_vectors(rows: list[dict], kind: str) -> list[dict]:
    """Keep rows whose embedding is a list of the majority length; log the ones that are not."""
    lengths = [len(r["embedding"]) for r in rows if isinstance(r.get("embedding"), list) and r["embedding"]]
    if not lengths:
        return [r for r in rows if isinstance(r.get("embedding"), list) and r["embedding"]]
    expected = max(set(lengths), key=lengths.count)
    good = [r for r in rows if isinstance(r.get("embedding"), list) and len(r["embedding"]) == expected]
    if len(good) != len(rows):
        log.warning(
            "Ignoring %d %s row(s) whose embedding is missing or not %d numbers long (built with a different "
            "embedding model?). Re-index those sources.",
            len(rows) - len(good),
            kind,
            expected,
        )
    return good


def _matrix(vectors: list[list[float]]) -> np.ndarray:
    """A float32 matrix from equal-length vectors (see _rows_with_good_vectors), or an empty (0, 0) one."""
    if not vectors:
        return np.zeros((0, 0), dtype=np.float32)
    return np.asarray(vectors, dtype=np.float32)
