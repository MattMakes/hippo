# Reflection: performance and final-answer retention

## Summary

The retained work improved measured storage/proof overhead, selector completion and bounded evidence delivery, then added an opt-in final-QA profile. The final production evaluation completed normally and passed 16/18. The remaining failures were generation fidelity issues rather than missing source: one answer omitted supplied named groups and another changed an exact accented Unicode value. The user accepted those two limits and stopped optimization; the original strict gates remain visibly abandoned.

## What worked

- Profiling storage and proof construction before changing models found the dominant cost and produced large measured reductions without weakening fresh authorization or evidence validation.
- Compact per-call selector labels removed a concrete token-budget failure while exact membership mapping prevented invented durable identifiers.
- Bounded graph walks supplied complete original source under explicit hop, symbol, entry and character limits; resolver-based citation handling preserved authorization and lineage.
- Independent fixture oracles avoided making production selection code its own test oracle.
- Guard-origin error handling preserved the actual authorization/profile exception and its public classification instead of flattening every failure into a provider error.
- Controlled on-wire body checks established exact model, messages, options, numeric types and one-call behavior before the production evaluation.
- Fixed questions, frozen oracles and source-backed independent grading made incomplete and unsupported answers visible rather than allowing partial answers to pass.

## What was missed

### Explicit named-member omission

The source contained the required names, but the public answer omitted them. This is a quality/execution gap at generation time, not a retrieval gap. The acceptance rubric caught it; focused source and wiring tests could not.

Would a gate have caught it? Yes:

- `EXPECT: every explicitly requested named member supplied by authorized evidence appears in the public answer`
- `CHECK: run the frozen source-backed case and compare normalized named-entity coverage against the independent oracle`

### Exact Unicode value drift

The answer changed an accented character in a requested captured value. This is a generation-fidelity/domain-value gap. Semantic review that tolerates spelling variation is insufficient when the question asks for an exact value.

Would a gate have caught it? Yes:

- `EXPECT: exact captured values are byte-for-byte equal, allowing only canonical Unicode normalization explicitly listed by the oracle`
- `CHECK: normalize only under the frozen oracle policy, then compare UTF-8 values and report the first differing code point`

## Process lessons

- Separate retrieval evidence, answer completeness and unsupported-claim grading. A source-present case can still fail generation.
- Treat explicit lists, ordered procedures and exact values as structural obligations, not general semantic similarity.
- Record the origin of errors at the guard/provider/parser boundary so authorization failures retain identity and diagnostics remain private.
- Keep review criteria consistent across reruns. Q3's recheck showed why a stable semantic criterion and preserved prior rationale matter.
- Report aggregated rerun coverage honestly. Complete resolution of failed nodes is useful evidence, but it is not one green full-suite invocation.
- Preserve exact Unicode and named-entity coverage as first-class oracle fields in future acceptance harnesses.

## Future verification checks

Before any future 18/18 claim:

1. Confirm the question and oracle hashes are unchanged.
2. Confirm application source and selected model identities before and after the run.
3. Require a normal provider stop, nonempty final-only public content and one configured QA response per case.
4. Resolve every retrieval and citation identifier against the authorized export.
5. Grade requested subparts, list membership/order, exact Unicode values, abstentions and unsupported extra claims independently.
6. Preserve generic repository documentation; keep private names, excerpts and detailed corpus facts only in protected artifacts.

No global process defaults were changed during this closeout.
