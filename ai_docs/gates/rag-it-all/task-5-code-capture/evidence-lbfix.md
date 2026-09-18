# LBFIX evidence — the Ladybug-only managed-build regression at the merged base

Branch `wp/lbfix`, worktree `.worktrees/lbfix`, base `8f32ec4` (the CC3 merge).
Not a plan slice: an urgent repair of a store defect the merged base carries, found by opus-17
while running the PA8 closure batch's Ladybug line.

## The symptom

`HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py
tests/unit/test_managed_pipeline_activation.py -q -o addopts='' -W error` was 5 failed at
`8f32ec4`, all five in `test_managed_pipeline_activation.py`:

* `test_the_raw_root_and_embedding_cache_appear_only_for_a_managed_build`
* `test_managed_add_refresh_and_conversion_never_destroy_source_wide_evidence`
* `test_a_mixed_bulk_refreshes_managed_evidence_and_converts_without_a_legacy_clear`
* `test_one_lane_failing_asynchronously_leaves_every_other_source_intact`
* `test_a_ladybug_reopen_preserves_pointers_manifests_raw_references_and_the_tombstone`

Every one had the same shape: the managed build did not publish, `managed_activation.py:440`
logged `code=operation_failed`, and the row landed on `stage=refresh_failed`. Fake was green on
the same files, and the orchestrator's Neo4j parity run passed `test_managed_source_lifecycle.py`
at `8f32ec4`, so the defect was Ladybug's alone.

## The bisect

Ladybug, the two files above, in `.worktrees/lbfix`:

| commit | what it is | result | log |
| --- | --- | --- | --- |
| `1e2f112` | last known-green run | **138 passed** (19:55) | `/tmp/hippo-lbfix-bisect-1e2f112.log` |
| `7a0c719` | CC1 | five named tests **pass** (04:49) | `/tmp/hippo-lbfix-five-7a0c719.log` |
| `c461c9c` | **CC2** | five named tests **all fail** (04:09) | `/tmp/hippo-lbfix-five-c461c9c.log` |
| `d56b618` | cc1fix | five named tests all fail (03:55) | `/tmp/hippo-lbfix-five-d56b618.log` |
| `8f32ec4` | CC3, this base | five named tests all fail (03:21) | `/tmp/hippo-lbfix-five-8f32ec4.log` |

`1e2f112` was run over both whole files. The four later commits were run with `-k` over the five
named tests only, because a whole-file run costs 20 minutes each and three workers shared the
machine; the first red merge and the first failing test are the same answer either way. The
first failing test at `c461c9c` is
`test_the_raw_root_and_embedding_cache_appear_only_for_a_managed_build`.

**First red merge: `c461c9c` (CC2, generation-scoped store reads).** What it changed, exactly:

```python
# 1e2f112
if name == "Passage":
    return next((row for row in self._native_rows("Passage") if row["id"] == record_id), None)

# c461c9c
if name == "Passage":
    return next(iter(self._native_rows("Passage", ids=[record_id])), None)
```

The whole-table read with a Python filter became a scoped read, and the scoped read spells its
selection `WHERE n.id IN $ids`. Nothing about CC2's intent is wrong — the whole-table read is the
quadratic this slice removes. The `IN` predicate is what LadybugDB cannot answer.

## The cause

A defect in the engine, not in the pipeline. Probed on **real_ladybug 0.15.3**:

> A list predicate on a **STRING column of a node table** — `WHERE n.id IN $ids`,
> `WHERE p.generation_id IN $generations` — selects the right row but projects that row's string
> properties **from a different row**, when two things are true at once: the node table holds a
> **deleted row**, and the wanted row was written **inside the currently open transaction**.

What comes back is a foreign `title`, an `id` cut to another row's length, and `*_json` bytes
that are not valid UTF-8, which the Python binding raises `UnicodeDecodeError` on while
materialising the row. The engine's own selection is correct — `count(n)` is right and
`substring(n.id, 1, 20)` is right — so the read comes back **quietly wrong** rather than empty or
raised. `= $id`, `MATCH (n:Kind {id: $id})`, `UNWIND $ids AS rid MATCH (n:Kind {id: rid})` and
`WHERE n.generation_id = $gen` are all correct in the same state.

Reduced to a factorial probe over the three conditions (deleted row, prior extraction, open
transaction), only `deleted row + open transaction` is red:

```
deleted=False extraction=False txn=True  -> GOOD  id/title from the wanted row
deleted=True  extraction=False txn=False -> GOOD  id/title from the wanted row
deleted=True  extraction=False txn=True  -> WRONG id truncated to the legacy row's length, title 'Legacy'
deleted=True  extraction=True  txn=True  -> WRONG same
```

Why the managed lane meets all of it: a reindex deletes and rewrites the legacy passages, so the
Passage table has a hole; the managed build writes its passages inside its own transaction and
`_validate_knowledge` reads one back through `_knowledge_get("Passage", id)` before that
transaction commits; and a managed passage id is `passage-` + a 64-character digest while a
legacy one is `passage-` + a 32-character `md5`, so the wrong row's length is *visible* instead
of silently plausible.

