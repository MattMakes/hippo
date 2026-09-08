# QA3 — The final gate: results

Run on `wp/qa3` at `5928662` (Part A commit `cc94e51`, merged with `code-graph` tip `90757f4`,
which folded in wp/wp4d's docs-only changes after QA3 branched). Neo4j container
`hippo-neo4j-test` on port 17687 (justfile default; confirmed no other container held 17687/17474
before the leg ran). Scratch server: `HIPPO_DATA_DIR=/tmp/hippo-qa3 HIPPO_STORE=ladybug
.venv/bin/hippo serve --port 8013`, with `hippo.ingest.repos.clone_repo` monkeypatched (in a small
launcher script, `serve_with_local_clone.py`) to accept a `file://` checkout — `is_git_url` refuses
a local path by design (same bypass `tests/conftest.py::git_index` uses), and there is no supported
way to point a **repo** source at a local path through the UI. Ollama on the host is the real model
throughout Part C and Part D's `build_old.py` step.

## Verdict table

| Area | Result |
|---|---|
| Part A.1 — `commit_questions`/`path_fidelity` over real `git_index` | **PASS** |
| Part A.2 — `code_seeded`/`path_fidelity` eval summary cards | **PASS** |
| Matrix — `just test` (LadybugDB) | **PASS** — 1119 passed, 15 skipped, exit 0 |
| Matrix — `just test-fake` | **PASS** — 1119 passed, 15 skipped, exit 0 |
| Matrix — `just test-neo4j` | **PASS** — 1119 passed, 15 skipped, exit 0 |
| Matrix — `just lint` | **PASS** — ruff check + format, exit 0 |
| Step 4 — Ask (traceback, seed chip, Code graph card) | **PASS** |
| Step 4 — Analyze (seed-symbols table, Paths, Tests:/Commits: grammar) | **PASS** |
| Step 4 — Analyze (`code_structural_scale=0`, no LLM call) | **PASS** |
| Step 4 — Graph page (filter, node panel, subsystem colour) | **PASS** |
| Step 4 — Source page (`In the code graph` details, header stats) | **PASS** |
| Step 4 — Settings (`code_seed_weight=2`, `code_select` toggle) | **PASS** |
| Step 4 — CLI against running server (path/blast/raises/history) | **PASS** |
| Step 4 — MCP over stdio (9 tools, ambiguous-name `ToolError`) | **PASS** |
| Step 4 — prose question (no code card, `used_code_seeds=false`) | **PASS** |
| Part D — migration on the final tree | **PASS** |

## The three summary lines (verbatim, post-merge)

```
just test-fake:   1119 passed, 15 skipped, 17 warnings in 20.97s   EXIT 0
just test:        1119 passed, 15 skipped, 17 warnings in 459.43s (0:07:39)   EXIT 0
just test-neo4j:  1119 passed, 15 skipped, 17 warnings in 124.79s   EXIT 0
just lint:        ruff check: All checks passed! · ruff format: 133 files already formatted   EXIT 0
```

## Part A — the two loose ends

1. **`tests/unit/test_evals_code.py::test_commit_questions_over_real_git_history`** (new).
   Runs `commit_questions` and `run_question`'s `path_fidelity` over the `git_index` fixture (a
   real three-commit git repo, WP2b, landed after WP4c branched). Confirms the same shape the
   synthetic `code_history` fixture asserts:
   - the middle commit ("Total, invoice and log in place") edits only `place`'s body — one
     symbol — and never becomes a question;
   - the newest commit ("Raise on save, add the ts app") touches `pyapp.orders.OrderService.save`,
     `tsapp.index` and `tsapp.index.main` — three symbols, `path_fidelity` in `{0, 1/3, 2/3, 1}`;
   - the root commit's diff (S2.9's "no parent" case) lands on the whole tree **except**
     `tsapp.models.base`: that module's only content is one class (`tsapp/models/base.ts`), so
     once the class's lines are subtracted its own range is empty and no hunk ever lands on it —
     only the class and its method do. (My first hypothesis was `pyapp/store.py`; that module
     turned out to have blank lines between its two classes, so its own range is *not* empty and
     it correctly stays in the touched set. Verified by inspection of the fixture file, not by
     capturing whatever the code produced.)
   No `src/` change.
2. **`web/routes/evals.py::SUMMARY_CARDS`** gains `code_seeded` and `path_fidelity` (label + one-line
   help each), between `mean_gold_rank` and `dpr_fallbacks`. New test in
   `tests/unit/test_web_library_evals.py::test_summary_shows_code_seeded_and_path_fidelity_cards`
   drives a real run through the API and asserts both labels render on `/evals/runs/{id}` — RED
   verified before the fix (labels absent), GREEN after.

Committed on `wp/qa3` as `cc94e51`.

## Part C — manual verification, with real git history

