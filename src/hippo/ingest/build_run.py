"""The run state a managed build coordinator holds, owned by neither lane.

A coordinator's job is long, detached and cancellable, and everything that makes
that safe is the same whatever it is building: one captured `BuildAuthority`, one
lease heartbeat renewing the store's fence, one cooperative cancellation
checkpoint, and one failure latch that remembers the *first* thing that went
wrong so a downstream symptom can never be reported as the cause.

`prose_generation.py` owned all of it privately as `_Run` and still imports it
under that name; the code coordinator (`code_generation.py`) takes the same
class rather than a copy. Only the two operator-facing strings differ between
lanes, so they are constructor arguments with the plain-prose wording as the
default. Nothing here knows what a chunk, a document or a repository is.

`BuildRun` reads exactly two attributes from a lane's `options`
(`lease_duration_seconds` and `renewal_interval_seconds`), so each lane keeps
its own frozen options type.
"""

import json
from dataclasses import dataclass
from datetime import timedelta
from threading import RLock
from uuid import uuid4

from ..knowledge.access import AuthorizationChanged
from ..knowledge.build_authority import capture_build_authority
from ..knowledge.lease_heartbeat import LeaseHeartbeat


class BuildCancelled(RuntimeError):
    """Cancellation reached a cooperative checkpoint before commit admission."""


class BuildBusy(ValueError):
    """Another invocation owns the live source build or changed its head."""


@dataclass(frozen=True)
class BuildProgress:
    phase: str
    completed: int = 0
    total: int = 0


@dataclass(frozen=True)
class BuildReceipt:
    source_id: str
    generation_id: str
    event_id: str
    accepted_input_hash: str
    outcome: str
    # What a resumed or long build had to do, as counts. A lane that neither
    # resumes nor rebaselines leaves both at zero, which is what the plain
    # prose lane does. Counts only: still no path, no text, no exception body.
    resumed_from_batches: int = 0
    rebaselines: int = 0


def credentials(job):
    return dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)


def authority_fields(guard):
    return dict(
        expected_authorization_epoch=guard.expected_authorization_epoch,
        expected_suppression_epoch=guard.expected_suppression_epoch,
    )


class BuildRun:
    def __init__(
        self,
        ctx,
        actor,
        source_id,
        options,
        should_stop,
        on_progress,
        *,
        capture=capture_build_authority,
        cancelled_message="Plain source build cancelled",
        renewal_failed_message="Plain build lease renewal failed",
    ):
        self.store, self.actor, self.options = ctx.store, actor, options
        self.should_stop, self.on_progress = should_stop, on_progress
        self.cancelled_message = cancelled_message
        self.renewal_failed_message = renewal_failed_message
        self.guard = capture(self.store, source_id=source_id, actor=actor, clock=self.store._now)
        self.heartbeat, self.job, self.generation, self.receipt = None, None, None, None
        self.owner = uuid4().hex
        self._lock, self._closed = RLock(), False
        self._failure = None

    def _fail(self, error):
        with self._lock:
            if self._failure is None:
                self._failure = error

    def _cancel(self):
        with self._lock:
            closed = self._closed
            failure = self._failure
        if failure is not None:
            raise failure
        if closed or self.should_stop():
            raise BuildCancelled(self.cancelled_message)

    def check(self):
        try:
            self._check()
        except BaseException as error:
            self._fail(error)
            raise

    def _check(self):
        self._cancel()
        # One read: pause() clears the attribute before it joins this worker, so
        # re-reading it would test one worker and use another (or None).
        heartbeat = self.heartbeat
        if heartbeat is not None:
            heartbeat.check()
        # Store transaction depth is shared across threads. The caller already
        # guarantees no ambient transaction; another renewal is not one. Hold
        # only local reads here and invoke arbitrary callbacks outside the lock.
        with self._lock:
            with self.store.transaction():
                self.guard.check_local()
                if self.job is not None:
                    self.store._check_build(
                        self.generation.id, **credentials(self.job), states=("staging", "ready")
                    )
                self.guard.check_local()
        if heartbeat is not None:
            heartbeat.check()
        self._cancel()

    def renew(self):
        try:
            self.check()
            with self._lock:
                if self.job is not None:
                    with self.store.transaction():
                        self.guard.check_local()
                        current = self.store._check_build(
                            self.generation.id, **credentials(self.job), states=("staging", "ready")
                        )
                        expiry = max(
                            self.store._now() + timedelta(seconds=self.options.lease_duration_seconds),
                            current.lease_expires_at
                            + timedelta(seconds=self.options.renewal_interval_seconds),
                        )
                        self.store.renew_generation_build(
                            self.job.id,
                            **{key: value for key, value in credentials(self.job).items() if key != "job_id"},
                            lease_expires_at=expiry,
                        )
                        self.guard.check_local()
        except BuildCancelled:
            raise  # Cancellation is the caller's own decision, not a lost lease.
        except BaseException as error:
            failure = AuthorizationChanged(self.renewal_failed_message)
            self._fail(failure)
            raise failure from error

    def start(self):
        self.heartbeat = LeaseHeartbeat(self.renew, interval=self.options.renewal_interval_seconds)
        try:
            self.heartbeat.start()
        except BaseException as error:
            self._fail(error)
            raise

    def pause(self):
        heartbeat, self.heartbeat = self.heartbeat, None
        if heartbeat is not None:
            heartbeat.close()
            heartbeat.check()

    def progress(self, phase, completed=0, total=0):
        self.check()
        if self.on_progress is not None:
            try:
                self.on_progress(BuildProgress(phase, completed, total))
            except BaseException as error:
                self._fail(error)
                raise
            finally:
                self.check()

    def adopt(self, guard):
        with self._lock:
            previous, self.guard = self.guard, guard
            previous.close()

    def close(self):
        try:
            self.pause()
        finally:
            with self._lock:
                self._closed = True
            self.guard.close()


