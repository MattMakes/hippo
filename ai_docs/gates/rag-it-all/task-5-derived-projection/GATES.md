# Gates: Task 5 derived projection and original citations

OWNS: src/hippo/knowledge/projection.py, src/hippo/knowledge/citations.py, src/hippo/knowledge/graph_loader.py, src/hippo/knowledge/replay.py (fingerprint extension only), src/hippo/hipporag/graph_index.py (additive provenance/scoping), tests/unit/test_derived_projection.py

Scope: distinct rendered retrieval candidates, complete immutable original lineage, source-local inferred prose projection, graph copying/fingerprints and citation resolver. Root owns answer/transport consumer integration.

- [x] G1: Rendered views preserve distinct vector identities and resolve every original citation; hidden secondary inputs remove all dependent content and statistics.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_derived_projection.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..................                                                       [100%] | 18 passed in 0.21s

- [x] G2: Prose facts/entities/counts use exact source-local support; schema 4 identities/fingerprints and legacy resolver semantics remain unchanged; scopes/merges preserve frozen provenance.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_derived_projection.py tests/unit/test_evidence_projection.py tests/unit/test_generation_graph_loader.py tests/unit/test_graph_index.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...........................                                              [100%] | 99 passed in 0.37s

- [x] G3: New real-store contracts pass on disposable Ladybug and owned files pass Ruff.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_derived_projection.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..................                                                       [100%] | 18 passed in 30.65s

RED: `/tmp/hippo-derived-projection-red.log` (9 failed), `/tmp/hippo-derived-projection-binding-red.log` (2 failed). Independent adaptive_graph_papers review completed; final verdict and correction are recorded below.

Independent review found that the existing synonym finder assumes unit vectors although sealed prose only guarantees finite nonzero float32 vectors. RED: `/tmp/hippo-derived-projection-cosine-red.log` (2 failed). The projection now normalizes a temporary float64 matrix and casts to float32 only for synonym comparison; persisted vector equivalence and Fact embeddings remain exact. GREEN: `/tmp/hippo-derived-projection-cosine-green.log` (99 Fake tests passed, warnings treated as errors) and `/tmp/hippo-derived-projection-cosine-ladybug.log` (2 Ladybug cases passed). Both non-collinear scale false positives and differently scaled collinear false negatives are covered. Ruff passes. Narrow independent re-review requested.

Integration boundary: root owns answer/trace/transport consumer propagation. Pipeline must pass its captured nondefault synonymy_threshold to projection; the optional default is the existing HippoRAG 0.8. Only source-local inferred entity vectors participate in this new synonym lane; raw native code synonym vectors lack the required embedding-text binding. No production pipeline or durable reader replay migration is claimed by this slice.

Independent adaptive_graph_papers final SPEC/QUALITY PASS after synonym normalization fix. Only a temporary float64-to-float32 synonym matrix is normalized; stored payload equivalence and Fact vectors remain unchanged. Two RED regressions verify cosine behavior on non-unit vectors.
