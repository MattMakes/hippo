# Evidence: activation Task 4a — closed public failures and the structural query-session default

Branch `wp/pa4a`, worktree `.worktrees/pa4a`, base `rag-it-all-tibs` `043ca51`.
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, `mcp` pinned to 2.1.1 per the rulebook.

Commits:

| Hash | Subject |
|---|---|
| `4adf4e8` | Account for every low-level graph and session call before flipping the default |
| `d6696ce` | Say one bounded sentence about a failure instead of the exception's own words |
| `33cd4dc` | Make structural selection the query default and route ask through dense dispatch |
| `0abb01c` | Record what the structural default broke and who owns each repair |

Files created: `src/hippo/knowledge/public_errors.py`, `tests/unit/test_public_errors.py`,
`tests/unit/test_managed_route_activation.py`,
`ai_docs/gates/rag-it-all/task-5-production-activation/session-audit.md`, this file.
Files modified: `src/hippo/knowledge/query_access.py`, `src/hippo/ask.py`,
`tests/unit/test_query_session.py`, `tests/unit/test_query_snapshots.py`, `tests/unit/test_ask.py`.
Nothing under `src/hippo/web`, `mcp_server.py`, `cli.py`, `remote.py`, `analysis/`, `evals/`,
`context.py`, `dense_session.py`, `projection.py`, `status.py`, `ingest/`, `store/`, `docs/`, the
shared `GATES.md` or the checkpoint was touched.

## What the slice does

1. `src/hippo/knowledge/public_errors.py` — `PublicFailure(code, message, http_status)` and a pure
   `public_failure(exc)` over a closed table: four codes, five constant sentences, five statuses.
   It never reads the exception's text. `None` means "not one of these"; a managed path that must
   not leak an unknown exception writes `public_failure(exc) or OPERATION_FAILED` itself, which is
   the documented caller rule and how the bare `ValueError` from
   `GraphIndex.canonical_selected_generations` becomes `operation_failed` at its call site rather
   than by this table claiming every `ValueError`.
2. `query_access(..., structural=True)` and `query_session(..., structural=True)` are the defaults.
   `AppContext.graph_for(..., structural=False)` is unchanged.
3. `ask.search` / `ask.ask` / `ask.answer_from_trace` acquire or borrow through `retrieval_session`.

## Commands and results

All runs used the standard invocation with the log captured, never piped to `tail`.

| # | Command | Result | Log |
|---|---|---|---|
| 0 | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_query_session.py tests/unit/test_query_snapshots.py tests/unit/test_ask.py tests/unit/test_dense_session.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` (baseline, before any change) | 88 passed | `/tmp/hippo-pa4a-baseline.log` |
| 1 | RED: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_public_errors.py tests/unit/test_managed_route_activation.py -q -o addopts='' -W error`, then `test_public_errors.py` alone | collection error (`No module named 'hippo.knowledge.public_errors'`); 55 failed alone | `/tmp/hippo-pa4a-red.log` |
| 1b | RED for the flip itself, with `public_errors.py` present but `query_access.py` and `ask.py` restored to `d6696ce`: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_route_activation.py -q -o addopts='' -W error` | 18 failed, 4 passed. The four that already passed are the low-level `graph_for` default, the authorization-change denial, the settings mismatch and the caller's own authorization guard — the three behaviours the flip does not change plus one it preserves. | `/tmp/hippo-pa4a-red-flip.log` |
| 2 | GREEN Fake, owned + adjacent: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_query_session.py tests/unit/test_query_snapshots.py tests/unit/test_ask.py tests/unit/test_dense_session.py tests/unit/test_public_errors.py tests/unit/test_managed_route_activation.py tests/unit/test_answer_original_citations.py tests/unit/test_managed_source_inventory.py tests/unit/test_status_access.py tests/unit/test_core_context.py -q -o addopts='' -W error -W "ignore:…BlockingPortal…"` | 234 passed, 1 skipped, **6 failed — all in files this slice does not own** (table below) | `/tmp/hippo-pa4a-fake-green.log` |
| 3 | Owned files only: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_public_errors.py tests/unit/test_managed_route_activation.py tests/unit/test_query_session.py tests/unit/test_query_snapshots.py tests/unit/test_ask.py -q -o addopts='' -W error` | 142 passed | `/tmp/hippo-pa4a-mine.log`, rerun after formatting |
| 4 | Full sweep: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit -q -o addopts='' -p no:cacheprovider -W error -W "ignore:…BlockingPortal…"` | 3302 passed, 26 skipped, 50 failed (14 pre-existing `test_cli.py`, 36 routed below) in 237.88s | `/tmp/hippo-pa4a-full-fake.log` |
| 5 | GREEN Ladybug: `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_route_activation.py tests/unit/test_query_session.py tests/unit/test_query_snapshots.py -q -o addopts='' -W error` | **65 passed** in 129.21s, exit 0 | `/tmp/hippo-pa4a-ladybug-green.log` |
| 6 | `.venv/bin/ruff check src/hippo tests/unit/test_public_errors.py tests/unit/test_managed_route_activation.py tests/unit/test_query_session.py tests/unit/test_query_snapshots.py tests/unit/test_ask.py && .venv/bin/ruff format --check <the eight changed files>` | All checks passed; 8 files already formatted | — |

