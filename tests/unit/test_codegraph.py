"""
The code graph extractor: `src/hippo/codegraph/`.

Pure tests -- no store, no Ollama, no pipeline. `extract_code` is handed documents and
returns a `CodeGraph`, so everything here is a function of the bytes in
`tests/fixtures/code_sample/` (and, for the rows that tree does not reach, of small inline
trees written in the test itself).

Three groups:

* The fixture, checked against `expected.json`. That file is the *spec*: every symbol, every
  data object and every edge with its ω and provenance. `scripts/update_expected.py`
  regenerates it, and a diff there is a change to what hippo promises, read like source.
* PLAN.md's 2.2b resolver table, row by row, including the rows that must produce **no
  edge**. Those are positive assertions: `x.y.z()` not linking is a decision, not an
  oversight. Roughly half the table has no file in the frozen fixture tree (WP2i, WP3 and
  WP4 pin counts and chunk titles off it, so it must not grow); those rows get inline trees.
* The properties everything downstream leans on: determinism, speed, budgets, and the
  dependency direction that keeps this package importable from `ingest.chunker`.
"""

from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from hippo.codegraph import extract_code, resolve
from hippo.codegraph.data_access import (
    classify_literal,
    cypher_objects,
    mongo_hit,
    mongoose_hit,
    read_sql_file,
    sql_tables,
)
from hippo.codegraph.languages import PARSED_LANGS, RULES
from hippo.codegraph.model import (
    CODE_MAX_FILE_BYTES,
    LANG_BY_SUFFIX,
    CodeEdge,
    FileFacts,
    Symbol,
    merge_edges,
    name_text,
    symbol_id,
)
from hippo.codegraph.python import is_test_path, module_qualname
from hippo.codegraph.resolve import Resolution
from hippo.codegraph.treesitter import GRAMMARS, get_language, grammar_for
from hippo.ingest import readers
from tests.conftest import CODE_SAMPLE_PATH, code_sample_docs

EXPECTED = json.loads((CODE_SAMPLE_PATH / "expected.json").read_text())
SRC = Path(__file__).resolve().parents[2] / "src" / "hippo"


# ------------------------------------------------------------------ helpers


@dataclass
class Doc:
    """A stand-in `Document` for the inline trees. Same three fields `extract_code` reads."""

    title: str
    text: str
    path: str = ""
    is_code: bool = True


def graph_of(files: dict[str, str], source_id: str = "s"):
    """Extract a small inline tree written as `{path: source}`."""
    return extract_code([Doc(name, text, name) for name, text in files.items()], source_id)


def edges_of(graph, kind: str | None = None) -> set[tuple]:
    """`(kind, ω, provenance, a, b)` with nodes named by path/qualname, never by id."""
    names = {s.id: f"{s.path}::{s.qualname}" for s in graph.symbols}
    names.update({d.id: f"{d.kind}:{d.qualname}" for d in graph.data_objects})
    return {
        (e.kind, e.omega, e.provenance, names.get(e.a, e.a), names.get(e.b, e.b))
        for e in graph.edges
        if kind is None or e.kind == kind
    }


def links(graph, kind: str | None = None) -> set[tuple[str, str, str]]:
    """Just `(kind, a, b)` -- for the "no edge" assertions, where ω is beside the point."""
    return {(k, a, b) for k, _, _, a, b in edges_of(graph, kind)}


@pytest.fixture(scope="module")
def fixture_graph():
    """The `code_sample` tree, extracted once. `source_id` matches `expected.json`'s."""
    return extract_code(code_sample_docs(), "fixture")


def by_qualname(graph, path: str, qualname: str):
    return next(s for s in graph.symbols if s.path == path and s.qualname == qualname)


def edge(graph, kind: str, a: str, b: str):
    """The one edge of `kind` between two `path::qualname` (or `kind:qualname`) nodes."""
    found = [e for e in edges_of(graph, kind) if e[3] == a and e[4] == b]
    assert len(found) == 1, f"expected exactly one {kind} {a} -> {b}, found {found}"
    return found[0]


# ------------------------------------------------------------ the toolchain


def test_grammars_load():
    """All six grammars build. Catches a wheel whose ABI moved out from under us."""
    assert GRAMMARS == ("python", "typescript", "tsx", "go", "csharp", "rust")
    for grammar in GRAMMARS:
        assert get_language(grammar) is not None
    with pytest.raises(ValueError):
        get_language("cobol")


def test_grammar_choice_by_suffix():
    """JSX would confuse the plain TypeScript grammar, so every JS-ish suffix uses TSX."""
    assert grammar_for("a/b.ts", "typescript") == "typescript"
    for name in ("a.tsx", "a.js", "a.jsx", "a.mjs", "a.cjs"):
        assert grammar_for(name, "typescript") == "tsx"
    assert grammar_for("a.py", "python") == "python"
    # One grammar each for the rest, so the language name is the grammar name.
    for name, lang in (("a.go", "go"), ("A.cs", "csharp"), ("a.rs", "rust")):
        assert grammar_for(name, lang) == lang


def test_every_language_is_a_complete_registration():
    """
    A language is `RULES[name]`, not a branch. Every entry answers every question the
    extractor, the resolver and the chunker ask -- a half-filled entry would fail at the one
    call site that happens to reach it, on somebody else's source, months later.
    """
    assert sorted(RULES) == ["csharp", "go", "python", "rust", "typescript"]
    for name, rules in sorted(RULES.items()):
        assert rules.name == name
        assert rules.line_comment in ("#", "//"), name
        assert rules.walk is None or callable(rules.walk), name
        for field in ("resolve_module", "scope_defines", "module_qualname", "is_test_path",
                      "test_stem", "is_test_function", "member_paths"):  # fmt: skip
            assert callable(getattr(rules, field)), f"{name}.{field}"
        assert rules.source_setup is None or callable(rules.source_setup), name
        assert rules.self_names and rules.super_names, name
        # Byte-for-byte behaviour of the two languages that already shipped.
        if name in ("python", "typescript"):
            assert rules.scope_defines(None, None) == {}
            assert rules.self_names == frozenset({"self", "cls", "this"})
            assert rules.super_names == frozenset({"super", "super()"})


def test_base_is_csharps_super_and_nobody_elses():
    """
    `base` means `super` in C# and is an ordinary module name in Python -- `from . import
    base` then `base.helper()` is a real INVOKES edge. One shared `SUPER_NAMES` holding
    `base` would route that to the MRO and silently drop the edge, so the names are per
    language. Same for Rust's `Self`.
    """
    assert "base" in RULES["csharp"].super_names
    assert "base" not in RULES["python"].super_names | RULES["typescript"].super_names
    assert "Self" in RULES["rust"].self_names
    assert "Self" not in RULES["python"].self_names

    graph = graph_of(
        {
            "pkg/__init__.py": "",
            "pkg/base.py": "def helper():\n    return 1\n",
            "pkg/app.py": "from . import base\n\ndef go():\n    return base.helper()\n",
        }
    )
    assert ("INVOKES", 0.90, "via_import", "pkg/app.py::go", "pkg/base.py::helper") in edges_of(
        graph, "INVOKES"
    )


def test_every_known_suffix_has_a_grammar_and_a_registration():
    """`lang_of` may not name a language the extractor cannot at least load a grammar for."""
    for suffix, lang in sorted(LANG_BY_SUFFIX.items()):
        if lang == "sql":  # sqlglot reads these; there is no tree-sitter grammar and no walker
            continue
        assert lang in RULES, suffix
        assert grammar_for(f"file{suffix}", lang) in GRAMMARS, suffix


def test_parsed_langs_is_exactly_the_languages_with_a_walker():
    """
    `git_history` reads hunks only in files it can parse. `PARSED_LANGS` is derived from the
    registry rather than listed, so registering a walker is the whole job -- there is no
    second place to remember.
    """
    assert sorted(PARSED_LANGS) == sorted(name for name, r in RULES.items() if r.walk is not None)
    assert sorted(PARSED_LANGS) == ["csharp", "python", "typescript"]


