"""Capture a repository, an archive or a single code file as immutable accepted inputs.

The walk reproduces the legacy one (`repos._walk_files` and `readers._wanted_zip_member`)
file for file, and then says out loud what the legacy walk only did silently: every
entry it does not accept is recorded with one reason from `EXCLUSION_REASONS`, so a
partial tree is never presented as a complete one. Nothing is inferred from an error.

Two mechanisms, kept apart. An **exclusion** is a decision about one entry that leaves
the rest of the tree capturable -- an ignored directory, a symlink, a socket, a
submodule, a binary blob, an oversized file, a name no reader knows, a path the caller
excluded. A **refusal** (`CaptureRefused`) abandons the whole capture and produces no
inventory: a path that escapes the root, an archive nested inside an archive, a tree
past the file or byte rails, an unreadable file, a root that is not a tree, an archive
or a code file. Refusals over the rails are raised before any raw object is written.

Identity is the point of the ordering. The inventory is sorted by normalized logical
path before anything is captured, so reordering the walk -- or the filesystem's
directory listing -- cannot change `manifest.sha256`. The exclusion policy is folded
into the captured configuration under the reserved `capture` key so that changing it
is a different generation. The capture instant and the head revision are carried on
the result and are deliberately *not* hashed: plan section 5 keeps observation
timestamps out of identity, and the head commit enters through the repository
`ArtifactRevision` instead.

`ExcludedInput` in `hippo.knowledge.inputs` pins its reason to `configured_exclusion`,
so the canonical manifest records every exclusion under that one name. The finer
reason lives on `RepositoryCapture.exclusions` and reaches the generation through
`coverage_json` (plan section 9).

`repository_descriptor` derives the provisional repository identity of a clone URL.
It keeps the whole path rather than `repos.repo_name`'s last two segments, which
collide for any subgroup layout, and it is carried on the result rather than hashed.

`readers.py` is read-only here: this module consumes `IGNORED_DIRS`,
`is_supported_name`, `is_code_name`, `is_probably_binary` and `check_zip_budgets`,
and adds no reader predicate of its own.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile, ZipInfo

from ..codegraph.model import CODE_MAX_FILES
from ..knowledge.identity import normalize_provider_url, normalize_relative_path
from ..knowledge.inputs import (
    AcceptedInputs,
    ByteInput,
    CaptureLimits,
    ExcludedInput,
    FileInput,
    InputCaptureError,
)
from ..knowledge.raw_artifacts import RawArtifactStore
from . import readers
from .accepted_inputs import capture_raw_inputs

# Why one entry was not captured. Closed, sorted, and the only names a caller sees.
EXCLUSION_REASONS = (
    "binary",
    "configured_exclusion",
    "ignored_path",
    "not_regular",
    "submodule",
    "symlink",
    "too_large",
    "unsupported_language",
)
# Why no inventory was produced at all.
REFUSAL_REASONS = (
    "archive_budget",
    "damaged_archive",
    "duplicate_path",
    "escaping_path",
    "input_bytes",
    "nested_archive",
    "repository_without_checkout",
    "reserved_configuration",
    "too_many_files",
    "total_bytes",
    "unportable_path",
    "unreadable",
    "unsupported_repository_url",
    "unsupported_root",
)
# The reserved key `capture_repository_inputs` adds to the captured configuration.
CONFIGURATION_KEY = "capture"
# Archive suffixes, as `accepted_inputs._CONTAINER_SUFFIXES` spells them. Inside an
# archive these refuse, because an archive in an archive has no capture contract; in
# a checkout they are an ordinary `unsupported_language` exclusion, so one vendored
# tarball cannot fail a repository.
ARCHIVE_SUFFIXES = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar")

SourceKind = Literal["repo", "archive", "file"]
Descriptor = ByteInput | FileInput

# `git@host:owner/name.git`, the scp-like clone form that carries no scheme. The
# path may not start with `/`, which is what keeps `https://host/...` out of it.
_SCP_LIKE = re.compile(r"^(?:[A-Za-z0-9._\-]+@)?(?P<host>[A-Za-z0-9.\-]+):(?P<path>[^/].*)$")


class CaptureRefused(InputCaptureError):
    """No inventory was produced; `reason` is one of `REFUSAL_REASONS`.

    Messages never quote the offending URL or path: a clone URL can carry a
    credential, and plan section 10 keeps both out of logs and public errors.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError(f"Unknown capture refusal reason: {reason!r}")
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RepositoryDescriptor:
    """The provisional repository identity a clone URL stands for, until a connector.

    `provider_instance` is the forge, in the canonical form
    `knowledge.identity.repository_key` normalizes; `provider_repository_id` is the
    repository's **full** path on it. Feed the pair straight to
    `identity.repository_identity`.
    """

    provider_instance: str
    provider_repository_id: str

    def __post_init__(self) -> None:
        if self.provider_instance != normalize_provider_url(self.provider_instance):
            raise ValueError("The provider instance must already be canonical")
        parts = self.provider_repository_id.split("/")
        if (
            not self.provider_repository_id
            or not all(parts)
            or self.provider_repository_id != "/".join(part.lower() for part in parts)
        ):
            raise ValueError("The repository id must be a nonempty lowercase relative path")


