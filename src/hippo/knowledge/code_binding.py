"""Pure materialization of one code generation's captured tree into exact evidence.

No raw I/O, no persistence handle, no model client and no wall clock: the capture
instant is an argument, the captured tree and its mapped passages are arguments, and the
resolved code graph is an argument. Everything here is a function of what it is given,
so replaying the same inputs produces byte-identical records (plan section 6 step 7).

What it produces is the plan's section 4 inventory, minus the commit side. Accepted
artifacts and revisions for the tree, for its accepted manifest and for every captured
file; one `EvidenceSpan` per original line range the passages cite, with real
complete-line locators rather than a synthetic whole-file span; a `RetrievalView` plus
`DerivedRecord` plus `DerivedDependency` closure over those originals for every passage
whose text is not byte-identical to one original region; `KnowledgeObject`s of kind
`repository`, `file`, `symbol` and the data-object schema kinds with their
`ObjectObservation`s; the generation-namespaced native `Symbol`/`DataObject` rows with a
`NativeBinding` each; and the exact `GenerationEvidenceMember` closure over all of it.

Commits are deliberately untouched. Every `commit` passage passes through on
`CodeEvidenceBundle.commit_chunks` in chunk order, unbound: the history slice owns the
`history_event` artifacts and revisions, the commit objects and observations, the commit
views and the `MODIFIES`/`PRECEDES` rows, and no revision exists yet for a commit view
to anchor to. Inventing one here would mint evidence the history pass then has to
reconcile.

Order of operations. Generation identity does not depend on the code graph, but the
graph's native IDs depend on the generation namespace (plan section 6 steps 4 and 7).
So `code_generation` settles identity from the captured tree alone, the caller extracts
and chunks with `lifecycle.generation_namespace(...)` of that generation, and
`materialize_code_evidence` recomputes the identical generation and refuses any native
ID that does not re-derive from it -- the same check the store makes before a write.

Layering. This module sits above `hippo.ingest` and imports nothing from it, so its
inputs are validated structurally -- by the fields this boundary actually reads -- rather
than by class identity. `EXPECTED_CODE_CHUNK_RULE_VERSION` pins the mapped-chunk
derivation this binding was written against; a chunk result carrying any other rule
version is refused rather than bound, so bumping the chunker without bumping this module
fails closed instead of quietly producing a mixed generation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from . import model as k
from .derivations import dependency_version, view_fingerprint
from .identity import (
    canonical_json,
    make_identity,
    normalize_relative_path,
    repository_key,
    symbol_key,
)
from .inputs import MANIFEST_EXTERNAL_ID
from .lifecycle import generation_for_inputs, generation_namespace, generation_passage_id

# Bump whenever the spans, views, objects, observations, native rows or bindings this
# module can produce could change. Plan ruling 10 (design review M2) folds it into the
# configuration `generation_for_inputs` hashes, so a changed derivation is a different
# generation and a staged row from an older binding can never be resumed into a seal.
CODE_BINDING_RULE_VERSION = "code-binding-v1"

# The mapped-chunk derivation this binding was written against. Not imported: a
# knowledge module may not reach into `hippo.ingest` (`tests/unit/test_layering.py`).
# A prepared result carrying a different `rule_version` is refused, never bound.
EXPECTED_CODE_CHUNK_RULE_VERSION = "code-chunks-v1"

# Where the two derivation rule versions enter the hashed configuration. Reserved: a
# caller that already uses the key is refused rather than overwritten, the same contract
# `repo_capture` keeps for its own `capture` key.
CODE_BINDING_CONFIGURATION_KEY = "code_derivation"

# Where the repository object's one observation points. The tree has no decoded text, so
# its span is a field on the tree revision carrying the normalized clone path the capture
# recorded -- never some file's first line, which would claim that a file states the
# repository's identity.
REPOSITORY_FIELD_PATH = "repository.clone_path"

# `codegraph.model.DATA_KINDS` to `model.ObjectKind`. Only `table` and `column` have
# their own name among the object kinds; a Mongo collection and the two Cypher kinds are
# recorded as the generic `resource` while their real kind and dialect stay inside
# `canonical_key` and `attributes_json`, so nothing merges and nothing is lost. A later
# slice may grow `ObjectKind` and narrow this map.
DATA_OBJECT_KINDS = {
    "table": "table",
    "column": "column",
    "collection": "resource",
    "label": "resource",
    "rel_type": "resource",
}

# The passage kinds this module binds. `commit` is the one kind it passes through.
BOUND_CHUNK_KINDS = ("header", "symbol", "data_object", "window", "prose")

# Plan section 9's row for a symbol or data observation: a snapshot of what the walkers
# saw, recorded at the one injected capture instant, with no effective interval claimed.
_SNAPSHOT = {
    "validity_kind": "observed_snapshot",
    "temporal_basis": "observed",
    "temporal_precision": "instant",
}

_CHUNK_FIELDS = (
    "ordinal",
    "kind",
    "title",
    "text",
    "chunk_key",
    "requires_view",
    "logical_path",
    "originals",
    "original_units",
    "symbol_id",
    "data_object_ids",
    "chunker_profile",
)


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Code evidence requires an explicit {label}")
    return value


# The four fields `ArtifactRevision` is written once for. `identity_fields` is
# `(artifact_id, provider_revision, content_hash)`, so an unchanged file captured by a
# second generation derives the *same* revision ID with a later `observed_at` -- and the
# store refuses to rewrite an immutable record ("Immutable record already exists with
# different contents"). `observed_at` therefore means *first* observed, exactly as the
# reviewed prose lane's `prose_generation._pair` already treats it.
_REVISION_IDENTITY = ("artifact_id", "content_hash", "provider_revision", "raw_uri")


def _reuse(revision: k.ArtifactRevision, stored) -> k.ArtifactRevision:
    """The stored revision for this content, when one exists; otherwise the fresh one."""
    existing = stored.get(revision.id) if stored else None
    if existing is None:
        return revision
    if type(existing) is not k.ArtifactRevision or any(
        getattr(existing, name) != getattr(revision, name) for name in _REVISION_IDENTITY
    ):
        raise ValueError("A stored accepted revision conflicts with this capture")
    return existing


def _fields(value, names: tuple[str, ...], label: str):
    """Structural acceptance: this boundary reads these fields, so they must be present."""
    missing = [name for name in names if not hasattr(value, name)]
    if missing:
        raise ValueError(f"{label} is missing {', '.join(missing)}")
    return value


@dataclass(frozen=True, slots=True)
class CodeGenerationInputs:
    """Everything generation identity needs beyond the artifacts this module derives.

    `policy_id` rides here because an `AccessPolicy` cannot be minted purely: the
    coordinator owns it, and every artifact and span written here carries it.
    """

    parent_id: str | None
    parser_version: str
    linker_version: str
    embedding_profile: str
    configuration: dict
    policy_id: str

    def __post_init__(self) -> None:
        for name in ("parser_version", "linker_version", "embedding_profile", "policy_id"):
            _text(getattr(self, name), name)
        if self.parent_id is not None:
            _text(self.parent_id, "parent generation")
        if not isinstance(self.configuration, Mapping):
            raise ValueError("Generation configuration must be a JSON object")

    def folded(self, chunk_rule_version: str) -> dict:
        """The caller's configuration plus the two derivation rule versions (ruling 10)."""
        if CODE_BINDING_CONFIGURATION_KEY in self.configuration:
            raise ValueError(
                f"Configuration key {CODE_BINDING_CONFIGURATION_KEY!r} is reserved for the code "
                "derivation rule versions"
            )
        return dict(self.configuration) | {
            CODE_BINDING_CONFIGURATION_KEY: {
                "binding": CODE_BINDING_RULE_VERSION,
                "chunker": chunk_rule_version,
            }
        }


