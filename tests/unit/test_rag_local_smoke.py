"""Exercise the local smoke command through real HTTP request/response objects."""

from __future__ import annotations

import importlib
from pathlib import Path

import httpx
import pytest

from hippo.store.base import DEFAULT_SETTINGS

BASE_URL = "http://127.0.0.1:8011"
TOKEN = "fixture-token-never-print"


def run_smoke(monkeypatch, handler, *, token=TOKEN, base_url=BASE_URL, **client_options):
    path = Path(__file__).resolve().parents[2] / "scripts/rag_local_smoke.py"
    assert path.exists(), "Task 0 smoke command has not been implemented"
    smoke = importlib.import_module("scripts.rag_local_smoke")
    if token is None:
        monkeypatch.delenv("HIPPO_TOKEN", raising=False)
    else:
        monkeypatch.setenv("HIPPO_TOKEN", token)
    with httpx.Client(transport=httpx.MockTransport(handler), **client_options) as client:
        return smoke.main(["--base-url", base_url], client=client)


def healthy_status(**changes):
    return dict(
        store=True,
        store_backend="ladybug",
        ollama=True,
        models={"chat:latest": True, "embed:latest": True},
        models_ready=True,
        ready=True,
        embed_model_mismatch=False,
        **changes,
    )


def responder(request, *, status=None, settings=None, anonymous_status=401):
    if not request.headers.get("Authorization"):
        return httpx.Response(anonymous_status, json={"error": TOKEN})
    if request.headers["Authorization"] != f"Bearer {TOKEN}":
        return httpx.Response(401, json={"error": TOKEN})
    payload = (
        (status if status is not None else healthy_status())
        if request.url.path == "/api/status"
        else (settings if settings is not None else DEFAULT_SETTINGS)
    )
    return httpx.Response(200, json=payload)


def test_authenticated_ready_and_anonymous_refusal(monkeypatch, capsys):
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers.get("Authorization")))
        return responder(request)

    assert run_smoke(monkeypatch, handler) == 0
    output = capsys.readouterr().out
    assert "Server reachable" in output
    assert "Unauthenticated access denied" in output
    assert "Store ready" in output
    assert "models installed" in output
    assert "generation were not exercised" in output
    assert TOKEN not in output
    assert seen == [
        ("/api/settings", None),
        ("/api/status", f"Bearer {TOKEN}"),
        ("/api/settings", f"Bearer {TOKEN}"),
    ]


@pytest.mark.parametrize("token", [None, "", "invalid-token", "bad\r\nheader"])
def test_missing_or_invalid_token_fails_safely(monkeypatch, capsys, token):
    assert run_smoke(monkeypatch, responder, token=token) != 0
    output = capsys.readouterr().out
    assert "authentication" in output.lower() or "HIPPO_TOKEN" in output
    assert TOKEN not in output
    assert "invalid-token" not in output
    assert "bad" not in output


@pytest.mark.parametrize("anonymous_status", [200, 302, 500])
def test_open_or_broken_auth_gate_is_not_a_passing_smoke(monkeypatch, capsys, anonymous_status):
    assert run_smoke(monkeypatch, lambda r: responder(r, anonymous_status=anonymous_status)) != 0
    assert "Unauthenticated access denied" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"store": False, "ready": False}, "Store unavailable"),
        ({"ollama": False, "ready": False}, "Ollama unavailable"),
        ({"models": {"chat": False}, "models_ready": False, "ready": False}, "models missing"),
        ({"embed_model_mismatch": True}, "Embedding model mismatch"),
    ],
)
def test_dependency_readiness_is_separate_from_server_reachability(monkeypatch, capsys, changes, message):
    status = healthy_status()
    status.update(changes)
    assert run_smoke(monkeypatch, lambda r: responder(r, status=status)) != 0
    output = capsys.readouterr().out
    assert "Server reachable" in output
    assert message in output


