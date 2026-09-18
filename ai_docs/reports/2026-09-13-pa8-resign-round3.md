# PA8 re-sign-off, round 3: the residue after closure batch 2 and CC10

Reviewer `architect-reviewer-20`, 2026-09-13. Root tree `/Users/mascott/projects/hippo`, branch
`rag-it-all-tibs`, HEAD **`492cb4c`** ("Amend CD2 with the pipeline-level destructive-operation
refusals CC10 proved"), confirmed at the start, after the runs and again before this file was
written. Closure batch 2 merged at `4c01df7`; CC10 merged at `9a474e4`. Brief:
`ai_docs/handoffs/briefs/review-pa8-resign.md`, ROUND 3 paragraph. Read-only apart from this file:
no source, test, plan, ledger or evidence document was edited. **No Neo4j was used.**

Scope, per the brief: the 14 ids the second sign-off (`2026-09-13-pa8-resign.md`) left blocking,
plus anything the CC10 merge touched among the do-not-fix items. Every other row is cited from the
first sign-off (`2026-09-12-pa8-signoff.md`) and the second. Row ids follow those reports. Code was
read by symbol at `492cb4c`; line numbers below are at `492cb4c`.

## Verdict

**`PA8: NOT SIGNABLE (PA2-4)`**

Of the 14 ids: **7 CLOSED** (one of them unreachable and pinned), **6 DEFERRED by the plan** to a
numbered task that is not yet done, and **1 OPEN**. The open row is PA2-4. The plan assigns it to
CC10, CC10 merged without making the change, and no other plan names an owner.

**A hard precondition that is not a row.** The `[x]` boxes for PA1 and PA3–PA7 certify `9770c00`,
not `492cb4c`. Both merges since then changed files on those CHECK lines, and CC10 changed
production dispatch (section 2). A full `--reverify` at HEAD must precede any PA8 signature, even
once PA2-4 is resolved. PA1's CRITERIA sentence also needs the amendment `492cb4c` gave CD2.

PA2-4 is minor and, by inspection, unreachable on every graph a production `source_view` receives.
The verdict follows from the clause as written, not from severity.

## Runs

Root tree at `492cb4c`, `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6. Each command's
output was captured to a log, and results were read from the summary line.

| Line | Result | Log |
|---|---|---|
| PA2, verbatim from `GATES.md` (Fake, bare `-W error`; none of its four files imports `fastapi.testclient` at module level) | **105 passed, 1 skipped in 2.68s, EXIT 0**. Same count as the checker and round 2 | `/tmp/hippo-pa8r3-pa2.log` |
| PA8 static, verbatim, both commands in one subshell so the log holds both | **EXIT 0**. `All checks passed!` and `136 files already formatted` | `/tmp/hippo-pa8r3-pa8static.log` |
| Call-site sweep `rg -n 'query_session\(\|query_access\(\|graph_for\(\|ctx\.graph\(' src/hippo` | **58 rows**. With line numbers stripped, the set is identical to round 2's sweep at `a7e6a06`, which was identical to `c893a95`, the revision `session-audit.md` classifies | `/tmp/hippo-pa8r3-callsites.log` |
| Closing tests by name, Fake, bare `-W error`: PA3a-6 (3 cases), W15, PA3a-8 | **5 passed, EXIT 0** | `/tmp/hippo-pa8r3-closing-ingest.log` |
| Closing tests by name, Fake, form (b) (`test_web_analyze.py` and `test_managed_web_surfaces.py` import `fastapi.testclient` at module level): PA4b2-7, W20 (2 cases) | **3 passed, EXIT 0** | `/tmp/hippo-pa8r3-closing-web.log` |
| PA7 | **Not re-run**, per the brief. The ledger's EVIDENCE is `742 passed in 4111.53s (1:08:31)`, from log-3 at `9770c00` (section 2) | `/tmp/hippo-orch-pa-gates-3.log` |

## 1. The 14 rows at HEAD

### CLOSED — 7

| # | Sev | Commit | Test or artifact (gate) | Verified at HEAD |
|---|---|---|---|---|
| PA3a-6 | minor | `e954eb7`, merged `9a474e4` | `test_a_saved_file_not_named_as_its_row_says_is_refused_before_any_build` with 3 cases: `file` `notes.md`→`paper.pdf` (the review's own scenario, through the plain lane), `file` `orders.py`→`orders.pyc` (code lane), `archive` `bundle.zip`→`other.zip`. In `test_managed_code_activation.py`, on CD8/CD9 of the code-capture ledger and on **no PA line** | `ingress_file(ctx, source_id, *, stored_name=None)` refuses "The saved file is not the one this source recorded" when the single entry's name differs. `_recorded_name` passes exactly the review's `safe_stored_name(stored_filename(source))` for `file` and `archive`. `text` passes `None`, and a `repo` has no saved file. Both `run_managed_build` (plain, `:655`) and `_run_code_build` (`:693`) pass it. The test asserts `ManagedIngressError`, that no coordinator was called, and that no knowledge directory exists |
| PA3a-8 | minor | `3b93f86` (decision), `14beda7` (test) | Decision at activation plan `:274`: keep 1,000, per prose-coordinator §7. Test `test_a_managed_build_past_the_chunk_ceiling_fails_without_managed_state` (`test_managed_pipeline_activation.py:1788`; PA1, PA3, PA5, PA7) | The test first asserts `build_options(ctx).max_chunks == 1000` and `pipeline.MAX_CHUNKS == 20_000`, so a silent change to either constant fails it. It lowers the ceiling to 1 and then asserts: row `failed/failed`, `managed` false, no active pointer, an error inside the closed `(code, message)` set, no `Generation` row, and no source text sent to the model. The stored code is `operation_failed` (evidence deviation 5), which is closed and bounded as the review asked. The discrimination probe is recorded in `evidence-pa8close2.md` |
| PA3a-9 | minor (doc) | `e954eb7` | Documentation | `managed_eligibility`'s docstring names `source["managed"]` as the dispatch and cleanup authority it shares with `store.legacy_source_cleanup` (verified: that decorator calls `store.source_is_managed`, which is `bool(source.get("managed"))`). It names `_source_control`'s `managed or active_generation_id` (`build_authority.py:77`, verified) as the deliberately broader build guard, and says why they agree (the flag flips at staging start, which `source_serves_legacy`'s docstring also states). Nit, not a row: `web/routes/graph.py:167` still says "`managed_eligibility` is the one definition of "managed"", which the new docstring contradicts. `evidence-pa8close2.md` asked CC10 to reconcile it; `graph.py` was not CC10's file |
| PA4b2-7 | LOW (latent) | `14beda7` | **Unreachable, pinned**: `test_simulating_another_users_saved_result_is_a_404_not_a_mapped_500` (`test_web_analyze.py:108`; PA6) | An outsider posts another user's `result_id` to `/api/simulate` with `raise_server_exceptions=False`. The test asserts 404 `{"detail": "no such result"}`, no `operation_failed` and no private text. If any read on `_simulate`'s path raised `EvalAccessDenied` instead of answering `None`, the route's `except (ValueError, …)` would map it to 500 and this test would fail |
| W15 | LOW | `e954eb7` | `test_one_lane_that_cannot_start_never_strands_the_bulk_lanes_behind_it` (`test_managed_code_activation.py`; CD8/CD9, **no PA line**) | `pipeline._submit_lane` catches `Exception` (`noqa: BLE001`) and logs one warning that names the source and not the cause. Its docstring cites the finding. The test raises a `RuntimeError` carrying a path from the first lane, then asserts the return is 1, the lane after it was submitted, the source id is logged and the path is not. That is the review's preferred fix ("widen to `except Exception` with the same bounded log line") |
| W20 | LOW | `14beda7` | `test_a_partial_route_answers_a_fragment_when_a_mapped_failure_escapes`, cases `/partials/sources` and `/partials/sources/s1/status` (`test_managed_web_surfaces.py:1310`; PA6, PA7) | Inside `public_failure_handler`'s `wants_html` branch, a `/partials/` path renders `partials/failure.html`, which is a fragment with only `{{ error }}` and `{{ failure_code }}`. The test asserts 500, `text/html`, the bounded sentence, the code, no private text and no `<html`, and that `/` still answers a whole document. The review said "chosen by the same `render.wants_html` branch"; a path test inside that branch meets it |
| T2 | LOW | `db7aa77` (scan), `3b93f86` (versions) | Prose-coordinator plan `:170` | The scan half: `_source_control` reads the Source row alone, and its comment records the retired scan. The version half: `:170` names the fixed constants (`_configuration`'s `input_pipeline`, `_generation`'s `parser_version`/`linker_version`), says §3's field list is superseded on that point, and records the added `workers` field and `embedding_cache` parameter. `task4-notes.md:119` is corrected, but only in the root tree's untracked copy |

### DEFERRED by the plan — 6

Every assignment is in `ai_docs/plans/rag-it-all-task-5-production-activation.md`'s "Rollout and
rollback boundary", written by `3b93f86`. Each owner is a numbered task in `docs/rag_it_all.md`
that is not complete and whose Modify line covers the change.

| # | Plan line → owner | Owner's Modify line (`docs/rag_it_all.md`) | Code at HEAD |
|---|---|---|---|
| PA2-2 | `:278` → Task 16, performance | Task 16 (`:1525`), step 3 benchmarks 10k/100k/1m | `projection._selected_pairs` unchanged |
| PA3a-11 | `:280` → Task 14 | "`ollama.py` only where profile/token counting support is required" | Unchanged: `ollama.py:240`, `managed_activation.py:41,240` and `dense_session.py:14,227`. CC10 edited `managed_activation.py` and correctly left the import alone |
| PA3b-6 | `:281` → Task 9A | "stores/fakes" | Unchanged: `ladybug.py:722` splices `REFRESHING_PREFIX` into the Cypher text; `memory.py:205` passes `$prefix` |
| PA4b2-9 | `:282` → Task 9 | "`context.py`" | Unchanged: `test_query_snapshots.py:202,211` and `test_query_authorization_boundary.py:225,232` patch `AppContext._build_structural_graph` (`context.py:386`) |
| D4 | `:271` → Task 16 | Task 16 owns release notes (`:266`: "owns all five") | Not code |
| D5 | `:272` → Task 16 | same | Not code |

### OPEN — 1

**PA2-4 (minor, latent): `status._managed_source` attributes `CODE_EDGE_KINDS` arrows by node
membership.** The counter is unchanged at HEAD:
`edge.kind in CODE_EDGE_KINDS and graph.node_ids[edge.src] in node_ids`, where the relation counter
below it checks `pair in row.source_generations`.

**The plan's assignment no longer names an owner.** Plan `:279` assigns the row to CC10 "before
managed code is served". Four facts void it:

1. CC10 merged at `9a474e4` without touching `status.py`: `git diff --stat 4c01df7..9a474e4` has no
   `status.py`, and `evidence-cc10.md` lists `status.py` as untouched.
2. CC10 handed the row back in writing (`evidence-cc10.md`, finding 1): "`status.py` is frozen for
   this slice; the row needs an owner before managed code is served widely."
3. No code-capture slice can take it. The code-capture plan never mentions PA2-4 (a grep for `PA2`
   and `source_view` finds nothing). Its §12 gives CC10 `managed_activation.py`, `pipeline.py`,
   `readers.py` and a new test file, and gives CC11 "this plan and `GATES.md` only".
4. Closure batch 2's own rule rejects a completed task as an owner. Its deviation 3 refused Task 5A
   for PA3b-6 because 5A's ledger is MET.

**Reachability.** CC10's finding 1 says the row is reachable now. By inspection it is not, on every
graph a production `source_view` can receive:

- `source_view` uses the caller's session or, with none, `ctx.graph_for(access, structural=True)`.
  No production `QuerySession` wraps a non-structural graph. Its five constructors wrap
  `query_access` (`query_access.py:154`, `eval_access.py:164`, `changeset_access.py:71`), a
  `retrieval_session` query (`ask.py:79`) or a routed structural owner (`dense_session.py:274`).
  `query_session` and `query_access` default to `structural=True`, and no call in `src/hippo` passes
  `structural=False`. `graph_for` itself defaults to `structural=False`, but its only callers outside
  `context.py` are `status.py:47` and `query_access.py:85-87`, both structural unless told otherwise.
  `session-audit.md` classifies the same 58 low-level call sites.
- `_build_structural_graph` composes `load_generation_graph(generations={}, legacy_source_ids=…)`,
  which holds untagged legacy rows only, with `project_managed_graph(…, structural=True)`.
- `project_managed_graph` has one arrow emitter, `relation()` (`projection.py:520`). It is called
  only for `DEFINED_IN` (`:545`) and for assertion predicates (`:562`). `DEFINED_IN` is not in
  `CODE_EDGE_KINDS` (`codegraph/model.py:44-55`), and
  `test_relation_predicates_cannot_be_counted_twice_as_code_edges` pins the predicates as disjoint
  from those kinds.
- `compose_graphs` raises "Cannot compose colliding graph node identities". A legacy arrow's source
  vertex therefore cannot be a managed row's contributed node. A published source is not in the
  legacy lane, so its own untagged rows are not loaded either.
- Consequence: the first `edge_counts` Counter is empty for every managed row at HEAD.
- The non-structural `_build_managed_graph` does load `generations=selected` (`context.py:301-309`),
  so a managed code generation's native `CODE_EDGE` rows are in that graph. No production caller
  hands that graph to `source_view`.

**The invariant is not pinned.** `test_shared_code_object_counts_for_every_contributing_selected_source`
asserts symbols and passages, not `edges_by_kind`. Nothing fails the day a slice projects native code
edges into the structural graph, and that is the day the counter becomes wrong. Plan `:279`'s literal
precondition has also lapsed: CC10 serves managed code sources (web repo form, `/api/sources/repo`,
uploads, gated CLI). It holds in effect only because the structural graph carries none of their code
edges.

**What would close it, cheapest first:**

1. **Pin it (unreachable and pinned).** One test publishes a code source through CC10's dispatch, or
   builds two generations sharing a code object that each carry a native `CODE_EDGE`. It opens a
   structural session and asserts that no `code_out` arrow whose kind is in `CODE_EDGE_KINDS`
   starts at a node named by `structural_code_evidence` or `structural_object_evidence`. Equivalently,
   every managed row's `edges_by_kind` keys are disjoint from `CODE_EDGE_KINDS`. Correct plan `:279`
   and `evidence-cc10.md` finding 1 in the same change.
2. **Fix the counter** as the PA2 review proposed: gate code edges on the exact selected pair.
3. **Reassign it in the plan.** No candidate was found. Task 12's Modify line is
   `codegraph/{extract,data_access}.py` and `knowledge/lifecycle.py`, with no `status.py` or
   `projection.py`. This review does not guess an owner.

## 2. Does the ledger record what it claims?

**Every `[x]` has an EVIDENCE line from the reverify pass.** No EVIDENCE line has changed since
`a7e6a06`. The only ledger commit after it is `1f3d524`, which touches the Status line alone. Round
2's character-for-character match of all seven outputs against the PASS lines of
`/tmp/hippo-orch-pa-gates-3.log` therefore stands.

**The Status line names the revision**, `9770c00`, with the log path. `1f3d524` corrected two of
round 2's three recording deviations: the line now says "started 2026-09-12 06:33 -0700, finished
07:44; PA7's Ladybug line 1:08:31". The third, EVIDENCE lines carrying `path=…` where the format asks
for a revision, remains; the Status line still compensates for it.

**PA7's evidence started at `9770c00`, not at HEAD.** Round 2's mtime proof stands: the process
started at `9770c00` and is not the `c893a95` run. But `9770c00` is not `492cb4c`. Round 2 kept the
evidence on the premise that no PA-line file had changed, and that premise no longer holds:

| Gate | Files on its CHECK line changed since `9770c00` |
|---|---|
| PA1 | `test_managed_pipeline_activation.py` |
| PA2 | none (and re-run green at HEAD above) |
| PA3 | `test_managed_pipeline_activation.py` |
| PA4 | none on the line; its managed lifecycle and concurrency tests exercise `pipeline.py` and `managed_activation.py`, which changed |
| PA5 | `test_managed_pipeline_activation.py` |
| PA6 | `test_managed_transport_activation.py`, `test_managed_web_ingress.py`, `test_managed_web_surfaces.py`, `test_web_analyze.py` |
| PA7 | `test_managed_pipeline_activation.py`, `test_managed_transport_activation.py`, `test_managed_web_ingress.py`, `test_managed_web_surfaces.py` |

The source files that changed are `ingest/managed_activation.py` (294 lines), `ingest/pipeline.py`,
`ingest/repos.py`, `web/routes/sources.py`, `cli.py`, `web/app.py` and the new
`templates/partials/failure.html`. CC10 widened eligibility and dispatch, which is "shared routing"
under the ledger's own rule ("reruns the affected focused gate and PA7/PA8 when persistence or
shared routing changed").

Nobody has run a whole PA line at `492cb4c` except this review's PA2 and static runs:

- closure batch 2 ran PA2, PA4 and PA6 at `14beda7`, before CC10 landed;
- CC10 ran its regressions at its worktree tip, before the merge;
- `test_managed_pipeline_activation.py` changed on both sides of `9a474e4` (CC10 adapted
  assertions; batch 2 appended one test), and the merged file has run at HEAD only through this
  review's by-name selection.

**PA1's CRITERIA and the ledger scope no longer describe HEAD.** PA1 says "only pasted text and the
closed plain-prose extension set opt in; unsupported inputs preserve legacy behavior". At HEAD a
repository, a `.zip` archive and a code file opt in with an actor, and CC10 adapted PA1's own
`test_eligibility_reads_the_saved_source_kind_and_stored_filename` to `eligible_legacy`. The Scope
line's "repository/rich managed extraction … remain outside this ledger" is true of this ledger's
tests but not of the behavior its PA1 box certifies. `492cb4c` amended CD2 for the same merge; PA1
needs the equivalent sentence pointing at the code-capture ledger's CD8.

**Neo4j parity is still current.** `git diff --stat 9770c00..HEAD -- src/hippo/store` is empty, so
run 5 covers every store lane.

**PA8 is `[ ]` with no EVIDENCE line**, which is correct.

## 3. The do-not-fix items were left alone

Three of the four live in files CC10 or closure batch 2 edited, so each was re-checked at HEAD.

| Item | Touched file | Evidence at HEAD |
|---|---|---|
| W12, three `authorization_changed` spellings | `cli.py` (CC10), `web/app.py` (batch 2) | `cli.py:75 DENIED_CODE`, `mcp_server.py:176 DENIED_CODE` and `web/app.py:58 AUTHORIZATION_CHANGED` are all present. `git log -S'authorization_changed' 1e2f112..HEAD -- src/hippo` is empty. `cli.py`'s only hunk since `a7e6a06` is `cmd_index`'s git-URL branch; `web/app.py`'s is the template choice. Both pins are present: `test_the_three_copies_of_the_denial_code_are_the_same_string` (`test_managed_transport_activation.py:839`), `test_hippo_help_imports_no_serving_machinery` (`test_import_order.py:61`) |
| 4b-i F2, traceback at DEBUG only | none | `pages.py:136` `log.debug("ask failure detail [%s]", operation, exc_info=True)`. `pages.py` is unchanged since `a7e6a06`; `git log -S'exc_info' 1e2f112..HEAD` on it is empty |
| 4b-i F6, delete's uniform 404 | `web/routes/sources.py` (CC10) | `delete_source` still maps `AuthorizationChanged` to `404 "no such source"` (`:615-618`). CC10's hunks are `new_managed_source`'s docstring, `repo_form` and `/api/sources/repo` only |
| PA3a-10, `present()`'s locked transaction per call | `ingest/managed_activation.py` (CC10) | `present` is unchanged: no diff line touches its `def`, `store.transaction()` or `_lock_source`. CC10 added callers (`_run_code_build` `:695`, `:701`) and code phases that reach it through `_present_progress`. That is more of the same pattern, not a fix |

## 4. Ruling on the clause

The rule: SIGNABLE only if every remaining row is CLOSED, DEFERRED by the plan to a numbered task,
or closed as unreachable with a pinned invariant.

- **CLOSED:** PA3a-6, PA3a-8, PA3a-9, W15, W20, T2.
- **Unreachable and pinned:** PA4b2-7.
- **DEFERRED by the plan:** PA2-2, PA3a-11, PA3b-6, PA4b2-9, D4, D5.
- **None of the three:** PA2-4. It is unreachable at HEAD but not pinned, and its only plan owner is
  a merged slice that declined it.

The rows outside this round's scope keep the first two reports' dispositions.

**`PA8: NOT SIGNABLE (PA2-4)`**

What would make PA8 signable, in order:

1. **Reverify at `492cb4c`** (precondition, not a row): PA1, PA3, PA4, PA5, PA6 and PA7. PA2 is
   current by this review's run. Amend PA1's CRITERIA and the Scope line for CC10.
2. **PA2-4**: the pin in section 1 (cheapest) or the counter fix, plus corrections to plan `:279`
   and `evidence-cc10.md` finding 1.
3. A round-4 check can then be narrow: the pin and the reverify's EVIDENCE lines.

The alternative from round 2 still applies. If the orchestrator records "no unresolved findings
above LOW", PA2-4 (minor) no longer blocks, but item 1 still does.

## Noticed along the way (not rows, not blocking)

- **D1 is closed in code, and plan `:269` says otherwise.** `cmd_index` sets
  `owner_id = principal.user_id` and `access_role_id` from the principal (`cli.py:328-329`) since
  `39a3ba1` (merged `c9404ed`, an ancestor of `1e2f112`). The first sign-off's "Nothing merged
  changes it" (`:314`) was already wrong at round 1.
- **D2 is closed by CC10, and plan `:270` says otherwise.** `add_repo` takes `build_actor`
  (`e954eb7`), `cmd_index` passes it (`cli.py:332-335`), and the repository form and API use
  `new_managed_source`. The Task 16 release note as written would describe behavior that no longer
  exists.
- **Plan `:250`** ("Authenticated `.pdf`, `.py`, zip, repo, and sample remain legacy") and **`:255`**
  ("unsupported legacy repo/archive") are false at HEAD for `.py`, zip and repo.
- **Two closing tests sit on no PA line.** PA3a-6's and W15's tests live in
  `test_managed_code_activation.py`, which only CD8/CD9 run. A regression would not fail PA1 or PA5.
  Either add that file to PA5/PA7 or record CD8 as their gate.
- **For CC11/CD10, not PA8:** by the same projection reading as PA2-4, the structural graph carries
  no native `CODE_EDGE` arrow from a managed code generation. A converted repository's source row
  therefore shows no `INVOKES`/`IMPORTS` badges, and structural path reads cannot walk its code
  edges. CD9's CRITERIA require only `DEFINED_IN`, so this may be intended, but nothing records it as
  a decision.
- **For CD10, not PA8:** CC10 finding 7 (`repo_form` echoes a `CaptureRefused` message through
  `/?error=`) is the W18 class, on a form route where `upload_form` and `text_form` already do the
  same.
- **Round 2's nits are resolved:** `evidence-pa8close.md`'s count and the PA3b-8 test name,
  `task4-notes.md:119` (untracked root copy only), and the Status line's date and duration
  (`1f3d524`).
- `evidence-pa8close2.md` cites the PA3a-8 test at `:1783`; after CC10's merge it is at `:1788`.
