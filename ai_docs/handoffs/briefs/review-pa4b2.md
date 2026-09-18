# Brief: independent SPEC/QUALITY review of activation Task 4b-ii (web surfaces, status rendering)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`); the work is merged at HEAD (merge commit "Merge wp/pa4b2", branch commits `27cc4c2`, `1772e0c`, `c4da3a1`, `d338c0f` on top of `ffd2265`). You read and run; you do not edit source or tests.

GOAL: Independent SPEC and QUALITY verdict on Task 4b-ii before publication.

CONTEXT:
- Plan `ai_docs/plans/rag-it-all-task-5-production-activation.md`: "Production query-session activation", "Safe transport failures", invariants 4 and 5, the adversarial cases about mixed-profile corpora and blocked Ollama endpoints. Gates PA6, PA7 in the shared ledger.
- Orchestrator brief: `ai_docs/handoffs/briefs/pa4b2-web-surfaces-and-status.md`; cross-part contracts in `ai_docs/handoffs/briefs/task4-notes.md` ("Task 4 cross-part contracts"). Implementer evidence with twelve decisions: `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4b2.md`; audit rows in `session-audit.md`.
- Orchestrator rulings (not deviations): dense dispatch only where a model is actually called (light-up and simulate); the analyze GET pages stay structural owners, pinned by a model-offline test; JSON failure shape `{error, code}` at the mapper's status via `render.public_failure_response`; managed row `error` rendered through `public_failure_for_code` with the `OPERATION_FAILED` fallback; `test_dense_session.py:596` and `test_web_code_pages*.py` owned by this slice; the Group B stub on `ask._dispatch`.
- Diff: `git diff ffd2265..d338c0f -- src/ tests/`.

FILES:
  - own: `ai_docs/reports/2026-09-11-pa4b2-review.md`.
  - do NOT touch: anything else (Task 3b, 4b-i, 4c, 4d and 5A part 2 are live in worktrees).

STEPS:
1. Run, each to `/tmp/hippo-pa4b2-review-<n>.log` with `echo EXIT $?`: (a) `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_web_surfaces.py tests/unit/test_status_access.py tests/unit/test_graph_surface_access.py tests/unit/test_web_analyze.py tests/unit/test_web_code.py tests/unit/test_web_code_pages.py tests/unit/test_web_code_pages_2.py tests/unit/test_answer_original_citations.py tests/unit/test_query_authorization_boundary.py tests/unit/test_dense_session.py tests/unit/test_managed_route_activation.py tests/unit/test_managed_source_inventory.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` (correct any name that does not exist and say so); (b) `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_web_surfaces.py tests/unit/test_status_access.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`.
2. SPEC review; PROVEN (test) / UNTESTED / VIOLATED (file:line): (a) light-up and simulate hold one structural owner and dispatch through `retrieval_session` with exactly one acquisition/heartbeat/finalizer per response; (b) every other route in the five files holds a structural `query_session` through DTO/render with no preflight-close-reacquire, and works with `/api/show`, embed and chat blocked; (c) mixed-profile corpora fail before model text with `retrieval_rebuild_required`; empty corpora make no model call; hidden wrong-profile evidence does not affect routing; (d) JSON failures are `{error, code}` at the mapper's status, no fixed 502, no exception text; the HTML analyze submit no longer renders `str(exc)`; (e) managed Source rows render the classified code's public message and never the stored sentence; the withheld branch from Task 2 is intact; (f) revocation between DTO construction and response yields the existing 409; (g) `canonical_selected_generations`' bare `ValueError` cannot escape a route unmapped; (h) the four breakage rows (B, C, D and `test_dense_session.py:596`) are fixed with their meaning preserved.
3. QUALITY review, with attention to: the two-audience `graph_page` preview branch (decision 3: body is the previewed tier, header is the actor; is any evidence from the previewed tier reachable by the actor's header or vice versa?); the verified-lane web cases being direct route calls with an internal principal (decision 6) rather than HTTP, and whether that leaves an HTTP-level auth gap untested; the `AuthorizationChanged` build-failure row reading as `operation_failed` (decision 5); `light_up` pre-validation duplicating the session's validation (drift risk); `retrieval_failure` swallowing anything it should not (enumerate the exception types it maps to `OPERATION_FAILED` and check none is an authorization type).
4. Report the verbatim signatures of `public_failure_response`, `retrieval_failure` and any changed route signature for Task 4b-i's merge.

DONE WHEN: `ai_docs/reports/2026-09-11-pa4b2-review.md` exists with `SPEC: PASS|FAIL`, `QUALITY: PASS|FAIL`, the a–h table, numbered findings with severity, file:line, why, proposed fix, run results with log paths, and the signatures. `horch done` states both verdicts, finding counts by severity, and the report path.

CONSTRAINTS: no edits outside your report; no Neo4j; `HIPPO_TEST_STORE` explicit on every command.

REPORT: `horch note` after the runs, after the SPEC table, after the report.
