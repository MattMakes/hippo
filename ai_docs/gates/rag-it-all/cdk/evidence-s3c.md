# CDK S3c evidence: the sync runtime and the fixture connector

Worker `backend-developer-12`, branch `wp/s3c`, base `9a4977c` (the `rag-it-all-tibs` HEAD named in
the spawn message, after S1a, S2a, S1b, S1b-fix, S3a, S4c, S4c-fix, S3b and S2b merged). Contract:
Task S3c of `ai_docs/plans/cdk-s3-runtime.md` section 12, with sections 4.7, 5, 6, 9 and 11 as the
specification, amended by the rulings and review findings the brief
`ai_docs/handoffs/briefs/cdk-s3c.md` names, including its "Amendments from S3a and S3b" section.
Read first: `evidence-s2b.md`, `evidence-s3a.md` and `evidence-s3b.md` beside this file.

Where a ruling and the plan differ, the ruling wins; every such case is in "Overrides" below.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `4edd742` | Add the connector sync runtime and its fixture connector (CDK S3c) | `connectors/sync.py` (new), `connectors/__init__.py`, `connectors/guard.py`, `knowledge/staged_records.py`, `store/knowledge.py`, `tests/fakes/fixture_connector/**` (new), `tests/unit/test_connector_sync.py` (new), `tests/unit/test_connector_guard.py`, `tests/unit/test_import_order.py`, `tests/unit/test_connector_contract.py`, this file |

Both CK3 lines and the CK7 line were re-run against the committed tree at `4edd742`; the logs above
are that run. A second commit records this hash and nothing else.

Every file outside the brief's "own" list is there under a grant the brief or the orchestrator gave
by name: `guard.py` and its pin test (R65, the one S3a file S3c may edit), `connectors/__init__.py`
and `test_connector_contract.py` (R70(2)), `staged_records.py`'s one field (R68(1)),
`store/knowledge.py` (R68(3), **two edits**, see overrides 2 and 3), and the three appended lines of
`test_import_order.py` (m12). Nothing else was touched: no `docs/spec`, no gate ledger checkbox, no
checkpoint, no `data/`, no `.rag-dev-data/`, no other `connectors` module.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| The CK3 Fake CHECK line, verbatim, before any implementation | `/tmp/hippo-s3c-red.log` | exit 2; one collection error, `ImportError: cannot import name 'sync' from 'hippo.connectors'` — the shape the plan's step 1 predicts |
| S3a's and S3b's seven files alone, at the same tree | `/tmp/hippo-s3c-red-others.log` | exit 0, 238 passed, 1 skipped |

The second line exists because a collection error interrupts the whole CK3 run, so the plan's
"S3a's and S3b's files pass" cannot be read off the first log (the same gap S2b recorded).

Because the plan's RED is a collection failure, it proves the module is absent but not that each
assertion bites. Four assertions did bite while going green, each on a real defect in the code
rather than in the test, and each is recorded under "What going green found" below.

## GREEN

| Line | Log | Result |
| --- | --- | --- |
| CK3 CHECK line 1 of `GATES.md`, verbatim, Fake | `/tmp/hippo-s3c-green.log` | exit 0, **296 passed, 2 skipped** |
| CK3 CHECK line 2 of `GATES.md`, verbatim, LadybugDB | `/tmp/hippo-s3c-ladybug.log` | exit 0, **110 passed** |
| Regression: the plan's step 3 set plus the store, registry and connector suites the changed shared files sit under, Fake | `/tmp/hippo-s3c-regress.log` | exit 0, **1052 passed, 2 skipped** |
| Ruff `check` then `format --check` over the thirteen changed files | run inline | exit 0; "All checks passed!", "13 files already formatted" |
| The CK7 CHECK line of `GATES.md`, verbatim | `/tmp/hippo-s3c-ck7.log` | exit 0; "All checks passed!", **"30 files already formatted"** — the first time that line runs end to end, because the two paths S2b and S3a had to skip (`knowledge/staged_records.py`, `tests/unit/test_staged_records.py`) now exist |

