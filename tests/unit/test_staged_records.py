"""One connector generation is written in fenced dependency groups, resumed and sealed.

Gate CK3. `knowledge/staged_records.py` is the third staged writer, and the first that
belongs to no lane: it shares `staged_code`'s fenced core, its resume probe and its seal
rather than copying them, and it writes the records a connector emits -- spans, objects
with their observations, derived records with their views, passages with their units, and
assertions with their versions and support.

The fixture is a small Jira-shaped connector generation built by hand. The runtime that
produces one for real is S3c's; this suite proves the store-facing half without it, which
is why nothing here reaches `hippo.connectors`.
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from types import SimpleNamespace

import pytest

from hippo.knowledge import build_authority, generation_profiles
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.derivations import dependency_version, view_fingerprint
from hippo.knowledge.embedding_profile import EmbeddingSpec, StoredEmbeddingProfile, _fingerprint
from hippo.knowledge.identity import canonical_json, text_hash
from hippo.knowledge.lifecycle import generation_for_inputs, generation_passage_id
from hippo.knowledge.registry import current_registry

INSTANT = datetime(2030, 1, 1, tzinfo=UTC)
LEASE = timedelta(minutes=5)
PARTITION = "PROJ"
RENDER_RULE = "cdk-render-v1"
BINDER_RULE = "cdk-binder-v1"
TICKETS = {
    "PROJ-1": "The importer drops the last row. Every page loses one.",
    "PROJ-2": "Retrying a failed page is not idempotent yet.",
}
RENDERED_TEXT = "PROJ-1 tracks REQ-9."
_instances = count()

ladybug_only = pytest.mark.skipif(
    os.environ.get("HIPPO_TEST_STORE", "").strip().lower() != "ladybug",
    reason="the durable-backend line of the plan's step 2",
)


def writer():
    try:
        return importlib.import_module("hippo.knowledge.staged_records")
    except ModuleNotFoundError:
        pytest.fail("Generic staged record writer is missing")


def embedding():
    spec = EmbeddingSpec(document_prefix="doc:", query_prefix="query:", dimensions=2)
    profile = spec.make_profile("embed:latest", "a" * 64, 2)
    return StoredEmbeddingProfile(profile, spec, _fingerprint(profile))


# ------------------------------------------------------------------ the accepted inventory


def world(store, *, partition=PARTITION, fault=None):
    """A connector Source, its instance, its remote inputs and the inventory manifest.

    Each call takes its own provider instance: a remote artifact's identity is scoped by
    `provider_instance`, not by the Source (`Artifact.identity_parts`), so two worlds sharing
    one instance would mint one artifact id for two Sources and the second write would refuse.

    `fault` builds a deliberately inconsistent manifest for the profile tests:
    `member_missing` drops one original from its inventory, and `other_connector` moves one
    original to a second instance the manifest never names.
    """
    instance = f"https://jira{next(_instances)}.example.com"
    store.ensure_schema()
    store.ensure_roles()
    if not store.count_users():
        # An enabled provider connector is refused in open mode; one operator makes it a real install.
        store.create_user("operator", "password", "individual")
    source = store.create_source("connector", "Tickets")
    workspace = store.get_source(source)["workspace_id"]
    connector = k.Connector(workspace_id=workspace, kind="jira_cloud", instance_url=instance, enabled=True)
    store.put_knowledge(connector)
    store.update_source(
        source, meta_json=canonical_json({"connector_id": connector.id, "partition": partition})
    )
    provider = k.AccessPolicy(
        workspace_id=workspace,
        origin="provider",
        scope_key=f"connector:{connector.id}:{partition}",
        mode="unknown",
        verified_at=INSTANT,
        expires_at=INSTANT + timedelta(hours=1),
    )
    grant = k.AccessPolicy(
        workspace_id=workspace,
        origin="local_curated",
        scope_key=f"source:{source}:{build_authority.CONNECTOR_SCOPE}",
        mode="workspace",
        verified_at=INSTANT,
    )
    elsewhere = None
    if fault == "other_connector":
        elsewhere = k.Connector(
            workspace_id=workspace,
            kind="jira_cloud",
            instance_url=f"https://other{next(_instances)}.example.com",
        )
        store.put_knowledge(elsewhere)
    originals = []
    for index, (external_id, body) in enumerate(TICKETS.items()):
        owner = elsewhere if elsewhere is not None and index else connector
        artifact = k.Artifact(
            workspace_id=workspace,
            source_id=source,
            connector_id=owner.id,
            provider_instance=owner.instance_url,
            kind="ticket",
            external_id=external_id,
            canonical_uri=f"{owner.instance_url}/browse/{external_id}",
            policy_id=provider.id,
        )
        digest = text_hash(body)
        revision = k.ArtifactRevision(
            artifact_id=artifact.id,
            provider_revision="1",
            content_hash=digest,
            raw_uri="hippo-raw:sha256:" + digest,
            observed_at=INSTANT,
            lifecycle="active",
            metadata_json=canonical_json({"span_policy_id": provider.id}),
        )
        originals.append((artifact, revision))
    profile = embedding()
    configuration = {
        "embedding_profile": profile.descriptor(),
        generation_profiles.GENERATION_PROFILE_KEY: generation_profiles.CONNECTOR_PROFILE,
        "connector": {"kind": connector.kind, "binder": BINDER_RULE, "render": RENDER_RULE},
        "partition": partition,
    }
    payload = {
        "version": 1,
        "source_id": source,
        "workspace_id": workspace,
        "connector_id": connector.id,
        "instance": instance,
        "partition": partition,
        "configuration": configuration,
        "members": [
            {
                "artifact_id": a.id,
                "revision_id": r.id,
                "content_hash": r.content_hash,
                "raw_uri": r.raw_uri,
                "provider_revision": r.provider_revision,
            }
            for a, r in originals
        ],
    }
    if fault == "member_missing":
        payload["members"] = payload["members"][:1]
    manifest_artifact = k.Artifact(
        workspace_id=workspace,
        source_id=source,
        kind="manifest",
        external_id=generation_profiles.CONNECTOR_MANIFEST_EXTERNAL_ID,
        canonical_uri=f"source:{source}/{generation_profiles.CONNECTOR_MANIFEST_EXTERNAL_ID}",
        policy_id=grant.id,
    )
    digest = text_hash(canonical_json(payload))
    manifest_revision = k.ArtifactRevision(
        artifact_id=manifest_artifact.id,
        content_hash=digest,
        raw_uri="hippo-raw:sha256:" + digest,
        observed_at=INSTANT,
        lifecycle="active",
        metadata_json=canonical_json({generation_profiles.CONNECTOR_MANIFEST_KEY: payload}),
    )
    pairs = [(manifest_artifact, manifest_revision), *originals]
    generation = generation_for_inputs(
        pairs,
        workspace_id=workspace,
        source_id=source,
        parent_id=None,
        parser_version="cdk-connector-v1",
        linker_version="cdk-sync-v1",
        embedding_profile=profile.fingerprint,
        configuration=configuration,
        created_at=INSTANT,
        registry_fingerprint=current_registry().fingerprint(),
    )
    return SimpleNamespace(
        store=store,
        source=source,
        workspace=workspace,
        connector=connector,
        instance=instance,
        partition=partition,
        provider=provider,
        grant=grant,
        originals=originals,
        profile=profile,
        configuration=configuration,
        configuration_json=canonical_json(configuration),
        payload=payload,
        manifest_artifact=manifest_artifact,
        manifest_revision=manifest_revision,
        pairs=pairs,
        generation=generation,
    )


# ------------------------------------------------------------------ the emitted records


def sentences(text):
    return [part.strip() + "." for part in text.rstrip(".").split(". ") if part.strip()]


def passage_of(w, span, *, view=None, ordinal=0, vector=(1.0, 0.0)):
    gen = w.generation
    row = {
        "id": generation_passage_id(
            gen.id, span.revision_id, span.id, ordinal, retrieval_view_id=None if view is None else view.id
        ),
        "source_id": gen.source_id,
        "generation_id": gen.id,
        "artifact_revision_id": span.revision_id,
        "span_id": span.id,
        "retrieval_view_id": None if view is None else view.id,
        "embedding_profile": gen.embedding_profile,
        "ordinal": ordinal,
        "title": "",
        "text": span.text if view is None else view.text,
    }
    return writer().StagedPassage(row=row, embedding=vector)


def bundle_of(w, *, vector=(1.0, 0.0)):
    """Everything S3c's `_bind` hands the writer, built by hand for one small generation."""
    module = writer()
    gen = w.generation
    members = tuple(k.GenerationMember(generation_id=gen.id, artifact_revision_id=r.id) for _, r in w.pairs)
    spans, objects, observations = [], [], []
    for index, (artifact, revision) in enumerate(w.originals):
        span = k.EvidenceSpan(
            revision_id=revision.id,
            locator_kind="field",
            locator_json=canonical_json({"kind": "field", "field_path": "description"}),
            text=TICKETS[artifact.external_id],
            policy_id=w.provider.id,
        )
        spans.append(span)
        item = k.KnowledgeObject(
            workspace_id=w.workspace,
            kind="ticket" if index == 0 else "requirement",
            canonical_key=canonical_json([w.instance, artifact.external_id]),
        )
        objects.append(item)
        observations.append(
            k.ObjectObservation(
                object_id=item.id,
                revision_id=revision.id,
                span_id=span.id,
                evidence_class="catalog_observed",
                recorded_from=INSTANT,
                attributes_json=canonical_json({"name": artifact.external_id}),
            )
        )
    dependencies = [("span", spans[0].id, dependency_version(spans[0]))]
    fingerprint = view_fingerprint(
        view_kind="projection",
        text=RENDERED_TEXT,
        text_profile=RENDER_RULE,
        vector_profile=gen.embedding_profile,
        rule_version=RENDER_RULE,
        model_version=None,
        dependencies=dependencies,
    )
    derived = k.DerivedRecord(
        workspace_id=w.workspace,
        view_kind="projection",
        rule_version=RENDER_RULE,
        input_revision_ids=(spans[0].revision_id,),
        dependency_fingerprint=fingerprint,
        state="ready",
    )
    dependency = k.DerivedDependency(
        derived_record_id=derived.id,
        input_kind="span",
        input_id=spans[0].id,
        input_version=dependencies[0][2],
    )
    view = k.RetrievalView(
        span_id=spans[0].id,
        view_kind="projection",
        text=RENDERED_TEXT,
        text_profile=RENDER_RULE,
        vector_profile=gen.embedding_profile,
        source_revision_id=spans[0].revision_id,
        derivation_version=RENDER_RULE,
        dependency_fingerprint=fingerprint,
        derived_record_id=derived.id,
    )
    passages = [passage_of(w, span, vector=vector) for span in spans]
    passages.append(passage_of(w, spans[0], view=view, vector=vector))
    mentions = canonical_json(sorted(item.id for item in objects))
    units = []
    for passage in passages:
        rendered = passage.row["retrieval_view_id"] is not None
        for ordinal, sentence in enumerate(sentences(passage.row["text"])):
            units.append(
                k.Unit(
                    generation_id=gen.id,
                    passage_id=passage.id,
                    span_id=passage.row["span_id"],
                    ordinal=ordinal,
                    kind="rendered_fact" if rendered else "sentence",
                    text=sentence,
                    prefix="" if rendered else "PROJ: ",
                    embed_text=sentence if rendered else "PROJ: " + sentence,
                    mentions_json=mentions,
                    template="ticket.tracks@1" if rendered else None,
                )
            )
    assertion = k.Assertion(
        workspace_id=w.workspace,
        subject_id=objects[0].id,
        predicate="TRACKS",
        object_id=objects[1].id,
        scope_key=f"source:{w.source}:{w.partition}",
    )
    version = k.AssertionVersion(
        assertion_id=assertion.id,
        evidence_class="declared",
        rule_version=BINDER_RULE,
        confidence=1.0,
        status="active",
        recorded_from=INSTANT,
        family="deterministic",
        source="metadata",
        rule="cdk-tracks",
        weight=1.0,
        statement=RENDERED_TEXT,
        unit_id=units[-1].id,
    )
    support = k.AssertionSupport(
        assertion_version_id=version.id, span_id=spans[0].id, derivation_group="cdk-tracks-1"
    )
    scoped = (*spans, *observations, derived, dependency, view, *units, version, support)
    return module.RecordBundle(
        generation=gen,
        configuration_json=w.configuration_json,
        accepted_pairs=tuple(w.pairs),
        manifest_revision=w.manifest_revision,
        revision_members=members,
        spans=tuple(spans),
        objects=tuple(objects),
        observations=tuple(observations),
        views=(view,),
        derived_records=(derived,),
        derived_dependencies=(dependency,),
        passages=tuple(passages),
        units=tuple(units),
        assertions=(assertion,),
        versions=(version,),
        supports=(support,),
        evidence_members=tuple(
            k.GenerationEvidenceMember(
                generation_id=gen.id, record_kind=type(record).__name__, record_id=record.id
            )
            for record in scoped
        ),
    )


