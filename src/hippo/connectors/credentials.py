"""Credential references: a connector configuration names where a secret lives, never the secret.

Design `docs/spec/connector-developer-kit.md` section 8, plan `ai_docs/plans/cdk-s3-runtime.md`
sections 4.2 and 10.3. `Connector.credential_ref` (`knowledge/model.py`) stores one of the two
references this module understands, `env:NAME` or `file:/absolute/path`, and the value is read fresh
on every sync so that rotating it needs no write.

Two rules hold everywhere below. A message names the reference and never a value, so a refusal is
safe to log and safe to return from a route. And a URL that leaves this process goes through
`redact_url` first: userinfo is dropped and any query value whose name looks like a secret becomes
`REDACTED`, while every other byte of the URL is preserved so that `redact_url(u) != u` is a reliable
"this URL carries a secret" test for callers.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import unquote, urlsplit, urlunsplit

from pydantic import BaseModel

REFERENCE_RULE = "Credential references are env:NAME or file:/absolute/path"
REDACTED = "REDACTED"

_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
_SECRET_QUERY_NAMES = ("token", "key", "secret", "password", "signature", "sig", "code")
_SECRET_FIELD_NAMES = ("token", "password", "secret", "api_key", "credential")


class CredentialError(ValueError):
    """A credential reference cannot be resolved; the message names the reference, never a value."""


@dataclass(frozen=True, slots=True)
class CredentialRef:
    scheme: Literal["env", "file"]
    name: str

    def __str__(self) -> str:
        return f"{self.scheme}:{self.name}"

    @classmethod
    def parse(cls, value: str) -> CredentialRef:
        scheme, separator, name = (value or "").partition(":")
        if not separator or not name:
            raise CredentialError(REFERENCE_RULE)
        if scheme == "env" and _ENV_NAME.fullmatch(name):
            return cls(scheme="env", name=name)
        if scheme == "file" and name.startswith("/") and ".." not in name.split("/"):
            return cls(scheme="file", name=name)
        raise CredentialError(REFERENCE_RULE)


@dataclass(frozen=True, slots=True, repr=False)
class ResolvedCredential:
    ref: CredentialRef
    _secret: str = field(repr=False)

    def authorization(self, scheme: Literal["Bearer", "Basic", "Token"] = "Bearer") -> tuple[str, str]:
        """The one header a connector sends, ready to put on a request."""
        return ("Authorization", f"{scheme} {self._secret}")

    def __repr__(self) -> str:
        return f"ResolvedCredential(ref={self.ref!r}, secret=<redacted>)"


def resolve(
    ref: str, *, environ: Mapping[str, str] | None = None, max_bytes: int = 64_000
) -> ResolvedCredential:
    """Read the secret a reference names, refusing anything a secret should not be stored in."""
    parsed = CredentialRef.parse(ref)
    if parsed.scheme == "env":
        source = os.environ if environ is None else environ
        value = source.get(parsed.name) or ""
        if not value:
            raise CredentialError(f"Credential {parsed} names an environment variable that is unset or empty")
        return ResolvedCredential(ref=parsed, _secret=value)
    return ResolvedCredential(ref=parsed, _secret=_read_private_file(parsed, max_bytes))


def _read_private_file(ref: CredentialRef, max_bytes: int) -> str:
    try:
        descriptor = os.open(ref.name, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        # O_NOFOLLOW is how a symlink is refused: the open itself fails with ELOOP.
        raise CredentialError(f"Credential {ref} cannot be opened ({error.strerror})") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise CredentialError(f"Credential {ref} is not a regular file")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise CredentialError(f"Credential {ref} is readable by group or others; chmod 600 it")
        if info.st_size > max_bytes:
            raise CredentialError(f"Credential {ref} is larger than {max_bytes} bytes")
        raw = os.read(descriptor, max_bytes + 1)
    finally:
        os.close(descriptor)
    if len(raw) > max_bytes:
        raise CredentialError(f"Credential {ref} is larger than {max_bytes} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CredentialError(f"Credential {ref} is not UTF-8 text") from error
    if not text:
        raise CredentialError(f"Credential {ref} names an empty file")
    return text[:-1] if text.endswith("\n") else text


def redact_url(url: str) -> str:
    """Drop userinfo and blank every secret-looking query value, leaving every other byte alone."""
    parsed = urlsplit(url)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc.rpartition("@")[2],
            parsed.path,
            _redact_query(parsed.query),
            parsed.fragment,
        )
    )


def _redact_query(query: str) -> str:
    if not query:
        return query
    pairs = []
    for pair in query.split("&"):
        name, separator, _value = pair.partition("=")
        pairs.append(f"{name}={REDACTED}" if separator and _names_a_secret(name) else pair)
    return "&".join(pairs)


def _names_a_secret(name: str) -> bool:
    lowered = unquote(name).lower()
    return any(word in lowered for word in _SECRET_QUERY_NAMES)


def refuse_inline_secrets(config: BaseModel) -> None:
    """Refuse a connector configuration that carries a secret instead of pointing at one."""
    for name in type(config).model_fields:
        lowered = name.lower()
        if any(word in lowered for word in _SECRET_FIELD_NAMES):
            raise CredentialError(
                f"Connector configuration names a secret field {name}; store a credential_ref instead"
            )
