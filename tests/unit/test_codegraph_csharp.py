"""
The C# walker: `src/hippo/codegraph/csharp.py`.

Pure tests -- no store, no Ollama, no pipeline -- written against small inline trees rather
than the shared `code_sample` fixture, the way `test_codegraph.py` covers the resolver rows
that tree has no file for. `extract_code` is handed documents and returns a `CodeGraph`, so
every assertion here is a function of the bytes in the strings below.

The tree in `ORDERS` is the plan's "order service" story in C#: the same `orders` table,
`archive_orders` collection and `Order`/`Customer` Cypher objects the Python and TypeScript
trees name, so the edges it produces can be read beside theirs. Line numbers are pinned
exactly -- a passage that starts one line late is a bug the ω table cannot see.

Four rules are C#'s alone and get their own tests: a namespace is a scope (ω 1.00
`same_scope` with no `using`), a `using` names that scope rather than a file, a field's
declared type is what makes dependency injection resolve, and a test case is an attribute
rather than a name.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from hippo.codegraph import csharp  # imported as a module: `test_stem` would be collected
from hippo.codegraph.extract import extract_code

# ------------------------------------------------------------------ helpers


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


def by_qualname(graph, path: str, qualname: str):
    return next(s for s in graph.symbols if s.path == path and s.qualname == qualname)


def extra_of(graph, a: str, b: str) -> dict:
    """The INVOKES `extra` of one pair: `call_line`, `in_branch`, `is_await`, `arg_binding`."""
    names = {s.id: f"{s.path}::{s.qualname}" for s in graph.symbols}
    found = [e for e in graph.edges if e.kind == "INVOKES" and names.get(e.a) == a and names.get(e.b) == b]
    assert len(found) == 1, f"expected exactly one INVOKES {a} -> {b}, found {found}"
    return found[0].extra


# --------------------------------------------------------------- the tree
#
# Line numbers are load-bearing: every `line_start`/`line_end` below is counted off these
# strings, and the first line of each is line 1.

STORE = """namespace CsApp.Store;

public class Base
{
    /// <summary>Writes a line and gives it back.</summary>
    public string Log(string m) => m;
}

public class OrderError : Exception { }
"""

BILLING = """namespace CsApp.Billing;

public static class Billing
{
    public static int Total(Order o) => o.Amount;

    public static void SendInvoice(Order o) { }
}
"""

ORDERS = """namespace CsApp.Orders;

using CsApp.Billing;
using CsApp.Store;
using static CsApp.Billing.Billing;
using Repo = CsApp.Store.Base;

/// <summary>Keeps orders.</summary>
/// <remarks>Acme Robotics is headquartered in Boulder.</remarks>
public class OrderService : Base, IOrderRepo
{
    private readonly IOrderRepo _repo;

    public int Place(Order order)
    {
        var amt = Billing.Total(order);
        try { SendInvoice(order); }
        catch (OrderError e) { throw new InvalidOperationException("no"); }
        base.Log("x");
        _repo.Save(order);
        return amt;
    }

    public void Save(Order o) { }

    public void ListOpen()
    {
        var fallback = new Repo();
        db.Query("SELECT id, total FROM orders WHERE status = 'open'");
        Console.WriteLine("done");
    }

    public async Task Archive(Order o)
    {
        await _repo.SaveAsync(o);
        db.GetCollection<Order>("archive_orders").InsertOneAsync(o);
    }

    public void Graph()
    {
        session.RunAsync("MATCH (o:Order)-[:PLACED_BY]->(c:Customer) RETURN c");
    }
}

public interface IOrderRepo
{
    void Save(Order o);

    Task SaveAsync(Order o);
}
"""

TESTS = """namespace CsApp.Orders;

public class OrderServiceTests
{
    [Fact]
    public void Place_totals()
    {
        new OrderService().Place(new Order());
    }

    public void Helper() { }
}
"""

PROGRAM = """using CsApp.Orders;

var service = new OrderService();
service.Place(new Order());
"""

STORE_PATH = "csapp/Store/Base.cs"
BILLING_PATH = "csapp/Billing/Billing.cs"
ORDERS_PATH = "csapp/Orders/OrderService.cs"
TESTS_PATH = "csapp/Orders.Tests/OrderServiceTests.cs"
PROGRAM_PATH = "csapp/Program.cs"

TREE = {
    STORE_PATH: STORE,
    BILLING_PATH: BILLING,
    ORDERS_PATH: ORDERS,
    TESTS_PATH: TESTS,
    PROGRAM_PATH: PROGRAM,
}


@pytest.fixture(scope="module")
def graph():
    return graph_of(TREE)


# ------------------------------------------------------------- the symbols


def test_every_file_parses(graph):
    """A C# file the walker cannot read would be an `unsupported` row and line windows."""
    assert graph.files_parsed == list(TREE)
    assert graph.files_skipped == {}
    assert graph.stats()["languages"] == ["csharp"]


