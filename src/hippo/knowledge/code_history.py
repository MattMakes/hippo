"""Pure materialization of one repository's git history into exact evidence.

`read_history` already walks the first-parent line and returns commits, `MODIFIES`
and `PRECEDES` in the shapes the native writers take. This module turns that walk
into the plan's section 4 commit inventory and the plan's section 9 temporal fields:
one `history_event` `Artifact` and immutable `ArtifactRevision` per commit, one
`KnowledgeObject(kind="commit")` and one `ObjectObservation` per commit, the
commit-message `EvidenceSpan` those observations point at, the rendered view for the
commit passage CC6 passed through unbound, the generation-namespaced native `Commit`
rows with a `NativeBinding` each, and the exact `GenerationEvidenceMember` closure
over all of it.

No raw I/O, no persistence handle, no model client and **no wall clock**: the capture
instant is an argument, and it has to be the one the generation was settled at, so a
replay of the same inputs produces byte-identical records (plan section 6 step 7).
A commit's own timestamps are the repository's, not this machine's: the author date
lands in `source_updated_at`, its raw `%aI` text in `source_timestamp_original` and
its offset in `source_timezone`, unparsed and unrewritten, at `source_precision`
`"second"`.

Honest coverage. `git log --first-parent` never sees a merged side branch, so
`coverage` always records `history_walk: "first_parent"` beside the budget skips, the
truncation flag, the shallow-clone boundary and the configured depth (design review
m4). A first-parent walk is never presented as the repository's complete history, and
`history_depth == 0` records `history: "disabled"` rather than an empty one.

Refusals, not silent drops. A `MODIFIES` edge whose symbol has no native row in this
generation's bundle, a `PRECEDES` pair naming a commit this walk did not keep, a
commit passage naming a commit that is not here, a native commit ID that does not
re-derive from the generation namespace: each refuses. Losing history quietly is
worse than failing a build that can be re-run.

Layering. Like `code_binding`, this module imports nothing from `hippo.ingest`; the
prepared commit passages it reads are validated structurally, by the fields this
boundary actually reads. `EXPECTED_CODE_BINDING_RULE_VERSION` pins the binding
derivation this history was written against, so bumping CC6 without bumping this
module fails closed instead of mixing two derivations into one generation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from . import model as k
from .code_binding import BoundCodePassage, CodeEvidenceBundle, NativeCodeRow, _reuse
from .derivations import dependency_version, view_fingerprint
from .identity import canonical_json, make_identity, text_hash
from .lifecycle import generation_namespace as _namespace_of
from .lifecycle import generation_passage_id

# Bump whenever the artifacts, revisions, spans, views, objects, observations, native
# rows, bindings or coverage this module can produce could change. Plan ruling 10 folds
# it into the configuration `generation_for_inputs` hashes, so a changed derivation is a
# different generation and a staged row from an older history pass can never be resumed
# into a seal.
CODE_HISTORY_RULE_VERSION = "code-history-v1"

# The binding derivation this history was written against. Pinned rather than imported
# as a live value: a `CodeEvidenceBundle` carrying any other rule version is refused, so
# a CC6 bump requires a bump here instead of silently binding a derivation never seen.
EXPECTED_CODE_BINDING_RULE_VERSION = "code-binding-v2"

# Where this module's rule version enters the hashed configuration. Deliberately a
# top-level key of its own rather than a third entry under `code_binding`'s reserved
# `code_derivation`: the coordinator must set it **before** it settles the generation,
# and `code_binding.CodeGenerationInputs.folded` owns `code_derivation` outright and
# refuses a caller that pre-sets it. Setting this key is therefore how the history rule
# version actually reaches `generation_for_inputs`; `bind_history` refuses a generation
# whose configuration omits it or carries another value, so identity provably includes
# it rather than merely claiming to.
HISTORY_CONFIGURATION_KEY = "code_history_derivation"

# Where a commit's own message lives. A field locator on the `history_event` revision,
# never a synthetic whole-file `file_lines` span: a commit message is not a region of
# any captured file, and claiming it was would make a file appear to state the commit.
COMMIT_MESSAGE_FIELD_PATH = "commit.message"

# A commit's metadata is what its author declared, so it is `declared` evidence -- the
# same class `code_binding` gives the repository's own identity. It is emphatically not
# `syntax_observed` (no walker read it) nor `catalog_observed` (no tree inventory listed
# it): git reports the author's own words and the author's own timestamp.
COMMIT_EVIDENCE_CLASS = "declared"

# `read_history` walks `git log --first-parent`, so commits on merged side branches are
# never seen. Recorded in coverage on every build, enabled or not (design review m4).
HISTORY_WALK = "first_parent"

# A commit revision names no stored raw object: nothing was captured for it and nothing
# dereferences a non-`file` revision's `raw_uri` (`generation_profiles.py:168-178`
# checks raw identity for accepted `file` revisions only). The scheme says so plainly
# rather than borrowing the accepted manifest's URI, which would claim the commit's
# content is the tree's inventory.
COMMIT_RAW_URI_SCHEME = "hippo-commit:"

# Plan section 9's row for a commit observation: an explicit interval opening at the
# author date, basis `commit`, at the second `%aI` actually carries.
_COMMIT_INTERVAL = {
    "validity_kind": "explicit_interval",
    "temporal_basis": "commit",
    "temporal_precision": "second",
}

# `History`, `read_history`'s commit rows, its `MODIFIES` rows and CC6's passed-through
# commit passages, by the fields this boundary reads.
_HISTORY_FIELDS = ("commits", "modifies", "precedes", "skipped", "truncated")
_COMMIT_FIELDS = ("id", "source_id", "sha", "author", "date", "message", "ordinal")
_MODIFIES_FIELDS = ("commit_id", "symbol_id", "omega", "hunk")
_COMMIT_CHUNK_FIELDS = (
    "ordinal",
    "kind",
    "title",
    "text",
    "chunk_key",
    "commit_id",
    "commit_sha",
    "chunker_profile",
    "original_units",
)


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Code history requires an explicit {label}")
    return value


def _fields(value, names: tuple[str, ...], label: str):
    """Structural acceptance: this boundary reads these fields, so they must be present."""
    missing = [name for name in names if not hasattr(value, name)]
    if missing:
        raise ValueError(f"{label} is missing {', '.join(missing)}")
    return value


def _keys(row, names: tuple[str, ...], label: str) -> dict:
    if not isinstance(row, Mapping):
        raise ValueError(f"{label} must be a mapping in the shape read_history returns")
    missing = [name for name in names if name not in row]
    if missing:
        raise ValueError(f"{label} is missing {', '.join(missing)}")
    return dict(row)


def _offset_text(offset: timedelta) -> str:
    """A UTC offset as `%aI` spells it: `+00:00`, `+05:30`, `-08:00`."""
    total = int(offset.total_seconds()) // 60
    sign = "-" if total < 0 else "+"
    hours, minutes = divmod(abs(total), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def _author_date(raw) -> tuple[datetime, str, str]:
    """The git `%aI` author date, parsed, plus its original text and its offset.

    The text and the offset are kept exactly as git printed them because the parsed
    instant is normalized to UTC by `model.Instant`, and a repository's own spelling
    of when something happened is evidence that normalization would erase.
    """
    original = _text(raw, "commit author date")
    try:
        parsed = datetime.fromisoformat(original)
    except ValueError as error:
        raise ValueError("A commit author date must be the ISO-8601 text git's %aI prints") from error
    offset = parsed.utcoffset()
    if offset is None:
        raise ValueError("A commit author date must carry its own UTC offset")
    return parsed, original, _offset_text(offset)


# --------------------------------------------------------------- native rows


@dataclass(frozen=True, slots=True)
class NativeCommitRow:
    """One `add_commits` row, carried as canonical JSON.

    JSON rather than a mapping so the bundle stays immutable and two runs of the same
    inputs compare equal. `row` rebuilds what `store.code.add_commits` takes.
    """

    native_id: str
    row_json: str

    def __post_init__(self) -> None:
        _text(self.native_id, "native commit id")
        row = json.loads(self.row_json)
        if not isinstance(row, dict) or row.get("id") != self.native_id:
            raise ValueError("A native commit row must be an object identified by its own native ID")
        if "embedding" in row:
            raise ValueError("Vectors are added outside this boundary")

    @property
    def native_kind(self) -> Literal["Commit"]:
        return "Commit"

    @property
    def row(self) -> dict:
        return json.loads(self.row_json)


@dataclass(frozen=True, slots=True)
class NativeModifies:
    """One `add_modifies` row: which commit's diff landed inside which symbol."""

    commit_id: str
    symbol_id: str
    omega: float
    hunk_json: str

    def __post_init__(self) -> None:
        _text(self.commit_id, "commit id")
        _text(self.symbol_id, "symbol id")
        if type(self.omega) is not float:
            raise ValueError("A MODIFIES weight must be an explicit float")
        if not isinstance(json.loads(self.hunk_json), dict):
            raise ValueError("A MODIFIES hunk must be a JSON object")

    @property
    def row(self) -> dict:
        return {
            "commit_id": self.commit_id,
            "symbol_id": self.symbol_id,
            "omega": self.omega,
            "hunk": json.loads(self.hunk_json),
        }


