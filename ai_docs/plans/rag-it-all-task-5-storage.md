# Task 5 storage contract proposal

Status: approved storage implementation contract after root review; implementation is starting. Task 5 remains incomplete. The root agent owns snapshot/context/query/projection/pipeline integration. This document defines the bounded storage slice and records the remaining integration decisions.

The governing scope is `docs/rag_it_all.md` Task 5, sections 7.2, 7.3 and 10. Task 5A adds controlled recorded-time closure; Task 9 adds the maintenance scheduler and cross-source dependency orchestration. Neither is implemented here.

## Existing foundation

- `store/generations.py::publish_generation` provides a transaction, source lock, expected-parent CAS, ready-manifest check, idempotent active publication receipt and pointer/version/event failpoints.
- `MaintenanceJob(kind="rebuild")` already carries source, expected parent, phase, lease owner/expiry, fencing token, attempt counter, input fingerprint and status.
- `GenerationMember` currently pins raw artifact revisions only. `NativeBinding` is generation-specific. `QuerySnapshot` is workspace-specific and contains source-generation selections and retrieval/policy fingerprints.
- Passage generation/revision/span/profile columns exist, but passage writers do not consistently preserve them. Symbol/DataObject/Commit generation columns are absent.
- All managed record insertions and updates currently bump `authorization_epoch`. Publication also bumps that epoch. This must change without weakening current revocation checks.
- Schema 3 is published. Its exact descriptor/checksum and migration steps must be frozen before deriving schema 4 from the expanded models.

## Ownership

Storage owner: `src/hippo/store/{generations,knowledge,migrations,memory,code,ladybug}.py`, store registration, `knowledge/model.py`, the relevant FakeStore methods and storage tests. A separate `store/snapshots.py` mixin is appropriate if it keeps `generations.py` readable; registration remains this owner's responsibility.

Root: `knowledge/{snapshots,access,projection,lifecycle}.py`, `context.py`, query/answer/eval/transport callers and pipeline dispatch. The extraction agent owns codegraph IDs. Storage uses that agent's namespace helper and must not duplicate its formula.

All new operations are internal service APIs. Public `get/list_knowledge` must continue withholding control records. A snapshot or lease is not an access grant.

## Schema 4

### Source columns

Add:

| Field | Type | Meaning |
| --- | --- | --- |
| `managed` | BOOLEAN, default false | Explicit managed/legacy dispatch boundary; entering managed mode invalidates previously authorized legacy views |
| `active_build_id` | STRING, nullable | Current source-wide build lease's MaintenanceJob ID |
| `build_fencing_token` | INT64, default 0 | Monotonic source-wide fence, independent of an individual job row |

Keep `generation_lock` as a lock implementation detail. Do not reuse it as a lease fence: ordinary lock acquisition must not invalidate a valid worker.

Backfill `managed=true` for sources referenced by an existing Artifact or Generation. Preserve all source IDs, current pointers, existing data and permissions. No new default generation is invented.

### Native rows

Add nullable `generation_id STRING` to Symbol, DataObject and Commit. Logical `source_id` remains unchanged. The namespace is derivable from source and generation and need not be duplicated in storage.

Preserve and validate all existing managed Passage columns: `generation_id`, `artifact_revision_id`, `span_id`, `embedding_profile`, `content_kind`, and `parent_passage_id` when supplied. A generation-tagged passage cannot omit its revision/span/profile binding.

Legacy untagged rows retain existing IDs and behavior. New staged writers require a complete generation context. Store code label dispatch continues accepting native `symbol-`, `data-`, `commit-` and `passage-` prefixes.

### GenerationEvidenceMember

Add a typed immutable record:

```python
class GenerationEvidenceMember(Record):
    generation_id: Text
    record_kind: Literal[
        "EvidenceSpan", "ObjectObservation", "AssertionVersion", "AssertionSupport",
        "Section", "SectionMember", "RetrievalView", "DerivedRecord",
        "DerivedDependency", "ConflictSet", "Alias",
    ]
    record_id: Text
    identity_fields = ("generation_id", "record_kind", "record_id")
```

