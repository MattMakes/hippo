# R21I evidence: the legacy synonym pass never reads a managed code row (R21-B4)

Branch `wp/r21i`, worktree `.worktrees/r21i`, base `e026640`. Brief
`ai_docs/handoffs/briefs/fix-r21-legacy-indexer.md`; finding R21-B4 of
`ai_docs/reports/2026-09-13-code-capture-review.md`.

## The defect

`find_synonyms` (`src/hippo/hipporag/indexer.py:375-413`) builds its key matrix from
`store.load_entity_embeddings()` plus `store.load_code_embeddings()`. The code read had no
generation filter, so every Symbol and DataObject name vector entered the matrix, including a
staging or published generation's rows. `index_source` then wrote the pairs through
`add_synonyms`, and `native_mutation` refused them: a staging generation through
`_assert_generation_writable`, a sealed one through its checksum. Once any repository converts,
a never-managed source whose entity names resemble a managed symbol fails to index, which breaks
ruling 14 ("only untagged rows serve the legacy lane") and the byte-identical legacy lane of CD1
and CD2.

## Ownership grant

`src/hippo/store/ladybug.py` is on the brief's do-not-touch list, but
`LadybugStore.load_code_embeddings` overrides the read and `LadybugStore` does not inherit
`CodeQueries`, so a filter in `store/code.py` could not reach LadybugDB. I asked the
orchestrator (BLOCKED, 2026-09-13), and the reply was: "(a) GRANTED: store/ladybug.py
load_code_embeddings only, adding WHERE n.generation_id IS NULL to its one query (no other line);
mirror the same filter in the Neo4j read (store/code.py) and the Fake so all three backends agree,
and pin it with a test on each backend you can run". The `ladybug.py` diff is that one statement.
`ruff format` wrapped it over three lines because the longer query passed the line length.

## The read changed

`load_code_embeddings` keeps its public name and its shape: `(ids, vectors)`, symbols first and
then data objects, rows without a vector left out. It now returns only rows whose
`generation_id` is null, on every backend:

| Backend | Where | Filter |
| --- | --- | --- |
| Fake | `tests/fakes/fake_store.py:768` | `node.get("embedding") and node.get("generation_id") is None` |
| LadybugDB | `src/hippo/store/ladybug.py:1553` | `MATCH (n:{label}) WHERE n.generation_id IS NULL RETURN n.id AS id, n.embedding AS embedding` |
| Neo4j | `src/hippo/store/code.py:673` | the query below |

The Neo4j shape for root parity (root-owned, not run here):

```cypher
MATCH (n:Symbol) WHERE n.embedding IS NOT NULL AND n.generation_id IS NULL
RETURN n.id AS id, n.embedding AS embedding
UNION ALL
MATCH (n:DataObject) WHERE n.embedding IS NOT NULL AND n.generation_id IS NULL
RETURN n.id AS id, n.embedding AS embedding
```

The predicate is spelled the way CC2's `_native_rows(kind, untagged=True)` spells it
(`evidence-cc2.md`, "Ruling 14"), with no `IN <list>` (`evidence-lbfix.md`). `indexer.py` needed
no change: `find_synonyms` still calls `store.load_code_embeddings()`.

### Callers of `load_code_embeddings`

* `src/hippo/hipporag/indexer.py:391`, `find_synonyms`: the only production caller. It runs in
  step 5 of `index_source`, so every legacy lane reaches it: `add_text`, uploads, `add_repo`
  without an actor, `reindex`, `reindex_all` and bulk.
* `src/hippo/knowledge/projection.py:871`: not a store read. The projection hands
  `find_synonyms` a `SimpleNamespace` whose `load_code_embeddings` is `lambda: ([], [])`.
* Tests: `tests/unit/test_indexer.py:674`, `tests/unit/test_store_code.py:433`, `:442`, `:467`,
  and the new file below.

## Reverse guard (brief requirement 3)

A managed build does not use this path, so it cannot read untagged legacy rows through it. Over
`src/hippo/knowledge/*.py` (which includes `staged_code.py` and `code_binding.py`) and
`src/hippo/ingest/*.py` (which includes `code_generation.py`), the only hits for `find_synonyms`,
`add_synonyms` or `load_code_embeddings` are `projection.py:860-873` (the stub above, which reads
nothing from the store) and a comment at `code_generation.py:560`. The managed code lane computes
its own name vectors in `code_generation._index` and never runs the legacy synonym pass.

## Tests

New file `tests/unit/test_legacy_index_beside_managed.py`, 5 tests on the `store`/`ctx`
fixtures, so the same file runs on Fake, LadybugDB and Neo4j.

The `managed` fixture builds a published code generation and a staging one with
`test_structural_loading.published` (`dimension=DIM`). Each holds a Symbol `OrderService` and a
DataObject `order_service`, bound to the generation's span through a `KnowledgeObject`, a
selected `ObjectObservation` and a `NativeBinding` (the seal refuses an unbound native row). Both
carry the name vector `embed_text(name_text("OrderService"))`, which is exactly the vector of the
legacy entity "order service". An untagged twin pair with the same vector sits on a plain legacy
source, so every test proves the read filters rather than returning nothing.

