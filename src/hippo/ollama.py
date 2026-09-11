"""
A small client for Ollama, the local model server.

Everything the app asks a language model to do goes through this file:

* `chat_json()`  - ask the LLM a question and get back JSON that matches a schema
* `chat_text()`  - ask the LLM a question and get back plain text
* `embed()`      - turn a list of texts into unit-length vectors
* `ensure_model()` - pull a model if it is not installed yet (with progress)

It talks to Ollama's HTTP API directly (https://github.com/ollama/ollama/blob/main/docs/api.md),
so there is no SDK to learn. Tests swap in a fake HTTP transport.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import numpy as np

log = logging.getLogger(__name__)

# Some embedding models want a hint about whether a text is a query or a document.
# (nomic-embed-text and mxbai-embed-large do; bge-m3 and others do not.)
EMBED_PREFIXES: dict[str, tuple[str, str]] = {
    "nomic-embed-text": ("search_query: ", "search_document: "),
    "mxbai-embed-large": ("Represent this sentence for searching relevant passages: ", ""),
}

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

CONNECT_TIMEOUT = 10.0  # seconds to reach Ollama at all; an unreachable host should fail fast
PULL_READ_TIMEOUT = 300.0  # seconds without any download progress before a model pull is given up


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable, a model is missing, or a reply cannot be used."""


