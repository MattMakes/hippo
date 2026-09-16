"""The one adapter from a saved Source to its reviewed coordinator: plain prose or code.

Eligibility is a closed predicate over the saved Source row - its kind and its
sanitized stored filename - never over an HTTP claim about the bytes. The
adapter owns no storage records: it locates the saved input, captures the
effective configuration, and hands both to `build_plain_source` or, for a
repository, an archive or a code file, to `build_code_source`. It never clears
passages, deletes a source, sweeps orphans, collects a generation or removes
raw bytes; a managed attempt that cannot publish leaves the last good
generation exactly where it was. The one thing it removes is a repository
build's own per-operation clone (`discard_checkout`), after the coordinator
has captured every byte it needed.

Failures reach the Source row as a bounded generic code. Source text, raw
bytes, absolute paths, clone URLs, tokens, prompts, provider bodies, model
output and the text of an unknown exception never do.

Since gate CK5 the prose hand-off goes through the kit: the `local` connector
answers the inventory and `connectors.lanes.run_coordinator_lane` calls
`build_plain_source` with the frozen registry's fingerprint. The coordinator's
arguments, its capture and its output are unchanged - the fingerprint is the
one field a runtime build records that the pre-kit path did not. This module is
the only one in `hippo.ingest` that may import `hippo.connectors` (ruling R54),
and the kit never imports back.
"""

from __future__ import annotations

import logging
import shutil
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from ..connectors.base import ChangePage, current_registry
from ..connectors.lanes import CoordinatorLane, run_coordinator_lane
from ..connectors.local.connector import LocalConnector, LocalSourceConfig
from ..knowledge.access import AuthorizationChanged
from ..knowledge.build_authority import BuildActor
from ..knowledge.embedding_cache import EmbeddingCache
from ..knowledge.embedding_profile import (
    EmbeddingProfileChanged,
    EmbeddingProfileMismatch,
    EmbeddingSpec,
)
from ..knowledge.raw_artifacts import RawArtifactStore
from ..knowledge.source_lifecycle import OPERATION_ID
from ..ollama import EMBED_PREFIXES, OllamaError, _base_name
from ..store.generations import INTERRUPTED_REFRESH_STAGE, REFRESHING_PREFIX
from . import repos
from .accepted_inputs import CaptureLimits, FileInput, InputCaptureError
from .chunker import MIN_CHUNK_CHARS
from .code_generation import CodeBuildOptions, CodeBuildRefused, CodeTreeInput, build_code_source
from .prose_generation import (
    BuildBusy,
    BuildCancelled,
    BuildProgress,
    BuildReceipt,
    PlainBuildOptions,
    build_plain_source,
)
from .provenance import UnsupportedProvenanceFormat
from .readers import TooLarge, is_code_name, is_plain_prose_name
from .repo_capture import CaptureRefused, repository_descriptor
from .repos import RepoError

log = logging.getLogger(__name__)

Source = Mapping[str, Any]
Eligibility = Literal["managed", "eligible_legacy", "unsupported", "tombstoned"]

SOURCES_DIR = "sources"
KNOWLEDGE_DIR = "knowledge"
RAW_DIR = "raw-v1"
CACHE_DIR = ("cache", "embeddings-v1")
# Where a managed repository build clones, one folder per operation. Not beside the legacy
# lane's `repo/` checkout, because `repo` is itself a valid operation identity.
CHECKOUTS_DIR = "checkouts"

# A Source row Task 15 will create for one connector instance. It has no saved bytes, so it has no
# managed build here; ruling R43 makes the refusal explicit rather than leaving it to `ingress_file`.
CONNECTOR_KIND = "connector"

# The saved presentation of a current tombstone (hippo.knowledge.source_lifecycle).
TOMBSTONE = ("deleted", "tombstoned")

MAX_MESSAGE_CHARS = 200
STATUSES = ("ready", "failed")
# The first is the stage the store's own restart sweep writes, so it is that constant rather
# than a second spelling of it: 4e decision 7 moved the managed-lane vocabulary to
# `store/generations.py`, and `REFRESHING_PREFIX` above already comes from there.
STAGES = (INTERRUPTED_REFRESH_STAGE, "refresh_cancelled", "failed", "cancelled")


