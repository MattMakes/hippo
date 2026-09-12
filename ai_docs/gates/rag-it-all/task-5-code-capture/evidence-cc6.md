# CC6 evidence: code evidence and object binding (gate CD5)

Worker `backend-developer-18`, 2026-09-12. Branch `wp/cc6`, worktree `.worktrees/cc6`, base
`b516232` (the merge of `wp/cc5`; CC4 and CC5 both landed). Contract:
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` sections 4, 5 and 6 and rulings 1, 4, 7
and 10; brief `ai_docs/handoffs/briefs/cc6-code-binding.md`; CC4's `evidence-cc4.md` and CC5's
`evidence-cc5.md`; the design review `ai_docs/reports/2026-09-12-code-capture-plan-review.md` (m5,
m7). No gate checkbox is set here.

## Files

Created, and nothing else was touched:

- `src/hippo/knowledge/code_binding.py`
- `tests/unit/test_code_binding.py`
- this file

## Public signature

```python
CODE_BINDING_RULE_VERSION = "code-binding-v1"
EXPECTED_CODE_CHUNK_RULE_VERSION = "code-chunks-v1"
CODE_BINDING_CONFIGURATION_KEY = "code_derivation"
REPOSITORY_FIELD_PATH = "repository.clone_path"
BOUND_CHUNK_KINDS = ("header", "symbol", "data_object", "window", "prose")
DATA_OBJECT_KINDS = {
    "table": "table",
    "column": "column",
    "collection": "resource",
    "label": "resource",
    "rel_type": "resource",
}


def code_generation(
    capture,
    *,
    workspace_id: str,
    source_id: str,
    generation_identity_inputs: CodeGenerationInputs,
    observed_at: datetime,
) -> k.Generation: ...