@pytest.mark.parametrize(
    "status",
    [
        [],
        {},
        {**healthy_status(), "store": "true"},
        {**healthy_status(), "models": {}},
        {**healthy_status(), "models": {"chat": "true"}},
        {**healthy_status(), "models": {"chat": False}},
        {**healthy_status(), "models_ready": False},
        {**healthy_status(), "ready": False},
        {**healthy_status(), "embed_model_mismatch": "false"},
    ],
)
def test_invalid_status_schema_or_inconsistent_readiness(monkeypatch, capsys, status):
    assert run_smoke(monkeypatch, lambda r: responder(r, status=status)) != 0
    assert "/api/status: invalid schema" in capsys.readouterr().out


@pytest.mark.parametrize(
    "settings",
    [
        [],
        {},
        {**DEFAULT_SETTINGS, "damping": TOKEN},
        {**DEFAULT_SETTINGS, "damping": 7},
        {**DEFAULT_SETTINGS, "node_specificity": "true"},
        {**DEFAULT_SETTINGS, "qa_top_k": True},
    ],
)
def test_invalid_settings_schema_fails_without_echoing_values(monkeypatch, capsys, settings):
    assert run_smoke(monkeypatch, lambda r: responder(r, settings=settings)) != 0
    output = capsys.readouterr().out
    assert "/api/settings: invalid schema" in output
    assert TOKEN not in output


@pytest.mark.parametrize("endpoint", ["/api/status", "/api/settings"])
@pytest.mark.parametrize("failure", ["json", "http", "network"])
def test_bad_response_or_network_failure_is_sanitized(monkeypatch, capsys, endpoint, failure):
    def handler(request):
        if request.headers.get("Authorization") and request.url.path == endpoint:
            if failure == "network":
                raise httpx.ConnectError(TOKEN, request=request)
            if failure == "http":
                return httpx.Response(503, text=TOKEN)
            return httpx.Response(200, text=TOKEN)
        return responder(request)

    assert run_smoke(monkeypatch, handler) != 0
    output = capsys.readouterr().out
    assert endpoint in output
    assert TOKEN not in output


def test_unreachable_server_is_not_reported_reachable(monkeypatch, capsys):
    def handler(request):
        raise httpx.ConnectTimeout(TOKEN, request=request)

    assert run_smoke(monkeypatch, handler) != 0
    output = capsys.readouterr().out
    assert "Server reachable" not in output
    assert "network" in output
    assert TOKEN not in output


@pytest.mark.parametrize("redirect", ["http://example.test/stolen", BASE_URL + "/other"])
def test_redirects_are_never_followed_even_with_redirecting_injected_client(monkeypatch, capsys, redirect):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.headers.get("Authorization"):
            return httpx.Response(307, headers={"Location": redirect})
        return responder(request)

    assert run_smoke(monkeypatch, handler, follow_redirects=True) != 0
    assert redirect not in seen
    assert TOKEN not in capsys.readouterr().out


def test_injected_client_cookies_default_headers_and_auth_do_not_bypass_probe(monkeypatch):
    def handler(request):
        assert "cookie" not in request.headers
        if request.url.path == "/api/settings" and "Authorization" not in request.headers:
            return httpx.Response(401)
        return responder(request)

    assert (
        run_smoke(
            monkeypatch,
            handler,
            headers={"Authorization": "Bearer injected"},
            auth=("user", "password"),
            cookies={"hippo_session": "session"},
        )
        == 0
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://example.test",
        "http://user:secret@localhost",
        "http://localhost/path",
        "http://localhost?secret=yes",
        "http://localhost#secret",
        "file:///tmp/thing",
        "http://localhost:99999",
        "http://localhost\n",
        "http://127.0.0.1.evil.test",
    ],
)
def test_nonlocal_or_ambiguous_origins_are_rejected_before_sending_credentials(monkeypatch, capsys, base_url):
    def handler(request):
        pytest.fail("Invalid origin must not receive a request")

    assert run_smoke(monkeypatch, handler, base_url=base_url) != 0
    output = capsys.readouterr().out
    assert "base URL" in output
    assert "secret" not in output


@pytest.mark.parametrize(
    "base_url", ["http://localhost:8011/", "http://[::1]:8011", "https://127.0.0.1:8011"]
)
def test_supported_loopback_origins(monkeypatch, base_url):
    assert run_smoke(monkeypatch, responder, base_url=base_url) == 0
