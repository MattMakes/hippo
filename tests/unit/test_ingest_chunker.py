"""Tests for hippo.ingest.chunker: sizes, overlap, headings, code windows, ordinals."""

from __future__ import annotations

from pathlib import Path

from hippo.hipporag.indexer import Chunk
from hippo.ingest.chunker import (
    chunk_document,
    chunk_documents,
    code_windows,
    split_sections,
    split_sentences,
)
from hippo.ingest.readers import Document

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "acme_robotics.md"


def prose(text: str, title: str = "doc.md") -> Document:
    return Document(title=title, text=text, path=title, is_code=False)


def code(text: str, title: str = "app.py") -> Document:
    return Document(title=title, text=text, path=title, is_code=True)


def sentences(n: int, prefix: str = "Sentence") -> str:
    return " ".join(f"{prefix} number {i} is here." for i in range(n))


# ---------------------------------------------------------------- headings


def test_sample_is_split_on_headings_with_doc_and_heading_titles() -> None:
    doc = prose(SAMPLE.read_text(), title="acme_robotics.md")
    chunks = chunk_document(doc, size_chars=1500, overlap_chars=150)
    titles = [c.title for c in chunks]
    assert titles[0] == "The Acme Robotics Field Guide › The company"  # the H1 names the document
    assert "The Acme Robotics Field Guide › Suppliers" in titles
    assert len(chunks) == 8  # eight "##" sections; the H1 has no body of its own
    assert all(isinstance(c, Chunk) for c in chunks)
    assert [c.ordinal for c in chunks] == list(range(8))
    assert all(len(c.text) <= 1500 for c in chunks)
    assert chunks[0].text.startswith("Acme Robotics was founded in 2015")
    assert "##" not in chunks[0].text  # the heading lives in the title, not the text


def test_text_before_the_first_heading_keeps_the_document_title() -> None:
    doc = prose("Intro line.\n\n## Part A\n\nBody of A.")
    chunks = chunk_document(doc, 500, 50)
    assert [(c.title, c.text) for c in chunks] == [
        ("doc.md", "Intro line."),
        ("doc.md › Part A", "Body of A."),
    ]


def test_headings_inside_code_blocks_are_not_headings() -> None:
    text = "## Real\n\nSome text.\n\n```\n# not a heading\ncode()\n```\n"
    assert [h for h, _ in split_sections(text)] == ["Real"]


def test_empty_sections_are_dropped() -> None:
    assert split_sections("# Title\n\n## Empty\n\n## Full\n\nText.") == [("Full", "Text.")]


# -------------------------------------------------------------- packing


def test_paragraphs_are_packed_up_to_the_size_limit() -> None:
    paragraphs = [f"Paragraph {i} is about forty characters." for i in range(10)]
    doc = prose("\n\n".join(paragraphs))
    chunks = chunk_document(doc, size_chars=100, overlap_chars=0)
    assert all(len(c.text) <= 100 for c in chunks)
    assert chunks[0].text.count("Paragraph") == 2  # two paragraphs of ~40 chars + blank line fit in 100
    joined = "\n\n".join(c.text for c in chunks)
    assert all(p in joined for p in paragraphs)


def test_a_section_that_spills_over_gets_part_numbers() -> None:
    doc = prose("## Long\n\n" + sentences(30))
    chunks = chunk_document(doc, size_chars=200, overlap_chars=0)
    assert len(chunks) > 1
    assert [c.title for c in chunks] == [f"doc.md › Long (part {n})" for n in range(1, len(chunks) + 1)]


def test_long_paragraphs_are_split_at_sentence_ends() -> None:
    doc = prose(sentences(40))
    chunks = chunk_document(doc, size_chars=200, overlap_chars=0)
    assert all(len(c.text) <= 200 for c in chunks)
    assert all(c.text.endswith(".") for c in chunks)
    seen = " ".join(c.text.replace("\n\n", " ") for c in chunks)
    assert seen == sentences(40)  # nothing lost, nothing duplicated


def test_overlap_repeats_the_last_whole_sentences_of_the_previous_chunk() -> None:
    doc = prose(sentences(40))
    chunks = chunk_document(doc, size_chars=200, overlap_chars=60)
    assert len(chunks) > 2
    for previous, current in zip(chunks, chunks[1:], strict=False):
        previous_sentences = split_sentences(previous.text.replace("\n\n", " "))
        current_sentences = split_sentences(current.text.replace("\n\n", " "))
        # The overlap is the last whole sentences of the previous chunk, as many as fit in 60 chars:
        # each sentence is 26 chars, so exactly two of them.
        shared = [s for s in current_sentences if s in previous_sentences]
        assert shared == previous_sentences[-2:]
        assert current_sentences[: len(shared)] == shared  # and they come first
        assert len(current.text) <= 200  # the overlap never pushes a chunk over the limit


