# V2 — Judgment review of PLAN.md: decisions, fidelity, sequencing, testability

**Reviewed:** `docs/plans/hippo-for-code/PLAN.md` as of **577 lines, mtime 15:42:11**, md5 `6512eedeff26e24582e242bd8d4c7ff2`
(pinned copy at `/tmp/PLAN-v2-snapshot.md`). The file grew 486 → 577 lines *while this review was running* — the S2.x
clarifications had just been applied. **Every `PLAN.md:LINE` below is a line of that 577-line snapshot.** Several findings
are contradictions *introduced* by that revision (the S2 text and the surrounding prose disagree); if a newer revision
already caught them, skip those rows.

Source line numbers were checked with `grep -n` / `sed -n` against the working tree.

## Summary

| Item | Verdict | blockers / fixes / nits | Headline |
|---|---|---|---|
| V2.1 User decisions | **clean** | 0 / 0 / 1 | All 9 decisions + all 6 deferrals accounted for; the one reversal (community prior → 0.0) is under Confirm #1. No silent drop. |
| V2.2 Conflict coverage | **clean** | 0 / 0 / 1 | All 25 R5 rows have a D-row; all 14 R5 questions answered. Only D24's citation is soft. |
| V2.3 Fidelity | **not sound** | 2 / 2 / 0 | The inertness sentence is false on a mixed corpus, and dense seeds turn the code path on for *every* prose question. |
| V2.4 Sequencing | **not sound** | 2 / 4 / 1 | Vertex-order rationale is exactly inverted; WP1 imports three WP2/WP3 artefacts, so it cannot land green. |
| V2.5 Testability | mostly sound | 0 / 1 / 0 | Three-store matrix, real git in `tmp_path`, no LLM outside FakeOllama — all correct. The gap is that nothing tests a *mixed* memory. |
| V2.6 Phase calls | sound | 0 / 2 / 3 | Costs are credible. S2.9 reversed an approximation the Known-limitations list still states, and its cost line cites a measurement of the design it replaced. |
| V2.7 Risk | — | — | Three assumptions with no gating test; each has a pure, pre-WP1 experiment. |
| V2.8 Scope | mostly sound | 0 / 2 / 2 | Creep is small and declared. Two things A asked for are absent and unlisted: the `docs/design/` deliverable and the `tiers_of` change. |
| **S2 conflicts** | **3 items need reversing** | 3 / 6 / 2 | S2.7's literal rule disables OpenIE on all prose; S2.15's block grammar drops the "subsystem label" A asked for; S2.17's golden file cannot match, because tmp_path commit SHAs are not reproducible. |

**Totals: 7 blockers, 17 fixes, 10 nits** — 19 fix- and 11 nit-tagged bullets, less two duplicates and one item
retired by S2-14(a); all three are marked in place.

---

## V2.1 — User decisions

Clean. Every bullet of A's "User decisions" appears verbatim at `PLAN.md:15-22` with a status, and A's "Deferred with
reasons" at `:23` maps to D12 / D13 / D23 / "Out of scope". The single reversal — the Leiden rerank prior at 0.1 → 0.0
(`:20`, D11 `:45`) — is listed under **Confirm #1** (`:516`) with a reason and a flip cost. Nothing is silently dropped.
A's "Verified on this machine" block is correctly superseded by R4 and the two corrections are stated (`:25`); I confirmed
the Neo4j one independently — `justfile:132-140` is port 17687 / `hippo-password`.

- `PLAN.md:23` — A's deferral text is quoted verbatim as *"the extractor is per-file and **cached**"*, but neither A §2.2
  nor `PLAN.md:280` specifies any cache; `extract_code(docs, source_id)` walks every file on every run. — Either add an
  mtime/content-hash cache to `extract.py`, or annotate the quoted row "(A's word 'cached' is aspirational — phase 1 is
  per-file and deterministic, not cached)". Inherited from A, not introduced here. `nit`