def as_python(**overrides):
    """Python's rules with one hook swapped, to exercise a rule no shipped language uses yet."""
    return dataclasses.replace(RULES["python"], **overrides)


def test_a_same_scope_name_needs_no_import_and_is_worth_1_00(monkeypatch):
    """
    Go's package and C#'s namespace make a sibling file's name visible with no import. The
    resolver seeds those after the file's own `defines`, so an own name still wins as
    `same_file`, and a sibling's is `same_scope` at 1.00 -- the language resolves it as
    unambiguously as a local name, and 0.90 `via_import` would understate it.
    """

    def scope_defines(index, facts):
        return {
            name: symbol
            for module, names in index.defines.items()
            if module != facts.module
            for name, symbol in names.items()
        }

    monkeypatch.setitem(RULES, "python", as_python(scope_defines=scope_defines))
    graph = graph_of(
        {
            "billing.py": "def total(o):\n    return 1\n",
            "orders.py": "def place(o):\n    return total(o)\n",
        }
    )
    assert edge(graph, "INVOKES", "orders.py::place", "billing.py::total")[1:3] == (1.00, "same_scope")


def test_a_scope_resolution_answers_for_the_names_it_holds(monkeypatch):
    """
    `ledger.Post` where `ledger` is a package or a namespace, not a file: `resolve_module`
    hands back a `Resolution` carrying the scope, and `_on_class`'s sibling `_in_scope`
    reads the member out of it. The tier is the holder's distance, as for any other import.
    """

    def resolve_module(index, facts, spec):
        target = index.modules.get(spec.module)
        if target is None:
            return None
        return Resolution(
            index.module_symbol(target),
            0.95,
            "import_path",
            is_module=True,
            scope=dict(index.defines.get(target.module, {})),
        )

    monkeypatch.setitem(RULES, "python", as_python(resolve_module=resolve_module))
    graph = graph_of(
        {
            "ledger.py": "def post(entry):\n    return 1\n",
            "orders.py": "import ledger\n\ndef place(o):\n    return ledger.post(o)\n",
        }
    )
    assert edge(graph, "INVOKES", "orders.py::place", "ledger.py::post")[1:3] == (0.90, "via_import")
    assert ("IMPORTS", "orders.py::orders", "ledger.py::ledger") in links(graph, "IMPORTS")


def test_a_class_can_hold_members_in_another_file(monkeypatch):
    """
    Rust puts `impl S` in any file, so which files may hold a member of `S` is the
    language's call. Every other language answers "the one the class is in".
    """
    monkeypatch.setitem(
        RULES, "python", as_python(member_paths=lambda index, qualname, path: sorted(index.files))
    )
    graph = graph_of(
        {
            "impl.py": "class Service:\n    def log(self, m):\n        return m\n",
            "app.py": "class Service:\n    pass\n\ndef go(s=Service()):\n    return Service().log(1)\n",
        }
    )
    assert edge(graph, "INVOKES", "app.py::go", "impl.py::Service.log")[1:3] == (0.90, "via_import")


def test_build_index_merges_a_scope_and_owns_an_inline_module():
    """
    `FileFacts.scope` is what a Go package or a C# namespace is called; `build_index` merges
    every file of one, first declaration winning. And a symbol of kind `module` that is not
    the file's own -- Rust's inline `mod tests { }` -- is an ordinary container.
    """
    facts = []
    for path, scope in (("a.py", "pkg"), ("b.py", "pkg"), ("c.py", "other")):
        module = module_qualname(path)
        symbols = [Symbol(id=f"m-{path}", name=module, qualname=module, kind="module", path=path)]
        symbols.append(Symbol(id=f"f-{path}", name=path[0], qualname=path[0], kind="function", path=path))
        facts.append(FileFacts(path=path, lang="python", module=module, scope=scope, symbols=symbols))
    index = resolve.build_index(facts, {"python": "state"})
    assert sorted(index.scopes[("python", "pkg")]) == ["a", "b"]
    assert sorted(index.scopes[("python", "other")]) == ["c"]
    assert index.lang_state == {"python": "state"}

    inline = FileFacts(
        path="lib.rs",
        lang="rust",
        module="lib",
        symbols=[
            Symbol(id="m", name="lib", qualname="lib", kind="module", path="lib.rs"),
            Symbol(id="t", name="tests", qualname="tests", kind="module", path="lib.rs"),
            Symbol(id="f", name="works", qualname="tests.works", kind="function", path="lib.rs"),
        ],
    )
    index = resolve.build_index([inline])
    assert sorted(index.defines["lib"]) == ["tests"]  # the inline mod is a top-level name...
    assert index.members[("lib.rs", "tests")]["works"].id == "f"  # ...and owns what is in it


def test_a_language_names_its_own_test_functions(monkeypatch):
    """
    Only Python and TypeScript spell a test case `test_*`. Go's is `TestPlace`, C#'s is an
    ordinary method with `[Fact]` on it -- so the *name* rule is the language's, while
    "is this file test code at all" stays shared (`is_test_path` already decided that).
    Without the hook a Go test function is nobody's test and the 0.85 `test_import` row of
    the ω table is unreachable for it.
    """
    files = {
        "billing.py": "def total(o):\n    return 1\n",
        "tests/check_orders.py": "from billing import total\n\ndef CheckPlace():\n    return total(1)\n",
    }
    assert edges_of(graph_of(files), "TESTED_BY") == set()  # `CheckPlace` is not `test_*`

    monkeypatch.setitem(RULES, "python", as_python(is_test_function=lambda s: s.name.startswith("Check")))
    edges = edges_of(graph_of(files), "TESTED_BY")
    assert edges == {
        ("TESTED_BY", 0.85, "test_import", "billing.py::total", "tests/check_orders.py::CheckPlace")
    }


def test_source_setup_runs_once_over_the_raw_documents(monkeypatch):
    """
    Go reads `go.mod` and Rust finds its crate root once per source, not per file, and from
    the *documents* -- `go.mod` is not a file any walker parses. A language that produced no
    files is not asked at all.
    """
    seen = []

    def source_setup(docs):
        seen.append([d.title for d in docs])
        return "once"

    monkeypatch.setitem(RULES, "python", as_python(source_setup=source_setup))
    monkeypatch.setitem(RULES, "go", dataclasses.replace(RULES["go"], source_setup=source_setup))
    graph_of({"a.py": "def f():\n    return 1\n", "notes.md": "# hi\n", "tool.go": "package main\n"})
    assert seen == [["a.py", "notes.md", "tool.go"]]  # once, for Python only: Go has no walker


def test_a_registered_language_with_no_walker_is_skipped_as_unsupported():
    """
    Go, C# and Rust are registered for their suffix, grammar and comment style before their
    walkers exist. Until then their files behave exactly as a language we have no grammar
    for: no symbols, line windows, one `unsupported` row -- which is why `tools/build.go` is
    still the fixture's unparsed-code file.
    """
    graph = graph_of({"good.py": "def fine():\n    return 1\n", "tool.go": "package main\n"})
    assert graph.files_skipped == {"tool.go": "unsupported"}
    assert graph.files_parsed == ["good.py"]
    assert graph.stats()["files_skipped"] == {"parse_error": 0, "too_big": 0, "unsupported": 1}


def test_jsx_and_fragments_parse():
    """R4 T9: the TSX grammar reads plain JSX, and that file still yields its symbols."""
    graph = graph_of({"ui.jsx": "export function App() { return <div>{go()}</div>; }\n"})
    assert [s.qualname for s in graph.symbols] == ["ui", "App"]
    assert graph.files_skipped == {}


# ---------------------------------------------------------------- the ids


