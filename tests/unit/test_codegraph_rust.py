"""
The Rust walker: `src/hippo/codegraph/rust.py`.

Pure tests -- no store, no Ollama, no pipeline, and no shared fixture tree. Every tree here
is written inline, the way `test_codegraph.py` covers the resolver rows the frozen
`code_sample/` tree has no file for, so this file can pin exact line numbers and exact ω
without moving anybody else's counts.

What is being pinned, in order: the symbols a Rust file yields (an `impl` is not one, an
inline `mod` is), what a walker reports about them, every edge kind with its ω and
provenance from PLAN.md's 2.2b table, and -- just as deliberately -- the rows that must
produce **no edge**: a macro, an external crate, a `super::` call at file level, a
`?`/`Err(...)` that is not a raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from hippo.codegraph import extract_code, rust
from hippo.codegraph.languages import RULES
from hippo.codegraph.model import Symbol
from hippo.codegraph.rust import (
    is_test_function,
    is_test_path,
    source_setup,
)
from hippo.codegraph.rust import (
    test_stem as rust_test_stem,  # aliased: pytest would collect a `test_`-named import
)

# ------------------------------------------------------------------ helpers
#
# Copied rather than imported from `test_codegraph.py`: that file is the fixture tree's,
# and a language worker must not make it a dependency of three other test files.


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
    """The one edge of `kind` between two `path::qualname` (or `kind:qualname`) nodes."""
    found = [e for e in edges_of(graph, kind) if e[3] == a and e[4] == b]
    assert len(found) == 1, f"expected exactly one {kind} {a} -> {b}, found {found}"
    return found[0]


def symbol(graph, path: str, qualname: str):
    return next(s for s in graph.symbols if s.path == path and s.qualname == qualname)


def invokes_extra(graph, a: str, b: str) -> dict:
    names = {s.id: f"{s.path}::{s.qualname}" for s in graph.symbols}
    found = [e for e in graph.edges if e.kind == "INVOKES" and names.get(e.a) == a and names.get(e.b) == b]
    assert len(found) == 1, f"expected one INVOKES {a} -> {b}, found {found}"
    return found[0].extra


# ------------------------------------------------------------- the one tree
#
# One crate, the `pyapp`/`tsapp` "order service" story told in Rust. Line numbers below are
# counted from the first line of each string, so the assertions can name them.

LIB = """\
//! The order service crate.
//!
//! Three modules and the trait they share.
pub mod store;
pub mod billing;
pub mod orders;
"""

STORE = """\
/// What every store can do.
pub trait Base {
    /// Log a message and hand it back.
    fn log(&self, m: &str) -> String;

    fn describe(&self) -> String {
        String::new()
    }
}

pub struct OrderError;

pub fn helper() -> i64 {
    1
}
"""

BILLING = """\
use crate::orders::Order;

/// Total one order.
pub fn total(o: &Order) -> i64 {
    let _ = o;
    1
}

pub fn send_invoice(o: &Order) {
    let _ = o;
}
"""

ORDERS = """\
use crate::billing::{total, send_invoice as invoice};
use crate::store::{self, Base, OrderError};
use std::collections::HashMap;

pub struct Order;

/// Keeps orders. Acme Robotics is headquartered in Boulder.
#[derive(Debug)]
pub struct OrderService {
    db: Db,
}

impl Base for OrderService {
    fn log(&self, m: &str) -> String {
        m.to_string()
    }
}

impl OrderService {
    /// Place an order.
    pub fn place(&self, o: &Order) -> Result<i64, OrderError> {
        let amt = total(o)?;
        invoice(o);
        self.log("x");
        if amt > 0 {
            store::helper();
        }
        println!("placed");
        Self::audit();
        Ok(amt)
    }

    fn audit() {
        let _ = HashMap::new();
    }

    pub fn list_open(&self) {
        sqlx::query("SELECT id, total FROM orders WHERE status = 'open'");
    }

    pub fn archive(&self, o: &Order) {
        self.db.collection::<Order>("archive_orders").insert_one(o, None);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn place_totals() {
        super::OrderService::new().place(&Order);
    }
}
"""

MAIN = """\
use rsapp::orders::OrderService;

fn main() {
    let service = OrderService::new();
    service.place(&Order);
}
"""

INTEGRATION = """\
use rsapp::orders::OrderService;

#[test]
fn test_place() {
    OrderService::new().place(&Order);
}
"""

CRATE = {
    "rsapp/src/lib.rs": LIB,
    "rsapp/src/store.rs": STORE,
    "rsapp/src/billing.rs": BILLING,
    "rsapp/src/orders.rs": ORDERS,
    "rsapp/src/main.rs": MAIN,
    "rsapp/tests/orders.rs": INTEGRATION,
}

ORDERS_RS = "rsapp/src/orders.rs"
STORE_RS = "rsapp/src/store.rs"
BILLING_RS = "rsapp/src/billing.rs"


@pytest.fixture(scope="module")
def crate():
    return graph_of(CRATE)


# ------------------------------------------------------------- the symbols


def test_every_file_of_the_crate_is_parsed(crate):
    """A `.rs` file is no longer `unsupported`: the walker is registered, so it is parsed."""
    assert crate.files_skipped == {}
    assert sorted(crate.files_parsed) == sorted(CRATE)
    assert crate.stats()["languages"] == ["rust"]


def test_the_symbols_of_a_rust_file(crate):
    """
    Exactly what becomes a symbol, with its kind and the lines it claims.

