"""Published interpretations stay exact even when raw revisions are reused."""

from types import SimpleNamespace

import pytest

from hippo.knowledge import model as k
from hippo.knowledge.access import EvidenceSelection
from tests.unit.test_evidence_access import NOW, engine, observation, policy, relationship, span, world


def generation(w, records, *, strict=True, name="first"):
    gen = w.store.add(
        k.Generation(
            source_id="s",
            status="active",
            parser_version=name,
            linker_version="l",
            embedding_profile="e",
            created_at=NOW,
            published_at=NOW,
            manifest_hash=name,
        )
    )
    w.store.add(k.GenerationMember(generation_id=gen.id, artifact_revision_id=w.revision.id))
    if strict:
        w.store.add(
            k.IndexManifest(
                generation_id=gen.id,
                profile_fingerprint="e",
                config_fingerprint="c",
                required_representations=("evidence", "dense", "native"),
                checksums=tuple(
                    k.RepresentationChecksum(kind=kind, checksum="test", row_count=0, ready=True)
                    for kind in ("evidence", "dense", "native")
                ),
                ready=True,
            )
        )
        # Read-contract fixture intentionally does not claim store sealing validation.
        for record in records:
            identity = f"{gen.id}:{type(record).__name__}:{record.id}"
            w.store.records["GenerationEvidenceMember"][identity] = SimpleNamespace(
                id=identity,
                generation_id=gen.id,
                record_kind=type(record).__name__,
                record_id=record.id,
            )
    return gen


def select(gen, **kwargs):
    return EvidenceSelection(generation_ids=frozenset({gen.id}), **kwargs)


def test_new_interpretation_on_old_revision_cannot_change_selected_generation():
    w = world()
    obj, old, evidence = observation(w, "billing")
    gen = generation(w, [old, evidence])
    before = engine(w).build(select(gen))
    later = w.store.add(
        k.ObjectObservation(
            object_id=obj.id,
            revision_id=w.revision.id,
            span_id=evidence.id,
            evidence_class="declared",
            recorded_from=NOW,
            attributes_json='{"name":"changed"}',
        )
    )
    extra = span(w, "newly-extracted-span")
    generation(w, [later, evidence, extra], name="second")
    after = engine(w).build(select(gen))
    assert after.observation_ids == before.observation_ids == frozenset({old.id})
    assert after.span_ids == before.span_ids == frozenset({evidence.id})
    assert after.policy_fingerprint == before.policy_fingerprint


def test_selected_support_inventory_keeps_private_and_member():
    w = world()
    _, version = relationship(w)
    records = [
        record
        for kind in ("EvidenceSpan", "ObjectObservation", "AssertionVersion", "AssertionSupport")
        for record in w.store._knowledge_rows(kind)
    ]
    gen = generation(w, records)
    assert version.id not in engine(w).build(select(gen)).assertion_version_ids
    direct = span(w, "new-independent-proof")
    w.store.add(
        k.AssertionSupport(assertion_version_id=version.id, span_id=direct.id, derivation_group="new")
    )
    # A support outside the interpretation cannot supply a new OR branch.
    assert version.id not in engine(w).build(select(gen)).assertion_version_ids


def test_private_unselected_observation_does_not_change_proof_deadline():
    w = world()
    _, obs, evidence = observation(w, "billing")
    gen = generation(w, [obs, evidence])
    before = engine(w).build(select(gen))
    span(w, "private", policy(w))
    after = engine(w).build(select(gen))
    assert before.policy_fingerprint == after.policy_fingerprint


def test_empty_sealed_generation_does_not_fall_back_to_revision_inventory():
    w = world()
    observation(w, "unselected")
    gen = generation(w, [])
    proof = engine(w).build(select(gen))
    assert not proof.span_ids and not proof.observation_ids


def test_compatibility_generation_retains_existing_revision_selection():
    w = world()
    _, obs, evidence = observation(w, "legacy")
    gen = generation(w, [], strict=False)
    proof = engine(w).build(select(gen))
    assert obs.id in proof.observation_ids and evidence.id in proof.span_ids


def test_durable_selection_refuses_missing_exact_manifest():
    w = world()
    gen = generation(w, [], strict=False)
    with pytest.raises(ValueError, match="exact|sealed|rebuild"):
        engine(w).build(select(gen, require_exact_membership=True))


def test_exact_selection_requires_explicit_generations():
    with pytest.raises(ValueError, match="generation"):
        EvidenceSelection(require_exact_membership=True)


def test_staged_artifact_cannot_change_selected_proof():
    w = world()
    _, obs, evidence = observation(w, "selected")
    gen = generation(w, [obs, evidence])
    before = engine(w).build(select(gen))
    artifact = w.store.add(
        k.Artifact(
            workspace_id=w.workspace.id,
            source_id="s",
            kind="file",
            external_id="new.md",
            canonical_uri="source:s/new.md",
            policy_id=w.parent.id,
        )
    )
    w.store.add(
        k.ArtifactRevision(
            artifact_id=artifact.id,
            content_hash="new",
            raw_uri="blob:new",
            observed_at=NOW,
            lifecycle="active",
        )
    )
    after = engine(w).build(select(gen))
    assert after.artifact_ids == before.artifact_ids
    assert after.policy_fingerprint == before.policy_fingerprint