Counts per backend: **Fake 296 (2 skipped)** on the CK3 line plus 1052 (2 skipped) on the
regression set; **LadybugDB 110 (0 skipped)**. `test_connector_sync.py` alone is 56 cases: 55 pass
on Fake with one skip, and the skipped one
(`test_the_last_published_generation_survives_ladybug_close_and_reopen_after_a_failed_sync`) runs
and passes on the LadybugDB line, verified on its own
(`-k ladybug`: 1 passed, 55 deselected). The other Fake skip is S3b's
`test_a_sealed_connector_generation_survives_ladybug_close_and_reopen`.

Every line ran with `-W error` alone. **No anyio filter was needed and no warning was suppressed**:
none of the CK3 files imports `fastapi.testclient` at module level, so form (a) of rulebook line 19
applies and no form-(b) command-line filter was used. One `ResourceWarning` did surface while going
green — matrix row M10's socket case leaked the socket it opened to be refused — and it was fixed by
closing the socket in a `finally`, never by a filter.

**No Neo4j run.** The rulebook forbids one without a written grant, which this worker did not hold.
Nothing was written for Neo4j and nothing was run on it.

Nothing in this slice reads `.rag-dev-data/`, a real credential or a real token. The fixture
connector declares a `fixture_token` credential requirement and never resolves one.

## The regression set

`test_code_generation`, `test_prose_generation`, `test_managed_code_activation`,
`test_staged_code_writer`, `test_staged_prose_writer`, `test_generation_resume`, `test_layering`,
`test_import_order`, `test_managed_source_lifecycle`, `test_query_session` (the plan's step 3, plus
the two S3c adds), then `test_connector_contract`, `test_connector_keys`, `test_connector_classify`,
`test_connector_emit`, `test_connector_render`, `test_connector_loader`, `test_store_knowledge`,
`test_generation_store`, `test_derived_generation_store`, `test_temporal_evidence`,
`test_multi_generation_support`, `test_generation_scoped_reads`, `test_knowledge_scoped_reads`,
`test_code_capture_acceptance`, `test_registry`, `test_registry_model`. The last ten are there
because `store/knowledge.py` and `knowledge/staged_records.py` are shared files this slice edits.

## The failure matrix

Every row is one case of `test_connector_sync.py::test_the_failure_matrix[...]`, and every row runs
on Fake and on LadybugDB (both CK3 lines include the file). "G1 intact" is the byte comparison of
plan section 7.1: `generation_checksums`, the canonical serialization of every `GenerationMember`,
every evidence member's record and every `Passage`, plus the Source's `active_generation_id` and
`status` (`World.fingerprint`, after `test_temporal_evidence.py:1338`).

