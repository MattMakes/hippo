"""Rendered retrieval stays distinct from immutable original source citations."""

import importlib
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import numpy as np
import pytest

from hippo.access import EVERYTHING
from hippo.knowledge import model as k
from hippo.knowledge.access import EvidenceAccess, EvidenceSelection
from hippo.knowledge.graph_loader import load_generation_graph
from hippo.knowledge.identity import text_hash
from hippo.knowledge.lifecycle import generation_passage_id
from hippo.knowledge.projection import ProjectionError, compose_graphs, project_managed_graph
from hippo.knowledge.replay import view_fingerprint
from tests.unit.test_derived_generation_store import extraction, member, rendered
from tests.unit.test_generation_store import (
    NOW,
    authority,
    claim,
    evidence,
    generation,
    passage,
    publish,
    seal,
)


def citations():
    assert importlib.util.find_spec("hippo.knowledge.citations"), "Original citation resolver is missing"
    return importlib.import_module("hippo.knowledge.citations")


def prepared(
    store,
    *,
    parent=None,
    extra_view=False,
    extra_input=False,
    prose=True,
    key="one",
    conflict=False,
    prose_payload=None,
):
    gen = generation(store, key, parent)
    job = claim(store, gen, key=key)
    rows, originals, views, extractions = [], [], [], []
    with store.generation_write(gen.id, **authority(job)):
        rev, span = evidence(store, gen)
        originals.append(span)
        if extra_input:
            other = span.replace(
                text="another original",
                text_hash=text_hash("another original"),
                locator_json='{"kind":"file_lines","path":"a.txt","start":2,"end":2}',
            )
            member(store, gen, other)
            originals.append(other)
        inputs = originals + ([span] if extra_view else [])
        for i, original in enumerate(inputs):
            view, _, _ = rendered(store, gen, original, text=f"rendered view {i}")
            row = passage(gen, rev, original)
            row.update(
                id=generation_passage_id(gen.id, rev.id, original.id, i, retrieval_view_id=view.id),
                retrieval_view_id=view.id,
                text=view.text,
                ordinal=i,
                embedding=[1.0, 0.0] if i == 0 else [0.0, 1.0],
            )
            store.add_passages([row])
            rows.append(row)
            views.append(view)
            if prose and i < len(originals):
                payload = prose_payload
                if conflict and i:
                    payload = k.ProseExtractionPayload(
                        entities=(k.ProseEntity(name="alice", embedding=(0.9, 0.8)),),
                    )
                record = extraction(store, gen, original, row, payload=payload)
                member(store, gen, record)
                extractions.append(record)
    seal(store, gen, job)
    publish(store, gen, job)
    return SimpleNamespace(gen=gen, rows=rows, spans=originals, views=views, extractions=extractions)


def project(store, gen, *, engine=None, full=None):
    selection = EvidenceSelection(generation_ids=frozenset({gen.id}), require_exact_membership=True)
    engine = engine or EvidenceAccess(
        store,
        store.get_source(gen.source_id)["workspace_id"],
        EVERYTHING,
        clock=lambda: NOW,
    )
    proof = engine.build(selection)
    full = full or load_generation_graph(
        store,
        generations={gen.source_id: gen.id},
        legacy_source_ids=frozenset(),
        version=1,
    )
    graph = project_managed_graph(full, store, proof, embedding_profile="p")
    graph.authorization_check = lambda: engine.validate_current(proof)
    return graph


def test_two_views_of_one_span_keep_different_vectors_and_one_original_citation(store):
    w = prepared(store, extra_view=True)
    graph = project(store, w.gen)
    assert {p.id for p in graph.passages} == {r["id"] for r in w.rows}
    assert {tuple(row) for row in graph.passage_embeddings} == {(1.0, 0.0), (0.0, 1.0)}
    bundle = citations().resolve_citations(graph, tuple(r["id"] for r in w.rows))
    assert len(bundle.citations) == 1
    original = bundle.citations[0]
    assert original.id == original.span_id == w.spans[0].id
    assert original.text == w.spans[0].text
    assert original.locator_json == w.spans[0].locator_json
    assert bundle.retrieval_passage_ids == tuple(r["id"] for r in w.rows)
    assert all(item.citation_ids == (original.id,) for item in bundle.items)
    assert all(item.retrieval_view_id for item in bundle.items)
    with pytest.raises(FrozenInstanceError):
        original.text = "replacement"


