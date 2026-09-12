# PA1/PA4/PA7 evidence — Task 1, local workspace memberships and the managed tombstone

Worker `backend-developer-1`. Branch `wp/pa1`, base `26f9a55`, worktree `.worktrees/pa1`.
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, real_ladybug 0.15.3, mcp pinned to 2.1.1.

Scope proved here: PA4 entirely, the membership half of PA1, and the
membership/tombstone/fence/epoch half of PA7. Every other gate belongs to
another worker; nothing in this branch activates a production route.

## Commits

| Hash | Subject |
|---|---|
| `5f6b7e9` | Map live local users into the reviewed default workspace |
| `8b056aa` | Tombstone a managed source instead of deleting its evidence |
| `771aac0` | Prove the managed tombstone survives a Ladybug reopen |

## Public contract as implemented

```python
# src/hippo/store/knowledge.py — KnowledgeQueries
LOCAL_MAPPING_AUTHORITY = "local"

def ensure_local_workspace_memberships(self, principal_ids: Iterable[str] | None = None) -> int: ...
def _ensure_local_workspace_memberships_locked(self, principal_ids: Iterable[str] | None = None) -> int: ...
def _disable_local_workspace_memberships_locked(self, principal_ids: Iterable[str]) -> int: ...

# src/hippo/store/generations.py — GenerationQueries
@dataclass(frozen=True, slots=True)
class SourceTombstone:
    suppression_epoch: int
    fencing_token: int
    cancelled_generation_id: str | None
    cancelled_job_id: str | None

def tombstone_scope_key(source_id: str) -> str: ...          # f"source:{source_id}:delete"
def apply_source_tombstone(self, source_id, *, operation_id, created_at) -> SourceTombstone: ...

# src/hippo/knowledge/source_lifecycle.py
@dataclass(frozen=True)
class TombstoneReceipt:
    source_id: str
    operation_id: str
    outcome: Literal["tombstoned", "already_tombstoned"]
    suppression_epoch: int
    fencing_token: int
    cancelled_generation_id: str | None
    cancelled_job_id: str | None

class SourceLifecycleError(ValueError): ...
class UnmanagedSource(SourceLifecycleError): ...
class InvalidOperationId(SourceLifecycleError): ...

def tombstone_managed_source(ctx, *, source_id: str, actor: BuildActor, operation_id: str) -> TombstoneReceipt: ...
```

`operation_id` is bounded by `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`: printable,
path-safe and at most 128 characters, because it is echoed into a receipt and
persisted as the suppression's `restoration_barrier`.

Every pre-existing public method of `src/hippo/store/generations.py` keeps its
signature and semantics; `apply_source_tombstone` is added beside them.

## Commands and results

Working directory `/Users/mascott/projects/hippo/.worktrees/pa1` for every run.

| # | Command | Result |
|---|---|---|
| 1 | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_build_authority.py tests/unit/test_generation_failure.py -q -o addopts='' -W error` | EXIT 0, **61 passed** (baseline before any change) — `/tmp/hippo-pa1-baseline.log` |
| 2 | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_local_workspace_membership.py -q -o addopts='' -W error` | EXIT 1, **50 failed** (RED) — `/tmp/hippo-pa1-membership-red.log` |
| 3 | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py -q -o addopts='' -W error` | EXIT 1, **20 failed, 1 passed** (RED) — `/tmp/hippo-pa1-lifecycle-red.log` |
| 4 | strict Fake regression, see below | EXIT 0, **367 passed, 8 skipped** — `/tmp/hippo-pa1-fake-green.log` |
| 5 | filtered Fake regression, see below | EXIT 0, **44 passed** — `/tmp/hippo-pa1-fake-web-green.log` |
| 6 | Ladybug acceptance, see below | EXIT 0, **191 passed** in 71s — `/tmp/hippo-pa1-ladybug-green.log` |
| 7 | `.venv/bin/ruff check src/hippo && .venv/bin/ruff format --check src/hippo` plus every changed test file | All checks passed; 122 files already formatted |

RED note for run 3: exactly one test passed in RED,
`test_legacy_delete_still_removes_an_unmanaged_source`. It is a regression guard
that asserts legacy `delete_source` is *unchanged*, so passing before the
feature exists is the correct RED result. Every other test failed with
`ModuleNotFoundError: No module named 'hippo.knowledge.source_lifecycle'`.

RED note for run 2: all 50 failed with
`AttributeError: 'FakeStore'/'LadybugStore' object has no attribute
'ensure_local_workspace_memberships'`, or with the reviewed authority list and
memberships simply absent.

Run 4 (strict, no warning filter at all):

```
HIPPO_TEST_STORE=fake .venv/bin/pytest \
  tests/unit/test_local_workspace_membership.py tests/unit/test_managed_source_lifecycle.py \
  tests/unit/test_build_authority.py tests/unit/test_generation_failure.py \
  tests/unit/test_generation_store.py tests/unit/test_evidence_access.py \
  tests/unit/test_evidence_epochs.py tests/unit/test_snapshot_store.py \
  tests/unit/test_query_snapshots.py tests/unit/test_ingest_concurrency.py \
  tests/unit/test_store_knowledge.py tests/unit/test_access.py \
  tests/unit/test_account_snapshot_lifetime.py tests/unit/test_derived_evidence_access.py \
  tests/unit/test_evidence_store_access.py tests/unit/test_lookup_snapshot_lifetime.py \
  tests/unit/test_store_migrations.py -q -o addopts='' -W error
