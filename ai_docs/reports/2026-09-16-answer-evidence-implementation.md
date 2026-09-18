# Answer evidence implementation report

## Scope and requirements

Implemented the approved experiment without model, service, schema, credential, public response-shape, or raw-store changes.

- Preserve the ordinary answer base as the first `qa_top_k` non-`via_expand` trace rows, with unavailable passages skipped after that slice.
- Add supplemental full-text passages only for kept, unambiguous lexical symbol seeds. Dense, data, ambiguous, unkept, stale, and mismatched seeds add nothing.
- Include seed definitions, outgoing `INVOKES` callees at `omega >= code_theta` for at most two hops, and conventional initializer methods (`constructor`, `__init__`, `__new__`, `init`, `new`) that are immediate `CONTAINS` children of an actual `class` parent of a named method.
- Never walk callers, arbitrary siblings, module-level `new` functions, low-confidence edges, or a third call hop.
- Traverse deterministically, deduplicate vertices and passages, visit at most 64 symbols, add at most `min(code_expand_max, 10)` passages, add nothing at zero, and supply at most 6,000 supplemental text characters. Oversize passages are skipped whole rather than truncated.
- Resolve base and supplemental retrieval IDs together through immutable original-citation resolution; the Code graph summary remains an uncited pseudo-passage.
- Preserve live authorization checks before model work and result release.
- Instruct QA to answer every requested part, preserve explicit names/order, avoid sample-to-population and snapshot-to-live extrapolation, stay within evidence, and clearly abstain where evidence is missing while preserving `Thought:` / `Answer:` parsing.

## Implementation evidence

- `src/hippo/hipporag/answer_context.py:10-14` defines the fixed 10-passage, 6,000-character, 64-symbol, and two-hop rails plus exact initializer names.
- `src/hippo/hipporag/answer_context.py:17-110` preserves the ranked base, gates on lexical symbols, walks deterministic outgoing calls, and selects only complete deduplicated defining passages within both budgets.
- `src/hippo/hipporag/answer_context.py:113-141` finds initializers only through incoming parent-to-child `CONTAINS` edges whose parent metadata is `code_kind == "class"`, then immediate method children. Supported language extractors normalize class/struct/interface/record/enum/trait type-like declarations to that metadata.
- `src/hippo/ask.py:137-147` resolves the helper's ordered retrieval IDs in one call to the existing citation resolver, supplies exact original text to the answer model, and records retrieval IDs separately from returned original citation IDs.
- `src/hippo/prompts.py:319-325` implements the complete, evidence-only QA instruction without changing the one-shot examples, parser, signatures, or output fields.
- `tests/unit/test_answer_context.py:136-320` uses synthetic public graph fixtures to cover the unchanged base, lexical gates, two-hop calls, initializer containment, excluded callers/siblings/low-confidence/third-hop edges, zero/entry/character/visited-symbol bounds, cycles, determinism, deduplication, unavailable vertices, original citation IDs/text, and post-model revocation.

## Authorized citation-test migration

Before migration, the prescribed fake regression run produced 188 passes and exactly two failures in `/tmp/hippo-answer-evidence-green-fake-detail.log`:

- `test_ask.py::test_the_block_rides_in_as_a_pseudo_passage_and_is_never_cited` required citations to equal only the first five ranked rows.
- `test_retriever.py::test_expanded_passages_are_never_part_of_what_the_model_reads` excluded a row even when the new lexical graph walk independently selected its complete source text.

The orchestrator authorized migration of only those assumptions. `tests/unit/test_ask.py:188-202` now proves exact base-plus-supplement retrieval IDs, complete prompt text, real passage identities, and no pseudo-passage citation. `tests/unit/test_retriever.py:933-966` separately proves that a merely `via_expand` row is excluded when supplemental evidence is disabled and that an independently selected full-text source is included in the prompt and citation IDs. Expansion marking and ranking tests were unchanged.

## Verification evidence

- RED: `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_answer_context.py -q` failed during collection because the new helper did not exist. Complete log: `/tmp/hippo-answer-evidence-red.log`.
- G1: `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_answer_context.py -q -o addopts=''` passed 7 tests. Log: `/tmp/hippo-answer-evidence-g1.log`.
- G2: `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_ask.py tests/unit/test_retriever.py tests/unit/test_answer_original_citations.py tests/unit/test_query_authorization_boundary.py tests/unit/test_query_session.py tests/unit/test_dense_session.py -q -o addopts=''` passed 184 tests with one existing Starlette deprecation warning. Log: `/tmp/hippo-answer-evidence-g2.log`.
- Combined fake run: `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_answer_context.py tests/unit/test_ask.py tests/unit/test_retriever.py tests/unit/test_answer_original_citations.py tests/unit/test_query_authorization_boundary.py tests/unit/test_query_session.py tests/unit/test_dense_session.py -q -o addopts=''` passed 191 tests with one existing Starlette deprecation warning. Log: `/tmp/hippo-answer-evidence-green-fake.log`.
- Ladybug: `HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_answer_context.py tests/unit/test_answer_original_citations.py -q -o addopts=''` passed 18 tests with the same warning. Log: `/tmp/hippo-answer-evidence-green-ladybug.log`.
- Ruff: `.venv/bin/ruff check src/hippo/ask.py src/hippo/prompts.py src/hippo/hipporag/answer_context.py tests/unit/test_answer_context.py tests/unit/test_ask.py tests/unit/test_retriever.py` passed. Log: `/tmp/hippo-answer-evidence-ruff.log`.
- Compile: `.venv/bin/python -m compileall -q` over the six owned Python files passed. Log: `/tmp/hippo-answer-evidence-compileall.log`.
- Whitespace: `git diff --check` over changed tracked files passed, and an `rg` trailing-whitespace scan over all owned files plus this report found no matches. Logs: `/tmp/hippo-answer-evidence-diff-check.log` and `/tmp/hippo-answer-evidence-trailing-whitespace.log`.

G1 and G2 have runnable passing evidence. G3 is intentionally pending orchestrator-owned fresh copied-corpus real-model grading of all twelve original questions plus supplemental evidence checks. Unit tests do not establish Q3/Q5/Q9 answer quality or authorize retention/commit.
