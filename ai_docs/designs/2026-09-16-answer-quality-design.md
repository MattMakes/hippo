# Measured answer completeness and compact selection

Final disposition, 2026-09-17: compact selection and bounded original evidence are retained. The initial proposal to replace the legacy QA instruction was superseded by the [optional dedicated QA design](2026-09-16-dedicated-qa-profile.md), which preserves the legacy default. The full evaluation produced 16/18 passes; the user explicitly accepted wrapping up with the two documented generation misses. The original all-case quality requirement below records the stricter initial target, not an achieved result. See the [final analysis](../reports/2026-09-16-performance-improvements.md) and [acceptance record](../reports/2026-09-17-performance-post-flight.md).

The original twelve-question evaluation was initially tallied as nine passes, two incomplete answers and one answer with unsupported additions. Later strict review also identified an omitted comparison detail in an initially accepted answer; the earlier tally is not proof of complete baseline quality. All five code-selector calls failed to produce valid complete JSON. The previous session's compact-ID probe completed all five requests in 0.83–0.97 seconds. That probe is evidence for testing the mechanism, not proof of final answer quality.

The user authorizes implementation experiments and their measured retention or rollback. No further approval pause is needed. The orchestrator makes design decisions; Codex workers execute bounded file-based tasks. No private corpus content belongs in committed tests or reports.

## First experiment: compact model-local candidate IDs

`Retriever.llm_select` will assign short decimal identifiers to the ordered candidates supplied in that call. It sends those identifiers to the existing prompt, then translates returned keep/drop/expand values through that call's exact mapping. Unknown IDs are discarded. Durable passage IDs remain the internal and public contract; injected select functions, trace decisions and citations keep their existing shape. Raw selector output remains the actual provider response for diagnosis.

Keep the existing token budget and fallback behavior for this first isolated experiment. Increasing output tokens alone still spends tokens copying opaque IDs, while changing the selector model would confound comparison and require new quality evidence. No additional model calls or dependency changes are needed.

## Second experiment: complete, grounded final answers

The existing QA system instruction requests a definitive answer without elaboration. Replace that instruction with one that answers every requested part, preserves named items and ordered steps when asked, uses only supplied evidence, distinguishes samples/snapshots from collection-wide or live claims, and explicitly states when evidence is missing. Keep the Thought/Answer parsing contract and response fields. This revises an earlier prompt-byte-identity design constraint under the user's explicit instruction to improve the observed deficient results.

Prompt changes alone do not prove code-chain completeness: the current five-passage context omits relevant implementation. After the compact selector replay, examine the exact selected context. If required evidence is still excluded, add a separate bounded evidence-selection experiment with its own design and authorization/citation tests. Do not hardcode evaluation questions or fabricate an answer from expected-output strings.

## Preservation and checks

- Every current authorization and provenance check stays in place; no ID mapping creates access.
- Only IDs supplied to a selector call can become decisions. Unknown, malformed and duplicate responses need explicit tests.
- Ranked passage order, fallback on model failure, injected selectors, trace serialization and citation identity stay compatible except for legitimate reranking from the now-working selector.
- No settings/model/service/credential change. Replay uses fresh copies and existing local models.
- Prompt-only quality changes need real-model evaluation; an assertion that prompt text changed is not evidence of improved answers.
- Require complete source-backed answers on all twelve original questions, including both abstentions and every previously omitted detail. Add held-out checks from captured source evidence before claiming success.
- Measure isolated runtime, selector completion/token counts, answers and citation evidence. Keep an experiment only when the full acceptance evidence supports it; otherwise roll back its own patch.

The original twelve questions and expected facts remain fixed. Full success requires the complete evaluation and relevant regression suites, not a passing subset.

## Bounded code evidence for answering

The saved Q3 trace proves that the required callee and initializer bodies are in the authorized graph but outside the five-passage answer slice. A working selector alone cannot guarantee coverage because it sees only a limited candidate window and previews. Add actual source passages for a bounded neighborhood of kept lexical code seeds when answering code questions. Preserve the ordinary ranked base slice; add at most the existing `code_expand_max` (capped at 10) distinct evidence passages and at most 6,000 extra text characters. Never truncate a passage into an apparently complete source; skip one that does not fit. `qa_top_k` continues to set the ranked base slice; the code neighborhood is explicit supplemental evidence.

Walk outgoing `INVOKES` edges above the existing `code_theta` for at most two hops, in deterministic seed/edge order. Include the seeds themselves if absent from the base slice. A named method can depend on receiver initialization, so also consider constructor/initializer methods of its immediate containing type, using only actual `CONTAINS` edges and conventional exact terminal names (`constructor`, `__init__`, `__new__`, `init`, `new`). Do not walk arbitrary sibling methods, callers, imported modules or low-confidence/unresolved guesses. Keep a fixed bound of 64 visited symbols even if the graph is large. Respect `code_expand_max=0` by adding nothing.

Every supplemental passage comes from the already authorized graph, resolves through the existing original-citation path, and appears in the returned retrieval/citation IDs because its full text was actually supplied to the model. The graph summary remains separate and has no fake citation ID. No additional inference or storage bypass is introduced. Existing `via_expand` rows are not automatically citations merely by being present; only passages explicitly selected as full-text evidence enter the citation bundle.

This trades a small bounded prompt increase for source coverage and keeps non-code questions unchanged except for the improved completeness/grounding instructions. Tests must prove deterministic bounds, cycles, hidden/unavailable vertices, confidence cutoff, unchanged base slice, full original-citation resolution and final authorization failure. Real-model grading decides whether to retain the experiment.

### Bound the resolved originals

Independent review identified that derived retrieval text can fan out into larger original citations. The supplemental budget therefore also applies after original-citation resolution: no more than `min(code_expand_max, 10)` novel original citations and 6,000 novel source-text characters beyond the unchanged base bundle. Resolve candidate groups once through the existing authorized resolver, then accept or skip each supplemental item with its complete original dependency group. Count shared originals once; do not truncate or partially admit a group. Later fitting groups remain eligible. Preserve resolver errors and authorization checks. The concrete correction and RED cases are in `ai_docs/handoffs/briefs/perf-answer-review-fixes.md`.
