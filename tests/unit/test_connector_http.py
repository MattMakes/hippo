"""The bounded provider client: six error classes, capped retries, recording and replay.

Plan `ai_docs/plans/cdk-s3-runtime.md` sections 4.3 and 10.2, with ruling B4 (the transports are
specified once, here, and `replay_transport` raises `ProviderMalformedError` on an unexpected
request) and R27 (no clock argument beyond the injectable ones this client already takes).

Nothing here opens a socket: every case runs over `httpx.MockTransport`, and every clock, sleep and
random source is injected, so the retry schedule is asserted exactly rather than approximately.
"""

import base64
import email.utils
import json
import random
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from hippo.connectors.credentials import CredentialRef, ResolvedCredential
from hippo.connectors.http import (
    ERROR_CLASSES,
    HttpLimits,
    ProviderAuthenticationError,
    ProviderClient,
    ProviderError,
    ProviderForbiddenError,
    ProviderMalformedError,
    ProviderNotFoundError,
    ProviderThrottledError,
    ProviderTransientError,
    record_transport,
    replay_transport,
)

INSTANCE = "https://provider.example/api"
WALL = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
SECRET = "s3cr3t-token-value"


def _credential() -> ResolvedCredential:
    return ResolvedCredential(ref=CredentialRef(scheme="env", name="PROVIDER_TOKEN"), _secret=SECRET)


def _stopped_clock():
    return 0.0


def _stepping(step: float):
    """A monotonic clock that advances by `step` on every reading."""
    ticks = iter(range(0, 1_000_000))
    return lambda: next(ticks) * step


def _client(handler, *, limits=None, sleeps=None, monotonic=None, credential=None, base=INSTANCE, seed=7):
    return ProviderClient(
        base,
        limits=limits if limits is not None else HttpLimits(),
        transport=httpx.MockTransport(handler),
        credential=credential,
        monotonic=monotonic if monotonic is not None else _stopped_clock,
        wall_clock=lambda: WALL,
        sleep=(sleeps.append if sleeps is not None else (lambda _seconds: None)),
        rng=random.Random(seed),
    )


def _status(status: int, **kwargs):
    return lambda request: httpx.Response(status, **kwargs)


STATUS_CLASSES = {
    401: (ProviderAuthenticationError, "authentication"),
    403: (ProviderForbiddenError, "forbidden"),
    404: (ProviderNotFoundError, "not_found"),
    410: (ProviderNotFoundError, "not_found"),
    429: (ProviderThrottledError, "throttled"),
    408: (ProviderTransientError, "transient"),
    500: (ProviderTransientError, "transient"),
    503: (ProviderTransientError, "transient"),
    418: (ProviderMalformedError, "malformed"),
}


def test_the_six_error_classes_are_the_closed_set() -> None:
    assert ERROR_CLASSES == (
        "authentication",
        "forbidden",
        "not_found",
        "throttled",
        "transient",
        "malformed",
    )
    raised = {error.error_class for error, _ in STATUS_CLASSES.values()}
    assert raised == set(ERROR_CLASSES)


@pytest.mark.parametrize("status", sorted(STATUS_CLASSES))
def test_each_status_maps_to_its_error_class(status) -> None:
    expected_error, expected_class = STATUS_CLASSES[status]
    client = _client(_status(status, text="a body nobody should see"), limits=HttpLimits(max_attempts=1))

    with pytest.raises(expected_error) as caught:
        client.get_bytes("notes/1")

    assert isinstance(caught.value, ProviderError)
    assert caught.value.error_class == expected_class
    assert caught.value.status == status
    assert caught.value.attempts == 1


def test_transport_errors_are_transient_and_invalid_json_is_malformed() -> None:
    def refused(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ProviderTransientError) as caught:
        _client(refused, limits=HttpLimits(max_attempts=1)).get_bytes("notes/1")
    assert caught.value.status is None
    assert caught.value.attempts == 1

    broken = _status(200, content=b'{"id": ', headers={"content-type": "application/json"})
    with pytest.raises(ProviderMalformedError) as malformed:
        _client(broken).get_json("notes/1")
    assert malformed.value.status == 200

    # Only `get_json` parses: the same body is bytes to `get_bytes`.
    body, headers = _client(broken).get_bytes("notes/1")
    assert body == b'{"id": '
    assert headers["content-type"] == "application/json"


def test_throttled_and_transient_retry_with_capped_jittered_backoff() -> None:
    limits = HttpLimits(
        max_attempts=4, backoff_base_seconds=0.5, backoff_cap_seconds=2.0, max_total_seconds=10_000.0
    )
    sleeps: list[float] = []

    with pytest.raises(ProviderTransientError) as caught:
        _client(_status(503), limits=limits, sleeps=sleeps, seed=7).get_bytes("notes/1")

    assert caught.value.attempts == 4
    expected_rng = random.Random(7)
    assert sleeps == [min(2.0, 0.5 * 2**step) * expected_rng.uniform(0.5, 1.0) for step in range(3)]

    # A 429 with no Retry-After takes the same schedule.
    throttled_sleeps: list[float] = []
    with pytest.raises(ProviderThrottledError):
        _client(_status(429), limits=limits, sleeps=throttled_sleeps, seed=7).get_bytes("notes/1")
    assert throttled_sleeps == sleeps