def test_symbol_set_kinds_and_line_ranges(graph):
    """
    The exact symbol set. A namespace is *not* a symbol -- it is the scope in
    `FileFacts.scope` -- so a file's types are top-level whichever way it spells its
    namespace, and the module symbol owns them.
    """
    found = [(s.path, s.qualname, s.kind, s.line_start, s.line_end) for s in graph.symbols]
    assert found == [
        (STORE_PATH, "csapp.Store.Base", "module", 1, 9),
        (STORE_PATH, "Base", "class", 3, 7),
        (STORE_PATH, "Base.Log", "method", 6, 6),
        (STORE_PATH, "OrderError", "class", 9, 9),
        (BILLING_PATH, "csapp.Billing.Billing", "module", 1, 8),
        (BILLING_PATH, "Billing", "class", 3, 8),
        (BILLING_PATH, "Billing.Total", "method", 5, 5),
        (BILLING_PATH, "Billing.SendInvoice", "method", 7, 7),
        (ORDERS_PATH, "csapp.Orders.OrderService", "module", 1, 50),
        (ORDERS_PATH, "OrderService", "class", 10, 43),
        (ORDERS_PATH, "OrderService.Place", "method", 14, 22),
        (ORDERS_PATH, "OrderService.Save", "method", 24, 24),
        (ORDERS_PATH, "OrderService.ListOpen", "method", 26, 31),
        (ORDERS_PATH, "OrderService.Archive", "method", 33, 37),
        (ORDERS_PATH, "OrderService.Graph", "method", 39, 42),
        (ORDERS_PATH, "IOrderRepo", "class", 45, 50),
        (ORDERS_PATH, "IOrderRepo.Save", "method", 47, 47),
        (ORDERS_PATH, "IOrderRepo.SaveAsync", "method", 49, 49),
        (TESTS_PATH, "csapp.Orders.Tests.OrderServiceTests", "module", 1, 12),
        (TESTS_PATH, "OrderServiceTests", "class", 3, 12),
        (TESTS_PATH, "OrderServiceTests.Place_totals", "method", 5, 9),
        (TESTS_PATH, "OrderServiceTests.Helper", "method", 11, 11),
        (PROGRAM_PATH, "csapp.Program", "module", 1, 4),
    ]


def test_an_interface_member_is_a_symbol_though_it_has_no_body(graph):
    """
    Without it a DI call would land nowhere: `_repo.Save()` resolves to the *declared*
    interface method, which is the only thing the declaration says for certain.
    """
    declared = by_qualname(graph, ORDERS_PATH, "IOrderRepo.Save")
    assert (declared.kind, declared.signature, declared.statement_lines) == (
        "method",
        "void Save(Order o)",
        [],
    )


def test_module_qualname_and_display(graph):
    """
    The module is the path, `/` to `.`, extension dropped -- the namespace does not enter it.
    `App/Billing/OrderService.cs` is the module `App.Billing.OrderService`, the class inside
    is `OrderService`, and its display name is the two joined.
    """
    service = by_qualname(graph, ORDERS_PATH, "OrderService")
    assert (service.module, service.display) == (
        "csapp.Orders.OrderService",
        "csapp.Orders.OrderService.OrderService",
    )
    assert (
        by_qualname(graph, ORDERS_PATH, "OrderService.Place").display
        == "csapp.Orders.OrderService.OrderService.Place"
    )
    module = by_qualname(graph, ORDERS_PATH, "csapp.Orders.OrderService")
    assert (module.name, module.display) == ("OrderService", "csapp.Orders.OrderService")


def test_signatures_stop_at_the_body_and_drop_the_attributes(graph):
    """
    A signature reads from the modifiers to the body, `=>` or `;`. `[Fact]` is inside the
    symbol's line range -- it is part of the passage -- but it is not how the member reads.
    """
    assert (
        by_qualname(graph, ORDERS_PATH, "OrderService").signature
        == "public class OrderService : Base, IOrderRepo"
    )
    assert by_qualname(graph, ORDERS_PATH, "OrderService.Place").signature == "public int Place(Order order)"
    assert (
        by_qualname(graph, ORDERS_PATH, "OrderService.Archive").signature
        == "public async Task Archive(Order o)"
    )
    assert by_qualname(graph, STORE_PATH, "Base.Log").signature == "public string Log(string m)"
    assert (
        by_qualname(graph, TESTS_PATH, "OrderServiceTests.Place_totals").signature
        == "public void Place_totals()"
    )


