"""
The shapes the code graph is made of, and the ids that name them.

Three kinds of node: a `Symbol` (a module, class, function or method), a `DataObject`
(a table, column, collection, graph label or relationship type the code talks to) and
-- from WP2b -- a commit. `CodeEdge` is one typed, weighted relation between two of
them. `CodeGraph` is everything one source produced.

Ids are computed here and nowhere else; the store is handed ids, it never derives them.
They are `make_id` prefixed md5s, so `symbol-`/`data-`/`commit-` are disjoint from the
`entity-`/`fact-`/`passage-` namespaces `hipporag.text` already uses (D4, S2.2).

This module imports stdlib and `hipporag.text` only -- `ingest.chunker` imports it, and
`ingest` may not pull tree-sitter in just to build a chunk.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..hipporag.text import make_id, split_identifier

# --------------------------------------------------------------- budgets
#
# Safety rails, not tuning knobs -- the same class as `MAX_CHUNKS` and `MAX_FILE_BYTES`,
# which are module constants today. The three *tunable* history budgets are settings
# instead (`code_history_depth`, `code_git_timeout_s`, `code_history_total_s`); see
# PLAN.md 2.2c, the one place any budget is spelled.

CODE_MAX_FILES = 5_000  # files parsed per source; past it, extraction stops
CODE_MAX_FILE_BYTES = 512 * 1024  # above this a file keeps today's line windows, unparsed
CODE_MAX_SYMBOLS_PER_SOURCE = 50_000  # past it extraction stops and `stats()["truncated"]` is True

# Every edge kind the extractor can emit, in the order the ω table lists them.
CODE_EDGE_KINDS = (
    "CONTAINS",
    "IMPORTS",
    "INHERITS",
    "OVERRIDES",
    "INVOKES",
    "RAISES",
    "CATCHES",
    "TESTED_BY",
    "READS",
    "WRITES",
)
SYMBOL_KINDS = ("module", "class", "function", "method")
DATA_KINDS = ("table", "column", "collection", "label", "rel_type")

# Why a file was not parsed. `stats()["files_skipped"]` counts by these keys.
SKIP_REASONS = ("too_big", "unsupported", "parse_error")

# Suffix -> language. `ingest.readers.lang_of` is the same table on the ingest side of the
# dependency line (codegraph may not import ingest); `test_ingest_readers.py` pins them equal.
LANG_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".mjs": "typescript",
    ".cjs": "typescript",
    ".sql": "sql",
}

ARG_BINDING_MAX_CHARS = 60  # an argument expression longer than this is truncated in `extra`


# ------------------------------------------------------------------- ids


def symbol_id(source_id: str, path: str, qualname: str) -> str:
    """Id of a symbol. Namespaced by source *and path*, so two same-named symbols in
    different files do not collide (D4)."""
    return make_id("symbol-", f"{source_id}:{path}:{qualname}")


def data_id(source_id: str, kind: str, qualname: str) -> str:
    """Id of a data object. Keyed on kind too: a table `orders` and a label `orders` differ."""
    return make_id("data-", f"{source_id}:{kind}:{qualname}")


def commit_id(source_id: str, sha: str) -> str:
    """Id of a commit node (written by WP2b's git history pass)."""
    return make_id("commit-", f"{source_id}:{sha}")


def lang_of(name: str) -> str | None:
    """ "python", "typescript", "sql" or None, from a file name's suffix alone."""
    _, _, tail = name.replace("\\", "/").rpartition("/")
    suffix = f".{tail.rsplit('.', 1)[1]}".lower() if "." in tail else ""
    return LANG_BY_SUFFIX.get(suffix)


def name_text(name: str) -> str:
    """
    The text we embed for a symbol or data object (D7: name only, no signature).

    The split tokens come first so that a prose entity reaches the identifier:
    `name_text("OrderService") == "order service OrderService"`, which is what makes the
    entity `order service` a synonym of the symbol. A name that is already one plain word
    is returned unchanged rather than doubled.
    """
    tokens = " ".join(split_identifier(name))
    return name if tokens == name else f"{tokens} {name}".strip()


# ----------------------------------------------------------------- nodes


@dataclass
class Symbol:
    """
    One module, class, function or method.

    The first block of fields is exactly the store row (`add_symbols`, WP1.3). The rest is
    what the chunker needs and the store never sees: `display` for passage titles and the
    context block, `header_end` for the module/class header passage, and `statement_lines`
    for splitting an oversized body at a statement boundary rather than mid-expression.
    """

    id: str = ""
    source_id: str = ""
    name: str = ""
    qualname: str = ""  # module-relative: `OrderService.place`; a module's is its own path form
    kind: str = "function"
    lang: str = "python"
    path: str = ""  # repo-relative, as `Document.title` carries it
    line_start: int = 0
    line_end: int = 0
    signature: str = ""
    doc: str = ""
    is_test: bool = False
    raises: list[str] = field(default_factory=list)  # builtin/unresolved exception names, no edge
    # ---- not stored on the node; the chunker's and resolver's half of the contract
    params: list[str] = field(default_factory=list)  # parameter names, for the INVOKES arg_binding
    module: str = ""  # qualname of the module this lives in
    display: str = ""  # f"{module}.{qualname}"; a module's display is its own qualname
    header_end: int = 0  # last line of the header passage (module/class: before the first member)
    statement_lines: list[int] = field(default_factory=list)  # start lines of the body's statements

    def row(self) -> dict:
        """
        Exactly what `store.add_symbols` takes, and nothing else. The five fields below the
        line above are the chunker's and the resolver's; the store has no columns for them,
        so the indexer writes `symbol.row()` rather than `asdict(symbol)`. `embedding` is
        the indexer's to add -- it is the one field only Ollama can fill.
        """
        return {
            "id": self.id,
            "source_id": self.source_id,
            "name": self.name,
            "qualname": self.qualname,
            "kind": self.kind,
            "lang": self.lang,
            "path": self.path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "signature": self.signature,
            "doc": self.doc,
            "is_test": self.is_test,
            "raises": list(self.raises),
        }


@dataclass
class DataObject:
    """
    A table, column, collection, graph label or relationship type named by the code.

    Deduped across every site that names it -- a `CREATE TABLE orders`, a `FROM orders`
    literal and a `__tablename__ = "orders"` are one node. `mentions` keeps *every* site,
    not just the first: S2.5 gives a data object a DEFINED_IN edge from every passage whose
    literal names it, so a table named in ten files does not vanish when one is hidden.
    """

    id: str = ""
    source_id: str = ""
    name: str = ""
    qualname: str = ""  # `orders`, or `orders.id` for a column
    kind: str = "table"
    dialect: str = ""  # `sql`, `mongo`, `cypher`
    mentions: list[tuple[str, int]] = field(default_factory=list)  # (path, line), sorted, unique

    def row(self) -> dict:
        """What `store.add_data_objects` takes. `mentions` is not stored: it is how the
        indexer knows which passages get a DEFINED_IN edge to this node (S2.5)."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "name": self.name,
            "qualname": self.qualname,
            "kind": self.kind,
            "dialect": self.dialect,
        }


@dataclass
class CodeEdge:
    """
    One directed relation between two code nodes.

    Named apart from `GraphIndex.DirectedEdge`, which is the same relation once it has been
    loaded back out of the store. `extra` is free-form JSON: INVOKES carries
    `{call_line, in_branch, is_await, arg_binding}` and, only when a pair has more than one
    call site, `call_lines` listing the rest.
    """

    a: str = ""
    b: str = ""
    kind: str = "INVOKES"
    omega: float = 0.0
    provenance: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.a, self.b, self.kind)


def merge_edges(edges: list[CodeEdge]) -> list[CodeEdge]:
    """
    One edge per `(a, b, kind)`: keep the highest ω (and its provenance), the first call
    line, and list any further call lines in `extra["call_lines"]`. Self-loops are dropped.
    Order is the order each pair was first seen, so two runs give the same list.
    """
    merged: dict[tuple[str, str, str], CodeEdge] = {}
    for edge in edges:
        if edge.a == edge.b or not edge.a or not edge.b:
            continue
        seen = merged.get(edge.key)
        if seen is None:
            merged[edge.key] = CodeEdge(
                a=edge.a, b=edge.b, kind=edge.kind, omega=edge.omega,
                provenance=edge.provenance, extra=dict(edge.extra),
            )  # fmt: skip
            continue
        line = edge.extra.get("call_line")
        if line is not None:
            lines = [seen.extra["call_line"], *seen.extra.get("call_lines", [])]
            if line not in lines:
                seen.extra["call_lines"] = sorted({*lines[1:], line})
        if edge.omega > seen.omega:
            first, rest = seen.extra.get("call_line"), seen.extra.get("call_lines")
            seen.omega = edge.omega
            seen.provenance = edge.provenance
            seen.extra = dict(edge.extra)
            if first is not None:  # the higher-ω site is not necessarily the first one
                seen.extra["call_line"] = first
                if rest:
                    seen.extra["call_lines"] = rest
    return list(merged.values())


# ------------------------------------------------- what a walker reports
#
# Pass 1 (`python.walk` / `typescript.walk`) turns one file into `FileFacts`: its symbols,
# plus every *unresolved* thing its bodies do. Pass 2 (`resolve.py`) needs the whole source
# before it can say what `invoice(order)` or `class Order extends Base` points at.


@dataclass
class ImportFact:
    """One imported name. `module` is as written -- `os`, `.billing`, `./base`."""

    module: str = ""
    name: str = ""  # the member imported from it; "" for a whole-module import
    alias: str = ""  # the local binding
    line: int = 0
    level: int = 0  # python relative-import dots (`from . import x` is 1)
    is_wildcard: bool = False
    is_default: bool = False  # TS `import x from "./b"` / `export default`


@dataclass
class CallFact:
    """One call site, with the enclosing symbol and enough context for INVOKES `extra`."""

    caller: str = ""  # qualname of the enclosing symbol
    receiver: str = ""  # "" for a bare call; else `self`, `billing`, `os.path`, `super`
    name: str = ""
    line: int = 0
    in_branch: bool = False
    is_await: bool = False
    is_new: bool = False  # TS `new X()`
    args: list[str] = field(default_factory=list)
    kwargs: dict[str, str] = field(default_factory=dict)


@dataclass
class BaseFact:
    """`class OrderService(Base)` / `class Order extends Base`."""

    cls: str = ""
    base: str = ""
    line: int = 0


@dataclass
class RaiseFact:
    """A `raise X` / `throw new X` (kind `raise`) or an `except X` / `instanceof X` (kind `catch`)."""

    caller: str = ""
    name: str = ""
    line: int = 0
    kind: str = "raise"


@dataclass
class AssignFact:
    """`service = OrderService()` -- what a later `service.place()` has to go through."""

    scope: str = ""  # enclosing symbol qualname
    target: str = ""
    value: str = ""  # the constructed name, `OrderService`
    line: int = 0


@dataclass
class LiteralFact:
    """A string literal, with the symbol that holds it. `data_access` classifies these."""

    caller: str = ""
    text: str = ""
    line: int = 0


@dataclass
class FileFacts:
    """Everything pass 1 saw in one file."""

    path: str = ""
    lang: str = "python"
    module: str = ""  # the module symbol's qualname
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportFact] = field(default_factory=list)
    calls: list[CallFact] = field(default_factory=list)
    bases: list[BaseFact] = field(default_factory=list)
    exceptions: list[RaiseFact] = field(default_factory=list)
    assignments: list[AssignFact] = field(default_factory=list)
    literals: list[LiteralFact] = field(default_factory=list)
    table_names: list[tuple[str, str, int]] = field(default_factory=list)  # (class qualname, name, line)
    models: list[tuple[str, str, int]] = field(default_factory=list)  # mongoose (binding, collection, line)
    names: dict[str, list[int]] = field(default_factory=dict)  # bare identifier -> lines (TESTED_BY)
    reexports: list[ImportFact] = field(default_factory=list)  # TS `export ... from "./x"`
    default_export: str = ""  # TS `export default class X` -> "X"


@dataclass
class FileGraph:
    """What pass 2 resolved for one file."""

    path: str = ""
    symbols: list[Symbol] = field(default_factory=list)
    data_objects: list[DataObject] = field(default_factory=list)
    edges: list[CodeEdge] = field(default_factory=list)
    unresolved_calls: int = 0


# ----------------------------------------------------------- the graph


@dataclass
class CodeGraph:
    """
    One source's code graph. `extract_code` returns exactly this, the chunker reads
    `symbols`, the indexer writes all of it, and `stats()` becomes `Source.meta["code"]`.
    """

    source_id: str = ""
    symbols: list[Symbol] = field(default_factory=list)
    data_objects: list[DataObject] = field(default_factory=list)
    edges: list[CodeEdge] = field(default_factory=list)
    files_parsed: list[str] = field(default_factory=list)
    files_skipped: dict[str, str] = field(default_factory=dict)  # path -> one of SKIP_REASONS
    unresolved_calls: dict[str, int] = field(default_factory=dict)  # path -> count (D15)
    truncated: bool = False
    # ---- the git history, filled by `codegraph.git_history.read_history` and by nothing else.
    # A source with no repository behind it simply keeps the empty lists, and the indexer writes
    # nothing. Rows are already in the shapes `add_commits` / `add_modifies` / `add_precedes` take.
    commits: list[dict] = field(default_factory=list)
    modifies: list[dict] = field(default_factory=list)
    precedes: list[tuple[str, str]] = field(default_factory=list)
    history_skipped: int = 0  # commits a budget cost us; 0 means "the history is all here"

    def by_path(self, path: str) -> list[Symbol]:
        """The symbols of one file, in source order. What the chunker asks for."""
        return [s for s in self.symbols if s.path == path]

    def parsed(self, path: str) -> bool:
        """True when this file has a symbol tree, so the chunker may split it by symbol."""
        return path in self.files_parsed

    def symbol_by_id(self, node_id: str) -> Symbol | None:
        return next((s for s in self.symbols if s.id == node_id), None)

    def stats(self) -> dict:
        """
        The counts that become `Source.meta["code"]`. JSON-safe and deterministic: every
        dict is built in sorted key order, so two runs over the same tree compare equal.
        """
        by_kind: dict[str, int] = {}
        for edge in self.edges:
            by_kind[edge.kind] = by_kind.get(edge.kind, 0) + 1
        skipped = dict.fromkeys(SKIP_REASONS, 0)
        for reason in self.files_skipped.values():
            skipped[reason] = skipped.get(reason, 0) + 1
        return {
            "symbols": len(self.symbols),
            "languages": sorted({s.lang for s in self.symbols}),
            "data_objects": len(self.data_objects),
            "edges": len(self.edges),
            "edges_by_kind": {k: by_kind[k] for k in sorted(by_kind)},
            "files_parsed": len(self.files_parsed),
            "files_skipped": {k: skipped[k] for k in sorted(skipped)},
            "unresolved_calls": {p: self.unresolved_calls[p] for p in sorted(self.unresolved_calls)},
            "unresolved_calls_total": sum(self.unresolved_calls.values()),
            "truncated": self.truncated,
            "commits": len(self.commits),
            "modifies": len(self.modifies),
            "history_skipped": self.history_skipped,
        }
