# Brief: activation Task 1 follow-up — tombstone barrier in claim_generation_build and review minors

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa1fix` (branch `wp/pa1fix`, base `82bd317`, the current `rag-it-all-tibs` HEAD, which already contains Task 1 and Task 2).

GOAL: Close the one major and the cheap minors from `ai_docs/reports/2026-09-11-pa1-review.md` so that a committed tombstone is a store-level barrier, not a dispatcher courtesy. Committed on `wp/pa1fix`.

CONTEXT:
- Task 1 as merged: `src/hippo/store/knowledge.py` (`ensure_local_workspace_memberships`, `_ensure_local_workspace_memberships_locked`, `_disable_local_workspace_memberships_locked`, `_local_mapping_available`), `src/hippo/store/generations.py` (`apply_source_tombstone`, `SourceTombstone`, `tombstone_scope_key`), `src/hippo/knowledge/source_lifecycle.py` (`tombstone_managed_source`, `TombstoneReceipt`), `src/hippo/store/authorization.py` (decorator hook), tests `tests/unit/test_local_workspace_membership.py`, `tests/unit/test_managed_source_lifecycle.py`, evidence `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa1.md`.
- Review report: read all of it, especially PROBE9 (the major) and the minors list with proposed fixes. Plan: `ai_docs/plans/rag-it-all-task-5-production-activation.md`, "Managed delete" section and invariants 1, 2, 9.

DECISIONS (final):
1. MAJOR. `claim_generation_build` (`src/hippo/store/generations.py` ~:129-186) must refuse, after `_lock_source`, when the source carries a current-only tombstone `Suppression` (scope key `tombstone_scope_key(source_id)`, reason `tombstone`) or `status == "deleted"`. Refuse with the existing busy/denied error family the coordinator already maps, never a new public message. It must not re-fence, not install `active_build_id`, and not run `_collect_generation`. RED: reproduce PROBE9 exactly (tombstone, then claim on the failed unpublished generation) and assert no fence advance, no active build, the attempt untouched, then GREEN. Second test: a trusted-local replay of the same operation ID after an attempted claim reports the SAME `fencing_token` as the original receipt, which turns review deviation 7 from reachable into unreachable; update the deviation text in `evidence-pa1.md` accordingly.
2. MINOR, disable path: `_disable_local_workspace_memberships_locked` disables in place (sets `enabled=False`, raises `policy_epoch`) and preserves the existing `mapping_authority`; it never rewrites a non-local authority to `local`. Test with a `reviewed` membership.
3. MINOR, guard parity: `_disable_local_workspace_memberships_locked` gets the same `_local_mapping_available` guard as its sibling, so `delete_user` on a pre-schema-5 file does not raise on a missing table. Test on Ladybug with the migration fixture pattern from `tests/unit/test_store_migrations.py`.
4. MINOR, oracle: `tombstone_managed_source` must establish the actor's standing BEFORE revealing whether the source is managed. Order: validate `operation_id`; capture build authority for the source (this denies unauthorized readers with the generic `AuthorizationChanged` whether or not the source exists or is managed); only then raise `UnmanagedSource` for a legacy source. Test: an unauthorized reader gets the identical generic denial for a managed source, an unmanaged source, and a nonexistent source ID.
5. MINOR, tests only: assert `ctx.jobs.cancel` (or the actual cooperative-cancellation call) is requested for `index:<source_id>` before the transaction; assert many changes produce exactly one epoch bump in the public `ensure_local_workspace_memberships`.
6. Leave as documented, no code change: `create_user` under the schema guard maps nobody until the next `on_first_connection` (add one docstring sentence); the Neo4j `Store.on_first_connection` + `users.py` lane stays untested here (the orchestrator runs Neo4j parity later).

FILES:
  - own: `src/hippo/store/generations.py`, `src/hippo/store/knowledge.py`, `src/hippo/knowledge/source_lifecycle.py`, `tests/unit/test_managed_source_lifecycle.py`, `tests/unit/test_local_workspace_membership.py`, `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa1.md` (append a "Follow-up 2026-09-11" section; do not rewrite history).
  - do NOT touch: `src/hippo/store/base.py`, `src/hippo/store/ladybug.py`, `tests/fakes/fake_store.py`, `src/hippo/knowledge/build_authority.py` (another worker owns their transaction machinery right now), `src/hippo/store/authorization.py`, `src/hippo/ingest/*`, `src/hippo/web/*`, the shared `GATES.md`, `docs/`, the checkpoint. If decision 3 seems to need `ladybug.py`, stop and ask.

STEPS:
1. Worktree + venv per the rulebook (with the `mcp==2.1.1` pin). Baseline green: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py tests/unit/test_local_workspace_membership.py tests/unit/test_generation_store.py tests/unit/test_generation_failure.py tests/unit/test_prose_generation.py -q -o addopts='' -W error` (note: `test_prose_generation.py` exists in this HEAD only if the coordinator has been committed; if it is absent, drop it and say so).
2. RED for decisions 1–5, save `/tmp/hippo-pa1fix-red.log`.
3. Implement; GREEN Fake on the baseline set plus `tests/unit/test_build_authority.py tests/unit/test_evidence_access.py tests/unit/test_evidence_epochs.py tests/unit/test_store_knowledge.py tests/unit/test_store_migrations.py tests/unit/test_query_snapshots.py`, log `/tmp/hippo-pa1fix-fake-green.log`.
4. GREEN Ladybug: `test_managed_source_lifecycle.py test_local_workspace_membership.py test_generation_store.py test_store_migrations.py`, log `/tmp/hippo-pa1fix-ladybug-green.log`.
5. Ruff check + format; append the evidence section; commit on `wp/pa1fix` (one or two commits).

DONE WHEN: steps 3–5 green with `-W error`; evidence appended; commits on `wp/pa1fix`; `horch done` lists commits, files, the exact refusal error type used in decision 1, and test counts with log paths.

OUT OF SCOPE: Neo4j runs (orchestrator), Task 3 dispatch, anything in the do-NOT-touch list.

REPORT: `horch note` per step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for any contract question; wait.
