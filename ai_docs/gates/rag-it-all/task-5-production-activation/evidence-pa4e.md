# Evidence: activation Task 4e — web wrap-up (one failure helper, exact 4xx catches, preview notice, legacy error bounding)

Branch `wp/pa4e`, worktree `.worktrees/pa4e`, base `rag-it-all-tibs` `0bc378c`
("Merge wp/pa4b1"), the HEAD named in the spawn message.
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, `mcp` pinned to 2.1.1 per the
rulebook. Store fixture always explicit (`HIPPO_TEST_STORE=fake` or `=ladybug`); no Neo4j
was used and none of the three Neo4j-only paths below was executed on that backend.

## Ownership granted during the slice

The brief's DECISIONS name two files that appear in neither FILES list. Both were asked for
by `horch tell` and granted in writing by the orchestrator before either was touched:

- `src/hippo/web/routes/sources.py`, **the reindex-all route body only**, for decision 5's
  `bulk_refused` 409 and the `ManagedActorRequired` mapping. The addendum later extended
  this to the seven JSON failure bodies (F3) and the two ingress catches (F5).
- `src/hippo/knowledge/projection.py`, **the two lines** that make `ProjectionError` the
  class defined in `hipporag/graph_index.py`, for decision 8's no-cycle fallback.

The addendum added `src/hippo/web/app.py` (F1, F4) and `src/hippo/web/routes/pages.py` (F2),
both named in it as mine.

Nothing under `evals/`, `analysis/`, `eval_access.py`, `mcp_server.py`, `cli.py`,
`remote.py`, `knowledge/access.py`, `docs/`, the checkpoint or `GATES.md` was touched.
`tests/unit/test_ingest_limits.py` was deliberately left untouched: see decision 4.

## Commits

| Hash | Subject |
|---|---|
| `629b1ae` | Let one exact validator type own every 4xx the web layer answers |
| `d746c7b` | Bound what a legacy failure and a refused bulk tell their callers |
| `38ad96c` | Answer a browser a page, and give every refusal a code to branch on |
| *(branch tip)* | Record what the Task 4 wrap-up closed and what it left |

