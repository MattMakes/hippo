# Independent SPEC/QUALITY review: plain-prose coordinator

**SPEC: PASS — QUALITY: FAIL**

Reviewer: `architect-reviewer-1` (herdr fleet), 2026-09-11. Root tree, branch `rag-it-all-tibs`, HEAD `26f9a55`.
Under review (uncommitted): `src/hippo/ingest/prose_generation.py` (763 lines), `tests/unit/test_prose_generation.py` (961 lines).
Contract: `ai_docs/plans/rag-it-all-task-5-prose-coordinator.md` §§4–9, gates §10.
No source or test file was edited by this review.

SPEC passes: none of items a–o is VIOLATED. Two are PROVEN only in part (i, and the coordinator-level
half of c and g); those are recorded as findings, not violations.

QUALITY fails on four counts. The PC2 Ladybug gate is RED and reproduces deterministically (findings 1
and 2, both test-harness timing defects), and two real concurrency defects exist in production code
(findings 3 and 4) — one can lose a committed receipt, the other can fail a build that was about to
publish and throw away a completed inference run.

---

## 1. Gate results

| Gate | Command | Result | Log |
| --- | --- | --- | --- |
| PC1 | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_prose_generation.py -o addopts='' -q -W error` | **59 passed, 1 skipped in 6.69s — EXIT 0** | `/tmp/hippo-prose-review-pc1.log` |
| PC2 | `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_prose_generation.py -o addopts='' -q -W error` | **2 failed, 58 passed in 992.16s — EXIT 1** | `/tmp/hippo-prose-review-pc2.log` |
| PC3 | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_build_authority.py tests/unit/test_managed_prose_preparation.py tests/unit/test_staged_prose_writer.py tests/unit/test_generation_profiles.py tests/unit/test_ingest_concurrency.py -o addopts='' -q -W error` | **136 passed in 5.48s — EXIT 0** | `/tmp/hippo-prose-review-pc3.log` |
| PC4 | `.venv/bin/ruff check <2 files> && .venv/bin/ruff format --check <2 files>` | **All checks passed; 2 files already formatted — EXIT 0** | `/tmp/hippo-prose-review-pc4.log` |

The PC1 skip is `test_ladybug_reopen_preserves_receipt_original_closure_and_runtime_profile`, which is
the real Ladybug close/reopen contract and runs (green) under PC2.

**PC2 failures are deterministic, not flaky.** My independent run failed at the same two ordinal
positions (35 and 54) as the implementer's earlier detached run
(`/tmp/hippo-prose-coordinator-final-ladybug.log`, 2 failed / 58 passed in 936.29s), with identical
assertions:

- `test_two_detached_bootstrap_workers_admit_exactly_one_atomic_winner` — `assert not thread.is_alive()` after `thread.join(10)`
- `test_inflight_model_return_waits_for_renewal_transaction_without_false_ambient_error` — `assert release.wait(10)` returned False

One supporting measurement, outside the four gates:
`HIPPO_TEST_STORE=ladybug … ::test_bootstrap_uses_real_http_and_publishes_complete_bound_originals`
is **18.59 s for a single bootstrap build** (`/tmp/hippo-prose-review-timing.log`). That number is what
sizes the fixes in finding 1.

Both failures are root-caused in findings 1 and 2. Neither is caused by the coordinator's atomicity, fencing or
authority logic; both are wall-clock budgets in the test harness that hold on the Fake store (whole
file: 6.69 s) and cannot hold on Ladybug (whole file: 992 s — 148x slower; finding 9 explains why).

---

## 2. SPEC table (plan §§3–9)

Line references are `src/hippo/ingest/prose_generation.py` unless prefixed. Test references are
`tests/unit/test_prose_generation.py` unless prefixed `test_build_authority.py`.

