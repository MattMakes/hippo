"""
The Go walker: `src/hippo/codegraph/go.py`.

Pure tests -- no store, no Ollama, no pipeline, and no fixture tree either. Every tree here
is written inline, the way `test_codegraph.py` covers the resolver rows the shared fixture
lacks, so the line numbers and edges a test asserts are visible in the same screen as the
assertion.

`GOAPP` is the "order service" story the `pyapp`/`tsapp` fixtures tell, in Go: a `billing`
package, a `store` package with the type everything embeds, an `orders` package split over
three files (so the same-package tier has something to resolve), a `_test.go` beside it and
a `cmd/main.go` above it. The rows it cannot reach -- a repository with no `go.mod`, two
directories that both say `package main`, an interface, a type alias -- get their own small
trees.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from hippo.codegraph import extract_code
from hippo.codegraph.go import RULES_ENTRY, package_dir, source_setup
from hippo.codegraph.languages import PARSED_LANGS, RULES

# --------------------------------------------------------------------- helpers


@dataclass
class Doc:
    """A stand-in `Document`. The same three fields `extract_code` reads."""

    title: str
    text: str
    path: str = ""
    is_code: bool = True


def graph_of(files: dict[str, str], source_id: str = "s"):
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
    """Just `(kind, a, b)` -- for the "no edge" rows, where ω is beside the point."""
    return {(k, a, b) for k, _, _, a, b in edges_of(graph, kind)}


def edge(graph, kind: str, a: str, b: str):
    found = [e for e in edges_of(graph, kind) if e[3] == a and e[4] == b]
    assert len(found) == 1, f"expected exactly one {kind} {a} -> {b}, found {found}"
    return found[0]


def extra_of(graph, kind: str, a: str, b: str) -> dict:
    """The `extra` of the one edge between two nodes -- `call_line`, `in_branch`, bindings."""
    names = {s.id: f"{s.path}::{s.qualname}" for s in graph.symbols}
    found = [e for e in graph.edges if e.kind == kind and names.get(e.a) == a and names.get(e.b) == b]
    assert len(found) == 1, f"expected exactly one {kind} {a} -> {b}, found {found}"
    return found[0].extra


def symbol(graph, path: str, qualname: str):
    return next(s for s in graph.symbols if s.path == path and s.qualname == qualname)


# ------------------------------------------------------------------ the tree

GOAPP = {
    "goapp/go.mod": "module example.com/goapp\n\ngo 1.22\n",
    "goapp/store/base.go": """package store

// Base is the logger every service embeds.
//
// This paragraph is the detail, and is not the doc.
type Base struct{}

// Log writes a message and hands it back.
func (b *Base) Log(msg string) string { return msg }

type OrderError struct{}
""",
    "goapp/billing/billing.go": """package billing

// Total prices an order.
func Total(o Order) int { return 1 }

func SendInvoice(o Order) {}
""",
    "goapp/orders/order.go": """package orders

// Order is one placed order.
type Order struct{}

// Validate says whether an order may be placed.
func Validate(o Order) bool { return true }
""",
    "goapp/orders/service.go": """package orders

import (
	"database/sql"
	"fmt"

	bill "example.com/goapp/billing"
	"example.com/goapp/store"
)

// Service keeps orders. Acme Robotics is headquartered in Boulder.
type Service struct {
	store.Base
	db *sql.DB
}

// Place records an order and returns its total.
func (s *Service) Place(o Order) int {
	amt := bill.Total(o)
	if amt > 0 {
		bill.SendInvoice(o)
	}
	s.Log("x")
	Validate(o)
	fmt.Errorf("no total")
	return amt
}

// Log records a line against this service.
func (s *Service) Log(msg string) string { return msg }

func (s *Service) ListOpen() {
	s.db.Query("SELECT id, total FROM orders WHERE status = 'open'")
}

func (s *Service) Archive(o Order) {
	coll := client.Database("app").Collection("archive_orders")
	coll.InsertOne(ctx, o)
}

func (s *Service) Graph() {
	session.Run(`MATCH (o:Order)-[:PLACED_BY]->(c:Customer) RETURN c`, nil)
}

func panicking() { panic("nope") }
""",
    "goapp/orders/service_test.go": """package orders

import "testing"

