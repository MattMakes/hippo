# r21c evidence — capture bounds, archive member kinds, the converting source page, URL echo and CI size (R21-M7..M11)

Brief: `ai_docs/handoffs/briefs/fix-r21-capture-web.md`. Review: `ai_docs/reports/2026-09-13-code-capture-review.md`
(MAJOR rows R21-M7 to R21-M11; minors m15, m16, m20, m21). Branch `wp/r21c` from `rag-it-all-tibs` at `e026640`,
worktree `.worktrees/r21c`, venv with `mcp==2.1.1`.

## Files

| File | Change |
| --- | --- |
| `src/hippo/ingest/repo_capture.py` | M8, M9, m15, m21: classify-then-budget-then-read archive walk, member type from `external_attr`, scp-like credential refusal, closed budget sentence; `_wanted_member` deleted |
| `src/hippo/ingest/repos.py` | M10: `NOT_A_GIT_URL`, used by `clone_repo` |
| `src/hippo/ingest/pipeline.py` | M10: `add_repo` raises `repos.NOT_A_GIT_URL`; m20: the history warning logs the exception's class |
| `src/hippo/web/routes/sources.py` | M7: `source_page` branches on the view's legacy lane; M10: `repo_form` percent-encodes its redirect; `add_repo` comment corrected |
| `.github/workflows/ci.yml` | M11: header comment stating the acceptance size CI runs; no step or env changed |
| `tests/unit/test_code_capture_acceptance.py` | M11: the default-size line (`"48"` to `"8"`) and the comment above it, nothing else |
| `tests/unit/test_repo_capture.py` | M8, M9, m15, m21 tests |
| `tests/unit/test_ingest_repos.py` | M10 test |
| `tests/unit/test_ingest_pipeline.py` | M10 and m20 tests |
| `tests/unit/test_managed_web_ingress.py` | M10 web test |
| `tests/unit/test_managed_web_surfaces.py` | M7 test; `STR_EXC_SITES` gains the `repo_form` redirect line |

Not touched: every file the brief lists under "do NOT touch", `readers.py`, `cli.py`.

## Runs

AnyIO: form (b), `-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`, on
every command line that includes `test_managed_web_surfaces.py` or `test_managed_web_ingress.py` (both import
`fastapi.testclient` at module level). No marker was added.

| Phase | Backend | Files | Result | Log |
| --- | --- | --- | --- | --- |
| Baseline at `e026640` | Fake | CD3 CHECK files + `test_ingest_repos.py test_managed_web_surfaces.py test_managed_web_ingress.py test_ingest_pipeline.py` | 388 passed | `/tmp/hippo-r21c-baseline-fake.log` |
| RED | Fake | `test_repo_capture.py` | 5 failed, 56 passed | `/tmp/hippo-r21c-red-capture.log` |
| RED | Fake | `test_ingest_repos.py test_ingest_pipeline.py test_managed_web_ingress.py test_managed_web_surfaces.py` | 9 failed, 235 passed | `/tmp/hippo-r21c-red-web.log` |
| RED | — | `FILES_PER_LANGUAGE` with the variable unset | `48` | `/tmp/hippo-r21c-red-acceptance-size.log` |
| GREEN | Fake | the baseline set | 404 passed (388 + 16 new) | `/tmp/hippo-r21c-green-fake-final.log` |
| GREEN | Fake | the CD3 CHECK line verbatim | 160 passed | `/tmp/hippo-r21c-green-cd3.log` |
| Regression | Fake | `test_browse_original_citations.py test_status_access.py test_web_analyze.py test_web_auth.py test_web_busy_pages.py test_web_code_pages_2.py test_web_code_pages.py test_web_library_evals.py test_converting_source_serving.py test_managed_source_inventory.py` (every suite that renders `/sources/{id}`, plus the lane suites) | 143 passed, 2 skipped | `/tmp/hippo-r21c-green-fake-pages.log` |
| GREEN | — | `FILES_PER_LANGUAGE` unset / set to 48 | `8` / `48`; `BUFFER_POOL_BYTES` 4294967296 | `/tmp/hippo-r21c-green-acceptance-size.log` |
| GREEN | Fake | `test_code_capture_acceptance.py`, variable unset | 2 passed in 12.96s | `/tmp/hippo-r21c-fake-acceptance-default.log` |
| GREEN | LadybugDB | `test_repo_capture.py` | 61 passed | `/tmp/hippo-r21c-ladybug-capture.log` |
| GREEN | LadybugDB | `test_managed_web_surfaces.py -k converting` | 1 passed, 95 deselected | `/tmp/hippo-r21c-ladybug-web-converting.log` |

The LadybugDB runs were serial, one at a time. Neo4j was not run (root-owned). No new store shape or query: the
page uses `get_passages`, which every backend already has (`store/memory.py:264` on Neo4j, `store/ladybug.py:947`,
the Fake store), and the capture and URL changes touch no store.