    An `impl` block is not a symbol -- its functions are methods of the type it is for, even
    though the type is written twenty lines earlier. An inline `mod` *is* one, of kind
    `module`. A struct field, a `use` and the `#[derive]` on a struct are none of them.
    """
    found = [(s.qualname, s.kind, s.line_start, s.line_end) for s in crate.symbols if s.path == ORDERS_RS]
    assert found == [
        ("rsapp.src.orders", "module", 1, 54),
        ("Order", "class", 5, 5),
        ("OrderService", "class", 8, 11),
        ("OrderService.log", "method", 14, 16),
        ("OrderService.place", "method", 21, 31),
        ("OrderService.audit", "method", 33, 35),
        ("OrderService.list_open", "method", 37, 39),
        ("OrderService.archive", "method", 41, 43),
        ("tests", "module", 46, 54),
        ("tests.place_totals", "function", 50, 53),
    ]


def test_a_struct_keeps_its_own_lines_and_its_methods_keep_theirs(crate):
    """
    A type's `impl` blocks are elsewhere, so the type's range is the type. Stretching it
    over its impls would make two types with interleaved impls claim each other's lines,
    and the line range is what a passage title promises.
    """
    service = symbol(crate, ORDERS_RS, "OrderService")
    assert (service.line_start, service.line_end, service.header_end) == (8, 11, 11)
    assert symbol(crate, ORDERS_RS, "OrderService.place").line_start == 21
    # The attribute is part of the struct's passage the way a Python decorator is; the doc
    # comment above it is not, exactly as a TypeScript JSDoc block stays with the container.
    assert ORDERS.splitlines()[service.line_start - 1] == "#[derive(Debug)]"


def test_a_container_header_stops_before_its_first_member(crate):
    """
    The module's header is everything above its first item; a trait's is everything above
    its first method; an inline `mod`'s counts from its own attribute.
    """
    assert symbol(crate, ORDERS_RS, "rsapp.src.orders").header_end == 4
    assert symbol(crate, STORE_RS, "Base").header_end == 3
    assert symbol(crate, ORDERS_RS, "tests").header_end == 49


def test_kinds_come_from_the_item_not_the_name(crate):
    """`struct`, `enum`, `union` and `trait` are all a `class`; a trait's methods are methods."""
    graph = graph_of(
        {
            "k/src/lib.rs": (
                "pub struct S;\n"
                "pub enum E { A }\n"
                "pub union U { a: i32 }\n"
                "pub trait T {\n"
                "    fn t(&self);\n"
                "}\n"
                "pub fn f() {}\n"
                "type Alias = i64;\n"
                "const MAX: i64 = 5;\n"
                'static NAME: &str = "x";\n'
            )
        }
    )
    found = {(s.qualname, s.kind) for s in graph.symbols}
    assert found == {
        ("k.src.lib", "module"),
        ("S", "class"),
        ("E", "class"),
        ("U", "class"),
        ("T", "class"),
        ("T.t", "method"),
        ("f", "function"),
    }  # `type`, `const` and `static` stay in the module's header (2.2a)


def test_signatures_docs_and_params(crate):
    """The signature is the item down to its body; the doc is the `///` block above it."""
    place = symbol(crate, ORDERS_RS, "OrderService.place")
    assert place.signature == "pub fn place(&self, o: &Order) -> Result<i64, OrderError>"
    assert place.doc == "Place an order."
    assert place.params == ["o"]  # `self` is the receiver, not an argument

    service = symbol(crate, ORDERS_RS, "OrderService")
    assert service.signature == "pub struct OrderService"
    assert service.doc == "Keeps orders. Acme Robotics is headquartered in Boulder."

    required = symbol(crate, STORE_RS, "Base.log")
    assert required.signature == "fn log(&self, m: &str) -> String"  # no body, no `;`
    assert required.doc == "Log a message and hand it back."

