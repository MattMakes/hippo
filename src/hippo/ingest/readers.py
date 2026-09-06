"""
Turning files into plain text.

Whatever you give hippo (a PDF, a Word file, an e-book, a web page, a source
file, a zip of any of those) ends up as one or more `Document`s: a title, the
text, and a flag saying whether the text is code (code is chunked by lines,
prose by paragraphs; see chunker.py).

Rules of thumb used here:

* Rich formats (.pdf .docx .epub .html) get a small dedicated reader.
* Anything with a known text/code extension is read as UTF-8.
* A file with *no* extension is accepted if it decodes as UTF-8 and has no
  NUL bytes (a README, a Makefile, a LICENSE...). Everything else is skipped.
* Inside zips we ignore the usual junk folders (.git, node_modules, ...),
  hidden folders, and anything bigger than MAX_FILE_BYTES.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .html_text import html_to_text

log = logging.getLogger(__name__)

IGNORED_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
    "vendor",
}
MAX_FILE_BYTES = 2_000_000

# Prose: chunked by headings/paragraphs/sentences.
PROSE_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".text"}
# Rich formats with their own reader.
RICH_EXTENSIONS = {".pdf", ".docx", ".epub", ".html", ".htm"}
# Code and config: chunked by lines. Generous on purpose; the cost of a wrong
# guess is only a slightly odd chunk boundary.
CODE_EXTENSIONS = {
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".kts",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".cs", ".rb", ".php", ".swift", ".scala", ".m",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".sql", ".r", ".jl", ".lua", ".pl", ".pm", ".ex",
    ".exs", ".erl", ".hs", ".ml", ".clj", ".dart", ".groovy", ".gradle", ".cmake", ".mk", ".makefile",
    ".yaml", ".yml", ".toml", ".json", ".jsonl", ".xml", ".css", ".scss", ".sass", ".less", ".ini",
    ".cfg", ".conf", ".properties", ".proto", ".graphql", ".tf", ".hcl", ".vue", ".svelte",
    ".csv", ".tsv", ".dockerfile", ".lock",
}  # fmt: skip
# Extensionless files that we know are text.
KNOWN_TEXT_NAMES = {"makefile", "dockerfile", "license", "readme", "notice", "authors", "changelog"}

BINARY_SNIFF_BYTES = 8_000


@dataclass
class Document:
    """One readable thing: a file, a zip member, a pasted text."""

    title: str
    text: str
    path: str
    is_code: bool


class ReadError(ValueError):
    """The file exists but we could not get text out of it."""


# ------------------------------------------------------------- questions


def is_probably_binary(data: bytes) -> bool:
    """True when the start of `data` has NUL bytes or is not valid UTF-8."""
    head = data[:BINARY_SNIFF_BYTES]
    if b"\x00" in head:
        return True
    try:
        # A cut in the middle of a multi-byte character would look invalid, so
        # ignore a partial tail: decode with a tolerant fallback on the last bytes.
        head.decode("utf-8")
    except UnicodeDecodeError as err:
        return err.start < len(head) - 4
    return False


def is_code_name(name: str) -> bool:
    return _suffix(name) in CODE_EXTENSIONS


def is_supported_name(name: str) -> bool:
    """Decide by name alone (used for zip members, uploads and repo files)."""
    suffix = _suffix(name)
    if suffix in PROSE_EXTENSIONS or suffix in RICH_EXTENSIONS or suffix in CODE_EXTENSIONS:
        return True
    return suffix == "" and PurePosixPath(name).name.lower() in KNOWN_TEXT_NAMES


def is_supported(path: Path) -> bool:
    """True if `read_file` would try to read it. Extensionless files are sniffed for text."""
    if is_supported_name(path.name):
        return True
    if path.suffix or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            return not is_probably_binary(handle.read(BINARY_SNIFF_BYTES))
    except OSError:
        return False


# --------------------------------------------------------------- reading


def read_file(path: Path) -> list[Document]:
    """Read one file from disk. The document title is the file name."""
    return read_path(path, path.name)


def read_path(path: Path, title: str) -> list[Document]:
    """Like read_file, but you choose the title (repos use the path relative to the root)."""
    data = path.read_bytes()
    return read_bytes(data, title, path=str(path))


def read_bytes(data: bytes, name: str, path: str | None = None) -> list[Document]:
    """Read from memory. `name` decides the format (by extension) and becomes the title."""
    suffix = _suffix(name)
    where = path or name
    if suffix == ".pdf":
        text = _read_pdf(data)
    elif suffix == ".docx":
        text = _read_docx(data)
    elif suffix == ".epub":
        text = _read_epub(data)
    elif suffix in (".html", ".htm"):
        text = html_to_text(_decode(data, strict=False))
    elif suffix in PROSE_EXTENSIONS or suffix in CODE_EXTENSIONS:
        if is_probably_binary(data):
            log.info("Skipping %s: looks binary", where)
            return []
        text = _decode(data, strict=False)
    else:
        # No known extension: accept only clean UTF-8 text.
        if is_probably_binary(data):
            return []
        text = _decode(data, strict=True)
    text = text.strip()
    if not text:
        return []
    return [Document(title=name, text=text, path=where, is_code=suffix in CODE_EXTENSIONS)]


def read_zip(path: Path, name: str) -> list[Document]:
    """Read every supported member of a zip. Titles are the member paths inside the archive."""
    docs: list[Document] = []
    with zipfile.ZipFile(path) as archive:
        for member in sorted(archive.infolist(), key=lambda m: m.filename):
            if not _wanted_zip_member(member):
                continue
            try:
                data = archive.read(member)
                docs.extend(read_bytes(data, member.filename, path=f"{name}:{member.filename}"))
            except Exception as err:  # noqa: BLE001 - one broken member must not sink the archive
                log.warning("Skipping %s in %s: %s", member.filename, name, err)
    return docs


def _wanted_zip_member(member: zipfile.ZipInfo) -> bool:
    if member.is_dir() or member.file_size > MAX_FILE_BYTES:
        return False
    parts = PurePosixPath(member.filename).parts
    if any(p in IGNORED_DIRS or p.startswith(".") or p == "__MACOSX" for p in parts[:-1]):
        return False
    if parts[-1].startswith(".") and not is_supported_name(parts[-1]):
        return False
    return is_supported_name(parts[-1])


# --------------------------------------------------------- rich formats


def _read_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")  # many "encrypted" PDFs just have an empty owner password
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as err:  # pypdf raises many different types
        raise ReadError(f"could not read PDF: {err}") from err
    return "\n\n".join(p for p in pages if p)


def _read_docx(data: bytes) -> str:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as err:
        raise ReadError(f"could not read .docx: {err}") from err
    blocks: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        # Turn Word headings into markdown headings so the chunker can split on them.
        level = _heading_level(paragraph.style.name if paragraph.style is not None else "")
        blocks.append(f"{'#' * level} {text}" if level else text)
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                blocks.append(" | ".join(cells))
    return "\n\n".join(blocks)


def _heading_level(style_name: str) -> int:
    if style_name.lower() == "title":
        return 1
    if style_name.lower().startswith("heading"):
        digits = "".join(ch for ch in style_name if ch.isdigit())
        return min(int(digits), 6) if digits else 2
    return 0


def _read_epub(data: bytes) -> str:
    """An epub is a zip of XHTML chapters; read them in reading (spine) order."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as book:
            chapters = _epub_chapter_names(book)
            texts = [html_to_text(_decode(book.read(name), strict=False)) for name in chapters]
    except zipfile.BadZipFile as err:
        raise ReadError(f"could not read .epub: {err}") from err
    return "\n\n".join(t for t in texts if t.strip())


