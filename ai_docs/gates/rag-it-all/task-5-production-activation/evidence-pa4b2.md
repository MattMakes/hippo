# Evidence: activation Task 4b-ii — the analyze, graph, code and render surfaces, status rendering, and the structural-default breakage

Branch `wp/pa4b2`, worktree `.worktrees/pa4b2`.
Base: `rag-it-all-tibs` `957fc35` per the orchestrator's override of the brief's `1acf069`.
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, `mcp` pinned to 2.1.1 per the rulebook.

## The merge this slice had to take first

`957fc35` could not be imported. `hippo.web.app`, `hippo.mcp_server` and
`hippo.knowledge.dense_session` all died on a circular import
(`knowledge/generation_profiles.py:14` → `ingest/__init__` → `pipeline` →
`managed_activation` → `prose_generation.py:25` → a partially initialised
`knowledge.generation_profiles`), and `pytest tests/unit --collect-only` reported 11
collection errors. It is order-dependent: only a module that reaches
`knowledge.generation_profiles` before `hippo.ingest` sees it, which is why 4a's full
sweep at `043ca51` never did. Reported to the orchestrator, fixed by them in `da51784`
(`pipeline.py` reaches the managed lane through a lazy `_managed()` accessor, guarded by
the new `tests/unit/test_import_order.py`), and merged here once, with their written
authorization:

**Merge: fast-forward `957fc35` → `ffd2265`** (`git merge rag-it-all-tibs`, no merge
commit created). Every number below is measured at or after `ffd2265`.

## Commits

| Hash | Subject |
|---|---|
| `27cc4c2` | Answer a failing web surface with its code, not the provider's words |
| `1772e0c` | Show a managed source the failure its build lane classified |
| `c4da3a1` | Point four tests at what the structural default actually does |
| *(branch tip)* | Record what this slice converted, closed and decided |

Four rather than the brief's "two or three". The fourth is the commit that adds this file,
so it cannot carry its own hash; it is the tip of `wp/pa4b2`. It also carries the one
assertion the 400-vs-500 boundary review added, and no other code.

Files created: `tests/unit/test_managed_web_surfaces.py`, this file.
Files modified: `src/hippo/web/render.py`, `src/hippo/web/routes/graph.py`,
`src/hippo/web/routes/analyze.py`, `src/hippo/web/routes/code.py`, `src/hippo/status.py`,
`tests/unit/test_status_access.py`, `tests/unit/test_query_authorization_boundary.py`,
`tests/unit/test_answer_original_citations.py`, `tests/unit/test_dense_session.py`.

Nothing under `web/app.py`, `web/auth.py`, `web/routes/{api,pages,sources,users}.py`,
`mcp_server.py`, `cli.py`, `remote.py`, `analysis/`, `evals/`, `knowledge/`, `ingest/`,
`store/`, `context.py`, `docs/`, the shared `GATES.md` or the checkpoint was touched.

## What the slice does

1. **Two dense owners, and only two.** `POST /api/graph/light-up` and `POST /api/simulate`
   dispatch the one structural owner they hold through `retrieval_session`. Everything else
   in these files — the two GET analyze pages, the changesets page, graph browse, full
   graph, node detail, all five code endpoints, `render.render` and `status` — stays a
   structural `query_session` held through DTO and render. No route preflights a graph,
   closes it and reacquires.
2. **One public body.** `web/render.py` gains `public_failure_response(failure)`, which
   answers `{"error": failure.message, "code": failure.code}` at `failure.http_status`, and
   `retrieval_failure(exc)`, which is the `public_failure(exc) or OPERATION_FAILED` caller
   rule `knowledge/public_errors.py` documents, spelled once for the whole web layer. The
   fixed `502` that `light_up` and `simulate` used to return is gone; both now answer 409
   for stale or mixed evidence, 503 for an unreachable model and 500 for anything unknown.
3. **The caller's own mistakes keep their own 400.** `light_up` validates the request's
   settings against the stored settings before it opens a scope, exactly as the session
   would, so the only `ValueError`s left inside the scope are activation failures. The code
   endpoints keep `_answer`'s existing 404/409/400 mapping for `UnknownSymbol`,
   `AmbiguousSymbol` and a blank required argument, which are `LookupError`s and a
   `_required` check, and map only what escapes the held session.
4. **A managed Source row shows its classified failure.** `status._managed_source` reads the
   code out of the `"<code>: <message>"` value `managed_activation.record_build_failure`
   stores and renders `public_failure_for_code(code).message`. The stored sentence is never
   echoed. The withheld branch is untouched.
5. **Four breakage groups closed**, listed row by row below.

## Audit rows converted (session-audit.md)

Post-change sweep on the five owned files:

