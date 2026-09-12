# CC2 evidence — generation-scoped store reads (gate CD1)

Branch `wp/cc2`, worktree `.worktrees/cc2`, base `7a0c719` (CC1 merged).
Commits: `2b4f412` (readers, indexes, schema v6) and the commit carrying this file (inner
loops, per-kind allow-list, ceiling test, journal fixtures).

Plan section 8.1; design review `ai_docs/reports/2026-09-12-code-capture-plan-review.md` M3, M4,
M5 and question 3.

## What the reads look like now

```python
_native_rows(kind, *, ids=None, generation_id=None)
_native_relationships(*, ids=None, generation_id=None)   # exactly one is required
_knowledge_rows(name, *, generation_id=None, where=None)
_edges_touching(ids, *, both=False, rels=None)           # new, internal to the passes
_selected_revisions(generation_id)                       # new, hoistable member-revision read
_validate_managed_native(kind, row, gen, *, selected=None)
```

`where` takes an exact-match field map drawn from a **closed per-kind allow-list** in
`store/knowledge.py`. A field outside it raises `"<Kind>.<field> is not a scoped field"` rather
than being answered, because an unindexed filter is a whole-table scan wearing a scoped read's
clothes: it would let a query counter report bounded work while the database did exactly as much
as before.

* `SCOPED_FIELDS` — `id` plus the nine fields `schema_steps` already indexes on every kind that
  declares them.
* `KIND_SCOPED_FIELDS` — `IndexEvent.aggregate_id`, `Suppression.target_kind`,
  `Suppression.target_id`, `MaintenanceJob.input_fingerprint`. These are indexed on **one kind
  each** by the v6 step, so they are refused elsewhere. `SyncRun` also declares
  `input_fingerprint` and is refused, which
  `test_a_kind_specific_scoped_field_is_refused_on_another_kind` asserts.

`migrations._v6_indexes()` derives its knowledge half from `KIND_SCOPED_FIELDS` rather than
repeating it, so a field cannot join the allow-list without the index that makes it bounded;
`test_every_kind_scoped_field_has_an_index_in_the_v6_step` asserts the containment.

Scoping `Entity` or `Fact` by generation raises. They are the shared graph and have no
`generation_id` column, so the honest answer is a refusal, not an empty list.

## Which consumer uses which key, and why (M3)

| Caller | Key | Why it cannot use the other |
| --- | --- | --- |
| `native_write` | `ids` | Reads `existing` to find a **prior** row before any generation is known; `generation_id = row.get(...) or (prior or {}).get(...)` is the fallback that keeps untagged legacy writes working. |
| `native_mutation` | `ids` | Decides which argument strings are native ids by membership, and its cross-generation check is only meaningful while rows of *other* generations are visible. |
| `generation_checksums` | `generation_id` | Wants exactly one generation's dense and native rows. |
| `staged_prose._inventory` | `generation_id` | Same. |
| `generation_counts` | `generation_id` | Same. |
| `source_serves_legacy` (CC1) | `where` | Scopes by `aggregate_id` / `target_kind`+`target_id`, neither of which is a generation. |
| legacy lane (ruling 14, opus-18) | `source_id` + `untagged` | Wants the rows of a source that **no** generation owns; `generation_id=None` already means "do not filter". |

`native_mutation` collects every string in `args`/`kwargs` and does one `_native_rows(kind,
ids=candidates)` per kind, so membership is preserved exactly and the work is bounded by the
argument size. Both guards are covered by tests:
`test_native_mutation_still_refuses_an_edge_across_two_generations` and
`test_native_mutation_still_admits_an_edge_to_an_untagged_legacy_row`.

### Ruling 14: untagged rows as one bounded query

Added at the orchestrator's request for the urgent fix worker (opus-18) that owns
`context.py`/`status.py`. `_native_rows(kind, *, source_id=None, untagged=False)` answers "the
rows of this source that no generation owns" in **one** query on every backend, so that lane need
not filter in Python:

```cypher
-- Symbol / DataObject / Commit: source_id is a column, and already indexed by base.CONSTRAINTS
MATCH (n:Symbol) WHERE n.generation_id IS NULL AND n.source_id = $source_id RETURN n AS n

-- Passage: ownership is the FROM edge, so scoping by source makes that edge required
MATCH (n:Passage) WHERE n.generation_id IS NULL
MATCH (n)-[:FROM]->(s:Source {id:$source_id})
RETURN n AS n, s.id AS source_id
```

