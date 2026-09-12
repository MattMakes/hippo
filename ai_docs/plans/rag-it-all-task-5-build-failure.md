# Controlled unpublished build failure

Implements the non-collecting failure transition required by §8 of the plain-prose coordinator plan. Root preflight checked `GenerationQueries._check_build`, `claim_generation_build`, strict publication and `SnapshotQueries.discard_generation`: discard also collects inventory, so it cannot express this operation.

Owned files: `store/generations.py`, `store/snapshots.py`, `tests/unit/test_generation_failure.py`, this plan and `ai_docs/gates/rag-it-all/task-5-build-failure/GATES.md`.

`fail_generation_build(generation_id, *, job_id, lease_owner, fencing_token, error_code="build_failed")` requires a live, exact staging/ready build holder under the existing source/authorization transaction lock. Closed codes `build_failed` and `build_cancelled` mark the job failed/cancelled respectively; both mark the unpublished generation failed. Refuse any published timestamp, active pointer or publication event. Clear only the verified holder's active-build pointer and advance content epoch in the same transaction. Return the terminal MaintenanceJob. Caller permission guards remain separate from build credentials.

Retain native rows, original records, memberships and seals. Never call collection or delete raw blobs. A subsequent explicit claim uses the existing failed-generation cleanup under a fresh fence. Expired/replaced/terminal holders cannot retry this mutation; recovery handles expired jobs. Publication receipts cannot be marked failed after release errors. No schema or production route change.

`recover_generation_builds(*, source_id=None)` adds an exact optional source filter before any generation mutation. Omitted scope preserves global maintenance behavior. A supplied scope must be a nonempty string; an unknown source is a harmless empty result. A source-authorized coordinator runs this operation inside its guarded source admission transaction; it cannot recover unrelated expired jobs. Live holders remain untouched. Four RED cases establish missing scope support before implementation; the unchanged RecoveryResult field is `failed_builds`.

Validation: first 13 cases failed because the operation was missing; after implementation, 55 focused Fake lifecycle/snapshot cases passed. Gates verify Fake, disposable Ladybug and regression behavior, including injected rollback after every mutation, both terminal outcomes, ready/staging inventory, stale fences and cleanup on a fresh claim. Root coordinates separate disposable Neo4j tests. Independent review required before publication.
