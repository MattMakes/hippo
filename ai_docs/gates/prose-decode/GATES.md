# Gates: exact-content prose decoding

OWNS: src/hippo/store/knowledge.py, tests/unit/test_prose_decode_cache.py

Scope: Reduce repeated parsing while retaining fresh storage reads and strict evidence validation.

- [x] G1: Exact-content cache preserves corruption, freshness and memory boundaries
  CHECK: .venv/bin/python -m pytest tests/unit/test_prose_decode_cache.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=e31b4788df0c/40 entries; output=...................                                                      [100%] | 19 passed in 3.23s

- [x] G2: Existing derived evidence and query snapshot regressions pass
  CHECK: .venv/bin/python -m pytest tests/unit/test_derivation_read_reuse.py tests/unit/test_derived_evidence_access.py tests/unit/test_derived_generation_store.py tests/unit/test_query_snapshots.py tests/unit/test_evidence_access.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=e31b4788df0c/40 entries; output=.............................                                            [100%] | 101 passed in 53.22s

- [x] G3: Fresh-copy Q3 replay improves time with identical answer and evidence
  EVIDENCE: Parent-confirmed replay exit 0, 120.311612s versus 298.610555s (59.71% reduction). Exact equality of full answer, ranked passages, seed entities/passages/symbols, facts, top nodes, paths/tests/history, settings, expansions, filter and evidence fingerprint. Main SQL/proofs unchanged at 230646/304. Artifact: /private/tmp/hippo-decode-measure-BPYYk2/replay-q3-escalated/results.json. Single-run timing; original deficient Q3 answer remains unchanged, so this is a performance-slice pass only.