class Ollama:
    def __init__(
        self,
        base_url: str,
        llm_model: str,
        embed_model: str,
        *,
        num_ctx: int = 8192,
        timeout_seconds: float = 600.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.llm_model = llm_model
        self.embed_model = embed_model
        self.num_ctx = num_ctx
        self.timeout_seconds = timeout_seconds
        # Waiting long for a reply is fine (local models are slow); waiting long to *connect* is not.
        self.client = client or httpx.Client(
            base_url=self.base_url, timeout=httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT)
        )
        self._capabilities: dict[str, set[str]] = {}
        self._embedding_dim: int | None = None

    # ------------------------------------------------------------------ status

    def is_up(self) -> bool:
        try:
            return self.client.get("/api/tags", timeout=5.0).status_code == 200
        except httpx.HTTPError:
            return False

    def installed_models(self) -> list[str]:
        data = self._request("GET", "/api/tags").json()
        return [m["name"] for m in data.get("models", [])]

    def has_model(self, name: str) -> bool:
        return _same_model(name, self.installed_models())

    def required_models(self) -> list[str]:
        return [self.llm_model, self.embed_model]

    def missing_models(self) -> list[str]:
        installed = self.installed_models()
        return [m for m in self.required_models() if not _same_model(m, installed)]

    def pull(self, name: str) -> Iterator[dict[str, Any]]:
        """Stream Ollama's pull progress: dicts with `status`, and `completed`/`total` bytes while downloading."""
        # No overall limit (a 6 GB download takes as long as it takes), but a stalled download must
        # end as an error rather than leave the pull job "running" forever.
        timeout = httpx.Timeout(None, connect=CONNECT_TIMEOUT, read=PULL_READ_TIMEOUT)
        try:
            with self.client.stream(
                "POST", "/api/pull", json={"model": name, "stream": True}, timeout=timeout
            ) as resp:
                if resp.status_code != 200:
                    raise OllamaError(f"Ollama could not pull {name}: HTTP {resp.status_code}")
                for line in resp.iter_lines():
                    if line.strip():
                        yield json.loads(line)
        except httpx.TimeoutException as exc:
            raise OllamaError(
                f"Ollama stopped sending data while pulling {name} (nothing for {PULL_READ_TIMEOUT:.0f}s); "
                "check the network and try again"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama at {self.base_url} could not pull {name}: {exc}") from exc

    def ensure_model(self, name: str, on_progress: Callable[[dict[str, Any]], None] | None = None) -> None:
        """Pull `name` if it is not installed. Calls `on_progress(event)` as the download moves along."""
        if self.has_model(name):
            return
        log.info("Pulling model %s from Ollama", name)
        for event in self.pull(name):
            if on_progress:
                on_progress(event)
            if "error" in event:
                raise OllamaError(f"Ollama could not pull {name}: {event['error']}")

    # -------------------------------------------------------------------- chat

    def chat_text(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        request_guard: Callable[[], None] | None = None,
    ) -> str:
        """Send a chat conversation and get the assistant's reply as plain text."""
        return self._chat(
            messages, schema=None, max_tokens=max_tokens, temperature=temperature, request_guard=request_guard
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        request_guard: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """
        Send a chat conversation and get back a JSON object matching `schema`.

        Ollama constrains the model's output to the schema ("structured outputs"),
        so parsing almost always succeeds. If the model still produces something
        odd we try to rescue the first JSON object in the text.
        """
        raw = self._chat(
            messages,
            schema=schema,
            max_tokens=max_tokens,
            temperature=temperature,
            request_guard=request_guard,
        )
        return parse_json_object(raw)

    def _chat(self, messages, *, schema, max_tokens, temperature, request_guard=None) -> str:
        body: dict[str, Any] = {
            "model": self.llm_model,
            "messages": messages,
            "stream": False,
            "keep_alive": "15m",
            "options": {"temperature": temperature, "num_ctx": self.num_ctx},
        }
        if max_tokens:
            body["options"]["num_predict"] = max_tokens
        if schema is not None:
            body["format"] = schema
        if "thinking" in self._model_capabilities(self.llm_model, request_guard=request_guard):
            body["think"] = False  # qwen3 & friends: skip the long "<think>" monologue, we want the answer
        data = self._request("POST", "/api/chat", json=body, request_guard=request_guard).json()
        content = data.get("message", {}).get("content", "")
        return _THINK_BLOCK.sub("", content).strip()

    # --------------------------------------------------------------- embeddings

    def embedding_models_metadata(self) -> dict:
        """Fresh installed-model metadata for explicit managed profile resolution."""
        return self._embedding_metadata_request("GET", "/api/tags")

    def embedding_model_details(self, model: str) -> dict:
        """Fresh details; unlike chat capability detection, failures are not hidden."""
        return self._embedding_metadata_request("POST", "/api/show", {"model": model})

    def embed_explicit(
        self, model: str, inputs: list[str], *, options: dict, dimensions: int | None, truncate: bool
    ) -> dict:
        """Raw embedding request with caller-captured semantics; no prefixing or normalization."""
        body = {
            "model": model,
            "input": inputs,
            "options": options,
            "truncate": truncate,
            "keep_alive": "15m",
        }
        if dimensions is not None:
            body["dimensions"] = dimensions
        return self._embedding_metadata_request("POST", "/api/embed", body)

    def _embedding_metadata_request(self, method: str, path: str, body=None) -> dict:
        # Managed callers guard each dispatch. Hidden retries would resend inputs
        # before they can recheck authorization and the captured model identity.
        response = self._request(method, path, json=body, attempts=1)

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result

        def invalid_constant(value):
            raise ValueError("nonfinite JSON value")

        try:
            result = json.loads(response.content, object_pairs_hook=unique, parse_constant=invalid_constant)
            if not isinstance(result, dict):
                raise ValueError("expected JSON object")
            return result
        except (ValueError, RecursionError) as exc:
            raise OllamaError("Ollama returned invalid embedding metadata or output") from exc

    def embed(self, texts: list[str], kind: str = "document", batch_size: int = 32) -> np.ndarray:
        """
        Embed texts into unit-length float32 vectors, shape (len(texts), dim).

        `kind` is "query" for questions and "document" for everything we store
        (passages, entities, facts); some models embed the two differently.
        """
        if not texts:
            return np.zeros((0, self.embedding_dim()), dtype=np.float32)
        query_prefix, doc_prefix = EMBED_PREFIXES.get(_base_name(self.embed_model), ("", ""))
        prefix = query_prefix if kind == "query" else doc_prefix
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = [prefix + t for t in texts[start : start + batch_size]]
            data = self._request(
                "POST", "/api/embed", json={"model": self.embed_model, "input": batch, "keep_alive": "15m"}
            ).json()
            vectors.extend(data["embeddings"])
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms
        self._embedding_dim = matrix.shape[1]
        return matrix

    def embed_one(self, text: str, kind: str = "query") -> np.ndarray:
        return self.embed([text], kind=kind)[0]

    def embedding_dim(self) -> int:
        """How many numbers are in one embedding vector (found out by embedding a short probe text once)."""
        if self._embedding_dim is None:
            self.embed(["hello"], kind="document")
        return int(self._embedding_dim)  # type: ignore[arg-type]

    # ----------------------------------------------------------------- helpers

    def _model_capabilities(self, name: str, *, request_guard=None) -> set[str]:
        if name not in self._capabilities:
            try:
                data = self._request(
                    "POST", "/api/show", json={"model": name}, request_guard=request_guard
                ).json()
                self._capabilities[name] = set(data.get("capabilities", []))
            except OllamaError:
                if request_guard is not None:
                    raise  # Guard failures (including identity errors) must not become a capability miss.
                self._capabilities[name] = set()
        return self._capabilities[name]

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        attempts: int = 3,
        request_guard: Callable[[], None] | None = None,
    ) -> httpx.Response:
        """
        One HTTP call with a little patience: network hiccups and 5xx replies are retried.

        A reply that did not arrive in time is *not* retried: the model will not be faster the
        second time, and three tries would turn one long wait into three.
        """
        last_error: Exception | None = None
        for attempt in range(attempts):
            if request_guard is not None:
                request_guard()
            transport_error = None
            try:
                try:
                    resp = self.client.request(method, path, json=json)
                except httpx.HTTPError as exc:
                    transport_error = exc
            finally:
                if request_guard is not None:
                    request_guard()
            if isinstance(transport_error, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
                raise OllamaError(
                    f"Ollama did not answer {method} {path} within {self.timeout_seconds:.0f}s; "
                    "raise HIPPO_LLM_TIMEOUT or use a smaller model"
                ) from transport_error
            if transport_error is not None:  # connection refused/reset, ConnectTimeout: worth another go
                last_error = transport_error
                log.warning(
                    "Ollama request %s %s failed (%s), attempt %d/%d",
                    method,
                    path,
                    transport_error,
                    attempt + 1,
                    attempts,
                )
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 404:
                raise OllamaError(
                    f"Ollama says: {resp.text.strip()} (is the model installed? open Settings to pull it)"
                )
            if resp.status_code >= 500:
                last_error = OllamaError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:300]}")
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise OllamaError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:300]}")
            return resp
        raise OllamaError(f"Ollama at {self.base_url} is not answering: {last_error}")


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the JSON object in `text`, tolerating chatter around it. Raises OllamaError if there is none."""
    text = _THINK_BLOCK.sub("", text).strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for start, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise OllamaError(f"The model did not return a JSON object. It said: {text[:200]!r}")


def _base_name(model: str) -> str:
    """'nomic-embed-text:latest' -> 'nomic-embed-text'."""
    return model.split(":", 1)[0]


def _same_model(wanted: str, installed: list[str]) -> bool:
    """'qwen3:8b' matches 'qwen3:8b'; 'nomic-embed-text' matches 'nomic-embed-text:latest'."""
    wanted_full = wanted if ":" in wanted else wanted + ":latest"
    return any(name == wanted or name == wanted_full for name in installed)
