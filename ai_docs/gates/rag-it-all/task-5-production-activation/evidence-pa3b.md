# Evidence: production activation Task 3b — managed delete dispatch and mixed bulk reindex

**Branch:** `wp/pa3b`, worktree `.worktrees/pa3b`, base `c668688` (rag-it-all-tibs),
merged forward to `ffd2265` part-way through (see below).
**Scope:** PA4 (dispatch half), PA5 (all), PA7 (pipeline half, including the Ladybug
close/reopen case Task 3a left open). Task 3a's adapter and add/refresh dispatch are
inherited unchanged except for the review items recorded below.

## Commits

| Hash | Subject |
|---|---|
| `7bf346d` | Send a managed delete to the tombstone service, not to the clear |
| `990b587` | Retire the stage of a refresh no restart could finish |
| `4447cbc` | Merge rag-it-all-tibs: reach the managed lane through the lazy accessor |
| (the commit adding this file) | Record the PA3b evidence |

**The merge.** `rag-it-all-tibs` fixed an import cycle at `da51784` (recorded at
`ffd2265`): `pipeline.py` no longer imports `managed_activation` at module level but
through a lazy `_managed()` accessor, and `tests/unit/test_import_order.py` guards the
entry modules. The one conflict was that import line. Resolved by keeping `_managed()`
and rewriting this branch's four new call sites to go through it; the module-level
`from . import managed_activation` was not restored. The three lifecycle imports this
branch adds (`knowledge.access`, `knowledge.build_authority`, `knowledge.source_lifecycle`)
stay at module level: none of them reaches `hippo.ingest`, and `test_import_order.py`
passes (7 passed) with them there.

## Files

| File | Change |
|---|---|
| `src/hippo/ingest/pipeline.py` | `delete_source(..., build_actor, operation_id)` dispatch and `_tombstone`; `reindex_all(..., build_actor)` classification, `_preflight_managed`, legacy-only clear, per-lane submission; module docstring. |
| `src/hippo/ingest/managed_activation.py` | `_fraction` and the stored synonym threshold refusal (review item 4); the profile-mismatch rows ahead of `OllamaError` in `FAILURES` (review item 7). |
| `src/hippo/store/memory.py` | `REFRESHING_PREFIX`, `INTERRUPTED_REFRESH_STAGE`, `INTERRUPTED_REFRESH_ERROR`; `mark_interrupted_jobs` retires an interrupted managed refresh (review minor 12). |
| `src/hippo/store/ladybug.py` | The same recovery, over the same three constants. |
| `tests/fakes/fake_store.py` | The same recovery. |
| `tests/unit/test_managed_pipeline_activation.py` | Delete matrix, mixed bulk, settings and restart recovery, Ladybug reopen; `inline_jobs`/`held_jobs` on the `Setup` fixture; review items 1–5 and 7. |
| `tests/unit/test_ingest_concurrency.py` | Managed delete against running jobs; the two bulk races. Imports the managed `setup` fixture from the activation module. |
| `src/hippo/web/routes/sources.py` | **Not changed.** The `edit_graph` precondition for the bulk lives at `sources.py:481`, outside the pipeline, and is preserved by not touching it. Actor propagation into the route is Task 4's. |

## Public signatures as implemented

```python
# src/hippo/ingest/pipeline.py
def delete_source(
    ctx, source_id, *, build_actor: BuildActor | None = None, operation_id: str | None = None
) -> None
def reindex_all(ctx, *, build_actor: BuildActor | None = None) -> int
def _tombstone(ctx, source_id, actor: BuildActor | None, operation_id: str | None) -> None
def _preflight_managed(ctx, lanes: list[tuple[str, Any]], actor: BuildActor | None) -> bool
#   the second element is a `managed_activation.Dispatch`; the annotation stays `Any`
#   because that module is only reachable through the lazy `_managed()` accessor.

# src/hippo/ingest/managed_activation.py
def _fraction(value, what: str) -> float        # new; `build_options` uses it for the threshold
# FAILURES gains two rows, ahead of the OllamaError row:
#   (EmbeddingProfileMismatch, "retrieval_rebuild_required", ...)
#   (EmbeddingProfileChanged,  "retrieval_rebuild_required", ...)

# src/hippo/store/memory.py  (imported by ladybug.py and tests/fakes/fake_store.py)
REFRESHING_PREFIX = "refreshing:"
INTERRUPTED_REFRESH_STAGE = "refresh_failed"
INTERRUPTED_REFRESH_ERROR = "build_interrupted: The build was interrupted by a restart. Reindex to run it again."
```

