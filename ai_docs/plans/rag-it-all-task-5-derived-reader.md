# Task 5 authorized derived retrieval and original citations

Status: reader integration proposal for root review. No implementation or acceptance gate completion is claimed. This implements the reader side of the approved [derived-evidence contract](rag-it-all-task-5-derived-evidence.md) and complements the [pipeline](rag-it-all-task-5-pipeline.md) and [embedding profile](rag-it-all-task-5-embedding-profile.md) designs.

## Decision

Keep the retrieved Passage and its original evidence as separate objects. A rendered Passage remains a distinct dense candidate with its exact RetrievalView text and vector. A citation resolves to immutable EvidenceSpan text and its real locator, including every contributing original span. The graph owns this mapping for its pinned generation; no consumer reconstructs lineage by reading whichever generation is current later.

Add the smallest three reader primitives: complete derived authorization in EvidenceAccess, provenance-aware managed projection, and one original-citation resolver shared by answer and presentation consumers. Reuse the existing HippoRAG retrieval stages and GraphIndex. Project authorized ProseExtraction payloads into the existing inferred Entity/Fact channel; keep typed engineering assertions separate. The strict schema 4 and legacy branches retain their existing identities and behavior.

## Actual seams and constraints

`knowledge/access.py:_interpretation_inventory` currently selects EvidenceSpan, ObjectObservation, AssertionVersion and AssertionSupport from exact generations. `EvidenceAccess.build` proves original grants, complete support groups and native bindings, and `validate_current` recomputes the audience proof. Adding a model record alone would therefore leave it outside the interpretation inventory.

`knowledge/projection.py:_safe_vectors` requires native Passage text to equal its original span text and indexes vectors by span ID. `project_managed_graph` emits span-ID passages and an empty Fact lane. Its observation filter also currently depends on the dense span inventory. A derived implementation must separate authorized originals from retrieval candidates, or it will discard unembedded secondary originals and their provenance. `_assemble` constructs statistics, matrices and graph versions; `compose_graphs` copies authorized lanes.

`hipporag/graph_index.py:passage_by_id` returns retrieval text. `scoped` reconstructs graphs and support counts. `ask.py:_answer_from_trace`, MCP search/ask, HTML answer rendering, graph details and question generation currently consume that retrieval text directly. `knowledge/replay.py:view_fingerprint` hashes the current graph representation; reconstruction correctly reads labels from the live graph rather than trusting saved labels. These are explicit propagation seams, not reasons to replace original evidence with rendered text.

## Shared structural contract

The storage owner has agreed these exact APIs in `knowledge/derivations.py`:

```python
validate_view(store, generation_id, view) -> DerivationClosure
validate_prose(store, generation_id, extraction) -> DerivationClosure
```

`DerivationClosure` is frozen and contains frozensets named `span_ids`, `revision_ids`, `derived_record_ids`, `dependency_ids`, `view_ids`, `binding_ids`, and `support_passage_ids`. It proves exact membership, complete dependency groups, ready derivations, source/workspace/generation consistency, profiles and hashes. Prose closure includes its input view and every support passage's view closure. It provides provenance, never ACL authority.

Use the shared `derived_capability(generation)` check before enabling these new inventories. Controlled schema 5 writes stamp `Generation.coverage_json['derived_evidence_version']=1`; callers cannot preseed, remove or downgrade it. Historical generations without the marker retain their old interpretation even if they contain selected presentation views. Unknown capability versions fail closed. Capable generations validate every selected view, including views without native dense rows.

Use the owner's `dependency_version`, `view_fingerprint` and `prose_fingerprint` recipes for construction and validation. Readers must not reproduce these hash recipes independently. The helper receives the full selected inventory through the store, before authorization removes children; otherwise an incomplete group could incorrectly become complete after filtering. Structural failure fails the managed snapshot with a typed projection/validation error. An ordinary permission denial removes the entire affected view/extraction. Neither path falls back to untagged native data.