def test_xml_docs_put_the_summary_first_and_drop_the_tags(graph):
    """`<summary>` leads, the rest follows, every tag is stripped -- it is prose for OpenIE."""
    assert by_qualname(graph, ORDERS_PATH, "OrderService").doc == (
        "Keeps orders.\nAcme Robotics is headquartered in Boulder."
    )
    assert by_qualname(graph, STORE_PATH, "Base.Log").doc == "Writes a line and gives it back."
    assert by_qualname(graph, ORDERS_PATH, "OrderService.Place").doc == ""


def test_fields_stay_in_the_class_header_passage(graph):
    """
    A field is not a symbol, so the class header runs to just before its first *member* --
    which is what puts `private readonly IOrderRepo _repo;` in the header passage.
    """
    service = by_qualname(graph, ORDERS_PATH, "OrderService")
    assert service.header_end == 13  # `Place` opens on 14; the field on 12 is inside the header
    assert by_qualname(graph, ORDERS_PATH, "csapp.Orders.OrderService").header_end == 9
    assert by_qualname(graph, ORDERS_PATH, "OrderService.Place").header_end == 22


def test_params_and_statement_lines(graph):
    place = by_qualname(graph, ORDERS_PATH, "OrderService.Place")
    assert place.params == ["order"]
    assert place.statement_lines == [16, 17, 19, 20, 21]


# ------------------------------------------------------- namespaces and usings


def test_a_namespace_is_the_scope_and_a_sibling_needs_no_using(graph):
    """
    `OrderServiceTests` is in `namespace CsApp.Orders` and never mentions `OrderService`, but
    C# resolves it as surely as a local name. That is ω 1.00 `same_scope` -- 0.90
    `via_import` would understate a name that needed no import at all.
    """
    assert edge(
        graph, "INVOKES", f"{TESTS_PATH}::OrderServiceTests.Place_totals", f"{ORDERS_PATH}::OrderService"
    )[1:3] == (1.00, "same_scope")


def test_a_files_own_name_still_wins_over_its_namespaces():
    """
    The scope is seeded *after* the file's own defines. Two files of one namespace declare a
    `Helper`; `build_index` keeps the first for the scope, but inside the second file its own
    declaration is what `Helper.Go()` means -- `same_file` 1.00, and no edge to the other.
    """
    graph = graph_of(
        {
            "a/One.cs": "namespace App;\n\npublic class Helper { public static int Go() => 1; }\n",
            "a/Two.cs": (
                "namespace App;\n"
                "\n"
                "public class Helper { public static int Go() => 2; }\n"
                "\n"
                "public class C { public int R() => Helper.Go(); }\n"
            ),
        }
    )
    assert edge(graph, "INVOKES", "a/Two.cs::C.R", "a/Two.cs::Helper.Go")[1:3] == (1.00, "same_file")
    assert ("INVOKES", "a/Two.cs::C.R", "a/One.cs::Helper.Go") not in links(graph, "INVOKES")


def test_the_three_using_forms(graph):
    """
    Plain (`using X.Y;`) binds a whole namespace, aliased binds one name, `using static`
    binds a type's members. All three are IMPORTS at 0.95 `import_path`; a namespace nobody
    declares here is a dependency and gets no edge at all.
    """
    module = f"{ORDERS_PATH}::csapp.Orders.OrderService"
    assert edges_of(graph, "IMPORTS") >= {
        ("IMPORTS", 0.95, "import_path", module, f"{BILLING_PATH}::csapp.Billing.Billing"),
        ("IMPORTS", 0.95, "import_path", module, f"{STORE_PATH}::csapp.Store.Base"),
        ("IMPORTS", 0.95, "import_path", module, f"{BILLING_PATH}::Billing"),  # using static
        ("IMPORTS", 0.95, "import_path", module, f"{STORE_PATH}::Base"),  # using Repo = ...
    }


def test_using_static_binds_the_members_so_a_bare_call_resolves(graph):
    """`using static CsApp.Billing.Billing;` is what makes the bare `SendInvoice(order)` an edge."""
    assert edge(
        graph, "INVOKES", f"{ORDERS_PATH}::OrderService.Place", f"{BILLING_PATH}::Billing.SendInvoice"
    )[1:3] == (0.90, "via_import")


def test_a_using_alias_binds_the_one_type(graph):
    """`using Repo = CsApp.Store.Base;` then `new Repo()` is a call to `Base`."""
    assert edge(graph, "INVOKES", f"{ORDERS_PATH}::OrderService.ListOpen", f"{STORE_PATH}::Base")[1:3] == (
        0.90,
        "via_import",
    )


def test_a_global_using_reads_like_any_other():
    graph = graph_of(
        {
            "a/One.cs": "namespace App.Store;\n\npublic class Thing { public static int Go() => 1; }\n",
            "b/Two.cs": "global using App.Store;\n\nnamespace Other;\n\npublic class C { public int R() => Thing.Go(); }\n",
        }
    )
    assert edge(graph, "INVOKES", "b/Two.cs::C.R", "a/One.cs::Thing.Go")[1:3] == (0.90, "via_import")