@dataclass(frozen=True, slots=True)
class AcceptedCodeBinding:
    """One accepted captured file, its local artifact and its immutable revision."""

    raw_input: object
    artifact: k.Artifact
    revision: k.ArtifactRevision

    def __post_init__(self) -> None:
        if type(self.artifact) is not k.Artifact or type(self.revision) is not k.ArtifactRevision:
            raise ValueError("Accepted code bindings require exact immutable artifact/revision types")
        raw = _fields(
            self.raw_input,
            ("input_key", "logical_path", "raw_hash", "raw_uri", "provider_revision", "container_chain"),
            "Accepted raw input",
        )
        artifact, revision = self.artifact, self.revision
        if artifact.kind != "file" or artifact.connector_id is not None or tuple(raw.container_chain):
            raise ValueError("Only plain captured files without container mappings are supported")
        if artifact.deleted_at is not None or revision.lifecycle != "active":
            raise ValueError("An accepted captured file must be an active immutable revision")
        if (
            artifact.external_id != raw.logical_path
            or artifact.canonical_uri != f"source:{artifact.source_id}/{raw.logical_path}"
        ):
            raise ValueError("An accepted input path differs from its local artifact")
        if (revision.artifact_id, revision.content_hash, revision.raw_uri, revision.provider_revision) != (
            artifact.id,
            raw.raw_hash,
            raw.raw_uri,
            raw.provider_revision,
        ):
            raise ValueError("An accepted raw hash, URI or provider revision differs from its revision")

    @property
    def logical_path(self) -> str:
        return self.artifact.external_id

    @property
    def pair(self) -> tuple[k.Artifact, k.ArtifactRevision]:
        return (self.artifact, self.revision)


@dataclass(frozen=True, slots=True)
class NativeCodeRow:
    """One `Symbol` or `DataObject` row, carried as canonical JSON.

    JSON rather than a mapping so the bundle stays immutable and two runs compare equal.
    `row` rebuilds what the native writers take; the vector is the coordinator's to add,
    because only the embedding model can fill it.
    """

    native_kind: Literal["Symbol", "DataObject"]
    native_id: str
    row_json: str

    def __post_init__(self) -> None:
        if self.native_kind not in ("Symbol", "DataObject"):
            raise ValueError("Managed code native rows are Symbol or DataObject rows")
        _text(self.native_id, "native id")
        row = json.loads(self.row_json)
        if not isinstance(row, dict) or row.get("id") != self.native_id:
            raise ValueError("A native row must be an object identified by its own native ID")
        if "embedding" in row:
            raise ValueError("Vectors are added outside this boundary")

    @property
    def row(self) -> dict:
        return json.loads(self.row_json)