| # | Injection | Test case | What it proves |
| --- | --- | --- | --- |
| M1 | `after_fetch` raises on page 1 | `test_the_failure_matrix[M1]` | no `Artifact`, `ArtifactRevision` or `AccessPolicy` row added (`_capture_rows` equal); `SyncState`'s cursor and pending unchanged; a rerun publishes |
| M2 | `before_checkpoint` raises, inside the transaction | `[M2]` | as M1: the transaction rolled back |
| M3 | `after_checkpoint` raises on page 1, the rerun replays it | `[M3]` | every row page 1 wrote is still there byte for byte, and the checkpoint that replayed it moved no authorization epoch (read *at* `after_checkpoint`, not at the end of the run — the publication that follows legitimately moves one) |
| M4 | the provider replays one inventory page twice in one run | `[M4]` | one artifact id per note; the run still publishes |
| M5 | `ProviderTransientError` on page 2 of an inventory scan | `[M5]` | no `deleted_at` set; `scan.complete` false; the next scan completes |
| M6 | the scan stops at `max_pages=1` before a `complete` page | `[M6]` | `inventory == "partial"`; no deletion |
| M7 | a complete scan omits n2 (confirmed 404), keeps n1 | `[M7]` | n2 excluded with `deleted_at`; n1 kept; `receipt.deleted == 1` |
| M8 | page `[policy_change n1]` after a published G1 | `[M8]` | the run publishes; `policy_updates >= 1`; G1 retired |
| M8b | a policy-only narrowing, then a widening with a new revision | `[M8b]` | the artifact's `policy_id` moves at the checkpoint; **every stored span keeps its policy**; the reused revision keeps its first capture's `span_policy_id`; the widened policy reaches the spans only through the new revision (ruling R48 / B2) |
| M9 | a session open on G1, then a page deleting n2 | `[M9]` | the old session's `validate()` raises `Permissions changed; repeat the query`; a new session opens; `collect_generation(G1)` returns without deleting anything reachable |
| M10 | `emit` calls `socket.connect_ex`, `httpx`, `Ollama.embed_one`, `subprocess.run`, `Thread.start`, `time.time`, `datetime.now` (one subclass each) | `[M10]` | `ConnectorContractViolation` every time; no `Generation` row added |
| M11 | `emit` raises `ValueError` for one revision | `[M11]` | `coverage["emit_failed"]` counts it; publication proceeds |
| M12 | `staged_records._write_batch` raises after two batches | `[M12]` | the rerun reclaims and reports `resumed_from_batches > 0` |
| M13 | `before_seal`, then `before_publish` | `[M13]` | no active generation; no `IndexEvent(kind="published")`; the next run publishes |
| M14 | `after_publish` | `[M14]` | G2 is active; the rerun answers without rebuilding |
| M15 | the source's active pointer moves between install and publish | `[M15]` | `Generation publication compare-and-swap failed`; the next run publishes |
| M16 | a second `sync_connector` while the first holds the lease | `[M16]` | `ConnectorSyncBusy` |
| M17 | the lease expires and another claim advances the fence | `[M17]` | the next checkpoint refuses `Sync lease was lost` and writes no artifact |
| M18 | `should_stop` turns true between pages | `[M18]` | `ConnectorSyncCancelled` |
| M19 | the Source is tombstoned during staging | `[M19]` | the run refuses; G1's row is still there, withdrawn and never deleted |
| M20 | spies on `discard_generation`, `collect_generation`, `_clear_passages`, `delete_passages_for_source`, `delete_code_nodes_for_source` across three runs including a failed publication | `[M20]` | never called (review m13: the spy counts only the runtime's own calls, and this row makes none of its own — M9's test makes one `collect_generation` call on purpose, in its own case) |
| M21 | two syncs of unchanged content inside the policy TTL window, with a session open | `[M21]` | `authorization_epoch()` unchanged and the open session still validates (review M3 / ruling R52) |
| M22 | a crash after the first checkpoint, before any publication | `[M22]` | artifacts exist, `active_generation_id` is None, a query session validates and sees no `Passage` of this Source (review m16) |

Beside the matrix, the plan's named cases all exist and pass:
`test_a_fixture_partition_syncs_through_every_step_and_publishes`,
`test_publication_uses_the_build_authority_and_writes_one_published_index_event`,
`test_the_generation_records_the_registry_fingerprint_outside_its_configuration`,
`test_the_configuration_carries_the_connector_templates_and_derivation_versions`,
`test_passages_are_embedded_through_ctx_ollama_and_units_are_not`,
`test_rendered_facts_are_retrievable_as_derived_passages`,
`test_an_unchanged_partition_returns_no_changes_and_builds_nothing`,
`test_a_second_run_with_one_changed_note_publishes_a_child_generation`,
`test_the_sync_lease_is_one_row_per_partition_with_a_monotonic_fence`,
`test_store_classification_writes_only_when_the_value_changes`,
`test_a_partition_without_a_stored_classification_is_refused`,
`test_emit_receives_the_stored_mapping`, `test_a_reader_actor_is_refused_for_a_connector_sync`,
`test_a_coordinator_lane_connector_is_refused_by_sync_connector`,
`test_a_registry_that_is_not_the_frozen_current_registry_is_refused`,
`test_no_production_module_passes_fault_hook_to_sync_connector`,
`test_every_fault_point_label_is_reachable`,
`test_on_batch_sees_each_revision_outside_transactions_and_the_guard`, and the LadybugDB reopen
case. The brief's extra rulings add
`test_a_disabled_connector_instance_is_refused` (R51/M5),
`test_a_template_version_bump_rebuilds_an_unchanged_partition` (R52/M4),
`test_sync_refuses_a_descriptor_whose_registered_definition_differs` (R32/R46/m7),
`test_a_connector_source_is_refused_by_the_plain_coordinator` (R25),
`test_a_fetch_of_an_absent_id_raises_provider_not_found` (M15),
`test_the_fixture_connector_constructs_with_no_arguments` and
`test_a_probe_samples_through_list_changes_and_fetch` (R60/R-S3-7),
`test_the_registry_is_loaded_before_a_lifecycle_write` (R66 i),
`test_a_collected_connector_generation_leaves_its_published_versions_readable` (R68(3)/R66 ii),
`test_the_record_bundle_stages_alias_candidates` (R68(1)),
`test_the_guard_reports_one_violation_per_emit_call` (R65), and three source-level guards
(`test_the_runtime_never_deletes_the_active_generation`,
`test_the_documented_dangling_unit_note_is_present`, `test_sqlite_is_not_used_by_the_runtime`).

