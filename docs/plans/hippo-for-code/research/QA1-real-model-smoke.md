# QA1 — real-model end-to-end smoke of the code graph

Run 2026-09-07 on `code-graph` tip `d7187c4`, read-only against the running codebase (worktree
`.worktrees/qa1`, branch `wp/qa1`). Real Ollama on the host: `qwen3.8:latest` (the chat model this
machine actually has pulled — 27B, per `.env`'s override of the `qwen3:8b` default) and
`nomic-embed-text` (embeddings). Every number below is measured, not estimated, unless marked
"projected".

**Scope change from the brief, agreed with the orchestrator mid-run:** the brief's zip (`src/`,
`tests/`, `docs/`, `README.md`, `pyproject.toml`) dry-runs to 204 documents / 3,789 chunks / 1,514
passages needing a real OpenIE call — at the measured ~16-21s/passage (NER + triples, serialized at
`HIPPO_OPENIE_WORKERS=1` as the brief specifies), that is **~6.7h for one index pass and ~13.4h for
the two passes CI gate 1 needs**, on a host already running six other fleet workers' test suites.
The orchestrator trimmed scope to a **subset zip** — `src/hippo/hipporag/`, `src/hippo/codegraph/`,
`README.md` (330 symbols, 199 OpenIE-needing passages) — and asked that the full-repo projection be
kept as its own finding (see Surprises). Two questions were retargeted to stay inside the subset:
(a)'s traceback now ends in `hipporag/retriever.py`, not `store/ladybug.py`; (c) asks about
`find_anchors` (defined and called within the subset) rather than `delete_code_nodes_for_source`
(lives in `store/`, outside it).

## Verdict

| Check | Result | Number |
|---|---|---|
| CI gate 1 (deterministic re-index) | **PASS** | nodes/data/edges/DEFINED_IN/REFERS_TO all equal across two independent index passes; `meta["code"]` byte-identical |
| CI gate 2 (no function body / CREATE TABLE reaches OpenIE) | **PASS** | 0/199 expected OpenIE texts leak a body or a real `CREATE TABLE` statement, checked two ways (see Step 2) |
| Inertness (the four settings zero out every code-touching term) | **PASS** | code-kind `top_nodes`: baseline 24 (b) / 12 (d) → 0 / 0 after the four settings; `used_code_seeds`, `context_block`, `timing_ms["paths"]` all switch off |
| Anchors on prose (`used_code_seeds` stays False for (d), (e)) | **PASS** | (d) prose README question and (e) bare-word "load" question both show `used_code_seeds=False`, `context_block=""` |
| Synonym quality (cross-kind, ≥2-token guard) | **PASS, better than predicted** | 0/30 nonsense in the top 30 distinct Entity↔Symbol pairs (spike 2 predicted ≤27%); 0 one-token symbols have an embedding, 0 multi-token symbols are missing one |
| Timings | **PASS** | `extract_code` over full `src/hippo`: 0.27s (budget < 5s); `GraphIndex.load`: 0.18s for 944 passages |

