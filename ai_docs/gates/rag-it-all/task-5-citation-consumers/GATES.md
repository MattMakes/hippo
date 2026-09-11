# Task 5 original citations in answer consumers

Scope: answer and question-generation model inputs, API/MCP/HTML answer sources, search/analysis distinction between derived retrieval text and originals. Uses held GraphIndex provenance from the separately reviewed derived projection. Retrieval trace and evaluation gold IDs stay in retrieval space. Original citations are deduplicated only after complete candidate closure is resolved.

- [x] C1: Models read complete original evidence; many-to-many views retain retrieval IDs separately; missing managed lineage denies dispatch; answer/search/analysis surfaces distinguish originals and rendered views.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_answer_original_citations.py -o addopts='' -q
  EXPECT: 11 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 11 passed, 1 warning in 0.47s
  RED: /tmp/hippo-answer-citations-red.log (3 failed); /tmp/hippo-citation-surfaces-red.log (3 failed); /tmp/hippo-question-citations-red.log (2 failed). Saved question-set creation intentionally precedes the model session because creation changes the authorization epoch; the model job uses one held graph through generation and question persistence.

- [x] C2: Original citation and generation-publication behavior passes on isolated Ladybug.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_answer_original_citations.py -o addopts='' -q
  EXPECT: 11 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 11 passed, 1 warning in 6.33s

- [x] C3: Existing answer, MCP, HTML, analysis and evaluation behavior remains compatible.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_ask.py tests/unit/test_mcp_server.py tests/unit/test_web_base.py tests/unit/test_web_analyze.py tests/unit/test_web_code_pages.py tests/unit/test_web_code_pages_2.py tests/unit/test_evals_question_maker.py tests/unit/test_eval_access.py tests/unit/test_analysis_snapshot_lifetime.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 149 passed, 1 warning in 25.80s

- [x] C4: Owned Python files pass lint and formatting.
  CHECK: .venv/bin/python -m ruff check src/hippo/ask.py src/hippo/evals/question_maker.py src/hippo/hipporag/answerer.py src/hippo/knowledge/answer_evidence.py src/hippo/mcp_server.py src/hippo/web/routes/api.py src/hippo/web/routes/pages.py src/hippo/web/routes/analyze.py tests/unit/test_answer_original_citations.py && .venv/bin/python -m ruff format --check src/hippo/ask.py src/hippo/evals/question_maker.py src/hippo/hipporag/answerer.py src/hippo/knowledge/answer_evidence.py src/hippo/mcp_server.py src/hippo/web/routes/api.py src/hippo/web/routes/pages.py src/hippo/web/routes/analyze.py tests/unit/test_answer_original_citations.py
  EXPECT: All checks passed!
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 9 files already formatted

## Independent review

SPEC PASS / QUALITY PASS from rag_generation_loader after multi-hop original deduplication fix: 100 Fake tests and two real Ladybug regressions pass; scoped Ruff passes. Multi-hop pairs require distinct originals on both sides and send shared originals only once. Staged production ingestion, remaining direct graph/code-tool lifetimes, historical selection and full evidence packing remain separate Task 5/5A/14 work. No generated retrieval text is relabeled as an original quote.
