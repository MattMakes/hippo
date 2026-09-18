# Dense capability and fingerprint gates

Scope: pure graph capability, immutable vector sidecar, scoping/composition/fingerprints and Retriever enforcement only. No storage marker, profile binding, context/session selection, routing or production activation. Structural composition with a populated legacy graph lacking exact vector bindings explicitly fails in this increment; step 2 must preserve heterogeneous browsing topology through its structural loading adapter.

Independent final SPEC/QUALITY PASS: 41 focused and 210 broader tests, plus separate mixed-dimension, inferred-Fact, scope, smallest-nonzero-float and model-property revocation probes. Root reverified all three gates and 59 Ladybug-selected cases. Review corrections reject zero vectors and validate authorization before reading a verified model profile property.

- [x] D1: Capability and vector records enforce strict canonical identities/dimensions, immutable finite nonzero float32 values and complete projected passage/Fact bindings.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_dense_capability.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.........................................                                [100%] | 41 passed in 0.04s

- [x] D2: Structural/verified fingerprints agree for identical evidence; scopes and compositions preserve closure and legacy/original fingerprints remain unchanged.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_dense_capability.py tests/unit/test_graph_index.py tests/unit/test_evidence_projection.py tests/unit/test_derived_projection.py tests/unit/test_rag_replay_access.py tests/unit/test_retriever.py -o addopts='' -q -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning'
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..................................................................       [100%] | 210 passed in 15.90s

- [x] D3: Lint, formatting and independent review pass.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/dense.py src/hippo/hipporag/graph_index.py src/hippo/hipporag/retriever.py src/hippo/knowledge/projection.py src/hippo/knowledge/replay.py tests/unit/test_dense_capability.py && .venv/bin/ruff format --check src/hippo/knowledge/dense.py src/hippo/hipporag/graph_index.py src/hippo/hipporag/retriever.py src/hippo/knowledge/projection.py src/hippo/knowledge/replay.py tests/unit/test_dense_capability.py
  EXPECT: 6 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 6 files already formatted
