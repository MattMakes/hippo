# The Connector Developer Kit (SDK)

> **Amendments.** `ai_docs/plans/cdk-rulings.md` amends this document: each ruling names the section or
> earlier ruling it changes, later rulings supersede earlier ones, and the ledger
> `ai_docs/gates/rag-it-all/cdk/GATES.md` names the range in force. Where a ruling changed a rule this
> document states (for example R40 over evidence sources, R42 over the passage bound, R43 over
> connector-kind dispatch, R45 over locator verifiers, R76 over the lane re-export), the ruling is the
> rule and the shipped code follows it.

**A v1.0 output of the Enterprise Graph-RAG unified specification. Design of record, 2026-09-15.**

> **Status.** This document is the design the implementation plans are written from. It is owned by
> the orchestrator; implementation plans live in `ai_docs/plans/cdk-*.md`, the gate ledger in
> `ai_docs/gates/rag-it-all/cdk/GATES.md`, and per-slice evidence beside it. Section 12 names the
> gates, section 13 the slices, section 14 the decisions that are the user's to make. Nothing here
> is ordered or sized by duration.

The unified specification ([`enterprise-graph-rag-v1.md`](enterprise-graph-rag-v1.md), §3) defines a
connector as a pure function from a source system's bytes to five kinds of record, and says that a new
source "is a new connector against this contract and a fixture set, and nothing else changes". It does
not say how a developer who has never seen the system writes that connector, how the system learns
what kind of data has arrived when a new source connects, or how a source that fits none of the seven
families gets a type at all. The Connector Developer Kit is that missing piece: the contract as an
installable kit, the runtime that drives any connector through capture, staging and publication, the
classification step that assigns a family and a type mapping when a source connects, the registry that
admits new node and edge types, the render templates, the identity helpers, the contract test kit, and
the scaffold and validation commands.

## 0 Purpose and boundaries

**What the kit is.** Three halves and a descriptor, all typed, all testable without a provider:

| Half | Question it answers | Comes from |
| --- | --- | --- |
| Sync | What changed at the source, and what are its bytes and permissions now? | `docs/rag_it_all.md` §7.1 (`capabilities`, `list_changes`, `fetch`, `fetch_policy`), unchanged in shape |
| Classify | What kind of data is this, and which types will it become? | New: `probe` and the classification result (§2) |
| Emit | Which nodes, edges, passages, units and alias candidates do these bytes justify? | Spec §3, as a pure function (§1, §4) |

The kit also owns what no single connector should: the ontology registry (§3), canonical keys (§5),
rendering (§6), the sync runtime (§7), the test kit (§8), packaging and commands (§9).

**What the kit is not.** It is index-agnostic. A connector emits records into the knowledge model
that already exists in `src/hippo/knowledge/model.py` (`Artifact`, `ArtifactRevision`, `EvidenceSpan`,
`KnowledgeObject`, `ObjectObservation`, `Assertion`, `AssertionVersion`, `AssertionSupport`,
`AccessPolicy`, `Generation`, `SyncState`) plus one new record, `Unit` (§4). Whatever builds indexes
from those records, today the LadybugDB or Neo4j store with igraph PageRank and Ollama embeddings,
in the specification a CSR tier with Qdrant and Cohere Embed v4, is downstream of the kit and outside
this document. The choice between those stacks is the user's (§14); the kit does not wait on it.

**Two standing rules the kit enforces, not merely states.** No connector calls a language model, and
no connector writes a relation label it did not derive from syntax, metadata or a named rule (spec §3,
"What a connector must not do"). The repository's OpenIE prose extraction is not a connector: it is an
extractor that runs downstream of emission on passages that no parser typed. Whether it stays in v1.0
is part of the stack decision in §14; the kit's contract is unaffected either way.

**Relation to the repository's earlier plan.** `docs/rag_it_all.md` and
`docs/rag_it_all_remaining_tasks.md` already name a connector package
(`src/hippo/connectors/{base,local,http,registry,sync,credentials}.py`) across Tasks 6, 9, 10, 11 and
15. The kit claims that layout rather than creating a parallel one. §11 records, item by item, what
the kit absorbs, what it leaves in place and what it renames.

## 1 What a connector is

A connector is a Python class with a descriptor and up to four methods. The descriptor is data; three of
the methods talk to the provider and are read-only; one, `emit`, is pure. Nothing a connector does
touches the store, the index, a model, or the clock.

