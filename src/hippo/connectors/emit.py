"""The batch-to-records binder: one emission batch onto the knowledge records, totally.

Design `docs/spec/connector-developer-kit.md` sections 4, 5 and 6, plan
`ai_docs/plans/cdk-s2-contract.md` sections 4.5, 8 and 9. `bind_batch` is pure and deterministic: it
reads no store, no socket, no model, no subprocess and no clock. `recorded_from` is the generation
instant the caller passes in, and `observed_at` belongs to the runtime's capture step.

Rulings applied: R6 (a rendered fact is a `Unit` and a derived `Passage` over the record span;
identity-only foreign endpoints), R16 and R39 (bind runs against the frozen `current_registry()` and
calls `Registry.check_record` on every record it builds), R40/R62/R63 (`evidence_class` takes the
registry, reads built-ins from `EVIDENCE_CLASS_DERIVATION` and an extension source's class from
`Registry.evidence_source_definition`), R42 with review m6 (the bound message interpolates
`PASSAGE_CHAR_BOUND`), R45 (`BUILTIN_VERIFIERS` is this module's table, consulted before an extension
locator kind's `verifier`), R48 (every span keeps `RevisionInput.span_policy_id`, never the
artifact's current policy), R53 (an identity-only foreign endpoint is keyed by its declared
`NodeRef.instance`), R61 (`policy_record` applies the instance `principal_map`), R66(ii) (a version's
`unit_id` is a name, never a lookup), and review M7 (`Provenance.observed_at` is the fetch's
`source_updated_at`).

An extension locator kind supplies `LocatorKindDefinition.verifier`, which this module calls as
`verifier(data, locator, artifact=artifact) -> str`, where `locator` is the parsed canonical locator
payload. It returns the span's exact text or raises `ValueError`; the kit turns that into a
`BindRefused` naming the locator and never quoting the text.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import ValidationError

from ..knowledge import model as k
from ..knowledge.builtin_types import EVIDENCE_CLASS_DERIVATION
from ..knowledge.derivations import dependency_version, view_fingerprint
from ..knowledge.identity import canonical_json, make_identity, text_hash
from ..knowledge.lifecycle import generation_passage_id
from ..knowledge.predicates import SCHEMA as SCHEMA_KINDS
from ..knowledge.predicates import validate_endpoints
from ..knowledge.registry import (
    PredicateDefinition,
    Registry,
    UnregisteredName,
    current_registry,
)
from .base import (
    PASSAGE_CHAR_BOUND,
    ConnectorDescriptor,
    ContractError,
    EmissionBatch,
    PolicyObservation,
    PrincipalMap,
    RawFetch,
    RevisionInput,
    SpanRef,
    map_principals,
    token_count,
)

BINDER_VERSION = "cdk-emit-v1"
IDENTITY_PREDICATE = "SAME_OBJECT_AS"
# Section 8.8: kind pairs an exact-identity rule cannot settle on its own, so the alias waits for
# the reconciliation queue (Task 12) rather than joining two objects unreviewed. The database pairs
# are read from `predicates.SCHEMA` (`predicates.py:53`), so a kind added there is guarded too.
GUARDED_ALIAS_PAIRS = frozenset(
    {
        frozenset({"service"}),
        frozenset({"service", "repository"}),
        *(frozenset({kind, "resource"}) for kind in SCHEMA_KINDS.split()),
    }
)


class BindRefused(ContractError):
    """One emission the kit will not store; the message names the fix."""


# `keys` and `render` are imported below `BindRefused` on purpose: `keys.KeyPartsRefused` subclasses
# it (plan section 10, Task S2b), so importing them above would leave the name unbound whenever
# `hippo.connectors.emit` is the first module of the cycle to be imported.
from . import keys, render  # noqa: E402

__all__ = [
    "BINDER_VERSION",
    "BUILTIN_VERIFIERS",
    "BindContext",
    "BindRefused",
    "BoundBatch",
    "BoundPassageRow",
    "CapturedRevision",
    "EmissionCoverage",
    "bind_batch",
    "capture_records",
    "check_direction_and_ownership",
    "evidence_class",
    "merge_bound",
    "policy_record",
    "verify_span",
]


# ------------------------------------------------------------------ the records bind produces


@dataclass(frozen=True, slots=True)
class BindContext:
    registry: Registry
    descriptor: ConnectorDescriptor
    connector: k.Connector
    generation: k.Generation
    workspace_id: str
    source_id: str
    partition: str

    @property
    def scope_key(self) -> str:
        return f"source:{self.source_id}:{self.partition}"

    @property
    def instance(self) -> str:
        return self.connector.instance_url


@dataclass(frozen=True, slots=True)
class BoundPassageRow:
    """A managed `Passage` native row before the runtime adds its vector (`input_binding.py:118`)."""

    generation: k.Generation
    span: k.EvidenceSpan
    view: k.RetrievalView | None
    ordinal: int
    title: str
    text: str

    @property
    def id(self) -> str:
        return generation_passage_id(
            self.generation.id,
            self.span.revision_id,
            self.span.id,
            self.ordinal,
            retrieval_view_id=self.retrieval_view_id,
        )

    @property
    def retrieval_view_id(self) -> str | None:
        return self.view.id if self.view is not None else None

    def native_row(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.generation.source_id,
            "generation_id": self.generation.id,
            "artifact_revision_id": self.span.revision_id,
            "span_id": self.span.id,
            "retrieval_view_id": self.retrieval_view_id,
            "embedding_profile": self.generation.embedding_profile,
            "ordinal": self.ordinal,
            "title": self.title,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class EmissionCoverage:
    """What one batch contributed, including what it could not state (section 8.10)."""

    nodes: int = 0
    edges: int = 0
    passages: int = 0
    units: Mapping[str, int] = field(default_factory=dict)
    aliases: Mapping[str, int] = field(default_factory=dict)
    hints: Mapping[str, int] = field(default_factory=dict)
    failures: Mapping[str, int] = field(default_factory=dict)
    # Section 8.2's `Node.domain` column and section 7's skipped fact templates: neither is a record
    # field, and both are lost if the batch does not count them.
    nodes_by_family: Mapping[str, int] = field(default_factory=dict)
    facts_skipped: Mapping[str, int] = field(default_factory=dict)
    unclassified: int = 0

    def __add__(self, other: EmissionCoverage) -> EmissionCoverage:
        if not isinstance(other, EmissionCoverage):
            return NotImplemented
        return EmissionCoverage(
            nodes=self.nodes + other.nodes,
            edges=self.edges + other.edges,
            passages=self.passages + other.passages,
            units=_summed(self.units, other.units),
            aliases=_summed(self.aliases, other.aliases),
            hints=_summed(self.hints, other.hints),
            failures=_summed(self.failures, other.failures),
            nodes_by_family=_summed(self.nodes_by_family, other.nodes_by_family),
            facts_skipped=_summed(self.facts_skipped, other.facts_skipped),
            unclassified=self.unclassified + other.unclassified,
        )

    def to_json(self) -> dict:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "passages": self.passages,
            "units": dict(sorted(self.units.items())),
            "aliases": dict(sorted(self.aliases.items())),
            "hints": dict(sorted(self.hints.items())),
            "failures": dict(sorted(self.failures.items())),
            "nodes_by_family": dict(sorted(self.nodes_by_family.items())),
            "facts_skipped": dict(sorted(self.facts_skipped.items())),
            "unclassified": self.unclassified,
        }


def _summed(left: Mapping[str, int], right: Mapping[str, int]) -> dict[str, int]:
    merged = dict(left)
    for name, count in right.items():
        merged[name] = merged.get(name, 0) + count
    return dict(sorted(merged.items()))


@dataclass(frozen=True, slots=True)
class BoundBatch:
    generation_id: str
    revision_ids: tuple[str, ...]
    spans: tuple[k.EvidenceSpan, ...]
    objects: tuple[k.KnowledgeObject, ...]
    observations: tuple[k.ObjectObservation, ...]
    assertions: tuple[k.Assertion, ...]
    versions: tuple[k.AssertionVersion, ...]
    supports: tuple[k.AssertionSupport, ...]
    passages: tuple[BoundPassageRow, ...]
    units: tuple[k.Unit, ...]
    views: tuple[k.RetrievalView, ...]
    derived_records: tuple[k.DerivedRecord, ...]
    derived_dependencies: tuple[k.DerivedDependency, ...]
    evidence_members: tuple[k.GenerationEvidenceMember, ...]
    coverage: EmissionCoverage


@dataclass(frozen=True, slots=True)
class CapturedRevision:
    artifact: k.Artifact
    revision: k.ArtifactRevision
    policy: k.AccessPolicy


# ------------------------------------------------------------------ evidence classes (section 8.3)


def evidence_class(registry: Registry, family: str, source: str, metadata_origin: str | None = None) -> str:
    """The design's section 4 derivation table; a connector never sets an evidence class itself.

    Built-in sources are read from `EVIDENCE_CLASS_DERIVATION`. An extension source carries its own
    family and class (rulings R40 and R62), so the registry is the table for it. Ruling R63 gives
    this function the registry for exactly that reason. Every other pair refuses, which is what
    keeps `deterministic`/`similarity` and `probabilistic`/`parser` out of the store.
    """
    derived = EVIDENCE_CLASS_DERIVATION.get((family, source, metadata_origin))
    if derived is not None:
        return derived
    try:
        definition = registry.evidence_source_definition(source)
    except UnregisteredName:
        definition = None
    if (
        definition is not None
        and definition.evidence_class is not None
        and definition.family == family
        and metadata_origin is None
    ):
        return definition.evidence_class
    raise BindRefused(
        f"No evidence class for family={family} source={source}; "
        "the derivation table in the kit design section 4 is fixed"
    )


# ------------------------------------------------------------------ span verification (section 8.4)


def _verify_file_lines(data: bytes, locator: dict, *, artifact: k.Artifact) -> str:
    from ..ingest.provenance import _lines

    if artifact.kind == "file" and locator["path"] != artifact.external_id:
        raise BindRefused("A file_lines locator names a different file than its revision")
    text = _decoded(data)
    lines = _lines(text)
    start, end = locator["start"], locator["end"]
    if not 1 <= start <= end <= len(lines):
        raise BindRefused(f"Locator {canonical_json(locator)} is outside the revision's {len(lines)} lines")
    return "".join(text[line.start : line.end] for line in lines[start - 1 : end])


def _verify_field(data: bytes, locator: dict, *, artifact: k.Artifact) -> str:
    path = locator["field_path"]
    try:
        document = json.loads(_decoded(data))
    except ValueError as error:
        raise BindRefused("The revision is not one JSON document; a field span cannot be resolved") from error
    value = document
    for segment in path.split("."):
        if segment.isdigit() and isinstance(value, list):
            index = int(segment)
            if index >= len(value):
                raise BindRefused(f"Field {path} is absent from the revision document")
            value = value[index]
        elif isinstance(value, dict) and segment in value:
            value = value[segment]
        else:
            raise BindRefused(f"Field {path} is absent from the revision document")
    return value if isinstance(value, str) else canonical_json(value)


def _verify_table_cell(data: bytes, locator: dict, *, artifact: k.Artifact) -> str:
    if locator["table"] != 0:
        raise BindRefused("A revision holds one CSV table; table must be 0")
    rows = list(csv.reader(io.StringIO(_decoded(data))))
    row, cell = locator["row"], locator["column"]
    if not (0 <= row < len(rows) and 0 <= cell < len(rows[row])):
        raise BindRefused(f"Cell ({row}, {cell}) is outside the revision table")
    return rows[row][cell]


# Ruling R45: the kit's own verifiers, consulted before an extension kind's `verifier`. There is no
# byte-range built-in kind; `section`, `comment`, `page` and `diff_hunk` have no verifier here and
# are admitted only when the connector that registers them supplies one.
BUILTIN_VERIFIERS = {
    "file_lines": _verify_file_lines,
    "field": _verify_field,
    "table_cell": _verify_table_cell,
}


def _decoded(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BindRefused("The revision bytes are not valid UTF-8; no span can be verified") from error
    return text[1:] if text.startswith("﻿") else text


def verify_span(data: bytes, span: SpanRef, *, artifact: k.Artifact) -> str:
    """The span's text, computed from the revision bytes; `SpanRef.text` is only a cross-check.

    The kit never trusts an emitted text. A mismatch names the locator and never quotes either
    text: one of them may hold content the reader of this message may not see.
    """
    locator_json = _canonical_locator(span)
    locator = json.loads(locator_json)
    verifier = BUILTIN_VERIFIERS.get(span.locator_kind)
    if verifier is None:
        verifier = _extension_verifier(span.locator_kind)
    try:
        text = verifier(data, locator, artifact=artifact)
    except BindRefused:
        raise
    except ValueError as error:
        raise BindRefused(
            f"Locator {locator_json} could not be resolved against the revision bytes"
        ) from error
    if not isinstance(text, str):
        raise BindRefused(f"The verifier of {span.locator_kind} returned no text")
    if span.text is not None and span.text != text:
        raise BindRefused(f"Span text differs from the revision bytes at {span.locator_kind} {locator_json}")
    return text


def _canonical_locator(span: SpanRef) -> str:
    payload = dict(span.locator)
    payload.setdefault("kind", span.locator_kind)
    if payload["kind"] != span.locator_kind:
        raise BindRefused(f"Locator payload names kind {payload['kind']!r}, not {span.locator_kind!r}")
    try:
        return k.canonical_locator_json(canonical_json(payload))
    except (ValueError, UnregisteredName) as error:
        raise BindRefused(f"Locator for {span.locator_kind} is invalid: {error}") from error


def _extension_verifier(locator_kind: str):
    try:
        definition = current_registry().locator_kind(locator_kind)
    except UnregisteredName as error:
        raise BindRefused(
            f"locator kind {locator_kind!r} is not registered; "
            "register it with a TypeExtension before emitting"
        ) from error
    if definition.verifier is None:
        raise BindRefused(
            f"Locator kind {locator_kind} has no byte verifier in the kit; "
            "spans of this kind cannot be emitted"
        )
    return definition.verifier


# ------------------------------------------------------------------ direction and ownership (8.5)


def check_direction_and_ownership(
    registry: Registry,
    descriptor: ConnectorDescriptor,
    predicate: str,
    subject_kind: str,
    object_kind: str,
) -> PredicateDefinition:
    """The predicate an edge may be stored under, or the refusal its developer must read.

    The binder and S4's kit call this one function, so the message a developer sees from
    `hippo connector validate` is the message the binder would have raised.
    """
    definition = _registered(registry, "predicate", predicate)
    if definition.identity:
        raise BindRefused(f"{predicate} is an identity predicate; emit an AliasEmission with its rule")
    forward = _endpoints_fit(definition, subject_kind, object_kind)
    if not forward and _endpoints_fit(definition, object_kind, subject_kind):
        raise BindRefused(
            f"{predicate} runs {sorted(definition.subject_kinds)} -> {sorted(definition.object_kinds)}; "
            f"this edge runs {subject_kind} -> {object_kind}, the reverse of its canonical direction. "
            "Swap subject and object if you own the fact, or emit a ReverseViewHint."
        )
    if not set(descriptor.families) & definition.owner_families:
        raise BindRefused(
            f"{descriptor.name} ({', '.join(descriptor.families)}) cannot store {predicate}: "
            f"its owner families are {', '.join(sorted(definition.owner_families))}. "
            "Emit a ReverseViewHint for the view you observed, or an AliasEmission for an identity "
            "you can back with a rule."
        )
    if not forward:
        # `k.checked_assertion`'s own message, kept verbatim (S1 D10).
        raise BindRefused(f"Invalid endpoint kinds for {predicate}")
    return definition


def _endpoints_fit(definition: PredicateDefinition, subject_kind: str, object_kind: str) -> bool:
    return subject_kind in definition.subject_kinds and object_kind in definition.object_kinds


def _registered(registry: Registry, what: str, name: str):
    lookup = {
        "object kind": registry.object_kind,
        "predicate": registry.predicate,
        "locator kind": registry.locator_kind,
        "evidence source": registry.evidence_source,
    }[what]
    try:
        return lookup(name)
    except UnregisteredName as error:
        raise BindRefused(
            f"{what} {name!r} is not registered; register it with a TypeExtension before emitting"
        ) from error


# ------------------------------------------------------------------ capture records (section 8.9)


def policy_record(
    policy: PolicyObservation,
    *,
    connector: k.Connector,
    workspace_id: str,
    observed_at: datetime,
    expires_at: datetime,
) -> k.AccessPolicy:
    """The provider policy of one artifact, with its principals mapped to local ids (R44, R61).

    `expires_at` is always set: a provider policy without a deadline is unreadable
    (`access.py:476-480`), and an unknown policy is `mode="unknown"`, which denies every reader.
    """
    mapped, _dropped = map_principals(policy, _principal_map(connector))
    return k.AccessPolicy(
        workspace_id=workspace_id,
        origin="provider",
        scope_key=(f"connector:{connector.id}:{policy.ref.artifact_kind}:{policy.ref.external_id}"),
        mode="unknown" if mapped.state == "unknown" else mapped.mode,
        allow_users=mapped.allow_users,
        allow_groups=mapped.allow_groups,
        deny_users=mapped.deny_users,
        deny_groups=mapped.deny_groups,
        verified_at=observed_at,
        expires_at=expires_at,
    )


def _principal_map(connector: k.Connector) -> PrincipalMap:
    configured = json.loads(connector.config_json).get("principal_map")
    if configured is None:
        return PrincipalMap()
    try:
        return PrincipalMap.model_validate(configured)
    except ValidationError as error:
        raise BindRefused(f"The connector principal_map is invalid: {error}") from error


def capture_records(
    fetch: RawFetch,
    policy: PolicyObservation,
    *,
    connector: k.Connector,
    workspace_id: str,
    source_id: str,
    raw_uri: str,
    observed_at: datetime,
    policy_expires_at: datetime,
) -> CapturedRevision:
    """The artifact, revision and policy of one fetch; the runtime decides what to reuse (S3)."""
    if fetch.ref != policy.ref:
        raise BindRefused("Policy and fetch name different artifacts")
    record = policy_record(
        policy,
        connector=connector,
        workspace_id=workspace_id,
        observed_at=observed_at,
        expires_at=policy_expires_at,
    )
    artifact = k.Artifact(
        workspace_id=workspace_id,
        source_id=source_id,
        connector_id=connector.id,
        provider_instance=connector.instance_url,
        kind=fetch.ref.artifact_kind,
        external_id=fetch.external_id,
        canonical_uri=fetch.canonical_uri,
        policy_id=record.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        provider_revision=fetch.provider_revision,
        content_hash=hashlib.sha256(fetch.data).hexdigest(),
        raw_uri=raw_uri,
        # Review M7: the provider's instant of this version. The kit's receipt clock is
        # `observed_at`, which the runtime passes; neither is read here.
        source_updated_at=fetch.source_updated_at,
        source_timestamp_original=fetch.source_timestamp_original,
        source_timezone=fetch.source_timezone,
        source_precision=fetch.source_precision,
        observed_at=observed_at,
        lifecycle="active",
        metadata_json=canonical_json(
            {
                "content_type": fetch.content_type,
                "parser": fetch.parser.spelling if fetch.parser is not None else None,
            }
        ),
    )
    return CapturedRevision(artifact=artifact, revision=revision, policy=record)


# ------------------------------------------------------------------ the binder (section 8.1)


@dataclass
class _Pending:
    """A rendered unit and the derived passage that will hold it, before ordinals are assigned."""

    order: tuple
    handle: str
    span: k.EvidenceSpan
    text: str
    template: str
    title: str
    kind: str
    mentions: tuple[str, ...]
    object_id: str | None


def bind_batch(context: BindContext, revision: RevisionInput, batch: EmissionBatch) -> BoundBatch:
    """Bind one emission batch onto knowledge records, or refuse at the first violation.

    Pure and deterministic: the same context, revision and batch produce equal records, and nothing
    here reads a clock, a store or the network.
    """
    return _Binder(context, revision).run(batch)


class _Binder:
    def __init__(self, context: BindContext, revision: RevisionInput) -> None:
        registry = context.registry
        if registry is not current_registry() or not registry.frozen or revision.registry is not registry:
            raise BindRefused(
                "Bind requires the frozen current registry that the knowledge model validates against"
            )
        self.context = context
        self.revision = revision
        self.registry = registry
        self.descriptor = context.descriptor
        self.recorded_from = context.generation.created_at
        self.spans: dict[str, k.EvidenceSpan] = {}
        self.objects: dict[str, k.KnowledgeObject] = {}
        self.labels: dict[str, str] = {}
        self.observed_span: dict[str, str] = {}
        self.observations: list[k.ObjectObservation] = []
        self.assertions: dict[str, k.Assertion] = {}
        self.versions: dict[str, k.AssertionVersion] = {}
        self.supports: dict[tuple[str, str, str], k.AssertionSupport] = {}
        self.verbatim: list[tuple[tuple, k.EvidenceSpan, str, str]] = []
        self.slices: list[tuple[str, dict]] = []
        self.fact_pending: list[_Pending] = []
        self.edge_pending: list[_Pending] = []
        self._derived: dict[str, k.DerivedRecord] = {}
        self._dependencies: dict[str, k.DerivedDependency] = {}
        self.coverage_units: dict[str, int] = {}
        self.coverage_aliases: dict[str, int] = {}
        self.coverage_hints: dict[str, int] = {}
        self.coverage_failures: dict[str, int] = {}
        self.nodes_by_family: dict[str, int] = {}
        self.facts_skipped: dict[str, int] = {}
        self.nodes = 0
        self.edges = 0

    # -------------------------------------------------------------- steps

    def run(self, batch: EmissionBatch) -> BoundBatch:
        self._check_vocabulary(batch)
        self._bind_nodes(batch)
        self._bind_verbatim(batch)
        self._bind_edges(batch)
        self._bind_aliases(batch)
        self._bind_hints(batch)
        self._count_failures(batch)
        passages, units = self._materialize(batch)
        views = tuple(row.view for row in passages if row.view is not None)
        derived_records, derived_dependencies = self._derivations(views)
        return BoundBatch(
            generation_id=self.context.generation.id,
            revision_ids=(self.revision.revision.id,),
            spans=self._sorted(self.spans.values()),
            objects=self._sorted(self.objects.values()),
            observations=self._sorted(self.observations),
            assertions=self._sorted(self.assertions.values()),
            versions=self._sorted(self.versions.values()),
            supports=self._sorted(self.supports.values()),
            passages=passages,
            units=units,
            views=tuple(sorted(views, key=lambda record: record.id)),
            derived_records=derived_records,
            derived_dependencies=derived_dependencies,
            evidence_members=self._members(passages, units, views, derived_records, derived_dependencies),
            coverage=EmissionCoverage(
                nodes=self.nodes,
                edges=self.edges,
                passages=len(passages),
                units=dict(sorted(self.coverage_units.items())),
                aliases=dict(sorted(self.coverage_aliases.items())),
                hints=dict(sorted(self.coverage_hints.items())),
                failures=dict(sorted(self.coverage_failures.items())),
                nodes_by_family=dict(sorted(self.nodes_by_family.items())),
                facts_skipped=dict(sorted(self.facts_skipped.items())),
            ),
        )

    def _check_vocabulary(self, batch: EmissionBatch) -> None:
        """Step 2: every name resolves in the registry, and the descriptor declares it (R3)."""
        refs = [
            *(emission.ref for emission in batch.nodes),
            *(ref for edge in batch.edges for ref in (edge.subject, edge.object)),
            *(ref for alias in batch.aliases for ref in (alias.a, alias.b)),
            *(ref for hint in batch.hints for ref in (hint.subject, hint.object)),
            *(ref for unit in batch.units for ref in unit.mentions),
            *(emission.node for emission in batch.passages if emission.node is not None),
        ]
        for ref in refs:
            self._declared("object kind", ref.kind, self.descriptor.kinds)
        for name in (*(edge.predicate for edge in batch.edges), *(hint.predicate for hint in batch.hints)):
            self._declared("predicate", name, self.descriptor.predicates)
        for span in _every_span(batch):
            self._declared("locator kind", span.locator_kind, self.descriptor.locator_kinds)
        for source in (
            *(emission.source for emission in batch.nodes),
            *(edge.source for edge in batch.edges),
        ):
            _registered(self.registry, "evidence source", source)

    def _declared(self, what: str, name: str, declared: tuple[str, ...]) -> None:
        _registered(self.registry, what, name)
        if name not in declared:
            raise BindRefused(f"Connector {self.descriptor.name} emits {what} {name!r} it does not declare")

    def _bind_nodes(self, batch: EmissionBatch) -> None:
        """Step 4: the object, its observation and, when the connector owns the family, its facts."""
        for emission in batch.nodes:
            definition = self.registry.object_kind(emission.ref.kind)
            span = self._span(emission.span)
            attrs = self._attributes(definition, emission.attrs)
            key = keys.canonical_key(self.registry, emission.ref, instance=self.context.instance)
            obj = keys.knowledge_object(
                self.registry,
                emission.ref,
                workspace_id=self.context.workspace_id,
                instance=self.context.instance,
            )
            self._record(obj)
            self.objects[obj.id] = obj
            owned = definition.family in self.descriptor.families
            if owned:
                label = render.render_label(definition, attrs)
                self.labels[obj.id] = label
                attributes = {
                    "attrs": attrs.model_dump(mode="json"),
                    "key": key.readable,
                    "label": label,
                }
            else:
                # Ruling R6: an endpoint of a family this connector does not own is identity only.
                # Ruling R70: it is named by the label the connector emitted for it when there is
                # one, and by its readable canonical key otherwise. Both spellings go to
                # `attributes_json`, so a statement about the endpoint stays re-derivable from the
                # records that were stored, while the emitted attributes are not (S2b).
                attributes = {"key": key.readable}
                if emission.ref.label is not None:
                    attributes["label"] = emission.ref.label
                self.labels.setdefault(obj.id, emission.ref.label or key.readable)
            observation = k.ObjectObservation(
                object_id=obj.id,
                revision_id=span.revision_id,
                span_id=span.id,
                attributes_json=canonical_json(attributes),
                evidence_class=evidence_class(
                    self.registry, "deterministic", emission.source, emission.metadata_origin
                ),
                recorded_from=self.recorded_from,
                **_node_timing(emission),
            )
            self._record(observation)
            self.observations.append(observation)
            self.observed_span[obj.id] = span.id
            self.nodes += 1
            self.nodes_by_family[definition.family] = self.nodes_by_family.get(definition.family, 0) + 1
            if owned:
                self._render_facts(definition, attrs, obj, span, label=label, key=key)

    def _attributes(self, definition, attrs: dict):
        try:
            return definition.attrs_model.model_validate(attrs)
        except ValidationError as error:
            raise BindRefused(
                f"Attributes of {definition.name} do not match its attribute model: {error}"
            ) from error

    def _render_facts(self, definition, attrs, obj, span, *, label: str, key) -> None:
        for rendered in render.render_facts(definition, attrs, label=label, key=key):
            self.fact_pending.append(
                _Pending(
                    order=(rendered.template, obj.canonical_key),
                    handle=f"fact:{obj.id}:{rendered.template}",
                    span=span,
                    text=rendered.text,
                    template=rendered.template,
                    title=label,
                    kind="rendered_fact",
                    mentions=(obj.id,),
                    object_id=obj.id,
                )
            )
        for skipped in render.skipped_fact_templates(definition, attrs):
            self.facts_skipped[skipped] = self.facts_skipped.get(skipped, 0) + 1

    def _bind_verbatim(self, batch: EmissionBatch) -> None:
        """Step 5: passages emitted verbatim, then the units sliced out of their spans."""
        for emission in batch.passages:
            span = self._span(emission.span)
            if token_count(span.text) > PASSAGE_CHAR_BOUND:
                raise BindRefused(
                    f"Passage {emission.key} has {token_count(span.text)} characters; "
                    f"split it at {PASSAGE_CHAR_BOUND} before emitting"
                )
            title = emission.title
            if emission.node is not None:
                title = self._passage_node_title(emission, span)
            self._check_passage_ts(emission, span)
            self.verbatim.append(((span.id, emission.key), span, title, span.text))
        for unit in batch.units:
            span = self._span(unit.span)
            text = span.text
            if unit.start is not None and unit.end is not None:
                if unit.end > len(text):
                    raise BindRefused(f"Unit {unit.key} offsets fall outside its span")
                text = text[unit.start : unit.end]
            self.slices.append(
                (
                    unit.passage,
                    {
                        "span": span,
                        "ordinal": unit.ordinal,
                        "kind": unit.kind,
                        "text": text,
                        "prefix": unit.prefix,
                        "mentions": self._mention_ids(unit.mentions),
                        # An edge that names this unit reuses its id (section 8.7).
                        "handle": f"unit:{unit.key}",
                    },
                )
            )

    def _passage_node_title(self, emission, span: k.EvidenceSpan) -> str:
        obj = keys.knowledge_object(
            self.registry,
            emission.node,
            workspace_id=self.context.workspace_id,
            instance=self.context.instance,
        )
        if self.observed_span.get(obj.id) != span.id:
            raise BindRefused(
                f"Passage {emission.key} names node {emission.node.kind}, but that node is "
                "observed on a different span; emit the node on the passage's span"
            )
        return emission.title

    def _check_passage_ts(self, emission, span: k.EvidenceSpan) -> None:
        """Deviation DV1: `Passage.ts` has no column, so the binder pins it to a known instant."""
        if emission.ts is None:
            return
        allowed = {self.revision.revision.source_updated_at}
        if emission.node is not None:
            obj = keys.knowledge_object(
                self.registry,
                emission.node,
                workspace_id=self.context.workspace_id,
                instance=self.context.instance,
            )
            allowed |= {
                observation.valid_from for observation in self.observations if observation.object_id == obj.id
            }
        if emission.ts not in allowed:
            raise BindRefused(
                f"Passage {emission.key} has a ts that is neither its node's valid_from nor the "
                "revision's source_updated_at; drop it or emit the node on this span"
            )

    def _bind_edges(self, batch: EmissionBatch) -> None:
        """Step 6: the checks, then the statement, then one version per fact with its groups."""
        validated = []
        for emission in batch.edges:
            definition = check_direction_and_ownership(
                self.registry,
                self.descriptor,
                emission.predicate,
                emission.subject.kind,
                emission.object.kind,
            )
            if emission.source not in definition.sources_allowed:
                raise BindRefused(
                    f"{emission.predicate} does not accept source {emission.source}; "
                    f"allowed: {sorted(definition.sources_allowed)}"
                )
            if emission.source == "reviewed":
                # Review CK7 finding F2. No built-in reaches this line any more, but an extension
                # predicate writes its own `sources_allowed` and `reviewed` is a registered source,
                # so this is the check that keeps `human_verified` out of the binder for good.
                raise BindRefused(
                    f"{emission.predicate}: reviewed is the reconciliation queue's source "
                    "(spec 4.3); emit the rule you derived the fact from"
                )
            if emission.valid_from is not None and not definition.windowed:
                raise BindRefused(f"{emission.predicate} is not windowed; drop valid_from/valid_to")
            subject, target = self._endpoint(emission.subject), self._endpoint(emission.object)
            statement = render.edge_statement(
                definition,
                (self.registry.object_kind(subject.kind), self.labels[subject.id]),
                (self.registry.object_kind(target.kind), self.labels[target.id]),
                source_statement=emission.source_statement,
                rule=emission.rule,
                rule_evidence=emission.rule_evidence,
            )
            validated.append((emission, definition, subject, target, statement))
        for emission, definition, subject, target, statement in validated:
            unit_id = self._edge_unit(emission, definition, subject, target, statement)
            self._edge_version(emission, definition, subject, target, statement, unit_id)
            self.edges += 1

    def _edge_unit(self, emission, definition, subject, target, statement: str) -> str | None:
        """A bare edge gets a `rendered_edge` unit; an edge that names a statement unit reuses it."""
        if emission.unit is not None:
            return f"unit:{emission.unit}"
        span = self._span(emission.support[0].spans[0])
        self.edge_pending.append(
            _Pending(
                order=(emission.predicate, subject.id, target.id),
                handle=f"rendered:{emission.predicate}:{subject.id}:{target.id}",
                span=span,
                text=statement,
                template=f"edge_statement@{render.RENDER_RULE_VERSION}",
                title=self.labels[subject.id],
                kind="rendered_edge",
                mentions=tuple(sorted({subject.id, target.id})),
                object_id=subject.id,
            )
        )
        return f"rendered:{emission.predicate}:{subject.id}:{target.id}"

    def _edge_version(self, emission, definition, subject, target, statement, unit_id) -> None:
        assertion = self._assertion(subject, emission.predicate, target)
        version = k.AssertionVersion(
            assertion_id=assertion.id,
            evidence_class=evidence_class(
                self.registry, emission.family, emission.source, emission.metadata_origin
            ),
            rule_version=self._rule_version(emission.rule),
            confidence=emission.weight,
            status="active",
            family=emission.family,
            source=emission.source,
            rule=emission.rule,
            weight=emission.weight,
            statement=statement,
            unit_id=unit_id,
            recorded_from=self.recorded_from,
            **_edge_timing(emission, definition),
        )
        self._add_version(emission, version)
        for support in emission.support:
            self._support_group(version, [self._span(span) for span in support.spans])

    def _add_version(self, emission, version: k.AssertionVersion) -> None:
        existing = self.versions.get(version.id)
        if existing is not None and (
            existing.statement != version.statement or existing.unit_id != version.unit_id
        ):
            raise BindRefused(
                f"Edge {emission.predicate} {version.assertion_id} is emitted twice with "
                "different statements; emit one EdgeEmission with two support groups"
            )
        self.versions[version.id] = version

    def _support_group(self, version: k.AssertionVersion, spans: list[k.EvidenceSpan]) -> None:
        group = text_hash(canonical_json(sorted(span.id for span in spans)))[:32]
        for span in spans:
            support = k.AssertionSupport(
                assertion_version_id=version.id, span_id=span.id, derivation_group=group
            )
            self.supports[(version.id, span.id, group)] = support

    def _bind_aliases(self, batch: EmissionBatch) -> None:
        """Section 8.8: an identity the connector can back with a rule, ordered by the S1 rule."""
        for emission in batch.aliases:
            first, second = self._endpoint(emission.a), self._endpoint(emission.b)
            if first.id == second.id:
                raise BindRefused("An alias needs two distinct objects")
            subject, target = sorted((first, second), key=lambda obj: (obj.canonical_key, obj.kind))
            definition = self.registry.predicate(IDENTITY_PREDICATE)
            statement = render.edge_statement(
                definition,
                (self.registry.object_kind(subject.kind), self.labels[subject.id]),
                (self.registry.object_kind(target.kind), self.labels[target.id]),
            )
            status = (
                "candidate" if frozenset({subject.kind, target.kind}) in GUARDED_ALIAS_PAIRS else "active"
            )
            span = self._span(emission.support[0].spans[0])
            self.edge_pending.append(
                _Pending(
                    order=(IDENTITY_PREDICATE, subject.id, target.id),
                    handle=f"rendered:{IDENTITY_PREDICATE}:{subject.id}:{target.id}",
                    span=span,
                    text=statement,
                    template=f"edge_statement@{render.RENDER_RULE_VERSION}",
                    title=self.labels[subject.id],
                    kind="rendered_edge",
                    mentions=tuple(sorted({subject.id, target.id})),
                    object_id=subject.id,
                )
            )
            assertion = self._assertion(subject, IDENTITY_PREDICATE, target)
            version = k.AssertionVersion(
                assertion_id=assertion.id,
                evidence_class="rule_derived",
                rule_version=f"{emission.rule}@{self.descriptor.version}",
                confidence=1.0,
                status=status,
                family="deterministic",
                source="rule",
                rule=emission.rule,
                weight=1.0,
                statement=statement,
                unit_id=f"rendered:{IDENTITY_PREDICATE}:{subject.id}:{target.id}",
                recorded_from=self.recorded_from,
                validity_kind="observed_snapshot",
                temporal_basis="observed",
                temporal_precision="instant",
            )
            self._add_version(emission, version)
            for support in emission.support:
                self._support_group(version, [self._span(span) for span in support.spans])
            self.coverage_aliases[status] = self.coverage_aliases.get(status, 0) + 1

    def _bind_hints(self, batch: EmissionBatch) -> None:
        """Section 9: coverage evidence that the owner's fact is expected; no record is written."""
        for hint in batch.hints:
            definition = self.registry.predicate(hint.predicate)
            if set(self.descriptor.families) & definition.owner_families:
                raise BindRefused(
                    f"{self.descriptor.name} owns {hint.predicate}; "
                    "emit the edge instead of a reverse-view hint"
                )
            try:
                validate_endpoints(hint.predicate, hint.subject.kind, hint.object.kind)
            except ValueError as error:
                raise BindRefused(str(error)) from error
            for support in hint.support:
                for span in support.spans:
                    self._span(span)
            self.coverage_hints[hint.predicate] = self.coverage_hints.get(hint.predicate, 0) + 1

    def _count_failures(self, batch: EmissionBatch) -> None:
        for failure in batch.failures:
            parser = failure.parser.spelling if failure.parser is not None else "-"
            name = f"{failure.family}|{parser}|{failure.dialect or '-'}"
            self.coverage_failures[name] = self.coverage_failures.get(name, 0) + failure.count

    # -------------------------------------------------------------- passages, units, members

    def _materialize(self, batch: EmissionBatch):
        """Assign passage ordinals, then build every `Unit` against its bound passage row."""
        rows: list[BoundPassageRow] = []
        by_key: dict[str, BoundPassageRow] = {}
        ordinal = 0
        for _order, span, title, text in sorted(self.verbatim, key=lambda row: row[0]):
            row = BoundPassageRow(
                generation=self.context.generation,
                span=span,
                view=None,
                ordinal=ordinal,
                title=title,
                text=text,
            )
            rows.append(row)
            by_key[_order[1]] = row
            ordinal += 1
        pending_units: list[tuple[BoundPassageRow, dict]] = []
        for pending in sorted(self.fact_pending, key=lambda item: item.order) + sorted(
            self.edge_pending, key=lambda item: item.order
        ):
            view = self._view(pending)
            row = BoundPassageRow(
                generation=self.context.generation,
                span=pending.span,
                view=view,
                ordinal=ordinal,
                title=pending.title,
                text=pending.text,
            )
            rows.append(row)
            ordinal += 1
            pending_units.append(
                (
                    row,
                    {
                        "span": pending.span,
                        "ordinal": 0,
                        "kind": pending.kind,
                        "text": pending.text,
                        "prefix": "",
                        "mentions": pending.mentions,
                        "template": pending.template,
                        "handle": pending.handle,
                    },
                )
            )
        for key, slice_unit in self.slices:
            row = by_key.get(key)
            if row is None:  # EmissionBatch already refuses a unit naming no passage
                raise BindRefused(f"Emission names missing passage {key!r}")
            pending_units.append((row, slice_unit))
        units: list[k.Unit] = []
        handles: dict[str, str] = {}
        for row, spec in pending_units:
            rendered = render.unit_text(
                spec["text"], prefix=spec.get("prefix", ""), template=spec.get("template")
            )
            unit = k.Unit(
                generation_id=self.context.generation.id,
                passage_id=row.id,
                span_id=spec["span"].id,
                ordinal=spec["ordinal"],
                kind=spec["kind"],
                text=rendered.text,
                prefix=rendered.prefix,
                embed_text=rendered.embed_text,
                mentions_json=canonical_json(list(spec["mentions"])),
                template=rendered.template,
            )
            units.append(unit)
            handles[spec["handle"]] = unit.id
            self.coverage_units[unit.kind] = self.coverage_units.get(unit.kind, 0) + 1
        self._resolve_unit_ids(handles)
        return tuple(rows), tuple(sorted(units, key=lambda unit: unit.id))

    def _resolve_unit_ids(self, handles: Mapping[str, str]) -> None:
        """Replace each version's unit handle with the id of the unit that was built (R66 (ii)).

        The reference is a name the reader may find missing after collection, never a lookup.
        """
        resolved = {}
        for version in self.versions.values():
            unit_id = handles.get(version.unit_id)
            if unit_id is None:
                raise BindRefused(f"Edge statement unit {version.unit_id!r} was not built")
            replaced = version.replace(unit_id=unit_id)
            resolved[replaced.id] = replaced
            self.supports = {
                (replaced.id if key[0] == version.id else key[0], key[1], key[2]): (
                    support.replace(assertion_version_id=replaced.id) if key[0] == version.id else support
                )
                for key, support in self.supports.items()
            }
        self.versions = resolved

    def _view(self, pending: _Pending) -> k.RetrievalView:
        """The derived passage's projection view, in `input_binding._view`'s shape (R6)."""
        generation = self.context.generation
        dependencies = (("span", pending.span.id, dependency_version(pending.span)),)
        profile = make_identity(
            "text_profile", [BINDER_VERSION, render.RENDER_RULE_VERSION, pending.template]
        )
        fingerprint = view_fingerprint(
            view_kind="projection",
            text=pending.text,
            text_profile=profile,
            vector_profile=generation.embedding_profile,
            rule_version=BINDER_VERSION,
            model_version=None,
            dependencies=dependencies,
        )
        derived = k.DerivedRecord(
            workspace_id=self.context.workspace_id,
            view_kind="projection",
            rule_version=BINDER_VERSION,
            input_revision_ids=(pending.span.revision_id,),
            dependency_fingerprint=fingerprint,
            state="ready",
        )
        self._derived[derived.id] = derived
        for kind, identity, version in dependencies:
            dependency = k.DerivedDependency(
                derived_record_id=derived.id, input_kind=kind, input_id=identity, input_version=version
            )
            self._dependencies[dependency.id] = dependency
        return k.RetrievalView(
            object_id=pending.object_id,
            span_id=pending.span.id,
            view_kind="projection",
            text=pending.text,
            text_profile=profile,
            vector_profile=generation.embedding_profile,
            source_revision_id=pending.span.revision_id,
            derivation_version=BINDER_VERSION,
            dependency_fingerprint=fingerprint,
            derived_record_id=derived.id,
        )

    def _derivations(self, views):
        return (
            self._sorted(self._derived.values()),
            self._sorted(self._dependencies.values()),
        )

    def _members(self, passages, units, views, derived_records, derived_dependencies):
        """Step 8: one member per generation-scoped record; identity-only records get none."""
        scoped = [
            ("EvidenceSpan", self.spans.values()),
            ("ObjectObservation", self.observations),
            ("AssertionVersion", self.versions.values()),
            ("AssertionSupport", self.supports.values()),
            ("Unit", units),
            ("RetrievalView", views),
            ("DerivedRecord", derived_records),
            ("DerivedDependency", derived_dependencies),
        ]
        members = [
            k.GenerationEvidenceMember(
                generation_id=self.context.generation.id, record_kind=kind, record_id=record.id
            )
            for kind, records in scoped
            for record in records
        ]
        return self._sorted(members)

    # -------------------------------------------------------------- shared helpers

    def _span(self, span_ref: SpanRef) -> k.EvidenceSpan:
        """Step 3: one `EvidenceSpan` per distinct locator, verified against the revision bytes."""
        locator_json = _canonical_locator(span_ref)
        existing = self.spans.get(locator_json)
        if existing is not None:
            if span_ref.text is not None and span_ref.text != existing.text:
                raise BindRefused(
                    f"Span text differs from the revision bytes at {span_ref.locator_kind} {locator_json}"
                )
            return existing
        text = verify_span(self.revision.data, span_ref, artifact=self.revision.artifact)
        span = k.EvidenceSpan(
            revision_id=self.revision.revision.id,
            locator_kind=span_ref.locator_kind,
            locator_json=locator_json,
            text=text,
            # Ruling R48: the policy of the revision's first capture, never the artifact's current
            # one, so a policy change never re-mints a stored span with different contents.
            policy_id=self.revision.span_policy_id,
        )
        self._record(span)
        self.spans[locator_json] = span
        return span

    def _endpoint(self, ref) -> k.KnowledgeObject:
        obj = keys.knowledge_object(
            self.registry,
            ref,
            workspace_id=self.context.workspace_id,
            instance=self.context.instance,
        )
        if obj.id not in self.objects:
            raise BindRefused(
                f"Edge endpoint {ref.kind} is not emitted as a node in this batch; "
                "emit it, identity-only if another family owns it"
            )
        return obj

    def _assertion(self, subject, predicate: str, target) -> k.Assertion:
        try:
            assertion = k.checked_assertion(subject, predicate, target, scope_key=self.context.scope_key)
        except ValueError as error:
            raise BindRefused(str(error)) from error
        self._record(assertion)
        self.assertions[assertion.id] = assertion
        return assertion

    def _mention_ids(self, refs) -> tuple[str, ...]:
        ids = {
            keys.knowledge_object(
                self.registry,
                ref,
                workspace_id=self.context.workspace_id,
                instance=self.context.instance,
            ).id
            for ref in refs
        }
        return tuple(sorted(ids))

    def _rule_version(self, rule: str | None) -> str:
        spelling = f"{self.descriptor.name}@{self.descriptor.version}"
        return f"{spelling}#{rule}" if rule is not None else spelling

    def _record(self, record) -> None:
        """Ruling R39: vocabulary is checked where a record is built, never where one is read."""
        try:
            self.registry.check_record(record)
        except ValueError as error:
            raise BindRefused(str(error)) from error

    @staticmethod
    def _sorted(records: Iterable):
        return tuple(sorted(records, key=lambda record: record.id))


