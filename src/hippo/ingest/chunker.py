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

Code with a symbol tree (a `CodeGraph` from `codegraph.extract_code`, PLAN 2.3):
  one passage per symbol instead of line windows — a module header holding the
  file's own lines with a placeholder for every symbol range in it, a class
  header holding its own lines with a placeholder for each method wherever that
  method is written (Rust's `impl OrderService { }` and Go's
  `func (s *Service) Place()` are outside the type), an inline module (Rust's
  `mod tests { }`) treated as a container like any class, and one passage per
  function or method, titled "path :: module.qualname (lines a-b)". A body too
  long for one passage splits at the top-level statements of that body into
  "(part N)". Each passage carries the ids it `defines` and an `extract_text`
  that keeps OpenIE off the body (S2.7). A `.sql` file keeps its line windows
  but still carries the tables it defines.

Ordinals: chunk_document numbers from 0; chunk_documents keeps counting across
all the documents of one source, so passage order is the order you read them.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..hipporag.indexer import MIN_OPENIE_DOC_CHARS, Chunk
from .readers import Document, lang_of

if TYPE_CHECKING:  # `codegraph` pulls tree-sitter in; the chunker only reads plain attributes
    from ..codegraph.model import CodeGraph, Symbol

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
MIN_CHUNK_CHARS = 50  # a safety net against 0 or negative sizes; real chunks are far bigger
# The symbol kinds that hold other symbols: a header passage of their own, then a passage per
# member. Rust's `mod tests { }` is one of these, so its cases are passages like any other.
CONTAINER_KINDS = ("class", "module")

# (line number or None for a placeholder, the text of that line).
Row = tuple[int | None, str]
# (title, text, defines, extract_text) - one passage before it is numbered.
Piece = tuple[str, str, list[str], str | None]

# (path, line) -> the data objects mentioned there, each with its (kind, qualname) rank.
Mentions = dict[tuple[str, int], list[tuple[int, str]]]


def chunk_documents(
    docs: list[Document], size_chars: int, overlap_chars: int, code: CodeGraph | None = None
) -> list[Chunk]:
    """
    Chunk every document, numbering the chunks continuously across the list.

    A repository's commits come last and are passages like any other, so they get an embedding,
    a DEFINED_IN link to their `Commit` node and -- because their `extract_text` is the message,
    which is prose -- REFERS_TO edges to the symbols the message names.
    """
    chunks: list[Chunk] = []
    mentions = _mention_index(code)  # once per source, not once per passage (AR1 fix 7)
    for doc in docs:
        for chunk in chunk_document(doc, size_chars, overlap_chars, code=code, mentions=mentions):
            chunk.ordinal = len(chunks)
            chunks.append(chunk)
    for chunk in _chunk_commits(code, size_chars):
        chunk.ordinal = len(chunks)
        chunks.append(chunk)
    return chunks


def _chunk_commits(code: CodeGraph | None, size_chars: int) -> list[Chunk]:
    """
    One passage per commit: the message, then the symbols the commit touched.

    The message is what OpenIE reads (`extract_text`) and the "Touched:" line is deliberately
    not part of it -- those are identifiers, and OpenIE over prose is what this pass is for.
    Names are the fully-qualified `display` form, the one the answer block, the path tools and
    the CLI all use, so a reader sees the same name everywhere.
    """
    if code is None or not code.commits:
        return []
    size = max(MIN_CHUNK_CHARS, size_chars)
    display = {s.id: s.display for s in code.symbols}
    touched: dict[str, list[str]] = {}
    for row in code.modifies:
        name = display.get(row["symbol_id"])
        if name is not None:
            touched.setdefault(row["commit_id"], []).append(name)

    chunks: list[Chunk] = []
    for commit in code.commits:
        message = (commit.get("message") or "").strip()
        subject = message.splitlines()[0] if message else commit["sha"][:10]
        names = touched.get(commit["id"], [])
        chunks.append(
            Chunk(
                ordinal=0,  # chunk_documents renumbers across the whole source
                title=f"commit {commit['sha'][:10]}: {subject}",
                text=_commit_text(message, names, size),
                defines=[commit["id"]],
                extract_text=message,
            )
        )
    return chunks


def _commit_text(message: str, names: list[str], size: int) -> str:
    """
    `message`, then `Touched: a, b, c` -- cut to fit the passage with a count of what was cut.

    A merge can touch hundreds of symbols, and a passage that long is neither readable nor
    embeddable. Cutting silently would make the passage quietly wrong about what the commit
    did, so the number that was dropped is part of the text.
    """
    if not names:
        return message
    header = f"{message}\n\nTouched: " if message else "Touched: "
    kept: list[str] = []
    for position, name in enumerate(names):
        more = len(names) - position - 1
        tail = f", … (+{more} more)" if more else ""
        if len(header) + len(", ".join([*kept, name])) + len(tail) > size:
            break
        kept.append(name)
    if len(kept) == len(names):
        return header + ", ".join(kept)
    if not kept:  # not even one name fits: say so rather than claim the commit touched nothing
        return f"{header}… ({len(names)} symbols)"[:size]
    return f"{header}{', '.join(kept)}, … (+{len(names) - len(kept)} more)"


