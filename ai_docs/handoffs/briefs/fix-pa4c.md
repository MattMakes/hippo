# Brief: Task 4c follow-up — MCP code tools through the mapper, owned CLI sources, one denial sentence

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `pa4cfix` (branch `wp/pa4cfix`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: Close the 4c review findings that live in the MCP, CLI and remote-client files, plus the two MCP test branches that pin the old raw behavior. Committed on `wp/pa4cfix`.

CONTEXT:
- Review: `ai_docs/reports/2026-09-11-pa4c-review.md` (read findings F1–F9, the F2a ruling section, and the "confirmed good" list so you do not re-litigate `require_online=True` or the exact-type `ValueError` rule). Prior evidence: `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4c.md`. Contracts: `ai_docs/handoffs/briefs/task4-notes.md`.
- Cross-slice facts: `/api/ask` and `/api/search` no longer answer `502 {error: str(exc)}` on the unmerged 4b-i branch (its commit `2377f7c`); after 4b-i merges, `web/app.py`'s 409 body becomes `{"error": "Permissions changed; repeat the query", "code": "authorization_changed"}`. Your remote-client change must consume exactly that. `ingest/pipeline.py` is Task 3b's file (in flight) and must not be edited here.

DECISIONS (final):
- F2 (major): every MCP code tool body, including the leading `validate()`, the acquisition/release of `query_session`, and the `finally` re-validate in `_code_answer` (~`mcp_server.py:413-439`), maps through `tool_failure`. Use the nested-try shape the reviewer prototyped (`/tmp/pa4c_probe7.py` if still present): outer try maps, inner `finally` validates on both exits, an ambiguous-symbol result keeps its text, a denial outranks a partial answer, and an already-mapped `ToolError` is never swallowed by the `finally`. Update the MCP branches of `tests/unit/test_lookup_snapshot_lifetime.py:~135` (`mcp_path`/revoke) and `tests/unit/test_graph_surface_access.py:~185` (four code tools) to assert `ToolError` whose message equals `mcp_server.DENIED` and that `PRIVATE SYMBOL` does not appear; leave every HTTP branch raising raw `AuthorizationChanged` (the web 409 handler is that surface's contract).
- F4 (major): gated `hippo index` creates the Source with `owner_id` = the resolved principal's user ID and `access_role_id` = that principal's tier, exactly as `hippo_remember` does, so a low-rank reader's indexed file is restricted to their tier and manageable by them. Test: a low-rank reader indexes a file; a higher-tier reader of another role cannot see it; the creator can delete it.
- F3 (major): `cmd_index` prints a stored Source error only when it matches the closed `code: message` shape produced by `managed_activation.record_build_failure`; any other stored text (the legacy lane stores `f"{type(err).__name__}: {err}"`) prints a fixed sentence such as `error: indexing failed; inspect local logs for source <id>`. Test with a legacy failure whose message carries a path and source text. (Changing what the legacy lane stores is Task 3b's file; the orchestrator carries it in the wrap-up notes.)
- F1 second half (major): `remote.py` never prints a response body it could not parse into `{error, code}`; on an unparseable or code-less body it prints `error: operation_failed: Operation failed; inspect local logs by operation ID` plus the HTTP status. Test with a body containing a path and source text.
- F6 (medium): ONE denial sentence on all three surfaces: set `mcp_server.DENIED` and `cli.DENIED` to exactly `Permissions changed; repeat the query` (the web sentence), and carry the code `authorization_changed` on MCP (`ToolError("authorization_changed: Permissions changed; repeat the query")`) and CLI stderr (`error: authorization_changed: Permissions changed; repeat the query`); keep the existing test that pins MCP and CLI to the same string, updated to the new value. Update `public_errors.py` ONLY if you must add the `authorization_changed` constant there (one line; say so).
- F5 (medium): a bare `ValueError` from a closed validator reads the same on MCP and CLI: both keep the validator's own bounded text (the reviewer's first option); a bare `ValueError` from anywhere else maps to `operation_failed` on both.
- F7: `sources_tool` validates its view after DTO construction like the CLI does. F8: `RemoteAmbiguous` can never be empty (fall back to the fixed sentence). F9: fix `cli._refusal`'s docstring or branch so they agree.

FILES:
  - own: `src/hippo/mcp_server.py`, `src/hippo/cli.py`, `src/hippo/remote.py`, `src/hippo/knowledge/public_errors.py` (one constant at most), `tests/unit/test_managed_transport_activation.py`, `tests/unit/test_mcp_server.py`, `tests/unit/test_mcp_http.py`, `tests/unit/test_cli.py`, the MCP branches only of `tests/unit/test_lookup_snapshot_lifetime.py` and `tests/unit/test_graph_surface_access.py`, NEW `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4cfix.md`.
  - do NOT touch: `src/hippo/web/*` (4b-i live, 4b-ii follow-up live in the root tree), `src/hippo/ingest/*` (3b live), `status.py`, anything else.

STEPS:
1. Worktree + venv (with the `mcp==2.1.1` pin). Baseline: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_transport_activation.py tests/unit/test_mcp_server.py tests/unit/test_mcp_http.py tests/unit/test_cli.py tests/unit/test_lookup_snapshot_lifetime.py tests/unit/test_graph_surface_access.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` green.
2. RED for F2, F4, F3, F1-second-half, F6, F5, F7, F8; save `/tmp/hippo-pa4cfix-red.log`.
3. Implement; GREEN: the baseline command (log `/tmp/hippo-pa4cfix-fake-green.log`) and Ladybug `tests/unit/test_managed_transport_activation.py tests/unit/test_mcp_server.py` (log `/tmp/hippo-pa4cfix-ladybug-green.log`).
4. Ruff; evidence (per finding what changed, file:line, tests); commit on `wp/pa4cfix` in two or three commits.

DONE WHEN: green on both backends; evidence written; commits; `horch done` lists per finding the change and test, the final `DENIED` sentence and code, counts and logs.

REPORT: `horch note` per step. `horch tell orchestrator "[<role>] BLOCKED: ..."` for any conflict with these decisions.
