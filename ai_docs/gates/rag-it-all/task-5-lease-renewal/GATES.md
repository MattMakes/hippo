# Task 5 renewal during outstanding model calls

Design: ai_docs/plans/rag-it-all-task-5-lease-renewal.md. QuerySession owns and joins one worker for durable references; legacy sessions start none. Build coordinator wiring remains pending.

- [x] H1: Renewal continues while a model request crosses original lease expiry; failure/startup/close behavior preserves ownership and denies unusable results.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_lease_heartbeat.py -o addopts='' -q -W error
  EXPECT: 12 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=............                                                             [100%] | 12 passed in 0.09s
  RED: /tmp/hippo-lease-heartbeat-red.log (missing worker and no background renewal); /tmp/hippo-heartbeat-start-red.log (partial startup returned from close before active renewal finished).

- [x] H2: Managed model-call and cleanup cases pass against isolated Ladybug.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_lease_heartbeat.py -o addopts='' -q -W error
  EXPECT: 12 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=............                                                             [100%] | 12 passed in 5.12s

- [x] H3: Query, analysis and saved evaluation lifetime behavior remains intact.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_query_session.py tests/unit/test_query_snapshots.py tests/unit/test_analysis_snapshot_lifetime.py tests/unit/test_eval_snapshot_lifetime.py tests/unit/test_saved_snapshot_retention.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.....                                                                    [100%] | 77 passed in 1.96s

- [x] H4: Owned implementation and test formatting/lint pass.
  CHECK: .venv/bin/python -m ruff check src/hippo/knowledge/lease_heartbeat.py src/hippo/knowledge/query_access.py src/hippo/context.py tests/unit/test_lease_heartbeat.py && .venv/bin/python -m ruff format --check src/hippo/knowledge/lease_heartbeat.py src/hippo/knowledge/query_access.py src/hippo/context.py tests/unit/test_lease_heartbeat.py
  EXPECT: All checks passed!
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 4 files already formatted

## Independent review

adaptive_graph_papers found the partial-start ownership race and verified the fix: record ownership before start, stop on startup error, join any started worker. Eight pure worker cases passed after the fix; earlier Ladybug11 passed before that narrow delta. Root final managed reverify after projection stabilization passed all4gates:12Fake,12Ladybug with warnings as errors,77query/eval/analysis regressions. No worker performs model/network requests. A delayed not-yet-started worker observes stop before any renewal callback; a running callback completes before snapshot release.
