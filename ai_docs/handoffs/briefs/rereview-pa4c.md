# Brief: re-review the Task 4c follow-up (MCP, CLI, remote client)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`); the fixes are merged at HEAD `c9404ed` (branch commits `f5c3777`, `39a3ba1`, `3dc4c39`, `11e0859`, `01d11c3`, `2770e9a` on top of `be6062a`). You read and run; you do not edit source or tests.

GOAL: Confirm that findings F1–F9 of `ai_docs/reports/2026-09-11-pa4c-review.md` are resolved per the orchestrator's decisions in `ai_docs/handoffs/briefs/fix-pa4c.md`, and that the closed public-code table is correct.

CONTEXT: implementer evidence `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4cfix.md`; contracts in `ai_docs/handoffs/briefs/task4-notes.md` (denial sentence and code on all three transports; remote-client 4xx `detail` rule; codes round-trip to messages, never statuses). Task 4b-i is merged, so `/api/ask` and `/api/search` now answer `{error, code}`; verify the remote client against the real bodies.

FILES:
  - own: `ai_docs/reports/2026-09-11-pa4c-rereview.md`.
  - do NOT touch: anything else.

STEPS:
1. Run, each to `/tmp/hippo-pa4c-rereview-<n>.log` with `echo EXIT $?`: (a) `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_transport_activation.py tests/unit/test_mcp_server.py tests/unit/test_mcp_http.py tests/unit/test_cli.py tests/unit/test_public_errors.py tests/unit/test_lookup_snapshot_lifetime.py tests/unit/test_graph_surface_access.py tests/unit/test_managed_route_activation.py tests/unit/test_managed_web_ingress.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`; (b) `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_cli.py -q -o addopts='' -W error` (bare); (c) `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_transport_activation.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`.
2. For each of F1–F9 plus the three addenda: CORRECT / INCOMPLETE / WRONG with file:line and the test that proves it. Specifically re-probe: (a) every MCP code tool path (acquisition failure, denial before build, denial outranking a mapped build failure, ambiguity keeping candidates) yields `ToolError` with the closed code or the denial sentence, never `Error executing tool`; (b) a low-rank reader's gated `hippo index` produces a source restricted to their tier and manageable by them, for both a file and a repository URL; (c) `cmd_index` and `_index_remotely` never print a legacy-lane stored error containing a path or source text; (d) the remote client prints 4xx `detail`, and the fixed sentence plus status for every 5xx and unparseable body, against a real `/api/ask` 500 from the merged server; (e) the denial reads `authorization_changed: Permissions changed; repeat the query` on MCP, CLI and remote, and the web 409 body carries the same sentence and code; (f) the exact-type `ValueError` rule is identical on MCP and CLI; (g) `public_failure_for_code` round-trips every code to its message and the 413/400 collision is pinned by name; (h) the `hippo --help` import footprint regression the implementer caught (per-call import) holds.
3. Write the report: `RE-REVIEW: PASS|FAIL`, the table, any new findings with severity and proposed fix, run results with log paths.

DONE WHEN: the report exists; `horch done` states the verdict, any new findings by severity, and the report path.

CONSTRAINTS: no edits outside your report; no Neo4j (the orchestrator holds the container); `HIPPO_TEST_STORE` explicit on every command.

REPORT: `horch note` after the runs and after the report.
