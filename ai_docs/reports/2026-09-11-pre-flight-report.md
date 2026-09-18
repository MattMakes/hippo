# Pre-flight report: RAG it all

Date: 2026-09-11. Plan: [docs/rag_it_all.md](../../docs/rag_it_all.md). Inspected implementation baseline: `3ac02f30054fff3827ec25aa799147be99967692`, carried forward from `code-graph` to `rag-it-all-tibs`.

This review read the complete 1,635-line plan and inspected the current Python application, stores, ingestion, access, transports, configuration, and test/CI setup. It made no application or plan changes. It did not run the application tests, live provider requests, model calls, migration tests, or database performance checks. Task 0 runtime verification is being performed separately by the root implementation agent. Findings below are source-inspection evidence and implementation requirements, not passing acceptance gates.

## Prerequisites

- Runtime discovery: source-level baseline is present in plan section 2. The plan records a limited prior disposable Ladybug probe and explicitly states its limits. Fresh Task 0 runtime results remain pending this review. This is an additive extension with explicit migration work, not an undocumented replacement service.
- Local development setup: present as Task 0, including isolated data paths, authenticated smoke, fake/Ladybug regression tests, and disposable Neo4j guidance.
- External dependencies matrix: present in section 11.2. Existing stored authentication material needs the additional migration coverage described under F.
- Deployment and ordering: local-first LadybugDB and planned Neo4j adapter parity are explicit. No delivery estimates or timing-based implementation decisions are introduced here. Operational clocks/timeouts and temporal evidence remain functional requirements.

## Verdict

**CLEAR FOR TAKEOFF for Task 0 and the fixture/contract foundation.** No unresolved research reference, live connector credential, or native search extension prevents that work. The source-level corrections below must be incorporated into their owning tasks before those tasks can pass. In particular, do not expose managed records through current read routes before the Task 4/5 visibility and snapshot protections exist.

This is not approval to claim G0–G20 complete or to promote unverified live connectors. Missing live credentials block the corresponding deployment checks, not recorded-response adapter implementation. The root agent can make these concrete corrections within the user's authorization; no further user permission is needed.

Execution coordination update: the root incorporated workspace membership, authorized status aggregates, early managed projection protection, and caller snapshot reuse into the plan in commit `0849471`, and is carrying authentication continuity into the migration fixture. These are tracked implementation requirements rather than unresolved design permission requests. The remaining implementation checks below stay attached to their tasks.

## A. Wiring verification

**PASS — primary registrations are identified.** Section 10.3 names both real stores and FakeStore, parser dispatch, connector registry/AppContext, snapshot acquisition, shared ask orchestration, HTTP routers, CLI forwarding and MCP. Existing implementation uses direct composition rather than a third-party dependency injection container: `src/hippo/store/__init__.py:61` composes Neo4j query mixins; `:77` selects the backend; `src/hippo/context.py:48` constructs runtime collaborators. New query mixins must be registered in that composition and all store contracts must be implemented by Ladybug and FakeStore.

**Required correction A1 — workspace/group identity needs a concrete contract (Tasks 2–4).** Section 9 requires workspace membership and provider groups, but the core record list does not define membership/mapping records. Existing `Access` only contains rank, user ID and unrestricted state (`src/hippo/access.py:114`). Define a validated principal scope with workspace memberships and namespaced provider user/group IDs; persist or explicitly load the reviewed mapping through one authoritative configuration path. Include its version in the authorization fingerprint. Default legacy sources to the default workspace without broadening managed access. A role-preview principal without a real user must not inherit the viewer's provider groups.

**Required correction A2 — legacy projection protection belongs before managed visibility (Tasks 4–5).** Section 8.1 correctly requires an authorized snapshot projection, but its concrete adapter implementation is listed again in Task 13. Build the minimum safe projection in Task 4/5 and reuse it in Task 13. Current `AppContext.graph_for()` filters only visible source IDs and caches by source set (`src/hippo/context.py:106–132`); that cannot enforce restricted comments or support groups within one source. Until the protected projection exists, keep managed records out of the ordinary legacy loader. Test that staging, retired and restricted support cannot become seeds, synonyms, communities, or score contributions.