def test_symbol_ids_are_namespaced_by_source_and_path():
    """D4: two same-named symbols in different files must not collide."""
    a = symbol_id("src1", "a/x.py", "Thing.go")
    assert a != symbol_id("src1", "b/x.py", "Thing.go")
    assert a != symbol_id("src2", "a/x.py", "Thing.go")
    assert a == symbol_id("src1", "a/x.py", "Thing.go")
    assert a.startswith("symbol-")


def test_name_text_puts_the_split_tokens_first():
    """D7: what makes the prose entity `order service` a synonym of the symbol."""
    assert name_text("OrderService") == "order service OrderService"
    assert name_text("get_user2") == "get user 2 get_user2"
    assert name_text("place") == "place"  # already one plain word; not doubled


def test_module_qualname_keeps_dunder_init():
    """2.2a: a package and its `__init__` module are never the same node."""
    assert module_qualname("pyapp/__init__.py") == "pyapp.__init__"
    assert module_qualname("src/hippo/store/ladybug.py") == "src.hippo.store.ladybug"
    assert module_qualname("tsapp/models/order.ts") == "tsapp.models.order"


def test_is_test_path():
    for path in ("tests/test_orders.py", "test/a.py", "a/test_x.py", "a/x_test.py", "a/x.spec.ts"):
        assert is_test_path(path), path
    for path in ("pyapp/orders.py", "a/latest.py", "a/contest.py"):
        assert not is_test_path(path), path


def test_merge_edges_keeps_the_best_omega_and_lists_repeat_call_sites():
    """One edge per (a, b, kind); the first call line stays first and the rest are listed."""
    merged = merge_edges(
        [
            CodeEdge("a", "b", "INVOKES", 0.50, "fuzzy_name", {"call_line": 3}),
            CodeEdge("a", "b", "INVOKES", 0.90, "via_import", {"call_line": 9}),
            CodeEdge("a", "a", "INVOKES", 1.00, "same_file", {}),  # self-loop: dropped
        ]
    )
    assert len(merged) == 1
    assert (merged[0].omega, merged[0].provenance) == (0.90, "via_import")
    assert merged[0].extra["call_line"] == 3
    assert merged[0].extra["call_lines"] == [9]


# ------------------------------------------------------- the fixture: symbols


def test_fixture_symbol_set(fixture_graph):
    """The exact symbol set, with kind and line range. Nothing more, nothing less."""
    found = {(s.path, s.qualname, s.kind, s.line_start, s.line_end) for s in fixture_graph.symbols}
    wanted = {
        (s["path"], s["qualname"], s["kind"], s["line_start"], s["line_end"]) for s in EXPECTED["symbols"]
    }
    assert found == wanted
    assert len(fixture_graph.symbols) == 30


def test_fixture_symbol_line_ranges(fixture_graph):
    """The line numbers PLAN.md's fixture plan names, recomputed from the final files."""
    ranges = {(s.path, s.qualname): (s.line_start, s.line_end) for s in fixture_graph.symbols}
    assert ranges[("pyapp/store.py", "Base")] == (1, 5)
    assert ranges[("pyapp/store.py", "Base.log")] == (4, 5)
    assert ranges[("pyapp/billing.py", "total")] == (4, 5)
    assert ranges[("pyapp/billing.py", "send_invoice")] == (8, 9)
    assert ranges[("pyapp/orders.py", "OrderService")] == (9, 40)
    assert ranges[("pyapp/orders.py", "OrderService.place")] == (16, 23)
    assert ranges[("pyapp/cli.py", "main")] == (4, 6)
    assert ranges[("tsapp/models/base.ts", "Base")] == (1, 5)
    assert ranges[("tsapp/models/base.ts", "Base.log")] == (2, 4)
    assert ranges[("tsapp/models/order.ts", "Order")] == (7, 11)
    assert ranges[("tsapp/models/order.ts", "Order.total")] == (8, 10)
    assert ranges[("tsapp/models/order.ts", "compute")] == (13, 15)
    assert ranges[("tsapp/index.ts", "main")] == (3, 8)


def test_fixture_display_qualnames(fixture_graph):
    """2.2a: the fully-qualified name passage titles, path tools and the CLI all use."""
    place = by_qualname(fixture_graph, "pyapp/orders.py", "OrderService.place")
    assert place.display == "pyapp.orders.OrderService.place"
    assert by_qualname(fixture_graph, "pyapp/orders.py", "pyapp.orders").display == "pyapp.orders"
    assert by_qualname(fixture_graph, "tsapp/models/order.ts", "compute").display == (
        "tsapp.models.order.compute"
    )


def test_fixture_signatures_and_docs(fixture_graph):
    place = by_qualname(fixture_graph, "pyapp/orders.py", "OrderService.place")
    assert place.signature == "def place(self, order)"
    assert place.doc.startswith("Place an order: total it with billing")
    assert len(place.doc) >= 80  # WP4's code-question generator needs a qualifying function
    service = by_qualname(fixture_graph, "pyapp/orders.py", "OrderService")
    assert service.signature == "class OrderService(Base)"
    assert service.doc.startswith("Keeps orders.") and "Second paragraph" in service.doc
    order = by_qualname(fixture_graph, "tsapp/models/order.ts", "Order")
    assert order.signature == "class Order extends Base"
    assert len(order.doc) >= 80 and order.doc.startswith("An order.")
    compute = by_qualname(fixture_graph, "tsapp/models/order.ts", "compute")
    assert compute.signature == "compute = (o: Order): number"


def test_fixture_is_test_and_raises(fixture_graph):
    """`raise ValueError` lands on the symbol, with no edge anywhere (2.2b)."""
    place = by_qualname(fixture_graph, "pyapp/orders.py", "OrderService.place")
    assert place.raises == ["ValueError"]
    assert not place.is_test
    assert by_qualname(fixture_graph, "tests/test_orders.py", "test_place").is_test
    assert by_qualname(fixture_graph, "tests/test_orders.py", "tests.test_orders").is_test


def test_fixture_header_and_statement_lines(fixture_graph):
    """The chunker's half of the contract: where a header stops and where a body may split."""
    module = by_qualname(fixture_graph, "pyapp/orders.py", "pyapp.orders")
    assert module.header_end == 8  # the imports and DEFAULT_STATUS, up to the class on line 9
    assert module.statement_lines == [1, 2, 3, 4, 6, 9]
    service = by_qualname(fixture_graph, "pyapp/orders.py", "OrderService")
    assert service.header_end == 15  # docstring and __tablename__, up to `place` on line 16
    place = by_qualname(fixture_graph, "pyapp/orders.py", "OrderService.place")
    assert place.header_end == place.line_end  # a function is all header
    assert place.statement_lines == [17, 18, 19, 21, 22, 23]
    bare = by_qualname(fixture_graph, "pyapp/store.py", "pyapp.store")
    assert bare.header_end < bare.line_start  # opens with `class Base`: no header passage at all


def test_row_is_exactly_the_store_shape(fixture_graph):
    """
    `Symbol` carries five fields the store has no columns for. `row()` is the boundary, so
    the indexer never has to know which of them the schema happens to accept today.
    """
    from hippo.store.code import data_object_write_row, symbol_write_row

    place = by_qualname(fixture_graph, "pyapp/orders.py", "OrderService.place")
    row = place.row()
    assert set(row) == {
        "id", "source_id", "name", "qualname", "kind", "lang", "path",
        "line_start", "line_end", "signature", "doc", "is_test", "raises",
    }  # fmt: skip
    assert symbol_write_row(row)["qualname"] == "OrderService.place"
    orders = next(d for d in fixture_graph.data_objects if d.kind == "table" and d.qualname == "orders")
    assert set(orders.row()) == {"id", "source_id", "name", "qualname", "kind", "dialect"}
    assert data_object_write_row(orders.row())["dialect"] == "sql"


