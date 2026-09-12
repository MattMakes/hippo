# Evidence: the final Task 4 cleanup batch

Branch `wp/cleanup4`, base `rag-it-all-tibs` `4a8bbb2`, worktree `.worktrees/cleanup4`.
Brief: `ai_docs/handoffs/briefs/final-cleanup-task4.md`. Closes the small items every
Task 4 review left open, so the activation ledger's PA8 ("independent SPEC and QUALITY
reviews have no unresolved findings") can be claimed on the items in scope. Nothing here
changes a contract and nothing activates a production route.

Findings closed from `ai_docs/reports/2026-09-12-pa4-wrapup-review.md`: **1** (with a
correction to its premise, below), **2**, **3**, **10**, **12**, **14** and **19** — seven —
plus the 4c re-review's **N1–N4** and 4e decision **1**'s own check.
Findings deliberately **not** taken, by the orchestrator's ruling: **18**
(`users.py`/`auth.py`), which the review itself deferred to whoever next owns those files.

## Commands and results

All from `.worktrees/cleanup4` with `.venv/bin/pytest` 9.1.1, mcp pinned to 2.1.1, each
captured to a log and read from its summary line. Every command over a module-level
`fastapi.testclient` importer carries the sanctioned filter as **form (b)**:
`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`.
Form (a) was not needed anywhere in this batch.

| # | Command | Result | Log |
|---|---|---|---|
| 1 | Baseline, before any change: the sixteen affected files, form (b) | **560 passed**, EXIT 0 | `/tmp/hippo-cleanup4-baseline.log` |
| 2 | First run after implementing: five non-web files, bare `-W error` | **178 passed**, EXIT 0 | `/tmp/hippo-cleanup4-run1.log` |
| 3 | First run of the web/transport set, form (b) | **2 failed**, 297 passed | `/tmp/hippo-cleanup4-run2.log` |
| 4 | The same set after the two corrections below, form (b) | **299 passed**, EXIT 0 | `/tmp/hippo-cleanup4-run3.log` |
| 5 | GREEN (Fake), all twenty-one affected and adjacent files, form (b) | **677 passed**, EXIT 0 | `/tmp/hippo-cleanup4-green-fake.log` |
| 6 | GREEN (Ladybug), `test_managed_web_surfaces.py test_managed_web_ingress.py`, form (b) | see "Ladybug" below | `/tmp/hippo-cleanup4-green-ladybug.log` |

Run 3's two failures are worth recording because both were the new tests telling the truth
rather than defects:

- `test_an_empty_authorized_corpus_answers_without_one_model_call[simulate]` read
  `["legacy", "legacy"]` where the old per-module patch point saw one. `legacy` is not one
  of the routed modes `retrieval_session` passes through, so `run_simulation`'s re-entry
  cannot be handed the session back — it re-activates over the route's *same* owner. The
  single patch point sees both calls, which is exactly what the comment above
  `EMPTY_SURFACES` always claimed; the expectation now says so, and `record.once()` beside
  it is what proves the re-entry borrowed rather than acquired.
- `test_every_str_exc_in_the_web_layer_is_one_the_review_classified` caught the `str(exc)`
  inside the new `pages.py` **comment**. The scan now skips `#` lines, and says why.

Ruff: `.venv/bin/ruff check src/hippo tests/unit` → **All checks passed**;
`.venv/bin/ruff format --check src/hippo tests/unit` → **260 files already formatted**.
The three edited evidence documents and this one carry no fenced Python, so the CI Ruff
job over Markdown blocks has nothing to read in them; `ruff format --check` was run over
`ai_docs/` all the same.

## Correction to wrap-up finding 1's premise

The review read `src/hippo/web/routes/sources.py:507` as a **live** leak: an
`except RepoError` answering `coded_response(str(exc), INVALID_SOURCE, 400)`, where a
`RepoError` "carries an absolute server path and git's raw stderr". The class does carry
those. That route cannot.