The store validates the registered target kind, target existence, workspace and source/revision closure. Add a typed relation to Generation; target lookup uses the allowlisted `record_kind`, never caller-supplied Cypher labels.

GenerationMember remains the raw revision manifest. GenerationEvidenceMember is the exact interpretation manifest. KnowledgeObject and Assertion identities are reached through selected observations/versions; their immutable identity payloads do not authorize inclusion by themselves. NativeBinding already supplies its generation membership.

This record is required even when a new generation reuses unchanged raw revisions. Otherwise a new observation attached to an old span can change the old generation's labels before publication. Selecting all observations belonging to the revision is insufficient.

The root's evidence/projection selection must apply this closure before authorization filtering. Complete support groups are assembled from the selected interpretation's full support closure, then ACL checks apply. Do not shrink an AND group by dropping its private support first.

For this source-local build slice, declared spans/observations/supports must belong to revisions in the generation. Cross-source link construction remains a later LinkGeneration service; this slice does not silently invent compatible link sets.

### SnapshotReference

Add a typed record referencing an existing QuerySnapshot:

```python
class SnapshotReference(Record):
    workspace_id: Text
    snapshot_id: Text
    kind: Literal["active_query", "saved", "retained"]
    reference_key: Text
    created_at: Instant
    lease_owner: Text | None = None
    lease_expires_at: Instant | None = None
    released_at: Instant | None = None
    identity_fields = ("workspace_id", "snapshot_id", "kind", "reference_key")
```

Rules:

- An active_query reference requires a unique request key, lease owner and expiry after creation. The owner is a process/request lease identity, not a user authorization grant.
- Saved/retained references have no lease fields. Their reference keys identify the owning saved result or retention record through its service.
- Snapshot and reference workspaces must match. An expired or released reference cannot be renewed or resurrected. A new request uses a new key.
- Only lease expiry extension and one-way released_at are mutable. Owner, kind, target and key never change.
- An idempotent duplicate retain returns the original row; it does not rewrite created_at.
- Saving a result creates its durable saved reference in the same transaction as the result. Releasing an active reference cannot remove the saved reference.
- A request spanning several workspace snapshots acquires/releases a reference for each in one outer transaction. The root owns the aggregate request handle.

## Store APIs

The signatures below use explicit timestamps for compatibility with current publication tests. Production lease methods sample a store/service clock inside the transaction; test clock injection must not turn caller-supplied stale time into a successful lease check.

```python
def content_epoch() -> int: ...
def suppression_epoch() -> int: ...
def source_is_managed(source_id: str) -> bool: ...
def begin_managed_source(source_id: str) -> None: ...

def claim_generation_build(
    generation_id: str, *, job_key: str, lease_owner: str,
    lease_expires_at: datetime,
) -> MaintenanceJob: ...

def renew_generation_build(
    job_id: str, *, lease_owner: str, fencing_token: int,
    lease_expires_at: datetime,
) -> MaintenanceJob: ...

def check_generation_write(
    generation_id: str, *, job_id: str, lease_owner: str,
    fencing_token: int,
) -> None: ...

def seal_generation(
    generation_id: str, index_manifest: IndexManifest, *,
    job_id: str, lease_owner: str, fencing_token: int,
) -> str: ...  # returns the verified, immutable manifest ID

def publish_staged_generation(
    generation_id: str, *, expected_parent_id: str | None,
    job_id: str, lease_owner: str, fencing_token: int,
    expected_suppression_epoch: int, published_at: datetime,
    fault_hook=None,
) -> str: ...  # returns the durable publication IndexEvent ID

def acquire_snapshot_reference(
    snapshot: QuerySnapshot, *, reference_key: str,
    lease_owner: str, lease_expires_at: datetime,
    require_current: bool = True,
) -> SnapshotReference: ...

def renew_snapshot_reference(
    reference_id: str, *, lease_owner: str, lease_expires_at: datetime,
) -> SnapshotReference: ...

def retain_snapshot(
    snapshot_id: str, *, kind: Literal["saved", "retained"], reference_key: str,
) -> SnapshotReference: ...

def release_snapshot_reference(reference_id: str, *, lease_owner: str | None = None) -> None: ...

def discard_generation(
    generation_id: str, *, job_id: str, lease_owner: str, fencing_token: int,
) -> CollectionResult: ...

def collect_generation(generation_id: str) -> CollectionResult: ...

def recover_generation_builds() -> RecoveryResult: ...
```

