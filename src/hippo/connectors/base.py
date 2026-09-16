"""The connector contract: every record a connector exchanges with the kit, and the port itself.

Design `docs/spec/connector-developer-kit.md` sections 1 and 2, plan `ai_docs/plans/cdk-s2-contract.md`
sections 4.1 and 4.6. Every record is a `Contract`: frozen, strict, `extra="forbid"`, revalidated. A
connector therefore cannot invent an id, an evidence class or a field the kit does not know.

Nothing here reads a store, a model, the network or a clock. `probe`'s `clock` exists for a
connector's own bounded HTTP and never enters a `Classification`.

Rulings applied: R24 and R42 (`PASSAGE_CHAR_BOUND`), R26 (`token_count` is the one counter), R44
(`map_principals`), R46 (`ConnectorDescriptor.extension`), R48 (`RevisionInput.span_policy_id`), R53
(`NodeRef.instance`), and the orchestrator's R-S2-10 addition (the registry accessors are re-exported
here, so a connector never imports `hippo.knowledge.registry`).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Literal, Protocol, Self, runtime_checkable
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ..knowledge import model as k
from ..knowledge.identity import canonical_json, text_hash
from ..knowledge.model import (
    Code,
    Contract,
    Instant,
    Json,
    Nonnegative,
    Positive,
    ProviderURL,
    TemporalPrecision,
    Text,
)
from ..knowledge.registry import FactTemplate as FactTemplate
from ..knowledge.registry import Family as Family
from ..knowledge.registry import ObjectKindDefinition as ObjectKindDefinition
from ..knowledge.registry import PredicateDefinition as PredicateDefinition
from ..knowledge.registry import Registry as Registry
from ..knowledge.registry import TypeExtension as TypeExtension
from ..knowledge.registry import UnregisteredName, connector_configuration
from ..knowledge.registry import current_registry as current_registry
from ..knowledge.registry import extension_scope as extension_scope
from ..knowledge.registry import use_registry as use_registry

Clock = Callable[[], datetime]
# Ruling R24, as R42 records it: 6,000 characters approximate the specification's 1,500 tokens at
# four characters per token. It is a maximum, not a target, and the chunker's own default is untouched.
PASSAGE_CHAR_BOUND = 6000
UNCLASSIFIED = "custom/unclassified"

_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_.+-]{0,63}$")
_PARSER_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)?$")
_PARSER_SPELLING = "Parser version must be spelled name@version, e.g. tree-sitter/python@0.23"
_POLICY_ID = re.compile(
    rf"^{k.AccessPolicy.identity_prefix or k.AccessPolicy.__name__.lower()}-[0-9a-f]{{64}}$"
)


def token_count(text: str) -> int:
    """The one counter (rulings R11 and R26): the character measure `ingest/chunker.py` budgets with.

    A character count never under-counts subword tokens, so text within `PASSAGE_CHAR_BOUND`
    characters is within the specification's token bound. The kit, the binder and every connector
    use this function and no other.
    """
    return len(text)


class ContractError(ValueError):
    """A connector produced something the contract refuses; the message is for its developer."""


class RegistrationRequired(ContractError):
    """A mapping or descriptor names vocabulary nothing registered: a registration request (design §2)."""

    def __init__(
        self, message: str, *, kinds: tuple[str, ...], predicates: tuple[str, ...], skeleton: str
    ) -> None:
        super().__init__(message)
        self.kinds, self.predicates, self.skeleton = kinds, predicates, skeleton


def _skeleton(missing: Mapping[str, tuple[str, ...]]) -> str:
    """A `TypeExtension(...)` the developer can paste, naming every type that is not registered."""
    lines = ["TypeExtension("]
    if missing["families"]:
        lines.append(f"    families={_tuple(missing['families'])},")
    if missing["object_kinds"]:
        lines.append("    object_kinds=(")
        for name in missing["object_kinds"]:
            lines.extend(
                [
                    "        ObjectKindDefinition(",
                    f'            name="{name}",',
                    '            family="<family>",',
                    '            key_template=("<part>",),',
                    '            key_prefix="<prefix>",',
                    "            attrs_model=<AttributesModel>,",
                    '            label_template="{<attribute>}",',
                    "        ),",
                ]
            )
        lines.append("    ),")
    if missing["artifact_kinds"]:
        lines.append(f"    artifact_kinds={_tuple(missing['artifact_kinds'])},")
    if missing["locator_kinds"]:
        lines.append("    locator_kinds=(")
        for name in missing["locator_kinds"]:
            lines.append(f'        LocatorKindDefinition(name="{name}", model=<LocatorModel>),')
        lines.append("    ),")
    if missing["predicates"]:
        lines.append("    predicates=(")
        for name in missing["predicates"]:
            lines.extend(
                [
                    "        PredicateDefinition(",
                    f'            name="{name}",',
                    '            subject_kinds=frozenset({"<kind>"}),',
                    '            object_kinds=frozenset({"<kind>"}),',
                    '            owner_families=frozenset({"<family>"}),',
                    '            canonical_direction="subject_to_object",',
                    '            family_default="deterministic",',
                    '            sources_allowed=frozenset({"<source>"}),',
                    '            verb_phrase="<verb>",',
                    "        ),",
                ]
            )
        lines.append("    ),")
    lines.append(")")
    return "\n".join(lines)


def _tuple(names: tuple[str, ...]) -> str:
    return "(" + "".join(f'"{name}", ' for name in names).rstrip() + ")"


def _registration_required(subject: str, missing: Mapping[str, tuple[str, ...]]) -> RegistrationRequired:
    names = ", ".join(name for section in missing.values() for name in section)
    return RegistrationRequired(
        f"{subject} names unregistered types: {names}; register a TypeExtension first",
        kinds=missing["object_kinds"],
        predicates=missing["predicates"],
        skeleton=_skeleton(missing),
    )


def _unregistered(registry: Registry, **sections: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """Every name of each section the registry does not hold, in the order the caller declared them."""
    lookup = {
        "families": lambda name: name in registry.families() or _raise(name),
        "object_kinds": registry.object_kind,
        "artifact_kinds": registry.artifact_kind,
        "locator_kinds": registry.locator_kind,
        "predicates": registry.predicate,
    }
    missing = {section: () for section in lookup}
    for section, names in sections.items():
        absent = []
        for name in names:
            try:
                lookup[section](name)
            except UnregisteredName:
                if name not in absent:
                    absent.append(name)
        missing[section] = tuple(absent)
    return missing


def _raise(name: str):
    raise UnregisteredName(f"Unknown family: '{name}'")


class ConnectorCapabilities(Contract):
    changes_feed: bool = False
    deletion_feed: bool = False
    acls: bool = False
    history: bool = False
    attachments: bool = False
    webhooks: bool = False
    inventory: bool = False  # list_changes(None) walks the whole partition and marks its last page complete
    derivation: Literal["emit", "coordinator_lane"] = "emit"  # ruling R1: a lane connector has no emit


class CredentialRequirement(Contract):
    name: Code
    scopes: tuple[Text, ...] = ()


class ParserVersion(Contract):
    name: Text  # "tree-sitter/python"
    version: Text  # "0.23"

    @model_validator(mode="after")
    def spelled(self) -> Self:
        if not _PARSER_NAME.fullmatch(self.name) or not _VERSION.fullmatch(self.version):
            raise ValueError(_PARSER_SPELLING)
        return self

    @property
    def spelling(self) -> str:
        return f"{self.name}@{self.version}"

    @classmethod
    def parse(cls, spelling: str) -> ParserVersion:
        name, separator, version = str(spelling).rpartition("@")
        if not separator:
            raise ContractError(_PARSER_SPELLING)
        try:
            return cls(name=name, version=version)
        except ValueError as error:
            raise ContractError(_PARSER_SPELLING) from error


class PrincipalMap(Contract):
    """Provider principals to local principal and group ids (ruling R30, amended by R44).

    Users and groups are mapped separately, so a provider user id cannot be read as a group id. The
    map lives in the connector instance configuration; `emit.policy_record` applies it through
    `map_principals`.
    """

    users: dict[Text, Text] = {}
    groups: dict[Text, Text] = {}


class ConnectorDescriptor(Contract):
    name: Code
    version: Text
    families: tuple[Family, ...]
    kinds: tuple[Code, ...]
    predicates: tuple[Code, ...]
    artifact_kinds: tuple[Code, ...]
    locator_kinds: tuple[Code, ...]
    capabilities: ConnectorCapabilities
    config_model: type[BaseModel]
    credentials: tuple[CredentialRequirement, ...]
    parsers: tuple[ParserVersion, ...]
    extension: TypeExtension  # ruling R46: the vocabulary this connector registers

    @model_validator(mode="after")
    def declared(self) -> Self:
        if not _VERSION.fullmatch(self.version):
            raise ValueError("Connector version must be a short token such as 1.2.0")
        if not (self.families and self.artifact_kinds and self.locator_kinds):
            raise ValueError("A connector declares at least one family, artifact kind and locator kind")
        fields = {
            "families": self.families,
            "kinds": self.kinds,
            "predicates": self.predicates,
            "artifact_kinds": self.artifact_kinds,
            "locator_kinds": self.locator_kinds,
            "parsers": tuple(parser.spelling for parser in self.parsers),
            "credentials": tuple(credential.name for credential in self.credentials),
        }
        for field, values in fields.items():
            seen: set[str] = set()
            for value in values:
                if value in seen:
                    raise ValueError(f"Connector descriptor lists {field} {value!r} twice")
                seen.add(value)
        if self.config_model.model_config.get("extra") != "forbid":
            raise ValueError(
                f'Connector configuration model {self.config_model.__name__} must set extra="forbid"'
            )
        return self

    def validate_against(self, registry: Registry) -> None:
        """Refuse a descriptor naming vocabulary nothing registered, with the extension to write."""
        missing = _unregistered(
            registry,
            families=self.families,
            object_kinds=self.kinds,
            artifact_kinds=self.artifact_kinds,
            locator_kinds=self.locator_kinds,
            predicates=self.predicates,
        )
        if any(missing.values()):
            raise _registration_required(f"Connector {self.name}", missing)


def descriptor_configuration(descriptor: ConnectorDescriptor, registry: Registry) -> dict:
    """S1's `{"connector": {...}}`, never the registry fingerprint (design §3, S1 D25)."""
    return connector_configuration(
        name=descriptor.name,
        version=descriptor.version,
        templates=registry.declared_template_versions(descriptor.kinds),
        parsers=[parser.spelling for parser in descriptor.parsers],
    )