def test_fixture_params_feed_the_arg_binding(fixture_graph):
    assert by_qualname(fixture_graph, "pyapp/orders.py", "OrderService.place").params == ["self", "order"]
    assert by_qualname(fixture_graph, "pyapp/billing.py", "total").params == ["order"]
    assert by_qualname(fixture_graph, "tsapp/models/base.ts", "Base.log").params == ["msg"]


# --------------------------------------------------------- the fixture: edges


def test_fixture_edges_match_the_plans_worked_example(fixture_graph):
    """PLAN.md 2.6's named edges, each with the ω and provenance the table gives it."""
    assert edge(fixture_graph, "IMPORTS", "pyapp/cli.py::pyapp.cli", "pyapp/orders.py::OrderService")[
        1:3
    ] == (
        0.90,
        "reexport",
    )
    assert edge(
        fixture_graph,
        "INVOKES",
        "pyapp/orders.py::OrderService.place",
        "pyapp/billing.py::send_invoice",
    )[1:3] == (0.90, "via_import")
    assert edge(
        fixture_graph,
        "INVOKES",
        "pyapp/orders.py::OrderService.list_open",
        "pyapp/orders.py::OrderService.run",
    )[1:3] == (1.00, "same_file")
    assert edge(fixture_graph, "OVERRIDES", "pyapp/orders.py::OrderService.log", "pyapp/store.py::Base.log")[
        1:3
    ] == (0.90, "mro")
    assert edge(fixture_graph, "RAISES", "pyapp/orders.py::OrderService.save", "pyapp/store.py::OrderError")[
        1:3
    ] == (0.90, "resolved")
    assert edge(
        fixture_graph, "CATCHES", "pyapp/orders.py::OrderService.place", "pyapp/store.py::OrderError"
    )[1:3] == (0.90, "resolved")
    assert edge(fixture_graph, "READS", "pyapp/orders.py::OrderService.list_open", "table:orders")[1:3] == (
        0.85,
        "sql_literal",
    )
    assert edge(
        fixture_graph, "WRITES", "pyapp/orders.py::OrderService.archive", "collection:archive_orders"
    )[1:3] == (0.85, "mongo_chain")
    assert edge(fixture_graph, "READS", "pyapp/orders.py::OrderService.graph", "label:Order")[1:3] == (
        0.85,
        "cypher_literal",
    )
    assert edge(fixture_graph, "READS", "tsapp/index.ts::main", "collection:Order")[1:3] == (
        0.85,
        "mongoose_model",
    )
    assert edge(
        fixture_graph, "TESTED_BY", "pyapp/orders.py::OrderService.place", "tests/test_orders.py::test_place"
    )[1:3] == (0.85, "test_import")
    assert edge(
        fixture_graph,
        "TESTED_BY",
        "pyapp/orders.py::pyapp.orders",
        "tests/test_orders.py::tests.test_orders",
    )[1:3] == (0.75, "test_filename")


def test_fixture_ruled_edges(fixture_graph):
    """
    The two rows where PLAN.md 2.6's prose contradicts the 2.2b spec table. The table wins
    (orchestrator ruling): the receiver of `service.place(...)` is a tracked binding, and
    `self.log(...)` never reaches the base because `OrderService` defines `log` itself.
    """
    assert edge(fixture_graph, "INVOKES", "pyapp/cli.py::main", "pyapp/orders.py::OrderService.place")[
        1:3
    ] == (0.90, "via_import")
    assert edge(
        fixture_graph,
        "INVOKES",
        "pyapp/orders.py::OrderService.place",
        "pyapp/orders.py::OrderService.log",
    )[1:3] == (1.00, "same_file")
    assert (
        "INVOKES",
        "pyapp/orders.py::OrderService.place",
        "pyapp/store.py::Base.log",
    ) not in links(fixture_graph)


def test_fixture_fuzzy_name_edge(fixture_graph):
    """`session.run(...)`: the receiver is unknown, but `run` is unique and not stoplisted."""
    assert edge(
        fixture_graph,
        "INVOKES",
        "pyapp/orders.py::OrderService.graph",
        "pyapp/orders.py::OrderService.run",
    )[1:3] == (0.50, "fuzzy_name")


def test_fixture_invokes_extra(fixture_graph):
    """The INVOKES `extra` PLAN.md 2.6 spells out, exactly."""
    found = next(
        e
        for e in fixture_graph.edges
        if e.kind == "INVOKES" and e.extra.get("call_line") == 18 and e.provenance == "via_import"
    )
    assert found.extra == {
        "call_line": 18,
        "in_branch": False,
        "is_await": False,
        "arg_binding": {"order": "order"},
    }
    branched = edge(
        fixture_graph,
        "INVOKES",
        "pyapp/orders.py::OrderService.place",
        "pyapp/billing.py::send_invoice",
    )
    assert branched  # the `try:` call is the same shape but in a branch
    inside = next(e for e in fixture_graph.edges if e.kind == "INVOKES" and e.extra.get("call_line") == 19)
    assert inside.extra["in_branch"] is True


def test_fixture_contains_edges(fixture_graph):
    """CONTAINS is pure syntax: module -> class/function, class -> method, table -> column."""
    contains = links(fixture_graph, "CONTAINS")
    assert ("CONTAINS", "pyapp/orders.py::pyapp.orders", "pyapp/orders.py::OrderService") in contains
    assert (
        "CONTAINS",
        "pyapp/orders.py::OrderService",
        "pyapp/orders.py::OrderService.place",
    ) in contains
    assert ("CONTAINS", "table:orders", "column:orders.id") in contains
    assert all(
        omega == 1.00 and prov == "syntax" for _, omega, prov, _, _ in edges_of(fixture_graph, "CONTAINS")
    )


def test_fixture_no_edge_rows(fixture_graph):
    """
    Every "no edge" row 2.6 names, as a positive assertion. A call that does not resolve
    inside the source produces nothing at all -- not a low-confidence edge (D24).
    """
    targets = {b for _, _, b in links(fixture_graph)}
    for absent in ("print", "join", "sum", "console", "log", "insert_one", "model", "Schema"):
        assert not any(target.endswith(f"::{absent}") for target in targets), absent
    # `import os` and `import mongoose from "mongoose"` are dependencies, not this source.
    assert not any("os" == b.rpartition("::")[2] for _, _, b in links(fixture_graph, "IMPORTS"))
    assert not any("mongoose" in b for _, _, b in links(fixture_graph, "IMPORTS"))
    # `class OrderError(Exception)`: a builtin base is not in the repo, so there is no INHERITS.
    assert not any(a.endswith("::OrderError") for _, _, a in links(fixture_graph, "INHERITS"))
    # `db.archive_orders.insert_one(...)` is a data access, never a call edge.
    assert not any(a.endswith("::OrderService.archive") for _, _, a in links(fixture_graph, "INVOKES"))


# ---------------------------------------------------- the fixture: data objects


def test_fixture_data_objects_are_deduped_across_every_site(fixture_graph):
    """One `table orders` for the DDL, the two SQL literals and `__tablename__` (2.2)."""
    orders = [d for d in fixture_graph.data_objects if d.kind == "table" and d.qualname == "orders"]
    assert len(orders) == 1
    assert orders[0].mentions == [
        ("pyapp/orders.py", 14),
        ("pyapp/orders.py", 28),
        ("pyapp/orders.py", 31),
        ("schema/orders.sql", 1),
    ]
    kinds = {(d.kind, d.qualname) for d in fixture_graph.data_objects}
    assert ("collection", "Order") in kinds and ("label", "Order") in kinds  # kind is part of the key
    # S2.5 needs the declaring site too, not only the file that reads it.
    collection = next(
        d for d in fixture_graph.data_objects if d.kind == "collection" and d.qualname == "Order"
    )
    assert ("tsapp/models/order.ts", 17) in collection.mentions


