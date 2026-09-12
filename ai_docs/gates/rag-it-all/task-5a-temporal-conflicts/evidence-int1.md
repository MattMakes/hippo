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
SnapshotQueries.purged_history_evidence(manifest_id) -> tuple[PurgedEvidence, ...]
@dataclass(frozen=True) PurgedEvidence(target_kind, target_id, code="evidence_purged")
```

## Behavior to test map (plan section 4 order)

| # | Behavior | Test |
|---|---|---|
| 1 | Selector resolved against the injected cutoff; compare rejected | `test_history_manifest_rejects_a_compare_selector_without_pinned_sides` |
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

## What part 2 still owes

`recorded_correction` (section 5 `TemporalPublicationPlan` and `publish_staged_generation`
closure, with failpoint rollback and idempotent retry), `tests/fixtures/rag_all/temporal_events.jsonl`
chronological fixture loading, and re-review minor N2 (`superseded_version_ids` repeating an ID
within one series). Root still owes the disposable-Neo4j repeat of T5A3.
