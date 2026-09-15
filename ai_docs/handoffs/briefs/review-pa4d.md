# Brief: independent SPEC/QUALITY review of activation Task 4d (evaluation, analysis, changeset owners)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`); the work is merged at HEAD (merge commit "Merge wp/pa4d", branch commits `3f36d1c`, `267f3af`, `d9d3d24`, `929862b`, `1181c9d` on top of `da51784`). You read and run; you do not edit source or tests.

GOAL: Independent SPEC and QUALITY verdict on Task 4d before publication.

CONTEXT:
- Plan `ai_docs/plans/rag-it-all-task-5-production-activation.md`: "Production query-session activation" (analysis simulation, evaluation runner and the static RAG-all evaluator are model/dense owners; changeset/eval access and question-maker passage reads are graph-only owners), invariants 4 and 5. Gates PA6, PA7.
- Orchestrator brief: `ai_docs/handoffs/briefs/pa4d-evals-and-analysis.md`; contracts in `ai_docs/handoffs/briefs/task4-notes.md`. Implementer evidence: `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4d.md` (decisions section and the two open findings). Audit rows in `session-audit.md` tagged 4d.
- Implementer decisions to judge (not orchestrator rulings): dispatch lives in `run_question`, not `_run_all`, so an unroutable corpus stays per-question trouble; the slice imports the private `ask._dispatch` rather than duplicating the own/wrap/pass-through rule; empty corpora dispatch more than once because `ask` re-wraps a legacy session as a no-op; `compare_with_baseline` keeps nested owners because baseline settings differ; `changeset_access.py:170` keeps an unrestricted `ctx.graph()` read inside the mutation scope that never reaches a response body; the question-maker test generates over a fact-free corpus to sidestep the Ladybug fact-ordering defect (being fixed separately on `wp/factorder`).
- Diff: `git diff da51784..1181c9d -- src/ tests/`.

FILES:
  - own: `ai_docs/reports/2026-09-11-pa4d-review.md`.
  - do NOT touch: anything else.

STEPS:
1. Run, each to `/tmp/hippo-pa4d-review-<n>.log` with `echo EXIT $?`: (a) `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_eval_activation.py tests/unit/test_analysis_simulate.py tests/unit/test_analysis_snapshot_lifetime.py tests/unit/test_analysis_changesets.py tests/unit/test_evals_runner.py tests/unit/test_eval_access.py tests/unit/test_evals_question_maker.py tests/unit/test_rag_replay_access.py tests/unit/test_rag_eval.py tests/unit/test_rag_eval_session.py tests/unit/test_web_analyze.py tests/unit/test_managed_route_activation.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`; (b) `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_eval_activation.py tests/unit/test_analysis_snapshot_lifetime.py tests/unit/test_eval_access.py -q -o addopts='' -W error`.
2. SPEC review; PROVEN (test) / UNTESTED / VIOLATED (file:line): (a) simulation, runner and static evaluator dispatch through `retrieval_session` (or wrap the borrowed structural session) with exactly one acquisition/heartbeat/finalizer per operation and no reacquire when a session is supplied; captured settings, saved baseline settings and explicit overrides preserved; (b) `EvalAccess`, `ChangesetAccess`, question-maker reads hold a structural `query_session` through DTO/save; `ChangesetAccess` mutations keep acquire-before-transaction / close-after; (c) mixed-profile fails before model text with `retrieval_rebuild_required`; empty corpora make no model call; hidden wrong-profile evidence does not affect routing; revocation between acquisition and output denies; (d) saved results retain snapshot references; question-generation model inputs use originals; (e) breakage rows A, B and D fixed with meaning preserved; the AnyIO markers only where the import is function-level.
3. QUALITY review, with attention to: the private `ask._dispatch` import (coupling; propose the public name); the `changeset_access.py:170` unrestricted read (prove it cannot influence a response or a saved record); the "empty corpora dispatch more than once" claim (is a second dispatch ever a second acquisition?); whether per-question containment in `run_question` can mark a run `done` with errors and no public reason (the implementer's open finding 2: is that a leak, a gap, or acceptable for this increment?); whether the fact-free question-maker test hides any assertion that a fact-bearing corpus would need once `wp/factorder` lands.
4. Report the verbatim signatures of any changed public function in `runner.py`, `simulate.py`, `rag_all.py`.

DONE WHEN: `ai_docs/reports/2026-09-11-pa4d-review.md` exists with `SPEC: PASS|FAIL`, `QUALITY: PASS|FAIL`, the a–e table, numbered findings with severity, file:line, why, proposed fix, run results with log paths, and the signatures. `horch done` states both verdicts, finding counts by severity, and the report path.

CONSTRAINTS: no edits outside your report; no Neo4j; `HIPPO_TEST_STORE` explicit on every command.

REPORT: `horch note` after the runs, after the SPEC table, after the report.