```

Run 5 (`test_web_auth.py` and `test_status_access.py`, which the brief's
regression list names):

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_web_auth.py tests/unit/test_status_access.py \
  -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
```

Why the extra `-W ignore`: both files do `from fastapi.testclient import
TestClient` at **module level**, and starlette's testclient touches the
deprecated `anyio.abc.BlockingPortal` alias at import time. Under a bare
`-W error` that is a *collection* error, so the per-test
`@pytest.mark.filterwarnings` pattern at `tests/unit/test_eval_access.py:251`
cannot reach it — the module never imports. The rulebook names third-party
Starlette/httpx/AnyIO deprecations as the known exception, so the run adds that
one third-party filter and nothing else. This is pre-existing and unrelated to
this branch: 15 test files import the testclient at module level and all fail
collection the same way at `26f9a55` —

```
test_browse_original_citations.py test_changeset_access.py test_graph_surface_access.py
test_mcp_server.py test_render_authorization.py test_settings_and_safety.py
test_web_analyze.py test_web_auth.py test_web_base.py test_web_busy_pages.py
test_web_code.py test_web_code_pages.py test_web_code_pages_2.py
test_web_graph_code.py test_web_library_evals.py
```

I modified none of them.

Run 6 (Ladybug, the primary acceptance backend):

```
HIPPO_TEST_STORE=ladybug .venv/bin/pytest \
  tests/unit/test_local_workspace_membership.py tests/unit/test_managed_source_lifecycle.py \
  tests/unit/test_build_authority.py tests/unit/test_generation_failure.py \
  tests/unit/test_generation_store.py tests/unit/test_evidence_epochs.py \
  tests/unit/test_query_snapshots.py -q -o addopts='' -W error
```

`tests/unit/test_local_workspace_membership.py` parametrizes its own backends
(`fake` and a real `LadybugStore` on a temporary file) because it is about store
*startup*: the shared `store` fixture hands out an already bootstrapped object,
and the Ladybug case has to close and reopen the same database between steps.
It therefore proves both backends under either `HIPPO_TEST_STORE`.
`tests/unit/test_managed_source_lifecycle.py` runs on the shared fixture and
additionally owns one self-contained Ladybug close/reopen test
(`test_tombstone_fence_and_epochs_survive_a_ladybug_reopen`) using a temporary
absolute `data_dir`; nothing here writes to the repository's `data/`.

## Mandatory negative evidence

`test_tombstone_never_runs_a_destructive_cleanup` monkeypatches each of these to
raise `AssertionError` and then asserts the tombstone still commits:

- `store.delete_source`
- `store.delete_passages_for_source`
- `store.delete_code_nodes_for_source`
- `store.remove_orphans`
- `store.collect_generation`
- `store.discard_generation`
- `hippo.ingest.pipeline._clear_passages`
- `shutil.rmtree`
- `pathlib.Path.unlink`
- `os.remove`

Counts alone are not relied on, but they are also asserted:
`test_retained_history_raw_references_and_other_sources_are_untouched` compares
`AccessPolicy`, `Artifact`, `ArtifactRevision`, `EvidenceSpan`, `Generation`,
`GenerationMember`, `GenerationEvidenceMember`, `IndexManifest`, `IndexEvent`
and every passage row before and after, plus a second unrelated managed source
row.  `test_saved_ingress_and_query_snapshots_survive_the_tombstone` proves the
saved bytes under `source_dir(ctx, source_id)`, `QuerySnapshot` and
`SnapshotReference` are unchanged.