Ruff: `ruff check` and `ruff format --check` clean on the ten Python files above and on this file. Ruff has no YAML
formatter; `ci.yml` was parsed with `yaml.safe_load`, and its `unit` and `neo4j` test steps are unchanged.

## R21-M7: the converting source page

- Before: `source_page` branched on `source.get("managed")`. The first staged row sets that flag, so a converting
  source, which is in the legacy lane until it publishes (ruling 14), rendered its legacy passages from the graph
  with `triples: []`, `entities: []` and no extraction error. RED: `'1 facts' in page.text` failed.
- Fix: the branch is `source_id in view.legacy_ids`. For a lane member the page is cut from `view.graph.passages`
  for the source, sorted by `(ordinal, id)`, and hydrated with `ctx.store.get_passages(ids, access=principal.access)`,
  which returns entities, triples and the extraction error. `passage_evidence` is computed only outside the lane.
  The managed branch is unchanged. No store method was added; `status.py` and `context.py` are untouched.
- Why not `passages_for_source`: that read matches every `(p)-[:FROM]->(s)` with no generation filter, so a converting
  source's page would show the staged generation's passage. The test asserts the staged text and the staged passage
  id are absent, which separates this fix from that one. Checked, not only read: with the legacy branch temporarily
  swapped to `passages_for_source`, the test fails on that assertion on Fake and on LadybugDB (the staged passage's
  text is on the page); the file was then restored with `git checkout`
  (`/tmp/hippo-r21c-mutant-m7-fake.log`, `/tmp/hippo-r21c-mutant-m7-ladybug.log`).
- Also changed: a plain legacy source (no generation) now takes the same lane read instead of
  `passages_for_source`'s `SKIP`/`LIMIT`. It gets the same rows, which the held graph serves for the caller, with the
  same fields in `(ordinal, id)` order; the page count still comes from the Source row as before. Every suite that
  renders `/sources/{id}` passes on Fake (regression row above).
- Test: `test_managed_web_surfaces.py::test_a_converting_sources_page_keeps_its_legacy_facts_and_shows_no_staged_row`
  (Fake, LadybugDB).

## R21-M8 and R21-m21: the archive budget

- Before: the budget set came from `_wanted_member`, which needs a supported name, while `_member_reason` admits
  extensionless names for the content sniff; those members were read whole into memory outside `check_zip_budgets`.
  The refusal message was `str(TooLarge)`, which names the archive. RED: `ZipFile.read` ran before the budget on both
  rails, and the refusal quoted `client-private-bundle.zip`.
- Fix: `_walk_archive` classifies every member first (normalize, duplicate check, `_member_reason`), then runs
  `readers.check_zip_budgets` over exactly the members it will read, then reads them. `_wanted_member`, its only
  caller gone, is deleted. `readers.py` is unchanged. The refusal is `"The archive holds more readable files or unpacked
  bytes than its budget allows"`, with reason `archive_budget`.
- Two consequences, both from counting only what is read:
  1. A member the caller's exclusion policy removes (`configured_exclusion`) is no longer counted, because it is never
     read. An archive that was over budget only through such members used to refuse and now captures.
  2. Inside one archive, `duplicate_path`, `escaping_path`, `unportable_path` and `nested_archive` now come before
     `archive_budget`, which used to be checked first. Every one is still a refusal before any read, and no test
     pins the combined order.
- Tests: `test_extensionless_archive_members_count_against_the_archive_budget_before_any_read[MAX_ZIP_MEMBERS]`,
  `[MAX_ZIP_TOTAL_BYTES]` (budget lowered, `ZipFile.read` made to fail), and
  `test_the_archive_budget_refusal_is_a_closed_sentence_naming_no_archive`.

## R21-M9: archive member kinds

- Before: members were never classified by `external_attr`, so a symlink member was captured as a text file holding its
  target path. RED: the accepted paths included the link, the FIFO and the character device.
- Fix: `_member_reason` reads `stat.S_IFMT(member.external_attr >> 16)`. `S_IFLNK` is `symlink`, and any type other
  than none or `S_IFREG` is `not_regular`. A member with no type bits stays a plain file, because `ZipFile.writestr`
  from a bare name records `0o600` and a zip written on Windows records nothing. The `nested_archive` refusal stays
  first, so no refusal became a skip; after it the order is `_directory_entry_reason`'s: type, then policy and
  ignore rules, then size, then name.
- Coverage: `EXCLUSION_REASONS` already held both names, and `code_generation._coverage` counts `captured.exclusions`
  by reason generically, so `files_excluded` records `symlink` and `not_regular` for an archive with no change there.
