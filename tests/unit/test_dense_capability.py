"""Dense execution eligibility never changes or discards structural evidence."""

import importlib
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import numpy as np
import pytest

from hippo.hipporag.graph_index import Edge, Fact, Passage
from hippo.hipporag.retriever import Retriever
from hippo.knowledge.citations import OriginalCitation, ProseProvenance, RetrievalEvidence
from hippo.knowledge.identity import make_identity, text_hash
from hippo.knowledge.projection import _assemble, compose_graphs
from hippo.knowledge.replay import view_fingerprint

PROFILE_A = "a" * 64
PROFILE_B = "b" * 64


def api():
    try:
        return importlib.import_module("hippo.knowledge.dense")
    except ModuleNotFoundError:
        pytest.fail("Dense graph capability is not implemented")


def base_graph(source="s", dimension=2, *, with_fact=True):
    passage = Passage("passage-" + source, "Original", "original evidence", source, source, 0)
    vector = np.arange(1, dimension + 1, dtype=np.float32)
    span = "span-" + source
    generation = "generation-" + source
    entities = {
        make_identity("entity", ["inferred-prose-v1", source, name]): name for name in ("alice", "bob")
    }
    a, b = entities
    fact_id = make_identity("fact", ["inferred-prose-v1", source, "alice", "knows", "bob"])
    fact = Fact(fact_id, "alice", "knows", "bob", a, b, [passage.id])
    return _assemble(
        entities if with_fact else {},
        [],
        [passage],
        {passage.id: vector},
        [fact] if with_fact else [],
        {fact_id: vector[::-1]} if with_fact else {},
        {(a, passage.id): Edge(mention=True), (b, passage.id): Edge(mention=True), (a, b): Edge(fact_count=1)}
        if with_fact
        else {},
        [],
        retrieval_evidence=(RetrievalEvidence(passage.id, generation, None, (span,)),),
        original_citations=(
            OriginalCitation(
                span,
                passage.text,
                "Original",
                source,
                text_hash(passage.text),
                span_id=span,
                revision_id="rev-" + source,
                artifact_id="artifact-" + source,
            ),
        ),
        prose_provenance=(ProseProvenance(fact_id, generation, ("extraction-" + source,), (passage.id,)),)
        if with_fact
        else (),
        managed_passage_ids=frozenset({passage.id}),
    )


def sidecar(graph, profile=PROFILE_A):
    generation = {p.passage_id: p.generation_id for p in graph.retrieval_evidence}
    facts = {f.fact_id: f.generation_id for f in graph.prose_provenance}
    return tuple(
        [
            api().DenseVector(
                "passage",
                p.id,
                generation[p.id],
                profile,
                graph.passage_embeddings.shape[1],
                tuple(graph.passage_embeddings[i].tolist()),
            )
            for i, p in enumerate(graph.passages)
        ]
        + [
            api().DenseVector(
                "fact",
                f.id,
                facts[f.id],
                profile,
                graph.fact_embeddings.shape[1],
                tuple(graph.fact_embeddings[i].tolist()),
            )
            for i, f in enumerate(graph.facts)
        ]
    )


def capable(graph, mode, profile=PROFILE_A):
    vectors = sidecar(graph, profile)
    capability = (
        api().DenseCapability(mode, profile, graph.passage_embeddings.shape[1])
        if mode == "verified"
        else api().DenseCapability(mode)
    )
    changes = {"dense_capability": capability, "dense_vectors": vectors}
    if mode == "unavailable":
        changes |= {
            "passage_embeddings": np.zeros((len(graph.passages), 0), dtype=np.float32),
            "fact_embeddings": np.zeros((len(graph.facts), 0), dtype=np.float32),
        }
    return replace(graph, **changes)


@pytest.mark.parametrize(
    ("fingerprint", "dimension"),
    [
        ("", 2),
        ("A" * 64, 2),
        ("a" * 63, 2),
        (PROFILE_A, True),
        (PROFILE_A, 0),
        (PROFILE_A, 65537),
        (PROFILE_A, 2.0),
    ],
)
def test_dense_selection_rejects_noncanonical_identity_and_dimensions(fingerprint, dimension):
    with pytest.raises(ValueError):
        api().DenseSelection(fingerprint, dimension)


def test_capabilities_are_closed_and_legacy_default_stays_usable():
    graph = base_graph()
    assert graph.dense_capability == api().DenseCapability("legacy")
    graph.require_dense()
    with pytest.raises(ValueError):
        api().DenseCapability("unknown")
    with pytest.raises(ValueError):
        api().DenseCapability("unavailable", PROFILE_A, 2)
    with pytest.raises(ValueError):
        api().DenseCapability("verified")