`untagged` is a separate key rather than `generation_id=None` because `None` already means "do
not filter", and the two questions must not be spelled the same way. `generation_id=` and
`untagged=True` together raise, as does `untagged` on `Entity`/`Fact`.

`IS NULL` was probed directly on `real_ladybug` 0.15.3 and works, including combined with a
`source_id` equality. `test_untagged_rows_of_a_source_are_one_bounded_query` asserts the managed
source's staged row is invisible to that key while remaining visible under `generation_id=`, on
both backends.

## Byte-identical results

Generation ids are random per run, so no golden checksum can be pinned. Instead
`tests/unit/test_generation_scoped_reads.py` keeps the reviewed whole-database enumeration
verbatim as `reference_relationships` and asserts the scoped passes reproduce it row for row
(`test_scoped_relationships_equal_the_reviewed_unscoped_enumeration`). The unscoped forms of
`_native_rows` and `_knowledge_rows` remain available and act as their own oracles.

`_native_relationships` was the one helper whose algorithm changed. Question 3's two constraints
are honoured:

1. **Edges with exactly one endpoint in `ids` are still returned.** Pass 1 is
   `WHERE (a.id IN $ids OR b.id IN $ids)`, so a crossing edge arrives with its far endpoint and
   `ValueError("Native relationship crosses generations")` and
   `ValueError("Missing shared graph endpoint")` both still fire.
   `test_scoped_relationships_equal_the_reviewed_unscoped_enumeration` asserts a partial
   selection raises identically in both implementations.
2. **The two-hop closure gets a second scoped pass.** The `MENTIONS`/`STATES` hop can add nothing
   pass 1 did not already reach (its left side is a `Passage`, already selected), so only the
   `SUBJECT`/`OBJECT` hop is walked, with `rels=("SUBJECT", "OBJECT")`.

Pass 3 takes edges with **both** endpoints in `reachable - ids`, which is disjoint from pass 1 by
construction, so the union needs no de-duplication and the multiset matches. `sorted(result,
key=canonical_json)` means enumeration order never entered the checksum.

## Index backing (M4)

Four `generation_id` indexes on the native tables, plus the three columns CC1's serving predicate
filters on and the one `_assert_generation_writable` filters on:

```
CREATE INDEX symbol_generation IF NOT EXISTS FOR (n:Symbol) ON (n.generation_id)
CREATE INDEX data_object_generation IF NOT EXISTS FOR (n:DataObject) ON (n.generation_id)
CREATE INDEX commit_generation IF NOT EXISTS FOR (n:Commit) ON (n.generation_id)
CREATE INDEX passage_generation IF NOT EXISTS FOR (n:Passage) ON (n.generation_id)
CREATE INDEX knowledge_indexevent_aggregate_id IF NOT EXISTS FOR (n:IndexEvent) ON (n.aggregate_id)
CREATE INDEX knowledge_suppression_target_kind IF NOT EXISTS FOR (n:Suppression) ON (n.target_kind)
CREATE INDEX knowledge_suppression_target_id IF NOT EXISTS FOR (n:Suppression) ON (n.target_id)
CREATE INDEX knowledge_maintenancejob_input_fingerprint IF NOT EXISTS FOR (n:MaintenanceJob) ON (n.input_fingerprint)
```

**A schema-version bump was required; here is why it was the only way.** They are declared twice
on purpose:

* `store/base.py`'s `CONSTRAINTS` reaches a **new** store, at `_ensure_legacy_schema` time.
* `store/migrations.py`'s **v6** step reaches an **existing** one.

`migrate_store` returns early when the journal already says the store is
current, and that early return is *before* `_ensure_legacy_schema` — which is called from nowhere
else. So `base.CONSTRAINTS` alone would never reach a store that is already migrated. Appending
the statements to the v2–v5 step lists instead is not available either: `check_compatibility`
validates each historical journal row against `len(schema_steps(store, version=version))`, so
growing an older version's step list invalidates every existing store's journal.

v5 is therefore frozen exactly as v2–v4 were: `V5_DESCRIPTOR` is a JSON literal, `V5_CHECKSUM` is
derived from it, `_descriptor(5)` returns the literal, and `SUPPORTED_CHECKSUMS[5]` keeps its
recorded value `45745388d17d797b5c67879c98c80f53d0507cad28b0d6f60fec4268ee032619`. The v1–v5
history is preserved and a v5 store still validates. `validate_physical_schema` gains a
`version >= 6` block that checks each index exists as a `RANGE` index, so a completion row that is
not backed by the actual indexes is refused — the guard M4 asked for.

