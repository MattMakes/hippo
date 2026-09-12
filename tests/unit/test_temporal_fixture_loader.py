"""Chronological JSONL loading of the Task 5A temporal fixture, end to end.

Every scenario in plan section 7 step 3 is exercised through the loader and the
part 1/part 2 APIs, never through a hand-built world: the fixture's own parsed
instants and adapter ordering metadata are what drive publication and closure.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hippo.access import EVERYTHING, Access
from hippo.evals.rag_all_temporal import (
    DEFAULT_SCOPE_KEY,
    TemporalFixtureError,
    load_temporal_events,
    read_temporal_events,
)
from hippo.knowledge import model as k
from hippo.knowledge.conflicts import build_conflict_sets, compare_orders, select_same_source
from hippo.knowledge.temporal import TemporalInputs, select_history, serialize_temporal_evidence
from hippo.store.snapshots import SnapshotUnavailable
from tests.unit.test_store_knowledge import reader

FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/rag_all/temporal_events.jsonl"

APRIL_15 = datetime(2026, 4, 15, tzinfo=UTC)
MAY_2 = datetime(2026, 5, 2, tzinfo=UTC)
BEFORE_CORRECTION = datetime(2026, 5, 5, tzinfo=UTC)
AFTER_CORRECTION = datetime(2026, 5, 12, 12, tzinfo=UTC)
BEFORE_RESTATEMENT = datetime(2026, 5, 13, 3, tzinfo=UTC)
AFTER_IMPORT = datetime(2026, 5, 13, 12, tzinfo=UTC)
AFTER_CLAIMS = datetime(2026, 5, 14, 12, tzinfo=UTC)
AFTER_TOMBSTONE = datetime(2026, 5, 15, 12, tzinfo=UTC)
AFTER_PURGE = datetime(2026, 5, 16, 12, tzinfo=UTC)
AFTER_BOTH_PURGES = datetime(2026, 5, 16, 23, tzinfo=UTC)
AFTER_EVERYTHING = datetime(2026, 5, 18, tzinfo=UTC)
MAY_20 = datetime(2026, 5, 20, tzinfo=UTC)
REQUEST_CUTOFF = datetime(2026, 6, 1, tzinfo=UTC)


def load(store, *, at=AFTER_EVERYTHING):
    return load_temporal_events(store, FIXTURE, clock=lambda: at)


def row_for(case):
    """One shipped row by its case label, so a probe file never pins a line number."""
    for line in FIXTURE.read_text().splitlines():
        row = json.loads(line)
        if row["case"] == case:
            return row
    raise AssertionError(f"{case!r} is not a fixture case")


def written(tmp_path, *rows, name="probe.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def history(load_result, store, *, valid_at, known_at, access=EVERYTHING):
    return select_history(
        store,
        workspace_id=load_result.workspace_id,
        access=access,
        selector=k.AsOfSelector(valid_at=valid_at, known_at=known_at),
        request_cutoff=REQUEST_CUTOFF,
        clock=lambda: REQUEST_CUTOFF,
    )


def proven_versions(selection):
    return {item.record_id for item in selection.proven if item.record_kind == "AssertionVersion"}


def contextual_versions(selection):
    return {item.record_id for item in selection.contextual if item.record_kind == "AssertionVersion"}


# --- Parsing: explicit instants only, never a wall clock -------------------------


def test_every_row_instant_is_parsed_as_an_aware_utc_value_in_recorded_order():
    events = read_temporal_events(FIXTURE)

    assert len(events) == 16
    assert [event.recorded_from for event in events] == sorted(event.recorded_from for event in events)
    for event in events:
        assert event.recorded_from.tzinfo is not None
        assert event.recorded_from.utcoffset() == timedelta(0)
        for moment in (event.valid_from, event.valid_to, event.source_updated_at):
            assert moment is None or moment.utcoffset() == timedelta(0)
    # The provider's own text and declared zone survive parsing.
    correction = next(event for event in events if event.case == "backdated_correction")
    assert correction.source_timestamp_original == "2026-04-01T00:00:00Z"
    assert correction.source_timezone == "UTC"
    assert correction.precision == "instant"


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"recorded_from": "2026-05-01T00:00:00"}, "timezone"),
        ({"recorded_from": None}, "recorded_from"),
        ({"valid_from": "2026-04-01T00:00:00"}, "timezone"),
        ({"recorded_from": "not-a-date"}, "ISO"),
    ],
)
def test_a_naive_or_missing_instant_is_refused_instead_of_defaulted(tmp_path, row, message):
    path = written(tmp_path, row_for("may_owner_alice") | row)

    with pytest.raises(TemporalFixtureError, match=message):
        read_temporal_events(path)


@pytest.mark.parametrize(
    ("declared", "label"),
    [
        ("2026-04-01T02:00:00+02:00", "+02:00"),
        ("2026-04-01T02:00:00+0200", "+02:00"),
        ("2026-03-31T19:00:00-05:00", "-05:00"),
        ("2026-04-01T00:00:00Z", "UTC"),
    ],
)
def test_a_declared_offset_survives_while_the_computed_instant_is_utc(tmp_path, declared, label):
    """Section 1: the provider's declared zone is preserved, never flattened to UTC."""
    path = written(tmp_path, row_for("may_owner_alice") | {"valid_from": declared})

    (event,) = read_temporal_events(path)

    assert event.valid_from == datetime(2026, 4, 1, tzinfo=UTC)
    assert event.valid_from.utcoffset() == timedelta(0)
    assert event.source_timestamp_original == declared
    assert event.source_timezone == label


