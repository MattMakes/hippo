"""Plain prose preparation retains origins through the shared legacy algorithm."""

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from random import Random
from types import SimpleNamespace

import pytest

from hippo.ingest.chunker import chunk_documents
from hippo.ingest.provenance import GeneratedSegment, OriginalSegment, RawInput, read_plain_provenance


@pytest.fixture
def api():
    return import_module("hippo.ingest.prepared_chunks")


def test_prepared_prose_api_exists():
    from importlib.util import find_spec

    assert find_spec("hippo.ingest.prepared_chunks") is not None, "mapped prose preparation is missing"


def document(text, name="notes.md"):
    data = text.encode()
    digest = sha256(data).hexdigest()
    raw = RawInput("file:" + name, name, "text/plain", "hippo-raw:sha256:" + digest, digest, len(data))
    return read_plain_provenance(raw, data).documents[0]


def render(chunk):
    units = {unit.unit_key: unit for unit in chunk.original_units}
    return "".join(
        units[s.unit_key].text[s.start : s.end] if isinstance(s, OriginalSegment) else s.text
        for s in chunk.retrieval_segments
    )


@pytest.mark.parametrize("size,overlap", [(1500, 150), (100, 0), (200, 60), (1, -1), (50, 999)])
@pytest.mark.parametrize(
    "text",
    [
        "# Title\n\n## Part\n\nA paragraph.\n\nAnother paragraph.",
        "# Title\n\nFirst.\n\n## Title\n\nRepeated title.",
        "\ufeff \r\n# Résumé 😀\r\n\r\nSame 😀.\r\n\r\nSame 😀.\r\n ",
        " ".join(f"Sentence number {i} is here." for i in range(40)),
        " ".join(f"word{i}" for i in range(100)),
        "z" * 233,
        "## Heading\n\n```\n# Not a heading\nprint('x')\n```\n\nLast paragraph.",
        "a\rb\r\nc\u2028d\n\nend",
    ],
)
def test_plain_chunk_outputs_match_legacy(api, text, size, overlap):
    doc = document(text)
    expected = chunk_documents([doc.to_document()], size, overlap)
    prepared = api.prepare_prose_chunks((doc,), size_chars=size, overlap_chars=overlap)
    assert [chunk.to_chunk() for chunk in prepared] == expected
    for chunk in prepared:
        assert render(chunk) == chunk.text
        assert chunk.extraction_segments == chunk.retrieval_segments
        assert chunk.extract_text is None and chunk.defines == ()
        assert chunk.support_chunk_keys == (chunk.chunk_key,)


def test_real_sample_has_eight_legacy_equivalent_chunks(api):
    doc = document((Path(__file__).parents[2] / "samples/acme_robotics.md").read_text(), "acme.md")
    prepared = api.prepare_prose_chunks((doc,), size_chars=1500, overlap_chars=150)
    assert len(prepared) == 8
    assert [c.to_chunk() for c in prepared] == chunk_documents([doc.to_document()], 1500, 150)
    assert prepared[0].title == "The Acme Robotics Field Guide › The company"
    assert {o.lines.locator.start for o in prepared[0].originals} >= {1}


def test_repeated_equal_paragraphs_retain_distinct_positions(api):
    paragraph = "Identical paragraph with enough words to fill most of one chunk."
    doc = document(paragraph + "\n\n" + paragraph)
    first, second = api.prepare_prose_chunks((doc,), size_chars=70, overlap_chars=0)
    assert first.text == second.text == paragraph
    assert first.retrieval_segments == (OriginalSegment(doc.original_units[0].unit_key, 0, len(paragraph)),)
    assert second.retrieval_segments == (
        OriginalSegment(doc.original_units[0].unit_key, len(paragraph) + 2, len(paragraph) * 2 + 2),
    )
    assert first.chunk_key != second.chunk_key
    assert first.originals[0].lines.locator.start == 1
    assert second.originals[0].lines.locator.start == 3


def test_overlap_reuses_original_ranges_and_generated_separators(api):
    doc = document(" ".join(f"Sentence number {i} is here." for i in range(40)))
    chunks = api.prepare_prose_chunks((doc,), size_chars=200, overlap_chars=60)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        prev = {(s.start, s.end) for s in previous.retrieval_segments if isinstance(s, OriginalSegment)}
        current_originals = [s for s in current.retrieval_segments if isinstance(s, OriginalSegment)]
        assert (current_originals[0].start, current_originals[0].end) in prev
        assert any(isinstance(s, GeneratedSegment) for s in current.retrieval_segments)
        assert render(current) == current.text
        assert current.originals[0].lines.text == doc.original_units[0].text


def test_hard_cut_long_line_never_claims_shortened_original(api):
    doc = document(" \r\n" + "α😀" * 120 + "\r\n ")
    chunks = api.prepare_prose_chunks((doc,), size_chars=50, overlap_chars=0)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.requires_view
        assert len(chunk.originals) == 1
        assert chunk.originals[0].lines.text == "α😀" * 120 + "\r\n"
        assert chunk.originals[0].lines.locator.start == chunk.originals[0].lines.locator.end == 2
    assert [
        s.start for chunk in chunks for s in chunk.retrieval_segments if isinstance(s, OriginalSegment)
    ] == [3, 53, 103, 153, 203]


def test_heading_title_inputs_are_retained_without_citing_unrelated_sections(api):
    doc = document("# Root title\n\n## Current\n\nChosen body.\n\n## Other\n\nUnrelated body.")
    first, second = api.prepare_prose_chunks((doc,), size_chars=500, overlap_chars=0)
    assert first.text == "Chosen body." and first.title == "Root title › Current"
    originals = "".join(item.lines.text for item in first.originals)
    assert "# Root title\n" in originals and "## Current\n" in originals
    assert "Chosen body.\n" in originals
    assert "Other" not in originals and "Unrelated" not in originals
    assert "Current" not in "".join(item.lines.text for item in second.originals)
    assert first.requires_view


