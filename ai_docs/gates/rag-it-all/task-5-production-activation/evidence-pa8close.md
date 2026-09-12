# Evidence: PA8 closure batch

Worker `opus-17`, 2026-09-12. Worktree `.worktrees/pa8close`, branch `wp/pa8close`, base
`rag-it-all-tibs` **`c893a95`** ("List hippo.ingest.build_run in the import-order proof").
Brief: `ai_docs/handoffs/briefs/pa8-closure.md`. Work list: the "What would make PA8 signable"
items 1-5 of `ai_docs/reports/2026-09-12-pa8-signoff.md` (item 6 is the orchestrator's).

Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, `mcp==2.1.1` (pinned after
install, per the rulebook). `HIPPO_TEST_STORE` explicit on every run, `-o addopts=''`,
`-W error`, every run captured to its own log and read from the summary line. Nothing piped
to `tail`. **No Neo4j was used and the disposable container was never claimed.**

## Commits

Three, not the brief's two. Item 1/4/5 landed first because they touch no code and the audit
refresh had to be stamped at a HEAD; items 2 and 3 are separate because item 2 changes
behaviour and item 3 only adds coverage, and a reviewer of one should not have to read the
other.

| # | Hash | Subject | Contents |
|---|---|---|---|
| 1 | `4e235bb` | Refresh the call-site audit and assign the three deferred rollout notes | Items 1, 4, 5 |
| 2 | `ccb6635` | Guard the last isinstance catches and close the LOW activation batch | Item 2 |
| 3 | (this commit) | Cover the activation gaps the plan's adversarial cases name | Item 3 + this file |

## Findings, one row each

**CLOSED: 15. OPEN: 1.**

| Finding | Status | Commit | Test / artifact |
|---|---|---|---|
| wrap-up 7 (`public_errors.py` points `build_interrupted` at `store/memory.py`) | **CLOSED** | `4e235bb` | Comment now names `store/generations.py`, where `INTERRUPTED_REFRESH_ERROR` is (`:29`). Documentation only; no test |
| wrap-up 16 (`evidence-pa4e.md:438` says `evidence-pa4cfix.md` does not exist) | **CLOSED** | `4e235bb` | Residual 6 now records what was true when written, plus the correction: the file exists, 457 lines, committed by `603dadd` |
| wrap-up 8 (`STAGES[0]` duplicates `INTERRUPTED_REFRESH_STAGE`) | **CLOSED** | `ccb6635` | `managed_activation.STAGES = (INTERRUPTED_REFRESH_STAGE, ...)`, imported on the line that already brought `REFRESHING_PREFIX`. No new test: both spellings are the same interned literal, so an identity test would pass either way |
| wrap-up 9 (the bulk's `Busy` branch skips `view.validate()`) | **CLOSED** | `ccb6635` | `test_a_bulk_refused_as_busy_still_makes_the_revocation_check_its_siblings_make` + `test_a_bulk_refused_as_busy_with_nothing_revoked_still_says_busy`. See "green on arrival" below |
| wrap-up 11 (`managed_evidence_exists` reads the unfiltered inventory) | **CLOSED** | `ccb6635` | The docstring now says the read is workspace metadata for a manager rather than an audience read, which is the sentence the review asked for. Documentation only |
| wrap-up 17 (`ManagedActorRequired` says "rebuilt" on the delete path) | **CLOSED** | `ccb6635` | `test_the_actorless_refusal_names_the_delete_path_it_also_guards`. Wording change; see "deviations" |
| wrap-up 18 (six unguarded isinstance `ValueError` catches on user/role/account paths) | **CLOSED** | `ccb6635` | `test_a_user_or_role_write_that_fails_is_mapped_rather_than_quoted_back_as_a_400` (5 cases), `test_the_role_form_still_shows_the_validators_sentence_but_not_a_subclasses`, `test_a_password_change_that_fails_is_not_redirected_back_with_its_own_words` |
| C1 (`pages.py`'s settings form `str(exc)` unguarded) | **CLOSED** | `ccb6635` | `test_a_settings_form_write_that_fails_is_mapped_rather_than_rendered_into_the_page`; the JSON twin's guard, on the page that shares its store call |
| wrap-up 6 (`CLOSED_INPUT_VALIDATORS` is an unchecked copy) | **CLOSED** | `ccb6635` | `test_the_pipelines_closed_validator_tuple_is_the_public_tables_own_family` compares it with `public_errors._ROWS`' `invalid_source` family, so a sixth validator cannot be added on one side alone |
| wrap-up 13 (the borrow pair is documented, untested) | **CLOSED** | `ccb6635` | `test_run_question_hands_the_dispatcher_a_session_or_an_audience_but_never_both`, including the dispatcher's own `invalid_borrow` refusal of the pair the runner never forms |
| PA4d 2 (nothing makes `changeset_access.apply`'s guard fire) | **CLOSED** | `ccb6635` | `test_a_changeset_naming_managed_evidence_is_refused_by_the_unrestricted_read`. A managed span is in the *authorized* graph (so the draft saves) and not in the *native* one, which is the whole distinction the guard encodes |
| PA2 6 (`compose_graphs`' `populated` shortcut version unasserted) | **CLOSED** | commit 3 | `test_a_lane_holding_only_an_empty_generation_still_owns_the_composed_version` |
| PA3a 3 (single-source `reindex` of an unsupported source with an actor) | **CLOSED** | commit 3 | `test_a_single_reindex_of_an_unsupported_source_with_an_actor_stays_legacy` |
| PA3a 5 (`on_first_connection` / `status.source_view` not in the raw-root test) | **CLOSED** | commit 3 | `test_the_raw_root_and_embedding_cache_appear_only_for_a_managed_build`, extended with both. See the backend note below |
| PA3b 8 (the restart-sweep tests lack the "nothing else moved" half) | **CLOSED** | commit 3 | `test_an_interrupted_refresh_is_retired_and_the_published_generation_keeps_serving`, extended with a `before = row_of(...)` comparison over every field except `stage`, `error`, `updated_at`, plus an explicit `progress_done`/`progress_total` assertion. **No defect exposed**: the sweep leaves them stale, which is what the review expected |
| T3 (verified dense over HTTP; revocation on the verified lane) | **CLOSED** | commit 3 | `test_a_reader_reaches_verified_dense_over_http`, `test_revoking_during_a_verified_dispatch_is_the_generic_permission_answer` |
| S1 (`session-audit.md` one row behind HEAD) | **CLOSED** | `4e235bb` | The audit's three sweep commands re-run at `c893a95`; 58 rows, 0 unclassified, `cli.py:567 _sources_locally` classified |
| The five DEFERRED items (plan assignment) | **CLOSED** | `4e235bb` | Three lines in the plan's "Rollout and rollback boundary" assign the `model_unavailable` behaviour change, the CLI ownership question and `add_repo`'s legacy status to Task 16 |
| **PA2 5 (a relation supported by two generations)** | **OPEN** | — | See below. Owner: *orchestrator: dedicated interleaved-fixture task after `pa8close`* |

## PA2 finding 5 stays OPEN, and why

The fixture was attempted, not skipped. The obvious shape -- publish generation A with
`shared_pair(relationship=True)`, then publish generation B whose `enrich` adds a second
`AssertionSupport` to A's `AssertionVersion` in the same `derivation_group` -- is refused by
the store:

```
ValueError: Sealed assertion proof group cannot gain support
src/hippo/store/generations.py:601
```

That is a correct invariant: a published generation's proof group is immutable, so a relation
supported by two **sequentially published** generations is not constructible at all.

The branch is still reachable, because `knowledge/access.py:445-447` groups
`AssertionSupport` by `(assertion_version_id, derivation_group)` across every authorized row
rather than per generation. The shape that reaches it is two generations on **different
sources staging concurrently**, both joining one proof group before either seals -- the
coordinator serialises builds per source, not across sources. The orchestrator confirmed this
reading and assigned the fixture as its own task.

**The fixture that is needed** (~60 lines, an interleaved variant of
`tests/unit/test_structural_loading.py:25 published()`): create sources A and B, create both
`Generation` rows in `staging` and claim a build job for each; run A's `enrich` (which writes
`shared_pair(relationship=True)`, opening the assertion, version and its first
`AssertionSupport`); run B's `enrich` writing its own support span plus an `AssertionSupport`
for **A's** version id with `derivation_group="declared"`; only then seal and publish both.
The assertions are then the ones drafted in this batch and removed with the test:
`relation.source_generations == tuple(sorted((a.pair, b.pair)))`, exactly one `BOUND_TO`
arrow, `edges_by_kind["BOUND_TO"] == 1` on **both** rows of `status.source_view`, and the
relation surviving `graph.scoped({either.source_id})`.

Until it exists, every `source_generations` assertion in the tree is a one-entry tuple, so
`status.py:124`'s `pair in row.source_generations` could be `row.source_generations[0] == pair`
and nothing would fail. That is the finding, unchanged.

## Deviations from the brief

1. **Finding 17 touched `managed_activation.py` beyond `STAGES`.** The brief's FILES section
   limits that module to finding 8; its REQUIRED BEHAVIOR section lists finding 17, whose
   string is at `:176`. Raised as a question, and the orchestrator granted the one string in
   addition to `STAGES`. The fix is **not** the review's literal "rebuilt" -> "deleted": that
   string is in `plan_dispatch`, the single classification both `reindex` and `delete_source`
   run, and `delete_source` reaches it (`pipeline.py:563`) *before* `_tombstone`'s own already
   correct "cannot be deleted" sentence at `:590`, which is therefore unreachable. A verb swap
   would only move the error onto the rebuild path. The sentence now names both operations:
   *"A managed source cannot be rebuilt or deleted without a build actor"*. Two tests that
   hardcoded the old string were updated (`test_managed_web_ingress.py`,
   `test_managed_pipeline_activation.py`); neither asserted on it.
2. **Findings 18 + C1 needed one clause more than `caller_error` at two of the nine sites.**
   `create_role_form` and `update_role_form` build their pydantic model *inside* the `try`, so
   an empty role name arrives as a `ValidationError` -- a `ValueError` subclass, but this
   form's own field rules and the only thing that tells the operator which box was wrong.
   `caller_error` alone turned `POST /roles` with an empty name into a 500. The guard at those
   two sites is
   `if isinstance(exc, ValueError) and not (caller_error(exc) or isinstance(exc, ValidationError))`.
   The `STR_EXC_SITES` allow-list did **not** grow: the same two entries are simply recorded
   as guarded instead of deferred. `test_the_role_form_still_shows_the_validators_sentence_but_not_a_subclasses`
   pins both kept families (the `ValidationError` and the bare `ValueError` from `int()`).
3. **`ccb6635`'s commit message overclaims once.** It says the guard "now runs ahead of every
   `str(exc)` under `src/hippo/web`". `analyze.py`'s two sites are still the deferred family
   (`ChangesetUnavailable` caught first, then `changesets.validate`'s own sentence) and were
   not in this brief. The `STR_EXC_SITES` comment was corrected to say so; the commit message
   cannot be, because the commit was already reported.
4. **Three commits rather than two**, for the reason in the commits table.
5. **PA5 ran verbatim with a bare `-W error`.** The brief says PA5 needs AnyIO form (b); it
   does not -- none of its five files imports a transport at module level, and the ledger's
   PA5 CHECK line carries no filter. Running it verbatim is green (184 passed, 2 skipped).
   PA6's line carries form (b) in the ledger itself and was run verbatim, filter included.
6. **PA3a finding 5 calls `on_first_connection` through `getattr`.** It is backend-only
   (`test_store_code.BACKEND_ONLY`), so the Fake has no such method; the test runs
   `getattr(store, "on_first_connection", store.ensure_schema)`. On Ladybug -- which is where
   PA7 runs this file -- the real bootstrap executes.

## Tests that were green on arrival, and why that is said out loud

The rulebook asks for a RED log. Four of these rows are coverage over code that is already
correct, so there is no RED to produce and manufacturing one would have meant breaking
something to watch it break.

| Test | RED? | Log |
|---|---|---|
| Findings 18 + C1, eight tests | **RED**, 8 failed | `/tmp/hippo-pa8close-red-18c1.log` |
| Finding 17 | **RED**, 1 failed | `/tmp/hippo-pa8close-red-f17.log` |
| Finding 9, two tests | green on arrival | `/tmp/hippo-pa8close-red-f9.log` |
| Finding 6 | green on arrival | `/tmp/hippo-pa8close-cov-f6.log` |
| Finding 13 | green on arrival | `/tmp/hippo-pa8close-cov-f13.log` |
| PA4d finding 2 | green on arrival | `/tmp/hippo-pa8close-cov-pa4df2.log` |
| PA2 f6 / PA3a f3 / PA3a f5 / PA3b f8 / T3 | green on arrival | `/tmp/hippo-pa8close-cov-pa2f6.log`, `-pa3af3.log`, `-pa3af5.log`, `-pa3bf8.log`, `-t3.log` |

**Finding 9 deserves the detail.** The revocation test passed *before* the `view.validate()`
was added, and the reason matters for anyone re-reading the finding: `query_session`
validates on every exit (`knowledge/query_access.py:157-162`, the `finally`), and an
`__exit__` that raises discards the response the branch had just built. So the `Busy` branch
already answered the revocation -- by accident of the context manager rather than by saying
so, and with the *session's* proof rather than the *view's*, which is `source_view`'s own
epoch. The finding is the asymmetry with its two siblings, not a leak. Both halves are now
pinned: the revocation answer and the plain `Busy` answer.

## Runs

### Baseline at `c893a95`, before any edit

| Gate | Result | Log |
|---|---|---|
| PA1 | 186 passed, 2 skipped — EXIT 0 | `/tmp/hippo-pa8close-base-pa1.log` |
| PA2 | 93 passed, 1 skipped — EXIT 0 | `/tmp/hippo-pa8close-base-pa2.log` |
| PA3 | 189 passed, 3 skipped — EXIT 0 | `/tmp/hippo-pa8close-base-pa3.log` |
| PA4 | 117 passed — EXIT 0 | `/tmp/hippo-pa8close-base-pa4.log` |
| PA5 | 184 passed, 2 skipped — EXIT 0 | `/tmp/hippo-pa8close-base-pa5.log` |
| PA6 | **6 failed, 708 passed — EXIT 1** | `/tmp/hippo-pa8close-base-pa6.log` |

### PA6 is RED at `c893a95` before this batch touches anything

Reported to the orchestrator at the time and confirmed as a CC1 regression owned by a
separate fix worker; **nothing in this batch touches those files.** Six failures, reproduced
in isolation on the two files alone (`/tmp/hippo-pa8close-regress-check.log`, 6 failed,
76 passed in 4.65s) in a clean worktree with zero edits:

- `test_graph_surface_access.py::test_unpublished_managed_native_rows_never_escape_graph_surfaces`
  `[/api/entities?q=orion]`, `[/api/graph/full]`, `[/graph]`
- `test_graph_surface_access.py::test_staged_generation_without_artifacts_is_not_a_source_dropdown_entry`
- `test_graph_surface_access.py::test_unpublished_managed_code_never_appears_in_symbol_lookup`
- `test_eval_access.py::test_generated_names_and_source_labels_come_from_visible_evidence`
  (a label reads `Sample questions: SECRET source container`)

Cause: `74ebaa5` "Serve a converting source's legacy graph until its first publication" (with
`d74e482`). `context.py`'s `_build_managed_graph`/`_build_structural_graph` now compute
`legacy_ids` as `store.source_serves_legacy(row)` instead of `row["id"] not in
managed_sources`, so a source holding **staged, unpublished** managed rows lands in
`legacy_ids` and the loader emits its unpublished native rows on the graph surfaces. That is
plan invariant 5 (staging evidence must not affect visibility or counts) and PA6's own
criterion. `context.py`, `status.py` and `store/generations.py` belong to the code-capture
fleet and to this brief's "do NOT touch" list.

### Green at commit 3, still on the `c893a95` base

Every line verbatim from `GATES.md`, Fake, at the tip of this branch before the merge below.

| Gate | Result | vs baseline | Log |
|---|---|---|---|
| PA1 | 188 passed, 2 skipped — EXIT 0 | +2 | `/tmp/hippo-pa8close-green-pa1.log` |
| PA2 | 94 passed, 1 skipped — EXIT 0 | +1 | `/tmp/hippo-pa8close-green-pa2.log` |
| PA3 | 191 passed, 3 skipped — EXIT 0 | +2 | `/tmp/hippo-pa8close-green-pa3.log` |
| PA4 | 117 passed — EXIT 0 | 0 | `/tmp/hippo-pa8close-green-pa4.log` |
| PA5 | 187 passed, 2 skipped — EXIT 0 | +3 | `/tmp/hippo-pa8close-green-pa5.log` |
| PA6 | 6 failed, 722 passed — EXIT 1 | +14 passed, **same 6 failures** | `/tmp/hippo-pa8close-green-pa6.log` |

PA6's failure set is identical to the baseline's, proved as a set rather than as a count:

```
diff <(grep '^FAILED' /tmp/hippo-pa8close-base-pa6.log | sort) \
     <(grep '^FAILED' /tmp/hippo-pa8close-green-pa6.log | sort)   # no output
```

### After merging the CC1 fix

`rag-it-all-tibs` moved to `013317f` while this batch was finishing, carrying the fix for the
regression above. The orchestrator instructed a merge into `wp/pa8close` so the final PA6
line is clean rather than six-red; that is the one merge this worker made, and it is recorded
here because the rulebook otherwise forbids one.

| Gate | Result | Log |
|---|---|---|
| PA6 after merge | *see the merge section at the end* | `/tmp/hippo-pa8close-merged-pa6.log` |

Ladybug, the two files the brief names (`HIPPO_TEST_STORE=ladybug`, verbatim, bare
`-W error`): `/tmp/hippo-pa8close-ladybug-1.log` (item 2 only) and
`/tmp/hippo-pa8close-ladybug-2.log` (final, after item 3 and the merge).

### Ruff

`.venv/bin/ruff check src/hippo tests/unit && .venv/bin/ruff format --check src/hippo tests/unit`
— `All checks passed!`, `269 files already formatted`. `ruff format --check` also run over
every Markdown file this batch wrote: `session-audit.md`, `evidence-pa4e.md`, the plan, and
this file.

## Files

Created: this file.

Modified: `src/hippo/knowledge/public_errors.py` (comment), `src/hippo/ingest/managed_activation.py`
(`STAGES` + the one refusal string), `src/hippo/web/auth.py`, `src/hippo/web/routes/{users,pages,sources,graph}.py`,
`ai_docs/gates/rag-it-all/task-5-production-activation/{session-audit.md,evidence-pa4e.md}`,
`ai_docs/plans/rag-it-all-task-5-production-activation.md`, and the tests
`tests/unit/test_{managed_web_surfaces,managed_web_ingress,managed_pipeline_activation,managed_source_inventory,ingest_pipeline,evals_runner}.py`.

Not touched: `src/hippo/store/*`, `tests/fakes/fake_store.py`, `src/hippo/context.py`,
`src/hippo/status.py`, `src/hippo/knowledge/*` other than the one `public_errors.py` comment,
`src/hippo/ingest/*` other than `managed_activation.py`, `GATES.md`, `docs/`, the checkpoint.

## New tests no PA CHECK line names

All of this batch's new tests live in files a PA line already runs, except one:
`test_the_pipelines_closed_validator_tuple_is_the_public_tables_own_family` is in
`tests/unit/test_ingest_pipeline.py`, which **is** in PA5. Nothing is orphaned. The CHECK
lines are the orchestrator's to maintain and none of them needed widening for this batch.
