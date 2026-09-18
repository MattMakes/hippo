# CDK S5a evidence: the coordinator lane and the local prose connector

Worker `backend-developer-11`, branch `wp/s5a`, base `2a9913a` (the `rag-it-all-tibs` HEAD carrying
S1a, S2a, S1b, S1b-fix, S3a, S4c and S4c-fix). Contract: the S5a steps of
`ai_docs/plans/cdk-s5-port.md` section 7, with sections 3, 4.1, 5, 6 and 8 as the contract, amended
by the rulings the brief `ai_docs/handoffs/briefs/cdk-s5a.md` names — R1, R2, R3, R5, R43/M14, R47,
R54/M11, R65, R67 and m9 — and by `ai_docs/reports/2026-09-15-cdk-plan-review.md`. Gate: CK5.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `864500e` | Dispatch the managed prose build through the local connector and the coordinator lane (CDK S5a) | `src/hippo/connectors/lanes.py`, `src/hippo/connectors/local/{__init__,connector,types}.py`, `tests/fakes/connector_parity.py`, `tests/unit/test_connector_local.py` (new); `src/hippo/ingest/prose_generation.py`, `src/hippo/ingest/managed_activation.py`, `src/hippo/connectors/loader.py`, `tests/unit/test_connector_loader.py`, `tests/unit/test_import_order.py`, `tests/unit/test_layering.py` (modified) |
| 2 | (this commit) | Record the S5a evidence | this file (new) |

`loader.py` and `tests/unit/test_connector_loader.py` are outside the brief's "own" list and were
granted by the orchestrator during implementation, for the one change described under "Override 3"
below. Every other file is on the brief's list.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| Section 9's S5a Fake line, minus the file that does not exist yet, on the unmodified tree | `/tmp/hippo-cdk-s5a-baseline.log` | exit 0, 205 passed, 3 skipped |
| Section 8's S5a tests, the R43 test and the R54 pins, before any source file | `/tmp/hippo-cdk-s5a-red.log` | exit 1, 32 failed, 32 passed |

The 32 RED failures are the 27 cases of `tests/unit/test_connector_local.py`, the two appended
`test_import_order.MODULES` entries, and the three R54 pins in `tests/unit/test_layering.py`. The
baseline's four files are the same four the GREEN line carries, so 205 + 32 = 237 is the GREEN
count below, and no existing case changed its result.

The parity cases fail RED on a stated property rather than on a missing module, because before the
switch both worlds call the same coordinator and would be trivially equal: `_drive` asserts that
`managed_activation.run_coordinator_lane` is the lane's own function, and that a published runtime
build carries `current_registry().fingerprint()`. Both are false at `2a9913a` and true after the
switch, so a parity comparison can never pass by comparing world A with itself.

## GREEN

| Line | Log | Result |
| --- | --- | --- |
| Section 9's S5a Fake line: `test_connector_local.py test_prose_generation.py test_managed_pipeline_activation.py test_import_order.py test_layering.py` | `/tmp/hippo-cdk-s5a-green.log` | exit 0, 237 passed, 3 skipped |
| Section 9's S5a LadybugDB line: `test_connector_local.py` | `/tmp/hippo-cdk-s5a-ladybug.log` | exit 0, 27 passed |
| Kit regression (not a gate line): the seven `test_connector_*.py` files S1–S4 own | `/tmp/hippo-cdk-s5a-kit-regression.log` | exit 0, 202 passed |
| The DONE WHEN's "unchanged" pair on its own: `test_prose_generation.py test_managed_pipeline_activation.py` | `/tmp/hippo-cdk-s5a-unchanged.log` | exit 0, 173 passed, 3 skipped |
| Ruff `check` then `format --check` | `/tmp/hippo-s5a-ruff.log` | exit 0 and exit 0 |

Every line above was re-run against the committed tree `864500e`, after the Ruff formatting pass
and after the retry test was tightened, so no figure here is from an earlier working tree.

Counts per backend: **Fake** 237 passed / 3 skipped on the S5a line (205 baseline + 32 new) and 202
passed on the kit regression; **LadybugDB** 27 passed on `test_connector_local.py`. **No Neo4j run**
— the rulebook forbids one without a written grant, and the plan's section 9 makes the Neo4j parity
of the connector files root-owned.

Every command carries `-W error` alone, with no filter appended: none of the files on either line
imports `fastapi.testclient` at module level, so form (b) of the fleet rules is not needed and no
warning was suppressed. No ini-wide `filterwarnings` was added.

