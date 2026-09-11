# Task 5 staged indexing integration contract

Status: proposed production integration contract for root review; no implementation or gate completion is claimed. This complements `rag-it-all-task-5-storage.md` and `docs/rag_it_all.md` Task 5. Existing legacy sources remain on their current path until the parity gates below pass. Task 5A historical interpretation/closure and Task 9 scheduling remain separate work.

## Decision

Keep the existing readers, chunker, OpenIE, code extractor and HippoRAG Retriever. Separate their computation from persistence, then add a managed coordinator that writes a complete source generation under the existing fenced store APIs. A managed query must reconstruct prose facts and code relations from immutable, explicitly selected evidence; feeding ordinary `index_source()` writes into the current managed projection is insufficient.

The three practical alternatives are:

1. **Recommended: shared preparation with separate legacy and staged writers.** Preserve extraction/ranking semantics while making generation ownership, original evidence and publication explicit. This requires the original/derived text and prose-projection contracts below.
2. **Only wrap the current store in a staging adapter.** Smaller superficially, but `index_source()` reads global entity/code vectors, publishes global metadata and writes synthesized chunks. An adapter cannot establish missing original provenance or restore the facts/relations deliberately omitted by managed projection. Reject this as the production contract.
3. **Replace ingestion and retrieval together.** Unnecessary for Task 5 and makes fidelity harder to assess. Defer hybrid retrieval and generalized connector orchestration to their planned tasks.

## Current code and concrete gaps

| Existing seam | Current behavior | Required change |
| --- | --- | --- |
| `ingest/pipeline.py:run_indexing`, `_prepare_reindex`, `_clear_passages` | Failure/reindex deletes source-wide passages; repo refresh deletes its checkout | Dispatch managed mode before any destructive helper; retain active generation and immutable raw inputs |
| `pipeline.py:_read_chunk_index`, `_read_history` | Extractor/history called without generation namespace or syntax cache; settings read at several stages | Capture inputs/config once, then pass namespace, settings and cache explicitly |
| `hipporag/indexer.py:index_source` | Embeds and writes passages, code, global entities/facts/synonyms; sets global embedding metadata and bumps graph version | Separate preparation from persistence/publication; no model calls in a managed write transaction |
| `indexer.py:find_synonyms` | Searches all stored entity/code embeddings | Managed candidate set belongs to the accepted generation/profile; cross-source links require a separate compatible link contract |
| `ingest/readers.py:Document`, `ingest/chunker.py:Chunk` | Neither carries a durable revision/span binding; generated code placeholders and commit `Touched:` text are ordinary chunk text | Preserve source locators during reading/chunking and distinguish original spans from rendered views |
| `knowledge/projection.py:project_managed_graph` | Original span passages and typed supported relations; explicitly empty OpenIE fact list | Add an explicitly inferred prose compatibility lane; retain typed assertions outside the legacy fact budget |
| `knowledge/predicates.py` | Does not declare native `INVOKES`, `IMPORTS`, `CONTAINS`, `MODIFIES`, `PRECEDES` vocabulary | Declare the valid parser-observed relation contracts and project them with their existing native direction/weight semantics |
| `knowledge/embedding_cache.py` | Strict cache primitive exists, but no production caller resolves its profile | Add model identity/profile resolution and a captured embedding adapter |
| `context.py:_build_managed_graph` | Compares generation/profile strings with `ollama.embed_model`, currently a model tag | Resolve an explicit retrieval profile identity without overloading the model name sent to Ollama |

`store/generations.py:_validate_managed_native` currently requires `Passage.text == EvidenceSpan.text`. `projection.py:_safe_vectors` independently verifies that equality. These are real invariants, not obstacles to bypass with a fabricated EvidenceSpan. Likewise, `DerivedRecord` currently holds identity/dependency metadata, not an arbitrary payload or vector field; implementation must not assume such fields already exist.

## Service and file seams

Use small immutable input/result types in `knowledge/lifecycle.py` or a focused `knowledge/indexing.py`; keep orchestration in `ingest/pipeline.py` and the managed service. Proposed APIs:

```python
@dataclass(frozen=True)
class BuildInputs:
    source_id: str
    workspace_id: str
    expected_parent_id: str | None
    expected_suppression_epoch: int
    artifacts_and_revisions: tuple
    documents: tuple
    configuration: Mapping
    embedding_profile: EmbeddingProfile
    extraction_profile: str


def prepare_index(
    inputs, model, *, syntax_cache, embedding_cache, should_stop, on_progress
) -> PreparedIndex: ...


def write_generation(store, generation, prepared, *, authority) -> IndexManifest: ...


def rebuild_managed_source(ctx, source_id, *, should_stop) -> str: ...
```

`PreparedIndex` contains ordinary chunks/vectors/extractions/code plus exact original span bindings, rendered views, canonical observations and supported relations. It is bounded by the current text/chunk/code limits. It contains no live store handles or authorization grant. Factor existing indexer stages into shared helpers rather than copy the whole indexer. Preserve `index_source(store, ollama, source_id, chunks, ...)` and legacy IDs/default side effects for existing callers; its legacy writer consumes those same helpers. The staged writer never calls the legacy publication tail or source-wide cleanup.

The coordinator sequence is:

1. Read logical source, workspace, active parent, suppression epoch and validated settings/configuration. Capture model identity before preparation. Fetch/read raw input into a build-specific checkout/staging directory; do not remove the prior checkout/blob. Materialize a stable accepted-input inventory, including repo revision and commit-history inputs.
2. Construct Artifacts/revisions and `generation_for_inputs(...)`; configuration includes reader/chunker versions, parser/runtime profile, resolver version, OpenIE model/prompt/cleaning profile, history options and synonym threshold. Output vectors/extractions/checksums never enter the generation input hash.
3. For an already managed source, persist the staging Generation and claim its `MaintenanceJob` with `claim_generation_build`. Capture the returned job ID, owner and fencing token. Preparation and model requests happen outside database transactions. A lease guard renews while long model work is outstanding and stops on lost ownership; a checkpoint-only heartbeat is insufficient when one request can outlast a lease.
4. Extract with `extract_code(..., node_namespace=generation_namespace(gen), syntax_cache=...)`; pass the same namespace to `read_history`. Cached syntax is rematerialized and resolution runs over the entire accepted source every time. Compute communities before persisting native rows.
5. Persist bounded batches inside `store.generation_write(gen.id, **authority)`. Each batch rechecks source/lease/fence and writes its evidence/native payload together. Include exact `GenerationMember`, `GenerationEvidenceMember` and `NativeBinding` closure. Complete support groups are written before sealing. Extractions explicitly skipped by policy are distinct from extraction failures.
6. Verify declared chunk/view coverage, original/view provenance and completeness against `PreparedIndex`; store-level coverage alone is intentionally weaker than this inventory check. Compute `generation_checksums`, create mandatory `evidence`, `dense`, `native` manifest, and call `seal_generation`. Empty code is valid for a prose source; silently absent requested prose extraction or required parser output is not equivalent to a complete representation.
7. Call `publish_staged_generation` with captured parent and suppression epoch. Its transaction owns pointer change, parent retirement, graph/content version, lease completion and receipt. A retry consults the receipt; it must not create a second publication.
8. On pre-publication failure/cancellation, discard only the owned staging generation when authority is still valid. If the fence was lost, leave cleanup to the current owner/recovery rather than attempting stale cleanup. Keep G1's pointer, vectors, blobs and serving status. Record refresh failure on the build; preserve the source's ready state when it has active content. A post-publication UI/status error must not discard the committed generation.

## Original evidence and rendered retrieval text

Add a provenance-bearing chunk result alongside the existing `Chunk`, with an artifact revision, original locator(s), exact source slice(s), and rendered retrieval text. Do not infer locators by parsing a display title. Readers must supply stable source-relative file paths, page/block coordinates or provider field identifiers before transformations. Preserve original bytes in immutable blobs and record the decoding/extraction profile; PDF/DOCX/HTML extracted text remains traceable to that original artifact and its actual supported locator precision.

