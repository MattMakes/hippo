"""
hipporag/paths.py: walking the directed code graph, and how the answer block reads.

The graph PPR runs on is undirected, so everything about direction - who calls whom, what a change
would break, which commits touched a function - lives here. These tests pin the walking rules
(`DEFINED_IN` is never a step, `code_theta` filters, a directed search falls back to an undirected
one) and the block's grammar, which `test_ask.py` then asserts end to end.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hippo.hipporag import paths
from hippo.hipporag.graph_index import GraphIndex
from hippo.hipporag.paths import (
    AmbiguousSymbol,
    UnknownSymbol,
    blast_radius,
    code_paths_for,
    cut_to,
    direct_edges,
    display_of,
    exception_path,
    history,
    history_rows,
    module_of,
    render_blast,
    render_block,
    render_triples,
    resolve_symbol,
    shortest_code_path,
    triple_rows,
)
from tests.fakes.code_fixture import call_hub, module_and_its_namesake, write_commit_history

THETA = 0.5
HEADER = "Relations from the code graph."


@pytest.fixture
def index(code_index) -> GraphIndex:
    """`tests/fixtures/code_sample/` indexed through the real pipeline, extractor and all."""
    ctx, _source_id = code_index
    return ctx.graph()


@pytest.fixture
def index_with_history(code_index) -> GraphIndex:
    """The same tree plus three commits. WP2b builds these from a real checkout; `GraphIndex` has
    loaded `Commit`, `MODIFIES` and `PRECEDES` since WP1, so the tools need nothing from it."""
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    return ctx.graph()


@pytest.fixture
def index_with_hub(code_index) -> tuple[GraphIndex, dict[str, str]]:
    """The tree plus QA1 defect 1's shape: a ten-call hub with one caller, and a second seed."""
    ctx, source_id = code_index
    names = call_hub(ctx, source_id)
    return ctx.graph(), names


def vertex(index: GraphIndex, name: str) -> int:
    return index.idx_of[resolve_symbol(index, name)]


def lines(index: GraphIndex, edges) -> list[str]:
    return render_triples(triple_rows(index, edges))


# ---------------------------------------------------------------- resolving


def test_a_fully_qualified_name_resolves(index: GraphIndex) -> None:
    node_id = resolve_symbol(index, "pyapp.orders.OrderService.place")
    assert display_of(index.code_node_by_id(node_id)) == "pyapp.orders.OrderService.place"


def test_a_module_relative_qualname_and_a_bare_name_resolve(index: GraphIndex) -> None:
    # `run` is the one method of `OrderService` the Rust tree does not also have, so it is still
    # the single symbol a short name can mean; every other short name here is now ambiguous, which
    # is what the test below pins.
    assert resolve_symbol(index, "OrderService.run") == resolve_symbol(index, "pyapp.orders.OrderService.run")
    assert resolve_symbol(index, "run") == resolve_symbol(index, "OrderService.run")


def test_an_id_resolves_to_itself(index: GraphIndex) -> None:
    node_id = resolve_symbol(index, "pyapp.orders.OrderService.save")
    assert resolve_symbol(index, node_id) == node_id


def test_an_ambiguous_name_lists_its_candidates(index: GraphIndex) -> None:
    with pytest.raises(AmbiguousSymbol) as raised:
        resolve_symbol(index, "log")
    assert raised.value.candidates == [
        "csapp.Orders.OrderService.OrderService.Log",
        "csapp.Store.Base.Base.Log",
        "goapp.orders.service.Service.Log",
        "goapp.store.base.Base.Log",
        "pyapp.orders.OrderService.log",
        "pyapp.store.Base.log",
        "rsapp.src.orders.OrderService.log",
        "rsapp.src.store.Base.log",
        "tsapp.models.base.Base.log",
    ]
    assert "could mean any of" in str(raised.value)
    # A second tree telling the same story makes the *qualname* ambiguous too, not just the bare
    # name: `OrderService.place` is a symbol in `pyapp/orders.py`, one in `rsapp/src/orders.rs`
    # and -- the lookup lower-cases -- one in `csapp/Orders/OrderService.cs`.
    with pytest.raises(AmbiguousSymbol) as both:
        resolve_symbol(index, "OrderService.place")
    assert both.value.candidates == [
        "csapp.Orders.OrderService.OrderService.Place",
        "pyapp.orders.OrderService.place",
        "rsapp.src.orders.OrderService.place",
    ]