# ------------------------------------------------------------ bound commits


@dataclass(frozen=True, slots=True)
class BoundCommitPassage:
    """One synthesized commit passage bound to the commit message it renders.

    The passage text is the message plus a `Touched:` line, so it is never byte
    identical to its original and always carries a view -- exactly the case
    `input_binding._view` exists for.
    """

    chunk: object
    generation: k.Generation
    span: k.EvidenceSpan
    view: k.RetrievalView
    derived_record: k.DerivedRecord
    derived_dependencies: tuple[k.DerivedDependency, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "derived_dependencies", tuple(self.derived_dependencies))
        if (
            type(self.generation) is not k.Generation
            or type(self.span) is not k.EvidenceSpan
            or type(self.view) is not k.RetrievalView
            or type(self.derived_record) is not k.DerivedRecord
            or any(type(edge) is not k.DerivedDependency for edge in self.derived_dependencies)
        ):
            raise ValueError("Commit passage bindings require exact immutable evidence types")
        chunk = _fields(self.chunk, _COMMIT_CHUNK_FIELDS, "Prepared commit passage")
        if self.generation.status != "staging":
            raise ValueError("Bound commit passages require a staging generation")
        if chunk.kind != "commit":
            raise ValueError(f"Passage kind {chunk.kind!r} is not a commit passage")
        if (self.view.span_id, self.view.source_revision_id, self.view.text, self.view.vector_profile) != (
            self.span.id,
            self.span.revision_id,
            chunk.text,
            self.generation.embedding_profile,
        ):
            raise ValueError("A rendered commit passage differs from its exact view binding")
        if self.view.derived_record_id != self.derived_record.id:
            raise ValueError("A commit view cites a derivation that is not its own")

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
    def retrieval_view_id(self) -> str:
        return self.view.id

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
class BoundCommit:
    """One commit's complete evidence, as one dependency group the writer can batch."""

    sha: str
    artifact: k.Artifact
    revision: k.ArtifactRevision
    knowledge_object: k.KnowledgeObject
    span: k.EvidenceSpan
    observation: k.ObjectObservation
    native_row: NativeCommitRow
    binding: k.NativeBinding
    member: k.GenerationMember
    passage: BoundCommitPassage | None

    def __post_init__(self) -> None:
        _text(self.sha, "commit sha")
        if (
            type(self.artifact) is not k.Artifact
            or type(self.revision) is not k.ArtifactRevision
            or type(self.knowledge_object) is not k.KnowledgeObject
            or type(self.span) is not k.EvidenceSpan
            or type(self.observation) is not k.ObjectObservation
            or type(self.native_row) is not NativeCommitRow
            or type(self.binding) is not k.NativeBinding
            or type(self.member) is not k.GenerationMember
        ):
            raise ValueError("A bound commit requires exact immutable record types")
        if self.passage is not None and type(self.passage) is not BoundCommitPassage:
            raise ValueError("A bound commit requires an exact immutable commit passage")
        if self.artifact.kind != "history_event" or self.knowledge_object.kind != "commit":
            raise ValueError("A bound commit is a history_event artifact and a commit object")
        if self.revision.artifact_id != self.artifact.id or self.revision.provider_revision != self.sha:
            raise ValueError("A commit revision must belong to its own history_event artifact")
        if self.span.revision_id != self.revision.id:
            raise ValueError("A commit message span must sit on its own commit revision")
        if (self.observation.object_id, self.observation.revision_id, self.observation.span_id) != (
            self.knowledge_object.id,
            self.revision.id,
            self.span.id,
        ):
            raise ValueError("A commit observation must cite its own object, revision and span")
        if (
            self.binding.object_id,
            self.binding.native_kind,
            self.binding.native_id,
            self.binding.span_id,
        ) != (
            self.knowledge_object.id,
            "Commit",
            self.native_row.native_id,
            self.span.id,
        ):
            raise ValueError("A commit binding must join its own object, native row and span")
        if self.member.artifact_revision_id != self.revision.id:
            raise ValueError("A commit membership must select its own commit revision")
        if self.passage is not None and self.passage.span != self.span:
            raise ValueError("A commit passage must render its own commit message span")

    @property
    def records(self) -> tuple:
        """This commit's typed evidence records, in dependency order."""
        if self.passage is None:
            return (self.span, self.observation)
        return (
            self.span,
            self.passage.derived_record,
            *self.passage.derived_dependencies,
            self.passage.view,
            self.observation,
        )


