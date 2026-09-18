"""The bounded provider boundary: one client, six error classes, and a recording that replays.

Design `docs/spec/connector-developer-kit.md` section 8, plan `ai_docs/plans/cdk-s3-runtime.md`
sections 4.3 and 10.2, ruling B4 (the transports are specified once, here; the kit re-exports them,
and `replay_transport` raises `ProviderMalformedError` on an unexpected request).

Every provider call a connector makes is bounded on five axes: a connect and a read timeout, a
response size, a number of attempts, and a total elapsed budget. What comes back is either bytes or
one of the six `ProviderError` classes, which is the whole vocabulary the runtime's deletion and
policy rules are written against: a `forbidden` is never a deletion, and a `transient` is.

Two rules about secrets hold everywhere. Redirects are not followed, so credentials never cross an
origin; and every URL this module puts in an error, a log line or a recording goes through
`credentials.redact_url` first. No error carries a response body.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import ClassVar, NamedTuple

import httpx
from pydantic import JsonValue

from ..knowledge.access import utc_now
from ..knowledge.identity import normalize_provider_url
from .credentials import ResolvedCredential, redact_url

ERROR_CLASSES = ("authentication", "forbidden", "not_found", "throttled", "transient", "malformed")
RETRYABLE_CLASSES = ("throttled", "transient")
RECORDING_VERSION = 1
PATH_RULE = "Provider paths are relative to the configured instance"

_RECORDED_REQUEST_HEADERS = ("accept", "content-type")
_RECORDED_RESPONSE_HEADERS = ("content-type", "retry-after", "link")
_RETRY_AFTER_SECONDS = re.compile(r"\d+(?:\.\d+)?")


class ProviderError(Exception):
    """A provider call failed. Carries a redacted URL, a status and an attempt count, never a body.

    `ProviderError` itself is never raised: one of the six subclasses below is, and its
    `error_class` is a member of `ERROR_CLASSES`.
    """

    error_class: ClassVar[str]

    def __init__(
        self,
        *,
        url: str,
        status: int | None,
        attempts: int,
        retry_after: float | None = None,
        detail: str = "",
    ) -> None:
        self.url = url
        self.status = status
        self.attempts = attempts
        self.retry_after = retry_after
        self.detail = detail
        described = f"status {status}" if status is not None else "no response"
        message = (
            f"Provider {getattr(type(self), 'error_class', 'provider')} error: "
            f"{described} from {url} after {attempts} attempt(s)"
        )
        super().__init__(f"{message}: {detail}" if detail else message)


class ProviderAuthenticationError(ProviderError):
    """401: the credential was rejected."""

    error_class = "authentication"


class ProviderForbiddenError(ProviderError):
    """403: the credential is valid and the principal may not see this. Never a deletion."""

    error_class = "forbidden"


class ProviderNotFoundError(ProviderError):
    """404 or 410: the provider says the resource is gone."""

    error_class = "not_found"


class ProviderThrottledError(ProviderError):
    """429: slow down. Retried, honouring `Retry-After`."""

    error_class = "throttled"


class ProviderTransientError(ProviderError):
    """408, 5xx or a transport failure: try again."""

    error_class = "transient"


class ProviderMalformedError(ProviderError):
    """Anything else: an unexpected status, a redirect, an oversize body, or a body that is not JSON."""

    error_class = "malformed"


_STATUS_ERRORS: Mapping[int, type[ProviderError]] = {
    401: ProviderAuthenticationError,
    403: ProviderForbiddenError,
    404: ProviderNotFoundError,
    410: ProviderNotFoundError,
    408: ProviderTransientError,
    429: ProviderThrottledError,
}


@dataclass(frozen=True, slots=True)
class HttpLimits:
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    max_response_bytes: int = 8_000_000
    max_attempts: int = 5
    max_total_seconds: float = 300.0
    backoff_base_seconds: float = 0.5
    backoff_cap_seconds: float = 300.0
    max_retry_after_seconds: float = 300.0


# A module constant rather than `HttpLimits()` in the signature: a call in a default argument is
# evaluated once anyway, and Ruff's B008 refuses the spelling.
DEFAULT_LIMITS = HttpLimits()


class _Fetched(NamedTuple):
    body: bytes
    headers: Mapping[str, str]
    url: str
    status: int
    attempts: int


class ProviderClient:
    """A connector's only way out to its provider.

    Everything that would otherwise make behaviour depend on the wall clock or on luck is injected:
    `monotonic` measures the elapsed budget, `wall_clock` reads an HTTP-date `Retry-After`, `sleep`
    waits between attempts and `rng` supplies the backoff jitter. The runtime passes the store clock
    (ruling R27); tests pass counters and lists.
    """

    def __init__(
        self,
        base_url: str,
        *,
        limits: HttpLimits = DEFAULT_LIMITS,
        transport: httpx.BaseTransport | None = None,
        credential: ResolvedCredential | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.base_url = normalize_provider_url(base_url)
        self.limits = limits
        self._credential = credential
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._rng = rng if rng is not None else random.Random()
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(limits.read_timeout, connect=limits.connect_timeout),
        )

    def get_bytes(
        self, path: str, *, params: Mapping[str, str] | None = None
    ) -> tuple[bytes, Mapping[str, str]]:
        fetched = self._fetch(path, params, "*/*")
        return fetched.body, fetched.headers

    def get_json(self, path: str, *, params: Mapping[str, str] | None = None) -> JsonValue:
        fetched = self._fetch(path, params, "application/json")
        try:
            return json.loads(fetched.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderMalformedError(
                url=fetched.url,
                status=fetched.status,
                attempts=fetched.attempts,
                detail="the body is not JSON",
            ) from error

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ the bounded attempt loop

    def _fetch(self, path: str, params: Mapping[str, str] | None, accept: str) -> _Fetched:
        url = self._join(path)
        request = self._request(url, params, accept)
        redacted = redact_url(str(request.url))
        started = self._monotonic()
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._attempt(request, redacted, attempt)
            except ProviderError as error:
                if error.error_class not in RETRYABLE_CLASSES or attempt >= self.limits.max_attempts:
                    raise
                delay = self._delay(error, attempt)
                if delay is None or self._monotonic() - started + delay > self.limits.max_total_seconds:
                    raise
                self._sleep(delay)
                # A fresh Request per attempt: a sent one carries a consumed stream.
                request = self._request(url, params, accept)

    def _join(self, path: str) -> str:
        segments = path.split("/")
        if (
            not path
            or "?" in path
            or "#" in path
            or "\\" in path
            or ":" in segments[0]
            or any(segment in {"", ".", ".."} for segment in segments)
        ):
            raise ValueError(PATH_RULE)
        return f"{self.base_url}/{path}"

    def _request(self, url: str, params: Mapping[str, str] | None, accept: str) -> httpx.Request:
        headers = {"accept": accept}
        if self._credential is not None:
            name, value = self._credential.authorization()
            headers[name] = value
        return self._client.build_request("GET", url, params=params, headers=headers)

    def _attempt(self, request: httpx.Request, redacted: str, attempt: int) -> _Fetched:
        try:
            response = self._client.send(request, stream=True)
        except httpx.TransportError as error:
            raise ProviderTransientError(
                url=redacted, status=None, attempts=attempt, detail="the transport failed"
            ) from error
        try:
            status = response.status_code
            if 300 <= status < 400:
                raise ProviderMalformedError(
                    url=redacted,
                    status=status,
                    attempts=attempt,
                    detail="the provider redirected, and a credential never crosses an origin",
                )
            failure = _STATUS_ERRORS.get(status)
            if failure is None and not 200 <= status < 300:
                failure = ProviderTransientError if 500 <= status < 600 else ProviderMalformedError
            if failure is not None:
                raise failure(
                    url=redacted, status=status, attempts=attempt, retry_after=self._retry_after(response)
                )
            body = self._read(response, redacted, status, attempt)
        finally:
            response.close()
        return _Fetched(body=body, headers=response.headers, url=redacted, status=status, attempts=attempt)

    def _read(self, response: httpx.Response, redacted: str, status: int, attempt: int) -> bytes:
        limit = self.limits.max_response_bytes
        declared = response.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            raise ProviderMalformedError(
                url=redacted,
                status=status,
                attempts=attempt,
                detail=f"the response declares more than {limit} bytes",
            )
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > limit:
                raise ProviderMalformedError(
                    url=redacted,
                    status=status,
                    attempts=attempt,
                    detail=f"the response passed {limit} bytes",
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _retry_after(self, response: httpx.Response) -> float | None:
        raw = response.headers.get("retry-after")
        if raw is None:
            return None
        text = raw.strip()
        if _RETRY_AFTER_SECONDS.fullmatch(text):
            return float(text)
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - self._wall_clock()).total_seconds())

    def _delay(self, error: ProviderError, attempt: int) -> float | None:
        """How long to wait before attempt `attempt + 1`, or None to stop now."""
        if error.retry_after is not None:
            if error.retry_after > self.limits.max_retry_after_seconds:
                return None
            return error.retry_after
        window = min(self.limits.backoff_cap_seconds, self.limits.backoff_base_seconds * 2 ** (attempt - 1))
        return window * self._rng.uniform(0.5, 1.0)


# ---------------------------------------------------------------------- recording and replay


def record_transport(case_dir: Path, inner: httpx.BaseTransport) -> httpx.BaseTransport:
    """Wrap `inner` so every exchange lands in `case_dir/http/NNNN.json`, in order and redacted."""
    return _RecordingTransport(Path(case_dir), inner)


def replay_transport(case_dir: Path) -> httpx.MockTransport:
    """Answer the exchanges a recording holds, in order, refusing anything else."""
    remaining = [
        json.loads(page.read_text(encoding="utf-8"))
        for page in sorted((Path(case_dir) / "http").glob("*.json"))
    ]

    return httpx.MockTransport(_replaying(remaining))


def _replaying(remaining: list[dict]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        url = redact_url(str(request.url))
        if not remaining:
            raise ProviderMalformedError(
                url=url, status=None, attempts=1, detail="the recording holds no further exchange"
            )
        page = remaining.pop(0)
        recorded = page["request"]
        digest = hashlib.sha256(request.read()).hexdigest()
        if (
            request.method != recorded["method"]
            or url != recorded["url"]
            or digest != recorded["body_sha256"]
        ):
            raise ProviderMalformedError(
                url=url,
                status=None,
                attempts=1,
                detail=f"the recording expected {recorded['method']} {recorded['url']}",
            )
        answer = page["response"]
        return httpx.Response(
            answer["status"],
            headers=answer.get("headers", {}),
            content=base64.b64decode(answer["body_base64"]),
        )

    return handler


class _RecordingTransport(httpx.BaseTransport):
    def __init__(self, case_dir: Path, inner: httpx.BaseTransport) -> None:
        self._dir = case_dir / "http"
        self._inner = inner
        self._index = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        response = self._inner.handle_request(request)
        response.read()
        page = {
            "version": RECORDING_VERSION,
            "request": {
                "method": request.method,
                "url": redact_url(str(request.url)),
                "headers": {
                    name: request.headers[name]
                    for name in _RECORDED_REQUEST_HEADERS
                    if name in request.headers
                },
                "body_sha256": hashlib.sha256(body).hexdigest(),
            },
            "response": {
                "status": response.status_code,
                "headers": {
                    name: response.headers[name]
                    for name in _RECORDED_RESPONSE_HEADERS
                    if name in response.headers
                },
                "body_base64": base64.b64encode(response.content).decode("ascii"),
            },
        }
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{self._index:04d}.json"
        path.write_text(json.dumps(page, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._index += 1
        return response

    def close(self) -> None:
        self._inner.close()
