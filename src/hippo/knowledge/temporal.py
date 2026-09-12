"""Pure bitemporal selector predicates over already-authorized evidence.

This module does not select generations or grant access. Callers must first hold
an authorization/snapshot proof, then use these predicates to narrow its IDs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, TypeAlias

from . import model as k
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


def _resolve_single(selector, *, latest_known_at: datetime, inherited_known_at: datetime | None = None):
    explicit = getattr(selector, "known_at", None)
    if explicit is not None:
        return ResolvedTemporalSelector(selector, explicit, "explicit", latest_known_at)
    if inherited_known_at is not None:
        return ResolvedTemporalSelector(selector, inherited_known_at, "inherited", latest_known_at)
    return ResolvedTemporalSelector(selector, latest_known_at, "latest", latest_known_at)


def resolve_selector(
    selector: k.TemporalSelector, *, latest_known_at: datetime
) -> ResolvedTemporalSelector | tuple[ResolvedTemporalSelector, ResolvedTemporalSelector]:
    """Resolve implicit knowledge cutoffs without duplicating them in identity JSON."""
    latest = _utc(latest_known_at, field="Latest knowledge cutoff")
    if isinstance(selector, k.CompareSelector):
        return (
            _resolve_single(selector.left, latest_known_at=latest, inherited_known_at=selector.known_at),
            _resolve_single(selector.right, latest_known_at=latest, inherited_known_at=selector.known_at),
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