class ExternalRef(Contract):
    partition: Code
    artifact_kind: Code
    external_id: Text
    provider_revision: Text | None = None

    @model_validator(mode="after")
    def printable(self) -> Self:
        if any(ord(character) < 32 or ord(character) == 127 for character in self.external_id):
            raise ValueError("External ids cannot contain control characters")
        return self


class SyncCursor(Contract):
    partition: Code
    value: Json = "{}"
    scan: Literal["changes", "inventory"] = "changes"


class Change(Contract):
    ref: ExternalRef
    operation: Literal["upsert", "delete", "policy_change"]


class ChangePage(Contract):
    partition: Code
    changes: tuple[Change, ...]
    next_cursor: SyncCursor | None
    complete: bool = False
    warnings: tuple[Code, ...] = ()

    @model_validator(mode="after")
    def one_partition(self) -> Self:
        cursor = self.next_cursor
        if any(change.ref.partition != self.partition for change in self.changes) or (
            cursor is not None and cursor.partition != self.partition
        ):
            raise ValueError("A change page cannot mix partitions")
        return self


class RawFetch(Contract):
    # A credentialed URI must never reach a log or an error, so the refusal hides its input.
    model_config = ConfigDict(hide_input_in_errors=True)

    ref: ExternalRef
    data: bytes
    content_type: Text
    external_id: Text
    canonical_uri: Text
    provider_revision: Text | None = None
    source_updated_at: Instant | None = None
    source_timestamp_original: Text | None = None
    source_timezone: Text | None = None
    source_precision: TemporalPrecision = "unknown"
    parser: ParserVersion | None = None

    @model_validator(mode="after")
    def provider_fields(self) -> Self:
        if self.external_id != self.ref.external_id:
            raise ValueError("RawFetch.external_id must equal the requested ref")
        try:
            parsed = urlsplit(self.canonical_uri)
            credentialed = parsed.username is not None or parsed.password is not None
        except ValueError as error:
            raise ValueError("A canonical URI must be a parseable URI") from error
        if credentialed:
            raise ValueError("Canonical URIs cannot carry credentials")
        if (self.source_updated_at is None) != (self.source_timestamp_original is None):
            raise ValueError("A source timestamp needs its original spelling, and only with a timestamp")
        return self