`test_every_fault_point_label_is_reachable` asserts set equality with `FAULT_POINTS`: every one of
the twelve labels fires on one clean run, and no label outside the tuple is ever raised.

## Overrides: where a ruling, a review finding or the code overrode the plan

1. **R52/M4 over `build_run.prior_receipt`'s `already_current` branch (a decision the plan leaves
   open).** Review M4 moves the "nothing changed" decision onto the candidate generation, so a
   policy-only change reaches `prior_receipt` with a manifest hash equal to the parent's and gets
   `already_current` — which would refuse to republish, while CK3's CRITERIA require a policy-only
   change to publish (M8b). `sync._prior` therefore discards an `already_current` result when the
   run observed a policy change; the `operation_id` replay branch (`already_published`) still
   answers, which is what M14 needs. Without this, M8b and M14 cannot both hold.
2. **R68(3): the exemption is one place in `src/hippo/store/knowledge.py`, not in
   `generations.py`.** R68(3) names "`_references` in `store/generations.py`", but `_references` is
   defined at `store/knowledge.py:591`; `generations.py` only calls it (`:571`, `:1014`, `:1060`).
   The reachable break is `store/knowledge.py:673` `_validate_knowledge`, which walks `_references`
   and raises `Missing Unit reference` when `update_knowledge` closes the recorded interval of a
   superseded `AssertionVersion` whose generation was collected — exactly R66(ii)'s case, and not
   reachable from `generations.py` at all. The orchestrator was asked and **granted option (a)**:
   the exemption lives in `_references`, covering every call site. Recorded here as the brief asks.
3. **The exemption is narrowed to a *stored* version, so S1b's guarantee survives.** A bare
   exemption makes `test_generation_store.py::test_assertion_version_unit_reference_must_exist`
   fail: it pins that a new `AssertionVersion` naming a missing `Unit` is refused, which is what
   S1b's write order (`Passage`, then `Unit`, then `AssertionVersion`) exists for.
   `_validate_knowledge` therefore re-adds the check for a version the store does not already
   hold. The dangling case R66(ii) describes only ever arises on a version that is already stored,
   so every write, checksum, close and collection R68(3) names is unblocked and no existing test
   changed. If the reviewer wants the literal unconditional exemption, that one `if` comes out and
   `test_assertion_version_unit_reference_must_exist` must be rewritten by its owner.
4. **R48/B2: the revision's metadata carries two keys, not one.** Plan section 5.4 and B2 ask for
   `metadata_json["span_policy_id"]`. `_capture` also writes `metadata_json["raw_bytes"]`, because
   `RawArtifactStore.read_bytes` verifies a length it is given and `ArtifactRevision` has no byte
   column; `_emit` would otherwise have to guess it or reach into the raw store's private layout.
   `metadata_json` is outside `ArtifactRevision.identity_fields`, so neither key moves an id. The
   *manifest* revision's metadata stays closed to `{"connector_inventory_v1": ...}`, which
   `generation_profiles._connector_manifest` requires.
5. **m15: the pending log and the seen set are `{"uri", "sha256", "bytes"}` references, not bare
   URIs.** Plan section 6.4 writes the seen set as "the raw uri of the sorted seen artifact ids".
   A bare URI cannot be read back, for the reason in override 4. Both are content addressed, so a
   replayed page computes an identical reference and `SyncState.cursor_json` does not change a
   byte, which is what M3 and M4 check.
