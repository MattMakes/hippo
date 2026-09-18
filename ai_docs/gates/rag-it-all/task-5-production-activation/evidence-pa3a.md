# Evidence: production activation Task 3a — managed adapter, eligibility, add/bootstrap/refresh dispatch

**Branch:** `wp/pa3a`, worktree `.worktrees/pa3a`, base `158ebf2` (rag-it-all-tibs).
**Scope:** PA1 (pipeline half), PA3, PA5 (single-source half), PA7 (pipeline half).
Delete, `reindex_all` and mixed bulk dispatch are Task 3b and are untouched here.

## Commits

| Hash | Subject |
|---|---|
| `0863b8f` | Decide the managed plain-prose lane on the saved source alone |
| `efc1075` | Send an authenticated eligible source through the coordinator, not the clear |
| `98aac44` | Keep a failure that cannot be written from becoming a report |
| (the commit adding this file) | Record the PA3a evidence |

## Files

| File | Change |
|---|---|
| NEW `src/hippo/ingest/managed_activation.py` | The whole adapter: eligibility, dispatch plan, ingress discipline, option/spec capture, presentation, closed failure mapping. |
| `src/hippo/ingest/pipeline.py` | `build_actor`/`operation_id` on `add_text`, `add_upload`, `start_indexing`, `run_indexing`, `reindex`; the managed lane in `run_indexing`; `source_dir` delegates to the adapter. |
| `src/hippo/ingest/readers.py` | `is_plain_prose_name`, the closed name predicate over `PROSE_EXTENSIONS`. |
| NEW `tests/unit/test_managed_pipeline_activation.py` | 41 test functions, 73 cases. |
| `src/hippo/config.py` | **Not changed.** Every value the adapter needs (`chunk_size_chars`, `chunk_overlap_chars`, `openie_workers`, `max_upload_bytes`, `max_text_chars`, `data_dir`) already exists. |
| `tests/unit/test_ingest_pipeline.py`, `tests/unit/test_ingest_concurrency.py` | **Not changed.** Both pass unmodified against the new dispatch, which is the backward-compatibility evidence. |

## Public signatures as implemented

```python
# src/hippo/ingest/managed_activation.py
Source = Mapping[str, Any]
Eligibility = Literal["managed", "eligible_legacy", "unsupported", "tombstoned"]

class ManagedDispatchError(ValueError): ...
class ManagedActorRequired(ManagedDispatchError): ...
class ManagedConfigurationError(ManagedDispatchError): ...
class ManagedIngressError(ManagedDispatchError): ...

def stored_filename(source: Source) -> str
def safe_stored_name(name: str) -> str
def managed_eligibility(source: Source) -> Eligibility
def new_operation_id() -> str
def check_actor(actor: BuildActor | None) -> BuildActor | None

@dataclass(frozen=True)
class Dispatch:
    mode: Literal["managed", "legacy", "skip"]
    eligibility: Eligibility
    actor: BuildActor | None = None
    operation_id: str | None = None

def plan_dispatch(source, *, actor=None, operation_id=None) -> Dispatch
def source_directory(ctx, source_id: str) -> Path
def raw_root(ctx) -> Path
def cache_root(ctx) -> Path
def embedding_spec(ollama) -> EmbeddingSpec
def build_options(ctx) -> PlainBuildOptions
def ingress_file(ctx, source_id: str) -> Path
def present(ctx, source_id: str, **fields: Any) -> bool

@dataclass(frozen=True)
class ManagedFailure:
    status: str
    stage: str
    code: str
    message: str

def map_build_failure(exc, *, has_active_generation: bool) -> ManagedFailure
def record_build_failure(ctx, *, source_id, operation_id, error) -> ManagedFailure
def record_build_receipt(ctx, *, source_id, receipt: BuildReceipt) -> None
def run_managed_build(ctx, *, source_id, actor, operation_id, job_key) -> BuildReceipt

# src/hippo/ingest/pipeline.py
def add_text(ctx, name, text, *, owner_id=None, access_role_id=None, build_actor=None) -> str
def add_upload(ctx, filename, data, *, owner_id=None, access_role_id=None, build_actor=None) -> str
def start_indexing(ctx, source_id, *, build_actor=None, operation_id=None) -> bool
def run_indexing(ctx, source_id, *, build_actor=None, operation_id=None) -> None
def reindex(ctx, source_id, *, build_actor=None) -> bool

# src/hippo/ingest/readers.py
def is_plain_prose_name(name: str) -> bool
```