One projection call may memoize validated closures by generation plus immutable record ID under its existing read/snapshot boundary. Do not introduce a long-lived closure cache keyed only by DerivedRecord ID: complete child enumeration and exact generation membership are part of the proof. No network or model call belongs in these helpers.

## Authorization API and ordering

Extend the existing frozen `AuthorizedEvidence` with `derived_record_ids`, `derived_dependency_ids`, `retrieval_view_ids` and `prose_extraction_ids`, each defaulting to an empty frozenset. Extend `_interpretation_inventory` to select DerivedRecord, DerivedDependency, RetrievalView and ProseExtraction from exact membership. Empty exact selection stays empty. Schema 4 compatibility does not invent new derived capabilities from old unbound views or revision-only membership.

After the existing original span/revision and native-binding grants are established:

1. Validate every selected dense view and extraction using the shared structural helper. Enumerate full dependency groups even when a secondary input will be denied.
2. Require every closure span, revision and binding to be authorized in this selected source generation. Require all intermediate views and derivations to be selected and ready. The existing source/workspace, provider freshness, historical/current applicability and policy deadlines continue to intersect.
3. Apply active `Suppression(target_kind='derived_record')` to every derivation in the closure. A suppressed input view denies its extraction. A hidden span in a support passage also denies the extraction even when that span was not sent to OpenIE.
4. Publish only complete authorized view/extraction IDs. Derivation and dependency sets contain only lineage supporting authorized outputs; they never imply that an otherwise unselected output is allowed.
5. Include the new sets in proof hashing for the new capability. Preserve the original proof hash recipe when all four sets are empty, so opening a schema 4 graph after migration does not invalidate a previously compatible proof solely because fields were added.

The existing graph authorization callback revalidates this proof before model dispatch and final response release. Pinned G1 remains valid after pure G2 publication; a current ACL or suppression change still denies the affected request. A lease preserves availability, not permission. There is no special derived-record grant that overrides an original input denial.

## Minimal immutable graph metadata

Add small frozen reader DTOs, preferably in a dependency-light module imported by GraphIndex and `knowledge/citations.py`. They are reader values, not additional schema records:

```python
RetrievalEvidence(
    passage_id: str,
    generation_id: str,
    retrieval_view_id: str | None,
    original_span_ids: tuple[str, ...],
)

OriginalCitation(
    span_id: str,
    revision_id: str,
    artifact_id: str,
    source_id: str,
    title: str,
    locator_kind: str,
    locator_json: str,
    text: str,
    text_hash: str,
)
```

Store canonical locator JSON as a string rather than retaining mutable dictionaries. Original text comes only from the selected immutable EvidenceSpan, and title comes from authorized source/locator or original observation information. A generated view title is not original evidence. Order original IDs deterministically by source/revision/locator/span identity; ordering never chooses a privileged anchor and discards secondary inputs.

GraphIndex gains default-empty immutable tuples of these entries, with lookup helpers or rebuilt indexes. Frozen tuples avoid `MappingProxyType`/`deepcopy` incompatibility in current graph copying. Do not add fields to the existing Passage dataclass merely to transport provenance: `asdict(Passage)` already participates in old fingerprints. Enforce uniqueness and mapping completeness at graph assembly. The originals map may contain spans without dense vectors or graph vertices.

For new inferred prose, add a frozen provenance tuple per projected Fact containing generation, extraction IDs and explicit support passage IDs. This is useful for replay/explanation and makes graph fingerprints commit the actual inferred inputs, including successful outputs that happen to produce the same visible triple. It does not become a permission token. Empty successful extraction records remain in the audience proof/captured inventory even though they produce no Fact.

`GraphIndex.scoped` subsets retrieval metadata by retained passage IDs and keeps the union of their complete original closures. It must not truncate a view to whichever originals happen to remain as dense vertices. It likewise subsets prose provenance by surviving support. `_assemble`, `compose_graphs`, copied/simulated graphs and graph-version replacement must preserve the frozen metadata. Conflicting original records under the same span ID fail composition. Composition still rejects colliding projected node IDs and does not infer cross-source relationships.

