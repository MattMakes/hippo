"""
Step 3 of HippoRAG: the graph, loaded into memory so search is fast.

The store is where the graph *lives*; this file is where it *runs*. Loading pulls
every entity, passage, fact, code node and link out of the store once and builds:

* an `igraph` graph whose vertices are entities, then symbols, data objects and
  commits, then passages
* numpy matrices of fact and passage embeddings (for similarity to a question)
* little lookup tables (id -> vertex index, node -> how specific it is, name -> node ids)

The graph is rebuilt whenever the store's `graph_version` counter changes (after
indexing or applying a changeset). Building it is the only slow part; a
search afterwards takes milliseconds.

**Passages come last, and that is load-bearing.** `passage_position` maps a vertex
to a row of `self.passages` by subtracting `first_passage_vertex`; a code vertex
placed after the passages would give a negative index, which silently serves the
wrong passage rather than raising.

Edge weights follow the reference, with one term added for code:
    max(number of facts linking them, 1.0 if a passage mentions the entity,
        entity-entity synonym score, code confidence x code_structural_scale)
and a TUNED edge (from an applied changeset) replaces that number outright. Every
term that exists only because code was indexed - CODE_EDGE, DEFINED_IN, REFERS_TO,
MODIFIES and a cross-kind synonym - is inside that last term, so
`code_structural_scale = 0` drops every code vertex out of the graph entirely.
Direction is not in igraph (PPR runs undirected, exactly as the reference does);
it lives in `code_out`/`code_in` for the path tools.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

import igraph as ig
import numpy as np

from ..store.code import SPECIFICITY_KINDS
from .text import split_identifier

log = logging.getLogger(__name__)

NodeKind = Literal["entity", "passage", "symbol", "data", "commit"]

ENTITY = "entity"
PASSAGE = "passage"
SYMBOL = "symbol"
DATA = "data"
COMMIT = "commit"

CODE_KINDS: tuple[str, ...] = (SYMBOL, DATA, COMMIT)


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
class CodeNode:
    """A symbol, data object or commit: one vertex, with whatever its kind carries."""

    id: str
    kind: str  # a NodeKind: "symbol", "data" or "commit"
    name: str  # what to show: a symbol's or table's name, a commit's short sha
    qualname: str = ""
    code_kind: str = ""  # module/class/function/method, or table/column/collection/label/rel_type
    lang: str = ""
    path: str = ""
    line_start: int = 0
    line_end: int = 0
    signature: str = ""
    doc: str = ""
    is_test: bool = False
    raises: list[str] = field(default_factory=list)
    community: int | None = None
    name_tokens: list[str] = field(default_factory=list)
    dialect: str = ""
    sha: str = ""
    author: str = ""
    date: str = ""
    message: str = ""
    ordinal: int = 0
    in_degree: int = 0
    source_id: str = ""
    source_name: str = ""


@dataclass
class DirectedEdge:
    """One code relation, with its direction kept. Named apart from `codegraph.model.CodeEdge`."""

    src: int  # vertex
    dst: int  # vertex
    kind: str  # INVOKES, IMPORTS, ..., or DEFINED_IN / REFERS_TO / MODIFIES / PRECEDES
    omega: float = 0.0
    provenance: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Edge:
    """Why two nodes are connected. `weight` is what PPR uses."""

    fact_count: int = 0
    mention: bool = False
    synonym_score: float = 0.0  # entity-entity synonyms only; a cross-kind one goes in `omega`
    tuned: float | None = None
    omega: float = 0.0  # the best code confidence between the pair; scaled by code_structural_scale
    code_kinds: list[str] = field(default_factory=list)

    def weight_at(self, scale: float) -> float:
        """The PPR weight at a given `code_structural_scale`. Only the code term moves."""
        if self.tuned is not None:
            return self.tuned  # a user set it by hand; nothing scales it
        return max(
            float(self.fact_count),
            1.0 if self.mention else 0.0,
            self.synonym_score,
            self.omega * scale,
        )

    @property
    def weight(self) -> float:
        """The weight at the default scale, which is what `explain.py` and the Graph page read."""
        return self.weight_at(1.0)

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
        kinds.extend(kind for kind in self.code_kinds if kind not in kinds)
        return kinds


@dataclass
class EdgeEdit:
    """A temporary edge change for a simulation: set the weight between two node ids (0 removes the edge)."""

    a: str
    b: str
    weight: float


@dataclass
class GraphIndex:
    """
    The whole graph in memory, plus the lookups a search needs.

    Vertex order is entities, symbols, data objects, commits, **passages last**.

    `graph` is the igraph at `code_structural_scale = 1.0`. A search that runs at another scale
    asks `graph_for_scale(scale)`, which rebuilds once and memoises per scale on this index; the
    memo dies with the index, which `graph_version` already invalidates. `graph_with_edits(edits,
    scale)` composes a simulation's edge edits with the same scale in one rebuild, so moving the
    slider *and* editing an edge still applies both.
    """

    version: int
    node_ids: list[str]  # vertex index -> node id (entities, code nodes, then passages)
    node_kind: list[str]  # vertex index -> a NodeKind
    idx_of: dict[str, int]  # node id -> vertex index
    entity_names: dict[str, str]  # entity id -> display name
    entity_boost: np.ndarray  # per vertex, 1.0 unless someone tuned it (code nodes included)
    specificity: np.ndarray  # per vertex: the divisor that damps a seed (see S2.4 in the plan)
    passages: list[Passage]  # passage rows, aligned with `passage_vertices`
    passage_vertices: np.ndarray  # vertex index of each passage
    passage_embeddings: np.ndarray  # (num passages, dim)
    facts: list[Fact]
    fact_embeddings: np.ndarray  # (num facts, dim)
    fact_index_of: dict[str, int]
    graph: ig.Graph
    edges: dict[tuple[int, int], Edge] = field(default_factory=dict)  # (low vertex, high vertex) -> Edge
    code_nodes: list[CodeNode] = field(default_factory=list)  # aligned with `code_vertices`
    code_vertices: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    code_out: dict[int, list[DirectedEdge]] = field(default_factory=dict)
    code_in: dict[int, list[DirectedEdge]] = field(default_factory=dict)
    name_index: dict[str, list[str]] = field(default_factory=dict)  # lowercase name/token -> node ids
    communities: dict[int, str] = field(default_factory=dict)  # community -> its canonical label
    # One rebuilt igraph per non-default code_structural_scale; see graph_for_scale.
    _scaled: dict[float, ig.Graph] = field(default_factory=dict, repr=False, compare=False)

    @property
    def entity_passage_count(self) -> np.ndarray:
        """The old name for `specificity`: `retriever.py` and the Graph page still read it."""
        return self.specificity

    # ------------------------------------------------------------- loading

    @classmethod
    def load(cls, store, version: int | None = None) -> GraphIndex:
        started = time.time()
        version = store.graph_version() if version is None else version

        # Neo4j returns nodes in no promised order (deleted node ids get reused), so sort here:
        # vertex numbers are recorded in traces, and a stable numbering keeps old traces readable.
        by_creation = lambda r: (r.get("created_at") or "", r["id"])  # noqa: E731 - a sort key, not a function
        entity_rows = sorted(store.load_entities(), key=by_creation)
        symbol_rows = sorted(store.load_symbols(), key=by_creation)
        data_rows = sorted(store.load_data_objects(), key=by_creation)
        commit_rows = sorted(store.load_commits(), key=by_creation)
        passage_rows = sorted(store.load_passages(), key=lambda r: (r["source_id"], r["ordinal"] or 0))
        fact_rows = store.load_facts()
        # A row without a usable vector cannot take part in similarity search; drop it here so the
        # embedding matrices stay aligned with the row lists (a misaligned matrix would rank the wrong passage).
        passage_rows = _rows_with_good_vectors(passage_rows, "passage")
        fact_rows = _rows_with_good_vectors(fact_rows, "fact")

        code_rows = (
            [(SYMBOL, r) for r in symbol_rows]
            + [(DATA, r) for r in data_rows]
            + [(COMMIT, r) for r in commit_rows]
        )
        # Passages last: `passage_position` subtracts `first_passage_vertex`, so a code vertex after
        # them would give a negative index and silently serve the wrong passage.
        node_ids = (
            [r["id"] for r in entity_rows]
            + [r["id"] for _kind, r in code_rows]
            + [r["id"] for r in passage_rows]
        )
        node_kind = (
            [ENTITY] * len(entity_rows) + [kind for kind, _r in code_rows] + [PASSAGE] * len(passage_rows)
        )
        idx_of = {node_id: i for i, node_id in enumerate(node_ids)}

        boost = np.ones(len(node_ids))
        passage_count = np.zeros(len(node_ids))
        for i, row in enumerate(entity_rows):
            stored_boost = row.get("boost")
            boost[i] = (
                1.0 if stored_boost is None else float(stored_boost)
            )  # 0 is a real value: "mute this entity"
            passage_count[i] = float(row.get("passage_count") or 0)

        code_nodes = [_code_node(kind, row) for kind, row in code_rows]
        code_vertices = np.array([idx_of[n.id] for n in code_nodes], dtype=np.int64)
        for (_kind, row), vertex, node in zip(code_rows, code_vertices, code_nodes, strict=True):
            stored_boost = row.get("boost")
            # Without this a changeset that boosts a symbol works in simulation and does nothing
            # when applied, because the applied boost never reaches the loaded graph.
            boost[vertex] = 1.0 if stored_boost is None else float(stored_boost)
            passage_count[vertex] = _code_specificity(node)

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
            if e is None:
                continue
            score = float(row["score"] or 0.0)
            a, b = idx_of[row["a"]], idx_of[row["b"]]
            if node_kind[a] == ENTITY and node_kind[b] == ENTITY:
                e.synonym_score = max(e.synonym_score, score)
            else:
                # A cross-kind synonym exists only because code was indexed, so it is scaled with
                # the rest of the code terms and must not ride the unscaled entity-entity slot.
                _add_code_term(e, score, "synonym")
        for row in store.load_tuned_edges():
            e = edge(row["a"], row["b"])
            if e is not None:
                e.tuned = float(row["weight"])

        # The code relations. Each is undirected in igraph (PPR is undirected, as the reference is)
        # and directed in code_out/code_in, which is what the path tools walk.
        code_out: dict[int, list[DirectedEdge]] = {}
        code_in: dict[int, list[DirectedEdge]] = {}

        def directed(a_id: str, b_id: str, kind: str, omega: float, provenance="", extra=None) -> None:
            a, b = idx_of.get(a_id), idx_of.get(b_id)
            if a is None or b is None or a == b:
                return
            arrow = DirectedEdge(a, b, kind, omega, provenance, extra or {})
            code_out.setdefault(a, []).append(arrow)
            code_in.setdefault(b, []).append(arrow)

        for row in store.load_code_edges():
            omega = float(row["omega"] or 0.0)
            directed(row["a"], row["b"], row["kind"], omega, row["provenance"], row["extra"])
            e = edge(row["a"], row["b"])
            if e is not None:
                _add_code_term(e, omega, row["kind"].lower())
        for row in store.load_definitions():
            directed(row["node_id"], row["passage_id"], "DEFINED_IN", 1.0)
            e = edge(row["node_id"], row["passage_id"])
            if e is not None:
                # Counts as a mention, but as the *weight term* 1.0 - not the `mention` flag, which
                # only ever joins an entity to a passage and is deliberately unscaled.
                _add_code_term(e, 1.0, "defined_in")
        for row in store.load_refers_to():
            omega = float(row["omega"] or 0.0)
            directed(row["passage_id"], row["node_id"], "REFERS_TO", omega, row["token"])
            e = edge(row["passage_id"], row["node_id"])
            if e is not None:
                _add_code_term(e, omega, "refers_to")
        for row in store.load_modifies():
            omega = float(row["omega"] or 0.0)
            directed(row["commit_id"], row["symbol_id"], "MODIFIES", omega, extra=row["hunk"])
            e = edge(row["commit_id"], row["symbol_id"])
            if e is not None:
                _add_code_term(e, omega, "modifies")
        for row in store.load_precedes():
            # PRECEDES stays out of igraph on purpose: 200 commits would chain every symbol they
            # touched into one neighbourhood. The history tool reads it from code_out.
            directed(row["a"], row["b"], "PRECEDES", 1.0)

        graph = build_igraph(len(node_ids), edges)
        log.info(
            "Graph v%s loaded: %d entities, %d code nodes, %d passages, %d facts, %d edges in %.1fs",
            version,
            len(entity_rows),
            len(code_nodes),
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
            specificity=passage_count,
            passages=passages,
            passage_vertices=passage_vertices,
            passage_embeddings=passage_embeddings,
            facts=facts,
            fact_embeddings=fact_embeddings,
            fact_index_of=fact_index_of,
            graph=graph,
            edges=edges,
            code_nodes=code_nodes,
            code_vertices=code_vertices,
            code_out=code_out,
            code_in=code_in,
            name_index=_name_index(code_nodes),
            communities=_community_labels(code_nodes),
        )

    # ------------------------------------------------------------ queries

    @property
    def num_nodes(self) -> int:
        return len(self.node_ids)

    @property
    def num_entities(self) -> int:
        """How many entity vertices there are - not "everything before the passages", which would
        count the code nodes too and report them as entities on the Graph page."""
        return len(self.entity_names)

    @property
    def first_code_vertex(self) -> int:
        """The vertex the code block starts at: symbols, then data objects, then commits."""
        return len(self.entity_names)

    @property
    def first_passage_vertex(self) -> int:
        """The vertex the passage block starts at: everything before it is an entity or code node."""
        return len(self.node_ids) - len(self.passages)

    def is_empty(self) -> bool:
        return len(self.passages) == 0

    def name_of(self, vertex: int) -> str:
        node_id = self.node_ids[vertex]
        kind = self.node_kind[vertex]
        if kind == ENTITY:
            return self.entity_names.get(node_id, node_id)
        if kind in CODE_KINDS:
            node = self.code_node_by_id(node_id)
            return (node.qualname or node.name) if node else node_id
        return self.passages[self.passage_position(vertex)].title

    def passage_position(self, vertex: int) -> int:
        """Vertex index -> position in `self.passages` (passages come after every other vertex)."""
        return vertex - self.first_passage_vertex

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

    # ----------------------------------------------------------- code nodes

    def code_node_by_id(self, node_id: str) -> CodeNode | None:
        vertex = self.idx_of.get(node_id)
        if vertex is None or self.node_kind[vertex] not in CODE_KINDS:
            return None
        return self.code_nodes[vertex - len(self.entity_names)]

    def code_node_at(self, vertex: int) -> CodeNode | None:
        if vertex < 0 or vertex >= len(self.node_kind) or self.node_kind[vertex] not in CODE_KINDS:
            return None
        return self.code_nodes[vertex - len(self.entity_names)]

    def out_edges(self, vertex: int) -> list[DirectedEdge]:
        """Code relations pointing away from this vertex (a calls b, a imports b, ...)."""
        return self.code_out.get(vertex, [])

    def in_edges(self, vertex: int) -> list[DirectedEdge]:
        """Code relations pointing at this vertex (who calls it, which commits touched it)."""
        return self.code_in.get(vertex, [])

    def defining_passages(self, vertex: int) -> list[int]:
        """The passage vertices a code node is written down in (its DEFINED_IN targets)."""
        return [e.dst for e in self.out_edges(vertex) if e.kind == "DEFINED_IN"]

    def symbols_defined_in(self, passage_vertex: int) -> list[int]:
        """The code vertices this passage defines - the reverse of `defining_passages`."""
        return [e.src for e in self.in_edges(passage_vertex) if e.kind == "DEFINED_IN"]

    def community_of(self, vertex: int) -> int | None:
        node = self.code_node_at(vertex)
        return node.community if node else None

    def community_name(self, community: int | None) -> str:
        """The subsystem label of a community: the lexicographically smallest member's qualname."""
        return "" if community is None else self.communities.get(community, "")

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
        passages mention, the code nodes those passages define, the facts they state, and only the
        edges among them.

        This is what makes access control hold for search: PPR runs on the returned graph, so
        activation can never pass through a hidden passage, and a hidden passage can never be
        ranked. Edge weights and specificity are recomputed from the visible passages alone, so a
        fact stated only in a hidden passage neither links its entities nor seeds them, and a
        symbol whose defining passages are all hidden has no vertex at all. That is one rule, not
        two: a node is visible when a visible passage reaches it, for every kind.
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

        # A code node stays when at least one passage it is DEFINED_IN is visible. A data object
        # takes that edge from *every* passage naming it, so a table named in ten files does not
        # vanish the moment its declaring file is hidden.
        keep_code = [
            (i, node)
            for i, node in enumerate(self.code_nodes)
            if any(dst in old_passage_vertices for dst in self.defining_passages(int(self.code_vertices[i])))
        ]
        code_vertices_old = [int(self.code_vertices[i]) for i, _node in keep_code]

        entity_vertices = sorted(keep_entity_vertices)
        entity_ids = [self.node_ids[v] for v in entity_vertices]
        code_nodes = [node for _i, node in keep_code]
        code_ids = [node.id for node in code_nodes]
        node_ids = entity_ids + code_ids + [p.id for p in keep_passages]
        node_kind = (
            [ENTITY] * len(entity_ids) + [node.kind for node in code_nodes] + [PASSAGE] * len(keep_passages)
        )
        idx_of = {node_id: i for i, node_id in enumerate(node_ids)}
        old_to_new = {v: i for i, v in enumerate(entity_vertices)}
        for i, old_v in enumerate(code_vertices_old):
            old_to_new[old_v] = len(entity_ids) + i
        for i, p in enumerate(keep_passages):
            old_to_new[self.idx_of[p.id]] = len(entity_ids) + len(code_ids) + i

        boost = np.ones(len(node_ids))
        passage_count = np.zeros(len(node_ids))
        for old_v, new_v in old_to_new.items():
            if self.node_kind[old_v] == ENTITY:
                boost[new_v] = self.entity_boost[old_v]
                passage_count[new_v] = float(mention_count.get(old_v, 0))
            elif self.node_kind[old_v] in CODE_KINDS:
                # A boost on a symbol must survive scoping, or a changeset that sets one works for
                # an unrestricted reader and silently does nothing for everyone else.
                boost[new_v] = self.entity_boost[old_v]

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
        # mention, synonym, tuned and the code terms carry over as they are per pair, not per passage.
        edges: dict[tuple[int, int], Edge] = {}
        for (a, b), e in self.edges.items():
            na, nb = old_to_new.get(a), old_to_new.get(b)
            if na is None or nb is None:
                continue
            # omega and code_kinds must be copied here, or a restricted reader silently gets a
            # differently *weighted* graph rather than a smaller one.
            edges[(min(na, nb), max(na, nb))] = Edge(
                fact_count=0,
                mention=e.mention,
                synonym_score=e.synonym_score,
                tuned=e.tuned,
                omega=e.omega,
                code_kinds=list(e.code_kinds),
            )
        for f in facts:
            a, b = idx_of[f.subject_id], idx_of[f.object_id]
            if a == b:
                continue
            e = edges.setdefault((min(a, b), max(a, b)), Edge())
            e.fact_count += len(f.passage_ids)

        # The directed code relations, renumbered, and the specificity recomputed from the ones
        # that survived: a symbol whose only caller is hidden is more specific here, not less.
        code_out: dict[int, list[DirectedEdge]] = {}
        code_in: dict[int, list[DirectedEdge]] = {}
        in_degree: dict[int, int] = {}
        for arrows in self.code_out.values():
            for arrow in arrows:
                src, dst = old_to_new.get(arrow.src), old_to_new.get(arrow.dst)
                if src is None or dst is None:
                    continue
                kept = DirectedEdge(src, dst, arrow.kind, arrow.omega, arrow.provenance, arrow.extra)
                code_out.setdefault(src, []).append(kept)
                code_in.setdefault(dst, []).append(kept)
                if arrow.kind in SPECIFICITY_KINDS:
                    in_degree[dst] = in_degree.get(dst, 0) + 1
        for new_v in (idx_of[node_id] for node_id in code_ids):
            passage_count[new_v] = float(in_degree.get(new_v, 0) + 1)

        return GraphIndex(
            version=self.version,
            node_ids=node_ids,
            node_kind=node_kind,
            idx_of=idx_of,
            entity_names={eid: self.entity_names.get(eid, eid) for eid in entity_ids},
            entity_boost=boost,
            specificity=passage_count,
            passages=list(keep_passages),
            passage_vertices=passage_vertices,
            passage_embeddings=passage_embeddings,
            facts=facts,
            fact_embeddings=fact_embeddings,
            fact_index_of=fact_index_of,
            graph=build_igraph(len(node_ids), edges),
            edges=edges,
            code_nodes=code_nodes,
            code_vertices=np.array([idx_of[node_id] for node_id in code_ids], dtype=np.int64),
            code_out=code_out,
            code_in=code_in,
            # Shared, not rebuilt: every consumer filters its hits through this index's `idx_of`,
            # so a hidden symbol can be named here and still never be reached.
            name_index=self.name_index,
            communities=self.communities,
        )

    # ---------------------------------------------------- what-if edits

    def graph_with_edits(self, edits: list[EdgeEdit], scale: float = 1.0) -> ig.Graph:
        """
        A copy of the graph with some edge weights changed/added/removed (for simulations).

        The `code_structural_scale` comes in here too, because `simulate()` hands whatever this
        returns straight to `retrieve(graph=)`: applying the scale anywhere else would be silently
        thrown away the moment a simulation also edited an edge. Simulation edits change the igraph
        PPR runs on, not the directed code relations the path tools walk.
        """
        if not edits:
            return self.graph_for_scale(scale)
        changed = {k: Edge(**vars(v)) for k, v in self.edges.items()}
        for edit in edits:
            a, b = self.idx_of.get(edit.a), self.idx_of.get(edit.b)
            if a is None or b is None or a == b:
                continue
            e = changed.setdefault((min(a, b), max(a, b)), Edge())
            e.tuned = float(edit.weight)
        return build_igraph(self.num_nodes, changed, scale)

    def graph_for_scale(self, scale: float) -> ig.Graph:
        """
        The igraph at a given `code_structural_scale`, memoised per scale on this index.

        `self.graph` is the scale-1.0 copy every ordinary search uses. Another scale needs a real
        rebuild, because `Edge.weight` is a property with no access to settings and `build_igraph`
        runs once inside `load()`. The memo lives and dies with the index, which `graph_version`
        already invalidates; a `scoped()` index gets its own.
        """
        if scale == 1.0:
            return self.graph
        cached = self._scaled.get(scale)
        if cached is None:
            cached = build_igraph(self.num_nodes, self.edges, scale)
            self._scaled[scale] = cached
        return cached