**Ladybug has no index story, and this is stated rather than worked around.** Probed directly
against the installed `real_ladybug` 0.15.3:

```
CREATE INDEX symbol_gen IF NOT EXISTS FOR (n:Symbol) ON (n.generation_id)
  -> RuntimeError: Parser exception: Invalid input <CREATE INDEX symbol_gen>:
     expected rule oC_SingleQuery (line: 1, offset: 13)
CREATE INDEX symbol_gen ON Symbol(generation_id)
  -> RuntimeError: Parser exception: Invalid input <CREATE INDEX symbol_gen>
CALL CREATE_INDEX('symbol_gen','Symbol','generation_id')
  -> RuntimeError: Catalog exception: function CREATE_INDEX does not exist.
```

There is no secondary-index DDL in the dialect at all, so Ladybug's v6 step list is empty and its
scoped reads are bounded **by the query predicate only**. Ladybug is the CD9 acceptance backend,
so CD9 should record that the index-backed half of this bound is proven on Neo4j, not on the
acceptance backend. `WHERE n.id IN $ids` and `WHERE n.generation_id = $g` were both confirmed
working on 0.15.3, including with an empty list parameter; scoped readers short-circuit to `[]`
before issuing a query when the id set is empty regardless.

## Quadratic Python loops (M5)

Query scoping does not fix a loop that rescans a list per row. Four were removed:

| Site | Was | Now |
| --- | --- | --- |
| `generation_checksums` bindings loop | rebuilt the full observation list per binding, O(bindings x exact) | one `observed_objects` set, built once |
| `generation_checksums` native loop | scanned every binding per native row, O(natives x bindings) | one `bound` set keyed by `(native_kind, native_id)` |
| `_validate_managed_native` | read every `GenerationMember` per row inside `native_write`'s loop | `selected=` passed in, read once per generation per call |
| `_knowledge_get` | `next(r for r in _knowledge_rows(name) ...)`, a whole-table read **per call**, and it is called per row by both the checksum and every managed native validation | `where={"id": record_id}`, one bounded query |

`native_write` also now resolves the `Generation` row and its writability check once per
generation rather than once per row.

The last row of that table was the dominant cost and is not named in M5; it is the one that made
the observation and binding loops expensive in the first place.

## Measured

Fake store, `time.process_time()` around `generation_checksums` alone, symbols with a binding and
an observation each:

| rows | before (`7a0c719`) | ratio | after | ratio |
| --- | --- | --- | --- | --- |
| 50 | 0.0055 s | - | 0.0044 s | - |
| 100 | 0.0262 s | 4.79x | 0.0082 s | 1.86x |
| 200 | 0.2009 s | 7.67x | 0.0133 s | 1.62x |
| 400 | 1.6867 s | 8.39x | 0.0291 s | 2.19x |
| 800 | not measured | | 0.0669 s | 2.30x |
| 1600 | not measured | | 0.1103 s | 1.65x |

Before, doubling the generation multiplied the seal by roughly **eight**. After, it roughly
doubles it: linear. The `before` column stops at 400 rows because the same run extended to 2,000
rows had not finished after ten minutes, which is the defect stated as a measurement -- at 400
rows the old code already costs 1.69 s against the new code's 0.029 s, a 58x gap that widens with
every doubling.

`test_sealing_is_linear_in_the_generation` asserts eight times the rows costs under 24x, which
leaves room for constants and for the checksum's own sort without admitting a rescan per row. The
old code would have measured ~300x on that same comparison.

**At the ceiling.** `test_sealing_at_the_symbol_ceiling_completes` builds a generation of
`CODE_MAX_SYMBOLS_PER_SOURCE` = **50,000** symbols (`codegraph/model.py:41`, referenced rather
than copied), each with a binding and an observation, by direct injection into the Fake store's
tables — the write path is proven by the other tests, and going through `add_symbols` here would
measure batching rather than the seal. Fixture build **2.2 s**, seal **3.51 s**, and the native
representation's `row_count` is asserted to be exactly 50,000. Extrapolating the old code's
eightfold-per-doubling from its 400-row measurement, the same seal is seven doublings away and
does not complete; this is the CD1 criterion "sealing a generation at the symbol ceiling is
linear in the generation in CPU as well as in queries", met on the Fake store.

