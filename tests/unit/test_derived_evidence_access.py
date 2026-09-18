"""A derived output grants no access beyond its complete original lineage."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from hippo.access import Access
from hippo.knowledge import derivations as d
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged, EvidenceAccess, EvidenceSelection
from hippo.knowledge.identity import canonical_json
from hippo.knowledge.lifecycle import generation_passage_id
from tests.unit.test_derived_generation_store import extraction, member
from tests.unit.test_generation_store import NOW, authority, claim, generation, passage, publish, seal


def add_view(store, gen, spans):
    dependencies = [("span", span.id, d.dependency_version(span)) for span in spans]
    fingerprint = d.view_fingerprint(
        view_kind="projection",
        text="combined rendered text",
        text_profile="render-v1",
        vector_profile="p",
        rule_version="render-v1",
        model_version=None,
        dependencies=dependencies,
    )
    derived = k.DerivedRecord(
        workspace_id=store.get_source(gen.source_id)["workspace_id"],
        view_kind="projection",
        rule_version="render-v1",
        input_revision_ids=tuple(sorted({s.revision_id for s in spans})),
        dependency_fingerprint=fingerprint,
        state="ready",
    )
    member(store, gen, derived)
    deps = []
    for kind, identity, version in dependencies:
        dep = k.DerivedDependency(
            derived_record_id=derived.id,
            input_kind=kind,
            input_id=identity,
            input_version=version,
        )
        member(store, gen, dep)
        deps.append(dep)
    view = k.RetrievalView(
        span_id=spans[0].id,
        source_revision_id=spans[0].revision_id,
        view_kind="projection",
        text="combined rendered text",
        text_profile="render-v1",
        vector_profile="p",
        derivation_version="render-v1",
        dependency_fingerprint=fingerprint,
        derived_record_id=derived.id,
    )
    member(store, gen, view)
    return view, derived, deps


def world(store, *, private_secondary=False, derived=True):
    gen = generation(store)
    job = claim(store, gen)
    workspace = store.get_source(gen.source_id)["workspace_id"]
    store.ensure_roles()
    user = store.create_user("alice", "correct-password", "arch-admin")
    store.update_knowledge(
        k.WorkspaceMembership(
            workspace_id=workspace,
            principal_id=user,
            enabled=True,
            mapping_authority="reviewed",
            policy_epoch=2,
        )
    )
    policy = k.AccessPolicy(
        workspace_id=workspace,
        origin="local_curated",
        scope_key=gen.source_id,
        mode="workspace",
        verified_at=NOW,
    )
    secondary_policy = (
        policy
        if not private_secondary
        else k.AccessPolicy(
            workspace_id=workspace,
            origin="local_curated",
            scope_key=gen.source_id + "/secondary",
            mode="restricted",
            allow_users=("another-user",),
            verified_at=NOW,
        )
    )
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=gen.source_id,
        kind="file",
        external_id="a.txt",
        canonical_uri="a.txt",
        policy_id=policy.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        content_hash="original",
        raw_uri="blob:original",
        observed_at=NOW,
        lifecycle="active",
    )
    spans = [
        k.EvidenceSpan(
            revision_id=revision.id,
            locator_kind="file_lines",
            locator_json=canonical_json(dict(kind="file_lines", path="a.txt", start=n, end=n)),
            text=text,
            policy_id=grant.id,
        )
        for n, text, grant in ((1, "public anchor", policy), (2, "secondary original", secondary_policy))
    ]
    with store.generation_write(gen.id, **authority(job)):
        for record in (
            policy,
            secondary_policy,
            artifact,
            revision,
            k.GenerationMember(generation_id=gen.id, artifact_revision_id=revision.id),
        ):
            store.put_knowledge(record)
        for span in spans:
            member(store, gen, span)
        row = passage(gen, revision, spans[0])
        view = dr = prose = None
        deps = []
        if derived:
            view, dr, deps = add_view(store, gen, spans)
            row.update(
                id=generation_passage_id(gen.id, revision.id, spans[0].id, 0, retrieval_view_id=view.id),
                retrieval_view_id=view.id,
                text=view.text,
            )
        store.add_passages([row])
        if derived:
            # OpenIE sees only the anchor, but its support card also contains the
            # secondary original. Authorization must cover that complete card.
            prose = extraction(store, gen, spans[0], row)
            member(store, gen, prose)
    seal(store, gen, job)
    publish(store, gen, job)
    engine = EvidenceAccess(
        store,
        workspace,
        Access(user_id=user, rank=100),
        mapping_authorities=frozenset({"reviewed"}),
        clock=lambda: NOW,
    )
    selection = EvidenceSelection(generation_ids=frozenset({gen.id}), require_exact_membership=True)
    return SimpleNamespace(
        store=store,
        gen=gen,
        job=job,
        workspace=workspace,
        user=user,
        spans=spans,
        view=view,
        dr=dr,
        deps=deps,
        prose=prose,
        row=row,
        engine=engine,
        selection=selection,
    )


def suppress(w, identity, *, kind="derived_record", applicability="all_history", principal=None):
    w.store.put_knowledge(
        k.Suppression(
            workspace_id=w.workspace,
            target_kind=kind,
            target_id=identity,
            scope_key=w.gen.source_id,
            view_applicability=applicability,
            reason="tombstone",
            epoch=w.store.suppression_epoch() + 1,
            created_at=NOW,
            restoration_barrier="reverify",
            all_principals=principal is None,
            principal_ids=() if principal is None else (principal,),
        )
    )


def test_exact_proof_contains_complete_view_and_prose_lineage(store):
    w = world(store)
    proof = w.engine.build(w.selection)
    closure = d.validate_prose(store, w.gen.id, w.prose)
    assert proof.retrieval_view_ids == closure.view_ids == frozenset({w.view.id})
    assert proof.prose_extraction_ids == frozenset({w.prose.id})
    assert proof.derived_record_ids == closure.derived_record_ids
    assert proof.derived_dependency_ids == closure.dependency_ids
    assert proof.span_ids == frozenset(s.id for s in w.spans)
    with pytest.raises(FrozenInstanceError):
        proof.retrieval_view_ids = frozenset()


def test_private_secondary_input_denies_whole_view_and_supported_prose(store):
    w = world(store, private_secondary=True)
    proof = w.engine.build(w.selection)
    assert proof.span_ids == frozenset({w.spans[0].id})
    assert not proof.retrieval_view_ids
    assert not proof.prose_extraction_ids
    assert not proof.derived_record_ids
    assert not proof.derived_dependency_ids


@pytest.mark.parametrize("target", ["view", "prose", "secondary"])
def test_current_suppression_intersects_all_derived_inputs(store, target):
    w = world(store)
    before = w.engine.build(w.selection)
    if target == "secondary":
        suppress(w, w.spans[1].id, kind="span")
    else:
        suppress(w, w.dr.id if target == "view" else w.prose.derived_record_id)
    after = w.engine.build(w.selection)
    assert not after.prose_extraction_ids
    assert bool(after.retrieval_view_ids) == (target == "prose")
    with pytest.raises(AuthorizationChanged):
        w.engine.validate_current(before)


def test_current_only_and_principal_specific_derived_suppression(store):
    w = world(store)
    suppress(w, w.dr.id, applicability="current_only", principal="another-user")
    assert w.view.id in w.engine.build(w.selection).retrieval_view_ids
    suppress(w, w.dr.id, applicability="current_only", principal=w.user)
    assert not w.engine.build(w.selection).retrieval_view_ids
    history = EvidenceSelection(
        generation_ids=frozenset({w.gen.id}),
        query_mode="history",
        require_exact_membership=True,
    )
    assert w.view.id in w.engine.build(history).retrieval_view_ids
    suppress(w, w.dr.id)
    assert not w.engine.build(history).retrieval_view_ids


@pytest.mark.parametrize("selection", ["omitted", "empty", "unsealed"])
def test_derived_outputs_have_no_compatibility_or_unselected_fallback(store, selection):
    w = world(store)
    if selection == "omitted":
        chosen = None
    elif selection == "empty":
        chosen = EvidenceSelection(generation_ids=frozenset(), require_exact_membership=True)
    else:
        newer = generation(store, "unsealed", w.gen)
        chosen = EvidenceSelection(generation_ids=frozenset({newer.id}))
    proof = w.engine.build(chosen)
    assert not proof.retrieval_view_ids
    assert not proof.prose_extraction_ids
    assert not proof.derived_record_ids
    assert not proof.derived_dependency_ids


def test_structural_completeness_is_checked_before_acl_filters(store):
    w = world(store, private_secondary=True)
    dependency = w.deps[1]
    membership = next(
        m
        for m in store._knowledge_rows("GenerationEvidenceMember")
        if m.generation_id == w.gen.id and m.record_id == dependency.id
    )
    # Trusted low-level corruption: ordinary sealed writes already forbid this.
    store._delete_knowledge_record("GenerationEvidenceMember", membership.id)
    with pytest.raises(ValueError, match="exact generation membership"):
        w.engine.build(w.selection)


@pytest.mark.parametrize("corruption", ["missing", "unbound"])
def test_capable_generation_cannot_silently_drop_an_invalid_selected_view(store, corruption):
    w = world(store)
    membership = next(
        m for m in store._knowledge_rows("GenerationEvidenceMember") if m.record_id == w.prose.id
    )
    store._delete_knowledge_record("GenerationEvidenceMember", membership.id)
    if corruption == "missing":
        store._delete_knowledge_record("RetrievalView", w.view.id)
    else:
        store._write_knowledge(w.view.replace(derived_record_id=None))
    with pytest.raises(ValueError):
        w.engine.build(w.selection)


def test_selected_prose_payload_cannot_disappear_from_the_proof(store):
    w = world(store)
    store._delete_knowledge_record("ProseExtraction", w.prose.id)
    with pytest.raises(ValueError):
        w.engine.build(w.selection)


def test_pure_publication_does_not_change_a_selected_derived_proof(store):
    w = world(store)
    before = w.engine.build(w.selection)
    newer = generation(store, "next", w.gen)
    job = claim(store, newer, key="next")
    seal(store, newer, job)
    publish(store, newer, job)
    w.engine.validate_current(before)
    assert w.engine.build(w.selection).policy_fingerprint == before.policy_fingerprint
    empty = w.engine.build(
        EvidenceSelection(generation_ids=frozenset({newer.id}), require_exact_membership=True)
    )
    assert not empty.retrieval_view_ids and not empty.prose_extraction_ids


def test_original_only_proof_hash_is_unchanged():
    from tests.unit.test_evidence_access import engine, span, world

    w = world()
    span(w, "original-only")
    proof = engine(w).build()
    assert proof.policy_fingerprint == "fe50d4cdbb2f77f702c0b1beb89d0bad32027cbce197170d1021a1c310a002d3"
    assert not proof.retrieval_view_ids and not proof.prose_extraction_ids


def test_historical_unmarked_views_do_not_enable_new_derived_authority(store):
    w = world(store, derived=False)
    before = w.engine.build(w.selection)
    derived = k.DerivedRecord(
        workspace_id=w.workspace,
        view_kind="projection",
        rule_version="historical-v4",
        input_revision_ids=(w.spans[0].revision_id,),
        dependency_fingerprint="old-unverified",
        state="ready",
    )
    view = k.RetrievalView(
        span_id=w.spans[0].id,
        source_revision_id=w.spans[0].revision_id,
        view_kind="projection",
        text="old unbound presentation",
        text_profile="historical",
        vector_profile="p",
        derivation_version="historical-v4",
        dependency_fingerprint="old-unverified",
        derived_record_id=derived.id,
    )
    # Simulate imported v4 rows, which predate controlled capability stamping.
    # They are not bound to any dense Passage and retain their old contract.
    for record in (derived, view):
        store._write_knowledge(record)
        store._write_knowledge(
            k.GenerationEvidenceMember(
                generation_id=w.gen.id,
                record_kind=type(record).__name__,
                record_id=record.id,
            )
        )
    after = w.engine.build(w.selection)
    assert after.policy_fingerprint == before.policy_fingerprint
    assert not after.retrieval_view_ids and not after.derived_record_ids
