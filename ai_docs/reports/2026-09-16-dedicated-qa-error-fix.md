# Dedicated QA error-boundary correction

Date: 2026-09-16

Scope: `src/hippo/ollama.py`, `tests/unit/test_qa_profile.py`, and the existing dedicated-QA gate ledger. No full suite, live model, network, corpus, database benchmark, commit, staging operation, or worker was used.

## Findings resolved

1. Fresh selected-model capability failures are now bounded at the provider/transport origin. Private `_request(..., bounded_errors=False)` preserves every legacy caller by default; complete QA passes `True` for both `/api/show` and `/api/chat`. In bounded mode, provider HTTP/transport text and the base URL do not enter the raised `OllamaError`. A failed bounded capability request is rethrown even without a guard and cannot fall back to an empty capability set. Invalid bounded capability JSON also stops before chat with a fixed response error.
2. Typed guard failures are no longer relabeled by `_chat`. The request returns before response JSON parsing begins, and only that separate JSON parse catches `ValueError`. Exact caller-supplied `OllamaError`, `OllamaError` subclass, `PermissionError`, and `ValueError` objects survive unchanged. Real transient `EmbeddingProfileChanged` failures from `ProfiledEmbeddings` wrapped by `AuthorizedModel`, both during chat and between retries, retain the public `retrieval_rebuild_required` / HTTP 409 classification and permit no answer or extra chat attempt.

Successful request construction was not changed. The existing exact default and dedicated-QA wire-body assertions pass, including selected model, messages, options, capability-derived `think`, and one-chat behavior. Legacy error behavior remains under the default-false path and the existing Ollama regression file passes.

## Test-first evidence

RED was captured before production edits:

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_qa_profile.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning' -k 'fresh_capability_http_error_at_its_origin or preserves_exact_guard_exception_and_makes_no_request or preserves_profile_change_and_public_rebuild_classification'
```

Result: exit 1; 5 failed, 3 passed, 30 deselected. Log: `/private/tmp/hippo-dedicated-qa-error-fix-red.log`.

The real profile fixture was then tightened to make the observed digest change transient, ensuring wrapper-final validation could not accidentally replace the wrongly relabeled exception. Its isolated RED was:

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_qa_profile.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning' -k 'preserves_profile_change_and_public_rebuild_classification'
```

Result: exit 1; 2 failed, 36 deselected. Log: `/private/tmp/hippo-dedicated-qa-error-fix-profile-red.log`.

Focused GREEN after the correction, including bounded invalid capability JSON:

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_qa_profile.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning' -k 'fresh_capability_http_error_at_its_origin or invalid_capability_json_without_chat or preserves_exact_guard_exception_and_makes_no_request or preserves_profile_change_and_public_rebuild_classification'
```

Result: exit 0; 9 passed, 30 deselected. Log: `/private/tmp/hippo-dedicated-qa-error-fix-focused-green.log`.

## Final gates and checks

The inspected gate runner was executed exactly as assigned:

```text
UNLAZY_APPROVAL_DIR=/private/tmp/hippo-gate-approvals node /Users/mascott/.agents/skills/dev-gates/scripts/gate-check.mjs --approve --reverify ai_docs/gates/dedicated-qa/GATES.md --root . --cwd . --timeout 600
```

- G1 PASS: 85 passed in 0.58s.
- G2 PASS: 430 passed in 35.40s.
- Aggregate exit 1 solely because manual production G3 remains pending, as required. No runnable gate failed.

Additional focused checks:

- `tests/unit/test_public_errors.py`: 94 passed in 0.06s with the fake-store environment.
- Ladybug-backed `tests/unit/test_qa_profile.py`: 39 passed in 2.36s.
- `ruff check`: passed for both owned Python files.
- `ruff format --check`: both owned Python files already formatted after the final formatting pass.
- `python -m compileall -q`: passed for both owned Python files.
- `git diff --check`: passed for the owned source, test, and gate files.

## Final hashes and limits

- `src/hippo/ollama.py`: `bf1aa2cd23fa94def7e3a37f999d8e6b412b967c268e4c3013eb71c393d79067`
- `tests/unit/test_qa_profile.py`: `9418afc2502820c658ed2ece9ad3f30e4a30455e169788d08860ec230170d77f`

G3 still requires the parent-owned isolated production fixed18 run and independent grading. Per the assignment, this correction did not run a full suite, live models, HTTP/network calls, a corpus, or a database benchmark. The `/private/tmp` logs are local ephemeral evidence; the decisive gate evidence is also recorded in `ai_docs/gates/dedicated-qa/GATES.md`.

SOURCE FROZEN. DONE. No source edits follow this signal.