def scoped_records(bundle):
    """Every record the bundle's exact evidence membership names, in no particular order."""
    return (
        *bundle.spans,
        *bundle.observations,
        *bundle.views,
        *bundle.derived_records,
        *bundle.derived_dependencies,
        *bundle.units,
        *bundle.versions,
        *bundle.supports,
    )


# ------------------------------------------------------------------ installation and the fence


def install(w, *, job_key="ck3", owner="worker", at=INSTANT):
    """Persist the generation and its accepted inventory, then bind the verified profile."""
    store, gen = w.store, w.generation
    store.put_knowledge(gen)
    store._generation_clock = lambda: at
    job = store.claim_generation_build(
        gen.id, job_key=job_key, lease_owner=owner, lease_expires_at=at + LEASE
    )
    credentials = dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)
    with store.generation_write(gen.id, **credentials):
        for policy in (w.provider, w.grant):
            store.put_knowledge(policy)
        for artifact, revision in w.pairs:
            store.put_knowledge(artifact)
            store.put_knowledge(revision)
            store.put_knowledge(k.GenerationMember(generation_id=gen.id, artifact_revision_id=revision.id))
    store.bind_generation_embedding_profile(gen.id, w.manifest_revision.id, **credentials)
    return job, dict(
        **credentials,
        expected_authorization_epoch=store.authorization_epoch(),
        expected_suppression_epoch=store.suppression_epoch(),
    )