class ManagedDispatchError(ValueError):
    """This request cannot be dispatched to a managed build."""


class ManagedActorRequired(ManagedDispatchError):
    """A managed source never falls back to legacy: it needs an explicit build actor."""


class ManagedConfigurationError(ManagedDispatchError):
    """The effective configuration lies outside the coordinator's reviewed contract."""


class ManagedIngressError(ManagedDispatchError):
    """The saved bytes of this source cannot be offered to a managed build."""


class ManagedPreflightRefused(ManagedDispatchError):
    """One managed lane of this bulk cannot be built; which one is not disclosed.

    A bulk that refuses and a bulk with nothing to do both used to return `0`, so a route
    could not tell "this workspace is empty" from "one lane's authority failed" without
    re-reading the inventory it had just been refused. This is the global signal the plan's
    "no hidden per-source breakdown" leaves open: it names no source and carries no count.
    """


# ------------------------------------------------------------- eligibility


def stored_filename(source: Source) -> str:
    """The saved file name of a source, as `add_text`/`add_upload` sanitized it."""
    meta = source.get("meta") or {}
    name = meta.get("file") if isinstance(meta, Mapping) else None
    return name if type(name) is str else ""


def safe_stored_name(name: str) -> str:
    """The base name, with anything that could walk out of the source folder removed."""
    return PurePosixPath(str(name).replace("\\", "/")).name.strip()


def managed_eligibility(source: Source) -> Eligibility:
    """Which lane one saved Source belongs to. Closed, and decided on the row alone.

    Two definitions of "managed" exist on purpose, and neither is a copy of the other to
    fix (PA3a review finding 9). Here, and in `store.legacy_source_cleanup`, the authority
    is `source["managed"]`: a row whose flag is set is never dispatched to, or cleared by,
    the legacy lane. `build_authority._source_control` reads `managed or
    active_generation_id`, the deliberately broader guard for the build it admits. Every
    writer keeps them in agreement: the flag flips at staging start (ruling 9), before any
    generation can be published and pointed at.

    The eligible families are pasted text, a plain-prose file, and -- through the code
    coordinator -- a repository, a `.zip` archive and a file whose saved name is a code
    name. Everything else (rich documents, the sample) has no managed build.
    """
    if not isinstance(source, Mapping):
        raise ManagedDispatchError("A saved source row is required")
    if (source.get("status"), source.get("stage")) == TOMBSTONE:
        return "tombstoned"
    if source.get("managed"):
        return "managed"
    kind = source.get("kind")
    name = stored_filename(source)
    if kind in ("text", "repo"):
        return "eligible_legacy"
    if kind == "archive" and name.lower().endswith(".zip"):
        return "eligible_legacy"
    if kind == "file" and (is_plain_prose_name(name) or is_code_name(name)):
        return "eligible_legacy"
    return "unsupported"


def is_code_source(source: Source) -> bool:
    """Whether a saved Source is built by the code coordinator rather than the plain-prose one."""
    kind = source.get("kind")
    return kind in ("repo", "archive") or (kind == "file" and is_code_name(stored_filename(source)))


def new_operation_id() -> str:
    """A bounded unique identity for one source operation, safe to echo in a receipt."""
    value = f"index.{uuid4().hex}"
    if OPERATION_ID.match(value) is None:  # the pattern is the contract, not a guess
        raise ManagedDispatchError("Generated operation identity is not bounded")
    return value


def check_actor(actor: BuildActor | None) -> BuildActor | None:
    """An omitted actor means legacy; anything that is not a `BuildActor` is a mistake."""
    if actor is not None and type(actor) is not BuildActor:
        raise ManagedDispatchError("Explicit immutable build actor required")
    return actor


@dataclass(frozen=True)
class Dispatch:
    """What one caller's actor and one saved Source decide, before any mutation."""

    mode: Literal["managed", "legacy", "skip"]
    eligibility: Eligibility
    actor: BuildActor | None = None
    operation_id: str | None = None