def repository_descriptor(url: str) -> RepositoryDescriptor:
    """Derive the provisional repository identity of a clone URL (plan section 5).

    Two normalizations are chosen here, because minting two identities for one
    repository is the failure that matters and a later connector can add an alias
    but cannot un-merge evidence:

    * **The whole path is kept.** `repos.repo_name` returns only the last two
      segments, so `host/alpha/team/api` and `host/beta/team/api` collide into one
      `repository` object and merge their symbol identities. It is referenced here
      and deliberately not reused.
    * **Host and path both fold to lowercase, and transport is ignored.**
      `host/Acme/Robots`, `host/acme/robots`, the `ssh://` form and the scp-like
      form are one repository on every major forge, so they get one identity. The
      cost is a forge with case-sensitive paths, which Task 10's connector fixes by
      replacing this provisional identity with real provider IDs.

    A trailing `.git` is dropped. An `http(s)` URL carrying userinfo refuses rather
    than being silently stripped: that is how a personal access token is passed.
    """
    if not isinstance(url, str) or not (candidate := url.strip()):
        raise CaptureRefused("A repository needs a clone URL", reason="unsupported_repository_url")
    if candidate.startswith("-") or any(character.isspace() for character in candidate):
        raise CaptureRefused("The clone URL is not a remote URL", reason="unsupported_repository_url")
    if any(character in candidate for character in "?#\\"):
        raise CaptureRefused(
            "A clone URL carries no query, fragment or backslash", reason="unsupported_repository_url"
        )
    scheme, host, port, path = _split_clone_url(candidate)
    instance = f"{scheme}://[{host}]" if ":" in host else f"{scheme}://{host}"
    try:
        return RepositoryDescriptor(
            normalize_provider_url(instance if port is None else f"{instance}:{port}"),
            _repository_path(path),
        )
    except ValueError as error:
        raise CaptureRefused(
            "The clone URL names no repository on a usable host", reason="unsupported_repository_url"
        ) from error


