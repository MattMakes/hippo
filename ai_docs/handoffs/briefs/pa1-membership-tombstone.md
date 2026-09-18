# Brief: production activation Task 1 — local workspace memberships and managed tombstone

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa1` (branch `wp/pa1`, base `26f9a55`).

GOAL: Implement Task 1 of `ai_docs/plans/rag-it-all-task-5-production-activation.md`: (a) idempotent reviewed local workspace memberships at the store boundary, (b) an atomic managed-source tombstone primitive in the store plus a `knowledge/source_lifecycle.py` service, (c) two new test files proving both on Fake and on Ladybug close/reopen, committed on `wp/pa1`.

CONTEXT:
- Plan sections that bind you, read them completely: "Build actors at every boundary" (the numbered list 1–4 about `ensure_local_workspace_memberships` and the paragraph after it), "Managed delete: suppression now, physical purge elsewhere", invariants 1, 2, 7, 10, the Task 1 row of the ownership table, and the adversarial cases about users/upgrade/monkeypatched destructive operations.
- Gates you are proving (ledger `ai_docs/gates/rag-it-all/task-5-production-activation/GATES.md`): PA4 entirely; the membership half of PA1; the membership/tombstone/fence/epoch half of PA7. Other gates belong to other workers.
- Existing primitives to reuse, not reimplement: `src/hippo/knowledge/build_authority.py` (`BuildActor`, `capture_build_authority`, `BuildAuthority.check_local`), `src/hippo/knowledge/access.py` (`EvidenceAccess`, `require_source`, `WorkspaceMembership` rules), `src/hippo/store/authorization.py` (authorization epoch and lock), `src/hippo/store/generations.py` (source fencing: `build_fencing_token`, `active_build_id`, `MaintenanceJob`, `fail_generation_build`), `src/hippo/knowledge/model.py` (`Suppression`, `WorkspaceMembership`, `Source` fields). Read `tests/unit/test_build_authority.py`, `tests/unit/test_generation_failure.py`, `tests/unit/test_evidence_epochs.py` and `tests/unit/test_query_snapshots.py` for fixture patterns (how a managed source with a published generation is built in tests, how epochs are asserted, how a held query session is validated).
- The prior root session confirmed: `Store` (Fake) and `LadybugStore` share `KnowledgeQueries`; `on_first_connection` runs schema and roles; `create_user`/`delete_user` are wrapped by the `permission_mutation` decorator which already bumps the authorization epoch once inside a transaction. Verify these by reading `src/hippo/store/__init__.py`, `src/hippo/store/knowledge.py`, `src/hippo/store/users.py`, `src/hippo/store/ladybug.py`.

FROZEN PUBLIC CONTRACT (Task 3 will code against this; do not rename):

```python
# src/hippo/knowledge/source_lifecycle.py
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TombstoneReceipt:
    source_id: str
    operation_id: str
    outcome: Literal["tombstoned", "already_tombstoned"]
    suppression_epoch: int  # epoch of the committed (or previously committed) suppression
    fencing_token: int  # source build_fencing_token after the transition
    cancelled_generation_id: str | None
    cancelled_job_id: str | None


