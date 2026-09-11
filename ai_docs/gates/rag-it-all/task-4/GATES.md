# Gates: RAG Task 4

The completed task-4-foundation and task-4-mcp ledgers cover policy persistence, membership, revocation and credential separation. This ledger verifies their reader integration.

OWNS: src/hippo/knowledge/{projection,query_access,replay,eval_access,changeset_access}.py, src/hippo/context.py, src/hippo/ask.py, src/hippo/status.py, src/hippo/mcp_server.py, src/hippo/hipporag/{graph_index,retriever}.py, src/hippo/evals/{runner,question_maker}.py, src/hippo/analysis/{simulate,changesets}.py, src/hippo/web/{adhoc,app,auth,render}.py, src/hippo/web/routes/{analyze,api,code,evals,graph,pages,sources,users}.py, tests/unit/test_{evidence_projection,evidence_context,query_authorization_boundary,rag_replay_access,eval_access,changeset_access,status_access,graph_surface_access,render_authorization,access,graph_index,evals_runner,settings_and_safety,web_analyze,web_auth}.py

- [x] G4A: Managed access requires live reviewed membership, fresh scoped upstream policy, complete support groups and current endpoint observations; mutations atomically invalidate old authorization.
  EVIDENCE: Completed task-4-foundation/GATES.md, including actual Ladybug and Neo4j migration, rollback, concurrency and complete support-group checks. Reader integration does not weaken that policy engine.

- [x] G4R: Managed projections, scoped graphs, saved results, model dispatch, code paths and aggregate metadata use current evidence permissions; private-only content cannot alter visible labels or graph versions.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_evidence_projection.py tests/unit/test_evidence_context.py tests/unit/test_query_authorization_boundary.py tests/unit/test_rag_replay_access.py tests/unit/test_eval_access.py tests/unit/test_changeset_access.py tests/unit/test_status_access.py tests/unit/test_graph_surface_access.py tests/unit/test_render_authorization.py tests/unit/test_access.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=_PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]] | -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html

- [x] G4L: Ladybug persists the same reader authorization and owner metadata and rejects revoked model/replay output.
  EVIDENCE: Root final reader suite (the full G4R set plus settings/safety) passed on Ladybug, exit0 /tmp/hippo-rag-task4-reader-final-ladybug.log. Real HTTP MCP and final replay/render/changeset deltas passed39cases, exit0 /tmp/hippo-rag-task4-live-and-deltas-ladybug.log. Independent runner suite73Ladybug cases passed after the original-question dispatch fix.

- [x] G4N: Disposable Neo4j passes projection, publication-to-query, owner metadata, graph/source/eval surfaces and saved-input model dispatch checks.
  EVIDENCE: Root serial Neo4j checks passed: projection/context/query/replay in /tmp/hippo-rag-task4-reader-neo4j.log (the three JSON-owner failures were corrected and reverified in /tmp/hippo-rag-changeset-neo4j-green.log); final source/eval/graph surfaces /tmp/hippo-rag-task4-surfaces-neo4j.log; final rendering/ownership/replay deltas /tmp/hippo-rag-task4-final-deltas-neo4j.log; saved-question dispatch /tmp/hippo-rag-task4-runner-neo4j.log;91final scoped/privacy/index cases /tmp/hippo-rag-task4-scoped-serial-neo4j.log, all final runs exit0. Two accidentally overlapping disposable DB runs were discarded and replaced by the final serial run; no application database was touched.

- [x] G4M: Real HTTP MCP never inherits process credentials; stdio credentials remain explicit and supported.
  EVIDENCE: Completed task-4-mcp/GATES.md; root reran all19 actual-client/transport tests after reader integration, exit0 /tmp/hippo-rag-task4-mcp-live.log. Socket tests ran with authorized loopback access.

- [x] G4C: Legacy behavior and formatting checks pass alongside the new authorization tests.
  EVIDENCE: Root final fullFake unit suite excluding19realHTTP MCP tests passed, exit0 /tmp/hippo-rag-task4-full-fake-reviewed.log; MCP19passed separately with authorized sockets. FullLadybug run completed with only8sandbox socket failures and a preloaded obsolete reindex assertion; all were resolved by39realHTTP/final delta checks and206current reader/settings checks, both exit0. Independent73Ladybug runner/ask/simulation and91Fake scoped/index cases passed after the final fixes. Ruff check and format --check pass across189files; git diff --check passes. Published foundation CI had only the inherited Neo4j unordered-edge assertion failure, now corrected and verified on realNeo4j.

- [x] G4S: Independent specification and quality reviews pass for all Task 4 integration slices and their final fixes.
  EVIDENCE: Independent specification/quality PASS from rag_contract_design for projection and graph/code transports; rag_task2 for EvalAccess, changesets and reader view version; adaptive_graph_papers for context/query/replay/status/source/auth integration. Root independently reviewed the agents' renderer, runner callback, orphan-node/fact, scoped degree and unsupported-edge fixes and verified their actual RED-to-GREEN regressions. No outstanding review blockers. Isolated port8011 server was backed up, restarted and passed authenticated/unauthenticated readiness smoke; this smoke does not claim retrieval/model-generation coverage.