// TestPlace places one order.
func TestPlace(t *testing.T) { (&Service{}).Place(Order{}) }

func BenchmarkPlace(b *testing.B) { Validate(Order{}) }
""",
    "goapp/cmd/main.go": """package main

import "example.com/goapp/orders"

func main() {
	s := orders.Service{}
	s.Place(orders.Order{})
}
""",
}

SERVICE = "goapp/orders/service.go"
ORDER = "goapp/orders/order.go"
BASE = "goapp/store/base.go"
BILLING = "goapp/billing/billing.go"
TEST = "goapp/orders/service_test.go"
MAIN = "goapp/cmd/main.go"


@pytest.fixture(scope="module")
def goapp():
    return graph_of(GOAPP)


# ------------------------------------------------------------- registration


def test_go_is_registered_with_a_walker():
    """
    Registering the walker is the whole job: `extract.WALKERS` and `PARSED_LANGS` are both
    derived from `RULES`, so `.go` files parse and git hunks in them produce MODIFIES.
    """
    assert RULES["go"] is RULES_ENTRY
    assert RULES["go"].walk is not None
    assert "go" in PARSED_LANGS
    assert RULES["go"].line_comment == "//"


def test_the_shared_name_rules_are_gos_conventions():
    """
    `module_qualname`, `is_test_path` and `test_stem` are the defaults on purpose --
    `service_test.go` is test code named after `service`, and a module keeps the `main` and
    `_test` its file name carries, which is exactly what the shared rules already do.
    """
    rules = RULES["go"]
    assert rules.module_qualname("goapp/cmd/main.go") == "goapp.cmd.main"
    assert rules.module_qualname("goapp/orders/service_test.go") == "goapp.orders.service_test"
    assert rules.is_test_path("goapp/orders/service_test.go") is True
    assert rules.is_test_path("goapp/orders/service.go") is False
    assert rules.test_stem("goapp/orders/service_test.go") == "service"
    assert rules.test_stem("goapp/orders/service.go") is None


def test_a_test_function_is_what_go_test_runs():
    """`go test` runs `TestX`, `BenchmarkX` and `ExampleX`; the shared `test_*` rule is
    lowercase and would have called every one of them ordinary code."""
    from hippo.codegraph.model import Symbol

    for name, expected in (
        ("TestPlace", True),
        ("BenchmarkPlace", True),
        ("ExamplePlace", True),
        ("Place", False),
        ("testPlace", False),
    ):
        assert RULES_ENTRY.is_test_function(Symbol(name=name, kind="function")) is expected
    assert RULES_ENTRY.is_test_function(Symbol(name="TestPlace", kind="class")) is False


# ----------------------------------------------------------------- symbols


def test_the_symbols_of_a_file_with_their_kinds_and_line_ranges(goapp):
    """
    A module, every type that has a body, every func and every method -- and nothing else.
    A method is `Receiver.Name`, so the resolver's member table finds it exactly as it finds
    a Python method, even though Go writes it outside the type.
    """
    found = [(s.qualname, s.kind, s.line_start, s.line_end) for s in goapp.by_path(SERVICE)]
    assert found == [
        ("goapp.orders.service", "module", 1, 45),
        ("Service", "class", 12, 15),
        ("Service.Place", "method", 18, 27),
        ("Service.Log", "method", 30, 30),
        ("Service.ListOpen", "method", 32, 34),
        ("Service.Archive", "method", 36, 39),
        ("Service.Graph", "method", 41, 43),
        ("panicking", "function", 45, 45),
    ]
    assert [(s.qualname, s.kind) for s in goapp.by_path(BASE)] == [
        ("goapp.store.base", "module"),
        ("Base", "class"),
        ("Base.Log", "method"),
        ("OrderError", "class"),
    ]


def test_signatures_stop_at_the_body(goapp):
    """The declaration, whitespace collapsed: what a container's placeholder line shows."""
    assert symbol(goapp, SERVICE, "Service.Place").signature == "func (s *Service) Place(o Order) int"
    assert symbol(goapp, SERVICE, "Service").signature == "type Service struct"
    assert symbol(goapp, BASE, "Base.Log").signature == "func (b *Base) Log(msg string) string"
    assert symbol(goapp, BILLING, "Total").signature == "func Total(o Order) int"


