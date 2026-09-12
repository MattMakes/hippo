# Evidence: Task 4c follow-up — MCP code tools through the mapper, owned CLI sources, one denial sentence

Branch `wp/pa4cfix`, base `rag-it-all-tibs` `be6062a`. Closes findings F1 (second half),
F2 (with F2a), F3, F4, F5, F6, F7, F8 and F9 of
`ai_docs/reports/2026-09-11-pa4c-review.md`, plus one addendum routed mid-task from
Task 3b. Covers gate PA6 (the MCP/CLI/remote failure-contract half).

The base does **not** include 3b's merge (`640d20b`); I stayed on `be6062a` as the brief
says. 3b did not touch `src/hippo/knowledge/public_errors.py` — the file is byte-identical
on `wp/pa3b` and on `be6062a` — so the addendum row below cannot conflict on merge.

## Commands and results

All from `.worktrees/pa4cfix`, `.venv/bin/pytest` 9.1.1, mcp pinned to 2.1.1, each captured
to a log and read from the summary line. The sanctioned warning filter is form (b) on every
command: the `-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`
pair, because `test_cli.py`, `test_mcp_http.py` and `test_graph_surface_access.py` import
`fastapi.testclient` at module level and no per-test marker can catch a collection-time warning.

| # | Command | Result | Log |
|---|---|---|---|
| 1 | Baseline, before any change: the brief's six files | **188 passed**, EXIT 0 | `/tmp/hippo-pa4cfix-baseline.log` |
| 2 | RED: the six files plus `test_public_errors.py` | **31 failed**, 259 passed | `/tmp/hippo-pa4cfix-red.log` |
| 3 | GREEN (Fake), the brief's command | **212 passed**, EXIT 0 | `/tmp/hippo-pa4cfix-fake-green.log` |
| 4 | GREEN (Fake), adjacent sweep — see below | **290 passed, 1 skipped**, EXIT 0 | `/tmp/hippo-pa4cfix-sweep.log` |
| 5 | GREEN (Ladybug), `test_managed_transport_activation.py test_mcp_server.py` | **85 passed** in 246.96s, EXIT 0 | `/tmp/hippo-pa4cfix-ladybug-green.log` |

The adjacent sweep (4) is not in the brief. `public_errors.py`, `cli.py`, `mcp_server.py` and
`remote.py` are read by surfaces outside the six files, so it covers `test_public_errors.py`,
`test_managed_route_activation.py`, `test_web_auth.py`, `test_managed_pipeline_activation.py`,
`test_status_access.py`, `test_managed_source_inventory.py`, `test_managed_source_lifecycle.py`,
`test_source_snapshot_lifetime.py`, `test_query_snapshots.py` and `test_render_authorization.py`.
Nothing regressed.

Ruff: `.venv/bin/ruff check` and `ruff format --check` over all eight changed files — clean.
(`ruff format` reformatted two over-long parametrise/signature lines in
`test_managed_transport_activation.py` before the final check.)

## Per finding: what changed, where, and what pins it

### F2 + F2a (major) — the four MCP code tools were outside the mapper entirely

`src/hippo/mcp_server.py:458`, `:465`, `:474`, `:486` (the four tools) and `:427-451`
(`_code_answer`).

Two halves, both required:

1. `explain_path_tool`, `blast_radius_tool`, `exception_path_tool` and `history_tool` now
   read `with _answering(), _code_graph(ctx, principal) as (index, theta):`. `_answering()`
   wraps *outside* `_code_graph`, so it sees everything `query_session` does on acquisition
   (`ctx.store.get_settings()`, `validate_settings`, `query_access`, `ctx.graph_for`) and on
   release (`validate_live()`). This is the half that was a real leak: anything the store
   driver or the graph loader raised went out with its own text, and mcp 2.1.1 logs a
   non-`ToolError` with `logger.exception`, so it reached the server log too.
2. `_code_answer` is nested exactly as the reviewer prototyped: outer `try` maps, inner
   `finally` validates on both exits. Both `validate()` calls are now inside the mapper.

Ordering the nesting gives, all pinned: an ambiguous or unknown symbol keeps its own text;
a denial mid-answer outranks a partly built answer; a `ToolError` the inner handler already
built correctly is no longer swallowed by the `finally`; and a build failure with a valid
view still reads as its own mapped code rather than being masked by the denial.

Tests, all in `tests/unit/test_managed_transport_activation.py`:

- `test_mcp_code_tool_session_acquisition_failure_is_a_stable_code` — parametrised over all
  four tools; `ctx.graph_for` raises `OllamaError(POISON)`; asserts
  `retrieval_unavailable: Retrieval service is unavailable` and `assert_clean`. This is the
  leak the review says nothing covered. **Note:** `poisoned()` cannot be used here — the code
  tools never call a model, which `test_lookup_snapshot_lifetime.py` separately asserts — so
  the injection is at the acquisition point instead.
- `test_mcp_code_tool_denial_before_the_build_reads_as_the_shared_denial` — four tools; the
  epoch moves after the view is acquired, so the *leading* `validate()` is what raises.
- `test_mcp_code_tool_denial_outranks_a_mapped_build_failure` — the build fails on a poisoned
  `OllamaError` *and* the epoch moves. Before, the mapped `ToolError` was replaced by a raw
  `AuthorizationChanged`; now the caller gets the denial.
- `test_mcp_code_tool_build_failure_survives_a_view_that_is_still_valid` — the converse: a
  denial does not win by default.
- `test_mcp_code_tool_ambiguity_still_carries_its_candidates` — the carve-out survives.

Test updates outside this file, both named in the brief:

- `tests/unit/test_lookup_snapshot_lifetime.py:134-142` — the `revoke`/`mcp_path` case is split
  out of the shared `else` and asserts `ToolError` equal to the denial.
  `assert len(acquired) == 1` and `assert not live_refs(ctx)` still hold on that path:
  `query_session.__exit__` releases the snapshot before the mapped `ToolError` surfaces.
  The `surface="path"` (HTTP) case is untouched and still expects a raw
  `AuthorizationChanged`, because `web/app.py` registers the handler that renders it 409.
- `tests/unit/test_graph_surface_access.py:189` — the MCP half of
  `test_code_path_surfaces_validate_error_output` (four cases) now asserts the denial
  **and** `"PRIVATE SYMBOL" not in str(...)`, which is what the HTTP half has always
  asserted. The redaction this test exists to prove used to hold only as a side effect of
  the bug. The now-unused `AuthorizationChanged` import was removed.

### F1 second half (major) — `remote.py` printed a code-less body

`src/hippo/remote.py:131-154` (`_refusal`), module docstring `:14-30`.

**Deviation from the brief, authorised.** The brief's decision was to print the fixed
sentence for *any* code-less body. I raised this as BLOCKED before implementing: two
behaviors pinned in `test_cli.py`'s `remote` parametrisation go through code-less 4xx
bodies — `/api/code` answers `HTTPException(404, str(UnknownSymbol))` and
`HTTPException(400, "a is required")`, both rendered by FastAPI as a bare `detail`. Under
the literal rule, `hippo blast no_such_thing` behind a server would print
`operation_failed: ...` while the same command in-process names the symbol, so the two
branches of one command would stop agreeing and the user would lose the only actionable
fact. The orchestrator ruled **(B)**, the review's own F1 proposal: keep `detail` on a
**4xx** only, never fall back to `error`, fixed sentence plus status for every 5xx and
every unparseable body. That is what is implemented.

So `_refusal` now reads, in order: `code` + `error` → `f"{code}: {message}"` (no URL, no
status — the condition is the answer); a non-empty string `detail` on a status < 500 → that
detail alone (dropping the `{base_url}{path}: {status}` prefix the old code printed, so the
remote branch renders identically to the local one); everything else →
`f"{OPERATION_FAILED.code}: {OPERATION_FAILED.message} (HTTP {status})"`.

Both docstrings were false as written and are rewritten: the module's "Nothing else from
the body travels" and `_refusal`'s "Without one the route is a legacy validator".

Tests: `test_remote_client_never_prints_a_code_less_server_error` (502/500/503 with
`json={"error": POISON}` — the parseable body that leaked, which the existing
`test_remote_client_never_dumps_a_response_body` missed because a `text=` body exercises
only the unparseable branch); `test_remote_client_never_prints_a_code_less_error_key_on_a_4xx_either`;
`test_remote_client_keeps_a_legacy_validators_bounded_detail_on_a_4xx`;
and `test_remote_client_never_dumps_a_response_body` extended to pin the exact sentence.

**Not closed here:** F1's root cause is `web/routes/api.py:95` and `:115` returning
`{"error": str(exc)}` with no code for an `OllamaError`. That is 4b's file. The brief says
4b-i (`2377f7c`) already fixes it; this change is the independent second half and holds
whether or not that lands.

### F3 (major) — `hippo index` printed the legacy lane's `str(exc)`

