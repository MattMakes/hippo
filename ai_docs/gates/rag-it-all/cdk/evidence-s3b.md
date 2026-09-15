# CDK S3b evidence: the generic staged writer, the connector profile, authority admission and the moved helpers

Worker `backend-developer-7`, branch `wp/s3b`, base `89ff6ac` (the `rag-it-all-tibs` HEAD named in
the spawn message, after S1a `d0bd052`, S2a `96eda9f` and S1b `9e5b93c` merged). Contract: Task S3b
of `ai_docs/plans/cdk-s3-runtime.md` section 12, with sections 4.4–4.6, 7 and 8, amended by rulings
R38, R39, R47/B1 and review finding m10 (`ai_docs/handoffs/briefs/cdk-s3b.md`).

## Commit

| Hash | Subject | Files |
| --- | --- | --- |
| `7941635` | Add the generic staged writer, the connector generation profile and connector build authority (CDK S3b) | `knowledge/staged_records.py` (new), `knowledge/staged_code.py`, `knowledge/generation_profiles.py`, `knowledge/build_authority.py`, `ingest/build_run.py`, `ingest/code_generation.py`, `tests/unit/test_staged_records.py` (new), `tests/unit/test_generation_profiles.py`, `tests/unit/test_build_authority.py`, `tests/unit/test_build_run.py` |

## Baseline (at `89ff6ac`, before any change)

| Line | Log | Result |
| --- | --- | --- |
| Fake, plan step 3 (the regression set) | `/tmp/hippo-s3b-baseline-regress.log` | exit 0, 290 passed, 1 skipped |

No file in the regression set imports `fastapi.testclient` at module level, so every line below ran
with `-W error` alone. The rulebook's form (b) anyio filter was **not** needed and was not used.

## RED

| Log | Result |
| --- | --- |
| `/tmp/hippo-s3b-red.log` | exit 1, 17 failed, 131 passed, 1 skipped, 8 errors |

Every failure is "the feature is missing", and nothing else moved:

- 6 failures and all 8 errors in `test_staged_records.py`: `ModuleNotFoundError: No module named
  'hippo.knowledge.staged_records'`, surfaced through the file's `writer()` helper as
  `Failed: Generic staged record writer is missing`;
- 5 failures in `test_generation_profiles.py`: `module 'hippo.knowledge.generation_profiles' has no
  attribute 'CONNECTOR_PROFILE'`;
- 6 failures in `test_build_authority.py`: `'connector' in frozenset({'archive', 'file', 'repo',
  'text'})` and `module 'hippo.knowledge.build_authority' has no attribute 'CONNECTOR_SCOPE'`;
- 2 failures in `test_build_run.py`: `module 'hippo.ingest.build_run' has no attribute
  'published_receipt'`.

## GREEN

| Line | Log | Result |
| --- | --- | --- |
| Fake, plan step 2 line 1 | `/tmp/hippo-s3b-green.log` | exit 0, 159 passed, 1 skipped |
| LadybugDB, plan step 2 line 2 | `/tmp/hippo-s3b-ladybug.log` | exit 0, 160 passed |
| Fake, plan step 3 (regression) | `/tmp/hippo-s3b-regress.log` | exit 0, 290 passed, 1 skipped — **equal to the baseline** |
| Ruff check and format check, all ten changed files | run inline | exit 0, "All checks passed!", "10 files already formatted" |

Counts per backend: Fake 159 (1 skipped) on the S3b line plus 290 (1 skipped) on the regression set;
LadybugDB 160 (0 skipped). The one Fake skip is
`test_a_sealed_connector_generation_survives_ladybug_close_and_reopen`, which the plan marks
"skipped unless `HIPPO_TEST_STORE=ladybug`"; it runs and passes on the LadybugDB line, which is why
that line has one more test. **No Neo4j run:** the rulebook forbids it without a written grant,
which this worker did not hold.

### Wider sweep, beyond the plan's regression line

Every other test module that names `build_authority`, `generation_profiles`, `build_run` or
`staged_code`, plus the store and registry suites the three changed modules sit under:

| Log | Result |
| --- | --- |
| `/tmp/hippo-s3b-sweep.log` | exit 0, 555 passed, 4 skipped |

Files: `test_code_capture_acceptance`, `test_code_projection`, `test_ingest_concurrency`,
`test_knowledge_scoped_reads`, `test_generation_scoped_reads`, `test_local_workspace_membership`,
`test_managed_pipeline_activation`, `test_managed_source_lifecycle`, `test_multi_generation_support`,
`test_query_scoped_reads`, `test_rag_store_capabilities`, `test_transaction_ownership`,
`test_generation_store`, `test_derived_generation_store`, `test_managed_prose_preparation`,
`test_managed_input_binding`, `test_store_knowledge`, `test_registry`.