def _split_clone_url(candidate: str) -> tuple[str, str, int | None, str]:
    """Lowercase host, identity-bearing port and raw path of a clone URL.

    Every transport folds to `https`, the label a forge is identified by, so one
    repository reached over `https`, `http`, `ssh` or the scp-like form is one
    identity. An `ssh` port is a transport detail and is dropped; a scheme's own
    default port is dropped before the fold, so `http://host:80` and `http://host`
    cannot become two forges.
    """
    if match := _SCP_LIKE.match(candidate):
        # `user:secret@host:path` matches too, with `user` as the host, because `:` is outside
        # the user class and so the secret lands in the path. A path with an `@` in it is
        # refused rather than guessed at (R21-m15).
        if "@" in match["path"]:
            raise CaptureRefused(
                "A clone URL must not carry credentials", reason="unsupported_repository_url"
            )
        return "https", match["host"].lower(), None, match["path"]
    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in ("https", "http", "ssh"):
        raise CaptureRefused(
            "A clone URL must be https, http, ssh or the scp-like form",
            reason="unsupported_repository_url",
        )
    if parsed.password is not None or (parsed.username is not None and scheme != "ssh"):
        raise CaptureRefused("A clone URL must not carry credentials", reason="unsupported_repository_url")
    try:
        host, port = parsed.hostname, parsed.port
    except ValueError as error:
        raise CaptureRefused(
            "The clone URL has no usable host", reason="unsupported_repository_url"
        ) from error
    if not host:
        raise CaptureRefused("The clone URL has no usable host", reason="unsupported_repository_url")
    if scheme == "ssh" or (scheme, port) in (("https", 443), ("http", 80)):
        port = None
    return "https", host.lower(), port, parsed.path


def _repository_path(path: str) -> str:
    segments = [segment for segment in unquote(path).split("/") if segment]
    if segments and segments[-1].lower().endswith(".git"):
        segments[-1] = segments[-1][: -len(".git")]
    if (
        not segments
        or not all(segments)
        or any(segment in (".", "..") for segment in segments)
        or any(ord(character) < 32 or ord(character) == 127 for segment in segments for character in segment)
    ):
        raise CaptureRefused("The clone URL names no repository path", reason="unsupported_repository_url")
    return "/".join(segment.lower() for segment in segments)


@dataclass(frozen=True, slots=True)
class ExcludedFile:
    """One entry the walk declined, with the reason it declined it."""

    logical_path: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "logical_path", normalize_relative_path(self.logical_path))
        if self.reason not in EXCLUSION_REASONS:
            raise ValueError(f"Unknown capture exclusion reason: {self.reason!r}")


@dataclass(frozen=True, slots=True)
class CaptureInventory:
    """The ordered, normalized, bounded tree; nothing here has been captured yet."""

    kind: SourceKind
    root: Path
    inputs: tuple[Descriptor, ...]
    byte_lengths: tuple[int, ...]
    exclusions: tuple[ExcludedFile, ...]

    def __post_init__(self) -> None:
        if self.kind not in ("repo", "archive", "file"):
            raise ValueError("Unknown capture source kind")
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "byte_lengths", tuple(self.byte_lengths))
        object.__setattr__(self, "exclusions", tuple(self.exclusions))
        if any(type(item) not in (ByteInput, FileInput) for item in self.inputs):
            raise ValueError("Capture inputs must be immutable explicit descriptors")
        if any(type(item) is not ExcludedFile for item in self.exclusions):
            raise ValueError("Capture exclusions must be frozen ExcludedFile values")
        if len(self.inputs) != len(self.byte_lengths) or any(
            type(value) is not int or value < 0 for value in self.byte_lengths
        ):
            raise ValueError("Every capture input needs a nonnegative byte length")
        paths = [item.logical_path for item in (*self.inputs, *self.exclusions)]
        if len(paths) != len(set(paths)):
            raise ValueError("Duplicate logical path in the capture inventory")
        if [item.logical_path for item in self.inputs] != sorted(
            item.logical_path for item in self.inputs
        ) or [item.logical_path for item in self.exclusions] != sorted(
            item.logical_path for item in self.exclusions
        ):
            raise ValueError("Capture inventory must be ordered by normalized logical path")

    @property
    def total_bytes(self) -> int:
        return sum(self.byte_lengths)

    @property
    def descriptors(self) -> tuple[Descriptor | ExcludedInput, ...]:
        """Accepted and excluded descriptors interleaved in one canonical order."""
        merged: list[Descriptor | ExcludedInput] = [
            *self.inputs,
            *(ExcludedInput(item.logical_path) for item in self.exclusions),
        ]
        return tuple(sorted(merged, key=lambda item: item.logical_path))


