"""Explicit managed code builds: convert, refresh and resume one repository.

No production ingestion route calls this module; `managed_activation` dispatches to
it. Source management authority is required, raw objects are retained on every
outcome, and nothing here activates a route on its own.

Why a second coordinator rather than a wider `build_plain_source` (plan section 3):
a prose bootstrap is one detached commit with no durable reservation, while a
repository bootstrap is durable staging over many transactions with a resume, and
the prose lane refuses code by contract at three reviewed seams. The two share
`BuildActor`, `BuildAuthority`, `LeaseHeartbeat`, `RawArtifactStore` and
`build_run.BuildRun`/`BuildReceipt`, so neither owns the other's failure latch.

The order of preparation is plan section 6's, and it is forced (CC6 finding 2):
generation identity depends only on the accepted tree and the configuration, while
the code graph's native IDs depend on the generation namespace. So capture settles
the accepted inputs, `code_binding.code_generation` settles identity, and only then
are the walkers, the history walk, the chunker and the binding run inside that
namespace.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path

from ..codegraph.extract import extract_code
from ..codegraph.git_history import History, HistoryError, read_history, shallow_boundary
from ..codegraph.model import CODE_MAX_FILES, CODE_MAX_SYMBOLS_PER_SOURCE
from ..codegraph.syntax_cache import SCHEMA_VERSION, WALKER_RULES_VERSION, parser_profile
from ..hipporag.preparation import enters_synonym_search, name_text_of
from ..knowledge import code_binding, code_history, staged_code
from ..knowledge import model as k
from ..knowledge.access import AuthorizationChanged
from ..knowledge.build_authority import (
    MANAGED_CODE_SCOPE,
    AcceptedBuildInputs,
    BuildActor,
    capture_build_authority,
)
from ..knowledge.embedding_cache import EmbeddingCache
from ..knowledge.embedding_profile import (
    EmbeddingSpec,
    ProfiledEmbeddings,
    resolve_embedding_profile,
    validate_profile_descriptor,
)
from ..knowledge.generation_profiles import CODE_PROFILE, GENERATION_PROFILE_KEY
from ..knowledge.identity import canonical_json, normalize_relative_path
from ..knowledge.inputs import CaptureLimits
from ..knowledge.lifecycle import generation_namespace
from ..knowledge.raw_artifacts import RawArtifact
from ..store.generation_counts import generation_counts
from .build_run import (
    BuildBusy,
    BuildCancelled,
    BuildProgress,  # noqa: F401  -- re-exported for the code lane's callers, as prose does
    BuildReceipt,  # noqa: F401  -- same
    BuildRun,
    adopt_capture_instant,
    authority_fields,
    credentials,
    operation_generation,
    prior_receipt,
    published_receipt,
    rebaseline_between_batches,
)
from .code_provenance import CodeProvenance, CodeUnit, read_code_provenance
from .prepared_code_chunks import CapturedCode, CodeChunkSettings, prepare_code_chunks
from .provenance import read_plain_provenance
from .readers import TextBudget, is_plain_prose_name
from .repo_capture import capture_repository_inputs, walk_tree

# What the generation records about the derivation that produced it. Bumped when the
# coordinator's own composition changes what a build would produce; the preparation
# modules carry their own rule versions and fold them in separately (ruling 10).
CODE_PIPELINE_VERSION = "managed-code-v1"
CODE_PARSER_VERSION = "managed-code-v1"
CODE_LINKER_VERSION = "managed-code-linker-v1"

# The one reserved top-level configuration key this module owns. CC4 owns `capture`,
# CC6 owns `code_derivation` and CC7 owns `code_history_derivation`; a caller cannot
# set any of them (each of those seams refuses a caller that does).
CODE_CONFIGURATION_KEY = "code"

# The grammars `syntax_cache.parser_profile` knows a distribution for, hand-copied for
# the reason `code_provenance.CODE_LANGUAGES` is: deriving the tuple would import the
# walker registry here. A grammar added without updating this tuple would leave its
# version out of generation identity, so a test pins the tuple against the registry and
# fails closed on a seventh.
CODE_GRAMMARS = ("csharp", "go", "python", "rust", "tsx", "typescript")

# The lane's own operator-facing wording for the shared run (CC9a's two arguments).
CANCELLED_MESSAGE = "Code source build cancelled"
RENEWAL_FAILED_MESSAGE = "Code build lease renewal failed"

# Plan section 4: no code, config or unparsed file is sent to a chat model, so every
# captured file records why it was not extracted. `prose_extraction_deferred` is the
# named deferral of ruling 5 (see the module note below).
OPENIE_SKIPPED = "skipped"
OPENIE_CODE = "code"
OPENIE_UNPARSED = "unparsed"
OPENIE_PROSE_DEFERRED = "prose_extraction_deferred"

# Ruling 5 says a `readers.PROSE_EXTENSIONS` file inside a captured tree goes through
# the shared prose preparation *and* receives OpenIE. The first half is done here: the
# file is captured, decoded through `read_plain_provenance` and chunked through
# `prepare_code_chunks`' reviewed prose branch, so a README.md is evidence like any
# other passage. The second half is not reachable from this slice --
# `code_binding.CodeEvidenceBundle` and `code_history.MergedCodeBundle` carry no
# `ProseExtraction` field and `staged_code._inventory` refuses one outright ("A code
# generation produces no prose extraction") -- so the extraction is deferred, recorded
# per file in `coverage_json`, and the widening is a later slice's (orchestrator
# ruling, 2026-09-12).


class CodeBuildRefused(ValueError):
    """This tree cannot be built as one managed code generation."""


def _positive(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True)
class CodeTreeInput:
    """The checkout, archive or single code file one build captures.

    `paths`, when given, is the ordered tuple of normalized relative paths to capture;
    everything else the walk accepts becomes a configured exclusion, so the restriction
    enters generation identity through CC4's reserved `capture` key rather than
    silently shrinking the tree. `None` means "capture the whole walk".
    """

    root: Path
    paths: tuple[str, ...] | None = None
    kind: str = "repo"
    repository: object | None = None
    head_revision: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        if not self.root.is_absolute():
            raise ValueError("A captured tree needs an absolute root")
        if self.kind not in ("repo", "archive", "file"):
            raise ValueError("Unknown capture source kind")
        if self.paths is not None:
            paths = tuple(self.paths)
            if not paths or any(type(item) is not str for item in paths):
                raise ValueError("Requested capture paths must be a nonempty tuple of relative paths")
            normalized = tuple(normalize_relative_path(item) for item in paths)
            if normalized != tuple(sorted(set(normalized))):
                raise ValueError("Requested capture paths must be normalized, ordered and unique")
            object.__setattr__(self, "paths", normalized)
        if self.kind != "repo" and (self.repository is not None or self.head_revision is not None):
            raise ValueError("Only a checkout carries a repository descriptor and a head revision")
        if self.head_revision is not None and (
            type(self.head_revision) is not str or not self.head_revision.strip()
        ):
            raise ValueError("A head revision must be explicit text")

    @property
    def is_repository(self) -> bool:
        return self.kind == "repo"


@dataclass(frozen=True)
class CodeBuildOptions:
    """Two groups, and the split is the point (plan sections 3, 5 and 8.3).

    The first group changes what a generation *is*, so every field of it is hashed
    into `configuration`. The second group is scheduling and safety: batch size,
    leases, workers, the ceilings and the git budgets, none of which may change a
    record, and a test proves the worker count, the clone depth, progress and the
    capture instant stay out of identity.
    """

    # --- input-affecting: hashed into generation identity
    chunk_size_chars: int = 1500
    chunk_overlap_chars: int = 150
    synonymy_threshold: float = 0.8
    history_depth: int = 25
    exclusions: tuple[str, ...] = ()
    allow_empty: bool = False
    # --- operational: never hashed
    capture_limits: CaptureLimits = field(
        default_factory=lambda: CaptureLimits(
            max_input_bytes=2_000_000,
            max_total_bytes=512_000_000,
            # CC4 finding 10: every declined file is a disposition in the canonical
            # manifest, so both rails must cover accepted PLUS excluded entries.
            max_inputs=3 * CODE_MAX_FILES,
            max_manifest_bytes=32_000_000,
        )
    )
    max_decoded_chars: int = 8_000_000
    max_files: int = CODE_MAX_FILES
    max_file_bytes: int = 2_000_000
    max_symbols: int = CODE_MAX_SYMBOLS_PER_SOURCE
    max_chunks: int = 20_000
    max_batch_payload_bytes: int = staged_code.PAYLOAD_CEILING_BYTES
    batch_size: int = 128
    checkpoint_interval: int = 1
    workers: int = 2
    git_timeout_seconds: int = 20
    history_total_seconds: int = 120
    lease_duration_seconds: float = 300.0
    renewal_interval_seconds: float = 30.0

    def __post_init__(self) -> None:
        for name in (
            "chunk_size_chars",
            "max_decoded_chars",
            "max_files",
            "max_file_bytes",
            "max_symbols",
            "max_chunks",
            "max_batch_payload_bytes",
            "batch_size",
            "checkpoint_interval",
            "workers",
            "git_timeout_seconds",
            "history_total_seconds",
        ):
            _positive(getattr(self, name), "Code build limits")
        if type(self.chunk_overlap_chars) is not int or self.chunk_overlap_chars < 0:
            raise ValueError("Chunk overlap must be a nonnegative integer")
        if type(self.history_depth) is not int or self.history_depth < 0:
            raise ValueError("History depth must be a nonnegative integer")
        if type(self.allow_empty) is not bool or type(self.capture_limits) is not CaptureLimits:
            raise ValueError("Invalid captured code options")
        if (
            type(self.synonymy_threshold) not in (int, float)
            or not math.isfinite(self.synonymy_threshold)
            or not 0 <= self.synonymy_threshold <= 1
        ):
            raise ValueError("Invalid synonym threshold")
        exclusions = tuple(self.exclusions)
        if any(type(item) is not str for item in exclusions):
            raise ValueError("The exclusion policy must be relative paths")
        object.__setattr__(
            self, "exclusions", tuple(sorted({normalize_relative_path(p) for p in exclusions}))
        )
        if self.max_batch_payload_bytes > staged_code.PAYLOAD_CEILING_BYTES:
            raise ValueError("The per-batch payload ceiling cannot exceed the staged writer's own")
        for value in (self.lease_duration_seconds, self.renewal_interval_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Build lease intervals must be finite and positive")
        if self.renewal_interval_seconds >= self.lease_duration_seconds / 2:
            raise ValueError("Build renewal must precede lease expiry")

    @property
    def chunk_settings(self) -> CodeChunkSettings:
        return CodeChunkSettings(size_chars=self.chunk_size_chars, overlap_chars=self.chunk_overlap_chars)


# ----------------------------------------------------------------- configuration


def _grammar_profiles() -> dict:
    """Every grammar a walker could use, with the distribution versions behind it.

    Plan section 5 puts `syntax_cache.parser_profile(grammar)` into identity for every
    grammar used, so a tree-sitter or grammar upgrade is a new generation rather than a
    silent re-derivation. The whole table is recorded rather than only the grammars this
    tree happened to reach: which languages a repository contains is data, not
    configuration, and a per-tree table would make one configuration hash two things.
    """
    return {
        name: ([list(item) for item in profile] if (profile := parser_profile(name)) else None)
        for name in CODE_GRAMMARS
    }


def _configuration(embedding, options: CodeBuildOptions) -> dict:
    """The input-affecting configuration, and nothing operational (plan section 5)."""
    settings = options.chunk_settings
    return {
        "embedding_profile": embedding.descriptor(),
        GENERATION_PROFILE_KEY: CODE_PROFILE,
        # CC7's key is top-level and set before `code_generation`, so it is hashed;
        # `merge_code_bundles` refuses a generation whose configuration omits it.
        code_history.HISTORY_CONFIGURATION_KEY: code_history.CODE_HISTORY_RULE_VERSION,
        CODE_CONFIGURATION_KEY: {
            "rule": CODE_PIPELINE_VERSION,
            "chunk_size_chars": settings.effective_size,
            "chunk_overlap_chars": settings.effective_overlap,
            "chunker_profile": list(settings.profile),
            "synonymy_threshold": options.synonymy_threshold,
            "synonym_rule": "hipporag-cosine-top100-v1",
            "history_depth": options.history_depth,
            "allow_empty": options.allow_empty,
            "openie": OPENIE_SKIPPED,
            "walker_rules_version": WALKER_RULES_VERSION,
            "syntax_schema_version": SCHEMA_VERSION,
            "parser_profiles": _grammar_profiles(),
        },
    }


# ----------------------------------------------------------------- capture and reading


def _capture(run, tree: CodeTreeInput, options: CodeBuildOptions, raw_store, configuration, observed_at):
    """Walk, bound and canonically capture the tree; every later read is from the raw object."""
    control = run.guard.source_control
    exclusions = options.exclusions
    if tree.paths is not None:
        inventory = walk_tree(
            tree.root,
            exclusions=exclusions,
            max_files=options.max_files,
            max_file_bytes=options.max_file_bytes,
        )
        accepted = {item.logical_path for item in inventory.inputs}
        if not set(tree.paths) <= accepted:
            raise CodeBuildRefused("A requested capture path is not a capturable file of this tree")
        exclusions = tuple(sorted({*exclusions, *(accepted - set(tree.paths))}))
    return capture_repository_inputs(
        tree.root,
        raw_store=raw_store,
        source_id=control.source_id,
        workspace_id=control.workspace_id,
        limits=options.capture_limits,
        configuration=configuration,
        observed_at=observed_at,
        exclusions=exclusions,
        provider_revision=tree.head_revision,
        repository=tree.repository,
        max_files=options.max_files,
        max_file_bytes=options.max_file_bytes,
        should_stop=lambda: (run.check(), False)[1],
    )


def _unit(raw, data, budget) -> tuple[CodeProvenance, str]:
    """One captured file's provenance, and why it will not be extracted.

    `read_code_provenance` refuses a `readers.PROSE_EXTENSIONS` name by contract, so a
    README.md inside a checkout is decoded through the plain reader and wrapped in the
    same `CodeUnit` the code reader would have produced for an unparsed file. That is
    exactly the shape `prepare_code_chunks` sends down its reviewed prose branch; it
    carries no grammar, so it is never parsed and never sent to a model here.
    """
    if not is_plain_prose_name(raw.logical_path):
        provenance = read_code_provenance(
            raw, data, name=raw.logical_path, path=raw.logical_path, budget=budget
        )
        reason = OPENIE_CODE if provenance.unit is not None and provenance.unit.is_code else OPENIE_UNPARSED
        return provenance, reason
    read = read_plain_provenance(raw, data, name=raw.logical_path, path=raw.logical_path, budget=budget)
    if read.outcome != "text":
        return CodeProvenance(read.outcome, None, None, read), OPENIE_PROSE_DEFERRED
    unit = CodeUnit(
        input_key=raw.input_key,
        logical_path=raw.logical_path,
        language=None,
        is_code=False,
        parsable=False,
        original=read.original_units[0],
        document=read.documents[0],
    )
    return CodeProvenance("text", None, unit, read), OPENIE_PROSE_DEFERRED


def _read(run, captured, raw_store, options: CodeBuildOptions):
    """Decode every accepted file from its captured raw object, in canonical order."""
    run.progress("reading")
    budget = TextBudget(limit=options.max_decoded_chars)
    units, reasons = [], {}
    for raw in captured.accepted.inputs:
        run.check()
        data = raw_store.read_bytes(RawArtifact(raw.raw_uri, raw.raw_hash, raw.byte_length))
        run.check()
        provenance, reason = _unit(raw, data, budget)
        units.append(CapturedCode(raw, provenance))
        reasons[raw.logical_path] = reason
    return tuple(units), reasons


# ----------------------------------------------------------------- preparation


def _history(run, tree: CodeTreeInput, facts, options: CodeBuildOptions, namespace):
    """`read_history` against the captured checkout (plan section 6 step 5, section 9).

    The legacy `pipeline._read_history` / `indexer._write_code_graph` pair is never used
    for a managed source: its rows are untagged, and these carry the generation and its
    namespace. A tree with no repository, and a build with `history_depth == 0`, walk
    nothing at all.
    """
    if not tree.is_repository or options.history_depth == 0:
        return History(), frozenset()
    run.progress("history")
    try:
        walked = read_history(
            tree.root,
            list(facts.symbols),
            run.guard.source_control.source_id,
            depth=options.history_depth,
            timeout_s=options.git_timeout_seconds,
            total_s=options.history_total_seconds,
            should_stop=lambda: (run.check(), False)[1],
            node_namespace=namespace,
        )
    except HistoryError as error:
        # Closed wording: a git message can quote a path or a remote URL.
        raise CodeBuildRefused("The repository history could not be read") from error
    return walked, shallow_boundary(tree.root)


def _coverage(captured, chunks, facts, reasons, *, unbound, dropped, truncated, history_disabled):
    """What this generation does not contain, and why (plan section 9)."""
    excluded: dict[str, int] = {}
    for item in captured.exclusions:
        excluded[item.reason] = excluded.get(item.reason, 0) + 1
    kinds: dict[str, int] = {}
    for chunk in chunks.chunks:
        kinds[chunk.kind] = kinds.get(chunk.kind, 0) + 1
    return {
        "capture_kind": captured.kind,
        "files_accepted": len(captured.accepted.inputs),
        "files_excluded": excluded,
        # Keyed by path, not by reason: two binary files are two facts, and a
        # reason-keyed map would silently keep only the last of them.
        "files_refused": {item.logical_path: item.reason for item in chunks.refusals},
        "openie": OPENIE_SKIPPED,
        "openie_reasons": dict(sorted(reasons.items())),
        "passages": kinds,
        "symbols": len(facts.symbols) if facts is not None else 0,
        "data_objects": len(facts.data_objects) if facts is not None else 0,
        "code_edges": len(facts.edges) if facts is not None else 0,
        "code_truncated": bool(truncated),
        "unbound_nodes": len(unbound),
        "history_modifies_dropped": dropped,
        **({"history": "disabled"} if history_disabled else {}),
    }


def _stored_revisions(store, evidence, history):
    """Every accepted or commit revision this source already holds, by ID.

    Only records that actually differ are returned: a bootstrap finds none and binds
    once, while a refresh finds the revisions of its unchanged files and rebinds over
    them rather than minting a second record the store would refuse.
    """
    minted = [
        evidence.repository_revision,
        evidence.manifest_revision,
        *(item.revision for item in evidence.accepted),
        *history.revisions,
    ]
    found = {}
    for revision in minted:
        existing = store._knowledge_get("ArtifactRevision", revision.id)
        if existing is not None and existing != revision:
            found[revision.id] = existing
    return found


def _prepare(run, tree, options, captured, identity, gen, units, reasons):
    """Plan section 6 steps 4-7, all outside every transaction and every model call."""
    control = run.guard.source_control
    namespace = generation_namespace(gen)
    run.progress("extract")
    facts = extract_code(
        [item.unit.to_document() for item in units if item.unit is not None],
        control.source_id,
        should_stop=lambda: (run.check(), False)[1],
        node_namespace=namespace,
    )
    if len(facts.symbols) > options.max_symbols:
        raise CodeBuildRefused("This source holds more symbols than the configured ceiling allows")
    walked, boundary = _history(run, tree, facts, options, namespace)
    facts.commits, facts.modifies, facts.precedes = walked.commits, walked.modifies, walked.precedes
    run.progress("chunk")
    chunks = prepare_code_chunks(
        units, facts=facts, settings=options.chunk_settings, max_chunks=options.max_chunks
    )
    if not chunks.chunks and not options.allow_empty:
        raise CodeBuildRefused("No readable text was found in this source")
    run.check()
    run.progress("bind")
    bind = dict(
        workspace_id=control.workspace_id,
        source_id=control.source_id,
        generation_identity_inputs=identity,
        observed_at=gen.created_at,
    )
    evidence = code_binding.materialize_code_evidence(captured, chunks, facts, **bind)
    # CC6 finding 10 / CC7 finding 3: a symbol whose rendered body is only whitespace is
    # skipped by the committed chunker, so it has no passage and no native row. A
    # MODIFIES edge to one is dropped here (`bind_history` refuses it, and
    # `native_mutation` would reject the write) and the subtraction is recorded.
    unbound = ({item.id for item in facts.symbols} | {item.id for item in facts.data_objects}) - {
        row.native_id for row in evidence.native_rows
    }
    kept = [row for row in walked.modifies if row["symbol_id"] not in unbound]
    dropped = len(walked.modifies) - len(kept)
    history = dict(
        repository=tree.repository,
        workspace_id=control.workspace_id,
        source_id=control.source_id,
        generation_id=gen.id,
        generation_namespace=namespace,
        observed_at=gen.created_at,
        history_depth=options.history_depth if tree.is_repository else 0,
        shallow_boundary=boundary,
    )
    walked = replace(walked, modifies=kept)
    bound = code_history.bind_history(walked, code_bundle=evidence, **history)
    # An immutable revision is written once: a refresh over an unchanged file, and every
    # commit this source already holds, derive the *same* revision ID with a later
    # `observed_at`, which the store refuses to rewrite. So the two pure bindings run
    # again over the records the store already has, exactly as `prose_generation._pair`
    # reuses them. Bounded: one `_knowledge_get` per revision, and only when one exists.
    stored = _stored_revisions(run.store, evidence, bound)
    if stored:
        evidence = code_binding.materialize_code_evidence(
            captured, chunks, facts, stored_revisions=stored, **bind
        )
        bound = code_history.bind_history(walked, code_bundle=evidence, stored_revisions=stored, **history)
    merged = code_history.merge_code_bundles(evidence, bound)
    # CC7 finding 8: the merged coverage is the history bundle's, so this lane's own
    # coverage is unioned into it rather than written over it.
    coverage = _coverage(
        captured,
        chunks,
        facts,
        reasons,
        unbound=unbound,
        dropped=dropped,
        truncated=facts.truncated,
        history_disabled=not tree.is_repository or options.history_depth == 0,
    )
    merged = replace(merged, coverage_json=canonical_json(json.loads(merged.coverage_json) | coverage))
    return merged, facts


def _vectors(embeddings, texts):
    if not texts:
        return ()
    matrix = embeddings.embed(list(texts), kind="document")
    if len(matrix) != len(texts):
        raise ValueError("Embedding result inventory differs")
    return tuple(tuple(float(value) for value in row.tolist()) for row in matrix)


def _index(run, merged, facts, embeddings) -> staged_code.PreparedCodeIndex:
    """Join the merged evidence with its vectors and the graph's relations."""
    run.progress("embed", 0, len(merged.passages))
    vectors = _vectors(embeddings, [item.chunk.text for item in merged.passages])
    run.check()
    # `hipporag.preparation.prepare_code_rows`' rule, without its unguarded client: a
    # node's name vector exists for `find_synonyms` alone, so a node that may not link
    # is simply not embedded, and a commit never carries one.
    eligible = [
        row
        for row in merged.native_rows
        if row.native_kind != "Commit" and enters_synonym_search(row.native_id, row.row.get("name") or "")
    ]
    names = _vectors(embeddings, [name_text_of(row.row.get("name") or "") for row in eligible])
    by_id = dict(zip([row.native_id for row in eligible], names, strict=True))
    run.progress("embed", len(merged.passages), len(merged.passages))
    edges, definitions = staged_code.code_relations(merged, facts)
    return staged_code.PreparedCodeIndex(
        bundle=merged,
        dense=tuple(
            staged_code.PreparedCodePassage(item, vector)
            for item, vector in zip(merged.passages, vectors, strict=True)
        ),
        native=tuple(
            staged_code.PreparedNativeRow(row, by_id.get(row.native_id, ())) for row in merged.native_rows
        ),
        edges=edges,
        definitions=definitions,
    )


