"""Pure bitemporal selector and evidence-clock behavior."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from hippo.access import EVERYTHING, Access
from hippo.knowledge import model as k
from hippo.knowledge import snapshots as snapshot_service
from hippo.knowledge.access import AuthorizationChanged, EvidenceAccess
from hippo.knowledge.temporal import (
    RecordedSegment,
    ResolvedTemporalSelector,
    TemporalInputs,
    TemporalPublicationPlan,
    history_access,
    match_temporal,
    resolve_selector,
    select_history,
    serialize_temporal_evidence,
)
from hippo.store.snapshots import PurgedEvidence, SnapshotUnavailable
from tests.unit.test_store_knowledge import reader

MAY_1 = datetime(2026, 5, 1, tzinfo=UTC)
MAY_5 = datetime(2026, 5, 5, 12, tzinfo=UTC)
MAY_6 = datetime(2026, 5, 6, 12, tzinfo=UTC)
MAY_10 = datetime(2026, 5, 10, tzinfo=UTC)
MAY_12 = datetime(2026, 5, 12, tzinfo=UTC)


def version(
    *,
    recorded_from=MAY_1,
    recorded_to=None,
    valid_from=MAY_1,
    valid_to=None,
    validity_kind="explicit_interval",
    temporal_precision="instant",
    source_timestamp_original=None,
    source_timezone=None,
):
    basis = {
        "explicit_interval": "source_explicit",
        "observed_snapshot": "provider_snapshot",
        "atemporal": "atemporal",
        "unknown": "unknown",
    }[validity_kind]
    return k.AssertionVersion(
        assertion_id="assertion-a",
        evidence_class="declared",
        rule_version="fixture-v1",
        confidence=1.0,
        status="active",
        valid_from=valid_from,
        valid_to=valid_to,
        validity_kind=validity_kind,
        recorded_from=recorded_from,
        recorded_to=recorded_to,
        temporal_basis=basis,
        temporal_precision=temporal_precision,
        source_timestamp_original=source_timestamp_original,
        source_timezone=source_timezone,
    )


def resolved(selector, *, latest=MAY_12):
    result = resolve_selector(selector, latest_known_at=latest)
    assert isinstance(result, ResolvedTemporalSelector)
    return result


def test_resolve_selector_commits_one_utc_cutoff_and_tracks_its_origin():
    injected = resolved(k.AsOfSelector(valid_at=MAY_5))
    explicit = resolved(k.AsOfSelector(valid_at=MAY_5, known_at=MAY_6))

    assert injected.known_at == MAY_12
    assert injected.known_at_source == "latest"
    assert '"resolved_known_at":"2026-05-12T00:00:00Z"' in injected.selector_json
    assert '"known_at"' not in injected.selector_json
    assert explicit.known_at == MAY_6
    assert explicit.known_at_source == "explicit"
    assert '"resolved_known_at":"2026-05-06T12:00:00Z"' in explicit.selector_json


def test_resolved_selector_derives_its_canonical_identity_instead_of_accepting_one():
    selector = k.AsOfSelector(valid_at=MAY_5, known_at=MAY_6)
    canonical = resolved(selector)

    direct = ResolvedTemporalSelector(selector, MAY_6, "explicit", MAY_12)

    assert direct.selector_json == canonical.selector_json
    assert '"resolved_known_at":"2026-05-06T12:00:00Z"' in direct.selector_json
    assert direct.latest_known_at == MAY_12


def test_resolved_selector_rejects_forged_origins_and_cutoffs_beyond_available_knowledge():
    selector = k.AsOfSelector(valid_at=MAY_5, known_at=MAY_6)

    with pytest.raises(ValueError, match="origin contradicts"):
        ResolvedTemporalSelector(selector, MAY_6, "latest", MAY_12)
    with pytest.raises(ValueError, match="differs"):
        ResolvedTemporalSelector(selector, MAY_10, "explicit", MAY_12)
    with pytest.raises(ValueError, match="requires a selector cutoff"):
        ResolvedTemporalSelector(k.CurrentSelector(), MAY_12, "explicit", MAY_12)
    with pytest.raises(ValueError, match="after latest"):
        ResolvedTemporalSelector(k.CurrentSelector(), datetime(2099, 1, 1, tzinfo=UTC), "latest", MAY_12)
    with pytest.raises(TypeError, match="must be a datetime"):
        ResolvedTemporalSelector(k.CurrentSelector(), "2026-05-12T00:00:00Z", "latest", MAY_12)


def test_resolve_selector_normalizes_aware_values_and_rejects_naive_cutoff():
    phoenix = timezone(timedelta(hours=-7))
    result = resolved(k.AsOfSelector(valid_at=MAY_5.astimezone(phoenix)), latest=MAY_12.astimezone(phoenix))

    assert result.selector.valid_at == MAY_5
    assert result.known_at == MAY_12
    with pytest.raises(ValueError, match="timezone aware"):
        resolve_selector(k.CurrentSelector(), latest_known_at=datetime(2026, 5, 12))


def test_resolve_selector_rejects_a_knowledge_cutoff_beyond_the_request_cutoff():
    with pytest.raises(ValueError, match="after latest"):
        resolve_selector(k.AsOfSelector(valid_at=MAY_5, known_at=MAY_12), latest_known_at=MAY_10)


def test_compare_resolves_each_side_without_merging_their_snapshots():
    result = resolve_selector(
        k.CompareSelector(
            left=k.AsOfSelector(valid_at=MAY_1, snapshot_id="left-snapshot"),
            right=k.AsOfSelector(valid_at=MAY_5, known_at=MAY_10, snapshot_id="right-snapshot"),
        ),
        latest_known_at=MAY_12,
    )

    assert isinstance(result, tuple)
    assert [item.known_at for item in result] == [MAY_12, MAY_10]
    assert [item.selector.snapshot_id for item in result] == ["left-snapshot", "right-snapshot"]


def test_compare_labels_an_inherited_cutoff_without_claiming_the_side_pinned_it():
    left, right = resolve_selector(
        k.CompareSelector(
            known_at=MAY_10,
            left=k.CurrentSelector(),
            right=k.AsOfSelector(valid_at=MAY_5, known_at=MAY_10),
        ),
        latest_known_at=MAY_12,
    )

    assert (left.known_at, left.known_at_source) == (MAY_10, "inherited")
    assert (right.known_at, right.known_at_source) == (MAY_10, "explicit")
    assert (left.latest_known_at, right.latest_known_at) == (MAY_12, MAY_12)


def test_as_of_uses_recorded_and_effective_half_open_intervals():
    row = version(recorded_from=MAY_1, recorded_to=MAY_10, valid_from=MAY_1, valid_to=MAY_10)

    assert (
        match_temporal(
            TemporalInputs(row), resolved(k.AsOfSelector(valid_at=MAY_5), latest=MAY_6)
        ).disposition
        == "proven"
    )
    assert (
        match_temporal(TemporalInputs(row), resolved(k.AsOfSelector(valid_at=MAY_10), latest=MAY_6)).reason
        == "effective_outside"
    )
    assert (
        match_temporal(TemporalInputs(row), resolved(k.AsOfSelector(valid_at=MAY_5), latest=MAY_10)).reason
        == "recorded_closed"
    )
    assert (
        match_temporal(
            TemporalInputs(row), resolved(k.AsOfSelector(valid_at=MAY_5), latest=MAY_1 - timedelta(seconds=1))
        ).reason
        == "recorded_after_cutoff"
    )


def test_as_of_unknown_and_snapshot_time_are_contextual_not_proven():
    unknown = version(valid_from=None, validity_kind="unknown", temporal_precision="unknown")
    snapshot = version(
        valid_from=None,
        validity_kind="observed_snapshot",
        temporal_precision="instant",
    )

    assert (
        match_temporal(TemporalInputs(unknown), resolved(k.AsOfSelector(valid_at=MAY_5))).disposition
        == "contextual"
    )
    assert (
        match_temporal(TemporalInputs(snapshot), resolved(k.AsOfSelector(valid_at=MAY_5))).reason
        == "effective_unknown"
    )


def test_explicit_unknown_lower_bound_never_means_negative_infinity():
    row = version(valid_from=None, valid_to=MAY_10)

    point = match_temporal(TemporalInputs(row), resolved(k.AsOfSelector(valid_at=MAY_5)))
    during = match_temporal(
        TemporalInputs(row),
        resolved(
            k.DuringSelector(
                valid_during=k.TimeInterval(start=MAY_1, end=MAY_10),
                interval_predicate="overlaps",
            )
        ),
    )

    assert point.disposition == during.disposition == "contextual"
    assert point.reason == during.reason == "effective_unknown"


def test_during_distinguishes_overlap_from_throughout_and_supports_open_upper_bound():
    row = version(valid_from=MAY_1, valid_to=MAY_10)
    window = k.TimeInterval(start=MAY_5, end=MAY_12)

    overlap = match_temporal(
        TemporalInputs(row),
        resolved(k.DuringSelector(valid_during=window, interval_predicate="overlaps")),
    )
    throughout = match_temporal(
        TemporalInputs(row),
        resolved(k.DuringSelector(valid_during=window, interval_predicate="throughout")),
    )
    open_row = match_temporal(
        TemporalInputs(version(valid_from=MAY_1)),
        resolved(k.DuringSelector(valid_during=window, interval_predicate="throughout")),
    )

    assert overlap.disposition == "proven"
    assert throughout.reason == "effective_outside"
    assert open_row.disposition == "proven"


def test_coarser_than_instant_effective_bounds_are_never_proven_by_point_or_interval_predicates():
    year = version(
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        temporal_precision="year",
        source_timestamp_original="2026",
        source_timezone="UTC",
    )
    march = datetime(2026, 3, 1, tzinfo=UTC)
    window = k.TimeInterval(start=datetime(2026, 2, 1, tzinfo=UTC), end=march)

    point = match_temporal(TemporalInputs(year), resolved(k.AsOfSelector(valid_at=march)))
    throughout = match_temporal(
        TemporalInputs(year),
        resolved(k.DuringSelector(valid_during=window, interval_predicate="throughout")),
    )
    overlaps = match_temporal(
        TemporalInputs(year),
        resolved(k.DuringSelector(valid_during=window, interval_predicate="overlaps")),
    )
    day = match_temporal(
        TemporalInputs(version(temporal_precision="day")), resolved(k.CurrentSelector(), latest=MAY_5)
    )

    assert [item.disposition for item in (point, throughout, overlaps, day)] == ["contextual"] * 4
    assert {item.reason for item in (point, throughout, overlaps, day)} == {"effective_imprecise"}
    assert point.valid_at == march
    assert throughout.valid_during == window


def test_current_uses_request_cutoff_but_keeps_unknown_time_contextual():
    active = match_temporal(TemporalInputs(version()), resolved(k.CurrentSelector(), latest=MAY_5))
    future = match_temporal(
        TemporalInputs(version(valid_from=MAY_10)), resolved(k.CurrentSelector(), latest=MAY_5)
    )
    unknown = match_temporal(
        TemporalInputs(version(valid_from=None, validity_kind="unknown", temporal_precision="unknown")),
        resolved(k.CurrentSelector(), latest=MAY_5),
    )

    assert active.disposition == "proven"
    assert future.reason == "effective_outside"
    assert unknown.disposition == "contextual"


def test_atemporal_proves_only_atemporal_claims():
    atemporal = version(
        valid_from=None,
        validity_kind="atemporal",
        temporal_precision="unknown",
    )
    explicit = version()

    assert (
        match_temporal(TemporalInputs(atemporal), resolved(k.AtemporalSelector())).reason == "atemporal_match"
    )
    assert (
        match_temporal(TemporalInputs(explicit), resolved(k.AtemporalSelector())).reason
        == "effective_outside"
    )
    assert (
        match_temporal(TemporalInputs(atemporal), resolved(k.AsOfSelector(valid_at=MAY_5))).reason
        == "atemporal_match"
    )


@pytest.mark.parametrize(
    ("clock", "inputs", "expected"),
    [
        ("published", lambda row: TemporalInputs(row, published_at=MAY_10), "proven"),
        (
            "source_modified",
            lambda row: TemporalInputs(row, source_updated_at=MAY_10, source_precision="instant"),
            "proven",
        ),
        ("effective", lambda row: TemporalInputs(row), "proven"),
        ("source_modified", lambda row: TemporalInputs(row), "contextual"),
    ],
)
def test_changes_uses_only_the_selected_clock(clock, inputs, expected):
    row = version(valid_from=MAY_10)
    selector = k.ChangesSelector(
        changes_since=MAY_10,
        changes_until=MAY_12,
        change_clock=clock,
    )

    assert match_temporal(inputs(row), resolved(selector)).disposition == expected


def test_published_change_does_not_silently_substitute_recorded_time():
    row = version(recorded_from=MAY_10)
    selector = resolved(
        k.ChangesSelector(
            changes_since=MAY_10,
            changes_until=MAY_12,
            change_clock="published",
        )
    )

    assert match_temporal(TemporalInputs(row), selector).reason == "change_clock_unknown"
    assert (
        match_temporal(TemporalInputs(row, recorded_from_is_publication=True), selector).disposition
        == "proven"
    )
    with pytest.raises(ValueError, match="differs from recorded"):
        TemporalInputs(
            row,
            published_at=MAY_12,
            recorded_from_is_publication=True,
        )


def test_imprecise_change_clock_is_contextual_even_when_its_bound_is_in_range():
    row = version(valid_from=MAY_10, temporal_precision="day")
    selector = resolved(
        k.ChangesSelector(
            changes_since=MAY_10,
            changes_until=MAY_12,
            change_clock="effective",
        )
    )

    assert match_temporal(TemporalInputs(row), selector).reason == "change_clock_unknown"


def test_temporal_serialization_keeps_every_clock_and_original_precision():
    row = version(
        recorded_from=MAY_10,
        valid_from=MAY_1,
        valid_to=None,
        temporal_precision="day",
        source_timestamp_original="2026-05-01 America/Phoenix",
        source_timezone="America/Phoenix",
    )
    payload = serialize_temporal_evidence(
        TemporalInputs(
            row,
            source_updated_at=MAY_1,
            observed_at=MAY_6,
            published_at=MAY_10,
            source_precision="day",
        )
    )

    assert payload == {
        "record_id": row.id,
        "validity_kind": "explicit_interval",
        "temporal_basis": "source_explicit",
        "temporal_precision": "day",
        "source_timestamp_original": "2026-05-01 America/Phoenix",
        "source_timezone": "America/Phoenix",
        "valid_from": "2026-05-01T00:00:00Z",
        "valid_to": None,
        "recorded_from": "2026-05-10T00:00:00Z",
        "recorded_to": None,
        "source_updated_at": "2026-05-01T00:00:00Z",
        "source_precision": "day",
        "observed_at": "2026-05-06T12:00:00Z",
        "published_at": "2026-05-10T00:00:00Z",
    }


def test_model_rejects_empty_effective_and_recorded_intervals():
    with pytest.raises(ValueError, match="Effective interval"):
        version(valid_from=MAY_1, valid_to=MAY_1)
    with pytest.raises(ValueError, match="Recorded interval"):
        version(recorded_from=MAY_1, recorded_to=MAY_1)


def test_resolved_selector_rejects_origin_labels_its_own_data_contradicts():
    """N1: `latest` must match the injected cutoff and `inherited` needs its parent."""
    parent = k.CompareSelector(
        known_at=MAY_10, left=k.CurrentSelector(), right=k.AsOfSelector(valid_at=MAY_5)
    )
    inherited = ResolvedTemporalSelector(k.CurrentSelector(), MAY_10, "inherited", MAY_12, parent)

    assert inherited.known_at_source == "inherited"
    with pytest.raises(ValueError, match="latest knowledge cutoff"):
        ResolvedTemporalSelector(k.CurrentSelector(), MAY_10, "latest", MAY_12)
    with pytest.raises(ValueError, match="comparison parent"):
        ResolvedTemporalSelector(k.CurrentSelector(), MAY_10, "inherited", MAY_12)
    with pytest.raises(ValueError, match="comparison parent"):
        ResolvedTemporalSelector(k.CurrentSelector(), MAY_12, "latest", MAY_12, parent)
    with pytest.raises(ValueError, match="comparison parent"):
        ResolvedTemporalSelector(k.AsOfSelector(valid_at=MAY_1), MAY_10, "inherited", MAY_12, parent)


# --- Section 4: authorized history selection, manifests and snapshot pinning ---


def _publish_window(store, at=MAY_12):
    store._generation_clock = lambda: at


def _credentials(job):
    return dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)


def _generation(store, source, key, parent=None, *, at=MAY_12):
    row = k.Generation(
        source_id=source,
        parent_id=parent.id if parent else None,
        status="staging",
        parser_version="1",
        linker_version="1",
        embedding_profile="p",
        created_at=MAY_1,
        manifest_hash=key,
    )
    store.put_knowledge(row)
    _publish_window(store, at)
    return row


def _claim(store, gen, *, at=MAY_12):
    return store.claim_generation_build(
        gen.id,
        job_key=gen.manifest_hash,
        lease_owner="worker",
        lease_expires_at=at + timedelta(minutes=5),
    )


def _seal(store, gen, job):
    store.seal_generation(
        gen.id,
        k.IndexManifest(
            generation_id=gen.id,
            profile_fingerprint="p",
            config_fingerprint="c",
            required_representations=("evidence", "dense", "native"),
            checksums=store.generation_checksums(gen.id),
            ready=True,
        ),
        **_credentials(job),
    )


def _publish_only(store, gen, job, *, at=MAY_12, plan=None, fault_hook=None):
    return store.publish_staged_generation(
        gen.id,
        expected_parent_id=gen.parent_id,
        expected_suppression_epoch=store.suppression_epoch(),
        published_at=at,
        plan=plan,
        fault_hook=fault_hook,
        **_credentials(job),
    )


def _publish(store, gen, job, *, at=MAY_12, plan=None, fault_hook=None):
    _seal(store, gen, job)
    return _publish_only(store, gen, job, at=at, plan=plan, fault_hook=fault_hook)


def _revision(store, artifact, text, observed_at):
    row = k.ArtifactRevision(
        artifact_id=artifact.id,
        content_hash=text,
        raw_uri="blob:" + text,
        observed_at=observed_at,
        lifecycle="active",
    )
    store.put_knowledge(row)
    return row


def _span(store, revision, name, policy):
    row = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="field",
        locator_json='{"kind":"field","field_path":"' + name + '"}',
        text=name,
        policy_id=policy.id,
    )
    store.put_knowledge(row)
    return row


def _object(store, workspace, kind, name):
    row = k.KnowledgeObject(workspace_id=workspace, kind=kind, canonical_key='["' + name + '"]')
    store.put_knowledge(row)
    return row


def _observation(store, obj, span, recorded_from, *, valid_from=None, validity_kind="explicit_interval"):
    explicit = validity_kind == "explicit_interval"
    row = k.ObjectObservation(
        object_id=obj.id,
        revision_id=span.revision_id,
        span_id=span.id,
        evidence_class="declared",
        recorded_from=recorded_from,
        valid_from=valid_from if explicit else None,
        validity_kind=validity_kind,
        temporal_basis="source_explicit" if explicit else "unknown",
        temporal_precision="instant" if explicit else "unknown",
    )
    store.put_knowledge(row)
    return row


def _version(store, assertion, recorded_from, valid_from):
    row = k.AssertionVersion(
        assertion_id=assertion.id,
        evidence_class="declared",
        rule_version="fixture-v1",
        confidence=1.0,
        status="active",
        recorded_from=recorded_from,
        valid_from=valid_from,
        validity_kind="explicit_interval",
        temporal_basis="source_explicit",
        temporal_precision="instant",
    )
    store.put_knowledge(row)
    return row


def history_world(store):
    """May-1 ownership, retired on May-10 by a correction in a second generation."""
    source = store.create_source("text", "owners")
    workspace = store.get_source(source)["workspace_id"]
    if store._knowledge_get("Workspace", workspace) is None:
        store.put_knowledge(k.Workspace(name="default"))
    assert store._knowledge_get("Workspace", workspace) is not None
    public = k.AccessPolicy(
        workspace_id=workspace,
        origin="local_curated",
        scope_key="source:" + source,
        mode="workspace",
        verified_at=MAY_1,
    )
    private = k.AccessPolicy(
        workspace_id=workspace,
        origin="local_curated",
        scope_key="source:" + source + "/private",
        mode="restricted",
        allow_users=("keeper",),
        verified_at=MAY_1,
    )
    store.put_knowledge(public)
    store.put_knowledge(private)
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=source,
        kind="file",
        external_id="owners.md",
        canonical_uri="source:owners.md",
        policy_id=public.id,
    )
    store.put_knowledge(artifact)

    first = _generation(store, source, "gen-one")
    job = _claim(store, first)
    with store.generation_write(first.id, **_credentials(job)):
        revision_one = _revision(store, artifact, "may-1", MAY_1)
        store.put_knowledge(k.GenerationMember(generation_id=first.id, artifact_revision_id=revision_one.id))
        span_one = _span(store, revision_one, "owners-may-1", public)
        secret_span = _span(store, revision_one, "owners-private", private)
        service = _object(store, workspace, "service", "checkout")
        ada = _object(store, workspace, "person", "ada")
        vault = _object(store, workspace, "service", "vault")
        legacy = _object(store, workspace, "service", "legacy")
        _observation(store, service, span_one, MAY_1, valid_from=MAY_1)
        _observation(store, ada, span_one, MAY_1, valid_from=MAY_1)
        secret = _observation(store, vault, secret_span, MAY_1, valid_from=MAY_1)
        undated = _observation(store, legacy, span_one, MAY_1, validity_kind="unknown")
        owned_by_ada = k.checked_assertion(service, "OWNED_BY", ada, scope_key="prod")
        store.put_knowledge(owned_by_ada)
        version_one = _version(store, owned_by_ada, MAY_1, MAY_1)
        store.put_knowledge(
            k.AssertionSupport(
                assertion_version_id=version_one.id, span_id=span_one.id, derivation_group="direct"
            )
        )
    _publish(store, first, job)

    second = _generation(store, source, "gen-two", first)
    job = _claim(store, second)
    with store.generation_write(second.id, **_credentials(job)):
        revision_two = _revision(store, artifact, "may-10", MAY_10)
        store.put_knowledge(k.GenerationMember(generation_id=second.id, artifact_revision_id=revision_two.id))
        span_two = _span(store, revision_two, "owners-may-10", public)
        bo = _object(store, workspace, "person", "bo")
        _observation(store, service, span_two, MAY_10, valid_from=MAY_10)
        _observation(store, bo, span_two, MAY_10, valid_from=MAY_10)
        owned_by_bo = k.checked_assertion(service, "OWNED_BY", bo, scope_key="prod")
        store.put_knowledge(owned_by_bo)
        version_two = _version(store, owned_by_bo, MAY_10, MAY_10)
        store.put_knowledge(
            k.AssertionSupport(
                assertion_version_id=version_two.id, span_id=span_two.id, derivation_group="direct"
            )
        )
        version_one = store.update_knowledge(version_one.replace(recorded_to=MAY_10))
        version_one = store._knowledge_get("AssertionVersion", version_one)
    _publish(store, second, job)

    return SimpleNamespace(
        store=store,
        source=source,
        workspace=workspace,
        public=public,
        private=private,
        artifact=artifact,
        first=first,
        second=second,
        revision_one=revision_one,
        revision_two=revision_two,
        span_one=span_one,
        secret_span=secret_span,
        secret=secret,
        undated=undated,
        version_one=version_one,
        version_two=version_two,
    )


def select(world, *, valid_at=MAY_5, known_at=MAY_5, access=EVERYTHING, selector=None):
    return select_history(
        world.store,
        workspace_id=world.workspace,
        access=access,
        selector=selector or k.AsOfSelector(valid_at=valid_at, known_at=known_at),
        request_cutoff=MAY_12,
        clock=lambda: MAY_12,
    )


def test_history_manifest_selects_retired_evidence_at_a_fixed_knowledge_cutoff(store):
    world = history_world(store)

    old = select(world)
    now = select(world, valid_at=MAY_12, known_at=MAY_12)

    assert old.manifest.assertion_version_ids == (world.version_one.id,)
    assert old.manifest.revision_ids == (world.revision_one.id,)
    assert old.manifest.knowledge_cutoff == MAY_5
    assert '"known_at":"2026-05-05T12:00:00Z"' in old.manifest.temporal_selector_json
    assert now.manifest.assertion_version_ids == (world.version_two.id,)
    # Only the ownership assertion was corrected: the May-1 object observations
    # are still recorded-open, so their revision stays beside the correction's.
    assert now.manifest.revision_ids == tuple(sorted((world.revision_one.id, world.revision_two.id)))
    assert store._knowledge_get("HistoryManifest", old.manifest.id) == old.manifest


def test_history_manifest_rejects_a_compare_selector_and_asks_for_one_manifest_per_side(store):
    """Compare is rejected in part 1, even with two independently pinned sides.

    Each side is its own historical question with its own authorization proof,
    so the remedy is one manifest per side, which the error names explicitly.
    """
    world = history_world(store)
    compare = k.CompareSelector(
        left=k.AsOfSelector(valid_at=MAY_1, known_at=MAY_5),
        right=k.AsOfSelector(valid_at=MAY_10, known_at=MAY_12),
    )

    with pytest.raises(ValueError, match="one independently pinned manifest per side"):
        select(world, selector=compare)


def test_history_manifest_keeps_current_policy_mandatory(store):
    world = history_world(store)
    principal = reader(store, world.workspace, "bystander")

    internal = select(world)
    audience = select(world, access=Access(user_id=principal))

    assert world.secret.id in {item.record_id for item in internal.decisions}
    assert world.secret.id not in {item.record_id for item in audience.decisions}
    assert audience.manifest.assertion_version_ids == (world.version_one.id,)


def test_history_manifest_separates_contextual_inventory_from_proven_evidence(store):
    world = history_world(store)

    old = select(world)

    contextual = {item.record_id: item for item in old.contextual}
    assert world.undated.id in contextual
    assert contextual[world.undated.id].match.reason == "effective_unknown"
    assert contextual[world.undated.id].recorded_reason == "recorded_match"
    assert world.undated.id not in {item.record_id for item in old.proven}
    assert old.coverage["contextual"]["observations"] >= 1
    assert old.coverage["proven"]["assertion_versions"] == 1


def test_history_manifest_never_adds_an_id_outside_the_authorization_proof(store):
    world = history_world(store)

    old = select(world)

    assert set(old.manifest.revision_ids) <= set(old.broad.revision_ids)
    assert set(old.manifest.assertion_version_ids) <= set(old.broad.assertion_version_ids)
    assert set(old.proof.revision_ids) <= set(old.broad.revision_ids)
    assert world.revision_two.id not in old.manifest.revision_ids
    assert {item.record_id for item in old.decisions} <= (
        set(old.broad.observation_ids) | set(old.broad.assertion_version_ids)
    )


def test_history_manifest_reports_history_unavailable_before_the_earliest_interval(store):
    world = history_world(store)
    before = datetime(2026, 4, 28, tzinfo=UTC)

    empty = select(world, valid_at=before, known_at=before)

    assert empty.codes == ("history_unavailable",)
    assert empty.manifest.revision_ids == ()
    assert empty.manifest.assertion_version_ids == ()
    assert empty.proof.span_ids == frozenset()


def test_history_manifest_records_a_retention_gap_without_fabricating_revisions(store):
    world = history_world(store)
    assert store.collect_generation(world.first.id).blocked_reason is None

    old = select(world)

    assert old.manifest.retention_gaps == (world.revision_one.id,)
    assert "retention_gap" in old.codes
    assert world.revision_one.id in old.manifest.revision_ids


def test_history_manifest_includes_only_compatible_link_generations(store):
    world = history_world(store)
    compatible = k.LinkGeneration(
        workspace_id=world.workspace,
        input_manifest_hash="retained",
        linker_version="l",
        assertion_version_ids=(world.version_one.id,),
        created_at=MAY_1,
    )
    straddling = k.LinkGeneration(
        workspace_id=world.workspace,
        input_manifest_hash="straddling",
        linker_version="l",
        assertion_version_ids=tuple(sorted((world.version_one.id, world.version_two.id))),
        created_at=MAY_10,
    )
    store.put_knowledge(compatible)
    store.put_knowledge(straddling)

    old = select(world)

    assert old.manifest.link_generation_ids == (compatible.id,)
    assert "link_coverage_incomplete" in old.codes


def test_history_manifest_pins_a_query_snapshot_and_releases_its_reference(store):
    world = history_world(store)
    old = select(world)

    bundle = snapshot_service.acquire_history_snapshot(
        store, EVERYTHING, history=old, settings_fingerprint="settings", clock=lambda: MAY_12
    )
    with bundle:
        snapshot = bundle.snapshots[0]
        assert snapshot.history_manifest_ids == (old.manifest.id,)
        assert snapshot.sources == ()
        assert snapshot.knowledge_cutoff == MAY_5
        assert snapshot.temporal.known_at == MAY_5
        bundle.validate()
    assert all(ref.released_at is not None for ref in store._knowledge_rows("SnapshotReference"))


def test_suppression_history_keeps_a_current_only_tombstone_selectable(store):
    world = history_world(store)
    store.put_knowledge(
        k.Suppression(
            workspace_id=world.workspace,
            target_kind="source",
            target_id=world.source,
            scope_key="source:" + world.source + ":delete",
            view_applicability="current_only",
            reason="tombstone",
            epoch=1,
            created_at=MAY_12,
            restoration_barrier="refetch",
        )
    )

    old = select(world)

    assert old.manifest.assertion_version_ids == (world.version_one.id,)
    assert old.resolver.build().span_ids == frozenset()


def test_suppression_history_denies_an_old_snapshot_after_all_history_access_loss(store):
    world = history_world(store)
    old = select(world)
    bundle = snapshot_service.acquire_history_snapshot(
        store, EVERYTHING, history=old, settings_fingerprint="settings", clock=lambda: MAY_12
    )
    try:
        bundle.validate()
        store.put_knowledge(
            k.Suppression(
                workspace_id=world.workspace,
                target_kind="artifact",
                target_id=world.artifact.id,
                scope_key="source:" + world.source,
                view_applicability="all_history",
                reason="access_loss",
                epoch=2,
                created_at=MAY_12,
                restoration_barrier="reverify",
            )
        )
        with pytest.raises(AuthorizationChanged):
            bundle.validate()
    finally:
        bundle.close()


def test_purge_history_overrides_retained_snapshot_roots(store):
    world = history_world(store)
    old = select(world)
    bundle = snapshot_service.acquire_history_snapshot(
        store, EVERYTHING, history=old, settings_fingerprint="settings", clock=lambda: MAY_12
    )
    try:
        assert store.collect_generation(world.first.id).blocked_reason == "snapshot_reference"
        store.put_knowledge(
            k.Suppression(
                workspace_id=world.workspace,
                target_kind="revision",
                target_id=world.revision_one.id,
                scope_key="source:" + world.source,
                view_applicability="all_history",
                reason="purge",
                epoch=3,
                created_at=MAY_12,
                restoration_barrier="destroy",
            )
        )
        assert store.collect_generation(world.first.id).blocked_reason is None
        markers = store.purged_history_evidence(
            old.manifest.id, workspace_id=world.workspace, access=EVERYTHING
        )
        assert [(item.target_kind, item.target_id, item.code) for item in markers] == [
            ("revision", world.revision_one.id, "evidence_purged")
        ]
        assert not any(hasattr(item, "text") for item in markers)
        with pytest.raises(AuthorizationChanged):
            bundle.validate()
    finally:
        bundle.close()


def _suppress(
    world, *, target_kind, target_id, reason, epoch, applicability="all_history", barrier="reverify"
):
    world.store.put_knowledge(
        k.Suppression(
            workspace_id=world.workspace,
            target_kind=target_kind,
            target_id=target_id,
            scope_key="source:" + world.source,
            view_applicability=applicability,
            reason=reason,
            epoch=epoch,
            created_at=MAY_12,
            restoration_barrier=barrier,
        )
    )


def test_history_manifest_is_written_inside_the_transaction_that_read_it(store, monkeypatch):
    """The proof, the closure and the persisted manifest are one atomic decision."""
    world = history_world(store)
    ambient = []
    original = type(store).put_knowledge

    def watched(self, record, *args, **kwargs):
        if isinstance(record, k.HistoryManifest):
            ambient.append(self.in_ambient_transaction())
        return original(self, record, *args, **kwargs)

    monkeypatch.setattr(type(store), "put_knowledge", watched)

    select(world)

    assert ambient == [True]


def test_history_manifest_is_never_persisted_outside_its_final_proof(store, monkeypatch):
    """Containment runs on the manifest before the write, not on the proof after it."""
    world = history_world(store)
    original = EvidenceAccess.build

    def narrowed(self, selection=None):
        proof = original(self, selection)
        if selection is not None and selection.revision_ids:
            return replace(proof, revision_ids=frozenset())
        return proof

    monkeypatch.setattr(EvidenceAccess, "build", narrowed)

    with pytest.raises(AuthorizationChanged):
        select(world)

    assert store._knowledge_rows("HistoryManifest") == []


def test_history_manifest_refuses_an_authorization_epoch_that_moved_mid_read(store, monkeypatch):
    """A bump between the broad proof and the final one invalidates both."""
    world = history_world(store)
    original = EvidenceAccess.build

    def moved(self, selection=None):
        proof = original(self, selection)
        if selection is not None and selection.revision_ids:
            return replace(proof, authorization_epoch=proof.authorization_epoch + 1)
        return proof

    monkeypatch.setattr(EvidenceAccess, "build", moved)

    with pytest.raises(AuthorizationChanged):
        select(world)

    assert store._knowledge_rows("HistoryManifest") == []


def test_history_manifest_pin_proves_the_calling_audience_not_the_selecting_one(store):
    """The bundle's proof, fingerprint and later revalidations belong to the caller."""
    world = history_world(store)
    principal = reader(store, world.workspace, "bystander")
    caller = Access(user_id=principal)
    internal = select(world)

    bundle = snapshot_service.acquire_history_snapshot(
        store, caller, history=internal, settings_fingerprint="settings", clock=lambda: MAY_12
    )
    try:
        resolver, proof = bundle.proofs[0]
        own = history_access(store, world.workspace, caller, clock=lambda: MAY_12).build(internal.selection)
        assert world.secret_span.id in internal.proof.span_ids
        assert world.secret_span.id not in proof.span_ids
        assert resolver.access == caller
        assert proof.policy_fingerprint == own.policy_fingerprint
        assert bundle.snapshots[0].policy_fingerprint == own.policy_fingerprint
    finally:
        bundle.close()