def test_a_block_namespace_and_a_file_scoped_one_agree():
    """The two spellings are the same scope, so they produce the same graph."""
    block = graph_of(
        {
            "a/One.cs": "namespace App\n{\n    public class Thing { public static int Go() => 1; }\n}\n",
            "a/Two.cs": "namespace App\n{\n    public class C { public int R() => Thing.Go(); }\n}\n",
        }
    )
    scoped = graph_of(
        {
            "a/One.cs": "namespace App;\npublic class Thing { public static int Go() => 1; }\n",
            "a/Two.cs": "namespace App;\npublic class C { public int R() => Thing.Go(); }\n",
        }
    )
    assert edges_of(block) == edges_of(scoped)
    assert [s.qualname for s in block.symbols] == [s.qualname for s in scoped.symbols]
    # The member is reached *through* the class, so it is scored by file distance; 1.00
    # `same_scope` is the tier of the name itself, which `test_a_namespace_is_the_scope...`
    # pins on `new OrderService()`.
    assert edge(block, "INVOKES", "a/Two.cs::C.R", "a/One.cs::Thing.Go")[1:3] == (0.90, "via_import")


def test_a_nested_namespace_is_one_dotted_scope():
    graph = graph_of(
        {
            "a/One.cs": "namespace App\n{\n    namespace Store\n    {\n        public class Thing { public static int Go() => 1; }\n    }\n}\n",
            "b/Two.cs": "using App.Store;\n\npublic class C { public int R() => Thing.Go(); }\n",
        }
    )
    assert edge(graph, "INVOKES", "b/Two.cs::C.R", "a/One.cs::Thing.Go")[1:3] == (0.90, "via_import")


# ----------------------------------------------------------------- calls


def test_the_invokes_edges_with_omega_and_provenance(graph):
    """Every INVOKES the tree produces, with the tier the ω table gives it."""
    assert edges_of(graph, "INVOKES") == {
        # `Billing.Total(o)`: the receiver is a class reached through `using CsApp.Billing`.
        (
            "INVOKES",
            0.90,
            "via_import",
            f"{ORDERS_PATH}::OrderService.Place",
            f"{BILLING_PATH}::Billing.Total",
        ),
        # ...and the bare `SendInvoice(o)` through `using static`.
        (
            "INVOKES",
            0.90,
            "via_import",
            f"{ORDERS_PATH}::OrderService.Place",
            f"{BILLING_PATH}::Billing.SendInvoice",
        ),
        # `base.Log("x")` walks the base list: C#'s `base` is its `super`.
        ("INVOKES", 0.90, "via_inheritance", f"{ORDERS_PATH}::OrderService.Place", f"{STORE_PATH}::Base.Log"),
        # `_repo.Save(order)` -- the field's declared type, in the same file.
        (
            "INVOKES",
            1.00,
            "same_file",
            f"{ORDERS_PATH}::OrderService.Place",
            f"{ORDERS_PATH}::IOrderRepo.Save",
        ),
        (
            "INVOKES",
            1.00,
            "same_file",
            f"{ORDERS_PATH}::OrderService.Archive",
            f"{ORDERS_PATH}::IOrderRepo.SaveAsync",
        ),
        # `new Repo()` -- the alias.
        ("INVOKES", 0.90, "via_import", f"{ORDERS_PATH}::OrderService.ListOpen", f"{STORE_PATH}::Base"),
        # the test: `new OrderService()` is same-namespace, `.Place` is a member of it.
        (
            "INVOKES",
            1.00,
            "same_scope",
            f"{TESTS_PATH}::OrderServiceTests.Place_totals",
            f"{ORDERS_PATH}::OrderService",
        ),
        (
            "INVOKES",
            0.90,
            "via_import",
            f"{TESTS_PATH}::OrderServiceTests.Place_totals",
            f"{ORDERS_PATH}::OrderService.Place",
        ),
        # `Program.cs`: top-level statements belong to the module symbol.
        ("INVOKES", 0.90, "via_import", f"{PROGRAM_PATH}::csapp.Program", f"{ORDERS_PATH}::OrderService"),
        (
            "INVOKES",
            0.90,
            "via_import",
            f"{PROGRAM_PATH}::csapp.Program",
            f"{ORDERS_PATH}::OrderService.Place",
        ),
    }


def test_a_field_type_is_what_makes_di_resolve(graph):
    """
    `private readonly IOrderRepo _repo;` then `_repo.Save(order)`: the call resolves through
    the field's *declared* type, which is the common ASP.NET shape. The walker says it as one
    `AssignFact` per method of the class, because that is the scope the resolver reads.
    """
    assert edge(graph, "INVOKES", f"{ORDERS_PATH}::OrderService.Place", f"{ORDERS_PATH}::IOrderRepo.Save")[
        1:3
    ] == (1.00, "same_file")