The traceback at the base, captured by wrapping `managed_activation.record_build_failure`
(`/tmp/hippo-lbfix-tb1.log`):

```
hippo/ingest/prose_generation.py:599  build_plain_source -> _write_batch
hippo/knowledge/staged_prose.py:144   store.put_knowledge(record)
hippo/store/knowledge.py:716          _validate_knowledge(record)
hippo/store/knowledge.py:627          reference = self._knowledge_get(name, rid)
hippo/store/knowledge.py:472          self._native_rows("Passage", ids=[record_id])
hippo/store/generations.py:764        self.run("MATCH (n:Passage) WHERE n.id IN $ids ... RETURN n AS n, ...")
hippo/store/ladybug.py:349            rows.append(dict(zip(columns, result.get_next(), strict=True)))
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xed in position 8: invalid continuation byte
```

The other failures present as `ValueError` rather than `UnicodeDecodeError` because the same
wrong row reaches a different guard first. Captured the same way at the base
(`/tmp/hippo-lbfix-tb-valueerror.log`):

```
hippo/knowledge/staged_prose.py:195   _seal -> store.generation_checksums(...)
hippo/store/generations.py:1029       validate_prose(self, gen.id, extraction)
hippo/knowledge/derivations.py:286    support = inventory.passage(identity)
hippo/knowledge/derivations.py:236    raise ValueError("Prose support passage crosses generation/source")
```

`inventory.passage` is `self.store._knowledge_get("Passage", identity)` followed by
`row.get("generation_id") != self.gen.id or row.get("source_id") != self.gen.source_id` — the
same read, and the guard fires because the row it got back belongs to another passage. Whether
the corrupt projection raises in the binding or merely returns the wrong `generation_id` depends
on which bytes the wrong row happens to hold; both are the one defect.

The `OllamaError` in the seventh log line is not a defect at all:
`test_one_lane_failing_asynchronously_leaves_every_other_source_intact` fails one lane on purpose
(`Ollama at http://local-model ... HTTP 500`), and that log line is the failure it asks for. That
test was red because its *other* lanes hit the store defect.

All five tests are green after one fix, and nothing in the pipeline was changed.

## The fix

`store/base.by_ids(label, variable="n", *, param="ids", bind="wanted_id")` returns
`UNWIND $ids AS wanted_id MATCH (n:Label {id: wanted_id})`: the id list **drives** the match
instead of filtering it, so every selection is a primary-key lookup. `store/base.unique_ids`
goes with it, because `UNWIND` binds a repeated id twice where `IN` collapsed it and a query
that aggregates over the match would count it twice.

This is the form the Neo4j store already used (`memory.py:264`), which is why Neo4j never had the
bug and why the row-for-row parity between the two stores is restored rather than invented.

Converted (every `IN $list` predicate on a node property that existed in `store/*`):

| site | was | now |
| --- | --- | --- |
| `generations.py` `_native_rows` | `n.id IN $ids` | `by_ids(kind)` heads the MATCH |
| `generations.py` `_edges_touching` | `a.id IN $ids OR b.id IN $ids` | one pass per endpoint, union de-duplicated in Python |
| `generations.py` `_edges_touching` | `a.id IN $ids AND b.id IN $ids` | left pass only, far endpoint filtered in Python |
| `ladybug.py` `get_passages` | `p.id IN $ids` | `by_ids("Passage", "p")` |
| `ladybug.py` `existing_entity_ids` | `e.id IN $ids` | `by_ids("Entity", "e")` |
| `ladybug.py` `get_entities` | `e.id IN $ids` | `by_ids("Entity", "e")` |
| `ladybug.py` `existing_fact_ids` | `f.id IN $ids` | `by_ids("Fact", "f")` |
| `ladybug.py` `get_facts` / `_fact_rows` | `WHERE f.id IN $ids` | `_fact_rows` takes the **head** clause, not a `where` |
| `ladybug.py` `_code_nodes` | `n.id IN $ids` | `by_ids(label)` |
| `generation_counts.py` | `p.id IN $ids` | `by_ids("Passage", "p")` |
| `knowledge/projection.py` `_passage_bindings` | `p.generation_id IN $generations` | `MATCH (p:Passage {generation_id: wanted_generation})` |

`_edges_touching` is the only one whose shape changed rather than its clause. A relationship
exists once per ordered pair, so the two endpoint-driven passes plus a `seen` set reproduce
exactly what the engine's `OR` returned, and `_native_relationships` sorts its result anyway, so
no checksum sees enumeration order.

The `knowledge/projection.py` line was outside this brief's file grant; the orchestrator granted
it after the probe showed the same defect on `p.generation_id IN $gens` (wrong row) against
`p.generation_id = $gen` (right row).

Not converted, deliberately:

* `store/code.py:596` and `store/ladybug.py:1280`, `r.kind IN $kinds` — a **relationship**
  property, not a node column. Two attempts to build a CODE_EDGE the trigger could reach came
  back empty (`/tmp/hippo-lbfix-probe-relkind.log`), so there is no repro to justify rewriting an
  aggregate on a guess. Allowlisted by name in the tripwire test, with that log named in the
  comment.