@dataclass(frozen=True, slots=True)
class RepositoryCapture:
    """An immutable accepted inventory plus everything identity deliberately excludes."""

    kind: SourceKind
    root: Path
    inputs: tuple[Descriptor, ...]
    exclusions: tuple[ExcludedFile, ...]
    accepted: AcceptedInputs
    observed_at: datetime
    provider_revision: str | None
    repository: RepositoryDescriptor | None = None

    def __post_init__(self) -> None:
        if type(self.accepted) is not AcceptedInputs:
            raise ValueError("A repository capture requires an immutable accepted inventory")
        if self.repository is not None and type(self.repository) is not RepositoryDescriptor:
            raise ValueError("A repository capture requires a frozen RepositoryDescriptor")
        # Backstop for the refusal `capture_repository_inputs` raises before any raw
        # write; plan section 5 gives an archive or a single file no repository.
        if self.repository is not None and self.kind != "repo":
            raise ValueError("Only a checkout can carry a repository descriptor")
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "exclusions", tuple(self.exclusions))
        if type(self.observed_at) is not datetime or self.observed_at.utcoffset() is None:
            raise ValueError("The capture instant must be an explicit timezone-aware datetime")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        if self.provider_revision is not None and (
            type(self.provider_revision) is not str or not self.provider_revision
        ):
            raise ValueError("provider_revision must be nonempty text, never filesystem metadata")

    @property
    def manifest_hash(self) -> str:
        return self.accepted.manifest.sha256


# ------------------------------------------------------------------ walk


def walk_tree(
    root: Path | str,
    *,
    exclusions: Iterable[str] = (),
    max_files: int = CODE_MAX_FILES,
    max_file_bytes: int = readers.MAX_FILE_BYTES,
) -> CaptureInventory:
    """Enumerate a checkout, a `.zip` or a single code file into one ordered inventory.

    No bytes are stored and nothing is decoded; this decides only what the capture
    will accept and why it declined the rest.
    """
    if type(max_files) is not int or max_files <= 0 or type(max_file_bytes) is not int:
        raise ValueError("Capture rails must be explicit positive integers")
    resolved = _resolve_root(root)
    policy = normalized_exclusions(exclusions)
    if resolved.is_dir():
        kind, inputs, lengths, excluded = "repo", *_walk_directory(resolved, policy, max_file_bytes)
    elif resolved.suffix.lower() == ".zip":
        kind, inputs, lengths, excluded = "archive", *_walk_archive(resolved, policy, max_file_bytes)
    elif readers.is_code_name(resolved.name):
        kind, inputs, lengths, excluded = "file", *_walk_single_file(resolved, policy, max_file_bytes)
    else:
        raise CaptureRefused(
            "Managed code capture accepts a checkout, a .zip or one code file",
            reason="unsupported_root",
        )
    if len(inputs) > max_files:
        raise CaptureRefused(
            f"The tree holds {len(inputs)} capturable files; the rail is {max_files}",
            reason="too_many_files",
        )
    order = sorted(range(len(inputs)), key=lambda index: inputs[index].logical_path)
    return CaptureInventory(
        kind=kind,
        root=resolved,
        inputs=tuple(inputs[index] for index in order),
        byte_lengths=tuple(lengths[index] for index in order),
        exclusions=tuple(sorted(excluded, key=lambda item: item.logical_path)),
    )


def normalized_exclusions(exclusions: Iterable[str]) -> tuple[str, ...]:
    """The caller's exclusion policy as sorted, deduplicated, normalized relative paths."""
    if isinstance(exclusions, str):
        raise ValueError("The exclusion policy must be a collection of relative paths")
    return tuple(sorted({normalize_relative_path(item) for item in exclusions}))


