"""Lineage inventories reuse reads only within one immutable validation pass."""

from collections import Counter

import pytest

from hippo.knowledge import derivations as d
from tests.unit.test_derived_evidence_access import world


def count_records(store, monkeypatch):
    counts = Counter()
    original = store._knowledge_get

    def counted(kind, identity):
        counts[kind, identity] += 1
        return original(kind, identity)

    monkeypatch.setattr(store, "_knowledge_get", counted)
    return counts


def test_inventory_reads_each_record_once(store, monkeypatch):
    w = world(store)
    counts = count_records(store, monkeypatch)
    inventory = d._Inventory(store, w.gen.id)
    first = inventory.view(w.view)
    assert inventory.view(w.view) == first
    assert first.span_ids == frozenset(s.id for s in w.spans)
    assert max(counts.values()) == 1


def test_proof_shares_view_and_prose_inventory(store, monkeypatch):
    w = world(store)
    counts = count_records(store, monkeypatch)
    proof = w.engine.build(w.selection)
    assert proof.retrieval_view_ids == frozenset({w.view.id})
    assert proof.prose_extraction_ids == frozenset({w.prose.id})
    assert counts["EvidenceSpan", w.spans[1].id] == 1


def test_cached_nonexact_record_still_requires_exact_membership(store):
    w = world(store)
    inventory = d._Inventory(store, w.gen.id)
    revision_id = w.spans[0].revision_id
    assert inventory.record("ArtifactRevision", revision_id, exact=False).id == revision_id
    with pytest.raises(ValueError, match="exact generation membership"):
        inventory.record("ArtifactRevision", revision_id)


def test_fresh_proof_detects_corruption_without_epoch_change(store):
    w = world(store)
    proof = w.engine.build(w.selection)
    epoch = w.engine.epoch_reader()
    store._write_knowledge(w.spans[1].replace(policy_id="corrupted-policy"))
    assert w.engine.epoch_reader() == epoch
    with pytest.raises(ValueError, match="input version differs"):
        w.engine.validate_current(proof)


@pytest.mark.parametrize("kind", ["view", "prose"])
def test_standalone_validation_reads_fresh_records(store, kind):
    w = world(store)
    validate = (
        (lambda: d.validate_view(store, w.gen.id, w.view))
        if kind == "view"
        else (lambda: d.validate_prose(store, w.gen.id, w.prose))
    )
    validate()
    store._write_knowledge(w.spans[1].replace(policy_id="corrupted-policy"))
    with pytest.raises(ValueError, match="input version differs"):
        validate()


def test_generation_views_rejects_mismatched_inventory(store):
    w = world(store)
    inventory = d._Inventory(store, w.gen.id)
    with pytest.raises(ValueError, match="generation"):
        d.GenerationViews(store, "another-generation", inventory=inventory).validate(w.view)
