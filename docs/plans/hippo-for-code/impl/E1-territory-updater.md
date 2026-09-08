# E1 — Run hippo on a real repository (territory-updater) and see how questions are answered

Read `impl/00-impl-context.md` first. You are an exploration/QA worker: **you edit no source and no
test**; you produce `docs/plans/hippo-for-code/research/E1-territory-updater.md`. Worktree
`.worktrees/e1`, branch `wp/e1` (only the report is committed there), from the CURRENT tip of
`code-graph` (everything is merged and green). Scratch data under `/tmp/hippo-e1/` only. Ollama on the
host is the real LLM (`qwen3.8:latest`, tens of seconds per call) and the real embedder — this run is
the user's first look at the feature on their own code, so the report must show what they would see.
Never touch port 8000 / 7687 / 7474, `data/`, or the containers `hippo-app-1` / `hippo-neo4j-1`.

## The repository

`/Users/mascott/projects/territory-updater` (git, 160 commits, remote on GitHub). A Node/Express app
with MongoDB: `server/` (~9k lines JS/TS: `routes/api`, `services`, `logic/{queue,scraper,import}`,
`dnc-lookup`, `utils`, plus `src_old` and a `docs-wiki`), `scripts/`, `tests/` (~6.7k lines),
`README.md`, `DEPLOYMENT.md`, `docs/operations.md`, `docs/superpowers/{plans,specs}` (~8k lines of
markdown), `ai_docs/`. **It also tracks thousands of PDFs, PNGs, CSVs, xlsx and docx files containing
people's names and home addresses. Those must NOT be indexed**: they would swamp `MAX_CHUNKS`, cost
hours of OpenIE, and put personal data into a scratch memory for no reason. Index code and prose only.

## Build the source (a repo source, so git history is read)

1. Prepare a sparse local clone so the working tree holds only what should be indexed but `.git` holds
   the full history: `git clone --no-checkout /Users/mascott/projects/territory-updater
   /tmp/hippo-e1/checkout`, `git -C ... sparse-checkout set --no-cone server scripts tests README.md
   DEPLOYMENT.md docs/operations.md package.json justfile`, `git checkout`. Then remove anything
   non-code that still landed (`server/public/brand` images, any `.csv/.pdf/.docx/.xlsx/.png/.map` under
   the kept paths, `server/docs-wiki/assets`). Keep `server/docs-wiki/*.md` if it is prose about the
   app. Do NOT include `docs/superpowers` or `ai_docs` in the first pass (OpenIE over ~10k lines of
   markdown is hours); note in the report that they were excluded and why.
2. Dry-run the cost before indexing: `readers.read_source` + `extract_code` + `chunk_documents` (see
   `research/QA1-real-model-smoke.md` §Methodology for the exact scratch script) → number of documents,
   chunks, code passages, and how many chunks will reach OpenIE (prose chunks + code passages with a
   docstring ≥ 80 chars) × ~16-21 s each. **Target ≤ 90 minutes of indexing.** If the projection is
   higher, drop `server/docs-wiki` first, then `tests/`, and say so. Record the projection and the
   actual wall time.
3. Start a scratch server: `HIPPO_DATA_DIR=/tmp/hippo-e1 HIPPO_STORE=ladybug HIPPO_OPENIE_WORKERS=1
   .venv/bin/hippo serve --port 8014`, with the Ollama env the way `just dev` sets it. There is no UI
   path for a local repo source (`ingest.repos.is_git_url` refuses local paths by design): add the source
   the way `tests/conftest.py::git_index` and the QA3 report describe — create the source with the
   checkout path as `meta["url"]` and monkeypatch `clone_repo` to copy your sparse checkout (including
   `.git`) into the destination, then run the pipeline; or run a small launcher that patches
   `clone_repo` before `hippo serve`. Default settings (`code_history_depth` 200 covers all 160 commits).
   Record `meta["code"]` in full (symbols, edges by kind, files parsed/skipped, unresolved, commits,
   modifies, history_skipped, languages) and the Status page's Code card.

## Ask, and judge honestly

Ask each of these through the **Ask page** (screenshot each answer with its Code graph card into
`/tmp/hippo-e1/shots/`) and save the trace JSON (`/api/ask` returns it). Pick concrete names from the
repo yourself — read the code first so you can grade the answers. For each question record verbatim:
the question, the answer, the seed chips (which anchored, which were dense), the `Title: Code graph`
block, the top-5 passage titles, `timing_ms`, whether the select pass ran and what it dropped/expanded,
and your **verdict** (correct / partial / wrong / refused) with the file:line evidence from the repo that
proves it. Ten questions, in this mix:

1. "What does `<a queue worker function>` do?" — an identifier question on `server/logic/queue`.
2. "Where is `<that function>` called?" — the caller question the smoke fix was for.
3. A realistic Node stack trace (`at <fn> (server/logic/queue/<file>.js:<line>:<col>)`, 5-8 frames,
   ending in an `Error:` line) pasted with one sentence: "why would this happen?"
4. "Which commits touched the export worker?" — git history (the HEAD commit
   `fix(queue): keep the export worker alive, and show why a job failed` is a good target).
5. "How does the export queue keep the worker alive?" — code + commit message together.
6. "Which code reads or writes the `<a Mongo collection>` collection?" — data-access edges
   (`mongoose_model` / `mongo_chain`); check `meta["code"]["edges_by_kind"]` shows READS/WRITES first.
7. "What tests cover the NWS export?" — TESTED_BY.
8. "How do I seed an admin user?" — pure prose from the README; must show NO Code graph card and no
   anchored chips (dense chips are allowed).
9. "What does the DNC lookup do when the assessor site returns nothing?" — a cross-cutting question.
10. One question of your own that you think the graph should nail, and one you think it will miss.

Then, for questions 1, 2, 5 and 6, re-ask with the four baseline settings
(`code_seed_weight=0`, `code_dense_seeds=0`, `code_select=False`, `code_structural_scale=0`) through
the settings API and record whether the answer got worse, the same, or better. Restore defaults.

Also run against the live server (`HIPPO_HOST`/`HIPPO_PORT` as `test_cli.py`'s behind-server fixture
does — the CLI has no `HIPPO_URL`): `hippo path <route handler> <service function>`, `hippo blast
<the queue worker> --depth 2`, `hippo history <the queue worker>`, and one `hippo raises` if the code
throws a named in-repo error class. Paste the outputs.

## Output

`research/E1-territory-updater.md`: (1) a one-paragraph verdict a user would want first — does asking
this repo questions work, what was impressive, what was wrong; (2) a table of the ten questions with
verdict and timing; (3) each question in full as above; (4) the baseline comparison; (5) the CLI
outputs; (6) `meta["code"]` and the indexing cost; (7) **Defects** with reproductions (anything the
graph got wrong that the repo could answer, a chip that should not have fired, a block that hid the
answer, a UI glitch) and **Surprises**. Commit the report on `wp/e1`. Stop the server, delete
`/tmp/hippo-e1` except `shots/`. `horch tell orchestrator "[<role>] DONE: research/E1-territory-updater.md — <verdict line>"`,
ledger summary, close pane.