`Store.mark_interrupted_jobs()` keeps its `-> int` contract; the integer now also counts
retired refreshes. `test_store.py:478`'s `== 3` is unchanged because that fixture holds no
refreshing source.

## Delete matrix

Classification is `managed_activation.plan_dispatch` — one predicate, shared with
`start_indexing`/`run_indexing`/`reindex` — and the lane is chosen on `plan.eligibility`,
not `plan.mode`. That distinction matters: an *eligible legacy* source plus an actor plans
mode `"managed"` for a build, but a delete of it is still the legacy physical delete,
because there is no managed evidence to suppress.

| Source | Actor | Result | Test (`test_managed_pipeline_activation.py`) |
|---|---|---|---|
| managed | reader | `tombstone_managed_source`; row `deleted/tombstoned`; pointer, seal, raw and saved bytes retained; current view excludes it at once; unrelated managed source byte-identical | `test_deleting_a_managed_source_suppresses_it_and_removes_nothing` |
| managed | reader, explicit `operation_id` | that identity is the suppression's `restoration_barrier` | `test_a_managed_delete_takes_the_supplied_operation_identity_or_a_fresh_bounded_one` |
| managed | reader, no `operation_id` | a fresh bounded identity is generated | same test |
| managed | reader, unbounded `operation_id` | `ManagedDispatchError` before any mutation | `test_a_managed_delete_refuses_an_unbounded_operation_identity_before_any_mutation` |
| managed | none | `ManagedActorRequired` before any legacy hook, file removal or generation mutation | `test_deleting_a_managed_source_without_an_actor_refuses_before_any_legacy_hook` |
| unmanaged legacy | none | legacy physical delete, unchanged (row, passages, orphans, folder, graph version) | `test_deleting_an_unmanaged_source_keeps_the_legacy_physical_delete[False]` |
| unmanaged legacy | reader | the same legacy physical delete: an actor never converts a delete | `...[True]` |
| tombstoned | reader | `AuthorizationChanged` — the same generic denial as an unavailable source; no mutation, no new epoch | `test_deleting_a_tombstoned_source_answers_like_an_unavailable_source` |
| tombstoned | trusted local, same `operation_id` | returns `None` (its own receipt replayed); no second suppression, no new epoch | same test |
| tombstoned | trusted local, different `operation_id` | `AuthorizationChanged` | same test |
| tombstoned | none | `ManagedActorRequired`, exactly as a live managed source: an actorless caller cannot tell them apart | `test_deleting_a_tombstoned_source_without_an_actor_refuses_like_any_managed_source` |

A tombstoned source is dispatched *into* `tombstone_managed_source` rather than
short-circuited, which is what keeps the reader denial and the trusted-local replay both
correct (Task 1 review note 4: the service establishes actor standing before revealing
managed/unmanaged, so the pipeline may call it for anything it has classified as managed).

## `reindex_all` protocol