def test_an_unknown_name_raises(index: GraphIndex) -> None:
    with pytest.raises(UnknownSymbol):
        resolve_symbol(index, "no_such_thing")
    with pytest.raises(UnknownSymbol):
        resolve_symbol(index, "")


def test_a_module_and_its_namesake_read_as_two_different_names(ctx) -> None:
    """
    E2 defect 1's read side. Giving the two symbols two ids is only half the fix: `display_of`
    collapsed any `qualname == module` to the bare qualname, so `main.go`'s package and its
    `func main` both printed as `main`, `resolve_symbol("main")` raised `AmbiguousSymbol` with
    two IDENTICAL candidates, and `main.main` -- the name the function's own passage is titled
    with -- resolved to nothing at all. Only a module's qualname is collapsed now.

    A memory holding just the one file, because in the fixture tree `main` is a name seven
    symbols answer to and the ambiguity being pinned here is the one *inside* a single file.
    """
    source_id = ctx.store.create_source("archive", "goapp")
    ids = module_and_its_namesake(ctx, source_id)
    index = ctx.graph()

    assert display_of(index.code_node_by_id(ids["module"])) == "main"
    assert display_of(index.code_node_by_id(ids["function"])) == "main.main"
    # Each name reaches exactly one of them, and neither raises.
    assert resolve_symbol(index, "main") == ids["module"]
    assert resolve_symbol(index, "main.main") == ids["function"]


def test_a_display_name_outranks_a_qualname_that_spells_the_same_word(code_index) -> None:
    """
    The tier that makes the above work in a real memory. `main` is the qualname of seven symbols
    in the fixture tree and the *display name* of exactly one -- `main.go`'s package. One tier
    for both made every one of them a candidate and the answer an ambiguity; the display name is
    the more specific form and the docstring always said it was tried first.
    """
    ctx, source_id = code_index
    ids = module_and_its_namesake(ctx, source_id)
    index = ctx.graph()

    assert resolve_symbol(index, "main") == ids["module"]
    assert resolve_symbol(index, "main.main") == ids["function"]
    # The seven `main` functions are still reachable, each by its own display name.
    assert display_of(index.code_node_by_id(resolve_symbol(index, "pyapp.cli.main"))) == "pyapp.cli.main"
    # And a word that is nobody's display name is as ambiguous as it ever was.
    with pytest.raises(AmbiguousSymbol) as raised:
        resolve_symbol(index, "log")
    assert len(raised.value.candidates) == 9


def test_module_qualnames_come_from_the_path(index: GraphIndex) -> None:
    assert module_of("pyapp/orders.py") == "pyapp.orders"
    assert module_of("pyapp/__init__.py") == "pyapp.__init__"  # S2.6 keeps the trailing __init__
    assert display_of(index.code_node_by_id(resolve_symbol(index, "table orders"))) == "table orders"


# ------------------------------------------------------------------ walking


def test_a_direct_call_renders_exactly(index: GraphIndex) -> None:
    walk = shortest_code_path(
        index,
        vertex(index, "pyapp.orders.OrderService.place"),
        vertex(index, "pyapp.billing.total"),
        theta=THETA,
    )
    assert lines(index, walk) == [
        "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total"
    ]


def test_the_same_call_in_the_rust_tree_renders_the_same_way(index: GraphIndex) -> None:
    """
    `hippo path rsapp.src.orders.OrderService.place rsapp.src.billing.total`: one story in two
    languages, one grammar. The tier is 0.90 `via_import` -- the call goes through a `use` -- and
    Rust can never reach the 1.00 `same_scope` tier at all, because its walker sets no
    `FileFacts.scope` for a language whose modules are files rather than a declared package.
    """
    walk = shortest_code_path(
        index,
        vertex(index, "rsapp.src.orders.OrderService.place"),
        vertex(index, "rsapp.src.billing.total"),
        theta=THETA,
    )
    assert lines(index, walk) == [
        "rsapp.src.orders.OrderService.place -[INVOKES 0.90 via_import]-> rsapp.src.billing.total"
    ]
    assert not any(e.provenance == "same_scope" for e in direct_edges(index, walk[0].src, theta=THETA))


