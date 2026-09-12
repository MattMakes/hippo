# Raw artifact primitive gates

Scope: explicit-root immutable bytes only. Root and ancestor directories must exclude untrusted local writers; inode checks detect observed substitutions but portable POSIX cannot make a conditional unlink atomic. Authorization, reachability, GC and application integration remain caller work.

- [x] R1: Content-addressed references, bounded binary I/O, verified reads and immutable publication pass structural tests.
  CHECK: .venv/bin/pytest tests/unit/test_raw_artifacts.py -o addopts='' -q
  EXPECT: 46 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..............................................                           [100%] | 46 passed in 0.06s

- [x] R2: New code and tests pass lint and formatting.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/raw_artifacts.py tests/unit/test_raw_artifacts.py && .venv/bin/ruff format --check src/hippo/knowledge/raw_artifacts.py tests/unit/test_raw_artifacts.py
  EXPECT: 2 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 2 files already formatted

- [x] R3: Independent review confirms integrity, atomic publication, symlink refusal and staging cleanup.
  CHECK: .venv/bin/pytest tests/unit/test_raw_artifacts.py -o addopts='' -q
  EXPECT: 46 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..............................................                           [100%] | 46 passed in 0.05s
