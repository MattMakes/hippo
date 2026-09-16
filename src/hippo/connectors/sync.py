"""The connector sync runtime: one entry that drives any connector through the design's section 7.

`sync_connector` is a third coordinator beside `build_plain_source` and `build_code_source`, and it
reuses their machinery rather than copying it: `BuildRun` for the failure latch, heartbeat and
cancellation; `capture_build_authority`, `bind_inputs` and `rebaseline_between_batches`;
`generation_for_inputs`; and the store's claim, write, seal and publication compare. What is new is
the part before a generation exists -- a sync lease on a `SyncRun` row, per-page durable capture,
a cursor checkpoint in `SyncState`, and deletion inferred only from a completed inventory.

Contract: `ai_docs/plans/cdk-s3-runtime.md` sections 4.7, 5, 6, 9 and 11, amended by the rulings its
brief names. Where a ruling and the plan differ the ruling wins, and the deviation is recorded in
`ai_docs/gates/rag-it-all/cdk/evidence-s3c.md`:

* R48/B2 -- the policy of a revision's first capture is recorded in
  `ArtifactRevision.metadata_json["span_policy_id"]` and passed as `RevisionInput.span_policy_id`,
  so a stored span is never re-minted under a different policy.
* R49/B4 -- the entry takes `connector_id`; each emit worker enters the guard inside its own thread
  under `contextvars.copy_context().run(...)`.
* R51/M5 -- `ensure_connector` creates an instance disabled and a disabled instance is refused here;
  review CK7 F5 made the argument `bool | None`, so re-ensuring one does not disable it.
* R52/M3 -- a stored policy is refreshed only when `expires_at - now < policy_ttl_seconds / 2`, so
  two syncs of unchanged content inside the window move no epoch.
* R52/M4 -- `no_changes` is decided *after* the candidate generation is computed, by `manifest_hash`
  equality with the parent and no policy change, so a template version bump rebuilds.
* R32/R46 -- the connector's `TypeExtension` must be registered, and each registered definition must
  equal `descriptor.extension`.
* m15 -- the pending change log lives in the raw store, as the inventory's seen set already does,
  and a changed `canonical_uri` is written at the checkpoint.

**A collected generation's units may dangle (ruling R66 ii).** `AssertionVersion.unit_id` is
informational and is never cleared: collection deletes a generation's `Unit` rows while a
superseded or retracted version still names one, so the reference is exempt from the store's
reference checks and a reader treats a missing unit as "no statement vector".

The runtime never deletes the active generation: it calls no collection, discard or passage-delete
primitive anywhere, and a failed attempt is failed in place.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from ..ingest.build_run import (
    BuildBusy,
    BuildCancelled,
    BuildProgress,
    BuildReceipt,
    BuildRun,
    adopt_capture_instant,
    authority_fields,
    credentials,
    prior_receipt,
    rebaseline_between_batches,
)
from ..knowledge import identity as ident
from ..knowledge import model as k
from ..knowledge import staged_records
from ..knowledge.access import AuthorizationChanged
from ..knowledge.build_authority import (
    CONNECTOR_SCOPE,
    AcceptedBuildInputs,
    BuildActor,
    capture_build_authority,
)
from ..knowledge.embedding_cache import EmbeddingCache
from ..knowledge.embedding_profile import (
    EmbeddingSpec,
    ProfiledEmbeddings,
    resolve_embedding_profile,
    validate_profile_descriptor,
)
from ..knowledge.generation_profiles import (
    CONNECTOR_MANIFEST_EXTERNAL_ID,
    CONNECTOR_MANIFEST_KEY,
    CONNECTOR_PROFILE,
    GENERATION_PROFILE_KEY,
)
from ..knowledge.identity import canonical_json, text_hash
from ..knowledge.lifecycle import generation_for_inputs
from ..knowledge.raw_artifacts import RawArtifact, RawArtifactStore
from ..knowledge.registry import Registry, current_registry
from ..store.generation_counts import generation_counts
from . import credentials as credential_refs
from . import emit, guard
from .base import (
    ChangePage,
    ConnectorDescriptor,
    EmissionBatch,
    ExternalRef,
    RevisionInput,
    SyncCursor,
    TypeMapping,
)
from .classify import CLASSIFIER_VERSION
from .emit import BINDER_VERSION, ContractError
from .http import ProviderNotFoundError
from .keys import KEY_RULE_VERSION
from .render import RENDER_RULE_VERSION

__all__ = [
    "CONNECTOR_PARSER_VERSION",
    "CONNECTOR_SOURCE_KIND",
    "FAULT_POINTS",
    "SYNC_RULE_VERSION",
    "ConnectorContractViolation",
    "ConnectorSyncBusy",
    "ConnectorSyncCancelled",
    "ConnectorSyncRefused",
    "SyncOptions",
    "SyncReceipt",
    "connector_source",
    "ensure_connector",
    "load_classification",
    "reconcile_due",
    "store_classification",
    "sync_connector",
]

SYNC_RULE_VERSION = "cdk-sync-v1"
CONNECTOR_SOURCE_KIND = "connector"
CONNECTOR_PARSER_VERSION = "cdk-connector-v1"
MANIFEST_PAYLOAD_VERSION = 1
CANCELLED_MESSAGE = "Connector sync cancelled"
RENEWAL_FAILED_MESSAGE = "Connector sync lease renewal failed"
LEASE_LOST = "Sync lease was lost"

FAULT_POINTS = (
    "lease",
    "after_page",
    "after_fetch",
    "before_checkpoint",
    "after_checkpoint",
    "after_emit",
    "after_bind",
    "after_install",
    "before_batch",
    "before_seal",
    "before_publish",
    "after_publish",
)


class ConnectorSyncRefused(ValueError):
    """The call itself cannot run: a wrong actor, registry, lane, instance or partition."""


class ConnectorSyncBusy(BuildBusy):
    """Another holder owns the sync lease, or this run's lease was taken from it."""


class ConnectorSyncCancelled(BuildCancelled):
    """`should_stop` turned true; the last checkpoint is kept."""


class ConnectorContractViolation(ValueError):
    """The connector broke the kit's contract: a side effect in `emit`, or an impure batch."""


@dataclass(frozen=True)
class SyncOptions:
    max_pages: int = 1000
    max_changes_per_page: int = 1000
    max_fetch_bytes: int = 8_000_000
    max_run_bytes: int = 256_000_000
    max_batch_records: int = 50_000
    emit_workers: int = 2
    emit_timeout_seconds: float = 30.0
    policy_ttl_seconds: float = 600.0
    reconcile: bool = False
    reconcile_interval_seconds: float = 86_400.0
    batch_size: int = 128
    max_batch_payload_bytes: int = 64 * 1024 * 1024
    lease_duration_seconds: float = 300.0
    renewal_interval_seconds: float = 30.0


@dataclass(frozen=True)
class SyncReceipt:
    source_id: str
    partition: str
    outcome: Literal["published", "already_current", "already_published", "no_changes"]
    generation_id: str | None
    build: BuildReceipt | None
    pages: int
    changes: int
    deleted: int
    policy_updates: int
    inventory: Literal["not_scanned", "partial", "complete"]
    coverage: Mapping[str, object]


# ------------------------------------------------------------------ instances, sources, probes