def test_view_resolves_unembedded_secondary_original_and_acl_denies_whole_output(store):
    from tests.unit.test_derived_evidence_access import suppress, world

    w = world(store)
    graph = project(store, w.gen, engine=w.engine)
    assert len(graph.passages) == 1
    bundle = citations().resolve_citations(graph, (w.row["id"],))
    assert {c.id for c in bundle.citations} == {s.id for s in w.spans}
    assert {c.text for c in bundle.citations} == {s.text for s in w.spans}
    suppress(w, w.spans[1].id, kind="span")
    with pytest.raises(Exception, match="Authorization|authorization|permissions"):
        citations().resolve_citations(graph, (w.row["id"],))
    hidden = project(store, w.gen, engine=w.engine)
    assert not hidden.passages and not hidden.facts and not hidden.entity_names
    assert not hidden.original_citations and not hidden.prose_provenance


def test_prose_support_is_explicit_and_extra_views_do_not_multiply_counts(store):
    w = prepared(store, extra_view=True)
    graph = project(store, w.gen)
    assert len(graph.facts) == 1
    fact = graph.facts[0]
    assert fact.triple == ["alice", "knows", "bob"]
    assert fact.passage_ids == [w.rows[0]["id"]]
    assert len(graph.entity_names) == 2
    for identity in graph.entity_names:
        assert graph.specificity[graph.idx_of[identity]] == 1
    assert graph.edge_between(graph.idx_of[fact.subject_id], graph.idx_of[fact.object_id]).fact_count == 1
    assert graph.prose_provenance[0].extraction_ids == (w.extractions[0].id,)


def test_repeated_prose_unions_distinct_support_and_keeps_source_local_ids(store):
    w = prepared(store, extra_input=True)
    graph = project(store, w.gen)
    assert len(graph.facts) == 1
    assert set(graph.facts[0].passage_ids) == {r["id"] for r in w.rows}
    assert all(graph.specificity[graph.idx_of[e]] == 2 for e in graph.entity_names)
    newer = prepared(store, parent=w.gen, key="next")
    current = project(store, newer.gen)
    assert current.facts[0].id == graph.facts[0].id
    assert set(current.entity_names) == set(graph.entity_names)
    assert current.facts[0].passage_ids == [newer.rows[0]["id"]]
    other = prepared(store, key="other-source")
    other_graph = project(store, other.gen)
    assert not set(current.entity_names) & set(other_graph.entity_names)
    assert current.facts[0].id != other_graph.facts[0].id


def test_scoping_and_composition_keep_complete_immutable_lineage(store):
    left = prepared(store)
    right = prepared(store, key="right")
    left_graph, right_graph = project(store, left.gen), project(store, right.gen)
    combined = compose_graphs(left_graph, right_graph)
    scoped = combined.scoped({left.gen.source_id})
    bundle = citations().resolve_citations(scoped, (left.rows[0]["id"],))
    assert tuple(c.id for c in bundle.citations) == (left.spans[0].id,)
    assert scoped.retrieval_evidence == left_graph.retrieval_evidence
    assert scoped.original_citations == left_graph.original_citations
    assert scoped.prose_provenance == left_graph.prose_provenance
    copied = deepcopy(scoped)
    assert copied.original_citations == scoped.original_citations
    assert not scoped.scoped(set()).original_citations


def test_original_only_graph_ids_and_fingerprints_are_unchanged():
    from tests.unit.test_evidence_projection import fixture, projected

    w = fixture()
    graph = projected(w)
    assert graph.version == 315054166138069197
    assert view_fingerprint(graph) == "5a1de139727473877aa3f3201636b56ef4c50af9d45e898b29e69301ac3d8ca0"
    bundle = citations().resolve_citations(graph, (w.spans[0].id,))
    assert bundle.citations[0].span_id == w.spans[0].id
    assert bundle.citations[0].text == w.spans[0].text


def test_legacy_resolution_does_not_invent_span_or_revision_ids():
    from hippo.hipporag.graph_index import Passage
    from tests.unit.test_evidence_projection import graph

    legacy = graph([], [Passage("legacy", "title", "original legacy text", "source", "source", 0)])
    bundle = citations().resolve_citations(legacy, ("legacy",))
    assert bundle.citations[0].id == "legacy"
    assert bundle.citations[0].span_id is None and bundle.citations[0].revision_id is None
    assert bundle.items[0].citation_ids == ("legacy",)
    assert bundle.items[0].retrieval_view_id is None