## Ownership extensions granted by the orchestrator

| File | What changed | Why |
|---|---|---|
| `src/hippo/store/authorization.py` | `permission_mutation` calls `store._disable_local_workspace_memberships_locked([user_id])` before a `delete_user` and `store._ensure_local_workspace_memberships_locked([result])` after a `create_user`; a three-line `_mutated_user` helper reads the id. No membership logic lives here. | There are **three** `create_user`/`delete_user` implementations — `src/hippo/store/users.py` (Neo4j `Store`), `src/hippo/store/ladybug.py` (`LadybugStore` does not inherit `UserQueries`) and `tests/fakes/fake_store.py`. All three already share this one decorator, which owns the single transaction, authorization lock and epoch bump the plan requires. Orchestrator approved Option A. |
| `tests/fakes/fake_store.py` | One line in `ping()`: `self.ensure_local_workspace_memberships()` after `ensure_schema()`/`ensure_roles()`, mirroring the real stores. | The brief allowed `src/hippo/store/fake.py`, which does not exist; the Fake store lives under `tests/fakes/`. Orchestrator approved exactly this one line. |

The brief also allowed `src/hippo/store/neo4j.py` for the same hook. That file
does not exist either: the Neo4j backend is `src/hippo/store/base.py` plus
`Store` in `src/hippo/store/__init__.py`, and `Store.on_first_connection`
(already owned) is where the call went.

## Files created and modified

Created:

- `src/hippo/knowledge/source_lifecycle.py`
- `tests/unit/test_local_workspace_membership.py`
- `tests/unit/test_managed_source_lifecycle.py`
- this file

Modified (source): `src/hippo/store/knowledge.py`,
`src/hippo/store/generations.py`, `src/hippo/store/__init__.py`,
`src/hippo/store/ladybug.py`, `src/hippo/store/authorization.py`.
`src/hippo/store/users.py` needed no change — Option A covers it.

Modified (existing tests), `git diff 26f9a55 --stat -- tests/`:

| File | Hunks | Change |
|---|---|---|
| `tests/fakes/fake_store.py` | 1 | the approved `ping()` line |
| `tests/unit/test_store_knowledge.py` | 3 | `put_knowledge` → `update_knowledge`, `policy_epoch=1` → `2` |
| `tests/unit/test_evidence_store_access.py` | 5 + 1 new helper | same, plus `local_mapping()` and one disable in the "no membership → denied" test |
| `tests/unit/test_derived_evidence_access.py` | 1 | same |
| `tests/unit/test_lookup_snapshot_lifetime.py` | 2 | drop the hand-written membership (create_user now writes exactly it) and its now unused import |

`tests/unit/test_status_access.py` is **not modified**. All 11 of its `-W error`
failures are the pre-existing anyio collection issue above; it contains no
`WorkspaceMembership` write and no membership collision.

### Why those fixtures had to change

`WorkspaceMembership.identity_fields == ("workspace_id", "principal_id")`, so
there is exactly one membership record per principal per workspace and
`mapping_authority` is a mutable lifecycle field, not part of the identity. Once
`create_user` writes the reviewed `local` mapping, a fixture that then
`put_knowledge`s a *second* membership for the same pair under a different
authority hits `Immutable record already exists with different contents` — 112
occurrences before the fix. The repair is the documented path for a mutable
field: `update_knowledge` with a higher `policy_epoch`. The tests still exercise
a non-`local` reviewed authority exactly as before.

## Root-tree tests that merge into this branch

Checked read-only in `/Users/mascott/projects/hippo` (untracked there, absent
from this worktree):

- `tests/unit/test_prose_generation.py:102-113` — **no change needed.** It
  creates the user and then writes
  `WorkspaceMembership(workspace_id=…, principal_id=user, mapping_authority="local", enabled=True, policy_epoch=1)`,
  which is byte-identical to the record `create_user` now writes, so
  `put_knowledge` sees `existing == record` and is a no-op. Its
  `set_meta("reviewed_mapping_authorities", ["local"])` on line 110 is likewise
  already the stored value. Line 361 creates a second user and writes no
  membership.
- `tests/unit/test_temporal_conflicts.py`, `tests/unit/test_temporal_evidence.py`
  — no `create_user` and no `WorkspaceMembership`; unaffected.

Should any future fixture need a different authority for a local user, the
one-line fix is always the same: `put_knowledge(...)` → `update_knowledge(...)`
with `policy_epoch` raised above `1`.

## Decisions and deviations

