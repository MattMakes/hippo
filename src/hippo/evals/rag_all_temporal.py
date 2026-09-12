"""Chronological JSONL loading of the Task 5A temporal fixture.

The rows of `tests/fixtures/rag_all/temporal_events.jsonl` are recorded events,
not a snapshot. This module replays them in `recorded_from` order into a real
knowledge store so the plan's nine temporal scenarios can be exercised through
the same publication, selection and conflict APIs production would use.

Three rules shape every decision here:

* Every instant comes from its row, parsed as an aware UTC value, with the
  provider's own text, declared zone and precision preserved. Nothing is
  defaulted to a wall clock: the caller supplies the one clock, and it says
  which events have happened, never when they happened.
* Supersession comes from the adapter ordering metadata a row carries. A claim
  is closed only when `select_same_source` proves an adapter-declared monotonic
  order retired it, and the closure travels as a `TemporalPublicationPlan`, so
  corrections stay append-only.
* Everything the loader writes is content addressed, so replaying the same file
  into the same store is an exact retry rather than a second history.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from ..knowledge import model as k
from ..knowledge.conflicts import (
    ConflictCandidate,
    SourceOrder,
    fully_superseded_version_ids,
    select_same_source,
)
from ..knowledge.temporal import RecordedSegment, TemporalPublicationPlan

EventKind = Literal["claim", "suppression", "barrier"]

SUBJECT_KIND = "service"
SUBJECT_NAME = "service-a"
"""One subject for the whole fixture: the rows argue about who owns it."""

OBJECT_KIND = "owner"
DEFAULT_SCOPE_KEY = "service-a:production"
"""The scope a row without an explicit `scope_key` claims. `environment_collision`
is the one row that declares another, which is what makes it a distinct scope."""

RULE_VERSION = "rag-all-temporal-v1"
PROFILE = "rag-all-temporal"
PARSER_VERSION = "1"
LINKER_VERSION = "1"
LEASE = timedelta(minutes=5)
LEASE_OWNER = "rag-all-temporal"
DEFAULT_BARRIERS = {"tombstone": "refetch", "access_loss": "reverify", "purge": "destroy"}
"""The barrier a suppression carries when no barrier row names one for its source."""

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
ORDER_KEYS = {"adapter", "version", "kind", "ordinal", "token"}
PRECISIONS = {"instant", "second", "minute", "day", "month", "year", "unknown"}


class TemporalFixtureError(ValueError):
    """A fixture row cannot be read as a recorded event."""


# ------------------------------------------------------------------ parsing


@dataclass(frozen=True)
class TemporalEvent:
    """One parsed row: every instant explicit, every original clock preserved."""

    index: int
    case: str
    kind: EventKind
    source_name: str
    recorded_from: datetime
    scope_key: str = DEFAULT_SCOPE_KEY
    order: SourceOrder | None = None
    predicate: str | None = None
    object_name: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    precision: str = "unknown"
    source_updated_at: datetime | None = None
    source_precision: str = "unknown"
    content_hash: str | None = None
    source_timestamp_original: str | None = None
    source_timezone: str | None = None
    view_applicability: str | None = None
    reason: str | None = None
    epoch: int | None = None
    restoration_barrier: str | None = None

    @property
    def validity_kind(self) -> str:
        return "explicit_interval" if self.valid_from is not None else "unknown"

    @property
    def temporal_basis(self) -> str:
        return "source_explicit" if self.valid_from is not None else "unknown"


def _instant(row: Mapping[str, Any], field: str, *, required: bool) -> datetime | None:
    value = row.get(field)
    if value is None:
        if required:
            raise TemporalFixtureError(f"{field} is required and may never be defaulted")
        return None
    if not isinstance(value, str):
        raise TemporalFixtureError(f"{field} must be an ISO instant string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TemporalFixtureError(f"invalid ISO instant for {field}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TemporalFixtureError(f"{field} requires a declared timezone: {value!r}")
    return parsed.astimezone(UTC)


def _timezone_label(text: str, parsed: datetime) -> str:
    return "UTC" if parsed.utcoffset() == timedelta(0) else text[-6:]


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TemporalFixtureError(f"{label} must be a nonempty string")
    return value


def _order(row: Mapping[str, Any], *, series_key: str) -> SourceOrder:
    data = row.get("provider_order")
    if not isinstance(data, dict) or set(data) != ORDER_KEYS:
        raise TemporalFixtureError(f"provider_order must declare exactly {sorted(ORDER_KEYS)}")
    try:
        return SourceOrder(
            adapter_id=_text(data["adapter"], "provider_order.adapter"),
            adapter_version=_text(data["version"], "provider_order.version"),
            series_key=series_key,
            kind=data["kind"],
            provider_token=data["token"],
            monotonic_ordinal=data["ordinal"],
        )
    except ValueError as exc:  # the ordering contract itself refused the row
        raise TemporalFixtureError(f"invalid provider_order: {exc}") from exc


def _precision(value: Any, label: str) -> str:
    if value not in PRECISIONS:
        raise TemporalFixtureError(f"{label} must be one of {sorted(PRECISIONS)}")
    return value


def _claim_event(index: int, row: Mapping[str, Any], source: str, recorded_from: datetime) -> TemporalEvent:
    keys = set(row)
    if not CLAIM_KEYS <= keys <= CLAIM_KEYS | CLAIM_OPTIONAL_KEYS:
        raise TemporalFixtureError(f"claim row {row.get('case')!r} declares unexpected fields")
    claim = row["claim"]
    if not isinstance(claim, dict) or set(claim) != {"predicate", "object"}:
        raise TemporalFixtureError("claim must declare exactly a predicate and an object")
    valid_from = _instant(row, "valid_from", required=False)
    valid_to = _instant(row, "valid_to", required=False)
    if valid_from is not None and valid_to is not None and valid_to <= valid_from:
        raise TemporalFixtureError("effective interval must be a nonempty half-open range")
    precision = _precision(row["precision"], "precision")
    if (precision == "instant") != (valid_from is not None):
        raise TemporalFixtureError("an exact effective bound and instant precision imply each other")
    original = row["valid_from"] if valid_from is not None else row["recorded_from"]
    anchor = valid_from if valid_from is not None else recorded_from
    return TemporalEvent(
        index=index,
        case=_text(row["case"], "case"),
        kind="claim",
        source_name=source,
        recorded_from=recorded_from,
        scope_key=_text(row.get("scope_key", DEFAULT_SCOPE_KEY), "scope_key"),
        order=_order(row, series_key=source),
        predicate=_text(claim["predicate"], "claim.predicate"),
        object_name=_text(claim["object"], "claim.object"),
        valid_from=valid_from,
        valid_to=valid_to,
        precision=precision,
        source_updated_at=_instant(row, "source_updated_at", required=False),
        source_precision=_precision(row.get("source_precision", "unknown"), "source_precision"),
        content_hash=row.get("content_hash"),
        source_timestamp_original=original,
        source_timezone=_timezone_label(original, anchor),
    )


def _suppression_event(
    index: int, row: Mapping[str, Any], source: str, recorded_from: datetime
) -> TemporalEvent:
    if set(row) != SUPPRESSION_KEYS:
        raise TemporalFixtureError(f"suppression row {row.get('case')!r} declares unexpected fields")
    data = row["suppression"]
    if not isinstance(data, dict) or set(data) != {"view_applicability", "reason", "epoch"}:
        raise TemporalFixtureError("suppression must declare view applicability, reason and epoch")
    if type(data["epoch"]) is not int or data["epoch"] < 1:
        raise TemporalFixtureError("suppression epoch must be a positive integer")
    return TemporalEvent(
        index=index,
        case=_text(row["case"], "case"),
        kind="suppression",
        source_name=source,
        recorded_from=recorded_from,
        view_applicability=_text(data["view_applicability"], "view_applicability"),
        reason=_text(data["reason"], "reason"),
        epoch=data["epoch"],
    )


def _barrier_event(index: int, row: Mapping[str, Any], source: str, recorded_from: datetime) -> TemporalEvent:
    if set(row) != BARRIER_KEYS:
        raise TemporalFixtureError(f"barrier row {row.get('case')!r} declares unexpected fields")
    return TemporalEvent(
        index=index,
        case=_text(row["case"], "case"),
        kind="barrier",
        source_name=source,
        recorded_from=recorded_from,
        order=_order(row, series_key=source),
        restoration_barrier=_text(row["restoration_barrier"], "restoration_barrier"),
    )


def read_temporal_events(path: str | Path) -> tuple[TemporalEvent, ...]:
    """Parse every row into a typed recorded event, in chronological order.

    Ties keep their file order, so the fixture's own sequence within one instant
    is what decides application order - never an ambient clock.
    """
    events = []
    for index, line in enumerate(Path(path).read_text().splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise TemporalFixtureError(f"row {index} is not valid JSON") from exc
        if not isinstance(row, dict):
            raise TemporalFixtureError(f"row {index} must be a JSON object")
        source = _text(row.get("source_id"), "source_id")
        recorded_from = _instant(row, "recorded_from", required=True)
        if "suppression" in row:
            events.append(_suppression_event(index, row, source, recorded_from))
        elif "restoration_barrier" in row:
            events.append(_barrier_event(index, row, source, recorded_from))
        elif "claim" in row:
            events.append(_claim_event(index, row, source, recorded_from))
        else:
            raise TemporalFixtureError(f"row {index} is neither a claim, a suppression nor a barrier")
    return tuple(sorted(events, key=lambda event: (event.recorded_from, event.index)))


# ------------------------------------------------------------------- loading


@dataclass(frozen=True)
class LoadedClaim:
    """One applied claim row and everything its publication wrote."""

    event: TemporalEvent
    generation_id: str
    revision_id: str
    span_id: str
    assertion: k.Assertion
    version: k.AssertionVersion
    candidate: ConflictCandidate
    closed_version_ids: tuple[str, ...]


@dataclass(frozen=True)
class TemporalLoad:
    """What a replay applied, deferred and wrote, with nothing inferred."""

    workspace_id: str
    applied: tuple[TemporalEvent, ...]
    deferred: tuple[TemporalEvent, ...]
    claims: tuple[LoadedClaim, ...]
    source_ids: Mapping[str, str]
    suppressions: Mapping[str, str]
    barriers: Mapping[str, str]
    events: tuple[TemporalEvent, ...]

    def claims_for(self, case: str) -> tuple[LoadedClaim, ...]:
        return tuple(item for item in self.claims if item.event.case == case)

    def claim(self, case: str) -> LoadedClaim:
        found = self.claims_for(case)
        if len(found) != 1:
            raise KeyError(f"{case!r} named {len(found)} applied claims, not one")
        return found[0]

    def barrier(self, case: str) -> TemporalEvent:
        return next(event for event in self.events if event.case == case and event.kind == "barrier")

    @property
    def candidates(self) -> tuple[ConflictCandidate, ...]:
        return tuple(item.candidate for item in self.claims)

    @property
    def current_candidates(self) -> tuple[ConflictCandidate, ...]:
        """The candidates same-source selection still carries as current claims."""
        return select_same_source(self.candidates).current


@contextmanager
def _generation_window(store):
    """Lend the store the instant of the row being applied, then give it back.

    The store's generation clock is the only ambient time a publication reads.
    Leaving it on wall time would judge a lease for a 2026-05 event against
    whenever the replay happens, so each row lends it its own recorded instant.
    """
    previous = getattr(store, "_generation_clock", None)
    state = {"at": None}
    store._generation_clock = lambda: state["at"]
    try:
        yield state
    finally:
        if previous is None:
            store.__dict__.pop("_generation_clock", None)
        else:
            store._generation_clock = previous


def _source_id(store, name: str) -> str:
    for source in store.list_sources():
        if source.get("name") == name:
            return source["id"]
    return store.create_source("text", name)


def _canonical(name: str) -> str:
    return json.dumps([name], separators=(",", ":"))


def _content_hash(event: TemporalEvent) -> str:
    """The provider's bytes when it declared them, else its opaque revision token.

    `old_imported_last` carries the token of the revision it re-imports, so it
    resolves to the same `ArtifactRevision` - which is exactly what "the same old
    bytes, imported last" means.
    """
    if event.content_hash:
        return event.content_hash
    if event.order is not None and event.order.provider_token:
        return event.order.provider_token
    return event.case


def _span_text(event: TemporalEvent) -> str:
    return f"{event.source_name}:{event.case}:{event.predicate}:{event.object_name}"


class _SourceState:
    """Per-source bookkeeping a replay needs and a fixture row does not carry."""

    def __init__(self, store, name: str, workspace_id: str, event: TemporalEvent, barrier: str | None):
        self.name = name
        self.id = _source_id(store, name)
        self.barrier = barrier
        policy = k.AccessPolicy(
            workspace_id=workspace_id,
            origin="local_curated",
            scope_key=f"source:{self.id}",
            mode="workspace",
            verified_at=event.recorded_from,
        )
        store.put_knowledge(policy)
        artifact = k.Artifact(
            workspace_id=workspace_id,
            source_id=self.id,
            kind="file",
            external_id=f"{name}.jsonl",
            canonical_uri=f"source:{name}",
            policy_id=policy.id,
        )
        store.put_knowledge(artifact)
        self.policy = policy
        self.artifact = artifact
        self.parent_id: str | None = None


def _revision(store, state: _SourceState, event: TemporalEvent) -> k.ArtifactRevision:
    """The revision these bytes are, reusing the stored row when it already exists.

    A revision is identified by its artifact, provider revision and bytes, so
    `old_imported_last` - the same `rev-a` bytes arriving after everything else -
    resolves to the revision it re-imports rather than to a second copy observed
    later. Re-import is not a new observation of new content.
    """
    record = k.ArtifactRevision(
        artifact_id=state.artifact.id,
        content_hash=_content_hash(event),
        provider_revision=(event.order.provider_token if event.order else None) or event.case,
        raw_uri=f"blob:{state.name}/{_content_hash(event)}",
        observed_at=event.recorded_from,
        source_updated_at=event.source_updated_at,
        source_precision=event.source_precision,
        lifecycle="active",
    )
    return store._knowledge_get("ArtifactRevision", record.id) or record


def _staged_records(state: _SourceState, workspace_id: str, event: TemporalEvent, revision):
    """Every immutable record one claim row contributes, with no instant invented."""
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="field",
        locator_json=json.dumps({"kind": "field", "field_path": event.case}, separators=(",", ":")),
        text=_span_text(event),
        policy_id=state.policy.id,
    )
    subject = k.KnowledgeObject(
        workspace_id=workspace_id, kind=SUBJECT_KIND, canonical_key=_canonical(SUBJECT_NAME)
    )
    target = k.KnowledgeObject(
        workspace_id=workspace_id, kind=OBJECT_KIND, canonical_key=_canonical(event.object_name)
    )
    observations = tuple(
        k.ObjectObservation(
            object_id=obj.id,
            revision_id=revision.id,
            span_id=span.id,
            evidence_class="declared",
            recorded_from=event.recorded_from,
            valid_from=event.valid_from,
            valid_to=event.valid_to,
            validity_kind=event.validity_kind,
            temporal_basis=event.temporal_basis,
            temporal_precision=event.precision,
            source_timestamp_original=event.source_timestamp_original,
            source_timezone=event.source_timezone,
        )
        for obj in (subject, target)
    )
    assertion = k.checked_assertion(subject, event.predicate, target, scope_key=event.scope_key)
    version = k.AssertionVersion(
        assertion_id=assertion.id,
        evidence_class="declared",
        # Each fixture source is its own extraction rule. Two sources that state
        # an identical undated claim at the same instant would otherwise share one
        # version row, and a published version's proof group is sealed: the second
        # source could not attach its own support. Corroboration across sources is
        # expressed as separate candidates over the same assertion instead.
        rule_version=f"{RULE_VERSION}:{state.name}",
        confidence=1.0,
        status="active",
        valid_from=event.valid_from,
        valid_to=event.valid_to,
        validity_kind=event.validity_kind,
        recorded_from=event.recorded_from,
        temporal_basis=event.temporal_basis,
        temporal_precision=event.precision,
        source_timestamp_original=event.source_timestamp_original,
        source_timezone=event.source_timezone,
    )
    support = k.AssertionSupport(assertion_version_id=version.id, span_id=span.id, derivation_group="direct")
    return revision, span, subject, target, observations, assertion, version, support


def _write_staged(store, generation, records):
    """Stage the row as evidence membership, so nothing but a plan can close it."""
    from ..knowledge.lifecycle import generation_passage_id

    revision, span, subject, target, observations, assertion, version, support = records
    store.put_knowledge(revision)
    store.put_knowledge(k.GenerationMember(generation_id=generation.id, artifact_revision_id=revision.id))
    for record in (subject, target, assertion):
        store.put_knowledge(record)
    for record in (span, *observations, version, support):
        store.put_knowledge(record)
        store.put_knowledge(
            k.GenerationEvidenceMember(
                generation_id=generation.id, record_kind=type(record).__name__, record_id=record.id
            )
        )
    store.add_passages(
        [
            {
                "id": generation_passage_id(generation.id, revision.id, span.id, 0),
                "source_id": generation.source_id,
                "generation_id": generation.id,
                "artifact_revision_id": revision.id,
                "span_id": span.id,
                "embedding_profile": PROFILE,
                "text": span.text,
                "title": span.text,
                "ordinal": 0,
                "embedding": [0.1, 0.2],
            }
        ]
    )


def _closures(
    store,
    candidates: Sequence[ConflictCandidate],
    *,
    source_id: str,
    published_at: datetime,
    open_ids: set[str],
) -> tuple[str, ...]:
    """The versions an adapter-declared monotonic order has retired, and only those.

    Arrival order never appears here: `select_same_source` decides over every
    loaded candidate, and `fully_superseded_version_ids` keeps a version still
    current under another series out of the closure entirely. Only this source's
    own open segments survive the filter, because a publication may close only
    what its own lineage asserted, and only segments recorded strictly before
    this instant, because a claim cannot retire itself.
    """
    own = {item.version.id for item in candidates if item.source_id == source_id}
    superseded = fully_superseded_version_ids(select_same_source(candidates))
    closable = []
    for version_id in superseded:
        if version_id not in own or version_id not in open_ids:
            continue
        row = store._knowledge_get("AssertionVersion", version_id)
        if row is not None and row.recorded_to is None and row.recorded_from < published_at:
            closable.append(version_id)
    return tuple(closable)


def _apply_claim(store, state, workspace_id, event, candidates, open_ids):
    records = _staged_records(state, workspace_id, event, _revision(store, state, event))
    revision, span, _subject, _target, _observations, assertion, version, _support = records
    generation = k.Generation(
        source_id=state.id,
        parent_id=state.parent_id,
        status="staging",
        parser_version=PARSER_VERSION,
        linker_version=LINKER_VERSION,
        embedding_profile=PROFILE,
        created_at=event.recorded_from,
        manifest_hash=f"rag-all-temporal:{event.index}:{event.case}",
    )
    candidate = ConflictCandidate(
        assertion=assertion,
        version=version,
        source_id=state.id,
        support_span_ids=(span.id,),
        order=event.order,
    )
    existing = store._knowledge_get("Generation", generation.id)
    if existing is not None and existing.status != "staging":
        # An exact retry: this row's publication already committed, so replaying
        # it observes the receipt instead of recording a second history.
        state.parent_id = generation.id
        return LoadedClaim(event, generation.id, revision.id, span.id, assertion, version, candidate, ())
    store.put_knowledge(generation)
    job = store.claim_generation_build(
        generation.id,
        job_key=generation.manifest_hash,
        lease_owner=LEASE_OWNER,
        lease_expires_at=event.recorded_from + LEASE,
    )
    credentials = dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)
    with store.generation_write(generation.id, **credentials):
        _write_staged(store, generation, records)
    closures = _closures(
        store,
        (*candidates, candidate),
        source_id=state.id,
        published_at=event.recorded_from,
        open_ids=open_ids,
    )
    plan = None
    if closures:
        plan = TemporalPublicationPlan(
            published_at=event.recorded_from,
            closures=tuple(RecordedSegment("AssertionVersion", item) for item in closures),
            appends=(RecordedSegment("AssertionVersion", version.id),),
        )
    store.seal_generation(
        generation.id,
        k.IndexManifest(
            generation_id=generation.id,
            profile_fingerprint=PROFILE,
            config_fingerprint=PROFILE,
            required_representations=("evidence", "dense", "native"),
            checksums=store.generation_checksums(generation.id),
            ready=True,
        ),
        **credentials,
    )
    store.publish_staged_generation(
        generation.id,
        expected_parent_id=generation.parent_id,
        expected_suppression_epoch=store.suppression_epoch(),
        published_at=event.recorded_from,
        plan=plan,
        **credentials,
    )
    state.parent_id = generation.id
    return LoadedClaim(event, generation.id, revision.id, span.id, assertion, version, candidate, closures)


def _apply_suppression(store, state, workspace_id, event) -> str:
    record = k.Suppression(
        workspace_id=workspace_id,
        target_kind="source",
        target_id=state.id,
        scope_key=f"source:{state.id}",
        all_principals=True,
        view_applicability=event.view_applicability,
        reason=event.reason,
        epoch=event.epoch,
        created_at=event.recorded_from,
        restoration_barrier=state.barrier or DEFAULT_BARRIERS[event.reason],
    )
    store.put_knowledge(record)
    return record.id


def load_temporal_events(store, path: str | Path, *, clock: Callable[[], datetime]) -> TemporalLoad:
    """Replay the fixture's recorded events into `store`, oldest event first.

    `clock` is the caller's statement of now. It bounds which events have
    happened - a row recorded after it is deferred, not applied - and it is the
    only time input the loader has: every instant it writes comes from a row.

    A claim becomes a staged generation published at the row's own
    `recorded_from`; when that row's adapter ordering retires an earlier claim in
    the same series, the publication carries a `TemporalPublicationPlan` that
    closes the retired segment and appends the new one in one transaction. A
    suppression row writes its suppression; a barrier row declares the
    authoritative restoration barrier its source's suppressions carry.
    """
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise TemporalFixtureError("the caller's clock must return an aware instant")
    events = read_temporal_events(path)
    # Barrier rows are resolved before any suppression is written: a Suppression
    # is immutable and `restoration_barrier` is not a mutable field, so the
    # barrier a source declares anywhere in the file is the one its suppressions
    # were always going to carry. Resolving it later would make an incremental
    # replay try to rewrite a committed suppression.
    barriers = {event.source_name: event.restoration_barrier for event in events if event.kind == "barrier"}
    applied, deferred = [], []
    claims: list[LoadedClaim] = []
    suppressions: dict[str, str] = {}
    states: dict[str, _SourceState] = {}
    workspace_id = None
    candidates: list[ConflictCandidate] = []
    open_ids: set[str] = set()
    with _generation_window(store) as window:
        for event in events:
            if event.recorded_from > now:
                deferred.append(event)
                continue
            window["at"] = event.recorded_from
            if event.kind == "barrier":
                # Its barrier is already in force; the row itself writes nothing.
                applied.append(event)
                continue
            if event.source_name not in states:
                identifier = _source_id(store, event.source_name)
                workspace_id = store.get_source(identifier)["workspace_id"]
                if store._knowledge_get("Workspace", workspace_id) is None:
                    store.put_knowledge(k.Workspace(name="default"))
                states[event.source_name] = _SourceState(
                    store, event.source_name, workspace_id, event, barriers.get(event.source_name)
                )
            state = states[event.source_name]
            if event.kind == "suppression":
                suppressions[event.case] = _apply_suppression(store, state, workspace_id, event)
            else:
                loaded = _apply_claim(store, state, workspace_id, event, candidates, open_ids)
                claims.append(loaded)
                candidates.append(loaded.candidate)
                open_ids.add(loaded.version.id)
                open_ids.difference_update(loaded.closed_version_ids)
            applied.append(event)
    return TemporalLoad(
        workspace_id=workspace_id,
        applied=tuple(applied),
        deferred=tuple(deferred),
        claims=tuple(claims),
        source_ids={name: state.id for name, state in states.items()},
        suppressions=suppressions,
        barriers=barriers,
        events=events,
    )
