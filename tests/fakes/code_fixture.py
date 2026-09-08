"""
The code graph of `tests/fixtures/code_sample/` (PLAN.md "Test fixture plan"), written by hand.

WP2 builds that tree and the extractor that reads it; WP2i wires the extractor into indexing and
ships the `code_index` fixture. Until both have landed, WP3 needs *something* code-shaped to retrieve
over, so this module writes the same graph straight through the store's own methods - the symbols,
data objects, commits and edges the extractor is specified to produce for that tree, with the ids
`codegraph.model` will compute (`make_id("symbol-", f"{source_id}:{path}:{qualname}")`, D4).

It is deliberately a *fake*, not a fixture file: when the real `code_index` arrives, tests that only
needed "an index with code in it" move over to it, and the ones that need a case the tree cannot
express (an eleven-way ambiguous name, say) keep building their graph here.

    source_id = build_code_source(store, ollama)      # passages + the whole code graph
    index = GraphIndex.load(store)
    place = index.idx_of[symbol_id(source_id, "pyapp/orders.py", "OrderService.place")]

Names follow S2.6: `Symbol.qualname` is module-relative (`OrderService.place`) and the display name
is `f"{module_qualname}.{qualname}"` (`pyapp.orders.OrderService.place`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hippo.hipporag.indexer import Chunk, index_source, passage_id
from hippo.hipporag.text import entity_id, make_id

# --------------------------------------------------------------------- ids


def symbol_id(source_id: str, path: str, qualname: str) -> str:
    return make_id("symbol-", f"{source_id}:{path}:{qualname}")


def data_id(source_id: str, kind: str, qualname: str) -> str:
    return make_id("data-", f"{source_id}:{kind}:{qualname}")


def commit_id(source_id: str, sha: str) -> str:
    return make_id("commit-", f"{source_id}:{sha}")


# ----------------------------------------------------------------- the tree


@dataclass
class SymbolSpec:
    path: str
    qualname: str  # module-relative, per S2.6
    kind: str
    name: str
    line_start: int
    line_end: int
    text: str  # the passage this symbol is defined in
    signature: str = ""
    doc: str = ""
    is_test: bool = False
    raises: list[str] = field(default_factory=list)
    community: int | None = None

    @property
    def module(self) -> str:
        """The module qualname this symbol lives in: the path with `/` -> `.`, extension dropped."""
        return self.path.rsplit(".", 1)[0].replace("/", ".")

    @property
    def display(self) -> str:
        """The fully-qualified display name (S2.6). A module's is its own qualname."""
        return self.qualname if self.kind == "module" else f"{self.module}.{self.qualname}"

    @property
    def title(self) -> str:
        return f"{self.path} :: {self.display} (lines {self.line_start}-{self.line_end})"


@dataclass
class DataSpec:
    kind: str
    qualname: str
    name: str
    dialect: str
    defined_in: list[str]  # display names of the symbols whose passages name it


