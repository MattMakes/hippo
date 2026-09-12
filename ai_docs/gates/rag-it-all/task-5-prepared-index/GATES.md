# Shared index preparation gates

Scope: reusable computation and the legacy adapter only. No managed production writer or input provenance materialization is claimed.

- [x] P1: Explicit-input preparation preserves model inputs, extraction gating and order, normalized payloads and detached rows.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_prepared_index.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.......                                                                  [100%] | 7 passed in 0.04s

- [x] P2: Legacy indexer output, cancellation, write diagnostics and existing-ID behavior remain compatible on Fake and Ladybug.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_prepared_index.py tests/unit/test_indexer.py tests/unit/test_openie.py -o addopts='' -q && HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_prepared_index.py tests/unit/test_indexer.py tests/unit/test_openie.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..................................................................       [100%] | 66 passed in 124.35s (0:02:04)

- [x] P3: Lint, formatting and independent review pass.
  CHECK: .venv/bin/ruff check src/hippo/hipporag/indexer.py src/hippo/hipporag/preparation.py tests/unit/test_prepared_index.py && .venv/bin/ruff format --check src/hippo/hipporag/indexer.py src/hippo/hipporag/preparation.py tests/unit/test_prepared_index.py
  EXPECT: 3 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 3 files already formatted