def chunk_document(
    doc: Document,
    size_chars: int,
    overlap_chars: int,
    code: CodeGraph | None = None,
    mentions: Mentions | None = None,
) -> list[Chunk]:
    """
    Chunk one document; ordinals start at 0. Without `code` this is exactly today's chunker.

    `mentions` is `_mention_index(code)`, which `chunk_documents` builds once for the whole
    source; a caller with one document may leave it out and pay for it here.
    """
    size = max(MIN_CHUNK_CHARS, size_chars)
    overlap = max(0, min(overlap_chars, size // 3))  # overlap must leave room for new text
    if code is not None and code.parsed(doc.title):
        found = _mention_index(code) if mentions is None else mentions
        # A .sql file is parsed but has no symbols, so it branches on the language, not on
        # `parsed()`: its tables are data objects that no symbol owns.
        pieces = (
            _chunk_sql(doc, found, size)
            if lang_of(doc.title) == "sql"
            else _chunk_symbols(doc, code, found, size)
        )
    elif doc.is_code:
        pieces = [(title, text, [], None) for title, text in _chunk_code(doc, size)]
    else:
        pieces = [(title, text, [], None) for title, text in _chunk_prose(doc, size, overlap)]
    return [
        Chunk(ordinal=i, title=title, text=text, defines=defines, extract_text=extract)
        for i, (title, text, defines, extract) in enumerate(pieces)
    ]


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


# ------------------------------------------------------------ code symbols


def _chunk_symbols(doc: Document, code: CodeGraph, mentions: Mentions, size: int) -> list[Piece]:
    """
    One passage per symbol, in source order: the module header, then every top-level symbol;
    a class or inline module contributes its own header and then its members, wherever in the
    file those are written -- a Rust `impl OrderService { }` follows the type it belongs to,
    not the line it sits on. Every line of the file lands in exactly one passage, placeholders
    aside.
    """
    symbols = code.by_path(doc.title)
    module = _file_module(symbols)
    if module is None:  # parsed, but nothing to cut by: fall back to today's windows
        return [(title, text, [], None) for title, text in _chunk_code(doc, size)]
    pieces = _container_pieces(module, symbols, doc.text.splitlines(), doc, mentions, size)
    if pieces and not any(module.id in defines for _, _, defines, _ in pieces):
        # A file that opens with `class Base:` has no module header passage, so its module
        # symbol would have no DEFINED_IN at all -- and a code node reachable from no visible
        # passage is invisible to a scoped graph (S2.5). Its first passage is the top of the
        # file, so that is where the module is defined.
        title, text, defines, extract = pieces[0]
        pieces[0] = (title, text, [module.id, *defines], extract)
    return pieces


def _chunk_sql(doc: Document, mentions: Mentions, size: int) -> list[Piece]:
    """
    A `.sql` file keeps today's line windows -- it has no symbols to cut by -- but each window
    still defines the tables and columns declared in it, and OpenIE never sees DDL (S2.7).
    """
    lines = doc.text.splitlines()
    pieces: list[Piece] = []
    for first, last in code_windows(lines, size):
        text = "\n".join(lines[first:last]).strip("\n")
        if text.strip():
            span = set(range(first + 1, last + 1))
            title = f"{doc.title} (lines {first + 1}-{last})"
            pieces.append((title, text, _data_ids_in(mentions, doc.title, span), ""))
    return pieces


def _container_pieces(
    symbol: Symbol, symbols: list[Symbol], lines: list[str], doc: Document, mentions: Mentions, size: int
) -> list[Piece]:
    """
    The header passage of a module, class or inline module, then a passage per member.

    Members come grouped under their container, not in the file's own order: a Rust
    `impl OrderService` written below a top-level function still follows the type it
    belongs to, the way `class OrderService:` and its methods always have.
    """
    members = _members(symbol, symbols)
    rows = _header_rows(symbol, _placeholders(symbol, symbols, members), lines)
    pieces: list[Piece] = []
    if any(line is not None and text.strip() for line, text in rows):
        pieces.extend(_pieces_from_rows(symbol, rows, doc, mentions, size, header=True))
    for member in members:
        if member.kind in CONTAINER_KINDS:
            pieces.extend(_container_pieces(member, symbols, lines, doc, mentions, size))
        else:
            body = [(n, lines[n - 1]) for n in _line_numbers(member, lines)]
            pieces.extend(_pieces_from_rows(member, body, doc, mentions, size, header=False))
    return pieces


def _file_module(symbols: list[Symbol]) -> Symbol | None:
    """
    The symbol standing for the file itself, the one the whole file hangs off.

    Only it names its own module: every walker gives it `qualname == module`. Rust's inline
    `mod tests { ... }` is a `module` symbol too, but a member of one, so the first
    `module`-kind symbol is no longer the answer.
    """
    modules = [s for s in symbols if s.kind == "module"]
    return next((s for s in modules if s.qualname == s.module), modules[0] if modules else None)


def _members(parent: Symbol, symbols: list[Symbol]) -> list[Symbol]:
    """
    Direct members only, in source order -- wherever in the file they are written.

    A container owns the names one dot below its own, so `OrderService.place` is the type's
    method whether it is written inside `class OrderService:` or in a Rust
    `impl OrderService { }` further down the file (Go's `func (s *Service) Place` likewise).
    The file's module owns everything no other symbol owns: its top-level functions and
    types, an inline `mod`, and a method whose type is declared in another file -- which
    Rust allows, so nothing in the file is left without a passage.
    """
    module = _file_module(symbols)
    named = {s.qualname: s for s in symbols if s is not module}
    found = [s for s in symbols if s is not module and _owner(s, named, module) is parent]
    return sorted(found, key=lambda s: (s.line_start, s.line_end))


def _owner(symbol: Symbol, named: dict[str, Symbol], module: Symbol | None) -> Symbol | None:
    """The innermost symbol of this file whose qualname is a prefix of `symbol`'s, else the module."""
    name = symbol.qualname
    while "." in name:
        name = name.rpartition(".")[0]
        found = named.get(name)
        if found is not None and found is not symbol:
            return found
    return module


def _placeholders(symbol: Symbol, symbols: list[Symbol], members: list[Symbol]) -> list[Symbol]:
    """
    Every symbol the container's header stands in for, in source order.

    Its members, wherever they live, plus anything else written inside its own lines but
    belonging to something else -- the methods of a Rust `impl OrderService` are the module's
    lines and the type's members, and a header that skipped them would print a body that
    already has a passage of its own. Nested members are dropped by `_header_rows`, which
    walks in order and never doubles back.
    """
    module = _file_module(symbols)
    taken = {id(m) for m in members}
    inside = [
        s
        for s in symbols
        if id(s) not in taken
        and s is not symbol
        and s is not module
        and symbol.line_start <= s.line_start
        and s.line_end <= symbol.line_end
    ]
    return sorted([*members, *inside], key=lambda s: (s.line_start, s.line_end))


def _line_numbers(symbol: Symbol, lines: list[str]) -> range:
    """The symbol's own lines, 1-based and clamped to the file (a parser may over-reach by one)."""
    last = min(symbol.line_end, len(lines))
    return range(symbol.line_start, max(symbol.line_start, last) + 1)


def _header_rows(symbol: Symbol, members: list[Symbol], lines: list[str]) -> list[Row]:
    """
    The container's own lines, with one placeholder line standing in for each member.

    The walk never runs past the container's last line: a Rust `impl OrderService { }` or a
    Go `func (s *Service) Place()` puts a member outside the type it belongs to, and a type
    that swallowed the lines up to its first method would claim -- and print -- code that is
    not its own. Such a member still gets its placeholder, in the file's order, so the header
    lists every member wherever it lives. A member already inside an earlier placeholder's
    range (a method of a class of this module) is left to that placeholder.
    """
    rows: list[Row] = []
    cursor = symbol.line_start
    last = min(symbol.line_end, len(lines))
    covered = 0
    for member in members:
        if member.line_start <= covered:
            continue
        rows.extend((n, lines[n - 1]) for n in range(cursor, min(member.line_start, last + 1)))
        rows.append((None, _placeholder(member, lines)))
        cursor = max(cursor, member.line_end + 1)
        covered = max(covered, member.line_end)
    rows.extend((n, lines[n - 1]) for n in range(cursor, last + 1))
    return rows


def _line_comment(lang: str) -> str:
    """
    How this language starts a line comment, from the code-graph language registry.

    Imported inside the function on purpose: `codegraph.languages` pulls tree-sitter in, and
    the chunker must stay importable without it. Nothing reaches here except through a
    `code.parsed(...)` branch, by which point the extractor has already loaded it.
    """
    from ..codegraph.languages import RULES

    rules = RULES.get(lang)
    return rules.line_comment if rules is not None else "#"


def _placeholder(symbol: Symbol, lines: list[str]) -> str:
    """
    `class OrderService(Base): ...  # lines 9-40` -- what a member looks like from its container.

    The reader sees the shape of the file without its bodies, and the line range says where the
    real passage is. Indented like the member it replaces, so a class still reads as a class.
    """
    source = lines[symbol.line_start - 1] if symbol.line_start <= len(lines) else ""
    indent = source[: len(source) - len(source.lstrip())]
    comment = _line_comment(symbol.lang)
    body = f"{symbol.signature}: ..." if symbol.lang == "python" else f"{symbol.signature} {{ ... }}"
    return f"{indent}{body}  {comment} lines {symbol.line_start}-{symbol.line_end}"


def _pieces_from_rows(
    symbol: Symbol, rows: list[Row], doc: Document, mentions: Mentions, size: int, *, header: bool
) -> list[Piece]:
    """
    Turn one symbol's lines into passages -- one, or several `(part N)` when the body is too
    long. Every part defines the symbol (so DEFINED_IN reaches all of them) but only the first
    carries `extract_text`: the docstring must not be extracted once per part.
    """
    # Blank groups are dropped before the parts are numbered, so "(part 2)" always exists.
    groups = [g for g in _split_rows(rows, symbol.statement_lines, size) if _text_of(g).strip()]
    doc_text = symbol.doc if len(symbol.doc.strip()) >= MIN_OPENIE_DOC_CHARS else ""
    pieces: list[Piece] = []
    for number, group in enumerate(groups, start=1):
        text = _text_of(group)
        first, last = _title_range(symbol, group, header=header, split=len(groups) > 1)
        part = f" (part {number})" if len(groups) > 1 else ""
        title = f"{doc.title} :: {symbol.display} (lines {first}-{last}){part}"
        span = {line for line, _ in group if line is not None}
        defines = [symbol.id, *_data_ids_in(mentions, doc.title, span)]
        pieces.append((title, text, defines, doc_text if number == 1 else ""))
    return pieces


def _text_of(rows: list[Row]) -> str:
    return "\n".join(text for _, text in rows).strip("\n")


def _title_range(symbol: Symbol, group: list[Row], *, header: bool, split: bool) -> tuple[int, int]:
    """
    The line range a passage's title claims. A whole symbol claims its own range; a header
    claims up to `header_end` (its last line before the first member), stretched to cover any
    module-level code that follows the members; a part claims the lines it actually holds.
    """
    real = [line for line, _ in group if line is not None]
    if split:
        return (real[0], real[-1]) if real else (symbol.line_start, symbol.line_end)
    if not header:
        return symbol.line_start, symbol.line_end
    last = max((line for line, text in group if line is not None and text.strip()), default=symbol.line_start)
    return symbol.line_start, max(symbol.header_end, last)


def _split_rows(rows: list[Row], statement_lines: list[int], size: int) -> list[list[Row]]:
    """
    Cut an oversized passage at the start of one of the body's own statements, never mid-
    expression. A single statement longer than `size` is the one case that falls back to
    line windows, because there is no smaller boundary to use.
    """
    breaks = set(statement_lines)
    groups: list[list[Row]] = []
    current: list[Row] = []
    length = 0
    for line, text in rows:
        if current and line in breaks and length + len(text) + 1 > size:
            groups.append(current)
            current, length = [], 0
        current.append((line, text))
        length += len(text) + 1
    if current:
        groups.append(current)
    return [part for group in groups for part in _split_long_group(group, size)]


def _split_long_group(group: list[Row], size: int) -> list[list[Row]]:
    if len("\n".join(text for _, text in group)) <= size:
        return [group]
    return [group[first:last] for first, last in code_windows([text for _, text in group], size)]


def _mention_index(code: CodeGraph | None) -> Mentions:
    """
    `(path, line) -> the data objects mentioned there`, ranked by `(kind, qualname)`.

    Built once per call rather than per passage: `_data_ids_in` used to scan every data object,
    and every mention of each, for every piece it produced -- O(pieces x objects x mentions) per
    source, which on a SQL-heavy repository with one passage per symbol is real time (AR1 fix 7).
    The rank travels with the id so a span's ids keep the global `(kind, qualname)` order rather
    than the order its lines happen to be in.
    """
    index: Mentions = {}
    if code is None:
        return index
    for rank, data in enumerate(sorted(code.data_objects, key=lambda d: (d.kind, d.qualname))):
        for path, line in data.mentions:
            index.setdefault((path, line), []).append((rank, data.id))
    return index


def _data_ids_in(mentions: Mentions, path: str, lines: set[int]) -> list[str]:
    """
    The data objects this passage's own lines name, in a stable `(kind, qualname)` order.

    A data object is mentioned wherever a literal names it, so `table orders` is defined by the
    `.sql` file, by `__tablename__` in the class header and by each query that reads it -- which
    is what keeps it visible when one of those files is hidden (S2.5).
    """
    found = {pair for line in lines for pair in mentions.get((path, line), ())}
    return [data_id for _rank, data_id in sorted(found)]
