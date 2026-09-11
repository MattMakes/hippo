"""Serving graphs must select source generations before building vector matrices."""

from copy import deepcopy

import pytest

from hippo.hipporag.graph_index import GraphIndex


class Rows:
    def __init__(self, **rows):
        self.rows = rows

    def __getattr__(self, name):
        if name.startswith("load_"):
            return lambda: deepcopy(self.rows.get(name[5:], []))
        raise AttributeError(name)


def passage(identity, source="managed", generation="g1", dim=2):
    return dict(
        id=identity,
        source_id=source,
        generation_id=generation,
        title="same.py",
        text=identity,
        ordinal=0,
        source_name=source,
        embedding=[1.0] * dim,
    )


def node(identity, source="managed", generation="g1", **extra):
    return dict(
        id=identity,
        source_id=source,
        generation_id=generation,
        name="same",
        path="same.py",
        in_degree=99,
        **extra,
    )


def fact(identity, passages, dim=2):
    return dict(
        id=identity,
        subject="a",
        predicate="uses",
        object="b",
        subject_id="a",
        object_id="b",
        passage_ids=passages,
        embedding=[1.0] * dim,
    )


def load(store, **kwargs):
    from hippo.knowledge import graph_loader

    return graph_loader.load_generation_graph(
        store,
        generations={"managed": "g1"},
        legacy_source_ids=frozenset({"legacy"}),
        version=7,
        **kwargs,
    )


def test_generation_selection_precedes_vector_dimension_selection():
    store = Rows(
        passages=[passage("g1:p"), passage("legacy:p", "legacy", None)]
        + [passage(f"g2:{i}", generation="g2", dim=3) for i in range(4)]
    )
    assert len(GraphIndex.load(store, version=7).passages) == 4
    graph = load(store)
    assert {row.id for row in graph.passages} == {"g1:p", "legacy:p"}
    assert graph.passage_embeddings.shape == (2, 2)
    assert graph.version == 7


def test_shared_fact_support_and_entity_statistics_are_rebuilt():
    store = Rows(
        passages=[passage("g1:p"), passage("g2:p", generation="g2"), passage("legacy:p", "legacy", None)],
        entities=[dict(id=key, name=key, passage_count=50) for key in ("a", "b", "excluded")],
        facts=[fact("shared", ["g1:p", "g2:p", "legacy:p"]), fact("staged", ["g2:p"], 3)],
        fact_edges=[dict(a="a", b="b", weight=50)],
        mentions=[
            dict(passage_id=p, entity_id=e)
            for p, e in [("g1:p", "a"), ("legacy:p", "a"), ("g2:p", "a"), ("g2:p", "excluded")]
        ],
    )
    graph = load(store)
    assert "excluded" not in graph.idx_of
    assert graph.specificity[graph.idx_of["a"]] == 2
    assert graph.specificity[graph.idx_of["b"]] == 0
    assert [(f.id, f.passage_ids) for f in graph.facts] == [("shared", ["g1:p", "legacy:p"])]
    assert graph.fact_embeddings.shape == (1, 2)
    edge = graph.edges[tuple(sorted((graph.idx_of["a"], graph.idx_of["b"])))]
    assert edge.fact_count == 2


def test_all_native_relations_are_filtered_and_degrees_recomputed():
    def code(a, b, kind="INVOKES"):
        return dict(a=a, b=b, kind=kind, omega=0.8, provenance="test", extra={})

    store = Rows(
        passages=[passage("g1:p"), passage("g2:p", generation="g2")],
        symbols=[node("g1:s"), node("g2:s", generation="g2"), node("legacy:s", "legacy", None)],
        data_objects=[node("g1:d"), node("g2:d", generation="g2")],
        commits=[node("g1:c"), node("g2:c", generation="g2")],
        code_edges=[code("legacy:s", "g1:s"), code("g2:s", "g1:s"), code("g1:s", "g1:d", "READS")],
        definitions=[dict(node_id=s, passage_id=p) for s, p in [("g1:s", "g1:p"), ("g2:s", "g1:p")]],
        refers_to=[dict(passage_id=p, node_id="g1:s", omega=0.8, token="same") for p in ("g1:p", "g2:p")],
        modifies=[dict(commit_id=c, symbol_id="g1:s", omega=1, hunk={}) for c in ("g1:c", "g2:c")],
        precedes=[dict(a="g1:c", b="g2:c")],
        synonyms=[dict(a="g1:s", b=b, score=0.9) for b in ("g1:d", "g2:d")],
        tuned_edges=[dict(a="g1:s", b=b, weight=5) for b in ("legacy:s", "g2:s")],
    )
    graph = load(store)
    assert set(graph.node_ids) == {"g1:p", "g1:s", "g1:d", "g1:c", "legacy:s"}
    nodes = {row.id: row for row in graph.code_nodes}
    assert nodes["g1:s"].in_degree == 1
    assert graph.specificity[graph.idx_of["g1:s"]] == 2
    assert nodes["g1:d"].in_degree == 1
    assert set(graph.path_index["same.py"]) == {"g1:s", "legacy:s"}
    assert {arrow.kind for arrows in graph.code_out.values() for arrow in arrows} == {
        "INVOKES",
        "READS",
        "DEFINED_IN",
        "REFERS_TO",
        "MODIFIES",
    }
    assert store.rows["symbols"][0]["in_degree"] == 99


@pytest.mark.parametrize(
    "trusted, expected",
    [
        (None, {"g1:p", "legacy:p"}),
        ({"managed": "g1"}, {"g1:p", "legacy:p", "old:p"}),
        ({"managed": "g2"}, {"g1:p", "legacy:p"}),
    ],
)
def test_untagged_managed_rows_need_explicit_generation_bound_trust(trusted, expected):
    store = Rows(
        passages=[
            passage("g1:p"),
            passage("old:p", generation=None),
            passage("legacy:p", "legacy", None),
            passage("unknown:p", "unknown", None),
            passage("wrong-source:p", "unknown", "g1"),
            passage("legacy-staged:p", "legacy", "g2"),
        ]
    )
    assert {row.id for row in load(store, trusted_untagged_generations=trusted).passages} == expected