    module = symbol(crate, "rsapp/src/lib.rs", "rsapp.src.lib")
    assert module.doc == "The order service crate.\n\nThree modules and the trait they share."


def test_the_doc_forms_rust_writes():
    """
    `///` above the item, `//!` inside the thing it documents, and the older `/** */` block
    with its ` * ` decoration. An attribute may sit between the doc and the item, and an
    ordinary `//` comment ends the block rather than joining it.
    """
    graph = graph_of(
        {
            "d/src/lib.rs": (
                "/** Block doc.\n * Second line.\n */\npub struct A;\n\n"
                "/// Line doc.\n#[derive(Debug)]\npub struct B;\n\n"
                "// Not a doc.\npub struct C;\n"
            )
        }
    )
    assert symbol(graph, "d/src/lib.rs", "A").doc == "Block doc.\nSecond line."
    assert symbol(graph, "d/src/lib.rs", "B").doc == "Line doc."
    assert symbol(graph, "d/src/lib.rs", "C").doc == ""


def test_a_module_qualname_keeps_mod_lib_and_main():
    """
    A Rust module is a path, and `mod.rs`/`lib.rs`/`main.rs` are real components of it --
    kept the way Python keeps `__init__`, so a directory and its `mod.rs` are never one node.
    """
    rules = RULES["rust"]
    assert rules.module_qualname("rsapp/src/lib.rs") == "rsapp.src.lib"
    assert rules.module_qualname("rsapp/src/billing/mod.rs") == "rsapp.src.billing.mod"
    assert rules.module_qualname("rsapp/src/orders.rs") == "rsapp.src.orders"


# ------------------------------------------------------------- the imports


def test_every_import_form(crate):
    """
    A `use` list, an `as` alias, `self` inside a list and a `mod x;` declaration -- each one
    binds a name and each one that names something in this source is an IMPORTS edge.
    """
    found = links(crate, "IMPORTS")
    assert (
        "IMPORTS",
        f"{ORDERS_RS}::rsapp.src.orders",
        f"{BILLING_RS}::total",
    ) in found  # `use crate::billing::{total, ...}`
    assert (
        "IMPORTS",
        f"{ORDERS_RS}::rsapp.src.orders",
        f"{BILLING_RS}::send_invoice",
    ) in found  # ...and the aliased half of the same list
    assert (
        "IMPORTS",
        f"{ORDERS_RS}::rsapp.src.orders",
        f"{STORE_RS}::rsapp.src.store",
    ) in found  # `{self, ...}` imports the module itself
    assert (
        "IMPORTS",
        f"{ORDERS_RS}::rsapp.src.orders",
        f"{STORE_RS}::Base",
    ) in found
    assert (
        "IMPORTS",
        "rsapp/src/lib.rs::rsapp.src.lib",
        f"{STORE_RS}::rsapp.src.store",
    ) in found  # `pub mod store;` is an import of the file beside it
    assert edge(crate, "IMPORTS", f"{ORDERS_RS}::rsapp.src.orders", f"{BILLING_RS}::total")[1:3] == (
        0.95,
        "import_path",
    )


def test_an_external_crate_is_not_part_of_this_source(crate):
    """`use std::collections::HashMap` names nothing in the repo, so there is no edge (2.2b)."""
    imported = {b for _, a, b in links(crate, "IMPORTS") if a == f"{ORDERS_RS}::rsapp.src.orders"}
    assert not any("HashMap" in name or "collections" in name for name in imported)


def test_a_use_of_your_own_file_is_not_an_import(crate):
    """
    `use super::*` inside an inline `mod` names the file it is written in. Binding through
    it would price this file's own names at the wildcard's 0.60 instead of `same_file`'s
    1.00, so the resolver is handed nothing at all.
    """
    assert ("IMPORTS", f"{ORDERS_RS}::rsapp.src.orders", f"{ORDERS_RS}::rsapp.src.orders") not in links(
        crate, "IMPORTS"
    )
    assert edge(crate, "INVOKES", f"{ORDERS_RS}::tests.place_totals", f"{ORDERS_RS}::OrderService.place")[
        1:3
    ] == (1.00, "same_file")


def test_a_directory_module_and_a_super_import():
    """
    `mod orders;` finds `orders.rs` *or* `orders/mod.rs`; `use super::x` from inside that
    directory walks back up to the crate root. A `mod.rs` owns the directory it is in, so
    its own submodules are its siblings.
    """
    graph = graph_of(
        {
            "app/src/lib.rs": "pub mod orders;\n\npub fn root_helper() -> i64 {\n    1\n}\n",
            "app/src/orders/mod.rs": (
                "use super::root_helper;\n\npub fn place() -> i64 {\n    root_helper()\n}\n"
            ),
        }
    )
    assert ("IMPORTS", "app/src/lib.rs::app.src.lib", "app/src/orders/mod.rs::app.src.orders.mod") in links(
        graph, "IMPORTS"
    )
    assert edge(graph, "INVOKES", "app/src/orders/mod.rs::place", "app/src/lib.rs::root_helper")[1:3] == (
        0.90,
        "via_import",
    )


def test_a_wildcard_import_is_worth_0_60():
    """`use crate::x::*` is the ω table's wildcard row, in Rust as in Python."""
    graph = graph_of(
        {
            "w/src/lib.rs": "pub mod a;\npub mod b;\n",
            "w/src/a.rs": "pub fn helper() -> i64 {\n    1\n}\n",
            "w/src/b.rs": "use crate::a::*;\n\npub fn go() -> i64 {\n    helper()\n}\n",
        }
    )
    assert edge(graph, "IMPORTS", "w/src/b.rs::w.src.b", "w/src/a.rs::w.src.a")[1:3] == (0.60, "wildcard")
    assert edge(graph, "INVOKES", "w/src/b.rs::go", "w/src/a.rs::helper")[1:3] == (0.90, "via_import")


def test_the_crate_name_reaches_the_library_half(crate):
    """
    A binary and an integration test cannot say `crate::` about the library beside them --
    they say `rsapp::`. The crate's name is the directory its root sits in (`rsapp/src/lib.rs`
    is the crate `rsapp`), which is the layout `cargo new` writes.
    """
    assert ("IMPORTS", "rsapp/src/main.rs::rsapp.src.main", f"{ORDERS_RS}::OrderService") in links(
        crate, "IMPORTS"
    )
    assert edge(crate, "INVOKES", "rsapp/src/main.rs::main", f"{ORDERS_RS}::OrderService.place")[1:3] == (
        0.90,
        "via_import",
    )


def test_the_crate_name_comes_from_cargo_toml_when_there_is_one():
    """A renamed package (`name = "order-service"`) is `order_service` in every path."""
    files = {
        "Cargo.toml": '[package]\nname = "order-service"\nversion = "0.1.0"\n',
        "src/lib.rs": "pub mod orders;\n",
        "src/orders.rs": "pub fn place() -> i64 {\n    1\n}\n",
        "tests/it.rs": "use order_service::orders::place;\n\n#[test]\nfn test_it() {\n    place();\n}\n",
    }
    docs = [Doc(name, text, name) for name, text in files.items()]
    assert source_setup(docs) == {"src": "order_service"}
    graph = extract_code(docs, "s")
    assert edge(graph, "INVOKES", "tests/it.rs::test_it", "src/orders.rs::place")[1:3] == (
        0.90,
        "via_import",
    )


def test_crate_stays_inside_its_own_crate_in_a_workspace():
    """
    A workspace has several crates, and `crate::` in one of them must never reach into
    another: the root a file uses is the nearest one above it. The sibling is reachable
    only by name, which is what a `Cargo.toml` dependency actually is.
    """
    files = {
        "crates/alpha/src/lib.rs": "pub mod thing;\n",
        "crates/alpha/src/thing.rs": "pub fn go() -> i64 {\n    1\n}\n",
        "crates/beta/src/lib.rs": "pub mod thing;\n",
        "crates/beta/src/thing.rs": (
            "use crate::helper;\nuse alpha::thing::go;\n\npub fn run() -> i64 {\n    go()\n}\n"
        ),
        "crates/beta/src/helper.rs": "pub fn helper() -> i64 {\n    2\n}\n",
    }
    docs = [Doc(name, text, name) for name, text in files.items()]
    assert source_setup(docs) == {"crates/alpha/src": "alpha", "crates/beta/src": "beta"}
    graph = extract_code(docs, "s")
    # `use alpha::thing::go` crosses to the sibling crate by name...
    assert edge(graph, "INVOKES", "crates/beta/src/thing.rs::run", "crates/alpha/src/thing.rs::go")[1:3] == (
        0.90,
        "via_import",
    )
    # ...and beta's own `crate::` never lands in alpha, whose `thing` has the same name.
    assert (
        "IMPORTS",
        "crates/beta/src/thing.rs::crates.beta.src.thing",
        "crates/alpha/src/lib.rs::crates.alpha.src.lib",
    ) not in links(graph, "IMPORTS")


# --------------------------------------------------------------- the calls


def test_the_invokes_tiers(crate):
    """
    1.00 `same_file` for a method reached on `self`, 0.90 `via_import` for anything that
    came through a `use`. Rust has no package scope, so `same_scope` never fires (below).
    """
    assert edge(crate, "INVOKES", f"{ORDERS_RS}::OrderService.place", f"{ORDERS_RS}::OrderService.log")[
        1:3
    ] == (1.00, "same_file")
    assert edge(crate, "INVOKES", f"{ORDERS_RS}::OrderService.place", f"{BILLING_RS}::total")[1:3] == (
        0.90,
        "via_import",
    )
    # The alias is the binding: `send_invoice as invoice` then `invoice(o)`.
    assert edge(crate, "INVOKES", f"{ORDERS_RS}::OrderService.place", f"{BILLING_RS}::send_invoice")[1:3] == (
        0.90,
        "via_import",
    )
    # `store::helper()` -- the module was imported with `{self, ...}`, the name through it.
    assert edge(crate, "INVOKES", f"{ORDERS_RS}::OrderService.place", f"{STORE_RS}::helper")[1:3] == (
        0.90,
        "via_import",
    )


def test_self_and_capital_self_are_both_the_receiver(crate):
    """`self.log(...)` and `Self::audit()` are both "a member of the type I am in"."""
    assert "Self" in RULES["rust"].self_names
    assert edge(crate, "INVOKES", f"{ORDERS_RS}::OrderService.place", f"{ORDERS_RS}::OrderService.audit")[
        1:3
    ] == (1.00, "same_file")


def test_in_branch_and_arg_binding(crate):
    """
    A call inside an `if` is conditional; a resolved call carries the callee's parameter
    names bound to the caller's argument expressions.
    """
    conditional = invokes_extra(crate, f"{ORDERS_RS}::OrderService.place", f"{STORE_RS}::helper")
    assert conditional["in_branch"] is True
    assert conditional["call_line"] == 26