- `PLAN.md:56` vs `:338` — D22 still says history depth "stays `Config.git_history_depth`, an ingest knob", while S2.11
  makes it the `code_history_depth` *setting* and explicitly drops `HIPPO_GIT_HISTORY_DEPTH`. The user decision ("a
  configurable history depth, default 200") is satisfied either way, so this is a consistency `fix`, not a decision
  reversal — *duplicate, counted once under S2-11.*

## V2.2 — Conflict coverage

Clean. R5's matrix has 25 rows; the Decision Log has D1–D25, one per row, in order, each with an Evidence column. R5's 14
"Questions the synthesizer must answer" all resolve (Q1→D1/D2, Q2→D8, Q3→D9, Q4→D10, Q5→D11, Q6→D12/D13, Q7→D14/D16,
Q8→D15, Q9→D18, Q10→D19, Q11→D6, Q12→D23, Q13→D21, Q14→D25). No uncited row.

- `PLAN.md:58` — D24's Evidence is "R5 #24, A §Design summary, B §4.3". R5 #24 is the *conflict row*, not a finding; no
  R-file verifies any ω value. So the one table that governs every edge weight in the system rests on A's judgement alone.
  — Say so explicitly in the Evidence cell ("no research bears on the values; A's table adopted, WP4's eval set is what
  revises it") so nobody later reads D24 as research-backed. `nit`

## V2.3 — Fidelity

Two blockers. Both are cases where the plan's own standard — "name the addition *and* the condition under which it is
inert" (`:123`, quoting `FIDELITY.md:121-124`) — is not met by the sentence it proposes to ship.

- **`PLAN.md:120`, `:390`, `:396` — dense seeds flip `used_code_seeds` on *every* question once any code source is
  indexed.** `code_dense_seeds` defaults to 5 (`:140`) and dense seeds are "the top `code_dense_seeds` code passages by
  existing `dpr_scores` rank (**no cosine floor**)" (`:390`). `dpr_scores` is min-max normalised
  (`retriever.py:200`), so on a mixed memory five code passages always rank top-5-among-code-passages regardless of the
  question. The plan never defines `used_code_seeds`; under A §3.4's definition (`any kept > 0`, dense seeds included) it
  is therefore **True for a prose question about Boulder**. Consequences, all on the default path: the `code_select` LLM
  call fires (`:390`, +1 chat per prose question, defeating D10's "gated so prose stays cheap"); the `Title: Code graph`
  pseudo-passage enters the QA prompt (`:392`); `timing["paths"]` is written; and the DPR fallback is disabled, because
  `if not kept_fact_indices and not trace.used_code_seeds` (`:120`) now takes the PPR branch seeded by five arbitrary code
  passages instead of falling back to dense retrieval. No planned test catches this — every "prose stays green" assertion
  runs on a prose-only fixture (`:390`, `:394`), and `:396`'s "Done when" quietly concedes the point by requiring four
  settings at 0/False to get byte-identical behaviour. — Define `used_code_seeds = any *anchor* seed kept` and let dense
  seeds add reset mass without flipping the gate; **or** require a dense seed to be in the overall top-`k` by
  `dpr_scores` (not top-`k` among code passages). State the chosen definition at `:390`. `blocker`
- **`PLAN.md:125-129` — the FIDELITY inertness sentence is false on a mixed corpus.** It claims
  `code_structural_scale = 0` "drops every code-only pair out of igraph". True as written, but the pairs that matter are
  not code-only: `find_synonyms` keys become `load_entity_embeddings() ⊕ load_code_embeddings()` (`:348`), so an
  `Entity`↔`Symbol` SYNONYM edge is created (`entity_id("order service")` ↔ `OrderService`, asserted at `:357`). That
  edge's weight term is `synonym_score`, **not** ω, so it survives `code_structural_scale = 0` (`graph_index.py:69-73`,
  `build_igraph` at `:415-420` keeps any `weight > 0`), so PPR mass flows from an entity into a symbol vertex on every
  prose question that mentions the entity — prose ranking on that memory changes. Widened `TUNED` (`:81`) has the same property. This is the same class
  of leak the plan uses to reject B at `:36` and `:503`. It also invalidates WP4.5's baseline control (`:414`), which is
  meant to read "as if no code were indexed". — Replace the second sentence with something checkable, e.g.: *"With code
  indexed, `code_seed_weight = 0` and `code_dense_seeds = 0` restore fact-only seeding, `code_select = False` removes the
  second LLM pass, and `code_structural_scale = 0` drops every ω-weighted pair (CODE_EDGE, REFERS_TO, MODIFIES) out of
  igraph. Three kinds of pair remain: `DEFINED_IN` (a fixed 1.0 under S2.3, not an ω term), an `Entity`–`Symbol` SYNONYM,
  and any `TUNED` edge a user set. A prose corpus indexed alongside code is therefore *not* bit-identical to the same
  corpus indexed alone."* The stronger alternative — and the one I recommend, because it is what makes Confirm #2's
  "exact and checkable" justification true — is to scale `DEFINED_IN` and cross-kind `synonym_score` by
  `code_structural_scale` as well, so that scale 0 genuinely removes every code vertex from igraph. **See S2-3 and S2-15
  below: S2.3's fixed-1.0 `DEFINED_IN` falsifies this sentence a second, independent way and must be settled first.**
  `blocker`
- `PLAN.md:106`, `:138`, `:573` — **"an entity pair with three facts (3.0) outranks any code edge" is false above scale
  3.** `SETTING_RULES` allows `code_structural_scale` up to 10.0 (`:138`), so ω 1.0 × 10 = 10 > 3. The claim is repeated
  into FIDELITY at `:573`. — Either qualify ("at the default scale of 1.0, and up to scale 3") or cap the rule at
  `(float, 0.0, 3.0)`. A shipped fidelity sentence must not be conditionally false. `fix`
- `PLAN.md:131`, `:573` — the list of FIDELITY sentences that get **edited** names `:67-72` and `:153-155` but omits
  `docs/FIDELITY.md:120-121`, which reads *"Edge weights are recomputed at load time with the same `max(fact count, 1.0 if
  mention, synonym score)` rule"* — verbatim false once ω joins the max. — Add `:120-121` to the edit list. Separately,
  `FIDELITY.md:67-72` sits inside the bullet list describing what is *byte-identical to the reference*, so the edit must be
  phrased to keep the parity claim true for entity seeds (e.g. "…the rest are set to 0. Symbol seeds, which the reference
  has no counterpart for, are budgeted separately — adaptation 15"). `fix`

The rest of V2.3 checks out. With **no** code source indexed the graph is genuinely unchanged: ω defaults to 0.0 and
cannot raise a `max`; code vertices do not exist; `find_anchors` returns `[]`; the `link_top_k` cut at
`retriever.py:301` iterates `flatnonzero(occurs > 0)`, which anchors are not in, so `MAX_CODE_SEEDS` as a separate budget
(`:121`) is a true statement about a disjoint set. Specificity stays kind-agnostic in the retriever
(`retriever.py:286-287` divides by whatever is in the shared array), so S2.4 (`:119`) costs no branch. Adaptation 15 is
the right shape — `FIDELITY.md` is a flat numbered list ending at 14 (`14. **Synonym gate counts Unicode letters.**`).

## V2.4 — Sequencing

Order (WP1 ← WP2 ← WP2b ← WP3 ← WP4, `:173`) is right, and the WP2b-before-WP3 edge is real and correctly drawn: WP3's
`test_paths.py` asserts `history(place)` on `git_index` (`:394`), which WP2b creates (`:376`). WP1 and the pure half of
WP2 genuinely parallelise. Two blockers stop WP1 from landing green as written.

- **`PLAN.md:253`, `:507` — the vertex-order rationale is exactly inverted, and the chosen order silently corrupts
  passage lookups.** The plan puts code vertices *after* passages because "appending at the end leaves both the forward
  mapping (`num_entities + passage_index`) and the reverse (`v - num_entities`) valid at every existing call site, while
  A's insertion invalidates all of them… No research file enumerates those sites, so this is the order that needs no
  unverified grep." I ran that grep. `num_entities` is not stored — it is a derived property:
  ```python
  # src/hippo/hipporag/graph_index.py:234-249
  @property
  def num_entities(self) -> int:
      return len(self.node_ids) - len(self.passages)
  ...
  def passage_position(self, vertex: int) -> int:
      """Vertex index -> position in `self.passages` (passages come after all entities)."""
      return vertex - self.num_entities
  ```
  Under the plan's order it returns `entities + code`, so `passage_position(first_passage_vertex)` is `-num_code` — a
  negative index that returns a passage from the *end* of the list instead of raising. `name_of` (`:245`) and
  `passage_by_id` (`:255`) then serve the wrong passage, and so does every Ask answer. Under **A's** order (code before
  passages) `passage_position` stays correct by construction, because passages remain last. Also `passage_position()` is
  not "A's new helper threaded through each call site" — it already exists at `graph_index.py:247`. And
  `first_code_vertex = num_entities + num_passages` (`:253`) is broken by the same property. The nine sites are:
  `graph_index.py:235, 245, 247-249, 255` and `graph.py:144, 148, 181, 214, 337` (`graph.py:214` reports
  `index.num_entities` as the Graph page's entity count, wrong under either order).
  — Do not reorder; **fix the arithmetic**, which is three lines and makes the order a free choice: store
  `num_entities` (or define it as `len(entity_names)`), add `first_passage_vertex`, and rewrite
  `passage_position(v) = v - first_passage_vertex`. Then delete the rationale at `:253` and the "no existing
  `num_entities` offset arithmetic changes" row at `:507`, which are the load-bearing false claims. WP1.5's own
  assertion "a passage vertex is still `num_entities + i`" (`:262`) is the test that catches this — keep it, but note it
  fails until the property is fixed. `blocker`
- **`PLAN.md:183`, `:263`, `:264`, `:265` — WP1 depends on three artefacts that WP2/WP3 create, so it cannot be a green
  PR.** (a) S2.2 puts `label_of(id)` in `codegraph/model.py` (`:183`) and makes it the label resolver every WP1 store
  writer calls — but `src/hippo/codegraph/` is created in **WP2** (`:276`); WP1's `store/code.py` would import a package
  that does not exist. (b) The S2.17 golden-file test is listed in WP1's `test_store_code.py` (`:264`) but indexes
  `tests/fixtures/code_sample/`, created in WP2 (`:276`), via `extract_code`, also WP2. (c) S2.5's access case at `:263`
  asserts `find_anchors` returns nothing for a hidden symbol — `anchors.py` is created in **WP3** (`:384`).
  — Move `label_of` to `hipporag/text.py`, which WP1 already modifies and already holds `make_id`/`split_identifier`
  (`:183`); move S2.17 to WP2's `test_indexer.py` and add `expected.json` to WP2's files-to-create; split `:263` so WP1
  asserts `get_symbols` + `shortest_code_path` and WP3 adds the `find_anchors` leg. `blocker`
- `PLAN.md:253`, `:412` — **`code_structural_scale` is silently lost whenever a simulation also edits an edge.**
  `simulate()` passes `graph=index.graph_with_edits(...)` when `overrides.edge_edits` is set (`analysis/simulate.py:110`),
  and `retrieve(..., graph=)` uses that igraph instead of the index's own (`retriever.py:170`, `:350`
  `index.ppr(reset, damping, graph=graph)`). `graph_with_edits` builds from `Edge.weight`, which the plan freezes at
  scale 1.0 (`:253`). So on the Analyze page, moving the scale slider *and* editing an edge applies only the edit. —
  Give `graph_with_edits(edits, scale=1.0)` the scale and have `simulate.py:110` pass
  `settings["code_structural_scale"]`; `build_igraph(..., scale)` then composes and `GraphIndex.with_scale` as a
  GraphIndex copy is not needed at all. `fix`
- `PLAN.md:253` — "cached per scale value **beside the `graph_with_edits` cache**". There is no such cache:
  `graph_with_edits` (`graph_index.py:401-412`) rebuilds the igraph on every call and returns an `ig.Graph`, not a
  `GraphIndex`. The only cache nearby is `AppContext._scoped` (`context.py:106-127`, 16 entries, keyed by
  `(version, visible)`). — Strike the phrase, or say "a new per-scale cache, since `graph_with_edits` has none". `fix`
- `PLAN.md:235`, `:239` vs `:183` — **S2.2 says A's query-based `_labels_of(ids)` "is dropped"** in favour of the pure
  `label_of(id)`, and that `label_of` "**replaces** `_node_label` … and the `:Entity|Passage` disjunction in
  `store/changesets.py:71`". But `:235` still instructs the implementer to write "a new `_labels_of(ids)` replacing
  `_node_label`", and `:239` still says "Two hard-coded label lists in two dialects must both grow". — Delete the
  `_labels_of` sentence at `:235` and rewrite `:239` as "both call sites switch to `label_of`". `fix`
- `PLAN.md:237` vs `:350` — `test_store.py:107` (`assert set(store.stats()) == keys`, verified: 11 keys today) is claimed
  by WP1 at `:237` ("update in this WP") and by WP2's S2.18 at `:350` ("they are updated here"). `stats()` gains its four
  keys in WP1, so WP1's PR is red unless WP1 owns it. — WP1 owns `test_store.py:107`; WP2 owns only the six
  `test_indexer.py` count assertions and the two `test_ingest_pipeline.py` titles. `fix`
- `PLAN.md:384` vs `:412` — the `settings.html` `SETTING_RULES` wiring and the `SETTING_HELP` lines are listed as WP3
  files-to-modify *and* as WP4.4 work. — One owner; WP3, since that is where the settings are registered. `nit`

Otherwise each WP is independently landable: WP2's chunker/indexer changes update the six pinned count assertions and two
pinned titles in the same PR (`:350`, verified at `test_indexer.py:55,98,212-217,218-223,238,317` — the plan's "six, not
two" correction is right); WP3's new `Trace` fields are all defaulted so `trace_from_dict` keeps loading old rows
(`retriever.py:429-445`); WP4 is additive.

## V2.5 — Testability

Conventions are right. The `store` fixture parametrises the backend from `HIPPO_TEST_STORE` (`tests/conftest.py:32-37`)
and the plan correctly warns that a bare `pytest` is LadybugDB, not the fake (`:173`, `:484`). `test_codegraph.py` is
pure (`:355`). `test_git_history.py` and `make_code_checkout` build a **real** git repo in `tmp_path` with `git init` +
three commits (`:374`, `:480`), modelled on `make_checkout` (`test_ingest_repos.py:144-160`) — which is indeed the only
real-git pattern in the suite. No test needs a live LLM: everything routes through `FakeOllama`, and the one new model
interaction (the select pass) is explicitly given a new dispatch rule (`:390`).

- **No test anywhere indexes prose and code into the same memory.** Every "prose stays green" claim (`:390`, `:392`,
  `:394`) runs on a prose-only fixture, and every code claim runs on `code_index`/`git_index` (`:481-482`). That is
  exactly why the two V2.3 blockers are invisible to the plan's own test list. — Add a `mixed_index` fixture (the
  `acme_robotics.md` sample **plus** the code fixture, one memory) and assert, at defaults: a prose question yields
  `trace.used_code_seeds is False`, adds **zero** chat calls versus the prose-only index, `answer.context_block == ""`,
  and the same top-3 passage ids as `indexed`. Put it in WP3's `test_retriever.py`; it is the single test that would have
  caught both blockers. `fix`
- `PLAN.md:390` — "`tests/unit/test_fakes.py` is where an exhaustive-dispatch assertion would live and must be updated
  with it": no such assertion exists today (`tests/unit/test_fakes.py` has no dispatch test). More useful is the failure
  mode: `FakeOllama.chat` falls through to `json.dumps({"reply": "I am a fake model."})`
  (`tests/fakes/fake_ollama.py:238`), so a missing select rule produces a reply with no `decisions` key and no error. —
  Change to "*add* an exhaustive-dispatch assertion", and require the select parser to treat a missing/!list `decisions`
  as keep-all, with a test. *Retired if S2.14's injected `select_fn` lands (S2-14a); not counted.* `nit`

## V2.6 — Phase calls

Cost lines are credible and each names what phase 2 pays. D12 (CCG: `Passage.ccg_json` on three stores), D13
(`Passage.path`+`kind`, `delete_passages_for_paths`), D15 (2 node tables), D16 (`eval_set_id` on `Changeset`, a new
exception type) all correctly identify a schema change as the cost. D14's phase-1 gap is stated honestly at `:526`, and
its premise checks out (`remove_orphans` matches `:Fact`/`:Entity` only, so code nodes are never swept). D23 is right
that an LSP adapter needs no schema change.

- `PLAN.md:372` vs `:528` — **S2.9 reverses the HEAD-range approximation** ("MODIFIES intersects each hunk with the
  symbol ranges AT THAT COMMIT, not at HEAD"), but Known limitations still reads *"History is approximate. Symbol ranges
  are taken at HEAD, not at each commit's parent (WP2b)"* — `:528` is the only place the stale claim survives, and S2.9
  itself asks for it to be replaced. Additionally S2.9's cost line cites **R4 T11**, which timed the *old* design (one
  `git log --first-parent -n 200
  --numstat` at 0.042 s). The new design is `depth × touched-files` invocations of `git show <sha>:<path>` plus a
  tree-sitter parse each — for 200 commits × ~5 files that is ~1 000 subprocesses, unmeasured, and the only budget is
  **per-commit** (`code_git_timeout_s` = 10 s), so the worst case is 200 × 10 s = 33 minutes inside a single index job. —
  Delete the stale limitation at `:528` (replace with the rename-detection-off limitation S2.9 actually creates); mark
  S2.9's cost as *unmeasured*; add a **whole-pass** budget (e.g. `code_history_total_s`, or stop after N skipped
  commits) beside the per-commit one. `fix`
- `PLAN.md:56`, `:148`, `:368`, `:412`, `:577` — **the `code_history_depth` change is only half-applied.** S2.11 (`:338`)
  makes history depth a *setting* and drops `HIPPO_GIT_HISTORY_DEPTH` / `Config.git_history_depth`, but: D22 (`:56`)
  still says it "stays `Config.git_history_depth`, an ingest knob"; WP2b still lists `src/hippo/config.py` as a file to
  modify (`:368`); WP4.4 says "`SETTING_HELP` lines for all **eight** keys" (`:412`) when the table now has **ten**
  (`:137-146`); and README (`:577`) still promises "`HIPPO_GIT_HISTORY_DEPTH`" and "the eight `code_*` settings and the
  one env var". — One sweep: D22, `:368`, `:412`, `:577`, and the CONTRACTS entry at `:548`
  (`read_history(checkout, symbols, *, depth)` is missing the `timeout_s` parameter `:370` adds). `fix`
- `PLAN.md:47` — D13's phase-2 hook is costed but a cheaper partial one already exists and is not mentioned:
  `Chunk.defines` → `DEFINED_IN` → `Symbol.path` gives passage→path for every *parsed* file with no new column. Adding
  `Passage.path` in WP1 would remove the phase-2 migration entirely, but that means `ALTER TABLE` on a **populated node
  table**, which R4 tested only for rel tables (T6). — Either fold a node-table `ALTER` into test 1.5a and add the column
  now, or note the partial hook and leave D13 as costed. `nit`
- `PLAN.md:49` — D15: phase 1 *discards* every unresolved call, so phase 2's leaderboard starts from zero data and users
  cannot see how big the gap is. Counting them per file in `CodeGraph.stats()` → `meta["code"]` is a few lines now and
  gives phase 2 a baseline plus an immediately useful number. `nit`
- `PLAN.md:57` — D23 says "no schema change", which is true, but an LSP upgrade rewrites ω and `provenance` on existing
  edges, so it takes effect only after a full re-index. Worth one clause so nobody expects it to be hot-swappable. `nit`

## V2.7 — Risk: three riskiest assumptions, cheapest experiment each

Test 1.5a (`:258`) already gates the one big LadybugDB unknown (`ALTER TABLE` on a *populated, propertied* SYNONYM/TUNED
across a reopen) and is correctly ordered first — that risk is handled. The three below have no gating test, and each
experiment is pure Python, no LLM, runnable before WP1 starts.

1. **Anchors fire on ordinary prose.** `:386` admits bare words on "≥ 3 chars, absence from a stoplist, and an exact
   `name` hit". hippo's own symbol names include `status`, `index`, `config`, `source`, `run`, `ask`, `stats` — all
   ordinary English. A false anchor on a mixed memory diverts PPR mass and (with B2 unfixed) triggers the whole code
   path. *Experiment:* extract the symbol-name set from `src/hippo` with a 30-line tree-sitter or `ast` walk, run the
   plan's tokenizer + stoplist rule over the questions in the existing eval question sets, and count how many prose
   questions produce ≥ 1 anchor. If it is not near zero, the stoplist is not the mechanism — require two tokens, or a
   qualified/backticked form, for a bare-word anchor. ~1 hour.
2. **Symbol `name_text` ↔ entity synonyms are noise under a real embedder.** D7 (`:41`) rests entirely on
   `"order service OrderService"` reaching the entity `order service`, and `:357` pins that at 0.87 — but that number is
   `FakeOllama`'s feature hashing, not the real model. At the 0.8 default, generic names (`run`, `save`, `main`, `total`)
   could link to unrelated prose entities, and every such edge survives `code_structural_scale = 0` (V2.3 blocker 2).
   *Experiment:* embed `name_text()` of ~200 hippo symbol names with the real embedding model against the entity set of
   an already-indexed prose source, and count pairs ≥ 0.8 and how many are nonsense. If the rate is high, raise the
   threshold for cross-kind pairs or require ≥ 2 split tokens. ~1 hour, one model, no indexing.
3. **Index and reload cost at real-repo scale.** One passage per symbol *plus* one name vector per symbol multiplies the
   stored-vector count that `FIDELITY.md:124-127` already flags as the driver of full-reload cost (R3 gotcha 11), and
   `ctx.invalidate_graph()` runs on every changeset apply (`analysis/changesets.py:148`). R4 T8's 537 s for 200k
   relationships is the only datapoint and the plan treats it as a ceiling (`:527`) without checking where a real target
   repo lands. *Experiment:* count functions/methods/classes in the repo the user actually wants indexed (`ast` walk,
   minutes), multiply by 2 vectors + ~4 edges per symbol, and place it on the T5 (13.6 s) → T8 (537 s) curve. If it lands
   past T5, WP1's write path needs the batching decision revisited **before** it is written three times. ~30 minutes.

## V2.8 — Scope

**Creep is small and all of it is declared.** `code_structural_scale` + `GraphIndex.with_scale` are new versus both A and
B, and carry Confirm #2 (`:517`). The three bundled pre-existing bug fixes — `settings.html`'s hard-coded `max="1"`
(which also unbreaks `passage_node_weight`, `:148`), `README.md:228`'s stale "four MCP tools" (`:577`), and the
`node_details` else-branch (`:412`) — are each justified in place; the 3-line store parity guard (`:266`) is new and
cheap. No objection to any of it; naming them collectively as "pre-existing fixes carried along" in the *vs A* table
would make the diff honest.

Two things A asked for are **absent and unlisted**, which is the part that needs a decision:

- `PLAN.md:539-577` — **A §4.6's `docs/design/` deliverable is dropped with no trace.** A asks to keep the user's two
  design documents verbatim as `docs/design/code-hipporag-design.md` and `docs/design/code-only-design.md`, plus a
  `docs/design/README.md` mapping each principle of the code-only design to where it lives in hippo and what phase 1
  defers. "Docs to update" covers only CONTRACTS / FIDELITY / MCP / README, and "Out of scope" (`:535`) does not mention
  it. That map is also the natural home for the D12/D15/D23 deferral rationale. — Either add it to WP4's docs list or
  add one line to "Out of scope" saying it was dropped and why. Silence is the only wrong answer. `fix`
- `PLAN.md:412` — **A §4.4's `tiers_of` change is dropped.** A explicitly flags that "`tiers_of` gives code nodes their
  source's tier directly (today it assumes every non-passage node is an entity reached by a mention edge)". Confirmed:
  `web/routes/graph.py:63-88` builds `node_tier` from passages and then only from `e.mention` edges, so a symbol — which
  has no `MENTIONS` under D1 — gets no entry, and `graph.py:175-176` renders
  `node_tier.get(node_id, EVERYONE_TIER)["name"]`. A symbol belonging to a restricted-tier source is therefore
  **labelled "Everyone"** on the Graph page. Not an access leak (the index is already scoped by `ctx.graph_for`), but a
  visibly wrong badge on exactly the page WP4 adds symbol filtering to. — Add to WP4.4: `tiers_of` sets a code node's
  tier from `source_tier[node.source_id]` directly, with a test asserting a hidden-tier symbol shows its real tier.
  `fix`
- `PLAN.md:392` — A §3.5's `prompts.CODE_GRAPH_HEADER` — the one sentence explaining the notation ("INVOKES = calls,
  READS/WRITES = uses/changes a table, confidence 0–1 in brackets") — is not carried over. The plan renders `[PATH]` /
  `[TESTS]` / `[COMMIT …]` lines into the prompt with no legend, so the model sees `-[INVOKES 0.90]->` uninterpreted. —
  Restore the header line; it is one constant and it is the difference between the block being evidence and being noise.
  `nit`
- `PLAN.md:412` — A §4.4's Graph-page **`community` colour mode** is named explicitly in A; the plan mentions only
  "`g-kind`/`g-color` options" generically. Since D11 keeps Leiden precisely so the label is available (`:45`), and the
  prior ships at 0.0, the colour mode is the label's only visible use outside `blast_radius`. — Name it, or the WP4 eval
  set has nothing to judge Confirm #1 against. `nit`

Nothing else in the plan is unasked-for, and nothing else that both A and B asked for is missing — R5's "Shared and
agreed" list (tree-sitter Python + TS/JS, deterministic structure, no OpenIE over bodies, symbol-level passages,
statement splitting, anchors from identifiers/stack traces/snippets/diffs, provenance-weighted directed paths, no
free-form user graph query, git history, commit passages, code-localization evals, path/blast/exception/history, scoped
access, PPR as the spine, no external PRD/ticket/DDL) is fully covered.

---

## S2 conflicts

Checked every item of `tasks/S2-staff-decisions.md` against the Decision Log, A's user decisions, R3.10's fidelity
constraints and R2.8's test conventions. **S2.1–S2.11 and S2.17–S2.18 were already applied in my snapshot; S2.12–S2.16
were not, and are assessed as if present.** Items not listed below are consistent and need no action (S2.1, S2.6, S2.8,
S2.10, S2.16).

- **S2-7 (blocker). `None` is overloaded, and both readings break an A user decision.** `extract_text` has two producers
  and one consumer, and S2.7 gives them incompatible rules. (a) S2.7's *indexer* rule — "skips `openie.extract` when
  `extract_text is None`" — read literally turns OpenIE off for **every prose source**, since `None` is the default
  (`PLAN.md:346`) and is what every existing prose chunk carries; indexing `acme_robotics.md` would yield zero entities
  and facts, and `test_indexer.py:55` (`entities: 31, facts: 34`) would go to zero. (b) Take the only other reading
  (`None` = "extract `text` as today", which is what `:348` and A both intend) and S2.7's *chunker* rule bites instead:
  "function passage → its docstring/doc-comment iff ≥ 80 chars **else `None`**" (`:346`) means a function with a 30-char
  docstring gets `None` → **OpenIE runs over its body**, violating A's "Never function bodies or DDL" (`:21`). `:348` is
  itself self-contradictory, asserting the skip rule and the prose default in one sentence. — Fix both sides, which is
  A's original design: the **chunker** emits a *string* for every code passage (the doc, or `""` when there is none or it
  is short) and `None` only for prose; the **indexer** treats `None` as "extract `text`, unchanged" and a string as
  "extract iff ≥ `MIN_OPENIE_DOC_CHARS`, else save an empty `Extraction`". Repair `:346` (drop "else `None`" → "else
  `\"\"`"), rewrite `:348` to state exactly those two branches, and amend S2.7's own sentence so the mechanical re-check
  does not restore it. Contradicts: A's OpenIE user decision (`:21`), R2-6.
