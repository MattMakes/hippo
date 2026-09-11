"""Exact derived provenance validation. These helpers never grant audience access."""

import json
from dataclasses import dataclass, fields

from .identity import canonical_json, text_hash


@dataclass(frozen=True)
class DerivationClosure:
    span_ids: frozenset[str] = frozenset()
    revision_ids: frozenset[str] = frozenset()
    derived_record_ids: frozenset[str] = frozenset()
    dependency_ids: frozenset[str] = frozenset()
    view_ids: frozenset[str] = frozenset()
    binding_ids: frozenset[str] = frozenset()
    support_passage_ids: frozenset[str] = frozenset()

    def union(self, other):
        return DerivationClosure(
            **{f.name: getattr(self, f.name) | getattr(other, f.name) for f in fields(self)}
        )


def dependency_version(record) -> str:
    return text_hash(canonical_json(record.model_dump(mode="json")))


def _dependencies(values):
    return sorted(set(tuple(value) for value in values))


def view_fingerprint(
    *, view_kind, text, text_profile, vector_profile, rule_version, model_version, dependencies
):
    return text_hash(
        canonical_json(
            [
                "retrieval-view-v1",
                view_kind,
                text_hash(text),
                text_profile,
                vector_profile,
                rule_version,
                model_version,
                _dependencies(dependencies),
            ]
        )
    )


def prose_fingerprint(
    *,
    rule_version,
    model_version,
    dependencies,
    input_kind,
    input_id,
    input_text_hash,
    support_passage_ids,
    extractor_profile,
    embedding_profile,
    payload_hash,
):
    return text_hash(
        canonical_json(
            [
                "prose-extraction-v1",
                rule_version,
                model_version,
                _dependencies(dependencies),
                input_kind,
                input_id,
                input_text_hash,
                sorted(set(support_passage_ids)),
                extractor_profile,
                embedding_profile,
                payload_hash,
            ]
        )
    )


def derived_capability(generation) -> bool:
    """Explicit storage-owned boundary; legacy view metadata is not rendered evidence."""
    coverage = json.loads(generation.coverage_json)
    if not isinstance(coverage, dict) or "derived_evidence_version" not in coverage:
        return False
    if type(coverage["derived_evidence_version"]) is not int or coverage["derived_evidence_version"] != 1:
        raise ValueError("Unsupported derived evidence capability")
    return True


def validate_generation_derivations(store, generation_id):
    """Validate every selected view and complete child group, including unbound ones."""
    inventory = _Inventory(store, generation_id)
    for kind, identity in sorted(inventory.exact):
        if kind == "DerivedRecord":
            inventory.derivation(identity)
        elif kind == "RetrievalView":
            inventory.view(inventory.record(kind, identity))


