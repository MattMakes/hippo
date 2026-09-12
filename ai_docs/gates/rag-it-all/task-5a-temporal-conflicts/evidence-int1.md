# Task 5A integration part 1 — authorized history selection, manifests, snapshot pinning

Worker `opus-6`, branch `wp/t5a1`, base `158ebf2`. Contract:
`ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` sections 1, 4, 6, 8 including the
`Amended 2026-09-11 in integration part 1` notes this worker added.

Scope delivered: plan section 4 plus the section 6 shared-file changes it needs, and the
re-review minor N1. Section 5 (atomic correction publication), the fixture loader and N2
are part 2 and are NOT delivered here.

## Signatures

```python
# src/hippo/knowledge/temporal.py
select_history(store, *, workspace_id: str, access, selector: k.TemporalSelector,
               request_cutoff: datetime, clock=utc_now) -> HistorySelection
pinned_selector(resolved: ResolvedTemporalSelector) -> k.TemporalSelector
history_access(store, workspace_id: str, access, *, clock=utc_now) -> EvidenceAccess

@dataclass(frozen=True) HistoryDecision(record_id, record_kind, recorded_reason, match)
@dataclass(frozen=True) HistorySelection(manifest, selector, resolved, selection, decisions,
                                         resolver, broad, proof)
    .proven / .contextual / .excluded -> tuple[HistoryDecision, ...]
    .coverage -> dict     .codes -> tuple[HistoryCoverageCode, ...]
ResolvedTemporalSelector(selector, known_at, known_at_source, latest_known_at,
                         inherited_from=None)   # inherited_from is new (N1)

# src/hippo/knowledge/access.py
EvidenceAccess.build_history(selection: EvidenceSelection | None = None) -> AuthorizedEvidence

# src/hippo/knowledge/snapshots.py
acquire_history_snapshot(store, access, *, history: HistorySelection,
                         settings_fingerprint: str,
                         lease_duration=timedelta(minutes=5), clock=utc_now) -> QuerySnapshotBundle

# src/hippo/store/snapshots.py
SnapshotQueries.purged_history_evidence(manifest_id, *, workspace_id: str,
                                         access) -> tuple[PurgedEvidence, ...]   # scoped after review
@dataclass(frozen=True) PurgedEvidence(target_kind, target_id, code="evidence_purged")
```

## Behavior to test map (plan section 4 order)

| # | Behavior | Test |
|---|---|---|
| 1 | Selector resolved against the injected cutoff; compare rejected | `test_history_manifest_rejects_a_compare_selector_and_asks_for_one_manifest_per_side` (renamed after review, F5) |
| 2 | Broad `query_mode="history"` proof first; `current_only` tombstone leaves history | `test_suppression_history_keeps_a_current_only_tombstone_selectable`, `test_history_manifest_keeps_current_policy_mandatory` |
| 3 | Predicates applied only to authorized rows; `recorded_match`; contextual inventory | `test_history_manifest_separates_contextual_inventory_from_proven_evidence`, `test_history_manifest_never_adds_an_id_outside_the_authorization_proof` |
| 4 | Exact revision closure, compatible link generations, retention gaps | `test_history_manifest_includes_only_compatible_link_generations`, `test_history_manifest_records_a_retention_gap_without_fabricating_revisions` |
| 5 | Canonical persisted manifest, exact selector, cutoff, coverage codes | `test_history_manifest_selects_retired_evidence_at_a_fixed_knowledge_cutoff`, `test_history_manifest_reports_history_unavailable_before_the_earliest_interval` |
| 6 | Final selection, snapshot pin, revalidation before dispatch and release | `test_history_manifest_pins_a_query_snapshot_and_releases_its_reference`, `test_history_manifest_and_its_pin_survive_ladybug_reopen` |
| 7 | History collection roots; purge overrides them; access loss/purge denies an old snapshot | `test_purge_history_overrides_retained_snapshot_roots`, `test_suppression_history_denies_an_old_snapshot_after_all_history_access_loss` |
| 8 | Canonical sorted/unique `HistoryManifest` and `ConflictSet` validation | `test_history_manifest_requires_sorted_unique_ids_and_keeps_open_selectors`, `test_conflict_set_requires_sorted_unique_ids_and_a_proven_lower_bound` |
| 9 | N1 origin labels | `test_resolved_selector_rejects_origin_labels_its_own_data_contradicts` |

## Commands and results

RED log `/tmp/hippo-t5a1-red.log` (written before any implementation):
`ImportError: cannot import name 'select_history'` for the 14 new store-backed tests plus the
N1 test, and `2 failed, 91 passed` for the two model-validation tests run alone.

