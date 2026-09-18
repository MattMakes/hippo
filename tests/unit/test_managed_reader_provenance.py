"""Plain input mapping is independent of store backends and legacy dispatch."""

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from importlib import import_module
from types import SimpleNamespace

import pytest

from hippo.ingest.readers import TextBudget, TooLarge, read_bytes


@pytest.fixture
def api():
    return import_module("hippo.ingest.provenance")


def test_provenance_reader_api_exists():
    from importlib.util import find_spec

    assert find_spec("hippo.ingest.provenance") is not None, "plain provenance reader is missing"


def raw(api, data, path="src/example.py", **kwargs):
    digest = sha256(data).hexdigest()
    return api.RawInput(
        input_key="file:" + path,
        logical_path=path,
        media_type="text/plain",
        raw_uri="hippo-raw:sha256:" + digest,
        raw_hash=digest,
        byte_length=len(data),
        **kwargs,
    )


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a.py", b"\n  def f():\r\n    return 1\r\n\t"),
        ("readme.md", "\ufeff\n  Café 😀\r\nCafé 😀\n ".encode()),
        ("go.mod", b"module test\n"),
        ("README", b"\t hello\n"),
        ("a.yaml", b"a: b\r\n"),
        ("a.txt", b"hello\xff"),
        ("a.txt", b"x" * 8000 + b"\xe2\x82!\xff"),
        ("a.txt", b"\xef\xbb\xbf"),
        ("a.txt", b""),
        ("a.txt", b" \r\n\t"),
        ("a.txt", b"\x00binary"),
    ],
)
def test_analysis_matches_legacy_exactly(api, name, data):
    expected = read_bytes(data, name, path="temporary/display:" + name)
    result = api.read_plain_provenance(raw(api, data), data, name=name, path="temporary/display:" + name)
    assert [doc.to_document() for doc in result.documents] == expected
    if result.documents:
        doc = result.documents[0]
        assert doc.render() == doc.analysis_text == expected[0].text
        assert doc.original_units[0].text == data.decode("utf-8-sig", errors="replace")
        assert doc.original_units[0].locator.path == "src/example.py"


def test_bom_crlf_trim_unicode_and_repeat_offsets(api):
    data = "\ufeff \r\nα😀\r\nα😀\r\n \t".encode()
    result = api.read_plain_provenance(raw(api, data), data)
    doc = result.documents[0]
    unit = doc.original_units[0]
    assert unit.text == " \r\nα😀\r\nα😀\r\n \t"
    assert unit.bom_bytes == 3
    assert unit.locator.start == 1 and unit.locator.end == 4
    assert tuple(line.newline for line in unit.lines) == ("\r\n", "\r\n", "\r\n", "")
    assert tuple(line.start for line in unit.lines) == (0, 3, 7, 11)
    second = doc.original_segments_for_bytes(8, 14)
    assert second == (api.OriginalSegment(unit.unit_key, 7, 9),)
    assert unit.text[second[0].start : second[0].end] == "α😀"
    assert unit.raw_ranges[7].start == 14
    assert data[unit.raw_ranges[7].start : unit.raw_ranges[8].end].decode() == "α😀"
    lines = unit.complete_lines(second[0].start, second[0].end)
    assert lines.text == "α😀\r\n" and lines.locator.start == lines.locator.end == 3
    assert lines.start == 7 and lines.end == 11
    with pytest.raises(ValueError, match="UTF-8 boundary"):
        doc.original_segments_for_bytes(1, 2)


def test_long_line_partial_range_requires_complete_line_original(api):
    data = b"  abcdef  \n"
    doc = api.read_plain_provenance(raw(api, data), data).documents[0]
    segment = doc.original_segments_for_bytes(1, 3)[0]
    unit = doc.original_units[0]
    assert unit.text[segment.start : segment.end] == "bc"
    original = unit.complete_lines(segment.start, segment.end)
    assert original.text == data.decode()
    assert original.locator.start == original.locator.end == 1


@pytest.mark.parametrize("tail", [b"\xff", b"\xe2\x82", b"\xe2\x82!", b"\xed\xa0\x80", b"\xf0\x80\x80\x80"])
def test_replacement_groups_match_actual_decoder(api, tail):
    data = b"x" * 8000 + tail
    unit = api.read_plain_provenance(raw(api, data), data).original_units[0]
    assert unit.text == data.decode("utf-8-sig", errors="replace")
    assert len(unit.raw_ranges) == len(unit.text)
    assert unit.decoder_profile.endswith("replace-v1")
    for char, mapping in zip(unit.text, unit.raw_ranges, strict=True):
        piece = data[mapping.start : mapping.end]
        if mapping.exact:
            assert piece.decode("utf-8") == char
        else:
            assert char == "�" and piece.decode("utf-8", errors="replace") == char
    assert all(a.end == b.start for a, b in zip(unit.raw_ranges, unit.raw_ranges[1:], strict=False))
    assert unit.raw_ranges[-1].end == len(data)


