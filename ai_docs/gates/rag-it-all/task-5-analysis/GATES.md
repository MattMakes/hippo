# Task 5 analysis query lifetimes

Scope: simulations and stored/ad-hoc analysis routes own or borrow one QuerySession through response materialization. Saved baseline settings and explicit simulation overrides remain distinct from the snapshot's captured default settings. Production managed ingestion remains pending.

- [x] A1: Managed publication, error, borrowed ownership, baseline rebinding, route rendering and saved deletion boundaries are covered.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_analysis_snapshot_lifetime.py -o addopts='' -q
  EXPECT: 13 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.............                                                            [100%] | 13 passed in 0.59s
  RED: Four initial lifetime failures in /tmp/hippo-analysis-snapshot-red.log; five route failures in /tmp/hippo-analysis-routes-red.log; saved deletion in /tmp/hippo-analysis-deleted-red.log; final DTO deletion in /tmp/hippo-analysis-dto-red.log; stale baseline snapshot in /tmp/hippo-analysis-baseline-red.log.

- [x] A2: The same lifetime contract passes real isolated Ladybug persistence.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_analysis_snapshot_lifetime.py -o addopts='' -q
  EXPECT: 13 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.............                                                            [100%] | 13 passed in 15.44s

- [x] A3: Existing replay, simulation, HTML/code analysis and query-session behavior remains compatible.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_web_analyze.py tests/unit/test_rag_replay_access.py tests/unit/test_analysis_simulate.py tests/unit/test_web_code_pages.py tests/unit/test_query_session.py -o addopts='' -q
  EXPECT: 87 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 87 passed, 1 warning in 11.88s

- [x] A4: Owned source and tests meet repository lint and formatting checks.
  CHECK: .venv/bin/python -m ruff check src/hippo/analysis/simulate.py src/hippo/web/routes/analyze.py tests/unit/test_analysis_snapshot_lifetime.py && .venv/bin/python -m ruff format --check src/hippo/analysis/simulate.py src/hippo/web/routes/analyze.py tests/unit/test_analysis_snapshot_lifetime.py
  EXPECT: All checks passed!
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 3 files already formatted

## Independent review

SPEC PASS / QUALITY PASS from adaptive_graph_papers after fixing final DTO saved-deletion, model-error response materialization and reused-baseline snapshot issues. Baselines are copied only when snapshot IDs differ, preserving the original legacy object when unchanged. Root gate checker: 4/4 met, 13 Fake + 13 Ladybug lifetime cases and 87 compatibility cases.