AnyIO warning handling: **form (b)** on the command line, and only on the runs that include a
module-level `fastapi.testclient` importer (`test_status_access.py`, `test_answer_original_citations.py`,
the full sweep). The two new files import no transport, so runs 1, 3 and 5 pass under a bare
`-W error` with no ignore at all. No per-test marker was added and no ini-wide `filterwarnings`
exists.

## Breakage for 4b/4c/4d

Every row below is a test in a file this slice does not own. None was edited. Grouped by root
cause; the count is 36, and the full sweep contains nothing else beyond the 14 pre-existing
`test_cli.py` failures.

### A. The owner scores dense candidates straight off its structural graph (27 tests)

A structural graph keeps its vectors in `dense_vectors` / `legacy_dense_vectors` with a zero-width
joint matrix and `DenseCapability("unavailable")`, so `GraphIndex.require_dense` refuses it. Every
one of these is a model/dense owner from the audit that still builds a `Retriever` on a raw
`query_session`. The cause is identical in all 27:
`DenseUnavailable: This structural graph is unavailable for dense retrieval`, raised at
`src/hippo/hipporag/graph_index.py:287` and surfaced as an HTTP 400 body on the three route cases.

**One-line fix, same for all of them:** the owner acquires (or wraps) through
`retrieval_session(ctx, access, settings=…)` / `retrieval_session(ctx, session=owner)` instead of
using `session.graph` directly — the conversion the audit already assigns it.

| File | Tests | Production owner to convert | Part |
|---|---|---|---|
| `tests/unit/test_analysis_simulate.py` | 13: `test_damping_change_moves_scores_and_the_diff_lists_ranks`, `test_force_exclude_of_a_kept_fact_removes_its_seed`, `test_force_include_of_a_dropped_fact_adds_its_seed`, `test_edge_edit_with_weight_zero_drops_the_passage`, `test_node_boost_changes_the_seed_weight`, `test_without_a_baseline_the_llm_filter_runs_once_and_is_replayed`, `test_rerun_filter_calls_the_llm_again`, `test_reanswer_produces_an_answer`, `test_stored_trace_json_round_trips_into_a_baseline`, `test_a_slider_move_on_a_code_question_costs_no_llm_call`, `test_the_structural_scale_moves_a_code_ranking_in_a_simulation`, `test_the_scale_and_an_edge_edit_compose_in_one_rebuild`, `test_a_structural_scale_override_is_passed_to_the_graph_the_search_runs_on` | `src/hippo/analysis/simulate.py:149` | 4d |
| `tests/unit/test_analysis_snapshot_lifetime.py` | 6: `test_simulation_holds_one_generation_through_answer_then_releases`, `test_simulation_failure_releases_pin[model]`, `test_simulation_failure_releases_pin[revocation]`, `test_simulation_borrows_callers_snapshot_and_captured_settings`, `test_reused_baseline_rebinds_snapshot_without_mutating_saved_trace`, `test_analysis_routes_use_one_graph_through_dto_and_render[simulate]` | `src/hippo/analysis/simulate.py:149` and `src/hippo/web/routes/analyze.py:270` | 4d, 4b |
| `tests/unit/test_web_analyze.py` | 4: `test_simulating_a_setting_change_returns_a_diff_and_ops`, `test_simulating_with_facts_boosts_edges_and_a_new_answer`, `test_simulate_without_a_baseline_runs_the_filter_once`, `test_saving_and_applying_a_changeset_changes_the_graph` | `src/hippo/web/routes/analyze.py:270` | 4b |
| `tests/unit/test_graph_surface_access.py` | 2: `test_query_transport_rechecks_after_building_output[light-up]`, `test_light_up_holds_one_graph_through_source_inventory_and_releases` (surface as HTTP 400 with the same detail) | `src/hippo/web/routes/graph.py:328` (`light_up`) | 4b |
| `tests/unit/test_rag_replay_access.py` | 1: `test_simulation_diff_does_not_reveal_old_hidden_titles` | `src/hippo/analysis/simulate.py:149` | 4d |
| `tests/unit/test_web_auth.py` | 1: `test_graph_page_and_its_endpoints_are_scoped_and_previewable` — `POST /api/graph/light-up` returns the 400 error body, so the assertion fails with `KeyError: 'seeds'` | `src/hippo/web/routes/graph.py:328` (`light_up`) | 4b |

