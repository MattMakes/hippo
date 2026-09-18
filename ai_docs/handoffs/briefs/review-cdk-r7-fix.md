# Brief: confirm the closure of the CK7 review's code findings (r7-fix)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree
(`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message. Read-only except your one
output: `ai_docs/reports/2026-09-16-cdk-r7-confirmation.md`. You may run tests on Fake and LadybugDB
(never Neo4j, never `pkill -f`), one pytest process at a time, logs under `/tmp/hippo-confirm-*.log`.

GOAL: rule CLOSED or OPEN, per finding, for the eight code findings of
`ai_docs/reports/2026-09-15-cdk-code-review.md` that `r7-fix` closed (F1, F2, F3, F5, F10, F11, F14,
F15; merged at `7c8f132`; the fixer's evidence is `ai_docs/gates/rag-it-all/cdk/evidence-r7-fix.md`),
and confirm the two standing rules of CK7's CRITERIA are enforced by tests at this HEAD.

REQUIRED:
1. F1: rerun the first reviewer's reproduction `/tmp/hippo-review-probe3.py` (a connector whose `emit`
   swallows the refusal with a broad `except` and makes a second model call) against the rebased
   guard; it must fail the sync and fail `assert_emit_pure`. Confirm `EmitSideEffect` is a
   `BaseException`, that both guard entry points catch it by name, and that the one-violation test
   is real.
2. F2: confirm `reviewed` is absent from every built-in `sources_allowed` (33 predicates) and that
   `EdgeEmission(source="reviewed")` is refused for every built-in predicate; rerun the first
   reviewer's probe 5 if it is on disk.
3. F3, F5, F10, F11, F14, F15: read each fix against the finding's "exact fix" column and its test;
   run the mutation harness `/tmp/hippo_mutation_plugin.py` (`PYTHONPATH=/tmp`, `-p
   hippo_mutation_plugin`, `HIPPO_MUTATION=<name>`) where a mutation exists, and one hand mutation
   otherwise, to show each new test bites.
4. The committed goldens, the registry lock and the guide's marked regions are byte-identical to
   `c863e03` (the fixer asserts it; verify).
5. A table (finding, CLOSED/OPEN, the test that proves it, what you ran) and a one-line verdict:
   CK7's review findings CLOSED, or the list still OPEN with the exact remaining fix.

FILES:
  - own: `ai_docs/reports/2026-09-16-cdk-r7-confirmation.md`.
  - do NOT touch: anything else.

DONE WHEN: the report exists with the table and the verdict; `ruff format --check` clean;
`horch done` with the verdict and the per-finding results.

REPORT: `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a missing input.