def test_fixture_tablename_is_the_bare_identifier_row(fixture_graph):
    """`__tablename__ = "orders"` names a table without parsing anything: READS at 0.60."""
    assert edge(fixture_graph, "READS", "pyapp/orders.py::OrderService", "table:orders")[1:3] == (
        0.60,
        "bare_identifier",
    )


def test_fixture_sql_file_columns(fixture_graph):
    """An in-repo `.sql` file contributes tables, their columns and CONTAINS between them."""
    names = {(d.kind, d.qualname) for d in fixture_graph.data_objects}
    assert ("table", "customers") in names
    for column in ("orders.id", "orders.total", "orders.status", "customers.id", "customers.name"):
        assert ("column", column) in names


# --------------------------------------------------------------- the spec file


def test_expected_json_matches_the_extractor(fixture_graph):
    """
    The golden test. `expected.json` and `extract_code` must agree on every symbol, data
    object and edge, order-independently. Regenerate with `scripts/update_expected.py` and
    read the diff -- it is a change to the spec, not a way to make a build green.
    """
    names = {s.id: ["symbol", s.path, s.qualname] for s in fixture_graph.symbols}
    names.update({d.id: ["data", d.kind, d.qualname] for d in fixture_graph.data_objects})

    found_symbols = {
        (s["path"], s["qualname"], s["kind"], s["lang"], s["line_start"], s["line_end"], s["display"])
        for s in EXPECTED["symbols"]
    }
    assert found_symbols == {
        (s.path, s.qualname, s.kind, s.lang, s.line_start, s.line_end, s.display)
        for s in fixture_graph.symbols
    }

    assert {
        (d["kind"], d["qualname"], d["dialect"], tuple(map(tuple, d["mentions"])))
        for d in EXPECTED["data_objects"]
    } == {(d.kind, d.qualname, d.dialect, tuple(d.mentions)) for d in fixture_graph.data_objects}

    assert {
        (
            e["kind"],
            e["omega"],
            e["provenance"],
            tuple(e["a"]),
            tuple(e["b"]),
            json.dumps(e.get("extra", {}), sort_keys=True),
        )
        for e in EXPECTED["edges"]
    } == {
        (
            e.kind,
            e.omega,
            e.provenance,
            tuple(names[e.a]),
            tuple(names[e.b]),
            json.dumps(e.extra, sort_keys=True),
        )
        for e in fixture_graph.edges
    }


def test_expected_json_has_all_seven_sections_filled_in():
    """
    Every section of the spec now has content -- WP2b filled the last two.

    `commits` and `modifies` are keyed by `(ordinal, subject)` and `(ordinal, path, qualname)`
    and carry no sha of their own (S2.17): a sha hashes the author, the committer and both of
    their timestamps, so a file keyed on one could not match on another machine. The `hunk` is
    kept because it is what pins S2.9 -- the ranges are the file as it was at that commit.
    """
    for section in ("symbols", "data_objects", "edges", "definitions", "refers_to", "commits", "modifies"):
        assert EXPECTED[section], f"{section} is empty"
    assert {c["ordinal"] for c in EXPECTED["commits"]} == {0, 1, 2}
    assert set(EXPECTED["commits"][0]) == {"ordinal", "subject", "message", "author", "date"}
    assert set(EXPECTED["modifies"][0]) == {"ordinal", "path", "qualname", "hunk"}
    assert set(EXPECTED["modifies"][0]["hunk"]) == {"file", "old_range", "new_range", "churn"}


def test_expected_json_never_stores_node_ids():
    """Ids hash the run's `source_id`, so a file keyed on them could never match (S2.17)."""
    text = (CODE_SAMPLE_PATH / "expected.json").read_text()
    for prefix in ("symbol-", "data-", "commit-"):
        assert prefix not in text


# -------------------------------------------------------------- 2.2b: Python


def test_python_import_forms():
    """`import a.b`, `from a import b`, a re-export through `__init__`, and a wildcard."""
    graph = graph_of(
        {
            "a/__init__.py": "from .b import helper\n",
            "a/b.py": "def helper():\n    return 1\n",
            "wide/__init__.py": "",
            "wide/things.py": "def widen():\n    return 2\n",
            "app.py": "import a.b\nfrom a.b import helper\nfrom a import helper as reexported\n",
            "star.py": "from wide.things import *\n",
        }
    )
    imports = edges_of(graph, "IMPORTS")
    assert ("IMPORTS", 0.95, "import_path", "app.py::app", "a/b.py::a.b") in imports
    assert ("IMPORTS", 0.95, "import_path", "app.py::app", "a/b.py::helper") in imports
    assert ("IMPORTS", 0.90, "reexport", "app.py::app", "a/b.py::helper") not in imports  # 0.95 wins
    assert ("IMPORTS", 0.60, "wildcard", "star.py::star", "wide/things.py::wide.things") in imports


def test_python_reexport_through_init_is_0_90():
    graph = graph_of(
        {
            "a/__init__.py": "from .b import helper\n",
            "a/b.py": "def helper():\n    return 1\n",
            "app.py": "from a import helper\n",
        }
    )
    assert ("IMPORTS", 0.90, "reexport", "app.py::app", "a/b.py::helper") in edges_of(graph, "IMPORTS")


def test_python_relative_imports():
    """`from . import x` and `from .. import x`, including from inside an `__init__`."""
    graph = graph_of(
        {
            "top/__init__.py": "",
            "top/shared.py": "def one():\n    return 1\n",
            "top/deep/__init__.py": "from ..shared import one\n",
            "top/deep/leaf.py": "from .. import shared\nfrom ..shared import one\n",
        }
    )
    imports = edges_of(graph, "IMPORTS")
    assert (
        "IMPORTS",
        0.95,
        "import_path",
        "top/deep/leaf.py::top.deep.leaf",
        "top/shared.py::one",
    ) in imports
    assert (
        "IMPORTS",
        0.95,
        "import_path",
        "top/deep/leaf.py::top.deep.leaf",
        "top/shared.py::top.shared",
    ) in imports
    assert (
        "IMPORTS",
        0.95,
        "import_path",
        "top/deep/__init__.py::top.deep.__init__",
        "top/shared.py::one",
    ) in imports


def test_python_self_super_and_class_calls():
    """The four receiver shapes: `self.m`, `super().m`, `Class.m`, and `obj = Class()`."""
    graph = graph_of(
        {
            "app.py": (
                "class Root:\n"
                "    def ping(self):\n"
                "        return 1\n"
                "\n"
                "class Leaf(Root):\n"
                "    def ping(self):\n"
                "        return super().ping()\n"
                "    def near(self):\n"
                "        return self.ping()\n"
                "    def named(self):\n"
                "        return Root.ping(self)\n"
                "    def built(self):\n"
                "        thing = Root()\n"
                "        return thing.ping()\n"
            )
        }
    )
    invokes = edges_of(graph, "INVOKES")
    assert ("INVOKES", 0.90, "via_inheritance", "app.py::Leaf.ping", "app.py::Root.ping") in invokes
    assert ("INVOKES", 1.00, "same_file", "app.py::Leaf.near", "app.py::Leaf.ping") in invokes
    assert ("INVOKES", 1.00, "same_file", "app.py::Leaf.named", "app.py::Root.ping") in invokes
    assert ("INVOKES", 1.00, "same_file", "app.py::Leaf.built", "app.py::Root.ping") in invokes
    assert ("INVOKES", 0.90, "mro", "app.py::Leaf.ping", "app.py::Root.ping") not in invokes
    assert ("OVERRIDES", 0.90, "mro", "app.py::Leaf.ping", "app.py::Root.ping") in edges_of(
        graph, "OVERRIDES"
    )