def test_history_manifest_pin_denies_a_caller_who_cannot_reprove_it(store):
    """Acquisition, not first use, is where a lost grant stops a historical pin."""
    world = history_world(store)
    old = select(world)
    _suppress(world, target_kind="artifact", target_id=world.artifact.id, reason="access_loss", epoch=2)

    with pytest.raises(AuthorizationChanged):
        snapshot_service.acquire_history_snapshot(
            store, EVERYTHING, history=old, settings_fingerprint="settings", clock=lambda: MAY_12
        )


def test_history_manifest_pins_an_implicit_cutoff_for_current_and_atemporal_modes(store):
    """All six modes round-trip: a pinned selector re-resolves to the pinned instant."""
    world = history_world(store)
    later = datetime(2026, 6, 1, tzinfo=UTC)

    for selection in (
        select(world, selector=k.CurrentSelector()),
        select(world, selector=k.AtemporalSelector()),
    ):
        assert selection.selector.known_at == MAY_12
        assert '"known_at":"2026-05-12T00:00:00Z"' in selection.manifest.temporal_selector_json
        again = resolve_selector(selection.selector, latest_known_at=later)
        assert (again.known_at, again.known_at_source) == (MAY_12, "explicit")

    current = select(world, selector=k.CurrentSelector())
    bundle = snapshot_service.acquire_history_snapshot(
        store, EVERYTHING, history=current, settings_fingerprint="settings", clock=lambda: MAY_12
    )
    try:
        assert bundle.snapshots[0].temporal.known_at == MAY_12
    finally:
        bundle.close()


