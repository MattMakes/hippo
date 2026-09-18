# Task 5 dense-session implementation contract

Status: bounded implementation complete after independent preflight and structural owner release. Final Fake/Ladybug gates pass; final implementation review is pending. Production activation remains separate. This refines the session/dispatcher steps of [the dense-session design](rag-it-all-task-5-dense-session.md) against the implemented structural graph and controlled profile binding. Where the earlier design proposes resolution before graph acquisition, this contract replaces that sequence with one held structural session.

**Goal:** activate faithful dense matrices and the matching query model from one authorized structural graph, with an explicit compatibility path for existing tags.

**Architecture:** `dense_session.py` wraps the existing session owner. It classifies only retained evidence, reads controlled descriptors locally, and verifies the live model outside transactions. Matrix activation replaces execution capability without reloading evidence or transferring snapshot ownership.

**Gates:** `ai_docs/gates/rag-it-all/task-5-dense-dispatch/GATES.md`.

**Tech stack:** existing Python dataclasses, NumPy, synchronous context managers, store transactions, Ollama adapter, pytest/MockTransport and Fake/Ladybug stores. This is a library increment; no service startup, credentials, model download or live server is required for its gates.

## Public surface

Both constructors yield the existing `QuerySession` type:

```python
@contextmanager
def dense_session(
    ctx,
    access=None,
    *,
    settings=None,
    resolved_profile=None,
    spec=None,
    cache=None,
    session=None,
): ...


@contextmanager
def retrieval_session(
    ctx,
    access=None,
    *,
    settings=None,
    resolved_profile=None,
    spec=None,
    cache=None,
    session=None,
): ...
```

`dense_session` always requests verified mode. `retrieval_session` selects verified or tag compatibility from the held graph. Supplying `resolved_profile` or `spec` explicitly requests verified mode; supplying an optional cache alone does not upgrade evidence. A tag-compatible call never consumes the verified-profile cache.

Without `session`, either wrapper enters exactly one `query_session(ctx, access, settings=settings, structural=True)`. With `session`, it borrows that already selected structural or activated session. It does not reacquire when the borrowed graph is incompatible. A populated default legacy graph lacks the required canonical sidecars and is rejected as an unsuitable borrowed structural input. Empty default legacy graphs are safe compatibility inputs.

Borrowed `access`, when provided, cannot establish a new audience: it must match the owner's effective access contract, or the API should reject it rather than reinterpret the graph. Since `QuerySession` currently stores no audience field, the minimal implementation requires `access is None` for borrowed calls and relies on `session.validate`. Borrowed settings may be omitted; if supplied, merging and validating them against the owner's frozen settings must yield the same settings. Never reread store settings. The wrapper yields the same settings object. Caller-supplied settings are not permission to rebuild the graph.

Add `DenseSessionUnavailable(DenseUnavailable)` with a closed reason value such as `mixed_modes`, `mixed_profiles`, `dimension_mismatch`, `unverified`, `invalid_binding`, `no_dense_dimension` or `invalid_borrow`. Messages must not disclose hidden sources, accepted manifests or private input inventories. Existing typed `EmbeddingProfileUnavailable`, `EmbeddingProfileChanged` and `EmbeddingProfileMismatch` continue to describe live model failures. `AuthorizationChanged` retains precedence. HTTP/MCP translation belongs to later production activation.

## Exact contributor classification

Begin with `validate_dense_graph(graph)` and the owner's live validation. Classify from the resulting graph, never from all workspace sources, all acquired snapshot IDs, current source pointers or arbitrary Generation rows.

The contributor union is:

1. Managed passage and inferred-Fact `DenseVector.generation_id`, with their validated source identity from retrieval/prose support provenance.
2. Every `StructuralCodeEvidence(source_id, generation_id, ...)`, including code nodes with no passage vector and every contribution to a shared node.
3. Every `StructuralObjectEvidence(node_id, generation_id, source_id, observation_ids, original_span_ids)` contribution in `graph.structural_object_evidence`, including standalone typed noncode entities without dense or Fact rows. Observation and original IDs are exact immutable sorted tuples. These node IDs are managed.
4. Every `StructuralRelationEvidence.source_generations` pair. This is necessary when a supported assertion survives from source A while its endpoint code is retained only from sources B/C. Endpoint provenance alone cannot classify A. The implemented immutable tuple is sorted, unique, and exactly covers the relation's original-support sources.
5. Explicit untagged legacy content: `LegacyDenseVector` entries and genuinely legacy retained code/topology. Classify a code node as managed when it has structural code provenance OR an authorized `DEFINED_IN` connection to managed retrieval IDs; ordinary managed code with its own Passage intentionally need not have `StructuralCodeEvidence`. A node with legacy defining passages still contributes compatibility evidence even if it also has a managed contribution. Code without either managed support form is legacy. Managed entity endpoints are established by source-local inferred Fact provenance; remaining unexplained entity topology is legacy. These remain compatibility contributions, never inferred verified members.

