# Independent review: bounded answer evidence

## Review scope

Static, read-only comparison against `4c22322` and the approved plan/design. I reviewed the final source and owned tests without reading the implementation report, running tests, invoking models, benchmarking, or changing source. Evidence below contains only repository-local synthetic/public identifiers.

## Verdict

**Specification verdict: FAIL.** The implementation does not enforce the 10-passage/6,000-character supplemental bounds on the text actually supplied to the answer model, and both authorized migrated tests use the production selector as their expected-value oracle instead of independently asserting exact source IDs. G3 remains pending and parent-owned; static review cannot establish answer-quality acceptance.

**Code-quality verdict: WARN.** The core walk is compact and most selection rules are expressed directly, but one test advertised as covering cycles never traverses an edge, and two nearby docstrings still describe the obsolete base-only answer slice.

## Sanitized evidence table

| Requirement | Evidence | Verdict |
|---|---|---|
| Base slice remains the first `qa_top_k` present, non-`via_expand` ranked passages | `src/hippo/hipporag/answer_context.py:19-27`; direct synthetic assertion at `tests/unit/test_answer_context.py:136-150` | PASS |
| Supplemental count is `code_expand_max`, clamped to 0..10, and zero disables extras | `src/hippo/hipporag/answer_context.py:29-34,107-109`; `tests/unit/test_answer_context.py:219-235` | PASS at retrieval-ID selection; FAIL after original-citation fan-out (F1) |
| Supplemental text is at most 6,000 characters and whole passages are skipped | Projected text is counted at `src/hippo/hipporag/answer_context.py:91-106`; actual model passages are resolved originals at `src/hippo/ask.py:143-145` and `src/hippo/knowledge/citations.py:123-143` | FAIL (F1) |
| Only kept, unambiguous lexical symbol seeds are eligible; dense/data/stale/mismatched seeds are excluded | `src/hippo/hipporag/answer_context.py:36-55`; `tests/unit/test_answer_context.py:199-216` | PASS |
| Seed bodies, qualifying outgoing callees through two hops, confidence threshold, callers/siblings excluded | `src/hippo/hipporag/answer_context.py:57-89`; expected list at `tests/unit/test_answer_context.py:153-196` | PASS |
| Initializers are named immediate children of actual type-like parents | Parent and child checks at `src/hippo/hipporag/answer_context.py:113-141`; repository metadata normalizes supported type-like symbols to `class` at `src/hippo/codegraph/model.py:56` and `src/hippo/hipporag/graph_index.py:112` | PASS |
| Walk is deterministic, cycle-safe, deduplicated, and visits at most 64 symbols | Stable seed/edge ordering and visited set at `src/hippo/hipporag/answer_context.py:36-89`; ID dedup at `src/hippo/hipporag/answer_context.py:93-109` | PASS by inspection; cycle regression is ineffective (F3) |
| Graph index access is safe for graphs produced by current loaders/scoping | Loader rejects absent endpoints at `src/hippo/hipporag/graph_index.py:534-540`; scoped graphs remap only retained endpoints at `src/hippo/hipporag/graph_index.py:911-925`; selector validates stale seed vertices at `src/hippo/hipporag/answer_context.py:45-49` and defining-passage vertices at `src/hippo/hipporag/answer_context.py:94-99` | PASS; no malformed-edge requirement invented |
| Supplemental retrieval IDs resolve through original citations and actual originals reach the model | `src/hippo/ask.py:143-147`; explicit original IDs/text assertion at `tests/unit/test_answer_context.py:266-302` | PASS, subject to F1 bounds |
| Live authorization surrounds citation resolution/model I/O/result release | Citation validation at `src/hippo/knowledge/citations.py:97-145`; model validation at `src/hippo/knowledge/query_access.py:58-72`; release checks at `src/hippo/ask.py:113-116,128-134`; revocation regression at `tests/unit/test_answer_context.py:305-321` | PASS by inspection |
| Prompt requests complete, ordered/named, evidence-only answers with snapshot/sample restraint and abstention | `src/hippo/prompts.py:319-325` | PASS structurally; quality is G3 and unproven here |
| Public response/trace shapes and Thought/Answer parsing remain unchanged | `Answer` fields remain at `src/hippo/hipporag/answerer.py:21-28`; parser call remains at `src/hippo/hipporag/answerer.py:45-51`; new helper only changes retrieval-ID selection at `src/hippo/ask.py:137-147` | PASS |
| Authorized test migrations independently pin exact expected source IDs | Both migrations derive `expected` by calling the implementation under test at `tests/unit/test_ask.py:192-198` and `tests/unit/test_retriever.py:950-964` | FAIL (F2) |
| G3 real-model quality evidence | Gate remains explicitly pending in `ai_docs/gates/answer-evidence/GATES.md` | NOT PROVEN; parent-owned |

