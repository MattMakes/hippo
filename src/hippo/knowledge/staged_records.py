"""Fenced writes, resume probing and exact sealing for a generation of plain records.

The third staged writer, and the first that belongs to no lane. `staged_prose` requires the
native code inventory to be *empty* and `staged_code` requires it to be exactly the code
graph; a connector generation has no native inventory at all beyond its passages, and it
carries records neither lane ever wrote -- units, assertions, versions and support.

Nothing here is copied from `staged_code`. Its fenced core, its ceiling, its resume plan and
its immutable-native comparison are imported under the public names review finding m10 asked
for, so a change to the fence is a change to one implementation rather than three.

What is new is the group order. A `Unit` names its `Passage` and an `AssertionVersion` names
its `Unit` (S1 D18, RS1-5), so passages come before their units and assertions come last --
which is why `_write_batch` writes a batch in order rather than bucketing it by type.

No callback, model call or filesystem access happens inside a transaction, and the public
wrapper refuses an ambient one. This module imports nothing from `hippo.connectors`: it
knows about records, not about providers.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from . import model as k
from .identity import canonical_json, text_hash
from .staged_code import (
    CLEANUP,
    PAYLOAD_CEILING_BYTES,
    DependencyGroup,
    ResumePlan,
    fenced_local,
    immutable_native,
)

__all__ = [
    "CLEANUP",
    "PAYLOAD_CEILING_BYTES",
    "RecordBundle",
    "ResumePlan",
    "StagedPassage",
    "probe_staged_records",
    "write_staged_records",
]

# The native kinds a connector generation must not hold. A rendered fact is a passage and a
# unit, never a `Symbol`: the code graph belongs to the code lane (plan section 7.1).
FORBIDDEN_NATIVE_KINDS = ("Symbol", "DataObject", "Commit")


def _vector(values):
    result = tuple(float(value) for value in values)
    if any(value != value or value in (float("inf"), float("-inf")) for value in result):
        raise ValueError("A prepared vector must be finite")
    return result


@dataclass(frozen=True, slots=True)
class StagedPassage:
    """One bound passage row plus the vector the runtime produced.

    The row is the passage without its embedding, so the vector is carried once and the
    comparison the resume probe makes sees exactly what the store would hold.
    """

    row: Mapping[str, object]
    embedding: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.row, Mapping) or "embedding" in self.row:
            raise ValueError("A staged passage carries its native row without an embedding")
        object.__setattr__(self, "row", dict(self.row))
        for name in ("id", "generation_id", "span_id"):
            if type(self.row.get(name)) is not str or not self.row[name]:
                raise ValueError("A staged passage row names its id, generation and span")
        object.__setattr__(self, "embedding", _vector(self.embedding))
        if not self.embedding:
            raise ValueError("A dense passage requires a vector")

    @property
    def id(self) -> str:
        return self.row["id"]

    def native_row(self) -> dict:
        return {**self.row, "embedding": list(self.embedding)}


# ------------------------------------------------------------------ the bundle


def _typed(values, kind, label):
    result = tuple(values)
    if any(type(item) is not kind for item in result):
        raise ValueError(f"{label} must be an immutable tuple of {kind.__name__}")
    return result


@dataclass(frozen=True, slots=True)
class RecordBundle:
    """One connector generation's complete write plan, closed over its own references.

    Every check here is pure: no store, no clock, no model. A bundle that reaches the writer
    has already been proved internally consistent, so a refusal inside a transaction is about
    what the store holds rather than about what the caller built.
    """

    generation: k.Generation
    configuration_json: str
    accepted_pairs: tuple[tuple[k.Artifact, k.ArtifactRevision], ...]
    manifest_revision: k.ArtifactRevision
    revision_members: tuple[k.GenerationMember, ...]
    spans: tuple[k.EvidenceSpan, ...]
    objects: tuple[k.KnowledgeObject, ...]
    observations: tuple[k.ObjectObservation, ...]
    views: tuple[k.RetrievalView, ...]
    derived_records: tuple[k.DerivedRecord, ...]
    derived_dependencies: tuple[k.DerivedDependency, ...]
    passages: tuple[StagedPassage, ...]
    units: tuple[k.Unit, ...]
    assertions: tuple[k.Assertion, ...]
    versions: tuple[k.AssertionVersion, ...]
    supports: tuple[k.AssertionSupport, ...]
    evidence_members: tuple[k.GenerationEvidenceMember, ...]

    def __post_init__(self) -> None:
        if type(self.generation) is not k.Generation or type(self.configuration_json) is not str:
            raise ValueError("A record bundle takes one generation and its canonical configuration")
        for name, kind in (
            ("revision_members", k.GenerationMember),
            ("spans", k.EvidenceSpan),
            ("objects", k.KnowledgeObject),
            ("observations", k.ObjectObservation),
            ("views", k.RetrievalView),
            ("derived_records", k.DerivedRecord),
            ("derived_dependencies", k.DerivedDependency),
            ("passages", StagedPassage),
            ("units", k.Unit),
            ("assertions", k.Assertion),
            ("versions", k.AssertionVersion),
            ("supports", k.AssertionSupport),
            ("evidence_members", k.GenerationEvidenceMember),
        ):
            object.__setattr__(self, name, _typed(getattr(self, name), kind, f"Bundle {name}"))
        object.__setattr__(self, "accepted_pairs", tuple(self.accepted_pairs))
        self._closed()
        self._references()

    @property
    def scoped(self) -> tuple:
        """Every record this generation's exact evidence membership names, in group order."""
        return (
            *self.spans,
            *self.observations,
            *self.derived_records,
            *self.derived_dependencies,
            *self.views,
            *self.units,
            *self.versions,
            *self.supports,
        )

    def _closed(self) -> None:
        gen_id = self.generation.id
        wanted = {(type(record).__name__, record.id) for record in self.scoped}
        held = {(member.record_kind, member.record_id) for member in self.evidence_members}
        if (
            len(wanted) != len(self.scoped)
            or len(held) != len(self.evidence_members)
            or wanted != held
            or any(member.generation_id != gen_id for member in self.evidence_members)
            or any(member.generation_id != gen_id for member in self.revision_members)
        ):
            raise ValueError("Record bundle membership differs from its generation-scoped records")

    def _references(self) -> None:
        known = {
            "KnowledgeObject": {item.id for item in self.objects},
            "EvidenceSpan": {span.id for span in self.spans},
            "Assertion": {item.id for item in self.assertions},
            "AssertionVersion": {item.id for item in self.versions},
            "Unit": {unit.id for unit in self.units},
            "DerivedRecord": {item.id for item in self.derived_records},
            "Passage": {item.id for item in self.passages},
        }

        def present(kind, *identities):
            for identity in identities:
                if identity is not None and identity not in known[kind]:
                    raise ValueError(f"Record bundle references a missing {kind}")

        for row in self.observations:
            present("KnowledgeObject", row.object_id)
            present("EvidenceSpan", row.span_id)
        for item in self.assertions:
            present("KnowledgeObject", item.subject_id, item.object_id)
        for version in self.versions:
            present("Assertion", version.assertion_id)
            present("Unit", version.unit_id)
        for support in self.supports:
            present("AssertionVersion", support.assertion_version_id)
            present("EvidenceSpan", support.span_id)
        for unit in self.units:
            present("Passage", unit.passage_id)
            present("EvidenceSpan", unit.span_id)
        for view in self.views:
            present("EvidenceSpan", view.span_id)
            present("DerivedRecord", view.derived_record_id)
        for edge in self.derived_dependencies:
            present("DerivedRecord", edge.derived_record_id)
        revisions = {member.artifact_revision_id for member in self.revision_members}
        if any(span.revision_id not in revisions for span in self.spans):
            raise ValueError("Record bundle span is outside its revision members")
        if any(item.row.get("generation_id") != self.generation.id for item in self.passages):
            raise ValueError("Record bundle passage belongs to another generation")


