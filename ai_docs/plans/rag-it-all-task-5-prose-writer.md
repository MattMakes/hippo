# Task 5 managed plain-prose preparation and staged writer

Status: implemented and independently reviewed SPEC PASS / QUALITY PASS. The gate ledger records focused Fake/Ladybug evidence, including transaction-local authorization/suppression checks and controlled profile binding. Production runtime/coordinator activation remains separate; no production dispatch is authorized by this document.

**Goal:** Turn immutable prepared plain-file evidence into complete model outputs, then write and seal that exact inventory under a generation fence.

**Architecture:** Two small modules reuse existing HippoRAG preparation and schema5 provenance. Model preparation has no store dependency; the writer has no model dependency. The caller owns accepted raw inputs, captured configuration, live build authorization and eventual publication.

**Gates:** `ai_docs/gates/rag-it-all/task-5-prose-writer/GATES.md`.

**Tech stack:** Existing Python dataclasses, immutable knowledge models, NumPy preparation, Ollama adapters and Fake/Ladybug stores. No new package, table, service registry or production route.

**Wiring manifest:** `PreparedEvidence` → `prepare_plain_prose` → `PreparedProseIndex` → `write_staged_prose` → existing `generation_write` / `generation_checksums` / `seal_generation`. The coordinator later supplies the guarded models, accepted inputs and authority; it separately calls `publish_staged_generation`.

This narrows the approved input-provenance, derived-evidence and pipeline plans. Those plans' remaining code, rich-format, history, migration and profile activation gates still apply.

## Current seams and preservation requirements

| Existing seam | Required behavior |
| --- | --- |
| `hipporag/preparation.py:prepare_passage_vectors` | Exact supplied passage IDs/order/text; document-mode embeddings; detach its mutable rows/NumPy output immediately. |
| `extract_chunk_prose` / `_openie_text` | `None` uses the full chunk even when short; empty explicit input skips; nonempty explicit input requires 80 stripped characters. The helper's skipped empty `Extraction` placeholders are not successful inference. |
| `hipporag/openie.py:extract` | Real NER then triples, current prompts/schemas/token caps; raw NER names are hints, while normalized triple endpoints become graph entities. Any `.error` fails mandatory coverage. |
| `prepare_fact_payloads`, `hipporag/text.py:fact_text` | Current normalized names/triples, endpoint selection, ordering and exact embedding strings. Temporary legacy hash keys deduplicate computation only; no global Entity/Fact writes or existence lookups. |
| `knowledge/input_binding.py:PreparedEvidence` | Original text stays exact; views retain full original/title dependencies and independent retrieval IDs. The prepared DTO is provenance, not an access grant. |
| `ProseExtractionPayload` / `prose_fingerprint` | One successful typed result per exact input/profile; source-local projection owns facts/mentions/synonyms. Typed engineering assertions remain separate. |
| `generation_for_inputs` | Accepted artifacts/revisions and configuration determine generation identity before outputs exist. There is no `Generation.config` property. |
| `generation_write` / `seal_generation` | Each write is fenced. Store checksums prove internal closure, while this writer additionally proves the declared dense/inference inventory was fully produced. |

The initial scope accepts only the existing plain `PreparedChunk` contract: one original unit, no code definitions, `extract_text is None`. Unsupported code/rich/generated-origin preparation rejects before models. The three-valued gate is shared and tested against legacy fixtures, but this module does not broaden provenance support to accept those other chunk types.

## Concrete API and immutable values

All new dataclasses are frozen with slots. Collection fields become tuples of exact supported immutable types; dictionaries, NumPy arrays, mutable `Chunk`/`Extraction` objects and live callbacks are never retained in a prepared result. Row adapters return fresh containers.

`OpenIEProfile` contains `wire_model`, canonical resolved `model_digest`, `num_ctx`, `prompt_fingerprint`, `normalization_version`, `response_parser_version`, `ner_max_tokens=512`, `triples_max_tokens=2048`, `temperature=0.0`, and the captured thinking/capability policy. Its fingerprint commits a closed versioned descriptor. Prompt fingerprinting uses the current static prompt messages/demonstrations/frame and schemas with fixed sentinels, not input text. Rule versions identify the current cleanup, valid-triple and JSON-response parsing semantics. Values must match the shared implementation; arbitrary caller versions cannot relabel changed behavior.

This is a captured description, not a resolver or remote attestation. The actual guarded chat adapter must separately verify that these model/options semantics are used. A model tag by itself is insufficient. Existing `ProfiledEmbeddings.chat_json` guards the embedding identity and does not establish a pinned OpenIE LLM; it cannot silently satisfy this contract.

`PlainProseInputs` contains:

- `generation: Generation`, `evidence: PreparedEvidence`;
- `artifacts_and_revisions: tuple[tuple[Artifact, ArtifactRevision], ...]` for the complete accepted inventory, including a manifest revision when supplied by the coordinator;
- `configuration_json: str`, canonical JSON object accepted before generation creation;
- `embedding_profile: StoredEmbeddingProfile` and `extractor_profile: OpenIEProfile`.

The pair inventory is exact, immutable, unique by artifact/revision and scoped to the evidence workspace and generation source. Its revision IDs must equal `evidence.revision_members`, including accepted zero-text or manifest revisions. File bindings already passed raw metadata/provenance validation in the input materializer; this boundary does not reread or attest raw bytes. Extra accepted manifest revisions need explicit members supplied by the coordinator, never a guessed membership from a raw URI.

Validate configuration/profile agreement through reserved managed-prose configuration entries: `embedding_profile` holds the complete stored descriptor, `openie_profile` the complete extractor descriptor, and `prose` holds the preparation/rule version, `synonymy_threshold`, synonym rule version, `code='empty'`, `history='excluded'`, and an explicit empty-source policy. Other reader/capture settings remain in the same canonical object. No descriptor enters original ArtifactRevision metadata.

Reconstruct the expected generation with `generation_for_inputs(artifacts_and_revisions, workspace_id=evidence.workspace_id, source_id=generation.source_id, parent_id=generation.parent_id, parser_version=generation.parser_version, linker_version=generation.linker_version, embedding_profile=embedding_profile.fingerprint, configuration=json.loads(configuration_json), created_at=generation.created_at)`. Require matching identity and immutable fields, staging status and no publication time. The expected manifest hash must match; checking only the embedding fingerprint is insufficient. Store-owned coverage markers are excluded from this comparison because they may be added during writing.

`PreparedDensePassage` contains `passage: BoundPassage` and `embedding: tuple[float, ...]`; `.native_row()` adds a fresh embedding list to the existing exact passage row adapter. Reject wrong dimensions, bool/nonfinite/unrepresentable/zero vectors and values inconsistent with the captured normalization contract.

`ProseCoverage` contains ordered `dense_passage_ids`, expected inference groups `(input_kind, input_id, input_version, input_text_hash, extractor_profile, support_passage_ids)`, successful extraction IDs, explicit skipped input/reason pairs and `native='empty'`. It is derived from the accepted preparation, not trusted as an independently supplied count. The plain-only branch has no skipped entries. A successful empty payload has an extraction ID; a skipped input has none. Failure produces no `PreparedProseIndex`.

`PreparedProseIndex` contains `inputs: PlainProseInputs`, `dense: tuple[PreparedDensePassage, ...]`, `extractions: tuple[ProseExtraction, ...]`, the new inference `derived_records`, `derived_dependencies`, `evidence_members`, and `coverage: ProseCoverage`. The input evidence retains rendered-view lineage. Validate exact output inventories, all original/support dependencies and fingerprints in the constructor; a frozen wrapper around unchecked lists or omitted results is insufficient. No authorization, lease, model or store handle survives in this DTO.

```python
def prepare_plain_prose(
    inputs: PlainProseInputs,
    *,
    embeddings,
    chat,
    check,
    workers: int = 2,
    on_progress=None,
    should_stop=None,
) -> PreparedProseIndex: ...


def write_staged_prose(
    store,
    prepared: PreparedProseIndex,
    *,
    job_id: str,
    lease_owner: str,
    fencing_token: int,
    expected_authorization_epoch: int,
    expected_suppression_epoch: int,
    check,
    batch_size: int = 128,
) -> IndexManifest: ...
```

The embedding runtime exposes `.resolved.descriptor()`, `.validate()` and `.embed(..., kind='document')`; its descriptor must validate to exactly `inputs.embedding_profile`. Production uses the existing `ProfiledEmbeddings` with the scoped cache. The chat runtime exposes `.profile` equal to the captured `OpenIEProfile`, `.validate()` and `.chat_json(..., request_guard=...)`, with the request guard applied around every actual HTTP attempt/retry. Tests use explicit guarded fakes. No unguarded production fallback or no-op default `check` is supplied.

## Model preparation sequence