| Plan step | Implementation | Test |
|---|---|---|
| 1. `edit_graph` and no-index-job preconditions | `edit_graph` stays in `web/routes/sources.py:481`; `_refuse_if_indexing(ctx)` is still the first statement | `test_ingest_concurrency.py::test_delete_and_reindex_refuse_while_another_source_is_being_indexed` (unchanged) |
| 2. snapshot current Source rows | one `ctx.store.list_sources()` before any mutation | every bulk test |
| 3. classify all, skip tombstones | `plan_dispatch` per row; `mode == "skip"` dropped | `test_a_mixed_bulk_clears_only_legacy_lanes_and_submits_each_with_its_own_identity` |
| 3b. no actor + managed inventory refuses before any clear | `plan_dispatch` raises `ManagedActorRequired` during classification | `test_a_bulk_without_an_actor_refuses_before_clearing_a_managed_inventory` |
| 4. capture `BuildAuthority` for every managed lane; any failure clears nothing, starts nothing, returns 0 | `_preflight_managed` uses `capture_build_authority` (the Task 1 primitive) and closes each guard; catches `AuthorizationChanged` only | `test_a_failed_managed_preflight_clears_nothing_and_starts_nothing` |
| 5. `_prepare_reindex` for the legacy lane only, all clears before any job | one loop over `mode == "legacy"`, then a separate submission loop; each lane records the clears it saw | `test_a_mixed_bulk_clears_only_legacy_lanes_and_submits_each_with_its_own_identity` asserts `prepared == [unsupported]` and that every lane saw the complete clear |
| 6. submit each lane with its immutable actor and a fresh operation ID | `start_indexing(..., build_actor=plan.actor, operation_id=plan.operation_id)`; identities come from `plan_dispatch`, one per lane | same test: two distinct bounded identities, one per managed lane |
| 6b. public response and integer | `{"accepted": true}` unchanged in the route; the integer is still what `Jobs` accepted | `test_status_access.py::test_reindex_all_acknowledges_without_exposing_the_global_start_count` (unchanged) |
| 7. workers recheck classification and authority; a race fails that lane without legacy fallback | `run_indexing` re-plans, and the coordinator re-captures authority | `test_ingest_concurrency.py::test_a_source_tombstoned_between_the_bulk_preflight_and_its_worker_skips_that_lane`, `::test_an_actor_disabled_between_the_bulk_preflight_and_its_worker_fails_only_that_lane` |
| one lane's asynchronous failure isolates | the managed lane presents, never clears; the legacy lane clears only its own | `test_one_lane_failing_asynchronously_leaves_every_other_source_intact` |
| managed refresh and eligible conversion in a real mixed bulk | | `test_a_mixed_bulk_refreshes_managed_evidence_and_converts_without_a_legacy_clear` |

The mixed inventory in the `mixed` fixture is exactly the plan's adversarial case: a
managed refresh, an eligible legacy conversion, an unsupported legacy upload (`module.py`)
and a current tombstone.

**Returning 0 rather than raising** is what "clears nothing, starts nothing, and no hidden
per-source breakdown" asks for, so a preflight failure is indistinguishable from a bulk
that had nothing to do. The consequence is worth stating: a workspace that contains one
legacy text source somebody else owns makes an authenticated bulk return `{"accepted":
true}` and do nothing at all. That is the specified behaviour, not an accident, but an
operator has only the local log line (`Bulk reindex started nothing: source <id> ...`) to
find it by.

## Destructive-operation spies

`refuse_destruction` (new) patches each of these to **raise**, and every managed delete
still returns normally with the source tombstoned:

- `store.delete_source`
- `store.delete_passages_for_source`
- `store.delete_code_nodes_for_source`
- `store.remove_orphans`
- `store.discard_generation`
- `store.collect_generation`
- `pipeline._clear_passages`
- `shutil.rmtree`
- `os.unlink`, `os.remove`, `os.rmdir` for any path at or below the data directory
  (`Path.unlink`/`Path.rmdir` reach `os`), which covers saved ingress bytes, raw objects and
  cache entries. The backing database file is outside the data directory and is not guarded.

The file-removal guard is armed only inside `w.refusing()`, the window of the delete under
test. It has to be: an ordinary managed *capture* unlinks its own staging spool below the
data directory (`RawArtifactStore.put_stream`), so an always-on guard would break the build
that sets the test up rather than prove anything about the delete. This is the same
limitation pa3a recorded; arming a window is how this slice gets the assertion anyway.

Every delete test additionally compares `data_inventory(ctx)` — every file below the data
directory, by relative path and bytes — before and after, so a removal that somehow avoided
the patched entry points would still fail.

