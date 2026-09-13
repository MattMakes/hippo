# CC9b evidence: the code coordinator (gate CD8, and CD7's coordinator-visible clauses)

Worker `backend-developer-22`, 2026-09-12. Branch `wp/cc9b`, worktree `.worktrees/cc9b`, base
`d1910c8` (CC1, CC1fix, CC2–CC8 and CC9a merged). Contract:
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` sections 3, 5, 6, 7, 8.2, 8.3 and 10,
rulings 2, 4, 5, 7, 9, 10, 11, 12 and 13; brief `ai_docs/handoffs/briefs/cc9b-code-coordinator.md`;
`evidence-cc1.md` … `evidence-cc9a.md`, whose findings bind this slice; the design review
`ai_docs/reports/2026-09-12-code-capture-plan-review.md` (B3, B4, B6 dissolved, M2, M9, M11). No
gate checkbox is set here.

## Commits

| Hash | Subject |
| --- | --- |
| `3ac801c` | Surface the shallow boundary a managed build has to record |
| `0b01dc1` | Reuse an accepted revision the store already holds |
| `5f45611` | Build one code source through capture, staging and publication |

## Files

| File | Change |
| --- | --- |
| NEW `src/hippo/ingest/code_generation.py` | the coordinator, 1,037 lines |
| NEW `tests/unit/test_code_generation.py` | 33 tests, 1,000 lines |
| `src/hippo/codegraph/git_history.py` | `shallow_boundary(checkout)`, additions only (orchestrator grant, Q1) |
| `src/hippo/knowledge/code_binding.py` | `_reuse` plus an optional `stored_revisions=`, additions only (grant) |
| `src/hippo/knowledge/code_history.py` | the same optional argument on `bind_history` (grant) |
| `tests/unit/test_code_binding.py` | 3 added tests; the 52 existing cases are untouched |
| `tests/unit/test_code_history.py` | 2 added tests; the 55 existing cases are untouched |
| NEW `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc9b.md` | this file |

`git show --stat` for the three commits names exactly these seven files. `prose_generation.py`,
`build_run.py`, `managed_activation.py`, `pipeline.py`, `readers.py`, `repos.py`, `store/*`,
`context.py`, `status.py`, `docs/`, the checkpoint and `GATES.md` are untouched.

## Public signatures, verbatim

```python
CODE_PIPELINE_VERSION = "managed-code-v1"
CODE_PARSER_VERSION = "managed-code-v1"
CODE_LINKER_VERSION = "managed-code-linker-v1"
CODE_CONFIGURATION_KEY = "code"
CODE_GRAMMARS = ("csharp", "go", "python", "rust", "tsx", "typescript")
CANCELLED_MESSAGE = "Code source build cancelled"
RENEWAL_FAILED_MESSAGE = "Code build lease renewal failed"
OPENIE_SKIPPED, OPENIE_CODE, OPENIE_UNPARSED = "skipped", "code", "unparsed"
OPENIE_PROSE_DEFERRED = "prose_extraction_deferred"


class CodeBuildRefused(ValueError): ...


@dataclass(frozen=True)
class CodeTreeInput:
    root: Path
    paths: tuple[str, ...] | None = None
    kind: str = "repo"
    repository: object | None = None
    head_revision: str | None = None


@dataclass(frozen=True)
class CodeBuildOptions:
    # input-affecting: hashed into generation identity
    chunk_size_chars: int = 1500
    chunk_overlap_chars: int = 150
    synonymy_threshold: float = 0.8
    history_depth: int = 25
    exclusions: tuple[str, ...] = ()
    allow_empty: bool = False
    # operational: never hashed
    capture_limits: CaptureLimits = ...
    max_decoded_chars: int = 8_000_000
    max_files: int = CODE_MAX_FILES
    max_file_bytes: int = 2_000_000
    max_symbols: int = CODE_MAX_SYMBOLS_PER_SOURCE
    max_chunks: int = 20_000
    max_batch_payload_bytes: int = staged_code.PAYLOAD_CEILING_BYTES
    batch_size: int = 128
    checkpoint_interval: int = 1
    workers: int = 2
    git_timeout_seconds: int = 20
    history_total_seconds: int = 120
    lease_duration_seconds: float = 300.0
    renewal_interval_seconds: float = 30.0


def build_code_source(
    ctx,
    *,
    source_id,
    actor,
    tree: CodeTreeInput,
    options: CodeBuildOptions,
    raw_store,
    embedding_spec,
    operation_id,
    should_stop,
    on_progress=None,
    embedding_cache: EmbeddingCache | None = None,
) -> BuildReceipt: ...
```

In `codegraph/git_history.py`:

```python
def shallow_boundary(checkout: Path) -> frozenset[str]: ...
```

In `code_binding.py` and `code_history.py`, both keyword-only with a `None` default so no existing
call site changed:

```python
def code_generation(capture, *, ..., stored_revisions=None) -> k.Generation: ...


def materialize_code_evidence(capture, chunks, facts, *, ..., stored_revisions=None): ...


def bind_history(history, *, ..., stored_revisions=None) -> CodeHistoryBundle: ...
```

### Two deviations from the brief's spelling, both forced

1. **`CodeTreeInput.paths` becomes an exclusion policy, not a capture argument.**
   `capture_repository_inputs` has no "only these paths" parameter, and inventing one would be CC4's
   change. When `paths` is given the coordinator walks first (`walk_tree`, pure, no raw write),
   refuses if any requested path is not a capturable file, and passes the complement as
   `exclusions` — so the restriction enters identity through CC4's reserved `capture` key and a
   narrowed build is honestly a different generation.
   (`test_explicit_paths_capture_only_those_files_and_enter_identity`,
   `test_a_requested_path_outside_the_walk_refuses_before_capture`.)
2. **No clone-depth field exists.** The brief lists clone depth among the operational options, but
   cloning is CC10's (`repos.py`) and this coordinator is handed a checkout. What it does own is
   proved absent from identity instead
   (`test_the_worker_count_progress_and_capture_instant_stay_out_of_identity`).

## What enters generation identity, and what does not

The configuration `generation_for_inputs` hashes is, exactly:

| Key | Value |
| --- | --- |
| `embedding_profile` | the verified profile descriptor |
| `generation_profile` | `"code"` — CC8's selector, so the profile cannot be re-labelled later |
| `code_history_derivation` | CC7's `CODE_HISTORY_RULE_VERSION`, top-level, set before `code_generation` |
| `code_derivation` | CC6's `{binding, chunker}`, folded by `CodeGenerationInputs.folded` |
| `capture` | CC4's own reserved key: capture kind and the exclusion policy |
| `code` | rule, effective chunk size/overlap after the clamp, chunker profile, synonymy threshold and rule, history depth, `allow_empty`, `openie: "skipped"`, `walker_rules_version`, `syntax_schema_version`, `parser_profiles` |

Plus the accepted artifact/revision pairs (the head SHA rides in as the repository revision's
`provider_revision`), the parent generation, `parser_version` and `linker_version`.

**Not in identity**, asserted rather than claimed: `workers`, `batch_size`, `checkpoint_interval`,
`max_chunks`, `max_files`, `max_batch_payload_bytes`, the lease intervals, the progress callback and
the capture instant. `test_the_worker_count_progress_and_capture_instant_stay_out_of_identity`
asserts the hashed configuration contains none of those names and then rebuilds with four of them
changed, getting `already_current` and the same generation ID.

### The configuration round trip (CC8 finding 1)

Done in the order CC8's evidence names, and it is the one thing that would otherwise fail with
"Generation identity differs from its accepted input manifest":

1. the base configuration above (no `capture`, no `code_derivation`);
2. `identity.folded(EXPECTED_CODE_CHUNK_RULE_VERSION)` → adds `code_derivation`;
3. `capture_repository_inputs(configuration=folded)` → adds `capture`;
4. the manifest's configuration is read back and `code_derivation` **removed**; that dict is
   `CodeGenerationInputs.configuration`, so `folded()` reproduces the manifest's copy exactly.

`test_the_head_sha_the_walker_rules_and_the_grammar_profiles_are_identity` reads all four keys back
out of the persisted manifest revision.

### The grammar table

`CODE_GRAMMARS` is a hand-copied closed tuple, for the reason `code_provenance.CODE_LANGUAGES` is
one: deriving it would import the walker registry into `ingest`.
`test_the_grammar_table_fails_closed_on_a_seventh_grammar` pins it against
`syntax_cache._DISTRIBUTIONS`, so adding a grammar without adding its version to identity fails.
The whole table is recorded, not only the grammars a tree happened to reach: which languages a
repository contains is data, and a per-tree table would make one configuration hash two things.

## The three paths, one line each

- **Bootstrap** (`active_generation_id is None`): resolve the profile → capture → settle identity →
  resolve the one instant → `_prior_receipt` → read, extract, walk history, chunk, bind, merge →
  `bind_inputs` → install (holder check, `recover_generation_builds`, `put_knowledge(gen)`,
  `begin_managed_source`, claim, accepted **and** history pairs plus members under
  `generation_write`, profile binding, fresh-authority comparison) → embed → probe → batches with
  `run.check()` between them → seal → publication in one short transaction under the source lock
  with `expected_parent_id=None`.
- **Refresh** (a pointer exists): the identical code path; G1 stays the active pointer throughout,
  the parent is G1, publication uses `expected_parent_id=G1`, and a failure or cancellation leaves
  G1 active with the source `status="ready"`.
- **Resume**: the same generation ID is reclaimed rather than claimed (never-published `staging` or
  `failed`), its stored `created_at` is adopted as the capture instant, `probe_staged_rows` decides
  which dependency groups already exist, and the receipt reports the groups that were real staging
  work.

**Bootstrap versus refresh is decided from the active pointer, never from `managed`** (B2 shape (b)):
a resumed bootstrap has `managed=True` and no pointer, so `prose_generation.py:~656`'s "Managed
source needs explicit recovery before initial publication" check is deliberately **not** copied.
`test_cancellation_between_batches_leaves_a_resumable_generation` and
`test_a_crash_mid_batch_resumes_the_same_generation_and_reports_the_skipped_groups` both run that
shape.

**B6 stays dissolved.** The `+ int(not source_is_managed(...))` term appears exactly once, in the
install window, as prose does it. `_publish` asserts both epochs unchanged with no arithmetic, so a
genuine unrelated authorization change in the publication window still refuses.

## The defect this slice found, and the amendment it was granted

**A code refresh over an unchanged file could not write at all.**
`ArtifactRevision.identity_fields` is `(artifact_id, provider_revision, content_hash)`, so an
unchanged file in generation 2 derives the **same** revision ID with a later `observed_at`;
`build_authority._inventory` then raises "Accepted record differs from current stored identity" and
`put_knowledge` would raise "Immutable record already exists with different contents". Every
`history_event` revision of a commit the source already holds has the same collision. The reviewed
prose lane has always solved this in `prose_generation._pair`: an immutable revision is written once
and `observed_at` means *first* observed.

The coordinator cannot fix it alone — `staged_code._accepted` re-reads every accepted and history
pair and compares it to the **bundle's** copy, so a coordinator-side swap makes the writer refuse
instead. Reported and granted (orchestrator, 2026-09-12): `code_binding` and `code_history` take an
optional `stored_revisions` mapping and reuse a stored record whose
`(artifact_id, content_hash, provider_revision, raw_uri)` tuple matches, refusing one that
contradicts the capture. Nothing enters identity: `observed_at` is hashed nowhere, and
`test_stored_revisions_change_no_generation_identity` pins that.

The coordinator binds twice on a refresh and once on a bootstrap: the pure binding runs, the
revisions it minted are looked up (`_knowledge_get` per revision, bounded), and the binding is
re-run only if the store actually holds a differing record. Extraction, the history walk and
chunking never repeat.

Proposed ledger clause (CD7, and CD9 for the reopen case): *a refresh over an unchanged file reuses
its immutable revision, so one revision record is a member of both generations and its `observed_at`
stays the instant it was first observed.*

## Rulings and prior-slice findings, and where each is discharged

| Obligation | Where |
| --- | --- |
| Ruling 11 / CC7 finding 2: `HISTORY_CONFIGURATION_KEY` set **before** `code_generation` | `_configuration`; read back in the identity test |
| CC7 finding 2: the **folded** configuration goes to `capture_repository_inputs` | `build_code_source`, step 3 above |
| CC6 finding 10 / CC7 finding 3: subtract the unbound-symbol complement from `History.modifies` | `_prepare`; recorded as `unbound_nodes` and `history_modifies_dropped` |
| CC7 finding 8: union coverage into the merged `coverage_json`, never overwrite | `_prepare`; `test_coverage_records_what_this_generation_does_not_contain` reads both halves |
| CC7 finding 11: obtain the shallow boundary yourself, never `None` for a real shallow clone | `shallow_boundary(checkout)` (Q1 grant) |
| CC7: `bind_history` requires `observed_at == code_bundle.generation.created_at` | one instant threaded through `gen.created_at` |
| Ruling 11 (extensionless README): `window`/`prose` passage, `openie=skipped` reason `unparsed` | `_unit`; coverage test asserts `NOTES` |
| CC5's parity latch stays | untouched; `prepare_code_chunks` is called as-is |
| CC4 evidence 9: never pass `capture` yourself | only `folded` is passed; the test asserts the key came from CC4 |
| CC4 evidence 10: size `CaptureLimits` for accepted **plus** excluded entries | default `max_inputs = 3 × CODE_MAX_FILES`; asserted in the options test |
| CC4 evidence 11: `walk_tree` is not cancellable | the coordinator's `should_stop` reaches `capture_raw_inputs` only; named below |
| CC4 finding 2: `parsable=False` is captured, not excluded | no parse-rail option exists; the rail stays `codegraph.model`'s |
| CC8 finding 2: rebaseline must precede the failing check | `_rebaseline` compares epochs before every `run.check()` in the write loop |
| CC8 finding 7: `batch_size` is groups per transaction | documented on the option and used that way in the tests |
| CC8 finding 8: probe and write the same `PreparedCodeIndex` object | one `prepared` value flows from `_index` into `probe_staged_rows` and `_write` |
| Ruling 12: the shared chunk/capture dataclasses may move to `knowledge/inputs.py` | **not done**, recorded as deferred (below) |
| Ruling 13: the coordinator sets the `code` generation profile in configuration | `GENERATION_PROFILE_KEY: CODE_PROFILE` |

## Ruling 5, as a named deferral

A `readers.PROSE_EXTENSIONS` file inside a captured tree is captured and bound like any other
passage: `read_code_provenance` refuses a plain-prose name by contract, so the coordinator decodes it
through `read_plain_provenance` and wraps it in the same `CodeUnit` an unparsed file gets, which is
the shape `prepare_code_chunks` sends down its reviewed `prepare_prose_chunks` branch. Only public
types are used and no seam was widened.

Ruling 5's **OpenIE half is deferred**, with the orchestrator's agreement: `CodeEvidenceBundle` and
`MergedCodeBundle` carry no `ProseExtraction` field and `staged_code._inventory` refuses one outright
("A code generation produces no prose extraction"), so extraction inside a code generation needs CC6,
CC7 and CC8 widened together. `coverage_json` records it per file rather than implying it:
`openie_reasons["README.md"] == "prose_extraction_deferred"`, beside `"code"` for a code file and
`"unparsed"` for an extensionless one. Routed to CC11 as a follow-up slice.

## `coverage_json`

CC7's `history_*` keys, unioned with this lane's:

```text
capture_kind, files_accepted, files_excluded{reason: count}, files_refused{reason: path},
openie: "skipped", openie_reasons{path: reason}, passages{kind: count}, symbols, data_objects,
code_edges, code_truncated, unbound_nodes, history_modifies_dropped
```

Coverage is written into the `Generation` row **once, at install, and only when the row is created**.
On a resume the persisted coverage is the first attempt's and is left alone, because by then it also
carries the store's own `embedding_mode` and `embedding_manifest_revision_id` keys, which a rewrite
would clobber. Recorded here rather than discovered by a reviewer.

## Results

All runs from `.worktrees/cc9b` with `.venv/bin/python` (3.12.11, `mcp==2.1.1` pinned). Invocation
shape: `HIPPO_TEST_STORE=<backend> .venv/bin/pytest <files> -q -o addopts='' -W error`.

| Run | Command | Result | Log |
| --- | --- | --- | --- |
| Baseline before any edit | `test_prose_generation.py test_staged_code_writer.py test_generation_resume.py test_build_run.py test_converting_source_serving.py` | 169 passed, 2 skipped | `/tmp/hippo-cc9b-baseline.log` |
| RED | `test_code_generation.py` with `code_generation.py` moved aside | 32 errors, `ModuleNotFoundError` | `/tmp/hippo-cc9b-red.log` |
| GREEN, per file | `test_code_generation.py` | **33 passed** (20.7s) | `/tmp/hippo-cc9b-green-code.log` |
| GREEN, **the CD8 line** | `test_code_generation.py test_ingest_pipeline.py test_ingest_concurrency.py test_managed_pipeline_activation.py test_prose_generation.py` | **251 passed, 3 skipped** | `/tmp/hippo-cc9b-cd8.log` |
| GREEN, wide Fake regression | the baseline set plus `test_code_binding.py test_code_history.py test_git_history.py test_layering.py test_import_order.py test_generation_profiles.py test_build_authority.py` | **452 passed, 2 skipped** | `/tmp/hippo-cc9b-green-fake.log` |
| GREEN, the amended suites | `test_code_binding.py` 55, `test_code_history.py` 57 | 112 passed | in the regression above |
| **GREEN, Ladybug** | `test_code_generation.py test_converting_source_serving.py` | **50 passed** (1,920.65s) | `/tmp/hippo-cc9b-ladybug.log` |
| Ladybug, one build alone | `test_code_generation.py -k reaches_no_destructive` | 1 passed (54.86s) | `/tmp/hippo-cc9b-lb-one.log` |

The CD8 CHECK line as the ledger spells it also names `tests/unit/test_managed_code_activation.py`,
which **does not exist**: it is CC10's file. The command above is the ledger's line minus that one
path, and the gate's own run passes once CC10 lands.

The CD8 run needs the sanctioned anyio filter, form **(b)**, because
`test_managed_pipeline_activation.py` imports `fastapi.testclient` at module level:
`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`. Every
other run above is plain `-W error` with no marker and no filter; `test_code_generation.py` itself
needs neither.

The RED log was produced by moving the finished module aside and re-running, the way CC8's was: it
proves every test binds to the module's contract rather than to an import that happens to succeed.
The first honest run against the real module is `/tmp/hippo-cc9b-first.log` (2 passed, 1 failed on
the first assertion) and `/tmp/hippo-cc9b-run2.log` (13 passed, 19 failed), which is where the
revision-reuse defect surfaced.

Ruff, over every file changed and over this document:

```text
.venv/bin/ruff check src/hippo/ingest/code_generation.py src/hippo/codegraph/git_history.py \
  src/hippo/knowledge/code_binding.py src/hippo/knowledge/code_history.py \
  tests/unit/test_code_generation.py tests/unit/test_code_binding.py tests/unit/test_code_history.py
.venv/bin/ruff format --check <the same seven> \
  ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc9b.md
```

`All checks passed!` and `already formatted`.

## Ladybug and Neo4j

**Query shapes added: none.** Every store call this slice makes already existed:
`transaction`, `_lock_source`, `_now`, `get_source`, `update_source`, `source_is_managed`,
`authorization_epoch`, `suppression_epoch`, `_knowledge_get`, `_knowledge_rows`, `_generation`,
`put_knowledge`, `begin_managed_source`, `recover_generation_builds`, `claim_generation_build`,
`reclaim_generation_build`, `generation_write`, `bind_generation_embedding_profile`,
`publish_staged_generation`, `fail_generation_build`, `validate_generation_seal`,
`in_ambient_transaction`, plus CC8's writer and CC2's scoped reads underneath it. No Cypher was
written, no schema step added, no index declared, so the Neo4j parity run for CD8 is a re-run of the
same files rather than a shape review.

The Ladybug lines ran **after** `wp/lbfix` merged (`rag-it-all-tibs` at `9770c00`, merged into
`wp/cc9b` at `3ca02d5`), because `staged_code._immutable_native` reaches
`_native_rows(kind, ids=[...])`, the exact shape the recorded real_ladybug 0.15.3 engine defect
answered from the wrong row. **50 passed**, so CC1's converting-source suite and this coordinator's
suite are both green on the acceptance backend and close/reopen behaviour is exercised by the
per-test database.

**One managed code build costs about 45 seconds on LadybugDB against 0.6 on the fake**, measured
alone (`/tmp/hippo-cc9b-lb-one.log`) on a five-file tree with three commits: roughly 68 dependency
groups, nine batch transactions, the resume probe, `generation_checksums` at the seal and
`generation_counts` at publication. Nothing here is a scale measurement — CD9 owns that — but it is
the number a reviewer should have before reading the plan's multi-hundred-file expectation, and it is
why this suite takes 32 minutes on Ladybug and 21 seconds on Fake.

## How each CD8 criterion is covered

| CD8 criterion | Test |
| --- | --- |
| an authenticated actor converts an eligible `repo`, `archive` or code `file` | `test_a_bootstrap_publishes_one_code_generation_and_flips_the_lane`, `test_an_archive_without_a_repository_builds_through_the_same_path` |
| the legacy graph serves unchanged until publication | `test_the_legacy_graph_answers_every_query_until_the_publication_commits` (snapshots the whole served graph from inside `on_progress`, batch by batch), `test_a_bootstrap_publishes_one_code_generation_and_flips_the_lane` |
| refresh keeps G1 selected through capture, extraction, every write batch and the seal, and after failure or cancellation | `test_a_refresh_keeps_g1_selected_through_every_batch_and_publishes_atomically`, `test_a_fault_mid_batch_leaves_g1_active_and_the_staged_inventory_retained` |
| a crashed build resumes the same generation and reports the skipped batch count | `test_a_crash_mid_batch_resumes_the_same_generation_and_reports_the_skipped_groups`, `test_a_resumed_build_adopts_the_persisted_capture_instant_even_at_a_new_clock` |
| `already_current` returns without inference | `test_an_unchanged_tree_under_a_new_operation_is_already_current`, `test_an_operation_id_replay_returns_the_first_receipt_without_inference` (asserts the wire: nothing of the tree is embedded again) |
| the head SHA, walker rules version and per-grammar parser profile participate in identity while worker count, clone depth and progress do not | `test_the_head_sha_the_walker_rules_and_the_grammar_profiles_are_identity`, `test_the_worker_count_progress_and_capture_instant_stay_out_of_identity`, `test_a_smaller_history_depth_is_a_different_generation`, `test_a_changed_derivation_version_is_a_different_generation` |
| `BuildAuthority.rebaseline` accepts an unrelated epoch change and refuses after any capability loss, suppression or sticky failure | `test_a_long_build_rebaselines_across_an_unrelated_authorization_change`, `test_a_capability_loss_mid_build_aborts_and_never_rebaselines`, `test_a_suppression_change_mid_build_aborts_rather_than_rebaselining` |
| spies on `_clear_passages`, `delete_passages_for_source`, `delete_code_nodes_for_source`, `remove_orphans`, `store.delete_source`, `shutil.rmtree` and generation collection are never called | `test_a_bootstrap_reaches_no_destructive_operation`, and the same spy set inside the fault and capability-loss tests |
| the reviewed prose coordinator suite is unchanged | `test_prose_generation.py` in the CD8 run, untouched |
| cancellation leaves a resumable staging generation | `test_cancellation_between_batches_leaves_a_resumable_generation` |
| ceilings refuse before installing anything | `test_every_ceiling_refuses_before_it_installs_anything` (files, symbols, chunks, per-batch payload) |
| privacy: no path, URL or source text in logs, the Source row or the receipt | `test_no_log_record_source_row_or_receipt_carries_a_path_url_or_source_text`, `test_a_refused_capture_never_names_the_path_it_refused` |
| a busy source refuses | `test_a_live_holder_refuses_the_build_as_busy` |

CD7's coordinator-visible resume clauses — the adopted capture instant, the byte-identical
observation inventory, the nonzero `resumed_from_batches`, and a retry with different inputs
superseding rather than resuming — are covered by the three resume tests plus
`test_a_resume_after_a_changed_tree_supersedes_rather_than_resuming`.

## What a reviewer must not read as proven

1. **`resumed_from_batches` excludes the install's own revision-member groups.** CC8's finding 3
   leaves the choice open; the number reported here is skipped groups **minus** the members the
   install writes before every attempt, fresh or resumed, because the probe recognises those on a
   *fresh* build too and a first bootstrap reporting "resumed from four batches" would be false.
   `test_a_fresh_bootstrap_reports_no_resumed_batches_although_its_members_are_installed` pins it,
   and the crash test pins the other side (`written - 1`, the first batch being the accepted
   preflight, which writes no row).
2. **The fixture is a five-file checkout with three real commits**, two walker languages (Python and
   TypeScript), one SQL file, a `README.md`, an extensionless `NOTES`, and two excluded files. It
   exercises every group kind and both text-file shapes, but it is **not** the multi-hundred-file
   fixture CD9 asks for, and no ceiling is measured: each ceiling is proved by lowering the option,
   not by building a corpus that reaches it.
3. **No throughput, query-count or scale claim is made.** CD1's bound is CC2's and CD9's.
4. **The heartbeat can still lose the rebaseline race.** `LeaseHeartbeat` calls `run.renew()` →
   `check()` → `guard.check_local()` on its own timer, and `check_local` latches an epoch mismatch,
   which ruling 2 then forbids rebaselining after. The tests set `renewal_interval_seconds=120` so
   the loop's own comparison always wins. In production a build that loses the race fails with the
   staged inventory retained and the next attempt resumes, so nothing is lost but time — but the
   window is real and belongs in CC11's review. Closing it needs a hook in `build_run.py` (CC9a's
   file), which is why it is named rather than patched.
5. **A crash between the seal and the publication is not resumable.** `seal_generation` leaves the
   generation `ready`, and `reclaim_generation_build` admits only `staging`/`failed`, so such an
   attempt needs the explicit failed-generation cleanup path. Pre-existing store behaviour (CC3);
   named here because this coordinator is the first caller that could hit it.
6. **`walk_tree` is not cancellable** (CC4 finding 11), so a `should_stop` raised during enumeration
   is only observed once `capture_raw_inputs` starts.
7. **A structural graph over a published generation must be released.** `context.graph_for` returns a
   graph holding a leased `SnapshotReference` and releases it only on its own failure path, so a
   caller that keeps it pins the generation — on LadybugDB the next build's publication then waits on
   it and never returns. The suite's `served()` helper closes it in a `finally`; production callers go
   through `query_session`, which already does. Found by this slice's first Ladybug run, which made
   no progress past the serving test until the release was added.

## Findings for CC10, CC11 and the reviewer

1. **`_operation_generation` and `_receipt` read whole record tables.** `_knowledge_rows("MaintenanceJob")`
   and `_knowledge_rows("IndexEvent")` are unscoped, copied verbatim from the reviewed
   `prose_generation.py` so the two lanes cannot drift. CC2's `where=` allow-list would bound both
   (`job_key`, `generation_id`); it is a shared change and belongs with the prose lane's copy, not
   only here.
2. **Ruling 12's relocation is deferred.** The shared chunk/capture dataclasses stay in
   `hippo.ingest`; `knowledge/code_binding.py` still validates them structurally and
   `tests/unit/test_layering.py`'s allow-list is unchanged. Recorded as deferred, as the ruling
   requires.
3. **Renames stay `history_renames: "not_reported"`.** The Q1 grant allowed promoting them "if it is
   a trivial promotion of what `_Diff` already computes", and it is not worth it: the value CC7
   writes into coverage is a hardcoded literal inside `bind_history`, which is not this slice's to
   change, so surfacing the rename list on `History` would record nothing new.
4. **CC10 inherits three refusals from this seam.** `CodeTreeInput` refuses a non-absolute root, a
   descriptor or head revision on an archive or single file, and unsorted or denormalized requested
   paths; `build_code_source` refuses a source whose kind differs from the captured tree's, an
   ambient transaction, and a non-`CodeBuildOptions` options object. Dispatch should surface those as
   its own closed errors rather than letting `CodeBuildRefused` (a `ValueError`, so
   `public_errors` maps it to `operation_failed`) reach a user.
5. **`community` is still not written.** CC6 finding 4 and CC8 finding 3 stand: nothing in this
   coordinator computes or merges a community label, and `store.code.symbol_write_row` has nowhere to
   put one. CC11 should drop the claim from plan section 4 or open a `store/code.py` slice.
6. **A `HistoryError` is wrapped, not propagated.** `read_history` raises `HistoryError(RuntimeError)`,
   which is outside `public_errors`' closed table, and its message can quote a path or a remote URL.
   The coordinator re-raises it as `CodeBuildRefused("The repository history could not be read")`
   with the original as `__cause__`.
