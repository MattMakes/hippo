"""Tests for hippo.ingest.chunker: sizes, overlap, headings, code windows, ordinals."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hippo.codegraph import extract_code
from hippo.hipporag.indexer import Chunk
from hippo.ingest.chunker import (
    chunk_document,
    chunk_documents,
    code_windows,
    split_sections,
    split_sentences,
)
from hippo.ingest.readers import Document
from tests.conftest import CODE_SAMPLE_PATH, code_sample_docs

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "acme_robotics.md"
FIXTURE_SOURCE = "fixture"


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


# ------------------------------------------------------ one passage per symbol
#
# With a `CodeGraph` in hand the chunker stops cutting a parsed file into line windows and
# cuts it by symbol instead (PLAN 2.3). These tests pin the exact titles, the placeholder
# lines a header keeps in place of its members, and the three-valued `extract_text` (S2.7).

ORDERS = "pyapp/orders.py"


@pytest.fixture(scope="module")
def code_graph():
    """The fixture tree's code graph. Extraction is pure, so one per module is plenty."""
    return extract_code(code_sample_docs(), FIXTURE_SOURCE)


def fixture_doc(path: str) -> Document:
    return Document(title=path, text=(CODE_SAMPLE_PATH / path).read_text(), path=path, is_code=True)


def chunks_of(path: str, code_graph, size: int = 1500) -> list[Chunk]:
    return chunk_document(fixture_doc(path), size_chars=size, overlap_chars=150, code=code_graph)


def test_a_parsed_file_becomes_one_passage_per_symbol_in_source_order(code_graph) -> None:
    assert [c.title for c in chunks_of(ORDERS, code_graph)] == [
        "pyapp/orders.py :: pyapp.orders (lines 1-8)",
        "pyapp/orders.py :: pyapp.orders.OrderService (lines 9-15)",
        "pyapp/orders.py :: pyapp.orders.OrderService.place (lines 16-23)",
        "pyapp/orders.py :: pyapp.orders.OrderService.log (lines 25-25)",
        "pyapp/orders.py :: pyapp.orders.OrderService.list_open (lines 27-28)",
        "pyapp/orders.py :: pyapp.orders.OrderService.save (lines 30-32)",
        "pyapp/orders.py :: pyapp.orders.OrderService.archive (lines 34-35)",
        "pyapp/orders.py :: pyapp.orders.OrderService.graph (lines 37-38)",
        "pyapp/orders.py :: pyapp.orders.OrderService.run (lines 40-40)",
    ]


def test_the_module_header_keeps_its_own_lines_and_a_placeholder_for_each_member(code_graph) -> None:
    header = chunks_of(ORDERS, code_graph)[0]
    assert header.text.splitlines()[:4] == [
        "import os",
        "from . import billing",
        "from .billing import send_invoice as invoice",
        "from pyapp.store import Base, OrderError",
    ]
    assert 'DEFAULT_STATUS = "open"' in header.text
    assert "class OrderService(Base): ...  # lines 9-40" in header.text
    assert "def place" not in header.text  # the body lives in its own passage, not here


def test_the_class_header_keeps_its_own_lines_and_a_placeholder_for_each_method(code_graph) -> None:
    klass = chunks_of(ORDERS, code_graph)[1]
    assert klass.text.startswith("class OrderService(Base):")
    assert '__tablename__ = "orders"' in klass.text
    assert "    def place(self, order): ...  # lines 16-23" in klass.text
    assert "    def run(self, sql): ...  # lines 40-40" in klass.text
    assert "billing.total(order)" not in klass.text


def test_a_typescript_header_uses_a_line_comment_placeholder(code_graph) -> None:
    module = chunks_of("tsapp/models/order.ts", code_graph)[0]
    assert "class Order extends Base { ... }  // lines 7-11" in module.text
    assert "OrderModel = mongoose.model" in module.text  # module-level code after the members