6. **The authority guard is re-captured after *every* checkpoint, not only after the last one.**
   Plan section 5.5 step 6 says "after the last checkpoint and before `bind_inputs`". That is
   necessary but not sufficient: `run.check()` runs between pages and compares the captured epochs,
   so the first page's own policy write makes the *second* page's check refuse with "Build
   authorization or suppression changed". Decision 11's rule ("no guard ever spans a checkpoint")
   is implemented literally: `_pages` adopts a fresh authority after each checkpoint, `_reconcile`
   runs under the last of them, and one more capture happens after `_reconcile` (which sets
   `deleted_at` and moves the epoch itself) and before `bind_inputs`.
7. **Cancellation is re-raised as `ConnectorSyncCancelled`.** `BuildRun` raises the shared
   `BuildCancelled`; plan section 4.7 names a runtime subclass. The entry converts the base class
   at its boundary, so a caller catching either works (M18).
8. **`sync_connector` takes `connector_id` and reads the `Connector` row itself** (R49/B4). The
   plan's section 4.7 signature has no `connector_id` and the S4 plan's R-S3-1 does; the S4
   spelling is implemented verbatim, including the keyword order.
9. **`ensure_connector` defaults to `enabled=False`** (R51/M5), against plan section 4.7's
   `enabled=True`. The entry refuses a disabled instance with
   `Connector instance {id} is not enabled`.
10. **The runtime stops paging on `complete`, not only on a null cursor.** The plan bounds pages by
    `max_pages` and the cursor but does not say when a walk ends. A page marked `complete` ends an
    authoritative enumeration, so continuing past it is meaningless; the fixture's last inventory
    page hands back a *changes* cursor so the next run reads the incremental feed. Row M6 pins that
    stopping on `max_pages` before a `complete` page infers no deletion.
11. **`R66(i)` is pinned by a registry comparison rather than by a write under a bare registry.**
    `test_the_registry_is_loaded_before_a_lifecycle_write` asserts that the version a sync published
    is refused by a `Registry.with_builtins()` installed with `use_registry` and admitted by the
    loaded one. That is the same claim — the lifecycle write path is vocabulary-checked, so the
    registry must be loaded first — proved without depending on which of the two vocabulary checks
    fires first.

12. **M5 restarts its scan; it does not resume at page 2.** Plan section 9's M5 row says "the next
    run resumes at page 2". `_pages` starts every inventory scan from cursor `None` with a fresh
    `scan` record, because section 6.4's first condition for inferring a deletion is that "the scan
    started from cursor `None`", and a resumed scan cannot satisfy it without carrying the seen set
    and the started-at instant across a failure. Restarting is strictly safer and is what the row's
    *expectation* asks for — no deletion follows the failed page, and the next run completes — so
    `[M5]` asserts the outcome and not the page number. Resuming a partial scan is an optimisation
    a later slice can add on top of the stored `scan` record, which already holds everything it
    would need.
13. **`SyncOptions.max_batch_payload_bytes` is enforced by `_stage`.** Plan section 5.8 step 3 does
    not name the check, but the code lane's `_write` (`code_generation.py:717-719`) refuses on its
    own option before the writer's `PAYLOAD_CEILING_BYTES` does, and leaving the option unread would
    make it a lie. `_batch_bytes` mirrors `code_generation._batch_bytes` over
    `staged_records._payload`.

## The `excluded_vocabulary` decision (the S1a-fix finding; the brief asks me to say where)

`Generation.coverage_json` gains a top-level `"excluded_vocabulary"` key, written by
`sync._coverage_json` beside `"emission"`, `"pages"`, `"inventory"` and the rest. Its value is
**always `{}`** for a connector generation, by construction and not by omission: every record in the
bundle was built under the frozen current registry and passed `Registry.check_record` at bind
(ruling R39), so a projection of this generation leaves nothing out. The key is written anyway so a
reader can tell "this build counted exclusions and found none" from "this build never counted them"
— a pre-kit generation has no such key at all. Where *read-time* counts surface (a query's coverage,
which is what `project_managed_graph(..., exclusions=...)` actually fills) stays open and is Task
15's, exactly as S1a's open question 3 and S1b-fix leave it. The runtime never calls
`project_managed_graph`.