def check_operation_id(operation_id: str | None) -> str | None:
    """An omitted identity is fine; anything that is not a bounded printable token is not.

    Closed validation of a caller-supplied token, so it can be echoed in a receipt. It is
    separate from `plan_dispatch` because `delete_source` has to apply it even when there
    is no Source row left to classify.
    """
    if operation_id is not None and (
        type(operation_id) is not str or OPERATION_ID.match(operation_id) is None
    ):
        raise ManagedDispatchError("Operation identity must be a bounded printable token")
    return operation_id


def plan_dispatch(
    source: Source, *, actor: BuildActor | None = None, operation_id: str | None = None
) -> Dispatch:
    """Decide the lane for one source. Raises before a managed source can reach legacy."""
    check_actor(actor)
    check_operation_id(operation_id)
    eligibility = managed_eligibility(source)
    if eligibility == "tombstoned":
        return Dispatch("skip", eligibility)
    if eligibility == "managed" and actor is None:
        # Both verbs, because this one classification is what `reindex` and `delete_source`
        # run: `delete_source` reaches it before `_tombstone`'s own "deleted" sentence.
        raise ManagedActorRequired("A managed source cannot be rebuilt or deleted without a build actor")
    if actor is not None and eligibility in ("managed", "eligible_legacy"):
        return Dispatch("managed", eligibility, actor, operation_id or new_operation_id())
    return Dispatch("legacy", eligibility)


# --------------------------------------------------------- build resources


def source_directory(ctx, source_id: str) -> Path:
    """Where one source's saved ingress bytes live; `pipeline.source_dir` is this."""
    return Path(ctx.config.data_dir) / SOURCES_DIR / source_id


def raw_root(ctx) -> Path:
    """Content-addressed immutable originals, always below the absolute data directory."""
    return Path(ctx.config.data_dir).resolve() / KNOWLEDGE_DIR / RAW_DIR


def cache_root(ctx) -> Path:
    """The disposable profile-keyed vector cache, a sibling of the raw root."""
    return Path(ctx.config.data_dir).resolve() / KNOWLEDGE_DIR / Path(*CACHE_DIR)


def embedding_spec(ollama) -> EmbeddingSpec:
    """The current base-model prefix mapping, shared with empty-corpus resolution."""
    query_prefix, document_prefix = EMBED_PREFIXES.get(_base_name(ollama.embed_model), ("", ""))
    return EmbeddingSpec(query_prefix=query_prefix, document_prefix=document_prefix)


def _positive(value: Any, what: str) -> int:
    if type(value) is not int or value <= 0:
        raise ManagedConfigurationError(f"Configured {what} must be a positive whole number")
    return value


def _fraction(value: Any, what: str) -> float:
    """A stored setting the build's profile is bound to: refused here, not deep in the coordinator."""
    if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
        raise ManagedConfigurationError(f"Stored {what} must be a fraction between 0 and 1")
    return float(value)


def _stored_count(settings: Mapping[str, Any], name: str, what: str, minimum: int) -> int:
    value = settings.get(name)
    if type(value) is not int or value < minimum:
        raise ManagedConfigurationError(f"Stored {what} must be a whole number of at least {minimum}")
    return value


def _chunking(config) -> tuple[int, int]:
    """Chunk size and overlap as configured, or a refusal.

    Both coordinators would raise a small chunk size to `MIN_CHUNK_CHARS` and lower an
    overlap past a third of the size. Both change the coverage the operator asked for, so
    they are refused here rather than silently applied.
    """
    size = _positive(config.chunk_size_chars, "chunk size")
    overlap = config.chunk_overlap_chars
    if size < MIN_CHUNK_CHARS:
        raise ManagedConfigurationError("Configured chunk size is below the reviewed minimum")
    if type(overlap) is not int or overlap < 0 or overlap > size // 3:
        raise ManagedConfigurationError("Configured chunk overlap exceeds a third of the chunk size")
    return size, overlap