def _suppression(**changes):
    row = row_for("ordinary_tombstone")
    return row | {"suppression": row["suppression"] | changes}


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (_suppression(reason="policy_change"), "reason"),
        (_suppression(view_applicability="everything"), "view applicability"),
        (row_for("ordinary_tombstone") | {"suppression": {"reason": "tombstone", "epoch": 5}}, "epoch"),
        ({key: value for key, value in row_for("may_owner_alice").items() if key != "precision"}, "fields"),
        (row_for("may_owner_alice") | {"claim": {"predicate": "OWNED_BY"}}, "predicate and an object"),
    ],
)
def test_every_malformed_row_is_a_fixture_error_naming_its_row_index(tmp_path, row, message):
    """F3: no malformed shape may escape as a KeyError or a pydantic ValidationError."""
    path = written(tmp_path, row)

    with pytest.raises(TemporalFixtureError, match=message) as raised:
        read_temporal_events(path)

    assert "row 0" in str(raised.value)


def test_a_row_the_knowledge_model_refuses_is_reported_as_a_fixture_error(store, tmp_path):
    """The model's own refusal names the row that caused it, not an opaque traceback."""
    path = written(tmp_path, row_for("may_owner_alice") | {"content_hash": 5})

    with pytest.raises(TemporalFixtureError, match="row 0"):
        load_temporal_events(store, path, clock=lambda: AFTER_EVERYTHING)


def _tied(ordinal, *, recorded="2026-05-17T00:00:00Z"):
    row = row_for("may_owner_alice")
    return row | {
        "case": f"tied_{ordinal}",
        "recorded_from": recorded,
        "provider_order": row["provider_order"] | {"ordinal": ordinal, "token": f"rev-tie-{ordinal}"},
        "claim": {"predicate": "OWNED_BY", "object": f"Tie {ordinal}"},
    }


@pytest.mark.parametrize("ordinals", [(1, 2), (2, 1)])
def test_one_instant_twice_in_a_series_is_ordered_by_ordinal_and_never_drops_a_closure(
    store, tmp_path, ordinals
):
    """F4: the ordering is the ordinal's, so an impossible closure is loud in both file orders."""
    path = written(tmp_path, *(_tied(ordinal) for ordinal in ordinals))

    assert [event.case for event in read_temporal_events(path)] == ["tied_1", "tied_2"]
    with pytest.raises(TemporalFixtureError, match="2026-05-17"):
        load_temporal_events(store, path, clock=lambda: AFTER_EVERYTHING)


def test_two_rows_tying_on_both_instant_and_ordinal_are_refused_as_ambiguous(tmp_path):
    first, second = _tied(1), _tied(1) | {"case": "tied_again"}
    second["provider_order"] = second["provider_order"] | {"token": "rev-tie-other"}

    with pytest.raises(TemporalFixtureError, match="ordinal"):
        read_temporal_events(written(tmp_path, first, second))


def test_the_loader_reads_no_wall_clock_anywhere():
    """The caller supplies the clock; the file supplies every recorded instant."""
    from hippo.evals import rag_all_temporal

    source = Path(rag_all_temporal.__file__).read_text()

    assert "datetime.now" not in source
    assert "utc_now" not in source
    assert "\nfrom datetime import" in source or "import datetime" in source


