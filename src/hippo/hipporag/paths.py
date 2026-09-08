"""
Walking the code graph: paths, blast radius, exception routes, history, and how they read.

`GraphIndex` keeps two pictures of the same relations. igraph is **undirected**, because that is what
Personalized PageRank runs on and `docs/FIDELITY.md` pins that call character for character. The
directed picture lives in `code_out` / `code_in`, and this file is the only thing that walks it:
who calls whom, what a change would touch, which commits edited a function, which tests cover it.

Three rules hold for every tool here.

* **Only the relations between two code nodes are steps in a path** (`NOT_A_STEP` below).
  `DEFINED_IN` and `REFERS_TO` join a symbol to the passage it is written down in or named by -
  walking either would hop from "code" to "prose" and back, producing paths that read as nonsense.
  `MODIFIES` and `PRECEDES` belong to history, which is a side list (`history`), not a route.
* **`code_theta` filters, and it never touches PPR.** An edge below the threshold is invisible here
  and in the answer block; it still carries its weight into the graph search, where the reference's
  own `max()` rule decides what it is worth (D22).
* **A simulation's edge edits do not reach these tools.** `graph_with_edits` copies the *igraph*
  the ranking runs on; `code_out`/`code_in` are the loaded graph. Moving a slider on the Analyze
  page therefore changes a ranking without rewriting the path that explains it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from itertools import zip_longest
from typing import Any

from .graph_index import COMMIT, DATA, SYMBOL, CodeNode, DirectedEdge, GraphIndex

MAX_HOPS = 6  # shortest_code_path
PATH_HOPS = 4  # code_paths_for: what goes in the answer block
PAIRED_SEEDS = 5  # code_paths_for: how many of the seeds are searched against each other
# One traversal's ceiling. `_bfs` re-sorts `_walkable` at every vertex it visits, so an unbounded
# walk over a 20k-symbol graph is what `timing["paths"]` would spend a question on; past this many
# visited vertices the two seeds are treated as unconnected, which is what the caller shows anyway.
BFS_VISIT_BUDGET = 5000
BLAST_DEPTH = 2
BLAST_CAP = 200
MAX_BLOCK_EDGES = 60  # a hard rail; `code_triples_chars` is the real cut
EXPAND_KINDS = ("INVOKES", "OVERRIDES", "RAISES")  # what "expand" follows (WP3.3)
EXPAND_OMEGA = 0.75

# Relations that exist to attach code to prose, or to a commit: never a step in a path. Walking
# DEFINED_IN or REFERS_TO would hop out of the code graph into a passage and back; MODIFIES and
# PRECEDES belong to history, which `history()` reads directly and the block prints as `Commits:`.
NOT_A_STEP = ("DEFINED_IN", "PRECEDES", "REFERS_TO", "MODIFIES")

MORE_LINE = "… (+{n} more)"


class UnknownSymbol(LookupError):
    """No code node goes by that name in the part of the graph this caller may see."""

    def __init__(self, name: str):
        super().__init__(f"no symbol or data object called {name!r}")
        self.name = name


class AmbiguousSymbol(LookupError):
    """Several code nodes go by that name; the caller has to say which."""

    def __init__(self, name: str, candidates: list[str]):
        super().__init__(f"{name!r} could mean any of: {', '.join(candidates)}")
        self.name = name
        self.candidates = candidates


# ------------------------------------------------------------------- names


def module_of(path: str) -> str:
    """The module qualname of a file: `pyapp/orders.py` -> `pyapp.orders` (S2.6)."""
    if not path:
        return ""
    stem = path.rsplit(".", 1)[0] if "." in path.rsplit("/", 1)[-1] else path
    return stem.replace("\\", "/").replace("/", ".")


def display_of(node: CodeNode | None) -> str:
    """
    What a person reads: `pyapp.orders.OrderService.place`, `table orders`, `a1b2c3d`.

    `Symbol.qualname` is module-relative (S2.6), so a symbol's display name is its module's
    qualname joined to it. This is the form `resolve_symbol` accepts, the path tools print and the
    answer block uses.
    """
    if node is None:
        return ""
    if node.kind == COMMIT:
        return (node.sha or node.name)[:7]
    if node.kind == DATA:
        return f"{node.code_kind} {node.qualname or node.name}".strip()
    module = module_of(node.path)
    qualname = node.qualname or node.name
    if not module or qualname == module or qualname.startswith(module + "."):
        return qualname
    return f"{module}.{qualname}"


def display_at(index: GraphIndex, vertex: int) -> str:
    """Memoised on the index: `_walkable` sorts on this for two strings per edge at every vertex a
    walk visits, and `display_of` rebuilds them each time (AR1 fix 6)."""
    cached = index.display_cache.get(vertex)
    if cached is None:
        cached = display_of(index.code_node_at(vertex))
        index.display_cache[vertex] = cached
    return cached


# -------------------------------------------------------------- resolving


def resolve_symbol(index: GraphIndex, name: str) -> str:
    """
    A name a person typed -> one code node id.

    Accepts the node id itself, the fully-qualified display name
    (`pyapp.orders.OrderService.place`), the module-relative qualname (`OrderService.place`), a
    dotted suffix of either, or a bare name when only one node carries it. Raises
    `AmbiguousSymbol` (with the candidates) or `UnknownSymbol`.
    """
    wanted = (name or "").strip().strip("`")
    if not wanted:
        raise UnknownSymbol(name)
    vertex = index.idx_of.get(wanted)
    if vertex is not None and index.code_node_at(vertex) is not None:
        return wanted

    low = wanted.lower()
    exact: list[CodeNode] = []
    suffix: list[CodeNode] = []
    bare: list[CodeNode] = []
    for node in index.code_nodes:
        if index.idx_of.get(node.id) is None:
            continue
        display = display_of(node).lower()
        qualname = (node.qualname or "").lower()
        if low in (display, qualname):
            exact.append(node)
        elif display.endswith("." + low) or qualname.endswith("." + low):
            suffix.append(node)
        elif low == (node.name or "").lower():
            bare.append(node)

    for group in (exact, suffix, bare):
        if len(group) == 1:
            return group[0].id
        if len(group) > 1:
            raise AmbiguousSymbol(wanted, sorted(display_of(n) for n in group))
    raise UnknownSymbol(wanted)


# ----------------------------------------------------------------- walking


def _walkable(index: GraphIndex, edges: list[DirectedEdge], theta: float) -> list[DirectedEdge]:
    """
    The edges of one direction that a walk may take, in a backend-independent order.

    The sort is load-bearing, not cosmetic. `code_out`/`code_in` are built in whatever order
    `load_code_edges()` returned, and a graph promises none: LadybugDB and the FakeStore hand back
    insertion order, Neo4j does not. Without a sort here the same question would produce the same
    *set* of relations in a different order on a different backend, which shows up as a different
    answer block and a different tie-break in the shortest-path search.
    """
    kept = [e for e in edges if e.kind not in NOT_A_STEP and e.omega >= theta]
    return sorted(kept, key=lambda e: (e.kind, display_at(index, e.dst), display_at(index, e.src)))


def _tier(edge: DirectedEdge) -> float:
    """An edge's confidence as the block prints it, so two edges of one ω tier group together."""
    return round(float(edge.omega), 4)


