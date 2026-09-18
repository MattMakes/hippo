# Independent final review: bounded answer evidence correction

## Scope and verdict

This was a static, read-only review of the final source against `4c22322`, the approved design and plan, the correction brief, and the pre-fix review. I did not read the fix implementer's report, run tests, invoke models, benchmark, stage, commit, or modify source.

**Specification verdict: PASS for the implemented/static scope.** The bounded answer-context design and the specified correction are present. The ranked base behavior is preserved, the lexical source walk remains bounded, citation resolution occurs once, and supplemental admission is now based on the deduplicated original source actually supplied to QA. The four prior findings F1-F4 are resolved. No residual concrete defect was found in the reviewed scope.

**Code-quality verdict: PASS.** The correction is localized, continues to use the existing resolver and graph APIs, preserves authorization and lineage failures, and has focused independent regressions for the corrected behavior. Unrelated proof-inventory and compact-selector changes remain outside this review and were not modified.

**G3 remains PENDING.** Static inspection and unit-regression ledger evidence do not establish real-model answer quality. The fresh copied-corpus grading must still prove complete, grounded Q3/Q5/Q9 while preserving the other nine cases, including abstentions (`ai_docs/gates/answer-evidence/GATES.md:15-16`).

## Design and safety evidence

| Requirement | Final evidence | Verdict |
|---|---|---|
| Unchanged ranked base | `_base_answer_passage_ids` takes the first `qa_top_k` non-`via_expand` rows, ignores unavailable rows, and preserves order at `src/hippo/hipporag/answer_context.py:149-160`; the base is passed through without applying supplemental budgets at `src/hippo/hipporag/answer_context.py:109-119`. | PASS |
| Lexical walk bounds | Only kept, unambiguous, lexical symbol seeds are admitted at `src/hippo/hipporag/answer_context.py:30-49`; initializers are restricted to immediate `CONTAINS` children of class parents at `src/hippo/hipporag/answer_context.py:163-191`; outgoing `INVOKES` traversal is thresholded, two-hop, cycle-safe, deterministically sorted, and capped at 64 visited symbols at `src/hippo/hipporag/answer_context.py:51-83`. | PASS |
| Candidate passage bounds | Candidate retrieval passages remain whole, deduplicated, capped by `min(code_expand_max, 10)`, and constrained to 6,000 rendered characters at `src/hippo/hipporag/answer_context.py:85-104`. `code_expand_max=0` exits before any lexical supplement at `src/hippo/hipporag/answer_context.py:23-28`. | PASS |
| One resolver invocation | `select_answer_citations` forms base and candidate IDs, then calls the existing `resolve_citations` exactly once at `src/hippo/hipporag/answer_context.py:107-114`; `ask` consumes the returned bundle directly at `src/hippo/ask.py:136-145`. | PASS |
| Actual deduplicated original budget | The full base bundle initializes the seen-original set at `src/hippo/hipporag/answer_context.py:115-125`. Each supplemental item is charged only for original IDs not already seen, using resolved original text length, at `src/hippo/hipporag/answer_context.py:127-139`. The configured count is clamped to 0..10 and source text to 6,000 characters. | PASS |
| Whole-group skip and later admission | A group exceeding either original count or text budget is skipped with `continue`; later resolved items remain eligible at `src/hippo/hipporag/answer_context.py:127-139`. Only complete accepted items and their originals are rebuilt into the final bundle at `src/hippo/hipporag/answer_context.py:141-146`. | PASS |
| Exact retrieval/citation/model-text agreement | `_answer_from_trace` sends only `bundle.citations` to `answer_question` and publishes only `bundle.retrieval_passage_ids` at `src/hippo/ask.py:136-145`. Focused tests assert resolved-original IDs/text, oversized-group exclusion, exact-bound inclusion, later-group admission, stable citation order, and shared-original accounting at `tests/unit/test_answer_context.py:322-500`. | PASS |
| Authorization and lineage failures unchanged | The correction delegates all candidates to the existing resolver. That resolver validates authorization before and after, rejects unavailable retrieval items, missing managed lineage, and inconsistent originals at `src/hippo/knowledge/citations.py:97-145`. Final result release remains guarded at `src/hippo/ask.py:110-115,127-133`; post-model revocation coverage remains at `tests/unit/test_answer_context.py:503-519`. | PASS |
| No raw-store bypass | Selection uses only the held `GraphIndex`, graph edge/definition APIs, and validated `CitationBundle`; the answer path imports and calls no store API (`src/hippo/hipporag/answer_context.py:7-9,88-99,107-146`; `src/hippo/ask.py:136-145`). | PASS |
| Prompt and public contracts | The prompt now asks for every requested part, named/order preservation, evidence-only claims, sample/snapshot restraint, and explicit missing-evidence disclosure at `src/hippo/prompts.py:319-325`. Thought/Answer parsing and `Answer` fields remain unchanged at `src/hippo/hipporag/answerer.py:21-28,43-54`. | PASS statically; quality remains G3 |