def test_generated_newline_is_a_view_even_when_rendering_matches_original(api):
    doc = document("First line\nsecond line")
    (chunk,) = api.prepare_prose_chunks((doc,), size_chars=500, overlap_chars=0)
    assert chunk.text == doc.original_units[0].text
    assert any(isinstance(segment, GeneratedSegment) for segment in chunk.retrieval_segments)
    assert chunk.requires_view
    assert all(s.original_unit_keys for s in chunk.retrieval_segments if isinstance(s, GeneratedSegment))


def test_untouched_whole_original_can_remain_original(api):
    doc = document("Exactly original.")
    (chunk,) = api.prepare_prose_chunks((doc,), size_chars=500, overlap_chars=0)
    assert not chunk.requires_view
    assert chunk.originals[0].lines.text == chunk.text


def test_ordinals_identity_and_immutable_legacy_adapter(api):
    docs = (document("First."), document("Second.", "second.txt"))
    prepared = api.prepare_prose_chunks(docs, size_chars=100, overlap_chars=0)
    assert [c.ordinal for c in prepared] == [0, 1]
    assert prepared == api.prepare_prose_chunks(docs, size_chars=100, overlap_chars=0)
    moved = replace(docs[0], path="/temporary/other-checkout/notes.md")
    assert (
        prepared[0].chunk_key
        == api.prepare_prose_chunks((moved,), size_chars=100, overlap_chars=0)[0].chunk_key
    )
    adapter = prepared[0].to_chunk()
    adapter.text = "changed"
    adapter.defines.append("foreign")
    assert prepared[0].text == "First." and prepared[0].defines == ()
    with pytest.raises(FrozenInstanceError):
        prepared[0].text = "changed"
    with pytest.raises(ValueError):
        replace(prepared[0], original_dependencies=(SimpleNamespace(unit_key="bad", start=0, end=1),))
    with pytest.raises(ValueError):
        replace(prepared[0], text="changed")


def test_unsupported_code_and_existing_generated_inputs_reject(api):
    doc = document("print('x')", "a.py")
    with pytest.raises(api.UnsupportedChunkProvenance):
        api.prepare_prose_chunks((doc,), size_chars=100, overlap_chars=0)
    prose = document("text")
    generated = replace(
        prose, segments=(GeneratedSegment("text", "other-reader", (prose.original_units[0].unit_key,)),)
    )
    with pytest.raises(api.UnsupportedChunkProvenance):
        api.prepare_prose_chunks((generated,), size_chars=100, overlap_chars=0)
    assert api.prepare_prose_chunks((), size_chars=100, overlap_chars=0) == ()


def test_prepared_identity_changes_with_title_and_exact_generated_inputs(api):
    doc = document("# Name\n\nFirst.\nsecond.")
    (chunk,) = api.prepare_prose_chunks((doc,), size_chars=100, overlap_chars=0)
    renamed = replace(chunk, title="Other name")
    assert renamed.chunk_key != chunk.chunk_key
    assert renamed.support_chunk_keys == (renamed.chunk_key,)
    assert chunk.title_dependencies
    assert len(chunk.segment_dependencies) == len(chunk.retrieval_segments)
    for segment, dependencies in zip(chunk.retrieval_segments, chunk.segment_dependencies, strict=True):
        assert dependencies
        if isinstance(segment, GeneratedSegment):
            assert set(segment.original_unit_keys) == {dep.unit_key for dep in dependencies}


def test_prepared_closure_cannot_drop_rendered_or_title_inputs(api):
    doc = document("# Title\n\nBody line\nsecond line")
    (chunk,) = api.prepare_prose_chunks((doc,), size_chars=100, overlap_chars=0)
    with pytest.raises(ValueError):
        replace(chunk, original_dependencies=(), originals=())
    with pytest.raises(ValueError):
        replace(chunk, segment_dependencies=())
    with pytest.raises(ValueError):
        replace(chunk, title_dependencies=(SimpleNamespace(unit_key="x", start=0, end=1),))


def test_non_plain_original_remapping_is_explicitly_unsupported(api):
    doc = document("First. Second.")
    unit = doc.original_units[0]
    reordered = replace(
        doc,
        analysis_text="Second. First.",
        segments=(
            OriginalSegment(unit.unit_key, 7, 14),
            OriginalSegment(unit.unit_key, 6, 7),
            OriginalSegment(unit.unit_key, 0, 6),
        ),
    )
    with pytest.raises(api.UnsupportedChunkProvenance):
        api.prepare_prose_chunks((reordered,), size_chars=100, overlap_chars=0)


def test_seeded_mixed_whitespace_heading_and_repetition_parity(api):
    random = Random(715)
    pieces = ("# Name", "## Part", "## Name", "Same sentence. Again!", "α😀" * 40, "```", "  indented  ", "")
    separators = ("\n", "\r\n", "\r", "\n\n", "\n \n", "\u2028", "\v")
    for _ in range(120):
        text = "".join(
            random.choice(pieces) + random.choice(separators) for _ in range(random.randrange(1, 14))
        )
        doc = document(text + "\nFinal body.")
        size, overlap = random.randrange(50, 160), random.randrange(0, 100)
        expected = chunk_documents([doc.to_document()], size, overlap)
        prepared = api.prepare_prose_chunks((doc,), size_chars=size, overlap_chars=overlap)
        assert [chunk.to_chunk() for chunk in prepared] == expected
        assert all(render(chunk) == chunk.text for chunk in prepared)
