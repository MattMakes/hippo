"""Mapped code chunks: the legacy chunker's passages with exact original closures.

Every passage the committed `chunk_documents(..., code=code)` produces for a code
tree must come back byte-identical, carrying the file line ranges it was cut from
and an explicit mark on every character no original supplied.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from random import Random

import pytest

from hippo.codegraph.extract import extract_code
from hippo.codegraph.model import CodeGraph
from hippo.ingest import chunker
from hippo.ingest.chunker import chunk_documents
from hippo.ingest.code_provenance import read_code_provenance
from hippo.ingest.provenance import GeneratedSegment, OriginalSegment
from hippo.knowledge.inputs import RawInput

SOURCE = "source-cc5"


@pytest.fixture
def api():
    return import_module("hippo.ingest.prepared_code_chunks")


# ------------------------------------------------------------------ helpers


def raw(data: bytes, path: str):
    digest = sha256(data).hexdigest()
    return RawInput(
        input_key="raw-input:" + path,
        logical_path=path,
        media_type="text/plain",
        raw_uri="hippo-raw:sha256:" + digest,
        raw_hash=digest,
        byte_length=len(data),
    )


def captured(data: bytes, path: str):
    from hippo.ingest.prepared_code_chunks import CapturedCode

    accepted = raw(data, path)
    return CapturedCode(accepted, read_code_provenance(accepted, data, name=path))


def provenance(text: str, path: str = "src/orders.py", *, newline: str = "\n", bom: bool = False):
    body = text.replace("\n", newline) if newline != "\n" else text
    return captured((b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8"), path)


def graph_of(units, source_id: str = SOURCE) -> CodeGraph:
    return extract_code([unit.to_document() for unit in units], source_id)


def units_of(results):
    return [item.unit for item in results if item.unit is not None]


def prepare(api, results, *, size=1500, overlap=150, facts=None, max_chunks=20_000):
    settings = api.CodeChunkSettings(size_chars=size, overlap_chars=overlap)
    code = graph_of(units_of(results)) if facts is None else facts
    return api.prepare_code_chunks(results, facts=code, settings=settings, max_chunks=max_chunks), code


def legacy(results, code, *, size=1500, overlap=150):
    return chunk_documents([unit.to_document() for unit in units_of(results)], size, overlap, code=code)


def render(chunk) -> str:
    units = {unit.unit_key: unit for unit in chunk.original_units}
    return "".join(
        units[s.unit_key].text[s.start : s.end] if type(s) is OriginalSegment else s.text
        for s in chunk.retrieval_segments
    )


ORDERS = """\
\"\"\"Order handling.\"\"\"

import os


class OrderService:
    \"\"\"Places orders, and keeps a long enough docstring to be worth extracting here.\"\"\"

    def place(self, order):
        total = order.total
        return total

    def save(self, order):
        return os.stat(order.path)


def helper(value):
    return value + 1