`tests/unit/test_prose_generation.py` and `tests/unit/test_managed_pipeline_activation.py` pass
**unchanged** — neither file is modified in this branch, and `git show --stat` proves it.

## The parity comparison

`tests/fakes/connector_parity.py` builds each world on its own data directory and its own store of
the selected backend, **one after the other**, so the code shape is the same for a backend that
holds two stores (Fake, LadybugDB) and one that serves a single database per process (Neo4j, which
the helper resets between worlds but which is not exercised here). Both worlds pin, identically:

- the store clock (`store._generation_clock = lambda: INSTANT`);
- `new_id` in every module that binds it — `hippo.store.base`, `hippo.store.memory`,
  `hippo.store.ladybug` and `tests.fakes.fake_store` — to one counter, reset per world;
- `managed_activation.new_operation_id` to a counter, so a refresh is a second build with its own
  identity rather than a replay of the first operation's;
- the same signed-in builder, membership and reviewed mapping authority, and the same mock model
  `Runtime` from `tests/unit/test_prose_generation.py`.

World A is `pipeline.add_text` / `add_upload` with jobs held, then the coordinator called with the
arguments `run_managed_build` built at `2a9913a`, copied verbatim into
`connector_parity.pre_kit_prose_build`. World B is the same `add_*` call, then
`managed_activation.run_managed_build(ctx, source_id=…, actor=…, operation_id=…, job_key=…)` — the
call `pipeline._run_managed_indexing` makes at `pipeline.py:361-367`.

`published_snapshot` compares, and requires equal:

| # | What | Where |
| --- | --- | --- |
| 1 | `store.generation_checksums(generation_id)`, element by element | `"checksums"` |
| 2 | every `GenerationMember`, `GenerationEvidenceMember` and `NativeBinding`, and every record they reference, walked as `generation_checksums` walks them | `"closure"` |
| 3 | native `Passage`, `Symbol`, `DataObject` and `Commit` rows, canonical and sorted; and `_native_relationships(generation_id=…)` | `"native"`, `"relationships"` |
| 4 | the `Generation` row's dump **without** `registry_fingerprint` (so `coverage_json`, `manifest_hash`, `parser_version`, `linker_version`, `embedding_profile`, `created_at`, `published_at`, `status`) | `"generation"` |
| 5 | the accepted manifest revision's `metadata_json`, which holds the configuration | `"accepted_manifest"` |
| 6 | `IndexManifest` rows for the generation | `"index_manifests"` |
| 7 | `IndexEvent` rows on `id`, `kind`, `generation_id`, `aggregate_id`, `sequence`, `dedupe_key`, `created_at` | `"index_events"` |
| 8 | the `BuildReceipt`, all seven fields | `"receipt"` |
| 9 | the content-addressed raw object listing | `"raw_objects"` |

**Result: the only difference the comparison finds anywhere is `Generation.registry_fingerprint`.**
Measured directly on the `first_text` scenario before the closure walk was narrowed: every one of
the nine entries was equal except `"closure"`, whose single differing element was the `Generation`
row itself, `null` in world A and
`f3fab62f43ffd81f448e3c4148cd7991866ec7d9547cd73ff86bf219a35247b4` in world B. `coverage_json`,
`manifest_hash`, the spans, passages, receipts, index events and raw objects were byte for byte the
same. `generation_checksums` does not hash the fingerprint, because it skips the `Generation` row
(`store/generations.py:1010`), so the three representation checksums are equal too.

`test_registry_fingerprint_is_the_only_generation_field_that_differs` states this as an assertion
over the whole row dump: `{key for key in a if a[key] != b[key]} == {"registry_fingerprint"}`.

Outside the comparison, as section 6 names them: `MaintenanceJob` rows (the `uuid4` lease owner),
`IndexEvent.payload_json` (the same credentials), Source-row presentation and its `now_iso`
timestamps, and store meta epochs. `test_the_runtime_path_writes_no_connector_or_sync_state_row_and_no_connector_id`
proves the comparison hides no extra row: the runtime path writes no `Connector` and no `SyncState`
row, and sets no `Artifact.connector_id` (ruling R5).

## Overrides and deviations

