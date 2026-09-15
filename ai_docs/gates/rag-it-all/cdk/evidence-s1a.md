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

## Review amendments

Worker `backend-developer-2`, brief `ai_docs/handoffs/briefs/cdk-s1a-fix.md`, applying review
`ai_docs/reports/2026-09-15-cdk-plan-review.md` (M1, M8, m1, m5, m14, m22) as the S1a brief's
"Review amendments" section states. Follow-up commits on `wp/s1a` after `5930626`, with no rebase
and no merge. Where this section and the sections above differ, this section holds: the
registry-backed validators of `938d657` are gone (ruling R39), and R29's evidence-source rule is
amended by R40. The four open questions above are answered below: 1 and 3 by the accessors, 2 by
R40, and 4 by the documented key shape.

### Commits

| Hash | Subject | Files |
| --- | --- | --- |
| `5a7288b` | Check kinds, locators and predicates through the registry at bind and write | `knowledge/answer_evidence.py`, `knowledge/model.py`, `knowledge/projection.py`, `knowledge/registry.py`, `tests/unit/test_knowledge_contracts.py` (granted lines), `tests/unit/test_registry.py`, `tests/unit/test_registry_model.py` |
| `775c0ce` | Register extension evidence sources with their family and evidence class | `knowledge/builtin_types.py`, `knowledge/contract.py`, `knowledge/model.py`, `knowledge/registry.py`, `tests/unit/test_registry.py`, `tests/unit/test_registry_model.py` |
| `e9fccd0` | Return registered locator kind definitions and refuse repeated fact template names | `knowledge/registry.py`, `tests/unit/test_registry.py` |
| `845f529` | Add custom to ALIAS_OF's owners and pin key templates and identity predicates by test | `knowledge/predicates.py`, `tests/unit/test_registry.py`, `tests/unit/test_registry_model.py` |

The fallback split was not used. This section is a documentation-only commit after `845f529`.
`knowledge/dense.py` is untouched (see m22).

### RED and GREEN per commit

Baseline at `5930626`: the Fake regression set, 717 passed, 10 skipped
(`/tmp/hippo-s1a-fix-baseline-regression-fake.log`). "Targeted" is `test_registry.py`,
`test_registry_model.py` and `test_knowledge_contracts.py` on Fake.

