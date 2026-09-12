"""Capture explicitly supplied raw bytes/files into a complete accepted inventory.

No production source, job, network, reader or model is consulted. Configuration
contains caller-selected input settings, never a whole application Config object.
File paths and raw-store locations never enter the canonical manifest. Callers
must exclude hostile local writers from input paths and their ancestors. Descriptor
metadata detects ordinary changes, not immutable repository/history attestation.
Failures may leave immutable content-addressed blobs; reachability/GC is separate.
"""

from __future__ import annotations

import io
import json
import os
import stat
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO, Literal

from ..knowledge.identity import canonical_json, make_identity, normalize_json, normalize_relative_path
from ..knowledge.raw_artifacts import RawArtifact, RawArtifactStore, RawArtifactTooLarge
from .provenance import RawInput

_CONTAINER_SUFFIXES = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".git")
_CONTAINER_MEDIA = {"application/zip", "application/x-tar", "application/gzip", "application/x-git"}


def _text(value: str, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be nonempty text")


def _descriptor(item) -> None:
    object.__setattr__(item, "logical_path", normalize_relative_path(item.logical_path))
    _text(item.media_type, "media_type")
    if item.provider_revision is not None and type(item.provider_revision) is not str:
        raise ValueError("provider_revision must be text, never filesystem metadata")


@dataclass(frozen=True, slots=True)
class ByteInput:
    logical_path: str
    data: bytes
    media_type: str = "text/plain"
    provider_revision: str | None = None

    def __post_init__(self) -> None:
        _descriptor(self)
        if type(self.data) is not bytes:
            raise ValueError("ByteInput requires immutable original bytes")


@dataclass(frozen=True, slots=True)
class FileInput:
    logical_path: str
    path: Path
    media_type: str = "text/plain"
    provider_revision: str | None = None

    def __post_init__(self) -> None:
        _descriptor(self)
        path = Path(self.path)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("Physical input path must be absolute without parent traversal")
        object.__setattr__(self, "path", path)


@dataclass(frozen=True, slots=True)
class ExcludedInput:
    logical_path: str
    reason: Literal["configured_exclusion"] = "configured_exclusion"

    def __post_init__(self) -> None:
        object.__setattr__(self, "logical_path", normalize_relative_path(self.logical_path))
        if self.reason != "configured_exclusion":
            raise ValueError("Unknown exclusion policy")


@dataclass(frozen=True, slots=True)
class CaptureLimits:
    max_input_bytes: int
    max_total_bytes: int
    max_inputs: int
    max_manifest_bytes: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError("Capture limits must be explicit positive integers")


@dataclass(frozen=True, slots=True)
class InputDisposition:
    input_key: str
    logical_path: str
    outcome: Literal["accepted", "excluded", "failed"]
    reason: str
    byte_length: int | None = None
    raw_hash: str | None = None

    def __post_init__(self) -> None:
        _text(self.input_key, "input_key")
        object.__setattr__(self, "logical_path", normalize_relative_path(self.logical_path))
        reasons = {
            "accepted": {"captured"},
            "excluded": {"configured_exclusion"},
            "failed": {
                "unreadable",
                "unsupported_container",
                "size_limit",
                "changed_during_capture",
                "storage_failure",
            },
        }
        if (
            type(self.outcome) is not str
            or self.outcome not in reasons
            or self.reason not in reasons[self.outcome]
        ):
            raise ValueError("Unknown input disposition")
        if self.outcome == "accepted":
            RawArtifact("hippo-raw:sha256:" + (self.raw_hash or ""), self.raw_hash, self.byte_length)
        elif self.byte_length is not None or self.raw_hash is not None:
            raise ValueError("Uncaptured input cannot attest raw bytes")


class InputCaptureError(ValueError):
    """No accepted inventory was produced; dispositions are diagnostic only."""

    def __init__(self, message: str, *, dispositions: tuple[InputDisposition, ...] = ()) -> None:
        super().__init__(message)
        self.dispositions = tuple(dispositions)


class CaptureTooLarge(InputCaptureError):
    pass


class UnsupportedCaptureInput(InputCaptureError):
    pass


class CaptureCancelled(RuntimeError):
    """A build outcome, never an exclusion or successful partial inventory."""

    def __init__(self, dispositions: tuple[InputDisposition, ...] = ()) -> None:
        super().__init__("Input capture cancelled")
        self.dispositions = tuple(dispositions)


def _input_key(workspace_id: str, source_id: str, logical_path: str) -> str:
    return make_identity("raw_input", [workspace_id, source_id, logical_path])


def _manifest_bytes(source_id, workspace_id, inputs, dispositions, configuration_json, limits) -> bytes:
    return canonical_json(
        {
            "version": 1,
            "source_id": source_id,
            "workspace_id": workspace_id,
            "inputs": [
                {
                    "input_key": item.input_key,
                    "logical_path": item.logical_path,
                    "media_type": item.media_type,
                    "raw_hash": item.raw_hash,
                    "byte_length": item.byte_length,
                    "provider_revision": item.provider_revision,
                    "container_chain": item.container_chain,
                }
                for item in inputs
            ],
            "dispositions": [asdict(item) for item in dispositions],
            "configuration": json.loads(configuration_json),
            "limits": asdict(limits),
        }
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class AcceptedInputs:
    source_id: str
    workspace_id: str
    inputs: tuple[RawInput, ...]
    dispositions: tuple[InputDisposition, ...]
    configuration_json: str
    limits: CaptureLimits
    manifest: RawArtifact

    def __post_init__(self) -> None:
        _text(self.source_id, "source_id")
        _text(self.workspace_id, "workspace_id")
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "dispositions", tuple(self.dispositions))
        if type(self.limits) is not CaptureLimits or type(self.manifest) is not RawArtifact:
            raise ValueError("Accepted inventory requires immutable limits and manifest reference")
        if any(type(item) is not RawInput for item in self.inputs) or any(
            type(item) is not InputDisposition for item in self.dispositions
        ):
            raise ValueError("Accepted inventory requires immutable typed records")
        if (
            normalize_json(self.configuration_json) != self.configuration_json
            or type(json.loads(self.configuration_json)) is not dict
        ):
            raise ValueError("Configuration must be a canonical JSON object")
        paths = [item.logical_path for item in self.dispositions]
        if len(paths) != len(set(paths)) or any(item.outcome == "failed" for item in self.dispositions):
            raise ValueError("Accepted inventory cannot contain duplicate paths or failed inputs")
        if any(
            item.input_key != _input_key(self.workspace_id, self.source_id, item.logical_path)
            for item in (*self.inputs, *self.dispositions)
        ):
            raise ValueError("Accepted input identity belongs to another source or path")
        expected = [
            InputDisposition(
                item.input_key, item.logical_path, "accepted", "captured", item.byte_length, item.raw_hash
            )
            for item in self.inputs
        ]
        if expected != [item for item in self.dispositions if item.outcome == "accepted"]:
            raise ValueError("Accepted dispositions must exactly describe ordered captured inputs")
        if (
            len(self.dispositions) > self.limits.max_inputs
            or self.total_bytes > self.limits.max_total_bytes
            or any(item.byte_length > self.limits.max_input_bytes for item in self.inputs)
        ):
            raise CaptureTooLarge("Accepted inventory exceeds capture limits")
        data = self.manifest_bytes
        if len(data) > self.limits.max_manifest_bytes:
            raise CaptureTooLarge("Accepted manifest exceeds capture limit")
        if self.manifest.sha256 != sha256(data).hexdigest() or self.manifest.byte_length != len(data):
            raise ValueError("Manifest reference does not match the accepted inventory")

    @property
    def manifest_bytes(self) -> bytes:
        return _manifest_bytes(
            self.source_id,
            self.workspace_id,
            self.inputs,
            self.dispositions,
            self.configuration_json,
            self.limits,
        )

    @property
    def total_bytes(self) -> int:
        return sum(item.byte_length for item in self.inputs)

    @property
    def outcome(self) -> Literal["empty_inventory", "all_excluded", "accepted"]:
        return "accepted" if self.inputs else "all_excluded" if self.dispositions else "empty_inventory"


def _checkpoint(should_stop, dispositions=()) -> None:
    if should_stop and should_stop():
        raise CaptureCancelled(tuple(dispositions))


@contextmanager
def _open_file(path: Path) -> Iterator[BinaryIO]:
    """Pin each directory; do not follow symlinks or block on FIFO inputs."""
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("Input must be a regular file")
        stream = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        yield stream


def _file_version(stream: BinaryIO) -> tuple[int, ...]:
    info = os.fstat(stream.fileno())
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class _InputReadError(OSError):
    pass


class _StorageFailure(ValueError):
    pass


class _CaptureReader:
    def __init__(self, stream, limit, should_stop, dispositions):
        self.stream = stream
        self.limit = limit
        self.should_stop = should_stop
        self.dispositions = dispositions
        self.length = 0
        self.digest = sha256()
        self.finished = False

    def read(self, size: int) -> bytes:
        _checkpoint(self.should_stop, self.dispositions)
        if type(size) is not int or size <= 0:
            raise ValueError("Raw sink must use bounded reads")
        wanted = min(size, self.limit - self.length + 1)
        try:
            chunk = self.stream.read(wanted)
        except OSError as error:
            raise _InputReadError("Input bytes could not be read") from error
        if type(chunk) is not bytes or len(chunk) > wanted:
            raise ValueError("Capture input must honor bounded binary reads")
        self.length += len(chunk)
        if self.length > self.limit:
            raise CaptureTooLarge("Input bytes exceed the per-input or aggregate limit")
        self.digest.update(chunk)
        self.finished = not chunk
        return chunk

    def verify(self, artifact: RawArtifact) -> None:
        if (
            type(artifact) is not RawArtifact
            or not self.finished
            or artifact.byte_length != self.length
            or artifact.sha256 != self.digest.hexdigest()
        ):
            raise ValueError("Raw sink did not attest the complete descriptor bytes")


class _ChangedInput(ValueError):
    pass


def _capture_one(raw_store, item, limit, should_stop, dispositions) -> RawArtifact:
    def copy(stream):
        reader = _CaptureReader(stream, limit, should_stop, dispositions)
        try:
            artifact = raw_store.put_stream(reader)
        except _InputReadError:
            raise
        except OSError as error:
            raise _StorageFailure("Raw storage could not accept the bytes") from error
        reader.verify(artifact)
        _checkpoint(should_stop, dispositions)
        return artifact

    if type(item) is ByteInput:
        if len(item.data) > limit:
            raise CaptureTooLarge("Input bytes exceed the per-input or aggregate limit")
        return copy(io.BytesIO(item.data))
    with _open_file(item.path) as stream:
        before = _file_version(stream)
        if before[2] > limit:
            raise CaptureTooLarge("Input bytes exceed the per-input or aggregate limit")
        artifact = copy(stream)
        if _file_version(stream) != before or artifact.byte_length != before[2]:
            raise _ChangedInput("Input file changed during capture")
        return artifact


def capture_raw_inputs(
    raw_store: RawArtifactStore,
    *,
    source_id: str,
    workspace_id: str,
    inputs: Iterable[ByteInput | FileInput | ExcludedInput],
    configuration: dict,
    limits: CaptureLimits,
    should_stop: Callable[[], bool] | None = None,
) -> AcceptedInputs:
    """Capture an explicit ordered inventory or raise without a success result.

    Empty inventory, all-excluded inventory and accepted zero-byte files remain
    distinct. Downstream policy decides whether any permits publication. Limits
    include every descriptor in max_inputs; identical content is charged once per
    logical input toward max_total_bytes. No exclusion is inferred from an error.
    """
    _text(source_id, "source_id")
    _text(workspace_id, "workspace_id")
    if type(limits) is not CaptureLimits or type(configuration) is not dict:
        raise ValueError("Capture requires typed limits and explicit JSON configuration settings")
    _checkpoint(should_stop)
    try:
        configuration_json = canonical_json(configuration)
    except RecursionError as error:
        raise ValueError("Configuration nesting exceeds canonical JSON bounds") from error
    if len(configuration_json.encode("utf-8")) > limits.max_manifest_bytes:
        raise CaptureTooLarge("Configuration exceeds manifest byte limit")
    descriptors = []
    paths = set()
    for item in inputs:
        _checkpoint(should_stop)
        if type(item) not in (ByteInput, FileInput, ExcludedInput):
            raise ValueError("Capture requires immutable explicit input descriptors")
        if len(descriptors) >= limits.max_inputs:
            raise CaptureTooLarge("Input descriptor count exceeds capture limit")
        if item.logical_path in paths:
            raise ValueError("Duplicate logical input path")
        if type(item) is not ExcludedInput and (
            item.logical_path.lower().endswith(_CONTAINER_SUFFIXES)
            or item.media_type.lower() in _CONTAINER_MEDIA
        ):
            disposition = InputDisposition(
                _input_key(workspace_id, source_id, item.logical_path),
                item.logical_path,
                "failed",
                "unsupported_container",
            )
            raise UnsupportedCaptureInput(
                "Container ingestion is not implemented", dispositions=(disposition,)
            )
        paths.add(item.logical_path)
        descriptors.append(item)
    # Reject oversized metadata before storing input. Actual byte-count digits
    # are checked again after capture, so an exactly fitting manifest is valid.
    placeholder_inputs = []
    placeholder_dispositions = []
    for item in descriptors:
        key = _input_key(workspace_id, source_id, item.logical_path)
        if type(item) is ExcludedInput:
            placeholder_dispositions.append(InputDisposition(key, item.logical_path, "excluded", item.reason))
        else:
            placeholder_inputs.append(
                RawInput(
                    key,
                    item.logical_path,
                    item.media_type,
                    "hippo-raw:sha256:" + "0" * 64,
                    "0" * 64,
                    0,
                    item.provider_revision,
                )
            )
            placeholder_dispositions.append(
                InputDisposition(key, item.logical_path, "accepted", "captured", 0, "0" * 64)
            )
    metadata_floor = _manifest_bytes(
        source_id, workspace_id, placeholder_inputs, placeholder_dispositions, configuration_json, limits
    )
    if len(metadata_floor) > limits.max_manifest_bytes:
        raise CaptureTooLarge("Input metadata exceeds manifest byte limit")

    captured = []
    dispositions = []
    total = 0
    for item in descriptors:
        _checkpoint(should_stop, dispositions)
        key = _input_key(workspace_id, source_id, item.logical_path)
        if type(item) is ExcludedInput:
            dispositions.append(InputDisposition(key, item.logical_path, "excluded", item.reason))
            continue
        try:
            artifact = _capture_one(
                raw_store,
                item,
                min(limits.max_input_bytes, limits.max_total_bytes - total),
                should_stop,
                dispositions,
            )
        except CaptureCancelled:
            raise
        except (CaptureTooLarge, RawArtifactTooLarge) as error:
            failed = InputDisposition(key, item.logical_path, "failed", "size_limit")
            raise CaptureTooLarge(
                "Input bytes exceed capture limits", dispositions=(*dispositions, failed)
            ) from error
        except _ChangedInput as error:
            failed = InputDisposition(key, item.logical_path, "failed", "changed_during_capture")
            raise InputCaptureError(
                "Input changed during capture", dispositions=(*dispositions, failed)
            ) from error
        except OSError as error:
            failed = InputDisposition(key, item.logical_path, "failed", "unreadable")
            raise InputCaptureError(
                "Input could not be captured", dispositions=(*dispositions, failed)
            ) from error
        except ValueError as error:
            failed = InputDisposition(key, item.logical_path, "failed", "storage_failure")
            raise InputCaptureError(
                "Raw bytes could not be stored", dispositions=(*dispositions, failed)
            ) from error
        captured.append(
            RawInput(
                key,
                item.logical_path,
                item.media_type,
                artifact.uri,
                artifact.sha256,
                artifact.byte_length,
                item.provider_revision,
            )
        )
        dispositions.append(
            InputDisposition(
                key, item.logical_path, "accepted", "captured", artifact.byte_length, artifact.sha256
            )
        )
        total += artifact.byte_length
    _checkpoint(should_stop, dispositions)
    data = _manifest_bytes(source_id, workspace_id, captured, dispositions, configuration_json, limits)
    if len(data) > limits.max_manifest_bytes:
        raise CaptureTooLarge("Accepted manifest exceeds capture limit", dispositions=tuple(dispositions))
    manifest = raw_store.put_bytes(data)
    _checkpoint(should_stop, dispositions)
    return AcceptedInputs(
        source_id, workspace_id, tuple(captured), tuple(dispositions), configuration_json, limits, manifest
    )
