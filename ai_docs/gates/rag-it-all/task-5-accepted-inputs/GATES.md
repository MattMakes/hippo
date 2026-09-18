# Accepted raw input capture gates

Scope: explicit text bytes and individual local files only; no source mutation, production dispatch, repository/archive ingestion, model calls, or raw-object collection. Directory trust and file metadata checks do not attest immutable history.

Root independent final SPEC/QUALITY PASS after distinguishing source read failures from raw-storage failures. Root reverified all three gates; the complete capture/raw-object suite passes 97 tests with warnings treated as errors.

- [x] A1: Accepted inventory and manifest identity are immutable, canonical, source scoped, and independent of raw root and physical input paths.
  CHECK: .venv/bin/pytest tests/unit/test_accepted_inputs.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...................................................                      [100%] | 51 passed in 0.08s

- [x] A2: Exact bytes, size/count/configuration bounds, exclusions, file safety, failures and cancellation preserve the complete-or-fail capture contract.
  CHECK: .venv/bin/pytest tests/unit/test_accepted_inputs.py tests/unit/test_raw_artifacts.py -o addopts='' -q -W error
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.........................                                                [100%] | 97 passed in 0.12s

- [x] A3: Lint, formatting and independent review pass.
  CHECK: .venv/bin/ruff check src/hippo/ingest/accepted_inputs.py tests/unit/test_accepted_inputs.py && .venv/bin/ruff format --check src/hippo/ingest/accepted_inputs.py tests/unit/test_accepted_inputs.py
  EXPECT: 2 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 2 files already formatted
