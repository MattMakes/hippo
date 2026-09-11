# Gates: Task 5 saved snapshot retention

OWNS: src/hippo/knowledge/saved_snapshots.py, src/hippo/hipporag/retriever.py, src/hippo/ask.py, src/hippo/knowledge/replay.py, tests/unit/test_saved_snapshot_retention.py

- [x] G5SS: Saving an evaluation atomically retains its live selected snapshots; failed persistence rolls back references and deletion releases only the owning results' references.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_saved_snapshot_retention.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=............                                                             [100%] | 12 passed in 0.57s

- [x] G5SC: Trace snapshot IDs round-trip with legacy compatibility and reconstruction uses the current graph's identity; a closed or mismatched session cannot authorize a save.
  EVIDENCE: Root's nine initial saved-retention tests passed on Fake; final suite adds three stale generated-owner deletion regressions. Independent rag_generation_loader review SPEC/QUALITY PASS, 99 combined Fake tests passed and separate denial/targeted-release adversarial checks passed. Snapshot IDs are interpreted only with a live session and current permission proof.

- [x] G5SI: Evaluation runner persistence and deletion use these helpers, with real Ladybug/Neo4j retention and rollback checks and independent review.
  EVIDENCE: Root Ladybug evaluation/retention regression passed 58 tests (/tmp/hippo-task5-eval-saved-ladybug.log), followed by 3 final stale generated-owner deletion tests (/tmp/hippo-saved-deletion-ladybug.log). Root isolated Neo4j counts/evaluation/retention suite passed 24 tests, then 3 final stale-deletion regressions, all exit 0 (/tmp/hippo-task5-counts-saved-neo4j.log and /tmp/hippo-saved-deletion-final-neo4j.log). Independent rag_generation_loader SPEC PASS / QUALITY PASS after reproducing and verifying the deletion fix; 99 combined Fake tests and additional wrong-owner/source-revocation/targeted-release checks passed. Saved reads remain current-authorized reconstruction; historical query selection belongs to Task 5A.
