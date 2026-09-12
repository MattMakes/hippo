# Independent review: activation Tasks 4e and 4f, and a first pass at PA8

Reviewer `architect-reviewer-16`, 2026-09-12. Root tree `/Users/mascott/projects/hippo`,
branch `rag-it-all-tibs`. Read-only apart from this file: no source, test, plan, checkpoint
or gate ledger was edited.

**Verdicts**

- `4e: SPEC PASS on seven of eight decisions; decision 1 is VIOLATED as written (its own
  grep check fails at HEAD, and two of the sites are findings 1 and 2) while its substance —
  one helper, no local copy in app.py — is PROVEN / QUALITY PASS WITH FINDINGS`
- `4f: SPEC PASS on all five decisions -- decision 5 was completed at a4595ee, after the 4f
  merge / QUALITY PASS WITH FINDINGS`
- `PA8 first pass: NOT YET SIGNABLE` — PA1–PA7 and the static checks pass at HEAD and the
  Neo4j criterion is now met (finding 5 was closed by parity run 3 while this review was open),
  but a large part of Task 4's acceptance suite is unreachable from any CHECK line (finding 4),
  and this review has findings, which PA8's own criterion forbids.

20 findings: 4 MEDIUM, 13 LOW, 2 INFO, and 1 (finding 5) resolved by the orchestrator while
the review was open. None is a correctness regression in merged code; the two that reach a
client are pre-existing sites the wrap-up was asked to classify.

## Revisions reviewed, and the tree the runs saw

HEAD moved four times during the review. Everything below is judged at **`f96c01f`** (the
HEAD when the report was finished) unless a row says otherwise.

| Revision | What it is |
|---|---|
| `b5a5086` | Merge `wp/pa4f` — the evaluation wrap-up |
| `65fbcab` | Merge `wp/pa4e` — the web wrap-up |
| `dfd13b0` | Test-only: the MCP code tool now expects the mapped `ToolError` |
| `a4595ee` | sonnet-4's completion of 4f decision 5 (late-bound `rag_all`, dispatch-mode test) plus the two status partials and the last two `log.exception` calls |
| `f6ea424`, `db662bc` | The Task 5A fixture-loader fixes and their ledger record — no Task 4 surface |
| `0d4d2ec` | Merge `wp/layering`: `hippo.knowledge` no longer imports `hippo.ingest` except two allowlisted residuals; the lazy `ingest` package; the `_managed()` accessor removed. Moves class definitions between modules; no web, store or route behaviour change, but it renumbers `ingest/pipeline.py` and `ingest/accepted_inputs.py` |
| `f96c01f`, `4e6ec8b` | Checkpoint records only, no source. `4e6ec8b` was HEAD when this report was filed; every run below is at `f96c01f`, which is source-identical to it |

The gate runs below were taken in four passes, because the tree was live under two other
workers for most of the review and HEAD moved under it three times:

- **Pass A** ran in the root tree while `src/hippo/evals/{runner,rag_all,question_maker}.py`,
  `web/routes/evals.py`, the two status partials and three test files were uncommitted. The
  full patch is saved at `/tmp/hippo-pa-wrapup-dirty.patch` (392 lines). That work is now
  `a4595ee`, so pass A is effectively a run of `a4595ee`'s source.
- **Pass B** ran the same six CHECK lines against a pristine `git archive dfd13b0` export in
  `/tmp/hippo-head`, with `PYTHONPATH=/tmp/hippo-head/src` (verified: `hippo.__file__`
  resolves to `/tmp/hippo-head/src/hippo/__init__.py`, not the root editable install).

- **Pass C** re-ran PA6 and the PA8 static line in the root tree at **exactly `a4595ee`**,
  after that work merged and the tree went clean (`git status` shows only
  `tests/fixtures/rag_all/temporal_events.jsonl`, which no CHECK line names, and this report).
  PA6 is the only gate whose file list contains anything `a4595ee` changed
  (`tests/unit/test_evals_runner.py`). `test_managed_route_activation.py`, which PA1, PA5, PA6
  and PA7 all name, is byte-identical across those three trees, so PA1–PA5 needed nothing here.

- **Pass D** re-ran PA1–PA6, the PA8 static line, PA7 and the supplementary set at
  **`f96c01f`**, after the layering merge landed. That merge rewrites `ingest/accepted_inputs.py`
  and `ingest/pipeline.py`, which PA1, PA3, PA4, PA5 and PA7 all exercise, so a fourth pass was not
  optional. **Pass D is the result the ledger should cite.** The stale PA7 against the pass-A tree was stopped by PID at 50% rather than
  left to finish against superseded source.

All passes are green, so no gate result depends on which tree it saw. Every `file:line` in this
report was re-resolved against `f96c01f` after the layering merge renumbered those two files.

## Run results

`HIPPO_TEST_STORE` is explicit on every command. macOS has no `timeout`; nothing was piped
to `tail`; every log ends with its own `EXIT` line.

