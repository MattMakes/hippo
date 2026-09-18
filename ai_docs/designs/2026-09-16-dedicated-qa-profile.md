# Optional dedicated QA profile

Final disposition, 2026-09-17: retained after the complete production evaluation passed 16/18 cases and the user explicitly accepted wrapping up with two documented generation misses. The original all-18 retention condition below was waived, not passed; see the [acceptance record](../reports/2026-09-17-performance-post-flight.md). The implemented interface and one-call profile remain as specified. Earlier native-mode candidates and later prompt/revision experiments are not retained.

Accepted generic system source: `/private/tmp/hippo-binding-resolution-qa-wzrTqG/results.json`, each `candidate.request.messages[0].content`, UTF-8 SHA-256 `623fc4c74b8e56ffbccd3dc1f8b077021b4377db875bf20618aa099f8e199df7`. Exact result file SHA-256 `c85ab431dab817a9bb5b1f0501c17344eb0c6f487d8a696af3c784a446ed6b0f`. Independent sanitized evidence: `ai_docs/reports/2026-09-16-binding-resolution-qa-review.md`. Copy only this generic system text, never captured questions or sources.

## Decision and evidence

Storage optimizations are accepted separately. The default 8B answer pipeline, stronger instructions, a multipart example, direct-answer formatting, native reasoning, one revision pass, and model-card sampling each failed fixed complete-answer criteria. The installed 27B model supplied required facts; the accepted direct-mode profile then passed the six fixed completeness and grounding checks. Increasing extraction/retrieval model size would spend inference time on calls that are already adequate. Keep those on the configured base LLM and allow an explicit final-answer model.

`HIPPO_QA_MODEL` is an optional empty-default setting. Empty preserves the existing answer protocol and base model. Nonempty enables the experimentally validated one-call grounded answer profile for that model. The example tested model is `qwen3.8:latest`; this does not guarantee quality for arbitrary models. No existing service environment, model installation, stored corpus or embedding profile is changed by implementation. The accepted profile, exact model and inference cost must be identified in evaluation and final reporting.

## Fixed interfaces

1. `Config.qa_model: str | None = None`; environment strips surrounding whitespace and normalizes empty to None. Document the opt-in and memory/latency tradeoff. Add compose pass-through with empty default and `.env.example` entry.
2. `Ollama(..., qa_model: str | None = None)` remembers the configured availability requirement. `required_models` adds distinct QA after the existing base/embed entries, deduplicating model aliases with the existing tag normalization. `AppContext.from_env` supplies the setting. Programmatically injected clients must be constructed with the same QA requirement; never temporarily mutate a shared client's `llm_model` or bypass wrappers.
3. Extend `chat_text` and private `_chat` with optional `model: str | None = None`, `top_p: float | None = None`, `top_k: int | None = None`, `min_p: float | None = None`, `seed: int | None = None`, and `require_complete: bool = False`. Existing defaults preserve wire behavior. `chat_json` retains its current API and defaults. Explicit sampling values, including zero, are sent when not None. No arbitrary dictionary can override model/context/budget or guards. No new think keyword is needed for the direct-mode candidate.
4. Capability lookup uses the selected per-call model and existing model-keyed cache. Preserve current behavior: thinking-capable models receive think=False; others omit that field. Both show and chat use existing request_guard handling. Existing wrappers already forward kwargs; retain their pre/post validations and retry/output-release checks. Do not enable native reasoning in this profile.
5. For require_complete, require provider done is True, done_reason is `stop`, and cleaned final message.content is nonempty text. Reject malformed/truncated/incomplete output with a clear bounded error; do not expose source/provider raw content in the error. Native message.thinking never enters final answer or Answer.thought. Default chat keeps legacy compatibility.
6. `answer_question(..., *, qa_model: str | None = None)` uses legacy qa_messages/1024 cap when absent. When present, exactly two messages: the accepted generic source-only system text and the unchanged final title/text/question content without the terminal `\nThought: ` suffix. One call: model=qa_model, max_tokens4096, temperature0, top_p.95, top_k20, min_p0, seed0, require_complete=True; the selected thinking-capable model receives the existing think=False control. Retain current Answer fields, existing parser, original citations/order and code graph placement. No refinement call or automatic fallback.
7. `ask` and `answer_from_trace` pass ctx.config.qa_model through `_answer_from_trace(..., *, qa_model=None)` to the answerer on the existing guarded query.model. Empty evidence remains zero model calls. Retrieval/extraction/selector/judging remain base model with current controls. Do not unwrap AuthorizedModel/ProfiledEmbeddings.
8. Settings must show accurate roles for base, QA and embedding, including a same-base-model explicit QA profile. CLI settings displays inherited vs configured QA. Readiness/pulls use required_models; no separate pulling implementation. The retrieval-only `evals/rag_all.py:evaluate` does not generate answers, contrary to an earlier census interpretation; do not add a false claim of a QA call there. Existing durable eval path calls answer_from_trace and therefore uses the profile, while its judge remains on the base client. Final private harness must explicitly record configured models, actual request model identities and installed model digests.
9. Roll back only the unsuccessful uncommitted legacy QA_SYSTEM wording to its committed HEAD version, preserving all unrelated prompt content. Add a distinct grounded system constant/helper for the opt-in profile. Update README/FIDELITY to distinguish default reference protocol from the explicit profile and bounded source evidence. Never alter fixed evaluation questions or oracles.

## Preservation and verification

| Contract | Required proof |
|---|---|
| Default requests | Existing chat_json/text tests plus exact default QA four-message body/1024 behavior |
| Profile requests | Actual six preserved QA requests driven through production chat_text, on-wire equality to accepted scratch requests; ignore only authorized surrounding capability calls |
| Shared model lifetime | QA override followed by base selector/judge call, proving no client mutation and correct separate capability caches |
| Authorization | Wrapper integration, fail before show/chat, revoke during chat/retry, deny output; no source leakage |
| Response | Normal stop returns final content only; native thought/empty/length/malformed cases rejected without fallback |
| Citations | One resolved bundle, deterministic original IDs and exact supplied source order, bounds unchanged |
| Availability/config | Empty/inherit/same/distinct alias cases, readiness and pull list, accurate settings roles |
| Quality/performance | Fresh full18 production ask run, fixed original12 plus frozen supplemental6; independent visible-answer grading and complete latency including model load/reasoning/proofs |

Use failing semantic/wire tests before implementation, then focused fake and Ladybug regressions and independent review. Six diagnostic successes alone permit integration work, not retention or a claim of100% quality. Commit only after the complete gate passes. No arbitrary prompt retry, case-specific hint, external oracle content or answer substitution is allowed.

## Review correction: error origin boundary

Independent review found that sanitizing an outer `OllamaError` catch both misses capability lookup and masks typed guard errors. Provider/transport failures must be bounded where `_request` constructs them, behind a default-false private flag. Complete QA forwards that flag through capability lookup and chat. Guard exceptions remain untouched; JSON parsing is caught only after the guarded request returns. Default error messages, retries and capability fallback remain compatible. This is an internal correction, not a new public profile option.
