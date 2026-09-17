# Gates: proof performance

OWNS: src/hippo/knowledge/derivations.py, src/hippo/knowledge/access.py, tests/unit/test_derivation_read_reuse.py

Scope: Reduce duplicate immutable lineage reads within one proof without caching authorization decisions.

- [ ] G1: Read reuse and mutation boundaries pass regression tests
  CHECK: .venv/bin/python -m pytest tests/unit/test_derivation_read_reuse.py
  EXPECT: passed
  EVIDENCE: pending

- [x] G2: Existing derived authorization and storage regressions pass
  CHECK: .venv/bin/python -m pytest tests/unit/test_derived_evidence_access.py tests/unit/test_derived_generation_store.py tests/unit/test_query_snapshots.py tests/unit/test_evidence_access.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=79d2c244a993/39 entries; output=......................                                                   [100%] | 94 passed in 47.81s

- [ ] G3: Real-data replay improves latency without evidence regression
  EVIDENCE: pending; manual because grounded answer completeness needs source-by-source review, not a substring oracle.
