"""Opt-in managed Ollama identities and digest-guarded vector reuse.

Metadata bracketing detects observable replacement, not replace-and-restore races
or request-level model attestation. Callers require a trusted stable Ollama server
and must invoke all resolving/validation/model methods outside database locks.
Legacy Ollama clients and indexing paths remain unchanged until explicitly wired.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import numpy as np

from ..ollama import Ollama, OllamaError
from .embedding_cache import MAX_DIMENSION, EmbeddingCache, EmbeddingProfile, _vectors, cached_embed

_PROBE = "hippo embedding profile probe v1"
_DIGEST = re.compile(r"(?:sha256:)?([0-9a-f]{64})\Z", re.IGNORECASE)


class EmbeddingProfileUnavailable(OllamaError):
    """A strict profile cannot be established or verified."""


class EmbeddingProfileChanged(OllamaError):
    """The captured model/client identity changed during the operation."""


class EmbeddingProfileMismatch(OllamaError):
    """Embedding output does not belong to the captured profile."""


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hash(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _options(raw: str) -> str:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate option key")
            result[key] = value
        return result

    if type(raw) is not str or len(raw.encode("utf-8")) > 65536:
        raise ValueError("options_json must be a bounded JSON object")
    try:
        value = json.loads(raw, object_pairs_hook=unique)
        if type(value) is not dict:
            raise ValueError("options_json must be an object")
        return _canonical(value)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("invalid embedding options") from exc


@dataclass(frozen=True)
class EmbeddingSpec:
    query_prefix: str = ""
    document_prefix: str = ""
    options_json: str = "{}"
    dimensions: int | None = None
    truncate: bool = False
    normalization: str = "l2-f64-to-f32-v1"
    preprocessing: str = "exact-utf8-prefix-v1"

    def __post_init__(self):
        for prefix in (self.query_prefix, self.document_prefix):
            if type(prefix) is not str or len(prefix.encode("utf-8")) > 4096:
                raise ValueError("invalid embedding prefix")
        if self.dimensions is not None and (
            type(self.dimensions) is not int or not 1 <= self.dimensions <= MAX_DIMENSION
        ):
            raise ValueError("invalid requested embedding dimension")
        if self.truncate is not False:
            raise ValueError("managed embeddings require truncate=false")
        if self.normalization != "l2-f64-to-f32-v1" or self.preprocessing != "exact-utf8-prefix-v1":
            raise ValueError("unsupported embedding preprocessing or normalization")
        object.__setattr__(self, "options_json", _options(self.options_json))

    def make_profile(self, model: str, digest: str, dimension: int) -> EmbeddingProfile:
        return EmbeddingProfile(
            model=model,
            model_digest=digest,
            dimension=dimension,
            preprocessing_version=self.preprocessing
            + ":"
            + _hash({"query_prefix": self.query_prefix, "document_prefix": self.document_prefix}),
            normalization_options_fingerprint=_hash(
                {
                    "normalization": self.normalization,
                    "options": json.loads(self.options_json),
                    "truncate": self.truncate,
                    "dimensions": self.dimensions,
                }
            ),
        )


def _fingerprint(profile: EmbeddingProfile) -> str:
    return _hash({"profile_schema": 1, "profile": asdict(profile)})


@dataclass(frozen=True)
class ResolvedEmbeddingProfile:
    profile: EmbeddingProfile
    fingerprint: str
    wire_model: str
    spec: EmbeddingSpec
    endpoint_identity: tuple[str, str] = field(repr=False)
    _client: object = field(repr=False, compare=False)

    def __post_init__(self):
        if self.spec.make_profile(
            self.profile.model, self.profile.model_digest, self.profile.dimension
        ) != self.profile or self.fingerprint != _fingerprint(self.profile):
            raise ValueError("inconsistent resolved embedding profile")

    def descriptor(self) -> dict:
        """Persistable copied identity only; never serialize the transport-bound dataclass."""
        return {
            "profile_schema": 1,
            "profile": asdict(self.profile),
            "spec": asdict(self.spec),
            "fingerprint": self.fingerprint,
        }


def _endpoint(ollama: Ollama) -> tuple[str, str]:
    return ollama.base_url, str(ollama.client.base_url)


def _name_key(name: str) -> str:
    if type(name) is not str or not name.strip() or name != name.strip() or len(name) > 4096:
        raise EmbeddingProfileUnavailable("Invalid embedding model name")
    return name if ":" in name.rsplit("/", 1)[-1] else name + ":latest"


def _select(data: dict, wanted: str) -> tuple[str, str]:
    rows = data.get("models")
    if type(rows) is not list:
        raise EmbeddingProfileUnavailable("Installed model metadata is missing")
    matches = set()
    for row in rows:
        if type(row) is not dict:
            raise EmbeddingProfileUnavailable("Invalid installed model metadata")
        name = row.get("name")
        if _name_key(name) != _name_key(wanted):
            continue
        if "model" in row and _name_key(row["model"]) != _name_key(name):
            raise EmbeddingProfileUnavailable("Conflicting installed model names")
        digest = row.get("digest")
        match = _DIGEST.fullmatch(digest) if type(digest) is str else None
        if not match:
            raise EmbeddingProfileUnavailable("Installed embedding model has no valid SHA-256 digest")
        matches.add((name, match.group(1).lower()))
    if len(matches) != 1:
        raise EmbeddingProfileUnavailable("Embedding model is missing or ambiguous")
    return next(iter(matches))


class _Identity:
    def __init__(self, ollama, *, model, endpoint, client, authorization_check=None):
        self.ollama = ollama
        self.model = model
        self.endpoint = endpoint
        self.client = client
        self.authorize = authorization_check or (lambda: None)
        self.expected = None

    def local(self):
        self.authorize()
        if (
            self.ollama.embed_model != self.model
            or self.ollama.client is not self.client
            or _endpoint(self.ollama) != self.endpoint
        ):
            raise EmbeddingProfileChanged("Embedding client identity changed")

    def call(self, method, *args, **kwargs):
        self.local()
        try:
            return method(*args, **kwargs)
        finally:
            self.local()

    def validate(self):
        current = _select(self.call(self.ollama.embedding_models_metadata), self.model)
        if self.expected is not None and current != self.expected:
            raise EmbeddingProfileChanged("Installed embedding model identity changed")
        return current


def _matrix(data, *, wire_model, count, dimension=None):
    """Reject raw float32 overflow/all-zero underflow; normalize original accepted f64 values."""
    try:
        if _name_key(data.get("model")) != _name_key(wire_model):
            raise ValueError("embedding response model mismatch")
        raw = data.get("embeddings")
        if dimension is None:
            if type(raw) is not list or len(raw) != count or not raw or type(raw[0]) is not list:
                raise ValueError("invalid probe output")
            dimension = len(raw[0])
        if not 1 <= dimension <= MAX_DIMENSION:
            raise ValueError("invalid output dimension")
        _vectors(raw, (count, dimension))  # Validate scalar types and float32 representability first.
        vectors = np.array(raw, dtype=np.float64, copy=True)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        result = (vectors / norms).astype(np.float32)
        return _vectors(result, (count, dimension))
    except (ValueError, TypeError, OverflowError) as exc:
        raise EmbeddingProfileMismatch("Invalid embedding output for the captured profile") from exc


def _embed_call(identity, *, wire_model, spec, inputs):
    return identity.call(
        identity.ollama.embed_explicit,
        wire_model,
        inputs,
        options=json.loads(spec.options_json),
        dimensions=spec.dimensions,
        truncate=spec.truncate,
    )


def resolve_embedding_profile(
    ollama: Ollama, *, spec: EmbeddingSpec, authorization_check: Callable[[], None] | None = None
) -> ResolvedEmbeddingProfile:
    """Resolve a strict profile outside all database locks, without installing models."""
    if type(spec) is not EmbeddingSpec:
        raise ValueError("an explicit EmbeddingSpec is required")
    identity = _Identity(
        ollama,
        model=ollama.embed_model,
        endpoint=_endpoint(ollama),
        client=ollama.client,
        authorization_check=authorization_check,
    )
    try:
        identity.expected = identity.validate()
        wire_model, digest = identity.expected
        try:
            details = identity.call(ollama.embedding_model_details, wire_model)
            capabilities = details.get("capabilities")
            if capabilities is not None and (
                type(capabilities) is not list or "embedding" not in capabilities
            ):
                raise EmbeddingProfileUnavailable("Model does not declare embedding support")
            info = details.get("model_info", {})
            if type(info) is not dict:
                raise EmbeddingProfileUnavailable("Invalid embedding model_info")
            for key, value in info.items():
                if key.endswith(".embedding_length") and (type(value) is not int or value <= 0):
                    raise EmbeddingProfileUnavailable("Invalid architecture embedding dimension")
            data = _embed_call(
                identity, wire_model=wire_model, spec=spec, inputs=[spec.document_prefix + _PROBE]
            )
            vectors = _matrix(data, wire_model=wire_model, count=1, dimension=spec.dimensions)
            profile = spec.make_profile(identity.model, digest, vectors.shape[1])
        finally:
            identity.validate()
        return ResolvedEmbeddingProfile(
            profile, _fingerprint(profile), wire_model, spec, identity.endpoint, identity.client
        )
    except (EmbeddingProfileChanged, EmbeddingProfileUnavailable):
        raise
    except OllamaError as exc:
        raise EmbeddingProfileUnavailable("Cannot resolve embedding profile") from exc


class _MissModel:
    def __init__(self, owner):
        self.owner = owner
        self.embed_model = owner.embed_model

    def embed(self, texts, kind="document", batch_size=32):
        owner = self.owner
        resolved = owner.resolved
        prefix = resolved.spec.query_prefix if kind == "query" else resolved.spec.document_prefix
        rows = []
        for start in range(0, len(texts), batch_size):
            owner.validate()
            try:
                data = _embed_call(
                    owner._identity,
                    wire_model=resolved.wire_model,
                    spec=resolved.spec,
                    inputs=[prefix + text for text in texts[start : start + batch_size]],
                )
                rows.extend(
                    _matrix(
                        data,
                        wire_model=resolved.wire_model,
                        count=min(batch_size, len(texts) - start),
                        dimension=resolved.profile.dimension,
                    )
                )
            finally:
                owner.validate()
        return np.asarray(rows, dtype=np.float32)


class ProfiledEmbeddings:
    """Captured managed embedding semantics, with fresh remote checks even on hits.

    Resolving, validate(), embed() and chat methods perform HTTP: the caller owns
    the no-database-lock boundary. No automatic retry changes the captured profile.
    """

    def __init__(
        self,
        ollama: Ollama,
        resolved: ResolvedEmbeddingProfile,
        *,
        cache: EmbeddingCache | None = None,
        authorization_check: Callable[[], None] | None = None,
    ):
        if type(resolved) is not ResolvedEmbeddingProfile:
            raise ValueError("an explicit resolved embedding profile is required")
        self._ollama = ollama
        self._resolved = resolved
        self.cache = cache
        self._identity = _Identity(
            ollama,
            model=self.embed_model,
            endpoint=resolved.endpoint_identity,
            client=resolved._client,
            authorization_check=authorization_check,
        )
        self._identity.expected = resolved.wire_model, resolved.profile.model_digest
        self._identity.local()

    @property
    def ollama(self) -> Ollama:
        return self._ollama

    @property
    def resolved(self) -> ResolvedEmbeddingProfile:
        return self._resolved

    @property
    def embed_model(self) -> str:
        return self.resolved.profile.model

    def validate(self) -> None:
        self._identity.validate()

    def embedding_dim(self) -> int:
        self._identity.local()
        return self.resolved.profile.dimension

    def embed(self, texts: list[str], kind: str = "document", batch_size: int = 32) -> np.ndarray:
        self.validate()
        try:
            result = cached_embed(
                _MissModel(self),
                texts,
                profile=self.resolved.profile,
                kind=kind,
                cache=self.cache,
                batch_size=batch_size,
            )
            if not len(result):
                return result
            return _matrix(
                {"model": self.resolved.wire_model, "embeddings": result},
                wire_model=self.resolved.wire_model,
                count=len(texts),
                dimension=self.resolved.profile.dimension,
            )
        finally:
            self.validate()

    def embed_one(self, text: str, kind: str = "query") -> np.ndarray:
        return self.embed([text], kind=kind)[0]

    def _chat(self, name, *args, **kwargs):
        self.validate()
        try:
            return self._identity.call(
                getattr(self.ollama, name), *args, request_guard=self.validate, **kwargs
            )
        finally:
            self.validate()

    def chat_text(self, *args, **kwargs):
        return self._chat("chat_text", *args, **kwargs)

    def chat_json(self, *args, **kwargs):
        return self._chat("chat_json", *args, **kwargs)