"""

CONFIG = '{\n  "name": "acme",\n  "version": "1.0.0"\n}\n'

SCHEMA = "CREATE TABLE orders (\n  id INT\n);\n\nSELECT id FROM orders;\n"

READ_ME = "Acme\n\nA paragraph about the project.\n\nAnother paragraph about it.\n"


# --------------------------------------------------------------------- api


def test_the_mapped_code_preparation_module_exists():
    from importlib.util import find_spec

    assert find_spec("hippo.ingest.prepared_code_chunks") is not None, "mapped code preparation is missing"


def test_the_rule_version_is_frozen_and_travels_with_every_result(api):
    assert api.CODE_CHUNK_RULE_VERSION == "code-chunks-v1"
    prepared, _ = prepare(api, [provenance(ORDERS)])
    assert prepared.rule_version == api.CODE_CHUNK_RULE_VERSION
    assert all(chunk.rule_version == api.CODE_CHUNK_RULE_VERSION for chunk in prepared.chunks)
    with pytest.raises(FrozenInstanceError):
        prepared.rule_version = "code-chunks-v2"


def test_the_chunk_kinds_and_refusal_reasons_are_closed_sets(api):
    assert api.CODE_CHUNK_KINDS == ("header", "symbol", "data_object", "window", "prose", "commit")
    assert api.CODE_REFUSAL_REASONS == ("binary", "empty")
    assert api.CODE_PLACEHOLDER_RULE == "code-placeholder-v1"
    assert api.CODE_LINE_JOIN_RULE == "code-line-join-v1"
    assert api.CODE_COMMIT_RULE == "code-commit-v1"


def test_the_module_holds_no_store_model_or_clock(api):
    text = Path(api.__file__).read_text(encoding="utf-8")
    for forbidden in ("datetime", "time.time", "import time", "Ollama", "ctx.store", "AppContext"):
        assert forbidden not in text, f"pure preparation must not reach for {forbidden}"


# ------------------------------------------------------------------ parity


def test_symbol_and_header_passages_match_the_committed_chunker(api):
    results = [provenance(ORDERS)]
    prepared, code = prepare(api, results)
    assert [chunk.to_chunk() for chunk in prepared.chunks] == legacy(results, code)
    kinds = [chunk.kind for chunk in prepared.chunks]
    assert kinds[0] == "header" and "symbol" in kinds
    assert all(chunk.logical_path == "src/orders.py" for chunk in prepared.chunks)


def test_every_chunk_reconstructs_from_its_own_segments(api):
    results = [provenance(ORDERS), provenance(SCHEMA, "db/schema.sql"), provenance(CONFIG, "package.json")]
    prepared, _ = prepare(api, results)
    assert prepared.chunks
    for chunk in prepared.chunks:
        assert render(chunk) == chunk.text


def test_a_pure_line_feed_body_is_one_original_region_with_nothing_generated(api):
    results = [provenance(ORDERS)]
    prepared, _ = prepare(api, results)
    body = next(c for c in prepared.chunks if c.kind == "symbol" and "helper" in c.title)
    assert all(type(segment) is OriginalSegment for segment in body.retrieval_segments)
    assert len(body.originals) == 1
    # The closure is complete source lines, so it keeps the newline the passage dropped.
    assert body.originals[0].lines.text == body.text + "\n"


def test_a_passage_that_is_exactly_its_source_lines_needs_no_view(api):
    text = "def helper(value):\n    return value + 1"  # no trailing newline
    prepared, _ = prepare(api, [provenance(text, "src/tiny.py")])
    (chunk,) = prepared.chunks
    assert chunk.text == text and chunk.requires_view is False
    assert chunk.originals[0].lines.text == text
    assert all(type(segment) is OriginalSegment for segment in chunk.retrieval_segments)


def test_a_carriage_return_file_marks_each_line_join_as_generated(api):
    results = [provenance(ORDERS, newline="\r\n")]
    prepared, _ = prepare(api, results)
    body = next(c for c in prepared.chunks if c.kind == "symbol" and "helper" in c.title)
    joins = [s for s in body.retrieval_segments if type(s) is GeneratedSegment]
    assert joins and all(s.rule_id == api.CODE_LINE_JOIN_RULE and s.text == "\n" for s in joins)
    assert body.requires_view is True
    assert render(body) == body.text


def test_a_header_places_one_generated_placeholder_per_member(api):
    results = [provenance(ORDERS)]
    prepared, _ = prepare(api, results)
    header = next(c for c in prepared.chunks if c.kind == "header" and "OrderService" in c.title)
    placeholders = [s for s in header.retrieval_segments if type(s) is GeneratedSegment and "..." in s.text]
    assert placeholders and all(s.rule_id == api.CODE_PLACEHOLDER_RULE for s in placeholders)
    assert len(header.placeholders) == len(placeholders)


def test_every_placeholder_depends_on_lines_inside_the_member_it_stands_for(api):
    results = [provenance(ORDERS)]
    prepared, code = prepare(api, results)
    by_id = {symbol.id: symbol for symbol in code.symbols}
    unit = units_of(results)[0]
    seen = 0
    for chunk in prepared.chunks:
        for symbol_id, dependency in chunk.placeholders:
            member = by_id[symbol_id]
            lines = unit.original.complete_lines(dependency.start, dependency.end).locator
            offset = unit.analysis_offset
            first = unit.original.text.count("\n", 0, offset)  # whole lines the trim removed
            assert member.line_start + first <= lines.start <= member.line_end + first
            seen += 1
    assert seen, "the fixture must exercise placeholders"


def test_leading_blank_lines_move_the_locators_to_the_real_file_lines(api):
    shifted = "\n\n\n" + ORDERS
    plain, _ = prepare(api, [provenance(ORDERS)])
    moved, _ = prepare(api, [provenance(shifted)])
    assert [c.text for c in moved.chunks] == [c.text for c in plain.chunks]
    first_plain = plain.chunks[0].originals[0].lines.locator
    first_moved = moved.chunks[0].originals[0].lines.locator
    assert first_moved.start == first_plain.start + 3


def test_a_sql_file_keeps_line_windows_and_names_the_objects_they_declare(api):
    results = [provenance(SCHEMA, "db/schema.sql")]
    prepared, code = prepare(api, results)
    assert [chunk.to_chunk() for chunk in prepared.chunks] == legacy(results, code)
    assert {chunk.kind for chunk in prepared.chunks} == {"data_object"}
    (window,) = prepared.chunks
    assert window.data_object_ids and set(window.data_object_ids) <= set(window.defines)
    assert window.extract_text == ""


def test_a_tree_with_no_code_graph_at_all_keeps_line_windows(api):
    results = [provenance(CONFIG, "package.json"), provenance(ORDERS)]
    settings = api.CodeChunkSettings(size_chars=200, overlap_chars=0)
    prepared = api.prepare_code_chunks(results, facts=None, settings=settings, max_chunks=20_000)
    assert prepared.to_chunks() == legacy(results, None, size=200, overlap=0)
    assert {chunk.kind for chunk in prepared.chunks} == {"window"}
    assert all(not chunk.defines and chunk.symbol_id is None for chunk in prepared.chunks)


def test_an_unparsed_config_file_keeps_todays_line_windows(api):
    results = [provenance(CONFIG, "package.json")]
    prepared, code = prepare(api, results)
    assert [chunk.to_chunk() for chunk in prepared.chunks] == legacy(results, code)
    assert {chunk.kind for chunk in prepared.chunks} == {"window"}
    assert all(chunk.symbol_id is None for chunk in prepared.chunks)


def test_an_extensionless_text_file_goes_through_the_reviewed_prose_lane(api):
    results = [provenance(READ_ME, "README")]
    prepared, code = prepare(api, results, size=60, overlap=0)
    assert [chunk.to_chunk() for chunk in prepared.chunks] == legacy(results, code, size=60, overlap=0)
    assert {chunk.kind for chunk in prepared.chunks} == {"prose"}
    assert all(chunk.chunker_profile[0] == "plain-prose-v1" for chunk in prepared.chunks)
    for chunk in prepared.chunks:
        assert render(chunk) == chunk.text


# ----------------------------------------------------------------- commits


def history(code: CodeGraph, count: int = 2) -> CodeGraph:
    place = next((s for s in code.symbols if s.qualname.endswith("place")), code.symbols[0])
    code.commits = [
        {
            "id": f"commit-{i}",
            "source_id": SOURCE,
            "sha": f"{i}" * 40,
            "author": "Hippo Fixture",
            "date": f"2024-01-0{i + 1}T09:00:00+00:00",
            "message": f"Subject {i}\n\nA body paragraph for commit {i}.",
            "ordinal": i,
        }
        for i in range(count)
    ]
    code.modifies = [{"commit_id": "commit-0", "symbol_id": place.id, "omega": 1.0, "hunk": {}}]
    return code


def test_a_commit_passage_is_generated_from_its_commit_record_alone(api):
    results = [provenance(ORDERS)]
    code = history(graph_of(units_of(results)))
    prepared, _ = prepare(api, results, facts=code)
    assert [chunk.to_chunk() for chunk in prepared.chunks] == legacy(results, code)
    commits = [chunk for chunk in prepared.chunks if chunk.kind == "commit"]
    assert [chunk.commit_id for chunk in commits] == ["commit-0", "commit-1"]
    first = commits[0]
    assert first.original_units == () and first.originals == () and first.logical_path is None
    (segment,) = first.retrieval_segments
    assert type(segment) is api.CommitSegment
    assert segment.rule_id == api.CODE_COMMIT_RULE and segment.text == first.text
    assert first.commit_sha == "0" * 40 and first.requires_view is True


def test_a_commit_with_no_message_and_nothing_touched_is_an_empty_passage(api):
    results = [provenance(ORDERS)]
    code = history(graph_of(units_of(results)), count=1)
    code.commits[0]["message"] = ""
    code.modifies = []
    prepared, _ = prepare(api, results, facts=code)
    assert [chunk.to_chunk() for chunk in prepared.chunks] == legacy(results, code)
    (commit,) = [chunk for chunk in prepared.chunks if chunk.kind == "commit"]
    assert commit.title == "commit 0000000000: 0000000000" and commit.text == ""
    assert commit.retrieval_segments == () and commit.segment_dependencies == ()
    assert render(commit) == "" and commit.requires_view is True


def test_commit_passages_come_last_and_keep_the_ordinal_run(api):
    results = [provenance(ORDERS), provenance(CONFIG, "package.json")]
    code = history(graph_of(units_of(results)))
    prepared, _ = prepare(api, results, facts=code)
    assert [chunk.ordinal for chunk in prepared.chunks] == list(range(len(prepared.chunks)))
    assert [chunk.kind for chunk in prepared.chunks][-2:] == ["commit", "commit"]


def test_a_commit_that_touched_many_symbols_says_what_was_cut(api):
    results = [provenance(ORDERS)]
    code = history(graph_of(units_of(results)))
    code.modifies = [
        {"commit_id": "commit-0", "symbol_id": s.id, "omega": 1.0, "hunk": {}} for s in code.symbols
    ]
    prepared, _ = prepare(api, results, facts=code, size=80, overlap=0)
    assert [c.to_chunk() for c in prepared.chunks] == legacy(results, code, size=80, overlap=0)
    commit = next(c for c in prepared.chunks if c.kind == "commit" and c.commit_id == "commit-0")
    assert len(commit.text) <= 80 and commit.text.rstrip().endswith("more)")
    (segment,) = commit.retrieval_segments
    assert segment.text == commit.text and commit.originals == ()


# ---------------------------------------------------------------- refusals


def test_a_binary_or_empty_input_produces_no_chunk_and_an_explicit_reason(api):
    binary = captured(b"\x00\x01\x02binary", "vendor/a.py")
    blank = provenance("   \n  \n", "src/blank.py")
    prepared, _ = prepare(api, [binary, blank, provenance(ORDERS)])
    assert {(r.logical_path, r.reason) for r in prepared.refusals} == {
        ("vendor/a.py", "binary"),
        ("src/blank.py", "empty"),
    }
    assert all(r.reason in api.CODE_REFUSAL_REASONS for r in prepared.refusals)
    assert all(chunk.logical_path == "src/orders.py" for chunk in prepared.chunks)


def test_a_refused_input_keeps_its_accepted_input_key(api):
    blank = provenance("", "src/blank.py")
    prepared, _ = prepare(api, [blank])
    (refusal,) = prepared.refusals
    assert refusal.input_key == "raw-input:src/blank.py" and refusal.reason == "empty"
    assert prepared.chunks == ()


def test_passing_the_chunk_ceiling_refuses_rather_than_truncating(api):
    results = [provenance(ORDERS)]
    with pytest.raises(api.TooManyCodeChunks) as error:
        prepare(api, results, max_chunks=2)
    assert "src/orders.py" not in str(error.value) and "OrderService" not in str(error.value)
    assert "2" in str(error.value)


def test_a_remapped_unit_is_explicitly_unsupported(api):
    item = provenance(ORDERS)
    document = item.unit.document
    segment = document.segments[0]
    moved = replace(
        document,
        analysis_text=document.analysis_text[1:],
        segments=(OriginalSegment(segment.unit_key, segment.start + 1, segment.end),),
    )
    remapped = replace(item, provenance=replace(item.provenance, unit=replace(item.unit, document=moved)))
    with pytest.raises(api.UnsupportedCodeChunkInput):
        prepare(api, [remapped], facts=CodeGraph(source_id=SOURCE))


def test_an_input_that_is_not_captured_code_is_rejected(api):
    document = provenance(ORDERS).unit.document
    with pytest.raises(api.UnsupportedCodeChunkInput):
        prepare(api, [document], facts=CodeGraph(source_id=SOURCE))
    with pytest.raises(api.UnsupportedCodeChunkInput):
        api.CapturedCode(raw(b"x", "a.py"), document)


def test_two_inputs_claiming_one_logical_path_are_rejected(api):
    with pytest.raises(api.UnsupportedCodeChunkInput):
        prepare(api, [provenance(ORDERS), provenance(CONFIG, "src/orders.py")])


# ------------------------------------------------------------- the latch


def test_a_disagreement_with_the_committed_chunker_fails_closed(api, monkeypatch):
    results = [provenance(ORDERS)]
    code = graph_of(units_of(results))
    real = api.chunk_documents

    def perturbed(docs, size_chars, overlap_chars, code=None):
        chunks = real(docs, size_chars, overlap_chars, code=code)
        chunks[0].text = chunks[0].text + " drift"
        return chunks

    monkeypatch.setattr(api, "chunk_documents", perturbed)
    with pytest.raises(api.CodeChunkParityError) as error:
        prepare(api, results, facts=code)
    assert " drift" not in str(error.value) and "OrderService" not in str(error.value)


def test_the_reexpressed_header_rows_equal_the_committed_ones(api):
    results = [provenance(ORDERS)]
    code = graph_of(units_of(results))
    unit = units_of(results)[0]
    lines = unit.analysis_text.splitlines()
    symbols = code.by_path(unit.logical_path)
    module = chunker._file_module(symbols)
    for symbol in [module, *chunker._members(module, symbols)]:
        if symbol.kind not in chunker.CONTAINER_KINDS:
            continue
        members = chunker._members(symbol, symbols)
        placeholders = chunker._placeholders(symbol, symbols, members)
        expected = chunker._header_rows(symbol, placeholders, lines)
        mine = api._header_rows(symbol, placeholders, lines)
        assert [(row.line, row.text) for row in mine] == expected


# --------------------------------------------------------------- structure


def test_an_oversized_body_splits_at_statement_boundaries_as_today(api):
    body = "".join(f"    step_{i} = compute({i})\n" for i in range(40))
    text = f'def big():\n    """A big body."""\n{body}    return 0\n'
    results = [provenance(text, "src/big.py")]
    prepared, code = prepare(api, results, size=200, overlap=0)
    assert [c.to_chunk() for c in prepared.chunks] == legacy(results, code, size=200, overlap=0)
    parts = [c for c in prepared.chunks if "(part " in c.title]
    assert len(parts) >= 2
    assert all(part.symbol_id for part in parts)
    assert [part.extract_text for part in parts][1:] == [""] * (len(parts) - 1)


def test_originals_close_over_every_declared_dependency(api):
    results = [provenance(ORDERS), provenance(SCHEMA, "db/schema.sql")]
    prepared, _ = prepare(api, results)
    for chunk in prepared.chunks:
        declared = {dep.unit_key for dep in chunk.original_dependencies}
        assert declared == {original.unit_key for original in chunk.originals}
        for dep in chunk.original_dependencies:
            covering = [
                o
                for o in chunk.originals
                if o.unit_key == dep.unit_key and o.lines.start <= dep.start and dep.end <= o.lines.end
            ]
            assert len(covering) == 1, "every dependency lies in exactly one complete-line closure"


def test_prepared_chunks_are_immutable_and_keyed(api):
    prepared, _ = prepare(api, [provenance(ORDERS)])
    chunk = prepared.chunks[0]
    assert chunk.chunk_key and chunk.support_chunk_keys == (chunk.chunk_key,)
    with pytest.raises(FrozenInstanceError):
        chunk.text = "other"
    again, _ = prepare(api, [provenance(ORDERS)])
    assert [c.chunk_key for c in again.chunks] == [c.chunk_key for c in prepared.chunks]


def test_a_rust_impl_written_below_the_type_follows_the_type(api):
    text = (
        "pub struct OrderService {\n    pub id: u32,\n}\n\n"
        "pub fn helper(v: u32) -> u32 {\n    v + 1\n}\n\n"
        "impl OrderService {\n    pub fn place(&self) -> u32 {\n        self.id\n    }\n}\n"
    )
    results = [provenance(text, "src/orders.rs")]
    prepared, code = prepare(api, results)
    assert [c.to_chunk() for c in prepared.chunks] == legacy(results, code)
    titles = [c.title for c in prepared.chunks]
    assert any("OrderService.place" in title for title in titles)


# ------------------------------------------------------------ seeded parity

PY_PIECES = (
    "import os\n",
    "VALUE = 'orders'\n",
    "# a comment line\n",
    "\n",
    'def {n}(a, b):\n    """Doc for {n}, long enough that the extractor would read it."""\n'
    "    return a + b\n",
    "class {N}:\n    def one(self):\n        return 1\n\n    def two(self):\n        return 2\n",
    "class {N}:\n    pass\n",
    "async def {n}_async():\n    await go()\n",
)
TS_PIECES = (
    "import fs from 'fs';\n",
    "export function {n}(a: number): number {{\n  return a + 1;\n}}\n",
    "export class {N} {{\n  one() {{ return 1; }}\n  two() {{ return 2; }}\n}}\n",
    "// a comment\n",
    "\n",
)
GO_PIECES = (
    "package main\n",
    'import "fmt"\n',
    "func {N}(a int) int {{\n\treturn a + 1\n}}\n",
    "type {N}Svc struct {{\n\tID int\n}}\n",
    "func (s *{N}Svc) Place() int {{\n\treturn s.ID\n}}\n",
    "\n",
)
RS_PIECES = (
    "use std::fmt;\n",
    "pub struct {N} {{\n    pub id: u32,\n}}\n",
    "impl {N} {{\n    pub fn place(&self) -> u32 {{\n        self.id\n    }}\n}}\n",
    "pub fn {n}(v: u32) -> u32 {{\n    v + 1\n}}\n",
    "mod tests {{\n    fn t() {{}}\n}}\n",
    "\n",
)
CS_PIECES = (
    "using System;\n",
    "namespace Acme {{\n  public class {N} {{\n    public int One() {{ return 1; }}\n  }}\n}}\n",
    "// a comment\n",
    "\n",
)
SQL_PIECES = (
    "CREATE TABLE {n} (\n  id INT,\n  name TEXT\n);\n",
    "SELECT id FROM {n};\n",
    "-- a comment\n",
    "\n",
)
OTHER_PIECES = ("A paragraph of prose.\n", "# Heading\n", "\n", "key = value\n")

LANGUAGES = (
    ("py", PY_PIECES),
    ("ts", TS_PIECES),
    ("go", GO_PIECES),
    ("rs", RS_PIECES),
    ("cs", CS_PIECES),
    ("sql", SQL_PIECES),
    ("json", OTHER_PIECES),
    ("", OTHER_PIECES),
)


def seeded_units(random: Random, count: int):
    """`count` random files spread over the languages the walkers support."""
    out = []
    for index in range(count):
        suffix, pieces = LANGUAGES[index % len(LANGUAGES)]
        body = "".join(
            random.choice(pieces).format(n=f"item{random.randrange(4)}", N=f"Item{random.randrange(4)}")
            for _ in range(random.randrange(1, 7))
        )
        if random.randrange(4) == 0:
            body = "\n" * random.randrange(1, 4) + body
        if random.randrange(6) == 0:
            body += "\n   \n"
        if random.randrange(7) == 0:  # a line boundary `splitlines` knows and `_lines` does not
            body = body.replace("\n", random.choice(("\x0c\n", "\r")), 1)
        name = f"pkg{index % 7}/file{index}" + (f".{suffix}" if suffix else "")
        if not suffix:
            name = f"pkg{index % 7}/README"
        newline = "\r\n" if random.randrange(5) == 0 else "\n"
        out.append(provenance(body or "x = 1\n", name, newline=newline, bom=random.randrange(9) == 0))
    return out


def descriptor(chunk) -> list:
    return [
        chunk.ordinal,
        chunk.kind,
        chunk.title,
        chunk.text,
        list(chunk.defines),
        chunk.extract_text,
        chunk.logical_path,
        [
            ["original", s.unit_key, s.start, s.end]
            if type(s) is OriginalSegment
            else ["generated", s.text, s.rule_id, list(s.original_unit_keys)]
            if type(s) is GeneratedSegment
            else ["commit", s.text, s.rule_id, s.commit_id]
            for s in chunk.retrieval_segments
        ],
        [[o.unit_key, o.lines.locator.start, o.lines.locator.end] for o in chunk.originals],
    ]


def test_two_thousand_seeded_units_match_the_committed_chunker(api):
    random = Random(5507)
    kinds: set[str] = set()
    rules: set[str] = set()
    total = units = parts = 0
    for batch in range(50):
        results = seeded_units(random, 44)
        size = random.choice((80, 200, 1500))
        code = graph_of(units_of(results), f"{SOURCE}-{batch}")
        if batch % 3 == 0 and code.symbols:
            code = history(code, count=2)
        prepared, _ = prepare(api, results, size=size, overlap=0, facts=code)
        assert [c.to_chunk() for c in prepared.chunks] == legacy(results, code, size=size, overlap=0)
        units += len(units_of(results))
        for chunk in prepared.chunks:
            assert render(chunk) == chunk.text
            kinds.add(chunk.kind)
            rules.update(s.rule_id for s in chunk.retrieval_segments if type(s) is not OriginalSegment)
            parts += "(part " in chunk.title
            # Every character is either a declared original range or a marked generated one.
            assert sum(
                (s.end - s.start) if type(s) is OriginalSegment else len(s.text)
                for s in chunk.retrieval_segments
            ) == len(chunk.text)
        total += len(prepared.chunks)
    assert units >= 2_000, f"the seeded corpus produced only {units} units"
    assert kinds == set(api.CODE_CHUNK_KINDS), f"seeded corpus missed {set(api.CODE_CHUNK_KINDS) - kinds}"
    assert {api.CODE_PLACEHOLDER_RULE, api.CODE_LINE_JOIN_RULE, api.CODE_COMMIT_RULE} <= rules
    assert parts and total > units


def test_the_parity_fixture_digest_is_pinned_against_the_rule_version(api):
    random = Random(4242)
    digest = sha256()
    digest.update(api.CODE_CHUNK_RULE_VERSION.encode())
    for batch in range(5):
        results = seeded_units(random, 20)
        code = graph_of(units_of(results), f"{SOURCE}-pin-{batch}")
        if batch == 0 and code.symbols:
            code = history(code, count=2)
        prepared, _ = prepare(api, results, size=200, overlap=0, facts=code)
        payload = [descriptor(chunk) for chunk in prepared.chunks]
        digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode())
    assert digest.hexdigest() == api.CODE_CHUNK_FIXTURE_DIGEST