The third commit is the mid-slice addendum (the 4b-i review's F1-F5, probes 5 and 6, and
the orchestrator's ruling on decision 4); see "Addendum" below.

Files touched (25 paths: 23 modified, 2 new):

- `src/hippo/hipporag/graph_index.py`, `src/hippo/knowledge/projection.py`,
  `src/hippo/knowledge/query_access.py`
- `src/hippo/web/app.py`, `src/hippo/web/render.py`,
  `src/hippo/web/routes/{api,code,graph,pages,sources}.py`,
  `src/hippo/web/templates/graph.html`, NEW `src/hippo/web/templates/failure.html`
- `src/hippo/ingest/{pipeline,managed_activation}.py`
- `src/hippo/store/{generations,memory,ladybug}.py`, `tests/fakes/fake_store.py`
- `tests/unit/test_{managed_web_surfaces,graph_surface_access,managed_web_ingress,
  ingest_pipeline,ingest_concurrency,managed_pipeline_activation}.py`
- NEW: this file.

`src/hippo/web/app.py` was not modified for decision 1 (nothing to do), but **is** modified
by the addendum's F1 and F4.

## Runs

AnyIO handling: **form (b)** on every command line below
(`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`),
because `test_managed_web_ingress.py`, `test_managed_web_surfaces.py`, `test_web_base.py`,
`test_web_code.py` and `test_graph_surface_access.py` all import `fastapi.testclient` at
module level. No marker was added anywhere and no ini-wide `filterwarnings` exists.

| # | What | Result | Log |
|---|---|---|---|
| 1 | **Baseline, Fake**, the ten files below, before any edit | **375 passed, 2 skipped, EXIT 0** | `/tmp/hippo-pa4e-baseline.log` |
| 2 | **RED, web** (decisions 2, 8) | 8 failed, 5 passed | `/tmp/hippo-pa4e-red-web.log` |
| 3 | **RED, decisions 3 and 6** | 3 failed (2 + 1) | `/tmp/hippo-pa4e-red-web2.log`, `-web3.log` |
| 4 | **RED, pipeline** (decisions 5, 7) | 6 failed, 1 passed | `/tmp/hippo-pa4e-red-pipeline.log` |
| 5 | **RED, decisions 4 and 5's route** | 2 failed, 3 passed | `/tmp/hippo-pa4e-red-pipeline2.log` |
| 6 | **RED, addendum** (F1-F5, probes 5-6) | 14 failed, 130 passed | `/tmp/hippo-pa4e-red-addendum.log` |
| 7 | **GREEN, addendum** | **174 passed, EXIT 0** | `/tmp/hippo-pa4e-green-addendum.log` |
| 8 | **GREEN, Fake**, the brief's set plus `test_ingest_limits.py` | **435 passed, 2 skipped, EXIT 0** | `/tmp/hippo-pa4e-fake-green.log` |
| 9 | **GREEN, whole Fake unit suite** (not asked for; run because this slice edits three store modules) | **3737 passed, 28 skipped, 1 failed** — the one failure PROVEN pre-existing at the base, residual 10 | `/tmp/hippo-pa4e-fake-full.log` |
| 10 | **GREEN, Ladybug** `test_managed_web_ingress.py test_managed_web_surfaces.py` | **144 passed, EXIT 0** in 805s | `/tmp/hippo-pa4e-ladybug-green.log` |

| 11 | **GREEN, Ladybug**, the restart sweep: `test_managed_pipeline_activation.py -k "interrupted or right_after_a_restart or reopen"` | **4 selected, 4 passed, 104 deselected, EXIT 0** | `/tmp/hippo-pa4e-ladybug-sweep.log` |

Run 11 is not in the brief. It is here because `release_interrupted_build` and the rewritten
`mark_interrupted_jobs` are the change with the least coverage, and
`test_an_interrupted_refresh_is_retired_by_the_next_ladybug_open` is the only place either
runs against a real backend's close/reopen.

Run 1 and run 8 are the same command over the same ten files (run 8 adds
`tests/unit/test_ingest_limits.py`, which decision 4 has to leave green):

```
HIPPO_TEST_STORE=fake .venv/bin/pytest \
  tests/unit/test_managed_web_ingress.py tests/unit/test_managed_web_surfaces.py \
  tests/unit/test_web_base.py tests/unit/test_web_code.py \
  tests/unit/test_ingest_pipeline.py tests/unit/test_graph_surface_access.py \
  tests/unit/test_managed_pipeline_activation.py tests/unit/test_ingest_concurrency.py \
  tests/unit/test_managed_route_activation.py tests/unit/test_status_access.py \
  -q -o addopts='' -W error \
  -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"
```

Baseline 375 → 435, and run 8 adds `test_ingest_limits.py` (9 tests, unchanged), so
**+51 tests added here** and no pre-existing test deleted. Counted the other way:
`test_managed_web_surfaces.py` +30, `test_managed_web_ingress.py` +9,
`test_managed_pipeline_activation.py` +7, `test_graph_surface_access.py` +3,
`test_ingest_pipeline.py` +2. Five pre-existing tests changed their assertions; each is
named under its decision below.

**Ruff:** `ruff check` and `ruff format --check` over all 22 changed `.py` files — **clean**
(`All checks passed!`, `22 files already formatted`). This file is prose with no fenced
Python block, so the CI Markdown Ruff job has nothing to format in it.

## What each decision does, and the test that holds it

### 1. One public-failure helper — already true at `0bc378c`, no change

`web/app.py` at the base already imports `public_failure_response` and `retrieval_failure`
from `web/render.py` (`app.py:30`); the 4b-i merge deduped the local copy. The 409 handler
already answers `{"error": "Permissions changed; repeat the query", "code":
"authorization_changed"}` (`app.py:109-112`). **Decision 1 itself therefore required no
change to `app.py`**, and `render.py` holds the only definition of both helpers. `app.py`
*is* modified later in the slice, by the addendum's F1 (Accept negotiation) and F4 (the
handler rename) — see "Addendum" below.

