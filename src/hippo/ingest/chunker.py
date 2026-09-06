"""
Cutting documents into passages ("chunks") of a comfortable size.

Why chunk at all: the language model reads a handful of passages when it
answers, and it extracts facts from one passage at a time, so each passage
must be small (default 1500 characters, about 350 tokens) yet still make
sense on its own.

Prose (markdown, text, PDFs...):
  1. split on markdown headings; each section is titled "Doc › Heading"
  2. pack whole paragraphs into chunks no longer than `size_chars`
  3. a paragraph that is too long is split at sentence ends
  4. each chunk after the first starts with the tail of the previous one
     (whole sentences, at most `overlap_chars`) so a fact cut in half is still
     seen whole somewhere
  5. when a section needs several chunks they are titled "Title (part N)"

Code (anything readers.py marks is_code):
  windows of whole lines, breaking preferably at a blank line or at a line
  that starts in column 0 (usually a new function/class); titled
  "path (lines a-b)". No overlap: the line ranges say exactly what is where.

Ordinals: chunk_document numbers from 0; chunk_documents keeps counting across
all the documents of one source, so passage order is the order you read them.
"""

from __future__ import annotations

import re

from ..hipporag.indexer import Chunk
from .readers import Document

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
MIN_CHUNK_CHARS = 50  # a safety net against 0 or negative sizes; real chunks are far bigger


def chunk_documents(docs: list[Document], size_chars: int, overlap_chars: int) -> list[Chunk]:
    """Chunk every document, numbering the chunks continuously across the list."""
    chunks: list[Chunk] = []
    for doc in docs:
        for chunk in chunk_document(doc, size_chars, overlap_chars):
            chunk.ordinal = len(chunks)
            chunks.append(chunk)
    return chunks


