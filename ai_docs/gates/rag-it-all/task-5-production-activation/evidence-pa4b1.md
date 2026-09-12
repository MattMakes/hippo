# Evidence: activation Task 4b-i — web ingress actors, safe failures and route sessions

Branch `wp/pa4b1`, worktree `.worktrees/pa4b1`. Base `rag-it-all-tibs` `957fc35` (the hash the
orchestrator assigned, not the `1acf069` printed in the brief), then **fast-forwarded to `da51784`**
under a one-time merge authorization; see "The blocker at the base" below.
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, `mcp` pinned to 2.1.1 per the rulebook.

Commits:

| Hash | Subject |
|---|---|
| `2377f7c` | Say one closed thing about a failed query instead of its own words |
| `d27321f` | Let every web ingress bring the reader who actually asked |

Merge recorded for this branch: `git merge rag-it-all-tibs` fast-forwarded `957fc35 → da51784`
(`Import the managed lane lazily so knowledge modules load first`). No other branch was merged.

Files created: `tests/unit/test_managed_web_ingress.py`, this file.
Files modified: `src/hippo/web/app.py`, `src/hippo/web/auth.py`, `src/hippo/web/routes/api.py`,
`src/hippo/web/routes/pages.py`, `src/hippo/web/routes/sources.py`, `tests/unit/test_web_base.py`,
`tests/unit/test_query_session.py` (the last one under an explicit one-change authorization,
deviation 2).

Nothing under `src/hippo/web/routes/{analyze,code,graph}.py`, `web/render.py`, `status.py`,
`mcp_server.py`, `cli.py`, `remote.py`, `analysis/`, `evals/`, `eval_access.py`,
`changeset_access.py`, `knowledge/` (other than reading `public_errors`), `ingest/`, `store/`,
`context.py`, the shared `GATES.md`, `docs/` or the checkpoint was touched.

## The blocker at the base, and the merge

At the assigned base `957fc35` every web test file failed to **collect**: importing
`hippo.knowledge.dense_session` (and therefore `hippo.web.app`) raised

```
ImportError: cannot import name 'MANIFEST_EXTERNAL_ID' from partially initialized module
'hippo.knowledge.generation_profiles' (most likely due to a circular import)
```

through `knowledge.dense_session → generation_profiles → input_binding → hippo.ingest/__init__ →
pipeline → managed_activation → prose_generation → generation_profiles`. Reproduced both in a clean
worktree venv and with the root venv pointed at `957fc35`'s `src`, so it was the branch, not the
environment: baseline run `/tmp/hippo-pa4b1-baseline.log` showed **6 collection errors**
(`test_web_base`, `test_web_auth`, `test_web_busy_pages`, `test_web_library_evals`,
`test_account_snapshot_lifetime`, `test_inventory_snapshot_lifetime`). `ingest/pipeline.py` is on
this slice's do-not-touch list, so the orchestrator was asked rather than patched around; the answer
was the one-time merge of `da51784`, which makes `pipeline.py` reach the managed lane through a lazy
`_managed()` accessor and adds `tests/unit/test_import_order.py` as a guard. That guard is included
in the GREEN run below, because this slice adds a new import edge
(`web/auth.py → knowledge.build_authority`).

## What the slice does

1. **`web/auth.py::build_actor_of(principal) -> BuildActor | None`** — the one place a web route
   turns the identity a request already proved into a build actor. A real reader gets
   `BuildActor.reader(principal)`; an open-mode or preview identity gets `None`, which is the
   dispatch table's "no actor" column and therefore the legacy lane for a *new* source, while
   `plan_dispatch` still refuses them before touching an *existing* managed one.
   `BuildActor.trusted_local()` is not reachable from web code.
2. **`web/routes/sources.py`** — `new_managed_source()` is `new_source_access()` plus that actor, and
   the four ingress routes for pasted text and uploads use it (`POST /sources/text`,
   `POST /sources/upload`, `POST /api/sources/text`, `POST /api/sources/upload`). `add_repo` and
   `add_sample` keep taking no actor at all. `POST /api/sources/{id}/reindex` passes the principal
   `manageable_source` just authorized. The unsupported families stay legacy without the route
   deciding anything: the actor is handed over unconditionally and the pipeline's closed eligibility
   predicate refuses to convert a `.pdf`, a `.py`, a zip, a repo or the sample.
