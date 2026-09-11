"""Rendered retrieval text is immutable derived evidence, never an original span."""

import importlib

import pytest

from hippo.knowledge import model as k
from hippo.knowledge.identity import canonical_json, text_hash
from hippo.knowledge.lifecycle import generation_passage_id
from hippo.store import migrations
from tests.unit.test_generation_store import authority, claim, evidence, generation, passage, publish, seal


def helpers():
    assert hasattr(k, "ProseExtraction"), "typed prose extraction storage is missing"
    return importlib.import_module("hippo.knowledge.derivations")


def member(store, gen, record):
    store.put_knowledge(record)
    store.put_knowledge(
        k.GenerationEvidenceMember(
            generation_id=gen.id, record_kind=type(record).__name__, record_id=record.id
        )
    )


def rendered(store, gen, span, text="rendered card", *, selected=True):
    d = helpers()
    dependencies = [("span", span.id, d.dependency_version(span))]
    fp = d.view_fingerprint(
        view_kind="projection",
        text=text,
        text_profile="render-v1",
        vector_profile="p",
        rule_version="render-v1",
        model_version=None,
        dependencies=dependencies,
    )
    dr = k.DerivedRecord(
        workspace_id=store.get_source(gen.source_id)["workspace_id"],
        view_kind="projection",
        rule_version="render-v1",
        input_revision_ids=(span.revision_id,),
        dependency_fingerprint=fp,
        state="ready",
    )
    member(store, gen, dr)
    dep = k.DerivedDependency(
        derived_record_id=dr.id, input_kind="span", input_id=span.id, input_version=dependencies[0][2]
    )
    (member(store, gen, dep) if selected else store.put_knowledge(dep))
    view = k.RetrievalView(
        span_id=span.id,
        view_kind="projection",
        text=text,
        text_profile="render-v1",
        vector_profile="p",
        source_revision_id=span.revision_id,
        derivation_version="render-v1",
        dependency_fingerprint=fp,
        derived_record_id=dr.id,
    )
    member(store, gen, view)
    return view, dr, dep


def setup_view(store):
    helpers()
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        rev, span = evidence(store, gen)
        view, dr, dep = rendered(store, gen, span)
        row = passage(gen, rev, span)
        row.update(
            retrieval_view_id=view.id,
            text=view.text,
            id=generation_passage_id(gen.id, rev.id, span.id, 0, retrieval_view_id=view.id),
        )
        store.add_passages([row])
    return gen, job, span, view, dr, dep, row


def extraction(store, gen, span, row, *, payload=None):
    d = helpers()
    payload = payload or k.ProseExtractionPayload(
        entities=(
            k.ProseEntity(name="alice", embedding=(0.1, 0.2)),
            k.ProseEntity(name="bob", embedding=(0.2, 0.1)),
        ),
        triples=(k.ProseTriple(subject="alice", predicate="knows", object="bob", embedding=(0.3, 0.4)),),
    )
    dependencies = [("span", span.id, d.dependency_version(span))]
    fields = dict(
        input_kind="span",
        input_id=span.id,
        input_text_hash=span.text_hash,
        support_passage_ids=(row["id"],),
        extractor_profile="openie-v1",
        embedding_profile="p",
        payload_hash=text_hash(canonical_json(payload.model_dump(mode="json"))),
    )
    fp = d.prose_fingerprint(
        rule_version="openie-v1", model_version="model-v1", dependencies=dependencies, **fields
    )
    dr = k.DerivedRecord(
        workspace_id=store.get_source(gen.source_id)["workspace_id"],
        view_kind="projection",
        rule_version="openie-v1",
        model_version="model-v1",
        input_revision_ids=(span.revision_id,),
        dependency_fingerprint=fp,
        state="ready",
    )
    member(store, gen, dr)
    member(
        store,
        gen,
        k.DerivedDependency(
            derived_record_id=dr.id, input_kind="span", input_id=span.id, input_version=dependencies[0][2]
        ),
    )
    return k.ProseExtraction(generation_id=gen.id, derived_record_id=dr.id, payload=payload, **fields)


def test_schema5_freezes_v4_and_preserves_original_checksum_shape(store):
    assert migrations.CURRENT_SCHEMA_VERSION == 5
    assert (
        migrations.SUPPORTED_CHECKSUMS[4]
        == "af3234c2ffd6aa2a5c935b06352ad91c92b8c44f80926969a6c3a775a4d5dfd7"
    )
    assert text_hash(canonical_json(migrations._descriptor(4))) == migrations.SUPPORTED_CHECKSUMS[4]
    assert "ProseExtraction" not in migrations._descriptor(4)[1]
    assert "retrieval_view_id" not in store._canonical_native("Passage", dict(id="x", embedding=[]))


