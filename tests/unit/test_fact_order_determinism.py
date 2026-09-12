"""One canonical fact order, so an unchanged corpus keeps one view fingerprint.

LadybugDB and Neo4j promise no row order, so `store.load_facts()` hands `GraphIndex`
a differently ordered list on every load of the same corpus. `graph.facts` and the
vector matrix aligned with it are both hashed by `view_fingerprint`, so the view's
identity used to move while nothing about the evidence had changed -- which denies a
generated evaluation set its own stored `evidence_fingerprint` and withholds a saved
answer that is still perfectly reusable. The Fake store hid all of it by keeping
insertion order.

The fix orders facts by their stored identity wherever they are materialised, so the
order is a property of the corpus rather than of the backend. These tests pin that:
the order a store happens to return must not reach `GraphIndex` at all.

Nothing here imports a transport, so the module stays clean under a bare `-W error`.
"""

import numpy as np
import pytest

from hippo.access import EVERYTHING
from hippo.context import AppContext
from hippo.hipporag.graph_index import GraphIndex
from hippo.knowledge.eval_access import EvalAccess
from hippo.knowledge.query_access import query_session
from hippo.knowledge.replay import can_reuse_answer, view_fingerprint
from tests.unit.test_managed_eval_activation import legacy_sample


def reloaded(ctx):
    """A second context over the same store: no cached index can be shared with the first."""
    return AppContext(config=ctx.config, store=ctx.store, ollama=ctx.ollama)


def fact_ids(graph):
    return [fact.id for fact in graph.facts]


@pytest.fixture
def corpus(ctx, sample_text):
    """The sample corpus indexed the legacy way: 34 extracted facts, no generation."""
    source_id = legacy_sample(ctx, sample_text)
    assert GraphIndex.load(ctx.store).facts, "the corpus must have facts or nothing is under test"
    return source_id


# --------------------------------------------------- the order itself


def test_repeated_loads_of_one_corpus_agree_on_facts_and_fingerprint(ctx, corpus):
    """Three cold loads of an unchanged corpus are one view, on every backend."""
    graphs = [GraphIndex.load(ctx.store) for _ in range(3)]
    assert len({tuple(fact_ids(graph)) for graph in graphs}) == 1
    assert len({view_fingerprint(graph) for graph in graphs}) == 1
    assert len({graph.version for graph in graphs}) == 1


def test_loaded_facts_are_ordered_by_their_stored_identity(ctx, corpus):
    """The canonical key is the fact id, so every backend agrees by construction."""
    graph = GraphIndex.load(ctx.store)
    assert fact_ids(graph) == sorted(fact_ids(graph))
    assert graph.fact_index_of == {fact.id: i for i, fact in enumerate(graph.facts)}
    assert all(sorted(fact.passage_ids) == fact.passage_ids for fact in graph.facts)


def test_the_store_return_order_never_reaches_the_graph(ctx, corpus, monkeypatch):
    """Hand the loader the same rows backwards and nothing about the graph moves.

    This is the defect itself, made deterministic: LadybugDB varies this order run to
    run, and the Fake store does not, so only an explicit reversal tests both backends.
    The passage ids inside a fact are reversed too -- LadybugDB collects them with no
    `ORDER BY` and the Fake store keeps them in a set, so they are as unordered as the
    fact list is.
    """
    rows = ctx.store.load_facts()
    passage_ids = [passage["id"] for passage in ctx.store.load_passages()][:2]
    assert len(rows) > 1 and len(passage_ids) == 2

    def stated(row, order):
        return {**row, "passage_ids": list(order)}

    forward = [stated(row, passage_ids) for row in rows]
    backward = [stated(row, reversed(passage_ids)) for row in reversed(rows)]

    graphs = []
    for served in (forward, backward):
        monkeypatch.setattr(ctx.store, "load_facts", lambda served=served: [dict(r) for r in served])
        graphs.append(GraphIndex.load(ctx.store))

    first, second = graphs
    assert fact_ids(first) == fact_ids(second) == sorted(fact_ids(first))
    assert first.fact_index_of == second.fact_index_of
    assert [f.passage_ids for f in first.facts] == [f.passage_ids for f in second.facts]
    assert np.array_equal(first.fact_embeddings, second.fact_embeddings)
    assert view_fingerprint(first) == view_fingerprint(second)


def test_each_fact_keeps_the_vector_row_that_belongs_to_it(ctx, corpus):
    """Reordering the list must carry the matrix with it, or every fact scores as another."""
    rows = {row["id"]: row["embedding"] for row in ctx.store.load_facts()}
    graph = GraphIndex.load(ctx.store)
    for position, fact in enumerate(graph.facts):
        assert np.allclose(graph.fact_embeddings[position], np.asarray(rows[fact.id], dtype=np.float32))


def test_a_scoped_and_composed_view_keeps_the_canonical_order(ctx, corpus):
    """The structural default composes lanes through `_assemble`; it must agree too."""
    with query_session(ctx, EVERYTHING) as session:
        graph = session.graph
        assert fact_ids(graph) == sorted(fact_ids(graph))
        assert graph.fact_index_of == {fact.id: i for i, fact in enumerate(graph.facts)}
        scoped = graph.scoped({corpus})
        assert fact_ids(scoped) == sorted(fact_ids(scoped))


def test_three_sessions_over_one_corpus_prove_the_same_view(ctx, corpus):
    """What `EvalAccess` and `can_reuse_answer` actually compare, from a cold context each time."""
    prints = []
    for _ in range(3):
        with query_session(reloaded(ctx), EVERYTHING) as session:
            prints.append((view_fingerprint(session.graph), session.graph.version))
    assert len(set(prints)) == 1


# ------------------------------------------- what the moving order broke


def test_a_generated_evaluation_set_reproves_its_own_evidence(ctx, corpus):
    """`EvalAccess._authorized` re-proves the stored fingerprint on every read."""
    created = EvalAccess(ctx, EVERYTHING)
    set_id = created.create_question_set("generated", corpus, origin="generated")
    later = EvalAccess(reloaded(ctx), EVERYTHING)
    assert later.require_set(set_id)["id"] == set_id
    assert [row["id"] for row in later.list_question_sets()] == [set_id]


def test_a_saved_answer_over_unchanged_evidence_is_still_reusable(ctx, corpus):
    """`can_reuse_answer` compares the same value, so a saved answer used to be withheld."""
    with query_session(ctx, EVERYTHING) as session:
        stamp = view_fingerprint(session.graph)
    with query_session(reloaded(ctx), EVERYTHING) as session:
        assert can_reuse_answer(session.graph, stamp)