| Gate | Command | **Pass D — `f96c01f`, current HEAD** | Pass A (`dfd13b0` + patch) | Pass B (pristine `dfd13b0`) | Pass C (clean `a4595ee`) | Log |
|---|---|---|---|---|---|---|
| PA1 | ledger line, verbatim | **186 passed, 2 skipped, EXIT 0** | 186 passed, 2 skipped, **EXIT 0** | 186 passed, 2 skipped, **EXIT 0** | not needed (file list unchanged) | `/tmp/hippo-pa-wrapup-head2-pa1.log`, `/tmp/hippo-pa-wrapup-pa1.log`, `/tmp/hippo-pa-wrapup-head-pa1.log` |
| PA2 | ledger line, verbatim | **93 passed, 1 skipped, EXIT 0** | 93 passed, 1 skipped, **EXIT 0** | 93 passed, 1 skipped, **EXIT 0** | not needed | `/tmp/hippo-pa-wrapup-head2-pa2.log`, `/tmp/hippo-pa-wrapup-pa2.log`, `…-head-pa2.log` |
| PA3 | ledger line, verbatim | **189 passed, 3 skipped, EXIT 0** | 189 passed, 3 skipped, **EXIT 0** | same, **EXIT 0** | not needed | `/tmp/hippo-pa-wrapup-head2-pa3.log`, `/tmp/hippo-pa-wrapup-pa3.log`, `…-head-pa3.log` |
| PA4 | ledger line, verbatim | **117 passed, EXIT 0** | 117 passed, **EXIT 0** | same, **EXIT 0** | not needed | `/tmp/hippo-pa-wrapup-head2-pa4.log`, `/tmp/hippo-pa-wrapup-pa4.log`, `…-head-pa4.log` |
| PA5 | ledger line, verbatim | **175 passed, 2 skipped, EXIT 0** | 175 passed, 2 skipped, **EXIT 0** | same, **EXIT 0** | not needed | `/tmp/hippo-pa-wrapup-head2-pa5.log`, `/tmp/hippo-pa-wrapup-pa5.log`, `…-head-pa5.log` |
| PA6 | ledger line **+ AnyIO form (b)** | **321 passed, EXIT 0** | 321 passed, **EXIT 0** | same, **EXIT 0** | **321 passed, EXIT 0** | `/tmp/hippo-pa-wrapup-head2-pa6.log`, `/tmp/hippo-pa-wrapup-a4595ee-pa6.log`, `/tmp/hippo-pa-wrapup-pa6.log`, `…-head-pa6.log` |
| PA7 | ledger line, verbatim, Ladybug | **484 passed, EXIT 0** in 2369s (39m29s) | stopped by PID at 50%, stale tree | not run (Ladybug, long, run once) | not re-run | `/tmp/hippo-pa-wrapup-head2-pa7.log`, `/tmp/hippo-pa-wrapup-pa7.log` |
| PA8 | ledger `ruff check` + `ruff format --check` line, verbatim | **EXIT 0**, `128 files already formatted` | `All checks passed!` / `127 files already formatted`, **EXIT 0** | — | **EXIT 0** | `/tmp/hippo-pa-wrapup-head2-pa8.log`, `/tmp/hippo-pa-wrapup-a4595ee-pa8.log`, `/tmp/hippo-pa-wrapup-pa8.log` |
| extra | the wrap-up files **no** CHECK line runs (finding 4) | **300 passed, EXIT 0** | 300 passed, **EXIT 0** | — | — | `/tmp/hippo-pa-wrapup-head2-uncovered.log`, `/tmp/hippo-pa-wrapup-uncovered.log` |

**AnyIO handling.** Only **PA6** carries command-line form (b)
(`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`).
Five of its files import `fastapi.testclient` at module level, where no marker can catch the
warning: `test_web_base.py:6`, `test_web_analyze.py:6`, `test_mcp_server.py:10`,
`test_web_auth.py:12`, `test_web_code.py:16`. Every other gate line ran **verbatim with a
bare `-W error`**; their files import `fastapi.testclient` inside test bodies only
(`test_status_access.py`, `test_eval_access.py`, both already carrying per-test markers) or
not at all (`test_mcp_http.py`; `test_cli.py` uses `starlette.testclient`). The supplementary
run also uses form (b) (`test_managed_web_surfaces.py`, `test_managed_web_ingress.py`,
`test_web_library_evals.py`, `test_graph_surface_access.py`). No marker was added, no
ini-wide filter exists, and no application warning was suppressed.

**PA7.** Started once against the pass-A tree and **stopped by PID at 50%** when the layering
merge landed: that merge rewrites `ingest/accepted_inputs.py` and `ingest/pipeline.py`, which
five of PA7's eleven files exercise, so finishing against superseded source would have produced
a result nobody could cite. The reported run is the re-run — the verbatim ledger line, a bare
`-W error` (none of its eleven files imports a transport at module level), Ladybug, at
`f96c01f`: **484 passed, EXIT 0 in 2369.01s (39m29s)**, log `/tmp/hippo-pa-wrapup-head2-pa7.log`.
No Neo4j was used and the disposable container was never claimed by this session.

## 4e — SPEC

Decisions as numbered in `ai_docs/handoffs/briefs/pa4e-web-wrapup.md` (that file lists 8
before 7; both are covered).

| # | Decision | Verdict | Where it lives, and what holds it |
|---|---|---|---|
| 1 | One public-failure helper in the web layer; the 409 body keeps its shape | **VIOLATED as written; the one-helper half is PROVEN** | `app.py` imports `render.public_failure_response` / `retrieval_failure`; `render.py:129` and `:79` hold the only definitions; `app.py:58` `AUTHORIZATION_CHANGED`. The decision's own check — a grep for `str(exc)` under `src/hippo/web` "must find only the legacy settings validators" — fails at HEAD: 33 sites remain, and two of them are leak-class (findings 1 and 2), so the decision as written is **VIOLATED**. The substantive half is **PROVEN**: `app.py` holds no local copy and `render.py` is the single definition. All 33 sites are classified below, which is the work `task4-notes.md:70` routes to this review. |
| 2 | Exact-type 4xx catches | **PROVEN** | `render.caller_error` (`render.py:92`, `type(exc) is ValueError`) applied at `api.py:88` (`checked_settings`), `api.py:54-58` (the `put_settings` split) and `code.py:225`. Tests `test_a_code_payload_value_error_subclass_is_mapped_rather_than_printed_as_a_400` and `test_a_settings_write_that_fails_is_mapped_rather_than_quoted_back_as_a_400`, both in `test_managed_web_surfaces.py`. |
| 3 | Preview notice, no change to `access.py` | **PROVEN** | `graph.py:150` `PREVIEW_NOTICE` (a fixed string, no interpolation), `graph.py:155` `managed_evidence_exists`, `graph.py:190`, `graph.html:13`. `knowledge/access.py` is untouched. Test `test_a_preview_of_a_workspace_with_managed_evidence_says_it_shows_legacy_only` (`test_graph_surface_access.py`) plus the two negative cases. |
| 4 | Legacy lane stores a bounded error | **PROVEN, as amended** | `pipeline.py:316` `CLOSED_INPUT_VALIDATORS`, `:319` `_legacy_failure`. Tests `test_an_unknown_legacy_failure_stores_its_class_and_a_fixed_sentence` and `test_a_closed_input_validator_keeps_the_limit_it_names` (`test_ingest_pipeline.py`). The orchestrator's mid-slice amendment sparing the limit vocabulary is recorded in the evidence, and `test_ingest_limits.py` is untouched and green. Its cost is carried as finding 14. |
| 5 | `bulk_refused` 409; `ManagedActorRequired` to the generic permission answer | **PROVEN** | `managed_activation.ManagedPreflightRefused`; route at `sources.py:521-550`. Catch order is `Busy` then `ManagedPreflightRefused` — disjoint types, no broader `ManagedDispatchError` above them — and `view.validate()` runs before the 409 is returned, so a revocation outranks the refusal. `ManagedActorRequired` is deliberately uncaught and reaches `app.py:84`. Tests `test_a_bulk_whose_managed_preflight_refuses_answers_a_closed_refusal_code` and `test_a_bulk_over_a_managed_inventory_with_no_actor_is_the_generic_permission_answer` (`test_managed_web_ingress.py`). The `Busy` branch's asymmetry is finding 9. |
| 6 | `effective_settings` shared | **PROVEN** | `query_access.py:104`, used at `query_access.py:135` and `graph.py:388`; no other copy in `src/hippo`. `test_effective_settings_is_the_stored_knobs_under_the_callers_own` asserts function identity, so a future local copy fails the test rather than drifting. |
| 7 | 3b review minors 4, 7, 9, 10 | **PROVEN** (finding 4 of that review narrowly — see finding 15) | `_submit_lane` (`pipeline.py:629`); `GenerationQueries.release_interrupted_build` (`generations.py:89`) called by **all three** sweep lanes (`memory.py:222`, `ladybug.py:731`, `tests/fakes/fake_store.py:338`), each reading the matching ids **before** the rewrite; the three constants moved to `generations.py:26-30` with a fourth, `INTERRUPTED_REFRESH_CODE`; `check_operation_id` at `pipeline.py:553`, **before** `get_source` at `:554`. There is no fourth sweep copy — `store/base.py` has none and `store/__init__.py:82` only calls it. All four named tests exist in `test_managed_pipeline_activation.py`. |
| 8 | `canonical_selected_generations` raises `ProjectionError` | **PROVEN** | Exactly one definition, `hipporag/graph_index.py:284`; `knowledge/projection.py` imports it; raised at `graph_index.py:316,319`; `public_errors._ROWS:139` already had the row. Test `test_an_incoherent_selection_reaches_an_mcp_code_tool_as_a_mapped_failure` (`test_managed_web_surfaces.py`). **`evidence-pa4e.md` residual 4 is closed**: `_answering()` (`mcp_server.py:340`) is entered *before* `_code_graph` in `with _answering(), _code_graph(...)`, so an acquisition failure is caught by its `except Exception -> tool_failure`, not only by `_code_answer`. |