def build_igraph(num_nodes: int, edges: dict[tuple[int, int], Edge], scale: float = 1.0) -> ig.Graph:
    """
    The undirected weighted graph PPR runs on. Only pairs with a positive weight become edges, so
    `scale = 0` removes every pair that exists only because code was indexed - and with it every
    code vertex, which then has degree 0 and can neither receive nor pass activation.
    """
    pairs, weights = [], []
    for (a, b), e in edges.items():
        weight = e.weight_at(scale)
        if weight > 0:
            pairs.append((a, b))
            weights.append(weight)
    graph = ig.Graph(n=num_nodes, edges=pairs, directed=False)
    graph.es["weight"] = weights
    return graph


def _add_code_term(edge: Edge, omega: float, kind: str) -> None:
    """Fold one code relation into a pair's single code term: the best confidence, plus its name."""
    edge.omega = max(edge.omega, omega)
    if kind not in edge.code_kinds:
        edge.code_kinds.append(kind)


def _code_node(kind: str, row: dict) -> CodeNode:
    """One stored row -> the vertex. A commit shows its short sha; the rest show their name."""
    name = row.get("name") or (row.get("sha") or "")[:10]
    return CodeNode(
        id=row["id"],
        kind=kind,
        name=name,
        qualname=row.get("qualname") or "",
        code_kind=row.get("kind") or "",
        lang=row.get("lang") or "",
        path=row.get("path") or "",
        line_start=int(row.get("line_start") or 0),
        line_end=int(row.get("line_end") or 0),
        signature=row.get("signature") or "",
        doc=row.get("doc") or "",
        is_test=bool(row.get("is_test")),
        raises=list(row.get("raises") or []),
        community=row.get("community"),
        name_tokens=list(row.get("name_tokens") or []),
        dialect=row.get("dialect") or "",
        sha=row.get("sha") or "",
        author=row.get("author") or "",
        date=row.get("date") or "",
        message=row.get("message") or "",
        ordinal=int(row.get("ordinal") or 0),
        in_degree=int(row.get("in_degree") or 0),
        source_id=row.get("source_id") or "",
        source_name=row.get("source_name") or "",
    )


