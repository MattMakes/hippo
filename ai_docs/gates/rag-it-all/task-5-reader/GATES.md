# Gates: RAG Task 5 pinned readers

This increment covers exact interpretation selection, generation-filtered loading and query-session pinning. The full Task 5 remains open for staged indexing, embedding-cache wiring, lifecycle dispatch and recovery startup integration.

OWNS: src/hippo/knowledge/{access,projection,snapshots,graph_loader,query_access,lifecycle}.py, src/hippo/context.py, src/hippo/ask.py, src/hippo/status.py, src/hippo/cli.py, src/hippo/mcp_server.py, src/hippo/web/render.py, src/hippo/web/routes/{api,pages,graph}.py, tests/unit/test_generation_evidence_selection.py, tests/unit/test_generation_graph_loader.py, tests/unit/test_query_snapshot_service.py, tests/unit/test_query_snapshots.py, tests/unit/test_query_session.py

- [x] G5RE: Exact spans, observations and complete support groups are selected before ACL checks; staging cannot alter a held interpretation or vector dimensions.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_generation_evidence_selection.py tests/unit/test_generation_graph_loader.py tests/unit/test_evidence_access.py tests/unit/test_evidence_projection.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=........................................................................ [ 93%] | .....                                                                    [100%]

- [x] G5RQ: One query captures its effective settings and graph through retrieval, model calls, source inventory and rendering; every session exit releases its reference.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_query_snapshot_service.py tests/unit/test_query_snapshots.py tests/unit/test_query_session.py tests/unit/test_query_authorization_boundary.py tests/unit/test_graph_surface_access.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=_PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]] | -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html

- [x] G5RB: Real LadybugDB and Neo4j integration proves retained G1 during G2 publication, reference-blocked collection, final release and immediate suppression/revocation.
  EVIDENCE: Root Ladybug integration passed 65 tests in /tmp/hippo-rag-task5-root-pins-ladybug.log; root isolated Neo4j integration passed 128 tests, exit 0, in /tmp/hippo-rag-task5-root-neo4j.log. The cases include held G1 during publication, suppression, lease collection and query-session output construction.

- [x] G5RR: Independent specification and quality review passes, including effective request settings and post-acquisition failure cleanup.
  EVIDENCE: rag_generation_loader independently reviewed the final settings and cleanup fixes: SPEC PASS / QUALITY PASS, 128 Fake tests passed. Root independently verified 84 settings/query/snapshot/session/graph-surface tests in /tmp/hippo-rag-task5-settings-root.log. New red-first regressions cover both review findings.