def test_history_manifest_reads_through_a_running_rebuild_of_its_source(store):
    """Naming retained evidence is bookkeeping; it never needs the build lease."""
    world = history_world(store)
    third = _generation(store, world.source, "gen-three", world.second)
    _claim(store, third)

    old = select(world)

    assert old.manifest.revision_ids == (world.revision_one.id,)
    assert old.manifest.assertion_version_ids == (world.version_one.id,)


def test_history_manifest_read_leaves_the_content_epoch_where_it_found_it(store):
    """A read may not advance content state, for the manifest or a conflict set."""
    world = history_world(store)
    before = store.content_epoch()

    old = select(world)
    store.put_knowledge(
        k.ConflictSet(
            workspace_id=world.workspace,
            scope_key="prod",
            assertion_version_ids=tuple(sorted((world.version_one.id, world.version_two.id))),
            resolution_status="possible",
            support_span_ids=tuple(sorted((world.span_one.id, world.secret_span.id))),
        )
    )

    assert store._knowledge_get("HistoryManifest", old.manifest.id) == old.manifest
    assert store.content_epoch() == before


def test_history_manifest_conflict_set_persists_through_a_running_rebuild(store):
    """Part 2 persists conflict sets on a read path; a build lease must not fence it."""
    world = history_world(store)
    third = _generation(store, world.source, "gen-three", world.second)
    _claim(store, third)

    conflict = k.ConflictSet(
        workspace_id=world.workspace,
        scope_key="prod",
        assertion_version_ids=tuple(sorted((world.version_one.id, world.version_two.id))),
        resolution_status="possible",
        support_span_ids=tuple(sorted((world.span_one.id, world.secret_span.id))),
    )
    store.put_knowledge(conflict)

    assert store._knowledge_get("ConflictSet", conflict.id) == conflict


