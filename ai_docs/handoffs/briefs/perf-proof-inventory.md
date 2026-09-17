# Implement raw read reuse within one proof

Fresh Codex Sol worker; no Claude/nested workers. Root `/Users/mascott/projects/hippo`, branch `rag-it-all-tibs`, measured base `4c22322`. Read the full plan `ai_docs/plans/2026-09-16-proof-inventory-reuse-plan.md`; its design decisions are fixed by the orchestrator. Use horch only for communication.

Implement Task1 with semantic RED/GREEN. Own only the four code/test files named in the plan and `ai_docs/reports/2026-09-16-proof-inventory-implementation.md`. Do not edit another plan/gate/report, retriever.py, prompts.py, ask.py, store decoder or native generation validation. No commit/stage/push, Neo4j, full suite, model requests or private-corpus benchmarks. Independent review/measurement is owned by the orchestrator.

Steps: extract all plan requirements; read actual raw/filtered lookup paths; write failing tests using existing fixtures; make the minimal private reader plumbing; prove G1/G2 on Ladybug and fake; run Ruff/compileall/diff checks; write requirement checklist plus RED/GREEN evidence and exact commands/counts/log paths. Do not infer new design choices or cache-lifetime changes. If plan cannot preserve a concrete current behavior, report evidence and wait.

No timing jobs currently run, so tests may begin immediately. Another worker edits only retriever.py and selector tests. Preserve all its changes. Persist your logs under `/tmp/hippo-proof-inventory-*`. Do not modify source repositories, original scratch data, production data or services.

When finished, send concise DONE via horch tell orchestrator, record horch done and close normally. If sandbox prevents ledger writes, use an available escalation; otherwise tell the orchestrator and retain evidence in your owned report. Do not change sandbox/trust settings. All code must remain uncommitted for the orchestrator's measured keep/rollback decision.

## Orchestrator review while G2 runs

The initial patch fetches exact/revision membership before `derived_capability` and source/failed-generation checks in `_Inventory.__init__`. Restore the original validation order: resolve generation, validate capability, get/check source and failed status, then fetch membership through the chosen reader. This avoids new reads/errors before an existing early refusal, especially for standalone validators. Preserve the existing `Unknown generation` error text where the injected raw reader returns none. Keep all existing checks; no broader design change. Record any added meaningful regression and the final tests affected by this correction.
