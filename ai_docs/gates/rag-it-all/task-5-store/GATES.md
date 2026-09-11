# Gates: RAG Task 5 storage and retention

Governing contract: `ai_docs/plans/rag-it-all-task-5-storage.md`. This ledger covers the storage portion only; snapshot/projection/query and pipeline wiring are separately verified under full Task 5.

OWNS: src/hippo/store/{generations,snapshots,knowledge,migrations,memory,code,ladybug,authorization,__init__}.py, src/hippo/knowledge/model.py, tests/fakes/fake_store.py, tests/unit/test_generation_store.py, tests/unit/test_snapshot_store.py, tests/unit/test_store_migrations.py, tests/unit/test_knowledge_contracts.py

- [x] G5ST: Staging, sealing, fenced publication and exact evidence membership preserve active immutable generations and reject stale or suppressed builders.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_generation_store.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..................................                                       [100%]

- [x] G5SR: Durable snapshot references and collection share a transactional boundary; live or retained references preserve generation inputs and expired leases cannot resurrect.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_snapshot_store.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=........                                                                 [100%]

- [x] G5SB: Schema 4 and the shared storage contract pass on real Ladybug and disposable Neo4j, preserving the frozen schema-3 migration history.
  EVIDENCE: Root final Ladybug generation/snapshot/migration run passed 60 tests, with 3 legacy-version cases deselected (/tmp/hippo-rag-task5-storage-final-ladybug.log); the separate frozen-v3/reopen checks passed 2 tests (/tmp/hippo-rag-task5-frozen-schema-ladybug.log). Root final disposable Neo4j run passed 58 tests with 2 Ladybug-only skips and 3 legacy-version cases deselected, exit 0 (/tmp/hippo-rag-task5-storage-final-neo4j.log). Earlier complete Ladybug migration/policy suite passed 79 tests; prior root Neo4j integration passed 128 tests. Latest retention, deterministic retry, lock-read, minimum coverage and backfill regressions ran on both real backends.

- [x] G5SV: Independent specification and quality reviews pass for the storage slice and epoch classification.
  EVIDENCE: adaptive_graph_papers final SPEC PASS / QUALITY PASS for source fencing, exact membership, published immutability, retention tombstones, never-published retries, snapshot exclusion and fresh lock reads; 86 tests passed and 6 backend-specific cases skipped in /tmp/hippo-storage-latest-review.log. Root also inspected publication, snapshot and collection boundaries. Full chunk-inventory coverage remains the pipeline's responsibility.