**Required correction A3 — every caller must reuse the pinned result (Tasks 4–5).** Changing `ask.py` alone does not close the snapshot boundary. `/api/search` calls shared search, then reacquires `ctx.graph_for()` to render its code block (`src/hippo/web/routes/api.py:105–117`). Audit equivalent MCP/code/analysis callers. Return or retain a request-local pinned projection/result and serialize code context from it. Add `web/routes/api.py` and relevant MCP/analysis callers to task ownership. Existing snapshot-less saved traces must be marked legacy and authorized at replay rather than silently interpreted as a new managed snapshot.

**Required correction A4 — router and worker lifecycle order (Tasks 9A/15).** Add routers before `_mount_mcp()` in `src/hippo/web/app.py:63–65`; the existing comment documents that the MCP mount catches otherwise unmatched routes. Start the maintenance scheduler in the application lifespan and stop it before `AppContext.close()` waits for jobs and closes the store. Do not start an autonomous scheduler merely because an offline CLI/test constructs `AppContext`. Keep external work outside the database transaction/write lock.

**PASS — managed native identities cover more than symbols.** Section 7.3/Task 5 explicitly includes code walkers, resolver-generated data, commits, references and chunk definitions. This matches `symbol_id`, `data_id`, and `commit_id` in `src/hippo/codegraph/model.py:102–115`. Preserve the legacy constructors' default output and rematerialize all cached source-scoped references for managed generations.

## B. Behavioral preservation

No separate `source_path` was supplied; the current branch baseline is the preserved implementation. This category therefore checks explicit preservation seams rather than asserting a completed old/new parity comparison.

**PASS — failure and concurrency behavior are recognized.** The plan retains last-good generation serving, explicit model/provider failure coverage, original parser provenance, legacy ranking and FakeStore/real-backend parity. It correctly identifies the indexer's existing unconditional embedding metadata/version writes (`src/hippo/hipporag/indexer.py:307–309`) and requires staged writes to suppress them.

**Required correction B1 — route all managed delete/reindex entry points (Tasks 5/9A).** The current `pipeline.delete_source()` calls source-wide store deletion and removes the entire source directory; `_prepare_reindex()` calls source-wide cleanup (`src/hippo/ingest/pipeline.py:408–477`). HTTP source management uses these entry points (`src/hippo/web/routes/sources.py:431–449`), and `reindex_all()` traverses every source. Add a managed/legacy dispatch at the common pipeline/service boundary, not only in new connector routes. Managed reindex stages a replacement; managed deletion suppresses and schedules the configured lifecycle action. Existing low-level source-wide cleanup must refuse managed misuse. Do not delete blobs referenced by retained revisions or query pins. Test deletion and bulk reindex through the existing public API as well as direct maintenance methods.

**Required correction B2 — migration guard precedes schema mutation (Task 3).** `LadybugStore.__init__()` calls `ensure_schema()` immediately (`src/hippo/store/ladybug.py:242–267`), while Neo4j bootstraps lazily through `ping()` (`src/hippo/store/base.py:176–205`). Check stored schema compatibility before applying new declarations or crash cleanup at either path. Preserve the Ladybug file lock, bytes/decode text workaround, and shutdown ordering. Add a populated future-schema fixture proving an older/newly incompatible process refuses without modifying data.

**Required check — managed startup recovery.** Both stores currently mark interrupted source/eval jobs failed on first connection. Task 5 must distinguish an abandoned managed build from the active serving source, as already required by section 7.3. Task 9A then resumes durable leases/jobs rather than treating thread bookkeeping as truth.

## C. Contract surface analysis

**PASS — additive endpoint strategy.** Task 15 adds `/api/knowledge/*` and preserves current endpoint/tool names. Current `/api/ask` returns `answer`, `thought`, `passage_ids`, `trace`, and the five shared code fields (`src/hippo/web/routes/api.py:84–101`; `src/hippo/ask.py:69–89`). Preserve these fields through the stated compatibility adapter. `passage_ids` remains supplied context, not verified claim entailment.