def test_the_caller_clock_bounds_which_recorded_events_are_applied(store):
    result = load(store, at=AFTER_CORRECTION)

    assert [event.case for event in result.deferred] == [
        "old_imported_last",
        "equal_order_different_bytes",
        "equal_order_different_bytes",
        "equal_timestamp_different_bytes",
        "equal_timestamp_different_bytes",
        "restated_new_state",
        "unknown_date",
        "environment_collision",
        "independent_alternative",
        "ordinary_tombstone",
        "purged_history",
        "purged_proven_history",
    ]
    assert [event.case for event in result.applied] == [
        "may_owner_alice",
        "may_owner_bob",
        "backdated_correction",
    ]
    # A barrier row is neither applied nor deferred: it is a file-level declaration.
    assert [event.case for event in result.declarations] == ["explicit_restoration"]


def test_a_barrier_row_is_a_declaration_the_clock_does_not_bound(store):
    """The carve-out convention 5 declares, proved where a reader would trip on it."""
    result = load(store, at=AFTER_TOMBSTONE)
    declared = result.barrier("explicit_restoration")
    tombstone = store._knowledge_get("Suppression", result.suppressions["ordinary_tombstone"])

    assert declared.recorded_from > AFTER_TOMBSTONE
    # A Suppression is immutable, so the barrier its source declares anywhere in the
    # file is the one it was always going to carry - the clock never bounded it.
    assert tombstone.restoration_barrier == "confirmed:9"
    assert declared in result.declarations
    assert declared not in result.applied + result.deferred


# --- Scenario 1: the May ownership correction -----------------------------------


def test_may_ownership_correction_shows_the_original_before_and_the_correction_after(store):
    result = load(store, at=AFTER_CORRECTION)
    original = result.claim("may_owner_alice")
    corrected = result.claim("backdated_correction")

    before = history(result, store, valid_at=APRIL_15, known_at=BEFORE_CORRECTION)
    after = history(result, store, valid_at=APRIL_15, known_at=AFTER_CORRECTION)

    assert proven_versions(before) == {original.version.id}
    assert proven_versions(after) == {corrected.version.id}
    # The correction is an append-only publication: the prior segment is closed,
    # never rewritten, and the corrected segment is the newly open one.
    assert store._knowledge_get("AssertionVersion", original.version.id).recorded_to is not None
    assert store._knowledge_get("AssertionVersion", corrected.version.id).recorded_to is None
    assert corrected.closed_version_ids == (result.claim("may_owner_bob").version.id,)
    assert result.claim("may_owner_bob").closed_version_ids == (original.version.id,)


def test_the_corrected_segment_keeps_its_bounded_effective_interval(store):
    result = load(store, at=AFTER_CORRECTION)
    corrected = result.claim("backdated_correction")

    inside = history(result, store, valid_at=APRIL_15, known_at=AFTER_CORRECTION)
    outside = history(result, store, valid_at=MAY_2, known_at=AFTER_CORRECTION)

    assert corrected.version.valid_from == datetime(2026, 4, 1, tzinfo=UTC)
    assert corrected.version.valid_to == datetime(2026, 5, 1, tzinfo=UTC)
    assert corrected.version.id in proven_versions(inside)
    assert corrected.version.id not in proven_versions(outside)


# --- Scenario 2: an old import arriving last ------------------------------------


def test_an_old_import_arriving_last_supersedes_nothing(store):
    result = load(store, at=AFTER_IMPORT)
    imported = result.claim("old_imported_last")
    corrected = result.claim("backdated_correction")
    restated = result.claim("restated_new_state")

    selection = select_same_source(result.candidates)

    assert imported.closed_version_ids == ()
    assert compare_orders(imported.candidate.order, corrected.candidate.order) == "older"
    assert compare_orders(imported.candidate.order, restated.candidate.order) == "older"
    assert restated.version.id in {item.version.id for item in selection.current}
    assert imported.version.id not in {item.version.id for item in selection.current}
    assert store._knowledge_get("AssertionVersion", restated.version.id).recorded_to is None