def test_the_doc_is_the_comment_run_above_the_declaration(goapp):
    """
    Go's doc comment is the `//` run immediately above a declaration, and its first
    paragraph is the summary -- a bare `//` line ends it, exactly as `go doc` reads it.
    """
    assert symbol(goapp, SERVICE, "Service").doc == (
        "Service keeps orders. Acme Robotics is headquartered in Boulder."
    )
    assert symbol(goapp, BASE, "Base").doc == "Base is the logger every service embeds."
    assert symbol(goapp, SERVICE, "Service.Place").doc == "Place records an order and returns its total."
    assert symbol(goapp, BILLING, "SendInvoice").doc == ""  # no comment above it at all


def test_a_methods_receiver_is_recorded_as_self(goapp):
    """
    `params` feeds the INVOKES `arg_binding`, which drops a first parameter only when it is
    one of the language's `self_names`. A Go receiver is spelled differently in every method
    (`s`, `b`, `svc`), so the walker records it as `self` and the bodies rewrite it to
    `self` too -- the two halves of the contract agree or every binding is off by one.
    """
    assert symbol(goapp, SERVICE, "Service.Place").params == ["self", "o"]
    assert symbol(goapp, BASE, "Base.Log").params == ["self", "msg"]
    assert symbol(goapp, BILLING, "Total").params == ["o"]


def test_a_test_file_marks_every_symbol_in_it(goapp):
    assert [s.is_test for s in goapp.by_path(TEST)] == [True, True, True]
    assert [s.is_test for s in goapp.by_path(SERVICE)] == [False] * 8


def test_a_go_type_has_no_members_inside_it(goapp):
    """
    A type declaration's header passage is the whole declaration: its methods are top-level
    declarations elsewhere in the file, so there is nothing inside it to stop before.
    """
    service = symbol(goapp, SERVICE, "Service")
    assert (service.line_start, service.header_end) == (12, 15)
    module = symbol(goapp, SERVICE, "goapp.orders.service")
    assert module.header_end == 11  # everything before the first declaration
    assert symbol(goapp, SERVICE, "Service.Place").statement_lines == [19, 20, 23, 24, 25, 26]


def test_an_interface_is_a_class_and_its_method_signatures_are_not_symbols():
    """
    An interface has no bodies to show, so its methods stay in its header passage. Go
    interface satisfaction is implicit and gets no edge at all (add_langs.md, Step 1).
    """
    graph = graph_of(
        {
            "app/store.go": "package store\n\ntype Reader interface {\n\tRead() int\n}\n",
            "app/file.go": "package store\n\ntype File struct{}\n\nfunc (f *File) Read() int { return 1 }\n",
        }
    )
    assert [(s.qualname, s.kind) for s in graph.by_path("app/store.go")] == [
        ("app.store", "module"),
        ("Reader", "class"),
    ]
    assert not [e for e in graph.edges if e.kind == "INHERITS"]
    # An interface holds its `method_elem`s with no list node around them, unlike a struct's
    # fields -- so both the signature and the split points have to look past that.
    reader = symbol(graph, "app/store.go", "Reader")
    assert (reader.signature, reader.statement_lines) == ("type Reader interface", [4])
    file_type = symbol(graph, "app/file.go", "File")
    assert (file_type.signature, file_type.statement_lines) == ("type File struct", [])


def test_a_type_alias_and_a_defined_type_are_no_symbol_but_a_grouped_declaration_is():
    """Only a `struct` or an `interface` has a body worth a passage of its own."""
    graph = graph_of(
        {
            "app/types.go": (
                "package app\n\ntype ID int\n\ntype Alias = Order\n\n"
                "type (\n\tOrder struct{ total int }\n\tLister interface{ List() }\n)\n"
            )
        }
    )
    assert [(s.qualname, s.kind, s.line_start) for s in graph.symbols] == [
        ("app.types", "module", 1),
        ("Order", "class", 8),
        ("Lister", "class", 9),
    ]


# ------------------------------------------------------------------- edges