Use selected generation IDs directly. A pinned generation may now be retired after publication. Do not reread the active pointer and switch it, reload a second graph, or require it still be current. Read the contributing Generation rows and controlled descriptors in a short local transaction under the existing authorization bracket. Validate before and after the local reads. All graph-held proofs and lease checks remain authoritative; stored descriptors and trace snapshot IDs are not grants.

For every contributing managed generation, call `embedding_mode(generation)`. Absence retains `legacy_tag_v1`; a digest-shaped tag is still a tag. Unknown modes fail explicitly. For `verified_v1`, call `validate_generation_profile(store, generation)`, which validates the exact manifest revision membership, canonical accepted configuration and generation identity, and returns a detached `StoredEmbeddingProfile`. Compare the complete safe descriptor, fingerprint and dimension across contributors, including contributors without vectors. Require every canonical vector to agree with its generation's profile and expected width.

Do not return or fingerprint the accepted manifest, configuration fingerprint, manifest revision ID, source-wide seal checksum or its hidden revision inventory. A generation selected for snapshot retention but contributing no authorized graph evidence does not enter this classification or trigger descriptor/model checks. Staged, suppressed and otherwise excluded content cannot introduce a route error, a width decision or a metadata request.

Any verified contribution combined with tagged or untagged legacy content denies the joint dense route before model text dispatch. No profile partition is silently discarded. Structural browsing remains usable.

## Capability and matrix contract

Add exactly one capability mode:

```python
DenseCapability("tag_compatible", fingerprint=None, dimension=dimension)
```

Its dimension must be a positive bounded integer. It carries no verified fingerprint. Only the dispatcher enables it after proving that every contributing managed generation is `legacy_tag_v1`, that their declared tags equal the captured current `ctx.ollama.embed_model`, and that all retained passage/Fact vectors have one positive width. Untagged legacy remains the existing explicit compatibility assumption; neither matching width nor tag spelling proves an immutable model.

For both active modes, allocate new `np.float32` matrices in exact `graph.passages` and `graph.facts` order. Read values only from canonical sidecars. Verified mode accepts only verified managed rows. Tag mode accepts managed `DenseVector` rows plus `LegacyDenseVector` rows. Keep canonical managed nonzero requirements; retain existing valid all-zero legacy rows. Do not normalize, rescale, majority-select, prune candidates, invent code-name embeddings or reinterpret float precision. Empty lanes have shape `(0, D)`.

A tag graph with surviving code/relation evidence but no trustworthy vector width raises `DenseSessionUnavailable(reason='no_dense_dimension')`. Do not query Ollama for a dimension and pretend it describes historical rows. A truly empty graph with no retained vertices, Facts, vectors or provenance returns the empty compatibility session without HTTP. Hidden-only selected generations do not change that result. A verified code-only graph can obtain width from its validated stored descriptor; its empty matrices are `(0, D)` and its runtime still verifies that descriptor. Explicit verified mode against a truly empty graph can resolve the requested/configured profile; this is a deliberate request, independent of hidden generations.

`dataclasses.replace` preserves all declared GraphIndex fields: retrieval/original/prose evidence, every structural code/object observation contribution and relation, sidecars, topology, counts, weights, boosts, arrows and version. Set only capability, newly assembled matrices and the local owner validation callback. Copy immutable `snapshot_ids` explicitly because they are currently dynamic attributes; retain renewal metadata only as descriptive metadata. Never attach a new owning finalizer, transfer/call the source graph's `close_snapshot`, or start a second heartbeat. The original graph remains alive inside its owning session until the outer context exits.

Compare `view_fingerprint` before/after activation in tests. Capability is an execution condition; canonical row values and authorized evidence remain identical. The source structural graph and its absent matrices remain unchanged.

The coordinated `dense.py` amendment validates tag matrix width and exact union-sidecar equality, preserves complete provenance checks and rejects verified/tag composition. Existing unavailable composition remains unavailable. Same-capability tag composition can retain rows after ordinary source/profile consistency validation. Default populated legacy graphs still require faithful structural conversion before composition. `GraphIndex.scoped` and projection `_assemble` need only include `tag_compatible` in their existing active-width branches, including empty results. Structural relation and code propagation must remain intact.

## Runtime resolution and lifetime