def test_history_manifest_is_empty_rather_than_unavailable_without_authorized_rows(store):
    """`history_unavailable` is a statement about retention, not about permission."""
    world = history_world(store)
    _suppress(world, target_kind="artifact", target_id=world.artifact.id, reason="access_loss", epoch=2)

    empty = select(world)

    assert empty.codes == ()
    assert empty.manifest.revision_ids == ()
    assert empty.manifest.assertion_version_ids == ()
    assert empty.coverage["proven"] == {"observations": 0, "assertion_versions": 0}
    assert empty.coverage["contextual"] == {"observations": 0, "assertion_versions": 0}


def test_purge_history_evidence_answers_only_an_audience_that_proves_the_manifest(store):
    """Unknown, foreign-workspace and unauthorized all get one indistinguishable answer."""
    world = history_world(store)
    principal = reader(store, world.workspace, "bystander")
    revoked = reader(store, world.workspace, "revoked")
    store.update_knowledge(
        k.WorkspaceMembership(
            workspace_id=world.workspace,
            principal_id=revoked,
            enabled=False,
            mapping_authority="reviewed",
            policy_epoch=3,
        )
    )
    now = select(world, valid_at=MAY_12, known_at=MAY_12)
    _suppress(
        world,
        target_kind="revision",
        target_id=world.revision_one.id,
        reason="purge",
        epoch=3,
        barrier="destroy",
    )
    markers = (PurgedEvidence("revision", world.revision_one.id),)

    assert world.revision_two.id in now.manifest.revision_ids
    for audience in (EVERYTHING, Access(user_id=principal)):
        assert (
            store.purged_history_evidence(now.manifest.id, workspace_id=world.workspace, access=audience)
            == markers
        )
    for call in (
        dict(workspace_id="workspace-elsewhere", access=EVERYTHING),
        dict(workspace_id=world.workspace, access=Access(user_id=revoked)),
    ):
        with pytest.raises(SnapshotUnavailable):
            store.purged_history_evidence(now.manifest.id, **call)
    with pytest.raises(SnapshotUnavailable):
        store.purged_history_evidence(
            "historymanifest-absent", workspace_id=world.workspace, access=EVERYTHING
        )


