# QA1 — Real-model end-to-end smoke of the code graph (runs while WP4 is built)

Read `impl/00-impl-context.md` first. You are a QA worker: **you edit no source and no test**; you
produce `docs/plans/hippo-for-code/research/QA1-real-model-smoke.md`. Worktree `.worktrees/qa1`,
branch `wp/qa1` (only your report file gets committed there). Scratch data under `/tmp/hippo-qa1/`.
Neo4j is not needed. **Ollama on the host is the real LLM** (`qwen3.8:latest`, tens of seconds per
call) and the real embedder (`nomic-embed-text`) — that is the point of this task: every unit test uses
`FakeOllama`, so nobody has yet seen the code graph under real vectors and a real extractor.

`code-graph` contains WP1-WP3: indexing writes symbols / data objects / edges / DEFINED_IN / REFERS_TO /
communities, retrieval seeds from anchors and dense hits, the answer carries a `Title: Code graph` block.
Git history (WP2b) and the web/CLI/MCP surfaces (WP4) are still in flight, so you work through the Python
API and the existing web UI/`hippo ask` only. Spec to test against: PLAN.md §Verification steps 4 (the
Ask part), 5 (deterministic re-index) and 6 (OpenIE cost), §Retrieval rule, and `research/S0-spikes.md`
spikes 1 and 2 (what real embeddings were predicted to do).

## Do this, in order, recording every number

1. Set up the worktree venv per the rulebook. Start a scratch server:
   `HIPPO_DATA_DIR=/tmp/hippo-qa1 HIPPO_STORE=ladybug HIPPO_OPENIE_WORKERS=1 .venv/bin/hippo serve --port 8012`
   (check `src/hippo/config.py` / `.env.example` for the Ollama URL and model env vars and set them the
   way `just dev` does; NEVER port 8000, NEVER `data/`). Log to a file.
2. **Index hippo itself** as a zip source (zip `src/`, `tests/`, `docs/`, `README.md`, `pyproject.toml` of
   your worktree — no `.venv`, no `.git`, no `data`). Record: wall time, `meta["code"]` in full,
   `stats()`, the number of NER/triples calls (count them in the log), and whether **any** OpenIE call's
   text contains a function body or `CREATE TABLE` (CI gate 2; grep the log with `HIPPO_OPENIE_WORKERS=1`).
   Then index the same zip again as a second source and compare `meta["code"]` and the node/edge
   multisets (`load_symbols`, `load_code_edges`, community excluded) — CI gate 1.
3. **Synonyms under the real embedder**: list every cross-kind SYNONYM written (`store` query or the
   loaders) with its score; hand-label the top 30 sensible / nonsense; compare with spike 2's prediction
   (≤ 27% nonsense after the ≥ 2-token guard). Confirm no one-token symbol has an embedding.
4. **Ask, five questions** through `hippo ask` or the Ask page, each with the trace saved (`/api/ask` or
   the CLI's JSON): (a) a traceback ending in `File "src/hippo/store/ladybug.py", line N, in
   ensure_schema` (pick a real line); (b) "what does GraphIndex.load do"; (c) "where is
   delete_code_nodes_for_source called"; (d) a pure-prose question about the README ("what backends can
   hippo use"); (e) a question with a bare English word that is also a symbol name ("what is the status
   of the project"). For each: `seed_symbols` (token, how, weight, n_matches), `used_code_seeds`, top-5
   passage titles, whether the select pass ran and what it kept/dropped/expanded, `timing_ms`, and the
   `context_block` verbatim. (d) and (e) must show `used_code_seeds == False` and no block.
5. **Inertness**: set the four settings (`code_seed_weight=0`, `code_dense_seeds=0`, `code_select=False`,
   `code_structural_scale=0`) via the settings API and re-ask (b) and (d); record the ranking deltas.
6. `extract_code` over `src/hippo` timing (must be < 5 s) and `GraphIndex.load` timing on this memory
   (spike 3 flagged vector reload cost).

## Output

`research/QA1-real-model-smoke.md`: a verdict table (CI gate 1, CI gate 2, inertness, anchors-on-prose,
synonym quality, timings — PASS/FAIL with the number), then the evidence per step, then a
**Defects** list — each with a reproduction (question text, settings, expected vs observed) precise
enough for a fix worker — and a **Surprises** list. Commit the report on `wp/qa1`, stop the server,
delete `/tmp/hippo-qa1`, `horch tell orchestrator "[<role>] DONE: research/QA1-real-model-smoke.md — <verdict line>"`,
ledger summary, close pane.
