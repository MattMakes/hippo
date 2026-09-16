"""The vocabulary the fixture connector registers (plan `cdk-s3-runtime.md` section 11).

One object kind, `fixture_note`, in the built-in `custom` family, with one fact template; one
predicate, `FIXTURE_LINKS`, that `custom` owns. Nothing here is ever registered automatically:
a test installs it with `extension_scope()` or `use_registry()` (ruling R10, finding N1 of the S4
re-review).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from hippo.knowledge.registry import (
    FactTemplate,
    ObjectKindDefinition,
    PredicateDefinition,
    TypeExtension,
)

FIXTURE_CONNECTOR_KIND = "fixture"
FIXTURE_NOTE_KIND = "fixture_note"
FIXTURE_LINKS = "FIXTURE_LINKS"
FIXTURE_FAMILY = "custom"


class FixtureNoteAttributes(BaseModel):
    """A note's typed attributes; `extra="forbid"` is required of every extension kind (S1 D5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    updated: str | None = None


def fixture_note_kind(**overrides) -> ObjectKindDefinition:
    fields = {
        "name": FIXTURE_NOTE_KIND,
        "family": FIXTURE_FAMILY,
        # `instance` is filled by the kit's key builder and never emitted (S4 scaffold note).
        "key_template": ("instance", "note_id"),
        "key_prefix": "note",
        "attrs_model": FixtureNoteAttributes,
        "label_template": "{title}",
        "fact_templates": (
            FactTemplate(
                name="note_summary",
                version="1",
                consumes=("title", "updated"),
                text="Note {key} titled {title} was updated {updated}",
            ),
        ),
    }
    return ObjectKindDefinition(**(fields | overrides))


def fixture_links_predicate(**overrides) -> PredicateDefinition:
    fields = {
        "name": FIXTURE_LINKS,
        "subject_kinds": frozenset({FIXTURE_NOTE_KIND}),
        "object_kinds": frozenset({FIXTURE_NOTE_KIND}),
        "owner_families": frozenset({FIXTURE_FAMILY}),
        "canonical_direction": "subject_to_object",
        "family_default": "deterministic",
        "sources_allowed": frozenset({"metadata"}),
        "verb_phrase": "links to",
    }
    return PredicateDefinition(**(fields | overrides))


def fixture_extension(**overrides) -> TypeExtension:
    fields = {
        "object_kinds": (fixture_note_kind(),),
        "predicates": (fixture_links_predicate(),),
        "connector_kinds": (FIXTURE_CONNECTOR_KIND,),
    }
    return TypeExtension(**(fields | overrides))


FIXTURE_EXTENSION = fixture_extension()
