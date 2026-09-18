"""Captured OpenIE requests for a trusted, stable local Ollama server.

Metadata brackets detect observable replacement, not request-level digest
attestation. Every operation belongs outside store locks; callers own build
authorization and lease lifetime. No shared client settings/cache are changed.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock

from ..ollama import _THINK_BLOCK, OllamaError, parse_json_object
from .embedding_profile import _endpoint, _name_key, _select
from .prose_preparation import OpenIEProfile


class OpenIEIdentityChanged(OllamaError):
    """The captured chat model, client or configuration is no longer available."""


@dataclass(frozen=True, slots=True)
class ResolvedOpenIEProfile:
    profile: OpenIEProfile
    configured_model: str
    capabilities: tuple[str, ...]
    _endpoint_identity: tuple[str, str] = field(repr=False)
    _client: object = field(repr=False, compare=False)

    def __post_init__(self):
        if type(self.profile) is not OpenIEProfile:
            raise ValueError("An immutable OpenIE profile is required")
        if _name_key(self.configured_model) != _name_key(self.profile.wire_model):
            raise ValueError("Configured and selected chat model names differ")
        if type(self.capabilities) is not tuple or _capabilities(self.capabilities) != self.capabilities:
            raise ValueError("Captured capabilities must be an immutable canonical tuple")
        if (
            type(self._endpoint_identity) is not tuple
            or len(self._endpoint_identity) != 2
            or any(type(value) is not str or not value for value in self._endpoint_identity)
        ):
            raise ValueError("Captured endpoint identity is invalid")


def _capabilities(values):
    if type(values) not in (list, tuple) or any(type(v) is not str or not v for v in values):
        raise OllamaError("Managed OpenIE requires explicit model capabilities")
    if len(set(values)) != len(values) or "completion" not in values:
        raise OllamaError("Managed OpenIE requires an unambiguous completion capability")
    return tuple(sorted(values))


def _local(ollama, *, model, num_ctx, endpoint, client, authorize):
    authorize()
    if (
        ollama.llm_model != model
        or type(ollama.num_ctx) is not int
        or ollama.num_ctx != num_ctx
        or ollama.client is not client
        or _endpoint(ollama) != endpoint
    ):
        raise OpenIEIdentityChanged("Captured OpenIE client or configuration changed")


def resolve_openie_profile(ollama, *, authorization_check):
    if not callable(authorization_check):
        raise ValueError("Live authorization is required")
    authorization_check()
    model, num_ctx = ollama.llm_model, ollama.num_ctx
    _name_key(model)
    if type(num_ctx) is not int or num_ctx <= 0:
        raise ValueError("OpenIE context size must be a positive integer")
    endpoint, client = _endpoint(ollama), ollama.client

    def local():
        _local(
            ollama,
            model=model,
            num_ctx=num_ctx,
            endpoint=endpoint,
            client=client,
            authorize=authorization_check,
        )

    def call(method, *args):
        local()
        try:
            return method(*args)
        finally:
            local()

    identity = _select(call(ollama.embedding_models_metadata), model)
    try:
        details = call(ollama.embedding_model_details, identity[0])
        capabilities = _capabilities(details.get("capabilities"))
    finally:
        if _select(call(ollama.embedding_models_metadata), model) != identity:
            raise OpenIEIdentityChanged("Installed OpenIE model changed during resolution")
    return ResolvedOpenIEProfile(
        OpenIEProfile(wire_model=identity[0], model_digest=identity[1], num_ctx=num_ctx),
        model,
        capabilities,
        endpoint,
        client,
    )


class GuardedOpenIE:
    """One preparation's chat runtime with sticky failure and guarded retries."""

    def __init__(self, ollama, resolved, *, authorization_check):
        if type(resolved) is not ResolvedOpenIEProfile or not callable(authorization_check):
            raise ValueError("Captured OpenIE identity and live authorization are required")
        self._ollama, self._resolved, self._authorize = ollama, resolved, authorization_check
        self._lock, self._failure = Lock(), None
        self._local()

    @property
    def profile(self):
        return self._resolved.profile

    def _failed(self):
        with self._lock:
            failure = self._failure
        if failure is not None:
            raise failure

    def _fail(self, exc):
        with self._lock:
            if self._failure is None:
                self._failure = exc

    def _local(self):
        self._failed()
        resolved = self._resolved
        try:
            _local(
                self._ollama,
                model=resolved.configured_model,
                num_ctx=self.profile.num_ctx,
                endpoint=resolved._endpoint_identity,
                client=resolved._client,
                authorize=self._authorize,
            )
            self._failed()  # Another worker may fail while authorization blocks.
        except BaseException as exc:
            self._fail(exc)
            raise

    def validate(self):
        self._local()
        try:
            try:
                current = _select(self._ollama.embedding_models_metadata(), self._resolved.configured_model)
            finally:
                self._local()
            if current != (self.profile.wire_model, self.profile.model_digest):
                raise OpenIEIdentityChanged("Installed OpenIE model identity changed")
        except BaseException as exc:
            self._fail(exc)
            raise

    def chat_json(self, messages, schema, *, max_tokens, request_guard):
        if type(max_tokens) is not int or max_tokens not in (
            self.profile.ner_max_tokens,
            self.profile.triples_max_tokens,
        ):
            raise ValueError("Token limit differs from captured OpenIE semantics")
        if not callable(request_guard):
            raise ValueError("A per-request preparation guard is required")

        def guard():
            self._failed()
            try:
                request_guard()
                self._failed()
                self.validate()
            except BaseException as exc:
                self._fail(exc)
                raise

        try:
            guard()
            body = {
                "model": self.profile.wire_model,
                "messages": deepcopy(messages),
                "format": deepcopy(schema),
                "stream": False,
                "keep_alive": "15m",
                "options": {
                    "temperature": self.profile.temperature,
                    "num_ctx": self.profile.num_ctx,
                    "num_predict": max_tokens,
                },
            }
            if "thinking" in self._resolved.capabilities:
                body["think"] = False
            try:
                response = self._ollama._request("POST", "/api/chat", json=body, request_guard=guard)
                try:
                    data = response.json()
                except ValueError as exc:
                    raise OllamaError("OpenIE response is not valid JSON") from exc
                if type(data) is not dict or _name_key(data.get("model")) != _name_key(
                    self.profile.wire_model
                ):
                    raise OllamaError("OpenIE response model differs from captured identity")
                message = data.get("message")
                if type(message) is not dict or type(message.get("content")) is not str:
                    raise OllamaError("OpenIE response must contain assistant text")
                return parse_json_object(_THINK_BLOCK.sub("", message["content"]).strip())
            finally:
                guard()
        except BaseException as exc:
            self._fail(exc)
            raise