def test_the_same_call_in_the_go_tree_renders_the_same_way(index: GraphIndex) -> None:
    """
    `hippo path goapp.orders.service.Service.Place goapp.billing.billing.Total`: the third telling
    of the same story, and the same 0.90 `via_import` tier -- the call goes through an `import` of
    another package. Go *can* reach 1.00 `same_scope` (the next test), which is why this one says
    which of the two a cross-package call is.
    """
    walk = shortest_code_path(
        index,
        vertex(index, "goapp.orders.service.Service.Place"),
        vertex(index, "goapp.billing.billing.Total"),
        theta=THETA,
    )
    assert lines(index, walk) == [
        "goapp.orders.service.Service.Place -[INVOKES 0.90 via_import]-> goapp.billing.billing.Total"
    ]


def test_a_go_test_in_the_same_package_calls_at_the_same_scope_tier(index: GraphIndex) -> None:
    """
    The 1.00 `same_scope` tier, which only a language with a real package has: `service_test.go`
    imports nothing to reach `Service` -- it is in the same directory, and in Go that *is* the
    package. The 0.85 `test_import` TESTED_BY edge runs the other way over the same call.
    """
    walk = shortest_code_path(
        index,
        vertex(index, "goapp.orders.service_test.TestPlace"),
        vertex(index, "goapp.orders.service.Service.Place"),
        theta=THETA,
    )
    assert lines(index, walk) == [
        "goapp.orders.service_test.TestPlace -[INVOKES 1.00 same_scope]-> goapp.orders.service.Service.Place"
    ]


def test_the_same_call_in_the_csharp_tree_renders_the_same_way(index: GraphIndex) -> None:
    """
    `hippo path csapp.…OrderService.Place csapp.Billing.Billing.Billing.Total`: the fourth telling,
    and the same 0.90 `via_import` tier -- the call goes through `using CsApp.Billing;`. C# reaches
    1.00 `same_scope` for a *sibling of its namespace* (the walker's own tests pin that), which the
    fixture tree deliberately has no site for: two files declaring one namespace would make the
    IMPORTS edge for a `using` of it a choice between them.
    """
    walk = shortest_code_path(
        index,
        vertex(index, "csapp.Orders.OrderService.OrderService.Place"),
        vertex(index, "csapp.Billing.Billing.Billing.Total"),
        theta=THETA,
    )
    assert lines(index, walk) == [
        "csapp.Orders.OrderService.OrderService.Place "
        "-[INVOKES 0.90 via_import]-> csapp.Billing.Billing.Billing.Total"
    ]
    assert not any(e.provenance == "same_scope" for e in direct_edges(index, walk[0].src, theta=THETA))


def test_a_csharp_entry_point_reaches_place_through_its_using(index: GraphIndex) -> None:
    """
    `csapp/Program.cs` is top-level statements, so the *module* is the caller. The `using` is what
    makes this an edge at all: phase A measured the same file without one at 0.50 `fuzzy_name`,
    pointing at the method with no edge to the class that holds it.
    """
    walk = shortest_code_path(
        index,
        vertex(index, "csapp.Program"),
        vertex(index, "csapp.Orders.OrderService.OrderService.Place"),
        theta=THETA,
    )
    assert lines(index, walk) == [
        "csapp.Program -[INVOKES 0.90 via_import]-> csapp.Orders.OrderService.OrderService.Place"
    ]


def test_a_data_access_edge_renders_with_its_kind_and_confidence(index: GraphIndex) -> None:
    walk = shortest_code_path(
        index, vertex(index, "pyapp.orders.OrderService.save"), vertex(index, "table orders"), theta=THETA
    )
    assert lines(index, walk) == ["pyapp.orders.OrderService.save -[WRITES 0.85 sql_literal]-> table orders"]


