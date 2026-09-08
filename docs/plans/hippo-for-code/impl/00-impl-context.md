# Shared context for every IMPLEMENTATION worker on "hippo for code" (phase 1)

You are an implementation worker in a herdr fleet. The plan is done; you are building it.
Ignore `docs/plans/hippo-for-code/tasks/00-shared-context.md` — that was for the read-only research
fleet. This file is your rulebook. Your own briefing (`impl/WP*.md`) says which slice is yours.

## The contract

`docs/plans/hippo-for-code/PLAN.md` (598 lines) is the single authoritative spec. Read it in full once
before touching code — the **Decision Log**, **Design summary** (graph model, ω table, retrieval rule,
settings, package layout) and **Test fixture plan** are the shared contract every WP builds against; then
your WP section is authoritative for your slice. Do not re-litigate decisions. If the plan is wrong about
the code (a cited line moved, a signature differs), follow the code and note the discrepancy in your
ledger notes; if the plan is internally contradictory or a decision is genuinely missing, `horch tell
orchestrator` and wait. The `research/R*.md` files are the evidence behind the plan; read the ones your
briefing points at when you need the *why*.

The five "Confirm with user" items ship at the plan's defaults. Do not change them.

## Where you work: a git worktree with its own venv

The repo root is `/Users/mascott/projects/hippo`; the integration branch is `code-graph` and is checked
out in the root tree. **Never edit files in the root tree.** Your briefing names your worktree directory
and branch; set up exactly like this (first thing, before reading code):

```bash
cd /Users/mascott/projects/hippo
git worktree add .worktrees/<name> -b wp/<name> code-graph     # from the CURRENT tip of code-graph
cd /Users/mascott/projects/hippo/.worktrees/<name>              # run this cd ALONE, then `pwd` to confirm
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e '.[dev,neo4j]'      # --python is REQUIRED (see below)
.venv/bin/python -c "import hippo; print(hippo.__file__)"       # must print YOUR worktree's src path
.venv/bin/python -m pytest tests/unit -p no:cacheprovider -W ignore -q -x 2>&1 | tail -3   # must be green before you start
```

Two harness gotchas found by the first worker: (1) a bare `uv pip install` ignores the local `.venv` when
the shell has an ambient conda/VIRTUAL_ENV active and installs into THAT — always pass
`--python .venv/bin/python`; (2) `cd <dir> && cmd` in one Bash call does not reliably persist the cwd to
later calls — run `cd` on its own, confirm with `pwd`, and prefer absolute paths.

Why the venv: the root `.venv` is an editable install pinned to the root tree's `src/`, so running it from
your worktree would test the root tree's code, not yours. The justfile uses a relative `.venv/bin`, so
inside your worktree `just test` (LadybugDB) and `just test-fake` run against YOUR checkout.

Every path in the plan is relative to the repo root; in your worktree that is
`/Users/mascott/projects/hippo/.worktrees/<name>/`. Do all `cd`, edits and test runs there.

## Tests: the three-store matrix

Every WP ends green on all three stores. Commands, inside your worktree:

1. `just test` — LadybugDB, a fresh embedded file per test. A bare `pytest` is ALSO LadybugDB, not the fake.
2. `just test-fake` — `HIPPO_TEST_STORE=fake`, the in-memory `tests/fakes/fake_store.py`. Fastest; run it constantly.
3. Neo4j — **do not run `just test-neo4j`**: it hardcodes one container name and port 17687, and other
   workers are running it at the same time as you. Use your own name and port from your briefing:
   ```bash
   docker rm -f hippo-neo4j-<name> >/dev/null 2>&1 || true
   docker run -d --rm --name hippo-neo4j-<name> -p 127.0.0.1:<port>:7687 \
       -e NEO4J_AUTH=neo4j/hippo-password neo4j:5.26-community >/dev/null
   for i in $(seq 1 40); do .venv/bin/python -c "import socket;socket.create_connection(('127.0.0.1',<port>),1)" 2>/dev/null && break; sleep 3; done
   HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://localhost:<port> NEO4J_PASSWORD=hippo-password \
       .venv/bin/python -m pytest tests/unit -p no:cacheprovider -W ignore -q
   docker stop hippo-neo4j-<name> >/dev/null
   ```
   Run the Neo4j leg when the other two are green, and again right before you report DONE.
4. `just lint` — `ruff check .` and `ruff format --check .` must both pass.

**Never touch ports 7687 / 7474 / 8000, the containers `hippo-app-1` / `hippo-neo4j-1`, or `data/`.**
That is the user's live hippo with their own memory in it; the `store` fixture WIPES whatever database it
is pointed at. `HIPPO_TEST_STORE=neo4j` must only ever see your throwaway container.

