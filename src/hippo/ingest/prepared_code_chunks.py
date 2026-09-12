"""Code passages with immutable, exact original and generated text mappings.

Pure preparation. No store handle, no model, no wall clock: captured files arrive
as accepted inputs paired with CC4's provenance, and the resolved `CodeGraph`
arrives as an argument, so everything here is a function of what it is given.

The legacy chunker is not reimplemented. Plan section 6 step 6 says this seam
*wraps* `chunk_documents(..., code=code)`, and it does: every boundary decision --
which symbols a container owns, where a placeholder goes, where an oversized body
splits, how a commit's touched list is cut -- is taken by calling the committed
chunker's own helpers. What is re-expressed here is only the plumbing that
assembles rows into passages, because `chunk_documents` returns rendered strings
and throws away which line produced which character.

That re-expression is then latched: `prepare_code_chunks` runs the committed
`chunk_documents` over the same documents and refuses to return anything unless
its own `Chunk` list is equal, field for field. Byte-identity with the legacy
passage text is therefore an invariant of this module rather than a property some
test happens to observe.

Coordinates. A `CodeUnit` carries the untrimmed *original* file and the trimmed
*analysis* text the parser and the chunker see; the chunker's line numbers are
analysis line numbers, and every locator this module emits is an original
complete-line range, translated through CC4's `analysis_offset`.

What is generated. Three renderings have no original behind them: a container
header's placeholder line for each member, the ``"\\n"`` the chunker joins its rows
with wherever that newline is not the file's own character, and the whole of a
commit passage, which is rendered from a commit record rather than from any
captured file. Each is marked with its own rule id so the binding task can build a
`RetrievalView` over the originals exactly as `input_binding._view` does for prose.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, fields

from hippo.knowledge.identity import make_identity
from hippo.knowledge.inputs import RawInput

from ..codegraph.model import CodeGraph, Symbol
from .chunker import (
    CONTAINER_KINDS,
    MIN_CHUNK_CHARS,
    MIN_OPENIE_DOC_CHARS,
    Mentions,
    _chunk_commits,
    _data_ids_in,
    _file_module,
    _line_numbers,
    _members,
    _mention_index,
    _placeholder,
    _placeholders,
    _split_rows,
    _text_of,
    _title_range,
    chunk_documents,
    code_windows,
)
from .code_provenance import CodeProvenance, CodeUnit
from .prepared_chunks import (
    PreparedOriginal,
    _MappedText,
    _original_closure,
    _Range,
    _Run,
    _translate,
    _unique,
    prepare_prose_chunks,
)
from .provenance import GeneratedSegment, OriginalSegment, OriginalUnit, Segment
from .readers import ReadError, TooLarge, lang_of

# Bump whenever the chunk texts, kinds, original ranges or generated segments this
# module can produce could change. Plan ruling 10 (design review M2) folds it into
# the configuration `generation_for_inputs` hashes, so a changed derivation is a
# different generation and a stale staged row can never be resumed into a seal.
CODE_CHUNK_RULE_VERSION = "code-chunks-v1"

# The seeded-corpus digest `tests/unit/test_prepared_code_chunks.py` pins against
# the rule version above. It covers chunk kinds, titles, texts, defines, segment
# descriptors and original closures, so a derivation change fails that test until
# the rule version is bumped with it.
CODE_CHUNK_FIXTURE_DIGEST = "955a8dddfe37302bd34a77944cbd7413891fa4f5f77cd3a7aae0cf5dcd36a83b"

# What a passage is. `header` is a module/class/inline-module header, `symbol` a
# function or method body (or one part of one), `data_object` a `.sql` line window,
# `window` a line window of a file with no symbol tree, `prose` a file the legacy
# chunker packs as prose -- an extensionless `README`, `go.mod` -- and `commit` a
# synthesized commit passage. `window` and `prose` are additions to the four kinds
# the brief names: the committed chunker has those two branches and the passages
# they produce have to land somewhere honest.
CODE_CHUNK_KINDS = ("header", "symbol", "data_object", "window", "prose", "commit")

# A captured file that produces no passage at all, and why. Closed, as CC4's
# exclusion reasons are. An over-large *source* is not in this set: it raises
# `TooManyCodeChunks`, because plan section 8.3 refuses the build rather than
# dropping passages.
CODE_REFUSAL_REASONS = ("binary", "empty")

CODE_PLACEHOLDER_RULE = "code-placeholder-v1"
CODE_LINE_JOIN_RULE = "code-line-join-v1"
CODE_COMMIT_RULE = "code-commit-v1"

CODE_CHUNKER_PROFILE = "code-v1"
PROSE_CHUNKER_PROFILE = "plain-prose-v1"


class UnsupportedCodeChunkInput(ReadError):
    """This preparation slice only accepts CC4's untouched code provenance."""


class CodeChunkParityError(ReadError):
    """The mapped passages and the committed chunker's passages disagree."""