def test_a_two_hop_path_is_found(index: GraphIndex) -> None:
    walk = shortest_code_path(
        index, vertex(index, "pyapp.cli.main"), vertex(index, "pyapp.billing.total"), theta=THETA
    )
    assert lines(index, walk) == [
        "pyapp.cli.main -[INVOKES 0.90 via_import]-> pyapp.orders.OrderService.place",
        "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total",
    ]


def test_theta_above_an_edge_hides_it(index: GraphIndex) -> None:
    # `graph` calls `self.run` through an unresolvable receiver, so the resolver emits the 0.50
    # fuzzy-name tier for it. Above theta that call is gone and only the longer route survives.
    caller, callee = (
        vertex(index, "pyapp.orders.OrderService.graph"),
        vertex(index, "pyapp.orders.OrderService.run"),
    )
    assert lines(index, shortest_code_path(index, caller, callee, theta=0.5)) == [
        "pyapp.orders.OrderService.graph -[INVOKES 0.50 fuzzy_name]-> pyapp.orders.OrderService.run"
    ]
    assert len(shortest_code_path(index, caller, callee, theta=0.6)) == 2
    assert not [e for e in direct_edges(index, caller, theta=0.6) if e.kind == "INVOKES"]


def test_a_backwards_pair_is_found_by_the_undirected_second_pass(index: GraphIndex) -> None:
    total, place = vertex(index, "pyapp.billing.total"), vertex(index, "pyapp.orders.OrderService.place")
    walk = shortest_code_path(index, total, place, theta=THETA)
    # The edge comes back pointing the way it really points, so the rendered line stays true.
    assert lines(index, walk) == [
        "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total"
    ]


def test_defined_in_is_never_a_step_in_a_path(index: GraphIndex) -> None:
    names = ("pyapp.orders.OrderService.place", "pyapp.orders.OrderService.save")
    seeds = [vertex(index, n) for n in names]
    edges = code_paths_for(index, seeds, theta=THETA)
    assert edges
    assert {e.kind for e in edges}.isdisjoint({"DEFINED_IN", "REFERS_TO", "PRECEDES", "MODIFIES"})
    assert all(e.kind not in paths.NOT_A_STEP for e in direct_edges(index, seeds[0], theta=THETA))


def test_a_path_to_itself_is_empty(index: GraphIndex) -> None:
    place = vertex(index, "pyapp.orders.OrderService.place")
    assert shortest_code_path(index, place, place, theta=THETA) == []


def test_only_the_strongest_seeds_are_searched_against_each_other(index: GraphIndex, monkeypatch) -> None:
    """
    AR1 fix 6. `_explain_code` hands over up to MAX_CODE_SEEDS = 20 seeds in weight order, and
    every pair costs a directed *and* an undirected BFS whenever the two are unrelated - the
    common case. All 20 would be 190 pairs and 380 traversals per question.
    """
    names = (
        "pyapp.orders.OrderService.place",
        "pyapp.orders.OrderService.save",
        "pyapp.orders.OrderService.log",
        "pyapp.billing.total",
        "pyapp.cli.main",
        "pyapp.orders.OrderService.archive",
        "pyapp.orders.OrderService.list_open",
    )
    seeds = [vertex(index, name) for name in names]
    assert len(seeds) > paths.PAIRED_SEEDS

    searched: list[tuple[int, int]] = []
    real = paths.shortest_code_path
    monkeypatch.setattr(
        paths,
        "shortest_code_path",
        lambda idx, a, b, **kw: (searched.append((a, b)), real(idx, a, b, **kw))[1],
    )
    edges = code_paths_for(index, seeds, theta=THETA)

    top = seeds[: paths.PAIRED_SEEDS]
    assert len(searched) == len(top) * (len(top) - 1) // 2 == 10
    assert {v for pair in searched for v in pair} == set(top)
    # Every seed still contributes its own direct edges, capped or not.
    assert any(seeds[-1] in (e.src, e.dst) for e in edges)


