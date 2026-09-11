"""Version-one knowledge identities. Legacy code/HippoRAG IDs are deliberately untouched.

Canonical keys are UTF-8 JSON arrays, with ordered arrays and sorted object keys.
Paths use portable POSIX relative spelling; backslashes/drive paths are rejected even
on POSIX so an export has the same meaning on another machine. SQL Server collation
is recorded, never approximated with Python's Unicode casefold.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlsplit, urlunsplit


def _json_value(value: object) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Nonfinite numbers are not canonical JSON")
        return
    if type(value) in (tuple, list):
        for item in value:
            _json_value(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("Canonical JSON object keys must be strings")
            _json_value(item)
        return
    raise ValueError("Value is not a canonical JSON value")


def canonical_json(value: object) -> str:
    _json_value(value)
    result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    # Reject lone surrogates before they can become an unhashable stored key.
    result.encode("utf-8")
    return result


def normalize_json(value: str) -> str:
    if type(value) is not str:
        raise ValueError("JSON payload must be a serialized string")

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = item
        return result

    return canonical_json(json.loads(value, object_pairs_hook=pairs))


def make_identity(prefix: str, parts: list | tuple) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", prefix):
        raise ValueError("Identity prefix must be a lowercase readable namespace")
    if type(parts) not in (list, tuple):
        raise ValueError("Identity input must be a JSON array")
    return f"{prefix}-{hashlib.sha256(canonical_json(parts).encode('utf-8')).hexdigest()}"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_provider_url(value: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError("Provider URL contains whitespace/control characters")
    if "\\" in value or "?" in value or "#" in value:
        raise ValueError("Provider URL cannot contain query, fragment or backslashes")
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise ValueError("Provider URL has malformed percent encoding")
    parsed = urlsplit(value)
    # Reject before parsed.hostname lowercases Unicode such as Kelvin sign.
    if not parsed.netloc.isascii():
        raise ValueError("Provider host must use ASCII or explicit punycode")
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Provider URL must be an HTTP(S) instance without credentials")
    port = parsed.port  # validates malformed and out-of-range ports
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    else:
        # Python's built-in IDNA codec folds some distinct modern hostnames
        # (for example ß -> ss). Require the caller's explicit ASCII/punycode
        # hostname rather than inventing a transport-incompatible equivalence.
        if not host.isascii():
            raise ValueError("Provider host must use ASCII or explicit punycode")
    scheme = parsed.scheme.lower()
    if port is not None and (scheme, port) not in {("https", 443), ("http", 80)}:
        host = f"{host}:{port}"
    decoded = unquote(parsed.path)
    if any(part in {".", ".."} for part in decoded.split("/")) or "\\" in decoded or "//" in decoded:
        raise ValueError("Provider base path must be unambiguous")
    if any(ord(c) < 32 or ord(c) == 127 for c in decoded):
        raise ValueError("Provider base path contains control characters")
    return urlunsplit((scheme, host, parsed.path.rstrip("/"), "", ""))


def normalize_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("Path must use portable relative POSIX spelling")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or ".." in path.parts or path == PurePosixPath("."):
        raise ValueError("Path must stay below its source root")
    return path.as_posix()


def source_relative_path(root: Path | str, value: str) -> str:
    relative = normalize_relative_path(value)
    source_root = Path(root).resolve(strict=True)
    if not source_root.is_dir():
        raise ValueError("Source root must be a directory")
    resolved = (source_root / relative).resolve(strict=False)
    if not resolved.is_relative_to(source_root):
        raise ValueError("Source path escapes through a symlink")
    # Preserve the logical path, not a symlink target's name. Ingestion must open
    # safely/check again when reading; validation is not a race-proof file handle.
    return relative


def artifact_identity(workspace: str, connector_instance: str, kind: str, provider_id: str) -> str:
    return make_identity(
        "artifact", [workspace, normalize_provider_url(connector_instance), kind, provider_id]
    )


def local_artifact_identity(
    workspace: str, source: str, root: Path | str, path: str, kind: str = "file"
) -> str:
    return make_identity("artifact", [workspace, source, kind, source_relative_path(root, path)])


def knowledge_object_identity(workspace: str, kind: str, key: list | tuple) -> str:
    """The same key wrapper used by KnowledgeObject; raw spelling is metadata."""
    return make_identity("object", [workspace, kind, key])


def repository_key(provider_instance: str, provider_repository_id: str) -> list:
    return [normalize_provider_url(provider_instance), provider_repository_id]


def repository_identity(workspace: str, provider_instance: str, provider_repository_id: str) -> str:
    return knowledge_object_identity(
        workspace, "repository", repository_key(provider_instance, provider_repository_id)
    )


def review_key(provider_instance: str, repository_id: str, review_id: str) -> list:
    return [normalize_provider_url(provider_instance), repository_id, review_id]


def review_identity(workspace: str, provider_instance: str, repository_id: str, review_id: str) -> str:
    return knowledge_object_identity(
        workspace, "review", review_key(provider_instance, repository_id, review_id)
    )


def catalog_reference(
    value: str, *, default_kind: str = "Component", default_namespace: str = "default"
) -> str:
    kind, rest = value.split(":", 1) if ":" in value else (default_kind, value)
    namespace, name = rest.split("/", 1) if "/" in rest else (default_namespace, rest)
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in (kind, namespace, name)):
        raise ValueError("Invalid catalog entity reference")
    return f"{kind.lower()}:{namespace.lower()}/{name.lower()}"


def service_key(catalog_instance: str, reference: str) -> list:
    return [normalize_provider_url(catalog_instance), catalog_reference(reference)]


def service_identity(workspace: str, catalog_instance: str, reference: str) -> str:
    return knowledge_object_identity(workspace, "service", service_key(catalog_instance, reference))


@dataclass(frozen=True)
class SqlIdentifier:
    original: str
    lookup: str
    quoted: bool
    dialect: str
    collation: str | None


def sql_identifier(
    value: str, *, dialect: str, quoted: bool = False, collation: str | None = None
) -> SqlIdentifier:
    if dialect not in {"postgres", "tsql"} or type(quoted) is not bool or not value or "\x00" in value:
        raise ValueError("Explicit supported dialect and valid identifier required")
    # PostgreSQL folds only unquoted ASCII upper-case identifiers. Preserve original
    # spelling/quoting independently from lookup. Deployment collation is metadata.
    lookup = (
        value.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))
        if dialect == "postgres" and not quoted
        else value
    )
    return SqlIdentifier(value, lookup, quoted, dialect, collation)


def database_object_key(
    instance: str,
    environment: str,
    catalog: str | SqlIdentifier,
    schema: str | SqlIdentifier,
    parts: list[SqlIdentifier] | tuple[SqlIdentifier, ...],
) -> list:
    if not parts or not all(isinstance(part, SqlIdentifier) for part in parts):
        raise ValueError("Database identity requires dialect-aware identifier parts")
    if len({part.dialect for part in parts}) != 1:
        raise ValueError("Database identifier parts must share a dialect")

    def semantic(part):
        if isinstance(part, str):
            part = sql_identifier(part, dialect=parts[0].dialect, collation=parts[0].collation)
        if part.dialect != parts[0].dialect:
            raise ValueError("Database qualifiers must share the object dialect")
        return [part.lookup, part.dialect, part.collation]

    return [instance, environment, semantic(catalog), semantic(schema), [semantic(part) for part in parts]]


def database_object_identity(
    workspace: str,
    instance: str,
    environment: str,
    catalog: str | SqlIdentifier,
    schema: str | SqlIdentifier,
    parts: list[SqlIdentifier] | tuple[SqlIdentifier, ...],
    kind: str,
) -> str:
    return knowledge_object_identity(
        workspace, kind, database_object_key(instance, environment, catalog, schema, parts)
    )


def revision_identity(artifact_id: str, provider_revision: str | None, content_hash: str) -> str:
    return make_identity("revision", [artifact_id, provider_revision, content_hash])


def span_identity(revision_id: str, locator: dict, exact_text_hash: str) -> str:
    # Imported lazily: the typed locator contract itself uses basic identity
    # helpers while its module is being defined.
    from .model import canonical_locator_json

    canonical_locator = json.loads(canonical_locator_json(canonical_json(locator)))
    return make_identity("span", [revision_id, canonical_locator, exact_text_hash])


def symbol_key(
    repository: str,
    language: str,
    path: str,
    qualified_name: str,
    signature: str | None = None,
    *,
    kind: str = "symbol",
) -> list:
    return [repository, language, normalize_relative_path(path), qualified_name, kind, signature]


def symbol_identity(
    repository: str,
    language: str,
    path: str,
    qualified_name: str,
    signature: str | None = None,
    *,
    kind: str = "symbol",
    workspace: str = "default",
) -> str:
    return knowledge_object_identity(
        workspace, "symbol", symbol_key(repository, language, path, qualified_name, signature, kind=kind)
    )


def endpoint_key(
    service: str,
    protocol: str,
    api_version: str,
    method: str,
    path_template: str,
    *,
    api_identity: str = "default",
) -> list:
    if not method.isascii() or not method.isalpha() or not path_template.startswith("/"):
        raise ValueError("Endpoint requires an HTTP method and exact absolute contract path")
    return [service, protocol.lower(), api_identity, api_version, method.upper(), path_template]


def endpoint_identity(
    service: str,
    protocol: str,
    api_version: str,
    method: str,
    path_template: str,
    *,
    api_identity: str = "default",
    workspace: str = "default",
) -> str:
    return knowledge_object_identity(
        workspace,
        "endpoint",
        endpoint_key(service, protocol, api_version, method, path_template, api_identity=api_identity),
    )
