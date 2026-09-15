# CDK S1a evidence: the ontology registry and the registry-backed validators

Worker `backend-developer-1`, branch `wp/s1a`, base `ffb075e`. Contract: section 5 of
`ai_docs/plans/cdk-s1-registry.md`, amended by rulings R2, R13, R15, R16, R19, R20, R22, R23, R29
and R31 of `ai_docs/plans/cdk-rulings.md`, per the brief `ai_docs/handoffs/briefs/cdk-s1a.md`. No
review findings were delivered to this worker before the work was committed.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `5039b46` | Move the knowledge contract primitives and locator models into leaf modules | `knowledge/contract.py` (new), `knowledge/locators.py` (new), `knowledge/model.py` |
| 2 | `dc10058` | Add the ontology registry with its refusal rules and fingerprint | `knowledge/registry.py` (new) |
| 3 | `7a074b2` | Register the built-in vocabulary and serve predicates from the registry | `knowledge/builtin_types.py` (new), `knowledge/predicates.py`, `tests/unit/test_registry.py` (new) |
| 4 | `938d657` | Validate kinds, locators and predicates through the registry | `knowledge/model.py`, `knowledge/projection.py`, `knowledge/answer_evidence.py`, `tests/unit/test_registry_model.py` (new) |

All four plan commits landed; the fallback split was not used. This evidence file is a fifth,
documentation-only commit.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| Both new test files before any implementation | `/tmp/hippo-s1a-red.log` | exit 2; collection errors `ModuleNotFoundError: No module named 'hippo.knowledge.builtin_types'` and `cannot import name 'contract' from 'hippo.knowledge'` (the modules did not exist) |
| `test_registry_model.py` plus the `use_registry` test, on the commit 3 tree (before commit 4) | `/tmp/hippo-s1a-red-model.log` | exit 1; 12 failed, 38 passed. Failures are the missing feature: `Literal` errors for `incident_fixture`, `incident_export`, `incident_ndjson`; union tag `incident_event` refused; `Unknown object kind` absent from messages; `PREDICATES[` still in `projection.py`; `rule_derived` refused. The 38 passing are pins of behaviour the `Literal`s already had (refused names, byte-identical locators, predicate view, `ALIAS_OF`, `RENAMED_TO`). |

## GREEN (final tree, `938d657`)

| Line (plan section 5.6) | Log | Result |
| --- | --- | --- |
| Fake: `test_registry.py test_registry_model.py` | `/tmp/hippo-s1a-green.log` | exit 0, 110 passed (61 + 49) |
| Fake: the 21-file regression set | `/tmp/hippo-s1a-regression-fake.log` | exit 0, 717 passed, 10 skipped |
| LadybugDB: `test_registry_model.py test_store_knowledge.py test_generation_store.py test_store_migrations.py` | `/tmp/hippo-s1a-ladybug.log` | exit 0, 133 passed, 1 skipped |
| Ruff check and format check over the ten owned Python files | `/tmp/hippo-s1a-ruff.log` | exit 0, "All checks passed!", "10 files already formatted" |

Baseline of the same Fake regression set at `ffb075e`, before any change:
`/tmp/hippo-s1a-baseline-fake.log`, exit 0, 717 passed, 10 skipped. The counts are unchanged, and
no existing test file was edited.

Per-commit checks: commit 1, `test_knowledge_contracts.py` and `test_code_binding.py` 159 passed
(`/tmp/hippo-s1a-c1-contracts.log`) and the Fake regression set 717 passed, 10 skipped
(`/tmp/hippo-s1a-c1-regression-fake.log`). Commit 2 adds a module nothing imports, so its tree
behaves as commit 1's. Commit 3, `test_registry.py` 60 passed with
`test_use_registry_validates_records_against_the_installed_registry_only` deselected, because it
needs commit 4's registry-backed `KnowledgeObject.kind` (`/tmp/hippo-s1a-c3-registry.log`), and
the Fake regression set 717 passed, 10 skipped (`/tmp/hippo-s1a-c3-regression-fake.log`). The
commit 3 tree is the plan's fallback split point and was green on its own.

Additional runs on the final tree, not required by the brief:

| Line | Log | Result |
| --- | --- | --- |
| CK1 Fake CHECK as applied in `GATES.md` | `/tmp/hippo-s1a-ck1-fake.log` | exit 0, 255 passed, 7 skipped |
| CK1 LadybugDB CHECK as applied in `GATES.md` | `/tmp/hippo-s1a-ck1-ladybug.log` | exit 0, 135 passed |
| `test_import_order.py test_layering.py` (Fake) | `/tmp/hippo-s1a-layering.log` | exit 0, 31 passed |