def test_a_walk_gives_up_once_it_has_spent_its_visit_budget(index: GraphIndex, monkeypatch) -> None:
    # AR1 fix 6: `_bfs` had no time or visit budget at all - `cap` only truncates the result.
    main, total = vertex(index, "pyapp.cli.main"), vertex(index, "pyapp.billing.total")
    place = vertex(index, "pyapp.orders.OrderService.place")
    assert len(shortest_code_path(index, main, total, theta=THETA)) == 2

    monkeypatch.setattr(paths, "BFS_VISIT_BUDGET", 2)
    assert shortest_code_path(index, main, total, theta=THETA) == []  # two hops: budget spent
    assert len(shortest_code_path(index, main, place, theta=THETA)) == 1  # one hop still lands


# ------------------------------------------------------- relevance order (QA1 defect 1)
# The smoke's shape: a function whose own outgoing calls crowd `code_triples_chars` before its one
# caller is reached, so "where is X called" got a block that could not answer it.


def test_a_seeds_own_edges_come_back_strongest_first_in_before_out(index_with_hub) -> None:
    """
    Ten outgoing calls at ω 0.90-1.00 and one caller at 0.90, as `direct_edges` orders them.

    ω descending puts the four calls above 0.90 first; the in-before-out tie-break inside the 0.90
    tier then puts the caller ahead of the six calls it ties with. Out-then-in made it the eleventh.
    """
    graph, names = index_with_hub
    rendered = lines(graph, direct_edges(graph, vertex(graph, names["hub"]), theta=THETA))

    assert [float(line.split(" ")[2]) for line in rendered] == [1.0, 1.0, 0.95, 0.95] + [0.9] * 7
    assert rendered[4] == f"{names['caller']} -[INVOKES 0.90 via_import]-> {names['hub']}"
    assert all(line.startswith(names["hub"]) for line in rendered[:4] + rendered[5:])


def test_the_caller_survives_a_budget_that_only_fits_six_lines(index_with_hub) -> None:
    """The defect as a reader meets it: a block with room for six of the eleven relations."""
    graph, names = index_with_hub
    hub = vertex(graph, names["hub"])
    trace = SimpleNamespace(
        paths=triple_rows(graph, code_paths_for(graph, [hub], theta=THETA)), tests=[], history=[]
    )
    body = render_block(graph, trace, header=HEADER, max_chars=8000).splitlines()[1:]
    six = sum(len(line) for line in body[:6]) + 5  # exactly six lines' worth of budget

    kept = render_block(graph, trace, header=HEADER, max_chars=six).splitlines()[1:]
    assert len(kept) == 7 and kept[-1] == "… (+5 more)"  # six relations, then the count
    assert f"{names['caller']} -[INVOKES 0.90 via_import]-> {names['hub']}" in kept
    # The budget is genuinely the tight one: the hub's own calls alone would have filled it.
    assert len([line for line in body if line.startswith(names["hub"])]) == 10


def test_the_seeds_take_turns_so_a_hub_cannot_starve_the_next_seed(index_with_hub) -> None:
    """`code_paths_for` round-robins the seeds' direct edges rather than exhausting each in turn."""
    graph, names = index_with_hub
    seeds = [vertex(graph, names["hub"]), vertex(graph, names["other"])]
    rendered = lines(graph, code_paths_for(graph, seeds, theta=THETA))

    assert rendered[:3] == [
        f"{names['hub']} -[INVOKES 1.00 same_file]-> pkg.anchors._step0",
        f"{names['other']} -[INVOKES 0.90 same_file]-> {names['other_helper']}",  # its turn, at once
        f"{names['hub']} -[INVOKES 1.00 same_file]-> pkg.anchors._step1",
    ]


def test_the_same_relation_from_two_indexed_copies_is_shown_once(index_with_hub, code_index) -> None:
    """
    A repository indexed twice gives every symbol a same-named twin, so every edge of the overlap
    renders identically. The block dedupes on the two display names and the kind, not on the node
    ids (which carry the source), so the budget is not spent saying one thing twice (QA1 defect 1).
    """
    graph, names = index_with_hub
    ctx, _source_id = code_index
    call_hub(ctx, ctx.store.create_source("zip", "the same repository again"))
    twinned = ctx.graph()

    copies = [twinned.idx_of[n.id] for n in twinned.code_nodes if display_of(n) == names["hub"]]
    assert len(copies) == 2, "two node ids behind one display name"
    assert lines(twinned, code_paths_for(twinned, copies, theta=THETA)) == lines(
        graph, code_paths_for(graph, [vertex(graph, names["hub"])], theta=THETA)
    )


