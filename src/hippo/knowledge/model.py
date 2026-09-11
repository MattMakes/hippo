"""Immutable version-one evidence, maintenance and query contracts.

Payload JSON is canonical text, collections are tuples, and nested models are frozen.
`replace` validates updates; `model_copy(update=...)` is disabled because Pydantic's
normal copy API bypasses validation. Persisted IDs are derived from typed canonical
keys, never supplied independently. Cross-record existence, workspace chains, policy
visibility, fencing and publication transactions are store responsibilities.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Annotated, ClassVar, Literal, Self, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .identity import (
    canonical_json,
    make_identity,
    normalize_json,
    normalize_provider_url,
    normalize_relative_path,
    source_relative_path,
    text_hash,
)
from .predicates import OBJECT_KINDS, PREDICATES, validate_endpoints

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Json = Annotated[str, BeforeValidator(normalize_json)]
Code = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")]
Nonnegative = Annotated[int, Field(strict=True, ge=0)]
Positive = Annotated[int, Field(strict=True, ge=1)]
VersionOne = Annotated[int, Field(strict=True, ge=1, le=1)]
EvidenceClass = Literal[
    "syntax_observed", "catalog_observed", "declared", "discussion_claim", "model_inferred", "human_verified"
]
ValidityKind = Literal["explicit_interval", "observed_snapshot", "atemporal", "unknown"]
TemporalBasis = Literal[
    "source_explicit", "provider_snapshot", "commit", "catalog_snapshot", "observed", "atemporal", "unknown"
]
TemporalPrecision = Literal["instant", "second", "minute", "day", "month", "year", "unknown"]
Lifecycle = Literal["active", "draft", "accepted", "rejected", "superseded", "deleted", "unknown"]
WorkState = Literal["pending", "running", "ready", "failed", "retry", "completed", "cancelled"]
ObjectKind = Literal[
    "service",
    "api",
    "endpoint",
    "owner",
    "team",
    "person",
    "group",
    "user",
    "system",
    "domain",
    "resource",
    "repository",
    "file",
    "symbol",
    "commit",
    "database",
    "schema",
    "table",
    "column",
    "view",
    "constraint",
    "index",
    "routine",
    "requirement",
    "criterion",
    "ticket",
    "review",
    "decision",
    "document",
    "alias",
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must carry a timezone")
    return value.astimezone(UTC)


Instant = Annotated[datetime, AfterValidator(_utc)]
RelativePath = Annotated[str, AfterValidator(normalize_relative_path)]
ProviderURL = Annotated[str, AfterValidator(normalize_provider_url)]


class Contract(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, revalidate_instances="always", validate_default=True
    )

    def replace(self, **changes) -> Self:
        return type(self).model_validate(self.model_dump() | changes)

    def model_copy(self, *, update=None, deep=False) -> Self:
        if update:
            return self.replace(**update)
        return type(self).model_validate(self.model_dump())


class Record(Contract):
    id: Text = "pending"
    identity_key: Json = "[]"
    identity_fields: ClassVar[tuple[str, ...]] = ()
    identity_prefix: ClassVar[str | None] = None

    def identity_parts(self) -> list:
        data = self.model_dump(mode="json")
        return [data[name] for name in self.identity_fields]

    @model_validator(mode="after")
    def canonical_id(self) -> Self:
        prefix = self.identity_prefix or self.__class__.__name__.lower()
        parts = self.identity_parts()
        key = canonical_json(parts)
        if self.identity_key != "[]" and self.identity_key != key:
            raise ValueError("Stored identity key disagrees with canonical record fields")
        expected = make_identity(prefix, parts)
        if self.id != "pending" and self.id != expected:
            raise ValueError("Record id does not match its canonical identity")
        object.__setattr__(self, "id", expected)
        object.__setattr__(self, "identity_key", key)
        return self

    def replace(self, **changes) -> Self:
        data = self.model_dump() | changes
        if "id" not in changes:
            data.pop("id")
        if "identity_key" not in changes:
            data.pop("identity_key")
        return type(self).model_validate(data)


class FileLinesLocator(Contract):
    kind: Literal["file_lines"] = "file_lines"
    path: RelativePath
    start: Positive
    end: Positive

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("Line interval is reversed")
        return self


class SectionLocator(Contract):
    kind: Literal["section"] = "section"
    heading_path: tuple[Text, ...]
    block_start: Nonnegative
    block_end: Nonnegative

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.block_end < self.block_start:
            raise ValueError("Block interval is reversed")
        return self


class FieldLocator(Contract):
    kind: Literal["field"] = "field"
    field_path: Text


class CommentLocator(Contract):
    kind: Literal["comment"] = "comment"
    comment_id: Text
    field_path: Text = "body"
    changeset_id: Text | None = None


class PageLocator(Contract):
    kind: Literal["page"] = "page"
    page: Positive
    offset_start: Nonnegative = 0
    offset_end: Nonnegative | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.offset_end is not None and self.offset_end < self.offset_start:
            raise ValueError("Page offsets are reversed")
        return self


class TableCellLocator(Contract):
    kind: Literal["table_cell"] = "table_cell"
    table: Nonnegative
    row: Nonnegative
    column: Nonnegative
    heading_path: tuple[Text, ...] = ()


class DiffHunkLocator(FileLinesLocator):
    kind: Literal["diff_hunk"] = "diff_hunk"
    base_revision: Text
    head_revision: Text
    side: Literal["base", "head"]
    hunk_id: Text | None = None


SourceLocator = Annotated[
    FileLinesLocator
    | SectionLocator
    | FieldLocator
    | CommentLocator
    | PageLocator
    | TableCellLocator
    | DiffHunkLocator,
    Field(discriminator="kind"),
]
LOCATOR_ADAPTER = TypeAdapter(SourceLocator)


def canonical_locator_json(value: str) -> str:
    """Validate coordinates, normalize paths, and materialize every default."""
    locator = LOCATOR_ADAPTER.validate_json(normalize_json(value))
    return canonical_json(locator.model_dump(mode="json"))


class Workspace(Record):
    name: Text
    identity_fields = ("name",)


class WorkspaceMembership(Record):
    workspace_id: Text
    principal_id: Text
    enabled: bool
    mapping_authority: Text
    policy_epoch: Nonnegative
    identity_fields = ("workspace_id", "principal_id")


class GroupMembership(Record):
    workspace_id: Text
    group_id: Text
    principal_id: Text
    enabled: bool
    mapping_authority: Text
    policy_epoch: Nonnegative
    identity_fields = ("workspace_id", "group_id", "principal_id")


class Connector(Record):
    workspace_id: Text
    kind: Literal["local", "git", "github", "gitlab", "jira_cloud", "jira_data_center", "tuleap", "backstage"]
    instance_url: ProviderURL
    config_json: Json = "{}"
    credential_ref: Text | None = None
    enabled: bool = False
    capabilities_json: Json = "{}"
    identity_fields = ("workspace_id", "kind", "instance_url")


class Artifact(Record):
    workspace_id: Text
    source_id: Text
    connector_id: Text | None = None
    provider_instance: ProviderURL | None = None
    kind: Literal[
        "file",
        "repository",
        "ticket",
        "comment",
        "attachment",
        "review",
        "schema_snapshot",
        "catalog_entity",
        "document",
        "manifest",
        "openapi",
        "history_event",
    ]
    external_id: Text
    canonical_uri: Text
    policy_id: Text
    deleted_at: Instant | None = None
    identity_fields = ("workspace_id", "connector_id", "kind", "external_id")

    def identity_parts(self) -> list:
        # A remote object survives moving between logical Sources. Local file
        # identity is source-scoped because it has no immutable provider identity.
        return [self.workspace_id, self.provider_instance or self.source_id, self.kind, self.external_id]

    @model_validator(mode="after")
    def provider_and_path(self) -> Self:
        if (self.connector_id is None) != (self.provider_instance is None):
            raise ValueError("Remote artifacts require both connector and normalized provider instance")
        if self.connector_id is None and self.kind == "file":
            if normalize_relative_path(self.external_id) != self.external_id:
                raise ValueError("Local artifact paths must be normalized by local_artifact")
        return self


def local_artifact(*, workspace_id: str, source_id: str, root, path: str, policy_id: str) -> Artifact:
    relative = source_relative_path(root, path)
    return Artifact(
        workspace_id=workspace_id,
        source_id=source_id,
        kind="file",
        external_id=relative,
        canonical_uri=f"source:{source_id}/{relative}",
        policy_id=policy_id,
    )


class ArtifactRevision(Record):
    artifact_id: Text
    provider_revision: Text | None = None
    content_hash: Text
    raw_uri: Text
    source_updated_at: Instant | None = None
    source_timestamp_original: Text | None = None
    source_timezone: Text | None = None
    source_precision: TemporalPrecision = "unknown"
    observed_at: Instant
    lifecycle: Lifecycle
    metadata_json: Json = "{}"
    identity_prefix = "revision"
    identity_fields = ("artifact_id", "provider_revision", "content_hash")


class Generation(Record):
    source_id: Text
    parent_id: Text | None = None
    status: Literal["staging", "ready", "active", "retired", "failed"]
    parser_version: Text
    linker_version: Text
    embedding_profile: Text
    created_at: Instant
    published_at: Instant | None = None
    manifest_hash: Text
    coverage_json: Json = "{}"
    identity_fields = (
        "source_id",
        "parent_id",
        "manifest_hash",
        "parser_version",
        "linker_version",
        "embedding_profile",
    )

    @model_validator(mode="after")
    def publication(self) -> Self:
        if self.published_at is not None and self.published_at < self.created_at:
            raise ValueError("Publication precedes generation creation")
        if self.status == "active" and self.published_at is None:
            raise ValueError("Active generation requires publication time")
        return self


class GenerationMember(Record):
    generation_id: Text
    artifact_revision_id: Text
    identity_fields = ("generation_id", "artifact_revision_id")


class GenerationEvidenceMember(Record):
    generation_id: Text
    record_kind: Literal[
        "EvidenceSpan",
        "ObjectObservation",
        "AssertionVersion",
        "AssertionSupport",
        "Section",
        "SectionMember",
        "RetrievalView",
        "ProseExtraction",
        "DerivedRecord",
        "DerivedDependency",
        "ConflictSet",
        "Alias",
    ]
    record_id: Text
    identity_fields = ("generation_id", "record_kind", "record_id")


class EvidenceSpan(Record):
    revision_id: Text
    locator_kind: Literal["file_lines", "section", "field", "comment", "page", "table_cell", "diff_hunk"]
    locator_json: Json
    text_hash: Text = "pending"
    text: str
    policy_id: Text
    identity_prefix = "span"
    identity_fields = ("revision_id", "locator_json", "text_hash")

    @field_validator("locator_json")
    @classmethod
    def canonical_locator(cls, value):
        return canonical_locator_json(value)

    @model_validator(mode="before")
    @classmethod
    def check_text_hash(cls, values):
        if isinstance(values, dict) and isinstance(values.get("text"), str):
            expected = text_hash(values["text"])
            if values.get("text_hash", expected) != expected:
                raise ValueError("Evidence text hash does not match original text")
            values = values | {"text_hash": expected}
        return values

    def identity_parts(self) -> list:
        return [self.revision_id, json.loads(self.locator_json), self.text_hash]

    @model_validator(mode="after")
    def valid_locator(self) -> Self:
        locator = LOCATOR_ADAPTER.validate_json(self.locator_json)
        if locator.kind != self.locator_kind:
            raise ValueError("Locator kind disagrees with its payload")
        return self


class KnowledgeObject(Record):
    workspace_id: Text
    kind: ObjectKind
    canonical_key: Json
    identity_prefix = "object"
    identity_fields = ("workspace_id", "kind", "canonical_key")

    @field_validator("canonical_key")
    @classmethod
    def array_key(cls, value):
        if not isinstance(json.loads(value), list):
            raise ValueError("Canonical object key must be a JSON array")
        return value

    def identity_parts(self) -> list:
        return [self.workspace_id, self.kind, json.loads(self.canonical_key)]


class TemporalRecord(Record):
    valid_from: Instant | None = None
    valid_to: Instant | None = None
    validity_kind: ValidityKind = "unknown"
    recorded_from: Instant
    recorded_to: Instant | None = None
    temporal_basis: TemporalBasis = "unknown"
    temporal_precision: TemporalPrecision = "unknown"
    source_timestamp_original: Text | None = None
    source_timezone: Text | None = None

    @model_validator(mode="after")
    def intervals(self) -> Self:
        if self.valid_from is not None and self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("Effective interval must have positive half-open extent")
        if self.recorded_to is not None and self.recorded_to <= self.recorded_from:
            raise ValueError("Recorded interval must have positive half-open extent")
        if self.validity_kind != "explicit_interval" and (
            self.valid_from is not None or self.valid_to is not None
        ):
            raise ValueError("Effective bounds require explicit-interval provenance")
        return self


class ObjectObservation(TemporalRecord):
    object_id: Text
    revision_id: Text
    span_id: Text
    attributes_json: Json = "{}"
    evidence_class: EvidenceClass
    identity_fields = (
        "object_id",
        "revision_id",
        "span_id",
        "attributes_json",
        "evidence_class",
        "valid_from",
        "valid_to",
        "validity_kind",
        "recorded_from",
        "temporal_basis",
        "temporal_precision",
    )


class Assertion(Record):
    workspace_id: Text
    subject_id: Text
    predicate: Text
    object_id: Text
    scope_key: Text
    identity_fields = ("workspace_id", "subject_id", "predicate", "object_id", "scope_key")

    @field_validator("predicate")
    @classmethod
    def registered_predicate(cls, value):
        if value not in PREDICATES:
            raise ValueError("Unknown assertion predicate")
        return value

    def validate_endpoints(self, subject: KnowledgeObject, target: KnowledgeObject) -> None:
        if subject.id != self.subject_id or target.id != self.object_id:
            raise ValueError("Assertion endpoints do not match supplied objects")
        if subject.workspace_id != self.workspace_id or target.workspace_id != self.workspace_id:
            raise ValueError("Assertion endpoints must share its workspace")
        validate_endpoints(self.predicate, subject.kind, target.kind)


def checked_assertion(
    subject: KnowledgeObject, predicate: str, target: KnowledgeObject, *, scope_key: str
) -> Assertion:
    assertion = Assertion(
        workspace_id=subject.workspace_id,
        subject_id=subject.id,
        predicate=predicate,
        object_id=target.id,
        scope_key=scope_key,
    )
    assertion.validate_endpoints(subject, target)
    return assertion


class AssertionVersion(TemporalRecord):
    assertion_id: Text
    evidence_class: EvidenceClass
    rule_version: Text
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    status: Literal["active", "candidate", "retracted", "superseded", "disputed"]
    identity_fields = (
        "assertion_id",
        "evidence_class",
        "rule_version",
        "confidence",
        "status",
        "valid_from",
        "valid_to",
        "validity_kind",
        "recorded_from",
        "temporal_basis",
        "temporal_precision",
    )

    @field_validator("confidence", mode="before")
    @classmethod
    def no_boolean_confidence(cls, value):
        if isinstance(value, bool):
            raise ValueError("Confidence must be numeric, not boolean")
        return value


class AssertionSupport(Record):
    assertion_version_id: Text
    span_id: Text
    derivation_group: Text
    identity_fields = ("assertion_version_id", "span_id", "derivation_group")


class SupportGroup(Contract):
    derivation_group: Text
    span_ids: Annotated[tuple[Text, ...], Field(min_length=1)]

    @field_validator("span_ids")
    @classmethod
    def unique_spans(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Duplicate span in support group")
        return values


class SupportGroups(Contract):
    groups: Annotated[tuple[SupportGroup, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_groups(self) -> Self:
        if len({group.derivation_group for group in self.groups}) != len(self.groups):
            raise ValueError("Duplicate derivation group")
        return self

    def satisfied_by(self, applicable_visible_span_ids: frozenset[str]) -> bool:
        return any(set(group.span_ids) <= applicable_visible_span_ids for group in self.groups)


class NativeBinding(Record):
    generation_id: Text
    object_id: Text
    native_kind: Literal["Symbol", "DataObject", "Commit"]
    native_id: Text
    span_id: Text
    identity_fields = ("generation_id", "object_id", "native_kind", "native_id", "span_id")


class ColumnPair(Contract):
    source_column_id: Text
    target_column_id: Text


class ForeignKeyMapping(Contract):
    constraint_id: Text
    source_table_id: Text
    target_table_id: Text
    columns: Annotated[tuple[ColumnPair, ...], Field(min_length=1)]
    target_key_id: Text | None = None
    on_update: Literal["NO ACTION", "RESTRICT", "CASCADE", "SET NULL", "SET DEFAULT"] = "NO ACTION"
    on_delete: Literal["NO ACTION", "RESTRICT", "CASCADE", "SET NULL", "SET DEFAULT"] = "NO ACTION"

    @model_validator(mode="after")
    def unique_columns(self) -> Self:
        if len({pair.source_column_id for pair in self.columns}) != len(self.columns) or len(
            {pair.target_column_id for pair in self.columns}
        ) != len(self.columns):
            raise ValueError("FK column mapping cannot repeat a column")
        return self


class AccessPolicy(Record):
    workspace_id: Text
    origin: Literal["legacy_unknown", "local_curated", "provider"] = "legacy_unknown"
    scope_key: Text | None = None
    mode: Literal["unknown", "restricted", "workspace"] = "unknown"
    allow_users: tuple[Text, ...] = ()
    allow_groups: tuple[Text, ...] = ()
    deny_users: tuple[Text, ...] = ()
    deny_groups: tuple[Text, ...] = ()
    verified_at: Instant
    expires_at: Instant | None = None
    identity_fields = ("workspace_id", "mode", "allow_users", "allow_groups", "deny_users", "deny_groups")

    def identity_parts(self) -> list:
        parts = super().identity_parts()
        if self.origin == "legacy_unknown":
            if self.scope_key is not None:
                raise ValueError("Legacy policy origin cannot declare a scope")
            return parts
        if self.scope_key is None:
            raise ValueError("Explicit policy origin requires a scope_key")
        return [*parts, self.origin, self.scope_key]

    @model_validator(mode="after")
    def expiry(self) -> Self:
        if self.expires_at is not None and self.expires_at <= self.verified_at:
            raise ValueError("Policy expiry must follow verification")
        return self


class SyncState(Record):
    connector_id: Text
    partition_key: Text
    cursor_json: Json = "{}"
    watermark: Text | None = None
    last_success_at: Instant | None = None
    last_reconciled_at: Instant | None = None
    error_code: Code | None = None
    identity_fields = ("connector_id", "partition_key")


class LeasedWork(Record):
    source_id: Text
    scope_key: Text
    phase: Literal[
        "queued",
        "fetch",
        "extract",
        "index",
        "validate",
        "publish",
        "invalidate",
        "reconcile",
        "repair",
        "complete",
    ]
    expected_parent_id: Text | None = None
    cursor_json: Json = "{}"
    lease_owner: Text | None = None
    lease_expires_at: Instant | None = None
    fencing_token: Nonnegative = 0
    attempt_count: Nonnegative = 0
    retry_at: Instant | None = None
    input_fingerprint: Text
    error_code: Code | None = None
    status: WorkState = "pending"

    @model_validator(mode="after")
    def lease_pair(self) -> Self:
        if (self.lease_owner is None) != (self.lease_expires_at is None):
            raise ValueError("Lease owner and expiry must appear together")
        if self.lease_owner is not None and self.fencing_token == 0:
            raise ValueError("Acquired lease requires a positive fencing token")
        return self


class SyncRun(LeasedWork):
    connector_id: Text
    run_key: Text
    identity_fields = ("connector_id", "source_id", "scope_key", "run_key", "input_fingerprint")


class MaintenanceJob(LeasedWork):
    kind: Literal["sync", "rebuild", "invalidate", "reconcile", "repair", "collect", "purge"]
    job_key: Text
    identity_fields = ("source_id", "scope_key", "kind", "job_key", "input_fingerprint")


class SourceEvent(Record):
    connector_id: Text
    artifact_id: Text
    provider_instance: ProviderURL
    provider_artifact_id: Text
    delivery_id: Text
    provider_revision: Text | None = None
    provider_sequence: Text | None = None
    operation: Literal["upsert", "delete", "access_change", "restore", "reconcile"]
    received_at: Instant
    payload_hash: Text
    acceptance_state: Literal["pending", "accepted", "duplicate", "stale", "quarantined", "rejected"] = (
        "pending"
    )
    dedupe_key: Text
    identity_fields = ("connector_id", "dedupe_key")


class RepresentationChecksum(Contract):
    kind: Text
    checksum: Text
    row_count: Nonnegative
    ready: bool


class IndexManifest(Record):
    generation_id: Text
    profile_fingerprint: Text
    config_fingerprint: Text
    required_representations: tuple[Text, ...]
    checksums: tuple[RepresentationChecksum, ...]
    ready: bool
    missing_optional: tuple[Text, ...] = ()
    identity_fields = (
        "generation_id",
        "profile_fingerprint",
        "config_fingerprint",
        "required_representations",
        "checksums",
        "missing_optional",
    )

    @model_validator(mode="after")
    def complete(self) -> Self:
        kinds = [item.kind for item in self.checksums]
        if len(set(kinds)) != len(kinds):
            raise ValueError("Duplicate representation checksum")
        if self.ready and not set(self.required_representations) <= {
            item.kind for item in self.checksums if item.ready
        }:
            raise ValueError("Ready manifest is missing required representations")
        if set(self.required_representations) & set(self.missing_optional):
            raise ValueError("Required representation cannot be optional")
        return self


class LinkGeneration(Record):
    workspace_id: Text
    input_manifest_hash: Text
    linker_version: Text
    assertion_version_ids: tuple[Text, ...]
    coverage_json: Json = "{}"
    created_at: Instant
    identity_fields = ("workspace_id", "input_manifest_hash", "linker_version", "assertion_version_ids")


class HistoryManifest(Record):
    workspace_id: Text
    revision_ids: tuple[Text, ...]
    assertion_version_ids: tuple[Text, ...]
    link_generation_ids: tuple[Text, ...]
    knowledge_cutoff: Instant
    temporal_selector_json: Json
    coverage_json: Json = "{}"
    retention_gaps: tuple[Text, ...] = ()
    identity_fields = (
        "workspace_id",
        "revision_ids",
        "assertion_version_ids",
        "link_generation_ids",
        "knowledge_cutoff",
        "temporal_selector_json",
        "retention_gaps",
    )

    @field_validator("temporal_selector_json")
    @classmethod
    def selector_contract(cls, value):
        TypeAdapter(TemporalSelector).validate_json(value)
        return value

    @model_validator(mode="after")
    def consistent_knowledge_cutoff(self) -> Self:
        selector = TypeAdapter(TemporalSelector).validate_json(self.temporal_selector_json)
        validate_knowledge_cutoff(selector, self.knowledge_cutoff)
        return self


ViewKind = Literal[
    "exact",
    "lexical",
    "dense",
    "passage",
    "table_card",
    "column_card",
    "constraint_card",
    "schema_card",
    "view_card",
    "routine_card",
    "symbol_signature",
    "symbol_body",
    "symbol_documentation",
    "section",
    "summary",
    "link",
    "projection",
    "saved_answer",
    "evaluation",
    "experience",
]


class DerivedRecord(Record):
    workspace_id: Text
    view_kind: ViewKind
    rule_version: Text
    model_version: Text | None = None
    input_revision_ids: tuple[Text, ...]
    input_binding_ids: tuple[Text, ...] = ()
    dependency_fingerprint: Text
    state: Literal["dirty", "ready", "retired"]
    identity_fields = (
        "workspace_id",
        "view_kind",
        "rule_version",
        "model_version",
        "input_revision_ids",
        "input_binding_ids",
        "dependency_fingerprint",
    )


class DerivedDependency(Record):
    derived_record_id: Text
    input_kind: Literal[
        "revision",
        "span",
        "binding",
        "assertion_version",
        "policy",
        "generation",
        "link_generation",
        "derived_record",
    ]
    input_id: Text
    input_version: Text
    identity_fields = ("derived_record_id", "input_kind", "input_id", "input_version")


class Suppression(Record):
    workspace_id: Text
    target_kind: Literal[
        "source", "artifact", "revision", "span", "assertion_version", "derived_record", "policy"
    ]
    target_id: Text
    scope_key: Text
    principal_ids: tuple[Text, ...] = ()
    all_principals: bool = True
    view_applicability: Literal["current_only", "all_history"]
    reason: Literal["access_loss", "tombstone", "purge"]
    epoch: Positive
    created_at: Instant
    restoration_barrier: Text
    identity_fields = (
        "workspace_id",
        "target_kind",
        "target_id",
        "scope_key",
        "principal_ids",
        "all_principals",
        "view_applicability",
        "reason",
        "epoch",
    )

    @model_validator(mode="after")
    def applicability(self) -> Self:
        if self.all_principals == bool(self.principal_ids):
            raise ValueError("Suppression must target all principals or an explicit nonempty set")
        if self.reason in {"access_loss", "purge"} and self.view_applicability != "all_history":
            raise ValueError("Access loss and purge must suppress all historical views")
        return self


RemovalStatus = Literal["pending", "removed", "absent", "failed"]


class PurgeJob(Record):
    workspace_id: Text
    scope_key: Text
    request_key: Text
    phase: Literal["suppress", "inventory", "remove", "verify", "complete", "failed"]
    removal_manifest_ids: tuple[Text, ...]
    raw_status: RemovalStatus
    derived_status: RemovalStatus
    saved_output_status: RemovalStatus
    backup_disposition: Literal["pending", "not_present", "destroyed", "replay_suppression_required"]
    audit_code: Code
    created_at: Instant
    completed_at: Instant | None = None
    identity_fields = ("workspace_id", "scope_key", "request_key")

    @model_validator(mode="after")
    def completed(self) -> Self:
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("Purge completion precedes creation")
        if self.phase == "complete" and (
            self.completed_at is None
            or any(
                status not in {"removed", "absent"}
                for status in (self.raw_status, self.derived_status, self.saved_output_status)
            )
            or self.backup_disposition == "pending"
        ):
            raise ValueError("Completed purge requires verified removals and backup disposition")
        return self


class IndexEvent(Record):
    workspace_id: Text
    generation_id: Text | None = None
    kind: Literal["published", "invalidated", "suppressed", "purged", "policy_changed", "restored"]
    payload_json: Json = "{}"
    state: Literal["pending", "delivered", "failed"] = "pending"
    aggregate_id: Text
    sequence: Positive
    dedupe_key: Text
    created_at: Instant
    identity_fields = ("workspace_id", "aggregate_id", "sequence", "dedupe_key")


class ConsumerAck(Record):
    event_id: Text
    consumer_id: Text
    state: Literal["pending", "running", "acknowledged", "retry", "failed"]
    attempt_count: Nonnegative = 0
    lease_owner: Text | None = None
    lease_expires_at: Instant | None = None
    fencing_token: Nonnegative = 0
    retry_at: Instant | None = None
    acknowledged_at: Instant | None = None
    identity_fields = ("event_id", "consumer_id")

    @model_validator(mode="after")
    def lease_pair(self) -> Self:
        if (self.lease_owner is None) != (self.lease_expires_at is None):
            raise ValueError("Consumer lease requires owner and expiry")
        if self.lease_owner is not None and self.fencing_token == 0:
            raise ValueError("Consumer lease requires positive fencing token")
        if self.state == "acknowledged" and self.acknowledged_at is None:
            raise ValueError("Acknowledged consumer requires its receipt timestamp")
        return self


class RetrievalView(Record):
    object_id: Text | None = None
    span_id: Text
    view_kind: ViewKind
    text: str
    text_profile: Text
    vector_profile: Text | None = None
    source_revision_id: Text
    derivation_version: Text
    dependency_fingerprint: Text
    derived_record_id: Text | None = None
    identity_fields = (
        "object_id",
        "span_id",
        "view_kind",
        "text_profile",
        "vector_profile",
        "source_revision_id",
        "derivation_version",
        "dependency_fingerprint",
    )


def _prose_vector(value):
    import math
    import struct

    if not isinstance(value, (tuple, list)) or not value or any(type(v) not in (int, float) for v in value):
        raise ValueError("Prose vector requires finite numeric values")
    try:
        result = tuple(struct.unpack("f", struct.pack("f", v))[0] for v in value)
    except (OverflowError, TypeError) as error:
        raise ValueError("Invalid prose vector") from error
    if not all(math.isfinite(v) for v in result):
        raise ValueError("Prose vector must be finite")
    return result


ProseVector = Annotated[tuple[float, ...], BeforeValidator(_prose_vector)]


class ProseEntity(Contract):
    name: Text
    embedding: ProseVector


class ProseTriple(Contract):
    subject: Text
    predicate: Text
    object: Text
    embedding: ProseVector


class ProseExtractionPayload(Contract):
    schema_version: VersionOne = 1
    evidence_class: Literal["model_inferred"] = "model_inferred"
    entities: tuple[ProseEntity, ...] = ()
    triples: tuple[ProseTriple, ...] = ()

    @model_validator(mode="after")
    def canonical_output(self) -> Self:
        from ..hipporag.text import clean_phrase

        entities = {}
        triples = {}
        for row in self.entities:
            if row.name != clean_phrase(row.name):
                raise ValueError("Entity name requires normalized text")
            if row.name in entities and entities[row.name] != row:
                raise ValueError("Conflicting entity vectors")
            entities[row.name] = row
        for row in self.triples:
            key = (row.subject, row.predicate, row.object)
            if any(value != clean_phrase(value) for value in key):
                raise ValueError("Triple requires normalized text")
            if not {row.subject, row.object} <= entities.keys():
                raise ValueError("Triple endpoint missing from entities")
            if key in triples and triples[key] != row:
                raise ValueError("Conflicting triple vectors")
            triples[key] = row
        if len({len(row.embedding) for row in (*entities.values(), *triples.values())}) > 1:
            raise ValueError("Prose vector dimensions differ")
        object.__setattr__(self, "entities", tuple(entities[key] for key in sorted(entities)))
        object.__setattr__(self, "triples", tuple(triples[key] for key in sorted(triples)))
        return self


class ProseExtraction(Record):
    generation_id: Text
    derived_record_id: Text
    input_kind: Literal["span", "view"]
    input_id: Text
    input_text_hash: Text
    support_passage_ids: Annotated[tuple[Text, ...], Field(min_length=1)]
    extractor_profile: Text
    embedding_profile: Text
    payload: ProseExtractionPayload
    payload_hash: Text = "pending"
    identity_fields = (
        "generation_id",
        "derived_record_id",
        "input_kind",
        "input_id",
        "input_text_hash",
        "support_passage_ids",
        "extractor_profile",
        "embedding_profile",
        "payload_hash",
    )

    @model_validator(mode="before")
    @classmethod
    def bind_payload(cls, values):
        if isinstance(values, dict) and "payload" in values:
            payload = (
                values["payload"]
                if isinstance(values["payload"], ProseExtractionPayload)
                else ProseExtractionPayload.model_validate_json(canonical_json(values["payload"]))
            )
            expected = text_hash(canonical_json(payload.model_dump(mode="json")))
            if values.get("payload_hash", expected) != expected:
                raise ValueError("Prose payload hash differs")
            values = values | {"payload": payload, "payload_hash": expected}
            if "support_passage_ids" in values:
                values = values | {"support_passage_ids": tuple(sorted(set(values["support_passage_ids"])))}
        return values


class Section(Record):
    source_revision_id: Text
    original_heading: str
    ordinal: Nonnegative
    parent_section_id: Text | None = None
    breadcrumb: tuple[Text, ...]
    original_span_ids: Annotated[tuple[Text, ...], Field(min_length=1)]
    identity_fields = ("source_revision_id", "parent_section_id", "ordinal", "original_span_ids")


class SectionMember(Record):
    section_id: Text
    child_id: Text
    child_kind: Literal["section", "span"]
    ordinal: Nonnegative
    identity_fields = ("section_id", "child_id", "child_kind", "ordinal")


class ConflictSet(Record):
    workspace_id: Text
    scope_key: Text
    assertion_version_ids: Annotated[tuple[Text, ...], Field(min_length=2)]
    valid_from: Instant | None = None
    valid_to: Instant | None = None
    resolution_status: Literal["unresolved", "possible", "resolved", "dismissed"]
    support_span_ids: Annotated[tuple[Text, ...], Field(min_length=1)]
    resolution_rule: Text | None = None
    identity_fields = ("workspace_id", "scope_key", "assertion_version_ids", "valid_from", "valid_to")

    @model_validator(mode="after")
    def conflict_bounds(self) -> Self:
        if len(set(self.assertion_version_ids)) < 2:
            raise ValueError("Conflict requires distinct versions")
        if self.valid_from is not None and self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("Conflict interval is reversed or empty")
        if self.resolution_status == "resolved" and self.resolution_rule is None:
            raise ValueError("Resolved conflict requires an authoritative rule")
        return self


class Alias(Record):
    workspace_id: Text
    namespace: Text
    alias_key: Text
    target_object_id: Text
    authority: Text
    support_span_ids: Annotated[tuple[Text, ...], Field(min_length=1)]
    status: Literal["explicit", "reviewed", "candidate", "retired"]
    identity_fields = ("workspace_id", "namespace", "alias_key", "target_object_id", "authority")


class TimeInterval(Contract):
    start: Instant
    end: Instant

    @model_validator(mode="after")
    def positive(self) -> Self:
        if self.end <= self.start:
            raise ValueError("Time interval must have positive half-open extent")
        return self


class SelectorBase(Contract):
    timezone: Text = "UTC"
    snapshot_id: Text | None = None

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Unknown IANA timezone") from error
        return value


class CurrentSelector(SelectorBase):
    mode: Literal["current"] = "current"


class AsOfSelector(SelectorBase):
    mode: Literal["as_of"] = "as_of"
    valid_at: Instant
    known_at: Instant | None = None


class DuringSelector(SelectorBase):
    mode: Literal["during"] = "during"
    valid_during: TimeInterval
    interval_predicate: Literal["overlaps", "throughout"]
    known_at: Instant | None = None


class ChangesSelector(SelectorBase):
    mode: Literal["changes"] = "changes"
    changes_since: Instant
    changes_until: Instant
    change_clock: Literal["published", "source_modified", "effective"] = "published"
    known_at: Instant | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.changes_until <= self.changes_since:
            raise ValueError("Change interval must have positive half-open extent")
        return self


class AtemporalSelector(SelectorBase):
    mode: Literal["atemporal"] = "atemporal"


SingleSelector = Annotated[
    CurrentSelector | AsOfSelector | DuringSelector | ChangesSelector | AtemporalSelector,
    Field(discriminator="mode"),
]


class CompareSelector(SelectorBase):
    mode: Literal["compare"] = "compare"
    left: SingleSelector
    right: SingleSelector
    known_at: Instant | None = None

    @model_validator(mode="after")
    def comparison_scope(self) -> Self:
        if self.snapshot_id is not None:
            raise ValueError("Comparison pins snapshots on each side, not globally")
        if self.known_at is not None:
            for side in (self.left, self.right):
                known_at = getattr(side, "known_at", None)
                if known_at is not None and known_at != self.known_at:
                    raise ValueError("Comparison knowledge cutoffs contradict")
        return self


TemporalSelector = Annotated[
    CurrentSelector | AsOfSelector | DuringSelector | ChangesSelector | CompareSelector | AtemporalSelector,
    Field(discriminator="mode"),
]


def validate_knowledge_cutoff(selector: TemporalSelector, cutoff: datetime) -> None:
    """A pinned manifest has one knowledge cutoff; implicit latest resolves to it.

    Comparisons that intentionally use different knowledge cutoffs require their
    own side manifests rather than silently overriding an explicit selector.
    """
    known_at = getattr(selector, "known_at", None)
    if known_at is not None and known_at != cutoff:
        raise ValueError("Manifest knowledge cutoff contradicts its temporal selector")
    if isinstance(selector, CompareSelector):
        validate_knowledge_cutoff(selector.left, cutoff)
        validate_knowledge_cutoff(selector.right, cutoff)


class QueryBudget(Contract):
    max_exact: Annotated[int, Field(ge=1, le=1000)] = 20
    max_lexical: Annotated[int, Field(ge=1, le=1000)] = 60
    max_dense: Annotated[int, Field(ge=1, le=1000)] = 60
    max_hipporag: Annotated[int, Field(ge=1, le=1000)] = 60
    max_objects: Annotated[int, Field(ge=1, le=10000)] = 100
    max_edges: Annotated[int, Field(ge=1, le=20000)] = 200
    max_hops: Annotated[int, Field(ge=0, le=5)] = 2
    max_sections: Annotated[int, Field(ge=1, le=1000)] = 20
    max_hierarchy_levels: Annotated[int, Field(ge=1, le=5)] = 3
    max_child_spans: Annotated[int, Field(ge=1, le=1000)] = 40
    max_evidence_tokens: Annotated[int, Field(ge=1, le=100000)] = 8000
    max_evidence_needs: Annotated[int, Field(ge=1, le=3)] = 3
    max_followups: Annotated[int, Field(ge=0, le=1)] = 1


class QueryRequest(Contract):
    question: Text
    mode: Literal["legacy", "hybrid", "schema", "code", "traceability", "overview", "auto"] = "auto"
    source_ids: tuple[Text, ...] = ()
    kinds: tuple[ObjectKind, ...] = ()
    repository_ids: tuple[Text, ...] = ()
    service_ids: tuple[Text, ...] = ()
    database_ids: tuple[Text, ...] = ()
    environments: tuple[Text, ...] = ()
    temporal: TemporalSelector = Field(default_factory=CurrentSelector)
    snapshot_id: Text | None = None
    budget: QueryBudget = Field(default_factory=QueryBudget)

    @model_validator(mode="after")
    def snapshot_consistency(self) -> Self:
        if self.snapshot_id is not None:
            if self.temporal.mode == "compare":
                raise ValueError("Comparison requires separate side snapshots")
            if self.temporal.snapshot_id is not None and self.temporal.snapshot_id != self.snapshot_id:
                raise ValueError("Request snapshot selectors contradict")
        return self


class SnapshotSource(Contract):
    source_id: Text
    generation_id: Text


class QuerySnapshot(Record):
    workspace_id: Text
    sources: tuple[SnapshotSource, ...]
    history_manifest_ids: tuple[Text, ...] = ()
    link_generation_id: Text | None = None
    knowledge_cutoff: Instant
    temporal: TemporalSelector
    profile_fingerprint: Text
    settings_fingerprint: Text
    policy_fingerprint: Text
    suppression_epoch: Nonnegative
    created_at: Instant
    identity_fields = (
        "workspace_id",
        "sources",
        "history_manifest_ids",
        "link_generation_id",
        "knowledge_cutoff",
        "temporal",
        "profile_fingerprint",
        "settings_fingerprint",
        "policy_fingerprint",
        "suppression_epoch",
    )

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        validate_knowledge_cutoff(self.temporal, self.knowledge_cutoff)
        if len({source.source_id for source in self.sources}) != len(self.sources):
            raise ValueError("A query snapshot cannot pin two generations of a source")
        return self


class SnapshotReference(Record):
    workspace_id: Text
    snapshot_id: Text
    kind: Literal["active_query", "saved", "retained"]
    reference_key: Text
    created_at: Instant
    lease_owner: Text | None = None
    lease_expires_at: Instant | None = None
    released_at: Instant | None = None
    identity_fields = ("workspace_id", "snapshot_id", "kind", "reference_key")

    @model_validator(mode="after")
    def lease_contract(self) -> Self:
        if self.kind == "active_query":
            if (
                self.lease_owner is None
                or self.lease_expires_at is None
                or self.lease_expires_at <= self.created_at
            ):
                raise ValueError("Active query requires an owner and positive lease")
        elif self.lease_owner is not None or self.lease_expires_at is not None:
            raise ValueError("Durable references cannot have leases")
        if self.released_at is not None and self.released_at < self.created_at:
            raise ValueError("Release cannot precede creation")
        return self


# Explicit allow-list avoids silently making internal mixins wire record types.
_RECORD_CLASSES = (
    Workspace,
    WorkspaceMembership,
    GroupMembership,
    Connector,
    Artifact,
    ArtifactRevision,
    Generation,
    GenerationMember,
    GenerationEvidenceMember,
    EvidenceSpan,
    KnowledgeObject,
    ObjectObservation,
    Assertion,
    AssertionVersion,
    AssertionSupport,
    NativeBinding,
    AccessPolicy,
    SyncState,
    SyncRun,
    MaintenanceJob,
    SourceEvent,
    IndexManifest,
    LinkGeneration,
    HistoryManifest,
    DerivedRecord,
    DerivedDependency,
    Suppression,
    PurgeJob,
    IndexEvent,
    ConsumerAck,
    RetrievalView,
    ProseExtraction,
    Section,
    SectionMember,
    ConflictSet,
    Alias,
    QuerySnapshot,
    SnapshotReference,
)

RECORD_TYPES = MappingProxyType({record.__name__: record for record in _RECORD_CLASSES})


RecordPayload = Union[_RECORD_CLASSES]  # noqa: UP007 - union is built from the explicit runtime catalog


class EvidenceEnvelope(Contract):
    version: VersionOne = 1
    record_type: Text
    payload: RecordPayload

    @model_validator(mode="before")
    @classmethod
    def decode_record(cls, values):
        if not isinstance(values, dict):
            return values
        record_type = RECORD_TYPES.get(values.get("record_type"))
        if record_type is None:
            raise ValueError("Unknown evidence record type")
        payload = values.get("payload")
        if isinstance(payload, Record):
            if type(payload) is not record_type:
                raise ValueError("Evidence payload has the wrong record type")
            payload = record_type.model_validate(payload)
        elif isinstance(payload, dict):
            # Serialized tuple/datetime values must follow the same strict JSON path.
            payload = record_type.model_validate_json(canonical_json(payload))
        else:
            raise ValueError("Evidence payload must be a typed record")
        return values | {"payload": payload}


class QueryEnvelope(Contract):
    version: VersionOne = 1
    payload: QueryRequest


assert set(OBJECT_KINDS) == set(ObjectKind.__args__)