def test_every_passage_defines_its_symbol_and_the_data_objects_it_names(code_graph) -> None:
    from hippo.codegraph.model import data_id, symbol_id

    defines = {c.title: c.defines for c in chunks_of(ORDERS, code_graph)}
    orders_table = data_id(FIXTURE_SOURCE, "table", "orders")
    assert defines["pyapp/orders.py :: pyapp.orders (lines 1-8)"] == [
        symbol_id(FIXTURE_SOURCE, ORDERS, "pyapp.orders")
    ]
    # `__tablename__ = "orders"` sits on line 14, inside the class header, not inside a method.
    assert defines["pyapp/orders.py :: pyapp.orders.OrderService (lines 9-15)"] == [
        symbol_id(FIXTURE_SOURCE, ORDERS, "OrderService"),
        orders_table,
    ]
    assert defines["pyapp/orders.py :: pyapp.orders.OrderService.list_open (lines 27-28)"] == [
        symbol_id(FIXTURE_SOURCE, ORDERS, "OrderService.list_open"),
        orders_table,
    ]
    assert defines["pyapp/orders.py :: pyapp.orders.OrderService.archive (lines 34-35)"] == [
        symbol_id(FIXTURE_SOURCE, ORDERS, "OrderService.archive"),
        data_id(FIXTURE_SOURCE, "collection", "archive_orders"),
    ]
    # Data ids follow the symbol in a stable (kind, qualname) order, so a passage's `defines`
    # never depends on the order the extractor happened to see the literals in.
    assert defines["pyapp/orders.py :: pyapp.orders.OrderService.graph (lines 37-38)"] == [
        symbol_id(FIXTURE_SOURCE, ORDERS, "OrderService.graph"),
        data_id(FIXTURE_SOURCE, "label", "Customer"),
        data_id(FIXTURE_SOURCE, "label", "Order"),
        data_id(FIXTURE_SOURCE, "rel_type", "PLACED_BY"),
    ]


def test_the_mention_index_dedupes_a_span_and_keeps_the_kind_qualname_order(code_graph) -> None:
    """
    AR1 fix 7. `_data_ids_in` used to rescan every data object, and every mention of each, for
    every passage; it now looks a `(path, line)` index up. Same answer: one id per object however
    many of the span's lines name it, still in the global `(kind, qualname)` order rather than the
    order the span's lines happen to be in.
    """
    from hippo.codegraph.model import data_id
    from hippo.ingest.chunker import _data_ids_in, _mention_index

    mentions = _mention_index(code_graph)
    orders = data_id(FIXTURE_SOURCE, "table", "orders")
    named_on = sorted(
        line for (path, line), ids in mentions.items() if path == ORDERS and orders in dict(ids).values()
    )
    assert len(named_on) > 1, "`orders` is named on several lines of pyapp/orders.py"
    assert _data_ids_in(mentions, ORDERS, set(named_on)) == [orders]

    # The graph method names one label on its first line and two more on its second; the ids come
    # back sorted by (kind, qualname), not by the line that mentioned them.
    assert _data_ids_in(mentions, ORDERS, set(range(37, 39))) == [
        data_id(FIXTURE_SOURCE, "label", "Customer"),
        data_id(FIXTURE_SOURCE, "label", "Order"),
        data_id(FIXTURE_SOURCE, "rel_type", "PLACED_BY"),
    ]
    assert _data_ids_in(mentions, ORDERS, set()) == []
    assert _data_ids_in(_mention_index(None), ORDERS, {1, 2, 3}) == []


def test_extract_text_is_the_doc_when_it_is_long_enough_and_empty_otherwise(code_graph) -> None:
    """S2.7: OpenIE never sees a function body. A short doc is '' (skip), never None (extract)."""
    by_title = {c.title: c.extract_text for c in chunks_of(ORDERS, code_graph)}
    klass = by_title["pyapp/orders.py :: pyapp.orders.OrderService (lines 9-15)"]
    assert klass.startswith("Keeps orders. Acme Robotics is headquartered in Boulder.")
    place = by_title["pyapp/orders.py :: pyapp.orders.OrderService.place (lines 16-23)"]
    assert place.startswith("Place an order: total it with billing")
    assert by_title["pyapp/orders.py :: pyapp.orders (lines 1-8)"] == ""  # no module docstring
    assert by_title["pyapp/orders.py :: pyapp.orders.OrderService.save (lines 30-32)"] == ""
    assert all(text is not None for text in by_title.values())


def test_a_short_doc_comment_is_dropped_rather_than_shrunk(code_graph) -> None:
    short = chunks_of("pyapp/billing.py", code_graph)[0]
    assert short.title == "pyapp/billing.py :: pyapp.billing (lines 1-3)"
    assert short.extract_text == ""  # "Billing helpers." is under MIN_OPENIE_DOC_CHARS