def test_contains_comes_straight_from_the_syntax(goapp):
    """A module holds its types and funcs; a type holds the methods declared on it."""
    assert links(goapp, "CONTAINS") >= {
        ("CONTAINS", f"{SERVICE}::goapp.orders.service", f"{SERVICE}::Service"),
        ("CONTAINS", f"{SERVICE}::goapp.orders.service", f"{SERVICE}::panicking"),
        ("CONTAINS", f"{SERVICE}::Service", f"{SERVICE}::Service.Place"),
        ("CONTAINS", f"{BASE}::Base", f"{BASE}::Base.Log"),
    }
    assert all(e[1] == 1.00 and e[2] == "syntax" for e in edges_of(goapp, "CONTAINS"))


def test_an_import_names_a_package_and_the_edge_goes_to_its_first_file(goapp):
    """
    `import "example.com/goapp/billing"` is resolved through `go.mod` to the directory
    `goapp/billing`. The IMPORTS edge goes to the first file of that package by path, so two
    runs name the same module symbol.
    """
    assert edges_of(goapp, "IMPORTS") == {
        (
            "IMPORTS",
            0.95,
            "import_path",
            f"{SERVICE}::goapp.orders.service",
            f"{BILLING}::goapp.billing.billing",
        ),
        ("IMPORTS", 0.95, "import_path", f"{SERVICE}::goapp.orders.service", f"{BASE}::goapp.store.base"),
        ("IMPORTS", 0.95, "import_path", f"{MAIN}::goapp.cmd.main", f"{ORDER}::goapp.orders.order"),
    }


def test_embedding_is_inheritance(goapp):
    """
    `struct { store.Base }` promotes `Base`'s methods, so it is INHERITS at 0.90 `resolved`
    -- and `Service.Log` shadowing `Base.Log` is an override found through it.
    """
    assert edge(goapp, "INHERITS", f"{SERVICE}::Service", f"{BASE}::Base")[1:3] == (0.90, "resolved")
    assert edge(goapp, "OVERRIDES", f"{SERVICE}::Service.Log", f"{BASE}::Base.Log")[1:3] == (0.90, "mro")


def test_the_three_invokes_tiers(goapp):
    """
    Same file 1.00 `same_file`; same package, other file, no import at all, 1.00
    `same_scope`; through an import 0.90 `via_import`. The middle one is what a Go package
    *is*, and 0.90 would understate it.
    """
    assert edge(goapp, "INVOKES", f"{SERVICE}::Service.Place", f"{SERVICE}::Service.Log")[1:3] == (
        1.00,
        "same_file",
    )
    assert edge(goapp, "INVOKES", f"{SERVICE}::Service.Place", f"{ORDER}::Validate")[1:3] == (
        1.00,
        "same_scope",
    )
    assert edge(goapp, "INVOKES", f"{SERVICE}::Service.Place", f"{BILLING}::Total")[1:3] == (
        0.90,
        "via_import",
    )


def test_a_call_through_an_alias_and_on_a_composite_literal(goapp):
    """
    `bill "example.com/goapp/billing"` binds `bill`, and `(&Service{}).Place(...)` /
    `orders.Service{}` are calls on the type they construct -- Go's way of writing what
    another language spells `new Service().place()`.

    The tier is the distance, for a method as much as for a bare name: the `_test.go` file
    is in `Service`'s own package and reaches its method at `same_scope` 1.00, while
    `cmd/main.go` is another package and pays the 0.90 an import costs.
    """
    assert edge(goapp, "INVOKES", f"{SERVICE}::Service.Place", f"{BILLING}::SendInvoice")[1:3] == (
        0.90,
        "via_import",
    )
    assert edge(goapp, "INVOKES", f"{TEST}::TestPlace", f"{SERVICE}::Service.Place")[1:3] == (
        1.00,
        "same_scope",
    )
    assert edge(goapp, "INVOKES", f"{MAIN}::main", f"{SERVICE}::Service.Place")[1:3] == (0.90, "via_import")


def test_the_invokes_extra_carries_the_call_site(goapp):
    """`in_branch` for the call inside the `if`, and the callee's parameters bound to the
    caller's argument expressions -- with the receiver dropped, which is what `self` buys."""
    assert extra_of(goapp, "INVOKES", f"{SERVICE}::Service.Place", f"{SERVICE}::Service.Log") == {
        "call_line": 23,
        "in_branch": False,
        "is_await": False,
        "arg_binding": {"msg": '"x"'},
    }
    assert extra_of(goapp, "INVOKES", f"{SERVICE}::Service.Place", f"{BILLING}::SendInvoice") == {
        "call_line": 21,
        "in_branch": True,
        "is_await": False,
        "arg_binding": {"o": "o"},
    }


