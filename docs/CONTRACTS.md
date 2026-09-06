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
  it touches the store, the same tests run against real Neo4j in CI via the
  `store` fixture (see tests/conftest.py).

## Already written (do not redesign; extend if you must)

```
src/hippo/config.py               Config + load_config()
src/hippo/ollama.py               Ollama(client): chat_json/chat_text/embed/embed_one/ensure_model/missing_models/pull/is_up
src/hippo/prompts.py              every prompt + JSON schema (*_messages(...) builders)
src/hippo/context.py              AppContext(config, store, ollama, jobs); ctx.graph() -> GraphIndex; ctx.invalidate_graph()
src/hippo/jobs.py                 Jobs.start(key, fn) -> bool; is_running(key); running_keys(); wait_all()
src/hippo/ask.py                  search(ctx, question, settings=None) -> Trace; ask(ctx, q) -> (Trace, Answer); answer_from_trace(ctx, trace)
src/hippo/store/                  Store (Neo4j). Read store/__init__.py for the graph shape; read each file for the methods.
src/hippo/hipporag/text.py        clean_phrase, entity_id, fact_id, fact_text, make_id, min_max_normalize, is_meaningful_phrase
src/hippo/hipporag/openie.py      extract(ollama, passage_id, text) -> Extraction; extract_many(...)
src/hippo/hipporag/indexer.py     Chunk(ordinal, title, text); index_source(store, ollama, source_id, chunks, *, synonymy_threshold, workers, on_progress)
src/hippo/hipporag/graph_index.py GraphIndex.load(store); .ppr(); .neighbors(); .edge_between(); .graph_with_edits(); Passage; Fact; Edge; EdgeEdit
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
created_at, updated_at, passages (count), fact_links (count).

## To write

### `src/hippo/ingest/` — getting text in

```
readers.py   Document(title: str, text: str, path: str, is_code: bool)
             read_file(path: Path) -> list[Document]      # .txt .md .markdown .rst .html .htm .pdf .docx .epub, plus any code/text file
             read_zip(path: Path, name: str) -> list[Document]   # every supported file inside, ignoring junk dirs
             is_supported(path: Path) -> bool; is_probably_binary(data: bytes) -> bool
             IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target", ".idea", ".vscode", "vendor"}
             MAX_FILE_BYTES = 2_000_000
chunker.py   chunk_document(doc: Document, size_chars: int, overlap_chars: int) -> list[Chunk]
             prose: split on markdown headings first (title becomes "Doc › Heading"), then pack paragraphs into <= size chunks, splitting
                    long paragraphs on sentence ends; overlap = tail of previous chunk (whole sentences). Chunk titles: "Title (part N)" when a
                    section spills into several chunks.
             code: pack lines into <= size chunks, preferring to break at blank lines / lines starting at column 0; title "path (lines a-b)".
             ordinal counts up across the whole document list for a source (chunk_documents(docs, size, overlap) -> list[Chunk] does that).