## The promoted names (review finding m10)

`staged_records.py` shares `staged_code`'s fenced core instead of copying it, so the four private
names it reuses are now public in their owning module, with the private spellings still bound for
that module's own callers:

| Public name | Private name kept bound | What it is |
| --- | --- | --- |
| `staged_code.fenced_epochs` | `_epochs` | the authorization/suppression epoch comparison |
| `staged_code.fenced_local` | `_local` | the `generation_write` context that brackets every batch |
| `staged_code.DependencyGroup` | `_Group` | one group's records, probes and shared payloads |
| `staged_code.immutable_native` | `_immutable_native` | the canonical-payload comparison that refuses an overwrite |

`CLEANUP`, `PAYLOAD_CEILING_BYTES` and `ResumePlan` were already public and are imported unchanged.
The pairing is pinned by `test_staged_records.py::test_staged_records_imports_nothing_from_connectors`,
which also asserts that no import line of `staged_records.py` names `connectors` and that no
`hippo.connectors` module is loaded.

**`ingest/provenance.py._lines` was not touched.** m10 lists it beside the `staged_code` names, but
that half of the finding belongs to S2's `§8.4`; nothing in S3b's sections 4.4–4.6, 7 or 8 reads it,
and no file of this branch imports it.

## Where a ruling, the brief or the design overrode the plan — and where the plan won

1. **R47 / B1 had not landed at this base (brief override, no work done).** The brief says "S1b
   already made the two generation comparisons fingerprint-tolerant; do not redo them". At `89ff6ac`
   they are **not** made: `staged_code.py:310` still reads
   `if current.replace(coverage_json=gen.coverage_json) != gen:` with no fingerprint normalization,
   `prose_preparation.py` still calls `generation_for_inputs` without `registry_fingerprint`, and the
   HEAD commit `89ff6ac` is titled "Brief the S1b follow-up: **B1**, …" — it briefs the work rather
   than landing it. S3b needs neither edit and made neither: the connector bundle carries the stored
   generation itself, so both sides of `fenced_local`'s equality hold the same
   `registry_fingerprint`, which `test_connector_profile_rederives_identity_with_the_registry_fingerprint`
   and the whole writer suite exercise with a fingerprinted generation. **The follow-up worker still
   owns B1.**
2. **Design §7 step 7 lists alias candidates and, for code, native bindings; plan §4.4 lists
   neither (plan wins, per the brief).** `RecordBundle` has no `aliases` or `bindings` field and
   plan §7.1 has `_inventory` refuse `NativeBinding` outright, which the writer does. An `Alias` in
   `evidence_members` is refused by the bundle's closure check, correctly, because no field carries
   the record. Adding `aliases: tuple[k.Alias, ...] = ()` with a group of its own is additive and
   costs one group in `_groups`, one entry in `scoped` and one line in `_inventory`; **S3c or a later
   slice should decide whether the kit needs it in v1.** The brief's GOAL sentence copies the design's
   wording, so this is recorded as a deviation from the GOAL prose, not from the contract.
3. **`registry_fingerprint` in the identity re-derivation is a no-op for existing profiles (plan
   §7.2 applied literally).** §7.2 asks the connector branch to pass
   `registry_fingerprint=generation.registry_fingerprint` to `generation_for_inputs`. It is passed on
   **both** paths, because `generation_for_inputs` never hashes the field and
   `validate_generation_profile` compares only `.id` and `.manifest_hash`: a pre-kit generation
   carries `None`, which is the parameter's default, so no prose or code identity moves.
   `test_connector_profile_rederives_identity_with_the_registry_fingerprint` pins S1 D21 directly by
   re-deriving the same generation without the fingerprint and asserting the id and manifest hash are
   equal.
4. **`PLANNED_POLICY_SCOPES` is shared across kinds (plan §7.3 applied literally; flagged).** The
   plan says the tuple "gains `CONNECTOR_SCOPE`", and it is one module-level tuple consulted for
   every source kind, so a `text` source could now plan a `source:{id}:connector-v1` grant. That is
   what the plan asks for and what `test_a_planned_policy_may_carry_the_code_scope_key` and
   `test_connector_authority_admits_provider_and_unknown_policies_of_its_connector_only` now pin. If
   the scopes should be partitioned by source kind, that is a one-line change and a reviewer's call.
5. **The connector authority's refusal message is new wording.** §7.3 specifies the checks, not the
   text. A connector input that is not an active input of its connector refuses with
   `Accepted original is not an active input of this connector`; the inventory manifest refuses with
   `Connector inventory manifest must be a local artifact`. The pre-kit path keeps
   `Accepted original is not an active local input` byte for byte, which
   `test_text_file_repo_and_archive_authority_is_unchanged` pins for all four legacy kinds.