| Commit | RED | Targeted GREEN | Fake regression set | LadybugDB line |
| --- | --- | --- | --- | --- |
| `5a7288b` | `/tmp/hippo-s1a-fix-red-c1.log`: exit 1, 34 failed, 81 passed. Records naming `incident_fixture` were refused at construction with `Unknown object kind`, `check_record` did not exist, `_location` raised `Unknown locator kind`, and `project_managed_graph` had no `exclusions`. On LadybugDB the read-back test failed on the store read with `Unknown object kind` (`/tmp/hippo-s1a-fix-red-c1-ladybug.log`). The rendered-view test, written after the first exclusions, raised `ProjectionError: Authorized rendered passage binding is unavailable` (`/tmp/hippo-s1a-fix-red-c1-views.log`). | `/tmp/hippo-s1a-fix-green-c1.log`: 211 passed | `/tmp/hippo-s1a-fix-c1-regression-fake.log`: 717 passed, 10 skipped | `/tmp/hippo-s1a-fix-c1-ladybug.log`: 139 passed, 1 skipped |
| `775c0ce` | `/tmp/hippo-s1a-fix-red-c2.log`: exit 2, collection `ImportError: cannot import name 'EvidenceSourceDefinition'` | `/tmp/hippo-s1a-fix-green-c2.log`: 220 passed | `/tmp/hippo-s1a-fix-c2-regression-fake.log`: 717 passed, 10 skipped | `/tmp/hippo-s1a-fix-c2-ladybug.log`: 142 passed, 1 skipped |
| `e9fccd0` | `/tmp/hippo-s1a-fix-red-c3.log`: exit 1, 6 failed, 124 passed (four `duplicate_template` cases across both files did not raise; `Registry.locator_kind` did not exist) | `/tmp/hippo-s1a-fix-green-c3.log`: 225 passed | `/tmp/hippo-s1a-fix-c3-regression-fake.log`: 717 passed, 10 skipped | `/tmp/hippo-s1a-fix-c3-ladybug.log`: 144 passed, 1 skipped |
| `845f529` | `/tmp/hippo-s1a-fix-red-c4.log`: exit 1, 1 failed, 131 passed (`ALIAS_OF`'s owners lacked `custom`); the m5 and m22 tests passed before any code change, as explained below | `/tmp/hippo-s1a-fix-green-c4.log`: 227 passed | `/tmp/hippo-s1a-fix-c4-regression-fake.log`: 717 passed, 10 skipped | `/tmp/hippo-s1a-fix-c4-ladybug.log`: 145 passed, 1 skipped |

Two intermediate runs failed and were rerun into the same log paths, so only the green runs remain.
On the commit 1 draft, the Fake regression set was 716 passed, 1 failed, because
`test_knowledge_contracts.py` expected construction-time refusal of an unknown predicate; the
granted edit below resolved it. On the commit 2 draft, the targeted run was 219 passed, 1 failed:
`REFUSALS[duplicate_name]` still expected the artifact kind message (see M8).

### GREEN lines on the final tree (`845f529`)

| Line | Log | Result |
| --- | --- | --- |
| Fake: `test_registry.py test_registry_model.py` | `/tmp/hippo-s1a-fix-final-green.log` | exit 0, 132 passed |
| Fake: the 21-file regression set of plan section 5.6 | `/tmp/hippo-s1a-fix-final-regression-fake.log` | exit 0, 717 passed, 10 skipped (equal to the baseline) |
| LadybugDB: `test_registry_model.py test_store_knowledge.py test_generation_store.py test_store_migrations.py` | `/tmp/hippo-s1a-fix-final-ladybug.log` | exit 0, 145 passed, 1 skipped |
| CK1 Fake CHECK as in `GATES.md` | `/tmp/hippo-s1a-fix-final-ck1-fake.log` | exit 0, 277 passed, 7 skipped |
| CK1 LadybugDB CHECK as in `GATES.md` | `/tmp/hippo-s1a-fix-final-ck1-ladybug.log` | exit 0, 147 passed |
| Fake: `test_import_order.py test_layering.py` | `/tmp/hippo-s1a-fix-final-layering.log` | exit 0, 31 passed |
| Ruff check and format check over the ten owned Python files and `test_knowledge_contracts.py` | `/tmp/hippo-s1a-fix-final-ruff.log` | exit 0, "All checks passed!", "11 files already formatted" |

Anyio filter: form (b) on the Fake regression line only, as before. Every other line ran with
`-W error` alone. No Neo4j run.

### Guards on the final tree

- **Checksum guard.** `test_the_vocabulary_slice_changes_no_persisted_column` passes on Fake and
  LadybugDB: `CURRENT_SCHEMA_VERSION == 7` and the v7 checksum is unchanged. The five fields are
  plain `Code` again, which `migrations._type` maps to `STRING`, and `Assertion.predicate` keeps
  `Text`.
- **`PREDICATES` count.** `len(PREDICATES) == 32`. The legacy endpoint digest `050f71a4…` still
  passes (`test_builtin_endpoint_rules_are_the_legacy_table`): m14 changes owner families, which the
  digest does not hash.
- **Span identity.** `span-3f9d480f…` still passes (`test_builtin_span_identity_is_unchanged`).
- **Built-in fingerprint** at `845f529`:
  `f3fab62f43ffd81f448e3c4148cd7991866ec7d9547cd73ff86bf219a35247b4`, equal for `REGISTRY` and
  `Registry.with_builtins()`. `775c0ce` moved it from `8c13f085…` to
  `91db988e191cf40909debb11d5cc4534a0b71bf45090e7494a31e7acf8110295`, because each evidence source
  definition entered the document. `845f529` moved it again, for `ALIAS_OF`'s owners. `5a7288b`
  and `e9fccd0` change no built-in definition and no document field.

### M1 (ruling R39)

- **Fields.** `KnowledgeObject.kind`, `Artifact.kind`, `Connector.kind`, `EvidenceSpan.locator_kind`
  and `QueryRequest.kinds` are plain `Code`; `_registered` and the `Registered*` aliases are gone.
  `Assertion.registered_predicate` is gone too, under the brief's "any other": it was a registry
  lookup that `store/knowledge.py` `_knowledge_records` runs on every read. `Assertion.predicate`
  keeps the `Text` type it had before S1a, since tightening it to `Code` would narrow what a read
  accepts.
- **Spans.** For a registered locator kind the payload is validated and canonicalized through its
  model as before, so built-in bytes and span ids are unchanged. For an unregistered kind the stored
  payload (already canonical JSON) is kept, so the row reads back with its identity. A payload with
  no kind, or with a kind that differs from `locator_kind`, is still refused at construction.
  Neither check consults the registry.
- **`Registry.check_record(record) -> None`.** It is keyed by record class name, because
  `registry.py` may not import `model`. `KnowledgeObject`, `Artifact`, `Connector`, `EvidenceSpan`
  and `Assertion` raise `ValueError` with the removed validators' messages (`Unknown object kind`,
  `Unknown artifact kind`, `Unknown connector kind`, `Unknown locator kind`, `Unknown assertion
  predicate`), chained from the `UnregisteredName` that names the value. A span's payload is also
  validated with its registered model, which raises pydantic's `ValidationError`. Other records
  pass, and a non-model raises `TypeError`. `QueryRequest` is not a record, so its `kinds` are not
  checked (open question 4).