    direct = invokes_extra(crate, f"{ORDERS_RS}::OrderService.place", f"{BILLING_RS}::total")
    assert direct["in_branch"] is False
    assert direct["is_await"] is False
    assert direct["arg_binding"] == {"o": "o"}
    assert invokes_extra(crate, f"{ORDERS_RS}::OrderService.place", f"{ORDERS_RS}::OrderService.log")[
        "arg_binding"
    ] == {"m": '"x"'}


def test_a_match_arm_is_a_branch():
    """`match` is Rust's `if`: the arm that calls `rollback` is not the always-taken path."""
    graph = graph_of(
        {
            "m/src/lib.rs": (
                "pub fn rollback() {}\n\n"
                "pub fn run(r: Result<i64, E>) {\n"
                "    match r {\n"
                "        Ok(_) => {}\n"
                "        Err(_) => rollback(),\n"
                "    }\n"
                "}\n"
            )
        }
    )
    assert invokes_extra(graph, "m/src/lib.rs::run", "m/src/lib.rs::rollback")["in_branch"] is True


def test_an_awaited_call_says_so():
    graph = graph_of(
        {
            "a/src/lib.rs": (
                "pub async fn fetch() -> i64 {\n    1\n}\n\n"
                "pub async fn run() -> i64 {\n    fetch().await\n}\n"
            )
        }
    )
    assert invokes_extra(graph, "a/src/lib.rs::run", "a/src/lib.rs::fetch")["is_await"] is True


def test_a_closure_folds_into_the_function_it_is_written_in():
    """
    A closure and a nested `fn` are not symbols (2.2a), so what they call belongs to the
    function they are written in -- which is also the passage a reader would find it in.
    """
    graph = graph_of(
        {
            "l/src/lib.rs": (
                "pub fn helper(x: i64) -> i64 {\n    x\n}\n\n"
                "pub fn run(v: Vec<i64>) {\n    v.iter().map(|x| helper(*x));\n}\n"
            )
        }
    )
    assert {s.qualname for s in graph.symbols} == {"l.src.lib", "helper", "run"}
    assert edge(graph, "INVOKES", "l/src/lib.rs::run", "l/src/lib.rs::helper")[1:3] == (
        1.00,
        "same_file",
    )


def test_a_struct_literal_binding_carries_its_type():
    """`let s = OrderService { .. }` names the type as surely as `OrderService::new()` does."""
    graph = graph_of(
        {
            "b/src/lib.rs": (
                "pub struct Service {\n    pub on: bool,\n}\n\n"
                "impl Service {\n    pub fn place(&self) {}\n}\n\n"
                "pub fn go() {\n    let s = Service { on: true };\n    s.place();\n}\n"
            )
        }
    )
    assert edge(graph, "INVOKES", "b/src/lib.rs::go", "b/src/lib.rs::Service.place")[1:3] == (
        1.00,
        "same_file",
    )


def test_a_trait_holds_both_its_required_and_its_default_methods(crate):
    """`fn log(&self) -> String;` and `fn describe(&self) { ... }` are both `Base`'s."""
    assert [s.qualname for s in crate.symbols if s.path == STORE_RS] == [
        "rsapp.src.store",
        "Base",
        "Base.log",
        "Base.describe",
        "OrderError",
        "helper",
    ]
    assert symbol(crate, STORE_RS, "Base.describe").kind == "method"


def test_a_constructor_chain_names_its_type(crate):
    """
    `OrderService::new().place(o)` knows what `place` is on, because `new`/`default`/`from`
    are the associated functions that name their own type -- the same guess Python makes for
    `OrderService().place(o)`, and no wider.
    """
    assert edge(crate, "INVOKES", "rsapp/tests/orders.rs::test_place", f"{ORDERS_RS}::OrderService.place")[
        1:3
    ] == (0.90, "via_import")


def test_any_other_chain_stays_unresolved():
    """`Config::load().validate()` is 2.2b's unresolvable chain: we do not know what it is."""
    graph = graph_of(
        {
            "c/src/lib.rs": (
                "pub struct Config;\n\n"
                "impl Config {\n"
                "    pub fn load() -> Config {\n        Config\n    }\n"
                "    pub fn validate(&self) {}\n"
                "}\n\n"
                "pub fn go() {\n    Config::load().validate();\n}\n"
            )
        }
    )
    assert ("INVOKES", "c/src/lib.rs::go", "c/src/lib.rs::Config.validate") not in links(graph, "INVOKES")
    assert edge(graph, "INVOKES", "c/src/lib.rs::go", "c/src/lib.rs::Config.load")[1:3] == (
        1.00,
        "same_file",
    )


def test_a_let_binding_carries_the_type(crate):
    """`let service = OrderService::new(); service.place(...)` resolves through the binding."""
    facts_lines = MAIN.splitlines()
    assert facts_lines[3].strip() == "let service = OrderService::new();"
    assert edge(crate, "INVOKES", "rsapp/src/main.rs::main", f"{ORDERS_RS}::OrderService.place")[1:3] == (
        0.90,
        "via_import",
    )


def test_the_rows_that_produce_no_edge(crate):
    """
    A macro is not a call, an external crate is not ours, and a bare `super::` path at file
    level names a module we have no binding for. None of them is a low-confidence edge: they
    are simply absent, and counted in `unresolved_calls` where they were a call at all.
    """
    from_place = {b for k, a, b in links(crate, "INVOKES") if a == f"{ORDERS_RS}::OrderService.place"}
    assert from_place == {
        f"{BILLING_RS}::total",
        f"{BILLING_RS}::send_invoice",
        f"{ORDERS_RS}::OrderService.log",
        f"{ORDERS_RS}::OrderService.audit",
        f"{STORE_RS}::helper",
    }  # `println!`, `Ok(...)` and the `?` are not in it