`src/hippo/cli.py:354`, `:635` and the new `_stored_error` at `:359-380`; constant
`INDEXING_FAILED` at `:80`.

A stored `error` is printed unchanged only when its leading token is one of the closed
codes `managed_activation.record_build_failure` can store — tested with
`public_failure_for_code(code) is not None or code == DENIED_CODE`, the second disjunct
because `authorization_changed` is the one closed code the public table maps to `None` on
purpose. Anything else — the legacy lane's `f"{type(err).__name__}: {err}"` — becomes
`indexing failed; inspect local logs for source <id>`. Type names are CamelCase and codes
are snake_case, so the two vocabularies cannot collide.

Applied at **both** print sites: `cmd_index` (local) and `_index_remotely` (behind a running
server, `cli.py:635`). The second is the reviewer's finding applied consistently rather than
a separate one — the server's Source row is the same row with the same two lanes in it.

Tests: `test_cli_index_never_prints_an_unclosed_stored_error` (a legacy
`OllamaError: <POISON>` row, asserting the fixed sentence and `assert_clean`), and
`test_cli_index_prints_a_closed_stored_error_unchanged` parametrised over
`model_unavailable`, `retrieval_rebuild_required` and `authorization_changed`. The existing
`test_a_gated_local_index_really_reaches_the_managed_lane` still pins the managed half
verbatim and is untouched.

**Corrects evidence-pa4c deviation 5**, which reads "already closed" but checked only the
managed lane. The durable fix — the legacy lane not storing `str(err)` at
`ingest/pipeline.py:309` — is Task 3b's file and is not touched here.

### F4 (major) — gated `hippo index` published to everyone and left its creator unable to manage it

`src/hippo/cli.py:328-345`.

`cmd_index` now passes the identity it already resolved: `owner_id=principal.user_id` and
`access_role_id=None if principal.is_open else principal.role_id` — exactly
`remember_tool`'s rule. Open mode keeps `None`/`None`, so
`test_open_mode_local_index_preserves_legacy_indexing` is unchanged and still passes.

**Scope note:** applied to `add_repo` as well as `add_upload`. The review's proposal named
`add_upload` only, but `add_repo` takes the same two keyword arguments, the decision says
"gated `hippo index`" without qualifying the target, and a git URL indexed by a low tier
discloses exactly as much as a file does.