```python
class ConnectorDescriptor(Contract):
    name: Code  # "jira", "local_files", "acme_incidents"
    version: Text  # the connector's own version; goes into the generation configuration
    families: tuple[Family, ...]  # what it can emit: prose|code|change|db|work|service|incident|custom
    kinds: tuple[Code, ...]  # object kinds it emits; each must be registered (§3)
    predicates: tuple[Code, ...]  # predicates it emits; each must be registered, with it as owner or view
    artifact_kinds: tuple[Code, ...]
    locator_kinds: tuple[Code, ...]
    capabilities: ConnectorCapabilities  # changes feed, deletion feed, acls, history, attachments, webhooks
    config_model: type[BaseModel]  # instance configuration; validated before probe
    credentials: tuple[CredentialRequirement, ...]  # names and scopes; values resolve at runtime (§9)
    parsers: tuple[ParserVersion, ...]  # "tree-sitter/python@0.23", "sqlglot/postgres@26", ...


class Connector(Protocol):
    descriptor: ConnectorDescriptor

    def probe(self, config: BaseModel, clock: Clock) -> Classification: ...  # §2
    def list_changes(self, config: BaseModel, cursor: SyncCursor | None) -> ChangePage: ...
    def fetch(self, config: BaseModel, ref: ExternalRef) -> RawFetch: ...
    def fetch_policy(self, config: BaseModel, ref: ExternalRef) -> PolicyObservation: ...
    def emit(self, revision: RevisionInput, mapping: TypeMapping) -> EmissionBatch: ...  # pure
```

`ChangePage` is the earlier plan's record, unchanged: ordered `Change` records, each with a stable
external identity, the provider revision when the provider has one, and one of `upsert`, `delete`,
`policy_change`; an opaque continuation cursor; a completed-scan marker; provider coverage warnings.
`RawFetch` is bytes plus the provider's metadata for the revision (`provider_revision`,
`source_updated_at` with its original string, timezone and precision, `canonical_uri`, `external_id`,
content type). `PolicyObservation` is the principal lists the provider reports for the artifact, or
`unknown`, which the runtime stores as deny.

`RevisionInput` is what `emit` receives: the bytes, the `Artifact` and `ArtifactRevision` records the
runtime already created for them, the connector's validated config, the `TypeMapping` from
classification, and a registry handle. `EmissionBatch` is what it returns:

```python
class EmissionBatch(Contract):
    nodes: tuple[NodeEmission, ...]
    edges: tuple[EdgeEmission, ...]
    passages: tuple[PassageEmission, ...]
    units: tuple[UnitEmission, ...]
    aliases: tuple[AliasEmission, ...]
    failures: tuple[ParseFailure, ...]  # counted per family and parser; never silently dropped
```

The five emission records carry exactly the fields of spec §3, with two substitutions the kit makes
for the developer: a node's `id` is not written by the connector but derived by the kit from the
node's kind and key parts (§5), and provenance is not a free-form record but a `Locator` of a
registered kind plus the revision the runtime already holds. A connector therefore never invents an
id, never concatenates a key, and never guesses a version.

Every field in spec §3 has a named home in the knowledge model; the table in §4 is that mapping.

## 2 Classification on connect

"Connect data of any type and classify it as a type when it connects" is the requirement the
specification lacks. It is met by one method and one durable record.

`probe(config, clock)` connects read-only, verifies credentials, and returns a `Classification`:

- per partition the provider exposes (a repository, a database and environment, a board, a folder, a
  bucket prefix), the **family** it will be read as, the **`TypeMapping`** from the provider's own
  record types to registered object kinds and predicates, the capabilities actually observed (a
  deletion feed the API version supports, ACLs the token may read), a sample count, and warnings;
- the registry fingerprint (§3) the mapping was computed against.

The runtime stores the classification on the `Connector` row (`classification_json`) and shows it
through `hippo connector probe` and the connector status surface. The `emit` step receives the stored
mapping, never a fresh guess, so the same bytes classify the same way on every sync; the test kit
asserts that `probe` is a pure function of the descriptor, the config and the sampled bytes.

Classification has three levels, and every level names its evidence:

1. **Family.** One of the seven families of the specification, or `custom`. A connector that serves
   one system (Jira, Snowflake) declares its family in the descriptor and `probe` only confirms it. A
   connector that serves a container of unknown content (a folder, a ZIP, an object-store prefix, a
   generic JSON API) classifies each item.
2. **Kinds.** Provider record types map to registered object kinds: a Jira `issuetype` named "Story"
   to `story`, a Trello list to a status category, a `.py` file to `file` and `symbol` through the
   code walkers, a DDL statement to `table` and `column`. An unmapped provider type maps to
   `custom/unclassified` in that family, is counted in coverage, and is never dropped silently.
