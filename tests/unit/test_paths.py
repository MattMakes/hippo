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
from tests.fakes.code_fixture import write_commit_history

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


def vertex(index: GraphIndex, name: str) -> int:
    return index.idx_of[resolve_symbol(index, name)]


def lines(index: GraphIndex, edges) -> list[str]:
    return render_triples(triple_rows(index, edges))


# ---------------------------------------------------------------- resolving


def test_a_fully_qualified_name_resolves(index: GraphIndex) -> None:
    node_id = resolve_symbol(index, "pyapp.orders.OrderService.place")
    assert display_of(index.code_node_by_id(node_id)) == "pyapp.orders.OrderService.place"


def test_a_module_relative_qualname_and_a_bare_name_resolve(index: GraphIndex) -> None:
    assert resolve_symbol(index, "OrderService.place") == resolve_symbol(
        index, "pyapp.orders.OrderService.place"
    )
    assert resolve_symbol(index, "list_open") == resolve_symbol(index, "OrderService.list_open")


def test_an_id_resolves_to_itself(index: GraphIndex) -> None:
    node_id = resolve_symbol(index, "OrderService.save")
    assert resolve_symbol(index, node_id) == node_id


def test_an_ambiguous_name_lists_its_candidates(index: GraphIndex) -> None:
    with pytest.raises(AmbiguousSymbol) as raised:
        resolve_symbol(index, "log")
    assert raised.value.candidates == [
        "pyapp.orders.OrderService.log",
        "pyapp.store.Base.log",
        "tsapp.models.base.Base.log",
    ]
    assert "could mean any of" in str(raised.value)


def test_an_unknown_name_raises(index: GraphIndex) -> None:
    with pytest.raises(UnknownSymbol):
        resolve_symbol(index, "no_such_thing")
    with pytest.raises(UnknownSymbol):
        resolve_symbol(index, "")


def test_module_qualnames_come_from_the_path(index: GraphIndex) -> None:
    assert module_of("pyapp/orders.py") == "pyapp.orders"
    assert module_of("pyapp/__init__.py") == "pyapp.__init__"  # S2.6 keeps the trailing __init__
    assert display_of(index.code_node_by_id(resolve_symbol(index, "table orders"))) == "table orders"


# ------------------------------------------------------------------ walking


def test_a_direct_call_renders_exactly(index: GraphIndex) -> None:
    walk = shortest_code_path(
        index, vertex(index, "OrderService.place"), vertex(index, "pyapp.billing.total"), theta=THETA
    )
    assert lines(index, walk) == [
        "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total"
    ]


def test_a_data_access_edge_renders_with_its_kind_and_confidence(index: GraphIndex) -> None:
    walk = shortest_code_path(
        index, vertex(index, "OrderService.save"), vertex(index, "table orders"), theta=THETA
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
    caller, callee = vertex(index, "OrderService.graph"), vertex(index, "OrderService.run")
    assert lines(index, shortest_code_path(index, caller, callee, theta=0.5)) == [
        "pyapp.orders.OrderService.graph -[INVOKES 0.50 fuzzy_name]-> pyapp.orders.OrderService.run"
    ]
    assert len(shortest_code_path(index, caller, callee, theta=0.6)) == 2
    assert not [e for e in direct_edges(index, caller, theta=0.6) if e.kind == "INVOKES"]


def test_a_backwards_pair_is_found_by_the_undirected_second_pass(index: GraphIndex) -> None:
    total, place = vertex(index, "pyapp.billing.total"), vertex(index, "OrderService.place")
    walk = shortest_code_path(index, total, place, theta=THETA)
    # The edge comes back pointing the way it really points, so the rendered line stays true.
    assert lines(index, walk) == [
        "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total"
    ]


def test_defined_in_is_never_a_step_in_a_path(index: GraphIndex) -> None:
    seeds = [vertex(index, n) for n in ("OrderService.place", "OrderService.save")]
    edges = code_paths_for(index, seeds, theta=THETA)
    assert edges
    assert {e.kind for e in edges}.isdisjoint({"DEFINED_IN", "REFERS_TO", "PRECEDES", "MODIFIES"})
    assert all(e.kind not in paths.NOT_A_STEP for e in direct_edges(index, seeds[0], theta=THETA))


def test_a_path_to_itself_is_empty(index: GraphIndex) -> None:
    place = vertex(index, "OrderService.place")
    assert shortest_code_path(index, place, place, theta=THETA) == []


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
    walk = exception_path(index, vertex(index, "OrderService.save"), "OrderError", theta=THETA)
    assert lines(index, walk) == [
        "pyapp.orders.OrderService.save -[RAISES 0.90 resolved]-> pyapp.store.OrderError"
    ]


def test_exception_path_for_an_unknown_exception_raises(index: GraphIndex) -> None:
    with pytest.raises(UnknownSymbol):
        exception_path(index, vertex(index, "OrderService.save"), "NoSuchError", theta=THETA)


def test_history_lists_the_commits_that_touched_a_symbol_newest_first(
    index_with_history: GraphIndex,
) -> None:
    index = index_with_history
    commits = history(index, vertex(index, "OrderService.place"), limit=3)
    assert [c.sha for c in commits] == ["b2b2b2b"]
    assert history_rows(commits) == [
        {"id": commits[0].id, "sha": "b2b2b2b", "date": "2026-01-02", "subject": "Total the order in place"}
    ]


def test_tests_for_finds_the_covering_test(index: GraphIndex) -> None:
    covering = paths.tests_for(index, [vertex(index, "OrderService.place")], theta=THETA)
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
        vertex(index, "OrderService.place"),
        vertex(index, "pyapp.billing.send_invoice"),
        theta=THETA,
    )
    assert lines(index, walk) == [
        "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import in_branch]-> pyapp.billing.send_invoice"
    ]


def block_trace(index: GraphIndex):
    seeds = [vertex(index, "OrderService.place")]
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

    place, total = vertex(index, "OrderService.place"), vertex(index, "pyapp.billing.total")
    index.graph_with_edits([EdgeEdit(index.node_ids[place], index.node_ids[total], 0.0)])
    assert shortest_code_path(index, place, total, theta=THETA)