- **Projection.** This is the orchestrator's option (a). `project_managed_graph` leaves out the
  objects, spans and assertions whose kind, locator kind or predicate the current registry lacks,
  and never raises on them. Its keyword-only `exclusions: Counter | None = None` receives, after a
  successful build, the number of distinct rows left out under `object_kinds`, `locator_kinds` and
  `predicates`. Existing callers are unchanged.
  - `_safe_vectors` skips a bound passage anchored on a left-out span. A rendered view there used
    to raise `Authorized rendered passage binding is unavailable`.
  - `_project_prose` skips an extraction whose closure reads a left-out span.
  - Neither skip is counted separately. Observations, bindings and assertions that depend on a
    left-out object drop out through the existing filters.
- **Citations.** A span of an unregistered locator kind never becomes an `OriginalCitation`, which
  the orchestrator confirmed satisfies the citations half. `answer_evidence._location` returns an
  empty label for any locator kind outside `LABELLED_LOCATOR_KINDS` (the seven built-ins) without
  consulting the registry, so an unregistered kind cannot make it raise.
- **Tests added.**
  - `test_a_row_of_an_unregistered_kind_reads_back_outside_its_registry`: all five record shapes
    go through `model_validate_json` as the store reads them, plus a `store` round trip of an
    extension object and assertion.
  - `test_check_record_refuses_an_unregistered_kind`.
  - `test_check_record_validates_a_span_payload_with_its_registered_model`.
  - `test_answer_location_is_empty_for_an_unregistered_locator`.
  - `test_projection_leaves_out_and_counts_rows_of_unregistered_vocabulary`.
  - `test_projection_keeps_those_rows_where_their_extension_is_registered`.
  - `test_projection_leaves_out_views_and_prose_anchored_on_an_unregistered_locator`.