def test_the_replay_ends_with_the_highest_ordinal_as_the_catalogs_only_proven_claim(store):
    """Closure follows the adapter ordinal alone, so arrival order decides nothing.

    The re-import arrives last and stays recorded-open until a higher ordinal
    publishes; the ordinal-4 restatement then closes every lower-ordinal open
    segment of the series in one publication, including the corrected historical
    one. Both closed segments stay queryable at a cutoff before their closure.
    """
    result = load(store, at=AFTER_IMPORT)
    imported = result.claim("old_imported_last")
    corrected = result.claim("backdated_correction")
    restated = result.claim("restated_new_state")
    catalog = {item.version.id for item in result.claims if item.event.source_name == "catalog"}

    after = history(result, store, valid_at=MAY_20, known_at=AFTER_IMPORT)
    before = history(result, store, valid_at=APRIL_15, known_at=BEFORE_RESTATEMENT)

    assert restated.closed_version_ids == tuple(sorted((corrected.version.id, imported.version.id)))
    assert proven_versions(after) & catalog == {restated.version.id}
    assert {corrected.version.id, imported.version.id} <= proven_versions(before)
    assert store._knowledge_get("AssertionVersion", imported.version.id).recorded_to == datetime(
        2026, 5, 13, 6, tzinfo=UTC
    )


# --- Scenario 3: an equal ordering datum with different bytes -------------------


@pytest.mark.parametrize("case", ["equal_order_different_bytes", "equal_timestamp_different_bytes"])
def test_an_equal_ordering_datum_with_different_bytes_stays_ambiguous(store, case):
    result = load(store, at=AFTER_IMPORT)
    pair = result.claims_for(case)

    selection = select_same_source([item.candidate for item in pair])

    assert len(pair) == 2
    assert {item.event.content_hash for item in pair} == {f"hash-{name}" for name in _bytes_of(case)}
    assert selection.requires_refetch
    assert selection.superseded_version_ids == ()
    assert {item.version.id for item in selection.current} == {item.version.id for item in pair}
    assert all(item.closed_version_ids == () for item in pair)
    assert all(store._knowledge_get("AssertionVersion", item.version.id).recorded_to is None for item in pair)


def _bytes_of(case):
    return ("one", "two") if case == "equal_order_different_bytes" else ("three", "four")


# --- Scenario 4: an unknown date stays contextual --------------------------------


def test_an_unknown_date_is_contextual_and_never_time_proven(store):
    result = load(store, at=AFTER_CLAIMS)
    undated = result.claim("unknown_date")

    selection = history(result, store, valid_at=MAY_2, known_at=AFTER_CLAIMS)

    assert undated.version.validity_kind == "unknown"
    assert undated.version.valid_from is None
    assert undated.version.temporal_precision == "unknown"
    assert undated.version.id in contextual_versions(selection)
    assert undated.version.id not in proven_versions(selection)
    reason = next(item for item in selection.contextual if item.record_id == undated.version.id)
    assert reason.match.reason == "effective_unknown"


def test_an_unknown_date_serializes_as_null_rather_than_hippos_own_clock(store):
    """No source declared an instant for this row, so no field may report one."""
    result = load(store, at=AFTER_CLAIMS)
    undated = result.claim("unknown_date")
    observations = [
        row for row in store._knowledge_rows("ObjectObservation") if row.revision_id == undated.revision_id
    ]

    evidence = serialize_temporal_evidence(TemporalInputs(record=undated.version))

    assert evidence["source_timestamp_original"] is None
    assert evidence["source_timezone"] is None
    assert evidence["valid_from"] is None
    assert evidence["temporal_precision"] == "unknown"
    assert evidence["validity_kind"] == "unknown"
    # The recorded instant is still reported as what it is: a recorded instant.
    assert evidence["recorded_from"] == "2026-05-14T00:00:00Z"
    assert observations
    assert all(row.source_timestamp_original is None and row.source_timezone is None for row in observations)
    # A dated row keeps reporting the text and zone its provider declared.
    dated = serialize_temporal_evidence(TemporalInputs(record=result.claim("backdated_correction").version))
    assert (dated["source_timestamp_original"], dated["source_timezone"]) == ("2026-04-01T00:00:00Z", "UTC")


# --- Scenario 5: an environment collision is not a conflict ---------------------