def test_a_file_that_opens_with_a_class_has_no_header_passage(code_graph) -> None:
    from hippo.codegraph.model import symbol_id

    chunks = chunks_of("pyapp/store.py", code_graph)
    assert [c.title for c in chunks] == [
        "pyapp/store.py :: pyapp.store.Base (lines 1-3)",
        "pyapp/store.py :: pyapp.store.Base.log (lines 4-5)",
        "pyapp/store.py :: pyapp.store.OrderError (lines 8-9)",
    ]
    # The module symbol still needs a passage of its own: a code node no visible passage
    # reaches is invisible to a scoped graph (S2.5). The top of the file is that passage.
    assert chunks[0].defines == [
        symbol_id(FIXTURE_SOURCE, "pyapp/store.py", "pyapp.store"),
        symbol_id(FIXTURE_SOURCE, "pyapp/store.py", "Base"),
    ]


def test_a_sql_file_keeps_line_windows_but_defines_its_tables_and_skips_openie(code_graph) -> None:
    from hippo.codegraph.model import data_id

    (chunk,) = chunks_of("schema/orders.sql", code_graph)
    assert chunk.title == "schema/orders.sql (lines 1-2)"
    assert chunk.extract_text == ""  # never OpenIE over DDL
    assert data_id(FIXTURE_SOURCE, "table", "orders") in chunk.defines
    assert data_id(FIXTURE_SOURCE, "column", "orders.total") in chunk.defines
    assert data_id(FIXTURE_SOURCE, "table", "customers") in chunk.defines


def test_a_code_file_with_no_grammar_is_chunked_exactly_as_before(code_graph) -> None:
    """Ruby has no grammar and no walker, so `tools/build.rb` keeps today's line windows.
    `tools/build.go` used to play this part and is a parsed Go file now."""
    (chunk,) = chunks_of("tools/build.rb", code_graph)
    assert chunk.title == "tools/build.rb (lines 1-3)"
    assert chunk.extract_text is None and chunk.defines == []  # OpenIE as today


def test_an_oversized_body_splits_at_statement_starts_with_only_part_one_extracting() -> None:
    doc = code(
        'def big():\n    """'
        + "Long docstring. " * 8
        + '"""\n'
        + "\n".join(f"    x{i} = {i}" for i in range(200))
        + "\n",
        title="big.py",
    )
    graph = extract_code([doc], FIXTURE_SOURCE)
    chunks = chunk_document(doc, size_chars=500, overlap_chars=0, code=graph)

    assert len(chunks) > 3
    assert chunks[0].title.startswith("big.py :: big.big (lines 1-")
    assert chunks[0].title.endswith("(part 1)")
    assert [c.extract_text != "" for c in chunks] == [True] + [False] * (len(chunks) - 1)
    assert all(c.defines == chunks[0].defines for c in chunks)  # DEFINED_IN from every part

    covered: list[int] = []
    for chunk in chunks:
        first, last = chunk.title.split("(lines ")[1].split(")")[0].split("-")
        covered.extend(range(int(first), int(last) + 1))
    assert covered == list(range(1, 203))  # every line once, in order


def test_chunk_document_without_a_code_graph_is_unchanged(code_graph) -> None:
    doc = fixture_doc(ORDERS)
    assert chunk_document(doc, 1500, 150) == chunk_document(doc, 1500, 150, code=None)
    assert [c.title for c in chunk_document(doc, 1500, 150)] == ["pyapp/orders.py (lines 1-40)"]


def test_chunk_documents_numbers_symbol_passages_continuously(code_graph) -> None:
    docs = [fixture_doc(ORDERS), prose("Boulder is located in Colorado.", "notes.md")]
    chunks = chunk_documents(docs, 1500, 150, code=code_graph)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert chunks[-1].title == "notes.md" and chunks[-1].extract_text is None


# --------------------------------------- members written outside their type (L3)
#
# Rust writes a type's methods in `impl` blocks of their own and Go writes them as
# `func (s *Service) Place()`, so a member's lines are nowhere near its type's. The type's
# header is then exactly its own lines plus one placeholder per member, wherever that member
# is written, and the *module* header stands in for every symbol range in the file, whatever
# its kind and owner -- which is what keeps every line in exactly one passage. The rule is
# language-agnostic: these cases are Rust because that walker is merged, and the Go shape
# (`type Service struct` at the top, its methods further down) reaches the same code.

RUST_ORDERS = """use crate::billing;

/// Keeps orders for one customer.
pub struct OrderService {
    pub open: i64,
}

impl OrderService {
    /// Place an order and return its identifier.
    pub fn place(&self, order: &Order) -> i64 {
        billing::total(order)
    }
}

impl Base for OrderService {
    fn log(&self, message: &str) {
        println!("{}", message);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn place_totals() {
        let service = OrderService { open: 0 };
        assert_eq!(service.place(&Order {}), 0);
    }
}
"""

