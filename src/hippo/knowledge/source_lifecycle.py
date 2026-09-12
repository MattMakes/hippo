"""Managed source deletion: an immediate current-view tombstone, never byte erasure.

Deleting a managed source suppresses it from every current view and fences its
builder in one transaction. Published and retired generations, their manifests,
raw references and saved ingress all remain for authorized historical reads.
Physical removal, restoration and retention are separate operations elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from ..access import Access
from ..store.generations import tombstone_scope_key
from .access import AuthorizationChanged, EvidenceAccess
from .build_authority import BuildActor, capture_build_authority

OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
"""Bounded, printable and filesystem-safe: an operation identity is echoed into a receipt."""


class SourceLifecycleError(ValueError):
    """This request cannot be dispatched to managed deletion."""


class UnmanagedSource(SourceLifecycleError):
    """Callers dispatch legacy cleanup themselves before reaching this service."""


class InvalidOperationId(SourceLifecycleError):
    """Operation identities are caller supplied, so they are bounded and closed."""


@dataclass(frozen=True)
class TombstoneReceipt:
    source_id: str
    operation_id: str
    outcome: Literal["tombstoned", "already_tombstoned"]
    suppression_epoch: int
    fencing_token: int
    cancelled_generation_id: str | None
    cancelled_job_id: str | None


def tombstone_managed_source(
    ctx, *, source_id: str, actor: BuildActor, operation_id: str
) -> TombstoneReceipt:
    """Suppress a managed source from the current view and fence its builder.

    Raises `InvalidOperationId` for an unbounded identity, then the same
    `AuthorizationChanged` as any unavailable source when the actor may not
    manage it - including a reader retrying a delete that already committed -
    and only then `UnmanagedSource` when the caller should have dispatched
    legacy cleanup. That order is deliberate: answering "is this source
    managed?" before the actor has standing would make this refusal an oracle.
    """
    if type(actor) is not BuildActor:
        raise SourceLifecycleError("Explicit build actor required")
    if type(operation_id) is not str or OPERATION_ID.match(operation_id) is None:
        raise InvalidOperationId("Operation identity must be a bounded printable token")
    store = ctx.store
    try:
        guard = capture_build_authority(store, source_id=source_id, actor=actor)
    except AuthorizationChanged:
        # A committed tombstone denies every current view, our own replay
        # included, so a reader retry is indistinguishable from any other
        # unavailable source. Only an established internal authority reads the
        # receipt back, and only for the operation that wrote it.
        receipt = _replayed_receipt(store, source_id, actor, operation_id)
        if receipt is None:
            raise
        return receipt
    try:
        if not store.source_is_managed(source_id):
            raise UnmanagedSource("Legacy cleanup owns unmanaged sources")
        # Cooperative cancellation is a courtesy, not the safety mechanism: it is
        # requested and never awaited, so a blocked model call cannot delay this.
        ctx.jobs.cancel(f"index:{source_id}")
        now = datetime.now(UTC)
        with store.transaction():
            store._lock_source(source_id)
            guard.check_local()
            if not store.source_is_managed(source_id):
                raise UnmanagedSource("Legacy cleanup owns unmanaged sources")
            result = store.apply_source_tombstone(source_id, operation_id=operation_id, created_at=now)
    finally:
        guard.close()
    return TombstoneReceipt(
        source_id=source_id,
        operation_id=operation_id,
        outcome="tombstoned",
        suppression_epoch=result.suppression_epoch,
        fencing_token=result.fencing_token,
        cancelled_generation_id=result.cancelled_generation_id,
        cancelled_job_id=result.cancelled_job_id,
    )


def _replayed_receipt(store, source_id, actor, operation_id) -> TombstoneReceipt | None:
    """The prior receipt, for an internal caller repeating its own operation."""
    if actor.kind != "trusted_local":
        return None
    source = store.get_source(source_id)
    if not source or not source.get("workspace_id") or not store.source_is_managed(source_id):
        return None
    authorities = store.get_meta("reviewed_mapping_authorities") or []
    if type(authorities) is not list or any(type(value) is not str or not value for value in authorities):
        raise AuthorizationChanged("Reviewed identity mapping configuration is invalid")
    engine = EvidenceAccess(
        store,
        source["workspace_id"],
        Access(unrestricted=True, audience_kind="internal"),
        mapping_authorities=frozenset(authorities),
    )
    # A current-only tombstone is deliberately invisible to this history check,
    # which is what lets an internal caller prove its standing after committing.
    engine.require_source(source_id, query_mode="history")
    committed = next(
        (
            row
            for row in store._knowledge_rows("Suppression")
            if row.target_kind == "source"
            and row.target_id == source_id
            and row.reason == "tombstone"
            and row.view_applicability == "current_only"
            and row.scope_key == tombstone_scope_key(source_id)
            and row.restoration_barrier == operation_id
        ),
        None,
    )
    if committed is None:
        return None
    generation_id, job_id = _cancelled_build(store, source_id)
    return TombstoneReceipt(
        source_id=source_id,
        operation_id=operation_id,
        outcome="already_tombstoned",
        suppression_epoch=committed.epoch,
        fencing_token=int(source.get("build_fencing_token") or 0),
        cancelled_generation_id=generation_id,
        cancelled_job_id=job_id,
    )


def _cancelled_build(store, source_id):
    jobs = [
        job
        for job in store._knowledge_rows("MaintenanceJob")
        if job.source_id == source_id
        and job.kind == "rebuild"
        and job.status == "cancelled"
        and job.error_code == "source_tombstoned"
    ]
    if len(jobs) != 1:
        return None, None
    return jobs[0].input_fingerprint, jobs[0].id
