# CDK S1b evidence: `Unit`, the widened columns and schema v8

Worker `backend-developer-3`, branch `wp/s1b`, base `95867be` (the `rag-it-all-tibs` HEAD named in
the spawn message; S1a merged at `d0bd052`). Contract: section 6 of
`ai_docs/plans/cdk-s1-registry.md`, amended by the brief's two review-amendment sections
(`ai_docs/handoffs/briefs/cdk-s1b.md`) and by rulings R2, R12, R17/R41, R23, R39, R47 and m3 of
`ai_docs/plans/cdk-rulings.md`.

**Status: in progress.** This file is written as the work lands; the sections below are final for
the commits they name.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `4020c81` | Freeze the v7 schema descriptor and index set as literals | `store/migrations.py`, `tests/unit/test_store_migrations.py`, `tests/unit/test_generation_store.py` |
| 2 | `8e261a9` | Add schema v8: units, assertion provenance, the registry fingerprint and connector classification | `knowledge/model.py`, `knowledge/lifecycle.py`, `knowledge/registry.py` (the granted entry), `store/migrations.py`, `store/knowledge.py`, `store/authorization.py`, `store/generations.py`, seven test files |
| 3 | `88984c0` | Stage, checksum and collect units with their generation | `store/generations.py`, `store/snapshots.py`, `tests/unit/test_generation_store.py`, `tests/unit/test_derived_generation_store.py` |

The plan's fallback split (stop after commit 2) was **not** used: all three commits landed. What did
not land is named under "Handed off" below.

## Granted edits outside the brief's file list

Every one was asked for and granted by the orchestrator before it was made, and each is the same
mechanical "one more schema version" change the earlier bumps made:

| Grant | Sites |
| --- | --- |
| Q1, schema-version pins | `test_generation_scoped_reads.py:838` (`[*SUPPORTED_CHECKSUMS]`) and `:845` (`schema_history()`), `test_policy_migration.py:173` and `:243` (`schema_history()`), beside the pins the plan already named in `test_policy_migration.py`, `test_knowledge_scoped_reads.py` and `test_derived_generation_store.py` |
| Q2, `AssertionVersion.source` | one `_RECORD_VOCABULARY` entry in `knowledge/registry.py`, with a `None` skip in `check_record` |
| Q4, journal enumerations that stopped at 7 | `change_journal(store, 8, delete=True)` in `test_pending_v3_recovery_never_rewrites_explicit_policy_identity`; `store._schema_history.pop(8)` in `test_v3_transform_fault_keeps_legacy_policy_and_recovery_completes` (its Fake branch only; the other branch already deletes `version >= 3`) |
| Q5(e), the v4-era store | one `ALTER TABLE Generation ADD IF NOT EXISTS registry_fingerprint STRING` after the v4 open in `test_actual_v4_upgrade_retains_original_seal` |
| Q6, the same test | one further line, `old.run(migrations.schema_steps(old, version=8)[0])`, which is exactly the `Unit` `CREATE NODE TABLE` statement: commit 3 makes `generation_checksums` compare a generation's `Unit` rows with its exact membership, and that test seals inside its v4 store. Nothing else of v8 is applied |

Q5 was first granted as option (a), seeding that test's `Generation` row v4-shaped in literal Cypher.
A direct probe showed (a) cannot work and it was never applied: the literal seed succeeds, but the
next read raises `Binder exception: Cannot find property registry_fingerprint for n`, because
`_knowledge_records` always projects the current model's columns, and the test reads that generation
throughout (claim, `generation_write`, seal, publish, `validate_generation_seal`). The orchestrator
then approved (e) and declined the general fix (projecting reads to the journaled version's
columns) as a read hot-path change for a test-only situation.

## Baseline (at `95867be`, before any change)

| Line | Log | Result |
| --- | --- | --- |
| Fake, plan section 6.5 line 1 | `/tmp/hippo-s1b-baseline-green.log` | exit 0, 277 passed, 7 skipped |
| Fake, plan section 6.5 line 2 (regression) | `/tmp/hippo-s1b-baseline-regression-fake.log` | exit 0, 484 passed, 2 skipped |

## RED