Test counts per backend: Fake 110 new plus 717 regression (10 skipped); LadybugDB 133 (1 skipped)
on the plan's line. No Neo4j run: S1a changes no persisted column, and the rulebook forbids Neo4j
without a written grant.

Anyio filter: form (b) of the rulebook, `-W error -W "ignore:The anyio.abc.BlockingPortal alias is
deprecated:DeprecationWarning"`, on the Fake regression line only, exactly as plan section 5.6
spells it. Every other line ran with `-W error` alone and passed.

## Guards

- **Checksum guard.** `test_registry_model.py::test_the_vocabulary_slice_changes_no_persisted_column`
  passes on Fake and LadybugDB: `CURRENT_SCHEMA_VERSION == 7` and `MIGRATION_CHECKSUM ==
  73720e1eaeed7c148033c269de3a7e3af0d0c167fd87e580622f5c57537787f3`. Registry-backed fields are
  `Annotated[Code, AfterValidator]`, which `migrations._type` maps to `STRING` as it did the
  `Literal`s.
- **`PREDICATES` count.** `len(PREDICATES) == 32` (`test_knowledge_contracts.py`, unchanged, and
  `test_predicates_view_holds_the_non_identity_predicates_and_follows_extensions`); the registry
  holds 33 with `SAME_OBJECT_AS`. The legacy endpoint digest is
  `050f71a4c3ef7af8e0107067d8e601cc08832f4daaea01c97f885f2bf148803e`, the plan's value, checked
  on the unmodified tree before implementation and pinned by
  `test_builtin_endpoint_rules_are_the_legacy_table`.
- **Span identity.** `span-3f9d480f360a65f44ffbf25b1bb72b282ead62e65bad0f9723a614e9170cb15a`,
  checked on the unmodified tree and pinned by `test_builtin_span_identity_is_unchanged`.
- **Built-in fingerprint** at `938d657` (informational, not pinned):
  `8c13f085b48931e1920b2828e82d844fc0782d3a15c8ba9287e2f062705b9434`, equal for `REGISTRY` and
  `Registry.with_builtins()`.

## Where a ruling overrode the plan

1. **R29, evidence sources need a derivation row.** Plan section 5.2's refusal table has no such
   rule, and its fixture registers the extension source `pager_feed`. Implemented:
   - `builtin_types.EVIDENCE_CLASS_DERIVATION`, a read-only mapping from `(family, source,
     metadata_origin)` to an evidence class. It holds the eight rows of design section 4, with
     `metadata_origin` `"catalog"` or `"declaration"` for `metadata` and `None` otherwise, and the
     "any" family `reviewed` row spelled once per family (twelve keys).
   - A new refusal in the `evidence_sources` pass, after `shadows_builtin` and `duplicate_name`:
     reason `underivable_evidence_source`, message `evidence source '<name>' has no row in the
     evidence class derivation table`. It also applies to built-ins, all ten of which have rows.
   - The test fixture registers no evidence source; `AFFECTS_FIXTURE` allows `metadata`. The
     `unregistered_evidence_source` case still names `pager_feed`, which nothing registers.
   - Consequence: because the table is fixed, no extension can register a new evidence source.
2. **R16, `extension_scope()` extends in place.** Plan section 5.2 describes it twice with
   different semantics: once as snapshotting and yielding the current registry, and once as
   building a new `Registry` installed with `use_registry`. Implemented the in-place form, which
   R16 names and plan test 11 requires (`current_registry() is REGISTRY` inside the scope).
3. **R31, `LocatorKindDefinition.verifier`.** Added `verifier: Callable[..., object] | None = None`;
   S2 defines the call. The built-ins register none
   (`test_a_locator_kind_may_carry_a_verifier_and_builtins_register_none`). The fingerprint does
   not read it: a callable has no canonical JSON form, so R20's "full canonical definition" is read
   as every declarative field.
4. **R20, render text is in the fingerprint.** The plan's document already hashes `label_template`
   and `verb_phrase`; `test_fingerprint_covers_label_templates_and_verb_phrases` pins it.
5. **R22.** `SAME_OBJECT_AS` compares `(canonical_key, kind)` as Python strings, which is
   code-point order, with no collation.
6. **R2, R13, R15, R19, R23** hold as planned. No `ingest/*` file is edited, `incident` is a
   family and not a kind, no loader exists in `knowledge`, owner families are the plan's table, and
   the plan's ratified deviations are kept.

## Decisions the plan left open

