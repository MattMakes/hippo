# Gates: proof performance

OWNS: src/hippo/knowledge/derivations.py, src/hippo/knowledge/access.py, tests/unit/test_derivation_read_reuse.py

Scope: Reduce duplicate immutable lineage reads within one proof without caching authorization decisions.

- [x] G1: Read reuse and mutation boundaries pass regression tests
  CHECK: .venv/bin/python -m pytest tests/unit/test_derivation_read_reuse.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=79d2c244a993/39 entries; output=.......                                                                  [100%] | 7 passed in 8.99s

- [x] G2: Existing derived authorization and storage regressions pass
  CHECK: .venv/bin/python -m pytest tests/unit/test_derived_evidence_access.py tests/unit/test_derived_generation_store.py tests/unit/test_query_snapshots.py tests/unit/test_evidence_access.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=79d2c244a993/39 entries; output=......................                                                   [100%] | 94 passed in 50.25s

- [x] G3: Real-data replay improves latency without evidence regression
  EVIDENCE: Q3 fresh-copy replay 415.103s -> 298.611s; main SQL 530135 -> 230646; proof builds unchanged at 304. /private/tmp/hippo-speed-round1-FfTJFE/compare.py verified exact answer/context/citations/ranked passages/seeds/paths/history/tests/evidence fingerprint equality. Q3 remains incomplete as in baseline; this gate proves no regression, not full quality. Single-run timing; baseline overlapped some pytest work. Earlier independent baseline 388.861s also remains slower than this result.