3. **Attributes.** Provider fields map to the declared attribute schema of the kind (story points
   from the instance's custom field id, mapped once in configuration and recorded in the mapping).

The kit ships the classifier the generic and local connectors use (`connectors/classify.py`). It
decides in this order, and the first decision that applies wins: **declaration** (the instance config
says how to read a path pattern: `migrations/*.sql` is `db`, `docs/adr/*` is prose with the ADR
template), then **content** (a successful SQLGlot parse in a declared dialect; `openapi:` or
`asyncapi:` at the top of a YAML or JSON document; Kubernetes `apiVersion` and `kind`;
`catalog-info.yaml`; the heading signatures of §5.1 of the specification for ADR, PRD, runbook and
post-mortem; NDJSON, CSV or JSON arrays of homogeneous objects as tabular rendered facts under a
declared kind), then **name** (the existing `ingest/readers.py` rules: `lang_of`, `is_code_name`,
`is_plain_prose_name`, and the binary sniff). What none of the three decides is `custom/unclassified`.

A `TypeMapping` may name a kind that no connector has registered yet. Then it is a registration
request, not a mapping: `probe` fails with the exact `TypeExtension` the developer needs to write
(§3), and nothing is stored.

## 3 The ontology registry

Today the vocabulary is closed in five places: `Connector.kind` and `Artifact.kind` are `Literal`s in
`knowledge/model.py`, `EvidenceSpan.locator_kind` is a `Literal` over a discriminated union of locator
models (`LOCATOR_ADAPTER`), `ObjectKind` is a `Literal` mirrored by `predicates.OBJECT_KINDS`, and
`predicates.PREDICATES` is a frozen mapping. A kit that admits new data types cannot be built on
closed vocabularies, so the decision is:

**One registry, validated at load, refused at registration, frozen before the first emit.**
`knowledge/registry.py` holds families, object kinds, artifact kinds, locator kinds, connector kinds,
evidence sources and predicates. The Pydantic validators in `model.py` and `predicates.validate_endpoints`
consult the registry instead of a `Literal` or a frozenset. Every value that is a `Literal` today is
registered as a **built-in** at import time, so every row that validates today validates unchanged
afterwards, and a registration that tries to redefine a built-in is refused.

What a registration carries:

```python
class ObjectKindDefinition(Contract):
    name: Code
    family: Family
    key_template: tuple[Code, ...]  # ordered key parts, e.g. ("tracker", "key") for wi:{tracker}/{key}
    key_prefix: Code  # the readable prefix of spec §4.1: "wi", "tbl", "svc", ...
    attrs_model: type[BaseModel]  # typed attributes; extra="forbid"
    label_template: Text  # display label from attrs
    fact_templates: tuple[FactTemplate, ...]  # one rendered unit each (§6)
    scope_kind: bool = (
        False  # Domain, System, Service, Team, Sprint, Epic, Initiative: eligible for enumeration
    )


class PredicateDefinition(Contract):
    name: Code
    subject_kinds: frozenset[Code]
    object_kinds: frozenset[Code]
    # the connector families that may store the fact (spec §6 table, "across (owner)"); non-empty
    owner_families: frozenset[Family]
    # SAME_OBJECT_AS only: undirected in meaning, any family may emit, exempt from ownership,
    # stored once with the lexically smaller canonical_key as subject, never traversed
    identity: bool = False
    canonical_direction: Literal["subject_to_object"]  # the reverse is a view, never a second edge
    inverse_lookup: bool = True  # the earlier registry's "both"
    family_default: Literal["deterministic", "probabilistic"]
    sources_allowed: frozenset[
        Code
    ]  # parser, metadata, rule, similarity, cooccurrence, access_history, apm, ...
    verb_phrase: Text  # "calls stored procedure", "is owned by", "suspects change"
    windowed: bool = False  # carries valid_from/valid_to
    support_required: bool = True
    traversal_permitted: bool = True


class TypeExtension(Contract):
    families: tuple[Family, ...] = ()
    object_kinds: tuple[ObjectKindDefinition, ...] = ()
    artifact_kinds: tuple[Code, ...] = ()
    locator_kinds: tuple[LocatorKindDefinition, ...] = ()  # name plus a Pydantic locator model
    connector_kinds: tuple[Code, ...] = ()
    evidence_sources: tuple[Code, ...] = ()
    predicates: tuple[PredicateDefinition, ...] = ()
```

The registry API the other slices program against (normative):

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

Registration is refused, with the reason named, when: a name repeats or shadows a built-in; a family
is unknown; a key template is empty or repeats a part; an attribute model allows extra fields; a fact
or label template references an attribute the model does not declare; a predicate names an endpoint
kind that is not registered by the same or an earlier extension; none of a predicate's owner families is one
the registering connector declares; a locator kind has no model or its model is not a `SourceLocator`.
Refusal happens when the registry loads, at process start or in `hippo connector validate`, never when
a connector emits.

Vocabulary is checked at registration, at bind and at store write, never on read (review M1, ruling
R39). Model fields that name a kind, a locator kind or a predicate stay plain codes; the store's
reads accept any code, so a process that has not registered an extension (the MCP stdio server,
`hippo ask`, startup recovery, a `hippo serve` whose connector package failed to import) still reads
every row. `Registry.check_record` is what the binder and the write path call; projection and
citations exclude rows whose vocabulary the current registry lacks and count them in coverage.

The registry is loaded from three places in order: the built-ins, the in-repo connector packages, and
the entry points of installed packages (§9). Its fingerprint is recorded on every managed generation
(`Generation.registry_fingerprint`, schema v8, outside `identity_fields`), so a generation records the
vocabulary it was built with. What a connector depends on goes into the generation's
`configuration_json` instead: its name and version and the versions of the templates and parsers its
descriptor declares, so a changed template is a new manifest and a rebuild rather than a silent
re-reading of old evidence. The two ported connectors (§13 S5) declare no templates, and their
configuration stays byte for byte what the prose and code paths write today. The fingerprint itself
must never enter `configuration_json`: `inputs._manifest_bytes` hashes the configuration and
`Generation.identity_fields` includes the manifest hash, so it would change every generation-scoped id.

Store impact: kinds and predicates are stored as strings on every backend today, so opening the
vocabularies needs no DDL; the new columns and the new record of §4, `Generation.registry_fingerprint`,
and `Connector.classification_json` (§2; `Json`, default `"{}"`, mutable, outside `identity_fields`)
need one journaled schema step (v8) on LadybugDB, Neo4j, the migrations module and the Fake store,
with the frozen v1 to v7 history preserved.

Naming: the existing built-in predicates keep their names (`READS_TABLE`, `OWNED_BY`, `ALIAS_OF`, and
the rest of `predicates.py`). The specification's wider vocabulary (`CALLS_PROC`, `LOCKS`,
`SUSPECT_CHANGE`, `SAME_OBJECT_AS`, `HOSTED_IN`, and the tables of its §5 and §6) is registered by the
connectors that own each predicate as they are written with the kit, each with its owner families and
verb phrase. Nothing is renamed.