# --- Section 5: append-only recorded correction publication ---------------------


def _passage(gen, revision, span):
    from hippo.knowledge.lifecycle import generation_passage_id

    return dict(
        id=generation_passage_id(gen.id, revision.id, span.id, 0),
        source_id=gen.source_id,
        generation_id=gen.id,
        artifact_revision_id=revision.id,
        span_id=span.id,
        embedding_profile="p",
        text=span.text,
        title=span.text,
        ordinal=0,
        embedding=[0.1, 0.2],
    )


def _member(store, gen, record):
    store.put_knowledge(
        k.GenerationEvidenceMember(
            generation_id=gen.id, record_kind=type(record).__name__, record_id=record.id
        )
    )


def _support(store, version, span):
    row = k.AssertionSupport(assertion_version_id=version.id, span_id=span.id, derivation_group="direct")
    store.put_knowledge(row)
    return row


def _owned_by(store, workspace, subject, name, *, scope_key="prod"):
    target = _object(store, workspace, "person", name)
    assertion = k.checked_assertion(subject, "OWNED_BY", target, scope_key=scope_key)
    store.put_knowledge(assertion)
    return assertion, target


def correction_world(store, *, extra_span=None, corroborated=False, seal=True):
    """The plan's May ownership example, staged for an append-only correction.

    Unlike `history_world`, every corrected row is an exact member of its
    generation, so the published-interpretation guard is real and nothing but a
    publication plan can close it. The second generation is left sealed and
    unpublished, so each test publishes it with the plan variation it is about.

    `extra_span` stages one more version in the corrected series whose support
    row is deliberately *not* a member: `"two"` supports it from this
    generation's own span, `"one"` from the previous generation's, which are the
    two ways an appended segment can depend on evidence its generation does not
    carry. Such a generation cannot be sealed, so `extra_span` implies
    `seal=False`. `corroborated` adds an open version this source supports
    *jointly with a second source*, built before the second build is claimed
    because a support row reaching a source's revisions needs build authority
    once its build is running.
    """
    source = store.create_source("text", "owners-corrected")
    workspace = store.get_source(source)["workspace_id"]
    if store._knowledge_get("Workspace", workspace) is None:
        store.put_knowledge(k.Workspace(name="default"))
    policy = k.AccessPolicy(
        workspace_id=workspace,
        origin="local_curated",
        scope_key="source:" + source,
        mode="workspace",
        verified_at=MAY_1,
    )
    store.put_knowledge(policy)
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=source,
        kind="file",
        external_id="owners.md",
        canonical_uri="source:owners.md",
        policy_id=policy.id,
    )
    store.put_knowledge(artifact)

    first = _generation(store, source, "corr-one", at=MAY_1)
    job_one = _claim(store, first, at=MAY_1)
    with store.generation_write(first.id, **_credentials(job_one)):
        revision_one = _revision(store, artifact, "may-1", MAY_1)
        store.put_knowledge(k.GenerationMember(generation_id=first.id, artifact_revision_id=revision_one.id))
        span_one = _span(store, revision_one, "owners-may-1", policy)
        _member(store, first, span_one)
        store.add_passages([_passage(first, revision_one, span_one)])
        service = _object(store, workspace, "service", "checkout")
        observation_one = _observation(store, service, span_one, MAY_1, valid_from=MAY_1)
        _member(store, first, observation_one)
        owned_by_ada, ada = _owned_by(store, workspace, service, "ada")
        # Both endpoints need an authorized observation before the proof carries
        # the assertion at all, exactly as `history_world` establishes them.
        _member(store, first, _observation(store, ada, span_one, MAY_1, valid_from=MAY_1))
        version_one = _version(store, owned_by_ada, MAY_1, MAY_1)
        support_one = _support(store, version_one, span_one)
        _member(store, first, version_one)
        _member(store, first, support_one)
    _publish(store, first, job_one, at=MAY_1)

    # An open-then-closed version of the same source that no generation selected.
    # Its effective time is unknown, so it stays contextual and never enters a
    # manifest, but it is a real "already closed" closure target.
    retracted = k.AssertionVersion(
        assertion_id=_owned_by(store, workspace, service, "cass")[0].id,
        evidence_class="declared",
        rule_version="fixture-v1",
        confidence=1.0,
        status="retracted",
        recorded_from=MAY_1,
    )
    store.put_knowledge(retracted)
    _support(store, retracted, span_one)
    store.update_knowledge(retracted.replace(recorded_to=MAY_10))
    retracted = store._knowledge_get("AssertionVersion", retracted.id)

    corroborated_version = None
    if corroborated:
        # Decision 3's case: this source's claim, also proven by a second
        # source's span, so no single publication owns the whole support group.
        other = _other_source_span(store, workspace, "corroborating-owners")
        subject = _object(store, workspace, "service", "search")
        assertion = _owned_by(store, workspace, subject, "gil")[0]
        corroborated_version = _version(store, assertion, MAY_1, MAY_1)
        _support(store, corroborated_version, span_one)
        _support(store, corroborated_version, other)

    second = _generation(store, source, "corr-two", first, at=MAY_12)
    job_two = _claim(store, second, at=MAY_12)
    with store.generation_write(second.id, **_credentials(job_two)):
        revision_two = _revision(store, artifact, "may-10", MAY_10)
        store.put_knowledge(k.GenerationMember(generation_id=second.id, artifact_revision_id=revision_two.id))
        span_two = _span(store, revision_two, "owners-may-10", policy)
        _member(store, second, span_two)
        store.add_passages([_passage(second, revision_two, span_two)])
        observation_two = _observation(store, service, span_two, MAY_12, valid_from=MAY_10)
        _member(store, second, observation_two)
        # A staged segment whose recorded clock is not the publication instant.
        mistimed = _observation(store, service, span_two, MAY_10, valid_from=MAY_10)
        _member(store, second, mistimed)
        owned_by_bo, bo = _owned_by(store, workspace, service, "bo")
        _member(store, second, _observation(store, bo, span_two, MAY_12, valid_from=MAY_10))
        version_two = _version(store, owned_by_bo, MAY_12, MAY_10)
        support_two = _support(store, version_two, span_two)
        _member(store, second, version_two)
        _member(store, second, support_two)
        extra_version = None
        if extra_span is not None:
            owned_by_eve, _ = _owned_by(store, workspace, service, "eve")
            extra_version = _version(store, owned_by_eve, MAY_12, MAY_10)
            _support(store, extra_version, span_one if extra_span == "one" else span_two)
            # The version stages cleanly - an AssertionVersion reaches no revision
            # through its references, so the evidence-member guard passes
            # vacuously. Its support row is deliberately never staged: that is
            # what the publication plan's own dependency check must catch.
            _member(store, second, extra_version)
    if seal and extra_span is None:
        _seal(store, second, job_two)

    return SimpleNamespace(
        store=store,
        source=source,
        workspace=workspace,
        policy=policy,
        artifact=artifact,
        first=first,
        second=second,
        job_two=job_two,
        revision_one=revision_one,
        revision_two=revision_two,
        span_one=span_one,
        span_two=span_two,
        service=service,
        observation_one=observation_one,
        observation_two=observation_two,
        mistimed=mistimed,
        retracted=retracted,
        version_one=version_one,
        version_two=version_two,
        support_one=support_one,
        extra_version=extra_version,
        corroborated=corroborated_version,
    )


