"""PA2 finding 4: a managed row's code edges are its selected generation's own rows.

`status.source_view` counted every `CODE_EDGE_KINDS` arrow in the held graph whose source vertex
was in the row's contributed node set. That is attribution by node membership: nothing ties an
arrow on a vertex to the generation the row presents, and a shared vertex carries every
contributor's arrows. CC10 made it reachable by dispatching managed code generations, which
write native `CODE_EDGE` rows under their `generation_id`. The structural projection serves none
of those rows as arrows, so the node walk reported a published repository as having no code
edges at all, while an arrow that did land on one of its vertices would have been counted
whichever generation it came from.

A managed row now counts native code relations from one scoped
`_native_relationships(generation_id=...)` read of its proven selected pair, the gate the
relation-predicate counter already used. The oracle below never uses that read: it takes the
store's whole-table `load_code_edges()` and keeps the rows whose endpoints are the generation's
own native rows, found through the whole-table `load_symbols()`/`load_data_objects()`.
"""

from collections import Counter
from dataclasses import replace

import pytest

from hippo.access import EVERYTHING
from hippo.codegraph.model import CODE_EDGE_KINDS
from hippo.hipporag.graph_index import DirectedEdge
from hippo.knowledge.query_access import query_session
from hippo.status import source_view
from tests.unit.test_code_generation import ORDERS_V1, _commit, build, head_of, world  # noqa: F401
from tests.unit.test_managed_source_inventory import row_of, tombstone
from tests.unit.test_structural_loading import Offline

# One more module-level function, so a refreshed generation holds a different set of code edges.
AUDITED = ORDERS_V1 + "\n\ndef audit(order):\n    return order\n"


def generation_edges(store, generation_id):
    """The oracle: every stored code edge whose endpoints are both this generation's own rows."""
    own = {
        row["id"]
        for row in [*store.load_symbols(), *store.load_data_objects()]
        if row.get("generation_id") == generation_id
    }
    return Counter(row["kind"] for row in store.load_code_edges() if row["a"] in own and row["b"] in own)


def code_edges(row):
    """A row's native code relation counts, apart from any relation predicate it also carries."""
    counts = (((row or {}).get("meta") or {}).get("code") or {}).get("edges_by_kind") or {}
    return {kind: count for kind, count in counts.items() if kind in CODE_EDGE_KINDS}


def code_row(ctx, source_id):
    """The source's row from one fresh structural session, released before returning."""
    with query_session(ctx, EVERYTHING, structural=True) as session:
        return row_of(source_view(ctx, EVERYTHING, session=session), source_id)


def refresh_tree(w):
    """The same repository one commit later, with one more function in `orders.py`."""
    (w.checkout / "src" / "orders.py").write_text(AUDITED)
    _commit(w.checkout, "Add an audit helper", 3)
    return replace(w.tree, head_revision=head_of(w.checkout))


# ----------------------------------------------------------- the selected generation


def test_a_published_code_generation_counts_exactly_its_own_code_edge_rows(world):  # noqa: F811
    w = world
    result = build(w)
    expected = generation_edges(w.store, result.generation_id)
    assert expected, "the fixture repository must produce native code edges"

    row = code_row(w.ctx, w.source)

    assert code_edges(row) == dict(expected)
    assert row["meta"]["code"]["edges"] == sum(row["meta"]["code"]["edges_by_kind"].values())


def test_a_staged_second_generation_adds_nothing_until_it_publishes_and_then_replaces_the_count(
    world,  # noqa: F811
):
    """Observed at the coordinator's `seal` step: every edge is staged and nothing is published."""
    w = world
    first = build(w)
    before = generation_edges(w.store, first.generation_id)
    tree = refresh_tree(w)
    staged = []

    def watch(progress):
        if progress.phase != "seal" or staged:
            return
        generation = next(row for row in w.store._knowledge_rows("Generation") if row.status == "staging")
        staged.append((generation.id, generation_edges(w.store, generation.id), code_row(w.ctx, w.source)))

    second = build(w, operation="refresh", tree=tree, on_progress=watch)

    ((staged_id, staged_edges, during),) = staged
    assert staged_id == second.generation_id
    assert staged_edges and staged_edges != before, "the staged generation must hold different code edges"
    assert code_edges(during) == dict(before)
    assert generation_edges(w.store, second.generation_id) == staged_edges
    assert code_edges(code_row(w.ctx, w.source)) == dict(staged_edges)


