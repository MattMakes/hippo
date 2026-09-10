"""
The code graph: what hippo knows about a repository's *structure*, as opposed to
what it knows about its prose.

Reading a source produces `Document`s; running `extract_code` over them produces a
`CodeGraph`: symbols (modules, classes, functions, methods), data objects (the tables,
collections and graph labels the code talks to) and typed, weighted edges between them
(CONTAINS, IMPORTS, INVOKES, INHERITS, OVERRIDES, RAISES, CATCHES, TESTED_BY, READS,
WRITES). Every edge carries an omega -- how sure the resolver is -- and a provenance
naming the rule that produced it. `read_history` is the same idea over a repository's git
log: commits, and a MODIFIES edge to every symbol a commit's diff landed inside.

This package is deliberately *pure*: it imports stdlib, tree-sitter, sqlglot and
`hippo.hipporag.text`, and nothing else. No store, no LLM, no ingest. The chunker
imports `codegraph.model`; the indexer imports `CodeGraph` under TYPE_CHECKING only.
Extraction is deterministic -- the same files always give the same graph -- which is
what lets `tests/fixtures/code_sample/expected.json` be a checked-in spec.
"""

from __future__ import annotations

from .extract import extract_code
from .git_history import History, HistoryError, read_history
from .model import (
    CODE_MAX_FILE_BYTES,
    CODE_MAX_FILES,
    CODE_MAX_SYMBOLS_PER_SOURCE,
    CodeEdge,
    CodeGraph,
    DataObject,
    FileFacts,
    FileGraph,
    Symbol,
    commit_id,
    data_id,
    name_text,
    symbol_id,
    symbol_key,
)

__all__ = [
    "CODE_MAX_FILES",
    "CODE_MAX_FILE_BYTES",
    "CODE_MAX_SYMBOLS_PER_SOURCE",
    "CodeEdge",
    "CodeGraph",
    "DataObject",
    "FileFacts",
    "FileGraph",
    "History",
    "HistoryError",
    "Symbol",
    "commit_id",
    "data_id",
    "extract_code",
    "name_text",
    "read_history",
    "symbol_id",
    "symbol_key",
]