def _plan(world, **changes):
    fields = dict(
        published_at=MAY_12,
        closures=(
            RecordedSegment("AssertionVersion", world.version_one.id),
            RecordedSegment("ObjectObservation", world.observation_one.id),
        ),
        appends=(
            RecordedSegment("AssertionVersion", world.version_two.id),
            RecordedSegment("ObjectObservation", world.observation_two.id),
        ),
    )
    return TemporalPublicationPlan(**(fields | changes))


def _row(store, kind, record_id):
    return store._knowledge_get(kind, record_id)


def _bytes(store, kind, record_id):
    """The row as it would serialize, so a rollback can be compared byte for byte."""
    return _row(store, kind, record_id).model_dump_json()


def _unsupported_version(world):
    """An open version with no support group at all; nothing proves its lineage."""
    subject = _object(world.store, world.workspace, "service", "shipping")
    assertion, _ = _owned_by(world.store, world.workspace, subject, "dee")
    return _version(world.store, assertion, MAY_1, MAY_1)


def _other_source_span(store, workspace, name):
    """A span of a second source in the same workspace."""
    other = store.create_source("text", name)
    policy = k.AccessPolicy(
        workspace_id=workspace,
        origin="local_curated",
        scope_key="source:" + other,
        mode="workspace",
        verified_at=MAY_1,
    )
    store.put_knowledge(policy)
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=other,
        kind="file",
        external_id=name + ".md",
        canonical_uri="source:" + name + ".md",
        policy_id=policy.id,
    )
    store.put_knowledge(artifact)
    return _span(store, _revision(store, artifact, name + "-may-1", MAY_1), name, policy)