# Communities: 0 = orders/cli, 1 = billing, 2 = store, 3 = tests. Leiden would find something like
# this on the file projection; the numbers here are already S2.10-canonical (smallest qualname wins).
SYMBOLS: list[SymbolSpec] = [
    SymbolSpec(
        "pyapp/__init__.py",
        "pyapp.__init__",
        "module",
        "__init__",
        1,
        3,
        '"""The pyapp package."""\nfrom .orders import OrderService\n__all__ = ["OrderService"]',
        doc="The pyapp package.",
        community=0,
    ),
    SymbolSpec(
        "pyapp/store.py",
        "pyapp.store",
        "module",
        "store",
        1,
        7,
        "class Base:\nclass OrderError(Exception): pass",
        community=2,
    ),
    SymbolSpec(
        "pyapp/store.py",
        "Base",
        "class",
        "Base",
        1,
        5,
        'class Base:\n    """A tiny base class."""\n    def log(self, msg): ...',
        signature="Base",
        doc="A tiny base class.",
        community=2,
    ),
    SymbolSpec(
        "pyapp/store.py",
        "Base.log",
        "method",
        "log",
        4,
        5,
        "    def log(self, msg):\n        return msg",
        signature="log(self, msg)",
        community=2,
    ),
    SymbolSpec(
        "pyapp/store.py",
        "OrderError",
        "class",
        "OrderError",
        7,
        7,
        "class OrderError(Exception): pass",
        signature="OrderError",
        community=2,
    ),
    SymbolSpec(
        "pyapp/billing.py",
        "pyapp.billing",
        "module",
        "billing",
        1,
        9,
        '"""Billing helpers."""\ndef total(order): ...\ndef send_invoice(order): ...',
        doc="Billing helpers.",
        community=1,
    ),
    SymbolSpec(
        "pyapp/billing.py",
        "total",
        "function",
        "total",
        4,
        5,
        '    def total(order):\n        return sum(order["lines"])',
        signature="total(order)",
        community=1,
    ),
    SymbolSpec(
        "pyapp/billing.py",
        "send_invoice",
        "function",
        "send_invoice",
        8,
        9,
        '    def send_invoice(order):\n        print("sending", order["id"])',
        signature="send_invoice(order)",
        community=1,
    ),
    SymbolSpec(
        "pyapp/orders.py",
        "pyapp.orders",
        "module",
        "orders",
        1,
        7,
        "import os\nfrom . import billing\nfrom .billing import send_invoice as invoice\n"
        'from pyapp.store import Base, OrderError\n\nDEFAULT_STATUS = "open"',
        community=0,
    ),
    SymbolSpec(
        "pyapp/orders.py",
        "OrderService",
        "class",
        "OrderService",
        9,
        14,
        "class OrderService(Base):\n"
        '    """Keeps orders. Acme Robotics is headquartered in Boulder. '
        "Priya Natarajan lives in Boulder.\n\n"
        '    Second paragraph, not part of the first."""\n\n'
        '    __tablename__ = "orders"',
        signature="OrderService(Base)",
        doc="Keeps orders. Acme Robotics is headquartered in Boulder. Priya Natarajan lives in Boulder.",
        community=0,
    ),
    SymbolSpec(
        "pyapp/orders.py",
        "OrderService.place",
        "method",
        "place",
        16,
        23,
        "    def place(self, order):\n"
        '        """Place an order: total it with billing, send the invoice and log the path."""\n'
        "        amount = billing.total(order)\n"
        "        try: invoice(order)\n"
        '        except OrderError: raise ValueError("bad order")\n'
        '        self.log(os.path.join("a", "b"))\n'
        "        print(amount)\n"
        "        return amount",
        signature="place(self, order)",
        doc="Place an order: total it with billing, send the invoice and log the path.",
        raises=["ValueError"],
        community=0,
    ),
    SymbolSpec(
        "pyapp/orders.py",
        "OrderService.log",
        "method",
        "log",
        25,
        25,
        "    def log(self, msg): return msg",
        signature="log(self, msg)",
        community=0,
    ),
    SymbolSpec(
        "pyapp/orders.py",
        "OrderService.list_open",
        "method",
        "list_open",
        27,
        28,
        "    def list_open(self):\n"
        "        return self.run(\"SELECT id, total FROM orders WHERE status = 'open'\")",
        signature="list_open(self)",
        community=0,
    ),
    SymbolSpec(
        "pyapp/orders.py",
        "OrderService.save",
        "method",
        "save",
        30,
        32,
        "    def save(self, order):\n"
        '        self.run("INSERT INTO orders (id, total) VALUES (?, ?)")\n'
        '        raise OrderError("nope")',
        signature="save(self, order)",
        community=0,
    ),
    SymbolSpec(
        "pyapp/orders.py",
        "OrderService.archive",
        "method",
        "archive",
        34,
        35,
        "    def archive(self, order):\n        db.archive_orders.insert_one(order)",
        signature="archive(self, order)",
        community=0,
    ),
    SymbolSpec(
        "pyapp/orders.py",
        "OrderService.graph",
        "method",
        "graph",
        37,
        38,
        "    def graph(self, order):\n"
        '        session.run("MATCH (o:Order)-[:PLACED_BY]->(c:Customer) RETURN c")',
        signature="graph(self, order)",
        community=0,
    ),
    SymbolSpec(
        "pyapp/orders.py",
        "OrderService.run",
        "method",
        "run",
        40,
        40,
        "    def run(self, sql): return sql",
        signature="run(self, sql)",
        community=0,
    ),
    SymbolSpec(
        "pyapp/cli.py",
        "pyapp.cli",
        "module",
        "cli",
        1,
        2,
        "from pyapp import OrderService",
        community=0,
    ),
    SymbolSpec(
        "pyapp/cli.py",
        "main",
        "function",
        "main",
        4,
        6,
        '    def main():\n        service = OrderService()\n        service.place({"id": 1, "lines": [1]})',
        signature="main()",
        community=0,
    ),
    SymbolSpec(
        "tests/test_orders.py",
        "tests.test_orders",
        "module",
        "test_orders",
        1,
        2,
        "from pyapp.orders import OrderService",
        community=3,
    ),
    SymbolSpec(
        "tests/test_orders.py",
        "test_place",
        "function",
        "test_place",
        4,
        4,
        '    def test_place(): assert OrderService().place({"id": 1, "lines": [1]}) == 1',
        signature="test_place()",
        is_test=True,
        community=3,
    ),
]