# ------------------------------------------------------------------ the accepted preflight


def _accepted(store, bundle):
    from .generation_profiles import embedding_mode, validate_generation_profile

    generation = store._generation(bundle.generation.id)
    if embedding_mode(generation) != "verified_v1":
        raise ValueError("Staged record writer requires a controlled verified profile binding")
    bound = validate_generation_profile(store, generation)
    if (bound.profile.fingerprint, bound.config_fingerprint) != (
        bundle.generation.embedding_profile,
        text_hash(bundle.configuration_json),
    ):
        raise ValueError("Bound profile/configuration differs from prepared inputs")
    for artifact, revision in bundle.accepted_pairs:
        for record in (artifact, revision):
            if store._knowledge_get(type(record).__name__, record.id) != record:
                raise ValueError("Persisted accepted artifact/revision inventory differs")


# ------------------------------------------------------------------ batch planning


def _groups(bundle):
    """Every dependency group, in the plan's order. Pure and deterministic.

    Accepted preflight, revision members, spans, objects with their observations, derived
    records with their dependencies and views, passages with their units, and assertions with
    their versions and support. Two orderings are forced rather than chosen:

    * an observation cites a span, so objects follow spans, as they do in `staged_code`;
    * a `Unit` names its `Passage` and an `AssertionVersion` names its `Unit`, so a passage
      travels with its own units and assertions come last (S1 section 10).

    A `KnowledgeObject` and an `Assertion` are workspace-scoped, not generation-scoped: they
    carry no member of their own, so they travel as `shared` payloads that the probe compares
    without ever mistaking them for this generation's rows.
    """
    gen_id = bundle.generation.id

    def selected(record):
        return (
            record,
            k.GenerationEvidenceMember(
                generation_id=gen_id, record_kind=type(record).__name__, record_id=record.id
            ),
        )

    def exact(record):
        return ("exact", (type(record).__name__, record.id), record)

    yield DependencyGroup((None,))  # Accepted inventory preflight, before any mutation.
    for member in bundle.revision_members:
        yield DependencyGroup((member,), (("member", member.id, member),))
    observations = {}
    for row in bundle.observations:
        observations.setdefault(row.object_id, []).append(row)
    for span in bundle.spans:
        yield DependencyGroup(selected(span), (exact(span),))
    for item in bundle.objects:
        rows = observations.get(item.id, [])
        records = [item]
        for row in rows:
            records.extend(selected(row))
        yield DependencyGroup(tuple(records), tuple(exact(row) for row in rows), (("KnowledgeObject", item),))
    dependencies = {}
    for edge in bundle.derived_dependencies:
        dependencies.setdefault(edge.derived_record_id, []).append(edge)
    views = {}
    for view in bundle.views:
        views.setdefault(view.derived_record_id, []).append(view)
    for derived in bundle.derived_records:
        records = list(selected(derived))
        for edge in dependencies.get(derived.id, []):
            records.extend(selected(edge))
        for view in views.get(derived.id, []):
            records.extend(selected(view))
        yield DependencyGroup(tuple(records), tuple(exact(record) for record in records[::2]))
    units = {}
    for unit in bundle.units:
        units.setdefault(unit.passage_id, []).append(unit)
    for item in bundle.passages:
        rows = units.get(item.id, [])
        records = [item]
        for unit in rows:
            records.extend(selected(unit))
        yield DependencyGroup(
            tuple(records),
            (
                ("native", ("Passage", item.id), item.native_row()),
                *(("unit", unit.id, unit) for unit in rows),
                *(exact(unit) for unit in rows),
            ),
        )
    versions = {}
    for version in bundle.versions:
        versions.setdefault(version.assertion_id, []).append(version)
    supports = {}
    for support in bundle.supports:
        supports.setdefault(support.assertion_version_id, []).append(support)
    for assertion in bundle.assertions:
        records, probes = [assertion], []
        for version in versions.get(assertion.id, []):
            records.extend(selected(version))
            probes.append(exact(version))
            for support in supports.get(version.id, []):
                records.extend(selected(support))
                probes.append(exact(support))
        yield DependencyGroup(tuple(records), tuple(probes), (("Assertion", assertion),))