def prepare(store):
    """A whole installed connector generation: the world, its bundle and its live fence."""
    w = world(store)
    bundle = bundle_of(w)
    job, credentials = install(w)
    return SimpleNamespace(store=store, world=w, bundle=bundle, job=job, credentials=credentials)


@pytest.fixture
def built(store):
    return prepare(store)


def write(built, *, check=None, bundle=None, **kwargs):
    def outside():
        assert not getattr(built.store, "_transaction_depth", 0)
        assert getattr(built.store, "_transaction", None) is None
        if check:
            check()

    return writer().write_staged_records(
        built.store, built.bundle if bundle is None else bundle, check=outside, **built.credentials, **kwargs
    )


def fence(built):
    return {key: built.credentials[key] for key in ("job_id", "lease_owner", "fencing_token")}


def reclaim(built, *, key="ck3-resume", owner="resumed"):
    """Expire the holder and take the generation back without collecting its rows."""
    store, gen = built.store, built.bundle.generation
    later = INSTANT + timedelta(minutes=30)
    store._generation_clock = lambda: later
    job = store.reclaim_generation_build(
        gen.id,
        job_key=key,
        lease_owner=owner,
        lease_expires_at=later + LEASE,
        expected_manifest_hash=gen.manifest_hash,
    )
    built.job = job
    built.credentials = dict(
        job_id=job.id,
        lease_owner=job.lease_owner,
        fencing_token=job.fencing_token,
        expected_authorization_epoch=store.authorization_epoch(),
        expected_suppression_epoch=store.suppression_epoch(),
    )
    return job