An `EvidenceSpan` always contains the original slice at its declared locator. A code module with placeholder lines, a synthesized signature card, or a commit message plus generated touched-symbol names is a `RetrievalView` anchored to original span(s), with `DerivedRecord`/`DerivedDependency` lineage. For a view assembled from several spans, an anchor span is not the entire proof: record and authorize every input dependency. Commit originals come from accepted commit metadata/message/diff records, not from the rendered `Touched:` line.

Keep the current original-only native Passage binding valid. Introduce an explicit optional rendered-view binding for managed dense rows, including view ID, profile and the existing revision/span/generation IDs. Extend the passage identity helper with a view discriminator only for this new form; existing original-only IDs remain unchanged. Storage verifies that the view is an exact generation member, its original dependencies are inside the generation, its derivation/profile matches, and row text/vector input exactly matches the view. Seal its binding and payload. This needs an actual native schema/row-shape change with the next applicable migration; it is not a loose extra dict field.

Projection must then verify two distinct cases: an original vector bound to exact span text, or a rendered vector bound to the selected immutable RetrievalView and all authorized original inputs. Citation/answer evidence remains original text and locators. The rendered view may drive retrieval and explicitly labeled code context, but must never become an original quotation merely by occupying `Passage.text`. Keep the mapping available through evidence packing and the current `passage_by_id` consumers. Tests must prove both retrieved view identity and returned original evidence, including one original span with several views.

## Preserve prose and code retrieval explicitly

### Prose

Run the existing OpenIE NER/triple extraction and cleanup rules on the same intended input as today. Preserve the three-valued `extract_text` gate and `MIN_OPENIE_DOC_CHARS`; code bodies do not become OpenIE input. Arbitrary OpenIE predicate strings are model-inferred compatibility facts, not registered engineering assertions.

Persist a closed, versioned **prose extraction projection record** (proposed `ProseExtraction`) with source generation, exact input span/view dependencies, extractor profile, original inference text hash, normalized entity names/triples and the embedding profile/vectors needed for the legacy fact channel. Include the output payload hash in its immutable identity. This is a new typed payload contract and exact-member kind: add validation, storage registration, schema migration, sealing/checksum/collection coverage and authorized read support together. Do not hide JSON inside `RetrievalView.text`, infer a proof from global `Fact` endpoints, or pretend the metadata-only `DerivedRecord` already stores this payload.

For each authorized selected extraction, the compatibility projection constructs source-local entity/fact IDs, fact embeddings, mentions and passage support using the original-evidence mapping. Recompute shared counts and synonym candidates from authorized selected contributions. A hidden or staging extraction must not change visible labels, fact counts, vector dimensions or synonym weights. Deduplicate equivalent triples within the source as the current indexer does; cross-source equality is not a grant to merge their provenance. Preserve the current Retriever, fact filter and graph weighting for this lane. Typed AssertionVersions continue to use their separate supported relation lane and do not compete for OpenIE fact-filter slots.

New managed prose with an OpenIE failure must either fail mandatory prose coverage or explicitly use a documented degraded representation policy captured in its manifest/configuration. For the initial parity gate, fail the refresh and retain G1; merely having dense passages is insufficient to claim a successful equivalent HippoRAG rebuild. Existing legacy error behavior is unchanged.

### Code

Create stable source-local KnowledgeObjects and syntax-observed ObjectObservations from extracted code; attach every native Symbol/DataObject/Commit to authorized original evidence through `NativeBinding`. Store display fields and native code kinds on observations so existing `_code_node` reconstruction remains authoritative. Source-local canonical object identity survives refresh; generation namespaces isolate physical native rows, including commits and resolver-created data objects.

Declare the observed code predicates needed for native parity in the registry with precise endpoint kinds and support rules. Create AssertionVersion/AssertionSupport rows from the extractor's actual locations/confidence; do not invent a semantic predicate by mapping every edge to `DEPENDS_ON`. Preserve native direction, specificity kinds, `code_structural_scale`, non-PPR `PRECEDES`, definition/refers/modifies attachments and community behavior through the projection adapter. Unknown or unproven mappings fail that representation's coverage gate. Multi-span support remains AND within a derivation group and OR across alternatives.