    graph = graph_of(
        {
            "n/src/lib.rs": "pub mod inner;\n\npub fn helper() -> i64 {\n    1\n}\n",
            "n/src/inner.rs": (
                "pub fn go() {\n"
                "    super::helper();\n"
                '    println!("{}", helper_name());\n'
                '    panic!("nope");\n'
                "}\n"
            ),
        }
    )
    assert links(graph, "INVOKES") == set()


def test_a_macro_body_still_yields_its_literals():
    """
    `sqlx::query!("SELECT ...")` is not a call, but the SQL in it is still SQL: the walker
    descends into the macro's tokens for literals and identifiers even though it emits no
    CallFact for the macro itself.
    """
    graph = graph_of({"q/src/lib.rs": ('pub fn list() {\n    sqlx::query!("SELECT id FROM orders");\n}\n')})
    assert [(d.kind, d.qualname) for d in graph.data_objects] == [("table", "orders")]
    assert links(graph, "INVOKES") == set()


def test_the_fuzzy_rule():
    """
    An unknown receiver may still resolve, but only when exactly one symbol in this language
    carries the name and the name is not one everybody uses. Two candidates: no edge.
    """
    one = graph_of(
        {
            "f/src/lib.rs": (
                "pub struct Widget;\n\n"
                "impl Widget {\n    pub fn spin(&self) {}\n}\n\n"
                "pub fn run(w: &Widget) {\n    w.spin();\n}\n"
            )
        }
    )
    assert edge(one, "INVOKES", "f/src/lib.rs::run", "f/src/lib.rs::Widget.spin")[1:3] == (
        0.50,
        "fuzzy_name",
    )