```
rg -n 'query_session\(|query_access\(|graph_for\(|ctx\.graph\(|retrieval_session\(|dense_session\(' \
   src/hippo/web/routes/{analyze,graph,code}.py src/hippo/web/render.py src/hippo/status.py
```

| Audit row | Symbol | Classified | Now | Note |
|---|---|---|---|---|
| `web/routes/graph.py:328` | `light_up` | model/dense | **`retrieval_session`** (`graph.py:342`) | Group A fix. |
| `web/routes/analyze.py:270` | `simulate` | model/dense | **`retrieval_session`** (`analyze.py:291`) | Group A fix; body moved into `_simulate` so the mapping sits outside the scope. |
| `web/routes/analyze.py:55` | `analyze_adhoc` | model/dense | structural `query_session` (`analyze.py:63`) | **Reclassified, see decision 1.** |
| `web/routes/analyze.py:108` | `analyze_result` | model/dense | structural `query_session` (`analyze.py:119`) | **Reclassified, see decision 1.** |
| `web/routes/analyze.py:233` | `changesets_page` | graph-only | structural `query_session` (`analyze.py:244`) | Confirmed; default is structural since 4a. |
| `web/routes/graph.py:145` | `graph_page` | graph-only | structural `query_session` (`graph.py:151`) | Confirmed; see decision 3 on the preview branch. |
| `web/routes/graph.py:190` | `full_graph` | graph-only | structural `query_session` (`graph.py:196`) | Confirmed. |
| `web/routes/graph.py:418` | `node_details` | graph-only | structural `query_session` (`graph.py:432`) | Confirmed. |
| `web/routes/code.py:182` | `_graph` | graph-only | structural `query_session` (`code.py:188`) | Confirmed; every endpoint now reaches it through one `_code_response`. |
| `web/render.py:89` | `render` | graph-only | structural `query_session` (`render.py:118`) | Confirmed. |
| `status.py:46` | `source_view` | graph-only | `ctx.graph_for(access, structural=True)` (`status.py:47`) | Fallback **kept**, see decision 2. |
| `status.py:242` | `_audience_inventory` | graph-only | `query_session(..., structural=True)` (`status.py:263`) | Kept explicit, see decision 4. |
| `web/routes/code.py:10` | module docstring | not-a-call | rewritten | Says one held structural session, and that no code endpoint embeds anything. |
| `web/routes/graph.py:6` | module docstring | not-a-call | rewritten | Same, plus which endpoint is the dense one. |

**Unclassified production callers in these five files: 0.**

## Breakage rows closed (evidence-pa4a.md "Breakage for 4b/4c/4d")