CollectionResult and RecoveryResult are internal typed DTOs with counts, removed native IDs/blob references, and a non-content blocked reason. Returning blob references does not authorize deleting whole source directories.

### Build lease invariants

Use `MaintenanceJob(kind="rebuild", input_fingerprint=generation.id)`. Its expected_parent_id must equal the Generation parent; its source must equal the Generation source.

Claiming locks the source before reading active_build_id. A different nonexpired holder blocks acquisition. Reacquisition after expiration increments Source.build_fencing_token, even if the old job row is replaced. Copy the granted fence to the job. A stale owner/fence cannot renew, write, seal, publish or discard.

Every managed write batch checks the lease/fence and generation's writable state in the same transaction as its writes. Checking only at publication would allow an expired worker to corrupt another worker's staging rows.

No external fetch, model call or large computation runs while holding this transaction. Indexing computes outside, then validates its write authority again when persisting.

### Sealing and immutable content

Only staging generations accept new members, bindings and native row payloads. seal_generation verifies the complete raw/evidence/native closure, profile, vector dimensions, original span/text bindings and mandatory representation checksums, then installs one ready IndexManifest and transitions to ready atomically.

The manifest is the result of validation, not a caller's unchecked `ready=True`. Representation names and canonical checksum inputs must be shared with the staged writer. Missing required indexes cannot be downgraded to optional.

Ready/active/retired generations cannot acquire new membership or new native rows. Published derived record payloads and native rows cannot change; byte-equivalent normalized duplicate writes are allowed. A new interpretation receives a distinct record identity and is explicitly a member of the new generation. Reusing an immutable raw revision or identical derived record is allowed.

Generic update_knowledge must not reopen a sealed generation by setting status back to staging. Controlled status transitions and recorded_to updates on published interpretations are not an escape hatch. Task 5A will add the latter with knowledge-cutoff semantics.

Normalize embeddings to the backend's actual persisted numeric representation before duplicate comparison so harmless float serialization differences do not defeat idempotence.

### Publication compatibility

Preserve the existing publish_generation signature and its current trusted/internal use in persistence tests. Extract its transactional body into a private helper. The production lifecycle calls publish_staged_generation, which adds fence, suppression, sealed-closure and actual-index validation before invoking that same body.

The compatibility primitive is not exposed through HTTP, MCP or the managed pipeline. It does not become a second production path that bypasses staged checks. Existing fixture construction can remain explicit trusted setup; new production builds and G5 tests use the strict API.

Strict publication atomically verifies the expected parent, switches the active pointer, retires the former active generation, increments graph/content version, completes the build lease and writes one publication receipt/outbox event. It does not bump ACL epoch merely because content changed.

Record the originating job/fence in the event payload. A retry of an already committed identical publication may return that receipt without reactivating content or creating another event. A stale different build still fails CAS. Suppression checks precede any new activation; a historical receipt is never an authorization to restore suppressed content.

Preserve and extend pointer/version/event rollback failpoints. New failure points cover sealing, parent retirement, lease completion and reference acquisition.

## Snapshot and collection exclusion

Snapshot selection, reference acquisition and collection use the same durable transactional lock boundary on all three backends. Root may open an outer transaction to select all source pointers, construct workspace snapshots and acquire their references. The store operation is nesting-safe.

