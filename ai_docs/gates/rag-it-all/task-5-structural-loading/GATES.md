# Opt-in structural loading gates

Scope: opt-in structural graph/session loading only; production defaults and routing remain unchanged. Legacy retention means the rows accepted by the existing visible legacy eligibility algorithm, not recovery of previously discarded rows.

- [x] S1: Structural selection preserves authorized heterogeneous managed and retained legacy topology, closure and canonical vectors without model access.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_structural_loading.py -o addopts='' -q -W error
  EXPECT: 43 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...........................................                              [100%] | 43 passed in 0.42s

- [x] S2: Real embedded persistence preserves profile-group snapshot atomicity, pinning, revocation and session cleanup.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_structural_loading.py -o addopts='' -q -W error
  EXPECT: 43 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...........................................                              [100%] | 43 passed in 50.91s

- [x] S3: Existing compatibility and lifecycle behavior remains unchanged.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_dense_capability.py tests/unit/test_graph_index.py tests/unit/test_derived_projection.py tests/unit/test_evidence_context.py tests/unit/test_query_snapshots.py tests/unit/test_query_session.py -o addopts='' -q -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning'
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..........................                                               [100%] | 170 passed in 1.16s

- [x] S4: Lint, formatting and independent review pass.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/dense.py src/hippo/hipporag/graph_index.py src/hippo/knowledge/projection.py src/hippo/knowledge/snapshots.py src/hippo/knowledge/query_access.py src/hippo/knowledge/replay.py src/hippo/context.py tests/unit/test_structural_loading.py && .venv/bin/ruff format --check src/hippo/knowledge/dense.py src/hippo/hipporag/graph_index.py src/hippo/knowledge/projection.py src/hippo/knowledge/snapshots.py src/hippo/knowledge/query_access.py src/hippo/knowledge/replay.py src/hippo/context.py tests/unit/test_structural_loading.py
  EXPECT: 8 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 8 files already formatted

Typed-observation refinement: four focused RED cases reproduced omission/scoping loss before the fix (`/tmp/hippo-structural-typed-red.log`). Final 43 Fake and 43 Ladybug structural cases plus 170 compatibility cases pass; independent reviewer re-ran the original adversarial reproduction and all 43 Fake cases: SPEC PASS / QUALITY PASS. New scope/suppression cases preserve authorized original-only typed observations and never infer endpoint observations from assertion support. Final Neo4j revalidation remains root-owned; prior 38-case run predates this additive fix.