class _Inventory:
    def __init__(self, store, generation_id):
        self.store = store
        self.gen = store._generation(generation_id)
        if not derived_capability(self.gen):
            raise ValueError("Generation has no derived evidence capability")
        self.source = store.get_source(self.gen.source_id)
        if self.gen.status == "failed" or self.source is None:
            raise ValueError("Derived generation is unavailable")
        self.exact = {
            (m.record_kind, m.record_id)
            for m in store._knowledge_rows("GenerationEvidenceMember")
            if m.generation_id == generation_id
        }
        self.revisions = {
            m.artifact_revision_id
            for m in store._knowledge_rows("GenerationMember")
            if m.generation_id == generation_id
        }
        self.visiting = set()

    def record(self, kind, identity, *, exact=True):
        result = self.store._knowledge_get(kind, identity)
        if result is None or (exact and (kind, identity) not in self.exact):
            raise ValueError("Derived input missing from exact generation membership")
        return result

    def span(self, identity):
        span = self.record("EvidenceSpan", identity)
        revision = self.record("ArtifactRevision", span.revision_id, exact=False)
        artifact = self.record("Artifact", revision.artifact_id, exact=False)
        if (
            revision.id not in self.revisions
            or artifact.source_id != self.gen.source_id
            or artifact.workspace_id != self.source["workspace_id"]
        ):
            raise ValueError("Derived original input crosses generation/source/workspace")
        return DerivationClosure(span_ids=frozenset({span.id}), revision_ids=frozenset({revision.id}))

    def derivation(self, identity):
        derived = self.record("DerivedRecord", identity)
        if derived.state != "ready" or derived.workspace_id != self.source["workspace_id"]:
            raise ValueError("Derived input requires ready workspace provenance")
        dependencies = [
            d for d in self.store._knowledge_rows("DerivedDependency") if d.derived_record_id == identity
        ]
        closure = DerivationClosure(derived_record_ids=frozenset({identity}))
        tuples = []
        declared_revisions = set()
        for dep in dependencies:
            self.record("DerivedDependency", dep.id)
            if dep.input_kind not in {"revision", "span", "binding"}:
                raise ValueError("Unsupported or cyclic derivation input")
            kind = {"revision": "ArtifactRevision", "span": "EvidenceSpan", "binding": "NativeBinding"}[
                dep.input_kind
            ]
            target = self.record(kind, dep.input_id, exact=kind == "EvidenceSpan")
            if dependency_version(target) != dep.input_version:
                raise ValueError("Derived input version differs")
            tuples.append((dep.input_kind, dep.input_id, dep.input_version))
            closure = closure.union(DerivationClosure(dependency_ids=frozenset({dep.id})))
            if dep.input_kind == "span":
                closure = closure.union(self.span(dep.input_id))
            elif dep.input_kind == "revision":
                declared_revisions.add(dep.input_id)
            else:
                native = self.store._knowledge_get(target.native_kind, target.native_id)
                if (
                    target.generation_id != self.gen.id
                    or native is None
                    or native.get("generation_id") != self.gen.id
                    or native.get("source_id") != self.gen.source_id
                ):
                    raise ValueError("Derived binding crosses generations")
                observations = [
                    self.record(kind, rid) for kind, rid in self.exact if kind == "ObjectObservation"
                ]
                if not any(
                    o.object_id == target.object_id and o.span_id == target.span_id for o in observations
                ):
                    raise ValueError("Derived binding has no exact observation")
                closure = closure.union(self.span(target.span_id)).union(
                    DerivationClosure(binding_ids=frozenset({target.id}))
                )
        if (
            not closure.span_ids
            or not declared_revisions <= closure.revision_ids
            or set(derived.input_revision_ids) != closure.revision_ids
            or set(derived.input_binding_ids) != closure.binding_ids
        ):
            raise ValueError("Derived original inventory differs from complete dependencies")
        return derived, tuples, closure

    def view(self, view):
        if view.id in self.visiting:
            raise ValueError("Cyclic retrieval view")
        self.visiting.add(view.id)
        try:
            if self.record("RetrievalView", view.id) != view or view.derived_record_id is None:
                raise ValueError("Rendered view requires immutable derivation")
            derived, dependencies, closure = self.derivation(view.derived_record_id)
            span = self.record("EvidenceSpan", view.span_id)
            if (
                view.span_id not in closure.span_ids
                or view.source_revision_id != span.revision_id
                or view.derivation_version != derived.rule_version
                or view.view_kind != derived.view_kind
                or (view.vector_profile is not None and view.vector_profile != self.gen.embedding_profile)
            ):
                raise ValueError("View anchor/profile/derivation differs")
            fingerprint = view_fingerprint(
                view_kind=view.view_kind,
                text=view.text,
                text_profile=view.text_profile,
                vector_profile=view.vector_profile,
                rule_version=derived.rule_version,
                model_version=derived.model_version,
                dependencies=dependencies,
            )
            if fingerprint != view.dependency_fingerprint or fingerprint != derived.dependency_fingerprint:
                raise ValueError("Rendered view fingerprint differs")
            return closure.union(DerivationClosure(view_ids=frozenset({view.id})))
        finally:
            self.visiting.remove(view.id)

    def passage(self, identity):
        row = self.store._knowledge_get("Passage", identity)
        if (
            row is None
            or row.get("generation_id") != self.gen.id
            or row.get("source_id") != self.gen.source_id
        ):
            raise ValueError("Prose support passage crosses generation/source")
        self.store._validate_managed_native("Passage", row, self.gen)
        closure = self.span(row["span_id"])
        if row.get("retrieval_view_id"):
            closure = closure.union(self.view(self.record("RetrievalView", row["retrieval_view_id"])))
        return closure.union(DerivationClosure(support_passage_ids=frozenset({identity})))


def validate_view(store, generation_id, view) -> DerivationClosure:
    """Require complete exact lineage; caller must separately authorize every input."""
    return _Inventory(store, generation_id).view(view)


def validate_prose(store, generation_id, extraction, *, require_member=True) -> DerivationClosure:
    """Validate persisted output or, for the fenced writer, a candidate before membership."""
    inventory = _Inventory(store, generation_id)
    if (
        extraction.generation_id != generation_id
        or extraction.embedding_profile != inventory.gen.embedding_profile
    ):
        raise ValueError("Prose extraction generation/profile differs")
    if require_member and inventory.record("ProseExtraction", extraction.id) != extraction:
        raise ValueError("Prose extraction payload differs")
    derived, dependencies, closure = inventory.derivation(extraction.derived_record_id)
    if derived.view_kind != "projection":
        raise ValueError("Prose requires projection derivation")
    if extraction.input_kind == "span":
        original = inventory.record("EvidenceSpan", extraction.input_id)
        inputs = inventory.span(original.id)
    else:
        original = inventory.record("RetrievalView", extraction.input_id)
        inputs = inventory.view(original)
    if extraction.input_text_hash != text_hash(original.text) or closure.span_ids != inputs.span_ids:
        raise ValueError("Prose inference input differs from original lineage")
    fingerprint = prose_fingerprint(
        rule_version=derived.rule_version,
        model_version=derived.model_version,
        dependencies=dependencies,
        input_kind=extraction.input_kind,
        input_id=extraction.input_id,
        input_text_hash=extraction.input_text_hash,
        support_passage_ids=extraction.support_passage_ids,
        extractor_profile=extraction.extractor_profile,
        embedding_profile=extraction.embedding_profile,
        payload_hash=extraction.payload_hash,
    )
    if fingerprint != derived.dependency_fingerprint:
        raise ValueError("Prose derivation fingerprint differs")
    closure = closure.union(inputs)
    for identity in extraction.support_passage_ids:
        support = inventory.passage(identity)
        if not inputs.span_ids <= support.span_ids:
            raise ValueError("Prose support does not cover extraction originals")
        closure = closure.union(support)
    return closure