1. **Replay is unreachable through `capture_build_authority`** (orchestrator
   approved the resolution). `BuildAuthority.check_local` calls
   `EvidenceAccess.require_source` in `query_mode="current"`, and
   `_source_allowed` denies any `("source", id)` in `_suppressed("current")` —
   which includes our own `current_only` tombstone, for readers *and* for
   `trusted_local` (an internal audience still fails the source-suppression
   check). `test_build_authority.py::test_empty_precapture_guard_still_enforces_membership_and_source_suppression`
   already proves this. Therefore:
   - a **reader** replay raises the same generic `AuthorizationChanged` as any
     inaccessible source and learns nothing;
   - a **`trusted_local`** replay re-establishes standing with
     `EvidenceAccess(...).require_source(source_id, query_mode="history")`,
     which correctly ignores `current_only` suppressions, and returns the prior
     receipt only when the committed suppression matches `reason="tombstone"`,
     `view_applicability="current_only"`, the exact `scope_key` and
     `restoration_barrier == operation_id`. It writes nothing and adds no epoch;
   - a `trusted_local` caller with a **different** `operation_id` gets the
     generic denial, never a receipt.

   All three are tested
   (`test_reader_replay_reveals_nothing_about_a_tombstoned_source`,
   `test_internal_replay_of_the_same_operation_returns_the_prior_receipt`
   parametrized over a staging build, `test_internal_replay_with_another_operation_id_is_denied`).

2. **`_disable_local_workspace_memberships_locked(principal_ids) -> int`
   added** (name approved). The frozen locked helper *ensures enabled*
   memberships, so it cannot also retire one; `delete_user` needs a distinct
   locked operation that runs while the `User` row still exists, so the retained
   membership reference stays valid. Both frozen names are unchanged.

3. **`_local_mapping_available()` schema guard.** The mapping is skipped unless
   `schema_version()` reports the current version in state `complete`.
   Without it, `test_store_migrations.py::test_populated_v1_ladybug_migrates_reopens_and_preserves_auth`
   fails: it creates users on a deliberately pre-schema-5 file where the
   `WorkspaceMembership` table does not exist yet. A store that has not migrated
   has no mapping to maintain.

4. **`_set_meta_locked` writes the reviewed authority list through
   `type(self).set_meta.__wrapped__`.** `set_meta` is decorated with
   `metadata_mutation`, which owns its own authorization bump; the locked helper
   must bump nothing so the public wrapper (and the permission-mutation
   decorator) can bump exactly once for the whole change. The value is built
   from an already validated list, so skipping that decorator skips no check the
   caller has not already made. All three backends decorate with
   `functools.wraps`, so `__wrapped__` is always present; the helper raises if
   it is not.

   *Partly superseded 2026-09-11 — see "Follow-up 2026-09-11", decision 8: the
   public wrapper no longer bumps at all. `permission_mutation` still owns the
   single bump for every reduction, and the locked helper still bumps nothing,
   which is the part this deviation turns on.*

5. **New memberships are exactly `enabled=True`, `mapping_authority="local"`,
   `policy_epoch=1`**, and the locked helper is a no-op (no write, no count)
   when an equal enabled membership already exists. That keeps
   `tests/unit/test_build_authority.py` and `test_prose_generation.py`, which
   both hand-write that exact record, green without modification.

6. **`test_identity_and_source_changes_invalidate_a_captured_authority[role]`
   asserts less than the other cases, on purpose.** Lowering the role's rank
   invalidates the *captured* proof (the epoch moved), but the source's owner
   may still recapture — that is the difference from losing standing
   (`membership`, `source_acl`, `disabled`, `deleted`), where recapture is also
   denied. Read as a precise assertion, not a weakened one.

7. **Known limit of a replayed receipt.** `already_tombstoned` reports the
   *current* `build_fencing_token` rather than a persisted copy, because the
   receipt itself is not stored. If some later operation fences the source again
   after the tombstone, a replay would report the higher value. The suppression
   epoch, which is what the barrier is keyed on, is always the committed one.

   *Superseded 2026-09-11 — see "Follow-up 2026-09-11", deviation 7 restated.*

8. **Cooperative cancellation is requested, never awaited.**
   `ctx.jobs.cancel(f"index:{source_id}")` is called before the transaction
   opens; `Jobs.cancel` only sets an event.
   `test_tombstone_does_not_wait_for_a_blocked_model_callback` parks a worker
   thread in a blocking callback holding no store transaction, tombstones, and
   then proves the worker's `check_generation_write` fails on the new fence.

