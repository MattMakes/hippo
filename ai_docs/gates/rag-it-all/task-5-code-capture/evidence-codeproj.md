# CODEPROJ evidence: a published managed code generation serves its native code arrows

Owner: opus-23. Branch `wp/codeproj`, worktree `.worktrees/codeproj`. Brief
`ai_docs/handoffs/briefs/fix-code-projection.md`. The spawn base was `492cb4c`; before any commit
the orchestrator moved it to `b2754f6` (`rag-it-all-tibs`), so the PA2-4 status fix `63aae1e` is
in the base and the status consistency test below could be written against it. Finding: CC11's
probe (`/tmp/hippo-cc11-scratch.log`). No gate checkbox is set here.

Commits, three against the brief's "one or two": the Ladybug run found a row-order assumption
in one test after the first commit, and the fix is kept separate rather than amended because
`52ae475` is already cited in the ledger.

* `52ae475`: the projection, the tests and the stub.
* `2e3ad8c`: the crossing-edge test compares its two reads as multisets.
* The commit carrying this file.

## Files

| File | Change |
| --- | --- |
| `src/hippo/knowledge/projection.py` | New `_native_code_relations` (`:304`). `relation()` takes the arrow's `provenance` and gives `PRECEDES` an arrow-only path (`:576-590`). `project_managed_graph` feeds it the native relations (`:594`), and the observation-derived `DEFINED_IN` skips a pair the native read already attached (`:607`). The module docstring now states the ruling 1 exception. It imports `store.code._json_field` on purpose: that is the decoder the legacy `_code_edge_read_row` and `load_modifies` apply to `extra`/`hunk`, and a copy would drift. |
| NEW `tests/unit/test_code_projection.py` | 8 tests, below. |
| `tests/unit/test_evidence_access.py` | `EvidenceStore._edges_touching` returning `[]`, granted by the orchestrator (option (a)). This read-contract stub binds native code rows but holds no native relation. Without the method, `test_derived_projection.py::test_original_only_graph_ids_and_fingerprints_are_unchanged` raised `AttributeError`; with it, that test keeps its pinned version `315054166138069197` and fingerprint unchanged. |
| NEW `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-codeproj.md` | This file. |

`git diff --stat b2754f6 -- src/hippo/knowledge/code_binding.py src/hippo/knowledge/staged_code.py
src/hippo/knowledge/code_history.py src/hippo/ingest src/hippo/store tests/fakes src/hippo/status.py
src/hippo/context.py` is empty.

## Item 1: `DEFINED_IN` reads the native rows; `code_binding` emits nothing new

Two routes were open. `code_binding` could emit binding dependencies on code derived records, the
way the prose closure carries them. Or the projection could read the generation's sealed native
`DEFINED_IN` rows together with each node's `NativeBinding`. The second was chosen, for three
reasons.

1. **Identity is unchanged by construction.** A binding dependency changes each code view's
   dependencies. That changes its `view_fingerprint`, its `RetrievalView` and `DerivedRecord`
   ids, and the passage id, which `generation_passage_id(..., retrieval_view_id=...)` derives.
   Ruling 10 requires a changed derivation to be a different generation, so an honest version of
   that change bumps `CODE_BINDING_RULE_VERSION` and with it `generation_id`. The route taken
   changes no evidence writer: the diff above is empty, so every bundle, checksum and
   `generation_id` is what `b2754f6` produces. The first test also asserts that projecting
   leaves `validate_generation_seal` returning the same manifest and `graph_version` unchanged.

   Pinned by number: the fixture's only per-run input is its app ids. The source id enters
   generation identity and is `store.base.new_id()`, which is `uuid4().hex[:12]`. With that
   function replaced by a counter, `test_code_generation.py`'s world builds
   `generation-2546d2bf484566dbdbd256d8a3b690e4bab1f16d1c5e2fcb666514e8157cd352` in three runs:

   * from `b2754f6`'s `src/`, in a throwaway detached worktree loaded through `PYTHONPATH`, since
     removed (`/tmp/hippo-codeproj-identity-base.log`);
   * from `52ae475`, twice (`/tmp/hippo-codeproj-identity-head-1.log`,
     `/tmp/hippo-codeproj-identity-head-2.log`).

   The unpinned ids elsewhere, CC11's `generation-b4c1…` and this slice's first probe
   `generation-da09…`, differ only through that random source id.
