# Pre-flight report: Task 5A bitemporal evidence and deterministic conflicts

## Prerequisites

- Runtime discovery: PRESENT. Schema 5 temporal records, immutable update rules, authorization selection, strict generation publication, snapshot reachability, and both Fake/Ladybug transaction implementations were inspected.
- Local dev setup: PRESENT through the existing Task 0 and disposable-store fixtures.
- External dependencies: NONE for the pure increment. Store integration uses existing LadybugDB and root-reserved Neo4j contracts.

## Summary

Wiring: CLEAR for pure modules; RESERVED for integration. Behavioral: CLEAR. Contracts: CLEAR. Configuration: CLEAR. Domain: CLEAR. Credentials: CLEAR. Gate ledger: CLEAR after approval.

## Findings

- PASS — Wiring: `knowledge/model.py` already defines `TemporalRecord`, all selector variants, `HistoryManifest`, `ConflictSet`, and query snapshots. The pure modules can compile and classify those contracts without registration or storage changes.
- PASS — Behavioral preservation: current selection remains generation-first and authorization-first. The plan adds no temporal filtering to legacy/default routes during the pure increment.
- PASS — Contract: UTC normalization and basic interval rejection exist in Pydantic models. The plan adds explicit unknown/contextual behavior and half-open selector compilation without changing serialized version-one envelopes.
- PASS — Authorization: `EvidenceAccess` already distinguishes `current` from `history`; history ignores only `current_only` suppression while `all_history` still applies. The plan reuses this path and forbids a second policy implementation.
- PASS — Immutability: `store/knowledge.py` already permits only a one-time `recorded_to` closure on temporal rows. The planned batch primitive preserves this rule and adds atomic publication coordination rather than permitting generic mutation.
- PASS — Snapshot retention: `store/snapshots.py` already treats revisions reachable from a pinned `HistoryManifest` as collection roots. The integration plan extends validation/acquisition while preserving purge as an explicit override.
- PASS — Ordering: no generic provider token comparator exists. The plan requires adapter-declared monotonic ordering and explicitly rejects sorting ETags, Git SHAs, source timestamps, observed times, or recorded times as a substitute.
- PASS — Conflict semantics: the existing predicate registry contains no cardinality claim. The plan requires cardinality as typed adapter/configuration input rather than guessing from predicate names.
- PASS — Configuration and credentials: this work introduces neither connector credentials nor temporal defaults based on wall-clock timing. All tests inject fixed UTC instants.
- PASS — Ownership: the immediately executable increment owns only new temporal/conflict modules, tests, fixture, plan, ledger, and this report. Active dense and prose coordinator files are excluded.
- WARN — Integration ownership: model/access/snapshot/lifecycle/generation/store changes are required for full G18 and remain reserved. Their exact changes are listed in plan section 6 and must be released by root before editing.
- WARN — Backend completion: this worker may run Fake and Ladybug only after shared integration. Root owns the separately reserved Neo4j parity evidence.

## Gate ledger review

The ledger has unique IDs T5A1–T5A6, explicit ownership, deterministic commands, and no missing script dependency. T5A1/T5A2 are runnable after the new tests/modules are created. T5A3–T5A5 intentionally remain unmet until the shared integration files are released. T5A6 covers formatting and independent reviews; root records Neo4j evidence separately.

## Verdict: CLEAR FOR PURE INCREMENT

The pure temporal selector and conflict implementation can proceed with TDD. Full Task 5A remains held at the shared integration boundary, not because of a design gap, but because those files have active owners. No production route activation is authorized by this verdict.
