# Dedicated QA profile implementation

Task1 is implemented and verified. G1 and G2 pass; G3 remains pending and parent-owned. No real
model, benchmark corpus, production service, full suite, commit, stage, push, or worker was used.

## Requirements

| # | Requirement | Result |
|---|---|---|
| 1 | Preserve the default path | Empty `HIPPO_QA_MODEL` retains the committed four-message reference prompt, 1024-token cap, base model, parser, citations, and answer fields. The committed system-text SHA-256 is `99c1a269c82621a4e6ec0d7b97e11b1860876fa971e14dd402f5c164fac17fbb`. |
| 2 | Add one explicit profile | Nonempty `HIPPO_QA_MODEL` uses exactly two messages and one existing `chat_text` call with model override, 4096 tokens, temperature `0.0`, `top_p=0.95`, `top_k=20`, `min_p=0.0` as a float, seed `0` as an integer, and `require_complete=True`. |
| 3 | Use only the accepted generic system text | The results file SHA-256 is `c85ab431dab817a9bb5b1f0501c17344eb0c6f487d8a696af3c784a446ed6b0f`; each of its six candidate system messages independently hashes to `623fc4c74b8e56ffbccd3dc1f8b077021b4377db875bf20618aa099f8e199df7`. The repository constant has that same hash. No captured question, source, answer, or oracle was copied. |
| 4 | Preserve model and authorization lifetimes | The per-call model is local to `_chat`; `llm_model` is never mutated. Capability lookup and caching use the selected model. `AuthorizedModel` and `ProfiledEmbeddings` remain wrapped, forward the explicit keywords, validate before/after calls, and supply request guards across show, chat, retry, and output release. |
| 5 | Enforce complete public output | The profile requires provider `done is True`, `done_reason == "stop"`, and nonempty text content. HTTP/provider errors, malformed, truncated, empty-provider, and empty-after-`split_answer` output raise bounded generic `OllamaError`s without raw provider or source content. Native `message.thinking` is never returned. Legacy parsing is unchanged. |
| 6 | Wire ask and replay | `ask` and `answer_from_trace` pass `ctx.config.qa_model` through `_answer_from_trace` to `answer_question`; both nonempty paths reach the real HTTP adapter. Empty evidence still makes zero model calls. Retrieval, extraction, selection, evaluation judging, citation order, and source bounds remain on their existing paths. |
| 7 | Wire configuration and readiness | `Config`, environment loading, compose, and `AppContext.from_env` carry the optional value. Injected clients must already have the matching QA requirement. `required_models` adds a distinct QA model after base/embed and deduplicates bare versus `:latest` aliases, so status and pulls use the existing machinery. |
| 8 | Report roles accurately | CLI output distinguishes inherited default protocol from configured grounded QA. Settings normalizes only the trailing `:latest` alias and includes base, QA, and embedding roles independently, including same-base and QA/embed shared rows. |
| 9 | Document the opt-in and limits | README, FIDELITY, and `.env.example` describe the default reference path, direct profile controls, `qwen3.8:latest` example, memory/latency tradeoff, bounded source evidence, and pending full-18 retention decision. |

## Test-first evidence