Two evidence classes are added to `EvidenceClass` so that rule-derived and similarity-derived edges are
never filed as either syntax or model output: `rule_derived` and `similarity_inferred`. §4 gives the
fixed derivation from the specification's `family` and `source` to an evidence class.

## 4 Mapping the contract onto the knowledge records

| Spec record and field | Knowledge record | Note |
| --- | --- | --- |
| `Node.id` | `KnowledgeObject.id` from `knowledge_object_identity(workspace, kind, canonical_key)` | Key parts come from the kind's `key_template`; the connector supplies parts, the kit builds the key (§5) |
| `Node.type`, `Node.domain` | `KnowledgeObject.kind`; the family is a property of the registered kind | `KnowledgeObject` stays identity-only |
| `Node.label`, `Node.attrs`, `Node.ts` | `ObjectObservation.attributes_json` (label rendered by `label_template`), `valid_from`/`temporal_basis`/`temporal_precision` for `ts`, `evidence_class` | One observation per (object, revision, span); conflicting descriptions from two sources are two observations, as the earlier plan requires |
| `Node.provenance` | `Artifact.canonical_uri`, `Artifact.external_id`, `ArtifactRevision` (`provider_revision`, `source_updated_at` = the specification's `observed_at` with its original spelling, timezone and precision, null when the provider gives none; `ArtifactRevision.observed_at` stays the kit's receipt clock; `metadata_json.parser`), `EvidenceSpan` with a registered locator | `parser` per revision; the descriptor's parser versions and the registry fingerprint per generation (review M7) |
| `Node.acl` | `AccessPolicy` referenced by `Artifact.policy_id` and `EvidenceSpan.policy_id` | Unknown policy is deny (`mode`), never an empty allow list |
| `Edge.src`, `Edge.dst`, `Edge.type` | `Assertion(subject_id, predicate, object_id, scope_key)` | `scope_key` = `source:{source_id}:{partition}`, the form the prose and code paths write today (`prose_generation.py`, `code_generation.py`), because `BuildAuthority` supersedes by scope on publication; two derivations of one fact inside a source are two support groups on one assertion; the same fact stored by two sources is two assertions with shared endpoints, which the specification's ownership rule (§6: stored once, by the owner) prevents for predicates with one owner family; merging two sources' assertions is not the kit's job (cross-source linking is Task 12; it does not de-duplicate assertions); the registry checks endpoint kinds and the owner families |
| `Edge.family`, `Edge.source`, `Edge.rule`, `Edge.weight`, `Edge.statement`, `Edge.unit_ref` | `AssertionVersion` gains `family`, `source`, `rule`, `weight`, `statement`, `unit_id` (schema v8); `confidence` = `weight`; `rule_version` = the connector or template version | `evidence_class` derived by the table below |
| `Edge.valid_from`, `Edge.valid_to` | `AssertionVersion.valid_from`, `valid_to`, `validity_kind` | Already on `TemporalRecord`; `windowed` predicates require them or `unknown` |
| `Edge.provenance` | `AssertionSupport(span_id, derivation_group)` | One group per independently sufficient derivation; a rule that needs two spans puts both in one group |
| `Passage` | managed `Passage` row bound to its `EvidenceSpan` through the existing `BoundPassage` / `PreparedEvidence` path; `title`, `ts` on the row | ≤ 1,500 tokens is a connector-side split the kit asserts |
| `Unit` | **new record** `Unit` (below) | The retrieval representation of a span; several per passage |
| `AliasCandidate` | `Assertion(SAME_OBJECT_AS)`, a built-in identity predicate (`identity=True`) over any two registered kinds, subject = the endpoint with the lexically smaller `canonical_key`, `scope_key` as for edges; `AssertionVersion(evidence_class=rule_derived, rule_version=<rule name and version>, source="rule", rule=<name>, weight=1.0, status="candidate" or "active")` | `ALIAS_OF` is untouched: its subject must be an `alias` object (`predicates.py`), so it cannot carry node-to-node identity. `SAME_OBJECT_AS` has no same-kind rule (`RENAMED_TO` keeps its own). Guarded kind pairs (service–service, service–repository, database object–resource) stay `candidate` until reviewed; acceptance is `status="active"`, `source="reviewed"`, `evidence_class=human_verified`, with the reviewer in the support span's attributes (spec §4.3) |