# ----------------------------------------------------------------- identity and receipts


def _policy(run, now):
    """The one local grant every artifact and span of this build carries."""
    control = run.guard.source_control
    policy = k.AccessPolicy(
        workspace_id=control.workspace_id,
        origin="local_curated",
        scope_key=f"source:{control.source_id}:{MANAGED_CODE_SCOPE}",
        mode="workspace",
        verified_at=now,
    )
    existing = run.store._knowledge_get("AccessPolicy", policy.id)
    return (existing, ()) if existing is not None else (policy, (policy,))


# The five lane-neutral helpers live in `build_run.py` now (plan section 8); the code lane
# keeps every old name bound, as `prose_generation.py` keeps `_Run`. Only the two receipts
# changed shape: they take the accepted manifest's hash, which this lane reads off its own
# capture record and the connector runtime reads off its inventory manifest.
_instant = adopt_capture_instant
_operation_generation = operation_generation
_rebaseline = rebaseline_between_batches


def _receipt(store, gen, captured, outcome, job=None, *, resumed=0, rebaselines=0):
    return published_receipt(
        store, gen, captured.accepted.manifest.sha256, outcome, job, resumed=resumed, rebaselines=rebaselines
    )


def _prior_receipt(run, gen, captured, operation_id):
    return prior_receipt(run, gen, captured.accepted.manifest.sha256, operation_id)


