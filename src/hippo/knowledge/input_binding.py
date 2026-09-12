"""Pure materialization of verified plain-file preparation into exact evidence.

No raw I/O or persistence happens here. The accepted reader verified raw bytes;
this boundary verifies their explicit artifact/revision metadata and preparation
identities. Native rows are fresh adapters and deliberately contain no vectors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..ingest.prepared_chunks import PreparedChunk
from ..ingest.provenance import RawInput
from . import model as k
from .derivations import dependency_version, view_fingerprint
from .identity import canonical_json, make_identity, normalize_relative_path, text_hash
from .lifecycle import generation_passage_id

MATERIALIZER_VERSION = "plain-prose-materializer-v1"


def local_input_key(*, workspace_id: str, source_id: str, logical_path: str) -> str:
    if any(not isinstance(value, str) or not value.strip() for value in (workspace_id, source_id)):
        raise ValueError("Local input identity needs an explicit source and workspace")
    return make_identity("raw_input", [workspace_id, source_id, normalize_relative_path(logical_path)])


@dataclass(frozen=True, slots=True)
class AcceptedArtifactBinding:
    raw_input: RawInput
    artifact: k.Artifact
    revision: k.ArtifactRevision

    def __post_init__(self):
        if (
            type(self.raw_input) is not RawInput
            or type(self.artifact) is not k.Artifact
            or type(self.revision) is not k.ArtifactRevision
        ):
            raise ValueError("Accepted bindings require exact immutable raw/artifact/revision types")
        raw, artifact, revision = self.raw_input, self.artifact, self.revision
        if artifact.kind != "file" or artifact.connector_id is not None or raw.container_chain:
            raise ValueError("Only plain local files without container mappings are supported")
        if artifact.deleted_at is not None or revision.lifecycle != "active":
            raise ValueError("Accepted local input must be an active immutable revision")
        if (
            artifact.external_id != raw.logical_path
            or artifact.canonical_uri != f"source:{artifact.source_id}/{raw.logical_path}"
            or raw.input_key
            != local_input_key(
                workspace_id=artifact.workspace_id,
                source_id=artifact.source_id,
                logical_path=raw.logical_path,
            )
        ):
            raise ValueError("Accepted input identity/path differs from its local artifact")
        if (revision.artifact_id, revision.content_hash, revision.raw_uri, revision.provider_revision) != (
            artifact.id,
            raw.raw_hash,
            raw.raw_uri,
            raw.provider_revision,
        ):
            raise ValueError("Accepted raw hash/URI/provider revision differs from its artifact revision")


@dataclass(frozen=True, slots=True)
class BoundPassage:
    chunk: PreparedChunk
    generation: k.Generation
    span: k.EvidenceSpan
    view: k.RetrievalView | None

    def __post_init__(self):
        if (
            type(self.chunk) is not PreparedChunk
            or type(self.generation) is not k.Generation
            or type(self.span) is not k.EvidenceSpan
            or (self.view is not None and type(self.view) is not k.RetrievalView)
        ):
            raise ValueError("Passage bindings require exact immutable preparation and evidence types")
        if self.generation.status != "staging" or len(self.chunk.original_units) != 1:
            raise ValueError("Bound passages require one plain original unit and a staging generation")
        if self.view is None:
            if self.chunk.requires_view or self.chunk.text != self.span.text:
                raise ValueError("Original-only passage differs from its complete original")
        elif (self.view.span_id, self.view.source_revision_id, self.view.text, self.view.vector_profile) != (
            self.span.id,
            self.span.revision_id,
            self.chunk.text,
            self.generation.embedding_profile,
        ):
            raise ValueError("Rendered passage differs from its exact view binding")

    @property
    def id(self) -> str:
        return generation_passage_id(
            self.generation.id,
            self.span.revision_id,
            self.span.id,
            self.chunk.ordinal,
            retrieval_view_id=self.retrieval_view_id,
        )

    @property
    def retrieval_view_id(self) -> str | None:
        return self.view.id if self.view is not None else None

    def to_chunk(self):
        return self.chunk.to_chunk()

    def native_row(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.generation.source_id,
            "generation_id": self.generation.id,
            "artifact_revision_id": self.span.revision_id,
            "span_id": self.span.id,
            "retrieval_view_id": self.retrieval_view_id,
            "embedding_profile": self.generation.embedding_profile,
            "ordinal": self.chunk.ordinal,
            "title": self.chunk.title,
            "text": self.chunk.text,
        }


def _ids(values) -> tuple[str, ...]:
    result = tuple(values)
    if (
        not result
        or any(not isinstance(value, str) or not value for value in result)
        or len(set(result)) != len(result)
    ):
        raise ValueError("Evidence references require unique nonempty immutable IDs")
    return result


@dataclass(frozen=True, slots=True)
class ExtractionInput:
    chunk_key: str
    input_kind: Literal["span", "view"]
    input_id: str
    input_version: str
    input_text_hash: str
    text: str
    original_span_ids: tuple[str, ...]
    support_passage_ids: tuple[str, ...]

    def __post_init__(self):
        if (
            any(
                not isinstance(value, str) or not value
                for value in (self.chunk_key, self.input_id, self.input_version, self.input_text_hash)
            )
            or not isinstance(self.text, str)
            or self.input_kind not in ("span", "view")
        ):
            raise ValueError("Extraction inputs require immutable typed identities and text")
        object.__setattr__(self, "original_span_ids", _ids(self.original_span_ids))
        object.__setattr__(self, "support_passage_ids", _ids(self.support_passage_ids))
        if self.input_text_hash != text_hash(self.text):
            raise ValueError("Extraction input hash differs from its exact text")


@dataclass(frozen=True, slots=True)
class PreparedEvidence:
    generation_id: str
    workspace_id: str
    spans: tuple[k.EvidenceSpan, ...]
    views: tuple[k.RetrievalView, ...]
    derived_records: tuple[k.DerivedRecord, ...]
    derived_dependencies: tuple[k.DerivedDependency, ...]
    revision_members: tuple[k.GenerationMember, ...]
    evidence_members: tuple[k.GenerationEvidenceMember, ...]
    passages: tuple[BoundPassage, ...]
    extraction_inputs: tuple[ExtractionInput, ...]

    def __post_init__(self):
        for name, expected in (
            ("spans", k.EvidenceSpan),
            ("views", k.RetrievalView),
            ("derived_records", k.DerivedRecord),
            ("derived_dependencies", k.DerivedDependency),
            ("revision_members", k.GenerationMember),
            ("evidence_members", k.GenerationEvidenceMember),
            ("passages", BoundPassage),
            ("extraction_inputs", ExtractionInput),
        ):
            values = tuple(getattr(self, name))
            if any(type(value) is not expected for value in values):
                raise ValueError("Prepared evidence requires exact immutable record types")
            object.__setattr__(self, name, values)
        if any(not isinstance(value, str) or not value for value in (self.generation_id, self.workspace_id)):
            raise ValueError("Prepared evidence requires an explicit immutable scope")
        if any(
            member.generation_id != self.generation_id
            for member in (*self.revision_members, *self.evidence_members)
        ):
            raise ValueError("Prepared membership crosses generations")
        revisions = {member.artifact_revision_id for member in self.revision_members}
        if len(revisions) != len(self.revision_members) or any(
            span.revision_id not in revisions for span in self.spans
        ):
            raise ValueError("Prepared revision membership must uniquely cover every original span")
        expected = {(type(record).__name__, record.id) for record in self.records}
        actual = {(member.record_kind, member.record_id) for member in self.evidence_members}
        if (
            expected != actual
            or len(actual) != len(self.evidence_members)
            or len(expected) != len(self.records)
        ):
            raise ValueError("Prepared exact membership differs from its immutable evidence inventory")
        if any(record.workspace_id != self.workspace_id for record in self.derived_records):
            raise ValueError("Prepared derivation crosses workspaces")
        if len(self.passages) != len(self.extraction_inputs):
            raise ValueError("Every plain prose passage requires an explicit extraction input")
        for identities in (
            [passage.id for passage in self.passages],
            [passage.chunk.chunk_key for passage in self.passages],
            [passage.chunk.ordinal for passage in self.passages],
        ):
            if len(set(identities)) != len(identities):
                raise ValueError("Prepared passages require unique IDs, chunk keys and ordinals")
        spans_by_id = {span.id: span for span in self.spans}
        views_by_id = {view.id: view for view in self.views}
        generation = self.passages[0].generation if self.passages else None
        expected_spans, expected_views, expected_derived, expected_dependencies = {}, {}, {}, {}
        for passage, extraction in zip(self.passages, self.extraction_inputs, strict=True):
            original = passage.view or passage.span
            if (
                passage.generation.id != self.generation_id
                or passage.generation != generation
                or spans_by_id.get(passage.span.id) != passage.span
                or (passage.view is not None and views_by_id.get(passage.view.id) != passage.view)
            ):
                raise ValueError("Prepared passage crosses its exact generation evidence")
            if (
                extraction.chunk_key,
                extraction.input_id,
                extraction.input_version,
                extraction.text,
                extraction.support_passage_ids,
            ) != (
                passage.chunk.chunk_key,
                original.id,
                dependency_version(original),
                passage.chunk.text,
                (passage.id,),
            ) or extraction.input_kind != ("view" if passage.view is not None else "span"):
                raise ValueError("Prepared extraction differs from its passage input/support binding")
            originals = tuple(
                k.EvidenceSpan(
                    revision_id=passage.span.revision_id,
                    locator_kind="file_lines",
                    locator_json=canonical_json(item.lines.locator.model_dump(mode="json")),
                    text=item.lines.text,
                    policy_id=passage.span.policy_id,
                )
                for item in passage.chunk.originals
            )
            if extraction.original_span_ids != tuple(span.id for span in originals):
                raise ValueError("Prepared extraction must retain its complete original/title proof")
            expected_spans.update((span.id, span) for span in originals)
            if passage.view is not None:
                view, derived, edges = _view(
                    passage.chunk, passage.generation, self.workspace_id, originals, passage.span
                )
                expected_views[view.id] = view
                expected_derived[derived.id] = derived
                expected_dependencies.update((edge.id, edge) for edge in edges)
        for expected, actual in (
            (expected_spans, self.spans),
            (expected_views, self.views),
            (expected_derived, self.derived_records),
            (expected_dependencies, self.derived_dependencies),
        ):
            if expected != {record.id: record for record in actual}:
                raise ValueError(
                    "Prepared derivation/original inventory differs from its complete input closure"
                )

    @property
    def records(self) -> tuple:
        """Typed evidence records in dependency order, excluding accepted artifacts/revisions."""
        return (*self.spans, *self.derived_records, *self.derived_dependencies, *self.views)


def _view(
    chunk: PreparedChunk,
    generation: k.Generation,
    workspace_id: str,
    spans: tuple[k.EvidenceSpan, ...],
    anchor: k.EvidenceSpan,
):
    dependencies = tuple(("span", span.id, dependency_version(span)) for span in spans)
    profile = make_identity(
        "text_profile",
        [
            MATERIALIZER_VERSION,
            list(chunk.chunker_profile),
            sorted({unit.decoder_profile for unit in chunk.original_units}),
            chunk.chunk_key,
        ],
    )
    fingerprint = view_fingerprint(
        view_kind="projection",
        text=chunk.text,
        text_profile=profile,
        vector_profile=generation.embedding_profile,
        rule_version=MATERIALIZER_VERSION,
        model_version=None,
        dependencies=dependencies,
    )
    derived = k.DerivedRecord(
        workspace_id=workspace_id,
        view_kind="projection",
        rule_version=MATERIALIZER_VERSION,
        input_revision_ids=tuple(sorted({span.revision_id for span in spans})),
        dependency_fingerprint=fingerprint,
        state="ready",
    )
    edges = tuple(
        k.DerivedDependency(
            derived_record_id=derived.id, input_kind=kind, input_id=identity, input_version=version
        )
        for kind, identity, version in dependencies
    )
    view = k.RetrievalView(
        span_id=anchor.id,
        source_revision_id=anchor.revision_id,
        view_kind="projection",
        text=chunk.text,
        text_profile=profile,
        vector_profile=generation.embedding_profile,
        derivation_version=MATERIALIZER_VERSION,
        dependency_fingerprint=fingerprint,
        derived_record_id=derived.id,
    )
    return view, derived, edges


def materialize_chunk_evidence(
    prepared: tuple[PreparedChunk, ...],
    generation: k.Generation,
    *,
    workspace_id: str,
    bindings: tuple[AcceptedArtifactBinding, ...],
) -> PreparedEvidence:
    """Bind verified plain preparations; a successful result is not a publication or grant."""
    if type(generation) is not k.Generation or generation.status != "staging":
        raise ValueError("Materialization requires an immutable staging generation")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ValueError("Materialization requires an explicit workspace")
    accepted = {}
    artifacts, revisions = set(), set()
    for binding in bindings:
        if type(binding) is not AcceptedArtifactBinding:
            raise ValueError("Materialization requires immutable accepted bindings")
        raw, artifact, revision = binding.raw_input, binding.artifact, binding.revision
        if artifact.source_id != generation.source_id or artifact.workspace_id != workspace_id:
            raise ValueError("Accepted input crosses generation source/workspace")
        if raw.input_key in accepted or artifact.id in artifacts or revision.id in revisions:
            raise ValueError("Duplicate or conflicting accepted input/artifact/revision")
        accepted[raw.input_key] = binding
        artifacts.add(artifact.id)
        revisions.add(revision.id)
    spans, views, derived_records, dependencies = {}, {}, {}, {}
    passages, extractions = [], []
    chunk_keys, ordinals = set(), set()
    for chunk in prepared:
        if type(chunk) is not PreparedChunk:
            raise ValueError("Materialization requires exact immutable PreparedChunk values")
        if len(chunk.original_units) != 1:
            raise ValueError("Only plain prose from one original file per chunk is supported")
        if chunk.chunk_key in chunk_keys or chunk.ordinal in ordinals:
            raise ValueError("Duplicate or conflicting prepared chunk identity/ordinal")
        chunk_keys.add(chunk.chunk_key)
        ordinals.add(chunk.ordinal)
        units = {}
        for unit in chunk.original_units:
            binding = accepted.get(unit.input_key)
            if (
                binding is None
                or unit.locator.path != binding.raw_input.logical_path
                or unit.unit_key
                != make_identity(
                    "original_unit", [unit.input_key, binding.raw_input.raw_hash, unit.decoder_profile]
                )
            ):
                raise ValueError("Prepared original unit differs from its accepted raw identity/path")
            if unit.raw_ranges[-1].end != binding.raw_input.byte_length:
                raise ValueError("Prepared decoder map differs from accepted raw byte length")
            units[unit.unit_key] = binding
        chunk_spans = []
        for original in chunk.originals:
            binding = units[original.unit_key]
            span = k.EvidenceSpan(
                revision_id=binding.revision.id,
                locator_kind="file_lines",
                locator_json=canonical_json(original.lines.locator.model_dump(mode="json")),
                text=original.lines.text,
                policy_id=binding.artifact.policy_id,
            )
            spans.setdefault(span.id, span)
            chunk_spans.append(span)
        if not chunk_spans:
            raise ValueError("A prepared passage cannot have an empty original closure")
        anchor = chunk_spans[0]
        view = None
        if chunk.requires_view:
            view, derived, edges = _view(chunk, generation, workspace_id, tuple(chunk_spans), anchor)
            views.setdefault(view.id, view)
            derived_records.setdefault(derived.id, derived)
            for edge in edges:
                dependencies.setdefault(edge.id, edge)
        passage = BoundPassage(chunk, generation, anchor, view)
        passages.append(passage)
        input_record = view or anchor
        extractions.append(
            ExtractionInput(
                chunk.chunk_key,
                "view" if view else "span",
                input_record.id,
                dependency_version(input_record),
                text_hash(input_record.text),
                input_record.text,
                tuple(span.id for span in chunk_spans),
                (passage.id,),
            )
        )
    records = (*spans.values(), *derived_records.values(), *dependencies.values(), *views.values())
    return PreparedEvidence(
        generation.id,
        workspace_id,
        tuple(spans.values()),
        tuple(views.values()),
        tuple(derived_records.values()),
        tuple(dependencies.values()),
        tuple(
            k.GenerationMember(generation_id=generation.id, artifact_revision_id=b.revision.id)
            for b in accepted.values()
        ),
        tuple(
            k.GenerationEvidenceMember(
                generation_id=generation.id, record_kind=type(r).__name__, record_id=r.id
            )
            for r in records
        ),
        tuple(passages),
        tuple(extractions),
    )
