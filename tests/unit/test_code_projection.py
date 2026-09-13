"""A published managed code generation serves the structural arrows a legacy code source serves.

Ruling 1 of `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` keeps code relations
native: the code lane seals `CODE_EDGE`, `DEFINED_IN`, `MODIFIES` and `PRECEDES` rows in the
generation's native representation and writes no assertion for them. Before this slice the
structural projection read none of them, so a published repository served no arrow at all: every
symbol passage is a rendered view (the chunker's context header), a code `DerivedRecord` carries
no binding ids, and the only `DEFINED_IN` rule the projection had needs them.

The projection now reads each selected generation's sealed relations once, between endpoints the
proof already projects, and every arrow names the generation and the originals that support it.
Ruling 14 bounds the read: a staged, failed, retired or tombstoned generation is never selected,
so it projects nothing. The parity test runs one repository through the legacy lane, converts it,
and compares the two arrow multisets by endpoint keys that carry no generation namespace.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace

import pytest

from hippo.access import EVERYTHING
from hippo.codegraph.model import CODE_EDGE_KINDS
from hippo.hipporag.graph_index import canonical_arrows
from hippo.ingest import pipeline
from hippo.knowledge import projection
from hippo.knowledge.query_access import query_session
from hippo.knowledge.replay import view_fingerprint
from hippo.knowledge.staged_code import RELATION_KINDS
from hippo.status import _audience_inventory, source_view
from hippo.store.snapshots import SnapshotUnavailable
from tests.unit.test_code_generation import _commit, build, head_of, world  # noqa: F401
from tests.unit.test_managed_code_activation import CLONE_URL, legacy_indexed
from tests.unit.test_managed_code_activation import world as activation_world  # noqa: F401
from tests.unit.test_managed_source_inventory import row_of, tombstone

# One more module that imports the order helper and calls within itself, so the fixture's
# relations are not only `CONTAINS`.
BILLING = '''"""Billing goes through the order helper."""

from orders import helper


def total(value):
    return helper(value)


def bill(value):
    return total(value)
'''

# What a managed arrow carries beyond the native row it was read from.
EVIDENCE_KEYS = ("generation_id", "support_span_ids")


def with_billing(checkout):
    (checkout / "src" / "billing.py").write_text(BILLING)
    _commit(checkout, "Bill through the order helper", 3)


def billed_tree(w):
    with_billing(w.checkout)
    return replace(w.tree, head_revision=head_of(w.checkout))


def arrows(graph):
    return [arrow for bucket in graph.code_out.values() for arrow in bucket]


def decoded(value):
    """A relationship payload's `extra`/`hunk`, which the backends return as JSON text."""
    return json.loads(value) if isinstance(value, str) and value else dict(value or {})


def native(extra):
    return json.dumps(
        {key: value for key, value in extra.items() if key not in EVIDENCE_KEYS}, sort_keys=True
    )


def sealed_relations(store, generation_id):
    """The oracle: the generation's sealed code relations by arrow kind, through CC2's closure read."""
    return Counter(
        row[3]["kind"] if row[0] == "CODE_EDGE" else row[0]
        for row in store._native_relationships(generation_id=generation_id)
        if row[0] in RELATION_KINDS
    )


def served_arrows(ctx):
    """Every served arrow by vertex identity, from one fresh structural session released on return."""
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        return sorted(
            (
                graph.node_ids[arrow.src],
                graph.node_ids[arrow.dst],
                arrow.kind,
                arrow.omega,
                arrow.provenance,
                json.dumps(arrow.extra, sort_keys=True),
            )
            for arrow in arrows(graph)
        )


def node_key(node):
    """A code node by what both lanes call it, never by an ID one lane namespaces."""
    if node.kind == "commit":
        return ("commit", node.sha)
    if node.kind == "symbol":
        return ("symbol", node.path, node.qualname, node.code_kind)
    return ("data", node.code_kind, node.qualname)