GREEN Fake, log `/tmp/hippo-t5a1-fake-green.log`, every command `exit=0`:

- T5A1 `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_temporal_evidence.py -q -o addopts='' -W error` -> `35 passed`
- T5A2 `... tests/unit/test_temporal_conflicts.py ...` -> `30 passed`
- T5A3 `... tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py -k 'history_manifest or recorded_correction or suppression_history or purge_history' ...` -> `12 passed, 53 deselected`
- T5A5 `... test_knowledge_contracts.py test_store_knowledge.py test_evidence_access.py test_generation_store.py test_snapshot_store.py test_generation_graph_loader.py ...` -> `209 passed, 1 skipped`
- Extra `... test_snapshot_store.py test_query_snapshots.py test_evidence_access.py test_knowledge_contracts.py test_generation_store.py test_managed_source_lifecycle.py test_managed_source_inventory.py ...` -> `234 passed, 1 skipped`

GREEN Ladybug, log `/tmp/hippo-t5a1-ladybug-green.log`, every command `exit=0`:

- T5A4 `HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_temporal_evidence.py tests/unit/test_temporal_conflicts.py -k 'history_manifest or recorded_correction or suppression_history or purge_history' -q -o addopts='' -W error` -> `12 passed, 53 deselected`
- `... test_snapshot_store.py test_query_snapshots.py ...` -> `14 passed`
- `... test_temporal_evidence.py test_temporal_conflicts.py test_knowledge_contracts.py ...` -> `158 passed`

T5A6 Ruff, run over every file this worker changed (the ledger's four plus
`access.py`, `model.py`, `knowledge/snapshots.py`, `store/snapshots.py`,
`test_snapshot_store.py`, `test_knowledge_contracts.py`):
`ruff check` -> `All checks passed!`; `ruff format --check` -> `10 files already formatted`.

Warning handling: every run above used a bare `-W error`. No file this worker touched imports
`fastapi.testclient`, so neither sanctioned `BlockingPortal` form (a) nor (b) was needed and no
`filterwarnings` was added anywhere.

`recorded_correction` currently matches no test: it is the part 2 keyword for section 5's
atomic publication, so the T5A3/T5A4 `-k` filter selects only the `history_manifest`,
`suppression_history` and `purge_history` halves this brief owns.

## Files

Implementation: `src/hippo/knowledge/temporal.py`, `src/hippo/knowledge/access.py`,
`src/hippo/knowledge/model.py`, `src/hippo/knowledge/snapshots.py`, `src/hippo/store/snapshots.py`.
Tests: `tests/unit/test_temporal_evidence.py`, `tests/unit/test_knowledge_contracts.py`,
`tests/unit/test_snapshot_store.py`.
Docs: this file and the `Amended 2026-09-11 in integration part 1` notes in the plan.

Untouched, as the brief requires: `knowledge/conflicts.py`, `knowledge/lifecycle.py`,
`store/generations.py`, `store/knowledge.py`, `store/ladybug.py`, `store/migrations.py`,
`tests/fakes/fake_store.py`, `src/hippo/ingest/*`, `knowledge/query_access.py`, `context.py`,
`web/*`, `docs/`, the checkpoint. Schema 5 is unchanged: no column was added or retyped, and
`HistoryManifest.identity_fields` is a `ClassVar`, not storage.

## Decisions and deviations

1. **Manifest selector JSON is the pinned selector, not `selector_json`.** The brief asks for
   "the exact resolved `selector_json`". `ResolvedTemporalSelector.selector_json` pops `known_at`
   and adds `resolved_known_at`, which `HistoryManifest.selector_contract` cannot accept under
   `Contract`'s `extra="forbid"`. The manifest therefore stores the selector with its own
   `known_at` bound to the resolved cutoff, which `validate_knowledge_cutoff` proves equals
   `knowledge_cutoff`. `selector_json` keeps its reviewed audit/identity role unchanged.
   **Corrected 2026-09-11 after review (F3), on `wp/t5a1fix`.** As written this held for four of
   the six modes. `CurrentSelector` and `AtemporalSelector` had no `known_at` field, so
   `pinned_selector` was the identity function for them and `validate_knowledge_cutoff`
   short-circuited on `known_at is None` and proved nothing. Both selectors now carry
   `known_at: Instant | None = None`, `pinned_selector` binds the resolved cutoff unconditionally,
   and the agreement is proved for all six modes. `None` still means "the latest knowledge
   available", so an unpinned `CurrentSelector()` — including `acquire_query_snapshots`' own — is
   unchanged.