class TooManyCodeChunks(TooLarge):
    """This source makes more passages than the configured ceiling allows."""


@dataclass(frozen=True, slots=True)
class CapturedCode:
    """One accepted input and what CC4 decoded it to.

    The pair, rather than the `CodeUnit` alone, because a binary or empty file has
    no unit and a refusal still has to name which accepted input it refused.
    """

    raw_input: RawInput
    provenance: CodeProvenance

    def __post_init__(self) -> None:
        if type(self.raw_input) is not RawInput or type(self.provenance) is not CodeProvenance:
            raise UnsupportedCodeChunkInput("Captured code pairs an accepted input with its provenance")

    @property
    def input_key(self) -> str:
        return self.raw_input.input_key

    @property
    def logical_path(self) -> str:
        return self.raw_input.logical_path

    @property
    def unit(self) -> CodeUnit | None:
        return self.provenance.unit


@dataclass(frozen=True, slots=True)
class CommitSegment:
    """Passage text rendered from a commit record; no captured file is behind it."""

    text: str
    rule_id: str
    commit_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("A commit segment requires nonempty immutable text")
        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise ValueError("A commit segment requires a renderer rule")
        if not isinstance(self.commit_id, str) or not self.commit_id:
            raise ValueError("A commit segment requires the commit it was rendered from")


CodeSegment = Segment | CommitSegment


