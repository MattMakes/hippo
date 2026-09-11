# Gates: RAG Task 5 syntax reuse

This increment covers reusable syntax facts in Task 5 step 3. Embedding reuse, staged indexing and publication are separate increments.

OWNS: src/hippo/codegraph/syntax_cache.py, src/hippo/codegraph/extract.py, tests/unit/test_syntax_cache.py

- [x] G5SC: Unchanged syntax can be cached across generations and logical sources without retaining native IDs, mutable references or resolved cross-file edges; every extraction reruns resolution against current source configuration.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_syntax_cache.py tests/unit/test_generation_namespace.py -q
  EXPECT: [100%]
  EVIDENCE: Root independent combined cache/namespace/extraction/history/chunker suite passed 357 tests, /tmp/hippo-rag-task5-cache-root.log. Runtime walker replacement and parser unavailability have RED-to-GREEN regressions; cache never parses on hits and still reruns source resolution.

- [x] G5SCR: Independent specification and quality review verifies cache integrity, compatibility and rematerialization boundaries.
  EVIDENCE: adaptive_graph_papers independent SPEC PASS and QUALITY PASS after both runtime invalidation findings were fixed; 42 focused tests plus adversarial probes passed. Ruff lint and format passed.
