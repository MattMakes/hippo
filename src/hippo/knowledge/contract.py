"""Contract primitives shared by the knowledge model, the locator models and the ontology registry.

They live outside `model.py` so the registry's definition classes and the model's validators can
share them without importing each other. `model.py` re-exports every name.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

from .identity import normalize_json, normalize_provider_url, normalize_relative_path

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Json = Annotated[str, BeforeValidator(normalize_json)]
Code = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")]
Nonnegative = Annotated[int, Field(strict=True, ge=0)]
Positive = Annotated[int, Field(strict=True, ge=1)]
VersionOne = Annotated[int, Field(strict=True, ge=1, le=1)]
EvidenceClass = Literal[
    "syntax_observed",
    "catalog_observed",
    "declared",
    "discussion_claim",
    "model_inferred",
    "human_verified",
    "rule_derived",
    "similarity_inferred",
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must carry a timezone")
    return value.astimezone(UTC)


Instant = Annotated[datetime, AfterValidator(_utc)]
RelativePath = Annotated[str, AfterValidator(normalize_relative_path)]
ProviderURL = Annotated[str, AfterValidator(normalize_provider_url)]


class Contract(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, revalidate_instances="always", validate_default=True
    )

    def replace(self, **changes) -> Self:
        return type(self).model_validate(self.model_dump() | changes)

    def model_copy(self, *, update=None, deep=False) -> Self:
        if update:
            return self.replace(**update)
        return type(self).model_validate(self.model_dump())
