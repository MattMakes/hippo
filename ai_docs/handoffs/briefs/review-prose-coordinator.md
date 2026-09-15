# Brief: independent SPEC/QUALITY review of the plain-prose coordinator

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`), not a worktree, because the files under review are uncommitted there.

GOAL: Produce an independent review verdict on the uncommitted plain-prose coordinator (`src/hippo/ingest/prose_generation.py`, `tests/unit/test_prose_generation.py`) against its approved contract, and run the one gate that has not been run (PC2, Ladybug). You read and run; you do not edit source or tests.

CONTEXT:
- Contract: `ai_docs/plans/rag-it-all-task-5-prose-coordinator.md`. Sections 4–9 are the binding requirements; section 10 lists gates PC1–PC8; the "Coordinator implementation notes" at the end record decisions the implementer made.
- Gate ledger: `ai_docs/gates/rag-it-all/task-5-prose-coordinator/GATES.md`. PC1, PC3, PC4 have evidence; PC2 (Ladybug) has none.
- The implementer was a Codex agent that no longer exists. The orchestrator has already confirmed on Fake: 59 passed, 1 skipped, Ruff clean. Your review is the independent SPEC/QUALITY step the project requires before this slice can be committed.
- The coordinator composes reviewed primitives; read them as needed to judge correct use: `src/hippo/knowledge/build_authority.py`, `src/hippo/knowledge/staged_prose.py`, `src/hippo/knowledge/prose_preparation.py`, `src/hippo/ingest/accepted_inputs.py`, `src/hippo/ingest/provenance.py`, `src/hippo/ingest/prepared_chunks.py`, `src/hippo/knowledge/input_binding.py`, `src/hippo/knowledge/lifecycle.py`, `src/hippo/store/generations.py`, `src/hippo/store/snapshots.py`, `src/hippo/knowledge/raw_artifacts.py`, `src/hippo/knowledge/embedding_profile.py`, `src/hippo/knowledge/openie_runtime.py` (or wherever `GuardedOpenIE` lives; find it with `rg`).
- The next slice (production activation, Task 3) will import `build_plain_source`, `PlainBuildOptions`, `BuildProgress`, `BuildReceipt`, `ByteInput`/`FileInput`/`ExcludedInput` from this module. The exact signatures matter.

FILES:
  - own (may create/modify): `ai_docs/reports/2026-09-11-prose-coordinator-review.md` (your report), and the EVIDENCE line under PC2 in `ai_docs/gates/rag-it-all/task-5-prose-coordinator/GATES.md`.
  - do NOT touch: anything else. If a defect needs a code change, describe it in the report; a separate worker will fix it.

STEPS:
1. Run the four gate commands from the ledger exactly as written, each captured to `/tmp/hippo-prose-review-pc<N>.log` with `echo EXIT $?`. PC2 is `HIPPO_TEST_STORE=ladybug ...` and takes minutes; start it first in the background with a log file, then continue reading. Record the PC2 result as an EVIDENCE line in the ledger (result line, log path); leave the checkbox unticked.
2. SPEC review. For each item below, locate the code and the test that proves it. Classify each as PROVEN (cite test name), UNTESTED (code exists, no test), or VIOLATED (cite file:line). Items:
   a. Entry captures authorization/suppression epochs BEFORE resolving live actor/source/workspace (plan §4).
   b. Source control descriptor excludes counts/progress/updated_at and is re-read at admission and publication (§4).
   c. Reader actor requires live enabled user, role, `may_manage_source`, enabled workspace membership; open/preview/synthetic actors rejected; trusted-local only from explicit call (§4).
   d. Local policy is exactly `AccessPolicy(origin='local_curated', scope_key='source:<id>:plain-prose-v1', mode='workspace')`; existing explicit policies reused, `legacy_unknown` never adopted (§4).
   e. Model resolution and all inference/file I/O happen outside store transactions; no callbacks under a lock (§5, §7 step 3).
   f. Descriptors sorted by normalized logical path before capture; existing Artifact/Revision reused whole, including observed-at (§5 steps 3–4).
   g. Manifest artifact `kind='manifest'`, external ID `accepted-inputs-v1`, metadata `{'accepted_manifest_v1': ...}`; manifest excludes itself (§5 step 5).
   h. Empty policy: empty inventory vs all-excluded vs empty originals distinguished; all-excluded rejected even with allow_empty (§5).
   i. Refresh: staging Generation inserted only after auth+source lock; renewal worker started outside the transaction; final publish transaction rechecks captured authorization epoch before AND after `publish_staged_generation`; legacy `publish_generation` never called (§6).
   j. Bootstrap: no Artifact/Generation/policy/managed flag persisted before the final transaction; one outer transaction installs policy, generation, managed flag, claims job, writes members, binds profile, writes batches via callback-free cores, publishes with parent None (§7).
   k. Bootstrap limits (1,000 chunks / 50,000 records / 64 MiB) enforced before the transaction with exact-at and one-over tests (§7).
   l. Idempotence: `already_current`, `already_published`, live-duplicate Busy, operation_id receipt replay validates job/owner/fence/seal; no lease revival (§8).
   m. Failure: heartbeat stop/join outside transactions; `fail_generation_build` used only by the holder; G1 never touched (§8).
   n. No raw deletion of any kind; no `_clear_passages`, `delete_passages_for_source`, `delete_code_for_source`, `remove_orphans`, `rmtree`, `discard_generation`, `store.delete_source` calls (§9). Verify with `rg` over the module.
   o. Receipt/logs/errors contain no source text, raw bytes, absolute paths, manifest JSON, prompts, model bodies or `str(exc)` of unknown exceptions (§3, §9).
3. QUALITY review: transaction-depth handling across threads (the notes say per-thread ownership is instrumented; check the production code does not rely on a test-only hook); sticky latch races; partial thread start; exception paths that could leave a claimed job without failure marking; duplicated logic that should call an existing primitive; any test that passes only because of a mock that bypasses the boundary it claims to test.
4. Record the actual public signatures of `build_plain_source`, `PlainBuildOptions` (all fields), `BuildReceipt`, `BuildProgress`, and the input types in the report verbatim.

DONE WHEN:
- `ai_docs/reports/2026-09-11-prose-coordinator-review.md` exists with: a one-line verdict `SPEC: PASS|FAIL`, `QUALITY: PASS|FAIL`; a table of items a–o with classification and citation; a numbered findings list, each with severity (blocker / major / minor), file:line, why it matters, and a proposed fix; the PC1–PC4 results with log paths; the verbatim public signatures.
- PC2 EVIDENCE line recorded in the ledger.
- `horch done` summary states the two verdicts, the number of blocker/major/minor findings, and the report path.

CONSTRAINTS: no source/test edits; no Neo4j; no full-suite run; do not start the dev server. Use `HIPPO_TEST_STORE` explicitly on every pytest command.

REPORT: `horch note` after PC2 starts, after the SPEC table is complete, and after the report is written. `horch tell orchestrator "[<role>] BLOCKED: ..."` only if a gate command cannot run at all.
