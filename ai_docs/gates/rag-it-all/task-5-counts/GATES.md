# Gates: Task 5 generation inventory counts

Approved scope: standalone `generation_counts(store, generation_id)` with a frozen DTO carrying explicit source/generation/state and `passages`/`fact_links`. Existing source aggregate methods, the indexer's nine write diagnostics, and public SourceView remain unchanged.

Independent review: rag_generation_store reported SPEC PASS / QUALITY PASS after Fake/Ladybug checks and lock-order inspection. Root fixed the minor orphaned-source exception inconsistency with a failing regression and verified all seven cases on Fake, Ladybug and isolated Neo4j. Pipeline invocation remains part of the full Task 5 integration.

OWNS: src/hippo/store/generation_counts.py, tests/unit/test_generation_counts.py, this ledger.

- [x] G5C1: Explicit generation inventory isolates staging/retired/native rows and shared fact contributions; empty and unavailable generations remain distinguishable.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_generation_counts.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.......                                                                  [100%]

- [x] G5C2: Reads validate source ownership and sealed content, preserve epochs, and share collection exclusion on Ladybug.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_generation_counts.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.......                                                                  [100%]

- [x] G5C3: The same standalone count contract passes serially on the reserved disposable Neo4j backend.
  CHECK: HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://127.0.0.1:32774 NEO4J_USER=neo4j NEO4J_PASSWORD=hippo-disposable-test .venv/bin/python -m pytest tests/unit/test_generation_counts.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.......                                                                  [100%]

- [x] G5C4: Changed files pass Ruff lint and formatting; no existing storage file or application data was modified.
  CHECK: .venv/bin/ruff check src/hippo/store/generation_counts.py tests/unit/test_generation_counts.py
  EXPECT: All checks passed!
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed!