def test_python_inheritance_reaches_a_base_method_at_0_90():
    graph = graph_of(
        {
            "base.py": "class Root:\n    def ping(self):\n        return 1\n",
            "leaf.py": "from base import Root\n\nclass Leaf(Root):\n    def go(self):\n        return self.ping()\n",
        }
    )
    assert ("INVOKES", 0.90, "via_inheritance", "leaf.py::Leaf.go", "base.py::Root.ping") in edges_of(
        graph, "INVOKES"
    )


def test_python_fuzzy_and_no_edge_rows():
    """
    Unique bare name -> 0.50. Ambiguous, stoplisted, or a chain we cannot walk -> nothing.
    The chain row is what keeps the fuzzy rule from claiming `os.path.join`.
    """
    graph = graph_of(
        {
            "lib.py": (
                "class A:\n"
                "    def twin(self):\n"
                "        return 1\n"
                "    def get(self):\n"
                "        return 2\n"
                "class B:\n"
                "    def twin(self):\n"
                "        return 3\n"
                "class C:\n"
                "    def only(self):\n"
                "        return 4\n"
            ),
            "app.py": (
                "import os\n"
                "\n"
                "def use(x, y):\n"
                "    x.only()\n"
                "    x.twin()\n"
                "    y.get()\n"
                "    x.y.only()\n"
                "    return os.path.join('a', 'b')\n"
            ),
        }
    )
    invokes = edges_of(graph, "INVOKES")
    assert ("INVOKES", 0.50, "fuzzy_name", "app.py::use", "lib.py::C.only") in invokes
    assert not any(b.endswith(("::A.twin", "::B.twin", "::A.get")) for _, _, _, _, b in invokes)
    assert len(invokes) == 1  # the chain and os.path.join produce nothing
    assert graph.unresolved_calls["app.py"] == 4


def test_python_decorators():
    """A resolvable decorator is a call the decorated symbol makes; an unresolvable one is not."""
    graph = graph_of(
        {
            "deco.py": "def register(fn):\n    return fn\n",
            "app.py": (
                "from deco import register\n"
                "\n"
                "@register\n"
                "def used():\n"
                "    return 1\n"
                "\n"
                "@nope.thing('x')\n"
                "def other():\n"
                "    return 2\n"
            ),
        }
    )
    invokes = edges_of(graph, "INVOKES")
    assert ("INVOKES", 0.90, "via_import", "app.py::used", "deco.py::register") in invokes
    assert len(invokes) == 1
    # The decorator lines belong to the symbol they decorate: no line is orphaned.
    assert by_qualname(graph, "app.py", "used").line_start == 3
    assert by_qualname(graph, "app.py", "other").line_start == 7
    assert by_qualname(graph, "app.py", "app").header_end == 2


def test_python_inherits_fuzzy_and_dotted():
    """A bare base name that uniquely matches is 0.50; a dotted one resolves properly."""
    fuzzy = graph_of(
        {
            "lib.py": "class Special:\n    pass\n",
            "app.py": "class Thing(Special):\n    pass\n",
        }
    )
    assert ("INHERITS", 0.50, "fuzzy_name", "app.py::Thing", "lib.py::Special") in edges_of(fuzzy, "INHERITS")
    dotted = graph_of(
        {
            "models/__init__.py": "",
            "models/base.py": "class Model:\n    pass\n",
            "app.py": "import models.base\n\nclass Thing(models.base.Model):\n    pass\n",
        }
    )
    assert ("INHERITS", 0.90, "resolved", "app.py::Thing", "models/base.py::Model") in edges_of(
        dotted, "INHERITS"
    )


def test_python_imported_class_method_call_is_0_90():
    """2.2b's `Class.m()` row, imported half: the same call one file over is 0.90, not 1.00."""
    graph = graph_of(
        {
            "lib.py": "class Root:\n    def ping(self):\n        return 1\n",
            "app.py": "from lib import Root\n\ndef go():\n    return Root.ping(None)\n",
        }
    )
    assert ("INVOKES", 0.90, "via_import", "app.py::go", "lib.py::Root.ping") in edges_of(graph, "INVOKES")


def test_python_raises_and_catches():
    """In-repo exception classes get edges; builtins go on `Symbol.raises` and nowhere else."""
    graph = graph_of(
        {
            "errors.py": "class Boom(Exception):\n    pass\n",
            "app.py": (
                "from errors import Boom\n"
                "\n"
                "def go():\n"
                "    try:\n"
                "        raise Boom('x')\n"
                "    except Boom:\n"
                "        raise ValueError('y')\n"
            ),
        }
    )
    assert ("RAISES", 0.90, "resolved", "app.py::go", "errors.py::Boom") in edges_of(graph, "RAISES")
    assert ("CATCHES", 0.90, "resolved", "app.py::go", "errors.py::Boom") in edges_of(graph, "CATCHES")
    assert by_qualname(graph, "app.py", "go").raises == ["ValueError"]
    assert not any(b.endswith("::ValueError") for _, _, b in links(graph))


def test_python_tested_by_mention():
    """The third TESTED_BY provenance: a test function names a symbol it never calls."""
    graph = graph_of(
        {
            "lib.py": "DISTINCTIVE = 1\n\nclass Rarity:\n    pass\n",
            "tests/test_lib.py": "from lib import Rarity\n\ndef test_it():\n    assert Rarity\n",
        }
    )
    assert (
        "TESTED_BY",
        0.60,
        "test_mention",
        "lib.py::Rarity",
        "tests/test_lib.py::test_it",
    ) in edges_of(graph, "TESTED_BY")


# ---------------------------------------------------------- 2.2b: TypeScript


def test_typescript_import_forms():
    """Default import, named import, `require`, `export * from`, and a bare specifier."""
    graph = graph_of(
        {
            "src/base.ts": "export default class Widget {\n  go(): number { return 1; }\n}\n",
            "src/util.ts": "export function tidy(): number { return 2; }\n",
            "src/index.ts": "export * from './util';\nexport { tidy as neat } from './util';\n",
            "src/app.ts": (
                'import Widget from "./base";\n'
                'import { neat } from "./index";\n'
                'import react from "react";\n'
                'const legacy = require("./util");\n'
            ),
        }
    )
    imports = edges_of(graph, "IMPORTS")
    assert ("IMPORTS", 0.95, "import_path", "src/app.ts::src.app", "src/base.ts::Widget") in imports
    assert ("IMPORTS", 0.90, "reexport", "src/app.ts::src.app", "src/util.ts::tidy") in imports
    assert ("IMPORTS", 0.95, "import_path", "src/app.ts::src.app", "src/util.ts::src.util") in imports
    assert ("IMPORTS", 0.60, "wildcard", "src/index.ts::src.index", "src/util.ts::src.util") in imports
    assert not any("react" in b for _, _, b in links(graph, "IMPORTS"))


def test_typescript_js_extension_resolves_to_the_source():
    """`./b.js` is written for the runtime; `./b.ts` is what the repo holds."""
    graph = graph_of(
        {
            "src/b.ts": "export function go(): number { return 1; }\n",
            "src/a.ts": 'import { go } from "./b.js";\n',
        }
    )
    assert ("IMPORTS", 0.95, "import_path", "src/a.ts::src.a", "src/b.ts::go") in edges_of(graph, "IMPORTS")


def test_typescript_index_directory_import():
    graph = graph_of(
        {
            "src/thing/index.ts": "export function go(): number { return 1; }\n",
            "src/a.ts": 'import { go } from "./thing";\n',
        }
    )
    assert ("IMPORTS", 0.95, "import_path", "src/a.ts::src.a", "src/thing/index.ts::go") in edges_of(
        graph, "IMPORTS"
    )


