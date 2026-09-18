"""Classification on connect: declaration, then content, then name; the first decision wins.

Design `docs/spec/connector-developer-kit.md` section 2, plan `ai_docs/plans/cdk-s2-contract.md`
section 5. The classifier is a pure function of the descriptor, the configuration and the sampled
bytes: it opens no socket, runs no subprocess and reads no clock, so `probe` returns the same
`Classification` for the same bytes on every run, and `emit` reclassifies identically from the stored
`TypeMapping.classifier`.

What none of the three rules decides is `custom/unclassified`: a count and an evidence row, never an
object kind and never a silent drop.
"""

from __future__ import annotations

import csv
import fnmatch
import io
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import groupby
from pathlib import PurePosixPath

import sqlglot
from pydantic import BaseModel
from sqlglot import exp
from sqlglot.errors import ErrorLevel, SqlglotError

from ..ingest import readers
from ..knowledge.model import Code, Contract, Text
from ..knowledge.registry import CUSTOM_FAMILY, Registry, UnregisteredName
from . import base

CLASSIFIER_VERSION = "cdk-classify-v1"

_SQL_STATEMENTS = (
    exp.Create,
    exp.Alter,
    exp.Drop,
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Select,
)
_SQL_DDL = (exp.Create, exp.Alter, exp.Drop)
_CATALOG_FILES = {"catalog-info.yaml", "catalog-info.yml"}
_BACKSTAGE = re.compile(r"^apiVersion:\s*backstage\.io/", re.MULTILINE)
_API_HEADER = re.compile(r"^(openapi|asyncapi|swagger)\s*:")
_API_KEYS = {"openapi", "asyncapi", "swagger"}
_K8S_API_VERSION = re.compile(r"^apiVersion:\s*\S", re.MULTILINE)
_K8S_KIND = re.compile(r"^kind:\s*\S", re.MULTILINE)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
# The document signatures of the specification's section 5.1, tried in this order.
_SIGNATURES = (
    ("adr", frozenset({"status", "context", "decision", "consequences"})),
    ("prd", frozenset({"problem", "goals", "requirements", "non-goals"})),
    ("runbook", frozenset({"prerequisites", "steps", "verification", "rollback"})),
    ("postmortem", frozenset({"summary", "impact", "timeline", "root cause", "action items"})),
)


class SampledItem(Contract):
    partition: Code
    path: Text  # a normalized relative path, or a provider record type for an API connector
    data: bytes
    provider_type: Text | None = None


@dataclass(frozen=True, slots=True)
class ItemDecision:
    family: str  # a registered family, or CUSTOM_FAMILY
    kind: str | None
    template: str | None
    dialect: str | None
    evidence: base.ClassificationEvidence
    # `declared_tabular_shape_missing` and `tabular_without_declared_kind` reach the partition's
    # `warnings` through here; the plan's dataclass has no other place to carry them.
    warnings: tuple[str, ...] = ()

    @property
    def unclassified(self) -> bool:
        return self.evidence.outcome == base.UNCLASSIFIED


def classifier_spec(
    *, declarations: tuple[base.PathDeclaration, ...] = (), sql_dialects: tuple[str, ...] = ()
) -> base.ClassifierSpec:
    """The procedure `classify_item` follows, stored in the mapping so emit repeats it exactly."""
    return base.ClassifierSpec(
        version=CLASSIFIER_VERSION, declarations=tuple(declarations), sql_dialects=tuple(sql_dialects)
    )


def classify_item(item: SampledItem, spec: base.ClassifierSpec) -> ItemDecision:
    """Decide one sampled item: declaration, then content, then name (design §2)."""
    warnings: tuple[str, ...] = ()
    for declaration in spec.declarations:
        if not fnmatch.fnmatchcase(item.path, declaration.pattern):
            continue
        if declaration.shape == "tabular":
            text = _text(item.data)
            if text is None or _tabular(text) is None:
                warnings = ("declared_tabular_shape_missing",)
                break
        return _decided(
            item,
            declaration.family,
            rule="declaration",
            detector="declaration",
            kind=declaration.kind,
            template=declaration.template,
            dialect=declaration.dialect,
        )
    text = _text(item.data)
    if text is not None:
        content = _content(item, text, spec)
        if content is not None:
            return _with(content, warnings)
    name = _name(item)
    if name is not None:
        return _with(name, warnings)
    return _with(_unclassified(item, rule="unclassified", detector="none"), warnings)