## Out of scope, untouched

Pipeline `delete_source`/`reindex` dispatch (Task 3 calls this service), any
HTTP/MCP/CLI route, physical purge, restoration, retention, Neo4j runs, and
projection/inventory (Task 2). No Neo4j database was contacted.

---

# Follow-up 2026-09-11 — review fixes (worker `opus-4`)

Worker `opus-4`. Branch `wp/pa1fix`, worktree `.worktrees/pa1fix`, base `82bd317`,
then `git merge rag-it-all-tibs` (fast-forward to `afb8960`, orchestrator-authorized)
to pick up `in_ambient_transaction()` on all three stores from `wp/txown`.
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, real_ladybug 0.15.3,
mcp pinned to 2.1.1. No Neo4j database was contacted; every Ladybug run is a real
`LadybugStore` file under `tmp_path`.

Brief: `ai_docs/handoffs/briefs/fix-pa1.md`. Source review:
`ai_docs/reports/2026-09-11-pa1-review.md` (1 major, 7 minor), plus two decisions
the orchestrator added mid-task (7 and 8).

## What changed

| # | Decision | Change |
|---|---|---|
| 1 | major — tombstone is not a store barrier | `claim_generation_build` refuses a tombstoned source |
| 2 | minor — disable rewrote the authority | `_apply_local_membership` retains `mapping_authority` when disabling |
| 3 | minor — guard parity | `_disable_local_workspace_memberships_locked` gets `_local_mapping_available()` |
| 4 | minor — managed/unmanaged oracle | standing established before the managed check; absent-source denial text normalized |
| 5 | minor — tests only | cancellation request asserted; many-changes epoch behaviour asserted |
| 6 | documented, no code change | `_local_mapping_available` docstring states the unmapped-create consequence |
| 7 | added — ambient guard was a false negative | `apply_source_tombstone` asks `in_ambient_transaction()` |
| 8 | added — lazy bootstrap invalidated in-flight readers | `ensure_local_workspace_memberships` never bumps the authorization epoch |

### 1. A committed tombstone is a store-level barrier

`src/hippo/store/generations.py`. `claim_generation_build` now reads the Source row
once, immediately after `self._lock_source(gen.source_id)` and the generation re-read,
and refuses through the new `_tombstoned(source_id, source)` helper when either
`source["status"] == "deleted"` or a `Suppression` matches
`target_kind="source"`, `target_id=source_id`, `reason="tombstone"`,
`view_applicability="current_only"`, `scope_key=tombstone_scope_key(source_id)`.

**Exact refusal used:** `ValueError("Stale build lease, fence, or generation state")`
— verbatim the string `_check_build` already raises (`generations.py:210` pre-change),
the only existing "stale fence/state" shape in this module. No new public message and
no new exception type appears. The refusal happens before `_collect_generation`,
before the fence increment and before `active_build_id` is written, and the enclosing
`with self.transaction()` rolls back the `_lock_source` write on Ladybug.

The duplicate `source = self.get_source(gen.source_id)` that used to sit further down
was removed; the single read now serves both the barrier and the live-holder check.

Proof, `tests/unit/test_managed_source_lifecycle.py`:

- `test_a_tombstoned_source_cannot_reclaim_its_failed_generation` — reproduces PROBE9
  exactly (claim a refresh generation, tombstone it, then reclaim the `failed`
  generation). `store._collect_generation` is monkeypatched to raise, so "did not
  collect" is an assertion rather than an inference. Asserts the fence still equals
  `receipt.fencing_token`, `active_build_id is None`, the cancelled generation is
  still `failed`, the cancelled job still carries `source_tombstoned`, and
  `(epochs, inventory, Source row)` are byte-identical to before the attempt.
- `test_a_refused_reclaim_leaves_the_replayed_fencing_token_pinned` — after the refused
  claim, a `trusted_local` replay of the same operation id reports the *same*
  `fencing_token`, `suppression_epoch`, `cancelled_generation_id` and
  `cancelled_job_id` as the original receipt.
- `test_tombstone_fence_and_epochs_survive_a_ladybug_reopen` — the reopened file also
  refuses the reclaim, and the Source row is still the one captured before the close.

### 2. Retiring a mapping keeps the authority that granted it

