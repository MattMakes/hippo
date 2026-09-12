"""Immutable plain-reader provenance, separate from legacy ingestion dispatch.

Analysis coordinates address the UTF-8 encoding of trimmed reader output. Original
coordinates address untrimmed decoded text. Raw ranges address retained input bytes;
replacement decoding is explicitly non-exact. Only complete original lines carry
file_lines locators. Nothing in these preparation values grants evidence access.

`RawInput` is the accepted-input value `hippo.knowledge.inputs` owns; it is
re-exported here because reading bytes is what this module does with one, and
because `hippo.ingest.provenance` is the import path every caller already uses.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Literal

from hippo.knowledge.identity import make_identity
from hippo.knowledge.inputs import RawInput
from hippo.knowledge.model import FileLinesLocator

from .readers import (
    CODE_EXTENSIONS,
    MAX_TEXT_CHARS,
    PROSE_EXTENSIONS,
    RICH_EXTENSIONS,
    Document,
    ReadError,
    TextBudget,
    TooLarge,
    is_probably_binary,
)


class UnsupportedProvenanceFormat(ReadError):
    """This reader has no honest original-unit mapping for the requested format."""


def _range(start: int, end: int, limit: int | None = None) -> None:
    if type(start) is not int or type(end) is not int or start < 0 or end < start:
        raise ValueError("Expected a half-open nonnegative character range")
    if limit is not None and end > limit:
        raise ValueError("Range exceeds original text")


@dataclass(frozen=True, slots=True)
class RawCharacterRange:
    start: int
    end: int
    exact: bool

    def __post_init__(self) -> None:
        _range(self.start, self.end)
        if self.start == self.end or type(self.exact) is not bool:
            raise ValueError("Decoded characters need a nonempty raw range and explicit precision")


@dataclass(frozen=True, slots=True)
class OriginalLine:
    start: int
    end: int
    newline: str

    def __post_init__(self) -> None:
        _range(self.start, self.end)
        if self.start == self.end or self.newline not in ("", "\n", "\r", "\r\n"):
            raise ValueError("Invalid physical line")


@dataclass(frozen=True, slots=True)
class OriginalLines:
    """A complete-line slice; internal character coordinates are not locator precision."""

    locator: FileLinesLocator
    text: str
    start: int
    end: int

    def __post_init__(self) -> None:
        _range(self.start, self.end)
        if type(self.locator) is not FileLinesLocator or not isinstance(self.text, str):
            raise ValueError("Original line slices need immutable text and a typed locator")
        if not self.text or len(self.text) != self.end - self.start:
            raise ValueError("Original line slice text must match its character range")


@dataclass(frozen=True, slots=True)
class OriginalUnit:
    unit_key: str
    input_key: str
    locator: FileLinesLocator
    text: str
    decoder_profile: str
    bom_bytes: int
    raw_ranges: tuple[RawCharacterRange, ...]
    lines: tuple[OriginalLine, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_ranges", tuple(self.raw_ranges))
        object.__setattr__(self, "lines", tuple(self.lines))
        if type(self.locator) is not FileLinesLocator:
            raise ValueError("Original units require a frozen FileLinesLocator")
        if any(type(item) is not RawCharacterRange for item in self.raw_ranges):
            raise ValueError("Original raw ranges must be frozen RawCharacterRange values")
        if any(type(item) is not OriginalLine for item in self.lines):
            raise ValueError("Original lines must be frozen OriginalLine values")
        if any(
            not isinstance(value, str) or not value for value in (self.unit_key, self.input_key, self.text)
        ):
            raise ValueError("Original unit requires identity and nonempty original text")
        if self.decoder_profile not in ("plain-utf8-sig-strict-v1", "plain-utf8-sig-replace-v1"):
            raise ValueError("Unknown original decoder profile")
        if self.bom_bytes not in (0, 3) or len(self.raw_ranges) != len(self.text):
            raise ValueError("Original decoder map does not cover its text")
        if self.raw_ranges[0].start != self.bom_bytes or any(
            a.end != b.start for a, b in zip(self.raw_ranges, self.raw_ranges[1:], strict=False)
        ):
            raise ValueError("Original raw ranges must be contiguous after the declared BOM")
        for char, mapping in zip(self.text, self.raw_ranges, strict=True):
            if mapping.exact:
                if mapping.end - mapping.start != len(char.encode("utf-8")):
                    raise ValueError("Exact decoder range has the wrong byte width")
            elif char != "�" or self.decoder_profile != "plain-utf8-sig-replace-v1":
                raise ValueError("Only replacement decoding may carry non-exact character ranges")
        if self.lines != _lines(self.text) or self.locator.start != 1 or self.locator.end != len(self.lines):
            raise ValueError("Original line locator must cover the complete untrimmed file")

    def complete_lines(self, start: int, end: int) -> OriginalLines:
        """Expand a nonempty character range to the actual whole source lines."""
        _range(start, end, len(self.text))
        if start == end:
            raise ValueError("An empty range cannot claim a positive source line")
        first = bisect_right(self.lines, start, key=lambda line: line.start) - 1
        last = bisect_right(self.lines, end - 1, key=lambda line: line.start) - 1
        left, right = self.lines[first].start, self.lines[last].end
        return OriginalLines(
            self.locator.replace(start=first + 1, end=last + 1), self.text[left:right], left, right
        )


@dataclass(frozen=True, slots=True)
class OriginalSegment:
    unit_key: str
    start: int
    end: int

    def __post_init__(self) -> None:
        _range(self.start, self.end)
        if not isinstance(self.unit_key, str) or not self.unit_key:
            raise ValueError("An original segment needs a unit key")


@dataclass(frozen=True, slots=True)
class GeneratedSegment:
    text: str
    rule_id: str
    original_unit_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not isinstance(self.rule_id, str):
            raise ValueError("Generated text and renderer rules must be immutable strings")
        if isinstance(self.original_unit_keys, str):
            raise ValueError("Generated dependencies must be a collection of unit keys")
        object.__setattr__(self, "original_unit_keys", tuple(self.original_unit_keys))
        if (
            not self.rule_id
            or not self.original_unit_keys
            or any(not isinstance(key, str) or not key for key in self.original_unit_keys)
        ):
            raise ValueError("Generated text needs a renderer rule and original dependencies")


Segment = OriginalSegment | GeneratedSegment


@dataclass(frozen=True, slots=True)
class ProvenanceDocument:
    title: str
    analysis_text: str
    path: str
    is_code: bool
    original_units: tuple[OriginalUnit, ...]
    segments: tuple[Segment, ...]
    parser_byte_boundaries: tuple[int, ...] = field(init=False)

    def __post_init__(self) -> None:
        if (
            any(not isinstance(value, str) for value in (self.title, self.analysis_text, self.path))
            or type(self.is_code) is not bool
        ):
            raise ValueError("Document fields must be immutable legacy-compatible values")
        object.__setattr__(self, "original_units", tuple(self.original_units))
        object.__setattr__(self, "segments", tuple(self.segments))
        if any(type(unit) is not OriginalUnit for unit in self.original_units):
            raise ValueError("Document originals must be frozen OriginalUnit values")
        units = {unit.unit_key: unit for unit in self.original_units}
        if len(units) != len(self.original_units):
            raise ValueError("Original unit keys must be unique")
        for segment in self.segments:
            if type(segment) is OriginalSegment:
                if segment.unit_key not in units:
                    raise ValueError("Original segment references a missing unit")
                _range(segment.start, segment.end, len(units[segment.unit_key].text))
            elif type(segment) is GeneratedSegment:
                if any(key not in units for key in segment.original_unit_keys):
                    raise ValueError("Generated segment references a missing original dependency")
            else:
                raise ValueError("Unknown provenance segment")
        if self.render() != self.analysis_text:
            raise ValueError("Provenance segments do not reconstruct analysis text")
        boundaries = [0]
        for char in self.analysis_text:
            boundaries.append(boundaries[-1] + len(char.encode("utf-8")))
        object.__setattr__(self, "parser_byte_boundaries", tuple(boundaries))

    def render(self) -> str:
        units = {unit.unit_key: unit for unit in self.original_units}
        return "".join(
            units[s.unit_key].text[s.start : s.end] if isinstance(s, OriginalSegment) else s.text
            for s in self.segments
        )

    def to_document(self) -> Document:
        """Return a fresh legacy adapter; mutating it cannot change provenance."""
        return Document(title=self.title, text=self.analysis_text, path=self.path, is_code=self.is_code)

    def original_segments_for_bytes(self, start: int, end: int) -> tuple[Segment, ...]:
        """Translate parser ranges without searching text or inventing generated offsets."""
        _range(start, end, self.parser_byte_boundaries[-1])
        first = bisect_left(self.parser_byte_boundaries, start)
        last = bisect_left(self.parser_byte_boundaries, end)
        if self.parser_byte_boundaries[first] != start or self.parser_byte_boundaries[last] != end:
            raise ValueError("Parser offset is not a UTF-8 boundary")
        result: list[Segment] = []
        offset = 0
        for segment in self.segments:
            size = segment.end - segment.start if isinstance(segment, OriginalSegment) else len(segment.text)
            left, right = max(first, offset), min(last, offset + size)
            if left < right:
                if isinstance(segment, OriginalSegment):
                    result.append(
                        OriginalSegment(
                            segment.unit_key, segment.start + left - offset, segment.start + right - offset
                        )
                    )
                else:
                    result.append(
                        GeneratedSegment(
                            segment.text[left - offset : right - offset],
                            segment.rule_id,
                            segment.original_unit_keys,
                        )
                    )
            offset += size
        return tuple(result)


@dataclass(frozen=True, slots=True)
class ProvenanceRead:
    documents: tuple[ProvenanceDocument, ...]
    original_units: tuple[OriginalUnit, ...]
    outcome: Literal["text", "empty", "binary"]

    def __post_init__(self) -> None:
        object.__setattr__(self, "documents", tuple(self.documents))
        object.__setattr__(self, "original_units", tuple(self.original_units))
        if any(type(doc) is not ProvenanceDocument for doc in self.documents):
            raise ValueError("Reader documents must be frozen ProvenanceDocument values")
        if any(type(unit) is not OriginalUnit for unit in self.original_units):
            raise ValueError("Reader originals must be frozen OriginalUnit values")
        if self.outcome not in ("text", "empty", "binary") or bool(self.documents) != (
            self.outcome == "text"
        ):
            raise ValueError("Reader outcome must describe its documents")
        if self.outcome == "binary" and self.original_units:
            raise ValueError("Binary inputs cannot claim decoded originals")
        units = {unit.unit_key: unit for unit in self.original_units}
        if len(units) != len(self.original_units) or any(
            units.get(unit.unit_key) != unit for doc in self.documents for unit in doc.original_units
        ):
            raise ValueError("Reader originals must include every document's immutable units")


def _lines(text: str) -> tuple[OriginalLine, ...]:
    """Physical CRLF/LF/CR lines, retaining each terminator; no synthetic final line."""
    result = []
    start = 0
    for match in re.finditer(r"\r\n|\r|\n", text):
        result.append(OriginalLine(start, match.end(), match.group()))
        start = match.end()
    if start < len(text):
        result.append(OriginalLine(start, len(text), ""))
    return tuple(result)


def _raw_ranges(data: bytes, bom_bytes: int) -> tuple[RawCharacterRange, ...]:
    """Ask the actual codec about at most one UTF-8 sequence per iteration.

    UnicodeDecodeError.end supplies replacement grouping, including truncated
    sequences and invalid continuation bytes. Each input byte is visited once.
    """
    result = []
    offset = bom_bytes
    while offset < len(data):
        lead = data[offset]
        width = 2 if 0xC2 <= lead <= 0xDF else 3 if 0xE0 <= lead <= 0xEF else 4 if 0xF0 <= lead <= 0xF4 else 1
        candidate = data[offset : offset + width]
        try:
            candidate.decode("utf-8", errors="strict")
            end, exact = offset + len(candidate), True
        except UnicodeDecodeError as error:
            end, exact = offset + error.end, False
        result.append(RawCharacterRange(offset, end, exact))
        offset = end
    return tuple(result)


def read_plain_provenance(
    raw_input: RawInput,
    data: bytes,
    *,
    name: str | None = None,
    path: str | None = None,
    budget: TextBudget | None = None,
) -> ProvenanceRead:
    """Map accepted bytes without mutating legacy readers or reaching into storage.

    The legacy text budget counts stripped analysis characters. A separate fixed
    MAX_TEXT_CHARS cap bounds the untrimmed character map, even for whitespace-only
    inputs. Raw capture must additionally enforce its configured byte limit.
    """
    if (
        not isinstance(data, bytes)
        or len(data) != raw_input.byte_length
        or sha256(data).hexdigest() != raw_input.raw_hash
    ):
        raise ValueError("Input bytes do not match the accepted raw identity")
    name = name if name is not None else raw_input.logical_path
    where = path or name
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in RICH_EXTENSIONS or suffix == ".zip":
        raise UnsupportedProvenanceFormat(f"Original provenance is not implemented for {suffix}")
    if is_probably_binary(data):
        return ProvenanceRead((), (), "binary")
    errors = "replace" if suffix in PROSE_EXTENSIONS or suffix in CODE_EXTENSIONS else "strict"
    original = data.decode("utf-8-sig", errors=errors)
    analysis = original.strip()
    if analysis:
        (budget or TextBudget()).add(len(analysis), where)
    if len(original) > MAX_TEXT_CHARS:
        raise TooLarge(f"{where}: original provenance exceeds {MAX_TEXT_CHARS} characters")
    if not original:
        return ProvenanceRead((), (), "empty")
    lines = _lines(original)
    profile = f"plain-utf8-sig-{errors}-v1"
    unit = OriginalUnit(
        unit_key=make_identity("original_unit", [raw_input.input_key, raw_input.raw_hash, profile]),
        input_key=raw_input.input_key,
        locator=FileLinesLocator(path=raw_input.logical_path, start=1, end=len(lines)),
        text=original,
        decoder_profile=profile,
        bom_bytes=3 if data.startswith(b"\xef\xbb\xbf") else 0,
        raw_ranges=_raw_ranges(data, 3 if data.startswith(b"\xef\xbb\xbf") else 0),
        lines=lines,
    )
    if not analysis:
        return ProvenanceRead((), (unit,), "empty")
    trim_start = len(original) - len(original.lstrip())
    doc = ProvenanceDocument(
        title=name,
        analysis_text=analysis,
        path=where,
        is_code=suffix in CODE_EXTENSIONS,
        original_units=(unit,),
        segments=(OriginalSegment(unit.unit_key, trim_start, trim_start + len(analysis)),),
    )
    return ProvenanceRead((doc,), (unit,), "text")