def build_options(ctx) -> PlainBuildOptions:
    """The effective configuration as plain-prose coordinator options, or a refusal."""
    config = ctx.config
    size, overlap = _chunking(config)
    upload = _positive(config.max_upload_bytes, "upload limit")
    decoded = _positive(config.max_text_chars, "text limit")
    workers = _positive(config.openie_workers, "OpenIE worker count")
    threshold = _fraction((ctx.store.get_settings() or {}).get("synonymy_threshold"), "synonym threshold")
    reviewed = PlainBuildOptions()
    return PlainBuildOptions(
        chunk_size_chars=size,
        chunk_overlap_chars=overlap,
        synonymy_threshold=threshold,
        allow_empty=False,
        capture_limits=CaptureLimits(
            max_input_bytes=upload,
            max_total_bytes=upload,
            max_inputs=1,
            max_manifest_bytes=reviewed.capture_limits.max_manifest_bytes,
        ),
        max_decoded_chars=decoded,
        max_chunks=reviewed.max_chunks,
        max_bootstrap_rows=reviewed.max_bootstrap_rows,
        max_bootstrap_bytes=reviewed.max_bootstrap_bytes,
        batch_size=reviewed.batch_size,
        workers=workers,
        lease_duration_seconds=reviewed.lease_duration_seconds,
        renewal_interval_seconds=reviewed.renewal_interval_seconds,
    )


def code_build_options(ctx) -> CodeBuildOptions:
    """The effective configuration as code coordinator options, or a refusal.

    The input-affecting settings are the ones the legacy lane reads for the same tree:
    chunk size and overlap, the synonym threshold and `code_history_depth`. The git budgets
    are `code_git_timeout_s` and `code_history_total_s`, and the decoded-text budget and
    worker count are the configured ones the plain lane uses. Every other limit is the code
    coordinator's reviewed default. Clone depth is not an option -- it is not identity and
    the coordinator never clones -- so it is derived by `clone_depth`.
    """
    config = ctx.config
    size, overlap = _chunking(config)
    decoded = _positive(config.max_text_chars, "text limit")
    workers = _positive(config.openie_workers, "OpenIE worker count")
    settings = ctx.store.get_settings() or {}
    return CodeBuildOptions(
        chunk_size_chars=size,
        chunk_overlap_chars=overlap,
        synonymy_threshold=_fraction(settings.get("synonymy_threshold"), "synonym threshold"),
        history_depth=_stored_count(settings, "code_history_depth", "history depth", 0),
        allow_empty=False,
        max_decoded_chars=decoded,
        workers=workers,
        git_timeout_seconds=_stored_count(settings, "code_git_timeout_s", "git timeout", 1),
        history_total_seconds=_stored_count(settings, "code_history_total_s", "history time budget", 1),
    )


def clone_depth(options: CodeBuildOptions) -> int:
    """How many commits a managed clone fetches: `pipeline._clone_depth`'s rule, from the options.

    One more than the history walk reads, so a shallow clone's parentless boundary commit is
    never walked, or 1 when history is off.
    """
    return options.history_depth + 1 if options.history_depth > 0 else 1


def ingress_file(ctx, source_id: str, *, stored_name: str | None = None) -> Path:
    """The one saved file of an eligible source, as an absolute regular path.

    Missing, duplicated, symlinked, non-regular, oversized and name-escaping
    inputs are refused here, before any raw root exists or any model is asked
    anything. Capture itself re-checks the file under `O_NOFOLLOW` and refuses a
    file that changes while it is read.

    `stored_name`, when given, is the sanitized name the Source row saved, which is
    what eligibility was decided on; a single saved file under any other name is
    refused rather than built as something the row never said it was (PA3a
    review finding 6).
    """
    directory = source_directory(ctx, source_id)
    try:
        entries = sorted(directory.iterdir())
    except OSError as error:
        raise ManagedIngressError("The saved source directory could not be read") from error
    if len(entries) != 1:
        raise ManagedIngressError("A managed plain source needs exactly one saved file")
    entry = entries[0]
    if not entry.name or entry.name != safe_stored_name(entry.name):
        raise ManagedIngressError("The saved file name does not stay inside the source directory")
    if stored_name is not None and entry.name != stored_name:
        raise ManagedIngressError("The saved file is not the one this source recorded")
    try:
        info = entry.lstat()
        root = directory.resolve(strict=True)
    except OSError as error:
        raise ManagedIngressError("The saved file could not be read") from error
    if not stat.S_ISREG(info.st_mode):
        raise ManagedIngressError("The saved input must be a regular file")
    if info.st_size > int(ctx.config.max_upload_bytes):
        raise ManagedIngressError("The saved input is larger than the configured upload limit")
    return root / entry.name