def unit_of(built, text, *, ordinal):
    """A well-formed unit of this generation's first passage that no bundle ever named."""
    return k.Unit(
        generation_id=built.bundle.generation.id,
        passage_id=built.bundle.passages[0].id,
        span_id=built.bundle.spans[0].id,
        ordinal=ordinal,
        kind="sentence",
        text=text,
        embed_text=text,
        mentions_json="[]",
    )


def rebind(bundle, field, index, **changes):
    """Replace one record of a tuple field and re-derive the evidence member naming it."""
    records = list(getattr(bundle, field))
    old = records[index]
    records[index] = old.replace(**changes)
    kept = [
        member
        for member in bundle.evidence_members
        if (member.record_kind, member.record_id) != (type(old).__name__, old.id)
    ]
    kept.append(
        k.GenerationEvidenceMember(
            generation_id=bundle.generation.id,
            record_kind=type(records[index]).__name__,
            record_id=records[index].id,
        )
    )
    return replace(bundle, **{field: tuple(records)}, evidence_members=tuple(kept))


# ------------------------------------------------------------------ the bundle's closure


def test_record_bundle_refuses_missing_references_and_inexact_membership(store):
    """Closure is checked in `__post_init__`, outside every transaction and before any write."""
    module = writer()
    w = world(store)
    bundle = bundle_of(w)
    absent = k.EvidenceSpan(
        revision_id=bundle.spans[0].revision_id,
        locator_kind="field",
        locator_json=canonical_json({"kind": "field", "field_path": "summary"}),
        text="A span this bundle never carries.",
        policy_id=w.provider.id,
    )
    with pytest.raises(ValueError, match="membership differs from its generation-scoped records"):
        replace(bundle, evidence_members=bundle.evidence_members[:-1])
    with pytest.raises(ValueError, match="references a missing KnowledgeObject"):
        replace(bundle, objects=bundle.objects[:1])
    with pytest.raises(ValueError, match="references a missing EvidenceSpan"):
        rebind(bundle, "supports", 0, span_id=absent.id)
    with pytest.raises(ValueError, match="references a missing Assertion"):
        replace(bundle, assertions=())
    with pytest.raises(ValueError, match="span is outside its revision members"):
        replace(bundle, revision_members=bundle.revision_members[:1])
    elsewhere = dict(bundle.passages[0].row) | {"generation_id": "generation-" + "0" * 64}
    with pytest.raises(ValueError, match="passage belongs to another generation"):
        replace(
            bundle,
            passages=(module.StagedPassage(row=elsewhere, embedding=(1.0, 0.0)), *bundle.passages[1:]),
        )


