# Evidence: deterministic fact order, so an unchanged corpus has one view fingerprint

Branch `wp/factorder`, worktree `.worktrees/factorder`. Base `rag-it-all-tibs` `c9f140e` (the HEAD
named in the spawn message; the rulebook's `26f9a55` predates the `wp/pa4d` merge).
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, `mcp` pinned to 2.1.1 per the rulebook.

This closes the open finding recorded in `evidence-pa4d.md`, section "Open finding: LadybugDB
returns extracted facts in an arbitrary order".

Files created: `tests/unit/test_fact_order_determinism.py`, this file.
Files modified: `src/hippo/hipporag/graph_index.py`, `src/hippo/knowledge/projection.py`.
Nothing under `src/hippo/store/`, `src/hippo/web/`, `evals/`, `analysis/`, `ingest/`,
`dense_session.py`, `query_access.py`, `replay.py`, `docs/`, the checkpoint or any `GATES.md` was
touched. `tests/unit/test_graph_index.py` and `tests/unit/test_structural_loading.py` were owned but
needed no change — they pass unaltered, which is itself the statement that no public signature moved.

## The defect, reproduced

Two consecutive loads of one unchanged corpus produced two different `view_fingerprint` values on
`HIPPO_TEST_STORE=ladybug`. Probing the sample corpus (`legacy_sample`, 34 extracted facts) three
times per backend, before the fix:

| | fact-id order stable across loads | `view_fingerprint` stable | ids already in id order | per-fact `passage_ids` sorted |
|---|---|---|---|---|
| Fake | yes | yes | **no** | yes (all facts single-passage) |
| Ladybug | **no** | **no** | **no** | yes (all facts single-passage) |

So the Fake store is stable but *arbitrary*: its order is `dict` insertion order, which hides the
defect in-process and is not a definition anyone else can reproduce. The probe measured, per load,
the fingerprint, the fact-id list, each fact's `passage_ids` and the flattened `code_out` arrows;
only the fact-id list moved. That the rest of the payload holds still is PA4D's measurement, not a
second one here: its component-by-component comparison reported exactly `['facts', 'fact_vectors']`.

The probe was a throwaway file and is **not committed**. The committed reproducer is
`test_the_store_return_order_never_reaches_the_graph`, which makes the same defect deterministic by
serving the loader its own rows backwards.

## Materialisation point and canonical key

**Point:** one helper pair in `src/hippo/hipporag/graph_index.py`, called by every place that
materialises facts into a `GraphIndex`:

* `_canonical_fact_positions(facts) -> list[int]` — the rule, as a permutation, so the list and
  anything parallel to it are moved the same way. The only place the key appears.
* `canonical_fact_order(facts) -> list[Fact]` — the facts alone, for a caller with no matrix.
* `canonical_facts(facts, embeddings) -> (facts, embeddings, fact_index_of)` — the same order with
  the parallel vector matrix and the id index moved with it.

Call sites, which are exactly the three `GraphIndex` construction sites in `src/`:

| Call site | Helper | Effect |
|---|---|---|
| `GraphIndex.load` (`graph_index.py`) | `canonical_facts` | the fix: every store backend, including Neo4j, loads through it |
| `GraphIndex.scoped` (`graph_index.py`) | `canonical_facts` | a no-op given a canonical parent (a filtered subsequence of a sorted list is sorted); applied so the invariant is local, not inherited |
| `_assemble` (`projection.py`) | `canonical_fact_order` | covers `project_managed_graph` **and** `compose_graphs`, which reaches `GraphIndex` only through `_assemble` |

**Key:** the fact's own stored id (`Fact.id`), never the store's return order. No tiebreaker was
added and none is reachable in practice: the id is a content hash (`make_id("fact-", …)`), and
`fact_index_of` has always been `{fact.id: position}`, so two facts sharing one id were already
indistinguishable before this change. Nothing in the fix leans on that — the helper permutes by
*position*, so a duplicate would keep its own vector row rather than take its twin's.
(`validate_dense_graph` does check `fact_index_of` against the enumeration, but it returns early for
`capability.mode == "legacy"`, so it is not a guarantee a legacy load can rely on.)
The per-fact `passage_ids` list is sorted by the same helper — see "One extension beyond the brief".

No `ORDER BY` was added to any store query, as the brief required: an `ORDER BY` in `ladybug.py`
would fix one backend and leave `compose_graphs` and the Fake store defining their own orders.

### Why not the `GraphIndex` constructor

`__post_init__` was the brief's other option and was rejected on evidence.
`validate_dense_graph` (`src/hippo/knowledge/dense.py:364`) *asserts*
`graph.fact_index_of == {fact.id: i for i, fact in enumerate(graph.facts)}` as a tamper check, and
`tests/unit/test_dense_capability.py::test_bound_sidecar_cannot_outlive_its_projected_vertex_or_original_closure[wrong_fact_index]`
drives a deliberately wrong `fact_index_of` through `replace(...)` and requires a `ValueError`.
Reordering facts in `__post_init__` forces it to rebuild `fact_index_of` as well, which would
silently repair exactly the tampering that test exists to catch. The brief's alternative — "a single
normalisation helper called by `load`, `_assemble`, `scoped` and `compose_graphs`" — has the same
"by construction" reach without disarming a security check.

In `_assemble` the sort is placed **above** `fact_matrix` and the `payload` list rather than around
the `GraphIndex(...)` call: `version` is hashed from the local `facts`, so canonicalising only
inside the constructor would have left `version` hashing the pre-sort order. `fact_matrix` is
`fact_vectors[f.id]`-keyed, so it follows the sorted list with no further change.

## Golden fingerprint test: unchanged and passing

`tests/unit/test_derived_projection.py::test_original_only_graph_ids_and_fingerprints_are_unchanged`
passes **unedited**, with its committed constants intact (`version == 315054166138069197`,
fingerprint `5a1de139…3d8ca0`). It runs the projected path, where facts were already built from
`sorted(triples.items())` with `shown_in = sorted(supports[identity])` — already the canonical
order, so the canonical key is the one the deterministic path had all along and no legacy-only
payload that was already deterministic moved. The reviewed rule from
`task-5-dense-capability/GATES.md` is untouched: `fingerprint_vectors` still chooses canonical
retained vectors the same way for structural and verified views, and this change only permutes the
rows it returns, identically on both sides.

Legacy-only *loads* do get a new fingerprint value, necessarily: their old value was the Fake
store's insertion order, which is the thing that was never reproducible. No committed constant
depends on it (checked: `test_prepared_index.py:260`'s digest is over indexer store writes, not a
loaded `GraphIndex`, and it passes).

## One extension beyond the brief

The brief's key is the fact id. The helper also sorts each fact's own `passage_ids`. Reasons:

* both backends leave that list unordered — LadybugDB builds it with `collect(p.id)` and no
  `ORDER BY` (`store/ladybug.py::_fact_rows`), and the Fake store derives it from `self.statements`,
  a `set` (`tests/fakes/fake_store.py::_fact_row`), whose iteration order is stable only within one
  process. A fact stated by two passages therefore moves in exactly the way the fact list did, in
  the same `facts` payload component named in the finding, and would have re-opened it.
* it is safe: every check that compares a fact's passage ids to a sidecar compares **sets and
  lengths**, never order — `dense.py:450-452`, `dense.py:534-536`, `citations.py:87`. Nothing
  asserts an ordered equality against `LegacyDenseVector.support_passage_ids` or
  `ProseProvenance.support_passage_ids`, and both of those are already built sorted upstream
  (`prose_preparation.py:256`, `_assemble`'s `sorted(supports[identity])`).
  `structural_legacy_graph` builds `support_passage_ids` *from* `fact.passage_ids`
  (`dense.py:307`), so both sides move together by construction.
* no consumer reads the list positionally. `grep -rn 'passage_ids\[' src/` returns one hit and it is
  `prose_preparation.py:510`'s `support_passage_ids[0]`, upstream of any graph. Every read of a
  `Fact`'s own list is membership, a set, a length or a whole-list copy: `status.py:99`,
  `explain.py:275`, `web/routes/graph.py:469`, `retriever.py:368`, `replay.py:94`,
  `graph_index.py:719/767/802`.
* the sample corpus has no multi-passage fact, so nothing else would have exercised it;
  `test_the_store_return_order_never_reaches_the_graph` injects one.

Also outside the strict letter of "own: `projection.py` (`_assemble` only)": the import list at
`projection.py:21-33` gains `canonical_fact_order`. That is the whole of the change outside
`_assemble` in that file.

## Tests

`tests/unit/test_fact_order_determinism.py`, 8 tests:

| Test | What it pins |
|---|---|
| `test_repeated_loads_of_one_corpus_agree_on_facts_and_fingerprint` | three cold `GraphIndex.load` calls are one view |
| `test_loaded_facts_are_ordered_by_their_stored_identity` | the canonical key, and that `fact_index_of` follows it |
| `test_the_store_return_order_never_reaches_the_graph` | the same rows served backwards, with each fact's passage ids reversed, give a byte-identical fingerprint — the defect made deterministic, so it fails on **both** backends without the fix |
| `test_each_fact_keeps_the_vector_row_that_belongs_to_it` | the matrix moved with the list; a reorder that forgot it would score every fact against another's vector |
| `test_a_scoped_and_composed_view_keeps_the_canonical_order` | `_assemble`/`compose_graphs` and `scoped` agree |
| `test_three_sessions_over_one_corpus_prove_the_same_view` | the fingerprint *and* `version` a cold `AppContext` proves |
| `test_a_generated_evaluation_set_reproves_its_own_evidence` | `EvalAccess._authorized` — the deny in the finding |
| `test_a_saved_answer_over_unchanged_evidence_is_still_reusable` | `can_reuse_answer` — the withheld answer in the finding |

Nothing in the file imports a transport, so it runs under a bare `-W error` with no AnyIO filter.
Neither sanctioned form (the per-test marker or the appended command-line filter) was needed
anywhere in this slice, and no `filterwarnings` was added.

### RED

`HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_fact_order_determinism.py -q -o addopts='' -W error`
→ **7 failed, 1 passed**, `/tmp/hippo-factorder-red-ladybug.log`.
`HIPPO_TEST_STORE=fake` on the same file → **3 failed, 5 passed**,
`/tmp/hippo-factorder-red-fake.log`. The Fake run failing three is the point: the five that passed
are the in-process-stability tests the Fake store never broke, and the three that failed are the
order *contract* — an order nobody else can reproduce is not a fixed order.
The one test green on Ladybug before the fix is `test_each_fact_keeps_the_vector_row_that_belongs_to_it`,
a regression guard on the alignment the fix must not lose.

### GREEN

Baseline before any change, for comparison:
`HIPPO_TEST_STORE=fake … test_graph_index.py test_derived_projection.py test_structural_loading.py test_dense_capability.py`
→ **155 passed**, exit 0, `/tmp/hippo-factorder-baseline.log`.

| Backend | Command | Result | Log |
|---|---|---|---|
| Fake | the baseline four + `test_fact_order_determinism.py` + `test_managed_eval_activation.py` `test_eval_access.py` `test_analysis_snapshot_lifetime.py` `test_query_snapshots.py` `test_managed_source_inventory.py`, `-q -o addopts='' -W error` | **253 passed, 1 skipped**, exit 0 | `/tmp/hippo-factorder-fake-green.log` |
| Ladybug | `test_fact_order_determinism.py` `test_managed_eval_activation.py` `test_eval_access.py` `test_structural_loading.py`, `-q -o addopts='' -W error` | **101 passed** in 314.76s, exit 0 | `/tmp/hippo-factorder-ladybug-green.log` |
| Fake (adjacent, not required by the brief) | `test_retriever.py` `test_prepared_index.py` `test_evidence_projection.py` `test_derived_evidence_access.py` `test_rag_replay_access.py` `test_dense_session.py` | **154 passed**, exit 0 | `/tmp/hippo-factorder-fake-adjacent.log` |

The adjacent run was added because reordering `graph.facts` moves `argsort` positions in the
retriever's fact ranking and could have broken an exact-tie ordering under FakeOllama, and because
`test_prepared_index.py` holds a committed digest. Neither moved.

Ruff: `.venv/bin/ruff check` + `ruff format --check` over
`src/hippo/hipporag/graph_index.py src/hippo/knowledge/projection.py tests/unit/test_fact_order_determinism.py`
→ **All checks passed, 3 files already formatted**, exit 0.

## After the fix

Same probe, three loads per backend:

| | fact-id order stable | `view_fingerprint` stable | ids in canonical order |
|---|---|---|---|
| Fake | yes | yes | yes |
| Ladybug | yes | yes | yes |

## For PA7: every fingerprint stored before this commit is stale

The fix changes what an unchanged corpus hashes to, so any `evidence_fingerprint` persisted before
it — a generated evaluation set's, a saved answer's — will not re-prove afterwards and its set will
deny or its answer will be reconstructed rather than reused. That is a one-time cost with nothing to
migrate, for three reasons: on LadybugDB and Neo4j none of those values was reliably re-provable in
the first place (that is the defect); the Fake store, where they were stable, is a test backend and
not a deployment target; and Task 5 is open, so production ingestion is still the legacy pipeline
and no production data holds one. A generated set whose fingerprint no longer proves can be
recreated; nothing is lost but the saved answer's reuse.

## Open finding: one fingerprint is per stored corpus, not per corpus text

Fake and Ladybug still produce *different* fingerprints for the same source text, and that is
correct rather than a residual defect. A per-component digest after the fix shows the remaining
differences are `node_ids`, `passages`, `facts`, `specificity` and `edges` — all of which carry
passage ids, and `make_id("passage-", f"{source_id}:{ordinal}:{text}")`
(`hipporag/indexer.py:148`) derives those from the store-assigned `source_id`. Two stores, or two
runs of one store, assign different source ids to the same text, so cross-backend equality is not a
property a view fingerprint ever had or should have. `fact_vectors`, `passage_vectors`,
`entity_names`, `node_kind`, `code_nodes`, `entity_boost` and `code_out` are byte-identical across
the two backends, which is the parity that was available to prove. What the brief means by "and (by
construction) Neo4j" is satisfied in the stronger sense: the ordering rule is applied above every
store, so no backend can introduce an order of its own.

## Second observation, not fixed and not in scope

`view_fingerprint`'s `code_out` component is
`[asdict(edge) for _, arrows in sorted(graph.code_out.items()) for edge in arrows]`. The *keys* are
sorted; the arrows within one vertex are appended in `store.load_code_edges()` / `load_definitions()`
/ `load_refers_to()` / `load_modifies()` order, which LadybugDB and Neo4j promise no more than they
promise fact order. The corpus in the finding and in these tests has no code nodes
(`code_out` is empty, and the component is stable in every run above), so this is unproven rather
than observed — but it is the same class of defect one layer over, and a code-bearing corpus on the
primary backend is where it would appear. Raised rather than fixed: this brief's DECISION is scoped
to facts, and the arrows are materialised in `load`, `scoped` and `_assemble` in three different
shapes.