**Deviation from the brief's check.** The brief says a grep for `str(exc)` under
`src/hippo/web` "must find only the legacy settings validators (`api.py`
put_settings/checked_settings, `pages.py` settings form)". That is not achievable from this
slice's files and was not true at the base either. At `0bc378c` the grep found **24**
sites; after this slice it finds **25** (`render.py`'s new docstring adds one; `api.py` went
from two to one; `sources.py` stayed at seven, but every one of them is now inside a
`coded_response(...)` guarded by an exact-type check rather than a bare `JSONResponse`).

Full count after: `users.py` 7, `sources.py` 7, `code.py` 3 (two are the exact
`UnknownSymbol`/`AmbiguousSymbol` types the plan intends), `analyze.py` 2, `api.py` 1,
`evals.py` 1, `auth.py` 1, `pages.py` 1, `graph.py` 1, `render.py` 1 (prose).

The checkable part of the decision holds and is stronger than the count suggests: `app.py`
has no local helper, and **every** `str(exc)` this brief owns is now reached only through
an exact validator type — `api.py`'s one via `caller_error`, `code.py`'s three via
`caller_error`/`UnknownSymbol`/`AmbiguousSymbol`, `sources.py`'s seven via `caller_error`,
`RepoError` or `Busy`. What remains uncovered is `users.py`, `analyze.py`, `evals.py`,
`auth.py`, `pages.py` (the settings form the plan protects) and `graph.py:386` — see
residual 2.

### 2. Exact 4xx catches

New shared predicate `render.caller_error(exc)` — `type(exc) is ValueError` — with the
reason written where it lives. It is deliberately the **same rule** `mcp_server.tool_failure`
already applies (`mcp_server.py:188`), so a client moving between HTTP and MCP is told the
same thing by the same rule, and `mcp_server.py` (do NOT touch) needed no change.

Why exact type rather than "ask the closed table": `code.py:224` already re-raised anything
`public_failure()` knew, which covers `ReadError`, `TooLarge` and `ProjectionError` — the
three the brief names — but *not* the `ValueError` subclasses the table has no row for
(`RepoError`, `_StorageFailure`, `ManagedDispatchError`, `Busy`, `RawArtifactError`, …),
several of which name a path. The RED for `code.py` therefore uses `RepoError`, and the
observed failure was literally `{"detail":"/Users/someone/checkout/.git"}` at 400.

| Site | Before | After | Test |
|---|---|---|---|
| `code.py::_answer` | `except ValueError` → `HTTPException(400, str(exc))` unless the table knew it | `if not caller_error(exc): raise` → the view's own mapper | `test_a_code_payload_value_error_subclass_is_mapped_rather_than_printed_as_a_400` (RED: 400 with the path; GREEN: 500 `operation_failed`) |
| `api.py::put_settings` | `except ValueError` around `store.update_settings` | `checked_settings(changes)` first, then the write under `(ValueError, OllamaError, httpx.TransportError)` → `public_failure_response(retrieval_failure(exc))` | `test_a_settings_write_that_fails_is_mapped_rather_than_quoted_back_as_a_400[projection|read]` (RED: 400 with the path; GREEN: 500 `operation_failed` / 400 `invalid_source`) |
| `api.py::checked_settings` | `except ValueError` | `if not caller_error(exc): raise` | `test_a_settings_precheck_failure_that_is_not_the_validator_is_mapped[/api/ask|/api/search]` |

`put_settings` is safe to split because `store.update_settings` calls the *same*
`validate_settings` on the *same* dict (`store/base.py:290`), so nothing it raises past the
pre-check is the caller's mistake.