def _recorded_name(source: Source) -> str | None:
    """The saved name eligibility read, for the families whose eligibility reads one."""
    if source.get("kind") in ("file", "archive"):
        return safe_stored_name(stored_filename(source))
    return None


def checkout_directory(ctx, source_id: str, operation_id: str) -> Path:
    """Where one managed repository build clones: its own folder, never the legacy `repo/`.

    Named by the operation identity, which `OPERATION_ID` bounds to one printable path
    segment that cannot start with a dot.
    """
    if type(operation_id) is not str or OPERATION_ID.match(operation_id) is None:
        raise ManagedDispatchError("Operation identity must be a bounded printable token")
    return source_directory(ctx, source_id) / CHECKOUTS_DIR / operation_id


def discard_checkout(ctx, source_id: str, operation_id: str) -> None:
    """Remove one repository build's own clone, and nothing else.

    The only removal this adapter performs, named so that a reader -- and CD8's spies --
    can tell it apart from the legacy delete's `rmtree` of the whole source directory.
    Every byte the build used was captured into the raw store before the coordinator
    returned, and the next build clones afresh under its own operation, so nothing a
    generation depends on lives here. A symlink is refused rather than followed; a missing
    checkout is nothing to do.
    """
    checkout = checkout_directory(ctx, source_id, operation_id)
    if checkout.is_symlink():
        raise ManagedDispatchError("A managed checkout must be a folder this build created")
    if not checkout.exists():
        return
    shutil.rmtree(checkout, ignore_errors=True)
    if checkout.exists():
        log.warning("Managed checkout could not be removed: source=%s operation=%s", source_id, operation_id)


def _clone_url(source: Source) -> str:
    meta = source.get("meta") or {}
    url = meta.get("url") if isinstance(meta, Mapping) else None
    return url if type(url) is str else ""


# ------------------------------------------------------ source presentation


_PHASE_STAGES = {
    "capture": "capture",
    "reading": "capture",
    "extract": "extract",
    # The code coordinator's own phases, folded into the same bounded tokens.
    "history": "extract",
    "chunk": "extract",
    "bind": "extract",
    "embed": "extract",
    "write": "write",
    "seal": "write",
}
_UNKNOWN_PHASE = "building"


def _stage_token(progress: BuildProgress) -> str:
    """A safe bounded stage name for one coordinator phase."""
    token = _PHASE_STAGES.get(progress.phase, _UNKNOWN_PHASE)
    if token == "extract" and progress.total > 0 and progress.completed >= progress.total:
        return "write"  # extraction is complete; the coordinator is writing its batches
    return token


def present(ctx, source_id: str, **fields: Any) -> bool:
    """Write Source presentation under the lock a tombstone takes, or not at all.

    A committed tombstone owns `deleted/tombstoned`; a late worker must never
    overwrite it, so the read and the write share one transaction and one source
    lock with `apply_source_tombstone`.
    """
    store = ctx.store
    with store.transaction():
        if store.get_source(source_id) is None:
            return False
        store._lock_source(source_id)
        source = store.get_source(source_id)
        if source is None or managed_eligibility(source) == "tombstoned":
            return False
        # A repeated stage, or a refresh that found the current inputs already
        # published, must not move the row's timestamp or wake a watcher.
        if all(key in source and source[key] == value for key, value in fields.items()):
            return True
        store.update_source(source_id, **fields)
        return True


def _present_progress(ctx, source_id: str, progress: BuildProgress, *, refresh: bool) -> None:
    """Coordinator progress reaches `status`/`stage`/`progress_*` and nothing else.

    Never `meta_json`: that field feeds `SourceControl.input_config_json`, which
    the build's own authority is bound to.
    """
    token = _stage_token(progress)
    fields: dict[str, Any] = {"stage": _refreshing_stage(token) if refresh else token}
    if refresh:
        fields["status"] = "ready"  # the current generation keeps serving throughout
    if progress.total > 0:
        fields["progress_done"] = min(int(progress.completed), int(progress.total))
        fields["progress_total"] = int(progress.total)
    present(ctx, source_id, **fields)