def test_go_and_defer_are_calls_like_any_other():
    """Neither is an await, and both are as much a dependency of the caller as a plain call."""
    graph = graph_of(
        {
            "app/a.go": (
                "package app\n\nfunc notify() {}\n\nfunc closeUp() {}\n\n"
                "func Place() {\n\tgo notify()\n\tdefer closeUp()\n}\n"
            )
        }
    )
    for callee, line in (("notify", 8), ("closeUp", 9)):
        found = extra_of(graph, "INVOKES", "app/a.go::Place", f"app/a.go::{callee}")
        assert found["call_line"] == line
        assert found["is_await"] is False


def test_the_fuzzy_rule_is_the_last_resort():
    """
    An unknown receiver with exactly one candidate of that name in the source is 0.50
    `fuzzy_name`; two candidates are no edge at all.
    """
    one = graph_of(
        {
            "app/a.go": "package app\n\ntype T struct{}\n\nfunc (t *T) Frobnicate() {}\n",
            "app/b.go": "package other\n\nfunc Run(x Thing) { x.Frobnicate() }\n",
        }
    )
    assert edge(one, "INVOKES", "app/b.go::Run", "app/a.go::T.Frobnicate")[1:3] == (0.50, "fuzzy_name")

    two = graph_of(
        {
            "app/a.go": "package app\n\ntype T struct{}\n\nfunc (t *T) Frobnicate() {}\n",
            "app/c.go": "package app\n\ntype U struct{}\n\nfunc (u *U) Frobnicate() {}\n",
            "app/b.go": "package other\n\nfunc Run(x Thing) { x.Frobnicate() }\n",
        }
    )
    assert not [e for e in two.edges if e.kind == "INVOKES"]

    # And a name everybody uses is refused however it is capitalised: `FUZZY_STOPLIST` is
    # written in lower case and matched in lower case, so Go's `Close` is Python's `close`.
    common = graph_of(
        {
            "app/a.go": "package app\n\ntype T struct{}\n\nfunc (t *T) Close() {}\n",
            "app/b.go": "package other\n\nfunc Run(x Thing) { x.Close() }\n",
        }
    )
    assert edges_of(common, "INVOKES") == set()


# --------------------------------------------------------------- no edge


def test_the_rows_that_must_produce_no_edge(goapp):
    """
    Positive assertions, every one of them a decision: the standard library and a third
    party are not part of this source (`fmt.Errorf`), `panic` is an ordinary unresolved call
    and never a RAISES edge, and an unresolvable chain (`s.db.Query`) is not ours to guess
    at -- the SQL inside it is still read, because a literal needs no receiver.
    """
    invokes = {(a, b) for _, a, b in links(goapp, "INVOKES")}
    assert not [b for a, b in invokes if a == f"{SERVICE}::panicking"]
    assert not [e for e in goapp.edges if e.kind in ("RAISES", "CATCHES")]
    assert symbol(goapp, SERVICE, "panicking").raises == []
    assert (f"{SERVICE}::Service.ListOpen", f"{SERVICE}::Service.Log") not in invokes
    # `fmt` and `database/sql` are dependencies, not files of this source: no IMPORTS row.
    assert len(edges_of(goapp, "IMPORTS")) == 3
    # Errorf, Database, Collection, db.Query, session.Run, panic -- counted, never guessed at.
    assert goapp.unresolved_calls[SERVICE] == 6


def test_a_third_party_package_that_shares_a_name_with_a_local_one_resolves_to_nothing():
    """
    The directory fallback needs two trailing segments to agree, so `github.com/other/
    billing` never claims the repository's own `billing/`, and no single-segment standard
    library path (`fmt`, `errors`) resolves at all: no IMPORTS edge, and the call it carries
    falls all the way through to the 0.50 `fuzzy_name` guess every language's unknown
    receiver gets -- never the 0.90 `via_import` an import would have earned.
    """
    graph = graph_of(
        {
            "myrepo-main/goapp/billing/billing.go": "package billing\n\nfunc Total() int { return 1 }\n",
            "myrepo-main/goapp/orders/service.go": (
                'package orders\n\nimport (\n\t"fmt"\n\t"errors"\n\t"github.com/other/billing"\n)\n\n'
                'func Place() error { fmt.Errorf("x"); return errors.New(billing.Total()) }\n'
            ),
        }
    )
    assert edges_of(graph, "IMPORTS") == set()
    assert edges_of(graph, "INVOKES") == {
        (
            "INVOKES",
            0.50,
            "fuzzy_name",
            "myrepo-main/goapp/orders/service.go::Place",
            "myrepo-main/goapp/billing/billing.go::Total",
        )
    }


