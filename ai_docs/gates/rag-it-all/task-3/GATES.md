# Gates: RAG Task 3

OWNS: src/hippo/store/knowledge.py, src/hippo/store/generations.py, src/hippo/store/migrations.py, src/hippo/store/base.py, src/hippo/store/ladybug.py, src/hippo/store/__init__.py, src/hippo/store/memory.py, tests/fakes/fake_store.py, tests/unit/test_store_knowledge.py, tests/unit/test_store_migrations.py, scripts/rag_store_capabilities.py, tests/unit/test_rag_store_capabilities.py

- [ ] G3F: FakeStore enforces the new persistence, identity/reference and migration contracts, including failure paths.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_store_knowledge.py tests/unit/test_store_migrations.py -q
  EXPECT: [100%]
  EVIDENCE: pending

- [ ] G3L: Real Ladybug persistence survives reopen; migrations preserve populated legacy/auth data, reject unsupported versions before mutation and roll back interrupted writes.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_store_knowledge.py tests/unit/test_store_migrations.py -q
  EXPECT: [100%]
  EVIDENCE: pending

- [ ] G3N: The same contracts pass against the newly created disposable Neo4j backend, including journaled schema recovery and atomic data/publication writes.
  EVIDENCE: pending; run only against a verified disposable test instance, never an existing/shared graph.

- [x] G3C: The isolated capability probe records native search support as passed/unavailable/failed and documents the selected fallback without claiming unverified filtering or lifecycle guarantees.
  CHECK: .venv/bin/python -m pytest tests/unit/test_rag_store_capabilities.py -q && .venv/bin/python scripts/rag_store_capabilities.py --output .rag-eval/store-capabilities.json
  EXPECT: native search disabled; exit 0.
  EVIDENCE: Root independently ran 20 tests with warnings as errors and the actual CLI (exit 0); targeted Ruff lint/format pass. Independent nine-requirement specification re-review and quality review PASS. The minor test environment name was corrected to HIPPO_DB_PATH and all 20 tests rerun. Engine 0.15.3/storage 40, exact fixture/reopen/cleanup pass; native FTS/vector unavailable and dependent checks not_run. Native promotion disabled; emulated transaction diagnostic strings are not claimed as locally verified extension messages.
