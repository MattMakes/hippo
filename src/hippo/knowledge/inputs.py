"""The accepted-input contracts, as values: what was accepted, never how to read it.

These are the descriptors and the inventory a caller hands to, or gets back from,
input capture. They perform no I/O, consult no store and grant no access; the
capture that opens files and writes raw objects stays in `hippo.ingest`, which
re-exports every name here so existing import paths keep working.

They live under `hippo.knowledge` because knowledge modules validate accepted
metadata -- a generation's manifest, a materialized binding -- and `hippo.ingest`
may depend on `hippo.knowledge` but never the reverse. Reversing that direction
is what `tests/unit/test_layering.py` guards.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from .identity import canonical_json, make_identity, normalize_json, normalize_relative_path
from .raw_artifacts import RawArtifact

# The external ID of the accepted manifest artifact, which is the local naming
# convention a verified generation is checked against.
MANIFEST_EXTERNAL_ID = "accepted-inputs-v1"


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


@dataclass(frozen=True, slots=True)
class RawInput:
    input_key: str
    logical_path: str
    media_type: str
    raw_uri: str
    raw_hash: str
    byte_length: int
    provider_revision: str | None = None
    container_chain: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.input_key, str)
            or not self.input_key
            or not isinstance(self.media_type, str)
            or not self.media_type
        ):
            raise ValueError("Raw input needs an input key and media type")
        if self.provider_revision is not None and not isinstance(self.provider_revision, str):
            raise ValueError("Provider revision must be immutable text")
        if isinstance(self.container_chain, str):
            raise ValueError("Container chain must be a collection of logical paths")
        object.__setattr__(self, "logical_path", normalize_relative_path(self.logical_path))
        object.__setattr__(
            self, "container_chain", tuple(normalize_relative_path(p) for p in self.container_chain)
        )
        _ = self.raw_artifact  # Validate the portable, content-addressed reference.

    @property
    def raw_artifact(self) -> RawArtifact:
        return RawArtifact(self.raw_uri, self.raw_hash, self.byte_length)


class InputCaptureError(ValueError):
    """No accepted inventory was produced; dispositions are diagnostic only."""

    def __init__(self, message: str, *, dispositions: tuple[InputDisposition, ...] = ()) -> None:
        super().__init__(message)
        self.dispositions = tuple(dispositions)


class CaptureTooLarge(InputCaptureError):
    pass


class UnsupportedCaptureInput(InputCaptureError):
    pass


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
