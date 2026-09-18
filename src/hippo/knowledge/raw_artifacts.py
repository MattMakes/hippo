"""Bounded immutable raw bytes under an explicitly configured POSIX directory.

This primitive provides integrity, not authorization or reachability. Callers own
those policies. The root and its ancestors must exclude untrusted local writers;
portable POSIX operations cannot atomically unlink a name conditional on its
inode identity. Detected substitutions fail closed and are left for operator
repair; this is not a sandbox against a process that can rewrite the directory.
References contain no filesystem paths, and there is no delete
API. Existing corrupt objects fail closed and require separate operator repair.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

_URI = re.compile(r"hippo-raw:sha256:([0-9a-f]{64})")
_CHUNK_BYTES = 64 * 1024


class RawArtifactError(ValueError):
    """An invalid reference, unavailable object, or unsafe storage location."""


class RawArtifactCorrupt(RawArtifactError):
    """Stored bytes disagree with their immutable reference."""


class RawArtifactTooLarge(RawArtifactError):
    """An object exceeds this store's explicit per-object limit."""


@dataclass(frozen=True)
class RawArtifact:
    """Portable reference suitable for RawInput metadata."""

    uri: str
    sha256: str
    byte_length: int

    def __post_init__(self) -> None:
        match = _URI.fullmatch(self.uri) if isinstance(self.uri, str) else None
        if match is None or match[1] != self.sha256:
            raise RawArtifactError("Invalid raw artifact reference")
        if type(self.byte_length) is not int or self.byte_length < 0:
            raise RawArtifactError("byte_length must be a nonnegative integer")

    @classmethod
    def from_uri(cls, uri: str, *, byte_length: int) -> RawArtifact:
        match = _URI.fullmatch(uri) if isinstance(uri, str) else None
        if match is None:
            raise RawArtifactError("Invalid raw artifact URI")
        return cls(uri=uri, sha256=match[1], byte_length=byte_length)


def _write_all(sink: BinaryIO, chunk: bytes) -> None:
    remaining = memoryview(chunk)
    while remaining:
        count = sink.write(remaining)
        if type(count) is not int or not 0 < count <= len(remaining):
            raise RawArtifactError("Binary output did not accept bytes")
        remaining = remaining[count:]