def materialize_code_evidence(
    capture,
    chunks,
    facts,
    *,
    workspace_id: str,
    source_id: str,
    generation_identity_inputs: CodeGenerationInputs,
    observed_at: datetime,
) -> CodeEvidenceBundle: ...
```

Frozen values: `CodeGenerationInputs(parent_id, parser_version, linker_version, embedding_profile,
configuration, policy_id)` with `folded(chunk_rule_version)`;
`AcceptedCodeBinding(raw_input, artifact, revision)` with `logical_path` / `pair`;
`NativeCodeRow(native_kind, native_id, row_json)` with `row`;
`BoundCodePassage(chunk, generation, span, spans, view)` with `id` / `retrieval_view_id` /
`native_row()`; `CodeEvidenceBundle`. Every refusal is a `ValueError`, as
`input_binding.materialize_chunk_evidence` already raises, so
`knowledge/public_errors.py` closes over them unchanged.

`CodeEvidenceBundle` fields: `generation, workspace_id, rule_version, chunk_rule_version,
configuration_json, repository_artifact, repository_revision, repository_object, repository_span,
manifest_artifact, manifest_revision, accepted, objects, observations, spans, views,
derived_records, derived_dependencies, native_rows, bindings, revision_members, evidence_members,
passages, commit_chunks`, with derived `generation_id`, `source_id`, `configuration`, `records` and
`accepted_pairs`.

## Two additions to the brief's signature, both forced

1. **`code_generation` is a second public entry point.** The brief gives CC6 the job of computing
   `generation_id`, and plan section 6 step 4 extracts the code graph with
   `node_namespace=generation_namespace(gen)`. So the caller needs the generation *before* it can
   produce the `facts` that `materialize_code_evidence` consumes, while generation identity depends
   only on the accepted inputs and the configuration and never on the graph. `code_generation`
   settles identity from the captured tree alone; `materialize_code_evidence` recomputes the
   identical value from the same arguments and refuses any native ID that does not re-derive from
   its namespace, which is the same check `generations.py:1283-1298` makes before a write. Pinned by
   `test_the_generation_is_settled_before_extraction_from_the_tree_alone`. Without this the
   coordinator would have to guess the namespace or bind legacy (unnamespaced) IDs.
2. **The bundle carries the accepted manifest pair and the tree pair, not only the file pairs.**
   Plan section 5 hashes "every accepted artifact/revision pair plus the manifest pair", and
   `generation_profiles.validate_generation_profile:186-197` re-runs `generation_for_inputs` over
   the persisted member pairs and compares IDs, so a bundle that omitted either pair would compute a
   generation the store then rejects as "Generation identity differs from its accepted input
   manifest". `MANIFEST_EXTERNAL_ID` is reused from `knowledge/inputs.py` rather than re-spelled.

## Orchestrator rulings obtained during this slice (2026-09-12)

Three contract questions were escalated before any implementation code was written, and one
smaller one during it. All four answers are implemented as ruled.

1. **Layering — option B.** `code_binding.py` imports **no** `hippo.ingest` module.
   `tests/unit/test_layering.py:38` pins the knowledge-to-ingest allow-list to exactly
   `{input_binding.py, public_errors.py}` and asserts set equality, and that file is not CC6's to
   edit. The ruling was that the allow-list does not grow and that a later slice may move the shared
   dataclasses into `knowledge/inputs.py` instead. Consequences, both deliberate:
   - Inputs are validated **structurally** — by the fields this boundary actually reads, listed in
     `_CHUNK_FIELDS` and in each `_fields(...)` call — rather than by `type(x) is PreparedCodeChunk`
     as the prose materializer does. A missing field is a named `ValueError`
     (`test_an_input_that_is_not_a_prepared_code_result_refuses`).
   - `EXPECTED_CODE_CHUNK_RULE_VERSION = "code-chunks-v1"` is **pinned, not imported**. A
     `PreparedCodeChunks` carrying any other `rule_version` is refused
     (`test_a_chunk_rule_version_that_differs_from_the_pinned_one_refuses`, which monkeypatches
     CC5's constant to build a v2 result). The cost is that bumping
     `CODE_CHUNK_RULE_VERSION` without bumping this module refuses every code build; the benefit is
     that it can never silently bind a chunk derivation it was not written against.
   - `test_the_module_imports_no_ingest_module` runs a fresh interpreter and asserts no
     `hippo.ingest.*` module is loaded, so the property is enforced rather than asserted in prose.
2. **The tree artifact IS a `GenerationMember`.** CC6 reported that
   `generation_profiles.validate_generation_profile:157-180` requires the member set to be exactly
   one `kind="manifest"` artifact plus one `kind="file"` artifact per `accepted.inputs` entry, so a
   `kind="repository"` member raises "Accepted original revision inventory differs", and that
   `generation_checksums:776` ("Evidence outside raw manifest") therefore forbids any span,
   observation or view on a repository revision. **The plan holds**: the repository
   `Artifact`/`ArtifactRevision` is a member with the head SHA as `provider_revision`, CC7's
   `history_event` revisions likewise, and **CC8 adds a `code` accepted-input profile to
   `validate_generation_profile` and to the `Evidence outside raw manifest` rule** — manifest, one
   repository, one file per accepted input, N `history_event` — leaving plain prose byte-identical.
   **This bundle does not seal until that CC8 change lands.** See "What a reviewer must not read as
   proven" item 1.
3. **Observation shape.** File object: one observation per span of that file,
   `evidence_class="catalog_observed"` (it is tree-inventory evidence). Repository object: exactly
   **one** observation, `evidence_class="declared"`, on an `EvidenceSpan` of the **repository
   revision** with a `FieldLocator(field_path="repository.clone_path")` whose text is the normalized
   clone path CC4 recorded — explicitly never some file's first line, which would claim that a file
   states the repository's identity. Symbol and data object: `evidence_class="syntax_observed"`. The
   brief's "declared/observed/inferred" was shorthand; `model.py:46`'s Literal has no `observed` or
   `inferred` and `model.py` is not CC6's to edit, so the real values are used (design review m5's
   amendment, which needed no new field because `ObjectObservation.evidence_class` already exists
   and is already in its identity).
4. **`ObjectKind` narrowing, accepted as a named narrowing.** `codegraph.model.DATA_KINDS` is
   `(table, column, collection, label, rel_type)` and all five are reachable — `resolve.py:715-725`
   mints a Mongo `collection` from `mongoose.model(...)` and `read_sql_file` mints `label` and
   `rel_type` — but `model.ObjectKind` (`model.py:56-87`) has only `table` and `column`.
   `DATA_OBJECT_KINDS` maps `table`/`column` to themselves and `collection`/`label`/`rel_type` to
   the generic `resource`. **Nothing merges**: the object's `canonical_key` is
   `[repository_object_id, dialect, kind, qualname]` and its `attributes_json` carries `name`,
   `qualname`, `kind` and `dialect`, so a Mongo `orders` collection, a SQL `orders` table and a
   Cypher `orders` label are three distinct objects with three distinct keys. The only thing lost is
   the coarse presentation label. **For the CD10 reviewer:** the alternative is adding
   `collection`, `label` and `rel_type` to `model.py:56` `ObjectKind` and narrowing this map to the
   identity mapping; that is a one-line model change plus a migration review, and it is the
   reviewer's call, not this slice's. `test_the_data_object_kind_map_covers_every_codegraph_data_kind`
   pins the map against `DATA_KINDS` so a sixth data kind fails closed.

## Decisions this slice made on its own, with their reasons

| Decision | Reason |
| --- | --- |
| Symbol `canonical_key` is `symbol_key(repository_object.id, lang, path, qualname, signature or None, kind=kind)` | The repository **object ID** as the first element is what makes CD5's "a shared canonical symbol observed by two sources keeps distinct per-source observations" true: two sources of one clone URL get one repository object, hence one symbol object, while their revisions and therefore their observations differ. `signature or None` makes an empty walker signature identical to an absent one. |
| A tree with no clone URL gets `external_id = canonical_key = ["source:<source-id>"]` | Plan section 5's source-scoped fallback. `repository_key` normalizes its instance through `normalize_provider_url`, which refuses anything that is not `http(s)`, so the fallback cannot go through it. A source-scoped key can never collide with a forge key, whose first element is an `https` instance URL. Applies to an archive, a single file, and a checkout captured without a descriptor. |
| The tree artifact is always `kind="repository"`, never `kind="file"` | Plan section 4 offers `kind="file"` "for a single code file", but that artifact would then be the *same* artifact as the one accepted file, collapsing two identities, and an archive has no single file at all. Ruling 2's member profile ("manifest + one repository + one file per accepted input + N history_event") is uniform, which is what CC8 has to validate. |
| The tree revision's `content_hash` / `raw_uri` are the accepted manifest's | Both fields are required `Text` and the tree has no raw object of its own. Its content *is* exactly its accepted manifest. The head SHA is the `provider_revision`, which is what puts it into generation identity (plan section 5), so two captures of one tree at two head SHAs are two generations — pinned by `test_two_captures_at_different_head_shas_are_different_generations`, and the reason CC4's finding 8 (equal `manifest.sha256` across head SHAs) does not lose the SHA. **CC8 must expect exactly this pair when it writes the `code` profile.** |
| Accepted artifacts carry `connector_id = provider_instance = None` | `generation_profiles.py:137-139` refuses a non-local accepted artifact outright, and `model.py:321` requires connector and provider instance together. Only the `KnowledgeObject` carries the provider key. |
| `file` objects exist only for files that produced at least one span | CD5 allows a `file` object with observations and no native row, but an object with **no** observation would be unreachable evidence. A file CC5 refused as `binary` or `empty` produces no span, so it produces no object either. Its exclusion is already recorded in CC4's `RepositoryCapture.exclusions` and belongs in `coverage_json`, which is CC9's. |
| `coverage_json` stays `"{}"` | Coverage is CC9's and is not in `Generation.identity_fields`. The store sets `derived_evidence_version: 1` itself the moment a `RetrievalView`, `DerivedRecord` or `DerivedDependency` evidence member is written (`generations.py:530-542`), so a rendered code passage acquires the derived capability `derivations.validate_view` needs without CC6 or CC8 asserting it. |
| Native rows are carried as canonical JSON (`NativeCodeRow.row_json`) | Keeps the bundle immutable and makes two runs of the same inputs compare equal (`test_the_same_inputs_twice_produce_a_byte_identical_bundle`). `row` rebuilds what `add_symbols` / `add_data_objects` take. `store.base.with_defaults` keeps unknown keys, so the `generation_id` this module adds survives row shaping. |
| The disjointness check is **per passage**, not per generation | Two overlapping line windows of one file legitimately cite the same bytes in two different spans, exactly as an overlapping prose chunk does; a generation-wide check would refuse every windowed file with `overlap_chars > 0`. Within one passage the originals are merged complete-line runs, so they cannot overlap — `_disjoint` proves it and `test_every_cited_original_line_is_covered_by_exactly_one_span_per_passage` pins it. |
| Observation temporal fields: `validity_kind="observed_snapshot"`, `temporal_basis="observed"`, `temporal_precision="instant"`, `recorded_from=observed_at`, `recorded_to=None`, no effective bounds | Plan section 9's symbol/data row. `TemporalRecord.intervals` refuses effective bounds outside `explicit_interval`, so a symbol snapshot cannot carry them. Commit observations, which *do* use `explicit_interval` and `temporal_basis="commit"`, are CC7's. |

## Fixture inventory (the two-file tree the suite uses)

`src/orders.py` (a module docstring, an import, a class with two methods, a module function) plus
`db/schema.sql` (`CREATE TABLE orders (id INT); SELECT id FROM orders;`), captured from
`https://git.example.com/acme/robots.git` at head `4f1d2c8…`:

| Record | Count |
| --- | --- |
| prepared chunks (kinds `header`, `symbol`, `data_object`) | 6, 0 refusals |
| `AcceptedCodeBinding` | 2 |
| `KnowledgeObject` (`repository` 1, `file` 2, `symbol` 5, `table` 1, `column` 1) | 10 |
| `ObjectObservation` (`declared` 1, `catalog_observed` 12, `syntax_observed` 7) | 20 |
| `EvidenceSpan` (1 `field` on the tree revision, 12 `file_lines`) | 13 |
| `RetrievalView` / `DerivedRecord` / `DerivedDependency` | 6 / 6 / 12 |
| `NativeCodeRow` (`Symbol` 5, `DataObject` 2) | 7 |
| `NativeBinding` | 7 |
| `GenerationMember` (tree, manifest, two files) | 4 |
| `GenerationEvidenceMember` | 57, equal to `len(bundle.records)` |
| `BoundCodePassage` (all 6 rendered) | 6 |
| `commit_chunks` | 0 |

All six passages require a view, which is CC5's finding 2 in practice: the complete-line closure
keeps the newline the passage text dropped.

## Results

All runs from `.worktrees/cc6` with `.venv/bin/python` (3.12.11, `mcp==2.1.1` pinned). Pure
binding: no store handle, no model client and no clock, so **no Ladybug or Neo4j run is applicable
to CD5** and none was made. Fake is the only backend this gate needs.