* `store/migrations.py:307`, `any(label IN labels(n) WHERE label IN $labels)` — a comprehension
  over `labels(n)`, not a stored column. Different shape.

## The pins

Three tests in `tests/unit/test_generation_scoped_reads.py`, CC2's own file:

* `test_an_id_scoped_read_answers_from_the_wanted_row_while_its_transaction_is_open` — builds the
  three-row shape (a deleted row, a legacy row, a managed row written inside the open
  transaction) and asserts `_native_rows("Passage", ids=[...])` and `_knowledge_get` answer from
  the wanted row. **RED before the fix**: `assert 'passage-2222…2222' == 'passage-2222…'` — the id
  came back cut to the legacy row's 40 characters.
* `test_the_public_id_reads_answer_from_the_wanted_row_in_the_same_state` — the same state through
  `get_passages`. **RED before the fix**: returned `[]`.
* `test_no_query_builder_selects_node_rows_with_a_list_predicate` — the tripwire. Scans every
  module of `hippo/store` and `hippo/knowledge` for `<var>.<prop> IN $…`, with the module's
  docstrings and comments removed by `ast` so the rule can quote the defect in prose without
  tripping over itself. **RED before the fix**: nine offenders.

The tripwire exists because this defect is silent. `IN $ids` reads correctly almost everywhere;
only the three conditions above expose it, and by then the wrong row has already entered a
checksum.

## Runs

RED (at the base, `wp/lbfix`): `/tmp/hippo-lbfix-red.log` (Ladybug, 3 failed),
`/tmp/hippo-lbfix-red-fake.log` (Fake, 1 failed — the tripwire; Fake runs no Cypher).

GREEN:

| backend | files | result | log |
| --- | --- | --- | --- |
| ladybug | `test_managed_source_lifecycle.py test_managed_pipeline_activation.py` | **138 passed** (21:33) | `/tmp/hippo-lbfix-green-managed.log` |
| ladybug | `test_generation_scoped_reads.py test_generation_resume.py test_converting_source_serving.py` | 64 passed, 2 skipped | `/tmp/hippo-lbfix-ladybug-slice.log` |
| ladybug | `test_store*.py test_access.py test_analysis_changesets.py test_evals_question_maker.py test_fact_order_determinism.py test_indexer.py test_prepared_index.py` | 289 passed, 1 skipped | `/tmp/hippo-lbfix-ladybug-store.log` |
| ladybug | the nine projection / dense / evidence / managed-surface files | 362 passed | `/tmp/hippo-lbfix-ladybug-projection.log` |
| ladybug | `test_graph_index.py test_retriever.py` | 118 passed | `/tmp/hippo-lbfix-ladybug-graph.log` |
| ladybug | `test_settings_and_safety.py test_ingest_pipeline.py` | 42 passed | `/tmp/hippo-lbfix-ladybug-extra.log` |
| fake | CD1 + CD2 lines + `test_generation_resume.py` | 224 passed, 2 skipped | `/tmp/hippo-lbfix-fake-cd12.log` |
| fake | the same store parity set | 282 passed, 8 skipped | `/tmp/hippo-lbfix-fake-store.log` |
| fake | the same projection set | 361 passed, 1 skipped | `/tmp/hippo-lbfix-fake-projection.log` |
| fake | `test_graph_index.py test_retriever.py` | 118 passed | `/tmp/hippo-lbfix-fake-graph.log` |
| fake | `test_settings_and_safety.py test_ingest_pipeline.py` | 42 passed | `/tmp/hippo-lbfix-fake-extra.log` |
| fake | `test_generation_scoped_reads.py` | 30 passed | `/tmp/hippo-lbfix-fake-scoped2.log` |
| fake | the two managed files + scoped reads + resume + converting | 201 passed, 3 skipped | `/tmp/hippo-lbfix-fake-managed.log` |

`test_settings_and_safety.py` imports `fastapi.testclient` at module level, so those two runs
carry the sanctioned **form (b)** filter on the command line:
`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`.
Every other run is plain `-W error`.

Ruff: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` clean over
`src/hippo/store/base.py src/hippo/store/generations.py src/hippo/store/ladybug.py
src/hippo/store/generation_counts.py src/hippo/knowledge/projection.py
tests/unit/test_generation_scoped_reads.py` and over this document.

Neo4j was not run: it is root-owned here and the orchestrator holds the parity run. The converted
Cypher is the shape `memory.py` already used, so the Neo4j store's own queries are untouched and
`generations.py`'s shared queries move to the form Neo4j prefers (an index seek per id rather
than a label scan carrying a list predicate).

## What is still open

`hippo/store/code.py:596` and `hippo/store/ladybug.py:1280` keep `r.kind IN $kinds`, unprobed.
If a CODE_EDGE repro is ever built, the same `UNWIND` rewrite applies and the allowlist entry in
`test_no_query_builder_selects_node_rows_with_a_list_predicate` comes out.