def keyed_arrows(ctx):
    """Served arrows and code nodes by those keys, without the managed evidence keys."""
    with query_session(ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        passages = {graph.idx_of[passage.id]: passage for passage in graph.passages}

        def key(vertex):
            node = graph.code_node_at(vertex)
            return ("passage", passages[vertex].text) if node is None else node_key(node)

        served = Counter(
            (arrow.kind, key(arrow.src), key(arrow.dst), arrow.omega, arrow.provenance, native(arrow.extra))
            for arrow in arrows(graph)
        )
        return served, {node_key(node) for node in graph.code_nodes}


# ----------------------------------------------------------- the selected generation


def test_a_published_code_generation_projects_every_relation_it_sealed_and_writes_nothing(world):  # noqa: F811
    """CC11's probe: 14 code nodes and 14 sidecar rows served `Counter(arrow kinds) == {}`."""
    w = world
    result = build(w)
    sealed = sealed_relations(w.store, result.generation_id)
    assert sealed == {"DEFINED_IN": 14, "MODIFIES": 10, "CONTAINS": 7, "PRECEDES": 2}
    manifest = w.store.validate_generation_seal(result.generation_id)
    version = w.store.graph_version()

    with query_session(w.ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert len(graph.code_nodes) == 14
        assert Counter(arrow.kind for arrow in arrows(graph)) == sealed
        assert {arrow.extra["generation_id"] for arrow in arrows(graph)} == {result.generation_id}

    # Reading the relations is a read: the sealed representations and the graph version are as built.
    assert w.store.validate_generation_seal(result.generation_id) == manifest
    assert w.store.graph_version() == version


def test_each_bound_node_is_defined_in_the_passage_whose_originals_hold_its_binding_span(world):  # noqa: F811
    w = world
    result = build(w)
    bound = {
        row.object_id: row.span_id
        for row in w.store._knowledge_rows("NativeBinding", generation_id=result.generation_id)
    }

    with query_session(w.ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        closure = {row.passage_id: row.original_span_ids for row in graph.retrieval_evidence}
        cited = {row.id for row in graph.original_citations}
        defined = [arrow for arrow in arrows(graph) if arrow.kind == "DEFINED_IN"]
        assert sorted(graph.node_ids[arrow.src] for arrow in defined) == sorted(
            node.id for node in graph.code_nodes
        )
        for arrow in defined:
            node, passage = graph.node_ids[arrow.src], graph.node_ids[arrow.dst]
            assert arrow.extra["support_span_ids"] == [bound[node]]
            assert bound[node] in closure[passage] and bound[node] in cited
        # Every node now reaches a passage that cites its binding, so none needs the sidecar.
        assert graph.structural_code_evidence == ()


def test_code_edges_keep_their_native_weight_provenance_and_extra_in_canonical_order(world):  # noqa: F811
    w = world
    result = build(w, tree=billed_tree(w))
    stored = Counter(
        (row[3]["kind"], float(row[3]["omega"]), row[3]["provenance"] or "", native(decoded(row[3]["extra"])))
        for row in w.store._native_relationships(generation_id=result.generation_id)
        if row[0] == "CODE_EDGE"
    )
    assert {"CONTAINS", "IMPORTS", "INVOKES"} <= {key[0] for key in stored}

    fingerprints = []
    for _load in range(2):
        with query_session(w.ctx, EVERYTHING, structural=True) as session:
            graph = session.graph
            served = arrows(graph)
            assert (
                Counter(
                    (arrow.kind, arrow.omega, arrow.provenance, native(arrow.extra))
                    for arrow in served
                    if arrow.kind in CODE_EDGE_KINDS
                )
                == stored
            )
            for buckets in (graph.code_out, graph.code_in):
                assert all(bucket == canonical_arrows(bucket) for bucket in buckets.values())
            for arrow in served:
                pair = graph.edges.get((min(arrow.src, arrow.dst), max(arrow.src, arrow.dst)))
                if arrow.kind == "PRECEDES":
                    # The legacy loader keeps PRECEDES out of igraph on purpose; so does this lane.
                    assert pair is None or "precedes" not in pair.code_kinds
                else:
                    assert pair is not None and arrow.kind.lower() in pair.code_kinds
            fingerprints.append(view_fingerprint(graph))
    assert fingerprints[0] == fingerprints[1]


def test_a_staged_generation_adds_no_arrow_until_it_publishes(world):  # noqa: F811
    """Observed at the coordinator's `seal` step, when every relation of G2 is staged and none published."""
    w = world
    build(w)
    before = served_arrows(w.ctx)
    during = []

    def watch(progress):
        if progress.phase != "seal" or during:
            return
        staged = next(row for row in w.store._knowledge_rows("Generation") if row.status == "staging")
        during.append((staged.id, sealed_relations(w.store, staged.id), served_arrows(w.ctx)))

    second = build(w, operation="refresh", tree=billed_tree(w), on_progress=watch)

    ((staged_id, staged, while_staged),) = during
    assert staged_id == second.generation_id and staged["INVOKES"]
    assert while_staged == before
    after = served_arrows(w.ctx)
    assert Counter(row[2] for row in after) == staged
    assert {json.loads(row[5])["generation_id"] for row in after} == {second.generation_id}


def inject_code_edge(store, a, b):
    """A `CODE_EDGE` placed beneath `native_mutation`, which refuses one that crosses generations."""
    row = {"a": a, "b": b, "kind": "INVOKES", "omega": 1.0, "provenance": "resolved", "extra": "{}"}
    if store.knowledge_backend == "fake":
        store.code_edges[(a, b, "INVOKES")] = row
        return
    store.run(
        "MATCH (a:Symbol {id: $a}), (b:Symbol {id: $b}) "
        "CREATE (a)-[:CODE_EDGE {kind: $kind, omega: $omega, provenance: $provenance, extra: $extra}]->(b)",
        **row,
    )


def test_an_edge_crossing_into_another_generation_is_never_read_and_fails_the_view_closed(
    world,  # noqa: F811
    monkeypatch,
):
    """Two layers. The projection's read is keyed by both endpoints, so it never returns a
    crossing edge; and acquiring a view re-validates the selected generation's seal, whose native
    read refuses one, so no session is served over it at all."""
    w = world
    first = build(w)
    second = build(w, operation="refresh", tree=billed_tree(w))
    read, calls = projection._native_code_relations, []

    def spy(*args):
        calls.append((args, read(*args)))
        return calls[-1][1]

    monkeypatch.setattr(projection, "_native_code_relations", spy)
    assert served_arrows(w.ctx)
    args, relations = calls[-1]
    assert {extra["generation_id"] for *_, extra in relations} == {second.generation_id}
    symbols = w.store.load_symbols()
    retired = next(row["id"] for row in symbols if row.get("generation_id") == first.generation_id)
    active = next(row["id"] for row in symbols if row.get("generation_id") == second.generation_id)

    inject_code_edge(w.store, active, retired)
    inject_code_edge(w.store, retired, active)

    assert read(*args) == relations
    with pytest.raises(SnapshotUnavailable):
        served_arrows(w.ctx)


def test_a_tombstoned_code_source_projects_no_code_arrow(world):  # noqa: F811
    w = world
    result = build(w)
    assert served_arrows(w.ctx)

    tombstone(w.store, w.source)

    assert served_arrows(w.ctx) == []
    # Retained and unselected: the arrows went with the pair, not with a physical delete.
    assert sealed_relations(w.store, result.generation_id)


def test_the_status_card_and_inventory_count_the_code_edges_the_source_row_counts(world):  # noqa: F811
    """PA2-4 counts a managed row from its generation's rows; the aggregates count served arrows."""
    w = world
    build(w)

    with query_session(w.ctx, EVERYTHING, structural=True) as session:
        row = row_of(source_view(w.ctx, EVERYTHING, session=session), w.source)
        stats, card, _jobs = _audience_inventory(w.ctx, EVERYTHING, session=session)

    code = row["meta"]["code"]
    by_kind = {kind: count for kind, count in code["edges_by_kind"].items() if kind in CODE_EDGE_KINDS}
    assert by_kind == {"CONTAINS": 7}
    assert stats["code_edges"] == card["code_edges"] == sum(by_kind.values()) == code["edges"]


# ------------------------------------------------------------------ the two lanes


def test_one_repository_serves_the_same_code_arrows_through_the_legacy_and_the_managed_lane(
    activation_world,  # noqa: F811
    monkeypatch,
):
    w = activation_world
    with_billing(w.origin)
    source = legacy_indexed(w, monkeypatch, lambda: pipeline.add_repo(w.ctx, CLONE_URL, owner_id=w.user))
    legacy, legacy_nodes = keyed_arrows(w.ctx)
    w.inline_jobs()

    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True
    generation = w.store._generation(w.store.get_source(source)["active_generation_id"])
    managed, managed_nodes = keyed_arrows(w.ctx)

    kinds = {key[0] for key in managed}
    assert {"CONTAINS", "IMPORTS", "INVOKES", "DEFINED_IN", "MODIFIES", "PRECEDES"} <= kinds
    # The documented differences, and only these. First, the managed lane writes no REFERS_TO,
    # the arrow the legacy indexer draws from a prose passage to the code it names.
    assert "REFERS_TO" not in kinds
    # Second, a node the managed lane leaves unbound has no native row, so neither it nor any
    # relation touching it is sealed. `materialize_code_evidence` binds a chunk's own `symbol_id`;
    # a TypeScript module holding only declarations has no passage of its own and is named only
    # in its first declaration's `defines`. The coordinator counts these as `unbound_nodes`.
    unbound = legacy_nodes - managed_nodes
    assert managed_nodes <= legacy_nodes
    assert unbound == {("symbol", "web/index.ts", "web.index", "module")}
    assert json.loads(generation.coverage_json)["unbound_nodes"] == len(unbound)
    assert managed == Counter(
        {
            key: count
            for key, count in legacy.items()
            if key[0] != "REFERS_TO" and key[1] not in unbound and key[2] not in unbound
        }
    )