def test_two_views_retain_original_and_roundtrip(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        other, _, _ = rendered(store, gen, span, text="another view")
        store.add_passages(
            [
                {
                    **row,
                    "id": generation_passage_id(
                        gen.id, span.revision_id, span.id, 0, retrieval_view_id=other.id
                    ),
                    "retrieval_view_id": other.id,
                    "text": other.text,
                    "embedding": [0.3, 0.4],
                }
            ]
        )
    assert store._knowledge_get("EvidenceSpan", span.id).text == span.text
    assert store._knowledge_get("RetrievalView", view.id) == view
    assert {r["retrieval_view_id"] for r in store._native_rows("Passage")} == {view.id, other.id}
    seal(store, gen, job)
    assert helpers().validate_view(store, gen.id, view).span_ids == frozenset({span.id})


def test_incomplete_dependency_group_cannot_bind_a_passage(store):
    helpers()
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        rev, span = evidence(store, gen)
        view, _, _ = rendered(store, gen, span, selected=False)
        row = passage(gen, rev, span)
    with pytest.raises(ValueError), store.generation_write(gen.id, **authority(job)):
        store.add_passages(
            [
                {
                    **row,
                    "id": generation_passage_id(gen.id, rev.id, span.id, 0, retrieval_view_id=view.id),
                    "retrieval_view_id": view.id,
                    "text": view.text,
                }
            ]
        )


def test_sealed_dependency_group_and_state_cannot_change(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    seal(store, gen, job)
    with pytest.raises(ValueError):
        store.put_knowledge(
            k.DerivedDependency(
                derived_record_id=dr.id, input_kind="revision", input_id=span.revision_id, input_version="new"
            )
        )
    with pytest.raises(ValueError):
        store.update_knowledge(dr.replace(state="retired"))
    with pytest.raises(ValueError):
        store.add_passages([{key: value for key, value in row.items() if key != "retrieval_view_id"}])


def test_prose_roundtrip_and_exact_membership_seal(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        record = extraction(store, gen, span, row)
        member(store, gen, record)
    assert store._knowledge_get("ProseExtraction", record.id) == record
    closure = helpers().validate_prose(store, gen.id, record)
    assert closure.support_passage_ids == frozenset({row["id"]})
    assert view.id in closure.view_ids
    seal(store, gen, job)
    publish(store, gen, job)


@pytest.mark.parametrize("vector", [(True, 0.2), (float("nan"), 0.2), (float("inf"), 0.2), ()])
def test_prose_vectors_reject_invalid_values(vector):
    helpers()
    with pytest.raises(ValueError):
        k.ProseEntity(name="alice", embedding=vector)


def test_prose_payload_rejects_mixed_dimensions_and_unknown_keys():
    helpers()
    with pytest.raises(ValueError):
        k.ProseExtractionPayload(
            entities=(
                k.ProseEntity(name="a", embedding=(0.1,)),
                k.ProseEntity(name="b", embedding=(0.1, 0.2)),
            )
        )
    with pytest.raises(ValueError):
        k.ProseExtractionPayload(entities=(), triples=(), evidence_class="declared")


def test_original_ids_remain_unchanged_with_null_view():
    from hippo.knowledge.identity import make_identity

    helpers()
    assert generation_passage_id("g", "r", "s", 0, retrieval_view_id=None) == make_identity(
        "passage", ["g", "r", "s", 0]
    )
    assert generation_passage_id("g", "r", "s", 0, retrieval_view_id="view") != generation_passage_id(
        "g", "r", "s", 0
    )


def test_view_rejects_changed_original_dependency_version(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    bad = dep.replace(input_version="stale")
    # Persisted corruption models a lost input/version; no caller-provided hash is trusted.
    store._delete_knowledge_record("DerivedDependency", dep.id)
    store._write_knowledge(bad)
    store._write_knowledge(
        k.GenerationEvidenceMember(generation_id=gen.id, record_kind="DerivedDependency", record_id=bad.id)
    )
    with pytest.raises(ValueError):
        seal(store, gen, job)


@pytest.mark.parametrize("change", ["text", "profile", "anchor"])
def test_rendered_native_binding_rejects_changed_payload(store, change):
    gen, job, span, view, dr, dep, row = setup_view(store)
    values = {"text": "fabricated original", "embedding_profile": "other", "span_id": "missing"}
    field = {"text": "text", "profile": "embedding_profile", "anchor": "span_id"}[change]
    with pytest.raises(ValueError), store.generation_write(gen.id, **authority(job)):
        store.add_passages([{**row, field: values[field]}])


def test_prose_dimension_mismatch_with_dense_rejected_at_seal(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        payload = k.ProseExtractionPayload(entities=(k.ProseEntity(name="alice", embedding=(0.1,)),))
        member(store, gen, extraction(store, gen, span, row, payload=payload))
    with pytest.raises(ValueError, match="dimension"):
        seal(store, gen, job)


def test_conflicting_successful_outputs_for_one_input_cannot_seal(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        member(store, gen, extraction(store, gen, span, row))
        member(store, gen, extraction(store, gen, span, row, payload=k.ProseExtractionPayload()))
    with pytest.raises(ValueError, match="Conflicting prose"):
        seal(store, gen, job)


def test_prose_requires_live_generation_lease_even_with_valid_inputs(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        record = extraction(store, gen, span, row)
    with pytest.raises(ValueError):
        store.put_knowledge(record)


def test_collected_generation_keeps_immutable_derived_tombstones(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        record = extraction(store, gen, span, row)
        member(store, gen, record)
    seal(store, gen, job)
    publish(store, gen, job)
    new = generation(store, "new", gen)
    new_job = claim(store, new, key="new")
    seal(store, new, new_job)
    publish(store, new, new_job)
    assert store.collect_generation(gen.id).blocked_reason is None
    assert store._knowledge_get("ProseExtraction", record.id) == record
    with pytest.raises(ValueError):
        helpers().validate_prose(store, gen.id, record)
    with pytest.raises(ValueError):
        store.put_knowledge(
            k.DerivedDependency(
                derived_record_id=dr.id,
                input_kind="revision",
                input_id=span.revision_id,
                input_version="more",
            )
        )


@pytest.mark.parametrize("legacy_view", [False, True])
def test_actual_v4_upgrade_retains_original_seal(tmp_path, monkeypatch, legacy_view):
    from hippo.store.ladybug import LadybugStore

    path = tmp_path / "v4.lbug"
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "CURRENT_SCHEMA_VERSION", 4)
        old = LadybugStore(path)
        gen = generation(old)
        job = claim(old, gen)
        with old.generation_write(gen.id, **authority(job)):
            rev, span = evidence(old, gen)
            row = passage(gen, rev, span)
            old.run(
                "MATCH (s:Source {id:$source_id}) CREATE (p:Passage {id:$id,text:$text,title:$title,ordinal:$ordinal,embedding:$embedding,generation_id:$generation_id,artifact_revision_id:$artifact_revision_id,span_id:$span_id,embedding_profile:$embedding_profile})-[:FROM]->(s)",
                **row,
            )
        if legacy_view:
            dr = k.DerivedRecord(
                workspace_id=old.get_source(gen.source_id)["workspace_id"],
                view_kind="projection",
                rule_version="legacy-v4",
                input_revision_ids=(rev.id,),
                dependency_fingerprint="opaque-v4",
                state="ready",
            )
            view = k.RetrievalView(
                span_id=span.id,
                source_revision_id=rev.id,
                view_kind="projection",
                text="legacy unbound metadata",
                text_profile="legacy",
                derivation_version="legacy-v4",
                dependency_fingerprint="opaque-v4",
                derived_record_id=dr.id,
            )
            # Literal historical storage shape: v4 did not stamp a capability or
            # interpret unbound metadata using the new fingerprint contract.
            for record in (dr, view):
                old._write_knowledge(record)
                old._write_knowledge(
                    k.GenerationEvidenceMember(
                        generation_id=gen.id, record_kind=type(record).__name__, record_id=record.id
                    )
                )
        seal(old, gen, job)
        publish(old, gen, job)
        before = old.validate_generation_seal(gen.id)
        history = old.schema_history()
        old.close()
    upgraded = LadybugStore(path)
    try:
        assert upgraded.schema_history()[:4] == history
        assert upgraded.validate_generation_seal(gen.id) == before
        assert not helpers().derived_capability(upgraded._generation(gen.id))
        assert upgraded._native_rows("Passage")[0]["retrieval_view_id"] is None
    finally:
        upgraded.close()


def test_payload_rejects_unnormalized_embedded_names():
    helpers()
    with pytest.raises(ValueError, match="normalized"):
        k.ProseExtractionPayload(entities=(k.ProseEntity(name="Radio-City", embedding=(0.1, 0.2)),))


def test_empty_successful_extraction_remains_distinct_from_missing_output(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        record = extraction(store, gen, span, row, payload=k.ProseExtractionPayload())
        member(store, gen, record)
    assert record.payload.entities == record.payload.triples == ()
    seal(store, gen, job)


def test_all_original_inputs_are_exposed_in_view_and_prose_closure(store):
    d = helpers()
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        rev, span = evidence(store, gen)
        secondary = span.replace(
            text="secondary original",
            text_hash=text_hash("secondary original"),
            locator_json='{"kind":"file_lines","path":"a.txt","start":2,"end":2}',
        )
        member(store, gen, secondary)
        deps = [("span", s.id, d.dependency_version(s)) for s in (span, secondary)]
        fp = d.view_fingerprint(
            view_kind="projection",
            text="combined",
            text_profile="render-v1",
            vector_profile="p",
            rule_version="render-v1",
            model_version=None,
            dependencies=deps,
        )
        dr = k.DerivedRecord(
            workspace_id=store.get_source(gen.source_id)["workspace_id"],
            view_kind="projection",
            rule_version="render-v1",
            input_revision_ids=(rev.id,),
            dependency_fingerprint=fp,
            state="ready",
        )
        member(store, gen, dr)
        for kind, identity, version in deps:
            member(
                store,
                gen,
                k.DerivedDependency(
                    derived_record_id=dr.id, input_kind=kind, input_id=identity, input_version=version
                ),
            )
        view = k.RetrievalView(
            span_id=span.id,
            source_revision_id=rev.id,
            view_kind="projection",
            text="combined",
            text_profile="render-v1",
            vector_profile="p",
            derivation_version="render-v1",
            dependency_fingerprint=fp,
            derived_record_id=dr.id,
        )
        member(store, gen, view)
        row = passage(gen, rev, span)
        row.update(
            id=generation_passage_id(gen.id, rev.id, span.id, 0, retrieval_view_id=view.id),
            retrieval_view_id=view.id,
            text=view.text,
        )
        store.add_passages([row])
        prose = extraction(store, gen, span, row)
        member(store, gen, prose)
    assert d.validate_view(store, gen.id, view).span_ids == frozenset({span.id, secondary.id})
    assert d.validate_prose(store, gen.id, prose).span_ids == frozenset({span.id, secondary.id})
    seal(store, gen, job)


def test_exact_prose_member_cannot_claim_another_generation_output(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        record = extraction(store, gen, span, row)
        member(store, gen, record)
    seal(store, gen, job)
    publish(store, gen, job)
    new = generation(store, "new", gen)
    new_job = claim(store, new, key="new")
    with store.generation_write(new.id, **authority(new_job)):
        store.put_knowledge(k.GenerationMember(generation_id=new.id, artifact_revision_id=span.revision_id))
    with pytest.raises(ValueError), store.generation_write(new.id, **authority(new_job)):
        store.put_knowledge(
            k.GenerationEvidenceMember(
                generation_id=new.id, record_kind="ProseExtraction", record_id=record.id
            )
        )


def test_payload_version_is_a_strict_integer():
    helpers()
    with pytest.raises(ValueError):
        k.ProseExtractionPayload(schema_version=True)


def test_unrelated_prose_support_is_rejected(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        other = span.replace(
            text="other",
            text_hash=text_hash("other"),
            locator_json='{"kind":"file_lines","path":"a.txt","start":3,"end":3}',
        )
        member(store, gen, other)
        revision = store._knowledge_get("ArtifactRevision", span.revision_id)
        other_row = passage(gen, revision, other)
        store.add_passages([other_row])
        record = extraction(store, gen, span, other_row)
    with pytest.raises(ValueError), store.generation_write(gen.id, **authority(job)):
        member(store, gen, record)


def test_failed_retry_selects_only_new_prose_output(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        old = extraction(store, gen, span, row)
        member(store, gen, old)
    store.discard_generation(gen.id, **authority(job))
    retry = claim(store, gen, key="retry")
    with store.generation_write(gen.id, **authority(retry)):
        rev, span = evidence(store, gen)
        view, dr, dep = rendered(store, gen, span)
        store.add_passages([row])
        fresh = extraction(store, gen, span, row, payload=k.ProseExtractionPayload())
        member(store, gen, fresh)
    selected = {
        m.record_id
        for m in store._knowledge_rows("GenerationEvidenceMember")
        if m.generation_id == gen.id and m.record_kind == "ProseExtraction"
    }
    assert selected == {fresh.id}
    assert store._knowledge_get("ProseExtraction", old.id) == old
    seal(store, gen, retry)


def test_view_input_prose_closure_includes_both_derivations(store):
    gen, job, span, view, dr, dep, row = setup_view(store)
    d = helpers()
    with store.generation_write(gen.id, **authority(job)):
        dependencies = [("span", span.id, d.dependency_version(span))]
        payload = k.ProseExtractionPayload()
        fields = dict(
            input_kind="view",
            input_id=view.id,
            input_text_hash=text_hash(view.text),
            support_passage_ids=(row["id"],),
            extractor_profile="openie-v1",
            embedding_profile="p",
            payload_hash=text_hash(canonical_json(payload.model_dump(mode="json"))),
        )
        fingerprint = d.prose_fingerprint(
            rule_version="openie-v1", model_version="model-v1", dependencies=dependencies, **fields
        )
        prose_dr = k.DerivedRecord(
            workspace_id=dr.workspace_id,
            view_kind="projection",
            rule_version="openie-v1",
            model_version="model-v1",
            input_revision_ids=(span.revision_id,),
            dependency_fingerprint=fingerprint,
            state="ready",
        )
        member(store, gen, prose_dr)
        member(
            store,
            gen,
            k.DerivedDependency(
                derived_record_id=prose_dr.id,
                input_kind="span",
                input_id=span.id,
                input_version=dependencies[0][2],
            ),
        )
        record = k.ProseExtraction(
            generation_id=gen.id, derived_record_id=prose_dr.id, payload=payload, **fields
        )
        member(store, gen, record)
    closure = d.validate_prose(store, gen.id, record)
    assert closure.derived_record_ids == frozenset({dr.id, prose_dr.id})
    assert closure.view_ids == frozenset({view.id})
    seal(store, gen, job)


def test_saved_snapshot_retains_derived_generation_across_reopen(tmp_path):
    from datetime import timedelta

    from hippo.store.ladybug import LadybugStore
    from tests.unit.test_generation_store import NOW
    from tests.unit.test_snapshot_store import snapshot

    path = tmp_path / "derived-retained.lbug"
    store = LadybugStore(path)
    gen, job, span, view, dr, dep, row = setup_view(store)
    with store.generation_write(gen.id, **authority(job)):
        record = extraction(store, gen, span, row)
        member(store, gen, record)
    seal(store, gen, job)
    publish(store, gen, job)
    snap = snapshot(store, gen)
    active = store.acquire_snapshot_reference(
        snap, reference_key="request", lease_owner="reader", lease_expires_at=NOW + timedelta(minutes=2)
    )
    saved = store.retain_snapshot(snap.id, kind="saved", reference_key="saved-output")
    store.release_snapshot_reference(active.id, lease_owner="reader")
    new = generation(store, "new", gen)
    new_job = claim(store, new, key="new")
    seal(store, new, new_job)
    publish(store, new, new_job)
    store.close()
    reopened = LadybugStore(path)
    try:
        reopened._generation_clock = lambda: NOW
        assert reopened.collect_generation(gen.id).blocked_reason == "snapshot_reference"
        assert helpers().validate_prose(reopened, gen.id, record).view_ids == frozenset({view.id})
        reopened.validate_generation_seal(gen.id)
        reopened.release_snapshot_reference(saved.id)
        assert reopened.collect_generation(gen.id).blocked_reason is None
    finally:
        reopened.close()


def test_selected_unbound_view_requires_complete_dependencies_at_seal(store):
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
        store.add_passages([passage(gen, revision, span)])
        rendered(store, gen, span, selected=False)
    with pytest.raises(ValueError, match="exact"):
        seal(store, gen, job)


def test_capability_cannot_be_preseeded_or_downgraded(store):
    gen = generation(store)
    malicious = gen.replace(manifest_hash="new-input", coverage_json='{"derived_evidence_version":0}')
    with pytest.raises(ValueError, match="capability"):
        store.put_knowledge(malicious)
    gen, job, span, view, dr, dep, row = setup_view(store)
    stored = store._generation(gen.id)
    assert helpers().derived_capability(stored)
    with pytest.raises(ValueError):
        store.update_knowledge(stored.replace(coverage_json="{}"))


def test_selected_orphan_derivation_cannot_hide_unselected_children(store):
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
        store.add_passages([passage(gen, revision, span)])
        view, dr, dep = rendered(store, gen, span, selected=False)
        store._delete_knowledge_record(
            "GenerationEvidenceMember",
            k.GenerationEvidenceMember(
                generation_id=gen.id, record_kind="RetrievalView", record_id=view.id
            ).id,
        )
    with pytest.raises(ValueError, match="exact"):
        seal(store, gen, job)