def _every_span(batch: EmissionBatch):
    for emission in batch.nodes:
        yield emission.span
    for emission in batch.passages:
        yield emission.span
    for unit in batch.units:
        yield unit.span
    for group in (*batch.edges, *batch.aliases, *batch.hints):
        for support in group.support:
            yield from support.spans
    for failure in batch.failures:
        if failure.span is not None:
            yield failure.span


def _node_timing(emission) -> dict:
    """Section 8.2's `Node.ts` row: an explicit interval, or the observed snapshot of `code_binding`."""
    if emission.ts is None:
        return {
            "validity_kind": "observed_snapshot",
            "temporal_basis": "observed",
            "temporal_precision": "instant",
        }
    return {
        "valid_from": emission.ts,
        "validity_kind": "explicit_interval",
        "temporal_basis": "source_explicit",
        "temporal_precision": emission.ts_precision,
        "source_timestamp_original": emission.ts_original,
        "source_timezone": emission.ts_timezone,
    }


def _edge_timing(emission, definition: PredicateDefinition) -> dict:
    """A windowed predicate without a window is `unknown`; an unwindowed one is a snapshot."""
    if emission.valid_from is not None:
        return {
            "valid_from": emission.valid_from,
            "valid_to": emission.valid_to,
            "validity_kind": "explicit_interval",
            "temporal_basis": "source_explicit",
            "temporal_precision": emission.window_precision,
        }
    if definition.windowed:
        return {"validity_kind": "unknown", "temporal_basis": "unknown"}
    return {
        "validity_kind": "observed_snapshot",
        "temporal_basis": "observed",
        "temporal_precision": "instant",
    }