Fixture: `tests/conftest.py::make_code_checkout` into `/tmp/hippo-qa3/checkout` (three real
commits, `git log --oneline`: `b569d9c` "Raise on save, add the ts app", `c9be063` "Total, invoice
and log in place", `dea088d` "Add the order service"). Indexed as a **repo** source
(`meta.url = file:///tmp/hippo-qa3/checkout`) plus `samples/acme_robotics.md` as a prose source, in
one memory, through the real pipeline with the real host Ollama (`qwen3:8b` / `nomic-embed-text`).
Server confirmed **open mode** (no users created, no auth needed for the browser, CLI or MCP checks
below). Screenshots in `/tmp/hippo-qa3/shots/` (kept; everything else under `/tmp/hippo-qa3` and
the scratch worktrees were removed — see Cleanup).

**Ask** — pasted `File "pyapp/orders.py", line 18, in place` traceback:
- seed chip `OrderService.place · stack trace · weight 0.333` (`pyapp/orders.py:18`), plus
  `total · identifier · weight 0.500` and `tsapp.models.order · identifier · weight 0.250`.
- Code graph card, "also reached by similarity" row, and (in the Analyze page's expanded Relations
  panel) the exact line `pyapp.orders.OrderService.place -[INVOKES 1.00 same_file]->
  pyapp.orders.OrderService.log`.
- Answer in 6395 ms. Screenshot: `01-ask-traceback.png`.

**Analyze** (`qa3-02-analyze.png`):
- Step 3b seed-symbols table: `total` (identifier, weight 0.500), `OrderService.place` (stack_trace,
  0.333), `tsapp.models.order` (identifier, 0.250), two data/symbol `Order` rows, two `dense` rows.
- Paths section, S2.15 grammar (`a -[KIND ω provenance]-> b`), 28 relations.
- `Tests:` `tests.test_orders.test_place`, `tests.test_orders`.
- `Commits:` `c9be063` 2024-01-02 "Total, invoice and log in place" · `dea088d` 2024-01-01 "Add the
  order service" — 7-char shas, exact subjects, matching `CODE_CHECKOUT_SUBJECTS`.
- Moved `code_structural_scale` to 0 and pressed Simulate twice, isolating each click against
  `~/.ollama/logs/server.log`: **zero** new `/api/chat` (LLM) requests either time; one
  `/api/embed` call each time (29–537 ms). This matches `analysis/simulate.py`'s documented design
  — the LLM fact filter and select pass are *replayed* from the baseline trace unless
  `rerun_filter`/`reanswer` are set (neither was here), but `retriever.retrieve` still re-embeds
  the question to re-score fact similarity. The requirement ("no LLM call fires") is about the
  chat/completion model, and it held: confirmed by isolating two back-to-back Simulate clicks
  against a 20-second idle control window (no embed/chat calls at all when idle, only the
  `/api/tags` status-badge polling that runs regardless). **Not a defect** — noted here because it
  is easy to misread "an Ollama request appeared in the log" as a violation when it isn't one.

**Graph** (`qa3-03*.png`, `qa3-04-graph-place-panel.png`, `qa3-05-graph-subsystem-color.png`):
filtered kind=`symbol`, name=`place` → 9 nodes. The graph is a `3d-force-graph` WebGL canvas with
no accessible DOM nodes per graph vertex, so the usual accessibility-tree click didn't work;
dispatched a synthetic `pointerdown`/`pointerup`/`click` sequence at the node's screen pixel
instead (a real click would work identically — this is a browser-automation constraint of the
canvas, not a product defect). Opened `pyapp.orders.OrderService.place`: signature
`def place(self, order)`, doc "Place an order: total it with billing, send the invoice and log the
path. Acme Robotics ships from Boulder.", Calls out (5), Called by (3), Tests (1), Commits (2) with
the same shas/subjects as above, `Raises: ValueError`. Subsystem colour mode recolours the node set
(all `pyapp.__init__` subsystem, shown red).

**Source page** (`qa3-06-source-place-details.png`): the `#10` passage
(`pyapp/orders.py :: pyapp.orders.OrderService.place`) has an "In the code graph" `<details>` with
`Commits: c9be063 2024-01-02 Total, invoice and log in place · dea088d 2024-01-01 Add the order
service`. Header: `SYMBOLS 30`, `DATA OBJECTS 12`, `RELATIONS 64`, `COMMITS 3`; `meta.code` (via
`/api/sources`) confirms `history_skipped: 0`. The template only renders the "history stopped
early" callout when `history_skipped` is truthy (same pattern as `files_skipped`), so `0` shows as
*no* callout — confirmed via the API rather than a visible "0" in the UI, which is consistent with
the rest of the page's "silent when good" convention, not a gap.

**Settings** (`qa3-07-settings-saved.png`): saved `code_seed_weight = 2` (field has `max="10.0"`,
confirming the `SETTING_RULES` fix — no longer capped at 1) and unchecked `code_select`; reload
confirms both persisted (`?saved=1`, field values `2.0` / unchecked).

**CLI against the running server** (`HIPPO_DATA_DIR=/tmp/hippo-qa3 HIPPO_PORT=8013`, open mode so
no token needed):
```
hippo path pyapp.cli.main pyapp.billing.total
hippo blast pyapp.orders.OrderService.place --depth 2
hippo raises pyapp.orders.OrderService.save OrderError
hippo history pyapp.orders.OrderService.place
```
All four printed `(the database is open in hippo serve; asking the server at
http://127.0.0.1:8013)` and correct output (`blast` included a `Subsystems:` line). Note: the
briefing's "set `HIPPO_URL`/token the way `test_cli.py`'s behind-server fixture does" doesn't map
to a real env var — the fixture monkeypatches `RemoteHippo.for_config` directly; the real CLI reads
`HIPPO_HOST`/`HIPPO_PORT` (`config.py`), which is what actually selects the remote target. Worth a
one-line clarification in `docs/CONTRACTS.md` or the CLI's own docstring for the next person who
goes looking for `HIPPO_URL` and won't find it.

**MCP over stdio** (`hippo mcp`, server stopped first to release the LadybugDB file lock — `hippo
mcp` builds its `AppContext` with `AppContext.from_env()` directly, unlike the CLI's
`_context_or_running_server()` fallback, so it cannot share the file with a running `hippo serve`).
`list_tools` → all nine: `hippo_ask`, `hippo_blast_radius`, `hippo_exception_path`,
`hippo_explain_path`, `hippo_history`, `hippo_remember`, `hippo_search`, `hippo_sources`,
`hippo_whoami`. Called `hippo_explain_path`, `hippo_blast_radius`, `hippo_exception_path`,
`hippo_history` — all four returned correct edges/lines matching the CLI output above. Called
`hippo_explain_path(a="log", b="pyapp.billing.total")` (ambiguous — three symbols named `log`):
`ToolError`, `"'log' could mean any of: pyapp.orders.OrderService.log, pyapp.store.Base.log,
tsapp.models.base.Base.log"` — exactly the three candidates. Server restarted after.

**Prose question** ("Where is Acme Robotics headquartered?", `qa3-08-ask-prose-no-code-card.png`):
answer "Boulder." in 2428 ms, no Code graph card, no chips under "the question named" (confirmed
`document.body.innerText` does not contain "Code graph"). Replayed the trace via `/api/simulate`
with the stored `trace_key`: `used_code_seeds: false` (3 `dense` code seed-symbol rows exist from
passages that happen to define symbols, but per S2.11 dense seeds never flip the flag — only a
lexical anchor does, and there wasn't one).

## Part D — migration, on the final tree

`/tmp/hippo-main` (scratch worktree of `main`, its own venv) indexed `samples/acme_robotics.md`
into `/tmp/hippo-qa3-old.lbug` through `main`'s real `index_source` with `FakeOllama` (31 entities,
8 passages, 34 facts), then added one manual `SYNONYM` (score 0.91) and one `TUNED` edge (weight
3.5) through `main`'s own `LadybugStore` API. Copied the file, opened the copy with the **final**
tree's `LadybugStore` (opening runs `ensure_schema`, the migration):

- `connection_pairs('SYNONYM')` == the full widened set for `("Entity", "Symbol", "DataObject")`
  (9 pairs) — **True**.
- `connection_pairs('TUNED')` == the full widened set for
  `("Entity", "Passage", "Symbol", "DataObject")` (16 pairs) — **True**.
- The old synonym row (`score 0.91`, `manual: True`) and the old tuned row (`weight 3.5`) load
  back unchanged; all 31 entities are present.
- Idempotence (`ensure_schema()` a second time on an already-widened file changes nothing) is not
  re-checked here — it's covered by
  `test_store_ladybug.py::test_an_old_narrow_database_is_widened_in_place_and_keeps_its_rows`,
  which ran green in all three matrix legs above.
- Indexed `code_sample.zip` into the **same** migrated file through the qa3 pipeline: source status
  `ready`, 30 `Symbol` nodes created — a code source can be added to a migrated file.

Scratch worktree `/tmp/hippo-main` and the scratch `.lbug` files removed after.

## Defects

None found. Two things noted above are process/documentation clarifications, not code defects:

1. The CLI's `HIPPO_URL` fallback env var named in the QA3 briefing does not exist; the real
   mechanism is `HIPPO_HOST`/`HIPPO_PORT`. No behavior is wrong — this is a note for whoever writes
   the CLI's user-facing docs next.
2. `code_structural_scale=0` + Simulate makes one `/api/embed` call (re-scoring fact similarity),
   not zero Ollama traffic. The "no LLM call" claim is about the chat/completion model specifically
   and holds; a reader skimming the Ollama log for "any request" could misread the embed call as a
   violation, so it is called out here rather than left implicit.
3. The briefing named the Neo4j container `hippo-neo4j-qa3`; the same paragraph also says the
   justfile default is fine now, so `just test-neo4j` ran as `hippo-neo4j-test` (its hardcoded
   name) instead. Not a defect — just noting the name actually used, for anyone grepping `docker
   ps` history for `hippo-neo4j-qa3` later.

## Cleanup

Server stopped. `/tmp/hippo-main` (Part D scratch worktree) removed after Part D. `/tmp/hippo-qa3`
data removed except `shots/`; scratch scripts under `/tmp/hippo-qa3-part-c` removed.