def _payload(record):
    if record is None:
        return None
    if type(record) is StagedPassage:
        return record.native_row()
    return record.model_dump(mode="json")


def _write_batches(bundle, *, batch_size, resume=None):
    """Yield complete dependency groups; no store, callback or model is retained."""
    if type(bundle) is not RecordBundle or type(batch_size) is not int or batch_size < 1:
        raise ValueError("Expected an immutable record bundle and a positive batch size")
    skipped = ()
    if resume is not None:
        if type(resume) is not ResumePlan or resume.generation_id != bundle.generation.id:
            raise ValueError("A resume plan belongs to the generation it was probed against")
        skipped = resume.skipped
    batch, count, index = [], 0, 0
    for group in _groups(bundle):
        if index in skipped:
            index += 1
            continue
        index += 1
        batch.extend(group.records)
        count += 1
        if count == batch_size:
            yield tuple(batch)
            batch, count = [], 0
    if resume is not None and index != resume.group_count:
        raise ValueError("A resume plan belongs to the bundle it was probed against")
    if batch:
        yield tuple(batch)


def _check_ceiling(batch):
    """Refuse an oversized batch before its transaction opens (plan section 8.3)."""
    size = len(canonical_json([_payload(record) for record in batch]).encode("utf-8"))
    if size > PAYLOAD_CEILING_BYTES:
        raise ValueError(
            f"Staged record batch payload is {size} bytes; the ceiling is {PAYLOAD_CEILING_BYTES}"
        )


