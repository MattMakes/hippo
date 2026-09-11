#!/usr/bin/env python
"""Check an isolated local Hippo server without changing its data.

Run with HIPPO_TOKEN in the environment after creating an account:
    .venv/bin/python scripts/rag_local_smoke.py --base-url http://127.0.0.1:8011

Exit 0 means the protected status/settings contracts pass, the store responds,
and configured models are installed. This does not perform retrieval, embedding,
or generation. Exit 1 means a failed check; exit 2 means invalid configuration.
Response bodies, model names, URLs and exception strings are never printed.
"""

from __future__ import annotations

import argparse
import math
import os
from contextlib import nullcontext
from urllib.parse import urlsplit

import httpx

from hippo.store.base import SETTING_RULES


def local_origin(value: str) -> str:
    """Only accept the loopback origins supported by Hippo's default host guard."""
    try:
        parts = urlsplit(value)
        valid = (
            not any(ord(char) <= 32 or ord(char) == 127 for char in value)
            and parts.scheme in {"http", "https"}
            and parts.hostname in {"localhost", "127.0.0.1", "::1"}
            and parts.username is None
            and parts.password is None
            and parts.path in {"", "/"}
            and not parts.query
            and not parts.fragment
            and (parts.port is None or 0 < parts.port <= 65535)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Invalid base URL: use an HTTP(S) loopback origin without credentials or a path.")
    return value.rstrip("/")


def status_schema(value: object) -> bool:
    """Validate the readiness subset; optional display fields may evolve independently."""
    if not isinstance(value, dict):
        return False
    flags = ("store", "ollama", "models_ready", "ready", "embed_model_mismatch")
    if any(type(value.get(key)) is not bool for key in flags):
        return False
    models = value.get("models")
    if not isinstance(models, dict) or not models:
        return False
    if any(
        not isinstance(name, str) or not name.strip() or type(ready) is not bool
        for name, ready in models.items()
    ):
        return False
    models_ready = all(models.values())
    return value["models_ready"] == models_ready and value["ready"] == (
        value["store"] and value["ollama"] and models_ready
    )


def settings_schema(value: object) -> bool:
    """Check current keys strictly against app types/ranges without coercing JSON strings."""
    if not isinstance(value, dict):
        return False
    for key, (kind, low, high) in SETTING_RULES.items():
        item = value.get(key)
        if kind is bool:
            if type(item) is not bool:
                return False
            continue
        types = (int, float) if kind is float else (int,)
        if type(item) not in types:
            return False
        if isinstance(item, float) and not math.isfinite(item):
            return False
        if (low is not None and item < low) or (high is not None and item > high):
            return False
    return True


def request(client: httpx.Client, origin: str, endpoint: str, token: str | None = None):
    """Bypass injected client cookies/default auth, and prohibit redirects at every call."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    outgoing = httpx.Request(
        "GET",
        origin + endpoint,
        headers=headers,
        extensions={"timeout": {key: 10.0 for key in ("connect", "read", "write", "pool")}},
    )
    try:
        return client.send(outgoing, auth=None, follow_redirects=False)
    except httpx.HTTPError:
        print(f"FAIL {endpoint}: network or protocol error.")
        return None


def read_json(client: httpx.Client, origin: str, endpoint: str, token: str):
    response = request(client, origin, endpoint, token)
    if response is None:
        return None
    if response.status_code != 200:
        if response.status_code in {401, 403}:
            print(f"FAIL {endpoint}: authentication refused (HTTP {response.status_code}).")
        else:
            print(f"FAIL {endpoint}: HTTP {response.status_code}; redirects are not followed.")
        return None
    try:
        return response.json()
    except ValueError:
        print(f"FAIL {endpoint}: invalid JSON.")
        return None


def check(client: httpx.Client, origin: str, token: str | None) -> int:
    anonymous = request(client, origin, "/api/settings")
    if anonymous is None:
        return 1
    print("PASS Server reachable (an HTTP response was received).")
    if anonymous.status_code not in {401, 403}:
        print(f"FAIL Unauthenticated protected access was not refused (HTTP {anonymous.status_code}).")
        return 1
    print("PASS Unauthenticated access denied.")
    if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
        print("FAIL HIPPO_TOKEN is missing or has an invalid authentication header format.")
        return 2

    status = read_json(client, origin, "/api/status", token)
    settings = read_json(client, origin, "/api/settings", token)
    status_valid = status_schema(status)
    settings_valid = settings_schema(settings)
    if not status_valid:
        print("FAIL /api/status: invalid schema or inconsistent readiness flags.")
    if not settings_valid:
        print("FAIL /api/settings: invalid schema.")
    if not status_valid or not settings_valid:
        return 1
    print("PASS Authenticated status and settings contracts.")
    failures = []
    if not status["store"]:
        failures.append("Store unavailable.")
    if not status["ollama"]:
        failures.append("Ollama unavailable.")
    if not status["models_ready"]:
        failures.append(
            "Configured models missing; use hippo pull-models with the isolated server environment."
        )
    if status["embed_model_mismatch"]:
        failures.append(
            "Embedding model mismatch; indexed vectors require compatible configuration or reindexing."
        )
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        return 1
    print("PASS Store ready; configured models installed.")
    print("Retrieval, embedding and generation were not exercised by this smoke check.")
    return 0


def main(argv: list[str] | None = None, *, client: httpx.Client | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Isolated HTTP(S) loopback origin")
    args = parser.parse_args(argv)
    try:
        origin = local_origin(args.base_url)
    except ValueError as exc:
        print(str(exc))  # This exception contains a fixed message, never the supplied URL.
        return 2
    # Ignore proxy/netrc environment settings so the local account token stays local.
    manager = nullcontext(client) if client is not None else httpx.Client(trust_env=False)
    with manager as active_client:
        return check(active_client, origin, os.environ.get("HIPPO_TOKEN"))


if __name__ == "__main__":
    raise SystemExit(main())