def test_a_generic_or_nullable_field_type_still_resolves():
    """`IRepo<Order>? _repo` is the type `IRepo`; the ceremony comes off before the lookup."""
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public interface IRepo<T> { void Save(T item); }\n"
                "\n"
                "public class Service\n"
                "{\n"
                "    private readonly IRepo<Order>? _repo;\n"
                "\n"
                "    public void Go(Order o) { _repo.Save(o); }\n"
                "}\n"
            )
        }
    )
    assert edge(graph, "INVOKES", "a/App.cs::Service.Go", "a/App.cs::IRepo.Save")[1:3] == (1.00, "same_file")


def test_this_reaches_the_class_and_a_local_var_its_type():
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class Service\n"
                "{\n"
                "    public int Amount() => 1;\n"
                "\n"
                "    public int Go()\n"
                "    {\n"
                "        var other = new Service();\n"
                "        return this.Amount() + other.Amount();\n"
                "    }\n"
                "}\n"
            )
        }
    )
    assert edge(graph, "INVOKES", "a/App.cs::Service.Go", "a/App.cs::Service.Amount")[1:3] == (
        1.00,
        "same_file",
    )


def test_invokes_extra_carries_the_branch_the_await_and_the_arg_binding(graph):
    """
    `in_branch` is true inside a `try`, `is_await` on an awaited call, and `arg_binding` maps
    the callee's parameter names onto the caller's argument expressions.
    """
    total = extra_of(graph, f"{ORDERS_PATH}::OrderService.Place", f"{BILLING_PATH}::Billing.Total")
    assert total == {"call_line": 16, "in_branch": False, "is_await": False, "arg_binding": {"o": "order"}}
    invoice = extra_of(graph, f"{ORDERS_PATH}::OrderService.Place", f"{BILLING_PATH}::Billing.SendInvoice")
    assert invoice["in_branch"] is True and invoice["call_line"] == 17
    archive = extra_of(graph, f"{ORDERS_PATH}::OrderService.Archive", f"{ORDERS_PATH}::IOrderRepo.SaveAsync")
    assert archive["is_await"] is True and archive["arg_binding"] == {"o": "o"}


def test_a_call_in_an_if_is_in_a_branch():
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class Service\n"
                "{\n"
                "    public int Amount() => 1;\n"
                "\n"
                "    public int Go(bool flag)\n"
                "    {\n"
                "        if (flag) { return this.Amount(); }\n"
                "        return 0;\n"
                "    }\n"
                "}\n"
            )
        }
    )
    assert extra_of(graph, "a/App.cs::Service.Go", "a/App.cs::Service.Amount")["in_branch"] is True


def test_the_no_edge_rows(graph):
    """
    2.2b's positive decisions. `Console.WriteLine` and `db.Query` are not in this source, so
    they are *nothing* -- not a low-confidence edge, not a placeholder -- and each is counted
    into `unresolved_calls` so phase 2 has a baseline.
    """
    targets = {b for _, _, b in links(graph, "INVOKES")}
    assert not any(name.endswith(("WriteLine", "Query", "Order")) for name in targets)
    assert graph.stats()["unresolved_calls"] == {
        ORDERS_PATH: 4,  # db.Query, Console.WriteLine, db.GetCollection, session.RunAsync
        TESTS_PATH: 1,  # new Order()
        PROGRAM_PATH: 1,  # new Order()
    }


def test_an_unresolvable_chain_is_no_edge():
    """`x.y.z()`: we do not know what `x.y` is, so `z` is not ours to guess at."""
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class Service\n"
                "{\n"
                "    public int Total() => 1;\n"
                "\n"
                "    public int Go() => outer.inner.Total();\n"
                "}\n"
            )
        }
    )
    assert links(graph, "INVOKES") == set()


def test_a_unique_bare_name_is_the_0_50_fuzzy_row():
    """An unknown receiver may still resolve, once, when exactly one symbol carries the name."""
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class Service\n"
                "{\n"
                "    public int Reconcile() => 1;\n"
                "}\n"
                "\n"
                "public class Caller\n"
                "{\n"
                "    public int Go(dynamic thing) => thing.Reconcile();\n"
                "}\n"
            )
        }
    )
    assert edge(graph, "INVOKES", "a/App.cs::Caller.Go", "a/App.cs::Service.Reconcile")[1:3] == (
        0.50,
        "fuzzy_name",
    )


def test_a_stoplisted_name_is_never_guessed():
    """`x.Get()` must never link to somebody's `Get`."""
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class Service\n"
                "{\n"
                "    public int Get() => 1;\n"
                "}\n"
                "\n"
                "public class Caller\n"
                "{\n"
                "    public int Go(dynamic thing) => thing.get();\n"
                "}\n"
            )
        }
    )
    assert links(graph, "INVOKES") == set()