`FakeOllama` (`tests/fakes/fake_ollama.py`) stands in for the LLM in every unit test; no test may need
a running Ollama. Its OpenIE only matches English "X <relation> Y." sentences and its embeddings are
feature-hashed, so tests assert counts and structure, not model quality.

## Six load-bearing gotchas (all in PLAN.md, gathered here because they are scattered)

1. **Vertex order: entities, symbols, data objects, commits, passages — passages stay LAST.**
   `passage_position()` at `graph_index.py:247` derives `num_entities` as `len(node_ids) - len(passages)`;
   code vertices after passages give a negative index that silently serves the wrong passage. WP1 also fixes
   the arithmetic (`num_entities = len(entity_names)`, `first_passage_vertex`, nine call sites).
2. **Deleting a source's code nodes is THREE per-label statements** (`Symbol`, `DataObject`, `Commit`).
   `:Symbol:DataObject:Commit` is LadybugDB's OR but Neo4j's AND — chained it matches nothing on Neo4j and
   leaks every code node. Per-label statements are correct in both dialects.
3. **`used_code_seeds` flips only on a LEXICAL ANCHOR** (identifier / stack frame / exception / fenced code /
   diff). Dense seeds never flip it, and a dense seed is admitted only when its passage is in the OVERALL
   top `code_dense_seeds` of all passages by `dpr_scores` — never top-N among code passages (the score is
   min-max normalised, so that would fire on every prose question).
4. **Every code-touching weight term is multiplied by `code_structural_scale`** — CODE_EDGE, DEFINED_IN,
   REFERS_TO, MODIFIES and cross-kind SYNONYM. Entity–Entity SYNONYM and TUNED are not. Scale 0 must remove
   every code vertex from igraph; this is what the FIDELITY inertness claim rests on.
5. **`Chunk.extract_text` is three-valued:** `None` = OpenIE sees `text` (every prose chunk, unchanged);
   `""` = skip OpenIE; a non-empty string = OpenIE sees that string. Only the code chunker ever sets it.
6. **Dependency direction:** `codegraph/` imports only stdlib, tree-sitter, sqlglot and `hipporag.text`;
   `ingest.chunker` → `codegraph.model`; `hipporag.indexer` imports `CodeGraph` under `TYPE_CHECKING` only;
   `hipporag/paths.py` lives in `hipporag/` because the retriever calls it. WP1 imports nothing from
   `codegraph/` or `anchors.py`. `label_of` and `split_identifier` live in `hipporag/text.py` (already landed).

Also from the research: LadybugDB free text goes through `text(x or "")` on write and `decode()` on read —
a bare `None` breaks `decode()`; `UNWIND` writes go in batches of 5,000; `store/base.py` is the *Neo4j*
backend's base class, not an interface — the three stores match by convention and by `test_store_*` only.

## Code conventions

- Match the surrounding style exactly: the existing store methods, row shapers (`_passage_row` in
  `store/memory.py`), fixtures in `tests/conftest.py`, and `FakeOllama` call inspection. Read a neighbour
  before writing.
- `docs/CONTRACTS.md` lists module contracts; `docs/FIDELITY.md` says what stays byte-identical to the
  HippoRAG reference. WP4-docs updates them; every other WP keeps them true.
- Keep every new dataclass field defaulted (`Trace`, `TopNode`, `RankedPassage`, `Answer`, `Chunk`): stored
  traces and answers are loaded with `Cls(**row)` forever.
- No new env vars. Budgets and settings have exactly the spellings in PLAN.md §Settings and §2.2c.
- Tests that pin exact numbers/titles that your WP legitimately changes: update them and say so in your
  ledger note. Never weaken a fidelity assertion to get green.

## Working discipline

- Record progress in the ledger as you go (`horch note` if available; otherwise the notes your harness
  gives you). At minimum: started; each major milestone; anything you decided that the plan left open.
- Commit on your `wp/<name>` branch in small, green steps with clear messages. **Never merge, rebase onto,
  or push anything.** The orchestrator merges into `code-graph`.
- `git add` only your own files by path; `git status` before every commit; no stray scratch files.
- If blocked on a decision only the orchestrator/user can make: `horch tell orchestrator "<question>"`
  and WAIT for the answer. Do not guess on a Decision Log item.
- When truly done: all three stores green + lint green in your worktree, everything committed on your
  branch, ledger summary written, then
  `horch tell orchestrator "[<role>] DONE: <branch> <one-paragraph summary: what landed, tests updated, anything left>"`
  and close your pane. Your final ledger summary must list every file you created/modified and every
  pinned test you changed, so the next worker can be briefed without resuming you.