class RawArtifactStore:
    """Content-addressed bytes with no implicit root or size configuration.

    Root components must be real directories, never symlinks. Each operation
    pins directory descriptors and verifies the configured root's identity.
    Writes publish using a no-replace hard link on the same filesystem. Reads
    verify into an unlinked private spool before emitting any caller output.
    Neither input nor output streams are closed by this class.
    """

    def __init__(self, root: str | os.PathLike[str], *, max_object_bytes: int) -> None:
        if type(max_object_bytes) is not int or max_object_bytes <= 0:
            raise RawArtifactError("max_object_bytes must be a positive integer")
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise RawArtifactError("Raw storage requires POSIX no-follow directory operations")
        self._root = Path(root)
        if not self._root.is_absolute() or ".." in self._root.parts:
            raise RawArtifactError("Raw storage root must be an absolute path without parent traversal")
        self._max_object_bytes = max_object_bytes
        self._root_identity: tuple[int, int] | None = None
        with self._directory(create=True) as descriptor:
            info = os.fstat(descriptor)
            self._root_identity = (info.st_dev, info.st_ino)

    @contextmanager
    def _directory(self, *, create: bool = False) -> Iterator[int]:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in self._root.parts[1:]:
                if create:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                try:
                    child = os.open(
                        component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                except OSError as exc:
                    raise RawArtifactError("Raw storage directory unavailable or unsafe") from exc
                os.close(descriptor)
                descriptor = child
            info = os.fstat(descriptor)
            if self._root_identity is not None and self._root_identity != (info.st_dev, info.st_ino):
                raise RawArtifactError("Raw storage root has been replaced")
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _staging(directory: int) -> tuple[str, int]:
        while True:
            name = ".pending-" + secrets.token_hex(24)
            try:
                descriptor = os.open(
                    name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
                )
            except FileExistsError:
                continue
            return name, descriptor

    @staticmethod
    def _names_inode(directory: int, name: str, owned: os.stat_result) -> bool:
        try:
            current = os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino)

    @classmethod
    def _unlink_owned(cls, directory: int, name: str, owned: os.stat_result) -> None:
        # The configured directory excludes hostile writers. This identity check
        # preserves observed substitutions; it is not a portable unlink CAS.
        if cls._names_inode(directory, name, owned):
            os.unlink(name, dir_fd=directory)

    def _copy_hash(self, source: BinaryIO, sink: BinaryIO | None = None) -> tuple[str, int]:
        digest = hashlib.sha256()
        length = 0
        while True:
            requested = min(_CHUNK_BYTES, self._max_object_bytes - length + 1)
            chunk = source.read(requested)
            if not isinstance(chunk, bytes) or len(chunk) > requested:
                raise RawArtifactError("Input must honor bounded binary reads")
            if not chunk:
                return digest.hexdigest(), length
            length += len(chunk)
            if length > self._max_object_bytes:
                raise RawArtifactTooLarge("Raw artifact exceeds max_object_bytes")
            digest.update(chunk)
            if sink is not None:
                _write_all(sink, chunk)

    def _verify(
        self,
        directory: int,
        artifact: RawArtifact,
        sink: BinaryIO | None = None,
        *,
        owned: os.stat_result | None = None,
    ) -> None:
        try:
            descriptor = os.open(
                artifact.sha256, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        except OSError as exc:
            raise RawArtifactError("Raw artifact unavailable or unsafe") from exc
        try:
            info = os.fstat(descriptor)
            if owned is not None and (info.st_dev, info.st_ino) != (owned.st_dev, owned.st_ino):
                raise RawArtifactCorrupt("Raw artifact publication inode changed")
            if not stat.S_ISREG(info.st_mode):
                raise RawArtifactError("Raw artifact must be a regular file")
            source = os.fdopen(descriptor, "rb")
        except BaseException:
            os.close(descriptor)
            raise
        with source:
            if info.st_size != artifact.byte_length:
                raise RawArtifactCorrupt("Raw artifact byte length mismatch")
            digest, length = self._copy_hash(source, sink)
            if digest != artifact.sha256 or length != artifact.byte_length:
                raise RawArtifactCorrupt("Raw artifact digest or byte length mismatch")

    def put_bytes(self, value: bytes) -> RawArtifact:
        if not isinstance(value, bytes):
            raise RawArtifactError("Raw artifact input must be bytes")
        if len(value) > self._max_object_bytes:
            raise RawArtifactTooLarge("Raw artifact exceeds max_object_bytes")
        return self.put_stream(io.BytesIO(value))

    def put_stream(self, source: BinaryIO) -> RawArtifact:
        """Consume bounded binary reads and atomically publish the complete object."""
        with self._directory() as directory:
            name, descriptor = self._staging(directory)
            with os.fdopen(descriptor, "wb") as staging:
                owned = os.fstat(staging.fileno())
                try:
                    digest, length = self._copy_hash(source, staging)
                    staging.flush()
                    os.fchmod(staging.fileno(), 0o400)
                    os.fsync(staging.fileno())
                    artifact = RawArtifact(
                        uri="hippo-raw:sha256:" + digest, sha256=digest, byte_length=length
                    )
                    if not self._names_inode(directory, name, owned):
                        raise RawArtifactCorrupt("Raw artifact staging inode changed")
                    try:
                        os.link(
                            name, digest, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False
                        )
                    except FileExistsError:
                        self._verify(directory, artifact)
                    else:
                        self._verify(directory, artifact, owned=owned)
                        if not self._names_inode(directory, digest, owned):
                            raise RawArtifactCorrupt("Raw artifact publication inode changed")
                    os.fsync(directory)
                    return artifact
                finally:
                    self._unlink_owned(directory, name, owned)

    def copy_to(self, artifact: RawArtifact, sink: BinaryIO) -> int:
        """Verify fully before output; return the number of verified bytes copied.

        A failing output stream may receive a partial, verified object. A corrupt
        stored object never emits a prefix. Working disk space is bounded by the
        configured object limit per concurrent call.
        """
        if not isinstance(artifact, RawArtifact):
            raise RawArtifactError("A validated RawArtifact reference is required")
        if artifact.byte_length > self._max_object_bytes:
            raise RawArtifactTooLarge("Raw artifact exceeds max_object_bytes")
        with self._directory() as directory:
            name, descriptor = self._staging(directory)
            with os.fdopen(descriptor, "w+b") as spool:
                owned = os.fstat(spool.fileno())
                if not self._names_inode(directory, name, owned):
                    raise RawArtifactCorrupt("Raw artifact spool inode changed")
                self._unlink_owned(directory, name, owned)
                self._verify(directory, artifact, spool)
                spool.seek(0)
                while chunk := spool.read(_CHUNK_BYTES):
                    _write_all(sink, chunk)
        return artifact.byte_length

    def read_bytes(self, artifact: RawArtifact) -> bytes:
        """Return a verified object, bounded by max_object_bytes, in memory."""
        sink = io.BytesIO()
        self.copy_to(artifact, sink)
        return sink.getvalue()
