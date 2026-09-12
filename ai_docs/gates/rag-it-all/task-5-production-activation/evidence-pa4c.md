# Evidence: activation Task 4c — MCP, local CLI and remote client actors, sessions and failures

Branch `wp/pa4c`. Base `rag-it-all-tibs` `957fc35`, fast-forwarded to `ffd2265` (see "Base" below).
Covers gate PA1 (the MCP/CLI half) and gate PA6 (the MCP/CLI/remote half).

## Base

The brief said to start from `957fc35`. That commit does not import: `hippo.ask` →
`knowledge.dense_session` → `knowledge.generation_profiles:14` → `ingest.accepted_inputs` →
`ingest/__init__:15` → `pipeline:47` → `managed_activation:35` → `prose_generation:25` →
`knowledge.generation_profiles` (partially initialised) → `ImportError: cannot import name
'MANIFEST_EXTERNAL_ID'`. In a clean `pa4c` worktree this is a **collection** error, not a test
failure: `tests/unit/test_mcp_server.py`, `test_mcp_http.py` and `test_managed_route_activation.py`
all abort with `Interrupted: 3 errors during collection`. `test_cli.py` still collects (it reaches
`hippo.ingest` first) but `test_ask_prints_the_answer_and_passages` fails on the same ImportError —
a fifteenth `test_cli.py` failure the pa4a breakage table does not list, because that table was
produced in the root tree, which held an uncommitted fix.