class PolicyObservation(Contract):
    ref: ExternalRef
    state: Literal["known", "unknown"]
    mode: Literal["restricted", "workspace"] | None = None
    allow_users: tuple[Text, ...] = ()
    allow_groups: tuple[Text, ...] = ()
    deny_users: tuple[Text, ...] = ()
    deny_groups: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def principals(self) -> Self:
        principals = self.allow_users + self.allow_groups + self.deny_users + self.deny_groups
        if self.state == "unknown":
            if self.mode is not None or principals:
                raise ValueError("An unknown policy carries no principals; the runtime stores it as deny")
            return self
        if self.mode is None:
            raise ValueError("A known policy needs a mode")
        if self.mode == "restricted" and not (self.allow_users or self.allow_groups):
            raise ValueError(
                "A known restricted policy needs at least one allowed principal; "
                'report state="unknown" instead'
            )
        return self


def _unknown(policy: PolicyObservation) -> PolicyObservation:
    return PolicyObservation(ref=policy.ref, state="unknown")


def _mapped(names: tuple[str, ...], mapping: Mapping[str, str]) -> tuple[tuple[str, ...], int]:
    local: list[str] = []
    dropped = 0
    for name in names:
        translated = mapping.get(name)
        if translated is None:
            dropped += 1
        elif translated not in local:
            local.append(translated)
    return tuple(local), dropped


