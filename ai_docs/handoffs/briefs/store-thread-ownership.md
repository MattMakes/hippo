# Brief: per-thread transaction ownership for the stores (coordinator review finding 3)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `txown` (branch `wp/txown`, base `5564d73`, the current `rag-it-all-tibs` HEAD).

GOAL: Every store can answer "does the CALLING thread currently hold an open transaction on this store?" and `BuildAuthority.check` uses that answer instead of the process-global transaction depth, so a second concurrent managed build in another thread is no longer mistaken for an ambient transaction. Committed on `wp/txown`.

CONTEXT:
- Origin: `ai_docs/reports/2026-09-11-prose-coordinator-review.md`, finding 3. Read that finding and its "checked and cleared" notes. Summary: the ambient-transaction probes in `src/hippo/knowledge/build_authority.py:167-168` (and one in `src/hippo/ingest/prose_generation.py:~652`, NOT yours) read the store's `_transaction_depth` / `_transaction`, which are process-global: every store holds one lock across the whole transaction body (`src/hippo/store/ladybug.py:378-384` and the equivalents in `src/hippo/store/base.py` and `tests/fakes/fake_store.py`), so while thread A is inside a transaction, thread B sees a nonzero depth and is rejected with "requires no ambient transaction". Plan section 1 of `ai_docs/plans/rag-it-all-task-5-prose-coordinator.md` requires concurrent bootstrap workers.
- The existing depth counter and lock semantics must NOT change for their current users (nested transactions, `metadata_mutation`, `permission_mutation`, `generation_write`, tests that assert depth). You are adding an ownership record beside them.
- The coordinator's own probe is under separate ownership in the root tree right now; the orchestrator will switch it to the new API after the coordinator commits. Design the API so that switch is a one-line change.

CONTRACT (frozen):

```python
# on every store class (Store/base, LadybugStore, FakeStore), same name and semantics
def in_ambient_transaction(self) -> bool:
    """True only when the calling thread has an open transaction on this store."""
```

Implementation guidance: record the owning thread identity (`threading.get_ident()`) when the outermost transaction opens on that thread, clear it when the outermost transaction closes on any exit path (commit, rollback, exception, auto-abort cleanup), and compare against the caller's identity. Nested transactions on the same thread keep the same owner. If the stores share a base implementation, implement it once; otherwise mirror it exactly in each store and test each. Do not change lock acquisition order or the depth counter's values.

`BuildAuthority.check` (and any sibling in `build_authority.py` that rejects ambient transactions) must call `store.in_ambient_transaction()`; `check_local` keeps its "may run inside a caller-owned transaction" contract unchanged.

FILES:
  - own: `src/hippo/store/base.py`, `src/hippo/store/ladybug.py` (transaction machinery only), `tests/fakes/fake_store.py` (transaction machinery only), `src/hippo/knowledge/build_authority.py` (probe only), `tests/unit/test_build_authority.py`, NEW `tests/unit/test_transaction_ownership.py`, NEW `ai_docs/gates/rag-it-all/task-5-prose-coordinator/evidence-txown.md`.
  - do NOT touch: `src/hippo/ingest/prose_generation.py` and its test (root tree, other owner), `src/hippo/store/{knowledge,generations,users,authorization,snapshots}.py`, anything under `src/hippo/web`, `src/hippo/knowledge/*` other than `build_authority.py`, `docs/`, the checkpoint, any `GATES.md`.

STEPS:
1. Worktree + venv per the rulebook (including the `mcp==2.1.1` pin). Baseline green: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_build_authority.py tests/unit/test_store_knowledge.py tests/unit/test_generation_store.py tests/unit/test_evidence_epochs.py -q -o addopts='' -W error`.
2. RED `tests/unit/test_transaction_ownership.py`: thread A opens a transaction and blocks on an event; thread B calls `in_ambient_transaction()` and gets False while A gets True; nested depth on A stays True; after A exits (commit path, rollback path, exception path, and the driver auto-abort path the Ladybug store handles) both get False; a `BuildAuthority.check` call from thread B while A holds a transaction succeeds (this is the coordinator scenario) and from A raises the existing ambient-transaction error. Parametrize Fake and Ladybug through the shared store fixture; the Neo4j (`base.py`) path cannot run here, so mirror its code exactly and say so. Save `/tmp/hippo-txown-red.log`.
3. Implement; keep the diff small and local to the transaction enter/exit code.
4. GREEN on Fake: the new file plus `test_build_authority.py test_store_knowledge.py test_generation_store.py test_evidence_epochs.py test_snapshot_store.py test_generation_failure.py test_query_snapshots.py test_ingest_concurrency.py test_local_workspace_membership.py test_managed_source_lifecycle.py`. Log `/tmp/hippo-txown-fake-green.log`.
5. GREEN on Ladybug: the new file plus `test_build_authority.py test_generation_failure.py test_local_workspace_membership.py`. Log `/tmp/hippo-txown-ladybug-green.log`.
6. Ruff check + format on changed files.
7. Write `evidence-txown.md` (commands, results, logs, RED log, the exact enter/exit sites you changed per store) and commit on `wp/txown` in one or two commits.

DONE WHEN: steps 4–6 green with `-W error`; evidence written; commits on `wp/txown`; `horch done` lists commits, files, the enter/exit sites changed per store, and test counts with log paths.

OUT OF SCOPE: the coordinator's probe line and un-skipping its deferred test (orchestrator does that after the coordinator commits); performance of authority checks (review minor 9); Neo4j runs.

REPORT: `horch note` per step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for any contract question; wait.