def test_fingerprint_commits_original_locators_and_resolver_rejects_missing_lineage(store):
    w = prepared(store)
    graph = project(store, w.gen)
    before = view_fingerprint(graph)
    altered = replace(graph, original_citations=(replace(graph.original_citations[0], locator_json="{}"),))
    assert view_fingerprint(altered) != before
    stripped = replace(graph, original_citations=())
    with pytest.raises(ValueError):
        citations().resolve_citations(stripped, (w.rows[0]["id"],))


def test_cached_rendered_text_or_vector_mismatch_fails_closed(store):
    w = prepared(store)
    full = load_generation_graph(
        store,
        generations={w.gen.source_id: w.gen.id},
        legacy_source_ids=frozenset(),
        version=1,
    )
    full.passages[0].text = "untrusted cache text"
    with pytest.raises(ProjectionError):
        project(store, w.gen, full=full)


def test_equivalent_entities_with_conflicting_vectors_fail_projection(store):
    w = prepared(store, extra_input=True, conflict=True)
    with pytest.raises(ProjectionError, match="conflicting vectors"):
        project(store, w.gen)


def test_rendered_passage_id_commits_its_ordinal_binding(store):
    from unittest.mock import patch

    w = prepared(store)
    # Persisted/cached content agree but the native identity no longer describes
    # the claimed row. Do not accept matching vector dimension as evidence.
    with patch("hippo.knowledge.projection._passage_bindings", return_value=[{**w.rows[0], "ordinal": 99}]):
        with pytest.raises(ProjectionError):
            project(store, w.gen)


def test_a_scoped_managed_graph_keeps_its_live_authorization_callback(store):
    w = prepared(store)
    graph = project(store, w.gen)
    graph.authorization_check = lambda: (_ for _ in ()).throw(PermissionError("revoked"))
    scoped = graph.scoped(set())
    with pytest.raises(PermissionError, match="revoked"):
        citations().resolve_citations(scoped, ())


def test_missing_managed_mapping_does_not_turn_a_view_into_legacy_text(store):
    w = prepared(store)
    graph = project(store, w.gen)
    stripped = replace(graph, retrieval_evidence=())
    with pytest.raises(ValueError, match="no original lineage"):
        citations().resolve_citations(stripped, (w.rows[0]["id"],))


def test_staging_other_dimensions_never_affect_the_serving_view_or_prose(store):
    w = prepared(store)
    before = project(store, w.gen)
    staged = generation(store, "staging", w.gen)
    job = claim(store, staged, key="staging")
    with store.generation_write(staged.id, **authority(job)):
        rev, span = evidence(store, staged)
        for ordinal in range(3):
            row = passage(staged, rev, span)
            row.update(
                id=generation_passage_id(staged.id, rev.id, span.id, ordinal),
                ordinal=ordinal,
                embedding=[1.0, 0.0, 0.0],
            )
            store.add_passages([row])
    after = project(store, w.gen)
    np.testing.assert_array_equal(before.passage_embeddings, after.passage_embeddings)
    assert before.retrieval_evidence == after.retrieval_evidence
    assert before.prose_provenance == after.prose_provenance
    assert view_fingerprint(before) == view_fingerprint(after)


