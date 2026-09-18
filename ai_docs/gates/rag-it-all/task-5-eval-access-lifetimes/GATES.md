# Standalone evaluation snapshot lifetimes

Scope: owned/borrowed evaluation DTO reads, question-set creation and non-epoch question/run writes. Historical retained replay and deletion permissions remain unchanged. Root independent code review passes after the in-transaction post-write validation correction.

- [x] E1: Single reads own exactly one snapshot; creation releases outside its transaction; borrowed sessions remain owned by their caller.
  CHECK: env HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_eval_access_lifetime.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..........................                                               [100%] | 26 passed in 1.11s

- [x] E2: Real Ladybug storage preserves rollback, exact reference closure and intentionally changed ownership epochs.
  CHECK: env HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_eval_access_lifetime.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..........................                                               [100%] | 26 passed in 41.68s

- [x] E3: Existing evaluation, saved snapshots, graph edits and question generation remain compatible.
  CHECK: env HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_eval_access.py tests/unit/test_eval_snapshot_lifetime.py tests/unit/test_changeset_access.py tests/unit/test_changeset_snapshot_lifetime.py tests/unit/test_evals_question_maker.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 66 passed, 1 warning in 5.20s

- [x] E4: Changed Python passes lint and formatting.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/eval_access.py tests/unit/test_eval_access_lifetime.py tests/unit/test_eval_access.py tests/unit/test_eval_snapshot_lifetime.py && .venv/bin/ruff format --check src/hippo/knowledge/eval_access.py tests/unit/test_eval_access_lifetime.py tests/unit/test_eval_access.py tests/unit/test_eval_snapshot_lifetime.py
  EXPECT: 4 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 4 files already formatted
