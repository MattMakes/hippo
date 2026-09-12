# CC7 evidence: git history binding (gate CD6)

Worker `backend-developer-19`, 2026-09-12. Branch `wp/cc7`, worktree `.worktrees/cc7`, base `e02bb08`
(the merge of `wp/cc6`; CC4, CC5 and CC6 all landed). Contract:
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` sections 4, 5, 6 (step 5) and 9 and rulings
1, 4, 7 and 10; brief `ai_docs/handoffs/briefs/cc7-code-history.md`; CC6's `evidence-cc6.md`, whose
twelve findings bind this slice; the design review `ai_docs/reports/2026-09-12-code-capture-plan-review.md`
(m4, m5). No gate checkbox is set here.

## Files

Created, and nothing else was touched:

- `src/hippo/knowledge/code_history.py`
- `tests/unit/test_code_history.py`
- this file

## Public signature

```python
CODE_HISTORY_RULE_VERSION = "code-history-v1"
EXPECTED_CODE_BINDING_RULE_VERSION = "code-binding-v1"
HISTORY_CONFIGURATION_KEY = "code_history_derivation"
COMMIT_MESSAGE_FIELD_PATH = "commit.message"
COMMIT_EVIDENCE_CLASS = "declared"
HISTORY_WALK = "first_parent"
COMMIT_RAW_URI_SCHEME = "hippo-commit:"


def bind_history(
    history,
    *,
    code_bundle: CodeEvidenceBundle,
    repository,
    workspace_id: str,
    source_id: str,
    generation_id: str,
    generation_namespace: str,
    observed_at: datetime,
    history_depth: int,
    shallow_boundary,
) -> CodeHistoryBundle: ...


def merge_code_bundles(
    code_bundle: CodeEvidenceBundle, history_bundle: CodeHistoryBundle
) -> MergedCodeBundle: ...
```

Frozen values: `NativeCommitRow(native_id, row_json)` with `native_kind` / `row`;
`NativeModifies(commit_id, symbol_id, omega, hunk_json)` with `row`;
`BoundCommitPassage(chunk, generation, span, view, derived_record, derived_dependencies)` with `id` /
`retrieval_view_id` / `native_row()`;
`BoundCommit(sha, artifact, revision, knowledge_object, span, observation, native_row, binding, member,
passage)` with `records`; `CodeHistoryBundle`; `MergedCodeBundle`. Every refusal is a `ValueError`, as
CC6's already are, so `knowledge/public_errors.py` closes over them unchanged.

`CodeHistoryBundle` fields are `generation, workspace_id, rule_version, coverage_json, commits,
modifies, precedes`; the flat inventories (`artifacts, revisions, objects, observations, spans, views,
derived_records, derived_dependencies, native_rows, bindings, revision_members, evidence_members,
passages, records, coverage`) are **derived properties** of `commits`, so there is no second copy to
drift out of step with the first.

## The record shapes CD6 names

| Record | Value |
| --- | --- |
| `Artifact(kind="history_event")` | `external_id = canonical_uri = f"{repository_external_id}@{sha}"`, where `repository_external_id` is the string CC6 already bound (`https://git.example.com/acme/robots`, or `source:<source-id>` for an archive or single file). `connector_id` and `provider_instance` stay `None`; `policy_id` is the repository artifact's. |
| `ArtifactRevision` | `provider_revision = sha`; `source_updated_at` = the parsed author date; `source_timestamp_original` = the raw `%aI` text; `source_timezone` = its offset as `±HH:MM`; `source_precision = "second"`; `observed_at` = the one capture instant; `lifecycle = "active"`. |
| `content_hash` / `raw_uri` | `text_hash(canonical_json([sha, author, original_date_text, message]))` and `hippo-commit:<sha>`. See "decisions" below for why `ordinal` is excluded and why the URI names no stored object. |
| `KnowledgeObject(kind="commit")` | `canonical_key = [repository_object_id, sha]` — plan section 5's "repository plus SHA", spelled the way CC6 spells `file` and `symbol` keys, so two sources of one clone share one commit object. |
| `EvidenceSpan` | `locator_kind="field"` with `FieldLocator(field_path="commit.message")` on the `history_event` revision; `text` is the commit message. Never a synthetic whole-file `file_lines` span. |
| `ObjectObservation` | `valid_from` = author date, `valid_to = None`, `validity_kind="explicit_interval"`, `temporal_basis="commit"`, `temporal_precision="second"`, `recorded_from` = the capture instant, `recorded_to = None`, `evidence_class="declared"`, `attributes_json = {"sha", "author", "ordinal"}`, plus `source_timestamp_original` / `source_timezone` (see below). |
| `RetrievalView` + `DerivedRecord` + `DerivedDependency` | One projection per commit passage over its message span, built exactly as `input_binding._view` / `code_binding._view` build theirs, at `CODE_HISTORY_RULE_VERSION`. |
| native `Commit` row | `{id, source_id, generation_id, sha, author, date, message, ordinal}` — `store.code.commit_write_row`'s input plus `generation_id`, with `id = commit_id(source_id, sha, node_namespace=generation_namespace(gen))`. |
| `NativeBinding` | `native_kind="Commit"`, to the commit object and the message span. |
| `MODIFIES` / `PRECEDES` | `read_history`'s own shapes, unchanged: `{commit_id, symbol_id, omega, hunk}` and `(newer, older)` pairs. |
| `GenerationMember` | One per `history_event` revision (ruling 13). |