def tombstone_managed_source(
    ctx, *, source_id: str, actor: "BuildActor", operation_id: str
) -> TombstoneReceipt: ...
```

Behavior: exactly the transition list in the plan's "Managed delete" section, in one callback-free transaction after cooperative cancellation of `index:<source_id>` has been REQUESTED (not awaited). Non-managed source: raise a `ValueError` subclass (callers dispatch legacy before calling you). Denied actor: raise the same authorization exception type the build-authority primitive raises. `already_tombstoned` is returned only when the same operation_id replays under an established trusted authority, and it must not add a second suppression epoch. Bounded `operation_id` (define and enforce a max length and charset). The store-level primitive you add to `src/hippo/store/generations.py` is yours to name; it must require the caller's transaction, authorization lock and source lock, and must never be reachable without them.

```python
# KnowledgeQueries (src/hippo/store/knowledge.py)
def ensure_local_workspace_memberships(self, principal_ids: Iterable[str] | None = None) -> int: ...
def _ensure_local_workspace_memberships_locked(self, principal_ids: Iterable[str] | None = None) -> int: ...
```

Semantics exactly as plan list items 1–4: `"local"` in sorted unique `reviewed_mapping_authorities`; one enabled default-workspace `WorkspaceMembership(mapping_authority="local")` per selected live User; repair via `policy_epoch` increase; locked form returns change count and does not bump; public form bumps authorization exactly once when count > 0; wired into `Store.on_first_connection`, `LadybugStore.on_first_connection` (after schema and roles), into `create_user` (locked one-user form inside the existing permission-mutation transaction) and before `delete_user` removes the User (disable the membership with the locked helper, retain the record). No nested second epoch-owning wrapper.

FILES:
  - own: `src/hippo/store/knowledge.py`, `src/hippo/store/generations.py`, `src/hippo/store/users.py`, `src/hippo/store/ladybug.py`, `src/hippo/store/__init__.py`, NEW `src/hippo/knowledge/source_lifecycle.py`, NEW `tests/unit/test_local_workspace_membership.py`, NEW `tests/unit/test_managed_source_lifecycle.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa1.md`.
  - If the Fake store or Neo4j store live in other files and need the same hook, you may edit `src/hippo/store/fake.py` and `src/hippo/store/neo4j.py` for the membership hook and tombstone primitive ONLY. Name them in your report.
  - do NOT touch: `src/hippo/ingest/*`, `src/hippo/web/*`, `src/hippo/context.py`, `src/hippo/status.py`, `src/hippo/hipporag/*`, `src/hippo/knowledge/projection.py`, `query_access.py`, `dense_session.py`, `access.py`, `build_authority.py`, any existing test file except to fix a test that your membership hook legitimately changes (name each in the report), the shared `GATES.md`, `docs/`, the checkpoint.
- Every existing public method of `src/hippo/store/generations.py` keeps its signature and semantics. An uncommitted coordinator in the root tree (`src/hippo/ingest/prose_generation.py`, not in your worktree) calls `claim`/`renew`/`publish_staged_generation`/`fail_generation_build`/`bind_generation_embedding_profile`/`generation_write`; you are adding beside them, not changing them.

STEPS:
1. Worktree + venv per the rulebook. Confirm `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_build_authority.py tests/unit/test_generation_failure.py -q -o addopts='' -W error` is green before you change anything.
2. RED: write `tests/unit/test_local_workspace_membership.py` covering: fresh store startup creates `local` authority + memberships for existing users; repeated startup changes nothing and bumps no epoch; `create_user` yields exactly one epoch bump and a membership; `delete_user` disables (does not delete) the membership; a disabled/different-authority membership is repaired with a higher `policy_epoch`; removing `local` from the reviewed authorities makes a captured `BuildAuthority.check_local()` fail; changed role, Source ACL change, disabled user and deleted user each invalidate a captured authority; a `parametrize` over Fake and Ladybug where the Ladybug case closes and reopens the store between steps. Save `/tmp/hippo-pa1-membership-red.log`.
3. RED: write `tests/unit/test_managed_source_lifecycle.py` covering every bullet of PA4's CRITERIA plus: monkeypatched `Store.delete_source`, `_clear_passages`, `delete_passages_for_source`, `delete_code_for_source`, `remove_orphans`, `shutil.rmtree`, generation collect/discard and raw unlink all raise, and tombstone still succeeds; a held structural `query_session` opened before the tombstone fails validation after commit; a new session excludes the source; retired/active generations, history, raw references, snapshots and an unrelated source are byte-identical before and after; legacy `delete_source` path is unchanged (existing tests still pass); replay with the same operation_id returns `already_tombstoned` with no new epoch; a different actor without authority gets the generic denial and learns nothing; a source with an unpublished staging generation owned by the active build gets exactly that generation failed and job cancelled with code `source_tombstoned`, and the published active generation untouched; delete does not wait for a blocked model callback (use an event-controlled fake that blocks, as `test_generation_failure.py` does). Save `/tmp/hippo-pa1-lifecycle-red.log`.
4. Implement. Membership first, then the store primitive, then the service.
5. GREEN on Fake: both new files plus regressions `tests/unit/test_build_authority.py tests/unit/test_generation_failure.py tests/unit/test_generation_store.py tests/unit/test_evidence_access.py tests/unit/test_evidence_epochs.py tests/unit/test_snapshot_store.py tests/unit/test_query_snapshots.py tests/unit/test_ingest_concurrency.py tests/unit/test_store_knowledge.py tests/unit/test_web_auth.py tests/unit/test_status_access.py` and any user/role store tests you find with `rg -l "create_user" tests/unit`. Log `/tmp/hippo-pa1-fake-green.log`.
6. GREEN on Ladybug: the two new files plus `test_build_authority.py test_generation_failure.py test_generation_store.py test_evidence_epochs.py test_query_snapshots.py`. Log `/tmp/hippo-pa1-ladybug-green.log`. Ladybug is slow; run it once at the end, not per iteration.
7. Ruff check + format on every changed file.
8. Write `evidence-pa1.md` with: the exact commands run, result lines, log paths, RED log paths, the list of monkeypatched destructive operations proven untouched, and any deviation from the plan with the reason.
9. Commit on `wp/pa1` in two or three commits (membership; tombstone primitive + service; tests may be included with each). Stage only owned files.

DONE WHEN: steps 5–7 green with `-W error`; `evidence-pa1.md` written; commits on `wp/pa1`; `horch done` lists commit hashes, all files touched, the verbatim `TombstoneReceipt`/`tombstone_managed_source`/`ensure_local_workspace_memberships` signatures as implemented, test counts per backend with log paths, and every existing test you had to modify.

OUT OF SCOPE: pipeline `delete_source`/`reindex` dispatch (Task 3 will call your service), any HTTP/MCP/CLI route, physical purge, restoration, retention, Neo4j runs, projection/inventory (Task 2).

REPORT: `horch note` at each step 1–9. `horch tell orchestrator "[<role>] BLOCKED: ..."` for any contract or ownership question; wait for the answer.
