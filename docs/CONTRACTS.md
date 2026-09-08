# Module contracts

This is the map of hippo's code and the function signatures each part
exposes. It exists so that people (and the agents that helped build v1) can
work on one folder without reading every other folder.

Style rules for every file:

* Start each module with a short docstring that says, in plain words, what it
  does and why. Write for a tired reader; no jargon without a one-line gloss.
* Small functions, descriptive names, type hints, no metaprogramming.
* Comments explain *why*, not what. Reference the HippoRAG paper/code when a
  choice comes from there.
* `ruff check` and `ruff format` clean (see pyproject.toml).
* Every package has tests under `tests/unit/` (fast, use the fakes) and, where
  it touches the store, the same tests run on LadybugDB, the fake and real Neo4j in CI via the
  `store` fixture (see tests/conftest.py).

## Already written (do not redesign; extend if you must)

```
src/hippo/config.py               Config + load_config()
src/hippo/ollama.py               Ollama(client): chat_json/chat_text/embed/embed_one/ensure_model/missing_models/pull/is_up
src/hippo/prompts.py              every prompt + JSON schema (*_messages(...) builders)
src/hippo/context.py              AppContext(config, store, ollama, jobs); ctx.graph() -> GraphIndex; ctx.graph_for(access) -> the caller's slice
                                  (cached by (graph version, visible source ids)); ctx.invalidate_graph(); ctx.invalidate_scoped()
src/hippo/access.py               Access(rank, user_id, unrestricted) + ACCESS_WHERE (the Cypher predicate on a Source `s`) + access_params;
                                  Principal(user, role, access): .can(cap), .may_manage_source(row), .may_assign_role(role), .as_role(role);
                                  CAPABILITIES, DEFAULT_ROLES (arch-admin 40 > regional-admin 30 > local-admin 20 > local-assistant 10 > individual 0);
                                  hash_password/verify_password (scrypt), new_token, top_role, roles_at_or_below
                                  Rule: a source is visible when its min_rank <= the caller's rank, or they own it; passages follow their
                                  source; an entity/fact is visible when a visible passage mentions/states it. Enforced twice: in every
                                  store read (ACCESS_WHERE) and in memory (GraphIndex.scoped) so PPR never crosses a hidden node.
src/hippo/jobs.py                 Jobs.start(key, fn) -> bool; is_running(key); running_keys(); cancel(key); is_cancelled(key); wait(key, timeout); wait_all()
src/hippo/ask.py                  search(ctx, question, settings=None, access=None) -> Trace; ask(ctx, q, settings=None, access=None) -> (Trace, Answer);
                                  answer_from_trace(ctx, trace, access=None)      # access=None means unrestricted (CLI, open mode, tests)
src/hippo/store/                  Store (Neo4j) and LadybugStore (embedded LadybugDB file), same methods; open_store(config) picks one.
                                  Read store/__init__.py for the graph shape; read each file for the methods.
                                  code.py adds symbols, data objects, commits and their edges; see "the code graph" below
                                  Reads that return sources/passages/entities/facts take `access: Access | None` (memory.py); users.py holds
                                  roles/users: ensure_roles, list_roles, get_role, create_role, update_role (a rank change rewrites min_rank on
                                  its sources), delete_role (refused while in use), count_users, list_users, get_user, get_user_by_username,
                                  get_user_by_token, create_user, update_user, rotate_token, delete_user, check_password, set_source_access
src/hippo/remote.py               RemoteHippo: the CLI's client for a running server (the embedded file is single-process).
justfile                          `just ladybug` / `just neo4j` (docker), `just dev` / `just dev-neo4j` (local), `just test*`; each says its backend.
src/hippo/hipporag/text.py        clean_phrase, entity_id, fact_id, fact_text, make_id, min_max_normalize, is_meaningful_phrase
                                  label_of(node_id) -> "Entity"|"Passage"|"Symbol"|"DataObject"|"Commit", from the id prefix alone
                                  split_identifier("OrderService") -> ["order", "service"]  (camelCase, snake_case, dots, digits)
src/hippo/hipporag/openie.py      extract(ollama, passage_id, text) -> Extraction; extract_many(...)
src/hippo/hipporag/indexer.py     Chunk(ordinal, title, text, defines=[], extract_text=None); index_source(store, ollama, source_id, chunks, *, code=None,
                                  synonymy_threshold, workers, on_progress, should_stop) -> the nine COUNT_KEYS
                                  extract_text is the only gate on OpenIE: None = extract `text` (prose, as always), "" = skip, a string = extract that
                                  code=CodeGraph adds three stages: "writing code graph", "linking mentions" (REFERS_TO), "communities" (Leiden per module)
                                  GRAPH_WRITE_LOCK: held while entities/facts are written and linked, and by anything that ends in remove_orphans
src/hippo/hipporag/graph_index.py GraphIndex.load(store); .scoped(visible_source_ids) -> induced subgraph (recomputed fact counts and passage
                                  counts); .ppr(); .neighbors(); .edge_between(); .graph_with_edits(); Passage; Fact; Edge; EdgeEdit
                                  the code half (CodeNode, DirectedEdge, name_index, out_edges, graph_for_scale, ...) is under "the code graph" below
src/hippo/hipporag/retriever.py   Retriever(index, ollama).retrieve(question, settings, *, fact_filter, force_include, force_exclude, node_boosts, graph) -> Trace
src/hippo/hipporag/answerer.py    answer_question(ollama, question, [(id,title,text)]) -> Answer(answer, thought, raw, passage_ids)
tests/fakes/fake_store.py         FakeStore: in-memory Store with identical methods/row shapes
tests/fakes/fake_ollama.py        FakeOllama: rule-based model behind httpx.MockTransport
tests/conftest.py                 fixtures: store, ollama, fake_ollama, ctx, sample_text
samples/acme_robotics.md          a tiny corpus whose sentences are "X <relation> Y." (the fake extractor understands it)
```

