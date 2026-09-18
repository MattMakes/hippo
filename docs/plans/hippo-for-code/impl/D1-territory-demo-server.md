# D1 — A persistent demo instance with territory-updater indexed (the user wants to browse it)

Read `impl/00-impl-context.md` for the fleet rules. You edit no source and no test. Worktree
`.worktrees/d1`, branch `wp/d1` (nothing is committed on it; it only gives you a venv at the current
`code-graph` tip). Never touch port 8000 / 7687 / 7474, `data/`, or the live containers.

Goal: the user wants to open a browser and look at the territory-updater code graph the E1 run
built. That run's data was deleted, so rebuild it — **persistently this time**, outside `/tmp`, and
leave the server RUNNING when you finish (it must outlive your pane).

## Do this, fast — the user is waiting for the URL

1. Read `research/E1-territory-updater.md` §Methodology: the sparse checkout (server/, scripts/,
   tests/, README.md, DEPLOYMENT.md, docs/operations.md, package.json, justfile — NO csv/pdf/docx/xlsx/
   png/map files, no `server/public/brand`, no `donotcalls.json` or other personal data) and the
   `clone_repo` monkeypatch launcher (`serve_with_local_clone.py`) that feeds a local checkout to the
   repo-source path. Recreate both under `/Users/mascott/hippo-demo/` (checkout at
   `/Users/mascott/hippo-demo/checkout`, launcher at `/Users/mascott/hippo-demo/serve.py`, data at
   `/Users/mascott/hippo-demo/data`, log at `/Users/mascott/hippo-demo/server.log`).
2. Start the server DETACHED so it survives your pane: `cd` to your worktree and run
   `nohup setsid env HIPPO_DATA_DIR=/Users/mascott/hippo-demo/data HIPPO_STORE=ladybug
   HIPPO_OPENIE_WORKERS=1 <ollama env as just dev sets it> .venv/bin/python
   /Users/mascott/hippo-demo/serve.py --port 8014 > /Users/mascott/hippo-demo/server.log 2>&1 &`
   (or the equivalent; verify with `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8014/`).
   The moment it answers, `horch tell orchestrator "[<role>] SERVER UP: http://127.0.0.1:8014/ pid <pid>"`.
3. Add the source (POST `/api/sources/repo` the way E1 did) and confirm the job is running on the
   Sources page. `code_history_depth` default. Then wait for status `ready` (~35 min), checking every
   few minutes; note the wall time and `meta["code"]` in the ledger.
4. Write `/Users/mascott/hippo-demo/README.txt`: how to stop (`kill <pid>`), how to restart (the exact
   command), where the data lives, and that the checkout is a sparse copy of
   `/Users/mascott/projects/territory-updater` at its current HEAD.
5. `horch tell orchestrator "[<role>] DONE: territory-updater indexed at http://127.0.0.1:8014/ — <meta summary>, pid <pid>, README at /Users/mascott/hippo-demo/README.txt"`,
   ledger summary, close pane. DO NOT stop the server. Remove the worktree (`git worktree remove
   .worktrees/d1`, `git branch -D wp/d1`) — the venv the server uses must be the ROOT `.venv`, not the
   worktree's, so start the server with `/Users/mascott/projects/hippo/.venv/bin/python` (the root venv
   is on the same `code-graph` tip and has all grammars installed).