CD9's note stands: a multi-hundred-file fixture is not large enough to have caught this, which is
why the ceiling is exercised directly here.

Query counts, `native_write` of one batch (`test_batched_writes_do_a_constant_number_of_reads_per_batch`):

| batch size | read calls before | read calls after | whole-table reads after |
| --- | --- | --- | --- |
| 4 | 54 | 9 | 0 |
| 16 | 210 | 9 | 0 |
| 64 | (not measured) | 9 | 0 |

Before, reads grew with the rows (~13 per row). After, the count is **9 regardless of batch
size** -- constant per batch, which is stronger than the O(N/B) the brief asks for -- and none of
the nine is a whole-table read. The nine are: 4 `Generation`, 2 `MaintenanceJob`, 1
`IndexManifest`, 1 `GenerationMember`, 1 `Symbol`. `test_writing_in_batches_never_does_a_whole_table_native_read`
separately asserts no native read in the whole write loop named no scoping key.

## Neo4j query shapes for the orchestrator's parity run

Neo4j is root-owned and was not run here. The shapes this slice introduces:

```cypher
-- _native_rows, non-Passage, by id (backed by the existing id uniqueness constraint)
MATCH (n:Symbol) WHERE n.id IN $ids RETURN n AS n

-- _native_rows, non-Passage, by generation (backed by the new v6 index)
MATCH (n:Symbol) WHERE n.generation_id = $generation_id RETURN n AS n

-- _native_rows, Passage: the owning Source folded in, one statement instead of one per row
MATCH (n:Passage) WHERE n.generation_id = $generation_id
OPTIONAL MATCH (n)-[:FROM]->(s:Source)
RETURN n AS n, s.id AS source_id

-- _edges_touching pass 1 and pass 2, per (a_kind, rel, b_kind) in the eleven specs
MATCH (a:Symbol)-[r:DEFINED_IN]->(b:Passage) WHERE (a.id IN $ids OR b.id IN $ids)
RETURN a.id AS a, b.id AS b, properties(r) AS r

-- _edges_touching pass 3
MATCH (a:Entity)-[r:SYNONYM]->(b:Entity) WHERE a.id IN $ids AND b.id IN $ids
RETURN a.id AS a, b.id AS b, properties(r) AS r

-- _knowledge_rows scoped
MATCH (n:GenerationMember) WHERE n.generation_id = $generation_id RETURN n.<field> AS <field>, ...
MATCH (n:IndexEvent) WHERE n.aggregate_id = $aggregate_id RETURN ...
MATCH (n:Suppression) WHERE n.target_kind = $target_kind AND n.target_id = $target_id RETURN ...
```

Worth targeting in parity: the `OPTIONAL MATCH` passage owner join (it returns `source_id` as
`None` for an orphan passage, where the old code returned `None` too), and `properties(r)` under
the new `WHERE`.

## Commands

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_scoped_reads.py \
  tests/unit/test_generation_store.py tests/unit/test_generation_counts.py \
  tests/unit/test_staged_prose_writer.py -q -o addopts='' -W error
```

CD1 CHECK result: **85 passed** (`/tmp/hippo-cc2-cd1.log`), exit 0.

```
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_generation_scoped_reads.py \
  tests/unit/test_generation_store.py tests/unit/test_prose_generation.py \
  -k "reopen or publish" -q -o addopts='' -W error
