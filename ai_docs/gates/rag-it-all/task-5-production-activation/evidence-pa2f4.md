# PA2 finding 4: a managed row's code edges are its selected generation's own rows

Owner: opus-22. Branch `wp/pa2f4`, worktree `.worktrees/pa2f4`, base `9a474e4` (`rag-it-all-tibs`,
CC10 merged). Brief `ai_docs/handoffs/briefs/fix-pa2-4-code-edges.md`. Finding: PA2-4 in
`ai_docs/reports/2026-09-11-pa2-review.md`, restated in `ai_docs/reports/2026-09-13-pa8-resign.md`;
its owner sentence is the "PA2 review finding 4" bullet in the rollout section of
`ai_docs/plans/rag-it-all-task-5-production-activation.md`. No gate checkbox is set here.

Commits: `f0df1be` (the fix and its tests) and the commit carrying this file.

## Files

| File | Change |
|---|---|
| `src/hippo/status.py` | `_managed_source` no longer walks `graph.code_out` by node membership; it keeps only the relation-predicate counter gated on the exact pair (`:136`). New `_with_code_edges` (`:179`) adds the native code relation counts from the scoped read. `source_view` applies it to every managed row with that row's proven pair (`:83`). |
| NEW `tests/unit/test_status_code_edges.py` | 6 tests, below. |
| NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa2f4.md` | This file. |

`context.py`, `store/*`, `knowledge/*` and the ingest lane are untouched.

## The scoped read

`store._native_relationships(generation_id=...)` (`src/hippo/store/generations.py:867`, CC2). No new
store read was needed. Every returned `["CODE_EDGE", a, b, payload]` whose `payload["kind"]` is in
`CODE_EDGE_KINDS` is counted, and nothing else.

The generation read is the one in `graph.selected_managed_generations`, the pair this audience
proved for the held view, not the Source row's current pointer. A staged, failed, retired or
tombstoned generation is never a selected pair, so it is never read. A publication replaces the
pair, and with it the count, in the next view; a view pinned before it keeps its own pair and its
own count. A managed row without a pair gets no read. The legacy lane is not touched: a legacy
row is still `deepcopy(source)` and a converting row is still `_legacy_source`.

`_managed_source(source, graph)` keeps its two-argument shape.
`test_managed_source_inventory.py::test_held_session_is_validated_after_dto_construction` wraps it
with a two-argument function, and the brief does not own that file. The store read therefore sits
in `_with_code_edges`, which `source_view` calls on `_managed_source`'s result. That keeps it inside
the same two `validate()` calls as the rest of the row construction.

## What the defect looked like at `9a474e4` (deviation from the brief's RED)

The brief expected the RED to be "a staged second generation inflates the count today". That does
not reproduce. A probe with the real code coordinator (`build_code_source` over the CD8 git
checkout, Fake store) found:

| Moment | Native `CODE_EDGE` rows of the selected generation | `source_view` row `meta.code` |
|---|---|---|
| G1 published | `CONTAINS: 7` | `edges: 0, edges_by_kind: {}` |
| G2 failed mid-write, G1 selected | `CONTAINS: 7` | `edges: 0, edges_by_kind: {}` |
| G2 published | `CONTAINS: 7` | `edges: 0, edges_by_kind: {}` |

The structural graph `source_view` loads carries no arrow for a managed generation's native
`CODE_EDGE` rows. The projection emits only `DEFINED_IN` and assertion arrows
(`knowledge/projection.py:520-572`). The legacy half loads untagged rows of legacy-lane sources
only (`knowledge/graph_loader.py:45-51`). At HEAD the finding was therefore visible as an
undercount: a published repository reported no code edges.

Attribution by node membership was still there, only latent. Any `CODE_EDGE_KINDS` arrow on one of
the source's vertices was counted, whichever generation or contributor it came from. The RED pins
both shapes (`/tmp/hippo-pa2f4-red.log`, Fake, 5 failed, 1 passed):

| Test | RED at `9a474e4` |
|---|---|
| published generation | `assert {} == {'CONTAINS': 7}` |
| staged second generation | `assert {} == {'CONTAINS': 7}` (the count while G2 is staged) |
| tombstoned source | precondition `assert {}`: no edges to lose |
| straddling edge | precondition `assert {} == {'CONTAINS': 8}` |
| arrow on the source's own vertex | `assert {'INVOKES': 1} == {'CONTAINS': 7}`: the node-membership shape itself |
| legacy repository | passed: a regression pin, green before and after |

## Tests (`tests/unit/test_status_code_edges.py`)

The oracle never uses the read under test. `generation_edges` takes the store's whole-table
`load_code_edges()` and keeps the rows whose endpoints are both rows of that generation, found
through the whole-table `load_symbols()`/`load_data_objects()`.

| Test | Brief requirement | What it proves |
|---|---|---|
| `test_a_published_code_generation_counts_exactly_its_own_code_edge_rows` | 2, first clause | The row's `edges_by_kind` equals the oracle for the published generation, and `edges` is their sum. |
| `test_a_staged_second_generation_adds_nothing_until_it_publishes_and_then_replaces_the_count` | 2, second clause | The refreshed tree adds one function, so G2 holds `CONTAINS: 8` against G1's 7 (asserted as a precondition). Observed at the coordinator's `seal` progress, when every G2 edge is staged and nothing is published, the row still shows G1's 7. After publication it shows exactly G2's 8, never 15. |
| `test_a_tombstoned_code_source_shows_no_code_edges` | 2, third clause | After the current-only Source suppression the pair is gone and the row is absent. The generation's edges are still in the store: unselected, not deleted. |
| `test_an_edge_straddling_two_generations_is_refused_and_never_counted` | 2, fourth clause | `add_code_edges` from an active-G2 symbol to a retired-G1 symbol raises `Native relationship crosses generations` (`store/generations.py:1739`). No row is written and the count is unchanged. |
| `test_an_arrow_on_the_sources_own_vertex_is_not_a_row_of_its_generation` | 1, "never by walking node membership" | An `INVOKES` arrow placed on two of the source's own vertices in the held graph leaves the count equal to the generation's rows. |
| `test_a_legacy_repository_keeps_the_count_its_source_row_has_always_presented` | 1 and 2, last clause | A legacy repo source with untagged symbols and an untagged `CODE_EDGE` is in `legacy_ids`. Its row equals the Source row the store lists, `meta` included, and `_native_relationships` is never called. |

Fixture reuse: `world`, `build`, `ORDERS_V1`, `_commit` and `head_of` come from
`tests/unit/test_code_generation.py` (CD8's real coordinator over a real git checkout); `row_of`
and `tombstone` from `test_managed_source_inventory.py`; `Offline` from
`test_structural_loading.py`. If CC11 changes those helpers, this file follows them.

## Runs

Every run is `-o addopts='' -W error` from the worktree. The runs the brief names need no warning
filter: `test_status_access.py` imports `fastapi.testclient` inside its tests, under its existing
form (a) markers. The wider sweep includes module-level importers, so it carries form (b).

| Run | Store | Result | Log |
|---|---|---|---|
| Baseline, PA2 CHECK line verbatim | Fake | exit 0, 105 passed, 1 skipped | `/tmp/hippo-pa2f4-baseline-pa2.log` |
| Baseline, `test_status_access.py test_managed_code_activation.py` | Fake | exit 0, 83 passed | `/tmp/hippo-pa2f4-baseline-status.log` |
| RED, `test_status_code_edges.py` | Fake | exit 1, 5 failed, 1 passed | `/tmp/hippo-pa2f4-red.log` |
| GREEN, `test_status_code_edges.py` | Fake | exit 0, 6 passed | `/tmp/hippo-pa2f4-green.log` |
| GREEN, PA2 CHECK line verbatim | Fake | exit 0, 105 passed, 1 skipped | `/tmp/hippo-pa2f4-green-pa2.log` |
| GREEN, `test_status_access.py test_managed_code_activation.py test_status_code_edges.py` | Fake | exit 0, 89 passed | `/tmp/hippo-pa2f4-green-status.log` |
| GREEN, `test_status_code_edges.py test_status_access.py` | Ladybug | exit 0, 33 passed (788.24s; 7 real code builds at about 45s each, per CC9b) | `/tmp/hippo-pa2f4-ladybug.log` |
| Sweep, the 12 modules that reach `source_view` or `hippo.status` (list in `/tmp/hippo-pa2f4-sweep-files.txt`), form (b) | Fake | exit 0, 493 passed, 4 skipped | `/tmp/hippo-pa2f4-sweep.log` |

Ruff: `ruff check` and `ruff format --check` are clean on `src/hippo/status.py`,
`tests/unit/test_status_code_edges.py` and this file. Neo4j was not run: the container is
root-owned and the brief does not ask for it. No `store/*` file changed.

## Findings for the orchestrator (not fixed; outside this brief's files)

1. **The row and the aggregate now disagree for managed code.** `_audience_inventory`'s
   `stats.code_edges`, and the code card built from it, counts `CODE_EDGE_KINDS` arrows in the held
   graph's `code_out`. Path tools walk the same `code_out`. The structural graph serves no native
   managed `CODE_EDGE` arrow, so for the fixture repository the card says 0 while the source row
   now says 7. Whether managed code should serve its native `CODE_EDGE` rows as arrows is a
   projection/loader question, for CC11 or the owner of `knowledge/projection.py`. The card follows
   once it does.
2. **Cost.** Each `source_view` call does one `_native_relationships` read per managed source with a
   pair. It runs three bounded passes: every native Passage/Symbol/DataObject/Commit row of the
   generation, then its Entity/Fact closure. It is bounded by the generation (CC2), not the corpus,
   and it is what the brief mandates. For Task 16's performance work, a `CODE_EDGE`-only form
   (`_edges_touching(ids, rels=("CODE_EDGE",))`) or a count recorded at seal would remove the
   closure passes.
3. **Granularity.** The count is exact to the generation, not to the view. A proven pair admits
   the generation. If a narrower suppression or authorization inside that generation keeps some
   of its code objects out of the held graph, their native `CODE_EDGE` rows still count. That is
   the rule the brief states ("rows whose `generation_id` is the selected generation"), named here
   for the PA8 reviewer.
4. **Fail closed.** `_native_relationships` raises on a crossing edge or a missing shared
   endpoint, so status would fail rather than miscount. Writes already refuse a crossing edge
   (`store/generations.py:1739`), and sealing recomputes the same read through
   `generation_checksums`, so a sealed generation cannot hold one.