# ------------------------------------------------------- inheritance and types


def test_inherits_covers_interfaces_too(graph):
    """
    The plan's decision: implementing an interface counts as INHERITS. C# writes a base class
    and an interface in one list and means the same thing to a graph -- "look here for
    members I did not declare".
    """
    assert edges_of(graph, "INHERITS") == {
        ("INHERITS", 0.90, "resolved", f"{ORDERS_PATH}::OrderService", f"{STORE_PATH}::Base"),
        ("INHERITS", 0.90, "resolved", f"{ORDERS_PATH}::OrderService", f"{ORDERS_PATH}::IOrderRepo"),
    }


def test_overrides_follows_the_base_list(graph):
    assert edges_of(graph, "OVERRIDES") == {
        ("OVERRIDES", 0.90, "mro", f"{ORDERS_PATH}::OrderService.Save", f"{ORDERS_PATH}::IOrderRepo.Save"),
    }


def test_a_struct_record_enum_and_nested_type_are_all_classes():
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public record Money(int Cents);\n"
                "\n"
                "public struct Pt { }\n"
                "\n"
                "public enum Kind { A, B }\n"
                "\n"
                "public class Outer\n"
                "{\n"
                "    public class Inner { public void Go() { } }\n"
                "}\n"
            )
        }
    )
    assert [(s.qualname, s.kind) for s in graph.symbols] == [
        ("a.App", "module"),
        ("Money", "class"),
        ("Pt", "class"),
        ("Kind", "class"),
        ("Outer", "class"),
        ("Outer.Inner", "class"),
        ("Outer.Inner.Go", "method"),
    ]
    assert by_qualname(graph, "a/App.cs", "Money").params == ["Cents"]
    assert ("CONTAINS", "a/App.cs::Outer", "a/App.cs::Outer.Inner") in links(graph, "CONTAINS")


def test_constructors_destructors_and_operators_are_methods():
    """A destructor is `~Base`, so it cannot collide with the constructor of the same name."""
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class Base\n"
                "{\n"
                "    public Base() { }\n"
                "\n"
                "    ~Base() { }\n"
                "\n"
                "    public static Base operator +(Base a, Base b) => a;\n"
                "}\n"
            )
        }
    )
    assert [(s.qualname, s.kind) for s in graph.symbols if s.kind == "method"] == [
        ("Base.Base", "method"),
        ("Base.~Base", "method"),
        ("Base.operator+", "method"),
    ]


def test_a_partial_class_keeps_both_halves_distinct():
    """
    `symbol_id` is namespaced by path, so the two halves are two nodes; the namespace scope
    lists the first one declared, and each file's module CONTAINS its own.
    """
    graph = graph_of(
        {
            "a/One.cs": "namespace App;\n\npublic partial class Service { public void A() { } }\n",
            "a/Two.cs": "namespace App;\n\npublic partial class Service { public void B() { } }\n",
        }
    )
    halves = [s for s in graph.symbols if s.qualname == "Service"]
    assert len(halves) == 2 and halves[0].id != halves[1].id
    assert ("CONTAINS", "a/One.cs::Service", "a/One.cs::Service.A") in links(graph, "CONTAINS")
    assert ("CONTAINS", "a/Two.cs::Service", "a/Two.cs::Service.B") in links(graph, "CONTAINS")


# ------------------------------------------------------- raises and catches


def test_raises_and_catches(graph):
    """
    C# gets both (the plan's decision). `throw new X` and `catch (X e)` reach an in-repo
    class; anything else that merely looks like an exception lands on `Symbol.raises` with no
    edge at all.
    """
    assert edges_of(graph, "CATCHES") == {
        ("CATCHES", 0.90, "resolved", f"{ORDERS_PATH}::OrderService.Place", f"{STORE_PATH}::OrderError"),
    }
    assert edges_of(graph, "RAISES") == set()
    assert by_qualname(graph, ORDERS_PATH, "OrderService.Place").raises == ["InvalidOperationException"]


def test_a_throw_of_an_in_repo_class_is_a_raises_edge():
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class OrderError : Exception { }\n"
                "\n"
                "public class Service\n"
                "{\n"
                "    public void Go() { throw new OrderError(); }\n"
                "}\n"
            )
        }
    )
    assert edge(graph, "RAISES", "a/App.cs::Service.Go", "a/App.cs::OrderError")[1:3] == (0.90, "resolved")
    # ...and it is a RAISES edge, not *also* a call to the class.
    assert ("INVOKES", "a/App.cs::Service.Go", "a/App.cs::OrderError") not in links(graph, "INVOKES")