The `Unit` record:

```python
class Unit(Record):
    generation_id: Text
    passage_id: Text
    span_id: Text  # the original evidence; rendered kinds name the span(s) their attributes came from
    ordinal: Nonnegative
    kind: Literal["sentence", "statement", "row", "diff_line", "rendered_fact", "rendered_edge"]
    # sentence/statement/row/diff_line: a verified slice of the span; rendered kinds: the template output
    text: str
    # sha256 of `text`; identical text anywhere shares it: the boilerplate weight key (spec §7.2)
    content_hash: Text
    prefix: str = ""  # heading of at most twelve tokens, or the enclosing symbol; empty for rendered kinds
    embed_text: str  # prefix + text; what is embedded
    embed_hash: Text  # sha256 of `embed_text`; the vector cache key
    mentions_json: Json  # object ids; the rows of M
    template: Text | None = None  # fact template name and version for rendered kinds
    identity_prefix = "unit"
    identity_fields = ("generation_id", "passage_id", "ordinal", "content_hash")
```

`Unit` joins `GenerationEvidenceMember.record_kind`, is written by the staged writer with the passage
it belongs to, and is collected with its generation. Vectors are keyed by (embedding profile,
`embed_hash`) through the existing embedding cache, so an unchanged unit is never
re-embedded. `mentions_json` is what the linker turns into the mention matrix; the containment matrix
follows from `passage_id`.

Evidence class from the specification's `family` and `source`:

| `family` | `source` | `evidence_class` |
| --- | --- | --- |
| deterministic | parser | `syntax_observed` |
| deterministic | metadata, from a catalog or tracker API | `catalog_observed` |
| deterministic | metadata, from a document, manifest or declaration in a file | `declared` |
| deterministic | rule | `rule_derived` |
| deterministic | access_history, apm | `catalog_observed`, with the source kept on the version |
| deterministic | postmortem, slack (human-asserted text) | `discussion_claim` |
| probabilistic | similarity, cooccurrence | `similarity_inferred` |
| any | reviewed | `human_verified` |

A connector never sets `evidence_class`; the kit derives it. A connector never emits `model_inferred`.

## 5 Identity and aliases

Identity is the kit's, not the connector's. `connectors/keys.py` provides one builder per registered
kind, generated from its `key_template` and `key_prefix`, producing the canonical key array that
`knowledge/identity.py` hashes. The readable prefixes of spec §4.1 (`repo`, `file`, `fn`, `pr`,
`commit`, `tbl`, `col`, `proc`, `view`, `coll`, `wi`, `sprint`, `svc`, `team`, `eng`, `inc`, `alert`,
`doc`, `sec`, `term`) are reserved for the connectors that register those kinds; the built-ins are the thirty kinds of
`knowledge/builtin_types.py` (R13). The earlier plan's scoping rules apply
unchanged: workspace and provider instance are always the first parts; provider-instance hostnames
are ASCII or explicit punycode; database identifiers keep their dialect-aware parts; a Jira key is an
alias, the immutable issue id is the identity.

Artifact, revision and span identities are computed by the runtime from what the connector returns
(`external_id`, `provider_revision`, content hash, canonical locator, exact text hash) with the
existing helpers; a connector cannot produce a span whose text is not a verified slice of the revision
bytes, because the kit hashes the slice itself.

Aliases follow spec §4.2. Rules 1 and 2 (explicit annotation, declared in code) can only be seen by the
connector that reads the annotation, so it emits `AliasEmission(a, b, rule)` with the rule name. Rules
3 to 5 (identifier equality, normalized name equality between compatible kinds, same object across
environments) are kit services computed from registered key templates, so no connector re-implements
them. Synonym proposals and the reconciliation queue are the linker's (`knowledge/linking.py`, Task
12); the kit only guarantees every alias it stores names its rule.

Direction is enforced. The registry records each predicate's owner families and canonical direction; the
kit refuses an edge that a connector of another family emits, or that points the wrong way, and tells
the developer to emit an alias candidate or a reverse-view hint instead. This is what keeps "the work
connector's fixed-by is the reverse view of `RESOLVES`" (spec §4.4) true by construction.

## 6 Rendering

Rendered facts are declared, not written by hand at emit time. A registered kind carries
`fact_templates`; each template names the attributes it consumes and produces one unit per
invocation, so "one fact per unit" (spec §3) holds by construction: a table with forty columns is
forty `column_definition` invocations, forty units. A registered predicate carries a `verb_phrase`;
the kit renders every edge statement as *{subject kind label} {subject label} {verb phrase} {object
kind label} {object label}*, appends *: {source statement}* when the edge came from a unit, and
appends *({rule}: {evidence})* for rule-derived edges. An edge produced by a source statement reuses
that unit's vector (`unit_id` on the version); a rendered edge is a `rendered_edge` unit of its own.