# `sig { ... }  // lines a-b`: a placeholder stands in for a range, it does not print it.
PLACEHOLDER_RE = re.compile(r"(?://|#) lines \d+-\d+$")


def rust_chunks(text: str, title: str = "src/orders.rs", size: int = 1500) -> list[Chunk]:
    doc = Document(title=title, text=text, path=title, is_code=True)
    graph = extract_code([doc], FIXTURE_SOURCE)
    return chunk_documents([doc], size_chars=size, overlap_chars=150, code=graph)


def printed_lines(chunks: list[Chunk]) -> list[str]:
    """Every source line the passages print, placeholders aside. Blank lines are boundaries."""
    return [
        line
        for chunk in chunks
        for line in chunk.text.splitlines()
        if line.strip() and not PLACEHOLDER_RE.search(line)
    ]


def test_a_type_whose_methods_live_outside_it_gets_a_passage_per_symbol_in_order() -> None:
    chunks = rust_chunks(RUST_ORDERS)
    assert [c.title for c in chunks] == [
        "src/orders.rs :: src.orders (lines 1-19)",
        "src/orders.rs :: src.orders.OrderService (lines 4-6)",  # its own lines, not up to `place`
        "src/orders.rs :: src.orders.OrderService.place (lines 10-12)",
        "src/orders.rs :: src.orders.OrderService.log (lines 16-18)",
        "src/orders.rs :: src.orders.tests (lines 21-30)",
        "src/orders.rs :: src.orders.tests.place_totals (lines 25-29)",
    ]
    assert [c.ordinal for c in chunks] == list(range(6))


def test_every_line_of_such_a_file_is_printed_exactly_once() -> None:
    chunks = rust_chunks(RUST_ORDERS)
    source = [line for line in RUST_ORDERS.splitlines() if line.strip()]
    assert sorted(printed_lines(chunks)) == sorted(source)  # no line printed twice, none lost
    assert len(printed_lines(chunks)) == len(source)


def test_the_type_header_is_its_own_lines_and_a_placeholder_per_method_wherever_it_lives() -> None:
    klass = rust_chunks(RUST_ORDERS)[1]
    assert klass.text.splitlines() == [
        "pub struct OrderService {",
        "    pub open: i64,",
        "}",
        # Both impl blocks are elsewhere in the file; the header still lists what they hold.
        "    pub fn place(&self, order: &Order) -> i64 { ... }  // lines 10-12",
        "    fn log(&self, message: &str) { ... }  // lines 16-18",
    ]
    assert "billing::total(order)" not in klass.text  # the body lives in its own passage


def test_the_module_header_stands_in_for_every_symbol_range_whatever_its_owner() -> None:
    module = rust_chunks(RUST_ORDERS)[0]
    assert "pub struct OrderService { ... }  // lines 4-6" in module.text
    # A method the module does not own still gets a placeholder here: its lines are the
    # module's own, and printing the body would repeat the passage that already holds it.
    assert "    pub fn place(&self, order: &Order) -> i64 { ... }  // lines 10-12" in module.text
    assert "    fn log(&self, message: &str) { ... }  // lines 16-18" in module.text
    assert "mod tests { ... }  // lines 21-30" in module.text
    assert "impl OrderService {" in module.text  # the impl's own lines belong to nobody else
    assert "billing::total(order)" not in module.text
    assert "assert_eq!" not in module.text


def test_an_inline_module_is_a_container_and_its_functions_get_their_own_passages() -> None:
    _, _, _, _, tests, place_totals = rust_chunks(RUST_ORDERS)
    assert tests.text.splitlines() == [
        "#[cfg(test)]",
        "mod tests {",
        "    use super::*;",
        "",
        "    fn place_totals() { ... }  // lines 25-29",
        "}",
    ]
    assert place_totals.text.startswith("    #[test]\n    fn place_totals() {")
    assert "assert_eq!(service.place(&Order {}), 0);" in place_totals.text


def test_a_member_that_opens_on_its_containers_own_line_leaves_the_container_the_header() -> None:
    """
    `mod tests { fn t() {}` starts both symbols on line 1 and the member ends first, so the
    two ranges are only ordered by width. The wider one stands in for the narrower -- the
    other way round would print the container's closing brace twice, once here and once in
    the member's own passage.
    """
    text = "mod tests { fn t() {}\n}\n"
    chunks = rust_chunks(text, title="src/compact.rs")
    assert [c.title for c in chunks] == [
        "src/compact.rs :: src.compact.tests (lines 1-2)",
        "src/compact.rs :: src.compact.tests.t (lines 1-1)",
    ]
    assert sorted(printed_lines(chunks)) == ["mod tests { fn t() {}", "}"]