def _refreshing_stage(token: str) -> str:
    """The stage a refresh writes, built from the prefix the restart sweep matches.

    The store's sweep finds an abandoned refresh by `stage STARTS WITH REFRESHING_PREFIX`.
    Spelling the prefix here as well would let the two drift, and the drift is silent: the
    sweep would stop matching, `refreshing: ...` would stay on the row for ever, and every
    test would still be green.
    """
    return f"{REFRESHING_PREFIX} {token}"


def _starting_fields(refresh: bool) -> dict[str, Any]:
    if refresh:
        return {"status": "ready", "stage": _refreshing_stage("capture"), "error": None}
    return {"status": "indexing", "stage": "capture", "progress_done": 0, "progress_total": 0, "error": None}


# ------------------------------------------------------------- the failure


@dataclass(frozen=True)
class ManagedFailure:
    """What a caller may see about a managed build that did not publish."""

    status: str
    stage: str
    code: str
    message: str

    def __post_init__(self) -> None:
        if any(type(value) is not str for value in (self.status, self.stage, self.code, self.message)):
            raise ManagedDispatchError("A managed failure is bounded text")
        if self.status not in STATUSES or self.stage not in STAGES:
            raise ManagedDispatchError("Unknown managed failure presentation")
        if not self.code.isascii() or len(self.message) > MAX_MESSAGE_CHARS or not self.message:
            raise ManagedDispatchError("A managed failure message must be generic and bounded")


UNKNOWN_CODE = "operation_failed"
UNKNOWN_MESSAGE = "The build could not be completed. Check the local logs for this operation."
_INVALID_SOURCE = "The saved file for this source cannot be built as plain prose."
_INVALID_CODE_SOURCE = "The saved repository, archive or code file for this source cannot be built."
# The same stable code `knowledge.public_errors` gives a query that met a stale profile.
_REBUILD_CODE = "retrieval_rebuild_required"
_REBUILD_MESSAGE = "The embedding profile changed during the build. Reindex this source before using it."

# Closed, ordered: the first matching family wins. `BuildBusy`, the managed errors, the
# code lane's refusals and `RepoError` are all `ValueError`s, so their order relative to
# capture matters.
FAILURES: tuple[tuple[type[BaseException], str, str], ...] = (
    (BuildCancelled, "build_cancelled", "The build stopped before it finished. Reindex to run it again."),
    (BuildBusy, "build_busy", "Another build already owns this source. Try again in a moment."),
    (
        AuthorizationChanged,
        "authorization_changed",
        "Permission for this source changed while it was being built.",
    ),
    # Ahead of `OllamaError`, whose subclasses these are. A stale or mismatched profile asks
    # for a rebuild and is a 409; an unreachable model asks for a retry and is a 503. Reading
    # the wider row first would store the retry code for evidence that will never be
    # compatible again. `EmbeddingProfileUnavailable` is deliberately not here: it means the
    # model service could not answer, which really is the unavailable case.
    (EmbeddingProfileMismatch, _REBUILD_CODE, _REBUILD_MESSAGE),
    (EmbeddingProfileChanged, _REBUILD_CODE, _REBUILD_MESSAGE),
    (OllamaError, "model_unavailable", "The local model service was unavailable during the build."),
    (TooLarge, "source_too_large", "This source holds more text than a managed build accepts."),
    (UnsupportedProvenanceFormat, "unsupported_source", "This source is not plain prose a build can read."),
    (ManagedConfigurationError, "invalid_configuration", "Current indexing settings cannot build a source."),
    (ManagedIngressError, "invalid_source", _INVALID_SOURCE),
    # The code lane's refusals. `CaptureRefused` is an `InputCaptureError`, so it precedes
    # that row; `CodeBuildRefused` covers the coordinator's ceilings, its empty tree and its
    # unreadable history alike, because none of their words may reach the row. A clone
    # failure keeps the unknown code: git's reasons are not all the caller's to fix.
    (CaptureRefused, "invalid_source", _INVALID_CODE_SOURCE),
    (CodeBuildRefused, "invalid_source", _INVALID_CODE_SOURCE),
    (RepoError, UNKNOWN_CODE, "The repository could not be cloned. Check the local logs for this operation."),
    (InputCaptureError, "invalid_source", _INVALID_SOURCE),
)


