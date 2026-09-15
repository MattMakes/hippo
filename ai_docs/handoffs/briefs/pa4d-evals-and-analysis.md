# Brief: activation Task 4d — evaluation, analysis, changeset and eval-access owners under the structural default

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa4d` (branch `wp/pa4d`, base `1acf069`, the current `rag-it-all-tibs` HEAD).

GOAL: The analysis simulation, evaluation runner, question maker, static RAG-all evaluator, `EvalAccess` and `ChangesetAccess` hold one structural owner per operation, dispatch every model or dense path through `retrieval_session` over it, and every breakage-table test in your files is green with its meaning preserved. Committed on `wp/pa4d`.

CONTEXT (read all before coding):
- Plan section "Production query-session activation" (model/dense owner list names analysis simulation, evaluation runner, the static RAG-all evaluator; graph-only owners include changeset/eval access and question-maker passage reads). Gates PA6, PA7.
- Task 4a outputs: `session-audit.md` rows tagged 4d (4 model/dense, 3 graph-only) and `evidence-pa4a.md` "Breakage for 4b/4c/4d": Group A rows for `analysis/simulate.py:149` (`test_analysis_simulate` 13, `test_analysis_snapshot_lifetime` 6, `test_rag_replay_access` 1: dense scoring off a structural graph; fix = `retrieval_session`), Group B's `test_analysis_snapshot_lifetime` dto case (falls out of the Group A fix), Group D `test_analysis_changesets::test_overrides_to_ops_are_valid_and_apply_reaches_the_graph` (compares `trace.graph_version` to a store counter that is now a view fingerprint; fix = compare two traces). `tests/unit/test_rag_replay_access.py` also needs the per-test AnyIO marker (function-level imports).
- Prior reviewed facts: analysis/simulation own or borrow one `QuerySession` through saved-result reads, retrieval, answer, explanation and materialization; the evaluation runner pins once through search/answer/grade/metrics; `EvalAccess` requires explicit graph ownership; `ChangesetAccess` intentionally bumps the authorization epoch during mutations, so naive session wrapping would reject its own writes (see `ai_docs/checkpoints/2026-09-11-execution-state.md`, the Task 5 lifetime sections). `ai_docs/handoffs/briefs/task4-notes.md`.

REQUIRED BEHAVIOR:
1. `analysis/simulate.py`, `evals/runner.py`, `evals/rag_all.py` and any other model/dense owner in your files use `retrieval_session` (or wrap the one borrowed structural `QuerySession`); the lower layer never reacquires when a session is supplied; captured settings, saved baseline settings and explicit simulation overrides stay as reviewed.
2. `EvalAccess`, `ChangesetAccess` and question-maker passage reads hold a structural `query_session` through DTO/save; `ChangesetAccess` mutations keep their acquire-before-transaction / close-after pattern.
3. Mixed-profile corpora fail before model text with `retrieval_rebuild_required`; empty corpora make no model call; hidden wrong-profile evidence does not affect routing; a revocation between acquisition and output denies.
4. Fix Groups A, B (your row) and D as the table prescribes; add the AnyIO marker to `test_rag_replay_access.py`.

FILES:
  - own: `src/hippo/analysis/simulate.py`, `src/hippo/evals/runner.py`, `src/hippo/evals/question_maker.py`, `src/hippo/evals/rag_all.py`, `src/hippo/knowledge/eval_access.py`, `src/hippo/knowledge/changeset_access.py`, `tests/unit/test_analysis_simulate.py`, `tests/unit/test_analysis_snapshot_lifetime.py`, `tests/unit/test_analysis_changesets.py`, `tests/unit/test_evals_runner.py`, `tests/unit/test_eval_access.py`, `tests/unit/test_evals_question_maker.py`, `tests/unit/test_rag_replay_access.py`, `tests/unit/test_rag_all*.py` (confirm with `ls`), NEW `tests/unit/test_managed_eval_activation.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4d.md`.
  - do NOT touch: `src/hippo/web/*`, `status.py` (4b), `mcp_server.py`, `cli.py`, `remote.py` (4c), `ask.py`, `query_access.py`, `dense_session.py`, `projection.py`, `replay.py`, `ingest/*`, `store/*`, `context.py`, the shared `GATES.md`, `docs/`, the checkpoint. If a fix seems to need `replay.py` or `ask.py`, stop and ask.

STEPS:
1. Worktree + venv (with the `mcp==2.1.1` pin). Baseline your files on clean `1acf069` with form (b) where a module-level `fastapi.testclient` importer exists; failures must match the breakage rows for your files.
2. RED `test_managed_eval_activation.py`: simulation and evaluation runs on verified managed, tag-compatible legacy, mixed-profile, empty and code-only corpora with exactly one acquisition/heartbeat/finalizer per operation; saved results retain snapshot references; revocation denies; question-maker model inputs still use originals. Save `/tmp/hippo-pa4d-red.log`.
3. Implement; fix the breakage rows.
4. GREEN Fake: all your files plus `test_managed_route_activation.py test_query_snapshots.py`; log `/tmp/hippo-pa4d-fake-green.log`. GREEN Ladybug: `test_managed_eval_activation.py test_analysis_snapshot_lifetime.py test_eval_access.py`; log `/tmp/hippo-pa4d-ladybug-green.log`.
5. Ruff; evidence (commands, results, logs, audit rows by id, breakage rows fixed); commit on `wp/pa4d` in two or three commits.

DONE WHEN: your files green on both backends with `-W error`; evidence written; commits; `horch done` lists commits, files, audit rows by id, breakage rows, counts and logs.

REPORT: `horch note` per step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for ownership or contract questions; wait.