def map_principals(policy: PolicyObservation, principal_map: PrincipalMap) -> tuple[PolicyObservation, int]:
    """Translate provider principals to local ids (ruling R44); the count is the dropped allow entries.

    Three rules, all deny-leaning. An unmapped principal in a deny list makes the observation
    `unknown`, because dropping it would grant its members what the provider denied. An allow list
    the map empties makes it `unknown` too (read per list, orchestrator 2026-09-15). Any other
    unmapped allow entry is dropped and counted, never silently kept.
    """
    if policy.state == "unknown":
        return policy, 0
    allow_users, dropped_users = _mapped(policy.allow_users, principal_map.users)
    allow_groups, dropped_groups = _mapped(policy.allow_groups, principal_map.groups)
    dropped = dropped_users + dropped_groups
    deny_users, denied_users = _mapped(policy.deny_users, principal_map.users)
    deny_groups, denied_groups = _mapped(policy.deny_groups, principal_map.groups)
    if denied_users or denied_groups:
        return _unknown(policy), dropped
    if (policy.allow_users and not allow_users) or (policy.allow_groups and not allow_groups):
        return _unknown(policy), dropped
    return (
        policy.replace(
            allow_users=allow_users,
            allow_groups=allow_groups,
            deny_users=deny_users,
            deny_groups=deny_groups,
        ),
        dropped,
    )


class PathDeclaration(Contract):
    pattern: Text  # fnmatch.fnmatchcase over the normalized relative path
    family: Family
    kind: Code | None = None
    template: Code | None = None
    dialect: Code | None = None
    shape: Literal["document", "tabular"] = "document"


class ClassifierSpec(Contract):
    version: Code
    declarations: tuple[PathDeclaration, ...] = ()
    sql_dialects: tuple[Code, ...] = ()


class KindMapping(Contract):
    provider_type: Text
    kind: Code | None  # None is custom/unclassified: counted, never dropped


class AttributeMapping(Contract):
    kind: Code
    attribute: Code
    provider_field: Text


class TypeMapping(Contract):
    family: Family
    kinds: tuple[KindMapping, ...] = ()
    predicates: tuple[Code, ...] = ()
    attributes: tuple[AttributeMapping, ...] = ()
    classifier: ClassifierSpec | None = None

    @model_validator(mode="after")
    def one_row_per_provider_type(self) -> Self:
        seen: set[str] = set()
        for mapping in self.kinds:
            if mapping.provider_type in seen:
                raise ValueError(f"Provider type {mapping.provider_type!r} is mapped twice")
            seen.add(mapping.provider_type)
        return self

    @property
    def mapping_hash(self) -> str:
        return text_hash(canonical_json(self.model_dump(mode="json")))

    def validate_against(self, registry: Registry) -> None:
        declarations = self.classifier.declarations if self.classifier else ()
        missing = _unregistered(
            registry,
            families=(self.family, *(declaration.family for declaration in declarations)),
            object_kinds=tuple(
                name
                for name in (
                    *(mapping.kind for mapping in self.kinds),
                    *(declaration.kind for declaration in declarations),
                    *(attribute.kind for attribute in self.attributes),
                )
                if name is not None
            ),
            predicates=self.predicates,
        )
        if any(missing.values()):
            raise _registration_required(f"Type mapping for family {self.family}", missing)
        for attribute in self.attributes:
            definition = registry.object_kind(attribute.kind)
            if attribute.attribute not in definition.attrs_model.model_fields:
                raise ContractError(f"Kind {attribute.kind} declares no attribute {attribute.attribute}")


