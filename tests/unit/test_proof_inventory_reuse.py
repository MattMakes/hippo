"""A proof may share only its raw, store-bound reads with derivation validation."""

from collections import Counter

import pytest

from hippo.knowledge import access as a
from hippo.knowledge import derivations as d
from hippo.knowledge import model as k
from tests.unit.test_derived_evidence_access import world


def test_proof_inventory_does_not_repeat_raw_record_lookup(store, monkeypatch):
    w = world(store)
    counts = Counter()
    original = store._knowledge_get

    def counted(kind, identity):
        counts[kind, identity] += 1
        return original(kind, identity)

    monkeypatch.setattr(store, "_knowledge_get", counted)
    proof = w.engine.build(w.selection)

    assert proof.retrieval_view_ids == frozenset({w.view.id})
    assert counts["EvidenceSpan", w.spans[1].id] == 0


def test_proof_inventory_queries_each_derived_parent_dependencies_once(store, monkeypatch):
    w = world(store)
    counts = Counter()
    original = store._knowledge_rows

    def counted(kind, *, generation_id=None, where=None, ids=None):
        if kind == "DerivedDependency" and where and "derived_record_id" in where:
            counts[where["derived_record_id"]] += 1
        return original(kind, generation_id=generation_id, where=where, ids=ids)

    monkeypatch.setattr(store, "_knowledge_rows", counted)
    proof = w.engine.build(w.selection)

    assert proof.retrieval_view_ids == frozenset({w.view.id})
    assert counts[w.dr.id] == 1


def test_proof_inventory_detects_persisted_nonmember_dependency(store):
    w = world(store)
    revision = store._knowledge_get("ArtifactRevision", w.spans[0].revision_id)
    extra = k.DerivedDependency(
        derived_record_id=w.dr.id,
        input_kind="revision",
        input_id=revision.id,
        input_version=d.dependency_version(revision),
    )
    store._write_knowledge(extra)

    with pytest.raises(ValueError, match="exact generation membership"):
        w.engine.build(w.selection)


def test_proof_inventory_never_authorizes_private_secondary_input(store):
    w = world(store, private_secondary=True)
    proof = w.engine.build(w.selection)

    assert proof.span_ids == frozenset({w.spans[0].id})
    assert not proof.retrieval_view_ids
    assert not proof.prose_extraction_ids
    assert not proof.derived_record_ids
    assert not proof.derived_dependency_ids


def test_separate_proofs_observe_intervening_corruption(store):
    w = world(store)
    assert w.engine.build(w.selection).retrieval_view_ids == frozenset({w.view.id})
    store._write_knowledge(w.spans[1].replace(policy_id="corrupted-policy"))

    with pytest.raises(ValueError, match="input version differs"):
        w.engine.build(w.selection)


def test_generation_views_rejects_proof_reader_from_another_store(store):
    w = world(store)
    reads = a._ProofReads(object(), bounded=True)

    with pytest.raises(ValueError, match="store"):
        d.GenerationViews(store, w.gen.id, _proof_reads=reads)


def test_injected_reader_preserves_unknown_generation_error(store):
    w = world(store)
    store._delete_knowledge_record("Generation", w.gen.id)
    reads = a._ProofReads(store, bounded=True)

    with pytest.raises(ValueError, match="^Unknown generation$"):
        d.GenerationViews(store, w.gen.id, _proof_reads=reads).validate(w.view)