```

Ladybug results: `test_generation_scoped_reads.py test_generation_store.py` **56 passed, 1
skipped** (`/tmp/hippo-cc2-ladybug.log`); `test_prose_generation.py -k "reopen or publish"`
**9 passed, 58 deselected** (`/tmp/hippo-cc2-ladybug-prose.log`); and because v6's step list is
backend-specific, `test_store_migrations.py test_policy_migration.py test_generation_counts.py
test_staged_prose_writer.py` **79 passed** on Ladybug too (`/tmp/hippo-cc2-ladybug-mig.log`).

Full Fake unit suite: **4011 passed, 29 skipped, 10 failed**
(`/tmp/hippo-cc2-full2.log`). All ten failures are **pre-existing on `rag-it-all-tibs` HEAD
`7a0c719`** and are not touched by this slice -- the identical ten fail in the unmodified root
tree (`/tmp/hippo-cc2-basefull.log`). `comm -13` of the two failure lists is empty: this slice
introduces no new failure. They are listed under "Pre-existing failures" below.

Ruff: `check` and `format --check` clean on every file touched, including this document.

**Warning filter (fleet rule).** The CD1 command and the Ladybug commands need no filter; they
pass under a bare `-W error`. The whole-suite sweep used **form (b)**, the command-line filter
`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`,
because that run collects modules that import `fastapi.testclient` at module level. No ini-wide
`filterwarnings` was added and no test gained a marker.

## Deviations from the brief

1. **`src/hippo/store/knowledge.py` was not in the brief's file list.** `_knowledge_rows` and
   `_knowledge_get` live there, not in `generations.py`. Ownership of those two query methods was
   granted by the orchestrator before any edit, along with the `where=` allow-list shape and
   narrow read-call access to `staged_prose._inventory`.
2. **Three unlisted test files needed a one-line signature fix**, each forced by the new keyword
   arguments rather than by a behaviour change: `tests/unit/test_generation_counts.py` and
   `tests/unit/test_prose_generation.py` monkeypatch `_native_rows` / `_knowledge_rows` with
   helpers that took the kind positionally (now `(kind, **scope)`), and
   `tests/unit/test_generation_store.py::test_schema4_freezes_v3` asserted
   `CURRENT_SCHEMA_VERSION == 5`. `tests/unit/test_store_migrations.py` gained version 6 in its
   history assertion, which the brief allows for a new schema step.
3. **`_inventory` is in `src/hippo/knowledge/staged_prose.py`**, inside the brief's do-NOT-touch
   package. Only its three read calls were switched, under the orchestrator's narrow grant.
4. **Two indexes beyond M4's four** (`MaintenanceJob.input_fingerprint`, and the three CC1
   columns) were added so that every field on the `SCOPED_FIELDS` allow-list is genuinely
   index-backed. Without them the allow-list would have promised a bounded query it could not
   deliver on Neo4j.

## Pre-existing failures on `7a0c719` (not this slice)

Ten unit tests already fail on the unmodified branch HEAD. They are reported here because they
sit in CC1's subject area -- unpublished managed rows escaping a legacy surface -- and the
orchestrator should decide who owns them. Verified by running the same files in the root tree at
`7a0c719` before any CC2 change:

```
tests/unit/test_evidence_context.py::test_managed_source_cannot_enter_legacy_graph_without_published_evidence[None]
tests/unit/test_evidence_context.py::test_managed_source_cannot_enter_legacy_graph_without_published_evidence[access1]
tests/unit/test_evidence_context.py::test_managed_source_cannot_enter_legacy_graph_without_published_evidence[access2]
tests/unit/test_evidence_context.py::test_adding_managed_evidence_invalidates_previously_cached_legacy_scope
tests/unit/test_graph_surface_access.py::test_unpublished_managed_native_rows_never_escape_graph_surfaces[/api/entities?q=orion]
tests/unit/test_graph_surface_access.py::test_unpublished_managed_native_rows_never_escape_graph_surfaces[/api/graph/full]
tests/unit/test_graph_surface_access.py::test_unpublished_managed_native_rows_never_escape_graph_surfaces[/graph]
tests/unit/test_graph_surface_access.py::test_staged_generation_without_artifacts_is_not_a_source_dropdown_entry
tests/unit/test_graph_surface_access.py::test_unpublished_managed_code_never_appears_in_symbol_lookup
tests/unit/test_eval_access.py::test_generated_names_and_source_labels_come_from_visible_evidence
```

The symptom is a managed source's staged passages appearing in the legacy graph
(`{passage.source_id for passage in graph.passages}` contains the managed source as well as the
legacy one). That is question 1's "legacy graph fall-through" and CD2's subject, not CD1's.

## Journal fixtures updated for v6

A new schema version means every fixture that rewinds or enumerates the journal has to know about
it. These are mechanical and carry no behaviour change:

* `test_policy_migration.py`: `CURRENT_SCHEMA_VERSION == 6`; three `schema_version()["version"]`
  assertions; two history lists; the checksum map now expects `5: m.V5_CHECKSUM,
  6: m.MIGRATION_CHECKSUM`; the two rewind fixtures drop version 6 as well as 5/4/3.
* `test_store_migrations.py`: history set gains 6.
* `test_derived_generation_store.py`, `test_generation_store.py`: `CURRENT_SCHEMA_VERSION == 6`.

That the checksum map assertion had to split `5` from `6` is the freeze working: v5 keeps
`45745388...` and only v6 carries the newly derived `MIGRATION_CHECKSUM` `4b639a6b...`.