class ClassificationEvidence(Contract):
    level: Literal["family", "kind", "attribute"]
    rule: Literal["descriptor", "declaration", "content", "name", "unclassified"]
    detector: Code
    subject: Text
    outcome: Text


class PartitionClassification(Contract):
    partition: Code
    family: Family
    mapping: TypeMapping
    capabilities: ConnectorCapabilities
    sample_count: Nonnegative
    counts: dict[Text, Nonnegative]
    warnings: tuple[Code, ...] = ()
    evidence: tuple[ClassificationEvidence, ...] = ()


class Classification(Contract):
    connector: Code
    connector_version: Text
    registry_fingerprint: Text
    partitions: tuple[PartitionClassification, ...]


class SqlPart(Contract):
    original: Text
    dialect: Literal["postgres", "tsql"]
    quoted: bool = False
    collation: Text | None = None

    @model_validator(mode="after")
    def printable(self) -> Self:
        if "\x00" in self.original:
            raise ValueError("SQL identifiers cannot contain NUL")
        return self


KeyValue = Text | SqlPart | tuple[SqlPart, ...]


class NodeRef(Contract):
    # An instance URL may carry credentials in a mistaken configuration; the refusal hides its input.
    model_config = ConfigDict(hide_input_in_errors=True)

    kind: Code
    key: dict[Code, KeyValue]  # every key_template part except the instance parts
    # Ruling R53: an identity-only foreign endpoint carries the instance that minted its name, so a
    # cross-domain edge points at the node the owning connector writes.
    instance: ProviderURL | None = None
    # Ruling R70: that endpoint may also name itself, so a statement about it reads as prose. It is
    # read from the `NodeEmission` of an endpoint whose family this connector does not own, and
    # nowhere else: an owned node's label comes from its `label_template`, and a label on an edge or
    # an alias reference stores nothing, which would leave a statement no record can re-derive.
    label: Text | None = None

    @model_validator(mode="before")
    @classmethod
    def key_parts(cls, data):
        if isinstance(data, dict):
            key = data.get("key")
            empty = not key or (
                isinstance(key, dict)
                and any(isinstance(value, str) and not value.strip() for value in key.values())
            )
            if empty:
                raise ValueError("A node reference needs its key parts")
        return data


class SpanRef(Contract):
    locator_kind: Code
    locator: dict[str, JsonValue]
    text: str | None = None


class SupportEmission(Contract):
    spans: tuple[SpanRef, ...] = Field(min_length=1)


class NodeEmission(Contract):
    ref: NodeRef
    attrs: dict[str, JsonValue]
    span: SpanRef
    source: Code
    metadata_origin: Literal["catalog", "declaration"] | None = None
    ts: Instant | None = None
    ts_original: Text | None = None
    ts_timezone: Text | None = None
    ts_precision: TemporalPrecision = "unknown"

    @model_validator(mode="after")
    def provenance(self) -> Self:
        if (self.ts is None) != (self.ts_original is None):
            raise ValueError("A node ts needs its original spelling, and only with a ts")
        _metadata_origin(self.source, self.metadata_origin)
        return self


def _metadata_origin(source: str, metadata_origin: str | None) -> None:
    if (source == "metadata") != (metadata_origin is not None):
        raise ValueError("Metadata provenance must say catalog or declaration")


class EdgeEmission(Contract):
    subject: NodeRef
    predicate: Code
    object: NodeRef
    family: Literal["deterministic", "probabilistic"]
    source: Code
    weight: float = Field(ge=0, le=1, allow_inf_nan=False)
    support: tuple[SupportEmission, ...] = Field(min_length=1)
    metadata_origin: Literal["catalog", "declaration"] | None = None
    rule: Code | None = None
    rule_evidence: Text | None = None
    unit: Code | None = None
    source_statement: str | None = None
    valid_from: Instant | None = None
    valid_to: Instant | None = None
    window_precision: TemporalPrecision = "unknown"

    @model_validator(mode="after")
    def attribution(self) -> Self:
        if self.family == "deterministic" and self.weight != 1.0:
            raise ValueError("Deterministic edges carry weight 1.0")
        if (self.source == "rule") != (self.rule is not None and self.rule_evidence is not None):
            raise ValueError(
                "A rule-derived edge names its rule and its evidence, and only a rule-derived edge does"
            )
        _metadata_origin(self.source, self.metadata_origin)
        if self.unit is not None and self.source_statement is not None:
            raise ValueError("An edge reuses a statement unit or quotes a source statement, not both")
        if self.valid_to is not None and (self.valid_from is None or self.valid_to <= self.valid_from):
            raise ValueError("An edge window needs a start before its end")
        return self


