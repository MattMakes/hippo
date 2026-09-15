"""Credential references: environment variables and private files, and nothing inline.

Plan `ai_docs/plans/cdk-s3-runtime.md` sections 4.2 and 10.3. No test here reads
`.rag-dev-data/smoke-credentials.json` or any real token: every secret is a string this file makes
up, placed in an environment variable or a file the test creates under `tmp_path`.
"""

import os
import stat

import pytest
from pydantic import BaseModel, ConfigDict

from hippo.connectors.credentials import (
    CredentialError,
    CredentialRef,
    ResolvedCredential,
    redact_url,
    refuse_inline_secrets,
    resolve,
)

SECRET = "not-a-real-token-6f21"
REFERENCE_RULE = "Credential references are env:NAME or file:/absolute/path"


def _private_file(tmp_path, name="provider.token", text=f"{SECRET}\n", mode=0o600):
    path = tmp_path / name
    path.write_text(text)
    path.chmod(mode)
    return path


def test_env_and_file_references_parse_and_others_refuse() -> None:
    env = CredentialRef.parse("env:PROVIDER_TOKEN")
    assert (env.scheme, env.name) == ("env", "PROVIDER_TOKEN")

    file_ref = CredentialRef.parse("file:/etc/hippo/provider.token")
    assert (file_ref.scheme, file_ref.name) == ("file", "/etc/hippo/provider.token")

    for bad in (
        "PROVIDER_TOKEN",
        "env:lowercase",
        "env:1STARTS_WITH_A_DIGIT",
        "env:WITH-A-DASH",
        "env:",
        "file:relative/path",
        "file:/escapes/../upward",
        "file:",
        "vault:secret/provider",
        "",
        "env:NAME:EXTRA",
    ):
        with pytest.raises(CredentialError, match=REFERENCE_RULE):
            CredentialRef.parse(bad)


def test_env_reference_resolves_and_a_missing_variable_names_only_the_reference(monkeypatch) -> None:
    resolved = resolve("env:PROVIDER_TOKEN", environ={"PROVIDER_TOKEN": SECRET})
    assert resolved.ref == CredentialRef(scheme="env", name="PROVIDER_TOKEN")
    assert resolved.authorization() == ("Authorization", f"Bearer {SECRET}")
    assert resolved.authorization("Token") == ("Authorization", f"Token {SECRET}")
    assert resolved.authorization("Basic") == ("Authorization", f"Basic {SECRET}")

    with pytest.raises(CredentialError) as caught:
        resolve("env:PROVIDER_TOKEN", environ={})
    assert "env:PROVIDER_TOKEN" in str(caught.value)

    with pytest.raises(CredentialError):
        resolve("env:PROVIDER_TOKEN", environ={"PROVIDER_TOKEN": ""})

    # With no mapping the process environment is the source.
    monkeypatch.setenv("PROVIDER_TOKEN", SECRET)
    assert resolve("env:PROVIDER_TOKEN").authorization()[1] == f"Bearer {SECRET}"
    assert os.environ["PROVIDER_TOKEN"] == SECRET


def test_file_reference_refuses_symlinks_oversize_and_group_readable_files(tmp_path) -> None:
    private = _private_file(tmp_path)
    assert resolve(f"file:{private}").authorization() == ("Authorization", f"Bearer {SECRET}")

    link = tmp_path / "link.token"
    link.symlink_to(private)
    with pytest.raises(CredentialError) as symlinked:
        resolve(f"file:{link}")
    assert str(link) in str(symlinked.value)
    assert SECRET not in str(symlinked.value)

    with pytest.raises(CredentialError):
        resolve(f"file:{private}", max_bytes=4)

    group_readable = _private_file(tmp_path, name="group.token", mode=0o640)
    with pytest.raises(CredentialError) as shared:
        resolve(f"file:{group_readable}")
    assert SECRET not in str(shared.value)
    assert stat.S_IMODE(group_readable.stat().st_mode) == 0o640

    directory = tmp_path / "adirectory"
    directory.mkdir(mode=0o700)
    with pytest.raises(CredentialError):
        resolve(f"file:{directory}")

    with pytest.raises(CredentialError) as missing:
        resolve(f"file:{tmp_path / 'absent.token'}")
    assert "absent.token" in str(missing.value)


def test_a_file_credential_strips_one_trailing_newline_only(tmp_path) -> None:
    bare = _private_file(tmp_path, name="bare", text=SECRET)
    one = _private_file(tmp_path, name="one", text=SECRET + "\n")
    two = _private_file(tmp_path, name="two", text=SECRET + "\n\n")

    assert resolve(f"file:{bare}")._secret == SECRET
    assert resolve(f"file:{one}")._secret == SECRET
    assert resolve(f"file:{two}")._secret == SECRET + "\n"


def test_resolved_credential_repr_and_str_never_show_the_secret() -> None:
    resolved = resolve("env:PROVIDER_TOKEN", environ={"PROVIDER_TOKEN": SECRET})

    for rendering in (repr(resolved), str(resolved), f"{resolved}", format(resolved)):
        assert SECRET not in rendering
        assert "<redacted>" in rendering
        assert "PROVIDER_TOKEN" in rendering

    assert SECRET not in repr({"credential": resolved})
    assert SECRET not in repr([resolved])
    assert resolved._secret == SECRET


def test_redact_url_removes_userinfo_and_secret_query_values() -> None:
    assert redact_url("https://u:pw@provider.example/api/notes") == "https://provider.example/api/notes"
    assert redact_url("https://u@provider.example/api") == "https://provider.example/api"

    redacted = redact_url("https://provider.example/api?token=abc&page=2&API_KEY=def")
    assert redacted == "https://provider.example/api?token=REDACTED&page=2&API_KEY=REDACTED"

    for name in ("token", "Access-Token", "apikey", "client_secret", "PASSWORD", "signature", "sig", "code"):
        assert redact_url(f"https://p.example/x?{name}=abc") == f"https://p.example/x?{name}=REDACTED"

    # A URL with nothing secret in it comes back byte for byte, so `redact_url(u) != u` detects a secret.
    for clean in (
        "https://provider.example/api/notes/1",
        "https://provider.example/api?page=2&q=a%20b",
        "https://provider.example/api?flag",
        "http://provider.example:8080/api?after=2026-09-15T12%3A00%3A00Z",
    ):
        assert redact_url(clean) == clean

    assert redact_url(redacted) == redacted


class CleanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_url: str
    partition: str
    page_size: int = 100


def test_inline_secret_fields_in_a_config_model_are_refused() -> None:
    refuse_inline_secrets(CleanConfig(instance_url="https://p.example", partition="main"))

    class WithToken(BaseModel):
        api_token: str = "x"

    class WithPassword(BaseModel):
        password: str = "x"

    class WithSecret(BaseModel):
        client_secret: str = "x"

    class WithApiKey(BaseModel):
        api_key: str = "x"

    class WithCredential(BaseModel):
        credential_ref: str = "env:X"

    for model, field in (
        (WithToken, "api_token"),
        (WithPassword, "password"),
        (WithSecret, "client_secret"),
        (WithApiKey, "api_key"),
        (WithCredential, "credential_ref"),
    ):
        expected = f"Connector configuration names a secret field {field}; store a credential_ref instead"
        with pytest.raises(CredentialError) as caught:
            refuse_inline_secrets(model())
        assert str(caught.value) == expected


def test_a_credential_error_is_a_value_error() -> None:
    assert issubclass(CredentialError, ValueError)
    assert isinstance(
        ResolvedCredential(ref=CredentialRef(scheme="env", name="X"), _secret="y"), ResolvedCredential
    )
