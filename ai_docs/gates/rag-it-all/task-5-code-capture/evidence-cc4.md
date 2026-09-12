# CC4 evidence: repository capture and code provenance (gate CD3)

Worker `backend-developer-14`, 2026-09-12. Branch `wp/cc4`, worktree `.worktrees/cc4`, base
`e456e05`. Contract: `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` sections 3, 5, 6
and 10; brief `ai_docs/handoffs/briefs/cc4-repo-capture.md`. No gate checkbox is set here.

## Files

Created, and nothing else was touched:

- `src/hippo/ingest/repo_capture.py`
- `src/hippo/ingest/code_provenance.py`
- `tests/unit/test_repo_capture.py`
- `tests/unit/test_code_provenance.py`
- this file

## Public signatures

```python
def walk_tree(
    root: Path | str,
    *,
    exclusions: Iterable[str] = (),
    max_files: int = CODE_MAX_FILES,
    max_file_bytes: int = readers.MAX_FILE_BYTES,
) -> CaptureInventory: ...


def capture_repository_inputs(
    root: Path | str,
    *,
    raw_store: RawArtifactStore,
    source_id: str,
    workspace_id: str,
    limits: CaptureLimits,
    configuration: dict,
    observed_at: datetime,
    exclusions: Iterable[str] = (),
    provider_revision: str | None = None,
    max_files: int = CODE_MAX_FILES,
    max_file_bytes: int = readers.MAX_FILE_BYTES,
    should_stop: Callable[[], bool] | None = None,
) -> RepositoryCapture: ...


def read_code_provenance(
    raw_input: RawInput,
    data: bytes,
    *,
    name: str | None = None,
    path: str | None = None,
    budget: TextBudget | None = None,
) -> CodeProvenance: ...
```

Two documented deviations from the brief's abbreviated spellings, both forced by contracts the
brief itself sets:

- `capture_repository_inputs` keeps `root` first and everything else keyword-only, as the brief
  spells it, and adds the five arguments `capture_raw_inputs` requires (`raw_store`, `source_id`,
  `workspace_id`, `configuration`, `should_stop`) plus the two rails as injectable keywords so a
  test does not have to build a 5,000-file tree.
- `read_code_provenance` takes `data` because the brief requires a pure module with no store
  handle. The bytes therefore arrive as an argument, exactly as `read_plain_provenance` takes them.

`walk_tree` is public because plan section 6 step 2 names it.

## Closed reason sets

`repo_capture.EXCLUSION_REASONS` — one entry declined, the rest of the tree still capturable:

```
binary, configured_exclusion, ignored_path, not_regular,
submodule, symlink, too_large, unsupported_language
```

`repo_capture.REFUSAL_REASONS` — no inventory produced at all (`CaptureRefused.reason`):

```
archive_budget, damaged_archive, duplicate_path, escaping_path, input_bytes,
nested_archive, reserved_configuration, too_many_files, total_bytes,
unportable_path, unreadable, unsupported_root
```

`escaping_path` and `unportable_path` are deliberately separate. A name that climbs out of the
root is a security matter; a name that merely has no portable relative spelling (a backslash, a
control character) escapes nothing, and telling a reader otherwise would be false. Both refuse,
because the eight exclusion reasons are closed and neither case has one.

Orchestrator rulings of 2026-09-12 that this shape implements: `ExcludedInput.reason` in
`knowledge/inputs.py` stays pinned to `configured_exclusion`, so the canonical manifest records
every exclusion under that one name while the fine reason lives on `RepositoryCapture.exclusions`
for `coverage_json` (plan section 9); `symlink`, `not_regular` and `submodule` are exclusions, not
refusals; `configured_exclusion` is an eighth reason distinct from `ignored_path`;
`read_code_provenance` refuses `is_plain_prose_name` and accepts extensionless known-text names.

## Results

All runs from `.worktrees/cc4` with `.venv/bin/python` (3.12.11, `mcp==2.1.1` pinned). Pure
preparation: no store, no model, no clock, so **no Ladybug or Neo4j run is applicable to CD3** and
none was made.

| Run | Command | Result | Log |
| --- | --- | --- | --- |
| Baseline before RED | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_accepted_inputs.py tests/unit/test_ingest_readers.py -q -o addopts='' -W error` | 81 passed | `/tmp/hippo-cc4-baseline.log` |
| RED | the two new test files | 70 errors, `ModuleNotFoundError: No module named 'hippo.ingest.repo_capture'` | `/tmp/hippo-cc4-red.log` |
| GREEN, CD3 command | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_repo_capture.py tests/unit/test_code_provenance.py tests/unit/test_accepted_inputs.py -q -o addopts='' -W error` | **126 passed** | `/tmp/hippo-cc4-cd3.log` |
| GREEN, CD3 plus baseline and the plain-provenance suite | the CD3 files plus `test_ingest_readers.py test_managed_reader_provenance.py` | 198 passed | `/tmp/hippo-cc4-green-cd3.log` |
| Layering and downstream | `tests/unit/test_layering.py test_managed_chunk_provenance.py test_ingest_chunker.py` | 132 passed | `/tmp/hippo-cc4-layering.log` |