def _steps(index: GraphIndex, vertex: int, *, theta: float, undirected: bool) -> list[DirectedEdge]:
    """The edges a walk may take from `vertex`, forwards (and backwards when undirected)."""
    out = _walkable(index, index.out_edges(vertex), theta)
    if undirected:
        out += _walkable(index, index.in_edges(vertex), theta)
    return out


def shortest_code_path(
    index: GraphIndex, a: int, b: int, *, theta: float, max_hops: int = MAX_HOPS
) -> list[DirectedEdge]:
    """
    The fewest relations that lead from vertex `a` to vertex `b`, or `[]`.

    Directed first - "a calls something that calls b" is the answer to "how does a reach b". If no
    directed route exists inside `max_hops`, a second undirected pass finds the shared-caller kind
    of connection ("both are called by main"), and the edges come back with their real direction, so
    a rendered line never lies about which way a call goes.
    """
    if a == b:
        return []
    for undirected in (False, True):
        found = _bfs(index, a, b, theta=theta, max_hops=max_hops, undirected=undirected)
        if found:
            return found
    return []


def _bfs(
    index: GraphIndex, a: int, b: int, *, theta: float, max_hops: int, undirected: bool
) -> list[DirectedEdge]:
    queue: deque[tuple[int, list[DirectedEdge]]] = deque([(a, [])])
    seen = {a}
    while queue and len(seen) < BFS_VISIT_BUDGET:  # a hard visit budget, not a time budget
        vertex, walked = queue.popleft()
        if len(walked) >= max_hops:
            continue
        for edge in _steps(index, vertex, theta=theta, undirected=undirected):
            other = edge.dst if edge.src == vertex else edge.src
            if other in seen:
                continue
            route = [*walked, edge]
            if other == b:
                return route
            seen.add(other)
            queue.append((other, route))
    return []