**Required correction C1 — authorized status/metadata is part of the evidence boundary (Task 4).** `/api/status` only sanitizes running job keys for restricted users (`src/hippo/web/routes/api.py:29–38`). `system_status()` currently returns global statistics, and `_code_card()` scans unrestricted source metadata (`src/hippo/status.py:42–70,82–101`). Include `status.py` and `web/routes/api.py` in Task 4 ownership. Compute user-visible counts and code summaries from authorized current membership or expose only non-content service health to restricted users. Test that adding a private-only corpus does not change exposed content metadata for an unauthorized viewer. Recheck other template/status callers because the module cache is process-global.

**Required check — errors and ambiguity remain machine-readable.** Preserve HTTP validation/auth/not-found semantics, `{"error": ...}` model failure handling, and the `RemoteAmbiguous` candidate-bearing 409 path (`src/hippo/remote.py:31–41,77–94`). New unsupported-mode errors must fail explicitly. New evidence IDs should return an unavailable/purged marker only under the authorized contract, without exposing forbidden revision details.

**PASS — HTTP/stdio credential distinction is a known change.** Current MCP falls back to the environment token even when an HTTP request supplied no bearer (`src/hippo/mcp_server.py:99–118`). Task 4 explicitly fixes this and requires an actual HTTP client regression test; local stdio environment authentication remains supported.

## D. Configuration migration

No replacement configuration tree was supplied, so there is no completed migration to compare. Current configuration is `Config/load_config()` in `src/hippo/config.py`; persistent retrieval settings are separately validated by `store/base.py`.

**PASS — configuration sources and separation.** Preserve `HIPPO_STORE`, data paths, Neo4j credentials, Ollama model/context settings, upload limits and host restrictions. Add connector credentials as references, not serialized secrets. Keep new operational configuration in one validated source and query ranking settings in their existing validation path; do not create competing defaults in connector constructors, UI forms and retrieval modules.

**Required check — managed capability activation.** Task 5 initially publishes only its implemented dense/legacy-compatible manifest. Task 13 changes mandatory capability version and rebuilds before enabling hybrid. Native FTS/ANN cannot silently become a startup dependency or omit generation/permission/time filtering. Extension unavailable is a supported fallback outcome, not a passing native-extension test.

**Required check — health semantics.** Existing status distinguishes `store`, `ollama`, `models`, `models_ready`, and `ready` (`src/hippo/status.py:46–65`). The smoke and new operations UI must preserve this distinction. Do not report the system ready solely because HTTP returned 200.

## E. Domain assumptions and constants

Existing values inspected: local host `127.0.0.1`; port `8000`; `num_ctx=8192`; configured LLM timeout `600`; upload size `50,000,000` bytes; extracted text `20,000,000` characters; chunk size/overlap `1500/150` characters; two OpenIE workers (`src/hippo/config.py`). Existing source deletion waits up to 60 seconds for its job; retrieval scoped cache holds 16 entries; legacy answer output is capped at 1024 tokens (`src/hippo/hipporag/answerer.py:14`). Existing source visibility is rank-or-owner, and installations are open before first user creation.

**PASS — plan distinguishes old defaults from new policy.** Managed policies add requirements without converting catalog ownership into read access. New chunking/token budgets, polling/lease intervals and temporal precision are named tunable functional defaults. The new answer reserve must be passed to the actual model output limit; legacy 1024 remains available for parity. Database case/quoting and provider revision ordering are explicitly domain-specific.

**Required check — freeze new defaults in validated configuration and deterministic fixtures.** Inject the clock for leases, policy expiry, recency and retention. Unknown timestamps receive no recency bonus; ingestion time is not business time. Missing policy denies managed evidence. Preserve existing input/archive/root restrictions in new local and remote readers. Do not use elapsed delivery time or schedule estimates to choose implementation scope.

## F. Credential source inventory

