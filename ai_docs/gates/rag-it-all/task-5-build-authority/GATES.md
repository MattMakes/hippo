# Prospective build authority gates

- [x] BA1: Prospective originals reuse core policy rules, with live source/actor controls and no persistent staging mutation.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_build_authority.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=............................................                             [100%] | 44 passed in 1.15s

- [x] BA2: The same read-only guard works with disposable Ladybug persistence and transaction-local checks.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_build_authority.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=............................................                             [100%] | 44 passed in 13.93s

- [x] BA3: Core evidence policy behavior remains unchanged.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_build_authority.py tests/unit/test_evidence_access.py tests/unit/test_evidence_store_access.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=....................                                                     [100%] | 92 passed in 1.30s

- [x] BA4: Lint and formatting.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/build_authority.py src/hippo/knowledge/access.py tests/unit/test_build_authority.py && .venv/bin/ruff format --check src/hippo/knowledge/build_authority.py src/hippo/knowledge/access.py tests/unit/test_build_authority.py
  EXPECT: 3 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 3 files already formatted

Implementation evidence (runnable boxes await independent root gate execution):

- RED: 38 missing-module failures, `/tmp/hippo-build-authority-red.log`.
- Additional RED: unknown source metadata change accepted, `/tmp/hippo-build-authority-cas-red.log`; binding without the required lock, `/tmp/hippo-build-authority-bind-red.log`; invalid query mode with missing workspace, `/tmp/hippo-build-authority-mode-red.log`.
- GREEN: 91 Fake authority/core access cases, `/tmp/hippo-build-authority-regressions.log`; 43 disposable Ladybug cases, `/tmp/hippo-build-authority-ladybug-final.log`; Ruff and format pass for all three Python files.
- Independent SPEC/QUALITY review and publication remain root-owned. No coordinator, heartbeat, production dispatch or store writer is implemented in this increment.
