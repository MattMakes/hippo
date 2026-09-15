# CDK S1: the ontology registry (S1a) and schema v8 (S1b)

**Status:** proposed implementation contract for gate CK1 of `ai_docs/gates/rag-it-all/cdk/GATES.md`.
Nothing here is implemented and no production route changes. Written against the design of record
`docs/spec/connector-developer-kit.md` and the ledger at `ef143b1` (the design amendments `d1b7bb2`,
`f7b14ee` and `ef143b1` are read in full). Every `file:line` anchor below is at `ef143b1`;
`git diff 0434aa1 ef143b1 -- src tests` is empty, so the anchors also hold at the brief's HEAD.

## 1. Outcome and scope

After S1a and S1b, the five closed vocabularies of design §3 are open: `Connector.kind`,
`Artifact.kind`, `EvidenceSpan.locator_kind` with its locator models, `KnowledgeObject.kind`
(mirrored by `predicates.OBJECT_KINDS`) and `predicates.PREDICATES` are backed by one registry. The
registry also holds families, connector kinds and evidence sources. Every value those vocabularies
accept today is a built-in registration, so every stored row still validates. An extension is
refused at `Registry.register` with a named reason, and the registry has a stable fingerprint. On
top of that, schema v8 adds the `Unit` record, the six `AssertionVersion` columns of design §4,
`Generation.registry_fingerprint` and `Connector.classification_json` on Fake, LadybugDB and Neo4j.
The v1–v7 journal stays byte-identical and every existing record identity is unchanged.

**In scope.** `knowledge/registry.py` and the leaf modules it needs; the validator changes in
`knowledge/model.py`; `knowledge/predicates.py` as a compatibility façade; the built-in
`SAME_OBJECT_AS` identity predicate; `EvidenceClass` gaining `rule_derived` and `similarity_inferred`;
the `Unit` record and its store support; the widened columns; schema v8; the fingerprint; the
`configuration_json` fragment a kit connector writes.

