# Gates: RAG Task 0

OWNS: scripts/rag_local_smoke.py, tests/unit/test_rag_local_smoke.py, .gitignore

Scope: authenticated local smoke tooling and a recorded unchanged application baseline.

- [x] G0: The smoke checker distinguishes authenticated readiness, unavailable dependencies and invalid HTTP/schema responses without exposing credentials.
  CHECK: .venv/bin/python -m pytest tests/unit/test_rag_local_smoke.py -q
  EXPECT: [100%]
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=.................................................                        [100%]

- [x] G0B: Existing fake/Ladybug suites and Ruff baseline are recorded with actual failures and skips distinguished.
  EVIDENCE: Full fake baseline: 1354 passed, 15 skipped, exit 0. Full Ladybug baseline completed with two sandbox-only localhost setup errors; both affected tests passed separately with authorized loopback, exit 0. Full Ruff lint and format passed. Commands, logs and environment recorded in ai_docs/checkpoints/2026-09-11-execution-state.md.

- [x] G0R: An isolated authenticated server passes the smoke command and refuses unauthenticated protected access.
  EVIDENCE: Actual CLI subprocess against isolated Ladybug server on 127.0.0.1:8011 exited 0; authenticated status/settings and configured Ollama model readiness passed, anonymous settings returned 401. User created using existing form; private token remains ignored.