1. Validate all immutable inputs, generation/configuration reconstruction, explicit empty policy and runtime profile equality before any model call. `check()` is a caller-owned live build/source authorization and cancellation check; it may raise. It is not inferred from prepared provenance.
2. Use `prepare_passage_vectors` with exact bound passage IDs and fresh legacy Chunk copies. The model wrapper checks authorization and profile before dispatch and after return; validate every returned vector and detach to tuples. Zero passages require explicit authoritative-empty policy and no model call.
3. Classify the shared OpenIE gate independently of the helper's placeholders. Each wanted input must equal its immutable `ExtractionInput` text/hash/version and full original closure. Group identical `(input_kind, input_id, extractor_profile)` inputs only when text/version/closure agree, union their declared support passage IDs, and run one inference per group. This matches schema5's one-result-per-input requirement; repeated equal text at different original locations remains separate.
4. Invoke shared `extract_chunk_prose` for group representatives. Run the real `openie.extract` in tests so prompts, NER-to-triple hints and cleanup are exercised. Reject missing, extra, duplicate or errored results. `openie.extract` catches guard errors into `.error`, so recheck the guard and fail the whole preparation; never convert errors into successful empty payloads.
5. Use `prepare_fact_payloads` for normalized names/triples, then embed every needed entity name and `fact_text(subject, predicate, object)` under the captured document profile. Deduplicate within this build, not through selected or unselected global rows. NER-only names get no entity vectors. Preserve first-seen model input order; immutable payload canonicalization remains owned by schema5.
6. For each actual successful result, build the existing `ProseExtractionPayload`; an empty valid result produces an empty payload and still records inference. Legacy cleanup can retain an empty predicate, which schema5 rejects: fail with an input-specific mandatory-coverage diagnostic. Do not drop that fact or change schema semantics in this slice.
7. Construct inference `DerivedRecord(view_kind='projection')` and complete span dependencies from the input's original closure, then `ProseExtraction`, using `dependency_version` and `prose_fingerprint`. The extractor fingerprint identifies both `extractor_profile` and the model/processing version; embedding profile and payload hash are committed separately. Support is the exact grouped native passage inventory. Rendered input-view closure remains selected through `PreparedEvidence`.
8. Validate the complete detached result, then perform final runtime/profile/build checks before returning. Model failure or cancellation returns no prepared success and performs no writes.

A shared local failure latch permanently denies subsequent dispatch once preparation fails or closes. This is required because `extract_many` can return on cancellation while already-running requests finish in background. Their results are discarded; late calls cannot advance to another model phase. The latch does not abort bytes already sent. The caller keeps its build lease heartbeat active during outstanding work; checkpoint checks alone do not guarantee lease lifetime. Production activation must prove actual HTTP retry guards and heartbeat ownership, separately from the pure preparation tests.

Synonyms are not persisted here. Their source-local candidates are recomputed from authorized extraction vectors by the existing projection, using its cosine-normalized temporary matrix, meaningful-phrase gate and neighbor cap. Capture the threshold and rule identity in generation configuration; test the corresponding projection behavior. Cross-source synonyms and code candidates remain outside this plain-only increment.

## Fenced writer and sealing sequence

Precondition: Source, staging Generation, claimed MaintenanceJob, policies and the exact accepted Artifact/Revision records and GenerationMember inventory already exist. The coordinator installs the accepted manifest pair and calls `bind_generation_embedding_profile` under its fence before this writer. The writer requires controlled `verified_v1`, compares the local validator's descriptor/configuration fingerprint before mutation and again before sealing, and idempotently verifies/reuses revision members. The coordinator's fenced capture stage owns those initial writes and later publication. This module writes prepared evidence/lineage, passages and inferred prose only. It cannot bootstrap a legacy source by itself.

The public refresh wrapper requires no ambient transaction and rejects one before invoking any callback. Callback-free `_write_batches`, `_write_batch` and `_seal` form the reusable local core for a future atomic bootstrap transaction; the core uses the same local epoch/fence checks. No second writer implementation or public bootstrap API is introduced.

