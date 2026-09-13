# CC10 evidence: activation dispatch for code sources (gate CD8)

Worker `backend-developer-23`, 2026-09-13. Branch `wp/cc10`, worktree `.worktrees/cc10`, base
`bc7ea22` (CC1–CC9b and `wp/lbfix` merged). Contract: brief
`ai_docs/handoffs/briefs/cc10-activation-dispatch.md`; plan
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` sections 1, 7 (per ruling 9), 10 and the
CC10 row of section 12; rulings 8 and 9; design review m6 and M10; CC1 evidence finding 4; CC9b
evidence "Findings for CC10, CC11 and the reviewer". No gate checkbox is set here.

## Orchestrator rulings taken during this slice (2026-09-13)

| Question | Ruling |
| --- | --- |
| 1. Tests outside the brief's file list pin code, archive and repo sources as unsupported | Adapt exactly those assertions, each named below with its old and new expectation |
| 2. Route and CLI pass-through for `add_repo` | Mirror `add_file`'s: `new_managed_source` at `repo_form` and `/api/sources/repo`, `build_actor=actor` in `cli.cmd_index`'s git-URL branch; adapt `test_managed_web_ingress.py:240`, re-run the transport test and fix its docstring |
| 3. A credentialed URL in the Source row | (b): with an actor, `add_repo` runs `repository_descriptor` before any row exists, and `run_managed_build` re-checks before its clone. The legacy lane keeps storing the URL it was given; recorded below as a finding for Task 16 |
| FYI (i)–(iv) | Accepted: archive captured from the saved `.zip`; checkout layout and named cleanup; actorless bulk asserts `ManagedActorRequired`; heartbeat hook left for CC11 |
| Routed LOW rows | PA3a-6, PA3a-9 and W15 from `ai_docs/reports/2026-09-13-pa8-resign.md` belong to this slice's files; each is done and named below |

## Files

| File | Change |
| --- | --- |
| `src/hippo/ingest/managed_activation.py` | eligibility widened; `is_code_source`, `code_build_options`, `clone_depth`, `checkout_directory`, `discard_checkout`; `run_managed_build` dispatches by kind through `_run_code_build`/`_build_code`; code-lane `FAILURES` rows; code phases in `_PHASE_STAGES`; `ingress_file(..., stored_name=)` (PA3a-6); the two-definitions note (PA3a-9) |
| `src/hippo/ingest/pipeline.py` | `add_repo(..., build_actor=None, operation_id=None)`; `_submit_lane` contains every cause (W15); the module note on `build_actor` |
| `src/hippo/ingest/repos.py` | m6 redaction; `head_revision(checkout)` |
| `src/hippo/web/routes/sources.py` | `repo_form` and `/api/sources/repo` use `new_managed_source` (ruling 2) |
| `src/hippo/cli.py` | `cmd_index`'s git-URL branch passes `build_actor=actor` (ruling 2) |
| NEW `tests/unit/test_managed_code_activation.py` | 56 tests (the file CD8 names) |
| `tests/unit/test_ingest_repos.py` | one adapted assertion, seven new tests, three strengthened ones (below) |
| `tests/unit/test_managed_pipeline_activation.py` | adapted assertions only (ruling 1) |
| `tests/unit/test_managed_web_ingress.py` | adapted assertions only (rulings 1 and 2) |
| `tests/unit/test_managed_transport_activation.py` | docstring only (ruling 2) |
| NEW `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc10.md` | this file |

`readers.py` is unchanged: `is_code_name` and `is_plain_prose_name` were enough.
`code_generation.py`, `build_run.py`, `prose_generation.py`, `repo_capture.py`, `code_provenance.py`,
`prepared_code_chunks.py`, `knowledge/*`, `store/*`, `codegraph/*`, `context.py`, `status.py`,
`docs/`, the checkpoint and `GATES.md` are untouched.

## Eligibility

`managed_eligibility` stays closed and row-only; `plan_dispatch` is unchanged in shape.

| Saved row | Eligibility |
| --- | --- |
| `status/stage == deleted/tombstoned` (any kind, any flag) | `tombstoned` |
| `managed` flag set (any kind) | `managed` |
| `text` | `eligible_legacy` |
| `file` whose stored name `is_plain_prose_name` (`.md`, `.txt`, `.rst`, `.markdown`, `.text`) | `eligible_legacy` |
| `file` whose stored name `is_code_name` (every `readers.CODE_EXTENSIONS` suffix, e.g. `.py`, `.TSX`, `.sql`, `.yaml`) | `eligible_legacy` (new) |
| `archive` whose stored name ends in `.zip` (any case) | `eligible_legacy` (new) |
| `repo` (whatever its URL: the build refuses a credentialed one, not eligibility) | `eligible_legacy` (new) |
| `file` named `LICENSE`, `go.mod`, `paper.pdf`, `book.epub`, `page.html`, `orders.py.zip`, or no name | `unsupported` |
| `archive` not named `.zip`; `sample`; any other kind | `unsupported` |

An actorless caller therefore still gets `legacy` for every one of them, an actor gets `managed`
for the new rows, and a managed row without an actor still raises `ManagedActorRequired`
(`test_an_actorless_caller_stays_legacy_and_a_managed_code_source_needs_an_actor`).

## Dispatch sites

| Site | What it decides |
| --- | --- |
| `managed_activation.py:125` `managed_eligibility` | the closed table above |
| `managed_activation.py:157` `is_code_source` | `repo`, `archive`, or a `file` with a code name goes to the code coordinator |
| `managed_activation.py:650` `run_managed_build` | `is_code_source(source)` → `_run_code_build`; otherwise the plain-prose body, unchanged except the PA3a-6 name check at `:655` |
| `managed_activation.py:677` `_run_code_build` | archive/code file: `ingress_file` (`:693`) → `CodeTreeInput(root=<saved file>, kind=...)`; repo: `repository_descriptor` (`:699`) → `present` → `discard_checkout` → `repos.clone_repo` (`:704`) → `repos.head_revision` (`:709`) → finally `discard_checkout` (`:713`) |
| `managed_activation.py:716` `_build_code` | raw store and embedding cache, then `build_code_source` (`:734`) with `code_build_options`, job cancellation and `_present_progress` |
| `pipeline.py:160` `add_repo` | `check_actor` and `check_operation_id` before any row; with an actor `repository_descriptor(url)` (`:185`) before any row; `start_indexing(..., build_actor, operation_id)` (`:190`) |
| `pipeline.py:260` `start_indexing`, `:298` `run_indexing`, `:581` `delete_source`, `:640` `reindex_all`, `:711` `reindex` | unchanged: each runs `plan_dispatch`, which now classifies code kinds; the tests below prove each path by kind |
| `web/routes/sources.py:423` `repo_form`, `:512` `/api/sources/repo` | `new_managed_source` (ruling 2) |
| `cli.py:334` `cmd_index` git-URL branch | `build_actor=actor` (ruling 2) |

## The checkout layout

- A managed repository build clones into `data/sources/<source-id>/checkouts/<operation-id>/`
  (`checkout_directory`). It is never the legacy `data/sources/<source-id>/repo/`, which the legacy
  lane's `read_source` still `rmtree`s and re-clones for itself. `checkouts/` is a subfolder
  because `repo` is itself a valid `OPERATION_ID`.
- The clone depth is `clone_depth(options)`: `code_history_depth + 1`, or 1 with history off. That
  is `pipeline._clone_depth`'s rule; the test asserts they agree. `CodeBuildOptions` has no
  clone-depth field (CC9b deviation 2), so the depth is derived rather than hashed.
- `CodeTreeInput(root=<checkout>.resolve(), kind="repo", repository=repository_descriptor(url),
  head_revision=repos.head_revision(checkout))`. `head_revision` names the git directory
  explicitly (`--git-dir`), so a folder that is not a repository cannot borrow the HEAD of a
  working tree above it. A data directory can live inside one.
- **Cleanup, as the brief asked me to state:** a named function,
  `managed_activation.discard_checkout(ctx, source_id, operation_id)`. It removes exactly
  `checkouts/<operation-id>`, refuses a symlink, and treats a missing folder as nothing to do. It
  runs once before the clone (a crashed attempt of the same operation) and in a `finally` after
  the coordinator returns or raises. Every byte the generation needs was captured into the raw
  store by then. The spies record every `shutil.rmtree` path and forgive only paths
  `discard_checkout` named. An `rmtree` of the source directory, the raw root or anything else
  shows up in `destroyed()`.
- An archive is captured straight from its saved `.zip` (`CodeTreeInput(root=<zip>,
  kind="archive")`). CC4's `walk_tree` applies `readers.check_zip_budgets` itself and refuses nested
  archives. Nothing is extracted, so there is no extraction folder and nothing to clean up. This
  deviates from the brief's "extract into a per-operation directory" (FYI (i), accepted): a
  directory root would record `capture_kind="repo"`. The archive conversion test asserts the
  source folder still holds only `bundle.zip`.
- A code file is its one saved file (`ingress_file`).

## Options

`code_build_options(ctx)`: chunk size and overlap through the same refusals as `build_options`
(now one shared `_chunking`); `synonymy_threshold` through `_fraction`; `history_depth =
code_history_depth` (≥ 0); `git_timeout_seconds = code_git_timeout_s` and `history_total_seconds =
code_history_total_s` (≥ 1); `max_decoded_chars = max_text_chars`; `workers = openie_workers`;
`allow_empty=False`; every other field is `CodeBuildOptions()`'s reviewed default. The raw store's
per-object cap is `max(capture_limits.max_input_bytes, capture_limits.max_manifest_bytes)`, since
every raw object is a captured file or the manifest, both bounded before any write.

## Failure mapping

New closed rows, ahead of `InputCaptureError` because `CaptureRefused` subclasses it:

| Exception | Code | Stored message |
| --- | --- | --- |
| `CaptureRefused` (every reason, including a credentialed URL) | `invalid_source` | "The saved repository, archive or code file for this source cannot be built." |
| `CodeBuildRefused` (ceilings, an empty tree, an unreadable history, a kind mismatch) | `invalid_source` | the same |
| `RepoError` (clone failure, missing git, unreadable head) | `operation_failed` | "The repository could not be cloned. Check the local logs for this operation." |

`status._public_error` renders from the code alone, so a row reads `INVALID_SOURCE_TYPE.message` or
`OPERATION_FAILED.message`. CC9b finding 4 is discharged: `CodeBuildRefused` no longer falls
through to the unknown row. Size ceilings share `invalid_source` with type refusals, as the plain
lane's `CaptureTooLarge` already does. The code vocabulary in `knowledge/public_errors.py` is
frozen and `invalid_source` covers both.

## m6 redaction (`src/hippo/ingest/repos.py`)

- `_explain_git_failure` returns `"could not clone the repository: <reason>."`. The four closed
  reason clauses are the only variable text, and no URL appears. Its `log.warning` is `"git clone
  from host %s failed: %s"` with the bare host (`_host_of`: userinfo and port stripped) and the
  same closed reason. It no longer logs git's stderr or the URL.
- The clone timeout message names no URL and is raised `from None`. `TimeoutExpired` quotes the
  whole command line, and `log.exception` in the legacy job would print it as the chained cause.
- `"the clone destination already exists and is not empty"` and `"the checkout is not a folder"`
  name no absolute path.
- `walk_repo`'s warning is `"Skipping %s: %s"` with the path relative to the root and the
  exception's class name. A reader's own message quotes the absolute path it was reading.
- `is_git_url` and `pipeline.add_repo`'s "does not look like a git URL" hint are unchanged.

Proof that `https://robot:ghp_s3cr3tT0ken@git.example.com/...` never leaks:

- `test_a_credentialed_clone_failure_keeps_the_token_out_of_the_message_and_the_log`:
  `repos.py`'s message, its formatted traceback and every log record. The host is still logged.
- `test_a_clone_timeout_names_no_url_even_in_its_chained_cause`: the rendered traceback.
- `test_a_legacy_clone_failure_keeps_a_credential_out_of_the_logs_and_the_row_presentation`:
  through the real legacy job. Git's stderr echoes the credentialed URL; the token is absent from
  every `hippo` log record at DEBUG, including `log.exception`'s traceback, and from the row's
  `name`/`status`/`stage`/`error`. The row's `meta.url` still holds it (ruling 3, Task 16).
- `test_add_repo_checks_its_actor_operation_and_managed_url_before_a_source_row`: with an actor,
  `CaptureRefused` before any row, clone or source folder; the token is in no message or log.
- `test_a_managed_repository_refuses_a_credentialed_url_before_any_clone_or_raw_root`: a row that
  already holds such a URL refuses in `run_managed_build` before a clone, a checkout or a raw root.

### Adapted and added assertions in `tests/unit/test_ingest_repos.py`

| Test | Old | New |
| --- | --- | --- |
| `test_clone_explains_git_failures` | `".git-credentials" in caplog.text`, so the operator's log held git's stderr | `.git-credentials` and `repository not found` NOT in the log; `acme/missing` in neither message nor log; the closed reason and `github.com` in the log |
| `test_clone_refuses_a_non_empty_destination` | `match="not empty"` | the same, plus the absolute path is not in the message |
| `test_walk_repo_needs_a_folder` | raises `RepoError` | the same, plus the absolute path is not in the message |
| NEW | — | `test_a_clone_timeout_names_no_url_even_in_its_chained_cause`, `test_a_credentialed_clone_failure_keeps_the_token_out_of_the_message_and_the_log`, `test_head_revision_reads_the_checkouts_own_head_commit`, `test_head_revision_refuses_a_repository_with_no_commit`, `test_head_revision_never_reads_an_enclosing_repository`, `test_walk_repo_logs_a_skipped_file_by_its_path_inside_the_checkout` |

`test_clone_really_runs_git_and_reports_unreachable_hosts` still matches `"could not clone"` unchanged.

## Adapted assertions outside the brief's file list (ruling 1 and ruling 2)

| File and test | Old expectation | New expectation |
| --- | --- | --- |
| `test_managed_pipeline_activation.py::test_eligibility_reads_the_saved_source_kind_and_stored_filename` rows `module.py`, `settings.yaml` (`file`), `bundle.zip` (`archive`), `https://host/o/r` (`repo`) | `unsupported` | `eligible_legacy` |
| `test_managed_pipeline_activation.py::test_unsupported_upload_stays_legacy_even_with_an_actor` parameters | `paper.pdf`, `module.py`, `settings.yaml`, `bundle.zip` → legacy | `paper.pdf`, `LICENSE` → legacy |
| `test_managed_pipeline_activation.py::test_repo_and_sample_stay_legacy_even_with_an_actor` | renamed to `test_a_sample_stays_legacy_and_a_repo_converts_when_an_actor_is_offered_later`; `[("legacy", repo), ("legacy", sample)]` | `[("managed", repo), ("legacy", sample)]` |
| `test_managed_pipeline_activation.py::mixed` fixture, the unsupported lane | `module.py` | `LICENSE` (feeds `test_a_mixed_bulk_clears_only_legacy_lanes...`, `test_a_single_reindex_of_an_unsupported_source...` whose docstring now says LICENSE, `test_a_failed_managed_preflight...`, `test_a_bulk_without_an_actor...`, `test_a_mixed_bulk_refreshes...`, `test_one_lane_failing_asynchronously...`, `test_a_lane_that_changes_lane_after_the_plan...`; every one of their assertions is unchanged) |
| `test_managed_web_ingress.py::test_an_unsupported_upload_stays_legacy_for_a_signed_in_reader` parameters | `paper.pdf`, `module.py`, `bundle.zip` → legacy | `paper.pdf`, `LICENSE` → legacy; the now-unused `zip_bytes` helper and its `io`/`zipfile` imports removed |
| `test_managed_web_ingress.py::test_repo_and_sample_stay_legacy_for_a_signed_in_reader` | renamed to `test_a_repo_takes_the_managed_lane_and_a_sample_stays_legacy_for_a_signed_in_reader`; API repo → legacy | API repo and the `/sources/repo` form → managed, sample → legacy |
| `test_managed_transport_activation.py::test_a_gated_local_index_is_owned_by_its_creator_and_kept_to_their_tier` | docstring: "`add_repo` has no `build_actor`... the git-URL branch stays legacy" | docstring: the git-URL branch passes the same actor and dispatches the managed code lane; assertions unchanged and green |

## Destructive-operation spies (CD8's dispatch clause; CC1 finding 4; ruling 8)

`arm_spies` records, rather than allows:

- `store.delete_source`, `delete_passages_for_source`, `delete_code_nodes_for_source`,
  `remove_orphans` and `_collect_generation` (generation collection);
- `pipeline._prepare_reindex`, `_clear_passages`, and the whole legacy read path
  (`_read_chunk_index`, `_read_history`, `read_source`);
- every `shutil.rmtree` path, forgiving only those `discard_checkout` named;
- `os.unlink`/`os.remove` of an absolute path at or under the raw root. The raw store's own
  temporary-file cleanup unlinks a bare name relative to a directory descriptor, so it is not
  mistaken for one.

| Criterion | Test |
| --- | --- |
| an actorless `reindex`, `delete_source`, `reindex_all`, `start_indexing` and `run_indexing` of a converting `repo`/`archive`/code `file` refuse with `ManagedActorRequired`, reach no spy, and change no row and no file | `test_an_actorless_caller_never_reaches_cleanup_for_a_converting_code_source[repo,archive,file]` |
| the same three actorless refusals mid-staging of a REAL conversion (staging generation present, flag flipped, no pointer), the legacy graph unchanged in every sampled snapshot until publication, the legacy rows and the legacy checkout still on disk after it | `test_a_legacy_repository_converts_with_its_legacy_graph_serving_until_publication` |
| after publication: all five actorless paths refuse; with an actor a reindex refreshes through the code lane and a delete tombstones; no raw object removed | `test_add_repo_with_an_actor_publishes_one_code_generation_and_then_refuses_every_legacy_path` |
| an actor-bearing bulk whose actor cannot build a converting code source raises `ManagedPreflightRefused` before any legacy lane is cleared | `test_a_bulk_by_an_actor_who_cannot_build_a_converting_code_source_clears_nothing` |
| an actor's reindex of a converting source dispatches the code lane by kind and its delete tombstones, with no spy reached and every saved byte, legacy checkout and legacy row kept | `test_an_actor_refreshes_or_tombstones_a_converting_code_source_without_cleanup[repo,archive,file]` |
| the index job never reaches the legacy read path for a managed attempt | `_read_chunk_index`/`read_source`/`_read_history` are spies in every test above |
| per-kind dispatch through `run_managed_build`: the tree, options, raw store, cache; the clone's URL, folder and depth; the head SHA and descriptor; the checkout removed afterwards | `test_run_managed_build_hands_each_code_kind_a_tree_this_lane_owns[repo,archive,file]`, `test_a_plain_prose_source_still_goes_to_the_plain_coordinator` |
| the cleanup is one named function that removes only its own operation's clone | `test_the_checkout_cleanup_removes_only_one_operations_own_clone` |
| real builds through dispatch | repository bootstrap via `add_repo` with an actor; repository conversion via `reindex`; archive conversion via `reindex`; code-file bootstrap via `add_upload` |
| unsupported and actorless callers stay legacy | `test_ingress_sends_code_sources_to_the_managed_lane_only_with_an_actor` (repo, archive, code file with and without an actor, plus `LICENSE` with one) |
| closed failure mapping, no path, URL or stderr on the row | `test_a_managed_clone_failure_is_presented_by_its_closed_code_alone`, `test_a_capture_refusal_is_presented_as_an_invalid_source_without_a_path`, `test_the_code_lane_failures_map_to_closed_generation_aware_codes` |

The brief's item 3 said an actorless bulk refuses with `ManagedPreflightRefused`. The reviewed code
and `test_a_bulk_without_an_actor_refuses_before_clearing_a_managed_inventory` raise
`ManagedActorRequired` there, and the orchestrator confirmed that (FYI (iii)).
`ManagedPreflightRefused` is asserted where it applies: an actor who cannot build one lane.

## The routed LOW rows

| Row | What was done | Test |
| --- | --- | --- |
| PA3a-6 | `ingress_file(ctx, source_id, *, stored_name=None)`: when given, the single saved file must carry that name. `run_managed_build` and `_run_code_build` pass `safe_stored_name(stored_filename(source))` for `file` and `archive` sources, the families whose eligibility reads the name. `text` passes none. The signature stays backward compatible | `test_a_saved_file_not_named_as_its_row_says_is_refused_before_any_build[file-notes.md-paper.pdf, file-orders.py-orders.pyc, archive-bundle.zip-other.zip]` |
| PA3a-9 | `managed_eligibility`'s docstring names `source["managed"]` as the dispatch and cleanup authority, shared with `store.legacy_source_cleanup`, and `build_authority._source_control`'s `managed or active_generation_id` as the deliberately broader build guard, and says why they agree | documentation only |
| W15 | `pipeline._submit_lane` catches `Exception`, with one bounded log line that names the source and not the cause ("its lane could not be started after the plan"); the docstring names the wrap-up finding | `test_one_lane_that_cannot_start_never_strands_the_bulk_lanes_behind_it` (a `RuntimeError` carrying a path: the lane after it is still submitted, the count is 1, and the path is in no log) |

## Commits

| Hash | Subject |
| --- | --- |
| `a07e325` | Keep clone URLs and git's stderr out of repository errors and logs |
| `e954eb7` | Dispatch repositories, archives and code files to the code coordinator |
| (the commit adding this file) | Record the CC10 evidence for code activation dispatch |

## Results

All runs from `.worktrees/cc10` with `.venv/bin/python` (3.12.11, `mcp==2.1.1` pinned), shape
`HIPPO_TEST_STORE=<backend> .venv/bin/pytest <files> -q -o addopts='' -W error`, output captured to
a log and read from its summary line. "Form (b)" means the sanctioned
`-W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` was appended,
used only on runs whose file list includes `test_managed_web_ingress.py` or
`test_managed_transport_activation.py`; "plain" means no filter and no marker.

| Run | Files | Result | Log |
| --- | --- | --- | --- |
| Baseline before any edit, Fake, form (b) | `test_managed_pipeline_activation.py test_ingest_pipeline.py test_ingest_concurrency.py test_ingest_repos.py test_managed_route_activation.py test_code_generation.py` | 241 passed, 2 skipped | `/tmp/hippo-cc10-baseline.log` |
| RED, repos, Fake, plain | `test_ingest_repos.py` | 9 failed, 29 passed (the log held the URL and stderr; no `head_revision`) | `/tmp/hippo-cc10-red-repos.log` |
| GREEN, repos, Fake, plain | `test_ingest_repos.py test_ingest_pipeline.py` | 70 passed | `/tmp/hippo-cc10-green-repos.log` |
| RED, dispatch, Fake, form (b) | `test_managed_code_activation.py test_managed_pipeline_activation.py test_managed_web_ingress.py test_managed_transport_activation.py` | 46 failed, 255 passed, 2 skipped: missing `build_code_source`/`discard_checkout`/`checkout_directory`/`code_build_options`, `add_repo()` without `build_actor`, and the eligibility and lane diffs | `/tmp/hippo-cc10-red.log` |
| GREEN, new file, Fake, plain | `test_managed_code_activation.py` | **56 passed** (3.6 s) | `/tmp/hippo-cc10-green-new.log` |
| **CD8, the ledger's CHECK line verbatim, Fake, plain** | `test_code_generation.py test_managed_code_activation.py test_ingest_pipeline.py test_ingest_concurrency.py test_managed_pipeline_activation.py test_prose_generation.py` | **305 passed, 3 skipped** (47.6 s) | `/tmp/hippo-cc10-cd8.log` |
| Wide regression, Fake, form (b) | the baseline six plus `test_managed_code_activation.py test_managed_web_ingress.py test_managed_transport_activation.py test_managed_web_surfaces.py test_import_order.py test_layering.py test_cli.py test_mcp_server.py test_converting_source_serving.py` | **657 passed, 3 skipped** (79 s) | `/tmp/hippo-cc10-green-fake.log` |
| **Ladybug, the brief's line, plain** | `test_managed_code_activation.py test_managed_pipeline_activation.py -k "repo or archive or code"` | **59 passed, 105 deselected** (131 s) | `/tmp/hippo-cc10-ladybug.log` |
| Ruff | `check` and `format --check` over the ten changed Python files and this document | `All checks passed!`, `11 files already formatted` | — |

**The CD8 CHECK line needs no form (b).** It passed with plain `-W error`. CC9b's evidence said
the line needs the AnyIO filter because `test_managed_pipeline_activation.py` imports
`fastapi.testclient` at module level. At `bc7ea22` it does not: its imports are `httpx`, `pytest`,
`hippo.*` and `tests.unit.test_prose_generation`. The ledger's line is runnable as written.

**What the Ladybug `-k` selected.** It selects every test in `test_managed_code_activation.py`,
because the module name contains `code`: all 56, including the four real builds, the cleanup test,
the PA3a-6 and W15 tests and the eligibility table. From `test_managed_pipeline_activation.py` it
selects exactly three: `test_a_sample_stays_legacy_and_a_repo_converts_when_an_actor_is_offered_later`,
`test_a_refresh_that_meets_a_changed_profile_reads_back_as_the_rebuild_code` and
`test_a_failure_that_cannot_be_presented_still_reports_nothing_private` (the last two by substring).
The four real code builds, two legacy indexings and everything else in the selection took 131 s on
LadybugDB. CC9b measured ~45 s for one build of the same five-file tree with `batch_size=8`; these
builds use `code_build_options`' reviewed default `batch_size=128`, which is the likely reason
they are cheaper. That is not measured here, and no scale claim is made.

## Deviations from the brief

1. **No archive extraction directory** (FYI (i), accepted); see the checkout layout.
2. **Clone depth is derived, not an option field**: `CodeBuildOptions` has no such field and
   `code_generation.py` is not this slice's.
3. **Actorless bulk refusal is `ManagedActorRequired`** (FYI (iii), accepted).
4. **`build_run.py`'s heartbeat hook was not taken** (FYI (iv)): CC9b's finding stays open for CC11.

## Findings for CC11, the orchestrator and the reviewer

1. **PA2-4 becomes reachable with this slice.** The PA8 re-sign report records that
   `status.source_view` attributes `CODE_EDGE_KINDS` arrows by node membership, not by
   `row.source_generations`. It notes this was unreachable only because nothing dispatched the code
   coordinator. This slice dispatches it, so a published code generation's edges are now counted
   that way. `status.py` is frozen for this slice; the row needs an owner before managed code is
   served widely.
2. **The legacy lane still stores a credentialed clone URL in `meta.url`** (ruling 3), and a
   legacy reindex clones it. Recorded for Task 16.
3. **A crashed repository build leaves `checkouts/<operation-id>/` behind** until the same
   operation is retried. Nothing else removes it: a managed source is tombstoned, never physically
   deleted. The next build clones under a new operation, so correctness is unaffected, but the
   folder is disk the restart sweep could reclaim. The empty `checkouts/` parent is also left after
   a successful build.
4. **`invalid_source` covers the code coordinator's ceilings and unreadable history too.** The
   public vocabulary is frozen, and `status._public_error` renders from the code alone, so a
   too-large repository reads "The source is not an accepted input type". The plain lane's
   `CaptureTooLarge` already reads the same way.
5. **`hippo index <credentialed git URL>` in gated mode** now raises `CaptureRefused` from
   `add_repo` before a row exists. `cmd_index` does not catch it specially, so the CLI reports it
   like any other `ValueError`. The message names no URL.
6. **`CodeTreeInput`'s own `ValueError`s** (CC9b finding 4, first half) cannot be reached from
   dispatch. The adapter always builds an absolute root, gives no descriptor or head to an archive
   or file, and passes no `paths`. Were one reached, it would map to `operation_failed`.
7. **`repo_form` now prints a `CaptureRefused`.** Its existing `except (RepoError, ValueError)` →
   `f"/?error={exc}"` catches the new refusal from `add_repo` and echoes its message. That is safe
   today only because CC4 closed every `CaptureRefused` message (none names a URL or path), and
   `upload_form`/`text_form` already print any `ValueError` the same way. It is still a
   non-exact `ValueError` printed at a caller, which `render.caller_error` forbids on the JSON
   routes. `/api/sources/repo` is correct: `caller_error` is false, so `public_failure_handler`
   answers 400 `INVALID_SOURCE_TYPE`. Not changed here, because ruling 2 was "mirror exactly".