    two = graph_of(
        {
            "f/src/lib.rs": (
                "pub struct Widget;\npub struct Gear;\n\n"
                "impl Widget {\n    pub fn spin(&self) {}\n}\n\n"
                "impl Gear {\n    pub fn spin(&self) {}\n}\n\n"
                "pub fn run(w: &Widget) {\n    w.spin();\n}\n"
            )
        }
    )
    assert links(two, "INVOKES") == set()


def test_rust_has_no_same_scope_tier():
    """
    Go's package and C#'s namespace make a sibling's name visible with no import; a Rust
    module does not. A name from the file next door needs a `use`, so `same_scope` -- the
    1.00 tier -- can never fire for Rust, and an unimported name is no edge at all.
    """
    assert RULES["rust"].scope_defines(None, None) == {}
    graph = graph_of(
        {
            "s/src/lib.rs": "pub mod a;\npub mod b;\n",
            "s/src/a.rs": "pub fn helper() -> i64 {\n    1\n}\n",
            "s/src/b.rs": "pub fn go() -> i64 {\n    helper()\n}\n",
        }
    )
    assert links(graph, "INVOKES") == set()
    assert not any(provenance == "same_scope" for _, _, provenance, _, _ in edges_of(graph))


# ------------------------------------------------- inheritance and members


def test_a_trait_impl_inherits_and_overrides(crate):
    """
    `impl Base for OrderService` is 2.2b's INHERITS row (an interface implementation counts,
    the plan's decision), and the method it fills in OVERRIDES the trait's required one.
    """
    assert edge(crate, "INHERITS", f"{ORDERS_RS}::OrderService", f"{STORE_RS}::Base")[1:3] == (
        0.90,
        "resolved",
    )
    assert edge(crate, "OVERRIDES", f"{ORDERS_RS}::OrderService.log", f"{STORE_RS}::Base.log")[1:3] == (
        0.90,
        "mro",
    )


def test_an_inherent_impl_inherits_nothing(crate):
    """`impl OrderService { }` says what the type does, not what it is."""
    inherits = {b for _, a, b in links(crate, "INHERITS") if a == f"{ORDERS_RS}::OrderService"}
    assert inherits == {f"{STORE_RS}::Base"}


def test_a_type_may_hold_its_methods_in_another_file():
    """
    Rust puts `impl S` in any file of the crate, so `member_paths` says every file with an
    `impl` for the type -- the calling file first, so a method beside the call still counts
    as `same_file`. Two `spin`s make the fuzzy rule impossible, so this is the member path
    and nothing else.
    """
    graph = graph_of(
        {
            "x/src/lib.rs": "pub mod model;\npub mod behaviour;\npub mod other;\npub mod app;\n",
            "x/src/model.rs": "#[derive(Default)]\npub struct Widget;\n",
            "x/src/behaviour.rs": (
                "use crate::model::Widget;\n\nimpl Widget {\n    pub fn spin(&self) {}\n}\n"
            ),
            "x/src/other.rs": "pub struct Gear;\n\nimpl Gear {\n    pub fn spin(&self) {}\n}\n",
            "x/src/app.rs": (
                "use crate::model::Widget;\n\n"
                "pub fn run() {\n    let w = Widget::default();\n    w.spin();\n}\n"
            ),
        }
    )
    assert edge(graph, "INVOKES", "x/src/app.rs::run", "x/src/behaviour.rs::Widget.spin")[1:3] == (
        0.90,
        "via_import",
    )
    # The method is a member of `Widget` without being written inside it, so nothing in
    # `behaviour.rs` contains it -- CONTAINS is syntax, and the syntax is in another file.
    assert not any(b == "x/src/behaviour.rs::Widget.spin" for _, _, b in links(graph, "CONTAINS"))


def test_the_impl_table_is_never_shared_between_two_sources():
    """
    `member_paths` inverts `index.members` once per source rather than scanning it per call
    site. The cache is keyed on the index it was built from, so a second extraction with the
    same type name in different files must not see the first one's paths.
    """
    first = graph_of(
        {
            "one/src/lib.rs": "pub mod a;\n",
            "one/src/a.rs": "pub struct W;\n\nimpl W {\n    pub fn only_here(&self) {}\n}\n",
        }
    )
    second = graph_of(
        {
            "two/src/lib.rs": "pub mod b;\npub mod c;\n",
            "two/src/b.rs": "pub struct W;\n",
            "two/src/c.rs": (
                "use crate::b::W;\n\nimpl W {\n    pub fn elsewhere(&self) {}\n}\n\n"
                "pub fn go() {\n    let w = W::default();\n    w.elsewhere();\n}\n"
            ),
        }
    )
    assert edge(first, "CONTAINS", "one/src/a.rs::W", "one/src/a.rs::W.only_here")
    assert edge(second, "INVOKES", "two/src/c.rs::go", "two/src/c.rs::W.elsewhere")[1:3] == (
        1.00,
        "same_file",
    )
    assert not any("only_here" in b for _, _, b in links(second))


def test_contains_is_the_syntax_of_one_file(crate):
    """Module -> item, type -> the methods its impls declare, inline mod -> its own items."""
    contains = {(a, b) for _, a, b in links(crate, "CONTAINS")}
    assert (f"{ORDERS_RS}::rsapp.src.orders", f"{ORDERS_RS}::OrderService") in contains
    assert (f"{ORDERS_RS}::rsapp.src.orders", f"{ORDERS_RS}::tests") in contains
    assert (f"{ORDERS_RS}::OrderService", f"{ORDERS_RS}::OrderService.place") in contains
    assert (f"{ORDERS_RS}::tests", f"{ORDERS_RS}::tests.place_totals") in contains
    assert (f"{STORE_RS}::Base", f"{STORE_RS}::Base.log") in contains


# --------------------------------------------------------- raises and data


def test_raises_comes_from_the_return_type_and_nowhere_else(crate):
    """
    `-> Result<_, E>` is the only thing that says what a function fails with. `?` and
    `Err(...)` move a value; `match ... Err(e)` reads one. Rust has values, not exceptions,
    so there is no CATCHES edge in the language at all.
    """
    assert edge(crate, "RAISES", f"{ORDERS_RS}::OrderService.place", f"{STORE_RS}::OrderError")[1:3] == (
        0.90,
        "resolved",
    )
    assert links(crate, "CATCHES") == set()