# ------------------------------------------------------------- the bundles


@dataclass(frozen=True, slots=True)
class CodeHistoryBundle:
    """One code generation's complete commit evidence, closed and self-consistent."""

    generation: k.Generation
    workspace_id: str
    rule_version: str
    coverage_json: str
    commits: tuple[BoundCommit, ...]
    modifies: tuple[NativeModifies, ...]
    precedes: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "commits", tuple(self.commits))
        object.__setattr__(self, "modifies", tuple(self.modifies))
        object.__setattr__(self, "precedes", tuple(tuple(pair) for pair in self.precedes))
        if any(type(item) is not BoundCommit for item in self.commits):
            raise ValueError("Code history requires exact immutable BoundCommit values")
        if any(type(row) is not NativeModifies for row in self.modifies):
            raise ValueError("Code history requires exact immutable NativeModifies values")
        _text(self.workspace_id, "workspace")
        if type(self.generation) is not k.Generation or self.generation.status != "staging":
            raise ValueError("Code history requires an immutable staging generation")
        if self.rule_version != CODE_HISTORY_RULE_VERSION:
            raise ValueError("Code history carries the current history rule version")
        if not isinstance(self.coverage, Mapping):
            raise ValueError("Code history carries its coverage as a JSON object")
        _check_inventory(
            ("commit shas", [item.sha for item in self.commits]),
            ("history_event artifacts", [item.artifact.id for item in self.commits]),
            ("commit revisions", [item.revision.id for item in self.commits]),
            ("commit objects", [item.knowledge_object.id for item in self.commits]),
            ("commit spans", [item.span.id for item in self.commits]),
            ("commit observations", [item.observation.id for item in self.commits]),
            ("native commit rows", [item.native_row.native_id for item in self.commits]),
            ("commit bindings", [item.binding.id for item in self.commits]),
            ("commit passages", [p.id for p in self.passages]),
            ("commit passage ordinals", [p.chunk.ordinal for p in self.passages]),
            ("MODIFIES edges", [(row.commit_id, row.symbol_id) for row in self.modifies]),
            ("PRECEDES pairs", list(self.precedes)),
        )
        self._check_scope()
        self._check_endpoints()

    # -------------------------------------------------------------- validation

    def _check_scope(self) -> None:
        for item in self.commits:
            if (item.artifact.workspace_id, item.artifact.source_id) != (
                self.workspace_id,
                self.generation.source_id,
            ):
                raise ValueError("A history_event artifact crosses the generation source or workspace")
            if item.knowledge_object.workspace_id != self.workspace_id:
                raise ValueError("A commit knowledge object crosses workspaces")
            if item.binding.generation_id != self.generation.id or item.member.generation_id != (
                self.generation.id
            ):
                raise ValueError("Code history crosses generations")
            if item.passage is not None and item.passage.generation != self.generation:
                raise ValueError("Code history crosses generations")

    def _check_endpoints(self) -> None:
        commits = {item.native_row.native_id for item in self.commits}
        for row in self.modifies:
            if row.commit_id not in commits:
                raise ValueError("A MODIFIES edge names a commit outside this history")
        for pair in self.precedes:
            if len(pair) != 2 or pair[0] == pair[1]:
                raise ValueError("A PRECEDES pair joins two distinct commits")
            if not set(pair) <= commits:
                raise ValueError("A PRECEDES pair names a commit outside this history")

    # ------------------------------------------------------------- projections

    @property
    def generation_id(self) -> str:
        return self.generation.id

    @property
    def source_id(self) -> str:
        return self.generation.source_id

    @property
    def coverage(self) -> dict:
        return json.loads(self.coverage_json)

    @property
    def artifacts(self) -> tuple[k.Artifact, ...]:
        return tuple(item.artifact for item in self.commits)

    @property
    def revisions(self) -> tuple[k.ArtifactRevision, ...]:
        return tuple(item.revision for item in self.commits)

    @property
    def objects(self) -> tuple[k.KnowledgeObject, ...]:
        return tuple(item.knowledge_object for item in self.commits)

    @property
    def spans(self) -> tuple[k.EvidenceSpan, ...]:
        return tuple(item.span for item in self.commits)

    @property
    def observations(self) -> tuple[k.ObjectObservation, ...]:
        return tuple(item.observation for item in self.commits)

    @property
    def passages(self) -> tuple[BoundCommitPassage, ...]:
        return tuple(item.passage for item in self.commits if item.passage is not None)

    @property
    def views(self) -> tuple[k.RetrievalView, ...]:
        return tuple(passage.view for passage in self.passages)

    @property
    def derived_records(self) -> tuple[k.DerivedRecord, ...]:
        return tuple(passage.derived_record for passage in self.passages)

    @property
    def derived_dependencies(self) -> tuple[k.DerivedDependency, ...]:
        return tuple(edge for passage in self.passages for edge in passage.derived_dependencies)

    @property
    def native_rows(self) -> tuple[NativeCommitRow, ...]:
        return tuple(item.native_row for item in self.commits)

    @property
    def bindings(self) -> tuple[k.NativeBinding, ...]:
        return tuple(item.binding for item in self.commits)

    @property
    def revision_members(self) -> tuple[k.GenerationMember, ...]:
        return tuple(item.member for item in self.commits)

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
    def evidence_members(self) -> tuple[k.GenerationEvidenceMember, ...]:
        return tuple(
            k.GenerationEvidenceMember(
                generation_id=self.generation.id,
                record_kind=type(record).__name__,
                record_id=record.id,
            )
            for record in self.records
        )