Both public constructors require invocation outside an ambient caller-owned store transaction, including borrowed calls and model use inside their body. This is an explicit API precondition, not a claim of universal runtime enforcement: current stores expose shared transaction state rather than a reviewed per-thread ownership seam, and polling global depth would race the legitimate heartbeat. Tests assert zero transaction depth throughout wrapper-owned HTTP flows. No store API change is included.

The owned structural session has already captured effective settings, selected all evidence, acquired references and started its local-only heartbeat before resolution begins. No preliminary graph/proof route is duplicated.

For a verified candidate set, use the stored `EmbeddingSpec` by default. This preserves the actual indexed query/document prefixes, options, normalization, requested dimensions and truncation behavior. An explicitly supplied spec must match before HTTP. A supplied resolved profile must have an exactly matching validated descriptor and spec; constructing or trusting that object alone does not establish current remote identity.

Without a supplied resolution, call `resolve_embedding_profile(ctx.ollama, spec=captured_spec, authorization_check=owner.validate)` outside all transactions. Compare its descriptor with the accepted stored descriptor. Do not change the shared Ollama model/tag/client or silently resolve another configured model. Explicit verified empty graphs may use the current documented legacy prefix mapping with native dimensions and default options when no spec is supplied, as the existing design allows.

Construct `ProfiledEmbeddings(..., cache=cache, authorization_check=owner.validate)` and freshly validate it outside transactions, including when resolution was supplied. Yield an `AuthorizedModel(adapter, owner.validate)` in the activated session. Add only read-only, local `profile_fingerprint` properties to `ProfiledEmbeddings` and `AuthorizedModel`: the first exposes its immutable resolved fingerprint; the second brackets reading that single optional property with its existing local authorization callback, including nested wrappers and revocation during the read. No unrestricted attribute forwarding or metadata HTTP occurs when the Retriever reads it.

The existing adapter guards every actual embedding/chat HTTP attempt and validates cache hits. The heartbeat and `graph.validate_authorization` continue to perform local/store checks only. Embedding metadata bracketing is not request-level digest attestation and does not pin the answer model's LLM identity.

Tag compatibility retains the existing model path. A captured-tag callback brackets tag equality with owner validation and is attached to the activated graph authorization callback, yielded session validation, and model wrapper, as well as final validation. This rejects tag changes before Retriever scoring even when a supplied question vector and fact filter bypass all model calls, and before empty-result shortcuts. It performs no new digest/show resolution and makes no verified-cache or immutable-model claim. This preserves the named compatibility policy, including existing model transport behavior. Strengthening that transport is a separate change.

On verified wrapper exit, attempt the adapter's remote validation outside locks, and always run owner authorization validation afterward so revocation takes precedence over remote errors. If resolution failed before an adapter exists, still validate the owner. The enclosing owned `query_session` then stops its heartbeat and releases all references in its existing `finally`. A borrowed wrapper validates but never closes its owner. Publication alone keeps G1 valid throughout resolution, retrieval, answer and DTO/save work; an authorization/suppression change denies output.

## Implementation tasks and ownership

All implementation starts with RED tests and ends with focused GREEN evidence. No commits, production route changes or Neo4j use are delegated by this document.

| Task | Gates | Exclusive files | Change and verification |
|---|---|---|---|
| 1. Coordinate active capability amendment after structural owner releases files | DS1 | `src/hippo/knowledge/dense.py`, `src/hippo/hipporag/graph_index.py`, `src/hippo/knowledge/projection.py`, `tests/unit/test_dense_capability.py` | Add tag mode, union matrix validation and active empty widths. RED zero-legacy, mismatched widths, scopes/composition and complete relation provenance cases; preserve prior verified/unavailable tests. No parallel edits during structural step 2. |
| 2. Expose immutable model fingerprint | DS3 | `src/hippo/knowledge/embedding_profile.py`, `src/hippo/knowledge/query_access.py` | Add the two pure read-only properties. Test nested AuthorizedModel forwarding without HTTP; all existing constructors/default session behavior remain valid. |
| 3. Implement one-owner dispatcher and verified activation | DS2–DS5 | NEW `src/hippo/knowledge/dense_session.py`, NEW `tests/unit/test_dense_session.py` | Implement classification, local profile validation, resolution, matrix replacement and owned/borrowed finalization. Exercise public context managers through real managed fixtures and MockTransport, rather than mirroring helper implementations. |
| 4. Integrated regression and independent review | DS6 | This plan and its new gate ledger only | Record exact commands/results and independent SPEC/QUALITY findings. Re-run changed cases after fixes; leave production activation open. |