    graph = graph_of(
        {
            "r/src/lib.rs": (
                "pub struct DbError;\n\n"
                "pub fn read() -> Result<i64, DbError> {\n    Ok(1)\n}\n\n"
                "pub fn go() -> i64 {\n"
                "    match read() {\n        Ok(v) => v,\n        Err(DbError) => 0,\n    }\n"
                "}\n"
            )
        }
    )
    assert links(graph, "RAISES") == {("RAISES", "r/src/lib.rs::read", "r/src/lib.rs::DbError")}
    assert links(graph, "CATCHES") == set()


def test_an_unresolved_error_type_lands_on_the_symbol():
    """A `Result<_, io::Error>` we cannot see is a name on `Symbol.raises`, not an edge."""
    graph = graph_of({"e/src/lib.rs": "pub fn read() -> Result<i64, IoError> {\n    Ok(1)\n}\n"})
    assert symbol(graph, "e/src/lib.rs", "read").raises == ["IoError"]
    assert links(graph, "RAISES") == set()


def test_a_sql_literal_reads_its_table(crate):
    """`sqlx::query("SELECT ... FROM orders")` is a literal like any other."""
    assert edge(crate, "READS", f"{ORDERS_RS}::OrderService.list_open", "table:orders")[1:3] == (
        0.85,
        "sql_literal",
    )


def test_a_mongo_collection_chain_writes(crate):
    """`db.collection::<Order>("archive_orders").insert_one(...)` is the Rust driver's shape."""
    assert edge(crate, "WRITES", f"{ORDERS_RS}::OrderService.archive", "collection:archive_orders")[1:3] == (
        0.85,
        "mongo_chain",
    )
    assert [(d.kind, d.qualname, d.dialect) for d in crate.data_objects] == [
        ("collection", "archive_orders", "mongo"),
        ("table", "orders", "sql"),
    ]


def test_a_cypher_literal_names_its_labels():
    """The literal classifier is language-agnostic: `neo4rs::query` is just a string holder."""
    graph = graph_of(
        {
            "g/src/lib.rs": (
                "pub fn graph() {\n"
                '    neo4rs::query("MATCH (o:Order)-[:PLACED_BY]->(c:Customer) RETURN c");\n'
                "}\n"
            )
        }
    )
    assert {(d.kind, d.qualname) for d in graph.data_objects} == {
        ("label", "Order"),
        ("label", "Customer"),
        ("rel_type", "PLACED_BY"),
    }


# ------------------------------------------------------------ test code


def test_which_files_and_items_are_test_code(crate):
    """
    Cargo's layout: `tests/` and `benches/` are test code, and so is anything under a
    `#[cfg(test)]` mod or carrying `#[test]`, wherever it is written.
    """
    assert is_test_path("rsapp/tests/orders.rs")
    assert is_test_path("rsapp/benches/place.rs")
    assert not is_test_path("rsapp/src/orders.rs")