def _code_specificity(node: CodeNode) -> float:
    """
    The divisor that damps a code seed (S2.4). It is the denominator, never its reciprocal: storing
    `1/x` here would invert the damping and boost hub symbols instead of damping them.

    A symbol or data object is `in_degree + 1` over INVOKES/READS/WRITES only - a function called
    from everywhere is a poor seed. A commit is 1: nothing points at it.
    """
    return 1.0 if node.kind == COMMIT else float(node.in_degree + 1)


def _name_index(code_nodes: list[CodeNode]) -> dict[str, list[str]]:
    """
    Lowercase name, lowercase qualname and each split token -> the node ids they could mean.

    Built once and shared by `scoped()`, which is safe because every consumer filters its hits
    through the scoped index's `idx_of` before using them.
    """
    index: dict[str, list[str]] = {}

    def add(key: str, node_id: str) -> None:
        if key:
            ids = index.setdefault(key, [])
            if node_id not in ids:
                ids.append(node_id)

    for node in code_nodes:
        add(node.name.lower(), node.id)
        add(node.qualname.lower(), node.id)
        for token in node.name_tokens or split_identifier(node.name):
            add(token, node.id)
    return index


def _community_labels(code_nodes: list[CodeNode]) -> dict[int, str]:
    """A community's label is its lexicographically smallest member qualname, so the integers the
    Leiden pass happened to hand out never leak into anything a person reads."""
    labels: dict[int, str] = {}
    for node in code_nodes:
        if node.community is None:
            continue
        name = node.qualname or node.name
        if node.community not in labels or name < labels[node.community]:
            labels[node.community] = name
    return labels


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