@dataclass(frozen=True, slots=True)
class BoundCodePassage:
    """One mapped code passage bound to its exact original spans and rendered view."""

    chunk: object
    generation: k.Generation
    span: k.EvidenceSpan
    spans: tuple[k.EvidenceSpan, ...]
    view: k.RetrievalView | None

    def __post_init__(self) -> None:
        if (
            type(self.generation) is not k.Generation
            or type(self.span) is not k.EvidenceSpan
            or (self.view is not None and type(self.view) is not k.RetrievalView)
        ):
            raise ValueError("Passage bindings require exact immutable evidence types")
        object.__setattr__(self, "spans", tuple(self.spans))
        if not self.spans or any(type(span) is not k.EvidenceSpan for span in self.spans):
            raise ValueError("A bound passage requires a nonempty exact original closure")
        if self.spans[0] != self.span:
            raise ValueError("A bound passage anchors on the first span of its own closure")
        chunk = _fields(self.chunk, _CHUNK_FIELDS, "Prepared code chunk")
        if self.generation.status != "staging":
            raise ValueError("Bound passages require a staging generation")
        if chunk.kind not in BOUND_CHUNK_KINDS:
            raise ValueError(f"Passage kind {chunk.kind!r} is not bound at this boundary")
        if self.view is None:
            if chunk.requires_view or chunk.text != self.span.text or len(self.spans) != 1:
                raise ValueError("An original-only passage differs from its complete original")
        elif (self.view.span_id, self.view.source_revision_id, self.view.text, self.view.vector_profile) != (
            self.span.id,
            self.span.revision_id,
            chunk.text,
            self.generation.embedding_profile,
        ):
            raise ValueError("A rendered passage differs from its exact view binding")

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

    def native_row(self) -> dict:
        """The dense passage row without its vector, which the coordinator adds."""
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


