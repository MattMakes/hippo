"""
`extract_code(docs, source_id)` -- the one entry point into this package.

Two passes over the documents one source produced: walk every parsable file into
`FileFacts`, then resolve the names in all of them together. Resolution needs the whole
source, which is why it cannot be done file by file: `invoice(order)` in `orders.py` only
means something once `billing.py` has been read.

Three properties everything downstream depends on:

* **Deterministic.** The same files always give the same graph -- same ids, same edges,
  same order -- which is what lets `tests/fixtures/code_sample/expected.json` be a
  checked-in spec rather than a snapshot.
* **Per file, and forgiving.** Each file is parsed in its own `try`/`except`. A file that
  cannot be parsed is recorded in `stats()` and simply has no symbols, so the chunker falls
  back to today's line windows for that file alone and the rest of the source is unharmed.
* **Pure.** No store, no LLM, no `ingest` import. It is handed documents and returns a
  `CodeGraph`; writing it is the indexer's job.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import resolve
from .languages import RULES
from .model import (
    CODE_MAX_FILE_BYTES,
    CODE_MAX_FILES,
    CODE_MAX_SYMBOLS_PER_SOURCE,
    CodeEdge,
    CodeGraph,
    DataObject,
    FileFacts,
    lang_of,
    merge_edges,
)
from .treesitter import grammar_for, new_parser

# Every registered language that has a walker. A language may be registered without one --
# for its suffix, grammar and comment style -- and its files are then skipped as
# `unsupported`, keeping today's line windows and OpenIE.
WALKERS = {name: rules.walk for name, rules in RULES.items() if rules.walk is not None}


def extract_code(
    docs,
    source_id: str,
    *,
    should_stop: Callable[[], bool] | None = None,
    node_namespace: str | None = None,
) -> CodeGraph:
    """
    The code graph of one source. `docs` is what `ingest.readers.read_source` produced; only
    `title` (the repo-relative path), `text` and `is_code` are read, so this never imports
    `ingest`.

    `should_stop` is checked between files, so cancelling a large repo does not have to wait
    for the whole tree (2.2c). A cancelled or over-budget run returns what it had, with
    `stats()["truncated"]` set.

    `node_namespace` changes native IDs while every node keeps the logical `source_id`.
    Omit it for legacy IDs; managed callers supply their generation's namespace.
    """
    graph = CodeGraph(source_id=source_id, node_namespace=node_namespace)
    parsers: dict[str, object] = {}
    files: list[FileFacts] = []
    sql: list[tuple[str, str]] = []
    docs = list(docs)  # `source_setup` reads them again after the walk; a generator would be spent

    for doc in docs:
        if should_stop is not None and should_stop():
            graph.truncated = True
            break
        path = getattr(doc, "title", "") or getattr(doc, "path", "")
        text = getattr(doc, "text", "") or ""
        lang = lang_of(path)
        rules = RULES.get(lang or "")
        # No language, or a language registered without a walker yet: either way this file
        # is `unsupported` -- the chunker keeps its line windows and OpenIE reads it whole.
        # Checked before the size cap so an over-sized file of an unwalked language is
        # counted exactly as it is today.
        if lang is None or (lang != "sql" and (rules is None or rules.walk is None)):
            if getattr(doc, "is_code", False):
                graph.files_skipped[path] = "unsupported"
            continue
        if len(text.encode("utf-8", errors="replace")) > CODE_MAX_FILE_BYTES:
            graph.files_skipped[path] = "too_big"
            continue
        if lang == "sql":
            sql.append((path, text))
            graph.files_parsed.append(path)
            continue
        if len(files) >= CODE_MAX_FILES:
            graph.truncated = True
            break
        facts = _walk(path, text, lang, source_id, parsers, node_namespace=node_namespace)
        if facts is None:
            graph.files_skipped[path] = "parse_error"
            continue
        files.append(facts)
        graph.files_parsed.append(path)
        if sum(len(f.symbols) for f in files) >= CODE_MAX_SYMBOLS_PER_SOURCE:
            graph.truncated = True
            break

    _resolve(graph, files, sql, source_id, _source_state(docs, files))
    return graph


def _source_state(docs: list, files: list[FileFacts]) -> dict[str, Any]:
    """
    What each language needs to know about the source as a whole, once: Go's `go.mod` module
    path, Rust's crate root. Run after the walk, over the raw documents -- `go.mod` is not a
    file any walker parses -- and only for a language that actually produced files, so a
    source with no Go in it pays nothing.
    """
    state: dict[str, Any] = {}
    for lang in sorted({facts.lang for facts in files}):
        setup = RULES[lang].source_setup
        if setup is not None:
            state[lang] = setup(docs)
    return state


def _walk(
    path: str, text: str, lang: str, source_id: str, parsers: dict, *, node_namespace: str | None = None
) -> FileFacts | None:
    """
    One file, in its own `try`. A parser is built once per grammar per call (not thread-safe).

    tree-sitter parses tolerantly and never raises, so "parse error" means the useful thing:
    the file has syntax the grammar could not read *and* nothing came out of it but the
    module itself. A file with a stray error node and twenty good symbols is still worth
    chunking by symbol; a file that yielded nothing is better off as line windows.
    """
    try:
        grammar = grammar_for(path, lang)
        parser = parsers.get(grammar)
        if parser is None:
            parser = parsers[grammar] = new_parser(grammar)
        tree = parser.parse(text.encode("utf-8", errors="replace"))
        if node_namespace is None:
            facts = WALKERS[lang](path, tree.root_node, source_id)
        else:
            facts = WALKERS[lang](path, tree.root_node, source_id, node_namespace=node_namespace)
        if tree.root_node.has_error and len(facts.symbols) <= 1:
            return None
        return facts
    except Exception:  # noqa: BLE001 - one unparsable file must not sink the source
        return None


def _resolve(
    graph: CodeGraph,
    files: list[FileFacts],
    sql: list[tuple[str, str]],
    source_id: str,
    lang_state: dict[str, Any] | None = None,
) -> None:
    """Pass 2: everything that needs the whole source at once."""
    index = resolve.build_index(files, lang_state)
    edges: list[CodeEdge] = []
    edges.extend(resolve.resolve_imports(index))
    edges.extend(resolve.resolve_bases(index))
    edges.extend(resolve.resolve_overrides(index))

    objects: list[DataObject] = []
    invokes: list[CodeEdge] = []
    for facts in files:
        graph.symbols.extend(facts.symbols)
        edges.extend(_contains(index, facts))
        calls, hits, unresolved = resolve.resolve_calls(index, facts)
        invokes.extend(calls)
        edges.extend(resolve.resolve_raises(index, facts))
        found, data_edges = resolve.resolve_data(index, facts, hits)
        objects.extend(found)
        edges.extend(data_edges)
        if unresolved:
            graph.unresolved_calls[facts.path] = unresolved
    edges.extend(invokes)
    edges.extend(resolve.resolve_tested_by(index, invokes))

    for path, text in sql:
        found, sql_edges = resolve.sql_file_objects(
            source_id, path, text, node_namespace=graph.node_namespace
        )
        objects.extend(found)
        edges.extend(sql_edges)

    graph.data_objects.extend(_dedupe(objects))
    graph.edges.extend(sorted(merge_edges(edges), key=lambda e: (e.kind, e.a, e.b)))


def _contains(index: resolve.SourceIndex, facts: FileFacts) -> list[CodeEdge]:
    """
    CONTAINS, straight from the syntax: module -> class/function, class -> member.

    The owner is looked up the way `resolve.declared` looks one up, so a method written in a
    Rust `impl` block far from its `struct` still hangs off the type rather than off nothing.
    """
    edges: list[CodeEdge] = []
    module = facts.symbols[0]
    for symbol in facts.symbols[1:]:
        owner, _, _ = symbol.qualname.rpartition(".")
        parent = resolve.declared(index, facts, owner) if owner else module
        if parent is not None:
            edges.append(CodeEdge(a=parent.id, b=symbol.id, kind="CONTAINS", omega=1.00, provenance="syntax"))
    return edges


def _dedupe(objects: list[DataObject]) -> list[DataObject]:
    """
    One node per `(kind, qualname)`, however many files name it -- the DDL, the SQL literal
    and the `__tablename__` are one table. Every mention site is kept: S2.5 gives a data
    object a DEFINED_IN edge from every passage that names it, not just the first.
    """
    merged: dict[str, DataObject] = {}
    for target in objects:
        seen = merged.get(target.id)
        if seen is None:
            merged[target.id] = target
            continue
        seen.mentions.extend(target.mentions)
        if not seen.dialect:
            seen.dialect = target.dialect
    for target in merged.values():
        target.mentions = sorted(set(target.mentions))
    return sorted(merged.values(), key=lambda o: (o.kind, o.qualname))