**Override 1 — the lane's refusal is `LaneRefused`, not `ManagedDispatchError`.** Plan section 3.2
step 1 says `run_coordinator_lane` refuses with `managed_activation.ManagedDispatchError`. Review
M11 and ruling R54 say `lanes.py` raises its own `LaneRefused`, because importing the dispatch would
close the one `ingest` → `connectors` edge into a cycle. **The ruling wins.** `LaneRefused` is a
`ValueError` outside `managed_activation.FAILURES`, so a refusal presents as the unknown code — which
is the right shape for a kit mistake, and which the ported connectors cannot produce: their
descriptors are static and their inventories are always complete.

**Override 2 — `ConnectorCapabilities.inventory` is `True`, not false.** Plan section 4.1 says
"Capabilities are all false". The `inventory` field did not exist when the plan was written; it
means exactly "`list_changes(None)` walks the whole partition and marks its last page complete",
which is precisely what `run_coordinator_lane` requires of this connector and what it does.
Declaring it false would deny the behaviour the lane depends on. Recorded here; S5b owns
`local/connector.py` after this merge and can narrow it with the `check_capture` test (R67) if the
kit reads it differently.

**Override 3 — `loader.py`: a built-in connector kind is not an in-repo candidate.** The plan's
mandated layout (`connectors/local/__init__.py` + `connector.py`) makes `local` an in-repo connector
*package* by S4c's shape rule (`loader.PACKAGE_FILES`), and `load_registry` subtracts packaged names
from the built-in list. That took `local` off the built-in entries and failed
`test_connector_loader.py::test_built_in_connector_kinds_are_listed_with_their_enablement`; worse, as
an in-repo entry `local` would report `registered=False, enabled=False` forever, because ruling R5
forbids a `Connector` row for it until Task 15, so a built-in vocabulary would read as unloaded. The
orchestrator granted `loader.py` and `tests/unit/test_connector_loader.py` for this only and chose
option (a): `_in_repo_candidates` now skips a directory whose name is a built-in connector kind, so
`local` (and S5b's `git`) keeps exactly one entry, the built-in one. S4c's assertion is unchanged;
the new case is `test_a_package_named_after_a_built_in_kind_keeps_its_built_in_entry`. Entry points
keep their existing shadowing behaviour — only in-repo packages are affected.

**Override 4 — the closure walk keeps `Artifact` and `AccessPolicy`, and skips `Generation`.**
Section 6's comparison 2 says the closure is walked "as `generation_checksums` walks them", which
skips `Artifact`, `AccessPolicy`, `Generation`, `Source` and `Workspace`. The helper skips
`Generation` (comparison 4 compares it separately, minus the one allowed difference), `Source` and
`Workspace` (presentation and wall time, which section 6 puts outside), and **keeps** `Artifact` and
`AccessPolicy`: they are immutable inputs and they must agree, so comparing them strengthens the
proof rather than weakening it.

**Override 5 — the lane's build callable returns `Any`, not `BuildReceipt`.** Plan section 3.2
types it `Callable[[ChangePage, str], BuildReceipt]`. `BuildReceipt` lives in
`hippo.ingest.build_run`, which R54 does not forbid, but the lane never reads the value: it returns
whatever the coordinator returned, so that `map_build_failure` and `record_build_receipt` see
exactly what they saw before the port. Typing the return `Any` keeps the kit from depending on an
ingest record it does not interpret. The switch's own closure is annotated `-> BuildReceipt`, which
is where the type actually holds.

**Deviation carried from the plan, not introduced here — `descriptor.kinds` is the superset both
lanes write.** The local descriptor declares the code lane's object kinds (`repository`, `file`,
`symbol`, `commit`, `table`, `column`, `resource`), the artifact kinds `file`, `manifest`,
`repository` and `history_event`, and the locator kinds `file_lines` and `field`, because plan
section 4.1 makes the descriptor the exact set "the two lanes write for text, file and archive
sources" and section 4.2 records that the local descriptor carries `history_event`. S5a can only pin
the prose subset, so `test_local_descriptor_covers_every_record_the_lanes_write` asserts that the
prose lane's published artifact and locator kinds are **covered by** the declaration; S5b pins the
code subset. `descriptor.validate_against(current_registry())` passes: every declared name is a
built-in.

**Not a deviation, recorded for the reader — the archive and code-file branches raise.**
`LocalConnector.list_changes` and `_member` raise `NotImplementedError` naming S5b for an archive or
a code file. Nothing reaches them in this slice: `run_managed_build` routes a code source to
`_run_code_build`, which is untouched and does not use the connector until S5b. `probe` is complete
for every eligible kind now, because
`test_local_probe_family_agrees_with_the_dispatch_for_every_eligible_kind` compares it against
`managed_activation.is_code_source` for `text`, a prose `file`, a code `file` and an `archive`.