| # | Requirement | Class | Evidence |
| --- | --- | --- | --- |
| a | Epochs captured **before** live actor/source/workspace resolution (§4) | **PROVEN** | `build_authority.py:343` reads both epochs, `:344` then reads source control, `:346` only then runs `check_local()` (which resolves the live actor). Entered from `:143-145`. Tests: `test_build_authority.py:425 test_captured_epochs_are_readonly_and_do_not_follow_store_changes`; `:373 test_revocation_during_binding_does_not_rebase_to_new_epoch`; coordinator-level `:359 test_setup_cannot_rebase_an_unrelated_authorization_change` |
| b | Source control descriptor excludes counts/progress/`updated_at`; re-read at admission **and** publication (§4) | **PROVEN** | `build_authority.py:88-92` drops `{chunks, documents, counts, code, progress}` from meta; `SourceControl` (`:49-59`) carries no `updated_at`. Re-read at every `check_local` (`build_authority.py:268`), at admission (`_install:504-517`, comparing a freshly captured control against `replace(original, managed=True)`) and at publication (`_publish:606-618`, against `replace(control, active_generation_id=gen.id)`). Tests: `test_build_authority.py:243 test_source_input_change_without_epoch_invalidates_but_progress_does_not`, `:354 test_unknown_source_input_metadata_cannot_evade_control_cas`, coordinator `:379 test_changed_source_control_during_inference_never_installs_bootstrap` |
| c | Reader actor: live enabled user, role, `may_manage_source`, enabled workspace membership; open/preview/synthetic rejected; trusted-local only from an explicit call (§4) | **PROVEN (authority layer) / UNTESTED (coordinator layer)** | `BuildActor.reader` (`build_authority.py:32-42`) rejects non-reader audience, empty or mismatched `user_id`, and `unrestricted`. `_actor_access:202-215` reloads the live user, rejects `disabled`, reloads the role, clamps rank to `min(actor.max_rank, role.rank)` and requires `Principal.may_manage_source`. Workspace membership comes from `EvidenceAccess.require_source` (`:282`) over reviewed mapping authorities (`:271-273`). `trusted_local` is reachable only through the explicit `BuildActor.trusted_local()` classmethod (`:44-46`). Tests: `test_build_authority.py:310 test_open_preview_and_mutable_inputs_cannot_become_build_authority`, `:130 test_live_identity_and_source_management_required`, `:392 test_live_reader_role_is_reloaded_before_management_decision`, `:362 test_local_maintenance_remains_explicit_and_respects_source_suppression`; coordinator `:704 test_published_receipt_still_requires_current_original_authority[user]`, `:304 test_revocation_during_source_request_blocks_followup_and_publication`. **Gap:** no `test_prose_generation.py` case passes a `trusted_local` actor to `build_plain_source`, and none removes the workspace membership (finding 8) |
| d | Policy exactly `AccessPolicy(origin='local_curated', scope_key='source:<id>:plain-prose-v1', mode='workspace')`; existing explicit policies reused; `legacy_unknown` never adopted (§4) | **PROVEN** | Constructed verbatim at `:278-284`. Reuse is by deterministic identity: `AccessPolicy.identity_fields` (`knowledge/model.py:631`) excludes `verified_at` and `expires_at`, so `:285-287` finds an existing policy regardless of verification time and reuses it whole. `:324-326` plans the new policy only when it is both new *and* actually referenced. `build_authority.py:221-233` independently re-derives the exact expected policy and refuses anything else, or any replacement of an existing row; `:248-259` refuses non-`local_curated`, `mode == "unknown"` (i.e. `legacy_unknown`), future `verified_at` and expired policies. Existing artifacts keep their stored `policy_id` because `_pair:260-262` reuses the stored Artifact whole. Tests: `test_build_authority.py:178 test_planned_policy_is_explicit_exact_source_local_grant`, `:219 test_hidden_secondary_span_denies_whole_input_without_overriding_existing_policy`, `:231 test_policy_expiry_rechecked_without_epoch_mutation`; coordinator `:704 [provider]` and `[expired]` |
| e | Model resolution and all inference/file I/O outside store transactions; no callbacks under a lock (§5, §7 step 3) | **PROVEN** | Profile resolution `:666-667`, raw capture `:670-678`, embedding/OpenIE `:702-713`, `_bootstrap_bounds` `:715` — all outside any transaction. The two write transactions (`:695-697`, `:729-741`) contain only store calls: `_install` (store reads/writes plus a read-only `capture_build_authority`), the pure generator `_write_batches` (`knowledge/staged_prose.py:69-73` — "no store, callback or model is retained"), `_write_batch`, `_seal`, `_publish`. `_Run._check:179-187` holds `_Run._lock` plus one transaction containing only `check_local()` and `_check_build`; `on_progress` is invoked at `:237` outside both, `should_stop` at `:162` outside both. Tests: `:317 test_callback_runs_outside_transaction_and_can_cancel_bootstrap` and the fixture's `Runtime.handle:38` assertion ("HTTP inside caller transaction") — both use a `threading.local` depth counter, so they are not fooled by the store's shared counter; `:667 test_worker_start_failure_stops_and_joins_outside_transaction` asserts `close()` runs at depth 0 |
| f | Descriptors sorted by **normalized** logical path before capture; existing Artifact/Revision reused whole, including `observed_at` (§5 steps 3–4) | **PROVEN** | `:674` sorts on `item.logical_path`, which `ByteInput`/`FileInput`/`ExcludedInput` normalise in `__post_init__` (`ingest/accepted_inputs.py:37-38`, `:78`), so the sort key *is* the normalised path. `_pair:259-273` substitutes the entire stored Artifact and the entire stored ArtifactRevision (preserving `observed_at` and `metadata_json`) after validating `(artifact_id, content_hash, provider_revision, raw_uri)`, and raises on conflict. Tests: `:233 test_identical_input_is_noop_and_reordered_descriptors_have_same_identity` (reversed order yields the same generation and no new chats), `:212 test_refresh_keeps_g1_during_model_work_and_reuses_original_revisions` (asserts revision rows are unchanged objects after a second build), `test_build_authority.py:255 test_existing_revision_cannot_be_represented_with_new_observation_metadata` |
| g | Manifest artifact `kind='manifest'`, external ID `accepted-inputs-v1`, metadata `{'accepted_manifest_v1': ...}`; manifest excludes itself (§5 step 5) | **PROVEN (structurally) / UNTESTED (collision case)** | `:307-314` builds `kind="manifest"`, `external_id=MANIFEST_EXTERNAL_ID`, which is `"accepted-inputs-v1"` (`knowledge/generation_profiles.py:22`); `:321` sets metadata to exactly `canonical_json({"accepted_manifest_v1": json.loads(captured.manifest_bytes)})`. Self-exclusion is structural: `capture_raw_inputs` (`:670-678`) receives only the caller's inventory, and the manifest artifact is constructed afterwards at `:307`, so it can never be one of its own raw inputs. Tests: `:169` asserts `{a.kind ...} == {"file", "manifest"}`, `:170` asserts exactly 2 `GenerationMember` rows for a one-file source. **Gap:** no test supplies a file literally named `accepted-inputs-v1` to prove the kind-based collision immunity §5 step 5 claims (finding 8) |
| h | Empty inventory vs all-excluded vs empty originals distinguished; all-excluded rejected even with `allow_empty` (§5) | **PROVEN** | `:679-680` rejects `captured.outcome == "all_excluded"` unconditionally, and before `allow_empty` is ever consulted; `_configuration:345` records `"all_excluded": "reject"` in the captured configuration. Empty inventory and empty originals are gated by `prose_configuration(..., allow_empty=...)` (`:333`). Reader errors and budget exhaustion are hard failures, never emptiness: `ingest/provenance.py:376` raises `UnsupportedProvenanceFormat`, `:385` raises `TooLarge`, and `ingest/readers.py:119-125` raises `TooLarge` rather than truncating. Binary is refused at `:437`. Tests: `:243 test_unsupported_or_all_excluded_input_never_converts_source[ExcludedInput]` runs with `allow_empty=True` and still raises; `:260 test_authoritative_empty_requires_explicit_policy_and_complete_manifest` covers all three empty shapes (no inventory, zero-byte, whitespace-only) and asserts a sealed empty generation |
| i | Refresh: staging Generation only after auth+source lock; renewal worker started outside the transaction; publish transaction rechecks the captured authorization epoch **before and after** `publish_staged_generation`; legacy `publish_generation` never called (§6) | **PROVEN, except the after-publication recheck is UNTESTED** | `:695-697` opens `transaction()`, then `_lock_source`, then `_install`, which inserts the staging Generation at `:486` — inside that lock (`_lock_source` takes the authorization lock first, `store/generations.py:38-39`). `run.start()` is at `:701`, after the `with` block closes. `_publish:580` runs `guard.check_local()` (full epoch + control + live-actor check) before, and `:588-592` re-reads both epochs after. `publish_staged_generation` itself checks suppression, fence, seal and parent but **not** the authorization epoch (`store/generations.py:746-786`), which is exactly why §6 ¶3 requires the coordinator's own before/after pair. `rg` confirms only `publish_staged_generation` is called (`:581`); the legacy `publish_generation` appears nowhere in the module. **Gap:** no test bumps the authorization epoch between `publish_staged_generation` returning and the `:588` comparison (finding 5) |
| j | Bootstrap: nothing persisted before the final transaction; one outer transaction does policy + generation + managed flag + job claim + members + profile binding + callback-free batches + publish with parent `None` (§7) | **PROVEN** | Nothing is written before `:729`; `_install` is invoked at `:733` *inside* that transaction and performs, in order: policy `:484`, Generation `:486`, managed flag `:487`, job claim `:488-493`, Artifact/Revision/member writes under `generation_write` `:494-499`, profile binding `:501`. Batches and seal follow at `:736-740` through the callback-free `_write_batches`/`_write_batch`/`_seal` cores. `_publish:583` passes `expected_parent_id=gen.parent_id`, which is `None` for a legacy source because `_generation:356` takes `parent_id` from `active_generation_id`. Tests: `:181 test_bootstrap_any_install_failure_rolls_back_legacy_serving_state` (6 parametrised fault points; asserts legacy passages, serving source, authorization epoch and graph version all unchanged), `:611 test_bootstrap_publication_tail_failure_rolls_back_source_and_job`, `:525 test_bootstrap_lease_expiry_inside_commit_rolls_back_all_state`, `:573 test_two_detached_bootstrap_workers_admit_exactly_one_atomic_winner` (green on Fake, RED on Ladybug — finding 1) |
| k | Bootstrap limits (1,000 chunks / 50,000 records / 64 MiB) enforced before the transaction, with exact-at and one-over tests (§7) | **PROVEN** | Defaults match §7 exactly: `max_chunks=1000` (`:71`), `max_bootstrap_rows=50_000` (`:72`), `max_bootstrap_bytes=64 * 1024 * 1024` (`:73`). `_bootstrap_bounds` (`:548-575`) runs at `:715`, outside any transaction, and raises before `:729`. The source-metadata envelope pre-check runs even earlier, at `:660-663`, before `run.start()` and before any HTTP. Chunk count is enforced at `:447`, before evidence materialisation. Tests: `:270 test_bootstrap_bound_excess_leaves_no_managed_state` (3 options), `:937 test_bootstrap_canonical_admission_exact_boundary` (observes the real requirement, then re-runs at exactly that value, expecting `published`, and at one below it, expecting rejection, for both rows and bytes), `:928 test_large_source_input_metadata_rejects_before_model_requests_or_managed_write` (asserts `not w.runtime.calls` — no HTTP at all) |
| l | Idempotence: `already_current`, `already_published`, live-duplicate Busy, `operation_id` receipt replay validates job/owner/fence/seal, no lease revival (§8) | **PROVEN** | `_prior_receipt:400-424` resolves under `transaction()` + `_lock_source` + `check_local`, returns `already_published` for a completed operation after `validate_generation_seal` and `validate_generation_profile`, and `already_current` for a different operation whose `manifest_hash` matches the active generation and whose `embedding_mode` is `verified_v1`. `_operation_generation:381-397` rejects multiple matching jobs and any retargeting to different accepted inputs. `_receipt:366-378` requires exactly one published event and validates its payload against `_credentials(job)`, the parent and the aggregate. `_install:474-477` raises `BuildBusy` for a live foreign holder. No lease revival: `claim_generation_build` (`store/generations.py:67`) requires a future lease and accepts only `staging` or unpublished `failed`; expired holders are cleared by `recover_generation_builds` (`store/snapshots.py:263-298`), which then lets `claim_generation_build:107-113` run `_collect_generation` and reset to `staging` — so a retry after a partial write can never append a second OpenIE interpretation. Tests: `:233`, `:430 test_operation_retry_returns_original_retired_receipt_without_moving_head`, `:443 test_operation_identity_cannot_be_retargeted_to_different_inputs`, `:393 test_live_duplicate_operation_cannot_adopt_running_owner`, `:833 test_operation_receipt_requires_its_original_publication_credentials`, `:775 test_expired_attempt_recovery_is_source_scoped_and_uses_fresh_fence` (4 parametrisations; the `ready=False, same_inputs=True` case is the one that actually leaves a partial batch and proves collect-and-reclaim, asserting a strictly greater fencing token and a different lease owner) |
| m | Failure: heartbeat stop/join outside transactions; `fail_generation_build` used only by the holder; G1 never touched (§8) | **PROVEN** (with findings 4 and 6 against its robustness) | `run.pause()` is called at `:685`, `:693`, `:727` and `:749`, and `run.close()` at `:763` — every one outside any transaction (an exception inside `with run.store.transaction():` unwinds the `with` before the `except` body runs). `fail_generation_build` at `:754` is guarded by `installed and run.job is not None and run.receipt is None`; the store enforces holder identity independently through `_check_build` (`store/generations.py:175-181`) and refuses to fail a published generation (`:183-191`). G1 is never touched: `recover_generation_builds` skips generations whose status is not `staging`/`ready`/`failed` (`store/snapshots.py:273`), and `fail_generation_build` refuses when the generation is the source's `active_generation_id`. Tests: `:286 test_refresh_model_failure_preserves_last_good_generation`, `:642 test_refresh_cancellation_marks_only_owned_job_cancelled` (asserts `cancelled`/`build_cancelled` and a cleared `active_build_id`), `:667 test_worker_start_failure_stops_and_joins_outside_transaction` (bootstrap/refresh x partial/clean start), `:330 test_postcommit_release_revocation_does_not_mark_published_generation_failed`, `:775` (asserts the unrelated source's job and generation are unchanged) |
| n | No raw deletion of any kind; none of `_clear_passages`, `delete_passages_for_source`, `delete_code_for_source`, `remove_orphans`, `rmtree`, `discard_generation`, `store.delete_source` (§9) | **PROVEN** | `rg -n "delete\|remove\|unlink\|purge\|clear\|drop\|rmtree\|collect" src/hippo/ingest/prose_generation.py` returns **no matches at all** — broader than the brief's enumerated list — and the module contains no filesystem call of any kind. The only row removal anywhere on this path is `_collect_generation` inside `claim_generation_build` (`store/generations.py:110`), which is the controlled failed-generation reclaim §8 mandates and touches no raw objects. Test: `:748 test_refresh_dimension_change_preserves_held_g1_and_conservative_raw_objects` monkeypatches `delete_source`, `delete_passages_for_source`, `delete_code_nodes_for_source` and `remove_orphans` to `pytest.fail`, and asserts every raw blob on disk is byte-identical after a full dimension-changing refresh |
| o | Receipt/logs/errors contain no source text, raw bytes, absolute paths, manifest JSON, prompts, model bodies or `str(exc)` (§3, §9) | **PROVEN** | `BuildReceipt` (`:119-125`) is five scalars. Every `raise` in the module uses a fixed literal string — no f-string interpolates content, and `str(exc)` appears nowhere; `:217` chains with `raise ... from error` rather than quoting. The module imports no logger and emits no log record. The only source-row write is `:597-605`, which sets `error=None`. Upstream error text was checked too: `ingest/provenance.py:385` quotes the *logical* path only, and `ingest/accepted_inputs.py` has exactly one interpolating raise (`:34`, a field name). Tests: `:171` asserts the receipt's exact field set; `:301` asserts `"private"` (the mock provider's 400 body) never reaches `source["error"]` |

