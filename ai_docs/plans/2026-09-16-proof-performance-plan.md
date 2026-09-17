# Proof Performance Implementation Plan

> **For Claude:** Use `/dev-execute` to implement this plan task-by-task.

**Goal:** Reduce repeated lineage storage reads while retaining all authorization boundaries.
**Architecture:** Per-inventory record reuse; one generation inventory for all selected views and prose during a proof. No cross-proof caches, no removal of validation calls.
**Gates:** ai_docs/gates/proof-performance/GATES.md
**Tech Stack:** Python, pytest, Ladybug, local Ollama.
**Wiring Manifest:** EvidenceAccess.build → _authorized_derivations → GenerationViews → _Inventory. Standalone validate_prose/view retain fresh inventories.
**Regression Hotspots:** Exact membership even after non-exact reads; version checks; generation mismatch; mutations between proof validations; private secondary inputs.

## Task 0: Local dev and auth setup

Already verified by the completed baseline and instrumented replay. Use `.venv/bin/python`, local Ollama at `http://localhost:11434`, qwen3:8b and nomic-embed-text. Copy the baseline scratch data directory before replay. Queries use internal EVERYTHING exactly as the baseline; ordinary-reader security is independently tested by pytest. No web server or credentials are needed for direct ask() benchmarking. Do not ingest again or edit original source repositories/notes/Mongo.

## External Dependencies

| Dependency | Verification | Credential |
|---|---|---|
| Embedded Ladybug | pytest store fixture + copied corpus | none |
| Ollama | existing baseline HTTP calls; replay with same models | none locally |

## Task 1: Reuse immutable lineage reads within a proof

- [ ] complete
Gates: G1, G2, G3
OWNS: src/hippo/knowledge/derivations.py, src/hippo/knowledge/access.py, tests/unit/test_derivation_read_reuse.py

Spec: A single generation inventory's record() method loads a given record at most once. Direct native/support-passage reads outside record() remain unchanged in this slice. Exact membership remains checked on every record() call. Expose prose validation through GenerationViews so views and prose in one proof share the inventory; standalone entry points stay fresh. Reject generation mismatch. Do not memoize arbitrary authorization decisions, change prompts, or modify unrelated files.

1. Read existing derivations/access implementation and fixtures. Add regression tests using real store fixture and existing world() builder. Instrument storage calls only for counting (no replacement data). Test reduced reads and fresh validation after corruption. Run new tests; capture expected failing assertion before production edits.
2. Add a per-_Inventory record map keyed by (kind, identity); enforce exact membership separately on every call. Share the per-generation inventory for prose and view validation. Keep every existing validation/error path. Inventory lifetime must not outlive a no-write validation pass.
3. Run G1/G2 and ruff on edited files. Add further tests for exact=False→exact=True and generation mismatch as needed. Report red/green evidence.
4. Parent runs one copied-corpus replay and broader regressions. Commit only after observed improvement and review; implementation agent must not commit before parent benchmark approval.

## Plan Verification Checklist

Run pre-flight before execution and post-flight after. The six preservation tables in `ai_docs/designs/2026-09-16-proof-performance-design.md` are incorporated verbatim by reference; every row belongs to Task 1. API contracts, credentials, models, expiry policies, source data and query selection remain unchanged. Later quality/retrieval experiments require their own failing cases and measurements.
