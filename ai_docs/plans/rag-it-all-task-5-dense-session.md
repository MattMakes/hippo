# Task 5: dense sessions and profile-independent graph browsing

Status: step 1 (capability, immutable vector sidecar, fingerprints and Retriever guard) is root-approved for bounded implementation. The remaining storage/profile/session/routing steps are an integration draft pending their own contract review. The resolver/cache adapter is implemented; no production activation is authorized by this document alone. It extends [the embedding profile plan](rag-it-all-task-5-embedding-profile.md). Existing query-session ownership, authorization, citation and lease guarantees remain required.

## Decision and public APIs

Separate requests that need a query vector from requests that only read evidence and graph structure. Browsing must work when Ollama is offline and when selected sources were indexed under different immutable profiles. Dense retrieval must fail explicitly when its authorized candidates cannot share a verified profile. It must not discard sources or mistake equal dimensions for equal models.

```python
@dataclass(frozen=True)
class DenseSelection:
    fingerprint: str
    dimension: int

@dataclass(frozen=True)
class DenseCapability:
    mode: Literal['legacy', 'verified', 'unavailable']
    fingerprint: str | None = None
    dimension: int | None = None

# Existing calls remain valid. No network resolution in this constructor.
query_session(ctx, access=None, *, settings=None,
              dense_selection: DenseSelection | None = None)

# New constructor: supplied resolution is optional; verified mode is mandatory.
dense_session(ctx, access=None, *, settings=None,
              resolved_profile: ResolvedEmbeddingProfile | None = None,
              spec: EmbeddingSpec | None = None, cache=None)

# Context accepts a local, immutable selection, never a transport-bearing adapter.
ctx.graph_for(access, *, settings=None,
              dense_selection: DenseSelection | None = None)
```

`DenseSelection` validates a canonical fingerprint and positive bounded integer dimension. `dense_session` with no resolved profile resolves one; it never interprets omission as permission to use unverified managed vectors. If both spec and a resolved profile are supplied, require exact spec agreement before I/O. Initially the spec is captured from the existing Ollama model-prefix mapping, empty options, native dimensions and `truncate=false`. No new settings UI or model installation is introduced.

Keep trusted tag compatibility in a small explicit dispatcher, `retrieval_session(ctx, access, *, settings=None)`. Authorized candidates that all belong to the established tag-compatibility mode use the existing model path, including supported v3/v4/schema5 managed fixtures and generations awaiting rebuild. Any verified candidates require `dense_session`; mixing verified and tag-compatible candidates fails explicitly. An explicitly supplied resolved profile always requests verified mode, even against legacy-only content. Existing `query_session` calls used by graph-only routes remain network-free. Ordinary legacy GraphIndex fixtures keep their current dense capability by default; structural mixed-profile views are explicitly unavailable for dense retrieval.

Classification is a versioned storage contract, not a date, model-name pattern, or digest-shaped string. Introduce a storage-controlled `Generation.coverage_json.embedding_mode` value: `legacy_tag_v1` or `verified_v1`. An absent value on the existing supported generation contract means `legacy_tag_v1`, preserving the published compatibility default. Unknown values fail closed. New legacy adapter/fixture generations may explicitly stamp `legacy_tag_v1`; the new managed coordinator must request controlled `verified_v1` binding and cannot publish without it. Generic Generation writes cannot preseed, change, or remove a controlled verified marker. Never upgrade an unmarked generation because its profile string happens to equal a fingerprint. Legacy untagged native rows remain legacy-only; their existing narrow trusted-generation mapping remains explicit. The dispatcher rechecks classification after atomic selection and chooses compatibility only if every authorized candidate belongs to that mode.

## Current seams

- `knowledge/query_access.py:query_session` already captures settings, owns a selected graph and heartbeat, and closes on all exits. Extend that lifetime; do not duplicate lease ownership in the dense wrapper.
- `context.py:_build_managed_graph` currently sets `profile = self.ollama.embed_model`, requires it during snapshot selection and projection, and checks that tag in its live callback. This assumption must be removed from structural reads before fingerprinted generations can be published.
- `knowledge/snapshots.py:acquire_query_snapshots` currently accepts one profile string and creates one snapshot per workspace. Structural reads need the selected generations' declared profiles without asking Ollama which model is installed.
- `knowledge/graph_loader.py` currently applies the majority-dimension rule before constructing the graph. That rule cannot select a verified dense partition or determine structural visibility.
- `knowledge/projection.py:_safe_vectors`, `_project_prose`, `_assemble` and `compose_graphs` currently assume compatible matrices. Split text/binding authorization from matrix assembly; keep their existing original and derived evidence checks.
- `hipporag/retriever.py:Retriever.retrieve` embeds or accepts a query vector and can fall back to dense passage retrieval. Add a capability check before either path, before empty-result shortcuts and before any model call.