| Run | Command | Result | Log |
| --- | --- | --- | --- |
| Baseline before RED | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_input_binding.py tests/unit/test_prepared_code_chunks.py tests/unit/test_repo_capture.py tests/unit/test_knowledge_contracts.py tests/unit/test_layering.py -q -o addopts='' -W error` | 233 passed | `/tmp/hippo-cc6-baseline.log` |
| RED | `tests/unit/test_code_binding.py` | 2 failed, 44 errors, `ModuleNotFoundError: No module named 'hippo.knowledge.code_binding'` | `/tmp/hippo-cc6-red.log` |
| GREEN, CD5 command | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_binding.py tests/unit/test_managed_input_binding.py -q -o addopts='' -W error` | **82 passed** | `/tmp/hippo-cc6-cd5.log` |
| GREEN, layering and upstream | `tests/unit/test_layering.py test_import_order.py test_knowledge_contracts.py test_prepared_code_chunks.py test_repo_capture.py test_code_provenance.py` | 260 passed | `/tmp/hippo-cc6-green.log` |

Per file: `test_code_binding.py` 48 passed.

The CD5 CHECK line as the ledger spells it runs from `/Users/mascott/projects/hippo`; the command
above is byte-identical but was run from `.worktrees/cc6`, so the gate checker's own run passes only
once `wp/cc6` lands on `rag-it-all-tibs`. The ledger's CD5 line already names
`test_managed_input_binding.py`, so design review m1 needs nothing further here.