| Stage | Log | Result |
| --- | --- | --- |
| Commit 1, the frozen-history test before the literals existed | `/tmp/hippo-s1b-red-c1.log` | exit 1, `AttributeError: module 'hippo.store.migrations' has no attribute 'V7_CHECKSUM'` |
| Commit 2, every new test before any v8 code | `/tmp/hippo-s1b-red-c2.log` | exit 2, collection error `AttributeError: module 'hippo.knowledge.model' has no attribute 'Unit'` |
| Commit 2, after the model records only, before the schema and store work | `/tmp/hippo-s1b-red-c2b.log` | exit 1, 38 failed, 203 passed, 9 skipped |
| Commit 3, the four unit tests before the guards existed | `/tmp/hippo-s1b-red-c3.log` | exit 1, 3 failed, 1 passed: both new refusals "DID NOT RAISE", and the unit survived collection |

`test_units_are_exact_members_and_enter_the_evidence_checksum` passed in commit 3's RED: writing a
unit with its member, and its two rows entering the evidence representation, already worked through
commit 2's reference map. It is kept as the characterization test that commit 3 must not break; the
two refusals and the collection are what commit 3 adds.

The second commit-2 RED is the informative one: it fails on the missing v8 schema (`assert 7 == 8`,
`KeyError: 8`), the missing `Unit` table on LadybugDB, the missing
`generation_for_inputs(registry_fingerprint=...)` keyword, the missing `check_record` refusal, and —
importantly — on the v7 evidence checksum pinned in commit 1, which moved to `e3b312eb…` because the
six new `AssertionVersion` columns entered `model_dump`. Restoring `356ad2ec…` is exactly what
`generations._evidence_row` does (decision D19).

## The two checksums

| Version | Checksum | How it is produced |
| --- | --- | --- |
| 7 | `73720e1eaeed7c148033c269de3a7e3af0d0c167fd87e580622f5c57537787f3` | `V7_CHECKSUM`, hashed from the frozen `V7_DESCRIPTOR` literal; the value published at `ef143b1`, unchanged |
| 8 | `e8ae3bcf61b0617d906908ecfb8c9dc9bbd0db9b92c19f1057099618d047cc43` | `MIGRATION_CHECKSUM`, still live from the models while v8 is current; freeze it as a literal before v9 |

`SUPPORTED_CHECKSUMS` now holds 1 to 8. A generation sealed under v7 keeps its published evidence
checksum across the bump: `test_a_v7_generation_keeps_its_published_evidence_checksum` pins
`356ad2ec…` with 10 rows and passes on Fake and LadybugDB at the final tree, and
`test_unset_v8_assertion_fields_leave_the_evidence_checksum_unchanged` proves the same rule directly
by comparing against the v7 column projection. `test_set_v8_assertion_fields_enter_the_evidence_checksum`
is its converse: once `family` and `source` are set, the checksum does move.

## What schema v8 emits, per backend

| Backend | Steps | Journal |
| --- | --- | --- |
| LadybugDB | one `CREATE NODE TABLE IF NOT EXISTS Unit(...)` with the fourteen columns in model order, then eight `ALTER TABLE ... ADD IF NOT EXISTS` (`AssertionVersion.family`, `source`, `rule`, `weight DOUBLE`, `statement`, `unit_id`, `Generation.registry_fingerprint`, `Connector.classification_json`); then the classification backfill, all in one transaction | `knowledge-v8`, step 9, complete |
| Neo4j (written, not run) | `CREATE CONSTRAINT knowledge_unit_id`, then `CREATE INDEX` for `Unit.generation_id`, `Unit.passage_id` and `Unit.content_hash` (ruling R41); properties need no DDL | `knowledge-v8`, step 4, complete |
| Fake | no DDL | version 8, step 0, complete |

`V8_INDEXES` also joins `validate_physical_schema`'s declared-index loop beside v6's and v7's, so a
Neo4j store that journals v8 without those indexes is refused rather than trusted. That check has
not been executed here: this slice ran no Neo4j, as the rulebook requires.

## Guards carried from commit 1

- **The v7 literal.** `V7_DESCRIPTOR` is the descriptor published by `df05bac`, spelled per table as
  v5's literal is, and `V7_CHECKSUM = text_hash(canonical_json(V7_DESCRIPTOR))` equals
  `73720e1eaeed7c148033c269de3a7e3af0d0c167fd87e580622f5c57537787f3`, the value at `ef143b1`.
  `V7_INDEXES` is the pair `_v7_indexes()` derived; the derivation guard survives as
  `test_knowledge_scoped_reads.py:584` and `test_generation_scoped_reads.py:486`, which still check
  every `KIND_SCOPED_FIELDS` entry against the literal.