Graph assembly/versioning and `view_fingerprint` include a versioned provenance extension only when the new derived/prose capability contributes metadata. Keep the exact old payload shape on original-only schema 4 and legacy graphs. The extension commits original text/hash/locators and retrieval-to-original relationships as well as view/extraction IDs. It is insufficient to hash rendered text alone.

## Managed projection

Replace `_safe_vectors` with a helper returning validated retrieval entries and a physical-to-projected passage-ID map. An entry carries its projected Passage, vector and RetrievalEvidence; it is built from persisted bindings and the already generation-filtered cached native graph. Compare persisted and cached text/vector/profile exactly after the shared finite float32 validation.

| Native row | Projected retrieval ID | Text/vector contract | Citation closure |
| --- | --- | --- | --- |
| Original-only, no retrieval_view_id | Existing EvidenceSpan ID | Native text equals span text; equal duplicate vectors collapse as today | That original span |
| New strict rendered row | View-aware native Passage ID | Native text equals selected RetrievalView text; captured profile and dimension agree | Complete validated view original-span set |
| Legacy row | Existing native Passage ID | Existing legacy loader behavior | Existing legacy text/ID; do not invent an EvidenceSpan or locator |

The nullable view field must reach `_passage_bindings` and the generation-aware loader before GraphIndex matrix creation. Multiple views of one anchor retain different IDs and vectors. Selected G1 cannot inspect staging G2 dimensions, prose outputs or native aggregates. A selected rendered row with missing or unauthorized view closure cannot become an original row by dropping its view field.

Keep `authorized_originals` separate from `retrieval_entries`. Build immutable citation records from all required original inputs, including secondary spans with no vectors. Build canonical typed code objects and assertions using authorized observations/support groups as today. Attach a code object to an original retrieval candidate through its authorized observation; attach it to a rendered candidate only when the explicit NativeBinding dependency establishes that candidate's defining object and anchor. Merely appearing as a secondary view input does not imply DEFINED_IN or REFERS_TO. Do not use raw global native edges as an authority shortcut. If the prepared writer cannot establish this association using approved bindings and assertions, leave the edge absent and fail the applicable parity gate rather than guess.

Preserve endpoint filtering for every code/synonym/tuned/defines/refers/modifies/precedes relation. Recompute code indegrees and communities from the final authorized graph. Typed AssertionVersion/AssertionSupport relations continue to carry their complete proof and do not consume the OpenIE Fact budget.

## Inferred prose projection into HippoRAG

For each authorized ProseExtraction, use its closed payload and exact declared support_passage_ids. Translate physical native IDs through the projection map; all supporting retrieval candidates must exist and have their full authorized original closure. Do not query global legacy Entity/Fact rows to supplement managed results.

Use versioned source-local identity helpers for normalized entity names and triples, for example a domain-separated identity over `(source_id, 'inferred-prose-v1', normalized_name)` or `(source_id, 'inferred-prose-v1', subject, predicate, object)`. Exclude generation from logical projected IDs; provenance records the selected generation. Distinguish this namespace from both KnowledgeObject IDs and legacy global names. Cross-source merging remains out of scope.

Union equivalent entity/triple payloads only within a source and captured profile. Require equal canonical float32 vectors for repeated entity/triple values; conflicting vectors fail projection rather than choosing iteration order. Maintain entity-vector validation even if the present retrieval implementation only uses entity names plus fact vectors. Fact embeddings feed the existing fact candidate stage, reranker, entity seeds and PageRank flow.

Construct each Fact.passage_ids from distinct declared support, build entity-to-passage mentions from that support, and recompute entity passage counts and fact edge weight sums using the existing GraphIndex semantics. Allowed synonyms must be derived from these selected authorized entities, never cached global synonyms that include hidden/staged entities. Additional retrieval views do not create additional mentions or Fact support unless explicitly declared by the sealed extraction. The coordinator remains responsible for the logical chunk support inventory.