@dataclass(frozen=True, slots=True)
class MergedCodeBundle:
    """CC6's tree evidence and CC7's commit evidence as one inventory for the writer.

    Shaped like `code_binding.CodeEvidenceBundle` -- same field names, same
    projections -- rather than being one, because that type cannot hold this result:
    `NativeCodeRow` admits only `Symbol` and `DataObject` rows, and its membership
    check requires the revision members to be exactly the manifest, the tree and the
    accepted files. Both are deliberate there and neither is CC7's to change, so the
    union gets its own type and re-runs the same checks over the whole of it.
    """

    generation: k.Generation
    workspace_id: str
    rule_version: str
    chunk_rule_version: str
    history_rule_version: str
    configuration_json: str
    coverage_json: str
    repository_artifact: k.Artifact
    repository_revision: k.ArtifactRevision
    repository_object: k.KnowledgeObject
    repository_span: k.EvidenceSpan
    manifest_artifact: k.Artifact
    manifest_revision: k.ArtifactRevision
    accepted: tuple
    history_artifacts: tuple[k.Artifact, ...]
    history_revisions: tuple[k.ArtifactRevision, ...]
    objects: tuple[k.KnowledgeObject, ...]
    observations: tuple[k.ObjectObservation, ...]
    spans: tuple[k.EvidenceSpan, ...]
    views: tuple[k.RetrievalView, ...]
    derived_records: tuple[k.DerivedRecord, ...]
    derived_dependencies: tuple[k.DerivedDependency, ...]
    native_rows: tuple
    bindings: tuple[k.NativeBinding, ...]
    revision_members: tuple[k.GenerationMember, ...]
    evidence_members: tuple[k.GenerationEvidenceMember, ...]
    passages: tuple
    modifies: tuple[NativeModifies, ...]
    precedes: tuple[tuple[str, str], ...]
    commit_chunks: tuple = ()

    def __post_init__(self) -> None:
        for name in (
            "accepted",
            "history_artifacts",
            "history_revisions",
            "objects",
            "observations",
            "spans",
            "views",
            "derived_records",
            "derived_dependencies",
            "native_rows",
            "bindings",
            "revision_members",
            "evidence_members",
            "passages",
            "modifies",
            "commit_chunks",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "precedes", tuple(tuple(pair) for pair in self.precedes))
        if any(type(row) not in (NativeCodeRow, NativeCommitRow) for row in self.native_rows):
            raise ValueError("A merged native row must be a Symbol, DataObject or Commit row")
        if any(type(item) not in (BoundCodePassage, BoundCommitPassage) for item in self.passages):
            raise ValueError("A merged passage must be a bound code or commit passage")
        self._check_scope()
        self._check_inventory()
        self._check_membership()
        self._check_references()

    # -------------------------------------------------------------- validation

    def _check_scope(self) -> None:
        _text(self.workspace_id, "workspace")
        if type(self.generation) is not k.Generation or self.generation.status != "staging":
            raise ValueError("A merged code bundle requires an immutable staging generation")
        if self.rule_version != EXPECTED_CODE_BINDING_RULE_VERSION:
            raise ValueError("A merged code bundle carries the pinned binding rule version")
        if self.history_rule_version != CODE_HISTORY_RULE_VERSION:
            raise ValueError("A merged code bundle carries the current history rule version")
        _require_history_configuration(self.configuration)
        if not isinstance(self.coverage, Mapping):
            raise ValueError("A merged code bundle carries its coverage as a JSON object")
        crossing = {
            member.generation_id
            for member in (*self.revision_members, *self.evidence_members, *self.bindings)
        } | {passage.generation.id for passage in self.passages}
        if crossing - {self.generation.id}:
            raise ValueError("A merged code bundle crosses generations")
        if self.commit_chunks:
            raise ValueError("A merged code bundle leaves no commit passage unbound")

    def _check_inventory(self) -> None:
        _check_inventory(
            ("spans", [span.id for span in self.spans]),
            ("objects", [item.id for item in self.objects]),
            ("observations", [row.id for row in self.observations]),
            ("views", [view.id for view in self.views]),
            ("derived records", [record.id for record in self.derived_records]),
            ("derived dependencies", [edge.id for edge in self.derived_dependencies]),
            ("bindings", [binding.id for binding in self.bindings]),
            ("native rows", [(row.native_kind, row.native_id) for row in self.native_rows]),
            ("passages", [passage.id for passage in self.passages]),
            ("passage ordinals", [passage.chunk.ordinal for passage in self.passages]),
            ("revision members", [member.artifact_revision_id for member in self.revision_members]),
            ("MODIFIES edges", [(row.commit_id, row.symbol_id) for row in self.modifies]),
            ("PRECEDES pairs", list(self.precedes)),
        )

    def _check_membership(self) -> None:
        revisions = {member.artifact_revision_id for member in self.revision_members}
        expected = {
            self.repository_revision.id,
            self.manifest_revision.id,
            *(item.revision.id for item in self.accepted),
            *(revision.id for revision in self.history_revisions),
        }
        if revisions != expected:
            raise ValueError("Merged revision membership differs from its accepted inventory")
        if any(span.revision_id not in revisions for span in self.spans):
            raise ValueError("Merged revision membership must cover every original span")
        if any(row.revision_id not in revisions for row in self.observations):
            raise ValueError("Merged revision membership must cover every observation")
        if any(view.source_revision_id not in revisions for view in self.views):
            raise ValueError("Merged revision membership must cover every rendered view")
        if any(
            set(record.input_revision_ids) - revisions or record.input_binding_ids
            for record in self.derived_records
        ):
            raise ValueError("A merged derivation cites a revision outside the accepted inventory")
        expected_members = {(type(record).__name__, record.id) for record in self.records}
        actual = {(member.record_kind, member.record_id) for member in self.evidence_members}
        if (
            expected_members != actual
            or len(actual) != len(self.evidence_members)
            or len(expected_members) != len(self.records)
        ):
            raise ValueError("Merged exact membership differs from its immutable evidence inventory")

    def _check_references(self) -> None:
        spans = {span.id: span for span in self.spans}
        objects = {item.id for item in self.objects}
        views = {view.id for view in self.views}
        records = {record.id for record in self.derived_records}
        natives = {(row.native_kind, row.native_id) for row in self.native_rows}
        observed = {(row.object_id, row.span_id) for row in self.observations}
        if spans.get(self.repository_span.id) != self.repository_span:
            raise ValueError("The repository span is outside the merged span inventory")
        if self.repository_object.id not in objects:
            raise ValueError("The repository object is outside the merged object inventory")
        for row in self.observations:
            if row.object_id not in objects or row.span_id not in spans:
                raise ValueError("An observation cites an object or span outside the merged bundle")
            if row.revision_id != spans[row.span_id].revision_id:
                raise ValueError("An observation revision differs from its own span")
        for view in self.views:
            if view.span_id not in spans or view.derived_record_id not in records:
                raise ValueError("A rendered view cites a span or derivation outside the merged bundle")
        for edge in self.derived_dependencies:
            if edge.derived_record_id not in records or edge.input_kind != "span":
                raise ValueError("A derivation dependency must cite a span of its own record")
            if edge.input_id not in spans or edge.input_version != dependency_version(spans[edge.input_id]):
                raise ValueError("A derivation dependency differs from its exact original")
        if {(binding.native_kind, binding.native_id) for binding in self.bindings} != natives:
            raise ValueError("Every merged native row requires an evidence binding")
        for binding in self.bindings:
            if (binding.object_id, binding.span_id) not in observed:
                raise ValueError("A native binding object lacks a selected observation")
        for passage in self.passages:
            cited = passage.spans if type(passage) is BoundCodePassage else (passage.span,)
            if any(spans.get(span.id) != span for span in cited):
                raise ValueError("A passage cites a span outside the merged inventory")
            if passage.retrieval_view_id is not None and passage.retrieval_view_id not in views:
                raise ValueError("A rendered passage cites a view outside the merged inventory")
            _disjoint(cited)
        commits = {row.native_id for row in self.native_rows if row.native_kind == "Commit"}
        symbols = {row.native_id for row in self.native_rows if row.native_kind == "Symbol"}
        for row in self.modifies:
            if row.commit_id not in commits or row.symbol_id not in symbols:
                raise ValueError("A MODIFIES edge names an endpoint outside the merged bundle")
        for pair in self.precedes:
            if not set(pair) <= commits:
                raise ValueError("A PRECEDES pair names an endpoint outside the merged bundle")

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
    def coverage(self) -> dict:
        return json.loads(self.coverage_json)

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
        """Every accepted artifact/revision pair `generation_for_inputs` hashed.

        The `history_event` pairs are deliberately absent: plan section 6 settles the
        generation before `read_history` runs, so a commit can never be an identity
        input. The head SHA already puts the history's endpoint into identity as the
        repository revision's `provider_revision`. CC8's `code` accepted-input profile
        has to select exactly these pairs for its `generation_for_inputs` re-derivation
        even though the member set is larger.
        """
        return (
            (self.repository_artifact, self.repository_revision),
            (self.manifest_artifact, self.manifest_revision),
            *(item.pair for item in self.accepted),
        )

    @property
    def history_pairs(self) -> tuple[tuple[k.Artifact, k.ArtifactRevision], ...]:
        """The `history_event` pairs: generation members, never identity inputs."""
        return tuple(zip(self.history_artifacts, self.history_revisions, strict=True))