# ------------------------------------------------------------ the resolution


def test_go_mod_says_which_directory_an_import_path_names():
    """
    `source_setup` runs once per source over the raw documents -- `go.mod` is not a file any
    walker parses -- and turns `module example.com/goapp` into "the directory `goapp`".
    """
    docs = [Doc("goapp/go.mod", "module example.com/goapp\n\ngo 1.22\n"), Doc("a/b.go", "package b\n")]
    assert source_setup(docs) == {"example.com/goapp": "goapp"}
    assert source_setup([Doc("notes.md", "module nothing\n")]) == {}
    assert source_setup([Doc("go.mod", "module solo\n")]) == {"solo": ""}


def test_an_import_resolves_without_a_go_mod_by_directory_suffix():
    """
    A downloaded zip arrives under its own root folder (`myrepo-main/goapp/billing`), so an
    import path can only ever be a *suffix* match on a directory. The longest run of shared
    trailing segments wins, and an ambiguous one resolves to nothing.
    """
    graph = graph_of(
        {
            "myrepo-main/goapp/billing/billing.go": "package billing\n\nfunc Total() int { return 1 }\n",
            "myrepo-main/goapp/orders/service.go": (
                'package orders\n\nimport "example.com/goapp/billing"\n\n'
                "func Place() int { return billing.Total() }\n"
            ),
        }
    )
    assert edge(
        graph,
        "INVOKES",
        "myrepo-main/goapp/orders/service.go::Place",
        "myrepo-main/goapp/billing/billing.go::Total",
    )[1:3] == (0.90, "via_import")


def test_a_package_is_a_directory_not_the_word_after_package():
    """
    `cmd/main.go` and `tools/build.go` both say `package main` and are two packages. Merging
    them by that word would invent edges between programs that share nothing.
    """
    assert package_dir("goapp/cmd/main.go") == "goapp/cmd"
    assert package_dir("build.go") == "."
    graph = graph_of(
        {
            "cmd/main.go": "package main\n\nfunc main() { helper() }\n",
            "tools/build.go": "package main\n\nfunc helper() int { return 1 }\n",
        }
    )
    assert edges_of(graph, "INVOKES") == set()
    assert graph.unresolved_calls == {"cmd/main.go": 1}


def test_every_import_form(goapp):
    """
    Aliased, plain, blank and grouped. A plain import binds the path's last segment, which
    is the package name by the convention every Go repository follows.
    """
    facts = RULES["go"].walk(
        "app/a.go",
        _parse('package app\n\nimport (\n\t_ "app/store"\n\tst "app/store"\n)\n\nimport "app/one"\n'),
        "s",
    )
    assert [(i.module, i.alias, i.line) for i in facts.imports] == [
        ("app/store", "_", 4),
        ("app/store", "st", 5),
        ("app/one", "one", 8),
    ]


def _parse(text: str):
    from hippo.codegraph.treesitter import new_parser

    return new_parser("go").parse(text.encode()).root_node


# --------------------------------------------------------------- tested by


def test_tested_by_all_three_provenances(goapp):
    """
    A test that calls a symbol is `test_import` 0.85 -- in Go the package *is* the import,
    so a `_test.go` file beside the code earns the same tier as an imported one. The file
    named after a module is `test_filename` 0.75, and a name a test only mentions is
    `test_mention` 0.60. `BenchmarkPlace` counts as a test function, which the shared
    lowercase `test_*` rule would have missed.
    """
    assert edge(goapp, "TESTED_BY", f"{SERVICE}::Service.Place", f"{TEST}::TestPlace")[1:3] == (
        0.85,
        "test_import",
    )
    assert edge(goapp, "TESTED_BY", f"{ORDER}::Validate", f"{TEST}::BenchmarkPlace")[1:3] == (
        0.85,
        "test_import",
    )
    assert edge(
        goapp,
        "TESTED_BY",
        f"{SERVICE}::goapp.orders.service",
        f"{TEST}::goapp.orders.service_test",
    )[1:3] == (0.75, "test_filename")
    assert edge(goapp, "TESTED_BY", f"{SERVICE}::Service", f"{TEST}::TestPlace")[1:3] == (
        0.60,
        "test_mention",
    )