**One defect found** (Step 4 / Defects below): a "where is X called" question can get a context
block that never shows the calling edge, for any symbol whose outgoing-edge count crowds the
`code_triples_chars` budget before its incoming edges are reached. The one HTTP-layer gap found
(`/api/ask`'s JSON omits `Answer.context_block`) is WP4a's explicitly planned, in-flight work, not
a regression — see Surprises, not filed as a Defect.

## Methodology

Real Ollama calls are slow and the store is single-writer (LadybugDB, one process at a time), so
this run went through **the Python API directly** (`hippo.ask`, `hippo.ingest.pipeline`,
`hippo.context.AppContext`) rather than a long-lived `hippo serve` process for the bulk of the
work — the QA1 brief explicitly allows this ("you work through the Python API and the existing web
UI/`hippo ask` only"). This also gets `Answer.context_block` verbatim, which `/api/ask`'s JSON
response does not expose (see Surprises). Step 1's scratch server was still run for real, at the
very end, once every script had closed the store, to verify the HTTP layer independently.

`HIPPO_DATA_DIR=/tmp/hippo-qa1/data`, `HIPPO_STORE=ladybug`, `HIPPO_OPENIE_WORKERS=1`,
`HIPPO_LLM_MODEL=qwen3.8:latest`, `OLLAMA_URL=http://localhost:11434` (default) throughout.

OpenIE calls were observed by a runtime monkeypatch of `Ollama.chat_json` and `openie.extract`
(classifying calls by `schema is prompts.NER_SCHEMA` / `TRIPLES_SCHEMA` identity, logging the real
passage text and its passage id) — **no source or test file in the repo was edited**; the patch
lives in a scratch script (`lib_instrument.py`, quoted below) applied before `AppContext` is built,
the same seam `tests/fakes/fake_ollama.py` stands in at, but for observing the real model instead
of replacing it.

**Two bugs in the QA harness itself, caught and fixed before they cost real time or produced a
false result** (both documented in full in the Evidence section, since they change how the CI
gate 2 evidence should be read):

1. The first version of the instrumentation grabbed the *first* `role: "user"` message in
   `ner_messages`/`triples_messages`. `prompts.py` puts a fixed one-shot example there
   ("Radio City is India's first…") and the real passage in the *last* user message — so every
   logged call looked identical. Caught with a synthetic function-body probe after the (first
   attempt at the) main run had gone 15/199 passages; the run was killed, the data dir wiped, and
   restarted clean with `messages[-1]` instead of the first match — the numbers in this report are
   all from that second, correctly-instrumented run.
2. A separate rehearsal script (run concurrently, against a tiny fixture — `tests/fixtures/code_sample/pyapp`,
   zipped, indexed twice into its own throwaway data dir — to shake out bugs in the analysis
   scripts before spending the real run's time on them) hardcoded the *same* log path as the main
   run. Its own `install()` truncates the log at start, so it wiped ~65 of the main run's early
   log lines, and its own lines got interleaved with the remainder. The main run's *counts*
   (`lib_instrument.summary()`, in-process, unaffected) are exact; only the per-call *content* log
   has a gap. **CI gate 2 in this report does not rely on that log**: it recomputes the full,
   authoritative set of 199 expected OpenIE texts the same way `_read_chunk_index` builds them
   (`readers.read_zip` → `extract_code` → `chunk_documents` → `_openie_text`, deterministic, no
   Ollama needed) and checks the real property directly against that; the surviving log is used
   only as a secondary, weaker cross-check. Checked precisely: 731 of ~796 lines survived; of 365
   surviving `ner`-kind records, 361 match one of the 199 expected texts' first 200 characters
   exactly, and the other 4 are confirmed (by printing them) to be the rehearsal fixture's own
   text ("Keeps orders. Acme Robotics is headquartered in Boulder…", "Place an order: total it
   with billing…") — not main-run content. `lib_instrument.py` was fixed afterward (env-var log
   path) so this can't recur, but that fix landed *after* the main run's process had already
   started — Python does not hot-reload a running process's imports — so `lib_instrument_v1_as_launched.py`
   (quoted below) is the exact code that actually produced the main run's log. It is what step 2's
   naive `"CREATE TABLE" in text` substring check ran; the current `lib_instrument.py` (with
   `passage_id` attribution and the env-var log path) is only ever imported by the small rehearsal
   script and was not used by any of the numbered scripts (`02`–`08`) that produced this report's
   numbers.

Scripts live under `/tmp/hippo-qa1/scripts/`, quoted in full in Evidence below; all scratch data
(`/tmp/hippo-qa1/`) is deleted once this report is committed, per the brief.

## Step 1 — scratch server

`HIPPO_DATA_DIR=/tmp/hippo-qa1/data HIPPO_STORE=ladybug HIPPO_LLM_MODEL=qwen3.8:latest
.venv/bin/hippo serve --port 8012` started cleanly against the already-indexed subset memory
(never port 8000, never `data/`):

```
INFO:     Started server process [70945]
INFO:     Waiting for application startup.
INFO mcp.server.streamable_http_manager: StreamableHTTP session manager started
INFO hippo.mcp_server: MCP server ready at /mcp
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8012 (Press CTRL+C to quit)
```

`GET /api/status`: `store: true`, `ollama: true`, `models_ready: true`,
`stats.passages: 944`, `stats.symbols: 660`, `stats.synonym_edges: 3738` — matches the Python-API
numbers below exactly (same live memory, two lenses on it).

`POST /api/ask {"question": "what does GraphIndex.load do"}` over real HTTP: top-level response
keys are `['answer', 'passage_ids', 'thought', 'trace']`; `trace`'s keys are `['expansions',
'fact_candidates', 'fallback_reason', 'filter', 'graph_version', 'history', 'passages', 'paths',
'question', 'question_code', 'question_prose', 'seed_entities', 'seed_passages', 'seed_symbols',
'select', 'settings', 'tests', 'timing_ms', 'top_nodes', 'used_code_seeds', 'used_dpr_fallback']`.
**`context_block` is present on neither** — confirmed live over HTTP, matching the prediction from
reading `web/routes/api.py`'s `ask()` handler (see Surprises: this is WP4a's planned work).

Server stopped cleanly after this single verification call.

## Step 2 — index hippo's own subset, twice (CI gates 1 and 2)

**Wall time:** pass 1 (fresh source): **2352.2s** (39.2 min). pass 2 (same zip, second source):
**2191.7s** (36.5 min). 398 NER + 398 triples real Ollama calls total, exactly `2 × 199` — matches
the dry-run's prediction of 199 OpenIE-needing chunks per pass to the call.

**`meta["code"]` (pass 1, byte-identical to pass 2):**

```json
{
  "symbols": 330, "data_objects": 0, "edges": 875,
  "edges_by_kind": {"CONTAINS": 313, "IMPORTS": 84, "INVOKES": 473, "RAISES": 5},
  "files_parsed": 17,
  "files_skipped": {"parse_error": 0, "too_big": 0, "unsupported": 0},
  "unresolved_calls_total": 1571,
  "truncated": false
}
```

This is **identical** to the pure-static dry-run computed before any Ollama call was made — a
strong determinism anchor independent of the model.

**CI gate 1**, done two ways:

1. The quick check (`02_index_run.py`'s own comparison, ids normalized to `(path, qualname, kind)`
   for symbols/data and edges remapped through that key): `meta_code_equal=true`,
   `symbol_multiset_equal=true`, `edge_multiset_equal=true` (330 symbols / 875 edges each pass).
2. The **same shape the pinned test uses** (`tests/unit/test_indexer.py`'s
   `test_indexing_the_same_tree_twice_gives_the_same_graph`'s `comparable()` helper — nodes, data
   objects, edges with provenance, DEFINED_IN, REFERS_TO, each keyed by `(path, qualname)` rather
   than by id since ids embed `source_id` and the two passes are, by construction, two different
   sources): **all five sections equal** — nodes 330, data 0, edges 875, DEFINED_IN 28, REFERS_TO 6,
   identical between passes.

**CI gate 2.** The dry-run's exact accounting for the subset (472 total chunks): **22 pure-prose
chunks** (`extract_text is None`, unchanged — README.md), **273 code chunks skipped entirely**
(`extract_text == ""`, no or too-short docstring), **177 code chunks with a real docstring**
(`extract_text` ≥ 80 chars) — 22 + 177 = **199 chunks needing a real OpenIE call**, matching the
398+398 measured calls exactly.

Checked two ways, as described in Methodology:

- **Authoritative (no Ollama, no log):** recomputed all 199 expected `(title, openie_text)` pairs
  the same way the indexer does (`08_gate2_attribution.py`). A **real** failure would be a
  code-titled chunk whose sent text is as long as its own body *and* that body actually looks like
  a function/class (excludes legitimate docstring-only stubs), or any sent text matching a real
  `CREATE TABLE name (` statement shape, or a `def`/`class` line followed by an indented line.
  **0 failures.** (The first pass of this check flagged 2 false positives — both docstrings in
  `codegraph/data_access.py` and `codegraph/model.py` that *describe* SQL handling in English
  prose, e.g. "its `` `CREATE TABLE` ``s become tables" — from a naive `"CREATE TABLE" in text`
  substring check; tightened to `CREATE\s+TABLE\s+[\w."\`]+\s*\(` before reporting PASS.)
- **Confirmatory, against the surviving log** (see Methodology's corruption note): 731 of the
  main run's ~796 log lines survived; of 365 surviving `ner`-kind records, **361 match one of the
  199 expected texts' first 200 characters exactly**, and the other 4 (verified by printing them)
  are the rehearsal fixture's own text, not main-run content. The log's `contains_function_body`
  flag (checked against the whole log): 0 records. The log's `contains_create_table` flag, which
  is `lib_instrument_v1_as_launched.py`'s **naive** `"CREATE TABLE" in text` substring check (the
  main run's actual instrumentation — see Methodology bug #2, the tightened regex only exists in
  `08`'s standalone recomputation): **6 records** (3 `ner` + 3 `triples`), every one of them the
  same two descriptive docstrings identified above (`data_access.py`'s `read_sql_file` and
  `model.py`'s `DataObject`, each appearing more than once across the two indexed passes) — the
  same false positives the authoritative check already found and ruled out, not new ones.

## Step 3 — synonyms under the real embedder

3,738 total SYNONYM edges after both passes. Indexing the same zip **twice** means every symbol
has a same-named twin in the other source, so a large share of same-kind (Symbol↔Symbol) pairs are
trivial cross-source self-matches at score ≈1.0 — a real, scaled SYNONYM edge (the plan's retrieval
table lists "Symbol–Symbol" as an example of the scaled row) but an artifact of this test's
double-indexing, not what spike 2 measured or what needs hand-labelling. Split accordingly:

- **826 same-kind (Symbol↔Symbol) pairs** — the duplicate-indexing artifact above.
- **1,036 Entity↔Symbol/DataObject pairs (492 distinct after dedup)** — spike 2's actual scope.

**Top 30 distinct Entity↔Symbol pairs by score, hand-labelled:**

```
0.9829  Entity:'resolve symbol' ~ Symbol:'resolve_symbol'
0.9823  Entity:'exception anchors' ~ Symbol:'_exception_anchors'
0.9819  Entity:'extract code' ~ Symbol:'extract_code'
0.9815  Entity:'in branch' ~ Symbol:'_in_branch'
0.9810  Entity:'passage position' ~ Symbol:'passage_position'
0.9810  Entity:'diff anchors' ~ Symbol:'_diff_anchors'
0.9804  Entity:'code shaped' ~ Symbol:'_code_shaped'
0.9801  Entity:'header end' ~ Symbol:'_header_end'
0.9800  Entity:'export default' ~ Symbol:'_default_export'
0.9800  Entity:'frame anchors' ~ Symbol:'_frame_anchors'
0.9799  Entity:'enters synonym search' ~ Symbol:'enters_synonym_search'
0.9798  Entity:'arg binding' ~ Symbol:'_arg_binding'
0.9797  Entity:'find anchors' ~ Symbol:'find_anchors'
0.9788  Entity:'build igraph' ~ Symbol:'build_igraph'
0.9786  Entity:'passage id' ~ Symbol:'passage_id'
0.9785  Entity:'module qualname' ~ Symbol:'module_qualname'
0.9772  Entity:'statement lines' ~ Symbol:'_statement_lines'
0.9766  Entity:'graph index' ~ Symbol:'graph_index'
0.9762  Entity:'resolve raises' ~ Symbol:'resolve_raises'
0.9762  Entity:'find synonyms' ~ Symbol:'find_synonyms'
0.9757  Entity:'code node' ~ Symbol:'_code_node'
0.9734  Entity:'name index' ~ Symbol:'_name_index'
0.9729  Entity:'new parser' ~ Symbol:'new_parser'
0.9727  Entity:'make id' ~ Symbol:'make_id'
0.9708  Entity:'code graph' ~ Symbol:'CodeGraph'
0.9703  Entity:'graph with edits' ~ Symbol:'graph_with_edits'
0.9696  Entity:'data access' ~ Symbol:'data_access'
0.9683  Entity:'index source' ~ Symbol:'index_source'
0.9677  Entity:'rows with good vectors' ~ Symbol:'_rows_with_good_vectors'
0.9676  Entity:'entity names' ~ Symbol:'entity_names'
```

**0/30 nonsense (0%)** by the same "would a reader accept these as the same thing" standard spike
2 used — every pair is the un-snake-cased English of the exact symbol it matches. This beats spike
2's prediction (≤27% nonsense after the ≥2-token guard) by a wide margin, for two compounding
reasons, not a contradiction of spike 2: (1) the ≥2-token guard (`enters_synonym_search`,
confirmed below) structurally *removes* the failure mode spike 2 found — single-word generic
symbol names (`run`, `load`, `library`) never enter the key matrix at all, so they cannot collide
with a generic prose phrase; (2) this corpus's Entities came from OpenIE reading hippo's own
technical docstrings, which describe what a function does using vocabulary close to its name, not
spike 2's adversarial synthetic set of generic business nouns built specifically to find the
collision. The two failure modes are different corpora, and both results are correct for their
corpus. A larger, more adversarial memory (prose that discusses "the library", "the run", "a
search") would still need the ≥2-token guard as the load-bearing defense — the 0% here is evidence
the guard *works*, not evidence it's unneeded.

**D7 / spike 2 remedy, checked both directions:** `load_symbols()`'s row shaper does not carry an
`embedding` field at all (confirmed empirically — every row was missing the key; `SYMBOL_DEFAULTS`
in `store/code.py` does not list it), so the only authoritative source for "does this id have a
stored vector" is `load_code_embeddings()`, the actual key matrix `find_synonyms` searches:
**0 one-token symbols have an embedding, and 0 multi-token symbols are missing one** — the guard
neither under- nor over-fires on this real corpus.

## Step 4 — five real Ask calls

| # | Question | `used_code_seeds` | seed_symbols | select ran | `context_block` | `timing_ms` keys | answer quality |
|---|---|---|---|---|---|---|---|
| a | traceback ending `retriever.py:296, in retrieve` | **True** | 5 (1 stack_trace @ w=1.0, 4 dense) | True | 1759 chars | embed, filter, ppr, paths, total | ran out of `QA_MAX_TOKENS` before `Answer:` (Surprise 5) |
| b | "what does GraphIndex.load do" | **True** | 5 (2 identifier @ w=1.0, 3 dense) | True | 1838 chars | embed, filter, ppr, paths, total | clean, correct |
| c | "where is find_anchors called" | **True** | 5 (2 identifier @ w=0.25, 3 dense) | True | 1793 chars | embed, filter, ppr, paths, total | **wrong** — see Defect 1 |
| d | "what backends can hippo use" (prose) | **False** | 0 | False | **""** | embed, filter, ppr, total (no `paths`) | clean, correct |
| e | "how long does it take to load a big file" (bare "load") | **False** | 2 (both dense) | False | **""** | embed, filter, total (no `ppr`, no `paths`) | clean, correct ("not specified") |

(d) and (e) both show `used_code_seeds == False` and an empty context block, exactly as spike 1's
fallback (b) predicts: a bare all-lowercase single-token word ("load") never anchors, whatever it
means in the sentence, but *can* still contribute dense seed mass (e in fact pulled 2 dense seeds
from `graph_index.py`, without flipping the gate) — precisely Ruling 1a's "dense seeds add reset
mass but never flip the gate" spelled out on a real question. (e) has no `ppr` key at all because
`trace.used_dpr_fallback == True`: no lexical anchor fired and the fact filter kept nothing, so
retrieval fell back to plain DPR similarity and PPR never ran — a second real question
demonstrating the same fallback path (b)/(a)/(c) never take.

**The `weight` column needs one more layer to read correctly.** The number in the table above is
the *final* `SeedSymbol.weight` (after `retriever.py`'s `_code_seeds`), not the raw anchor share:
`anchors.py` gives a **qualified** match (`GraphIndex.load`, dotted) the *full* `code_seed_weight`
per hit with no fan-out division ("the dots already say which one it is" — `anchors.py:377`), while
a **bare** code-shaped match (`find_anchors`, snake_case) divides `code_seed_weight` by its
`n_matches` (`anchors.py:392`, S2.13's ambiguity-adjacent fan-out rule). Both are then divided
again by the vertex's node-specificity (`in_degree + 1`, S2.4, `retriever.py:531-533`) before
becoming the trace's `weight`. (b)'s `GraphIndex.load` has `in_degree=0` (specificity 1), so
`1.0 / 1 = 1.0`; (c)'s `find_anchors` has `in_degree=1` (specificity 2) and `n_matches=2` (it
matched itself in *both* indexed copies), so `(1.0 / 2) / 2 = 0.25` — the arithmetic checks out
exactly once both layers are accounted for, and both are working as documented, not a defect.

(a)'s stack-trace anchor: `token="src/hippo/hipporag/retriever.py:296"`, `how="stack_trace"`,
`weight=1.0` (top frame, `0.8**0`), correctly resolved to `Retriever.retrieve`. `context_block`
(1759 chars) verbatim, first lines:

```
Relations read from the code graph, not from prose. INVOKES = calls, IMPORTS = imports, INHERITS = subclasses, OVERRIDES = replaces, CONTAINS = defines, RAISES / CATCHES = throws or handles, TESTED_BY = is covered by, READS / WRITES = uses or changes a table or collection. The number in brackets is a confidence between 0 and 1.
src.hippo.hipporag.retriever.Retriever.retrieve -[INVOKES 0.90 via_import]-> src.hippo.hipporag.anchors.split_question
src.hippo.hipporag.anchors -[CONTAINS 1.00 syntax]-> src.hippo.hipporag.anchors.split_question
src.hippo.hipporag.retriever.Retriever.retrieve -[INVOKES 0.50 fuzzy_name in_branch]-> src.hippo.hipporag.graph_index.GraphIndex.graph_for_scale
...
… (+51 more)
```

`select` for (a): `keep=[2 passages]`, `drop=[3 passages]`, `expand=[]` — the LLM select pass ran,
read the ranked passages, and pruned three it judged irrelevant, keeping the two `retriever.py`
excerpts that actually contain line 296. Retrieval and the context block worked correctly.

**But (a) never produced an `Answer:` line.** `answer.thought` is empty and `answer.answer` is
3,758 characters of pure `Thought:` reasoning that runs straight into `QA_MAX_TOKENS=1024`'s
truncation mid-sentence ("...If `trace` is `None`,"). `answer_question`'s `split_answer` found no
`Answer:` marker in the raw reply, so the whole raw thought became `answer.answer` — this is not
special-cased truncation handling, it is what happens when the model runs out of budget before
concluding. Reading the reasoning: the model correctly notices the traceback is impossible (`trace`
is assigned two lines above 296 in the retrieved source, so it cannot be `None` there) and spends
its entire budget enumerating hypotheses (shadowing, a `None` `index`, a misleading snippet) without
converging — because **the bug I invented for this synthetic traceback is not actually reachable**,
the model is correctly reasoning about an unanswerable question, just never says so out loud before
the token cap. (b)'s answer, by contrast, is a clean 314-character `Answer:`-only reply (no
`Thought:` prefix at all) — the format works fine when the model converges quickly, which most real
questions will. Worth a line in the docs or a UX note: on a slow local model, a hard-to-diagnose
question can exhaust `QA_MAX_TOKENS` before reaching `Answer:`, and the user sees the raw
reasoning trail rather than an error or a "still thinking" indicator.

**(c) is wrong, and it is a real defect, not a model-quality issue — see Defects below.**
`answer.thought` (2,286 chars, real) correctly reasons through the visible context block, notices
it lists only outgoing edges of `find_anchors`, and concludes "the provided text does not specify
where `find_anchors` is called from." `answer.answer` is 1,411 characters of the same reasoning
with no clean conclusion. **The model is right that the block doesn't show it, and the block is
wrong to omit it**: `find_anchors` has a real caller, `Retriever._code_seeds -[INVOKES
0.90]-> find_anchors` (`retriever.py:551`), at ω well above the default `code_theta=0.5` — but
`paths.direct_edges`'s "everything one hop … in a fixed order (out first, then in)"
(`paths.py:210`) puts all 16 of `find_anchors`'s eligible *outgoing* edges before any of its 6
*incoming* ones, and the default `code_triples_chars=1500` only fits 14 lines, so the one edge
that actually answers "where is X called" never reaches the rendered block for any function whose
own outgoing calls outnumber `code_triples_chars / (average line length)`. Full repro and fix
pointer in Defects.

**Methodology artifact, not a defect:** because the same content is indexed twice (for CI gate 1),
every question's top-5 shows exact duplicate titles back-to-back (two physically distinct passages
with identical text, one per source) — e.g. (a)'s rank 3/4 are both
`hipporag/__init__.py (lines 1-27) (part 1)`. A single-indexed memory would not show this.

## Step 5 — inertness

`code_seed_weight=0, code_dense_seeds=0, code_select=False, code_structural_scale=0` applied via
`ctx.store.update_settings(...)` — **exactly** what `PUT /api/settings` calls, with no manual graph
invalidation, because none is needed: `update_settings` does not bump `graph_version`
(`graph_version_before == graph_version_after == 2`, confirmed), and `code_structural_scale` is
read live on every `retrieve()` call via `GraphIndex.graph_for_scale(scale)`
(`graph_index.py:717`), which rebuilds and memoises its own igraph view lazily — a settings change
takes effect on the *next* ask with no reindex and no explicit cache-bust, which is the real
production path a user hits.

Non-vacuous before/after (a code vertex at scale=0 has degree 0 and simply does not reach
`top_nodes`, so "all zero" would be trivially true on an empty list — the meaningful comparison is
count-before vs. count-after):

| Question | code-kind `top_nodes`, baseline | code-kind `top_nodes`, after inertness |
|---|---|---|
| (b) "what does GraphIndex.load do" | **24** | **0** |
| (d) "what backends can hippo use" | **12** | **0** |

Also confirmed after the settings change: `used_code_seeds=False`, `context_block=""`, and
`timing_ms` has no `paths` key for both questions — the second-LLM-pass gate (`code_select`), the
seed gate, and the path-tool gate all switched off together, matching the docs/FIDELITY.md
sentence this proves.

**The ranking deltas the brief asks for, in full — this is the actual headline result, not just
the node counts above.**

(b) "what does GraphIndex.load do" — baseline top-5 is entirely code, led by the exact function
asked about; after inertness, `GraphIndex.load` **disappears from the top 10 altogether** and the
ranking becomes plain-DPR passages from the same three files, no longer boosted by PPR mass from
the code graph:

```
baseline:  1/2  0.0017  graph_index.py :: GraphIndex.load (lines 221-244) (part 1)
           3/4  0.0020  hipporag/__init__.py (lines 1-27) (part 1)
           5    0.0015  hipporag/anchors.py (lines 1-20) (part 1)
after:     1/2  0.0035  hipporag/__init__.py (lines 1-27) (part 1)
           3/4  0.0024  hipporag/anchors.py (lines 1-20) (part 1)
           5/6  0.0021  hipporag/anchors.py :: find_anchors (lines 196-218)
```

(d) "what backends can hippo use" (prose) — **the ranking is identical, title for title and rank
for rank, before and after**; only the absolute PPR scores move (uniformly higher, consistent with
removing the code vertices redistributing mass among what's left), which is exactly
`docs/FIDELITY.md`'s "a prose corpus indexed alongside code ranks identically" sentence, checked
against a real run rather than asserted:

```
baseline:  1/2  0.0041  README › Choosing a backend (part 3)
           3/4  0.0021  README › Run it (part 1)
           5    0.0020  README › Choosing a backend (part 1)
after:     1/2  0.0056  README › Choosing a backend (part 3)
           3/4  0.0028  README › Run it (part 1)
           5    0.0028  README › Choosing a backend (part 1)
```

One unexplained number, reported rather than omitted: the first ask *after* applying the inertness
settings took **43.9s** for (b) versus ~9.7s at baseline (and (d) was 9.1s post-settings, close to
its own baseline) — likely LLM-call variance under this host's load (six other fleet workers were
running test suites throughout), not a cost of the settings change itself, since
`graph_for_scale`'s rebuild is a pure in-memory igraph operation (Step 6 measures the whole
`GraphIndex.load`, vectors included, at 0.18s, so a same-process igraph rebuild is not plausibly
40+ seconds) and the fact-filter LLM call dominates `timing_ms` regardless of these settings.

## Step 6 — timings

`extract_code` over the **full** `src/hippo` (not just the subset, per the brief's CI gate 2
wording): **0.272s**, budget < 5s — **PASS**, with room to spare (R4 T9's "milliseconds" claim
holds; the budget is for resolution, not parsing, and resolution is included in this number).
1,147 symbols found (the whole package, versus 330 in the hipporag/codegraph subset actually
indexed).

`GraphIndex.load` against this run's live memory (944 passages, 660 symbols, 3,738 synonym edges):
**0.176s**. Spike 3 flagged vector-reload cost as the real scaling risk (117 MiB at the largest
size hippo will accept); this memory's footprint is far below that, so this number does not
stress-test the concern — it confirms the concern doesn't bite at ordinary scale, not that it
never bites.

## Defects

Every gate the brief numbers (CI gate 1, CI gate 2, inertness, anchors-on-prose, synonym quality,
timings) passed on the real model and the real embedder, including two false positives this run's
own checks raised and then resolved by tightening the check rather than the target (the
`CREATE TABLE` substring match on descriptive prose, Step 2; the vacuous embedding/settings checks
caught in rehearsal before they ran for real, Methodology). One real defect surfaced by question
(c), outside those six numbered gates:

**1. A "where is X called" / "who calls X" question can get a `Title: Code graph` block that never
shows the calling edge, for any symbol whose own outgoing edges outnumber what
`code_triples_chars` fits before its incoming edges are reached.**

- **Reproduction:** default settings, subset memory as built in Step 2 (or any memory with a
  similarly-connected function). Ask "where is find_anchors called".
- **Expected:** the context block includes `Retriever._code_seeds -[INVOKES 0.90]-> find_anchors`
  (`retriever.py:551`, the real, resolved caller, ω=0.90, well above the default
  `code_theta=0.5`), and the model answers with it.
- **Observed, verified by direct reproduction** (calling `paths.code_paths_for` with this
  question's exact seed vertices, outside of `render_block`'s char cut, to see the full ordered
  list `cut_to` truncates): **29 edges total**, in this exact order —
  10 lines of `find_anchors`'s own outgoing INVOKES (to `_best`, `_diff_anchors`,
  `_exception_anchors`, `_frame_anchors`, `_plain`, `_token_anchors`, `_without`, `split_question`,
  some appearing twice across the two indexed copies), one shortest-path hop
  (`_diff_anchors -> _anchor`), two CONTAINS edges for other seeds, then **position 14**:
  `anchors -[CONTAINS]-> find_anchors` (the module containing it — an incoming edge, but not an
  answer to "who calls"). `render_block`'s char cut lands exactly there: 14 lines rendered,
  "(+16 more)" reported. **Positions 15 and 16 — the very next two edges, immediately past the
  cut** — are `retriever -[IMPORTS 0.95]-> find_anchors` and
  `Retriever._code_seeds -[INVOKES 0.90]-> find_anchors`: the real, resolved, well-above-threshold
  caller edge that answers the question. `answer.thought` correctly notices the block it *was*
  shown has no incoming INVOKES edge and `answer.answer` concludes the information isn't
  available — a wrong answer to a question the graph can answer, missed by one or two lines.
- **Root cause:** `code_paths_for` (`paths.py:214-245`) first runs every pairwise
  `shortest_code_path` between seed vertices (the one `_diff_anchors -> _anchor` hop above comes
  from this pass), then walks seed vertices in seed order appending each vertex's full
  `direct_edges` result — and `direct_edges` (`paths.py:209-211`) states its own contract:
  "everything one hop from a vertex, both ways, in a **fixed order (out first, then in)**."
  `render_block`/`cut_to` then truncate that single list at `code_triples_chars` (default 1500) on
  a line boundary with no reordering. A well-connected symbol's own outgoing calls are therefore
  *always* listed ahead of its callers within its own `direct_edges` block, however close the
  caller edge's ω is to the top — this case happened to land the payoff edge one line past a
  ~14-line budget, but the ordering has no notion of "this edge answers the question" or even
  "this edge outranks that one"; it is pairwise-shortest-paths-first, then per-seed
  out-then-in, with no relevance-based sort anywhere in the pipeline.
- **Suggested fix directions** (not evaluated here — this run is read-only): interleave out/in
  edges instead of a fixed out-then-in order per seed; sort the whole `code_paths_for` list by ω
  descending before the char cut, so the most-confident edges in *either* direction survive
  regardless of direction; or bias toward the direction the question implies ("called"/"used by"
  → incoming first) the way `anchors.py` already distinguishes anchor `how` kinds.
- **Scope check:** verified precisely only for this one question against this one (double-indexed)
  memory — the defect is structural (a fixed, unprioritized ordering with a hard character budget
  and no notion of relevance), so it is not specific to double-indexing in principle, but no
  single-indexed repro was run to confirm the caller edge would still miss the cut with half as
  many duplicate lines in front of it. That would be the first thing to check before filing a fix.

## Surprises

1. **The full-repo index would take ~13.4h, not a smoke.** Dry-run (no Ollama:
   `readers.read_zip` + `extract_code` + `chunk_documents`) on the brief's full zip (`src/`, `tests/`,
   `docs/`, `README.md`, `pyproject.toml`) gives 204 documents, 3,789 chunks, of which **1,514 need a
   real NER+triples call** (903 pure-prose passages, 611 code passages whose docstring clears
   `MIN_OPENIE_DOC_CHARS`; 2,275 code chunks correctly skip OpenIE entirely, `extract_text == ""`).
   One measured NER+triples pair against `qwen3.8:latest` on this host cost 16s in isolation and
   16-21s/passage in the real serialized run (`HIPPO_OPENIE_WORKERS=1`, host also running six other
   fleet workers' test suites). That is **~6.7h for one pass, ~13.4h for the two CI gate 1 needs** —
   this is exactly what `pipeline.py`'s own comment anticipates ("anything past this would keep the
   OpenIE workers busy for days") and what `readers.py` states outright ("a local model can index in
   a day"), but it is worth a sentence in the docs: a user pointing hippo at a real monorepo with
   `HIPPO_OPENIE_WORKERS=1` and a single local model should expect multi-hour indexing, and
   `HIPPO_OPENIE_WORKERS` (more parallel calls hippo makes) / Ollama's own `OLLAMA_NUM_PARALLEL`
   (more Ollama will actually run concurrently) are the two knobs that shorten it — not something
   to file as a bug when it happens on a large real repository.
2. **Synonym quality on hippo's own docstrings is far better than spike 2's adversarial prediction**
   (0% nonsense in the top 30 vs. ≤27% predicted) — see Step 3 for why this doesn't contradict
   spike 2 (the ≥2-token guard removes exactly spike 2's failure mode; this corpus isn't
   adversarial). Worth remembering when WP4's eval set is built: a *representative* prose corpus
   (business nouns, generic descriptions) will show a higher nonsense rate than this technical
   corpus did, and that's the more informative test for tuning the guard further.
3. **`/api/ask`'s JSON response omits `Answer.context_block`.** Confirmed by direct HTTP call in
   Step 1 (`trace` and top-level response keys listed there in full). `Answer` carries
   `context_block` already (`hipporag/answerer.py:27`); WP4a's briefing explicitly names exposing
   `context_block` on the `Answer` as part of its scope ("`context_block` on the `Answer`. You
   expose the path tools over HTTP, MCP and the CLI.") — this is planned, in-flight work on
   `code-graph`, not a regression, so it is recorded here rather than filed as a Defect.
4. **Indexing the same content twice (needed for CI gate 1) visibly perturbs the Ask and synonym
   results**: duplicate top-5 passages (Step 4), and Symbol↔Symbol self-match SYNONYM edges at
   score ≈1.0 dominating the raw ranking before filtering to Entity↔Symbol pairs (Step 3). Neither
   is a hippo defect — both are real, correct behavior of a memory that happens to contain
   duplicate content — but a future real-model smoke that wants clean single-copy Ask/synonym
   numbers should index the fixture once and use a *second*, separate source for CI gate 1's
   determinism check instead of doubling the same memory.
5. **A hard question can exhaust `QA_MAX_TOKENS` (1024) before the model reaches `Answer:`.**
   Question (a) (Step 4) is a synthetic, actually-unreachable bug (the traceback claims `trace` is
   `None` two lines after it is assigned); the real `qwen3.8:latest` correctly reasoned that
   something didn't add up but spent all 1024 tokens exploring hypotheses without concluding, so
   `split_answer` found no `Answer:` marker and the entire raw `Thought:` became `answer.answer` —
   3,758 characters of reasoning shown to the user as "the answer," truncated mid-sentence. This
   is not a bug in `split_answer` (it does exactly what it should when the marker never appears);
   it is a real characteristic of small local models on hard synthetic questions worth a line in
   the docs, since a user would reasonably read a cut-off wall of `Thought:` text as broken output
   rather than "still thinking." (b), (d) and (e)'s answers were all clean, `Answer:`-only replies,
   so this is a tail case, not the common one. ((c)'s answer field starts mid-sentence with a bare
   `**`, suggesting the raw reply used `**Answer:**` in markdown bold and `split_answer`'s marker
   match left the leading asterisks — a formatting artifact riding along with Defect 1's wrong
   *content*, not a second bug.)

## Evidence — scripts

`/tmp/hippo-qa1/scripts/00_dry_run_counts.py` — the zip → chunk dry run, no Ollama, used both to
decide the subset's scope and to recompute CI gate 2's authoritative expected-text set:

```python
"""
Dry run: read the QA1 zip and chunk it exactly as run_indexing would, WITHOUT calling Ollama,
to count how many passages will actually need a real OpenIE call (NER + triples) versus how
many are skipped (extract_text == "" -- short/absent docstring) or unchanged prose (extract_text
is None). No store, no AppContext: this only exercises readers.read_zip, extract_code and
chunk_documents, so it is safe to run before deciding whether the real run is hours or days.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from hippo.codegraph import extract_code  # noqa: E402
from hippo.ingest import readers  # noqa: E402
from hippo.ingest.chunker import chunk_documents  # noqa: E402
from hippo.hipporag.indexer import MIN_OPENIE_DOC_CHARS  # noqa: E402

ZIP_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/hippo-qa1/hippo_repo.zip")
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 150


def openie_text(chunk):
    if chunk.extract_text is None:
        return chunk.text
    return chunk.extract_text if len(chunk.extract_text.strip()) >= MIN_OPENIE_DOC_CHARS else None


def main() -> None:
    t0 = time.time()
    budget = readers.TextBudget(limit=readers.MAX_TEXT_CHARS)
    docs = readers.read_zip(ZIP_PATH, ZIP_PATH.name, budget)
    t1 = time.time()
    print(f"documents: {len(docs)}  (read_zip: {t1 - t0:.2f}s)")

    code = extract_code(docs, "dryrun-source")
    t2 = time.time()
    print(f"extract_code: {t2 - t1:.2f}s  meta={code.stats()}")

    chunks = chunk_documents(docs, CHUNK_SIZE, CHUNK_OVERLAP, code=code)
    t3 = time.time()
    print(f"chunk_documents: {t3 - t2:.2f}s  total chunks: {len(chunks)}")

    needs_openie = 0
    skipped_empty = 0
    skipped_short_doc = 0
    prose_none = 0
    for c in chunks:
        text = openie_text(c)
        if c.extract_text is None:
            prose_none += 1
        elif c.extract_text == "":
            skipped_empty += 1
        elif len(c.extract_text.strip()) < MIN_OPENIE_DOC_CHARS:
            skipped_short_doc += 1
        if text is not None:
            needs_openie += 1

    print(f"prose chunks (extract_text is None): {prose_none}")
    print(f"code chunks, extract_text == '' (skipped, no/short doc): {skipped_empty}")
    print(f"code chunks, doc < {MIN_OPENIE_DOC_CHARS} chars (skipped): {skipped_short_doc}")
    print(f"TOTAL chunks needing a real OpenIE call (NER+triples): {needs_openie}")
    print(f"total wall clock for dry run: {time.time() - t0:.2f}s")


if __name__ == "__main__":
    main()
```

`/tmp/hippo-qa1/scripts/lib_instrument_v1_as_launched.py` — the **exact** instrumentation that
produced the main run's log (see Methodology bug #2 for why this is kept separately from the
current `lib_instrument.py`):

```python
"""
This is the exact content of lib_instrument.py at the moment 02_index_run.py (pid 69093, the
main indexing run whose numbers this report uses) was launched -- kept verbatim for the report
because lib_instrument.py itself was edited twice AFTER that launch (to add passage_id
attribution and to fix the CALLS_LOG path collision described in the CI gate 2 section), and
Python does not hot-reload an already-running process's imports. The main run's log
(openie_calls.log) was produced by THIS version: no `passage_id` field, hardcoded log path.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

CALLS_LOG = Path("/tmp/hippo-qa1/openie_calls.log")
COUNTS = {"ner": 0, "triples": 0, "other": 0}


def _looks_like_function_body(text: str) -> bool:
    lines = text.splitlines()
    return any(
        line.strip().startswith(("def ", "async def ", "class "))
        and i + 1 < len(lines)
        and lines[i + 1].startswith(("    ", "\t"))
        for i, line in enumerate(lines)
    )


def install() -> None:
    from hippo import prompts
    from hippo.ollama import Ollama

    original_chat_json = Ollama.chat_json
    CALLS_LOG.write_text("")  # fresh log for this run

    def patched_chat_json(self, messages, schema, *, max_tokens=None, temperature=0.0):
        if schema is prompts.NER_SCHEMA:
            kind = "ner"
        elif schema is prompts.TRIPLES_SCHEMA:
            kind = "triples"
        else:
            kind = "other"
        COUNTS[kind] = COUNTS.get(kind, 0) + 1
        # ner_messages/triples_messages (prompts.py) each carry TWO user messages: a fixed
        # one-shot example first, then the real passage last. The first user message is always
        # "Radio City is India's first..."; the real content under test is the LAST one.
        user_messages = [m["content"] for m in messages if m.get("role") == "user"]
        user_text = user_messages[-1] if user_messages else ""
        t0 = time.time()
        result = original_chat_json(self, messages, schema, max_tokens=max_tokens, temperature=temperature)
        dt = time.time() - t0
        if kind in ("ner", "triples"):
            record = {
                "kind": kind,
                "seconds": round(dt, 2),
                "text_chars": len(user_text),
                "contains_function_body": _looks_like_function_body(user_text),
                "contains_create_table": "CREATE TABLE" in user_text,
                "text_preview": user_text[:200],
            }
            with CALLS_LOG.open("a") as f:
                f.write(json.dumps(record) + "\n")
        return result

    Ollama.chat_json = patched_chat_json


def summary() -> dict:
    return dict(COUNTS)
```

`/tmp/hippo-qa1/scripts/02_index_run.py` — the two-pass real index run:

```python
"""
QA1 step 2: index the subset zip (src/hippo/hipporag/, src/hippo/codegraph/, README.md) as a
real source, twice, through the real Python API (pipeline.add_upload + the background job
queue), against the real qwen3.8:latest / nomic-embed-text on the host. No source or test file
in the repo is touched; instrumentation is a runtime monkeypatch from lib_instrument.py.

Writes progress.json continuously (poll this rather than tailing stdout) and
results_index.json once both passes finish.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path("/Users/mascott/projects/hippo/.worktrees/qa1")
sys.path.insert(0, str(REPO_ROOT / "src"))

os.environ["HIPPO_DATA_DIR"] = "/tmp/hippo-qa1/data"
os.environ["HIPPO_STORE"] = "ladybug"
os.environ["HIPPO_OPENIE_WORKERS"] = "1"
os.environ["HIPPO_LLM_MODEL"] = "qwen3.8:latest"
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_instrument  # noqa: E402

lib_instrument.install()

from hippo.context import AppContext  # noqa: E402
from hippo.ingest import pipeline  # noqa: E402

ZIP_PATH = Path("/tmp/hippo-qa1/hippo_subset.zip")
PROGRESS_FILE = Path("/tmp/hippo-qa1/progress.json")
RESULTS_FILE = Path("/tmp/hippo-qa1/results_index.json")
POLL_SECONDS = 5


def write_progress(**kw) -> None:
    kw["ts"] = time.time()
    PROGRESS_FILE.write_text(json.dumps(kw, indent=2, default=str))


def wait_for_source(ctx, source_id: str, label: str) -> tuple[dict, float]:
    t0 = time.time()
    while True:
        source = ctx.store.get_source(source_id)
        write_progress(
            pass_label=label,
            source_id=source_id,
            status=source.get("status"),
            stage=source.get("stage"),
            progress_done=source.get("progress_done"),
            progress_total=source.get("progress_total"),
            elapsed_s=round(time.time() - t0, 1),
            openie_counts=lib_instrument.summary(),
        )
        if source.get("status") in ("ready", "failed"):
            return source, time.time() - t0
        time.sleep(POLL_SECONDS)


def normalized_symbols(rows: list[dict]) -> list[tuple]:
    keys = ("name", "qualname", "kind", "lang", "path", "line_start", "line_end", "signature", "doc", "in_degree")
    return sorted(tuple(r.get(k) for k in keys) for r in rows)


def id_map(rows: list[dict]) -> dict[str, tuple]:
    return {r["id"]: (r.get("path"), r.get("qualname"), r.get("kind")) for r in rows}


def normalized_edges(edges: list[dict], idmap: dict[str, tuple]) -> list[tuple]:
    out = []
    for e in edges:
        a = idmap.get(e["a"], e["a"])
        b = idmap.get(e["b"], e["b"])
        out.append((a, b, e.get("kind"), e.get("omega")))
    return sorted(out)


def main() -> None:
    ctx = AppContext.from_env()
    print(f"store: {ctx.config.store_location}", flush=True)
    print("warming the model...", flush=True)
    t_warm = time.time()
    ctx.ollama.chat_text([{"role": "user", "content": "reply with the single word: ready"}], max_tokens=8)
    print(f"model warm in {time.time() - t_warm:.1f}s", flush=True)

    data = ZIP_PATH.read_bytes()
    results: dict = {"passes": []}

    for label in ("pass1", "pass2"):
        print(f"--- {label}: indexing {ZIP_PATH.name} ---", flush=True)
        source_id = pipeline.add_upload(ctx, ZIP_PATH.name, data)
        source, wall_s = wait_for_source(ctx, source_id, label)
        print(f"{label}: status={source.get('status')} wall={wall_s:.1f}s", flush=True)

        symbols = [r for r in ctx.store.load_symbols() if r.get("source_id") == source_id]
        code_edges_all = ctx.store.load_code_edges()
        idmap = id_map(symbols) | id_map(
            [r for r in ctx.store.load_data_objects() if r.get("source_id") == source_id]
        )
        edges = [e for e in code_edges_all if e["a"] in idmap or e["b"] in idmap]

        results["passes"].append(
            {
                "label": label,
                "source_id": source_id,
                "wall_seconds": wall_s,
                "status": source.get("status"),
                "error": source.get("error"),
                "meta": source.get("meta"),
                "symbol_count": len(symbols),
                "code_edge_count": len(edges),
                "normalized_symbols": normalized_symbols(symbols),
                "normalized_edges": normalized_edges(edges, idmap),
            }
        )
        RESULTS_FILE.write_text(json.dumps(results, indent=2, default=str))

    p1, p2 = results["passes"][0], results["passes"][1]
    comparison = {
        "meta_code_equal": p1["meta"].get("code") == p2["meta"].get("code") if p1["meta"] and p2["meta"] else None,
        "symbol_multiset_equal": p1["normalized_symbols"] == p2["normalized_symbols"],
        "edge_multiset_equal": p1["normalized_edges"] == p2["normalized_edges"],
        "symbol_count_p1": p1["symbol_count"],
        "symbol_count_p2": p2["symbol_count"],
        "edge_count_p1": p1["code_edge_count"],
        "edge_count_p2": p2["code_edge_count"],
    }
    results["ci_gate_1"] = comparison
    results["openie_counts"] = lib_instrument.summary()
    results["stats_after_both_passes"] = ctx.store.stats()

    RESULTS_FILE.write_text(json.dumps(results, indent=2, default=str))
    print("=== CI gate 1 ===", flush=True)
    print(json.dumps(comparison, indent=2), flush=True)
    print("=== openie counts ===", flush=True)
    print(json.dumps(lib_instrument.summary(), indent=2), flush=True)

    write_progress(status="all_done", openie_counts=lib_instrument.summary())
    ctx.close()


if __name__ == "__main__":
    main()
```

`/tmp/hippo-qa1/scripts/07_ci_gate1_full.py` — CI gate 1, replicated in the pinned test's exact
shape:

```python
"""
QA1 step 2, CI gate 1, done the same way the pinned test does it
(tests/unit/test_indexer.py::test_indexing_the_same_tree_twice_gives_the_same_graph's
`comparable()` helper): nodes, data objects, edges (with provenance), DEFINED_IN and REFERS_TO,
each keyed by (path, qualname) rather than by id, since ids embed source_id and the two passes
are two different sources by construction (exactly as the real test does it).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path("/Users/mascott/projects/hippo/.worktrees/qa1")
sys.path.insert(0, str(REPO_ROOT / "src"))

os.environ["HIPPO_DATA_DIR"] = "/tmp/hippo-qa1/data"
os.environ["HIPPO_STORE"] = "ladybug"

from hippo.context import AppContext  # noqa: E402

RESULTS = Path("/tmp/hippo-qa1/results_index.json")
OUT = Path("/tmp/hippo-qa1/results_ci_gate1_full.json")


def comparable(store, source_id: str):
    symbols = {r["id"]: (r["path"], r["qualname"]) for r in store.load_symbols() if r["source_id"] == source_id}
    data = {r["id"]: (r["kind"], r["qualname"]) for r in store.load_data_objects() if r["source_id"] == source_id}
    keys = {**symbols, **data}
    passages = {p["id"]: p["title"] for p in store.passages_for_source(source_id)}
    nodes = sorted(
        (keys[r["id"]], r["kind"], r["lang"], r["line_start"], r["line_end"], r["signature"], r["doc"])
        for r in store.load_symbols()
        if r["source_id"] == source_id
    )
    data_sorted = sorted(data.values())
    edges = sorted(
        (keys[e["a"]], keys[e["b"]], e["kind"], e["omega"], e["provenance"])
        for e in store.load_code_edges()
        if e["a"] in keys and e["b"] in keys
    )
    defined = sorted(
        (keys[d["node_id"]], passages[d["passage_id"]])
        for d in store.load_definitions()
        if d["node_id"] in keys and d["passage_id"] in passages
    )
    refers = sorted(
        (passages[r["passage_id"]], keys[r["node_id"]], r["omega"], r["token"])
        for r in store.load_refers_to()
        if r["node_id"] in keys and r["passage_id"] in passages
    )
    return {"nodes": nodes, "data": data_sorted, "edges": edges, "defined": defined, "refers": refers}


def main() -> None:
    results = json.loads(RESULTS.read_text())
    id1 = results["passes"][0]["source_id"]
    id2 = results["passes"][1]["source_id"]

    ctx = AppContext.from_env()
    c1 = comparable(ctx.store, id1)
    c2 = comparable(ctx.store, id2)

    diff = {k: (c1[k] == c2[k]) for k in c1}
    out = {"equal_by_section": diff, "all_equal": all(diff.values()), "counts_pass1": {k: len(v) for k, v in c1.items()}, "counts_pass2": {k: len(v) for k, v in c2.items()}}
    for k, ok in diff.items():
        if not ok:
            a, b = c1[k], c2[k]
            out[f"{k}_only_in_pass1"] = [x for x in a if x not in b][:20]
            out[f"{k}_only_in_pass2"] = [x for x in b if x not in a][:20]

    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))
    ctx.close()


if __name__ == "__main__":
    main()
```

`/tmp/hippo-qa1/scripts/08_gate2_attribution.py` — CI gate 2, recomputed authoritatively (see
Methodology bug #2 and Step 2 for why this does not trust the log alone):

```python
"""
QA1 step 2, CI gate 2 -- done without relying on the (partly corrupted, no-passage_id) log from
the main run. The log from `lib_instrument.py` as it ran for the main index (hardcoded path, no
`openie.extract` patch, no `passage_id` field) got overwritten mid-run by a later rehearsal script
that reused the same hardcoded path -- a real bug in the QA harness, not in hippo, documented in
the report. Rather than trust what survives in that file, this recomputes the FULL, authoritative
set of 199 (title, openie_text) pairs the same way `_read_chunk_index` does --
`readers.read_zip` -> `extract_code` -> `chunk_documents` -> `_openie_text` -- which is
deterministic and needs no Ollama, and checks the real gate-2 property directly:

  for every CODE-titled chunk that needs a real call, the text sent (the docstring,
  `chunk.extract_text`) must be strictly shorter than the chunk's own body (`chunk.text`) and
  never equal to it -- i.e. the body itself never reaches the model.

The surviving log lines are then used only as a weaker, confirmatory cross-check: every "ner"
record's `text_preview` that is intact should match one of the 199 expected texts' first 200
chars (a mismatch would mean the real indexer sent something the dry run does not predict, which
would be a genuine finding).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# A real leaked CREATE TABLE statement has a name and an opening paren for its column list.
# The bare English phrase "CREATE TABLE" (or backticked "`CREATE TABLE`s") shows up legitimately
# in prose *describing* SQL handling (data_access.py's and model.py's own docstrings do this) and
# must not be confused with an actual statement reaching the model.
_CREATE_TABLE_STATEMENT = re.compile(r"CREATE\s+TABLE\s+[\w.\"`]+\s*\(", re.IGNORECASE)

REPO_ROOT = Path("/Users/mascott/projects/hippo/.worktrees/qa1")
sys.path.insert(0, str(REPO_ROOT / "src"))

from hippo.codegraph import extract_code  # noqa: E402
from hippo.ingest import readers  # noqa: E402
from hippo.ingest.chunker import chunk_documents  # noqa: E402
from hippo.hipporag.indexer import MIN_OPENIE_DOC_CHARS  # noqa: E402

ZIP_PATH = Path("/tmp/hippo-qa1/hippo_subset.zip")
LOG = Path("/tmp/hippo-qa1/openie_calls.log")
OUT = Path("/tmp/hippo-qa1/results_gate2.json")


def openie_text(chunk):
    if chunk.extract_text is None:
        return chunk.text
    return chunk.extract_text if len(chunk.extract_text.strip()) >= MIN_OPENIE_DOC_CHARS else None


def looks_like_function_body(text: str) -> bool:
    lines = text.splitlines()
    return any(
        line.strip().startswith(("def ", "async def ", "class "))
        and i + 1 < len(lines)
        and lines[i + 1].startswith(("    ", "\t"))
        for i, line in enumerate(lines)
    )


def main() -> None:
    # Use the real pass-1 source_id (from results_index.json, written once indexing finishes)
    # rather than a placeholder: Symbol.display is f"{module}.{qualname}" with no source_id in
    # it, and neither is chunk title or text, so this should not change any of the 199 expected
    # texts -- but matching it exactly removes the doubt rather than asserting it away.
    source_id = json.loads(Path("/tmp/hippo-qa1/results_index.json").read_text())["passes"][0]["source_id"]
    budget = readers.TextBudget(limit=readers.MAX_TEXT_CHARS)
    docs = readers.read_zip(ZIP_PATH, ZIP_PATH.name, budget)
    code = extract_code(docs, source_id)
    chunks = chunk_documents(docs, 1500, 150, code=code)

    expected = []
    for c in chunks:
        text = openie_text(c)
        if text is None:
            continue
        is_code_chunk = c.extract_text is not None and c.extract_text != ""
        # A docstring-only stub (a module whose only content IS its docstring) can legitimately
        # have extract_text == text; that is not a body leak unless the body it "equals" actually
        # looks like a function/class body worth worrying about. Gate on both conditions.
        chunk_body_looks_like_a_body = looks_like_function_body(c.text)
        expected.append(
            {
                "title": c.title,
                "text": text,
                "is_code_chunk": is_code_chunk,
                "chunk_text_chars": len(c.text),
                "openie_text_chars": len(text),
                "chunk_body_looks_like_a_body": chunk_body_looks_like_a_body,
                "flagged_function_body": looks_like_function_body(text),
                "flagged_create_table": bool(_CREATE_TABLE_STATEMENT.search(text)),
            }
        )

    real_failures = [
        e
        for e in expected
        if e["is_code_chunk"]
        and (
            (e["openie_text_chars"] >= e["chunk_text_chars"] and e["chunk_body_looks_like_a_body"])
            or e["flagged_function_body"]
            or e["flagged_create_table"]
        )
    ]
    prose_flagged = [e for e in expected if not e["is_code_chunk"] and (e["flagged_function_body"] or e["flagged_create_table"])]

    # Weak confirmatory cross-check against whatever survived the log corruption.
    log_records = [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()] if LOG.exists() else []
    ner_previews = [r["text_preview"] for r in log_records if r.get("kind") == "ner"]
    expected_prefixes = {e["text"][:200] for e in expected}
    matched = sum(1 for p in ner_previews if p in expected_prefixes)

    out = {
        "expected_openie_chunks": len(expected),
        "expected_code_chunks": sum(1 for e in expected if e["is_code_chunk"]),
        "expected_prose_chunks": sum(1 for e in expected if not e["is_code_chunk"]),
        "real_gate2_failures": real_failures,
        "gate2_pass": len(real_failures) == 0,
        "prose_chunks_containing_code_like_text_ok": prose_flagged,
        "surviving_log_lines": len(log_records),
        "surviving_ner_lines_matching_expected": matched,
        "surviving_ner_lines_total": len(ner_previews),
    }
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({k: v for k, v in out.items() if k not in ("real_gate2_failures", "prose_chunks_containing_code_like_text_ok")}, indent=2))
    print(f"gate2_pass={out['gate2_pass']}  real_failures={len(real_failures)}  prose_flagged(expected, not a failure)={len(prose_flagged)}")


if __name__ == "__main__":
    main()
```

`/tmp/hippo-qa1/scripts/03_synonyms.py` — the synonym listing and hand-labelling input:

```python
"""QA1 step 3: list every cross-kind SYNONYM edge written by the real embedder, with its score,
for hand-labelling against spike 2's prediction (<=27% nonsense after the >=2-token guard).
Also confirms no one-token symbol got an embedding (enters_synonym_search / D7)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path("/Users/mascott/projects/hippo/.worktrees/qa1")
sys.path.insert(0, str(REPO_ROOT / "src"))

os.environ["HIPPO_DATA_DIR"] = "/tmp/hippo-qa1/data"
os.environ["HIPPO_STORE"] = "ladybug"

from hippo.context import AppContext  # noqa: E402
from hippo.hipporag.text import label_of, split_identifier  # noqa: E402

OUT = Path("/tmp/hippo-qa1/results_synonyms.json")


def main() -> None:
    ctx = AppContext.from_env()
    rows = ctx.store.load_synonyms()
    ids = {r["a"] for r in rows} | {r["b"] for r in rows}
    names = {
        r["id"]: r["name"]
        for r in ctx.store.run("MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, n.name AS name", ids=list(ids))
    }

    # Indexing the SAME zip twice (CI gate 1) means every symbol has a same-named twin in the
    # other source, so Symbol-Symbol / DataObject-DataObject pairs are dominated by trivial
    # cross-source self-matches at score ~1.0 -- a real, scaled SYNONYM edge per the plan's table
    # (it lists "Symbol-Symbol" as an example of the scaled "cross-kind" row), but NOT what spike
    # 2's methodology or this step's hand-labelling is about. Spike 2 measured symbol-vs-PROSE
    # confusion specifically: one side Entity, the other Symbol/DataObject. Report both, but the
    # thing to hand-label is `entity_code_pairs`, not `same_kind_pairs`.
    entity_code_pairs = []
    same_kind_pairs = []
    for r in rows:
        la, lb = label_of(r["a"]), label_of(r["b"])
        if la == "Entity" and lb == "Entity":
            continue  # not cross-kind: unscaled entity-entity synonym, out of scope for this check
        row = {
            "a_id": r["a"],
            "a_label": la,
            "a_name": names.get(r["a"], "?"),
            "b_id": r["b"],
            "b_label": lb,
            "b_name": names.get(r["b"], "?"),
            "score": r["score"],
            "manual": r["manual"],
        }
        if (la == "Entity") != (lb == "Entity"):
            entity_code_pairs.append(row)
        else:
            same_kind_pairs.append(row)
    entity_code_pairs.sort(key=lambda x: -(x["score"] or 0))
    same_kind_pairs.sort(key=lambda x: -(x["score"] or 0))
    cross_kind = entity_code_pairs  # kept name for the rest of the script / report references

    # Every pair appears twice (once per indexed copy, since the zip was indexed twice for CI
    # gate 1): dedupe by (a_name, b_name) so "top 30" is 30 distinct concepts, not 15 doubled.
    seen_pairs: set[tuple[str, str]] = set()
    entity_code_distinct = []
    for p in entity_code_pairs:
        key = (p["a_name"], p["b_name"])
        if key not in seen_pairs:
            seen_pairs.add(key)
            entity_code_distinct.append(p)

    # D7 / spike 2 remedy check: no one-token Symbol name should have a stored embedding at all.
    # `load_symbols()`'s row shaper (SYMBOL_DEFAULTS, store/code.py) does not carry `embedding` --
    # confirmed empirically in a rehearsal run, where every row was missing the key entirely -- so
    # `load_code_embeddings()` (the actual key matrix `find_synonyms` searches) is the only
    # authoritative source for "does this id have a stored vector at all".
    all_symbols = ctx.store.load_symbols()
    symbol_names = {s["id"]: s["name"] for s in all_symbols}
    code_emb_ids, _ = ctx.store.load_code_embeddings()
    code_emb_id_set = set(code_emb_ids)
    one_token_with_embedding = [
        {"id": nid, "name": symbol_names[nid]}
        for nid in code_emb_ids
        if label_of(nid) == "Symbol" and nid in symbol_names and len(split_identifier(symbol_names[nid])) < 2
    ]
    # Two-sided check: not just "no one-token symbol has a vector" but also "every multi-token
    # symbol does" -- catches an over-eager guard that silently drops legitimate candidates too.
    multi_token_symbol_ids = {s["id"] for s in all_symbols if len(split_identifier(s["name"])) >= 2}
    multi_token_missing_embedding = sorted(multi_token_symbol_ids - code_emb_id_set)

    out = {
        "total_synonym_edges": len(rows),
        "entity_code_synonym_edges": len(entity_code_pairs),
        "same_kind_code_synonym_edges (cross-source duplicate artifact of indexing the zip twice)": len(same_kind_pairs),
        "top_30_entity_code_raw_with_duplicates": entity_code_pairs[:30],
        "top_30_entity_code_distinct": entity_code_distinct[:30],
        "distinct_entity_code_pairs": len(entity_code_distinct),
        "top_10_same_kind_for_reference": same_kind_pairs[:10],
        "cross_kind_synonym_edges": len(cross_kind),
        "top_30_cross_kind": cross_kind[:30],
        "code_embeddings_stored": len(code_emb_ids),
        "total_symbols": len(all_symbols),
        "multi_token_symbols": len(multi_token_symbol_ids),
        "one_token_symbols_with_embedding": one_token_with_embedding,
        "multi_token_symbols_missing_embedding": [
            {"id": nid, "name": symbol_names.get(nid, "?")} for nid in multi_token_missing_embedding
        ],
    }
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"total SYNONYM edges: {len(rows)}")
    print(f"entity<->code SYNONYM edges (spike 2's actual scope): {len(entity_code_pairs)}")
    print(f"same-kind code SYNONYM edges (cross-source duplicate artifact): {len(same_kind_pairs)}")
    print(f"one-token symbols with an embedding (should be 0, checked via load_code_embeddings): {len(one_token_with_embedding)}")
    print(f"multi-token symbols missing an embedding (should be 0): {len(multi_token_missing_embedding)}")
    print(f"distinct entity<->code pairs: {len(entity_code_distinct)}")
    print("top 30 DISTINCT entity<->code pairs by score (hand-label these):")
    for p in entity_code_distinct[:30]:
        print(f"  {p['score']:.4f}  {p['a_label']}:{p['a_name']!r} ~ {p['b_label']}:{p['b_name']!r}")
    ctx.close()


if __name__ == "__main__":
    main()
```

`/tmp/hippo-qa1/scripts/04_ask.py` — the five real Ask calls:

```python
"""
QA1 step 4: five real Ask calls through the Python API (ask_service.ask), against the subset
index (src/hippo/hipporag/, src/hippo/codegraph/, README.md). Records seed_symbols, used_code_seeds,
top-5 passage titles, the select pass outcome, timing_ms and the context_block verbatim (Answer
carries it; the /api/ask HTTP response does not yet -- that is WP4a's planned work, still in
flight).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path("/Users/mascott/projects/hippo/.worktrees/qa1")
sys.path.insert(0, str(REPO_ROOT / "src"))

os.environ["HIPPO_DATA_DIR"] = "/tmp/hippo-qa1/data"
os.environ["HIPPO_STORE"] = "ladybug"
os.environ["HIPPO_OPENIE_WORKERS"] = "1"
os.environ["HIPPO_LLM_MODEL"] = "qwen3.8:latest"

from hippo import ask as ask_service  # noqa: E402
from hippo.context import AppContext  # noqa: E402

OUT = Path("/tmp/hippo-qa1/results_ask.json")

TRACEBACK_A = (
    "Traceback (most recent call last):\n"
    '  File "src/hippo/hipporag/retriever.py", line 296, in retrieve\n'
    "    asked = trace.question_prose or question\n"
    "AttributeError: 'NoneType' object has no attribute 'question_prose'"
)

QUESTIONS = [
    ("a_traceback_in_subset", TRACEBACK_A),
    ("b_qualified_graphindex_load", "what does GraphIndex.load do"),
    ("c_where_called_find_anchors", "where is find_anchors called"),
    ("d_prose_readme", "what backends can hippo use"),
    ("e_bare_word_also_symbol", "how long does it take to load a big file"),
]


def main() -> None:
    ctx = AppContext.from_env()
    ctx.ollama.chat_text([{"role": "user", "content": "reply with the single word: ready"}], max_tokens=8)
    results = []
    for key, question in QUESTIONS:
        trace, answer = ask_service.ask(ctx, question, settings=None, access=None)
        record = {
            "key": key,
            "question": question,
            "used_code_seeds": trace.used_code_seeds,
            "used_dpr_fallback": trace.used_dpr_fallback,
            "seed_symbols": [
                {
                    "token": s.token,
                    "how": s.how,
                    "weight": s.weight,
                    "n_matches": s.n_matches,
                    "kept": s.kept,
                    "ambiguous": s.ambiguous,
                    "name": s.name,
                }
                for s in trace.seed_symbols
            ],
            "top5_passages": [
                {"rank": p.rank, "score": p.score, "title": p.title, "source_name": p.source_name}
                for p in trace.passages[:5]
            ],
            "select_ran": bool(trace.select),
            "select": trace.select,
            "paths_count": len(trace.paths),
            "timing_ms": trace.timing_ms,
            "context_block": answer.context_block,
            "answer": answer.answer,
            "thought": answer.thought,
        }
        results.append(record)
        OUT.write_text(json.dumps(results, indent=2, default=str))
        print(f"=== {key} ===")
        print(f"used_code_seeds={trace.used_code_seeds} seed_symbols={len(trace.seed_symbols)} select_ran={bool(trace.select)}")
        print(f"top5: {[p.title for p in trace.passages[:5]]}")
        print(f"context_block chars: {len(answer.context_block)}")
        print()

    ctx.close()


if __name__ == "__main__":
    main()
```

`/tmp/hippo-qa1/scripts/05_inertness.py` — the inertness check:

```python
"""
QA1 step 5: set the four inertness settings via ctx.store.update_settings -- exactly what
PUT /api/settings does, with NO manual graph invalidation, because that is the real production
path a user hits (confirmed empirically: `update_settings` does not bump `graph_version`, and
`code_structural_scale` is read live per `retrieve()` call via `GraphIndex.graph_for_scale`,
which rebuilds+memoises its own igraph view lazily -- see graph_index.py:717). Then re-ask (b)
and (d) and record: the ranking, whether `used_code_seeds`/`context_block`/`timing_ms["paths"]`
switched off, and whether every code-kind top_node's PPR score is exactly 0 (the FIDELITY-checkable
sentence). Restores the defaults afterward.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path("/Users/mascott/projects/hippo/.worktrees/qa1")
sys.path.insert(0, str(REPO_ROOT / "src"))

os.environ["HIPPO_DATA_DIR"] = "/tmp/hippo-qa1/data"
os.environ["HIPPO_STORE"] = "ladybug"
os.environ["HIPPO_OPENIE_WORKERS"] = "1"
os.environ["HIPPO_LLM_MODEL"] = "qwen3.8:latest"

from hippo import ask as ask_service  # noqa: E402
from hippo.context import AppContext  # noqa: E402

OUT = Path("/tmp/hippo-qa1/results_inertness.json")

INERT_SETTINGS = {
    "code_seed_weight": 0.0,
    "code_dense_seeds": 0,
    "code_select": False,
    "code_structural_scale": 0.0,
}

QUESTIONS = [
    ("b_qualified_graphindex_load", "what does GraphIndex.load do"),
    ("d_prose_readme", "what backends can hippo use"),
]


def ranked_titles(trace):
    return [(p.rank, round(p.score, 4), p.title) for p in trace.passages[:10]]


def code_top_node_scores(trace):
    return [(t.kind, t.name, t.score) for t in trace.top_nodes if t.kind in ("symbol", "data")]


def main() -> None:
    ctx = AppContext.from_env()
    ctx.ollama.chat_text([{"role": "user", "content": "reply with the single word: ready"}], max_tokens=8)
    before = ctx.store.get_settings()

    baseline = {}
    for key, q in QUESTIONS:
        trace, _ = ask_service.ask(ctx, q, settings=None, access=None)
        baseline[key] = {
            "ranking": ranked_titles(trace),
            "used_code_seeds": trace.used_code_seeds,
            "timing_ms_keys": sorted(trace.timing_ms.keys()),
            "code_top_node_scores": code_top_node_scores(trace),
        }

    v_before = ctx.store.graph_version()
    print("applying inertness settings (PUT /api/settings equivalent):", INERT_SETTINGS)
    print("graph_version before settings change:", v_before)
    ctx.store.update_settings(INERT_SETTINGS)
    v_after = ctx.store.graph_version()
    print("graph_version after settings change (expected: unchanged):", v_after)

    after = {}
    first_ask_seconds = {}
    for key, q in QUESTIONS:
        t0 = time.time()
        trace, answer = ask_service.ask(ctx, q, settings=None, access=None)
        first_ask_seconds[key] = time.time() - t0
        after[key] = {
            "ranking": ranked_titles(trace),
            "used_code_seeds": trace.used_code_seeds,
            "seed_symbols": len(trace.seed_symbols),
            "context_block_chars": len(answer.context_block),
            "timing_ms_keys": sorted(trace.timing_ms.keys()),
            "code_top_node_scores": code_top_node_scores(trace),
            "select_ran": bool(trace.select),
        }

    # Non-vacuous form: under scale=0 a zero-mass code vertex does not reach top_nodes at all
    # (it is not merely present-with-score-0), so the PASS condition is "baseline saw code-kind
    # top_nodes; after inertness settings, none survive" -- not "the (possibly empty) list we got
    # is all zero".
    baseline_code_top_node_counts = {k: len(v["code_top_node_scores"]) for k, v in baseline.items()}
    after_code_top_node_counts = {k: len(v["code_top_node_scores"]) for k, v in after.items()}
    every_after_count_is_zero = all(n == 0 for n in after_code_top_node_counts.values())
    baseline_saw_any_code_top_nodes = any(n > 0 for n in baseline_code_top_node_counts.values())

    out = {
        "settings_before": {k: before.get(k) for k in INERT_SETTINGS},
        "settings_applied": INERT_SETTINGS,
        "graph_version_before": v_before,
        "graph_version_after": v_after,
        "graph_version_unchanged_by_settings": v_before == v_after,
        "first_ask_after_settings_seconds": first_ask_seconds,
        "baseline": baseline,
        "after_inertness": after,
        "baseline_code_top_node_counts": baseline_code_top_node_counts,
        "after_code_top_node_counts": after_code_top_node_counts,
        "baseline_saw_any_code_top_nodes": baseline_saw_any_code_top_nodes,
        "every_after_count_is_zero": every_after_count_is_zero,
        "inertness_pass": every_after_count_is_zero,  # meaningful only if baseline_saw_any_code_top_nodes
    }
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))

    ctx.store.update_settings({k: before[k] for k in INERT_SETTINGS})
    ctx.close()


if __name__ == "__main__":
    main()
```

`/tmp/hippo-qa1/scripts/06_timings.py` — the two pure-code timings:

```python
"""
QA1 step 6: two pure-code timings, no Ollama needed.
  - extract_code over the FULL src/hippo (as PLAN.md's CI gate 2 specifies), must stay < 5s.
  - GraphIndex.load timing against the subset store this QA run built (spike 3's vector-reload
    cost concern), by forcing a cold reload.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path("/Users/mascott/projects/hippo/.worktrees/qa1")
sys.path.insert(0, str(REPO_ROOT / "src"))

os.environ["HIPPO_DATA_DIR"] = "/tmp/hippo-qa1/data"
os.environ["HIPPO_STORE"] = "ladybug"

from hippo.codegraph import extract_code  # noqa: E402
from hippo.context import AppContext  # noqa: E402
from hippo.hipporag.graph_index import GraphIndex  # noqa: E402
from hippo.ingest import readers, repos  # noqa: E402

OUT = Path("/tmp/hippo-qa1/results_timings.json")


def main() -> None:
    budget = readers.TextBudget(limit=readers.MAX_TEXT_CHARS)
    docs = repos.walk_repo(REPO_ROOT / "src" / "hippo", budget)

    t0 = time.time()
    code = extract_code(docs, "timing-source")
    extract_code_s = time.time() - t0
    print(f"extract_code over src/hippo: {extract_code_s:.3f}s (budget < 5s)  symbols={code.stats().get('symbols')}")

    ctx = AppContext.from_env()
    version = ctx.store.graph_version()
    t0 = time.time()
    loaded = GraphIndex.load(ctx.store, version=version)
    load_s = time.time() - t0
    print(
        f"GraphIndex.load on this memory: {load_s:.3f}s  "
        f"(passages={len(loaded.passages)}, symbols/data vectors included)"
    )

    OUT.write_text(
        json.dumps(
            {
                "extract_code_src_hippo_seconds": extract_code_s,
                "extract_code_under_5s": extract_code_s < 5.0,
                "graph_index_load_seconds": load_s,
                "graph_passages": len(loaded.passages),
            },
            indent=2,
        )
    )
    ctx.close()


if __name__ == "__main__":
    main()
```