@dataclass(frozen=True, slots=True)
class CodeEvidenceBundle:
    """One code generation's complete non-commit evidence, closed and self-consistent."""

    generation: k.Generation
    workspace_id: str
    rule_version: str
    chunk_rule_version: str
    configuration_json: str
    repository_artifact: k.Artifact
    repository_revision: k.ArtifactRevision
    repository_object: k.KnowledgeObject
    repository_span: k.EvidenceSpan
    manifest_artifact: k.Artifact
    manifest_revision: k.ArtifactRevision
    accepted: tuple[AcceptedCodeBinding, ...]
    objects: tuple[k.KnowledgeObject, ...]
    observations: tuple[k.ObjectObservation, ...]
    spans: tuple[k.EvidenceSpan, ...]
    views: tuple[k.RetrievalView, ...]
    derived_records: tuple[k.DerivedRecord, ...]
    derived_dependencies: tuple[k.DerivedDependency, ...]
    native_rows: tuple[NativeCodeRow, ...]
    bindings: tuple[k.NativeBinding, ...]
    revision_members: tuple[k.GenerationMember, ...]
    evidence_members: tuple[k.GenerationEvidenceMember, ...]
    passages: tuple[BoundCodePassage, ...]
    commit_chunks: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        for name, expected in (
            ("accepted", AcceptedCodeBinding),
            ("objects", k.KnowledgeObject),
            ("observations", k.ObjectObservation),
            ("spans", k.EvidenceSpan),
            ("views", k.RetrievalView),
            ("derived_records", k.DerivedRecord),
            ("derived_dependencies", k.DerivedDependency),
            ("native_rows", NativeCodeRow),
            ("bindings", k.NativeBinding),
            ("revision_members", k.GenerationMember),
            ("evidence_members", k.GenerationEvidenceMember),
            ("passages", BoundCodePassage),
        ):
            values = tuple(getattr(self, name))
            if any(type(value) is not expected for value in values):
                raise ValueError(f"Code evidence requires exact immutable {expected.__name__} values")
            object.__setattr__(self, name, values)
        object.__setattr__(self, "commit_chunks", tuple(self.commit_chunks))
        self._check_scope()
        self._check_inventory()
        self._check_membership()
        self._check_references()

    # -------------------------------------------------------------- validation

    def _check_scope(self) -> None:
        _text(self.workspace_id, "workspace")
        if type(self.generation) is not k.Generation or self.generation.status != "staging":
            raise ValueError("Code evidence requires an immutable staging generation")
        if self.rule_version != CODE_BINDING_RULE_VERSION:
            raise ValueError("Code evidence carries the current binding rule version")
        if self.chunk_rule_version != EXPECTED_CODE_CHUNK_RULE_VERSION:
            raise ValueError("Code evidence carries the pinned chunk rule version")
        if not isinstance(self.configuration, Mapping):
            raise ValueError("Code evidence carries its hashed configuration as a JSON object")
        if self.repository_artifact.kind != "repository" or self.manifest_artifact.kind != "manifest":
            raise ValueError("The tree and manifest artifacts must keep their declared kinds")
        if self.manifest_artifact.external_id != MANIFEST_EXTERNAL_ID:
            raise ValueError("The accepted manifest keeps its local external identity")
        scope = (self.workspace_id, self.source_id)
        for artifact in (
            self.repository_artifact,
            self.manifest_artifact,
            *(item.artifact for item in self.accepted),
        ):
            if (artifact.workspace_id, artifact.source_id) != scope:
                raise ValueError("An accepted artifact crosses the generation source or workspace")
        if any(record.workspace_id != self.workspace_id for record in self.derived_records):
            raise ValueError("A code derivation crosses workspaces")
        if any(object_.workspace_id != self.workspace_id for object_ in self.objects):
            raise ValueError("A code knowledge object crosses workspaces")
        crossing = {
            member.generation_id
            for member in (*self.revision_members, *self.evidence_members, *self.bindings)
        } | {passage.generation.id for passage in self.passages}
        if crossing - {self.generation_id} or any(
            passage.generation != self.generation for passage in self.passages
        ):
            raise ValueError("Code evidence crosses generations")

    def _check_inventory(self) -> None:
        for label, identities in (
            ("spans", [span.id for span in self.spans]),
            ("objects", [object_.id for object_ in self.objects]),
            ("observations", [row.id for row in self.observations]),
            ("views", [view.id for view in self.views]),
            ("derived records", [record.id for record in self.derived_records]),
            ("derived dependencies", [edge.id for edge in self.derived_dependencies]),
            ("bindings", [binding.id for binding in self.bindings]),
            ("native rows", [(row.native_kind, row.native_id) for row in self.native_rows]),
            ("accepted inputs", [item.artifact.id for item in self.accepted]),
            ("passages", [passage.id for passage in self.passages]),
            ("passage chunk keys", [passage.chunk.chunk_key for passage in self.passages]),
            ("passage ordinals", [passage.chunk.ordinal for passage in self.passages]),
            ("revision members", [member.artifact_revision_id for member in self.revision_members]),
        ):
            if len(set(identities)) != len(identities):
                raise ValueError(f"Duplicate code evidence {label}")

    def _check_membership(self) -> None:
        revisions = {member.artifact_revision_id for member in self.revision_members}
        expected = {
            self.repository_revision.id,
            self.manifest_revision.id,
            *(item.revision.id for item in self.accepted),
        }
        if revisions != expected:
            raise ValueError("Code revision membership differs from its accepted inventory")
        if any(span.revision_id not in revisions for span in self.spans):
            raise ValueError("Code revision membership must cover every original span")
        if any(row.revision_id not in revisions for row in self.observations):
            raise ValueError("Code revision membership must cover every observation")
        if any(view.source_revision_id not in revisions for view in self.views):
            raise ValueError("Code revision membership must cover every rendered view")
        if any(
            set(record.input_revision_ids) - revisions or record.input_binding_ids
            for record in self.derived_records
        ):
            raise ValueError("A code derivation cites a revision outside the accepted inventory")
        expected_members = {(type(record).__name__, record.id) for record in self.records}
        actual = {(member.record_kind, member.record_id) for member in self.evidence_members}
        if (
            expected_members != actual
            or len(actual) != len(self.evidence_members)
            or len(expected_members) != len(self.records)
        ):
            raise ValueError("Code exact membership differs from its immutable evidence inventory")

    def _check_references(self) -> None:
        spans = {span.id: span for span in self.spans}
        objects = {object_.id for object_ in self.objects}
        views = {view.id for view in self.views}
        records = {record.id for record in self.derived_records}
        natives = {(row.native_kind, row.native_id) for row in self.native_rows}
        observed = {(row.object_id, row.span_id) for row in self.observations}
        if spans.get(self.repository_span.id) != self.repository_span:
            raise ValueError("The repository span is outside the exact span inventory")
        if self.repository_object.id not in objects:
            raise ValueError("The repository object is outside the object inventory")
        for row in self.observations:
            if row.object_id not in objects or row.span_id not in spans:
                raise ValueError("An observation cites an object or span outside the bundle")
            if row.revision_id != spans[row.span_id].revision_id:
                raise ValueError("An observation revision differs from its own span")
        for view in self.views:
            if view.span_id not in spans or view.derived_record_id not in records:
                raise ValueError("A rendered view cites a span or derivation outside the bundle")
        for edge in self.derived_dependencies:
            if edge.derived_record_id not in records or edge.input_kind != "span":
                raise ValueError("A derivation dependency must cite a span of its own record")
            if edge.input_id not in spans or edge.input_version != dependency_version(spans[edge.input_id]):
                raise ValueError("A derivation dependency differs from its exact original")
        if {(binding.native_kind, binding.native_id) for binding in self.bindings} != natives:
            raise ValueError("Every native row requires an evidence binding")
        for binding in self.bindings:
            if (binding.object_id, binding.span_id) not in observed:
                raise ValueError("A native binding object lacks a selected observation")
        for passage in self.passages:
            if any(spans.get(span.id) != span for span in passage.spans):
                raise ValueError("A passage cites a span outside the exact inventory")
            if passage.retrieval_view_id is not None and passage.retrieval_view_id not in views:
                raise ValueError("A rendered passage cites a view outside the exact inventory")
            _disjoint(passage.spans)

    # ------------------------------------------------------------- projections

    @property
    def generation_id(self) -> str:
        return self.generation.id

    @property
    def source_id(self) -> str:
        return self.generation.source_id

    @property
    def configuration(self) -> dict:
        return json.loads(self.configuration_json)

    @property
    def records(self) -> tuple:
        """Typed evidence records in dependency order, excluding artifacts and revisions."""
        return (
            *self.spans,
            *self.derived_records,
            *self.derived_dependencies,
            *self.views,
            *self.observations,
        )

    @property
    def accepted_pairs(self) -> tuple[tuple[k.Artifact, k.ArtifactRevision], ...]:
        """Every accepted artifact/revision pair `generation_for_inputs` hashed."""
        return (
            (self.repository_artifact, self.repository_revision),
            (self.manifest_artifact, self.manifest_revision),
            *(item.pair for item in self.accepted),
        )


