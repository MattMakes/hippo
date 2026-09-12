# Task 5 source presentation and inventory lifetimes

Scope: source read pages/helpers, source lists, standalone status and MCP inventory, graph landing page. Mutation authorization and connector lifecycle remain separate work. A preview graph page may use two explicitly different audiences; it never borrows the preview graph as the actor's header status.

- [x] S1: Source pages and inventories keep a single snapshot through materialization, release on errors, and handle reconnect without an unowned graph.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_source_snapshot_lifetime.py tests/unit/test_inventory_snapshot_lifetime.py -o addopts='' -q
  EXPECT: 19 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...................                                                      [100%] | 19 passed in 0.98s

- [x] S2: Source response ownership works on isolated Ladybug.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_source_snapshot_lifetime.py tests/unit/test_inventory_snapshot_lifetime.py -o addopts='' -q
  EXPECT: 19 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...................                                                      [100%] | 19 passed in 30.63s

- [x] S3: Existing source/code/status/auth and transport behavior remains compatible.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_status_access.py tests/unit/test_web_code_pages.py tests/unit/test_web_code_pages_2.py tests/unit/test_web_base.py tests/unit/test_mcp_server.py tests/unit/test_graph_surface_access.py tests/unit/test_render_authorization.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 140 passed, 1 warning in 19.55s

- [x] S4: Owned files pass lint and formatting.
  CHECK: .venv/bin/ruff check src/hippo/status.py src/hippo/mcp_server.py src/hippo/web/routes/graph.py src/hippo/web/routes/sources.py tests/unit/test_status_access.py tests/unit/test_source_snapshot_lifetime.py tests/unit/test_inventory_snapshot_lifetime.py && .venv/bin/ruff format --check src/hippo/status.py src/hippo/mcp_server.py src/hippo/web/routes/graph.py src/hippo/web/routes/sources.py tests/unit/test_status_access.py tests/unit/test_source_snapshot_lifetime.py tests/unit/test_inventory_snapshot_lifetime.py
  EXPECT: All checks passed!
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 7 files already formatted

RED: source10 failures and inventory4 failures before conversion. Independent review found library reconnect could acquire an unowned view when a second ping became healthy; source/graph inventory now depends on whether a session was actually acquired, with two reconnect regressions. Independent adaptive SPEC/QUALITY PASS with98Fake regressions plus preview isolation probe. Durable preview success/error/revocation tests now cover two separately owned audience views and close both. Root earlier16Neo passed; final preview cases verified separately.
