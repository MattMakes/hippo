# Task 5: captured OpenIE runtime

Status: implemented; independent SPEC/QUALITY PASS and all three runnable gates pass. Production ingestion remains legacy.

The plain-prose preparation API requires a chat runtime whose captured `OpenIEProfile` identifies the actual LLM, context size, prompts, parsing and inference options. `ProfiledEmbeddings.chat_json` verifies the embedding model and cannot provide that guarantee. Add a separate guarded adapter; preserve the existing Ollama client and legacy chat behavior.

## Ownership and interface

Own new `src/hippo/knowledge/openie_runtime.py`, new `tests/unit/test_openie_runtime.py`, and this plan and its gate ledger. Reuse the immutable `OpenIEProfile` from `prose_preparation.py`, existing model metadata selection helpers, `Ollama._request` retry guards, `parse_json_object` and the existing think-block removal semantics. Do not edit shared Ollama, preparation, context, projection or store modules without a separately reviewed need.

`resolve_openie_profile(ollama, *, authorization_check)` returns a frozen transport-bound `ResolvedOpenIEProfile` containing the safe profile, exact configured model spelling, endpoint/client identity and captured thinking capability. The safe profile alone is serializable; transport state is private and excluded from representation. A required callable authorization check brackets every local inspection and HTTP operation. Resolve fresh installed-model metadata, select one unambiguous canonical name/digest, fetch fresh show metadata and validate its capability array, and recheck installed identity afterward. Require an explicit list of unique nonempty capability strings containing `completion`; absent, null, malformed and embedding-only capabilities reject before any source-bearing call. No model installation or inference probe occurs.

`GuardedOpenIE(ollama, resolved, *, authorization_check)` exposes read-only `.profile`, `.validate()` and `.chat_json(messages, schema, *, max_tokens, request_guard)`. The constructor checks local identity without HTTP. `validate` brackets fresh installed-model metadata with authorization and configured model/context/client/endpoint checks, comparing exact selected name/digest to the captured values. Model replacement, client replacement, settings drift or revocation raises an explicit error. Recheck the failure latch after authorization and request callbacks, including callbacks that block while another worker fails. A failure permanently closes that adapter to further dispatch; it is scoped to one preparation operation.

The adapter builds an explicit chat request from captured values: model, context, temperature zero, no streaming, supplied bounded token cap/schema/messages, existing keep-alive policy, and `think=false` exactly when the captured model declares thinking. It does not use or mutate the shared mutable capability cache. Copy input containers before dispatch. Reuse `Ollama._request` with a composite guard before and after **every actual attempt**, including retries. The composite guard runs the caller's request guard and this adapter's live identity/authorization checks without recursion. Metadata requests have one attempt and carry no source text. Validation failures prevent further attempts; no automatic profile replacement.

Require the response model name to match the captured canonical model, remove think blocks and parse the JSON object with the existing parser, then perform final guards even on parsing or transport errors. Reject unsupported token limits and temperatures rather than silently changing captured extraction semantics. Both real NER and triple phases from `prepare_plain_prose` must run through this adapter in a MockTransport integration test.

Metadata bracketing detects observable replacement; it is not request-level digest attestation and cannot detect replace-and-restore races on an untrusted server. The existing local trusted Ollama assumption remains explicit. All resolver, validation and model operations run outside database transactions; the caller owns a live build lease and authorization heartbeat. This module neither persists a profile nor publishes a generation.

## Gates

- OR1: Resolver selects exact digest/name/context and supported capabilities; rejects malformed, absent, ambiguous, drifted and unauthorized identity. No source prompt is sent during resolution.
- OR2: Exact HTTP request semantics for NER/triples; response parsing compatibility; model mismatch, invalid response and post-call revocation fail. A stale shared capability cache cannot alter the captured request.
- OR3: Inject 5xx and connection failure, change digest/authorization between attempts, and assert no next source-bearing dispatch. Successful guarded retry preserves the captured body. Test late/background calls after failure and immutable profile/transport isolation.
- OR4: Actual plain-prose preparation uses the guarded adapter; existing embedding-profile and Ollama behavior remains green. All tests use MockTransport and fresh disposable fixtures; no application data or live model is required.
- OR5: Ruff and formatting pass; independent specification and quality review before publishing.

Write the runnable gate ledger before implementation, prove RED cases, then implement and reverify. Do not activate this adapter in production in this increment.