---

## 3. Findings

Two blockers, three majors, six minors.

### 1. `[blocker]` PC2 is RED: the two-worker test's join and barrier budgets are Fake-store sized

**`tests/unit/test_prose_generation.py:602` (`thread.join(10)`) and `:21` (`barrier.wait(timeout=5)`)**

`test_two_detached_bootstrap_workers_admit_exactly_one_atomic_winner` starts two threads that each run
a complete bootstrap build, then asserts `not thread.is_alive()` after a 10-second join. On Ladybug the
assertion fails. The observed `assert not True` is a thread that had not *finished*, not a hang — the
suite went on to complete all 60 tests, so both threads did terminate.

Why 10 s cannot work here. Every store serialises transactions with a lock held for the whole
transaction body (`store/ladybug.py:378-384` takes `self._lock`, an `RLock`, around `BEGIN`/`COMMIT`).
The winner's final bootstrap transaction (`:729-741`) writes every batch, the seal, the publication
event and the source row under that lock, so the loser is blocked for the winner's *entire* commit and
only then fails. The two builds are therefore close to fully serialised, and a single Ladybug build
already costs far more than 10 s. I measured it directly:

```
$ HIPPO_TEST_STORE=ladybug .venv/bin/pytest \
    tests/unit/test_prose_generation.py::test_bootstrap_uses_real_http_and_publishes_complete_bound_originals \
    -o addopts='' -q -W error --durations=0
18.59s call  test_bootstrap_uses_real_http_and_publishes_complete_bound_originals
1 passed in 19.24s
```