    assert symbol(crate, "rsapp/tests/orders.rs", "test_place").is_test
    assert symbol(crate, ORDERS_RS, "tests").is_test  # `#[cfg(test)] mod tests`
    assert symbol(crate, ORDERS_RS, "tests.place_totals").is_test
    assert not symbol(crate, ORDERS_RS, "OrderService.place").is_test


def test_a_test_stem_is_the_crate_level_file_name():
    """
    `tests/orders.rs` tests the module `orders`. Rust does not decorate the name, so the
    directory is the whole signal -- and `tests/common/mod.rs` names no module at all.
    """
    assert rust_test_stem("rsapp/tests/orders.rs") == "orders"
    assert rust_test_stem("rsapp/tests/common/mod.rs") is None
    assert rust_test_stem("rsapp/src/orders.rs") is None


def test_every_function_in_rust_test_code_is_a_case():
    """`#[test]`, not the name, marks a Rust test case, so `place_totals` is one."""
    assert is_test_function(Symbol(kind="function", name="place_totals"))
    assert is_test_function(Symbol(kind="method", name="anything"))
    assert not is_test_function(Symbol(kind="class", name="Tests"))


def test_the_three_tested_by_provenances(crate):
    """
    0.85 `test_import` from a resolved call in a test case, 0.75 `test_filename` for
    `tests/orders.rs` naming the module `orders`, 0.60 `test_mention` for a name a test
    function says without calling it.
    """
    assert edge(
        crate,
        "TESTED_BY",
        f"{ORDERS_RS}::OrderService.place",
        "rsapp/tests/orders.rs::test_place",
    )[1:3] == (0.85, "test_import")
    assert edge(crate, "TESTED_BY", f"{ORDERS_RS}::OrderService.place", f"{ORDERS_RS}::tests.place_totals")[
        1:3
    ] == (0.85, "test_import")
    assert edge(
        crate,
        "TESTED_BY",
        f"{ORDERS_RS}::rsapp.src.orders",
        "rsapp/tests/orders.rs::rsapp.tests.orders",
    )[1:3] == (0.75, "test_filename")
    assert edge(crate, "TESTED_BY", f"{ORDERS_RS}::Order", "rsapp/tests/orders.rs::test_place")[1:3] == (
        0.60,
        "test_mention",
    )


# ---------------------------------------------------------- the properties


def test_extraction_is_deterministic():
    """Two runs over the same bytes give the same ids, the same edges and the same order."""
    first, second = graph_of(CRATE), graph_of(CRATE)
    assert [s.id for s in first.symbols] == [s.id for s in second.symbols]
    assert [(e.a, e.b, e.kind, e.omega, e.provenance) for e in first.edges] == [
        (e.a, e.b, e.kind, e.omega, e.provenance) for e in second.edges
    ]
    assert first.stats() == second.stats()


def test_a_file_that_will_not_parse_does_not_sink_the_source():
    """One broken file is `parse_error` and line windows; the rest of the crate is unharmed."""
    graph = graph_of({"b/src/lib.rs": "pub fn ok() {}\n", "b/src/bad.rs": "fn ((( {\n"})
    assert graph.files_parsed == ["b/src/lib.rs"]
    assert graph.files_skipped == {"b/src/bad.rs": "parse_error"}


def test_the_walker_imports_no_resolver_at_module_level():
    """
    `languages` imports `rust`, and `resolve` imports `languages`. A module-level
    `from .resolve import ...` here would be a cycle that only bites at import time, in
    somebody else's process.
    """
    source = Path(rust.__file__).read_text()
    for line in source.splitlines():
        if ".resolve import" in line:
            assert line.startswith(" "), line  # inside `TYPE_CHECKING`, or inside a function