def test_typescript_this_super_new_and_throw():
    graph = graph_of(
        {
            "src/base.ts": (
                "export class Widget {\n  go(): number { return 1; }\n}\nexport class Boom extends Error {}\n"
            ),
            "src/app.ts": (
                'import { Widget, Boom } from "./base";\n'
                "\n"
                "export class Child extends Widget {\n"
                "  go(): number { return super.go(); }\n"
                "  near(): number { return this.go(); }\n"
                "  boom(): void { throw new Boom(); }\n"
                "  make(): Widget { const w = new Widget(); return w; }\n"
                "}\n"
            ),
        }
    )
    invokes = edges_of(graph, "INVOKES")
    assert ("INVOKES", 0.90, "via_inheritance", "src/app.ts::Child.go", "src/base.ts::Widget.go") in invokes
    assert ("INVOKES", 1.00, "same_file", "src/app.ts::Child.near", "src/app.ts::Child.go") in invokes
    assert ("INVOKES", 0.90, "via_import", "src/app.ts::Child.make", "src/base.ts::Widget") in invokes
    assert ("INHERITS", 0.90, "resolved", "src/app.ts::Child", "src/base.ts::Widget") in edges_of(
        graph, "INHERITS"
    )
    assert ("RAISES", 0.90, "resolved", "src/app.ts::Child.boom", "src/base.ts::Boom") in edges_of(
        graph, "RAISES"
    )
    # `extends Error` is a builtin base, and `throw new Boom()` is not also a call to Boom.
    assert not any(b.endswith("::Error") for _, _, b in links(graph, "INHERITS"))
    assert ("INVOKES", "src/app.ts::Child.boom", "src/base.ts::Boom") not in links(graph)


def test_typescript_this_reaches_a_resolved_base_at_0_90():
    """`this.m()` where `m` lives on the base, not on this class: 0.90 `via_inheritance`."""
    graph = graph_of(
        {
            "src/base.ts": "export class Widget {\n  go(): number { return 1; }\n}\n",
            "src/app.ts": (
                'import { Widget } from "./base";\n'
                "\n"
                "export class Child extends Widget {\n"
                "  near(): number { return this.go(); }\n"
                "}\n"
            ),
        }
    )
    assert ("INVOKES", 0.90, "via_inheritance", "src/app.ts::Child.near", "src/base.ts::Widget.go") in (
        edges_of(graph, "INVOKES")
    )


def test_typescript_extends_a_unique_bare_name_is_0_50():
    """2.2b's `extends B` fuzzy half: nothing imported `Special`, but only one class is called that."""
    graph = graph_of(
        {
            "src/lib.ts": "export class Special {\n  go(): number { return 1; }\n}\n",
            "src/app.ts": "export class Thing extends Special {}\n",
        }
    )
    assert ("INHERITS", 0.50, "fuzzy_name", "src/app.ts::Thing", "src/lib.ts::Special") in edges_of(
        graph, "INHERITS"
    )


def test_typescript_catch_needs_an_instanceof():
    """A bare `catch (e)` says nothing about the type, so 2.2b gives it no edge."""
    graph = graph_of(
        {
            "src/base.ts": "export class Boom extends Error {}\n",
            "src/app.ts": (
                'import { Boom } from "./base";\n'
                "\n"
                "export function guard(): void {\n"
                "  try { go(); } catch (e) { if (e instanceof Boom) { return; } }\n"
                "}\n"
                "export function loose(): void {\n"
                "  try { go(); } catch (e) { return; }\n"
                "}\n"
            ),
        }
    )
    catches = edges_of(graph, "CATCHES")
    assert ("CATCHES", 0.90, "resolved", "src/app.ts::guard", "src/base.ts::Boom") in catches
    assert len(catches) == 1


def test_typescript_arrow_is_a_symbol_but_a_callback_is_not():
    """2.2a: an arrow bound to a module-scope const is named by its binding; nothing else is."""
    graph = graph_of(
        {
            "src/a.ts": (
                "export const compute = (o: number): number => { return o; };\n"
                "export interface Shape { x: number }\n"
                "export type Alias = number;\n"
                "export enum Colour { Red }\n"
                "const plain = 1;\n"
                "[1, 2].map((n) => n + 1);\n"
            )
        }
    )
    assert [s.qualname for s in graph.symbols] == ["src.a", "compute"]


# ------------------------------------------------------------- the classifier


def test_classify_literal_checks_cypher_before_sql():
    """`MERGE (s:Settings ...)` opens with a keyword SQL also has; the pattern decides."""
    hits = classify_literal("MERGE (s:Settings {id: 1}) SET s.value = 2")
    assert [(h.kind, h.qualname, h.access, h.provenance) for h in hits] == [
        ("label", "Settings", "WRITES", "cypher_literal")
    ]


def test_cypher_objects():
    hits = cypher_objects("MATCH (o:Order)-[:PLACED_BY]->(c:Customer) RETURN c")
    assert [(h.kind, h.qualname) for h in hits] == [
        ("label", "Order"),
        ("label", "Customer"),
        ("rel_type", "PLACED_BY"),
    ]
    assert all(h.access == "READS" and h.dialect == "cypher" for h in hits)
    assert cypher_objects("just some prose about a (thing)") == []


def test_sql_tables_reads_and_writes():
    assert [(h.qualname, h.access) for h in sql_tables("SELECT id FROM orders")] == [("orders", "READS")]
    assert [(h.qualname, h.access) for h in sql_tables("INSERT INTO orders (id) VALUES (1)")] == [
        ("orders", "WRITES")
    ]
    assert [(h.qualname, h.access) for h in sql_tables("UPDATE orders SET total = 1")] == [
        ("orders", "WRITES")
    ]


def test_sql_is_only_tried_on_a_real_statement_head():
    """Otherwise sqlglot turns prose into tables: "Create, edit and remove users." is not DDL."""
    for prose in (
        "Create, edit and remove users whose role ranks below their own.",
        "Select a source from the list.",
        "sending",
        "orders",
        "Place an order: total it with billing, send the invoice and log the path.",
    ):
        assert classify_literal(prose) == [], prose


def test_read_sql_file_gives_tables_columns_and_lines():
    hits = read_sql_file((CODE_SAMPLE_PATH / "schema" / "orders.sql").read_text())
    assert [(h.kind, h.qualname, h.line) for h in hits] == [
        ("table", "orders", 1),
        ("column", "orders.id", 1),
        ("column", "orders.total", 1),
        ("column", "orders.status", 1),
        ("table", "customers", 2),
        ("column", "customers.id", 2),
        ("column", "customers.name", 2),
    ]


def test_mongo_and_mongoose_hits():
    hit = mongo_hit("db.archive_orders", "insert_one", 35)
    assert (hit.kind, hit.qualname, hit.access, hit.provenance) == (
        "collection",
        "archive_orders",
        "WRITES",
        "mongo_chain",
    )
    assert mongo_hit("db.orders", "find").access == "READS"
    assert mongo_hit("orders", "find") is None  # a bare receiver invents a collection
    assert mongo_hit("db.orders", "sprinkle") is None
    assert mongoose_hit("Order", "find").provenance == "mongoose_model"
    assert mongoose_hit("Order", "sprinkle") is None


def test_mongo_names_the_pascalcase_drivers_use():
    """
    The Go driver and `MongoDB.Driver` spell the same methods in PascalCase, and C# adds
    `Async`. One name set, with the ceremony stripped before the lookup.
    """
    assert mongo_hit("db.orders", "InsertOne").access == "WRITES"
    assert mongo_hit("db.orders", "FindAsync").access == "READS"
    assert mongo_hit("db.orders", "InsertOneAsync").access == "WRITES"
    assert mongoose_hit("Order", "CountDocuments").access == "READS"
    assert mongo_hit("db.orders", "SprinkleAsync") is None


def test_a_collection_call_names_the_collection():
    """
    Go, C# and Rust reach a collection through a *call*, not an attribute; the string
    argument is the collection name. An ordinary `a.b()` chain still names nothing.
    """
    for chain in (
        'client.Database("app").Collection("archive_orders")',
        '_db.GetCollection<Order>("archive_orders")',
        'db.collection::<Order>("archive_orders")',
        'client.get_collection("archive_orders")',
    ):
        hit = mongo_hit(chain, "InsertOne", 12)
        assert hit is not None, chain
        assert (hit.kind, hit.qualname, hit.access) == ("collection", "archive_orders", "WRITES"), chain
    assert mongo_hit("service.repository()", "InsertOne") is None
    assert mongo_hit("client.Collection(name)", "InsertOne") is None  # not a literal: no name