| Test | What it proves |
| --- | --- |
| `test_the_legacy_key_matrix_holds_only_untagged_code_vectors` | The store pin for each backend: `ids == [twin symbol, twin data object]` in that order, the vectors equal, and the tagged rows still readable with their vectors through `_native_rows(kind, generation_id=...)`. |
| `test_find_synonyms_pairs_a_new_entity_only_with_untagged_code` | The review's function-level reproduction: the pairs' targets are exactly the two twins. |
| `test_index_source_beside_managed_code_links_only_the_untagged_twin` | `index_source` over one prose chunk succeeds, links "order service" to the twin, writes no SYNONYM touching a tagged ID, and leaves the managed state unchanged. |
| `test_a_legacy_code_graph_beside_managed_code_never_pairs_with_a_tagged_node` | The same for the unmanaged repository lane, where a new legacy Symbol is the query. |
| `test_add_text_beside_managed_code_indexes_and_leaves_every_managed_row_unchanged` | `pipeline.add_text` end to end: the source is `ready` with no error, `meta.counts.synonyms > 0`, plus the same three assertions. |

Byte identity: `managed_state` deep-copies, per generation, `_native_rows(kind,
generation_id=...)` for Passage, Symbol, DataObject and Commit (sorted by ID),
`_native_relationships(generation_id=...)` and `generation_checksums(generation_id)`, and
the three indexer tests assert the copy taken after indexing `==` the copy taken before.

The managed-free legacy lane is pinned by the unchanged suites below: `test_indexer.py` (counts,
synonyms, the one-token rule at `:674`) and `test_store_code.py:430-467` (both kinds read,
vectorless rows left out, empty store). No existing test file was edited.

## Before and after

Before is `e026640` (the RED run below); after is `wp/r21i`.

| Probe | Before | After |
| --- | --- | --- |
| `load_code_embeddings` IDs | 6: the 2 twins and 4 tagged rows | 2: the twins |
| `find_synonyms` targets for "order service" | 6, 4 of them tagged | 2: the twins |
| `index_source`, prose chunk | `ValueError: Managed writes require a live generation lease` | succeeds |
| `index_source`, legacy code graph | `ValueError: Native relationship crosses generations` | succeeds |
| `pipeline.add_text` | source `failed` | source `ready`, no error |

Which guard refuses first depends on which generation `native_mutation` checks first; the
fixture holds both, and the reviewer reproduced the sealed refusal ("Sealed native payload or
relationship is immutable") on a published generation alone.

## Runs

All with `-q -o addopts='' -W error` and no warning filter of either sanctioned form. None of
these modules imports `fastapi.testclient` at module level; `test_converting_source_serving.py:414`
imports it inside one test, and every run below passed under `-W error` without a filter.

| Run | Backend | Files | Result | Log |
| --- | --- | --- | --- | --- |
| Baseline at `e026640` | Fake | `test_indexer.py`, `test_ingest_pipeline.py`, `test_converting_source_serving.py`, `test_store_code.py` | 114 passed, 1 skipped | `/tmp/hippo-r21i-baseline-fake.log` |
| Baseline at `e026640` | LadybugDB | same four | 115 passed | `/tmp/hippo-r21i-baseline-ladybug.log` |
| RED | Fake | `test_legacy_index_beside_managed.py` | 5 failed | `/tmp/hippo-r21i-red-fake.log` |
| RED | LadybugDB | `test_legacy_index_beside_managed.py` | 5 failed | `/tmp/hippo-r21i-red-ladybug.log` |
| GREEN | Fake | the new file and the same four | 119 passed, 1 skipped | `/tmp/hippo-r21i-green-fake.log` |
| GREEN | LadybugDB | the new file and the same four | 120 passed | `/tmp/hippo-r21i-green-ladybug.log` |

`/tmp/hippo-r21i-red.log` is the two RED logs concatenated. The one Fake skip is
`test_converting_source_serving.py:366`, "reopen is a LadybugDB persistence assertion" (named by
the `-rs` rerun `/tmp/hippo-r21i-green-fake-rs.log`, same 119 passed, 1 skipped); it is a Fake-only
skip, which is why the LadybugDB counts are one higher (115 = 114 + 1, 120 = 119 + 1).

Ruff: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` over `src/hippo/store/code.py`,
`src/hippo/store/ladybug.py`, `tests/fakes/fake_store.py` and
`tests/unit/test_legacy_index_beside_managed.py`: clean.

## Notes

* No review minor names `indexer.py` or `store/code.py`. R21-m20 (`ingest/pipeline.py:504`)
  belongs to r21c.
* A neighbouring path, not reachable today and not changed here: when a call touches an
  `entity-` or `fact-` ID, `native_mutation` (`store/generations.py:1762-1767`) checksums every
  generation with a ready manifest, and `_native_relationships` includes edges between the
  shared entities a generation's passages reach. A legacy SYNONYM between two entities that a
  sealed generation's passages `MENTION` would therefore change that checksum. No managed lane
  writes native `MENTIONS` or `STATES` today: `link_passage_entities`, `link_passage_facts` and
  `add_entities(` have no call in `src/hippo/knowledge`, `ingest/code_generation.py` or
  `ingest/prose_generation.py`. It is named here for the owners of `store/generations.py`.