def _foreign_version(world):
    """A version whose complete support belongs to another source entirely."""
    store = world.store
    subject = _object(store, world.workspace, "service", "billing")
    assertion, _ = _owned_by(store, world.workspace, subject, "cy")
    version = _version(store, assertion, MAY_1, MAY_1)
    _support(store, version, _other_source_span(store, world.workspace, "other-owners"))
    return version


def test_recorded_correction_plan_is_frozen_canonical_and_disjoint():
    """The plan is data the caller fixed before the transaction, not a callback."""
    older = RecordedSegment("AssertionVersion", "assertionversion-a")
    newer = RecordedSegment("AssertionVersion", "assertionversion-b")
    observation = RecordedSegment("ObjectObservation", "objectobservation-a")
    plan = TemporalPublicationPlan(published_at=MAY_12, closures=(observation, older), appends=(newer,))

    assert plan.closures == (older, observation)
    assert plan.published_at == MAY_12
    assert (
        plan.fingerprint
        == TemporalPublicationPlan(
            published_at=MAY_12, closures=(older, observation), appends=(newer,)
        ).fingerprint
    )
    assert (
        plan.fingerprint
        != TemporalPublicationPlan(
            published_at=MAY_12 + timedelta(days=1), closures=(older, observation), appends=(newer,)
        ).fingerprint
    )
    with pytest.raises(AttributeError):
        plan.closures = ()
    with pytest.raises(ValueError, match="unique"):
        TemporalPublicationPlan(published_at=MAY_12, closures=(older, older))
    with pytest.raises(ValueError, match="also be appended"):
        TemporalPublicationPlan(published_at=MAY_12, closures=(older,), appends=(older,))
    with pytest.raises(ValueError, match="at least one"):
        TemporalPublicationPlan(published_at=MAY_12, closures=())
    with pytest.raises(TypeError, match="segments"):
        TemporalPublicationPlan(published_at=MAY_12, closures=(("AssertionVersion", "x"),))
    with pytest.raises(ValueError, match="timezone aware"):
        TemporalPublicationPlan(published_at=datetime(2026, 5, 12), closures=(older,))
    with pytest.raises(ValueError, match="recorded evidence"):
        RecordedSegment("EvidenceSpan", "evidencespan-a")


def test_recorded_correction_closes_the_prior_segment_and_appends_the_corrected_one(store):
    """May's backdated ownership correction: closures and appends in one transaction."""
    world = correction_world(store)

    _publish_only(store, world.second, world.job_two, plan=_plan(world))

    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to == MAY_12
    assert _row(store, "ObjectObservation", world.observation_one.id).recorded_to == MAY_12
    assert _row(store, "AssertionVersion", world.version_two.id).recorded_to is None
    assert _row(store, "AssertionVersion", world.version_two.id).recorded_from == MAY_12
    assert _row(store, "Generation", world.second.id).status == "active"
    assert _row(store, "Generation", world.first.id).status == "retired"
    assert store.get_source(world.source)["active_generation_id"] == world.second.id
    # Original bytes are immutable: `recorded_to` is the only field that moved.
    assert _row(store, "AssertionVersion", world.version_one.id) == world.version_one.replace(
        recorded_to=MAY_12
    )


def test_recorded_correction_is_visible_to_history_selection_at_each_cutoff(store):
    """Behavior 7: each cutoff returns its own segment, and `recorded_to` serializes."""
    world = correction_world(store)
    _publish_only(store, world.second, world.job_two, plan=_plan(world))

    before = select(world, valid_at=MAY_5, known_at=MAY_5)
    after = select(world, valid_at=MAY_12, known_at=MAY_12)

    assert before.manifest.assertion_version_ids == (world.version_one.id,)
    assert after.manifest.assertion_version_ids == (world.version_two.id,)
    closed = _row(store, "AssertionVersion", world.version_one.id)
    assert serialize_temporal_evidence(TemporalInputs(record=closed))["recorded_to"] == "2026-05-12T00:00:00Z"
    assert serialize_temporal_evidence(TemporalInputs(record=world.version_two))["recorded_to"] is None


@pytest.mark.parametrize("point", ["closure", "pointer", "version", "retirement", "event", "lease"])
def test_recorded_correction_rolls_back_every_write_when_a_failpoint_fires(store, point):
    world = correction_world(store)
    epoch = store.content_epoch()
    affected = (
        ("AssertionVersion", world.version_one.id),
        ("ObjectObservation", world.observation_one.id),
        ("AssertionVersion", world.version_two.id),
        ("ObjectObservation", world.observation_two.id),
    )
    before = {key: _bytes(store, *key) for key in affected}

    def fail(at):
        if at == point:
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        _publish_only(store, world.second, world.job_two, plan=_plan(world), fault_hook=fail)

    # Byte-identical, not merely open: no field of any corrected row may move.
    assert {key: _bytes(store, *key) for key in affected} == before
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to is None
    assert _row(store, "ObjectObservation", world.observation_one.id).recorded_to is None
    assert _row(store, "Generation", world.first.id).status == "active"
    assert _row(store, "Generation", world.second.id).status == "ready"
    assert store.get_source(world.source)["active_generation_id"] == world.first.id
    assert _row(store, "MaintenanceJob", world.job_two.id).status == "running"
    assert store.content_epoch() == epoch


def test_recorded_correction_retry_returns_the_original_receipt_and_observes_the_closures(store):
    world = correction_world(store)
    plan = _plan(world)

    receipt = _publish_only(store, world.second, world.job_two, plan=plan)
    epoch = store.content_epoch()

    assert _publish_only(store, world.second, world.job_two, plan=plan) == receipt
    assert store.content_epoch() == epoch
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to == MAY_12


def test_recorded_correction_retry_with_a_different_plan_fails_without_writing(store):
    world = correction_world(store)
    _publish_only(store, world.second, world.job_two, plan=_plan(world))
    epoch = store.content_epoch()
    narrower = _plan(
        world,
        closures=(RecordedSegment("AssertionVersion", world.version_one.id),),
        appends=(RecordedSegment("AssertionVersion", world.version_two.id),),
    )

    for call in (dict(plan=narrower), dict(plan=None)):
        with pytest.raises(ValueError, match="another build"):
            _publish_only(store, world.second, world.job_two, **call)
    assert store.content_epoch() == epoch
    assert _row(store, "ObjectObservation", world.observation_one.id).recorded_to == MAY_12


@pytest.mark.parametrize(
    "case,message",
    [
        ("closed", "already closed"),
        ("foreign", "lineage"),
        ("corroborated", "lineage"),
        ("unsupported", "complete support"),
        ("not_before", "before the publication"),
        ("missing", "missing"),
    ],
)
def test_recorded_correction_refuses_a_closure_target_it_cannot_prove(store, case, message):
    """Decision 3 included: one source's publication cannot retire a shared claim."""
    world = correction_world(store, corroborated=case == "corroborated")
    target = {
        "closed": lambda: world.retracted.id,
        "foreign": lambda: _foreign_version(world).id,
        "corroborated": lambda: world.corroborated.id,
        "unsupported": lambda: _unsupported_version(world).id,
        "not_before": lambda: world.version_two.id,
        "missing": lambda: "assertionversion-absent",
    }[case]()
    plan = _plan(world, closures=(RecordedSegment("AssertionVersion", target),), appends=())
    epoch = store.content_epoch()

    with pytest.raises(ValueError, match=message):
        _publish_only(store, world.second, world.job_two, plan=plan)
    assert store.content_epoch() == epoch
    assert _row(store, "Generation", world.second.id).status == "ready"
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to is None


@pytest.mark.parametrize(
    "case,message",
    [
        ("outside", "exact member"),
        ("recorded", "publication instant"),
        ("series", "corrected series"),
    ],
)
def test_recorded_correction_refuses_an_append_outside_the_staged_correction(store, case, message):
    world = correction_world(store)
    closures = (RecordedSegment("AssertionVersion", world.version_one.id),)
    appends = {
        "outside": lambda: (RecordedSegment("AssertionVersion", _unsupported_version(world).id),),
        "recorded": lambda: (RecordedSegment("ObjectObservation", world.mistimed.id),),
        "series": lambda: (RecordedSegment("ObjectObservation", world.observation_two.id),),
    }[case]()

    with pytest.raises(ValueError, match=message):
        _publish_only(
            store, world.second, world.job_two, plan=_plan(world, closures=closures, appends=appends)
        )
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to is None
    assert _row(store, "Generation", world.second.id).status == "ready"


