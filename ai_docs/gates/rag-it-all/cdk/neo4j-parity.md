# CDK Neo4j parity (root-owned)

Run by the orchestrator only, against the disposable container the orchestrator grants, never by a
worker and never against port 7687. One pytest process at a time. Each line is recorded here with
exit code, revision and test count once it has run.

- CK1: `HIPPO_TEST_STORE=neo4j .venv/bin/pytest tests/unit/test_store_migrations.py tests/unit/test_generation_store.py tests/unit/test_policy_migration.py tests/unit/test_knowledge_scoped_reads.py -q -o addopts='' -W error` — RUN 2026-09-15 by the orchestrator at `9e5b93c` (S1b merged) against `hippo-rag-test-b780ab5` (bolt 127.0.0.1:32774), one pytest process: exit 0, 114 passed, 4 skipped, log `/tmp/hippo-orch-ck1-neo4j.log`. Proves the four-step v8 journal, the `knowledge_unit_id` constraint, the three `Unit` indexes and the classification backfill on Neo4j.
- CK3: `HIPPO_TEST_STORE=neo4j .venv/bin/pytest tests/unit/test_connector_sync.py tests/unit/test_staged_records.py tests/unit/test_generation_profiles.py -q -o addopts='' -W error` — not yet run.
- CK5: `tests/unit/test_connector_local.py tests/unit/test_connector_git.py` on Neo4j — not yet run.