def test_distinct_environment_scopes_never_form_one_conflict(store):
    result = load(store, at=AFTER_CLAIMS)
    staging = result.claim("environment_collision")
    production = result.claim("independent_alternative")

    conflicts = build_conflict_sets(result.current_candidates, cardinality="single")

    assert staging.assertion.scope_key == "service-a:staging"
    assert production.assertion.scope_key == DEFAULT_SCOPE_KEY == "service-a:production"
    assert conflicts
    assert not any(staging.version.id in item.assertion_version_ids for item in conflicts)
    assert all(item.scope_key == DEFAULT_SCOPE_KEY for item in conflicts)


# --- Scenario 6: independent sources corroborate rather than conflict -----------


def test_independent_source_alternatives_support_each_other(store):
    result = load(store, at=AFTER_CLAIMS)
    accepted = result.claim("independent_alternative")
    undated = result.claim("unknown_date")
    pair = (accepted.candidate, undated.candidate)

    selection = select_same_source(pair)

    assert accepted.event.source_name != undated.event.source_name
    assert accepted.assertion.id == undated.assertion.id  # one claim, two sources
    assert selection.superseded_version_ids == ()
    assert selection.ambiguous_series == ()
    assert build_conflict_sets(pair, cardinality="single") == ()
    assert build_conflict_sets(pair, cardinality="multiple") == ()


# --- Scenario 7: an ordinary tombstone keeps history ----------------------------


def test_an_ordinary_tombstone_hides_the_current_view_and_keeps_history(store):
    result = load(store, at=AFTER_TOMBSTONE)
    corrected = result.claim("backdated_correction")
    restated = result.claim("restated_new_state")
    suppression = store._knowledge_get("Suppression", result.suppressions["ordinary_tombstone"])

    selection = history(result, store, valid_at=MAY_20, known_at=AFTER_TOMBSTONE)
    pinned = history(result, store, valid_at=APRIL_15, known_at=BEFORE_RESTATEMENT)

    assert suppression.view_applicability == "current_only"
    assert suppression.reason == "tombstone"
    assert suppression.epoch == 5
    # The catalog's open segment and, at a cutoff before its closure, the corrected
    # historical one both remain proven history under a current-only tombstone.
    assert restated.version.id in proven_versions(selection)
    assert corrected.version.id in proven_versions(pinned)
    assert restated.span_id not in _current_span_ids(store, result)
    assert corrected.span_id not in _current_span_ids(store, result)


def _current_span_ids(store, result):
    from hippo.knowledge.access import EvidenceAccess

    engine = EvidenceAccess(store, result.workspace_id, EVERYTHING)
    return engine.build().span_ids


# --- Scenario 8: an all-history purge denies even a pinned manifest -------------


def test_an_all_history_purge_denies_the_retained_history_a_tombstone_would_keep(store):
    result = load(store, at=AFTER_TOMBSTONE)
    undated = result.claim("unknown_date")
    before = history(result, store, valid_at=MAY_2, known_at=AFTER_TOMBSTONE)
    assert undated.version.id in contextual_versions(before)
    assert undated.revision_id in before.broad.revision_ids

    purged = load(store, at=AFTER_PURGE)
    after = history(purged, store, valid_at=MAY_2, known_at=AFTER_PURGE)

    suppression = store._knowledge_get("Suppression", purged.suppressions["purged_history"])
    assert suppression.reason == "purge"
    assert suppression.view_applicability == "all_history"
    assert suppression.epoch == 6
    # A purge denies even historical mode, where the ordinary tombstone did not.
    assert undated.version.id not in contextual_versions(after) | proven_versions(after)
    assert undated.revision_id not in after.broad.revision_ids
    assert result.claim("restated_new_state").version.id in proven_versions(
        history(purged, store, valid_at=MAY_20, known_at=AFTER_PURGE)
    )