`test_a_failed_managed_preflight_clears_nothing_and_starts_nothing` and
`test_a_bulk_without_an_actor_refuses_before_clearing_a_managed_inventory` run under
Task 3a's `no_destruction` (which fails rather than raises) *and* compare every Source row
and every saved byte before and after.

## Review items from the Task 3a review, carried here

1. **`reindex` drives the conversion branch.**
   `test_an_eligible_legacy_reindex_converts_atomically_and_serves_legacy_until_publish`
   now calls `pipeline.reindex(ctx, source, build_actor=...)` with jobs running inline, so
   the branch under test is `reindex`'s own, not just the worker it submits. It also fails
   if `_prepare_reindex` is reached, and asserts the legacy passage row outlives the publish.
2. **Redaction assertions use `caplog.text`.** `record.getMessage()` omits the formatted
   traceback, which is the one place a leaked exception string would appear. Both
   `test_an_unknown_failure_never_reaches_the_source_row_or_the_logs` and
   `test_a_failure_that_cannot_be_presented_still_reports_nothing_private` were changed.
3. **The missing dispatch cell is covered.**
   `test_an_eligible_plain_upload_without_an_actor_stays_legacy` (3 cases) uses
   `Setup.stage_upload`, which had no caller before.
4. **The stored synonym threshold is validated.** `build_options` refused every
   configuration value it reads except this one, which reached `PlainBuildOptions` and
   raised a bare `ValueError` there — mapped to `operation_failed` instead of
   `invalid_configuration`. `_fraction` now refuses a non-number, a bool, a non-finite
   value and anything outside `0..1` as `ManagedConfigurationError`, and a missing setting
   no longer raises `KeyError`.
   Tests: `test_an_out_of_contract_stored_synonym_threshold_is_refused` (6 cases) and
   `test_a_build_refuses_a_stored_threshold_generically_and_without_a_model_call`.
5. **An interrupted refresh is retired by the restart sweep** (review minor 12). A managed
   refresh leaves `status="ready"`, `stage="refreshing: ..."`, because its published
   generation keeps serving; the restart sweep only looked at `status IN ('reading',
   'indexing')`, so a crash mid-refresh left that stage on the row for ever.
   `mark_interrupted_jobs` now also matches `status = 'ready' AND stage STARTS WITH
   'refreshing:'` and sets `stage="refresh_failed"` with the bounded generic
   `build_interrupted: ...` error. Status, active pointer and counts are untouched; the
   source keeps serving. Implemented identically in `store/memory.py` (Neo4j),
   `store/ladybug.py` and `tests/fakes/fake_store.py`, as a pure store rewrite with no
   import of `hippo.ingest`.
   Tests: `test_a_refresh_interrupted_by_a_restart_is_retired_without_losing_g1` (the stage
   it writes back is taken from a *real* refresh observed in flight, not invented) and
   `test_an_interrupted_refresh_is_retired_by_the_next_ladybug_open` (close, reopen,
   `on_first_connection`).
   **Ownership:** `src/hippo/store/*` is listed under "do NOT touch" in this brief. The
   orchestrator granted `store/memory.py`, `store/ladybug.py` and `tests/fakes/fake_store.py`
   for `mark_interrupted_jobs` only; `store/__init__.py` needed no change.
6. **pa3a deviation 7 was false.** `reindex_all` did not "clear nothing and start nothing"
   for a managed source: `list_sources()` orders newest first, so every legacy source
   ordered before the first managed one was already cleared by `_prepare_reindex` when
   `legacy_source_cleanup` finally raised. The RED run shows exactly that
   (`Failed: managed attempt called pipeline._clear_passages` from
   `test_a_bulk_without_an_actor_refuses_before_clearing_a_managed_inventory`). Classifying
   the whole inventory before the first clear is what makes it impossible now.
   The spy the brief called `delete_code_for_source` is `store.delete_code_nodes_for_source`.

