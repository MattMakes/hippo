"""Disposable, source-independent syntax facts; never a cache of resolved graphs.

Bump WALKER_RULES_VERSION when walker semantics change, and SCHEMA_VERSION when
serialized facts change. Parser distributions are fingerprinted from installed metadata.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import types
from dataclasses import asdict, dataclass, fields, is_dataclass
from importlib import metadata
from pathlib import Path
from typing import Union, get_args, get_origin, get_type_hints

from .model import FileFacts, Symbol, symbol_id, validate_node_namespace
from .treesitter import grammar_for

SCHEMA_VERSION = 1
WALKER_RULES_VERSION = "1"
MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_PATH_BYTES = 4096
_DISTRIBUTIONS = {
    "python": "tree-sitter-python",
    "typescript": "tree-sitter-typescript",
    "tsx": "tree-sitter-typescript",
    "go": "tree-sitter-go",
    "csharp": "tree-sitter-c-sharp",
    "rust": "tree-sitter-rust",
}


def _json(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parser_profile(grammar: str) -> tuple[tuple[str, str], ...] | None:
    """Unknown/unavailable distribution metadata disables reuse for this grammar."""
    distribution = _DISTRIBUTIONS.get(grammar)
    if distribution is None:
        return None
    try:
        profile = tuple((name, metadata.version(name)) for name in ("tree-sitter", distribution))
    except (metadata.PackageNotFoundError, ValueError, OSError):
        return None
    return profile if all(isinstance(version, str) and version.strip() for _, version in profile) else None


@dataclass(frozen=True)
class SyntaxCacheKey:
    schema_version: int
    path: str
    lang: str
    grammar: str
    input_hash: str
    parser_profile: tuple[tuple[str, str], ...]
    walker_rules_version: str

    @property
    def digest(self) -> str:
        return _hash(_json(asdict(self)))


def cache_key(path: str, text: str, lang: str) -> SyntaxCacheKey | None:
    """Hash exactly the UTF-8 replacement encoding fed to tree-sitter."""
    if not path or len(path.encode("utf-8", errors="replace")) > MAX_PATH_BYTES or "\0" in path:
        return None
    grammar = grammar_for(path, lang)
    profile = parser_profile(grammar)
    if profile is None:
        return None
    return SyntaxCacheKey(
        SCHEMA_VERSION,
        path,
        lang,
        grammar,
        _hash(text.encode("utf-8", errors="replace")),
        profile,
        WALKER_RULES_VERSION,
    )


def _decode(value, annotation):
    """Strictly reconstruct every typed field; no coercion, unknown fields or defaults.

    The dataclass annotations are the schema, including nested collections. A model
    change therefore rejects old entries until rewritten (and should bump the version).
    """
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        for candidate in args:
            try:
                return _decode(value, candidate)
            except ValueError:
                pass
        raise ValueError("invalid union field")
    if is_dataclass(annotation):
        omitted = (
            {"id", "source_id"}
            if annotation is Symbol
            else {"node_namespace"}
            if annotation is FileFacts
            else set()
        )
        expected = {f.name for f in fields(annotation)} - omitted
        if type(value) is not dict or set(value) != expected:
            raise ValueError("invalid dataclass fields")
        hints = get_type_hints(annotation)
        return annotation(**{name: _decode(item, hints[name]) for name, item in value.items()})
    if origin in (list, tuple):
        if type(value) is not list:
            raise ValueError("invalid sequence")
        if origin is list:
            return [_decode(item, args[0]) for item in value]
        if len(value) != len(args):
            raise ValueError("invalid tuple length")
        return tuple(_decode(item, kind) for item, kind in zip(value, args, strict=True))
    if origin is dict:
        if type(value) is not dict:
            raise ValueError("invalid mapping")
        return {_decode(k, args[0]): _decode(v, args[1]) for k, v in value.items()}
    if type(value) is not annotation:
        raise ValueError("invalid scalar")
    return value


def _payload(facts: FileFacts) -> dict:
    payload = asdict(facts)
    del payload["node_namespace"]
    for symbol in payload["symbols"]:
        del symbol["id"]
        del symbol["source_id"]
    return payload


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class SyntaxCache:
    """Bounded JSON entries at a caller-selected root, with atomic replacement.

    Cache I/O or validation failure is always a miss. Instances retain no mutable facts.
    The caller should use its data directory's cache/syntax/v1 directory.
    """

    def __init__(self, root: str | Path, *, max_entry_bytes: int = MAX_ENTRY_BYTES):
        if type(max_entry_bytes) is not int or not 0 < max_entry_bytes <= MAX_ENTRY_BYTES:
            raise ValueError("invalid syntax cache entry limit")
        self.root = Path(root)
        self.max_entry_bytes = max_entry_bytes

    def get(
        self, key: SyntaxCacheKey, source_id: str, *, node_namespace: str | None = None
    ) -> FileFacts | None:
        validate_node_namespace(node_namespace)
        try:
            with (self.root / f"{key.digest}.json").open("rb") as stream:
                raw = stream.read(self.max_entry_bytes + 1)
            if len(raw) > self.max_entry_bytes:
                return None
            envelope = json.loads(raw, object_pairs_hook=_unique_object)
            if type(envelope) is not dict or set(envelope) != {"key", "payload", "payload_hash"}:
                return None
            expected_key = json.loads(_json(asdict(key)))
            if _json(envelope["key"]) != _json(expected_key) or key.schema_version != SCHEMA_VERSION:
                return None
            payload = envelope["payload"]
            if type(envelope["payload_hash"]) is not str or envelope["payload_hash"] != _hash(_json(payload)):
                return None
            facts = _decode(payload, FileFacts)
            if facts.path != key.path or facts.lang != key.lang or not facts.symbols:
                return None
            if any(s.path != key.path or s.lang != key.lang for s in facts.symbols):
                return None
            facts.node_namespace = node_namespace
            for symbol in facts.symbols:
                symbol.source_id = source_id
                symbol.id = symbol_id(
                    source_id, symbol.path, symbol.qualname, symbol.kind, node_namespace=node_namespace
                )
            return facts
        except (OSError, ValueError, TypeError, RecursionError, OverflowError):
            return None

    def put(self, key: SyntaxCacheKey, facts: FileFacts) -> None:
        temporary = None
        try:
            payload = _payload(facts)
            raw = _json({"key": asdict(key), "payload": payload, "payload_hash": _hash(_json(payload))})
            if len(raw) > self.max_entry_bytes:
                return
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.root, prefix=".syntax-", suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
            os.replace(temporary, self.root / f"{key.digest}.json")
        except (OSError, ValueError, TypeError, RecursionError, OverflowError):
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