Per file: `test_repo_capture.py` 27 passed, `test_code_provenance.py` 48 passed.

The CD3 CHECK line as the ledger spells it runs from `/Users/mascott/projects/hippo`; the command
above is byte-identical but was run from `.worktrees/cc4`, so the gate checker's own run passes
only once `wp/cc4` lands on `rag-it-all-tibs`.

No `filterwarnings` marker and no command-line warning filter were needed: neither new test module
imports `fastapi.testclient`, so the sanctioned anyio exception does not arise. Plain `-W error`
throughout.

Ruff, over every file changed:

```
.venv/bin/ruff check src/hippo/ingest/repo_capture.py src/hippo/ingest/code_provenance.py \
  tests/unit/test_repo_capture.py tests/unit/test_code_provenance.py
.venv/bin/ruff format --check <the same four files> <this file>
```

`All checks passed!` and `already formatted`.

## How each CD3 criterion is covered

| CD3 criterion | Test |
| --- | --- |
| inventory normalized, sorted, identical under a reordered walk | `test_inventory_is_normalized_sorted_and_classified`, `test_walk_order_does_not_change_the_accepted_identity` |
| ignored directories, oversized files, unsupported names and explicit exclusions each carry a distinct reason | `test_every_exclusion_reason_is_recorded_with_its_own_name`, `test_exclusion_reasons_are_a_closed_set`, `test_an_ignored_directory_is_recorded_once_and_never_descended` |
| symlinks, non-regular files, escaping paths, files changed during capture | `test_a_symlinked_directory_is_excluded_rather_than_followed`, the `symlink`/`not_regular` rows of the reason test, `test_an_archive_member_that_escapes_the_root_refuses`; changed-during-capture stays `capture_raw_inputs`'s existing `changed_during_capture` disposition and is unchanged by this slice |
| code and config decode with exact complete-line locators, Unicode byte mappings, legacy trim | `test_complete_line_locators_expand_to_whole_original_lines`, `test_leading_blank_lines_are_counted_in_the_original_not_the_analysis`, `test_parser_byte_ranges_map_through_unicode_to_complete_lines`, `test_a_parser_offset_inside_a_character_refuses`, `test_the_original_unit_maps_every_character_to_its_raw_bytes` |
| rich, archive-inside-archive and binary outcomes refuse in this seam | `test_rich_and_archive_names_refuse_in_this_seam`, `test_an_archive_inside_an_archive_refuses`, `test_binary_inputs_claim_no_decoded_original` |
| the manifest excludes itself and contains no absolute path | `test_manifest_records_only_relative_logical_paths` |
| every later read is from the captured raw object | `test_every_accepted_file_is_readable_from_the_captured_raw_object`; `read_code_provenance` takes bytes and verifies them against `raw_input.raw_hash`, so it cannot reach the checkout (`test_bytes_that_do_not_match_the_accepted_identity_refuse`) |
| identity stable across two captures; rails refuse before any raw write | `test_two_captures_of_the_same_tree_share_one_identity`, `test_capture_instant_and_head_revision_are_carried_but_never_hashed`, `test_the_file_rail_refuses_before_any_raw_write`, `test_the_total_byte_rail_refuses_before_any_raw_write`, `test_the_per_input_byte_rail_refuses_before_any_raw_write` |
| `.zip` and single file go through the same function | `test_an_archive_goes_through_the_same_function`, `test_a_single_code_file_goes_through_the_same_function` |

## Statements a reviewer should read as claims, not proofs

1. **The 20,000-case decoder parity test is a divergence guard, not an independent-decoder
   proof.** `read_code_provenance` delegates its decode to `read_plain_provenance`, so parity is a
   property of the code and the test cannot currently fail. It is there so that the day either
   seam's decode changes, CD3 goes red instead of the two lanes silently drifting. The test also
   asserts that a strict-decode name which is not clean UTF-8 fails identically in both seams
   (`refused > 0` in the run: the seeded corpus reaches that branch).
2. **Two independent checks were mutation-tested rather than merely observed green.** Deleting the
   inventory sort fails five tests including the two identity tests; intercepting `os.scandir` was
   confirmed to reach the walk (4 directories intercepted) so that the order-independence test is
   not vacuous.
3. `test_every_exclusion_reason_is_recorded_with_its_own_name` uses `max_file_bytes=32` rather than
   writing a 2 MB file; the production rail is `readers.MAX_FILE_BYTES`.
4. The unreadable-entry test chmods to `0o000` and **skips** itself if the test user can still read
   the entry, so it is a no-op when the suite runs as root.

## Corrections and findings for the reviewer and for CC5–CC9

1. **Plan section 2 is wrong about `read_plain_provenance`.** It states that
   `ingest/provenance.py:322` "rejects code". It does not: `provenance.py:349` decodes
   `CODE_EXTENSIONS` with `errors="replace"` and `:377` sets `is_code=True`. Only rich extensions
   and `.zip` are refused there. The premise for a separate code seam still holds — language
   detection, the parse rail and the locator helpers are genuinely new — but the reason given in
   the plan should be corrected before CC11 cites it. (`prepare_prose_chunks` was not examined by
   this slice; the claim about it is untested here.)
