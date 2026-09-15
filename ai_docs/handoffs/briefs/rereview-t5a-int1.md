# Brief: re-review the Task 5A integration part 1 fixes

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`). The fixes are merged at HEAD (merge commit "Merge wp/t5a1fix", branch commits `babe0b7`, `5fc3b8c`, `f077b9c`, `6a11ea3`, `f340a05`, `18cc610` on top of `043ca51`). You read and run; you do not edit source or tests.

GOAL: Confirm that every finding F1–F10 of `ai_docs/reports/2026-09-11-t5a-int1-review.md` is resolved exactly per the orchestrator's decisions in `ai_docs/handoffs/briefs/fix-t5a-int1.md`, and that the identity carve-out the F3 fix required is safe.

CONTEXT:
- Fixer's report: `ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-int1.md` ("Fixes after review" section) and its done summary, which states: F1 caller proof via `history_access(...).build(history.selection)` plus `proof_covers_manifest` (`knowledge/snapshots.py:236-241`); F2 one `store.transaction()` around reads, closure and put with manifest-subset-of-proof before the write and both proofs matched to the start epoch (`temporal.py:556-615`); F3 `CurrentSelector`/`AtemporalSelector.known_at` with unconditional pinning; F4 `HistoryManifest` and `ConflictSet` reclassified as bookkeeping (`store/authorization.py:143-161`) after auditing every record class reachable by the `REFERENCES`/`LIST_REFERENCES` walk; F5 rename; F6 purge set resolved once per collection pass; F7 `history_access` reuses `store._reviewed_mapping_authorities()` while `_reader_proof` keeps an inline copy (store/knowledge.py out of scope); F8 `history_unavailable` only when an earliest interval exists and the cutoff precedes it; F9 `purged_history_evidence(manifest_id, *, workspace_id, access)` raising the same `SnapshotUnavailable` for unknown, foreign and unprovable, with the gate manifest-minus-purged; F10 docs. Plus the orchestrator-ruled carve-out: `Record.identity_parts` omits a null `known_at` at any depth (`model.py:115-143`) so pre-change `QuerySnapshot` identities stay byte-identical; proven with a captured 043ca51 JSON.
- Residuals the fixer declared: when every manifest revision is purged the F9 audience gate is vacuous (a caller holding the manifest ID learns which revisions it named); F2's concurrency claim is structural; T5A3/T5A4 remain partial pending `recorded_correction` (part 2).

FILES:
  - own: `ai_docs/reports/2026-09-11-t5a-int1-rereview.md`.
  - do NOT touch: anything else (four activation workers and Task 3b are live in worktrees; nothing else is live in the root tree).

STEPS:
1. Run, each to `/tmp/hippo-t5a1-rereview-<gate>.log` with `echo EXIT $?`: T5A1, T5A2, T5A3, T5A5, T5A6 (Fake) and T5A4 (Ladybug) verbatim from the ledger, plus `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_snapshot_store.py tests/unit/test_query_snapshots.py tests/unit/test_evidence_epochs.py tests/unit/test_query_session.py tests/unit/test_managed_route_activation.py tests/unit/test_managed_source_inventory.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`.
2. For each of F1–F10 and the carve-out: CORRECT / INCOMPLETE / WRONG with file:line and the test that proves it. Specifically verify: (a) the bystander scenario from the original report now fails validation and the caller's proof governs expiry and fingerprint; (b) inside `select_history`, no callback, model call or uncontrolled clock runs within the transaction, and a proof narrowed between the two reads raises without a row; (c) all six selector modes pin and replay to the same instant; (d) the carve-out changes no identity of any record class other than the six selector-bearing ones, and a `known_at` that is SET still changes the identity (grep every `identity_fields` that embeds a selector); (e) the F4 audit: independently re-walk `REFERENCES`/`LIST_REFERENCES` and confirm only the two read-path records moved, and that `content_epoch` is unchanged by a history read; (f) F9's residual: state whether the all-purged case leaks anything beyond what the manifest ID's holder already knew.
3. Write the report: `RE-REVIEW: PASS|FAIL`, the table, any new findings with severity and proposed fix, run results with log paths.

DONE WHEN: the report exists; `horch done` states the verdict, any new findings by severity, and the report path.

CONSTRAINTS: no edits outside your report; no Neo4j; `HIPPO_TEST_STORE` explicit on every command.

REPORT: `horch note` after the runs and after the report.