7. **A stale embedding profile asks for a rebuild, not a retry** (from the Task 4a
   evidence). `EmbeddingProfileMismatch` and `EmbeddingProfileChanged` are `OllamaError`
   subclasses, so the widest model row matched them first and a build that met a changed
   profile was stored as `model_unavailable` — read back publicly as 503 "try again", for
   evidence that will never be compatible again, while the same exception in a query reads
   as `retrieval_rebuild_required` (409). Both now have their own row ahead of
   `OllamaError`, with the same stable code the query path uses, so the two vocabularies
   agree and `public_errors._MANAGED_CODES` can map the code to `REBUILD_REQUIRED`
   directly. `EmbeddingProfileUnavailable` deliberately stays on the `OllamaError` row: it
   means the model service could not answer, which is the unavailable case.
   Tests: `test_a_stale_embedding_profile_asks_for_a_rebuild_rather_than_a_retry` (both
   families × both generation states, plus the two that must stay `model_unavailable`) and
   `test_a_refresh_that_meets_a_changed_profile_reads_back_as_the_rebuild_code`, which
   reads the code back off the Source row after a real refresh.
   **Follow-up for Task 4:** `retrieval_rebuild_required` is a tenth managed code;
   `public_errors._MANAGED_CODES` documents itself as covering "the nine stable values
   `managed_activation.FAILURES` and `UNKNOWN_CODE` produce" and needs the row added.
## Ladybug close and reopen (the PA7 half Task 3a left open)

`test_a_ladybug_reopen_preserves_pointers_manifests_raw_references_and_the_tombstone`
builds three managed sources in one temporary absolute `HIPPO_DATA_DIR`, then:

1. publishes source A (managed bootstrap);
2. rewrites source B's ingress and fails its refresh at `/api/chat`, leaving G1 active and
   the row `ready` / `refresh_failed`;
3. tombstones source C through `pipeline.delete_source`.

It snapshots every Source row (minus `generation_lock`), the `Artifact`,
`ArtifactRevision`, `Suppression` and `Generation` rows, the whole raw inventory by name
and bytes, both epochs, and the current structural citations. Then it closes the Store,
reopens the same file with `LadybugStore(path)` and asserts all of it again, plus
`source_is_managed` and `validate_generation_seal(...).ready` for all three generations,
and that every `ArtifactRevision.raw_uri` still names an object present on disk. The
tombstoned source's text is absent from the current view before and after.

It skips when the backend is not Ladybug, the same way `test_prose_generation.py:1014` does.

## Commands and results

