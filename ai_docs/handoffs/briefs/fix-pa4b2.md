# Brief: Task 4b-ii follow-up — map the five unmapped routes and close the cheap review findings

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`) at HEAD `79e379a` or later. Do NOT commit; the orchestrator commits.

GOAL: Every route in the analyze, graph, code and render files answers a structural-loading or retrieval failure with the closed `{error, code}` body at the mapper's status (JSON) or the bounded sentence (HTML), never a bare 500; the cheap findings of the 4b-ii review are closed.

CONTEXT:
- Review: `ai_docs/reports/2026-09-11-pa4b2-review.md` (read findings 1–7 and section 7). Finding 1 (MEDIUM, the SPEC row): `full_graph` (`web/routes/graph.py:196`), `node_details` (`graph.py:432`), `changesets_page` (`analyze.py:244`), `analyze_adhoc` (`analyze.py:63`), `analyze_result` (`analyze.py:119`) and `render.py:118` let `ValueError` (bare from `canonical_selected_generations`, plus `ProjectionError`/`DenseUnavailable`/`QuerySnapshotUnavailable`) escape as `500 text/plain`. `light_up` and the five `/api/code/*` routes already map correctly via `except (ValueError, OllamaError, httpx.TransportError) -> public_failure_response(retrieval_failure(exc))`; `AuthorizationChanged` is a `RuntimeError` so the existing 409 still wins.
- Contracts: `ai_docs/handoffs/briefs/task4-notes.md` ("Task 4 cross-part contracts"); `web/render.py` exports `public_failure_response(failure)` and `retrieval_failure(exc)`.

DECISIONS:
1. Finding 1: give `full_graph` and `node_details` the same `except` tuple and mapping as `light_up`; give the three HTML pages an `except` that renders the bounded sentence and code the way `analyze_submit` now does, at the mapper's HTTP status (this also closes finding 6: HTML failures no longer render at 200). `render.py:118`: same mapping.
2. Finding 3: `code.py:203` catch tuple gains `httpx.TransportError` like the other sites.
3. Finding 5: `graph.py:340` must not quote a stored setting value in a 400; use the closed `invalid_source`-style bounded text from `public_errors` or a fixed sentence naming the setting key only.
4. Finding 2 (optional if under 15 lines): give `code._required` its own exception type so the 400 vocabulary is separated from the mapper by type, not timing.
5. Section 7 seam: parametrize the existing `test_managed_web_surfaces.py:~300` case over the simulate surface so POST `/api/simulate` on an EMPTY corpus is proven (1 acquisition, 1 release, no model call).
6. Findings 4, 7, 8, 9: no code change; the orchestrator carries them in the wrap-up notes.

FILES:
  - own: `src/hippo/web/routes/graph.py`, `src/hippo/web/routes/analyze.py`, `src/hippo/web/routes/code.py`, `src/hippo/web/render.py`, `tests/unit/test_managed_web_surfaces.py`, `tests/unit/test_web_analyze.py`, `tests/unit/test_web_code.py`, `tests/unit/test_graph_surface_access.py` (only if an existing assertion pins the old 500).
  - do NOT touch: `src/hippo/web/app.py`, `web/routes/{api,pages,sources,users}.py` (Task 4b-i, live), `status.py`, `src/hippo/knowledge/*`, `mcp_server.py`, `cli.py`, anything else.

STEPS:
1. Baseline: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_web_surfaces.py tests/unit/test_web_analyze.py tests/unit/test_web_code.py tests/unit/test_graph_surface_access.py -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-pa4b2fix-baseline.log 2>&1; echo EXIT $?` green.
2. RED: for each of the five routes, a test that injects a structural-loading `ValueError` (monkeypatch `ctx.graph_for` or the projection to raise `ProjectionError("PRIVATE")`) and asserts the JSON `{error, code}` body at the mapped status (or the HTML sentence at that status) with no `PRIVATE` text; plus the simulate empty-corpus seam. Save `/tmp/hippo-pa4b2fix-red.log`.
3. Implement decisions 1–5. GREEN: the baseline command, log `/tmp/hippo-pa4b2fix-fake-green.log`; Ladybug `tests/unit/test_managed_web_surfaces.py`, log `/tmp/hippo-pa4b2fix-ladybug-green.log`.
4. Ruff check + format on changed files.

DONE WHEN: Fake and Ladybug green; Ruff clean; `horch done` lists the routes mapped (file:line), the tests added, counts and logs. No commits.

REPORT: `horch note` after RED and after GREEN. `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a conflict with these decisions.
