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
