# Re-review: the Task 4c follow-up (MCP, CLI, remote client)

Reviewer: `architect-reviewer-14`, root tree, read-only. Reviewed at HEAD
`c9404ed` ("Merge wp/pa4cfix"), which carries `f5c3777`, `39a3ba1`, `3dc4c39`,
`11e0859`, `01d11c3` and `2770e9a` on top of `be6062a`. The branch moved to
`812c60e` during the review; none of the eight files under review changed
(`git diff c9404ed 812c60e` over them is empty), and run (e) below re-confirms
the suite at the newer HEAD. Source of truth for the findings:
`ai_docs/reports/2026-09-11-pa4c-review.md`; decisions:
`ai_docs/handoffs/briefs/fix-pa4c.md`; implementer evidence:
`ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4cfix.md`.

**RE-REVIEW: PASS**

All nine findings F1-F9 and all three addenda are resolved, and the closed
public-code table is correct **at HEAD** rather than only at the branch base.
Four new findings, all Low: one documentation defect in `public_errors.py` that
could mislead a maintainer into deleting two live rows, and three coverage gaps
where the fix is right but nothing pins it.

Every `file:line` below is at `c9404ed`. The evidence's line numbers are from the
`wp/pa4cfix` worktree and have shifted.

---

## Run results

Root tree, `.venv/bin/python` 3.12.11, pytest 9.1.1, `mcp` 2.1.1 (confirmed by
`importlib.metadata`, because the `UnexpectedToolError` masking this review rules
on is version-specific). Every command captured to a log and read from the
summary line; `HIPPO_TEST_STORE` explicit on all four. No Neo4j.

