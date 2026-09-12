"""Request-scoped generation pins with live authorization and renewable retention.

The store owns atomic pointer selection/reference exclusion with collection.
These handles are never access grants: every use rechecks the original audience.
Legacy graphs are pinned separately in memory, not represented as durable history.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from uuid import uuid4

from ..access import Access
from .access import AuthorizationChanged, EvidenceSelection, utc_now
from .model import CurrentSelector, QuerySnapshot, SnapshotSource
from .query_access import current_access


class QuerySnapshotUnavailable(ValueError):
    """The requested current source set cannot produce compatible sealed evidence."""


def _now(clock):
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Snapshot clock must be timezone aware")
    return value.astimezone(UTC)


@dataclass
class QuerySnapshotBundle:
    store: object = field(repr=False)
    snapshots: tuple[QuerySnapshot, ...]
    proofs: tuple = field(repr=False)
    references: tuple = field(repr=False)
    authorization_epoch: int = field(repr=False)
    lease_owner: str = field(repr=False)
    lease_duration: timedelta = field(repr=False)
    clock: object = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def generation_ids(self) -> frozenset[str]:
        return frozenset(source.generation_id for snapshot in self.snapshots for source in snapshot.sources)

    def validate(self) -> None:
        if self._closed:
            raise AuthorizationChanged("Query snapshot is closed")
        with self.store.transaction():
            self._validate_authorization()
            now = _now(self.clock)
            renewed = []
            for reference in self.references:
                try:
                    # Always ask storage: a separately released reference must not
                    # remain usable just because this handle cached its old expiry.
                    renewed.append(
                        self.store.renew_snapshot_reference(
                            reference.id,
                            lease_owner=self.lease_owner,
                            lease_expires_at=now + self.lease_duration,
                        )
                    )
                except ValueError as error:
                    raise AuthorizationChanged("Query snapshot lease is unavailable") from error
            self._validate_authorization()
            self.references = tuple(renewed)

    def _validate_authorization(self):
        if self.store.authorization_epoch() != self.authorization_epoch:
            raise AuthorizationChanged("Permissions changed during snapshot use")
        for resolver, proof in self.proofs:
            resolver.validate_current(proof)
        if self.store.authorization_epoch() != self.authorization_epoch:
            raise AuthorizationChanged("Permissions changed during snapshot use")

    def close(self) -> None:
        if self._closed:
            return
        with self.store.transaction():
            for reference in self.references:
                self.store.release_snapshot_reference(reference.id, lease_owner=self.lease_owner)
        self._closed = True

    def __enter__(self):
        try:
            self.validate()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, error_type, error, traceback):
        self.close()
        return False


def acquire_query_snapshots(
    store,
    access: Access,
    *,
    source_ids: frozenset[str],
    profile_fingerprint: str | None = None,
    source_profiles: Mapping[str, str] | None = None,
    settings_fingerprint: str,
    lease_duration: timedelta = timedelta(minutes=5),
    clock=utc_now,
) -> QuerySnapshotBundle:
    """Acquire one snapshot per workspace, all references in one transaction.

    The caller supplies managed sources only. Empty input creates no durable
    snapshot; it cannot be used to claim reconstruction of legacy source data.
    """
    if lease_duration <= timedelta(0):
        raise ValueError("Snapshot lease duration must be positive")
    if not isinstance(source_ids, frozenset) or any(not isinstance(s, str) or not s for s in source_ids):
        raise ValueError("Snapshot source IDs must be immutable nonempty strings")
    if (profile_fingerprint is None) == (source_profiles is None):
        raise ValueError("Exactly one snapshot profile selector is required")
    if source_profiles is not None:
        if not isinstance(source_profiles, Mapping):
            raise ValueError("Snapshot source profiles require a mapping")
        profiles = dict(source_profiles)
        if set(profiles) != source_ids or any(
            type(k) is not str or type(v) is not str or not v for k, v in profiles.items()
        ):
            raise ValueError("Snapshot profile keys must exactly match selected sources")
    else:
        if type(profile_fingerprint) is not str or not profile_fingerprint:
            raise ValueError("Snapshot profile must be a nonempty string")
        profiles = dict.fromkeys(source_ids, profile_fingerprint)
    owner, request_key = str(uuid4()), str(uuid4())
    with store.transaction():
        epoch = store.authorization_epoch()
        audience = current_access(store, access)
        if audience is None:
            raise ValueError("Snapshots require an explicit audience")
        now = _now(clock)
        sources = {row["id"]: row for row in store.list_sources(audience)}
        if not source_ids <= sources.keys():
            raise QuerySnapshotUnavailable("Requested source is unavailable")
        by_workspace = {}
        for identity in sorted(source_ids):
            source = sources[identity]
            generation_id = source.get("active_generation_id")
            generation = store._knowledge_get("Generation", generation_id) if generation_id else None
            if (
                generation is None
                or generation.status != "active"
                or generation.source_id != identity
                or generation.embedding_profile != profiles[identity]
            ):
                raise QuerySnapshotUnavailable("Source lacks a compatible active generation/profile")
            by_workspace.setdefault((source["workspace_id"], profiles[identity]), []).append(
                SnapshotSource(source_id=identity, generation_id=generation.id)
            )
        snapshots, proofs, references = [], [], []
        for (workspace, profile), selected in sorted(by_workspace.items()):
            selection = EvidenceSelection(
                generation_ids=frozenset(source.generation_id for source in selected),
                require_exact_membership=True,
            )
            resolver, proof = store._reader_proof(
                workspace, audience, expected_epoch=epoch, selection=selection
            )
            snapshot = QuerySnapshot(
                workspace_id=workspace,
                sources=tuple(selected),
                knowledge_cutoff=now,
                temporal=CurrentSelector(),
                profile_fingerprint=profile,
                settings_fingerprint=settings_fingerprint,
                policy_fingerprint=proof.policy_fingerprint,
                suppression_epoch=store.suppression_epoch(),
                created_at=now,
            )
            reference = store.acquire_snapshot_reference(
                snapshot,
                reference_key=request_key,
                lease_owner=owner,
                lease_expires_at=now + lease_duration,
                require_current=True,
            )
            snapshots.append(snapshot)
            proofs.append((resolver, proof))
            references.append(reference)
        bundle = QuerySnapshotBundle(
            store,
            tuple(snapshots),
            tuple(proofs),
            tuple(references),
            epoch,
            owner,
            lease_duration,
            clock,
        )
        bundle._validate_authorization()
        return bundle


def acquire_history_snapshot(
    store,
    access: Access,
    *,
    history,
    settings_fingerprint: str,
    lease_duration: timedelta = timedelta(minutes=5),
    clock=utc_now,
) -> QuerySnapshotBundle:
    """Pin an already-persisted history manifest for one historical request.

    A history snapshot pins reachability, not serving evidence: it names no active
    generation, so it can never be mistaken for a current answer, and its proof is
    rebuilt and rechecked here and on every later use exactly like a current pin.
    """
    if lease_duration <= timedelta(0):
        raise ValueError("Snapshot lease duration must be positive")
    if type(settings_fingerprint) is not str or not settings_fingerprint:
        raise ValueError("Snapshot settings must be a nonempty fingerprint")
    manifest = history.manifest
    owner, request_key = str(uuid4()), str(uuid4())
    with store.transaction():
        epoch = store.authorization_epoch()
        if current_access(store, access) is None:
            raise ValueError("Snapshots require an explicit audience")
        now = _now(clock)
        resolver = history.resolver
        proof = resolver.build(history.selection)
        if proof.authorization_epoch != epoch:
            raise AuthorizationChanged("Authorization changed during the history read")
        snapshot = QuerySnapshot(
            workspace_id=manifest.workspace_id,
            sources=(),
            history_manifest_ids=(manifest.id,),
            knowledge_cutoff=manifest.knowledge_cutoff,
            temporal=history.selector,
            # No embedding profile is claimed: the manifest itself is what this pin
            # reproduces, and inventing a profile would imply dense reachability.
            profile_fingerprint="history:" + manifest.id,
            settings_fingerprint=settings_fingerprint,
            policy_fingerprint=proof.policy_fingerprint,
            suppression_epoch=store.suppression_epoch(),
            created_at=now,
        )
        reference = store.acquire_snapshot_reference(
            snapshot,
            reference_key=request_key,
            lease_owner=owner,
            lease_expires_at=now + lease_duration,
            require_current=False,
        )
        bundle = QuerySnapshotBundle(
            store, (snapshot,), ((resolver, proof),), (reference,), epoch, owner, lease_duration, clock
        )
        bundle._validate_authorization()
        return bundle