6. **`build_run` defers its `generation_profiles` import.** `prior_receipt` needs `embedding_mode`
   and `validate_generation_profile`. Importing them at module level made
   `test_the_shared_run_loads_without_either_coordinator` fail: `generation_profiles` reaches
   `input_binding`, the one knowledge module `test_layering.ALLOWED` lets import `ingest`, so the
   reader stack loaded with the shared run state. The import is deferred into the function, exactly
   as `staged_code._accepted` defers the same pair.

## What the writer does that the plan's prose does not spell out

- **`_write_batch` writes a batch in order, not bucketed by type.** `staged_code._write_batch` sorts
  a batch into knowledge records, dense rows, native rows and bindings and writes each bucket in
  turn. That cannot work here: `put_knowledge` refuses a `Unit` whose `Passage` row is absent
  (`store/generations.py:700`) and an `AssertionVersion` whose `Unit` is absent
  (`store/knowledge.py:75`), and both rows are in the same group.
  `test_groups_write_passages_before_units_and_units_before_versions` records the actual write order
  and asserts the three orderings.
- **The probe carries a `unit` flavour beside `exact`.** §7.1 names the `Unit` scoped read for
  `_inventory`; the probe needs it too, because a unit written before its member is a generation-scoped
  orphan the `exact` flavour cannot see. Proved by the third case of
  `test_resume_fails_closed_on_a_partial_group_a_changed_payload_or_an_orphan_row`.
- **`_groups` keys the derived stage on the derived record, not the view** (plan §7.1 item 5), so a
  derived record with several views is one group; `staged_code` keys it per view.

## Fixture notes for S3c and any later worker

`tests/unit/test_staged_records.py::world` is the hand-built connector generation; `bundle_of` is the
`RecordBundle` S3c's `_bind` will produce. Four traps it had to work around, all of them real
constraints on the runtime:

1. **A remote `Artifact`'s identity is scoped by `provider_instance`, not by its Source**
   (`Artifact.identity_parts`). Two connector worlds sharing one instance mint one artifact id for
   two Sources, and the second write refuses with "Immutable record already exists". Each `world()`
   call takes its own instance from a counter; `test_build_authority.connector_world` does the same.
2. **An enabled provider `Connector` is refused in open mode** ("Provider connectors require a
   signed-in installation"), so the fixture creates one operator user first.
3. **A sealed generation cannot be reclaimed or written.** `_admit_build` wants `staging` or
   `failed`, and `generation_write` refuses a `ready` one with "Stale build lease, fence, or
   generation state". Tests that need a written-but-unsealed generation drive `_write_batches` and
   `_write_batch` directly instead of `write_staged_records`.
4. **`AccessPolicy` refuses an expiry that does not follow its verification**, so an already-lapsed
   provider policy needs `verified_at` further back than `expires_at`.

`test_generation_profiles.py` imports `tests.unit.test_staged_records` for that fixture, the way
`test_registry_model.py` imports fixtures from other test modules, so one hand-built connector
generation exists in the tree rather than two that can drift.

## Existing tests changed, and why

| Test | Change |
| --- | --- |
| `test_generation_profiles.py::test_the_accepted_generation_profile_names_are_closed` | `GENERATION_PROFILES` is now the three-tuple the plan's §4.5 specifies |
| `test_build_authority.py::test_a_planned_policy_may_carry_the_code_scope_key` | `PLANNED_POLICY_SCOPES` is now the three-tuple §7.3 specifies |
| `test_generation_profiles.py::prepared` | gains one `fault="remote_original"` branch (a `Connector` row and a remote artifact), used only by the new `test_plain_prose_and_code_profiles_are_unchanged` |

No other existing test was edited, and no test was deleted or weakened.

## Open questions for the orchestrator

1. **Aliases in `RecordBundle` (deviation 2 above).** The design names alias candidates as part of
   what the generic writer stages; the plan's `RecordBundle` has no field for them. Should S3c carry
   them, or is that a later slice's?
2. **`PLANNED_POLICY_SCOPES` shared across source kinds (deviation 4 above).** Confirm the plan meant
   one shared tuple rather than a per-kind set.
3. **S1b's own open question 1 still stands for this runtime.** `check_record` sits on
   `put_knowledge`/`update_knowledge`, so closing a recorded interval on an extension
   `AssertionVersion` is refused in a process that has not registered that extension. S3b writes
   versions through `put_knowledge` under the frozen current registry, so it is unaffected; the
   recorded-interval close a *publication* performs is S3c's and Task 15's to confirm.
4. **S1b's open question 2 is now S3c's.** A collected generation deletes its `Unit` rows while a
   published `AssertionVersion` keeps `unit_id`. S3b is the first writer that sets `unit_id`, so the
   decision — clear it at collection, or exempt it from the reference check — is due before a
   connector generation is ever collected.