`src/hippo/store/knowledge.py`, `_apply_local_membership`:
`authority = LOCAL_MAPPING_AUTHORITY if enabled else existing.mapping_authority`.
The no-change comparison and the `replace(...)` both use that value, so the enable
path still repairs a foreign authority to `local` (plan step 2) while the disable path
retains it (plan step 3). Proof:
`test_local_workspace_membership.py::test_disabling_a_mapping_keeps_the_authority_that_granted_it`
— a `reviewed` membership survives `delete_user` as `(False, "reviewed", 3)`.

Consequential edit outside the owned list: `tests/unit/test_evidence_store_access.py:164`
changed from `membership.replace(enabled=False, mapping_authority="local", policy_epoch=3)`
to `membership.replace(enabled=False, policy_epoch=3)`. That is the exact edit the
review prescribed (finding 2) — the file encoded the defect. It is neither in the
brief's "own" nor its "do NOT touch" list; flagging it explicitly.

### 3. Guard parity on the disable path

`_disable_local_workspace_memberships_locked` now returns 0 when
`_local_mapping_available()` is false, after the explicit-principals check so a bad
argument is still refused on a legacy file. Proof:
`test_delete_user_on_a_pre_schema_store_has_no_mapping_to_retire` — a real
`LadybugStore` with `ensure_schema` bound to `_ensure_legacy_schema` (the fixture
shape from `tests/unit/test_store_migrations.py:147`), `WorkspaceMembership` confirmed
absent via `show_tables()`, `create_user` then `delete_user` with no raise.

**Accepted residual (orchestrator-acknowledged):** `delete_user` of the *last* user on
a pre-schema-5 file still raises, because `src/hippo/store/authorization.py:86` reads
`_knowledge_rows("Connector")` on the last-user branch and that table is also absent
on a v1 file. `authorization.py` is on this brief's do-NOT-touch list, so the test
creates two principals and deletes one. Same narrow reachability as finding 3: a real
`LadybugStore(path)` migrates to v5 before its first transaction.

### 4. Standing before the managed check

`src/hippo/knowledge/source_lifecycle.py`. Order is now: actor type → `operation_id`
regex → `capture_build_authority` (with the unchanged `AuthorizationChanged` → replay
branch) → **inside the `try`/`finally` that closes the guard** →
`source_is_managed` → `UnmanagedSource`. The managed check therefore cannot answer
"is this source managed?" for an actor with no standing, and the guard is closed on
the `UnmanagedSource` path too (it previously could not be reached with a guard open).
The function docstring states the ordering and why.

Proof, `test_an_unauthorized_reader_learns_nothing_about_the_source`: a `stranger`
reader attempting a managed source, an unmanaged source and a nonexistent id gets
`AuthorizationChanged` all three times, none of them a `SourceLifecycleError`, with
one single distinct message across all three and with epochs and the whole retained
inventory unchanged.

The reorder alone made the managed and unmanaged denials byte-identical
(`"Build actor cannot manage source"`), closing the oracle finding 7 named, but a
*nonexistent* source id still yielded `"Plain build source is unavailable"` from
`_source_control` — a distinguishable absent-vs-present signal in
`src/hippo/knowledge/build_authority.py`, which this brief listed as do-NOT-touch
because `wp/txown` owned it. Reported to the orchestrator as options (a) record the
residual or (b) normalize; **the orchestrator chose (b) and granted ownership of that
file and `tests/unit/test_build_authority.py` for this one change.** `_source_control`
now raises the same `"Build actor cannot manage source"` text, with a comment stating
why the two read alike. No test asserted either string, so
`tests/unit/test_build_authority.py` needed no edit. The test's message assertion is
therefore full equality across all three cases, not just managed vs unmanaged.

That normalization applies to every `capture_build_authority` caller, not only this
one: an absent, wrong-kind or workspace-less source and a source the actor may not
manage are now indistinguishable everywhere. The refusal *condition* is unchanged.

`test_unmanaged_source_is_refused_before_any_mutation` now creates its legacy source
with `owner_id=managed.user` and asserts `UnmanagedSource` specifically. Without an
owner the reader has no standing and the new ordering would (correctly) return the
generic denial, which would no longer test what the test is named for. `AuthorizationChanged`
is a `RuntimeError`, not a `ValueError`, so the old `pytest.raises(ValueError)` would
also have stopped holding.

### 5. Assertions the review asked for

- `test_cancellation_is_requested_before_the_transaction` — `ctx.jobs.cancel` is
  monkeypatched with a spy recording `(key, store.in_ambient_transaction(),
  len(suppressions(...)))`. Asserts exactly `[("index:<source_id>", False, 0)]`: one
  call, the right key, no transaction open and nothing committed yet. Deleting the
  `ctx.jobs.cancel` line now fails a test.