class PassageEmission(Contract):  # verbatim passages only; the kit derives rendered ones (ruling R6)
    key: Code
    span: SpanRef
    title: Text
    node: NodeRef | None = None
    ts: Instant | None = None


class UnitEmission(Contract):
    key: Code
    passage: Code
    ordinal: Nonnegative
    kind: Literal["sentence", "statement", "row", "diff_line"]
    span: SpanRef
    start: Nonnegative | None = None
    end: Nonnegative | None = None
    prefix: str = ""
    mentions: tuple[NodeRef, ...] = ()

    @model_validator(mode="after")
    def offsets(self) -> Self:
        if (self.start is None) != (self.end is None) or (
            self.start is not None and self.end is not None and self.start >= self.end
        ):
            raise ValueError("Unit offsets come as a nonempty start/end pair")
        return self


class AliasEmission(Contract):
    a: NodeRef
    b: NodeRef
    rule: Code
    support: tuple[SupportEmission, ...] = Field(min_length=1)


class ReverseViewHint(Contract):
    predicate: Code
    subject: NodeRef
    object: NodeRef
    support: tuple[SupportEmission, ...] = Field(min_length=1)


class ParseFailure(Contract):
    family: Family
    reason: Code  # a short code, never exception text
    parser: ParserVersion | None = None
    dialect: Code | None = None
    scope: Literal["revision", "record"] = "record"
    span: SpanRef | None = None
    count: Positive = 1


class EmissionBatch(Contract):
    nodes: tuple[NodeEmission, ...] = ()
    edges: tuple[EdgeEmission, ...] = ()
    passages: tuple[PassageEmission, ...] = ()
    units: tuple[UnitEmission, ...] = ()
    aliases: tuple[AliasEmission, ...] = ()
    failures: tuple[ParseFailure, ...] = ()
    hints: tuple[ReverseViewHint, ...] = ()

    @model_validator(mode="after")
    def keys_resolve(self) -> Self:
        passages, units = set(), set()
        for emission in self.passages:
            if emission.key in passages:
                raise ValueError(f"Emission key {emission.key!r} is duplicated")
            passages.add(emission.key)
        for unit in self.units:
            if unit.key in units:
                raise ValueError(f"Emission key {unit.key!r} is duplicated")
            units.add(unit.key)
        for unit in self.units:
            if unit.passage not in passages:
                raise ValueError(f"Emission names missing passage {unit.passage!r}")
        for edge in self.edges:
            if edge.unit is not None and edge.unit not in units:
                raise ValueError(f"Emission names missing unit {edge.unit!r}")
        return self


class RevisionInput(Contract):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    partition: Code
    artifact: k.Artifact
    revision: k.ArtifactRevision
    data: bytes
    config: BaseModel
    mapping: TypeMapping
    registry: Registry
    # Ruling R48: the policy the revision was first captured under; every span keeps it, so a policy
    # change never re-mints a stored span with different contents.
    span_policy_id: str

    @model_validator(mode="after")
    def revision_of_its_artifact(self) -> Self:
        if not _POLICY_ID.fullmatch(self.span_policy_id):
            raise ValueError("A revision input names the AccessPolicy its spans keep")
        if self.revision.artifact_id != self.artifact.id:
            raise ValueError("Revision does not belong to its artifact")
        if self.revision.content_hash != hashlib.sha256(self.data).hexdigest():
            raise ValueError("Revision bytes differ from the revision's content hash")
        if not self.registry.frozen:
            raise ValueError("emit requires a frozen registry")
        return self


@runtime_checkable
class SyncConnector(Protocol):  # the sync half; a coordinator-lane connector is only this (ruling R1)
    descriptor: ConnectorDescriptor

    def probe(self, config: BaseModel, clock: Clock) -> Classification: ...

    def list_changes(self, config: BaseModel, cursor: SyncCursor | None) -> ChangePage: ...

    def fetch(self, config: BaseModel, ref: ExternalRef) -> RawFetch: ...

    def fetch_policy(self, config: BaseModel, ref: ExternalRef) -> PolicyObservation: ...


@runtime_checkable
class Connector(SyncConnector, Protocol):
    def emit(self, revision: RevisionInput, mapping: TypeMapping) -> EmissionBatch: ...
