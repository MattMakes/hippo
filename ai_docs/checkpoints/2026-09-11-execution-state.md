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
- [x] Task 1: cross-source fixture and deterministic retrieval baseline; spec and quality reviews passed.
- [x] Task 2: immutable identities/evidence/lifecycle/query contracts; 119 tests and independent specification/quality reviews pass.
- [ ] Tasks 3–16, including 5A/9A: pending integration/implementation.
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

## Disposable Neo4j preparation

A newly created container `hippo-rag-test-b780ab5` runs the existing `neo4j:5.26-community` image (runtime 5.26.30), with no existing data mount. Bolt is bound only to `127.0.0.1:32774`. The 98 inherited store/code/eval/graph/row-shape tests passed against it, exit 0; log `/tmp/hippo-rag-baseline-neo4j-store.log`. This establishes the disposable backend before managed persistence work; it does not prove the future migration contracts.

## Inherited CI portability fix

Baseline CI run `34629977683` failed three history assertions because its Git renders ISO UTC as `Z`, while the checked-in expectations spell the same instants `+00:00`. The fix compares parsed aware timestamps in `test_git_history.py` and the history comparison helpers in `test_indexer.py`; application date text and golden fixtures remain unchanged. The affected two modules passed all 71 tests locally; independent review passed. CI must verify the runner-specific form after publication. Log: `/tmp/hippo-rag-git-date-fix.log`.

## Persistence probe findings for Task 3

Temporary-only probe `/tmp/hippo_rag_ladybug_probe.py` confirmed that Ladybug 0.15.3 rolls back node/relationship DDL, ALTER and multiple writes together, and supports catalog-first version guards and conditional-update CAS. Database errors can auto-abort: rollback cleanup must preserve the original exception when no transaction remains. Free-text lists require byte elements and `list_transform(CAST($names AS BLOB[]), x -> decode(x))`, including empty/null lists. Validate integer contracts before writing: FLOAT to INT64 otherwise truncates. No persistence implementation is claimed yet.

CI run `34631555844` for commit `a21ea35` completed successfully: Ruff, fake and Ladybug suites on Python 3.11/3.12, and the complete real Neo4j unit suite. This confirms the inherited timestamp portability fix on the Linux runners and provides full backend baseline coverage beyond the earlier split local Ladybug run.

Task 1 implementation reached independent review: root ran G1 (27 tests passed), 15 inherited metric tests, full Ruff lint/format, and two actual CLI development baseline runs with byte-identical output. Seven of twelve dev questions evaluated; five explicit capability gaps. The corpus has 24 questions across six slices. No Task 1 completion claim yet: spec/quality reviews remain in progress, and any fixes require fresh checks/capture.

Task 1 independent spec re-review passed after four focused corrections: all-gold leakage/permission validation, strict aware temporal selectors and boolean insufficiency, temporal capability detection independent of labels, and metric-specific sample counts. Root's fresh G1 ran 51 tests successfully; 15 inherited metric tests and full Ruff also passed. Independent quality review passed and additionally confirmed identical results with different PYTHONHASHSEED values. Two small quality refinements (string-list validation and stable references for unlabeled candidates) are being completed before final baseline capture and commit.

Task 1 final verification: G1 and G1R met; 56 focused tests and 15 inherited metric tests passed, full Ruff lint/format passed. Two final CLI reports are byte-identical (SHA-256 `e72d524e1eb883553740cd688282dc177f22bdf1b27a7e07697757cb4b395650`). Saved report `ai_docs/reports/2026-09-11-rag-legacy-dev.json` contains seven evaluated dev questions, five capability gaps, original candidate references, settings and per-metric sample counts. No holdout quality tuning or live-model quality claim. Optional live recipe is documented in the fixture README. Task 2 is in progress with /root/rag_task2; contracts/tests only, no persistence yet.

Neo4j migration probe: the disposable 5.26.30 backend rejected mixed schema/data writes with Neo.ClientError.Transaction.ForbiddenDueToTransactionType; rollback left no probe constraint or node. Task 3 now explicitly requires guarded, journaled idempotent Neo4j schema steps plus atomic data/completion transactions. Ladybug retains a single transactional schema/data migration. Probe records were removed.

Agent orchestration note: creating another new agent hit the thread limit after Task2 dispatch. Completed agents remain available through followup_task; reuse them with explicit new scopes if additional fresh threads remain unavailable. /root/rag_task2 owns only the new knowledge modules/tests and an explicit direct dependency declaration. /root/rag_contract_design is checking additional identity collision cases read-only. No Task3 implementation has started; its ledger is prepared.

Task 1 is committed/published as `76d1448`. CI run `34633261255` completed successfully across Ruff, fake/Ladybug on Python 3.11 and 3.12, and real Neo4j. Task 2 initial RED established 34 expected missing-module/contract failures; implementation remains in progress. Identity preparation flagged semantic PostgreSQL equivalence, provider base-path/encoded-separator distinctions, module/member discriminators and API identity/version separation; implementer is incorporating those cases.

