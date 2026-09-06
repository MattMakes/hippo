"""The request guard's pure pieces: host parsing, the allow list, and the config that feeds them."""

from __future__ import annotations

from starlette.datastructures import Headers

from hippo.config import DEFAULT_ALLOWED_HOSTS, Config, load_config, parse_allowed_hosts
from hippo.web.security import HostAndOriginGuard, host_allowed, host_name

LOCAL = ("localhost", "127.0.0.1", "[::1]")


def headers(**values: str) -> Headers:
    return Headers({k.replace("_", "-"): v for k, v in values.items()})


def test_host_name_strips_ports_schemes_and_ipv6_brackets():
    assert host_name("localhost:8000") == "localhost"
    assert host_name("localhost") == "localhost"
    assert host_name("[::1]:8000") == "::1"
    assert host_name("[::1]") == "::1"
    assert host_name("https://evil.example/page") == "evil.example"
    assert host_name("http://127.0.0.1:8000/ask") == "127.0.0.1"
    assert host_name("LOCALHOST:8000") == "localhost"
    assert host_name("") is None and host_name(None) is None
    assert host_name("[") is None  # an unreadable IPv6 literal is not a match for anything


def test_host_allowed_matches_names_not_substrings():
    assert host_allowed("localhost:8000", LOCAL)
    assert host_allowed("[::1]:8000", LOCAL)
    assert host_allowed("http://127.0.0.1:8000", LOCAL)
    assert not host_allowed("localhost.evil.example", LOCAL)
    assert not host_allowed("evil.example", LOCAL)
    assert not host_allowed("null", LOCAL)  # the Origin a sandboxed page sends
    assert not host_allowed(None, LOCAL)
    assert host_allowed("anything.example", ("localhost", "*"))


def test_guard_refuses_foreign_hosts_and_cross_site_writes():
    guard = HostAndOriginGuard(app=None, allowed_hosts=LOCAL)
    assert guard.reject_reason("GET", headers(host="localhost:8000")) is None
    assert guard.reject_reason("GET", headers(host="evil.example"))[0] == 400
    assert guard.reject_reason("GET", Headers({}))[0] == 400  # no Host at all
    # Reads with a foreign Origin are fine (the browser will not show the response cross-site anyway).
    assert guard.reject_reason("GET", headers(host="localhost", origin="https://evil.example")) is None
    for method in ("POST", "PUT", "PATCH", "DELETE", "post"):
        assert guard.reject_reason(method, headers(host="localhost")) is None, method
        assert guard.reject_reason(method, headers(host="localhost", origin="http://localhost:8000")) is None
        assert guard.reject_reason(method, headers(host="localhost", sec_fetch_site="same-origin")) is None
        assert guard.reject_reason(method, headers(host="localhost", sec_fetch_site="none")) is None
        assert guard.reject_reason(method, headers(host="localhost", origin="https://evil.example"))[0] == 403
        assert (
            guard.reject_reason(method, headers(host="localhost", referer="https://evil.example/"))[0] == 403
        )
        assert guard.reject_reason(method, headers(host="localhost", sec_fetch_site="cross-site"))[0] == 403
    # Origin wins over Referer when both are present.
    both = headers(host="localhost", origin="http://localhost:8000", referer="https://evil.example/")
    assert guard.reject_reason("POST", both) is None


def test_allowed_hosts_config_extends_the_defaults(monkeypatch):
    assert Config().allowed_hosts == DEFAULT_ALLOWED_HOSTS
    assert parse_allowed_hosts("") == DEFAULT_ALLOWED_HOSTS
    assert parse_allowed_hosts(" mybox, 192.168.1.5 ,localhost") == (
        *DEFAULT_ALLOWED_HOSTS,
        "mybox",
        "192.168.1.5",
    )
    monkeypatch.setenv("HIPPO_ALLOWED_HOSTS", "mybox")
    assert load_config().allowed_hosts == (*DEFAULT_ALLOWED_HOSTS, "mybox")
    monkeypatch.setenv("HIPPO_ALLOWED_HOSTS", "*")
    assert "*" in load_config().allowed_hosts
