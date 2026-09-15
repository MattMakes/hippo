# Brief: activation Task 4b-ii — analyze, graph, code and render routes, status rendering, and the structural-default breakage

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa4b2` (branch `wp/pa4b2`, base `1acf069`, the current `rag-it-all-tibs` HEAD).

GOAL: The analyze, graph (including light-up), code and render surfaces and `status.py` hold one structural owner per response; every model or dense path among them dispatches through `retrieval_session` over that owner; graph/source/status/code surfaces still work with Ollama offline; managed Source rows render the closed public failure code; and every breakage-table test in your files is green. Committed on `wp/pa4b2`.

CONTEXT (read all before coding):
- Plan sections: "Production query-session activation" (owner classification), "Structural source inventory" (status rendering already implemented by Task 2; you add the error code), "Safe transport failures". Gates PA6, PA7.
- Task 4a outputs: `ai_docs/gates/rag-it-all/task-5-production-activation/session-audit.md` (your rows: tagged 4b with file `web/routes/analyze.py`, `web/routes/graph.py`, `web/routes/code.py`, `web/render.py`, `status.py`) and `evidence-pa4a.md` "Breakage for 4b/4c/4d": Group A rows for `web/routes/analyze.py:270` and `web/routes/graph.py:328` (light-up scores dense candidates off a structural graph whose vectors sit in sidecars behind a zero-width matrix; fix = `retrieval_session`), Group B (`test_answer_original_citations` derived_graph fixture stubs `ctx.graph_for` with a hand-built managed graph; fix = stub `ask._dispatch` or build it with `test_structural_loading.published`), Group C (`test_status_access.py:195` asserts the old default), Group D (`test_query_authorization_boundary.py:211` expiry callback must wrap `ctx._build_structural_graph`).
- `src/hippo/knowledge/public_errors.py` (`public_failure`, `public_failure_for_code`, `OPERATION_FAILED`). Task 2's `status.source_view` and `_managed_source` (`ai_docs/reports/2026-09-11-pa2-review.md` for its signatures and minors: bare `ValueError` from `canonical_selected_generations`, inherited code-edge attribution by node membership).
- `ai_docs/handoffs/briefs/task4-notes.md`, all of it.

REQUIRED BEHAVIOR:
1. Analyze routes, graph light-up and any other model/dense owner in your files use `retrieval_session` (or wrap the borrowed structural `QuerySession`); graph browse, node detail, neighborhood, entity search, source dropdowns, code routes, render helpers and status hold a structural `query_session` through DTO/render; no preflight-close-reacquire.
2. With `/api/show`, embed and chat blocked (MockTransport returning errors), graph/source/status/code endpoints still answer; model endpoints in your files return the stable `retrieval_unavailable` failure with no private text.
3. Managed Source rows: `status._managed_source` renders `error` from `public_failure_for_code(source['error_code'])` (or however Task 3a stored it; read `managed_activation.record_build_failure`), never the raw stored message for a managed row; legacy rows unchanged. Keep the withheld-branch behavior from Task 2.
4. Fix Groups A (your two sites), B, C, D as the table prescribes; keep the meaning of each test.
5. `canonical_selected_generations`' bare `ValueError` cannot escape a route unmapped: catch it where projection errors are caught, or map it to `OPERATION_FAILED`.

FILES:
  - own: `src/hippo/web/routes/analyze.py`, `src/hippo/web/routes/graph.py`, `src/hippo/web/routes/code.py`, `src/hippo/web/render.py`, `src/hippo/status.py`, `tests/unit/test_web_analyze.py`, `tests/unit/test_web_code.py`, `tests/unit/test_graph_surface_access.py`, `tests/unit/test_status_access.py`, `tests/unit/test_query_authorization_boundary.py`, `tests/unit/test_answer_original_citations.py`, any `tests/unit/test_web_graph*.py` / `test_render*.py` (confirm names with `ls`), NEW `tests/unit/test_managed_web_surfaces.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4b2.md`.
  - do NOT touch: `src/hippo/web/app.py`, `web/auth.py`, `web/routes/{api,pages,sources,users}.py` (4b-i), `mcp_server.py`, `cli.py`, `remote.py` (4c), `analysis/*`, `evals/*`, `eval_access.py`, `changeset_access.py` (4d), `knowledge/*`, `ingest/*`, `store/*`, `context.py`, the shared `GATES.md`, `docs/`, the checkpoint. If Group D truly needs `context.py`, stop and ask.

STEPS:
1. Worktree + venv (with the `mcp==2.1.1` pin). Baseline your files on clean `1acf069` with the AnyIO form (b) ignore; the failures must match the breakage table rows for your files.
2. RED `test_managed_web_surfaces.py`: light-up and analyze on verified managed, tag-compatible legacy, mixed-profile (fails before model text with `retrieval_rebuild_required`), empty and code-only corpora with exactly one acquisition/heartbeat/finalizer per response; offline-Ollama graph/status/code success; managed row error code rendering; revocation between DTO and response. Save `/tmp/hippo-pa4b2-red.log`.
3. Implement; fix the breakage rows.
4. GREEN Fake: all your files plus `test_managed_route_activation.py test_managed_source_inventory.py` with form (b); log `/tmp/hippo-pa4b2-fake-green.log`. GREEN Ladybug: `test_managed_web_surfaces.py test_status_access.py test_graph_surface_access.py`; log `/tmp/hippo-pa4b2-ladybug-green.log`.
5. Ruff; evidence (commands, results, logs, audit rows converted by id, breakage rows fixed); commit on `wp/pa4b2` in two or three commits.

DONE WHEN: your files green on both backends with `-W error`; evidence written; commits; `horch done` lists commits, files, audit rows by id, breakage rows, counts and logs.

REPORT: `horch note` per step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for ownership or contract questions; wait.
