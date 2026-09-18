# Brief: confirm the closure of finding N1 (n1-fix)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree
(`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message (e2a6f48, `wp/n1-fix` merged).
Read-only except your one output: `ai_docs/reports/2026-09-16-cdk-n1-confirmation.md`. Run tests on
Fake only, plus the single LadybugDB row `test_the_failure_matrix[M10c]`; the orchestrator's gate
checker is running the full LadybugDB lines at the same time, so no other LadybugDB run. Never Neo4j,
never `pkill -f`, never kill a PID you did not start. Logs under `/tmp/hippo-n1-confirm-*.log`.

GOAL: rule CLOSED or OPEN for finding N1 of `ai_docs/reports/2026-09-16-cdk-r7-confirmation.md`
(section 5) as fixed by `n1-fix` (commits 6952b41 and 9a89a90; evidence
`ai_docs/gates/rag-it-all/cdk/evidence-n1-fix.md`; ruling R82 in `ai_docs/plans/cdk-rulings.md`).

REQUIRED:
1. Read the `forbid_effects` diff (`git diff 57171f4 HEAD -- src/hippo/connectors/guard.py`) against
   the finding's "The fix" paragraph; confirm the two exclusions (`KeyboardInterrupt`, `SystemExit`)
   and that the refusal itself is not re-raised a second time.
2. Rerun `/tmp/hippo-confirm-probe-residual.py` (case A must raise `EmitSideEffect`; cases B and C
   unchanged from `/tmp/hippo-confirm-probe-residual*.log` if a log exists, else from the report).
3. Undo the fix in-process (a mutation plugin in the style of `/tmp/hippo_confirm_mutations.py`, or a
   temporary stash you restore) and show each of the three new tests fails, then passes at HEAD:
   `test_connector_guard.py::test_a_swallowed_refusal_outranks_a_later_ordinary_failure`,
   `test_connector_sync.py::test_the_failure_matrix[M10c]` (Fake and LadybugDB),
   `test_connector_testing_kit.py::test_a_swallowed_refusal_followed_by_an_ordinary_raise_is_reported_as_emit_pure`.
   Leave the tree exactly as you found it (`git status --porcelain` empty but for your report).
4. Confirm the diff `57171f4..HEAD` touches only the five files the fixer names, and that no golden,
   lock, guide or scaffold output changed.
5. A short table (check, result, what you ran) and a one-line verdict: N1 CLOSED, or OPEN with the
   exact remaining fix. Note, not finding: the untested `KeyboardInterrupt`/`SystemExit` exclusion.

FILES:
  - own: `ai_docs/reports/2026-09-16-cdk-n1-confirmation.md`.
  - do NOT touch: anything else.

DONE WHEN: the report exists with the table and the verdict; `ruff format --check` clean;
`horch done` with the verdict.

REPORT: `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a missing input.