@pytest.mark.parametrize(
    "values",
    [
        (True, 1.0),
        ("1", 1.0),
        (float("nan"), 1.0),
        (float("inf"), 1.0),
        (0.1, 1.0),
        (0.0, -0.0),
        [1.0, 2.0],
        np.array([1.0, 2.0], dtype=np.float32),
    ],
)
def test_sidecar_rejects_mutable_noncanonical_or_invalid_vector_values(values):
    with pytest.raises(ValueError):
        api().DenseVector("passage", "p", "g", PROFILE_A, 2, values)


def test_sidecar_is_immutable_after_deepcopy_and_rejects_unsupported_lanes():
    row = api().DenseVector("passage", "p", "g", PROFILE_A, 2, (1.0, 2.0))
    copied = deepcopy(row)
    with pytest.raises(FrozenInstanceError):
        copied.values = (2.0, 3.0)
    with pytest.raises(TypeError):
        copied.values[0] = 8.0
    for lane in ("entity", "symbol", "code"):
        with pytest.raises(ValueError):
            replace(row, lane=lane)


def test_structural_and_verified_views_keep_exact_evidence_fingerprints():
    original = base_graph()
    verified = capable(original, "verified")
    structural = capable(original, "unavailable")
    assert structural.passage_embeddings.shape == (1, 0)
    assert structural.fact_embeddings.shape == (1, 0)
    assert structural.node_ids == original.node_ids
    assert view_fingerprint(original) == view_fingerprint(verified) == view_fingerprint(structural)
    changed_rows = tuple(
        replace(r, values=(3.0, 4.0)) if r.lane == "fact" else r for r in structural.dense_vectors
    )
    assert view_fingerprint(replace(structural, dense_vectors=changed_rows)) != view_fingerprint(structural)
    with pytest.raises(ValueError):
        replace(verified, passage_embeddings=np.array([[3.0, 4.0]], dtype=np.float32))


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "unknown_node",
        "wrong_generation",
        "wrong_fact_support",
        "missing_extraction",
        "mutable_record",
        "native_fact",
    ],
)
def test_sidecar_requires_exact_authorized_node_generation_and_fact_support_binding(fault):
    original = base_graph()
    changes = {}
    rows = sidecar(original)
    if fault == "missing":
        rows = rows[1:]
    elif fault == "duplicate":
        rows += (rows[0],)
    elif fault == "unknown_node":
        rows = (replace(rows[0], projected_id="missing"), *rows[1:])
    elif fault == "wrong_generation":
        rows = (replace(rows[0], generation_id="other-generation"), *rows[1:])
    elif fault == "wrong_fact_support":
        changes["prose_provenance"] = (
            replace(original.prose_provenance[0], support_passage_ids=("missing",)),
        )
    elif fault == "missing_extraction":
        changes["prose_provenance"] = (replace(original.prose_provenance[0], extraction_ids=()),)
    elif fault == "mutable_record":
        rows = (
            (SimpleNamespace(**vars(rows[0])), *rows[1:])
            if hasattr(rows[0], "__dict__")
            else (SimpleNamespace(lane="passage", projected_id=rows[0].projected_id), *rows[1:])
        )
    else:
        changed_fact = replace(original.facts[0], id="fact-global-native")
        changes |= {
            "facts": [changed_fact],
            "fact_index_of": {changed_fact.id: 0},
            "prose_provenance": (replace(original.prose_provenance[0], fact_id=changed_fact.id),),
        }
        rows = tuple(replace(r, projected_id=changed_fact.id) if r.lane == "fact" else r for r in rows)
    with pytest.raises(ValueError):
        replace(
            original,
            dense_capability=api().DenseCapability("verified", PROFILE_A, 2),
            dense_vectors=rows,
            **changes,
        )


def test_mixed_structural_composition_and_scope_preserve_all_topology_and_vector_identity():
    left = capable(base_graph("left", 2), "unavailable", PROFILE_A)
    right = capable(base_graph("right", 3), "unavailable", PROFILE_B)
    combined = compose_graphs(left, right)
    assert combined.dense_capability == api().DenseCapability("unavailable")
    assert combined.passage_embeddings.shape == combined.fact_embeddings.shape == (2, 0)
    assert set(combined.node_ids) == set(left.node_ids) | set(right.node_ids)
    assert len(combined.dense_vectors) == 4
    scoped = combined.scoped({"left"})
    assert scoped.dense_vectors == left.dense_vectors
    assert view_fingerprint(scoped) == view_fingerprint(left)
    assert scoped.prose_provenance == left.prose_provenance
    assert scoped.original_citations == left.original_citations
    hidden = combined.scoped(set())
    assert hidden.dense_vectors == ()
    assert hidden.dense_capability.mode == "unavailable"
    assert hidden.passage_embeddings.shape == hidden.fact_embeddings.shape == (0, 0)
    with pytest.raises(ValueError):
        compose_graphs(left, left)