# ------------------------------------------------------------------ group order and the fence


def test_groups_write_passages_before_units_and_units_before_versions(built, monkeypatch):
    """S1's order is the group order: a `Unit` names a `Passage`, a version names a `Unit`."""
    written = []
    put, add = built.store.put_knowledge, built.store.add_passages
    monkeypatch.setattr(
        built.store,
        "put_knowledge",
        lambda record: (written.append((type(record).__name__, record.id)), put(record))[1],
    )
    monkeypatch.setattr(
        built.store,
        "add_passages",
        lambda rows: (written.extend(("Passage", row["id"]) for row in rows), add(rows))[1],
    )
    write(built, batch_size=64)
    for unit in built.bundle.units:
        assert written.index(("Passage", unit.passage_id)) < written.index(("Unit", unit.id))
    for version in built.bundle.versions:
        assert written.index(("Unit", version.unit_id)) < written.index(("AssertionVersion", version.id))
    for support in built.bundle.supports:
        assert written.index(("AssertionVersion", support.assertion_version_id)) < written.index(
            ("AssertionSupport", support.id)
        )


def test_every_batch_revalidates_the_fence_and_both_epochs(store):
    """Either epoch moving between two batches aborts the write, as `staged_code` does."""
    for epoch in ("authorization", "suppression"):
        built = prepare(store)
        calls = []

        def bump(built=built, epoch=epoch, calls=calls):
            calls.append(epoch)
            if len(calls) != 3:
                return
            if epoch == "authorization":
                built.store.put_knowledge(
                    k.AccessPolicy(
                        workspace_id=built.world.workspace,
                        origin="local_curated",
                        scope_key="source:elsewhere:plain-prose-v1",
                        mode="restricted",
                        allow_users=("nobody",),
                        verified_at=INSTANT,
                    )
                )
            else:
                built.store.put_knowledge(
                    k.Suppression(
                        workspace_id=built.world.workspace,
                        target_kind="policy",
                        target_id=built.world.grant.id,
                        scope_key="test",
                        view_applicability="all_history",
                        reason="access_loss",
                        epoch=1,
                        created_at=INSTANT,
                        restoration_barrier="restore",
                    )
                )

        with pytest.raises(AuthorizationChanged, match="epoch changed during staged writing"):
            write(built, batch_size=1, check=bump)


