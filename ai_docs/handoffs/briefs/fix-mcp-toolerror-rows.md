# Brief: adapt five MCP tests to the closed ToolError contract

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`) at HEAD `a0f811f` or later. Do NOT commit; the orchestrator commits.

GOAL: Five tests that asserted raw exceptions from MCP tool paths assert the closed `ToolError` contract instead, with every release and revocation assertion kept exactly as it was.

CONTEXT:
- Task 4c (merged at `a0f811f`) made every MCP tool body map failures through `mcp_server.tool_failure`: `ToolError` passes through; `public_failure(exc)` gives `code: message`; `AuthorizationChanged` becomes the shared `mcp_server.DENIED` sentence with no code; an exact-type `ValueError` keeps its own text; anything else becomes `operation_failed: Operation failed; inspect local logs by operation ID`. Model errors (`OllamaError`, connection/timeout) map to `retrieval_unavailable: Retrieval service is unavailable`. See `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4c.md` and `src/hippo/mcp_server.py` (`tool_failure`, `DENIED`).
- The failing tests (log `/tmp/hippo-orch-full-fake-a0f811f.log`):
  - `tests/unit/test_graph_surface_access.py::test_mcp_query_rechecks_after_building_output[ask|search]` (expects `AuthorizationChanged`; now `ToolError` carrying `DENIED`)
  - `tests/unit/test_graph_surface_access.py::test_mcp_model_errors_cannot_skip_transport_revocation_checks[ask|search]` (expects the raw model error or `AuthorizationChanged`; now `ToolError` with `retrieval_unavailable` or `DENIED`, and the revocation check must still be proven to run)
  - `tests/unit/test_lookup_snapshot_lifetime.py::test_code_builder_holds_snapshot_and_captured_settings[error-mcp_path]` (expects `RuntimeError("construction failed")`; now `ToolError` with `operation_failed`)
- Precedent: 4b-i adapted the HTTP and MCP rows of `tests/unit/test_query_session.py::test_model_failure_releases_graph_and_revocation_wins` the same way (that file is NOT yours; do not touch it). The meaning of each test is what it proves about acquisition, release and revocation ordering; only the "it raises X" half changes.

FILES:
  - own: `tests/unit/test_graph_surface_access.py`, `tests/unit/test_lookup_snapshot_lifetime.py`.
  - do NOT touch: anything else, including `src/`, `tests/unit/test_query_session.py`, `mcp_server.py`.

STEPS:
1. Reproduce: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_graph_surface_access.py tests/unit/test_lookup_snapshot_lifetime.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-toolerror-red.log 2>&1; echo EXIT $?` (5 failed expected).
2. For each test: replace `pytest.raises(<raw type>)` with `pytest.raises(ToolError)` and assert the message equals `mcp_server.DENIED` (authorization) or starts with the expected closed code (`retrieval_unavailable:` for model errors, `operation_failed:` for the construction failure); assert the private text (`PRIVATE PROVIDER ERROR`, `construction failed`, `model failed`) does NOT appear in the `ToolError` message; keep every existing assertion about acquisition counts, release, snapshot validity and revocation ordering unchanged.
3. GREEN: the step-1 command, log `/tmp/hippo-toolerror-green.log`; then `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_mcp_server.py tests/unit/test_managed_transport_activation.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` must stay green.
4. Ruff check + format on the two files.

DONE WHEN: both files green; Ruff clean; `horch done` lists the five tests, what each now asserts, and the log paths. No commits.

REPORT: `horch note` after RED and after GREEN.
