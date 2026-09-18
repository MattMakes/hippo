# Task 5 derived storage gates

Scope: schema5, typed inferred extraction, rendered native bindings and immutable closure only. Reader/projection and production pipeline integration remain pending.

- [x] D1: Frozen schema4 descriptor and old original seals survive additive schema5 upgrade; typed payload and complete immutable provenance pass focused storage tests.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_derived_generation_store.py -o addopts='' -q
  EXPECT: 33 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.................................                                        [100%] | 33 passed in 3.35s

- [x] D2: Derived closure, fencing, retention and original storage contracts agree on Ladybug.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_derived_generation_store.py tests/unit/test_generation_store.py tests/unit/test_snapshot_store.py -o addopts='' -q
  EXPECT: 75 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...                                                                      [100%] | 75 passed in 41.72s

- [x] D3: Relevant existing model/storage/migration/count/row-shape tests pass.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_derived_generation_store.py tests/unit/test_generation_store.py tests/unit/test_snapshot_store.py tests/unit/test_store_migrations.py tests/unit/test_policy_migration.py tests/unit/test_knowledge_contracts.py tests/unit/test_generation_counts.py tests/unit/test_store_row_shapes.py tests/unit/test_store_knowledge.py -o addopts='' -q
  EXPECT: 251 passed, 8 skipped
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=..............................s............                              [100%] | 251 passed, 8 skipped in 8.78s

- [x] D4: Persistence contract passes reserved serial disposable Neo4j.
  CHECK: HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://127.0.0.1:32774 NEO4J_USER=neo4j NEO4J_PASSWORD=hippo-disposable-test .venv/bin/pytest tests/unit/test_derived_generation_store.py -o addopts='' -q
  EXPECT: 33 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.................................                                        [100%] | 33 passed in 71.94s (0:01:11)

- [x] D5: Changed code passes lint and formatting.
  CHECK: .venv/bin/ruff check src/hippo/knowledge/model.py src/hippo/knowledge/lifecycle.py src/hippo/knowledge/derivations.py src/hippo/store/migrations.py src/hippo/store/knowledge.py src/hippo/store/generations.py src/hippo/store/authorization.py src/hippo/store/memory.py src/hippo/store/ladybug.py tests/fakes/fake_store.py tests/unit/test_derived_generation_store.py tests/unit/test_generation_store.py tests/unit/test_store_migrations.py tests/unit/test_policy_migration.py && .venv/bin/ruff format --check src/hippo/knowledge/model.py src/hippo/knowledge/lifecycle.py src/hippo/knowledge/derivations.py src/hippo/store/migrations.py src/hippo/store/knowledge.py src/hippo/store/generations.py src/hippo/store/authorization.py src/hippo/store/memory.py src/hippo/store/ladybug.py tests/fakes/fake_store.py tests/unit/test_derived_generation_store.py tests/unit/test_generation_store.py tests/unit/test_store_migrations.py tests/unit/test_policy_migration.py
  EXPECT: 14 files already formatted
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 14 files already formatted

RED evidence:
- Initial 11 failures: missing schema5/model/helper, followed by Fake/Ladybug 11-pass GREEN.
- Additional RED: unnormalized phrase, foreign-generation prose exact membership and boolean payload version accepted; all fixed with typed rejection.
- Review RED: selected unbound view and orphan derivation with an unselected child could seal; generation capability could be preseeded. Controlled marker and complete-group seal checks now reject all three.

Reader/projection gates are outside this ledger. No application database or application data was used.

Independent review: SPEC PASS / QUALITY PASS after the capability fix; final independent Ladybug derived suite 33 passed.