2. **`coverage_json` added to `HistoryManifest.identity_fields`.** Without it, two audiences that
   prove the same IDs from different inventories produce one ID with different contents and
   `put_knowledge` raises "Immutable record already exists with different contents". Coverage is
   part of what the manifest asserts, so it belongs in the identity.
3. **`TemporalInputs` carries only the record.** `observed_at`/`source_updated_at`/`published_at`
   are only consumed by the `changes` clocks; deriving them through support-group revisions is
   deferred to a later slice rather than guessed here. `None` is the honest value.
4. **History snapshots pin no generation.** `sources=()` and
   `profile_fingerprint="history:<manifest id>"` keep a history pin from claiming dense
   reachability or an active generation; the caller still supplies `settings_fingerprint`.
5. **`retention_gaps` holds revision IDs**, not codes; the stable code `retention_gap` lives in
   `coverage_json["codes"]`. Nothing invents a missing revision or date.
6. **N1 needed a new optional field.** "Rejects `inherited` without a compare parent" is not
   checkable from the record alone, as the re-review notes, so `ResolvedTemporalSelector` gained
   an optional `inherited_from` parent that `resolve_selector` supplies and that the constructor
   validates (cutoff matches, this side is the parent's `left` or `right`, no other origin
   carries one). Positional construction is unchanged for the first four arguments.
7. **One behavior in the brief reads differently than the fixture shows.** At a current cutoff the
   May-1 revision stays in the closure beside the May-10 correction, because only the ownership
   *assertion version* was closed; the May-1 *object observations* are still recorded-open. The
   test asserts this explicitly rather than asserting a revision-level retirement that no record
   claims.

## Open findings for root / part 2

These three were the implementer's findings at `043ca51`. Finding 1 is **resolved** below (F4);
findings 2 and 3 remain open and belong to the orchestrator and to part 2 respectively. The review
brief's "four findings" count included the "What part 2 still owes" paragraph, which is scope
rather than a finding — reconciled here, so the count is three.

1. **A historical read is fenced by a write lease it does not use.** `RECORD_EPOCHS`
   (`src/hippo/store/authorization.py:130`) classifies `HistoryManifest` as `content`, so
   `_check_knowledge_write` walks `_record_revisions` through the manifest's `revision_ids` to the
   source and demands build authority whenever that source has a running rebuild. Verified: with a
   claimed rebuild on the source, `select_history` raises
   `ValueError: Managed evidence write requires build authority`. Every test world here is fully
   published before selection, so nothing in this slice hits it, but a production history query
   concurrent with a rebuild would fail. `store/authorization.py` is outside this brief's
   ownership; the suggested fix is reclassifying `HistoryManifest` as `bookkeeping`, since it
   names evidence rather than being evidence. Root or part 2 should decide.
2. **T5A6's CHECK line is narrower than this slice.** It still lists only the four pure-module
   files. The orchestrator should widen it to also cover `src/hippo/knowledge/access.py`,
   `src/hippo/knowledge/model.py`, `src/hippo/knowledge/snapshots.py`,
   `src/hippo/store/snapshots.py`, `tests/unit/test_snapshot_store.py` and
   `tests/unit/test_knowledge_contracts.py`. All ten are Ruff clean today.
3. **"Revalidate before release" is inherited, not added here.** `QuerySnapshotBundle.close()`
   releases its references without rechecking authorization; that is the reviewed pre-existing
   behavior and this slice did not change it. Part 2 should not assume a release-time recheck
   exists. Revalidation before each *dispatch* is covered by `validate()`, which this slice does
   exercise for history pins.

## What part 2 still owes

`recorded_correction` (section 5 `TemporalPublicationPlan` and `publish_staged_generation`
closure, with failpoint rollback and idempotent retry), `tests/fixtures/rag_all/temporal_events.jsonl`
chronological fixture loading, and re-review minor N2 (`superseded_version_ids` repeating an ID
within one series). Root still owes the disposable-Neo4j repeat of T5A3.

## Fixes after review (worker `opus-7`, branch `wp/t5a1fix`, base `043ca51`)

Every finding in `ai_docs/reports/2026-09-11-t5a-int1-review.md` is resolved here, RED first, under
the decisions in `ai_docs/handoffs/briefs/fix-t5a-int1.md`.