def _resolve_root(root: Path | str) -> Path:
    try:
        return Path(root).resolve(strict=True)
    except OSError as error:
        raise CaptureRefused("The capture root does not exist", reason="unsupported_root") from error


def _is_excluded(logical_path: str, policy: Sequence[str]) -> bool:
    return any(logical_path == item or logical_path.startswith(item + "/") for item in policy)


def _normalized(logical_path: str) -> str:
    """Normalize one logical path, distinguishing the two ways it can be unusable.

    A name that climbs out of the root is a different problem from a name that
    simply has no portable relative spelling -- a backslash or a control character
    -- so they refuse under different reasons and a reader is not told that a
    legally named file escaped anything.
    """
    try:
        return normalize_relative_path(logical_path)
    except ValueError as error:
        if "\\" in logical_path or any(ord(char) < 32 for char in logical_path):
            raise CaptureRefused(
                "A captured name has no portable relative spelling", reason="unportable_path"
            ) from error
        raise CaptureRefused("A captured path escapes its root", reason="escaping_path") from error


def _unreadable() -> CaptureRefused:
    """One refusal for every entry the walk cannot open, stat or list."""
    return CaptureRefused("A captured entry could not be read", reason="unreadable")


def _sniffed_binary(path: Path) -> bool:
    """The same head `readers.is_supported` and `readers.read_bytes` look at."""
    try:
        with path.open("rb") as handle:
            return readers.is_probably_binary(handle.read(readers.BINARY_SNIFF_BYTES))
    except OSError as error:
        raise _unreadable() from error


def _name_reason(name: str) -> str | None:
    """`unsupported_language` for a suffix no reader knows; None when the name is fine.

    An extensionless name that is not a known one is left to the content sniff,
    exactly as `readers.is_supported` decides it.
    """
    if readers.is_supported_name(name) or not PurePosixPath(name).suffix:
        return None
    return "unsupported_language"


def _walk_directory(
    root: Path, policy: Sequence[str], max_file_bytes: int
) -> tuple[list[Descriptor], list[int], list[ExcludedFile]]:
    inputs: list[Descriptor] = []
    lengths: list[int] = []
    excluded: list[ExcludedFile] = []
    pending = [""]
    while pending:
        relative = pending.pop()
        directory = root / relative if relative else root
        try:
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda entry: entry.name)
        except OSError as error:
            raise _unreadable() from error
        for entry in children:
            logical = _normalized(f"{relative}/{entry.name}" if relative else entry.name)
            try:
                reason = _directory_entry_reason(entry, logical, policy, max_file_bytes)
                size = 0 if reason else entry.stat(follow_symlinks=False).st_size
            except OSError as error:
                raise _unreadable() from error
            if reason == "descend":
                pending.append(logical)
            elif reason is not None:
                excluded.append(ExcludedFile(logical, reason))
            else:
                inputs.append(FileInput(logical, Path(entry.path)))
                lengths.append(size)
    return inputs, lengths, excluded


def _directory_entry_reason(
    entry: os.DirEntry[str], logical: str, policy: Sequence[str], max_file_bytes: int
) -> str | None:
    """The exclusion reason for one directory entry, `"descend"`, or None to accept.

    The order reproduces `repos._walk_files`: link and type first, then the ignore
    rules, then size, then whether any reader knows the name, then the content sniff.
    """
    if entry.is_symlink():
        return "symlink"
    if _is_excluded(logical, policy):
        return "configured_exclusion"
    if entry.is_dir(follow_symlinks=False):
        if entry.name in readers.IGNORED_DIRS or entry.name.startswith("."):
            return "ignored_path"
        # A checkout inside a checkout is another repository's history; the root's
        # own `.git` is never reached here, only a child's.
        return "submodule" if os.path.lexists(os.path.join(entry.path, ".git")) else "descend"
    if not entry.is_file(follow_symlinks=False):
        return "not_regular"
    if entry.name.startswith("."):
        return "ignored_path"
    if entry.stat(follow_symlinks=False).st_size > max_file_bytes:
        return "too_large"
    return _name_reason(entry.name) or ("binary" if _sniffed_binary(Path(entry.path)) else None)