(log: `/tmp/hippo-prose-review-timing.log`). **One** uncontended Ladybug bootstrap is 18.59 s. Two
serialised ones cannot finish inside a 10-second join under any scheduling. For comparison, the same
test on Fake is part of a 6.69 s whole-file run — finding 9 explains the 148x gap.

`barrier.wait(timeout=5)` has the same problem from the other side: the barrier must absorb the skew
between the two threads' pre-inference phases, which are themselves a large fraction of those 18.59 s.
If one thread reaches `/api/chat` more than 5 s after the other, the barrier breaks and both builds die
with `BrokenBarrierError`, surfacing as a different and more confusing failure.

This is a test-harness defect, not a coordinator defect. The atomicity property the test exists to
prove — exactly one `BuildReceipt`, one `Generation`, one `IndexEvent`, and a valid seal — is sound and
passes on Fake.

*Failure scenario:* run PC2 on any machine. Thread 1 has not finished its serialised bootstrap 10 s
after start; `assert not thread.is_alive()` fails; the gate is RED and reads like a deadlock.

*Why it matters:* PC2 is one of eight gates and the slice cannot be committed while it is RED. The
current message points the reader at the coordinator's locking, which is not where the problem is.

*Proposed fix* (test-only, no production change):

```python
barrier.wait(timeout=120)   # was 5
...
    thread.join(300)        # was 10
    assert not thread.is_alive()
```

Better still, derive the budget from the backend so the Fake run keeps its fast failure mode — e.g. a
module-level `slow = setup.store.knowledge_backend != "fake"` and `timeout=120 if slow else 5`.

I do **not** expect finding 3's `:745` variant to keep this test red once the budgets are raised — see
that finding for why the winner almost always wins that particular race. Raising the two budgets should
be sufficient; if it is not, finding 3 is the next thing to look at.

### 2. `[blocker]` PC2 is RED: the renewal-race test's release window opens before the build, not at the rendezvous

**`tests/unit/test_prose_generation.py:892` (`assert release.wait(10)`), caused by `:92-94` and `:99-100` (the `unblock` helper)**

`test_inflight_model_return_waits_for_renewal_transaction_without_false_ambient_error` wires four
events. The helper thread is started at `:100`, *before* `build(...)` at `:915`, and immediately begins
`checking.wait(10)`. `checking` can only be set after `held`, and `held` can only be set once a worker
is already blocked inside `/api/chat` — that is, after the entire pre-inference phase of a refresh
build (authority capture, raw capture, `bind_inputs`, `_prior_receipt`, `_materialize`, the whole
`_install` transaction, heartbeat start, embeddings).

On Fake that phase costs milliseconds, so the helper's 10-second budget is never at risk. On Ladybug it
exceeds 10 s. The helper then times out and returns **without setting `release`**; nothing else ever
sets it; and the renewal thread — parked at `:892` while holding both `_Run._lock` and an open store
transaction — fails its own `release.wait(10)`. `_Run.renew:214-217` converts that into a sticky
`AuthorizationChanged`, which the next `run.check()` re-raises, and the build dies. The chain is
visible verbatim in `/tmp/hippo-prose-review-pc2.log` (and at `:135-190` of the earlier detached log).

Again: harness timing, not a coordinator defect. The property under test — that a worker thread can
enter `_Run.check` while the renewal thread holds a store transaction, without a false
ambient-transaction error — is real and worth testing. Finding 3 shows it is real in a way this test
does not yet cover.

*Failure scenario:* run PC2 on Ladybug. The refresh build's pre-inference phase takes longer than 10 s;
the helper exits; the renewal thread times out; the build fails with
`AuthorizationChanged: Plain build lease renewal failed`.

*Why it matters:* same as finding 1, with the added cost that the failure presents as an authorization
error and sends the reader into `build_authority.py` rather than into the harness.

*Proposed fix* (test-only). Remove the wall clock from the helper entirely and let teardown be what
unblocks it:

```python
def unblock():
    held.wait()
    checking.wait()
    release.set()

...
finally:
    held.set()          # new: guarantee the helper leaves held.wait()
    checking.set()      # new: guarantee the helper leaves checking.wait()
    release.set()
    helper.join(10)
    assert not helper.is_alive()
```

Unbounded waits are safe here precisely because the existing `finally` at `:922-925` always runs — on
success, on assertion failure, and on any error before the rendezvous. Adding `held.set()` and
`checking.set()` to that block is what makes them safe; without it an unbounded `held.wait()` would hang
the helper whenever the build fails before reaching `/api/chat`, and the `assert not helper.is_alive()`
would then mask the real error. Do not substitute a larger timeout (`held.wait(300)`): that reintroduces
the same masking, just more slowly.

