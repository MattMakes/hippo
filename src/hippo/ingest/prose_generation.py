"""Explicit plain-source builds with detached preparation and atomic bootstrap.

No production ingestion route calls this module. Source management authority is
required; raw objects are retained conservatively on every outcome.
"""

import json
import math
from dataclasses import dataclass, field, replace
from datetime import timedelta
from itertools import chain
from threading import RLock
from uuid import uuid4

from ..knowledge import model as k
from ..knowledge.access import AuthorizationChanged
from ..knowledge.build_authority import AcceptedBuildInputs, BuildActor, capture_build_authority
from ..knowledge.embedding_cache import EmbeddingCache
from ..knowledge.embedding_profile import (
    EmbeddingSpec,
    ProfiledEmbeddings,
    resolve_embedding_profile,
    validate_profile_descriptor,
)
from ..knowledge.generation_profiles import MANIFEST_EXTERNAL_ID, embedding_mode, validate_generation_profile
from ..knowledge.identity import canonical_json
from ..knowledge.input_binding import (
    MATERIALIZER_VERSION,
    AcceptedArtifactBinding,
    materialize_chunk_evidence,
)
from ..knowledge.lease_heartbeat import LeaseHeartbeat
from ..knowledge.lifecycle import generation_for_inputs
from ..knowledge.openie_runtime import GuardedOpenIE, resolve_openie_profile
from ..knowledge.prose_preparation import PlainProseInputs, prepare_plain_prose, prose_configuration
from ..knowledge.raw_artifacts import RawArtifact
from ..knowledge.staged_prose import _seal, _write_batch, _write_batches
from ..store.generation_counts import generation_counts
from .accepted_inputs import CaptureLimits, capture_raw_inputs
from .chunker import MIN_CHUNK_CHARS
from .prepared_chunks import prepare_prose_chunks
from .provenance import read_plain_provenance
from .readers import TextBudget

# Logical canonical payload admission, not database pages, indexes or WAL.
# Reserve job, event, seal, source/epoch updates and their bounded JSON framing;
# unbounded caller/source strings are additionally counted in the envelope.
BOOTSTRAP_BUDGET_VERSION = "plain-bootstrap-budget-v1"
BOOTSTRAP_LIFECYCLE_RECORDS = 12
BOOTSTRAP_LIFECYCLE_BYTES = 16 * 1024


class BuildCancelled(RuntimeError):
    """Cancellation reached a cooperative checkpoint before commit admission."""


class BuildBusy(ValueError):
    """Another invocation owns the live source build or changed its head."""