def _walk_archive(
    archive_path: Path, policy: Sequence[str], max_file_bytes: int
) -> tuple[list[Descriptor], list[int], list[ExcludedFile]]:
    inputs: list[Descriptor] = []
    lengths: list[int] = []
    excluded: list[ExcludedFile] = []
    try:
        with ZipFile(archive_path) as package:
            readable: list[tuple[str, ZipInfo]] = []
            seen: set[str] = set()
            for member in sorted(package.infolist(), key=lambda member: member.filename):
                if member.is_dir():
                    continue
                logical = _normalized(member.filename)
                # A zip may hold two members whose names normalize to one logical
                # path; there is no honest way to choose between their bytes.
                if logical in seen:
                    raise CaptureRefused(
                        "Two archive members claim one logical path", reason="duplicate_path"
                    )
                seen.add(logical)
                reason = _member_reason(member, logical, policy, max_file_bytes)
                if reason is not None:
                    excluded.append(ExcludedFile(logical, reason))
                else:
                    readable.append((logical, member))
            # The budget is taken over exactly the members read below, and before any of them
            # is: an extensionless name is left to the content sniff, so it is read like a named
            # one and counts like one (R21-M8). The refusal is this module's own sentence;
            # `TooLarge` quotes the archive's name (R21-m21).
            try:
                readers.check_zip_budgets([member for _logical, member in readable], archive_path.name)
            except readers.TooLarge as error:
                raise CaptureRefused(
                    "The archive holds more readable files or unpacked bytes than its budget allows",
                    reason="archive_budget",
                ) from error
            for logical, member in readable:
                data = package.read(member)
                if readers.is_probably_binary(data):
                    excluded.append(ExcludedFile(logical, "binary"))
                    continue
                inputs.append(ByteInput(logical, data))
                lengths.append(len(data))
    except BadZipFile as error:
        raise CaptureRefused("The archive could not be read", reason="damaged_archive") from error
    return inputs, lengths, excluded


def _member_reason(member: ZipInfo, logical: str, policy: Sequence[str], max_file_bytes: int) -> str | None:
    """The exclusion reason for one archive member, or None to read it and sniff its content.

    After the one refusal an archive adds, the order is `_directory_entry_reason`'s: link and
    type, then the ignore rules, then size, then the name. A member's type is the Unix mode a
    zip keeps in the high bits of `external_attr`. A zip written on Windows, or by
    `ZipFile.writestr` from a bare name, records no type at all, and that is a plain file.
    """
    parts = PurePosixPath(logical).parts
    if logical.lower().endswith(ARCHIVE_SUFFIXES):
        raise CaptureRefused("An archive inside an archive has no capture contract", reason="nested_archive")
    kind = stat.S_IFMT(member.external_attr >> 16)
    if kind == stat.S_IFLNK:
        return "symlink"
    if kind not in (0, stat.S_IFREG):
        return "not_regular"
    if _is_excluded(logical, policy):
        return "configured_exclusion"
    if any(part in readers.IGNORED_DIRS or part.startswith(".") for part in parts[:-1]):
        return "ignored_path"
    if parts[-1].startswith(".") and not readers.is_supported_name(parts[-1]):
        return "ignored_path"
    if member.file_size > max_file_bytes:
        return "too_large"
    return _name_reason(parts[-1])


