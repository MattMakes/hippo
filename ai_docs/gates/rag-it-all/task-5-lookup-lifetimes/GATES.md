# Task 5 graph lookup and rendering lifetimes

Scope: HTTP entity/neighborhood/code lookups, MCP code tools, full graph/node detail, and standalone status rendering. Explicit query sessions own live snapshot references through response materialization; graph-only routes perform no embedding requests. Source administration pages remain a separate integration step.

- [x] L1: Lookup, graph and rendering ownership survives publication and releases on success/error; revocation wins and path settings stay captured.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_lookup_snapshot_lifetime.py tests/unit/test_graph_snapshot_lifetime.py tests/unit/test_render_snapshot_lifetime.py -o addopts='' -q
  EXPECT: 28 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=............................                                             [100%] | 28 passed in 1.06s

- [x] L2: Real Ladybug references follow the same response lifetimes.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_lookup_snapshot_lifetime.py tests/unit/test_graph_snapshot_lifetime.py tests/unit/test_render_snapshot_lifetime.py -o addopts='' -q
  EXPECT: 28 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=............................                                             [100%] | 28 passed in 29.62s

- [x] L3: Existing HTTP/MCP/code/graph/auth/render behavior stays compatible.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_web_code.py tests/unit/test_mcp_server.py tests/unit/test_web_base.py tests/unit/test_web_graph_code.py tests/unit/test_graph_surface_access.py tests/unit/test_render_authorization.py tests/unit/test_query_session.py tests/unit/test_web_auth.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 173 passed, 1 warning in 22.13s

- [x] L4: Owned files pass lint and formatting.
  CHECK: .venv/bin/ruff check src/hippo/mcp_server.py src/hippo/web/routes/api.py src/hippo/web/routes/code.py src/hippo/web/routes/graph.py src/hippo/web/render.py tests/unit/test_lookup_snapshot_lifetime.py tests/unit/test_graph_snapshot_lifetime.py tests/unit/test_render_snapshot_lifetime.py tests/unit/test_graph_surface_access.py && .venv/bin/ruff format --check src/hippo/mcp_server.py src/hippo/web/routes/api.py src/hippo/web/routes/code.py src/hippo/web/routes/graph.py src/hippo/web/render.py tests/unit/test_lookup_snapshot_lifetime.py tests/unit/test_graph_snapshot_lifetime.py tests/unit/test_render_snapshot_lifetime.py tests/unit/test_graph_surface_access.py
  EXPECT: All checks passed!
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 9 files already formatted

RED: lookup18 failing ownership/settings cases; graph7 failing release cases; render3 failing acquisition/release cases. Fixtures use an authenticated user with explicitly reviewed workspace mapping. Existing graph_for revocation mock now accepts captured settings. Independent lookup/render SPEC/QUALITY PASS (113 Fake tests); full/node extension independently SPEC/QUALITY PASS with 50 Fake regressions. Root isolated Neo4j28 tests passed; final gate ledger4/4MET.
