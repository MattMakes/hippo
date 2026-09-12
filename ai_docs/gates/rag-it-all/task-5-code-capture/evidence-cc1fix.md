# CC1fix evidence — the legacy lane serves untagged rows only (gates PA6, CD2, PA2)

Worker `opus-18`, worktree `.worktrees/cc1fix`, branch `wp/cc1fix`, base `c893a95`, then merged
up to `rag-it-all-tibs` `c461c9c` (CC2 + CC6) at `a65833d` to use CC2's bounded untagged read.
Brief: `ai_docs/handoffs/briefs/fix-cc1-legacy-lane.md`. Fixes the regression opus-17 reported
at `c893a95`: CC1 (`74ebaa5`, `82e31c1`, `d74e482`) moved the lane decision to
`store.source_serves_legacy` alone, which put sources with unpublished managed records back
into the legacy lane and leaked their native rows onto the graph surfaces.

## The ruling, as implemented

The brief's ruling — "the legacy lane serves only untagged rows, and a `managed` source is
presented in the legacy lane only when it has at least one untagged row" — could not by itself
make the six contract tests green. The refinement below was reported to the orchestrator by
`horch tell` before any test was re-adapted, and approved before the change was committed. The
measurement that forced it:

- `tests/unit/test_graph_surface_access.py::test_unpublished_managed_native_rows_never_escape_graph_surfaces`
  builds its source with `foundation()` (an `Artifact`, no `Generation`) and then writes its
  rows with `index_source`, the **legacy** indexer. Those rows carry no `generation_id`.
- The source is nevertheless `managed=True`: `record_mutation`
  (`src/hippo/store/authorization.py:187`) calls `begin_managed_source` on the first `Artifact`,
  not only on the first staged row. Probed directly: `FOUNDATION managed=True`,
  `FOUNDATION untagged passages=1`.
- The same holds for `::test_unpublished_managed_code_never_appears_in_symbol_lookup`
  (`code_index` has 93 untagged symbols, then the test adds an `Artifact`) and for
  `tests/unit/test_eval_access.py::test_generated_names_and_source_labels_come_from_visible_evidence`
  (a monkeypatched `Artifact` row over a plain legacy source).

So "managed flag + at least one untagged row" does not separate those three from CC1's
converting source, which has exactly the same shape. The only thing that does is a
`Generation` row. **Approved rule** (orchestrator, this session):

```
legacy lane = { s : s has no Generation row and s is in no managed-record set }      # 13efa40, verbatim
            ∪ { s : s has a Generation row
                    and store.source_serves_legacy(s)
                    and s owns >= 1 untagged Passage/Symbol/DataObject/Commit }
```

`src/hippo/context.py::legacy_lane(store, sources, managed_records)` returns
`(the legacy-lane ids, the converting subset of them)`. `source_serves_legacy` is untouched:
same signature, same three terms (no active pointer, no published `IndexEvent`, no
all-principals `Suppression`). The presence gate lives beside the lane decision, in
`context.py` and `status.py`, exactly as the brief requires.

Why a `Generation` and not a tagged native row: a conversion **is** a generation being built,
and the production coordinator writes the `Generation` before the first `Artifact`
(`src/hippo/ingest/prose_generation.py:351-352` — `put_knowledge(gen)`, then
`begin_managed_source`, then the artifacts inside `generation_write`). The generation therefore
exists at the instant the source becomes `managed`, so a converting source never falls into the
first rule for even one transaction and its legacy graph never blinks out. Blocker A stays
fixed. Keying on "has a staged native row" instead would reintroduce the blink for a repository
bootstrap that commits its generation and artifacts before its first batch of rows.

### The corner case rule (a) hides

A `managed` source that has an `Artifact` (or the flag, or `meta.managed`) but **no**
`Generation` row is invisible in the legacy lane even when it owns untagged rows — its graph
rows do not load and it has no inventory row, dropdown entry, eval label or count. That is
`13efa40`'s behaviour restored byte for byte, and it is what the three contract tests above
assert. It is a real narrowing relative to the brief's literal ruling and is recorded here
deliberately: if a production path is ever added that creates artifacts for a legacy source
*before* its generation, that source's legacy graph will disappear for the duration. The
coordinator does not do this today.

## Requirement 1: no generation-tagged row in the legacy lane

Both generation-aware builders reach the store through
`knowledge/graph_loader.py::load_generation_graph`, whose `selected(row)` ends
`return source_id in legacy_source_ids and generation_id is None` — a legacy-lane source
contributes untagged `Passage`/`Symbol`/`DataObject`/`Commit` rows and nothing else, and the
edge tables are then filtered to the surviving node ids. Nothing is dropped after loading
because nothing tagged is loaded.

The one loader that cannot filter is `GraphIndex.load` (`hippo/hipporag/graph_index.py:411`,
design review B1), reached from `_graph_for` only when `managed_sources` is empty. A
generation-tagged row names a `Generation`, and every `Generation`'s `source_id` is in
`managed_sources`, so that path is unreachable while any tagged row exists and has no tagged
rows to drop. The argument is recorded as a comment at `src/hippo/context.py:_graph_for` rather
than as an unreachable filter.