### B. Route tests that hand `ask` a graph with no structural vector bindings (5 tests)

`ask` now dispatches a borrowed session, and the dispatcher validates the borrow. A hand-built
`GraphIndex` (or an unconverted legacy owner) is refused with
`DenseSessionUnavailable("invalid_borrow", "Borrowed graph requires structural vector bindings")`.
This is the intended fail-closed behaviour, not a regression: `public_failure` maps it to
`operation_failed`, never to a "rebuild your sources" lie.

| File | Test | Reason | One-line fix | Part |
|---|---|---|---|---|
| `tests/unit/test_answer_original_citations.py` | `test_answer_surfaces_present_originals_separately_from_ranked_views[http]`, `[mcp]`, `[html]`, `test_search_labels_derived_text_and_analysis_renders_original_evidence` | The `derived_graph` fixture stubs `ctx.graph_for` with a hand-built managed graph whose `retrieval_evidence` names a generation that does not exist in the store, so the dispatcher's binding check refuses it. The three unit-level tests in the same file that call `_answer_from_trace` directly still pass. | Stub the dispatcher rather than the graph: `monkeypatch.setattr(ask, "_dispatch", lambda *a, **kw: nullcontext(QuerySession(index, ctx.ollama, lambda: None, {})))` — or build the fixture with `tests/unit/test_structural_loading.published` so the generation exists. | 4b |
| `tests/unit/test_analysis_snapshot_lifetime.py` | `test_deleted_saved_result_is_withheld_during_analysis[dto]` | Same, reached through `/api/simulate`; surfaces as `HTTPException: 400`. | Converting `analyze.py:270` to `retrieval_session` (group A) fixes it. | 4b |

### C. Tests that assert the old default directly (2 tests)

| File | Test | Reason | One-line fix | Part |
|---|---|---|---|---|
| `tests/unit/test_dense_session.py` | `test_populated_default_legacy_borrow_rejects_without_reacquiring` (line 596) | Its subject is that a *legacy* borrow is refused, and it obtained one from the old `query_session` default: `assert owner.graph.dense_capability.mode == "legacy"` now reads `"unavailable"`. | `with query_session(ctx, EVERYTHING, structural=False) as owner:` — the legacy lane is an explicit opt-out now. | 4b (or whoever next owns `dense_session.py`) |
| `tests/unit/test_status_access.py` | `test_status_route_and_page_header_pass_the_request_audience` (line 195) | `query_access` now forwards the flag verbatim, so the recorded call is `graph_for(access, settings={}, structural=True)`. | `ctx.graph_for.assert_called_with(access, settings=ANY, structural=True)` | 4b |

### D. A graph the query no longer reaches, and a counter that is now a fingerprint (2 tests)

| File | Test | Reason | One-line fix | Part |
|---|---|---|---|---|
| `tests/unit/test_query_authorization_boundary.py` | `test_graph_expiry_callback_blocks_model_output_without_epoch_write` (line 211) | It installs an expiry callback on `ctx.graph_for(None)` and relies on the query reusing that cached legacy object. The structural builder builds a fresh graph, so the callback never fires and nothing raises. | Install the callback on the graph the query will actually use, by wrapping the builder: `monkeypatch.setattr(ctx, "_build_structural_graph", stamping)` where `stamping` sets `authorization_check` on the returned graph. | 4b |
| `tests/unit/test_analysis_changesets.py` | `test_overrides_to_ops_are_valid_and_apply_reaches_the_graph` | Asserts `trace.graph_version == store.graph_version() + 1`. Structural selection makes a view's version its content fingerprint, which is what a scoped legacy reader already recorded through `AppContext._authorize_legacy`. | Compare two traces (`before.graph_version != after.graph_version`) instead of the store counter, as `tests/unit/test_ask.py` now does. | 4b |

### E. Pre-existing, not this slice (14 tests)

All fourteen `tests/unit/test_cli.py` failures are the known Starlette
`You should not use the 'timeout' argument with the TestClient` deprecation under `-W error`,
recorded as pre-existing at `c3333ca` in the checkpoint and assigned to Task 4c. Same file, same
count, same message. Their logs additionally show
`StoreLockedError: data/hippo.lbug is already open in another hippo process`, which is the running
dev server holding the repository's `data/` tree while the CLI's `remote` fixture starts its own —
an environment condition, unrelated to sessions, and nothing in this slice reads or writes `data/`.

## Deviations and decisions