def _disjoint(spans: tuple[k.EvidenceSpan, ...]) -> None:
    """One passage's own originals are merged complete-line runs, so they cannot overlap.

    Deliberately per passage rather than across the generation: two overlapping line
    windows of one file legitimately cite the same bytes in two different spans, exactly
    as an overlapping prose chunk does.
    """
    ranges = sorted(
        (json.loads(span.locator_json)["start"], json.loads(span.locator_json)["end"]) for span in spans
    )
    if any(left[1] >= right[0] for left, right in zip(ranges, ranges[1:], strict=False)):
        raise ValueError("A passage cites one original line from two spans")


# ------------------------------------------------------------------ rendering


def _view(chunk, generation: k.Generation, workspace_id: str, spans, anchor: k.EvidenceSpan):
    """A projection over exact originals, as `input_binding._view` does for prose."""
    dependencies = tuple(("span", span.id, dependency_version(span)) for span in spans)
    profile = make_identity(
        "text_profile",
        [
            CODE_BINDING_RULE_VERSION,
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
        rule_version=CODE_BINDING_RULE_VERSION,
        model_version=None,
        dependencies=dependencies,
    )
    derived = k.DerivedRecord(
        workspace_id=workspace_id,
        view_kind="projection",
        rule_version=CODE_BINDING_RULE_VERSION,
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
        derivation_version=CODE_BINDING_RULE_VERSION,
        dependency_fingerprint=fingerprint,
        derived_record_id=derived.id,
    )
    return view, derived, edges


# ------------------------------------------------------- accepted inputs


@dataclass(frozen=True, slots=True)
class _Settled:
    """Generation identity and the accepted inputs it was computed from."""

    generation: k.Generation
    configuration: dict
    tree: tuple[k.Artifact, k.ArtifactRevision]
    manifest: tuple[k.Artifact, k.ArtifactRevision]
    files: tuple[AcceptedCodeBinding, ...]
    repository_object: k.KnowledgeObject
    repository_span: k.EvidenceSpan

    @property
    def pairs(self) -> tuple[tuple[k.Artifact, k.ArtifactRevision], ...]:
        return (self.tree, self.manifest, *(item.pair for item in self.files))


def _file_pairs(capture, *, workspace_id, source_id, policy_id, observed_at, stored=None):
    """Local artifact/revision pairs for every captured file, in canonical order.

    Plan section 9: a file revision records the one capture instant and no
    `source_updated_at`, because a working-tree mtime is not provider truth.
    """
    out = []
    for raw in capture.accepted.inputs:
        artifact = k.Artifact(
            workspace_id=workspace_id,
            source_id=source_id,
            kind="file",
            external_id=raw.logical_path,
            canonical_uri=f"source:{source_id}/{raw.logical_path}",
            policy_id=policy_id,
        )
        revision = k.ArtifactRevision(
            artifact_id=artifact.id,
            provider_revision=raw.provider_revision,
            content_hash=raw.raw_hash,
            raw_uri=raw.raw_uri,
            observed_at=observed_at,
            lifecycle="active",
        )
        out.append(AcceptedCodeBinding(raw, artifact, _reuse(revision, stored)))
    return tuple(out)


def _manifest_pair(capture, *, workspace_id, source_id, policy_id, observed_at, stored=None):
    artifact = k.Artifact(
        workspace_id=workspace_id,
        source_id=source_id,
        kind="manifest",
        external_id=MANIFEST_EXTERNAL_ID,
        canonical_uri=f"source:{source_id}/{MANIFEST_EXTERNAL_ID}",
        policy_id=policy_id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        content_hash=capture.accepted.manifest.sha256,
        raw_uri=capture.accepted.manifest.uri,
        observed_at=observed_at,
        lifecycle="active",
        metadata_json=canonical_json({"accepted_manifest_v1": json.loads(capture.accepted.manifest_bytes)}),
    )
    return artifact, _reuse(revision, stored)


def _repository_identity(capture, source_id: str) -> tuple[str, list]:
    """The tree's external identity and its canonical object key.

    Plan ruling 4 and design review M8: a checkout's identity is its whole normalized
    clone path, so two subgroups of one forge cannot collide into one repository. An
    archive, a single file, or a checkout captured without a clone URL has no repository
    on any forge, so plan section 5's source-scoped key stands in; it can never collide
    with a forge key, whose first element is an `https` instance URL.
    """
    descriptor = capture.repository
    if descriptor is None:
        return f"source:{source_id}", [f"source:{source_id}"]
    external_id = f"{descriptor.provider_instance}/{descriptor.provider_repository_id}"
    return external_id, repository_key(descriptor.provider_instance, descriptor.provider_repository_id)


def _tree_records(capture, *, workspace_id, source_id, policy_id, observed_at, stored=None):
    external_id, canonical_key = _repository_identity(capture, source_id)
    artifact = k.Artifact(
        workspace_id=workspace_id,
        source_id=source_id,
        kind="repository",
        external_id=external_id,
        canonical_uri=external_id,
        policy_id=policy_id,
    )
    # The tree has no raw object of its own: its content is exactly its accepted
    # manifest, and the head commit SHA is the provider revision plan section 5 puts into
    # generation identity.
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        provider_revision=capture.provider_revision,
        content_hash=capture.accepted.manifest.sha256,
        raw_uri=capture.accepted.manifest.uri,
        observed_at=observed_at,
        lifecycle="active",
    )
    revision = _reuse(revision, stored)
    object_ = k.KnowledgeObject(
        workspace_id=workspace_id, kind="repository", canonical_key=canonical_json(canonical_key)
    )
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="field",
        locator_json=canonical_json(k.FieldLocator(field_path=REPOSITORY_FIELD_PATH).model_dump(mode="json")),
        text=external_id,
        policy_id=policy_id,
    )
    return (artifact, revision), object_, span


