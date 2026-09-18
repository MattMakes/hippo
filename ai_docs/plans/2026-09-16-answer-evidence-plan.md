# Complete answers with bounded source evidence

Design: `ai_docs/designs/2026-09-16-answer-quality-design.md`, sections Second experiment and Bounded code evidence.
Gates: `ai_docs/gates/answer-evidence/GATES.md`.
Goal: fix the observed missing call chain, omitted document names and unsupported snapshot/sample assertions without losing any original pass or abstention.

## Task 0: environment

Use the root `.venv`, fake unit fixtures and existing original-citation tests. No source corpus access or model calls are required for implementation. The orchestrator owns fresh copied-corpus evaluation with the same models. Credentials, services, databases, public API fields and stored schemas stay unchanged.

## Task 1: complete grounded QA plus bounded code evidence

- [ ] complete
Gates: G1, G2, G3
OWNS: src/hippo/ask.py, src/hippo/prompts.py, src/hippo/hipporag/answer_context.py, tests/unit/test_answer_context.py, tests/unit/test_ask.py, tests/unit/test_retriever.py

1. Read existing graph/path contracts, lexical seed kinds, code node names/kinds, CONTAINS/INVOKES direction, defining_passages, original-citation resolution, _answer_from_trace and answer_question. Implement the detailed selection algorithm from the design in a small `answer_context.py` helper returning ordered retrieval passage IDs. Base slice is unchanged (first non-via_expand qa_top_k present passages); extras are real full-text source passages from the same authorized graph. `ask.py` resolves base+extras together through the existing citation resolver. No direct raw-store reads or new model calls.
2. Use graph APIs rather than guessed metadata. For initializers, restrict parents to actual type-like nodes (class/struct/etc according to current graph metadata), then named immediate CONTAINS children. Do not add generic `new` functions from a module. If graph metadata cannot distinguish the required parent kind, report that concrete blocker before changing the design.
3. New synthetic tests must first RED on missing behavior: base selection unchanged, lexical-seed two-hop callees included, containing-type initializer included, no arbitrary sibling/caller or low-confidence edge, seed types/DENSE ambiguity respected, no code extras for prose/no lexical seeds, zero/entry/6,000-character/64-symbol/hop bounds, cycles/deterministic ordering/deduplication, and actual original-citation IDs in returned Answer. Reuse existing fixtures where possible. Do not create private benchmark-specific source fixtures or answer strings. Include a revocation-at-output integration assertion with the existing graph/query boundary.
4. Improve QA_SYSTEM per the design: concise but complete, every requested subpart, explicit ordered/named items, evidence-only claims, no sample-to-population or snapshot-to-live extrapolation, and clear abstention for missing evidence. Preserve existing Thought/Answer parsing, few-shot examples, function signatures and output fields. Do not add tests that merely assert prompt substrings; the orchestrator uses real-model evaluation for prompt quality.
5. Run new tests and existing test_ask.py, test_retriever.py, test_answer_original_citations.py, test_query_authorization_boundary.py, test_query_session.py, test_dense_session.py on fake. Run new/citation tests on Ladybug if their fixtures exercise stores. Run Ruff/compileall/diff check. Save complete RED/GREEN logs and exact counts. Do not weaken existing expected behavior to pass; if a deliberate revised citation behavior conflicts, report the case for orchestrator decision.
6. Report exact requirements and limits. Do not commit until independent review and all twelve real questions plus supplemental evidence checks pass. The orchestrator may refine or roll back this experiment if actual quality falls short.

Acceptance requires complete grounded Q3/Q5/Q9 and preservation of the other nine passes (including Q11/Q12), bounded source-backed additional context, stable public shapes, and live authorization before model calls and result release. Unit tests alone do not prove prompt quality. Quality results must not be silently relabeled partial-as-pass.

## Authorized migration of two obsolete citation assertions

The implementation reproduced two direct conflicts with the approved source-context design. The orchestrator explicitly authorizes updating only these old assumptions, preserving their real safety purpose:

- `test_ask.py::test_the_block_rides_in_as_a_pseudo_passage_and_is_never_cited`: continue proving the Code graph pseudo-passage never creates a citation; replace the exact-first-five assertion with exact expected real base plus explicitly selected source passage IDs, and prove their full text was supplied. Do not weaken this to an arbitrary subset/range.
- `test_retriever.py::test_expanded_passages_are_never_part_of_what_the_model_reads`: split the old blanket rule into the two real behaviors. A merely `via_expand` row is not automatically included (exercise no qualifying lexical walk or `code_expand_max=0` after expansion); a row independently selected as bounded full-text lexical evidence is included and cited as a real source. Add/retain exact assertions for both. Keep the expansion marking and ranking tests unchanged.

This is an intentional behavior change required by the new design, not a suppressed regression. Update relevant owned docstrings/comments. No other existing expected outcomes are authorized to change; report any further conflict.

## Closure under revised acceptance (2026-09-17)

The bounded evidence implementation, focused regressions and independent final review passed. The production fixed18 run supplied authorized source evidence for all cases and passed Q3, Q5, Q9 and the Q11/Q12 abstentions, but strict G3 did not pass: Q8 omitted three supplied names and S4 changed one accented Unicode value. The user explicitly ended further optimization and accepted retention at 16/18. Accordingly, the original G3 is recorded as abandoned rather than checked; a separate manual gate records the revised acceptance. The two misses remain future work, and neither the fixed questions nor their oracle was changed.
