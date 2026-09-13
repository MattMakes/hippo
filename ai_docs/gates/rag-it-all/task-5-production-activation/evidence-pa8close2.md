# Evidence: PA8 closure batch 2 (the enumerated residue)

Worker `opus-21`, 2026-09-13. Worktree `.worktrees/pa8close2`, branch `wp/pa8close2`, base
`rag-it-all-tibs` **`a7e6a06`** ("Record PA1-PA7 MET at 9770c00, widen PA2, amend CD7/CD8 and record
Neo4j parity run 5"). Brief: `ai_docs/handoffs/briefs/pa8-closure-2.md`. Work list: the 14 blocking
rows of `ai_docs/reports/2026-09-13-pa8-resign.md`, through its "Routes to a signature" items (1) and
(2), plus its two evidence nits.

Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, `mcp==2.1.1` (pinned after install).
`HIPPO_TEST_STORE` explicit on every run, `-o addopts=''`, `-W error`, every run captured to its own
log and read from the summary line. **No Neo4j was used.** CC10 (`backend-developer-23`) is live on
`ingest/managed_activation.py`, `pipeline.py`, `readers.py`, `repos.py`, `web/routes/sources.py`,
`cli.py` and their tests; none of those source files was edited.

## Commits

| # | Hash | Subject | Contents |
|---|---|---|---|
| 1 | `3b93f86` | Assign the PA8 residue to named owners and correct the closure evidence | Route (1): the activation plan's rollout section and the prose-coordinator plan's implementation notes; the two `evidence-pa8close.md` corrections |
| 2 | `14beda7` | Answer a fragment from a failing partial route and pin the simulate denial and the chunk ceiling | Route (2): W20's code and test, the PA4b2-7 and PA3a-8 tests, this file |

## The 14 rows

**CLOSED: 4. ASSIGNED in a plan: 7. OPEN, routed to CC10: 3.**

"Plan" is `ai_docs/plans/rag-it-all-task-5-production-activation.md` unless the row says otherwise.
Plan lines are at `3b93f86`, and code and test lines are at `14beda7`. Neither plan changed between
the two commits.

| ID | Status | Commit | Test or plan line |
|---|---|---|---|
| PA2-2 | **ASSIGNED → Task 16 (performance)** | `3b93f86` | plan `:278`. `knowledge/projection._selected_pairs` gets the review's `by_generation` index when Task 16 benchmarks structural reads |
| PA2-4 | **ASSIGNED → CC10** | `3b93f86` | plan `:279` names CC10 and `rag-it-all-task-5-managed-code-capture.md`, and states the counter: `status.source_view` must attribute code edges by generation membership, gated on the exact selected pair as the relation counter is, before managed code is served |
| PA3a-6 | **OPEN → CC10** | — | The review's one line lands in `managed_activation.ingress_file` (`:265`), a CC10 file. Routing accepted by the orchestrator |
| PA3a-8 | **CLOSED** | `3b93f86` (decision), `14beda7` (test) | Decision at plan `:274`: **keep 1,000**, the value the prose-coordinator plan states (§7 bootstrap limits). Test `test_a_managed_build_past_the_chunk_ceiling_fails_without_managed_state` (`tests/unit/test_managed_pipeline_activation.py:1783`, on PA1/PA3/PA5/PA7) |
| PA3a-9 | **OPEN → CC10** | — | The review's comment belongs at `managed_activation.managed_eligibility` (`:114`), a CC10 file. The broader guard it must name, `knowledge/build_authority._source_control` (`:77`), is on this brief's do-not-touch list. The fixer should also reconcile `web/routes/graph.py:167` ("`managed_eligibility` is the one definition of "managed""), a third statement of the same rule. Routing accepted |
| PA3a-11 | **ASSIGNED → Task 14** | `3b93f86` | plan `:280`: a public helper beside `EMBED_PREFIXES` in `ollama.py`, with both callers moved onto it |
| PA3b-6 | **ASSIGNED → Task 9A** | `3b93f86` | plan `:281`: parameterise the Ladybug restart-sweep prefix |
| PA4b2-7 | **CLOSED (unreachable, pinned)** | `14beda7` | `test_simulating_another_users_saved_result_is_a_404_not_a_mapped_500` (`tests/unit/test_web_analyze.py:108`, on PA6) |
| PA4b2-9 | **ASSIGNED → Task 9** | `3b93f86` | plan `:282`: a public build/observe seam on `AppContext`, with both tests moved onto it |
| W15 | **OPEN → CC10** | — | The review's `except Exception` lands in `pipeline._submit_lane` (`:634`), a CC10 file. Routing accepted |
| W20 | **CLOSED** | `14beda7` | `web/app.py` `public_failure_handler` (`:145`) renders the new `templates/partials/failure.html` for a `/partials/` path inside the same `render.wants_html` branch. Test `test_a_partial_route_answers_a_fragment_when_a_mapped_failure_escapes` (`tests/unit/test_managed_web_surfaces.py:1310`, 2 cases, on PA6 and PA7). RED then GREEN |
| T2 | **CLOSED** | `3b93f86` | The scan half was already closed by `db7aa77`. The version half is the two sentences coordinator review minor 7 asked for, at `ai_docs/plans/rag-it-all-task-5-prose-coordinator.md:170` (versions are fixed constants; `workers` and `embedding_cache` were added). `task4-notes.md:119` corrected (see deviation 1) |
| D4 | **ASSIGNED → Task 16** | `3b93f86` | plan `:271` (`answer_withheld`) |
| D5 | **ASSIGNED → Task 16** | `3b93f86` | plan `:272` (gold means, `accuracy: None` beside `errors: N`) |

Plan `:266` now reads "owns all five" where it said three.

## Corrections the orchestrator asked for

- `evidence-pa8close.md:30`: "CLOSED: 15" is now **"CLOSED: 18. OPEN: 1."**, the count of its own table (17 finding rows plus the deferral row), with a dated note. That deferral row claims all five DEFERRED items were assigned on three lines. It was not rewritten, because the brief limits that file to two corrections, but D4 and D5 are assigned as of `3b93f86`.
- `evidence-pa8close.md:48`: the PA3b-8 test is now named `test_a_refresh_interrupted_by_a_restart_is_retired_without_losing_g1`.
- `task4-notes.md:119` now says minor 7 was not recorded by the fixer, and that this batch writes its two sentences.

## Decisions and deviations

1. **`task4-notes.md` is untracked.** `ai_docs/handoffs/` is `??` in the root tree, so the file is not in this worktree and cannot be committed on `wp/pa8close2`. The one-line correction was made in the root tree's copy and left uncommitted.
2. **One ownership question, answered.** `horch blocked` does not exist in this install, so the question went through `horch tell orchestrator`. The answer, verbatim: *"(b) GRANTED: ONE append-only test at the END of tests/unit/test_managed_pipeline_activation.py (CC10 will edit rows near :201-206/:305/:313/:1408 later, so append only, no other edit to that file). Keep 1,000 per the prose-coordinator plan section 7 and write the decision into the activation plan. The three OPEN-routed rows are accepted; I route them to CC10."* The test is the file's last function and uses only names the module already imports.
3. **Owners are task numbers, not "whoever next owns X".** The first sign-off ruled that wording is "not a task, so this is OPEN, not DEFERRED" (wrap-up 18). Each owner comes from the task's **Modify** line in `docs/rag_it_all.md`:
   - `ollama.py`: Task 14 is the only later task that lists it, and for profile support, which this is.
   - `context.py`: Task 9 is the next task that lists it. Tasks 9A and 13 list it too.
   - The Ladybug sweep: Task 5A is the only task that lists `store/ladybug.py`, and its ledger is 6/6 MET per the checkpoint. The owner is Task 9A, which lists the stores and fakes and rebuilds the lease and recovery machinery the sweep belongs to.
4. **PA2-4's counter lives in `status.py`**, which is not in CC10's exclusive-files row of the code-capture plan (§12). The brief routes it to CC10 by name, and the plan sentence follows the brief.
5. **PA3a-8's stored code is `operation_failed`.** The coordinator refuses past `max_chunks` with a bare `ValueError("Plain source exceeds complete chunk budget")`, which `managed_activation.FAILURES` maps to `UNKNOWN_CODE`. That is closed and bounded, which is what the review asked for, so the test asserts membership in the closed `(code, message)` set rather than one code. A more specific code (for example `source_too_large`) would change `prose_generation.py` or `FAILURES`. That is not this batch's file, and the review did not ask for it. Not a row.
6. **PA4b2-7 is a pin, not a code change.** The reviewing report offered "one line in `_simulate` or an `except EvalAccessDenied` ahead of the mapper", and the re-sign-off's route is the pin. No `public_errors` row was added, because the report did not ask for one. `tests/unit/test_rag_replay_access.py:138` `test_saved_analysis_routes_require_the_evaluation_owner[simulate]` already asserted the same 404, but that file is on no PA line, which is why both reviewers read the finding as unpinned. The new test sits on PA6, runs with `raise_server_exceptions=False` so a 500 would be seen as a status, and asserts the exact 404 body and no `operation_failed`.
7. **W20 selects the fragment by path prefix.** It checks `/partials/`, the same way `render.wants_html` treats `/api`: deterministic, and independent of whether htmx sent `HX-Request`. The page routes and the JSON twin are unchanged: the 12 existing F1 cases pass in the RED run, before the fix.
8. **The brief's expected FILES did not match two findings.** It anticipated "one web module for W15" and "`context.py` or `status.py` comments for PA3a-9". W15's fix is in `pipeline.py`, and PA3a-9's named site is `managed_eligibility`; both are CC10's. No comment was added to `context.py` or `status.py`, because neither review named them.
9. **Do-not-fix items untouched:** W12, 4b-i F2, 4b-i F6, PA3a-10.
10. **Three commits, not two.** The third changes only this file: it names the second commit's hash and states which revision the line numbers cite. That is the same follow-up shape `evidence-pa8close.md` used (`779d8c7`).

## Runs

AnyIO handling: PA2 and PA4 ran verbatim with a bare `-W error`. PA6 ran verbatim with the ledger's own form (b), `-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`. Single-file runs of `test_managed_web_surfaces.py`, `test_web_analyze.py` and `test_web_busy_pages.py` use form (b) too, because each imports `fastapi.testclient` at module level. `test_managed_pipeline_activation.py` runs with a bare `-W error`. No marker was added and nothing was suppressed.

### Baseline at `a7e6a06`, before any edit

| Line | Result | Log |
|---|---|---|
| PA2, verbatim | 105 passed, 1 skipped — EXIT 0 | `/tmp/hippo-pa8close2-base-pa2.log` |
| PA4, verbatim | 117 passed — EXIT 0 | `/tmp/hippo-pa8close2-base-pa4.log` |
| PA6, verbatim, form (b) | 728 passed — EXIT 0 | `/tmp/hippo-pa8close2-base-pa6.log` |

### RED, and tests that were green on arrival

| Test | Result | Log |
|---|---|---|
| W20, both partial routes (with the 12 F1 page/JSON cases alongside) | **RED**: 2 failed, 12 passed. The failing assertion is `"<html" not in response.text`: the partial answered `<!doctype html>` | `/tmp/hippo-pa8close2-red-w20.log` |
| PA4b2-7 | green on arrival, 1 passed. The code is already correct; this pins it | `/tmp/hippo-pa8close2-red-pa4b2f7.log` |
| PA3a-8 | green on arrival, 1 passed. The ceiling already refuses; this pins the lane's half | `/tmp/hippo-pa8close2-red-pa3af8.log` |

**PA3a-8 discriminates; it is not green by accident.** Two throwaway probes, neither committed:

- The same test with `--log-cli-level=WARNING` shows the build failing on the ceiling: `Managed build did not publish: ... code=operation_failed exception=ValueError` (`/tmp/hippo-pa8close2-probe-pa3af8-log.log`).
- The same source and the same `LONG_TEXT`, built without lowering `max_chunks`, publishes: `status == "ready"` with an active generation, 1 passed. That probe was an untracked `tests/unit/test_zz_probe_pa8close2.py`, deleted right after its run (`/tmp/hippo-pa8close2-probe-pa3af8-publishes.log`).

### GREEN at the tip of `wp/pa8close2`

The same lines verbatim, plus every touched test file not on those lines, with the code above in
place.

| Line | Result | vs baseline | Log |
|---|---|---|---|
| W20 test plus the 12 F1 cases | **14 passed — EXIT 0** | RED 2 failed → 0 | `/tmp/hippo-pa8close2-green-w20.log` |
| PA2, verbatim | **105 passed, 1 skipped — EXIT 0** | 0 (no new test on PA2) | `/tmp/hippo-pa8close2-green-pa2.log` |
| PA4, verbatim | **117 passed — EXIT 0** | 0 | `/tmp/hippo-pa8close2-green-pa4.log` |
| PA6, verbatim, form (b) | **731 passed — EXIT 0** in 56.87s | +3: W20 ×2, PA4b2-7 ×1 | `/tmp/hippo-pa8close2-green-pa6.log` |
| `tests/unit/test_managed_pipeline_activation.py` (PA1/PA3/PA5/PA7 file), Fake | **109 passed, 2 skipped — EXIT 0** | +1: PA3a-8 | `/tmp/hippo-pa8close2-green-pipeline.log` |
| `tests/unit/test_web_busy_pages.py` (polls both partial routes; on no PA line), form (b) | **5 passed — EXIT 0** | — | `/tmp/hippo-pa8close2-green-busypages.log` |
| PA3a-8's test alone, **Ladybug** (PA7 runs its file there) | **1 passed — EXIT 0** | — | `/tmp/hippo-pa8close2-ladybug-pa3af8.log` |

PA1, PA3, PA5 and PA7 were not re-run as whole lines, because the brief names PA2, PA4 and PA6. The
one change that reaches them is the appended PA3a-8 test, green above on Fake and alone on Ladybug.
`test_managed_web_surfaces.py` is also on PA7, and its W20 cases touch no store code.

### Ruff

- `.venv/bin/ruff check` and `ruff format --check` over `src/hippo/web/app.py` and the three test files: `All checks passed!`, `4 files already formatted`.
- The PA8 static CHECK line, verbatim, after both route (1) and route (2): EXIT 0, `All checks passed!`, `136 files already formatted` (`/tmp/hippo-pa8close2-pa8static-1.log`, `/tmp/hippo-pa8close2-pa8static-2.log`).
- `ruff format --check` also ran over every Markdown file this batch wrote: both plans, `evidence-pa8close.md` and this file.

## Files

Created:
- `src/hippo/web/templates/partials/failure.html`
- this file

Modified:
- `src/hippo/web/app.py` (`public_failure_handler`: template choice and one docstring sentence)
- `tests/unit/test_managed_web_surfaces.py` (`PARTIAL_ROUTES` and one test)
- `tests/unit/test_web_analyze.py` (one test)
- `tests/unit/test_managed_pipeline_activation.py` (one test appended at the end, nothing else)
- `ai_docs/plans/rag-it-all-task-5-production-activation.md` (rollout section only)
- `ai_docs/plans/rag-it-all-task-5-prose-coordinator.md` (implementation notes only)
- `ai_docs/gates/rag-it-all/task-5-production-activation/evidence-pa8close.md` (two corrections)
- the root tree's untracked `ai_docs/handoffs/briefs/task4-notes.md` (one line)

Not touched: `GATES.md`, `docs/`, the checkpoint, `src/hippo/store/*`, `src/hippo/knowledge/*`, and every CC10 source file.