## Prior finding dispositions

### F1 — Resolved

The former pre-resolution-only bound no longer controls final admission. All candidate retrieval IDs are resolved together once, base originals seed the deduplication set, and supplemental items are accepted only when their complete novel-original dependency group fits both the original-count and actual source-text budgets (`src/hippo/hipporag/answer_context.py:107-146`).

The regressions exercise a one-character rendered candidate expanding to a 6,001-character original or eleven originals and require its complete exclusion from retrieval IDs, citation IDs, and model messages (`tests/unit/test_answer_context.py:361-410`). Exact 10-original/6,000-character admission with an oversized base is covered at `tests/unit/test_answer_context.py:413-443`; skipped-large-then-later-small behavior and citation order at `tests/unit/test_answer_context.py:446-474`; base/shared-original zero-cost accounting at `tests/unit/test_answer_context.py:477-500`.

### F2 — Resolved

Neither authorized migrated test calls the production answer-context selector as its oracle. Both independently construct the intended seed and exact callees with stable fixture identity helpers, map those explicit symbols to their defining passages, and pin the complete ordered base-plus-extra result (`tests/unit/test_ask.py:188-217`; `tests/unit/test_retriever.py:949-978`). They also assert source text reaches the prompt, while the pseudo-passage remains uncited and `via_expand` alone remains insufficient.

### F3 — Resolved

The former 70-seed case is accurately named as visit-bound and passage-deduplication coverage (`tests/unit/test_answer_context.py:271-296`). A separate one-seed cycle has two qualifying outgoing edges inserted in reverse canonical order, cycles both targets back to the seed, and asserts exact stable, duplicate-free output (`tests/unit/test_answer_context.py:299-319`).

### F4 — Resolved

The `ask` contract now describes the ranked base plus bounded supplemental code evidence (`src/hippo/ask.py:100-115`), and `answer_question` describes the same ordered input (`src/hippo/hipporag/answerer.py:31-42`). README settings correctly distinguish the ranked `qa_top_k` base, `code_theta` call-walk cutoff, and `code_expand_max` supplemental cap/disable behavior (`README.md:350-363`). FIDELITY removes the obsolete same-prompt/never-cited claims and documents the changed grounding instruction, resolved-original limits, whole-group behavior, independent `via_expand` selection, and citation-free graph pseudo-passage (`docs/FIDELITY.md:87-96,240-263`).

## Residual findings and gate status

No residual concrete source, test-oracle, or documentation defect was found in the requested final-review scope. The acceptance ledger records G1 as 13 passing focused tests and G2 as 184 passing compatibility tests (`ai_docs/gates/answer-evidence/GATES.md:5-13`); those commands were not rerun in this review, as required.

G3 is still explicitly pending and parent-owned. A PASS here is therefore not a final answer-quality acceptance or merge claim.

## Worker communication note

`horch tell` successfully delivered the final verdict to the orchestrator. `horch note` attempts were intermittently blocked because the managed filesystem sandbox denied the shared ledger lock at `/Users/mascott/.local/state/horch/-Users-mascott-projects-hippo.json.lock`. Trust settings were not changed and no bypass was attempted.