- **S2-15 (blocker). S2.15's context-block grammar silently drops A's "shown as the subsystem label".** A's community
  user decision (`PLAN.md:20`) is kept on three legs: the Leiden pass, the stored label, and the label being *shown*.
  S2.15 specifies the block as triple lines + a `Tests:` line + `Commits:` lines, with no community line, and requires
  `test_ask.py` to assert the exact string — which supersedes `:392`'s `[PATH]`/`[COMMUNITY]`/`[EXPANDED]`/`[TESTS]`/
  `[COMMIT` markers. That removes the answer-block surface; the only other surface D11 names is "what makes
  `blast_radius` readable" (`:45`), and `paths.blast_radius`'s own spec at `:388` does not mention grouping by community
  either. With `code_community_boost` also shipping at 0.0 (Confirm #1), the label ends up with **no specified surface**,
  and Confirm #1's "the WP4 eval set is what should decide" becomes undecidable. — Adopt S2.15's grammar (it is the one
  with a golden assertion) **plus** a `Subsystem: <community_name> (N files)` line, update `:392` to match, and name
  community grouping in `blast_radius` at `:388`. Also fold in A §3.5's one-sentence notation legend (V2.8 nit) so the ω
  values are interpretable. Contradicts: A user decision (`:20`), D11.