def test_a_bare_throw_and_a_bare_catch_name_nothing():
    """`throw;` re-raises and `catch { }` says nothing about the type, so neither is a fact."""
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class OrderError : Exception { }\n"
                "\n"
                "public class Service\n"
                "{\n"
                "    public void Go()\n"
                "    {\n"
                "        try { Work(); } catch { throw; }\n"
                "    }\n"
                "}\n"
            )
        }
    )
    assert links(graph, "RAISES") == set() and links(graph, "CATCHES") == set()


# ------------------------------------------------------------- data access


def test_data_objects_from_literals_and_a_collection_chain(graph):
    """
    A SQL literal, a Cypher literal and a Mongo chain. `GetCollection<Order>("archive_orders")`
    is the C# spelling of the collection marker, and `InsertOneAsync` is `InsertOne` with
    ceremony -- the trailing `Async` comes off before the driver names are consulted.
    """
    assert [(d.kind, d.qualname, d.dialect) for d in graph.data_objects] == [
        ("collection", "archive_orders", "mongo"),
        ("label", "Customer", "cypher"),
        ("label", "Order", "cypher"),
        ("rel_type", "PLACED_BY", "cypher"),
        ("table", "orders", "sql"),
    ]
    assert edge(graph, "READS", f"{ORDERS_PATH}::OrderService.ListOpen", "table:orders")[1:3] == (
        0.85,
        "sql_literal",
    )
    assert edge(graph, "WRITES", f"{ORDERS_PATH}::OrderService.Archive", "collection:archive_orders")[
        1:3
    ] == (0.85, "mongo_chain")


def test_every_string_spelling_reaches_the_classifier():
    """
    Verbatim, interpolated and raw literals all carry SQL. An interpolation hole becomes `?`
    rather than a guess at what it holds -- which is also its limit: a hole where the dialect
    needs a value (`= {id}`, unquoted) leaves a statement sqlglot will not parse, and the
    shared classifier then finds nothing. That is true of every language's placeholders, not
    just C#'s.
    """
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class Service\n"
                "{\n"
                '    public void A() { db.Run(@"SELECT id FROM verbatim_orders"); }\n'
                "    public void B() { db.Run($\"SELECT id FROM interpolated_orders WHERE id = '{id}'\"); }\n"
                '    public void C() { db.Run("""SELECT id FROM raw_orders"""); }\n'
                "}\n"
            )
        }
    )
    assert {d.qualname for d in graph.data_objects} == {
        "verbatim_orders",
        "interpolated_orders",
        "raw_orders",
    }


# -------------------------------------------------------------- test code


def test_is_test_path_knows_the_c_sharp_conventions():
    """A `.Tests` project and a `*Tests.cs` class -- neither matches the shared default."""
    assert csharp.is_test_path("csapp/Orders.Tests/OrderServiceTests.cs") is True
    assert csharp.is_test_path("csapp/Orders.Tests/Helpers.cs") is True
    assert csharp.is_test_path("src/OrderServiceTests.cs") is True
    assert csharp.is_test_path("src/OrderServiceTest.cs") is True
    assert csharp.is_test_path("tests/Anything.cs") is True
    assert csharp.is_test_path("csapp/Orders/OrderService.cs") is False
    assert csharp.is_test_path("csapp/Latest/Contest.cs") is False


def test_test_stem_names_the_class_under_test():
    assert csharp.test_stem("csapp/Orders.Tests/OrderServiceTests.cs") == "OrderService"
    assert csharp.test_stem("csapp/Orders.Tests/OrderServiceTest.cs") == "OrderService"
    assert csharp.test_stem("csapp/Orders/OrderService.cs") is None
    assert csharp.test_stem("csapp/Orders.Tests/Tests.cs") is None


def test_an_attribute_marks_a_test_and_so_does_the_path(graph):
    """Every symbol in a test file is test code; `[Fact]` says so even outside one."""
    assert all(s.is_test for s in graph.symbols if s.path == TESTS_PATH)
    assert not by_qualname(graph, ORDERS_PATH, "OrderService.Place").is_test

    attributed = graph_of(
        {
            "a/Cases.cs": (
                "namespace App;\n"
                "\n"
                "public class Cases\n"
                "{\n"
                "    [Theory]\n"
                "    public void Works() { }\n"
                "\n"
                "    public void Helper() { }\n"
                "}\n"
            )
        }
    )
    assert by_qualname(attributed, "a/Cases.cs", "Cases.Works").is_test is True
    assert by_qualname(attributed, "a/Cases.cs", "Cases.Helper").is_test is False
    assert by_qualname(attributed, "a/Cases.cs", "Cases").is_test is False