- Test: `test_archive_symlink_and_non_regular_members_carry_their_own_reasons`, which checks that an untyped member and an
  `S_IFREG` member are both accepted.

## R21-M10: a refused URL is never quoted back

- Before: `pipeline.add_repo` and `repos.clone_repo` raised `f"'{url}' does not look like a git URL. ..."`, and
  `repo_form` redirected to `f"/?error={exc}"` unquoted (Starlette keeps `:` and `@` in a `Location`). RED showed the
  whole credentialed URL in the `RepoError`, the 400 body and the `Location`.
- Fix: `repos.NOT_A_GIT_URL` is `"The address does not look like a git URL. Use https://host/owner/repo,
  ssh://git@host/owner/repo or git@host:owner/repo."`, and both raise sites use it. `repo_form` redirects to
  `f"/?error={quote(str(exc))}"`. The phrase "does not look like a git URL" is kept, so the three substring pins still
  hold unchanged: `test_ingest_repos.py:80`, `test_managed_web_ingress.py:394`, and `test_managed_code_activation.py:632`
  (not owned).
- Access log: `TestClient` never runs uvicorn, so no test can capture its access log. That log prints the request line of
  the browser's follow-up `GET` to the redirect `Location`. The web test pins that `Location` to `/?error=` plus the
  quoted closed sentence and asserts no token, user or repository path in it, in either response's headers or body, or
  in `caplog` at DEBUG. `cli.py` is unchanged; it does not need a change.
- `STR_EXC_SITES` gains the redirect line. Its catch is unguarded, as before: any `ValueError` subclass
  `pipeline.add_repo` raises still reaches the redirect, now percent-encoded. Today those are the closed git-URL
  sentence and `CaptureRefused`'s closed sentences.
- Observation, left: `upload_form`'s `RedirectResponse(f"/?error={exc}")` in `sources.py` has the same unquoted,
  unguarded shape. No URL flows there and it is outside M10. The `str(exc)` scanner does not see `{exc}` f-string sites.
- Tests, each over `https://robot:<token>@gitserver/owner/private.git` (host without a dot) and
  `git+https://robot:<token>@git.example.com/owner/private.git`:
  - `test_ingest_repos.py::test_a_refused_url_is_answered_with_a_closed_sentence_that_quotes_none_of_it`
  - `test_ingest_pipeline.py::test_add_repo_refuses_an_unrecognised_url_without_quoting_it`
  - `test_managed_web_ingress.py::test_a_refused_repo_url_reaches_no_body_redirect_or_log`

## R21-M11: the acceptance size CI runs

- Before: `FILES_PER_LANGUAGE` defaulted to 48, so every CI job ran the multi-hundred-file scenario, a size that has not
  completed anywhere.
- Fix: the default is `"8"`. The ledger size runs only with `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=48`; that opt-in
  and the `if FILES_PER_LANGUAGE == 48` assertion are kept. `HIPPO_CODE_ACCEPTANCE_BUFFER_POOL_BYTES` still defaults to
  4 GiB. `ci.yml` gains a comment only.
- What CI runs after the change (no job sets the variable, so every job uses the default):
  - `unit` job, Python 3.11 and 3.12 × store `ladybug` and `fake`, `pytest tests/unit -q`: the acceptance module runs at
    8 files per language (50 accepted files). On `ladybug`, `make_world` reopens the store with the 4 GiB pool; on
    `fake` it runs on the Fake store.
  - `neo4j` job, `HIPPO_TEST_STORE=neo4j`, `pytest tests/unit -q`: the same module at 8 files per language against the
    service container (the module has no skip).
- Not measured: runner wall time for the LadybugDB scenario at 8 (the whole ten-file CD9 CHECK line took 1:02:57 on the
  dev machine), and whether a hosted runner's memory holds the 4 GiB pool.

## Minors

| Minor | Outcome |
| --- | --- |
| R21-m15 | Closed. `_split_clone_url` refuses an scp-like match whose path holds `@` (`user:secret@host:path` used to read `user` as the host). `test_an_embedded_credential_refuses_and_never_reaches_the_message` is parametrized over five spellings: https and http `user:pass`, https token-as-user, ssh `user:pass`, scp-like `user:pass`. Only the scp-like one was RED. |
| R21-m20 | Closed. The `pipeline.py` history warning logs `type(err).__name__`. `test_a_broken_history_read_logs_its_class_and_not_the_checkout_or_gits_words` raises a `HistoryError` quoting the checkout path, git's words and a token; none reaches `caplog`. |
| R21-m21 | Closed with M8. |
| R21-m16 | Left. Walk-time size and binary decisions (`_directory_entry_reason`) can go stale before `capture_raw_inputs` copies the file, and `tree.paths` walks twice (`code_generation.py:314`, r21w's). Not a one-liner. |
| R21-m18, R21-m36, R21-m49 | Left, as briefed. |