- **S2-17 (blocker). The golden file cannot match, because the fixture's commit SHAs are not reproducible.** S2.17
  requires `expected.json` to carry "the commit→symbol MODIFIES set for the tmp_path-built history", and
  `commit_id = make_id("commit-", f"{source_id}:{sha}")` (`:85`). A git SHA is a hash of tree, parents, message **and
  the author/committer name, email and timestamps**; `make_code_checkout` (`:480`) sets `git config user.*` but nothing
  about dates, so every run produces different SHAs — and `source_id` differs per run too. A checked-in file keyed on
  those ids can never match. — Either pin `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` (plus author name/email) in
  `make_code_checkout` so SHAs are byte-reproducible, **or** key `expected.json`'s MODIFIES rows by
  `(commit ordinal, symbol qualname)` and assert ids only for structural equality within the run. State which.
  Contradicts: R2.8 / R2 gotcha 8 (real-git fixtures are built at test time), CI gate 1 (`:494`).
- **S2-3 (fix). `DEFINED_IN` at a fixed 1.0 falsifies the FIDELITY inertness sentence.** S2.3's table (`PLAN.md:112`)
  gives `DEFINED_IN` the weight term **1.0 ("counts as a mention")** rather than `ω × code_structural_scale`. So at
  `code_structural_scale = 0` every symbol stays wired to its defining passage at weight 1.0, which changes each code
  passage's weighted degree and therefore its PPR normalisation — the "Done when" at `:396` ("the prose suite is
  byte-identical with `code_seed_weight=0 code_dense_seeds=0 code_select=False code_structural_scale=0`") is achievable
  only on a memory that has no code in it at all, i.e. trivially. — Scale `DEFINED_IN` by `code_structural_scale` too
  (see the V2.3 blocker for the combined wording), or restate `:396` as "on a prose-only memory". Contradicts: R3.10's
  requirement that the inert condition be checkable, D22/Confirm #2.
