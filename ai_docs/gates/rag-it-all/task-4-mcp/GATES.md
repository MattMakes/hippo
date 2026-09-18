# Gates: RAG Task 4 MCP transport subtask

OWNS: src/hippo/mcp_server.py, src/hippo/web/app.py, src/hippo/web/auth.py, tests/unit/test_mcp_http.py, tests/unit/test_web_auth.py

Scope: Task 4 step 5 only. Membership, managed graph projection, replay and aggregate authorization remain separate pending work.

- [x] G4M: HTTP MCP cannot inherit stdio/environment credentials; actual closed-installation HTTP clients without credentials are denied, conflicting ambient credentials cannot elevate a caller, and stdio token authentication remains supported.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_mcp_http.py tests/unit/test_web_auth.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=_PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]] | -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html

- [x] G4MR: Independent specification and quality review verify explicit transport separation at all server construction and caller resolution paths.
  EVIDENCE: Independent specification and quality re-review PASS after intermittent-outage correction and actual standalone HTTP tests. Reviewer reran 11 focused checks; root ran all 38 MCP/web-auth tests. All nine tools bind explicit transport; normal HTTP/SSE/stdio serving entrypoints enforce it. Full Task 4 remains pending.
