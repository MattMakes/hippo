"""Code and config decode with exact complete-line locators and Unicode byte mappings."""

from dataclasses import FrozenInstanceError
from hashlib import sha256
from importlib import import_module
from random import Random

import pytest

from hippo.codegraph.model import CODE_MAX_FILE_BYTES
from hippo.ingest.provenance import read_plain_provenance
from hippo.ingest.readers import TextBudget, TooLarge


@pytest.fixture
def api():
    return import_module("hippo.ingest.code_provenance")


def raw(data: bytes, path: str = "src/example.py"):
    from hippo.knowledge.inputs import RawInput

    digest = sha256(data).hexdigest()
    return RawInput(
        input_key="raw-input:" + path,
        logical_path=path,
        media_type="text/plain",
        raw_uri="hippo-raw:sha256:" + digest,
        raw_hash=digest,
        byte_length=len(data),
    )


def read(api, data: bytes, path: str = "src/example.py", **kwargs):
    return api.read_code_provenance(raw(data, path), data, **kwargs)


# --------------------------------------------------------------- outcomes


def test_a_code_file_decodes_to_one_frozen_unit_with_its_analysis_document(api):
    data = b"\n  def f():\r\n    return 1\r\n\t"
    result = read(api, data)
    assert result.outcome == "text"
    assert result.language == "python"
    unit = result.unit
    assert unit.logical_path == "src/example.py"
    assert unit.input_key == "raw-input:src/example.py"
    assert unit.is_code is True and unit.parsable is True
    assert unit.original.text == data.decode("utf-8-sig")
    assert unit.analysis_text == "def f():\r\n    return 1"
    assert unit.analysis_offset == 3
    assert unit.document.render() == unit.analysis_text
    with pytest.raises(FrozenInstanceError):
        unit.language = "go"


@pytest.mark.parametrize(
    ("path", "data", "outcome"),
    [
        ("a.py", b"\x00binary", "binary"),
        ("a.py", b"", "empty"),
        ("a.py", b" \r\n\t", "empty"),
        ("a.py", b"x = 1\n", "text"),
        ("conf/app.yaml", b"a: b\r\n", "text"),
        ("go.mod", b"module test\n", "text"),
        ("README", b"\t hello\n", "text"),
    ],
)
def test_outcomes_match_the_plain_reader(api, path, data, outcome):
    result = read(api, data, path)
    assert result.outcome == outcome
    assert (result.unit is not None) == (outcome == "text")
    assert result.read.outcome == outcome


def test_a_whitespace_only_file_is_empty_yet_keeps_its_original_unit(api):
    result = read(api, b" \r\n\t", "a.py")
    assert result.outcome == "empty" and result.unit is None
    (original,) = result.read.original_units
    assert original.text == " \r\n\t"


def test_binary_inputs_claim_no_decoded_original(api):
    result = read(api, b"\x00binary", "a.py")
    assert result.outcome == "binary" and result.unit is None
    assert result.read.original_units == ()


# -------------------------------------------------------------- refusals


@pytest.mark.parametrize("path", ["doc.pdf", "doc.docx", "doc.epub", "page.html", "page.htm", "b.zip"])
def test_rich_and_archive_names_refuse_in_this_seam(api, path):
    with pytest.raises(api.UnsupportedProvenanceFormat):
        read(api, b"anything", path)


@pytest.mark.parametrize("path", ["notes.md", "notes.txt", "notes.rst", "notes.markdown", "notes.text"])
def test_plain_prose_names_route_to_the_prose_lane(api, path):
    with pytest.raises(api.UnsupportedCodeFormat):
        read(api, b"hello\n", path)
    assert issubclass(api.UnsupportedCodeFormat, api.UnsupportedProvenanceFormat)


def test_bytes_that_do_not_match_the_accepted_identity_refuse(api):
    with pytest.raises(ValueError, match="accepted raw identity"):
        api.read_code_provenance(raw(b"x = 1\n"), b"x = 2\n")


def test_the_shared_text_budget_still_bounds_a_captured_tree(api):
    budget = TextBudget(limit=10)
    read(api, b"x = 1\n", "a.py", budget=budget)
    with pytest.raises(TooLarge):
        read(api, b"y = 22222\n", "b.py", budget=budget)


# ----------------------------------------------------- language detection


@pytest.mark.parametrize(
    ("path", "language", "is_code"),
    [
        ("a.py", "python", True),
        ("a.pyi", "python", True),
        ("a.tsx", "typescript", True),
        ("a.mjs", "typescript", True),
        ("a.go", "go", True),
        ("a.cs", "csharp", True),
        ("a.rs", "rust", True),
        ("q.sql", "sql", True),
        ("app.yaml", None, True),
        ("app.json", None, True),
        ("a.rb", None, True),
        ("go.mod", None, False),
        ("README", None, False),
        ("Makefile", None, False),
    ],
)
def test_language_follows_the_walker_rule_and_never_content(api, path, language, is_code):
    result = read(api, b"module test\n", path)
    assert result.language == language
    assert result.unit.language == language
    assert result.unit.is_code is is_code


def test_a_python_shebang_does_not_make_an_extensionless_file_python(api):
    result = read(api, b"#!/usr/bin/env python\nx = 1\n", "TOOLS")
    assert result.language is None and result.unit.parsable is False


def test_a_file_over_the_parse_rail_is_captured_but_not_parsable(api):
    result = read(api, b"x = 1\n" + b"# pad\n" * 32, "a.py")
    assert result.unit.parsable is True
    big = read(api, b"#" + b"x" * (CODE_MAX_FILE_BYTES + 8) + b"\n", "big.py")
    assert big.outcome == "text" and big.unit.parsable is False
    assert big.unit.language == "python"


