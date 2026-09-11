# Gates: Task 5 evaluation query snapshot lifetime

OWNS: src/hippo/evals/runner.py, src/hippo/knowledge/eval_access.py, tests/unit/test_eval_snapshot_lifetime.py, tests/unit/test_evals_runner.py, tests/unit/test_eval_access.py, ai_docs/gates/rag-it-all/task-5-eval-snapshot/GATES.md

Scope: Keep one owned or borrowed QuerySession through evaluation retrieval, answering, grading and metrics while rechecking current question ownership and authorization. Root owns durable snapshot save helpers.

Independent review: rag_generation_loader SPEC PASS / QUALITY PASS, 99 combined Fake tests. Review found stale generated evaluations could not release retained snapshots; deletion now checks current ownership/source administration without requiring old evidence to match the current graph. Reads retain their full evidence checks. The companion saved-snapshot ledger verifies atomic persistence and targeted deletion.

- [x] G1: A managed evaluation keeps its selected generation through publication during model work and releases its own reference on completion.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_eval_snapshot_lifetime.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.........                                                                [100%] | 9 passed in 1.11s

- [x] G2: Model failures, current revocation and question denial release references, while borrowed sessions remain owned by their caller.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_eval_snapshot_lifetime.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.........                                                                [100%] | 9 passed in 107.85s (0:01:47)

- [x] G3: Existing evaluation ownership, runner, and query session behavior remain covered.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_evals_runner.py tests/unit/test_eval_access.py tests/unit/test_query_session.py
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=......                                                                   [100%] | 78 passed in 4.18s