`embed_text` is the prefix plus the text: the innermost heading of at most twelve tokens for prose,
the enclosing symbol for code, nothing for rendered facts. The stored `text` is unchanged, so a
citation quotes the source exactly. `content_hash` is the hash of the stored text, so identical text anywhere shares it (the boilerplate key);
`embed_hash` is the hash of `embed_text`, the vector cache key. Template
names and versions are part of the registry fingerprint; a changed template is a new rule version and
a rebuild, never a silent change under an existing generation.

## 7 The sync runtime

`connectors/sync.py` implements the durable sequence of `docs/rag_it_all.md` §7.2 for any connector
and is the only code that calls one. It generalizes what `ingest/prose_generation.build_plain_source`
and `ingest/code_generation.build_code_source` do today for their two fixed inputs:

1. **Lease.** One lease per connector instance and partition (`SyncState`, `LeasedWork`); on the
   embedded backend every write stays in the owning process.
2. **Cursor and page.** Load the durable cursor; call `list_changes` with bounded timeout and
   response size.
3. **Capture.** For each change: `fetch` into the `RawArtifactStore`; create or reuse `Artifact` and
   `ArtifactRevision` by identity (content hashes exclude volatile fetch metadata); `fetch_policy` into
   an `AccessPolicy` observation, unknown as deny. A `delete` change is recorded as a delete
   observation; a `policy_change` as a policy epoch.
4. **Checkpoint.** Advance the cursor only after the page's raw observations are durable. A replayed
   page is a no-op by identity (invariant I8).
5. **Emit.** For each new revision call `emit` in a worker pool, with the stored `TypeMapping` and a
   frozen registry; the runtime forbids network, model and clock access inside the call (§8). Failures
   are `ParseFailure` rows in the batch and become `Generation.coverage_json` counts per family and
   parser; the failed revision drops out of the new generation and the previous generation stays
    queryable (every member revision is re-emitted each run, nothing is carried forward; R37).
6. **Bind.** Convert the batch to knowledge records (§4): compute identities, verify every span
   against the revision bytes, derive evidence classes, check predicates against the registry, reject
   reverse-direction edges, record the registry fingerprint on the generation and the connector's
   declared versions in its configuration (§3).
7. **Stage.** A generic staged writer, `knowledge/staged_records.py`, writes spans, passages, units,
   observations, assertions, versions, support, alias candidates and, for code, native bindings, under
   the same fencing the prose and code writers use today (`staged_prose.py`, `staged_code.py`), and
   seals.
8. **Publish.** Through `BuildAuthority` and the existing publication transaction: expected parent
   generation, fencing token, suppression epoch; the active generation is never deleted; a lost
   compare rebuilds. `IndexEvent` rows announce the append lane to downstream indexers; the
   compaction lane (linker, synonyms, IDF, drift) belongs to the maintenance worker of Task 9A, which
   consumes those events.
9. **Reconcile.** Deletions are inferred only from a completed authoritative inventory, never from a
   failed page; a periodic complete reconciliation of inventory and policy is scheduled by the same
   runtime.

Local and uploaded sources are connectors too: the local connector's `list_changes` is the existing
`repo_capture.walk_tree` and `accepted_inputs.capture_raw_inputs` walk, and its `fetch` reads the
captured file; the runtime is the same. The runtime never calls the legacy `_clear_passages`,
`delete_passages_for_source` or `delete_code_nodes_for_source`; managed failure keeps the last
published generation queryable (invariant I5).

## 8 The test kit

`hippo.connectors.testing` is what makes "a connector ships when its fixtures pass" (spec §13.1) a
command rather than a sentence.

- **Fixture layout.** `fixtures/<case>/inputs/` (raw bytes per external id), `changes.json` (one or
  more pages), `policies.json`, `config.json`, `expected/` (golden records: nodes, edges, passages,
  units, aliases, failures, as canonical JSON sorted by identity). `run_case(connector, case)` drives
  the runtime against a scratch workspace on the Fake store and diffs the published records against
  the golden files. `hippo connector validate --update-golden` rewrites them and prints the diff for
  review.
- **Contract assertions** (`assert_contract(batch, registry)`), each with a negative fixture in the
  kit's own tests so the assertion is known to fire: no unregistered kind, predicate, locator or
  source; every node has a locator and a policy; unknown policy is deny; every edge has a family, a
  source, a statement and, for deterministic edges, a source with a deterministic row in the §4
  table (review m18); no alias
  without a named rule; no `ts` equal to the injected clock or within the run's window (ingestion
  time never fills a missing timestamp); one fact per unit (every unit is a template output or a
  verified slice, never a join of two); every span's text hash matches the revision bytes at its
  locator; passages within the token bound; identities built by the kit's builders; no
  reverse-direction edge for a predicate the connector's family does not own; parse failures counted,
  never absent.
- **Purity assertions.** `emit` is run twice and must produce identical batches; it runs under a
  guard that raises on socket, `httpx`, Ollama client, subprocess and wall-clock use.