def classify(
    descriptor: base.ConnectorDescriptor,
    config: BaseModel,
    items: Iterable[SampledItem],
    registry: Registry,
    *,
    spec: base.ClassifierSpec,
    capabilities: base.ConnectorCapabilities,
    kinds: tuple[base.KindMapping, ...] = (),
    attributes: tuple[base.AttributeMapping, ...] = (),
) -> base.Classification:
    """One `PartitionClassification` per partition of the sample, with the evidence of every decision.

    A mapping that names a kind nothing registered is a registration request, not a mapping: the
    `RegistrationRequired` propagates and no `Classification` is returned (design §2).
    """
    mapped = {mapping.provider_type: mapping.kind for mapping in kinds}
    fallback = descriptor.families[0] if len(descriptor.families) == 1 else CUSTOM_FAMILY
    partitions = []
    ordered = sorted(items, key=lambda item: (item.partition, item.path))
    for partition, group in groupby(ordered, key=lambda item: item.partition):
        decisions = [
            _provider_decision(item, mapped, registry, fallback)
            if item.provider_type is not None
            else classify_item(item, spec)
            for item in group
        ]
        partitions.append(
            _partition(
                partition,
                decisions,
                descriptor=descriptor,
                registry=registry,
                spec=spec,
                capabilities=capabilities,
                kinds=kinds,
                attributes=attributes,
                fallback=fallback,
            )
        )
    return base.Classification(
        connector=descriptor.name,
        connector_version=descriptor.version,
        registry_fingerprint=registry.fingerprint(),
        partitions=tuple(partitions),
    )


def _partition(
    partition: str,
    decisions: list[ItemDecision],
    *,
    descriptor: base.ConnectorDescriptor,
    registry: Registry,
    spec: base.ClassifierSpec,
    capabilities: base.ConnectorCapabilities,
    kinds: tuple[base.KindMapping, ...],
    attributes: tuple[base.AttributeMapping, ...],
    fallback: str,
) -> base.PartitionClassification:
    decided = {decision.family for decision in decisions if not decision.unclassified}
    family = decided.pop() if len(decided) == 1 else fallback
    counts: dict[str, int] = {}
    for decision in decisions:
        key = base.UNCLASSIFIED if decision.unclassified else decision.family
        counts[key] = counts.get(key, 0) + 1
    mapping = base.TypeMapping(
        family=family,
        kinds=kinds,
        predicates=descriptor.predicates,
        attributes=attributes,
        classifier=spec,
    )
    mapping.validate_against(registry)
    evidence = [decision.evidence for decision in decisions]
    evidence.extend(
        base.ClassificationEvidence(
            level="attribute",
            rule="descriptor",
            detector="attribute_mapping",
            subject=attribute.provider_field,
            outcome=f"{attribute.kind}.{attribute.attribute}",
        )
        for attribute in attributes
    )
    warnings = sorted({warning for decision in decisions for warning in decision.warnings})
    return base.PartitionClassification(
        partition=partition,
        family=family,
        mapping=mapping,
        capabilities=capabilities,
        sample_count=len(decisions),
        counts=counts,
        warnings=tuple(warnings),
        evidence=tuple(evidence),
    )


def _provider_decision(
    item: SampledItem, mapped: dict[str, str | None], registry: Registry, fallback: str
) -> ItemDecision:
    """A provider record type: the `KindMapping` rows decide, and an unmapped type is counted."""
    kind = mapped.get(item.provider_type)
    if kind is None:
        return ItemDecision(
            family=fallback,
            kind=None,
            template=None,
            dialect=None,
            evidence=base.ClassificationEvidence(
                level="family",
                rule="unclassified",
                detector="kind_mapping",
                subject=item.provider_type,
                outcome=base.UNCLASSIFIED,
            ),
        )
    try:
        family = registry.object_kind(kind).family
    except UnregisteredName:
        # The mapping's own `validate_against` refuses the whole classification with the extension
        # the developer must write, so this family is never returned to a caller.
        family = fallback
    return ItemDecision(
        family=family,
        kind=kind,
        template=None,
        dialect=None,
        evidence=base.ClassificationEvidence(
            level="kind",
            rule="descriptor",
            detector="kind_mapping",
            subject=item.provider_type,
            outcome=f"{family}/{kind}",
        ),
    )


def _decided(
    item: SampledItem,
    family: str,
    *,
    rule: str,
    detector: str,
    kind: str | None = None,
    template: str | None = None,
    dialect: str | None = None,
    warnings: tuple[str, ...] = (),
) -> ItemDecision:
    return ItemDecision(
        family=family,
        kind=kind,
        template=template,
        dialect=dialect,
        evidence=base.ClassificationEvidence(
            level="kind" if kind else "family",
            rule=rule,
            detector=detector,
            subject=item.path,
            outcome=f"{family}/{kind}" if kind else family,
        ),
        warnings=warnings,
    )


def _unclassified(
    item: SampledItem, *, rule: str, detector: str, warnings: tuple[str, ...] = ()
) -> ItemDecision:
    return ItemDecision(
        family=CUSTOM_FAMILY,
        kind=None,
        template=None,
        dialect=None,
        evidence=base.ClassificationEvidence(
            level="family",
            rule=rule,
            detector=detector,
            subject=item.path,
            outcome=base.UNCLASSIFIED,
        ),
        warnings=warnings,
    )