repos.py     is_git_url(url) -> bool  (https://, http://, git@, ssh:// forms only)
             clone_repo(url, dest: Path, timeout=300) -> Path   # git clone --depth 1 --single-branch; raise RepoError with a friendly message
             walk_repo(root: Path) -> list[Document]          # uses readers; skips IGNORED_DIRS, hidden dirs, files > MAX_FILE_BYTES, binaries
pipeline.py  add_text(ctx, name, text) -> source_id                 # kind 'text', saves text under data_dir/sources/<id>/
             add_upload(ctx, filename, data: bytes) -> source_id    # kind 'file' or 'archive' (.zip); saves the file under data_dir/sources/<id>/
             add_repo(ctx, url) -> source_id                        # kind 'repo'
             add_sample(ctx) -> source_id                           # kind 'sample': samples/acme_robotics.md
             start_indexing(ctx, source_id) -> bool                 # background job "index:<source_id>": read -> chunk -> index_source
                                                                    # status flow: reading -> indexing -> ready | failed (error text kept)
                                                                    # stage/progress_done/progress_total updated through on_progress
                                                                    # meta gets {"chunks": n, "documents": n, "counts": {...}}
             delete_source(ctx, source_id) -> None                  # store.delete_source + bump_graph_version + remove files
             reindex(ctx, source_id) -> bool                        # delete passages of this source, then start_indexing again
             every add_* also calls start_indexing.
```

### `src/hippo/evals/` — asking questions and grading

```
metrics.py         normalize_answer(text) -> str (lowercase, strip punctuation/articles/extra spaces; MRQA style, same as reference)
                   exact_match(expected, actual) -> float; f1(expected, actual) -> float; both accept a list of accepted answers too
                   recall_at_k(gold_ids, ranked_ids, ks=(1, 2, 5, 10, 20)) -> dict["recall@k", float]
                   gold_rank(gold_ids, ranked_ids) -> int | None   # best rank of any gold passage, 1-based
judge.py           Verdict(verdict: 'correct'|'partially_correct'|'incorrect', score: 1.0|0.5|0.0, reason: str)
                   judge(ollama, question, expected, actual) -> Verdict   # prompts.judge_messages; on OllamaError -> incorrect with reason
question_maker.py  generate_questions(ctx, source_id, *, per_passage=1, max_single=10, max_multihop=5, name=None, set_id=None) -> set_id
                   - creates the QuestionSet first (origin 'generated', status 'generating'), fills it, sets status 'ready'
                     (update_question_set for stage/progress; on failure status 'failed' + error)
                   - single-hop: pick up to max_single passages spread evenly across the source; prompts.question_gen_messages
                   - multi-hop: find pairs of this source's passages that MENTION the same entity (use ctx.graph(): passage_vertices,
                     edges/neighbors, Edge.mention) preferring entities mentioned by exactly 2-3 passages; prompts.multihop_gen_messages;
                     skip empty questions; kind 'multihop'; gold_passage_ids = both passages
                   - each question row: {text, expected_answer, gold_passage_ids, kind, notes}
                   start_generation_job(ctx, source_id, **kw) -> set_id   # creates the set, then Jobs key "generate:<set_id>"
runner.py          start_run(ctx, set_id, name=None, settings=None) -> run_id   # Jobs key "run:<run_id>"
                   run_question(ctx, question_row, settings) -> dict          # search -> answer_from_trace -> judge -> metrics; returns the
                                                                             # dict that store.add_result wants (answer, thought, verdict,
                                                                             # judge_score, judge_reason, exact_match, f1, recall, gold_rank,
                                                                             # latency_ms, trace(dict), error)
                   summarize(results: list[dict]) -> dict   # accuracy (mean judge_score), correct/partial/incorrect counts, exact_match,
                                                            # f1, recall@k means, mean_gold_rank, gold_in_top5 rate, dpr_fallbacks, mean_latency_ms
                   the run node: progress_done per question; status running -> done | failed; summary_json at the end; settings_json = the
                   settings used (store.get_settings() merged with overrides). Runs are "history": never modified after done.
```

### `src/hippo/analysis/` — digging into one question

```
explain.py     explain(index: GraphIndex, trace: Trace, *, top_passages=10) -> Explanation
               Explanation.passages: for each of the top passages: passage_id, title, rank, score, dpr_rank,
                   linked_seeds: [{entity_id, name, seed_weight, edge_weight}]  (seed entities this passage MENTIONS),
                   path: [names] shortest path from the strongest seed to this passage when not directly linked (cutoff 3, by igraph),
                   why: one plain sentence ("Directly mentions seed 'boulder' (weight 0.50) and 'acme robotics'." / "Reached in 2 hops via ...")
               Explanation.subgraph: {"nodes": [{id, label, kind, score, is_seed, seed_weight, rank}], "edges": [{source, target, weight, kinds}]}
                   nodes = seed entities + top_nodes + top passages; edges = every graph edge among those nodes (index.edge_between)
               Explanation.facts: the trace's fact_candidates with passage titles resolved, for display
