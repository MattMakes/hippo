# Fleet worker rules (rag-it-all-tibs, 2026-09-11; base revised 2026-09-15)

Every worker reads this file first, then its own brief. These rules override habits.

## Project

- Repo: `/Users/mascott/projects/hippo`. Branch `rag-it-all-tibs`. Base for new worktrees: the HEAD named in your spawn message (never older than `d6d9a6c`). Public remote `MattMakes/hippo`.
- Direction of record since 2026-09-15: `docs/spec/enterprise-graph-rag-v1.md` (the unified specification) and `docs/spec/connector-developer-kit.md` (the SDK design). Earlier plan, still authoritative for the records, identity and lifecycle it defines: `docs/rag_it_all.md`. Progress record: `ai_docs/checkpoints/2026-09-11-execution-state.md` (read the last ~60 lines for the current state). Handoff: `ai_docs/handoffs/whats-next.md`.
- Per-slice contracts live in `ai_docs/plans/rag-it-all-task-*.md`; per-slice gate ledgers in `ai_docs/gates/rag-it-all/<slug>/GATES.md`.
- Tasks 0–4 are complete and published; Task 5's code-capture and activation ledgers are MET by the checker (CD10 and PA8 sign-offs parked by the direction change). Production ingestion is the managed pipeline behind the activation dispatch. The Connector Developer Kit (gates CK1–CK7, `ai_docs/gates/rag-it-all/cdk/GATES.md`) is the open work. Nothing you do activates a new production route unless your brief says so.

## Never

- Never touch `data/`, `.rag-dev-data/`, the server on port 8011, or the user's Ollama. Never print, log, or commit anything from `.rag-dev-data/smoke-credentials.json` or any token.
- Never run tests against Neo4j unless the orchestrator has told you, in writing, that you hold the disposable container. There is exactly one (`hippo-rag-test-b780ab5`, bolt `127.0.0.1:32774`) and one pytest process at a time may use it. Never point tests at port 7687.
- Never `pkill -f` any pytest pattern. It kills other workers' runs. Kill your own run by PID or let it finish. Never kill a PID you did not start, even one that looks like yours: check its start time and command line against your own logs first (a reviewer killed the orchestrator's run's wrapper on 2026-09-16).
- Never `git add -A` / `git add .` / `git commit -a`. Stage only files your brief says you own. Never push. Never rebase or merge branches. Never edit `docs/rag_it_all.md`, `docs/spec/*.md` (except the single `docs/spec` file your brief grants by name), the checkpoint file, or another slice's gate ledger.
- Never edit a file your brief lists under "do NOT touch". If you believe you must, stop and ask the orchestrator (see Reporting).
- Never suppress application warnings to make `-W error` pass. The one sanctioned third-party exception is `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated`, raised by importing `fastapi.testclient` with anyio 4.15 + starlette 1.6. Two sanctioned ways to handle it, nothing else: (a) when the warning fires inside a test, the per-test marker exactly `@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")` as `tests/unit/test_eval_access.py:251` does; (b) when a test module imports `fastapi.testclient` at module level, the warning fires at collection and no marker can catch it, so append the exact filter to the command line after `-W error`: `-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`. Record which form you used in your evidence. Never add an ini-wide `filterwarnings`. Gate CHECK lines that include module-level importers must carry form (b); the orchestrator maintains those lines.
- Worktree venvs resolve `mcp` to 2.2.0 while the root venv has 2.1.1; after installing, run `uv pip install --python .venv/bin/python 'mcp==2.1.1'` so MCP test behavior matches the reviewed root results.
- Never mark a gate checkbox `[x]` yourself. Record EVIDENCE lines only where your brief says; the orchestrator runs the gate checker.

## Environment

- Python: `.venv/bin/python` (3.12.11). pytest 9.1.1, Ruff 0.16.6, real_ladybug 0.15.3. macOS: there is no `timeout` command.
- The store fixture DEFAULTS TO LADYBUG. Always set `HIPPO_TEST_STORE=fake` or `HIPPO_TEST_STORE=ladybug` explicitly.
- Standard test invocation: `HIPPO_TEST_STORE=fake .venv/bin/pytest <files> -q -o addopts='' -W error > /tmp/<name>.log 2>&1; echo EXIT $?`
  Piping to `tail` hides the real exit code. Always capture to a log and read the summary line.
- Ruff: `.venv/bin/ruff check <files> && .venv/bin/ruff format --check <files>`. Run on every file you changed before you report. CI also runs `ruff format --check` over Markdown fenced Python blocks, so run it on every `.md` you write under `ai_docs/` (evidence, reports, plan notes) and format them; six documents failed the CI Ruff job on 2026-09-12 for this reason.
- Full Fake suite takes several minutes and needs local socket permission for HTTP tests; only run it if your brief asks.

## Worktree recipe (implementers only; reviewers work in the root tree)

Run from `/Users/mascott/projects/hippo`:

```
git worktree add .worktrees/<name> -b wp/<name> <HEAD named in your spawn message>
cd .worktrees/<name>
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e '.[dev,neo4j]'
.venv/bin/python -c "import hippo, sys; print(hippo.__file__)"   # must print a path inside .worktrees/<name>/src
```

A bare `uv pip install` lands in the wrong environment, and the root `.venv` is pinned to the root tree's `src/`. Do all work, tests and commits inside the worktree. The worktree does not contain the root tree's uncommitted files; your brief says whether that matters.

## Method

- TDD. Write the failing tests first, run them, save the RED log to `/tmp/hippo-<slug>-red.log`, then implement, then save the GREEN log. Your report names both.
- Exact contracts are in the plan your brief cites. Read the cited sections completely before writing code. When the plan and the existing code disagree, the plan wins unless it is impossible; then ask.
- Existing public signatures stay stable unless your brief changes them explicitly.
- Commit style: one imperative sentence, like the existing log (`git log --oneline -20`). Small, reviewable commits. End the commit body with a `Claude-Session: https://claude.ai/code/<your own session id>` trailer (the orchestrator's is `session_014KWY6KpCppo87nb9edeiwf`; use yours for commits you author).

## Reporting

- `horch note "<one line>"` at every milestone: RED written, GREEN, Ladybug green, Ruff clean, committed. At least every 15 minutes of work.
- `horch tell orchestrator "[<your role>] BLOCKED: <question>"` when you cannot proceed, then WAIT for the answer. Do not guess on ownership or contract questions.
- `horch done "<summary>"` when finished. The summary must list: commits (hash + subject) or "no commits", files created/modified, test counts per backend with log paths, Ruff result, open findings or deviations from the brief. Then your pane closes.
- Budget: if you are not converging after roughly 400k tokens of context, stop at a clean checkpoint, `horch note` what remains, and `horch done` with a partial summary. A drifting long session is worse than a clean handoff.
