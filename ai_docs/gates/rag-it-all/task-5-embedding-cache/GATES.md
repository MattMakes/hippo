# Gates: Task 5 embedding cache primitive

This increment implements explicit-profile vector reuse. Production model identity resolution and pipeline/query wiring remain part of Task 5.

OWNS: src/hippo/knowledge/embedding_cache.py, tests/unit/test_embedding_cache.py

- [x] G5EC: Exact input, resolved profile, document/query kind, dimensions and preprocessing distinguish cache entries; corrupt entries miss safely, model errors propagate and observable identity drift rejects the operation.
  CHECK: .venv/bin/python -m pytest tests/unit/test_embedding_cache.py tests/unit/test_ollama.py -o addopts='' -q
  EXPECT: 96 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=........................                                                 [100%] | 96 passed in 0.09s

- [x] G5EV: Independent specification and quality review passes for the cache primitive, including runtime identity checks and the caller's digest-resolution responsibility.
  EVIDENCE: adaptive_graph_papers independently reproduced and verified both runtime drift fixes; SPEC PASS / QUALITY PASS, 96 tests passed, Ruff and formatting clean. Root reviewed the cache implementation and reran the same 96 tests. Digest resolution and stable model identity remain explicit caller responsibilities.