def test_a_tombstoned_code_source_shows_no_code_edges(world):  # noqa: F811
    w = world
    result = build(w)
    assert code_edges(code_row(w.ctx, w.source))

    tombstone(w.store, w.source)

    with query_session(w.ctx, EVERYTHING, structural=True) as session:
        assert session.graph.selected_managed_generations == ()
        assert row_of(source_view(w.ctx, EVERYTHING, session=session), w.source) is None
    # Retained and unselected: the count went with the pair, not with a physical delete.
    assert generation_edges(w.store, result.generation_id)


def test_an_edge_straddling_two_generations_is_refused_and_never_counted(world):  # noqa: F811
    w = world
    first = build(w)
    second = build(w, operation="refresh", tree=refresh_tree(w))
    symbols = w.store.load_symbols()
    retired = next(row["id"] for row in symbols if row.get("generation_id") == first.generation_id)
    active = next(row["id"] for row in symbols if row.get("generation_id") == second.generation_id)
    counted = code_edges(code_row(w.ctx, w.source))
    assert counted == dict(generation_edges(w.store, second.generation_id))

    with pytest.raises(ValueError, match="Native relationship crosses generations"):
        w.store.add_code_edges([{"a": active, "b": retired, "kind": "INVOKES", "omega": 1.0}])

    assert not any(row["a"] == active and row["b"] == retired for row in w.store.load_code_edges())
    assert code_edges(code_row(w.ctx, w.source)) == counted


def test_an_arrow_on_the_sources_own_vertex_is_not_a_row_of_its_generation(world):  # noqa: F811
    """The finding's own shape: vertex membership is not generation membership.

    An arrow that lands on one of the source's vertices -- from another generation, or from
    another contributor to a shared vertex -- is not one of the selected generation's rows, so
    it must not change the count however it reached the held graph.
    """
    w = world
    result = build(w)
    expected = dict(generation_edges(w.store, result.generation_id))
    with query_session(w.ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        own = [graph.idx_of[node.id] for node in graph.code_nodes if node.source_id == w.source]
        assert len(own) >= 2
        graph.code_out.setdefault(own[0], []).append(DirectedEdge(own[0], own[1], "INVOKES", 1.0))
        row = row_of(source_view(w.ctx, EVERYTHING, session=session), w.source)

    assert code_edges(row) == expected


# ------------------------------------------------------------------ the legacy lane


def test_a_legacy_repository_keeps_the_count_its_source_row_has_always_presented(ctx, monkeypatch):
    """Untagged rows only, read from the Source row as before; no generation read happens."""
    store = ctx.store
    meta = {"code": {"symbols": 2, "edges": 1, "edges_by_kind": {"INVOKES": 1}, "languages": ["python"]}}
    source = store.create_source("repo", "legacy robots", meta)
    symbols = [
        dict(
            id=f"sym-legacy-{index}",
            source_id=source,
            name="f",
            qualname="f",
            kind="function",
            path=f"a{index}.py",
            embedding=[0.1, 0.2],
        )
        for index in range(2)
    ]
    store.add_symbols(symbols)
    store.add_code_edges([{"a": symbols[0]["id"], "b": symbols[1]["id"], "kind": "INVOKES", "omega": 1.0}])
    presented = next(row for row in store.list_sources(EVERYTHING) if row["id"] == source)
    reads, original = [], store._native_relationships

    def record(**keys):
        reads.append(keys)
        return original(**keys)

    monkeypatch.setattr(store, "_native_relationships", record)
    ctx.ollama = Offline()
    with query_session(ctx, EVERYTHING, structural=True) as session:
        view = source_view(ctx, EVERYTHING, session=session)
        assert source in view.legacy_ids
        assert row_of(view, source) == presented
    assert row_of(view, source)["meta"] == meta
    assert reads == []
