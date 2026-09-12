# CC1 evidence — legacy serving until publication (gate CD2)

Worker `backend-developer-13`, worktree `.worktrees/cc1`, branch `wp/cc1`, base `e456e05`.
Contract: `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` section 7 (blocker A) as
amended by `ai_docs/reports/2026-09-12-code-capture-plan-review.md` blockers B1 and B2, and by the
orchestrator's rulings recorded below.

## What was built

`GenerationQueries.source_serves_legacy(source_row) -> bool`
(`src/hippo/store/generations.py:62`), beside `source_is_managed`:

```python
def source_serves_legacy(self, source_row) -> bool: ...
```

True iff the source row has no `active_generation_id`, no published `IndexEvent`
(`kind="published"`, `aggregate_id` = the source), and no all-principals `Suppression`
targeting it in its workspace. A pure read: no lock, no clock, no transaction. The pointer
clause short-circuits before either scan, so a published source touches neither table.

The third term is **ruling 9's amendment**, settled after the shape-(b) rework. Plan ruling 8
has a tombstoned converting source present "as managed for dispatch, in neither serving lane",
and publication alone could not express that: a source tombstoned part way through its
conversion has no pointer and no published event, so it stayed in the legacy lane and kept
serving. Its suppression is enforced where managed evidence is authorized
(`knowledge/access.py:273-282`), and legacy rows are not evidence, so nothing else withdrew it.
With the term, such a source leaves the legacy lane, and the managed lane shows nothing for it:
no pointer, so no pair, and no authorized evidence. The orchestrator chose this shape over
subtracting suppressed ids at the three lane sites, so all three call sites stay unchanged and
blocker A keeps its one narrow predicate. Only an all-principals suppression is readable from a
row (`Suppression.all_principals` defaults to `True`, so every tombstone is one); a
principal-specific suppression stays the access layer's decision, as it is for any legacy
source.

