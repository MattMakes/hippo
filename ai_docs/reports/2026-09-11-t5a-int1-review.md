# Independent SPEC/QUALITY review — Task 5A integration part 1

Reviewer `architect-reviewer-5`, root tree, read-only except this file.
Under review: `158ebf2..043ca51` (`859d1eb`, `049d582`, `de6edc4`, `043ca51`), 8 files, 992 insertions.
Contract: `ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md` §1, §4, §6, §8 with every
`Amended 2026-09-11` note. Implementer evidence:
`ai_docs/gates/rag-it-all/task-5a-temporal-conflicts/evidence-int1.md`.

**SPEC: FAIL** — row (f) is VIOLATED: `acquire_history_snapshot` pins and revalidates the
*selection-time* audience while advertising an `access` parameter it only existence-checks.

**QUALITY: FAIL** — F1 (authorization fork) and F2 (`select_history` runs its whole
prove/read/persist sequence outside any transaction and never checks that the persisted
manifest is contained in a still-valid proof) are the two named T5A6 disqualifiers
"authorization fork" and "non-atomic closure".

Findings: **2 blocker, 2 major, 6 minor**. Everything the implementer's evidence claims about
test results reproduces exactly; two of its *narrative* claims do not (see F3, F9).

---

## 1. Run results

All eight commands exit 0. `HIPPO_TEST_STORE` explicit on every one. No Neo4j.

| # | Command | Log | Result |
|---|---|---|---|
| T5A1 | `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_temporal_evidence.py -q -o addopts='' -W error` | `/tmp/hippo-t5a1-review-1.log` | exit 0, **35 passed** |
| T5A2 | `HIPPO_TEST_STORE=fake ... tests/unit/test_temporal_conflicts.py ...` | `/tmp/hippo-t5a1-review-2.log` | exit 0, **30 passed** |
| T5A3 | `HIPPO_TEST_STORE=fake ... test_temporal_evidence.py test_temporal_conflicts.py -k 'history_manifest or recorded_correction or suppression_history or purge_history' ...` | `/tmp/hippo-t5a1-review-3.log` | exit 0, **12 passed, 53 deselected** |
| T5A4 | same `-k` filter, `HIPPO_TEST_STORE=ladybug` | `/tmp/hippo-t5a1-review-4.log` | exit 0, **12 passed, 53 deselected** in 11.73s |
| T5A5 | `HIPPO_TEST_STORE=fake ... test_knowledge_contracts.py test_store_knowledge.py test_evidence_access.py test_generation_store.py test_snapshot_store.py test_generation_graph_loader.py ...` | `/tmp/hippo-t5a1-review-5.log` | exit 0, **209 passed, 1 skipped** |
| T5A6 | `ruff check` + `ruff format --check` over the ledger's ten files | `/tmp/hippo-t5a1-review-6.log` | exit 0, `All checks passed!`, **10 files already formatted** |
| (c) | `HIPPO_TEST_STORE=fake .venv/bin/pytest test_snapshot_store.py test_query_snapshots.py test_evidence_access.py test_generation_store.py test_managed_source_lifecycle.py test_managed_source_inventory.py test_dense_session.py test_query_session.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` | `/tmp/hippo-t5a1-review-7.log` | exit 0, **211 passed, 1 skipped** |
| (d) | same set on `HIPPO_TEST_STORE=ladybug` minus `test_query_session.py` | `/tmp/hippo-t5a1-review-8.log` | exit 0, **174 passed** in 301.60s |

Notes on the runs:

- **T5A3/T5A4 counts.** `recorded_correction` matches no test at this HEAD; the 12 selected are
  the nine `history_manifest*`, two `suppression_history*` and one `purge_history*` case. The
  53 deselected are the pure `test_temporal_evidence.py`/`test_temporal_conflicts.py` bodies.
  The ledger's "partial" annotation is accurate; the gate cannot be closed on it.
- **Warning handling.** Form (b) (the sanctioned `BlockingPortal` command-line filter) was used
  only on runs (c) and (d), which include `test_query_session.py` / module-level
  `fastapi.testclient` importers. The six gate commands ran under bare `-W error`, exactly as the
  ledger CHECK lines are written. No `filterwarnings` was added anywhere.
- **Ledger drift (informational).** T5A5's recorded EVIDENCE line says `206 passed, 1 skipped`;
  the current tree gives `209 passed, 1 skipped`. That line predates this slice. Orchestrator's
  to refresh.
- `/tmp/hippo-t5a1-review-6.log` contains the `ruff format --check` result only; the `ruff check`
  half printed `All checks passed!` to the terminal because the brief's command redirects after
  the `&&`. Both halves exited 0.