The addendum (F1–F5 and probes 5 and 6) is proven too: `render.wants_html:106`,
`render.coded_response:117`, `templates/failure.html`, `pages.failure_operation_id`,
`app.public_failure_handler` with `app.public_failure_page is render.public_failure_page`,
and the seven coded `sources.py` bodies. Every test the evidence names exists in the tree.

## 4e — QUALITY

**Every `str(exc)` under `src/hippo/web`, classified** — step 3's first question, and the
item `task4-notes.md:70` routes to this review. Grep: `rg -n 'str\(exc' src/hippo/web`
(33 sites).

| Sites | Shape | Classification |
|---|---|---|
| `api.py:97`, `code.py:226` | `HTTPException(400, str(exc))` behind `if not caller_error(exc): raise` | **guarded** — the exact `ValueError` only |
| `code.py:214,216` | `AmbiguousSymbol` / `UnknownSymbol`, exact types | **intended** — the name is the caller's own input and the candidates are the answer |
| `sources.py:485,499,512` | `coded_response(str(exc), INVALID_SOURCE, 400)` behind `caller_error` | **guarded** |
| `sources.py:508` | `except RepoError` -> `coded_response(str(exc), …, 400)` | **leak — finding 1** |
| `sources.py:536,588,605` | `coded_response(str(exc), INDEXING_BUSY, 409)` | **bounded** — `Busy` is raised once (`pipeline.py:706`) with fixed text, and the plan's transport table keeps the indexing preconditions' own sentence |
| `sources.py:382,405,418,429,442`, `users.py:182,210`, `app.py:154` | `str(exc.detail)` of an `HTTPException` | **bounded** — the detail is what the route itself already decided to say |
| `users.py:228,250` | `getattr(exc, "detail", str(exc))` over `(HTTPException, ValueError)` | **bounded today** — the only bare `ValueError` reachable is `int()` on the caller's own form field — **finding 18** |
| `users.py:337,363,403,434,457`, `auth.py:382` | `except ValueError` around `store.create_user` / `update_user` / `create_role` / `update_role` | **bounded today, unguarded by construction — finding 18** |
| `pages.py:213` | the settings form's `error=str(exc)` | **protected** — the plan names it |
| `graph.py:386` | `except (ValueError, TypeError)` on the caller's **own** settings dict | **unreachable today — finding 10** (`evidence-pa4e.md` residual 2) |
| `analyze.py:379,392` | `except ValueError` around `ChangesetAccess.save` / `apply` | **bounded today** — both raise `ChangesetUnavailable` (caught first) or `changesets.validate`'s own sentence; still the isinstance shape decision 2 removes |
| `evals.py:373` | `HTTPException(404 if "unknown question set" in str(exc) else 400, str(exc))` | **leak-class — finding 2** |
| `render.py:98` | docstring | prose |

**Duplicated failure helper: none.** `render.py` holds the single
`public_failure_response` / `retrieval_failure` / `public_failure_page` / `coded_response`
set; `app.py`'s handler is `public_failure_handler` and imports render's page renderer. Pinned
by `test_the_app_handler_and_the_page_renderer_do_not_share_a_name`.

**The three copies of `authorization_changed`:** still three named module constants —
`mcp_server.py:176` `DENIED_CODE`, `cli.py:75` `DENIED_CODE`, `web/app.py:58`
`AUTHORIZATION_CHANGED` — plus two registry entries (`public_errors.py:196`,
`managed_activation.py:396`). Unconsolidated, for the reason `task4-notes.md:45` records: the
CLI keeps knowledge imports out of `hippo --help`. See finding 12.

**Can the preview notice itself leak a managed source's existence?** Not to an audience that
should not learn it. The notice is a fixed workspace-level sentence with no interpolation — no
source name, no count, no generation id — and `graph.html:13` renders it in the **actor's**
page head, not inside the previewed tier's body. `viewer()` (`graph.py:84`) raises 403 unless
the caller holds `manage_users` or `manage_roles`, so only a manager who asked for a preview
can see it, and `access.py` was not touched. The one imprecision is that the predicate reads
the raw inventory rather than the actor's view — finding 11.

**Do the sweep changes keep Neo4j's `memory.py` lane in step?** Structurally yes, empirically
no. All three lanes now read the matching ids before the `SET` and then call
`release_interrupted_build`, and `memory.py:205-222` uses the *same* parameterized predicate
string for the `RETURN` and the `SET`, so the two cannot disagree. But the Neo4j lane has
never been executed at or after `65fbcab` — finding 5.

## 4f — SPEC

Decisions as numbered in `ai_docs/handoffs/briefs/pa4f-eval-wrapup.md`.