def ensure_connector(
    store,
    *,
    workspace_id: str,
    kind: str,
    instance_url: str,
    config: BaseModel,
    credential_ref: str | None = None,
    enabled: bool | None = None,
) -> k.Connector:
    """Create or update one connector instance. Ruling R51: instances are disabled by default.

    A `Connector` write is an authorization record and bumps the authorization epoch
    (`store/authorization.py:113-114`), so operators create instances outside build windows
    (ruling R5/R35) and this is never called from inside a sync.

    Review CK7 finding F5: `enabled` is three-valued. `None` means "do not decide" - a new instance
    is created disabled (R51 unchanged) and an existing one keeps the flag it has - so re-ensuring
    an instance to change its configuration no longer silently disables it. `True` and `False` are
    the caller saying so.
    """
    if not isinstance(config, BaseModel):
        raise ConnectorSyncRefused("A connector instance stores its typed configuration")
    credential_refs.refuse_inline_secrets(config)
    if credential_ref is not None:
        credential_refs.CredentialRef.parse(credential_ref)
    row = k.Connector(
        workspace_id=workspace_id,
        kind=kind,
        instance_url=instance_url,
        config_json=config.model_dump_json(),
        credential_ref=credential_ref,
        enabled=bool(enabled),  # R51: a new instance is disabled unless the caller said otherwise
    )
    existing = store._knowledge_get("Connector", row.id)
    if existing is None:
        store.put_knowledge(row)
        return row
    updated = existing.replace(
        config_json=row.config_json,
        credential_ref=credential_ref,
        enabled=existing.enabled if enabled is None else enabled,
    )
    if updated != existing:
        store.update_knowledge(updated)
    return updated


def connector_source(
    store,
    *,
    connector: k.Connector,
    partition: str,
    name: str,
    owner_id: str | None = None,
    access_role_id: str | None = None,
) -> str:
    """The `connector` Source of one (instance, partition), created once (plan decision 1)."""
    meta = {"connector_id": connector.id, "partition": partition}
    for source in store.list_sources():
        if source.get("kind") != CONNECTOR_SOURCE_KIND:
            continue
        existing = source.get("meta") or {}
        if (existing.get("connector_id"), existing.get("partition")) == (connector.id, partition):
            return source["id"]
    return store.create_source(
        CONNECTOR_SOURCE_KIND, name, meta, owner_id=owner_id, access_role_id=access_role_id
    )


def store_classification(store, *, connector: k.Connector, classification) -> k.Connector:
    """Ruling R21: the probe result is written only when the value changes, so a re-probe is free."""
    payload = canonical_json(classification.model_dump(mode="json"))
    if connector.classification_json == payload:
        return connector
    updated = connector.replace(classification_json=payload)
    store.update_knowledge(updated)
    return updated


def load_classification(connector: k.Connector, partition: str):
    """One partition's stored probe result; `emit` never receives a fresh guess (design section 2)."""
    from .base import Classification

    stored = json.loads(connector.classification_json)
    if stored.get("partitions"):
        # The contract models are strict, so the round trip goes through JSON, not through dicts.
        classification = Classification.model_validate_json(connector.classification_json)
        for entry in classification.partitions:
            if entry.partition == partition:
                return entry
    raise ConnectorSyncRefused(f"Probe the connector before syncing partition {partition}")


def reconcile_due(state: k.SyncState | None, *, now: datetime, interval: timedelta) -> bool:
    """Whether a complete inventory scan is due (plan section 6.4; the default is daily)."""
    if state is None or state.last_reconciled_at is None:
        return True
    return state.last_reconciled_at + interval <= now


# ------------------------------------------------------------------ the run and its target


class ConnectorRun(BuildRun):
    """`BuildRun` plus the sync lease: the heartbeat renews both, and both are sticky."""

    def __init__(self, ctx, actor, source_id, options, should_stop, on_progress):
        super().__init__(
            ctx,
            actor,
            source_id,
            options,
            should_stop,
            on_progress,
            capture=capture_build_authority,
            cancelled_message=CANCELLED_MESSAGE,
            renewal_failed_message=RENEWAL_FAILED_MESSAGE,
        )
        self.sync_run: k.SyncRun | None = None

    def renew(self):
        try:
            with self._lock:
                held = self.sync_run
                if held is not None:
                    with self.store.transaction():
                        current = _check_sync(self.store, held)
                        expiry = max(
                            self.store._now() + timedelta(seconds=self.options.lease_duration_seconds),
                            current.lease_expires_at
                            + timedelta(seconds=self.options.renewal_interval_seconds),
                        )
                        renewed = current.replace(lease_expires_at=expiry)
                        self.store.update_knowledge(renewed)
                        self.sync_run = renewed
        except BuildCancelled:
            raise
        except BaseException as error:
            failure = AuthorizationChanged(RENEWAL_FAILED_MESSAGE)
            self._fail(failure)
            raise failure from error
        super().renew()