def _settle(
    capture, *, workspace_id, source_id, identity, observed_at, chunk_rule_version, stored=None
) -> _Settled:
    _text(workspace_id, "workspace")
    _text(source_id, "source")
    if type(identity) is not CodeGenerationInputs:
        raise ValueError("Code evidence requires immutable generation identity inputs")
    if type(observed_at) is not datetime or observed_at.utcoffset() is None:
        raise ValueError("The capture instant must be an explicit timezone-aware datetime")
    capture = _fields(
        capture,
        ("kind", "accepted", "observed_at", "provider_revision", "repository"),
        "Repository capture",
    )
    accepted = _fields(
        capture.accepted, ("source_id", "workspace_id", "inputs", "manifest"), "Accepted inputs"
    )
    if (accepted.source_id, accepted.workspace_id) != (source_id, workspace_id):
        raise ValueError("The captured inventory belongs to another source or workspace")
    if stored is not None and not isinstance(stored, Mapping):
        raise ValueError("Stored revisions must be a mapping of revision id to record")
    shared = {
        "workspace_id": workspace_id,
        "source_id": source_id,
        "policy_id": identity.policy_id,
        "observed_at": observed_at,
        "stored": stored,
    }
    files = _file_pairs(capture, **shared)
    manifest = _manifest_pair(capture, **shared)
    tree, repository_object, repository_span = _tree_records(capture, **shared)
    configuration = identity.folded(chunk_rule_version)
    pairs = (tree, manifest, *(item.pair for item in files))
    generation = generation_for_inputs(
        pairs,
        workspace_id=workspace_id,
        source_id=source_id,
        parent_id=identity.parent_id,
        parser_version=identity.parser_version,
        linker_version=identity.linker_version,
        embedding_profile=identity.embedding_profile,
        configuration=configuration,
        created_at=observed_at,
    )
    return _Settled(generation, configuration, tree, manifest, files, repository_object, repository_span)


def code_generation(
    capture,
    *,
    workspace_id: str,
    source_id: str,
    generation_identity_inputs: CodeGenerationInputs,
    observed_at: datetime,
    stored_revisions: Mapping[str, k.ArtifactRevision] | None = None,
) -> k.Generation:
    """The staging generation for a captured tree, settled before any extraction.

    The coordinator needs `lifecycle.generation_namespace(...)` before it can extract the
    code graph (plan section 6 step 4), and the namespace needs the generation -- which
    depends only on the accepted inputs and the configuration, never on the graph. So
    identity is settled here, and `materialize_code_evidence` recomputes exactly this
    value from the same arguments.
    """
    return _settle(
        capture,
        workspace_id=workspace_id,
        source_id=source_id,
        identity=generation_identity_inputs,
        observed_at=observed_at,
        chunk_rule_version=EXPECTED_CODE_CHUNK_RULE_VERSION,
        stored=stored_revisions,
    ).generation


# ------------------------------------------------------------------- objects


def _observation(object_id, span, *, evidence_class, attributes, observed_at):
    return k.ObjectObservation(
        object_id=object_id,
        revision_id=span.revision_id,
        span_id=span.id,
        attributes_json=canonical_json(attributes),
        evidence_class=evidence_class,
        recorded_from=observed_at,
        **_SNAPSHOT,
    )


def _repository_attributes(capture) -> dict:
    descriptor = capture.repository
    named = (
        {
            "provider_instance": descriptor.provider_instance,
            "repository_id": descriptor.provider_repository_id,
        }
        if descriptor is not None
        else {"provider_instance": None, "repository_id": None}
    )
    return named | {"capture_kind": capture.kind, "head_revision": capture.provider_revision}


def _file_object(workspace_id, repository_object_id, logical_path):
    return k.KnowledgeObject(
        workspace_id=workspace_id,
        kind="file",
        canonical_key=canonical_json([repository_object_id, normalize_relative_path(logical_path)]),
    )


def _symbol_object(workspace_id, repository_object_id, symbol):
    """Keyed by the repository object, so two sources of one repository share the symbol.

    The signature discriminator is supplied where the walker produced one, so overloads
    keep distinct canonical objects (plan section 5).
    """
    return k.KnowledgeObject(
        workspace_id=workspace_id,
        kind="symbol",
        canonical_key=canonical_json(
            symbol_key(
                repository_object_id,
                symbol.lang,
                symbol.path,
                symbol.qualname,
                symbol.signature or None,
                kind=symbol.kind,
            )
        ),
    )


def _symbol_attributes(symbol) -> dict:
    return {
        "name": symbol.name,
        "qualname": symbol.qualname,
        "path": symbol.path,
        "kind": symbol.kind,
        "lang": symbol.lang,
        "signature": symbol.signature,
        "doc": symbol.doc,
        "is_test": bool(symbol.is_test),
        "line_start": symbol.line_start,
        "line_end": symbol.line_end,
    }


def _data_object(workspace_id, repository_object_id, data):
    if data.kind not in DATA_OBJECT_KINDS:
        raise ValueError(f"Unknown code data object kind {data.kind!r}")
    return k.KnowledgeObject(
        workspace_id=workspace_id,
        kind=DATA_OBJECT_KINDS[data.kind],
        canonical_key=canonical_json([repository_object_id, data.dialect, data.kind, data.qualname]),
    )