```
$ HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py \
    tests/unit/test_prose_generation.py tests/unit/test_generation_failure.py \
    tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py \
    tests/unit/test_managed_source_lifecycle.py -q -o addopts='' -W error
EXIT 0 — 223 passed, 1 skipped in 27.19s        (baseline, /tmp/hippo-pa3b-baseline.log)

$ HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py \
    tests/unit/test_ingest_concurrency.py -q -o addopts='' -W error
EXIT 1 — 17 failed, 81 passed, 1 skipped        (RED, /tmp/hippo-pa3b-red.log)
    9 TypeError: delete_source() got an unexpected keyword argument 'build_actor'
    6 TypeError: reindex_all() got an unexpected keyword argument 'build_actor'
    1 RuntimeError: a managed delete never calls store.delete_source
      (the actorless managed delete reaching the legacy physical delete)
    1 Failed: managed attempt called pipeline._clear_passages
      (the actorless bulk clearing legacy sources before refusing — review item 6)
  The Ladybug reopen test is the 1 skip; it is RED on Ladybug for the same
  `delete_source` signature, which the Ladybug run below covers.

The addendum items arrived after that log, so their RED was reconstructed by checking the
four implementation files back out at their pre-change revisions and running only the tests
those items added:

$ git checkout 7bf346d^ -- src/hippo/ingest/managed_activation.py
$ git checkout 990b587^ -- src/hippo/store/memory.py src/hippo/store/ladybug.py \
    tests/fakes/fake_store.py
$ HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py \
    -k "synonym_threshold or stored_threshold or interrupted_by_a_restart or rebuild \
    or stale_embedding" -q -o addopts='' -W error
EXIT 1 — 10 failed, 91 deselected        (RED, /tmp/hippo-pa3b-red-addendum.log)
    6 `test_an_out_of_contract_stored_synonym_threshold_is_refused[...]`
      — `PlainBuildOptions` raised a bare `ValueError`/`TypeError`, not
        `ManagedConfigurationError` (item 4)
    1 `test_a_build_refuses_a_stored_threshold_generically_and_without_a_model_call`
      — the row read `operation_failed: ...` instead of `invalid_configuration: ...`
    1 `test_a_refresh_interrupted_by_a_restart_is_retired_without_losing_g1`
      — `mark_interrupted_jobs()` returned 0 and left `refreshing: ...` on the row (item 5)
    2 `test_a_stale_embedding_profile_...`, `test_a_refresh_that_meets_a_changed_profile_...`
      — both read `model_unavailable` from the `OllamaError` row (item 7)
$ git checkout HEAD -- <the same four files>

Addendum items 1–3 are coverage of behaviour that already worked (the conversion branch,
`caplog.text`, the actorless eligible upload), so they pass against the base by design and
have no RED. `test_an_interrupted_refresh_is_retired_by_the_next_ladybug_open` skips on
Fake; its RED is the same missing sweep, proven by the Fake case above.

$ PA3: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py \
    tests/unit/test_prose_generation.py tests/unit/test_generation_failure.py -q -o addopts='' -W error
EXIT 0 — 182 passed, 3 skipped in 31.64s

$ PA4: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py \
    tests/unit/test_ingest_concurrency.py tests/unit/test_generation_store.py \
    tests/unit/test_evidence_access.py -q -o addopts='' -W error
EXIT 0 — 116 passed in 6.04s

$ PA5: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py \
    tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py \
    tests/unit/test_status_access.py -q -o addopts='' -W error
EXIT 1 — 1 failed, 165 passed, 2 skipped in 35.71s   (the one failure is external, below)

$ EXTRA: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py \
    tests/unit/test_prose_generation.py tests/unit/test_store.py \
    tests/unit/test_import_order.py -q -o addopts='' -W error
EXIT 0 — 134 passed, 1 skipped in 19.91s
                                                (GREEN Fake, /tmp/hippo-pa3b-fake-green.log)

$ HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py \
    tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py \
    -q -o addopts='' -W error
EXIT 0 — 142 passed in 1650.44s (27:30)         (GREEN Ladybug, /tmp/hippo-pa3b-ladybug-green.log)
  No skips: both reopen tests run here, and this is the only backend where they do.

$ HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_store.py \
    tests/unit/test_managed_source_lifecycle.py tests/unit/test_import_order.py \
    -q -o addopts='' -W error
EXIT 0 — 68 passed in 36.76s                    (the store sweep on the real backend)

$ .venv/bin/ruff check src/hippo/ingest/pipeline.py src/hippo/ingest/managed_activation.py \
    src/hippo/store/memory.py src/hippo/store/ladybug.py tests/fakes/fake_store.py \
    tests/unit/test_managed_pipeline_activation.py tests/unit/test_ingest_concurrency.py
All checks passed!
$ .venv/bin/ruff format --check <same seven files>
7 files already formatted
```

## Expected external red in the PA5 line

`tests/unit/test_status_access.py::test_status_route_and_page_header_pass_the_request_audience`
fails on the integration branch itself, and this branch neither causes nor fixes it:

```
E   AssertionError: expected call not found.
E   Expected: mock(Access(rank=0, user_id='reader', ...), settings=<ANY>)
E     Actual: mock(Access(rank=0, user_id='reader', ...), settings={}, structural=True)
```

`src/hippo/status.py:46` now calls `ctx.graph_for(access, structural=True)` — the
production query-session activation from `65b13bc`, "Show authorized empty generations
with held-graph counts" — while the test's mock assertion still expects the old call.
`git diff ffd2265..wp/pa3b` touches neither `src/hippo/status.py` nor
`tests/unit/test_status_access.py`. The orchestrator confirmed it as breakage row Group C
(`test_status_access.py:195`), owned by Task 4b-ii. With it excluded the PA5 line is
165 passed, 2 skipped.

