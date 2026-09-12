# Browse original citations

Scope: graph node DTO/panel and managed source passage pages expose the original evidence behind derived retrieval text. Existing session ownership and all-input authorization remain in force.

- [x] B1: Derived graph and source browsing retain exact original texts and locators.
  CHECK: env HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_browse_original_citations.py tests/unit/test_source_snapshot_lifetime.py tests/unit/test_lookup_snapshot_lifetime.py tests/unit/test_web_graph_code.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 38 passed, 1 warning in 4.39s

- [x] B2: The citation rendering contract works with Ladybug storage.
  CHECK: env HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_browse_original_citations.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 2 passed, 1 warning in 0.91s

- [x] B3: Python formatting, lint and browser JavaScript syntax pass.
  CHECK: .venv/bin/ruff check src/hippo/web/routes/graph.py src/hippo/web/routes/sources.py tests/unit/test_browse_original_citations.py && .venv/bin/ruff format --check src/hippo/web/routes/graph.py src/hippo/web/routes/sources.py tests/unit/test_browse_original_citations.py && node --check src/hippo/web/static/graph.js
  EXPECT: 3 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 3 files already formatted
