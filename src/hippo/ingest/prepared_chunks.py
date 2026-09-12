"""Plain prose chunks with immutable, exact original and generated text mappings.

The shared chunker operates on _MappedText using its existing boundary rules.
Internal ranges address the reader's analysis characters. Only the final adapter
translates them to original coordinates and expands evidence to complete lines.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

from hippo.knowledge.identity import make_identity

from .provenance import (
    GeneratedSegment,
    OriginalLines,
    OriginalSegment,
    OriginalUnit,
    ProvenanceDocument,
    Segment,
)
from .readers import ReadError


class UnsupportedChunkProvenance(ReadError):
    """This preparation slice only accepts original plain prose reader mappings."""


@dataclass(frozen=True, slots=True)
class _Range:
    start: int
    end: int

    def __post_init__(self):
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end:
            raise ValueError("Mapped dependencies require nonempty character ranges")


@dataclass(frozen=True, slots=True)
class _Run:
    text: str
    start: int | None
    rule: str = ""
    dependencies: tuple[_Range, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        if not isinstance(self.text, str) or not self.text or not isinstance(self.rule, str):
            raise ValueError("Mapped runs require nonempty immutable text")
        if any(type(item) is not _Range for item in self.dependencies):
            raise ValueError("Mapped dependencies require immutable ranges")
        if self.start is None:
            if not self.rule or not self.dependencies:
                raise ValueError("Generated runs require an explicit rule and original dependencies")
        elif type(self.start) is not int or self.start < 0 or self.rule or self.dependencies:
            raise ValueError("Original runs require an offset and cannot claim generated metadata")

    @property
    def inputs(self) -> tuple[_Range, ...]:
        return self.dependencies if self.start is None else (_Range(self.start, self.start + len(self.text)),)


@dataclass(frozen=True, slots=True)
class _MappedText:
    """Small string-operation adapter; no searching for already-rendered chunk text."""

    runs: tuple[_Run, ...]
    anchors: tuple[_Range, ...] = ()
    _text: str = field(init=False, repr=False, compare=False)
    _ends: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "runs", tuple(self.runs))
        object.__setattr__(self, "anchors", tuple(self.anchors))
        if any(type(run) is not _Run for run in self.runs) or any(
            type(r) is not _Range for r in self.anchors
        ):
            raise ValueError("Mapped text requires immutable runs and anchors")
        ends = []
        length = 0
        for run in self.runs:
            length += len(run.text)
            ends.append(length)
        object.__setattr__(self, "_ends", tuple(ends))
        object.__setattr__(self, "_text", "".join(run.text for run in self.runs))

    def __str__(self) -> str:
        return self._text

    def __len__(self) -> int:
        return len(self._text)

    @property
    def inputs(self) -> tuple[_Range, ...]:
        return _unique((*self.anchors, *(r for run in self.runs for r in run.inputs)))

    def __getitem__(self, item: slice) -> _MappedText:
        if not isinstance(item, slice) or item.step not in (None, 1):
            raise ValueError("Mapped text supports forward character slices only")
        first, last, _ = item.indices(len(self))
        runs = []
        index = bisect_right(self._ends, first)
        offset = self._ends[index - 1] if index else 0
        for position in range(index, len(self.runs)):
            if offset >= last:
                break
            run = self.runs[position]
            left, right = max(first, offset), min(last, offset + len(run.text))
            if left < right:
                text = run.text[left - offset : right - offset]
                runs.append(
                    _Run(text, run.start + left - offset)
                    if run.start is not None
                    else _Run(text, None, run.rule, run.dependencies)
                )
            offset += len(run.text)
        return _MappedText(tuple(runs), self.anchors)

    def strip(self) -> _MappedText:
        text = str(self)
        left = len(text) - len(text.lstrip())
        return self[left : left + len(text.strip())]

    def splitlines(self) -> list[_MappedText]:
        result = []
        offset = 0
        for full_line in str(self).splitlines(keepends=True):
            # Python's splitlines namespace is part of legacy analysis behavior;
            # final original evidence still uses the reader's physical line policy.
            content = full_line.splitlines()[0]
            line = self[offset : offset + len(content)]
            if not line:
                line = _MappedText((), self[offset : offset + len(full_line)].inputs)
            result.append(line)
            offset += len(full_line)
        return result

    def rfind(self, needle: str, start: int, end: int) -> int:
        return str(self).rfind(needle, start, end)

    def replace(self, old: str, new: str) -> _MappedText:
        if old != "\n" or new != " ":
            raise ValueError("Only the legacy overlap newline replacement is supported")
        runs = []
        for run in self.runs:
            cursor = 0
            for offset, char in enumerate(run.text):
                if char != old:
                    continue
                if cursor < offset:
                    runs.extend(_MappedText((run,))[cursor:offset].runs)
                origin = _MappedText((run,))[offset : offset + 1]
                runs.append(_Run(new, None, "overlap-newline-v1", origin.inputs))
                cursor = offset + 1
            runs.extend(_MappedText((run,))[cursor:].runs)
        return _MappedText(tuple(runs), self.anchors)

    def join(self, values: list[_MappedText], separator: str, rule: str) -> _MappedText:
        runs = []
        anchors = []
        for position, value in enumerate(values):
            if position:
                previous = values[position - 1]
                before = previous[-1:].inputs if previous else previous.inputs
                after = value[:1].inputs if value else value.inputs
                runs.append(_Run(separator, None, rule, _unique((*before, *after))))
            runs.extend(value.runs)
            anchors.extend(value.anchors)
        return _MappedText(tuple(runs), () if runs else _unique(anchors))


def _unique(values):
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True, slots=True)
class PreparedOriginal:
    unit_key: str
    lines: OriginalLines

    def __post_init__(self):
        if not isinstance(self.unit_key, str) or not self.unit_key or type(self.lines) is not OriginalLines:
            raise ValueError("Prepared originals require an immutable unit identity and complete-line slice")


def _original_closure(
    units: tuple[OriginalUnit, ...], dependencies: tuple[OriginalSegment, ...]
) -> tuple[PreparedOriginal, ...]:
    out = []
    for unit in units:
        slices = sorted(
            (
                unit.complete_lines(dep.start, dep.end)
                for dep in dependencies
                if dep.unit_key == unit.unit_key
            ),
            key=lambda lines: lines.start,
        )
        merged = []
        for lines in slices:
            if merged and lines.start <= merged[-1].end:
                previous = merged.pop()
                merged.append(unit.complete_lines(previous.start, max(previous.end, lines.end)))
            else:
                merged.append(lines)
        out.extend(PreparedOriginal(unit.unit_key, lines) for lines in merged)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class PreparedChunk:
    ordinal: int
    title: str
    text: str
    defines: tuple[str, ...]
    extract_text: str | None
    original_units: tuple[OriginalUnit, ...]
    retrieval_segments: tuple[Segment, ...]
    extraction_segments: tuple[Segment, ...]
    segment_dependencies: tuple[tuple[OriginalSegment, ...], ...]
    title_dependencies: tuple[OriginalSegment, ...]
    original_dependencies: tuple[OriginalSegment, ...]
    originals: tuple[PreparedOriginal, ...]
    chunker_profile: tuple[str, int, int]
    chunk_key: str = field(init=False)

    def __post_init__(self):
        for name in (
            "defines",
            "original_units",
            "retrieval_segments",
            "extraction_segments",
            "title_dependencies",
            "original_dependencies",
            "originals",
            "chunker_profile",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(
            self, "segment_dependencies", tuple(tuple(group) for group in self.segment_dependencies)
        )
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("Prepared chunks require a nonnegative ordinal")
        if (
            len(self.chunker_profile) != 3
            or self.chunker_profile[0] != "plain-prose-v1"
            or any(type(v) is not int for v in self.chunker_profile[1:])
        ):
            raise ValueError("Prepared chunks require an immutable supported chunker profile")
        if (
            self.defines
            or self.extract_text is not None
            or self.extraction_segments != self.retrieval_segments
        ):
            raise ValueError("Plain prose preparation uses chunk text for extraction and defines no code")
        ProvenanceDocument(self.title, self.text, "", False, self.original_units, self.retrieval_segments)
        units = {unit.unit_key: unit for unit in self.original_units}
        declared = (
            *self.original_dependencies,
            *self.title_dependencies,
            *(dep for group in self.segment_dependencies for dep in group),
        )
        for dep in declared:
            if (
                type(dep) is not OriginalSegment
                or dep.unit_key not in units
                or not dep.start < dep.end <= len(units[dep.unit_key].text)
            ):
                raise ValueError("Prepared dependencies require exact immutable original ranges")
        if len(self.segment_dependencies) != len(self.retrieval_segments):
            raise ValueError("Every retrieval segment requires its own exact dependencies")
        for segment, dependencies in zip(self.retrieval_segments, self.segment_dependencies, strict=True):
            if type(segment) is OriginalSegment:
                if dependencies != (segment,):
                    raise ValueError("Original segment dependencies must match its own range")
            elif not dependencies or set(segment.original_unit_keys) != {
                dep.unit_key for dep in dependencies
            }:
                raise ValueError("Generated segment dependencies must cover its declared original units")
        expected = _unique(
            (*[dep for group in self.segment_dependencies for dep in group], *self.title_dependencies)
        )
        if self.original_dependencies != expected:
            raise ValueError("Prepared original dependencies must include every retrieval and title input")
        if any(
            type(item) is not PreparedOriginal for item in self.originals
        ) or self.originals != _original_closure(self.original_units, self.original_dependencies):
            raise ValueError("Prepared original closure must contain the complete supported source lines")
        descriptors = [
            ["original", s.unit_key, s.start, s.end]
            if type(s) is OriginalSegment
            else ["generated", s.text, s.rule_id, list(s.original_unit_keys)]
            for s in self.retrieval_segments
        ]
        key = make_identity(
            "prepared_chunk",
            [
                list(self.chunker_profile),
                self.ordinal,
                self.title,
                self.text,
                descriptors,
                [[[d.unit_key, d.start, d.end] for d in group] for group in self.segment_dependencies],
                [[d.unit_key, d.start, d.end] for d in self.title_dependencies],
            ],
        )
        object.__setattr__(self, "chunk_key", key)

    @property
    def support_chunk_keys(self) -> tuple[str, ...]:
        return (self.chunk_key,)

    @property
    def requires_view(self) -> bool:
        return (
            len(self.originals) != 1
            or self.originals[0].lines.text != self.text
            or any(isinstance(segment, GeneratedSegment) for segment in self.retrieval_segments)
        )

    def to_chunk(self):
        from ..hipporag.indexer import Chunk

        return Chunk(self.ordinal, self.title, self.text, list(self.defines), self.extract_text)


def _translate(doc: ProvenanceDocument, ranges: tuple[_Range, ...]) -> tuple[OriginalSegment, ...]:
    result = []
    for span in ranges:
        segments = doc.original_segments_for_bytes(
            doc.parser_byte_boundaries[span.start], doc.parser_byte_boundaries[span.end]
        )
        if any(type(segment) is not OriginalSegment for segment in segments):
            raise UnsupportedChunkProvenance("Generated input mapping is not yet supported")
        result.extend(segments)
    return _unique(result)


def _prepare_chunk(doc, mapped, title, title_inputs, ordinal, size, overlap):
    segments = []
    segment_dependencies = []
    for run in mapped.runs:
        dependencies = _translate(doc, run.inputs)
        if run.start is not None:
            segments.extend(dependencies)
            segment_dependencies.extend((dep,) for dep in dependencies)
        else:
            segments.append(GeneratedSegment(run.text, run.rule, _unique(d.unit_key for d in dependencies)))
            segment_dependencies.append(dependencies)
    title_ranges = tuple(r for value in title_inputs if type(value) is _MappedText for r in value.inputs)
    title_dependencies = _translate(doc, title_ranges)
    dependencies = _unique((*[dep for group in segment_dependencies for dep in group], *title_dependencies))
    return PreparedChunk(
        ordinal,
        title,
        str(mapped),
        (),
        None,
        doc.original_units,
        tuple(segments),
        tuple(segments),
        tuple(segment_dependencies),
        title_dependencies,
        dependencies,
        _original_closure(doc.original_units, dependencies),
        ("plain-prose-v1", size, overlap),
    )


def prepare_prose_chunks(
    documents: tuple[ProvenanceDocument, ...], *, size_chars: int, overlap_chars: int
) -> tuple[PreparedChunk, ...]:
    """Pure plain-prose preparation; legacy chunking and persistence stay separate."""
    from .chunker import MIN_CHUNK_CHARS, _prose_pieces

    size = max(MIN_CHUNK_CHARS, size_chars)
    overlap = max(0, min(overlap_chars, size // 3))
    chunks = []
    for doc in documents:
        if type(doc) is not ProvenanceDocument or doc.is_code:
            raise UnsupportedChunkProvenance("Code and rich-reader chunk provenance are not yet supported")
        if any(type(segment) is not OriginalSegment for segment in doc.segments):
            raise UnsupportedChunkProvenance("Existing generated input mappings are not yet supported")
        if not doc.analysis_text:
            continue
        if len(doc.original_units) != 1 or len(doc.segments) != 1:
            raise UnsupportedChunkProvenance(
                "Only the plain reader's single original trim mapping is supported"
            )
        unit = doc.original_units[0]
        trim_start = len(unit.text) - len(unit.text.lstrip())
        if doc.analysis_text != unit.text.strip() or doc.segments != (
            OriginalSegment(unit.unit_key, trim_start, trim_start + len(doc.analysis_text)),
        ):
            raise UnsupportedChunkProvenance("Only the plain reader's exact trim mapping is supported")
        mapped = _MappedText((_Run(doc.analysis_text, 0),)) if doc.analysis_text else _MappedText(())
        for title, piece, title_inputs in _prose_pieces(mapped, doc.title, size, overlap):
            chunks.append(_prepare_chunk(doc, piece, title, title_inputs, len(chunks), size, overlap))
    return tuple(chunks)