Source-local synonyms can remain explicitly derived compatibility links with full input/profile lineage. Cross-source link refresh is deferred to immutable LinkGeneration work; record this coverage boundary and keep existing legacy cross-source behavior until its managed replacement passes the relevant parity cases.

## Cache and profile wiring

Use `<data_dir>/cache/syntax-v1` and `<data_dir>/cache/embeddings-v1` as disposable cache roots owned by AppContext/configuration. Raw artifact blobs and retained evidence never live under those roots. Unavailable/corrupt entries are misses; a cache hit never substitutes for generation membership or authorization. Preserve existing limits and derive retention/quota separately from evidence collection.

The model adapter must expose separate **wire model identifier** and **resolved retrieval profile fingerprint**. Build `EmbeddingProfile` from resolved model digest, dimension, exact query/document prefix rule version, normalization and request options. Obtain dimension outside write transactions. Include the OpenIE model/prompt/cleanup identity separately in the generation configuration. `Ollama.installed_models()` currently drops `/api/tags` digest metadata; add a dedicated resolver rather than using returned names as immutable identity. The independent digest/alias adapter design must establish the model actually used for requests; a tag string or a one-time metadata read cannot prove that.

Use `cached_embed` for passage/view, entity/fact and code-name document inputs through one build-scoped adapter, retaining exact pre-prefix text and `kind`. Prefixing/normalization remain owned by Ollama. Query embedding uses the same captured profile's query mode. Detect observable drift before/after model calls and before sealing/publication/release. If identity cannot be resolved, legacy operation may explicitly bypass cache reuse; strict managed publication must not label unverified vectors with a trusted profile. No cache result is accepted under a fabricated digest.

Pass the resolved profile consistently through Generation, Passage/view binding, IndexManifest, snapshot acquisition and projection validation. During transition retain the explicit trusted legacy/old-managed profile path; do not silently reinterpret a model tag as a digest profile. A model-profile change builds compatible generations without deleting G1. Selecting a new query profile before compatible source generations exist must return an explicit unavailable/profile mismatch outcome, not silently drop sources or let majority dimensions choose a corpus.

## Production migration and lifecycle dispatch

Keep legacy IDs and legacy source behavior as the default while parity is incomplete. New managed sources require an explicit service/configuration choice; do not make every existing upload managed solely because the storage columns exist. Existing v3 managed fixtures retain their documented trusted compatibility path until rebuilt with exact closure.

For existing legacy sources the simplest safe conversion is a **prepared atomic bootstrap**: compute a complete canonical first generation from retained source input outside database transactions while the legacy graph remains serving. Then, under one source transaction and source/input/permission checks, establish managed mode, persist the prepared bootstrap, claim/write/seal/publish it, and invalidate the old legacy authorization view. There are no external/model calls inside that transaction. Rollback leaves the source legacy and usable. This avoids the current trap where inserting the first Artifact/Generation immediately marks the source managed and causes legacy rows to disappear before any active generation exists. The initial transaction may be larger than refresh batches; accept that bounded tradeoff for the first implementation. A later shadow-bootstrap protocol would require an explicit additional storage state.

Do not delete legacy rows or source files as part of conversion. Cleanup follows successful publication plus reachability checks. Once bootstrapped, ordinary managed reindex stages G2 beside G1 using the normal bounded batch workflow. `reindex_all` dispatches each source independently; it must not clear managed sources first. A managed delete uses the suppression/tombstone/fencing service, then retention-aware collection. `delete_source`, `_sweep_if_deleted` and failure handlers cannot call `rmtree(source_dir)` for managed data. Build temporary directories are cleaned only after ownership checks; content-addressed blob deletion requires collection's exact unreachable set.

## Remaining query and saved-result lifetimes

The current ask/search HTTP, CLI, MCP, HTML ask and graph light-up paths use one QuerySession through materialized response construction, capture effective settings, and release their active reference. Preserve those contracts.

