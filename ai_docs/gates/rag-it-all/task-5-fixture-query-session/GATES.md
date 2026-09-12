# Fixture evaluator query session

Scope: the existing static legacy retrieval-only fixture harness holds the same graph through retrieval, metric calculation and candidate DTO construction. It gains no managed ingestion or temporal evaluation capabilities.

- [x] F1: Scoring and candidate assembly retain one retrieval view through success, failure and revocation, while all existing fixture outputs remain compatible.
  CHECK: env HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_rag_eval_session.py tests/unit/test_rag_eval.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...........................................................              [100%] | 59 passed in 2.74s

- [x] F2: Lint and formatting pass.
  CHECK: .venv/bin/ruff check src/hippo/evals/rag_all.py tests/unit/test_rag_eval_session.py && .venv/bin/ruff format --check src/hippo/evals/rag_all.py tests/unit/test_rag_eval_session.py
  EXPECT: 2 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 2 files already formatted