def map_build_failure(exc: BaseException, *, has_active_generation: bool) -> ManagedFailure:
    """One closed exception-to-presentation mapping. Never `str(exc)`, never a detail."""
    if not isinstance(exc, BaseException):
        raise ManagedDispatchError("A raised exception is required")
    if type(has_active_generation) is not bool:
        raise ManagedDispatchError("Explicit generation awareness is required")
    code, message = UNKNOWN_CODE, UNKNOWN_MESSAGE
    for family, family_code, family_message in FAILURES:
        if isinstance(exc, family):
            code, message = family_code, family_message
            break
    cancelled = isinstance(exc, BuildCancelled)
    if has_active_generation:
        # The current generation is still published and still serving: this
        # attempt changed no pointer and no count, so the source stays ready.
        return ManagedFailure("ready", "refresh_cancelled" if cancelled else "refresh_failed", code, message)
    return ManagedFailure("failed", "cancelled" if cancelled else "failed", code, message)


def record_build_failure(ctx, *, source_id: str, operation_id: str, error: BaseException) -> ManagedFailure:
    """Present a failed managed attempt, generation-aware and without private detail."""
    source = ctx.store.get_source(source_id)
    failure = map_build_failure(
        error, has_active_generation=bool(source and source.get("active_generation_id"))
    )
    log.warning(
        "Managed build did not publish: source=%s operation=%s code=%s exception=%s",
        source_id,
        operation_id,
        failure.code,
        type(error).__name__,
    )
    present(
        ctx, source_id, status=failure.status, stage=failure.stage, error=f"{failure.code}: {failure.message}"
    )
    return failure


def record_build_receipt(ctx, *, source_id: str, receipt: BuildReceipt) -> None:
    """Publication owns `ready/ready` and the counts; an unchanged source needs its row back."""
    if type(receipt) is not BuildReceipt:
        raise ManagedDispatchError("A build receipt is required")
    if receipt.outcome == "published":
        return
    present(ctx, source_id, status="ready", stage="ready", error=None)


# ----------------------------------------------------------------- the build


def run_managed_build(
    ctx, *, source_id: str, actor: BuildActor, operation_id: str, job_key: str
) -> BuildReceipt:
    """Build one eligible source through its coordinator, from its saved bytes.

    Everything that can refuse - the tombstone, the ingress file, the effective
    options, a repository's clone URL - refuses before the raw root is created and
    before any model is asked anything. The coordinator is called with no ambient
    transaction, and cancellation is the job's own flag, never a shared process state.
    """
    check_actor(actor)
    if type(actor) is not BuildActor:
        raise ManagedDispatchError("Explicit immutable build actor required")
    if type(operation_id) is not str or OPERATION_ID.match(operation_id) is None:
        raise ManagedDispatchError("Operation identity must be a bounded printable token")
    if type(job_key) is not str or not job_key:
        raise ManagedDispatchError("A cancellation key is required")
    source = ctx.store.get_source(source_id)
    if source is None:
        raise ManagedDispatchError("Unknown source")
    eligibility = managed_eligibility(source)
    if eligibility == "tombstoned":
        raise ManagedDispatchError("A tombstoned source is never rebuilt")
    if eligibility == "unsupported":
        raise ManagedDispatchError("This source family has no managed build")
    if source.get("kind") == CONNECTOR_KIND:
        # Ruling R43 (review M14): a connector source is synced by the kit's runtime, over its own
        # partitions, and until Task 15 nothing routes a reader actor there. Refusing here keeps a
        # managed `connector` row out of the prose branch, which would read it as a saved file.
        raise ManagedDispatchError("A connector source is synced by the runtime, never rebuilt here")
    refresh = bool(source.get("active_generation_id"))
    if is_code_source(source):
        return _run_code_build(
            ctx, source, actor=actor, operation_id=operation_id, job_key=job_key, refresh=refresh
        )

    saved = ingress_file(ctx, source_id, stored_name=_recorded_name(source))
    options = build_options(ctx)
    spec = embedding_spec(ctx.ollama)
    store = RawArtifactStore(raw_root(ctx), max_object_bytes=int(ctx.config.max_upload_bytes))
    cache = EmbeddingCache(cache_root(ctx))

    def build(page: ChangePage, registry_fingerprint: str) -> BuildReceipt:
        """The lane's derivation half: the reviewed prose coordinator, unchanged (ruling R1).

        The connector's inventory is the same one saved file the coordinator captures, so `page`
        names nothing the capture does not already read; capture stays `FileInput`, which is the
        only capture that refuses an input changed while it was read.
        """
        return build_plain_source(
            ctx,
            source_id=source_id,
            actor=actor,
            inputs=(FileInput(saved.name, saved),),
            options=options,
            raw_store=store,
            embedding_spec=spec,
            operation_id=operation_id,
            should_stop=lambda: ctx.jobs.is_cancelled(job_key),
            on_progress=lambda progress: _present_progress(ctx, source_id, progress, refresh=refresh),
            embedding_cache=cache,
            registry_fingerprint=registry_fingerprint,
        )

    present(ctx, source_id, **_starting_fields(refresh))
    config = LocalSourceConfig(source_id=source_id, kind=source["kind"], root=str(saved))
    return run_coordinator_lane(
        LocalConnector(), config, CoordinatorLane("prose", build), registry=current_registry()
    )