# ------------------------------------------------------------------ shared checks


def _check_inventory(*groups: tuple[str, list]) -> None:
    for label, identities in groups:
        if len(set(identities)) != len(identities):
            raise ValueError(f"Duplicate code history {label}")


def _disjoint(spans: tuple[k.EvidenceSpan, ...]) -> None:
    """One passage's own originals cannot cite one line twice.

    A commit passage has exactly one `field` span, which has no line range at all, so
    the check applies only to the `file_lines` closures `code_binding` produced.
    """
    ranges = sorted(
        (json.loads(span.locator_json)["start"], json.loads(span.locator_json)["end"])
        for span in spans
        if span.locator_kind == "file_lines"
    )
    if any(left[1] >= right[0] for left, right in zip(ranges, ranges[1:], strict=False)):
        raise ValueError("A passage cites one original line from two spans")


def _require_history_configuration(configuration) -> dict:
    """Ruling 10: the history rule version must be in the hashed configuration.

    Not folded in here. `generation_for_inputs` hashed the configuration before this
    module ever ran, and `generation_profiles.validate_generation_profile` re-derives
    generation identity from the accepted manifest's copy of it, so a key added after
    the fact would be provenance nobody checks. The coordinator sets it before it
    settles the generation; this refuses the build if it did not.
    """
    if not isinstance(configuration, Mapping):
        raise ValueError("A generation configuration must be a JSON object")
    recorded = configuration.get(HISTORY_CONFIGURATION_KEY)
    if recorded != CODE_HISTORY_RULE_VERSION:
        raise ValueError(
            f"Generation configuration must record {HISTORY_CONFIGURATION_KEY!r} = "
            f"{CODE_HISTORY_RULE_VERSION!r} before the generation is settled; found {recorded!r}"
        )
    return dict(configuration)


