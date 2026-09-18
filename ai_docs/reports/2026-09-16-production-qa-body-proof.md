# Production QA body equivalence proof

Status: **PASS**

This synthetic, no-inference proof drove all six accepted cases through production
`answer_question`, `AuthorizedModel`, `Ollama.chat_text` / `_chat`, and `httpx.MockTransport`.
No database, corpus, live model, testsuite, accepted-answer substitution, or app edit was used.

- Accepted input SHA-256: `c85ab431dab817a9bb5b1f0501c17344eb0c6f487d8a696af3c784a446ed6b0f`
- Generic system UTF-8 SHA-256: `623fc4c74b8e56ffbccd3dc1f8b077021b4377db875bf20618aa099f8e199df7`
- Configured base / QA / embedding: `qwen3:8b` / `qwen3.8:latest` / `nomic-embed-text`
- Base client remained unchanged: `true`
- Captured chats: `6`
- Authorization validations: `12`
- Command: `/Users/mascott/projects/hippo/.venv/bin/python /private/tmp/hippo-production-qa-body-proof-codex-sol-28/prove_body_equivalence.py --run`
- Terminal status: `0`

| Case | Outcome | Expected canonical JSON SHA-256 | Actual canonical JSON SHA-256 |
|---|---|---|---|
| Q1 | PASS | `f59e999c831edae264a96c01b9ef38fc65d3b0de74e6b39359971cc5d08597c2` | `f59e999c831edae264a96c01b9ef38fc65d3b0de74e6b39359971cc5d08597c2` |
| Q2 | PASS | `82fc2241c48e0bb654c2aa16f6e0cb92d73f0404a63374f5bf3185b3c3a1791f` | `82fc2241c48e0bb654c2aa16f6e0cb92d73f0404a63374f5bf3185b3c3a1791f` |
| Q3 | PASS | `6ba725ada2d92732437fb53ceaffc67891234c059a3694acc5d4dafa066efe9c` | `6ba725ada2d92732437fb53ceaffc67891234c059a3694acc5d4dafa066efe9c` |
| Q4 | PASS | `6286bc004c966c9e3c8d3b7b61d19f7ef8a32f041fbf0c2a327ea8ec7e8bfd43` | `6286bc004c966c9e3c8d3b7b61d19f7ef8a32f041fbf0c2a327ea8ec7e8bfd43` |
| Q5 | PASS | `6bf18d0e4f65ab671a2beb910a7d6ac8bc8568338d962449a2702894fbbdba32` | `6bf18d0e4f65ab671a2beb910a7d6ac8bc8568338d962449a2702894fbbdba32` |
| Q9 | PASS | `23a8d850ef06d183f6154b72e1e5ece6d971a1a1d92f0339f5677a81fbaf7d81` | `23a8d850ef06d183f6154b72e1e5ece6d971a1a1d92f0339f5677a81fbaf7d81` |

Semantic equality includes exact string equality. Canonical hashes are separate from
serialized wire-body hashes in the private 0600 report, avoiding key-order confusion.
Synthetic provider responses used nonempty final text and separate synthetic thinking;
`Answer.raw` and `Answer.answer` were final-only, with IDs and context preserved.

Source/import hashes and sanitized mismatch paths are in the private report. The mock
advertised completion/thinking and the captured request selected `qwen3.8:latest` with
`think=false`.