| # | Decision | Verdict | Where it lives, and what holds it |
|---|---|---|---|
| 1 | A public failure reason on results, runs and sets | **PROVEN** | The writers store `f"{code}: …"` (`runner.py`, `question_maker.py:145`); `eval_access.failure_code_of:52` reads back **only** a member of `_PUBLIC_CODES` (`:40`, built from the `PublicFailure` constants) and falls back to `operation_failed` for a pre-convention row; the private `error` stays nulled; `evals.py:68-79` puts `("errors", "Errors", …)` first in `SUMMARY_CARDS` and passes `public_reason` into the render calls. Test `test_a_run_that_could_not_route_shows_a_count_and_a_public_reason` (`test_web_library_evals.py`) asserts the count, the `retrieval_rebuild_required` sentence, and the absence of the secret, the question text and the exception class. |
| 2 | The dispatch rule promoted into `retrieval_session`; `ask._dispatch` deleted | **PROVEN** | `dense_session._session:181-200`: a borrow with `access is not None` raises `DenseSessionUnavailable("invalid_borrow", …)`, the settings comparison runs on a pass-through, and the pass-through branch sits **after** both borrow checks. `rg '_dispatch\b' src/hippo` finds no definition, only the comment at `dense_session.py:196`. All four promoted callers look the name up on the module at call time (`ask.py:32,68`, `simulate.py:38,160`, `runner.py:39,164`, `rag_all.py:24,388`), each with the documented `None if session is not None else access`. Tests `test_the_dispatch_rule_is_public_and_owns_every_borrow_decision` and `test_no_module_reaches_dense_dispatch_through_a_private_helper` (`test_managed_route_activation.py`), the second asserting `not hasattr(ask_module, "_dispatch")`. The residual half is finding 13. |
| 3 | Bounded per-question logging | **PROVEN for the brief's line; two siblings are not** | `runner.py:230` logs `question=<id> code=<code> exception=<class>` with no `exc_info`; `runner.py:121` and `question_maker.py:145` now have the same shape, which closes 4f's own open item about the two remaining `log.exception` calls. Test `test_a_failing_question_logs_its_id_and_code_but_neither_its_text_nor_the_exception`. `question_maker.py:183,267` still interpolate `exc` — finding 3. |
| 4 | A fact-bearing question-maker corpus | **PROVEN, with the recorded deviation** | `test_question_generation_reads_originals_without_a_dense_dispatch` now runs over the staged prose writer; the code and commit paths moved to `test_code_and_commit_question_generation_dispatches_nothing_either`, which asserts `{"code","commit"} <= kinds` and `record.dispatched == []`. The deviation (code and commit are unreachable over a managed corpus) is stated in the evidence with its cause, and I agree with it. |
| 5 | Late-bound `rag_all` lookup plus the dispatch-mode test | **PROVEN at `a4595ee`** (was NOT DONE at `b5a5086`) | `rag_all.py:24` `from ..knowledge import dense_session`, called at `:388`. The dispatch-mode test the 4d review's finding 5 asked for lands with the same commit (`tests/unit/test_evals_runner.py`, `tests/unit/test_evals_question_maker.py`). At `dfd13b0` the verdict would have been **UNTESTED**. |

## 4f — QUALITY

`errors` reaching a reader with no private text is the one thing 4d's finding 3 asked for, and
it is now true on all four surfaces: the run page cards, `run_body.html`'s per-question pill,
`eval_set.html`'s callout, and — since `a4595ee` — `partials/run_status.html:5` and
`partials/set_status.html:5`, which both render `public_reason(… .failure_code)` in the
failed pill's `title` instead of the raw stored string. 4f's own first open finding is closed.

`failure_code_of` is defensively right about rows that predate the convention: a row holding
`f"{type(exc).__name__}: {exc}"` yields `operation_failed`, not the class name, so an old row
neither falls silent nor publishes an internal name. Its allow-list is **derived** from the
`PublicFailure` constants rather than copied, which is the pattern finding 6 wants applied to
`CLOSED_INPUT_VALIDATORS`.

The remaining 4f open items are unchanged and correctly scoped as contract questions rather
than wrap-up work: `answer_withheld` still conflates a withheld answer with a failure that
saved a trace, and `summarize`'s gold-means rule still lets `accuracy: None` sit beside
`errors: N`. Both belong in Task 16's release notes.

## Ledger pass — PA1 to PA8 at HEAD

| Gate | At HEAD | Result at `f96c01f` | Evidence behind it | What Neo4j still owes |
|---|---|---|---|---|
| PA1 | **PASS** (all four passes) | **186 passed, 2 skipped, EXIT 0** | `evidence-pa1.md`, `evidence-pa3a.md`, `evidence-pa4b1.md` | Nothing new; `neo4j-parity.md` run 1 covers the store and membership half at tree `812c60e`. |
| PA2 | **PASS** | **93 passed, 1 skipped, EXIT 0** | `evidence-pa2.md` | Covered by run 1. |
| PA3 | **PASS** | **189 passed, 3 skipped, EXIT 0** | `evidence-pa3a.md`, `evidence-pa3b.md` | Covered by run 1. |
| PA4 | **PASS** | **117 passed, EXIT 0** | `evidence-pa3b.md`, `evidence-pa1.md` | Covered by run 1. |
| PA5 | **PASS** | **175 passed, 2 skipped, EXIT 0** | `evidence-pa3b.md`, `evidence-pa4e.md` (bulk refusal, per-lane containment) | **Covered** by `neo4j-parity.md` run 3 (tree `65fbcab`, 16 passed, 2 skipped, exit 0), which landed during this review. |
| PA6 | **PASS**, with form (b) | **321 passed, EXIT 0** | `evidence-pa4a.md`, `-pa4b1.md`, `-pa4b2.md`, `-pa4c.md`, `-pa4cfix.md`, `-pa4e.md`, `-pa4f.md` | Nothing: `neo4j-parity.md` records that the route-level tests exercise no Neo4j-specific code. But see finding 4 — the CHECK line does not reach the files that prove most of this gate's own criterion. |
| PA7 | **PASS** | **484 passed, EXIT 0** in 2369s | `evidence-pa4e.md` runs 10 and 11, `evidence-pa4f.md` run 2 | **Covered** by run 3: `memory.py::mark_interrupted_jobs` and `release_interrupted_build` are proven on the container at the tree that introduced them (`65fbcab`; the layering merge that followed moves no store lane — see finding 5). |
| PA8 | **NOT YET SIGNABLE** | **EXIT 0**, `128 files already formatted` | this report; ruff EXIT 0 | Lint and format pass verbatim. The call-site audit is attached (`/tmp/hippo-pa-wrapup-callsites.txt`, 58 lines) and classified below. Neo4j parity is now recorded (runs 1–3). What is left is the criterion's own last clause: "independent SPEC and QUALITY reviews have **no unresolved findings**" — this file has nineteen. |

