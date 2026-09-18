# txown evidence — per-thread transaction ownership for the stores (coordinator review finding 3)

Worker `backend-developer-3`. Branch `wp/txown`, base `5564d73`, worktree `.worktrees/txown`.
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, real_ladybug 0.15.3, mcp pinned to 2.1.1.

Scope proved here: every store can answer "does the *calling* thread hold an open transaction
on this store?", and `BuildAuthority.check` asks that instead of reading the process-global
transaction depth. Nothing else changes: the depth counter, the `_transaction_failed` poison
flag, the lock and its acquisition order all keep their current values and order for their
current users. No production route is activated, and no Neo4j database was contacted.

## Commits

| Hash | Subject |
|---|---|
| `7e6328c` | Answer the ambient-transaction question per thread |
| (this file) | Record the per-thread ownership evidence |

## Public contract as implemented

```python
# src/hippo/store/base.py (Neo4jBase), src/hippo/store/ladybug.py (LadybugStore),
# tests/fakes/fake_store.py (FakeStore) — same name, same body, same semantics
def in_ambient_transaction(self) -> bool:
    """True only when the calling thread has an open transaction on this store."""
    return self._transaction_owner == threading.get_ident()
```

`_transaction_owner` is `threading.get_ident()` of the thread that opened the **outermost**
transaction, and `None` otherwise. Nested transactions on that thread keep the same owner.
No existing public signature changed. `build_authority._ambient()`, a module-private helper
with no other caller, is deleted; `check` now reads
`if self._store.in_ambient_transaction():` and raises the unchanged
`RuntimeError("External build checks require no ambient transaction")`.

Two deliberate properties:

- **The probe takes no lock.** Every store holds `_lock` for its whole transaction body, so a
  probe that acquired it would block the asking thread until the holder committed instead of
  answering it — the opposite of the fix. It is a single attribute read.
- **Owner identity, not depth.** The owner is set and cleared in lockstep with the outermost
  enter/exit, so `_transaction_owner` alone is the answer; reading the depth beside it could
  only reintroduce the global view. `None == get_ident()` is `False`, so the un-owned answer
  needs no special case.

## Exact enter/exit sites changed, per store

| Store | Init | Claim (outermost enter) | Clear (every exit) | Reader |
|---|---|---|---|---|
| `src/hippo/store/base.py` (`Neo4jBase`, Neo4j) | `:167` beside `self._transaction = None` | `:250`, right after `self._transaction = transaction` / `self._transaction_failed = False` inside `session.begin_transaction()` | `:265`, the `finally` that already does `self._transaction = None` — reached on commit, on rollback and on any exception | `:226-230` |
| `src/hippo/store/ladybug.py` (`LadybugStore`) | `:271` beside `self._transaction_depth = 0` | `:392`, inside `if outer:` after `self.run("BEGIN TRANSACTION")` has succeeded | `:412`, the `finally`'s `if outer:` beside `self._transaction_failed = False` | `:379-383` |
| `tests/fakes/fake_store.py` (`FakeStore`) | `:70` beside `self._transaction_failed = False` | `:151`, inside `if outer:` after `self._transaction_failed = False` | `:167`, the `finally`'s `if outer:` | `:120-124` |

The claim sits *after* `BEGIN TRANSACTION` in the Ladybug store so a failed `BEGIN` records no
owner; the `try` has not been entered at that point, so there is nothing to clear.
`"_transaction_owner"` is added to the Fake store's `transient` set (`:138`) beside
`_transaction_depth` and `_transaction_failed`: it is transaction machinery, so it must not be
part of the deep-copied rollback snapshot.

The Neo4j store's enter/exit sites cannot be executed in this fleet (no Neo4j run was
authorised for this worker, and the shared `store` fixture only reaches Neo4j when a disposable
database is configured). Its method body is character-for-character the same as the other two,
and `test_the_neo4j_store_mirrors_the_same_ownership_answer` calls
`Neo4jBase.in_ambient_transaction` against a stand-in `self` to prove that body's three
answers (unowned, owned by this thread, owned by another). What remains unexecuted is only the
claim at `:250` and the clear at `:265`, both single assignments in the same `finally` that
already nulls `self._transaction`.