# ---------------------------------------------------------------- rendering


def _commit_view(chunk, generation: k.Generation, workspace_id: str, span: k.EvidenceSpan):
    """A projection over one commit message, as `input_binding._view` does for prose."""
    dependencies = (("span", span.id, dependency_version(span)),)
    profile = make_identity(
        "text_profile",
        [
            CODE_HISTORY_RULE_VERSION,
            list(chunk.chunker_profile),
            # A commit passage declares no original unit at all: it is rendered from the
            # commit record, so there is no decoder profile behind it.
            sorted({unit.decoder_profile for unit in chunk.original_units}),
            chunk.chunk_key,
        ],
    )
    fingerprint = view_fingerprint(
        view_kind="projection",
        text=chunk.text,
        text_profile=profile,
        vector_profile=generation.embedding_profile,
        rule_version=CODE_HISTORY_RULE_VERSION,
        model_version=None,
        dependencies=dependencies,
    )
    derived = k.DerivedRecord(
        workspace_id=workspace_id,
        view_kind="projection",
        rule_version=CODE_HISTORY_RULE_VERSION,
        input_revision_ids=(span.revision_id,),
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
        span_id=span.id,
        source_revision_id=span.revision_id,
        view_kind="projection",
        text=chunk.text,
        text_profile=profile,
        vector_profile=generation.embedding_profile,
        derivation_version=CODE_HISTORY_RULE_VERSION,
        dependency_fingerprint=fingerprint,
        derived_record_id=derived.id,
    )
    return view, derived, edges


# ------------------------------------------------------------------ records


def _repository_external_id(repository, source_id: str) -> str:
    """What `code_binding` calls this repository, recomputed from the descriptor.

    Plan ruling 4 and design review M8: a checkout's identity is its whole normalized
    clone path. An archive, a single file or a checkout captured without a clone URL
    falls back to plan section 5's source-scoped key.
    """
    if repository is None:
        return f"source:{source_id}"
    descriptor = _fields(repository, ("provider_instance", "provider_repository_id"), "Repository descriptor")
    return f"{descriptor.provider_instance}/{descriptor.provider_repository_id}"


def _commit_records(
    row,
    *,
    external_id,
    workspace_id,
    source_id,
    policy_id,
    observed_at,
    repository_object_id,
    stored=None,
):
    """One commit's artifact, revision, object, message span and observation."""
    sha = _text(row["sha"], "commit sha")
    author = row["author"] if isinstance(row["author"], str) else ""
    message = row["message"] if isinstance(row["message"], str) else ""
    ordinal = row["ordinal"]
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("A commit ordinal must be its nonnegative position in the walk")
    updated_at, original, timezone_text = _author_date(row["date"])

    artifact = k.Artifact(
        workspace_id=workspace_id,
        source_id=source_id,
        kind="history_event",
        external_id=f"{external_id}@{sha}",
        canonical_uri=f"{external_id}@{sha}",
        policy_id=policy_id,
    )
    # A commit has no captured raw object: what identifies its content is the metadata
    # git reported for it. `ordinal` is deliberately excluded -- a walk position is not
    # commit content, and a budget skip above this commit must not restate its identity.
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        provider_revision=sha,
        content_hash=text_hash(canonical_json([sha, author, original, message])),
        raw_uri=f"{COMMIT_RAW_URI_SCHEME}{sha}",
        source_updated_at=updated_at,
        source_timestamp_original=original,
        source_timezone=timezone_text,
        source_precision="second",
        observed_at=observed_at,
        lifecycle="active",
    )
    # A commit's revision identity is its sha and its metadata hash, so the second
    # generation of one repository derives the *same* revision for a commit it already
    # holds. `observed_at` is when that commit was first observed, exactly as
    # `code_binding._reuse` treats a file revision.
    revision = _reuse(revision, stored)
    knowledge_object = k.KnowledgeObject(
        workspace_id=workspace_id,
        kind="commit",
        canonical_key=canonical_json([repository_object_id, sha]),
    )
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="field",
        locator_json=canonical_json(
            k.FieldLocator(field_path=COMMIT_MESSAGE_FIELD_PATH).model_dump(mode="json")
        ),
        text=message,
        policy_id=policy_id,
    )
    observation = k.ObjectObservation(
        object_id=knowledge_object.id,
        revision_id=revision.id,
        span_id=span.id,
        attributes_json=canonical_json({"sha": sha, "author": author, "ordinal": ordinal}),
        evidence_class=COMMIT_EVIDENCE_CLASS,
        valid_from=updated_at,
        valid_to=None,
        recorded_from=observed_at,
        recorded_to=None,
        source_timestamp_original=original,
        source_timezone=timezone_text,
        **_COMMIT_INTERVAL,
    )
    return artifact, revision, knowledge_object, span, observation