def test_strict_unknown_name_decode_failure_is_not_empty(api):
    data = b"x" * 8000 + b"\xff"
    with pytest.raises(UnicodeDecodeError):
        api.read_plain_provenance(raw(api, data), data, name="unknown")


def test_binary_and_empty_are_explicit_and_whitespace_original_is_retained(api):
    for data, expected in [(b"", "empty"), (b" \n ", "empty"), (b"\x00", "binary")]:
        result = api.read_plain_provenance(raw(api, data), data)
        assert result.outcome == expected and result.documents == ()
        if data == b" \n ":
            assert result.original_units[0].text == " \n "
        else:
            assert result.original_units == ()


@pytest.mark.parametrize("name", ["a.pdf", "a.docx", "a.html", "a.htm", "a.epub", "a.zip"])
def test_rich_and_archive_formats_are_explicitly_unsupported(api, name):
    data = b"input"
    with pytest.raises(api.UnsupportedProvenanceFormat):
        api.read_plain_provenance(raw(api, data), data, name=name)


def test_raw_identity_and_safe_paths(api):
    data = b"source"
    ref = raw(api, data, container_chain=("outer.zip", "inner.zip"))
    assert ref.raw_artifact.sha256 == sha256(data).hexdigest()
    assert ref.container_chain == ("outer.zip", "inner.zip")
    for path in ("/tmp/a.py", "../a.py", "a/../../b.py"):
        with pytest.raises(ValueError):
            raw(api, data, path=path)
    with pytest.raises(ValueError, match="raw"):
        api.read_plain_provenance(ref, b"changed")
    with pytest.raises(ValueError):
        replace(ref, byte_length=-1)


def test_budget_counts_analysis_before_building_large_character_map(api):
    data = b" " * 500 + b"content" + b" " * 500
    budget = TextBudget(limit=7)
    result = api.read_plain_provenance(raw(api, data), data, budget=budget)
    assert budget.used == 7 and result.documents[0].analysis_text == "content"
    with pytest.raises(TooLarge):
        api.read_plain_provenance(raw(api, data), data, budget=TextBudget(limit=6))


def test_documents_are_frozen_and_generated_repeat_segments_keep_order(api):
    data = b"repeat\nrepeat\n"
    doc = api.read_plain_provenance(raw(api, data), data).documents[0]
    unit = doc.original_units[0]
    segments = (
        api.OriginalSegment(unit.unit_key, 7, 13),
        api.GeneratedSegment(" / ", "join-v1", (unit.unit_key,)),
        api.OriginalSegment(unit.unit_key, 0, 6),
    )
    changed = replace(doc, analysis_text="repeat / repeat", segments=segments)
    assert changed.render() == "repeat / repeat"
    assert changed.original_segments_for_bytes(0, 15) == segments
    assert changed.original_segments_for_bytes(8, 11) == (
        api.GeneratedSegment(" ", "join-v1", (unit.unit_key,)),
        api.OriginalSegment(unit.unit_key, 0, 2),
    )
    legacy = changed.to_document()
    legacy.text = "mutated"
    assert changed.analysis_text == "repeat / repeat"
    with pytest.raises(FrozenInstanceError):
        changed.title = "mutated"
    with pytest.raises(ValueError, match="reconstruct"):
        replace(changed, analysis_text="unmapped")
    with pytest.raises(ValueError):
        replace(changed, segments=(api.OriginalSegment("missing", 0, 6),))
    with pytest.raises(ValueError):
        replace(changed, segments=(api.GeneratedSegment(changed.analysis_text, "join", ("missing",)),))
    with pytest.raises(ValueError):
        replace(changed, segments=(api.OriginalSegment(unit.unit_key, 0, 999),))


def test_mutable_metadata_cannot_enter_frozen_values(api):
    data = b"original"
    ref = raw(api, data)
    with pytest.raises(ValueError):
        replace(ref, provider_revision=["mutable"])
    with pytest.raises(ValueError):
        replace(ref, input_key=["mutable"])
    with pytest.raises(ValueError):
        replace(ref, container_chain="archive.zip")
    doc = api.read_plain_provenance(ref, data).documents[0]
    with pytest.raises(ValueError):
        replace(doc, title=["mutable"])
    with pytest.raises(ValueError):
        replace(doc.original_units[0], decoder_profile=["mutable"])
    with pytest.raises(ValueError):
        api.GeneratedSegment("value", ["mutable"], (doc.original_units[0].unit_key,))
    segments = list(doc.segments)
    copied = replace(doc, segments=segments)
    segments.clear()
    assert copied.render() == "original"
    original = doc.original_units[0].complete_lines(0, 1)
    with pytest.raises(ValueError):
        replace(original, text=["mutable"])