DATA_OBJECTS: list[DataSpec] = [
    DataSpec(
        "table",
        "orders",
        "orders",
        "sql",
        ["pyapp.orders.OrderService.list_open", "pyapp.orders.OrderService.save"],
    ),
    DataSpec("column", "orders.id", "id", "sql", ["pyapp.orders.OrderService.list_open"]),
    DataSpec("table", "customers", "customers", "sql", []),
    DataSpec(
        "collection", "archive_orders", "archive_orders", "mongo", ["pyapp.orders.OrderService.archive"]
    ),
    DataSpec("label", "Order", "Order", "cypher", ["pyapp.orders.OrderService.graph"]),
]

# (from display name, to display name, kind, omega, provenance, extra). Straight from PLAN 2.6.
EDGES: list[tuple[str, str, str, float, str, dict]] = [
    ("pyapp.orders", "pyapp.orders.OrderService", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.orders.OrderService", "pyapp.orders.OrderService.place", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.orders.OrderService", "pyapp.orders.OrderService.log", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.orders.OrderService", "pyapp.orders.OrderService.list_open", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.orders.OrderService", "pyapp.orders.OrderService.save", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.orders.OrderService", "pyapp.orders.OrderService.archive", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.orders.OrderService", "pyapp.orders.OrderService.graph", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.orders.OrderService", "pyapp.orders.OrderService.run", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.billing", "pyapp.billing.total", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.billing", "pyapp.billing.send_invoice", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.store", "pyapp.store.Base", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.store.Base", "pyapp.store.Base.log", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.store", "pyapp.store.OrderError", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.cli", "pyapp.cli.main", "CONTAINS", 1.00, "syntax", {}),
    ("tests.test_orders", "tests.test_orders.test_place", "CONTAINS", 1.00, "syntax", {}),
    ("pyapp.orders", "pyapp.billing", "IMPORTS", 0.95, "import_path", {}),
    ("pyapp.orders", "pyapp.store.Base", "IMPORTS", 0.95, "import_path", {}),
    ("pyapp.cli", "pyapp.orders.OrderService", "IMPORTS", 0.90, "reexport", {}),
    ("tests.test_orders", "pyapp.orders.OrderService", "IMPORTS", 0.95, "import_path", {}),
    ("pyapp.orders.OrderService", "pyapp.store.Base", "INHERITS", 0.90, "resolved", {}),
    ("pyapp.orders.OrderService.log", "pyapp.store.Base.log", "OVERRIDES", 0.90, "mro", {}),
    (
        "pyapp.orders.OrderService.place",
        "pyapp.billing.total",
        "INVOKES",
        0.90,
        "via_import",
        {"call_line": 18, "in_branch": False, "is_await": False, "arg_binding": {"order": "order"}},
    ),
    (
        "pyapp.orders.OrderService.place",
        "pyapp.billing.send_invoice",
        "INVOKES",
        0.90,
        "via_import",
        {"call_line": 19, "in_branch": True, "is_await": False, "arg_binding": {"order": "order"}},
    ),
    (
        "pyapp.orders.OrderService.place",
        "pyapp.store.Base.log",
        "INVOKES",
        0.90,
        "via_inheritance",
        {"call_line": 21, "in_branch": False, "is_await": False, "arg_binding": {}},
    ),
    (
        "pyapp.orders.OrderService.list_open",
        "pyapp.orders.OrderService.run",
        "INVOKES",
        1.00,
        "same_file",
        {"call_line": 28, "in_branch": False, "is_await": False, "arg_binding": {"sql": '"SELECT id, ..."'}},
    ),
    (
        "pyapp.orders.OrderService.save",
        "pyapp.orders.OrderService.run",
        "INVOKES",
        1.00,
        "same_file",
        {"call_line": 31, "in_branch": False, "is_await": False, "arg_binding": {}},
    ),
    (
        "pyapp.cli.main",
        "pyapp.orders.OrderService.place",
        "INVOKES",
        0.50,
        "fuzzy_name",
        {"call_line": 6, "in_branch": False, "is_await": False, "arg_binding": {}},
    ),
    ("pyapp.orders.OrderService.save", "pyapp.store.OrderError", "RAISES", 0.90, "resolved", {}),
    ("pyapp.orders.OrderService.place", "pyapp.store.OrderError", "CATCHES", 0.90, "resolved", {}),
    (
        "pyapp.orders.OrderService.place",
        "tests.test_orders.test_place",
        "TESTED_BY",
        0.85,
        "test_import",
        {},
    ),
    ("pyapp.orders.OrderService.list_open", "table:orders", "READS", 0.85, "sql_literal", {}),
    ("pyapp.orders.OrderService.save", "table:orders", "WRITES", 0.85, "sql_literal", {}),
    ("pyapp.orders.OrderService.archive", "collection:archive_orders", "WRITES", 0.85, "mongo_chain", {}),
    ("pyapp.orders.OrderService.graph", "label:Order", "READS", 0.85, "cypher_literal", {}),
    ("table:orders", "column:orders.id", "CONTAINS", 1.00, "syntax", {}),
]

# Prose passages that come with the tree: a README and one .sql file, both ordinary passages.
README_TITLE = "README.md (lines 1-3)"
README_TEXT = (
    "# pyapp\n"
    "The order service keeps orders for a shop.\n"
    "`OrderService.place` totals an order and sends its invoice."
)
SQL_TITLE = "schema/orders.sql (lines 1-2)"
SQL_TEXT = (
    "CREATE TABLE orders (id INT PRIMARY KEY, total DECIMAL(10, 2), status TEXT);\n"
    "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);"
)

# (passage title, node display name, omega, token) - a prose passage naming a code node.
REFERS_TO: list[tuple[str, str, float, str]] = [
    (README_TITLE, "pyapp.orders.OrderService.place", 0.85, "OrderService.place"),
    (README_TITLE, "pyapp.orders.OrderService", 0.60, "order service"),
    (SQL_TITLE, "table:orders", 0.85, "orders"),
    (SQL_TITLE, "table:customers", 0.85, "customers"),
]

# The three commits `make_code_checkout` builds, newest first (WP2b builds these for real).
COMMITS: list[tuple[str, str, str, str]] = [
    ("c3c3c3c", "2026-01-03T00:00:00+00:00", "Raise OrderError from save", "OrderService.save"),
    ("b2b2b2b", "2026-01-02T00:00:00+00:00", "Total the order in place", "OrderService.place"),
    ("a1a1a1a", "2026-01-01T00:00:00+00:00", "Add the order service", "OrderService"),
]


# ------------------------------------------------------------------ writing


def chunks() -> list[Chunk]:
    """Every passage of the tree, in the order the chunker walks it."""
    out: list[Chunk] = []
    for spec in SYMBOLS:
        out.append(Chunk(len(out), spec.title, spec.text))
    out.append(Chunk(len(out), SQL_TITLE, SQL_TEXT))
    out.append(Chunk(len(out), README_TITLE, README_TEXT))
    return out


def commit_chunks() -> list[Chunk]:
    """One passage per commit, as WP2b writes them: message + the qualnames it touched."""
    start = len(chunks())
    return [
        Chunk(start + i, f"commit {sha}: {subject}", f"{subject}\n\nTouched: {touched}")
        for i, (sha, _date, subject, touched) in enumerate(COMMITS)
    ]


def _by_display(source_id: str) -> dict[str, str]:
    """Display name -> node id, for symbols and (as `kind:qualname`) data objects."""
    ids = {s.display: symbol_id(source_id, s.path, s.qualname) for s in SYMBOLS}
    ids.update({f"{d.kind}:{d.qualname}": data_id(source_id, d.kind, d.qualname) for d in DATA_OBJECTS})
    return ids


def build_code_source(
    store, ollama, *, name: str = "pyapp", with_history: bool = True, with_graph: bool = True
) -> str:
    """
    Index the fixture tree as one source and write its whole code graph through the store.

    The passages go in through the real `index_source`, so they get real embeddings and whatever
    OpenIE the fake model finds in them; everything else is written with the WP1 store methods.

    `with_graph=False` indexes exactly the same passages and writes **no** code graph at all. That
    is the control the FIDELITY inertness claim needs: comparing it against the full build under
    `code_structural_scale = 0` separates "the code graph contributes nothing" (which must be true)
    from "the corpus now contains code passages" (which is just more passages).
    """
    source_id = store.create_source("repo", name)
    body = chunks()
    history = commit_chunks() if with_history else []
    index_source(store, ollama, source_id, body + history)
    if with_graph:
        write_code_graph(store, ollama, source_id, with_history=with_history)
    return source_id


def write_code_graph(store, ollama, source_id: str, *, with_history: bool = True) -> None:
    """The code graph on its own, for a source whose passages are already indexed."""
    body = chunks()
    history = commit_chunks() if with_history else []
    passage_of_title = {c.title: passage_id(source_id, c) for c in body + history}
    ids = _by_display(source_id)
    vectors = ollama.embed([_name_text(display) for display in ids], kind="document")
    embedding_of = dict(zip(ids, [v.tolist() for v in vectors], strict=True))

    store.add_symbols(
        [
            {
                "id": ids[s.display],
                "source_id": source_id,
                "name": s.name,
                "qualname": s.qualname,
                "kind": s.kind,
                "lang": "python",
                "path": s.path,
                "line_start": s.line_start,
                "line_end": s.line_end,
                "signature": s.signature,
                "doc": s.doc,
                "is_test": s.is_test,
                "raises": s.raises,
                "embedding": embedding_of[s.display],
            }
            for s in SYMBOLS
        ]
    )
    store.add_data_objects(
        [
            {
                "id": ids[f"{d.kind}:{d.qualname}"],
                "source_id": source_id,
                "name": d.name,
                "qualname": d.qualname,
                "kind": d.kind,
                "dialect": d.dialect,
                "embedding": embedding_of[f"{d.kind}:{d.qualname}"],
            }
            for d in DATA_OBJECTS
        ]
    )
    store.add_code_edges(
        [
            {"a": ids[a], "b": ids[b], "kind": kind, "omega": omega, "provenance": prov, "extra": extra}
            for a, b, kind, omega, prov, extra in EDGES
        ]
    )

    definitions = [(ids[s.display], passage_of_title[s.title]) for s in SYMBOLS]
    # A data object is DEFINED_IN *every* passage whose literal names it (S2.5), plus the DDL file.
    for d in DATA_OBJECTS:
        definitions.append((ids[f"{d.kind}:{d.qualname}"], passage_of_title[SQL_TITLE]))
        for display in d.defined_in:
            definitions.append((ids[f"{d.kind}:{d.qualname}"], passage_of_title[display_title(display)]))
    store.link_definitions(definitions)

    store.add_refers_to(
        [
            {
                "passage_id": passage_of_title[title],
                "node_id": ids[display],
                "omega": omega,
                "token": token,
            }
            for title, display, omega, token in REFERS_TO
        ]
    )
    store.set_symbol_communities({ids[s.display]: s.community for s in SYMBOLS if s.community is not None})
    # The cross-kind synonym WP2i's `find_synonyms` writes when prose and code are indexed
    # together. It is a code-only weight term, so `code_structural_scale = 0` must drop it too.
    # The entity has to be one the fake OpenIE really found in these passages, or all three stores
    # skip the row for a missing endpoint and the inertness test covers nothing.
    store.add_synonyms([(entity_id("acme robotics"), ids["pyapp.orders.OrderService"], 0.87)])

    if with_history:
        _write_history(store, source_id, ids, passage_of_title)


def _write_history(store, source_id: str, ids: dict[str, str], passage_of_title: dict[str, str]) -> None:
    rows, modifies, definitions = [], [], []
    for ordinal, (sha, date, subject, touched) in enumerate(COMMITS):
        cid = commit_id(source_id, sha)
        rows.append(
            {
                "id": cid,
                "source_id": source_id,
                "sha": sha,
                "author": "A Committer",
                "date": date,
                "message": subject,
                "ordinal": ordinal,
            }
        )
        modifies.append(
            {
                "commit_id": cid,
                "symbol_id": ids[f"pyapp.orders.{touched}"],
                "omega": 1.0,
                "hunk": {"file": "pyapp/orders.py", "old_range": [1, 0], "new_range": [16, 8], "churn": 8},
            }
        )
        definitions.append((cid, passage_of_title[f"commit {sha}: {subject}"]))
    store.add_commits(rows)
    store.add_modifies(modifies)
    # Newest -> older, the first-parent chain.
    store.add_precedes(
        [
            (commit_id(source_id, a[0]), commit_id(source_id, b[0]))
            for a, b in zip(COMMITS, COMMITS[1:], strict=False)
        ]
    )
    store.link_definitions(definitions)


def display_title(display: str) -> str:
    """The passage title of a symbol, by its display name."""
    return next(s.title for s in SYMBOLS if s.display == display)


def _name_text(display: str) -> str:
    """What `codegraph.model.name_text` embeds: the name and its split tokens."""
    last = display.rsplit(".", 1)[-1].rsplit(":", 1)[-1]
    return f"{last} {display}"