## What going green found (the assertions that bit)

1. **A rerun's inventory manifest must be the stored row.** `_manifest_pair` built a fresh
   `ArtifactRevision` with `observed_at=now`. `observed_at` is outside revision identity, so the id
   matched the stored row while the contents did not, and `BuildAuthority._inventory` refused every
   rerun with `Accepted record differs from current stored identity`. Rows M12, M13 and M15 all
   failed on it. The stored artifact and revision now win whole.
2. **The guard latched during capture** (override 6), failing the second page of every run.
3. **The strict contract models never accept a `dict`.** `ChangePage`, `PolicyObservation` and
   `Classification` round-trip through `model_validate_json`, because a JSON array is a `list` and
   the models want tuples. This is worth knowing for S4's replay connector and S6's exemplar.
4. **The inventory manifest's `members` are objects, not arrays.**
   `generation_profiles._connector_members` reads five named keys per member.

## What S4, S5 and S6 require from S3, satisfied by name

| Item | Where |
| --- | --- |
| S4 R-S3-1 (one entry; `connector_id`, actor, frozen registry, `fault_hook`, `on_batch`; the generation id) | `sync.sync_connector`, signature verbatim as `cdk-s4-kit.md` section 9 spells it, including keyword order; `SyncReceipt.generation_id` is the published id. Still refuted in one part: no `clock` argument (R27, the store clock is the one clock) |
| S4 R-S3-2 (failpoint names for the five boundaries) | `sync.FAULT_POINTS`; the five design section 8 boundaries are matrix rows M1/M2 (crash after fetch before checkpoint), M3/M4 (replayed page), M5 (failed inventory), M8/M8b (policy change mid-page) and M9 (delete with a live query session) |
| S4 R-S3-2 (instances and classification: `ensure_connector`, `connector_source`, `store_classification`) | All three, signatures verbatim; `ensure_connector` defaults to `enabled=False` (R51) and the kit always passes `True`; `store_classification` writes only on change (R21); `load_classification` reads one partition's entry |
| S4 R-S3-4 (the guard in a module both import) | `connectors.guard.forbid_effects` and `EmitSideEffect`, entered inside each emit worker thread under `contextvars.copy_context().run(...)` (m20), so `run_case`'s `use_registry` reaches the worker |
| S4 R-S3-5 (HTTP: `ERROR_CLASSES`, `ProviderError`, `record_transport`, `replay_transport`, `ProviderClient(base_url, transport=...)`) | S3a's, unchanged and exercised: the fixture connector reads its provider through `ProviderClient` over `httpx.MockTransport`, and `ProviderNotFoundError` and `ProviderTransientError` drive rows M5, M7 and `test_a_fetch_of_an_absent_id_raises_provider_not_found` |
| S4 R-S3-6 (credentials: `resolve`, `redact_url`) | S3a's, unchanged; `sync.ensure_connector` calls `refuse_inline_secrets` and `CredentialRef.parse` before it stores a reference |
| S4 R-S3-7 (a no-argument `FixtureConnector`, `fixtures/basic` with two or more upserts, `inventory=True`, a probe sampling through its own `list_changes` and `fetch`) | `tests/fakes/fixture_connector/`; `test_the_fixture_connector_constructs_with_no_arguments` and `test_a_probe_samples_through_list_changes_and_fetch` pin all four |
| S5 R-S3 (nothing functional; the `sync.py` re-export is S5b's) | `sync.py` leaves no lane seam (R3). `sync_connector` refuses a `derivation="coordinator_lane"` descriptor. Q7 is answered by R25/R43: until S5a's switch, `build_plain_source` refuses a `kind="connector"` Source, pinned by `test_a_connector_source_is_refused_by_the_plain_coordinator` |
| S6 R-S3-1 (Source creation, `_source_control` admission, `BuildAuthority`, `ctx.ollama`) | `connector_source` creates the `kind="connector"` Source with `meta={"connector_id","partition"}`; S3b's admission accepts it; publication goes through `publish_staged_generation` under the captured authority; passages embed through `ProfiledEmbeddings(ctx.ollama, ...)` |
| S6 R-S3-2 (rendered facts as managed passages over a view) | S2b's binder; `test_rendered_facts_are_retrievable_as_derived_passages` reads the `RetrievalView` rows and their derived `Passage`s back out of the published generation |
| S6 R-S3-3 (store and read the classification) | `store_classification` / `load_classification` |
| S6 R-S3-4 (instance creation with stored config; credentials for probe) | `ensure_connector(..., config=..., credential_ref=...)` stores `config.model_dump_json()` after `refuse_inline_secrets` |
| S6 R-S3-5 (deletion only from a completed inventory) | `sync._reconcile`; rows M5, M6, M7 |

## Gotchas for the next worker

1. **A strict contract model never accepts a `dict`.** Use `model_validate_json`. This will bite
   S4's `_ReplayConnector` and S6's exemplar the moment they parse a canned response.
2. **`emit` is called for every member revision, not only the changed ones** (DV1), so a
   connector's `emit` runs once per note per run. It must stay cheap and pure.
3. **The emit guard forbids the clock, so a connector cannot log inside `emit`.** It reports through
   `ParseFailure`. After the first violation CPython unsets the profiler for that thread, so a
   second violation in the same call is not reported (R65); the sync fails on the first.
4. **A new `AssertionVersion` still needs a live `Unit`** (override 3). Only a stored one is exempt.
5. **The fixture provider's instance URL must be unique per test.** A remote `Artifact`'s identity
   is scoped by `provider_instance`, not by its Source, so two worlds on one instance collide with
   "Immutable record already exists" (S3b gotcha (a)); `test_connector_sync.py` takes each instance
   from a module-level counter.
6. **An enabled provider `Connector` is refused in open mode**, so the world creates an operator
   user before `ensure_connector(..., enabled=True)` (S3b gotcha (b), R64).
7. **A `connector` Source's first sync always walks the whole partition**, because there is no
   stored cursor; that walk is complete, so the first run's `inventory` is `"complete"` and
   `last_reconciled_at` is set. Deletions are still impossible on it: there is no parent generation.

## Open questions for the orchestrator

1. **`already_current` for a connector partition is now unreachable** (override 1). Every "nothing
   changed" answer is `no_changes`, and `already_published` still answers an `operation_id` replay.
   `SyncReceipt.outcome`'s `Literal` keeps `already_current` because the S4 plan's section 3.1
   reads it; if the reviewer wants it reachable, M8b's "two more syncs publish" has to be rewritten.
2. **Aliases are structural only.** `RecordBundle.aliases` exists, is grouped, is inventoried and is
   refused when it names a missing object or span (R68(1)), but S2b's binder turns an
   `AliasEmission` into a `SAME_OBJECT_AS` assertion and writes no `k.Alias` row, so nothing in S3c
   fills the field. Whether the kit should write `Alias` rows at all is Task 12's under R18.
3. **`reconcile_due` defaults to daily and the first run is always a complete scan.** Task 9A owns
   when `sync_connector` is actually called (R33), so the interval is only an option here.
4. **In-process emit cannot be pre-empted** (R36, plan Q6): `emit_timeout_seconds` fails the sync
   while the worker thread runs to completion.
5. **`ensure_connector` writes `enabled` from its argument on an existing row.** With R51's
   `enabled=False` default, a caller that re-ensures an instance only to update its configuration
   silently disables it. Plan section 13 lists `enabled` among the updatable fields, so this is
   arguably intended, but S4b's `hippo connector enable` (R59) and S6's routes should pass
   `enabled=` deliberately every time.
6. **`ProviderForbiddenError` and `ProviderNotFoundError` on `fetch_policy` become
   `PolicyObservation(state="unknown")`**, which is deny, as `docs/rag_it_all.md:639` asks. Any
   other provider error on `fetch_policy` fails the page, which is the "failed page" rule (DV5).
   The plan does not say which classes are permission-masked; these two are the reading taken.
