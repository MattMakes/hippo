# Compact selector review and real-model probe

## Verdict

**PASS.** Task 1 matches the compact-selector plan. I found no correctness, contract, fallback, authorization, or maintainability defect in the reviewed change. No stylistic changes are recommended.

This is an independent spec review of the working-tree change against base commit `4c22322`. I did not read `ai_docs/reports/2026-09-16-compact-selector-implementation.md`. Per the task brief, I ran no tests, benchmarks, or model calls.

## Requirement evidence

| Requirement | Evidence | Verdict |
|---|---|---|
| Prompt candidates use ordered short decimal IDs beginning at 1. | `src/hippo/hipporag/retriever.py:246-257` builds a local `{"1": durable_id, ...}` map and sends the enumerated decimal strings to the existing prompt helper. `tests/unit/test_selector_candidate_ids.py:35-61` asserts the exact prompt labels and absence of the durable IDs. | PASS |
| Returned keep/drop/expand values translate to the exact supplied durable IDs. | `src/hippo/hipporag/retriever.py:259-270` looks up each string directly in the local map and returns mapped durable IDs. `tests/unit/test_selector_candidate_ids.py:35-50` covers all three lists. | PASS |
| Unknown, malformed, fuzzy, and durable-ID fallback values cannot create output IDs. | `src/hippo/hipporag/retriever.py:260-267` rejects non-lists, non-strings, and strings absent from the exact map. `tests/unit/test_selector_candidate_ids.py:64-80` covers unknown strings, non-string values, padded/numeric variants, and a durable ID supplied by the provider. | PASS |
| Output order is deterministic and duplicates are removed stably. | `src/hippo/hipporag/retriever.py:263-268` walks provider order and appends only the first mapped occurrence within each decision list. The expected order and duplicate removal are asserted at `tests/unit/test_selector_candidate_ids.py:64-80`. | PASS |
| Mapping lifetime is one call and follows that call's candidate order. | The map is a local variable created on every invocation at `src/hippo/hipporag/retriever.py:246`. `tests/unit/test_selector_candidate_ids.py:83-95` makes two calls with reversed order and proves label `1` resolves independently. | PASS |
| Empty input makes no model request. | The pre-existing early return remains at `src/hippo/hipporag/retriever.py:244-245`; `tests/unit/test_selector_candidate_ids.py:98-104` verifies no call. | PASS |
| Raw provider reply remains available. | `src/hippo/hipporag/retriever.py:270` preserves `raw=str(reply)`. It is asserted at `tests/unit/test_selector_candidate_ids.py:50,80`. Raw text truthfully contains local labels, as allowed by the plan. | PASS |
| Existing failure fallback remains keep-all. | The production change is confined to `llm_select`. `_select` still catches selector exceptions, records the error, and returns without changing passages at `src/hippo/hipporag/retriever.py:689-698`; the existing behavior is specified by `tests/unit/test_retriever.py:904-912`. | PASS |
| Injected selectors and selector gating remain unchanged. | `retrieve` still calls only an explicitly supplied `select_fn` under the existing code-seed/settings gate at `src/hippo/hipporag/retriever.py:520-524`; `_search` still installs `retriever.llm_select` at `src/hippo/ask.py:84-95`. Existing injected-selector coverage is at `tests/unit/test_retriever.py:802-870`. | PASS |
| Durable trace/output contract and serialization remain unchanged. | No dataclass, `_select`, or `trace_from_dict` shape changed. `_select` receives durable IDs from `llm_select` and writes them to `trace.select` at `src/hippo/hipporag/retriever.py:689-709`. Existing round-trip coverage is at `tests/unit/test_retriever.py:873-891,992-1000`. | PASS |
| Token budget, prompt schema/helper, and request count remain compatible. | The single `chat_json` call still uses `prompts.CODE_SELECT_SCHEMA` and `max_tokens=512` at `src/hippo/hipporag/retriever.py:247-257`, identical to `4c22322`. The focused test asserts both at `tests/unit/test_selector_candidate_ids.py:51-54`. No new request is introduced. | PASS |
| Authorization and memory bounds are preserved. | The mapping is created only from the already-authorized ranked window passed into `llm_select`; it performs no store read and cannot introduce an ID outside that exact list. Its size is bounded by the existing selector window. | PASS |

## Code-quality assessment

The implementation is appropriately local and direct. The nested `pick` function makes exact membership, type rejection, provider-order preservation, and stable deduplication visible in one place. The list-based duplicate check is quadratic in the number of accepted labels, but the input is the existing small bounded selector window, so replacing it with more state would not be a concrete improvement here.

The focused tests cover the behavioral risks introduced by the mapping. The unchanged broader retriever tests remain the evidence for fallback, injected functions, gating, and stored-trace compatibility. `git diff --check 4c22322 -- src/hippo/hipporag/retriever.py tests/unit/test_selector_candidate_ids.py` reported no whitespace errors (the new test is untracked, so its content was also reviewed directly).

## Prepared provider probe

Runnable harness:

`/private/tmp/hippo-selector-check-0pajYv/probe_selector.py`

It loads Q1/Q2/Q3/Q4/Q11 from the captured private results, constructs `RankedPassage` objects from each case's first ten saved trace passages, and invokes the actual production `Retriever.llm_select`. It uses `load_config()` and the production `Ollama` client; no database is opened. A recording HTTP client captures the provider response without copying the selector's mapping logic.

For every case it records wall time plus `done_reason`, `eval_count`, and `prompt_eval_count`; checks that every translated durable ID belongs to that exact call's ten candidates; and privately records the full provider response, selector raw reply, candidate IDs, and complete translated decisions. Any exception, retry/error HTTP status, missing/incomplete provider completion, non-`stop` done reason, or membership violation makes the process exit nonzero. The HTTP client closes in `finally`.

Run exactly:

```bash
PYTHONPATH=src .venv/bin/python /private/tmp/hippo-selector-check-0pajYv/probe_selector.py
```

Expected outputs:

- `/private/tmp/hippo-selector-check-0pajYv/private-results.json` — mode 0600; contains private raw responses, candidate IDs, and complete translated decisions.
- `/private/tmp/hippo-selector-check-0pajYv/summary.json` — sanitized per-case timing, provider counters/reason, decision counts, membership status, and aggregate pass/fail.
- Standard output — one sanitized JSON summary line per case followed by both output paths.

The harness was syntax-checked only with:

```bash
.venv/bin/python -m py_compile /private/tmp/hippo-selector-check-0pajYv/probe_selector.py
```

No model/provider probe was executed.