- **Tests adapted.** Each asserted read-time refusal and now asserts a `check_record` refusal:
  - `test_registry_model.py::test_a_registered_kind_validates_knowledge_objects_and_query_kinds`
    became `test_vocabulary_fields_accept_any_code_without_a_registration`: the five fields and
    `QueryRequest.kinds` accept an unregistered code, while a malformed code or payload is still
    refused.
  - `test_registry_model.py::test_registered_artifact_and_connector_kinds_validate_their_records`
    was folded into that test and `test_check_record_refuses_an_unregistered_kind`.
  - `test_registry_model.py::test_a_refused_extension_leaves_no_name_a_record_accepts` became
    `test_a_refused_extension_leaves_no_name_check_record_accepts`, with the same cases.
  - `test_registry.py::test_use_registry_validates_records_against_the_installed_registry_only`
    became `test_use_registry_checks_records_against_the_installed_registry_only`.
  - **The one existing-test change under M1, granted by the orchestrator.**
    `tests/unit/test_knowledge_contracts.py:205-208` expected `Assertion(predicate="MADE_UP")` to
    raise `ValidationError` at construction. It now expects
    `current_registry().check_record(assertion.replace(predicate="MADE_UP"))` to raise `ValueError`
    "Unknown assertion predicate". No other line of that file changed.

### M8 (ruling R40)

- **The definition.** `TypeExtension.evidence_sources` holds `EvidenceSourceDefinition(name, family,
  evidence_class)` objects, defined in `registry.py`. `family` is the derivation table's column
  (`EvidenceFamily`: `deterministic` or `probabilistic`), not an ontology family. `evidence_class` is
  an `EvidenceClass`. That type moved to `contract.py` so `registry.py` can name it, and `model.py`
  re-exports it (pinned in `test_moved_contract_names_resolve_through_the_model`).
- **Refusals for an extension source**, checked after `shadows_builtin` and `duplicate_name`:
  - `missing_evidence_family`: "evidence source 'pager_feed' declares no family".
  - `missing_evidence_class`: "evidence source 'pager_feed' declares no evidence class".
  - `excluded_evidence_class`: "evidence source 'pager_feed' declares evidence class
    'model_inferred', which no extension evidence source may declare". The same applies to
    `human_verified`.

  A class string that is not an `EvidenceClass` is refused when the definition is constructed. A
  source absent from the built-in table is no longer refused. `missing_evidence_family` goes beyond
  the brief's wording: without a family, S2 cannot check an emitted (family, source) pair against
  the source.
- **Built-in sources** declare neither family nor class, and keep their `EVIDENCE_CLASS_DERIVATION`
  rows. `underivable_evidence_source` now applies to built-ins only
  (`test_builtin_evidence_sources_take_their_class_from_the_derivation_table`).
- **The `EVIDENCE_CLASS_DERIVATION` key** is `(family, source, metadata_origin)`, mapped to an
  evidence class:
  - `family` is `"deterministic"` or `"probabilistic"`.
  - `source` is a built-in evidence source name.
  - `metadata_origin` is `"catalog"` (a catalog or tracker API) or `"declaration"` (a document,
    manifest or declaration in a file) when `source` is `"metadata"`, and `None` for every other
    source.

  The design's "any" family row for `reviewed` is spelled once per family, giving twelve keys.
- **Lookup and fingerprint.** `Registry.evidence_source(name)` still returns the name (design
  section 3, S2 R1). The fingerprint document hashes each full source definition (R20).
- **Fixture.** `incident_extension()` again registers `pager_feed`, as
  `EvidenceSourceDefinition(name="pager_feed", family="deterministic",
  evidence_class="catalog_observed")`, and `AFFECTS_FIXTURE` allows it, as plan section 5.5 wrote
  the fixture.
- **Tests adapted for the restored fixture.**
  - `REFUSALS[duplicate_name]` now expects "evidence source 'pager_feed' repeats the registered name
    'pager_feed'", because evidence sources are checked before artifact kinds.
  - `REFUSALS[unregistered_evidence_source]` and `test_a_refused_extension_registers_nothing` use
    `pager_pull` as the unregistered source.
  - `REFUSALS[underivable_evidence_source]` is replaced by the four extension cases above.
- **Tests added.** `test_an_extension_evidence_source_registers_with_its_family_and_class`,
  `test_builtin_evidence_sources_take_their_class_from_the_derivation_table` and
  `test_fingerprint_covers_evidence_source_families_and_classes`.

### Accessors (open questions a and c)

- **`Registry.locator_kind(name) -> LocatorKindDefinition`** sits beside `Registry.locator(name)`,
  which still returns only the model. `test_a_locator_kind_may_carry_a_verifier_and_builtins_register_none`
  reads the definition and its verifier back through it, and
  `test_lookups_of_unregistered_names_raise_unregistered_name` gained a `locator_kind` case.