def test_an_all_history_purge_of_a_proven_source_answers_with_purge_markers(store):
    """The other half of the section 4 purge contract: markers, and only to a prover.

    The contextual purge above can never reach markers, because a contextual row's
    revision never enters a manifest. This one purges a source whose claim is
    time-proven, so its revision is in the pinned manifest the markers describe.
    """
    result = load(store, at=AFTER_PURGE)
    accepted = result.claim("independent_alternative")
    pinned = history(result, store, valid_at=MAY_2, known_at=AFTER_PURGE)
    assert accepted.revision_id in pinned.manifest.revision_ids

    purged = load(store, at=AFTER_BOTH_PURGES)
    suppression = store._knowledge_get("Suppression", purged.suppressions["purged_proven_history"])
    principal = reader(store, purged.workspace_id, "bystander")
    revoked = reader(store, purged.workspace_id, "revoked")
    store.update_knowledge(
        k.WorkspaceMembership(
            workspace_id=purged.workspace_id,
            principal_id=revoked,
            enabled=False,
            mapping_authority="reviewed",
            policy_epoch=3,
        )
    )

    assert (suppression.view_applicability, suppression.reason, suppression.epoch) == (
        "all_history",
        "purge",
        7,
    )
    for audience in (EVERYTHING, Access(user_id=principal)):
        markers = store.purged_history_evidence(
            pinned.manifest.id, workspace_id=purged.workspace_id, access=audience
        )
        assert [(item.target_kind, item.target_id, item.code) for item in markers] == [
            ("revision", accepted.revision_id, "evidence_purged")
        ]
        assert not any(hasattr(item, "text") for item in markers)
    # A reader who cannot prove what is left of the manifest is told nothing at all.
    with pytest.raises(SnapshotUnavailable):
        store.purged_history_evidence(
            pinned.manifest.id, workspace_id=purged.workspace_id, access=Access(user_id=revoked)
        )
    # The purged claim is gone from the proof it was proven in.
    after = history(purged, store, valid_at=MAY_2, known_at=AFTER_BOTH_PURGES)
    assert accepted.version.id not in proven_versions(after) | contextual_versions(after)
    assert accepted.revision_id not in after.broad.revision_ids


# --- Scenario 9: the explicit restoration barrier -------------------------------


def test_the_explicit_restoration_barrier_is_what_a_restoration_must_satisfy(store):
    result = load(store, at=AFTER_EVERYTHING)
    barrier = result.barrier("explicit_restoration")
    tombstone = store._knowledge_get("Suppression", result.suppressions["ordinary_tombstone"])
    imported = result.claim("old_imported_last")

    assert barrier.restoration_barrier == "confirmed:9"
    assert tombstone.restoration_barrier == "confirmed:9"
    assert result.barriers[barrier.source_name] == "confirmed:9"
    # An ordinary later arrival from the same source is older than the confirmed
    # restoration, so re-import can never stand in for it.
    assert compare_orders(imported.candidate.order, barrier.order) == "older"
    assert store._knowledge_get("Generation", result.claim("may_owner_alice").generation_id) is not None
    assert "explicit_restoration" not in {item.event.case for item in result.claims}


# --- Retry and durability --------------------------------------------------------


def test_loading_the_same_fixture_twice_writes_nothing_new(store):
    first = load(store)
    before = _knowledge_snapshot(store)

    second = load(store)

    assert _knowledge_snapshot(store) == before
    assert [item.version.id for item in second.claims] == [item.version.id for item in first.claims]
    assert second.source_ids == first.source_ids
    assert second.suppressions == first.suppressions
    assert all(item.closed_version_ids == () for item in second.claims)


def _knowledge_snapshot(store):
    kinds = (
        "Generation",
        "GenerationMember",
        "GenerationEvidenceMember",
        "AssertionVersion",
        "AssertionSupport",
        "ObjectObservation",
        "ArtifactRevision",
        "EvidenceSpan",
        "Suppression",
        "IndexEvent",
        "KnowledgeObject",
        "Assertion",
    )
    return {kind: sorted(repr(row) for row in store._knowledge_rows(kind)) for kind in kinds}


def test_loaded_history_survives_a_ladybug_close_and_reopen(tmp_path):
    from hippo.store.ladybug import LadybugStore

    path = tmp_path / "temporal.lbug"
    store = LadybugStore(path)
    try:
        result = load(store)
        before = history(result, store, valid_at=APRIL_15, known_at=AFTER_CORRECTION)
        proven = proven_versions(before)
    finally:
        store.close()

    reopened = LadybugStore(path)
    try:
        after = history(result, reopened, valid_at=APRIL_15, known_at=AFTER_CORRECTION)
        assert proven_versions(after) == proven == {result.claim("backdated_correction").version.id}
        assert reopened._knowledge_get("Generation", result.claim("may_owner_bob").generation_id).status in {
            "active",
            "retired",
        }
        # A reopened store reloads the same fixture as an exact retry.
        again = load(reopened)
        assert [item.version.id for item in again.claims] == [item.version.id for item in result.claims]
    finally:
        reopened.close()