| # | Command | Result | Log |
|---|---|---|---|
| a | `HIPPO_TEST_STORE=fake … test_managed_transport_activation.py test_mcp_server.py test_mcp_http.py test_cli.py test_public_errors.py test_lookup_snapshot_lifetime.py test_graph_surface_access.py test_managed_route_activation.py test_managed_web_ingress.py -q -o addopts='' -W error -W "ignore:…BlockingPortal…"` | **387 passed** in 44.37s, EXIT 0 | `/tmp/hippo-pa4c-rereview-a.log` |
| b | `HIPPO_TEST_STORE=fake … test_cli.py -q -o addopts='' -W error` (bare) | **55 passed** in 15.32s, EXIT 0 | `/tmp/hippo-pa4c-rereview-b.log` |
| c | `HIPPO_TEST_STORE=ladybug … test_managed_transport_activation.py -q -o addopts='' -W error -W "ignore:…BlockingPortal…"` | **64 passed** in 123.41s, EXIT 0 | `/tmp/hippo-pa4c-rereview-c.log` |
| d | `HIPPO_TEST_STORE=fake … test_public_errors.py test_status_access.py test_managed_source_inventory.py test_managed_source_lifecycle.py test_managed_pipeline_activation.py test_source_snapshot_lifetime.py test_query_snapshots.py test_render_authorization.py test_web_auth.py test_import_order.py …` | **317 passed, 3 skipped**, EXIT 0 | `/tmp/hippo-pa4c-rereview-d.log` |
| e | Runs (a) plus `test_query_session.py`, re-run at HEAD `812c60e` (which added `7bf700e`, the orchestrator's MCP-denial test adaptation, and `812c60e`, an arrow-ordering change in `knowledge/projection.py` that the code-tool suites read) | **425 passed** in 43.19s, EXIT 0 | `/tmp/hippo-pa4c-rereview-e.log` |

Run (b) re-confirms that `test_cli.py` passes under a **bare** `-W error`, so
form (a) is still sufficient there and the fix added no module-level
`fastapi.testclient` importer to that file.

Runs (d) and (e) are **not in the brief**. Run (d) closes a real gap in the evidence. The
evidence's own adjacent sweep (its row 4) was last run at `11e0859`, but two
commits that change `public_errors.py` landed after it: `01d11c3` added the
`retrieval_unavailable` row and `2770e9a` rewrote the docstring. `status.py:174`
renders Source rows through `public_failure_for_code(code) or OPERATION_FAILED`,
so a new row can change what an existing row renders as. Nothing regressed.

Run (e) covers `test_query_session.py`, whose four MCP revocation rows the
orchestrator adapted at `7bf700e` to expect the coded denial — the blast radius of
F6 outside this slice's owned files. Green.

Probes, all under `/tmp/pa4c-rereview-probe*.py`; nothing in the repo was
modified except this report.

---

## Findings table

| | Finding | Verdict | Where it is closed, and what proves it |
|---|---|---|---|
| **F1** (2nd half) | remote client printed a code-less body | **CORRECT** | `remote.py:131-154`. Verified against the *merged server*, not injected bodies — see (d) below. |
| **F2 + F2a** | four MCP code tools outside the mapper | **CORRECT** | `mcp_server.py:427-451` (nested `_code_answer`), `:457`, `:462`, `:471`, `:480` (`with _answering(), _code_graph(...)`). All four tools × four failure paths driven through the real server — see (a). |
| **F3** | `hippo index` printed the legacy lane's `str(exc)` | **CORRECT** | `cli.py:359-380` (`_stored_error`), applied at both print sites `:354` and `:635`. Coverage gap at the second site: **N2**. |
| **F4** | gated `hippo index` published to everyone, unmanageable by its creator | **CORRECT** | `cli.py:328-345`. Correct for **both** branches, file and git URL. Coverage gap on the git-URL branch: **N3**. |
| **F5** | bare `ValueError` read differently on MCP and CLI | **CORRECT** | `cli.py:225-232`. Exact-type branch, identical resolution on both surfaces — see (f). |
| **F6** | denial read three ways on three surfaces | **CORRECT** | `mcp_server.py:175-176`, `:190`; `cli.py:74-75`, `:213-219`. One sentence, one code, four surfaces — see (e). |
| **F7** | MCP `hippo_sources` did not validate its view | **CORRECT** | `mcp_server.py:561`, after the rows are built, matching `_sources_locally`. |
| **F8** | `RemoteAmbiguous` could be empty | **CORRECT** | `remote.py:47`, `:126`. `test_remote_ambiguity_is_never_an_empty_line` asserts a non-empty message and the intact candidate list. |
| **F9** | `_refusal` docstring contradicted its branch order | **CORRECT** | `cli.py:195-224`. Docstring amended, branch deliberately left above the guard; the reviewer's second observation (the two modules order the same table differently) is recorded too. |
| **A1** | tenth code `retrieval_rebuild_required` unmapped | **CORRECT** | `public_errors.py:198`. |
| **A2** | eleventh code `build_interrupted` unmapped | **CORRECT** | `public_errors.py:194`, mapped to `operation_failed`/500. The reasoning against 409 is right: the sweep leaves the source `ready`, so no rebuild-required claim about the corpus is true. |
| **A3** | mapping not closed over its own output | **CORRECT** | `public_errors.py:199`. Verified as a set computation at HEAD — see (g). |

Nothing is INCOMPLETE and nothing is WRONG.

---

## Re-probes the brief asked for

### (a) Every MCP code-tool path, through the real server

The review's F2 said the client is told `Error executing tool hippo_explain_path`
instead of the mapped string. The exact mechanism in mcp 2.1.1
(`mcp/server/mcpserver/tools/base.py:200-210`) is worth stating precisely,
because it decides what "never `Error executing tool`" can mean:

- a deliberate `ToolError` becomes `ToolError(f"Error executing tool {name}: {exc}")`
  and is logged at INFO with `%r`, **no traceback**;
- anything else becomes `UnexpectedToolError(f"Error executing tool {name}")` —
  the original text is **withheld from the client entirely** — and
  `server.py:440` writes the whole traceback via `logger.exception`.

So the `Error executing tool <name>` prefix is the library's and is unavoidable;
the contract is that the call raises a plain `ToolError` carrying the closed code,
not an `UnexpectedToolError`. `/tmp/pa4c-rereview-probe2.py` drives all four tools
through `build_server(...).call_tool(...)` and checks the class, the message, the
log level and whether a traceback was logged:

```
-- acquisition failure, poisoned OllamaError (ctx.graph_for raises) --
  hippo_explain_path     ToolError   traceback=False
      Error executing tool hippo_explain_path: retrieval_unavailable: Retrieval service is unavailable
  hippo_blast_radius     ToolError   traceback=False   (same)
  hippo_exception_path   ToolError   traceback=False   (same)
  hippo_history          ToolError   traceback=False   (same)

-- denial before the build (the leading validate()) --
  all four               ToolError   level=INFO  traceback=False
      Error executing tool <name>: authorization_changed: Permissions changed; repeat the query

-- denial outranking a mapped build failure --
  hippo_explain_path     ToolError   level=INFO  traceback=False
      ... authorization_changed: Permissions changed; repeat the query

-- build failure with a view that is still valid (the denial must NOT win by default) --
  hippo_blast_radius     ToolError   level=INFO  traceback=False
      ... retrieval_unavailable: Retrieval service is unavailable

-- ambiguity keeps its candidates --
  hippo_history(log)     ToolError   level=INFO  traceback=False
      ... 'log' could mean any of: csapp.Orders...Log, ..., pyapp.store.Base.log, ...
```

No `UnexpectedToolError`, no traceback, and no injected secret in either the
message or the captured log records, on any of the twelve cases. The
acquisition case is the half the review called a genuine leak, and it is closed.

**One phrasing correction, worth carrying forward.** The brief's F2 decision and
the evidence both say "an already-mapped `ToolError` is never swallowed by the
`finally`". Measured, the inner `ToolError` *is* superseded: with an ambiguous
name **and** a denial in the trailing `validate()`, the caller gets the denial and
loses the candidate list. That is correct and intended — a denial outranks a
partly built answer — but "never swallowed" should be read as "never lost to a
raw exception or a masked crash", not "never superseded". `mcp_server.py:436-441`
states it correctly; the evidence's summary does not.

### (b) A low-rank reader's gated `hippo index`, file and repository URL

`Access.can_see_source` (`access.py:111-117`) admits `min_rank <= rank`, so the
implementer's deviation from the brief's test phrasing is right: setting
`access_role_id` to the creator's role stops a tier *below* them seeing the
source, and a higher tier still sees it by design. The brief's "a higher-tier
reader of another role cannot see it" is inverted relative to the model.

The **file** branch is pinned by
`test_a_gated_local_index_is_owned_by_its_creator_and_kept_to_their_tier`.
The **git-URL** branch is not, so `/tmp/pa4c-rereview-probe1.py` exercises it —
a `local-assistant` (rank 10) runs `hippo index https://github.com/acme/widgets`:

```
kind: repo   owner_id: <creator>   min_rank: 10
creator may manage : True      creator can see : True
rank-0 guest can see : False   rank-0 guest may manage : False
```

`pipeline.add_repo` (`ingest/pipeline.py:170-182`) does accept both keywords at
HEAD and passes them to `create_source`, so extending F4 to `add_repo` is sound
and not blocked by 3b's merge. Coverage gap only: **N3**.

### (c) Neither CLI print site prints a legacy stored error

`_stored_error` (`cli.py:359-380`) prints a stored `error` unchanged only when its
leading token is a closed code, testing
`public_failure_for_code(code) is not None or code == DENIED_CODE`. The second
disjunct is needed because `authorization_changed` is the one closed code the
table maps to `None` on purpose, and it is exercised: the parametrised
`test_cli_index_prints_a_closed_stored_error_unchanged` covers
`model_unavailable`, `retrieval_rebuild_required` and `authorization_changed`.

The vocabularies cannot collide: an exception class name is CamelCase and a code
is snake_case, and `partition(": ")` splits on the first separator, so
`OllamaError: <300 chars of a model body>` always yields the class name as the
candidate code. A stored string with no `": "` at all also falls to the fixed
sentence.

`/tmp/pa4c-rereview-probe4.py` drives the **second** print site, `_index_remotely`
(`cli.py:635`), which no test reaches:

```
legacy row  -> exit 1 | error: indexing failed; inspect local logs for source src-1
closed row  -> exit 1 | error: retrieval_rebuild_required: Rebuild compatible sources before retrieval
denial row  -> exit 1 | error: authorization_changed: Permissions changed; repeat the query
```

Correct, and clean of the injected path, token, source sentence and model tag.
Coverage gap only: **N2**.

### (d) The remote client against the real merged server

Done against a live `create_app(ctx)` behind a `TestClient` handed to
`RemoteHippo` as the injected client, not against injected bodies, so the branch
of `_refusal` that actually fires post-4b-i is on the record
(`/tmp/pa4c-rereview-probe3.py`):

```
server 503 {"error":"Retrieval service is unavailable","code":"retrieval_unavailable"}
  hippo ask (remote) -> error: retrieval_unavailable: Retrieval service is unavailable
  branch: code+error. No URL, no status suffix.

server 500 ''  (a BaseException the route's `except Exception` does not catch)
  hippo ask (remote) -> error: operation_failed: Operation failed; inspect local logs
                               by operation ID (HTTP 500)

server 404 Not Found  (/api/code, unknown symbol)
  hippo blast (remote) -> error: no symbol or data object called 'no_such_thing'
  the symbol survives; "http://server" does not.

server 409 {"error":"Permissions changed; repeat the query","code":"authorization_changed"}
  hippo ask (remote) -> error: authorization_changed: Permissions changed; repeat the query
```

Note the merged `/api/ask` answers an `OllamaError` as **503**, not 500: 4b-i
routes it through `public_failure_response(retrieval_failure(exc))`, so F1's root
cause is closed at the source as well as in the client. The fixed-sentence branch
was therefore also exercised against a genuinely code-less 5xx above.

The F1 leak shape itself can no longer print, at any status
(`/tmp/pa4c-rereview-probe4.py`):

```
502 {"error": "<poisoned OllamaError text>"} -> operation_failed: … (HTTP 502)
500 {"error": "<poisoned>"}                  -> operation_failed: … (HTTP 500)
409 {"error": "<poisoned>"}                  -> operation_failed: … (HTTP 409)
500 {"detail": "<poisoned>"}                 -> operation_failed: … (HTTP 500)
```

The orchestrator's ruling (B) — keep `detail` on a 4xx — is the right call and is
the review's own F1 proposal. Without it `hippo blast no_such_thing` behind a
server would lose the only actionable fact in the response, and the remote and
in-process branches of one command would stop agreeing.

### (e) One denial sentence and code, everywhere

```
MCP             authorization_changed: Permissions changed; repeat the query
CLI (evidence)  authorization_changed: Permissions changed; repeat the query
CLI (admin)     authorization_changed: Permissions changed; repeat the query
remote          authorization_changed: Permissions changed; repeat the query
web 409 body    {"error":"Permissions changed; repeat the query","code":"authorization_changed"}
```

`mcp_server.DENIED == cli.DENIED` and `mcp_server.DENIED_CODE == cli.DENIED_CODE`.
The web body was read off the real app, not asserted from the constants.

The cross-surface test's remote half builds its injected body **from**
`mcp_server.DENIED`, which on its own would let the web app drift; but
`test_graph_surface_access.py:80-84` asserts the real 409 body as a literal, and
`test_managed_transport_activation.py:52` pins the MCP/CLI rendering as a literal
too. Two files spell the same string independently, so a drift on either side
fails a test. Not a finding — but the agreement rests on two literals matching,
not on a shared constant, which is the cost of `cli.py` deliberately keeping
`knowledge` out of its top-level imports (there are now three copies of
`authorization_changed` in the tree: `mcp_server.py:176`, `cli.py:75`,
`web/app.py`).

### (f) The exact-type `ValueError` rule, identical on MCP and CLI

```
ValueError("note.md is too big (9,000,000 bytes); …")
    MCP -> note.md is too big (9,000,000 bytes); …        CLI -> identical
ValueError("photo.heic is not a supported file type …")
    MCP -> photo.heic is not a supported file type …      CLI -> identical
ProjectionError(<poison>)  both -> operation_failed: Operation failed; inspect local logs …
ReadError(<poison>)        both -> invalid_source: The source is not an accepted input type
RuntimeError(<poison>)     both -> operation_failed: Operation failed; inspect local logs …
```

The exact-type check (not `isinstance`) is load-bearing and both modules now use
it for the same reason. Note the two modules still consult the table in different
orders — `tool_failure` asks `public_failure` first, `_refusal` asks about a
permission change first — and agree only because `AuthorizationChanged` appears
in no row. `cli.py:205-208` records that, which is what F9 asked for.

### (g) The closed table, computed at HEAD

The evidence measured the table against `wp/pa3b`; 3b, 4b-i and 5A have merged
since. Recomputed at `c9404ed` as a set difference over every producer —
`managed_activation.FAILURES`, `UNKNOWN_CODE`,
`store/memory.INTERRUPTED_REFRESH_ERROR`'s prefix, and every `PublicFailure.code`
in the module:

```
PRODUCERS NOT IN TABLE: []
TABLE KEYS WITH NO PRODUCER: []
```

Exactly closed in both directions; no twelfth producer went unmapped. The round
trip:

```
authorization_changed      -> None (deliberate)
build_busy                 -> operation_failed            500   idempotent
build_cancelled            -> operation_failed            500   idempotent
build_interrupted          -> operation_failed            500   idempotent
invalid_configuration      -> operation_failed            500   idempotent
invalid_source             -> invalid_source              400   idempotent
model_unavailable          -> retrieval_unavailable       503   idempotent
operation_failed           -> operation_failed            500   idempotent
retrieval_rebuild_required -> retrieval_rebuild_required  409   idempotent
retrieval_unavailable      -> retrieval_unavailable       503   idempotent
source_too_large           -> invalid_source              413 -> 400   NOT identity
unsupported_source         -> invalid_source              400   idempotent
```

`test_the_code_mapping_is_idempotent` (`test_public_errors.py:311-333`) handles
the `None` row by early return rather than exploding on `.code`, and pins the
413 -> 400 collision **by name** with a message telling the next reader to re-read
the table comment. That is the honest test: asserting total object idempotence
would have passed only by not looking, and Task 4f would have inherited a false
guarantee. The ruling recorded in `task4-notes.md` — a stored code round-trips to
a *rendering*, never to a status — is consistent with what the code does.

### (h) The `hippo --help` import footprint

Measured rather than cited, in a fresh interpreter running `main(["--help"])`
under `SystemExit` and then dumping `sys.modules`
(`/tmp/pa4c-rereview-probe5.py`):

```
hippo.* modules imported: 33     total sys.modules: 489
  absent   hippo.ingest.pipeline
  absent   hippo.knowledge.public_errors
  absent   hippo.ingest.managed_activation
  absent   fastapi
  absent   starlette
```

The absences are the contract, and they hold. `remote.py` carries no top-level
`knowledge` import at all (`remote.py:33-41`); `cli.py` imports `public_errors`
per call at `:211` and `:373` and `ingest` per call at `:314`, `:614`, `:797`.
The evidence's "488 modules exactly" is one off here, which is an environment
difference between the worktree and the root venv and not a contract; the count
should not be used as one. Nothing pins any of this: **N4**.

---

## New findings

### N1 — Low — `public_errors.py`'s table comment points at the wrong two rows

`src/hippo/knowledge/public_errors.py:179-184`, echoed at
`tests/unit/test_public_errors.py:208-212`

The comment says:

> The last two rows are not build-lane codes at all: they are this module's *own*
> public codes, here so that `public_failure_for_code` is closed over the whole
> public vocabulary …

The last two rows of the literal it introduces (`:192-205`) are `invalid_source`
and `operation_failed`. Both **are** build-lane codes: `invalid_source` is in
`managed_activation.FAILURES` and `operation_failed` is `UNKNOWN_CODE` — verified
by the set computation in (g) above.

The rows the sentence means are `retrieval_rebuild_required` (`:198`) and
`retrieval_unavailable` (`:199`), which the two addenda added. Even for those the
claim is half wrong: `retrieval_rebuild_required` **is** a build-lane code, as the
same comment says twenty lines earlier at `:158` ("the one code the two
vocabularies name identically"). Only `retrieval_unavailable` is purely this
module's own.

**Failure scenario.** A maintainer trimming the table on the strength of that
sentence goes to `invalid_source` and `operation_failed` — two codes the managed
lane really stores — instead of to the row the comment means. Deleting either
would be a live defect: `status.py:174` renders a Source row as
`(public_failure_for_code(code) or OPERATION_FAILED).message`, so every row
carrying `invalid_source` would stop saying "The source is not an accepted input
type" and start saying "Operation failed; inspect local logs by operation ID" — a
400 the user can fix, reported as a 500 they cannot.

**It would not get that far, which is why this is Low.**
`test_every_public_code_round_trips_to_a_failure_carrying_that_code`
(`test_public_errors.py:289-307`) hardcodes the five module constants rather than
mirroring the dict, so removing either row fails it on the `None`. Measured:

```
removed 'invalid_source'    -> closure test fails on: ['invalid_source', 'invalid_source']
removed 'operation_failed'  -> closure test fails on: ['operation_failed']
```

So the defect is documentation only: the comment sends a reader to the wrong two
rows and contradicts itself about `retrieval_rebuild_required`, and the closure
test — added by the third addendum — is what stops that turning into a
regression.

The count sentence at `:143` ("The eleven stable values a Source row's `error` can
carry") is **correct** — eleven of the twelve keys are storable and
`retrieval_unavailable` is not — but it opens a comment on a twelve-entry literal
without saying so, which is what makes the later sentence easy to misread. The
test file's mirror comment (`test_public_errors.py:208-212`) is genuinely off by
one: it says "These eleven" and then enumerates 9 + 2, while the dict below it has
twelve entries, `retrieval_unavailable` being uncounted.

**Proposed fix.** Comment only; no behavior change. Name the rows instead of
positioning them — "`retrieval_unavailable` is the one row no producer stores: it
is here only so the mapping is closed over its own output" — and make the test
mirror say twelve.

### N2 — Low — `_index_remotely`'s stored-error print has no test

`src/hippo/cli.py:635`

F3 was applied at both print sites, correctly and deliberately (the server's
Source row is the same row with the same two lanes in it). Only `cmd_index` is
pinned; `_index_remotely` is reached by `hippo index` whenever a server holds the
database, which is the common deployed case. Proved correct by probe above, but a
regression there would not fail the suite.

**Proposed fix.** One test, the `FakeRemote` shape from
`/tmp/pa4c-rereview-probe4.py`: a legacy row asserting the fixed sentence and
`assert_clean`, a closed row asserting it prints unchanged.

### N3 — Low — the git-URL branch of `cmd_index`'s identity rule has no test

`src/hippo/cli.py:333`

The implementer extended F4 to `add_repo`, which the review had not named. The
extension is right and the code is right for both branches, but
`test_a_gated_local_index_is_owned_by_its_creator_and_kept_to_their_tier` indexes
a file, so the `repos.is_git_url(target)` branch — a different pipeline function
with its own keyword arguments — is unpinned. A repository indexed by a low tier
discloses exactly as much as a file does, which is the argument for extending the
fix, and it is the same argument for pinning it.

**Proposed fix.** Parametrise the existing test over `(file, git URL)` with
`pipeline.start_indexing` patched out, as `/tmp/pa4c-rereview-probe1.py` does.

### N4 — Low — nothing pins the `hippo --help` import footprint

The implementer caught a real regression here by measuring against the committed
base: a top-level `public_errors` import in `remote.py` pulled the whole ingest
stack into `hippo.cli`'s graph. The fix (a per-call import) is in the tree and
holds, but the next person to add a convenient top-level import to `cli.py` or
`remote.py` gets no signal. `tests/unit/test_import_order.py` checks only that
each module imports cleanly in a fresh interpreter, not what it drags in.

**Proposed fix.** One subprocess test beside `test_import_order.py` asserting the
absences, not a count: `hippo.ingest.pipeline`, `hippo.knowledge.public_errors`,
`hippo.ingest.managed_activation`, `fastapi` and `starlette` are all out of
`sys.modules` after `hippo.cli.main(["--help"])`.

---

## Deviations from the brief: all four are sound

1. **F1 second half implemented as (B)** — keep `detail` on a 4xx. Raised as
   BLOCKED and ruled by the orchestrator before implementing. Confirmed above:
   the literal rule would have cost `hippo blast <unknown symbol>` its only
   actionable fact behind a server, and (B) is the review's own F1 proposal.
2. **F4 extended to `add_repo`, and the brief's test phrasing inverted.** Both
   correct; `can_see_source` is `min_rank <= rank` (`access.py:117`).
3. **F6 added no constant to `public_errors.py`.** Correct — none was needed.
4. **F9 amended the docstring rather than moving the branch.** The better of the
   two options the review offered: moving the guard would make an administrative
   command answer a permission change with a traceback, which contradicts F6.
5. **F3 also applied to `_index_remotely`.** Right call, unnamed by the review.

## Still open, and owned elsewhere — not grounds against this slice

- `web/routes/api.py:50/94/117` and `web/routes/code.py:217` catch `ValueError`
  by `isinstance`, so a `ReadError`/`TooLarge`/`ProjectionError` message can
  reach a 4xx `detail` and therefore the remote CLI. Bounded per the original
  review's enumeration, but outside the closed validator set. Task 4 wrap-up.
- `ingest/pipeline.py:309` still stores `f"{type(err).__name__}: {err}"` on the
  legacy lane; `ingest/pipeline.py:146`, `:216-221` still raise bare `ValueError`
  where `ReadError`/`TooLarge` would let the table do the work. Task 3b/4e.
- Three copies of `authorization_changed` (`mcp_server.py:176`, `cli.py:75`,
  `web/app.py`). Consolidating is not free, because `cli.py` deliberately keeps
  `knowledge` out of its top-level imports — see (h).

## What is good here

- Driving the acquisition failure into the mapper is the half of F2 that mattered
  and it is the half the original review had no test for. The new test injects at
  `ctx.graph_for` rather than using `poisoned()`, with a comment saying why (the
  code tools never call a model) — that is the right reason, recorded.
- `test_graph_surface_access.py:184-194` now asserts the redaction it exists to
  prove instead of inheriting it as a side effect of the bug. That is a strictly
  better test than the one it replaced.
- The idempotence test pins the 413 -> 400 collision by name rather than skipping
  the row. A test that asserted total idempotence would have been green and
  wrong, and Task 4f would have built on it.
- `_stored_error`'s closed-shape check is the right shape: it asks the table
  rather than re-deriving a classification this process never saw.
- The `hippo --help` import regression was caught by measuring against the
  committed base rather than by assuming, and reported as a deviation nobody had
  asked about.