def _write_batch(store, bundle, batch, **authority):
    """Callback-free local core; safe under an existing outer transaction.

    Written strictly in group order rather than bucketed by type, because the store's own
    guards depend on that order: `put_knowledge` refuses a `Unit` whose `Passage` row is not
    yet there, and an `AssertionVersion` whose `Unit` is not (`store/generations.py:700`,
    `store/knowledge.py:75`).
    """
    _check_ceiling(batch)
    with fenced_local(store, bundle, **authority):
        for record in batch:
            if record is None:
                _accepted(store, bundle)
            elif type(record) is StagedPassage:
                row = record.native_row()
                immutable_native(store, "Passage", [row])
                store.add_passages([row])
            else:
                store.put_knowledge(record)


# ------------------------------------------------------------------ resume probe


def _persisted(store, bundle):
    """Every generation-scoped row the store already holds, one scoped read per kind.

    `Unit` is read by generation as well as through its member (RS1-4). A unit written
    without its member would otherwise be invisible to the probe: the `exact` flavour finds
    only what a `GenerationEvidenceMember` already points at.
    """
    gen_id = bundle.generation.id
    return {
        "member": {row.id: row for row in store._knowledge_rows("GenerationMember", generation_id=gen_id)},
        "unit": {row.id: row for row in store._knowledge_rows("Unit", generation_id=gen_id)},
        "exact": {
            (row.record_kind, row.record_id): row
            for row in store._knowledge_rows("GenerationEvidenceMember", generation_id=gen_id)
        },
        "native": {
            ("Passage", row["id"]): row for row in store._native_rows("Passage", generation_id=gen_id)
        },
    }


def probe_staged_records(store, bundle) -> ResumePlan:
    """Decide, per dependency group, whether a reclaimed generation already holds it.

    Three outcomes and nothing else, exactly as `staged_code.probe_staged_rows` decides them.
    SKIP when every row of the group is present and equal to what this attempt would write.
    WRITE when none of them is present. FAIL CLOSED -- a `ValueError` naming the explicit
    failed-generation cleanup path -- when a group is partially present, when a present
    payload differs, or when the store holds any generation-scoped row this attempt would not
    produce.
    """
    if type(bundle) is not RecordBundle:
        raise ValueError("A resume probe takes an immutable record bundle")
    persisted = _persisted(store, bundle)
    groups = list(_groups(bundle))
    expected = {flavour: set() for flavour in persisted}
    for group in groups:
        for flavour, key, _ in group.probes:
            expected[flavour].add(key)
    for flavour, actual in persisted.items():
        extra = set(actual) - expected[flavour]
        if extra:
            raise ValueError(
                f"The staged generation holds {len(extra)} {flavour} rows this build would not "
                f"produce; {CLEANUP} required"
            )
    skipped = set()
    for index, group in enumerate(groups):
        if not group.probes:
            continue  # The accepted preflight is a read, never a write, and never skipped.
        present = []
        for flavour, key, record in group.probes:
            stored = persisted[flavour].get(key)
            if stored is None:
                present.append(False)
                continue
            if flavour == "native":
                if store._canonical_native("Passage", stored) != store._canonical_native("Passage", record):
                    raise ValueError(f"A staged Passage row differs from this build; {CLEANUP} required")
            elif flavour in ("member", "unit") and stored != record:
                raise ValueError(f"A staged {flavour} record differs from this build; {CLEANUP} required")
            present.append(True)
        if not any(present):
            continue
        if not all(present):
            raise ValueError(f"A staged dependency group is incomplete; {CLEANUP} required")
        for flavour, key, record in group.probes:
            if flavour == "exact" and store._knowledge_get(key[0], key[1]) != record:
                raise ValueError(f"A staged {key[0]} payload differs from this build; {CLEANUP} required")
        for kind, record in group.shared:
            if store._knowledge_get(kind, record.id) != record:
                raise ValueError(f"A staged {kind} payload differs from this build; {CLEANUP} required")
        skipped.add(index)
    return ResumePlan(bundle.generation.id, len(groups), frozenset(skipped))


