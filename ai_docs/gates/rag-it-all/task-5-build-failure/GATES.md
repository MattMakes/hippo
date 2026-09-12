# Unpublished build failure gates

- [x] BF1: A live build ends atomically without collecting original or staged evidence; stale holders cannot affect a winner.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_failure.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.................                                                        [100%] | 17 passed in 0.07s

- [x] BF2: Disposable Ladybug verifies failure rollback and retained inventory on the real backend.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_generation_failure.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.................                                                        [100%] | 17 passed in 6.60s

- [x] BF3: Existing generation claims, strict publication, retry and collection remain valid.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_failure.py tests/unit/test_generation_store.py tests/unit/test_snapshot_store.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...........................................................              [100%] | 59 passed in 0.99s

- [x] BF4: Lint and formatting pass.
  CHECK: .venv/bin/ruff check src/hippo/store/generations.py src/hippo/store/snapshots.py tests/unit/test_generation_failure.py && .venv/bin/ruff format --check src/hippo/store/generations.py src/hippo/store/snapshots.py tests/unit/test_generation_failure.py
  EXPECT: 3 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 3 files already formatted