@dataclass(frozen=True)
class PlainBuildOptions:
    chunk_size_chars: int = 1500
    chunk_overlap_chars: int = 200
    synonymy_threshold: float = 0.8
    allow_empty: bool = False
    capture_limits: CaptureLimits = field(
        default_factory=lambda: CaptureLimits(8_000_000, 16_000_000, 128, 1_000_000)
    )
    max_decoded_chars: int = 2_000_000
    max_chunks: int = 1000
    max_bootstrap_rows: int = 50_000
    max_bootstrap_bytes: int = 64 * 1024 * 1024
    batch_size: int = 128
    workers: int = 2
    lease_duration_seconds: float = 300.0
    renewal_interval_seconds: float = 30.0

    def __post_init__(self):
        for name in (
            "chunk_size_chars",
            "max_decoded_chars",
            "max_chunks",
            "max_bootstrap_rows",
            "max_bootstrap_bytes",
            "batch_size",
            "workers",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError("Build limits must be positive integers")
        if (
            type(self.chunk_overlap_chars) is not int
            or self.chunk_overlap_chars < 0
            or type(self.allow_empty) is not bool
            or type(self.capture_limits) is not CaptureLimits
        ):
            raise ValueError("Invalid captured prose options")
        if (
            type(self.synonymy_threshold) not in (int, float)
            or not math.isfinite(self.synonymy_threshold)
            or not 0 <= self.synonymy_threshold <= 1
        ):
            raise ValueError("Invalid synonym threshold")
        for value in (self.lease_duration_seconds, self.renewal_interval_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Build lease intervals must be finite and positive")
        if self.renewal_interval_seconds >= self.lease_duration_seconds / 2:
            raise ValueError("Build renewal must precede lease expiry")


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


def _credentials(job):
    return dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)


def _authority_fields(guard):
    return dict(
        expected_authorization_epoch=guard.expected_authorization_epoch,
        expected_suppression_epoch=guard.expected_suppression_epoch,
    )


class _Run:
    def __init__(self, ctx, actor, source_id, options, should_stop, on_progress):
        self.store, self.actor, self.options = ctx.store, actor, options
        self.should_stop, self.on_progress = should_stop, on_progress
        self.guard = capture_build_authority(
            self.store, source_id=source_id, actor=actor, clock=self.store._now
        )
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
            raise BuildCancelled("Plain source build cancelled")

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
                        self.generation.id, **_credentials(self.job), states=("staging", "ready")
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
                            self.generation.id, **_credentials(self.job), states=("staging", "ready")
                        )
                        expiry = max(
                            self.store._now() + timedelta(seconds=self.options.lease_duration_seconds),
                            current.lease_expires_at
                            + timedelta(seconds=self.options.renewal_interval_seconds),
                        )
                        self.store.renew_generation_build(
                            self.job.id,
                            **{
                                key: value for key, value in _credentials(self.job).items() if key != "job_id"
                            },
                            lease_expires_at=expiry,
                        )
                        self.guard.check_local()
        except BuildCancelled:
            raise  # Cancellation is the caller's own decision, not a lost lease.
        except BaseException as error:
            failure = AuthorizationChanged("Plain build lease renewal failed")
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


def _pair(store, artifact, revision):
    existing_artifact = store._knowledge_get("Artifact", artifact.id)
    if existing_artifact is not None:
        artifact = existing_artifact
    existing_revision = store._knowledge_get("ArtifactRevision", revision.id)
    if existing_revision is not None:
        if (
            existing_revision.artifact_id,
            existing_revision.content_hash,
            existing_revision.provider_revision,
            existing_revision.raw_uri,
        ) != (revision.artifact_id, revision.content_hash, revision.provider_revision, revision.raw_uri):
            raise ValueError("Accepted revision identity conflicts with stored input")
        revision = existing_revision
    return artifact, revision


def _accepted_pairs(run, captured):
    control, now, store = run.guard.source_control, run.store._now(), run.store
    policy = k.AccessPolicy(
        workspace_id=control.workspace_id,
        origin="local_curated",
        scope_key=f"source:{control.source_id}:plain-prose-v1",
        mode="workspace",
        verified_at=now,
    )
    existing = store._knowledge_get("AccessPolicy", policy.id)
    if existing is not None:
        policy = existing
    pairs = []
    for raw in captured.inputs:
        artifact = k.Artifact(
            workspace_id=control.workspace_id,
            source_id=control.source_id,
            kind="file",
            external_id=raw.logical_path,
            canonical_uri=f"source:{control.source_id}/{raw.logical_path}",
            policy_id=policy.id,
        )
        revision = k.ArtifactRevision(
            artifact_id=artifact.id,
            provider_revision=raw.provider_revision,
            content_hash=raw.raw_hash,
            raw_uri=raw.raw_uri,
            observed_at=now,
            lifecycle="active",
        )
        pairs.append(_pair(store, artifact, revision))
    manifest = k.Artifact(
        workspace_id=control.workspace_id,
        source_id=control.source_id,
        kind="manifest",
        external_id=MANIFEST_EXTERNAL_ID,
        canonical_uri=f"source:{control.source_id}/{MANIFEST_EXTERNAL_ID}",
        policy_id=policy.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=manifest.id,
        content_hash=captured.manifest.sha256,
        raw_uri=captured.manifest.uri,
        observed_at=now,
        lifecycle="active",
        metadata_json=canonical_json({"accepted_manifest_v1": json.loads(captured.manifest_bytes)}),
    )
    pairs.append(_pair(store, manifest, revision))
    used = {a.policy_id for a, _ in pairs}
    planned = (policy,) if existing is None and policy.id in used else ()
    return AcceptedBuildInputs(pairs=tuple(pairs), planned_policies=planned)