`status.py`'s legacy counting reads the held graph (`_legacy_source`), so it counts exactly the
untagged rows the loader selected, never the Store's cumulative `Source.passages` counter.

## Requirement 2: presentation

`status.py::source_view` now builds its own managed-record set — `Artifact` ∪ `Generation` ∪
`active_generation_id` ∪ `managed` ∪ `meta.managed`, its pre-CC1 union, deliberately not
unified with `context.py`'s — passes it to `legacy_lane`, and takes `managed` as the
complement of the legacy ids. A staging-only managed source is therefore in neither set's
presentation: not legacy (no untagged row), and not `represented` (no passage, no code node, no
proven pair), so it has no inventory row at all until it publishes.

Three-way rendering, so unmanaged legacy behaviour is byte-identical to `13efa40`:

| source | row |
| --- | --- |
| not in the legacy lane | `_managed_source(source, graph)` — projected evidence only |
| converting (in the lane, has a generation) | `_legacy_source(source, graph)` — counted from the held graph |
| any other legacy source | `deepcopy(source)` — the Store counter it has always presented |

CC1 applied `_legacy_source` to every legacy source, which would have re-derived an ordinary
legacy source's `passages` count from the graph. Only a converting source has staged rows that
can corrupt the Store counter, so only a converting source needs the graph count.

## Requirement 4: the CC1 tests re-adapted

| test | change | why |
| --- | --- | --- |
| `test_managed_source_inventory.py::test_unpublished_generations_never_produce_a_pair[staging\|failed]` | back to "no pair AND no row"; also asserts `source_id not in view.legacy_ids` | `empty_published(..., publish=False)` owns no untagged row, so the legacy lane has nothing to present |
| `test_managed_source_inventory.py::test_converting_source_keeps_its_legacy_pairless_row[staging\|failed]` | NEW | the converting half: the same generation over `index_prose_sample`'s legacy graph keeps a non-managed row with its own legacy `passages` count and still no pair |
| `test_status_access.py::test_generation_only_source_without_legacy_rows_is_hidden_until_it_publishes` | renamed from CC1's `..._keeps_the_legacy_lane_until_it_publishes`; asserts `sources == 1`, `jobs == ["index:public"]` | states the contract: a staging generation holds the lane, but with no untagged row there is nothing to present |
| `test_status_access.py::test_converting_source_with_legacy_rows_keeps_the_legacy_lane_until_it_publishes` | NEW | the converting half of the same mock fixture: one untagged row is the whole difference |
| `test_status_access.py::test_proven_selected_pair_renders_the_source_control_presentation` | reverted CC1's `source_serves_legacy` monkeypatch to the pre-CC1 `Artifact`-row monkeypatch | the source has no generation, so rule (a) classifies it and the predicate is never consulted |
| `test_status_access.py::test_managed_source_surfaces_render_only_projected_evidence[individual\|local-admin]` | same revert | same reason |
| `test_status_access.py::test_account_and_identity_count_only_owned_sources_with_visible_evidence` | same revert | same reason |
| `test_status_access.py::status_context` | added a `_native_rows` mock returning `[]` | the presence gate reads it; the converting test gives it a side effect that answers one untagged `Passage` for its own source |
| `test_managed_source_inventory.py::empty_published` | added `existing_source=` | builds the same generation over a source that already has a legacy graph |

CC1's other adaptations (`test_private_corpus_cannot_change_reader_counts_cards_or_jobs`,
`test_managed_metadata_is_withheld_even_with_visible_managed_evidence`,
`test_mcp_identity_never_exposes_total_hidden_source_inventory`) moved their fixtures from an
`Artifact` row to `active_generation_id`. A published source is out of the legacy lane under
both rules, so those stand unchanged and pass.

Every CC1 converting-source assertion still passes unmodified: legacy rows served, counted
once, no staged row visible, publication flipping lane/pointer/presentation in one transaction,
tombstoned mid-conversion in neither lane, the Ladybug reopen, and the destructive-guard
refusals.

## Requirement 5: new surface tests

