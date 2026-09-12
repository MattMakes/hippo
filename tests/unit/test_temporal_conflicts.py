"""Adapter-owned ordering and cardinality-aware conflict behavior."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hippo.knowledge import model as k
from hippo.knowledge.conflicts import (
    ConflictCandidate,
    SourceOrder,
    build_conflict_sets,
    compare_orders,
    fully_superseded_version_ids,
    select_same_source,
)

JAN_1 = datetime(2026, 1, 1, tzinfo=UTC)
MAY_1 = datetime(2026, 5, 1, tzinfo=UTC)
MAY_5 = datetime(2026, 5, 5, tzinfo=UTC)
MAY_10 = datetime(2026, 5, 10, tzinfo=UTC)
JUNE_1 = datetime(2026, 6, 1, tzinfo=UTC)
NEXT_JAN_1 = datetime(2027, 1, 1, tzinfo=UTC)

FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/rag_all/temporal_events.jsonl"
PRECISIONS = {"instant", "second", "minute", "day", "month", "year", "unknown"}
ORDER_KINDS = {"monotonic", "equality_only", "unknown"}
CLAIM_KEYS = {
    "case",
    "source_id",
    "provider_order",
    "valid_from",
    "valid_to",
    "recorded_from",
    "precision",
    "claim",
}
CLAIM_OPTIONAL_KEYS = {"scope_key", "content_hash", "source_updated_at", "source_precision"}
SUPPRESSION_KEYS = {"case", "source_id", "suppression", "recorded_from"}
BARRIER_KEYS = {"case", "source_id", "provider_order", "restoration_barrier", "recorded_from"}
INSTANT_KEYS = ("valid_from", "valid_to", "recorded_from", "source_updated_at")
# The nine scenarios named in plan section 7 step 3, mapped onto the fixture's `case` labels.
SCENARIO_CASES = {
    "may ownership correction": ("may_owner_alice", "may_owner_bob", "backdated_correction"),
    "imported old last": ("old_imported_last",),
    "equal ordering datum with different bytes": (
        "equal_order_different_bytes",
        "equal_timestamp_different_bytes",
    ),
    "unknown date": ("unknown_date",),
    "environment collision": ("environment_collision",),
    "independent source alternatives": ("independent_alternative",),
    "ordinary tombstone": ("ordinary_tombstone",),
    "all-history purge": ("purged_history",),
    "explicit restoration barrier": ("explicit_restoration",),
}


def candidate(
    target,
    *,
    source_id,
    scope="service-a:production",
    valid_from=MAY_1,
    valid_to=None,
    validity_kind="explicit_interval",
    order_kind="unknown",
    ordinal=None,
    provider_token=None,
    adapter_id="fixture",
    adapter_version="v1",
    series_key="service-a-owner",
    support_suffix="one",
    recorded_from=MAY_1,
    precision=None,
):
    assertion = k.Assertion(
        workspace_id="workspace-a",
        subject_id="service-a",
        predicate="OWNED_BY",
        object_id=target,
        scope_key=scope,
    )
    temporal_basis = {
        "explicit_interval": "source_explicit",
        "observed_snapshot": "provider_snapshot",
        "atemporal": "atemporal",
        "unknown": "unknown",
    }[validity_kind]
    version = k.AssertionVersion(
        assertion_id=assertion.id,
        evidence_class="declared",
        rule_version="fixture-v1",
        confidence=1.0,
        status="active",
        valid_from=valid_from,
        valid_to=valid_to,
        validity_kind=validity_kind,
        recorded_from=recorded_from,
        temporal_basis=temporal_basis,
        temporal_precision=precision or ("instant" if validity_kind == "explicit_interval" else "unknown"),
    )
    return ConflictCandidate(
        assertion=assertion,
        version=version,
        source_id=source_id,
        support_span_ids=(f"span-{source_id}-{support_suffix}",),
        order=SourceOrder(
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            series_key=series_key,
            kind=order_kind,
            provider_token=provider_token,
            monotonic_ordinal=ordinal,
        ),
    )


def test_source_order_accepts_ordinal_only_for_versioned_monotonic_adapter_contract():
    with pytest.raises(ValueError, match="Monotonic ordering"):
        SourceOrder(
            adapter_id="fixture",
            adapter_version="v1",
            series_key="owners",
            kind="monotonic",
            provider_token="opaque",
        )
    with pytest.raises(ValueError, match="only for monotonic"):
        SourceOrder(
            adapter_id="fixture",
            adapter_version="v1",
            series_key="owners",
            kind="equality_only",
            provider_token="opaque",
            monotonic_ordinal=7,
        )


def order(**changes):
    fields = dict(
        adapter_id="fixture",
        adapter_version="v1",
        series_key="service-a-owner",
        kind="monotonic",
        provider_token=None,
        monotonic_ordinal=1,
    )
    return SourceOrder(**(fields | changes))


def test_compare_orders_relates_ordinals_only_within_one_adapter_contract_and_series():
    first = order(monotonic_ordinal=1)
    second = order(monotonic_ordinal=2)

    assert compare_orders(first, second) == "older"
    assert compare_orders(second, first) == "newer"
    assert compare_orders(first, order(monotonic_ordinal=1)) == "same"
    assert compare_orders(first, first) == "same"


def test_compare_orders_reports_ambiguous_for_every_order_it_cannot_prove():
    monotonic = order(monotonic_ordinal=2)
    unknown = SourceOrder(
        adapter_id="fixture", adapter_version="v1", series_key="service-a-owner", kind="unknown"
    )
    equality_only = SourceOrder(
        adapter_id="fixture",
        adapter_version="v1",
        series_key="service-a-owner",
        kind="equality_only",
        provider_token="etag-same",
    )

    assert compare_orders(monotonic, order(adapter_id="other", monotonic_ordinal=1)) == "ambiguous"
    assert compare_orders(monotonic, order(adapter_version="v2", monotonic_ordinal=1)) == "ambiguous"
    assert compare_orders(monotonic, order(series_key="other-series", monotonic_ordinal=1)) == "ambiguous"
    assert compare_orders(monotonic, unknown) == "ambiguous"
    assert compare_orders(unknown, unknown) == "ambiguous"
    assert compare_orders(monotonic, equality_only) == "ambiguous"
    assert compare_orders(equality_only, equality_only) == "ambiguous"

    corrupted = SourceOrder(
        adapter_id="fixture", adapter_version="v1", series_key="service-a-owner", kind="unknown"
    )
    object.__setattr__(corrupted, "kind", "monotonic")  # an ordinal-less order that bypassed validation
    assert compare_orders(corrupted, monotonic) == "ambiguous"
    assert compare_orders(monotonic, corrupted) == "ambiguous"


def test_each_ordering_adapter_forms_its_own_series_and_supersedes_within_it():
    old_one = candidate(
        "alice", source_id="catalog", order_kind="monotonic", ordinal=1, support_suffix="alice"
    )
    new_one = candidate("bob", source_id="catalog", order_kind="monotonic", ordinal=2, support_suffix="bob")
    old_two = candidate(
        "carol",
        source_id="catalog",
        order_kind="monotonic",
        ordinal=1,
        adapter_version="v2",
        support_suffix="carol",
    )
    new_two = candidate(
        "dave",
        source_id="catalog",
        order_kind="monotonic",
        ordinal=2,
        adapter_version="v2",
        support_suffix="dave",
    )

    selection = select_same_source((new_two, old_one, new_one, old_two))

    assert {item.version.id for item in selection.current} == {new_one.version.id, new_two.version.id}
    assert selection.superseded_version_ids == tuple(sorted((old_one.version.id, old_two.version.id)))
    assert selection.ambiguous_series == ()
    assert selection.requires_refetch is False


def test_two_adapters_on_one_series_never_request_a_spurious_refetch():
    left = candidate(
        "alice",
        source_id="catalog",
        order_kind="monotonic",
        ordinal=1,
        adapter_id="adapter-a",
        support_suffix="alice",
    )
    right = candidate(
        "bob",
        source_id="catalog",
        order_kind="monotonic",
        ordinal=2,
        adapter_id="adapter-b",
        support_suffix="bob",
    )

    selection = select_same_source((left, right))

    assert len(selection.current) == 2
    assert selection.superseded_version_ids == ()
    assert selection.ambiguous_series == ()
    assert selection.requires_refetch is False


def test_monotonic_same_source_selects_newest_adapter_ordinal_not_arrival_order():
    newer = candidate(
        "bob",
        source_id="catalog",
        order_kind="monotonic",
        ordinal=2,
        provider_token="rev-b",
        recorded_from=MAY_1,
    )
    imported_old_last = candidate(
        "alice",
        source_id="catalog",
        order_kind="monotonic",
        ordinal=1,
        provider_token="rev-a",
        recorded_from=MAY_10,
    )

    selection = select_same_source((imported_old_last, newer))

    assert tuple(item.version.id for item in selection.current) == (newer.version.id,)
    assert selection.superseded_version_ids == (imported_old_last.version.id,)
    assert selection.ambiguous_series == ()


def test_list_order_and_recorded_time_do_not_break_unknown_order_ties():
    alice = candidate("alice", source_id="prd", recorded_from=MAY_10, support_suffix="alice")
    bob = candidate("bob", source_id="prd", recorded_from=MAY_1, support_suffix="bob")

    forward = select_same_source((alice, bob))
    reverse = select_same_source((bob, alice))

    assert {item.version.id for item in forward.current} == {alice.version.id, bob.version.id}
    assert forward.current == reverse.current
    assert forward.ambiguous_series == reverse.ambiguous_series
    assert forward.requires_refetch is True


def test_equality_only_tokens_are_never_sorted_as_versions():
    z_token = candidate(
        "alice",
        source_id="git",
        order_kind="equality_only",
        provider_token="zzz",
        support_suffix="z",
    )
    a_token = candidate(
        "bob",
        source_id="git",
        order_kind="equality_only",
        provider_token="aaa",
        support_suffix="a",
    )

    selection = select_same_source((z_token, a_token))

    assert {item.version.id for item in selection.current} == {z_token.version.id, a_token.version.id}
    assert selection.superseded_version_ids == ()
    assert selection.requires_refetch is True


def test_equal_monotonic_ordinal_with_different_claims_remains_ambiguous():
    alice = candidate("alice", source_id="catalog", order_kind="monotonic", ordinal=4, support_suffix="alice")
    bob = candidate("bob", source_id="catalog", order_kind="monotonic", ordinal=4, support_suffix="bob")

    selection = select_same_source((alice, bob))

    assert len(selection.current) == 2
    assert selection.requires_refetch is True


def test_exact_duplicate_version_is_idempotently_collapsed():
    alice = candidate("alice", source_id="catalog")

    selection = select_same_source((alice, alice))

    assert selection.current == (alice,)


def test_one_version_id_cannot_carry_divergent_identity_metadata():
    open_segment = candidate("alice", source_id="catalog", support_suffix="one")
    closed_segment = ConflictCandidate(
        assertion=open_segment.assertion,
        version=open_segment.version.replace(recorded_to=MAY_10),
        source_id="mirror",
        support_span_ids=("span-mirror-one",),
        order=open_segment.order,
    )

    assert closed_segment.version.id == open_segment.version.id

    with pytest.raises(ValueError, match=re.escape(open_segment.version.id)):
        select_same_source((open_segment, closed_segment))
    with pytest.raises(ValueError, match="divergent identity metadata"):
        build_conflict_sets((open_segment, closed_segment), cardinality="single")


def test_a_different_target_object_can_never_share_one_version_id():
    alice = candidate("alice", source_id="catalog")
    bob = candidate("bob", source_id="catalog")

    assert alice.version.id != bob.version.id
    with pytest.raises(ValueError, match="version does not belong"):
        ConflictCandidate(
            assertion=bob.assertion,
            version=alice.version,
            source_id="catalog",
            support_span_ids=("span-catalog-one",),
            order=alice.order,
        )


def test_one_version_id_from_two_sources_is_corroboration_not_a_rebinding():
    one = candidate("alice", source_id="catalog-a", support_suffix="one")
    two = candidate("alice", source_id="catalog-b", support_suffix="two")

    assert one.version.id == two.version.id

    selection = select_same_source((two, one))

    assert {item.source_id for item in selection.current} == {"catalog-a", "catalog-b"}
    assert selection.current == select_same_source((one, two)).current
    assert selection.superseded_version_ids == ()
    assert selection.requires_refetch is False


def test_independent_single_valued_sources_create_one_unresolved_conflict():
    alice = candidate("alice", source_id="backstage", support_suffix="catalog")
    bob = candidate("bob", source_id="accepted-prd", support_suffix="prd")

    conflicts = build_conflict_sets((bob, alice), cardinality="single")

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.resolution_status == "unresolved"
    assert conflict.assertion_version_ids == tuple(sorted((alice.version.id, bob.version.id)))
    assert conflict.support_span_ids == tuple(sorted(("span-backstage-catalog", "span-accepted-prd-prd")))
    assert conflict.valid_from == MAY_1
    assert conflict.valid_to is None


def test_multiple_cardinality_keeps_alternatives_without_a_false_conflict():
    alice = candidate("alice", source_id="catalog-a")
    bob = candidate("bob", source_id="catalog-b")

    assert build_conflict_sets((alice, bob), cardinality="multiple") == ()


def test_distinct_environment_scopes_do_not_conflict():
    production = candidate("alice", source_id="catalog-a", scope="service-a:production")
    staging = candidate("bob", source_id="catalog-b", scope="service-a:staging")

    assert build_conflict_sets((production, staging), cardinality="single") == ()


def test_explicit_nonoverlapping_intervals_do_not_conflict():
    alice = candidate("alice", source_id="catalog-a", valid_from=MAY_1, valid_to=MAY_5)
    bob = candidate("bob", source_id="catalog-b", valid_from=MAY_5, valid_to=MAY_10)

    assert build_conflict_sets((alice, bob), cardinality="single") == ()


def test_explicit_overlap_records_exact_half_open_intersection():
    alice = candidate("alice", source_id="catalog-a", valid_from=MAY_1, valid_to=MAY_10)
    bob = candidate("bob", source_id="catalog-b", valid_from=MAY_5, valid_to=JUNE_1)

    conflict = build_conflict_sets((alice, bob), cardinality="single")[0]

    assert conflict.resolution_status == "unresolved"
    assert conflict.valid_from == MAY_5
    assert conflict.valid_to == MAY_10


def test_coarse_effective_precision_can_never_prove_a_conflict_overlap():
    year_alice = candidate(
        "alice",
        source_id="catalog-a",
        valid_from=JAN_1,
        valid_to=NEXT_JAN_1,
        precision="year",
        support_suffix="alice",
    )
    instant_bob = candidate(
        "bob", source_id="catalog-b", valid_from=MAY_1, valid_to=JUNE_1, support_suffix="bob"
    )

    imprecise = build_conflict_sets((year_alice, instant_bob), cardinality="single")

    assert imprecise == build_conflict_sets((instant_bob, year_alice), cardinality="single")
    assert len(imprecise) == 1
    assert imprecise[0].resolution_status == "possible"
    assert imprecise[0].valid_from is imprecise[0].valid_to is None

    instant_alice = candidate(
        "alice",
        source_id="catalog-a",
        valid_from=JAN_1,
        valid_to=NEXT_JAN_1,
        support_suffix="alice",
    )
    exact = build_conflict_sets((instant_alice, instant_bob), cardinality="single")

    assert len(exact) == 1
    assert exact[0].resolution_status == "unresolved"
    assert (exact[0].valid_from, exact[0].valid_to) == (MAY_1, JUNE_1)


def test_unknown_effective_overlap_is_possible_without_an_invented_interval():
    alice = candidate(
        "alice",
        source_id="catalog-a",
        valid_from=None,
        validity_kind="unknown",
    )
    bob = candidate("bob", source_id="catalog-b")

    conflict = build_conflict_sets((alice, bob), cardinality="single")[0]

    assert conflict.resolution_status == "possible"
    assert conflict.valid_from is None
    assert conflict.valid_to is None


def test_atemporal_single_values_conflict_without_inventing_effective_bounds():
    alice = candidate(
        "alice",
        source_id="catalog-a",
        valid_from=None,
        validity_kind="atemporal",
    )
    bob = candidate(
        "bob",
        source_id="catalog-b",
        valid_from=None,
        validity_kind="atemporal",
    )

    conflict = build_conflict_sets((alice, bob), cardinality="single")[0]

    assert conflict.resolution_status == "unresolved"
    assert conflict.valid_from is conflict.valid_to is None


def test_same_target_from_independent_sources_is_support_not_conflict():
    one = candidate("alice", source_id="catalog-a", support_suffix="one")
    two = candidate("alice", source_id="catalog-b", support_suffix="two")

    assert one.version.id == two.version.id
    assert build_conflict_sets((one, two), cardinality="single") == ()


def test_corroborated_alternative_and_a_rival_form_one_conflict_with_merged_support():
    alice_one = candidate("alice", source_id="catalog-a", support_suffix="one")
    alice_two = candidate("alice", source_id="catalog-b", support_suffix="two")
    bob = candidate("bob", source_id="catalog-c", support_suffix="bob")

    conflicts = build_conflict_sets((alice_one, bob, alice_two), cardinality="single")

    assert conflicts == build_conflict_sets((alice_two, alice_one, bob), cardinality="single")
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.resolution_status == "unresolved"
    assert conflict.assertion_version_ids == tuple(sorted((alice_one.version.id, bob.version.id)))
    assert conflict.support_span_ids == tuple(
        sorted(("span-catalog-a-one", "span-catalog-b-two", "span-catalog-c-bob"))
    )


def test_pairwise_conflicts_keep_corroborating_support_in_one_deterministic_alternative():
    alice_one = candidate("alice", source_id="s1", valid_to=MAY_5, support_suffix="one")
    alice_two = candidate("alice", source_id="s2", valid_to=MAY_5, support_suffix="two")
    bob = candidate("bob", source_id="s3", valid_from=MAY_5, valid_to=MAY_10, support_suffix="bob")
    carol = candidate("carol", source_id="s4", valid_to=JUNE_1, support_suffix="carol")

    forward = build_conflict_sets((alice_one, alice_two, bob, carol), cardinality="single")
    reverse = build_conflict_sets((carol, bob, alice_two, alice_one), cardinality="single")

    assert forward == reverse
    assert len(forward) == 2
    with_alice = [item for item in forward if alice_one.version.id in item.assertion_version_ids]
    assert len(with_alice) == 1
    assert with_alice[0].support_span_ids == tuple(sorted(("span-s1-one", "span-s2-two", "span-s4-carol")))
    assert (with_alice[0].valid_from, with_alice[0].valid_to) == (MAY_1, MAY_5)
    assert with_alice[0].resolution_status == "unresolved"


def test_conflict_identity_is_deterministic_under_input_reordering():
    alice = candidate("alice", source_id="catalog-a")
    bob = candidate("bob", source_id="catalog-b")
    carol = candidate("carol", source_id="catalog-c")

    forward = build_conflict_sets((alice, bob, carol), cardinality="single")
    reverse = build_conflict_sets((carol, bob, alice), cardinality="single")

    assert forward == reverse
    assert len(forward[0].assertion_version_ids) == 3


def fixture_rows():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def utc_instant(value):
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), value
    return parsed


def test_temporal_event_fixture_rows_match_one_of_three_declared_shapes():
    for row in fixture_rows():
        keys = set(row)
        if "suppression" in row:
            assert keys == SUPPRESSION_KEYS, row["case"]
            assert set(row["suppression"]) == {"view_applicability", "reason", "epoch"}
            assert row["suppression"]["view_applicability"] in {"current_only", "all_history"}
            assert type(row["suppression"]["epoch"]) is int
        elif "restoration_barrier" in row:
            assert keys == BARRIER_KEYS, row["case"]
            assert row["restoration_barrier"].strip()
        else:
            assert CLAIM_KEYS <= keys <= CLAIM_KEYS | CLAIM_OPTIONAL_KEYS, row["case"]
            assert set(row["claim"]) == {"predicate", "object"}
            assert row["precision"] in PRECISIONS, row["case"]
            assert (row["precision"] == "instant") == (row["valid_from"] is not None), row["case"]
            assert row.get("source_precision", "unknown") in PRECISIONS
        for key in INSTANT_KEYS:
            if row.get(key) is not None:
                utc_instant(row[key])
        if row.get("valid_from") is not None and row.get("valid_to") is not None:
            assert utc_instant(row["valid_from"]) < utc_instant(row["valid_to"]), row["case"]
        assert row["source_id"].strip()


def test_temporal_event_fixture_declares_ordering_metadata_where_the_scenario_needs_it():
    for row in fixture_rows():
        if "suppression" in row:
            assert "provider_order" not in row, row["case"]
            continue
        ordering = row["provider_order"]
        assert set(ordering) == {"adapter", "version", "kind", "ordinal", "token"}, row["case"]
        assert ordering["kind"] in ORDER_KINDS, row["case"]
        assert (type(ordering["ordinal"]) is int) == (ordering["kind"] == "monotonic"), row["case"]
        if ordering["kind"] == "equality_only":
            assert isinstance(ordering["token"], str) and ordering["token"].strip(), row["case"]
        if ordering["kind"] == "unknown":
            assert ordering["token"] is None, row["case"]
        assert ordering["adapter"].strip() and ordering["version"].strip()


def test_temporal_event_fixture_covers_every_named_scenario_without_orphan_rows():
    assert len(SCENARIO_CASES) == 9
    required = {case for cases in SCENARIO_CASES.values() for case in cases}

    assert {row["case"] for row in fixture_rows()} == required


def test_temporal_event_fixture_separates_equal_tokens_from_equal_source_timestamps():
    etag_pair = [row for row in fixture_rows() if row["case"] == "equal_order_different_bytes"]
    timestamp_pair = [row for row in fixture_rows() if row["case"] == "equal_timestamp_different_bytes"]

    for pair in (etag_pair, timestamp_pair):
        assert len(pair) == 2
        assert len({row["content_hash"] for row in pair}) == 2
        assert {row["provider_order"]["kind"] for row in pair} == {"equality_only"}
        assert len({row["provider_order"]["token"] for row in pair}) == 1
    assert all(row.get("source_updated_at") is None for row in etag_pair)
    assert len({row["source_updated_at"] for row in timestamp_pair}) == 1
    assert timestamp_pair[0]["source_updated_at"] is not None


def test_candidate_rejects_mismatched_version_and_duplicate_support():
    valid = candidate("alice", source_id="catalog")
    with pytest.raises(ValueError, match="version does not belong"):
        ConflictCandidate(
            assertion=valid.assertion.replace(object_id="bob"),
            version=valid.version,
            source_id="catalog",
            support_span_ids=("span-a",),
            order=valid.order,
        )
    with pytest.raises(ValueError, match="support spans"):
        ConflictCandidate(
            assertion=valid.assertion,
            version=valid.version,
            source_id="catalog",
            support_span_ids=("span-a", "span-a"),
            order=valid.order,
        )


# --- Integration part 2: supersession that a correction publication can act on ---


def test_recorded_correction_supersession_names_each_version_once_per_series():
    """One source, two support groups, one version: one closure, not two."""
    first = candidate(
        "alice", source_id="catalog", order_kind="monotonic", ordinal=1, support_suffix="direct"
    )
    mirrored = candidate(
        "alice", source_id="catalog", order_kind="monotonic", ordinal=1, support_suffix="inferred"
    )
    newer = candidate("bob", source_id="catalog", order_kind="monotonic", ordinal=2, support_suffix="bob")

    selection = select_same_source((first, mirrored, newer))

    assert first.version.id == mirrored.version.id
    assert selection.superseded_version_ids == (first.version.id,)
    assert fully_superseded_version_ids(selection) == (first.version.id,)


def test_recorded_correction_supersession_is_keyed_by_series_not_globally():
    """A version superseded in one series but current in another is never closed."""
    superseded_here = candidate(
        "alice", source_id="catalog-a", order_kind="monotonic", ordinal=1, support_suffix="a"
    )
    newer = candidate("bob", source_id="catalog-a", order_kind="monotonic", ordinal=2, support_suffix="bob")
    current_there = candidate(
        "alice", source_id="catalog-b", order_kind="monotonic", ordinal=1, support_suffix="b"
    )

    selection = select_same_source((superseded_here, newer, current_there))

    assert selection.superseded_version_ids == (superseded_here.version.id,)
    assert {item.version.id for item in selection.current} == {
        newer.version.id,
        current_there.version.id,
    }
    by_series = dict(selection.superseded_by_series)
    assert len(by_series) == 1
    assert next(iter(by_series.values())) == (superseded_here.version.id,)
    assert '"catalog-a"' in next(iter(by_series))
    # Still current under catalog-b, so nothing may close it.
    assert fully_superseded_version_ids(selection) == ()