def _walk_single_file(
    path: Path, policy: Sequence[str], max_file_bytes: int
) -> tuple[list[Descriptor], list[int], list[ExcludedFile]]:
    logical = _normalized(path.name)
    try:
        size = path.stat().st_size
    except OSError as error:
        raise _unreadable() from error
    reason = (
        "configured_exclusion"
        if _is_excluded(logical, policy)
        else "too_large"
        if size > max_file_bytes
        else _name_reason(path.name) or ("binary" if _sniffed_binary(path) else None)
    )
    if reason is not None:
        return [], [], [ExcludedFile(logical, reason)]
    return [FileInput(logical, path)], [size], []


# --------------------------------------------------------------- capture


def capture_repository_inputs(
    root: Path | str,
    *,
    raw_store: RawArtifactStore,
    source_id: str,
    workspace_id: str,
    limits: CaptureLimits,
    configuration: dict,
    observed_at: datetime,
    exclusions: Iterable[str] = (),
    provider_revision: str | None = None,
    repository: RepositoryDescriptor | None = None,
    max_files: int = CODE_MAX_FILES,
    max_file_bytes: int = readers.MAX_FILE_BYTES,
    should_stop: Callable[[], bool] | None = None,
) -> RepositoryCapture:
    """Walk a tree, archive or code file and capture it as one immutable inventory.

    The rails are checked before any raw object is written, so a tree that is too
    large leaves the raw store untouched. `observed_at` and `provider_revision` are
    carried on the result and never enter `manifest.sha256`; the exclusion policy and
    the source kind do, under the reserved `capture` configuration key.
    """
    if type(configuration) is not dict:
        raise ValueError("Capture requires explicit JSON configuration settings")
    if CONFIGURATION_KEY in configuration:
        raise CaptureRefused(
            f"The {CONFIGURATION_KEY!r} configuration key belongs to repository capture",
            reason="reserved_configuration",
        )
    if type(limits) is not CaptureLimits:
        raise ValueError("Capture requires typed limits")
    inventory = walk_tree(root, exclusions=exclusions, max_files=max_files, max_file_bytes=max_file_bytes)
    # Plan section 5: only a checkout has a repository. Checked here, where the kind
    # is first known, so the refusal still precedes every raw write.
    if repository is not None and inventory.kind != "repo":
        raise CaptureRefused(
            "Only a checkout can carry a repository descriptor", reason="repository_without_checkout"
        )
    if inventory.total_bytes > limits.max_total_bytes:
        raise CaptureRefused(
            f"The tree holds {inventory.total_bytes} capturable bytes; the limit is {limits.max_total_bytes}",
            reason="total_bytes",
        )
    if any(length > limits.max_input_bytes for length in inventory.byte_lengths):
        raise CaptureRefused(
            f"A captured file exceeds the {limits.max_input_bytes} byte per-input limit",
            reason="input_bytes",
        )
    settings = dict(configuration) | {
        CONFIGURATION_KEY: {
            "kind": inventory.kind,
            "exclusions": list(normalized_exclusions(exclusions)),
        }
    }
    accepted = capture_raw_inputs(
        raw_store,
        source_id=source_id,
        workspace_id=workspace_id,
        inputs=inventory.descriptors,
        configuration=settings,
        limits=limits,
        should_stop=should_stop,
    )
    return RepositoryCapture(
        kind=inventory.kind,
        root=inventory.root,
        inputs=inventory.inputs,
        exclusions=inventory.exclusions,
        accepted=accepted,
        observed_at=observed_at,
        provider_revision=provider_revision,
        repository=repository,
    )


__all__ = [
    "ARCHIVE_SUFFIXES",
    "CONFIGURATION_KEY",
    "EXCLUSION_REASONS",
    "REFUSAL_REASONS",
    "CaptureInventory",
    "CaptureLimits",
    "CaptureRefused",
    "ExcludedFile",
    "RepositoryCapture",
    "RepositoryDescriptor",
    "capture_repository_inputs",
    "normalized_exclusions",
    "repository_descriptor",
    "walk_tree",
]
