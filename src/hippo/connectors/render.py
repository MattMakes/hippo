"""Rendering: the label, the fact templates, the edge statement and the unit prefixes.

Design `docs/spec/connector-developer-kit.md` sections 4 and 6, plan `ai_docs/plans/cdk-s2-contract.md`
sections 4.4 and 7. The specification's rendering rules as code: one template invocation is one unit,
and nothing ever joins two outputs, so forty column nodes render forty units.

Nothing here reads a store, a model, the network or a clock; every function is a pure function of its
arguments. Rendered text carries no version of its own (ruling R20): a template's `name@version` and
the registry fingerprint cover it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ..knowledge.identity import text_hash
from ..knowledge.registry import ObjectKindDefinition, PredicateDefinition
from .base import ContractError

if TYPE_CHECKING:  # `keys` imports `emit`, which imports this module; rendering needs only the type
    from .keys import CanonicalKey

RENDER_RULE_VERSION = "cdk-render-v1"
PREFIX_TOKEN_LIMIT = 12
PREFIX_SEPARATOR = ": "


@dataclass(frozen=True, slots=True)
class RenderedText:
    """One template output, with the two hashes S1's `Unit` stores (D15, D17)."""

    text: str
    prefix: str
    embed_text: str
    content_hash: str
    embed_hash: str
    template: str | None


def kind_label(definition: ObjectKindDefinition) -> str:
    """The display label of a kind; the registry has no display name, so the code reads as prose."""
    return definition.name.replace("_", " ")


def render_label(definition: ObjectKindDefinition, attrs: BaseModel) -> str:
    """`label_template` over the attributes. S1 refuses an unknown field at registration (refusal 11).

    A `KeyError` here still means a definition and a model that disagree, which is the developer's
    to fix, so it is reported as a refusal rather than as a traceback.
    """
    try:
        return definition.label_template.format_map(attrs.model_dump(mode="json"))
    except KeyError as error:
        name = error.args[0] if error.args else "?"
        raise ContractError(
            f"Label template of {definition.name} names a missing attribute {name}"
        ) from error


def render_facts(
    definition: ObjectKindDefinition, attrs: BaseModel, *, label: str, key: CanonicalKey
) -> tuple[RenderedText, ...]:
    """One `RenderedText` per invoked fact template, in registration order.

    A template whose consumed attribute is `None` is not invoked: no unit and no error (S6 R-S2-5).
    An open incident has no resolution to state, and stating one would be an unearned claim. The
    caller counts the omission; `skipped_fact_templates` names it.
    """
    values = attrs.model_dump(mode="json")
    rendered = []
    for template in definition.fact_templates:
        if _skipped(template, values):
            continue
        fields = {name: values[name] for name in template.consumes}
        rendered.append(
            unit_text(
                template.text.format_map(fields | {"label": label, "key": key.readable}),
                template=f"{template.name}@{template.version}",
            )
        )
    return tuple(rendered)


def skipped_fact_templates(definition: ObjectKindDefinition, attrs: BaseModel) -> tuple[str, ...]:
    """The `name@version` of every template `render_facts` does not invoke, for coverage."""
    values = attrs.model_dump(mode="json")
    return tuple(
        f"{template.name}@{template.version}"
        for template in definition.fact_templates
        if _skipped(template, values)
    )


def _skipped(template, values: dict) -> bool:
    return any(values.get(name) is None for name in template.consumes)


def edge_statement(
    predicate: PredicateDefinition,
    subject: tuple[ObjectKindDefinition, str],
    object_: tuple[ObjectKindDefinition, str],
    *,
    source_statement: str | None = None,
    rule: str | None = None,
    rule_evidence: str | None = None,
) -> str:
    """The sentence that justifies an edge, in the specification's section 3 shape.

    S1's built-in verb phrases name no endpoint kind (S1 section 10), so the kind labels here are
    never doubled.
    """
    subject_definition, subject_label = subject
    object_definition, object_label = object_
    statement = (
        f"{kind_label(subject_definition)} {subject_label} "
        f"{predicate.verb_phrase} "
        f"{kind_label(object_definition)} {object_label}"
    )
    if source_statement is not None:
        statement = f"{statement}: {source_statement}"
    if rule is not None and rule_evidence is not None:
        statement = f"{statement} ({rule.replace('_', ' ')}: {rule_evidence})"
    return statement


def heading_prefix(heading_path: tuple[str, ...]) -> str:
    """The innermost heading, cut to `PREFIX_TOKEN_LIMIT` tokens, with the separator."""
    if not heading_path:
        return ""
    tokens = heading_path[-1].split()
    return " ".join(tokens[:PREFIX_TOKEN_LIMIT]) + PREFIX_SEPARATOR


def symbol_prefix(symbol: str) -> str:
    """The enclosing symbol with the separator: the specification's "{symbol}: {source line}"."""
    return symbol + PREFIX_SEPARATOR


def unit_text(text: str, *, prefix: str = "", template: str | None = None) -> RenderedText:
    """`embed_text = prefix + text`, with the content and embedding hashes S1's `Unit` requires.

    Identical text under two headings shares `content_hash` and not `embed_hash`, which is what
    makes the boilerplate weight of the specification's section 7.2 work while the vectors differ.
    """
    embed_text = prefix + text
    return RenderedText(
        text=text,
        prefix=prefix,
        embed_text=embed_text,
        content_hash=text_hash(text),
        embed_hash=text_hash(embed_text),
        template=template,
    )