def test_display_at_is_memoised_on_the_index(index: GraphIndex) -> None:
    # `_walkable` sorts on two `display_at` calls per edge at every vertex a walk visits.
    place = vertex(index, "pyapp.orders.OrderService.place")
    assert index.display_cache == {}
    assert paths.display_at(index, place) == "pyapp.orders.OrderService.place"
    assert index.display_cache[place] == "pyapp.orders.OrderService.place"
    index.display_cache[place] = "cached"
    assert paths.display_at(index, place) == "cached"


# ------------------------------------------------------------- blast radius


def test_blast_radius_walks_callers_level_by_level(index: GraphIndex) -> None:
    blast = blast_radius(index, vertex(index, "pyapp.billing.total"), theta=THETA, depth=2)
    assert [sorted(display_of(index.code_node_at(v)) for v in level) for level in blast.levels] == [
        ["pyapp.billing", "pyapp.orders.OrderService.place"],
        [
            "pyapp.cli.main",
            "pyapp.orders",
            "pyapp.orders.OrderService",
            "tests.test_orders.test_place",
        ],
    ]
    assert blast.truncated is False


def test_blast_radius_says_when_the_cap_stopped_it(index: GraphIndex) -> None:
    blast = blast_radius(index, vertex(index, "pyapp.billing.total"), theta=THETA, depth=3, cap=2)
    assert blast.truncated is True
    assert len(blast.vertices) <= 2


def test_blast_radius_renders_grouped_by_subsystem(index: GraphIndex) -> None:
    blast = blast_radius(index, vertex(index, "pyapp.billing.total"), theta=THETA, depth=1)
    rendered = render_blast(index, blast)
    assert rendered[0] == "Level 1: pyapp.billing, pyapp.orders.OrderService.place"
    assert any(line.startswith("Subsystems: ") for line in rendered)


# ------------------------------------------------------- exceptions, history


def test_exception_path_finds_the_raise(index: GraphIndex) -> None:
    # The exception is named in full for the same reason every symbol here is: the Rust tree has an
    # `OrderError` of its own, so the short name is ambiguous.
    walk = exception_path(
        index, vertex(index, "pyapp.orders.OrderService.save"), "pyapp.store.OrderError", theta=THETA
    )
    assert lines(index, walk) == [
        "pyapp.orders.OrderService.save -[RAISES 0.90 resolved]-> pyapp.store.OrderError"
    ]


def test_exception_path_for_an_unknown_exception_raises(index: GraphIndex) -> None:
    with pytest.raises(UnknownSymbol):
        exception_path(index, vertex(index, "pyapp.orders.OrderService.save"), "NoSuchError", theta=THETA)


def test_history_lists_the_commits_that_touched_a_symbol_newest_first(
    index_with_history: GraphIndex,
) -> None:
    index = index_with_history
    commits = history(index, vertex(index, "pyapp.orders.OrderService.place"), limit=3)
    assert [c.sha for c in commits] == ["b2b2b2b"]
    assert history_rows(commits) == [
        {"id": commits[0].id, "sha": "b2b2b2b", "date": "2026-01-02", "subject": "Total the order in place"}
    ]


def test_tests_for_finds_the_covering_test(index: GraphIndex) -> None:
    covering = paths.tests_for(index, [vertex(index, "pyapp.orders.OrderService.place")], theta=THETA)
    assert paths.test_rows(index, covering) == [
        {
            "id": covering[0].id,
            "name": "tests.test_orders.test_place",
            "path": "tests/test_orders.py",
        }
    ]


# ---------------------------------------------------------------- rendering


def test_in_branch_and_await_flags_appear_in_the_line(index: GraphIndex) -> None:
    walk = shortest_code_path(
        index,
        vertex(index, "pyapp.orders.OrderService.place"),
        vertex(index, "pyapp.billing.send_invoice"),
        theta=THETA,
    )
    assert lines(index, walk) == [
        "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import in_branch]-> pyapp.billing.send_invoice"
    ]