- **`malformed_template`.** A label or fact template that `string.Formatter().parse` cannot parse
  (for example `{title`) is refused with reason `malformed_template` and message `<label template
  or fact template '<t>'> of object kind '<name>' is not a valid format string`. Without it,
  `register` would raise a bare `ValueError` with no reason, which D4 rules out. Fields nested
  inside a format spec are checked like top-level fields.
- **Re-entry.** Built-ins install under an `RLock`. A registry lookup made while the built-in
  vocabulary is being installed raises `RuntimeError` instead of deadlocking. The fresh-interpreter
  tests import each module first, in its own interpreter, under `-W error`.
- **Precomputed name sets.** `_State.names` holds the frozenset of each section, built once per
  registration, so `PREDICATES.__contains__` in per-arrow loops (`projection.py:966`) builds no
  set.
- **Type guards.** `register` refuses a non-`TypeExtension` with `TypeError`. `declared_families`
  and `declared_template_versions` refuse a bare string, which would otherwise iterate its
  characters. `use_registry` refuses a non-`Registry`.
- **Plan test 12's "seven lookups"** is read as the six single-name lookups plus
  `declared_template_versions`. Lookup messages quote the name as `'<name>'`.
- **Tests added beyond plan section 5.5:**
  - `test_builtin_object_kinds_carry_the_planned_family_prefix_and_key_template` pins the full D13
    table, whose part names S2's R6 programs against.
  - `test_lookups_match_names_exactly`.
  - `test_fingerprint_covers_label_templates_and_verb_phrases` (R20).
  - `test_evidence_class_derivation_table_is_the_design_table` (R29).
  - `test_a_locator_kind_may_carry_a_verifier_and_builtins_register_none` (R31).
  - `test_moved_contract_names_resolve_through_the_model`.
  - `test_parse_locator_json_names_a_missing_or_unknown_kind`.
  - `test_register_refuses` has 26 cases, one or more per refusal reason, including the positional
    `{}` field, both empty endpoint roles, `malformed_template` and `underivable_evidence_source`.
- **Commit contents.** `test_registry.py` landed in commit 3, not commit 2, because every test in
  it needs `builtin_types.py`. Committed with commit 2 it could not even be collected.

## The S2 and S3 "requires from S1" lists

- **S2 R1.** Every name imports from `hippo.knowledge.registry` (`Registry`, `REGISTRY`,
  `current_registry`, `use_registry`, `extension_scope`, `ObjectKindDefinition`,
  `PredicateDefinition`, `TypeExtension`, `LocatorKindDefinition`, `FactTemplate`, `Family`,
  `CUSTOM_FAMILY`, `RESERVED_TEMPLATE_FIELDS`, `RegistrationError`, `UnregisteredName`,
  `connector_configuration`).
- **S2 R2 to R8, R11, R12.** `Registry.frozen` is a read-only property. Every lookup miss raises
  `UnregisteredName(KeyError)`. `FactTemplate(name, version, consumes, text)` with template fields
  enforced at `register`. `declared_template_versions(kinds) -> dict[str, str]` and
  `connector_configuration(*, name, version, templates, parsers) -> dict`. The D13 key templates,
  including `provider_instance`, `catalog_instance` and `instance`. `SAME_OBJECT_AS` with its
  `checked_assertion` ordering. `EvidenceClass` gains its two classes. The five fields and
  `canonical_locator_json` are registry-validated. `extension_scope()` is in place.
- **S2 R9, R10 and S3 RS1-2 to RS1-6** are S1b's.
- **S3 RS1-1.** `current_registry()`, `use_registry()`, `extension_scope()`, `Registry.freeze()`,
  `Registry.frozen` and `Registry.fingerprint()`; no loader.
- **Design section 3 normative API.** `register(extension)` still accepts a single positional
  argument; `declared_families` is keyword-only and optional.

## Open questions

1. **Verifier access (R31).** `Registry.locator(kind)` returns the model class, as design section 3
   specifies, so no registry method returns a registered `LocatorKindDefinition` or its `verifier`.
   S2a will need one, for example `Registry.locator_kind(name) -> LocatorKindDefinition`. It was
   not added because it is outside the plan.
2. **Closed evidence sources (R29).** With a fixed derivation table, `TypeExtension.evidence_sources`
   can never register a new name. Confirm that this is intended, or say how an extension adds a row.
3. **Repeated fact template names.** Two fact templates with one name on one kind are not refused,
   and `declared_template_versions` keeps the last. The refusal table has no row for it.
4. **Derivation table key.** The key `(family, source, metadata_origin)` is this slice's choice.
   S2a imports it as it stands.