- **Provider recording.** `httpx.MockTransport` helpers record a provider session into
  `fixtures/<case>/http/` and replay it, so `list_changes`, `fetch` and `fetch_policy` are tested
  without credentials; the earlier plan's error classes (authentication, forbidden, not found,
  throttled, transient, malformed) each have a replayable case.
- **Runtime assertions.** Failure injection at every durable boundary of §7: crash after fetch before
  checkpoint, replayed page, failed inventory, policy change mid-page, delete of an artifact with a
  live query session; the last published generation stays queryable throughout.
- **Registry assertions.** The fingerprint test fails when a template or kind changes without a
  version bump.

The kit's CI job runs every connector's fixtures on every change to that connector, the registry or
the runtime.

## 9 Packaging, discovery and commands

- **In-repo connectors** live at `src/hippo/connectors/<name>/` with `connector.py` (descriptor and
  class), `types.py` (the `TypeExtension`), `templates.py`, and `fixtures/`.
- **Third-party connectors** are any installed package exposing the entry point group
  `hippo.connectors` (`name = package.module:Connector`). `Registry.load()` discovers them; an entry
  point that fails to import is listed with its error, not skipped. A discovered kind is not enabled
  until an operator with source-management capability enables it (Task 15's `POST /api/connectors`);
  the configuration carries an allowlist of trusted connector kinds, empty by default for third-party
  entry points.
- **Commands** (`hippo connector ...`, all read-only to providers):
  `new <name> --family <f> [--kinds ...]` scaffolds a package with a descriptor, a `TypeExtension`,
  templates, one fixture case and a passing test;
  `list` shows discovered, enabled and classified connectors;
  `validate <package-or-path>` loads the registry with the connector's extension, runs the contract
  and purity assertions and the connector's fixtures, and prints the registry diff;
  `probe <name> --config <file>` runs classification and prints the family and type mapping per
  partition;
  `sync <instance> [--partition <p>] [--dry-run]` runs one bounded sync into a scratch workspace and
  prints coverage, or into the configured workspace when not a dry run.
- **Surfaces.** Task 15's connector routes and MCP tools expose `probe` and `validate` results and
  the classification summary beside status; the CLI forwards to a running server through `remote.py`
  as the other commands do.
- **Configuration and credentials.** Instance configuration is validated by the descriptor's
  `config_model` before `probe`; `credential_ref` is resolved at runtime by
  `connectors/credentials.py` (environment and file references first) and never stored in
  `config_json`; every URL that reaches a log or an error is redacted of credentials, the lesson of
  review finding m6 in the code-capture work.

## 10 Security and trust

Connectors are read-only to providers by contract and by test. They run in-process in v1.0 with an
explicit trust statement: only connector kinds the operator enabled run, third-party entry points are
allowlisted, and every run is bounded by the runtime (bytes per fetch, items per page, records per
batch, and a budget per `emit` call) rather than by the connector's good behaviour. Out-of-process
isolation is an open decision (§14). Unknown policy is deny; a connector that cannot read permissions
produces artifacts nobody can read until an operator assigns a policy, which is the earlier plan's rule
and stays.

## 11 Reconciliation with the repository's plan

| Earlier plan item | Disposition |
| --- | --- |
| `docs/rag_it_all.md` §7.1 connector interface | Absorbed as the sync half (§1); method names unchanged |
| §7.2 durable sync sequence | Absorbed as the runtime (§7) |
| §5.1 records, §5.2 identity, §5.3 predicate registry and evidence classes | Kept; the registry generalizes §5.3 (§3), two evidence classes added, `Unit` added, `AssertionVersion` widened (§4) |
| Task 5 managed code capture (CC1–CC11) and the prose coordinator | Kept unchanged as the code and prose connectors' emit and native rows; the port (gate CK5) wraps them without changing their output |
| Task 6 step 5 (local file, ZIP and repository input as managed artifacts) | Absorbed by the local connector (CK5); Task 6 steps 1–4 (block extraction, sections, spans) remain the prose connector's emit work, planned when that connector is written |
| Task 9 connector runtime and durable polling | Absorbed by CK3 (`sync.py`, `http.py`, `credentials.py`) |
| Task 9A autonomous maintenance, invalidation and purge | Kept; it consumes the runtime's `IndexEvent`s and owns the compaction lane |
| Tasks 10 and 11 (GitHub, GitLab, Jira, Tuleap, Backstage connectors) | Re-scoped as connectors written with the kit against spec §5.3, §5.5 and §5.6; their fixtures follow §8 |
| Task 12 cross-source linking | Kept; it consumes the kit's alias candidates and implements rules 3–5 and the synonym queue |
| Task 15 product surfaces and connector operations | Kept; gains the kit's commands and probe/validate results (§9) |
| §8 retrieval and the spec's §7–§9 | Not reconciled here; the stack decision (§14) |
| The verification wave in flight before the direction change (CD10 round 2, the PA7-alone run, PA8 round 5, the push) | Parked, not abandoned; recorded in the checkpoint |

## 12 Acceptance

Each gate has a Fake-first CHECK line in the ledger and, where persistence is touched, a LadybugDB
line and root-owned Neo4j parity, following the code-capture ledger's conventions.

- **CK1 Registry.** Kinds, predicates, locators, families, connector kinds and evidence sources are
  registry-driven; every existing suite that touches the model passes unchanged; each refusal reason
  in §3 has a test that triggers it at registration and a test that the same input is unreachable at
  emit; the fingerprint is recorded in a generation's configuration and changes when a template
  changes; schema v8 adds `Unit` and the `AssertionVersion` columns on all three backends with the
  frozen history intact.
- **CK2 Contract and emit.** `EmissionBatch` to knowledge records is total: a table-driven test
  proves every field of spec §3 lands in the record and column §4 names; identities come only from
  the builders; evidence classes follow the table; reverse-direction edges and non-owner predicates are
  refused with the developer-facing message; spans are verified against bytes; units satisfy the
  rendering rules.
- **CK3 Runtime.** A fixture connector syncs through every step of §7 on Fake and LadybugDB with
  failure injection at every durable boundary, publishes through `BuildAuthority`, keeps the last
  generation queryable on every failure, never deletes from a failed inventory, and is idempotent
  under page replay; LadybugDB reopen proven; Neo4j parity recorded.
- **CK4 Kit and commands.** Every contract, purity, runtime and registry assertion has a negative
  fixture that fires it; `hippo connector new` produces a package that `validate` passes; `probe`,
  `list` and `sync --dry-run` work against the fixture connector; the developer guide exists and its
  examples are the fixture connector.
- **CK5 Port.** The local prose path (`add_text`, `add_upload`, ZIP) and the git code path (`add_repo`)
  run through the runtime as connectors, and the published generation's records (spans, passages,
  native rows, receipts, coverage) are byte-identical to the pre-kit path on the existing fixtures,
  measured by the generation checksums the store already computes; the CD1 and CD2 gates still pass
  verbatim.
