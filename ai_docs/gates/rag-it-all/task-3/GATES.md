# Gates: RAG Task 3

OWNS: src/hippo/knowledge/model.py, tests/unit/test_knowledge_contracts.py, tests/unit/test_knowledge_identity.py, src/hippo/store/knowledge.py, src/hippo/store/generations.py, src/hippo/store/migrations.py, src/hippo/store/base.py, src/hippo/store/ladybug.py, src/hippo/store/__init__.py, src/hippo/store/memory.py, tests/conftest.py, tests/fakes/fake_store.py, tests/unit/test_store_knowledge.py, tests/unit/test_store_migrations.py, scripts/rag_store_capabilities.py, tests/unit/test_rag_store_capabilities.py

- [x] G3F: FakeStore enforces the new persistence, identity/reference and migration contracts, including failure paths.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_store_knowledge.py tests/unit/test_store_migrations.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; Final root expanded run: 142 collected, 137 passed and 5 genuine backend-specific skips; focused plus inherited store/code/eval/graph/row-shape modules. Exit 0; /tmp/hippo-rag-task3-fake-reviewed.log.

- [x] G3L: Real Ladybug persistence survives reopen; migrations preserve populated legacy/auth data, reject unsupported versions before mutation and roll back interrupted writes.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_store_knowledge.py tests/unit/test_store_migrations.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; Final root expanded run: 142 collected, 141 passed and 1 genuine Neo4j-only skip; focused plus inherited store/code/eval/graph/row-shape modules. Exit 0; /tmp/hippo-rag-task3-ladybug-reviewed.log.

- [x] G3N: The same contracts pass against the newly created disposable Neo4j backend, including journaled schema recovery and atomic data/publication writes.
  EVIDENCE: Root independently ran 142 collected tests on verified disposable Neo4j 5.26.30 at loopback: 140 passed, 2 Ladybug-only result-injection skips, exit 0. Includes focused persistence/migration tests and 98 inherited store/code/eval/graph/row-shape tests. /tmp/hippo-rag-task3-neo4j-reviewed.log. Every schema-step recovery, competing publication, immutable-write race and caught driver-error rollback passed.

- [x] G3C: The isolated capability probe records native search support as passed/unavailable/failed and documents the selected fallback without claiming unverified filtering or lifecycle guarantees.
  CHECK: .venv/bin/python -m pytest tests/unit/test_rag_store_capabilities.py -q && .venv/bin/python scripts/rag_store_capabilities.py --output .rag-eval/store-capabilities.json
  EXPECT: native search disabled; exit 0.
  EVIDENCE: Root independently ran 20 tests with warnings as errors and the actual CLI (exit 0); targeted Ruff lint/format pass. Independent nine-requirement specification re-review and quality review PASS. The minor test environment name was corrected to HIPPO_DB_PATH and all 20 tests rerun. Engine 0.15.3/storage 40, exact fixture/reopen/cleanup pass; native FTS/vector unavailable and dependent checks not_run. Native promotion disabled; emulated transaction diagnostic strings are not claimed as locally verified extension messages.

- [x] G3R: Independent specification and quality review validates migration, persistence, references and transaction semantics.
  EVIDENCE: Independent final source/spec and quality PASS. Reviewer reproduced and fixed statement-error poisoning and explicit empty-record namespaces; root independently reviewed fixes. Reviewer reran 12 targeted reference/namespace/membership/relocation regressions with warnings as errors. Final root backend runs remain required by G3F/G3L/G3N.
