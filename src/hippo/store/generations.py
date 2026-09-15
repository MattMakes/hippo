"""Durable generation leases, exact manifests, and atomic source publication."""

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from ..knowledge import model as k
from ..knowledge.identity import canonical_json, text_hash
from .authorization import bump_epoch, epoch
from .base import by_ids

MANDATORY_REPRESENTATIONS = ("evidence", "dense", "native")
# Schema v8 columns an older row reads back as null. Hashing the null keys would change the
# evidence checksum of every generation sealed before v8, and `validate_generation_seal` would
# then refuse it.
V8_UNSET_FIELDS = {"AssertionVersion": ("family", "source", "rule", "weight", "statement", "unit_id")}


def _evidence_row(record) -> dict:
    """A record as the evidence representation hashes it, without its unset v8 columns."""
    row = record.model_dump(mode="json")
    for field in V8_UNSET_FIELDS.get(type(record).__name__, ()):
        if row[field] is None:
            del row[field]
    return row


# A managed refresh leaves the source `ready` with a `refreshing: ...` stage, because its
# published generation keeps serving throughout. A restart therefore cannot mark it failed
# the way an interrupted legacy job is marked failed: only the stage has to be retired, or
# the row claims a refresh that no longer has a worker. The code and message are the same
# bounded shape the managed build's own failures use; saying it here keeps the store from
# importing the pipeline to recover from a crash.
#
# They live in this module rather than in `memory.py`, which is the Neo4j backend and not a
# shared base: two other backends importing a domain constant from a third backend's module
# made them depend on it for vocabulary rather than for row shape. `managed_activation`
# writes the stage this prefix matches and reads the prefix from here, so the sweep's
# predicate and the writer of the value it matches cannot drift apart.
REFRESHING_PREFIX = "refreshing:"
INTERRUPTED_REFRESH_STAGE = "refresh_failed"
INTERRUPTED_REFRESH_CODE = "build_interrupted"
INTERRUPTED_REFRESH_ERROR = (
    f"{INTERRUPTED_REFRESH_CODE}: The build was interrupted by a restart. Reindex to run it again."
)


@dataclass(frozen=True, slots=True)
class SourceTombstone:
    """What one committed managed tombstone changed. Nothing was deleted."""

    suppression_epoch: int
    fencing_token: int
    cancelled_generation_id: str | None
    cancelled_job_id: str | None


@dataclass(frozen=True, slots=True)
class BuildAdmission:
    """One fenced admission: the holder it installed, or the live holder it left alone.

    `reused` is true for the idempotent same-holder return, where nothing was written and the
    caller must not go on to collect, restage or otherwise touch the generation.
    """

    job: k.MaintenanceJob
    generation: k.Generation
    reused: bool


def tombstone_scope_key(source_id: str) -> str:
    return f"source:{source_id}:delete"


