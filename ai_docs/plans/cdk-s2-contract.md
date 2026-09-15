# CDK S2: the connector contract, classification, canonical keys, rendering and emission to records

> **For Claude:** execute with `dev:execute-plan`, one task per worker (S2a, then S2b). Every task is
> test-first: write the RED tests, save the RED log, implement, save the GREEN log.

**Status:** proposed implementation contract for gate CK2 of `ai_docs/gates/rag-it-all/cdk/GATES.md`.
Nothing here is implemented. Design of record: `docs/spec/connector-developer-kit.md` at `ef143b1`
(sections 1, 2, 4, 5, 6, 12, 13; section 3 is S1's). Every `src/` and `tests/` anchor below was read at
`ef143b1`; `git diff --stat 0434aa1 ef143b1 -- src tests` is empty, so they equal the brief's `0434aa1`.
Names S1 decides are taken from `ai_docs/plans/cdk-s1-registry.md` as it stood during this planning
session; where that plan changes a name, that plan wins and the call site named in section 3 changes.

**Goal:** a pure, typed connector contract (`hippo.connectors.base`), the classifier that assigns a
family and a type mapping when a source connects (`classify.py`), the canonical-key builders
(`keys.py`), the render rules (`render.py`) and the binder that turns one `EmissionBatch` into knowledge
records (`emit.py`), with a table-driven proof that every field of the specification's section 3 lands
in the record and column the design's section 4 names.

**Architecture:** `hippo.connectors` is a new bounded context above `hippo.knowledge`: it imports
`knowledge` (and `ingest` for the reader predicates and the physical-line rule) and nothing imports it
back. The `Connector` protocol is the port every connector adapter implements. Everything in S2 is a
pure function of its arguments: no store handle, no model, no network, no clock. The binder produces
plain knowledge records (`k.EvidenceSpan`, `k.ObjectObservation`, `k.Assertion`, `k.AssertionVersion`,
`k.AssertionSupport`, `k.Unit`, views, members) that S3's runtime stages.

**Tech stack:** Python 3.12 (`requires-python >= 3.11`, `pyproject.toml:6`), Pydantic 2.13.5 strict
contracts, `sqlglot` 30 (runtime dependency, `pyproject.toml:33`), the standard library `csv`, `json`,
`fnmatch`, `hashlib`. No PyYAML: it is a dev-only dependency (`pyproject.toml:39-42`).

**Wiring manifest:** `Connector` (protocol, `base.py`) → implemented by S3's fixture connector, S5's
local and git connectors and S6's exemplar → discovered by S4's registry load. `classify.classify_item`
→ called by `classify.classify` (a connector's `probe`) and, through `TypeMapping.classifier`, by a
connector's `emit`. `keys.knowledge_object` → called only by `emit.bind_batch`. `render.*` → called by
`emit.bind_batch` and by S4's kit. `emit.capture_records`, `emit.bind_batch`, `emit.merge_bound` →
called by S3's `connectors/sync.py`. No DI container exists.

**Regression hotspots:** the `knowledge/identity.py` helpers stay byte-identical and are called, never
copied (`identity.py:148,153,163,183,200,215,264,291`); `readers.py` predicates are read-only
(`readers.py:131-196`); `EvidenceSpan.check_text_hash` (`model.py:427-435`) and the managed passage
rules (`store/generations.py:1479-1545`) are what S2's records must satisfy when S3 writes them;
`predicates.validate_endpoints`'s message `Invalid endpoint kinds for {predicate}` (`predicates.py:113`)
is the fallback refusal.


**Rulings applied** (`ai_docs/plans/cdk-rulings.md`, R1-R23): R1 (declared coordinator-lane derivation and
an emit-less `SyncConnector`), R6 (a derived passage per rendered fact; identity-only foreign endpoints),
R11 (one counter, `base.token_count`), R15 and R16 (no loader; `current_registry()`), R18 and R22 (keys
and alias ordering as S1 plans them). The S4, S5 and S6 R-S2 items are answered in section 13 and in
decisions 37-40.

---

## 0. How to read this plan

- The form is the code-capture plan's (`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md`):
  scope, seams, public API, the parts of the design this slice decides, the task split, the gate,
  ownership, decisions, deviations and questions.
- DDD vocabulary only, no DDD workspace: the bounded context is `hippo.connectors`, the ports are the
  `Connector` protocol and the registry handle, the adapters are concrete connectors. This slice writes
  no `ddd/` folder.
- "Decided by S2" marks a choice the design leaves open. Section 14 lists every one again.
- Signatures and validator messages are exact. Bodies are described, not pasted.

## 1. Outcome and scope

**In scope.** Five new modules and one package marker, all pure:

- `src/hippo/connectors/__init__.py`: a package docstring that imports nothing, so `import
  hippo.connectors` stays cheap for `hippo --help` (`tests/unit/test_import_order.py:14-28`).
- `src/hippo/connectors/base.py`: every contract record of the design's sections 1 and 2, the
  `Connector` protocol, the contract errors and `descriptor_configuration`.
- `src/hippo/connectors/keys.py`: canonical keys and `KnowledgeObject` identities.
- `src/hippo/connectors/classify.py`: declaration, then content, then name.
- `src/hippo/connectors/render.py`: labels, fact units, edge statements, prefixes, unit hashes and the
  token count.
- `src/hippo/connectors/emit.py`: `capture_records`, `bind_batch`, `merge_bound`, the evidence-class table
  and the public checks S4's kit calls.

Five new test files, exactly the ones gate CK2's CHECK line names.

**Out of scope.** The registry, the vocabulary validators, the `Unit` record, the widened
`AssertionVersion` and schema v8 (S1a, S1b); the runtime, the emit guard, HTTP, credentials and the staged
writer (S3); the test kit, scaffold and commands (S4); the local and git connectors (S5); the exemplar
(S6); alias rules 3 to 5 and the synonym queue (Task 12, deviation DV3).

## 2. Existing seams

| Seam | Use or required boundary |
| --- | --- |
| `knowledge/model.py:101-112` `Contract` (frozen, `extra="forbid"`, strict, `revalidate_instances="always"`) | Base of every S2 record, so a connector cannot add an `id`, an `evidence_class` or any other field. S1 moves it to `knowledge/contract.py` and re-exports it from `model.py`. |
| `model.py:40-44` `Text`, `Json`, `Code`, `Nonnegative`, `Positive`; `:53` `TemporalPrecision`; `:96` `Instant` | Reused field types. `Code` (`^[A-Za-z][A-Za-z0-9_.:-]{0,127}$`) forbids `/` and `@`, which is why `ParserVersion` is structured (section 4.1). |
| `model.py:135-165` `Record` identity | Record ids derive from `identity_fields`; S2 never sets an `id`. |
| `model.py:168-178` `FileLinesLocator`, `:194-196` `FieldLocator`, `:219-224` `TableCellLocator`, `:248-251` `canonical_locator_json` | The three locator kinds S2 verifies against bytes (section 8.4). S1 dispatches `canonical_locator_json` through the registry. |
| `model.py:278-286` `Connector` row | `instance_url` (a normalized `ProviderURL`) fills every instance key part (section 6). |
| `model.py:289-326` `Artifact`; identity `[workspace, provider_instance or source_id, kind, external_id]` at `:314-317`; `connector_id` iff `provider_instance` at `:319-326` | `capture_records` builds remote artifacts with both set. |
| `model.py:341-354` `ArtifactRevision`, identity `(artifact_id, provider_revision, content_hash)` | `observed_at` and `metadata_json` are outside identity, so the runtime reuses a stored revision (S3), as `prose_generation._pair` does (`ingest/prose_generation.py:124-138`). |
| `model.py:412-445` `EvidenceSpan`; `check_text_hash` at `:427-435` | Proves only `text_hash == sha256(text)`. Nothing today proves `text` is a slice of the revision bytes; S2's verifiers do (section 8.4). |
| `model.py:448-463` `KnowledgeObject` | Built only by `keys.knowledge_object`. |
| `model.py:466-487` `TemporalRecord.intervals` | Effective bounds require `validity_kind="explicit_interval"`; the binder's temporal mapping follows it (section 8.2). |
| `model.py:490-508` `ObjectObservation` (identity includes `recorded_from`, `evidence_class`) | `recorded_from` is the generation's instant, never a clock read (design review B4, `ingest/code_generation.py:602-614`). |
| `model.py:511-545` `Assertion`, `checked_assertion` | The binder calls `checked_assertion` for every edge and alias, so endpoint validation, and S1's `SAME_OBJECT_AS` ordering rule, are not re-implemented. |
| `model.py:548-573` `AssertionVersion`; `:576-605` `AssertionSupport`, `SupportGroup`, `SupportGroups` | One support group per `SupportEmission` (section 8.6). |
| `model.py:640-667` `AccessPolicy`; identity adds `origin` and `scope_key` for non-legacy policies (`:653-661`) | `capture_records` builds one provider policy per artifact (section 8.9). |
| `model.py:794-798` `canonical_ids` | "Sorted and unique", the rule S1 applies to `Unit.mentions_json`. |
| `model.py:842-900`, `:1008-1031` `ViewKind`, `DerivedRecord`, `DerivedDependency`, `RetrievalView` | A rendered passage is a `projection` view, the pattern `input_binding._view` uses (`knowledge/input_binding.py:294-345`). |
| `knowledge/derivations.py:25-26` `dependency_version`, `:33-51` `view_fingerprint` | Reused for rendered-passage views. |
| `knowledge/lifecycle.py:73-89` `generation_passage_id` | Passage ids, with and without a view. |
| `knowledge/input_binding.py:73-130` `BoundPassage` | The invariants S2's passage rows keep: original-only text equals span text; a rendered passage's view carries the row's span, revision, text and vector profile. `BoundPassage` itself is not reused: it requires an ingest `PreparedChunk` with one original unit (`:88-89`). |
| `knowledge/code_binding.py:101-105` `_SNAPSHOT`, `:810-819` `_observation` | The observation convention for a node without a source timestamp. |
| `code_binding.py:835-840` `_file_object`, `:880-887` `_data_object`; `knowledge/code_history.py:943-944` commit key | How the code lane mints `file`, `resource`-style data objects and `commit` today (section 6). |
| `knowledge/identity.py:71` `text_hash`; `:75-111` `normalize_provider_url`; `:148-150` `knowledge_object_identity`; `:153`, `:163`, `:173-188`, `:200-234`, `:264-273`, `:291-302` key helpers | Called by `keys.py`, never re-implemented. |
| `knowledge/predicates.py:65` `SCHEMA` | Names the database-object kinds of the guarded alias pairs (section 8.8). |
| `knowledge/access.py:450-492` `grant`; `:458-459` internal audience; `:460` `mode == "unknown"` denies; `:476-480` a provider policy needs a deadline; `:514` artifact policy; `:529` span policy | Unknown is deny; a provider policy without `expires_at` is unreadable; both the artifact's and the span's policy are checked. |
| `ingest/readers.py:131-142` `is_probably_binary`, `:145-146` `is_code_name`, `:149-175` `lang_of`, `:189-196` `is_plain_prose_name` | The name rules of classification, called unchanged. |
| `ingest/provenance.py:288-297` `_lines` | The physical-line rule (CRLF, LF, CR, terminators kept) the `file_lines` verifier reuses. |
| `codegraph/data_access.py:181-188` `_parse_sql` | Not reused: it swallows every error into `[]`, so "not SQL" and "no statements" look alike. |
| `store/generations.py:1479-1545` `_validate_managed_native` (Passage) | A passage row's `text` must equal the view or span text, its id must be `generation_passage_id(...)`, and it needs a vector. S2 builds rows that pass; S3 adds the vector. |
| `store/migrations.py:138-146` `PASSAGE_COLUMNS` | No `ts` column (deviation DV1). |
| `knowledge/projection.py:626-640` | `DEFINED_IN` attaches an object to a passage through an observation whose `span_id` equals the passage's. S2 lands `Passage.node_ref` there (section 8.2). |
| `tests/unit/test_layering.py:27-47` | Pins `knowledge` → `ingest` only. S2 adds the `knowledge` → `connectors` rule in its own test file. |

## 3. Requires from S1

S2 programs against the design's normative API (section 3), which S1's plan (section 5.2) keeps and
extends:

```python
class Registry:
    def register(
        self, extension: TypeExtension
    ) -> None: ...  # raises RegistrationError with the exact reason
    def freeze(self) -> None: ...  # after load; emit refuses an unfrozen registry
    def fingerprint(self) -> str: ...  # sha256 over the canonical JSON of everything registered
    def families(self) -> frozenset[Family]: ...
    def object_kind(self, name: str) -> ObjectKindDefinition: ...
    def predicate(self, name: str) -> PredicateDefinition: ...
    def locator(self, kind: str) -> type[SourceLocator]: ...
    def artifact_kind(self, name: str) -> Code: ...
    def connector_kind(self, name: str) -> Code: ...
    def evidence_source(self, name: str) -> Code: ...
```

plus `ObjectKindDefinition`, `PredicateDefinition` (with `owner_families` and `identity`) and
`TypeExtension` as the design's section 3 prints them at `ef143b1`. In addition, S2 uses the following.
The last column names the only S2 module to change if S1's plan spells a name differently.

| # | S2 uses | S1 plan reference | S2 module |
| --- | --- | --- | --- |
| R1 | From `hippo.knowledge.registry`: `Registry`, `REGISTRY`, `current_registry`, `use_registry`, `extension_scope`, `ObjectKindDefinition`, `PredicateDefinition`, `TypeExtension`, `LocatorKindDefinition`, `FactTemplate`, `Family`, `CUSTOM_FAMILY`, `RESERVED_TEMPLATE_FIELDS`, `RegistrationError`, `UnregisteredName`, `connector_configuration` | section 5.2, D2, D3 | all |
| R2 | The read-only property `Registry.frozen` | section 5.2 | `base.py`, `emit.py` |
| R3 | Every lookup of an unregistered name raises `UnregisteredName(KeyError)` | D3, section 5.2 "Lookups" | `base.py`, `keys.py`, `emit.py` |
| R4 | `FactTemplate(name, version, consumes, text)`; `text` fields are drawn only from `consumes` and `RESERVED_TEMPLATE_FIELDS` (`label`, `key`), enforced at `register` | D3, refusal row 11 | `render.py` |
| R5 | `Registry.declared_template_versions(kinds) -> dict[str, str]` and `connector_configuration(*, name, version, templates, parsers) -> dict` | D25 | `base.py` |
| R6 | The built-in `key_template`s of S1's D13 table, including the instance parts `provider_instance`, `catalog_instance` and `instance` | D13, section 5.3 | `keys.py` |
| R7 | `SAME_OBJECT_AS` built in with `identity=True`; `checked_assertion` requires two distinct objects with the subject first by `(canonical_key, kind)` | D12 | `emit.py` |
| R8 | `EvidenceClass` with `rule_derived` and `similarity_inferred` | brief item 6 | `emit.py` |
| R9 | `AssertionVersion.family`, `source`, `rule`, `weight`, `statement: Text \| None`, `unit_id`, outside identity, with the `kit_provenance` rules (family and source together; `source == "rule"` needs `rule`; `weight == confidence`) | section 6.1, D18 | `emit.py` |
| R10 | `Unit` exactly as S1's section 6.1 (`embed_text == prefix + text`; a rendered unit has a `template` of `name@version` and an empty `prefix`; `mentions_json` sorted and unique), and `"Unit"` in `GenerationEvidenceMember.record_kind`. S1 ships `Unit` in S1b (S1 deviation 1), so S2b depends on S1b | section 6.1, D15 | `emit.py` |
| R11 | Registry-validated `KnowledgeObject.kind`, `Artifact.kind`, `Connector.kind`, `EvidenceSpan.locator_kind` and `canonical_locator_json` | D8, D9 | `emit.py`, `keys.py` |
| R12 | `extension_scope()` for tests: register a throwaway extension into the current registry, freeze it, restore it after | D2 | tests |

**One consequence S2 states for every caller** (ruling R16). The Pydantic validators consult
`current_registry()` (S1 plan section 5.2), which defaults to `REGISTRY` and which `use_registry()`
replaces for a bounded run and `extension_scope()` extends in place. A record naming an extension kind
therefore validates only if that kind is registered in the current registry. `bind_batch` refuses a
registry that is not `current_registry()` (section 8.1), so a binder and the model can never disagree
about the vocabulary. S2 plans no loader: S4 builds and installs the registry (ruling R15).

## 4. Public API

All records subclass `Contract`. Field order is as written. Section 4.6 lists every validator and its
exact message.

### 4.1 `connectors/base.py`

```python
from collections.abc import Callable
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ..knowledge import model as k
from ..knowledge.model import Code, Contract, Instant, Json, Nonnegative, Positive, TemporalPrecision, Text
from ..knowledge.registry import (  # re-exported: S4 R-S2-8, S6 R-S2-1
    FactTemplate,
    Family,
    ObjectKindDefinition,
    PredicateDefinition,
    Registry,
    TypeExtension,
)

Clock = Callable[[], datetime]
PASSAGE_CHAR_BOUND = 1500
UNCLASSIFIED = "custom/unclassified"


def token_count(text: str) -> int: ...  # the one counter (ruling R11): len(text), the chunker's measure


class ContractError(ValueError):
    """A connector produced something the contract refuses; the message is for its developer."""


class RegistrationRequired(ContractError):
    def __init__(self, message: str, *, kinds: tuple[str, ...], predicates: tuple[str, ...], skeleton: str):
        super().__init__(message)
        self.kinds, self.predicates, self.skeleton = kinds, predicates, skeleton


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

    @property
    def spelling(self) -> str: ...  # "tree-sitter/python@0.23"

    @classmethod
    def parse(cls, spelling: str) -> "ParserVersion": ...


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

    def validate_against(self, registry: Registry) -> None: ...


def descriptor_configuration(descriptor: ConnectorDescriptor, registry: Registry) -> dict: ...


class ExternalRef(Contract):
    partition: Code
    artifact_kind: Code
    external_id: Text
    provider_revision: Text | None = None


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


class RawFetch(Contract):
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


class PolicyObservation(Contract):
    ref: ExternalRef
    state: Literal["known", "unknown"]
    mode: Literal["restricted", "workspace"] | None = None
    allow_users: tuple[Text, ...] = ()
    allow_groups: tuple[Text, ...] = ()
    deny_users: tuple[Text, ...] = ()
    deny_groups: tuple[Text, ...] = ()


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

    @property
    def mapping_hash(self) -> str: ...

    def validate_against(self, registry: Registry) -> None: ...


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


KeyValue = Text | SqlPart | tuple[SqlPart, ...]


class NodeRef(Contract):
    kind: Code
    key: dict[Code, KeyValue]  # every key_template part except the instance parts


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
    reason: Code
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


class RevisionInput(Contract):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    partition: Code
    artifact: k.Artifact
    revision: k.ArtifactRevision
    data: bytes
    config: BaseModel
    mapping: TypeMapping
    registry: Registry


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
```

`descriptor_configuration(descriptor, registry)` returns exactly
`registry_module.connector_configuration(name=descriptor.name, version=descriptor.version,
templates=registry.declared_template_versions(descriptor.kinds), parsers=[p.spelling for p in
descriptor.parsers])`, which is S1's `{"connector": {...}}` shape (S1 D25). It never contains
`registry.fingerprint()`: the amended design's section 3 forbids it, because `inputs._manifest_bytes`
hashes the configuration and the generation id hashes the manifest. S3 merges it into a kit generation's
configuration; S5's ported lanes do not call it.

`probe`'s `clock` exists for the connector's own bounded HTTP (deadlines, backoff). It never enters a
`Classification`; the purity test runs `classify` under two clocks and compares.

`Family` and `Clock` are importable from `hippo.connectors.base` (S4's R-S2-1).

### 4.2 `connectors/keys.py`

```python
KEY_RULE_VERSION = "cdk-keys-v1"
INSTANCE_PARTS = frozenset({"instance", "provider_instance", "catalog_instance"})


@dataclass(frozen=True, slots=True)
class CanonicalKey:
    kind: str
    parts: tuple  # the canonical JSON array hashed by knowledge_object_identity
    readable: str  # "wi:https://jira.example/10042"

    @property
    def canonical_json(self) -> str: ...


def check_key_parts(definition: ObjectKindDefinition, ref: NodeRef) -> None: ...


def canonical_key(registry: Registry, ref: NodeRef, *, instance: str) -> CanonicalKey: ...


def knowledge_object(
    registry: Registry, ref: NodeRef, *, workspace_id: str, instance: str
) -> k.KnowledgeObject: ...
```

### 4.3 `connectors/classify.py`

```python
CLASSIFIER_VERSION = "cdk-classify-v1"


class SampledItem(Contract):
    partition: Code
    path: Text  # normalized relative path, or a provider record type for API connectors
    data: bytes
    provider_type: Text | None = None


@dataclass(frozen=True, slots=True)
class ItemDecision:
    family: str  # a registered family, or CUSTOM_FAMILY
    kind: str | None
    template: str | None
    dialect: str | None
    evidence: ClassificationEvidence

    @property
    def unclassified(self) -> bool: ...


def classifier_spec(
    *, declarations: tuple[PathDeclaration, ...] = (), sql_dialects: tuple[str, ...] = ()
) -> ClassifierSpec: ...


def classify_item(item: SampledItem, spec: ClassifierSpec) -> ItemDecision: ...


def classify(
    descriptor: ConnectorDescriptor,
    config: BaseModel,
    items: Iterable[SampledItem],
    registry: Registry,
    *,
    spec: ClassifierSpec,
    capabilities: ConnectorCapabilities,
    kinds: tuple[KindMapping, ...] = (),
    attributes: tuple[AttributeMapping, ...] = (),
) -> Classification: ...
```

### 4.4 `connectors/render.py`

```python
RENDER_RULE_VERSION = "cdk-render-v1"
PREFIX_TOKEN_LIMIT = 12
PREFIX_SEPARATOR = ": "


@dataclass(frozen=True, slots=True)
class RenderedText:
    text: str
    prefix: str
    embed_text: str
    content_hash: str
    embed_hash: str
    template: str | None


def kind_label(definition: ObjectKindDefinition) -> str: ...


def render_label(definition: ObjectKindDefinition, attrs: BaseModel) -> str: ...


def render_facts(
    definition: ObjectKindDefinition, attrs: BaseModel, *, label: str, key: CanonicalKey
) -> tuple[RenderedText, ...]: ...


def edge_statement(
    predicate: PredicateDefinition,
    subject: tuple[ObjectKindDefinition, str],
    object_: tuple[ObjectKindDefinition, str],
    *,
    source_statement: str | None = None,
    rule: str | None = None,
    rule_evidence: str | None = None,
) -> str: ...


def heading_prefix(heading_path: tuple[str, ...]) -> str: ...


def symbol_prefix(symbol: str) -> str: ...


def unit_text(text: str, *, prefix: str = "", template: str | None = None) -> RenderedText: ...
```

### 4.5 `connectors/emit.py`

```python
BINDER_VERSION = "cdk-emit-v1"


class BindRefused(ContractError):
    """One emission the kit will not store; the message names the fix."""


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
    def scope_key(self) -> str: ...  # f"source:{source_id}:{partition}"

    @property
    def instance(self) -> str: ...  # connector.instance_url, already normalized


@dataclass(frozen=True, slots=True)
class BoundPassageRow:
    generation: k.Generation
    span: k.EvidenceSpan
    view: k.RetrievalView | None
    ordinal: int
    title: str
    text: str

    @property
    def id(self) -> str: ...

    def native_row(self) -> dict: ...


@dataclass(frozen=True, slots=True)
class EmissionCoverage:
    nodes: int = 0
    edges: int = 0
    passages: int = 0
    units: Mapping[str, int] = field(default_factory=dict)
    aliases: Mapping[str, int] = field(default_factory=dict)
    hints: Mapping[str, int] = field(default_factory=dict)
    failures: Mapping[str, int] = field(default_factory=dict)
    unclassified: int = 0

    def __add__(self, other: "EmissionCoverage") -> "EmissionCoverage": ...

    def to_json(self) -> dict: ...


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


def evidence_class(family: str, source: str, metadata_origin: str | None = None) -> str: ...


def verify_span(data: bytes, span: SpanRef, *, artifact: k.Artifact) -> str: ...


def check_direction_and_ownership(
    registry: Registry, descriptor: ConnectorDescriptor, predicate: str, subject_kind: str, object_kind: str
) -> PredicateDefinition: ...


def policy_record(
    policy: PolicyObservation,
    *,
    connector: k.Connector,
    workspace_id: str,
    observed_at: datetime,
    expires_at: datetime,
) -> k.AccessPolicy: ...


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
) -> CapturedRevision: ...


def bind_batch(context: BindContext, revision: RevisionInput, batch: EmissionBatch) -> BoundBatch: ...


def merge_bound(batches: Iterable[BoundBatch]) -> BoundBatch: ...
```

### 4.6 Validators and their messages

| Record | Rule | Message |
| --- | --- | --- |
| `ParserVersion` | `name` matches `^[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)?$`, `version` matches `^[0-9A-Za-z][0-9A-Za-z_.+-]{0,63}$`; `parse` splits on the last `@` | `Parser version must be spelled name@version, e.g. tree-sitter/python@0.23` |
| `ConnectorDescriptor` | `version` matches `^[0-9A-Za-z][0-9A-Za-z_.+-]{0,63}$` | `Connector version must be a short token such as 1.2.0` |
| `ConnectorDescriptor` | `families`, `artifact_kinds`, `locator_kinds` non-empty | `A connector declares at least one family, artifact kind and locator kind` |
| `ConnectorDescriptor` | no duplicates in any tuple | `Connector descriptor lists {field} {value!r} twice` |
| `ConnectorDescriptor` | `config_model.model_config.get("extra") == "forbid"` | `Connector configuration model {name} must set extra="forbid"` |
| `ConnectorDescriptor.validate_against` | every kind, predicate, artifact kind, locator kind and family resolves (R3) | `RegistrationRequired("{descriptor} names unregistered types: {names}; register a TypeExtension first", ...)`, whose `skeleton` is a `TypeExtension(...)` source snippet naming them |
| `ExternalRef` | `external_id` has no control characters | `External ids cannot contain control characters` |
| `ChangePage` | every change's `ref.partition`, and `next_cursor.partition`, equal `partition` | `A change page cannot mix partitions` |
| `RawFetch` | `external_id == ref.external_id` | `RawFetch.external_id must equal the requested ref` |
| `RawFetch` | `canonical_uri` has no userinfo (`urllib.parse.urlsplit(uri).username is None`) | `Canonical URIs cannot carry credentials` |
| `RawFetch` | `source_updated_at` set iff `source_timestamp_original` set | `A source timestamp needs its original spelling, and only with a timestamp` |
| `PolicyObservation` | `state="unknown"` → `mode is None` and all four lists empty | `An unknown policy carries no principals; the runtime stores it as deny` |
| `PolicyObservation` | `state="known"` → `mode` set | `A known policy needs a mode` |
| `PolicyObservation` | `mode="restricted"` → `allow_users` or `allow_groups` non-empty | `A known restricted policy needs at least one allowed principal; report state="unknown" instead` |
| `TypeMapping` | `provider_type` unique | `Provider type {value!r} is mapped twice` |
| `TypeMapping.validate_against` | every mapped kind and predicate resolves; each attribute is a field of its kind's `attrs_model` | `RegistrationRequired` as above; for an attribute, `Kind {kind} declares no attribute {attribute}` |
| `SqlPart` | no NUL | `SQL identifiers cannot contain NUL` |
| `NodeRef` | `key` non-empty; every string value non-empty | `A node reference needs its key parts` |
| `NodeEmission` | `ts` set iff `ts_original` set | `A node ts needs its original spelling, and only with a ts` |
| `EdgeEmission` | `family="deterministic"` → `weight == 1.0` | `Deterministic edges carry weight 1.0` |
| `EdgeEmission` | `source="rule"` ↔ `rule` and `rule_evidence` both set | `A rule-derived edge names its rule and its evidence, and only a rule-derived edge does` |
| `EdgeEmission`, `NodeEmission` | `source="metadata"` ↔ `metadata_origin` set | `Metadata provenance must say catalog or declaration` |
| `EdgeEmission` | not both `unit` and `source_statement` | `An edge reuses a statement unit or quotes a source statement, not both` |
| `EdgeEmission` | `valid_to` requires `valid_from`, and `valid_to > valid_from` | `An edge window needs a start before its end` |
| `UnitEmission` | `start`/`end` both set or both unset, and `start < end` | `Unit offsets come as a nonempty start/end pair` |
| `ParseFailure` | `reason` is a `Code` | the `Code` pattern error; reasons are short codes, never exception text |
| `EmissionBatch` | passage and unit keys unique; every `unit.passage` names a batch passage; every `edge.unit` names a batch unit | `Emission key {key!r} is duplicated` / `Emission names missing {what} {key!r}` |
| `RevisionInput` | `revision.artifact_id == artifact.id` | `Revision does not belong to its artifact` |
| `RevisionInput` | `revision.content_hash == hashlib.sha256(data).hexdigest()` | `Revision bytes differ from the revision's content hash` |
| `RevisionInput` | `registry.frozen` (R2) | `emit requires a frozen registry` |

`SpanRef.locator` is validated at bind, through `k.canonical_locator_json`, which dispatches on the
registered locator kind (R11). Construction does not validate it, because the vocabulary is the
registry's and a contract record is built before a registry is consulted.

## 5. Classification on connect (brief decision 3)

`classify_item(item, spec)` is the design's order as code. The first rule that decides wins:

1. **Declaration.** The first `PathDeclaration` in `spec.declarations` whose `pattern` matches
   (`fnmatch.fnmatchcase(item.path, pattern)`) decides the family and its `kind`, `template` and
   `dialect`. A declaration with `shape="tabular"` also requires step 2's tabular shape and otherwise
   falls through with the warning `declared_tabular_shape_missing`. Evidence: `rule="declaration"`,
   `detector="declaration"`.
2. **Content.** Runs only when `readers.is_probably_binary(item.data)` is false and the bytes decode as
   strict UTF-8 with a leading BOM removed (the `plain-utf8-sig-v1` reader rule,
   `ingest/prose_generation.py:202`). Detectors, in order:
   - `sqlglot.ddl:{dialect}`, for each dialect of `spec.sql_dialects` in order. `sqlglot.parse(text,
     dialect=dialect, error_level=ErrorLevel.RAISE)` inside `try`. It decides `db` only when it raises
     nothing, returns at least one statement, returns no `sqlglot.exp.Command`, every statement is a
     `Create`, `Alter`, `Drop`, `Insert`, `Update`, `Delete`, `Merge` or `Select`, and at least one is a
     `Create`, `Alter` or `Drop`. sqlglot 30 falls back to `Command` for unsupported syntax instead of
     raising; that was checked against the root venv while planning. The DDL requirement stops prose
     that parses as a `SELECT` ("Select a source from the list.", `codegraph/data_access.py:170-178`)
     from becoming `db`.
   - `backstage.catalog`: basename `catalog-info.yaml` or `catalog-info.yml` and a line
     `^apiVersion:\s*backstage\.io/`. Decides `service`, kind `service`.
   - `api.header`: the first non-blank line that is not a `#` comment matches
     `^(openapi|asyncapi|swagger)\s*:`, or the document is a JSON object with one of those top-level keys.
     Decides `service`, kind `api`.
   - `k8s.manifest`: `^apiVersion:\s*\S` and `^kind:\s*\S` at column 0 before the first `^---`, or a
     JSON object with both keys. Decides `service`.
   - `heading.signature`: case-folded Markdown headings (`^#{1,6}\s+(.+?)\s*#*\s*$`) contain every
     heading of one signature of the specification's section 5.1, tried in this order: `adr` {status,
     context, decision, consequences}, `prd` {problem, goals, requirements, non-goals}, `runbook`
     {prerequisites, steps, verification, rollback}, `postmortem` {summary, impact, timeline, root cause,
     action items}. Decides `prose` with that template.
   - `tabular.ndjson`, `tabular.json_array`, `tabular.csv`: every non-empty line is a JSON object with one
     identical key set; or the document is a JSON array of objects with one identical key set; or
     `csv.reader` reads a first row of at least two columns and at least one more row, all the same
     width. Without a declared kind the item is `custom/unclassified` with the warning
     `tabular_without_declared_kind` (the design: "tabular rendered facts under a declared kind").
3. **Name.** `readers.lang_of(item.path)` not `None` decides `code` (`detector="readers.lang_of"`);
   `readers.is_code_name` decides `code` (`"readers.is_code_name"`); `readers.is_plain_prose_name` decides
   `prose` (`"readers.is_plain_prose_name"`); `readers.is_probably_binary(item.data)` decides
   `custom/unclassified` (`"readers.is_probably_binary"`).
4. **Nothing decided.** `custom/unclassified`, `detector="none"`, `rule="unclassified"`.

For API connectors, whose items are provider record types, `KindMapping` rows decide the kind, and an
unmapped `provider_type` is `custom/unclassified` in the partition's family with `rule="unclassified"`.
`custom/unclassified` is a count and an evidence row, never an object kind.

`classify(...)` sorts the items by `(partition, path)`, calls `classify_item` on each, and returns one
`PartitionClassification` per partition:

- `family`: the single decided family when every classified item agrees; else the descriptor's family
  when it declares exactly one; else `CUSTOM_FAMILY`.
- `counts`: items per family, plus `custom/unclassified`.
- `evidence`: every decision; the sample bounds its size.
- `mapping.classifier`: `spec`, so emit re-runs exactly this procedure on bytes probe never saw, and
  "the same bytes classify the same way on every sync".

`mapping.validate_against(registry)` runs last. A kind no connector registered raises
`RegistrationRequired`, and no `Classification` is returned, so nothing is stored (the design's section 2).
`registry_fingerprint` is `registry.fingerprint()`.

Purity: `classify` touches only its arguments. The test runs it twice, under two clocks and with the
items reversed, while `socket.socket.connect` and `time.time` are monkeypatched to raise, and asserts
equal `Classification`s. S3's per-thread emit guard is not needed for a pure function.

## 6. Canonical keys (brief decision 2)

**One rule for every kind.** S1's D13 gives each kind a `key_template` that names the positions of the
canonical key. `canonical_key(registry, ref, instance=...)`:

1. Looks the kind up (`registry.object_kind`; `UnregisteredName` becomes `BindRefused`).
2. `check_key_parts(definition, ref)`: `set(ref.key)` must equal the template's parts minus
   `INSTANCE_PARTS`. An instance part in `ref.key` refuses with `The kit fills {part} of {kind} from the
   connector's instance; do not emit it`. A missing or extra part refuses with `NodeRef for {kind} needs
   key parts {expected}, got {names}`.
3. Assembles the values in template order. Each instance part gets `instance`: the Connector row's
   `instance_url`, already normalized by `normalize_provider_url` (`model.py:98`, `identity.py:75-111`:
   ASCII or explicit punycode hosts, no userinfo). So the workspace, and then the provider instance, are
   the first parts wherever S1's template puts an instance part first. The workspace itself is never a
   key part: `knowledge_object_identity(workspace, kind, key)` adds it (`identity.py:148-150`).
4. Normalizes through the identity helper that already builds that shape. This is reuse, not a second
   spelling, and the parity test for each row compares the result with the helper's output:

| Kinds | Template (S1 D13) | Normalized by | Anchor |
| --- | --- | --- | --- |
| `service`, `system`, `domain` | `catalog_instance, reference` | `service_key(catalog_instance, reference)` | `identity.py:173-188` |
| `repository` | `provider_instance, repository_id` | `repository_key(provider_instance, repository_id)` | `identity.py:153-154` |
| `review` | `provider_instance, repository_id, review_id` | `review_key(...)` | `identity.py:163-164` |
| `endpoint` | `service, protocol, api_identity, api_version, method, path_template` | `endpoint_key(service, protocol, api_version, method, path_template, api_identity=...)` | `identity.py:291-302` |
| `api` | `service, protocol, api_identity, api_version` | `endpoint_key(...)[:4]` with a placeholder method and path, so protocol casing is the helper's | `identity.py:291-302` |
| `symbol` | `repository, language, path, qualified_name, symbol_kind, signature` | `symbol_key(repository, language, path, qualified_name, signature, kind=symbol_kind)` | `identity.py:264-273` |
| `table`, `column`, `view`, `constraint`, `index`, `routine` | `instance, environment, catalog, schema, parts` | `database_object_key(instance, environment, catalog, schema, parts)`, with each `SqlPart` through `sql_identifier(...)` | `identity.py:200-234` |
| `database`, `schema` | the first three or four parts of the above | the same call's leading parts | `identity.py:215-234` |
| `file` | `repository, path` | `[repository, normalize_relative_path(path)]` | the only writer, `code_binding.py:835-840`; parity test |
| `commit` | `repository, sha` | `[repository, sha]` | the only writer, `code_history.py:943-944`; parity test |
| `resource` | `repository, dialect, data_kind, qualname` | `[repository, dialect, data_kind, qualname]` | the only writer, `code_binding.py:880-887`; parity test |
| every other kind, and every extension kind | the registered template | plain values; a `SqlPart` or tuple value refuses: `Kind {kind} has plain key parts; SqlPart values belong to database kinds`; a control character refuses: `Key part {name} of {kind} contains control characters` | none |

`file`, `commit` and `resource` have no public helper, so the arrays are spelled here and a test builds
the same objects through `code_binding._file_object`, `code_binding._data_object` and the commit
construction and asserts equal ids. Question Q1 asks for public helpers.

The code lane writes `table` and `column` objects under the `resource` shape, `[repository, dialect,
data_kind, qualname]` (`code_binding.py:880-887`), while `keys.py` builds catalog tables with
`database_object_key`. A table seen in code and in a catalog is two objects until an alias rule joins
them. That is S1's open question 2; S2 does not re-key the code lane.

`readable` is `f"{definition.key_prefix}:{'/'.join(...)}"` over the parts, each nested value rendered
with `canonical_json`. It is used for display, logs, goldens and attribute units, and never hashed
(decided by S2).

`knowledge_object(...)` returns `k.KnowledgeObject(workspace_id=..., kind=ref.kind,
canonical_key=canonical_json(list(parts)))` and asserts `result.id == knowledge_object_identity(workspace_id,
ref.kind, list(parts))`. It is the only `KnowledgeObject(` call in `src/hippo/connectors`, which a static
test enforces (CK2: "identities come only from `connectors/keys.py`").

Of the provider-instance rules the design names: hostnames are ASCII or punycode (`normalize_provider_url`);
database identifiers keep dialect-aware parts (`sql_identifier`); a Jira key is an alias while the
immutable issue id is the identity. S1's `ticket` template is `provider_instance, issue_id` for that
reason; a connector reports the Jira key as an attribute and an `AliasEmission`.

## 7. Rendering (brief decision 4)

- `kind_label(definition)` is `definition.name.replace("_", " ")`, since the registry has no display
  label (decided by S2).
- `render_label(definition, attrs)` is `definition.label_template.format_map(attrs.model_dump(mode="json"))`.
  S1 refuses a label field that is not an attribute at registration (S1 refusal row 11). A `KeyError`
  here still becomes `BindRefused("Label template of {kind} names a missing attribute {name}")`.
- `render_facts(definition, attrs, label=..., key=...)` returns one `RenderedText` per
  `definition.fact_templates` entry, in registration order. Its text is
  `template.text.format_map({name: attrs_json[name] for name in template.consumes} | {"label": label, "key": key.readable})`,
  with `prefix=""` and `template=f"{template.name}@{template.version}"`. Those are exactly the fields S1
  admits (`consumes` plus `RESERVED_TEMPLATE_FIELDS`). One invocation is one unit, so forty column nodes
  are forty invocations and nothing ever joins two outputs. A template with a consumed attribute whose
  value is `None` is not invoked: no unit, no error, and `coverage["facts_skipped"][template]` counts it
  (S6 R-S2-5; an open incident has no resolution fact to state).
- `edge_statement(predicate, (s_def, s_label), (o_def, o_label), ...)` is
  `f"{kind_label(s_def)} {s_label} {predicate.verb_phrase} {kind_label(o_def)} {o_label}"`. It then appends
  `f": {source_statement}"` when a source statement exists, and
  `f" ({rule.replace('_', ' ')}: {rule_evidence})"` for a rule-derived edge. This reproduces the
  specification's section 3 examples. S1's built-in verb phrases name no endpoint kind (S1 section 10),
  so the kind labels are never doubled.
- `heading_prefix(path)` keeps the innermost heading's first `PREFIX_TOKEN_LIMIT` whitespace-separated
  tokens and appends `PREFIX_SEPARATOR`. `symbol_prefix(symbol)` is `symbol + PREFIX_SEPARATOR`. The
  separator lives in the prefix because S1's `Unit` requires `embed_text == prefix + text` (S1 D15). It
  reproduces the specification's "Locking strategy: It takes an exclusive lock" (section 5.1) and
  "{enclosing symbol}: {source line}" (section 5.2). Decided by S2.
- `unit_text(text, prefix=..., template=...)` sets `embed_text = prefix + text`,
  `content_hash = identity.text_hash(text)` and `embed_hash = identity.text_hash(embed_text)`
  (`identity.py:71`). Identical text under two headings therefore shares `content_hash` but not
  `embed_hash`, as the amended design's section 4 requires, and `embed_hash` equals the embedding cache's
  input hash (S1 D17).
- **The one token counter** (ruling R11) is `base.token_count(text) == len(text)`. It reuses the only
  measure `ingest/chunker.py` has for its own budget: characters (`size_chars`, `chunker.py:71`; the
  module docstring's "default 1500 characters, about 350 tokens", `:6`). A character count never
  under-counts subword tokens, so a passage of at most 1,500 characters is within the 1,500-token bound,
  and the bound coincides with the chunker's default chunk size. S2's binder, S4's kit and S6's exemplar
  import this function and no other. Ruling R11 names the module `connectors/contract.py`; no plan or the
  design has that module (the design's contract module is `connectors/base.py`, sections 1 and 13), so the
  function lives in `base.py`, and the ruling's substance, one counter reusing the chunker's measure, holds.
- Template versions reach the configuration through `descriptor_configuration` and the registry
  fingerprint through S1. A changed template version is therefore a new manifest (S1 D25).

## 8. Binding a batch to records (brief decision 5)

### 8.1 Order of operations in `bind_batch`

`bind_batch(context, revision, batch)` is pure and deterministic. It refuses (`BindRefused`) at the first
violation and never returns a partial result.

1. `context.registry is current_registry()` and `context.registry.frozen` (ruling R16); otherwise `Bind
   requires the frozen current registry that the knowledge model validates against`.
2. Every kind, predicate, locator kind and evidence source named in the batch must resolve (R3):
   `{what} {name!r} is not registered; register it with a TypeExtension before emitting`. Each must also be
   declared (`descriptor.kinds`, `predicates`, `locator_kinds`): `{descriptor} emits {what} {name!r} it
   does not declare`.
3. Bind every `SpanRef` to a `k.EvidenceSpan` whose text is `verify_span(revision.data, span_ref,
   artifact=revision.artifact)` and whose `policy_id` is `revision.artifact.policy_id`. Identical spans
   collapse.
4. Nodes: validate `attrs` with the kind's `attrs_model` (S1 leaves this to S2, S1 D6), build the object
   with `keys.knowledge_object`, render the label and facts, and bind one `ObjectObservation` on the node's
   span; a node of a family the connector does not declare binds identity-only (section 8.7, ruling R6).
5. Passages, then units: slice units from `UnitEmission`, rendered units from nodes and edges.
6. Edges: `check_direction_and_ownership`, the assertion through `k.checked_assertion`, one version per
   fact, its support groups.
7. Aliases, then hints.
8. Membership: one `GenerationEvidenceMember` for each `EvidenceSpan`, `ObjectObservation`,
   `AssertionVersion`, `AssertionSupport`, `Unit`, `RetrievalView`, `DerivedRecord` and `DerivedDependency`.
   `KnowledgeObject` and `Assertion` carry identity only and get none (`knowledge/staged_code.py:354-358`).
9. Coverage.

### 8.2 The totality table

Every field of the specification's section 3 records (`docs/spec/enterprise-graph-rag-v1.md:212-261`)
and where it lands. Section 10's table-driven test is this table as data.

| Spec record.field | Emission field | Knowledge record.column | Rule |
| --- | --- | --- | --- |
| `Node.id` | `NodeEmission.ref` | `KnowledgeObject.id`, `ObjectObservation.object_id` | `keys.knowledge_object`; a connector cannot write an id (`extra="forbid"`) |
| `Node.type` | `ref.kind` | `KnowledgeObject.kind` | registered kind |
| `Node.domain` | the registered kind's `family` | no per-row column; `coverage["nodes_by_family"]` | the family is a property of the kind (design section 4) |
| `Node.label` | none (rendered) | `ObjectObservation.attributes_json["label"]` | `render.render_label` |
| `Node.attrs` | `attrs` | `ObjectObservation.attributes_json["attrs"]` | `attributes_json = canonical_json({"attrs": ..., "key": key.readable, "label": ...})` |
| `Node.ts` | `ts`, `ts_original`, `ts_timezone`, `ts_precision` | `ObjectObservation.valid_from`, `validity_kind="explicit_interval"`, `temporal_basis="source_explicit"`, `temporal_precision`, `source_timestamp_original`, `source_timezone` | with no `ts`: `validity_kind="observed_snapshot"`, `temporal_basis="observed"`, `temporal_precision="instant"` (`code_binding.py:101-105`) |
| `Node.provenance.source_system` | none (the connector) | `Artifact.connector_id`, `Artifact.provider_instance` | `capture_records` |
| `Node.provenance.uri` | `RawFetch.canonical_uri` | `Artifact.canonical_uri` | `capture_records` |
| `Node.provenance.path` | `RawFetch.external_id` | `Artifact.external_id` | `capture_records` |
| `Node.provenance.span` | `span` | `EvidenceSpan.locator_kind`, `EvidenceSpan.locator_json`; `ObjectObservation.span_id` | verified (section 8.4) |
| `Node.provenance.version` | `RawFetch.provider_revision`, `data` | `ArtifactRevision.provider_revision`, `ArtifactRevision.content_hash` | `capture_records` |
| `Node.provenance.observed_at` | none (the runtime's instant) | `ArtifactRevision.observed_at`; `ObjectObservation.recorded_from = generation.created_at` | S2 never reads a clock |
| `Node.provenance.parser` | `RawFetch.parser` | `ArtifactRevision.metadata_json["parser"]` | `capture_records` |
| `Node.acl` | `PolicyObservation` | `Artifact.policy_id`, `EvidenceSpan.policy_id` → `AccessPolicy` | `policy_record` (section 8.9) |
| `Edge.src`, `Edge.dst` | `subject`, `object` | `Assertion.subject_id`, `Assertion.object_id` | `keys.knowledge_object`, then `k.checked_assertion` |
| `Edge.type` | `predicate` | `Assertion.predicate` | registered; direction and ownership (section 8.5) |
| `Edge.family` | `family` | `AssertionVersion.family` | R9 |
| `Edge.source` | `source`, `metadata_origin` | `AssertionVersion.source`; `AssertionVersion.evidence_class` | evidence-class table (section 8.3) |
| `Edge.rule` | `rule` | `AssertionVersion.rule`; `AssertionVersion.rule_version = f"{descriptor.name}@{descriptor.version}#{rule}"`, or `f"{descriptor.name}@{descriptor.version}"` without a rule | decided by S2, so two rules never share a version id |
| `Edge.weight` | `weight` | `AssertionVersion.weight`, `AssertionVersion.confidence` | design section 4: `confidence = weight` (S1 enforces equality) |
| `Edge.statement` | `source_statement`, `rule_evidence`; the rest rendered | `AssertionVersion.statement` | `render.edge_statement`; always set |
| `Edge.unit_ref` | `unit` | `AssertionVersion.unit_id` | the named statement unit, else the edge's own `rendered_edge` unit |
| `Edge.valid_from`, `Edge.valid_to` | `valid_from`, `valid_to`, `window_precision` | `AssertionVersion.valid_from`, `valid_to`, `validity_kind="explicit_interval"`, `temporal_basis="source_explicit"`, `temporal_precision` | a windowed predicate without a window: `validity_kind="unknown"`; an unwindowed predicate: `observed_snapshot`, and a window refuses |
| `Edge.provenance` | `support` | `AssertionSupport(assertion_version_id, span_id, derivation_group)` | one derivation group per `SupportEmission` (section 8.6) |
| `Passage.id` | `PassageEmission.key` (batch-local) | `Passage.id = generation_passage_id(generation.id, revision.id, span.id, ordinal, retrieval_view_id=...)` | `lifecycle.py:73-89` |
| `Passage.node_ref` | `node` | verbatim passage: the node's `ObjectObservation.span_id == Passage.span_id`, the attachment `projection.py:626-640` reads; derived passage: `RetrievalView.object_id` | a node observed on another span refuses (section 8.5) |
| `Passage.title` | `title` | `Passage.title` (native row) | `BoundPassageRow.native_row` |
| `Passage.text` | none (derived) | `Passage.text` | verbatim: the verified span text; derived: its one rendered unit's text (section 8.7) |
| `Passage.ts` | `ts` | no column (deviation DV1); equals the node observation's `valid_from` or `ArtifactRevision.source_updated_at` | any other value refuses |
| `Passage.provenance` | `span` | `Passage.span_id`, `Passage.artifact_revision_id` | verified |
| `Passage.acl` | none | `EvidenceSpan.policy_id` of the passage span | the artifact policy |
| `Unit.id` | `UnitEmission.key` (batch-local) | `Unit.id` from `("generation_id", "passage_id", "ordinal", "content_hash")` | R10 |
| `Unit.passage_id` | `passage` | `Unit.passage_id` | the bound passage row's id |
| `Unit.ordinal` | `ordinal` | `Unit.ordinal` | slice units as emitted; a rendered unit is ordinal 0 of its derived passage (section 8.7) |
| `Unit.text` | `span`, `start`, `end` | `Unit.text`, `Unit.span_id` | a verified slice; for rendered kinds, the template output |
| `Unit.embed_text` | `prefix` | `Unit.prefix`, `Unit.embed_text`, `Unit.embed_hash` | `render.unit_text`: `embed_text = prefix + text` |
| `Unit.mentions` | `mentions` | `Unit.mentions_json`: object ids, sorted and unique (`model.py:794-798`) | rendered fact: `[node id]`; rendered edge: `[subject id, object id]` sorted |
| `Unit.kind` | `kind` | `Unit.kind` | slice kinds are emitted; the kit makes `rendered_fact` and `rendered_edge` (deviation DV4) |
| `Unit.content_hash` | none (derived) | `Unit.content_hash` | `sha256(text)` |
| `AliasCandidate.a`, `.b` | `AliasEmission.a`, `.b` | `Assertion(predicate="SAME_OBJECT_AS").subject_id`, `.object_id` | subject first by `(KnowledgeObject.canonical_key, kind)` (R7) |
| `AliasCandidate.rule` | `rule` | `AssertionVersion.rule`, `AssertionVersion.rule_version = f"{rule}@{descriptor.version}"` | amended design section 4 |
| `AliasCandidate.weight` | none (always 1.0) | `AssertionVersion.weight = 1.0`, `confidence = 1.0` | |
| `AliasCandidate.provenance` | `support` | `AssertionSupport` | as for edges |
| `Provenance.*` | see `Node.provenance.*` | the same columns | one mapping for all four records |

### 8.3 The evidence-class table

`evidence_class(family, source, metadata_origin)` is the design's section 4 table as a mapping. It is the
only way a binder record gets an `evidence_class`; neither `NodeEmission` nor `EdgeEmission` has the
field. Nodes use `family="deterministic"`.

| `family` | `source` | `metadata_origin` | `evidence_class` |
| --- | --- | --- | --- |
| deterministic | `parser` | | `syntax_observed` |
| deterministic | `metadata` | `catalog` | `catalog_observed` |
| deterministic | `metadata` | `declaration` | `declared` |
| deterministic | `rule` | | `rule_derived` |
| deterministic | `access_history`, `apm` | | `catalog_observed` (`AssertionVersion.source` keeps the source) |
| deterministic | `postmortem`, `slack` | | `discussion_claim` |
| probabilistic | `similarity`, `cooccurrence` | | `similarity_inferred` |
| any | `reviewed` | | `human_verified` |

Every other pair refuses: `No evidence class for family={family} source={source}; the derivation table in
the kit design section 4 is fixed`. So `deterministic`/`similarity`, `probabilistic`/`parser` and a
registered source outside the table all refuse (question Q4). No input yields `model_inferred`.

### 8.4 Span verification

The kit always computes a span's text from the revision bytes; a `SpanRef.text` is only a cross-check.
`verify_span(data, span, artifact=...)` first validates the locator through `k.canonical_locator_json`.
It then has verifiers for three locator kinds (decided by S2):

- `file_lines`: decode strict UTF-8 with an optional BOM removed, split physical lines with
  `ingest.provenance._lines` (`provenance.py:288-297`, terminators kept), and concatenate lines
  `start..end` (1-based, inclusive) with their terminators. An `end` past the last line refuses:
  `Locator {canonical locator} is outside the revision's {count} lines`. When the artifact kind is `file`,
  the locator's `path` must equal `artifact.external_id`: `A file_lines locator names a different file
  than its revision`.
- `field`: the bytes are one JSON document (strict UTF-8, `json.loads`). `field_path` is dot-separated,
  and an all-digit segment indexes an array. A string value is the text; any non-string value is its
  `canonical_json`. A missing path refuses: `Field {field_path} is absent from the revision document`.
- `table_cell`: the bytes are one CSV table (`csv.reader` over the decoded text); `table` must be `0`;
  `row` and `column` are 0-based over every row, header included. Out of range refuses:
  `Cell ({row}, {column}) is outside the revision table`.

Every other locator kind (`section`, `comment`, `page`, `diff_hunk`, and every registered locator kind)
refuses: `Locator kind {kind} has no byte verifier in the kit; spans of this kind cannot be emitted`
(deviation DV2). A `SpanRef.text` that differs from the computed text refuses: `Span text differs from the
revision bytes at {locator_kind} {canonical locator}`. The message names the locator and never quotes the
text. Unit offsets `start`/`end` slice the unit's own verified span text; out of range refuses
`Unit {key} offsets fall outside its span`.

### 8.5 Refusals the developer sees

`check_direction_and_ownership(registry, descriptor, predicate, subject_kind, object_kind)` returns the
predicate definition or raises one of the first three `BindRefused`s below. The binder and S4's kit call
this one function. Each message is exact:

- **Identity predicate as an edge.** `SAME_OBJECT_AS is an identity predicate; emit an AliasEmission with
  its rule`.
- **Reverse direction.** `(subject_kind, object_kind)` fails the predicate's endpoint rule and
  `(object_kind, subject_kind)` passes it: `{predicate} runs {sorted subject_kinds} -> {sorted object_kinds};
  this edge runs {subject_kind} -> {object_kind}, the reverse of its canonical direction. Swap subject and
  object if you own the fact, or emit a ReverseViewHint.` It is checked before ownership, so the more
  specific message wins.
- **Non-owner family.** `set(descriptor.families) & predicate.owner_families` is empty:
  `{descriptor.name} ({families}) cannot store {predicate}: its owner families are {owners}. Emit a
  ReverseViewHint for the view you observed, or an AliasEmission for an identity you can back with a rule.`
- **Any other endpoint mismatch.** `k.checked_assertion`'s own message, `Invalid endpoint kinds for
  {predicate}` (`predicates.py:113`; S1 keeps it, S1 D10).
- **Source not allowed.** `source not in predicate.sources_allowed`: `{predicate} does not accept source
  {source}; allowed: {allowed}`.
- **Window.** An unwindowed predicate with `valid_from`: `{predicate} is not windowed; drop
  valid_from/valid_to`.
- **Passage node.** `Passage {key} names node {kind}, but that node is observed on a different span; emit
  the node on the passage's span`.
- **Token bound.** `base.token_count(text) > PASSAGE_CHAR_BOUND`: `Passage {key} has {count} characters;
  split it at 1500 before emitting`.
- **Two statements for one fact.** Two edges in one batch bind to one `AssertionVersion` id with different
  `statement` or `unit_id`: `Edge {predicate} {subject} -> {object} is emitted twice with different
  statements; emit one EdgeEmission with two support groups`.
- **Hint for an owned predicate.** `{descriptor.name} owns {predicate}; emit the edge instead of a
  reverse-view hint`.

### 8.6 Versions and support groups

- One `Assertion` per `(subject, predicate, object, scope_key)`, with `scope_key =
  f"source:{source_id}:{partition}"` (amended design section 4).
- One `AssertionVersion` per fact: `assertion_id`; `evidence_class` (section 8.3); `rule_version` (section
  8.2); `confidence = weight`; `status="active"`; the temporal fields of section 8.2; `recorded_from =
  generation.created_at`; and `family`, `source`, `rule`, `weight`, `statement`, `unit_id` (R9).
- Each `SupportEmission` is one derivation group. `derivation_group = text_hash(canonical_json(sorted(span_ids)))[:32]`
  is deterministic and equal for equal AND-sets (decided by S2). Each span of a group is one
  `AssertionSupport`. Two `EdgeEmission`s that bind to one version id with the same statement and unit
  collapse into one version whose groups are the union; with different statements they refuse (section 8.5).
- `merge_bound(batches)` merges per-revision results for one generation. Records with equal ids must be
  equal, except `AssertionVersion`s that differ only in `statement` or `unit_id`. Of those, the one from
  the lexically smallest `(revision_id, derivation_group)` is kept, together with every support group of
  all of them (decided by S2; the store refuses a same-id record with different contents,
  `store/knowledge.py:772`). Any other unequal pair refuses: `Two revisions bind {kind} {id} with different
  contents`.

### 8.7 Units and passages

- **Slice units** (`sentence`, `statement`, `row`, `diff_line`) come from `UnitEmission`: `text` is the
  verified slice, `span_id` its span, `prefix` as emitted (built with `heading_prefix` or
  `symbol_prefix`), `template=None`.
- **Rendered facts get a derived passage each** (ruling R6). Every invoked fact template of a node's
  kind yields one `rendered_fact` unit (`span_id` the node's span, `ordinal` 0) and one derived passage
  that holds exactly that unit: the passage's `text` is the fact text, and its `span_id` is the record
  span the node is observed on. This is what the existing query path retrieves: it serves passages, and
  changing retrieval is outside this ledger (design section 14).
- **Rendered edges get a derived passage each** in the same way. An edge without `unit` yields one
  `rendered_edge` unit whose text is its statement, with `span_id` the first span of its first support
  group, `template=f"edge_statement@{RENDER_RULE_VERSION}"`, and one derived passage over that span. An
  edge with `unit` reuses that statement unit and makes neither.
- **The derived passage** is bound as a `projection` view in the shape `input_binding._view` uses
  (`input_binding.py:294-345`):
  - a `DerivedRecord(view_kind="projection", rule_version=BINDER_VERSION, input_revision_ids=...)`;
  - one `DerivedDependency` per cited span, with `dependency_version(span)`;
  - `RetrievalView(span_id=<record span>, source_revision_id=<revision>, view_kind="projection", text=...,
    text_profile=make_identity("text_profile", [BINDER_VERSION, RENDER_RULE_VERSION, <template>]),
    vector_profile=generation.embedding_profile, derivation_version=BINDER_VERSION,
    dependency_fingerprint=view_fingerprint(...), derived_record_id=..., object_id=<node id or None>)`.

  Its `title` is the node's rendered label (for an edge, the subject's), and its passage ordinal follows
  the batch's verbatim passages, sorted by `(template, node canonical key)` for facts and then
  `(predicate, subject id, object id)` for edges.
- **Verbatim passages** come only from `PassageEmission`: `text` is the verified span text, with no view.
- **Identity-only endpoints** (ruling R6). A node whose kind's family is not in `descriptor.families`
  (the kind must still be registered and declared in `descriptor.kinds`) binds identity-only: its
  `KnowledgeObject` and one minimal observation on its span, with `attributes_json` holding only `key`,
  no label, attributes or fact units. Its evidence class follows section 8.3 from its `source`. That is
  how a cross-domain edge gets its object (S6's `service`, the object of `AFFECTS`). Ownership is
  checked on edges, never on endpoint nodes.
- `BoundPassageRow.native_row()` has exactly the keys of `BoundPassage.native_row`
  (`input_binding.py:118-130`): `id`, `source_id`, `generation_id`, `artifact_revision_id`, `span_id`,
  `retrieval_view_id`, `embedding_profile`, `ordinal`, `title`, `text`. `ordinal` is the passage's
  position in the batch sorted by `(span id, key)`. S3 adds the vector and writes the row before its
  units (S1 section 10).

### 8.8 Aliases

`AliasEmission(a, b, rule, support)` binds to `Assertion(SAME_OBJECT_AS)` through `k.checked_assertion`.
The binder orders the endpoints so the subject is first by `(canonical_key, kind)`, the rule S1's
`checked_assertion` enforces (R7). A connector need not order them. The version has:

- `evidence_class="rule_derived"`, `rule_version=f"{rule}@{descriptor.version}"`, `source="rule"`,
  `rule=rule`, `weight=1.0`, `confidence=1.0`;
- the rendered statement and the `unit_id` of its `rendered_edge` unit;
- `observed_snapshot` timing;
- `status="candidate"` for the guarded kind pairs, unordered (`service`–`service`, `service`–`repository`,
  and any of `predicates.SCHEMA` (`predicates.py:65`) with `resource`), and `status="active"` otherwise.

`a == b` refuses: `An alias needs two distinct objects`. Review acceptance (`status="active"`,
`source="reviewed"`, `human_verified`) belongs to the reconciliation queue (Task 12), not the binder.

### 8.9 Capture records

`policy_record(policy, ...)` and `capture_records(fetch, policy, ...)` are the pure mappings S3's capture
step calls:

- `policy_record` builds `k.AccessPolicy(workspace_id, origin="provider",
  scope_key=f"connector:{connector.id}:{ref.artifact_kind}:{ref.external_id}", mode="unknown" if
  policy.state == "unknown" else policy.mode, allow_users=..., allow_groups=..., deny_users=...,
  deny_groups=..., verified_at=observed_at, expires_at=expires_at)`.
  - Unknown is `mode="unknown"`, which `EvidenceAccess` denies to every reader (`access.py:460`).
  - `expires_at` is always set, because a provider policy without a deadline is unreadable
    (`access.py:476-480`).
  - There is one policy per artifact, so refreshing one artifact's verification never extends another's.
- `capture_records` builds
  `k.Artifact(workspace_id, source_id, connector_id=connector.id, provider_instance=connector.instance_url,
  kind=ref.artifact_kind, external_id=fetch.external_id, canonical_uri=fetch.canonical_uri, policy_id=<policy id>)`
  and `k.ArtifactRevision(artifact_id, provider_revision=fetch.provider_revision,
  content_hash=hashlib.sha256(fetch.data).hexdigest(), raw_uri=raw_uri, source_updated_at=...,
  source_timestamp_original=..., source_timezone=..., source_precision=..., observed_at=observed_at,
  lifecycle="active", metadata_json=canonical_json({"content_type": ..., "parser": <spelling or None>}))`.

Both return fresh records. Reusing a stored revision or policy with the same id is the runtime's job
(S3). A `RawFetch` whose `ref` differs from the `PolicyObservation`'s refuses: `Policy and fetch name
different artifacts`.

### 8.10 Coverage

`EmissionCoverage` counts:

- `nodes`, `edges` and `passages`;
- `units` by kind, `aliases` by status and `hints` by predicate;
- `failures`, keyed `f"{family}|{parser spelling or '-'}|{dialect or '-'}"` and summing `count`;
- `unclassified`.

`to_json()` returns sorted, canonical-JSON-ready data. Failures are never dropped, and a batch with only
failures is valid.

## 9. The reverse-view hint (brief decision 6)

Take a connector that observes the reverse of a predicate it does not own, for example "fixed by" on a
ticket, where `RESOLVES` belongs to the change connector. It emits
`ReverseViewHint(predicate, subject, object, support)` with the endpoints in the canonical direction and,
when it can back the link with a rule, an `AliasEmission` for the identity it read (the specification's
section 4.4). The binder:

1. requires the predicate to be registered and in `descriptor.predicates` (the design's "owner or view");
2. refuses a hint for a predicate the connector owns (section 8.5);
3. checks the endpoint kinds in the canonical direction through the registry's rule;
4. verifies the support spans against the bytes (section 8.4), so the hint is honest;
5. writes no `Assertion`, version or support, and counts `coverage.hints[predicate] += 1`.

A hint is coverage evidence that the owner's fact is expected. S4's kit can assert "no reverse-direction
edge", and the linker (Task 12) can later reconcile expected facts against stored ones. No record type is
added for it.

## 10. Task split

Two workers, in order. Each owns its files exclusively.

| # | Task | Depends on | Exclusive files | Result |
| --- | --- | --- | --- | --- |
| S2a | Contract, keys, classification | S1a merged | NEW `src/hippo/connectors/__init__.py`, `base.py`, `keys.py`, `classify.py`; NEW `tests/unit/test_connector_contract.py`, `test_connector_keys.py`, `test_connector_classify.py` | sections 4.1-4.3, 4.6, 5, 6 |
| S2b | Rendering and emission | S2a and S1b merged | NEW `src/hippo/connectors/render.py`, `emit.py`; NEW `tests/unit/test_connector_render.py`, `test_connector_emit.py` | sections 4.4-4.5, 7, 8, 9 |

### Task S2a: contract, keys, classification

**Spec.**

- *Purpose:* the typed port and its pure helpers.
- *Inputs:* the registry, descriptors, sampled bytes, node references.
- *Outputs:* validated records, canonical keys, classifications.
- *Errors:* `ContractError`, `RegistrationRequired` and `BindRefused` (`BindRefused` is defined in
  `emit.py` by S2b; in S2a, `keys.py` raises a `KeyPartsRefused(ContractError)` that S2b re-parents onto
  `BindRefused` without renaming it).
- *Invariants:* no store, model, network or clock; `KnowledgeObject(` appears only in `keys.py`.

**Files.** Create the seven files above. Modify nothing.

**Step 1: RED.** Write the three test files with these tests, run them, and save
`/tmp/hippo-s2a-red.log`. Every test that needs an extension kind registers it through S1's
`extension_scope()` and freezes the scoped registry.

`tests/unit/test_connector_contract.py`:

- `test_every_contract_is_frozen_strict_and_forbids_extra_fields`: parametrized over every `Contract`
  subclass in `base.py`.
- `test_sync_connector_and_connector_protocols_are_runtime_checkable`
- `test_capabilities_declare_emit_or_coordinator_lane_derivation`
- `test_base_reexports_the_registry_definition_classes`
- `test_descriptor_refuses_duplicates_and_missing_families_artifact_or_locator_kinds`
- `test_descriptor_config_model_must_forbid_extra_fields`
- `test_descriptor_validate_against_names_every_unregistered_type_in_a_skeleton`
- `test_descriptor_predicate_it_does_not_own_is_accepted_as_a_view`
- `test_descriptor_configuration_is_the_registry_connector_configuration_without_a_fingerprint`
- `test_parser_version_spelling_round_trips_and_refuses_free_text`
- `test_raw_fetch_refuses_a_different_external_id_and_a_credentialed_uri`
- `test_raw_fetch_source_time_requires_its_original_spelling`
- `test_unknown_policy_observation_carries_no_principals`
- `test_known_restricted_policy_without_an_allowed_principal_is_refused`
- `test_change_page_cannot_mix_partitions_and_keeps_change_order`
- `test_type_mapping_to_an_unregistered_kind_raises_registration_required`
- `test_type_mapping_attribute_must_be_declared_by_the_kind`
- `test_revision_input_refuses_bytes_that_differ_from_the_content_hash`
- `test_revision_input_refuses_an_unfrozen_registry`
- `test_node_emission_cannot_carry_an_id_or_an_evidence_class`
- `test_edge_emission_weight_rule_metadata_and_window_rules`
- `test_parse_failure_reason_is_a_code_not_a_message`
- `test_emission_batch_refuses_duplicate_and_dangling_keys`
- `test_family_and_clock_are_importable_from_base`
- `test_knowledge_package_never_imports_connectors`: a regex over `src/hippo/knowledge/**/*.py`, in the
  style of `tests/unit/test_layering.py:27-32`.
- `test_connectors_modules_import_first_in_a_fresh_interpreter`: `hippo.connectors.base`, `.keys` and
  `.classify`, each in a fresh `sys.executable -c` process (the `test_import_order.py:31-39` pattern).

`tests/unit/test_connector_keys.py`:

- `test_check_key_parts_requires_exactly_the_non_instance_template_parts`
- `test_instance_parts_are_filled_from_the_connector_instance_and_refused_in_a_node_ref`
- `test_extension_kind_key_follows_its_template_order`
- `test_plain_kinds_refuse_sql_parts_and_control_characters`
- `test_readable_key_uses_the_kind_prefix_and_is_never_hashed`
- `test_service_system_and_domain_keys_equal_service_key`
- `test_repository_and_review_keys_equal_their_identity_helpers`
- `test_endpoint_and_api_keys_equal_endpoint_key_and_its_prefix`
- `test_symbol_key_equals_symbol_key`
- `test_database_kind_keys_equal_database_object_key_and_its_prefixes`
- `test_file_key_matches_code_binding_file_object`
- `test_resource_key_matches_code_binding_data_object`
- `test_commit_key_matches_the_code_history_commit_object`
- `test_instance_must_be_a_normalized_ascii_provider_url`
- `test_object_id_equals_knowledge_object_identity`
- `test_keys_is_the_only_knowledge_object_constructor_in_connectors`: an `ast` walk over
  `src/hippo/connectors/**/*.py` for `KnowledgeObject(` calls outside `keys.py`.

`tests/unit/test_connector_classify.py`:

- `test_declaration_wins_over_content_and_name`
- `test_declared_tabular_shape_falls_through_when_the_bytes_are_not_tabular`
- `test_sql_ddl_content_wins_over_the_code_name_in_a_declared_dialect`
- `test_prose_that_parses_as_select_is_not_database_content`
- `test_sqlglot_command_fallback_is_not_a_successful_parse`
- `test_openapi_and_asyncapi_headers_classify_as_service_api`
- `test_backstage_catalog_and_kubernetes_manifests_classify_as_service`
- `test_heading_signatures_select_adr_prd_runbook_and_postmortem`
- `test_tabular_shape_without_a_declared_kind_is_unclassified_with_a_warning`
- `test_name_rules_call_readers_lang_of_code_and_prose_names`
- `test_binary_bytes_are_unclassified_and_counted`
- `test_unmapped_provider_type_is_custom_unclassified_and_counted`
- `test_every_decision_names_its_rule_and_detector`
- `test_classify_is_pure_under_reordering_clock_and_forbidden_io`
- `test_classification_records_the_registry_fingerprint_and_the_classifier_spec`
- `test_unregistered_mapped_kind_returns_no_classification`

Run: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_contract.py tests/unit/test_connector_keys.py tests/unit/test_connector_classify.py -q -o addopts='' -W error > /tmp/hippo-s2a-red.log 2>&1; echo EXIT $?`.
Expected: nonzero, with every test failing on `ModuleNotFoundError: No module named 'hippo.connectors'`.

**Step 2: GREEN.** Implement sections 4.1-4.3, 4.6, 5 and 6. Run the same command to
`/tmp/hippo-s2a-green.log`. Expected: `EXIT 0`, all passed.

**Step 3: regression.** `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_layering.py tests/unit/test_import_order.py tests/unit/test_ingest_readers.py tests/unit/test_knowledge_identity.py tests/unit/test_knowledge_contracts.py -q -o addopts='' -W error > /tmp/hippo-s2a-regress.log 2>&1; echo EXIT $?`.
Expected: `EXIT 0`, with the counts unchanged from the S1a merge.

**Step 4: lint.** `.venv/bin/ruff check src/hippo/connectors tests/unit/test_connector_contract.py tests/unit/test_connector_keys.py tests/unit/test_connector_classify.py && .venv/bin/ruff format --check src/hippo/connectors tests/unit/test_connector_contract.py tests/unit/test_connector_keys.py tests/unit/test_connector_classify.py`.

**Step 5: commit** in worktree `s2a`, staging only the seven files:
`Add the connector contract, canonical keys and classification (CDK S2a)`.

### Task S2b: rendering and emission

**Spec.**

- *Purpose:* the batch-to-records binder and the public checks S4's kit calls.
- *Inputs:* `BindContext`, `RevisionInput`, `EmissionBatch`.
- *Outputs:* `BoundBatch`.
- *Errors:* `BindRefused`, with section 8.5's messages.
- *Invariants:* pure and deterministic; every span verified; every evidence class from the table; no
  `KnowledgeObject(` outside `keys.py`.

**Files.** Create the four files above. In `keys.py`, change only the base class of `KeyPartsRefused` to
`BindRefused` (the one S2a file S2b may edit). A defect found in any other S2a file goes to the
orchestrator, not into a patch here.

**Step 1: RED.** Save `/tmp/hippo-s2b-red.log`.

`tests/unit/test_connector_render.py`:

- `test_label_template_renders_from_declared_attributes`
- `test_each_fact_template_renders_exactly_one_unit`
- `test_fact_templates_format_only_consumed_attributes_label_and_key`
- `test_forty_column_nodes_render_forty_units_and_none_joins_two_outputs`
- `test_edge_statement_reads_subject_kind_label_verb_object_kind_label`
- `test_edge_statement_appends_the_source_statement_after_a_colon`
- `test_rule_edge_statement_appends_rule_and_evidence_in_parentheses`
- `test_heading_prefix_is_the_innermost_heading_cut_to_twelve_tokens_with_its_separator`
- `test_symbol_prefix_ends_with_the_separator`
- `test_rendered_units_have_no_prefix_and_embed_text_equals_text`
- `test_embed_text_is_prefix_plus_text_and_both_hashes_are_sha256`
- `test_identical_text_under_two_headings_shares_content_hash_not_embed_hash`
- `test_embed_hash_is_the_embedding_cache_input_hash`
- `test_token_count_is_the_character_count_the_chunker_budgets_with`
- `test_a_template_with_a_none_consumed_attribute_is_skipped_and_counted`

`tests/unit/test_connector_emit.py`:

- `test_every_spec_section_3_field_lands_in_its_design_section_4_column`: parametrized over `TOTALITY`, a
  list of `(spec_field, build_batch, record_kind, column, expected)` rows transcribed from section 8.2.
- `test_the_totality_table_names_every_spec_section_3_field`: `{row.spec_field for row in TOTALITY}`
  equals `SPEC_FIELDS`, a literal set transcribed from `docs/spec/enterprise-graph-rag-v1.md:212-261`
  (every field of `Node`, `Edge`, `Passage`, `Unit`, `AliasCandidate` and `Provenance`).
- `test_evidence_class_follows_the_derivation_table`: parametrized over section 8.3's eight rows.
- `test_family_source_pairs_outside_the_table_are_refused`
- `test_no_emission_yields_model_inferred`
- `test_a_connector_cannot_set_evidence_class`
- `test_bind_refuses_a_registry_other_than_the_frozen_current_registry`
- `test_non_owner_family_edge_is_refused_with_the_developer_message`
- `test_reverse_direction_edge_is_refused_with_the_developer_message`
- `test_check_direction_and_ownership_is_the_check_the_binder_applies`
- `test_identity_predicate_is_refused_as_an_edge`
- `test_source_outside_sources_allowed_is_refused`
- `test_reverse_view_hint_is_counted_and_writes_no_assertion`
- `test_hint_for_an_owned_predicate_is_told_to_emit_the_edge`
- `test_alias_endpoints_are_ordered_by_canonical_key_then_kind`
- `test_guarded_alias_kind_pairs_stay_candidate`
- `test_alias_version_is_rule_derived_with_rule_name_and_version`
- `test_file_lines_span_text_is_sliced_from_revision_bytes_with_terminators`
- `test_span_text_that_differs_from_the_bytes_is_refused_without_quoting_it`
- `test_field_span_is_resolved_in_the_json_document`
- `test_table_cell_span_is_resolved_in_the_csv_table`
- `test_locator_kind_without_a_verifier_is_refused`
- `test_verify_span_returns_the_text_the_binder_hashes`
- `test_span_and_artifact_share_the_revision_policy`
- `test_node_attrs_are_validated_by_the_kind_attribute_model`
- `test_node_ts_is_an_explicit_valid_from_and_a_missing_ts_is_a_snapshot`
- `test_recorded_from_is_the_generation_instant_and_no_clock_is_read`
- `test_windowed_predicate_without_a_window_is_unknown_and_an_unwindowed_window_is_refused`
- `test_each_support_emission_is_one_derivation_group`
- `test_one_fact_with_two_statements_in_one_batch_is_refused`
- `test_merge_bound_collapses_equal_records_and_keeps_the_first_statement`
- `test_merge_bound_refuses_unequal_records_with_one_id`
- `test_statement_unit_edge_reuses_its_unit_and_a_bare_edge_gets_a_rendered_edge_unit`
- `test_each_rendered_fact_and_rendered_edge_gets_its_own_derived_passage`
- `test_identity_only_endpoint_of_a_foreign_family_binds_its_object_and_a_minimal_observation`
- `test_unit_mentions_are_sorted_unique_object_ids`
- `test_verbatim_passage_text_is_its_span_text`
- `test_derived_passage_is_a_projection_view_over_the_record_span`
- `test_passage_over_the_token_bound_is_refused`
- `test_passage_node_must_be_observed_on_the_passage_span`
- `test_passage_ts_other_than_node_or_source_time_is_refused`
- `test_unit_offsets_are_verified_within_the_unit_span`
- `test_passage_rows_satisfy_the_managed_passage_identity_and_text_rules`: builds rows and checks
  `generation_passage_id` and the text rule of `store/generations.py:1479-1545` without a store.
- `test_parse_failures_are_counted_per_family_parser_and_dialect`
- `test_unregistered_or_undeclared_type_at_bind_is_refused`: the literal emit call that S1's D7 leaves
  to S2 ("the same input cannot reach emit").
- `test_bind_batch_is_deterministic`
- `test_evidence_members_cover_exactly_the_generation_scoped_records`
- `test_capture_records_map_fetch_and_policy_onto_artifact_revision_and_policy`
- `test_unknown_policy_observation_is_stored_as_mode_unknown`
- `test_provider_policy_always_carries_its_expiry`

Run the CK2 CHECK line (section 11) to `/tmp/hippo-s2b-red.log`. Expected: the two new files fail on
`ModuleNotFoundError`, and S2a's three files pass.

**Step 2: GREEN.** Implement sections 4.4, 4.5, 7, 8 and 9. Run the CK2 CHECK line to
`/tmp/hippo-s2b-green.log`. Expected: `EXIT 0`.

**Step 3: regression.** S2a's step 3 command plus `tests/unit/test_managed_input_binding.py` and
`tests/unit/test_code_binding.py`.

**Step 4: lint.** CK7's Ruff command, restricted to `src/hippo/connectors` and the five CK2 test files.

**Step 5: commit** in worktree `s2b`, staging only the four new files and `keys.py`:
`Bind connector emission batches to knowledge records (CDK S2b)`.

## 11. Gate CK2

The CHECK line is confirmed verbatim:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_contract.py tests/unit/test_connector_emit.py tests/unit/test_connector_render.py tests/unit/test_connector_keys.py tests/unit/test_connector_classify.py -q -o addopts='' -W error
```

None of the five files imports `fastapi.testclient`, so no form-(b) warning filter is needed. None
touches a store, so `HIPPO_TEST_STORE` has no effect and CK2 needs no LadybugDB line.

CRITERIA, clause by clause:

| CK2 clause | Tests |
| --- | --- |
| every spec section 3 field lands in the record and column section 4 names | `test_every_spec_section_3_field_lands_in_its_design_section_4_column`, `test_the_totality_table_names_every_spec_section_3_field` |
| identities come only from `connectors/keys.py` | `test_keys_is_the_only_knowledge_object_constructor_in_connectors`, `test_object_id_equals_knowledge_object_identity`, `test_node_emission_cannot_carry_an_id_or_an_evidence_class` |
| `evidence_class` follows the table and a connector cannot set it | `test_evidence_class_follows_the_derivation_table`, `test_family_source_pairs_outside_the_table_are_refused`, `test_no_emission_yields_model_inferred`, `test_a_connector_cannot_set_evidence_class` |
| non-owner and reverse-direction edges are refused with the developer message | `test_non_owner_family_edge_is_refused_with_the_developer_message`, `test_reverse_direction_edge_is_refused_with_the_developer_message`, `test_hint_for_an_owned_predicate_is_told_to_emit_the_edge` |
| every span is verified against the revision bytes at its locator | the four `*_span_*` tests, `test_locator_kind_without_a_verifier_is_refused`, `test_verify_span_returns_the_text_the_binder_hashes`, `test_unit_offsets_are_verified_within_the_unit_span` |
| every rendered unit is one template output | `test_each_fact_template_renders_exactly_one_unit`, `test_forty_column_nodes_render_forty_units_and_none_joins_two_outputs`, `test_statement_unit_edge_reuses_its_unit_and_a_bare_edge_gets_a_rendered_edge_unit` |
| `probe` is a pure function of descriptor, config and sampled bytes | `test_classify_is_pure_under_reordering_clock_and_forbidden_io` covers the kit's pure core; a concrete connector's `probe` is checked by S4's kit against S3's fixture connector |
| order is declaration, content, name, with `custom/unclassified` counted | `test_declaration_wins_over_content_and_name`, `test_sql_ddl_content_wins_over_the_code_name_in_a_declared_dialect`, `test_name_rules_call_readers_lang_of_code_and_prose_names`, `test_binary_bytes_are_unclassified_and_counted`, `test_unmapped_provider_type_is_custom_unclassified_and_counted` |

## 12. Worktrees, merge order and what not to touch

- **Worktrees.** `s2a` (branch `wp/s2a`) and `s2b` (branch `wp/s2b`), each created with the recipe in
  `ai_docs/handoffs/fleet-worker-rules.md` from the HEAD the orchestrator names after the prerequisite
  merges.
- **Merge order.** S1a → S2a; S1b → S2b (S2b needs both S2a and S1b, because `Unit` and the widened
  `AssertionVersion` ship in S1b). S2a may run beside S1b. S3 starts after S2b (section 13 of S3's plan).
- **Do not touch**, in either task:
  - `src/hippo/knowledge/**`, including `registry.py`, `model.py`, `predicates.py`, `identity.py`,
    `input_binding.py`, `code_binding.py` and `derivations.py`;
  - `src/hippo/ingest/**`, including `readers.py` and `provenance.py`;
  - `src/hippo/codegraph/**`, `src/hippo/store/**`, `src/hippo/cli.py`, `src/hippo/remote.py`;
  - `tests/fakes/**`, `tests/unit/test_layering.py`, `tests/unit/test_import_order.py`;
  - `docs/spec/*`, `docs/rag_it_all.md`, every gate ledger and the checkpoint file.

  S2b additionally touches no S2a file except `keys.py`'s one base class.

## 13. Provides to S3, S4, S5 and S6

Exact names from section 4, which the other plans may program against:

- **S3:**
  - `capture_records`, `policy_record`, `bind_batch`, `merge_bound`;
  - `BindContext`, `BoundBatch`, `BoundPassageRow`, `CapturedRevision`, `EmissionCoverage`;
  - `descriptor_configuration` and every `base.py` record.

  `BoundPassageRow.native_row()` has no `embedding`; S3 adds it. `BoundBatch` holds knowledge records
  only, so S3's `knowledge/staged_records.py` can take them without importing `hippo.connectors`.
- **S4** (its R-S2-1 to R-S2-7):
  - R-S2-1: the `base.py` records, including `Family` and `Clock`, and `RegistrationRequired` as the
    registration-request outcome of `probe`;
  - R-S2-2: `keys.check_key_parts` and `keys.canonical_key`;
  - R-S2-3: `render.render_facts` and `render.unit_text`;
  - R-S2-4: `emit.verify_span`, whose result S4 hashes with `identity.text_hash`;
  - R-S2-5: `base.token_count` (ruling R11);
  - R-S2-6: `emit.policy_record`;
  - R-S2-7: `emit.check_direction_and_ownership`.

  S4 also gets `classify.classify` for `hippo connector probe`, and the refusal messages of sections 4.6
  and 8.5 for its negative fixtures.
- **S5 and S6**, item by item:

| Item | Answer |
| --- | --- |
| S5 R-S2-1 (empty `predicates`, `parsers`, `credentials`; `emit` optional) | Satisfied: those tuples may be empty (section 4.6 requires only families, artifact kinds and locator kinds); `SyncConnector` has no `emit`, and `ConnectorCapabilities.derivation="coordinator_lane"` declares it (ruling R1). S5's descriptors, which set every capability false, must set `derivation` too. |
| S5 R-S2-2 (records incl. `ConnectorCapabilities`, `Clock` from `base`) | Satisfied: section 4.1. |
| S5 R-S2-3 (the name-level classifier) | Satisfied: `classify.classify_item`, step 3 of section 5. |
| S5 R-S2-4 (`connectors/__init__.py` imports nothing) | Satisfied: section 1 and `test_connectors_modules_import_first_in_a_fresh_interpreter`. |
| S6 R-S2-1 (re-exported definition classes) | Satisfied: the `base.py` import block of section 4.1 (decision 40). |
| S6 R-S2-2 (records; `RawFetch` timestamp fields; `PolicyObservation` workspace, restricted and unknown) | Satisfied: section 4.1. |
| S6 R-S2-3 (the built-in `service` key builder) | Satisfied: the `service` row of section 6. |
| S6 R-S2-4 (`file_lines` as an emission locator) | Satisfied: section 8.4. |
| S6 R-S2-5 (skip a template with a `None` attribute) | Satisfied: section 7, decision 38. |
| S6 R-S2-6 (a foreign-family endpoint node) | Satisfied: identity-only binding, section 8.7, decision 37 (ruling R6). |

The ported connectors keep their lane binders for byte identity and never call `bind_batch`, and
`descriptor_configuration` never enters their configuration (amended design section 3). S6 also relies on
a derived passage per rendered fact (ruling R6) and on the `field` and `table_cell` verifiers.

## 14. Decisions taken

1. Every contract is a `Contract`. Only `RevisionInput` adds `arbitrary_types_allowed`, for the registry
   handle.
2. Records the design names without fields get the fields of section 4.1. Eleven records the design does
   not name are added: `NodeRef`, `SpanRef`, `SupportEmission`, `SqlPart`, `ReverseViewHint`,
   `PathDeclaration`, `ClassifierSpec`, `KindMapping`, `AttributeMapping`, `ClassificationEvidence` and
   `PartitionClassification` (the last two for "every level names its evidence").
3. `ParserVersion` is structured, because `Code` forbids `/` and `@`.
4. `ConnectorCapabilities.inventory` records whether a scan is an authoritative inventory, which the
   runtime's deletion rule needs (`docs/rag_it_all.md:640`).
5. `probe`'s clock never enters a `Classification`.
6. `PolicyObservation` principals are local principal ids. Unknown carries none; a known restricted
   policy needs at least one allowed principal.
7. One provider `AccessPolicy` per artifact, with `scope_key` `connector:{connector_id}:{artifact_kind}:{external_id}`
   and always an `expires_at`.
8. Keys follow S1's templates for every kind. Instance parts are filled from the Connector row and refused
   in a `NodeRef`; built-in shapes go through the identity helpers; `file`, `commit` and `resource` are
   spelled from their only writers and pinned by parity tests.
9. `KnowledgeObject(` is constructed only in `keys.py`, enforced statically.
10. The readable key is display-only.
11. Classification is first-match in section 5's order. SQL content needs a DDL statement and no `Command`
    fallback; there is no YAML parser; tabular content needs a declared kind; `TypeMapping.classifier`
    stores the procedure, so emit reclassifies identically.
12. `custom/unclassified` is a count and an evidence row, never an object kind.
13. Kind labels are the kind name with spaces for underscores. Templates use `str.format_map` over the
    consumed attributes, `label` and `key` only.
14. The prefix carries its `": "` separator, so `embed_text == prefix + text`.
15. The passage bound uses `base.token_count`, the character count the chunker budgets with (ruling R11).
16. Every observation's and version's `recorded_from` is `generation.created_at`.
17. A node without `ts` observes as `observed_snapshot` with `temporal_basis="observed"`, the code lane's
    convention.
18. Node observations derive their class with `family="deterministic"` from `NodeEmission.source` and
    `metadata_origin`.
19. `rule_version` is `name@version#rule` for edges and `rule@version` for aliases.
20. Span verifiers exist for `file_lines`, `field` and `table_cell` only; every other locator kind refuses.
21. Unit character offsets slice a unit's verified span.
22. The kit makes `rendered_fact` and `rendered_edge` units; `UnitEmission` admits slice kinds only.
23. Every rendered fact and rendered edge gets its own derived passage over its record span (ruling R6).
24. Emitted passages are verbatim; a derived passage is a `projection` view in `input_binding._view`'s
    shape.
25. `Passage.node_ref` lands as the node observation on the passage span, or as `RetrievalView.object_id`.
26. Derivation groups are named by a hash of their sorted span ids.
27. One fact with two statements in one batch refuses. Across revisions, `merge_bound` keeps the first
    statement and every support group.
28. Direction is checked before ownership, so the swap message wins.
29. The guarded alias pairs are service–service, service–repository, and any `SCHEMA` kind with `resource`.
30. A reverse-view hint is verified and counted, never stored.
31. `capture_records` and `policy_record` live in `emit.py`, so the whole contract-to-record mapping is one
    module with one totality test.
32. The binder refuses any registry other than the frozen `current_registry()` (ruling R16).
33. `descriptor_configuration` delegates to S1's `connector_configuration` and
    `declared_template_versions`; S2 spells no configuration shape of its own.
34. `verify_span`, `check_key_parts`, `check_direction_and_ownership`, `policy_record` and `token_count`
    are public, so S4's kit calls the binder's own checks.
35. The `knowledge` → `connectors` layering rule and the fresh-interpreter import test live in S2's own
    test file.
36. S2 is split into S2a and S2b, with S2b after S1b.
37. A node of a kind whose family the connector does not declare binds identity-only: its object and a
    minimal observation; ownership is checked on edges only (ruling R6).
38. A fact template with a `None` consumed attribute is skipped and counted (S6 R-S2-5).
39. `SyncConnector` is the sync half and `Connector` adds `emit`; `ConnectorCapabilities.derivation`
    declares a coordinator-lane connector (ruling R1, S5 R-S2-1).
40. `base.py` re-exports `TypeExtension`, `ObjectKindDefinition`, `PredicateDefinition` and `FactTemplate`
    (S4 R-S2-8, S6 R-S2-1).

## 15. Design deviations

- **DV1, `Passage.ts` has no row column.** The design's section 4 says "`title`, `ts` on the row", but
  `PASSAGE_COLUMNS` (`store/migrations.py:138-146`) has no `ts`, and S1's schema v8 adds none. The value is
  recoverable from the node observation's `valid_from` or the revision's `source_updated_at`, so the binder
  requires `PassageEmission.ts` to equal one of those and refuses anything else. A `ts` column would be a
  schema addition the orchestrator could request instead.
- **DV2, locator kinds without a byte verifier refuse.** The design's section 5 promises the kit hashes
  the slice itself. S2 keeps that promise by refusing `section`, `comment`, `page`, `diff_hunk` and
  registered locator kinds, rather than trusting connector-supplied text. Question Q6 names the hook that
  would admit them.
- **DV3, alias rules 3 to 5 are not kit services in S2.** The design's section 5 calls them kit services
  computed from key templates. They compare objects across sources, which one batch cannot see; no CK2
  clause requires them; Task 12's linker owns cross-source comparison. S2 guarantees only that every stored
  alias names its rule.
- **DV4, the kit makes rendered units.** The design's section 1 says the emission records carry the
  spec's fields, and `Unit.kind` includes the rendered kinds. The design's section 6 says rendered facts
  are "declared, not written by hand at emit time", so S2 treats the rendered kinds as a third kit
  substitution, beside `id` and provenance.
- **DV5, `EmissionBatch.hints`.** The design's section 5 tells the developer to emit a reverse-view hint
  but gives the batch no field for it; S2 adds `hints`.
- **DV6, the passage bound is 1,500 characters, not 1,500 tokens.** Ruling R11 reuses the chunker's
  measure, which is characters, and S2 keeps the chunker's default size, so `PASSAGE_CHAR_BOUND = 1500`.
  The specification's section 3 bound is 1,500 tokens, roughly four times longer. The alternative is
  `PASSAGE_CHAR_BOUND = 6000` (four characters per token). Question Q7 asks the orchestrator to pick.

## 16. Open questions

- **Q1.** `file`, `commit` and `resource` keys are spelled from `code_binding.py:835-840`, `:880-887` and
  `code_history.py:943-944`, and pinned by parity tests. Should a later owner of `identity.py` add public
  helpers, so the spelling goes?
- **Q2.** Resolved by ruling R18: two identities for one table are accepted for v1. `keys.py` builds
  catalog tables with `database_object_key`, the code lane keeps its repository-scoped shape, and a
  connector that sees both joins them with `SAME_OBJECT_AS`.
- **Q3.** Resolved by ruling R16: the binder checks `current_registry()`, and S4's `run_case` registers
  under `extension_scope()` or `use_registry()`.
- **Q4.** A registered evidence source with no row in the fixed derivation table refuses at bind. Should
  S1 refuse to register such a source, moving the refusal to registration time as the design prefers?
- **Q5.** Provider ACL principals must be local principal ids before they reach `PolicyObservation`. The
  design does not say where the mapping from provider principals lives (instance configuration, reviewed
  mapping authorities). S3's fixture connector uses local ids directly.
- **Q6.** Should `LocatorKindDefinition` carry an optional byte verifier, so `section`, `page`, `comment`
  and `diff_hunk` spans can be emitted without weakening DV2?
- **Q7.** The passage bound: 1,500 characters (the chunker's default, the current plan) or 6,000
  characters (about 1,500 tokens, the specification's number)? See DV6.

## Plan verification checklist

### Wiring manifest

| Interface | Implementation | Registration | Plan task |
| --- | --- | --- | --- |
| `base.Connector` protocol | S3 fixture, S5 local and git, S6 exemplar | S4 registry load and entry points | S2a (protocol) |
| `keys.check_key_parts` / `canonical_key` / `knowledge_object` | `keys.py` | called by `emit.bind_batch` and S4's kit | S2a |
| `classify.classify_item` / `classify` | `classify.py` | a connector's `probe`; `TypeMapping.classifier` at emit | S2a |
| `render.*` | `render.py` | called by `emit.bind_batch` and S4's kit | S2b |
| `emit.capture_records` / `policy_record` / `bind_batch` / `merge_bound` / `verify_span` / `check_direction_and_ownership` | `emit.py` | called by S3 `connectors/sync.py` and S4's kit | S2b |

### Regression hotspots

| # | Behavior | Old location | New location | Plan task | Verified |
| --- | --- | --- | --- | --- | --- |
| 1 | Object identity helpers unchanged and reused | `identity.py:148-302` | called from `keys.py` | S2a | parity tests |
| 2 | Code-lane `file`, `resource` and `commit` object ids | `code_binding.py:835-840`, `:880-887`, `code_history.py:943-944` | spelled in `keys.py` | S2a | parity tests |
| 3 | Reader name predicates unchanged | `readers.py:131-196` | called from `classify.py` | S2a | `test_ingest_readers.py` |
| 4 | Knowledge never imports a higher layer | `test_layering.py:27-47` | plus `test_knowledge_package_never_imports_connectors` | S2a | test |
| 5 | Managed passage row rules | `store/generations.py:1479-1545` | `BoundPassageRow` | S2b | `test_passage_rows_satisfy_the_managed_passage_identity_and_text_rules` |
| 6 | Rendered view shape | `input_binding.py:294-345` | `emit.py` rendered passages | S2b | `test_derived_passage_is_a_projection_view_over_the_record_span` |

### Contract matrix

| Endpoint | Old shape | New shape | Breaking? | Plan task |
| --- | --- | --- | --- | --- |
| none: S2 adds a library API and no HTTP, CLI or MCP surface | | | no | |

### External dependencies (runtime)

| Dependency | Type | Endpoint/connection | Auth method | Integration test script | Verified? |
| --- | --- | --- | --- | --- | --- |
| `sqlglot` 30 | in-process library | none | none | `test_connector_classify.py` (the DDL and `Command` fallback tests) | the fallback was run against the root venv while planning |

### Credential source inventory

| Credential | Runtime source | Path/key | Rotation? | Verified in new code |
| --- | --- | --- | --- | --- |
| none: S2 reads no credential; `CredentialRequirement` only names one for S3 | | | | |
