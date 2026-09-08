# WP2i — Chunker, indexer, pipeline integration (the second half of PLAN.md WP2)

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp2i`, branch `wp/wp2i`.
Neo4j test container: name `hippo-neo4j-wp2i`, port **17693**.

`code-graph` now contains WP1 (store methods + `GraphIndex` code vertices) and WP2's pure half
(`src/hippo/codegraph/`, the fixture tree, `expected.json`'s symbol/edge/data sections,
`readers.lang_of`). You wire them together so that indexing a repo or zip writes the code graph.

Your spec is PLAN.md **WP2 sections 2.3, 2.4, 2.5 and 2.6 bullets 2-4 (lines 338-352)**, the
**Test fixture plan (lines 416-482)** minus the git parts (`make_code_checkout`, `git_index` are WP2b's),
S2.7 (three-valued `extract_text`, gotcha 5), S2.10 (Leiden determinism), S2.17 (the golden file and its
regeneration hook), and D13/D15 for what `meta["code"]` records. Evidence: `research/R2-ingest-evals-tests.md`
(pipeline flow, indexer step order, OpenIE call shape, `FakeOllama` call inspection, pinned counts).

## What the spikes found — binding for this WP (`research/S0-spikes.md`, spikes 2 and 3, read them)

**Cross-kind synonyms: do NOT raise the threshold.** Under the real embedder (`nomic-embed-text`) only
20 of 26,400 symbol↔entity pairs reach 0.80, but 8 of those are nonsense (40%), and raising to 0.85 makes
it *worse* (43%) because generic one-word names score highest (`library` ~ "the library" 0.94, `main` ~
"main office" 0.86). **Ship the ≥ 2-split-token rule on the SYMBOL side instead**: a symbol enters the
cross-kind synonym search only when `split_identifier(name)` has ≥ 2 tokens (27% nonsense, zero of the
ten known-good pairs lost; `OrderService` ~ "order service" 0.9368 unaffected). Two scoping rules:
**exempt `DataObject`** (table names are single nouns; the rule would break D9's `table orders` ~
"orders"), and **gate BOTH the query list and the key matrix** — `find_synonyms` gates
`is_meaningful_phrase` on the new ids only (`indexer.py:268`), so a one-token symbol must be absent from
both sides or it still links as a key. Put the rule in one helper with a docstring citing the spike.
The fixture cannot prove the guard: no acme_robotics entity comes within 0.8 of any code name even
under the real embedder, so the regression test must CONSTRUCT the case (a one-token symbol and an
entity whose `FakeOllama` feature-hashed vectors collide — e.g. identical name text — and assert no
synonym is written, while a two-token symbol with the same collision does link).

**Write curve: no change to batching.** But note two facts for `meta["code"]`/docs: a repo the size of
pandas (~34k symbols) exceeds `MAX_CHUNKS = 20_000` after WP2 where its ~15.8k line windows fit today — a
behaviour change on existing corpora; record it in `Source.meta` as `truncated` per D15/2.2c and make the
error message say why. The WP4 docs worker will state it in Known limitations.

## What the previous workers built (read their code, not just this summary)

**WP1 (store + GraphIndex), merged as 240d348.** `src/hippo/store/code.py` holds the vocabulary
(`CODE_BATCH=5000`, `SYMBOL_KINDS`, `DATA_KINDS`, `CODE_EDGE_KINDS`, `SPECIFICITY_KINDS`, `CODE_EDGE_PAIRS`,
the `*_LABELS` tuples), the pure row shapers (`symbol_write_row`, `data_object_write_row`,
`commit_write_row`, `code_edge_write_rows`, `modifies_write_rows`, `refers_to_write_rows`, `node_label`,
`check_edge_kind`, `ordered_pairs`, `grouped_by_labels`) and the Neo4j `CodeQueries` mixin, twinned in
`store/ladybug.py` and `tests/fakes/fake_store.py`. 22 methods on every store: writers `add_symbols`,
`add_data_objects`, `add_commits`, `add_code_edges`, `link_definitions`, `add_modifies`, `add_precedes`,
`add_refers_to`, `set_symbol_communities`; readers `get_symbols`, `get_data_objects`, `get_commits`;
loaders `load_symbols`, `load_data_objects`, `load_commits`, `load_code_edges`, `load_definitions`,
`load_modifies`, `load_precedes`, `load_refers_to`, `load_code_embeddings`; and
`delete_code_nodes_for_source`. Row shapes are the WP1.3 table's, field by field — read the shapers.
Semantics: a node's label comes from `label_of(id)`; an unrecognised prefix is node-not-found (write
nothing, no raise); `add_code_edges` is two statements (MATCH+SET that only RAISES ω, then a
WHERE-NOT-EXISTS create), so re-adding never lowers a weight; edge `kind` is a plain string; writes go in
`CODE_BATCH` batches. `GraphIndex`: vertex order entities → symbols → data → commits → passages LAST,
`passage_position = v - first_passage_vertex`; `Edge.omega`/`code_kinds`, `Edge.weight_at(scale)`;
`specificity` holds the denominator (entity = mentions, symbol/data = in_degree+1 over
`SPECIFICITY_KINDS`, commit = 1, passage = 0); `graph_for_scale(scale)` memoised; `scoped()` carries
omega/code_kinds/boost. All eleven `code_*` settings are declared with help text.
**Landmine:** `analysis/simulate.py` has `SIMULATABLE_SETTINGS` and `INGEST_SETTINGS`, and
`test_analysis_simulate.py` asserts they partition `SETTING_RULES` exactly — any new setting must join one
list. The `Tiny` (`test_graph_index.py`) and `small_graph` (`test_store_graph.py`) fixtures now use
`make_id`-shaped ids. The parity test in `test_store_code.py` goes red if a store method lands on one
backend only. Full handoff in the `backend-developer-1` ledger entry (`horch sessions`).

**WP2 (extractors + fixture), merged as 9ba5e39.** `extract_code(docs, source_id, *, should_stop=None)
-> CodeGraph` in `src/hippo/codegraph/`. Over the fixture: 30 symbols, 12 data objects, 64 edges; over
`src/hippo` 0.20 s. `Symbol` carries the WP1 store row fields PLUS five the store has no columns for:
`params`, `module`, `display`, `header_end`, `statement_lines` — **use `Symbol.row()` / `DataObject.row()`,
not `asdict()`**, to build store rows; you add `embedding`. Passage titles use `Symbol.display`
(`module.qualname`, e.g. `pyapp.orders.OrderService.place`); PLAN 2.5 pins `src/tool.py :: src.tool.lift
(lines 1-2)`. `header_end < line_start` means there is NO header passage (`pyapp/store.py` opens with
`class Base`). `statement_lines` are the body's top-level statement starts — where an oversized passage
may split. **`.sql` files are in `files_parsed` but yield NO symbols**: `graph.parsed(path)` is True and
`graph.by_path(path)` is empty, so the chunker branches on `readers.lang_of(path) == "sql"`, not on
`parsed()`. `DataObject.mentions` is `[(path, line), ...]` for EVERY site naming it (deduped across DDL /
literal / `__tablename__` / `mongoose.model`) and is the only source for S2.5's DEFINED_IN-from-every-
passage; a `.sql` file's tables have no owning symbol, so their DEFINED_IN comes from the `.sql` chunk's
`defines`. `should_stop` returns a PARTIAL graph with `truncated=True` and never raises `openie.Stopped`
(codegraph cannot import it) — the pipeline decides what a truncated graph means. A zip with a root
folder resolves (unique-suffix fallback) but module qualnames/display keep the prefix
(`myrepo-main.pyapp.orders`). `unresolved_calls` counts every call with no edge, builtins included
(~4000 over `src/hippo` is expected). The three budget constants are UPPER_CASE
(`CODE_MAX_FILES`, `CODE_MAX_FILE_BYTES`, `CODE_MAX_SYMBOLS_PER_SOURCE`). `data_access.py` sets the
sqlglot logger to ERROR at import. `tests/conftest.py` already has `CODE_SAMPLE_PATH` and
`code_sample_docs()`. `expected.json` is keyed by `(path, qualname)` / `(kind, qualname)`, never by node
id; `scripts/update_expected.py` rewrites only `symbols`/`data_objects`/`edges` (`--check` fails when
stale) and leaves `definitions`/`refers_to`/`commits`/`modifies` for you — extend it. Two approved
rulings pinned by tests: `cli.main -> OrderService.place` is INVOKES 0.90 `via_import` (not 2.6's 0.50),
and `place -> OrderService.log` is INVOKES 1.00 `same_file` with NO `place -> Base.log` edge. Where PLAN
2.6's prose list and the 2.2b table conflict, the table wins. Pre-existing flake: an intermittent
`BufferError` in the neo4j driver's `close()` teardown in `test_web_auth.py` — not yours. Full handoff in
the `opus-1` ledger entry.

**WP3 phase 1 is on `wp/wp3` (not merged yet)** and added `tests/fakes/code_fixture.py`, which writes
the plan's tree through the store methods; you do not need it, but do not create a file of that name.

## Scope

1. **`hipporag/indexer.py`** — `Chunk.defines: list[str]` and `Chunk.extract_text: str | None` (defaulted;
   positional `Chunk(ordinal, title, text)` unchanged); `index_source(..., *, code: CodeGraph | None = None)`
   with `CodeGraph` imported under `TYPE_CHECKING`; `MIN_OPENIE_DOC_CHARS = 80`; the two OpenIE branches
   exactly as 2.4 states; the new stages `"writing code graph"` (embed `name_text()` per symbol and data
   object, then under `GRAPH_WRITE_LOCK`: `add_symbols`, `add_data_objects`, `add_code_edges`,
   `link_definitions`), `"linking mentions"` (REFERS_TO from prose passages via a local name index built
   from `code.symbols`/`code.data_objects`, ≤ 20 per passage, ω 0.85 backtick/qualified, 0.60 split-token),
   `"communities"` (seeded, relabelled Leiden over the module projection → `set_symbol_communities`);
   `find_synonyms` keys become entity ⊕ code embeddings. `should_stop` is checked between files and
   before each new stage. Commit stages (`add_commits`/`add_modifies`/`add_precedes`) are WP2b's — leave
   a clearly named hook (`code.commits` empty → nothing written) rather than a TODO.
2. **`ingest/chunker.py`** — `chunk_documents(docs, size, overlap, code=None)`; `_chunk_symbols` (module
   header with placeholder lines, class header with method placeholders, one passage per function/method
   titled `path :: qualname (lines a-b)`, oversized bodies split at the walker-recorded top-level statement
   starts into `(part N)`, only part 1 carrying `extract_text`); `.sql` files through `_chunk_code` with
   `defines` set and `extract_text=""`; everything else untouched. Only the code chunker ever sets
   `extract_text`.
3. **`ingest/pipeline.py`** — in `_read_chunk_index` between `read_source` and `chunk_documents`: stage
   `"parsing code"` → `extract_code(docs, source_id)` → `chunk_documents(..., code=code)` →
   `index_source(..., code=code)` → `meta["code"] = code.stats()`.
4. **`tests/conftest.py`** — `CODE_SAMPLE_PATH`, the `code_index` fixture (zip the tree, index through the
   real pipeline with `FakeOllama`, yield `(ctx, source_id)`), and the `--update-expected`
   `pytest_addoption` hook (refused when `CI` is set). `make_code_checkout`/`git_index` are WP2b's.
5. **`expected.json`** gains `definitions` (DEFINED_IN pairs keyed by `(path, qualname)` → passage title)
   and `refers_to` (README passage → symbol/data, ω, token); extend `scripts/update_expected.py` for them.
   The golden test in `test_indexer.py` (S2.17) indexes the fixture through `code_index` and asserts the
   loaded graph equals the file, order-independent, `community` excluded, commits/modifies sections
   ignored while empty.
6. **Tests** — every bullet of 2.6 (2)-(4): `test_ingest_chunker.py` (exact titles for `pyapp/orders.py`,
   placeholders, `defines`/`extract_text` per passage, the 200-line split, `chunk_document` without
   `code=` unchanged); `test_indexer.py` (nine-key counts on all three stores, DEFINED_IN rows, idempotent
   re-run, the OpenIE-policy assertions with the `fake_ollama.calls` system-prompt filter, the S2.7 gate
   count `2 × (prose chunks + code passages with non-empty extract_text)`, synonyms both directions,
   `should_stop` before `"writing code graph"` writes nothing, determinism across two runs with the compared
   fields named); `test_ingest_pipeline.py` (zip of the fixture → exact `meta["code"]`, symbol-titled
   passages, `delete_source` removes symbols; the two pinned titles updated).

## Pinned tests you own (S2.18 / V2.4)

`test_indexer.py:55, 98, 212-222, 238, 317` (the counts dict → nine keys) and
`test_ingest_pipeline.py:138, 205` (chunk titles). Nothing else should move.

## Done when (PLAN.md line 352)

Indexing the fixture is deterministic across two runs, `extract_code` over `src/hippo` is under 5 s,
no NER call contains a function body or `CREATE TABLE`, three stores + lint green. Commit, ledger summary
(files, pinned tests changed, the `code_index` fixture's exact yield and the source_id it uses, the
`meta["code"]` key names), `horch tell orchestrator "[<role>] DONE: wp/wp2i ..."`, close pane.
