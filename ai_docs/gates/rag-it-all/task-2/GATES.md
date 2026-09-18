# Gates: RAG Task 2

OWNS: src/hippo/knowledge/**, tests/unit/test_knowledge_identity.py, tests/unit/test_knowledge_contracts.py, pyproject.toml

Scope: additive immutable evidence, lifecycle and query contracts. Persistence, access decisions and temporal retrieval behavior belong to subsequent tasks.

- [x] G2: Canonical identities preserve namespace, dialect and path boundaries; immutable version-1 contracts reject invalid predicates, endpoints, locators, temporal selectors and wire versions.
  CHECK: .venv/bin/python -m pytest tests/unit/test_knowledge_identity.py tests/unit/test_knowledge_contracts.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=........................................................................ [ 58%] | ....................................................                     [100%]

- [x] G2R: Independent specification review covers all required section 5 records, and confirms legacy identities remain unchanged.
  EVIDENCE: /root/rag_contract_design independently verified all 12 numbered requirements and 35 persisted record types, reran 119 tests with warnings as errors, and passed additional locator/provider/temporal probes. Specification and subsequent quality review PASS after three RED-tested corrections. Legacy identity source files unchanged from 76d1448; targeted Ruff lint/format pass.