@dataclass
class _Target:
    """Everything the steps share about *what* is being synced; never mutated after entry."""

    connector: object
    row: k.Connector
    descriptor: ConnectorDescriptor
    config: BaseModel
    partition: str
    source_id: str
    workspace_id: str
    registry: Registry
    mapping: TypeMapping
    raw_store: RawArtifactStore
    options: SyncOptions
    operation_id: str
    fault_hook: Callable[[str], None] | None = None
    on_batch: Callable[[RevisionInput, EmissionBatch], None] | None = None
    counters: dict = field(default_factory=dict)

    def fault(self, label: str) -> None:
        """The store's own failpoint convention (`generations.py:481-518`); the return is ignored."""
        if self.fault_hook is not None:
            self.fault_hook(label)

    @property
    def scope_key(self) -> str:
        return f"source:{self.source_id}:{self.partition}"

    def count(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount


@dataclass(frozen=True)
class _Captured:
    """One change, captured durably, before the checkpoint decides what the store already holds."""

    operation: str
    artifact_id: str
    artifact: k.Artifact | None
    revision: k.ArtifactRevision | None
    policy: k.AccessPolicy | None


@dataclass(frozen=True)
class _CapturedPage:
    records: tuple[_Captured, ...]
    next_cursor: SyncCursor | None
    complete: bool
    scan: str


@dataclass(frozen=True)
class _SyncInputs:
    generation: k.Generation
    parent_id: str | None
    configuration: dict
    configuration_json: str
    pairs: tuple[tuple[k.Artifact, k.ArtifactRevision], ...]
    manifest_pair: tuple[k.Artifact, k.ArtifactRevision]
    planned_policies: tuple[k.AccessPolicy, ...]
    accepted: AcceptedBuildInputs


# ------------------------------------------------------------------ step 1: the lease


def _sync_run_identity(target: _Target) -> str:
    return k.SyncRun(
        connector_id=target.row.id,
        source_id=target.source_id,
        scope_key=target.scope_key,
        run_key=target.partition,
        input_fingerprint=SYNC_RULE_VERSION,
        phase="queued",
    ).id


def _sync_state_identity(target: _Target) -> str:
    return k.SyncState(connector_id=target.row.id, partition_key=target.partition).id


def _check_sync(store, held: k.SyncRun) -> k.SyncRun:
    """The fence: this run still owns the lease, or nothing it is about to write may commit."""
    current = store._knowledge_get("SyncRun", held.id)
    if (
        current is None
        or current.status != "running"
        or current.lease_owner != held.lease_owner
        or current.fencing_token != held.fencing_token
        or current.lease_expires_at is None
        or current.lease_expires_at <= store._now()
    ):
        raise ConnectorSyncBusy(LEASE_LOST)
    return current


def _lease(run: ConnectorRun, target: _Target, options: SyncOptions):
    store = run.store
    with store.transaction():
        store._lock_source(target.source_id)
        source = store.get_source(target.source_id)
        if source is None or store._tombstoned(target.source_id, source):
            raise ConnectorSyncRefused("Source is tombstoned")
        # A crashed run's expired build lease must be released before capture writes, because a
        # live rebuild job makes an `Artifact` write require build authority (section 6.2).
        store.recover_generation_builds(source_id=target.source_id)
        now = store._now()
        expiry = now + timedelta(seconds=options.lease_duration_seconds)
        identity = _sync_run_identity(target)
        held = store._knowledge_get("SyncRun", identity)
        if (
            held is not None
            and held.status == "running"
            and held.lease_expires_at is not None
            and held.lease_expires_at > now
            and held.lease_owner != run.owner
        ):
            raise ConnectorSyncBusy("Connector partition already has a live sync holder")
        cursor_json = canonical_json({"operation_id": target.operation_id})
        if held is None:
            leased = k.SyncRun(
                connector_id=target.row.id,
                source_id=target.source_id,
                scope_key=target.scope_key,
                run_key=target.partition,
                input_fingerprint=SYNC_RULE_VERSION,
                phase="fetch",
                status="running",
                lease_owner=run.owner,
                lease_expires_at=expiry,
                fencing_token=1,
                attempt_count=1,
                cursor_json=cursor_json,
            )
            store.put_knowledge(leased)
        else:
            leased = held.replace(
                phase="fetch",
                status="running",
                lease_owner=run.owner,
                lease_expires_at=expiry,
                fencing_token=held.fencing_token + 1,
                attempt_count=held.attempt_count + 1,
                retry_at=None,
                error_code=None,
                cursor_json=cursor_json,
            )
            store.update_knowledge(leased)
        state = store._knowledge_get("SyncState", _sync_state_identity(target))
        if state is None:
            state = k.SyncState(connector_id=target.row.id, partition_key=target.partition)
            store.put_knowledge(state)
    run.sync_run = leased
    target.fault("lease")
    return leased, state


def _release(run: ConnectorRun, target: _Target, *, error_code: str | None) -> None:
    """The failure path's lease release; it never raises over the original exception."""
    held = run.sync_run
    if held is None:
        return
    try:
        with run.store.transaction():
            current = run.store._knowledge_get("SyncRun", held.id)
            if current is None or current.lease_owner != held.lease_owner:
                return
            run.store.update_knowledge(
                current.replace(
                    status="failed",
                    lease_owner=None,
                    lease_expires_at=None,
                    error_code=error_code,
                )
            )
    except BaseException:  # noqa: BLE001 - the original failure is the one that matters
        pass


# ------------------------------------------------------------------ step 2: cursor and page


def _next_page(run: ConnectorRun, target: _Target, cursor: SyncCursor | None, options) -> ChangePage:
    run.check()
    page = target.connector.list_changes(target.config, cursor)
    run.check()
    if not isinstance(page, ChangePage):
        raise ConnectorContractViolation("list_changes must return a ChangePage")
    if len(page.changes) > options.max_changes_per_page:
        raise ConnectorSyncRefused("A change page exceeds max_changes_per_page")
    if page.partition != target.partition:
        raise ConnectorSyncRefused("A change page names another partition")
    target.count("pages")
    target.fault("after_page")
    return page


# ------------------------------------------------------------------ step 3: capture


def _capture(run: ConnectorRun, target: _Target, page: ChangePage, raw_store, options) -> _CapturedPage:
    """Outside every transaction: fetch, store the bytes, observe the policy (design section 7.3)."""
    store = run.store
    now = store._now()
    expires_at = now + timedelta(seconds=options.policy_ttl_seconds)
    records: list[_Captured] = []
    for change in page.changes:
        run.check()
        target.count("changes")
        operation = change.operation
        artifact_id = ident.artifact_identity(
            target.workspace_id, target.row.instance_url, change.ref.artifact_kind, change.ref.external_id
        )
        if operation == "policy_change" and store._knowledge_get("Artifact", artifact_id) is None:
            operation = "upsert"  # nothing is stored yet, so the change is the first capture
        if operation == "delete":
            records.append(_Captured("delete", artifact_id, None, None, None))
            continue
        policy = _fetch_policy(target, change.ref)
        if operation == "policy_change":
            records.append(
                _Captured(
                    "policy_change",
                    artifact_id,
                    None,
                    None,
                    emit.policy_record(
                        policy,
                        connector=target.row,
                        workspace_id=target.workspace_id,
                        observed_at=now,
                        expires_at=expires_at,
                    ),
                )
            )
            continue
        fetched = target.connector.fetch(target.config, change.ref)
        if len(fetched.data) > options.max_fetch_bytes:
            raise ConnectorSyncRefused("A fetched object exceeds max_fetch_bytes")
        target.count("fetched_bytes", len(fetched.data))
        if target.counters.get("fetched_bytes", 0) > options.max_run_bytes:
            raise ConnectorSyncRefused("This run exceeds max_run_bytes")
        raw = raw_store.put_bytes(fetched.data)
        captured = emit.capture_records(
            fetched,
            policy,
            connector=target.row,
            workspace_id=target.workspace_id,
            source_id=target.source_id,
            raw_uri=raw.uri,
            observed_at=now,
            policy_expires_at=expires_at,
        )
        target.count("fetched")
        records.append(
            _Captured(
                "upsert",
                captured.artifact.id,
                captured.artifact,
                _with_span_policy(captured.revision, captured.policy.id, raw.byte_length),
                captured.policy,
            )
        )
    target.fault("after_fetch")
    return _CapturedPage(
        records=tuple(records),
        next_cursor=page.next_cursor,
        complete=page.complete,
        scan=page.next_cursor.scan if page.next_cursor is not None else "changes",
    )


def _fetch_policy(target: _Target, ref: ExternalRef):
    """Unknown is deny: a forbidden or permission-masked ACL is an observation, never a deletion."""
    from .http import ProviderForbiddenError

    try:
        return target.connector.fetch_policy(target.config, ref)
    except (ProviderForbiddenError, ProviderNotFoundError):
        from .base import PolicyObservation

        return PolicyObservation(ref=ref, state="unknown")


def _with_span_policy(revision: k.ArtifactRevision, policy_id: str, byte_length: int):
    """Ruling R48/B2. `metadata_json` is outside revision identity, so the id does not move."""
    metadata = json.loads(revision.metadata_json)
    metadata["span_policy_id"] = policy_id
    metadata["raw_bytes"] = byte_length
    return revision.replace(metadata_json=canonical_json(metadata))


# ------------------------------------------------------------------ step 4: the checkpoint


def _raw_reference(raw_store, payload: dict) -> dict:
    """Write one bookkeeping payload to the raw store and name it by URI and length.

    Review m15: the pending change log lives in the raw store, as the inventory's seen set
    already does, so a large page never inflates the `SyncState` row. The payload is content
    addressed, so a replayed page computes the same reference and the row does not change a byte.
    The length travels with the URI because `RawArtifactStore` verifies it on read and the store
    layout is its own business.
    """
    body = canonical_json(payload).encode("utf-8")
    raw = raw_store.put_bytes(body)
    return {"uri": raw.uri, "sha256": raw.sha256, "bytes": raw.byte_length}


def _read_raw(raw_store, reference: dict | None) -> dict | None:
    if not reference:
        return None
    artifact = RawArtifact(reference["uri"], reference["sha256"], int(reference["bytes"]))
    return json.loads(raw_store.read_bytes(artifact).decode("utf-8"))


def _pending_uri(raw_store, pending: dict) -> dict | None:
    if not pending:
        return None
    return _raw_reference(raw_store, {"version": 1, "entries": pending})


def _read_pending(raw_store, reference: dict | None) -> dict:
    payload = _read_raw(raw_store, reference)
    return payload["entries"] if payload else {}


def _cursor_state(state: k.SyncState) -> dict:
    stored = json.loads(state.cursor_json)
    return {
        "version": 1,
        "cursor": stored.get("cursor"),
        "pending": stored.get("pending"),
        "scan": stored.get("scan"),
    }


def _checkpoint(run: ConnectorRun, target: _Target, captured: _CapturedPage, state, scan) -> k.SyncState:
    """One transaction per page: the durable observations, then the cursor (design section 7.4)."""
    store = run.store
    now = store._now()
    stored = _cursor_state(state)
    pending = dict(_read_pending(target.raw_store, stored.get("pending")))
    with store.transaction():
        store._lock_source(target.source_id)
        _check_sync(store, run.sync_run)
        for record in captured.records:
            entry = _apply(store, target, record, now)
            if entry is not None:
                pending[record.artifact_id] = entry
        cursor_json = canonical_json(
            {
                "version": 1,
                "cursor": captured.next_cursor.model_dump(mode="json")
                if captured.next_cursor is not None
                else None,
                "pending": _pending_uri(target.raw_store, pending),
                "scan": scan,
            }
        )
        target.fault("before_checkpoint")
        current = store._knowledge_get("SyncState", state.id)
        updated = current.replace(cursor_json=cursor_json)
        if updated != current:
            store.update_knowledge(updated)
        held = store._knowledge_get("SyncRun", run.sync_run.id)
        store.update_knowledge(held.replace(phase="fetch"))
    target.fault("after_checkpoint")
    return store._knowledge_get("SyncState", state.id)


def _apply(store, target: _Target, record: _Captured, now) -> list | None:
    """One captured change, inside the checkpoint transaction. Returns its pending-log entry."""
    stored_artifact = store._knowledge_get("Artifact", record.artifact_id)
    if record.operation == "delete":
        if stored_artifact is None:
            return None
        if stored_artifact.deleted_at is None:
            store.update_knowledge(stored_artifact.replace(deleted_at=now))
            target.count("deleted")
        return ["delete", None, stored_artifact.policy_id]
    policy = _policy_row(store, target, record.policy, now)
    if record.operation == "policy_change":
        if stored_artifact is not None and stored_artifact.policy_id != policy.id:
            store.update_knowledge(stored_artifact.replace(policy_id=policy.id))
            target.count("policy_updates")
        revision_id = _current_revision_id(store, target, record.artifact_id)
        return ["policy_change", revision_id, policy.id]
    revision = _revision_row(store, record.revision)
    if stored_artifact is None:
        store.put_knowledge(record.artifact)
        stored_artifact = record.artifact
    else:
        updated = stored_artifact
        if updated.policy_id != policy.id:
            updated = updated.replace(policy_id=policy.id)
            target.count("policy_updates")
        if updated.canonical_uri != record.artifact.canonical_uri:
            # Review m15: `canonical_uri` is mutable and moves no epoch; a moved object keeps
            # its identity and gains its new address.
            updated = updated.replace(canonical_uri=record.artifact.canonical_uri)
        if updated.deleted_at is not None and revision.id != _deleted_revision(store, updated):
            updated = updated.replace(deleted_at=None)  # the delete barrier, rag_it_all.md:637
        if updated != stored_artifact:
            store.update_knowledge(updated)
    store.put_knowledge(revision)
    return ["upsert", revision.id, policy.id]


def _policy_row(store, target: _Target, policy: k.AccessPolicy, now) -> k.AccessPolicy:
    """Ruling R52/M3: a stored policy is refreshed only inside half its remaining lifetime."""
    stored = store._knowledge_get("AccessPolicy", policy.id)
    if stored is None:
        store.put_knowledge(policy)
        return policy
    ttl = policy.expires_at - policy.verified_at if policy.expires_at else timedelta(0)
    if stored.expires_at is not None and stored.expires_at - now >= ttl / 2:
        return stored
    refreshed = stored.replace(verified_at=now, expires_at=now + ttl)
    store.update_knowledge(refreshed)
    return refreshed


def _revision_row(store, revision: k.ArtifactRevision) -> k.ArtifactRevision:
    """Whole-revision reuse, the rule of `prose_generation._pair` (`:124-138`).

    Reuse keeps the first capture's `span_policy_id`, which is what makes a stored span's policy
    stable under a later policy change (ruling R48/B2).
    """
    stored = store._knowledge_get("ArtifactRevision", revision.id)
    if stored is None:
        return revision
    if (stored.artifact_id, stored.content_hash, stored.provider_revision, stored.raw_uri) != (
        revision.artifact_id,
        revision.content_hash,
        revision.provider_revision,
        revision.raw_uri,
    ):
        raise ConnectorSyncRefused("Accepted revision identity conflicts with stored input")
    return stored


def _current_revision_id(store, target: _Target, artifact_id: str) -> str | None:
    rows = [
        row
        for row in store._knowledge_rows("ArtifactRevision", where={"artifact_id": artifact_id})
        if row.lifecycle == "active"
    ]
    if not rows:
        return None
    return max(rows, key=lambda row: (row.observed_at, row.id)).id


def _deleted_revision(store, artifact: k.Artifact) -> str | None:
    """The revision the artifact held when it was deleted; an identical replay stays deleted."""
    rows = list(store._knowledge_rows("ArtifactRevision", where={"artifact_id": artifact.id}))
    if not rows:
        return None
    return max(rows, key=lambda row: (row.observed_at, row.id)).id


# ------------------------------------------------------------------ step 5: inputs and authority


def _member_revisions(store, parent_id: str | None) -> dict[str, k.ArtifactRevision]:
    """The parent generation's accepted originals, keyed by artifact, without its manifest."""
    if parent_id is None:
        return {}
    members = {}
    for member in store._knowledge_rows("GenerationMember", generation_id=parent_id):
        revision = store._knowledge_get("ArtifactRevision", member.artifact_revision_id)
        artifact = store._knowledge_get("Artifact", revision.artifact_id)
        if artifact is None or artifact.kind == "manifest":
            continue
        members[artifact.id] = revision
    return members


def _inputs(run: ConnectorRun, target: _Target, state: k.SyncState, now) -> _SyncInputs | None:
    """Sections 5.5 and 6.4: the member set, the inventory manifest and the candidate generation."""
    store = run.store
    control = run.guard.source_control
    parent_id = control.active_generation_id
    members = _member_revisions(store, parent_id)
    pending = _read_pending(target.raw_store, _cursor_state(state).get("pending"))
    for artifact_id, entry in pending.items():
        operation, revision_id, _policy_id = entry
        if operation == "delete":
            members.pop(artifact_id, None)
        elif operation == "upsert" and revision_id:
            members[artifact_id] = store._knowledge_get("ArtifactRevision", revision_id)
    pairs = []
    for artifact_id, revision in sorted(members.items()):
        artifact = store._knowledge_get("Artifact", artifact_id)
        if artifact is None or artifact.deleted_at is not None or revision is None:
            continue  # publication refuses a tombstoned artifact in the closure (`:1322`)
        pairs.append((artifact, revision))
    pairs = tuple(pairs)
    configuration = _configuration(target)
    payload = {
        "version": MANIFEST_PAYLOAD_VERSION,
        "source_id": target.source_id,
        "workspace_id": target.workspace_id,
        "connector_id": target.row.id,
        "instance": target.row.instance_url,
        "partition": target.partition,
        "configuration": configuration,
        "members": [
            {
                "artifact_id": artifact.id,
                "revision_id": revision.id,
                "content_hash": revision.content_hash,
                "raw_uri": revision.raw_uri,
                "provider_revision": revision.provider_revision,
            }
            for artifact, revision in sorted(pairs, key=lambda pair: pair[0].id)
        ],
    }
    manifest_policy, planned = _manifest_policy(run, now)
    manifest_pair = _manifest_pair(store, target, payload, manifest_policy, now)
    resolved_profile = target.counters["embedding"]
    gen = generation_for_inputs(
        (*pairs, manifest_pair),
        workspace_id=target.workspace_id,
        source_id=target.source_id,
        parent_id=parent_id,
        parser_version=CONNECTOR_PARSER_VERSION,
        linker_version=BINDER_VERSION,
        embedding_profile=resolved_profile.fingerprint,
        configuration=configuration,
        created_at=now,
        registry_fingerprint=target.registry.fingerprint(),
    )
    instant = adopt_capture_instant(store, gen, now)
    if instant != now:
        gen = gen.replace(created_at=instant)
    # Review M4: `no_changes` is decided here, on the candidate generation, so a changed template
    # version or derivation rebuilds an otherwise unchanged partition.
    if (
        parent_id is not None
        and gen.manifest_hash == store._generation(parent_id).manifest_hash
        and not target.counters.get("policy_updates")
        and not target.counters.get("deleted")
    ):
        return None
    accepted = AcceptedBuildInputs(pairs=(*pairs, manifest_pair), spans=(), planned_policies=tuple(planned))
    return _SyncInputs(
        generation=gen,
        parent_id=parent_id,
        configuration=configuration,
        configuration_json=canonical_json(configuration),
        pairs=pairs,
        manifest_pair=manifest_pair,
        planned_policies=tuple(planned),
        accepted=accepted,
    )


def _configuration(target: _Target) -> dict:
    from .base import descriptor_configuration

    profile = target.counters["embedding"]
    return {
        GENERATION_PROFILE_KEY: CONNECTOR_PROFILE,
        "embedding_profile": profile.descriptor(),
        **descriptor_configuration(target.descriptor, target.registry),
        "mapping": target.mapping.model_dump(mode="json"),
        "partition": target.partition,
        "derivation": {
            "sync": SYNC_RULE_VERSION,
            "binder": BINDER_VERSION,
            "render": RENDER_RULE_VERSION,
            "keys": KEY_RULE_VERSION,
            "classifier": CLASSIFIER_VERSION,
        },
    }


def _manifest_policy(run: ConnectorRun, now):
    """The one local grant the inventory manifest carries (`code_generation._policy`'s shape)."""
    control = run.guard.source_control
    policy = k.AccessPolicy(
        workspace_id=control.workspace_id,
        origin="local_curated",
        scope_key=f"source:{control.source_id}:{CONNECTOR_SCOPE}",
        mode="workspace",
        verified_at=now,
    )
    existing = run.store._knowledge_get("AccessPolicy", policy.id)
    return (existing, ()) if existing is not None else (policy, (policy,))


def _manifest_pair(store, target: _Target, payload: dict, policy: k.AccessPolicy, now):
    """`connector-inventory-v1`, written to the raw store and bound as a local manifest artifact.

    A stored row wins whole. `observed_at` is outside revision identity, so a rebuilt pair would
    otherwise carry a new instant under the same id and `BuildAuthority._inventory` would refuse
    the accepted inputs ("Accepted record differs from current stored identity") on every rerun.
    """
    body = canonical_json(payload).encode("utf-8")
    raw = target.raw_store.put_bytes(body)
    artifact = k.Artifact(
        workspace_id=target.workspace_id,
        source_id=target.source_id,
        kind="manifest",
        external_id=CONNECTOR_MANIFEST_EXTERNAL_ID,
        canonical_uri=f"source:{target.source_id}/{CONNECTOR_MANIFEST_EXTERNAL_ID}",
        policy_id=policy.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        content_hash=text_hash(canonical_json(payload)),
        raw_uri=raw.uri,
        observed_at=now,
        lifecycle="active",
        metadata_json=canonical_json({CONNECTOR_MANIFEST_KEY: payload}),
    )
    stored_artifact = store._knowledge_get("Artifact", artifact.id)
    stored_revision = store._knowledge_get("ArtifactRevision", revision.id)
    return (
        stored_artifact if stored_artifact is not None else artifact,
        stored_revision if stored_revision is not None else revision,
    )


# ------------------------------------------------------------------ step 5: emit


def _emit_one(connector, revision_input: RevisionInput, mapping: TypeMapping) -> EmissionBatch:
    """The worker's whole body: the guard is entered *inside* the worker thread (ruling R65)."""
    with guard.forbid_effects():
        return connector.emit(revision_input, mapping)


def _emit(run: ConnectorRun, target: _Target, inputs: _SyncInputs, raw_store, options):
    """Deviation DV1: every member revision is emitted, not only the changed ones."""
    revisions = []
    for artifact, revision in inputs.pairs:
        metadata = json.loads(revision.metadata_json)
        span_policy_id = metadata.get("span_policy_id") or artifact.policy_id
        data = raw_store.read_bytes(
            RawArtifact(revision.raw_uri, revision.content_hash, int(metadata["raw_bytes"]))
        )
        revisions.append(
            RevisionInput(
                partition=target.partition,
                artifact=artifact,
                revision=revision,
                data=data,
                config=target.config,
                mapping=target.mapping,
                registry=target.registry,
                span_policy_id=span_policy_id,
            )
        )
    results = []
    with ThreadPoolExecutor(max_workers=max(1, options.emit_workers)) as pool:
        futures = [
            (
                revision_input,
                pool.submit(copy_context().run, _emit_one, target.connector, revision_input, target.mapping),
            )
            for revision_input in revisions
        ]
        for revision_input, future in futures:
            try:
                batch = future.result(timeout=options.emit_timeout_seconds)
            except TimeoutError as error:
                raise ConnectorContractViolation("emit exceeded its time budget") from error
            except (guard.EmitSideEffect, ContractError) as error:
                raise ConnectorContractViolation(str(error)) from error
            except BaseException as error:  # noqa: BLE001 - a revision-level parse failure
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                target.count("emit_failed")
                target.counters.setdefault("emit_failed_families", {})
                families = target.counters["emit_failed_families"]
                family = target.descriptor.families[0]
                families[family] = families.get(family, 0) + 1
                continue
            if len(batch.nodes) + len(batch.edges) + len(batch.passages) + len(batch.units) > (
                options.max_batch_records
            ):
                raise ConnectorSyncRefused("An emission batch exceeds max_batch_records")
            results.append((revision_input, batch))
    for revision_input, batch in results:
        if target.on_batch is not None:
            target.on_batch(revision_input, batch)
    run.check()
    target.fault("after_emit")
    return tuple(results)


# ------------------------------------------------------------------ step 6: bind


def _bind(run: ConnectorRun, target: _Target, inputs: _SyncInputs, results, embeddings):
    context = emit.BindContext(
        registry=target.registry,
        descriptor=target.descriptor,
        connector=target.row,
        generation=inputs.generation,
        workspace_id=target.workspace_id,
        source_id=target.source_id,
        partition=target.partition,
    )
    bound = (
        emit.merge_bound(
            [emit.bind_batch(context, revision_input, batch) for revision_input, batch in results]
        )
        if results
        else None
    )
    vectors = _vectors(embeddings, [row.text for row in bound.passages]) if bound else ()
    run.check()
    all_pairs = (*inputs.pairs, inputs.manifest_pair)
    members = tuple(
        k.GenerationMember(generation_id=inputs.generation.id, artifact_revision_id=revision.id)
        for _artifact, revision in all_pairs
    )
    staged = (
        tuple(
            staged_records.StagedPassage(row=row.native_row(), embedding=vector)
            for row, vector in zip(bound.passages, vectors, strict=True)
        )
        if bound
        else ()
    )
    bundle = staged_records.RecordBundle(
        generation=inputs.generation,
        configuration_json=inputs.configuration_json,
        accepted_pairs=all_pairs,
        manifest_revision=inputs.manifest_pair[1],
        revision_members=members,
        spans=bound.spans if bound else (),
        objects=bound.objects if bound else (),
        observations=bound.observations if bound else (),
        views=bound.views if bound else (),
        derived_records=bound.derived_records if bound else (),
        derived_dependencies=bound.derived_dependencies if bound else (),
        passages=staged,
        units=bound.units if bound else (),
        assertions=bound.assertions if bound else (),
        versions=bound.versions if bound else (),
        supports=bound.supports if bound else (),
        evidence_members=bound.evidence_members if bound else (),
    )
    target.fault("after_bind")
    return bundle, (bound.coverage if bound else None)


def _vectors(embeddings, texts):
    if not texts:
        return ()
    matrix = embeddings.embed(list(texts), kind="document")
    if len(matrix) != len(texts):
        raise ValueError("Embedding result inventory differs")
    return tuple(tuple(float(value) for value in row.tolist()) for row in matrix)


def _coverage_json(target: _Target, coverage, inventory: str) -> dict:
    """`Generation.coverage_json`'s connector section, plus the S1a-fix exclusions counter.

    `excluded_vocabulary` is empty by construction: every record this generation holds was built
    under the frozen current registry and passed `Registry.check_record`, so a projection of it
    leaves nothing out. The key is written anyway, so a reader of an old generation can tell "no
    exclusions" from "this build never counted them"; read-time counts are Task 15's.
    """
    return {
        "connector": target.descriptor.name,
        "partition": target.partition,
        "emission": coverage.to_json() if coverage is not None else {},
        "pages": target.counters.get("pages", 0),
        "fetched": target.counters.get("fetched", 0),
        "deleted": target.counters.get("deleted", 0),
        "policy_updates": target.counters.get("policy_updates", 0),
        "emit_failed": dict(sorted(target.counters.get("emit_failed_families", {}).items())),
        "inventory": inventory,
        "reconcile_unconfirmed": target.counters.get("reconcile_unconfirmed", 0),
        "units_embedded": "downstream",
        "excluded_vocabulary": {},
    }


# ------------------------------------------------------------------ steps 7 and 8


def _install(run: ConnectorRun, target: _Target, bundle, inputs: _SyncInputs, coverage_json: str):
    """`code_generation._install`'s order of store calls, without its bootstrap managed flip.

    The flip already happened at capture -- the first `Artifact` put makes the source managed
    (`store/authorization.py:187`) -- so the expected epoch carries no `+ int(not managed)` term.
    """
    store, gen = run.store, inputs.generation
    run.guard.check_local()
    original = run.guard.source_control
    source = store.get_source(gen.source_id)
    previous = store._knowledge_get("MaintenanceJob", source.get("active_build_id"))
    if previous is not None and previous.status == "running" and previous.lease_expires_at > store._now():
        raise BuildBusy("Source already has a live build holder")
    store.recover_generation_builds(source_id=gen.source_id)
    expected_epoch = run.guard.expected_authorization_epoch
    for policy in inputs.planned_policies:
        if store._knowledge_get("AccessPolicy", policy.id) is None:
            expected_epoch += 1
            store.put_knowledge(policy)
    existing = store._generation(gen.id) if store._knowledge_get("Generation", gen.id) else None
    if existing is None:
        store.put_knowledge(gen.replace(coverage_json=coverage_json))
    store.begin_managed_source(gen.source_id)
    expiry = store._now() + timedelta(seconds=run.options.lease_duration_seconds)
    if existing is None:
        job = store.claim_generation_build(
            gen.id, job_key=target.operation_id, lease_owner=run.owner, lease_expires_at=expiry
        )
    else:
        job = store.reclaim_generation_build(
            gen.id,
            job_key=target.operation_id,
            lease_owner=run.owner,
            lease_expires_at=expiry,
            expected_manifest_hash=gen.manifest_hash,
        )
    with store.generation_write(gen.id, **credentials(job)):
        for artifact, revision in bundle.accepted_pairs:
            store.put_knowledge(artifact)
            store.put_knowledge(revision)
        for member in bundle.revision_members:
            store.put_knowledge(member)
    store.bind_generation_embedding_profile(gen.id, bundle.manifest_revision.id, **credentials(job))
    if store.authorization_epoch() != expected_epoch:
        raise AuthorizationChanged("Setup changed authorization beyond its explicit local grants")
    fresh = capture_build_authority(
        store,
        source_id=gen.source_id,
        actor=run.actor,
        accepted=replace(inputs.accepted, planned_policies=()),
        clock=store._now,
    )
    if (
        fresh.expected_authorization_epoch != expected_epoch
        or fresh.source_control != replace(original, managed=True)
        or fresh.expected_suppression_epoch != run.guard.expected_suppression_epoch
    ):
        fresh.close()
        raise AuthorizationChanged("Setup changed unrelated source controls")
    return job, fresh


def _batch_bytes(batch) -> int:
    return len(canonical_json([staged_records._payload(record) for record in batch]).encode("utf-8"))


def _stage(run: ConnectorRun, target: _Target, bundle):
    """Durable staging over many transactions, the guard checked between each (`_write`'s rule)."""
    resume = staged_records.probe_staged_records(run.store, bundle)
    rebaselines = 0
    for batch in staged_records._write_batches(bundle, batch_size=run.options.batch_size, resume=resume):
        rebaselines += rebaseline_between_batches(run)
        run.check()
        if _batch_bytes(batch) > run.options.max_batch_payload_bytes:
            raise ConnectorSyncRefused("A staged record batch exceeds the configured payload ceiling")
        target.fault("before_batch")
        staged_records._write_batch(
            run.store, bundle, batch, **credentials(run.job), **authority_fields(run.guard)
        )
        rebaselines += rebaseline_between_batches(run)
        run.check()
    rebaselines += rebaseline_between_batches(run)
    run.check()
    target.fault("before_seal")
    staged_records._seal(run.store, bundle, **credentials(run.job), **authority_fields(run.guard))
    run.check()
    return rebaselines, _resumed_batches(bundle, resume)


def _resumed_batches(bundle, resume) -> int:
    installed = len(bundle.revision_members)
    return sum(1 for index in resume.skipped if index > installed)


def _publish(run: ConnectorRun, target: _Target, bundle, inputs: _SyncInputs, *, resumed, rebaselines):
    """One short transaction: the atomic swap, the cursor release and the fresh-authority compare."""
    store, gen, guard_ = run.store, inputs.generation, run.guard
    _check_sync(store, run.sync_run)
    guard_.check_local()
    target.fault("before_publish")
    event = store.publish_staged_generation(
        gen.id,
        expected_parent_id=gen.parent_id,
        **credentials(run.job),
        expected_suppression_epoch=guard_.expected_suppression_epoch,
        published_at=store._now(),
    )
    if (store.authorization_epoch(), store.suppression_epoch()) != (
        guard_.expected_authorization_epoch,
        guard_.expected_suppression_epoch,
    ):
        raise AuthorizationChanged("Authority changed during publication")
    counts = generation_counts(store, gen.id)
    source = store.get_source(gen.source_id)
    meta = dict(source.get("meta") or {}) | {
        "chunks": counts.passages,
        "documents": len(inputs.pairs),
    }
    store.update_source(
        gen.source_id,
        status="ready",
        stage="ready",
        progress_done=counts.passages,
        progress_total=counts.passages,
        error=None,
        meta_json=canonical_json(meta),
    )
    now = store._now()
    state = store._knowledge_get("SyncState", _sync_state_identity(target))
    stored = _cursor_state(state)
    complete = target.counters.get("inventory") == "complete"
    store.update_knowledge(
        state.replace(
            cursor_json=canonical_json(
                {"version": 1, "cursor": stored.get("cursor"), "pending": None, "scan": None}
            ),
            last_success_at=now,
            last_reconciled_at=now if complete else state.last_reconciled_at,
            error_code=None,
        )
    )
    held = store._knowledge_get("SyncRun", run.sync_run.id)
    store.update_knowledge(
        held.replace(
            status="completed", phase="complete", lease_owner=None, lease_expires_at=None, error_code=None
        )
    )
    fresh = capture_build_authority(
        store,
        source_id=gen.source_id,
        actor=run.actor,
        accepted=replace(inputs.accepted, planned_policies=()),
        clock=store._now,
    )
    if fresh.source_control != replace(guard_.source_control, active_generation_id=gen.id) or (
        fresh.expected_authorization_epoch,
        fresh.expected_suppression_epoch,
    ) != (guard_.expected_authorization_epoch, guard_.expected_suppression_epoch):
        fresh.close()
        raise AuthorizationChanged("Publication changed unrelated authority")
    receipt = BuildReceipt(
        gen.source_id,
        gen.id,
        event,
        bundle.manifest_revision.content_hash,
        "published",
        resumed,
        rebaselines,
    )
    return receipt, fresh


# ------------------------------------------------------------------ step 9: reconcile


def _reconcile(run: ConnectorRun, target: _Target, state: k.SyncState, parent_id: str | None) -> None:
    """Inferred deletion, only from a completed scan (design section 7 step 9, R-S3-5)."""
    store = run.store
    scan = _cursor_state(state).get("scan")
    if not scan or not scan.get("complete"):
        return
    if (scan.get("config_hash"), scan.get("credential_ref")) != (
        text_hash(target.config.model_dump_json()),
        target.row.credential_ref,
    ):
        return
    seen = set(_read_seen(target.raw_store, scan.get("seen")))
    confirmed = []
    for artifact_id in sorted(_member_revisions(store, parent_id)):
        if artifact_id in seen:
            continue
        artifact = store._knowledge_get("Artifact", artifact_id)
        if artifact is None or artifact.deleted_at is not None:
            continue
        ref = ExternalRef(
            partition=target.partition, artifact_kind=artifact.kind, external_id=artifact.external_id
        )
        try:
            target.connector.fetch(target.config, ref)
        except ProviderNotFoundError:
            confirmed.append(artifact)
            continue
        except BaseException:  # noqa: BLE001 - any other error keeps the artifact
            target.count("reconcile_unconfirmed")
            continue
    if not confirmed:
        return
    now = store._now()
    pending = dict(_read_pending(target.raw_store, _cursor_state(state).get("pending")))
    with store.transaction():
        store._lock_source(target.source_id)
        _check_sync(store, run.sync_run)
        for artifact in confirmed:
            current = store._knowledge_get("Artifact", artifact.id)
            if current.deleted_at is None:
                store.update_knowledge(current.replace(deleted_at=now))
                target.count("deleted")
            pending[artifact.id] = ["delete", None, current.policy_id]
        stored = _cursor_state(state)
        store.update_knowledge(
            store._knowledge_get("SyncState", state.id).replace(
                cursor_json=canonical_json(
                    {
                        "version": 1,
                        "cursor": stored.get("cursor"),
                        "pending": _pending_uri(target.raw_store, pending),
                        "scan": stored.get("scan"),
                    }
                )
            )
        )


def _read_seen(raw_store, reference: dict | None) -> list[str]:
    payload = _read_raw(raw_store, reference)
    return payload["seen"] if payload else []


def _write_seen(raw_store, seen) -> dict:
    return _raw_reference(raw_store, {"version": 1, "seen": sorted(seen)})


# ------------------------------------------------------------------ the entry


def _entry_checks(ctx, connector, *, config, partition, actor, registry, operation_id, should_stop, row):
    if registry is not current_registry() or not registry.frozen:
        raise ConnectorSyncRefused("Sync requires the frozen current registry")
    descriptor = connector.descriptor
    if descriptor.capabilities.derivation != "emit":
        raise ConnectorSyncRefused("A coordinator-lane connector syncs through its lane, not sync_connector")
    descriptor.validate_against(registry)
    _registered_extension(descriptor, registry)
    if type(config) is not descriptor.config_model:
        raise ConnectorSyncRefused("Connector configuration is not the descriptor's model")
    if type(actor) is not BuildActor or actor.kind != "trusted_local":
        raise ConnectorSyncRefused("Connector syncs run as the trusted local maintenance actor")
    if ctx.store.in_ambient_transaction():
        raise ConnectorSyncRefused("Sync requires no ambient transaction")
    if type(operation_id) is not str or not operation_id or len(operation_id) > 256:
        raise ConnectorSyncRefused("Stable operation identity is required")
    if not callable(should_stop):
        raise ConnectorSyncRefused("Live cancellation is required")
    if not row.enabled:
        raise ConnectorSyncRefused(f"Connector instance {row.id} is not enabled")
    if row.kind != descriptor.name or row.instance_url != getattr(config, "instance_url", row.instance_url):
        raise ConnectorSyncRefused("Connector instance does not match its descriptor or configuration")
    credential_refs.refuse_inline_secrets(config)
    return descriptor


def _registered_extension(descriptor: ConnectorDescriptor, registry: Registry) -> None:
    """Rulings R32 and R46: registered, and each registered definition equal to the descriptor's."""
    extension = descriptor.extension
    for definition in extension.object_kinds:
        if registry.object_kind(definition.name) != definition:
            raise ConnectorSyncRefused(
                f"Object kind {definition.name} differs from the registered definition"
            )
    for definition in extension.predicates:
        if registry.predicate(definition.name) != definition:
            raise ConnectorSyncRefused(f"Predicate {definition.name} differs from the registered definition")
    for definition in extension.locator_kinds:
        if registry.locator_kind(definition.name) != definition:
            raise ConnectorSyncRefused(
                f"Locator kind {definition.name} differs from the registered definition"
            )
    for definition in extension.evidence_sources:
        if registry.evidence_source_definition(definition.name) != definition:
            raise ConnectorSyncRefused(
                f"Evidence source {definition.name} differs from the registered definition"
            )
    for name in extension.connector_kinds:
        registry.connector_kind(name)
    for name in extension.artifact_kinds:
        registry.artifact_kind(name)


def sync_connector(
    ctx,
    connector,
    *,
    connector_id: str,
    config: BaseModel,
    partition: str,
    actor: BuildActor,
    registry: Registry,
    options: SyncOptions,
    raw_store: RawArtifactStore,
    embedding_spec: EmbeddingSpec,
    operation_id: str,
    should_stop: Callable[[], bool],
    on_progress: Callable[[BuildProgress], None] | None = None,
    on_batch: Callable[[RevisionInput, EmissionBatch], None] | None = None,
    embedding_cache: EmbeddingCache | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> SyncReceipt:
    """Sync one connector partition: lease, page, capture, checkpoint, emit, bind, stage, publish."""
    if type(options) is not SyncOptions or type(embedding_spec) is not EmbeddingSpec:
        raise ConnectorSyncRefused("Explicit immutable sync options and embedding spec are required")
    row = ctx.store._knowledge_get("Connector", connector_id)
    if row is None:
        raise ConnectorSyncRefused("Unknown connector instance")
    descriptor = _entry_checks(
        ctx,
        connector,
        config=config,
        partition=partition,
        actor=actor,
        registry=registry,
        operation_id=operation_id,
        should_stop=should_stop,
        row=row,
    )
    classification = load_classification(row, partition)
    mapping = classification.mapping
    mapping.validate_against(registry)
    source_id = connector_source(
        ctx.store, connector=row, partition=partition, name=f"{row.kind} {partition}"
    )
    target = _Target(
        connector=connector,
        row=row,
        descriptor=descriptor,
        config=config,
        partition=partition,
        source_id=source_id,
        workspace_id=row.workspace_id,
        registry=registry,
        mapping=mapping,
        raw_store=raw_store,
        options=options,
        operation_id=operation_id,
        fault_hook=fault_hook,
        on_batch=on_batch,
    )
    run = ConnectorRun(ctx, actor, source_id, options, should_stop, on_progress)
    installed = False
    try:
        run.start()
        run.progress("capture")
        resolved = resolve_embedding_profile(ctx.ollama, spec=embedding_spec, authorization_check=run.check)
        target.counters["embedding"] = validate_profile_descriptor(resolved.descriptor())
        _leased, state = _lease(run, target, options)
        state, inventory = _pages(run, target, state, options)
        run.pause()
        run.check()
        _reconcile(run, target, state, run.guard.source_control.active_generation_id)
        # Capture's own epoch bumps -- new policies, `policy_id` and `deleted_at` updates -- all
        # happened inside this run, so the guard is re-captured after the last checkpoint and
        # before `bind_inputs`, never across a checkpoint (decision 11).
        run.adopt(capture_build_authority(ctx.store, source_id=source_id, actor=actor, clock=ctx.store._now))
        state = ctx.store._knowledge_get("SyncState", _sync_state_identity(target))
        target.counters["inventory"] = inventory
        now = ctx.store._now()
        inputs = _inputs(run, target, state, now)
        if inputs is None:
            _finish_without_build(run, target, state)
            return _receipt(target, "no_changes", None, None, inventory, {})
        run.generation = inputs.generation
        run.adopt(run.guard.bind_inputs(inputs.accepted))
        manifest_sha = inputs.manifest_pair[1].content_hash
        if current := _prior(run, target, inputs, manifest_sha):
            run.pause()
            run.check()
            _finish_without_build(run, target, state)
            return _receipt(target, current.outcome, current.generation_id, current, inventory, {})
        run.start()
        embeddings = ProfiledEmbeddings(
            ctx.ollama, resolved, cache=embedding_cache, authorization_check=run.check
        )
        results = _emit(run, target, inputs, raw_store, options)
        bundle, coverage = _bind(run, target, inputs, results, embeddings)
        coverage_json = canonical_json(_coverage_json(target, coverage, inventory))
        run.pause()
        run.check()
        with ctx.store.transaction():
            ctx.store._lock_source(source_id)
            job, fresh = _install(run, target, bundle, inputs, coverage_json)
        run.job = job
        run.adopt(fresh)
        installed = True
        target.fault("after_install")
        run.start()
        rebaselines, resumed = _stage(run, target, bundle)
        embeddings.validate()
        run.pause()
        run.check()
        with ctx.store.transaction():
            ctx.store._lock_source(source_id)
            run.guard.check_local()
            receipt, final_guard = _publish(
                run, target, bundle, inputs, resumed=resumed, rebaselines=rebaselines
            )
        run.receipt = receipt
        run.job = None
        run.sync_run = None
        run.adopt(final_guard)
        run.guard.check()
        target.fault("after_publish")
        return _receipt(
            target,
            "published",
            receipt.generation_id,
            receipt,
            inventory,
            json.loads(coverage_json),
        )
    except BaseException as error:
        try:
            run.pause()
        except BaseException:  # noqa: BLE001 - the original failure wins
            pass
        if installed and run.job is not None and run.receipt is None:
            try:
                ctx.store.fail_generation_build(
                    run.generation.id,
                    **credentials(run.job),
                    error_code="build_cancelled" if isinstance(error, BuildCancelled) else "build_failed",
                )
            except (ValueError, AuthorizationChanged):
                pass  # A lost fence or a committed publication belongs to recovery.
        _release(run, target, error_code=_error_code(error))
        if type(error) is BuildCancelled:
            # The shared run state raises the base class; the kit's callers catch this one.
            raise ConnectorSyncCancelled(str(error)) from error
        raise
    finally:
        run.close()


def _error_code(error: BaseException) -> str:
    if isinstance(error, ConnectorSyncBusy):
        return "lease_lost"
    if isinstance(error, BuildCancelled):
        return "sync_cancelled"
    return "sync_failed"


def _prior(run: ConnectorRun, target: _Target, inputs: _SyncInputs, manifest_sha: str):
    """`build_run.prior_receipt`, with `already_current` suppressed after a policy change.

    Review M4 and ruling R52 put the "nothing changed" decision on the candidate generation, so a
    policy-only change reaches here with a manifest equal to the parent's. Returning
    `already_current` there would refuse to republish, and CK3 requires a policy-only change to
    publish (row M8b). The `operation_id` replay branch still answers.
    """
    result = prior_receipt(run, inputs.generation, manifest_sha, target.operation_id)
    if result is not None and result.outcome == "already_current" and target.counters.get("policy_updates"):
        return None
    return result


def _pages(run: ConnectorRun, target: _Target, state: k.SyncState, options):
    """Steps 2-4 over at most `max_pages` pages, with the inventory scan of section 6.4."""
    store = run.store
    now = store._now()
    scanning = target.descriptor.capabilities.inventory and (
        options.reconcile
        or reconcile_due(state, now=now, interval=timedelta(seconds=options.reconcile_interval_seconds))
    )
    stored = _cursor_state(state)
    cursor = None
    if not scanning and stored.get("cursor") is not None:
        cursor = SyncCursor.model_validate(stored["cursor"])
    scan = None
    seen: set[str] = set()
    if scanning:
        scan = {
            "mode": "inventory",
            "started_at": now.isoformat(),
            "complete": False,
            "config_hash": text_hash(target.config.model_dump_json()),
            "credential_ref": target.row.credential_ref,
            "seen": None,
        }
    pages = 0
    complete = False
    while pages < options.max_pages:
        page = _next_page(run, target, cursor, options)
        captured = _capture(run, target, page, target.raw_store, options)
        if scan is not None:
            seen.update(record.artifact_id for record in captured.records)
            scan = {**scan, "complete": bool(page.complete), "seen": _write_seen(target.raw_store, seen)}
        state = _checkpoint(run, target, captured, state, scan)
        # Decision 11: capture's own epoch bumps (new policies, `policy_id` and `deleted_at`
        # updates) are this run's, so the authority is re-captured after every checkpoint and no
        # guard ever spans one. `run.check()` between pages then compares live epochs.
        run.adopt(
            capture_build_authority(
                run.store, source_id=target.source_id, actor=run.actor, clock=run.store._now
            )
        )
        pages += 1
        complete = bool(page.complete)
        cursor = captured.next_cursor
        if complete or cursor is None:
            break
    if scan is None:
        inventory = "not_scanned"
    else:
        inventory = "complete" if complete else "partial"
    return state, inventory


def _finish_without_build(run: ConnectorRun, target: _Target, state: k.SyncState) -> None:
    """`no_changes`, `already_current` and `already_published`: clear pending, release the lease."""
    store = run.store
    now = store._now()
    with store.transaction():
        store._lock_source(target.source_id)
        _check_sync(store, run.sync_run)
        current = store._knowledge_get("SyncState", state.id)
        stored = _cursor_state(current)
        store.update_knowledge(
            current.replace(
                cursor_json=canonical_json(
                    {"version": 1, "cursor": stored.get("cursor"), "pending": None, "scan": None}
                ),
                last_success_at=now,
                last_reconciled_at=now
                if target.counters.get("inventory") == "complete"
                else current.last_reconciled_at,
                error_code=None,
            )
        )
        held = store._knowledge_get("SyncRun", run.sync_run.id)
        store.update_knowledge(
            held.replace(
                status="completed",
                phase="complete",
                lease_owner=None,
                lease_expires_at=None,
                error_code=None,
            )
        )
    run.sync_run = None


def _receipt(target: _Target, outcome, generation_id, build, inventory, coverage) -> SyncReceipt:
    return SyncReceipt(
        source_id=target.source_id,
        partition=target.partition,
        outcome=outcome,
        generation_id=generation_id,
        build=build,
        pages=target.counters.get("pages", 0),
        changes=target.counters.get("changes", 0),
        deleted=target.counters.get("deleted", 0),
        policy_updates=target.counters.get("policy_updates", 0),
        inventory=inventory,
        coverage=coverage,
    )