- **S2-14 (fix, three parts).** Injecting `select_fn` the way `fact_filter` is injected is the right call and matches
  R3.1, but three things in the plan and in S2 itself must move with it. (a) `PLAN.md:390` still requires a **FakeOllama
  dispatch rule** keyed on the select system prompt; with an injected callable, tests inject a fake and that rule (and
  the `test_fakes.py` note) becomes dead work — delete it, which also retires the V2.5 nit. (b) `simulate()` calls
  `retriever.retrieve(...)` directly (`analysis/simulate.py:112-119`) and passes `fact_filter` only when replaying; if
  it does not also pass a `select_fn`, the select pass never runs in a simulation, which defeats D10's entire reason for
  putting it in `retriever.py` ("so the decisions land in the trace and simulations can replay them"). Specify
  `replay_select(baseline)` alongside `replay_filter`, and have `simulate.py:110-119` pass it. (c) S2.14's rule that
  expanded passages are appended with score 0.0 and "never counted toward `top_k` for the answer's citation list unless
  the answer cites them" is circular — `ask.answer_from_trace` builds the prompt from `trace.passages[:qa_top_k]`
  (`ask.py:40-53`), so the citation list *is* what was sent. — Exclude expanded passages from the `qa_top_k` slice
  entirely; they appear only as `[EXPANDED]`/summary lines in the context block, which is what `:392` already renders.
