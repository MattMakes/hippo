# Task 5 immutable embedding profile and guarded Ollama adapter

Status: resolver and guarded adapter implemented and independently reviewed, 2026-09-11; focused ledger 2/2 met (164 tests). Build and query production wiring remain pending. This contract complements [the staged pipeline design](rag-it-all-task-5-pipeline.md), [the storage contract](rag-it-all-task-5-storage.md), and [Task 5](../../docs/rag_it_all.md#task-5--staged-generations-and-pinned-query-snapshots).

## Decision

Resolve a frozen embedding profile before managed indexing or dense querying. Capture the installed model digest, actual output dimension, both task prefixes, exact request options and normalization algorithm. Use its canonical fingerprint in Generation, Passage, QuerySnapshot, graph loading and cache selection. Keep the wire model name separate from that fingerprint.

Add a managed Ollama adapter around the existing vectors-only cache. It verifies the installed digest before and after each embedding HTTP batch, and before and after an entire operation even when every vector is cached. Unknown identity, changed identity or incompatible indexed profiles produce a typed error; they never silently switch models or bypass strict profile checks.

Legacy callers remain opt-in: ordinary `Ollama.embed`, existing mocks and legacy-only ingestion/querying keep their existing behavior. Managed callers must supply a resolved adapter. Missing metadata is not permission to publish an unverified managed generation.

## Verified API boundary

The official `GET /api/tags` response includes a model name and SHA-256 digest. Preserve these fields rather than using the current `installed_models()` name-only result. Resolve an exact configured name or its unambiguous omitted-`:latest` equivalent; do not search by basename or choose the first related model. [Ollama list-models API](https://docs.ollama.com/api/tags)

`POST /api/show` provides `model_info`, including architecture-specific fields such as `llama.embedding_length`. That example describes an architecture dimension, not a universal guarantee of the embedding endpoint's output shape. Use it as diagnostic metadata; establish actual output dimension using one fixed, non-sensitive embedding probe. Do not parse the Modelfile for a filesystem path or equate a weight-blob hash with the installed model manifest digest. [Official API documentation, show-model section](https://github.com/ollama/ollama/blob/main/docs/api.md#show-model-information)

`POST /api/embed` accepts a model **name**, input, optional dimensions, options and truncation behavior. Its documented response contains the model name and vectors, without digest attestation or a conditional digest precondition. Set `truncate=false` for the managed path so oversize input fails visibly. Do not invent `model@sha256` addressing or assume a raw digest is a supported model selector. [Ollama embedding API](https://docs.ollama.com/api/embed)

Ollama documents unit-length output and recommends using the same embedding model for indexing and querying. The app will still validate and normalize explicitly, because malformed or incompatible responses must fail before persistence. [Ollama embeddings guide](https://docs.ollama.com/capabilities/embeddings)

**Limit of the guarantee:** metadata bracketing detects observable tag replacement. It cannot prove that an external process did not replace and restore the same tag between requests, or that a load-balanced endpoint used the same model on every replica. Managed operation assumes a trusted, stable Ollama installation during the operation. No automatic pull/copy/install is part of this resolver. A copied alias is also mutable and does not remove this limitation. If adversarial concurrent server mutation must be supported, require a serving API with an attested immutable model selector before claiming that guarantee. Numeric bit-for-bit reproducibility across runtime/hardware versions is also outside this profile's claim.

## Existing seams and changes required

| Seam | Current behavior | Required managed behavior |
| --- | --- | --- |
| `src/hippo/ollama.py:77`, `installed_models` | Discards digest and other metadata | Add strict metadata reading without changing this legacy method's return type |
| `src/hippo/ollama.py:170`, `embed` | Reads mutable model/prefix on invocation; batches requests; normalizes | Explicit captured model/prefix/options and digest checks around every HTTP batch |
| `src/hippo/ollama.py:198`, `embedding_dim` | Caches a probe dimension independently of model identity | Never use this cache to resolve a strict profile |
| `src/hippo/knowledge/embedding_cache.py:39`, `EmbeddingProfile` | Validates caller-attested identity | Reuse unchanged; resolver supplies verified values |
| `src/hippo/knowledge/embedding_cache.py:197`, `cached_embed` | Exact-input cache with local `embed_model` guards | Keep network-free; adapter owns remote checks, including full-cache hits |
| `src/hippo/context.py:194`, `_managed_graph_for` | Opens a transaction; `_build_managed_graph` captures a tag | Pass a previously captured fingerprint/dimension into transaction-bound selection |
| `src/hippo/knowledge/query_access.py:66`, `query_access` | Wraps `ctx.ollama` in `AuthorizedModel` | Compose authorization checks with the request's managed embedding adapter |
| `src/hippo/knowledge/snapshots.py:99`, `acquire_query_snapshots` | Compares string profile identity | Supply the canonical fingerprint; never the wire tag |
| `src/hippo/knowledge/graph_loader.py` | Existing dimension filtering cannot establish model compatibility | Select exact profile before constructing dense matrices, then verify every row's dimension |
| `src/hippo/model_manager.py`, `ModelManager` | Background installation remains a separate operation | Resolver does not invoke it; observable concurrent change invalidates the managed operation |

Line numbers identify the inspected baseline and may move during pipeline integration.

## Minimal API contract

Create `src/hippo/knowledge/embedding_profile.py`. Keep low-level HTTP parsing in `src/hippo/ollama.py`, sharing its configured HTTP client, timeout and error handling. Do not create an independent client with different credentials or endpoint selection.

```python
@dataclass(frozen=True)
class EmbeddingSpec:
    query_prefix: str
    document_prefix: str
    options_json: str  # canonical strict JSON object, copied at capture
    dimensions: int | None = None
    truncate: bool = False
    normalization: str = "l2-f64-to-f32-v1"
    preprocessing: str = "exact-utf8-prefix-v1"


@dataclass(frozen=True)
class ResolvedEmbeddingProfile:
    profile: EmbeddingProfile
    fingerprint: str
    wire_model: str
    spec: EmbeddingSpec
    endpoint_identity: tuple[str, str]  # captured endpoints; omit from persistence

    def descriptor(self) -> dict: ...  # copied profile/spec/fingerprint only


def resolve_embedding_profile(
    ollama, *, spec: EmbeddingSpec, authorization_check=None
) -> ResolvedEmbeddingProfile: ...


class ProfiledEmbeddings:
    def __init__(self, ollama, resolved, *, cache=None, authorization_check=None): ...
    def validate(self) -> None: ...  # remote; never invoke under a DB lock
    def embed(self, texts, kind="document", batch_size=32) -> np.ndarray: ...
    def embed_one(self, text, kind="query") -> np.ndarray: ...
    def embedding_dim(self) -> int: ...  # captured value, no HTTP


class EmbeddingProfileUnavailable(OllamaError): ...


class EmbeddingProfileChanged(OllamaError): ...


class EmbeddingProfileMismatch(OllamaError): ...
```

`ProfiledEmbeddings.embed_model` is the exact captured model string in `profile.model`, satisfying the existing cache protocol. Its separate `wire_model` is the exact installed name selected from metadata. Capture the configured name and underlying client identity too; changing `ollama.embed_model`, endpoint or relevant request configuration invalidates the adapter even though its own profile remains frozen. The adapter exposes its resolved profile, model name and client through read-only properties. Persist `resolved.descriptor()`; never call `asdict(resolved)`, which includes transport state. Expose explicit chat forwarding to the captured original model, then wrap the adapter with `AuthorizedModel`. Thread an optional `request_guard` through Ollama's chat/capability methods and `_request`; the managed adapter supplies its validation callback before and after every actual HTTP attempt, including transport errors and retries. Guarded capability failures propagate rather than becoming an empty capability cache. No guard is installed on shared client/model state; legacy callers use the default `None`. Preserve chat prompts and LLM configuration.

The resolver and wrapper accept an authorization callback so the caller can deny before every HTTP dispatch and after it, including error paths. Indexing passes its source/build authorization check; querying passes the live query proof. A callback may perform short store reads and then return; it must not retain a transaction while network work executes. Use explicit methods, not unrestricted `__getattr__` proxying that could bypass guards.

### Canonical identity

1. Validate/copy the spec before any HTTP request. Prefixes must be strings with bounded UTF-8 length. Options must be a bounded JSON object with string keys, finite JSON values, no duplicate keys or custom coercions. Dimensions must be an integer in the cache's supported range, excluding booleans. Initially expose no arbitrary UI options: use `options={}`, native dimension and the existing two prefix pairs. The API can accept validated overrides for tests and later configuration.
2. Normalize the digest to lowercase 64-character hex without the optional `sha256:` prefix. Reject absent, malformed or conflicting matches. Do not silently repair an ambiguous model list.
3. `profile.model` is the captured configured model name. Preserve namespaces and registry components. For omitted tags, inspect the final path component when recognizing `:latest`; a registry port is not a model tag. Only accept the exact name and that one equivalence. If both equivalent entries exist, require agreement on digest and selected wire identity or reject ambiguity.
4. `preprocessing_version` is `exact-utf8-prefix-v1:` plus SHA-256 of canonical `{query_prefix, document_prefix}`. Both prefixes participate even when constructing a document vector. No trim, Unicode normalization or title concatenation occurs in this adapter; the prepared retrieval text is already the exact cache input.
5. `normalization_options_fingerprint` hashes canonical `{normalization, options, truncate, dimensions}`. All options sent to `/api/embed` belong here. Exclude operational `keep_alive`, batch size, timestamps and cache paths; they do not define the requested vector semantics. Explicit server runtime identity may be added later as a conservative invalidator, without claiming identical weights imply identical floating-point output.
6. `fingerprint = sha256(canonical_json({"profile_schema": 1, "profile": asdict(profile)}))`. Canonical JSON uses sorted keys, compact separators, UTF-8 and rejects nonfinite values. Do not use Python's process-dependent `hash()` or cache-key digest, which also includes input text and kind.
7. Store the complete nonsecret descriptor with the accepted build configuration/manifests, not only the fingerprint. The input manifest includes this descriptor/fingerprint before generation/native IDs are created. Document and query operations share this fingerprint; their cache keys still differ by `kind`.

Do not extend or reinterpret published cache entries: the existing profile fields suffice, and the new preprocessing/options fingerprints naturally create separate entries. A tag alias change may conservatively cause a miss even when the digest is unchanged.

### Resolution sequence

1. Validate local client identity and authorization; fetch `/api/tags` and select the installed model/digest.
2. Fetch `/api/show` for the selected wire model. Validate the response object; capture diagnostic architecture and declared capabilities. An explicit capabilities list without embedding support is unavailable. For older responses with no capabilities field, the successful probe establishes endpoint support. Missing dimension metadata is not fatal; contradictory/malformed declared metadata is reported rather than guessed.
3. Embed the constant document probe `hippo embedding profile probe v1` with the captured document prefix and exact managed options. Do not use source content or index/cache this probe. Obtain dimension from the actual single output row. If a dimensions override was requested, require exact agreement; architecture hidden width need not equal a reduced output dimension.
4. Validate one numeric, finite, nonzero vector; normalize with the named algorithm. Reject strings, booleans, ragged arrays, wrong row count, out-of-range dimensions and overflow. Verify the response model matches the selected wire identity using the same strict name equivalence.
5. Fetch `/api/tags` again and require the same digest/name; check local client identity and authorization in `finally`, including HTTP errors. If identity or permissions changed, that failure takes precedence over a retryable model error. A failed post-check yields no resolved profile.
6. Construct the immutable descriptor. Cache a descriptor only by captured endpoint, digest and full spec; never by tag alone. Initial implementation may resolve once per build/query session without a shared metadata cache. Optimize repeated probes later by a bounded descriptor cache keyed by verified digest/spec, while retaining fresh tag checks.

The network sequence must be bounded. Reuse the configured HTTP timeout, but strict embedding/metadata helpers perform one HTTP attempt: hidden client retries could resend input after permission or identity changed. A caller may explicitly retry the entire guarded operation; do not poll until a tag becomes stable or download a missing model. Legacy HTTP retry behavior remains unchanged. An unavailable resolver returns a typed failure without changing serving pointers.

### Cache and embedding operation sequence

The public adapter brackets the entire `cached_embed` call with `validate()`, including all-hit and empty-input operations. A private cache-protocol model handles misses using the captured spec. It brackets **each actual HTTP batch** with remote digest and authorization checks, validates the entire response before returning rows, and applies prefixes exactly once. Avoid calling legacy `Ollama.embed` and then prefixing again.

Use `try/finally` around metadata/model/cache operations so a failure cannot bypass the final identity/authorization check. Check authorization before each metadata request too. With a network error after vectors were produced, reject that operation and return no vectors. With stable identity, a model error remains a model error. No HTTP request may occur while a store transaction, generation-write scope or authorization lock is held.

Validate raw numbers and float32 representability before normalization: raw overflow or an entire row underflowing to zero is rejected even when an alternative normalization might recover a vector. Compute norms from the **original accepted float64 values**, normalize, cast to float32 and revalidate finite output and nonzero length. The representability check must not round the values used for normalization. This algorithm is named in the profile; it deliberately does not pretend to reuse vectors produced by a different legacy normalization profile. Every returned row must have exactly the captured dimension.

The published cache primitive validates all miss rows before writing them, deduplicates inputs and restores input order. Retain those semantics. Its local model guards remain useful, but remote digest checks belong in the adapter. Cached vectors also need the adapter's normalization contract: normalize/revalidate a cache-returned row before release, or reject non-unit rows as corrupt misses. Choose one deterministic rule in implementation tests; recommended is re-normalize the returned copy without rewriting shared cache files.

Cache writes already completed for an earlier, successfully verified batch remain valid for the old immutable profile if a later observable drift aborts the call. Do not delete shared entries as rollback; another caller may own them. A failed current batch must not be returned to `cached_embed`, so it cannot be written under an unverified profile. Cache I/O failure remains a usable miss/write omission, while model identity failure never becomes a cache bypass.

## Pipeline and query wiring

### Managed build

The pipeline owner captures `BuildInputs.embedding_profile` using this resolver before `generation_for_inputs`, staging writes or model-dependent preparation. Use one adapter for passage/view, entity/fact and code-name **document** embeddings; these distinct inputs retain their exact original cache keys. Use the frozen descriptor's dimension to allocate empty matrices without another probe. Keep the OpenIE extraction profile separate.

After preparation and before sealing/publication, verify identity once more outside the transaction. Publication seals the captured profile and prepared vectors; no HTTP validation happens inside the publication transaction. If the model changes after the last check, the old vectors still belong to their captured profile, but a new query must resolve a compatible profile before using them. This is preferable to pretending that a model tag can be atomically locked together with a database pointer.

Pass the descriptor/fingerprint through all staged writer APIs. A writer must reject a Passage/profile mismatch, including equal-dimensional vectors with different model digests. The full prepared inventory—not the metadata probe—establishes dense coverage before sealing.

### Managed dense query

1. Capture the caller's authorization epoch/live identity and effective settings. Determine whether the request needs managed dense retrieval using authorized metadata; do not make model calls for status, source listings, graph browsing or login/error pages.
2. Resolve the profile outside any DB transaction, with the preliminary authorization callback around network work. Recheck that callback before entering snapshot selection.
3. Pass the resolved fingerprint and dimension into `graph_for`/snapshot acquisition. The transaction selects only compatible generations and closes before any query embedding. Existing graph authorization callbacks remain local/store-only; do not add remote metadata checks to `GraphIndex.validate_authorization()`.
4. Bind the request's query adapter to the pinned graph and wrap it in `AuthorizedModel`. It uses `kind="query"`, the captured query prefix, and the same fingerprint as indexed documents. Retrieval never replaces it with `ctx.ollama.embed_one` or a newly resolved profile partway through the request.
5. Validate remote identity outside locks before final managed dense result release, including cache-only paths. Continue existing authorization/session guards and snapshot cleanup on every exit. Pure content publication does not invalidate a pinned generation; changed current permissions still do.

Expose the resolved object as an explicit optional context/query-session argument or a dedicated dense-session constructor. Do not store it by mutating shared `ctx.ollama`, and do not silently resolve network metadata from `graph_for` called by graph-only routes. Prefer requiring the descriptor for strict dense mode over allowing a caller to forget it and receive tag-based compatibility.

### Compatibility boundary

Legacy-only requests retain their existing tag-based model behavior and mocks. Strict managed paths require the resolver protocol explicitly; unsupported mocks fail with a typed unavailable result unless the test supplies a fake resolver/adapter. No test-only fallback is installed in production.

A legacy vector's tag and dimension cannot prove that it was produced by the currently resolved digest. Initially fail strict **combined dense** retrieval if it would mix an unverified legacy vector partition with managed vectors; direct the caller to rebuild those sources with a captured profile. Do not silently relabel old vectors, treat a matching dimension as compatibility, or hide a missing partition as an empty successful result. Legacy-only compatibility and graph-only source browsing remain available. Profile-partitioned multi-model retrieval is a later feature and requires separate query embeddings/ranked lists.

## Implementation slices and acceptance tests

These are proposed gates for the Task 5 integration ledger. Root owns scheduling, final ledger entries and publication. Each slice starts with a failing regression and then implements the smallest complete behavior.

| Slice / proposed gate | Owned implementation and tests | Required evidence |
| --- | --- | --- |
| E1 strict resolver | `src/hippo/ollama.py` metadata/batch helpers; new `knowledge/embedding_profile.py`; new `tests/unit/test_embedding_profile.py` | MockTransport tests prove real wire shapes, strict digest/name parsing, successful actual-dimension probe, stable canonical identity and errors |
| E2 guarded cached adapter | Same owner/files; existing cache tests stay unchanged except new integration coverage | Drift on miss/hit/error and individual HTTP batches prevents vector release; exact request prefixes/options and normalization verified |
| E3 build integration | Pipeline owner: `knowledge/indexing.py` or chosen preparation module, `ingest/pipeline.py`, `tests/unit/test_managed_profile_wiring.py` | All embedding lanes share descriptor; no metadata/model call in transactions; mismatch/failure leaves active generation intact |
| E4 query integration | Root: `context.py`, `knowledge/query_access.py`, graph loader, `tests/unit/test_managed_profile_wiring.py` and query-session regressions | Exact profile before dense selection; pinned adapter/prefix; full-hit drift denied; cleanup/ACL precedence; no network in graph-only routes |

Required adversarial cases:

1. Missing model, bad digest, conflicting duplicate rows, non-object show response, explicit non-embedding model, metadata timeout and HTTP failure. Neither profile nor staged publication is produced.
2. Exact model versus omitted `:latest`, namespace collisions and registry-with-port names. Equivalent names resolve deterministically; unrelated tags never match.
3. Show lacks embedding length; actual probe succeeds. Show architecture dimension differs from explicitly reduced output; probe/override agree. Invalid probe row count, values or dimensions reject. Existing stale `_embedding_dim` cannot influence the result.
4. Same tag changes digest between initial tags/show/probe/final tags. Also change the client's configured tag or endpoint while resolving. All fail without a resolved profile.
5. Each of digest, document prefix, query prefix, options, normalization version and dimensions changes the fingerprint. Reordering JSON object keys does not. Input order/batch size/cache location/keep-alive do not alter it. Mutating the original options dict cannot change a captured spec.
6. Assert actual HTTP request bodies use the selected model, exact single prefix, `truncate=false`, captured dimensions/options and document/query kind. Query and document cache entries remain distinct while the profile is identical.
7. Replace a same-named installed model during a miss batch, between two HTTP batches, during an all-hit cache read, and while an HTTP error is raised. No current operation returns vectors; failed current-batch vectors are not cached. Preserve already verified old-profile entries.
8. Change model identity during the last cache lookup/write or final guard. Cover all-hit, mixed-hit, duplicate inputs and empty input. Empty output is `(0, captured_dimension)` with no probe/embed request, while required metadata guards still run.
9. Cache corruption remains a miss; cache write failure still returns correctly verified vectors. Malformed model response remains an error. Normalization produces finite, nonzero float32 unit vectors without modifying cached arrays in place.
10. Fake store transaction-depth instrumentation makes every HTTP handler assert depth zero. Exercise resolver, per-batch checks, cache-only final checks, query cleanup and build seal/publication. Model calls must never be buried inside authorization callbacks.
11. Realistic MockTransport document indexing and query embedding use the same digest/profile but different captured prefixes. Same-dimensional wrong-digest generations are rejected before dense scoring. Mixed unverified legacy vectors produce the explicit compatibility error.
12. Metadata failure while refreshing preserves G1; no global embedding metadata is changed by staging. A later stable model digest requires a new generation rather than mutation of G1's profile.
13. ACL revocation during metadata, cache lookup, model success/error or final release wins over stale output. Snapshot references close on all errors. Authorization errors must not be converted to a model/cache miss.
14. Existing Ollama mocks, legacy indexer, offline context creation, authentication error pages and graph-only routes gain no metadata/probe calls. These cases must remain independent of a running Ollama daemon.

Proposed commands after implementation, using disposable fixtures and HTTP mocks:

```sh
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_embedding_profile.py tests/unit/test_embedding_cache.py tests/unit/test_ollama.py -q -W error
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_managed_profile_wiring.py tests/unit/test_query_session.py tests/unit/test_indexer.py -q
HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_managed_profile_wiring.py -q
.venv/bin/python -m ruff check src/hippo/knowledge/embedding_profile.py src/hippo/ollama.py tests/unit/test_embedding_profile.py
.venv/bin/python -m ruff format --check src/hippo/knowledge/embedding_profile.py src/hippo/ollama.py tests/unit/test_embedding_profile.py
```

Expected: all relevant assertions pass, no external model download or live application data access, and no claim that MockTransport proves immutable server execution. Optional real-Ollama integration uses an already installed test model and explicit opt-in; it validates installed API behavior without pulling, replacing or deleting models.

## Review checklist

- Resolver and adapter APIs are reviewed together with pipeline `BuildInputs` and query-session wiring before coding.
- Wire model names, canonical profile fingerprints, cache keys and generation identities remain distinct concepts.
- Every model/metadata call is outside store locks and inside the relevant authorization guard.
- Strict failure paths preserve the last published generation and never reinterpret legacy vectors.
- Cache primitive compatibility and existing legacy behavior are covered by regressions.
- Root records RED/GREEN and independent review evidence in the Task 5 gates before publication; this design alone completes no implementation gate.
