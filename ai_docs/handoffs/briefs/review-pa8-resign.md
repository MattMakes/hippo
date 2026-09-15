# Brief: PA8 re-sign-off after the closure batch

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message. You read and run; you do not edit source, tests or the ledger.

GOAL: State whether PA8 of `ai_docs/gates/rag-it-all/task-5-production-activation/GATES.md` ("independent SPEC and QUALITY reviews have no unresolved findings") is now SIGNABLE, by re-checking every row the previous sign-off left OPEN or DEFERRED against HEAD.

CONTEXT: the previous sign-off `ai_docs/reports/2026-09-12-pa8-signoff.md` (30 OPEN, 5 DEFERRED, verdict NOT SIGNABLE, with "What would make PA8 signable" items 1–6); the closure evidence `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa8close.md` (15 CLOSED, 1 OPEN) and `evidence-pa2f5.md` (PA2 finding 5 closed as unreachable-by-design; ruling recorded in `ai_docs/handoffs/briefs/task4-notes.md`); the orchestrator's full `--reverify` checker pass (its log path is in the spawn message) which ticked the boxes and wrote the EVIDENCE lines; the code-capture parity file `ai_docs/gates/rag-it-all/task-5-code-capture/neo4j-parity.md` and `evidence-lbfix.md` (the Ladybug engine defect that blocked PA7 and its fix). Since the previous sign-off, HEAD also gained the managed code-capture slices CC2, CC3, CC6, CC7, CC8, CC9a and the cc1fix lane fix; PA2/PA3/PA5/PA6/PA7 name files those merges rewrote, which is why the checker re-ran every gate.

ROUND 3 (2026-09-13, if the spawn message says so): the second sign-off `ai_docs/reports/2026-09-13-pa8-resign.md` left 14 ids (12 unowned LOW rows + D4/D5). Closure batch 2 (`evidence-pa8close2.md`, merged at `4c01df7`) CLOSED PA3a-8, PA4b2-7, W20, T2; ASSIGNED PA2-2, PA2-4, PA3a-11, PA3b-6, PA4b2-9, D4, D5 to numbered tasks in the activation plan's rollout section (`:~266-282`); ROUTED PA3a-6, PA3a-9, W15 to CC10 (`evidence-cc10.md`, merged at the HEAD the spawn message names). Re-check only those 14 plus anything the CC10 merge touched among the do-not-fix items; cite the two earlier reports for the rest. The clause is unchanged: a LOW with a named fix is unresolved unless CLOSED or assigned by the plan to a numbered task.

ROUND 4 (2026-09-14, if the spawn message says so): round 3 (`ai_docs/reports/2026-09-13-pa8-resign-round3.md`) left ONE row, PA2-4, plus a precondition (a full `--reverify` at the final HEAD) and two ledger amendments (PA1 CRITERIA opt-in set and the Scope line, applied at `dc20ccb`). PA2-4 was CLOSED by the `wp/pa2f4` slice (`evidence-pa2f4.md`, merged at `63aae1e`; `status._with_code_edges` counts a managed source's code edges from its selected generation's native rows; the PA2 line gained `tests/unit/test_status_code_edges.py`) and the projection now serves those arrows (`../task-5-code-capture/evidence-codeproj.md`, merged at `955cc11`). The activation plan's rollout section was corrected (D1/D2 closed, PA2-4 reassigned, eligibility text) at `dc20ccb`. The final `--reverify` (run 5) is running at HEAD `cbed8ca` when you start (`/tmp/hippo-orch-pa-gates-5.log`); do your row work first and, before writing the ledger-recording section, wait for that log's `UNMET:` summary line, then check every `[x]` and EVIDENCE line against it and confirm the Status line names `cbed8ca` (the orchestrator updates it after the run; if it still names `14d0a37` when you finish, say so as the one open recording item rather than failing the verdict on it). Re-check only PA2-4, the do-not-fix items, and the ledger; cite the three earlier reports for the rest.

REQUIRED:
1. For each of the 30 OPEN rows and 5 DEFERRED rows (round 3: the 14 above; round 4: PA2-4 only): cite the closing commit and test (read the code at HEAD by symbol, not stale line numbers), or state it is still OPEN with the reason. Verify each closure actually does what the review asked, not merely that a commit names it.
2. Confirm the ledger records what it claims: every `[x]` has an EVIDENCE line from the reverify pass, the Status line names the revision, and the PA7 line's evidence is from a process that started at HEAD (not from the earlier run that loaded `c893a95`).
3. Confirm the two items the previous review said must not be "fixed" were left alone.
4. Rule explicitly on the clause: if every remaining row is either CLOSED, DEFERRED-by-the-plan (Task 16 assignments now in the plan's rollout section) or closed-as-unreachable with a pinned invariant, say SIGNABLE; otherwise NOT SIGNABLE with the blocking ids.
5. Re-run only the PA2 line (it gained `tests/unit/test_multi_generation_support.py`) and the PA8 static line; do not re-run PA7 (77 minutes) — cite the checker's EVIDENCE line instead. Never Neo4j.

FILES:
  - own: `ai_docs/reports/<today>-pa8-resign.md`.
  - do NOT touch: anything else.

DONE WHEN: the report exists with the per-row table, the ledger-recording check, and a one-line verdict `PA8: SIGNABLE` or `PA8: NOT SIGNABLE (<ids>)`; `ruff format --check` clean on the report; `horch done` with the verdict and the report path.

REPORT: `horch note` per section; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a missing input.
