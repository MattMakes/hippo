# Captured OpenIE runtime gates

- [x] OR1: Captured identity, explicit completion capability, transport isolation and immutable profile.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_openie_runtime.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.........................................                                [100%] | 41 passed in 0.08s

- [x] OR2: Real preparation and legacy HTTP/profile regressions preserve request and parsing behavior; retries and revocation cannot silently change identity.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_openie_runtime.py tests/unit/test_managed_prose_preparation.py tests/unit/test_ollama.py tests/unit/test_embedding_profile.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...........................................                              [100%] | 187 passed in 0.26s

- [x] OR3: Lint and formatting pass.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/openie_runtime.py tests/unit/test_openie_runtime.py && .venv/bin/ruff format --check src/hippo/knowledge/openie_runtime.py tests/unit/test_openie_runtime.py
  EXPECT: 2 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 2 files already formatted
