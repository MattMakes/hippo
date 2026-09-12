"""Pure bitemporal selector predicates over already-authorized evidence.

This module does not select generations or grant access. Callers must first hold
an authorization/snapshot proof, then use these predicates to narrow its IDs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, TypeAlias

from . import model as k
from .access import (
    AuthorizationChanged,
    AuthorizedEvidence,
    EvidenceAccess,
    EvidenceSelection,
    utc_now,
)
from .identity import canonical_json

TemporalDisposition: TypeAlias = Literal["proven", "contextual", "excluded"]
TemporalReason: TypeAlias = Literal[
    "effective_match",
    "recorded_match",
    "effective_unknown",
    "effective_imprecise",
    "recorded_after_cutoff",
    "recorded_closed",
    "effective_outside",
    "change_match",
    "change_outside",
    "change_clock_unknown",
    "atemporal_match",
]
KnownAtSource: TypeAlias = Literal["explicit", "inherited", "latest"]
SourcePrecision: TypeAlias = Literal["instant", "second", "minute", "day", "month", "year", "unknown"]


def _utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone aware")
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class _HalfOpen:
    """Half-open `[start, end)` arithmetic where a missing end is open-ended."""

    start: datetime
    end: datetime | None

    def __post_init__(self):
        if self.end is not None and self.end <= self.start:
            raise ValueError("A half-open span must have positive extent")

    @classmethod
    def requested(cls, interval: k.TimeInterval) -> _HalfOpen:
        return cls(interval.start, interval.end)

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment and (self.end is None or moment < self.end)

    def overlaps(self, other: _HalfOpen) -> bool:
        return (other.end is None or self.start < other.end) and (self.end is None or other.start < self.end)

    def covers(self, other: _HalfOpen) -> bool:
        return self.start <= other.start and (
            self.end is None or (other.end is not None and other.end <= self.end)
        )

    def intersect(self, other: _HalfOpen) -> _HalfOpen | None:
        start = max(self.start, other.start)
        ends = [end for end in (self.end, other.end) if end is not None]
        end = min(ends) if ends else None
        if end is not None and end <= start:
            return None
        return _HalfOpen(start, end)


@dataclass(frozen=True)
class ResolvedTemporalSelector:
    selector: k.CurrentSelector | k.AsOfSelector | k.DuringSelector | k.ChangesSelector | k.AtemporalSelector
    known_at: datetime
    known_at_source: KnownAtSource
    latest_known_at: datetime
    inherited_from: k.CompareSelector | None = None
    selector_json: str = field(init=False, default="")

    def __post_init__(self):
        if isinstance(self.selector, k.CompareSelector):
            raise TypeError("A resolved selector represents one comparison side")
        object.__setattr__(self, "known_at", _utc(self.known_at, field="Known-at cutoff"))
        object.__setattr__(
            self, "latest_known_at", _utc(self.latest_known_at, field="Latest knowledge cutoff")
        )
        if self.known_at_source not in {"explicit", "inherited", "latest"}:
            raise ValueError("Unknown knowledge-cutoff origin")
        if self.known_at > self.latest_known_at:
            raise ValueError("Knowledge cutoff is after latest available knowledge")
        explicit = getattr(self.selector, "known_at", None)
        if explicit is not None:
            if _utc(explicit, field="Explicit knowledge cutoff") != self.known_at:
                raise ValueError("Resolved knowledge cutoff differs from explicit selector cutoff")
            if self.known_at_source != "explicit":
                raise ValueError("Knowledge-cutoff origin contradicts explicit selector cutoff")
        elif self.known_at_source == "explicit":
            raise ValueError("An explicit knowledge-cutoff origin requires a selector cutoff")
        # A `latest` label claims the injected cutoff was used verbatim, and an
        # `inherited` one claims a comparison parent supplied it. Both are checkable,
        # so neither may be asserted by a caller the record itself contradicts.
        if self.known_at_source == "latest" and self.known_at != self.latest_known_at:
            raise ValueError("A latest knowledge cutoff must equal the latest available knowledge")
        if self.known_at_source == "inherited":
            parent = self.inherited_from
            if (
                not isinstance(parent, k.CompareSelector)
                or parent.known_at is None
                or _utc(parent.known_at, field="Inherited knowledge cutoff") != self.known_at
                or self.selector not in (parent.left, parent.right)
            ):
                raise ValueError("An inherited knowledge cutoff requires its comparison parent")
        elif self.inherited_from is not None:
            raise ValueError("Only an inherited knowledge cutoff carries a comparison parent")
        object.__setattr__(self, "selector_json", _selector_payload(self.selector, self.known_at))


@dataclass(frozen=True)
class TemporalInputs:
    record: k.TemporalRecord
    source_updated_at: datetime | None = None
    observed_at: datetime | None = None
    published_at: datetime | None = None
    source_precision: SourcePrecision = "unknown"
    recorded_from_is_publication: bool = False

    def __post_init__(self):
        if not isinstance(self.record, k.TemporalRecord):
            raise TypeError("Temporal inputs require a TemporalRecord")
        for clock in ("source_updated_at", "observed_at", "published_at"):
            value = getattr(self, clock)
            if value is not None:
                object.__setattr__(self, clock, _utc(value, field=clock.replace("_", " ").title()))
        if self.source_precision not in {
            "instant",
            "second",
            "minute",
            "day",
            "month",
            "year",
            "unknown",
        }:
            raise ValueError("Unknown source timestamp precision")
        if type(self.recorded_from_is_publication) is not bool:
            raise ValueError("Recorded/publication binding must be boolean")
        if (
            self.recorded_from_is_publication
            and self.published_at is not None
            and self.published_at != self.record.recorded_from
        ):
            raise ValueError("Published time differs from recorded publication time")


@dataclass(frozen=True)
class TemporalMatch:
    record_id: str
    disposition: TemporalDisposition
    reason: TemporalReason
    known_at: datetime
    valid_at: datetime | None = None
    valid_during: k.TimeInterval | None = None
    change_interval: k.TimeInterval | None = None


def _selector_payload(selector, known_at: datetime) -> str:
    payload = selector.model_dump(mode="json")
    payload.pop("known_at", None)
    payload["resolved_known_at"] = _iso(known_at)
    return canonical_json(payload)


def _resolve_single(selector, *, latest_known_at: datetime, parent: k.CompareSelector | None = None):
    explicit = getattr(selector, "known_at", None)
    if explicit is not None:
        return ResolvedTemporalSelector(selector, explicit, "explicit", latest_known_at)
    if parent is not None and parent.known_at is not None:
        return ResolvedTemporalSelector(selector, parent.known_at, "inherited", latest_known_at, parent)
    return ResolvedTemporalSelector(selector, latest_known_at, "latest", latest_known_at)


def resolve_selector(
    selector: k.TemporalSelector, *, latest_known_at: datetime
) -> ResolvedTemporalSelector | tuple[ResolvedTemporalSelector, ResolvedTemporalSelector]:
    """Resolve implicit knowledge cutoffs without duplicating them in identity JSON."""
    latest = _utc(latest_known_at, field="Latest knowledge cutoff")
    if isinstance(selector, k.CompareSelector):
        return (
            _resolve_single(selector.left, latest_known_at=latest, parent=selector),
            _resolve_single(selector.right, latest_known_at=latest, parent=selector),
        )
    return _resolve_single(selector, latest_known_at=latest)


def _match(record, disposition, reason, resolved, **changes):
    return TemporalMatch(
        record_id=record.id,
        disposition=disposition,
        reason=reason,
        known_at=resolved.known_at,
        **changes,
    )


def _recorded(record: k.TemporalRecord, known_at: datetime) -> TemporalReason | None:
    if known_at < record.recorded_from:
        return "recorded_after_cutoff"
    if record.recorded_to is not None and known_at >= record.recorded_to:
        return "recorded_closed"
    return None


def _effective(record: k.TemporalRecord) -> _HalfOpen | None:
    if record.validity_kind != "explicit_interval" or record.valid_from is None:
        return None
    return _HalfOpen(record.valid_from, record.valid_to)


def _point(record: k.TemporalRecord, valid_at: datetime, resolved):
    if record.validity_kind == "atemporal":
        return _match(record, "proven", "atemporal_match", resolved, valid_at=valid_at)
    effective = _effective(record)
    if effective is None:
        return _match(record, "contextual", "effective_unknown", resolved, valid_at=valid_at)
    if record.temporal_precision != "instant":
        return _match(record, "contextual", "effective_imprecise", resolved, valid_at=valid_at)
    inside = effective.contains(valid_at)
    return _match(
        record,
        "proven" if inside else "excluded",
        "effective_match" if inside else "effective_outside",
        resolved,
        valid_at=valid_at,
    )


def _during(record: k.TemporalRecord, selector: k.DuringSelector, resolved):
    requested = selector.valid_during
    effective = _effective(record)
    if effective is None:
        return _match(record, "contextual", "effective_unknown", resolved, valid_during=requested)
    if record.temporal_precision != "instant":
        return _match(record, "contextual", "effective_imprecise", resolved, valid_during=requested)
    window = _HalfOpen.requested(requested)
    matches = (
        effective.overlaps(window) if selector.interval_predicate == "overlaps" else effective.covers(window)
    )
    return _match(
        record,
        "proven" if matches else "excluded",
        "effective_match" if matches else "effective_outside",
        resolved,
        valid_during=requested,
    )


def _changes(inputs: TemporalInputs, selector: k.ChangesSelector, resolved):
    interval = k.TimeInterval(start=selector.changes_since, end=selector.changes_until)
    precision = "instant"
    if selector.change_clock == "published":
        clock = inputs.published_at
        if clock is None and inputs.recorded_from_is_publication:
            clock = inputs.record.recorded_from
    elif selector.change_clock == "source_modified":
        clock = inputs.source_updated_at
        precision = inputs.source_precision
    else:
        clock = inputs.record.valid_from if inputs.record.validity_kind == "explicit_interval" else None
        precision = inputs.record.temporal_precision
    if clock is None or precision != "instant":
        return _match(
            inputs.record,
            "contextual",
            "change_clock_unknown",
            resolved,
            change_interval=interval,
        )
    matches = interval.start <= clock < interval.end
    return _match(
        inputs.record,
        "proven" if matches else "excluded",
        "change_match" if matches else "change_outside",
        resolved,
        change_interval=interval,
    )


def match_temporal(inputs: TemporalInputs, resolved: ResolvedTemporalSelector) -> TemporalMatch:
    """Classify one authorized record under one resolved selector side."""
    if not isinstance(resolved, ResolvedTemporalSelector):
        raise TypeError("Temporal matching requires one resolved selector side")
    record = inputs.record
    if reason := _recorded(record, resolved.known_at):
        return _match(record, "excluded", reason, resolved)
    selector = resolved.selector
    if isinstance(selector, k.ChangesSelector):
        return _changes(inputs, selector, resolved)
    if isinstance(selector, k.DuringSelector):
        return _during(record, selector, resolved)
    if isinstance(selector, k.AtemporalSelector):
        if record.validity_kind == "atemporal":
            return _match(record, "proven", "atemporal_match", resolved)
        if record.validity_kind in {"unknown", "observed_snapshot"}:
            return _match(record, "contextual", "effective_unknown", resolved)
        return _match(record, "excluded", "effective_outside", resolved)
    valid_at = selector.valid_at if isinstance(selector, k.AsOfSelector) else resolved.known_at
    return _point(record, valid_at, resolved)


def serialize_temporal_evidence(inputs: TemporalInputs) -> dict:
    """Render declared clocks without filling unknown values from another clock."""
    record = inputs.record
    return {
        "record_id": record.id,
        "validity_kind": record.validity_kind,
        "temporal_basis": record.temporal_basis,
        "temporal_precision": record.temporal_precision,
        "source_timestamp_original": record.source_timestamp_original,
        "source_timezone": record.source_timezone,
        "valid_from": _iso(record.valid_from),
        "valid_to": _iso(record.valid_to),
        "recorded_from": _iso(record.recorded_from),
        "recorded_to": _iso(record.recorded_to),
        "source_updated_at": _iso(inputs.source_updated_at),
        "source_precision": inputs.source_precision,
        "observed_at": _iso(inputs.observed_at),
        "published_at": _iso(inputs.published_at),
    }


HistoryCoverageCode: TypeAlias = Literal["history_unavailable", "retention_gap", "link_coverage_incomplete"]
TemporalRecordKind: TypeAlias = Literal["ObjectObservation", "AssertionVersion"]
_RECORDED_FAILURES = frozenset({"recorded_after_cutoff", "recorded_closed"})
_RETAINED_GENERATIONS = frozenset({"active", "retired"})


@dataclass(frozen=True)
class HistoryDecision:
    """One authorized row's recorded eligibility beside its effective disposition.

    `recorded_reason` is where a positive recorded-eligibility decision is finally
    reported: the pure predicates only ever name the failures, so `recorded_match`
    belongs here, at the one layer that selects recorded-only proofs.
    """

    record_id: str
    record_kind: TemporalRecordKind
    recorded_reason: TemporalReason
    match: TemporalMatch


@dataclass(frozen=True)
class HistorySelection:
    """A persisted manifest plus the proof and inventory that justify every ID."""

    manifest: k.HistoryManifest
    selector: k.TemporalSelector
    resolved: ResolvedTemporalSelector
    selection: EvidenceSelection
    decisions: tuple[HistoryDecision, ...]
    resolver: EvidenceAccess = field(repr=False)
    broad: AuthorizedEvidence = field(repr=False)
    proof: AuthorizedEvidence = field(repr=False)

    def _by(self, disposition: TemporalDisposition) -> tuple[HistoryDecision, ...]:
        return tuple(item for item in self.decisions if item.match.disposition == disposition)

    @property
    def proven(self) -> tuple[HistoryDecision, ...]:
        return self._by("proven")

    @property
    def contextual(self) -> tuple[HistoryDecision, ...]:
        """Recorded-eligible rows whose effective time nothing in the source proves."""
        return self._by("contextual")

    @property
    def excluded(self) -> tuple[HistoryDecision, ...]:
        return self._by("excluded")

    @property
    def coverage(self) -> dict:
        return json.loads(self.manifest.coverage_json)

    @property
    def codes(self) -> tuple[HistoryCoverageCode, ...]:
        return tuple(self.coverage["codes"])


def pinned_selector(resolved: ResolvedTemporalSelector) -> k.TemporalSelector:
    """The selector as persisted: an implicit cutoff bound to the resolved instant.

    `selector_json` stays the pure audit identity, which deliberately replaces
    `known_at` with `resolved_known_at` and therefore is not a `TemporalSelector`.
    A stored manifest instead has to reparse as one, so the resolved cutoff is
    written back into the selector's own field and validated against the manifest.

    Every single-side mode carries `known_at`, so this binds for all of them: a
    `current` or `atemporal` pin that kept an empty cutoff would re-resolve to
    whatever "now" a replay happened to inject.
    """
    return resolved.selector.replace(known_at=resolved.known_at)


def history_access(store, workspace_id: str, access, *, clock=utc_now) -> EvidenceAccess:
    """One `EvidenceAccess` over the configured reviewed authorities, not a fork.

    The authority configuration is read through the store's own accessor, so a
    later tightening of that contract cannot apply to the reader path and miss
    this one. The only delta from `_reader_proof` is the injectable clock.
    """
    return EvidenceAccess(
        store,
        workspace_id,
        access,
        mapping_authorities=frozenset(store._reviewed_mapping_authorities()),
        clock=clock,
    )


def _authorized_temporal_rows(store, proof: AuthorizedEvidence):
    rows = []
    for kind, attribute in (
        ("ObjectObservation", "observation_ids"),
        ("AssertionVersion", "assertion_version_ids"),
    ):
        for identity in sorted(getattr(proof, attribute)):
            record = store._knowledge_get(kind, identity)
            if record is not None:
                rows.append((kind, record))
    return tuple(rows)


def _decide(kind: TemporalRecordKind, record, resolved) -> HistoryDecision:
    match = match_temporal(TemporalInputs(record=record), resolved)
    eligible = match.reason not in _RECORDED_FAILURES
    return HistoryDecision(record.id, kind, "recorded_match" if eligible else match.reason, match)


def _revision_closure(store, decisions, proof, rows):
    """Only revisions the proof already carries, reached from proven rows alone."""
    records = {record.id: record for _, record in rows}
    proven = {item.record_id for item in decisions if item.match.disposition == "proven"}
    revisions = {
        records[item.record_id].revision_id
        for item in decisions
        if item.record_id in proven and item.record_kind == "ObjectObservation"
    }
    for group in proof.support_groups:
        if group.assertion_version_id not in proven:
            continue
        for span_id in sorted(group.span_ids):
            span = store._knowledge_get("EvidenceSpan", span_id)
            if span is not None:
                revisions.add(span.revision_id)
    return revisions & set(proof.revision_ids)


def _link_generations(store, workspace_id: str, versions: set[str]):
    """A link generation whose inputs straddle the cutoff is reported, not trimmed."""
    compatible, incomplete = [], False
    for link in store._knowledge_rows("LinkGeneration"):
        members = set(link.assertion_version_ids)
        if link.workspace_id != workspace_id or not members:
            continue
        if members <= versions:
            compatible.append(link.id)
        elif members & versions:
            incomplete = True
    return sorted(compatible), incomplete


def _retention_gaps(store, revisions: set[str]):
    """Selected revisions whose retained generation membership was collected away."""
    retained = set()
    for member in store._knowledge_rows("GenerationMember"):
        generation = store._knowledge_get("Generation", member.generation_id)
        if generation is not None and generation.status in _RETAINED_GENERATIONS:
            retained.add(member.artifact_revision_id)
    return sorted(revisions - retained)


def proof_covers_manifest(proof: AuthorizedEvidence, manifest: k.HistoryManifest) -> bool:
    """True when every ID the manifest asserts is still inside this audience's proof.

    This is the invariant that protects a persisted manifest, and the one a later
    pin has to re-establish for its own audience: containment of the *manifest* in
    the proof, not of the proof in some earlier, broader one.
    """
    return (
        frozenset(manifest.revision_ids) <= proof.revision_ids
        and frozenset(manifest.assertion_version_ids) <= proof.assertion_version_ids
    )


def _counts(decisions, disposition):
    return {
        "observations": sum(
            1
            for item in decisions
            if item.match.disposition == disposition and item.record_kind == "ObjectObservation"
        ),
        "assertion_versions": sum(
            1
            for item in decisions
            if item.match.disposition == disposition and item.record_kind == "AssertionVersion"
        ),
    }


def select_history(
    store,
    *,
    workspace_id: str,
    access,
    selector: k.TemporalSelector,
    request_cutoff: datetime,
    clock=utc_now,
) -> HistorySelection:
    """Authorize, time-filter and persist one retained-evidence manifest.

    The order is fixed: resolve the cutoff, prove the broad retained evidence,
    then narrow it by time. Nothing may enter the manifest that the proof did not
    already contain, and a cutoff older than the earliest retained recorded
    interval returns an empty `history_unavailable` manifest, never current rows.

    Every read, the whole closure and the write happen inside one transaction
    against one authorization epoch, so a persisted manifest always describes a
    state the store really held: a publication or a collection interleaved with
    these reads can no longer produce a row no consistent view ever supported.
    Nothing in the block calls a model, the filesystem, a remote or a caller
    callback, and the only clock is the injected one `EvidenceAccess` reads.
    """
    resolved = resolve_selector(selector, latest_known_at=request_cutoff)
    if isinstance(resolved, tuple):
        raise ValueError("A compare selector needs one independently pinned manifest per side")
    with store.transaction():
        epoch = store.authorization_epoch()
        resolver = history_access(store, workspace_id, access, clock=clock)
        broad = resolver.build_history()
        rows = _authorized_temporal_rows(store, broad)
        decisions = tuple(_decide(kind, record, resolved) for kind, record in rows)
        earliest = min((record.recorded_from for _, record in rows), default=None)
        # An audience that can prove nothing is not a statement about retention:
        # `history_unavailable` is reserved for a cutoff before the earliest
        # retained recorded interval among the rows this audience may see.
        unavailable = earliest is not None and resolved.known_at < earliest

        revisions = _revision_closure(store, decisions, broad, rows)
        versions = {
            item.record_id
            for item in decisions
            if item.match.disposition == "proven" and item.record_kind == "AssertionVersion"
        }
        links, incomplete = _link_generations(store, workspace_id, versions)
        gaps = _retention_gaps(store, revisions)
        codes = sorted(
            ({"history_unavailable"} if unavailable else set())
            | ({"retention_gap"} if gaps else set())
            | ({"link_coverage_incomplete"} if incomplete else set())
        )
        pinned = pinned_selector(resolved)
        manifest = k.HistoryManifest(
            workspace_id=workspace_id,
            revision_ids=tuple(sorted(revisions)),
            assertion_version_ids=tuple(sorted(versions)),
            link_generation_ids=tuple(links),
            knowledge_cutoff=resolved.known_at,
            temporal_selector_json=canonical_json(pinned.model_dump(mode="json")),
            coverage_json=canonical_json(
                {
                    "proven": _counts(decisions, "proven"),
                    "contextual": _counts(decisions, "contextual"),
                    "codes": codes,
                }
            ),
            retention_gaps=tuple(gaps),
        )
        selection = EvidenceSelection(
            revision_ids=frozenset(manifest.revision_ids),
            assertion_version_ids=frozenset(manifest.assertion_version_ids),
            query_mode="history",
        )
        proof = resolver.build(selection)
        if broad.authorization_epoch != epoch or proof.authorization_epoch != epoch:
            raise AuthorizationChanged("Authorization changed during the evidence read")
        # Both directions, before the write: the manifest may assert nothing the
        # final proof lost, and that proof may reach nothing the broad one denied.
        if not proof_covers_manifest(proof, manifest):
            raise AuthorizationChanged("History manifest left its authorization proof")
        if not (
            proof.revision_ids <= broad.revision_ids
            and proof.assertion_version_ids <= broad.assertion_version_ids
        ):
            raise AuthorizationChanged("History selection left its authorization proof")
        store.put_knowledge(manifest)
        return HistorySelection(
            manifest=manifest,
            selector=pinned,
            resolved=resolved,
            selection=selection,
            decisions=decisions,
            resolver=resolver,
            broad=broad,
            proof=proof,
        )
