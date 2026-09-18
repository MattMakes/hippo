# Brief: late-bind the static evaluator's dense dispatch and prove its mode

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message (Task 4f is merged, so `hippo.knowledge.dense_session.retrieval_session` now owns the own/wrap/pass-through rule and `ask._dispatch` is gone). Do NOT commit; the orchestrator commits.

GOAL: `src/hippo/evals/rag_all.py` resolves `retrieval_session` at call time through the `dense_session` module (not an import-time binding), so the shared `watch()` recorder in `tests/unit/test_managed_route_activation.py` observes the static evaluator, and a test proves the mode it dispatches over a managed and a legacy corpus (the 4d review's finding 5).

CONTEXT: `ai_docs/reports/2026-09-11-pa4d-review.md` finding 5; `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4f.md` (decision 5 was handed off; read how the other three callers now call `dense_session.retrieval_session(...)`); `tests/unit/test_managed_eval_activation.py` (fixtures for managed and legacy corpora and the `watch()` usage); `tests/unit/test_rag_eval.py`, `tests/unit/test_rag_eval_session.py` (the static evaluator's existing tests; its fixture is legacy-only).

FILES:
  - own: `src/hippo/evals/rag_all.py` (the import and the one call site, ~:388), `tests/unit/test_managed_eval_activation.py` (one new test), NEW section in `evidence-pa4f.md` under "Decision 5 (completed separately)".
  - do NOT touch: anything else, including `rag_all_temporal.py`.

STEPS:
1. Baseline: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_rag_eval.py tests/unit/test_rag_eval_session.py tests/unit/test_managed_eval_activation.py -q -o addopts='' -W error > /tmp/hippo-ragall-baseline.log 2>&1; echo EXIT $?` green.
2. RED: a test in `test_managed_eval_activation.py` that runs the static evaluator over a verified managed corpus and over a legacy corpus under `watch()` and asserts the dispatched modes (`verified` and `tag_compatible`/`legacy` as the fixtures produce) with exactly one acquisition each; it must fail before the change because `watch()` cannot see the import-time binding. Save `/tmp/hippo-ragall-red.log`.
3. Change `rag_all.py` to `from ..knowledge import dense_session` and `dense_session.retrieval_session(...)` at the call site. GREEN: the baseline command, log `/tmp/hippo-ragall-green.log`. Ruff check + format on both files.
4. Append the evidence section.

DONE WHEN: RED and GREEN logs saved; Ruff clean; evidence appended; `horch done` lists the change (file:line), the test name, counts and logs. No commits.

REPORT: `horch note` after RED and after GREEN.