def test_retry_after_seconds_and_http_date_are_honoured_and_capped() -> None:
    def flaky(header_value):
        seen = []

        def handler(request):
            seen.append(request)
            if len(seen) == 1:
                return httpx.Response(429, headers={"retry-after": header_value})
            return httpx.Response(200, json={"id": 1})

        return handler

    seconds_sleeps: list[float] = []
    assert _client(flaky("2"), sleeps=seconds_sleeps).get_json("notes/1") == {"id": 1}
    assert seconds_sleeps == [2.0]

    http_date = email.utils.format_datetime(WALL.replace(second=3), usegmt=True)
    date_sleeps: list[float] = []
    assert _client(flaky(http_date), sleeps=date_sleeps).get_json("notes/1") == {"id": 1}
    assert date_sleeps == [3.0]

    capped_sleeps: list[float] = []
    limits = HttpLimits(max_attempts=5, max_retry_after_seconds=300.0)
    with pytest.raises(ProviderThrottledError) as caught:
        _client(flaky("9999"), limits=limits, sleeps=capped_sleeps).get_json("notes/1")
    assert capped_sleeps == []
    assert caught.value.attempts == 1
    assert caught.value.retry_after == 9999.0


def test_attempts_and_total_duration_are_capped() -> None:
    attempt_sleeps: list[float] = []
    with pytest.raises(ProviderTransientError) as caught:
        _client(_status(503), limits=HttpLimits(max_attempts=2), sleeps=attempt_sleeps).get_bytes("notes/1")
    assert caught.value.attempts == 2
    assert len(attempt_sleeps) == 1

    # A clock that jumps a minute per reading exhausts a 100-second budget after the first sleep.
    duration_sleeps: list[float] = []
    limits = HttpLimits(max_attempts=5, max_total_seconds=100.0)
    with pytest.raises(ProviderTransientError) as timed_out:
        _client(_status(503), limits=limits, sleeps=duration_sleeps, monotonic=_stepping(60.0)).get_bytes(
            "notes/1"
        )
    assert timed_out.value.attempts == 2
    assert len(duration_sleeps) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 410, 418])
def test_authentication_forbidden_not_found_and_malformed_never_retry(status) -> None:
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status)

    sleeps: list[float] = []
    with pytest.raises(ProviderError) as caught:
        _client(handler, limits=HttpLimits(max_attempts=5), sleeps=sleeps).get_bytes("notes/1")

    assert sleeps == []
    assert len(seen) == 1
    assert caught.value.attempts == 1


def test_a_response_over_the_size_cap_is_malformed_before_it_is_read_whole() -> None:
    produced: list[int] = []

    def streaming(request):
        def chunks():
            for index in range(8):
                produced.append(index)
                yield b"x" * 8

        return httpx.Response(200, content=chunks())

    with pytest.raises(ProviderMalformedError):
        _client(streaming, limits=HttpLimits(max_response_bytes=10)).get_bytes("notes/1")
    assert 0 < len(produced) < 8, produced

    # A declared Content-Length over the cap is refused without reading the body at all.
    declared: list[int] = []

    def sized(request):
        declared.append(1)
        return httpx.Response(200, content=b"x" * 100)

    with pytest.raises(ProviderMalformedError) as caught:
        _client(sized, limits=HttpLimits(max_response_bytes=10)).get_bytes("notes/1")
    assert caught.value.status == 200

    # Exactly at the cap is fine.
    body, _headers = _client(
        _status(200, content=b"y" * 10), limits=HttpLimits(max_response_bytes=10)
    ).get_bytes("notes/1")
    assert body == b"y" * 10


