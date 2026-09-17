# Compact selector implementation evidence

## Scope and pre-flight

Task 1 from `ai_docs/plans/2026-09-16-compact-selector-plan.md` is implemented. The change is confined to `Retriever.llm_select` and its new focused unit tests. It does not change prompt helpers, settings, model configuration, token budgets, store/cache code, authorization, the injected `SelectFn` contract, trace serialization, citations, or answer schemas.

The existing production wiring remains `_search` passing `retriever.llm_select` into retrieval. `llm_select` still makes one `chat_json` request with `CODE_SELECT_SCHEMA` and `max_tokens=512`; empty input still makes no request. `_select` still accepts durable passage IDs and applies its existing known-window filtering and failure fallback.

## Numbered requirements

1. **Ordered compact prompt IDs.** `src/hippo/hipporag/retriever.py:246-256` creates a mapping scoped to one call and sends ordered decimal strings beginning at `"1"`. `tests/unit/test_selector_candidate_ids.py:35-61` verifies the prompt order, absence of durable IDs from the prompt, unchanged schema and unchanged token budget.
2. **Exact durable-ID round trip.** `src/hippo/hipporag/retriever.py:259-270` translates keep/drop/expand values only through exact membership in that call's mapping. `tests/unit/test_selector_candidate_ids.py:47-50` verifies all three output lists and the preserved raw provider reply.
3. **Malformed, unknown and duplicate values are bounded.** `src/hippo/hipporag/retriever.py:259-268` rejects non-list fields, non-string items and unknown strings, then stable-deduplicates each translated list. `tests/unit/test_selector_candidate_ids.py:64-80` covers unknown IDs, non-string values, duplicate labels, near-matches (`"02"`, `" 1"`, `"2.0"`) and an attempted durable-ID fallback.
4. **Mappings never cross calls.** The mapping is a local variable rebuilt from the supplied candidate order at `src/hippo/hipporag/retriever.py:246`. `tests/unit/test_selector_candidate_ids.py:83-95` makes two calls with reversed candidates and proves local ID `"1"` resolves differently in each.
5. **Empty input is inert.** `src/hippo/hipporag/retriever.py:244-245` preserves the early return, and `tests/unit/test_selector_candidate_ids.py:98-104` proves no model call occurs.
6. **Preservation.** Existing retriever, ask and original-citation suites pass unchanged. No existing test was edited.

## RED evidence

Command:

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_selector_candidate_ids.py -q -o addopts='' -W error
```

Before the production change, exit 1: `3 failed, 1 passed in 0.04s`. The three semantic failures showed the missing behavior directly: results contained local values such as `['2', '1']` and `['1']`, and unknown/near-match strings were retained instead of translating only known local IDs. The empty-input control passed. Full output is in `/tmp/hippo-compact-selector-red.log`.

## GREEN and regression evidence

- Focused GREEN / G1, with warnings as errors:
  `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_selector_candidate_ids.py -q -o addopts='' -W error`
  — exit 0, `4 passed in 0.02s`; log `/tmp/hippo-compact-selector-g1-werror.log`.
- Exact G1 ledger command:
  `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_selector_candidate_ids.py -q -o addopts=''`
  — exit 0, `4 passed in 0.02s`; log `/tmp/hippo-compact-selector-g1.log`.
- Exact G2 ledger command:
  `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_retriever.py tests/unit/test_ask.py tests/unit/test_answer_original_citations.py -q -o addopts=''`
  — exit 0, `90 passed, 1 warning in 14.82s`; the warning is the known anyio `BlockingPortal` alias emitted by Starlette; log `/tmp/hippo-compact-selector-g2.log`.
- Stronger G2 run with warnings as errors and only the permitted exact anyio alias suppression:
  `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_retriever.py tests/unit/test_ask.py tests/unit/test_answer_original_citations.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning'`
  — exit 0, `90 passed in 14.68s`; log `/tmp/hippo-compact-selector-g2-werror.log`.
- Compile check:
  `.venv/bin/python -m compileall -q src/hippo/hipporag/retriever.py tests/unit/test_selector_candidate_ids.py`
  — exit 0; log `/tmp/hippo-compact-selector-compileall.log`.
- Ruff check on the production and test files — exit 0, `All checks passed!`; log `/tmp/hippo-compact-selector-ruff-check.log`.
- Ruff format check on the production and test files — exit 0, `2 files already formatted`; log `/tmp/hippo-compact-selector-ruff-format.log`.
- Ruff format check on this report — exit 0, `1 file already formatted`; log `/tmp/hippo-compact-selector-ruff-report.log`.
- Diff whitespace checks on the tracked source and both new files — exit 0 under the expected no-index-new-file status handling, with no diagnostics; log `/tmp/hippo-compact-selector-diff-check.log`.

G3 and the final commit remain orchestrator-owned. The orchestrator released this implementation only after reporting that the isolated replay and cold/warm profiles were terminal with exit 0; this worker did not run or inspect private-corpus/model evidence and makes no independent G3 quality claim.