def block_trace(index: GraphIndex):
    seeds = [vertex(index, "pyapp.orders.OrderService.place")]
    return SimpleNamespace(
        paths=triple_rows(index, code_paths_for(index, seeds, theta=THETA)),
        tests=paths.test_rows(index, paths.tests_for(index, seeds, theta=THETA)),
        history=history_rows(history(index, seeds[0])),
    )


def test_the_block_carries_triples_then_tests_commits_and_subsystems(
    index_with_history: GraphIndex,
) -> None:
    index = index_with_history
    block = render_block(index, block_trace(index), header=HEADER, max_chars=8000)
    body = block.splitlines()
    assert body[0] == HEADER
    assert "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total" in body
    assert "Tests: tests.test_orders.test_place" in body
    assert "Commits: b2b2b2b 2026-01-02 Total the order in place" in body
    assert any(line.startswith("Subsystems: ") for line in body)
    # The order of the four sections is part of the grammar.
    kinds = [line.split(":")[0] for line in body if line.startswith(("Tests", "Commits", "Subsystems"))]
    assert kinds == sorted(kinds, key=["Tests", "Commits", "Subsystems"].index)


def test_the_block_is_cut_on_a_line_boundary(index_with_history: GraphIndex) -> None:
    index = index_with_history
    trace = block_trace(index)
    full = render_block(index, trace, header=HEADER, max_chars=8000).splitlines()[1:]
    cut = render_block(index, trace, header=HEADER, max_chars=60).splitlines()[1:]
    assert cut[:-1] == full[: len(cut) - 1]
    assert cut[-1] == f"… (+{len(full) - len(cut) + 1} more)"
    assert sum(len(line) for line in cut[:-1]) + max(0, len(cut) - 2) <= 60


def test_a_zero_budget_keeps_no_line_but_still_counts_them(index: GraphIndex) -> None:
    body = render_block(index, block_trace(index), header=HEADER, max_chars=0).splitlines()
    assert body[0] == HEADER
    assert len(body) == 2 and body[1].startswith("… (+")


def test_cut_to_never_splits_a_line() -> None:
    assert cut_to(["aaa", "bbb"], 100) == ["aaa", "bbb"]
    assert cut_to(["aaa", "bbb"], 3) == ["aaa", "… (+1 more)"]
    assert cut_to([], 10) == []


def test_an_empty_block_renders_as_an_empty_string(index: GraphIndex) -> None:
    empty = SimpleNamespace(paths=[], tests=[], history=[])
    assert render_block(index, empty, header=HEADER, max_chars=1500) == ""


def test_simulation_edge_edits_do_not_reach_the_path_tools(index: GraphIndex) -> None:
    from hippo.hipporag.graph_index import EdgeEdit

    place, total = vertex(index, "pyapp.orders.OrderService.place"), vertex(index, "pyapp.billing.total")
    index.graph_with_edits([EdgeEdit(index.node_ids[place], index.node_ids[total], 0.0)])
    assert shortest_code_path(index, place, total, theta=THETA)


def test_a_scoped_index_cannot_be_walked_to_a_hidden_symbol(mixed_index) -> None:
    """
    S2.5's second leg. WP1 proved `scoped()` drops a hidden source's symbols and every edge
    touching them; this is the half that needed `paths.py`: the tools built on `code_out` cannot
    route through a vertex that is not there, and `resolve_symbol` cannot even name it.
    """
    ctx, prose_source_id, _code_source_id = mixed_index
    full = ctx.graph()
    place, total = vertex(full, "pyapp.orders.OrderService.place"), vertex(full, "pyapp.billing.total")
    assert shortest_code_path(full, place, total, theta=THETA)
    assert blast_radius(full, total, theta=THETA, depth=2).levels

    scoped = full.scoped({prose_source_id})
    assert scoped.code_nodes == []
    with pytest.raises(UnknownSymbol):
        resolve_symbol(scoped, "pyapp.orders.OrderService.place")
    assert code_paths_for(scoped, [], theta=THETA) == []