def test_a_redirect_is_refused_and_credentials_never_cross_it() -> None:
    seen: list[httpx.Request] = []

    def redirecting(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://elsewhere.example/steal"})

    with pytest.raises(ProviderMalformedError) as caught:
        _client(redirecting, credential=_credential()).get_bytes("notes/1")

    assert caught.value.status == 302
    assert len(seen) == 1, "the client followed the redirect"
    assert str(seen[0].url) == f"{INSTANCE}/notes/1"
    assert seen[0].headers["authorization"] == f"Bearer {SECRET}"
    assert "elsewhere.example" not in str(caught.value)


@pytest.mark.parametrize(
    "path",
    [
        "/notes/1",
        "../notes/1",
        "notes/../../etc/passwd",
        "https://elsewhere.example/notes/1",
        "//elsewhere.example/notes/1",
        "notes/1?page=2",
        "notes/1#fragment",
        "notes\\1",
        "",
    ],
)
def test_an_absolute_or_escaping_path_is_refused(path) -> None:
    client = _client(_status(200, json={}))
    with pytest.raises(ValueError, match="Provider paths are relative to the configured instance"):
        client.get_bytes(path)


def test_a_relative_path_is_joined_under_the_instance_base_path() -> None:
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": 1})

    client = _client(handler)
    assert client.get_json("notes/1", params={"page": "2"}) == {"id": 1}
    # The instance's own path segment survives the join; httpx.URL.join would drop "/api".
    assert str(seen[0].url) == f"{INSTANCE}/notes/1?page=2"


def test_a_base_url_with_credentials_or_a_query_is_refused() -> None:
    for base in ("https://user:pw@provider.example/api", "https://provider.example/api?token=x", "ftp://x/y"):
        with pytest.raises(ValueError):
            ProviderClient(base, transport=httpx.MockTransport(_status(200, json={})))


def test_errors_carry_a_redacted_url_and_never_a_body() -> None:
    client = _client(
        _status(500, text="internal stack trace with a secret"), limits=HttpLimits(max_attempts=1)
    )

    with pytest.raises(ProviderTransientError) as caught:
        client.get_bytes("notes/1", params={"api_token": SECRET, "page": "2"})

    error = caught.value
    message = str(error)
    assert SECRET not in message and SECRET not in error.url
    assert "REDACTED" in error.url
    assert "page=2" in error.url
    assert "internal stack trace" not in message
    assert "500" in message
    assert error.url in message


def test_get_bytes_returns_the_body_and_the_response_headers() -> None:
    handler = _status(200, content=b"raw bytes", headers={"content-type": "text/plain", "link": "<next>"})
    body, headers = _client(handler).get_bytes("notes/1")
    assert body == b"raw bytes"
    assert headers["content-type"] == "text/plain"
    assert headers["link"] == "<next>"


def _recorded_pages(case_dir: Path) -> list[dict]:
    return [json.loads(path.read_text()) for path in sorted((case_dir / "http").glob("*.json"))]


def test_record_then_replay_reproduces_the_exchanges_in_order(tmp_path) -> None:
    def inner(request):
        note = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"id": note}, headers={"link": f"<notes/{note}>"})

    recorder = record_transport(tmp_path, httpx.MockTransport(inner))
    recording_client = ProviderClient(INSTANCE, transport=recorder, credential=_credential())
    first = recording_client.get_json("notes/1")
    second = recording_client.get_json("notes/2")
    recording_client.close()

    pages = _recorded_pages(tmp_path)
    assert len(pages) == 2
    assert [page["request"]["url"] for page in pages] == [f"{INSTANCE}/notes/1", f"{INSTANCE}/notes/2"]
    assert pages[0]["response"]["status"] == 200
    assert json.loads(base64.b64decode(pages[0]["response"]["body_base64"])) == {"id": "1"}
    assert pages[0]["response"]["headers"]["link"] == "<notes/1>"

    replaying_client = ProviderClient(INSTANCE, transport=replay_transport(tmp_path))
    assert replaying_client.get_json("notes/1") == first
    assert replaying_client.get_json("notes/2") == second
    replaying_client.close()


def test_replay_refuses_an_unexpected_request(tmp_path) -> None:
    recorder = record_transport(tmp_path, httpx.MockTransport(_status(200, json={"id": 1})))
    recording = ProviderClient(INSTANCE, transport=recorder)
    recording.get_json("notes/1")
    recording.close()

    wrong_path = ProviderClient(INSTANCE, transport=replay_transport(tmp_path))
    with pytest.raises(ProviderMalformedError):
        wrong_path.get_json("notes/9")

    exhausted = ProviderClient(INSTANCE, transport=replay_transport(tmp_path))
    assert exhausted.get_json("notes/1") == {"id": 1}
    with pytest.raises(ProviderMalformedError):
        exhausted.get_json("notes/1")


def test_a_recording_contains_no_authorization_header_or_secret_query_value(tmp_path) -> None:
    recorder = record_transport(tmp_path, httpx.MockTransport(_status(200, json={"id": 1})))
    client = ProviderClient(INSTANCE, transport=recorder, credential=_credential())
    client.get_json("notes/1", params={"access_token": SECRET, "page": "1"})
    client.close()

    raw = (tmp_path / "http" / "0000.json").read_text()
    assert SECRET not in raw
    assert "authorization" not in raw.lower()

    page = json.loads(raw)
    assert page["request"]["method"] == "GET"
    assert "access_token=REDACTED" in page["request"]["url"]
    assert "page=1" in page["request"]["url"]
    assert set(page["request"]["headers"]) <= {"accept", "content-type"}
    assert page["request"]["body_sha256"] == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