# ------------------------------------------------- complete-line locators


def test_complete_line_locators_expand_to_whole_original_lines(api):
    data = b"import os\n\n\ndef f():\n    return os\n"
    unit = read(api, data, "pkg/mod.py").unit
    assert unit.analysis_offset == 0
    lines = unit.lines_for_analysis(len("import "), len("import os"))
    assert lines.locator.path == "pkg/mod.py"
    assert (lines.locator.start, lines.locator.end) == (1, 1)
    assert lines.text == "import os\n"
    body = unit.lines_for_analysis(unit.analysis_text.index("def"), len(unit.analysis_text))
    assert (body.locator.start, body.locator.end) == (4, 5)
    assert body.text == "def f():\n    return os\n"


def test_leading_blank_lines_are_counted_in_the_original_not_the_analysis(api):
    data = b"\n\n\nx = 1\n"
    unit = read(api, data, "a.py").unit
    assert unit.analysis_text == "x = 1"
    lines = unit.lines_for_analysis(0, len(unit.analysis_text))
    assert (lines.locator.start, lines.locator.end) == (4, 4)


def test_parser_byte_ranges_map_through_unicode_to_complete_lines(api):
    data = "# α😀 header\nvalue = 'δ'\n".encode()
    unit = read(api, data, "a.py").unit
    text = unit.analysis_text
    start = len(text[: text.index("value")].encode("utf-8"))
    end = len(text[: text.index("'δ'") + 3].encode("utf-8"))
    lines = unit.lines_for_parser_bytes(start, end)
    assert (lines.locator.start, lines.locator.end) == (2, 2)
    assert lines.text == "value = 'δ'\n"
    whole = unit.lines_for_parser_bytes(0, len(text.encode("utf-8")))
    assert (whole.locator.start, whole.locator.end) == (1, 2)


def test_a_parser_offset_inside_a_character_refuses(api):
    unit = read(api, "x = '😀'\n".encode(), "a.py").unit
    with pytest.raises(ValueError, match="UTF-8 boundary"):
        unit.lines_for_parser_bytes(0, 6)


def test_the_original_unit_maps_every_character_to_its_raw_bytes(api):
    data = "﻿α😀 = 1\n".encode()
    unit = read(api, data, "a.py").unit
    original = unit.original
    assert original.bom_bytes == 3
    assert len(original.raw_ranges) == len(original.text)
    assert original.raw_ranges[0].start == 3 and original.raw_ranges[0].end == 5
    assert original.raw_ranges[1].end - original.raw_ranges[1].start == 4
    assert all(item.exact for item in original.raw_ranges)


def test_replacement_decoding_stays_non_exact_for_code_names(api):
    unit = read(api, b"x = 1\xff\n", "a.py").unit
    assert "�" in unit.original.text
    assert not all(item.exact for item in unit.original.raw_ranges)
    assert unit.original.decoder_profile == "plain-utf8-sig-replace-v1"


def test_an_extensionless_name_decodes_strictly_like_the_legacy_reader(api):
    unit = read(api, b"hello\n", "README").unit
    assert unit.original.decoder_profile == "plain-utf8-sig-strict-v1"


# ------------------------------------------------------- decoder parity


def test_twenty_thousand_seeded_cases_match_the_plain_reader(api):
    random = Random(20260912)
    names = [
        "a.py",
        "a.pyi",
        "pkg/b.ts",
        "svc/c.go",
        "d.cs",
        "e.rs",
        "q.sql",
        "app.yaml",
        "app.json",
        "f.rb",
        "go.mod",
        "README",
        "Makefile",
        "LICENSE",
        "conf/app.ini",
    ]
    pieces = [
        b"",
        b"\n",
        b"\r\n",
        b"\r",
        b"\t ",
        b"x = 1",
        b"def f():",
        b"\xef\xbb\xbf",
        b"\xff",
        b"\xe2\x82",
        b"\xf0\x9f\x98\x80",
        b"\xce\xb1",
        "café".encode(),
        b"# comment",
        b"\x80\x80",
        b"}",
    ]
    checked, refused = 0, 0
    for _ in range(20_000):
        name = random.choice(names)
        data = b"".join(random.choice(pieces) for _ in range(random.randrange(0, 9)))
        accepted = raw(data, name)
        try:
            expected = read_plain_provenance(accepted, data, name=name, path=name)
        except (ValueError, UnicodeDecodeError) as error:
            # A strict-decode name that is not clean UTF-8 must fail identically.
            with pytest.raises(type(error)):
                api.read_code_provenance(accepted, data, name=name, path=name)
            checked += 1
            refused += 1
            continue
        result = api.read_code_provenance(accepted, data, name=name, path=name)
        assert result.outcome == expected.outcome
        assert result.read.original_units == expected.original_units
        assert result.read.documents == expected.documents
        if result.unit is not None:
            assert result.unit.original == expected.original_units[0]
            assert result.unit.document == expected.documents[0]
            assert result.unit.analysis_text == expected.documents[0].analysis_text
        checked += 1
    assert checked == 20_000 and refused > 0


def test_parity_covers_every_outcome_the_plain_reader_can_produce(api):
    random = Random(4)
    seen = set()
    for _ in range(600):
        data = bytes(random.randrange(0, 256) for _ in range(random.randrange(0, 6)))
        seen.add(read(api, data, "a.py").outcome)
    assert seen == {"text", "empty", "binary"}