2. **The other route needs files this brief does not own.** It also removes checks rather than
   adding code. `CodeEvidenceBundle._check_membership` (`code_binding.py:459-463`) refuses
   `input_binding_ids`, and `_check_references` (`:492-494`) refuses any dependency that is not a
   span. `code_history.py:669` refuses binding ids on commit views. `staged_code._groups` writes
   derived views before native rows and bindings, so a binding dependency could not be validated
   at write time.
3. **The evidence stays exact.** The native `DEFINED_IN` pairs are `staged_code.code_relations`'
   `chunk.defines` restricted to bound nodes: the same `defines` the legacy `link_definitions`
   writes. An arrow is emitted only when the node's authorized binding span lies inside the
   target passage's exact original closure (`RetrievalEvidence.original_span_ids`).
   `support_span_ids` names that span. On the fixture, every binding span is its passage's anchor.

## Item 2: one scoped read per selected generation

`store._edges_touching(ids, both=True, rels=staged_code.RELATION_KINDS)`, once per selected
generation. `ids` is the union of two sets the projection already holds: that generation's
authorized bound native ids, and its projected native passage ids (the `aliases` from
`_safe_vectors`). `both=True` returns only edges whose two endpoints are both in `ids`. An edge
to another generation's node, to an unbound or unauthorized node, or to a passage this proof
does not project is never returned.

`_native_relationships(generation_id=...)` was not used. It reads four native row kinds, walks
the Entity/Fact closure, and raises on a crossing edge rather than restricting it. PA2-4's
finding 2 names the `_edges_touching` form as the cheaper one.

Mapping:

* A native node becomes every knowledge object its bindings name. Two overloads sharing one
  native ID yield the cross product.
* Each arrow keeps the legacy loader's kind, weight, provenance and extra (`GraphIndex.load`).
  - `CODE_EDGE` keeps its row's `kind`, `omega` and `provenance`, and its `extra` decoded from
    JSON text through `store.code._json_field`.
  - `MODIFIES` keeps its `omega`, and its `hunk` is decoded the same way.
  - `DEFINED_IN` and `PRECEDES` have weight 1.0 and provenance `""`.
* Each arrow adds `generation_id` and `support_span_ids`, the endpoints' binding spans.
* `PRECEDES` is an arrow only, with no igraph `Edge`, as in the legacy loader. `DEFINED_IN`,
  `CODE_EDGE` and `MODIFIES` fold into the pair's code term, as `_add_code_term` does.
* `_assemble` applies `canonical_arrows` to every bucket.

Every statement goes through `store.base.by_ids`, so no `IN <list>` predicate is used.

**Neo4j (root-owned, not run).** Each selected generation issues 8 statements of the shape
`UNWIND $ids AS wanted_id MATCH (a:<A> {id: wanted_id})-[r:<REL>]->(b:<B>) RETURN a.id AS a,b.id AS
b,properties(r) AS r`:

* `CODE_EDGE`: Symbol→Symbol, Symbol→DataObject, DataObject→DataObject
* `DEFINED_IN`: Symbol→Passage, DataObject→Passage, Commit→Passage
* `MODIFIES`: Commit→Symbol
* `PRECEDES`: Commit→Commit

Suggested lines:

```
HIPPO_TEST_STORE=neo4j .venv/bin/pytest tests/unit/test_code_projection.py -q -o addopts='' -W error
HIPPO_TEST_STORE=neo4j .venv/bin/pytest tests/unit/test_derived_projection.py tests/unit/test_code_generation.py -k "publish" -q -o addopts='' -W error
```

## Arrows before and after

`test_code_generation.py`'s 7-file world (three commits):

| | code nodes | sidecar rows | arrows by kind |
| --- | --- | --- | --- |
| before (CC11; RED at `b2754f6`) | 14 | 14 | `{}` |
| after | 14 | 0 | `DEFINED_IN 14, MODIFIES 10, CONTAINS 7, PRECEDES 2` (33, equal to the sealed relations) |

The sidecar drops because every node now reaches a passage that cites its binding, so the
existing `attached_code` rule no longer needs a `StructuralCodeEvidence` row for it.

The same world with `src/billing.py` added in a fourth commit, which imports `orders.helper` and
calls within itself: `DEFINED_IN 18, MODIFIES 13, CONTAINS 9, INVOKES 2, IMPORTS 1, PRECEDES 3`.
The two `INVOKES` are `via_import` at 0.9 and `same_file` at 1.0; the `IMPORTS` is `import_path`
at 0.95.

