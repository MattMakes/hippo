# Gates: RAG Task 5 generation namespaces

This increment covers Task 5 step 1 and its input-identity prerequisite. Staged writes, caching, snapshot leases and managed lifecycle dispatch remain under the full Task 5 gate.

OWNS: src/hippo/codegraph/model.py, src/hippo/codegraph/extract.py, src/hippo/codegraph/python.py, src/hippo/codegraph/typescript.py, src/hippo/codegraph/go.py, src/hippo/codegraph/rust.py, src/hippo/codegraph/csharp.py, src/hippo/codegraph/resolve.py, src/hippo/codegraph/git_history.py, src/hippo/knowledge/lifecycle.py, tests/unit/test_generation_namespace.py, tests/unit/test_generation_inputs.py

- [x] G5NI: Accepted revision/configuration inputs determine generation identity before output nodes or checksums exist; replay ordering and observation timestamps do not change identity.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_generation_inputs.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=................                                                         [100%]

- [x] G5NS: Native generation IDs are disjoint while logical source ownership and legacy IDs remain unchanged; walkers, resolver objects, Git and chunk definitions propagate the namespace consistently.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_generation_namespace.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=...................                                                      [100%]

- [x] G5NR: Independent specification and quality review passes, including namespace-omitted extraction compatibility.
  EVIDENCE: Independent adaptive_graph_papers specification and quality review PASS;350 constructor/namespace/extraction/five-language/history/chunker cases passed independently and in root /tmp/hippo-rag-task5-namespace-root.log. Legacy three-argument registered walkers and empty-SQL namespace rejection each have actual RED-to-GREEN regressions. Root reviewed code and verified no store/schema or lifecycle publication changes.