- **S2-13 (fix). The fan-out cap and the per-token cap do not compose.** S2.13 drops an identifier when
  `n_matches > 10`; `find_anchors` already caps at `MAX_MATCHES_PER_TOKEN = 8` (`PLAN.md:386`, from A §3.2). Under the
  8-cap, `n_matches > 10` is unreachable, so the ambiguity rule never fires and the retriever instead seeds 8 silently
  truncated, arbitrarily chosen symbols — strictly worse than dropping. — Make `n_matches` the **pre-cap** count, and
  order the rules: count all matches → drop as `ambiguous` if > 10 → otherwise seed up to `MAX_MATCHES_PER_TOKEN` at
  `code_seed_weight / n_matches`. Test both branches, as S2.13 asks.
- **S2-12 (fix). Question splitting is a new fidelity adaptation and is not listed as one.** Sending only `prose` to the
  question **embedding** and to the **fact-filter prompt** changes `dpr_scores` and the filter's input for any question
  containing a fenced block, a stack frame or a diff — including on a prose-only memory, where nothing else in this plan
  is supposed to change. `retriever.py:198` embeds the question verbatim today, R3.9 confirms `FIDELITY.md` has no
  sentence permitting any pre-retrieval step, and adaptation
  15's contents list (`PLAN.md:573`) does not mention splitting. — Add "the question is split, and only its prose half is
  embedded and filtered" to adaptation 15, and add a test that a pure-prose question splits to `(text, "")` and takes the
  unchanged path. Contradicts: R3.10 (an addition must name its inert condition).
