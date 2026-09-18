# Brief: independent SPEC/QUALITY review of Task 5A integration part 1 (history selection, manifests, snapshot pinning)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`). The work under review is merged at HEAD `043ca51` (branch commits `859d1eb`, `049d582`, `de6edc4`, `043ca51` on top of `158ebf2`). You read and run; you do not edit source or tests.

GOAL: Independent SPEC and QUALITY verdict on plan section 4 and the section 6 shared-file changes it needed, before publication.

CONTEXT:
- Contract: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` sections 1, 4, 6, 8 including every "Amended 2026-09-11" note (two were added in this part: `coverage_json` is part of `HistoryManifest` identity; `temporal_selector_json` stores the pinned selector with `known_at` bound to the resolved cutoff). Orchestrator brief the implementer followed: `ai_docs/handoffs/briefs/t5a-int1-history-selection.md`. Implementer's evidence: `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-int1.md` (verify its claims; it also lists four open findings).
- Diff: `git diff 158ebf2..043ca51 -- src/ tests/` (8 files, ~1,000 lines). Signatures reported: `select_history(store, *, workspace_id, access, selector, request_cutoff, clock=utc_now) -> HistorySelection`; `HistoryDecision`; `pinned_selector`; `history_access`; `EvidenceAccess.build_history(selection)`; `acquire_history_snapshot(...) -> QuerySnapshotBundle`; `SnapshotQueries.purged_history_evidence(manifest_id)`; `ResolvedTemporalSelector.inherited_from`.
- Prior reviews for the pure modules: `ai_docs/reports/2026-09-11-temporal-pure-review.md`, `...-rereview.md`.

FILES:
  - own: `ai_docs/reports/2026-09-11-t5a-int1-review.md`.
  - do NOT touch: anything else (another worker owns `src/hippo/ingest/*` in a worktree; nothing else is live in the root tree).

STEPS:
1. Run, each to `/tmp/hippo-t5a1-review-<n>.log` with `echo EXIT $?`: (a) T5A1, T5A2, T5A3, T5A5, T5A6 commands verbatim from the ledger (Fake; T5A3 will deselect `recorded_correction`, note the counts); (b) T5A4 command (Ladybug); (c) `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_snapshot_store.py tests/unit/test_query_snapshots.py tests/unit/test_evidence_access.py tests/unit/test_generation_store.py tests/unit/test_managed_source_lifecycle.py tests/unit/test_managed_source_inventory.py tests/unit/test_dense_session.py tests/unit/test_query_session.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`; (d) the same (c) set on Ladybug minus `test_query_session.py`.
2. SPEC review; classify PROVEN (test name) / UNTESTED / VIOLATED (file:line):
   a. Selector resolved with the injected UTC cutoff; compare rejected unless two independently pinned sides; `known_at` label validation (N1) rejects `latest` with a differing cutoff and `inherited` without a parent.
   b. Broad proof built by `EvidenceAccess` in history mode BEFORE time filtering: live identity, membership, artifact policy, complete AND groups, `all_history` suppression; a `current_only` source tombstone leaves retained history visible; history never widens access (no ID outside the proof).
   c. Predicates applied only to authorized `ObjectObservation`/`AssertionVersion` rows; `recorded_match` emitted for recorded-eligibility decisions; unknown-time rows in a separate contextual inventory; `match_temporal` unchanged.
   d. Exact revision closure from selected observations and surviving complete support groups; only compatible retained link generations; retention gaps recorded, nothing fabricated.
   e. Manifest canonical: sorted unique IDs, pinned selector JSON validating as a `TemporalSelector`, cutoff, `coverage_json` with proven/contextual counts and only the stable codes; canonical JSON with sorted keys so identity is stable; no private text.
   f. `EvidenceSelection(query_mode="history")`, snapshot pins the manifest, current authorization and suppression revalidated before each dispatch; `history_unavailable` before the earliest retained interval; a stale proof after ACL loss denies.
   g. Collection roots include live and durable history snapshots; purge overrides roots and yields `evidence_purged` markers without text; Ladybug close/reopen preserves the manifest and its pin.
   h. Model validation for `HistoryManifest`/`ConflictSet` rejects unsorted/duplicate IDs and bad shapes, keeps unknown/open semantics, adds no provider-ordering or authority JSON fields; `recorded_to` remains the only mutable historical field; schema 5 unchanged.
3. QUALITY review, with attention to: whether `coverage_json` in identity can make two manifests for one audience differ across runs (nondeterministic counts or ordering); whether the pinned selector round-trips through `resolve_selector` to the same cutoff; the write-classification finding (`HistoryManifest` is `content` in `store/authorization.py:130`, so `select_history` raises under a live rebuild): confirm the reproduction and whether any other bookkeeping record shares the misclassification; transaction boundaries in `acquire_history_snapshot` (no callbacks inside); whether `purged_history_evidence` can leak a purged target's text or locator; whether the new `ClassVar` identity change silently alters any existing manifest fixture's ID in other tests; any `datetime.now`/`utc_now` default that a test could not control.
4. Report the verbatim public signatures for part 2.

DONE WHEN: `ai_docs/reports/2026-09-11-t5a-int1-review.md` exists with `SPEC: PASS|FAIL`, `QUALITY: PASS|FAIL`, the a–h table, numbered findings with severity (blocker / major / minor), file:line, why, proposed fix, the run results with log paths, and the signatures. `horch done` states both verdicts, finding counts by severity, and the report path.

CONSTRAINTS: no edits outside your report; no Neo4j; `HIPPO_TEST_STORE` explicit on every command.

REPORT: `horch note` after the runs, after the SPEC table, after the report.