## Commands and results

Working directory `/Users/mascott/projects/hippo/.worktrees/txown` for every run. No run needed
a warning filter: none of these files imports `fastapi.testclient`, so every command is a bare
`-W error`.

| # | Command | Result |
|---|---|---|
| 1 | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_build_authority.py tests/unit/test_store_knowledge.py tests/unit/test_generation_store.py tests/unit/test_evidence_epochs.py -q -o addopts='' -W error` | EXIT 0, **121 passed, 1 skipped** (baseline before any change) — `/tmp/hippo-txown-baseline.log` |
| 2 | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_transaction_ownership.py -q -o addopts='' -W error` | EXIT 1, **8 failed, 1 skipped** (RED) — `/tmp/hippo-txown-red.log` |
| 3 | `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_transaction_ownership.py -q -o addopts='' -W error` | EXIT 1, **9 failed** (RED) — `/tmp/hippo-txown-red-ladybug.log` |
| 4 | Fake acceptance, see below | EXIT 0, **242 passed, 2 skipped** in 14s — `/tmp/hippo-txown-fake-green.log` |
| 5 | Ladybug acceptance, see below | EXIT 0, **120 passed** in 33s — `/tmp/hippo-txown-ladybug-green.log` |
| 6 | `.venv/bin/ruff check <the 5 changed files> && .venv/bin/ruff format --check <same>` | All checks passed; 5 files already formatted |

Run 4:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest \
  tests/unit/test_transaction_ownership.py tests/unit/test_build_authority.py \
  tests/unit/test_store_knowledge.py tests/unit/test_generation_store.py \
  tests/unit/test_evidence_epochs.py tests/unit/test_snapshot_store.py \
  tests/unit/test_generation_failure.py tests/unit/test_query_snapshots.py \
  tests/unit/test_ingest_concurrency.py tests/unit/test_local_workspace_membership.py \
  tests/unit/test_managed_source_lifecycle.py -q -o addopts='' -W error
```

Run 5:

```
HIPPO_TEST_STORE=ladybug .venv/bin/pytest \
  tests/unit/test_transaction_ownership.py tests/unit/test_build_authority.py \
  tests/unit/test_generation_failure.py tests/unit/test_local_workspace_membership.py \
  -q -o addopts='' -W error
```

Run 6 covered `src/hippo/store/base.py`, `src/hippo/store/ladybug.py`,
`tests/fakes/fake_store.py`, `src/hippo/knowledge/build_authority.py` and
`tests/unit/test_transaction_ownership.py`.

## What RED proved

Every case except the coordinator one RED with `AttributeError: 'FakeStore'/'LadybugStore'
object has no attribute 'in_ambient_transaction'` (and `type object 'Neo4jBase' has no attribute
'in_ambient_transaction'`) — the missing API: 7 of them on Fake, where `auto_abort` is skipped,
and 8 on Ladybug, where it runs. The one that matters carries the actual defect
from review finding 3, and it is deliberately written without the new method so it cannot RED
for the trivial reason:

```
test_build_authority_check_ignores_a_transaction_another_thread_owns
  assert not thread.is_alive() and errors == []