The focused test file for task 3 also covers task 2's properties; task 2 can write its RED cases only after task 3's test-file owner has yielded ownership. These tasks are sequential, not parallel file writers.

The new module imports `query_session`/`QuerySession`/`AuthorizedModel`, profile validators/adapters, existing dense DTOs and `view_fingerprint` only where needed for tests. It does not register routes, modify context selection, or introduce a second cache/service. Existing `_search` and Retriever already accept a borrowed session/model and check dense capability before text embedding or a supplied vector. Later activation must explicitly replace each model-based route's session factory and map typed dispatch exceptions; this slice does neither.

## Adversarial acceptance cases

- Tag mutation rejects supplied-vector and empty Retriever paths through graph validation; verified code defined by a managed passage without a structural-code sidecar is correctly managed.
- Strict G1 fixture published, then G2 published while profile metadata is blocked: exactly one `graph_for`/bundle acquisition, G1 originals/ranks/trace IDs remain selected, and close releases every reference. Repeat revocation and timeout variants with authorization error precedence and no lease resurrection.
- Hidden, staging and suppressed wrong-profile inputs have no visible routing/HTTP/fingerprint effect. An allowed view with a denied secondary original is absent before classification. Two visible same-dimensional but different verified descriptors deny before private text dispatch.
- A relation supported by A survives with only B/C endpoint code; its immutable source-generation tuple makes A participate even without A vectors. Code-only verified/tag sources also participate. Scoping retains only complete relation support and cannot forget the profile of a surviving contributor.
- Tag-compatible old managed plus untagged legacy at one width preserves exact vectors, including zero rows, ordinary prose/Fact IDs and sidecars. Wrong widths fail rather than prune. Digest-shaped unmarked tags stay tag-compatible. Provenance-only tags deny dense use; truly empty compatibility performs zero metadata/model HTTP calls.
- Captured spec overrides mutable prefix defaults. Query embedding uses the actual captured query prefix/options, cache keys remain profile-scoped, and all-hit cache access detects replacement of the live digest. An HTTP spy asserts store transaction depth is zero on every metadata/embed/chat attempt.
- Matrices are independent writable execution arrays while sidecars and provenance remain immutable. Source graph matrices are unchanged; activated/scoped/composed graph matrices match exact sidecars and fingerprints. Empty passage/Fact lanes retain the positive chosen width.
- Borrowed sessions reuse the same proof, settings and reference lifetime; conflicting settings or nonstructural populated legacy inputs reject without reread/reacquisition. Remote final-check failures and exceptions inside the caller body cannot leak owned references.

## Preservation and rollout boundary

| Existing contract | Preservation / verification | Plan task |
|---|---|---|
| Named legacy query/ingestion defaults and cache behavior | Existing `query_session()` and all production callers remain unchanged; run their regressions | 2–4 |
| Original IDs, generated retrieval IDs and citation closure | Matrix activation preserves graph evidence and fingerprint; no original text synthesis | 1, 3 |
| Scoped code and relation provenance | Preserve every contribution and exact support; classify relation-only generations directly | 1, 3 |
| Snapshot ownership and saved-result audit IDs | One owner/heartbeat, explicit dynamic ID propagation, deterministic close; IDs grant nothing | 3 |
| Controlled generation descriptors | Reuse local exact validator only for contributors; no private manifest data in output/fingerprint | 3 |
| External Ollama dependency | Captured configured endpoint/client; deterministic MockTransport integration, no real credentials needed | 2, 3 |
| Legacy versus new structural topology | Ordinary retained prose/Fact vectors and identities remain equal; structural fixes may retain code previously omitted by the default loader, so do not promise identical whole-graph ranks/topology | 1, 4 |
| Active storage/context ownership | No store/schema/context edits; wait for structural owner before the three bounded shared-file amendments | 1 |

Production publication/ingestion dispatch remains separate until structural callers, retrieval callers and typed transport errors are integrated together. This increment supplies an executable session boundary for that next step, not an alternate retrieval framework or a rollout switch.

## Plan verification checklist

- [x] Root approved the bounded contract, including both independent classification/tag-guard clarifications; shared-file release remains separate.
- [x] Independent SPEC/PREFLIGHT PASS for the amended design; include finalized relation source-generations and typed-object observation provenance. Structural shared-file release remains required.
- [x] Recorded RED/GREEN evidence, 73 focused Fake, 73 Ladybug and 254 broad Fake regressions. No Neo4j was used.
- [ ] Obtain independent SPEC/QUALITY review and run post-flight before publication.
- [x] Existing default routes/pipeline remain untouched; production activation remains open.
