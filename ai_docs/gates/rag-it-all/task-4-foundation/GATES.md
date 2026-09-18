# Gates: RAG Task 4 authorization foundation

This checkpoint implements evidence authorization, durable revocation, policy scope migration and open-mode connector guards. Full Task 4 remains open for graph, replay and transport-surface integration.

OWNS: src/hippo/access.py, src/hippo/knowledge/access.py, src/hippo/knowledge/model.py, src/hippo/store/authorization.py, src/hippo/store/base.py, src/hippo/store/generations.py, src/hippo/store/knowledge.py, src/hippo/store/ladybug.py, src/hippo/store/memory.py, src/hippo/store/migrations.py, src/hippo/store/users.py, tests/conftest.py, tests/fakes/fake_store.py, tests/unit/test_evidence_access.py, tests/unit/test_evidence_epochs.py, tests/unit/test_evidence_store_access.py, tests/unit/test_policy_migration.py, tests/unit/test_store_knowledge.py, tests/unit/test_store_migrations.py

- [x] G4FA: Managed evidence requires live reviewed membership, source and upstream policy intersection, fresh scoped grants, complete AND/OR support and current revocation state.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_evidence_access.py tests/unit/test_evidence_epochs.py tests/unit/test_evidence_store_access.py tests/unit/test_policy_migration.py tests/unit/test_store_migrations.py tests/unit/test_store_knowledge.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=........................................................................ [ 52%] | ................................ss.sss...............s............       [100%]

- [x] G4FL: Ladybug authorization and migration behavior matches the shared contract.
  EVIDENCE: Root /tmp/hippo-rag-task4-foundation-ladybug-final.log exit0 (core, epochs, public reads, persistence); independent migration re-review 46 tests passed with -W error; final identity-history marker and rollback checks passed in /tmp/hippo-query-identity-ladybug.log.

- [x] G4FN: Neo4j authorization, complete migration recovery and concurrent publication/permission mutations preserve the contract.
  EVIDENCE: Root /tmp/hippo-rag-task4-foundation-neo4j-final.log exit0, 113 shared authorization/access/persistence tests; /tmp/hippo-rag-task4-marker-neo4j.log exit0, 16 final epoch/marker tests. Migration suite session75540 exit0, 44 passed/2 Ladybug-only skips, including each of 70 v2 DDL recovery checkpoints. All used owned disposable hippo-rag-test-b780ab5; no application database was reset.

- [x] G4FR: Independent specification and quality reviews pass for this foundation slice.
  EVIDENCE: rag_contract_design independently re-reviewed policy identity/migration fixes PASS; rag_task2 reviewed epoch/lock and public-read boundaries, identified membership leak then verified 8 corrected read tests; adaptive_graph_papers independently re-reviewed root public-read integration PASS. Root reviewed marker transaction/rollback and ran final Neo4j checks. Query, projection, status and replay are outside this checkpoint and remain under the full Task4 ledger.