**Out of scope, with the owner named.** The `hippo.connectors` package, `ConnectorDescriptor`,
`EmissionBatch`, key builders, rendering and the evidence-class derivation table (S2). Enforcing
`windowed`, `attrs_model` and the edge statement at emit (S2). The staged writer, writer ordering,
the lease and recording the fingerprint on runtime-built generations (S3). Discovery of in-repo
packages and entry points (design §9's `Registry.load()`; §9 deviation 9) and the version-bump
assertion of design §8 (S4). Building the `configuration_json` fragment,
`connectors/base.connector_configuration(descriptor, registry)` (S2).
The port, which keeps the pre-kit lanes' `configuration_json` and `registry_fingerprint=None` (S5).
Retrieval over units and the stack decision (§14).

## 2. Existing seams

| Seam | Use or required boundary |
| --- | --- |
| `knowledge/model.py:40-45` `Text`, `Json`, `Code`, `Nonnegative`, `Positive`, `VersionOne`; `:90-98` `_utc`, `Instant`, `RelativePath`, `ProviderURL`; `:101-112` `Contract` | Primitives the registry's definition classes must share with the model. Defined inside `model.py` today, which is the import-cycle problem of decision D1. |
| `knowledge/model.py:46-48` `EvidenceClass` | A `Literal` of six classes; gains two (D20). |
| `knowledge/model.py:56-87` `ObjectKind`; `:1490` `assert set(OBJECT_KINDS) == set(ObjectKind.__args__)` | The closed kind vocabulary. `tests/unit/test_code_binding.py:848` reads `k.ObjectKind.__args__`, so the name must stay a `Literal` of the built-in kinds (D8). |
| `knowledge/model.py:168-245` seven locator models, `SourceLocator` union, `LOCATOR_ADAPTER`; `:248-251` `canonical_locator_json` | `tests/unit/test_knowledge_contracts.py:80-108` validates through `TypeAdapter(m.SourceLocator)` and expects `{"kind": "invented"}` to fail, so the union stays the built-in union (D9). |
| `knowledge/model.py:278-286` `Connector` (`kind` Literal `:280`, `identity_fields` `:286`) | `kind` becomes registry-backed (S1a); `classification_json` is added (S1b). |
| `knowledge/model.py:289-312` `Artifact` (`kind` Literal `:294-307`) | `kind` becomes registry-backed. `identity_parts` `:314-317` is unchanged. |
| `knowledge/model.py:357-383` `Generation` (`identity_fields` `:368-375`) | Gains `registry_fingerprint` outside identity (S1b). |
| `knowledge/model.py:392-409` `GenerationEvidenceMember.record_kind` | A `Literal` read reflectively by `store/generations.py:587` and `:1033`; gains `"Unit"` (S1b). |
| `knowledge/model.py:412-445` `EvidenceSpan` (`locator_kind` `:414`, `canonical_locator` `:422-425`, `valid_locator` `:440-445`) | Locator dispatch moves to the registry, byte-identical for built-ins (D9). |
| `knowledge/model.py:448-463` `KnowledgeObject`; `:1327` `QueryRequest.kinds` | Both typed `ObjectKind` today; both become registry-backed. |
| `knowledge/model.py:511-531` `Assertion` (`registered_predicate` `:519-524`, `validate_endpoints` `:526-531`); `:534-545` `checked_assertion` | Predicate and endpoint checks consult the registry; the identity-predicate ordering rule lives here (D12). |
| `knowledge/model.py:548-573` `AssertionVersion` (`identity_fields` `:554-566`, `no_boolean_confidence` `:568-573`) | Gains six columns outside identity (S1b, D18). |
| `knowledge/model.py:794-798` `canonical_ids` | Reused for `Unit.mentions_json`. |
| `knowledge/model.py:1412-1456` `_RECORD_CLASSES`, `RECORD_TYPES`, `RecordPayload` | `Unit` joins (S1b). |
| `knowledge/predicates.py:12-45` `OBJECT_KINDS`; `:48-54` `PredicateDefinition` dataclass (`direction="both"`); `:57-65` `_rule`, `ALL`, `CATALOG`, `SCHEMA`; `:66-105` `PREDICATES` (32 entries); `:108-115` `validate_endpoints` (same-kind rule `:114-115`) | Preserved by name as a façade over the registry (D10). `test_knowledge_contracts.py:191-199` pins `len(PREDICATES) == 32`, non-empty endpoint sets, `support_required` and `direction in {"forward", "both"}`. |
| `knowledge/identity.py:40-45` `canonical_json`; `:63-68` `make_identity`; `:71-72` `text_hash`; `:148-150` `knowledge_object_identity`; `:153-154` `repository_key`; `:163-164` `review_key`; `:183-184` `service_key`; `:215-234` `database_object_key`; `:255-261` `span_identity` (lazy `model` import); `:264-273` `symbol_key`; `:291-302` `endpoint_key` | The canonical key shapes the built-in kinds' `key_template`s record (D13). Unchanged. |
| `knowledge/embedding_cache.py:71-96` `EmbeddingCacheKey`, `cache_key` | Hashes the exact UTF-8 text; `Unit.embed_hash` equals `cache_key(profile, unit.embed_text).input_hash` by construction (D17). Unchanged. |
| `knowledge/lifecycle.py:15-65` `generation_for_inputs` | Gains a `registry_fingerprint` keyword that never enters the manifest (S1b, D21). |
| `knowledge/projection.py:67`, `:656`, `:966`; `knowledge/dense.py:182-198` | The only runtime readers of `PREDICATES`. `:656` subscripts it and would raise `KeyError` on a `SAME_OBJECT_AS` assertion (D10). |
| `knowledge/answer_evidence.py:6`, `:9-26` `_location` | Parses citation locators through `LOCATOR_ADAPTER` and falls through to table-cell attributes, so an extension locator would raise (D9). |
| `knowledge/code_binding.py:719-720`, `:835-839`, `:849-857`, `:880-891`; `:822-832`, `:865-877`; `code_history.py:86`, `:941-959` | Today's only writers of `KnowledgeObject`s and their attribute dicts. Their key arrays fix `repository`, `file`, `symbol`, `commit` and the code lane's data objects (D13). Their freeform attribute dicts are why built-in kinds carry an open attribute model (D6). |
| `store/migrations.py:18` `CURRENT_SCHEMA_VERSION = 7`; `:85-103` `_type`; `:106-109` `KNOWLEDGE_COLUMNS` (derived live from `RECORD_TYPES`); `:111-147` relation, Source, Passage and native descriptors; `:150-199` frozen v5/v6 literals; `:200-211` `MIGRATION_CHECKSUM` (live); `:212-220` `SUPPORTED_CHECKSUMS`; `:223-236` `_descriptor`; `:358-453` `validate_physical_schema`; `:477-514` `NATIVE_INDEXES`, `_v7_indexes` (live); `:517-580` `schema_steps` (v3 `ALTER` precedent `:526-534`); `:583-622` `_data_transform` (v3 backfill precedent `:605-611`); `:625-691` `migrate_store` | The v7 checksum is computed from the live models, so any new field or record changes it and refuses every existing v7 store (§3). |
| `store/knowledge.py:47-107` `REFERENCES`; `:108-121` `LIST_REFERENCES`; `:122-149` `REL_FIELDS`; `:151-157` `MUTABLE_FIELDS`; `:223-248` `SCOPED_FIELDS`, `KIND_SCOPED_FIELDS`; `:417-477` `_knowledge_rows`; `:503-517` `_knowledge_records`; `:540-585` `_write_knowledge`; `:587-640` `_references`; `:669-758` `_validate_knowledge`; `:760` `put_knowledge`; `:781-822` `update_knowledge` | One shared implementation of knowledge reads, writes and reference checks for all three backends, so `Unit` needs map entries, not backend code (S1b). |
| `store/authorization.py:44-59` `configured_provider`, `safer_connector`; `:113-163` `RECORD_EPOCHS`; `:183-197` `record_mutation` | `test_generation_store.py:136-140` requires `set(RECORD_EPOCHS) == set(RECORD_TYPES)`. |
| `store/generations.py:546-562` `_record_revisions`; `:580-592` `_sealed_member`; `:594-706` `_check_knowledge_write` (writable tuple `:640-653`); `:523-545` `_assert_generation_writable`; `:966-1112` `generation_checksums` (`visit` `:980-993`, closure `:1027-1044`, dense `:1081-1086`) | The generation-scoped write guard, exact closure and the checksum a `Unit` must join. `visit` skips `Generation` (`:982`), which is why `registry_fingerprint` is not hashed (the CK5 allowed difference). |
| `store/snapshots.py:262-312` `_collect_generation` (deleted kinds `:299-306`) | Units are collected with their generation (D16). |
| `store/ladybug.py:111-150` `NODE_TABLES`; `store/memory.py:43-563`; `tests/fakes/fake_store.py:66-76` | Legacy tables, Neo4j legacy queries and a generic `_knowledge_data` dict. None needs a change (§9 deviation 3). |
| `ingest/prose_generation.py:194-215` `_configuration`, `:216-228` `_generation`; `ingest/code_generation.py:280-303` `_configuration`; `knowledge/prose_preparation.py:164-176` | The models for the kit connector's `configuration_json` fragment (D25). The pre-kit lanes are not changed. `prose_preparation.py:175` compares a stored `Generation` with one recomputed by `generation_for_inputs`, an S3/S5 hand-off (§10). |

## 3. Why two slices, and why the split differs from design §13

`store/migrations.py:106-109` builds `KNOWLEDGE_COLUMNS` from `RECORD_TYPES` at import time. v7's
`MIGRATION_CHECKSUM` (`:200-211`) hashes it, and v7 is the one version not yet frozen as a literal.
At `ef143b1`, `MIGRATION_CHECKSUM` is
`73720e1eaeed7c148033c269de3a7e3af0d0c167fd87e580622f5c57537787f3`. Adding `Unit` to
`_RECORD_CLASSES`, or any field to `AssertionVersion`, `Generation` or `Connector`, changes that
value. `check_compatibility` (`:255-300`) then refuses every existing v7 store: "Unsupported schema
version or migration checksum; store was not modified".

So the two slices are cut along the persisted shape, not along "registry" and "store":

- **S1a changes no persisted column.** Registry-backed fields remain `str` to `_type` (`:85-103`),
  exactly as the `Literal`s they replace, and `EvidenceClass` stays a `Literal`. A guard test pins
  `CURRENT_SCHEMA_VERSION == 7` and the checksum above.
- **S1b lands every column-affecting model change in one commit with the v8 bump.** That covers
  `Unit`, the `record_kind` value, the six `AssertionVersion` columns, `Generation.registry_fingerprint`
  and `Connector.classification_json`, together with the frozen v7 literal.

This moves the `Unit` record from S1a (design §13) to S1b; see §9 deviation 1.

## 4. Decisions taken

Twenty-six decisions. "Decided by S1 plan" marks where design §3–§4 is silent. Each names the test
that pins it; the tests are specified in §5.5 and §6.4.

- **D1. Module graph (brief decision 1).** Two new leaf modules take code out of `model.py`
  unchanged. `knowledge/contract.py` gets `Text`, `Json`, `Code`, `Nonnegative`, `Positive`,
  `VersionOne`, `_utc`, `Instant`, `RelativePath`, `ProviderURL` and `Contract` (`model.py:40-45`,
  `:90-112`). `knowledge/locators.py` gets a new empty `LocatorBase(Contract)`, the seven locator
  models (`:168-233`, now subclassing it), `SourceLocator` and `LOCATOR_ADAPTER` (`:235-245`).
  `knowledge/registry.py` imports only the standard library, pydantic, `.contract`, `.locators` and
  `.identity`. `knowledge/predicates.py` imports `.registry` and keeps the built-in predicate table.
  `knowledge/builtin_types.py` imports `.registry`, `.locators` and `.predicates`, and holds every
  other built-in value. `Registry` installs built-ins lazily: its first public call imports
  `.builtin_types`. `model.py` imports `.contract`, `.locators`, `.registry` and `.predicates`, and
  re-exports every moved name, so each `hippo.knowledge.model.<name>` resolves as before. *Reason:*
  the definition classes need `Contract`, `Code` and the locator base, and the model's validators
  need the registry; with both in `model.py` that is an import cycle. The lazy install means
  importing `predicates` or `registry` first still sees built-ins. No new module imports
  `hippo.connectors` or `hippo.store`. *Pinned by* `test_registry.py::test_registry_modules_import_nothing_outside_the_knowledge_leaf_modules`
  and `::test_each_knowledge_module_imports_first_in_a_fresh_interpreter`.
- **D2. A default registry, a context-local current registry, freeze as a flag (decided by S1
  plan).**
  - `REGISTRY` is the process default. `current_registry()` reads a `ContextVar` that defaults to
    it, and every model validator and `predicates` reads `current_registry()`.
  - `use_registry(registry)` installs a registry for a `with` body and restores the previous one,
    even when the body raises.
  - `Registry.with_builtins()` builds a fresh registry holding only the built-ins.
  - `extension_scope()` extends the current registry in place for a `with` body, unfrozen, and
    restores its state and frozen flag afterwards, even when the body raises. Under the default
    that registry is `REGISTRY` itself.
  - Nothing in S1 calls `freeze()` in production; S3 and S4 load, then freeze.

  *Reason:* Pydantic validators get no registry handle. S2's R12 registers a throwaway extension
  into the process registry, and S2's binder accepts only `REGISTRY`. S4's R-S1-1 needs a fresh
  registry that leaves the process registry untouched, and a record built under it must validate
  against it. *Pinned by* `test_extension_scope_restores_the_registry_byte_for_byte`,
  `test_use_registry_validates_records_against_the_installed_registry_only` and
  `test_freeze_refuses_registration_and_the_scope_restores_the_frozen_flag`.
- **D3. Definition classes verbatim to design §3, plus marked additions.** The additions:
  - `LocatorKindDefinition.model: type[BaseModel] | None = None`, so "has no model" can be reached
    at `register`.
  - `FactTemplate(name, version, consumes, text)`, with `version: Version` so `"1"` is valid.
  - `Registry.declared_template_versions(kinds)` and `connector_configuration(...)` (D25).
  - A read-only `PredicateDefinition.direction` (`"both"` or `"forward"`).
  - `Registry.register(extension, *, declared_families=None)`.
  - Enumerators: `object_kinds()`, `predicates()`, `artifact_kinds()`, `connector_kinds()`,
    `locator_kinds()`, `evidence_sources()`.
  - `Registry.with_builtins()`, and the module functions `current_registry()`, `use_registry(registry)`
    and `extension_scope()` (D2).
  - `UnregisteredName(KeyError)` and `RegistrationError(ValueError)`, which carries `.reason`.

  *Pinned by* the §5.5 list.
- **D4. Shape in constructors, meaning in `register` (decided by S1 plan).** Constructors check
  types and the `Code` pattern only. Every refusal of design §3 happens in `register`, in the fixed
  order of §5.2, all or nothing, with names compared casefolded within a category. *Reason:* design
  §3 refuses "at registration", and a developer's `types.py` must fail with a named reason, not an
  unrelated `ValidationError`. *Pinned by* `test_register_refuses[...]`,
  `test_a_refused_extension_registers_nothing` and
  `test_a_case_variant_of_a_registered_name_is_refused`.
- **D5. "The families the registering connector declares" (decided by S1 plan).** If
  `declared_families` is `None`, the declared families are `extension.families` plus the families
  of `extension.object_kinds`. S4's `validate` passes the descriptor's `families`. Identity
  predicates skip the check. *Reason:* the normative `register(extension)` has no descriptor.
  *Pinned by* `test_owner_families_are_checked_against_the_extension_or_the_declared_families`.
- **D6. Built-ins take the same path with three exemptions (decided by S1 plan).** Built-ins go
  through `register`'s checks except the three rules that only make sense for an extension:
  1. an attribute model must forbid extra fields (built-in kinds use the open `BuiltinAttributes`);
  2. an owner family must be declared by the registering connector (built-ins have no registering
     connector);
  3. identity predicates are built-in only.

  S1 does not validate `ObjectObservation.attributes_json` against any attribute model; S2 does,
  for kit emissions. *Reason:* `code_binding.py:822-832` and `:865-877` write freeform attribute
  dicts, and CK5 requires their output byte for byte. *Pinned by*
  `test_builtins_are_exempt_from_exactly_three_extension_rules`.
- **D7. What "cannot reach `emit`" means in S1 (decided by S1 plan).** `emit` is S2's, so S1
  proves the next thing down: every name a refused extension carries is refused by the record
  validator that emit must go through (`KnowledgeObject.kind`, `Assertion.predicate`,
  `EvidenceSpan.locator_kind`, `Artifact.kind`, `Connector.kind`, and from S1b
  `AssertionVersion.source`). S2's CK2 tests add the literal emit call. *Pinned by*
  `test_a_refused_extension_leaves_no_name_a_record_accepts[<reason>]`.
- **D8. From `Literal` to registry types.** `RegisteredObjectKind`, `RegisteredArtifactKind`,
  `RegisteredConnectorKind`, `RegisteredLocatorKind` and `RegisteredEvidenceSource` are
  `Annotated[Code, AfterValidator(...)]`. The names `ObjectKind` (the `Literal` of the 30 built-in
  kinds), `OBJECT_KINDS`, `SourceLocator` and `LOCATOR_ADAPTER` stay as built-in aliases, because
  `test_code_binding.py:848` and `test_knowledge_contracts.py:82` read them. `EvidenceClass`,
  `Unit.kind`, `ViewKind` and the status `Literal`s stay `Literal`s: they are not among the five
  closed places design §3 opens. CK1's "every value that is a `Literal` or frozenset member today
  is a built-in registration" is read as those five places plus `OBJECT_KINDS` and `PREDICATES`.
  *Pinned by* `test_builtins_register_every_value_the_closed_vocabularies_held` and
  `test_the_vocabulary_slice_changes_no_persisted_column`.
- **D9. Locators dispatch through the registry.** `canonical_locator_json` and
  `EvidenceSpan.valid_locator` validate by the payload's `kind` through `current_registry().locator`; the
  new `parse_locator_json(value) -> LocatorBase` does the same. `answer_evidence._location` uses it
  and returns `""` for a kind it has no label for. *Reason:* span identity hashes the canonical
  locator (`model.py:437-438`), so built-ins must stay byte-identical, while an extension locator
  must validate and must not crash an answer. *Pinned by*
  `test_builtin_locator_canonical_json_is_byte_identical_to_the_union_adapter`,
  `test_builtin_span_identity_is_unchanged`,
  `test_a_registered_locator_validates_and_canonicalizes_an_evidence_span` and
  `test_answer_location_is_empty_for_an_extension_locator`.
- **D10. `predicates.PREDICATES` becomes a live view.** It is a read-only `Mapping` over every
  registered predicate whose `identity` is false: the 32 built-ins, then extensions.
  `predicate_definition(name)` reads any registered predicate. `validate_endpoints` keeps its
  signature, its messages and the `RENAMED_TO`/`DUPLICATE_OF` same-kind rule. `projection.py:656`
  switches to `predicate_definition`. *Reason:* `test_knowledge_contracts.py:194-198` pins 32 and
  non-empty endpoint sets, and `SAME_OBJECT_AS` declares none. Extension predicates must reach
  `projection.py:966` and `dense.py:197-198` exactly as built-ins do. A `SAME_OBJECT_AS`
  assertion would raise `KeyError` at `projection.py:656` if it were subscripted. *Pinned by*
  `test_predicates_view_holds_the_non_identity_predicates_and_follows_extensions` and
  `test_projection_reads_predicate_definitions_through_the_registry`.
- **D11. Metadata for the 32 existing predicates (brief decision 3; §5.3).** Every one is
  `canonical_direction="subject_to_object"`, `inverse_lookup=True` (all were `"both"`,
  `predicates.py:52`), `family_default="deterministic"` and `support_required=True`.
  `owner_families` come from spec §6's "across (owner)" column by domain. `sources_allowed` is a
  subset of `parser metadata rule reviewed`. `windowed` is true where ownership, dependency or a
  work link can change. Endpoint sets and traversal flags are unchanged. *Pinned by*
  `test_builtin_endpoint_rules_are_the_legacy_table` (digest
  `050f71a4…` at `ef143b1`, see §5.5) and `test_builtin_predicates_carry_owner_families_sources_and_verb_phrases`.
- **D12. `SAME_OBJECT_AS`.** A built-in with `identity=True`, empty endpoint sets meaning "any
  registered kind", all eight built-in families as owners (the check is skipped anyway),
  `traversal_permitted=False`, sources `rule reviewed`, verb phrase `is the same object as`, and no
  same-kind rule. `Assertion.validate_endpoints` requires two distinct objects with the subject
  first when `(canonical_key, kind)` pairs are compared as Python strings (decided by S1 plan: a
  tie in `canonical_key` breaks on `kind`). `ALIAS_OF` is untouched. *Pinned by*
  `test_same_object_as_accepts_any_registered_kind_pair_without_ownership_or_traversal`,
  `test_same_object_as_stores_the_lexically_smaller_canonical_key_as_subject` and
  `test_alias_of_keeps_its_alias_subject_rule`.
- **D13. Built-in object kinds (§5.3; decided by S1 plan where no helper exists).** Families follow
  spec §6's domain rows. Prefixes follow spec §4.1. Each `key_template` names the positions of the
  canonical key that today's identity helper builds (`identity.py`), or that today's only writer
  builds (`code_binding.py`, `code_history.py`). The workspace is never a key part:
  `knowledge_object_identity` adds it (`identity.py:148-150`). *Pinned by*
  `test_builtin_key_templates_match_the_identity_helpers`.
- **D14. The split (§3).** *Pinned by* S1a's
  `test_the_vocabulary_slice_changes_no_persisted_column`, which S1b replaces with
  `test_v7_descriptor_and_indexes_are_frozen_at_their_published_values`.
- **D15. `Unit` validation (S1b; decided by S1 plan).** `content_hash` and `embed_hash` are
  derived when omitted and refused when they disagree, as `EvidenceSpan.check_text_hash` does
  (`model.py:427-435`). Further rules:
  - `embed_text == prefix + text` exactly (design §4). A separator belongs to `prefix`; S2 keeps
    its `": "` there. `text` is not blank.
  - Rendered kinds carry `template` as `name@version` and an empty `prefix`; other kinds carry no
    `template`.
  - `mentions_json` is a sorted, unique JSON array of non-empty strings.

  *Pinned by* the `test_unit_*` tests of §6.4.
- **D16. `Unit` persistence (brief decision 4).**
  - **Storage per backend:** node table `Unit` on LadybugDB; label `Unit` on Neo4j, with a
    `knowledge_unit_id` uniqueness constraint and a `knowledge_unit_generation_id` index;
    `_knowledge_data["Unit"]` on Fake. Columns as §6.3.
  - **References:** `generation_id` to `Generation`, `span_id` to `EvidenceSpan`, `passage_id` to
    the native `Passage`. No relationship table.
  - **Membership:** an exact `GenerationEvidenceMember`.
  - **Write guard:** a write needs the build lease, the generation's own passage, and a span whose
    revision the generation selected.
  - **Checksum:** the generation's `Unit` rows must equal its `Unit` members, and each passage must
    be one of its dense passages. Units enter the `evidence` representation through `visit`.
  - **Reads and collection:** read by `generation_id` only (no `KIND_SCOPED_FIELDS` entry, so no
    new index derivation). Always deleted by collection, like native passages.
  - **Access:** hidden from non-internal readers by `_record_visible`'s default
    (`store/knowledge.py:923-940`) until retrieval owns units.

  *Pinned by* `test_unit_write_requires_a_build_lease_and_its_generations_passage`,
  `test_units_are_exact_members_and_enter_the_evidence_checksum`,
  `test_a_unit_row_outside_exact_membership_refuses_the_checksum` and
  `test_collection_removes_units_with_their_generation`.
- **D17. The vector key (brief decision 4).** `Unit.embed_hash` equals
  `embedding_cache.cache_key(profile, unit.embed_text).input_hash` by construction; both are the
  SHA-256 of the exact UTF-8 text (`embedding_cache.py:92-96`). So vectors key on
  `(profile, embed_hash)` with no change to `embedding_cache.py`. `content_hash` is the boilerplate
  weight key only. The brief's wording ("key on `content_hash`") predates design `d1b7bb2`, which
  this plan follows. *Pinned by* `test_unit_embed_hash_is_the_embedding_cache_input_hash`.
- **D18. `AssertionVersion` widening (brief decision 5).** The six columns are typed as §6.1, all
  `None` by default, so existing rows read back unchanged. None enters `identity_fields`, so every
  existing id is stable; no id migration exists. Model rules (decided by S1 plan):
  - `family` and `source` appear together;
  - `source` is registered;
  - `source == "rule"` requires `rule`;
  - `weight`, when set, equals `confidence` (design §4 "`confidence` = `weight`");
  - no kit field appears without `family`.

  The store requires `unit_id`, when set, to name an existing `Unit`. *Pinned by*
  `test_assertion_version_kit_provenance_rules`,
  `test_v8_fields_leave_existing_identities_unchanged` (pinned
  `assertionversion-6467ad40…`) and `test_assertion_version_unit_reference_must_exist`.
- **D19. The evidence checksum ignores unset v8 fields (decided by S1 plan).**
  `generation_checksums` drops an `AssertionVersion`'s six v8 keys when their value is `None`
  before hashing. *Reason:* `visit` hashes `model_dump(mode="json")` (`generations.py:984`), so six
  new null keys would change every sealed generation's `evidence` checksum, and
  `validate_generation_seal` would then refuse it (`:1131-1132`). This follows the precedent of
  `_identity_value`'s null-`known_at` rule (`model.py:115-132`). *Pinned by*
  `test_unset_v8_assertion_fields_leave_the_evidence_checksum_unchanged`, which compares against
  the v7 column projection, and `test_a_v7_generation_keeps_its_published_evidence_checksum`, whose
  literal is captured in S1b commit 1, before the model changes.
- **D20. `EvidenceClass` consumers (brief decision 6).** No code branches on a class value, so
  nothing changes but the `Literal`:
  - The writers are `code_binding.py:810-816`, `:970`, `:1000`, `:1135`, `code_history.py:86`,
    `:960`, `evals/rag_all_temporal.py:514`, `:529` and `ProseExtractionPayload` (`model.py:1063`).
  - Traversal filters on status, recorded interval, complete support and `traversal_permitted`
    (`projection.py:646-657`, `dense.py:193-198`), never on the class.
  - `SupportGroups.satisfied_by` (`model.py:604-605`) ignores it.
  - `status.py` and the access proof (`knowledge/access.py`) never read it.
  - The column is `STRING` in every descriptor (`migrations.py:28`, `:45`).

  *Pinned by* `test_the_two_new_evidence_classes_validate_and_change_no_column`.
- **D21. `Generation.registry_fingerprint` (brief decision 8).** Typed
  `Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None`. It is outside `identity_fields`
  and outside the manifest, and it is not in `MUTABLE_FIELDS`, so it cannot change once written.
  `generation_for_inputs` gains a `registry_fingerprint` keyword that sets it and never enters the
  manifest. The pre-kit lanes keep `None` (CK5's one allowed difference); S3 records the value on
  runtime-built generations. *Pinned by*
  `test_generation_registry_fingerprint_is_a_sha256_outside_identity_and_the_manifest` and
  `test_registry_fingerprint_round_trips_outside_identity_and_cannot_change`.
- **D22. `Connector.classification_json` (brief decision 7).** Typed `Json = "{}"` and required to
  be a JSON object. It is outside `identity_fields` and added to `MUTABLE_FIELDS["Connector"]`. The
  v8 data step backfills `'{}'` into existing rows, following v3's `origin` backfill
  (`migrations.py:605-611`), because a column added on LadybugDB or Neo4j reads back null and the
  field is not optional. *Pinned by*
  `test_connector_classification_is_a_json_object_outside_identity`,
  `test_v8_backfills_connector_classification_on_existing_rows` and
  `test_connector_classification_updates_under_the_same_identity`.
- **D23. Schema v8 (brief decision 7; §6.3).** The v7 descriptor is frozen as a literal whose
  checksum is `73720e1e…`, the value at `ef143b1`, and `V7_INDEXES` becomes a literal
  (`migrations.py:496-498` asks for exactly this before the next version). Per backend:
  - **LadybugDB:** one `CREATE NODE TABLE` for `Unit` and eight `ALTER TABLE ... ADD IF NOT
    EXISTS` statements.
  - **Neo4j:** the `Unit` constraint and generation index; properties need no DDL.
  - **Fake:** no DDL.

  A data step backfills the Connector classification. *Pinned by*
  `test_v7_descriptor_and_indexes_are_frozen_at_their_published_values`,
  `test_v8_schema_steps_are_exact_per_backend` and
  `test_populated_v7_ladybug_reopens_as_v8_without_reidentification`.
- **D24. What the fingerprint hashes (brief decision 8; decided by S1 plan).** SHA-256 of
  `canonical_json` over one document: sections in a fixed set, names sorted within each section,
  set-valued fields sorted, ordered fields (`key_template`, `consumes`) kept in order. Attribute
  and locator models contribute their `model_json_schema(mode="validation")` with schema-level
  `title` and `description` removed (§5.2). *Pinned by*
  `test_fingerprint_is_independent_of_registration_order`,
  `test_fingerprint_ignores_model_titles_and_descriptions_but_not_field_names` and
  `test_a_changed_fact_template_changes_the_fingerprint_and_the_declaring_configuration`.
- **D25. How a kit connector's template and parser versions reach `configuration_json` (brief
  decision 8).**
  - **S1 builds the fragment (S2's R1 and R5).** `Registry.declared_template_versions(kinds)`
    returns `{"<kind>.<template>": version}`, and `connector_configuration(*, name, version,
    templates, parsers)` returns `{"connector": {...}}` with sorted parsers and templates (§5.2). It
    follows `code_generation._configuration`'s one nested, versioned key
    (`code_generation.py:283-302`) and never holds the fingerprint.
  - **S2's `descriptor_configuration` calls both** with the descriptor's kinds and parsers
    (`cdk-s2-contract.md` §14, decision 33); S2 spells no configuration shape of its own.
  - **S3 merges the fragment** into the generation configuration. S1 edits neither
    `prose_generation.py` nor `code_generation.py` (ruling R2).
  - A changed template version is a new manifest. A changed text without a version bump changes
    only the fingerprint, which S4's registry lock catches.

  *Pinned by* `test_a_changed_fact_template_changes_the_fingerprint_and_the_declaring_configuration`,
  `test_a_template_text_change_without_a_version_bump_changes_only_the_fingerprint` and
  `test_connector_configuration_is_canonical_and_reads_declared_template_versions`.
- **D26. The CK1 CHECK line.** It names `tests/unit/test_knowledge_model.py`, which does not
  exist. §8 proposes the replacement, a LadybugDB line and the CK7 widening.

## 5. S1a: the registry and the vocabulary validators

**Goal.** The five closed vocabularies become registry-backed with every stored row still valid,
extensions are refused with named reasons, and the registry has a fingerprint, all without
changing one persisted column.

### 5.1 Module graph

```text
knowledge/identity.py          (unchanged; lazy `model` import at :258 stays)
knowledge/contract.py      NEW  <- identity                      Contract and primitives, moved
knowledge/locators.py      NEW  <- contract, identity            LocatorBase + seven locators, moved
knowledge/registry.py      NEW  <- contract, locators, identity  definitions, Registry, REGISTRY
knowledge/predicates.py         <- registry                      built-in predicate table, façade
knowledge/builtin_types.py NEW  <- registry, locators, predicates  every other built-in value
knowledge/model.py              <- contract, locators, registry, predicates (re-exports moved names)
registry.Registry._ensure_builtins() imports builtin_types at first use, never at module import.
```

No module-level statement in `predicates.py` or `builtin_types.py` may call a `REGISTRY` lookup:
it would re-enter the install. The fresh-interpreter test below catches it.

### 5.2 Contract

**`knowledge/contract.py` (new).** Move verbatim from `model.py`: `Text`, `Json`, `Code`,
`Nonnegative`, `Positive`, `VersionOne` (`:40-45`), `_utc`, `Instant`, `RelativePath`,
`ProviderURL` (`:90-98`) and `Contract` (`:101-112`), with the imports they use.

**`knowledge/locators.py` (new).** Move verbatim `FileLinesLocator` through `DiffHunkLocator`
(`model.py:168-233`), `SourceLocator` and `LOCATOR_ADAPTER` (`:235-245`). Add the base, and make
each of the six direct `Contract` subclasses subclass it (`DiffHunkLocator` already inherits it
through `FileLinesLocator`):

```python
class LocatorBase(Contract):
    """Every registered locator model subclasses this; its `kind` field defaults to its name."""
```

`SourceLocator` stays the discriminated union of the seven built-ins. It is the `SourceLocator` of
`test_knowledge_contracts.py:82`, which must keep refusing `{"kind": "invented"}`. The registry's
"is a `SourceLocator`" test is therefore `issubclass(model, LocatorBase)` (§9 deviation 6).

**`knowledge/registry.py` (new).** The normative classes of design §3 (amended), verbatim, with the
S1 additions marked:

```python
"""One registry for every kind, predicate, locator, family, connector kind and evidence source.

Validated at load, refused at registration, frozen before the first emit. Imports nothing from
`hippo.connectors` or `hippo.store`; built-ins install from `builtin_types` on first use.
"""

from __future__ import annotations

import string
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .contract import Code, Contract, Text
from .identity import canonical_json, text_hash
from .locators import LocatorBase

Family = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
Version = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")]  # "1", "2.0", "v3"
SPEC_FAMILIES = ("prose", "code", "change", "db", "work", "service", "incident")
CUSTOM_FAMILY = "custom"
RESERVED_TEMPLATE_FIELDS = frozenset({"label", "key"})  # decided by S1 plan
FINGERPRINT_VERSION = 1


class RegistrationError(ValueError):
    """A refused extension. `reason` is a code from the refusal table; the message names the input."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class UnregisteredName(KeyError):
    """A lookup of a name nothing registered; a KeyError so `Mapping.__contains__` works."""

    def __str__(self) -> str:
        return str(self.args[0])


class FactTemplate(Contract):  # fields decided by S1 plan
    name: Code
    version: Version  # a leading digit is allowed; Code is not
    consumes: tuple[Code, ...]  # the attributes it reads
    text: Text  # str.format fields drawn from `consumes` and RESERVED_TEMPLATE_FIELDS


class ObjectKindDefinition(Contract):
    name: Code
    family: Family
    key_template: tuple[Code, ...]  # ordered key parts, e.g. ("tracker", "key") for wi:{tracker}/{key}
    key_prefix: Code  # the readable prefix of spec §4.1: "wi", "tbl", "svc", ...
    attrs_model: type[BaseModel]  # typed attributes; extra="forbid" (extensions)
    label_template: Text  # display label from attrs
    fact_templates: tuple[FactTemplate, ...] = ()  # one rendered unit each (§6)
    scope_kind: bool = False  # Domain, System, Service, Team, Sprint, Epic, Initiative


class PredicateDefinition(Contract):
    name: Code
    subject_kinds: frozenset[Code]
    object_kinds: frozenset[Code]
    owner_families: frozenset[Family]  # non-empty
    identity: bool = False  # SAME_OBJECT_AS only
    canonical_direction: Literal["subject_to_object"]
    inverse_lookup: bool = True
    family_default: Literal["deterministic", "probabilistic"]
    sources_allowed: frozenset[Code]
    verb_phrase: Text
    windowed: bool = False
    support_required: bool = True
    traversal_permitted: bool = True

    @property
    def direction(self) -> Literal["both", "forward"]:  # decided by S1 plan (predicates.py:52)
        return "both" if self.inverse_lookup else "forward"


class LocatorKindDefinition(Contract):
    name: Code
    model: type[BaseModel] | None = None  # optional so "has no model" is refused at register


class TypeExtension(Contract):
    families: tuple[Family, ...] = ()
    object_kinds: tuple[ObjectKindDefinition, ...] = ()
    artifact_kinds: tuple[Code, ...] = ()
    locator_kinds: tuple[LocatorKindDefinition, ...] = ()
    connector_kinds: tuple[Code, ...] = ()
    evidence_sources: tuple[Code, ...] = ()
    predicates: tuple[PredicateDefinition, ...] = ()


SECTIONS = (
    "families",
    "evidence_sources",
    "artifact_kinds",
    "connector_kinds",
    "locator_kinds",
    "object_kinds",
    "predicates",
)


@dataclass(frozen=True)
class _State:
    entries: Mapping[str, Mapping[str, object]]  # section -> name -> definition, model or name
    builtin: Mapping[str, frozenset[str]]  # section -> names installed as built-ins
    frozen: bool = False


class Registry:
    def __init__(self, *, builtins: Callable[[], TypeExtension] | None = None) -> None: ...

    # normative (design §3)
    def register(
        self, extension: TypeExtension, *, declared_families: Iterable[str] | None = None
    ) -> None: ...  # `declared_families` decided by S1 plan (D5)
    def freeze(self) -> None: ...
    def fingerprint(self) -> str: ...
    def families(self) -> frozenset[str]: ...
    def object_kind(self, name: str) -> ObjectKindDefinition: ...
    def predicate(self, name: str) -> PredicateDefinition: ...
    def locator(self, kind: str) -> type[LocatorBase]: ...
    def artifact_kind(self, name: str) -> str: ...
    def connector_kind(self, name: str) -> str: ...
    def evidence_source(self, name: str) -> str: ...

    # decided by S1 plan
    @property
    def frozen(self) -> bool: ...
    def object_kinds(self) -> frozenset[str]: ...
    def predicates(self) -> frozenset[str]: ...
    def artifact_kinds(self) -> frozenset[str]: ...
    def connector_kinds(self) -> frozenset[str]: ...
    def locator_kinds(self) -> frozenset[str]: ...
    def evidence_sources(self) -> frozenset[str]: ...
    @classmethod
    def with_builtins(cls) -> Registry: ...  # a fresh, unfrozen registry holding only the built-ins
    def declared_template_versions(self, kinds: Iterable[str]) -> dict[str, str]: ...  # D25


def _builtin_extension() -> TypeExtension:
    from .builtin_types import BUILTIN_EXTENSION

    return BUILTIN_EXTENSION


REGISTRY = Registry(builtins=_builtin_extension)
_CURRENT: ContextVar[Registry] = ContextVar("hippo_registry", default=REGISTRY)


def current_registry() -> Registry: ...  # what every model validator and `predicates` consults


@contextmanager
def use_registry(registry: Registry) -> Iterator[Registry]: ...


@contextmanager
def extension_scope() -> Iterator[Registry]: ...  # extends the current registry in place, then restores it


def connector_configuration(
    *, name: str, version: str, templates: Mapping[str, str], parsers: Iterable[str]
) -> dict: ...  # {"connector": {...}}; never the fingerprint (D25)
```

Behaviour the bodies must have:

- **State.** `_state` is replaced whole under `_lock` and never mutated, so readers take no lock.
  `_ensure_builtins()` installs the built-in extension once, under the lock, through the same
  checker with `builtin=True`. Every public method calls it first; once installed it is one boolean
  check with no lock, because `PREDICATES` lookups run inside per-arrow loops (`projection.py:966`).
- **`register`.** Raises `frozen` if frozen. Otherwise it runs the checker over a copy of the state,
  appending the extension, and swaps the copy in only if every check passes. A refused extension
  registers nothing.
- **`freeze`.** Sets `frozen`; it is idempotent.
- **Lookups.** Match names exactly (casefolding applies to registration clashes only). A miss raises
  `UnregisteredName` with the message `"Unknown <section label>: '<name>'"`. `locator(kind)`
  returns the model class; `artifact_kind`, `connector_kind` and `evidence_source` return the name.
- **`with_builtins()`.** Returns `Registry(builtins=_builtin_extension)` with the install already
  run; it shares no state with `REGISTRY`.
- **`declared_template_versions(kinds)`.** Returns `{f"{kind}.{template.name}": template.version}`
  over the fact templates of the named kinds, sorted by key. An unregistered kind raises
  `UnregisteredName`.
- **`extension_scope()`.** Under the lock, snapshots the current registry's `_state` and frozen
  flag, clears the flag, and yields that registry. On exit, including an exception, it swaps the
  snapshot back whole. Under the default the yielded registry is `REGISTRY` itself, which S2's
  binder requires (`cdk-s2-contract.md` §8.1 step 1). It is for tests and is not safe across
  threads.
- **`connector_configuration`.** Returns `{"connector": {"name": name, "version": version,
  "parsers": sorted(parsers), "templates": dict(sorted(templates.items()))}}`. It never contains
  a fingerprint.
- **`current_registry()` and `use_registry(registry)`.** `current_registry()` is `_CURRENT.get()`.
  `use_registry` sets `_CURRENT` for the body and resets its token afterwards, even when the body
  raises. A thread-pool worker starts in a fresh context and so sees `REGISTRY`, unless the caller
  runs the work in `contextvars.copy_context()` (§10, S3).
- **`extension_scope()`.** Builds a `Registry` whose state is the current registry's state with
  `frozen=False` (built-ins already installed), installs it with `use_registry`, and yields it.
- **`fingerprint`.** `text_hash(canonical_json(document))`, over this document:

```python
def _schema(model: type[BaseModel]) -> object:
    """A model's validation schema without schema-level `title`/`description` (field names stay)."""

    def node(value):
        if isinstance(value, list):
            return [node(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in ("title", "description"):
                continue
            if key in ("properties", "$defs", "patternProperties") and isinstance(item, dict):
                result[key] = {name: node(child) for name, child in item.items()}
            else:
                result[key] = node(item)
        return result

    return node(model.model_json_schema(mode="validation"))


def _document(state: _State) -> dict:
    entries = state.entries

    def kind(definition: ObjectKindDefinition) -> dict:
        return {
            "name": definition.name,
            "family": definition.family,
            "key_template": list(definition.key_template),
            "key_prefix": definition.key_prefix,
            "attrs": _schema(definition.attrs_model),
            "label_template": definition.label_template,
            "fact_templates": sorted(
                (
                    {"name": t.name, "version": t.version, "consumes": list(t.consumes), "text": t.text}
                    for t in definition.fact_templates
                ),
                key=canonical_json,
            ),
            "scope_kind": definition.scope_kind,
        }

    def predicate(definition: PredicateDefinition) -> dict:
        return {
            field: sorted(value) if isinstance(value, frozenset) else value
            for field, value in definition.model_dump().items()
        }

    return {
        "version": FINGERPRINT_VERSION,
        "families": sorted(entries["families"]),
        "evidence_sources": sorted(entries["evidence_sources"]),
        "artifact_kinds": sorted(entries["artifact_kinds"]),
        "connector_kinds": sorted(entries["connector_kinds"]),
        "locator_kinds": [
            [name, _schema(entries["locator_kinds"][name])] for name in sorted(entries["locator_kinds"])
        ],
        "object_kinds": [kind(entries["object_kinds"][name]) for name in sorted(entries["object_kinds"])],
        "predicates": [predicate(entries["predicates"][name]) for name in sorted(entries["predicates"])],
    }
```

**The refusal table.** The checker takes the extension section by section in `SECTIONS` order,
item by item in the extension's order, and runs each item's rules in the order listed; the first
failing rule raises. `declared` is `set(declared_families)` when given, otherwise
`set(extension.families) | {kind.family for kind in extension.object_kinds}` (D5). Built-ins skip
the rules marked ✱ (D6). Section labels in messages: `family`, `evidence source`, `artifact kind`,
`connector kind`, `locator kind`, `object kind`, `predicate`.

| # | `reason` | Refused when | Message (exact) | Design §3 clause |
| --- | --- | --- | --- | --- |
| 1 | `frozen` | the registry is frozen | `Registry is frozen; register extensions before freeze()` | decided by S1 plan |
| 2 | `shadows_builtin` | a name equals a built-in of its section, casefolded | `<label> '<name>' shadows the built-in '<existing>'` | "shadows a built-in" |
| 3 | `duplicate_name` | a name equals, casefolded, one registered earlier or earlier in this extension | `<label> '<name>' repeats the registered name '<existing>'` | "a name repeats" |
| 4 | `missing_locator_model` | `LocatorKindDefinition.model is None` | `locator kind '<name>' has no model` | "has no model" |
| 5 | `not_a_source_locator` | the model is not a `LocatorBase` subclass, or its `kind` field's default is not `<name>` | `locator kind '<name>' model is not a SourceLocator whose kind defaults to '<name>'` | "not a SourceLocator" |
| 6 | `unknown_family` | an object kind's `family` is not registered (earlier or in this extension) | `object kind '<name>' names unknown family '<family>'` | "a family is unknown" |
| 7 | `empty_key_template` | `key_template == ()` | `object kind '<name>' has an empty key template` | "key template is empty" |
| 8 | `repeated_key_part` | a key part appears twice | `object kind '<name>' repeats key part '<part>'` | "repeats a part" |
| 9 ✱ | `extra_attributes_allowed` | `attrs_model.model_config.get("extra") != "forbid"` | `object kind '<name>' attribute model <Model> must forbid extra fields` | "allows extra fields" |
| 10 | `reserved_attribute` | the attribute model declares `label` or `key` | `object kind '<name>' attribute model declares the reserved template field '<field>'` | decided by S1 plan |
| 11 | `undeclared_template_field` | a `label_template` field is not an attribute; a fact template's `consumes` names a non-attribute; a fact template's `text` names a field outside `consumes` and `label`/`key`; any positional `{}` field | `<label template or fact template '<t>'> of object kind '<name>' references undeclared attribute '<field>'` | "references an attribute the model does not declare" |
| 12 | `repeated_template_attribute` | a fact template's `consumes` repeats an attribute | `fact template '<t>' of object kind '<name>' repeats attribute '<field>'` | decided by S1 plan |
| 13 ✱ | `identity_predicate` | an extension predicate has `identity=True` | `predicate '<name>' is an identity predicate; identity predicates are built-in` | decided by S1 plan (design §3 "SAME_OBJECT_AS only") |
| 14 | `empty_endpoint_kinds` | a non-identity predicate has empty `subject_kinds` or `object_kinds` | `predicate '<name>' declares no <subject or object> kinds` | decided by S1 plan |
| 15 | `unregistered_endpoint_kind` | an endpoint kind is not registered (earlier or in this extension) | `predicate '<name>' names unregistered <subject or object> kind '<kind>'` | "endpoint kind that is not registered" |
| 16 | `empty_owner_families` | `owner_families` is empty | `predicate '<name>' declares no owner families` | design "non-empty" |
| 17 | `unknown_family` | an owner family is not registered | `predicate '<name>' names unknown owner family '<family>'` | "a family is unknown" |
| 18 ✱ | `undeclared_owner_family` | non-identity and `owner_families` shares no family with `declared` | `predicate '<name>': none of its owner families <sorted list> is declared by the registering connector <sorted list>` | "none of a predicate's owner families is one the registering connector declares" |
| 19 | `unregistered_evidence_source` | a `sources_allowed` entry is not registered | `predicate '<name>' allows unregistered evidence source '<source>'` | decided by S1 plan |

Template fields are read with `string.Formatter().parse(text)`; the whole field name is the
attribute (`a.b` and `a[0]` are undeclared). Attributes are `attrs_model.model_fields`.

### 5.3 Built-in registrations

`knowledge/builtin_types.py` builds one `BUILTIN_EXTENSION: TypeExtension` from these values:

- **Families:** `prose`, `code`, `change`, `db`, `work`, `service`, `incident`, `custom`.
- **Evidence sources:** `parser`, `metadata`, `rule`, `similarity`, `cooccurrence`,
  `access_history`, `apm`, `postmortem`, `slack`, `reviewed` (design §3 `sources_allowed` comment
  and §4 derivation table).
- **Artifact kinds:** the twelve of `model.py:295-306`.
- **Connector kinds:** the eight of `model.py:280`.
- **Locator kinds:** the seven locator models, each registered under its `kind` default.
- **Predicates:** `predicates.BUILTIN_PREDICATES`.
- **Object kinds:** the thirty of `predicates.OBJECT_KINDS`, built with this helper and attribute
  model, and checked at import with
  `assert {kind.name for kind in BUILTIN_OBJECT_KINDS} == OBJECT_KINDS`.

```python
class BuiltinAttributes(BaseModel):
    """Open on purpose: the pre-kit lanes write freeform attribute dicts (plan D6)."""

    model_config = ConfigDict(frozen=True, extra="allow")
    name: str | None = None


def _kind(name, family, prefix, *key_template, scope=False) -> ObjectKindDefinition:
    return ObjectKindDefinition(
        name=name,
        family=family,
        key_template=key_template,
        key_prefix=prefix,
        attrs_model=BuiltinAttributes,
        label_template="{name}",
        scope_kind=scope,
    )
```

| Kind | Family | Prefix | `key_template` | Where the shape comes from | `scope_kind` |
| --- | --- | --- | --- | --- | --- |
| `service` | service | `svc` | `catalog_instance, reference` | `identity.service_key` (`identity.py:183-184`) | yes |
| `api` | service | `api` | `service, protocol, api_identity, api_version` | the first four parts of `endpoint_key` (`:302`); decided by S1 plan | no |
| `endpoint` | service | `ep` | `service, protocol, api_identity, api_version, method, path_template` | `identity.endpoint_key` (`:302`) | no |
| `owner` | service | `owner` | `provider_instance, external_id` | decided by S1 plan (no writer, no helper) | no |
| `team` | service | `team` | `name` | spec §4.1 `team:{name}` | yes |
| `person` | service | `eng` | `email` | spec §4.1 `eng:{email}` | no |
| `group` | service | `group` | `provider_instance, external_id` | decided by S1 plan | no |
| `user` | service | `user` | `provider_instance, external_id` | decided by S1 plan | no |
| `system` | service | `sys` | `catalog_instance, reference` | `service_key`'s shape | yes |
| `domain` | service | `domain` | `catalog_instance, reference` | `service_key`'s shape | yes |
| `resource` | service | `res` | `repository, dialect, data_kind, qualname` | its only writer, `code_binding.py:886` | no |
| `repository` | code | `repo` | `provider_instance, repository_id` | `identity.repository_key` (`:153-154`) | no |
| `file` | code | `file` | `repository, path` | its only writer, `code_binding.py:839` | no |
| `symbol` | code | `fn` | `repository, language, path, qualified_name, symbol_kind, signature` | `identity.symbol_key` (`:273`) | no |
| `commit` | change | `commit` | `repository, sha` | its only writer, `code_history.py:944` | no |
| `database` | db | `db` | `instance, environment, catalog` | the leading parts of `database_object_key` (`:234`) | no |
| `schema` | db | `schema` | `instance, environment, catalog, schema` | as above | no |
| `table` | db | `tbl` | `instance, environment, catalog, schema, parts` | `identity.database_object_key` (`:234`) | no |
| `column` | db | `col` | same as `table` | as above | no |
| `view` | db | `view` | same as `table` | as above | no |
| `constraint` | db | `constraint` | same as `table` | as above | no |
| `index` | db | `index` | same as `table` | as above | no |
| `routine` | db | `proc` | same as `table` | as above | no |
| `requirement` | prose | `req` | `provider_instance, external_id` | decided by S1 plan | no |
| `criterion` | work | `criterion` | `provider_instance, external_id` | decided by S1 plan | no |
| `ticket` | work | `wi` | `provider_instance, issue_id` | `docs/rag_it_all.md` §5.2 "Ticket" (immutable id; the key is an alias) | no |
| `review` | change | `pr` | `provider_instance, repository_id, review_id` | `identity.review_key` (`:164`) | no |
| `decision` | prose | `decision` | `provider_instance, external_id` | decided by S1 plan | no |
| `document` | prose | `doc` | `provider_instance, document_id` | spec §4.1 `doc:{system}/{id}` | no |
| `alias` | custom | `alias` | `namespace, alias_key` | `model.Alias` (`model.py:1185-1193`) | no |

The code lane writes `table` and `column` objects with the key `[repository, dialect, data_kind,
qualname]` (`code_binding.py:886`), not the database shape above; §11 open question 2.

**`knowledge/predicates.py` (rewritten).** The names `OBJECT_KINDS`, `ALL`, `CATALOG`, `SCHEMA`,
`PREDICATES`, `PredicateDefinition` and `validate_endpoints` stay. The table gains the D11
metadata; every endpoint set and traversal flag is copied from `predicates.py:68-103` unchanged:

```python
"""Declared assertion endpoints and traversal rules; support is always required.

`both` permits inverse lookup, while the stored and rendered predicate retains its
subject/object orientation. This registry never infers evidence or grants access.
`PREDICATES` reads the ontology registry, so a registered extension predicate appears in it;
an identity predicate declares no endpoint kinds and is read with `predicate_definition`.
"""

from collections.abc import Iterator, Mapping

from .registry import CUSTOM_FAMILY, SPEC_FAMILIES, PredicateDefinition, UnregisteredName, current_registry

OBJECT_KINDS = frozenset(...)  # the thirty names of predicates.py:12-45, unchanged

ALL = " ".join(sorted(OBJECT_KINDS))
CATALOG = "service api system domain resource repository"
SCHEMA = "database schema table column view constraint index routine"
DECLARED = "metadata rule reviewed"
PARSED = "parser metadata rule reviewed"
DISCUSSED = "metadata reviewed"
MENTIONED = "parser metadata reviewed"
EVERY_FAMILY = " ".join((*SPEC_FAMILIES, CUSTOM_FAMILY))


def _rule(name, subjects, objects, owners, sources, verb, *, windowed=False, traversal=True, identity=False):
    return PredicateDefinition(
        name=name,
        subject_kinds=frozenset(subjects.split()),
        object_kinds=frozenset(objects.split()),
        owner_families=frozenset(owners.split()),
        identity=identity,
        canonical_direction="subject_to_object",
        family_default="deterministic",
        sources_allowed=frozenset(sources.split()),
        verb_phrase=verb,
        windowed=windowed,
        traversal_permitted=traversal,
    )


BUILTIN_PREDICATES = (
    _rule(
        "PART_OF",
        CATALOG,
        "system domain service repository",
        "service",
        DECLARED,
        "is part of",
        windowed=True,
    ),
    _rule(
        "OWNED_BY",
        CATALOG + " endpoint",
        "owner group user team person",
        "service code",
        DECLARED,
        "is owned by",
        windowed=True,
    ),
    _rule("PROVIDES_API", "service", "api", "service", DECLARED, "provides", windowed=True),
    _rule("CONSUMES_API", "service", "api", "service", DECLARED, "consumes", windowed=True),
    _rule("DEPENDS_ON", CATALOG, CATALOG, "service", DECLARED, "depends on", windowed=True),
    _rule("EXPOSES_ENDPOINT", "service api", "endpoint", "service code", PARSED, "exposes", windowed=True),
    _rule(
        "IMPLEMENTED_BY",
        "service api endpoint requirement criterion",
        "symbol file repository",
        "code",
        PARSED,
        "is implemented by",
    ),
    _rule("READS_TABLE", "symbol routine", "table view", "code db", PARSED, "reads"),
    _rule("WRITES_TABLE", "symbol routine", "table view", "code db", PARSED, "writes"),
    _rule("READS_COLUMN", "symbol routine", "column", "code db", PARSED, "reads"),
    _rule("WRITES_COLUMN", "symbol routine", "column", "code db", PARSED, "writes"),
    _rule("REFERENCES_OBJECT", "symbol file routine", SCHEMA, "code db", PARSED, "references"),
    _rule("HAS_COLUMN", "table view", "column", "db", PARSED, "has"),
    _rule("HAS_CONSTRAINT", "table column", "constraint", "db", PARSED, "has"),
    _rule("FK_REFERENCES", "constraint", "table", "db", PARSED, "references"),
    _rule("VIEW_READS", "view", "table view column", "db", PARSED, "reads"),
    _rule("DERIVES_FROM", "column view", "column table view", "db", PARSED, "derives from"),
    _rule("RENAMED_TO", ALL, ALL, "code change db", PARSED, "was renamed to"),
    _rule("HAS_CRITERION", "requirement ticket", "criterion", "work prose", DECLARED, "has"),
    _rule("TRACKS", "ticket", "requirement criterion decision", "work", DECLARED, "tracks", windowed=True),
    _rule(
        "BLOCKS",
        "ticket requirement criterion",
        "ticket requirement criterion",
        "work",
        DECLARED,
        "blocks",
        windowed=True,
    ),
    _rule("DUPLICATE_OF", "ticket requirement", "ticket requirement", "work", DECLARED, "duplicates"),
    _rule(
        "MENTIONS",
        "document ticket review decision requirement criterion",
        ALL,
        "prose work change",
        MENTIONED,
        "mentions",
        traversal=False,
    ),
    _rule("ADDRESSES", "review commit", "ticket requirement criterion", "change", DECLARED, "addresses"),
    _rule("CHANGES", "review commit", "file symbol endpoint " + SCHEMA, "change", PARSED, "changes"),
    _rule("MERGED_AS", "review", "commit", "change", DECLARED, "was merged as"),
    _rule(
        "SUPERSEDES",
        "decision requirement criterion document",
        "decision requirement criterion document",
        "prose",
        DISCUSSED,
        "supersedes",
    ),
    _rule("CONTRADICTS", ALL, ALL, "prose", DISCUSSED, "contradicts", traversal=False),
    _rule("SUPPORTS", ALL, ALL, "prose", DISCUSSED, "supports"),
    _rule(
        "DECIDED_IN",
        "decision requirement criterion",
        "ticket review document",
        "prose work change",
        DISCUSSED,
        "was decided in",
    ),
    _rule("ALIAS_OF", "alias", ALL, " ".join(SPEC_FAMILIES), DECLARED, "is an alias of"),
    _rule(
        "BOUND_TO",
        "symbol resource service endpoint " + SCHEMA,
        "symbol resource service endpoint " + SCHEMA,
        "code service db",
        PARSED,
        "is bound to",
    ),
    _rule(
        "SAME_OBJECT_AS",
        "",
        "",
        EVERY_FAMILY,
        "rule reviewed",
        "is the same object as",
        traversal=False,
        identity=True,
    ),
)


class _PredicateView(Mapping[str, PredicateDefinition]):
    """Every registered predicate that declares endpoint kinds: the built-ins, then extensions."""

    def __getitem__(self, name: str) -> PredicateDefinition:
        definition = current_registry().predicate(name)  # UnregisteredName is a KeyError
        if definition.identity:
            raise KeyError(name)
        return definition

    def __iter__(self) -> Iterator[str]:
        registry = current_registry()
        return iter(sorted(name for name in registry.predicates() if not registry.predicate(name).identity))

    def __contains__(self, name: object) -> bool:  # no KeyError path in per-arrow loops
        registry = current_registry()
        return (
            isinstance(name, str) and name in registry.predicates() and not registry.predicate(name).identity
        )

    def __len__(self) -> int:
        return sum(1 for _ in self)


PREDICATES: Mapping[str, PredicateDefinition] = _PredicateView()


def predicate_definition(name: str) -> PredicateDefinition:
    """Any registered predicate, identity predicates included."""
    try:
        return current_registry().predicate(name)
    except UnregisteredName:
        raise ValueError("Unknown assertion predicate") from None


def validate_endpoints(predicate: str, subject_kind: str, object_kind: str) -> None:
    definition = predicate_definition(predicate)
    if definition.identity:
        kinds = current_registry().object_kinds()
        if subject_kind not in kinds or object_kind not in kinds:
            raise ValueError(f"Invalid endpoint kinds for {predicate}")
        return
    if subject_kind not in definition.subject_kinds or object_kind not in definition.object_kinds:
        raise ValueError(f"Invalid endpoint kinds for {predicate}")
    if predicate in {"RENAMED_TO", "DUPLICATE_OF"} and subject_kind != object_kind:
        raise ValueError(f"{predicate} requires matching endpoint kinds")
```

Verb phrases name no endpoint kind, because design §6 renders *{subject kind label} {subject label}
{verb phrase} {object kind label} {object label}*. `RENAMED_TO`'s `ALL` is the thirty built-in kinds
(unchanged), so an extension kind cannot be renamed through it.

### 5.4 File-by-file changes

1. **`src/hippo/knowledge/contract.py` (new)** and **`src/hippo/knowledge/locators.py` (new):**
   the moves of §5.2, then `LocatorBase` as the base of the six direct locator subclasses.
2. **`src/hippo/knowledge/registry.py` (new)** and **`src/hippo/knowledge/builtin_types.py`
   (new):** §5.2 and §5.3.
3. **`src/hippo/knowledge/predicates.py`:** replaced by §5.3's text; `:12-45` is kept verbatim.
4. **`src/hippo/knowledge/model.py`:**
   - `:10-38`: import the moved names from `.contract` and `.locators`; import `current_registry` and
     `UnregisteredName` from `.registry`; replace `from .predicates import OBJECT_KINDS,
     PREDICATES, validate_endpoints` with `OBJECT_KINDS, predicate_definition,
     validate_endpoints`. Delete the moved definitions at `:40-45`, `:90-112` and `:168-245`.
     Import each moved name that `model.py` no longer uses itself (at least `SourceLocator`,
     `LOCATOR_ADAPTER`, `_utc` and the seven locator classes; `ingest/provenance.py:24` imports
     `FileLinesLocator` through `model`) with the redundant alias, for example
     `from .locators import SourceLocator as SourceLocator`. The repository's Ruff treats that form
     as a re-export and skips F401 (checked against a probe file), so do not run
     `ruff check --fix` on `model.py` without it.
   - `:46-48`: `EvidenceClass` appends `"rule_derived", "similarity_inferred"`.
   - `:56-87`: `ObjectKind` stays, with the comment "built-in kinds; fields that accept any
     registered kind use `RegisteredObjectKind`". After it, add:

     ```python
     def _registered(lookup: str, message: str) -> AfterValidator:
         def check(value: str) -> str:
             try:
                 getattr(current_registry(), lookup)(value)
             except UnregisteredName as error:
                 raise ValueError(message) from error
             return value

         return AfterValidator(check)


     RegisteredObjectKind = Annotated[Code, _registered("object_kind", "Unknown object kind")]
     RegisteredArtifactKind = Annotated[Code, _registered("artifact_kind", "Unknown artifact kind")]
     RegisteredConnectorKind = Annotated[Code, _registered("connector_kind", "Unknown connector kind")]
     RegisteredLocatorKind = Annotated[Code, _registered("locator", "Unknown locator kind")]
     RegisteredEvidenceSource = Annotated[Code, _registered("evidence_source", "Unknown evidence source")]
     ```
   - `:248-251`: replace with:

     ```python
     def parse_locator_json(value: str) -> LocatorBase:
         """Validate a locator payload with the model its registered `kind` names."""
         payload = json.loads(normalize_json(value))
         kind = payload.get("kind") if isinstance(payload, dict) else None
         if type(kind) is not str:
             raise ValueError("Locator payload requires a kind")
         try:
             model = current_registry().locator(kind)
         except UnregisteredName as error:
             raise ValueError("Unknown locator kind") from error
         return model.model_validate_json(canonical_json(payload))


     def canonical_locator_json(value: str) -> str:
         """Validate coordinates, normalize paths, and materialize every default."""
         return canonical_json(parse_locator_json(value).model_dump(mode="json"))
     ```
   - `:280`: `kind: RegisteredConnectorKind`. `:294-307`: `kind: RegisteredArtifactKind`. `:414`:
     `locator_kind: RegisteredLocatorKind`. `:450`: `kind: RegisteredObjectKind`. `:1327`:
     `kinds: tuple[RegisteredObjectKind, ...] = ()`.
   - `:440-445`: `valid_locator` compares `parse_locator_json(self.locator_json).kind` with
     `self.locator_kind`; the message is unchanged.
   - `:519-524`: `if value not in current_registry().predicates(): raise ValueError("Unknown assertion predicate")`.
   - `:526-531`: after `validate_endpoints(...)`, add the D12 rule:

     ```python
     if predicate_definition(self.predicate).identity:
         if subject.id == target.id:
             raise ValueError(f"{self.predicate} requires two distinct objects")
         if (subject.canonical_key, subject.kind) > (target.canonical_key, target.kind):
             raise ValueError(f"{self.predicate} stores the lexically smaller canonical key as its subject")
     ```
   - `:1490`: the assertion stays.
5. **`src/hippo/knowledge/projection.py`:** `:67` becomes
   `from .predicates import PREDICATES, predicate_definition`; `:656` becomes
   `if not predicate_definition(assertion.predicate).traversal_permitted:`. `:966` is unchanged.
6. **`src/hippo/knowledge/answer_evidence.py`:** `:6` imports `parse_locator_json`; `:12` calls it.
   `:25` becomes `if locator.kind == "table_cell": return f"Table ..."` (same text), followed by
   `return ""`.

### 5.5 RED tests

Write every test first, save the failing run to `/tmp/hippo-s1a-red.log`, then implement. Shared
fixtures (top of `tests/unit/test_registry.py`; `test_registry_model.py` imports them from there):

```python
@pytest.fixture
def scoped():
    with extension_scope() as registry:
        yield registry


class IncidentAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str
    severity: str


class IncidentEventLocator(LocatorBase):
    kind: Literal["incident_event"] = "incident_event"
    event_id: Text


def incident_extension(**changes) -> TypeExtension:
    kind = ObjectKindDefinition(
        name="incident_fixture",
        family="incident",
        key_template=("tool", "incident_id"),
        key_prefix="incx",
        attrs_model=IncidentAttributes,
        label_template="{title}",
        fact_templates=(
            FactTemplate(
                name="severity", version="1", consumes=("severity",), text="{label} has severity {severity}"
            ),
        ),
    )
    predicate = PredicateDefinition(
        name="AFFECTS_FIXTURE",
        subject_kinds=frozenset({"incident_fixture"}),
        object_kinds=frozenset({"service"}),
        owner_families=frozenset({"incident"}),
        canonical_direction="subject_to_object",
        family_default="deterministic",
        sources_allowed=frozenset({"pager_feed"}),
        verb_phrase="affects",
    )
    return TypeExtension(
        object_kinds=(kind,),
        artifact_kinds=("incident_export",),
        locator_kinds=(LocatorKindDefinition(name="incident_event", model=IncidentEventLocator),),
        connector_kinds=("incident_ndjson",),
        evidence_sources=("pager_feed",),
        predicates=(predicate,),
    ).replace(**changes)
```

**`tests/unit/test_registry.py` (new):**

1. `test_builtins_register_every_value_the_closed_vocabularies_held`: the sets equal `ObjectKind.__args__`, `OBJECT_KINDS`, the twelve artifact kinds, the eight connector kinds, the seven locator `kind` defaults, eight families, ten evidence sources, and 32 plus `SAME_OBJECT_AS` predicates.
2. `test_builtin_endpoint_rules_are_the_legacy_table`: `text_hash(canonical_json({name: [sorted(d.subject_kinds), sorted(d.object_kinds), d.direction, d.support_required, d.traversal_permitted] for name, d in PREDICATES.items()}))` equals `"050f71a4c3ef7af8e0107067d8e601cc08832f4daaea01c97f885f2bf148803e"`, the value at `ef143b1`.
3. `test_builtin_predicates_carry_owner_families_sources_and_verb_phrases`: every built-in has non-empty `owner_families` ⊆ families, `sources_allowed` ⊆ evidence sources, a verb phrase, `canonical_direction == "subject_to_object"`; `MENTIONS` and `CONTRADICTS` are untraversed.
4. `test_builtin_key_templates_match_the_identity_helpers`: the template length equals the helper's array length for `repository` (`repository_key`), `review` (`review_key`), `service` (`service_key`), `endpoint` (`endpoint_key`), `symbol` (`symbol_key`) and `table` (`database_object_key`).
5. `test_builtins_are_exempt_from_exactly_three_extension_rules`: a new extension kind (not a built-in name, so `shadows_builtin` cannot fire first) using `BuiltinAttributes` is refused `extra_attributes_allowed`, and a copy of `SAME_OBJECT_AS` under a new name is refused `identity_predicate`; `Registry.with_builtins()` installs without error.
6. `test_register_refuses[<reason>]`: one case per table row, each asserting `error.reason` and the exact message. Cases change `incident_extension`: `frozen` (call `scoped.freeze()` first), `shadows_builtin` (kind named `File`), `duplicate_name` (register twice), `missing_locator_model`, `not_a_source_locator` (model `IncidentAttributes`), `unknown_family` (kind family `pager`, and predicate owner `pager`), `empty_key_template`, `repeated_key_part`, `extra_attributes_allowed`, `reserved_attribute`, `undeclared_template_field` (label `{name}`, consumes `impact`, text `{impact}`), `repeated_template_attribute`, `identity_predicate`, `empty_endpoint_kinds`, `unregistered_endpoint_kind` (object `pager_duty`), `empty_owner_families`, `undeclared_owner_family` (owner `work`, and separately `declared_families=("prose",)`), `unregistered_evidence_source`.
7. `test_a_refused_extension_registers_nothing`: after a refusal on the last predicate, the fingerprint and every section equal the pre-call values.
8. `test_a_case_variant_of_a_registered_name_is_refused`: `STORY` after `story`, and `Table` against the built-in.
9. `test_owner_families_are_checked_against_the_extension_or_the_declared_families`: an `incident` owner passes through the kind's family; `declared_families=("work",)` refuses the same extension.
10. `test_freeze_refuses_registration_and_the_scope_restores_the_frozen_flag`: on `fresh = Registry.with_builtins()` inside `use_registry(fresh)`, `register` after `freeze()` raises `frozen`; calling `freeze()` twice is harmless; inside `extension_scope()` the frozen `fresh` accepts a registration, and after the scope it is frozen again and lacks the extension.
11. `test_extension_scope_restores_the_registry_byte_for_byte`: inside the scope `current_registry() is REGISTRY` and `REGISTRY.object_kind("incident_fixture")` resolves; after the scope, including when the body raises, `REGISTRY`'s fingerprint, frozen flag and every section equal their pre-scope values.
12. `test_lookups_of_unregistered_names_raise_unregistered_name`: each of the seven lookups; `isinstance(error, KeyError)`.
13. `test_fingerprint_is_independent_of_registration_order`: two kinds registered as one extension versus two; equal fingerprints.
14. `test_fingerprint_ignores_model_titles_and_descriptions_but_not_field_names`: a docstring change leaves it equal; an attribute renamed from `title` to `name` changes it.
15. `test_a_changed_fact_template_changes_the_fingerprint_and_the_declaring_configuration`: separate scopes with template version `1` and `2` (text changed). The fingerprints differ, and `generation_for_inputs(..., configuration=connector_configuration(name="incident_ndjson", version="1", templates=current_registry().declared_template_versions(["incident_fixture"]), parsers=[]))` yields a different `id` and `manifest_hash`.
16. `test_a_template_text_change_without_a_version_bump_changes_only_the_fingerprint`.
17. `test_use_registry_validates_records_against_the_installed_registry_only`: `fresh = Registry.with_builtins()`; register `incident_extension()`; `freeze()`. Inside `use_registry(fresh)`, `KnowledgeObject(kind="incident_fixture", ...)` validates; outside it raises. `REGISTRY.fingerprint()` is unchanged, and a new `Registry.with_builtins().fingerprint() == REGISTRY.fingerprint()`.
18. `test_registry_modules_import_nothing_outside_the_knowledge_leaf_modules`: an AST scan of the four new modules and `predicates.py`. Imports must fall within the standard library, `pydantic`, and `hippo.knowledge.{contract,identity,locators,registry,predicates}`; `registry.py` may also import `builtin_types`, inside a function only.
19. `test_each_knowledge_module_imports_first_in_a_fresh_interpreter[<module>]`: for `registry`, `predicates`, `builtin_types`, `contract`, `locators` and `model`, run `subprocess.run([sys.executable, "-W", "error", "-c", "import hippo.knowledge.<m>; from hippo.knowledge.registry import REGISTRY; assert 'file' in REGISTRY.object_kinds()"], check=True)`.
20. `test_connector_configuration_is_canonical_and_reads_declared_template_versions`: inside a scope, `declared_template_versions(["incident_fixture"]) == {"incident_fixture.severity": "1"}` and `declared_template_versions(["pager"])` raises `UnregisteredName`; reordering the `templates` keys or the `parsers` leaves `canonical_json(connector_configuration(...))` unchanged; the result's only key is `"connector"`, and it contains no fingerprint.

**`tests/unit/test_registry_model.py` (new):**

1. `test_the_vocabulary_slice_changes_no_persisted_column`: `migrations.CURRENT_SCHEMA_VERSION == 7` and `migrations.MIGRATION_CHECKSUM == "73720e1eaeed7c148033c269de3a7e3af0d0c167fd87e580622f5c57537787f3"`. S1b deletes this test (§6.4).
2. `test_object_kind_literal_names_exactly_the_builtin_kinds`.
3. `test_a_registered_kind_validates_knowledge_objects_and_query_kinds`: `KnowledgeObject(kind="incident_fixture")` and `QueryRequest(kinds=("incident_fixture",))` pass inside `scoped` and fail after it.
4. `test_registered_artifact_and_connector_kinds_validate_their_records`.
5. `test_a_refused_extension_leaves_no_name_a_record_accepts[<reason>]`: the §5.5 item 6 cases again. After the refusal, the record carrying the refused name raises `ValidationError` (kind, predicate, locator, artifact kind, connector kind). For `shadows_builtin` and `duplicate_name`, `REGISTRY.object_kind("file")` is the built-in definition instead.
6. `test_builtin_locator_canonical_json_is_byte_identical_to_the_union_adapter`: for one sample of each of the seven kinds, `canonical_locator_json(v) == canonical_json(LOCATOR_ADAPTER.validate_json(normalize_json(v)).model_dump(mode="json"))`.
7. `test_builtin_span_identity_is_unchanged`: `EvidenceSpan(revision_id="revision-x", locator_kind="file_lines", locator_json='{"kind":"file_lines","path":"a.py","start":1,"end":2}', text="hello", policy_id="policy-x").id == "span-3f9d480f360a65f44ffbf25b1bb72b282ead62e65bad0f9723a614e9170cb15a"`.
8. `test_a_registered_locator_validates_and_canonicalizes_an_evidence_span`.
9. `test_answer_location_is_empty_for_an_extension_locator`: `answer_evidence._location` returns `""` for an `incident_event` citation and the existing labels for `file_lines` and `table_cell`.
10. `test_predicates_view_holds_the_non_identity_predicates_and_follows_extensions`: 32 outside a scope, 33 with `AFFECTS_FIXTURE`; `"SAME_OBJECT_AS" not in PREDICATES`; `PREDICATES["AFFECTS_FIXTURE"].traversal_permitted`.
11. `test_same_object_as_accepts_any_registered_kind_pair_without_ownership_or_traversal`: `checked_assertion` over `service` and `incident_fixture`, and over `table` and `view`; `predicate_definition("SAME_OBJECT_AS").traversal_permitted is False`.
12. `test_same_object_as_stores_the_lexically_smaller_canonical_key_as_subject`: the reversed order and the self-pair each raise the §5.4 message.
13. `test_alias_of_keeps_its_alias_subject_rule`: a `symbol` subject still raises `Invalid endpoint kinds for ALIAS_OF`.
14. `test_renamed_to_and_duplicate_of_keep_the_matching_kind_rule`.
15. `test_projection_reads_predicate_definitions_through_the_registry`: `"PREDICATES[" not in inspect.getsource(hippo.knowledge.projection)`.
16. `test_the_two_new_evidence_classes_validate_and_change_no_column`: `ObjectObservation` and `AssertionVersion` accept both; `"model_guess"` is refused; `KNOWLEDGE_COLUMNS[...]["evidence_class"] == "STRING"`.

### 5.6 GREEN commands and commits

Run from the worktree (`/Users/mascott/projects/hippo/.worktrees/s1a`):

```text
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_registry.py tests/unit/test_registry_model.py -q -o addopts='' -W error > /tmp/hippo-s1a-green.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_knowledge_contracts.py tests/unit/test_code_binding.py tests/unit/test_code_history.py tests/unit/test_evidence_projection.py tests/unit/test_structural_loading.py tests/unit/test_answer_original_citations.py tests/unit/test_evidence_access.py tests/unit/test_evidence_store_access.py tests/unit/test_derived_evidence_access.py tests/unit/test_store_knowledge.py tests/unit/test_temporal_evidence.py tests/unit/test_generation_store.py tests/unit/test_generation_profiles.py tests/unit/test_query_snapshots.py tests/unit/test_knowledge_scoped_reads.py tests/unit/test_managed_source_inventory.py tests/unit/test_converting_source_serving.py tests/unit/test_policy_migration.py tests/unit/test_build_authority.py tests/unit/test_code_capture_acceptance.py tests/unit/test_store_migrations.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-s1a-regression-fake.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_registry_model.py tests/unit/test_store_knowledge.py tests/unit/test_generation_store.py tests/unit/test_store_migrations.py -q -o addopts='' -W error > /tmp/hippo-s1a-ladybug.log 2>&1; echo EXIT $?
.venv/bin/ruff check src/hippo/knowledge/contract.py src/hippo/knowledge/locators.py src/hippo/knowledge/registry.py src/hippo/knowledge/builtin_types.py src/hippo/knowledge/predicates.py src/hippo/knowledge/model.py src/hippo/knowledge/projection.py src/hippo/knowledge/answer_evidence.py tests/unit/test_registry.py tests/unit/test_registry_model.py && .venv/bin/ruff format --check <the same files>
```

The regression line is the set `grep -rln` finds for `predicates`, `EvidenceClass`, `locator_kind`,
`ObjectKind` and `test_store_migrations` under `tests/unit`. Every file in it passes unchanged. The
anyio filter is form (b) of the rulebook; record it in the evidence.

Commits, in order, each green on the targeted tests:

1. "Move the knowledge contract primitives and locator models into leaf modules" (`contract.py`, `locators.py`, `model.py` imports; `test_knowledge_contracts.py` green).
2. "Add the ontology registry with its refusal rules and fingerprint" (`registry.py`, most of `test_registry.py`).
3. "Register the built-in vocabulary and serve predicates from the registry" (`builtin_types.py`, `predicates.py`).
4. "Validate kinds, locators and predicates through the registry" (`model.py`, `projection.py`, `answer_evidence.py`, `test_registry_model.py`).

### 5.7 Files

- **Own:** new `src/hippo/knowledge/contract.py`, `locators.py`, `registry.py`,
  `builtin_types.py`; modified `src/hippo/knowledge/predicates.py`, `model.py`, `projection.py`
  (`:67`, `:656` only), `answer_evidence.py` (`:6`, `:12`, `:25`); new
  `tests/unit/test_registry.py` and `tests/unit/test_registry_model.py`.
- **Do not touch:**
  - `src/hippo/store/*`, `src/hippo/ingest/*`, `tests/fakes/*`, `src/hippo/knowledge/dense.py`,
    `code_binding.py`, `code_history.py`, `lifecycle.py`, `embedding_cache.py`.
  - Every existing test file.
  - In `model.py`: `_RECORD_CLASSES`, any `identity_fields`, any field whose `migrations._type`
    changes.
  - `docs/spec/*`, the ledgers, `data/`, `.rag-dev-data/`.

## 6. S1b: `Unit`, the widened columns and schema v8

**Goal.** One journaled schema step adds `Unit`, the six `AssertionVersion` columns,
`Generation.registry_fingerprint` and `Connector.classification_json` on Fake, LadybugDB and Neo4j.
The v1–v7 journal is byte-identical, every stored identity is unchanged, every sealed generation
re-verifies, and units are written under the build lease, checksummed and collected with their
generation. S1b starts from S1a's merge.

### 6.1 Model changes (`src/hippo/knowledge/model.py`, after S1a)

```python
class Connector(Record):
    # workspace_id, kind, instance_url, config_json, credential_ref, enabled, capabilities_json unchanged
    classification_json: Json = "{}"  # v8: the stored probe result (design §2); mutable, not identity
    identity_fields = ("workspace_id", "kind", "instance_url")

    @field_validator("classification_json")
    @classmethod
    def classification_object(cls, value):
        if not isinstance(json.loads(value), dict):
            raise ValueError("Connector classification must be a JSON object")
        return value


class Generation(Record):
    # fields at model.py:358-367 unchanged
    registry_fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None  # v8; not identity
    # identity_fields (model.py:368-375) and the `publication` validator unchanged


class AssertionVersion(TemporalRecord):
    # assertion_id, evidence_class, rule_version, confidence, status and identity_fields unchanged
    # v8 (design §4): the specification's edge provenance; None on every pre-kit row; not identity
    family: Literal["deterministic", "probabilistic"] | None = None
    source: RegisteredEvidenceSource | None = None
    rule: Code | None = None
    weight: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    statement: Text | None = None
    unit_id: Text | None = None

    @field_validator("confidence", "weight", mode="before")
    @classmethod
    def no_boolean_confidence(cls, value):  # the existing validator, now also over `weight`
        if isinstance(value, bool):
            raise ValueError("Confidence must be numeric, not boolean")
        return value

    @model_validator(mode="after")
    def kit_provenance(self) -> Self:
        if (self.family is None) != (self.source is None):
            raise ValueError("Assertion version family and source appear together")
        if self.family is None and any(
            value is not None for value in (self.rule, self.weight, self.statement, self.unit_id)
        ):
            raise ValueError("Assertion version provenance fields require a family and source")
        if self.source == "rule" and self.rule is None:
            raise ValueError("A rule-sourced assertion version names its rule")
        if self.weight is not None and self.weight != self.confidence:
            raise ValueError("Assertion version weight must equal its confidence")
        return self


UnitKind = Literal["sentence", "statement", "row", "diff_line", "rendered_fact", "rendered_edge"]
RENDERED_UNIT_KINDS = frozenset({"rendered_fact", "rendered_edge"})
TEMPLATE_REFERENCE = r"^[A-Za-z][A-Za-z0-9_.:-]*@[A-Za-z0-9][A-Za-z0-9_.:-]*$"


class Unit(Record):  # placed after NativeBinding (model.py:608-614)
    generation_id: Text
    passage_id: Text
    span_id: Text  # the original evidence; rendered kinds name the span their attributes came from
    ordinal: Nonnegative
    kind: UnitKind
    text: str  # a verified slice of the span, or the template output for rendered kinds
    content_hash: Text  # sha256 of `text`: the boilerplate weight key (spec §7.2)
    prefix: str = ""  # heading or enclosing symbol with its separator; empty when rendered
    embed_text: str  # prefix + text exactly (design §4); what is embedded
    embed_hash: Text  # sha256 of `embed_text`; the vector cache key
    mentions_json: Json  # object ids; the rows of M
    template: Annotated[str, Field(pattern=TEMPLATE_REFERENCE)] | None = None  # "<name>@<version>"
    identity_prefix = "unit"
    identity_fields = ("generation_id", "passage_id", "ordinal", "content_hash")

    @model_validator(mode="before")
    @classmethod
    def derived_hashes(cls, values):
        if isinstance(values, dict):
            for source, target, message in (
                ("text", "content_hash", "Unit content hash does not match its text"),
                ("embed_text", "embed_hash", "Unit embed hash does not match its embed text"),
            ):
                if isinstance(values.get(source), str):
                    expected = text_hash(values[source])
                    if values.get(target, expected) != expected:
                        raise ValueError(message)
                    values = values | {target: expected}
        return values

    @field_validator("mentions_json")
    @classmethod
    def canonical_mentions(cls, value):
        mentions = json.loads(value)
        if not isinstance(mentions, list) or any(type(item) is not str or not item for item in mentions):
            raise ValueError("Unit mentions must be a JSON array of object ids")
        canonical_ids(tuple(mentions), label="Unit mentions")
        return value

    @model_validator(mode="after")
    def representation(self) -> Self:
        if not self.text.strip():
            raise ValueError("Unit text must not be blank")
        if self.embed_text != self.prefix + self.text:
            raise ValueError("Unit embed text must be its prefix followed by its text")
        if self.kind in RENDERED_UNIT_KINDS:
            if self.template is None or self.prefix:
                raise ValueError("A rendered unit names its template and carries no prefix")
        elif self.template is not None:
            raise ValueError("Only a rendered unit names a template")
        return self
```

Also in `model.py`:

- `GenerationEvidenceMember.record_kind` (`:394-407`) appends `"Unit"`.
- `_RECORD_CLASSES` (`:1412-1451`) gains `Unit` after `NativeBinding`.
- Every other record is unchanged.

### 6.2 Store changes, file by file

1. **`src/hippo/store/migrations.py`:** §6.3.
2. **`src/hippo/store/knowledge.py`:**
   - `:74` becomes `"AssertionVersion": {"assertion_id": "Assertion", "unit_id": "Unit"}`.
   - After `:80`, add `"Unit": {"generation_id": "Generation", "span_id": "EvidenceSpan", "passage_id": "Passage"}`.
   - `:154` adds `"classification_json"` to `MUTABLE_FIELDS["Connector"]`.
   - No `REL_FIELDS` or `KNOWLEDGE_RELATIONS` entry: units are several per passage, no reader
     traverses unit to span, and each relationship would add one `MERGE` per write
     (`:579-584`).

   What these entries do elsewhere: `_references` skips `None` (`:591`), so a pre-kit version's
   reference set is unchanged; `_validate_knowledge` then requires each referenced row to exist
   (`:679-683`); `_record_revisions` follows the span to its revision and ignores `Passage` and
   `Generation` (`generations.py:554-561`).
3. **`src/hippo/store/authorization.py`:** `"Unit"` joins the `content` tuple (`:116-138`).
4. **`src/hippo/store/generations.py`:**
   - `:640-653`: `k.Unit` joins the tuple, and `legacy_fixture=not isinstance(record, (k.GenerationEvidenceMember, k.ProseExtraction, k.Unit))`,
     so a unit write needs a claimed build and a live lease.
   - After the `GenerationEvidenceMember` block (`:674-682`), add:

     ```python
     if isinstance(record, k.Unit):
         passage = next(iter(self._native_rows("Passage", ids=[record.passage_id])), None)
         span = self._knowledge_get("EvidenceSpan", record.span_id)
         if (
             passage is None
             or passage.get("generation_id") != record.generation_id
             or span is None
             or not self._revision_member(record.generation_id, span.revision_id)
         ):
             raise ValueError("Unit passage or span is outside its generation")
     ```
   - Module level, and used by `visit` at `:984` as `evidence[key] = _evidence_row(record)`:

     ```python
     # Schema v8 columns an older row reads back as null. Hashing the null keys would change the
     # evidence checksum of every generation sealed before v8, and `validate_generation_seal` would
     # then refuse it (D19).
     V8_UNSET_FIELDS = {"AssertionVersion": ("family", "source", "rule", "weight", "statement", "unit_id")}


     def _evidence_row(record) -> dict:
         row = record.model_dump(mode="json")
         for field in V8_UNSET_FIELDS.get(type(record).__name__, ()):
             if row[field] is None:
                 del row[field]
         return row
     ```
   - After the dense loop (`:1082-1086`), add:

     ```python
     unit_members = {member.record_id for member in exact if member.record_kind == "Unit"}
     units = self._knowledge_rows("Unit", generation_id=generation_id)
     if {unit.id for unit in units} != unit_members:
         raise ValueError("Generation units differ from their exact membership")
     dense_ids = {row["id"] for row in dense}
     if any(unit.passage_id not in dense_ids for unit in units):
         raise ValueError("Unit passage is outside the generation's dense coverage")
     ```

     A unit's span must also be an exact member, which the existing closure rule (`:1031-1036`)
     already enforces once `Unit` is a `record_kind`. `visit` skips `Generation` (`:982`), so
     `registry_fingerprint` never enters a checksum.
5. **`src/hippo/store/snapshots.py`:** `:299` becomes
   `kinds = ["GenerationMember", "NativeBinding", "IndexManifest", "Unit"]`, with the comment
   "units are retrieval representations of this generation's passages and go with them".
6. **`src/hippo/knowledge/lifecycle.py`:** `generation_for_inputs` (`:15-26`) gains the keyword
   `registry_fingerprint: str | None = None`, passed to `k.Generation(...)` at `:56-65`. The
   docstring says it is recorded, not hashed, because the manifest (`:46-55`) does not include it.

No change to `store/ladybug.py`, `store/memory.py` or `tests/fakes/fake_store.py` (§9 deviation 3).

### 6.3 Schema v8

Edits to `src/hippo/store/migrations.py`:

- `:18`: `CURRENT_SCHEMA_VERSION = 8`.
- After `:199`, add `V7_DESCRIPTOR = json.loads("""...""")` with the comment "Published by
  df05bac. v8 widened the models, so v7 stops tracking them", followed by
  `V7_CHECKSUM = text_hash(canonical_json(V7_DESCRIPTOR))`. Generate the literal in the s1b
  worktree before any model change:

  ```text
  .venv/bin/python -c "from hippo.store import migrations as m; from hippo.knowledge.identity import canonical_json, text_hash; d = m._descriptor(7); assert text_hash(canonical_json(d)) == '73720e1eaeed7c148033c269de3a7e3af0d0c167fd87e580622f5c57537787f3'; print(canonical_json(d))" > /tmp/hippo-s1b-v7-descriptor.json
  ```
- `:212-220`: `7: V7_CHECKSUM, 8: MIGRATION_CHECKSUM`.
- `:223-236`: version 7 returns `V7_DESCRIPTOR`; version 8 returns
  `[8, KNOWLEDGE_COLUMNS, KNOWLEDGE_RELATIONS, SOURCE_COLUMNS, PASSAGE_COLUMNS, NATIVE_COLUMNS]`,
  with the comment "live while v8 is current; freeze it before v9".
- `:493-511`: replace `_v7_indexes()` and its call with the literal
  `V7_INDEXES = (("knowledge_deriveddependency_derived_record_id", "DerivedDependency", "derived_record_id"), ("knowledge_generationevidencemember_record_id", "GenerationEvidenceMember", "record_id"))`.
  `V7_INDEX_STEPS` and `validate_physical_schema`'s version loop (`:439-453`) are unchanged.
- In `schema_steps` (`:517`), before the version 7 branch:

```python
V8_ADDED_COLUMNS = (
    ("AssertionVersion", "family"),
    ("AssertionVersion", "source"),
    ("AssertionVersion", "rule"),
    ("AssertionVersion", "weight"),
    ("AssertionVersion", "statement"),
    ("AssertionVersion", "unit_id"),
    ("Generation", "registry_fingerprint"),
    ("Connector", "classification_json"),
)


def schema_steps(store, *, version=CURRENT_SCHEMA_VERSION) -> list[str]:
    if version == 8:
        columns = _descriptor(8)[1]
        if store.knowledge_backend == "ladybug":
            return [
                "CREATE NODE TABLE IF NOT EXISTS Unit("
                + ", ".join(
                    f"{field} {kind}" + (" PRIMARY KEY" if field == "id" else "")
                    for field, kind in columns["Unit"].items()
                )
                + ")",
                *(
                    f"ALTER TABLE {table} ADD IF NOT EXISTS {field} {columns[table][field]}"
                    for table, field in V8_ADDED_COLUMNS
                ),
            ]
        # Neo4j properties need no DDL; the Unit identity and its generation lookup do.
        return [
            "CREATE CONSTRAINT knowledge_unit_id IF NOT EXISTS FOR (n:Unit) REQUIRE n.id IS UNIQUE",
            "CREATE INDEX knowledge_unit_generation_id IF NOT EXISTS FOR (n:Unit) ON (n.generation_id)",
        ]
    # the existing branches for versions 7, 6, 3 and the descriptor-driven ones follow unchanged
```

- `_data_transform` (`:583`), before the `(5, 6, 7)` branch:

```python
if version == 8:
    # Added columns read back null, which every widened field accepts except the connector
    # classification, whose default is an empty object (the v3 `origin` backfill's pattern).
    if store.knowledge_backend != "fake":
        store.run("MATCH (c:Connector) WHERE c.classification_json IS NULL SET c.classification_json='{}'")
    store._knowledge_rows("Connector")  # every row must validate before the step is journaled
    return
```

The resulting statements, exactly:

| Backend | v8 statements, in order | Journal |
| --- | --- | --- |
| LadybugDB | `CREATE NODE TABLE IF NOT EXISTS Unit(id STRING PRIMARY KEY, identity_key STRING, generation_id STRING, passage_id STRING, span_id STRING, ordinal INT64, kind STRING, text STRING, content_hash STRING, prefix STRING, embed_text STRING, embed_hash STRING, mentions_json STRING, template STRING)`; `ALTER TABLE AssertionVersion ADD IF NOT EXISTS family STRING`; `... source STRING`; `... rule STRING`; `... weight DOUBLE`; `... statement STRING`; `... unit_id STRING`; `ALTER TABLE Generation ADD IF NOT EXISTS registry_fingerprint STRING`; `ALTER TABLE Connector ADD IF NOT EXISTS classification_json STRING`; then the backfill `MATCH`, all in one transaction (`migrations.py:665-672`) | `knowledge-v8`, step 9, complete |
| Neo4j | `CREATE CONSTRAINT knowledge_unit_id ...`; `CREATE INDEX knowledge_unit_generation_id ...`, each journaled `pending` with its step (`:683-687`); then the backfill `MATCH` and the completion row in one transaction | `knowledge-v8`, step 2, complete |
| Fake | no DDL; the journal row is written inside the migration transaction (`:659-663`) | `version 8`, step 0, complete |

### 6.4 RED tests

**First, at the s1b base:** commit 1 below (the v7 freeze) with
`test_v7_descriptor_and_indexes_are_frozen_at_their_published_values`. It is green at the base,
because freezing changes no value, and it turns into the frozen-history guard for everything after.
Then write the rest RED, save `/tmp/hippo-s1b-red.log`, and implement.

**`tests/unit/test_store_migrations.py` (add):**

1. `test_v7_descriptor_and_indexes_are_frozen_at_their_published_values`:

   ```python
   def test_v7_descriptor_and_indexes_are_frozen_at_their_published_values():
       from hippo.knowledge.identity import canonical_json, text_hash

       m = migrations()
       assert {version: m.SUPPORTED_CHECKSUMS[version] for version in range(1, 8)} == {
           1: "c7499192a9762dc424094c0bb4292914607748cd907e603fc8fddd9076ff6d12",
           2: "f4419a33c505b28fc7239c6aa6ac323c9bbcb926159df457c2a3876f0bbc5b0f",
           3: "ffc12b6f274a5b5573eed4dde9798f8b4abe9d37d68a570247a5c281c10d3ddc",
           4: "af3234c2ffd6aa2a5c935b06352ad91c92b8c44f80926969a6c3a775a4d5dfd7",
           5: "45745388d17d797b5c67879c98c80f53d0507cad28b0d6f60fec4268ee032619",
           6: "4b639a6ba1b60516f2cf31d74bd1aeb0e59295d3aaf7e1fd7825e85d5d95137d",
           7: "73720e1eaeed7c148033c269de3a7e3af0d0c167fd87e580622f5c57537787f3",
       }
       assert text_hash(canonical_json(m._descriptor(7))) == m.V7_CHECKSUM
       assert m.V7_INDEXES == (
           ("knowledge_deriveddependency_derived_record_id", "DerivedDependency", "derived_record_id"),
           ("knowledge_generationevidencemember_record_id", "GenerationEvidenceMember", "record_id"),
       )
   ```

   In commit 2 it gains `SUPPORTED_CHECKSUMS[8] == m.MIGRATION_CHECKSUM` and the v7-shape
   assertions: `"Unit"` is absent, and `family`, `registry_fingerprint` and
   `classification_json` are absent from their tables.
2. `test_v8_descriptor_adds_unit_and_the_widened_columns_only`: `canonical_json(_descriptor(8)[2:]) == canonical_json(_descriptor(7)[2:])`. The set of `(table, column)` pairs present at 8 and not at 7 equals the `Unit` columns plus `V8_ADDED_COLUMNS`. `KNOWLEDGE_COLUMNS["AssertionVersion"]["weight"] == "DOUBLE"`.
3. `test_v8_schema_steps_are_exact_per_backend`: `schema_steps(SimpleNamespace(knowledge_backend=...), version=8)` equals the table in §6.3 for `ladybug` and `neo4j`.
4. `test_populated_v7_ladybug_reopens_as_v8_without_reidentification`, modelled on `:443-480`.
   - **Seed.** With `CURRENT_SCHEMA_VERSION` patched to 7, open a `LadybugStore`. Write
     `AssertionVersion`, `Generation` and `Connector` rows with raw `CREATE (n:<Label> {...})`,
     restricted to `V7_DESCRIPTOR[1][<Label>]`'s columns, with instants as naive `datetime`
     parameters. Not `_write_knowledge`: the v8 models would `SET` columns the v7 tables lack.
     Assert the history is versions 1–7, then close.
   - **Reopen unpatched.** `schema_history()[:7]` equals the seeded history; version 8 is complete;
     each `_knowledge_get` equals the record built in Python (new fields `None`, classification
     `"{}"`).
   - **Samples** (pinned below): `AssertionVersion(assertion_id="assertion-x", evidence_class="declared", rule_version="r1", confidence=1.0, status="active", recorded_from=datetime(2026, 1, 1, tzinfo=UTC), validity_kind="atemporal", temporal_basis="atemporal")`,
     `Generation(source_id="source-x", status="staging", parser_version="p1", linker_version="l1", embedding_profile="e1", created_at=<same>, manifest_hash="m1")`,
     `Connector(workspace_id="workspace-x", kind="github", instance_url="https://github.com")`.
5. `test_v8_backfills_connector_classification_on_existing_rows` (`store` fixture): on LadybugDB `SET c.classification_json = NULL` and on Neo4j `REMOVE c.classification_json`; then `_data_transform(store, version=8)` reads the connector back with `"{}"`. Fake skips with the reason "Fake storage holds v8 records only".
6. Adapt `:259` to `{1, 2, 3, 4, 5, 6, 7, 8}` and `:293` to `[2, 3, 4, 5, 8]`.

**`tests/unit/test_registry_model.py` (append; delete S1a's `test_the_vocabulary_slice_changes_no_persisted_column`):**

7. `test_unit_derives_and_checks_its_content_and_embed_hashes`.
8. `test_unit_embed_text_is_its_prefix_followed_by_its_text`: `prefix="Refunds: "` with `text="It refunds"` and `embed_text="Refunds: It refunds"` passes (S2 keeps its separator in the prefix); `prefix="Refunds"` with the same `embed_text` raises; an empty prefix with `embed_text` other than `text` raises.
9. `test_rendered_units_name_a_template_and_carry_no_prefix`: `rendered_fact` without a template, or with a prefix, raises; `sentence` with a template raises; `template="severity@1"` passes.
10. `test_unit_mentions_are_sorted_unique_object_ids`.
11. `test_unit_identity_is_generation_passage_ordinal_and_content_hash`: changing `prefix` or `mentions_json` keeps the id; changing `text` changes it.
12. `test_unit_embed_hash_is_the_embedding_cache_input_hash`: `cache_key(profile, unit.embed_text).input_hash == unit.embed_hash`. Two units with equal `text` and different `prefix` share `content_hash` and differ in `embed_hash`.
13. `test_assertion_version_kit_provenance_rules`: one case per `kit_provenance` message; `source="pager"` outside a scope raises `Unknown evidence source`.
14. `test_v8_fields_leave_existing_identities_unchanged`: the three §6.4 item 4 samples have ids `assertionversion-6467ad40c0cb7cc99b5b7bc8dc6b5b9b7ea5329802a02102e6d3676a3f976124`, `generation-48340495d0e8683448ab762da4a3446b32ffe397c8377b22d4654c9decb0e2cc` and `connector-bc33ca852d33fda7c10321746a2eaf767b03f9bf735f2425ab82fa45cfedaa6f` (computed at `ef143b1`). The ids are unchanged when the v8 fields are set (`family="deterministic", source="metadata"`; `registry_fingerprint="a" * 64`; `classification_json='{"partitions":[]}'`).
15. `test_connector_classification_is_a_json_object_outside_identity`: `"[]"` raises.
16. `test_generation_registry_fingerprint_is_a_sha256_outside_identity_and_the_manifest`: `generation_for_inputs(..., registry_fingerprint="b" * 64)` has the same `id` and `manifest_hash` as without; `"B" * 64` and `"b" * 63` are refused.

**`tests/unit/test_generation_store.py` (add; reuse the helpers at `:13-190`):**

17. `test_unit_write_requires_a_build_lease_and_its_generations_passage`: refused without `generation_write`, refused for another generation's passage, refused for a span outside the generation's revisions, accepted with all three.
18. `test_units_are_exact_members_and_enter_the_evidence_checksum`: evidence `row_count` grows by two (the unit and its member); `seal` then `validate_generation_seal` pass.
19. `test_a_unit_row_outside_exact_membership_refuses_the_checksum`: a written unit without its member raises "Generation units differ from their exact membership".
20. `test_collection_removes_units_with_their_generation`: after `discard_generation`, `_knowledge_rows("Unit", generation_id=gen.id) == []`.
21. `test_unset_v8_assertion_fields_leave_the_evidence_checksum_unchanged`. The records are those of `test_sealed_proof_cannot_gain_support` (`:305-331`), copied into a new helper `assertion_generation(store, **version_fields)`, not refactored out of that test. Compute `generation_checksums`, then monkeypatch `generations._evidence_row` with the v7 projection below; the checksums must be equal:

    ```python
    def v7_row(record):
        row = record.model_dump(mode="json")
        columns = migrations.V7_DESCRIPTOR[1].get(type(record).__name__)
        return row if columns is None else {key: value for key, value in row.items() if key in columns}
    ```
22. `test_set_v8_assertion_fields_enter_the_evidence_checksum`: the same with `family="deterministic", source="metadata"`; the two checksums differ.
23. `test_registry_fingerprint_round_trips_outside_identity_and_cannot_change`: `put_knowledge` of a generation with `registry_fingerprint="c" * 64` reads back equal; `update_knowledge` changing it raises `Update changes immutable evidence fields`.
24. `test_connector_classification_updates_under_the_same_identity`: a `kind="local"` connector; `update_knowledge` with a new classification keeps the id and reads back.
25. `test_assertion_version_unit_reference_must_exist`: raises `Missing Unit reference`.
26. Adapt `:67` to `== 8`. `test_classifier_is_exhaustive` (`:136-140`) passes unchanged once `Unit` is in `RECORD_EPOCHS`.
27. `test_a_v7_generation_keeps_its_published_evidence_checksum`, added in commit 1 with the `assertion_generation(store, *, source_id=None, **version_fields)` helper, before any model change:
    - Inside `monkeypatch.context()`, patch `new_id` in the module that defines `type(store).create_source` to return `"source-pinned"`, then call `store.create_source("text", "pinned")`. Each backend calls `new_id` once there (`tests/fakes/fake_store.py:241`, `store/ladybug.py:738`, `store/memory.py:60`), and the workspace is `DEFAULT_WORKSPACE_ID` on every backend.
    - Build `assertion_generation(store, source_id="source-pinned")` with no v8 fields.
    - Pin only the `evidence` entry of `generation_checksums` (checksum and row count), because passage embeddings may round-trip differently per backend. Capture the literal on Fake at commit 1 and confirm LadybugDB gives the same value at commit 1. If the backends differ, record that in the evidence rather than pinning a value per backend.
    - Commits 2 and 3 must pass it unchanged. It proves that a generation sealed under v7 verifies under v8, which the reopen test cannot show.

**Other existing assertions that pin the schema version, adapted in commit 2 and named in the
evidence:**

- `tests/unit/test_policy_migration.py:56`, `:126`, `:166`, `:202`: `== 7` becomes `== 8`.
- `tests/unit/test_policy_migration.py:134`: `7: m.MIGRATION_CHECKSUM,` becomes
  `7: m.V7_CHECKSUM, 8: m.MIGRATION_CHECKSUM,`.
- `tests/unit/test_knowledge_scoped_reads.py:543-546`: version 8; keys `[1, ..., 8]`;
  `SUPPORTED_CHECKSUMS[7] == migrations.V7_CHECKSUM != V6_CHECKSUM`; and
  `SUPPORTED_CHECKSUMS[8] == migrations.MIGRATION_CHECKSUM`.
- `tests/unit/test_derived_generation_store.py:128`: `== 8`.

`tests/unit/test_managed_source_inventory.py:387-388` and
`tests/unit/test_generation_graph_loader.py:75`, `:79` pin graph versions, not the schema, and stay.
Before committing, re-run
`grep -rn "CURRENT_SCHEMA_VERSION\|SUPPORTED_CHECKSUMS\|\"version\"\] == 7" tests` and adapt only
schema-version pins.

### 6.5 GREEN commands and commits

```text
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_registry.py tests/unit/test_registry_model.py tests/unit/test_knowledge_contracts.py tests/unit/test_store_migrations.py tests/unit/test_generation_store.py -q -o addopts='' -W error > /tmp/hippo-s1b-green.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_policy_migration.py tests/unit/test_knowledge_scoped_reads.py tests/unit/test_derived_generation_store.py tests/unit/test_generation_scoped_reads.py tests/unit/test_generation_resume.py tests/unit/test_staged_prose_writer.py tests/unit/test_staged_code_writer.py tests/unit/test_prose_generation.py tests/unit/test_code_generation.py tests/unit/test_temporal_evidence.py tests/unit/test_store_knowledge.py tests/unit/test_evidence_projection.py tests/unit/test_query_snapshots.py tests/unit/test_generation_profiles.py tests/unit/test_code_capture_acceptance.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-s1b-regression-fake.log 2>&1; echo EXIT $?
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_registry_model.py tests/unit/test_store_migrations.py tests/unit/test_generation_store.py tests/unit/test_policy_migration.py tests/unit/test_knowledge_scoped_reads.py tests/unit/test_derived_generation_store.py -q -o addopts='' -W error > /tmp/hippo-s1b-ladybug.log 2>&1; echo EXIT $?
.venv/bin/ruff check src/hippo/knowledge/model.py src/hippo/knowledge/lifecycle.py src/hippo/store/migrations.py src/hippo/store/knowledge.py src/hippo/store/authorization.py src/hippo/store/generations.py src/hippo/store/snapshots.py tests/unit/test_registry_model.py tests/unit/test_store_migrations.py tests/unit/test_generation_store.py tests/unit/test_policy_migration.py tests/unit/test_knowledge_scoped_reads.py tests/unit/test_derived_generation_store.py && .venv/bin/ruff format --check <the same files>
```

Neo4j is root-owned (§8); do not run it unless the orchestrator grants the container in writing.

Commits, in order:

1. "Freeze the v7 schema descriptor and index set as literals" (`migrations.py`, tests 1 and 27 with the `assertion_generation` helper; version stays 7, every existing test is green).
2. "Add schema v8: units, assertion provenance, the registry fingerprint and connector classification" (`model.py`, `migrations.py`, `knowledge.py`, `authorization.py`, `_evidence_row` in `generations.py`, tests 2–16, 21–26, the adapted pins, the removed S1a guard).
3. "Stage, checksum and collect units with their generation" (the rest of `generations.py`, `snapshots.py`, `lifecycle.py`, tests 17–20).

### 6.6 Files

- **Own:** `src/hippo/knowledge/model.py` (the §6.1 records only), `src/hippo/knowledge/lifecycle.py`,
  `src/hippo/store/migrations.py`, `src/hippo/store/knowledge.py` (`:74`, `:80`, `:154`),
  `src/hippo/store/authorization.py` (`:116-138`), `src/hippo/store/generations.py` (the §6.2
  anchors), `src/hippo/store/snapshots.py` (`:299`), `tests/unit/test_registry_model.py`,
  `tests/unit/test_store_migrations.py`, `tests/unit/test_generation_store.py`, and the named
  assertion lines of `test_policy_migration.py`, `test_knowledge_scoped_reads.py` and
  `test_derived_generation_store.py`.
- **Do not touch:**
  - S1a's `registry.py`, `builtin_types.py`, `predicates.py`, `contract.py`, `locators.py`.
  - `src/hippo/store/ladybug.py`, `src/hippo/store/memory.py`, `tests/fakes/*`,
    `src/hippo/ingest/*`.
  - `src/hippo/knowledge/prose_preparation.py`, `code_binding.py`, `code_history.py`,
    `input_binding.py`, `staged_prose.py`, `staged_code.py`, `embedding_cache.py`,
    `projection.py`, `dense.py`, `access.py`.
  - `docs/spec/*`, the ledgers, `data/`, `.rag-dev-data/`.

## 7. Worktrees, merge order and sizing

- **s1a:** `git worktree add .worktrees/s1a -b wp/s1a <HEAD named in the spawn message, at or after ef143b1>`, then the rulebook's venv recipe.
- **s1b:** `git worktree add .worktrees/s1b -b wp/s1b <s1a's merge commit on rag-it-all-tibs>`.
- **Merge order:** s1a, then s1b. S2 may branch once s1a merges (design §13); S3 needs s1b.
- **S1a is one worker:**
  - scope: four new source modules (two are moves), four modified source files, two new test
    files, 36 tests, one Fake regression run over 21 files and one LadybugDB run;
  - fallback split, if the budget runs out: after commit 3 (S1a-1 is commits 1–3 with
    `test_registry.py`; S1a-2 is commit 4 with `test_registry_model.py`);
  - why that split is safe: between the halves the model still validates through `Literal`s and
    the `PREDICATES` view, which already serves the built-ins.
- **S1b is one worker:**
  - scope: about 120 lines of model, 70 lines of migrations plus the pasted v7 literal, 40 lines of
    store, six adapted test files, 27 tests, Fake and LadybugDB runs;
  - fallback split: after commit 2 (S1b-1 is commits 1–2, S1b-2 is commit 3);
  - what that split costs: between the halves a unit can be written without the lease guard, and
    no caller writes units until S3.

## 8. Ledger lines

For the orchestrator to apply to `ai_docs/gates/rag-it-all/cdk/GATES.md`:

- **CK1, replace the CHECK line.** `tests/unit/test_knowledge_model.py` does not exist. The
  existing model tests live in `test_knowledge_contracts.py` (record catalog `:19-27`, locators
  `:80-108`, predicates `:191-226`):

  ```text
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_registry.py tests/unit/test_registry_model.py tests/unit/test_knowledge_contracts.py tests/unit/test_store_migrations.py tests/unit/test_generation_store.py -q -o addopts='' -W error
  ```
- **CK1, add a LadybugDB CHECK line** (persistence is touched; the code-capture ledger's convention):

  ```text
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_registry_model.py tests/unit/test_store_migrations.py tests/unit/test_generation_store.py tests/unit/test_policy_migration.py -q -o addopts='' -W error
  ```
- **CK1, root-owned Neo4j parity,** recorded in `ai_docs/gates/rag-it-all/cdk/neo4j-parity.md`:

  ```text
  HIPPO_TEST_STORE=neo4j .venv/bin/pytest tests/unit/test_store_migrations.py tests/unit/test_generation_store.py tests/unit/test_policy_migration.py tests/unit/test_knowledge_scoped_reads.py -q -o addopts='' -W error
  ```
- **CK1 CRITERIA, a wording note.** "Every existing model test passes unchanged" holds for
  `test_knowledge_contracts.py` and `test_code_binding.py`. The schema-version pins in six store
  test files move to 8, as every schema version before has moved them (§6.4).
- **CK7:** add `src/hippo/knowledge/contract.py src/hippo/knowledge/locators.py src/hippo/knowledge/builtin_types.py src/hippo/knowledge/predicates.py`
  to both Ruff commands.
- **Evidence files:** `ai_docs/gates/rag-it-all/cdk/evidence-s1a.md` and `evidence-s1b.md`, each
  with RED and GREEN log paths, test counts per backend, and the anyio filter form used.

## 9. Design deviations

1. **`Unit` moves from S1a to S1b** (design §13). The live v7 checksum (§3) forbids a
   column-affecting model change without the v8 bump in the same commit.
2. **Three leaf modules beyond `registry.py`:** `contract.py`, `locators.py` and `builtin_types.py`
   (D1). Without them the registry and the model import each other. CK7's lint line widens (§8).
3. **File ownership differs from design §13.**
   - S1a also touches `knowledge/projection.py` (D10) and `knowledge/answer_evidence.py` (D9).
   - S1b also touches `store/knowledge.py`, `store/authorization.py`, `store/snapshots.py` and
     `knowledge/lifecycle.py`.
   - S1b does not touch `store/ladybug.py`, whose `NODE_TABLES` (`:111-150`) are legacy tables
     only; knowledge DDL is `migrations.schema_steps` (`:536-560`).
   - It does not touch `store/memory.py`, which holds Neo4j legacy queries only; knowledge reads and
     writes for every backend are `store/knowledge.py:417-585`.
   - It does not touch `tests/fakes/fake_store.py`, whose `_knowledge_data` is generic
     (`fake_store.py:71`, `knowledge.py:544-547`, `snapshots.py:257-258`).
4. **Registry API additions** beyond the normative list (D3), all additive.
5. **`LocatorBase` is the "`SourceLocator`" of design §3's refusal rule.** `model.SourceLocator`
   already names the built-in union that `test_knowledge_contracts.py:82` validates through.
6. **`predicates.PREDICATES` excludes identity predicates** (D10).
7. **Built-in kinds carry an open attribute model** (D6), where design §3 says `extra="forbid"`;
   extensions keep the rule.
8. **Schema-version pins in six store test files are adapted** (§6.4).
9. **Design §9's `Registry.load()` is not in S1.** Discovery imports connector packages and reads
   each connector's `TypeExtension` and families through S2's descriptor, and the brief forbids
   `registry.py` from importing `hippo.connectors`. S1 supplies the primitives a loader composes:
   `Registry.with_builtins()`, `register(..., declared_families=...)`, `freeze()` and
   `use_registry()`. `cdk-s4-kit.md` §9 (R-S1-1) asks S1 for `load()`; §11 question 7 asks the
   orchestrator to assign the loader to S4.
10. **The current registry is context-local** (D2). Design §3 describes one registry. S1 keeps a
    process default, lets a `with` block install another (S4's `run_case` step 2), and has
    `extension_scope()` extend the current registry in place for tests (S2's R12 and binder).

## 10. Cross-slice notes

What the other slices take from S1:

- the §5.2 registry API, including `frozen`, `with_builtins`, `current_registry`, `use_registry`,
  `extension_scope` and `UnregisteredName`;
- `Unit` (§6.1) and the `AssertionVersion` columns;
- `Generation.registry_fingerprint` with `generation_for_inputs(registry_fingerprint=...)`;
- `Connector.classification_json`.

This list was checked against these sources as they stood at `166bf00`:

- `cdk-s2-contract.md` §3, R1–R12 (the file last written 2026-09-15 13:24);
- `cdk-s4-kit.md` §9, R-S1-1 and R-S1-2;
- `cdk-s5-port.md` §12, R-S1-1 to R-S1-3;
- `cdk-s6-exemplar.md` §11, R-S1-1 to R-S1-3;
- `cdk-rulings.md` R2, R12 and R13.

The plan matches all three rulings:

- **R2:** S1 edits neither `ingest/prose_generation.py` nor `ingest/code_generation.py` (§6.6).
- **R12:** S1b adds `Connector.classification_json` (D22).
- **R13:** the built-in kinds are exactly today's thirty `OBJECT_KINDS`, with no `incident` kind (§5.3).

- **S2.**
  - Call `register(types, declared_families=descriptor.families)`.
  - **R1, R12:** `extension_scope()` registers into the current registry in place, so under the
    default `context.registry is REGISTRY` holds for the binder (S2 §8.1 step 1). A registry
    installed with `use_registry` is not `REGISTRY`, and that binder refuses it.
  - **R4:** `FactTemplate.version` is `Version` (a leading digit is allowed), not `Code`.
  - **R5:** `Registry.declared_template_versions` and `connector_configuration` are S1's (D25).
  - **R5:** the built-in key template part names are D13's table; S2's key-delegation table must use
    the same names.
  - **R8:** `weight` is a float in [0, 1] that equals `confidence`, and `statement` is non-blank
    `Text` (§6.1).
  - **Rendering:** `Unit` requires `embed_text == prefix + text` (D15), so the `": "` separator
    stays inside `prefix`, as S2's `unit_text` already does.
  - `checked_assertion` enforces `SAME_OBJECT_AS` ordering, so order the endpoints before building
    the assertion.
  - These are emit-time checks S1 leaves to S2: `windowed`, validation of emitted attributes
    against `attrs_model`, a statement on every edge, deterministic weight 1.0, and the
    evidence-class derivation.
  - Built-in verb phrases carry no endpoint kind. Fact template fields are attributes plus `label`
    and `key`. `Unit.template` is `"<name>@<version>"`.
  - The code lane's data-object keys differ from the registered `table`/`column` template (§11
    question 2).
- **S3.**
  - **Write order:** native `Passage`, then `Unit`, then any `AssertionVersion` naming it. Each unit
    needs its exact member, the lease, and a span on a selected revision.
  - **Fingerprint:** record `registry_fingerprint=current_registry().fingerprint()` after `freeze()`. On a
    retry, adopt the stored generation's value, as `prose_generation.py:228` adopts `created_at`.
  - **Generation equality:** `prose_preparation.py:175` compares the stored generation with one
    recomputed by `generation_for_inputs`. That fails on a fingerprinted generation unless the
    recomputation passes `registry_fingerprint=gen.registry_fingerprint`. The comparisons at
    `code_binding.py:424`, `code_history.py:441` and `input_binding.py:238` check a passage's
    generation against the build's; they hold as long as one generation record is threaded through
    the build.
  - **Epoch:** `Connector` is an authorization record (`authorization.py:114`), so a classification
    write bumps the authorization epoch (`:188-193`) and a live build must rebaseline.
  - **Visibility:** units are invisible to non-internal readers (`store/knowledge.py:923-940`).
  - **Threads:** an `emit` or bind worker in a thread pool sees `REGISTRY`, not a registry installed
    with `use_registry`, unless it runs in `contextvars.copy_context()`.
- **S5.**
  - The pre-kit lanes keep `registry_fingerprint=None`. `generation_checksums` skips the
    `Generation` row (`generations.py:982`), so CK5's allowed difference needs no normalization.
  - **R-S1-2:** the accessor is `REGISTRY`, read through `current_registry()`. "Built-ins plus
    in-repo packages" needs the loader of §11 question 7.
  - **R-S1-3:** the twelve built-in artifact kinds include `file`, `manifest`, `repository` and
    `history_event`, and all seven locator kinds are built in.
  - From S1b, `generation_checksums` hashes `AssertionVersion` rows through `_evidence_row` (D19).
    A row without v8 fields hashes exactly as before (S1b test 27), and S5's parity proof reads
    the same checksums.
- **S4.**
  - `Registry.load()` is not S1's (§9 deviation 9).
  - `Registry.with_builtins()` is R-S1-1's "fresh registry holding only the built-ins", and
    `FactTemplate(name, version, consumes, text)` satisfies R-S1-2.
  - S2's binder accepts only `REGISTRY`. A fresh registry under `use_registry` therefore serves
    registration and record validation but not binding. S2's open question Q3 (§16) already asks
    S4 to use `extension_scope()` for that.
- **S6.**
  - **R-S1-1:** `incident` is a built-in family and not a built-in kind (ruling R13).
  - **R-S1-2:** S1 spells it `FactTemplate(name, version, consumes, text)`; `consumes` names the
    attributes the text reads, and `register` refuses any other field.
  - **R-S1-3:** discovery is §11 question 7.
  - **Open question 2:** S1b adds `Connector.classification_json` (D22).
  - `answer_evidence._location` returns `""` for an extension locator, so a readable location for
    the exemplar's locator is S6's work.

## 11. Open questions

1. **Unit lookup indexes.** No index exists for `Unit.passage_id` or `Unit.content_hash`, because
   S1 reads units by generation only. Spec §7.2's boilerplate weighting by content hash would need
   a `KIND_SCOPED_FIELDS` entry and an index step in a later schema version. Decide with the stack
   decision (design §14).
2. **Two identities for one table.** The code lane keys `table` and `column` objects by
   repository, dialect, data kind and qualified name (`code_binding.py:886`); the registry records
   `database_object_key`'s shape (D13). A table seen in code and in a catalog is therefore two
   objects until an alias rule joins them. Accept that, or re-key the code lane, which is an
   identity migration S5 would have to prove byte-identical?
3. **Multi-owner built-in predicates.** Several built-ins name more than one owner family:
   `OWNED_BY`, `EXPOSES_ENDPOINT`, the four read/write predicates, `REFERENCES_OBJECT`,
   `RENAMED_TO`, `HAS_CRITERION`, `MENTIONS`, `DECIDED_IN`, `ALIAS_OF` and `BOUND_TO`. Spec §6
   stores a cross-domain fact once, by its owner. Confirm these sets or narrow them to one family
   each.
4. **Unversioned render text.** `verb_phrase` and `label_template` have no version, so changing
   one changes the fingerprint but not `configuration_json`. Should S4's version-bump assertion
   cover them through the connector version, or should S1 add version fields?
5. **Classification and the authorization epoch.** A classification write bumps the authorization
   epoch (§10, S3). Is that intended, or should the classification live on a bookkeeping record?
6. **`SAME_OBJECT_AS` ordering.** The subject is chosen by Python code-point comparison of
   `canonical_key` text. Confirm that no collation-aware order is wanted.
7. **Who implements discovery?** Design §9's `Registry.load()` must import connector packages and
   read their `TypeExtension`s through S2's descriptor. S4's plan asks S1 for it, but `registry.py`
   may not import `hippo.connectors`. Recommendation: S4 owns a loader in `hippo.connectors`, built
   on `register(..., declared_families=...)` and `freeze()`. It registers each discovered extension
   on `REGISTRY` for the process, or on `Registry.with_builtins()` under `use_registry` for a
   bounded run.

## 12. Wiring and regression hotspots

### Wiring manifest

| Interface | Implementation | Registration or consumer | Slice, commit |
| --- | --- | --- | --- |
| Registry API (§5.2) | `knowledge/registry.py` | `REGISTRY`; built-ins installed by `_ensure_builtins()` from `builtin_types.BUILTIN_EXTENSION` | S1a, 2–3 |
| Registry-backed field types | `model._registered` | `KnowledgeObject.kind`, `Artifact.kind`, `Connector.kind`, `EvidenceSpan.locator_kind`, `QueryRequest.kinds` | S1a, 4 |
| Predicate validation | `predicates.predicate_definition`, `validate_endpoints` | `Assertion` validators (`model.py:519-531`), `projection.py:656` | S1a, 3–4 |
| `PREDICATES` view | `predicates._PredicateView` | `projection.py:966`, `dense.py:197-198` | S1a, 3 |
| Locator dispatch | `model.parse_locator_json` | `canonical_locator_json`, `EvidenceSpan.valid_locator`, `answer_evidence._location` | S1a, 4 |
| Configuration fragment | `registry.connector_configuration`, `Registry.declared_template_versions` | S2's `descriptor_configuration` | S1a, 2 |
| `Unit` | `model.Unit` | `_RECORD_CLASSES`, `RECORD_EPOCHS`, `GenerationEvidenceMember.record_kind`, `authorization.py:116-138`, schema v8 | S1b, 2–3 |
| Evidence row projection | `generations._evidence_row` | `generation_checksums.visit` (`generations.py:984`) | S1b, 2 |
| Schema v8 | `migrations.py` | `SUPPORTED_CHECKSUMS[8]`, `schema_steps` on each backend | S1b, 2 |

### Regression hotspots

| # | Behaviour that must hold | Location at `ef143b1` | Pinned by |
| --- | --- | --- | --- |
| 1 | Span identity hashes the canonical locator | `model.py:437-438` | `test_builtin_span_identity_is_unchanged` |
| 2 | Thirty-two predicates with non-empty endpoint sets | `test_knowledge_contracts.py:194-198` | that test, unchanged; `test_builtin_endpoint_rules_are_the_legacy_table` |
| 3 | A v7 store opens under S1a unchanged | `migrations.py` checksum `73720e1e…` | `test_the_vocabulary_slice_changes_no_persisted_column` |
| 4 | A generation sealed under v7 still verifies | `generations.py:984`, `:1131-1132` | S1b tests 21 and 27 |
| 5 | Existing record ids do not move | every `identity_fields` | `test_v8_fields_leave_existing_identities_unchanged` |
| 6 | The code lane's freeform attribute dicts stay valid | `code_binding.py:822-832`, `:865-877` | `test_code_binding.py`, unchanged |
| 7 | `ObjectKind.__args__` and `TypeAdapter(SourceLocator)` still resolve | `test_code_binding.py:848`, `test_knowledge_contracts.py:82` | those tests, unchanged |

S1 adds no endpoint, external runtime dependency or credential, so it has no contract matrix,
dependency table or credential inventory.
