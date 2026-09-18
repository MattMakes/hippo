# Gates: optional grounded final QA profile

OWNS: src/hippo/config.py, src/hippo/context.py, src/hippo/ollama.py, src/hippo/ask.py, src/hippo/hipporag/answerer.py, src/hippo/prompts.py, src/hippo/cli.py, src/hippo/web/templates/settings.html, .env.example, docker-compose.yml, README.md, docs/FIDELITY.md, tests/unit/test_qa_profile.py, tests/fakes/fake_ollama.py

- [x] G1: Default compatibility, exact QA profile wiring and error handling
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_qa_profile.py tests/unit/test_ollama.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning'
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=1c70c9f36c41/40 entries; output=.............                                                            [100%] | 85 passed in 0.62s

- [x] G2: Existing answer, authorization, embedding, evaluation and operational surfaces stay compatible
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_ask.py tests/unit/test_answer_context.py tests/unit/test_answer_original_citations.py tests/unit/test_retriever.py tests/unit/test_selector_candidate_ids.py tests/unit/test_query_authorization_boundary.py tests/unit/test_query_session.py tests/unit/test_dense_session.py tests/unit/test_embedding_profile.py tests/unit/test_rag_replay_access.py tests/unit/test_evals_runner.py tests/unit/test_eval_access_lifetime.py tests/unit/test_web_base.py tests/unit/test_status_access.py tests/unit/test_cli.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning'
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=1c70c9f36c41/40 entries; output=......................................................................   [100%] | 430 passed in 35.94s

- [ ] G3: Complete grounded answers on all fixed18, with honest measured latency and model identity
  EVIDENCE: strict gate failed. The isolated production ask run completed all fixed18 with the original12 and supplemental6 unchanged, stable model/source identity, normal provider stops, nonempty public answers and resolved authorized evidence, but independent grading passed 16/18. Q8 omitted three supplied names and S4 changed one accented Unicode value. See ai_docs/reports/2026-09-16-qa-profile-final-quality-review.md.

ABANDON: G3 User explicitly accepted closure at 16/18 on 2026-09-17 with Q8's three supplied names omitted and S4's accented Unicode value changed; the original 18/18 requirement remains unmet and is future work.

- [x] G4: Revised manual acceptance retains the opt-in QA profile with the measured 16/18 limitations
  EVIDENCE: user decision on 2026-09-17 ends optimization and accepts the opt-in profile under the documented 16/18 scope; the base 8B path remains unchanged, the 27.3B qwen3.8:latest model is opt-in for final QA only, and no two-call review pipeline was retained.