Status on the 7-file world: `_audience_inventory`'s `stats.code_edges` and the code card went
from 0 to 7, equal to PA2-4's source row (`edges_by_kind == {"CONTAINS": 7}`, `edges == 7`).

## Parity

One repository, the billed tree above cloned from the activation suite's origin, runs through
the legacy lane (`add_repo` with no actor), then converts through the managed lane (`reindex`
with an actor). The comparison key per arrow is (kind, source key, target key, omega,
provenance, extra minus `generation_id`/`support_span_ids`). The endpoint keys carry no
namespace: `(path, qualname, kind)` for a symbol, the SHA for a commit, `(kind, qualname)` for a
data object, the passage text for a passage.

| kind | legacy | managed | difference |
| --- | --- | --- | --- |
| DEFINED_IN | 19 | 18 | 1 on the unbound module |
| MODIFIES | 14 | 13 | 1 on the unbound module |
| CONTAINS | 11 | 9 | 2 on the unbound module |
| PRECEDES | 3 | 3 | none |
| INVOKES | 2 | 2 | none |
| IMPORTS | 1 | 1 | none |
| REFERS_TO | 2 | 0 | the managed lane writes none |
| total | 52 | 46 | 6 |

Documented differences, which the test asserts exactly:

1. **`REFERS_TO`.** The managed lane writes none. `staged_code.RELATION_KINDS` is
   `CODE_EDGE/DEFINED_IN/MODIFIES/PRECEDES`, while the legacy indexer draws `REFERS_TO` from a
   prose passage to the code it names.
2. **A node the managed lane leaves unbound.** Here that is the TypeScript module `web.index`.
   `web/index.ts` holds only declarations, so the module has no passage of its own and appears
   only in its first declaration's `defines`. `materialize_code_evidence` binds a chunk's own
   `symbol_id` (`code_binding.py:1077-1085`). The module therefore has no native row, and
   `code_relations` drops every relation touching it. The coordinator records this as
   `unbound_nodes: 1`, which the test checks.

After removing those two, the multisets are equal. Not compared, because they are not arrows:
`SYNONYM` (undirected, and legacy-only) and community labels. History depth is 200 in the
legacy settings; both lanes read all four commits.

## Tests (`tests/unit/test_code_projection.py`)

The oracle for sealed relations is `store._native_relationships(generation_id=...)` (CC2's
closure read). The projection itself uses `_edges_touching`, so the oracle never goes through
the read under test.

| Test | Brief requirement | What it proves |
| --- | --- | --- |
| `test_a_published_code_generation_projects_every_relation_it_sealed_and_writes_nothing` | RED probe; item 2; identity | Arrow kinds equal the sealed relations (33); every arrow names the generation; the seal and `graph_version` are unchanged by projecting. |
| `test_each_bound_node_is_defined_in_the_passage_whose_originals_hold_its_binding_span` | item 1 | One `DEFINED_IN` per code node; `support_span_ids == [binding span]`; the span is in the passage's closure and in `original_citations`; the sidecar is empty. |
| `test_code_edges_keep_their_native_weight_provenance_and_extra_in_canonical_order` | item 2 | On the billed tree, `CODE_EDGE` arrows equal the stored rows by (kind, omega, provenance, extra); buckets are canonical; a `PRECEDES` arrow adds no `precedes` code term to igraph (no pair, or a pair without that term), while every other kind's pair carries its term; `view_fingerprint` is equal across two loads. |
| `test_a_staged_generation_adds_no_arrow_until_it_publishes` | item 3 | At the coordinator's `seal` step, G2 holds all its relations (including `INVOKES`) and the served arrows equal G1's. After publication they equal G2's sealed relations, all naming G2. |
| `test_an_edge_crossing_into_another_generation_is_never_read_and_fails_the_view_closed` | item 2 | Crossing `CODE_EDGE`s are placed beneath the writer, active G2 to retired G1 and back. Re-running the projection read with its captured arguments returns the same relations, compared as a multiset because a store promises no relationship order. The next session raises `SnapshotUnavailable`, because snapshot acquisition re-validates the seal and its native read refuses a crossing edge. |
| `test_a_tombstoned_code_source_projects_no_code_arrow` | item 3 | After the tombstone, no arrow is served, and the relations are still in the store. |
| `test_the_status_card_and_inventory_count_the_code_edges_the_source_row_counts` | orchestrator's PA2-4 consistency requirement | `stats.code_edges == card.code_edges == sum(row edges_by_kind) == row edges == 7`. |
| `test_one_repository_serves_the_same_code_arrows_through_the_legacy_and_the_managed_lane` | item 3, parity | The table above, with exactly the two documented differences. |