# ----------------------------------------------------------------- install, write, publish


def _install(run, bundle, accepted, operation_id, coverage_json, registry_fingerprint=None):
    """Callback-free; caller owns the source lock and admits intentional setup changes.

    Bootstrap and refresh share this window. The one difference a *bootstrap* makes is
    the managed flip, which ruling 9 keeps at staging start, so it is accounted here and
    nowhere else -- `_publish` expects no authorization-epoch change at all (review B6,
    dissolved).
    """
    store, gen = run.store, bundle.generation
    run.guard.check_local()
    _operation_generation(store, gen, operation_id)
    original = run.guard.source_control
    source = store.get_source(gen.source_id)
    previous = store._knowledge_get("MaintenanceJob", source.get("active_build_id"))
    if previous is not None and previous.status == "running" and previous.lease_expires_at > store._now():
        raise BuildBusy("Source already has a live build holder")
    # Recover this source's own expired attempt, so a crashed build's holder never
    # outlives it. Other sources' jobs are outside our authority.
    store.recover_generation_builds(source_id=gen.source_id)
    expected_epoch = run.guard.expected_authorization_epoch + int(not store.source_is_managed(gen.source_id))
    for policy in accepted.planned_policies:
        if store._knowledge_get("AccessPolicy", policy.id) is None:
            expected_epoch += 1
            store.put_knowledge(policy)
    existing = store._generation(gen.id) if store._knowledge_get("Generation", gen.id) else None
    if existing is None:
        # The generation row precedes the first Artifact, which is what keeps a
        # converting source in the legacy lane for every transaction of the bootstrap
        # (`context.legacy_lane`, ruling 14). Coverage is written once, here: on a
        # resume the persisted row already carries it plus the store's own keys.
        #
        # The registry this build read is recorded once, here, for the same reason
        # (plan section 3.2). It is outside `Generation.identity_fields`, so it moves no
        # generation id; it is never hashed, because `generation_checksums` skips the
        # `Generation` row. A reclaim takes the other branch and writes nothing, so a
        # rebuild under a different process registry adopts what was stored rather than
        # rewriting an immutable record - which is the adoption plan section 3.2 asks for,
        # and why `staged_code._local` normalizes the field away on both sides (ruling R47).
        store.put_knowledge(
            gen.replace(coverage_json=coverage_json, registry_fingerprint=registry_fingerprint)
        )
    store.begin_managed_source(gen.source_id)
    expiry = store._now() + timedelta(seconds=run.options.lease_duration_seconds)
    if existing is None:
        job = store.claim_generation_build(
            gen.id, job_key=operation_id, lease_owner=run.owner, lease_expires_at=expiry
        )
    else:
        # A never-published attempt of the *same* accepted inputs resumes without
        # collecting; `claim_generation_build` would collect a failed generation's rows
        # and restart this build from zero (CC3).
        job = store.reclaim_generation_build(
            gen.id,
            job_key=operation_id,
            lease_owner=run.owner,
            lease_expires_at=expiry,
            expected_manifest_hash=gen.manifest_hash,
        )
    with store.generation_write(gen.id, **credentials(job)):
        for artifact, revision in (*bundle.accepted_pairs, *bundle.history_pairs):
            store.put_knowledge(artifact)
            store.put_knowledge(revision)
        for member in bundle.revision_members:
            store.put_knowledge(member)
    store.bind_generation_embedding_profile(gen.id, bundle.manifest_revision.id, **credentials(job))
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


