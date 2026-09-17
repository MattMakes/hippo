# Dedicated QA error-boundary independent review

Date: 2026-09-16

Review scope was limited to static inspection of `src/hippo/ollama.py`, `tests/unit/test_qa_profile.py`, the two original findings, the assigned architecture decision, and the implementer's final frozen declaration. No tests, models, application requests, network calls, database operations, corpus access, commits, or source edits were performed.

## Frozen-source verification

The implementer declared `SOURCE FROZEN` before this review. The final hashes recorded there matched the files at the start of review and matched again after review:

- `src/hippo/ollama.py`: `bf1aa2cd23fa94def7e3a37f999d8e6b412b967c268e4c3013eb71c393d79067`
- `tests/unit/test_qa_profile.py`: `9418afc2502820c658ed2ece9ad3f30e4a30455e169788d08860ec230170d77f`

No subsequent drift was observed.

## Verdicts

- Specification: **PASS** for the narrow QA error-boundary correction.
- Code quality: **PASS** for the narrow QA error-boundary correction.
- Remaining concrete defects: **none found** in the reviewed scope.

This verdict does not claim full-suite, live-model, quality, performance, corpus, or production fixed18 success. G3 remains parent-owned.

## Resolved findings

1. **Fresh capability failure is bounded at its origin.** `src/hippo/ollama.py:218-230` enables bounded errors for both the selected-model capability request and chat only when complete output is required. `src/hippo/ollama.py:336-360` forwards that private flag, rethrows bounded request failures instead of caching an empty capability set, and converts bounded capability JSON failures to a fixed response error. `src/hippo/ollama.py:362-431` applies fixed complete-answer errors only to HTTP/transport failures constructed by `_request`; the default remains `False`, preserving legacy caller messages, types, retry count, timeout handling, and backoff. The independent guarded and unguarded sentinel cases at `tests/unit/test_qa_profile.py:246-268` require the fixed error, exclude provider content, stop before chat, and therefore cover original finding 1. Invalid capability JSON stopping before chat is independently asserted at `tests/unit/test_qa_profile.py:271-286`.

2. **Typed guard/profile failures retain identity and public classification.** `src/hippo/ollama.py:224-236` completes `_request` before entering the response-JSON `ValueError` catch, so request-guard exceptions cannot be relabeled at the parse boundary. `src/hippo/ollama.py:338-359` likewise keeps capability parsing outside the request catch and uses a bare re-raise for `OllamaError`, preserving the same exception object. Guard dispatch remains before and after every actual request at `src/hippo/ollama.py:378-390`, including retries, while the existing wrappers retain final output checks. Exact caller-supplied `OllamaError`, subclass, `PermissionError`, and `ValueError` identity with zero provider requests is asserted at `tests/unit/test_qa_profile.py:289-326`. The real `ProfiledEmbeddings` plus `AuthorizedModel` fixture at `tests/unit/test_qa_profile.py:402-469` drives identity changes during chat and between retries; `tests/unit/test_qa_profile.py:504-533` requires the real `EmbeddingProfileChanged`, public `retrieval_rebuild_required`/409 mapping, and exactly one chat attempt. This resolves original finding 2 without a substitute exception.

## Preservation evidence

- The successful dedicated request body remains exact at `tests/unit/test_qa_profile.py:120-158`, including selected model, system/messages, capability-derived key, `min_p` as float `0.0`, and `seed` as integer `0`.
- Per-model capability caching without base-model mutation is asserted at `tests/unit/test_qa_profile.py:161-167`.
- Guard order across selected-model capability lookup, chat, retry, and release is asserted at `tests/unit/test_qa_profile.py:360-399`.
- Default request construction and prompt behavior remain explicitly asserted at `tests/unit/test_qa_profile.py:94-117`; no test assertion was removed or weakened by the narrow correction.
- Static diff inspection found no source, citation, or settings change attributable to this error-boundary correction beyond the assigned Ollama implementation and QA-profile tests.

## Coverage gaps and limits

- The exact-object guard test exercises failure before a cached-capability chat dispatch; the real profile tests independently cover post-dispatch chat and retry boundaries. There is no single parameterized test asserting the same synthetic exception object at every pre/post capability and chat guard position. Static control-flow inspection shows those guard calls remain outside provider transformation and JSON parsing catches.
- Bounded invalid capability JSON is covered, but malformed decoded capability shapes beyond a non-object payload are not exhaustively parameterized. No observed defect follows from the reviewed required cases.
- Configured ask/replay plus revocation is still not combined in one end-to-end test, and missing-QA readiness remains indirectly exercised, as recorded by the prior independent review. These remain lower-risk coverage gaps, not observed defects.
- Test results and RED/GREEN logs in the implementer's report were not rerun or independently validated because this assignment prohibited tests. This review makes no G3 or broader quality/performance claim.
