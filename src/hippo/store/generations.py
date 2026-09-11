"""Durable generation leases, exact manifests, and atomic source publication."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime

from ..knowledge import model as k
from ..knowledge.identity import canonical_json, text_hash
from .authorization import bump_epoch, epoch

MANDATORY_REPRESENTATIONS = ("evidence", "dense", "native")


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

    def _generation(self, generation_id):
        row = self._knowledge_get("Generation", generation_id)
        if row is None:
            raise ValueError("Unknown generation")
        return row

    def claim_generation_build(self, generation_id, *, job_key, lease_owner, lease_expires_at):
        with self.transaction():
            gen = self._generation(generation_id)
            self._lock_source(gen.source_id)
            gen = self._generation(generation_id)
            now = self._now()
            if gen.status not in ("staging", "failed") or lease_expires_at <= now:
                raise ValueError("Build requires staging or unpublished failed generation and future lease")
            if gen.status == "failed" and (
                gen.published_at is not None
                or any(
                    event.generation_id == gen.id and event.kind == "published"
                    for event in self._knowledge_rows("IndexEvent")
                )
            ):
                raise ValueError("Published generations cannot reopen for retry")
            source = self.get_source(gen.source_id)
            previous = self._knowledge_get("MaintenanceJob", source.get("active_build_id"))
            if previous is not None and previous.status == "running" and previous.lease_expires_at > now:
                if (
                    previous.input_fingerprint == generation_id
                    and previous.job_key == job_key
                    and previous.lease_owner == lease_owner
                ):
                    return previous
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
            if gen.status == "failed":
                # The new source fence is held while removing this never-published
                # attempt's rows. Shared raw/evidence identities remain reusable.
                result = self._collect_generation(gen.id)
                if result.blocked_reason is not None:
                    raise ValueError("Failed generation retry is still referenced")
                self._write_knowledge(gen.replace(status="staging"))
            return job

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

    def _assert_generation_writable(self, generation_id, *, legacy_fixture=False):
        gen = self._generation(generation_id)
        jobs = [
            j
            for j in self._knowledge_rows("MaintenanceJob")
            if j.kind == "rebuild" and j.input_fingerprint == generation_id
        ]
        strict = any(
            m.generation_id == generation_id
            and set(m.required_representations) == set(MANDATORY_REPRESENTATIONS)
            for m in self._knowledge_rows("IndexManifest")
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

    def _check_knowledge_write(self, record, existing=None):
        from .authorization import RECORD_EPOCHS

        if (
            isinstance(record, k.MaintenanceJob)
            and record.kind == "rebuild"
            and self._knowledge_get("Generation", record.input_fingerprint) is not None
        ):
            raise ValueError("Generation build leases require controlled lifecycle operations")
        if RECORD_EPOCHS[type(record).__name__] == "content" and not isinstance(record, k.Generation):
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
            record, (k.GenerationMember, k.GenerationEvidenceMember, k.NativeBinding, k.IndexManifest)
        ):
            self._assert_generation_writable(
                record.generation_id, legacy_fixture=not isinstance(record, k.GenerationEvidenceMember)
            )
        if isinstance(record, k.GenerationEvidenceMember):
            selected = {
                r.artifact_revision_id
                for r in self._knowledge_rows("GenerationMember")
                if r.generation_id == record.generation_id
            }
            target = self._knowledge_get(record.record_kind, record.record_id)
            if not self._record_revisions(target) <= selected:
                raise ValueError("Evidence member is outside generation revisions")
        if isinstance(record, k.NativeBinding):
            gen = self._generation(record.generation_id)
            native = self._knowledge_get(record.native_kind, record.native_id)
            if native.get("generation_id") is not None or any(
                j.input_fingerprint == gen.id and j.kind == "rebuild"
                for j in self._knowledge_rows("MaintenanceJob")
            ):
                revisions = {
                    m.artifact_revision_id
                    for m in self._knowledge_rows("GenerationMember")
                    if m.generation_id == gen.id
                }
                selected = {
                    (m.record_kind, m.record_id)
                    for m in self._knowledge_rows("GenerationEvidenceMember")
                    if m.generation_id == gen.id
                }
                span = self._knowledge_get("EvidenceSpan", record.span_id)
                if (
                    native.get("generation_id") != gen.id
                    or span.revision_id not in revisions
                    or ("EvidenceSpan", span.id) not in selected
                ):
                    raise ValueError("Binding native or evidence is outside generation closure")
        frozen = [
            m
            for m in self._knowledge_rows("GenerationEvidenceMember")
            if self._generation(m.generation_id).status != "staging"
        ]
        if existing is not None and any(
            m.record_kind == type(record).__name__ and m.record_id == record.id for m in frozen
        ):
            raise ValueError("Published interpretation is immutable")
        if isinstance(record, k.AssertionSupport) and any(
            m.record_kind == "AssertionVersion" and m.record_id == record.assertion_version_id for m in frozen
        ):
            raise ValueError("Sealed assertion proof group cannot gain support")

    def _native_rows(self, kind):
        if self.knowledge_backend == "fake":
            return list(
                getattr(
                    self,
                    {
                        "Passage": "passages",
                        "Symbol": "symbols",
                        "DataObject": "data_objects",
                        "Commit": "commits",
                        "Entity": "entities",
                        "Fact": "facts",
                    }[kind],
                ).values()
            )
        rows = self.run(f"MATCH (n:{kind}) RETURN n AS n")
        result = []
        for row in rows:
            native = dict(row["n"])
            native = {key: value for key, value in native.items() if not key.startswith("_")}
            if kind == "Passage":
                owner = self.run_one(
                    "MATCH (n:Passage {id:$id})-[:FROM]->(s:Source) RETURN s.id AS id", id=native["id"]
                )
                native["source_id"] = owner["id"] if owner else None
            result.append(native)
        return result

    def _native_relationships(self, ids):
        specs = {
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
        edges = []
        for rel, (attr, left, right) in specs.items():
            if self.knowledge_backend == "fake":
                if attr is None:
                    field = "subject_id" if rel == "SUBJECT" else "object_id"
                    edges.extend([rel, row["id"], row[field], {}] for row in self.facts.values())
                    continue
                values = getattr(self, attr)
                for key in values:
                    a, b = key[:2]
                    payload = values[key] if isinstance(values, dict) else {}
                    edges.append([rel, a, b, payload])
            else:
                for a_kind in left:
                    for b_kind in right:
                        if rel == "CODE_EDGE" and (a_kind, b_kind) == ("DataObject", "Symbol"):
                            continue
                        relation_payload = "properties(r)" if self.knowledge_backend == "neo4j" else "r"
                        for row in self.run(
                            f"MATCH (a:{a_kind})-[r:{rel}]->(b:{b_kind}) RETURN a.id AS a,b.id AS b,{relation_payload} AS r"
                        ):
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
        shared = {row["id"]: dict(row) for kind in ("Entity", "Fact") for row in self._native_rows(kind)}
        reachable = set(ids)
        reachable.update(
            endpoint
            for _, a, b, _ in edges
            if a in ids or b in ids
            for endpoint in (a, b)
            if endpoint in shared
        )
        for relationships in ({"MENTIONS", "STATES"}, {"SUBJECT", "OBJECT"}):
            reachable.update(b for rel, a, b, _ in edges if rel in relationships and a in reachable)
        result = []
        for rel, a, b, payload in edges:
            selected = (a in ids or b in ids) or ({a, b} <= reachable)
            if not selected:
                continue
            if any(endpoint not in ids and endpoint not in shared for endpoint in (a, b)):
                raise ValueError("Native relationship crosses generations")
            result.append([rel, a, b, payload])
        for rid in sorted(reachable - set(ids)):
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
        gen = self._generation(generation_id)
        members = [m for m in self._knowledge_rows("GenerationMember") if m.generation_id == generation_id]
        exact = [
            m for m in self._knowledge_rows("GenerationEvidenceMember") if m.generation_id == generation_id
        ]
        bindings = [b for b in self._knowledge_rows("NativeBinding") if b.generation_id == generation_id]
        evidence = {}

        def visit(record):
            key = (type(record).__name__, record.id)
            if key in evidence or key[0] in ("Artifact", "AccessPolicy", "Generation", "Source", "Workspace"):
                return
            evidence[key] = record.model_dump(mode="json")
            for kind, rid in self._references(record):
                if kind in k.RECORD_TYPES:
                    target = self._knowledge_get(kind, rid)
                    if target is None:
                        raise ValueError("Missing immutable generation input")
                    visit(target)

        for record in [*members, *exact, *bindings]:
            visit(record)
        dense = [r for r in self._native_rows("Passage") if r.get("generation_id") == generation_id]
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
            for r in self._native_rows(kind)
            if r.get("generation_id") == generation_id
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
            observations = [
                self._knowledge_get("ObjectObservation", m.record_id)
                for m in exact
                if m.record_kind == "ObjectObservation"
            ]
            if not any(o.object_id == binding.object_id for o in observations):
                raise ValueError("Native binding object lacks a selected observation")
        dimensions = set()
        for row in dense:
            self._validate_managed_native("Passage", row, gen)
            if ("EvidenceSpan", row["span_id"]) not in exact_ids:
                raise ValueError("Passage span missing from exact manifest")
            dimensions.add(len(row["embedding"]))
        for kind, row in native:
            self._validate_managed_native(kind, row, gen)
            if not any(b.native_kind == kind and b.native_id == row["id"] for b in bindings):
                raise ValueError("Native row lacks evidence binding")
            if row.get("embedding"):
                dimensions.add(len(row["embedding"]))
        if len(dimensions) > 1:
            raise ValueError("Inconsistent vector dimensions")
        ids = {r["id"] for r in dense} | {r["id"] for _, r in native}
        representations = {
            "evidence": sorted(evidence.values(), key=canonical_json),
            "dense": sorted([self._canonical_native("Passage", r) for r in dense], key=canonical_json),
            "native": [
                *sorted([[kind, self._canonical_native(kind, r)] for kind, r in native], key=canonical_json),
                *self._native_relationships(ids),
            ],
        }
        return tuple(
            k.RepresentationChecksum(
                kind=kind, checksum=text_hash(canonical_json(rows)), row_count=len(rows), ready=True
            )
            for kind, rows in representations.items()
        )

    def _verify_manifest(self, gen, manifest):
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
            manifests = [m for m in self._knowledge_rows("IndexManifest") if m.generation_id == gen.id]
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
        manifests = [m for m in self._knowledge_rows("IndexManifest") if m.generation_id == generation_id]
        if gen.status not in ("ready", "active", "retired") or len(manifests) != 1:
            raise ValueError("Generation requires a strict rebuild")
        self._verify_manifest(gen, manifests[0])
        return manifests[0]

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
        fault_hook=None,
    ):
        with self.transaction():
            gen = self._generation(generation_id)
            self._lock_source(gen.source_id)
            receipt = [
                e
                for e in self._knowledge_rows("IndexEvent")
                if e.generation_id == generation_id and e.kind == "published"
            ]
            origin = dict(job_id=job_id, fencing_token=fencing_token, lease_owner=lease_owner)
            if receipt:
                if (
                    len(receipt) == 1
                    and json.loads(receipt[0].payload_json) == origin
                    and gen.parent_id == expected_parent_id
                ):
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
            for member in self._knowledge_rows("GenerationMember"):
                if member.generation_id == gen.id:
                    revision = self._knowledge_get("ArtifactRevision", member.artifact_revision_id)
                    artifact = self._knowledge_get("Artifact", revision.artifact_id)
                    if artifact.deleted_at is not None:
                        raise ValueError("Generation includes tombstoned artifact")
                    reachable |= {
                        ("revision", revision.id),
                        ("artifact", artifact.id),
                        ("policy", artifact.policy_id),
                    }
            for member in self._knowledge_rows("GenerationEvidenceMember"):
                if member.generation_id == gen.id:
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

    def publish_generation(self, generation_id, *, expected_parent_id, published_at, fault_hook=None):
        """Trusted fixture compatibility primitive; production uses strict publication."""
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
                e
                for e in self._knowledge_rows("IndexEvent")
                if e.generation_id == gen.id and e.kind == "published"
            ]
            if len(events) != 1:
                raise ValueError("Active generation lacks a unique publication event")
            return events[0].id
        if active != expected_parent_id:
            raise ValueError("Generation publication compare-and-swap failed")
        manifests = [m for m in self._knowledge_rows("IndexManifest") if m.generation_id == gen.id]
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

    def _validate_managed_native(self, kind, row, gen):
        if row.get("source_id") != gen.source_id or row.get("generation_id") != gen.id:
            raise ValueError("Native row source or generation differs")
        if kind == "Passage":
            span = self._knowledge_get("EvidenceSpan", row.get("span_id"))
            revision = self._knowledge_get("ArtifactRevision", row.get("artifact_revision_id"))
            selected = {
                m.artifact_revision_id
                for m in self._knowledge_rows("GenerationMember")
                if m.generation_id == gen.id
            }
            if (
                span is None
                or revision is None
                or revision.id not in selected
                or span.revision_id != revision.id
                or row.get("embedding_profile") != gen.embedding_profile
                or row.get("text") != span.text
            ):
                raise ValueError("Passage revision/span/profile/original text binding differs")
            from ..knowledge.lifecycle import generation_passage_id

            if row.get("id") != generation_passage_id(gen.id, revision.id, span.id, row.get("ordinal", 0)):
                raise ValueError("Passage ID does not match generation binding")
            if not row.get("embedding"):
                raise ValueError("Dense passage requires a vector")
            parent = row.get("parent_passage_id")
            if parent:
                parent_row = next((r for r in self._native_rows("Passage") if r["id"] == parent), None)
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
                existing = {row["id"]: row for row in store._native_rows(kind)}
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
                    gen = store._generation(generation_id)
                    store._validate_managed_native(kind, row, gen)
                    if gen.status == "staging":
                        store._assert_generation_writable(generation_id)
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
                    store._assert_generation_writable(generation_id)
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
        with store.transaction():
            store._lock_authorization()
            natives = {
                row["id"]: row
                for kind in ("Passage", "Symbol", "DataObject", "Commit", "Entity", "Fact")
                for row in store._native_rows(kind)
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
