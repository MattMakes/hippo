"""Immutable code and config provenance: the code-accepting sibling of the plain reader.

Pure preparation. No store handle, no model, no clock: the bytes arrive as an
argument, already captured, and every coordinate is derived from them alone.

The decode itself is not reimplemented here. `read_plain_provenance` already
decodes `CODE_EXTENSIONS` with replacement, everything else strictly, trims to the
legacy analysis text and maps every character back to its raw bytes, so this seam
delegates to it and parity with the prose lane is a property of the code rather
than of a test. `tests/unit/test_code_provenance.py` still compares 20,000 seeded
cases against it: that is a divergence guard for the day one of the two changes,
not a proof that two independent decoders happen to agree.

What this seam adds is the part the walkers and the chunker need and the plain
lane has no reason to carry: the language the code graph knows the file as,
decided by the walker's name table and never by sniffing content; whether the
file clears the parse rail; and complete-line locators addressed either by
analysis characters (the chunker) or by tree-sitter's UTF-8 byte offsets.

Plain prose inside a captured tree belongs to the prose lane and is refused here,
so a caller cannot silently record a README as a code original. Extensionless
text names (`README`, `Makefile`, `LICENSE`) and `go.mod` are accepted: they carry
no grammar but the Go walker reads `go.mod`, and the chunker keeps line windows
for the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..codegraph.model import CODE_MAX_FILE_BYTES
from ..knowledge.inputs import RawInput
from .provenance import (
    OriginalLines,
    OriginalSegment,
    OriginalUnit,
    ProvenanceDocument,
    ProvenanceRead,
    UnsupportedProvenanceFormat,
    read_plain_provenance,
)
from .readers import Document, TextBudget, is_plain_prose_name, lang_of

# Every language `codegraph` names, plus None for a config or unparsed text file.
CODE_LANGUAGES = ("csharp", "go", "python", "rust", "sql", "typescript")


class UnsupportedCodeFormat(UnsupportedProvenanceFormat):
    """Plain prose has its own original lane; this seam records no code unit for it."""


@dataclass(frozen=True, slots=True)
class CodeUnit:
    """One captured file, decoded once, ready for the walkers and the chunker.

    `original` addresses the untrimmed decoded file and is what locators are
    expressed in. `document` addresses the trimmed analysis text the parser and
    the chunker see. The two differ by `analysis_offset` characters.
    """

    input_key: str
    logical_path: str
    language: str | None
    is_code: bool
    parsable: bool
    original: OriginalUnit
    document: ProvenanceDocument

    def __post_init__(self) -> None:
        if type(self.original) is not OriginalUnit or type(self.document) is not ProvenanceDocument:
            raise ValueError("A code unit requires frozen original and analysis provenance")
        if not isinstance(self.input_key, str) or not self.input_key:
            raise ValueError("A code unit needs its accepted input key")
        if self.language is not None and self.language not in CODE_LANGUAGES:
            raise ValueError("Unknown code language")
        if type(self.is_code) is not bool or type(self.parsable) is not bool:
            raise ValueError("Code classification must be explicit")
        if self.logical_path != self.original.locator.path or self.input_key != self.original.input_key:
            raise ValueError("A code unit and its original must name one accepted input")
        # A captured file decodes to exactly one original region with nothing
        # generated, which is what makes the character offset below a constant.
        segments = self.document.segments
        if self.document.original_units != (self.original,) or len(segments) != 1:
            raise ValueError("A code unit maps one file to one original region")
        if type(segments[0]) is not OriginalSegment or segments[0].unit_key != self.original.unit_key:
            raise ValueError("A code unit cannot carry generated analysis text")

    @property
    def unit_key(self) -> str:
        return self.original.unit_key

    @property
    def analysis_text(self) -> str:
        return self.document.analysis_text

    @property
    def analysis_offset(self) -> int:
        """Where the trimmed analysis text starts inside the untrimmed original."""
        return self.document.segments[0].start

    def lines_for_analysis(self, start: int, end: int) -> OriginalLines:
        """Expand an analysis character range to the whole original lines it touches."""
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise ValueError("Expected a nonempty analysis character range")
        if end > len(self.analysis_text):
            raise ValueError("Range exceeds the analysis text")
        offset = self.analysis_offset
        return self.original.complete_lines(offset + start, offset + end)

    def lines_for_parser_bytes(self, start: int, end: int) -> OriginalLines:
        """Expand a tree-sitter UTF-8 byte range in the analysis text to whole original lines.

        Offsets that fall inside a character are refused rather than rounded, so a
        Unicode source can never silently cite the wrong line.
        """
        segments = self.document.original_segments_for_bytes(start, end)
        if not segments or any(type(item) is not OriginalSegment for item in segments):
            raise ValueError("A parser range must address original code, never generated text")
        return self.original.complete_lines(
            min(item.start for item in segments), max(item.end for item in segments)
        )

    def to_document(self) -> Document:
        """A fresh legacy adapter for `extract_code`; mutating it cannot change provenance."""
        return self.document.to_document()


@dataclass(frozen=True, slots=True)
class CodeProvenance:
    """What one captured file decoded to, including the outcomes that produce no unit."""

    outcome: Literal["text", "empty", "binary"]
    language: str | None
    unit: CodeUnit | None
    read: ProvenanceRead

    def __post_init__(self) -> None:
        if type(self.read) is not ProvenanceRead or self.read.outcome != self.outcome:
            raise ValueError("Code provenance must describe its own reader outcome")
        if (self.unit is not None) != (self.outcome == "text"):
            raise ValueError("Only decoded text carries a code unit")
        if self.unit is not None and type(self.unit) is not CodeUnit:
            raise ValueError("A code unit must be a frozen CodeUnit")
        if self.language is not None and self.language not in CODE_LANGUAGES:
            raise ValueError("Unknown code language")


def read_code_provenance(
    raw_input: RawInput,
    data: bytes,
    *,
    name: str | None = None,
    path: str | None = None,
    budget: TextBudget | None = None,
) -> CodeProvenance:
    """Map one captured code or config file without reopening the checkout.

    `data` is the bytes of the accepted raw object; the caller reads them from the
    raw store, so this stays pure. Rich formats and archives refuse, as they do in
    the plain lane, and plain prose refuses because it belongs to the prose lane.
    An empty or whitespace-only file, and a binary one, produce no unit and say so.
    """
    name = name if name is not None else raw_input.logical_path
    if is_plain_prose_name(name):
        raise UnsupportedCodeFormat(f"Plain prose belongs to the prose lane, not code capture: {name}")
    read = read_plain_provenance(raw_input, data, name=name, path=path, budget=budget)
    language = lang_of(name)
    if read.outcome != "text":
        return CodeProvenance(read.outcome, language, None, read)
    document = read.documents[0]
    # `extract_code` measures the same encoded analysis text against the same rail,
    # then decides separately whether a walker exists for the language.
    encoded = len(document.analysis_text.encode("utf-8", errors="replace"))
    unit = CodeUnit(
        input_key=raw_input.input_key,
        logical_path=raw_input.logical_path,
        language=language,
        is_code=document.is_code,
        parsable=language is not None and encoded <= CODE_MAX_FILE_BYTES,
        original=read.original_units[0],
        document=document,
    )
    return CodeProvenance("text", language, unit, read)


__all__ = [
    "CODE_LANGUAGES",
    "CodeProvenance",
    "CodeUnit",
    "UnsupportedCodeFormat",
    "UnsupportedProvenanceFormat",
    "read_code_provenance",
]
