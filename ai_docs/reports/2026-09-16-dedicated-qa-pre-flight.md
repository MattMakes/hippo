# Dedicated QA pre-flight

Verdict: clear for Task1 test-first implementation. G1/G2/G3 are pending implementation/runtime checks, not claimed passed. Candidate M independently passed six of six fixed diagnostic cases; full18 remains required.

Prerequisites: incremental Python change, not a rewrite; Task0 documents existing local tools and synthetic HTTP fixtures. External dependency matrix added to plan. No service startup or credential migration.

| Category | Verification | Result |
|---|---|---|
| A Wiring | Config/load_config to AppContext.from_env to Ollama; ask and answer_from_trace to answer_question; AuthorizedModel and ProfiledEmbeddings forward kwargs and preserve validation; model/status use required_models | Plan covers all seams |
| B Behavior | ollama.py chat_text/_chat/_request inspected against current source; legacy defaults, retry/guard/output checks, capability cache and citations preserved | Covered; tests pending |
| C Contracts | No route, auth policy, request schema or Answer field change; optional private/public Python keywords preserve prior calls | Covered |
| D Configuration | New empty-default HIPPO_QA_MODEL only; existing environment/endpoint/service/auth untouched; model availability and product labels included | Covered |
| E Domain | Accepted model/profile is explicit: direct mode,4096 cap,temp0,p.95,k20,min_p0,seed0; default1024/four messages retained; source budgets unchanged | Covered |
| F Credentials | Existing local Ollama endpoint has no new credential; graph credentials remain existing Config/open_store values and sources; no added secret or downgrade | No migration |
| G Gates | Parsed three unique gates; one task owns changes, no parallel ownership collision; exact G1/G2 commands read as code; Task1 creates missing test_qa_profile.py | Static PASS; dynamic approval/execution after tests exist |

Static references inspected: src/hippo/config.py:57, src/hippo/context.py:122, src/hippo/ask.py:102, src/hippo/hipporag/answerer.py:32, src/hippo/ollama.py:126, src/hippo/knowledge/query_access.py:44, src/hippo/knowledge/embedding_profile.py:448, src/hippo/status.py:277, src/hippo/model_manager.py:34, src/hippo/web/templates/settings.html:13, src/hippo/cli.py:619.

Gate status command returned three expected unmet gates with no parse errors. The approval command also executes tests, so its execution is sequenced after Task1 creates the required test file and records RED; there is no executable G3 shell oracle. No test/model run occurred in pre-flight.
