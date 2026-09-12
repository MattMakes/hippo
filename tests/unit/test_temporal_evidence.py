"""Pure bitemporal selector and evidence-clock behavior."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from hippo.knowledge import model as k
from hippo.knowledge.temporal import (
    ResolvedTemporalSelector,
    TemporalInputs,
    match_temporal,
    resolve_selector,
    serialize_temporal_evidence,
)

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