- `test_many_repairs_count_every_change_and_invalidate_no_reader` — three damaged
  memberships plus an emptied authority list give `ensure_local_workspace_memberships()
  == 4`. Its epoch assertion is `== before` rather than `== before + 1` because of
  decision 8 below.

### 6. Documented, no code change

`_local_mapping_available`'s docstring now states that a user created while the guard
is false is left unmapped — fail-closed, no managed evidence — until the next
`on_first_connection` runs the all-user form. The Neo4j `Store.on_first_connection` +
`users.py` lane remains untested here (finding 8, orchestrator-owned parity item).

### 7. The ambient-transaction guard was a false negative

`apply_source_tombstone`'s guard read `self._transaction_depth` / `self._transaction`,
which are process-wide: while **any** thread held a transaction, a thread holding
**none** passed the check and its fence, presentation and suppression writes
auto-committed one statement at a time. Replaced with
`if not self.in_ambient_transaction():` — the per-thread method `wp/txown` landed on
all three stores — keeping the same `RuntimeError("Managed tombstone requires the
caller's transaction")`.

Proof, `test_another_threads_transaction_is_not_the_tombstone_callers_transaction`: the
main thread holds a transaction, a helper thread calls `apply_source_tombstone` with
none and must be refused. The helper is joined with a timeout inside the held
transaction, so the pre-fix behaviour (admitted, then parked on the store lock) fails
as an assertion instead of hanging the suite. Epochs, the Source row and the absence of
any suppression are all asserted afterwards.

### 8. The lazy bootstrap must not invalidate an in-flight reader

`ensure_local_workspace_memberships` no longer bumps the authorization epoch at all.
Rationale (orchestrator decision, plan sentence amended by the orchestrator): the
public form is additive-only — it adds or repairs memberships and adds the local
authority — so the only proof it can stale is a *denial*, which fails safe. Every
reduction goes through `permission_mutation`, which takes the lock, calls the *locked*
helper and owns its own single bump; `create_user`/`delete_user` behaviour is therefore
unchanged.

The defect: `Store.ping()` runs `on_first_connection` → `ensure_local_workspace_memberships`
lazily, and `src/hippo/web/render.py:85` pings while holding the query session it is
rendering from, so the first HTML request against any store that still needed mapping
raised `AuthorizationChanged("Permissions changed; repeat the query")`.

Proof: `test_a_held_query_session_survives_the_first_ping_bootstrap` — a store with a
user, its mapping forgotten and `_bootstrapped` reset, holds a structural
`query_session` across `store.ping()` and then calls `session.validate()`. Asserts the
authorization epoch is unchanged and that the bootstrap did its work anyway
(`authorities == ["local"]`, memberships present).

Two existing assertions were updated from `+1` to unchanged:
`test_damaged_local_mapping_is_repaired_with_a_higher_policy_epoch` and the new
many-repairs test. `test_repeated_startup_changes_nothing_and_bumps_no_epoch`,
`test_create_user_maps_the_new_principal_in_one_authorization_bump` and
`test_delete_user_disables_and_retains_its_membership_in_one_bump` are untouched and
still hold — the per-mutation bumps are `permission_mutation`'s, not this wrapper's.

## Deviation 7, restated (supersedes the original)

`already_tombstoned` reports the current `build_fencing_token` rather than a persisted
copy. **With decision 1 in place this is no longer reachable through
`claim_generation_build`:** a tombstoned source refuses the claim before its fence can
advance, which is asserted by
`test_a_refused_reclaim_leaves_the_replayed_fencing_token_pinned` on the fake backend
and by the Ladybug reopen test. It remains true in principle that the field is read
live rather than stored, so any *future* store operation that increments
`build_fencing_token` on a tombstoned source would change what a replay reports.
`receipt.suppression_epoch` is the field keyed to the barrier and is always the
committed one; idempotency decisions should use it.

## Test runs

All from `.worktrees/pa1fix` with `.venv/bin/pytest`, `HIPPO_TEST_STORE` set explicitly,
`-q -o addopts='' -W error`. Runs that include a module-level `fastapi.testclient`
importer also carry rulebook form (b) verbatim:
`-W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`.
No ini-wide `filterwarnings` was added.

