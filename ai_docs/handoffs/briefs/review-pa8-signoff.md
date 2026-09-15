# Brief: PA8 sign-off review of the production activation ledger

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message (the final cleanup batch is merged and the orchestrator has re-run PA1–PA8). You read and run; you do not edit source or tests.

GOAL: State whether PA8 ("independent SPEC and QUALITY reviews have no unresolved findings") can be signed for `ai_docs/gates/rag-it-all/task-5-production-activation/GATES.md`, by re-checking every finding of every activation review against HEAD.

CONTEXT: reviews `ai_docs/reports/2026-09-11-pa1-review.md`, `pa2`, `pa3a`, `pa3b`, `pa4b1`, `pa4b2`, `pa4c` + `pa4c-rereview`, `pa4d`, `2026-09-12-pa4-wrapup-review.md`; evidence files under the ledger directory including `evidence-cleanup4.md`; `ai_docs/handoffs/briefs/task4-notes.md` (every open bullet must be either closed or explicitly deferred with an owner task); `neo4j-parity.md`; the plan `ai_docs/plans/rag-it-all-task-5-production-activation.md` with its amendments and its "Completion checklist".

FILES:
  - own: `ai_docs/reports/2026-09-12-pa8-signoff.md`.
  - do NOT touch: anything else.

STEPS:
1. Run PA1–PA8 verbatim from the ledger (PA7 is Ladybug and long; run it once), each to `/tmp/hippo-pa8-<gate>.log` with `echo EXIT $?`; run the full Fake unit suite once with the sanctioned AnyIO ignore, `/tmp/hippo-pa8-full-fake.log`.
2. Build one table over every finding from every report above (report, finding id, severity, one-line claim): CLOSED (commit or evidence that closes it, verified by reading the code) / DEFERRED (with the task or note that owns it; only acceptable for items the plan itself assigns to a later task) / OPEN. A PA8 signature requires zero OPEN and every DEFERRED item to name its owner.
3. Walk the plan's "Completion checklist" and "Invariants that block the activation" (1–10): for each, PROVEN with the test or evidence, or NOT.
4. Verdict: `PA8: SIGNABLE` or `PA8: NOT SIGNABLE` with the exact list of what blocks it.

DONE WHEN: the report exists with the runs, the findings table, the checklist/invariants walk and the verdict. `horch done` states the verdict and the count of OPEN and DEFERRED items.

CONSTRAINTS: no edits outside your report; no Neo4j; `HIPPO_TEST_STORE` explicit on every command.

REPORT: `horch note` after the runs, after the table, after the report.