## What landed

| File | Change |
| --- | --- |
| `src/hippo/connectors/lanes.py` (new, 100 lines) | `CoordinatorLane`, `run_coordinator_lane`, `LaneRefused`. Refuses a descriptor that does not declare `derivation="coordinator_lane"`, does not declare the lane's family, declares predicates or parsers, or names vocabulary the registry lacks; refuses an incomplete inventory; then returns `lane.build(page, registry.fingerprint())` with every exception propagating unchanged |
| `src/hippo/connectors/local/connector.py` (new, 193 lines) | `LocalSourceConfig`, the `local` descriptor, and `probe` / `list_changes` / `fetch` / `fetch_policy` over the text and prose-file branches |
| `src/hippo/connectors/local/types.py` (new) | `EXTENSION = TypeExtension()` — the connector registers no vocabulary (ruling R46 requires the field) |
| `src/hippo/connectors/local/__init__.py` (new) | The package marker, exporting `Connector` for the kit's package convention |
| `src/hippo/ingest/prose_generation.py` | `build_plain_source(..., registry_fingerprint: str | None = None)`; `_generation` sets it on a new generation and adopts the stored value on an existing one, exactly as it adopts `created_at` |
| `src/hippo/ingest/managed_activation.py` | The prose branch of `run_managed_build` is now the lane; the R43 refusal of `kind="connector"`; the three `hippo.connectors` imports; a module-docstring paragraph recording the CK5 hand-off and R54 |
| `src/hippo/connectors/loader.py` | Override 3 |
| `tests/fakes/connector_parity.py` (new, 398 lines) | The two worlds and `published_snapshot` |
| `tests/unit/test_connector_local.py` (new, 27 cases) | Section 8's twenty S5a names (25 cases, two of them parametrized), the R43 test, and one that states a rule section 8 leaves unnamed (`test_the_accepted_configuration_is_byte_for_byte_the_pre_kit_configuration`) |
| `tests/unit/test_layering.py` | The three R54 pins |
| `tests/unit/test_import_order.py` | `"hippo.connectors.lanes"` and `"hippo.connectors.local.connector"` appended to `MODULES` |
| `tests/unit/test_connector_loader.py` | One case for Override 3 |

## A finding: `_generation`'s adoption branch is not observable on any S5a path

Plan section 3.2 says `_generation` "sets the fingerprint on a new generation and adopts the stored
value for an existing one, exactly as it adopts `created_at`". That is implemented. It is also, on
every path S5a can reach, **unfalsifiable**, and this was measured rather than assumed: deleting
`registry_fingerprint=existing.registry_fingerprint` from the adoption and re-running
`tests/unit/test_connector_local.py` on Fake leaves 27 passed. Two reasons, both in reviewed code:

- `_install` writes the generation only when it is absent
  (`prose_generation.py:360-361`, `if store._knowledge_get("Generation", gen.id) is None`), so a
  retry never re-puts an existing `Generation` and never meets `put_knowledge`'s "Immutable record
  already exists with different contents";
- `prose_preparation`'s recomputation passes `registry_fingerprint=gen.registry_fingerprint` into
  `generation_for_inputs` and compares the result with `gen` (ruling R47, `:164-176`), so the
  fingerprint cancels on both sides of that equality whatever it holds.

`test_a_retried_prose_generation_keeps_its_stored_registry_fingerprint` therefore pins the property
that *is* observable, under a registry that genuinely differs (a bare `Registry.with_builtins()`
fingerprints identically to the process registry — freezing does not move a fingerprint — so the
test registers a `parity_probe` artifact kind first and asserts the difference as a precondition): a
rebuild under a different process registry takes the prior-receipt path, lands on the same
generation id, and leaves the stored record equal in every field. The adoption itself stays in, as
the plan requires and as correctness requires the moment any path does re-put a generation. **S5b
should re-check this for the code lane**, where `_instant` adopts a *reclaimable* generation: a
reclaim may well rewrite the row, which would make the same branch observable there.

