# Gates: complete answers and bounded source evidence

OWNS: src/hippo/ask.py, src/hippo/prompts.py, src/hippo/hipporag/answer_context.py, tests/unit/test_answer_context.py, tests/unit/test_ask.py, tests/unit/test_retriever.py

- [x] G1: Supplemental source context follows authorized graph edges within explicit bounds
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_answer_context.py -q -o addopts=''
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=1c70c9f36c41/40 entries; output=.............                                                            [100%] | 13 passed in 0.04s

- [x] G2: Retrieval, citation and live query boundaries remain compatible
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_ask.py tests/unit/test_retriever.py tests/unit/test_answer_original_citations.py tests/unit/test_query_authorization_boundary.py tests/unit/test_query_session.py tests/unit/test_dense_session.py -q -o addopts=''
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=1c70c9f36c41/40 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 184 passed, 1 warning in 16.46s

- [ ] G3: Complete grounded results on every original case and supplemental checks
  EVIDENCE: strict gate failed. The final source-backed production run completed all 18 cases with stable source/model identity and normal provider stops, but passed 16/18: Q8 omitted three supplied names and S4 changed one accented Unicode value. Q3, Q5 and Q9 passed, as did the required Q11/Q12 abstentions. See ai_docs/reports/2026-09-16-qa-profile-final-quality-review.md.

ABANDON: G3 User explicitly accepted closure at 16/18 on 2026-09-17 with Q8's three supplied names omitted and S4's accented Unicode value changed; the original 18/18 requirement remains unmet and is future work.

- [x] G4: Revised manual acceptance records the retained 16/18 result and both known limitations
  EVIDENCE: user decision on 2026-09-17 accepts the measured 16/18 scope without further optimization; ai_docs/reports/2026-09-16-qa-profile-final-quality-review.md records the independent fixed-case grading and ai_docs/reports/2026-09-17-performance-post-flight.md records the scope change without claiming 18/18.