The legacy original projection collapses equal physical rows onto one span ID. New extraction support must not ambiguously count several such physical aliases as different logical contributions. Initially require selected support IDs to map injectively to projected candidates within each extraction/support union; reject an ambiguous prepared inventory. A later explicit logical contribution identifier would require a separate contract. Preserve the old no-extraction branch unchanged.

## One citation resolver and answer evidence pack

Add `knowledge/citations.py` with the following narrow public functions:

```python
resolve_citations(graph, passage_ids: tuple[str, ...]) -> CitationBundle
answer_evidence(graph, trace, *, top_k: int) -> AnswerEvidence
```

Both operate solely on the held graph, check its live authorization before and after resolving, and return frozen reader DTOs. Missing lineage for a managed rendered candidate is an error. Legacy resolution returns an explicitly legacy citation using the existing passage ID/text; it cannot manufacture source span/revision identity. A bundle preserves ordered retrieval IDs, each item's derived/original classification and original citation IDs, plus a deduplicated ordered collection of original citations.

`answer_evidence` applies the current non-via-expand/top-k selection before resolving full closures. It does not reduce top-k by the number of original spans or truncate an individual dependency set to its anchor. If prompt limits require excluding an item, omit that entire item and record only the evidence actually supplied to the model. Preserve existing original-only prompt behavior. New rendered text may be supplied as separately labeled derived retrieval context; quotations/citation entries come from original text. A code graph context block remains labeled generated context and never becomes a fabricated passage citation.

`Answer.passage_ids` denotes the original citation IDs actually supplied for new managed answers and retains existing values for legacy/original-only answers. Add default-empty `retrieval_passage_ids` or an equivalent explicit citation bundle field for joins back to ranked results. Do not overload one ID list with a mixture of physical views and original spans. `answer_question` can retain its existing original triples input; the caller builds those triples from the resolver and supplies labeled derived context separately. Any additive Answer fields must preserve deserialization defaults.

## Consumer propagation checklist

| Consumer | Required change |
| --- | --- |
| `ask.py:_answer_from_trace`, `hipporag/answerer.py` | Use the shared evidence pack under the current QuerySession through model completion. Answer citations use original IDs/text; expose which retrieval candidates supplied them. |
| `hipporag/retriever.py` ranked/expanded previews and Trace serialization | Ranking and select-stage previews may retain exact retrieval text, explicitly classified as derived when appropriate. Add default-empty serialized provenance references for selected retrieval items. Trace passage IDs and ranking metrics remain retrieval IDs. |
| `knowledge/replay.py` | Rebuild previews, provenance and citations from the currently authorized held graph. Ignore saved labels, original text, locators and serialized snapshot/view IDs as grants. Extend fingerprint only for new capability; old traces deserialize with empty metadata. |
| `mcp_server.py:search_tool/ask_tool` | Search returns retrieval text with classification and original references. Ask sources come from the citation bundle; replace the current Answer.passage_ids-to-ranked-ID join, which would drop view-backed citations. |
| `web/routes/api.py` | Return original answer passage_ids plus additive retrieval/citation metadata; preserve existing response fields. Build the full response inside the owned session. |
| `web/routes/pages.py` and answer templates | Render the answer's actual citation bundle, not the first trace rows' `.text`. Label rendered previews as derived; original panels show actual locators/text. |
| `web/routes/graph.py`, `web/routes/analyze.py`, analysis/explain/simulate readers | Node details may show retrieval content, but separate original evidence from derived previews. Carry frozen provenance through simulation copies and resolve evidence panels under the current session. |
| `hipporag/paths.py:block_lines/render_block` and code question generation | Code summaries keep their existing generated-context label. Any displayed source evidence uses defining retrieval IDs followed by the resolver, not an assumption that `.text` is original. |
| `evals/question_maker.py`, `evals/runner.py`, `knowledge/eval_access.py` | Generate reference answers from original evidence bundles. Keep gold_passage_ids and retrieval recall in the existing retrieval-ID space; do not silently compare originals against ranked views. Generated set fingerprints include new provenance. Resolve originals separately for grounding/answer grading. Existing source ownership and held-session guards remain mandatory. |
| `knowledge/saved_snapshots.py` and saved eval rendering | Save while the same session is live using existing atomic saved references. The graph fingerprint commits provenance; snapshot IDs remain locators for retained evidence, never authorization. Existing exact deletion releases remain unchanged. |
| `evals/rag_all.py`, fixtures and DTO serialization tests | Fixtures must distinguish retrieval text from original citations and verify both. Legacy fixtures retain their exact existing IDs. |
| CLI and `status.py`/status routes | Follow shared ask/search DTOs. Preserve retrieval passage counts as retrieval counts and expose distinct original/view counts where needed; do not label a count of several views as several original source spans. |