- **S2-11 (fix). Two ingest-only budgets become simulate knobs.** `code_history_depth` and `code_git_timeout_s` are now
  graph settings (`:145-146`), and `simulate.py:48` builds the Analyze page's knob list from `SETTING_RULES` — so both
  will render as sliders that cannot affect any retrieval, on a page whose purpose is showing why a search ranked what it
  did. — Exclude them explicitly from the simulate knob list (or split `SETTING_RULES` into retrieval and ingest groups)
  and say which. Also finish the rename sweep listed under V2.6 (D22 `:56`, `:368`, `:412`, `:548`, `:577`).
- **S2-18 (fix). S2.18 assigns `test_store.py:107` to WP2; it must be WP1.** `stats()` gains `symbols`,
  `data_objects`, `code_edges`, `commits` in WP1 (`:237`), and `test_store.py:107` asserts the key set by equality
  (verified: 11 keys today), so WP1's PR is red the moment the store methods land. S2.18's other assignments are right,
  including `test_analysis_explain.py:114` → WP3 (WP1 adds `Edge.code_kinds`, but with no code indexed no new kind
  appears, so WP1 stays green). *Duplicate, counted once under V2.4 (`:237` vs `:350`).* — WP1 owns `test_store.py:107`; WP2 owns
  the six `test_indexer.py` count assertions and the two `test_ingest_pipeline.py` titles.
