"""Source locator models: the seven built-in kinds and the base every registered locator subclasses.

`SourceLocator` stays the discriminated union of the built-ins; validation by a payload's `kind`
goes through the ontology registry (`model.parse_locator_json`), which also knows extension kinds.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from .contract import Contract, Nonnegative, Positive, RelativePath, Text


class LocatorBase(Contract):
    """Every registered locator model subclasses this; its `kind` field defaults to its name."""


class FileLinesLocator(LocatorBase):
    kind: Literal["file_lines"] = "file_lines"
    path: RelativePath
    start: Positive
    end: Positive

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("Line interval is reversed")
        return self


class SectionLocator(LocatorBase):
    kind: Literal["section"] = "section"
    heading_path: tuple[Text, ...]
    block_start: Nonnegative
    block_end: Nonnegative

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.block_end < self.block_start:
            raise ValueError("Block interval is reversed")
        return self


class FieldLocator(LocatorBase):
    kind: Literal["field"] = "field"
    field_path: Text


class CommentLocator(LocatorBase):
    kind: Literal["comment"] = "comment"
    comment_id: Text
    field_path: Text = "body"
    changeset_id: Text | None = None


class PageLocator(LocatorBase):
    kind: Literal["page"] = "page"
    page: Positive
    offset_start: Nonnegative = 0
    offset_end: Nonnegative | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.offset_end is not None and self.offset_end < self.offset_start:
            raise ValueError("Page offsets are reversed")
        return self


class TableCellLocator(LocatorBase):
    kind: Literal["table_cell"] = "table_cell"
    table: Nonnegative
    row: Nonnegative
    column: Nonnegative
    heading_path: tuple[Text, ...] = ()


class DiffHunkLocator(FileLinesLocator):
    kind: Literal["diff_hunk"] = "diff_hunk"
    base_revision: Text
    head_revision: Text
    side: Literal["base", "head"]
    hunk_id: Text | None = None


SourceLocator = Annotated[
    FileLinesLocator
    | SectionLocator
    | FieldLocator
    | CommentLocator
    | PageLocator
    | TableCellLocator
    | DiffHunkLocator,
    Field(discriminator="kind"),
]
LOCATOR_ADAPTER = TypeAdapter(SourceLocator)