Complete the following before claiming all Task 5 consumers are integrated:

- `evals/runner.py:run_question` currently calls `search` and `answer_from_trace` in separate sessions, and its validation calls `evaluation.graph()` again. Give one question a session through retrieval, answer, grading, metrics and result persistence. Refresh only current permission proof, not the selected generation. External question/gold-answer ownership checks remain mandatory.
- `analysis/simulate.py:simulate`, analyze routes, graph detail/code tools and status/render paths still have direct `query_access`/`graph_for` consumers. Use explicit owned or borrowed sessions and deterministic release. A simulation owns one graph plus declared baseline/override settings; do not acquire a fresh graph during rendering/comparison.
- Saved evaluations/answers need snapshot IDs on their saved record and an unreleased `saved` SnapshotReference for every selected workspace snapshot, created atomically with the result before active references close. Deletion releases those exact references; current access still gates later reads. Do not infer a retained snapshot from only `trace.graph_version` or evidence fingerprint.
- `web/adhoc.py:remember_adhoc` stores a trace/answer without snapshot retention. Either retain it for the cache entry lifetime and release on expiry/eviction, or keep its existing explicitly current-only reconstruction semantics. Do not present it as durable historical replay. Ordinary legacy-only ephemeral results cannot become reconstructible history by saving an empty managed snapshot tuple.
- Request leases must cover long model calls. The build and query guards need bounded renewal during outstanding calls or a documented hard request duration shorter than the lease; expired references cannot be revived after the call. Keep revocation checks before dispatch and before releasing any output regardless of renewal.

## Implementation order and acceptance gates

Implement the missing contracts before switching production defaults. The commands below name proposed tests where absent; evidence is pending.

| Gate | CHECK | EXPECT |
| --- | --- | --- |
| P1 Original/derived binding | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_inputs.py tests/unit/test_managed_chunk_provenance.py` | File/code/commit/prose locators recover original text; placeholders/touched lines are derived; bindings and profile drift reject |
| P2 Staged native writer | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_staged_indexer.py tests/unit/test_generation_graph_loader.py` | Same-name G1/G2 nodes and every endpoint isolated; no global publish/metadata side effects; staged dimensions never reach G1 |
| P3 Prose/code parity | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_hipporag_parity.py tests/unit/test_indexer.py tests/unit/test_graph_index.py` | Fixture rankings/fact budgets, original citations, code paths and scale-zero behavior match declared legacy semantics; typed assertions stay outside inferred fact slots |
| P4 Lifecycle and conversion | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_pipeline.py tests/unit/test_ingest_concurrency.py` | Failure, cancellation, lost fence, restart, source delete and duplicate publish retain last good generation; bootstrap rollback preserves legacy serving; bulk dispatch does not clear managed rows |
| P5 Reuse/profile | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_syntax_cache.py tests/unit/test_embedding_cache.py tests/unit/test_managed_profile_wiring.py` | Unchanged syntax and exact embeddings reused; namespace rematerialization and whole-source resolution still run; model/prefix/options changes miss/reject correctly |
| P6 Query/result lifetime | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_query_session.py tests/unit/test_query_snapshots.py tests/unit/test_eval_snapshot_lifetime.py tests/unit/test_saved_snapshot_retention.py` | One generation set through model/render/save; pure publish allowed, ACL loss denied; error/eviction closes refs; saved retention survives request exit/reopen |
| P7 Real persistence | Repeat P1–P6 persistence cases with `HIPPO_TEST_STORE=ladybug` and later the dedicated CI Neo4j service | Seals, schema/row shapes, atomic bootstrap/publication, retention and reopen behavior agree with FakeStore; no app-data access during verification |

Suggested ownership: one agent for provenance/chunker and rendered-view bindings; one for shared preparation/staged indexer and inferred prose projection; one for profile/cache adapter; root for lifecycle dispatch/bootstrap and query/saved-result integration. Storage/model migrations are coordinated with the storage owner before new record/binding types are implemented. Native parser predicate additions and projection parity are reviewed together. None of these gates is satisfied merely by the existing storage/snapshot unit suites.
