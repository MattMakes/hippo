# AR1 — Architecture review of the merged WP1–WP3 work against PLAN.md

Read-only review of `git diff main...code-graph -- src tests` at `d7187c4` (WP0, WP1, WP2, WP2i, WP3
merged; WP2b and all of WP4 still on their own branches) against `docs/plans/hippo-for-code/PLAN.md`
and the four worker ledger summaries. **0 blockers, 9 fixes, 7 nits.** Nothing was edited or committed.

## Verdict

The architecture the plan chose is the architecture that landed, and it landed cleanly. The
dependency direction holds (`codegraph/` imports stdlib, tree-sitter, sqlglot and `hipporag.text`
and nothing else; the chunker and indexer reach it under `TYPE_CHECKING`; `paths.py` sits in
`hipporag/` because the retriever calls it); all six load-bearing gotchas are verifiable in the code
with a line number, including the two that were nearly shipped wrong in the plan itself (passages
last with the `first_passage_vertex` arithmetic, and the three per-label delete statements); the
scale composes through `build_igraph`/`graph_with_edits` exactly as WP1.4 demanded, and the
inertness claim is pinned by a mixed-memory test that deletes the code nodes out from under an
indexed corpus rather than comparing two corpora. `GraphIndex.load`, `scoped()` and `name_index`
are all linear — **none of the quadratics in this report is in the index build**; they are in the
per-query anchor and path code and in two ingest loops. The three stores are genuinely in step, and
the access story is stronger than the plan asked for: `name_index` is shared with `scoped()` but
every consumer filters through the scoped `idx_of`, and `test_anchors.py:237` and
`test_paths.py:315` pin it.

Two things are worth the orchestrator's attention before release. The first is a behavioural gap,
not a bug: D10's select pass ships, is gated correctly, is replayable in simulations — and its
`drop` decision **cannot change what the model reads**, because the window it judges is exactly the
slice `ask.py` sends (fix 1). That is a consequence of a WP3 decision the plan left open, and it is
one line to fix either way. The second is that `docs/FIDELITY.md` is now literally false in four
places on the merged tip; `wp/wp4d` fixes two of them and does not touch the other two, which the
plan never named (fix 8). Everything else is cost, and the cost findings matter only at the
20k-symbol ceiling spike 3 measured — but that ceiling is reachable (`MAX_CHUNKS` binds at 20,000
passages and one passage per symbol is the new granularity), so they should be fixed before a real
repository is indexed, not after.

**Scope note.** WP2b is not merged, so the `Commit`/`MODIFIES`/`PRECEDES` paths were reviewed only
against `tests/fakes/code_fixture.py::write_commit_history`, never against real git output. WP4 is
in flight in seven worktrees; I reviewed only what is on `code-graph`. The Neo4j `store/code.py`
mixin was spot-checked (the delete sweep, `_with_source_and_degree`, the row shapers), not read
statement by statement — `test_store_code.py` on the Neo4j leg is what covers the rest.

---

## Findings

### Fixes — should change before release

**1. `src/hippo/hipporag/retriever.py:653-671` (with `src/hippo/ask.py:53`) — the select pass's
`drop` cannot change what the model reads.**
`_select` takes its window as `trace.passages[:qa_top_k]` (`:653-654`) and reassembles the list as
`kept + demoted + rest + expanded` (`:671`). `answer_from_trace` then reads
`[p for p in trace.passages if not p.via_expand][:qa_top_k]` (`ask.py:53`) — the *same* slice.
A drop therefore reorders the five passages the answerer reads and never replaces one: nothing from
`rest` is ever promoted, so the citation list and the prompt are byte-identical whether the LLM
dropped a passage or not. PLAN's rule ("dropped passages are ranked below kept ones, never removed")
is implemented literally; it is WP3's own open decision — its ledger records "`_select` window is
the top `qa_top_k`" — that makes the rule inert. `test_retriever.py:700-712` asserts only
`demoted.rank > 1` and that the list length is unchanged, which is why this was invisible.
*Recommendation:* one of two one-liners — judge a wider window (`max(qa_top_k * 2, qa_top_k + 5)`)
so a drop lets the next passage in, or emit `kept + rest + demoted + expanded` so a demoted passage
falls below everything that was not judged. Then add the assertion the current test is missing: the
set of passage ids in the qa slice differs from the no-select baseline.