# ------------------------------------------------------------- data access


def test_the_data_objects_a_go_file_names(goapp):
    """
    A SQL literal in a `db.Query`, a Cypher literal in a `session.Run`, and a Mongo
    collection reached through a local bound to a `Collection("...")` chain. The literal
    classifier is language-agnostic; the collection chain is the one Go shape.
    """
    assert {(d.kind, d.qualname, d.dialect) for d in goapp.data_objects} == {
        ("table", "orders", "sql"),
        ("label", "Order", "cypher"),
        ("label", "Customer", "cypher"),
        ("rel_type", "PLACED_BY", "cypher"),
        ("collection", "archive_orders", "mongo"),
    }
    assert edge(goapp, "READS", f"{SERVICE}::Service.ListOpen", "table:orders")[1:3] == (
        0.85,
        "sql_literal",
    )
    assert edge(goapp, "READS", f"{SERVICE}::Service.Graph", "rel_type:PLACED_BY")[1:3] == (
        0.85,
        "cypher_literal",
    )
    assert edge(goapp, "WRITES", f"{SERVICE}::Service.Archive", "collection:archive_orders")[1:3] == (
        0.85,
        "mongo_chain",
    )


def test_a_collection_chain_counts_whether_it_is_bound_to_a_local_or_not():
    """
    `client.Database("app").Collection("orders").InsertOne(...)` written out, and the same
    chain bound to a local first -- the second is how Go actually reads, and the walker
    rewrites the receiver to the chain so both are the same access.
    """
    graph = graph_of(
        {
            "app/a.go": (
                "package app\n\n"
                'func Direct() { client.Database("app").Collection("orders").InsertOne(ctx, o) }\n\n'
                'func Bound() {\n\tcoll := client.Database("app").Collection("orders")\n'
                "\tcoll.Find(ctx)\n}\n"
            )
        }
    )
    assert edge(graph, "WRITES", "app/a.go::Direct", "collection:orders")[1:3] == (0.85, "mongo_chain")
    assert edge(graph, "READS", "app/a.go::Bound", "collection:orders")[1:3] == (0.85, "mongo_chain")


def test_a_constructor_binding_reaches_the_type_it_builds():
    """
    Go has no constructors: `NewService()` returning a `*Service` is the convention every
    repository uses in their place, so a local bound to one resolves like a composite
    literal does.
    """
    graph = graph_of(
        {
            "app/a.go": (
                "package app\n\ntype Service struct{}\n\nfunc NewService() *Service { return &Service{} }\n\n"
                "func (s *Service) Place() int { return 1 }\n\n"
                "func Run() int {\n\ts := NewService()\n\treturn s.Place()\n}\n"
            )
        }
    )
    assert edge(graph, "INVOKES", "app/a.go::Run", "app/a.go::Service.Place")[1:3] == (1.00, "same_file")


# ------------------------------------------------------------ the properties


def test_extraction_is_deterministic():
    """The same bytes give the same graph -- same ids, same edges, same order."""
    first, second = graph_of(GOAPP), graph_of(GOAPP)
    assert [s.id for s in first.symbols] == [s.id for s in second.symbols]
    assert [(e.kind, e.a, e.b, e.omega, e.provenance) for e in first.edges] == [
        (e.kind, e.a, e.b, e.omega, e.provenance) for e in second.edges
    ]
    assert first.stats() == second.stats()


def test_a_file_the_grammar_cannot_read_does_not_sink_the_source():
    """One unparsable file is `parse_error` and line windows; the rest of the tree is unharmed."""
    graph = graph_of({"app/a.go": "package app\n\nfunc Good() int { return 1 }\n", "app/b.go": "))) not go"})
    assert graph.files_parsed == ["app/a.go"]
    assert graph.files_skipped == {"app/b.go": "parse_error"}