1. **The `public_failure` contract for unknown exceptions was ambiguous in the brief** — the
   signature says `None` means "not an activation/retrieval failure", while the table says
   "anything else raised inside the managed paths → `operation_failed`", which a pure function
   cannot determine. Asked the orchestrator; answered: map `BuildBusy`, `BuildCancelled` and
   `ProjectionError` explicitly inside the closed set; bare `ValueError` and everything else
   unknown → `None`; `AuthorizationChanged` → `None`; export `OPERATION_FAILED` for managed-path
   callers' own fallback; document the caller rule in the module docstring. Implemented as
   answered.
2. **`invalid_source` messages are the mapper's own constants, not the validators' instance text.**
   "No `str(exc)` in any returned field" is absolute and the redaction test enforces it, and the
   existing validator messages interpolate file names, byte counts and limits. Two bounded
   sentences cover the row: `"The source exceeds the accepted input size limit"` (413) and
   `"The source is not an accepted input type"` (400). Only closed input validators reach them:
   the readers (`TooLarge`, `ReadError` and its `Unsupported*` subclasses), the accepted-input
   capture (`CaptureTooLarge`, `InputCaptureError`) and `RawArtifactTooLarge`. `RawArtifactCorrupt`
   and the rest of the raw-object family are deliberately **not** mapped: corrupt stored bytes or
   an unsafe storage location are not client input, so they fall through to existing handling.
3. **`DenseSessionUnavailable(reason="invalid_borrow")` maps to `operation_failed`, not 409.** The
   other six reasons are stale or mixed evidence and do ask for a rebuild. `invalid_borrow` means
   the caller assembled the session wrongly; telling the reader to rebuild their sources would be
   a lie about their data.
4. **A latent bug in the opt-out had to be fixed for the flip to be honest.** `query_session`
   forwarded the flag as `**({"structural": True} if structural else {})`, so an explicit
   `structural=False` passed no keyword at all and inherited `query_access`'s default. With both
   defaults flipped, every documented compatibility opt-out would have silently become structural.
   Now forwarded verbatim, and `test_managed_route_activation.py::test_an_explicit_legacy_opt_out_is_still_honoured`
   pins it.
5. **`ask` passes an already-dispatched session straight through** rather than re-wrapping it.
   Re-wrapping a `verified` session would re-run `resolve_embedding_profile`, costing a second
   `/api/show` and probe embedding for the same profile.
   `test_an_already_dispatched_session_is_not_re_resolved` pins it. An *empty* activated session
   reports `dense_capability.mode == "legacy"` and is re-wrapped, which is a no-op that makes no
   model call.
6. **Three owned tests changed meaning with the behaviour, and were adapted rather than re-pinned
   mechanically.** (a) `test_query_session.py::test_content_publication_during_model_keeps_rendering_on_same_graph`
   compared graph identity; dense dispatch renders on an *activation* of the pinned view, so the
   assertion became a `view_fingerprint` comparison, which still proves the publication's evidence
   did not leak in. (b) `test_query_snapshots.py::test_graph_acquisition_failure_closes_reference_before_propagating`
   patched `ctx._managed_graph_for`, which queries no longer reach; it patches
   `_build_structural_graph` now. (c) `test_ask.py`'s two `graph_version` assertions are the same
   fingerprint change described in D.
7. **The managed-corpus cases in `test_managed_route_activation.py` pass `access=EVERYTHING`.** With
   `access=None`, `_graph_for` substitutes `Principal.open().access`, and an open audience cannot
   prove managed evidence — the corpus comes back empty and the dispatch is a no-op. That is
   correct behaviour (invariant 7), but it means "no access" is no longer the same thing as
   "unrestricted" for managed sources. The local CLI's `query_session(ctx)` (`cli.py:233`) inherits
   this and is 4c's to decide.
8. **Ladybug was run on the three files the brief names.** No Neo4j run: out of scope, and this
   worker never held the disposable container.
9. **`tests/unit/test_web_base.py`** is named in `task4-notes.md` as needing the AnyIO marker before
   a `-W error` gate line can include it. It is not in this slice's file list and it does not fail
   in the full sweep under the command-line ignore (form (b)), so nothing was done to it. The gate
   line that includes it already carries form (b); the orchestrator maintains those lines.

## Ladybug result

`HIPPO_TEST_STORE=ladybug` over `test_managed_route_activation.py`, `test_query_session.py` and
`test_query_snapshots.py` with a bare `-W error`: **65 passed** in 129.21s, exit 0
(`/tmp/hippo-pa4a-ladybug-green.log`). No AnyIO ignore was needed; none of the three imports a
transport at module level. Same counts as Fake for the same three files, so nothing in the
structural default or the dense dispatch is Fake-only.