# ---------------------------------------------------------------- the boundary


def bind_history(
    history,
    *,
    code_bundle: CodeEvidenceBundle,
    repository,
    workspace_id: str,
    source_id: str,
    generation_id: str,
    generation_namespace: str,
    observed_at: datetime,
    history_depth: int,
    shallow_boundary,
    stored_revisions: Mapping[str, k.ArtifactRevision] | None = None,
) -> CodeHistoryBundle:
    """Bind one `read_history` walk to the generation `code_bundle` already settled.

    Every scope argument is also derivable from `code_bundle`; they are taken anyway
    and checked against it, the way `code_binding.materialize_code_evidence` recomputes
    the generation it was handed. A caller that believes it is binding a different
    generation, namespace, workspace, source or repository than the bundle holds has a
    bug, and a redundant argument that is checked is how it is caught here rather than
    at the seal.

    Nothing here writes, authorizes or publishes. A successful return says only that
    the commit inventory is internally exact.
    """
    if type(code_bundle) is not CodeEvidenceBundle:
        raise ValueError("Code history requires CC6's immutable code evidence bundle")
    if code_bundle.rule_version != EXPECTED_CODE_BINDING_RULE_VERSION:
        raise ValueError(
            f"The code evidence bundle carries binding rule version {code_bundle.rule_version!r}; "
            f"this history is pinned to {EXPECTED_CODE_BINDING_RULE_VERSION!r}"
        )
    walked = _fields(history, _HISTORY_FIELDS, "History")
    if type(observed_at) is not datetime or observed_at.utcoffset() is None:
        raise ValueError("The capture instant must be an explicit timezone-aware datetime")

    generation = code_bundle.generation
    _text(workspace_id, "workspace")
    _text(source_id, "source")
    if workspace_id != code_bundle.workspace_id:
        raise ValueError("Code history binds another workspace than its code evidence")
    if source_id != code_bundle.source_id:
        raise ValueError("Code history binds another source than its code evidence")
    if generation_id != generation.id:
        raise ValueError("Code history binds another generation than its code evidence")
    if generation_namespace != _namespace_of(generation):
        raise ValueError("Code history binds another generation namespace than its code evidence")
    _require_history_configuration(code_bundle.configuration)
    if observed_at != generation.created_at:
        raise ValueError("Code history requires the one capture instant its generation was settled at")

    external_id = _repository_external_id(repository, source_id)
    if external_id != code_bundle.repository_artifact.external_id:
        raise ValueError("The history repository differs from the repository the code evidence bound")

    if type(history_depth) is not int or history_depth < 0:
        raise ValueError("The configured history depth must be a nonnegative integer")
    boundary = tuple(sorted({_text(sha, "shallow boundary sha") for sha in (shallow_boundary or ())}))
    rows = list(walked.commits)
    if history_depth == 0 and rows:
        raise ValueError("A disabled history cannot carry commits; history_depth is 0")
    if history_depth and len(rows) > history_depth:
        raise ValueError("A history holds more commits than its configured depth allows")

    commits = _bind_commits(
        rows,
        code_bundle=code_bundle,
        external_id=external_id,
        workspace_id=workspace_id,
        source_id=source_id,
        generation_namespace=generation_namespace,
        observed_at=observed_at,
        stored_revisions=stored_revisions,
    )
    coverage = {
        "history": "disabled" if history_depth == 0 else "read",
        # Design review m4: `git log --first-parent` never sees a merged side branch, so
        # this walk is a restriction of the repository's history and says so, always.
        "history_walk": HISTORY_WALK,
        "history_depth": history_depth,
        "history_commits": len(commits),
        "history_skipped": int(walked.skipped),
        "history_truncated": bool(walked.truncated),
        "history_shallow_boundary": list(boundary),
        # `read_history` follows renames with `-M` but exposes no rename inventory on
        # `History`, so there is nothing honest to record beyond that absence.
        "history_renames": "not_reported",
    }
    return CodeHistoryBundle(
        generation=generation,
        workspace_id=workspace_id,
        rule_version=CODE_HISTORY_RULE_VERSION,
        coverage_json=canonical_json(coverage),
        commits=commits,
        modifies=_bind_modifies(walked.modifies, code_bundle=code_bundle, commits=commits),
        precedes=tuple(tuple(pair) for pair in walked.precedes),
    )


def _bind_commits(
    rows,
    *,
    code_bundle,
    external_id,
    workspace_id,
    source_id,
    generation_namespace,
    observed_at,
    stored_revisions=None,
) -> tuple[BoundCommit, ...]:
    # Imported here rather than at module scope: `hippo.codegraph`'s package body loads
    # the tree-sitter walkers, and no knowledge import should pay for a parser it never
    # uses. `codegraph.model` itself is pure.
    from ..codegraph.model import commit_id

    policy_id = code_bundle.repository_artifact.policy_id
    generation = code_bundle.generation
    chunks = _commit_chunks(code_bundle)
    built: list[BoundCommit] = []
    for row in rows:
        row = _keys(row, _COMMIT_FIELDS, "A read_history commit row")
        sha = _text(row["sha"], "commit sha")
        if row["source_id"] != source_id:
            raise ValueError("A read_history commit row belongs to another source")
        native_id = commit_id(source_id, sha, node_namespace=generation_namespace)
        if row["id"] != native_id:
            raise ValueError("A native commit ID does not match the generation namespace")
        artifact, revision, knowledge_object, span, observation = _commit_records(
            row,
            external_id=external_id,
            workspace_id=workspace_id,
            source_id=source_id,
            policy_id=policy_id,
            observed_at=observed_at,
            repository_object_id=code_bundle.repository_object.id,
            stored=stored_revisions,
        )
        native_row = NativeCommitRow(
            native_id,
            canonical_json(
                {
                    "id": native_id,
                    "source_id": source_id,
                    "generation_id": generation.id,
                    "sha": sha,
                    "author": row["author"],
                    "date": row["date"],
                    "message": row["message"],
                    "ordinal": row["ordinal"],
                }
            ),
        )
        chunk = chunks.pop(native_id, None)
        passage = None
        if chunk is not None:
            if chunk.commit_sha != sha:
                raise ValueError("A prepared commit passage names another commit's SHA")
            view, derived, edges = _commit_view(chunk, generation, workspace_id, span)
            passage = BoundCommitPassage(chunk, generation, span, view, derived, edges)
        built.append(
            BoundCommit(
                sha=sha,
                artifact=artifact,
                revision=revision,
                knowledge_object=knowledge_object,
                span=span,
                observation=observation,
                native_row=native_row,
                binding=k.NativeBinding(
                    generation_id=generation.id,
                    object_id=knowledge_object.id,
                    native_kind="Commit",
                    native_id=native_id,
                    span_id=span.id,
                ),
                member=k.GenerationMember(generation_id=generation.id, artifact_revision_id=revision.id),
                passage=passage,
            )
        )
    if chunks:
        raise ValueError("A prepared commit passage names a commit this history does not hold")
    return tuple(built)


