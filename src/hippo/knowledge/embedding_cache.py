"""Disposable vectors keyed by exact input and an explicitly resolved model profile.

Callers must resolve the actual Ollama model digest before constructing a profile,
and fingerprint the prefix/preprocessing rules and normalization/request options.
A mutable tag alone cannot establish identity. If identity cannot be resolved,
the caller must explicitly bypass reuse by calling its model directly. This module
does not fetch metadata, infer profiles, or apply Ollama's prefixes/normalization.
It is an opt-in primitive; existing indexing paths are not wired to it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

SCHEMA_VERSION = 1
MAX_ENTRY_BYTES = 2 * 1024 * 1024
MAX_DIMENSION = 65536
_SHA256 = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class EmbeddingProfile:
    """Caller-attested identity; fingerprint changes must invalidate vector reuse.

    ``model`` must exactly match the client's ``embed_model``. ``model_digest``
    must be a resolved SHA-256 digest, optionally prefixed with ``sha256:``.
    ``preprocessing_version`` includes the document/query prefix rule version.
    ``normalization_options_fingerprint`` covers normalization and embed options.
    Digest syntax is validated here; resolving/verifying it is the caller's job.
    """

    model: str
    model_digest: str
    dimension: int
    preprocessing_version: str
    normalization_options_fingerprint: str

    def __post_init__(self):
        for name in ("model", "model_digest", "preprocessing_version", "normalization_options_fingerprint"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 4096:
                raise ValueError(f"invalid embedding profile {name}")
        if not _SHA256.fullmatch(self.model_digest):
            raise ValueError("model_digest must be a resolved SHA-256 digest, not a mutable model tag")
        if type(self.dimension) is not int or not 1 <= self.dimension <= MAX_DIMENSION:
            raise ValueError("invalid embedding profile dimension")


def _validate_kind(kind: str) -> None:
    if kind not in ("document", "query"):
        raise ValueError("kind must be document or query")


@dataclass(frozen=True)
class EmbeddingCacheKey:
    profile: EmbeddingProfile
    kind: str
    input_hash: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        if type(self.profile) is not EmbeddingProfile:
            raise ValueError("an explicit EmbeddingProfile is required")
        _validate_kind(self.kind)
        if type(self.input_hash) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.input_hash):
            raise ValueError("invalid input hash")
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("invalid cache schema version")

    @property
    def digest(self) -> str:
        return _hash(_json(asdict(self)))


def cache_key(profile: EmbeddingProfile, text: str, *, kind: str = "document") -> EmbeddingCacheKey:
    """Hash exact UTF-8 text; do not trim, normalize Unicode or apply prefixes."""
    if type(text) is not str:
        raise ValueError("embedding input must be text")
    return EmbeddingCacheKey(profile, kind, _hash(text.encode("utf-8")))


def _vectors(value, shape: tuple[int, ...]) -> np.ndarray:
    """Reject coercible strings/bools and validate all rows before any cache write."""
    try:
        raw = np.asarray(value, dtype=object)
        if raw.shape != shape or any(
            isinstance(item, (bool, np.bool_)) or not isinstance(item, (int, float, np.integer, np.floating))
            for item in raw.flat
        ):
            raise ValueError("invalid embedding vector shape or scalar type")
        with np.errstate(over="ignore", invalid="ignore"):
            matrix = np.array(raw, dtype=np.float32, copy=True)
        if not np.isfinite(matrix).all() or np.any(np.linalg.norm(matrix.astype(np.float64), axis=-1) == 0):
            raise ValueError("embedding vectors must be finite and nonzero")
        return matrix
    except (TypeError, OverflowError) as exc:
        raise ValueError("invalid embedding vectors") from exc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"invalid JSON number: {value}")


class EmbeddingCache:
    """Per-entry bounded JSON with checksums and atomic replacement.

    Root selection/retention belong to the caller. No plaintext inputs or mutable
    in-memory arrays are retained. Invalid/unavailable entries are safe misses;
    disk write failures are harmless. This is not a total cache storage quota.
    """

    def __init__(self, root: str | Path, *, max_entry_bytes: int = MAX_ENTRY_BYTES):
        if type(max_entry_bytes) is not int or not 0 < max_entry_bytes <= MAX_ENTRY_BYTES:
            raise ValueError("invalid maximum cache entry size")
        self.root = Path(root)
        self.max_entry_bytes = max_entry_bytes

    def get(self, key: EmbeddingCacheKey) -> np.ndarray | None:
        try:
            with (self.root / f"{key.digest}.json").open("rb") as handle:
                raw = handle.read(self.max_entry_bytes + 1)
            if len(raw) > self.max_entry_bytes:
                return None
            envelope = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(envelope) is not dict or set(envelope) != {"key", "payload", "payload_hash"}:
                return None
            if _json(envelope["key"]) != _json(asdict(key)):
                return None
            if _hash(_json(envelope["payload"])) != envelope["payload_hash"]:
                return None
            return _vectors(envelope["payload"], (key.profile.dimension,))
        except (OSError, ValueError, RecursionError):
            return None

    def put(self, key: EmbeddingCacheKey, vector) -> None:
        """Reject invalid vectors; skip unavailable or oversized disk writes."""
        payload = _vectors(vector, (key.profile.dimension,)).tolist()
        raw = _json({"key": asdict(key), "payload": payload, "payload_hash": _hash(_json(payload))})
        if len(raw) > self.max_entry_bytes:
            return
        temporary = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.root, suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.root / f"{key.digest}.json")
        except OSError:
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


class EmbeddingModel(Protocol):
    embed_model: str

    def embed(self, texts: list[str], kind: str = "document", batch_size: int = 32) -> np.ndarray: ...


def _validate_model(model: EmbeddingModel, profile: EmbeddingProfile) -> None:
    if model.embed_model != profile.model:
        raise ValueError("model.embed_model does not match the embedding profile model")


def cached_embed(
    model: EmbeddingModel,
    texts: list[str],
    *,
    profile: EmbeddingProfile,
    kind: str = "document",
    cache: EmbeddingCache | None = None,
    batch_size: int = 32,
) -> np.ndarray:
    """Embed unique misses once and restore input order, including duplicate rows.

    The model retains ownership of prefixing, normalization and internal batching.
    Its complete output is validated before any cache write. Model errors propagate,
    unless observable model identity drift invalidates the operation first.
    Empty input returns float32 shape (0, profile.dimension) without a model probe.

    Callers must keep the client and resolved model/profile identity stable for the
    whole operation. Boundary checks reject observable tag changes, but cannot
    detect a server replacing a model behind the same tag or concurrent changes
    that revert between checks. Entries already written before a detected change
    retain vectors validated under the original profile; they are not deleted.
    """
    if type(profile) is not EmbeddingProfile:
        raise ValueError("an explicit EmbeddingProfile is required")
    _validate_model(model, profile)
    _validate_kind(kind)
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
    if not texts:
        result = np.zeros((0, profile.dimension), dtype=np.float32)
        _validate_model(model, profile)
        return result
    keys = [cache_key(profile, text, kind=kind) for text in texts]
    rows = {}
    missing = {}
    for key, text in zip(keys, texts, strict=True):
        if key in rows or key in missing:
            continue
        row = cache.get(key) if cache is not None else None
        _validate_model(model, profile)
        if row is None:
            missing[key] = text
        else:
            rows[key] = row
    if missing:
        _validate_model(model, profile)
        try:
            output = model.embed(list(missing.values()), kind=kind, batch_size=batch_size)
        finally:
            _validate_model(model, profile)
        computed = _vectors(output, (len(missing), profile.dimension))
        for key, row in zip(missing, computed, strict=True):
            rows[key] = row
            if cache is not None:
                _validate_model(model, profile)
                try:
                    cache.put(key, row)
                finally:
                    _validate_model(model, profile)
    result = np.stack([rows[key] for key in keys])
    _validate_model(model, profile)
    return result