def test_malformed_mapping_and_outcome_are_rejected(api):
    data = b"value"
    result = api.read_plain_provenance(raw(api, data), data)
    unit = result.original_units[0]
    with pytest.raises(ValueError):
        replace(unit, raw_ranges=(api.RawCharacterRange(0, 1, False),) + unit.raw_ranges[1:])
    with pytest.raises(ValueError):
        replace(unit, decoder_profile="unknown-decoder")
    with pytest.raises(ValueError):
        replace(result, original_units=())
    with pytest.raises(ValueError):
        api.ProvenanceRead((), (unit,), "binary")
    with pytest.raises(ValueError):
        api.GeneratedSegment("text", "rule", ())
    with pytest.raises(ValueError):
        unit.complete_lines(2, 2)
    with pytest.raises(ValueError):
        result.documents[0].original_segments_for_bytes(-1, 1)
    assert result.documents[0].original_segments_for_bytes(5, 5) == ()


def test_original_map_budget_is_enforced_before_allocating_ranges(api, monkeypatch):
    monkeypatch.setattr(api, "MAX_TEXT_CHARS", 8)

    def mapping_must_not_run(*args):
        pytest.fail("unbounded original map was allocated")

    monkeypatch.setattr(api, "_raw_ranges", mapping_must_not_run)
    for data in (b" " * 9, b" " * 9 + b"a"):
        with pytest.raises(TooLarge, match="original provenance"):
            api.read_plain_provenance(raw(api, data), data)


def test_physical_line_policy_and_literal_replacement_character(api):
    data = "a\rb\r\nc\nd\u2028e�".encode()
    unit = api.read_plain_provenance(raw(api, data), data).original_units[0]
    assert tuple(line.newline for line in unit.lines) == ("\r", "\r\n", "\n", "")
    assert unit.locator.end == 4
    assert unit.raw_ranges[-1].exact
    assert unit.raw_ranges[-1].end - unit.raw_ranges[-1].start == 3
    assert unit.complete_lines(0, len(unit.text)).text == unit.text


def test_actual_codec_mapping_for_every_lead_and_continuation_boundary(api):
    # Placing invalid sequences beyond the legacy binary-sniff prefix preserves
    # its behavior while exercising the decoder's actual replacement groups.
    tails = [bytes((lead, 0x41)) for lead in range(256)]
    tails += [bytes((lead, second, 0x80, 0x41)) for lead in (0xE0, 0xED, 0xF0, 0xF4) for second in range(256)]
    data = b"x" * 8000 + b"".join(tails)
    unit = api.read_plain_provenance(raw(api, data), data).original_units[0]
    assert unit.text == data.decode("utf-8", errors="replace")
    assert len(unit.raw_ranges) == len(unit.text)
    for char, mapping in zip(unit.text, unit.raw_ranges, strict=True):
        assert data[mapping.start : mapping.end].decode("utf-8", errors="replace") == char


@pytest.mark.parametrize("boundary", ["raw_range", "locator", "unit", "document", "line", "slice_locator"])
def test_mutable_duck_typed_children_are_rejected(api, boundary):
    data = b"x"
    result = api.read_plain_provenance(raw(api, data), data)
    doc = result.documents[0]
    unit = doc.original_units[0]
    fake_unit = SimpleNamespace(unit_key=unit.unit_key, text=unit.text)
    with pytest.raises(ValueError):
        if boundary == "raw_range":
            replace(unit, raw_ranges=(SimpleNamespace(start=0, end=1, exact=True),))
        elif boundary == "locator":
            replace(unit, locator=SimpleNamespace(start=1, end=1))
        elif boundary == "unit":
            replace(doc, original_units=(fake_unit,))
        elif boundary == "document":
            replace(result, documents=(SimpleNamespace(original_units=(unit,)),))
        elif boundary == "line":
            replace(unit, lines=(SimpleNamespace(start=0, end=1, newline=""),))
        else:
            replace(unit.complete_lines(0, 1), locator=SimpleNamespace(start=1, end=1))


def test_read_result_rejects_mutable_units_even_without_documents(api):
    fake_unit = SimpleNamespace(unit_key="unit", text="  ")
    with pytest.raises(ValueError):
        api.ProvenanceRead((), (fake_unit,), "empty")