simulate.py    Overrides(settings: dict = {}, force_include: list[str] = [], force_exclude: list[str] = [], node_boosts: dict[str, float] = {},
                         edge_edits: list[dict(a, b, weight)] = [], rerun_filter: bool = False, reanswer: bool = False)
               Overrides.from_dict(d); Overrides.to_ops() -> list[op dicts]  (settings -> set_setting; node_boosts -> set_node_boost;
                         edge_edits -> set_edge_weight)   # force_include/exclude are per-question and never become graph ops
               simulate(ctx, question, overrides, baseline: Trace | None) -> Simulation(trace, answer: Answer | None, diff)
                   - settings = baseline.settings (or store settings) merged with overrides.settings
                   - fact filter: replay baseline.filter["kept_triples"] unless rerun_filter (then the LLM runs again)
                   - graph = index.graph_with_edits([EdgeEdit(...)]) when edge_edits
                   - answer only when overrides.reanswer (costs an LLM call)
               diff_traces(before, after) -> {"passages": [{passage_id, title, before_rank, after_rank, change}], "seeds_before": [...],
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
app.py         create_app(ctx: AppContext | None = None) -> FastAPI   # ctx default: AppContext.from_env(); on startup: store.ensure_schema(),
               kick off "pull-models" job if Ollama is up and models are missing (Ollama.missing_models / ensure_model), mount /static,
               include routers, mount MCP at /mcp (hippo.mcp_server.mount_mcp)
routes/pages.py   HTML pages (all extend templates/base.html, which shows Neo4j/Ollama status + model pull progress in the header)
    GET /                          Library: sources table (name, kind, status+stage+progress, passages, facts, created); upload forms
                                   (file, zip, paste text, git URL, "Load the sample"); delete buttons; auto-refresh rows while indexing (HTMX poll)
    GET /sources/{id}              Source detail: meta, progress, passages (paged) with the entities/triples the LLM extracted,
                                   "Make sample questions" button (-> generation job), question sets about this source, "Reindex", "Delete"
    GET /ask                       Ask: a question box; result shows answer, thought, top passages with scores, kept facts, seeds;
                                   link "Analyze this question" (-> /analyze?question=...)
    GET /evals                     Question sets (with counts, origin, status) + create set form (name, paste "question | answer" lines, or JSON)
                                   + run history table (all runs: name, set, date, status/progress, accuracy, EM, F1, recall@5, gold in top5)
    GET /evals/sets/{id}           One set: questions (editable: add/delete), "Run this set" button (name), runs of this set, past results per question
    GET /evals/runs/{id}           One run: summary cards, per-question table (question, expected, answer, verdict, EM, F1, gold rank, fallback?,
                                   latency); each row links to /analyze/{result_id}; "Compare with" dropdown of other runs of the same set
    GET /analyze/{result_id}       The deep dive for one stored result (see below)
    GET /analyze?question=...      Same page for an ad-hoc question (runs search now; no expected answer)
    GET /changesets                List + detail (ops described in words), Apply / Delete buttons
    GET /settings                  Ollama status (url, models installed vs required, pull progress, "Pull now"), Neo4j status + stats,
                                   retrieval settings form (the DEFAULT_SETTINGS keys with one-line explanations), embed model warning
routes/api.py     JSON endpoints used by the pages' JS and by curl:
    POST /api/sources/text | /api/sources/upload | /api/sources/repo | /api/sources/sample ; DELETE /api/sources/{id}; POST /api/sources/{id}/reindex
    GET  /api/sources/{id} (status/progress JSON for polling)
    POST /api/ask {question} -> {answer, thought, trace}
    POST /api/search {question} -> {trace}
    POST /api/evals/sets {name, questions:[{text, expected_answer}]} ; DELETE /api/evals/sets/{id}; POST /api/evals/sets/{id}/questions ; DELETE /api/evals/questions/{id}
    POST /api/sources/{id}/generate-questions {max_single, max_multihop} -> {set_id}
    POST /api/evals/sets/{id}/run {name, settings?} -> {run_id} ; GET /api/evals/runs/{id} (progress) ; DELETE /api/evals/runs/{id}
    POST /api/simulate {question, result_id?, overrides} -> {trace, diff, answer?, explanation}
    POST /api/changesets {name, ops, from_result_id?, note?} ; POST /api/changesets/{id}/apply ; DELETE /api/changesets/{id}
    GET/PUT /api/settings ; POST /api/models/pull ; GET /api/status {neo4j, ollama, models, jobs, stats}
    GET  /api/entities?q=  (search entities by name, for the "add synonym" / "boost" pickers)
    GET  /api/graph/neighborhood?node_id=&depth=1  (small subgraph JSON for the graph picture)
The Analyze page shows, top to bottom:
    1. the question, expected answer (if any), the answer given, judge verdict/reason, metrics; "History" of this question across runs
    2. "What the search did": a step-by-step story: candidates (table: rank, triple, score, sent?, kept?, reason), the filter's raw reply,
       seed entities (name, weight, fact score sum, passage count, boost, from which facts), seed passages, fallback notice if any
    3. the graph picture (Cytoscape): seeds highlighted, passages as squares, gold passage(s) outlined, node size ~ PPR score; click a node
       to see its neighbours/edges (weights, kinds)
    4. ranked passages with the explanation sentence ("why") and rank/score/DPR rank; gold ones marked
    5. "Tweak & simulate" panel: sliders/inputs for linking_top_k, passage_node_weight, damping, node_specificity; checkboxes on each
       candidate fact (force in/out); entity boost inputs on seeds (+ entity search to boost any entity); edge edits (pick two nodes,
       set weight; "add synonym" helper); toggles "re-run the LLM filter" and "re-generate the answer"; "Simulate" button (JS -> POST
       /api/simulate) renders the diff table (before rank -> after rank with arrows), new seeds, new answer; "Save as changeset" button
       (name + note) -> POST /api/changesets with Overrides.to_ops(); note under it: fact in/out toggles are per-question and not saved.
templates/     base.html, library.html, source.html, ask.html, evals.html, eval_set.html, eval_run.html, analyze.html, changesets.html,
               settings.html, partials/ (source_row.html, run_row.html, ...)
static/        app.css (one clean stylesheet, system fonts, light theme, responsive; no framework), app.js (small helpers: fetch JSON,
               toasts), analyze.js (simulate panel + cytoscape), vendor/ (htmx.min.js, cytoscape.min.js already there)
```

### `src/hippo/mcp_server.py` and `src/hippo/cli.py`

```
mcp_server.py  build_server(ctx) -> MCPServer (mcp>=2: from mcp.server.mcpserver import MCPServer)
               tools: hippo_search(question, top_k=5) -> passages [{title, source, text, score, rank}] + kept facts
                      hippo_ask(question) -> {answer, thought, sources:[...]}
                      hippo_remember(name, text) -> {source_id} (adds a text source and indexes it)
                      hippo_sources() -> list of sources with status
               mount(app: FastAPI, ctx)   # streamable HTTP at /mcp, stateless_http=True, transport security allowing any host
                                          # (it runs inside docker; users connect at http://localhost:8000/mcp); wire session_manager.run()
                                          # into the FastAPI lifespan
               run_stdio(ctx)             # for `hippo mcp`
cli.py         main(argv=None): subcommands  serve (uvicorn), mcp (stdio), pull-models, index <path-or-git-url> [--name], ask "<question>",
               sources, settings. Uses AppContext.from_env().
```

### Docker, CI, docs

```
Dockerfile               python:3.12-slim, git installed (for repo cloning), pip install ., runs `hippo serve`
docker-compose.yml       services: neo4j (neo4j:5.26-community, ports 7474/7687, NEO4J_AUTH=neo4j/hippo-password, volume, healthcheck,
                         APOC not needed), app (build ., port 8000, depends_on neo4j healthy, env for NEO4J_*/OLLAMA_URL/HIPPO_*,
                         volume ./data:/app/data, extra_hosts host.docker.internal:host-gateway),
                         ollama (image ollama/ollama, profile "ollama", port 11434, volume) — only started when the host has no Ollama
hippo (bash launcher)    ./hippo up | down | logs | pull-models | test ; `up` checks host Ollama at :11434 -> sets OLLAMA_URL to
                         http://host.docker.internal:11434, else starts with --profile ollama; prints the URLs at the end
.env.example             every env var with a comment
.github/workflows/ci.yml lint (ruff) + unit tests with fakes + the same tests against a neo4j:5 service container (NEO4J_URI set)
README.md                the ELI5 guide (what/why, 3-step quick start, a tour of the pages, how HippoRAG works in plain words with a
                         diagram, MCP setup for Claude Code/Desktop/Cursor, configuration table, running without docker, tests, fidelity notes)
docs/FIDELITY.md         where we match the reference exactly and where we adapted (with reasons)
docs/MCP.md              connecting clients
```
