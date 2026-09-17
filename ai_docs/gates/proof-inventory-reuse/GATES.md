# Gates: proof inventory read reuse

OWNS: src/hippo/knowledge/access.py, src/hippo/knowledge/derivations.py, tests/unit/test_proof_inventory_reuse.py, tests/unit/test_derivation_read_reuse.py

- [x] G1: Shared raw proof reads remove duplicate work without weakening lineage
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_proof_inventory_reuse.py tests/unit/test_derivation_read_reuse.py -q -o addopts=''
  EXPECT: passed
  EVIDENCE: final-source parent rerun of CHECK with -W error; exit=0; 15 passed in 19.09s; /tmp/hippo-proof-inventory-parent-final-g1.log. Includes constructor-order and unknown-generation regressions added after the earlier 13-test run.

- [x] G2: Evidence, scoped reads and snapshot authorization regressions pass
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_derived_evidence_access.py tests/unit/test_derived_generation_store.py tests/unit/test_query_snapshots.py tests/unit/test_evidence_access.py tests/unit/test_generation_scoped_reads.py tests/unit/test_knowledge_scoped_reads.py -q -o addopts=''
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=e31b4788df0c/40 entries; output=...............................................ss................ss...   [100%] | 138 passed, 4 skipped in 218.56s (0:03:38)

- [x] G3: Isolated identical-corpus proof comparison preserves exact evidence and reduces time/SQL
  EVIDENCE: parent isolated driver exit 0; all eight full canonical proofs exactly equal; SQL 726 to 320; cold 0.648077s to 0.504514s; three-warm median 0.338153s to 0.201975s. Artifacts /private/tmp/hippo-proof-ab-run-74duca14; sanitized report ai_docs/reports/2026-09-16-proof-inventory-measurements.md.