def test_bound_code_view_defines_only_its_canonical_observed_object(store):
    from hippo.codegraph.model import symbol_id
    from hippo.knowledge import derivations as d
    from hippo.knowledge.identity import canonical_json
    from hippo.knowledge.lifecycle import generation_namespace

    gen = generation(store)
    job = claim(store, gen)
    workspace = store.get_source(gen.source_id)["workspace_id"]
    with store.generation_write(gen.id, **authority(job)):
        rev, span = evidence(store, gen)
        obj = k.KnowledgeObject(workspace_id=workspace, kind="symbol", canonical_key='["a.py","f"]')
        store.put_knowledge(obj)
        member(
            store,
            gen,
            k.ObjectObservation(
                object_id=obj.id,
                revision_id=rev.id,
                span_id=span.id,
                evidence_class="declared",
                recorded_from=NOW,
                attributes_json=canonical_json(
                    dict(name="f", path="a.py", signature="f()", doc="observed doc")
                ),
            ),
        )
        native_id = symbol_id(
            gen.source_id, "a.py", "f", "function", node_namespace=generation_namespace(gen)
        )
        store.add_symbols(
            [
                dict(
                    id=native_id,
                    source_id=gen.source_id,
                    generation_id=gen.id,
                    name="f",
                    qualname="f",
                    kind="function",
                    path="a.py",
                    doc="unchecked native doc",
                    embedding=[1.0, 0.0],
                )
            ]
        )
        binding = k.NativeBinding(
            generation_id=gen.id,
            object_id=obj.id,
            native_kind="Symbol",
            native_id=native_id,
            span_id=span.id,
        )
        store.put_knowledge(binding)
        deps = [
            (kind, record.id, d.dependency_version(record))
            for kind, record in (("span", span), ("binding", binding))
        ]
        fp = d.view_fingerprint(
            view_kind="symbol_body",
            text="rendered f card",
            text_profile="render-v1",
            vector_profile="p",
            rule_version="render-v1",
            model_version=None,
            dependencies=deps,
        )
        derived = k.DerivedRecord(
            workspace_id=workspace,
            view_kind="symbol_body",
            rule_version="render-v1",
            input_revision_ids=(rev.id,),
            input_binding_ids=(binding.id,),
            dependency_fingerprint=fp,
            state="ready",
        )
        member(store, gen, derived)
        for kind, identity, version in deps:
            member(
                store,
                gen,
                k.DerivedDependency(
                    derived_record_id=derived.id,
                    input_kind=kind,
                    input_id=identity,
                    input_version=version,
                ),
            )
        view = k.RetrievalView(
            span_id=span.id,
            source_revision_id=rev.id,
            view_kind="symbol_body",
            text="rendered f card",
            text_profile="render-v1",
            vector_profile="p",
            derivation_version="render-v1",
            dependency_fingerprint=fp,
            derived_record_id=derived.id,
        )
        member(store, gen, view)
        row = passage(gen, rev, span)
        row.update(
            id=generation_passage_id(gen.id, rev.id, span.id, 0, retrieval_view_id=view.id),
            retrieval_view_id=view.id,
            text=view.text,
        )
        store.add_passages([row])
    seal(store, gen, job)
    publish(store, gen, job)
    graph = project(store, gen)
    assert graph.code_node_by_id(obj.id).doc == "observed doc"
    assert graph.code_node_by_id(native_id) is None
    assert graph.defining_passages(graph.idx_of[obj.id]) == [graph.idx_of[row["id"]]]
    assert not graph.facts
    assert citations().resolve_citations(graph, (row["id"],)).citations[0].text == span.text


def test_synonyms_use_only_selected_source_local_prose_vectors(store):
    payload = k.ProseExtractionPayload(
        entities=(
            k.ProseEntity(name="alice", embedding=(1.0, 0.0)),
            k.ProseEntity(name="bob", embedding=(0.99, 0.01)),
        ),
        triples=(k.ProseTriple(subject="alice", predicate="knows", object="bob", embedding=(1.0, 0.0)),),
    )
    left = prepared(store, prose_payload=payload)
    right = prepared(store, key="right", prose_payload=payload)
    left_graph, right_graph = project(store, left.gen), project(store, right.gen)
    combined = compose_graphs(left_graph, right_graph)
    fact = left_graph.facts[0]
    assert (
        left_graph.edge_between(
            left_graph.idx_of[fact.subject_id], left_graph.idx_of[fact.object_id]
        ).synonym_score
        > 0.8
    )
    for a in left_graph.entity_names:
        for b in right_graph.entity_names:
            assert combined.edge_between(combined.idx_of[a], combined.idx_of[b]) is None


@pytest.mark.parametrize("a,b,expected", [((2.0, 0.0), (1.0, 2.0), 0.0), ((2.0, 0.0), (0.1, 0.0), 1.0)])
def test_synonyms_compare_cosine_without_changing_persisted_fact_vectors(store, a, b, expected):
    payload = k.ProseExtractionPayload(
        entities=(k.ProseEntity(name="alice", embedding=a), k.ProseEntity(name="bob", embedding=b)),
        triples=(k.ProseTriple(subject="alice", predicate="knows", object="bob", embedding=(0.3, 0.4)),),
    )
    w = prepared(store, prose_payload=payload)
    graph = project(store, w.gen)
    fact = graph.facts[0]
    edge = graph.edge_between(graph.idx_of[fact.subject_id], graph.idx_of[fact.object_id])
    assert edge.synonym_score == pytest.approx(expected)
    np.testing.assert_array_equal(
        graph.fact_embeddings[0], np.asarray(payload.triples[0].embedding, dtype=np.float32)
    )
    assert store._knowledge_get("ProseExtraction", w.extractions[0].id).payload == payload