## 2. SPEC table (plan §4 a–h)

| Row | Requirement | Verdict | Evidence |
|---|---|---|---|
| a | Selector resolved with injected UTC cutoff; compare rejected unless two independently pinned sides; N1 label validation | **PROVEN (partial)** | `test_resolved_selector_rejects_origin_labels_its_own_data_contradicts` covers N1 in all four directions (`latest` ≠ cutoff, `inherited` without parent, non-`inherited` with parent, side not in parent). Cutoff injection: `temporal.py:528`, proven by `test_history_manifest_selects_retired_evidence_at_a_fixed_knowledge_cutoff`. Compare **rejection** proven by `test_history_manifest_rejects_a_compare_selector_without_pinned_sides`. The plan's *acceptance* branch ("unless the caller requests two independently pinned sides") is **not implemented** — `temporal.py:529-530` rejects every `CompareSelector` unconditionally, including the fixture's two explicitly pinned sides. See **F5** (minor). |
| b | Broad `EvidenceAccess` history proof before time filtering; live identity, membership, artifact policy, complete AND groups, `all_history` suppression; `current_only` tombstone leaves history; history never widens access | **PROVEN (one gap)** | Ordering is structural: `temporal.py:532` builds the broad proof before `:533-534` decides anything. `build_history` (`access.py:544-555`) is a pure delegate that only pins `query_mode`, so no policy branch is duplicated. `test_suppression_history_keeps_a_current_only_tombstone_selectable` (retained history survives a `current_only` source tombstone while `build()` returns nothing), `test_history_manifest_keeps_current_policy_mandatory` (a restricted span is absent from a reader's decisions), `test_history_manifest_never_adds_an_id_outside_the_authorization_proof`. Pre-existing `test_evidence_access.py:377,391` proves the `current_only` / `all_history` split under `query_mode="history"`. **UNTESTED:** no test exercises a *multi-span complete AND group* under history mode — `history_world` builds only single-span `direct` groups, and the joint-group test (`test_evidence_access.py:319`) runs in current mode. Delegation makes this structurally safe; it is unproven. |
| c | Predicates only on authorized `ObjectObservation`/`AssertionVersion` rows; `recorded_match` emitted; unknown-time rows in a separate contextual inventory; `match_temporal` unchanged | **PROVEN** | `_authorized_temporal_rows` (`temporal.py:435-446`) iterates only `proof.observation_ids` / `proof.assertion_version_ids`. `test_history_manifest_never_adds_an_id_outside_the_authorization_proof` asserts `{decisions} ⊆ broad.observation_ids ∪ broad.assertion_version_ids`. `recorded_match` on `HistoryDecision.recorded_reason` proven by `test_history_manifest_separates_contextual_inventory_from_proven_evidence`; I re-derived the full inventory on the fixture: 4 rows `recorded_match`, 3 `recorded_after_cutoff`, 1 contextual `effective_unknown`+`recorded_match`. `match_temporal` is byte-for-byte unchanged in the diff — `_decide` (`temporal.py:448-451`) wraps it and never mutates the reason it returns except to translate a non-failure into `recorded_match`. |
| d | Exact revision closure from selected observations and surviving complete support groups; only compatible retained link generations; retention gaps recorded, nothing fabricated | **PROVEN** | `_revision_closure` (`temporal.py:453-471`) unions proven-observation revisions with proven-version support-span revisions and intersects with `proof.revision_ids`, so nothing can be invented. `_link_generations` (`:473-485`) admits a link only when `members ⊆ versions` and reports `link_coverage_incomplete` on a straddle — `test_history_manifest_includes_only_compatible_link_generations`. `_retention_gaps` (`:487-495`) reports selected revisions with no `active`/`retired` generation membership — `test_history_manifest_records_a_retention_gap_without_fabricating_revisions` collects the first generation, then asserts the revision stays in `revision_ids` *and* appears in `retention_gaps`. |
| e | Canonical manifest: sorted unique IDs, selector JSON validating as a `TemporalSelector`, cutoff, `coverage_json` with proven/contextual counts and only stable codes, sorted-key canonical JSON, no private text | **PROVEN (one deviation)** | `canonical_ids` (`model.py:774-778`) + the field validators (`:803-807`) reject unsorted/duplicated IDs; `test_history_manifest_requires_sorted_unique_ids_and_keeps_open_selectors` covers six cases. `selector_contract` (`:809-813`) reparses as a `TemporalSelector`. `canonical_json` emits sorted keys — verified: `{"codes":[],"contextual":{...},"proven":{...}}`. Codes are drawn only from the three-member `HistoryCoverageCode` literal and sorted (`temporal.py:546-550`). No source text or locator reaches the manifest. **Deviation:** the persisted selector cannot carry the cutoff for `current`/`atemporal` — **F3** (major). |
| f | `EvidenceSelection(query_mode="history")`; snapshot pins the manifest; current authorization and suppression revalidated before each dispatch; `history_unavailable` before the earliest retained interval; a stale proof after ACL loss denies | **VIOLATED** — `knowledge/snapshots.py:229-230` | The pieces that *are* proven: `EvidenceSelection(..., query_mode="history")` at `temporal.py:569-573`; `test_history_manifest_pins_a_query_snapshot_and_releases_its_reference` (snapshot names the manifest, `sources=()`, cutoff and `temporal.known_at` both MAY_5, reference released); `test_history_manifest_reports_history_unavailable_before_the_earliest_interval` (empty manifest, `codes == ("history_unavailable",)`, empty proof); `test_suppression_history_denies_an_old_snapshot_after_all_history_access_loss` (`bundle.validate()` raises `AuthorizationChanged` after an `all_history` access-loss suppression). **What breaks the row:** "revalidated" must mean *the requesting audience* is revalidated. `acquire_history_snapshot` consults its `access` argument only for a non-`None` existence check (`:226`), then adopts `history.resolver` (`:229`) — the `EvidenceAccess` built inside `select_history` from a possibly different `access` and a possibly different `clock`. Every later `bundle.validate()` therefore rechecks the selection-time audience. Reproduced: **F1**. |
| g | Collection roots include live and durable history snapshots; purge overrides roots and yields `evidence_purged` markers without text; Ladybug close/reopen preserves the manifest and its pin | **PROVEN** | `_snapshot_reaches` (`store/snapshots.py:183-200`) keeps a generation alive through `history_manifest_ids` and subtracts `_purged_revisions` first. `test_purge_history_overrides_retained_snapshot_roots` (blocked → `None` after the purge; markers exactly `("revision", id, "evidence_purged")`; `bundle.validate()` then raises). `test_history_manifest_and_its_pin_survive_ladybug_reopen` covers the real close/reopen on disk. I confirmed `PurgedEvidence` carries only a hash-derived revision ID — for the fixture revision whose `content_hash` is `"may-1"` and `raw_uri` is `"blob:may-1"`, the marker's `target_id` is `revision-fe2ae642…`, neither of them. Subtraction is per-revision, so a manifest that also lists a non-purged revision in the same generation still pins it. |
| h | Model validation for `HistoryManifest`/`ConflictSet` rejects unsorted/duplicate IDs and bad shapes, keeps unknown/open semantics, adds no provider-ordering or authority JSON fields; `recorded_to` remains the only mutable historical field; schema 5 unchanged | **PROVEN** | `test_history_manifest_requires_sorted_unique_ids_and_keeps_open_selectors` and `test_conflict_set_requires_sorted_unique_ids_and_a_proven_lower_bound` (which also proves `valid_from` with open `valid_to` stays valid, and that an upper bound alone is rejected — "an unknown lower bound is not negative infinity"). No ordering token or authority field was added to any JSON column. `recorded_to`: `store/knowledge.py:665-667` is untouched by this diff and `test_store_knowledge.py` still passes. Schema 5: the `migrations.py` schema literal already carried `HistoryManifest.coverage_json` as a column; `identity_fields` is a `ClassVar`, so no bump — confirmed by inspection of `migrations.py:67`. |

## 3. Findings

### F1 — blocker — `acquire_history_snapshot` pins the selection-time audience, not its caller's

`src/hippo/knowledge/snapshots.py:226-230`

**Why.** The signature is `acquire_history_snapshot(store, access, *, history, ...)`. `access` is
used at `:226` only to prove *some* audience exists, and is then discarded. `:229-230` take
`history.resolver` — the `EvidenceAccess` that `select_history` built from *its* `access` and
*its* `clock` — and build the pinned proof from it. That proof is what goes into
`QuerySnapshotBundle.proofs`, so `_validate_authorization` → `resolver.validate_current(proof)`
rechecks the selection-time audience for the life of the bundle, and
`_check_current_boundary`'s `self._now()` uses the selection-time clock, not the one passed here.
`acquire_query_snapshots:165` does the opposite and correct thing: `store._reader_proof(workspace,
audience, expected_epoch=epoch, selection=selection)` builds a fresh resolver from the caller's
own `access`. This is the T5A6 disqualifier "authorization fork" and contradicts plan §6
("never fork authorization policy") and §1 ("rechecked before result release").

**Reproduction** (`/tmp/t5a1_repro.py::repro_a_audience_confusion`, `HIPPO_TEST_STORE=fake`):

```
wide manifest (EVERYTHING) broad span_ids : 3
narrow reader's own broad span_ids        : 2
bundle = acquire_history_snapshot(store, Access(user_id=<bystander>), history=<wide>)
  bundle proof span_ids                   : 3     <- the wide proof
  bundle resolver access                  : Access(unrestricted=True, audience_kind='internal')
  wide-only span visible to narrow caller : True
  bundle.validate()                       : succeeded
```

The bystander receives a bundle whose pinned proof, `policy_fingerprint` and every future
revalidation belong to the internal audience. No production caller can obtain a foreign
`HistorySelection` *today*, which makes this latent, not absent — and `HistorySelection` is
precisely the object a request cache or a two-phase query path would hold across audiences.

**Proposed fix.** Build the proof from the caller: `history_access(store,
manifest.workspace_id, access, clock=clock).build(history.selection)`, keep the
`proof.authorization_epoch != epoch` check, and — because `coverage_json` in the identity makes a
manifest audience-specific — additionally require the rebuilt proof to cover the manifest:
`frozenset(manifest.revision_ids) <= proof.revision_ids` and the same for
`assertion_version_ids`, else `AuthorizationChanged`. Store `(rebuilt_resolver, proof)` in the
bundle. If the orchestrator prefers the narrower change, require `access` to equal the
selection-time audience and raise otherwise — but do not keep a parameter that does not mean
what its name says.

### F2 — blocker — `select_history` persists a manifest outside any transaction and never proves the manifest is contained in a valid proof

`src/hippo/knowledge/temporal.py:512-583` (persist at `:568`, containment check at `:574-579`)

**Why.** Three separate defects in one sequence, all of which the tests miss because Fake is
single-threaded and every fixture world is fully published before selection:

1. **No transaction.** `select_history` opens none (verified by source inspection:
   `"store.transaction()" in inspect.getsource(select_history)` is `False`). The broad proof
   (`:532`), the per-row reads (`:533`), the `LinkGeneration` scan (`:544`), the
   `GenerationMember`/`Generation` scan (`:545`) and the `put_knowledge` (`:568`) are five
   independent read/write windows. Plan §6 requires this path to "acquire/validate history
   manifests and references **atomically**"; T5A6 names "non-atomic closure" as a disqualifier.
   Both sibling functions —
   `acquire_query_snapshots:135` and `acquire_history_snapshot:224` — wrap everything in
   `with store.transaction():`. Under Neo4j (§8 requires transaction parity) a concurrent
   publication or collection between any two of these produces a persisted manifest that no
   single consistent state ever supported.
2. **The containment check runs in the wrong direction and too late.** `:575-578` asserts
   `proof ⊆ broad`. The invariant that protects the *persisted* row is `manifest ⊆ proof`. If the
   audience loses a revision between `:532` and `:574`, the narrowed `proof` simply lacks it,
   `proof ⊆ broad` still holds, and the manifest that names it is already on disk at `:568`. The
   check also runs *after* the write, so `AuthorizationChanged` leaves the manifest persisted.
3. **No epoch cross-check.** `_reader_proof:694` compares `proof.authorization_epoch` against the
   expected epoch on every read; `select_history` never compares `broad.authorization_epoch`
   with `proof.authorization_epoch`, so an epoch bump between the two builds is invisible.

**Proposed fix.** Wrap `:528-581` in `with store.transaction():`; capture
`epoch = store.authorization_epoch()` first and require both proofs to match it; move the
containment check before `put_knowledge` and flip it to
`frozenset(manifest.revision_ids) <= proof.revision_ids` (and the version equivalent) in addition
to the existing `proof ⊆ broad`.

### F3 — major — a `current` or `atemporal` history pin carries no cutoff, so the pinned selector does not round-trip

`src/hippo/knowledge/temporal.py:409-421`; `src/hippo/knowledge/model.py:1266-1274`

**Why.** `pinned_selector` binds the resolved cutoff only when the selector type *has* a
`known_at` field. `CurrentSelector` and `AtemporalSelector` do not (`AsOfSelector`,
`DuringSelector`, `ChangesSelector` and `CompareSelector` do), so for two of the six modes
`pinned_selector` is the identity function. `validate_knowledge_cutoff` then passes vacuously
(`model.py:1272-1273` short-circuits on `known_at is None`), for the `HistoryManifest`
(`model.py:815-819`) *and* for the `QuerySnapshot` (`model.py:1351`). Both plan §4's
`Amended 2026-09-11` note ("the manifest and the `QuerySnapshot` that pins it both store the
selector with its own `known_at` bound to the resolved cutoff") and evidence Decision 1
("which `validate_knowledge_cutoff` proves equals `knowledge_cutoff`") state this as a fact that
holds for all modes. It holds for four.

**Reproduction** (`/tmp/t5a1_repro2.py::repro_h_current_selector_pin`):

```
manifest cutoff              : 2026-05-12 00:00:00+00:00
manifest temporal_selector_json : {"mode":"current","snapshot_id":null,"timezone":"UTC"}
pinned selector known_at     : <no field>
re-resolve at 2026-06-01     : 2026-06-01 00:00:00+00:00 | round-trips: False
snapshot.temporal.known_at   : <none>
```

**Impact.** No collision and no data loss: `knowledge_cutoff` is in `identity_fields` and on the
`QuerySnapshot`, so identity stays distinct and the instant is recoverable from the sibling
column. The hazard is replay — a consumer that reconstructs a historical read from
`snapshot.temporal` (the field's whole purpose) silently gets "now" instead of the pinned
instant. Nothing in `src/` reads `snapshot.temporal.known_at` yet, which is why this is major
rather than blocker; it becomes a blocker the moment part 2 or the query dispatcher does.

**Proposed fix.** Either (a) add `known_at: datetime | None = None` to `CurrentSelector` and
`AtemporalSelector` — `temporal_selector_json`/`temporal` are text columns so schema 5 is
still untouched, but check that `acquire_query_snapshots:172`'s bare `CurrentSelector()` still
validates — or (b) have `select_history` reject the two unpinnable modes until (a) lands, so the
plan text and the code agree. (a) is the smaller lie to unwind.

### F4 — major — `HistoryManifest` is classified `content`, so a read-only history query is fenced by a build lease (implementer finding 1, confirmed and extended)

`src/hippo/store/authorization.py:131`; enforced at `src/hippo/store/generations.py:410-423`

**Why.** `RECORD_EPOCHS` lists `HistoryManifest` under `content`. `_check_knowledge_write`
therefore walks `_record_revisions` — which follows
`LIST_REFERENCES["HistoryManifest"]["revision_ids"] → ArtifactRevision`
(`store/knowledge.py:87-91`) — up to each contributing source, and demands build authority
whenever that source has a `running` rebuild.

**Reproduction** (`/tmp/t5a1_repro2.py::repro_b_build_lease`): after claiming a third generation
on the fixture's source (`active build: rebuild running`), `select_history` raises
`ValueError: Managed evidence write requires build authority`. Confirmed exactly as the
implementer reported.

**Extension the brief asked for — does any other record share the misclassification?**
Yes: **`ConflictSet`** (`authorization.py:138`) is `content` and has the same
`LIST_REFERENCES` walk (`assertion_version_ids` → `AssertionVersion`, `support_span_ids` →
`EvidenceSpan` → revisions, `knowledge.py:94`). If part 2 persists conflict sets on a query path
— which §3's builder invites — it hits the identical denial. `LinkGeneration`, `DerivedRecord`,
`RetrievalView`, `Section`, `Alias` and `ProseExtraction` are also `content` with revision
reachability, but all are written from build/derivation paths where holding the lease is
correct, so they are not misclassified. The precedent for the fix is already in the same table:
`QuerySnapshot` and `SnapshotReference` are `bookkeeping` (`authorization.py:152-154`) for exactly
the reason that applies here — they *name* evidence rather than being evidence.

**Proposed fix.** Move `HistoryManifest` (and, before part 2 persists them, `ConflictSet`) to
`bookkeeping`. Note the side effect this removes: as `content` they currently bump
`content_epoch` (`authorization.py:190-191`) on every history query, which is itself wrong —
a read must not advance the content epoch. `store/authorization.py` is outside this slice's
ownership; root's call.

### F5 — minor — compare selectors are rejected unconditionally, so the plan's acceptance branch is unimplemented and the test name overstates what is proven

`src/hippo/knowledge/temporal.py:529-530`; `tests/unit/test_temporal_evidence.py:424-432`

Plan §4 step 1 says "Reject compare unless the caller requests two independently pinned sides."
`select_history` raises for every `CompareSelector`. The test that guards it is named
`..._rejects_a_compare_selector_without_pinned_sides` yet its fixture supplies two sides that
*are* independently pinned (`known_at=MAY_5`, `known_at=MAY_12`), so it does not test the
condition its name states. The behavior is defensible — plan §4's amendment says each side needs
"one independently pinned manifest per side", i.e. the caller loops — but the code and the test
name should say so. **Fix:** rename to `..._rejects_a_compare_selector_and_asks_for_one_manifest_per_side`,
and make the error message name the remedy explicitly. No behavior change.

### F6 — minor — `_purged_revisions` runs full scans once per live snapshot reference during collection

`src/hippo/store/snapshots.py:153-170`, called from `:195` inside the `:210-215` loop

`_collection_block` iterates every unreleased `SnapshotReference` and calls `_snapshot_reaches`,
which now calls `_purged_revisions(workspace)` — a full `Suppression` scan plus, whenever an
`artifact`- or `source`-scoped purge exists, a full `ArtifactRevision` scan with one
`_knowledge_get("Artifact", …)` per revision. On Neo4j each `_knowledge_rows` is an unindexed
`MATCH`. The pre-existing `GenerationMember` scan in the same function has the same shape, so
this compounds an existing cost rather than introducing the pattern. **Fix:** compute the purged
set (and the generation's revision set) once in `_collection_block` and pass both into
`_snapshot_reaches`.

### F7 — minor — `history_access` duplicates `_reader_proof`'s authority validation verbatim

`src/hippo/knowledge/temporal.py:423-433` vs `src/hippo/store/knowledge.py:687-692`

Six lines reproduced character for character (including the `RuntimeError` text); the only
functional delta is that `history_access` can inject a `clock` and `_reader_proof` cannot. A
third copy already exists at `store/knowledge.py:325-331` (`_reviewed_mapping_authorities`).
This is the kind of duplication that drifts: a future tightening of the authority contract will
be applied to one copy. **Fix:** add `clock=None` to `_reader_proof` and have `history_access`
call it (or at minimum call `store._reviewed_mapping_authorities()` instead of re-validating).

### F8 — minor — an audience that can prove nothing is told `history_unavailable`

`src/hippo/knowledge/temporal.py:535-536`

`earliest` is the minimum `recorded_from` over the *authorized* rows only, so a reader with no
authorized rows always gets `earliest is None → unavailable = True` and the code
`history_unavailable`, which the plan defines as "a requested cutoff before the earliest retained
recorded interval". The behavior is information-safe (it leaks nothing about what exists) but the
code is a false statement about retention. **Fix:** emit `history_unavailable` only when
`rows` is nonempty and `resolved.known_at < earliest`; an empty authorized set deserves either no
code or a distinct one.

### F9 — minor — `purged_history_evidence` takes no audience and no workspace

`src/hippo/store/snapshots.py:172-181`

The method resolves a manifest ID to purged-revision markers with no `access` and no
`workspace_id` argument, so any caller holding a manifest ID gets the answer regardless of
audience or workspace. Every sibling on `SnapshotQueries` is likewise store-internal, so this is
consistent — but unlike `get_knowledge`/`list_knowledge` (`store/knowledge.py:717,734`) it has no
`Access` gate to fall back on. **Fix:** none required in this slice; record that any request path
exposing these markers must audience-check first, and prefer adding `workspace_id` +
`access` when part 2 wires it to a dispatcher.

### F10 — minor — bookkeeping drift in the accompanying documents

- `evidence-int1.md` lists **three** open findings; the review brief says four. The fourth appears
  to be the "what part 2 still owes" paragraph, which is scope, not a finding. Worth reconciling
  so the orchestrator's count matches.
- `evidence-int1.md` Decision 1 states the manifest "stores the selector with its own `known_at`
  bound to the resolved cutoff, which `validate_knowledge_cutoff` proves equals
  `knowledge_cutoff`" — false for `current` and `atemporal` (F3). Amend the decision text along
  with the plan note.
- The implementer's finding 2 is already **applied** to the CHECK line in the working-tree
  ledger — `GATES.md:40` now lists all ten files. What is still stale is T5A6's EVIDENCE line,
  which records the four-file result (`4 files already formatted`); my run of all ten gives
  `All checks passed!` / `10 files already formatted`.
- The implementer's finding 3 ("revalidate before release" is inherited, not added here) is
  **accurate**. `QuerySnapshotBundle.close()` (`knowledge/snapshots.py:79-85`) releases its
  references without rechecking authorization, and this slice did not change it. Plan §4 step 6
  says "revalidate current authorization/suppression before each dispatch **and release**": the
  dispatch half is proven (`validate()`, exercised for history pins by
  `test_suppression_history_denies_an_old_snapshot_after_all_history_access_loss`); the release
  half is **UNTESTED and inherited**, not a regression introduced here. Part 2 must not assume it
  exists.
- Adding `coverage_json` to `HistoryManifest.identity_fields` changes every manifest ID. I grepped
  `tests/`, `src/`, `docs/` and `ai_docs/` for literal `historymanifest-` IDs and found none, and
  the two fixtures that build manifests (`test_knowledge_contracts.py:860`,
  `test_store_knowledge.py:444`) derive IDs at runtime, so **no fixture silently changed meaning**.
  Any `HistoryManifest` persisted by a pre-`043ca51` store would have an ID today's code no longer
  computes; none exist, because Task 5 is not activated.

## 4. Answers to the specific QUALITY questions

**Can `coverage_json` in the identity make two manifests for one audience differ across runs?**
No nondeterminism found. Two identical `select_history` calls in one process produce the *same*
manifest ID and leave exactly one row in the store (`repro_d_manifest_determinism`);
`canonical_json` sorts keys, `codes` is sorted, and `_counts` is order-independent. Across
stores the ID differs only because the record IDs differ. The real consequence is different and
worth stating: coverage counts *all* proven and contextual rows in the workspace, including
contextual rows whose IDs the manifest does not list, and `codes` includes `retention_gap`, which
flips when a background collection runs. So the manifest ID is not a pure function of what the
manifest asserts about itself — unrelated workspace activity mints a new manifest for a repeated
query. That is the intended trade (it is what stops one audience's manifest from immutably
overwriting another's), but a `QuerySnapshot` that pinned the older ID keeps pointing at coverage
that is no longer current. Fine for this slice; part 2 should not treat manifest ID as a cache key
for "the same question".

**Does the pinned selector round-trip through `resolve_selector` to the same cutoff?**
For `as_of`, `during` and `changes`: yes — `pinned_selector` writes the resolved instant into
`known_at`, re-resolution returns it with origin `explicit`, and `validate_knowledge_cutoff`
enforces the agreement. For `current` and `atemporal`: no. See **F3**.

**Confirm the write-classification finding; does any other bookkeeping record share it?**
Confirmed with a live reproduction, and yes — `ConflictSet`. See **F4** for the full list and the
`QuerySnapshot`/`SnapshotReference` precedent.

**Transaction boundaries in `acquire_history_snapshot` (no callbacks inside).**
Clean on the callback question: the `with store.transaction():` block at `:224-258` contains only
store reads, one `EvidenceAccess.build` (itself pure store reads, the same thing
`acquire_query_snapshots` does at `:165`), record construction, one
`acquire_snapshot_reference` and `_validate_authorization`. No model, filesystem, remote or
user-supplied callback runs inside; the injected `clock` is called once at `:228` through
`_now`. The transaction discipline in *this* function is right — it is `select_history` that has
none (**F2**).

**Can `purged_history_evidence` leak a purged target's text or locator?**
No. `PurgedEvidence` has exactly three fields (`target_kind`, `target_id`, `code`), all
`Literal`/`str`, and the returned `target_id` is the hash-derived revision ID — for the fixture
revision whose `content_hash` is `"may-1"` and `raw_uri` is `"blob:may-1"`, the marker carries
`revision-fe2ae642a4f868368a800293da8423040aa717842c6662fbcb74976f5623aede`. The test asserts
`not any(hasattr(item, "text") for item in markers)`. Also checked: a purge cannot be scoped
`current_only` — `Suppression` rejects it ("Access loss and purge must suppress all historical
views"), so `_purged_revisions` filtering on `reason` alone is sufficient, not a gap.

**Does the `ClassVar` identity change silently alter any existing manifest fixture's ID?**
No. See F10.

**Any `datetime.now`/`utc_now` default a test could not control?**
None that a test cannot control, one that a *caller* cannot. `select_history` requires
`request_cutoff` explicitly (good — the cutoff is never ambient) and defaults only `clock`, which
feeds `EvidenceAccess`; `acquire_history_snapshot` defaults `clock` exactly as
`acquire_query_snapshots` does. `HistoryManifest` has no `created_at`, so no wall clock enters
the identity. The uncontrollable one is inside **F1**: the bundle's authorization boundary is
checked with the resolver's *selection-time* clock, so a caller passing `clock=` to
`acquire_history_snapshot` does not actually control expiry checking. Both tests pass
`lambda: MAY_12` to both functions, which is why it is invisible today.

## 5. Verbatim public signatures for part 2

```python
# src/hippo/knowledge/temporal.py
HistoryCoverageCode: TypeAlias = Literal["history_unavailable", "retention_gap", "link_coverage_incomplete"]
TemporalRecordKind: TypeAlias = Literal["ObjectObservation", "AssertionVersion"]


@dataclass(frozen=True)
class HistoryDecision:
    record_id: str
    record_kind: TemporalRecordKind
    recorded_reason: TemporalReason
    match: TemporalMatch


@dataclass(frozen=True)
class HistorySelection:
    manifest: k.HistoryManifest
    selector: k.TemporalSelector
    resolved: ResolvedTemporalSelector
    selection: EvidenceSelection
    decisions: tuple[HistoryDecision, ...]
    resolver: EvidenceAccess = field(repr=False)
    broad: AuthorizedEvidence = field(repr=False)
    proof: AuthorizedEvidence = field(repr=False)

    @property
    def proven(self) -> tuple[HistoryDecision, ...]: ...
    @property
    def contextual(self) -> tuple[HistoryDecision, ...]: ...
    @property
    def excluded(self) -> tuple[HistoryDecision, ...]: ...
    @property
    def coverage(self) -> dict: ...
    @property
    def codes(self) -> tuple[HistoryCoverageCode, ...]: ...


def pinned_selector(resolved: ResolvedTemporalSelector) -> k.TemporalSelector: ...


def history_access(store, workspace_id: str, access, *, clock=utc_now) -> EvidenceAccess: ...


def select_history(
    store,
    *,
    workspace_id: str,
    access,
    selector: k.TemporalSelector,
    request_cutoff: datetime,
    clock=utc_now,
) -> HistorySelection: ...


@dataclass(frozen=True)
class ResolvedTemporalSelector:
    selector: k.TemporalSelector
    known_at: datetime
    known_at_source: KnownAtSource  # "explicit" | "inherited" | "latest"
    latest_known_at: datetime
    inherited_from: k.CompareSelector | None = None
    selector_json: str = field(init=False, default="")


# src/hippo/knowledge/access.py
class EvidenceAccess:
    def build_history(self, selection: EvidenceSelection | None = None) -> AuthorizedEvidence: ...


# src/hippo/knowledge/model.py
def canonical_ids(values: tuple[str, ...], *, label: str) -> tuple[str, ...]: ...


HistoryManifest.identity_fields = (
    "workspace_id",
    "revision_ids",
    "assertion_version_ids",
    "link_generation_ids",
    "knowledge_cutoff",
    "temporal_selector_json",
    "retention_gaps",
    "coverage_json",
)


# src/hippo/knowledge/snapshots.py
def acquire_history_snapshot(
    store,
    access: Access,
    *,
    history,
    settings_fingerprint: str,
    lease_duration: timedelta = timedelta(minutes=5),
    clock=utc_now,
) -> QuerySnapshotBundle: ...


# src/hippo/store/snapshots.py
@dataclass(frozen=True)
class PurgedEvidence:
    target_kind: Literal["revision"]
    target_id: str
    code: Literal["evidence_purged"] = "evidence_purged"


class SnapshotQueries:
    def purged_history_evidence(self, manifest_id) -> tuple[PurgedEvidence, ...]: ...
```

## 6. Recommendation

Do not publish this slice as-is. F1 and F2 both hit named contract disqualifiers. F1 is
**confirmed by reproduction** (`repro_a`, output quoted above). F2 is **established by source
inspection**: the absence of `store.transaction()`, the direction of the containment check and
its position after `put_knowledge` are facts of the text at `temporal.py:512-583`; the concurrent
consequence is inferred from them, not reproduced — Fake is single-threaded, so a behavioral
repro would need a monkeypatched `history_access`. Neither is covered by any test in this
review's eight green runs,
because every fixture selects and pins under one audience, one clock and one thread. F1 and F2
are contained changes to `knowledge/snapshots.py` and `knowledge/temporal.py`, both already owned
by this slice. F3 needs a one-line decision (extend two selectors, or refuse two modes) and an
amendment to the plan note and the evidence file. F4 needs `store/authorization.py`, which this
slice does not own — root's call, and it should be settled before part 2 persists `ConflictSet`
on a read path. The remaining six are cleanups that need not block.

The engineering under review is careful and the reasoning in the comments is unusually good —
`build_history` as a pure delegate, the refusal to fabricate revisions in `_retention_gaps`, the
`sources=()` / `profile_fingerprint="history:<id>"` decision, and the `coverage_json`-in-identity
argument are all right, and the model-validation work in `canonical_ids` and the `ConflictSet`
lower-bound rule is exactly what §6 asked for. The two blockers are boundary defects at the seams
between this slice and the reviewed code it reuses, not flaws in the design.

## Appendix — reproduction scripts

`/tmp/t5a1_repro.py` and `/tmp/t5a1_repro2.py`, run as
`HIPPO_TEST_STORE=fake PYTHONPATH=/Users/mascott/projects/hippo .venv/bin/python <script>`.
They construct their own `FakeStore` instances, touch no repository file and write nothing
outside `/tmp`.
