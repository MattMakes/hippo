# Stored embedding profile descriptors

Scope: pure validation of the closed descriptor emitted by ResolvedEmbeddingProfile. This checks internal consistency, not remote execution or authorization. Controlled generation binding and production session routing remain pending.

- [x] S1: Closed canonical descriptors reconstruct detached immutable profile/spec identities and reject inconsistent metadata without I/O.
  CHECK: .venv/bin/pytest tests/unit/test_stored_embedding_profile.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.....................                                                    [100%] | 21 passed in 0.03s

- [x] S2: Existing profile resolution, drift detection and cache contracts remain unchanged.
  CHECK: .venv/bin/pytest tests/unit/test_stored_embedding_profile.py tests/unit/test_embedding_profile.py tests/unit/test_embedding_cache.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...................................................................      [100%] | 139 passed in 0.16s

- [x] S3: Lint and formatting pass.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/embedding_profile.py tests/unit/test_stored_embedding_profile.py && .venv/bin/ruff format --check src/hippo/knowledge/embedding_profile.py tests/unit/test_stored_embedding_profile.py
  EXPECT: 2 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 2 files already formatted