E   Left contains one more item: RuntimeError('External build checks require no ambient transaction')
```

That is a second thread's `BuildAuthority.check` being rejected for a transaction it does not
own — the concurrent-bootstrap rejection the plan's §1 forbids — on both Fake (`:132` of
`/tmp/hippo-txown-red.log`) and Ladybug. It is GREEN on both after the change.

## The new tests

`tests/unit/test_transaction_ownership.py`, 6 tests / 9 cases, on the shared `store` fixture
(so both backends, one per `HIPPO_TEST_STORE` run):

| Test | Proves |
|---|---|
| `test_only_the_thread_inside_the_transaction_reports_an_ambient_transaction` | True on the owner and False on a fresh thread, before / inside / nested inside / after; nesting keeps the outermost owner and leaving a nested body does not release it |
| `test_a_transaction_another_thread_holds_is_never_the_callers_transaction` | The reverse direction: a helper thread parks inside a transaction (holding the store lock) and the main thread's probe still answers False *promptly* — which is also the assertion that the probe never takes the store lock |
| `test_every_transaction_exit_releases_the_threads_ownership[commit\|exception\|nested_failure\|auto_abort]` | Ownership is cleared on all four exit paths, checked from the owning thread and a fresh one |
| `test_build_authority_check_ignores_a_transaction_another_thread_owns` | The coordinator scenario above |
| `test_build_authority_check_still_refuses_the_callers_own_transaction` | The existing same-thread rejection is intact, still raises before any checkpoint runs, and `check_local` still works inside a caller-owned transaction |
| `test_the_neo4j_store_mirrors_the_same_ownership_answer` | `Neo4jBase`'s mirrored body, against a stand-in self |

The four exit paths are four distinct code paths, not one:

- `commit` — normal exit.
- `exception` — the body raises; the `except BaseException` branch runs (`ROLLBACK` on Ladybug).
- `nested_failure` — a nested transaction raises and is caught **inside the outer body**, so the
  outer body completes normally and then trips
  `RuntimeError("Nested transaction failed; outer transaction must roll back")`
  (`ladybug.py:398`, `fake_store.py:156`, `base.py:254`). This is the only route to the rollback
  branch without an exception in the outer body.
- `auto_abort` — Ladybug only (`pytest.skip` when `store.knowledge_backend != "ladybug"`): a
  duplicate primary key makes the driver abort the transaction itself, so the store's own
  `ROLLBACK` fails with `No active transaction for ROLLBACK.` and is swallowed at
  `ladybug.py:403-405`. Verified out-of-band that this is what that statement raises, so the
  test really does enter the swallowed-rollback path and not just a parser error.

Thread discipline in these tests, because `-W error` turns an unhandled thread exception into
`PytestUnhandledThreadExceptionWarning` and would hide the real failure: every thread body
catches `BaseException` and records it for the calling thread to assert, every blocking wait is
bounded, and `release.set()` runs in the caller's `finally` before the join, so a failed
assertion on the main thread can never leave a helper parked (the PC2 lesson from the review).

## Findings for the orchestrator (out of my file ownership, untouched)

**Resolution (orchestrator, 2026-09-11):** all three probes below now use `in_ambient_transaction()`.
`generations.py` was switched in the Task 1 follow-up (`99a41b7`, decision 7); `staged_prose.py` and
the coordinator's own probe were switched together in `158ebf2` with the deferred concurrent-build
test enabled. The text below is kept as the original finding.

Two sibling probes read the same process-global attributes and have the same defect. Both are in
files this brief lists under "do NOT touch", so neither is changed here:

1. `src/hippo/knowledge/staged_prose.py:224` —
   `if getattr(store, "_transaction_depth", 0) or getattr(store, "_transaction", None) is not None:
   raise ValueError("Staged refresh wrapper requires no outer transaction")`. Same false
   rejection as finding 3: a concurrent refresh in another thread makes this fire. One-line
   switch to `store.in_ambient_transaction()`.
2. `src/hippo/store/generations.py:80` —
   `if not getattr(self, "_transaction_depth", 0) and getattr(self, "_transaction", None) is None:
   raise RuntimeError("Managed tombstone requires the caller's transaction")`. This one is the
   *opposite* direction and therefore a false **negative**: while thread A holds a transaction,
   thread B's `apply_source_tombstone` passes the guard without owning any transaction, so the
   write it claims to protect runs unguarded. The correct form is
   `if not self.in_ambient_transaction(): raise ...`.

`src/hippo/ingest/prose_generation.py:~652` is the coordinator's own probe, explicitly out of
scope: the orchestrator switches it to `ctx.store.in_ambient_transaction()` after the
coordinator commits, and un-skips the deferred test then.

## Out of scope, untouched

`src/hippo/ingest/prose_generation.py` and its test, the other store modules
(`knowledge/generations/users/authorization/snapshots.py`), anything under `src/hippo/web`,
`src/hippo/knowledge/*` other than `build_authority.py`, `docs/`, the checkpoint and every
`GATES.md`. Authority-check performance (review minor 9) and Neo4j runs are also out of scope.