# ---------------------------------------------------- properties and budgets


def test_extraction_is_deterministic(fixture_graph):
    """
    Two runs over the same tree give the same graph: same ids, same ω, same order. This is
    what lets `expected.json` be a checked-in spec (`community` is not set here -- Leiden is
    the indexer's, and S2.10 excludes it from the comparison there).
    """
    again = extract_code(code_sample_docs(), "fixture")

    def snapshot(graph):
        return (
            [
                (s.id, s.kind, s.qualname, s.path, s.line_start, s.line_end, tuple(s.raises), s.display)
                for s in graph.symbols
            ],
            [(d.id, d.kind, d.qualname, tuple(d.mentions)) for d in graph.data_objects],
            [
                (e.a, e.b, e.kind, e.omega, e.provenance, json.dumps(e.extra, sort_keys=True))
                for e in graph.edges
            ],
            graph.stats(),
        )

    assert snapshot(fixture_graph) == snapshot(again)


def test_self_smoke_over_the_hippo_source_is_fast():
    """`extract_code` over `src/hippo` finishes well inside 5 s and finds a real graph."""
    docs = []
    for path in sorted(SRC.rglob("*")):
        if not path.is_file() or any(part in readers.IGNORED_DIRS for part in path.parts):
            continue
        name = path.relative_to(SRC.parent).as_posix()
        if readers.lang_of(name) is None:
            continue
        docs.append(Doc(name, path.read_text(errors="replace"), name, True))

    started = time.perf_counter()
    graph = extract_code(docs, "self")
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"extraction took {elapsed:.2f}s"
    stats = graph.stats()
    assert stats["symbols"] > 300 and stats["edges"] > 300
    assert stats["edges_by_kind"]["INVOKES"] > 100
    # Our own code graph must find the thing this work package is about.
    assert any(s.qualname == "extract_code" for s in graph.symbols)


def test_stats_shape(fixture_graph):
    """The dict that becomes `Source.meta["code"]`. JSON-safe and ordered (D15's counter)."""
    stats = fixture_graph.stats()
    assert set(stats) == {
        "symbols",
        "languages",  # WP4a: the status page's Code card reads this out of Source.meta["code"]
        "data_objects",
        "edges",
        "edges_by_kind",
        "files_parsed",
        "files_skipped",
        "unresolved_calls",
        "unresolved_calls_total",
        "truncated",
        "commits",
        "modifies",
        "history_skipped",
    }
    assert stats["symbols"] == 30
    assert stats["files_parsed"] == 10
    assert stats["files_skipped"] == {"parse_error": 0, "too_big": 0, "unsupported": 1}  # tools/build.go
    assert stats["unresolved_calls"]["pyapp/orders.py"] == 2  # os.path.join and print
    assert stats["truncated"] is False
    # An archive has no history to read, so the three history counts are zero rather than absent:
    # `meta["code"]` has one shape whatever the source kind, and 0 commits is a fact about it.
    assert (stats["commits"], stats["modifies"], stats["history_skipped"]) == (0, 0, 0)
    assert json.loads(json.dumps(stats)) == stats


def test_history_is_carried_on_the_graph_for_the_indexer_to_write():
    """
    `read_history` fills these; `extract_code` never does. They live on `CodeGraph` because the
    indexer writes one object, and because `stats()` is what tells a user their history was cut
    short (`history_skipped`) rather than their repository being small.
    """
    graph = graph_of({"a.py": "def one():\n    return 1\n"})
    assert (graph.commits, graph.modifies, graph.precedes, graph.history_skipped) == ([], [], [], 0)

    graph.commits = [{"id": "commit-1", "sha": "abc", "ordinal": 0}]
    graph.modifies = [{"commit_id": "commit-1", "symbol_id": "symbol-1", "omega": 1.0, "hunk": {}}]
    graph.precedes = [("commit-1", "commit-2")]
    graph.history_skipped = 4
    stats = graph.stats()
    assert (stats["commits"], stats["modifies"], stats["history_skipped"]) == (1, 1, 4)
    assert json.loads(json.dumps(stats)) == stats


def test_unparsed_and_oversized_files_are_recorded_not_fatal():
    """A bad file costs its own symbols and nothing else; the chunker keeps line windows for it."""
    graph = graph_of(
        {
            "good.py": "def fine():\n    return 1\n",
            "broken.py": "def (:\n",
            "huge.py": "x = 1\n" * (CODE_MAX_FILE_BYTES // 3),
            "tool.go": "package main\n\nfunc main() {}\n",
        }
    )
    assert graph.files_skipped == {
        "broken.py": "parse_error",
        "huge.py": "too_big",
        "tool.go": "unsupported",
    }
    assert graph.files_parsed == ["good.py"]
    assert graph.parsed("good.py") and not graph.parsed("broken.py")
    assert [s.qualname for s in graph.symbols] == ["good", "fine"]


def test_a_tolerable_syntax_error_still_yields_its_symbols():
    """tree-sitter parses tolerantly; a file with a stray error and real symbols is still worth it."""
    graph = graph_of({"messy.py": "def fine():\n    return 1\n\n???\n"})
    assert graph.files_skipped == {}
    assert "fine" in [s.qualname for s in graph.symbols]


def test_should_stop_returns_a_partial_graph():
    """2.2c: cancellation is checked between files, so a large repo stays cancellable."""
    seen = []

    def stop():
        seen.append(1)
        return len(seen) > 2

    graph = extract_code(
        [Doc(f"m{i}.py", f"def f{i}():\n    return {i}\n", f"m{i}.py") for i in range(10)],
        "s",
        should_stop=stop,
    )
    assert graph.truncated is True
    assert len(graph.files_parsed) == 2


def test_prose_files_are_not_counted_as_skipped_code():
    """A README is not code we failed to parse; it is simply not our business."""
    graph = extract_code([Doc("README.md", "# hello\n", "README.md", is_code=False)], "s")
    assert graph.files_skipped == {}
    assert graph.stats()["files_parsed"] == 0


def test_a_zip_root_folder_does_not_break_absolute_imports():
    """
    `read_zip` titles members with the archive's own root folder, so a downloaded repo's
    `pyapp/store.py` arrives as `myrepo-main/pyapp/store.py`. Every absolute import must
    still resolve, or a zipped source would have almost no edges.
    """
    docs = [
        Doc(f"myrepo-main/{d.title}", d.text, f"myrepo-main/{d.title}", d.is_code) for d in code_sample_docs()
    ]
    graph = extract_code(docs, "s")
    imports = links(graph, "IMPORTS")
    assert (
        "IMPORTS",
        "myrepo-main/pyapp/orders.py::myrepo-main.pyapp.orders",
        "myrepo-main/pyapp/store.py::Base",
    ) in imports
    assert len(graph.edges) == len(EXPECTED["edges"])


def test_codegraph_imports_only_what_the_dependency_direction_allows():
    """
    `ingest.chunker` imports `codegraph.model`, so this package must never import `ingest`,
    the store, or anything from `hipporag` except `text` (PLAN.md's package layout).
    """
    banned = ("ingest", "store", "web", "analysis", "evals", "ollama", "context", "config")
    for module in sorted((SRC / "codegraph").glob("*.py")):
        for line in module.read_text().splitlines():
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            assert "hipporag" not in stripped or "hipporag.text" in stripped, f"{module.name}: {line}"
            for name in banned:
                assert f"..{name}" not in stripped and f"hippo.{name}" not in stripped, (
                    f"{module.name}: {line}"
                )