def test_tested_by_all_three_provenances(graph):
    """
    A resolved call out of a test method is `test_import` 0.85; the file named after the
    module under test is `test_filename` 0.75. Both are true of this tree, and `merge_edges`
    keeps the higher ω for a pair that earns two.
    """
    assert edges_of(graph, "TESTED_BY") == {
        (
            "TESTED_BY",
            0.85,
            "test_import",
            f"{ORDERS_PATH}::OrderService",
            f"{TESTS_PATH}::OrderServiceTests.Place_totals",
        ),
        (
            "TESTED_BY",
            0.85,
            "test_import",
            f"{ORDERS_PATH}::OrderService.Place",
            f"{TESTS_PATH}::OrderServiceTests.Place_totals",
        ),
        (
            "TESTED_BY",
            0.75,
            "test_filename",
            f"{ORDERS_PATH}::csapp.Orders.OrderService",
            f"{TESTS_PATH}::csapp.Orders.Tests.OrderServiceTests",
        ),
    }


def test_a_test_case_is_an_attribute_not_a_name():
    """
    `is_test_function` is C#'s own: `Place_totals` does not start with `test`, and the shared
    default would drop every TESTED_BY `test_import` edge the language can produce.
    """
    graph = graph_of(
        {
            "a/Service.cs": "namespace App;\n\npublic class Service { public int Reconcile() => 1; }\n",
            "a/ServiceTests.cs": (
                "namespace App;\n"
                "\n"
                "public class ServiceTests\n"
                "{\n"
                "    [Fact]\n"
                "    public void Reconciles() { new Service().Reconcile(); }\n"
                "}\n"
            ),
        }
    )
    assert (
        "TESTED_BY",
        0.85,
        "test_import",
        "a/Service.cs::Service.Reconcile",
        "a/ServiceTests.cs::ServiceTests.Reconciles",
    ) in edges_of(graph, "TESTED_BY")


# ------------------------------------------------------------- properties


def test_a_property_is_not_a_symbol_but_its_body_is_walked():
    """
    Properties, fields and events stay in the class header passage. An accessor with a body
    still holds calls and literals, and they are attributed to the class that declares it --
    which is what keeps a SQL string inside a property from vanishing.
    """
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class Service\n"
                "{\n"
                "    public int Amount() => 1;\n"
                "\n"
                '    public string Open => db.Run("SELECT id FROM property_orders");\n'
                "\n"
                "    public string Name { get; set; }\n"
                "}\n"
            )
        }
    )
    assert [s.qualname for s in graph.symbols] == ["a.App", "Service", "Service.Amount"]
    assert edge(graph, "READS", "a/App.cs::Service", "table:property_orders")[1:3] == (0.85, "sql_literal")


def test_a_local_function_folds_into_its_method():
    """A local function is not a symbol; what it calls belongs to the method holding it."""
    graph = graph_of(
        {
            "a/App.cs": (
                "namespace App;\n"
                "\n"
                "public class Service\n"
                "{\n"
                "    public int Amount() => 1;\n"
                "\n"
                "    public int Go()\n"
                "    {\n"
                "        int Helper() => this.Amount();\n"
                "        return Helper();\n"
                "    }\n"
                "}\n"
            )
        }
    )
    assert [s.qualname for s in graph.symbols] == ["a.App", "Service", "Service.Amount", "Service.Go"]
    assert edge(graph, "INVOKES", "a/App.cs::Service.Go", "a/App.cs::Service.Amount")[1:3] == (
        1.00,
        "same_file",
    )


# ------------------------------------------------------------ the contract


def test_contains_edges_come_straight_from_the_syntax(graph):
    assert links(graph, "CONTAINS") >= {
        ("CONTAINS", f"{ORDERS_PATH}::csapp.Orders.OrderService", f"{ORDERS_PATH}::OrderService"),
        ("CONTAINS", f"{ORDERS_PATH}::csapp.Orders.OrderService", f"{ORDERS_PATH}::IOrderRepo"),
        ("CONTAINS", f"{ORDERS_PATH}::OrderService", f"{ORDERS_PATH}::OrderService.Place"),
        ("CONTAINS", f"{ORDERS_PATH}::IOrderRepo", f"{ORDERS_PATH}::IOrderRepo.Save"),
    }


def test_extraction_is_deterministic():
    """Same bytes, same graph -- ids, edges and order alike. `expected.json` rests on this."""
    first, second = graph_of(TREE), graph_of(TREE)
    assert [s.id for s in first.symbols] == [s.id for s in second.symbols]
    assert [(e.a, e.b, e.kind, e.omega, e.provenance) for e in first.edges] == [
        (e.a, e.b, e.kind, e.omega, e.provenance) for e in second.edges
    ]
    assert first.stats() == second.stats()


def test_a_file_that_is_not_c_sharp_is_untouched():
    """The walker only ever sees `.cs`; a Ruby file stays `unsupported` and keeps line windows."""
    graph = graph_of({"a/App.cs": "namespace App;\n\npublic class C { }\n", "tools/build.rb": "puts 1\n"})
    assert graph.files_skipped == {"tools/build.rb": "unsupported"}
