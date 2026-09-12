"""Durable snapshot reachability shares the publication/collection lock boundary."""

from dataclasses import dataclass
from typing import Literal

from ..knowledge import model as k


class SnapshotUnavailable(ValueError):
    """Snapshot inputs need a strict rebuild or are no longer available."""


@dataclass(frozen=True)
class CollectionResult:
    generation_id: str
    removed_records: int = 0
    removed_native_ids: tuple[str, ...] = ()
    blob_references: tuple[str, ...] = ()
    blocked_reason: str | None = None


@dataclass(frozen=True)
class PurgedEvidence:
    """A named removal, never retained text: a purged ID resolves to nothing else."""

    target_kind: Literal["revision"]
    target_id: str
    code: Literal["evidence_purged"] = "evidence_purged"


@dataclass(frozen=True)
class RecoveryResult:
    failed_builds: int = 0
    abandoned_generations: int = 0
    cleared_leases: int = 0


class SnapshotQueries:
    def _check_snapshot_inputs(self, snapshot, *, require_current=False):
        self._validate_knowledge(snapshot)
        for selected in snapshot.sources:
            gen = self._generation(selected.generation_id)
            receipts = [
                event
                for event in self._knowledge_rows("IndexEvent")
                if event.generation_id == gen.id and event.kind == "published"
            ]
            if gen.status not in ("active", "retired") or gen.published_at is None or len(receipts) != 1:
                raise SnapshotUnavailable("Snapshot requires a previously published generation")
            try:
                self.validate_generation_seal(selected.generation_id)
            except ValueError as error:
                raise SnapshotUnavailable("Snapshot requires a strict generation rebuild") from error
            if (
                require_current
                and self.get_source(selected.source_id).get("active_generation_id") != selected.generation_id
            ):
                raise SnapshotUnavailable("Snapshot source pointer changed")
        if tuple(sorted(snapshot.sources, key=lambda item: item.source_id)) != snapshot.sources:
            raise ValueError("Snapshot source tuples must be sorted")

    def acquire_snapshot_reference(
        self, snapshot, *, reference_key, lease_owner, lease_expires_at, require_current=True, fault_hook=None
    ):
        with self.transaction():
            self._lock_authorization()
            now = self._now()
            if lease_expires_at <= now:
                raise ValueError("Snapshot lease must expire in the future")
            self._check_snapshot_inputs(snapshot, require_current=require_current)
            reference = k.SnapshotReference(
                workspace_id=snapshot.workspace_id,
                snapshot_id=snapshot.id,
                kind="active_query",
                reference_key=reference_key,
                created_at=now,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
            )
            previous = self._knowledge_get("SnapshotReference", reference.id)
            if previous:
                if (
                    previous.released_at is not None
                    or previous.lease_expires_at <= now
                    or previous.lease_owner != lease_owner
                ):
                    raise ValueError("Snapshot reference cannot be resurrected or transferred")
                return previous
            existing = self._knowledge_get("QuerySnapshot", snapshot.id)
            if existing is None:
                self.put_knowledge(snapshot)
            elif existing.replace(created_at=snapshot.created_at) != snapshot:
                raise ValueError("Conflicting snapshot")
            self._write_knowledge(reference)
            if fault_hook:
                fault_hook("reference")
            return reference

    def renew_snapshot_reference(self, reference_id, *, lease_owner, lease_expires_at):
        with self.transaction():
            self._lock_authorization()
            reference = self._knowledge_get("SnapshotReference", reference_id)
            now = self._now()
            if (
                reference is None
                or reference.kind != "active_query"
                or reference.released_at is not None
                or reference.lease_owner != lease_owner
                or reference.lease_expires_at <= now
            ):
                raise ValueError("Snapshot reference is not a live owned lease")
            if lease_expires_at <= reference.lease_expires_at:
                return reference
            reference = reference.replace(lease_expires_at=lease_expires_at)
            self._write_knowledge(reference)
            return reference

    def retain_snapshot(self, snapshot_id, *, kind: Literal["saved", "retained"], reference_key):
        with self.transaction():
            self._lock_authorization()
            if kind not in ("saved", "retained"):
                raise ValueError("Expected durable reference kind")
            snapshot = self._knowledge_get("QuerySnapshot", snapshot_id)
            if snapshot is None:
                raise SnapshotUnavailable("Unknown snapshot")
            self._check_snapshot_inputs(snapshot)
            reference = k.SnapshotReference(
                workspace_id=snapshot.workspace_id,
                snapshot_id=snapshot_id,
                kind=kind,
                reference_key=reference_key,
                created_at=self._now(),
            )
            existing = self._knowledge_get("SnapshotReference", reference.id)
            if existing:
                if existing.released_at is not None:
                    raise ValueError("Released reference cannot be resurrected")
                return existing
            self._write_knowledge(reference)
            return reference

    def release_snapshot_reference(self, reference_id, *, lease_owner=None):
        with self.transaction():
            self._lock_authorization()
            reference = self._knowledge_get("SnapshotReference", reference_id)
            if reference is None:
                raise ValueError("Unknown snapshot reference")
            if reference.kind == "active_query" and reference.lease_owner != lease_owner:
                raise ValueError("Snapshot reference owner differs")
            if reference.released_at is None:
                self._write_knowledge(reference.replace(released_at=self._now()))

    def _purged_revisions(self, workspace_id):
        """Resolve every committed purge barrier down to the revisions it removed."""
        barrier = {
            (row.target_kind, row.target_id)
            for row in self._knowledge_rows("Suppression")
            if row.workspace_id == workspace_id and row.reason == "purge"
        }
        if not barrier:
            return frozenset()
        purged = {identity for kind, identity in barrier if kind == "revision"}
        artifacts = {identity for kind, identity in barrier if kind == "artifact"}
        sources = {identity for kind, identity in barrier if kind == "source"}
        if artifacts or sources:
            for revision in self._knowledge_rows("ArtifactRevision"):
                artifact = self._knowledge_get("Artifact", revision.artifact_id)
                if artifact is not None and (artifact.id in artifacts or artifact.source_id in sources):
                    purged.add(revision.id)
        return frozenset(purged)

    def purged_history_evidence(self, manifest_id):
        """Name a pinned manifest's purged evidence so a reader gets markers, not text."""
        history = self._knowledge_get("HistoryManifest", manifest_id)
        if history is None:
            raise SnapshotUnavailable("Unknown history manifest")
        purged = self._purged_revisions(history.workspace_id)
        return tuple(
            PurgedEvidence("revision", revision_id)
            for revision_id in sorted(set(history.revision_ids) & purged)
        )

    def _snapshot_reaches(self, snapshot, generation_id):
        if any(item.generation_id == generation_id for item in snapshot.sources):
            return True
        if not snapshot.history_manifest_ids:
            return False
        revision_ids = {
            r.artifact_revision_id
            for r in self._knowledge_rows("GenerationMember")
            if r.generation_id == generation_id
        }
        # A purge barrier outranks retained-history reachability: purged evidence
        # must resolve to `evidence_purged`, so it cannot keep a generation alive.
        purged = self._purged_revisions(snapshot.workspace_id)
        for history_id in snapshot.history_manifest_ids:
            history = self._knowledge_get("HistoryManifest", history_id)
            if history and revision_ids.intersection(set(history.revision_ids) - purged):
                return True
        return False

    def _collection_block(self, generation_id):
        gen = self._generation(generation_id)
        if (
            gen.status == "active"
            or self.get_source(gen.source_id).get("active_generation_id") == generation_id
        ):
            return "active_generation"
        now = self._now()
        for ref in self._knowledge_rows("SnapshotReference"):
            if ref.released_at is not None or (ref.kind == "active_query" and ref.lease_expires_at <= now):
                continue
            snapshot = self._knowledge_get("QuerySnapshot", ref.snapshot_id)
            if snapshot and self._snapshot_reaches(snapshot, generation_id):
                return "snapshot_reference"
        return None

    def _delete_knowledge_record(self, kind, record_id):
        if self.knowledge_backend == "fake":
            self._knowledge_data.get(kind, {}).pop(record_id, None)
        else:
            self.run(f"MATCH (n:{kind} {{id:$id}}) DETACH DELETE n", id=record_id)

    def _collect_generation(self, generation_id):
        blocked = self._collection_block(generation_id)
        if blocked:
            return CollectionResult(generation_id, blocked_reason=blocked)
        native_ids = []
        for kind, attr in (
            ("Passage", "passages"),
            ("Symbol", "symbols"),
            ("DataObject", "data_objects"),
            ("Commit", "commits"),
        ):
            for row in self._native_rows(kind):
                if row.get("generation_id") != generation_id:
                    continue
                native_ids.append(row["id"])
                if self.knowledge_backend == "fake":
                    getattr(self, attr).pop(row["id"], None)
                else:
                    self.run(f"MATCH (n:{kind} {{id:$id}}) DETACH DELETE n", id=row["id"])
        if self.knowledge_backend == "fake":
            removed = set(native_ids)
            for attr in ("code_edges", "modifies", "refers_to", "synonyms", "tuned"):
                values = getattr(self, attr)
                for key in list(values):
                    if removed.intersection(key[:2]):
                        del values[key]
            for attr in ("mentions", "statements", "definitions", "precedes"):
                values = getattr(self, attr)
                filtered = [key for key in values if not removed.intersection(key[:2])]
                setattr(self, attr, type(values)(filtered))
        count = 0
        gen = self._generation(generation_id)
        published = gen.published_at is not None or any(
            event.generation_id == gen.id and event.kind == "published"
            for event in self._knowledge_rows("IndexEvent")
        )
        # Keep ever-published exact-membership provenance as an immutability
        # tombstone. It conveys no serving reachability without a sealed manifest.
        kinds = ["GenerationMember", "NativeBinding", "IndexManifest"]
        if not published:
            kinds.append("GenerationEvidenceMember")
        for kind in kinds:
            for row in self._knowledge_rows(kind):
                if row.generation_id == generation_id:
                    self._delete_knowledge_record(kind, row.id)
                    count += 1
        # Preserve Generation identity/parent ancestry and shared evidence/raw blobs.
        # The failed status is a durable unavailable tombstone for stale snapshots.
        self._write_knowledge(self._generation(generation_id).replace(status="failed"))
        return CollectionResult(
            generation_id, removed_records=count, removed_native_ids=tuple(sorted(native_ids))
        )

    def discard_generation(self, generation_id, *, job_id, lease_owner, fencing_token):
        with self.transaction():
            job = self._check_build(
                generation_id,
                job_id=job_id,
                lease_owner=lease_owner,
                fencing_token=fencing_token,
                states=("staging", "ready"),
            )
            result = self._collect_generation(generation_id)
            if result.blocked_reason is None:
                self._write_knowledge(job.replace(status="cancelled"))
                self._source_fields(job.source_id, active_build_id=None)
            return result

    def collect_generation(self, generation_id):
        with self.transaction():
            gen = self._generation(generation_id)
            self._lock_source(gen.source_id)
            source = self.get_source(gen.source_id)
            job = self._knowledge_get("MaintenanceJob", source.get("active_build_id"))
            if (
                job
                and job.input_fingerprint == generation_id
                and job.status == "running"
                and job.lease_expires_at > self._now()
            ):
                return CollectionResult(generation_id, blocked_reason="live_build")
            return self._collect_generation(generation_id)

    def recover_generation_builds(self, *, source_id=None):
        """Recover expired builds globally or within one caller-authorized source."""
        if source_id is not None and (type(source_id) is not str or not source_id.strip()):
            raise ValueError("Recovery requires a nonempty source scope")
        with self.transaction():
            self._lock_authorization()
            failed = cleared = abandoned = 0
            for gen in self._knowledge_rows("Generation"):
                if source_id is not None and gen.source_id != source_id:
                    continue
                if gen.status not in ("staging", "ready", "failed"):
                    continue
                self._lock_source(gen.source_id)
                source = self.get_source(gen.source_id)
                jobs = [
                    j
                    for j in self._knowledge_rows("MaintenanceJob")
                    if j.kind == "rebuild" and j.input_fingerprint == gen.id and j.status == "running"
                ]
                if any(j.lease_expires_at > self._now() for j in jobs):
                    continue
                for job in jobs:
                    self._write_knowledge(job.replace(status="failed", error_code="lease_expired"))
                    failed += 1
                    if (
                        source.get("active_build_id") == job.id
                        and source.get("build_fencing_token") == job.fencing_token
                    ):
                        self._source_fields(
                            gen.source_id, active_build_id=None, build_fencing_token=job.fencing_token + 1
                        )
                        cleared += 1
                if gen.status != "failed":
                    self._write_knowledge(gen.replace(status="failed"))
                    abandoned += 1
            return RecoveryResult(failed, abandoned, cleared)