2. **Two byte rails, not one.** Capture excludes at `readers.MAX_FILE_BYTES` (2 MB), reproducing
   `repos._walk_files:144`. `codegraph.model.CODE_MAX_FILE_BYTES` (512 KiB) is the *parse* rail: a
   file above it is still captured and decoded, and is reported as `CodeUnit.parsable is False`,
   measured the way `extract.py:96` measures it. CC5 and CC6 must not treat `parsable=False` as an
   exclusion.
3. **`CodeUnit.parsable` does not promise a walker exists.** It means the language is one
   `readers.lang_of` names and the encoded analysis text clears the parse rail. Whether
   `codegraph.extract.WALKERS` has an implementation stays `extract_code`'s decision, because
   `ingest` may not import tree-sitter (`codegraph/model.py` docstring). Only
   `codegraph.model.CODE_MAX_FILE_BYTES` and `CODE_MAX_FILES` are imported.
4. **A strict-decode name that is not clean UTF-8 raises `UnicodeDecodeError`**, propagated
   unchanged from `read_plain_provenance`. It is a `ValueError`, so existing `except ValueError`
   handlers still close over it, but it is not one of this lane's typed errors. Left identical on
   purpose: wrapping it would break the parity contract CD3 asks for. If the reviewer wants a typed
   error, it belongs in `provenance.py` and therefore in another owner's slice.
5. **The repo walk and the archive walk disagree about dotfiles, faithfully.**
   `repos._walk_files:142` skips every dotfile in a checkout, while
   `readers._wanted_zip_member:305` keeps one whose name a reader knows (`.eslintrc.json`). Both
   are reproduced as written rather than unified, because the brief asks for a faithful
   reproduction of the legacy walk. Worth a ruling before CC10 if the divergence is unwanted.
6. **Nested-archive refusal is scoped to archive members.** An archive inside an archive refuses
   (`nested_archive`), as CD3 requires. A vendored `.tar.gz` inside a *checkout* is an ordinary
   `unsupported_language` exclusion, so one committed tarball cannot fail a repository. If CD3
   intends the checkout case to refuse too, this is a one-line change plus a test.
7. **Submodule detection is filesystem-shaped, not `.gitmodules`-shaped.** A child directory that
   contains a `.git` entry is a submodule and is not descended. It needs no git binary and no
   `.gitmodules`, and the capture root's own `.git` is never subjected to the test. A submodule
   whose gitlink has been removed from disk would not be detected; nothing in Task 5 depends on
   that case today.
8. **`observed_at` and `provider_revision` are carried and never hashed.** Plan section 5 keeps
   observation timestamps out of identity, and the head commit SHA enters through the repository
   `ArtifactRevision.provider_revision` that CC6 builds. Two captures of the same tree at different
   head SHAs therefore share one `manifest.sha256`, which is correct but is the kind of thing a
   reviewer should confirm they expected.
9. **The exclusion policy enters identity under a reserved configuration key.**
   `capture_repository_inputs` merges `{"capture": {"kind": ..., "exclusions": [...]}}` into the
   caller's configuration and refuses (`reserved_configuration`) if the caller already used the
   key. CC9 must not pass `capture` itself in `CodeBuildOptions`' input-affecting group.
10. **Excluded entries count against `CaptureLimits`, which they did not before.** This is the
    direct cost of CD3's "each carry a distinct recorded reason": every declined *file* becomes a
    disposition in the canonical manifest, so `limits.max_inputs` and `limits.max_manifest_bytes`
    must be sized for accepted **plus** excluded entries, not for accepted alone. A checkout with a
    20,000-file `assets/` tree that the legacy walk skipped in silence can now exceed
    `max_inputs`. Ignored *directories* are recorded once and never descended, which is what keeps
    `node_modules` cheap, but there is no equivalent collapsing for a large directory of ordinary
    unsupported files. CC9 owns this sizing; the orchestrator may want a ruling on whether
    `max_inputs` should be raised or unsupported files collapsed per directory.
11. **`walk_tree` never consults `should_stop`.** Cancellation is checked only once capture starts,
    inside `capture_raw_inputs`. Plan section 6 wants the build guard between steps; the walk of a
    5,000-file rail is fast enough that this was left as a finding rather than a signature change,
    but CC9 should know the enumeration phase is not cancellable today.
12. **`code_provenance.CODE_LANGUAGES` is a hand-copied tuple of `readers.lang_of`'s range.**
    `CodeUnit.__post_init__` rejects a language outside it, so the day a seventh language is
    registered (the Go/C#/Rust add-langs work already names more), that check fails closed on a
    legitimate file until the tuple is updated. Deriving it from the registry would need an
    `ingest` to `codegraph.languages` import, which pulls tree-sitter into the chunker's dependency
    path and is forbidden by `codegraph/model.py`'s docstring. Left explicit and documented; the
    alternative is to drop the membership check and let `lang_of` be the sole authority.