# ------------------------------------------------------------------ merging (section 8.6)


def merge_bound(batches: Iterable[BoundBatch]) -> BoundBatch:
    """Merge per-revision results for one generation, refusing two contents under one id.

    The store refuses a same-id record with different contents (`store/knowledge.py:772`), so the
    one sanctioned difference is an `AssertionVersion`'s `statement` and `unit_id`, which are
    outside its identity: the version of the lexically smallest `(revision_id, derivation_group)`
    is kept, with every support group of all of them.
    """
    batches = list(batches)
    if not batches:
        raise BindRefused("merge_bound needs at least one bound batch")
    generation_ids = {bound.generation_id for bound in batches}
    if len(generation_ids) != 1:
        raise BindRefused("merge_bound merges one generation's batches")
    merged: dict[str, dict] = {name: {} for name in _MERGED_FIELDS}
    versions: dict[str, tuple[tuple, k.AssertionVersion]] = {}
    coverage = EmissionCoverage()
    revision_ids: list[str] = []
    for bound in batches:
        revision_ids.extend(bound.revision_ids)
        coverage = coverage + bound.coverage
        for name in _MERGED_FIELDS:
            for record in getattr(bound, name):
                _merge_record(merged[name], record, name)
        rank = (min(bound.revision_ids), min((s.derivation_group for s in bound.supports), default=""))
        for version in bound.versions:
            _merge_version(versions, version, rank)
    ordered = {name: tuple(sorted(records.values(), key=lambda r: r.id)) for name, records in merged.items()}
    return BoundBatch(
        generation_id=generation_ids.pop(),
        revision_ids=tuple(sorted(set(revision_ids))),
        versions=tuple(sorted((version for _rank, version in versions.values()), key=lambda r: r.id)),
        coverage=coverage,
        **ordered,
    )


_MERGED_FIELDS = (
    "spans",
    "objects",
    "observations",
    "assertions",
    "supports",
    "passages",
    "units",
    "views",
    "derived_records",
    "derived_dependencies",
    "evidence_members",
)


def _merge_record(into: dict, record, name: str) -> None:
    existing = into.get(record.id)
    if existing is not None and existing != record:
        raise BindRefused(f"Two revisions bind {type(record).__name__} {record.id} with different contents")
    into[record.id] = record


def _merge_version(into: dict, version: k.AssertionVersion, rank: tuple) -> None:
    existing = into.get(version.id)
    if existing is None:
        into[version.id] = (rank, version)
        return
    kept_rank, kept = existing
    if kept.replace(statement=None, unit_id=None) != version.replace(statement=None, unit_id=None):
        raise BindRefused(f"Two revisions bind AssertionVersion {version.id} with different contents")
    if rank < kept_rank:
        into[version.id] = (rank, version)