### The locator kind chosen for commit messages: `field`

`EvidenceSpan.locator_kind` is a closed set of seven (`model.py:411`). `diff_hunk` was the other
candidate, but `DiffHunkLocator` subclasses `FileLinesLocator` and therefore requires a `path`, a
`start`, an `end`, a `base_revision`, a `head_revision` and a `side` — coordinates inside **one file's
diff**, which a commit message is not part of. A commit message is a field of the commit record, and
`FieldLocator(field_path="commit.message")` says exactly that. It is also the shape CC6 chose for the
repository's own identity (`FieldLocator(field_path="repository.clone_path")`), so the two
non-file-backed spans in this lane are spelled the same way. `MODIFIES` hunks are native edge
payloads, not evidence spans, so nothing here needs `diff_hunk`.

### The `evidence_class` chosen: `declared` (design review m5)

`EvidenceClass` (`model.py:46-48`) is
`{syntax_observed, catalog_observed, declared, discussion_claim, model_inferred, human_verified}`, and
it is in `ObjectObservation.identity_fields`, so it is part of every observation ID and cannot be left
unset. `declared` is the only honest value: no walker parsed the commit (`syntax_observed` is CC6's
symbols), no tree inventory listed it (`catalog_observed` is CC6's files), nobody discussed it and no
model inferred it. Git reports the author's own message and the author's own timestamp, which is the
same relationship the repository's clone path has to CC6's `declared` repository observation. Ruled
the same way in `code-capture-notes.md` item 5d.

## Decisions this slice made on its own, with their reasons

| Decision | Reason |
| --- | --- |
| `source_timestamp_original` and `source_timezone` are set on the **observation** as well as the revision | `TemporalRecord` (`model.py:466-476`) carries both fields and `ObjectObservation.identity_fields` does **not** include them, so setting them costs no identity change and a reader of the observation alone never has to join back to the revision to learn that `2026-01-02T18:45:00+05:30` was the repository's own spelling. `model.Instant` normalizes `valid_from` to UTC, which is precisely why the raw text has to travel with it. |
| `content_hash` hashes `[sha, author, raw date text, message]` and deliberately **excludes** `ordinal` | A commit has no captured raw object, so its content hash has to be its metadata. `ordinal` is the position in *this* walk: a budget skip above a commit would otherwise restate that commit's identity and mint a second revision for an unchanged commit. Everything hashed is immutable git data. |
| `raw_uri = "hippo-commit:<sha>"` | `ArtifactRevision.raw_uri` is required `Text` and there is no raw object. `generation_profiles.py:168-178` dereferences `raw_uri` only for accepted `kind="file"` revisions (comparing it to the manifest's `hippo-raw:sha256:...`), and nothing else in `knowledge/` or `store/` reads it, so a scheme that names the commit is honest where borrowing the accepted manifest's URI — which would claim the commit's content is the tree's inventory — would not be. **CC8 must not try to fetch it.** |
| `metadata_json` on the commit revision stays `"{}"` | The message is the span, the rest is the observation's `attributes_json`. A third copy would be a third thing to keep consistent. |
| The commit object is keyed `[repository_object_id, sha]`, not `[provider_instance, repository_id, sha]` | CC6's `file` key is `[repository_object_id, path]` and its `symbol` key is `symbol_key(repository_object_id, ...)`. Reusing the repository **object ID** keeps every repository-scoped object in this lane keyed the same way and inherits CC6's fallback for an archive or a single file for free. |
| `bind_history` takes every scope argument the brief lists *and* checks each against `code_bundle` | Workspace, source, generation ID, generation namespace and the repository descriptor are all derivable from the bundle, so passing them is redundant — deliberately. `materialize_code_evidence` recomputes the generation it was handed for the same reason: a caller that believes it is binding a different generation than the bundle holds has a bug, and a checked redundant argument catches it here instead of at the seal. Each has its own refusal and its own test. |
| `observed_at` must equal `code_bundle.generation.created_at` | Plan section 9: "One capture instant is taken from the store clock at the start of the operation and threaded through every record." CC6 passes `observed_at` straight to `generation_for_inputs(created_at=...)`, so the generation records the instant it was settled at and this boundary can simply refuse a second one. `Generation.identity_fields` excludes `created_at`, so the same inputs at two instants are still one generation — which is what makes the B4 property (below) assertable at all. |
| `precedes` is carried as plain `(newer, older)` string pairs | That is exactly `History.precedes` and exactly what `store.code.add_precedes` takes. Wrapping two strings in a record would add a type without adding a check. |
| `modifies` is carried as `NativeModifies`, not raw dicts | The bundle has to be immutable and comparable between two runs, and `hunk_json` as canonical JSON is what makes that true. `row` rebuilds `add_modifies`'s input exactly, pinned by `test_modifies_rows_keep_their_hunks_and_bind_only_to_symbols_of_this_generation`, which compares `[row.row for row in bundle.modifies]` to the `History` it was given. |
| `CodeHistoryBundle`'s flat inventories are derived properties of `commits` | One source of truth. A bundle whose `spans` tuple could disagree with its `commits` tuple is a class of bug that simply does not exist here. |
| `coverage` uses flat `history_*` keys | `coverage_json` is assembled by CC9b from several slices' contributions; a flat prefixed namespace merges without a nesting convention and `history_skipped` is already the name `git_history.py:131` gives the number in `Source.meta["code"]`. |
| `shallow_boundary` is accepted as any iterable of SHA strings, refused if an entry is not nonempty text, and normalized to a sorted list in coverage | Nothing produces it today (finding 11), so this boundary cannot depend on one producer's type. Sorting makes two runs of one repository compare equal whatever order the caller read `.git/shallow` in. |

## Two additions to the brief's signature, both forced by CC6's code

1. **`merge_code_bundles` returns a new `MergedCodeBundle`, not a `CodeEvidenceBundle`.** The brief
   allows "a `CodeEvidenceBundle`-shaped result (or whatever CC6's evidence names as the writer's
   input type)". A literal `CodeEvidenceBundle` cannot hold this result and `code_binding.py` is not
   CC7's to edit: `NativeCodeRow.__post_init__` (`code_binding.py:231`) refuses any
   `native_kind` outside `("Symbol", "DataObject")`, and `_check_membership` (`:424-431`) requires the
   revision members to be **exactly** the manifest, the repository and the accepted files, so N
   `history_event` members raise "Code revision membership differs from its accepted inventory". Both
   refusals are correct for CC6's own half. `MergedCodeBundle` therefore carries CC6's field names and
   projections plus `history_artifacts`, `history_revisions`, `history_rule_version`, `coverage_json`,
   `modifies` and `precedes`, and re-runs the four CC6 check passes over the union. Reported to the
   orchestrator before implementation and accepted.
2. **`BoundCommitPassage` exists, because `BoundCodePassage` refuses a commit.**
   `BoundCodePassage.__post_init__` (`code_binding.py:270`) refuses any chunk whose kind is not in
   `BOUND_CHUNK_KINDS`, and `commit` is deliberately excluded. Without a commit-side equivalent the
   merged bundle would leave `commit_chunks` unbound — which is the exact thing CC7 exists to fix —
   and CC8 would have no dense `Passage` row for a commit. `BoundCommitPassage.native_row()` returns
   the same ten keys as `BoundCodePassage.native_row()`, field for field, and inherits CC6's finding 7
   (no `content_kind`).

## Orchestrator ruling obtained during this slice (2026-09-12)

One contract question was escalated before any implementation code was written, and its answer is
implemented as ruled.

**Where `CODE_HISTORY_RULE_VERSION` enters generation identity — option 3.** The brief said to fold it
under CC6's reserved `code_derivation` key "through the merge". That is not implementable as identity:
`CodeGenerationInputs.folded` (`code_binding.py:159-171`) writes exactly
`{"binding": ..., "chunker": ...}` and refuses a caller that pre-sets the key, and
`generation_profiles.validate_generation_profile:181-197` re-derives `generation_id` from the
**accepted manifest's** configuration — so a key added after the generation was settled is provenance
nobody ever checks. The ruling: export `HISTORY_CONFIGURATION_KEY = "code_history_derivation"` as a
top-level configuration key that **CC9b sets before it calls `code_generation`**, so
`generation_for_inputs` hashes it; and guard it, so identity provably includes it rather than merely
claiming to. `bind_history` and `MergedCodeBundle` both refuse a configuration that omits the key or
carries another value (`_require_history_configuration`), pinned by
`test_a_generation_whose_configuration_omits_the_history_rule_version_refuses` and
`test_a_generation_carrying_another_history_rule_version_refuses`. Ruling 10 is satisfied in substance:
a changed history derivation is a different generation, and resume across one is impossible by
construction.

## Fixture inventory (the two-file tree and its three commits)

CC6's fixture tree — `src/orders.py` (module, class, two methods, one function) plus `db/schema.sql` —
captured from `https://git.example.com/acme/robots.git`, with three hand-built commits whose middle
one carries a `+05:30` author offset:

| Record | CC7 | Merged with CC6 |
| --- | --- | --- |
| `Artifact(kind="history_event")` / `ArtifactRevision` | 3 / 3 | — |
| `KnowledgeObject(kind="commit")` | 3 | 13 objects total |
| `ObjectObservation` | 3 (all `declared`) | 23 |
| `EvidenceSpan` (all `field`) | 3 | 16 |
| `RetrievalView` / `DerivedRecord` / `DerivedDependency` | 3 / 3 / 3 | 9 / 9 / 9 |
| `NativeCommitRow` | 3 | 10 native rows |
| `NativeBinding` | 3 | 10 |
| `GenerationMember` | 3 | 7 |
| `GenerationEvidenceMember` | 15, equal to `len(bundle.records)` | 72 |
| `BoundCommitPassage` | 3 | 9 passages, `commit_chunks` 0 |
| `MODIFIES` / `PRECEDES` | 3 / 2 | 3 / 2 |

`coverage` for that run:

```
{"history": "read", "history_walk": "first_parent", "history_depth": 25, "history_commits": 3,
 "history_skipped": 0, "history_truncated": false,
 "history_shallow_boundary": ["a1a1a1a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7"],
 "history_renames": "not_reported"}
```

Three further shapes are covered outside that fixture: a commit the chunker never rendered (artifact,
revision, object, observation, span, native row and binding, no view —
`test_a_commit_with_no_passage_still_binds_its_artifact_object_and_row`); a disabled history
(`history_depth == 0`, nothing produced, `history: "disabled"`); and a merged bundle with no history at
all, which still closes.

## Results

All runs from `.worktrees/cc7` with `.venv/bin/python` (3.12.11, `mcp==2.1.1` pinned). Pure binding: no
store handle, no model client and no clock beyond the injected instant, so **no Ladybug or Neo4j run is
applicable to CD6** and none was made. Fake is the only backend this gate needs. The CD9 line does
re-run `test_code_history.py` under Ladybug; nothing in it is backend-sensitive.

| Run | Command | Result | Log |
| --- | --- | --- | --- |
| Baseline before RED | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_git_history.py tests/unit/test_code_binding.py tests/unit/test_managed_input_binding.py tests/unit/test_temporal_conflicts.py -q -o addopts='' -W error` | 152 passed | `/tmp/hippo-cc7-baseline.log` |
| RED | `tests/unit/test_code_history.py` | 2 failed, 53 errors, `ModuleNotFoundError: No module named 'hippo.knowledge.code_history'` | `/tmp/hippo-cc7-red.log` |
| GREEN, per file | `tests/unit/test_code_history.py` | **55 passed** | `/tmp/hippo-cc7-green.log` |
| GREEN, **the CD6 command** | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_history.py tests/unit/test_git_history.py -q -o addopts='' -W error` | **89 passed** | `/tmp/hippo-cc7-cd6.log` |
| GREEN, layering and upstream | `test_layering.py test_import_order.py test_code_binding.py test_managed_input_binding.py test_knowledge_contracts.py test_prepared_code_chunks.py test_repo_capture.py test_code_provenance.py test_temporal_conflicts.py` | 379 passed | `/tmp/hippo-cc7-regression.log` |

The CD6 CHECK line as the ledger spells it runs from `/Users/mascott/projects/hippo`; the command above
is byte-identical but was run from `.worktrees/cc7`, so the gate checker's own run passes once `wp/cc7`
lands on `rag-it-all-tibs`.

No `filterwarnings` marker and no command-line warning filter were needed: the new test module does not
import `fastapi.testclient`, so the sanctioned anyio exception does not arise. Plain `-W error`
throughout, including the subprocess that proves the no-ingest import.

Ruff, over both files changed and over this document:

```
.venv/bin/ruff check src/hippo/knowledge/code_history.py tests/unit/test_code_history.py
.venv/bin/ruff format --check src/hippo/knowledge/code_history.py tests/unit/test_code_history.py \
  ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc7.md
```

`All checks passed!` and `already formatted`.

### The tests were proved to discriminate

Every test in the new module failed at RED for one reason — the module did not exist — which proves
only that they run. Eight targeted mutations, plus a control, were applied to the finished module one
at a time, with the suite re-run and the module restored byte for byte after each:

| Mutation | Caught by |
| --- | --- |
| `COMMIT_EVIDENCE_CLASS` `declared` → `catalog_observed` | `test_a_commit_observation_carries_the_section_nine_temporal_row` |
| the `MODIFIES` foreign-symbol refusal removed | `test_a_modifies_edge_to_a_symbol_outside_this_generation_refuses` |
| `source_precision` `"second"` → `"unknown"` | `test_a_history_event_revision_carries_the_author_date_and_its_raw_text` |
| the `history_walk` coverage key removed | `test_a_disabled_history_produces_no_history_event_and_records_disabled` |
| `source_timezone` on the revision → `None` | `test_a_non_utc_author_offset_keeps_its_original_text_and_offset` |
| `_offset_text` emitting `+0530` instead of `+05:30` | the same, plus the UTC case |
| the capture-instant equality check removed | `test_a_capture_instant_that_differs_from_the_generation_refuses` |
| the history-configuration requirement removed | `test_a_generation_carrying_another_history_rule_version_refuses` |
| (control) the module restored byte for byte | suite green again |

## How each CD6 criterion is covered

| CD6 criterion | Test |
| --- | --- |
| one `history_event` artifact and revision per commit carrying the author date in `source_updated_at`, the raw `%aI` text in `source_timestamp_original`, its offset in `source_timezone` and `source_precision="second"` | `test_each_commit_becomes_one_history_event_artifact_and_revision`, `test_the_history_event_external_id_names_the_repository_and_the_sha`, `test_a_history_event_revision_carries_the_author_date_and_its_raw_text`, `test_a_non_utc_author_offset_keeps_its_original_text_and_offset` |
| commit observations use `valid_from` = author date, `validity_kind="explicit_interval"`, `temporal_basis="commit"`, `recorded_from` = the one injected capture instant, `recorded_to` null | `test_a_commit_observation_carries_the_section_nine_temporal_row`, `test_a_commit_observation_records_the_attributes_a_reader_renders` |
| every commit observation carries an explicit `evidence_class` (design review m5) | the same test, which pins `COMMIT_EVIDENCE_CLASS == "declared"` |
| no record calls a wall clock and no default instant appears anywhere | `test_the_module_holds_no_store_model_or_clock` (greps the module for `datetime.now`, `utcnow`, `utc_now`, `now()`, `time.time`, `_now(`), `test_a_naive_capture_instant_refuses`, `test_a_capture_instant_that_differs_from_the_generation_refuses`, `test_two_runs_with_the_same_inputs_produce_identical_ids` |
| `MODIFIES` hunks and `PRECEDES` pairs bind only to symbols of the same generation | `test_modifies_rows_keep_their_hunks_and_bind_only_to_symbols_of_this_generation`, `test_a_modifies_edge_to_a_symbol_outside_this_generation_refuses`, `test_a_modifies_edge_from_an_unbound_commit_refuses`, `test_precedes_pairs_chain_the_bound_commits_newest_to_oldest`, `test_a_precedes_pair_naming_an_unbound_commit_refuses`, `test_a_native_commit_id_that_does_not_match_the_generation_namespace_refuses` |
| `skipped`, `truncated`, the shallow boundary, renames and disabled history are recorded in coverage and never presented as a complete history | `test_coverage_records_the_walk_depth_skipped_truncated_and_the_shallow_boundary`, `test_a_disabled_history_produces_no_history_event_and_records_disabled`, `test_a_disabled_history_that_still_walked_commits_refuses`, `test_a_history_longer_than_its_configured_depth_refuses` |
| the first-parent restriction is recorded beside them (design review m4) | the two coverage tests above; `history_walk: "first_parent"` is recorded on every build, enabled or not |
| commit passages get a real locator and a rendered view over it | `test_a_commit_message_becomes_one_field_span_on_its_history_event_revision`, `test_no_commit_span_claims_a_line_of_any_captured_file`, `test_a_commit_passage_becomes_a_view_over_its_message_span`, `test_a_commit_passage_row_names_its_generation_view_and_span` |
| native IDs equal `commit_id` under the generation namespace, each with a binding | `test_every_commit_gets_a_namespaced_native_row_carrying_the_generation`, `test_every_commit_native_row_has_a_binding_to_its_object_and_span` |
| the exact membership closes | `test_every_history_event_revision_is_a_generation_member`, `test_the_evidence_member_closure_is_exactly_the_records_produced`, `test_every_referenced_identity_resolves_inside_the_history_bundle`, `test_only_the_five_exact_evidence_kinds_are_produced` |
| the merged inventory is the writer's input and revalidates | `test_the_merged_bundle_unions_both_inventories`, `test_the_merged_bundle_binds_every_commit_chunk`, `test_merge_validation_refuses_a_duplicate_record`, `test_merge_refuses_a_history_bundle_from_another_generation`, `test_the_merged_bundle_keeps_every_modifies_and_precedes_endpoint_present`, `test_a_merged_bundle_with_no_history_at_all_still_closes` |
| rule versions (ruling 10) | `test_the_history_rule_version_is_pinned`, `test_the_expected_binding_rule_version_is_pinned_to_the_one_cc6_produces`, `test_the_history_configuration_key_sits_outside_the_binding_reserved_key`, and the two configuration refusals |

## What a reviewer must not read as proven

1. **This bundle is not sealable yet, for CC6's reason and one more.** CC6's ruling 13 defers the
   `code` accepted-input profile to CC8. Nothing here was persisted, sealed or checksummed; the tests
   are pure. The additional constraint CC7 adds is finding 1 below.
2. **`test_the_module_imports_no_ingest_module` is a live subprocess check**, like CC6's. The
   `codegraph.model` import inside `_bind_commits` is deferred for the same reason CC6 defers its
   own — `hippo.codegraph`'s package body loads the tree-sitter walkers — and `codegraph` is not
   `ingest`, so `tests/unit/test_layering.py` is unaffected and still green.
3. **The three-commit fixture is hand-built, by design.** `read_history` itself is covered by
   `tests/unit/test_git_history.py` against real repositories (34 tests, green in the CD6 command).
   CC7 is tested against `History`'s *contract*, so a change to git's diff behaviour fails there, not
   here.
4. **`omega` is passed through, never recomputed.** `MODIFIES_OMEGA` stays `git_history`'s constant.

## Findings for CC8, CC9b and the reviewer

1. **CC8's `code` accepted-input profile must EXCLUDE the `history_event` pairs from its
   `generation_for_inputs` re-derivation.** `validate_generation_profile:123-141` builds `pairs` from
   **every** `GenerationMember` and then calls `generation_for_inputs(pairs, ...)` at `:185`, comparing
   the result to `generation.id` at `:196`. CC6 settled the generation from the tree, the manifest and
   the accepted files only — it had to, because plan section 6 settles the generation *before*
   `read_history` runs, so a commit can never be an identity input. So the widened profile must select
   `manifest + repository + one file per accepted input` for the hash while admitting the
   `history_event` members for the membership check. `MergedCodeBundle.accepted_pairs` is exactly the
   hashed set and `MergedCodeBundle.history_pairs` is exactly the complement; both are exported for
   this. The head SHA already carries the history's endpoint into identity as the repository revision's
   `provider_revision`. Routed to CC8 by the orchestrator on 2026-09-12.
2. **CC9b must set `HISTORY_CONFIGURATION_KEY` before calling `code_generation`.** Order:
   `configuration[code_history.HISTORY_CONFIGURATION_KEY] = code_history.CODE_HISTORY_RULE_VERSION`,
   then `CodeGenerationInputs(configuration=...)`, then `code_generation`, then the rest of section 6's
   order. The configuration that reaches `capture_repository_inputs(configuration=...)` must be the
   **folded** one — `CodeGenerationInputs.folded(chunk_rule_version)`, so it carries `code_derivation`
   as well as this key — because `validate_generation_profile:181-197` re-derives identity from the
   manifest's copy and CC6 hashed the folded dict. `bind_history` refuses the build if the key is
   missing or different.
3. **CC9b must subtract the unbound-symbol complement from `History.modifies` and record it in
   coverage.** This is CC6's finding 10 reaching the history lane. `bind_history` **refuses** a
   `MODIFIES` edge whose symbol has no native row in the bundle rather than dropping it, because a
   silent drop loses a commit's attribution and `native_mutation` would reject the write anyway
   ("Missing shared graph endpoint"). The one legitimate case is a symbol whose rendered body is only
   whitespace: the committed chunker skips such a group, so it sits in `facts.symbols` with no passage
   and no row, and a commit that touched it would fail the whole build. The complement is the same
   one-line set difference CC6 gave CC8:
   `{s.id for s in facts.symbols} | {d.id for d in facts.data_objects}` minus
   `{row.native_id for row in bundle.native_rows}`. CC9b holds both `facts` and the bundle; CC7 holds
   neither, which is why the filter is not here. A nonempty complement belongs in `coverage_json`
   beside the `history_*` keys.
4. **CC8 must not dereference a `history_event` revision's `raw_uri`.** `hippo-commit:<sha>` names the
   commit, not a stored raw object; there is nothing to fetch. Only accepted `kind="file"` revisions
   have a raw object, and only `generation_profiles.py:168-178` reads their `raw_uri`.
5. **The commit passage is a dense passage like any other.** `BoundCommitPassage.native_row()` returns
   the same ten keys as `BoundCodePassage.native_row()`. A commit with an empty message and no touched
   symbol renders to empty text, which is legal (`generation_checksums:719-724` requires dense coverage
   only for nonempty exact text) and still carries a view, because an empty passage is still not
   byte-identical to "one original region" in the sense `requires_view` means.
6. **`History` reports no renames, so coverage records `history_renames: "not_reported"`.** The brief
   asks for renames "if `read_history` reports them". It does not: `_Diff.renames` is internal to
   `git_history._hunks` and is consumed by the `alias` map inside the walk (`git_history.py:283`),
   never surfaced on `History`. Recording the absence is the honest option; surfacing the rename map
   would be a `git_history.py` change and belongs to whoever owns that file next.
7. **`ordinal` can have gaps and the coverage says so.** `read_history` numbers by position in the git
   log (`git_history.py:274`), so a skipped commit leaves a gap. `history_skipped` beside
   `history_commits` is what tells a reader the difference between a small repository and an
   incomplete walk.
8. **A merged bundle's `coverage_json` is the history bundle's.** CC6 leaves `coverage_json` at `"{}"`
   (its finding, coverage is CC9b's), so the merge takes CC7's whole map. CC9b must union its own
   coverage into it rather than overwrite it, or the `history_*` keys are lost.
9. **Two sources of one clone share a commit object; their observations do not.** The key is
   `[repository_object_id, sha]`, which contains no source, while the revision is source-scoped
   through the artifact and the observation is keyed by the revision. Structurally identical to CC6's
   symbol result; it is asserted here on the key shape rather than by building a second source, because
   the two-source case is already proven for CC6's half.
10. **`BoundCommit.records` is the per-commit dependency group.** `(span, derived_record, dependencies,
    view, observation)`, in dependency order, so CC8's "batches are complete dependency groups" can
    batch a commit at a time without recomputing the ordering.
11. **Nothing produces `shallow_boundary` yet — the brief is wrong about CC4.** The CC7 brief says
    "CC4 records the shallow-clone boundary and `files_skipped` on its capture result". It does not:
    `src/hippo/ingest/repo_capture.py` contains no occurrence of `shallow`, and `RepositoryCapture`
    (`:298-331`) carries `kind, root, inputs, exclusions, accepted, observed_at, provider_revision,
    repository` and nothing else. `git_history._shallow` (`:292`) does read `.git/shallow`, but it is
    private and its result is consumed inside the walk — `History` never surfaces it. So
    `shallow_boundary` is a caller-supplied argument here and **CC9b must obtain it itself**, either by
    reading `<checkout>/.git/shallow` in the coordinator or by having whoever next owns
    `git_history.py` promote `_shallow` to a public helper (the cleaner option: it already handles the
    full-clone, worktree and no-repository cases by returning an empty set). Passing `None` or `()` is
    accepted and records an empty boundary, which is correct for a full clone and **wrong and silent**
    for a shallow one — which is exactly why this needs naming rather than defaulting.