def _data_attributes(data) -> dict:
    return {"name": data.name, "qualname": data.qualname, "kind": data.kind, "dialect": data.dialect}


def _by_native_id(nodes) -> dict[str, list]:
    """Group code nodes by native ID, because one ID can name more than one node.

    `codegraph.model.symbol_id` carries no signature discriminator, so two C# or
    TypeScript overloads in one file share a native ID while `symbol_key` -- which does
    carry the signature -- keeps them distinct canonical objects (plan section 5, gate
    CD5). A passage naming that shared ID therefore observes every node behind it: the
    chunker's passage boundaries are drawn per symbol, but its `symbol_id` cannot tell
    the overloads apart, and silently attributing the passage to whichever node was seen
    last would drop half the inventory.
    """
    grouped: dict[str, list] = {}
    for node in nodes:
        grouped.setdefault(node.id, []).append(node)
    return grouped


def _unknown(label: str):
    raise ValueError(f"A prepared passage names a {label} this code graph does not know")


def _native_id(native_kind: str, source_id: str, node, namespace: str) -> str:
    # Imported here rather than at module scope: `hippo.codegraph`'s package body loads
    # the tree-sitter walkers, and no knowledge import should pay for a parser it never
    # uses. `codegraph.model` itself is pure.
    from ..codegraph.model import data_id, symbol_id

    if native_kind == "Symbol":
        return symbol_id(source_id, node.path, node.qualname, node.kind, node_namespace=namespace)
    return data_id(source_id, node.kind, node.qualname, node_namespace=namespace)


class _Inventory:
    """One generation's accumulating objects, observations, native rows and bindings."""

    def __init__(self, settled: _Settled, *, workspace_id: str, observed_at: datetime, capture):
        self.workspace_id = workspace_id
        self.observed_at = observed_at
        self.generation = settled.generation
        self.namespace = generation_namespace(settled.generation)
        self.repository_object_id = settled.repository_object.id
        self.objects = {settled.repository_object.id: settled.repository_object}
        self.observations: dict[str, k.ObjectObservation] = {}
        self.natives: dict[tuple[str, str], NativeCodeRow] = {}
        self.bindings: dict[str, k.NativeBinding] = {}
        self.record(
            settled.repository_object.id,
            settled.repository_span,
            evidence_class="declared",
            attributes=_repository_attributes(capture),
        )

    def record(self, object_id, span, *, evidence_class, attributes):
        row = _observation(
            object_id,
            span,
            evidence_class=evidence_class,
            attributes=attributes,
            observed_at=self.observed_at,
        )
        self.observations.setdefault(row.id, row)

    def bind(self, *, native_kind, node, object_, attributes, span):
        """One knowledge object, its observation, its native row and their binding.

        `codegraph.model.symbol_id` carries no signature discriminator, so two overloads
        differing only by signature share one native ID while `symbol_key` keeps them two
        distinct canonical objects. That is recorded rather than repaired: the first row
        in canonical order is kept and both objects bind to it.
        """
        if node.id != _native_id(native_kind, self.generation.source_id, node, self.namespace):
            raise ValueError("A native code ID does not match the generation namespace")
        key = (native_kind, node.id)
        if key not in self.natives:
            row = dict(node.row()) | {"generation_id": self.generation.id}
            self.natives[key] = NativeCodeRow(native_kind, node.id, canonical_json(row))
        self.objects.setdefault(object_.id, object_)
        self.record(object_.id, span, evidence_class="syntax_observed", attributes=attributes)
        binding = k.NativeBinding(
            generation_id=self.generation.id,
            object_id=object_.id,
            native_kind=native_kind,
            native_id=node.id,
            span_id=span.id,
        )
        self.bindings.setdefault(binding.id, binding)


# ---------------------------------------------------------------- the boundary