`checked_settings` moved **inside** `ask`/`search`'s mapped scope, with `except
HTTPException: raise` added ahead of the generic handler so its own 400 is not swallowed. It
still runs before `query_session`, which is the property its docstring depends on.

The 400 vocabulary is held by three regression tests that pass at both ends:
`test_a_blank_required_code_argument_is_still_the_callers_mistake` (`symbol is required`),
`test_an_invalid_setting_keeps_the_store_validators_own_sentence`, and
`test_a_callers_own_bad_setting_is_still_a_400_naming_it[/api/ask|/api/search]`.

### 3. Preview notice

`graph.py` gains `PREVIEW_NOTICE` and `managed_evidence_exists(ctx)`; `graph_page` passes
`preview_notice` and `graph.html` renders it in the page head under the existing subtitle.
**No change to `knowledge/access.py`** — preview audiences stay on legacy evidence for this
increment, exactly as the decision says.

The predicate is `managed_eligibility(source) == "managed" and source.get(
"active_generation_id")` over `ctx.store.list_sources()`. It uses `managed_eligibility`
rather than a hand-rolled `source["managed"]` because `task4-notes.md` records that two
definitions of "managed" coexist. A tombstoned source is not counted: its evidence is
suppressed for every audience, so the preview is not hiding it from anybody.

Tests (`test_graph_surface_access.py`), one managed and one legacy source as the decision
asks: `test_a_preview_of_a_workspace_with_managed_evidence_says_it_shows_legacy_only` (RED),
`..._with_no_managed_evidence_says_nothing_extra`, and
`test_the_graph_page_of_a_reader_who_is_not_previewing_carries_no_notice`.

### 4. Legacy lane bounding — as amended by the orchestrator mid-slice

`pipeline._legacy_failure(err)`, used by the generic `except Exception` in `run_indexing`.
The `openie.Stopped` branch keeps its own fixed sentence, unchanged.

**The rule, after the orchestrator's ruling:** an exception from a **closed input
validator** keeps its own bounded text; every other class stores its name plus
`"indexing failed; inspect local logs"`. `CLOSED_INPUT_VALIDATORS` is exactly the family
`knowledge/public_errors.py` lists as such — `TooLarge`, `ReadError`, `CaptureTooLarge`,
`InputCaptureError`, `RawArtifactTooLarge` — so the two modules cannot disagree about who
is one.

**Why the rule was amended, and what the first form cost.** The unconditional form broke
**five tests in `tests/unit/test_ingest_limits.py`**, a file this brief does not own, and
the full Fake sweep is what found them. What they pin is not incidental: "too large: more
than 50 characters... raise `HIPPO_MAX_TEXT_CHARS`", "3 readable files", "unpack to 120
bytes", "4 passages; the limit is 2". Each is a limit and the knob that raises it — the
whole answer the user needs, and precisely the row the plan's transport table already
assigns to the closed input validators ("existing bounded validation text from closed
input validators only"). I reported it rather than editing the file; the orchestrator ruled
that the limit vocabulary is spared. `test_ingest_limits.py` is **untouched and green**.

Tests: `test_an_unknown_legacy_failure_stores_its_class_and_a_fixed_sentence` drives an
exception class of the test's own (`Unexpected(RuntimeError)`) whose message carries both
an absolute path and a sentence of the source's own text, and asserts neither survives;
`test_a_closed_input_validator_keeps_the_limit_it_names` holds the other half.

**Two pre-existing tests still changed, and they record a real cost:**

| Test | Was | Now | Why it is not spared |
|---|---|---|---|
| `test_ingest_pipeline.py::test_a_source_with_no_text_fails_with_a_message` | `"no readable text" in error` | `"ValueError: indexing failed; inspect local logs"` | `pipeline.py:392` raises a bare `ValueError`, which is not one of the closed validator classes |
| `test_ingest_pipeline.py::test_add_repo_records_clone_failures` | `"could not clone" in error` | `"RepoError: indexing failed; inspect local logs"` | `RepoError` is not in `public_errors._ROWS`; a clone failure can carry a checkout path |
| `test_ingest_concurrency.py::test_a_failed_job_clears_the_passages_it_wrote` | `"model fell over" in error` | class + fixed sentence, private text asserted absent | an arbitrary `RuntimeError` |

"no readable text" is bounded and actionable and is now lost from the Library page (it
remains in `log.exception`). If that matters, the fix is to raise it as a `ReadError`
rather than to widen the rule — one line in `pipeline.py:392`, which I did not take because
it changes what the function raises and nothing in the brief asks for it.

### 5. Bulk refusal shape

- `managed_activation.ManagedPreflightRefused(ManagedDispatchError)`, with the "no source,
  no count" contract in its docstring.
- `pipeline._preflight_managed` raises it instead of returning `False`; `reindex_all` no
  longer has a `return 0` for the refused case, so `0` means only "nothing was started".
- `web/routes/sources.py::reindex_all` catches it and answers
  `409 {"error": "Bulk reindex refused", "code": "bulk_refused"}` after `view.validate()`.
  `ManagedActorRequired` is deliberately **not** caught: `app.py:77` already maps it to the
  generic permission response, and a route catch would be a second opinion.

Tests: `test_a_failed_managed_preflight_raises_a_refusal_that_names_no_source_and_no_count`
asserts the subclass relation, that no source id appears in the message, that the message
carries no digit at all, and keeps the original test's full row + byte comparison under
`no_destruction`. `test_an_empty_inventory_is_still_nothing_to_do_rather_than_a_refusal`
holds the other half. `test_a_failed_managed_preflight_clears_nothing_and_starts_nothing`
changed from `== 0` to `pytest.raises`, keeping every no-mutation assertion.
Route: `test_a_bulk_whose_managed_preflight_refuses_answers_a_closed_refusal_code`
(body asserted by **equality**, so a count or a breakdown would fail it) and
`test_a_bulk_over_a_managed_inventory_with_no_actor_is_the_generic_permission_answer`
(a regression guard — green at both ends, because `app.py:77` already did this).

### 6. `effective_settings`

`knowledge/query_access.effective_settings(ctx, settings)` —
`validate_settings({**ctx.store.get_settings(), **(settings or {})})` — called by
`query_session` and by `graph.py`'s merged-dict pre-validation, which were
character-for-character identical copies with nothing making them stay that way.
Tests: `test_effective_settings_is_the_stored_knobs_under_the_callers_own` and
`test_light_up_and_query_session_agree_on_the_effective_settings` (identity of the function
object, so a future local copy fails).

`graph.py`'s *caller's-own-values* pre-check (`graph.py:386`) is a separate call and is
untouched: the brief scopes graph.py to "settings merge and preview header only". See
residuals.

### 7. Pipeline minors from the 3b review

**Finding 4 — per-lane containment.** `pipeline._submit_lane` wraps each submission; a
`ManagedDispatchError` from a lane that changed lane since the plan logs and skips instead of
aborting the bulk and leaving every later legacy lane cleared, `queued` and jobless. Test:
`test_a_lane_that_changes_lane_after_the_plan_does_not_strand_the_lanes_behind_it` asserts
the bulk did not raise, both survivors were submitted, and every lane the bulk *cleared* was
also submitted (`set(prepared) <= set(submitted)`), which is the containment claim.

**Finding 7 — the sweep's build holder.** New `GenerationQueries.release_interrupted_build`
in `store/generations.py`, beside `apply_source_tombstone` and performing the same
transition minus the suppression: the source's own `MaintenanceJob`, if `kind == "rebuild"`
and `status == "running"`, becomes `cancelled` with `error_code="build_interrupted"`, and
`active_build_id` is cleared. Called by all three `mark_interrupted_jobs` implementations
after the stage rewrite. Each backend now reads the ids matching the `refreshing:` predicate
before rewriting them (past the rewrite the predicate no longer matches); the Ladybug and
Neo4j predicates are otherwise byte-identical to what they were.

Test: `test_a_reindex_right_after_a_restart_is_not_refused_by_the_holder_the_crash_left`
reconstructs the crash state from a *real* refresh observed in flight through the
`/api/chat` hook — its stage **and** its `active_build_id`, with the job put back to
`running` with a five-minute lease — then asserts the sweep clears the pointer, cancels that
exact job, and that the reindex the new error asks for proceeds without storing `build_busy`.

**Finding 9 — sweep constants.** `REFRESHING_PREFIX`, `INTERRUPTED_REFRESH_STAGE` and
`INTERRUPTED_REFRESH_ERROR` moved from `store/memory.py` (which is the Neo4j backend, not a
shared base) to the top of `store/generations.py`, **near the other module constants**, as
the spawn message asked, to keep the merge with opus-13's plan-validation work cheap. A
fourth constant `INTERRUPTED_REFRESH_CODE = "build_interrupted"` was added so the row's code
and the cancelled job's `error_code` cannot drift; `INTERRUPTED_REFRESH_ERROR` is now an
f-string over it. `ladybug.py`, `memory.py` and `tests/fakes/fake_store.py` import them from
`generations` instead of from `memory`.
`managed_activation._refreshing_stage(token)` builds the stage from the shared prefix, and
both `_present_progress` and `_starting_fields` go through it — `_starting_fields` was the
second inline `"refreshing: capture"` and has the same drift risk, so it is included.
Tests: `test_the_restart_sweep_constants_live_with_the_managed_lifecycle_vocabulary` and
`test_the_refreshing_stage_is_written_from_the_prefix_the_sweep_matches`.

**Finding 10 — identity before the row.** `managed_activation.check_operation_id` factored
out of `plan_dispatch`, and `pipeline.delete_source` calls it before `get_source`, so an
unbounded token is refused whether or not the row is still there. Test:
`test_an_unbounded_operation_identity_is_refused_even_when_the_row_is_already_gone`.

### 8. `canonical_selected_generations` raises `ProjectionError`

`knowledge/projection.py` imports `hippo.hipporag.graph_index`, so `graph_index` cannot
import `projection`: confirmed, not assumed. `ProjectionError` is therefore **defined in
`hipporag/graph_index.py`** and imported by `knowledge/projection.py`, which is the brief's
stated fallback. Every existing `from .projection import ProjectionError` still names the
same class, and `public_errors._ROWS` already lists it, so no table changed.

The RED drives the **real** function with a real incoherent selection
(`(("source-1","generation-a"),("source-1","generation-b"))`) rather than monkeypatching it
out, which is why it can see the type change at all — the existing
`test_a_bare_selection_failure_is_operation_failed_not_a_client_error` patches the function
and therefore cannot.

| Transport | Before | After | Test |
|---|---|---|---|
| 4b-i route, `/api/entities` (no catch of its own) | code-less 500, body not JSON | `500 {"error": …, "code": "operation_failed"}` | `test_an_incoherent_selection_is_the_closed_body_on_a_route_that_holds_no_catch` |
| 4b-ii route, `/api/graph/full` (has a catch) | already mapped | unchanged | `test_an_incoherent_selection_keeps_its_mapped_body_on_a_route_that_holds_one` |
| MCP code tool | bare `ValueError`, and `tool_failure` passes `type(exc) is ValueError` through **verbatim** | `ProjectionError`, mapped by the closed table | `test_an_incoherent_selection_reaches_an_mcp_code_tool_as_a_mapped_failure` |
| the function itself | — | — | `test_an_incoherent_selection_is_a_projection_failure_not_a_bare_value_error` |

Existing route catches were kept, as the decision requires.

## Addendum: the 4b-i review's F1-F5 and probes 5 and 6

Delivered mid-slice on the orchestrator's instruction, in commit `38ad96c`. Same method:
RED first (14 failing tests, `/tmp/hippo-pa4e-red-addendum.log`), then implement.

Three of those fourteen were my own test-setup mistakes rather than the defect, and the
test changed between RED and GREEN: the actorless probe patched `web.auth.build_actor_of`
when `sources.py` imports the name into its own namespace; the `Busy` probe used a managed
source, which has no `Busy` precondition by design; and the name-collision assertion said
`not hasattr(app, "public_failure_page")`, which F1's own import makes false. The other
eleven failed on the defect and are unchanged.

**F1 — six page routes answered a browser with raw JSON.** `render.wants_html(request)` is
now the one definition of "this caller asked for a page", used by `forbidden_page` (which
had it inline) and by the public-failure handler (which had nothing). The handler renders
`render.public_failure_page(request, failure, "failure.html")` for a browser and keeps the
JSON body for `/api` and for a non-HTML `Accept`. NEW template `failure.html`: the mapper's
sentence, its code, and a link back — no session of its own, because the failure being
reported is what a session would meet again.
Tests: `test_a_browser_gets_a_page_when_a_mapped_failure_escapes_a_page_route` and
`test_a_json_client_still_gets_the_closed_body_from_the_same_routes`, both over the review's
exact six (`/`, `/sources/s1`, `/account`, `/ask`, `/users`, `/partials/sources`), plus
`test_the_api_routes_answer_json_even_to_a_browsers_accept_header` so negotiation does not
turn an `/api` body into a page.

**F2 — the ask path's promise.** `pages.failure_operation_id()` mints `ask.<hex>`, validated
against the shared `OPERATION_ID` pattern (borrowing `managed_activation.new_operation_id`
would have claimed the failure was a build). `failure_text` logs
`ask failed [<id>]: <ExceptionClass>` at **WARNING** — the level the server actually emits —
and returns `"<sentence> [<code>] (operation <id>)"`, so the ID the message tells the reader
to quote exists on both sides.
Test: `test_the_ask_fragments_failure_is_logged_at_warning_with_an_operation_id`.

**Deviation on F2, deliberate:** the review also asks for `exc_info=True` at WARNING. I
tried it and it fails `test_the_html_ask_form_shows_the_same_closed_code` (3 rows), which
asserts that no part of `POISON` reaches `caplog` at INFO — the traceback carries the
exception's own words. The orchestrator's instruction was "log at WARNING with the operation
id (generate one if absent)", which is the review's own stated minimum, so the ID is at
WARNING and the traceback stays at DEBUG, now tagged with the same ID. **Someone has to
decide whether the local log may carry an exception message at INFO**; I would not weaken
another slice's redaction test to make that call.

**F3 — seven uncoded JSON bodies in `sources.py`.** New `render.coded_response(message,
code, status_code)`, and `public_failure_response` is now expressed through it, so there is
one body shape. The seven: `add_text` 400, `too_big` 413, `add_upload` 400, `add_repo` 400
(all `invalid_source`, taken from `public_errors.INVALID_SOURCE_TYPE.code` rather than
spelled again) and the three `Busy` 409s (new `indexing_busy`, minted next to
`bulk_refused`). Every message is unchanged.
Tests: `test_every_json_failure_body_the_source_routes_answer_carries_its_code` (4 bodies)
and `test_the_three_indexing_preconditions_answer_a_coded_409` (3, over a *legacy* source —
a managed delete has no `Busy` precondition by design).

**F4 — two `public_failure_page`s.** `app.py`'s handler is renamed
`public_failure_handler`; `app.py` now imports render's `public_failure_page` for F1, which
is exactly the collision the review predicted.
Test: `test_the_app_handler_and_the_page_renderer_do_not_share_a_name` asserts
`app.public_failure_page is render.public_failure_page`, that the handler is a different
object, and that it is what `create_app` actually registered.

**F5 — `add_text`/`add_upload`/`add_repo` catch by exact type.** Same `caller_error` rule
as decision 2. Latent today, as the review says.
Test: `test_an_ingress_route_reports_a_managed_dispatch_error_through_the_closed_table` —
RED showed the full `POISON` in a 400 body.

**Probe 5 promoted** — `test_an_actorless_delete_and_bulk_over_a_managed_inventory_answer_the_same_coded_409`:
end to end over HTTP with `build_actor_of` returning `None`, both routes answering the
generic permission body, and the source proven not suppressed.

**Probe 6 promoted** — `test_the_index_job_closure_captures_nothing_request_scoped`: reads
`co_freevars` off the closure the real route submitted and asserts it is exactly
`actor, ctx, operation, source_id` with the expected types. No `Request`, cookie or
request-scoped token can be reachable.

**F7's warning acted on.** `test_bulk_reindex_brings_the_bulk_managers_actor` would have
stayed green on a bulk that started nothing; it now also asserts a lane was submitted. And
`test_a_bulk_whose_managed_preflight_refuses_answers_a_closed_refusal_code` no longer
patches `reindex_all` at all: it withdraws the authority `capture_build_authority` would
prove, so the real `_preflight_managed` refuses, the real route maps it, and the test
asserts `start_indexing` was never called and the active generation did not move.

## Residual findings, deviations and things a reviewer should check

1. **Decision 1's grep is not satisfiable from this brief's files** — 23 of the 24
   `str(exc)` sites are in `users.py`, `sources.py`, `analyze.py`, `evals.py`, `pages.py`,
   `auth.py` and `graph.py`. Recorded above; needs a decision about scope, not code here.
2. **`graph.py:386` still catches `(ValueError, TypeError)` by isinstance** for the caller's
   own settings. The brief scopes graph.py to "settings merge and preview header only", so
   it was left alone. It is not reachable today — `validate_settings` on the caller's own
   dict is a pure closed validator — but it is the last site in the web layer with the shape
   decision 2 removes. One line, whoever owns graph.py next.
3. **F2's traceback level is an open decision** — see the deviation above.
4. **The MCP code tools do not map an acquisition failure at all.** `_code_graph`'s
   `with query_session(...)` is *outside* `_code_answer`'s `try` (`mcp_server.py:443-444`),
   so a `ProjectionError` from acquisition propagates out of `blast_radius_tool` raw rather
   than through `tool_failure`. Decision 8 makes the *type* mappable on every transport and
   the test asserts `tool_failure` renders it as `operation_failed`, but nothing in
   `mcp_server.py` calls it on that path. `mcp_server.py` is do-NOT-touch for this slice.
   **This is the one part of decision 8 that is type-correct but not yet wired.**
5. **The Neo4j lane of the sweep is unexecuted.** `memory.py::mark_interrupted_jobs` now runs
   two statements where it ran one, and calls `release_interrupted_build`. Fake and Ladybug
   both exercise the new path (runs 9, 10 and 11); Neo4j was not available to this worker.
   The change is a `RETURN s.id` read with the **same parameterized predicate string** the
   `SET` uses, so the two cannot disagree, plus the same `SET` — low risk, but PA7's Neo4j
   parity claim should re-run `test_managed_pipeline_activation.py -k interrupted` on the
   container before it is signed off.
6. **`evidence-pa4cfix.md` does not exist** anywhere in the tree (nor in the root working
   copy). `evidence-pa4c.md` and the `task4-notes.md` "Remote-client rule" section were read
   in its place.
7. **`api.py`'s brief line numbers were stale.** The brief names `~:50/94/117`; at `0bc378c`
   the file has exactly two such sites, `:50` (`put_settings`) and `:83`
   (`checked_settings`), and both are covered. There is no third.
8. **`STAGES[0] == "refresh_failed"` still duplicates `INTERRUPTED_REFRESH_STAGE`**
   (`managed_activation.py:66`). Finding 9 mentions it; the brief asks only for the prefix,
   so it was left. Same drift class, one line, and `store` may not import `ingest`.
9. `ManagedActorRequired`'s message still says "rebuilt" on the delete path (3b review
   finding 3). Not in this brief's decisions; untouched.
10. **One failure in the full Fake sweep is PROVEN pre-existing at the base.**
   `test_evidence_projection.py::test_composing_real_legacy_graph_with_empty_preserves_its_retrieval_results`
   (a `code_out` ordering comparison) fails at a clean `0bc378c` checkout of `src/` and
   `tests/` inside this worktree, and passes in the root tree at `25cd09b` — so it was
   fixed on `rag-it-all-tibs` after this slice's base, most likely by the code-arrow
   ordering work. Nothing to do here; it disappears on merge.
11. **`/partials/sources` now answers a whole page** when a mapped failure escapes it,
   because F1 uses one template for all six routes. That is better than the JSON blob it
   answered before, but an htmx swap of a full page into a table fragment is still not
   right. A `partials/failure.html` for the two partial routes is the finish; it was not in
   the addendum's wording so I did not invent the split.