- **`duplicate_template`** refuses two fact templates on one kind whose names are equal or differ
  only in case: "fact template 'Severity' of object kind 'incident_fixture' repeats the template
  name 'severity'". It is checked after the label template and before each template's fields, and
  has two `REFUSALS` cases.

### m14

`ALIAS_OF`'s owner families are now every family, `custom` included
(`test_alias_of_is_owned_by_every_family_including_custom`). Spec section 6's `OWNED_BY → Team (work)`
needs `ticket` subjects, which is Task 11's work, so `OWNED_BY` is unchanged here.

### m5

`test_builtin_key_templates_match_the_identity_helpers` binds each identity helper's signature
(`inspect.signature(...).bind`) with distinct argument values, then finds which parameter each
position of the built key carries. The template's part names, in order, must equal those
parameters.

Two parts are named for the kit rather than for the parameter they carry, and the test maps them:
`repository.repository_id` carries `repository_key`'s `provider_repository_id`, and
`symbol.symbol_kind` carries `symbol_key`'s `kind`. `endpoint_key` builds its key in a different
order from its signature (`api_identity` is keyword-only and sits third), and the test checks key
order.

The templates were already right, so the test passed before any change. A separate check showed
that it refuses a `symbol` template with `kind` and `signature` swapped, which the length-only
version accepted.

### m22

`test_a_stored_same_object_as_is_absent_from_projection_and_structural_relations` publishes the
structural lane's two shared symbols, joined by `BOUND_TO` and by a stored `SAME_OBJECT_AS`
assertion with an active version and support. The results:

- The managed graph has both code nodes and no `SAME_OBJECT_AS` arrow.
- The structural session's `structural_relations` hold only `BOUND_TO`.
- No arrow or edge kind names `same_object_as`, and nothing raises.

The test passed on Fake and LadybugDB before any change
(`/tmp/hippo-s1a-fix-c4-m22-ladybug-before.log`). `projection.py` skips any predicate whose
`traversal_permitted` is false before it builds a `StructuralRelationEvidence`, so `dense.py:197`
is never reached with an identity predicate. The granted `knowledge/dense.py:182-198` edit was
therefore not used, as the orchestrator agreed.

### m1

No change. `extension_scope()` extends the current registry in place (R16), as implemented in
`dc10058` and pinned by `test_extension_scope_restores_the_registry_byte_for_byte`.

### The S2 and S3 "requires from S1" lists, as amended

- S2 R1 gains `EvidenceSourceDefinition` among the names `hippo.knowledge.registry` exports.
  `Registry.check_record` and `Registry.locator_kind` are new.
- The earlier line "The five fields and `canonical_locator_json` are registry-validated" no longer
  holds. The five fields are plain codes. `canonical_locator_json` still validates through the
  registry and refuses an unregistered kind, so the binder may call it.

### Open questions after the amendments

1. **Evidence source accessor.** `Registry.evidence_source(name)` returns only the name, so no
   public method yet returns an extension source's family and class. This is the same shape as the
   earlier question 1. S2 should name the accessor. Under R40, S2 section 8.3's refusal of "a
   registered source outside the table" must also change.
2. **Mixed rendered views.** A rendered view anchored on a registered span whose closure also reads
   a left-out span still raises `Rendered passage lineage differs from the authorized proof`. No
   writer produces such a view today, and a test needs S2's rendering rules.
3. **Coverage surface.** `exclusions` is filled only when a caller passes a `Counter`, and no caller
   does yet. Where query coverage shows the counts is S3's or Task 15's decision.
4. **`QueryRequest.kinds`.** A query naming an unregistered kind is accepted and matches nothing.
   `check_record` covers records only; a query route that should refuse such a query needs its
   own check.
5. **Nested model names.** The S1a worker's question (e), that a nested attribute model's class
   name enters the fingerprint through `$defs`, was outside this brief and is unchanged.