### 3. `[major]` The ambient-transaction probe is process-global, so concurrent builds reject each other — and can lose a committed receipt

**`src/hippo/ingest/prose_generation.py:652`; `src/hippo/knowledge/build_authority.py:167-168`, used at `:304`, reached from `prose_generation.py:745`**

```python
# prose_generation.py:652
if getattr(ctx.store, "_transaction_depth", 0) or getattr(ctx.store, "_transaction", None) is not None:
    raise ValueError("Coordinator requires no ambient transaction")
```

`_transaction_depth` and `_transaction` are plain instance attributes shared by every thread using the
store (`store/ladybug.py:270,384`; `tests/fakes/fake_store.py:125,142`; `store/base.py:232,241`). Each
store holds its lock for the whole transaction body, so while *any* thread is inside a transaction the
counter is non-zero for *all* threads.

Two consequences, both on the concurrency plan §1 explicitly requires ("Bootstrap workers may compute
the same input concurrently") and that Task 3's job dispatch will create:

1. A second `build_plain_source` entered while another build is inside any transaction — `bind_inputs`
   (`build_authority.py:321`), `_prior_receipt` (`:402`), `_install` (`:695`) — is rejected with
   `ValueError("Coordinator requires no ambient transaction")`, a message that blames the caller for
   something the caller did not do.
2. A second, narrower variant: `:745` `run.guard.check()` runs **after** the publication transaction
   has committed, and `BuildAuthority.check` begins with
   `if _ambient(self._store): raise RuntimeError(...)` (`build_authority.py:303-304`). If another
   thread's transaction is open at that instant, a build that committed correctly raises
   `RuntimeError("External build checks require no ambient transaction")` and its caller never receives
   the `BuildReceipt`. The generation is correctly left `active` and the job `completed` (`run.job` is
   `None` at `:743`, so the `fail_generation_build` branch at `:752` is skipped), so §6's "must not
   mislabel the already committed generation as failed" still holds — but the caller cannot tell
   success from failure without re-entering the coordinator with the same `operation_id`.

   I want to be precise about how likely this is, because it is easy to overstate. In the two-worker
   race specifically the winner is heavily favoured: it exits `transaction()` at `:741` (the `finally`
   decrements the depth, then the `RLock` releases) and runs straight through `:742-:745` as pure
   Python with no GIL-releasing call — `adopt` takes two uncontended locks and `_ambient` is two
   attribute reads — while the loser is parked in `RLock.acquire()` and needs the GIL to run `BEGIN`
   and increment the depth. So the winner almost always reaches `_ambient` first, which is consistent
   with `:573` passing 59/59 on Fake. The variant that actually bites in production is (1): a *new*
   build entering at an arbitrary point inside another build's transaction, where there is no such
   ordering advantage.

*Failure scenario:* two sources build concurrently on one store — exactly what Task 3's in-process Jobs
scheduler does. Build A is inside `_prior_receipt`'s transaction; build B calls `build_plain_source`
and is rejected with a false ambient error and no work done. Or: build A publishes and commits, build
B's transaction opens in the same instant, and build A's `:745` check raises `RuntimeError` even though
A's generation is live, sealed and correct — so A's caller cannot tell success from failure.

*Why it matters:* the coordinator's stated concurrency contract does not hold. The receipt-loss variant
is the harder one to debug in production, because the database state is entirely correct.

*Proposed fix:* make the probe thread-aware rather than global. Record the owning thread when a
transaction opens, and expose it:

```python
# in each store's transaction(), alongside the depth increment
self._transaction_thread = threading.get_ident()   # cleared when depth returns to 0

# shared
def in_ambient_transaction(self):
    return bool(self._transaction_depth) and self._transaction_thread == threading.get_ident()
```

then have `build_plain_source:652` and `build_authority._ambient` call `store.in_ambient_transaction()`.
This is a store-layer change and therefore outside this slice's file ownership — the orchestrator
should decide whether it lands here or in the activation slice — but it must land **before** any
production route calls the coordinator concurrently. Note that the test fixture already models the
correct semantics with a `threading.local` depth counter
(`tests/unit/test_prose_generation.py:87-99`): production is the side that is wrong, not the test.

### 4. `[major]` `_Run._check` re-reads `self.heartbeat` after testing it for `None`, so `pause()` can crash the renewal thread

**`src/hippo/ingest/prose_generation.py:174-175` and `:187-188`; the racing writer is `:228`**

```python
# :174-175, and again at :187-188
if self.heartbeat is not None:
    self.heartbeat.check()

# :227-231
def pause(self):
    heartbeat, self.heartbeat = self.heartbeat, None    # <- nulls the attribute first
    if heartbeat is not None:
        heartbeat.close()                               # <- only then joins the thread
```

`pause()` clears `self.heartbeat` *before* it closes and joins the worker, so the renewal thread is by
construction still running when the attribute becomes `None`. Neither read is under `_Run._lock` — that
lock is only taken at `:179`. If the renewal thread sits between the `is not None` test and the
`.check()` call when the owning thread executes `:228`, it raises
`AttributeError: 'NoneType' object has no attribute 'check'`.

That exception is caught by `_Run.renew:214-217`, converted into
`AuthorizationChanged("Plain build lease renewal failed")`, and latched into `_Run._failure`, from
where the owning thread's next `check()` re-raises it.

*Failure scenario:* a refresh build finishes inference and calls `run.pause()` at `:727`, one line
before the publication transaction. The renewal thread happens to be inside `_check` at that instant.
`pause()` nulls the attribute; the renewal thread raises `AttributeError`; `pause()`'s own
`heartbeat.check()` at `:231` re-raises it as `AuthorizationChanged`; and the build fails at `:727`
*after* a complete, correct OpenIE run, with `installed=True` and `run.job` set — so `:754` marks the
job `failed` and the entire inference pass is discarded. Nothing is corrupted, but the work is lost and
the reported cause is wrong. The window is one bytecode gap wide, but it is entered on *every*
`pause()`, and the tests that set `renewal_interval_seconds=0.01` drive `_check` through it hundreds of
times.

*Why it matters:* it converts a healthy build into a failed one and burns a full model run, and the
error it reports sends the operator looking at permissions.

*Proposed fix:* snapshot the attribute once, and reuse the same snapshot for both calls (which is also
more correct — it keeps the pre-check and post-check on the same worker):

```python
def _check(self):
    self._cancel()
    heartbeat = self.heartbeat
    if heartbeat is not None:
        heartbeat.check()
    with self._lock:
        ...
    if heartbeat is not None:
        heartbeat.check()
    self._cancel()
```

### 5. `[major]` The after-publication authorization recheck — the one check the plan says the store cannot do for you — has no test

**`src/hippo/ingest/prose_generation.py:588-592`**

Plan §6 ¶3 is unusually specific: "The existing strict publish method checks suppression/fence/seal/parent
but not the caller's captured authorization epoch. Therefore the coordinator's encompassing publication
transaction must perform that explicit check before **and after** publication... This is not satisfied by
a check just before entering the transaction." I confirmed the premise: `publish_staged_generation`
(`store/generations.py:746-786`) validates suppression, fence, seal and parent, and never reads
`authorization_epoch()`.

The coordinator's code is present and correct-looking. But no test exercises it. Every authorization
test either revokes before entry (`:704 test_published_receipt_still_requires_current_original_authority`)
or during inference (`:304`, `:379`), and both are caught by earlier guards.
`:330 test_postcommit_release_revocation_does_not_mark_published_generation_failed` looks like the right
test but is not: its patched `transaction()` fires `update_user(disabled=True)` only when
`_transaction_depth` is 0 and `_transaction` is `None` (`:343-345`), i.e. after the *outer* transaction
commits — strictly later than `:588`.

*Failure scenario:* someone refactors `_publish` and drops or reorders the `:588-592` comparison. Every
test still passes on both backends, and a build whose authorization is revoked inside the publication
transaction publishes anyway.

*Why it matters:* this is the single check the plan singles out as unavailable from the store layer. An
untested security check is one refactor away from being an absent one.

*Proposed fix:* use the `fault_hook` parameter `publish_staged_generation` already exposes
(`store/generations.py:727`, invoked at `:785` and `:789`) — or monkeypatch `store._source_fields` — to
bump the authorization epoch between the publication write and the coordinator's recheck, then assert
`build_plain_source` raises `AuthorizationChanged` and that the transaction rolled back (no
`active_generation_id`, no `IndexEvent`). Add the symmetric case for `suppression_epoch`.

### 6. `[minor]` `_Run.renew` relabels a cancellation as an authorization failure

**`src/hippo/ingest/prose_generation.py:214-217`**

`renew()` wraps *every* exception, including the `BuildCancelled` that `_cancel():162-163` raises when
`should_stop()` flips on the renewal thread. `_Run._failure` keeps the first exception, which is the
original `BuildCancelled` (`check()` at `:165-170` latches it before `renew`'s handler runs), so the
common path still surfaces the right type. But `LeaseHeartbeat` stores the *wrapper*
(`knowledge/lease_heartbeat.py:44-46`), and `pause()` calls `heartbeat.check()` at `:231`, which raises
`AuthorizationChanged("Snapshot lease renewal failed; repeat the query")`.

*Failure scenario:* the caller's `should_stop()` becomes true while the renewal thread is mid-tick, and
the owning thread reaches `run.pause()` at `:727` before its own next `check()`. The caller receives
`AuthorizationChanged` instead of `BuildCancelled`, and `:757`'s `isinstance(error, BuildCancelled)` is
false, so the job is marked `build_failed` rather than `build_cancelled`.
`:642 test_refresh_cancellation_marks_only_owned_job_cancelled` does not cover this, because it flips
the flag from the progress callback on the owning thread.

*Proposed fix:* let cancellation through unchanged.

```python
except BuildCancelled:
    raise
except BaseException as error:
    failure = AuthorizationChanged("Plain build lease renewal failed")
    ...
```

### 7. `[minor]` `PlainBuildOptions` and `build_plain_source` drift from the plan §3 contract

**`src/hippo/ingest/prose_generation.py:61-109` and `:622-635`**

Plan §3 specifies `PlainBuildOptions` as carrying "pipeline/parser/materializer versions, effective
chunk size/overlap, synonym threshold, empty policy, capture limits, maximum decoded characters/chunks/
prepared rows/prepared bytes, writer batch size, lease duration and renewal interval". The
implementation:

- **omits** the pipeline/parser/materializer version fields. They are hard-coded in
  `_configuration:336-340` (`"plain-source-v1"`, `"plain-utf8-sig-v1"`, `MATERIALIZER_VERSION`,
  `"mapped-prose-v1"`).
- **adds** `workers: int = 2`, an operational field the plan does not list (§5 step 2 does say
  "operational worker count ... do not enter representation identity", and it correctly does not — it is
  absent from `_configuration`).
- `build_plain_source` **adds** `embedding_cache: EmbeddingCache | None = None`, not in §3.
- the plan's parameter type annotations are absent from the implementation; only `embedding_cache`
  carries one.

The hard-coding is arguably the safer choice — a caller cannot fabricate a version string and so cannot
forge generation identity — and none of this breaks the imports Task 3 needs. But §3 is the document
the activation slice will read, and the plan's "Coordinator implementation notes" do not record these
deviations.

*Failure scenario:* the activation slice reads §3, writes `PlainBuildOptions(parser_version=...)`, and
gets `TypeError`.

*Proposed fix:* no code change. Add two sentences to the plan's "Coordinator implementation notes"
recording that the versions are fixed constants rather than options, and that `workers` and
`embedding_cache` were added. Plan ownership is not mine, so this is flagged for the orchestrator.

### 8. `[minor]` Three coordinator-level coverage gaps

**`tests/unit/test_prose_generation.py`**

- **`trusted_local` actor.** `BuildActor.trusted_local()` is covered at the authority layer
  (`test_build_authority.py:195`, `:362`) but is never passed to `build_plain_source`. Every case in
  `tests/unit/test_prose_generation.py` uses `BuildActor.reader` (`:111`). §4 calls trusted-local "an
  internal capability for this local operation"; the coordinator path for it is unexercised.
- **Missing workspace membership.** No coordinator test deletes or disables the `WorkspaceMembership`
  row created at `:104-109`. §4 requires "an enabled workspace membership from reviewed mapping
  authorities"; only `test_build_authority.py:156` covers it.
- **Manifest name collision.** §5 step 5 asserts "A file literally named `accepted-inputs-v1` cannot
  collide because the artifact kind differs." No test supplies `ByteInput("accepted-inputs-v1", ...)`.

*Failure scenario:* a future change to `_accepted_pairs` keys the manifest artifact on `external_id`
alone; the collision goes unnoticed and a user's file silently becomes the manifest.

*Proposed fix:* three small cases — a `trusted_local` build, a membership-removal denial, and a
collision build asserting two Artifacts with distinct kinds and the same `external_id`.

### 9. `[minor]` Authority checking is hot enough to be the reason PC2's budgets fail

**`src/hippo/ingest/prose_generation.py:233-243` and `:677`; `src/hippo/knowledge/build_authority.py:70-75`, `:261-299`**

`_Run.progress` calls `self.check()` at `:234`, again in the `finally` at `:242`, and again at `:243` —
two or three times per progress tick, with the `:243` call redundant against `:242` whenever
`on_progress` is set. Each `check()` opens a store transaction and runs `guard.check_local()` **twice**
(`:181`, `:185`). Each `check_local` calls `_source_control`, which does
`any(r.source_id == source_id for kind in ("Artifact", "Generation") for r in store._knowledge_rows(kind))`
(`build_authority.py:70-75`) — a full scan of both tables — and then re-runs `_source_control` a second
time at `:292`. Raw capture pays the same price on every poll, through
`should_stop=lambda: (run.check(), False)[1]` at `:677`.

On Fake these are dictionary walks. On Ladybug each is Cypher. The 148x gap between the backends
(6.69 s against 992 s for the same 60 tests) is what turned findings 1 and 2 from latent into RED.

*Failure scenario:* Task 3 routes a real 500-file source here; each progress tick costs several full
table scans per chunk, and ingestion latency scales with total corpus size rather than with source size.

*Why it matters:* not a correctness defect, but it sets the cost of every future Ladybug/Neo4j gate run
and the latency of production ingestion.

*Proposed fix:* (a) drop the redundant `:243` `check()`; (b) in `_source_control`, use the existing
`store.source_is_managed` (`store/generations.py:24-26`) plus a targeted lookup instead of two full
table scans, falling back to the scan only when the narrow flag is false. Both live outside this slice's
file ownership (`build_authority.py` is a reviewed primitive), so this is a note for the next increment
rather than a change request here.

### 10. `[minor]` The bootstrap budget envelope hand-copies the payload `_publish` writes

**`src/hippo/ingest/prose_generation.py:521-545` against `:594-605`**

`_bootstrap_envelope` reconstructs, with upper-bound values, the source row `_publish` will later write:
the same `meta` keys (`chunks`, `documents`) and the same
`status`/`stage`/`progress_done`/`progress_total`/`error` fields. Nothing links the two.

*Failure scenario:* `_publish` gains a meta key. The pre-transaction budget silently under-counts, and
an over-budget build reaches the commit it was supposed to be rejected before. Today the 16 KiB
`BOOTSTRAP_LIFECYCLE_BYTES` reserve absorbs the known slack (for instance `active_generation_id` is
still `None` when measured), so this is a maintenance hazard rather than a live bug.

*Proposed fix:* extract one `_source_presentation(meta, chunks, documents)` helper and call it from both
sites, so a new field cannot be added to one without the other.

### 11. `[minor]` The brief's stated import path for the input types does not exist

**`src/hippo/ingest/prose_generation.py:39`**

The review brief states that the next slice "will import `build_plain_source`, `PlainBuildOptions`,
`BuildProgress`, `BuildReceipt`, `ByteInput`/`FileInput`/`ExcludedInput` from this module". The first
four are defined in `prose_generation.py`. The last three are not, and are not re-exported: `:39`
imports only `CaptureLimits` and `capture_raw_inputs` from `accepted_inputs`.

*Failure scenario:* the activation slice writes
`from hippo.ingest.prose_generation import ByteInput, FileInput, ExcludedInput` and gets `ImportError`.

*Why it matters:* it is a one-line mismatch, but it is in the handoff text the next worker will follow
literally, so it costs that worker a debugging cycle at the very start of their task.

*Proposed fix:* either correct the next brief to say `hippo.ingest.accepted_inputs` (which is what
`tests/unit/test_prose_generation.py:13` already does), or add an explicit re-export to
`prose_generation.py`. I recommend correcting the brief: the three types belong to the accepted-inputs
primitive, and re-exporting them through the coordinator would blur that ownership.

### Observations (no action)

The losing bootstrap racer receives `AuthorizationChanged`, where §7 step 1 says the coordinator "may
return `already_current` after proving equality". The plan says *may*, so this is not a violation, but
`:605` (`assert sum(isinstance(value, AuthorizationChanged) ...) == 1`) now locks the behaviour in, and
Task 3 will have to handle a losing concurrent build as an error rather than as a no-op.

A retry with the same `operation_id` against a generation that is still **active** returns
`already_published`, not `already_current` (`_prior_receipt:406` tests the operation branch before the
active branch). Plan §8 does not fix the label for this case and both values are truthful, but Task 3
will branch on `outcome` — worth deciding deliberately rather than inheriting.

---

## 4. Verbatim public signatures

Reproduced exactly from the working tree at HEAD `26f9a55` plus uncommitted changes.

### `build_plain_source` — `src/hippo/ingest/prose_generation.py:622-635`

```python
def build_plain_source(
    ctx,
    *,
    source_id,
    actor,
    inputs,
    options,
    raw_store,
    embedding_spec,
    operation_id,
    should_stop,
    on_progress=None,
    embedding_cache: EmbeddingCache | None = None,
):
```

Returns `BuildReceipt`. Raises `ValueError` (including the `BuildBusy` subclass),
`AuthorizationChanged`, `BuildCancelled`, and whatever the model and raw layers raise
(`OllamaError`, `TooLarge`, `UnsupportedProvenanceFormat`).

Entry validation, `:636-653`: `actor` must be exactly `BuildActor`, `options` exactly
`PlainBuildOptions`, `embedding_spec` exactly `EmbeddingSpec`, `inputs` exactly `tuple`;
`operation_id` a non-empty `str` of at most 256 characters; `should_stop` callable; `on_progress`
`None` or callable; and no ambient store transaction (see finding 3).

### `PlainBuildOptions` — `:61-109`

```python
@dataclass(frozen=True)
class PlainBuildOptions:
    chunk_size_chars: int = 1500
    chunk_overlap_chars: int = 200
    synonymy_threshold: float = 0.8
    allow_empty: bool = False
    capture_limits: CaptureLimits = field(
        default_factory=lambda: CaptureLimits(8_000_000, 16_000_000, 128, 1_000_000)
    )
    max_decoded_chars: int = 2_000_000
    max_chunks: int = 1000
    max_bootstrap_rows: int = 50_000
    max_bootstrap_bytes: int = 64 * 1024 * 1024
    batch_size: int = 128
    workers: int = 2
    lease_duration_seconds: float = 300.0
    renewal_interval_seconds: float = 30.0
```

`__post_init__` (`:79-109`) enforces: `chunk_size_chars`, `max_decoded_chars`, `max_chunks`,
`max_bootstrap_rows`, `max_bootstrap_bytes`, `batch_size` and `workers` are `int` and `> 0`;
`chunk_overlap_chars` is `int` and `>= 0`; `allow_empty` is `bool`; `capture_limits` is exactly
`CaptureLimits`; `synonymy_threshold` is a finite `int`/`float` in `[0, 1]`; both lease intervals are
finite and `> 0`; and `renewal_interval_seconds < lease_duration_seconds / 2`.
All type checks use `type(x) is not T`, so subclasses are rejected.

### `BuildProgress` — `:112-116`

```python
@dataclass(frozen=True)
class BuildProgress:
    phase: str
    completed: int = 0
    total: int = 0
```

Emitted phases: `"capture"` (`:665`), `"reading"` (`:428`), and `"extract"` (`:712`, carrying
`completed`/`total`).

### `BuildReceipt` — `:119-125`

```python
@dataclass(frozen=True)
class BuildReceipt:
    source_id: str
    generation_id: str
    event_id: str
    accepted_input_hash: str
    outcome: str
```

`outcome` is one of `"published"` (`:619`), `"already_current"` (`:422`) or `"already_published"`
(`:412`). `accepted_input_hash` is `captured.manifest.sha256`.

### Exceptions — `:53-58`

```python
class BuildCancelled(RuntimeError):
    """Cancellation reached a cooperative checkpoint before commit admission."""


class BuildBusy(ValueError):
    """Another invocation owns the live source build or changed its head."""
```

### Module constants — `:48-50`

```python
BOOTSTRAP_BUDGET_VERSION = "plain-bootstrap-budget-v1"
BOOTSTRAP_LIFECYCLE_RECORDS = 12
BOOTSTRAP_LIFECYCLE_BYTES = 16 * 1024
```

### Input types — `src/hippo/ingest/accepted_inputs.py:44-92`

```python
@dataclass(frozen=True, slots=True)
class ByteInput:
    logical_path: str
    data: bytes
    media_type: str = "text/plain"
    provider_revision: str | None = None


@dataclass(frozen=True, slots=True)
class FileInput:
    logical_path: str
    path: Path
    media_type: str = "text/plain"
    provider_revision: str | None = None


@dataclass(frozen=True, slots=True)
class ExcludedInput:
    logical_path: str
    reason: Literal["configured_exclusion"] = "configured_exclusion"


@dataclass(frozen=True, slots=True)
class CaptureLimits:
    max_input_bytes: int
    max_total_bytes: int
    max_inputs: int
    max_manifest_bytes: int
```

All three input types normalise `logical_path` in `__post_init__` (`accepted_inputs.py:37-38`, `:78`).
`FileInput.path` must be absolute and free of `..` (`:67-69`).

**Import note for Task 3 (finding 11).** The brief states the activation slice will import `ByteInput`,
`FileInput` and `ExcludedInput` "from this module". It cannot: `prose_generation.py:39` imports only
`CaptureLimits` and `capture_raw_inputs` from `accepted_inputs`, so the three input classes are not
re-exported through `hippo.ingest.prose_generation`. Import them from `hippo.ingest.accepted_inputs`
(which is what `tests/unit/test_prose_generation.py:13` does), or add an explicit re-export to the
coordinator module.

### `BuildActor` — `src/hippo/knowledge/build_authority.py:17-46`

```python
@dataclass(frozen=True, slots=True)
class BuildActor:
    kind: Literal["reader", "trusted_local"]
    user_id: str | None = None
    max_rank: int = 0

    @classmethod
    def reader(cls, principal): ...

    @classmethod
    def trusted_local(cls): ...
```

---

## 5. Checked and cleared (so it is not re-chased)

- **Cross-thread transaction merging.** All three stores hold a lock for the entire transaction body
  (`store/ladybug.py:379`, `tests/fakes/fake_store.py:120`, `store/base.py:227`), so two threads'
  transactions cannot interleave or roll each other's writes back. `_Run._lock` is belt-and-braces, not
  load-bearing, for isolation. The *probe* on those counters is still wrong — finding 3.
- **Retry after a partial staged write.** `recover_generation_builds` (`store/snapshots.py:284-296`)
  marks the expired job and generation `failed`; `claim_generation_build:107-113` then runs
  `_collect_generation` and resets to `staging`. Non-deterministic OpenIE therefore cannot append a
  second interpretation beside a first partial batch, and `:775 [ready=False, same_inputs=True]` does
  exercise that path with a real partial batch on disk.
- **Policy reuse across refreshes.** `AccessPolicy.identity_fields` (`knowledge/model.py:631`) excludes
  `verified_at`, so `:285`'s lookup by `policy.id` hits even though `:283` sets `verified_at=now`. No
  policy churn per refresh, and no expiry extension.
- **Silent budget truncation.** `TextBudget.add` raises `TooLarge` (`ingest/readers.py:119-125`) and
  `read_plain_provenance` raises rather than returning a truncated outcome (`ingest/provenance.py:376`,
  `:385`). No partial source can publish.
- **Effective chunk parameters.** `_configuration:330-331` computes `max(MIN_CHUNK_CHARS, size)` and
  `min(overlap, size // 3)`, which is exactly what `prepare_prose_chunks` re-applies
  (`ingest/prepared_chunks.py:377-378`). The values recorded in the captured configuration are the
  effective ones.
- **Managed-classification divergence.** `_source_control` derives `managed` broadly — flag, active
  generation, meta, or any Artifact/Generation row (`build_authority.py:67-76`) — while `_install:480`
  uses the narrow `store.source_is_managed`. They can disagree only for a source with stray rows and no
  flag, which `:658-659` rejects before any work with "Managed source needs explicit recovery before
  initial publication".
- **`_write_batches` purity.** It is a generator over prepared data holding no store, callback or model
  (`knowledge/staged_prose.py:69-73`), so calling it once in `_bootstrap_bounds` outside the transaction
  and again inside it at `:736` is deterministic and side-effect free.
- **Test-only hooks in production paths.** The per-thread transaction-depth instrumentation lives
  entirely in the test fixture (`tests/unit/test_prose_generation.py:87-99`); production code never
  references it. `publish_staged_generation` and `bind_generation_embedding_profile` expose `fault_hook`
  parameters and the coordinator passes none.
- **Mocks bypassing their boundary.** I looked specifically for this. The injected-failure tests
  (`:181`, `:611`, `:525`) all raise *after* the real store write, so rollback is genuinely exercised.
  `:833` corrupts `IndexEvent.payload_json` globally, but the assertion still lands on `_receipt`'s
  credential comparison at `:373`. `:748` turns deletion calls into `pytest.fail`, which is an assertion
  rather than a bypass. I found no test whose pass depends on a mock short-circuiting the boundary it
  claims to cover.