3. **`reindex_all` holds one owner** across `source_view`, the pipeline call and the post-operation
   validate. It used to validate a view it had already released and then acquire a second one
   (audit row: "`reindex_all` … validates a view it does not hold").
4. **The delete retry says only 404.** `AuthorizationChanged` out of `pipeline.delete_source` becomes
   `HTTPException(404, "no such source")` — the same answer as any unavailable source, so a reader
   retrying their own delete cannot learn that a tombstoned source is still there (plan: "A retry
   must not disclose whether an inaccessible/tombstoned source exists").
5. **Closed public codes on the JSON and HTML query paths.** `web/app.py` registers
   `public_failure_page` for `OllamaError`, `DenseUnavailable`, `ProjectionError`,
   `ManagedDispatchError` and `httpx.TransportError`; `web/routes/api.py` shapes its own for
   `/api/ask` and `/api/search`; `web/routes/pages.py::failure_text` does the HTML fragment. The body
   is the contract the orchestrator fixed with 4b-ii: `{"error": failure.message, "code":
   failure.code}` at `failure.http_status`. The old fixed `502` for `OllamaError` is gone (no test
   asserted it; `retrieval_unavailable` is 503).
6. **`ManagedActorRequired` is a permission answer, not a failure report** — registered to the
   existing `authorization_changed` handler, so its body stays exactly
   `{"error": "Permissions changed; repeat the query"}` at 409, which
   `test_query_authorization_boundary.py`, `test_render_authorization.py` and
   `test_graph_surface_access.py` all assert verbatim. Starlette resolves a handler by walking the
   exception's own MRO, so this row wins over the broader `ManagedDispatchError` one.
7. **Logging is bounded.** `pages.py` no longer calls `log.exception("ask failed")`, which wrote the
   traceback — and therefore `str(exc)` — at ERROR. It logs `type(exc).__name__` at WARNING and the
   exception only at DEBUG, so a capture at public level holds nothing private.

## Commands and results

All runs used the standard invocation with the log captured, never piped to `tail`.

| # | Command | Result | Log |
|---|---|---|---|
| 0 | Baseline at `957fc35`, my files with form (b): `HIPPO_TEST_STORE=fake .venv/bin/pytest <9 files> -q -o addopts='' -p no:cacheprovider -W error -W "ignore:…BlockingPortal…"` | **6 collection errors** (the import cycle) | `/tmp/hippo-pa4b1-baseline.log` |
| 0b | Same command after the `da51784` fast-forward | **1 failed, 111 passed** — exactly `test_web_auth.py::test_graph_page_and_its_endpoints_are_scoped_and_previewable`, which is pa4a breakage row **A / `test_web_auth.py`** | `/tmp/hippo-pa4b1-baseline.log` |
| 1 | RED: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_web_ingress.py -q -o addopts='' -p no:cacheprovider -W error -W "ignore:…BlockingPortal…"` | **44 failed, 11 passed, 2 skipped** | `/tmp/hippo-pa4b1-red.log` |
| 2 | GREEN, the new file alone | **55 passed, 2 skipped** | `/tmp/hippo-pa4b1-green1.log` |
| 3 | GREEN Fake, owned + adjacent (14 files, listed below) | **258 passed, 2 skipped, 2 failed — both in files this slice does not own** | `/tmp/hippo-pa4b1-fake-green.log` |
| 4 | Regression sweep over the other slices' route/analysis files (16 files) | **282 passed, 20 failed — and the 20 are exactly the 20 pa4a breakage rows for those files, so this slice adds no new failure** | `/tmp/hippo-pa4b1-adjacent.log` |
| 5 | GREEN Ladybug: `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_web_ingress.py tests/unit/test_web_base.py tests/unit/test_web_auth.py tests/unit/test_account_snapshot_lifetime.py tests/unit/test_inventory_snapshot_lifetime.py tests/unit/test_source_snapshot_lifetime.py -q -o addopts='' -p no:cacheprovider -W error -W "ignore:…BlockingPortal…"` | see "Ladybug result" | `/tmp/hippo-pa4b1-ladybug-green.log` |
| 6 | `.venv/bin/ruff check <8 changed files> && .venv/bin/ruff format --check <8 changed files>` | All checks passed; 8 files already formatted | — |

Run 3's files: `test_managed_web_ingress.py`, `test_web_base.py`, `test_web_auth.py`,
`test_web_busy_pages.py`, `test_web_library_evals.py`, `test_web_security.py`,
`test_account_snapshot_lifetime.py`, `test_inventory_snapshot_lifetime.py`,
`test_source_snapshot_lifetime.py`, `test_settings_and_safety.py`,
`test_managed_route_activation.py`, `test_query_session.py`, `test_status_access.py`,
`test_import_order.py`.

Run 3's two failures, neither owned here and both already on the pa4a table:

| Test | Row | Owner |
|---|---|---|
| `test_web_auth.py::test_graph_page_and_its_endpoints_are_scoped_and_previewable` | A | `web/routes/graph.py:328` `light_up` → `retrieval_session`, **4b-ii** |
| `test_status_access.py::test_status_route_and_page_header_pass_the_request_audience` | C | `assert_called_with(..., structural=True)`, **4b-ii** |

Run 4's 20, by file, against the pa4a table: `test_analysis_snapshot_lifetime.py` 7 (6 in row A + 1
in row B), `test_answer_original_citations.py` 4 (row B), `test_web_analyze.py` 4 (row A),
`test_graph_surface_access.py` 2 (row A), `test_dense_session.py` 1 (row C),
`test_query_authorization_boundary.py` 1 (row D), `test_rag_replay_access.py` 1 (row A). Table total
for those files: 20. Observed: 20, same names.

AnyIO warning handling: **form (b)** on the command line for every run, because
`test_managed_web_ingress.py`, `test_web_base.py` and `test_web_auth.py` import
`fastapi.testclient` at module level and the warning therefore fires at collection, where no marker
can catch it. No per-test marker was added and no ini-wide `filterwarnings` exists. Any gate CHECK
line that includes `tests/unit/test_managed_web_ingress.py` must carry form (b).

## Test files: owned versus run

The brief named `test_web_sources.py`, `test_web_users.py` and `test_web_pages.py`; `ls tests/unit |
rg web` shows that **none of the three exists**. The coverage for those routes lives elsewhere, so
the claim is narrow:

- **Owned and modified:** NEW `tests/unit/test_managed_web_ingress.py`, `tests/unit/test_web_base.py`,
  `tests/unit/test_query_session.py` (one authorized change, deviation 2).
- **Run, unmodified, green:** `test_web_auth.py` (one pre-existing red, 4b-ii's),
  `test_web_busy_pages.py`, `test_web_library_evals.py`, `test_web_security.py`,
  `test_settings_and_safety.py`, and the three route session-lifetime files
  `test_account_snapshot_lifetime.py`, `test_inventory_snapshot_lifetime.py`,
  `test_source_snapshot_lifetime.py`. The last three are the existing per-route ownership tests for
  `sources.py`, `users.py` and `auth.py`; they needed no change, which is itself the confirmation
  the audit asked for.

## Audit rows converted or confirmed (22)

Every row tagged 4b whose file is one of this slice's six. "Confirmed" means the row needed no edit
because the 4a default flip already made its `query_session(ctx, access)` structural and the route
already held exactly one owner through DTO/render/save — proven by
`test_each_route_acquires_exactly_one_graph_for_its_response`, not by reading.

| Row | Symbol | Class | Outcome |
|---|---|---|---|
| `api.py:78` | `ask` | model/dense | **converted**: holds the structural owner, maps failures; the inner `ask` re-wraps with `retrieval_session` since 4a |
| `api.py:104` | `search` | model/dense | **converted**, same shape |
| `pages.py:111` | `ask_submit` | model/dense | **converted**: `str(exc)` for `OllamaError` replaced by the closed table |
| `api.py:129`, `api.py:150` | `entities`, `neighborhood` | graph-only | confirmed |
| `pages.py:90` | `ask_page` | graph-only | confirmed |
| `sources.py:69` | `library` | graph-only | confirmed (and the ping-down branch still lets render own the header view) |
| `sources.py:94` | `sources_partial` | graph-only | confirmed |
| `sources.py:125` | `visible_source` | graph-only | confirmed: borrows a caller's session, owns one only when none was given |
| `sources.py:148` | `source_page` | graph-only | confirmed |
| `sources.py:236` | `code_details_for` | graph-only | confirmed: borrows |
| `sources.py:290` | `source_status_partial` | graph-only | confirmed |
| `sources.py:438` | `list_sources` | graph-only | confirmed |
| `sources.py` `reindex_all` | (no session) | graph-only | **converted**: one held owner across the pipeline call and the post-operation validate |
| `users.py:88` | `ladder` | graph-only | confirmed: borrows the page's view |
| `users.py:119` | `users_page` | graph-only | confirmed |
| `users.py:289`, `:300` | `list_users`, `list_roles` | graph-only | confirmed |
| `users.py:364`, `:435` | `patch_user`, `patch_role` | graph-only | confirmed, deliberately (deviation 1) |
| `auth.py:331` | `account_page` | graph-only | confirmed |
| `auth.py:384` | `me` | graph-only | confirmed |

Rows tagged 4b that are **not** this slice's files and were not touched: `status.py:46`,
`status.py:242`, `render.py:89`, `graph.py:{145,190,328,418}`, `code.py:182`,
`analyze.py:{55,108,233,270}`, `changeset_access.py:{49,70,170}`.

## Breakage-table rows fixed

Of the 36 rows in `evidence-pa4a.md` "Breakage for 4b/4c/4d", exactly one names a test file this
slice owns, and it is **not fixable here**: row **A / `tests/unit/test_web_auth.py`**
(`test_graph_page_and_its_endpoints_are_scoped_and_previewable`) fails because
`POST /api/graph/light-up` returns an error body, and its production owner is
`web/routes/graph.py:328`, which the brief puts under do-not-touch (4b-ii owns it). It is red at
this slice's clean base too (run 0b). It will go green when 4b-ii converts `light_up` to
`retrieval_session`; nothing in this slice can close it, and the failure shape is unchanged by this
slice (the body is now a 409 `retrieval_rebuild_required` instead of a 400, and the test still stops
at `KeyError: 'seeds'`).

No other breakage row names a file owned here.

## New behaviour pinned (`test_managed_web_ingress.py`, 55 passed / 2 skipped)

- The actor at each of the four ingress routes, and that it is a `reader` for the right user id.
- Open mode keeps the legacy lane at all four routes; `build_actor_of` returns `None` for
  `Principal.open()` and for a role preview, and the reader actor for a real reader.
- `BuildActor.trusted_local` is monkeypatched to fail the test if web code ever calls it.
- `.pdf`, `.py` and a zip stay legacy *with* an actor present, and a claimed `text/markdown`
  content type does not change that; repo and sample stay legacy.
- A role without `add_sources` is refused 403 before any actor exists.
- A real bootstrap over HTTP through the MockTransport model publishes a managed generation
  (`managed`, `active_generation_id`, `ready/ready`) and the source appears in `/api/sources`.
- `reindex` carries the authorized manager's actor.
- Every closed code on `/api/ask` and `/api/search` and in the HTML fragment, for
  `OllamaError`, `DenseUnavailable` and an unknown `RuntimeError`; a failure no route caught mapped
  by `app.py`; `ManagedActorRequired` as the permission response; the delete retry as 404; and the
  legacy validation messages (body-model bound, settings validator, git-URL) unchanged.
- **Redaction:** a poison string carrying a fake token, an absolute path, source text and a model
  reply body is injected into the managed background lane and into both query lanes, and none of the
  four fragments reaches any JSON body, HTML body, response header, the Source row, or `caplog`
  captured at `INFO`.
- One acquisition per response for twelve route patterns, with no live `SnapshotReference` left.
- A revocation between the DTO and the response is the existing 409 for eleven of them.
- One owner held across the bulk reindex, proven by counting acquisitions *and* releases at the
  moment of the pipeline call, not by counting afterwards.

## Deviations and decisions

1. **A mutation route acquires twice on purpose, and that is not the banned pattern.**
   `set_access`, `patch_user`, `patch_role` and `delete_user` authorize, mutate, then build the DTO
   they return. `store.set_source_access` / `create_user` / `update_user` are
   `permission_mutation`s, so they bump the authorization epoch; a single session held across one of
   them would raise `AuthorizationChanged` out of `query_session`'s own exit-time `validate_live()`
   and turn every successful mutation into a 409. The pattern the plan forbids — "a graph or profile
   preflight, closes it, then reacquires" — is about retrieving the same evidence twice; here the
   second acquisition exists because the first proof was deliberately invalidated. The audit already
   blesses this shape for `patch_user`/`patch_role` ("Mutation, but the session exists for the
   source/user view it returns"). Confirmed, not converted.
2. **`tests/unit/test_query_session.py` is not this slice's file; two rows were changed under an
   explicit authorization.** Mapping an unknown query exception to `operation_failed` means
   `/api/ask` and `/api/search` no longer *propagate* a `RuntimeError`, so
   `test_model_failure_releases_graph_and_revocation_wins[False-http_ask]` and `[False-http_search]`
   stopped raising. Asked the orchestrator; answered: edit exactly those two rows to assert the
   mapped 500 body and keep `len(acquired) == 1 and released == acquired`. Done that way; the
   `[True-*]` revoke rows are untouched and still prove that a revocation outranks the failure.
3. **The HTML fragment carries the code inside the sentence.** The answer partial renders one
   `error` string, and its template is not this slice's file, so `failure_text` returns
   `"<message> [<code>]"` rather than adding a second template variable. Same message and same code
   as the JSON body, which is what the agreed contract asks for; if 4b-ii's `render.py` helper grows
   a structured field, this becomes a one-line change.
4. **The caller's settings are validated before the session opens.** Both `validate_settings` and
   `GraphIndex.canonical_selected_generations` raise a bare `ValueError`, and they must answer
   differently (the first keeps "damping must be between 0.0 and 1.0", the second is
   `operation_failed` per pa4a decision 1). Nothing in the exception distinguishes them, so
   `api.py::checked_settings` validates the body's own numbers first; past that line a `ValueError`
   is never the request, so the mapping is unambiguous.
5. **`OllamaError` on `/api/ask` and `/api/search` is now 503, not 502.** The plan's table says
   `retrieval_unavailable` → 503 and the agreed contract says "no fixed 502". No test asserted 502
   (`rg -n 502 tests/unit/*.py` → nothing).
6. **The permission response gained no `code`.** The plan's row for an authorization change is
   "existing authorization response", and three test files outside this slice assert
   `{"error": "Permissions changed; repeat the query"}` exactly. Left byte-identical.
7. **`httpx.TransportError` is registered alongside the named families.** The model client is
   httpx, `public_failure` already maps `TransportError` to `retrieval_unavailable`, and an
   unwrapped connection error escaping a route is the one case that would otherwise reach a client
   as a traceback.
8. **The bulk-reindex ownership test uses a legacy corpus.** With a managed source, today's
   `reindex_all` refuses rather than clears (`ValueError: Managed source requires suppression and
   generation collection`) — the invariant working, and exactly what `wp/pa3b` replaces. The
   ownership question is lane-independent, so the test pins it on a legacy corpus and the managed
   bulk case belongs to the 3b follow-up.
9. **Left for the `wp/pa3b` merge** (the orchestrator had not announced "3b merged" by the time
   everything else was finished): `pipeline.delete_source` and `pipeline.reindex_all` do not yet
   accept `build_actor`, so the delete and bulk routes pass none.
   `test_deleting_brings_the_authorized_managers_actor` and
   `test_bulk_reindex_brings_the_bulk_managers_actor` are in place and **skipped** with that reason;
   unskipping them is the RED for that wiring. Nothing else in this slice depends on 3b.
10. **The managed Source row's `error` is still withheld, and rendering it stays 4b-ii's.** The
    redaction test pins that a background managed failure reaches no surface, which holds because 3a
    stores a bounded code and Task 2 withholds `error` on managed rows. Turning that stored code into
    a rendered sentence with `public_failure_for_code` belongs to `status.py`, which this slice must
    not touch; the consumer side is ready.