Task 2 root G2 initially passed 104 focused tests; full Ruff passed with 159 formatted files. Independent specification review then found three additional defects: builtin IDNA merges distinct provider hosts, normalized locator defaults/paths were discarded before span hashing, and manifest knowledge cutoffs could contradict their embedded selectors. These are being fixed with new RED tests; Task 2 is not complete until re-review and quality review pass.

Independent Task 3 capability preparation found no installed FTS/vector extensions in real_ladybug 0.15.3. No extension was installed or downloaded. Native-dependent correctness gates are unrun, not failed or passed; the documented filtered lexical/NumPy fallback remains selected. Disposable core FLOAT[3] and filtered exact cosine fixtures passed, including dimension rejection, visibility/generation/time filtering, hidden-record edit noninterference, validity closure and deletion. This does not establish application ACL or concurrent revocation correctness. Reproducers/reports live under `/tmp/hippo-ladybug-{capability,exact}-prep.*`. A permanent isolated capability script is being prepared independently of the pending contract corrections; no managed persistence is implemented yet.

Task 2 final verification: all 119 focused tests pass, including new RED-tested Unicode-host collision, canonical locator/default and manifest-cutoff consistency cases. Root G2 reverify passed. Independent specification re-review passed all 12 requirements; subsequent code-quality review passed without blockers. Targeted Ruff lint/format and git diff whitespace checks pass. Full-repo lint also passed; the separately in-progress capability test file was still being formatted. All 35 required persisted records round-trip through strict version-1 envelopes. G2/G2R are met. Task 3 persistence may now begin; native capability implementation remains independently scoped.

Task 2 commit: `be51619`. Automatic approval review initially rejected publication to the public remote and permitted a separate local commit. After read-only verification of `origin` (`git@github.com:MattMakes/hippo.git`, public, viewer ADMIN), the user explicitly answered: "Yes, publish reviewed commits to that branch." Publication then succeeded: `76d1448..be51619` on `origin/rag-it-all-tibs`. This authorization persists for reviewed implementation commits to that destination; do not ask again. Task 3 persistence is assigned to `/root/rag_task2`; `/root/adaptive_graph_papers` owns the isolated capability tool/tests. Root independently ran the initial 11 capability tests and actual command successfully; subsequent native-report integrity corrections remain under review.

Task 3 initial persistence/publication slice passed 10 tests on fake and real Ladybug according to the implementer; root is independently running the same slice against the disposable Neo4j instance. Full legacy/auth preservation, migration recovery and all-record coverage are still in progress, so this is not a Task 3 completion claim. Root also clarified that preexisting v1 binaries lack a schema guard: downgrade requires an isolated pre-upgrade restore, not running an old binary on an upgraded store.

Subagent execution later failed with a reported usage limit. `/root/rag_task2` stopped during Task 3, and `/root/adaptive_graph_papers` stopped before implementing Task 4 MCP transport changes. Root continued locally. Task 4 MCP has a prepared ledger but no implementation; the rest of Task 4 still depends on Task 3. Read-only preparation identified additional wiring in `web/render.py`, `web/routes/pages.py`, `web/adhoc.py`, `analysis/simulate.py` and `hipporag/graph_index.py`; the plan now includes these. HTTP credential mode must be explicit: the normal app's AuthGate can already block headerless requests, while low-role cookies combined with an ambient admin token remain a concrete identity-confusion regression to test.

Capability subtask is complete and independently reviewed: 20 tests, actual CLI and Ruff pass. Saved report `ai_docs/reports/2026-09-11-store-capabilities.json`; G3C met, with native installed-extension behavior and application isolation guarantees explicitly unverified. Root corrected the isolation fixture to use the actual HIPPO_DB_PATH name. This does not complete Task 3.

Root validated the interrupted persistence work: first 19 focused tests passed on fake and Ladybug. Expanded Neo4j revealed that a future-version test intentionally poisoned the shared disposable fixture; `tests/conftest.py` now resets through the raw test driver before application bootstrap, retaining the application's refusal behavior. Four new RED tests reproduced cross-source generation/snapshot binding, connector-provider mismatch, cross-revision sections and caught nested-transaction failure; fixes passed, followed by 121 tests on fake and Ladybug (new persistence plus inherited store suites) and all 23 focused tests on Neo4j. Logs: `/tmp/hippo-rag-task3-{fake,ladybug}-expanded.log`, `/tmp/hippo-rag-task3-neo4j-recheck.log`.

Further root RED tests added migration history, strict version-number types and physical-schema verification. New migration helpers preserve v1/v2 checksum history and validate actual Ladybug tables/columns/relationship endpoints plus Neo4j constraint/index definitions. Additional recovery tests now inject failure after each declared DDL step, and prove an initial Ladybug migration rolls back newly created tables and added columns. These final changes still need complete backend reruns and independent review. Task 3 remains uncommitted/incomplete; do not publish it as reviewed work. Full Ruff currently passes (167 files formatted).