1. Validate the immutable prepared result. Outside a transaction call `check()`. Open an outer transaction, take the authorization lock before the source/generation fence, and compare authorization and suppression epochs against the explicit expected authority values. Inside `generation_write` compare persisted accepted Artifact/Revision contents and generation identity with `PlainProseInputs`. Do not accept a matching ID whose immutable content differs. Current source ownership/ACL is enforced by caller checks plus these local epoch guards; the store's fence alone does not manufacture audience authorization. Epochs belong to write authority, not generation identity.
2. In bounded fenced batches, write exact revision members, then original spans and their exact members. A rendering group writes its DerivedRecord, every dependency and corresponding exact members, its view/member, and the associated vectorized Passage only after their prerequisites exist. Deduplicate shared original/derived records by ID with equality checks. Batch size bounds complete groups, so one bounded prepared chunk's full dependency closure stays atomic even if larger than the nominal row count.
3. Write each inference derivation/dependency group and `ProseExtraction`/member together after all support passages exist. Use `validate_prose` and storage's normal exact-member validation; do not synthesize native bindings for prose passages or write global Entity/Fact/MENTIONS/STATES/SYNONYM rows. The only native rows are explicit generation-owned Passages; code native inventory is empty.
4. Before each batch and after leaving it call `check()`. Every batch and final transaction takes the authorization lock first and checks both expected epochs before writes and after writes, before commit. A change between external check and fence or during writes denies and rolls back that batch. No callback, model/profile HTTP request or cache lookup occurs inside a transaction. Store calls can use existing internal inventory readers, as the other knowledge services do, but filter exact generation before comparison. Fences are rechecked inside each `generation_write`; lost ownership stops without cleanup.
5. In the final fenced transaction compare complete persisted revision members, exact evidence members and record contents, dense passage IDs/bindings/vectors, successful prose input/profile/support mappings and payloads against the prepared inventory. Require no extra native code rows/bindings/relationships and no extra interpretation members. Missing, duplicate/conflicting or unrelated staged leftovers fail; do not silently overwrite or delete a failed attempt's outputs. Replaying this identical prepared result may reuse equal existing rows while staging; a different preparation requires coordinator-owned failed-build recovery.
6. Compute `generation_checksums`, build `IndexManifest(required_representations=('evidence', 'dense', 'native'), profile_fingerprint=inputs.embedding_profile.fingerprint, config_fingerprint=text_hash(inputs.configuration_json), checksums=..., ready=True)` and call `seal_generation` in that same final transaction. This closes the gap between inventory comparison and sealing. Return the manifest after the outer transaction commits and a final caller check.

The expected coverage descriptor is an immutable preparation value verified at this boundary; the seal commits the resulting exact evidence/dense/native contents. The present store API cannot attach arbitrary new coverage to a Generation after controlled derived membership stamps its marker. This writer does not bypass that restriction with `_write_knowledge`, fabricate a Generation configuration field, or claim that its transient coverage descriptor is separately stored. A later requirement to persist the full declared coverage descriptor needs an explicitly reviewed control-record contract. Missing mandatory inference is already rejected by this writer before sealing.

No `publish_staged_generation`, global embedding metadata update, graph-version bump, source-wide cleanup or source status replacement occurs here. Existing `seal_generation` performs its documented content-epoch update. G1 remains selected throughout preparation/writing/sealing. Any failed batch may leave invisible G2 staging rows; only the coordinator decides retry/cleanup under live authority. A final authorization failure after seal leaves an unpublished ready generation, never a returned publication receipt.

## Implementation tasks and ownership

### Task 1: Immutable inputs and model preparation

Gates: PW1, PW2, PW3. OWNS: `src/hippo/knowledge/prose_preparation.py`, `tests/unit/test_managed_prose_preparation.py`.

Write RED tests for profile/config/input tampering, actual OpenIE request semantics, exact successful coverage, empty predicate failure, grouping/support and nested immutability. Implement the small DTOs and shared-helper adapter; run PW1–PW3. Add failure-latch/cancellation tests that block an in-flight fake call and verify no later dispatch or prepared output escapes. Preserve the existing shared helper and legacy indexer files.

### Task 2: Fenced persistence and strict seal

Gates: PW4, PW5. OWNS: `src/hippo/knowledge/staged_prose.py`, `tests/unit/test_staged_prose_writer.py`.

Write RED strict-store tests starting from the real plain provenance/materializer fixture and claimed generation jobs. Implement dependency-aware bounded writes and exact final reconciliation, then seal. Inject failures between batches, acquire a competing fence, remove an expected inference, add an extra staged row and change a profile. Assert last-good G1 and legacy global rows/meta are unchanged. Explicitly publish only in test setup after writer completion to exercise projection/citations and secondary-input denial. Repeat persistence/reopen cases on Ladybug; root coordinates Neo4j later.

### Task 3: Integration proof and review

Gates: PW6. OWNS: this plan and its ledger only.

Run the focused new tests plus existing shared preparation, OpenIE, materializer and derived-store regressions with warnings as errors. Check Ruff and formatting, including Markdown Python fences. Obtain independent SPEC/QUALITY review and record evidence. Root owns commits and future integration.

## Plan verification checklist

- Verify this contract against the approved parent plans before implementation; recheck the ledger and final integration after implementation.
- Accepted input identity/configuration is reconstructed through the existing API; stored descriptors are validated with the existing pure validator.
- Actual shared OpenIE semantics, including its skip/error distinctions and strict empty-predicate limitation, have dedicated tests.
- Original-only IDs/text and legacy Chunk/indexer behavior stay unchanged; generated retrieval text never becomes original evidence.
- Model callbacks have no transaction access through these modules; guarded adapter and lease coordinator activation remain explicit blockers to production dispatch.
- Writer dependency order, complete inventory, stale-fence behavior, strict sealing and G1 isolation run on Fake and Ladybug before review.
- No new schema, controlled-marker mutation, automatic publish, cleanup, generic framework or fallback authorization is introduced.