def test_recorded_correction_refuses_a_closure_target_the_same_generation_publishes(store):
    """A generation may not close a row it is itself publishing.

    `mistimed` is a staged member of the second generation whose `recorded_from`
    is before the publication instant, so every other closure precondition holds.
    Closing it would mint a recorded window over which Hippo exposed nothing: the
    generation that carries the row was not active for a moment of it. A
    correction closes only what an earlier generation published.
    """
    world = correction_world(store)
    plan = _plan(world, closures=(RecordedSegment("ObjectObservation", world.mistimed.id),), appends=())

    with pytest.raises(ValueError, match="generation being published"):
        _publish_only(store, world.second, world.job_two, plan=plan)
    assert _row(store, "ObjectObservation", world.mistimed.id).recorded_to is None
    assert _row(store, "Generation", world.second.id).status == "ready"


@pytest.mark.parametrize("extra_span", ["two", "one"])
def test_recorded_correction_cannot_even_seal_an_append_whose_proof_group_is_incomplete(store, extra_span):
    """Where "preserves evidence dependencies" is really enforced for a version.

    An `AssertionVersion` reaches no revision through its own references, so the
    evidence-member guard passes vacuously when it is staged. What catches it is
    `validate_generation_seal` (`generations.py:703-710`), which requires every
    support row of a member version to be a member too, and which
    `publish_staged_generation` re-runs at `generations.py:995` before it
    validates any plan. `"two"` supports the extra version from this
    generation's own span, `"one"` from the previous generation's; in both the
    support row is deliberately unstaged, and in both the generation never
    reaches a publishable state at all.
    """
    world = correction_world(store, extra_span=extra_span)

    with pytest.raises(ValueError, match="Incomplete assertion proof group"):
        _seal(store, world.second, world.job_two)
    # And an unsealed generation cannot publish at all: the strict path takes
    # only a `ready` generation, so no plan of any shape is ever looked at.
    with pytest.raises(ValueError, match="Stale build lease, fence, or generation state"):
        _publish_only(store, world.second, world.job_two, plan=_plan(world))
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to is None
    assert _row(store, "Generation", world.second.id).status == "staging"


@pytest.mark.parametrize("extra_span", ["two", "one"])
def test_recorded_correction_plan_refuses_an_append_depending_on_outside_evidence(store, extra_span):
    """The plan's own dependency check, pinned where the publication cannot reach it.

    `generations.py:914` is defense in depth behind the seal check above: every
    route to it through `publish_staged_generation` is refused earlier with
    "Incomplete assertion proof group" (measured by mutating the line away).
    Validation is read-only and side-effect free, so the check is pinned by
    calling it directly - this test fails if the line is removed.
    """
    world = correction_world(store, extra_span=extra_span)
    gen = store._knowledge_get("Generation", world.second.id)
    plan = _plan(
        world,
        closures=(RecordedSegment("AssertionVersion", world.version_one.id),),
        appends=(RecordedSegment("AssertionVersion", world.extra_version.id),),
    )

    with pytest.raises(ValueError, match="depends on evidence outside its generation"):
        store._validate_publication_plan(gen, plan)
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to is None


def test_recorded_correction_cannot_stage_a_support_row_from_another_generation(store):
    """The companion fact: what a support row's own staging already refuses.

    A support row *does* reach a revision, so staging one whose span belongs to
    an earlier generation is refused by the evidence-member guard. The version it
    supports is not, which is why the proof-group rule has to be enforced on the
    version rather than left to its references.
    """
    world = correction_world(store, seal=False)

    with pytest.raises(ValueError, match="outside generation revisions"):
        with store.generation_write(world.second.id, **_credentials(world.job_two)):
            _member(store, world.second, world.support_one)


def test_recorded_correction_requires_the_plan_clock_to_be_the_publication_clock(store):
    """No unguarded clock: `published_at` is the plan's, fixed before the transaction."""
    world = correction_world(store)

    with pytest.raises(ValueError, match="publication clock"):
        _publish_only(store, world.second, world.job_two, plan=_plan(world, published_at=MAY_10))
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to is None


def test_recorded_correction_is_refused_by_the_generic_fixture_publication_path(store):
    """The compatibility primitive must never become a correction bypass."""
    world = correction_world(store)

    with pytest.raises(ValueError, match="strict publication"):
        store.publish_generation(
            world.second.id, expected_parent_id=world.first.id, published_at=MAY_12, plan=_plan(world)
        )
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to is None


def test_recorded_correction_fails_without_writes_on_a_stale_parent_or_a_later_suppression(store):
    """Precondition (d) in full: a stale parent, a stale fence and a moved epoch."""
    world = correction_world(store)
    plan = _plan(world)

    for change in (
        dict(expected_suppression_epoch=store.suppression_epoch() + 1),
        dict(expected_parent_id=None),
        dict(fencing_token=world.job_two.fencing_token + 1),
    ):
        call = dict(
            expected_parent_id=world.first.id,
            expected_suppression_epoch=store.suppression_epoch(),
            published_at=MAY_12,
            plan=plan,
            **_credentials(world.job_two),
        )
        with pytest.raises(ValueError):
            store.publish_staged_generation(world.second.id, **(call | change))
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to is None
    assert _row(store, "ObjectObservation", world.observation_one.id).recorded_to is None


def test_recorded_correction_never_reaches_a_published_row_through_update_knowledge(store):
    """Outside the plan the published interpretation is immutable, and closes once."""
    world = correction_world(store)

    with pytest.raises(ValueError, match="immutable"):
        store.update_knowledge(world.version_one.replace(recorded_to=MAY_12))
    _publish_only(store, world.second, world.job_two, plan=_plan(world))
    with pytest.raises(ValueError, match="close once"):
        store.update_knowledge(world.version_one.replace(recorded_to=MAY_12 + timedelta(days=1)))


def test_recorded_correction_closure_helper_refuses_a_caller_without_a_capability(store):
    """An ambient transaction is not authority; the publication's capability is.

    `store.transaction()` is public, so "inside a transaction" says nothing about
    who opened it. The closure helper takes the capability `publish_staged_generation`
    mints after the plan validates, and a caller that has only a transaction
    cannot call it at all.
    """
    world = correction_world(store)
    segments = (("AssertionVersion", world.version_one.id),)

    with pytest.raises(TypeError, match="capability"):
        with store.transaction():
            store._close_recorded_intervals(segments, recorded_to=MAY_12)
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to is None


def test_recorded_correction_closure_capability_is_neither_forgeable_nor_reusable(store, monkeypatch):
    """The capability is the object the publication minted, not its field values.

    A caller can construct something that looks identical, and can keep the real
    one after the publication that minted it returns. Neither is accepted: the
    helper requires the capability the store is holding for this publication,
    and the publication drops it as soon as its closures are written.
    """
    from hippo.store.knowledge import RecordedClosureCapability

    world = correction_world(store)
    plan = _plan(world)
    segments = tuple((s.record_kind, s.record_id) for s in plan.closures)
    captured = []
    original = type(store)._close_recorded_intervals

    def spy(self, closing, *, recorded_to, capability):
        captured.append(capability)
        return original(self, closing, recorded_to=recorded_to, capability=capability)

    monkeypatch.setattr(type(store), "_close_recorded_intervals", spy)
    forged = RecordedClosureCapability(
        generation_id=world.second.id,
        plan_fingerprint=plan.fingerprint,
        recorded_to=plan.published_at,
        segments=segments,
    )

    for capability in (forged, None):
        with pytest.raises(RuntimeError, match="capability"):
            with store.transaction():
                store._close_recorded_intervals(segments, recorded_to=MAY_12, capability=capability)
    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to is None

    captured.clear()
    _publish_only(store, world.second, world.job_two, plan=plan)

    assert _row(store, "AssertionVersion", world.version_one.id).recorded_to == MAY_12
    # The minted capability carries the same fields the forgery guessed; being a
    # different object is the whole of the difference, and it is decisive.
    assert captured and captured[0] is not forged
    assert captured[0].plan_fingerprint == forged.plan_fingerprint
    assert getattr(store, "_closure_capability", None) is None
    with pytest.raises(RuntimeError, match="capability"):
        with store.transaction():
            store._close_recorded_intervals(segments, recorded_to=MAY_12, capability=captured[0])