With require_current=True, validate every selected generation against its source's current pointer while acquiring the reference. A previously acquired reference keeps that immutable generation reachable after a refresh. It does not keep a revoked policy valid.

A reachable generation includes its IndexManifest, GenerationMember revisions, exact GenerationEvidenceMember closure, native rows/bindings and any explicitly selected compatible link/history records. Existing QuerySnapshot tuples must be sorted by the acquisition service for deterministic IDs.

Collection refuses an active generation or any generation reachable from a live active_query reference or unreleased saved/retained reference. Expiry is checked from the current clock within the collection transaction. Collection cannot race a reader that selected a pointer but has not yet registered its reference.

Remove generation-owned native rows and support contributions by generation ID. Remove shared revisions, spans, objects, assertions or raw blobs only when no surviving generation, retained history/link manifest or snapshot reference reaches them. Start conservatively: preserving an otherwise orphaned shared record is safer than deleting it without a complete reachability check.

Managed source deletion is a suppression/tombstone and builder-fencing operation; it must not call legacy source-wide deletion. Normal GC honors snapshot references. Purge overriding retention and removing saved text belongs to the later purge task.

Recovery examines expired build leases and abandoned staging generations. It clears stale source build pointers under fencing checks, records failure/abandonment and leaves a usable active generation's serving state intact. This is startup recovery, not the Task 9 scheduler.

## Epoch classification for root review

Keep authorization_epoch as the durable current-grant/suppression boundary. Introduce a separate content_epoch for managed content/cache invalidation. Existing graph_version remains the native serving-graph reload counter; publication updates graph_version and content_epoch in the same transaction. Held snapshot validation ignores content_epoch and rechecks current ACL/suppression independently.

Store content_epoch and suppression_epoch as durable monotonic Settings counters with the same transactional corruption checks as authorization_epoch. The suppression counter advances on applied suppression/tombstone/restore changes, independently of ordinary permission refreshes. Schema 4 initializes it consistently with existing Suppression rows; subsequent removal cannot decrease it. It is an internal coarse global fence for expected_suppression_epoch, not a public corpus count. Source-scoped suppression counters can follow only with complete dependency mapping; this slice does not assume such mapping exists.

Use an exhaustive classifier over registered record types; a newly registered type without a classification fails a contract test.

| Record/mutation | ACL epoch | Content epoch |
| --- | --- | --- |
| WorkspaceMembership, GroupMembership insertion or effective mapping/grant change | Yes | No |
| AccessPolicy creation or freshness/expiry change | Yes | No |
| Connector creation/configuration/enabled-state change | Yes | No |
| Artifact policy_id or deleted_at change | Yes; deletion service must also install suppression | Yes for presentation/lifecycle change |
| Artifact creation; first Generation creation on a legacy source | Yes only for the transition into managed mode | Yes |
| Artifact canonical_uri update on an already managed source | No | Yes |
| Suppression creation or removal by a future controlled restore operation | Yes | Yes |
| ArtifactRevision, EvidenceSpan, KnowledgeObject, ObjectObservation, Assertion, AssertionVersion, AssertionSupport, NativeBinding | No | Yes |
| Generation, GenerationMember, GenerationEvidenceMember, IndexManifest, LinkGeneration, HistoryManifest | No after the managed-mode transition | Yes |
| DerivedRecord, DerivedDependency, RetrievalView, Section, SectionMember, ConflictSet, Alias | No | Yes |
| Workspace, SyncState, SyncRun, MaintenanceJob, SourceEvent, PurgeJob, IndexEvent, ConsumerAck, QuerySnapshot, SnapshotReference | No | No for bookkeeping alone |

Content-only mutations in this table are still subject to sealing and published-payload immutability. The table does not permit changing an old snapshot's content in place. Bookkeeping that applies a policy, suppression, tombstone or publication calls the corresponding operation; its own job/status write is not the authorization change.