def _run_code_build(
    ctx, source: Source, *, actor: BuildActor, operation_id: str, job_key: str, refresh: bool
) -> BuildReceipt:
    """The code lane: a tree this adapter owns, handed to `build_code_source`.

    An archive is captured straight from its saved `.zip`, whose members the capture walks
    under the existing zip budgets, and a code file from its one saved file. A repository
    is cloned into its own per-operation checkout -- never the legacy `repo/`, which the
    legacy lane keeps re-cloning for itself -- only after its URL has passed
    `repository_descriptor`, which refuses one carrying credentials, and that checkout is
    discarded however the build ends.
    """
    source_id = source["id"]
    options = code_build_options(ctx)
    spec = embedding_spec(ctx.ollama)
    if source.get("kind") != "repo":
        saved = ingress_file(ctx, source_id, stored_name=_recorded_name(source))
        tree = CodeTreeInput(root=saved, kind=source["kind"])
        present(ctx, source_id, **_starting_fields(refresh))
        return _build_code(ctx, source_id, actor, operation_id, job_key, refresh, tree, options, spec)

    url = _clone_url(source)
    descriptor = repository_descriptor(url)
    checkout = checkout_directory(ctx, source_id, operation_id)
    present(ctx, source_id, **_starting_fields(refresh))
    discard_checkout(ctx, source_id, operation_id)  # what a crashed attempt of this operation left
    try:
        repos.clone_repo(url, checkout, depth=clone_depth(options))
        tree = CodeTreeInput(
            root=checkout.resolve(),
            kind="repo",
            repository=descriptor,
            head_revision=repos.head_revision(checkout, timeout=options.git_timeout_seconds),
        )
        return _build_code(ctx, source_id, actor, operation_id, job_key, refresh, tree, options, spec)
    finally:
        discard_checkout(ctx, source_id, operation_id)


def _build_code(
    ctx,
    source_id: str,
    actor: BuildActor,
    operation_id: str,
    job_key: str,
    refresh: bool,
    tree: CodeTreeInput,
    options: CodeBuildOptions,
    spec: EmbeddingSpec,
) -> BuildReceipt:
    # Every raw object is a captured file or the manifest, both bounded by the capture's own
    # limits before anything is written, so the store's per-object cap is the larger of the two.
    limits = options.capture_limits
    store = RawArtifactStore(
        raw_root(ctx), max_object_bytes=max(limits.max_input_bytes, limits.max_manifest_bytes)
    )
    cache = EmbeddingCache(cache_root(ctx))
    return build_code_source(
        ctx,
        source_id=source_id,
        actor=actor,
        tree=tree,
        options=options,
        raw_store=store,
        embedding_spec=spec,
        operation_id=operation_id,
        should_stop=lambda: ctx.jobs.is_cancelled(job_key),
        on_progress=lambda progress: _present_progress(ctx, source_id, progress, refresh=refresh),
        embedding_cache=cache,
    )