def materialize_code_evidence(
    capture,
    chunks,
    facts,
    *,
    workspace_id: str,
    source_id: str,
    generation_identity_inputs: CodeGenerationInputs,
    observed_at: datetime,
    stored_revisions: Mapping[str, k.ArtifactRevision] | None = None,
) -> CodeEvidenceBundle:
    """Bind one captured tree and its mapped passages; the result is not a publication.

    Nothing here writes, authorizes or publishes. A successful return says only that the
    inventory is internally exact: the fenced writer still has to persist it under its
    lease, and the seal still has to agree.
    """
    chunks = _fields(chunks, ("rule_version", "chunks", "refusals"), "Prepared code chunks")
    if chunks.rule_version != EXPECTED_CODE_CHUNK_RULE_VERSION:
        raise ValueError(
            f"Prepared code chunks carry chunk rule version {chunks.rule_version!r}; this "
            f"binding is pinned to {EXPECTED_CODE_CHUNK_RULE_VERSION!r}"
        )
    settled = _settle(
        capture,
        workspace_id=workspace_id,
        source_id=source_id,
        identity=generation_identity_inputs,
        observed_at=observed_at,
        chunk_rule_version=chunks.rule_version,
        stored=stored_revisions,
    )
    generation = settled.generation
    inventory = _Inventory(settled, workspace_id=workspace_id, observed_at=observed_at, capture=capture)
    by_input_key = {item.raw_input.input_key: item for item in settled.files}
    by_path = {item.logical_path: item for item in settled.files}
    symbols = _by_native_id(facts.symbols if facts is not None else ())
    data_objects = _by_native_id(facts.data_objects if facts is not None else ())

    spans: dict[str, k.EvidenceSpan] = {settled.repository_span.id: settled.repository_span}
    views: dict[str, k.RetrievalView] = {}
    derived_records: dict[str, k.DerivedRecord] = {}
    dependencies: dict[str, k.DerivedDependency] = {}
    passages: list[BoundCodePassage] = []
    commit_chunks: list[object] = []
    file_spans: dict[str, list[k.EvidenceSpan]] = {}

    for chunk in chunks.chunks:
        chunk = _fields(chunk, _CHUNK_FIELDS, "Prepared code chunk")
        if chunk.kind == "commit":
            commit_chunks.append(chunk)
            continue
        if chunk.kind not in BOUND_CHUNK_KINDS:
            raise ValueError(f"Unknown prepared code chunk kind {chunk.kind!r}")
        if by_path.get(chunk.logical_path) is None:
            raise ValueError("A prepared passage cites a file this capture never accepted")
        units = {}
        for unit in chunk.original_units:
            item = by_input_key.get(unit.input_key)
            if item is None or unit.locator.path != item.logical_path:
                raise ValueError("A prepared passage cites a file this capture never accepted")
            if unit.unit_key != make_identity(
                "original_unit", [unit.input_key, item.raw_input.raw_hash, unit.decoder_profile]
            ):
                raise ValueError("A prepared original unit differs from its accepted raw identity")
            if unit.raw_ranges[-1].end != item.raw_input.byte_length:
                raise ValueError("A prepared decoder map differs from its accepted raw byte length")
            units[unit.unit_key] = item
        chunk_spans = []
        for original in chunk.originals:
            item = units[original.unit_key]
            candidate = k.EvidenceSpan(
                revision_id=item.revision.id,
                locator_kind="file_lines",
                locator_json=canonical_json(original.lines.locator.model_dump(mode="json")),
                text=original.lines.text,
                policy_id=item.artifact.policy_id,
            )
            span = spans.setdefault(candidate.id, candidate)
            chunk_spans.append(span)
            cited = file_spans.setdefault(item.logical_path, [])
            if all(existing.id != span.id for existing in cited):
                cited.append(span)
        if not chunk_spans:
            raise ValueError("A prepared passage cannot have an empty original closure")
        anchor = chunk_spans[0]
        view = None
        if chunk.requires_view:
            candidate, derived, edges = _view(chunk, generation, workspace_id, tuple(chunk_spans), anchor)
            view = views.setdefault(candidate.id, candidate)
            derived_records.setdefault(derived.id, derived)
            for edge in edges:
                dependencies.setdefault(edge.id, edge)
        passages.append(BoundCodePassage(chunk, generation, anchor, tuple(chunk_spans), view))

        if chunk.symbol_id is not None:
            for symbol in symbols.get(chunk.symbol_id) or _unknown("symbol"):
                inventory.bind(
                    native_kind="Symbol",
                    node=symbol,
                    object_=_symbol_object(workspace_id, inventory.repository_object_id, symbol),
                    attributes=_symbol_attributes(symbol),
                    span=anchor,
                )
        for identity in chunk.data_object_ids:
            for data in data_objects.get(identity) or _unknown("data object"):
                inventory.bind(
                    native_kind="DataObject",
                    node=data,
                    object_=_data_object(workspace_id, inventory.repository_object_id, data),
                    attributes=_data_attributes(data),
                    span=anchor,
                )

    for logical_path, cited in file_spans.items():
        object_ = _file_object(workspace_id, inventory.repository_object_id, logical_path)
        inventory.objects.setdefault(object_.id, object_)
        for span in cited:
            inventory.record(
                object_.id,
                span,
                evidence_class="catalog_observed",
                attributes={"path": logical_path, "capture_kind": capture.kind},
            )

    records = (
        *spans.values(),
        *derived_records.values(),
        *dependencies.values(),
        *views.values(),
        *inventory.observations.values(),
    )
    return CodeEvidenceBundle(
        generation=generation,
        workspace_id=workspace_id,
        rule_version=CODE_BINDING_RULE_VERSION,
        chunk_rule_version=chunks.rule_version,
        configuration_json=canonical_json(settled.configuration),
        repository_artifact=settled.tree[0],
        repository_revision=settled.tree[1],
        repository_object=settled.repository_object,
        repository_span=settled.repository_span,
        manifest_artifact=settled.manifest[0],
        manifest_revision=settled.manifest[1],
        accepted=settled.files,
        objects=tuple(inventory.objects.values()),
        observations=tuple(inventory.observations.values()),
        spans=tuple(spans.values()),
        views=tuple(views.values()),
        derived_records=tuple(derived_records.values()),
        derived_dependencies=tuple(dependencies.values()),
        native_rows=tuple(inventory.natives.values()),
        bindings=tuple(inventory.bindings.values()),
        revision_members=tuple(
            k.GenerationMember(generation_id=generation.id, artifact_revision_id=revision.id)
            for _, revision in settled.pairs
        ),
        evidence_members=tuple(
            k.GenerationEvidenceMember(
                generation_id=generation.id, record_kind=type(record).__name__, record_id=record.id
            )
            for record in records
        ),
        passages=tuple(passages),
        commit_chunks=tuple(commit_chunks),
    )