**PA8's call-site audit**
(`rg -n 'query_session\(|query_access\(|graph_for\(|ctx\.graph\(' src/hippo`, 58 lines).
Classified exhaustively, the 58 lines are: **11** definitions, internal plumbing and
docstrings that are not call sites at all (`query_access.py:75,126`, `context.py:8,117,129,170,180,201`,
and the three internal `graph_for`/`query_access` calls at `query_access.py:85,87,136`);
**41** production `query_session(ctx, <principal or audience>.access)` owners, each opening one
session for one operation inside a route, MCP tool, CLI command, page or access service, which
is the single-owner property PA6 asks for; **3** that take a caller's session when given one and
otherwise acquire (`status.py:47,263`, `render.py:185`); `dense_session.py:201`, the promoted
rule's own acquisition; and the **2** below, which need a sentence rather than a tick:
`changeset_access.py:170` calls `ctx.graph()` — the **unfiltered** whole graph — to build
`native_ids` inside `apply`; it is used only as a membership set to refuse managed object ids
and the audience-filtered read goes through `self._session`, so nothing is disclosed, but it
is the one raw-graph call left on a request path and the plan should say so. And
`eval_access.py:137` acquires lazily inside `read_scope`, which is what makes finding 2
reachable.

## `task4-notes.md` — every item, with a disposition