def _batch_bytes(batch):
    return len(canonical_json([staged_code._payload(record) for record in batch]).encode("utf-8"))


def _write(run, prepared, resume):
    """Durable staging over many transactions, with the guard checked between each.

    A rebaseline precedes *every* external check in this loop, because `check_local()`
    latches and ruling 2 forbids a rebaseline after a sticky failure: noticing the epoch
    change by calling `check()` is already too late (CC8 finding 2). An epoch change
    *inside* a batch rolls that batch back and aborts, which is what ruling 2's
    "between batches only" means; the staged inventory survives and a retry resumes.
    """
    size = run.options.batch_size
    total = -(-(resume.group_count - resume.skipped_groups) // size)
    rebaselines, written = 0, 0
    run.progress("write", 0, total)
    for batch in staged_code._write_batches(prepared, batch_size=size, resume=resume):
        rebaselines += _rebaseline(run)
        run.check()
        if _batch_bytes(batch) > run.options.max_batch_payload_bytes:
            raise CodeBuildRefused("A staged code batch exceeds the configured payload ceiling")
        staged_code._write_batch(
            run.store, prepared, batch, **credentials(run.job), **authority_fields(run.guard)
        )
        written += 1
        rebaselines += _rebaseline(run)
        run.check()
        if written % run.options.checkpoint_interval == 0:
            run.progress("write", written, total)
    rebaselines += _rebaseline(run)
    run.check()
    run.progress("seal")
    staged_code._seal(run.store, prepared, **credentials(run.job), **authority_fields(run.guard))
    run.check()
    return rebaselines


def _source_presentation(meta, passages, files):
    """The published source row shape, as the prose lane presents its own."""
    return (
        dict(status="ready", stage="ready", progress_done=passages, progress_total=passages, error=None),
        dict(meta or {}) | {"chunks": passages, "documents": files},
    )


def _publish(run, prepared, accepted, captured, *, resumed, rebaselines):
    """One short transaction: the atomic swap, its counts and its presentation."""
    store, gen, guard = run.store, prepared.generation, run.guard
    guard.check_local()
    event = store.publish_staged_generation(
        gen.id,
        expected_parent_id=gen.parent_id,
        **credentials(run.job),
        expected_suppression_epoch=guard.expected_suppression_epoch,
        published_at=store._now(),
    )
    # No arithmetic here: the managed flip happened at staging start (ruling 9), so a
    # genuine unrelated authorization change in this window still refuses.
    if (store.authorization_epoch(), store.suppression_epoch()) != (
        guard.expected_authorization_epoch,
        guard.expected_suppression_epoch,
    ):
        raise AuthorizationChanged("Authority changed during publication")
    counts = generation_counts(store, gen.id)
    source = store.get_source(gen.source_id)
    fields, meta = _source_presentation(source.get("meta"), counts.passages, len(prepared.bundle.accepted))
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
    manifest_hash = captured.accepted.manifest.sha256
    return BuildReceipt(gen.source_id, gen.id, event, manifest_hash, "published", resumed, rebaselines), fresh


def _resumed_batches(prepared, resume):
    """Skipped groups that were real staging work, not this install's own members.

    The probe recognises the revision members the install writes before every attempt,
    fresh or resumed, so counting them would report a first bootstrap as resumed from
    four batches. The member groups are indexes 1..len(revision_members) of a
    deterministic plan whose first group is the accepted preflight.
    """
    installed = len(prepared.bundle.revision_members)
    return sum(1 for index in resume.skipped if index > installed)


# ----------------------------------------------------------------- the coordinator


def build_code_source(
    ctx,
    *,
    source_id,
    actor,
    tree: CodeTreeInput,
    options: CodeBuildOptions,
    raw_store,
    embedding_spec,
    operation_id,
    should_stop,
    on_progress=None,
    embedding_cache: EmbeddingCache | None = None,
    registry_fingerprint: str | None = None,
) -> BuildReceipt:
    """Convert, refresh or resume one repository, archive or code file.

    Bootstrap and refresh are decided by the active pointer, never by the managed flag:
    a resumed bootstrap has `managed=True` and no pointer, so the prose lane's "managed
    source needs explicit recovery" check would refuse exactly the case this lane
    exists to support.

    `registry_fingerprint` is the frozen registry the runtime lane read (gate CK5, plan
    section 3.2). It defaults to `None`, so every reviewed caller of this coordinator is
    unchanged and the pre-kit path records nothing new.
    """
    if registry_fingerprint is not None and (
        type(registry_fingerprint) is not str or not registry_fingerprint
    ):
        raise ValueError("A registry fingerprint is an explicit nonempty string, or omitted")
    if (
        type(actor) is not BuildActor
        or type(options) is not CodeBuildOptions
        or type(embedding_spec) is not EmbeddingSpec
        or type(tree) is not CodeTreeInput
    ):
        raise ValueError("Explicit immutable code build inputs/options required")
    if (
        type(operation_id) is not str
        or not operation_id
        or len(operation_id) > 256
        or not callable(should_stop)
        or on_progress is not None
        and not callable(on_progress)
    ):
        raise ValueError("Stable operation identity and live cancellation required")
    if ctx.store.in_ambient_transaction():
        raise ValueError("Coordinator requires no ambient transaction")
    run = BuildRun(
        ctx,
        actor,
        source_id,
        options,
        should_stop,
        on_progress,
        capture=capture_build_authority,
        cancelled_message=CANCELLED_MESSAGE,
        renewal_failed_message=RENEWAL_FAILED_MESSAGE,
    )
    installed = False
    try:
        control = run.guard.source_control
        if control.kind != tree.kind:
            raise CodeBuildRefused("The captured tree is not this source's kind")
        run.start()
        run.progress("capture")
        resolved = resolve_embedding_profile(ctx.ollama, spec=embedding_spec, authorization_check=run.check)
        embedding = validate_profile_descriptor(resolved.descriptor())
        now = run.store._now()
        policy, planned = _policy(run, now)
        identity = code_binding.CodeGenerationInputs(
            parent_id=control.active_generation_id,
            parser_version=CODE_PARSER_VERSION,
            linker_version=CODE_LINKER_VERSION,
            embedding_profile=embedding.fingerprint,
            configuration=_configuration(embedding, options),
            policy_id=policy.id,
        )
        # CC8's contract note: `capture_repository_inputs` adds its own reserved
        # `capture` key and `folded` adds `code_derivation`, and the manifest's
        # configuration must be the dict generation identity hashes -- so the capture
        # runs on the folded configuration and the identity inputs take the manifest's
        # copy back with `code_derivation` removed.
        captured = _capture(
            run,
            tree,
            options,
            raw_store,
            identity.folded(code_binding.EXPECTED_CODE_CHUNK_RULE_VERSION),
            now,
        )
        identity = replace(
            identity,
            configuration={
                key: value
                for key, value in json.loads(captured.accepted.configuration_json).items()
                if key != code_binding.CODE_BINDING_CONFIGURATION_KEY
            },
        )
        settled = dict(
            workspace_id=control.workspace_id,
            source_id=control.source_id,
            generation_identity_inputs=identity,
        )
        gen = code_binding.code_generation(captured, observed_at=now, **settled)
        instant = _instant(run.store, gen, now)
        if instant != now:
            captured = replace(captured, observed_at=instant)
            gen = code_binding.code_generation(captured, observed_at=instant, **settled)
        if current := _prior_receipt(run, gen, captured, operation_id):
            run.pause()
            run.check()
            return current
        units, reasons = _read(run, captured, raw_store, options)
        merged, facts = _prepare(run, tree, options, captured, identity, gen, units, reasons)
        accepted = AcceptedBuildInputs(
            pairs=tuple((*merged.accepted_pairs, *merged.history_pairs)),
            spans=tuple(merged.spans),
            planned_policies=planned,
        )
        run.adopt(run.guard.bind_inputs(accepted))
        run.generation = gen
        run.pause()
        run.check()
        with run.store.transaction():
            run.store._lock_source(source_id)
            job, fresh = _install(
                run, merged, accepted, operation_id, merged.coverage_json, registry_fingerprint
            )
        run.job = job
        run.adopt(fresh)
        installed = True
        run.start()
        embeddings = ProfiledEmbeddings(
            ctx.ollama, resolved, cache=embedding_cache, authorization_check=run.check
        )
        prepared = _index(run, merged, facts, embeddings)
        resume = staged_code.probe_staged_rows(run.store, prepared)
        rebaselines = _write(run, prepared, resume)
        embeddings.validate()
        run.pause()
        run.check()
        with run.store.transaction():
            run.store._lock_source(source_id)
            run.guard.check_local()
            receipt, final_guard = _publish(
                run,
                prepared,
                accepted,
                captured,
                resumed=_resumed_batches(prepared, resume),
                rebaselines=rebaselines,
            )
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
                    **credentials(run.job),
                    error_code="build_cancelled" if isinstance(error, BuildCancelled) else "build_failed",
                )
            except (ValueError, AuthorizationChanged):
                pass  # A lost fence or committed publication is owned by recovery/receipt.
        raise
    finally:
        run.close()