- **The v7 evidence checksum.** `test_a_v7_generation_keeps_its_published_evidence_checksum` pins
  `356ad2ec426c7d9cef6904f0d464c81cb780ed95b9465f717b2cad3ca5fa99fb` with 10 rows, captured on Fake
  at commit 1 and **equal on LadybugDB** (`/tmp/hippo-s1b-capture-c1-fake.log`,
  `/tmp/hippo-s1b-capture-c1-ladybug.log`), so no per-backend literal was needed.
- **The plan's three pinned record ids** (`assertionversion-6467ad40…`, `generation-48340495…`,
  `connector-bc33ca85…`) were recomputed on this tree before any v8 field existed and are correct as
  the plan spells them.

## Defects this slice found

1. **`_data_transform`'s v4 step could not run under v8 (product defect, fixed here).** It read
   `Artifact` and `Generation` through `store._knowledge_rows`, which projects the **current** model,
   so the v4 tables — which have never held `Generation.registry_fingerprint` — raised
   `RuntimeError: Binder exception: Cannot find property registry_fingerprint for n`. This broke
   **every fresh LadybugDB store**, not only old ones, because `migrate_store` runs v2 → v8 in order
   and the v4 data step precedes the v8 `ALTER`. It now reads the single `source_id` column by Cypher
   on the two graph backends and keeps the record read on Fake. Any later version that widens a
   record a historical data step reads has the same trap.
2. **real_ladybug 0.15.3 segfaults in `prepare` for a parameterised seed of this shape (driver
   defect, worked around).** The v7 reopen test seeds three records into a v7 store. Binding them as
   a property map (`CREATE (n:X {a: $a, ...})`) killed the interpreter inside
   `real_ladybug/prepared_statement.py:33`; so did one `SET n.field = $value` per property. The same
   statements succeed standalone in a fresh process, and a 10-parameter map raises
   `Runtime exception: Trying to a create a vector with ANY type` rather than crashing. The seed now
   writes **literal** Cypher and binds nothing, which is what every other raw seed in these tests
   already does.

## Where a ruling overrode the plan

1. **R41 (review m2) over R17 and plan section 6.3.** The `Unit` indexes are Neo4j only. v8 emits
   four Neo4j steps — the `knowledge_unit_id` constraint plus `generation_id`, `passage_id` and
   `content_hash` indexes — and nine LadybugDB steps with no index DDL, because LadybugDB 0.15.3 has
   none. `test_v8_schema_steps_are_exact_per_backend` pins both lists and asserts no LadybugDB step
   contains `INDEX`.
