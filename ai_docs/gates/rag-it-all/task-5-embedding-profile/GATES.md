# Gates: Task 5 embedding profile resolver and adapter

Design: `ai_docs/plans/rag-it-all-task-5-embedding-profile.md`.

OWNS: src/hippo/knowledge/embedding_profile.py, src/hippo/ollama.py (explicit HTTP helpers only), tests/unit/test_embedding_profile.py

- [x] G5EP: Strict model resolution captures immutable digest/dimension/prefix/options identity; guarded cache hits and HTTP batches reject observable drift and preserve legacy Ollama behavior.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_embedding_profile.py tests/unit/test_embedding_cache.py tests/unit/test_ollama.py -o addopts='' -q -W error
  EXPECT: 164 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=....................                                                     [100%] | 164 passed in 0.20s
  RED: `/tmp/hippo-embedding-profile-red.log`: 39 failures because resolver module was absent. Precision regression `/tmp/hippo-embedding-profile-precision-red.log`: 1 failed / 52 passed. Captured binding/descriptor regressions `/tmp/hippo-embedding-profile-bindings-red.log`: 4 failed / 54 passed. HTTP retry revocation regression `/tmp/hippo-embedding-profile-retry-red.log`: 1 failed (three unauthorized retry attempts instead of one).
  CHAT RED: `/tmp/hippo-embedding-profile-chat-red.log`: 6 failed / 2 passed; chat HTTP/connection retries resent prompts after revocation, and capability errors swallowed identity changes before prompt dispatch.
  GREEN: `/tmp/hippo-embedding-profile-green.log`: exit zero, 164 passed, warnings treated as errors. Chat now guards each actual HTTP attempt through an explicit optional callback; no shared client state is changed. No pipeline/context wiring is included. Metadata brackets cannot attest the digest of an individual server execution or detect replace-and-restore races.

- [x] G5EPL: Owned Python files pass lint and formatting.
  CHECK: .venv/bin/python -m ruff check src/hippo/knowledge/embedding_profile.py src/hippo/ollama.py tests/unit/test_embedding_profile.py && .venv/bin/python -m ruff format --check src/hippo/knowledge/embedding_profile.py src/hippo/ollama.py tests/unit/test_embedding_profile.py
  EXPECT: All checks passed!
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 3 files already formatted

## Independent review

SPEC PASS / QUALITY PASS from `rag_generation_loader`: 164 focused tests with warnings as errors, Ruff and formatting passed. Six additional MockTransport cases rejected digest/client/endpoint drift after successful chat responses; stable managed retries succeeded. Production wiring remains pending and metadata bracketing does not attest individual model execution.