Fixture reuse: `world`, `build`, `_commit` and `head_of` come from `test_code_generation.py`;
the activation `world` (imported as `activation_world`), `legacy_indexed` and `CLONE_URL` from
`test_managed_code_activation.py`; `row_of` and `tombstone` from
`test_managed_source_inventory.py`.

## Runs

Every run is `-o addopts='' -W error` from the worktree. No warning filter was needed: none of
these modules imports `fastapi.testclient` at module level.

| Run | Store | Result | Log |
| --- | --- | --- | --- |
| Baseline, the brief's 4 files + `test_status_code_edges.py` + `test_dense_session.py`, at `b2754f6` | Fake | exit 0, 188 passed | `/tmp/hippo-codeproj-baseline-fake.log` |
| RED, `test_code_projection.py` (first version) | Fake | exit 1: 8 failed on zero arrows or a zero count; the crossing-edge test errored with `SnapshotUnavailable` and was reshaped into its two-layer form | `/tmp/hippo-codeproj-red.log` |
| GREEN, `test_code_projection.py` | Fake | exit 0, 8 passed | `/tmp/hippo-codeproj-green-fake.log` |
| Regression, 12 files (below) | Fake | exit 0, 363 passed, 1 skipped | `/tmp/hippo-codeproj-regress-fake.log` |
| GREEN, `test_code_projection.py` at `52ae475` | Ladybug | exit 1, 7 passed, 1 failed (17m57s). The failure was the crossing-edge test's `read(*args) == relations`: the re-read was equal but reordered. Not a projection defect: the store promises no row order, and the injection reorders the node's stored relationships. The test was fixed to compare multisets | `/tmp/hippo-codeproj-ladybug.log` |
| `test_derived_projection.py test_code_generation.py -k "publish"` | Ladybug | exit 0, 2 passed, 49 deselected (5m35s) | `/tmp/hippo-codeproj-ladybug-publish.log` |
| GREEN, `test_code_projection.py` after the ordering fix | Fake | exit 0, 8 passed | `/tmp/hippo-codeproj-green-fake.log` |
| The crossing-edge test after the ordering fix (`2e3ad8c`) | Ladybug | exit 0, 1 passed (4m01s); with the earlier run's 7, all 8 tests are green on Ladybug | `/tmp/hippo-codeproj-ladybug-crossing.log` |

The regression files: `test_derived_projection.py`, `test_structural_loading.py`,
`test_code_binding.py`, `test_code_generation.py`, `test_status_code_edges.py`,
`test_dense_session.py`, `test_evidence_access.py`, `test_evidence_projection.py`,
`test_access.py`, `test_managed_code_activation.py`, `test_managed_source_inventory.py` and
`test_generation_graph_loader.py`.

Ruff: `ruff check` and `ruff format --check` are clean on `src/hippo/knowledge/projection.py`,
`tests/unit/test_code_projection.py`, `tests/unit/test_evidence_access.py` and this file.

## Findings for the orchestrator (not fixed; outside this brief's files)

1. **Unbound declaration-only modules.** This is a gap in the managed lane, not in the
   projection; it belongs to the owner of `code_binding.py`/`ingest/code_generation.py`. The
   legacy lane serves such a module's node, its `CONTAINS`, `MODIFIES` and `DEFINED_IN`; the
   managed lane has none of them. The parity test pins the gap exactly, so a fix will flip it.
2. **`status._with_code_edges`'s docstring is now stale.** It says "the structural projection
   serves no native `CODE_EDGE` row as an arrow at all". That file is opus-22's.
3. **Overloads can make the card and the row disagree.** Two overloads sharing a native ID
   project as the cross product of their objects. `_audience_inventory` counts arrows, so the
   card would then exceed PA2-4's row count, which counts native rows. The fixture has no such
   overloads.
4. **Cost.** Each projection build does one `_edges_touching` per selected generation that has
   bound code nodes: 8 bounded statements on Ladybug and Neo4j, one pass over the relation dicts
   on Fake.