The first comprehensive RED command, before production edits, was:

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_qa_profile.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning'
```

It produced `18 failed in 0.29s` in `/tmp/dedicated-qa-red.log`. The initial test-only
`AppContext.from_env` setup also exposed an unclosed Ladybug warning; the fixture was corrected to
use the supplied fake store before production work. A clean semantic RED then ran:

```text
HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_qa_profile.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning' -k 'default_system_prompt_is_the_committed_reference_text or profile_rejects_nonempty_provider_final'
```

It produced `2 failed, 17 deselected in 0.06s` in
`/tmp/dedicated-qa-behavior-red.log`: the legacy system text differed and a nonempty provider reply
whose parsed public answer was empty was incorrectly released. The focused suite reached GREEN at
`29 passed in 0.54s` after the final coverage additions.

A final source review found that an HTTP-layer error still carried the legacy response text into a
profile error. The synthetic sentinel regression failed `1 failed, 29 deselected in 0.23s`, showing
the private provider string, then passed `1 passed, 29 deselected in 0.20s` after the narrow
`require_complete`-only wrapper. Guard exceptions and default-profile errors remain unchanged.

The new `tests/unit/test_qa_profile.py` independently pins the legacy message roles/content hashes,
accepted grounded-system hash, exact wire object and numeric types. It covers environment
normalization, required/missing/pulled models, default/profile requests, selected-model capability
caches, thinking-capable and ordinary models, complete-response failures, one-call behavior,
ask/replay/empty evidence, injected-client matching, CLI labels, normalized rendered role labels,
and actual `AuthorizedModel` plus `ProfiledEmbeddings` denial/revocation before show, during show,
during chat, between retries, and at output release. `tests/fakes/fake_ollama.py` gained the provider's
faithful `done: true` field and direct final-only behavior for the explicit grounded instruction;
its legacy behavior is unchanged.

## Final verification

The inspected gate runner was invoked as authorized:

```text
UNLAZY_APPROVAL_DIR=/private/tmp/hippo-gate-approvals node /Users/mascott/.agents/skills/dev-gates/scripts/gate-check.mjs --reverify ai_docs/gates/dedicated-qa/GATES.md --root . --cwd . --timeout 600
```

Results recorded in `ai_docs/gates/dedicated-qa/GATES.md` and
`/tmp/dedicated-qa-gates-final2.log`:

- G1: exit 0, expectation matched, `76 passed in 0.64s`.
- G2: exit 0, expectation matched, `430 passed in 35.69s`.
- Aggregate: expected unmet status because manual G3 remains unchecked.

Focused Ladybug integration used no real model or corpus:

```text
HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_qa_profile.py tests/unit/test_answer_context.py tests/unit/test_answer_original_citations.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning'
```

Result: `54 passed in 9.44s`, logged at `/tmp/dedicated-qa-ladybug-final2.log`.

Static verification, limited to owned Python files, completed with:

```text
.venv/bin/ruff check src/hippo/config.py src/hippo/context.py src/hippo/ollama.py src/hippo/ask.py src/hippo/hipporag/answerer.py src/hippo/prompts.py src/hippo/cli.py tests/unit/test_qa_profile.py tests/fakes/fake_ollama.py
.venv/bin/ruff format --check src/hippo/config.py src/hippo/context.py src/hippo/ollama.py src/hippo/ask.py src/hippo/hipporag/answerer.py src/hippo/prompts.py src/hippo/cli.py tests/unit/test_qa_profile.py tests/fakes/fake_ollama.py
.venv/bin/python -m compileall -q src/hippo/config.py src/hippo/context.py src/hippo/ollama.py src/hippo/ask.py src/hippo/hipporag/answerer.py src/hippo/prompts.py src/hippo/cli.py tests/unit/test_qa_profile.py tests/fakes/fake_ollama.py
git diff --check
```

Ruff check passed, all nine files pass the format check, compileall exited 0, and `git diff --check`
exited 0 with no output.

## Final file hashes

```text
2d8dd7cbe4d243296915818aa1885a58ed7d5220326d9d166b53fa686eb2edef  src/hippo/config.py
206c0040cad9bd964ccfa75263281603bc588cb28211ac574051f2be8617da8d  src/hippo/context.py
32239a89439b9faa7341731a5f784063bfcf20e21b7c28c710df5708c410562c  src/hippo/ollama.py
838231f7885dcd0f417a6474cccbfae66d5cbebb28f6aa278b10596d857a5408  src/hippo/ask.py
7bc3a4bf78329e04e36715048a703aa48382dc6133534e013e1eb3aea504a52e  src/hippo/hipporag/answerer.py
329a18e26c37043b7dcad3174957320f68bec5551af4abf91629716e60cd0877  src/hippo/prompts.py
487a6bd1347ec0afb97bbb74ba2e42dd18fc270cb811fe55c8f1921cce57f6ea  src/hippo/cli.py
9c565d3da777c5244e2ab349f0d355337879cc0d76bf7912740d82f68f8e9d74  src/hippo/web/templates/settings.html
956227254a183221688186cc1b437ac3404bf4e0195a4f9c503a952d84a86d71  .env.example
a9e1f1ee5102a249616a91f4e2a1db0d746ee1d7cd86ac8477213c2488c87e05  docker-compose.yml
1101aee7df376a1f1b9a31af2dfebe57ca7973dbf9302c34e23a0677d4944bc9  README.md
796c37ed67154115056adf6d0b59ba10e21f45368a9949d715760e4b5da73820  docs/FIDELITY.md
46b2eecba71df5bb366769c314b0506d31f3b3709d178e782c1e56d4f1700493  tests/unit/test_qa_profile.py
5dcf503794edae97ab00d8c2f65a9d25b5f81626510beadcd157434cc0c24a40  tests/fakes/fake_ollama.py
b8dc7106791854aa486d96e0f91e35045d234b7cad5a6dc28c6a65a406b364bb  ai_docs/gates/dedicated-qa/GATES.md
```

## Limits and handoff

G3 is deliberately not claimed: the parent owns the production six-body proof, isolated full-18
run, independent grading/review, latency/model/digest reporting, retention decision, and final
commit. Fleet `horch note/tell` calls were attempted at RED and source-final milestones but the
managed filesystem denied both ledger locking and herdr pane IPC with `Operation not permitted`;
no trust setting or external state was changed.