def _configuration(embedding, extractor, options):
    size = max(MIN_CHUNK_CHARS, options.chunk_size_chars)
    overlap = min(options.chunk_overlap_chars, size // 3)
    return prose_configuration(
        embedding, extractor, synonymy_threshold=options.synonymy_threshold, allow_empty=options.allow_empty
    ) | {
        "input_pipeline": {
            "version": "plain-source-v1",
            "reader": "plain-utf8-sig-v1",
            "materializer": MATERIALIZER_VERSION,
            "chunker": "mapped-prose-v1",
            "chunk_size_chars": size,
            "chunk_overlap_chars": overlap,
            "title": "logical-path",
            "max_decoded_chars": options.max_decoded_chars,
            "max_chunks": options.max_chunks,
            "all_excluded": "reject",
        }
    }


def _generation(run, accepted, config, profile):
    gen = generation_for_inputs(
        accepted.pairs,
        workspace_id=run.guard.source_control.workspace_id,
        source_id=run.guard.source_control.source_id,
        parent_id=run.guard.source_control.active_generation_id,
        parser_version="mapped-prose-v1",
        linker_version=MATERIALIZER_VERSION,
        embedding_profile=profile.fingerprint,
        configuration=config,
        created_at=run.store._now(),
    )
    existing = run.store._knowledge_get("Generation", gen.id)
    return gen.replace(created_at=existing.created_at) if existing is not None else gen


def _receipt(store, gen, captured, outcome, job=None):
    events = [
        e for e in store._knowledge_rows("IndexEvent") if e.generation_id == gen.id and e.kind == "published"
    ]
    if len(events) != 1:
        raise ValueError("Published generation lacks a unique receipt")
    if job is not None and (
        json.loads(events[0].payload_json) != _credentials(job)
        or job.expected_parent_id != gen.parent_id
        or events[0].aggregate_id != gen.source_id
    ):
        raise ValueError("Publication receipt differs from original build credentials")
    return BuildReceipt(gen.source_id, gen.id, events[0].id, captured.manifest.sha256, outcome)


def _operation_generation(store, gen, operation_id):
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


def _prior_receipt(run, gen, captured, operation_id):
    active = run.guard.source_control.active_generation_id
    with run.store.transaction():
        run.store._lock_source(gen.source_id)
        run.guard.check_local()
        operation = _operation_generation(run.store, gen, operation_id)
        if operation is not None and operation[0].status in {"active", "retired"}:
            old, job = operation
            if job.status != "completed" or embedding_mode(old) != "verified_v1":
                raise ValueError("Source operation lacks a verified publication")
            run.store.validate_generation_seal(old.id)
            validate_generation_profile(run.store, old)
            result = _receipt(run.store, old, captured, "already_published", job)
            run.guard.check_local()
            return result
        if not active:
            return None
        old = run.store._generation(active)
        if old.manifest_hash != gen.manifest_hash or embedding_mode(old) != "verified_v1":
            return None
        run.store.validate_generation_seal(old.id)
        validate_generation_profile(run.store, old)
        result = _receipt(run.store, old, captured, "already_current")
        run.guard.check_local()
        return result


def _materialize(run, captured, accepted, gen, config, raw_store, embedding, extractor):
    run.progress("reading")
    budget = TextBudget(limit=run.options.max_decoded_chars)
    documents, bindings = [], []
    by_path = {a.external_id: (a, r) for a, r in accepted.pairs if a.kind == "file"}
    for raw in captured.inputs:
        run.check()
        data = raw_store.read_bytes(RawArtifact(raw.raw_uri, raw.raw_hash, raw.byte_length))
        run.check()
        read = read_plain_provenance(raw, data, name=raw.logical_path, path=raw.logical_path, budget=budget)
        if read.outcome == "binary" or any(doc.is_code for doc in read.documents):
            raise ValueError("Only plain prose originals are supported")
        documents.extend(read.documents)
        bindings.append(AcceptedArtifactBinding(raw, *by_path[raw.logical_path]))
    config_chunk = config["input_pipeline"]
    chunks = prepare_prose_chunks(
        tuple(documents),
        size_chars=config_chunk["chunk_size_chars"],
        overlap_chars=config_chunk["chunk_overlap_chars"],
    )
    if len(chunks) > run.options.max_chunks:
        raise ValueError("Plain source exceeds complete chunk budget")
    evidence = materialize_chunk_evidence(
        chunks, gen, workspace_id=run.guard.source_control.workspace_id, bindings=tuple(bindings)
    )
    manifest_revision = next(r for a, r in accepted.pairs if a.kind == "manifest")
    evidence = replace(
        evidence,
        revision_members=(
            *evidence.revision_members,
            k.GenerationMember(generation_id=gen.id, artifact_revision_id=manifest_revision.id),
        ),
    )
    exact = replace(accepted, spans=evidence.spans)
    run.adopt(run.guard.bind_inputs(exact))
    return PlainProseInputs(
        gen, evidence, accepted.pairs, canonical_json(config), embedding, extractor
    ), exact


def _install(run, inputs, accepted, operation_id):
    """Callback-free; caller owns source/auth lock and admits intentional setup changes."""
    store, gen = run.store, inputs.generation
    run.guard.check_local()
    _operation_generation(store, gen, operation_id)
    original = run.guard.source_control
    source = store.get_source(gen.source_id)
    previous = store._knowledge_get("MaintenanceJob", source.get("active_build_id"))
    if previous is not None and previous.status == "running" and previous.lease_expires_at > store._now():
        raise BuildBusy("Source already has a live build holder")
    # Recover this source's expired attempt even when replacement inputs create
    # a different generation. Other sources' jobs are outside our authority.
    store.recover_generation_builds(source_id=gen.source_id)
    expected_epoch = run.guard.expected_authorization_epoch + int(not store.source_is_managed(gen.source_id))
    for policy in accepted.planned_policies:
        if store._knowledge_get("AccessPolicy", policy.id) is None:
            expected_epoch += 1
            store.put_knowledge(policy)
    if store._knowledge_get("Generation", gen.id) is None:
        store.put_knowledge(gen)
    store.begin_managed_source(gen.source_id)
    job = store.claim_generation_build(
        gen.id,
        job_key=operation_id,
        lease_owner=run.owner,
        lease_expires_at=store._now() + timedelta(seconds=run.options.lease_duration_seconds),
    )
    with store.generation_write(gen.id, **_credentials(job)):
        for artifact, revision in accepted.pairs:
            store.put_knowledge(artifact)
            store.put_knowledge(revision)
        for member in inputs.evidence.revision_members:
            store.put_knowledge(member)
    manifest_revision = next(r for a, r in accepted.pairs if a.kind == "manifest")
    store.bind_generation_embedding_profile(gen.id, manifest_revision.id, **_credentials(job))
    if store.authorization_epoch() != expected_epoch:
        raise AuthorizationChanged("Setup changed authorization beyond its explicit local grants")
    fresh = capture_build_authority(
        store,
        source_id=gen.source_id,
        actor=run.actor,
        accepted=replace(accepted, planned_policies=()),
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


def _source_presentation(meta, chunks, documents):
    """The published source row shape; the bootstrap envelope bounds these same fields."""
    return (
        dict(status="ready", stage="ready", progress_done=chunks, progress_total=chunks, error=None),
        dict(meta or {}) | {"chunks": chunks, "documents": documents},
    )


def _bootstrap_envelope(run, operation_id):
    source = {
        key: value
        for key, value in run.store.get_source(run.guard.source_control.source_id).items()
        if key != "generation_lock"
    }
    fields, meta = _source_presentation(
        source.get("meta"), run.options.max_chunks, run.options.capture_limits.max_inputs
    )
    source.update(fields)
    source["meta"] = meta
    identities = {
        "source": run.guard.source_control.source_id,
        "workspace": run.guard.source_control.workspace_id,
        "operation": operation_id,
    }
    return source, BOOTSTRAP_LIFECYCLE_BYTES + BOOTSTRAP_LIFECYCLE_RECORDS * len(
        canonical_json(identities).encode()
    )


def _bootstrap_bounds(run, prepared, accepted, operation_id):
    """Conservative record/payload admission; no store mutation or external I/O."""
    options = run.options
    source, size = _bootstrap_envelope(run, operation_id)
    count = BOOTSTRAP_LIFECYCLE_RECORDS
    records = chain(
        (source, prepared.inputs.generation),
        accepted.planned_policies,
        (record for pair in prepared.inputs.artifacts_and_revisions for record in pair),
        prepared.inputs.evidence.revision_members,
        (
            record
            for batch in _write_batches(prepared, batch_size=options.batch_size)
            for record in batch
            if record is not None
        ),
    )
    for record in records:
        payload = (
            record
            if type(record) is dict
            else (record.native_row() if hasattr(record, "native_row") else record.model_dump(mode="json"))
        )
        count += 1
        size += len(canonical_json(payload).encode())
        if count > options.max_bootstrap_rows or size > options.max_bootstrap_bytes:
            raise ValueError("Prepared bootstrap exceeds atomic transaction budget")
    return count, size


def _publish(run, inputs, accepted, captured):
    store, gen, guard = run.store, inputs.generation, run.guard
    guard.check_local()
    event = store.publish_staged_generation(
        gen.id,
        expected_parent_id=gen.parent_id,
        **_credentials(run.job),
        expected_suppression_epoch=guard.expected_suppression_epoch,
        published_at=store._now(),
    )
    if (store.authorization_epoch(), store.suppression_epoch()) != (
        guard.expected_authorization_epoch,
        guard.expected_suppression_epoch,
    ):
        raise AuthorizationChanged("Authority changed during publication")
    counts = generation_counts(store, gen.id)
    source = store.get_source(gen.source_id)
    fields, meta = _source_presentation(
        source.get("meta"), counts.passages, sum(a.kind == "file" for a, _ in accepted.pairs)
    )
    store.update_source(gen.source_id, **fields, meta_json=canonical_json(meta))
    fresh = capture_build_authority(
        store,
        source_id=gen.source_id,
        actor=run.actor,
        accepted=replace(accepted, planned_policies=()),
        clock=store._now,
    )
    if fresh.source_control != replace(guard.source_control, active_generation_id=gen.id) or (
        fresh.expected_authorization_epoch,
        fresh.expected_suppression_epoch,
    ) != (guard.expected_authorization_epoch, guard.expected_suppression_epoch):
        fresh.close()
        raise AuthorizationChanged("Publication changed unrelated authority")
    return BuildReceipt(gen.source_id, gen.id, event, captured.manifest.sha256, "published"), fresh


def build_plain_source(
    ctx,
    *,
    source_id,
    actor,
    inputs,
    options,
    raw_store,
    embedding_spec,
    operation_id,
    should_stop,
    on_progress=None,
    embedding_cache: EmbeddingCache | None = None,
):
    if (
        type(actor) is not BuildActor
        or type(options) is not PlainBuildOptions
        or type(embedding_spec) is not EmbeddingSpec
        or type(inputs) is not tuple
    ):
        raise ValueError("Explicit immutable plain build inputs/options required")
    if (
        type(operation_id) is not str
        or not operation_id
        or len(operation_id) > 256
        or not callable(should_stop)
        or on_progress is not None
        and not callable(on_progress)
    ):
        raise ValueError("Stable operation identity and live cancellation required")
    if getattr(ctx.store, "_transaction_depth", 0) or getattr(ctx.store, "_transaction", None) is not None:
        raise ValueError("Coordinator requires no ambient transaction")
    run = _Run(ctx, actor, source_id, options, should_stop, on_progress)
    installed = False
    try:
        bootstrap = not run.guard.source_control.managed
        if not bootstrap and run.guard.source_control.active_generation_id is None:
            raise ValueError("Managed source needs explicit recovery before initial publication")
        if bootstrap:
            source, envelope_size = _bootstrap_envelope(run, operation_id)
            if envelope_size + len(canonical_json(source).encode()) > options.max_bootstrap_bytes:
                raise ValueError("Source metadata exceeds atomic bootstrap budget")
        run.start()
        run.progress("capture")
        resolved = resolve_embedding_profile(ctx.ollama, spec=embedding_spec, authorization_check=run.check)
        resolved_chat = resolve_openie_profile(ctx.ollama, authorization_check=run.check)
        embedding = validate_profile_descriptor(resolved.descriptor())
        config = _configuration(embedding, resolved_chat.profile, options)
        captured = capture_raw_inputs(
            raw_store,
            source_id=source_id,
            workspace_id=run.guard.source_control.workspace_id,
            inputs=tuple(sorted(inputs, key=lambda item: item.logical_path)),
            configuration=config,
            limits=options.capture_limits,
            should_stop=lambda: (run.check(), False)[1],
        )
        if captured.outcome == "all_excluded":
            raise ValueError("All-excluded inventory cannot publish a source")
        accepted = _accepted_pairs(run, captured)
        run.adopt(run.guard.bind_inputs(accepted))
        gen = _generation(run, accepted, config, embedding)
        if current := _prior_receipt(run, gen, captured, operation_id):
            run.pause()
            run.check()
            return current
        value, accepted = _materialize(
            run, captured, accepted, gen, config, raw_store, embedding, resolved_chat.profile
        )
        run.generation = gen
        if not bootstrap:
            run.pause()
            run.check()
            with run.store.transaction():
                run.store._lock_source(source_id)
                job, fresh = _install(run, value, accepted, operation_id)
            run.job = job
            run.adopt(fresh)
            installed = True
            run.start()
        embeddings = ProfiledEmbeddings(
            ctx.ollama, resolved, cache=embedding_cache, authorization_check=run.check
        )
        chat = GuardedOpenIE(ctx.ollama, resolved_chat, authorization_check=run.check)
        prepared = prepare_plain_prose(
            value,
            embeddings=embeddings,
            chat=chat,
            check=run.check,
            workers=options.workers,
            on_progress=lambda done, total: run.progress("extract", done, total),
        )
        if bootstrap:
            _bootstrap_bounds(run, prepared, accepted, operation_id)
        else:
            authority = _credentials(run.job) | _authority_fields(run.guard)
            for batch in _write_batches(prepared, batch_size=options.batch_size):
                run.check()
                _write_batch(run.store, prepared, batch, **authority)
                run.check()
            run.check()
            _seal(run.store, prepared, **authority)
            run.check()
        embeddings.validate()
        chat.validate()
        run.pause()
        run.check()
        with run.store.transaction():
            run.store._lock_source(source_id)
            run.guard.check_local()
            if bootstrap:
                job, fresh = _install(run, value, accepted, operation_id)
                run.job = job
                run.adopt(fresh)
                for batch in _write_batches(prepared, batch_size=options.batch_size):
                    _write_batch(
                        run.store, prepared, batch, **_credentials(job), **_authority_fields(run.guard)
                    )
                _seal(run.store, prepared, **_credentials(job), **_authority_fields(run.guard))
            receipt, final_guard = _publish(run, value, accepted, captured)
        run.receipt = receipt
        run.job = None
        run.adopt(final_guard)
        run.guard.check()
        return receipt
    except BaseException as error:
        try:
            run.pause()
        except BaseException:
            pass
        if installed and run.job is not None and run.receipt is None:
            try:
                ctx.store.fail_generation_build(
                    run.generation.id,
                    **_credentials(run.job),
                    error_code="build_cancelled" if isinstance(error, BuildCancelled) else "build_failed",
                )
            except (ValueError, AuthorizationChanged):
                pass  # A lost fence or committed publication is owned by recovery/receipt.
        raise
    finally:
        run.close()