| # | Resolution | Where |
|---|---|---|
| F1 | `acquire_history_snapshot` rebuilds the proof for the CALLER: `history_access(store, manifest.workspace_id, access, clock=clock).build(history.selection)`, keeps the epoch check, and additionally requires the rebuilt proof to cover the manifest. The bundle stores that resolver, so every later `validate()` and every expiry check uses the caller's audience and the caller's clock. | `knowledge/snapshots.py:236-241` |
| F2 | `select_history` runs the epoch read, both proofs, every row/scan read, the closure and the write inside one `store.transaction()`. Containment is `manifest ⊆ proof` **before** `put_knowledge`, the old `proof ⊆ broad` direction is kept beside it, and both proofs must carry the epoch captured at the start. | `knowledge/temporal.py:556-615`, `proof_covers_manifest` at `:502` |
| F3 | `CurrentSelector` and `AtemporalSelector` gained `known_at: Instant | None = None`; `pinned_selector` binds the resolved cutoff unconditionally; `validate_knowledge_cutoff` now proves the agreement for all six modes. Plan section 4 note and Decision 1 above corrected. | `knowledge/model.py:1206,1238`, `knowledge/temporal.py:409-421` |
| F4 | `HistoryManifest` and `ConflictSet` moved to `bookkeeping`, beside `QuerySnapshot`/`SnapshotReference`. A historical read is no longer fenced by a running rebuild's build lease and no longer advances `content_epoch`. | `store/authorization.py:143-161` |
| F5 | The compare test is renamed `..._rejects_a_compare_selector_and_asks_for_one_manifest_per_side`, documents that both fixture sides *are* pinned, and asserts the remedy in the error text. No behavior change. | `tests/unit/test_temporal_evidence.py` |
| F6 | The generation's `GenerationMember` scan and the purge barrier are resolved once per collection pass (the barrier cached per workspace, since one pass can span workspaces) and only when a durable history pin actually asks. `_snapshot_reaches` became `_history_reaches`; the `sources` fast path moved into the loop, so a pass with no history pin does no extra scan at all. | `store/snapshots.py:207-251` |
| F7 | `history_access` calls `store._reviewed_mapping_authorities()` instead of repeating its six lines. **Deviation from the report's proposed fix:** it suggested adding `clock=None` to `_reader_proof`, but `store/knowledge.py` is outside this brief's ownership, so `_reader_proof` keeps its own inline copy and only the duplicate introduced by this slice is gone. | `knowledge/temporal.py:424-436` |
| F8 | `unavailable = earliest is not None and resolved.known_at < earliest`. An authorized audience with zero retained rows gets an empty manifest, proven 0 / contextual 0, and no code. | `knowledge/temporal.py:566` |
| F9 | `purged_history_evidence(manifest_id, *, workspace_id, access)`. Per the orchestrator's decision, an unknown manifest, a foreign workspace and an audience that cannot prove the manifest all raise the same `SnapshotUnavailable`, so the markers are no oracle and existing raise-on-unknown behavior is unchanged. The gate is the manifest's revisions **minus** the purged ones: a purge removes exactly the rows the markers describe from every proof, so `manifest ⊆ proof` would deny precisely when markers exist. Residual, recorded deliberately: when *every* manifest revision is purged the gate is vacuous, so any caller holding that manifest ID learns which revisions it named — the ID is itself derived from those contents. A request path exposing markers must still audience-check first. | `store/snapshots.py:174-205` |
| F10 | Decision 1 corrected above; the open-findings count reconciled to three (the fourth item was scope); the plan section 4 note amended. T5A6's stale EVIDENCE line and its CHECK line are the orchestrator's to refresh — the CHECK line should also cover `src/hippo/store/authorization.py` now. | this file, plan section 4 |

### F4: which other records could be misclassified

Walking `REFERENCES` + `LIST_REFERENCES` from every `content` record, these reach `ArtifactRevision`
and therefore walk the `_record_revisions` build-authority walk: `ArtifactRevision`, `EvidenceSpan`,
`ObjectObservation`, `AssertionSupport`, `NativeBinding`, `GenerationMember`, `DerivedRecord`,
`DerivedDependency`, `RetrievalView`, `ProseExtraction`, `Section`, `SectionMember`, `Alias`.
`Artifact`, `Assertion`, `AssertionVersion`, `KnowledgeObject`, `Generation`,
`GenerationEvidenceMember`, `IndexManifest` and `LinkGeneration` do not reach one. Every record in
both lists is written by ingestion, a generation build or a derivation pass, where holding the
lease is exactly right; none is written by a read path. `HistoryManifest` and `ConflictSet` were
the only two a query writes, which is why only they moved. (The review named `LinkGeneration` as
revision-reachable; by the reference walk it is not — it reaches `AssertionVersion` only. It stays
`content` either way, as a linker output.)