def direct_edges(index: GraphIndex, vertex: int, *, theta: float) -> list[DirectedEdge]:
    """
    Everything one hop from a vertex, both ways, **strongest first** - ω descending, and at equal
    ω the incoming edges interleaved with the outgoing ones, incoming first.

    The order used to be "out first, then in", and `code_triples_chars` cuts this list: a symbol
    with more outgoing calls than the budget fits therefore never showed a single caller, so
    "where is X called" got a block that could not answer it however confident the calling edge
    was (QA1 defect 1). Sorting by ω puts the most-confident relation of *either* direction first,
    and the in-before-out tie-break inside a tier is what keeps a resolved caller (INVOKES 0.90 in)
    ahead of the callee's own equally-confident calls (INVOKES 0.90 out).

    ω is grouped on `round(ω, 4)` - the value `triple_rows` renders - so a backend's float wobble
    cannot split one tier and give Neo4j a different interleave from LadybugDB.
    """
    incoming = _walkable(index, index.in_edges(vertex), theta)
    outgoing = _walkable(index, index.out_edges(vertex), theta)
    ordered: list[DirectedEdge] = []
    for omega in sorted({_tier(e) for e in (*incoming, *outgoing)}, reverse=True):
        both = zip_longest(
            [e for e in incoming if _tier(e) == omega], [e for e in outgoing if _tier(e) == omega]
        )
        ordered += [edge for pair in both for edge in pair if edge is not None]
    return ordered