**2. `src/hippo/hipporag/graph_index.py:717-732` — the per-scale igraph memo is unbounded and keyed
by a user-supplied float.**
`graph_for_scale` caches one full `ig.Graph` per distinct `code_structural_scale` in `self._scaled`,
with no cap and no eviction, on an index that `ctx.graph_for(access)` keeps alive until the next
`graph_version` bump. `validate_settings` (`store/base.py:61-86`) bounds-checks `(float, 0.0, 3.0)`
but never quantizes, so every distinct float is a new key: the settings form's `step="0.01"`
(`web/templates/settings.html:80`) gives ~300 rebuilds from one deliberate drag, and an API or MCP
caller can pass arbitrary floats without limit. At the ceiling spike 3 measured (20k symbols, ~100k
relationships) each copy is a few MB, so this is hundreds of MB of retained igraphs. Note the plan
explicitly said a per-scale cache was *not* needed ("no `GraphIndex.with_scale` copy is needed at
all… a per-scale cache is new work if it is wanted"); WP1 added it for WP3 to hang scale search off.
*Recommendation:* round the key (`round(scale, 2)`) and keep the last two or three entries, or drop
the memo and let `build_igraph` run per call as `graph_with_edits` already does.

**3. `src/hippo/hipporag/indexer.py:625-635` — `ig.set_random_number_generator` is process-global,
and index jobs run in threads.**
`_leiden` seeds igraph's global RNG, runs Leiden and restores it in a `finally`. `jobs.py` runs each
index job in its own thread and two can run at once — that is the plan's own stated reason for
building a parser per `extract_code` call (R2-10). Two concurrent jobs interleave as
seed(A) → seed(B) → run(A) → restore(A, unseeded) → run(B): job B partitions with an unseeded RNG
and gets community integers that a re-index will not reproduce. That breaks CI gate 1's determinism
claim in production even though the gate itself (single-threaded) stays green.
*Recommendation:* a module-level `threading.Lock` around the seed/run/restore triple. It costs
nothing — Leiden was measured at 0.027 s on 10k vertices.

**4. `src/hippo/hipporag/indexer.py:195` — an O(n²) set rebuild in the OpenIE skip list.**
`skipped = [pid for pid in ids if pid not in {p for p, _ in wanted}]`: the set comprehension sits in
the condition, so it is rebuilt for every one of `n` passage ids. At `MAX_CHUNKS = 20_000` that is
4×10⁸ hash insertions — tens of seconds of pure waste inside every large index run, growing
quadratically. (`_openie_text(c)` is also called twice per chunk at `:185` and `:188`, which is
cheap but the same shape.)
*Recommendation:* hoist it — `wanted_ids = {p for p, _ in wanted}` above the comprehension.

**5. `src/hippo/hipporag/anchors.py:423-427` and `:491-499` — every stack frame and every diff hunk
scans the whole symbol list.**
`_frame_anchors` builds `in_file` by iterating `index.code_nodes` per frame, calling `_visible` and
`_same_path` (which allocates two normalised strings) on each; `_diff_anchors` does the same per
hunk. A 40-frame traceback or a 30-hunk patch against a 20k-symbol index is ~10⁶ CodeNode
comparisons with string allocation, per question, on the retrieval path.
*Recommendation:* build a `path_index: dict[str, list[str]]` (normalised path → node ids) once in
`GraphIndex.load` beside `name_index`, share it with `scoped()` the same way, and filter its hits
through `idx_of` exactly as `_name_hits` already does — the access argument is identical.

**6. `src/hippo/hipporag/paths.py:238-241` (with `:181-185`) — `code_paths_for` is a quadratic
double BFS on the query path.**
`_explain_code` calls `code_paths_for` with every kept seed (up to `MAX_CODE_SEEDS = 20`), and it
runs `shortest_code_path` over all pairs: 190 pairs. `shortest_code_path` runs `_bfs` twice
(directed, then undirected) whenever no directed route exists — which is the *common* case for two
unrelated seeds — so 380 traversals, each re-sorting `_walkable` at every visited vertex with two
`display_at` string builds per edge and no memoisation. There is no time or visit budget; `cap` only
truncates the result. This is what `timing["paths"]` measures, and it is unmeasured above the
fixture.
*Recommendation:* cap the pairing to the top ~5 seeds by weight (the block is cut at
`code_triples_chars` anyway), memoise `display_at` per index, and give `_bfs` a visit budget.

**7. `src/hippo/ingest/chunker.py:456` — `_data_ids_in` scans every data object for every passage.**
Called once per piece with the piece's line span, it iterates all `code.data_objects` and, for each,
all of its `mentions`: O(pieces × data objects × mentions) per source. Fine on the 12-object
fixture; on a SQL-heavy repository with thousands of data objects and one passage per symbol it is
the same class of cost as finding 4.
*Recommendation:* build `dict[(path, line) -> [data ids]]` once from `code.data_objects` before the
chunk loop and look the span up.

**8. `docs/FIDELITY.md:74` and `:77-78` — two byte-identical-parity bullets are now false, on
`code-graph` *and* on `wp/wp4d`.**
`:74` "Reset vector = entity weights + passage weights" — the retriever computes
`reset = phrase_weights + code_weights + passage_weights` (`retriever.py:450`). `:77-78` "when no
fact survives the filter the ranking is plain dense passage retrieval" — the fallback condition is
now `if not kept_fact_indices and not trace.used_code_seeds` (`retriever.py:380`), so a question
with a lexical anchor and no surviving facts does *not* fall back. Both sit inside the list of
things claimed identical to the reference, and PLAN §3 named only three sentences to edit (`:67-72`,
`:120-121`, `:153-155`) — these two are a fourth and fifth it missed. *Status note, not a finding:*
`:120-121` (the `max(fact count, mention, synonym score)` rule) and `:153-155` ("Single-step
retrieval only") are false on the merged tip today and `wp/wp4d` already fixes both (its lines
122-123 and 158), as it does `:67-72`.
*Recommendation:* hand these two to WP4d: `:74` gains the code seed term with its inert condition
(no code nodes ⇒ `code_weights` is all zeros, `retriever.py:532-533`), and `:77-78` gains "unless a
lexical anchor fired (adaptation 15)".

**9. `src/hippo/hipporag/indexer.py:424` — `find_synonyms` sorts the full key row per new node.**
`np.argsort(-row)` over every entity ⊕ code embedding, once per new id, to take the top 100. The
shape is pre-existing, but D7 put code ids on *both* sides: a repository contributing 20k new
symbols against a key matrix of the same order is ~10⁹ comparison-equivalents, where it used to be
entities only. *Recommendation:* `np.argpartition(-row, SYNONYM_MAX_NEIGHBOURS)` then sort the
partition. Lower priority than 1–8; flag it if a real repo index turns out slow in QA1.

### Nits

**10. `src/hippo/hipporag/graph_index.py:42` — a new `hipporag → store` package edge, for a 3-tuple.**
`from ..store.code import SPECIFICITY_KINDS`. Before this branch `hipporag/` imported nothing from
`store/` at all (rows were handed in), and `store/code.py:33` imports `..hipporag.text`, so the two
packages now import each other. No module cycle today because `hipporag/text.py` is a leaf, but the
plan's own layering paragraph (line 164) never sanctions this direction and it will bite the moment
`store/` wants anything from `graph_index`. *Recommendation:* move `SPECIFICITY_KINDS` next to
`label_of` in `hipporag/text.py`, which `store/code.py` already imports from, and re-export it from
`store/code.py` so nothing else moves.

**11. `tests/fakes/fake_store.py:647` — `delete_code_nodes_for_source` returns `set[str]`; the two
real stores return `None`.** Exactly the divergence class the parity guard cannot see (it compares
`def` names only, `test_store_code.py:473-491`). The fake needs the return value at `:209` to prune
what `DETACH DELETE` cascades for free, so the divergence is deliberate — but a future caller
writing `if store.delete_code_nodes_for_source(sid):` would behave differently per backend.
*Recommendation:* keep the set on a private `_delete_code_nodes` and have the public method return
`None` on all three; or note the divergence in the parity test so it is a decision, not an accident.

**12. `src/hippo/hipporag/retriever.py:497` — the select pass sees the prose half only.**
`self._select(trace, select_fn, asked, settings)` passes `asked` (= `question_prose or question`).
S2.12 names the embedding and the fact-filter prompt as the two consumers of the prose half and
gives the QA prompt the full text; the select pass did not exist when that sentence was written.
The result is that on the headline case — a pasted traceback — the model deciding which passages are
relevant never sees the traceback. *Recommendation:* pass the full `question`, as the QA prompt does,
or record the choice in the plan. Cheap either way; no test pins it.

**13. `src/hippo/hipporag/anchors.py:118-124` and `:179-190` — `split_question`'s line rules can
silently delete a prose line from the embedding.** `_ENDS_LIKE_CODE` treats *any* non-blank line
ending in `;` or `{` as code; `_STATEMENT` matches a line starting `class `; `_DIFF_ISH` matches a
line starting `-5`. A multi-line question containing such a line loses it from both the embedded
text and the fact-filter prompt, and the `asked = prose or question` fallback only fires when prose
is *empty*. One-line questions are safe by construction (`:165-166`), which is what the inert-condition
test pins — but nothing tests a two- or three-line prose question. *Recommendation:* a test that a
multi-line prose question round-trips to `(text, "")`, and either drop the bare `[;{]$` alternative
or require a second code signal on the same line.

**14. `tests/unit/test_ask.py:106-127` — `CODE_BLOCK_BODY` pins a whole Leiden community's membership
byte-for-byte.** The `Subsystems:` line lists twelve display names in one sorted run, so any igraph
upgrade that changes Leiden's partition, any change to the seeded RNG consumption, or any file added
to `tests/fixtures/code_sample/` rewrites it — and the failure reads as a giant string diff rather
than as "the partition moved". The fixture tree is already frozen by four other files pinning counts
off it (WP2's ledger says so explicitly), so this compounds. *Recommendation:* keep the 14 triple
lines pinned exactly (that is the S2.15 grammar and it is worth pinning) and assert the `Subsystems:`
line by shape — one line per community present, label from `community_labels` — rather than by
membership.

**15. `src/hippo/hipporag/paths.py:449` — `community_labels(index)` rescans every code node on every
block render**, inside `_subsystem_lines`, which runs per answered code question.
*Recommendation:* memoise on the index beside `communities`, or take the label from
`index.communities` and keep `community_labels` for the display-name override only.

**16. Dense-seed weight — ratify with one number added.** WP3 shipped
`dpr_score × code_seed_weight × passage_node_weight` (`retriever.py:585-602`) where PLAN is silent,
and its reasoning is sound: the alternative reading puts the top passage's dense seed at exactly 1.0
and out-weighs an exact identifier match. The thing its ledger did not say is that this mass
**stacks** on the same passage's own seed at `dpr × passage_node_weight` (`:437`), so a code passage
in the overall top `code_dense_seeds` carries roughly twice a prose passage's reset mass at
defaults, spread between itself and its symbols. `test_retriever.py:440-470` shows that is benign on
the fixture (prose order is preserved exactly, and the prose winner stays first at
`code_dense_seeds=1`). *Recommendation:* ratify as shipped, with that consequence written into the
docstring so the next reader does not rediscover it.

---

## Decision Log D1–D25, as built

| # | Verdict | Evidence / note |
|---|---|---|
| D1 | kept | Separate `Symbol`/`DataObject`/`Commit` tables; `remove_orphans` untouched (`ladybug.py:623-625`, still `:Fact`/`:Entity` only) so no code node is swept |
| D2 | kept | Structure is `CODE_EDGE`, never `Fact` rows; `fact_embeddings` holds only OpenIE facts (`graph_index.py:301`) |
| D3 | kept | One row per `(a,b,kind)` with `extra` JSON through `text()`/`decode()` (`ladybug.py:981-1021`) |
| D4 | kept | `symbol_id(source_id, path, qualname)` in `codegraph/model.py`; the store never computes an id |
| D5 | kept | `specificity` holds `in_degree + 1` over `SPECIFICITY_KINDS`; the retriever stays kind-agnostic (`retriever.py:404-405`) |
| D6 | kept | In-memory `name_index` (`graph_index.py:801-821`); no store-side symbol search added |
| D7 | **adapted, stated** | Name text only, as planned — plus `enters_synonym_search` (`indexer.py:506+`), a ≥2-split-token gate on the symbol side from spike 2, with DataObject exempt. A real, evidence-backed narrowing of D7 that PLAN does not describe; it is in WP2i's ledger and should be added to the Decision Log or adaptation 15 |
| D8, D17 | not yet | WP2b unmerged; the store side (`add_commits`/`add_modifies`/`add_precedes`) and the `_history_rows` seam (`indexer.py:481-492`) are in place and exercised by a store-built fixture |
| D9 | kept | READS/WRITES from in-repo literals; `sqlglot` added to `pyproject.toml` |
| D10 | **kept but inert** | The pass ships, is gated on `code_select` ∧ `used_code_seeds`, is injected and replayable — see fix 1 for why `drop` has no effect on the answer |
| D11 | kept | Leiden runs, label stored, `code_community_boost` defaults 0.0 (`_community_boost`, `retriever.py:613-626`); see fix 3 for the RNG |
| D12, D13, D15, D16, D23 | phase 2, correctly absent | `unresolved_calls` counts *are* carried into `CodeGraph.stats()` as D15 requires |
| D14 | kept, limitation stands | `delete_code_nodes_for_source` runs before the passage delete in both re-index paths, so a symbol's boost/TUNED dies on re-index exactly as the plan says |
| D18 | kept | Anchors seed before the fallback `return` (`retriever.py:372-380`); `MAX_CODE_SEEDS = 20` is their own budget and the `link_top_k` cut at `:412-433` never sees them |
| D19 | kept | `context_block=` kwarg prepended inside `answer_question` (`answerer.py:41-51`); `passage_ids` stays clean, pinned by `test_ask.py:143-149` |
| D20 | kept, one new edge | Package layout as specified; `hipporag → store` is new — nit 10 |
| D21, D22 (UI half) | WP4 / merged in part | Eleven `code_*` settings declared with `SETTING_RULES` + help; `SIMULATABLE_SETTINGS`/`INGEST_SETTINGS` partition asserted by a test, as WP1 flagged |
| D24 | **adapted twice, approved** | `cli.main → OrderService.place` is INVOKES 0.90 `via_import`, not 0.50 `fuzzy_name`; `place → OrderService.log` 1.00 `same_file` with no `place → Base.log` edge. Both orchestrator-approved and pinned by `expected.json`; PLAN 2.6's prose still reads the old way and should be corrected so the next reader does not "fix" the code to match it |
| D25 | kept | `tests/fixtures/code_sample/` verbatim with `expected.json` keyed by `(path, qualname)` / `(kind, qualname)`, never by id or SHA |
| S2.2 | adapted | `label_of` landed in `hipporag/text.py` and *did* replace both label lists (`store/changesets.py:75-77`, `ladybug.py:861`). PLAN says it raises on an unknown prefix; WP1 made an unrecognised prefix a silent node-not-found in the writers. Defensible (a bad id writes nothing rather than killing an index run) but it is a divergence from the plan's wording |

## The six load-bearing gotchas, verified

| # | Gotcha | Where it is true |
|---|---|---|
| 1 | Passages last, arithmetic fixed | `graph_index.py:245-254` (order), `:422-435` (`num_entities = len(entity_names)`, `first_code_vertex`, `first_passage_vertex`), `:450-452` (`passage_position`) |
| 2 | Three per-label delete statements | `store/code.py:673-693` (Neo4j, batched 500), `store/ladybug.py:1275-1285`, `fake_store.py:647-662`; called from all four delete paths (`ladybug.py:587,594`, `memory.py:110,128`) |
| 3 | `used_code_seeds` on a lexical anchor only; dense seeds admitted from the **overall** top N | `retriever.py:610` (`s.kept and s.how != DENSE`), `:588` (`dpr_order[:dense_seeds]`, the global order), `:380` (the fallback condition) |
| 4 | Every code-touching term × `code_structural_scale`; TUNED exempt | `graph_index.py:136-145` (`weight_at`), `:326-331` (cross-kind SYNONYM into the code term), `:356-362` (DEFINED_IN at 1.0), `:363-374` (REFERS_TO, MODIFIES), `:744` (`weight > 0`). Proven inert by `test_retriever.py:473-507`, which asserts every code vertex has degree 0 at scale 0 |
| 5 | `Chunk.extract_text` three-valued | `indexer.py:320-322` (`None` → `text`; a string → only if ≥ 80 chars); `chunker.py:389,398` (`""` for a short doc, doc text on part 1 only). Only the code chunker sets it |
| 6 | Dependency direction | `codegraph/model.py:21` is the package's only hippo import; `chunker.py:45-46` and `indexer.py:55-56` are `TYPE_CHECKING`; `paths.py` is in `hipporag/`. One deviation each way: `indexer.py:499-503` takes a *runtime* function-level import of `codegraph.model.name_text` (harmless — `model.py` pulls no tree-sitter — and deliberately commented), and `graph_index.py:42` adds the new `hipporag → store` edge (nit 10) |

## Tests: what is pinned, what churns, what is missing

**Pinned well.** Backend-order independence is handled at the source rather than in assertions
(`paths.py:146-157` sorts every walk, `_expand` sorts `symbols_defined_in`), which is the right
place; `doc=None` and JSON-looking text round-trip on all three stores; the `name_index` access
question has a direct test on a scoped index (`test_anchors.py:237-244`, `test_paths.py:315-331`);
`scoped()` is pinned for `omega`/`code_kinds` carry-over, recomputed code specificity and a symbol
boost (`test_access.py:393-435`); the stored-trace contract (every new field defaulted) is pinned by
S2.16. The `mixed_index` inertness test is better than the plan asked for — deleting the code nodes
under a fixed corpus isolates the graph's contribution from the corpus's.

**Will churn on harmless changes.** `expected.json` is 2,227 lines keyed by `(path, qualname)`, which
is the right key — but four separate files now pin counts off the same frozen tree
(`test_indexer.py`'s nine-key counts, `test_ingest_pipeline.py`'s `meta["code"]`, `test_codegraph.py`,
`test_ask.py`), so adding one file to `code_sample/` is a four-file change. WP2 already declined to
grow the tree for that reason and put the 2.2b gap rows in inline `Document` trees inside
`test_codegraph.py` — that is the pattern to keep; consider a second, deliberately *unfrozen* fixture
for anything that needs to grow. `CODE_BLOCK_BODY` is nit 14.

**Not pinned, and should be.** (a) That a `drop` changes the qa slice — fix 1 is invisible precisely
because no test asserts it. (b) That two concurrent index jobs produce the same communities — fix 3.
(c) That the per-scale memo does not grow without bound — fix 2. (d) That a multi-line *prose*
question survives `split_question` intact — nit 13; the current inert-condition test only covers the
one-line case, which is the case that is safe by construction.
