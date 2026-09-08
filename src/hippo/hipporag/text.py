"""
Tiny text helpers used across the HippoRAG pipeline.

These mirror `hipporag/utils/misc_utils.py` in the reference implementation.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np


def clean_phrase(text: str) -> str:
    """
    Normalise an entity or fact phrase so "Radio-City" and "radio city" become the same node.

    Same rule as the reference's `text_processing`: lowercase, replace anything
    that is not a letter/digit/space with a space, collapse whitespace.
    """
    if not isinstance(text, str):
        text = str(text)
    normalized = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text.casefold())
    return " ".join(normalized.split())


def make_id(prefix: str, content: str) -> str:
    """Stable id for a node: md5 of its content, with a readable prefix (`entity-`, `fact-`, `passage-`)."""
    return prefix + hashlib.md5(content.encode("utf-8")).hexdigest()


def entity_id(name: str) -> str:
    """Id of the entity node for a (cleaned) phrase."""
    return make_id("entity-", name)


def fact_id(subject: str, predicate: str, obj: str) -> str:
    """Id of the fact node for a (cleaned) triple."""
    return make_id("fact-", f"{subject}\t{predicate}\t{obj}")


def fact_text(subject: str, predicate: str, obj: str) -> str:
    """The text we embed for a fact. (The reference embeds `str(tuple)`; a plain sentence reads better for local models.)"""
    return f"{subject} {predicate} {obj}"


_LABELS_BY_PREFIX = {
    "entity-": "Entity",
    "passage-": "Passage",
    "symbol-": "Symbol",
    "data-": "DataObject",
    "commit-": "Commit",
    "fact-": "Fact",
}


def label_of(node_id: str) -> str:
    """The node label for an id, from its `make_id` prefix alone (S2.2: never a query)."""
    if not isinstance(node_id, str):
        raise ValueError(f"node id must be a string, got {type(node_id).__name__}")
    for prefix, label in _LABELS_BY_PREFIX.items():
        if node_id.startswith(prefix):
            return label
    raise ValueError(f"unrecognised node id prefix: {node_id!r}")


_IDENTIFIER_BOUNDARY = re.compile(
    r"::"  # scope resolution (C++/Rust `pkg::Class`)
    r"|[._\-/\s]+"  # explicit separators
    r"|(?<=[^\W\d_])(?=\d)"  # letter -> digit
    r"|(?<=\d)(?=[^\W\d_])"  # digit -> letter
    r"|(?<=[a-z0-9])(?=[A-Z])"  # lower/digit -> upper (OrderService)
    r"|(?<=[A-Z])(?=[A-Z][a-z])"  # upper run -> capitalised word (HTTPServer -> HTTP, Server)
)


def split_identifier(name: str) -> list[str]:
    """Lowercase tokens of a code identifier, splitting on separators, digit/letter and camelCase boundaries."""
    return [token.lower() for token in _IDENTIFIER_BOUNDARY.split(name) if token]


def min_max_normalize(values: np.ndarray) -> np.ndarray:
    """
    Squash scores into [0, 1]. Same rule as the reference: if every value is
    identical the answer is all ones (there is nothing to separate them).
    """
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return values
    low, high = float(values.min()), float(values.max())
    if high - low == 0:
        return np.ones_like(values)
    return (values - low) / (high - low)


def is_meaningful_phrase(phrase: str) -> bool:
    """The reference only links synonyms for phrases with more than two letters/digits (skips 'a', 'us', '12')."""
    return len("".join(ch for ch in phrase if ch.isalnum())) > 2
