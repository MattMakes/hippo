# Brief: independent design review of the managed code-capture plan

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`), read-only except your report. No code, no tests; you may run read-only probes under `/tmp`.

GOAL: Judge `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` (with its "Orchestrator rulings" section) against the master plan and the existing seams before the fleet builds it. Two tasks (CC1 legacy serving, CC4 capture/provenance) start in parallel with you; your findings bind CC2–CC11.

CONTEXT: `docs/rag_it_all.md` (Task 5, sections 5.2, 5.3, 5.5, 7.5–7.9, Task 12, Task 6 boundary), `docs/rag_it_all_remaining_tasks.md`; the prose lane contracts (`ai_docs/plans/rag-it-all-task-5-prose-coordinator.md`, `-production-activation.md`, `-storage.md`, `-derived-evidence.md`, `-dense-dispatch.md`); the checkpoint `ai_docs/checkpoints/2026-09-11-execution-state.md`; the proposed ledger `ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`; the code the plan cites (`src/hippo/store/generations.py`, `snapshots.py`, `src/hippo/context.py`, `status.py`, `src/hippo/codegraph/*`, `src/hippo/ingest/{pipeline,repos,readers,prose_generation,managed_activation}.py`, `src/hippo/knowledge/{staged_prose,input_binding,build_authority,projection,dense}.py`, `src/hippo/hipporag/indexer.py`).

QUESTIONS TO ANSWER (each with file:line evidence):
1. Blocker A: is the legacy-serving predicate (`source_serves_legacy`: managed false, no active pointer, no published IndexEvent) sufficient and safe? Can a staged-only source be read through any current path the plan does not name (status counts, MCP source lists, eval access, changeset access, snapshots)? Does moving `begin_managed_source` into the publication transaction break any reviewed prose invariant (the coordinator's own tests must still pass unchanged)?
2. Blocker B: does `reclaim_generation_build` (manifest-equality, no collection, fresh fence) preserve every reviewed guarantee of `claim_generation_build`, `recover_generation_builds`, `fail_generation_build` and the tombstone barrier? Can a reclaim resurrect a tombstoned source or reuse a lease across a suppression?
3. Scale: are the proposed generation-scoped reads sufficient for `native_write`, `native_mutation` and `generation_checksums` to be linear in the generation on Neo4j and Ladybug, and can the checksums stay byte-identical to today's for existing generations?
4. Resume by probing the store's own rows: can a partially written batch group be mistaken for complete (identical IDs, different payload; a relation group whose endpoint group was written by a *different* attempt)?
5. `rebaseline()` under the orchestrator's conditions: enumerate what an attacker with a role change can and cannot achieve between batches.
6. Temporal fields (§9): do the commit-derived `valid_from`/`source_updated_at`/`recorded_from` choices agree with Task 5A's rules (no wall-clock defaults, precision preserved, recorded independent of effective)?
7. Identity (§5): generation identity inputs (commit SHA, walker/grammar versions, config) and the namespace rule; can two generations of the same repository at the same commit but different walker versions collide or wrongly dedupe?
8. Privacy (§10): paths, code text, model I/O boundaries, logs.
9. Split (§12): are the exclusive-file boundaries real (grep for shared helpers the tasks would both edit), is any task larger than the fleet budget, and are the dependencies complete?
10. Ledger: are CD1–CD10's CHECK lines runnable as written once the named test files exist, with EXPECT matching pytest/Ruff output verbatim?

FILES:
  - own: `ai_docs/reports/2026-09-12-code-capture-plan-review.md`.
  - do NOT touch: anything else.

DONE WHEN: the report exists with `DESIGN: APPROVED | APPROVED WITH CHANGES | REJECTED`, numbered findings with severity (blocker / major / minor), the section and line each binds, and a proposed amendment for each; plus a one-line note per task CC1–CC11 saying "unchanged" or "amend before spawn". `horch done` states the verdict and the counts.

CONSTRAINTS: read-only; no Neo4j.

REPORT: `horch note` after reading, after questions 1–5, after the report.