Related, for a reader grepping for a code: the `capture_too_large` scenario of
`test_a_failed_runtime_build_presents_the_pre_kit_public_failure` presents as `source_too_large`
(the `TooLarge` row of `FAILURES`), not as a code spelled `capture_too_large`. The parameter id is
the plan's scenario name; the test compares the whole presentation — exception type, the
`ManagedFailure` fields, and the source row's `status`/`stage`/`error` — between the two worlds.

## The rulings, checked

| Ruling | Where it is satisfied | Pinned by |
| --- | --- | --- |
| R1 — coordinator lanes; `capabilities.derivation="coordinator_lane"` | `lanes.py`, `local/connector.py` `DESCRIPTOR` | `test_local_descriptor_declares_no_templates_parsers_predicates_or_emit` |
| R2 — S5a owns `prose_generation.py` | one keyword argument, one `_generation` change | `test_build_plain_source_defaults_registry_fingerprint_to_none` |
| R5 — no `Connector` or `SyncState` row | the lane writes neither | `test_the_runtime_path_writes_no_connector_or_sync_state_row_and_no_connector_id` |
| R43 / M14 — `kind="connector"` refused with `ManagedDispatchError` | `run_managed_build`, among the refusals, before `ingress_file` | `test_a_connector_source_reindex_is_refused_by_dispatch` |
| R47 — S1b-fix owns the fingerprint-tolerant comparisons | `knowledge/prose_preparation.py` and `staged_code.py` untouched here | the refresh and retry parity cases pass |
| R54 / M11 — one `ingest` → `connectors` edge | `managed_activation` alone imports the kit; `lanes` and `local` import neither the dispatch nor the pipeline | `test_only_managed_activation_imports_the_connector_kit`, `test_the_ported_connectors_never_import_the_dispatch_or_the_pipeline` |
| R65 — no config field named `credential…` | `LocalSourceConfig` has none | the model's own field list |
| R67 — `check_capture` is S5b's | not written here | — |
| m9 — `SyncConnector`, `current_registry()`, a `mode="workspace"` observation | `run_coordinator_lane(connector: SyncConnector, …)`, `registry=current_registry()` in the switch, `fetch_policy` | `test_local_fetch_policy_equals_the_policy_the_prose_lane_mints`, `test_add_text_and_a_prose_upload_dispatch_through_the_prose_lane` |

## Ruff

`/tmp/hippo-s5a-ruff.log`. `ruff check` then `ruff format --check`, both exit 0, over
`src/hippo/connectors/lanes.py`, `src/hippo/connectors/local`, `src/hippo/connectors/loader.py`,
`src/hippo/ingest/prose_generation.py`, `src/hippo/ingest/managed_activation.py`,
`tests/fakes/connector_parity.py`, `tests/unit/test_connector_local.py`,
`tests/unit/test_connector_loader.py`, `tests/unit/test_layering.py`,
`tests/unit/test_import_order.py` and this file: "All checks passed!" and
"13 files already formatted". This file is included because CI runs `ruff format --check` over
Markdown fenced Python blocks; it carries none, and it formats clean.

## Open questions for the merger and for S5b

1. **`descriptor.kinds` is not yet pinned against published code rows.** S5b owns
   `local/connector.py` after this merge and should extend
   `test_local_descriptor_covers_every_record_the_lanes_write` to the archive and code-file worlds.
   If a local archive build publishes no `history_event` artifact and no `commit` object, the
   declaration is a superset and S5b may narrow it.
2. **Override 2 (`inventory=True`)** is the one capability declaration the plan and the shipped
   `ConnectorCapabilities` disagree about. S5b's `check_capture` test is the first thing that reads
   it.
3. **The Neo4j branch of `connector_parity._store` is written but unexercised.** It resets the
   database before each world, which is the shape the sequential worlds need; the rulebook forbade
   running it here.
4. **S5b's `connectors/git/` will hit Override 3's rule** and keep its built-in entry
   automatically — no further loader change is needed, but the git descriptor should be checked
   against `Registry.with_builtins().connector_kinds()` all the same.
5. **`_generation`'s adoption branch has no S5a-reachable consequence**, as the finding above
   records with its mutation result. S5b should check whether the code lane's reclaim rewrites the
   `Generation` row, which is where the same branch would bite.
6. **`LocalConnector.list_changes` and `_member` raise `NotImplementedError` for an archive or a
   code file.** S5b replaces both with `repo_capture.walk_tree`. Nothing routes there in S5a, but a
   merger reading the file cold should know the branch is deliberate and dated, not an oversight.
