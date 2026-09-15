# Brief: activation Task 4f — evaluation wrap-up (public failure reason, dispatch promotion, bounded logging)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa4f` (branch `wp/pa4f`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: An evaluation run's retrieval failure has a public reason a reader can see; the dense dispatch rule lives in one public place; the runner's logs are bounded; the question-maker activation test runs over a fact-bearing corpus. Committed on `wp/pa4f`.

CONTEXT: `ai_docs/handoffs/briefs/task4-notes.md` ("Wrap-up items from Task 4d" and the 4d review corrections), `ai_docs/reports/2026-09-11-pa4d-review.md` (findings 1, 3, 4, 5, 7), `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4d.md`, `evidence-factorder.md`.

DECISIONS (final):
1. Public failure reason (three parts): `evals/runner.py` stores `public_failure(exc).code` (or `OPERATION_FAILED.code`) in a closed field beside the private `error` on the result and the run summary; `knowledge/eval_access.py` passes that code through where it nulls `error` (~:305, ~:378); `web/routes/evals.py` adds `errors` to `SUMMARY_CARDS` and the templates (`run_body.html:42`, `eval_set.html:18`) render the code's public message through `public_failure_for_code`; the private `error` string stays nulled for readers. Tests: a run over an unroutable corpus shows `errors == N` and the `retrieval_rebuild_required` message to a reader with no private text.
2. Dispatch promotion (4d review finding 1): fold the own/wrap/pass-through rule of `ask._dispatch` into `retrieval_session` in `knowledge/dense_session.py` (public), make `ask.py`, `analysis/simulate.py` and `evals/runner.py` call it, and delete `ask._dispatch`. Audit `runner.py:106`, `rag_all.py:392-397` and `web/routes/analyze.py:319-327`, which pass access plus session: `_dispatch` silently dropped the access where `dense_session._session:178` raises `invalid_borrow`; the promoted rule must be explicit about which wins and tested.
3. Bounded logging: `runner.py:209`'s `log.exception("Question %r failed", text)` logs only the question ID and the public code, never the question text or exception text.
4. Fact-bearing corpus: restore a fact-bearing managed corpus in the question-maker case of `tests/unit/test_managed_eval_activation.py` now that fact order is canonical (`e709aad`), and assert multihop/code/commit generation paths run.
5. `rag_all.py` binds `retrieval_session` at import; make the lookup late-bound (module attribute at call time) so it can be patched, and add the dispatch-mode test the 4d review said was missing (finding 5).

FILES:
  - own: `src/hippo/evals/runner.py`, `src/hippo/evals/rag_all.py`, `src/hippo/knowledge/eval_access.py`, `src/hippo/knowledge/dense_session.py` (the promoted rule only), `src/hippo/ask.py` (delete `_dispatch`, call the public rule), `src/hippo/analysis/simulate.py` (call site only), `src/hippo/web/routes/evals.py`, `src/hippo/web/routes/analyze.py` (call site only, ~:319-327), `src/hippo/web/templates/run_body.html`, `src/hippo/web/templates/eval_set.html`, tests: `tests/unit/test_managed_eval_activation.py`, `tests/unit/test_evals_runner.py`, `tests/unit/test_eval_access.py`, `tests/unit/test_web_evals*.py` (confirm names), `tests/unit/test_ask.py`, `tests/unit/test_managed_route_activation.py`, `tests/unit/test_rag_eval.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4f.md`.
  - do NOT touch: `web/app.py`, `web/routes/{api,code,graph,pages,sources,users}.py`, `render.py` (Task 4e), `mcp_server.py`, `cli.py`, `remote.py`, `store/*`, `ingest/*`, `docs/`, the checkpoint, `GATES.md`.

STEPS: baseline green; RED per decision; implement; GREEN Fake (your files plus `test_managed_web_surfaces.py test_analysis_simulate.py test_query_session.py`), GREEN Ladybug (`test_managed_eval_activation.py test_eval_access.py`); Ruff; evidence; commit in two or three commits.

DONE WHEN: green on both backends; evidence written; commits; `horch done` lists per decision the change and test, the promoted function's signature, counts and logs.

REPORT: `horch note` per step; `horch tell orchestrator "[<role>] BLOCKED: ..."` for conflicts.