## Concrete findings

### F1 — Important — Bounds are applied before original-citation fan-out, not to model input

**Fail case.** A qualifying supplemental retrieval passage can have very short projected text but resolve to one original longer than 6,000 characters, or to more than ten original spans. Selection admits it because `len(passage.text)` and the retrieval-ID counter fit (`src/hippo/hipporag/answer_context.py:91-109`). `resolve_citations` then expands every `original_span_id` into model passages (`src/hippo/knowledge/citations.py:123-143`), and `_answer_from_trace` supplies those originals (`src/hippo/ask.py:143-145`). The actual supplemental prompt can therefore exceed both explicit bounds.

**Smallest justified correction.** Budget supplemental candidates using the deduplicated original citations that would actually be appended to the model context, while leaving the base slice unbounded by the supplemental budget. Admit a retrieval ID only when all newly introduced original passages keep both the configured/capped passage count and 6,000-character total within bounds; never truncate an original. Preserve retrieval-ID ordering and the existing resolver/authorization path.

**Meaningful regression.** Build one synthetic managed supplemental retrieval passage whose projected text is one character and whose lineage resolves (a) to a 6,001-character original and (b) to eleven distinct originals. Assert those candidates are skipped (or otherwise that the actual supplemental model passages remain at most ten and 6,000 characters), not merely that selected retrieval rows satisfy the pre-resolution limit. Also cover deduplication when a base and supplemental retrieval ID share an original.

### F2 — Important — Both authorized migrations use a self-confirming oracle

`test_the_block_rides_in_as_a_pseudo_passage_and_is_never_cited` assigns `expected = select_answer_passage_ids(graph, trace)` and compares the answer to it (`tests/unit/test_ask.py:192-200`). `test_via_expand_passage_selected_as_full_text_evidence_is_cited` does the same (`tests/unit/test_retriever.py:950-966`). These checks prove wiring and full-text inclusion, but an erroneous selector that adds the wrong sibling/caller or omits the intended callee changes both actual and expected identically. This directly violates the authorized migration's requirement for exact, meaningful expected source IDs.

**Smallest justified correction.** In each migrated fixture, derive or declare the exact expected base and supplemental passage IDs from stable fixture facts/symbol identities without calling `select_answer_passage_ids`; assert the complete ordered `retrieval_passage_ids` list and exact original `passage_ids` list. Keep the present prompt-text and pseudo-passage assertions as secondary checks.

**Meaningful regression.** The expected list must name the fixture's intended seed, initializer, and eligible callees and exclude an available sibling/caller/low-confidence target. A mutation that broadens or narrows the selector must fail the migrated test even if answer wiring still mirrors the selector.

### F3 — Minor — The named cycle/order test never executes the graph walk

`test_symbol_visit_bound_cycles_order_and_passage_deduplication` seeds all 70 symbols (`tests/unit/test_answer_context.py:238-255`). The selector fills `visited` to 64 while reading seeds and breaks (`src/hippo/hipporag/answer_context.py:36-55`); its traversal loop requires `len(visited) < 64` (`src/hippo/hipporag/answer_context.py:67`). Consequently none of the cycle or edge-order relations in that test is examined. The test does cover the seed visit cap, deterministic repeated output, and passage deduplication, but not the cycle behavior claimed by its name.

**Smallest justified correction.** Keep the current case as a visit-cap/dedup test and add a focused one-seed graph with an in-bound cycle plus at least two qualifying outgoing edges inserted in noncanonical order. Assert exact output order and termination.

### F4 — Minor — Answer-slice documentation is stale

`src/hippo/ask.py:110` still says the model reads only the top `qa_top_k` passages, and `src/hippo/hipporag/answerer.py:35` says its input was already cut to `qa_top_k`. The final path now appends supplemental evidence. This does not alter runtime behavior but is misleading at the changed contract boundary.

**Smallest justified correction.** Describe the input as the ranked base slice plus bounded supplemental code evidence; keep the citation/pseudo-passage explanation unchanged.

## Acceptance statement

No final acceptance claim is justified. F1 and F2 are specification failures, and G3 cannot be passed by static review. The remaining bounded-walk, provenance, authorization, initializer-parent, prompt-contract, and public-shape checks pass by source inspection only.