`add_repo`, `add_sample`, `delete_source` and `reindex_all` keep their current
signatures: the brief's frozen contract does not extend them, and the plan's
dispatch table leaves repository/sample sources legacy either way.

## Dispatch matrix

Every cell has a test in `tests/unit/test_managed_pipeline_activation.py`.

| Source / input | Explicit actor | Test |
|---|---|---|
| New pasted `text` | managed bootstrap | `test_new_pasted_text_with_an_actor_goes_to_managed_bootstrap` |
| New pasted `text` | no actor → legacy | `test_new_pasted_text_without_an_actor_stays_legacy` |
| New `.txt/.md/.markdown/.rst/.text` upload | managed bootstrap | `test_eligible_plain_upload_with_an_actor_goes_to_managed_bootstrap` (5 cases) |
| New `.pdf`, `.py`, `.yaml`, `.zip` upload | legacy with actor | `test_unsupported_upload_stays_legacy_even_with_an_actor` (4 cases) |
| Repo, sample | legacy with actor | `test_repo_and_sample_stay_legacy_even_with_an_actor` |
| Existing eligible legacy + actor `reindex` | atomic managed bootstrap, legacy evidence serves until publish | `test_an_eligible_legacy_reindex_converts_atomically_and_serves_legacy_until_publish` |
| Existing managed + actor | managed refresh only, no legacy preparation | `test_an_existing_managed_source_with_an_actor_refreshes_and_never_prepares_legacy` |
| Existing managed, no actor | refuse before any mutation, never legacy | `test_an_existing_managed_source_without_an_actor_refuses_before_any_legacy_hook` |
| Foreign (non-`BuildActor`) actor | refuse before the Source row exists | `test_add_text_and_add_upload_reject_a_foreign_actor_before_creating_a_source` |
| Current tombstone | skip, no mutation, no resurrection | `test_a_tombstoned_source_is_skipped_without_mutation_or_resurrection` |

Eligibility itself is proven on the saved row alone by
`test_eligibility_reads_the_saved_source_kind_and_stored_filename` (19 rows,
including a managed archive and a managed `.pdf` → `"managed"`, and a
tombstoned row → `"tombstoned"` even when `managed` is false) and by
`test_eligibility_never_trusts_a_claimed_content_type`.

## Adapter obligations (plan steps 1–7)

| Obligation | Test |
|---|---|
| Exactly one saved ingress file | `test_a_missing_ingress_file_is_refused_before_any_model_request`, `test_a_second_saved_file_is_refused_before_any_model_request` |
| Refuse symlinked / non-regular / escaping / oversized | `test_a_symlinked_ingress_file_is_refused`, `test_a_non_regular_ingress_file_is_refused`, `test_an_ingress_name_that_escapes_the_source_directory_is_refused`, `test_an_oversized_ingress_file_is_refused` |
| Refuse changed-during-capture | `test_an_ingress_file_changed_during_capture_is_refused` (a `RawArtifactStore` subclass rewrites the file inside `put_stream`) |
| `FileInput` absolute, sanitized `text.md`, `text/plain` | `test_the_saved_logical_name_is_the_sanitized_stored_filename` |
| Raw root / cache created only by a managed build | `test_the_raw_root_and_embedding_cache_appear_only_for_a_managed_build` (legacy add, legacy reindex and a structural query leave no `knowledge/` tree) |
| Options from effective configuration | `test_build_options_come_from_the_effective_configuration` |
| Out-of-contract values refused, never truncated | `test_out_of_contract_configuration_is_refused_rather_than_truncated` (5 cases) |
| Progress only to `status/stage/progress_*` | `test_bootstrap_progress_is_mapped_to_source_presentation_only` asserts the written field set and that no progress/status/error reaches `meta_json` |
| Called with no ambient transaction, cancellation from `Jobs` | `test_the_coordinator_is_called_outside_every_transaction_with_job_cancellation`; every real build additionally runs under the coordinator fixture's `HTTP inside caller transaction` assertion |

## Failure and progress presentation

