"""Deterministic source ordering and conflict indexes for authorized claims."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal, TypeAlias

from . import model as k
from .identity import canonical_json
from .temporal import _HalfOpen

OrderingKind: TypeAlias = Literal["monotonic", "equality_only", "unknown"]
OrderingRelation: TypeAlias = Literal["older", "same", "newer", "ambiguous"]
Cardinality: TypeAlias = Literal["single", "multiple"]


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")


@dataclass(frozen=True)
class SourceOrder:
    adapter_id: str
    adapter_version: str
    series_key: str
    kind: OrderingKind
    provider_token: str | None = None
    monotonic_ordinal: int | None = None

    def __post_init__(self):
        for value, label in (
            (self.adapter_id, "Adapter ID"),
            (self.adapter_version, "Adapter version"),
            (self.series_key, "Ordering series"),
        ):
            _text(value, label)
        if self.kind not in {"monotonic", "equality_only", "unknown"}:
            raise ValueError("Unknown source ordering kind")
        if self.provider_token is not None:
            _text(self.provider_token, "Provider token")
        if self.kind == "monotonic":
            if type(self.monotonic_ordinal) is not int:
                raise ValueError("Monotonic ordering requires an adapter-normalized integer ordinal")
        elif self.monotonic_ordinal is not None:
            raise ValueError("An ordering ordinal is valid only for monotonic adapters")
        if self.kind == "equality_only" and self.provider_token is None:
            raise ValueError("Equality-only ordering requires an opaque provider token")


@dataclass(frozen=True)
class ConflictCandidate:
    assertion: k.Assertion
    version: k.AssertionVersion
    source_id: str
    support_span_ids: tuple[str, ...]
    order: SourceOrder

    def __post_init__(self):
        if not isinstance(self.assertion, k.Assertion) or not isinstance(self.version, k.AssertionVersion):
            raise TypeError("Conflict candidates require typed assertion records")
        if self.version.assertion_id != self.assertion.id:
            raise ValueError("Assertion version does not belong to the supplied assertion")
        _text(self.source_id, "Source ID")
        if (
            not isinstance(self.support_span_ids, tuple)
            or not self.support_span_ids
            or any(not isinstance(item, str) or not item for item in self.support_span_ids)
            or len(set(self.support_span_ids)) != len(self.support_span_ids)
        ):
            raise ValueError("Conflict support spans must be a nonempty unique tuple")
        if tuple(sorted(self.support_span_ids)) != self.support_span_ids:
            object.__setattr__(self, "support_span_ids", tuple(sorted(self.support_span_ids)))


@dataclass(frozen=True)
class SameSourceSelection:
    current: tuple[ConflictCandidate, ...]
    superseded_version_ids: tuple[str, ...]
    ambiguous_series: tuple[str, ...]
    superseded_by_series: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """Supersession keyed by its series, because it was only ever decided there.

    `superseded_version_ids` is the flat sorted-unique union and answers "was this
    version superseded anywhere". It is not a retirement list: the same version ID
    can be superseded under one source's series and still be the current claim
    under another's, so a caller that persists closures must use
    `fully_superseded_version_ids`, never this tuple.
    """

    @property
    def requires_refetch(self) -> bool:
        return bool(self.ambiguous_series)


def fully_superseded_version_ids(selection: SameSourceSelection) -> tuple[str, ...]:
    """The version IDs no series still carries as current, so nothing else claims them.

    This is the only set an append-only correction may close: a version superseded
    inside one series while remaining the current same-source candidate in another
    is still being asserted, and closing its recorded interval would retire a claim
    no adapter retired.
    """
    current = {candidate.version.id for candidate in selection.current}
    return tuple(sorted(set(selection.superseded_version_ids) - current))


def compare_orders(a: SourceOrder, b: SourceOrder) -> OrderingRelation:
    """Relate two ordering results; anything an adapter did not prove is ambiguous."""
    if (a.adapter_id, a.adapter_version, a.series_key) != (b.adapter_id, b.adapter_version, b.series_key):
        return "ambiguous"
    if a.kind != "monotonic" or b.kind != "monotonic":
        return "ambiguous"
    if a.monotonic_ordinal is None or b.monotonic_ordinal is None:
        return "ambiguous"
    if a.monotonic_ordinal == b.monotonic_ordinal:
        return "same"
    return "older" if a.monotonic_ordinal < b.monotonic_ordinal else "newer"


def _candidate_key(candidate):
    return (
        candidate.assertion.id,
        candidate.version.id,
        candidate.source_id,
        candidate.support_span_ids,
        canonical_json(asdict(candidate.order)),
    )


def _series_key(candidate):
    assertion = candidate.assertion
    order = candidate.order
    return (
        candidate.source_id,
        order.adapter_id,
        order.adapter_version,
        order.series_key,
        assertion.workspace_id,
        assertion.subject_id,
        assertion.predicate,
        assertion.scope_key,
    )


def _deduplicate(candidates):
    """Collapse identical candidates; corroborating sources stay separate candidates."""
    declared = {}
    unique = {}
    for candidate in candidates:
        first = declared.setdefault(candidate.version.id, candidate)
        if (first.assertion, first.version) != (candidate.assertion, candidate.version):
            raise ValueError(
                f"Assertion version {candidate.version.id} carries divergent identity metadata "
                f"between sources {first.source_id} and {candidate.source_id}"
            )
        unique[_candidate_key(candidate)] = candidate
    return tuple(sorted(unique.values(), key=_candidate_key))


def select_same_source(candidates) -> SameSourceSelection:
    """Select current same-source revisions only when an adapter proves order."""
    grouped = defaultdict(list)
    for candidate in _deduplicate(tuple(candidates)):
        grouped[_series_key(candidate)].append(candidate)
    current, superseded, ambiguous, by_series = [], set(), [], []
    for series, members in sorted(grouped.items()):
        newest = [
            member
            for member in members
            if not any(compare_orders(member.order, other.order) == "older" for other in members)
        ]
        retained = {_candidate_key(member) for member in newest}
        current.extend(newest)
        # One source can contribute the same version under two support groups, so
        # collapse to version IDs before recording the series' supersession.
        dropped = sorted({member.version.id for member in members if _candidate_key(member) not in retained})
        if dropped:
            by_series.append((canonical_json(series), tuple(dropped)))
            superseded.update(dropped)
        if len({member.version.id for member in newest}) > 1:
            ambiguous.append(canonical_json(series))
    return SameSourceSelection(
        current=tuple(sorted(current, key=_candidate_key)),
        superseded_version_ids=tuple(sorted(superseded)),
        ambiguous_series=tuple(sorted(ambiguous)),
        superseded_by_series=tuple(sorted(by_series)),
    )


def _logical_key(candidate):
    assertion = candidate.assertion
    return (assertion.workspace_id, assertion.subject_id, assertion.predicate, assertion.scope_key)


def _explicit_intersection(candidates) -> tuple[datetime | None, datetime | None] | None:
    """Exact half-open overlap: `None` when unprovable and `()` when provably empty.

    A bound coarser than an exact instant proves neither overlap nor disjointness, so a
    coarse-precision member makes the whole group unprovable rather than widening its window.
    """
    if all(candidate.version.validity_kind == "atemporal" for candidate in candidates):
        return (None, None)
    if any(
        candidate.version.validity_kind != "explicit_interval" or candidate.version.valid_from is None
        for candidate in candidates
    ):
        return None
    if any(candidate.version.temporal_precision != "instant" for candidate in candidates):
        return None
    spans = [_HalfOpen(item.version.valid_from, item.version.valid_to) for item in candidates]
    overlap = spans[0]
    for span in spans[1:]:
        overlap = overlap.intersect(span)
        if overlap is None:
            return ()
    return (overlap.start, overlap.end)


def _conflict(candidates):
    intersection = _explicit_intersection(candidates)
    if intersection == ():
        return None
    source_versions = defaultdict(set)
    for candidate in candidates:
        source_versions[candidate.source_id].add(candidate.version.id)
    ambiguous_source = any(len(versions) > 1 for versions in source_versions.values())
    possible = intersection is None or ambiguous_source
    start, end = (None, None) if intersection is None else intersection
    first = candidates[0].assertion
    return k.ConflictSet(
        workspace_id=first.workspace_id,
        scope_key=first.scope_key,
        assertion_version_ids=tuple(sorted({candidate.version.id for candidate in candidates})),
        valid_from=start,
        valid_to=end,
        resolution_status="possible" if possible else "unresolved",
        support_span_ids=tuple(
            sorted({span for candidate in candidates for span in candidate.support_span_ids})
        ),
    )


def _version_buckets(members):
    """One bucket per assertion version: corroborating sources are one alternative."""
    buckets = defaultdict(list)
    for member in members:
        buckets[member.version.id].append(member)
    return tuple(tuple(buckets[version_id]) for version_id in sorted(buckets))


def _pairwise_conflicts(buckets):
    result = []
    for left_index, left in enumerate(buckets):
        for right in buckets[left_index + 1 :]:
            if left[0].assertion.object_id == right[0].assertion.object_id:
                continue
            if conflict := _conflict(left + right):
                result.append(conflict)
    return result


def build_conflict_sets(candidates, *, cardinality: Cardinality) -> tuple[k.ConflictSet, ...]:
    """Index conflicting alternatives without resolving or widening evidence."""
    if cardinality not in {"single", "multiple"}:
        raise ValueError("Unknown declaration cardinality")
    if cardinality == "multiple":
        return ()
    grouped = defaultdict(list)
    for candidate in _deduplicate(tuple(candidates)):
        grouped[_logical_key(candidate)].append(candidate)
    conflicts = []
    for _, members in sorted(grouped.items()):
        if len({member.assertion.object_id for member in members}) < 2:
            continue
        whole = _conflict(tuple(members))
        if whole is not None:
            conflicts.append(whole)
        else:
            conflicts.extend(_pairwise_conflicts(_version_buckets(members)))
    return tuple(sorted({item.id: item for item in conflicts}.values(), key=lambda item: item.id))