# --------------------------------------------------------- lane-neutral coordinator helpers
#
# Five helpers the code coordinator owned privately, moved here under public names because the
# connector runtime (`connectors/sync.py`) needs the same five and must not import a build
# lane to get them (plan section 8). Nothing below knows what a repository, a chunk or a
# connector is: each takes a store or a run, a generation, and the accepted manifest's hash.
# `code_generation.py` keeps every old name bound, as `prose_generation.py` keeps `_Run`.


def adopt_capture_instant(store, gen, candidate):
    """Design review B4: identity first, then one instant, adopted from a resumable attempt.

    `Generation.identity_fields` excludes `created_at`, so the same inputs at two
    instants are one generation with two different `ObjectObservation` inventories --
    which is exactly what a resume must never produce. The accepted manifest and the
    generation ID are instant-independent, so they are settled first and the instant is
    resolved once: a never-published attempt's stored instant, or one `store._now()`.
    """
    existing = store._knowledge_get("Generation", gen.id)
    if existing is None or existing.published_at is not None or existing.status not in ("staging", "failed"):
        return candidate
    return existing.created_at


def operation_generation(store, gen, operation_id):
    """This operation's prior generation, if this operation ran before."""
    jobs = [
        job
        for job in store._knowledge_rows("MaintenanceJob")
        if job.source_id == gen.source_id and job.kind == "rebuild" and job.job_key == operation_id
    ]
    if len(jobs) > 1:
        raise ValueError("Conflicting source operation identity")
    if not jobs:
        return None
    job = jobs[0]
    previous = store._generation(job.input_fingerprint)
    if previous.source_id != gen.source_id or previous.manifest_hash != gen.manifest_hash:
        raise ValueError("Source operation cannot target different accepted inputs")
    if previous.status not in {"active", "retired"} and previous.id != gen.id:
        raise ValueError("Source operation cannot target a different generation")
    return previous, job


def published_receipt(store, gen, manifest_sha256, outcome, job=None, *, resumed=0, rebaselines=0):
    """The receipt of a published generation, from its one `published` event.

    Takes the accepted manifest's hash rather than a lane's capture record: the code lane
    reads it off `CapturedCode`, the connector runtime off its inventory manifest, and the
    receipt itself cares about neither.
    """
    events = [
        e for e in store._knowledge_rows("IndexEvent") if e.generation_id == gen.id and e.kind == "published"
    ]
    if len(events) != 1:
        raise ValueError("Published generation lacks a unique receipt")
    if job is not None and (
        json.loads(events[0].payload_json) != credentials(job)
        or job.expected_parent_id != gen.parent_id
        or events[0].aggregate_id != gen.source_id
    ):
        raise ValueError("Publication receipt differs from original build credentials")
    return BuildReceipt(gen.source_id, gen.id, events[0].id, manifest_sha256, outcome, resumed, rebaselines)


def prior_receipt(run, gen, manifest_sha256, operation_id):
    """`operation_id` replay and `already_current`, both without inference or writes."""
    # Deferred, as `staged_code._accepted` defers the same pair: `generation_profiles` reaches
    # `input_binding`, the one knowledge module allowed to import `ingest`, and importing it
    # here would drag the reader stack into every module that only wants the run state.
    from ..knowledge.generation_profiles import embedding_mode, validate_generation_profile

    active = run.guard.source_control.active_generation_id
    with run.store.transaction():
        run.store._lock_source(gen.source_id)
        run.guard.check_local()
        operation = operation_generation(run.store, gen, operation_id)
        if operation is not None and operation[0].status in {"active", "retired"}:
            old, job = operation
            if job.status != "completed" or embedding_mode(old) != "verified_v1":
                raise ValueError("Source operation lacks a verified publication")
            run.store.validate_generation_seal(old.id)
            validate_generation_profile(run.store, old)
            result = published_receipt(run.store, old, manifest_sha256, "already_published", job)
            run.guard.check_local()
            return result
        if not active:
            return None
        old = run.store._generation(active)
        if old.manifest_hash != gen.manifest_hash or embedding_mode(old) != "verified_v1":
            return None
        run.store.validate_generation_seal(old.id)
        validate_generation_profile(run.store, old)
        result = published_receipt(run.store, old, manifest_sha256, "already_current")
        run.guard.check_local()
        return result


def rebaseline_between_batches(run):
    """Ruling 2: adopt an unrelated authorization epoch between two batches, or abort.

    CC8 finding 2: `check_local()` latches its own refusal and a rebaseline is forbidden
    after a sticky failure, so the epoch comparison has to happen *before* the external
    check rather than in response to it. Everything else -- a lost capability, a
    suppression change, a changed `SourceControl` -- refuses inside `rebaseline()` and
    aborts this build with the staged inventory retained.
    """
    if run.store.authorization_epoch() == run.guard.expected_authorization_epoch:
        return 0
    run.adopt(run.guard.rebaseline())
    return 1
