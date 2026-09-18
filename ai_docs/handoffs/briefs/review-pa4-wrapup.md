# Brief: independent SPEC/QUALITY review of the Task 4 wrap-ups (4e web, 4f evaluation) and the whole activation ledger

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`); the work is merged at the HEAD named in the spawn message. You read and run; you do not edit source or tests.

GOAL: Verdict on Tasks 4e and 4f, and a first pass at PA8 (the activation ledger as a whole): which gate CHECK lines pass verbatim at HEAD, which still need Neo4j evidence, and whether any wrap-up item in `ai_docs/handoffs/briefs/task4-notes.md` remains open.

CONTEXT: briefs `ai_docs/handoffs/briefs/pa4e-web-wrapup.md` and `pa4f-eval-wrapup.md` (their DECISIONS are the contract); evidence `evidence-pa4e.md`, `evidence-pa4f.md`; the earlier reviews under `ai_docs/reports/2026-09-11-pa4*.md` and `2026-09-11-pa3b-review.md`; the plan `ai_docs/plans/rag-it-all-task-5-production-activation.md` with its amendments; the ledger `ai_docs/gates/rag-it-all/task-5-production-activation/GATES.md`; `neo4j-parity.md`.

FILES:
  - own: `ai_docs/reports/2026-09-12-pa4-wrapup-review.md`.
  - do NOT touch: anything else.

STEPS:
1. Run every PA CHECK line verbatim from the ledger (PA1–PA7; add the AnyIO form (b) ignore only where a listed file imports `fastapi.testclient` at module level, and say where), each to `/tmp/hippo-pa-wrapup-<gate>.log` with `echo EXIT $?`. PA7 is Ladybug and long; run it once.
2. SPEC review of 4e decisions 1–8 and 4f decisions 1–5: PROVEN (test) / UNTESTED / VIOLATED (file:line). Include: exactly one public-failure helper in the web layer (grep `str(exc)` under `src/hippo/web`: only the protected legacy settings validators may remain); exact-type 4xx catches; the preview notice; the bounded legacy error storage; the `bulk_refused` 409 and the `ManagedActorRequired` mapping on the bulk route; `effective_settings` shared; `ProjectionError` raised at the source; the eval public failure reason visible to a reader with no private text; `ask._dispatch` gone and the promoted rule in `dense_session.retrieval_session` with the access-versus-session precedence explicit and tested; bounded runner logging; the fact-bearing question-maker corpus; late-bound `rag_all` lookup.
3. QUALITY review across both: any remaining `str(exc)` on a client path; any duplicated failure helper; the three copies of `authorization_changed`; whether the preview notice can itself leak a managed source's existence to a preview audience that should not learn it (the notice must be workspace-level, not per source); whether the sweep changes (job/pointer clearing, constants moved) keep Neo4j's `memory.py` lane in step.
4. Ledger pass: list each PA gate with PASS/FAIL at HEAD, what evidence file backs it, and what (if anything) Neo4j still owes; list every open item in `task4-notes.md` that is not closed by the merged code, with a one-line disposition (defer to Task 16 / wrap-up / fixed).

DONE WHEN: the report exists with `4e: SPEC/QUALITY`, `4f: SPEC/QUALITY`, the two tables, the ledger pass, numbered findings with severity, file:line, why, proposed fix, run results with log paths. `horch done` states the verdicts, finding counts, and the report path.

CONSTRAINTS: no edits outside your report; no Neo4j; `HIPPO_TEST_STORE` explicit on every command.

REPORT: `horch note` after the runs, after the tables, after the report.