| Transition | Test |
|---|---|
| Bootstrap success → coordinator owns `ready/ready` | `test_authenticated_pasted_text_publishes_a_managed_generation` |
| Refresh in progress → `ready` + `refreshing: …` | `test_refresh_progress_keeps_the_source_ready_and_marks_the_refresh_stage` |
| Refresh failure → `ready` / `refresh_failed`, pointer and counts untouched | `test_a_refresh_failure_at_any_coordinator_boundary_keeps_g1` (`/api/tags`, `/api/show`, `/api/embed`, `/api/chat`), `test_a_refresh_failure_at_publication_keeps_g1` |
| Refresh cancel → `ready` / `refresh_cancelled` | `test_a_cancelled_refresh_during_a_blocked_model_call_keeps_g1` (the transport blocks on an `Event` until the job is cancelled) |
| Initial failure / cancel → `failed` / `failed`\|`cancelled` | `test_an_initial_bootstrap_failure_fails_the_source_generically`, `test_a_cancelled_bootstrap_fails_the_source_without_managed_state` |
| Tombstone observed → never overwritten | `test_a_tombstone_observed_during_a_build_is_never_overwritten` (the tombstone commits from inside `/api/chat`) |
| Closed mapping, generation aware, bounded | `test_failure_mapping_is_closed_and_generation_aware` (10 exception families × both generation states) |
| Nothing private in the row or the logs | `test_an_unknown_failure_never_reaches_the_source_row_or_the_logs` |

The redaction test injects `"sk-live-secret /private/var/folders/data/sources/text.md ACME builds Robot. <model body>"`
as an unknown `RuntimeError` and asserts none of the four fragments reaches the
Source row or any `hippo` log record captured at DEBUG. The managed lane never
calls `log.exception`, never passes `exc_info`, and never formats `str(exc)`;
it logs source ID, operation ID, the stable code and the exception class name.

`test_a_failure_that_cannot_be_presented_still_reports_nothing_private` covers
the double fault: presenting a failure can itself fail (store outage, source
gone), and raising from there would hand `Jobs.start`'s `log.exception` a
chained traceback holding the original exception text. The second failure is
caught and logged by source and operation ID alone.

`present()` performs the read and the write inside one transaction holding
`_lock_source`, the same lock `apply_source_tombstone` takes, so a tombstone
that commits mid-build cannot be overwritten by a later progress or failure
write. It also skips a write whose fields already match the row, so a repeated
stage and an `already_current` refresh do not churn the source.

## Destructive-operation spies

`no_destruction` monkeypatches each of these to fail the test if called, and the
managed conversion, refresh and failed refresh all still complete:

- `store.delete_source`
- `store.delete_passages_for_source`
- `store.delete_code_nodes_for_source`
- `store.remove_orphans`
- `store.discard_generation`
- `store.collect_generation`
- `pipeline._clear_passages`
- `shutil.rmtree`

Raw deletion is asserted differently, and deliberately. `RawArtifactStore` has
no removal API at all; its only `unlink` is the staging-spool cleanup inside
`put_stream`/`copy_to`, so patching that would break an ordinary capture rather
than prove anything. Instead `test_managed_add_refresh_and_conversion_never_destroy_source_wide_evidence`
and `test_a_failed_managed_refresh_retains_every_raw_object_and_saved_byte`
capture the raw root's whole file inventory byte for byte before the operation
and assert every object is still present and unchanged afterwards, along with
the saved ingress file. `test_an_existing_managed_source_with_an_actor_refreshes_and_never_prepares_legacy`
and `test_an_eligible_legacy_reindex_converts_atomically_and_serves_legacy_until_publish`
additionally fail if `_prepare_reindex` or `_clear_passages` is reached.

## G1 through a live refresh

`test_a_refresh_serves_g1_until_the_new_generation_publishes` holds a structural
`query_session` across a real background refresh, asserts from inside `/api/chat`
that a *fresh* current session still serves G1 and that the active pointer is
unchanged, that the held session still serves its own pinned view afterwards,
and that a session opened after the job completes serves G2 and only G2.

## Commands and results