No `filterwarnings` marker and no command-line filter were needed. None of the files in the
PA4 or PA5 CHECK lines imports `fastapi.testclient` at module level — `test_status_access.py`
imports `hippo.web` inside a function — and `-W error` passes as written, so neither
sanctioned AnyIO form applies here.

## Deviations and decisions

1. **A managed delete has no `Busy` precondition.** `_refuse_if_indexing` protects the
   orphan sweep at the end of the legacy delete; a tombstone sweeps nothing, takes no graph
   write lock and mutates no other source. Refusing a suppression because an unrelated
   source is being indexed would keep a withdrawn source readable for the length of someone
   else's index job, against "delete must not wait ... before suppressing" and invariant 2.
   The legacy delete's `Busy` is unchanged, and
   `test_ingest_concurrency.py::test_a_managed_delete_suppresses_while_another_source_is_being_indexed`
   asserts both halves in one test.
2. **A managed delete does not wait for its own job.** `tombstone_managed_source` requests
   cooperative cancellation and never awaits it, so `CANCEL_WAIT_SECONDS` is not spent.
   `test_a_managed_delete_does_not_wait_for_its_own_blocked_build` holds a refresh inside
   `/api/chat`, deletes, and asserts the call returns in under five seconds with the row
   tombstoned; the released worker then never overwrites the tombstone.
3. **An unbounded `operation_id` is refused even for an unmanaged source.** `plan_dispatch`
   validates the identity before the lane is known. Refusing a malformed bounded identity
   the caller supplied is closed input validation, and it happens before any mutation.
4. **`_preflight_managed` catches `AuthorizationChanged` only.** Anything else (a
   programming error, a store outage) propagates rather than being reported as "nothing to
   do". The captured guard is closed immediately; each build captures its own.
5. **A bulk without an actor raises rather than returning 0.** The two refusals are
   different in kind: an actorless bulk over a managed inventory is a caller error that no
   retry fixes, so it raises `ManagedActorRequired`; a preflight that fails is a runtime
   condition whose detail must not be disclosed, so it returns 0. Both happen before any
   clear.
6. **Bulk tests run jobs inline where two managed builds would otherwise share one mock
   transport.** `Setup.inline_jobs()` runs each submitted job in the caller's thread in
   submission order, and `Setup.held_jobs()` captures them without running so a race can
   commit between the plan and the worker. "All legacy clears complete before any job"
   is still proven: `_prepare_reindex` finishes before the submission loop begins, and each
   lane records the clears it observed.
7. **Both reopen tests reassign `w.store` as well as `w.ctx.store`.** The helpers read
   `w.store`, which is the fixture's original object; setting only `ctx.store` left them
   querying a closed database. Caught by the first Ladybug run, which is why that run is
   not the recorded one.
8. **The `mixed` fixture's tombstoned source uses a short distinct text, not `LONG_TEXT`.**
   `LONG_TEXT` is 200 repetitions, which made four Ladybug tests build thousands of chunks
   for no assertion — and the `LONG_TEXT not in citations(...)` check it enabled was
   vacuous, because a citation is one chunk and never the whole text. `THIRD_TEXT` is one
   sentence, so it really is a source's exact citation and its absence after a tombstone is
   a real assertion.
9. **The `mixed` fixture's eligible source is owned by the acting reader.** An `individual`
   role has no `manage_sources` capability, so a legacy text source owned by somebody else
   cannot be converted by that reader — which is what
   `test_a_failed_managed_preflight_clears_nothing_and_starts_nothing` uses to fail a
   preflight naturally rather than by monkeypatching the authority.
10. **Task 3a's `max_chunks` ceiling and the `EmbeddingSpec` prefix helper are unchanged**,
   as the brief directs. So are deviations 2, 4, 5 and 6 of `evidence-pa3a.md`; deviation 7
   is corrected above.
