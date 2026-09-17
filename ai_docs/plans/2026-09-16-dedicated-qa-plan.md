# Optional dedicated QA profile implementation plan

For Codex only. Status: AUTHORIZED for Task1 implementation by the orchestrator after independent candidate M PASS6/6. Retention is conditional on full18 and final review; no commit is authorized to the worker.

**Goal:** Preserve inexpensive retrieval/extraction while enabling one explicit grounded final-answer model/profile whose quality and total cost are measured separately.
**Architecture:** Follow every fixed interface in `ai_docs/designs/2026-09-16-dedicated-qa-profile.md`. Per-request model override on the existing guarded client; no second client, model mutation, refinement call or authorization bypass.
**Gates:** `ai_docs/gates/dedicated-qa/GATES.md`.
**Tech stack:** Existing Python/httpx/pytest/Jinja and root `.venv`; fake/Ladybug stores. No packages or services needed.

## Task0: environment and verified seams

No server startup, credentials or auth bypass is needed. HTTP tests use MockTransport; corpus/model access belongs exclusively to parent. Parent has verified the Ollama endpoint and installed models with successful scratch calls. Config → AppContext.from_env → Ollama constructor supplies availability; ask/answer_from_trace → _answer_from_trace → answer_question → AuthorizedModel/ProfiledEmbeddings → Ollama.chat_text → _chat → guarded _request is the actual answer path. ModelManager, status and startup already use required_models. Settings/CLI display config. `evals/runner.py` calls answer_from_trace and judges with the base model. `evals/rag_all.py` is retrieval-only: do not alter its provenance to claim it called QA.

## Task1: one coherent opt-in path

Gates: G1,G2,G3. OWNS: every file in the gate header. Additional necessary test files may be changed only to add focused independent-oracle coverage; no existing expected outcomes may be weakened. Report any scope conflict. Parent owns all other pending selector/evidence source changes and reports; preserve them.

1. Read design, current source and relevant tests. Record starting git status/diff and existing QA_SYSTEM text from `git show HEAD:src/hippo/prompts.py` for the authorized narrow rollback. Do not restore the whole file.
2. Add `tests/unit/test_qa_profile.py` with meaningful failing cases before production changes. Prove default/inherit/nonempty env, default4 vs configured2 messages, exact model/options/wire controls, one call, final/thinking separation, nonempty/normal completion, truncation/errors, and selected-model capability lookup preserving thinkFalse for capable models and omission for others. Use actual Ollama via MockTransport rather than only checking kwargs; fixed expected request objects must not come from the production builder being tested.
3. Watch RED and capture log. Missing new API TypeError/import failures alone are insufficient: where practical tests must reach a behavior assertion with a small compatibility helper, or document API absence separately from behavioral RED. Add integration cases through ask and answer_from_trace, empty evidence zero calls, QA override followed by default structured call, separate capability cache, and validation/revocation across wrappers, show/chat/retry and output release. Use existing synthetic source fixtures; no private benchmark facts enter tests.
4. Implement the exact design with explicit optional keywords. Keep all structured/default calls unchanged. Preserve zero-valued min_p/seed. Check requested model capabilities. `require_complete` errors contain no raw response/source. Native thinking never returned. No fake pass via final content substitution. The accepted generic system text must be copied byte-for-byte from the parent-named accepted scratch profile, not rewritten.
5. Wire Config/environment/compose/AppContext, required-model aliases and readiness. Tests cover empty/inherit/same/distinct models and one missing QA model (missing/ready/pull results). Settings labels accurate whether QA differs or explicitly uses base. CLI prints override/inheritance. Programmatic client injection follows the documented matching-constructor contract; do not mutate a supplied client.
6. Restore only unsuccessful uncommitted legacy QA_SYSTEM to HEAD and add separate grounded helper/constant. Preserve bounded original citation bundle and supplemental limits. Update answerer/docstrings/README/FIDELITY, `.env.example`, compose: default reference protocol, explicit grounded direct-mode profile,4096 cap, temperature0 and preserved sampling controls, example qwen3.8:latest, quality claims pending full18. No production `.env`, service or data changes. If FakeOllama's normal response lacks done=True, add that faithful provider field only as needed for profile integration tests.
7. Run G1/G2 exactly; capture counts and logs. Run new ask/citation profile integration on Ladybug with sufficient timeout (>=600s). Run Ruff check/format only owned Python files, compileall on owned Python, and git diff --check. Use root .venv. Do not run full suite/model/corpus benchmarking. No concurrent timing should begin until this worker reports all tests terminal.
8. Write sanitized `ai_docs/reports/2026-09-16-dedicated-qa-implementation.md`: numbered requirement table, exact RED/GREEN commands/logs/counts, final-source hashes, how guards/wrappers are preserved, any limits. G3 remains parent-owned. No commit/stage/push; independent review and full18 required before retention.