| Line | Item | Disposition at `a4595ee` |
|---|---|---|
| 5–10 | Task 5A integration inputs (N1, N2, `ConflictSet`, selector shape, publication rule) | **Not this slice** — Task 5A's ledger. |
| 14–19 | Task 4 cross-part contracts (`public_failure_for_code`, code-versus-status, the JSON body shape, test ownership) | **Closed.** All three transports carry `{error, code}`; `public_failure_for_code` resolves the query-lane codes, which is what 4f consumes. |
| 20 | 4b-i finishing without the delete/bulk actor wiring | **Closed** by 4e decision 5 and promoted probe 5. |
| 24 | Should a refused bulk return a closed code? | **Closed** — `bulk_refused`, 4e decision 5. |
| 25 | An actorless bulk maps to the generic permission response | **Closed** — `app.py:84`, with a regression test. |
| 26 | The legacy lane stores `f"{type(err).__name__}: {err}"` | **Closed** — `_legacy_failure`, 4e decision 4. |
| 27 | Sweep constants live in `store/memory.py`; the Neo4j `base.py` sweep needs the same treatment | **Half closed.** The constants moved to `generations.py:26-30` and all three lanes import them; there is no `base.py` sweep to fix. The Neo4j lane is still unexecuted — **finding 5**. |
| 31 | 4b-i F1, F2, F3 | **Closed** by the 4e addendum (`failure.html`, `failure_operation_id`, seven coded bodies). F2's traceback level stays an explicit open decision (`evidence-pa4e.md` residual 3); I agree with the worker's call — do not weaken 4b-i's redaction test to add `exc_info` at WARNING. |
| 33 | F4, F5, probes 5 and 6, the bulk-starts-nothing caution, the stale line numbers in `evidence-pa4b1.md:388` | **Closed** except the stale line numbers: the real sites today are `graph_index.py:316,319`, not `:297,300`. **Wrap-up, documentation only.** |
| 37 | The bare `ValueError` from `canonical_selected_generations` | **Closed** — 4e decision 8. |
| 38 | HTTP, MCP and CLI unify on the sentence plus `authorization_changed` | **Closed**; the three constants stay unconsolidated — **finding 12**. |
| 42 | 4c N1: the `public_errors.py:179-184` comment misnames "the last two rows"; `test_public_errors.py:208` says eleven against a twelve-entry dict | **Open, documentation only** — the final cleanup batch. |
| 43 | 4c N2, N3, N4: three small tests (`_index_remotely`'s stored-error print, the git-URL identity branch, the `hippo --help` import footprint) | **Open.** `_stored_error` exists at `cli.py:359` and both print sites use it, but `tests/unit/test_import_order.py` has no help-footprint case and I found no test for either CLI branch. **Final cleanup batch**, three small tests. |
| 44 | The phrasing fix in `evidence-pa4cfix.md` | **Open, documentation only.** The file does exist — **finding 16**. |
| 45 | Three copies of `authorization_changed` | **Open** — **finding 12**. |
| 49 | `evidence-pa4c.md` deviation 5 says the stored-error print was "already closed" | **Open, documentation only** — amend the evidence line. |
| 50 | `pipeline.py:146/:216-221` should raise a dedicated closed validator type instead of a bare `ValueError` | **Open.** 4e did not take it; the bare raises now sit at `pipeline.py:109,137,142,214,524,733`. **Carried by this review**, same family as **finding 14**. |
| 51 | `build_interrupted` maps to `operation_failed`/500, not 409 | **Closed** — `public_errors.py:194`. |
| 55 | The remote-client rule; tighten the isinstance 4xx catches | **Closed** — 4e decision 2. |
| 59 | A gated `hippo index` sets no `owner_id`/`access_role_id` | **Open contract question.** Nothing merged changes it, and "likely yes" is not a decision. **Defer to Task 16** with a plan note. |
| 60 | `add_repo` takes no `build_actor` | **Open by design** — repositories are legacy by plan. **Defer to Task 16** release notes. |
| 61 | A gated `hippo index note.md` can now report `model_unavailable` where legacy succeeded | **Open, intended.** **Defer to Task 16** release notes and the plan's rollout section. |
| 62 | `mcp_server._code_answer`'s trailing `validate()` | **Closed** — it is inside the mapper (`mcp_server.py:443-454`) and the docstring states the ordering rule. |
| 63 | Enumerate what `tool_failure` passes verbatim | **Closed** — `type(exc) is ValueError` only, the same rule as `render.caller_error`. |
| 64 | `remote.py` no longer passes `timeout=` | **Closed** — `test_cli.py` is green under a bare `-W error` inside PA6. |
| 68 | 4e's logging decision (class only at INFO/WARNING, traceback at DEBUG) | **Closed and respected.** Do not "fix" it with `exc_info=True`. |
| 69 | MCP acquisition is already inside the mapper | **Closed** — confirmed at `mcp_server.py:340` and the three tool bodies; `evidence-pa4e.md` residual 4 is resolved, not open. |
| 70 | `pipeline.py:~392`'s bare `ValueError`; 18 unowned `str(exc)` sites; `analyze.py` and `graph.py` bind `retrieval_session` at import | **This review's job, done above.** The bare raise is now `pipeline.py:393` — **finding 14**. The `str(exc)` table is in "4e — QUALITY"; two sites became findings 1 and 2. The import binding is **finding 19**. |
| 71 | Neo4j `mark_interrupted_jobs` / `release_interrupted_build` run 3 | **Closed at `0d4d2ec`** — `neo4j-parity.md` run 3. See finding 5. |
| 75 | 4f's done list; decision 5 and two cheap findings handed to sonnet-4 | **Closed at `a4595ee`.** |
| 76 | `analyze.py` and `graph.py` late-binding; `answer_withheld`; `summarize`'s gold means | Late-binding **open** — **finding 19**. The other two: **defer to Task 16** as contract and release-note items, as 4f says. |
| 80 | Fact order fixed at `e709aad`; stale fingerprints; the code-arrow sibling | **Closed**; the arrow ordering is another worker's slice. |
| 81 | No public surface names an evaluation run's retrieval failure | **Closed** — 4f decision 1, plus the two partials at `a4595ee`. |
| 82 | Promote `ask._dispatch` and audit the three access-plus-session call sites | **Closed** — 4f decision 2; the residual precedence half is **finding 13**. |
| 83 | A fact-bearing corpus; `runner.py:209`'s logging | **Closed** — 4f decisions 4 and 3. |
| 87 | 4b-ii finding 8: a preview audience gets no identity | **Closed for this increment** — 4e decision 3's notice, with `access.py` unchanged exactly as decided. |
| 88 | 4b-ii finding 4: the duplicated settings merge | **Closed** — 4e decision 6. |
| 89 | 4b-ii finding 7: `retrieval_failure`'s total fallback and `EvalAccessDenied` | **Open, latent** from `_simulate`; it is live in the opposite direction at `evals.py:373` — **finding 2**. |
| 90 | 4b-ii finding 9: `test_query_authorization_boundary.py:219` monkeypatches `ctx._build_structural_graph` | **Open** — add a public seam when `context.py` is next owned. **Defer.** |
| 91, 96 | The `local_curated` verified fixture for verified dense over HTTP, and the revocation half | **Re-check; probably stale.** `prose_generation.py:284` stamps `origin="local_curated"` and `access.py:383` accepts exactly that origin, so the `legacy_unknown` blocker the note describes appears to be gone. The two cases still have no test — **carry as a small test task, not a fixture-building task**. |
| 97 | Narrowing a managed row's `AuthorizationChanged` rendering belongs in `_MANAGED_CODES` | **Open by design.** `public_errors.py:196` maps it to `None`, so the permission response owns it. **Defer**; no change needed unless the row presentation changes. |
| 98 | `graph_page`'s preview branch renders two audiences | **Checked, clean** — see "4e — QUALITY". |
| 100–102 | Layering: `hippo.knowledge` imports `hippo.ingest` | **Closed at `0d4d2ec`, with two allowlisted residuals.** The shared input contracts moved to the new leaf `knowledge/inputs.py`, `ingest/__init__.py` is lazy, the `_managed()` accessor is gone, and `tests/unit/test_layering.py` asserts the offending files are **exactly** the allowlist. The two survivors are `input_binding.py -> ingest.prepared_chunks` and `public_errors.py:81-83 -> ingest.{accepted_inputs,prose_generation,readers}`; both are one-directional, both are pinned by `test_import_order.py`, and closing them is a separate slice. **Nothing further owed by Task 4.** |
| 104–106 | 5A part 2 fix notes | Not this slice. |
| 108–111 | Per-thread transaction ownership; `build_authority`'s full scans; `PlainBuildOptions`' missing fields | Ownership merged (`test_transaction_ownership.py` is in `neo4j-parity.md` run 1); the performance item stays open for a later increment. |
| 113–131 | The merge checklist | Consumed. `:127` (`reindex_all` must become a single-owner session) is **closed** at `sources.py:529`. |

From `evidence-pa4e.md`'s own residual list: 2 becomes finding 10, 5 becomes finding 5, 6
becomes finding 16, 8 becomes finding 8, 9 becomes finding 17, 11 becomes finding 20.
Residuals 1, 3, 4, 7 and 10 are resolved or explicitly accepted above.

## Findings

**1. MEDIUM — `add_repo` answers a 400 carrying an absolute server path and git's raw
stderr.** `src/hippo/web/routes/sources.py:507-508` catches `RepoError` by exact type and
returns `coded_response(str(exc), INVALID_SOURCE, 400)`. `RepoError` messages are not
bounded: `ingest/repos.py:77` is `f"the folder {dest} already exists and is not empty"` — an
absolute path under the server's data root — and `repos.py:88` is `_explain_git_failure`,
whose return value is `f"could not clone {url}: {reason}. git said: {last_line}"`, where
`last_line` is git's own stderr verbatim (`repos.py:107`). PA6's criterion forbids "paths …
or arbitrary exception strings" in a stable code's body, and because `coded_response` gives the
body a `code`, `remote.py` branches on it and prints this `error` string to the terminal
rather than falling back to the generic sentence. 4e decision 4 bounds this *same class* on the Source row for this *same
reason* ("a clone failure can carry a checkout path", `evidence-pa4e.md:223`), so the two
lanes now disagree about `RepoError`.
*Fix:* bound `_explain_git_failure` to its `reason` clause and drop `last_line` (keeping the
full text in `log.warning`). The four `reason` strings are already the actionable half.
Returning `INVALID_SOURCE_TYPE.message` instead would also work but costs the user the
"only public repositories can be cloned" hint.

**2. MEDIUM — `/api/evals/sets/{set_id}/run` picks its status by substring and prints any
`ValueError` subclass.** `src/hippo/web/routes/evals.py:372-373`:
`except ValueError as exc: raise HTTPException(404 if "unknown question set" in str(exc) else 400, str(exc))`.
`runner.start_run:83-84` calls `EvalAccess(ctx, access).require_set`, which is
`@_guarded_collection` and therefore opens a session through `read_scope`
(`eval_access.py:137`). So `ProjectionError`, `DenseSessionUnavailable` and
`QuerySnapshotUnavailable` — all `ValueError` subclasses — reach the client as a **400 that
blames the request**, with the projection sentence as the `detail`. This is exactly the shape
4e decision 2 removed from `api.py` and `code.py`; `evals.py` was on 4e's do-NOT-touch list,
which is the only reason it survived. Choosing an HTTP status by matching a message substring
is independently fragile: rewording `EvalAccessDenied`'s sentence silently turns the 404 into
a 400.
*Fix:* `except EvalAccessDenied as exc: raise HTTPException(404, "no such question set") from exc`,
then `except ValueError as exc:` with `if not caller_error(exc): return public_failure_response(retrieval_failure(exc))`
ahead of the 400. The same three lines as `code.py:225`.

**3. MEDIUM — the question maker logs the model's reply body.**
`src/hippo/evals/question_maker.py:183`
(`log.warning("Question generation skipped passage %s: %s", passage.id, exc)`) and `:267`
(its multi-hop twin) interpolate `str(OllamaError)`. `knowledge/public_errors.py:12-13` states
as a fact that "`Ollama._request` puts 300 characters of the model's reply body into its
message", and that body is generated from the corpus's own passages. 4f decision 3's rule
("never the question text or exception text") and 4e's logging decision (`task4-notes.md:68`,
class only at INFO/WARNING) both forbid it. These two were missed because 4f's brief named
only `runner.py:209`, and 4b-i's redaction test asserts at INFO, so a WARNING is not caught.
*Fix:* `…, passage.id, type(exc).__name__)` at both sites — the two-line change 4f's own open
finding scoped, applied to the right pair.