No HTTP, MCP, CLI, HTML, analysis or eval consumer should fetch missing originals from current store rows after its session has closed. In-memory response DTO construction stays inside the existing session. Durable saves retain the exact snapshot before releasing its active reference. Saved reads reacquire an authorized graph; a saved ID is not a way around current ACLs.

## Schema 4 and rollout boundary

This reader slice requires the storage owner's schema 5 fields and shared validation APIs but introduces no additional store schema. A migrated schema 4 generation with only original rows must produce the same projected span IDs, passage text, vectors, Fact behavior, graph-version inputs and saved-answer fingerprint inputs as before. An absent retrieval_view_id means the original branch, not an opportunity to infer a view from similar text. Existing unbound RetrievalView records do not opt a generation into the new capability.

Wire the new path only for explicitly captured derived-capable generations. Unknown new capability versions fail closed. Legacy sources continue through their explicit legacy adapter, and mixed graph composition retains source partitions; strict mixed dense model compatibility remains governed by the embedding-profile design. Do not migrate source defaults until the full prose/code/citation parity gates pass. Missing derivation or extraction outputs cannot be repaired at query time with live model calls or raw staging reads.

## Suggested implementation order and acceptance gates

Create a focused ledger before implementation. Root allocates existing-file ownership and coordinates storage/profile dependencies.

1. **Authorization closure:** add exact inventories and all-input proof sets using real managed fixtures. RED cases hide a secondary unembedded span, suppress a support view or append an incomplete dependency; assert no text, label, vector, entity, fact, count or synonym contribution escapes. Prove current revocation after model work denies output and releases the lease.
2. **Projection identities:** two different vectors/views over one span remain distinct; a multi-original view cites every exact original locator. G2 staging with another dimension cannot affect pinned G1. Missing bindings/profile drift fail. Original-only schema 4 graph and fingerprint fixtures remain byte-for-byte compatible.
3. **Prose parity:** shared normalized entities/triples aggregate only authorized explicit support; same names in another source remain separate. G1/G2 replacement does not union results. Conflicting vectors and ambiguous physical support aliases fail. Successful empty extraction differs from missing/failed coverage. Typed engineering assertions remain outside Fact budgets.
4. **Graph propagation:** scoped/merged/simulated graphs preserve immutable lineage without aliasing mutable JSON. A retained candidate keeps all originals even when they have no graph vertices. Dropped candidate metadata cannot reappear through replay or a copied graph.
5. **End-to-end citations:** instrument the actual answer model input, API/MCP/HTML outputs and eval generator. Assert the generated view appears only as labeled context, original text/locators are exact, two views deduplicate one citation, and source joins preserve retrieval IDs separately. Tampered serialized provenance fails to grant visibility.
6. **Lifetimes and compatibility:** publish G2 during answer/grading/save and still cite G1; revoke current access and deny release; keep saved refs until exact authorized deletion. Reopen a migrated schema 4 fixture and read old saved outputs under unchanged proofs. Run Fake and disposable Ladybug coverage; root schedules any serial Neo4j proof.

Acceptance requires these consumer gates before enabling derived production indexing. The proposal adds no new framework, source reindex default, live model fallback or claim that current unimplemented reader behavior already supports rendered evidence.