def _with(decision: ItemDecision, warnings: tuple[str, ...]) -> ItemDecision:
    if not warnings:
        return decision
    kept = tuple(dict.fromkeys(warnings + decision.warnings))
    return ItemDecision(
        family=decision.family,
        kind=decision.kind,
        template=decision.template,
        dialect=decision.dialect,
        evidence=decision.evidence,
        warnings=kept,
    )


def _text(data: bytes) -> str | None:
    """The document's text, or None when the bytes are binary or not strict UTF-8 (`plain-utf8-sig-v1`)."""
    if readers.is_probably_binary(data):
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _content(item: SampledItem, text: str, spec: base.ClassifierSpec) -> ItemDecision | None:
    dialect = _sql_ddl(text, spec)
    if dialect is not None:
        return _decided(item, "db", rule="content", detector=f"sqlglot.ddl:{dialect}", dialect=dialect)
    document = _json(text)
    if PurePosixPath(item.path).name.lower() in _CATALOG_FILES and _BACKSTAGE.search(text):
        return _decided(item, "service", rule="content", detector="backstage.catalog", kind="service")
    if _API_HEADER.match(_first_line(text)) or (isinstance(document, dict) and _API_KEYS & set(document)):
        return _decided(item, "service", rule="content", detector="api.header", kind="api")
    head = _first_document(text)
    manifest = _K8S_API_VERSION.search(head) and _K8S_KIND.search(head)
    if manifest or (isinstance(document, dict) and {"apiVersion", "kind"} <= set(document)):
        return _decided(item, "service", rule="content", detector="k8s.manifest")
    template = _signature(text)
    if template is not None:
        return _decided(item, "prose", rule="content", detector="heading.signature", template=template)
    tabular = _tabular(text, document=document)
    if tabular is not None:
        # The design admits tabular rendered facts only under a declared kind, and a declaration
        # would have decided this item already.
        return _unclassified(
            item, rule="content", detector=tabular, warnings=("tabular_without_declared_kind",)
        )
    return None


def _name(item: SampledItem) -> ItemDecision | None:
    if readers.lang_of(item.path) is not None:
        return _decided(item, "code", rule="name", detector="readers.lang_of")
    if readers.is_code_name(item.path):
        return _decided(item, "code", rule="name", detector="readers.is_code_name")
    if readers.is_plain_prose_name(item.path):
        return _decided(item, "prose", rule="name", detector="readers.is_plain_prose_name")
    if readers.is_probably_binary(item.data):
        return _unclassified(item, rule="name", detector="readers.is_probably_binary")
    return None


def _sql_ddl(text: str, spec: base.ClassifierSpec) -> str | None:
    """The first declared dialect whose parse is a schema script: statements only, with a DDL one.

    sqlglot falls back to `Command` for syntax it does not support, which is not a successful parse,
    and prose that happens to parse as a `SELECT` is not a schema.
    """
    for dialect in spec.sql_dialects:
        try:
            parsed = sqlglot.parse(text, dialect=dialect, error_level=ErrorLevel.RAISE)
        except (SqlglotError, ValueError, RecursionError):
            continue
        statements = [statement for statement in parsed if statement is not None]
        if not statements or any(isinstance(statement, exp.Command) for statement in statements):
            continue
        if not all(isinstance(statement, _SQL_STATEMENTS) for statement in statements):
            continue
        if any(isinstance(statement, _SQL_DDL) for statement in statements):
            return dialect
    return None


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _first_document(text: str) -> str:
    """The lines before the first `---` separator, skipping a leading one."""
    lines = text.splitlines()
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].strip() == "---"):
        start += 1
    head = []
    for line in lines[start:]:
        if line.strip() == "---":
            break
        head.append(line)
    return "\n".join(head)


def _signature(text: str) -> str | None:
    headings = {match.group(1).strip().casefold() for match in _HEADING.finditer(text)}
    for template, needed in _SIGNATURES:
        if needed <= headings:
            return template
    return None


def _tabular(text: str, *, document=None) -> str | None:
    """`tabular.ndjson`, `tabular.json_array` or `tabular.csv`: homogeneous rows, or None."""
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        rows = [_json(line) for line in lines]
        if all(isinstance(row, dict) for row in rows) and len({tuple(sorted(row)) for row in rows}) == 1:
            return "tabular.ndjson"
    document = _json(text) if document is None else document
    if isinstance(document, list) and document:
        if all(isinstance(row, dict) for row in document) and (
            len({tuple(sorted(row)) for row in document}) == 1
        ):
            return "tabular.json_array"
    try:
        rows = [row for row in csv.reader(io.StringIO(text)) if row]
    except (csv.Error, ValueError):
        return None
    if len(rows) > 1 and len(rows[0]) > 1 and all(len(row) == len(rows[0]) for row in rows):
        return "tabular.csv"
    return None