class GenerationQueries:
    def _now(self):
        return getattr(self, "_generation_clock", lambda: datetime.now(UTC))()

    def content_epoch(self):
        return epoch(self, "content_epoch")

    def suppression_epoch(self):
        return epoch(self, "suppression_epoch")

    def source_is_managed(self, source_id):
        source = self.get_source(source_id)
        return bool(source and source.get("managed"))

    def source_serves_legacy(self, source_row) -> bool:
        """True while a source still answers queries from its legacy graph.

        The `managed` flag means "the managed lane owns this source's cleanup and
        dispatch", and it is still set the moment the first row is staged, so every
        destructive guard keeps firing throughout a conversion. What it deliberately does
        not mean is "serve managed evidence": a repository bootstrap stages over many
        transactions, and until it publishes there is no generation to serve. So this
        predicate reads publication alone -- no active pointer and no published
        `IndexEvent` -- and a staging or failed generation leaves its source serving
        exactly the legacy graph it was already serving.

        A tombstone is the third term, and the only one that is not about publication. A
        source tombstoned part way through its conversion has no pointer and no published
        event, so publication alone would leave it serving its legacy graph -- but the
        managed lane owns it for dispatch (it is `managed`), its suppression is enforced
        where managed evidence is authorized, and legacy rows are not evidence. Withdrawn
        means withdrawn: it serves neither lane. Only an all-principals suppression is
        readable from a row; a principal-specific one stays the access layer's decision,
        as it is for any legacy source.

        A pure read of the row and the rows naming it: no lock and no clock, so a query
        path may call it per source. The pointer clause answers every published source
        without touching either table.
        """
        if not source_row or source_row.get("active_generation_id"):
            return False
        source_id = source_row.get("id")
        # Both reads name the source. A graph build calls this once per legacy source, so the
        # unscoped forms were two whole-table reads per source per build.
        if any(
            event.kind == "published"
            for event in self._knowledge_rows("IndexEvent", where={"aggregate_id": source_id})
        ):
            return False
        return not any(
            row.all_principals and row.workspace_id == source_row.get("workspace_id")
            for row in self._knowledge_rows(
                "Suppression", where={"target_kind": "source", "target_id": source_id}
            )
        )

    def _source_fields(self, source_id, **fields):
        if self.knowledge_backend == "fake":
            self.sources[source_id].update(fields)
        else:
            self.run(
                "MATCH (s:Source {id:$id}) SET " + ", ".join(f"s.{key}=${key}" for key in fields),
                id=source_id,
                **fields,
            )

    def _lock_source(self, source_id):
        self._lock_authorization()
        if self.knowledge_backend != "fake":
            self.run(
                "MATCH (s:Source {id:$id}) SET s.generation_lock=coalesce(s.generation_lock,0)+1 RETURN s.id AS id",
                id=source_id,
            )
        if self.get_source(source_id) is None:
            raise ValueError("Unknown source")

    def begin_managed_source(self, source_id):
        with self.transaction():
            self._lock_source(source_id)
            if not self.source_is_managed(source_id):
                self._source_fields(source_id, managed=True)
                self._bump_authorization_epoch()

    def release_interrupted_build(self, source_id) -> None:
        """Release the build holder a crash left on a source the restart sweep is retiring.

        Without this the sweep's own sentence is a lie: `active_build_id` still names a
        `MaintenanceJob` the crash left `running` with a lease up to the whole lease
        duration in the future, `_install` refuses a new build while that holder is live
        (`BuildBusy`), and "Reindex to run it again" is refused for that window. The
        expired-lease recovery clears it eventually; the sweep already holds the right row.

        The same transition the delete path performs above, minus the suppression: only the
        exact job this source was holding ends, and the published active generation, every
        other job and every count are untouched.
        """
        source = self.get_source(source_id)
        if not source or not source.get("active_build_id"):
            return
        job = self._knowledge_get("MaintenanceJob", source["active_build_id"])
        if job is not None and job.kind == "rebuild" and job.status == "running":
            self._write_knowledge(job.replace(status="cancelled", error_code=INTERRUPTED_REFRESH_CODE))
        self._source_fields(source_id, active_build_id=None)

    def apply_source_tombstone(self, source_id, *, operation_id, created_at):
        """Fence the builder and suppress the current view of a managed source.

        Deletes nothing: published and retired generations, their manifests, raw
        references, saved snapshots and the active pointer all stay exactly as
        they are, so an authorized historical read still reconstructs them.

        The caller must already hold a transaction; the authorization and source
        locks are taken here so the transition cannot run without them.
        """
        # This thread's own transaction, not any thread's: a process-wide probe would
        # admit a caller holding none whenever some other thread happened to hold one.
        if not self.in_ambient_transaction():
            raise RuntimeError("Managed tombstone requires the caller's transaction")
        self._lock_source(source_id)
        if not self.source_is_managed(source_id):
            raise ValueError("Managed source required for suppression")
        source = self.get_source(source_id)
        fence = int(source.get("build_fencing_token") or 0) + 1
        cancelled_generation = cancelled_job = None
        job = self._knowledge_get("MaintenanceJob", source.get("active_build_id"))
        if job is not None and job.kind == "rebuild" and job.status == "running":
            gen = self._knowledge_get("Generation", job.input_fingerprint)
            if (
                gen is not None
                and gen.source_id == source_id
                and gen.status in ("staging", "ready")
                and gen.published_at is None
                and source.get("active_generation_id") != gen.id
                and not any(
                    event.kind == "published"
                    for event in self._knowledge_rows("IndexEvent", generation_id=gen.id)
                )
            ):
                # Only this exact unpublished attempt ends; the published active
                # generation and every other job keep their state.
                self._write_knowledge(gen.replace(status="failed"))
                self._write_knowledge(job.replace(status="cancelled", error_code="source_tombstoned"))
                cancelled_generation, cancelled_job = gen.id, job.id
        self._source_fields(source_id, active_build_id=None, build_fencing_token=fence)
        self.update_source(
            source_id, status="deleted", stage="tombstoned", progress_done=0, progress_total=0, error=None
        )
        suppression = k.Suppression(
            workspace_id=source["workspace_id"],
            target_kind="source",
            target_id=source_id,
            scope_key=tombstone_scope_key(source_id),
            all_principals=True,
            view_applicability="current_only",
            reason="tombstone",
            epoch=self.suppression_epoch() + 1,
            created_at=created_at,
            restoration_barrier=operation_id,
        )
        # Writing the record through the reviewed path is what commits the
        # suppression, content and authorization epochs with this transition.
        self.put_knowledge(suppression)
        return SourceTombstone(suppression.epoch, fence, cancelled_generation, cancelled_job)

    def _generation(self, generation_id):
        row = self._knowledge_get("Generation", generation_id)
        if row is None:
            raise ValueError("Unknown generation")
        return row

    def _tombstoned(self, source_id, source):
        """A committed managed tombstone, read under the source lock the caller holds."""
        if source.get("status") == "deleted":
            return True
        scope_key = tombstone_scope_key(source_id)
        return any(
            row.reason == "tombstone"
            and row.view_applicability == "current_only"
            and row.scope_key == scope_key
            # Scoped by the two fields the predicate already required; CC2's v6 step indexes
            # both, so the barrier costs a lookup rather than a walk of every suppression.
            for row in self._knowledge_rows(
                "Suppression", where={"target_kind": "source", "target_id": source_id}
            )
        )

    def _admit_build(
        self, generation_id, *, job_key, lease_owner, lease_expires_at, expected_manifest_hash=None
    ):
        """The fenced admission both build entry points share, so their guarantees cannot drift.

        The caller holds the transaction. In order: the source lock, a re-read of the generation
        under it, the tombstone barrier, the status and future-lease check, the never-published
        triple, the optional stored-manifest assertion, live-holder exclusion with the idempotent
        same-holder return, the fence advance, the holder install and the `attempt_count`
        carry-over. Nothing here collects: `claim_generation_build` collects afterwards and
        `reclaim_generation_build` never does, which is the one difference between them.

        Every read is scoped by the source or the generation, because this runs under the source
        lock on every build of every size and a whole-table read here is the whole corpus.
        """
        gen = self._generation(generation_id)
        self._lock_source(gen.source_id)
        gen = self._generation(generation_id)
        source = self.get_source(gen.source_id)
        if self._tombstoned(gen.source_id, source):
            # The barrier lives here, not in the dispatcher that read the source a
            # moment ago: refuse before the fence advances, before a holder is
            # installed, and before the retained attempt could be collected.
            raise ValueError("Stale build lease, fence, or generation state")
        now = self._now()
        if gen.status not in ("staging", "failed") or lease_expires_at <= now:
            raise ValueError("Build requires staging or unpublished failed generation and future lease")
        # All three publication proofs, each independently sufficient, exactly as
        # `fail_generation_build` and `_publish_generation` treat them. A generation any one of
        # them names has served a reader, so no holder may reopen it under any status.
        if (
            gen.published_at is not None
            or source.get("active_generation_id") == gen.id
            or any(
                event.kind == "published"
                for event in self._knowledge_rows("IndexEvent", generation_id=gen.id)
            )
        ):
            raise ValueError("Published generations cannot reopen for retry")
        if expected_manifest_hash is not None and expected_manifest_hash != gen.manifest_hash:
            raise ValueError("Reclaim manifest hash differs from the stored generation")
        previous = self._knowledge_get("MaintenanceJob", source.get("active_build_id"))
        if previous is not None and previous.status == "running" and previous.lease_expires_at > now:
            if (
                previous.input_fingerprint == generation_id
                and previous.job_key == job_key
                and previous.lease_owner == lease_owner
            ):
                return BuildAdmission(previous, gen, True)
            raise ValueError("Source already has a live build holder")
        fence = int(source.get("build_fencing_token") or 0) + 1
        job = k.MaintenanceJob(
            source_id=gen.source_id,
            scope_key="generation",
            kind="rebuild",
            job_key=job_key,
            input_fingerprint=gen.id,
            expected_parent_id=gen.parent_id,
            phase="extract",
            status="running",
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            fencing_token=fence,
            attempt_count=1,
        )
        prior = self._knowledge_get("MaintenanceJob", job.id)
        if prior:
            job = job.replace(attempt_count=prior.attempt_count + 1)
        self._write_knowledge(job)
        self._source_fields(gen.source_id, active_build_id=job.id, build_fencing_token=fence)
        return BuildAdmission(job, gen, False)

    def claim_generation_build(self, generation_id, *, job_key, lease_owner, lease_expires_at):
        """Admit a holder for a never-published generation, collecting a failed attempt first.

        This is the reviewed retry contract: a `failed` generation's staged rows are removed
        before it returns to `staging`, so the retry starts from zero and cannot inherit a
        half-written payload. `reclaim_generation_build` is the resumable form, for a build
        that can replay its own batches over rows it recognises.
        """
        with self.transaction():
            admitted = self._admit_build(
                generation_id, job_key=job_key, lease_owner=lease_owner, lease_expires_at=lease_expires_at
            )
            if admitted.reused:
                return admitted.job
            gen = admitted.generation
            if gen.status == "failed":
                # The new source fence is held while removing this never-published
                # attempt's rows. Shared raw/evidence identities remain reusable.
                result = self._collect_generation(gen.id)
                if result.blocked_reason is not None:
                    raise ValueError("Failed generation retry is still referenced")
                self._write_knowledge(gen.replace(status="staging"))
            return admitted.job

    def reclaim_generation_build(
        self, generation_id, *, job_key, lease_owner, lease_expires_at, expected_manifest_hash
    ):
        """Resume a never-published attempt under a fresh holder, keeping its staged rows.

        Admission is `claim_generation_build`'s, step for step and in the same order -- both
        call `_admit_build` -- so the tombstone barrier, the future lease, the never-published
        triple, live-holder exclusion with its idempotent same-holder return, the fence advance
        and the `attempt_count` carry-over all hold here unchanged. The single difference is
        that a `failed` generation returns to `staging` **without** `_collect_generation`, so a
        crashed build replays its remaining batches instead of restarting from zero.

        `expected_manifest_hash` is a cheap assertion against a corrupted row, not the safety
        property. `manifest_hash` is in `Generation.identity_fields`, so a stored generation with
        this ID necessarily carries the hash that was hashed into it: passing `generation_id`
        already pins it, and equality proves nothing the ID did not. The properties that do the
        work are the admission preconditions above, the derivation versions carried in generation
        identity, and the writer's probe that asserts what is absent as well as what is present.
        """
        if not isinstance(expected_manifest_hash, str) or not expected_manifest_hash:
            raise ValueError("Reclaim requires the stored generation's manifest hash")
        with self.transaction():
            admitted = self._admit_build(
                generation_id,
                job_key=job_key,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                expected_manifest_hash=expected_manifest_hash,
            )
            if admitted.reused:
                return admitted.job
            gen = admitted.generation
            if gen.status == "failed":
                # No collection: the rows of this never-published attempt are the resume
                # checkpoint, and the new fence is what makes writing over them safe.
                self._write_knowledge(gen.replace(status="staging"))
            return admitted.job

    def _check_build(self, generation_id, *, job_id, lease_owner, fencing_token, states=("staging",)):
        gen = self._generation(generation_id)
        self._lock_source(gen.source_id)
        gen = self._generation(generation_id)
        source = self.get_source(gen.source_id)
        job = self._knowledge_get("MaintenanceJob", job_id)
        if (
            job is None
            or job.kind != "rebuild"
            or job.input_fingerprint != gen.id
            or job.source_id != gen.source_id
            or job.expected_parent_id != gen.parent_id
            or source.get("active_build_id") != job.id
            or source.get("build_fencing_token") != fencing_token
            or job.fencing_token != fencing_token
            or job.lease_owner != lease_owner
            or job.lease_expires_at is None
            or job.lease_expires_at <= self._now()
            or job.status != "running"
            or gen.status not in states
        ):
            raise ValueError("Stale build lease, fence, or generation state")
        return job

    def renew_generation_build(self, job_id, *, lease_owner, fencing_token, lease_expires_at):
        with self.transaction():
            job = self._knowledge_get("MaintenanceJob", job_id)
            if job is None:
                raise ValueError("Unknown build")
            job = self._check_build(
                job.input_fingerprint,
                job_id=job_id,
                lease_owner=lease_owner,
                fencing_token=fencing_token,
                states=("staging", "ready"),
            )
            if lease_expires_at <= max(self._now(), job.lease_expires_at):
                raise ValueError("Renewal must extend live lease")
            job = job.replace(lease_expires_at=lease_expires_at)
            self._write_knowledge(job)
            return job

    def check_generation_write(self, generation_id, *, job_id, lease_owner, fencing_token):
        with self.transaction():
            self._check_build(
                generation_id, job_id=job_id, lease_owner=lease_owner, fencing_token=fencing_token
            )

    def fail_generation_build(
        self, generation_id, *, job_id, lease_owner, fencing_token, error_code="build_failed"
    ):
        """End a live unpublished attempt; collection remains an explicit operation.

        Caller authorization is separate from these durable build credentials.
        An expired or replaced holder must leave cleanup to recovery.
        """
        if error_code not in ("build_failed", "build_cancelled"):
            raise ValueError("Unknown build failure code")
        with self.transaction():
            job = self._check_build(
                generation_id,
                job_id=job_id,
                lease_owner=lease_owner,
                fencing_token=fencing_token,
                states=("staging", "ready"),
            )
            gen = self._generation(generation_id)
            if (
                gen.published_at is not None
                or self.get_source(gen.source_id).get("active_generation_id") == gen.id
                or any(
                    event.kind == "published"
                    for event in self._knowledge_rows("IndexEvent", generation_id=gen.id)
                )
            ):
                raise ValueError("Published generations cannot fail as builds")
            terminal = job.replace(
                status="cancelled" if error_code == "build_cancelled" else "failed",
                error_code=error_code,
            )
            self._write_knowledge(gen.replace(status="failed"))
            self._write_knowledge(terminal)
            self._source_fields(gen.source_id, active_build_id=None)
            bump_epoch(self, "content_epoch")
            return terminal

    @contextmanager
    def generation_write(self, generation_id, *, job_id, lease_owner, fencing_token):
        with self.transaction():
            credentials = dict(job_id=job_id, lease_owner=lease_owner, fencing_token=fencing_token)
            self._check_build(generation_id, **credentials)
            previous = getattr(self, "_generation_authority", None)
            self._generation_authority = (generation_id, credentials)
            try:
                yield
            finally:
                self._generation_authority = previous

    def bind_generation_embedding_profile(
        self, generation_id, manifest_revision_id, *, job_id, lease_owner, fencing_token, fault_hook=None
    ):
        from ..knowledge.generation_profiles import (
            PROFILE_POINTER,
            embedding_mode,
            validate_generation_profile,
        )

        credentials = dict(job_id=job_id, lease_owner=lease_owner, fencing_token=fencing_token)
        with self.transaction():
            self._check_build(generation_id, **credentials)
            gen = self._generation(generation_id)
            result = validate_generation_profile(self, gen, manifest_revision_id)
            if embedding_mode(gen) == "verified_v1":
                # Binding the profile a generation already holds is a no-op, sealed or not (a
                # different pointer refuses above). A failure after the seal leaves a failed
                # generation holding its manifest, and the retry of the same input-derived ID
                # installs the same binding again (R21-B2).
                return result
            if self._knowledge_rows("IndexManifest", generation_id=gen.id):
                raise ValueError("A sealed profile cannot be rebound")
            if fault_hook:
                fault_hook("before_binding")
            self._check_build(generation_id, **credentials)
            coverage = json.loads(gen.coverage_json)
            self._write_knowledge(
                gen.replace(
                    coverage_json=canonical_json(
                        {
                            **coverage,
                            "embedding_mode": "verified_v1",
                            PROFILE_POINTER: manifest_revision_id,
                        }
                    )
                )
            )
            if fault_hook:
                fault_hook("after_binding")
            self._check_build(generation_id, **credentials)
            bump_epoch(self, "content_epoch")
            return result

    def _assert_generation_writable(self, generation_id, *, legacy_fixture=False):
        gen = self._generation(generation_id)
        jobs = [
            j
            for j in self._knowledge_rows("MaintenanceJob", where={"input_fingerprint": generation_id})
            if j.kind == "rebuild"
        ]
        strict = any(
            set(m.required_representations) == set(MANDATORY_REPRESENTATIONS)
            for m in self._knowledge_rows("IndexManifest", generation_id=generation_id)
        )
        if gen.status != "staging":
            if legacy_fixture and not jobs and not strict:
                return
            raise ValueError("Sealed generation is immutable")
        if not jobs and not legacy_fixture:
            raise ValueError("Managed write requires a claimed generation build")
        if jobs:
            authority = getattr(self, "_generation_authority", None)
            if authority is None or authority[0] != generation_id:
                raise ValueError("Managed writes require a live generation lease")
            self._check_build(generation_id, **authority[1])

    def _record_revisions(self, record, seen=None):
        seen = set() if seen is None else seen
        key = (type(record).__name__, record.id)
        if key in seen:
            return set()
        seen.add(key)
        if isinstance(record, k.ArtifactRevision):
            return {record.id}
        if isinstance(record, (k.Generation, k.AccessPolicy, k.Artifact, k.KnowledgeObject, k.Assertion)):
            return set()
        result = set()
        for kind, rid in self._references(record):
            if kind in k.RECORD_TYPES:
                target = self._knowledge_get(kind, rid)
                if target is not None:
                    result |= self._record_revisions(target, seen)
        return result

    def _revision_member(self, generation_id, revision_id):
        """True when the generation selected this revision.

        A `GenerationMember`'s identity is exactly the pair, so this is one primary-key lookup
        rather than a read of every member revision per record written.
        """
        member = k.GenerationMember(generation_id=generation_id, artifact_revision_id=revision_id)
        return self._knowledge_get("GenerationMember", member.id) is not None

    def _evidence_member(self, generation_id, record_kind, record_id):
        """True when the generation's exact interpretation holds this record; one primary-key lookup."""
        member = k.GenerationEvidenceMember(
            generation_id=generation_id, record_kind=record_kind, record_id=record_id
        )
        return self._knowledge_get("GenerationEvidenceMember", member.id) is not None

    def _sealed_member(self, record_kind, record_id):
        """True when a generation that is no longer staging holds this exact record.

        Read by the record's own id (a v7 index on Neo4j), so the cost is the few generations that
        selected it rather than every member of every generation. A kind that can never be an
        exact member answers without a read.
        """
        if record_kind not in k.GenerationEvidenceMember.model_fields["record_kind"].annotation.__args__:
            return False
        return any(
            member.record_kind == record_kind and self._generation(member.generation_id).status != "staging"
            for member in self._knowledge_rows("GenerationEvidenceMember", where={"record_id": record_id})
        )

    def _check_knowledge_write(self, record, existing=None):
        from .authorization import RECORD_EPOCHS

        if isinstance(record, k.Generation):
            from ..knowledge.generation_profiles import PROFILE_POINTER, embedding_mode

            mode = embedding_mode(record)
            if mode == "verified_v1" or PROFILE_POINTER in json.loads(record.coverage_json):
                raise ValueError("Verified profile binding requires a controlled lifecycle operation")
        if (
            isinstance(record, k.Generation)
            and isinstance(json.loads(record.coverage_json), dict)
            and "derived_evidence_version" in json.loads(record.coverage_json)
        ):
            raise ValueError("Derived capability is controlled by storage membership")
        if (
            isinstance(record, k.MaintenanceJob)
            and record.kind == "rebuild"
            and self._knowledge_get("Generation", record.input_fingerprint) is not None
        ):
            raise ValueError("Generation build leases require controlled lifecycle operations")
        # The one authorized transition on a published historical row: the recorded
        # interval an already-validated publication plan closes. It skips the two
        # guards below because both refuse a change this transition is defined to
        # make, and it can name no other row, field or instant.
        closure = existing is not None and self._authorized_recorded_closure(record, existing)
        if (
            RECORD_EPOCHS[type(record).__name__] == "content"
            and not isinstance(record, k.Generation)
            and not closure
        ):
            authority = getattr(self, "_generation_authority", None)
            source_ids = {record.source_id} if isinstance(record, k.Artifact) else set()
            for revision_id in self._record_revisions(record):
                revision = self._knowledge_get("ArtifactRevision", revision_id)
                if revision:
                    source_ids.add(self._knowledge_get("Artifact", revision.artifact_id).source_id)
            for source_id in source_ids:
                source = self.get_source(source_id)
                active_job = self._knowledge_get("MaintenanceJob", source.get("active_build_id"))
                if active_job and active_job.status == "running":
                    if authority is None or authority[0] != active_job.input_fingerprint:
                        raise ValueError("Managed evidence write requires build authority")
                    self._check_build(authority[0], **authority[1])
        if existing is not None and isinstance(record, (k.Generation, k.SnapshotReference)):
            raise ValueError("Controlled lifecycle operation required")
        if isinstance(
            record,
            (
                k.GenerationMember,
                k.GenerationEvidenceMember,
                k.NativeBinding,
                k.IndexManifest,
                k.ProseExtraction,
            ),
        ):
            self._assert_generation_writable(
                record.generation_id,
                legacy_fixture=not isinstance(record, (k.GenerationEvidenceMember, k.ProseExtraction)),
            )
        if isinstance(record, k.GenerationEvidenceMember) and record.record_kind in {
            "RetrievalView",
            "DerivedRecord",
            "DerivedDependency",
            "ProseExtraction",
        }:
            gen = self._generation(record.generation_id)
            coverage = json.loads(gen.coverage_json)
            if not isinstance(coverage, dict):
                raise ValueError("Derived capability requires object coverage")
            if "derived_evidence_version" not in coverage:
                self._write_knowledge(
                    gen.replace(coverage_json=canonical_json({**coverage, "derived_evidence_version": 1}))
                )
        if isinstance(record, k.ProseExtraction):
            from ..knowledge.derivations import validate_prose

            validate_prose(self, record.generation_id, record, require_member=False)
        # The member tests below run once per record a build writes, so each asks about the rows
        # it names -- by primary key or by the record's id -- and never reads a member table whole.
        if isinstance(record, k.GenerationEvidenceMember):
            target = self._knowledge_get(record.record_kind, record.record_id)
            if isinstance(target, k.ProseExtraction) and target.generation_id != record.generation_id:
                raise ValueError("Prose extraction belongs to another generation")
            if not all(
                self._revision_member(record.generation_id, revision_id)
                for revision_id in self._record_revisions(target)
            ):
                raise ValueError("Evidence member is outside generation revisions")
        if isinstance(record, k.NativeBinding):
            gen = self._generation(record.generation_id)
            native = self._knowledge_get(record.native_kind, record.native_id)
            if native.get("generation_id") is not None or any(
                j.kind == "rebuild"
                for j in self._knowledge_rows("MaintenanceJob", where={"input_fingerprint": gen.id})
            ):
                span = self._knowledge_get("EvidenceSpan", record.span_id)
                if (
                    native.get("generation_id") != gen.id
                    or not self._revision_member(gen.id, span.revision_id)
                    or not self._evidence_member(gen.id, "EvidenceSpan", span.id)
                ):
                    raise ValueError("Binding native or evidence is outside generation closure")
        if existing is not None and not closure and self._sealed_member(type(record).__name__, record.id):
            raise ValueError("Published interpretation is immutable")
        if isinstance(record, k.DerivedDependency) and self._sealed_member(
            "DerivedRecord", record.derived_record_id
        ):
            raise ValueError("Sealed derivation cannot gain dependencies")
        if isinstance(record, k.AssertionSupport) and self._sealed_member(
            "AssertionVersion", record.assertion_version_id
        ):
            raise ValueError("Sealed assertion proof group cannot gain support")

    def _native_rows(self, kind, *, ids=None, generation_id=None, source_id=None, untagged=False):
        """Native rows of one kind, optionally scoped. Every combination is one bounded query.

        The keys push into a single statement, so a caller that knows which rows it wants pays
        for those rows rather than for the table:

        * `ids` is the key for a write or a mutation, which must still see rows of *other*
          generations to find a prior row and to refuse a crossing edge.
        * `generation_id` is the key for an inventory or a checksum, which wants exactly one
          generation.
        * `source_id` with `untagged=True` is the legacy lane's key under ruling 14: the rows of
          a source that no generation owns. `untagged` alone asks the same question of the whole
          store. It is a distinct key rather than `generation_id=None` because `None` already
          means "do not filter", and an operator would never be able to tell the two apart.

        Passing nothing is still legal and still reads the table, which collection relies on.

        Entity and Fact are the shared graph and carry no `generation_id` column, so scoping
        them by generation or by taggedness is refused rather than silently answered with
        nothing.
        """
        attribute = {
            "Passage": "passages",
            "Symbol": "symbols",
            "DataObject": "data_objects",
            "Commit": "commits",
            "Entity": "entities",
            "Fact": "facts",
        }[kind]
        if (generation_id is not None or untagged) and kind in ("Entity", "Fact"):
            raise ValueError(f"{kind} is shared and is not scoped by generation")
        if generation_id is not None and untagged:
            raise ValueError("A row cannot both belong to a generation and be untagged")
        if ids is not None:
            ids = list(dict.fromkeys(ids))
            if not ids:
                return []
        if self.knowledge_backend == "fake":
            rows = getattr(self, attribute)
            values = [rows[rid] for rid in ids if rid in rows] if ids is not None else list(rows.values())
            if generation_id is not None:
                values = [row for row in values if row.get("generation_id") == generation_id]
            if untagged:
                values = [row for row in values if row.get("generation_id") is None]
            if source_id is not None:
                values = [row for row in values if row.get("source_id") == source_id]
            return values
        where, params = [], {}
        head = f"MATCH (n:{kind})"
        if ids is not None:
            # The id list drives the match instead of filtering it; see `base.by_ids`.
            head = by_ids(kind)
            params["ids"] = ids
        if generation_id is not None:
            where.append("n.generation_id = $generation_id")
            params["generation_id"] = generation_id
        if untagged:
            where.append("n.generation_id IS NULL")
        if source_id is not None and kind != "Passage":
            where.append("n.source_id = $source_id")
            params["source_id"] = source_id
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        if kind == "Passage":
            # One statement, not one per row: the owning Source used to cost a lookup per passage.
            # A Passage has no source_id column; ownership is the FROM edge, so scoping by source
            # makes that edge required instead of optional.
            if source_id is not None:
                params["source_id"] = source_id
                rows = self.run(
                    f"{head}{clause} MATCH (n)-[:FROM]->(s:Source {{id:$source_id}}) "
                    "RETURN n AS n, s.id AS source_id",
                    **params,
                )
            else:
                rows = self.run(
                    f"{head}{clause} OPTIONAL MATCH (n)-[:FROM]->(s:Source) RETURN n AS n, s.id AS source_id",
                    **params,
                )
        else:
            rows = self.run(f"{head}{clause} RETURN n AS n", **params)
        result = []
        for row in rows:
            native = {key: value for key, value in dict(row["n"]).items() if not key.startswith("_")}
            if kind == "Passage":
                native["source_id"] = row["source_id"]
            result.append(native)
        return result

    NATIVE_RELATIONSHIP_SPECS = {
        "CODE_EDGE": ("code_edges", ("Symbol", "DataObject"), ("Symbol", "DataObject")),
        "DEFINED_IN": ("definitions", ("Symbol", "DataObject", "Commit"), ("Passage",)),
        "MODIFIES": ("modifies", ("Commit",), ("Symbol",)),
        "PRECEDES": ("precedes", ("Commit",), ("Commit",)),
        "REFERS_TO": ("refers_to", ("Passage",), ("Symbol", "DataObject")),
        "MENTIONS": ("mentions", ("Passage",), ("Entity",)),
        "STATES": ("statements", ("Passage",), ("Fact",)),
        "SUBJECT": (None, ("Fact",), ("Entity",)),
        "OBJECT": (None, ("Fact",), ("Entity",)),
        "SYNONYM": ("synonyms", ("Entity", "Symbol", "DataObject"), ("Entity", "Symbol", "DataObject")),
        "TUNED": (
            "tuned",
            ("Entity", "Passage", "Symbol", "DataObject"),
            ("Entity", "Passage", "Symbol", "DataObject"),
        ),
    }

    def _edges_touching(self, ids, *, both=False, rels=None):
        """Every relationship with an endpoint in `ids` (or, with `both`, both endpoints in it).

        The `both=False` form is what keeps the two generation guards alive: it returns the
        crossing edge *with* its far endpoint, so the caller can still refuse it. A read narrowed
        to one generation would drop that row and turn a refusal into silent acceptance.

        `rels` limits the scan to some relationship kinds, which is how the second closure hop
        asks only for `SUBJECT`/`OBJECT` instead of re-walking every kind.
        """
        ids = list(dict.fromkeys(ids))
        if not ids:
            return []
        edges = []
        for rel, (attribute, left, right) in self.NATIVE_RELATIONSHIP_SPECS.items():
            if rels is not None and rel not in rels:
                continue
            if self.knowledge_backend == "fake":
                selected = set(ids)
                # The Fake store's writers hold `_lock` for their whole transaction, so its live
                # tables are read under it too rather than half-applied (R21-m6).
                with self._lock:
                    if attribute is None:
                        field = "subject_id" if rel == "SUBJECT" else "object_id"
                        for row in self.facts.values():
                            pair = (row["id"], row[field])
                            if (
                                (pair[0] in selected and pair[1] in selected)
                                if both
                                else (set(pair) & selected)
                            ):
                                edges.append([rel, pair[0], pair[1], {}])
                    else:
                        values = getattr(self, attribute)
                        for key in values:
                            a, b = key[:2]
                            if (
                                (a in selected and b in selected)
                                if both
                                else (a in selected or b in selected)
                            ):
                                edges.append([rel, a, b, values[key] if isinstance(values, dict) else {}])
                continue
            selected = set(ids)
            for a_kind in left:
                for b_kind in right:
                    if rel == "CODE_EDGE" and (a_kind, b_kind) == ("DataObject", "Symbol"):
                        continue
                    payload = "properties(r)" if self.knowledge_backend == "neo4j" else "r"
                    # `base.by_ids` selects one endpoint at a time, so the `OR` form becomes two
                    # passes -- one driven from each end -- and the rows are unioned here. Every
                    # row the left pass returns has its `a` in `ids`, so the right pass skips
                    # exactly those and nothing else is de-duplicated: a `CODE_EDGE` exists once
                    # per `(a, b, kind)`, and one pair carrying two kinds is ordinary (R21-B5).
                    # `both` needs only the left pass: an edge whose far end is outside `ids` is
                    # dropped in Python rather than by a second list predicate.
                    heads = [f"{by_ids(a_kind, 'a')}-[r:{rel}]->(b:{b_kind})"]
                    if not both:
                        heads.append(f"{by_ids(b_kind, 'b')}<-[r:{rel}]-(a:{a_kind})")
                    for driven_from_b, head in enumerate(heads):
                        for row in self.run(f"{head} RETURN a.id AS a,b.id AS b,{payload} AS r", ids=ids):
                            if (both and row["b"] not in selected) or (
                                driven_from_b and row["a"] in selected
                            ):
                                continue
                            edges.append(
                                [
                                    rel,
                                    row["a"],
                                    row["b"],
                                    {
                                        key: value
                                        for key, value in dict(row["r"]).items()
                                        if not key.startswith("_")
                                    },
                                ]
                            )
        return edges

    def _native_relationships(self, *, ids=None, generation_id=None):
        """The generation's edges plus its shared-graph closure, in three bounded passes.

        `ids` names the selection set; `generation_id` derives the same set from the
        generation's own native rows. Exactly one is required -- a relationship read with no
        selection is the whole-database scan this replaces and no caller wants it.

        The passes reproduce the reviewed whole-database enumeration exactly:

        1. every edge touching `ids`, which keeps both endpoints of a crossing edge visible so
           `Native relationship crosses generations` still fires;
        2. the `MENTIONS`/`STATES` -> `SUBJECT`/`OBJECT` closure, a second scoped hop from the
           facts reached in pass 1;
        3. every edge with *both* endpoints inside the reached shared set, which is disjoint
           from pass 1 by construction, so the union needs no de-duplication.

        `sorted(..., key=canonical_json)` at the end means enumeration order never enters a
        checksum, which is why this restructuring is byte-identical.
        """
        if (ids is None) == (generation_id is None):
            raise ValueError("A relationship read needs exactly one scoping key: ids or generation_id")
        if generation_id is not None:
            ids = {
                row["id"]
                for kind in ("Passage", "Symbol", "DataObject", "Commit")
                for row in self._native_rows(kind, generation_id=generation_id)
            }
        ids = set(ids)
        edges = self._edges_touching(ids)
        endpoints = {endpoint for _, a, b, _ in edges for endpoint in (a, b)} - ids
        shared = {
            row["id"]: dict(row)
            for kind in ("Entity", "Fact")
            for row in self._native_rows(kind, ids=endpoints)
        }
        reachable = set(ids) | {endpoint for endpoint in endpoints if endpoint in shared}
        # The first hop of the reviewed closure (MENTIONS/STATES from a passage in `ids`) can add
        # nothing that pass 1 did not already reach, so only the SUBJECT/OBJECT hop is walked.
        for _rel, a, b, _ in self._edges_touching(reachable, rels=("SUBJECT", "OBJECT")):
            if a in reachable:
                reachable.add(b)
        closure = reachable - ids
        missing = closure - shared.keys()
        if missing:
            shared.update(
                {
                    row["id"]: dict(row)
                    for kind in ("Entity", "Fact")
                    for row in self._native_rows(kind, ids=missing)
                }
            )
        if closure:
            edges.extend(self._edges_touching(closure, both=True))
        result = []
        for rel, a, b, payload in edges:
            if not ((a in ids or b in ids) or ({a, b} <= reachable)):
                continue
            if any(endpoint not in ids and endpoint not in shared for endpoint in (a, b)):
                raise ValueError("Native relationship crosses generations")
            result.append([rel, a, b, payload])
        for rid in sorted(closure):
            if rid not in shared:
                raise ValueError("Missing shared graph endpoint")
            payload = {
                key: value
                for key, value in shared[rid].items()
                if key not in ("created_at", "updated_at") and not key.startswith("_") and value is not None
            }
            if payload.get("embedding") is not None:
                payload["embedding"] = float32_vector(payload["embedding"])
            result.append(["shared", rid, payload])
        return sorted(result, key=canonical_json)

    def generation_checksums(self, generation_id):
        from ..knowledge.generation_profiles import (
            PROFILE_POINTER,
            embedding_mode,
            validate_generation_profile,
        )

        gen = self._generation(generation_id)
        profile = validate_generation_profile(self, gen) if embedding_mode(gen) == "verified_v1" else None
        members = self._knowledge_rows("GenerationMember", generation_id=generation_id)
        exact = self._knowledge_rows("GenerationEvidenceMember", generation_id=generation_id)
        bindings = self._knowledge_rows("NativeBinding", generation_id=generation_id)
        evidence = {}

        def visit(record):
            key = (type(record).__name__, record.id)
            if key in evidence or key[0] in ("Artifact", "AccessPolicy", "Generation", "Source", "Workspace"):
                return
            evidence[key] = _evidence_row(record)
            for kind, rid in self._references(record):
                if kind in k.RECORD_TYPES:
                    target = self._knowledge_get(kind, rid)
                    if target is None:
                        raise ValueError("Missing immutable generation input")
                    visit(target)

        for record in [*members, *exact, *bindings]:
            visit(record)
        from ..knowledge.derivations import (
            GenerationViews,
            derived_capability,
            validate_generation_derivations,
        )

        if derived_capability(gen):
            validate_generation_derivations(self, gen.id)
            evidence[("DerivedCapability", gen.id)] = {"derived_evidence_version": 1}
        if profile is not None:
            evidence[("EmbeddingCapability", gen.id)] = {
                "embedding_binding_version": 1,
                "embedding_mode": "verified_v1",
                PROFILE_POINTER: json.loads(gen.coverage_json)[PROFILE_POINTER],
                "profile_fingerprint": profile.profile.fingerprint,
                "config_fingerprint": profile.config_fingerprint,
            }
        dense = self._native_rows("Passage", generation_id=generation_id)
        # Minimum capability coverage; a pipeline also verifies its declared chunk
        # inventory. Nested/support spans need not each have a separate vector.
        if not dense and any(
            member.record_kind == "EvidenceSpan"
            and self._knowledge_get("EvidenceSpan", member.record_id).text.strip()
            for member in exact
        ):
            raise ValueError("Nonempty exact text requires dense passage coverage")
        native = [
            (kind, r)
            for kind in ("Symbol", "DataObject", "Commit")
            for r in self._native_rows(kind, generation_id=generation_id)
        ]
        revisions = {m.artifact_revision_id for m in members}
        exact_ids = {(m.record_kind, m.record_id) for m in exact}
        for member in exact:
            target = self._knowledge_get(member.record_kind, member.record_id)
            if not self._record_revisions(target) <= revisions:
                raise ValueError("Evidence outside raw manifest")
            for kind, rid in self._references(target):
                if (
                    kind in k.GenerationEvidenceMember.model_fields["record_kind"].annotation.__args__
                    and (kind, rid) not in exact_ids
                ):
                    raise ValueError("Incomplete exact interpretation closure")
            if member.record_kind == "AssertionVersion":
                supports = [
                    s
                    for s in self._knowledge_rows("AssertionSupport")
                    if s.assertion_version_id == member.record_id
                ]
                if not supports or any(("AssertionSupport", s.id) not in exact_ids for s in supports):
                    raise ValueError("Incomplete assertion proof group")
        # Read once and index, not once per binding: this list is the same for every one of
        # them, and rebuilding it inside the loop is quadratic in the generation.
        observed_objects = {
            self._knowledge_get("ObjectObservation", m.record_id).object_id
            for m in exact
            if m.record_kind == "ObjectObservation"
        }
        for binding in bindings:
            native_row = self._knowledge_get(binding.native_kind, binding.native_id)
            span = self._knowledge_get("EvidenceSpan", binding.span_id)
            if (
                native_row is None
                or native_row.get("generation_id") != gen.id
                or span.revision_id not in revisions
                or ("EvidenceSpan", span.id) not in exact_ids
            ):
                raise ValueError("Binding native or evidence is outside generation closure")
            if binding.object_id not in observed_objects:
                raise ValueError("Native binding object lacks a selected observation")
        dimensions = set()
        from ..knowledge.derivations import validate_prose

        inputs = set()
        for member in exact:
            if member.record_kind != "ProseExtraction":
                continue
            extraction = self._knowledge_get("ProseExtraction", member.record_id)
            validate_prose(self, gen.id, extraction)
            key = (extraction.input_kind, extraction.input_id, extraction.extractor_profile)
            if key in inputs:
                raise ValueError("Conflicting prose extraction results for one input")
            inputs.add(key)
            dimensions.update(
                len(row.embedding) for row in (*extraction.payload.entities, *extraction.payload.triples)
            )
        # One inventory for every rendered passage, read at the first one that carries a view.
        views = GenerationViews(self, gen.id)
        for row in dense:
            self._validate_managed_native("Passage", row, gen, selected=revisions, views=views)
            if ("EvidenceSpan", row["span_id"]) not in exact_ids:
                raise ValueError("Passage span missing from exact manifest")
            dimensions.add(len(row["embedding"]))
        bound = {(b.native_kind, b.native_id) for b in bindings}
        for kind, row in native:
            self._validate_managed_native(kind, row, gen, selected=revisions)
            if (kind, row["id"]) not in bound:
                raise ValueError("Native row lacks evidence binding")
            if row.get("embedding"):
                dimensions.add(len(row["embedding"]))
        if len(dimensions) > 1:
            raise ValueError("Inconsistent vector dimensions")
        if profile is not None and dimensions and dimensions != {profile.profile.profile.dimension}:
            raise ValueError("Vector dimensions differ from the accepted embedding profile")
        ids = {r["id"] for r in dense} | {r["id"] for _, r in native}
        representations = {
            "evidence": sorted(evidence.values(), key=canonical_json),
            "dense": sorted([self._canonical_native("Passage", r) for r in dense], key=canonical_json),
            "native": [
                *sorted([[kind, self._canonical_native(kind, r)] for kind, r in native], key=canonical_json),
                *self._native_relationships(ids=ids),
            ],
        }
        return tuple(
            k.RepresentationChecksum(
                kind=kind, checksum=text_hash(canonical_json(rows)), row_count=len(rows), ready=True
            )
            for kind, rows in representations.items()
        )

    def _verify_manifest(self, gen, manifest):
        from ..knowledge.generation_profiles import embedding_mode, validate_generation_profile

        if embedding_mode(gen) == "verified_v1":
            profile = validate_generation_profile(self, gen)
            if manifest.config_fingerprint != profile.config_fingerprint:
                raise ValueError("Index manifest differs from accepted configuration")
        if (
            manifest.generation_id != gen.id
            or manifest.profile_fingerprint != gen.embedding_profile
            or not manifest.ready
            or set(manifest.required_representations) != set(MANDATORY_REPRESENTATIONS)
            or {c.kind for c in manifest.checksums} != set(MANDATORY_REPRESENTATIONS)
        ):
            raise ValueError(
                "Generation requires evidence, dense, and native representations with matching profile"
            )
        if {c.kind: c for c in manifest.checksums} != {c.kind: c for c in self.generation_checksums(gen.id)}:
            raise ValueError("Representation checksums do not match persisted generation")

    def seal_generation(
        self, generation_id, index_manifest, *, job_id, lease_owner, fencing_token, fault_hook=None
    ):
        with self.transaction():
            self._check_build(
                generation_id, job_id=job_id, lease_owner=lease_owner, fencing_token=fencing_token
            )
            gen = self._generation(generation_id)
            self._verify_manifest(gen, index_manifest)
            manifests = self._knowledge_rows("IndexManifest", generation_id=gen.id)
            if any(m != index_manifest for m in manifests):
                raise ValueError("Conflicting generation manifest")
            self._write_knowledge(index_manifest)
            if fault_hook:
                fault_hook("seal")
            self._write_knowledge(gen.replace(status="ready"))
            bump_epoch(self, "content_epoch")
            return index_manifest.id

    def validate_generation_seal(self, generation_id):
        gen = self._generation(generation_id)
        manifests = self._knowledge_rows("IndexManifest", generation_id=generation_id)
        if gen.status not in ("ready", "active", "retired") or len(manifests) != 1:
            raise ValueError("Generation requires a strict rebuild")
        self._verify_manifest(gen, manifests[0])
        return manifests[0]

    def _plan_row(self, kind, record_id):
        row = self._knowledge_get(kind, record_id)
        if row is None:
            raise ValueError("Correction plan names a missing recorded row")
        return row

    def _plan_lineage(self, kind, row):
        """The sources and revisions the row's complete support actually depends on."""
        if kind == "ObjectObservation":
            span = self._knowledge_get("EvidenceSpan", row.span_id)
            revisions = {row.revision_id} | ({span.revision_id} if span is not None else set())
        else:
            supports = [
                s for s in self._knowledge_rows("AssertionSupport") if s.assertion_version_id == row.id
            ]
            if not supports:
                raise ValueError("Correction plan target has no complete support group")
            revisions = set()
            for support in supports:
                span = self._knowledge_get("EvidenceSpan", support.span_id)
                if span is None:
                    raise ValueError("Correction plan target has no complete support group")
                revisions.add(span.revision_id)
        sources = set()
        for revision_id in sorted(revisions):
            revision = self._knowledge_get("ArtifactRevision", revision_id)
            artifact = None if revision is None else self._knowledge_get("Artifact", revision.artifact_id)
            if artifact is None:
                raise ValueError("Correction plan target has no complete support group")
            sources.add(artifact.source_id)
        return sources, revisions

    def _plan_series(self, kind, row):
        """The logical series a corrected segment belongs to, never a bare record ID.

        A correction replaces a claim, not a row: the May example closes
        `checkout OWNED_BY ada` and appends `checkout OWNED_BY bo`, which are
        different assertions in one workspace/subject/predicate/scope series.
        Object observations correct object observations, so their series is the
        observed object; the kind is part of the key and the two never cross.
        """
        if kind == "ObjectObservation":
            return (kind, row.object_id)
        assertion = self._knowledge_get("Assertion", row.assertion_id)
        return (
            kind,
            assertion.workspace_id,
            assertion.subject_id,
            assertion.predicate,
            assertion.scope_key,
        )

    def _validate_publication_plan(self, gen, plan):
        """Prove every closure and every append before the publication writes anything."""
        workspace = self.get_source(gen.source_id)["workspace_id"]
        staged = {
            (m.record_kind, m.record_id)
            for m in self._knowledge_rows("GenerationEvidenceMember", generation_id=gen.id)
        }
        series = set()
        for segment in plan.closures:
            row = self._plan_row(segment.record_kind, segment.record_id)
            if self._workspaces(row) != {workspace}:
                raise ValueError("Correction plan target belongs to another workspace")
            sources, _ = self._plan_lineage(segment.record_kind, row)
            if sources != {gen.source_id}:
                raise ValueError("Correction plan target is outside this source lineage")
            if row.recorded_to is not None:
                raise ValueError("Correction plan target is already closed")
            if row.recorded_from >= plan.published_at:
                raise ValueError("Correction plan target was not recorded before the publication")
            if (segment.record_kind, segment.record_id) in staged:
                # A correction closes what an earlier generation published. Closing
                # a row this very generation carries would mint a recorded window
                # over which Hippo exposed nothing, because the generation holding
                # the row was not active for any of it.
                raise ValueError("Correction plan target belongs to the generation being published")
            series.add(self._plan_series(segment.record_kind, row))
        revisions = self._selected_revisions(gen.id)
        for segment in plan.appends:
            if (segment.record_kind, segment.record_id) not in staged:
                raise ValueError("Corrected segment is not an exact member of the staged generation")
            row = self._plan_row(segment.record_kind, segment.record_id)
            if row.recorded_from != plan.published_at or row.recorded_to is not None:
                raise ValueError("Corrected segment must open at the publication instant")
            if self._plan_series(segment.record_kind, row) not in series:
                raise ValueError("Corrected segment belongs to another corrected series")
            _, dependencies = self._plan_lineage(segment.record_kind, row)
            supports = {
                ("AssertionSupport", s.id)
                for s in self._knowledge_rows("AssertionSupport")
                if s.assertion_version_id == row.id and segment.record_kind == "AssertionVersion"
            }
            # Defense in depth, not the operative guard: `validate_generation_seal`
            # already refuses a member version whose proof group is incomplete
            # (`:703-710`, re-run above), so every route here through publication
            # is refused earlier. This is what proves the dependency if a plan is
            # ever validated against a generation that check did not cover.
            if not dependencies <= revisions or not supports <= staged:
                raise ValueError("Corrected segment depends on evidence outside its generation")

    def _observe_recorded_closures(self, plan):
        """An exact retry observes the closures its own publication already committed."""
        for segment in plan.closures:
            row = self._knowledge_get(segment.record_kind, segment.record_id)
            if row is None or row.recorded_to != plan.published_at:
                raise ValueError("Recorded correction differs from the committed publication")

    def publish_staged_generation(
        self,
        generation_id,
        *,
        expected_parent_id,
        job_id,
        lease_owner,
        fencing_token,
        expected_suppression_epoch,
        published_at,
        plan=None,
        fault_hook=None,
    ):
        with self.transaction():
            gen = self._generation(generation_id)
            self._lock_source(gen.source_id)
            if plan is not None and plan.published_at != published_at:
                raise ValueError("Correction plan disagrees with the publication clock")
            receipt = [
                e
                for e in self._knowledge_rows("IndexEvent", generation_id=generation_id)
                if e.kind == "published"
            ]
            origin = dict(job_id=job_id, fencing_token=fencing_token, lease_owner=lease_owner)
            if plan is not None:
                # The receipt carries the plan, so a retry that corrects something
                # else is a different publication and is refused before any read.
                origin["temporal_plan"] = plan.fingerprint
            if receipt:
                if (
                    len(receipt) == 1
                    and json.loads(receipt[0].payload_json) == origin
                    and gen.parent_id == expected_parent_id
                ):
                    if plan is not None:
                        self._observe_recorded_closures(plan)
                    return receipt[0].id
                raise ValueError("Publication belongs to another build")
            job = self._check_build(
                generation_id,
                job_id=job_id,
                lease_owner=lease_owner,
                fencing_token=fencing_token,
                states=("ready",),
            )
            if expected_suppression_epoch != self.suppression_epoch():
                raise ValueError("Suppression changed during build")
            suppressed = {(s.target_kind, s.target_id) for s in self._knowledge_rows("Suppression")}
            reachable = {("source", gen.source_id)}
            for member in self._knowledge_rows("GenerationMember", generation_id=gen.id):
                revision = self._knowledge_get("ArtifactRevision", member.artifact_revision_id)
                artifact = self._knowledge_get("Artifact", revision.artifact_id)
                if artifact.deleted_at is not None:
                    raise ValueError("Generation includes tombstoned artifact")
                reachable |= {
                    ("revision", revision.id),
                    ("artifact", artifact.id),
                    ("policy", artifact.policy_id),
                }
            for member in self._knowledge_rows("GenerationEvidenceMember", generation_id=gen.id):
                kind = {
                    "EvidenceSpan": "span",
                    "AssertionVersion": "assertion_version",
                    "DerivedRecord": "derived_record",
                }.get(member.record_kind)
                if kind:
                    reachable.add((kind, member.record_id))
            if reachable & suppressed:
                raise ValueError("Suppressed generation cannot activate")
            self.validate_generation_seal(gen.id)
            if plan is not None:
                self._validate_publication_plan(gen, plan)
                # The capability is minted only here, only on a proved plan, and
                # only for as long as its closures take: it is what makes this
                # primitive the sole coordinator rather than merely the usual
                # caller of a private method.
                with self._recorded_closure_capability(gen.id, plan) as capability:
                    self._close_recorded_intervals(
                        tuple((s.record_kind, s.record_id) for s in plan.closures),
                        recorded_to=plan.published_at,
                        capability=capability,
                    )
                if fault_hook:
                    fault_hook("closure")
            result = self._publish_generation(
                gen.id,
                expected_parent_id=expected_parent_id,
                published_at=published_at,
                payload_json=canonical_json(origin),
                fault_hook=fault_hook,
            )
            self._write_knowledge(job.replace(status="completed", phase="complete"))
            self._source_fields(gen.source_id, active_build_id=None)
            if fault_hook:
                fault_hook("lease")
            return result

    def publish_generation(
        self, generation_id, *, expected_parent_id, published_at, plan=None, fault_hook=None
    ):
        """Trusted fixture compatibility primitive; production uses strict publication.

        A correction plan is refused outright here. This path takes no lease, no
        fence and no suppression epoch, so honouring one would make the fixture
        primitive the shortest route to closing a published interpretation.
        """
        if plan is not None:
            raise ValueError("A correction plan is honoured only by strict publication")
        with self.transaction():
            return self._publish_generation(
                generation_id,
                expected_parent_id=expected_parent_id,
                published_at=published_at,
                fault_hook=fault_hook,
            )

    def _publish_generation(
        self, generation_id, *, expected_parent_id, published_at, fault_hook=None, payload_json="{}"
    ):
        gen = self._generation(generation_id)
        self._lock_source(gen.source_id)
        if gen.parent_id != expected_parent_id:
            raise ValueError("Generation parent differs from compare-and-swap parent")
        source = self.get_source(gen.source_id)
        active = source.get("active_generation_id")
        if active == gen.id:
            events = [
                e for e in self._knowledge_rows("IndexEvent", generation_id=gen.id) if e.kind == "published"
            ]
            if len(events) != 1:
                raise ValueError("Active generation lacks a unique publication event")
            return events[0].id
        if active != expected_parent_id:
            raise ValueError("Generation publication compare-and-swap failed")
        manifests = self._knowledge_rows("IndexManifest", generation_id=gen.id)
        if gen.status != "ready" or len(manifests) != 1 or not manifests[0].ready:
            raise ValueError("Generation requires a complete ready index manifest")
        self._write_knowledge(gen.replace(status="active", published_at=published_at))
        sequence = int(source.get("generation_version") or 0) + 1
        self._source_fields(gen.source_id, active_generation_id=gen.id, generation_version=sequence)
        if fault_hook:
            fault_hook("pointer")
        if active:
            self._write_knowledge(self._generation(active).replace(status="retired"))
        if fault_hook:
            fault_hook("retirement")
        self.bump_graph_version()
        bump_epoch(self, "content_epoch")
        if fault_hook:
            fault_hook("version")
        event = k.IndexEvent(
            workspace_id=source["workspace_id"],
            generation_id=gen.id,
            kind="published",
            aggregate_id=gen.source_id,
            sequence=sequence,
            dedupe_key=gen.id,
            created_at=published_at,
            payload_json=payload_json,
        )
        self._write_knowledge(event)
        if fault_hook:
            fault_hook("event")
        return event.id

    def _canonical_native(self, kind, row):
        from .code import commit_write_row, data_object_write_row, symbol_write_row

        if kind == "Passage":
            shaped = {
                key: row.get(key)
                for key in (
                    "id",
                    "source_id",
                    "generation_id",
                    "artifact_revision_id",
                    "span_id",
                    "embedding_profile",
                    "parent_passage_id",
                    "content_kind",
                )
            }
            if row.get("retrieval_view_id") is not None:
                shaped["retrieval_view_id"] = row["retrieval_view_id"]
            shaped.update(
                title=row.get("title") or "",
                text=row.get("text") or "",
                ordinal=int(row.get("ordinal") or 0),
                embedding=row.get("embedding") or [],
            )
        else:
            shaped = {
                "Symbol": symbol_write_row,
                "DataObject": data_object_write_row,
                "Commit": commit_write_row,
            }[kind](row)
            shaped["generation_id"] = row.get("generation_id")
        for key in ("boost", "community", "entities_json", "triples_json", "extraction_error"):
            shaped[key] = row.get(key)
        if "embedding" in shaped:
            shaped["embedding"] = float32_vector(shaped["embedding"])
        return shaped

    def _selected_revisions(self, generation_id):
        """The generation's member revisions. Hoist this out of a per-row loop before calling."""
        return {
            m.artifact_revision_id
            for m in self._knowledge_rows("GenerationMember", generation_id=generation_id)
        }

    def _validate_managed_native(self, kind, row, gen, *, selected=None, views=None):
        """Validate one managed native row.

        `selected` is the generation's member revisions. A caller in a loop passes it once --
        reading it here per row is the same whole-table read repeated N times, which is what made
        writing a 50,000-symbol generation quadratic rather than linear.

        `views` is the same hoist for a rendered passage: a `derivations.GenerationViews` for
        `gen`, whose inventory of the generation's exact membership is read at the first view and
        reused for the rest of the caller's batch. Without it each view is validated from a fresh
        read, exactly as `validate_view` does.
        """
        if row.get("source_id") != gen.source_id or row.get("generation_id") != gen.id:
            raise ValueError("Native row source or generation differs")
        if kind == "Passage":
            span = self._knowledge_get("EvidenceSpan", row.get("span_id"))
            revision = self._knowledge_get("ArtifactRevision", row.get("artifact_revision_id"))
            if selected is None:
                selected = self._selected_revisions(gen.id)
            view = None
            if row.get("retrieval_view_id") is not None:
                from ..knowledge.derivations import GenerationViews

                view = self._knowledge_get("RetrievalView", row["retrieval_view_id"])
                if view is None:
                    raise ValueError("Missing rendered retrieval view")
                (GenerationViews(self, gen.id) if views is None else views).validate(view)
                if (
                    view.span_id != row.get("span_id")
                    or view.source_revision_id != row.get("artifact_revision_id")
                    or view.vector_profile != gen.embedding_profile
                ):
                    raise ValueError("Rendered passage binding differs")
            if (
                span is None
                or revision is None
                or revision.id not in selected
                or span.revision_id != revision.id
                or row.get("embedding_profile") != gen.embedding_profile
                or row.get("text") != (view.text if view else span.text)
            ):
                raise ValueError("Passage revision/span/profile/original text binding differs")
            from ..knowledge.lifecycle import generation_passage_id

            if row.get("id") != generation_passage_id(
                gen.id,
                revision.id,
                span.id,
                row.get("ordinal", 0),
                retrieval_view_id=row.get("retrieval_view_id"),
            ):
                raise ValueError("Passage ID does not match generation binding")
            if not row.get("embedding"):
                raise ValueError("Dense passage requires a vector")
            parent = row.get("parent_passage_id")
            if parent:
                parent_row = next(iter(self._native_rows("Passage", ids=[parent])), None)
                if (
                    parent_row is None
                    or parent_row.get("generation_id") != gen.id
                    or parent_row.get("artifact_revision_id") != revision.id
                ):
                    raise ValueError("Passage parent crosses generation/revision")
        else:
            from ..codegraph.model import commit_id, data_id, symbol_id
            from ..knowledge.lifecycle import generation_namespace

            namespace = generation_namespace(gen)
            if kind == "Symbol":
                expected = symbol_id(
                    gen.source_id,
                    row.get("path") or "",
                    row.get("qualname") or "",
                    row.get("kind") or "",
                    node_namespace=namespace,
                )
            elif kind == "DataObject":
                expected = data_id(
                    gen.source_id, row.get("kind") or "", row.get("qualname") or "", node_namespace=namespace
                )
            else:
                expected = commit_id(gen.source_id, row.get("sha") or "", node_namespace=namespace)
            if row["id"] != expected:
                raise ValueError("Native ID does not match generation namespace")
        float32_vector(row.get("embedding") or [])