def test_an_oversized_batch_is_refused_before_its_transaction(built, monkeypatch):
    module = writer()
    monkeypatch.setattr(module, "PAYLOAD_CEILING_BYTES", 32)
    with pytest.raises(ValueError, match="the ceiling is 32"):
        write(built, batch_size=64)
    gen = built.bundle.generation
    assert not built.store._knowledge_rows("GenerationEvidenceMember", generation_id=gen.id)
    assert not built.store._native_rows("Passage", generation_id=gen.id)


def test_a_conflicting_persisted_passage_is_never_overwritten(built):
    """`native_write`'s tolerant equality is never relied on; the canonical payload is compared."""
    module = writer()
    # Written but never sealed: `generation_write` refuses a sealed generation outright, and
    # the point here is the writer's own comparison, not the store's lifecycle guard.
    for batch in module._write_batches(built.bundle, batch_size=64):
        module._write_batch(built.store, built.bundle, batch, **built.credentials)
    conflicting = module.StagedPassage(row=built.bundle.passages[0].row, embedding=(0.5, 0.5))
    changed = replace(built.bundle, passages=(conflicting, *built.bundle.passages[1:]))
    with pytest.raises(ValueError, match="Conflicting staged Passage row"):
        module._write_batch(built.store, changed, (conflicting,), **built.credentials)


# ------------------------------------------------------------------ inventory and seal


def test_the_inventory_is_exact_including_units(built):
    """The seal reads a generation's units by scope (RS1-4), so one extra unit refuses."""
    module = writer()
    gen = built.bundle.generation
    for batch in module._write_batches(built.bundle, batch_size=4):
        module._write_batch(built.store, built.bundle, batch, **built.credentials)
    module._inventory(built.store, built.bundle)
    assert {row.id for row in built.store._knowledge_rows("Unit", generation_id=gen.id)} == {
        unit.id for unit in built.bundle.units
    }
    with built.store.generation_write(gen.id, **fence(built)):
        built.store.put_knowledge(unit_of(built, "One unit more than the bundle named.", ordinal=41))
    with pytest.raises(ValueError, match="Exact Unit inventory differs from prepared coverage"):
        module._inventory(built.store, built.bundle)


def test_the_seal_hashes_units_into_the_evidence_checksum(built):
    """RS1-4: a generation's units and their members are rows of its evidence representation."""
    gen, bundle = built.bundle.generation, built.bundle
    manifest = write(built, batch_size=4)
    assert manifest == built.store.validate_generation_seal(gen.id)
    assert set(manifest.required_representations) == {"evidence", "dense", "native"}
    evidence = next(row for row in manifest.checksums if row.kind == "evidence")
    expected = (
        2 * len(bundle.revision_members)  # each member and the revision it names
        + len(bundle.evidence_members)
        + len(scoped_records(bundle))
        + len(bundle.objects)  # reached through their observations
        + len(bundle.assertions)  # reached through their versions
        + 2  # the derived and embedding capability rows
    )
    assert evidence.row_count == expected
    assert bundle.units and evidence.checksum


# ------------------------------------------------------------------ replay and resume


def test_replaying_every_batch_changes_nothing(built):
    gen = built.bundle.generation
    manifest = write(built, batch_size=3)
    epochs = (built.store.authorization_epoch(), built.store.suppression_epoch(), built.store.content_epoch())
    plan = writer().probe_staged_records(built.store, built.bundle)
    assert plan.group_count > 1 and plan.skipped_groups == plan.group_count - 1
    assert built.store.generation_checksums(gen.id) == manifest.checksums
    assert (
        built.store.authorization_epoch(),
        built.store.suppression_epoch(),
        built.store.content_epoch(),
    ) == epochs