def code_paths_for(
    index: GraphIndex,
    vertices: list[int],
    *,
    theta: float,
    max_hops: int = PATH_HOPS,
    cap: int = MAX_BLOCK_EDGES,
) -> list[DirectedEdge]:
    """
    The relations worth showing for a set of seeds: what connects them, then what touches each.

    The order is what survives `code_triples_chars`, so it is the answer's shape, not a detail:

    1. **The pairwise paths first**, in seed order - they are what connects the seeds to each other,
       and a route only reads as a route whole.
    2. **Then every seed's `direct_edges` round-robin**, one edge per seed per turn in seed (weight)
       order, so a hub seed's 40 relations cannot starve the seed ranked behind it. Within a seed
       the edges are strongest-first, both directions interleaved (see `direct_edges`).

    A relation appears once, keyed on the two **display names** and the kind - the form the block
    prints. Node ids embed the source, so a repository indexed twice would otherwise render every
    edge of the overlap twice and spend the budget saying the same thing (QA1 defect 1). This also
    collapses the same INVOKES reached both as a step on a path and as a direct edge of its caller.

    Only the first `PAIRED_SEEDS` are searched *against each other*. `vertices` arrives in weight
    order from `_explain_code`, so those are the strongest seeds; every seed still contributes its
    own direct edges. Pairing is a double BFS per pair, and two unrelated seeds are the common
    case, so all of `MAX_CODE_SEEDS` would be 190 pairs and 380 traversals on the query path -
    for a block `code_triples_chars` cuts long before that many relations reach a reader
    (AR1 fix 6).
    """
    out: list[DirectedEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def add(edge: DirectedEdge) -> None:
        key = (display_at(index, edge.src), display_at(index, edge.dst), edge.kind)
        if key not in seen:
            seen.add(key)
            out.append(edge)

    ordered = list(dict.fromkeys(vertices))
    paired = ordered[:PAIRED_SEEDS]
    for i, a in enumerate(paired):
        for b in paired[i + 1 :]:
            for edge in shortest_code_path(index, a, b, theta=theta, max_hops=max_hops):
                add(edge)
    for turn in zip_longest(*(direct_edges(index, v, theta=theta) for v in ordered)):
        for edge in turn:
            if edge is not None:
                add(edge)
    return out[:cap]


def expand_from(
    index: GraphIndex, vertices: list[int], *, limit: int, omega: float = EXPAND_OMEGA
) -> list[DirectedEdge]:
    """One-hop INVOKES/OVERRIDES/RAISES neighbours of some symbols - what "expand" fetches (S2.14)."""
    out: list[DirectedEdge] = []
    seen: set[int] = set(vertices)
    for vertex in vertices:
        for edge in _walkable(index, index.out_edges(vertex), 0.0):
            if edge.kind in EXPAND_KINDS and edge.omega >= omega and edge.dst not in seen:
                seen.add(edge.dst)
                out.append(edge)
                if len(out) >= limit:
                    return out
    return out


@dataclass
class BlastRadius:
    """Who would feel a change to `vertex`, one list per level out."""

    vertex: int
    levels: list[list[int]] = field(default_factory=list)
    truncated: bool = False

    @property
    def vertices(self) -> list[int]:
        return [v for level in self.levels for v in level]


def blast_radius(
    index: GraphIndex, vertex: int, *, theta: float, depth: int = BLAST_DEPTH, cap: int = BLAST_CAP
) -> BlastRadius:
    """
    What a change here could break: the callers, then their callers, `depth` levels out.

    Direction matters - this walks `code_in`, so it answers "who depends on this", not "what does
    this depend on". `truncated` says the cap stopped it, which is a real answer for a hub symbol.
    """
    levels: list[list[int]] = []
    seen = {vertex}
    frontier = [vertex]
    truncated = False
    for _ in range(max(0, depth)):
        found: list[int] = []
        for current in frontier:
            for edge in _walkable(index, index.in_edges(current), theta):
                if edge.src in seen:
                    continue
                if len(seen) >= cap:
                    truncated = True
                    break
                seen.add(edge.src)
                found.append(edge.src)
            if truncated:
                break
        if not found:
            break
        levels.append(found)
        frontier = found
        if truncated:
            break
    return BlastRadius(vertex=vertex, levels=levels, truncated=truncated)


def render_blast(index: GraphIndex, blast: BlastRadius) -> list[str]:
    """One line per level, then the affected symbols grouped by subsystem (D11's second surface)."""
    lines = [
        f"Level {i}: " + ", ".join(sorted(display_at(index, v) for v in level))
        for i, level in enumerate(blast.levels, start=1)
    ]
    lines += _subsystem_lines(index, blast.vertices)
    if blast.truncated:
        lines.append("… (truncated)")
    return lines


def exception_path(
    index: GraphIndex, vertex: int, exception_name: str, *, theta: float, depth: int = PATH_HOPS
) -> list[DirectedEdge]:
    """How this function reaches that exception: `save -[RAISES]-> OrderError`, or the calls first."""
    target = index.idx_of.get(resolve_symbol(index, exception_name))
    if target is None:
        return []
    return shortest_code_path(index, vertex, target, theta=theta, max_hops=depth)


def history(index: GraphIndex, vertex: int, *, limit: int = 3) -> list[CodeNode]:
    """The commits that touched this symbol, newest first (`Commit.ordinal`, 0 = newest)."""
    commits = []
    for edge in index.in_edges(vertex):
        if edge.kind != "MODIFIES":
            continue
        node = index.code_node_at(edge.src)
        if node is not None and node.kind == COMMIT:
            commits.append(node)
    commits.sort(key=lambda c: (c.ordinal, c.sha))
    return commits[:limit]


def tests_for(index: GraphIndex, vertices: list[int], *, theta: float) -> list[CodeNode]:
    """The test symbols a set of seeds is TESTED_BY, in seed order, each once."""
    out: list[CodeNode] = []
    seen: set[str] = set()
    for vertex in vertices:
        for edge in _walkable(index, index.out_edges(vertex), theta):
            if edge.kind != "TESTED_BY":
                continue
            node = index.code_node_at(edge.dst)
            if node is not None and node.id not in seen:
                seen.add(node.id)
                out.append(node)
    return out


# ------------------------------------------------------- rows for the trace
# Everything the trace carries is a plain dict, so `trace_from_dict` needs no new class and an
# eval's stored trace can still be re-answered years later (R3 gotcha 8).


def triple_rows(index: GraphIndex, edges: list[DirectedEdge]) -> list[dict[str, Any]]:
    return [
        {
            "a": index.node_ids[e.src],
            "b": index.node_ids[e.dst],
            "a_name": display_at(index, e.src),
            "b_name": display_at(index, e.dst),
            "kind": e.kind,
            "omega": round(float(e.omega), 4),
            "provenance": e.provenance,
            "in_branch": bool((e.extra or {}).get("in_branch")),
            "is_await": bool((e.extra or {}).get("is_await")),
            "call_line": int((e.extra or {}).get("call_line") or 0),
        }
        for e in edges
    ]


def test_rows(index: GraphIndex, nodes: list[CodeNode]) -> list[dict[str, Any]]:
    return [{"id": n.id, "name": display_of(n), "path": n.path} for n in nodes]


def history_rows(nodes: list[CodeNode]) -> list[dict[str, Any]]:
    return [
        {
            "id": n.id,
            "sha": n.sha,
            "date": (n.date or "")[:10],
            "subject": (n.message or "").splitlines()[0] if n.message else "",
        }
        for n in nodes
    ]


# ---------------------------------------------------------------- rendering


def render_triples(rows: list[dict[str, Any]]) -> list[str]:
    """S2.15's fixed grammar, one line per relation. Not free text: `test_ask.py` pins it exactly."""
    lines = []
    for row in rows:
        flags = ""
        if row.get("in_branch"):
            flags += " in_branch"
        if row.get("is_await"):
            flags += " await"
        lines.append(
            f"{row['a_name']} -[{row['kind']} {float(row['omega']):.2f} "
            f"{row.get('provenance', '')}{flags}]-> {row['b_name']}"
        )
    return lines


def community_labels(index: GraphIndex) -> dict[int, str]:
    """
    Each community's label: the lexicographically smallest **display** name among its members.

    `GraphIndex.community_name` uses the smallest *qualname*, which is module-relative by S2.6 - so
    a repository with `pyapp/store.py`'s `Base` and `tsapp/models/base.ts`'s `Base` gets two
    different subsystems both labelled "Base", and the block says nothing. The display name is the
    form S2.6 makes unique, and it is what a person reads everywhere else here.
    """
    labels: dict[int, str] = {}
    for node in index.code_nodes:
        if node.community is None:
            continue
        name = display_of(node)
        if node.community not in labels or name < labels[node.community]:
            labels[node.community] = name
    return labels


def _subsystem_lines(index: GraphIndex, vertices: list[int]) -> list[str]:
    """One `Subsystems:` line per community present among these vertices (Ruling 4)."""
    groups: dict[int, list[str]] = {}
    for vertex in vertices:
        community = index.community_of(vertex)
        if community is None:
            continue
        name = display_at(index, vertex)
        if name and name not in groups.setdefault(community, []):
            groups[community].append(name)
    labels = community_labels(index) if groups else {}
    lines = []
    for community in sorted(groups):
        label = labels.get(community) or index.community_name(community) or str(community)
        lines.append(f"Subsystems: {label}: " + ", ".join(sorted(groups[community])))
    return lines


def block_lines(index: GraphIndex, trace: Any) -> list[str]:
    """The body of the Code graph block, before the `code_triples_chars` cut."""
    lines = render_triples(list(trace.paths))
    lines += [f"Tests: {row['name']}" for row in trace.tests]
    lines += [f"Commits: {row['sha'][:7]} {row['date']} {row['subject']}".rstrip() for row in trace.history]
    vertices: list[int] = []
    for row in trace.paths:
        for key in ("a", "b"):
            vertex = index.idx_of.get(row.get(key))
            if vertex is not None and index.node_kind[vertex] in (SYMBOL, DATA):
                vertices.append(vertex)
    lines += _subsystem_lines(index, vertices)
    return lines


def cut_to(lines: list[str], max_chars: int) -> list[str]:
    """
    Keep whole lines up to `max_chars`, then say how many were dropped.

    A cut in the middle of a line would produce a relation that reads as true and is not, so the
    cut is always on a line boundary - even when that means keeping nothing at all.
    """
    if max_chars <= 0:
        return [MORE_LINE.format(n=len(lines))] if lines else []
    kept: list[str] = []
    used = 0
    for line in lines:
        cost = len(line) + (1 if kept else 0)
        if used + cost > max_chars:
            break
        kept.append(line)
        used += cost
    if len(kept) < len(lines):
        kept.append(MORE_LINE.format(n=len(lines) - len(kept)))
    return kept


def render_block(index: GraphIndex, trace: Any, *, header: str, max_chars: int) -> str:
    """
    The `Title: Code graph` pseudo-passage's text: a legend, then the triples, tests, commits and
    subsystems of S2.15, cut on a line boundary at `code_triples_chars`.

    The header is outside the budget. It is the legend that tells the model what `INVOKES 0.90`
    means, so a small `code_triples_chars` should shrink the evidence, not turn it into noise.
    """
    lines = cut_to(block_lines(index, trace), max_chars)
    if not lines:
        return ""
    return "\n".join([header, *lines])


__all__ = [
    "AmbiguousSymbol",
    "BlastRadius",
    "UnknownSymbol",
    "blast_radius",
    "block_lines",
    "code_paths_for",
    "community_labels",
    "cut_to",
    "direct_edges",
    "display_at",
    "display_of",
    "exception_path",
    "expand_from",
    "history",
    "history_rows",
    "module_of",
    "render_blast",
    "render_block",
    "render_triples",
    "resolve_symbol",
    "shortest_code_path",
    "test_rows",
    "tests_for",
    "triple_rows",
]
