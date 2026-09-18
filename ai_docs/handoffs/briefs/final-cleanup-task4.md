# Brief: final Task 4 cleanup batch (small items carried from every review)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `cleanup4` (branch `wp/cleanup4`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: Close every small item the Task 4 reviews left open so the activation ledger's PA8 (independent review with no unresolved findings) can be claimed honestly. Each item is one to three lines of code or one test; none changes a contract. Committed on `wp/cleanup4`.

CONTEXT: `ai_docs/handoffs/briefs/task4-notes.md` (every section) and the wrap-up review `ai_docs/reports/2026-09-12-pa4-wrapup-review.md` (its ledger pass lists the remaining `str(exc)` sites with a disposition each; follow that list exactly). Reports referenced: `2026-09-11-pa4c-rereview.md` (N1–N4), `2026-09-11-pa4b1-review.md`, `2026-09-11-pa4b2-review.md`, `evidence-pa4e.md`, `evidence-pa4cfix.md`, `evidence-pa4b1.md`.

ITEMS (do all; say per item what changed and which test proves it):
1. `str(exc)` sites under `src/hippo/web` per the wrap-up review's site table (`2026-09-12-pa4-wrapup-review.md`, the table around its lines 130–150; 33 sites): the ones marked leak or leak-class go through `render.caller_error` (exact validator types) or `render.retrieval_failure`; protected legacy validators stay with a one-line comment naming the plan sentence that protects them. The two named mediums are mandatory: `sources.py:~508` answers 400 with `str(RepoError)`, which carries an absolute server path and git's raw stderr (bound it to the class name plus a fixed sentence, matching what 4e stores on the Source row); `evals.py:~373` picks 404-versus-400 by substring on `str(exc)` and prints any `ValueError` subclass (use exact types: unknown set → 404 fixed sentence, closed validator → its text, anything else → the mapper). Then make 4e decision 1's grep true: `rg -n "str\(exc\)" src/hippo/web` lists only the protected sites, and add that as a test.
1b. `evals/question_maker.py:~183` and `:~267` log `str(OllamaError)`, which carries up to 300 characters of the model's reply; log the question id and the public code only (same rule as the runner), with a poisoned-body test.
2. `ingest/pipeline.py:~392`: raise `ReadError` (the closed validator type) instead of a bare `ValueError` so the "no readable text" sentence is kept under the closed-validator rule; adjust the one assertion if any.
3. `web/routes/analyze.py` and `web/routes/graph.py`: late-bind `retrieval_session` through the `dense_session` module (as `ask.py`, `simulate.py`, `runner.py`, `rag_all.py` now do) and collapse `test_managed_web_surfaces.watch` onto the single patch point in `test_managed_route_activation.py`.
4. The three copies of the `authorization_changed` literal (`mcp_server.py`, `cli.py`, `web/app.py`): keep `cli.py`'s own copy (it must not import knowledge at top level) but add a test that the three strings are identical.
5. From the 4c re-review: N1 fix the `public_errors.py` comment naming "the last two rows" and the test mirror count; N2 a test for `cli._index_remotely`'s stored-error print; N3 parametrize the CLI ownership test over a git URL; N4 a subprocess test asserting the `hippo --help` import footprint excludes `hippo.ingest.pipeline`, `managed_activation`, `public_errors`, fastapi and starlette (absences, not a count).
6. Documentation: `evidence-pa4cfix.md`'s "never swallowed" sentence becomes "never lost to a raw exception or masked crash, may be superseded by a denial"; `evidence-pa4b1.md:~388` line numbers corrected to `graph_index.py:297,300`; `evidence-pa4c.md` deviation 5 reworded (only the managed lane had been checked; `_stored_error` now bounds both sites).
7. `tests/unit/test_managed_eval_activation.py`: nothing further; confirm the fact-bearing corpus case runs multihop and code generation paths after the fact-order fix (it should already).

FILES:
  - own: the six web route files named in item 1 (those lines only), `src/hippo/web/render.py` (only if a helper needs a new exact type), `src/hippo/ingest/pipeline.py` (item 2 line), `src/hippo/web/routes/analyze.py`, `src/hippo/web/routes/graph.py` (item 3 import lines), `src/hippo/knowledge/public_errors.py` (comment only), `tests/unit/test_public_errors.py`, `tests/unit/test_cli.py`, `tests/unit/test_managed_transport_activation.py`, `tests/unit/test_managed_web_surfaces.py`, `tests/unit/test_managed_web_ingress.py`, `tests/unit/test_import_order.py` (N4), the three evidence files in item 6, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-cleanup4.md`.
  - do NOT touch: `store/*`, `knowledge/*` other than the one comment, `mcp_server.py`, `cli.py` source, `docs/`, the checkpoint, `GATES.md`.

STEPS: baseline the affected test files green (form (b) where needed); RED per item where a test is added; implement; GREEN Fake on all affected files plus `test_managed_route_activation.py`; Ladybug on `test_managed_web_surfaces.py test_managed_web_ingress.py`; Ruff (including the evidence markdown); evidence; commit in two or three commits.

DONE WHEN: green on both backends; evidence written; commits; `horch done` lists per item the change and test, counts and logs.

REPORT: `horch note` per item; `horch tell orchestrator "[<role>] BLOCKED: ..."` for any conflict with the review's classification.
