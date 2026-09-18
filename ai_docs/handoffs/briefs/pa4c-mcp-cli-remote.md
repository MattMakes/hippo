# Brief: activation Task 4c — MCP, local CLI and remote client actors, sessions and failures

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa4c` (branch `wp/pa4c`, base `1acf069`, the current `rag-it-all-tibs` HEAD).

GOAL: HTTP and stdio MCP, the local CLI and the remote client pass the correct `BuildActor` (or none) at ingress, hold one structural owner per operation, dispatch model paths through `retrieval_session`, and surface the closed public failure codes with no private text; `test_cli.py`'s fourteen pre-existing Starlette `timeout` failures are fixed by correcting the test usage. Committed on `wp/pa4c`.

CONTEXT (read all before coding):
- Plan sections: "Build actors at every boundary" (MCP, remote CLI and direct local `hippo index` bullets), "Production query-session activation" (the "Local CLI code and source listing" bullet), "Safe transport failures" (MCP `ToolError`, remote client, CLI stderr use the same stable code/message). Gates PA1 (MCP/CLI half), PA6.
- Task 4a outputs: `session-audit.md` rows tagged 4c (3 model/dense, 2 graph-only, 2 cli/admin) and `evidence-pa4a.md` "Breakage for 4b/4c/4d" (the fourteen `test_cli.py` rows: `StarletteDeprecationWarning: You should not use the timeout argument with the TestClient`; fix the usage, do not filter). Task 4a's note: `query_session(ctx)` with no access inherits the open audience, which cannot prove managed evidence; you decide the CLI rule below.
- `src/hippo/knowledge/public_errors.py`; Task 3a's `plan_dispatch` behavior (`ai_docs/reports/2026-09-11-pa3a-review.md`, last section); `ai_docs/handoffs/briefs/task4-notes.md`.
- Existing transport separation (Task 4 MCP subtask): HTTP MCP resolves only the request bearer/cookie via `AuthGate`; stdio MCP resolves the process `HIPPO_TOKEN` through its principal provider; `TransportBoundServer` keeps them apart. Do not weaken it.

REQUIRED BEHAVIOR:
1. HTTP MCP `hippo_remember` (and any ingress tool) passes `BuildActor.reader(principal)` only when the `AuthGate` principal is a real reader; never inspects `HIPPO_TOKEN`; open MCP stays legacy. Stdio MCP passes the reader actor resolved from `HIPPO_TOKEN` through its existing provider. Neither ever manufactures `trusted_local`.
2. Remote CLI keeps going through HTTP and inherits server authorization; it prints the server's stable `code` and message on failure, never a body dump.
3. Local `hippo index` resolves `HIPPO_TOKEN` with `principal_from_bearer` when users exist, requires `add_sources`, passes a reader actor; a missing or invalid token in gated mode fails before source creation; never-gated open mode preserves legacy indexing. CLI RULE (decided): local query, code and source-listing commands resolve the same principal the same way when users exist and use one structural session with the shared payload/source-view functions; in never-gated open mode they use the open audience (legacy evidence only). Administrative commands may keep explicit unrestricted store operations but never as query evidence.
4. MCP ask/search and CLI ask dispatch through `retrieval_session` over the one held owner; MCP sources/code tools and CLI code/source listing hold a structural `query_session`.
5. Failures: MCP `ToolError` carries the same stable code and message; CLI stderr prints code and message; tests inject secret/path/text/model-body strings and assert none reaches MCP results, CLI stdout/stderr or logs.
6. `test_cli.py`: remove the `timeout` argument from `TestClient` usage (or the equivalent the warning names) so the fourteen tests pass under bare `-W error`.

FILES:
  - own: `src/hippo/mcp_server.py`, `src/hippo/cli.py`, `src/hippo/remote.py`, `tests/unit/test_mcp_server.py`, `tests/unit/test_mcp_http.py`, `tests/unit/test_cli.py`, `tests/unit/test_remote*.py` (confirm with `ls`), NEW `tests/unit/test_managed_transport_activation.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4c.md`.
  - do NOT touch: `src/hippo/web/*`, `status.py` (4b), `analysis/*`, `evals/*` (4d), `knowledge/*`, `ingest/*`, `store/*`, `context.py`, `ask.py`, the shared `GATES.md`, `docs/`, the checkpoint.

STEPS:
1. Worktree + venv (with the `mcp==2.1.1` pin; note MCP HTTP tests need local socket permission, which the Claude worker has). Baseline your files on clean `1acf069` with form (b) where needed; the failures must match the breakage table rows for your files.
2. RED `test_managed_transport_activation.py`: HTTP MCP remember with a real reader reaches `add_text` with a reader actor (spy) and with open MCP stays legacy; stdio MCP resolves the token actor; `HIPPO_TOKEN` is never read on the HTTP path (monkeypatch `os.environ` and assert); local `hippo index` gated/open behaviors; CLI query in gated mode sees managed evidence, open mode does not; MCP ask/search and CLI ask hold one owner (acquisition/heartbeat/finalizer counts); failure redaction across MCP results, CLI stdout/stderr and logs; stable codes on MCP `ToolError`. Save `/tmp/hippo-pa4c-red.log`.
3. Implement; fix `test_cli.py` usage.
4. GREEN Fake: all your files plus `test_managed_route_activation.py` (form (b) where a module-level importer exists; `test_cli.py` must pass under bare `-W error` after your fix); log `/tmp/hippo-pa4c-fake-green.log`. GREEN Ladybug: `test_managed_transport_activation.py test_mcp_server.py`; log `/tmp/hippo-pa4c-ladybug-green.log`.
5. Ruff; evidence (commands, results, logs, audit rows by id, the CLI rule as implemented); commit on `wp/pa4c` in two or three commits.

DONE WHEN: your files green on both backends; evidence written; commits; `horch done` lists commits, files, audit rows by id, counts and logs, and the exact CLI principal rule implemented.

REPORT: `horch note` per step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for ownership or contract questions; wait.