| Group | Row | Fix | Result |
|---|---|---|---|
| A | `test_web_analyze.py` ×4 | `analyze.py:270` → `retrieval_session` | green |
| A | `test_graph_surface_access.py` ×2 (`…rechecks_after_building_output[light-up]`, `…holds_one_graph_through_source_inventory_and_releases`) | `graph.py:328` → `retrieval_session` | green |
| A | `test_web_auth.py::test_graph_page_and_its_endpoints_are_scoped_and_previewable` | same | green (not my file; no edit needed) |
| A | `test_analysis_snapshot_lifetime.py::test_analysis_routes_use_one_graph_through_dto_and_render[simulate]` | same | green (not my file; no edit needed) |
| B | `test_answer_original_citations.py` ×4 | `_dispatch_the_fixture` stubs `ask._dispatch`, as the table prescribes | green |
| B | `test_analysis_snapshot_lifetime.py::test_deleted_saved_result_is_withheld_during_analysis[dto]` | fixed by the `analyze.py` conversion | green (no edit needed) |
| C | `test_dense_session.py:596` | `query_session(ctx, EVERYTHING, structural=False)` | green (mine per the orchestrator's Q1 answer) |
| C | `test_status_access.py:195` | `assert_called_with(access, settings=ANY, structural=True)` | green |
| D | `test_query_authorization_boundary.py:211` | callback stamped onto `ctx._build_structural_graph` | green |
| D | `test_analysis_changesets.py` | **not mine** — orchestrator assigned it to 4d (backend-developer-10) | untouched |

## Commands and results

All runs used the standard invocation with the log captured, never piped to `tail`.
AnyIO handling: **form (b)** on the command line for every run, because
`test_managed_web_surfaces.py`, `test_status_access.py`, `test_graph_surface_access.py`,
`test_answer_original_citations.py` and others import `fastapi.testclient` at module level.
No per-test marker was added and no ini-wide `filterwarnings` exists.

| # | Command | Result | Log |
|---|---|---|---|
| 0 | Baseline on clean `ffd2265`, the thirteen owned/adjacent files | **12 failed, 193 passed, 1 skipped** — exactly the breakage-table rows for my files (`test_web_analyze` 4, `test_graph_surface_access` 2, `test_status_access` 1, `test_query_authorization_boundary` 1, `test_answer_original_citations` 4); `test_render*`, `test_web_graph_code`, `test_web_code*`, `test_managed_route_activation`, `test_managed_source_inventory` all green | `/tmp/hippo-pa4b2-baseline.log` |
| 1 | RED: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_web_surfaces.py -q -o addopts='' -W error -W "ignore:…BlockingPortal…"` | **19 failed, 10 passed** — missing `retrieval_session` on `graph`/`analyze`, missing `render.public_failure_response`, empty `error` on the managed row, 500 instead of 409 on simulate | `/tmp/hippo-pa4b2-red.log` |
| 1n | *(note on row 1)* The RED log predates the fixture restructure in decisions 6 and 7. No assertion changed; the fixtures did, and two mixed-profile tests became one parametrized test, so the final file's names do not all appear in that log. The claims each one makes are the same. | — |
| 2 | GREEN Fake, owned files plus `test_dense_session.py`, `test_managed_route_activation.py`, `test_managed_source_inventory.py` | **266 passed, 1 skipped** in 50.39s, exit 0 | `/tmp/hippo-pa4b2-fake-green.log` |
| 3 | Blast radius: `test_web_auth test_web_base test_analysis_snapshot_lifetime test_analysis_simulate test_rag_replay_access test_mcp_server test_mcp_http test_eval_access test_evals_runner test_query_session test_ask test_browse_original_citations test_structural_loading test_import_order` | **258 passed, 19 failed** — every one of the 19 is a Group A row owned by 4d (`analysis/simulate.py:149`): `test_analysis_simulate` 13, `test_analysis_snapshot_lifetime` 5, `test_rag_replay_access` 1. Nothing new broke. | `/tmp/hippo-pa4b2-blast.log` |
| 4 | GREEN Ladybug: `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_web_surfaces.py tests/unit/test_status_access.py tests/unit/test_graph_surface_access.py -q -o addopts='' -W error -W "ignore:…BlockingPortal…"` | **90 passed** in 231.83s (0:03:51), exit 0 | `/tmp/hippo-pa4b2-ladybug-green.log` |
| 4b | Ladybug rerun of `test_managed_web_surfaces.py` alone, after the 400-boundary test grew the simulate-overrides case | **29 passed** in 181.52s (0:03:01), exit 0 | `/tmp/hippo-pa4b2-ladybug-rerun.log` |
| 5 | `.venv/bin/ruff check <the ten changed files> && .venv/bin/ruff format --check <the same ten>` | All checks passed; 10 files already formatted | — |
| 6 | Entry-module import check, a fresh interpreter each, after `render.py` and `status.py` gained an edge to `knowledge.public_errors` (which imports `ingest.accepted_inputs`, `ingest.prose_generation` and `ingest.readers` at module level): `hippo.status`, `hippo.web.render`, `hippo.web.app`, `hippo.mcp_server`, `hippo.cli`, `hippo.knowledge.dense_session`, `hippo.web.routes.graph`, `hippo.web.routes.code` | all 8 import clean | — |

## Decisions and deviations

1. **`analyze_adhoc` and `analyze_result` are not dense owners, against their audit rows.**
   The 4a audit classifies both as model/dense. Their stated reasons do not hold at
   `ffd2265`: `analyze_adhoc`'s cache-miss branch renders a 404 page and never reaches the
   retriever, and `analyze_result` calls neither `reconstruct_trace` nor `can_reuse_answer`.
   Only `Retriever.retrieve` calls `require_dense`; `explain`, `retrieval_fields` and
   `passage_by_id` are pure graph reads. The plan's own model/dense list ("Production
   query-session activation") names "analysis simulation, graph light-up" and not the
   analyze pages. Dispatching them would make every page view of a verified corpus resolve
   an embedding profile — one `/api/show` plus a probe embed to render cached text — which
   contradicts "graph-only operation remains functional when Ollama metadata and model
   endpoints are unavailable". Asked the orchestrator (Q5); answered: `retrieval_session`
   only where a model is actually called, with the offline test as the arbiter.
   `test_the_analyze_page_renders_a_cached_trace_without_resolving_a_profile` is that
   arbiter: it reaches the page the way a browser does and fails if a fresh `/api/show` or
   `/api/embed` appears.
2. **`source_view`'s session-less acquisition is kept.** The audit leaves 4b to decide
   whether it survives. Its only remaining caller without a session is `reindex_all` in
   `web/routes/sources.py`, which belongs to 4b-i; removing the fallback here would break
   their branch at merge. It is already the structural acquisition Task 2 made it.
3. **`graph_page`'s preview branch still passes `session=None` to `render`, deliberately.**
   In preview mode the page body is the previewed tier's evidence while the header is the
   *actor's* status, so `render` acquires its own owner for the actor. Two owners for one
   response, but they are two audiences and merging them would show one audience's counts
   over the other's graph. `test_graph_surface_access.py::test_graph_preview_menu_uses_the_live_actor_after_a_pre_entry_downgrade`
   pins the actor half. Unchanged by this slice; recorded rather than silently kept.
4. **`_audience_inventory` keeps its explicit `structural=True`.** Redundant since 4a, but
   it is the sentence that says why this owner counts the same sources `source_view`
   renders, and the plan allows named callers to pass the flag.
5. **An unmappable stored code renders `operation_failed`, not silence or the stored text.**
   `public_failure_for_code` returns `None` for `authorization_changed` and for any code it
   does not know, and `public_errors`' documented caller rule is `or OPERATION_FAILED`. So
   a managed row whose build failed on `AuthorizationChanged` reads "Operation failed;
   inspect local logs by operation ID" rather than the build lane's "Permission for this
   source changed while it was being built." The row's `status`/`stage` still carry the
   shape of the failure. Narrowing this belongs in `_MANAGED_CODES`, not in the renderer.
   `test_an_unmappable_stored_failure_still_never_shows_its_own_text` pins it.
6. **The verified-dense web cases are direct route calls, not HTTP.**
   `tests/unit/test_staged_prose_writer.setup` — the only fixture that builds verified
   evidence — stamps its `AccessPolicy` `legacy_unknown`, and `knowledge/access.py:370`
   refuses that origin for every audience except the internal one. That is correct
   fail-closed behaviour, but it means no signed-in HTTP reader can ever prove that corpus.
   So `test_light_up_over_verified_managed_evidence_dispatches_verified_dense_once`, the
   mixed-profile pair and the blocked-model pair call `graph_routes.light_up` /
   `analyze_routes.simulate` with an internal principal, the same way
   `test_status_access.py` and `test_answer_original_citations.py` already drive routes.
   The transport itself is covered end to end by the tag-compatible, purely-legacy, empty,
   code-only, relation-only and model-blocked cases, all of which a signed-in reader proves.
   **Open item:** a `local_curated` verified fixture would let the verified lane be driven
   over HTTP too; it belongs with whoever next owns `test_staged_prose_writer.py`.
7. **Managed web tests sign a reader in.** With `access` an open audience, a managed corpus
   comes back empty and every dispatch reads `legacy` — correct (4a deviation 7), but it
   would prove nothing. The `reader()` helper creates a real user, whose local workspace
   membership Task 1 guarantees.
8. **The status health card legitimately names the configured embedding model.** The
   redaction assertions therefore check the provider's own words (`sk-live-…`, an absolute
   path, quoted source text) on every surface, and the raw model reply body only on the
   model paths. Reporting the operator's own configured model name in a health report is
   the existing intended behaviour, not a leak.
9. **`analyze_submit`'s `str(exc)` leak is fixed here.** The audit names the same leak at
   `pages.py:114` for 4b-i; `analyze.py:97` had it too and is in this slice's files. The
   HTML form now renders `retrieval_failure(exc).message`.
10. **No Neo4j run.** Out of scope for this brief, and this worker never held the
   disposable container.

11. **A note for 4b-i about the Group B stub.** `_dispatch_the_fixture` in
   `test_answer_original_citations.py` patches `ask._dispatch`. That survives 4b-i holding a
   structural `query_session` in `api.py`/`pages.py` and passing it to `ask` — the shape the
   audit assigns them. It does **not** survive those routes calling `retrieval_session`
   themselves, because the hand-built `derived_graph` would then be refused before `ask` is
   reached. If 4b-i takes the second shape, the stub has to move to their module's
   `retrieval_session` or the fixture has to be rebuilt on `test_structural_loading.published`.
12. **The 400-vs-500 boundary was checked on all three of its vocabularies.** A bad
   light-up setting and a blank code argument were already covered;
   `Overrides.from_dict` runs `validate_simulation_settings` → `validate_settings`, so a bad
   simulation override raises inside the existing `bad overrides` clause and stays a 400
   rather than reaching the outer mapper. `test_a_malformed_client_request_keeps_its_own_bounded_400`
   now pins all three.

## Ladybug result

`HIPPO_TEST_STORE=ladybug` over `test_managed_web_surfaces.py`, `test_status_access.py` and
`test_graph_surface_access.py` with form (b): **90 passed** in 231.83s, exit 0
(`/tmp/hippo-pa4b2-ladybug-green.log`). Rerun of the new file alone after the last test grew
a case: **29 passed** in 181.52s, exit 0 (`/tmp/hippo-pa4b2-ladybug-rerun.log`) — the same 29 tests,
since the case widened an existing test rather than adding one. Same counts as Fake for
the same files, so nothing in the dispatch, the public failure body or the managed row's
error rendering is Fake-only.
