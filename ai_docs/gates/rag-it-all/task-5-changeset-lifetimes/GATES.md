# Changeset snapshot lifetimes

Scope: owned get/list/page views; bounded mutation scopes close after the transaction; applied responses revalidate their evidence under a fresh postcommit scope. No typed managed graph mutation is enabled.

- [x] C1: Reads, writes, rollback and postcommit response checks release every generation reference.
  CHECK: env HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_changeset_snapshot_lifetime.py tests/unit/test_changeset_access.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 19 passed, 1 warning in 1.17s

- [x] C2: The same lifetime contracts pass on real Ladybug storage.
  CHECK: env HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_changeset_snapshot_lifetime.py tests/unit/test_changeset_access.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 19 passed, 1 warning in 21.99s

- [x] C3: Existing graph editing and analysis behavior remains compatible.
  CHECK: env HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_analysis_changesets.py tests/unit/test_web_analyze.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 35 passed, 1 warning in 1.70s

- [x] C4: Changed Python code passes lint and formatting.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/changeset_access.py src/hippo/web/routes/analyze.py tests/unit/test_changeset_snapshot_lifetime.py && .venv/bin/ruff format --check src/hippo/knowledge/changeset_access.py src/hippo/web/routes/analyze.py tests/unit/test_changeset_snapshot_lifetime.py
  EXPECT: 3 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 3 files already formatted