- **CK6 Exemplar.** A connector for a family the repository does not cover yet (an incidents NDJSON
  export or a work-items CSV export) is written only with the public kit API and the scaffold,
  registers at least one new kind and one new predicate, passes `validate`, syncs a fixture into a
  scratch workspace, and its rendered facts are retrievable through the existing query path with
  citations that resolve to its spans.
- **CK7 Review.** Independent SPEC and QUALITY review with every finding closed or assigned by name.

## 13 Slices

Each slice is sized for one worker's context and hands off through the ledger; the dependency order
is the only order.

| Slice | Owns | Depends on |
| --- | --- | --- |
| S1a registry and model | `knowledge/registry.py`, the validator changes in `knowledge/model.py`, `knowledge/predicates.py`, the two evidence classes, the `Unit` record, `tests/fakes/fake_store.py` record support | — |
| S1b schema v8 | `store/base.py`, `store/migrations.py`, `store/ladybug.py`, `store/memory.py`, `store/generations.py` (Unit and AssertionVersion columns), migration tests | S1a |
| S2 contract, classify, keys, render, emit | `connectors/base.py`, `classify.py`, `keys.py`, `render.py`, `emit.py` | S1a (may start against the normative API in §3 once S1a's registry module is committed) |
| S3 runtime | `connectors/sync.py`, `http.py`, `credentials.py`, `knowledge/staged_records.py`, coordinator and `BuildAuthority` integration, `SyncState` | S1b, S2 |
| S4 kit and commands | `connectors/testing.py`, the scaffold templates, `cli.py` `connector` commands, `remote.py` forwarding, the developer guide `docs/spec/cdk-guide.md` | S2 (assertions), S3 (`sync`) |
| S5 port | `connectors/local/`, `connectors/git/`, the pipeline switch in `ingest/pipeline.py` and `managed_activation.py`, the byte-identity proof | S3 |
| S6 exemplar and surfaces | `connectors/examples/<name>/`, Task 15 route and MCP additions for probe and validate | S4, S5 |
| Review | `ai_docs/reports/<date>-cdk-review.md` | S5, S6 |

Each slice's implementation plan (`ai_docs/plans/cdk-<slice>.md`) names its files, its RED tests, its
CHECK line, and what it must not touch, in the form the code-capture plans use.

## 14 Open decisions for the user

1. **The stack.** The specification names a CSR snapshot tier, Qdrant, Cohere Embed v4 and a
   Sonnet-class utilizer; the repository is local-first on LadybugDB or Neo4j, igraph PageRank and
   Ollama, and its prose path uses OpenIE extraction, which the specification cuts. The kit is
   upstream of this choice. Recommendation: keep the local-first stores and Ollama as the default
   deployment; implement the specification's retrieval (bridging, validity-masked PageRank, MCMI,
   the router and compilers) over the existing `GraphIndex` as the CSR tier; make the embedder and the
   vector index pluggable with Ollama as the default and Cohere and Qdrant as options; keep OpenIE as
   an optional extractor, behind a flag, for prose that no parser types. This keeps the product
   local-first and its HippoRAG core intact while meeting the contract.
2. **Connector isolation.** In-process with bounds and an allowlist (this document) or a subprocess
   per connector from the start.
3. **Third-party trust.** Whether installed entry points may register kinds without an operator's
   allowlist entry.