### F2: what the RED tests prove, and what they cannot

Fake and Ladybug are single-threaded, so no test here observes a real interleaving. What is proved
behaviorally: the manifest is written while the calling thread holds the store transaction
(`in_ambient_transaction()` probed from a patched `put_knowledge`), and a proof that narrows
between the broad build and the final one now raises *and* leaves no row, where before the
containment check was satisfied by any narrowing (`∅ ⊆ broad`) and ran after the write anyway. The
concurrency claim itself — that a publication or collection interleaved with these five formerly
independent read/write windows cannot produce an unsupported manifest — follows from the structure:
one transaction, one epoch captured at its start, both proofs checked against it, and the only
write last. Neo4j transaction parity remains root's separate evidence (plan section 8).

### Commands and results (worktree `.worktrees/t5a1fix`, branch `wp/t5a1fix`)

RED `/tmp/hippo-t5a1fix-red.log`, written before any implementation: `14 failed, 135 passed`
(`tests/unit/test_temporal_evidence.py tests/unit/test_knowledge_contracts.py
tests/unit/test_snapshot_store.py`, `HIPPO_TEST_STORE=fake`). The failures are exactly F1's
audience assertion, F2's ordering/containment/epoch cases, F3's model round-trip, F4's build-lease
and content-epoch cases, F8's empty-audience code and F9's new signature.

GREEN Fake, log `/tmp/hippo-t5a1fix-fake-green.log`, every command `exit=0`:

- T5A1 `tests/unit/test_temporal_evidence.py` -> `46 passed` (was 35)
- T5A2 `tests/unit/test_temporal_conflicts.py` -> `30 passed`
- T5A3 `-k 'history_manifest or recorded_correction or suppression_history or purge_history'` -> `23 passed, 53 deselected` (was 12; `recorded_correction` still matches nothing, it is part 2)
- T5A5 `test_knowledge_contracts.py test_store_knowledge.py test_evidence_access.py test_generation_store.py test_snapshot_store.py test_generation_graph_loader.py` -> `210 passed, 1 skipped`
- Extra `test_snapshot_store.py test_query_snapshots.py test_evidence_access.py test_evidence_epochs.py test_generation_store.py test_managed_source_lifecycle.py test_managed_source_inventory.py test_build_authority.py` -> `201 passed, 1 skipped`
- Collateral check for the shared model/classification changes, `/tmp/hippo-t5a1fix-extra.log`: `test_rag_eval.py test_query_snapshot_service.py test_saved_snapshot_retention.py test_generation_profiles.py test_generation_failure.py test_generation_counts.py` -> `134 passed`

GREEN Ladybug, log `/tmp/hippo-t5a1fix-ladybug-green.log`, every command `exit=0`:

- T5A4 same `-k` filter -> `23 passed, 53 deselected` in 22.89s
- `test_snapshot_store.py test_query_snapshots.py test_evidence_epochs.py` -> `30 passed` in 15.96s

Ruff over all eleven files (the ledger's ten plus `src/hippo/store/authorization.py`),
`/tmp/hippo-t5a1fix-ruff.log`: `ruff check` -> `All checks passed!`; `ruff format --check` ->
`11 files already formatted`.

Warning handling: every command above ran under a bare `-W error`. No file in these runs imports
`fastapi.testclient`, so neither sanctioned `BlockingPortal` form was needed and no
`filterwarnings` was added anywhere.

### Files changed by this fix

Implementation: `src/hippo/knowledge/temporal.py`, `src/hippo/knowledge/snapshots.py`,
`src/hippo/knowledge/model.py` (selector fields and the cutoff docstring only),
`src/hippo/store/snapshots.py`, `src/hippo/store/authorization.py` (classification only).
Tests: `tests/unit/test_temporal_evidence.py` (11 new cases, one renamed),
`tests/unit/test_knowledge_contracts.py` (one new case),
`tests/unit/test_snapshot_store.py` (new `purged_history_evidence` kwargs).
Docs: this file, the plan's section 4 notes, and the T5A3/T5A4 EVIDENCE lines in `GATES.md`.
Untouched: `knowledge/{conflicts,access,lifecycle,query_access,ask}.py`, `src/hippo/ingest/*`,
`store/{generations,knowledge,ladybug,migrations}.py`, `tests/fakes/fake_store.py`, `docs/`,
the checkpoint and every gate checkbox.