def _commit_chunks(code_bundle) -> dict:
    """CC6's passed-through commit passages, by the commit each one renders."""
    out: dict = {}
    for chunk in code_bundle.commit_chunks:
        chunk = _fields(chunk, _COMMIT_CHUNK_FIELDS, "Prepared commit passage")
        if chunk.kind != "commit":
            raise ValueError(f"Passage kind {chunk.kind!r} is not a commit passage")
        identity = _text(chunk.commit_id, "commit passage identity")
        if identity in out:
            raise ValueError("Two prepared passages render one commit")
        out[identity] = chunk
    return out


def _bind_modifies(rows, *, code_bundle, commits) -> tuple[NativeModifies, ...]:
    """`read_history`'s MODIFIES rows, restricted to this generation's own endpoints.

    An edge whose symbol has no native row in `code_bundle` is **refused, never
    dropped**: a silent drop loses a commit's attribution without telling anyone, and
    `native_mutation` would reject the write anyway with "Missing shared graph
    endpoint". CC6's finding 10 is the case to watch -- a symbol whose rendered body is
    only whitespace produces no passage and therefore no native row, so the coordinator
    must subtract that complement from the walk and record it in `coverage_json` before
    calling here.
    """
    known_commits = {item.native_row.native_id for item in commits}
    known_symbols = {row.native_id for row in code_bundle.native_rows if row.native_kind == "Symbol"}
    built = []
    for row in rows:
        row = _keys(row, _MODIFIES_FIELDS, "A read_history MODIFIES row")
        if row["commit_id"] not in known_commits:
            raise ValueError("A MODIFIES edge names a commit outside this history")
        if row["symbol_id"] not in known_symbols:
            raise ValueError("A MODIFIES edge names a symbol outside this generation")
        built.append(
            NativeModifies(
                commit_id=row["commit_id"],
                symbol_id=row["symbol_id"],
                omega=float(row["omega"]),
                hunk_json=canonical_json(row["hunk"] or {}),
            )
        )
    return tuple(built)


def merge_code_bundles(code_bundle: CodeEvidenceBundle, history_bundle: CodeHistoryBundle):
    """Union CC6's tree evidence and CC7's commit evidence into the writer's input.

    The union is revalidated rather than trusted: each half closed over itself, but
    only here is it provable that the two describe one generation, that no record is
    duplicated across them, that no native row lost its binding, that every cited
    original line is still covered exactly once and that every `MODIFIES` and
    `PRECEDES` endpoint exists.
    """
    if type(code_bundle) is not CodeEvidenceBundle:
        raise ValueError("A merge requires CC6's immutable code evidence bundle")
    if type(history_bundle) is not CodeHistoryBundle:
        raise ValueError("A merge requires this module's immutable code history bundle")
    if code_bundle.generation != history_bundle.generation:
        raise ValueError("The code evidence and code history describe different generations")
    if code_bundle.workspace_id != history_bundle.workspace_id:
        raise ValueError("The code evidence and code history belong to different workspaces")
    return MergedCodeBundle(
        generation=code_bundle.generation,
        workspace_id=code_bundle.workspace_id,
        rule_version=code_bundle.rule_version,
        chunk_rule_version=code_bundle.chunk_rule_version,
        history_rule_version=history_bundle.rule_version,
        configuration_json=code_bundle.configuration_json,
        coverage_json=history_bundle.coverage_json,
        repository_artifact=code_bundle.repository_artifact,
        repository_revision=code_bundle.repository_revision,
        repository_object=code_bundle.repository_object,
        repository_span=code_bundle.repository_span,
        manifest_artifact=code_bundle.manifest_artifact,
        manifest_revision=code_bundle.manifest_revision,
        accepted=code_bundle.accepted,
        history_artifacts=history_bundle.artifacts,
        history_revisions=history_bundle.revisions,
        objects=(*code_bundle.objects, *history_bundle.objects),
        observations=(*code_bundle.observations, *history_bundle.observations),
        spans=(*code_bundle.spans, *history_bundle.spans),
        views=(*code_bundle.views, *history_bundle.views),
        derived_records=(*code_bundle.derived_records, *history_bundle.derived_records),
        derived_dependencies=(
            *code_bundle.derived_dependencies,
            *history_bundle.derived_dependencies,
        ),
        native_rows=(*code_bundle.native_rows, *history_bundle.native_rows),
        bindings=(*code_bundle.bindings, *history_bundle.bindings),
        revision_members=(*code_bundle.revision_members, *history_bundle.revision_members),
        evidence_members=(*code_bundle.evidence_members, *history_bundle.evidence_members),
        passages=(*code_bundle.passages, *history_bundle.passages),
        modifies=history_bundle.modifies,
        precedes=history_bundle.precedes,
    )
