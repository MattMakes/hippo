# Gates: Task 5 derived evidence authorization

OWNS: src/hippo/knowledge/access.py, tests/unit/test_derived_evidence_access.py

Design: ai_docs/plans/rag-it-all-task-5-derived-reader.md. Scope is exact derived inventories and all-input authorization only; projection and consumers remain pending.

- [x] G1: Complete view and prose lineage is authorized only when all original inputs, bindings and intermediate derivations remain authorized; suppression propagates through support views.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_derived_evidence_access.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=................                                                         [100%] | 16 passed in 0.51s

- [x] G2: Sealed generation selection excludes staging/unselected payloads, rejects incomplete structural closure, preserves original-only proof hashes and survives pure publication while current permission changes invalidate old proofs.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_derived_evidence_access.py tests/unit/test_evidence_access.py tests/unit/test_query_snapshots.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.............................................................            [100%] | 61 passed in 0.58s

- [x] G3: The same contracts pass against disposable Ladybug storage and owned files pass lint/format.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_derived_evidence_access.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=................                                                         [100%] | 16 passed in 22.56s

RED logs: `/tmp/hippo-derived-access-red.log` (12 failed); `/tmp/hippo-derived-access-capability-red.log` (1 failed); `/tmp/hippo-derived-access-missing-view-red.log` (2 failed); `/tmp/hippo-derived-access-missing-prose-red.log` (1 failed). Independent review is assigned by root and remains separate from these implementation checks.