def float32_vector(values):
    import math
    import struct

    try:
        result = [struct.unpack("f", struct.pack("f", float(value)))[0] for value in values]
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("Invalid persisted vector") from error
    if any(not math.isfinite(value) for value in result):
        raise ValueError("Vector must be finite")
    return result


def native_write(kind):
    """All backends check existing ownership before accepting untagged updates."""
    from functools import wraps

    def decorate(function):
        @wraps(function)
        def wrapped(store, rows):
            with store.transaction():
                store._lock_authorization()
                # Scoped by id, not by generation: the write has to find a row that may carry no
                # generation at all, which is the fallback that keeps untagged legacy writes
                # working, so the batch's own ids are the only key available here.
                existing = {
                    row["id"]: row for row in store._native_rows(kind, ids=[row["id"] for row in rows])
                }
                from ..knowledge.derivations import GenerationViews

                selected = {}  # generation id -> member revisions, read once per generation
                generations = {}  # the same, for the Generation row itself
                views = {}  # the same, for the inventory a rendered passage is validated against
                checked = set()  # generations already proven writable in this call

                def writable(generation_id):
                    if generation_id not in checked:
                        store._assert_generation_writable(generation_id)
                        checked.add(generation_id)

                pending = []
                managed = []
                for row in rows:
                    prior = existing.get(row["id"])
                    generation_id = row.get("generation_id") or (prior or {}).get("generation_id")
                    if generation_id is None:
                        if store.source_is_managed(row["source_id"]) and any(
                            j.source_id == row["source_id"] and j.kind == "rebuild"
                            for j in store._knowledge_rows("MaintenanceJob")
                        ):
                            raise ValueError("Managed native writes require generation context")
                        pending.append(row)
                        continue
                    if generation_id not in generations:
                        generations[generation_id] = store._generation(generation_id)
                        # Only the Passage branch reads it; the others never look.
                        selected[generation_id] = (
                            store._selected_revisions(generation_id) if kind == "Passage" else None
                        )
                        # Reads nothing until a row carries a view, so a generation with no derived
                        # capability never builds an inventory and never meets its refusal.
                        views[generation_id] = GenerationViews(store, generation_id)
                    gen = generations[generation_id]
                    store._validate_managed_native(
                        kind, row, gen, selected=selected[generation_id], views=views[generation_id]
                    )
                    if gen.status == "staging":
                        writable(generation_id)
                    shaped = store._canonical_native(kind, row)
                    if prior is not None:
                        if {
                            key: value
                            for key, value in store._canonical_native(kind, prior).items()
                            if key
                            not in ("boost", "community", "entities_json", "triples_json", "extraction_error")
                        } != {
                            key: value
                            for key, value in shaped.items()
                            if key
                            not in ("boost", "community", "entities_json", "triples_json", "extraction_error")
                        }:
                            raise ValueError("Managed native payload is immutable")
                        continue
                    writable(generation_id)
                    pending.append({**row, **shaped})
                    managed.append(shaped)
                result = function(store, pending) if pending else None
                # Persist managed columns through one shared backend-safe path. The
                # original writer remains the source of legacy payload behavior.
                for row in managed:
                    columns = (
                        (
                            "generation_id",
                            "artifact_revision_id",
                            "span_id",
                            "embedding_profile",
                            "parent_passage_id",
                            "content_kind",
                            "retrieval_view_id",
                        )
                        if kind == "Passage"
                        else ("generation_id",)
                    )
                    fields = {key: row.get(key) for key in columns}
                    if store.knowledge_backend == "fake":
                        attr = {
                            "Passage": "passages",
                            "Symbol": "symbols",
                            "DataObject": "data_objects",
                            "Commit": "commits",
                            "Entity": "entities",
                            "Fact": "facts",
                        }[kind]
                        getattr(store, attr)[row["id"]].update(fields)
                    else:
                        store.run(
                            f"MATCH (n:{kind} {{id:$id}}) SET "
                            + ", ".join(f"n.{key}=${key}" for key in fields),
                            id=row["id"],
                            **fields,
                        )
                if managed:
                    bump_epoch(store, "content_epoch")
                return result

        return wrapped

    return decorate