@dataclass(frozen=True, slots=True)
class CodeChunkSettings:
    """The input-affecting chunking configuration, and only that.

    Operational limits stay out: plan section 5 keeps them outside generation
    identity, so the passage ceiling is a separate argument rather than a field
    here. `effective_size` and `effective_overlap` are the values *after* the
    chunker's own clamp, which is what plan section 5 records in
    `configuration_json`.
    """

    size_chars: int
    overlap_chars: int

    def __post_init__(self) -> None:
        if type(self.size_chars) is not int or type(self.overlap_chars) is not int:
            raise ValueError("Chunk settings require integer character counts")

    @property
    def effective_size(self) -> int:
        return max(MIN_CHUNK_CHARS, self.size_chars)

    @property
    def effective_overlap(self) -> int:
        return max(0, min(self.overlap_chars, self.effective_size // 3))

    @property
    def profile(self) -> tuple[str, int, int]:
        return (CODE_CHUNKER_PROFILE, self.effective_size, self.effective_overlap)


@dataclass(frozen=True, slots=True)
class CodeChunkRefusal:
    """One captured file that produced no passage, and the reason it produced none."""

    input_key: str
    logical_path: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.input_key, str) or not self.input_key:
            raise ValueError("A refusal names its accepted input")
        if not isinstance(self.logical_path, str) or not self.logical_path:
            raise ValueError("A refusal names its logical path")
        if self.reason not in CODE_REFUSAL_REASONS:
            raise ValueError("Unknown code chunk refusal reason")


@dataclass(frozen=True, slots=True)
class PreparedCodeChunk:
    """One legacy code passage with its exact originals and its generated segments.

    `retrieval_segments` partition `text`: concatenating them reproduces it
    character for character, so no part of a passage is unaccounted for. A commit
    passage has no captured file behind it and therefore no original at all; its
    single `CommitSegment` names the commit record CC7 binds.
    """

    ordinal: int
    kind: str
    title: str
    text: str
    defines: tuple[str, ...]
    extract_text: str | None
    logical_path: str | None
    symbol_id: str | None
    data_object_ids: tuple[str, ...]
    commit_id: str | None
    commit_sha: str | None
    original_units: tuple[OriginalUnit, ...]
    retrieval_segments: tuple[CodeSegment, ...]
    segment_dependencies: tuple[tuple[OriginalSegment, ...], ...]
    title_dependencies: tuple[OriginalSegment, ...]
    original_dependencies: tuple[OriginalSegment, ...]
    originals: tuple[PreparedOriginal, ...]
    placeholders: tuple[tuple[str, OriginalSegment], ...]
    chunker_profile: tuple[str, int, int]
    rule_version: str
    chunk_key: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "defines",
            "data_object_ids",
            "original_units",
            "retrieval_segments",
            "title_dependencies",
            "original_dependencies",
            "originals",
            "placeholders",
            "chunker_profile",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(
            self, "segment_dependencies", tuple(tuple(group) for group in self.segment_dependencies)
        )
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("Prepared code chunks require a nonnegative ordinal")
        if self.kind not in CODE_CHUNK_KINDS or self.rule_version != CODE_CHUNK_RULE_VERSION:
            raise ValueError("Prepared code chunks require a known kind and the current rule version")
        if (
            len(self.chunker_profile) != 3
            or self.chunker_profile[0] not in (CODE_CHUNKER_PROFILE, PROSE_CHUNKER_PROFILE)
            or any(type(value) is not int for value in self.chunker_profile[1:])
        ):
            raise ValueError("Prepared code chunks require an immutable supported chunker profile")
        if not isinstance(self.title, str) or not isinstance(self.text, str):
            raise ValueError("Prepared code chunks require immutable passage text")
        # Only a commit may be empty: a commit with no message and no touched symbol
        # renders to nothing, and the legacy chunker still emits that passage.
        if not self.text and self.kind != "commit":
            raise ValueError("A file passage cannot be empty")
        self._check_segments()
        self._check_closure()
        object.__setattr__(self, "chunk_key", self._identity())

    def _check_segments(self) -> None:
        units = {unit.unit_key: unit for unit in self.original_units}
        rendered = []
        for segment in self.retrieval_segments:
            if type(segment) is OriginalSegment:
                unit = units.get(segment.unit_key)
                if unit is None or not segment.start < segment.end <= len(unit.text):
                    raise ValueError("An original segment must address a declared original unit")
                rendered.append(unit.text[segment.start : segment.end])
            elif type(segment) is GeneratedSegment:
                if any(key not in units for key in segment.original_unit_keys):
                    raise ValueError("A generated segment must depend on declared original units")
                rendered.append(segment.text)
            elif type(segment) is CommitSegment:
                if segment.commit_id != self.commit_id or self.kind != "commit":
                    raise ValueError("Only a commit passage carries commit-rendered text")
                rendered.append(segment.text)
            else:
                raise ValueError("Unknown prepared code segment")
        if "".join(rendered) != self.text:
            raise ValueError("Prepared code segments do not reconstruct the passage text")
        if len(self.segment_dependencies) != len(self.retrieval_segments):
            raise ValueError("Every retrieval segment requires its own exact dependencies")
        for segment, dependencies in zip(self.retrieval_segments, self.segment_dependencies, strict=True):
            if type(segment) is OriginalSegment:
                if dependencies != (segment,):
                    raise ValueError("Original segment dependencies must match its own range")
            elif type(segment) is CommitSegment:
                if dependencies:
                    raise ValueError("A commit segment has no original dependency")
            elif not dependencies or set(segment.original_unit_keys) != {
                dep.unit_key for dep in dependencies
            }:
                raise ValueError("Generated segment dependencies must cover its declared original units")

    def _check_closure(self) -> None:
        units = {unit.unit_key: unit for unit in self.original_units}
        declared = (
            *(dep for group in self.segment_dependencies for dep in group),
            *self.title_dependencies,
        )
        for dep in declared:
            if (
                type(dep) is not OriginalSegment
                or dep.unit_key not in units
                or not dep.start < dep.end <= len(units[dep.unit_key].text)
            ):
                raise ValueError("Prepared dependencies require exact immutable original ranges")
        if self.original_dependencies != _unique(declared):
            raise ValueError("Prepared original dependencies must include every segment and title input")
        if any(type(item) is not PreparedOriginal for item in self.originals) or self.originals != (
            _original_closure(self.original_units, self.original_dependencies)
        ):
            raise ValueError("Prepared original closure must contain the complete supported source lines")
        for symbol_id, dependency in self.placeholders:
            if not isinstance(symbol_id, str) or not symbol_id or type(dependency) is not OriginalSegment:
                raise ValueError("A placeholder names the member it stands for and the lines it read")
        if (self.commit_id is None) != (self.kind != "commit"):
            raise ValueError("Exactly the commit passages carry a commit identity")
        if self.kind == "commit" and (self.original_units or self.logical_path is not None):
            raise ValueError("A commit passage is rendered from its commit record, not from a file")

    def _identity(self) -> str:
        return make_identity(
            "prepared_code_chunk",
            [
                self.rule_version,
                list(self.chunker_profile),
                self.ordinal,
                self.kind,
                self.title,
                self.text,
                list(self.defines),
                self.extract_text,
                segment_descriptors(self.retrieval_segments),
                [[[d.unit_key, d.start, d.end] for d in group] for group in self.segment_dependencies],
                [[d.unit_key, d.start, d.end] for d in self.title_dependencies],
            ],
        )

    @property
    def support_chunk_keys(self) -> tuple[str, ...]:
        return (self.chunk_key,)

    @property
    def requires_view(self) -> bool:
        """True when the passage text is not byte-identical to one original region."""
        return (
            len(self.originals) != 1
            or self.originals[0].lines.text != self.text
            or any(type(segment) is not OriginalSegment for segment in self.retrieval_segments)
        )

    def to_chunk(self):
        from ..hipporag.indexer import Chunk

        return Chunk(self.ordinal, self.title, self.text, list(self.defines), self.extract_text)


def segment_descriptors(segments: Iterable[CodeSegment]) -> list[list]:
    """A JSON-safe description of one passage's provenance, for identity and evidence."""
    out = []
    for segment in segments:
        if type(segment) is OriginalSegment:
            out.append(["original", segment.unit_key, segment.start, segment.end])
        elif type(segment) is GeneratedSegment:
            out.append(["generated", segment.text, segment.rule_id, list(segment.original_unit_keys)])
        else:
            out.append(["commit", segment.text, segment.rule_id, segment.commit_id])
    return out


@dataclass(frozen=True, slots=True)
class PreparedCodeChunks:
    """Every passage one code generation's captured files produced, and every refusal."""

    rule_version: str
    chunker_profile: tuple[str, int, int]
    chunks: tuple[PreparedCodeChunk, ...]
    refusals: tuple[CodeChunkRefusal, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunks", tuple(self.chunks))
        object.__setattr__(self, "refusals", tuple(self.refusals))
        object.__setattr__(self, "chunker_profile", tuple(self.chunker_profile))
        if self.rule_version != CODE_CHUNK_RULE_VERSION:
            raise ValueError("Prepared code chunks carry the current rule version")
        if any(type(chunk) is not PreparedCodeChunk for chunk in self.chunks):
            raise ValueError("Prepared code chunks must be frozen PreparedCodeChunk values")
        if any(type(item) is not CodeChunkRefusal for item in self.refusals):
            raise ValueError("Code chunk refusals must be frozen CodeChunkRefusal values")
        if [chunk.ordinal for chunk in self.chunks] != list(range(len(self.chunks))):
            raise ValueError("Prepared code chunk ordinals must run from zero without a gap")

    def __len__(self) -> int:
        return len(self.chunks)

    def __iter__(self):
        return iter(self.chunks)

    def to_chunks(self) -> list:
        return [chunk.to_chunk() for chunk in self.chunks]


# ------------------------------------------------------------------- rows


@dataclass(frozen=True, slots=True)
class _Row:
    """One rendered line of a passage: a real analysis line, or a member placeholder."""

    line: int | None
    text: str
    member: Symbol | None = None


def _header_rows(symbol: Symbol, members: list[Symbol], lines: list[str]) -> list[_Row]:
    """`chunker._header_rows`, re-expressed to remember which member each placeholder is.

    The committed helper returns `(line, text)` and drops the member, and the member
    is exactly what a generated placeholder has to name. The walk is otherwise
    identical line for line, and
    `test_the_reexpressed_header_rows_equal_the_committed_ones` pins the two equal.
    """
    rows: list[_Row] = []
    cursor = symbol.line_start
    last = min(symbol.line_end, len(lines))
    covered = 0
    for member in members:
        if member.line_start <= covered:
            continue
        rows.extend(_Row(n, lines[n - 1]) for n in range(cursor, min(member.line_start, last + 1)))
        rows.append(_Row(None, _placeholder(member, lines), member))
        cursor = max(cursor, member.line_end + 1)
        covered = max(covered, member.line_end)
    rows.extend(_Row(n, lines[n - 1]) for n in range(cursor, last + 1))
    return rows


def _regroup(rows: list[_Row], statement_lines: list[int], size: int) -> list[list[_Row]]:
    """Split with the committed `_split_rows`, then hand the members back.

    `_split_rows` partitions its input in order and never rewrites a row, so the
    concatenation of its groups is the input list; walking a cursor therefore
    restores the member each placeholder stood for without re-deciding a boundary.
    """
    groups = _split_rows([(row.line, row.text) for row in rows], statement_lines, size)
    out: list[list[_Row]] = []
    cursor = 0
    for group in groups:
        out.append(rows[cursor : cursor + len(group)])
        cursor += len(group)
    if cursor != len(rows):
        raise CodeChunkParityError("the committed row split did not partition its rows")
    return out


# ------------------------------------------------------------ line mapping


@dataclass(frozen=True, slots=True)
class _Lines:
    """Where every analysis line of one captured file starts and ends."""

    texts: tuple[str, ...]
    spans: tuple[tuple[int, int], ...]
    terminators: tuple[str, ...]

    @property
    def anchor(self) -> _Range:
        """A range a generated segment can always depend on.

        The analysis text is the original stripped, so its first character is never
        whitespace and its first line is therefore never empty.
        """
        start, end = self.spans[0]
        return _Range(start, end)

    def span(self, line: int) -> _Range | None:
        start, end = self.spans[line - 1]
        return _Range(start, end) if start < end else None

    def first_nonempty(self, start: int, end: int) -> _Range:
        for number in range(max(1, start), min(end, len(self.texts)) + 1):
            found = self.span(number)
            if found is not None:
                return found
        return self.anchor

    def joined_by_the_file(self, first: int, second: int) -> bool:
        """True when the newline the chunker writes between two rows is the file's own."""
        return second == first + 1 and self.terminators[first - 1] == "\n"


def _measure(unit: CodeUnit) -> _Lines:
    """The analysis lines exactly as `str.splitlines` cuts them, with their offsets."""
    analysis = unit.analysis_text
    texts: list[str] = []
    spans: list[tuple[int, int]] = []
    terminators: list[str] = []
    offset = 0
    for full in analysis.splitlines(keepends=True):
        content = full.splitlines()[0]
        texts.append(content)
        spans.append((offset, offset + len(content)))
        terminators.append(full[len(content) :])
        offset += len(full)
    if texts != analysis.splitlines():
        raise UnsupportedCodeChunkInput("Analysis line measurement does not match the legacy split")
    return _Lines(tuple(texts), tuple(spans), tuple(terminators))


def _coalesce(runs: list[_Run]) -> list[_Run]:
    """Merge original runs that are already adjacent in the file into one region."""
    merged: list[_Run] = []
    for run in runs:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.start is not None
            and run.start is not None
            and previous.start + len(previous.text) == run.start
        ):
            merged[-1] = _Run(previous.text + run.text, previous.start)
        else:
            merged.append(run)
    return merged


def _join_inputs(measured: _Lines, previous: _Row, row: _Row) -> tuple[_Range, ...]:
    """What a generated newline reads: the edge characters of the lines it sits between."""
    before = (
        measured.first_nonempty(previous.line, previous.line)
        if previous.line is not None
        else measured.first_nonempty(previous.member.line_start, previous.member.line_end)
    )
    after = (
        measured.first_nonempty(row.line, row.line)
        if row.line is not None
        else measured.first_nonempty(row.member.line_start, row.member.line_end)
    )
    return _unique((_Range(before.end - 1, before.end), _Range(after.start, after.start + 1)))


def _mapped_rows(measured: _Lines, rows: list[_Row]) -> tuple[_MappedText, list[tuple[Symbol, _Range]]]:
    """The passage's runs, in order, with every generated character marked.

    The chunker writes `"\\n".join(...)` over its rows and then strips the leading
    and trailing newlines. A newline between two consecutive real lines whose file
    terminator is exactly `"\\n"` *is* the file's own character, so it merges into the
    original region around it; every other newline is generated, as is every
    placeholder line.
    """
    runs: list[_Run] = []
    placeholders: list[tuple[Symbol, _Range]] = []
    previous: _Row | None = None
    for row in rows:
        if previous is not None:
            if (
                previous.line is not None
                and row.line is not None
                and measured.joined_by_the_file(previous.line, row.line)
            ):
                runs.append(_Run("\n", measured.spans[previous.line - 1][1]))
            else:
                runs.append(_Run("\n", None, CODE_LINE_JOIN_RULE, _join_inputs(measured, previous, row)))
        if row.line is None:
            anchor = measured.first_nonempty(row.member.line_start, row.member.line_end)
            placeholders.append((row.member, anchor))
            runs.append(_Run(row.text, None, CODE_PLACEHOLDER_RULE, (anchor,)))
        else:
            span = measured.span(row.line)
            if span is not None:
                runs.append(_Run(measured.texts[row.line - 1], span.start))
        previous = row
    mapped = _MappedText(tuple(_coalesce(runs)))
    text = str(mapped)
    left = len(text) - len(text.lstrip("\n"))
    return mapped[left : left + len(text.strip("\n"))], placeholders


# ------------------------------------------------------------ passage build


def _segments(unit: CodeUnit, mapped: _MappedText):
    """Translate a passage's runs into original and generated provenance segments."""
    document = unit.document
    segments: list[CodeSegment] = []
    dependencies: list[tuple[OriginalSegment, ...]] = []
    for run in mapped.runs:
        resolved = _translate(document, run.inputs)
        if run.start is not None:
            segments.extend(resolved)
            dependencies.extend((dep,) for dep in resolved)
        else:
            segments.append(GeneratedSegment(run.text, run.rule, _unique(d.unit_key for d in resolved)))
            dependencies.append(resolved)
    return tuple(segments), tuple(dependencies)


def _build(
    *,
    unit: CodeUnit,
    kind: str,
    title: str,
    mapped: _MappedText,
    defines: list[str],
    extract_text: str | None,
    symbol_id: str | None,
    data_object_ids: list[str],
    placeholders: list[tuple[Symbol, _Range]],
    profile: tuple[str, int, int],
    ordinal: int,
) -> PreparedCodeChunk:
    segments, dependencies = _segments(unit, mapped)
    declared = _unique(dep for group in dependencies for dep in group)
    marked = tuple((member.id, _translate(unit.document, (anchor,))[0]) for member, anchor in placeholders)
    return PreparedCodeChunk(
        ordinal=ordinal,
        kind=kind,
        title=title,
        text=str(mapped),
        defines=tuple(defines),
        extract_text=extract_text,
        logical_path=unit.logical_path,
        symbol_id=symbol_id,
        data_object_ids=tuple(data_object_ids),
        commit_id=None,
        commit_sha=None,
        original_units=unit.document.original_units,
        retrieval_segments=segments,
        segment_dependencies=dependencies,
        title_dependencies=(),
        original_dependencies=declared,
        originals=_original_closure(unit.document.original_units, declared),
        placeholders=marked,
        chunker_profile=profile,
        rule_version=CODE_CHUNK_RULE_VERSION,
    )


def _symbol_chunks(
    *,
    unit: CodeUnit,
    measured: _Lines,
    symbol: Symbol,
    rows: list[_Row],
    mentions: Mentions,
    settings: CodeChunkSettings,
    header: bool,
    start_ordinal: int,
) -> list[PreparedCodeChunk]:
    """`chunker._pieces_from_rows`, keeping the rows each passage was rendered from."""
    groups = [
        group
        for group in _regroup(rows, symbol.statement_lines, settings.effective_size)
        if _text_of([(row.line, row.text) for row in group]).strip()
    ]
    doc_text = symbol.doc if len(symbol.doc.strip()) >= MIN_OPENIE_DOC_CHARS else ""
    out: list[PreparedCodeChunk] = []
    for number, group in enumerate(groups, start=1):
        mapped, placeholders = _mapped_rows(measured, group)
        pairs = [(row.line, row.text) for row in group]
        first, last = _title_range(symbol, pairs, header=header, split=len(groups) > 1)
        part = f" (part {number})" if len(groups) > 1 else ""
        span = {row.line for row in group if row.line is not None}
        data_ids = _data_ids_in(mentions, unit.logical_path, span)
        out.append(
            _build(
                unit=unit,
                kind="header" if header else "symbol",
                title=f"{unit.logical_path} :: {symbol.display} (lines {first}-{last}){part}",
                mapped=mapped,
                defines=[symbol.id, *data_ids],
                extract_text=doc_text if number == 1 else "",
                symbol_id=symbol.id,
                data_object_ids=data_ids,
                placeholders=placeholders,
                profile=settings.profile,
                ordinal=start_ordinal + len(out),
            )
        )
    return out


def _container_chunks(
    *,
    unit: CodeUnit,
    measured: _Lines,
    symbol: Symbol,
    symbols: list[Symbol],
    mentions: Mentions,
    settings: CodeChunkSettings,
    start_ordinal: int,
) -> list[PreparedCodeChunk]:
    """`chunker._container_pieces`: the container's header, then a passage per member."""
    lines = list(measured.texts)
    members = _members(symbol, symbols)
    rows = _header_rows(symbol, _placeholders(symbol, symbols, members), lines)
    out: list[PreparedCodeChunk] = []
    if any(row.line is not None and row.text.strip() for row in rows):
        out.extend(
            _symbol_chunks(
                unit=unit,
                measured=measured,
                symbol=symbol,
                rows=rows,
                mentions=mentions,
                settings=settings,
                header=True,
                start_ordinal=start_ordinal,
            )
        )
    for member in members:
        if member.kind in CONTAINER_KINDS:
            out.extend(
                _container_chunks(
                    unit=unit,
                    measured=measured,
                    symbol=member,
                    symbols=symbols,
                    mentions=mentions,
                    settings=settings,
                    start_ordinal=start_ordinal + len(out),
                )
            )
        else:
            out.extend(
                _symbol_chunks(
                    unit=unit,
                    measured=measured,
                    symbol=member,
                    rows=[_Row(n, lines[n - 1]) for n in _line_numbers(member, lines)],
                    mentions=mentions,
                    settings=settings,
                    header=False,
                    start_ordinal=start_ordinal + len(out),
                )
            )
    return out


def _window_chunks(
    *,
    unit: CodeUnit,
    measured: _Lines,
    kind: str,
    mentions: Mentions,
    settings: CodeChunkSettings,
    start_ordinal: int,
) -> list[PreparedCodeChunk]:
    """`chunker._chunk_code` and `_chunk_sql`: line windows, titled by the lines they hold."""
    lines = list(measured.texts)
    out: list[PreparedCodeChunk] = []
    for first, last in code_windows(lines, settings.effective_size):
        mapped, placeholders = _mapped_rows(
            measured, [_Row(n, lines[n - 1]) for n in range(first + 1, last + 1)]
        )
        if not str(mapped).strip():
            continue
        data_ids = (
            _data_ids_in(mentions, unit.logical_path, set(range(first + 1, last + 1)))
            if kind == "data_object"
            else []
        )
        out.append(
            _build(
                unit=unit,
                kind=kind,
                title=f"{unit.logical_path} (lines {first + 1}-{last})",
                mapped=mapped,
                defines=list(data_ids),
                extract_text="" if kind == "data_object" else None,
                symbol_id=None,
                data_object_ids=data_ids,
                placeholders=placeholders,
                profile=settings.profile,
                ordinal=start_ordinal + len(out),
            )
        )
    return out


def _prose_chunks(
    *, unit: CodeUnit, settings: CodeChunkSettings, start_ordinal: int
) -> list[PreparedCodeChunk]:
    """A captured file the legacy chunker packs as prose, through the reviewed seam.

    CC4 accepts extensionless known-text names (`README`, `Makefile`, `LICENSE`) and
    `go.mod`; none of them is in `CODE_EXTENSIONS`, so `chunk_document` sends them
    down its prose branch. `prepare_prose_chunks` already maps that branch exactly
    and carries its own parity gate, so this delegates rather than re-deriving it.
    """
    prepared = prepare_prose_chunks(
        (unit.document,), size_chars=settings.size_chars, overlap_chars=settings.overlap_chars
    )
    return [
        PreparedCodeChunk(
            ordinal=start_ordinal + offset,
            kind="prose",
            title=chunk.title,
            text=chunk.text,
            defines=(),
            extract_text=chunk.extract_text,
            logical_path=unit.logical_path,
            symbol_id=None,
            data_object_ids=(),
            commit_id=None,
            commit_sha=None,
            original_units=chunk.original_units,
            retrieval_segments=chunk.retrieval_segments,
            segment_dependencies=chunk.segment_dependencies,
            title_dependencies=chunk.title_dependencies,
            original_dependencies=chunk.original_dependencies,
            originals=chunk.originals,
            placeholders=(),
            chunker_profile=chunk.chunker_profile,
            rule_version=CODE_CHUNK_RULE_VERSION,
        )
        for offset, chunk in enumerate(prepared)
    ]


def _commit_chunks(
    *, facts: CodeGraph | None, settings: CodeChunkSettings, start_ordinal: int
) -> list[PreparedCodeChunk]:
    """`chunker._chunk_commits`, wrapped: the whole passage is rendered, nothing is quoted."""
    rendered = _chunk_commits(facts, settings.size_chars)
    if not rendered:
        return []
    if facts is None or len(rendered) != len(facts.commits):
        raise CodeChunkParityError("the committed commit chunker did not emit one passage per commit")
    out: list[PreparedCodeChunk] = []
    for offset, (commit, chunk) in enumerate(zip(facts.commits, rendered, strict=True)):
        commit_id = commit["id"]
        if chunk.defines != [commit_id]:
            raise CodeChunkParityError("a commit passage does not define its own commit")
        segments = (CommitSegment(chunk.text, CODE_COMMIT_RULE, commit_id),) if chunk.text else ()
        out.append(
            PreparedCodeChunk(
                ordinal=start_ordinal + offset,
                kind="commit",
                title=chunk.title,
                text=chunk.text,
                defines=tuple(chunk.defines),
                extract_text=chunk.extract_text,
                logical_path=None,
                symbol_id=None,
                data_object_ids=(),
                commit_id=commit_id,
                commit_sha=commit["sha"],
                original_units=(),
                retrieval_segments=segments,
                segment_dependencies=tuple(() for _ in segments),
                title_dependencies=(),
                original_dependencies=(),
                originals=(),
                placeholders=(),
                chunker_profile=settings.profile,
                rule_version=CODE_CHUNK_RULE_VERSION,
            )
        )
    return out


# ------------------------------------------------------------------ entry


def _accept(captured: object) -> CapturedCode:
    """Refuse anything but CC4's untouched capture mapping for one accepted input."""
    if type(captured) is not CapturedCode:
        raise UnsupportedCodeChunkInput("Code chunk preparation accepts captured code provenance only")
    unit = captured.unit
    if unit is None:
        return captured
    if unit.logical_path != captured.logical_path or unit.input_key != captured.input_key:
        raise UnsupportedCodeChunkInput("A captured unit and its accepted input name different files")
    document, original = unit.document, unit.original
    trim_start = len(original.text) - len(original.text.lstrip())
    expected = OriginalSegment(original.unit_key, trim_start, trim_start + len(document.analysis_text))
    if document.analysis_text != original.text.strip() or document.segments != (expected,):
        raise UnsupportedCodeChunkInput("Only CC4's exact capture trim mapping is supported")
    if document.title != unit.logical_path:
        raise UnsupportedCodeChunkInput("A passage title and its file locator must name one path")
    return captured


def _replace_defines(chunk: PreparedCodeChunk, defines: tuple[str, ...]) -> PreparedCodeChunk:
    """A frozen rebuild; `dataclasses.replace` cannot recompute the derived chunk key."""
    values = {
        item.name: getattr(chunk, item.name) for item in fields(chunk) if item.init and item.name != "defines"
    }
    return PreparedCodeChunk(defines=defines, **values)


def _file_chunks(
    *,
    unit: CodeUnit,
    facts: CodeGraph | None,
    mentions: Mentions,
    settings: CodeChunkSettings,
    start_ordinal: int,
) -> list[PreparedCodeChunk]:
    """The branch `chunk_document` would take for this file, with its provenance kept."""
    measured = _measure(unit)
    path = unit.logical_path
    windows = dict(unit=unit, measured=measured, mentions=mentions, settings=settings)
    if facts is not None and facts.parsed(path):
        if lang_of(path) == "sql":
            return _window_chunks(**windows, kind="data_object", start_ordinal=start_ordinal)
        symbols = facts.by_path(path)
        module = _file_module(symbols)
        if module is None:  # parsed, but nothing to cut by: today's windows
            return _window_chunks(**windows, kind="window", start_ordinal=start_ordinal)
        chunks = _container_chunks(
            unit=unit,
            measured=measured,
            symbol=module,
            symbols=symbols,
            mentions=mentions,
            settings=settings,
            start_ordinal=start_ordinal,
        )
        if chunks and not any(module.id in chunk.defines for chunk in chunks):
            # `chunker._chunk_symbols`: a file that opens with `class Base:` has no module
            # header passage, so its first passage is where the module is defined.
            chunks[0] = _replace_defines(chunks[0], (module.id, *chunks[0].defines))
        return chunks
    if unit.is_code:
        return _window_chunks(**windows, kind="window", start_ordinal=start_ordinal)
    return _prose_chunks(unit=unit, settings=settings, start_ordinal=start_ordinal)


def prepare_code_chunks(
    units: Iterable[CapturedCode],
    *,
    facts: CodeGraph | None,
    settings: CodeChunkSettings,
    max_chunks: int,
) -> PreparedCodeChunks:
    """Map every captured code file to the passages the legacy chunker produces.

    `units` is one `CapturedCode` per captured file, in capture order; a binary or
    empty one produces no passage and one explicit refusal. `facts` is the resolved
    `CodeGraph` for the same files, or `None` when nothing was extracted.
    `max_chunks` is the passage ceiling of plan section 8.3; it is an argument
    rather than an import because it is an operational limit that stays out of
    generation identity, and because `ingest.pipeline` imports this lane rather
    than the other way round.

    Raises `TooManyCodeChunks` past the ceiling and `CodeChunkParityError` if the
    mapped passages and the committed chunker's passages differ at all. Neither
    message quotes a path, a passage or a commit message (plan section 10).
    """
    if type(settings) is not CodeChunkSettings:
        raise UnsupportedCodeChunkInput("Code chunk preparation requires frozen chunk settings")
    if type(max_chunks) is not int or max_chunks < 1:
        raise ValueError("The passage ceiling must be a positive integer")
    if facts is not None and type(facts) is not CodeGraph:
        raise UnsupportedCodeChunkInput("Code chunk preparation requires a resolved code graph")
    captured = [_accept(item) for item in units]
    paths = [item.logical_path for item in captured]
    if len(set(paths)) != len(paths):
        raise UnsupportedCodeChunkInput("Two captured inputs claim one logical path")

    mentions = _mention_index(facts)
    chunks: list[PreparedCodeChunk] = []
    refusals: list[CodeChunkRefusal] = []
    for item in captured:
        if item.unit is None:
            refusals.append(CodeChunkRefusal(item.input_key, item.logical_path, item.provenance.outcome))
            continue
        chunks.extend(
            _file_chunks(
                unit=item.unit,
                facts=facts,
                mentions=mentions,
                settings=settings,
                start_ordinal=len(chunks),
            )
        )
    chunks.extend(_commit_chunks(facts=facts, settings=settings, start_ordinal=len(chunks)))
    if len(chunks) > max_chunks:
        raise TooManyCodeChunks(
            f"too large: this source makes {len(chunks):,} passages; the limit is {max_chunks:,}"
        )
    _latch(captured, facts, settings, chunks)
    return PreparedCodeChunks(CODE_CHUNK_RULE_VERSION, settings.profile, tuple(chunks), tuple(refusals))


def _latch(
    captured: list[CapturedCode],
    facts: CodeGraph | None,
    settings: CodeChunkSettings,
    chunks: list[PreparedCodeChunk],
) -> None:
    """Refuse to return anything the committed chunker would not have produced."""
    documents = [item.unit.to_document() for item in captured if item.unit is not None]
    expected = chunk_documents(documents, settings.size_chars, settings.overlap_chars, code=facts)
    actual = [chunk.to_chunk() for chunk in chunks]
    if actual == expected:
        return
    for position, (mine, theirs) in enumerate(zip(actual, expected, strict=False)):
        if mine != theirs:
            raise CodeChunkParityError(
                f"mapped passage {position} ({chunks[position].kind}) differs from the legacy chunker"
            )
    raise CodeChunkParityError(
        f"the legacy chunker produced {len(expected):,} passages and the mapping produced {len(actual):,}"
    )


__all__ = [
    "CODE_CHUNKER_PROFILE",
    "CODE_CHUNK_FIXTURE_DIGEST",
    "CODE_CHUNK_KINDS",
    "CODE_CHUNK_RULE_VERSION",
    "CODE_COMMIT_RULE",
    "CODE_LINE_JOIN_RULE",
    "CODE_PLACEHOLDER_RULE",
    "CODE_REFUSAL_REASONS",
    "CapturedCode",
    "CodeChunkParityError",
    "CodeChunkRefusal",
    "CodeChunkSettings",
    "CodeSegment",
    "CommitSegment",
    "PreparedCodeChunk",
    "PreparedCodeChunks",
    "TooManyCodeChunks",
    "UnsupportedCodeChunkInput",
    "prepare_code_chunks",
    "segment_descriptors",
]
