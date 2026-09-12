# Controlled generation profile gates

- [x] GP1: Exact accepted-input profile binding, fences, immutability and compatibility.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_profiles.py -q -W error -o addopts=''
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.................................                                        [100%] | 33 passed in 0.95s

- [x] GP2: The same contract holds on disposable Ladybug.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_generation_profiles.py -q -W error -o addopts=''
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.................................                                        [100%] | 33 passed in 13.92s

- [x] GP3: Existing sealed generation and derived storage contracts remain compatible.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_store.py tests/unit/test_derived_generation_store.py tests/unit/test_generation_inputs.py -q -W error -o addopts=''
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=............                                                             [100%] | 84 passed in 3.55s

- [x] GP4: Lint, formatting and independent review.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/generation_profiles.py src/hippo/store/generations.py tests/unit/test_generation_profiles.py && .venv/bin/ruff format --check src/hippo/knowledge/generation_profiles.py src/hippo/store/generations.py tests/unit/test_generation_profiles.py
  EXPECT: 3 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 3 files already formatted