Key data shapes (see the dataclasses in retriever.py): `Trace` has
`fact_candidates` (each: fact_id, triple, score, rank, sent_to_filter, kept, reason, passage_ids),
`filter` (raw_response, kept_triples, replayed), `seed_entities`, `seed_passages`, `top_nodes`,
`passages` (RankedPassage: passage_id, rank, score, dpr_rank, dpr_score, title, source_id, source_name, preview),
`used_dpr_fallback`, `fallback_reason`, `timing_ms`, `settings`, `graph_version`. `Trace.to_dict()` is JSON-safe.

Source rows (`store.get_source`/`list_sources`): id, kind ('text'|'file'|'archive'|'repo'|'sample'), name, status
('queued'|'reading'|'indexing'|'ready'|'failed'), stage (free text), progress_done, progress_total, error, meta (dict),
created_at, updated_at, passages (count), fact_links (count), owner_id, owner_name, access_role_id (None = everyone),
access_role_name ('Everyone' when open), min_rank (the role's rank, copied).
Role rows: id, name, rank, description, capabilities (list), builtin, users (count), sources (count).
User rows: id, username, display_name, role_id, role_name, rank, disabled, created_at, sources (count), token, password_hash
(the web layer strips the last two with auth.public_user before anything leaves the server).

## To write

### `src/hippo/ingest/` — getting text in

```
readers.py   Document(title: str, text: str, path: str, is_code: bool)
             read_file(path: Path, budget=None) -> list[Document]      # .txt .md .markdown .rst .html .htm .pdf .docx .epub, plus any code/text file
             read_zip(path: Path, name: str, budget=None) -> list[Document]   # every supported file inside, ignoring junk dirs
             is_supported(path: Path) -> bool; is_probably_binary(data: bytes) -> bool
             IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target", ".idea", ".vscode", "vendor"}
             MAX_FILE_BYTES = 2_000_000
             TextBudget(limit=MAX_TEXT_CHARS).add(chars, where)   # one per source; raises TooLarge(ReadError) past the limit, which
                                                                 # readers never swallow (pdf pages, epub chapters and zip members count as they go)
             MAX_TEXT_CHARS = 20_000_000; MAX_ZIP_MEMBERS = 5_000; MAX_ZIP_TOTAL_BYTES = 50_000_000 (unpacked); MAX_DOCX_XML_BYTES = 20_000_000
chunker.py   chunk_document(doc: Document, size_chars: int, overlap_chars: int, code: CodeGraph | None = None) -> list[Chunk]
             prose: split on markdown headings first (title becomes "Doc › Heading"), then pack paragraphs into <= size chunks, splitting
                    long paragraphs on sentence ends; overlap = tail of previous chunk (whole sentences). Chunk titles: "Title (part N)" when a
                    section spills into several chunks.
             code: pack lines into <= size chunks, preferring to break at blank lines / lines starting at column 0; title "path (lines a-b)".
             code with a symbol tree (code= is given and code.parsed(path)): one passage per symbol -- module header with a placeholder line per
                    member, class header with one per method, one per function/method, title "path :: module.qualname (lines a-b)", "(part N)" when a
                    body is split at the walker's statement starts. Each carries `defines` (-> DEFINED_IN) and `extract_text`. A .sql file keeps its
                    windows, still defines its tables, and never reaches OpenIE.
             ordinal counts up across the whole document list for a source (chunk_documents(docs, size, overlap, code=None) -> list[Chunk] does that).
repos.py     is_git_url(url) -> bool  (https://, http://, git@, ssh:// forms only)
             clone_repo(url, dest: Path, timeout=300) -> Path   # git clone --depth 1 --single-branch; raise RepoError with a friendly message
             walk_repo(root: Path, budget=None) -> list[Document]   # uses readers; skips IGNORED_DIRS, hidden dirs, files > MAX_FILE_BYTES, binaries
pipeline.py  add_text(ctx, name, text, *, owner_id=None, access_role_id=None) -> source_id   # kind 'text', saves text under data_dir/sources/<id>/
             add_upload(ctx, filename, data: bytes, *, owner_id=None, access_role_id=None) -> source_id    # kind 'file' or 'archive' (.zip)
             both raise ValueError past max_upload_bytes(ctx) (HIPPO_MAX_UPLOAD_BYTES, 50 MB); the same check serves forms, JSON and MCP
             add_repo(ctx, url, *, owner_id=None, access_role_id=None) -> source_id                        # kind 'repo'
             add_sample(ctx, *, owner_id=None, access_role_id=None) -> source_id                           # kind 'sample': samples/acme_robotics.md
             every add_* records who added the source and the lowest role that may see it (None = everyone; see hippo/access.py)
             start_indexing(ctx, source_id) -> bool                 # background job "index:<source_id>": read -> parse code -> chunk -> index_source
                                                                    # status flow: reading -> indexing -> ready | failed (error text kept)
                                                                    # stage/progress_done/progress_total updated through on_progress
                                                                    # meta gets {"chunks": n, "documents": n, "counts": {...}, "code": CodeGraph.stats()}
                                                                    # reads with TextBudget(max_text_chars(ctx)); > MAX_CHUNKS (20,000) passages
                                                                    # or TooLarge from a reader -> 'failed' with "TooLarge: too large: ..."
                                                                    # on failure the passages written so far are cleared; when the job is
                                                                    # cancelled (delete_source) it ends 'failed' / stage 'cancelled';
                                                                    # if the Source row is gone at the end: remove_orphans + bump_graph_version
             delete_source(ctx, source_id) -> None                  # cancels + waits for this source's own job, then (under GRAPH_WRITE_LOCK)
                                                                    # store.delete_source + bump_graph_version + remove files
             reindex(ctx, source_id) -> bool                        # delete passages of this source, then start_indexing again
             reindex_all(ctx) -> int                                # clear every source, then one job per source
             Busy(ValueError)                                       # raised by delete_source / reindex / reindex_all while ANY other index:* job
                                                                    # runs (their remove_orphans would eat the running job's unlinked nodes);
                                                                    # the routes answer 409 with the message
             every add_* also calls start_indexing.
```

### code graph — `codegraph/`, `store/code.py`, and the code half of `graph_index.py`

Source code only. `extract_code` turns a source's `Document`s into a `CodeGraph`; the chunker makes
one passage per symbol out of it, the indexer writes it, and `GraphIndex` loads it back as extra
vertices beside the entities. Every edge carries an `omega` (0-1: how sure the resolver is) and a
`provenance` (the rule that produced it). A prose source never reaches any of this: without a
`CodeGraph` the chunker, the indexer and the index behave exactly as they always have.

```
src/hippo/codegraph/   pure: stdlib, tree-sitter, sqlglot and hipporag.text only. No store, no LLM, no ingest, no
                       import of the chunker, so there is no cycle. Deterministic: the same files give the same graph.
model.py         Symbol, DataObject, CodeEdge(a, b, kind, omega, provenance, extra), FileFacts, FileGraph, CodeGraph
                 symbol_id(source_id, path, qualname); data_id(source_id, kind, qualname); commit_id(source_id, sha)
                     -- prefixed md5s through make_id, so they cannot collide with entity-/fact-/passage- ids
                 name_text(name) -> the text we embed for a symbol or data object (split tokens, then the name)
                 lang_of(name) -> 'python'|'typescript'|'sql'|None. ingest/readers.py holds the same table on the
                     ingest side of the dependency line; codegraph may not import ingest, so the two are kept in step
                     by a test, not by an import.
                 merge_edges(edges) -> one row per (a, b, kind): the best omega wins, the first call_line is kept and
                     extra.call_lines lists the rest
                 CODE_EDGE_KINDS, SYMBOL_KINDS ('module'|'class'|'function'|'method'), DATA_KINDS ('table'|'column'|
                     'collection'|'label'|'rel_type'), SKIP_REASONS, LANG_BY_SUFFIX, ARG_BINDING_MAX_CHARS
                 CODE_MAX_FILES = 5,000; CODE_MAX_FILE_BYTES = 512 KiB (above it a file keeps its line windows);
                     CODE_MAX_SYMBOLS_PER_SOURCE = 50,000 (past it extraction stops and stats()["truncated"] is True)
                     -- safety rails, module constants like MAX_CHUNKS, NOT settings. The history budgets are
                     settings: code_history_depth, code_git_timeout_s, code_history_total_s.
                 CodeGraph.by_path(path) / .parsed(path) / .symbol_by_id(id) / .stats() -> Source.meta["code"]
treesitter.py    get_language(grammar), grammar_for(path, lang), new_parser(grammar) -- one Parser per extract_code
                 call (parsers are not thread-safe and two index jobs can run at once); node helpers text_of,
                 line_of, end_line_of, named_children, field_child, walk_tree.
                 .js/.jsx/.mjs/.cjs all parse with the tsx grammar, so there is no third wheel.
python.py        walk(path, root, source_id) -> FileFacts   # the symbols of one file plus its raw imports, calls,
typescript.py    bases, raises/throws, assignments and string literals, all still unresolved
                 python.py also: module_qualname(path) (repo path, / -> ., extension stripped, __init__ kept),
                 is_test_path(path)
resolve.py       the second pass over every file at once: build_index(files) -> SourceIndex, then resolve_imports,
                 resolve_bases, resolve_overrides (breadth-first MRO, <= 5), resolve_calls, resolve_raises,
                 resolve_data, resolve_tested_by, sql_file_objects. Resolution carries the omega and provenance the
                 matching rule earns. A call it cannot bind emits NO EDGE; it is counted per file into
                 CodeGraph.unresolved_calls instead.
data_access.py   READS/WRITES against the tables, collections and graph labels the repo's own files name:
                 classify_literal(text), sql_tables (sqlglot, errors ignored), cypher_objects, mongo_hit,
                 mongoose_hit, read_sql_file, collect(literals). Cypher is tried BEFORE SQL, because
                 `MERGE (s:Settings ...)` starts with a SQL keyword.
extract.py       extract_code(docs, source_id, *, should_stop=None) -> CodeGraph
                 Each file parses in its own try/except, so one parse failure falls back to today's line windows for
                 that file alone. should_stop() is checked between files, so a big repo stays cancellable.

src/hippo/store/code.py   SYMBOL_KINDS, DATA_KINDS, CODE_EDGE_KINDS, SPECIFICITY_KINDS ('INVOKES','READS','WRITES'),
                 CODE_EDGE_PAIRS, CODE_BATCH = 5000 (rows per UNWIND write), and the label tuples a writer groups its
                 rows by: SYNONYM_LABELS, TUNED_LABELS, BOOSTABLE_LABELS, CODE_NODE_LABELS, DEFINABLE_LABELS,
                 REFERABLE_LABELS
                 node_label(id, allowed) (via text.label_of), check_edge_kind(kind), ordered_pairs(labels),
                 grouped_by_labels(...) -- LadybugDB refuses a CREATE bound by multiple node labels, so every write
                 is issued once per concrete label pair
                 row shapers: symbol_write_row, data_object_write_row, commit_write_row, code_edge_write_rows,
                 modifies_write_rows, refers_to_write_rows, and the read shapers _symbol_row/_data_object_row/_commit_row
                 CodeQueries (the Neo4j mixin; LadybugStore and FakeStore carry the same names and row shapes,
                 and a parity test asserts they do):
                     writers  add_symbols, add_data_objects, add_commits, add_code_edges, link_definitions,
                              add_modifies, add_precedes, add_refers_to, set_symbol_communities
                     readers  get_symbols, get_data_objects, get_commits(ids, access=None) -> rows in the asked
                              order, with source_name and passage_ids, visible only when the source is
                     loaders  load_symbols, load_data_objects, load_commits, load_code_edges, load_definitions,
                              load_modifies, load_precedes, load_refers_to, load_code_embeddings -- unrestricted,
                              they feed GraphIndex.load
                     delete   delete_code_nodes_for_source(source_id): THREE per-label statements, one each for
                              Symbol, DataObject and Commit. Never chain them: `:Symbol:DataObject:Commit` is
                              LadybugDB's OR but Neo4j's AND, so a chained match silently leaks every code node.
                 store.stats() gains symbols, data_objects, code_edges, commits (fifteen keys in all).

src/hippo/hipporag/graph_index.py   the code half of the in-memory index
                 NodeKind is five-valued: ENTITY, PASSAGE, SYMBOL, DATA, COMMIT (CODE_KINDS = the last three)
                 Vertex order is entities, symbols, data objects, commits, PASSAGES LAST, and that is load-bearing:
                 passage_position(v) = v - first_passage_vertex, so a code vertex after the passages would give a
                 negative index and silently serve the wrong passage. num_entities is len(entity_names);
                 first_code_vertex and first_passage_vertex are where each block starts.
                 CodeNode      one vertex -- a symbol, data object or commit -- with whatever its kind carries
                 DirectedEdge(src, dst, kind, omega, provenance, extra)   one relation with its direction kept
                               (named apart from codegraph.model.CodeEdge, which is the same relation before storage)
                 Edge gains omega and code_kinds. Edge.weight_at(scale) is
                     tuned if set else max(fact_count, 1.0 if mention, entity-entity synonym score, omega * scale)
                     and Edge.weight is weight_at(1.0), which is what explain.py and the Graph page read.
                 build_igraph(num_nodes, edges, scale=1.0); graph_for_scale(scale) rebuilds once and memoises per
                     scale on the index; graph_with_edits(edits, scale=1.0) composes a simulation's edge edits with
                     the scale in ONE rebuild, so moving the slider and editing an edge still applies both.
                 code_nodes / code_vertices; code_out and code_in: vertex -> [DirectedEdge]. These are in LOAD ORDER
                     and Neo4j promises none, so sort before you render or pin anything on them.
                 name_index: lowercase name, lowercase qualname and each split token -> node ids. Built once and
                     shared by scoped(), which is safe because every consumer filters its hits through idx_of.
                 specificity: the DIVISOR per vertex, not its reciprocal -- entity: the passages that mention it;
                     symbol and data: in_degree + 1 over INVOKES/READS/WRITES only (MODIFIES excluded, or a function
                     touched by 150 of 200 commits would be crushed); commit: 1; passage: 0, never seeded.
                     entity_passage_count is kept as an alias of it.
                 code_node_by_id, code_node_at, out_edges(v), in_edges(v), defining_passages(v),
                     symbols_defined_in(passage_v), community_of(v), community_name(c), communities
                 scoped() keeps a symbol or data object iff one of its DEFINED_IN passages is visible, and a commit
                     iff its commit passage is; omega and code_kinds are copied onto every surviving edge.

What gets written (the shape the three stores agree on):
    (Symbol|DataObject)-[:CODE_EDGE {kind, omega, provenance, extra}]->(Symbol|DataObject)   directed, one per (a,b,kind)
    (Symbol|DataObject|Commit)-[:DEFINED_IN]->(Passage)         omega 1.0. A data object gets one from EVERY passage
                                                                whose literal names it, not only its declaration site
    (Passage)-[:REFERS_TO {omega, token}]->(Symbol|DataObject)  a prose or commit passage naming a symbol
    (Commit)-[:MODIFIES {omega, hunk}]->(Symbol)    (Commit)-[:PRECEDES]->(Commit)   first-parent, newest to oldest
    SYNONYM widens to (Entity|Symbol|DataObject)^2 and TUNED to (Entity|Passage|Symbol|DataObject)^2
CODE_EDGE kinds: CONTAINS, IMPORTS, INHERITS, OVERRIDES, INVOKES, RAISES, CATCHES, TESTED_BY, READS, WRITES.
PRECEDES is the one relation that does NOT enter igraph -- 200 commits would chain every symbol they touched into
one neighbourhood -- so it exists only as a DirectedEdge, for the history tool.

The rest of the code path is documented in its own block above:
    ingest/readers.py    lang_of(name), beside is_code_name / is_supported_name on the same suffix sets
    ingest/chunker.py    chunk_documents(docs, size, overlap, code=None): one passage per symbol
    hipporag/indexer.py  Chunk.defines and Chunk.extract_text; index_source(..., code=None) and its three code stages
    ingest/pipeline.py   the one insertion point: read_source -> "parsing code" -> chunk_documents -> index_source
```

### `src/hippo/evals/` — asking questions and grading

```
metrics.py         normalize_answer(text) -> str (lowercase, strip punctuation/articles/extra spaces; MRQA style, same as reference)
                   exact_match(expected, actual) -> float; f1(expected, actual) -> float; both accept a list of accepted answers too
                   recall_at_k(gold_ids, ranked_ids, ks=(1, 2, 5, 10, 20)) -> dict["recall@k", float]
                   gold_rank(gold_ids, ranked_ids) -> int | None   # best rank of any gold passage, 1-based
judge.py           Verdict(verdict: 'correct'|'partially_correct'|'incorrect', score: 1.0|0.5|0.0, reason: str)
                   judge(ollama, question, expected, actual) -> Verdict   # prompts.judge_messages; on OllamaError -> incorrect with reason
question_maker.py  generate_questions(ctx, source_id, *, per_passage=1, max_single=10, max_multihop=5, name=None, set_id=None, access=None) -> set_id
                   - access: the caller's slice; passages and entity pairs come from ctx.graph_for(access)
                   - creates the QuestionSet first (origin 'generated', status 'generating'), fills it, sets status 'ready'
                     (update_question_set for stage/progress; on failure status 'failed' + error)
                   - single-hop: pick up to max_single passages spread evenly across the source; prompts.question_gen_messages
                   - multi-hop: find pairs of this source's passages that MENTION the same entity (use ctx.graph(): passage_vertices,
                     edges/neighbors, Edge.mention) preferring entities mentioned by exactly 2-3 passages; prompts.multihop_gen_messages;
                     skip empty questions; kind 'multihop'; gold_passage_ids = both passages
                   - each question row: {text, expected_answer, gold_passage_ids, kind, notes}
                   start_generation_job(ctx, source_id, **kw) -> set_id   # creates the set, then Jobs key "generate:<set_id>"
runner.py          start_run(ctx, set_id, name=None, settings=None, access=None) -> run_id   # Jobs key "run:<run_id>"; the run searches and
                                                                             # answers on the starter's slice of the memory (hippo/access.py)
                   run_question(ctx, question_row, settings, access=None) -> dict   # search -> answer_from_trace -> judge -> metrics; returns the
                                                                             # dict that store.add_result wants (answer, thought, verdict,
                                                                             # judge_score, judge_reason, exact_match, f1, recall, gold_rank, used_dpr_fallback,
                                                                             # latency_ms, trace(dict), error)
                   summarize(results: list[dict]) -> dict   # accuracy (mean judge_score), correct/partial/incorrect counts, exact_match,
                                                            # f1, recall@k means, mean_gold_rank, gold_in_top5 rate, dpr_fallbacks, mean_latency_ms
                   the run node: progress_done per question; status running -> done | failed; summary_json at the end; settings_json = the
                   settings used (store.get_settings() merged with overrides). Runs are "history": never modified after done.
```

### `src/hippo/analysis/` — digging into one question

```
explain.py     explain(index: GraphIndex, trace: Trace, *, top_passages=10, graph=None) -> Explanation   # graph: an edited igraph from a simulation
               Explanation.passages: for each of the top passages: passage_id, title, rank, score, dpr_rank,
                   linked_seeds: [{entity_id, name, seed_weight, edge_weight}]  (seed entities this passage MENTIONS),
                   path: [names] shortest path from the strongest seed to this passage when not directly linked (cutoff 3, by igraph),
                   path_ids: the same path as node ids (what the Graph page highlights),
                   why: one plain sentence ("Directly mentions seed 'boulder' (weight 0.50) and 'acme robotics'." / "Reached in 2 hops via ...")
               Explanation.subgraph: {"nodes": [{id, label, kind, score, is_seed, seed_weight, rank}], "edges": [{source, target, weight, kinds}]}
                   nodes = seed entities + top_nodes + top passages; edges = every graph edge among those nodes (index.edge_between)
               Explanation.facts: the trace's fact_candidates with passage titles resolved, for display
simulate.py    Overrides(settings: dict = {}, force_include: list[str] = [], force_exclude: list[str] = [], node_boosts: dict[str, float] = {},
                         edge_edits: list[dict(a, b, weight)] = [], rerun_filter: bool = False, reanswer: bool = False)
               Overrides.from_dict(d); Overrides.to_ops() -> list[op dicts]  (settings -> set_setting; node_boosts -> set_node_boost;
                         edge_edits -> set_edge_weight)   # force_include/exclude are per-question and never become graph ops
               simulate(ctx, question, overrides, baseline: Trace | None, access=None) -> Simulation(trace, answer: Answer | None, diff, baseline)
                   - runs on ctx.graph_for(access): a simulation never leaves the caller's slice of the graph
                   - settings = baseline.settings (or store settings) merged with overrides.settings
                   - fact filter: replay baseline.filter["kept_triples"] unless rerun_filter (then the LLM runs again)
                   - graph = index.graph_with_edits([EdgeEdit(...)]) when edge_edits
                   - answer only when overrides.reanswer (costs an LLM call)
               diff_traces(before: Trace | None, after) -> {"passages": [{passage_id, title, before_rank, after_rank, change}], "seeds_before": [...],
                   "seeds_after": [...], "fallback_before", "fallback_after", "kept_facts_before", "kept_facts_after"}
                   passages listed = union of top 10 of both, sorted by after_rank (missing rank -> None, shown as "–")
changesets.py  save(ctx, name, ops, from_result_id=None, note="") -> changeset_id
               apply(ctx, changeset_id) -> dict   # runs each op through the store, bumps graph version, marks applied; returns what changed
               describe(ctx, ops) -> list[str]   # "Set damping to 0.7", "Boost 'boulder' x1.5", "Link 'usa' ~ 'united states' (0.9)", ...
                                                 # resolve entity/passage names with store.get_entities / get_passages
               VALID_OPS = {"set_setting", "set_edge_weight", "add_synonym", "set_node_boost"}; validate(ops) raises ValueError on junk
```

### `src/hippo/web/` — the UI (FastAPI + Jinja2 + HTMX + vanilla JS; Cytoscape for the graph picture)

```
security.py    HostAndOriginGuard: refuses foreign Host headers and cross-site writes (CSRF); adhoc.py: the small cache of ad-hoc analyses
               (each entry remembers its owner; recall_adhoc(key, owner) answers only them)
auth.py        AuthGate (ASGI middleware): resolves the Principal (bearer token, then the signed `hippo_session` cookie) and puts it on
               request.state.principal; open mode (no users) = everyone acts as the top role. Strangers get 401 on /api and /mcp,
               303 -> /login on pages, 401 + HX-Redirect on htmx requests. principal_of(request); require(request, cap) -> 403;
               require_capability(cap) (a router dependency); principal_from_bearer(ctx, token) (used by the MCP server);
               sign_session/read_session (HMAC, secret kept as Settings meta "session_secret"); public_user(row) strips secrets.
    GET/POST /login, POST /logout, GET /account, POST /account/password, POST /account/token, GET /api/me
app.py         create_app(ctx: AppContext | None = None) -> FastAPI   # ctx default: AppContext.from_env(); on startup: store.ensure_schema(),
               kick off "pull-models" job if Ollama is up and models are missing (Ollama.missing_models / ensure_model), mount /static,
               include routers, mount MCP at /mcp (hippo.mcp_server.mount); a 403 on a page renders templates/forbidden.html
Every page extends templates/base.html (store/Ollama status + model pull progress in the header, who is signed in, sign out;
nav items for Evals/Changesets/Users appear only for roles that may use them). Routes are
grouped by feature, one file each, and every file has a `router` (HTML pages and the HTMX form posts / partials
they use) and, where it has JSON endpoints, an `api` router. app.py includes them in this order:
auth.router, users.router, users.api, graph.router, graph.api, pages.router, sources.router, sources.api, evals.router, evals.api,
analyze.router, analyze.api, api.router. render() passes the principal to every template as `me`.
The /api prefix is built per file: api.py's router has prefix="/api", sources.py's api has prefix="/api/sources",
and evals.py / analyze.py spell "/api/..." in every path; that is why the same prefix shows up in four modules.

routes/users.py   Users & roles (the access ladder)
    GET  /users                        needs manage_users or manage_roles. The ladder (every role top first: rank, users, sources at
                                       that tier, what it sees cumulatively, "see the graph as this tier"), the users table (change
                                       role / disable / reset password / new token / remove, only for users ranked below the caller,
                                       or peers when the caller is at the very top), and the roles editor (name, rank, description,
                                       capability checkboxes, add, delete when unused). Open mode shows a callout and the
                                       "create the first user" form (forced to the top role; that browser is signed in as them).
    POST /users, POST /users/{id}, POST /roles, POST /roles/{id}      the page's forms (action=save|delete|token)
    api: GET/POST /api/users, PATCH/DELETE /api/users/{id}, POST /api/users/{id}/token, GET/POST /api/roles, PATCH/DELETE /api/roles/{id}
routes/graph.py   the Graph page (3D, vendor/3d-force-graph.min.js, static/graph.js)
    GET  /graph?as_role=&q=&source=    the whole visible graph in 3D; "View as" a role (manage_users/manage_roles, tiers at or below yours)
    GET  /api/graph/full               nodes [{id,label,kind,degree,tier,tier_rank,source_id?,passage_count?}] + edges [{source,target,weight,kinds}]
                                       after filters q (name substring + one hop of context), source, kind, min_weight; capped by degree
                                       (limit, default 2500); plus totals, tiers and the viewer
    POST /api/graph/light-up {question, settings?, as_role?, top_passages?}   runs ask.search on the viewer's slice and returns seeds,
                                       kept_facts, top_nodes (PPR scores), ranked passages with "why", paths (seed -> passage node ids)
                                       and the lit subgraph, so the page can animate the spread
    GET  /api/graph/node/{id}          side-panel details: passage text/source/facts, or entity facts/passages/boost; neighbours
routes/pages.py   the pages that fit nowhere else
    GET  /partials/status              header partial: Neo4j/Ollama/model-pull status, polled by every page
    GET  /ask, POST /ask               Ask: a question box; the POST runs the search + answer (on the caller's slice) and renders the
                                       same page with the answer, thought, top passages with scores, kept facts, seeds; link "Analyze
                                       this question"; the page says "searching N of M sources visible to you as <role>"
    GET  /settings, POST /settings     Ollama status (url, models installed vs required, pull progress, "Pull now"), Neo4j status +
                                       stats, retrieval settings form (the DEFAULT_SETTINGS keys with one-line explanations),
                                       embed model warning; the POST (edit_graph) saves the settings and renders the same page
routes/sources.py  the Library (everything scoped to the caller; adding needs add_sources; delete/reindex/reclassify need
                   ownership or manage_sources; a source may only be restricted to a tier at or below the caller's own)
    GET  /                             sources table (name, kind, status+stage+progress, passages, facts, "visible to" with an inline
                                       tier picker for sources the caller may manage, owner, created); upload forms (file, zip, paste
                                       text, git URL, "Load the sample"), each with a "Visible to" picker defaulting to the caller's tier
    POST /sources/{id}/access          the tier pickers post here (visibility=<role id>|everyone, back=<path>)
    GET  /partials/sources             the sources table, polled while something is indexing (HTMX)
    GET  /sources/{id}                 Source detail: meta, progress, passages (paged) with the entities/triples the LLM extracted,
                                       "Make sample questions" button (-> generation job), question sets about this source, "Reindex", "Delete"
    GET  /partials/sources/{id}/status the progress block of the source page, polled while it is busy (HTMX)
    POST /sources/upload | /sources/text | /sources/repo | /sources/sample     the Library forms; redirect back to / (with ?error=)
    api (prefix /api/sources):
    GET    /api/sources                list every source (same rows as store.list_sources)
    POST   /api/sources/text {name, text} | /api/sources/upload (multipart file) | /api/sources/repo {url} | /api/sources/sample
                                       -> {source_id}; 400 with {error} when refused (unsupported type, empty, too big)
    POST   /api/sources/reindex-all    -> {started: n}
    GET    /api/sources/{id}           status/progress JSON for polling (404 when hidden from the caller)
    PUT    /api/sources/{id}/access {role_id|null|"everyone"}   change who may see it -> the source row
    DELETE /api/sources/{id}           -> {deleted}; 409 with {error} while another source is being indexed (pipeline.Busy)
    POST   /api/sources/{id}/reindex   -> {started: bool}; 409 as above
routes/evals.py    question sets and runs (every route needs run_evals)
    GET  /evals                        Question sets (with counts, origin, status) + create set form (name, paste "question | answer"
                                       lines, or JSON) + run history table (all runs: name, set, date, status/progress, accuracy, EM, F1,
                                       recall@5, gold in top5)
    GET  /partials/evals/tables        the two tables of /evals, polled while a run or a generation is going (HTMX)
    GET  /evals/sets/{id}              One set: questions (editable: add/delete), "Run this set" button (name), runs of this set,
                                       past results per question
    GET  /evals/runs/{id}              One run: summary cards, per-question table (question, expected, answer, verdict, EM, F1, gold rank,
                                       fallback?, latency); each row links to /analyze/{result_id}; "Compare with" dropdown of other runs
    GET  /partials/runs/{id}           the body of the run page, polled while the run is going (HTMX)
    POST /evals/sets | /evals/sets/{id}/questions | /evals/sets/{id}/run     the forms of those pages
    api:
    GET/POST /api/evals/sets           list sets; create {name, questions:[{text, expected_answer}]} -> {set_id}
    GET/DELETE /api/evals/sets/{id}    one set with its questions; delete it (and its runs)
    POST   /api/evals/sets/{id}/questions ; DELETE /api/evals/questions/{id}
    POST   /api/sources/{id}/generate-questions {max_single, max_multihop} -> {set_id}; 409 while that source is still indexing
    POST   /api/evals/sets/{id}/run {name, settings?} -> {run_id}
    GET    /api/evals/runs             every run (history)
    GET/DELETE /api/evals/runs/{id}    one run with its summary and progress; delete it
routes/analyze.py  the deep dive and changesets (explanations and simulations run on the caller's slice; stored results need
                   run_evals; changesets need edit_graph)
    GET  /analyze?question=&key=       Analyze an ad-hoc question: `key` names an analysis cached by the Ask page / POST /analyze
                                       (the last ADHOC_LIMIT, until restart); an expired key shows a 404 page with "analyze it again"
    POST /analyze                      run search + answer for a question typed now, cache it, redirect to GET /analyze?key=
    GET  /analyze/{result_id}          the same page for one stored eval result (see below)
    GET  /changesets                   List + detail (ops described in words), Apply / Delete buttons
    api:
    POST   /api/simulate {question, result_id?, overrides} -> {trace, diff, answer?, explanation}
    GET/POST /api/changesets           list; save {name, ops, from_result_id?, note?} -> {changeset_id}
    POST   /api/changesets/{id}/apply ; DELETE /api/changesets/{id}
routes/api.py      (router prefix /api) everything about the whole memory rather than one feature
    GET  /api/status                   {store, store_backend, store_location, neo4j (alias of store), ollama, models, jobs, stats}
    GET/PUT /api/settings              the retrieval settings
    POST /api/models/pull              start the model download job
    POST /api/ask {question} -> {answer, thought, trace}
    POST /api/search {question} -> {trace}
    GET  /api/entities?q=              search entities by name, for the boost / edge-edit pickers
    GET  /api/graph/neighborhood?node_id=&depth=1     small subgraph JSON for the graph picture
Mounted, not routes: /static (files), /mcp (the MCP server), /api/docs (FastAPI's own docs).
The Analyze page shows, top to bottom:
    1. the question, expected answer (if any), the answer given, judge verdict/reason, metrics; "History" of this question across runs
    2. "What the search did": a step-by-step story: candidates (table: rank, triple, score, sent?, kept?, reason), the filter's raw reply,
       seed entities (name, weight, fact score sum, passage count, boost, from which facts), seed passages, fallback notice if any
    3. the graph picture (Cytoscape): seeds highlighted, passages as squares, gold passage(s) outlined, node size ~ PPR score; click a node
       to see its neighbours/edges (weights, kinds)
    4. ranked passages with the explanation sentence ("why") and rank/score/DPR rank; gold ones marked
    5. "Tweak & simulate" panel: sliders/inputs for linking_top_k, passage_node_weight, damping, node_specificity; checkboxes on each
       candidate fact (force in/out); entity boost inputs on seeds (+ entity search to boost any entity); edge edits (pick two nodes,
       set weight; a new entity-entity edge behaves like a synonym link, and Overrides.to_ops emits set_edge_weight for it: the
       add_synonym op is only reachable by hand-writing ops to POST /api/changesets); toggles "re-run the LLM filter" and
       "re-generate the answer"; "Simulate" button (JS -> POST
       /api/simulate) renders the diff table (before rank -> after rank with arrows), new seeds, new answer; "Save as changeset" button
       (name + note) -> POST /api/changesets with Overrides.to_ops(); note under it: fact in/out toggles are per-question and not saved.
templates/     base.html, library.html, source.html, ask.html, evals.html, eval_set.html, eval_run.html, analyze.html, changesets.html,
               settings.html, login.html, account.html, users.html, graph.html, forbidden.html, partials/ (source_row.html, run_row.html, ...)
static/        app.css (one clean stylesheet, system fonts, light theme, responsive; no framework), app.js (small helpers: fetch JSON,
               toasts), analyze.js (simulate panel + cytoscape), graph.js (the 3D graph: filters, light-up animation, side panel),
               vendor/ (htmx.min.js, cytoscape.min.js, 3d-force-graph.min.js with their LICENSE files)
```

### `src/hippo/mcp_server.py` and `src/hippo/cli.py`

```
mcp_server.py  build_server(ctx) -> MCPServer (mcp>=2: from mcp.server.mcpserver import MCPServer)
               caller(ctx, mcp_ctx) -> Principal: from `Authorization: Bearer` (HTTP, via Context.headers) or HIPPO_TOKEN (stdio);
                      ToolError "sign in required" when users exist and no valid token came; open mode = everything
               tools (each takes an injected `mcp_ctx: Context`, hidden from the schema):
                      hippo_search(question, top_k=5) -> passages [{title, source, text, score, rank}] + kept facts (caller's slice)
                      hippo_ask(question) -> {answer, thought, sources:[...]}
                      hippo_remember(name, text, visibility=None) -> {source_id, visible_to} (needs add_sources; owner = caller;
                          visibility = a role id at or below the caller's tier, or "everyone"; default the caller's own tier)
                      hippo_sources() -> the sources the caller may see, with visible_to and owner
                      hippo_whoami() -> {open_mode, user, role, can, sources_visible, sources_total, ladder, visibility_you_may_use}
               mount(app: FastAPI, ctx)   # streamable HTTP at /mcp, stateless_http=True; DNS-rebinding protection on, hosts from config.allowed_hosts (HIPPO_ALLOWED_HOSTS)
                                          # (it runs inside docker; users connect at http://localhost:8000/mcp); wire session_manager.run()
                                          # into the FastAPI lifespan
               run_stdio(ctx)             # for `hippo mcp`
cli.py         main(argv=None): subcommands  serve (uvicorn), mcp (stdio), pull-models, index <path-or-git-url> [--name], ask "<question>",
               sources, settings, users, user add|token|role|remove. Uses AppContext.from_env(); talks to Neo4j directly, so it is not
               gated (it is how the first admin is created from `docker exec`).
```

### Docker, CI, docs

```
Dockerfile               python:3.12-slim, git installed (for repo cloning), pip install ., runs `hippo serve`
docker-compose.yml       services: neo4j (neo4j:5.26-community, ports 127.0.0.1:7474/7687, NEO4J_AUTH=neo4j/${NEO4J_PASSWORD:-hippo-password},
                         volume, healthcheck, APOC not needed), app (build ., port ${HIPPO_BIND:-127.0.0.1}:8000, depends_on neo4j healthy,
                         env for NEO4J_*/OLLAMA_URL/HIPPO_*, volume ./data:/app/data, extra_hosts host.docker.internal:host-gateway),
                         ollama (image ollama/ollama, profile "ollama", port 127.0.0.1:11434, volume) — only started when the host has no Ollama
                         every port is loopback-only: hippo has no login and Ollama no password
hippo (bash launcher)    ./hippo up | down | logs | pull-models | test ; `up` writes a random NEO4J_PASSWORD into .env on the first run
                         (keeps the default when a neo4j_data volume already exists), checks host Ollama at :11434 -> sets OLLAMA_URL to
                         http://host.docker.internal:11434, else starts with --profile ollama; prints the URLs and the password at the end
.env.example             every env var with a comment
.github/workflows/ci.yml lint (ruff) + unit tests with fakes + the same tests against a neo4j:5 service container (NEO4J_URI set)
README.md                the ELI5 guide (what/why, 3-step quick start, a tour of the pages, how HippoRAG works in plain words with a
                         diagram, MCP setup for Claude Code/Desktop/Cursor, configuration table, running without docker, tests, fidelity notes)
docs/FIDELITY.md         where we match the reference exactly and where we adapted (with reasons)
docs/MCP.md              connecting clients
```
