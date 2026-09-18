# Brief: n1-fix — a swallowed refusal outranks a later ordinary exception (guard finding N1)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Worktree `.worktrees/n1-fix` on branch
`wp/n1-fix` from the `rag-it-all-tibs` HEAD named in the spawn message, own venv
(`.venv/bin/pip install -e '.[dev]'`, pin `mcp==2.1.1`), one pytest process at a time, logs under
`/tmp/hippo-n1-fix-*.log`, never Neo4j, never `pkill -f`, never kill a PID you did not start.

GOAL: close finding N1 of `ai_docs/reports/2026-09-16-cdk-r7-confirmation.md` (section 5): an
`emit` that swallows the guard's refusal (`except BaseException` or a bare `except:`) and then raises
an ordinary exception for its own reason must still fail the sync with the refusal, not be counted as
an ordinary `emit_failed` revision that lets the run publish.

CONTEXT: `src/hippo/connectors/guard.py:218-229` raises the recorded refusal only when no exception
is propagating (`propagating` flag). Ruling R82 in `ai_docs/plans/cdk-rulings.md` adopts the
reviewer's exact fix; read the finding's "The fix" paragraph and the "Notes that are not findings"
(nested guards stay as they are). The reviewer's reproduction is `/tmp/hippo-confirm-probe-residual.py`
case A (read it; do not copy it into the repo as-is).

REQUIRED:
1. In `forbid_effects`, replace the `propagating` flag with the exception in flight
   (`except BaseException as error: in_flight = error; raise`). In the `finally`, raise
   `EmitSideEffect(swallowed) from in_flight` whenever a record exists and `in_flight` is neither an
   `EmitSideEffect` nor a `KeyboardInterrupt`/`SystemExit`. The existing
   `test_an_unrelated_failure_inside_the_guard_still_propagates` (no record) and
   `test_a_propagating_violation_is_not_raised_a_second_time_on_the_way_out` must stay green
   unchanged.
2. Three new tests, each shown RED before the fix (log the red run) and GREEN after:
   - `tests/unit/test_connector_guard.py`: a swallowed refusal outranks a later `ValueError` (the
     `EmitSideEffect` raised, `__cause__` is the `ValueError`).
   - `tests/unit/test_connector_sync.py`: a `[M10c]` row of `test_the_failure_matrix` in which
     swallow-then-raise gives `ConnectorContractViolation`, no `Generation` written, and one refused
     model request that never reached the transport; on Fake and LadybugDB.
   - `tests/unit/test_connector_testing_kit.py`: the same connector shape is reported as `emit_pure`
     (not `emit_deterministic`) by the kit.
3. Run, all `-q -o addopts='' -W error`: the CK3 CHECK line and the CK4 CHECK line of
   `ai_docs/gates/rag-it-all/cdk/GATES.md` verbatim (both backends where the line has them), plus
   `tests/unit/test_connector_exemplar.py`; `ruff check` and `ruff format --check` on every file you
   touched.
4. Evidence file `ai_docs/gates/rag-it-all/cdk/evidence-n1-fix.md`: the red and green logs, the
   commands and exit codes, and the diff summary. No golden, lock, guide or scaffold output changes;
   assert that `git diff --stat` shows only the four files above and the evidence file.

FILES:
  - own: `src/hippo/connectors/guard.py`, `tests/unit/test_connector_guard.py`,
    `tests/unit/test_connector_sync.py` (the new row and its helper only),
    `tests/unit/test_connector_testing_kit.py`, `ai_docs/gates/rag-it-all/cdk/evidence-n1-fix.md`.
  - do NOT touch: anything else (no `sync.py`, no `testing.py`, no goldens, no ledger, no rulings).

DONE WHEN: the three tests exist and were red then green; CK3 and CK4 lines green on the backends
they name; Ruff clean; committed on `wp/n1-fix` (never push, never merge); `horch done` with the
commit hash, the counts per run and the evidence path.

REPORT: `horch note` at red, at green, at commit; `horch tell orchestrator "[<role>] BLOCKED: ..."`
only for a missing input.