- **S2-17b (fix). No regeneration path is specified.** S2.17 requires stating how `expected.json` is regenerated and that
  regeneration diffs are reviewed; `PLAN.md:264` says neither. A `--update-expected` flag needs a `pytest_addoption` hook
  in `tests/conftest.py` (none exists today). — Add either that hook or a `scripts/update_expected.py`, and one sentence
  that a regeneration diff is reviewed like a source change. See also the V2.4 blocker: this test must live in WP2, not
  WP1, because the fixture and `extract_code` do not exist until then.
- **S2-2 (nit). Put `label_of` in `hipporag/text.py`, which S2.2 already allows.** S2.2 offers
  "`codegraph/model.py` (or `hipporag/text.py`)" and the plan chose the former (`:183`), which is what makes WP1 depend
  on a WP2 package (V2.4 blocker). `hipporag/text.py` is already a WP1 file and already holds `make_id`, whose prefixes
  `label_of` decodes. — Choose `hipporag/text.py`; the conflict disappears with no loss.
- **S2-4 (nit). Say that the shared array holds the denominator, not the reciprocal.** S2.4 writes the rule as
  "entity: `1 / passages that mention`; symbol and data: `1 / (in_degree + 1)`", but `retriever.py:286-287` *divides* by
  the array (`w /= index.entity_passage_count[v]`), so the array must hold `passages`, `in_degree + 1`, `1` and `0`.
  Storing the reciprocals as written would invert the damping and quietly boost hub symbols instead of damping them. —
  State the stored values explicitly in `:119`.

**S2 items I checked and found clean:** S2.1 (the seven-consumer checklist matches R6 C2/gotcha 3; `node_details` fix is
correctly required to fail loudly), S2.6 (qualname grammar is self-consistent and its `__init__`-kept reversal of A is a
stated improvement, since `symbol_id` hashes `path` anyway per D4), S2.8 (every row is a positive assertion including
the eight "no edge" rows — this is the right shape for a resolver spec), S2.10 (seeding igraph's RNG + relabelling by
smallest member qualname + excluding `community` from the multiset comparison is exactly sufficient for CI gate 1),
S2.16 (matches R3 gotcha 8; `trace_from_dict` uses `Cls(**row)` at `retriever.py:429-445`, so defaults plus
never-remove is the whole requirement).