def test_resume_skips_complete_groups_and_writes_absent_ones(built):
    module = writer()
    gen = built.bundle.generation
    batches = list(module._write_batches(built.bundle, batch_size=1))
    for batch in batches[: len(batches) // 2]:
        module._write_batch(built.store, built.bundle, batch, **built.credentials)
    reclaim(built)
    plan = module.probe_staged_records(built.store, built.bundle)
    assert 0 < plan.skipped_groups < plan.group_count
    manifest = write(built, batch_size=4, resume=plan)
    assert manifest == built.store.validate_generation_seal(gen.id)


def test_resume_fails_closed_on_a_partial_group_a_changed_payload_or_an_orphan_row(store):
    module = writer()
    partial = prepare(store)
    # Stop inside the first passage group: its row lands, its units do not.
    for batch in module._write_batches(partial.bundle, batch_size=1):
        passages = tuple(row for row in batch if type(row) is module.StagedPassage)
        module._write_batch(partial.store, partial.bundle, passages or batch, **partial.credentials)
        if passages:
            break
    with pytest.raises(ValueError, match="dependency group is incomplete"):
        module.probe_staged_records(partial.store, partial.bundle)

    changed = prepare(store)
    write(changed, batch_size=4)
    other = module.StagedPassage(row=changed.bundle.passages[0].row, embedding=(0.25, 0.75))
    with pytest.raises(ValueError, match="A staged Passage row differs from this build"):
        module.probe_staged_records(
            changed.store, replace(changed.bundle, passages=(other, *changed.bundle.passages[1:]))
        )

    orphaned = prepare(store)
    # Written but never sealed: `_admit_build` reclaims a staging generation, not a ready one.
    for batch in module._write_batches(orphaned.bundle, batch_size=4):
        module._write_batch(orphaned.store, orphaned.bundle, batch, **orphaned.credentials)
    with orphaned.store.generation_write(orphaned.bundle.generation.id, **fence(orphaned)):
        orphaned.store.put_knowledge(unit_of(orphaned, "An orphan unit no bundle would produce.", ordinal=97))
    with pytest.raises(ValueError, match="this build would not produce"):
        module.probe_staged_records(orphaned.store, orphaned.bundle)


# ------------------------------------------------------------------ the public wrapper


def test_the_public_wrapper_refuses_an_ambient_transaction_and_checks_between_batches(built):
    module = writer()
    with built.store.transaction():
        with pytest.raises(ValueError, match="requires no outer transaction"):
            module.write_staged_records(built.store, built.bundle, check=lambda: None, **built.credentials)
    calls = []
    batches = len(list(module._write_batches(built.bundle, batch_size=1)))
    write(built, batch_size=1, check=lambda: calls.append(1))
    assert len(calls) == 2 * batches + 2


def test_staged_records_imports_nothing_from_connectors():
    """`knowledge` never depends on `connectors`, and the shared core keeps public names (m10)."""
    module = writer()
    from hippo.knowledge import staged_code

    source = Path(module.__file__).read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if line.lstrip().startswith(("import ", "from "))]
    assert imports and not [line for line in imports if "connectors" in line]
    assert not [name for name in sys.modules if name.startswith("hippo.connectors")]
    assert module.CLEANUP is staged_code.CLEANUP
    assert module.ResumePlan is staged_code.ResumePlan
    assert (staged_code.fenced_epochs, staged_code.fenced_local) == (staged_code._epochs, staged_code._local)
    assert (staged_code.DependencyGroup, staged_code.immutable_native) == (
        staged_code._Group,
        staged_code._immutable_native,
    )


@ladybug_only
def test_a_sealed_connector_generation_survives_ladybug_close_and_reopen(tmp_path):
    from hippo.store.ladybug import LadybugStore

    path = tmp_path.resolve() / "connector.lbug"
    store = LadybugStore(path)
    try:
        built = prepare(store)
        manifest = write(built, batch_size=4)
        gen_id = built.bundle.generation.id
        expected = {unit.id for unit in built.bundle.units}
    finally:
        store.close()
    reopened = LadybugStore(path)
    try:
        assert reopened.validate_generation_seal(gen_id) == manifest
        assert reopened.generation_checksums(gen_id) == manifest.checksums
        assert {row.id for row in reopened._knowledge_rows("Unit", generation_id=gen_id)} == expected
        assert (
            generation_profiles.validate_generation_profile(
                reopened, reopened._generation(gen_id)
            ).profile.fingerprint
            == built.world.profile.fingerprint
        )
        assert writer().probe_staged_records(reopened, built.bundle).skipped_groups
    finally:
        reopened.close()