| Credential/material | Current runtime source | Plan/required preservation | Finding |
| --- | --- | --- | --- |
| Neo4j login | `NEO4J_USER`/`NEO4J_PASSWORD` through `Config` | Same; disposable CI database only | PASS |
| CLI/stdio bearer | `HIPPO_TOKEN` | Preserve for local transports | PASS |
| HTTP bearer | Per-request header, currently with unsafe MCP environment fallback | Remove HTTP fallback; keep caller-local identity | PASS, implementation pending |
| Browser signing secret | Generated once and persisted under Settings `session_secret`; cached in process (`web/auth.py:58–69`) | Preserve stored metadata through migration/reopen; never replace with an environment default | Add explicit fixture coverage |
| User password hashes/caller tokens | Stored User properties plus role and disabled state (`store/users.py:210–250`) | Preserve exact stored values, role relations and disabled state; verify login/session/token continuity | Add explicit fixture coverage |
| GitHub/GitLab/Jira/Tuleap/Backstage credentials | New integrations, no existing credential source inspected | Referenced environment/secret-file/provider adapter; origin scoped; sanitized failures; expiration/rotation handled | PASS design; live reads pending |
| Enterprise CA/proxy | New optional configuration | Preserve TLS verification and origin-scoped proxy/auth configuration | PASS design; deployment topology pending |

**Required correction F1 (Task 3):** Extend the populated v1 migration fixture beyond source roles to an actual user, password hash, bearer token, browser signing secret, role assignments and disabled state. Verify an existing token and session remain valid after migrate/reopen for an enabled user, and a disabled user remains denied. Plan section 11.2 does not enumerate these stored sources explicitly. This is an omission to resolve, not evidence of a performed credential downgrade.

Live source credentials are not required for Tasks 0–9A or recorded-response providers. A live adapter cannot be promoted on mocked tests alone; missing credentials are recorded as skipped/unreleased for that integration. No token values were read or logged by this review.

## G. Gate ledger and verification discipline

The plan has an inline ledger, not `ai_docs/gates/.../GATES.md`. The dev-execute skill explicitly permits its verification-gate fallback when no standalone ledger exists. Therefore `gate-check.mjs --status/--approve` was not run against a nonexistent file, and no bound-oracle approval is claimed.

At the end of this review the root created `ai_docs/gates/rag-it-all/task-0/GATES.md`. I read it and ran `node /Users/mascott/.agents/skills/dev-gates/scripts/gate-check.mjs --status ai_docs/gates/rag-it-all/task-0/GATES.md --root .`; it parses with G0, G0B and G0R pending/unmet. G0 names the Task 0-created smoke test; G0B and G0R are evidence-only checks. No test-oracle approval or passing result is claimed here. The root will review exact implemented checks before approval/execution. The inline inventory below records the earlier inspection point.

A read-only Python inspection found:

- 21 inline gate rows, 21 unique IDs (`G0`–`G20`).
- No referenced `G<n>` absent from the table.
- Every named release/smoke/capability/restore/benchmark script has an explicit creation task.
- Optional E1–E5 test files have explicit ownership.
- No standalone `GATES.md` under `ai_docs` at review time.

**WARN — inline commands are not all directly runnable oracle strings.** G0 refers to “Existing fake/Ladybug tests and Ruff commands”; G3 says “on all three stores”; G17 refers to other commands; G20 uses `NAME`. Expand these to exact reviewed commands in the execution checkpoint, using `.venv/bin/python` and explicit `HIPPO_TEST_STORE` values. If a standalone ledger is later created, give each optional experiment its own exact command and reject duplicate/overlapping ownership in a concurrent batch.

No missing planned file is a passing test. Run fresh full commands after implementation and inspect failures/skips. Do not execute Neo4j tests unless the target is a disposable instance: `tests/conftest.py:190–201` deletes every node. Fake and Ladybug tests are independent of a live provider and must not be skipped merely because provider credentials are absent.

## Corrections to carry into execution

1. Tasks 2–4: define workspace/provider principal mapping and authorization fingerprint inputs.
2. Task 3: guard schema version before mutation; test stored user/session/token preservation.
3. Tasks 4–5: implement the protected legacy projection before managed records are visible; include global status metadata and all transport renderers.
4. Task 5: route existing source reindex/delete/bulk-reindex entry points safely for managed generations; retain legacy behavior for legacy sources.
5. Tasks 9A/15: register scheduler shutdown and routers in the existing lifespan/mount order.
6. Every task: preserve exact fresh verification evidence; a gate remains pending until its actual checks run.

The plan's proposed model, lifecycle and retrieval split is technically coherent with the current project. These corrections make its existing invariants concrete at repository seams where partial implementation would otherwise bypass them.
