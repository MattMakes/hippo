# Brief: fix Task 5A integration part 1 after independent review

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `t5a1fix` (branch `wp/t5a1fix`, base `043ca51`, the current `rag-it-all-tibs` HEAD).

GOAL: Resolve every finding in `ai_docs/reports/2026-09-11-t5a-int1-review.md` (F1–F10) according to the decisions below, RED-first, so the history-selection slice is atomic, audience-correct and pins every selector mode. Committed on `wp/t5a1fix`.

CONTEXT:
- Contract: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` sections 4 and 6 with amendments. Implementer evidence: `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-int1.md`. Review report: read all of it; each finding has file:line, reproduction and a proposed fix. Reproduction scripts `/tmp/t5a1_repro.py`, `/tmp/t5a1_repro2.py` (may be gone; their output is in the report).
- Code under fix: `src/hippo/knowledge/temporal.py` (`select_history` ~:512-583, `pinned_selector` ~:409-421, `history_access`), `src/hippo/knowledge/snapshots.py` (`acquire_history_snapshot` ~:226-230), `src/hippo/store/snapshots.py` (`purged_history_evidence`, `_purged_revisions` inside `_collection_block`), `src/hippo/knowledge/model.py` (selectors, `validate_knowledge_cutoff` ~:1272), `src/hippo/store/authorization.py` (record classification ~:130-154). Pattern to copy for atomic acquisition: the sibling `acquire_*` functions and `_reader_proof` (~:687-694) in `snapshots.py`.

DECISIONS (final):
- F1 (blocker): `acquire_history_snapshot` rebuilds the proof for the CALLER's audience via `history_access(store, manifest.workspace_id, access, clock=clock).build(history.selection)`, keeps the epoch check, and additionally requires every manifest ID to be a subset of that proof's IDs; the bundle's proof, policy fingerprint, validation and expiry clock all belong to the caller. RED: the report's bystander scenario (internal 3-span proof versus a 2-span audience) must fail validation before the fix.
- F2 (blocker): `select_history` performs its reads, closure computation and `put_knowledge` inside ONE `store.transaction()` with no callbacks, model calls or clock reads other than the injected clock inside it; the containment check becomes manifest IDs subset of proof IDs and runs BEFORE the put; add the broad/proof epoch cross-check exactly as `_reader_proof` does. RED on Fake can only prove ordering and the inverted check (Fake is single-threaded); write those tests and state the concurrency argument in the evidence.
- F3 (major): extend `CurrentSelector` and `AtemporalSelector` in `model.py` with an optional `known_at: datetime | None = None` (None means latest available knowledge) so `pinned_selector` binds the resolved cutoff for all six modes; `validate_knowledge_cutoff` must cover them; re-resolving a pinned selector at a later cutoff returns the pinned instant for every mode. RED: the report's current/atemporal re-resolution case. Amend the plan section 4 note and evidence-int1.md Decision 1 to state the real rule.
- F4 (major): in `store/authorization.py`, classify `HistoryManifest` and `ConflictSet` as bookkeeping exactly like `QuerySnapshot`/`SnapshotReference` (~:152-154) so a historical read is not fenced by a build lease and does not bump `content_epoch`; you own that file for this change only. RED: `select_history` under a live rebuild raises before, succeeds after; a history read leaves `content_epoch` unchanged; persisting a `ConflictSet` on a read path likewise. Confirm no other read-path record shares the misclassification (`LIST_REFERENCES` walk) and list what you checked.
- F5: `compare` remains unimplemented in this slice but the test name and docstring must say "rejected in part 1", not "accepted".
- F6: compute the purged-revision set once per collection pass, not once per live `SnapshotReference`.
- F7: `history_access` reuses `_reader_proof`'s helper instead of duplicating it (factor a private function; behavior identical).
- F8: an authorized audience with zero retained rows receives an empty manifest (proven 0, contextual 0) with no `history_unavailable` code; that code is reserved for a cutoff earlier than the earliest retained recorded interval among the audience's authorized rows.
- F9: `purged_history_evidence(manifest_id, *, workspace_id, access)` scopes its answer to the caller's workspace and audience; unauthorized callers get the same empty answer as a nonexistent manifest.
- F10: fix the doc drift the report lists.

FILES:
  - own: `src/hippo/knowledge/temporal.py`, `src/hippo/knowledge/snapshots.py`, `src/hippo/knowledge/model.py` (selector fields and cutoff validation only), `src/hippo/store/snapshots.py`, `src/hippo/store/authorization.py` (classification only), `tests/unit/test_temporal_evidence.py`, `tests/unit/test_snapshot_store.py`, `tests/unit/test_knowledge_contracts.py`, `tests/unit/test_evidence_epochs.py` (only if the content_epoch assertion lives there), `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` (section 4 note), `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-int1.md` (append "Fixes after review" and correct Decision 1), EVIDENCE lines for T5A3/T5A4 in the ledger.
  - do NOT touch: `src/hippo/knowledge/conflicts.py`, `access.py` (unless F7's factoring genuinely needs one import; say so), `lifecycle.py`, `query_access.py`, `ask.py` (another worker), `src/hippo/ingest/*` (another worker), `src/hippo/store/{generations,knowledge,ladybug,migrations}.py`, `tests/fakes/fake_store.py` unless a store method you change has a Fake mirror there (then mirror only), `docs/`, the checkpoint, checkboxes.

STEPS:
1. Worktree + venv per the rulebook (with the `mcp==2.1.1` pin). Baseline green: T5A1, T5A2, T5A3, T5A5, T5A6 from the ledger plus `tests/unit/test_snapshot_store.py tests/unit/test_query_snapshots.py tests/unit/test_evidence_access.py tests/unit/test_evidence_epochs.py` on Fake.
2. RED for F1, F2, F3, F4, F8, F9; save `/tmp/hippo-t5a1fix-red.log`.
3. Implement F1–F10 in the order F4, F2, F1, F3, then the minors.
4. GREEN Fake: the baseline set plus `tests/unit/test_generation_store.py tests/unit/test_managed_source_lifecycle.py tests/unit/test_managed_source_inventory.py tests/unit/test_build_authority.py`. Log `/tmp/hippo-t5a1fix-fake-green.log`.
5. GREEN Ladybug: T5A4 plus `tests/unit/test_snapshot_store.py tests/unit/test_query_snapshots.py tests/unit/test_evidence_epochs.py`. Log `/tmp/hippo-t5a1fix-ladybug-green.log`.
6. Ruff check + format (T5A6 command); append the evidence; commit on `wp/t5a1fix` in two or three commits.

DONE WHEN: steps 4–6 green with `-W error`; RED log saved; plan and evidence amended; commits on `wp/t5a1fix`; `horch done` lists per finding what changed (file:line), tests added, counts per backend with log paths, and the list of record classes you checked for F4.

OUT OF SCOPE: part 2 (publication plan, closure, fixture loader, N2); Neo4j runs.

REPORT: `horch note` per step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for any conflict with these decisions; wait.