**Reconciliation with the brief's test phrasing.** The brief asks for "a higher-tier reader
of another role cannot see it". That is inverted relative to the model: `access_role_id` is
the *lowest* role that may see a source (`hippo_remember`'s own wording: "by default your own
tier and above"), `min_rank` is that role's rank, and `Access.can_see_source` admits
`min_rank <= rank`. `hippo users` states the same ladder: "a tier sees itself and every tier
below". So a higher tier *does* see it, by design, and what the fix actually buys is that a
tier *below* the creator no longer does. The test asserts the invariant the model enforces,
which is also what the review's `/tmp/pa4c_probe6.py` measured.

`test_a_gated_local_index_is_owned_by_its_creator_and_kept_to_their_tier`: a
`local-assistant` (rank 10) indexes a file; the row carries `owner_id == creator["id"]` and
`min_rank == 10`; the creator satisfies `may_manage_source` (they could not before — they
hold `add_sources` but not `manage_sources`, so ownership is the only thing that lets them
delete it) and `can_see_source`; an `individual` (rank 0) satisfies neither.

### F6 (medium) — one denial sentence and one code on all three surfaces

`src/hippo/mcp_server.py:166-176`, `:190`; `src/hippo/cli.py:69-75`, `:204-211`.

`mcp_server.DENIED` and `cli.DENIED` are now exactly **`Permissions changed; repeat the
query`** — the web app's own 409 sentence — and both modules gained
`DENIED_CODE = "authorization_changed"`, the managed lane's own stable name for the same
event. The rendered line is therefore:

- MCP: `ToolError("authorization_changed: Permissions changed; repeat the query")`
- CLI: `error: authorization_changed: Permissions changed; repeat the query`
- remote CLI: the same string, via `_refusal`'s `code` + `error` branch, once 4b-i's
  `{"error": "Permissions changed; repeat the query", "code": "authorization_changed"}`
  body lands. The test injects exactly that body rather than waiting for the merge.

**`public_errors.py` was NOT changed for this.** The brief allowed one constant there if
needed; it is not needed, and `cli.py` deliberately keeps `knowledge` out of its top-level
imports, so both modules hold their own `DENIED_CODE` with a cross-reference comment, the
way they already held `DENIED`.

**Wording conflict between F2 and F6, resolved.** The brief's F2 says the updated MCP test
branches should assert a message equal to `mcp_server.DENIED`; F6 makes the message
`code: DENIED`. F6 is the later and explicit decision ("carry the code ... on MCP
(`ToolError("authorization_changed: Permissions changed; repeat the query")`)"), so the
assertions compare against `f"{mcp_server.DENIED_CODE}: {mcp_server.DENIED}"`. The
cross-surface test pins the literal string rather than the constants, so it cannot pass by
self-reference.

`test_an_authorization_change_reads_the_same_on_both_surfaces` is renamed
`..._on_all_three_surfaces` and extended with the remote client; the four other assertions
against `mcp_server.DENIED` (two in `test_graph_surface_access.py`, both in `test_mcp_*`
tests, one in `test_lookup_snapshot_lifetime.py`, one here) are updated. A repo-wide grep
for `DENIED` and for the old sentence found no other reader, in `src/`, `tests/` or `docs/`.

New: `test_a_code_tool_denial_reads_the_same_on_both_surfaces` — the contract pinned on a
code tool (`explain_path_tool` and `hippo path`), where 4c had pinned it for `ask_tool`
alone.

### F5 (medium) — a bare `ValueError` read one way over MCP and another on the CLI

`src/hippo/cli.py:225-232`.

`_refusal` gained the same exact-type branch `tool_failure` has, placed after
`public_failure` so the two modules resolve a given exception identically: an exact-type
`ValueError` keeps the validator's own bounded text; everything else an evidence command
raises is `operation_failed`. The exact-type check (not `isinstance`) is load-bearing —
`ReadError`, `TooLarge`, `ManagedDispatchError` and `ProjectionError` are all `ValueError`
subclasses.

Tests: `test_a_closed_validators_own_text_reads_the_same_on_both_surfaces` (the upload-limit
sentence from the review's `/tmp/pa4c_probe3.py`, asserted identical on MCP and the CLI) and
`test_a_value_error_subclass_is_still_operation_failed_on_both_surfaces` (`ProjectionError`
with a poisoned message → `operation_failed` on both, `assert_clean`).

The review's better option — `pipeline`'s two validators raising `TooLarge`/`ReadError` so
both surfaces render `invalid_source` through the table — is `ingest/pipeline.py`, Task 3b's
file, and is not touched here.

### F7 (low) — MCP `hippo_sources` did not validate its view

`src/hippo/mcp_server.py:539-562`. `sources_tool` binds the comprehension to `rows`, calls
`view.validate()`, then returns — the order `_sources_locally` uses. The gap was narrow but
real: `source_view` keeps its own `authorization_epoch` comparison (`status.py:53`) that the
session's exit check never runs.

`test_mcp_source_listing_validates_its_view_like_the_cli` wraps the view's `validate` and
asserts it was called exactly once with the rows already built. A revocation test would not
have been a real RED here — the session's own exit check would deny anyway — so the call
itself is what is pinned.

### F8 (low) — `RemoteAmbiguous` could carry an empty message

`src/hippo/remote.py:45-47` (`AMBIGUOUS`), `:124-127`. A 409 carrying `candidates` but
neither text key now falls back to `that name could mean several things`, so
`cli.main:167` never prints a bare `error:` above the list.
`test_remote_ambiguity_is_never_an_empty_line` pins it. Latent today — `/api/code` always
sends `detail`.

### F9 (low) — `cli._refusal`'s docstring contradicted its own branch ordering

`src/hippo/cli.py:195-224`. **Docstring fixed, branch left where it is** — the alternative
the reviewer offered, and the deliberate choice of the two. Moving the
`AuthorizationChanged` check below the `EVIDENCE_COMMANDS` guard would make an
administrative command answer a permission change with a traceback, which is the opposite
of what F6 asks for one section earlier. The docstring now says the mapping is deliberate
for every command and names `cmd_settings` growing a capability check as the case it is
there for. The reviewer's second observation is recorded too: the two modules order the same
table differently and agree only because `AuthorizationChanged` appears in no row of the
public table, so if it ever gains one they have to be re-read together.

## Addendum from Task 3b: the tenth managed failure code

Routed mid-task by the orchestrator, with ownership of `public_errors.py` granted for it.

**Verified before acting.** `wp/pa3b` (merged to `rag-it-all-tibs` as `640d20b`) added
`_REBUILD_CODE = "retrieval_rebuild_required"` to `managed_activation.FAILURES`, reading
`EmbeddingProfileMismatch` and `EmbeddingProfileChanged` ahead of the wider `OllamaError`
row — and did **not** add the matching key to `public_errors._MANAGED_CODES`. The gap is
real: a Source row storing `retrieval_rebuild_required: ...` fell through to `None`, and
its caller's `or OPERATION_FAILED` turned a 409 "reindex this source" into a 500 "look in
the logs" — the wrong instruction as well as the wrong status.

`src/hippo/knowledge/public_errors.py:128-150`: the row
`"retrieval_rebuild_required": REBUILD_REQUIRED` is added, making the round trip an
identity. The comment above the table asserted the exact opposite of what 3b made true
("a build that failed on `EmbeddingProfileMismatch` ... is stored as `model_unavailable`")
and is rewritten.

This also mattered for F3: without the row, a stored rebuild code would have failed
`_stored_error`'s closed-shape check and been replaced by the fixed sentence.

**Ownership note:** the test went into `tests/unit/test_public_errors.py`, which is not in
this brief's owned list. The addendum said "with a test" and that file is the only sensible
home — it already holds the local `MANAGED_CODES` mirror and the pairing test. Three edits
there: the new key, two rows in `test_a_stored_code_and_its_own_exception_agree`
(`EmbeddingProfileMismatch` and `EmbeddingProfileChanged`), and "These nine" → "These ten"
with a sentence on where the tenth came from. Reported via `horch note`.

## Deviations from the brief, in one place

1. **F1 second half** — implemented as option (B) (keep `detail` on a 4xx), not the brief's
   literal rule. Raised as BLOCKED before implementing; ruled by the orchestrator. Full
   reasoning under F1 above.
2. **F4** — applied to `add_repo` as well as `add_upload`; and the brief's "a higher-tier
   reader cannot see it" is inverted relative to the access model, so the test asserts what
   the model enforces (a tier *below* the creator cannot see it). Reasoning under F4.
3. **F6** — no constant added to `public_errors.py`; it was not needed. The brief permitted
   one.
4. **F9** — docstring amended rather than the branch moved; the brief allowed either.
5. **F3** — also applied to `_index_remotely`, the second print site of the same stored
   string, which the review did not name.
6. **Not in the brief:** a top-level `public_errors` import I first added to `remote.py`
   pulled the whole ingest stack into `hippo.cli`'s import graph (488 → 547 modules, and
   `hippo.ingest.pipeline` imported for `hippo --help`). Caught by measuring against the
   committed base and made a per-call import, which is what `cli.py` already does for the
   same reason. Back to 488 modules exactly, and `fastapi` still absent.

## Merge order: 4b-i must land before or with this branch

`git merge-base --is-ancestor 2377f7c rag-it-all-tibs` answers **NOT-YET** as of this
writing, so stating it once rather than leaving it to be discovered.

On `be6062a`, `web/app.py:72` still answers a denial as
`409 {"error": "Permissions changed; repeat the query"}` with **no** `code`. `_refusal` now
refuses a code-less `error` whatever the status, which is the ruling, so in the gap between
these two branches a *remote* CLI denial reads
`operation_failed: Operation failed; inspect local logs by operation ID (HTTP 409)` — bounded
and honest, but less useful than the pre-fix `http://server/api/ask: 409 Permissions
changed; repeat the query`. The moment 4b-i's body carries the code, the same condition reads
`authorization_changed: Permissions changed; repeat the query` on all three surfaces, which
is the point of F6.

The brief accepted this by construction ("after 4b-i merges, `web/app.py`'s 409 body becomes
... Your remote-client change must consume exactly that"), and the cross-surface test injects
that body directly rather than waiting for the merge, so nothing here is red. It is a
sequencing fact, not a defect: merge 4b-i before or together with `wp/pa4cfix`. The MCP and
local-CLI denials are unaffected either way — they never went through `web/app.py`.

## Not closed here (other slices' files)

- `web/routes/api.py:95`, `:115` — F1's root cause, the code-less 502. Task 4b.
- `web/app.py:71-72` — F6's clean fix, the 409 body carrying the code. Task 4b-i, per the
  brief already done at `2377f7c`.
- `ingest/pipeline.py:309` — F3's durable fix, the legacy lane storing `str(err)`. Task 3b.
- `ingest/pipeline.py:146`, `:216-221` — F5's better option, the two validators raising
  `TooLarge`/`ReadError`. Task 3b.