No `filterwarnings` marker and no command-line warning filter were needed: the new test module does
not import `fastapi.testclient`, so the sanctioned anyio exception does not arise. Plain `-W error`
throughout, including the subprocess that proves the no-ingest import.

Ruff, over both files changed and over this document:

```
.venv/bin/ruff check src/hippo/knowledge/code_binding.py tests/unit/test_code_binding.py
.venv/bin/ruff format --check src/hippo/knowledge/code_binding.py tests/unit/test_code_binding.py \
  ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc6.md
```

`All checks passed!` and `already formatted`.

## How each CD5 criterion is covered

| CD5 criterion | Test |
| --- | --- |
| spans, views, derived records and dependencies, objects, observations, native rows, bindings, revision members and evidence members form one closed inventory | `test_the_evidence_member_closure_is_exactly_the_records_produced`, `test_every_referenced_identity_resolves_inside_the_bundle`, `test_every_evidence_record_revision_is_a_selected_member`, and `CodeEvidenceBundle.__post_init__`'s four check passes on every construction |
| no duplicate | `test_a_bundle_with_a_duplicate_span_or_object_refuses` over the thirteen identity lists `_check_inventory` walks |
| no orphan *binding*, and a `repository` or `file` object with observations and no native row is not an orphan | `test_every_native_row_has_a_binding_and_every_binding_has_an_observation`, `test_a_repository_or_file_object_has_observations_and_no_native_row`, `test_a_bundle_whose_native_row_lost_its_binding_refuses` |
| native IDs equal `symbol_id`/`data_id` under the generation namespace | `test_native_ids_equal_the_generation_namespaced_ids`, and `_Inventory.bind` re-derives every ID and refuses a mismatch on every call |
| `symbol_key` carries the signature discriminator so overloads do not merge | `test_two_overloads_do_not_merge_into_one_knowledge_object` (two real C# overloads: one native ID, two canonical objects, one native row, two bindings), `test_a_symbol_object_is_keyed_by_repository_and_signature` |
| a shared canonical symbol observed by two sources keeps distinct per-source observations | `test_a_shared_canonical_symbol_from_two_sources_keeps_distinct_observations` |
| no `Assertion`, `AssertionVersion`, `AssertionSupport` or `SYNONYM` row | `test_no_assertion_synonym_or_community_record_is_produced`, which also pins the `record_kind` set and greps the module source |
| the materialiser holds no store handle, model client or clock | `test_the_module_holds_no_store_model_or_clock`, `test_the_module_imports_no_ingest_module`, `test_the_generation_is_staging_and_takes_the_injected_instant`, `test_a_naive_capture_instant_refuses` |
| exact original line ranges, real locators, never a synthetic whole-file span (plan section 4) | `test_every_cited_original_line_range_becomes_one_span_with_real_locators` reconstructs the whole expected span set independently from the prepared chunks |
| rendered views for generated text, bound to their originals | `test_a_passage_with_a_generated_segment_gets_a_view_over_its_originals`, `test_a_passage_that_is_exactly_its_source_lines_needs_no_view`, `test_changing_the_binding_rule_version_changes_every_view_identity` |
| commit passages pass through unbound (orchestrator ruling a) | `test_commit_chunks_pass_through_unbound_in_chunk_order` |
| rule versions fold into generation identity (ruling 10) | `test_the_configuration_records_the_two_rule_versions_under_one_reserved_key`, `test_a_changed_binding_rule_version_is_a_different_generation`, `test_a_caller_configuration_that_already_claims_the_reserved_key_refuses`, `test_a_chunk_rule_version_that_differs_from_the_pinned_one_refuses` |
| a bundle whose chunks reference an excluded file is refused | `test_a_chunk_naming_a_file_the_capture_excluded_refuses` (a decoded file that belongs to no accepted inventory), `test_a_capture_from_another_source_or_workspace_refuses`, `test_a_chunk_naming_a_symbol_the_code_graph_does_not_know_refuses` |

## What a reviewer must not read as proven

1. **This bundle is not yet sealable, by design.** Ruling 2 defers the `code` accepted-input profile
   to CC8. Until `generation_profiles.validate_generation_profile` and `generation_checksums`' 
   "Evidence outside raw manifest" rule accept a `repository` member, persisting this bundle and
   calling `bind_generation_embedding_profile` raises "Accepted original revision inventory
   differs". Everything **else** the seal checks was traced statically against
   `store/generations.py` and `store/knowledge.py` and holds: `_references` for
   `EvidenceSpan`, `ObjectObservation`, `RetrievalView`, `DerivedRecord` and `DerivedDependency`
   reaches only evidence kinds that are in the member closure ("Incomplete exact interpretation
   closure"); `_record_revisions` of every evidence record stays inside the member revisions; every
   native row has a binding and every binding's object has a selected observation with the same
   span; and `derivations.validate_view`'s anchor, profile, rule-version and fingerprint equalities
   are satisfied by construction because the view and its `DerivedRecord` come from one
   `view_fingerprint` call. **That tracing is reasoning, not a passing test.** CD7 is where it
   becomes evidence.
2. **The overload rule is a recorded defect, not a repair.** `codegraph.model.symbol_id` carries no
   signature, so two overloads in one file share one native ID. `_by_native_id` groups nodes by
   native ID and a passage naming that ID observes **every** node behind it, because
   `PreparedCodeChunk.symbol_id` cannot tell the overloads apart. The consequence is honest but
   coarse: `Move(int)`'s passage carries an observation for `Move(string)` too, and the native row
   kept is the first in canonical order, so the persisted `signature` and `doc` are one overload's.
   The alternative — matching each passage to the overload whose line range contains it — needs the
   analysis-to-original line translation CC5 already owns and was judged not worth a heuristic here.
   A reviewer who wants per-overload precision should rule on giving `codegraph.model.symbol_id` a
   signature discriminator, which is a `codegraph` change and a native-ID migration.
3. **The two-source test proves object sharing, not cross-source merge behaviour at read time.** It
   shows that one clone URL yields one repository object and one set of symbol objects across two
   `source_id`s, with disjoint observations and disjoint native IDs. Whether the projection then
   presents them as one subject is `projection.py`'s business and is CD9's.
4. **`test_the_module_imports_no_ingest_module` is a live subprocess check, not a grep.** It is the
   one test here that would catch a future deferred `import hippo.ingest...` inside a function,
   which `test_layering.py`'s regex would also catch. Both are green.

## Findings for CC7, CC8, CC9 and the reviewer

1. **CC8 owns the `code` accepted-input profile.** Expect exactly: one `kind="manifest"` artifact at
   `make_identity("artifact", [ws, source, "manifest", "accepted-inputs-v1"])` with
   `provider_revision=None`; one `kind="repository"` artifact whose revision has
   `content_hash = accepted.manifest.sha256`, `raw_uri = accepted.manifest.uri` and
   `provider_revision = <head SHA or None>`; one `kind="file"` artifact per `accepted.inputs` entry,
   unchanged from the prose rule; and N `kind="history_event"` artifacts from CC7. The
   "Evidence outside raw manifest" rule needs the same widening, because the repository span sits on
   the repository revision and CC7's commit views will sit on `history_event` revisions.
2. **CC9 must call `code_generation` first.** The order is capture → `code_generation` →
   `extract_code(..., node_namespace=generation_namespace(gen))` → whole-source resolve →
   `read_history` → `prepare_code_chunks` → `materialize_code_evidence`. Feeding a legacy
   (unnamespaced) `CodeGraph` refuses with "A native code ID does not match the generation
   namespace". `code_generation` uses `EXPECTED_CODE_CHUNK_RULE_VERSION` for its configuration and
   `materialize_code_evidence` refuses any other chunk rule version, so the two can never disagree.
3. **CC9 owns `AccessPolicy` and `policy_id`.** It rides on `CodeGenerationInputs` because a policy
   cannot be minted purely; every artifact and every span here carries it, including the repository
   field span.
4. **The `community` label has nowhere to go in this bundle.** Plan section 4 says the community
   label is "computed during preparation (`indexer.module_communities`) and written in the `Symbol`
   row before the seal", and `store/code.py:253` does have a `community` column — but
   `codegraph.model.Symbol.row()` has no such key and CC6 computes no communities. The bundle's
   `NativeCodeRow.row` therefore has no `community`, and `test_no_assertion_synonym_or_community_record_is_produced`
   pins that. CC8 or CC9 must merge the label into the row before writing, or the plan should drop
   the claim. Plan section 4's ban on a *post-seal* `set_symbol_communities` is unaffected.
5. **`extract_code` does not dedupe symbols.** `extract.py:205` is a bare
   `graph.symbols.extend(facts.symbols)`, so `facts.symbols` may hold two entries with one `id` (see
   item 2 above). Anything downstream that builds `{symbol.id: symbol}` silently drops one; CC7's
   `MODIFIES` binding is the next place that matters.
6. **A `prose`-kind code chunk is bound like any other file passage here.** CC5's finding 3 asks for
   a ruling on whether such a chunk is OpenIE-extracted. CC6 takes no position and produces **no**
   `ProseExtraction` and no `ExtractionInput` for any kind, because plan section 4 says a code
   generation records `openie: "skipped"` and `PreparedCodeChunk` carries no `extraction_segments`
   (CC5 finding 2). If CC9 rules that a `prose`-kind chunk *is* extracted, it must build the
   extraction input from `bundle.passages` itself; the span and view it needs are already there.
7. **`BoundCodePassage.native_row()` omits `content_kind`.** It returns the dense row minus the
   vector, matching `input_binding.BoundPassage.native_row()` field for field.
   `generations.py:1226-1277` does not read `content_kind`, but the managed schema has the column, so
   if CC8 wants code passages distinguishable from prose ones in the native table it should add
   `content_kind` at write time rather than expect it here.
8. **A bundle with no passages at all is constructible.** Every accepted file refusing (all binary or
   empty) yields a bundle with the tree span and one `declared` observation and nothing else. That
   is legal at this boundary; whether a source with no passage is an acceptable build is CC9's
   source-level decision, matching CC5's finding 10.
9. **`capture.kind` is recorded in `attributes_json`, not in identity.** The repository observation
   carries `capture_kind` and `head_revision`, and each file observation carries `capture_kind`, so
   a reader can tell a checkout's file from an archive member's without another lookup. Neither
   enters any record's `identity_fields` beyond the attributes hash that `ObjectObservation` already
   includes, so an archive and a checkout of the same bytes are honestly different observations.
10. **The repository object's identity is provisional, exactly as ruling 4 intends.** It is
    `repository_key(provider_instance, provider_repository_id)` from CC4's normalized clone path.
    Task 10's connector adds a provider alias rather than renaming evidence. Design review m7's
    point applies to symbols and is worth CC11's attention: a walker upgrade that changes a
    `qualname` or a signature mints a **new** symbol object and leaves the old one with its
    observations, which is the intended shared-canonical design but does silently fork symbol
    history.