The `managed` flag is **not** a term of the predicate. Per review blocker B2 and the
orchestrator's shape-(b) ruling, that flag keeps its existing meaning — "the managed lane owns
this source's cleanup and dispatch" — and keeps flipping at staging start through
`record_mutation` (`src/hippo/store/authorization.py:186-187`, unchanged). Only the serving
decision is deferred to publication. Every existing destructive and dispatch guard
(`legacy_source_cleanup`, `apply_source_tombstone`, `managed_eligibility`, `_prepare_reindex`,
`native_write`'s untagged barrier) therefore fires unchanged throughout a conversion.

## Classification sites changed

| Site | Before | After |
| --- | --- | --- |
| `src/hippo/context.py:171-177` | Artifact/Generation presence built `managed_sources`, which decided both the loader and the lane | Unchanged as the **loader-selection** set, with a comment saying so: one managed row anywhere forces the generation-aware loader, because `GraphIndex.load` reads every native row with no generation filter (review B1) |
| `src/hippo/context.py:218-226` (`_build_managed_graph`) | `legacy_ids` = sources not in `managed_sources`; `selected` = `managed_sources` with a pointer | `legacy_ids` = `store.source_serves_legacy(row)`; `selected` = any row with an `active_generation_id` |
| `src/hippo/context.py:255-262` (`_build_managed_graph` proofs) | per-workspace `local` filtered by `managed_sources` | filtered by the active pointer alone |
| `src/hippo/context.py:342-353` (`_build_structural_graph`) | same presence test | `legacy_ids` = `source_serves_legacy`; selection = the active pointer |
| `src/hippo/status.py:57-62` (`source_view`) | Artifact/Generation presence, plus `managed`, `active_generation_id` and `meta["managed"]` | `managed` lane = `not store.source_serves_legacy(source)` |
| `src/hippo/status.py:78-89` (new `_legacy_source`) | legacy row was `deepcopy(source)` | same row, with `passages` counted from the held graph |

Two deliberate narrowings, both recorded here because nothing else names them:

- **`meta["managed"]` is no longer a lane marker.** `status.py:65` used to treat it as one. No
  production code writes that key (only `status.py` and `build_authority.py:72` read it) and no
  test sets it; `source_is_managed` and `apply_source_tombstone` already ignore it.
- **The legacy row's `passages` count now comes from the held graph**, not the Store's Source
  counter. The counter spans every passage ever written for the source, so a source part way
  through a conversion reported its staged passages as its own (observed: 95 → 96 on the
  `code_index` fixture). `_managed_source` already counts from the view's own provenance for
  exactly this reason. `system_status`'s *internal* audience still reports raw Store counters,
  which legitimately count staged rows; the audience inventory does not.

`begin_managed_source` keeps its existing call sites (`record_mutation`, and
`prose_generation.py:491` in `_install`). `src/hippo/ingest/prose_generation.py` is therefore
**unmodified** by CC1.

## Adapted assertions (ruling 3 allows only assertions that pin the Artifact-presence classification)

| File | Test | What changed, and why it pinned the old classification |
| --- | --- | --- |
| `tests/unit/test_managed_source_inventory.py` | `test_unpublished_generations_never_produce_a_pair[staging|failed]` | Asserted `row_of(source_view(...)) is None`: a staging or failed generation removed its whole source from the inventory, which is the disappearance blocker A exists to fix. Now asserts no pair, plus the row present in `view.legacy_ids` with `kind != "managed"` and `passages == 0`. Docstring added. |
| `tests/unit/test_status_access.py` | `status_context()` fixture | The `NS` store had no lane predicate; added `source_serves_legacy` keyed on `active_generation_id`, the fixture's way of saying "past its first publication". |
| `tests/unit/test_status_access.py` | `test_private_corpus_cannot_change_reader_counts_cards_or_jobs`, `test_managed_metadata_is_withheld_even_with_visible_managed_evidence`, `test_mcp_identity_never_exposes_total_hidden_source_inventory` | Each made a source managed by setting `_knowledge_rows` to return a fake `Artifact` row. Replaced with an `active_generation_id` on the source row. No assertion changed. |
| `tests/unit/test_status_access.py` | `test_private_source_is_invisible_to_real_web_status_and_header`, `test_managed_source_surfaces_render_only_projected_evidence`, `test_account_and_identity_count_only_owned_sources_with_visible_evidence` | Same pin on a real store: a monkeypatched `_knowledge_rows` returning a fake `Artifact`. Replaced with a monkeypatched `source_serves_legacy` for that one source. No assertion changed. |
| `tests/unit/test_status_access.py` | `test_generation_only_source_is_hidden_until_authorized_evidence_is_projected` → renamed `test_generation_only_source_keeps_the_legacy_lane_until_it_publishes` | The name and its two assertions (`sources == 1`, `jobs == ["index:public"]`) pinned the classification directly: a staging-only source was removed from the inventory. Now `sources == 2`, `passages == 1` (the generation contributes none) and the source's own indexing job is visible with it. **Renamed**, because the old name asserts the opposite of the contract; flagged here as the one change beyond an assertion. |

No other test was touched. `tests/unit/test_generation_store.py`, `tests/unit/test_prose_generation.py`,
`tests/unit/test_managed_pipeline_activation.py` and `tests/unit/test_structural_loading.py` pass
unchanged.

## New tests — `tests/unit/test_converting_source_serving.py`

14 tests. Staging is written directly under a claimed fenced build (the plan's sanctioned
alternative to the coordinator's detached preparation); the legacy side of the serving tests is
the real `code_index` fixture, indexed through the production pipeline.

- Predicate: staging rows alone keep the legacy lane (and the `managed` flag still flips);
  a failed unpublished generation keeps it; publication leaves it; each clause on its own;
  the `managed` flag alone does not leave it; an unconverted source serves legacy; the
  predicate takes no source lock and reads no clock.
- Safety: a source mid-conversion refuses `delete_passages_for_source`,
  `delete_code_nodes_for_source` and `delete_source`, and keeps both its rows.
- Serving: `search` and `ask` return byte-identical passage orders before and after staging,
  the staged passage never appears, and the code nodes are unchanged.
- Inventory: exactly one row, presentation identical to before the conversion (excluding the
  build controls `active_build_id`, `build_fencing_token`, `updated_at` and `managed`), and an
  unchanged audience `stats`.
- Publication: the pair appears, exactly the generation's passage serves, no legacy passage or
  code node does, the row becomes the managed presentation, and the source leaves `legacy_ids`.
- Tombstone: a source tombstoned mid-conversion appears in neither lane -- no inventory row, not
  in `legacy_ids`, no passage in the held graph, and `search` returns nothing (ruling 8).
- A held legacy session is refused (`AuthorizationChanged`) once the conversion starts, from the
  staging-start authorization-epoch bump.
- Ladybug: a close/reopen mid-staging keeps the legacy lane, the staging status and both rows
  (skipped unless `HIPPO_TEST_STORE=ladybug`, following the `test_managed_source_inventory`
  reopen convention).

## Results

AnyIO handling: form (b) on every command whose file list includes the web suites
(`test_status_access.py`, `test_managed_web_surfaces.py`, `test_managed_web_ingress.py`); the CD2
line itself needs no filter, because those files import `fastapi.testclient` inside test bodies,
not at module level.

| Run | Command | Result | Log |
| --- | --- | --- | --- |
| Baseline (before any change) | activation regression + `test_prose_generation.py test_generation_store.py test_structural_loading.py`, `-W error` + form (b) | 362 passed, 2 skipped | `/tmp/hippo-cc1-baseline.log` |
| RED | `HIPPO_TEST_STORE=fake ... tests/unit/test_converting_source_serving.py -q -o addopts='' -W error` | 11 failed, 1 skipped | `/tmp/hippo-cc1-red.log` |
| RED (tombstone, ruling 9) | same command, `-k tombstoned` | 1 failed: the row was still present and still in `legacy_ids` | `/tmp/hippo-cc1-tombstone.log` |
| **CD2 (exact CHECK line)** | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_converting_source_serving.py tests/unit/test_managed_source_inventory.py tests/unit/test_status_access.py tests/unit/test_structural_loading.py -q -o addopts='' -W error` | **106 passed, 2 skipped** | `/tmp/hippo-cc1-cd2-fake.log` |
| Wider Fake regression | CD2 files + `test_managed_route_activation.py test_managed_web_surfaces.py test_managed_web_ingress.py test_prose_generation.py test_generation_store.py test_managed_pipeline_activation.py`, form (b) | 481 passed, 5 skipped | `/tmp/hippo-cc1-regression-final.log` |
| Coordinator suite (brief requirement 3) | `HIPPO_TEST_STORE=fake ... tests/unit/test_managed_pipeline_activation.py`, form (b) | 106 passed, 2 skipped, **unchanged** (also inside the sweep above) | `/tmp/hippo-cc1-activation-fake.log` |
| Other `source_view` consumers | `test_inventory_snapshot_lifetime.py test_managed_transport_activation.py test_settings_and_safety.py test_web_analyze.py test_web_auth.py test_web_base.py test_web_library_evals.py test_mcp_server.py`, form (b) | 178 passed | `/tmp/hippo-cc1-consumers-fake.log` |
| Ladybug — new file | `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_converting_source_serving.py -q -o addopts='' -W error` | **14 passed** (includes the reopen and tombstone assertions) | `/tmp/hippo-cc1-ladybug-new.log` |
| Ladybug — prose reopen | `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_prose_generation.py -k reopen -q -o addopts='' -W error` | 1 passed, 66 deselected | `/tmp/hippo-cc1-ladybug-prose.log` |
| Ruff | `check` + `format --check` on every changed file and this document | clean | — |

The Ladybug run found one defect in the tests, not the implementation: `_lock_source` bumps
`generation_lock` on every backend but the fake one, so the inventory comparison had to exclude it
alongside the other build controls (`test_managed_pipeline_activation.row_of` and
`_bootstrap_envelope` exclude the same key). No production behaviour differs between backends.

## Findings handed on (not fixed here)

1. **`build_authority._source_control` holds a third copy of the Artifact-presence test**
   (`src/hippo/knowledge/build_authority.py:68-77`) and refuses any source whose kind is not
   `text` or `file`. Review blocker B3 assigns both halves to CC1 with a handoff to CC8; the
   orchestrator has not ruled that into this brief, so CC1 left the file untouched. Under shape
   (b) the `managed` term there is simply true for a converting source, so B3's second half is
   redundant, but the kind allow-list still blocks `repo` and `archive` outright.
2. **A converting source's lane and its controls now disagree by design.** Its inventory row is
   the legacy presentation while `row["managed"]` is `True`. That is the two-meanings split B2
   describes, and it is what keeps the cleanup guards armed.
3. **`source_serves_legacy` reads two whole tables per source.** It is called once per source in
   `_build_managed_graph`, `_build_structural_graph` and `source_view`, and every source without
   an active pointer reads all of `IndexEvent` and then all of `Suppression` (two queries per
   legacy source per graph build on Ladybug and Neo4j; the `Suppression` read is ruling 9's
   amendment). The classification it replaced was two whole-table scans in total, not per source.
   Correct but unscoped, and squarely CC2's mandate (generation-scoped store reads, gate CD1):
   CC2 should parameterise this alongside `_native_rows`/`_knowledge_rows`, or the lane sites
   should build one published-and-suppressed source set per graph build.
4. **CD2's criteria should gain the destructive-operation line** the review asks for ("an
   actorless delete, reindex or bulk reindex of a converting source refuses rather than clearing
   it"). CC1 proves the three store-level refusals; the `pipeline`-level refusals
   (`_prepare_reindex`, `shutil.rmtree`) belong to CC10's spies.