**4. MEDIUM — no PA CHECK line runs the files that hold most of Task 4's acceptance tests.**
`GATES.md:8-38` names 24 test files. `test_managed_web_surfaces.py`,
`test_managed_web_ingress.py`, `test_graph_surface_access.py`, `test_web_library_evals.py`,
`test_ingest_limits.py`, `test_managed_eval_activation.py`, `test_evals_question_maker.py`
and `test_managed_transport_activation.py` are in none of them. Fourteen of the nineteen tests
that hold 4e's and 4f's decisions live in those files, including every test of PA6's own
criterion that "HTTP/MCP/CLI stable codes contain no injected secrets, raw text, paths,
tokens, prompts, model bodies, or arbitrary exception strings". As the ledger stands, PA6 can
pass while every one of those regressions is live.
*Fix:* add `test_managed_web_surfaces.py`, `test_managed_web_ingress.py`,
`test_graph_surface_access.py` and `test_web_library_evals.py` to PA6 (all four import
`fastapi.testclient` at module level, and PA6 already carries form (b)), and
`test_managed_eval_activation.py` plus `test_ingest_limits.py` to PA5. I ran all eight
together at HEAD as supplementary evidence: **300 passed, EXIT 0**,
`/tmp/hippo-pa-wrapup-uncovered.log`.

**5. RESOLVED DURING THE REVIEW (was MEDIUM) — Neo4j parity for the rewritten restart
sweep.** When I opened this review `neo4j-parity.md` held runs 1 and 2 only. Run 1 is at tree
`812c60e`, which predates `65fbcab`'s rewrite of all three `mark_interrupted_jobs`
implementations — `store/memory.py:205-222` is the Neo4j one — and predates
`store/generations.py:89 release_interrupted_build`, which every lane now calls. Both
`evidence-pa4e.md` residual 5 and `task4-notes.md:71` referred to a "run 3" that did not exist,
and PA5's Neo4j half was stale for the same reason.
**Run 3 landed at `0d4d2ec`** and closes it: tree `65fbcab`,
`test_managed_pipeline_activation.py` and `test_ingest_concurrency.py` under
`-k "interrupted or sweep or restart or bulk or tombstone"`, **16 passed, 2 skipped, 102
deselected in 483.39s, exit 0**, log `/tmp/hippo-orch-neo4j-parity-3.log`. That is the Neo4j
lane of the sweep and the managed bulk/tombstone dispatch, which is what PA5 and PA7 owed.
*Residual, not a finding:* run 3's tree is `65fbcab`, so it predates the layering merge's
rewrite of `ingest/pipeline.py` and `ingest/accepted_inputs.py`. Neither moves a store lane —
the layering evidence records that Ladybug was not run for the same reason — so I do not think
a fourth run is owed, but the orchestrator should say so in the file rather than leave a reader
to infer it.

**6. LOW — `CLOSED_INPUT_VALIDATORS` is a copy, and the evidence claims it cannot drift.**
`src/hippo/ingest/pipeline.py:316` hand-lists
`(TooLarge, ReadError, CaptureTooLarge, InputCaptureError, RawArtifactTooLarge)`;
`knowledge/public_errors.py:132-136` lists the same five with their rows.
`evidence-pa4e.md:200-201` says the tuple "is exactly the family `public_errors.py` lists as
such … so the two modules cannot disagree about who is one". Nothing enforces that, and
`rg CLOSED_INPUT_VALIDATORS tests/` finds no test. Adding a sixth closed validator to
`public_errors` silently leaves it unbounded on the Source row, or the reverse.
*Fix:* a test in `test_ingest_pipeline.py` asserting the tuple is exactly those five classes
and that each has a `public_errors` row. `eval_access._PUBLIC_CODES:40` is the pattern: derive
where you can, pin by test where you cannot.

**7. LOW — a stale pointer left by the constant move.**
`src/hippo/knowledge/public_errors.py:146` still says `build_interrupted` "comes from …
(`store/memory.py`, `INTERRUPTED_REFRESH_ERROR`)". 4e moved that constant to
`store/generations.py:29`, and `memory.py` is the Neo4j backend rather than a shared base —
which is the reason 3b finding 9 gave for moving it in the first place.
*Fix:* one word in the comment.

**8. LOW — `STAGES[0]` still duplicates `INTERRUPTED_REFRESH_STAGE`.**
`src/hippo/ingest/managed_activation.py:67` spells `"refresh_failed"` again;
`store/generations.py:27` owns it. Same drift class the prefix fix closed. `store` may not
import `ingest`, but `ingest` may import `store`, and `managed_activation.py:38` already
imports `REFRESHING_PREFIX` from exactly there.
*Fix:* `STAGES = (INTERRUPTED_REFRESH_STAGE, "refresh_cancelled", "failed", "cancelled")`.

**9. LOW — the bulk's `Busy` branch skips the revocation check its sibling makes.**
`src/hippo/web/routes/sources.py:535-536` returns the 409 without `view.validate()`;
`:537-543` validates before returning the refusal and `:547` before the success. So a
permission change during a bulk that hit `Busy` is the one path that answers without proving
the audience still holds.
*Fix:* `view.validate()` before the `Busy` return, matching the two branches beside it.

**10. LOW — `graph.py:386` is the last isinstance 4xx catch in the web layer.**
`except (ValueError, TypeError) as exc: raise HTTPException(400, str(exc))` over the caller's
own settings dict. Unreachable today — `validate_settings` on a caller-supplied dict raises
the exact `ValueError` — and the comment above it explains why the caller's own values are
validated alone. It is still the shape decision 2 exists to remove.
*Fix:* one line, `if not caller_error(exc): return public_failure_response(retrieval_failure(exc))`,
for whoever owns `graph.py` next — the same worker who late-binds `retrieval_session` there
(finding 19).