def native_mutation(function):
    """Guard all indirect native payload/edge writers in the same transaction."""
    from functools import wraps

    @wraps(function)
    def wrapped(store, *args, **kwargs):
        from collections.abc import Iterable

        def materialize(value):
            if isinstance(value, dict):
                return {key: materialize(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return type(value)(materialize(item) for item in value)
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
                return [materialize(item) for item in value]
            return value

        args = materialize(args)
        kwargs = materialize(kwargs)

        def strings(value):
            """Every string anywhere in the call, which is the candidate set of native ids."""
            if isinstance(value, str):
                return {value}
            if isinstance(value, dict):
                return set().union(*(strings(key) | strings(item) for key, item in value.items()), set())
            if isinstance(value, (list, tuple, set)):
                return set().union(*(strings(item) for item in value), set())
            return set()

        with store.transaction():
            store._lock_authorization()
            # Membership in the native tables used to be decided by materialising all six of
            # them. The arguments bound the question instead: every string the call mentions is
            # a candidate, and one scoped read per kind says which of them are real. Rows of
            # *other* generations stay visible, so the cross-generation check below is unchanged.
            candidates = strings(args) | strings(kwargs)
            natives = {
                row["id"]: row
                for kind in ("Passage", "Symbol", "DataObject", "Commit", "Entity", "Fact")
                for row in store._native_rows(kind, ids=candidates)
            }

            def ids(value):
                if isinstance(value, str):
                    return {value} if value in natives else set()
                if isinstance(value, dict):
                    return (
                        set().union(*(ids(key) | ids(item) for key, item in value.items()))
                        if value
                        else set()
                    )
                if isinstance(value, (list, tuple, set)):
                    return set().union(*(ids(item) for item in value)) if value else set()
                return set()

            touched = ids(args) | ids(kwargs)
            generations = {natives[rid].get("generation_id") for rid in touched} - {None}
            # A relationship cannot connect native rows owned by different generations.
            if function.__name__ in (
                "add_code_edges",
                "link_definitions",
                "add_modifies",
                "add_precedes",
                "add_refers_to",
                "add_synonyms",
                "set_edge_weight",
                "clear_edge_weight",
            ):
                candidate = args[0] if args else next(iter(kwargs.values()), ())
                rows = candidate if isinstance(candidate, list) else [(args, kwargs)]
                for row in rows:
                    endpoints = ids(row)
                    scopes = {
                        natives[rid].get("generation_id")
                        for rid in endpoints
                        if not rid.startswith(("entity-", "fact-"))
                    }
                    if len(scopes) > 1 and scopes - {None}:
                        raise ValueError("Native relationship crosses generations")
            sealed = {}
            if any(rid.startswith(("entity-", "fact-")) for rid in touched):
                generations.update(
                    m.generation_id
                    for m in store._knowledge_rows("IndexManifest")
                    if m.ready and set(m.required_representations) == set(MANDATORY_REPRESENTATIONS)
                )
            for generation_id in generations:
                if store._generation(generation_id).status == "staging":
                    store._assert_generation_writable(generation_id)
                else:
                    sealed[generation_id] = store.generation_checksums(generation_id)
            result = function(store, *args, **kwargs)
            for generation_id, before in sealed.items():
                if store.generation_checksums(generation_id) != before:
                    raise ValueError("Sealed native payload or relationship is immutable")
            if generations - sealed.keys():
                bump_epoch(store, "content_epoch")
            return result

    return wrapped


def legacy_source_cleanup(function):
    from functools import wraps

    @wraps(function)
    def wrapped(store, source_id, *args, **kwargs):
        with store.transaction():
            store._lock_source(source_id)
            if store.source_is_managed(source_id):
                raise ValueError("Managed source requires suppression and generation collection")
            return function(store, source_id, *args, **kwargs)

    return wrapped