In `tests/unit/test_converting_source_serving.py`, all three through a real `TestClient`
(imported inside the test, each carrying the sanctioned
`@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")`
marker — form (a) of the fleet rule, because CD2's CHECK line carries no command-line filter):

- `test_a_converting_source_shows_exactly_its_legacy_rows_on_every_graph_surface` — after
  staging, `/api/graph/full` is byte-identical to before, `/api/entities`, `/api/code/symbols`
  and the `/graph` dropdown still show the legacy rows, and neither the staged text nor the
  staged passage id appears anywhere.
- `test_a_staging_only_source_shows_nothing_on_any_graph_surface_or_eval_label` — a source with
  staged rows only: `/api/graph/full` and `/graph` never name it, `/api/entities` and
  `/api/code/symbols` return `[]`, `source_view` has no row for it, and
  `EvalAccess.get_source` returns `None`.
- `test_a_failed_generation_leaves_the_converting_source_serving_its_legacy_rows` — the
  orchestrator's pin: a **failed** generation is still a `Generation` row, so rule (b) keeps
  applying and the converting source keeps serving its legacy rows.

## The store read

The presence gate was first written as `context._untagged_source_ids(store)`: the four unscoped
loader reads (`load_passages`, `load_symbols`, `load_data_objects`, `load_commits`) filtered
`generation_id is None` in Python, lazily, because `src/hippo/store/*` is CC2's file. The read
it wanted was recorded for CC2/CC3 as "distinct `source_id`s over a `generation_id IS NULL`
scan of `Passage`/`Symbol`/`DataObject`/`Commit`".

CC2 landed that read at `c461c9c` (ruling 14) as a key on the existing method:

```python
store._native_rows(kind, source_id=identity, untagged=True)
```

one bounded query per kind on every backend. `wp/cc1fix` merged `rag-it-all-tibs` at `a65833d`
on the orchestrator's offer, and `context._owns_untagged_rows(store, source_id)` now uses it,
stopping at the first kind that answers. The gate is asked only of a source that has a
generation and has not published, so the common request does no native read at all and a
converting source with passages costs a single indexed query — not four full table
materializations per uncached graph build. No file under `src/hippo/store/` was modified by this
slice.

## Results

All runs: `cwd=/Users/mascott/projects/hippo/.worktrees/cc1fix`, `shell=/bin/zsh`,
`.venv/bin/python` 3.12.11, pytest 9.1.1, `mcp==2.1.1` pinned per the fleet rules. RED is at
`c893a95`; every GREEN is at the post-merge tip (`a65833d` plus the read swap), so the numbers
below hold with CC2 and CC6 in the tree.

| what | command | result |
| --- | --- | --- |
| RED (PA6 line at `c893a95`, clean worktree) | the PA6 CHECK line verbatim | exit=1; **6 failed, 708 passed** in 68.45s — `/tmp/hippo-cc1fix-red.log` |
| GREEN PA6 | the PA6 CHECK line verbatim | exit=0; **714 passed** in 89.03s — `/tmp/hippo-cc1fix-green-pa6.log` |
| GREEN CD2 | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_converting_source_serving.py tests/unit/test_managed_source_inventory.py tests/unit/test_status_access.py tests/unit/test_structural_loading.py -q -o addopts='' -W error` | exit=0; **112 passed, 2 skipped** in 7.45s — `/tmp/hippo-cc1fix-green-cd2.log` |
| GREEN PA2 | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_source_inventory.py tests/unit/test_status_access.py tests/unit/test_structural_loading.py -q -o addopts='' -W error` | exit=0; **96 passed, 1 skipped** in 2.85s — `/tmp/hippo-cc1fix-green-pa2.log` |
| managed web surfaces | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_web_surfaces.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` | exit=0; **84 passed** in 6.71s — `/tmp/hippo-cc1fix-green-web.log` |
| evidence context + CC2 scoped reads | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_evidence_context.py tests/unit/test_generation_scoped_reads.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` | exit=0; **43 passed** in 10.64s — `/tmp/hippo-cc1fix-evctx.log` |
| Ladybug | `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_converting_source_serving.py tests/unit/test_managed_source_inventory.py -q -o addopts='' -W error` | exit=0; **43 passed** in 101.35s — `/tmp/hippo-cc1fix-ladybug.log` |
| Ruff | `.venv/bin/ruff check` + `ruff format --check` over the five changed source/test files and this document | `All checks passed!` / `6 files already formatted` |

`tests/unit/test_evidence_context.py` was added to this slice's GREEN set at the orchestrator's
request: CC2 saw four failures there with the same staged-passages symptom. At `c893a95` the
file fails **7**; with this fix it fails **3**, and those three are the sanctioned AnyIO
`BlockingPortal` deprecation, raised by an in-test `from fastapi.testclient import TestClient`
with no `filterwarnings` marker — not a lane defect. With form (b) on the command line it is
green. Whether the marker is added to those three tests or the filter to a CHECK line is the
orchestrator's call; the file is not in this brief's ownership list and was not modified.

PA6 returns the same **714** the activation ledger's recorded EVIDENCE line carries, so the six
contract tests are green with no count drift.

PA2's line moves from the ledger's recorded **93 passed, 1 skipped** to **96 passed, 1 skipped**.
The `+3` is this slice's new tests, all in files the PA2 line already collects:
`test_managed_source_inventory.py::test_converting_source_keeps_its_legacy_pairless_row[staging]`
and `[failed]`, and
`test_status_access.py::test_converting_source_with_legacy_rows_keeps_the_legacy_lane_until_it_publishes`.
No PA2 test was removed; the two `test_unpublished_generations_never_produce_a_pair` parameters
were re-adapted in place.

The RED for the requirement-5 surface tests is the PA6 RED itself: they assert exactly the leak
those six failures record, so they were written against a fix whose failing evidence already
existed rather than re-deriving it. The tests that had no prior RED — the two converting
variants — were run against the pre-fix tree by the same PA6/CD2 lines before the change landed.

The six contract tests
(`tests/unit/test_graph_surface_access.py`, `tests/unit/test_eval_access.py`) are **unmodified**
— `git diff --stat` for `fe457f0` touches neither file.