`pipeline.add_repo` (`pipeline.py:158-173`) raises `RepoError` for exactly one condition —
`is_git_url(url)` is false — and its message is the caller's own URL plus a fixed hint
("Use https://host/owner/repo, ssh://git@host/owner/repo or git@host:owner/repo."). The
two unbounded messages the finding names are raised inside `repos.clone_repo`
(`repos.py:77` for the destination path, `repos.py:88` for git's stderr), and cloning
happens in the **background job**: those reach the Source row through
`pipeline._legacy_failure`, which 4e decision 4 already bounds. Two tests in the tree
pinned the hint at the 400 and one calls it a legacy validator the plan protects
(`test_managed_web_ingress.py::test_legacy_validation_routes_keep_their_own_messages`,
and the comment at the fourth body of
`test_every_json_failure_body_the_source_routes_answer_carries_its_code`).

Reported to the orchestrator as a conflict with the review's classification, per the
brief's REPORT line. Ruling: take the review's *own* preferred fix plus a guard, rather
than the brief's "class name plus a fixed sentence", which would have deleted an
actionable hint to close a leak that is latent at that route.

What landed:

- `repos._explain_git_failure` returns `f"could not clone {url}: {reason}."` and drops
  `git said: {last_line}`. The four `reason` clauses are this module's own words and the
  actionable half; the full stderr goes to `log.warning`. This closes the real leak, which
  lives on the Source row and in the legacy lane, at its source.
- `sources.add_repo` keeps the git-URL hint and gains `if type(exc) is not RepoError:
  return public_failure_response(retrieval_failure(exc))` — the same exact-type rule
  `render.caller_error` applies one clause down, so a future subclass carrying something
  the route has not read is mapped rather than quoted.

Tests: `test_ingest_repos.py::test_clone_explains_git_failures` (rewritten — the reason
survives, `git said`, the raw line and a `.git-credentials` path do not, and the full
stderr reaches the log) and
`test_managed_web_ingress.py::test_only_the_exact_repo_error_is_printed_at_the_repo_route`.

## Item by item

| Item | Change | Test that proves it |
|---|---|---|
| 1 — `sources.py:508` (finding 1) | `_explain_git_failure` bounded to its reason clause, full stderr to `log.warning`; exact-`RepoError` guard at the route | `test_clone_explains_git_failures`; `test_only_the_exact_repo_error_is_printed_at_the_repo_route` |
| 1 — `evals.py:373` (finding 2) | `except EvalAccessDenied` → 404 "no such question set" by exact type; `except ValueError` guarded by `caller_error`, else the mapper. The substring test is gone | `test_starting_a_run_on_an_unknown_set_is_a_404_that_reads_no_exception`; `test_starting_a_run_that_cannot_be_routed_is_mapped_not_blamed_on_the_request`; `test_starting_a_run_with_a_bad_setting_keeps_the_validators_own_sentence` |
| 1 — `graph.py:386` (finding 10) | the last isinstance 4xx catch in the web layer gains the `caller_error` guard | `test_light_up_maps_a_settings_check_that_is_not_the_validators_own_refusal`; `test_light_up_still_names_the_knob_the_caller_sent` |
| 1 — `pages.py:213` | comment naming the plan sentence that protects it, and stating honestly what is *not* protected (see "Residual" below) | covered by the allow-list |
| 1 — decision 1's grep | `STR_EXC_SITES` allow-list + scan | `test_every_str_exc_in_the_web_layer_is_one_the_review_classified` |
| 1b — `question_maker.py:183,267` (finding 3) | both per-passage skips log id + closed code + exception class; never `str(OllamaError)` | `test_a_skipped_passage_logs_its_id_and_code_but_never_the_models_reply` |
| 2 — `pipeline.py:392` (finding 14) | `raise ReadError(...)` for "no readable text", so the closed-validator rule keeps the sentence | `test_a_source_with_no_text_fails_with_a_message` (assertion restored to `ReadError: no readable text was found in this source`) |
| 3 — `analyze.py`, `graph.py` (finding 19) | both late-bind through `dense_session`; `test_managed_web_surfaces.watch` collapsed onto the single patch point with the pass-through filter | `test_every_dispatching_surface_reaches_the_rule_through_the_module`; every `watch`-using test in the file |
| 4 — `authorization_changed` ×3 (finding 12) | no consolidation (the reason stands); both halves pinned | `test_the_three_copies_of_the_denial_code_are_the_same_string`; `test_hippo_help_imports_no_serving_machinery` |
| 5 — N1 | `public_errors.py` comment names the two rows instead of positioning them; the test mirror says eleven of twelve and names the twelfth | `test_every_managed_failure_code_has_one_public_answer` (unchanged, prose corrected) |
| 5 — N2 | none (the code was already right); the remote print site had no test | `test_remote_index_applies_the_same_stored_error_rule_as_the_local_one` |
| 5 — N3 | none; the git-URL branch of `cmd_index`'s identity rule had no test | `test_a_gated_local_index_is_owned_by_its_creator_and_kept_to_their_tier[git_url]` |
| 5 — N4 | none; nothing pinned the help footprint | `test_hippo_help_imports_no_serving_machinery` (five absences, not a count) |
| 6 — docs | `evidence-pa4cfix.md` "never swallowed" reworded; `evidence-pa4b1.md` line numbers; `evidence-pa4c.md` deviation 5 | n/a |
| 7 — `test_managed_eval_activation.py` | none needed; confirmed | both cases pass and assert what the brief asks (below) |

### Item 7, confirmed rather than changed

`test_question_generation_reads_originals_without_a_dense_dispatch` asserts
`shared_entity_pairs(session.graph, mine)` is non-empty ("the corpus must bear facts, or
the multi-hop generator never runs") and that some prompt carries **two** passages' own
originals, which is the multi-hop path actually running.
`test_code_and_commit_question_generation_dispatches_nothing_either` asserts
`{"code", "commit"} <= kinds`. Both pass at this tree
(`/tmp/hippo-cleanup4-item7.log`, 2 passed, EXIT 0). No change made.

### Item 6, with a correction

The brief asked for `evidence-pa4b1.md:~388`'s line numbers to become
`graph_index.py:297,300`. They are stale: the file actually said `:209,212`, the
orchestrator's notes said `:297,300`, and the wrap-up review (item 33) says the real sites
are `:316,319`. Verified directly — `rg -n ProjectionError src/hippo/hipporag/graph_index.py`
gives the two raises at **316 and 319**. Written as `:316,319`, with a note that 4e
decision 8 also closed that open finding by making both raises `ProjectionError`.

## The `str(exc)` allow-list

Twenty-five sites under `src/hippo/web` at this tree, each with the wrap-up review's
disposition. The test keys on file and source line rather than line number, so an edit
above a site does not break it, and both directions are asserted: an unlisted site fails,
and a listed site that no longer exists fails too.

| Sites | Disposition |
|---|---|
| `routes/sources.py` ×4 `coded_response(str(exc), INVALID_SOURCE, 400)` | **guarded** — three behind `render.caller_error`, the fourth behind `add_repo`'s exact-`RepoError` test |
| `routes/api.py` ×1, `routes/code.py` ×1 `HTTPException(400, …)` | **guarded** — `caller_error` (4e decision 2) |
| `routes/evals.py` ×1, `routes/graph.py` ×1 `HTTPException(400, …)` | **guarded by this batch** — the last two isinstance 4xx catches in the layer |
| `routes/sources.py` ×3 `coded_response(str(exc), INDEXING_BUSY, 409)` | **bounded** — `Busy` is raised once with fixed text; the plan's transport table keeps the indexing preconditions' sentence |
| `routes/code.py` ×2 (`candidates` body, `HTTPException(404, …)`) | **intended** — exact `AmbiguousSymbol` / `UnknownSymbol`; the name is the caller's own input and the candidates are the answer |
| `routes/pages.py` ×1 `error=str(exc)` | **protected** — the legacy settings form, which the plan names |
| `routes/users.py` ×5, `routes/users.py` ×2 (`getattr(exc, "detail", …)`), `auth.py` ×1 | **deferred** — wrap-up finding 18, "when `users.py` is next owned". Bounded today; a hardening, not a live leak |
| `routes/analyze.py` ×2 | **deferred** with the same family — both raise `ChangesetUnavailable` (caught first) or `changesets.validate`'s own sentence |
| `render.py` ×1 | **prose** — the docstring stating the rule the sites above follow |

## Residual observations (new, not in the wrap-up review)

1. **`pages.py:213` is protected in the plan's sense but unguarded in the code's.** What
   the transport table protects is `validate_settings`' sentence. The handler wraps
   `ctx.store.update_settings(...)` in a bare `except ValueError`, so a `ValueError`
   *subclass* raised by the write would be rendered into the settings page too — the exact
   shape `test_a_settings_write_that_fails_is_mapped_rather_than_quoted_back_as_a_400`
   guards on the JSON twin of this route. One `caller_error` line would close it and keep
   the sentence. Recorded at the site and here; it belongs with finding 18's batch, not
   with this one, since the brief asked only for a comment.
2. **`test_ingest_repos.py` had to change with `repos.py`.** It is not in the brief's FILES
   list; `test_clone_explains_git_failures` asserted git's raw last line survived into the
   `RepoError`, which is the behaviour the orchestrator's ruling removes. Rewritten rather
   than deleted: it now asserts the reason survives, the raw line does not, and the log
   keeps everything.
3. **`test_ingest_pipeline.py:167`** was edited under an explicit grant (one assertion),
   and **`src/hippo/evals/question_maker.py`** plus
   **`tests/unit/test_evals_question_maker.py`** under another. Both were absent from the
   brief's FILES list while its ITEMS required them; confirmed before any edit.

## What this batch does not close

- Wrap-up finding 18 (six unguarded `ValueError` catches on the user/role/account paths,
  plus the two `getattr` sites), deferred by the review and by the orchestrator's ruling.
- **Finding 7** — `public_errors.py:146` still points `build_interrupted` at
  "(`store/memory.py`, `INTERRUPTED_REFRESH_ERROR`)" and the constant moved to
  `store/generations.py:29`. It is one word, but `knowledge/*` is mine for the N1 comment
  only, and that is a different comment thirty lines up. **Open, one word, unowned.**
- **Finding 16** — `evidence-pa4e.md:438` residual 6 still says `evidence-pa4cfix.md`
  "does not exist anywhere in the tree". It does. Item 6 of the brief asked me to reword a
  sentence *inside* `evidence-pa4cfix.md`, which is a different document; `evidence-pa4e.md`
  is not in my FILES. **Open, documentation only, unowned.**
- Findings 4, 5, 6, 8, 9, 11, 13, 15, 17 and 20, none of which is in this brief.
- The `pages.py` residual above, which is finding 18's shape on a page route.

PA8's "no unresolved findings" clause is therefore **closer but not yet true**. This batch
closes seven of the twenty (1, 2, 3, 10, 12, 14, 19) plus N1–N4 and decision 1's check.
Findings 7 and 16 are each a one-line documentation fix in a file this brief did not own,
and are the cheapest two left.
