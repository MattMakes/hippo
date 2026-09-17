# Compact selector candidate IDs

Design: `ai_docs/designs/2026-09-16-answer-quality-design.md`, first experiment only.
Gates: `ai_docs/gates/compact-selector/GATES.md`.
Goal: eliminate wasted selector output tokens without changing durable passage identity, authorization or error fallback.

## Task 0: environment

Use the root Python environment and FakeStore tests. Real replay uses the already captured private corpus, copied before opening, and the same qwen3:8b / nomic-embed-text models. No new dependency, credentials, configuration or services. Complete any earlier decoder timing before running tests or editing loaded source.

## Task 1: local candidate IDs

- [ ] complete
Gates: G1, G2, G3
OWNS: src/hippo/hipporag/retriever.py, tests/unit/test_selector_candidate_ids.py

1. Add focused tests for `Retriever.llm_select`: candidates have long durable IDs; the captured model prompt uses ordered short decimal strings beginning at 1; keep/drop/expand returns translate to the exact supplied durable IDs. Use a small recording fake model and synthetic RankedPassage fixtures.
2. Cover unknown strings, malformed nonstring items and duplicates without creating arbitrary IDs; empty input makes no model call; two calls with different candidate order cannot share mappings; raw provider reply remains available. Existing fallback, injected select functions and trace serialization remain unchanged. Avoid weakening existing tests to match the implementation.
3. Obtain semantic assertion RED against the current implementation. Implement the mapping only inside `llm_select`; do not modify global prompt helpers, model configuration or token budget. No extra model requests. Translate lists with exact mapping membership; no substring/fuzzy/durable-ID fallback. Preserve deterministic order. Stable deduplication of each translated list is appropriate.
4. Run focused and existing retriever/ask/citation tests on fake, Ruff, compileall and diff check. Record exact commands/counts/logs and RED assertions. The orchestrator runs G3 afterward on the same captured candidates and then fresh full-query cases before retaining the change.

## Pre-flight and preservation

The only production wiring is `_search` installing `Retriever.llm_select`, which calls the existing `code_select_messages` with local labels, returns durable SelectResult values, and then `_select` applies its existing known-window filter. All graph authorization checks remain unchanged. The external trace/answer schema and injected SelectFn contract do not change. Raw provider text may contain local labels because it truthfully records the provider response. Unknown IDs remain rejected. Model failure keeps the original ranking and records its error. Memory is bounded by the existing candidate window.

No external credentials, feature flags, endpoint or schema changes. Quality is judged on complete answers and correct citation evidence; successful compact JSON alone is insufficient for the overall goal. Q3/Q5/Q9 deficiencies are not silently declared fixed by this task.

## Closure under revised acceptance (2026-09-17)

The selector task is complete. Five production probes (Q1, Q2, Q3, Q4 and Q11) completed normally in 47-49 tokens with exact candidate membership, and those five cases passed the final fixed evaluation. Focused tests and independent review also passed. This closes compact-selector G3, but does not convert selector success into an 18/18 answer-quality claim: the retained end-to-end result is 16/18 under the user's revised scope, with Q8 and S4 limitations documented in the final quality review and post-flight report.
