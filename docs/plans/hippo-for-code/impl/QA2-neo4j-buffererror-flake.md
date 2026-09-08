# QA2 — Characterise and fix the intermittent Neo4j `BufferError` in the test suite

Read `impl/00-impl-context.md` first. Worktree `.worktrees/qa2`, branch `wp/qa2`. Neo4j test container:
name `hippo-neo4j-qa2`, port **17690**.

Three independent workers hit the same thing: with `HIPPO_TEST_STORE=neo4j`, an intermittent
`BufferError` raised inside the neo4j Python driver's own `close()` during test teardown, in
`tests/unit/test_web_auth.py`, a different test each run, roughly 2 runs in 5. It reproduces on the
pristine `code-graph` tip with none of the new code loaded, so it is pre-existing — but it will make the
final three-store gate flaky, and a flaky gate hides real failures.

## Do this

1. Reproduce: run `tests/unit/test_web_auth.py` under `HIPPO_TEST_STORE=neo4j` in a loop (10-20 runs)
   against your container; capture the full traceback and the driver/python versions
   (`.venv/bin/pip show neo4j`, `.venv/bin/python --version`).
2. Find the cause. Likely suspects: a `Driver`/session closed from a different thread than it was
   created on (the web tests spin an app + background jobs — see `core/context.py`, `core/jobs.py`,
   `store/base.py`'s driver lifecycle and the `store` fixture teardown in `tests/conftest.py`); a
   driver closed twice; a bolt socket torn down while a background thread still holds a buffer view.
   `BufferError: Existing exports of data: object cannot be re-exported` from a `memoryview` is the
   classic shape. Read the driver's `close()` path in `.venv/lib/python*/site-packages/neo4j/` to confirm.
3. Fix it in the smallest correct place — the store's close ordering / thread ownership, or the
   fixture's teardown ordering — never by swallowing the exception or retrying the test. If the fix is
   in `src/hippo/store/base.py` or `memory.py`, keep the LadybugDB and fake stores untouched unless the
   same ordering bug exists there.
4. Prove it: 20 consecutive green runs of `test_web_auth.py` and one full `tests/unit` run on Neo4j, plus
   `just test` and `just test-fake` green (no behaviour change for the other backends), lint green.

## Done when

Root cause written in the ledger note with the driver code path cited, the fix committed on `wp/qa2`
with a test if one can pin it (a teardown-ordering test is fine), 20/20 green. If after ~2 hours the
cause is not found, commit nothing, write what you learned (exact traceback, what you ruled out) to
`docs/plans/hippo-for-code/research/QA2-neo4j-flake.md` and report that instead.
`horch tell orchestrator "[<role>] DONE: wp/qa2 ..."`, ledger summary, close pane.
