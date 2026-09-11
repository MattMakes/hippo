# RAG implementation state

Plan: `docs/rag_it_all.md`.

Branch: `rag-it-all-tibs`, created from `code-graph` at `3ac02f30054fff3827ec25aa799147be99967692`.
The original branch is unchanged. Plan carried in commit `0849471`; branch published to `origin/rag-it-all-tibs`.

## Repository / PR state

GitHub API inspection of `MattMakes/hippo` returned no PR whose head is `code-graph`.
The repository's only PR was #1, `ladybugdb`, already merged. Nothing was closed or merged.

## Execution

- [x] New isolated branch, plan commit and remote publication.
- [x] Pre-flight report: `ai_docs/reports/2026-09-11-pre-flight-report.md`; cleared the foundation tasks with downstream wiring requirements recorded in the plan.
- [x] Task 0: isolated development smoke checker; independent spec and quality reviews passed.
- [ ] Task 1: cross-source fixture and deterministic retrieval baseline.
- [ ] Tasks 2–16, including 5A/9A: pending implementation.
- [ ] Optional experiments E1–E5: not enabled.

## Current verification evidence

- Inherited Ruff check passed; inherited format check found 142 files formatted. After Task 0: full Ruff check passed and 147 files already formatted.
- Full fake-store baseline with authorized loopback: **1,354 passed, 15 skipped**, exit 0. Log: `/tmp/hippo-rag-baseline-fake-loopback.log`. Existing deprecation warnings remain.
- Full inherited Ladybug suite reached completion with exactly two setup errors, both `socket.bind` denied by the sandbox in `test_mcp_http.py`; all remaining cases passed or were backend-specific skips. Log: `/tmp/hippo-rag-baseline-ladybug.log`, exit 1. The two affected tests separately passed with authorized loopback, exit 0: `/tmp/hippo-rag-baseline-ladybug-mcp-loopback.log`. This is split verification, not a claim of one all-green full Ladybug invocation.
- Task 0 tests: **49 passed**, independently rerun by root and spec reviewer. Gate checker executed G0 and passed.
- Real CLI smoke against `http://127.0.0.1:8011`: exit 0; authenticated status/settings valid, Ladybug ready, Ollama ready and configured models installed. Anonymous protected settings returned 401. Retrieval, embedding and generation are explicitly outside this smoke check.
- Development user created through the existing user form and Account page on the isolated store. Credentials exist only in ignored `.rag-dev-data/smoke-credentials.json`, mode 0600; never include its contents in logs or commits.

## Environment evidence

- macOS 26.5.1, arm64, Apple M5 Max, 128 GiB RAM.
- Existing development virtual environment: Python 3.12.11. System Python: 3.12.8.
- `uv pip check --python .venv/bin/python` with temporary cache: 64 packages compatible. The virtual environment does not install pip; no environment replacement was needed.
- real_ladybug 0.15.3; fastapi 0.141.1; httpx 0.28.1; httpx2 2.12.0; mcp 2.1.1; numpy 2.5.3; igraph 1.0.0; pytest 9.1.1; ruff 0.16.6; sqlglot 30.18.0; tree-sitter 0.26.0.
- Existing Ollama includes configured `qwen3:8b` and `nomic-embed-text:latest`; no model download was necessary.
- Isolated server uses `HIPPO_DATA_DIR=$PWD/.rag-dev-data`, `HIPPO_DB_PATH=$PWD/.rag-dev-data/hippo.lbug`, `HIPPO_STORE=ladybug`, `HIPPO_PORT=8011`, and `OLLAMA_URL=http://127.0.0.1:11434`. Server log is `/tmp/hippo-rag-dev-server.log`.

## Constraints

No delivery estimates or timing-based prioritization. Architecture follows the documented capability/correctness requirements. Source chronology and runtime lifecycle safeguards remain functional requirements.

Do not touch the existing `data/` store. Runtime fixtures and experiments use isolated directories or temporary databases. Do not run Neo4j tests against an existing/shared database: the inherited fixture deletes all nodes.