def test_a_method_whose_type_is_declared_in_another_file_still_gets_a_passage() -> None:
    """
    L0d: Rust may write `impl Base for OrderService` in a module that declares neither type,
    so a member can have no owner in its own file. The module owns whatever nothing else
    does -- a symbol with no passage would be invisible to a scoped graph (S2.5).
    """
    text = (
        "use crate::orders::OrderService;\n\n"
        "impl Base for OrderService {\n"
        '    fn log(&self, message: &str) {\n        println!("{}", message);\n    }\n}\n'
    )
    chunks = rust_chunks(text, title="src/logging.rs")
    assert [c.title for c in chunks] == [
        "src/logging.rs :: src.logging (lines 1-7)",
        "src/logging.rs :: src.logging.OrderService.log (lines 4-6)",
    ]
    assert sorted(printed_lines(chunks)) == sorted(line for line in text.splitlines() if line.strip())


# ------------------------------------------------------- commit passages (WP2b)


def commit_graph(code_graph, count: int = 2):
    """The fixture's graph with a little history bolted on, as `read_history` would leave it."""
    from dataclasses import replace

    place = next(s for s in code_graph.symbols if s.qualname == "OrderService.place")
    save = next(s for s in code_graph.symbols if s.qualname == "OrderService.save")
    graph = replace(
        code_graph,
        commits=[
            {
                "id": f"commit-{i}",
                "source_id": FIXTURE_SOURCE,
                "sha": f"{i}" * 40,
                "author": "Hippo Fixture",
                "date": f"2024-01-0{i + 1}T09:00:00+00:00",
                "message": f"Subject {i}\n\nA body paragraph for commit {i}.",
                "ordinal": i,
            }
            for i in range(count)
        ],
        modifies=[
            {"commit_id": "commit-0", "symbol_id": place.id, "omega": 1.0, "hunk": {}},
            {"commit_id": "commit-0", "symbol_id": save.id, "omega": 1.0, "hunk": {}},
        ],
    )
    return graph, place, save


def test_each_commit_becomes_one_passage(code_graph) -> None:
    graph, place, save = commit_graph(code_graph)
    chunks = chunk_documents([fixture_doc(ORDERS)], 1500, 150, code=graph)
    commits = [c for c in chunks if c.title.startswith("commit ")]

    assert [c.title for c in commits] == [
        "commit 0000000000: Subject 0",  # sha[:10] and the message's first line
        "commit 1111111111: Subject 1",
    ]
    assert commits[0].defines == ["commit-0"]  # DEFINED_IN, so the commit node has a passage
    # The whole message, then what it touched -- by fully-qualified display name, the same name
    # the answer block and the path tools use, in the order MODIFIES came in.
    assert commits[0].text == (
        f"Subject 0\n\nA body paragraph for commit 0.\n\nTouched: {place.display}, {save.display}"
    )
    assert commits[1].text == "Subject 1\n\nA body paragraph for commit 1."  # touched nothing
    # OpenIE sees the message only, never the "Touched:" line: those are identifiers, and the
    # >= 80-char rule then skips a one-line commit message by itself (S2.7).
    assert commits[0].extract_text == "Subject 0\n\nA body paragraph for commit 0."


def test_commit_passages_come_after_the_files_and_keep_the_ordinal_run(code_graph) -> None:
    graph, _, _ = commit_graph(code_graph)
    chunks = chunk_documents(
        [fixture_doc(ORDERS), prose("Boulder is in Colorado.", "n.md")], 1500, 150, code=graph
    )
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert [c.title.startswith("commit ") for c in chunks][-2:] == [True, True]


def test_a_commit_that_touched_a_great_many_symbols_stays_one_readable_passage(code_graph) -> None:
    graph, _, _ = commit_graph(code_graph)
    graph.modifies = [
        {"commit_id": "commit-0", "symbol_id": s.id, "omega": 1.0, "hunk": {}} for s in code_graph.symbols
    ]
    (commit,) = [
        c for c in chunk_documents([], 300, 0, code=graph) if c.title == "commit 0000000000: Subject 0"
    ]
    assert len(commit.text) <= 300
    assert commit.text.rstrip().endswith("more)")  # says how many names were cut, never lies by omission


def test_a_graph_with_no_history_adds_no_commit_passages(code_graph) -> None:
    assert not [
        c
        for c in chunk_documents([fixture_doc(ORDERS)], 1500, 150, code=code_graph)
        if c.title.startswith("commit ")
    ]
