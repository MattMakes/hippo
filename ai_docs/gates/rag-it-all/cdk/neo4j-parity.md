# CDK Neo4j parity (root-owned)

Run by the orchestrator only, against the disposable container the orchestrator grants, never by a
worker and never against port 7687. One pytest process at a time. Each line is recorded here with
exit code, revision and test count once it has run.

- CK1: `HIPPO_TEST_STORE=neo4j .venv/bin/pytest tests/unit/test_store_migrations.py tests/unit/test_generation_store.py tests/unit/test_policy_migration.py tests/unit/test_knowledge_scoped_reads.py -q -o addopts='' -W error` — not yet run.
- CK3: the S3 plan names the line — not yet run.
- CK5: `tests/unit/test_connector_local.py tests/unit/test_connector_git.py` on Neo4j — not yet run.