def chunk_document(doc: Document, size_chars: int, overlap_chars: int) -> list[Chunk]:
    """Chunk one document; ordinals start at 0."""
    size = max(MIN_CHUNK_CHARS, size_chars)
    overlap = max(0, min(overlap_chars, size // 3))  # overlap must leave room for new text
    if doc.is_code:
        texts_and_titles = _chunk_code(doc, size)
    else:
        texts_and_titles = _chunk_prose(doc, size, overlap)
    return [Chunk(ordinal=i, title=title, text=text) for i, (title, text) in enumerate(texts_and_titles)]


# ------------------------------------------------------------------ prose


def _chunk_prose(doc: Document, size: int, overlap: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    doc_title = document_title(doc)
    for heading, body in split_sections(doc.text):
        title = f"{doc_title} › {heading}" if heading and heading != doc_title else doc_title
        pieces = pack_paragraphs(body, size, overlap)
        if len(pieces) == 1:
            out.append((title, pieces[0]))
        else:
            out.extend((f"{title} (part {n})", piece) for n, piece in enumerate(pieces, start=1))
    return out


def document_title(doc: Document) -> str:
    """A markdown file that starts with a '# Heading' is called by that heading, not by its file name."""
    for line in doc.text.splitlines():
        if not line.strip():
            continue
        match = re.match(r"^#\s+(.+?)\s*#*\s*$", line)
        return match.group(1).strip() if match else doc.title
    return doc.title


def split_sections(text: str) -> list[tuple[str | None, str]]:
    """Split markdown on heading lines. Returns (heading or None, body) pairs; empty bodies are dropped."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    in_code_block = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code_block = not in_code_block  # a "# comment" inside a code block is not a heading
        match = None if in_code_block else HEADING_RE.match(line)
        if match:
            sections.append((match.group(2).strip(), []))
        else:
            sections[-1][1].append(line)
    result = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if body:
            result.append((heading, body))
    return result


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def split_sentences(text: str) -> list[str]:
    """Split at sentence ends. Text without punctuation comes back as one sentence."""
    return [s.strip() for s in SENTENCE_END_RE.split(text) if s.strip()]


def pack_paragraphs(text: str, size: int, overlap: int) -> list[str]:
    """Pack paragraphs (and, for long ones, sentences) into chunks of at most `size` characters."""
    units: list[str] = []
    for paragraph in split_paragraphs(text):
        if len(paragraph) <= size:
            units.append(paragraph)
        else:
            units.extend(_split_long_paragraph(paragraph, size))
    return _pack(units, size, overlap)


def _split_long_paragraph(paragraph: str, size: int) -> list[str]:
    """Sentences, and hard cuts for a sentence that alone is longer than `size`."""
    units: list[str] = []
    for sentence in split_sentences(paragraph):
        if len(sentence) <= size:
            units.append(sentence)
        else:
            units.extend(_hard_split(sentence, size))
    return units


def _hard_split(text: str, size: int) -> list[str]:
    """Cut a very long run of text at word boundaries, `size` characters at a time."""
    pieces: list[str] = []
    rest = text
    while len(rest) > size:
        cut = rest.rfind(" ", size // 2, size)
        if cut == -1:
            cut = size
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def _pack(units: list[str], size: int, overlap: int) -> list[str]:
    """Greedy: keep adding units while the chunk stays under `size`; then start a new chunk with an overlap."""
    chunks: list[str] = []
    current: list[str] = []  # the chunk being built; its first item may be the overlap tail
    new_units = 0  # how many of `current` are real (non-overlap) units
    for unit in units:
        if new_units and _joined_len(current + [unit]) > size:
            chunks.append(_join(current))
            tail = _overlap_tail(chunks[-1], overlap)
            # Skip the overlap when it would push this chunk over the size limit.
            current = tail if _joined_len(tail + [unit]) <= size else []
            new_units = 0
        current.append(unit)
        new_units += 1
    if current:
        chunks.append(_join(current))
    return chunks


def _join(units: list[str]) -> str:
    return "\n\n".join(units)  # a blank line between paragraphs, like the source


def _joined_len(units: list[str]) -> int:
    return len(_join(units))


def _overlap_tail(chunk: str, overlap: int) -> list[str]:
    """The last whole sentences of `chunk`, together at most `overlap` characters. Empty when overlap is 0."""
    if overlap <= 0:
        return []
    sentences = split_sentences(chunk.replace("\n", " "))
    tail: list[str] = []
    length = 0
    for sentence in reversed(sentences):
        if length + len(sentence) + (1 if tail else 0) > overlap:
            break
        tail.insert(0, sentence)
        length += len(sentence) + 1
    return [" ".join(tail)] if tail else []


# ------------------------------------------------------------------- code


def _chunk_code(doc: Document, size: int) -> list[tuple[str, str]]:
    lines = doc.text.splitlines()
    out: list[tuple[str, str]] = []
    for first, last in code_windows(lines, size):
        text = "\n".join(lines[first:last]).strip("\n")
        if text.strip():
            out.append((f"{doc.title} (lines {first + 1}-{last})", text))
    return out


def code_windows(lines: list[str], size: int) -> list[tuple[int, int]]:
    """Return (start, end) line index pairs (end exclusive) whose text fits in `size` characters."""
    windows: list[tuple[int, int]] = []
    start = 0
    n = len(lines)
    while start < n:
        end = _fill_window(lines, start, size)
        if end < n:
            end = _nice_break(lines, start, end)
        windows.append((start, end))
        start = end
    return windows


def _fill_window(lines: list[str], start: int, size: int) -> int:
    """The largest `end` such that lines[start:end] fits; always at least start + 1 so we make progress."""
    total = 0
    end = start
    while end < len(lines):
        total += len(lines[end]) + 1
        if total > size and end > start:
            break
        end += 1
    return end


def _nice_break(lines: list[str], start: int, end: int) -> int:
    """Move `end` back to a blank line or a column-0 line, if one exists in the second half of the window."""
    lowest = start + max(1, (end - start) // 2)
    for i in range(end - 1, lowest, -1):
        if not lines[i].strip():
            return i + 1  # keep the blank line with the earlier window
    for i in range(end - 1, lowest, -1):
        if lines[i] and not lines[i][0].isspace():
            return i  # the column-0 line starts the next window
    return end