def test_verified_composition_checks_profiles_and_empty_legacy_is_neutral():
    left = capable(base_graph("left"), "verified")
    right = capable(base_graph("right"), "verified")
    combined = compose_graphs(left, right, compose_graphs())
    assert combined.dense_capability == left.dense_capability
    combined.require_dense(PROFILE_A)
    with pytest.raises(ValueError):
        compose_graphs(left, capable(base_graph("wrong"), "verified", PROFILE_B))
    with pytest.raises(ValueError):
        compose_graphs(capable(base_graph(), "unavailable"), base_graph("legacy"))


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("supplied", [False, True])
def test_unavailable_retrieval_rejects_before_empty_shortcut_or_any_model_calls(empty, supplied):
    graph = capable(base_graph(), "unavailable")
    if empty:
        graph = graph.scoped(set())

    class NoModelCalls:
        @property
        def profile_fingerprint(self):
            pytest.fail("structural graph inspected model profile")

        def embed_one(self, *args, **kwargs):
            pytest.fail("structural graph reached embedding")

        def chat_json(self, *args, **kwargs):
            pytest.fail("structural graph reached chat")

    with pytest.raises(api().DenseUnavailable):
        Retriever(graph, NoModelCalls()).retrieve(
            "question", {}, question_embedding=np.array([1.0, 0.0]) if supplied else None
        )


@pytest.mark.parametrize("fingerprint", [None, PROFILE_B])
def test_verified_retrieval_requires_matching_model_even_with_supplied_vector(fingerprint):
    graph = capable(base_graph(), "verified")
    with pytest.raises(api().DenseUnavailable):
        Retriever(graph, SimpleNamespace(profile_fingerprint=fingerprint)).retrieve(
            "question", {}, question_embedding=np.array([1.0, 0.0])
        )
    matching = SimpleNamespace(profile_fingerprint=PROFILE_A)
    trace = Retriever(graph, matching).retrieve(
        "question",
        {},
        question_embedding=np.array([1.0, 0.0]),
        fact_filter=lambda question, candidates: ([], ""),
    )
    assert trace.passages


def test_verified_retrieval_checks_authorization_before_model_profile_property():
    graph = capable(base_graph(), "verified")

    def expired():
        raise PermissionError("expired audience")

    graph.authorization_check = expired

    class Model:
        @property
        def profile_fingerprint(self):
            pytest.fail("expired graph inspected model profile")

    with pytest.raises(PermissionError, match="expired audience"):
        Retriever(graph, Model()).retrieve("question", {}, question_embedding=np.array([1.0, 0.0]))


def test_original_only_fingerprint_fixture_remains_unchanged():
    from tests.unit.test_derived_projection import test_original_only_graph_ids_and_fingerprints_are_unchanged

    test_original_only_graph_ids_and_fingerprints_are_unchanged()


@pytest.mark.parametrize(
    "fault", ["missing_vertex", "wrong_vertex_kind", "wrong_fact_index", "missing_original"]
)
def test_bound_sidecar_cannot_outlive_its_projected_vertex_or_original_closure(fault):
    graph = base_graph()
    changes = {}
    if fault == "missing_vertex":
        changes["idx_of"] = {key: value for key, value in graph.idx_of.items() if key != graph.passages[0].id}
    elif fault == "wrong_vertex_kind":
        changed = list(graph.node_kind)
        changed[graph.idx_of[graph.passages[0].id]] = "entity"
        changes["node_kind"] = changed
    elif fault == "wrong_fact_index":
        changes["fact_index_of"] = {graph.facts[0].id: 99}
    else:
        changes["original_citations"] = ()
    with pytest.raises(ValueError):
        replace(
            graph,
            dense_capability=api().DenseCapability("verified", PROFILE_A, 2),
            dense_vectors=sidecar(graph),
            **changes,
        )


def test_populated_legacy_code_component_needs_future_structural_adapter():
    from hippo.hipporag.graph_index import CodeNode

    legacy = _assemble({}, [CodeNode("code-legacy", "symbol", "LegacyCode")], [], {}, [], {}, {}, [])
    structural = capable(base_graph(), "unavailable")
    with pytest.raises(api().DenseUnavailable):
        compose_graphs(structural, legacy)