def _epub_chapter_names(book: zipfile.ZipFile) -> list[str]:
    """Chapter file names in spine order; falls back to every html file, sorted."""
    import xml.etree.ElementTree as ET

    names = book.namelist()
    opf_name = next((n for n in names if n.lower().endswith(".opf")), None)
    ordered: list[str] = []
    if opf_name:
        try:
            root = ET.fromstring(book.read(opf_name))
            base = PurePosixPath(opf_name).parent
            hrefs = {
                item.get("id"): str(base / item.get("href", ""))
                for item in root.iter()
                if item.tag.endswith("item") and item.get("id")
            }
            for ref in root.iter():
                if ref.tag.endswith("itemref") and ref.get("idref") in hrefs:
                    ordered.append(hrefs[ref.get("idref")].lstrip("./"))
        except ET.ParseError:
            ordered = []
    known = set(names)
    ordered = [n for n in ordered if n in known]
    if ordered:
        return ordered
    return sorted(n for n in names if _suffix(n) in (".html", ".htm", ".xhtml", ".xml"))


# --------------------------------------------------------------- helpers


def _suffix(name: str) -> str:
    return PurePosixPath(name).suffix.lower()


def _decode(data: bytes, *, strict: bool) -> str:
    """UTF-8 (with or without BOM). Non-strict mode replaces bad bytes instead of failing."""
    return data.decode("utf-8-sig", errors="strict" if strict else "replace")