# ------------------------------------------------------------------ inventory and seal


def _inventory(store, bundle):
    """Exact membership, exact units, exact passages, and no native code inventory at all."""
    _accepted(store, bundle)
    gen_id = bundle.generation.id

    def selected(kind):
        return {r.id: r for r in store._knowledge_rows(kind, generation_id=gen_id)}

    for kind, expected in (
        ("GenerationMember", bundle.revision_members),
        ("GenerationEvidenceMember", bundle.evidence_members),
        ("Unit", bundle.units),
    ):
        if selected(kind) != {r.id: r for r in expected}:
            raise ValueError(f"Exact {kind} inventory differs from prepared coverage")
    for record in (*bundle.objects, *bundle.assertions, *bundle.scoped):
        if store._knowledge_get(type(record).__name__, record.id) != record:
            raise ValueError("Persisted evidence payload differs from prepared inventory")
    expected_dense = {
        item.id: store._canonical_native("Passage", item.native_row()) for item in bundle.passages
    }
    actual_dense = {
        row["id"]: store._canonical_native("Passage", row)
        for row in store._native_rows("Passage", generation_id=gen_id)
    }
    if actual_dense != expected_dense:
        raise ValueError("Dense passage inventory differs from prepared coverage")
    if (
        selected("NativeBinding")
        or selected("ProseExtraction")
        or any(store._native_rows(kind, generation_id=gen_id) for kind in FORBIDDEN_NATIVE_KINDS)
        or store._native_relationships(ids=set(expected_dense))
    ):
        raise ValueError("A connector generation holds no native code, binding or extraction")


def _seal(store, bundle, **authority):
    """Compare and seal inside one local transaction; never invoke callbacks."""
    with fenced_local(store, bundle, **authority):
        _inventory(store, bundle)
        manifest = k.IndexManifest(
            generation_id=bundle.generation.id,
            profile_fingerprint=bundle.generation.embedding_profile,
            config_fingerprint=text_hash(bundle.configuration_json),
            required_representations=("evidence", "dense", "native"),
            checksums=store.generation_checksums(bundle.generation.id),
            ready=True,
        )
        store.seal_generation(
            bundle.generation.id,
            manifest,
            **{key: authority[key] for key in ("job_id", "lease_owner", "fencing_token")},
        )
        return manifest


def write_staged_records(
    store,
    bundle: RecordBundle,
    *,
    job_id: str,
    lease_owner: str,
    fencing_token: int,
    expected_authorization_epoch: int,
    expected_suppression_epoch: int,
    check: Callable[[], None],
    batch_size: int = 128,
    resume: ResumePlan | None = None,
) -> k.IndexManifest:
    """Write/seal one record generation outside ambient transactions; caller publishes."""
    if store.in_ambient_transaction():
        raise ValueError("Staged record wrapper requires no outer transaction")
    if type(bundle) is not RecordBundle or not callable(check):
        raise ValueError("A record bundle and a live build check are required")
    authority = dict(
        job_id=job_id,
        lease_owner=lease_owner,
        fencing_token=fencing_token,
        expected_authorization_epoch=expected_authorization_epoch,
        expected_suppression_epoch=expected_suppression_epoch,
    )
    for batch in _write_batches(bundle, batch_size=batch_size, resume=resume):
        check()
        _write_batch(store, bundle, batch, **authority)
        check()
    check()
    manifest = _seal(store, bundle, **authority)
    check()
    return manifest