**11. LOW — the preview notice's predicate reads the unfiltered inventory.**
`src/hippo/web/routes/graph.py:164-167` iterates `ctx.store.list_sources()` rather than the
audience-filtered `view.sources`. Only a `manage_users` or `manage_roles` holder can reach the
branch (`graph.py:84`), and the answer is one workspace-level boolean rendered as a fixed
sentence, so no source is identified — but "this workspace holds managed evidence" is computed
over sources the previewing manager's own audience may not be authorized to read, which is the
kind of question the plan otherwise routes through the view.
*Fix:* compute it from `view.sources` (the view is already open at `graph.py:180`), or add a
sentence to `managed_evidence_exists`' docstring stating that this is workspace metadata for a
manager, not an audience read. The docstring is the cheaper honest option.

**12. LOW — `authorization_changed` is still spelled in three modules.**
`src/hippo/mcp_server.py:176`, `src/hippo/cli.py:75` and `src/hippo/web/app.py:58`, plus the
registry entries at `knowledge/public_errors.py:196` and `ingest/managed_activation.py:396`.
`task4-notes.md:45` allows the duplication only while consolidating would drag knowledge
imports into `hippo --help`.
*Fix:* if a leaf module with no imports can hold the constant, use one. Otherwise close the
item explicitly by writing the `hippo --help` import-footprint test `task4-notes.md:43` (N4)
already asks for, so the constraint is pinned rather than remembered.

**13. LOW — the promoted rule refuses `access` beside `session`, but its callers still drop it
silently.** `dense_session._session:182-185` raises `invalid_borrow` when both arrive, which is
what the 4d review asked for. All four callers then pass
`None if session is not None else access` (`ask.py:69`, `simulate.py:161`, `runner.py:165`,
and by construction `rag_all.py:388`), so a caller handing over a mismatched pair still has
its `access` discarded — `_dispatch`'s behaviour, relocated one frame up and now documented in
four places instead of hidden in one. It matters in exactly one of them: `runner.py:167`
builds `EvalAccess(ctx, access, session=query)`, so the eval set would be read under `access`
while retrieval ran under the borrowed session's audience. Unreachable in production (routes
acquire both from the same principal) and no test pins that the two must agree.
*Fix:* either assert the pair agrees at the top of `run_question`, or state the invariant in
the docstring ("callers must not pass a session proved for a different audience") and add one
test. Not worth forcing a code change; it is the last unstated half of the promotion.

**14. LOW — "no readable text" is gone from the Library page for one missing word.**
`src/hippo/ingest/pipeline.py:393` raises
`ValueError("no readable text was found in this source")`, which is not one of the closed
input validators, so `_legacy_failure` now stores `ValueError: indexing failed; inspect local
logs`. The worker recorded this cost and deliberately did not take the fix
(`evidence-pa4e.md:226-229`), correctly — it changes what the function raises and no decision
asked for it. But the sentence is bounded and actionable, which is the whole test the rule
applies.
*Fix:* `raise ReadError("no readable text was found in this source")`, and put
`test_a_source_with_no_text_fails_with_a_message` back. Take it together with
`task4-notes.md:50` (`pipeline.py:137,142,214` and the other bare raises) as one small
pipeline pass.

**15. LOW — per-lane containment covers one cause, not the class.**
`src/hippo/ingest/pipeline.py:639-643` catches only `ManagedDispatchError`. A `Busy`, a store
failure or anything else from `start_indexing` still propagates out of the submission loop and
leaves the lanes ordered after it cleared, `queued` and jobless — the state 3b finding 4
describes, reached by a different cause. The docstring is accurate about what the code does;
the finding is that the containment claim in the evidence reads broader than the code.
*Fix:* widen to `except Exception` with the same bounded log line, or narrow the claim in the
docstring. Widening is the safer of the two: the loop's whole purpose is that one lane cannot
take the others down.

**16. INFO — `evidence-pa4e.md` residual 6 is stale.** It says `evidence-pa4cfix.md` "does not
exist anywhere in the tree". It does:
`ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa4cfix.md`, 455 lines, at
HEAD. It was created after 4e's base `0bc378c`, so the worker's statement was true of its own
worktree. Worth correcting so a later reader does not re-derive it.

**17. INFO — `ManagedActorRequired`'s message still says "rebuilt" on the delete path.**
3b review finding 3, restated as `evidence-pa4e.md` residual 9; no brief has owned it. The
message reaches a client only through `app.py:84`'s fixed permission body, so nothing is
disclosed — it is a wording bug in the exception and the local log.
*Fix:* one string, whoever next owns `managed_activation.py`.

**18. LOW — six unguarded isinstance `ValueError` catches remain on the user, role and account
paths.** `src/hippo/web/routes/users.py:337,363,403,434,457` and `src/hippo/web/auth.py:382`
wrap `store.create_user` / `update_user` / `create_role` / `update_role` in `except ValueError`
and print `str(exc)`; `users.py:228,250` do the same through
`getattr(exc, "detail", str(exc))`. Bounded today — those store methods raise the plain
`ValueError` their own validators raise, which is the caller's own field — but nothing keeps a
`_StorageFailure` (`ingest/accepted_inputs.py:97`, a `ValueError` subclass) or a future
subclass out, and `api.py:88`'s docstring says in as many words that the guard is what makes
"nothing else does" true rather than hopeful.
*Fix:* the same `if not caller_error(exc): raise` line, six times, when `users.py` is next
owned. Lowest priority of the twenty: a hardening, not a live leak.

**19. LOW — `analyze.py` and `graph.py` still bind `retrieval_session` at import.**
`src/hippo/web/routes/analyze.py:43` and `src/hippo/web/routes/graph.py:40` use
`from ...knowledge.dense_session import retrieval_session`, so `test_managed_web_surfaces.watch`
needs a per-module patch point while the four promoted callers share one. Recorded as open by
both 4e and 4f; neither owned both files.
*Fix:* `from ...knowledge import dense_session` and call through the module, matching
`ask.py:32`. Two lines, mechanical, and it simplifies one recorder.

**20. LOW — `/partials/sources` answers a whole page on a mapped failure.** The addendum's F1
uses one `failure.html` for all six page routes (`evidence-pa4e.md` residual 11), so an htmx
swap that expected a table fragment now receives a full document. Strictly better than the
JSON blob it answered before, and not worth blocking on.
*Fix:* a `partials/failure.html` for the two partial routes, chosen by the same
`render.wants_html` branch.

## What I would do next, in order

1. Findings 1, 2 and 3 — three small independent edits with a test each. They are the only
   findings on a client path or in a log.
2. Finding 4 — widen the PA5 and PA6 CHECK lines. Cheap, and it is what makes findings 1 to 3
   stay fixed. (Finding 5, the Neo4j run, closed itself while this review was open.)
3. A sentence in `neo4j-parity.md` saying whether run 3's tree is still current after the
   layering merge, so the next reader does not have to reason it out.
4. Everything else as one cleanup batch, with finding 19 and the layering item
   (`task4-notes.md:100-102`) folded in.