```
$ HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_ingest_pipeline.py \
    tests/unit/test_ingest_concurrency.py tests/unit/test_prose_generation.py \
    -q -o addopts='' -W error
EXIT 0 — 103 passed, 1 skipped                      (baseline, /tmp/hippo-pa3a-baseline.log)

$ HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py \
    -q -o addopts='' -W error
EXIT 1 — 72 failed                                  (RED, /tmp/hippo-pa3a-red.log)
   41 Failed: Managed activation adapter is missing
      (each from ModuleNotFoundError: No module named 'hippo.ingest.managed_activation')
   24 TypeError: run_indexing() got an unexpected keyword argument 'build_actor'
    6 TypeError: add_text()/add_upload() got an unexpected keyword argument 'build_actor'
    1 TypeError: FakeStore.update_settings() — a wrong call in the test itself, corrected
      to `update_settings({...})` before GREEN

$ HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py \
    tests/unit/test_prose_generation.py tests/unit/test_generation_failure.py \
    tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py \
    tests/unit/test_managed_source_lifecycle.py tests/unit/test_build_authority.py \
    tests/unit/test_local_workspace_membership.py -q -o addopts='' -W error
EXIT 0 — 323 passed, 1 skipped in 29.61s            (GREEN Fake, /tmp/hippo-pa3a-fake-green.log)

$ HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_pipeline_activation.py \
    tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py \
    -q -o addopts='' -W error
EXIT 0 — 110 passed in 515.87s (8:35)               (GREEN Ladybug, /tmp/hippo-pa3a-ladybug-green.log)

$ .venv/bin/ruff check src/hippo/ingest/managed_activation.py src/hippo/ingest/pipeline.py \
    src/hippo/ingest/readers.py tests/unit/test_managed_pipeline_activation.py
All checks passed!
$ .venv/bin/ruff format --check <same four files>
4 files already formatted
```

No `filterwarnings` marker or command-line filter was needed: none of the four
files imports `fastapi.testclient`, and `-W error` passes as written.

## Deviations and open findings

1. **`max_chunks` stays at the coordinator's reviewed default (1000).** The plan
   enumerates what the adapter takes from configuration — chunk size/overlap,
   synonym threshold, `openie_workers`, one input, `max_upload_bytes`,
   `max_text_chars` — and a chunk budget is not in that list, so the reviewed
   cap is used unchanged. A managed plain source therefore refuses past 1000
   chunks where legacy accepts 20 000. That is a refusal, never a truncation,
   which is what "do not silently lower coverage" asks for; it is worth an
   explicit decision in Task 5 if operators paste very long documents.
2. **`refreshing: publish` is never emitted.** `BuildProgress` has exactly three
   phases (`capture`, `reading`, `extract`), and the coordinator publishes after
   its last callback, so the adapter cannot observe the publication boundary.
   The stages it does emit are `refreshing: capture` (from `capture`/`reading`),
   `refreshing: extract`, and `refreshing: write` once extraction is complete
   and the coordinator moves to its batch writes. Emitting a fourth token would
   mean asserting a phase the adapter cannot see.
3. **The embedding-spec helper lives in `managed_activation`, not shared with
   `dense_session`.** `embedding_spec(ollama)` is built on exactly the primitives
   `dense_session.py:213` already inlines (`EMBED_PREFIXES`, `_base_name` from
   `hippo.ollama`), so the mapping table has one definition. Making
   `dense_session` call this helper would either edit a file this brief does not
   own or make `hippo.knowledge` import `hippo.ingest`, inverting the layering.
   Unifying the call site belongs with whoever next owns `dense_session.py`.
4. **`pipeline.source_dir` now delegates to `managed_activation.source_directory`.**
   The adapter must resolve the ingress directory absolutely for capture, and two
   definitions of the same path would be the drift this plan warns about; the
   adapter cannot import `pipeline` without a cycle, so the single definition
   lives there and `pipeline.source_dir` returns it. Its value is unchanged.
5. **`_refuse_if_indexing` still applies to the managed lane of `reindex`.** A
   managed refresh sweeps no orphans and so does not strictly need the `Busy`
   refusal, but keeping it preserves today's behaviour for every caller, and the
   actor and tombstone checks run before it, so no refusal order changed.
6. **An unchanged (`already_current`) refresh still moves `updated_at`.** The
   source really does enter a refresh and its stage is written once before the
   coordinator discovers the inputs are already published. Every other field —
   status, stage, error, progress, counts, meta and the active pointer — is
   restored exactly, which `test_an_unchanged_refresh_restores_the_ready_presentation`
   asserts field by field.
7. **`reindex_all` and `delete_source` are untouched** and remain Task 3b's. For
   a managed source `reindex_all` still raises from `legacy_source_cleanup`
   inside `_prepare_reindex`, exactly as it did before this change — it clears
   nothing and starts nothing. No new breakage, and no new protection either.
8. **PA7's close/reopen half is not proven from this slice.** The Ladybug run
   above is the same suite against the real embedded backend, which is what step
   5 asks for, but nothing here closes a Store and reopens the same database to
   check that a failed refresh state, an active pointer and a raw reference
   survive it. PA7's reopen fixture belongs to the Task 5 integrator; treat the
   managed-pipeline half of PA7 as backend-parity evidence only.