def test_overlap_zero_means_no_repetition() -> None:
    doc = prose(sentences(40))
    chunks = chunk_document(doc, size_chars=200, overlap_chars=0)
    all_sentences = [s for c in chunks for s in split_sentences(c.text.replace("\n\n", " "))]
    assert len(all_sentences) == len(set(all_sentences)) == 40


def test_a_giant_sentence_is_hard_split_at_word_boundaries() -> None:
    words = " ".join(f"word{i}" for i in range(200))  # no punctuation anywhere
    chunks = chunk_document(prose(words), size_chars=100, overlap_chars=0)
    assert len(chunks) > 1
    assert all(len(c.text) <= 100 for c in chunks)
    assert " ".join(c.text for c in chunks) == words


# ----------------------------------------------------------------- code


def python_module(functions: int) -> str:
    blocks = [f"def func_{i}(x):\n    y = x + {i}\n    return y * 2\n" for i in range(functions)]
    return "\n".join(blocks)


def test_code_windows_break_at_blank_lines_and_column_zero() -> None:
    text = python_module(20)
    lines = text.splitlines()
    windows = code_windows(lines, size=200)
    assert windows[0][0] == 0 and windows[-1][1] == len(lines)
    for (_, end_a), (start_b, _) in zip(windows, windows[1:], strict=False):
        assert end_a == start_b  # contiguous
        assert lines[start_b].startswith("def ")  # never cut inside a function body
    for start, end in windows:
        assert len("\n".join(lines[start:end])) <= 200


def test_code_chunk_titles_give_line_ranges() -> None:
    doc = code(python_module(20), title="src/app.py")
    chunks = chunk_document(doc, size_chars=200, overlap_chars=50)
    assert chunks[0].title.startswith("src/app.py (lines 1-")
    assert all(c.title.startswith("src/app.py (lines ") for c in chunks)
    assert all(len(c.text) <= 200 for c in chunks)
    # Line ranges follow each other without gaps.
    ranges = [c.title.split("lines ")[1].rstrip(")").split("-") for c in chunks]
    for (_, end_a), (start_b, _) in zip(ranges, ranges[1:], strict=False):
        assert int(start_b) == int(end_a) + 1


def test_code_handles_a_single_enormous_line() -> None:
    doc = code("x = [" + ", ".join(str(i) for i in range(500)) + "]")
    chunks = chunk_document(doc, size_chars=300, overlap_chars=0)
    assert len(chunks) == 1  # one line cannot be split by lines; we keep it whole rather than lose it
    assert chunks[0].title == "app.py (lines 1-1)"


def test_small_code_file_is_one_chunk() -> None:
    doc = code("print('hi')\n", title="hi.py")
    chunks = chunk_document(doc, size_chars=1500, overlap_chars=150)
    assert [(c.title, c.text) for c in chunks] == [("hi.py (lines 1-1)", "print('hi')")]


# ----------------------------------------------------------- ordinals etc.


def test_ordinals_continue_across_documents() -> None:
    docs = [prose(sentences(20), "a.md"), code(python_module(10), "b.py"), prose("Short.", "c.md")]
    chunks = chunk_documents(docs, size_chars=200, overlap_chars=0)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert chunks[-1].title == "c.md"
    assert len(chunks) > 3


def test_chunking_is_deterministic() -> None:
    doc = prose(SAMPLE.read_text(), title="acme_robotics.md")
    first = chunk_document(doc, 400, 100)
    second = chunk_document(doc, 400, 100)
    assert first == second


def test_empty_document_gives_no_chunks() -> None:
    assert chunk_document(prose("   \n  "), 500, 50) == []
    assert chunk_document(code(""), 500, 50) == []


def test_a_markdown_h1_names_the_document_and_a_file_without_one_keeps_its_file_name():
    from hippo.ingest.chunker import document_title
    from hippo.ingest.readers import Document

    with_h1 = Document(
        title="notes.md", text="\n# Field Guide\n\n## Part one\n\nText.", path="notes.md", is_code=False
    )
    assert document_title(with_h1) == "Field Guide"
    assert chunk_document(with_h1, 1500, 100)[0].title == "Field Guide › Part one"
    without = Document(title="notes.md", text="## Part one\n\nText.", path="notes.md", is_code=False)
    assert document_title(without) == "notes.md"
    assert chunk_document(without, 1500, 100)[0].title == "notes.md › Part one"