## Parent follow-through

Prepare a new private copy of the fixed full18 harness, explicitly Config.qa_model plus Ollama.qa_model, preserving frozen oracle and source export. Capture actual model names/digests and all source hashes. Verify six captured accepted requests through the production adapter before running full18. Start fresh reviewer after implementation, with auth/availability/response completeness focus. Run isolated full18 only when all tests are terminal and source reviewed; independent grading must see exact final source/context, no thought-as-answer credit. Report timings separately for original12 and supplemental6, base8B vs QA27B cost, coldload and provider calls; do not add component speedup percentages.

## Plan verification checklist

- [x] Parent diagnostic precondition met; exact accepted M system source/hash recorded in the design.
- [x] Wiring map and real function signatures inspected before planning.
- [x] Default compatibility, guard boundaries, config/readiness and product labels included.
- [x] External HTTP behavior has real adapter/MockTransport integration checks; existing endpoint availability already verified separately.
- [x] Citation/evidence/authorization/generation lifetimes unchanged by design.
- [x] Static pre-flight and parsed gate ledger verified; Task1 creates G1 test file before dynamic execution (see dedicated pre-flight report).
- [ ] G1/G2, final-source Ladybug regression and independent review complete.
- [ ] G3 full18 source-backed acceptance, writeup, post-flight and named-file commit complete.

| Preservation table | Contract and plan task |
|---|---|
| Wiring | Fixed seams in Task0; implementation Task1 steps4–6; real adapter proof parent |
| Public contract | Answer fields/citation order/default four-message behavior retained; Task1 steps2–4 |
| Data | No schema/corpus/production config change; synthetic tests only; Task1 steps3,6 |
| Authorization | Existing wrappers and every request/retry/output guard retained; Task1 steps3–4 |
| Failure | Explicit incomplete/unsupported errors, no fallback draft or thinking output; Task1 steps2–4 |
| Operations | Required models/readiness/pull/settings/CLI reflect explicit opt-in; Task1 step5 |

## External dependencies

| Dependency | Existing runtime source | Planned change | Verification |
|---|---|---|---|
| Ollama | Existing OLLAMA_URL; local installed models; no new authentication | Optional final-QA model on same guarded client and endpoint | Real MockTransport body/guard tests; parent already completed M live calls; full18 later |
| Graph store | Existing Config/open_store and synthetic fake/Ladybug test fixtures | None | Existing authorization/citation regression gates |
| Test tooling | Root .venv Python/httpx/pytest/Ruff | None | G1/G2 and focused Ladybug; no installs |

## Closure under revised acceptance (2026-09-17)

Task1, its focused fake/Ladybug validation, public-error coverage and independent error-boundary review passed. The isolated production fixed18 run used the retained single-call, direct final-QA profile with the opt-in 27.3B `qwen3.8:latest` model while leaving the base 8B model and default inherited protocol unchanged. It completed all cases with normal stops, stable identities and resolved authorized evidence, but strict G3 failed at 16/18: Q8 omitted three supplied names and S4 changed one accented Unicode value.

The user explicitly accepted those two limitations on 2026-09-17 and directed that optimization stop. The original 18/18 G3 is therefore preserved as an abandoned strict gate, while a new manual gate records the revised retention decision. No two-call review integration or rejected private experiment is retained, and the remaining two cases are future work.