| # | Backend / files | Result | Log |
|---|---|---|---|
| 1 | fake baseline — `test_managed_source_lifecycle`, `test_local_workspace_membership`, `test_generation_store`, `test_generation_failure` | **126 passed**, EXIT 0 | `/tmp/hippo-pa1fix-baseline.log` |
| 2 | fake RED (decisions 1–5, 7) — the two owned test files | **8 failed, 77 passed**, EXIT 1 | `/tmp/hippo-pa1fix-red.log` |
| 3 | fake RED (decision 8) — held-session regression + the two render/citation tests, bump temporarily restored | **3 failed, 11 passed**, EXIT 1 | `/tmp/hippo-pa1fix-d8-red.log` |
| 4 | fake GREEN — 20 files (the two owned, generation store/failure, build authority, evidence access/epochs/store-access/derived, store knowledge, migrations, policy migration, query snapshots, transaction ownership, ingest concurrency, query session, answer original citations, lookup snapshot lifetime, structural loading, managed source inventory); form (b) | **487 passed, 10 skipped**, EXIT 0 | `/tmp/hippo-pa1fix-fake-green.log` |
| 5 | ladybug GREEN — managed source lifecycle, local workspace membership, generation store, store migrations, transaction ownership, build authority, evidence store access, generation failure, query session, answer original citations; form (b) | **269 passed**, EXIT 0, 127.2s | `/tmp/hippo-pa1fix-ladybug-green.log` |

The step-2 RED failures, each for the intended reason:

| Test | RED reason |
|---|---|
| `test_a_tombstoned_source_cannot_reclaim_its_failed_generation` | `AssertionError: a tombstoned source must not collect its retained attempt` (PROBE9 reproduced) |
| `test_a_refused_reclaim_leaves_the_replayed_fencing_token_pinned` | `DID NOT RAISE ValueError` |
| `test_an_unauthorized_reader_learns_nothing_about_the_source` | `UnmanagedSource: Legacy cleanup owns unmanaged sources` leaked to a stranger |
| `test_another_threads_transaction_is_not_the_tombstone_callers_transaction` | `the unowned caller was admitted instead of refused` |
| `test_tombstone_fence_and_epochs_survive_a_ladybug_reopen` | `DID NOT RAISE ValueError` |
| `test_disabling_a_mapping_keeps_the_authority_that_granted_it` (fake, ladybug) | `(False, 'local', 3) == (False, 'reviewed', 3)` |
| `test_delete_user_on_a_pre_schema_store_has_no_mapping_to_retire` | `Binder exception: Table WorkspaceMembership does not exist.` |

Decision-5 tests were green on arrival, which is correct — finding 6 and the
many-changes half of finding 5 were missing *assertions*, not wrong behaviour.

Ruff 0.16.6 on every changed file
(`store/generations.py`, `store/knowledge.py`, `knowledge/source_lifecycle.py`,
`knowledge/build_authority.py`, `tests/unit/test_managed_source_lifecycle.py`,
`tests/unit/test_local_workspace_membership.py`,
`tests/unit/test_evidence_store_access.py`):
`All checks passed!` / `7 files already formatted`.

## Still open after this follow-up

- Finding 4's optional `log.warning` on a silent guard short-circuit: not added; the
  docstring sentence (decision 6) is the sanctioned form.
- Finding 8, the Neo4j lane (`store/__init__.py:81`, `store/users.py`): untested here,
  orchestrator-owned (PA7/PA8 parity from an isolated reservation).
- `delete_user` of the last user on a pre-schema-5 file (`authorization.py:86`,
  accepted residual).
- No route, dispatcher or production path was activated.

## Note on run ordering

Runs 4 and 5 above are the *final* runs, after the orchestrator's option (b) and after
a whitespace-only `ruff format` of `tests/unit/test_managed_source_lifecycle.py`. The
RED for option (b) is the first form of
`test_an_unauthorized_reader_learns_nothing_about_the_source`, which failed with
`assert 2 == 1` over
`{'Build actor cannot manage source', 'Plain build source is unavailable'}`.

On the decision-8 repro: the orchestrator named three tests. With the bump temporarily
restored and rulebook form (b) applied, the reproduced failures were
`test_query_session.py::test_html_ask_uses_one_graph_through_inventory_and_render[True]`
and `test_answer_original_citations.py::test_answer_surfaces_present_originals_separately_from_ranked_views[html]`,
plus the new held-session regression — all three
`AuthorizationChanged("Permissions changed; repeat the query")`.
`test_search_labels_derived_text_and_analysis_renders_original_evidence` failed only in
the first attempt, which omitted form (b), so its failure there was the sanctioned AnyIO
warning and not the epoch bump; it is green in run 4. Worth reconciling if the
orchestrator's own repro disagrees.
