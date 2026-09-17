# Gates: compact selector IDs

OWNS: src/hippo/hipporag/retriever.py, tests/unit/test_selector_candidate_ids.py

- [x] G1: Compact IDs round-trip only through the current candidate mapping
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_selector_candidate_ids.py -q -o addopts=''
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=1c70c9f36c41/40 entries; output=....                                                                     [100%] | 4 passed in 0.02s

- [x] G2: Retrieval, answer and original-citation behavior stays compatible
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_retriever.py tests/unit/test_ask.py tests/unit/test_answer_original_citations.py -q -o addopts=''
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=1c70c9f36c41/40 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 91 passed, 1 warning in 15.10s

- [x] G3: Real-model selector replay completes all five original code selections within budget
  EVIDENCE: production probes for Q1, Q2, Q3, Q4 and Q11 all completed normally in 47-49 tokens; every translated identifier belonged to that probe's exact candidate set. The retained full evaluation later passed Q1, Q2, Q3, Q4 and Q11. Private corpus content remains outside the repository; sanitized evidence is in ai_docs/reports/2026-09-16-performance-improvements.md and ai_docs/reports/2026-09-16-qa-profile-final-quality-review.md.