## Structural graph selection

1. Inside the existing authorization/pointer-selection transaction, capture source-to-generation IDs and each generation's declared profile. Build exact evidence proofs before allowing hidden rows to influence profile compatibility, dimensions or errors. Source-control visibility alone is insufficient: workspace membership and all-input evidence policies still apply.
2. Acquire all references atomically. Extend `acquire_query_snapshots` with a mutually exclusive `source_profiles` mapping for structural calls, retaining the existing scalar argument for compatibility. Validate each selected generation against its supplied profile and group snapshots by `(workspace_id, profile_fingerprint)`. Use one lease owner and one outer transaction for the complete bundle. This uses existing QuerySnapshot fields and requires no synthetic profile hash or schema migration. A returned bundle validates/releases every group.
3. Materialize each authorized source's native and prose evidence independently. Verify its generation, exact membership, span/view text, original dependency closure and persisted profile bindings. Do not compare its declared profile with the currently configured Ollama tag. Do not apply a cross-source majority-dimension filter. Staging and unauthorized inputs cannot affect retained topology or profile decisions.
4. Assemble all authorized passages, code objects, inferred Facts, explicit mentions/support counts, typed assertion edges and citations. Preserve source-local prose synonym semantics using the validated vectors within that source/profile. Never compute similarity between incompatible profiles. A malformed selected sealed input remains an integrity error; a different valid source profile is not corruption.
5. A structural mixed-profile GraphIndex has `DenseCapability('unavailable')`, matrices shaped `(passage_count, 0)` and `(fact_count, 0)`, and all authorized vertices. These are absent matrices, not zero embeddings to score. Preserve selected canonical vector rows in an immutable, ID-bound sidecar for fingerprints and per-source reconstruction; they are never exposed as a joint dense search matrix. Use frozen records with `(lane, projected_id, generation_id, profile, dimension, values: tuple[float, ...])` inside a tuple, not a frozen dataclass containing writable arrays/dictionaries. Validate finite canonical float32 values, strict dimensions, uniqueness, and binding to an existing authorized projected node. Passage entries cover exactly their projected retrieval IDs; Fact entries cover exactly the source-local inferred Fact IDs and selected extraction/support closure. Do not copy global native Entity/Fact vectors into this sidecar. Code-name vectors remain absent because the current managed projection has no exact embedding-text binding for their cross-kind use; future admission requires explicit binding to the authorized canonical object, selected generation and embedded name text. Existing code labels/edges remain available without those vectors. `scoped` retains only matching passages/Facts and complete support; composition rejects duplicate/conflicting lane+ID entries and builds deterministic row order. Deep copies cannot introduce mutable aliases. Do not add invented vectors to persisted rows.
6. Keep legacy-only graph loading and its fingerprints unchanged. For managed structural views, `view_fingerprint` reads the same ordered canonical passage/fact vector rows from the sidecar that a corresponding verified view would use from its matrices. Capability is an execution constraint, not source evidence: do not create an avoidable fingerprint mismatch merely by opening the same evidence for browsing. Preserve the existing original-only fingerprint fixtures. Fingerprint only authorized rows, never source-wide seal checksums containing hidden inputs.

Graph-only output can therefore include sources from profiles A and B while dense retrieval rejects the joint partition. No source disappears because the current model is missing, renamed or incompatible. No metadata HTTP calls run from graph loading, status, source listings, saved analysis display, login/error rendering, or snapshot heartbeat callbacks.

## Verified dense selection

`DenseSelection` takes the strict branch in the same context selection code. Before constructing matrices:

- Determine the authorized retrieval inventory from exact proofs and bindings. Hidden evidence or a hidden source must not cause a new visible profile error or trigger metadata resolution. Do not disclose offending source IDs unless the caller may see them.
- Require every selected managed candidate to carry the exact resolved fingerprint and expected dimension. Check individual passage and Fact rows; do not use majority voting or silently prune wrong-shaped candidates. Equal-dimensional wrong-digest rows fail. Empty inventories retain explicit empty semantics.
- In explicit verified mode, reject any authorized legacy/tag-compatible vector partition, including unverified tag-only managed generations, rather than relabeling it. The error requests a rebuild under a captured profile and leaves browsing and the all-tag-compatible baseline available. Never infer that a 64-character stored string proves a complete verified build descriptor: verify the descriptor/profile binding from the accepted build configuration described below.
- Compose only compatible verified matrices and set `DenseCapability('verified', fingerprint, dimension)`.

Preliminary routing uses short local reads/proofs under an authorization epoch bracket, outside HTTP work. It is advisory: selection is checked again atomically after resolution. If publication changes the compatibility classification in between, fail with a retryable typed selection error rather than silently switching mode. Pure publication after successful pinning keeps that pinned generation valid.

### Accepted descriptor storage and validation

Use the planned accepted-manifest Artifact and immutable ArtifactRevision, not arbitrary source metadata or the global embedding tag. The coordinator writes canonical accepted-manifest bytes to the raw artifact store; the manifest includes the closed, nonsecret `resolved.descriptor()` in its accepted configuration. Mirror that canonical manifest object in the manifest revision's `metadata_json.accepted_manifest_v1`. Because this revision's content hash includes the configuration itself, a changed descriptor creates a new manifest revision; it does not mutate an original source revision's metadata.

Add one controlled storage binding operation before verified publication: `bind_generation_embedding_profile(generation_id, manifest_revision_id, *, lease_owner, fencing_token, ...)`. Under the existing generation-write fence, it requires the manifest revision to be an exact GenerationMember, its Artifact to be `kind='manifest'` in the same source/workspace, the closed manifest serialization hash to equal the revision content hash, and recomputation of `Generation.manifest_hash` from the exact accepted revisions and configuration through the `generation_for_inputs` canonical helper to match the stored Generation. There is no standalone config-fingerprint field on Generation; the later IndexManifest.config_fingerprint must also match the canonical accepted configuration. A pure `validate_profile_descriptor` reconstructs validated EmbeddingProfile/EmbeddingSpec values and recomputes every fingerprint; it does not construct an HTTP client or assert remote execution attestation. Require descriptor fingerprint to equal `Generation.embedding_profile` and the dense/native inventory profiles and dimensions. Stamp `embedding_mode='verified_v1'` plus `embedding_manifest_revision_id` only through this operation, and include this binding in the new generation seal commitment. Revalidate the binding at seal/publication. Existing unmarked seals remain byte-compatible; no rewrite of old checksums.

Raw-byte verification and remote model verification occur during preparation outside DB locks. Transaction-bound validation operates on the immutable canonical metadata mirror and its content hash, never filesystem/network I/O. The new coordinator cannot skip the raw artifact capture or substitute mutable source configuration for the accepted manifest. Readers first establish that the generation contributes authorized evidence, then internally validate its controlled manifest binding and extract only the profile descriptor needed for selection. The full accepted manifest may contain hidden artifact inventory: do not grant access to it implicitly, render it, send it to a model, or include its whole hash/content in the audience fingerprint. Hidden-only generation/profile metadata must not change visible routing or error behavior.

## Dense-session sequence and guards

1. Capture effective settings and live audience under an authorization epoch bracket. Install a preliminary local authorization callback; it performs short reads, never holds a transaction across a network request.
2. Resolve the optional missing profile, or freshly validate a supplied resolved profile, outside all store locks. The fixed resolver probe contains no source or question text. Do not mutate `ctx.ollama`, global model settings or the shared HTTP client.
3. Open `query_session(..., dense_selection=DenseSelection(...))` with those captured settings. Its graph selection and reference acquisition are local. The heartbeat continues to call only local/store authorization and lease checks.
4. Build `ProfiledEmbeddings(ctx.ollama, resolved, cache=cache, authorization_check=session.validate)` and wrap it in `AuthorizedModel`. Yield a QuerySession with the same graph, settings and ownership, replacing only the model. Expose a read-only profile fingerprint through the model wrapper so the Retriever can match it with verified graph capability; do not expose client state or use unrestricted attribute forwarding.
5. Before and after every embedding/chat HTTP attempt, use the adapter's existing remote identity and local authorization guards. Both prefixes/options remain captured. Cache hits still perform adapter validation. No network check belongs in `GraphIndex.validate_authorization`, `QuerySnapshotBundle.validate` or the heartbeat.
6. In the dense wrapper's `finally`, validate remote identity outside locks and then validate current authorization, including model errors and cache-only operations. Authorization/revocation failure takes precedence over model failure. The enclosing query_session always stops/joins its heartbeat and releases references even if the remote final check fails. Borrowed callers do not close the owner's session.

