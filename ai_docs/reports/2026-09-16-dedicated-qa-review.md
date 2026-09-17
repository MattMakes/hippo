# Dedicated QA independent review

Recorded by the orchestrator from codex-sol-29's independent final review. Reviewed source: src/hippo/ollama.py SHA-256 `32239a89439b9faa7341731a5f784063bfcf20e21b7c28c710df5708c410562c`; all listed implementation hashes matched. No tests, model, database, or network calls were run by the reviewer.

Specification: FAIL. Code quality: FAIL. Two narrow failure-path corrections are required; full18 remains pending.

1. `ollama.py:216` calls selected-model capability lookup outside the complete-answer sanitizing boundary. With a production request guard, a failed `/api/show` rethrows provider text from `_request`. A fresh selected-model show-error sentinel test is required.
2. `ollama.py:220` catches every `OllamaError` from guarded chat, including `EmbeddingProfileChanged`. Replacing that subclass changes the public error mapping from rebuild-required to service-unavailable. Actual profile-change tests during chat and between retries must preserve the exception and public classification.

All other numbered design requirements passed static review: optional configuration, default compatibility, per-call model/capability cache, exact system and sampling, one-call ask/replay and empty evidence, original citations/budgets, model readiness consumers, aliases, and product documentation.

Lower-risk coverage gaps were recorded separately: configured ask/replay with revocation is not combined in one test (wrappers and entry points are independently covered), and missing-QA status readiness is indirectly exercised. These are not observed defects.