Reported as BLOCKED. The orchestrator committed the fix as `da51784` ("Import the managed lane
lazily so knowledge modules load first", plus `tests/unit/test_import_order.py`) and authorised one
merge. `git merge rag-it-all-tibs` fast-forwarded `957fc35 → ffd2265`; no merge commit exists, and
nothing outside `src/hippo/ingest/pipeline.py`, `tests/unit/test_import_order.py` and two ai_docs
files came in with it. After the merge `import hippo.ask` succeeds and the baseline below matches
the breakage table exactly.

## Commands and results

Baselines, at `ffd2265`, before any change of mine:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_mcp_server.py tests/unit/test_mcp_http.py \
  tests/unit/test_managed_route_activation.py -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
→ 63 passed

HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_cli.py -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
→ 14 failed, 41 passed          (/tmp/hippo-pa4c-baseline-cli-b.log)
```

The fourteen are exactly the breakage table's row E, same names, same
`StarletteDeprecationWarning: You should not use the 'timeout' argument with the TestClient`.

RED, `/tmp/hippo-pa4c-red.log` (first pass) and `/tmp/hippo-pa4c-red2.log` (the interrupt and
denial pass):

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_transport_activation.py \
  -q -o addopts='' -W error
→ 21 failed, 12 passed          (first pass)
→  5 failed, 33 passed          (second pass, after the review below)
```

The twelve that passed at RED are regression guards for behaviour 4a already made correct — MCP
ask/search and MCP sources/code already held one owner, because `ask._dispatch` wraps a borrowed
structural session rather than acquiring a second one. They are kept so that a later slice cannot
quietly undo it.

GREEN, Fake — `/tmp/hippo-pa4c-fake-green.log`:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_transport_activation.py \
  tests/unit/test_mcp_server.py tests/unit/test_mcp_http.py tests/unit/test_cli.py \
  tests/unit/test_managed_route_activation.py -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
→ 157 passed
```

`test_cli.py` alone under a **bare** `-W error`, as the brief requires —
`/tmp/hippo-pa4c-cli-after.log`:

```
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_cli.py -q -o addopts='' -W error
→ 55 passed
```

GREEN, Ladybug — `/tmp/hippo-pa4c-ladybug-green.log`:

```
HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_transport_activation.py \
  tests/unit/test_mcp_server.py -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
→ 56 passed
```

Ruff, on every file changed:

```
.venv/bin/ruff check  src/hippo/mcp_server.py src/hippo/cli.py src/hippo/remote.py \
                      tests/unit/test_managed_transport_activation.py tests/unit/test_cli.py
.venv/bin/ruff format --check <same five>
→ All checks passed! / 5 files already formatted
```

## Warning handling

- `tests/unit/test_cli.py`: **form (a)**, fourteen per-test markers, the exact sanctioned string.
  The file imports `starlette.testclient` inside `behind_server`, so the anyio
  `BlockingPortal` deprecation fires during fixture setup, where a marker still catches it. This is
  why the file now passes under a bare `-W error` and needs nothing on the command line.
- The combined GREEN command above carries **form (b)**, because `tests/unit/test_mcp_server.py`
  imports `fastapi.testclient` at module level and no marker can reach a collection-time warning.
- No `filterwarnings` was added to any ini file, and no application warning was suppressed.

## Audit rows closed

Rows are named by their id in `session-audit.md` (line numbers are that document's, at `043ca51`).

| Audit row | Symbol | Class | What it is now |
|---|---|---|---|
| `mcp_server.py:278` | `search_tool` | model/dense | One structural `query_session`, dispatched by `ask.search` through `retrieval_session`; whole body wrapped in the public-failure mapper. |
| `mcp_server.py:316` | `ask_tool` | model/dense | Same, through `ask.ask`. |
| `cli.py:233` | `cmd_ask` | model/dense | Now resolves a principal and holds `query_session(ctx, access)`, passing both to `ask`. Was `query_session(ctx)` — the open audience, whatever the token said. |
| `mcp_server.py:339` | `_code_graph` | graph-only | Unchanged acquisition (structural since 4a); failures now mapped. |
| `mcp_server.py:428` | `sources_tool` | graph-only | Unchanged acquisition; audience hoisted to one local, failures mapped. |
| `cli.py:278` | `_code_locally` | local-CLI presentation | Was `index = ctx.graph()`, the whole unrestricted graph. Now one structural `query_session` on the caller's audience, `session.settings["code_theta"]` instead of a second settings read, and `session.validate()` in a `finally`. |

Two further CLI presentation sites were converted that have no audit row, because neither held a
session to be swept up: `cmd_sources` listed `ctx.store.list_sources()` unrestricted (now
`_sources_locally`, one structural session through `status.source_view`), and `cmd_index` created a
Source with no identity at all (now gated).

**Count discrepancy, recorded not resolved:** the brief says 4c owns "3 model/dense, 2 graph-only, 2
cli/admin". `session-audit.md`'s own count table says `local-CLI / administrative presentation | 2
(4c 1, 4b 1)` — one row for 4c, `cli.py:278`. The audit is right about what is in it; the brief's
"2" has no second row to point at. `cmd_sources` is the site that would have been that second row
had unrestricted `list_sources()` matched the sweep pattern, and it is converted here.

## The CLI principal rule, as implemented

Written out because the brief left it to this slice to decide.

**Evidence commands** — `index`, `ask`, `sources`, `path`, `blast`, `raises`, `history`
(`cli.EVIDENCE_COMMANDS`) — resolve one principal per command through `cli._principal`:

```python
principal_from_bearer(ctx, os.environ.get("HIPPO_TOKEN") or None, require_online=True)
```

the same resolver and the same variable stdio MCP uses, so one token works for both. Then:

- **Users exist, token valid** → that reader. `index` additionally requires `add_sources` and passes
  `BuildActor.reader(principal)`; every read runs on `principal.access`, so the caller sees their
  own slice and can prove managed generations in it.
- **Users exist, token missing or unknown** → `Denied(NO_TOKEN)`, exit 2, message names
  `HIPPO_TOKEN` and the Account page. Nothing is created: the check is the first thing `cmd_index`
  does after choosing the local branch, before `add_repo`/`add_upload` and therefore before any
  Source row or saved byte.
- **Store unreachable** → `Denied(STORE_DOWN)`, exit 2. `require_online=True` is what makes this
  fail closed; without it a hiccup on a process that has never seen a user answers
  `Principal.open()`, handing the top role to a caller who proved nothing.
- **Never gated (no users)** → `Principal.open(top_role(...))`. No build actor, so indexing stays
  legacy; reads use the open audience, which is unrestricted over legacy evidence and proves no
  managed generation. `test_open_mode_cli_query_uses_the_open_audience_and_proves_legacy_only` pins
  that a managed source is *absent* there — this is Task 4a's decision 7 reaching the CLI, and it is
  the reason the rule had to be stated rather than inherited.

**Administrative commands** — `serve`, `mcp`, `pull-models`, `users`, `user`, `settings` — are
unchanged and ungated. Creating the first admin from `docker exec` is what they are for. They keep
their explicit unrestricted store operations (`list_users`, `list_roles`, `get_settings`,
`create_user`, …) and never use them as query evidence; `cmd_settings`'s retrieval-settings read is
configuration, not a corpus. They are also outside the public-failure mapping, so their own errors
still propagate as they did.

## Ingress actors

- **HTTP MCP** passes `BuildActor.reader(principal)` for the principal `AuthGate` resolved from the
  request's bearer or cookie, and never consults `HIPPO_TOKEN`. Proved by replacing
  `mcp_server.os` with a recording environment and asserting the key is never read on the HTTP path
  — and, as its counterpart, that the stdio path *does* read it.
- **Stdio MCP** keeps resolving `HIPPO_TOKEN` through its existing provider and builds as that
  reader. `TransportBoundServer` is untouched.
- **Open MCP** passes no actor, so `hippo_remember` keeps writing legacy evidence.
- **Remote CLI** still goes through HTTP and inherits server authorization; nothing about its
  identity changed.
- **`BuildActor.trusted_local()`** is never constructed by any of the three. `reader_actor`
  (`mcp_server.py`) and `_build_actor` (`cli.py`) return `None` rather than substituting it when the
  identity is open or unrestricted; `cli.py` holds its own three lines instead of importing
  `mcp_server`, which would drag FastAPI and the MCP library into `hippo ask`.

## Failures

One shape everywhere: `code: message`, both strings from `knowledge/public_errors.py`.

- **MCP** — every tool body goes through `mcp_server.tool_failure`, in this order: a `ToolError`
  passes through untouched; `public_failure(exc)`; `AuthorizationChanged` → `mcp_server.DENIED`;
  an **exact** `ValueError` → its own text; anything else → `OPERATION_FAILED`. The exact-type check
  is the load-bearing part: `ReadError`, `TooLarge`, `ManagedDispatchError` and `ProjectionError` are
  all `ValueError` *subclasses*, and an `isinstance` check would have let them out as `str(exc)`.
- **CLI** — `cli._refusal`, same table, printed to stderr as `error: <code>: <message>` with exit 2.
- **Remote client** — `RemoteHippo._refusal` reads `code` and `error` from the JSON body (the shape
  agreed with 4b: `{"error": failure.message, "code": failure.code}` at `failure.http_status`) and
  raises exactly `code: message`. The previous `detail = response.text` fallback is gone, so an
  unparseable error page is now reported as `<url>: <status>` and nothing else.
- **Redaction** is tested by injection: `POISON` carries a token, an absolute path, a sentence of
  source text and a model response body, and the tests assert none of the four reaches an MCP
  result, CLI stdout, CLI stderr, or any log record captured at level 0.

Two carve-outs, both deliberate and both plan-sanctioned:

1. **A symbol name and its candidates keep their text.** `AmbiguousSymbol` and `UnknownSymbol` are
   answers about the caller's own input; listing the candidates is the whole point of the error.
2. **`AuthorizationChanged` gets no code.** `public_failure` maps it to `None` and
   `_MANAGED_CODES["authorization_changed"]` is `None`, because the plan keeps a permission change on
   the response it already had. So both surfaces print one fixed sentence and no code, and
   `cli.DENIED` and `mcp_server.DENIED` are the same string. An earlier draft invented a fifth code
   `authorization_changed`; that would have reopened a closed set and was withdrawn.

`KeyboardInterrupt` and `SystemExit` are not mapped anywhere: all four handlers catch `Exception`,
not `BaseException`, so Ctrl-C during a build or a query still propagates instead of being reported
as `operation_failed`.

## The fourteen `test_cli.py` failures

Cause: `RemoteHippo.is_up` passed `timeout=3.0` on every liveness probe, including to the
`TestClient` the `behind_server` fixture hands in, and Starlette's `TestClient` refuses a
per-request `timeout` outright.

Fix, in `remote.py` rather than in the test, because the usage itself was wrong: a client the caller
supplied owns its own transport settings. `__init__` now records `self._probe_timeout = None if
client is not None else PROBE_SECONDS`, and `is_up` passes the keyword only when it has one. A real
`RemoteHippo` still gets its bounded 3-second probe; an injected client is never overridden. Both
branches are pinned by `test_the_liveness_probe_*`. No warning was filtered.

## Deviations and open items

1. **`add_repo` takes no `build_actor`** (`ingest/pipeline.py:162`), so gated `hippo index <git-url>`
   stays legacy: a repository is not an accepted managed input in this increment. `cmd_index` still
   requires `add_sources` and still refuses an invalid token first, so the identity rule holds; only
   the actor has nowhere to go. Not this slice's file to change. Recorded for whoever adds
   repository managed extraction.
2. **Gated `hippo index` sets no `owner_id` or `access_role_id`**, while MCP `hippo_remember` sets
   both from its principal. The brief asked only for the actor and the capability check, so widening
   the CLI's ownership semantics was left alone. Worth a decision in a later slice: a source built by
   a known reader arguably ought to be owned by them.
3. **Activating the actor moves accepted plain inputs from the legacy lane to the managed one**, and
   the managed lane resolves an embedding profile the legacy lane never asked for. Visible in
   `test_a_gated_local_index_really_reaches_the_managed_lane`: the shared `FakeOllama` serves no
   model metadata, so a gated `hippo index note.md` dispatches managed, fails
   `EmbeddingProfileUnavailable`, and presents `model_unavailable: The local model service was
   unavailable during the build.` with exit 1. That is the intended activation and the intended
   presentation, but it means the managed happy path is **not** exercised through the CLI here; the
   coordinator's own happy path stays in `test_managed_pipeline_activation.py`. Flagged because it is
   the first place a real deployment will notice the switch.
4. **`whoami_tool` was left alone.** It reaches a session only through
   `status.visible_source_count`, whose acquisition is `status.py:242`'s and therefore 4b's.
   Wrapping it here would have put two owners in one file's hands.
5. **`cmd_index` prints the Source row's stored `error` verbatim.** Checked rather than assumed:
   `managed_activation.map_build_failure` stores a closed code and a bounded sentence and never
   `str(exc)` (`FAILURES`, `managed_activation.py:343-357`), in the same `code: message` shape used
   here, so the printed line is already closed. A legacy row keeps its existing legacy text, which
   the plan preserves.
6. **Five failures in neighbouring files are pre-existing and belong to 4b**, not to this slice:
   `test_answer_original_citations.py` ×4 (breakage table row B) and
   `test_status_access.py::test_status_route_and_page_header_pass_the_request_audience` (row C).
   Proved rather than asserted: with my three `src/` files checked out back to `ffd2265` the same
   five fail with the same reasons — `/tmp/hippo-pa4c-prove-preexisting.log`, `5 failed, 32 passed`.
7. **No Neo4j run.** Out of this brief's scope, and this worker never held the disposable container.