`GraphIndex.require_dense(profile_fingerprint=None)` rejects unavailable capability and rejects a verified graph without the matching model profile. Invoke it at the Retriever boundary even with a caller-supplied query vector; lexical/code seeds cannot silently turn a structural graph into a retrieval fallback. Explicit code-path/neighborhood APIs remain structural and need no query vector. Preserve legacy-only Retriever tests and direct synthetic graph construction.

## Production caller wiring

Switch model-based retrieval ownership to `retrieval_session` (which chooses verified managed or the explicitly classified all-tag-compatible baseline): ask/search's unborrowed `_query_session`, API ask/search, MCP ask/search, CLI query entrypoint, graph light-up, eval runner and simulation. A supplied session must already satisfy the required dense capability; never upgrade it by reacquiring a second graph after the caller has selected evidence.

Keep `query_session` for source/status/account/user inventory, graph full/node/neighborhood and code-path tools, rendering, saved-result display/reconstruction, and eval metadata reads. Inspect conditional callers: analysis GET remains structural; simulation/retrieval POST owns a retrieval_session; question generation that only reads passages and uses chat does not need a query vector. Ensure its authorization-guarded chat contract remains intact without adding an embedding-model dependency.

Persist captured build descriptors/fingerprints in the accepted configuration before generation IDs. Use the existing shared preparation helpers and profiled adapter for every managed embedding lane. Only activate fingerprinted generation publication once structural reads, strict retrieval routing and typed HTTP/MCP error handling are implemented together. A separate unusable write-only capability is not the rollout target.

## Bounded implementation order and gates

1. **Capability and fingerprints:** add GraphIndex capability/sidecar, preserve scoped/composed behavior, and reject structural retrieval before all model calls, including supplied vectors and empty graphs. Old legacy/original-only fingerprint tests remain unchanged.
2. **Structural selection:** extend snapshot grouping and loader/projection modes; test profiles A/B with different dimensions in one workspace, all topology/citations/counts retained, zero Ollama calls, current revocation and deterministic reference closure. Same cases on Fake and Ladybug; root reserves Neo4j.
3. **Strict selection and compatibility:** explicit DenseSelection uses exact authorized inventory; reject wrong digest, wrong dimension and mixed unverified legacy content before embedding. Preserve all-tag-compatible v3/v4/schema5 fixtures until rebuild. Test absent/explicit legacy marker, verified marker, unknown marker, attempted preseed/downgrade and digest-shaped legacy tags. Test missing/malformed manifest descriptors, wrong source/member/config hash and same-dimensional descriptor mismatch. Hidden/staging incompatible content must not change visible results/errors. Multi-source selection failures release every acquired reference.
4. **Dense session and routing:** real MockTransport checks metadata and query wire prefix/options, all-hit digest replacement, timeout/error/revocation precedence, settings capture, no HTTP at positive transaction depth, and heartbeat renewal while the model blocks. Legacy-only mocks retain their prior calls. Borrowed-session incompatibility rejects instead of reacquiring.
5. **Activation regression:** publish a fingerprinted fixture generation and verify browse/status/source/analysis work with Ollama offline; bring the matching mock model online and retrieve it; replace the tag with a same-dimensional digest and deny dense results without hiding the source. Verify new-profile rebuild and pinned old-generation behavior. Validate every production caller listed above before enabling managed pipeline dispatch.

Tests should distinguish structural evidence completeness from dense retrieval eligibility. Passing resolver/cache unit tests alone does not satisfy these integration gates. The existing stable-server metadata-bracketing limitation remains unchanged; no cryptographic execution attestation is claimed.

Step 1 interim boundary: composing a structural graph with populated legacy content that lacks faithful generation/vector bindings rejects explicitly; empty legacy components are neutral. Step 2 must provide faithful heterogeneous structural loading before production activation, so this temporary implementation restriction cannot become a user-visible loss of source topology.