Retain existing ACL bumps for live user/role changes, source access/ownership, reviewed_mapping_authorities, installation open-mode transitions and evaluation ownership grants. Legacy content writes retain their current graph-version behavior. An Artifact/Generation insertion must not silently switch source mode without revoking an already held legacy view.

AccessPolicy/Connector creation currently uses conservative global invalidation even if no active evidence references the new record. Narrowing that requires a proven dependency-aware grant invalidator and is not needed for this slice.

## Required storage tests

1. Migrate a populated v3 store to v4 without changing legacy native IDs, policy IDs, v3 checksum/history or content. Inject each migration interruption and reopen safely.
2. Claim two jobs for one source; demonstrate only one live holder. Expire/reacquire and reject the stale holder on write, seal, publish and discard.
3. Stage G2 beside active G1 with identical source/path/commit inputs; native rows and every endpoint remain isolated.
4. Reuse G1's raw revision in G2, add a distinct observation on an existing span, and prove G1's exact interpretation closure and projection remain unchanged before and after G2 publication.
5. Reject writes to sealed membership, bindings, derived payloads and native rows; accept identical duplicates without changing epochs.
6. Reject wrong-source/revision/span/generation/native-ID/profile bindings and incomplete mandatory representations.
7. Exercise failure before sealing/publication, CAS competition, suppression during a build, duplicate successful publication, rollback at each failpoint and process reopen.
8. Hold a G1 query reference, publish G2, and prove G1 survives collection without changing ACL epoch; revoke a policy and prove the held query is denied.
9. Race snapshot acquisition/renewal with collection; expired/released references cannot resurrect, while saved/retained references survive process restart.
10. Discard only the requesting staging generation; preserve shared evidence, another build's rows, active content and retained raw blob references.
11. Recover an abandoned build while its source has active content; serving status and active pointer remain usable.
12. Assert the epoch matrix, including first managed-mode transition, pure build/reference bookkeeping and failed transaction rollback.

## Resolved integration decisions

1. Strict representation names are `evidence`, `dense`, and `native`, all mandatory (empty native rows are valid for prose). Store computes canonical checksums from actual persisted rows: evidence is sorted exact member payloads plus referenced immutable revisions/objects/assertions/bindings, excluding live Artifact/AccessPolicy payloads; dense is generation Passage IDs, ownership/revision/span/profile/text/title/ordinal/parent/kind and persisted vectors; native is generation Symbol/DataObject/Commit payloads and within-generation code/definition/modification/predecessor/reference relationships. Include all retrieval-affecting persisted payload fields. Normalize numeric vectors to persisted float32 before checksumming and reject invalid dimensions/nonfinite values. The staged writer consumes the same store checksum helper, and sealing independently recomputes it. Unknown/missing mandatory representations fail closed. No output checksum feeds Generation.manifest_hash.
2. Existing v3 managed generations require a strict rebuild before durable retained snapshot acquisition; no historical interpretation membership is invented. Their trusted compatibility projection remains available until an explicit migration/rebuild, but does not claim durable reconstructible snapshots. Acquiring a strict snapshot without sealed exact membership gives a typed unavailable/rebuild-required result.
3. Root will implement a request-local bundle of workspace QuerySnapshots, acquired/released in one transaction. Legacy graph content is pinned in memory with its own fingerprint; an empty managed source tuple is never presented as reconstructible legacy history.
4. The epoch matrix is approved subject to current immutable-field restrictions: no policy-affecting mutation is reclassified as content, and the first managed-mode transition still invalidates old legacy views. Published interpretation/native payloads are frozen. Adding new AssertionSupport to a version already sealed in a generation is forbidden: changing a proof group requires a new AssertionVersion, preventing partial-group reinterpretation. Identical existing support can be shared. Task5A later introduces controlled recorded_to closure with knowledge-cutoff semantics.

These are implementation decisions within authorized Task5. No Task5 gate is marked complete by this contract.