2. **R39 (review M1) over plan section 6.1.** The plan types `AssertionVersion.source` as
   `RegisteredEvidenceSource`; S1a-fix removed those registry-backed field types, so `source` is a
   plain `Code | None` and the refusal moved to `Registry.check_record`, which the store write path
   now calls (the brief's M1 grant). The orchestrator granted the one `registry.py` entry
   (`AssertionVersion` → `source` → "Unknown evidence source"), which skips a `None` source so every
   pre-kit row still writes.

## Deviations from the plan, recorded

1. **`knowledge/lifecycle.py` moves from commit 3 to commit 2.** Plan section 6.5 puts it in
   commit 3, but its test (section 6.4 item 16,
   `test_generation_registry_fingerprint_is_a_sha256_outside_identity_and_the_manifest`) is a
   commit-2 test, and a commit must be green on its own tests.

## GREEN on the final tree

| Line (plan section 6.5) | Log | Result |
| --- | --- | --- |
| Fake, line 1 | `/tmp/hippo-s1b-green.log` | exit 0, 301 passed, 9 skipped |
| Fake, line 2 (the regression set) | `/tmp/hippo-s1b-regression-fake.log` | exit 0, 484 passed, 2 skipped, equal to the baseline |
| LadybugDB, line 3 | `/tmp/hippo-s1b-ladybug.log` | exit 0, 220 passed, 2 skipped |
| Ruff check and format check | run inline | exit 0, "All checks passed!", every file already formatted |

Counts per backend on the final tree: Fake 301 (9 skipped) on the gate line plus 484 (2 skipped) on
the regression set, equal to the 484 (2 skipped) baseline; LadybugDB 220 (2 skipped). **No Neo4j
run:** its DDL is written and pinned by
`test_v8_schema_steps_are_exact_per_backend`, and the rulebook forbids running it without a written
grant, which this worker did not hold.

Anyio filter: form (b) of the rulebook, `-W error -W "ignore:The anyio.abc.BlockingPortal alias is
deprecated:DeprecationWarning"`, on the Fake regression line only, exactly as plan section 6.5
spells it. Every other line ran with `-W error` alone.

## Handed off, not done here

Each is specified enough to start from this file alone.

1. **B1 / R47, the fingerprint-tolerant comparisons.** Two source edits and two tests, none of them
   started, and no file below is touched by this branch:
   - `knowledge/prose_preparation.py`, inside `PlainProseInputs.__post_init__`: pass
     `registry_fingerprint=gen.registry_fingerprint` to the `generation_for_inputs(...)` call that
     builds `wanted`, so `gen.replace(coverage_json="{}") != wanted` stops refusing a fingerprinted
     generation.
   - `knowledge/staged_code.py`, in `_local`: normalize both sides of
     `if current.replace(coverage_json=gen.coverage_json) != gen`, for example by comparing
     `current.replace(coverage_json=gen.coverage_json, registry_fingerprint=None)` with
     `gen.replace(registry_fingerprint=None)`. The bundle copy is re-settled without the fingerprint
     at `code_binding.py:1037-1046`, and the field is outside identity and immutable, so ignoring it
     is sound.
   - Tests `test_a_fingerprinted_generation_passes_prose_preparation` and
     `test_a_fingerprinted_generation_passes_the_code_writer`. The fixtures to build on are
     `tests/unit/test_staged_prose_writer.py::setup` (which returns `old, job, prepared,
     credentials` and builds its `PlainProseInputs` through `tests/unit/test_managed_prose_preparation.inputs`
     and `replace`) and `tests/unit/test_staged_code_writer.py::built` (with `capture`, `prepare`
     and `install`). Put them in a file the next worker owns; `test_registry_model.py` already
     imports fixtures from other test modules this way.
2. **The two S1a-fix grants**, neither started:
   - `knowledge/registry.py`, one method `Registry.evidence_source_definition(name) ->
     EvidenceSourceDefinition`, returning the registered definition unchanged, with a test in
     `tests/unit/test_registry.py`. Per the orchestrator's Q3 answer, its docstring must say that a
     built-in carries `family=None` and `evidence_class=None` and that callers read
     `builtin_types.EVIDENCE_CLASS_DERIVATION` by `(family, source, metadata_origin)`; a single
     class cannot be returned for `metadata`, which derives two, or for `reviewed`, which spans both
     families.
   - `knowledge/projection.py`, the one-line fix so a caller's `exclusions` counter gains no
     `locator_kinds: 0` entry: the key is created by the two **reads**
     `frozenset(excluded["locator_kinds"])` (around `:490` and `:731`) on a `defaultdict`, not by
     the `.add` at `:475`, so both reads become `excluded.get("locator_kinds", ())`. Its test: a
     projection that excludes nothing leaves no `locator_kinds` key in the `Counter`.

## Open questions

1. **Closing a recorded interval needs the extension registered.** `check_record` sits on
   `put_knowledge` and `update_knowledge`, not on `_write_knowledge`, because that internal primitive
   has about twenty-five callers which write `Generation`, `MaintenanceJob`, `IndexManifest` and
   `SnapshotReference` rows — none of them in `_RECORD_VOCABULARY`. The consequence is that the
   recorded-interval closure a publication performs goes through `update_knowledge`, so closing an
   extension `AssertionVersion` (one that carries `source`) is refused in a process that has not
   registered that extension. That follows R39's "checked at store write", but it is a new
   constraint on S3's runtime and on Task 15's startup recovery, and they should confirm it.
2. **A collected generation's `unit_id` dangles.** `_collect_generation` deletes a generation's
   `Unit` rows, while a published generation keeps its `GenerationEvidenceMember` tombstones and its
   `AssertionVersion` rows. An `AssertionVersion` whose `unit_id` named a collected unit would then
   fail `_validate_knowledge`'s "Missing Unit reference" on any later `update_knowledge`, such as a
   recorded-interval close. No writer sets `unit_id` before S2/S3, so this is theirs to decide:
   either clear `unit_id` at collection or exempt it from the reference check.
