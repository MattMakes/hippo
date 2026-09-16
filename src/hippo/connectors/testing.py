"""The contract test kit (CDK S4a): what a connector developer runs before shipping.

Plan `ai_docs/plans/cdk-s4-kit.md` section 3.1, design `docs/spec/connector-developer-kit.md`
sections 8 and 9. Twelve contract assertions, two purity assertions, five capture assertions, five
runtime scenarios and the registry lock, each with a negative fixture in
`tests/unit/test_connector_testing_kit.py`.

Two rules hold everywhere here:

* **The kit never patches a module attribute.** `purity_guard` is the runtime's own
  `guard.forbid_effects`, a `sys.setprofile` hook on the calling thread (ruling R49, review B3), and
  the transports are the runtime's own recorder (review B4). The kit and the runtime therefore
  refuse exactly the same calls, because they run one function.
* **Every run is a scratch run.** `run_case`, `dry_run_sync` and `assert_runtime_resilience` open a
  temporary store in a temporary directory, hold only the built-ins and the connector's own
  extension, and remove the directory on the way out. Nothing reaches a configured store, a real
  provider or the user's Ollama.

Module-level imports are limited to the standard library, `numpy`, `httpx`, `pydantic` and the
leaf `hippo.connectors` modules; `sync`, `loader`, the store, the context and `ingest` are imported
inside the functions that use them, so `hippo --help` stays light.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
import shutil
import tempfile
import urllib.parse
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

import httpx
import numpy as np
import pydantic
from pydantic import BaseModel

from . import base, credentials, emit, keys, render
from .guard import EmitSideEffect
from .guard import forbid_effects as purity_guard  # B3, R49: the runtime's guard
from .http import ERROR_CLASSES as ERROR_CLASSES  # B4, R49: one recording format
from .http import ProviderNotFoundError, ProviderTransientError
from .http import record_transport as record_transport
from .http import replay_transport as replay_transport

if TYPE_CHECKING:  # pragma: no cover - annotation-only imports
    from ..context import AppContext
    from ..knowledge import model as k
    from ..knowledge.raw_artifacts import RawArtifactStore
    from ..knowledge.registry import Registry, TypeExtension
    from .base import (
        ChangePage,
        Classification,
        Clock,
        Connector,
        ConnectorDescriptor,
        EmissionBatch,
        PolicyObservation,
        RevisionInput,
        SyncConnector,
        TypeMapping,
    )
    from .sync import SyncOptions, SyncReceipt

FIXED_INSTANT: Final = datetime(2026, 1, 1, tzinfo=UTC)
SECOND_INSTANT: Final = datetime(2026, 1, 2, tzinfo=UTC)
TOKEN_BOUND: Final = base.PASSAGE_CHAR_BOUND  # m6, R42: the constant, never the number
KIT_INSTANCE_URL: Final = "https://connector-kit.invalid"
EMBEDDING_DIM: Final = 128
CASE_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CASE_FILES: Final = ("config.json", "changes.json", "policies.json")
CASE_DIRS: Final = ("inputs", "http", "expected")
GOLDEN_FILES: Final = (
    "nodes.json",
    "edges.json",
    "passages.json",
    "units.json",
    "aliases.json",
    "failures.json",
    "coverage.json",
)
CONTRACT_ASSERTIONS: Final = (
    "registered_vocabulary",
    "nodes_have_locator_and_policy",
    "unknown_policy_is_deny",
    "edges_fully_attributed",
    "aliases_name_a_rule",
    "no_ingestion_time",
    "one_fact_per_unit",
    "spans_match_bytes",
    "passages_within_token_bound",
    "identities_from_builders",
    "direction_and_ownership",
    "parse_failures_counted",
)
PURITY_ASSERTIONS: Final = ("emit_deterministic", "emit_pure")
CAPTURE_ASSERTIONS: Final = (
    "change_page_single_partition",
    "fetch_matches_ref",
    "canonical_uri_without_credentials",
    "unknown_policy_carries_no_principals",
    "probe_deterministic",
)
RUNTIME_SCENARIOS: Final = (
    "crash_after_fetch",
    "replayed_page",
    "failed_inventory",
    "policy_change_mid_page",
    "delete_with_live_session",
)
REGISTRY_ASSERTIONS: Final = ("registry_version_bump",)
ASSERTIONS: Final[tuple[str, ...]] = (
    CONTRACT_ASSERTIONS + PURITY_ASSERTIONS + CAPTURE_ASSERTIONS + RUNTIME_SCENARIOS + REGISTRY_ASSERTIONS
)
# The `RawFetch` fields a case's `fetches` map may set (S2 section 4.1).
FETCH_FIELDS: Final = (
    "content_type",
    "canonical_uri",
    "provider_revision",
    "source_updated_at",
    "source_timestamp_original",
    "source_timezone",
    "source_precision",
    "parser",
)
POLICY_TTL: Final = timedelta(minutes=10)
_KIT_OPERATOR: Final = "kit-operator"


class ContractViolation(AssertionError):
    """One named rule, broken. The name is always a member of `ASSERTIONS`."""

    def __init__(self, assertion: str, message: str, *, record: str | None = None) -> None:
        super().__init__(f"{assertion}: {message}" + (f" [{record}]" if record else ""))
        self.assertion = assertion
        self.message = message
        self.record = record


class CaseError(ValueError):
    """A fixture case the kit cannot read. The message always names the file."""


@dataclass(frozen=True)
class AssertionContext:
    registry: Registry
    descriptor: ConnectorDescriptor
    connector: k.Connector
    revision: RevisionInput
    policy: PolicyObservation
    clock_instant: datetime
    run_window: tuple[datetime, datetime]
    token_bound: int = TOKEN_BOUND


@dataclass(frozen=True)
class FixtureCase:
    name: str
    root: Path
    partition: str
    config: dict
    pages: tuple[ChangePage, ...]
    fetches: Mapping[str, dict]
    inputs: Mapping[str, bytes]
    policies: Mapping[str, PolicyObservation]


@dataclass(frozen=True)
class ScratchWorkspace:
    root: Path
    ctx: AppContext
    raw_store: RawArtifactStore
    user_id: str


@dataclass(frozen=True)
class ScratchInstance:
    row: k.Connector
    classification: Classification
    sources: Mapping[str, str]  # partition -> Source id


@dataclass(frozen=True)
class CaseResult:
    case: str
    generation_id: str | None
    records: Mapping[str, list]
    violations: tuple[ContractViolation, ...]
    diff: str
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and not self.violations and not self.diff


@dataclass(frozen=True)
class ValidationReport:
    connector: str
    version: str
    scope: Literal["capture", "contract", "full"]
    registry_diff: tuple[str, ...]
    cases: tuple[CaseResult, ...]
    violations: tuple[ContractViolation, ...]
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and not self.violations and all(case.passed for case in self.cases)

    def to_json(self) -> dict:
        return {
            "connector": self.connector,
            "version": self.version,
            "scope": self.scope,
            "passed": self.passed,
            "registry_diff": list(self.registry_diff),
            "error": self.error,
            "violations": [
                {"assertion": v.assertion, "message": v.message, "record": v.record} for v in self.violations
            ],
            "cases": [
                {
                    "case": case.case,
                    "passed": case.passed,
                    "generation_id": case.generation_id,
                    "error": case.error,
                    "diff": case.diff,
                    "violations": [
                        {"assertion": v.assertion, "message": v.message, "record": v.record}
                        for v in case.violations
                    ],
                }
                for case in self.cases
            ],
        }


# =========================================================================== the fixture layout


def _read_json(path: Path, *, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CaseError(f"{what} is missing: {path}") from error
    except ValueError as error:
        raise CaseError(f"{what} is not JSON: {path}: {error}") from error


def load_case(case_dir: Path) -> FixtureCase:
    """Read one case directory strictly, so a typo fails here and not mid-replay."""
    root = Path(case_dir).resolve()
    if not CASE_NAME.fullmatch(root.name):
        raise CaseError(
            f"Case directory name {root.name!r} must match {CASE_NAME.pattern}, "
            "so that validate.<case> is a legal operation id"
        )
    for entry in sorted(root.iterdir()):
        if entry.name not in CASE_FILES + CASE_DIRS:
            raise CaseError(f"{root.name}: unexpected entry {entry.name!r}; the layout is closed")

    config = _read_json(root / "config.json", what="config.json")
    changes = _read_json(root / "changes.json", what="changes.json")
    raw_pages = changes.get("pages") or []
    if not raw_pages:
        raise CaseError(f"{root.name}/changes.json names no pages")

    pages = []
    for index, page in enumerate(raw_pages):
        try:
            # R73: a strict contract model never accepts a dict; it round-trips through JSON.
            pages.append(base.ChangePage.model_validate_json(json.dumps(page)))
        except pydantic.ValidationError as error:
            raise CaseError(f"{root.name}/changes.json page {index} is not a ChangePage: {error}") from error
    partitions = {page.partition for page in pages}
    if len(partitions) != 1:
        raise CaseError(f"{root.name}/changes.json names more than one partition: {sorted(partitions)}")
    partition = partitions.pop()

    fetches = changes.get("fetches") or {}
    for external_id, entry in fetches.items():
        unknown = sorted(set(entry) - set(FETCH_FIELDS))
        if unknown:
            raise CaseError(
                f"{root.name}/changes.json fetches[{external_id!r}] names unknown fields: {unknown}"
            )
        # N10: `RawFetch` refuses a half timestamp, and it would surface unnamed mid-replay.
        if (entry.get("source_updated_at") is None) != (entry.get("source_timestamp_original") is None):
            raise CaseError(
                f"{root.name}/changes.json fetches[{external_id!r}]: "
                "a source timestamp needs its original spelling, and only with a timestamp"
            )

    inputs: dict[str, bytes] = {}
    input_dir = root / "inputs"
    if input_dir.is_dir():
        for path in sorted(input_dir.iterdir()):
            external_id = urllib.parse.unquote(path.name)
            if urllib.parse.quote(external_id, safe="") != path.name:
                raise CaseError(f"{root.name}/inputs/{path.name}: a file name is quote(external_id, safe='')")
            inputs[external_id] = path.read_bytes()

    refs = {change.ref.external_id: change.ref for page in pages for change in page.changes}
    for page in pages:
        for change in page.changes:
            if change.operation == "upsert" and change.ref.external_id not in inputs:
                raise CaseError(
                    f"{root.name}: upsert of {change.ref.external_id!r} has no file under inputs/"
                )

    policies: dict[str, PolicyObservation] = {}
    for external_id, payload in (_read_json(root / "policies.json", what="policies.json") or {}).items():
        ref = refs.get(external_id) or _fallback_ref(partition, pages, external_id)
        try:
            policies[external_id] = base.PolicyObservation.model_validate_json(
                json.dumps({**payload, "ref": ref.model_dump(mode="json")})
            )
        except pydantic.ValidationError as error:
            raise CaseError(
                f"{root.name}/policies.json[{external_id!r}] is not a PolicyObservation: {error}"
            ) from error

    return FixtureCase(
        name=root.name,
        root=root,
        partition=partition,
        config=config,
        pages=tuple(pages),
        fetches=dict(fetches),
        inputs=inputs,
        policies=policies,
    )


def _fallback_ref(partition: str, pages, external_id: str):
    """A ref for a policy entry no change names; `fetch_policy` replaces it with the request's."""
    kinds = [change.ref.artifact_kind for page in pages for change in page.changes]
    return base.ExternalRef(
        partition=partition,
        artifact_kind=kinds[0] if kinds else "document",
        external_id=external_id,
    )


def discover_cases(package_dir: Path) -> tuple[Path, ...]:
    """Every case directory of a package, in name order."""
    fixtures = Path(package_dir) / "fixtures"
    if not fixtures.is_dir():
        return ()
    return tuple(sorted(path for path in fixtures.iterdir() if path.is_dir()))


# =========================================================================== the replay connector


def _replay_connector(connector, case: FixtureCase, *, pages=None, policies=None, fail_on_page=None):
    """A per-call subclass that replays the sync half and keeps the real `probe` and `emit`.

    The subclass overrides exactly `list_changes`, `fetch` and `fetch_policy`, so a `probe` that
    samples through its own methods (R-S3-7) reads the case rather than the network.
    """
    replayed = tuple(case.pages if pages is None else pages)
    observed = dict(case.policies if policies is None else policies)
    calls: dict[str, int] = {}

    def list_changes(self, config, cursor):
        index = 0 if cursor is None else int(json.loads(cursor.value)["page"])
        if fail_on_page is not None and index == fail_on_page:
            raise ProviderTransientError(url=f"{KIT_INSTANCE_URL}/changes", status=503, attempts=1)
        if index >= len(replayed):
            return base.ChangePage(partition=case.partition, changes=(), next_cursor=None, complete=True)
        page = replayed[index]
        last = index + 1 >= len(replayed)
        if cursor is not None:
            scan = cursor.scan
        else:
            scan = page.next_cursor.scan if page.next_cursor is not None else "changes"
        next_cursor = (
            None
            if last
            else base.SyncCursor(
                partition=case.partition,
                value=json.dumps({"page": index + 1}, sort_keys=True),
                scan=scan,
            )
        )
        return page.model_copy(update={"next_cursor": next_cursor})

    def fetch(self, config, ref):
        data = case.inputs.get(ref.external_id)
        if data is None:
            # M15: the confirmation the runtime needs before it infers a deletion.
            raise ProviderNotFoundError(
                url=f"{KIT_INSTANCE_URL}/{urllib.parse.quote(ref.external_id, safe='')}",
                status=404,
                attempts=1,
            )
        entry = dict(case.fetches.get(ref.external_id) or {})
        fields = {
            "content_type": entry.get("content_type", "application/octet-stream"),
            "canonical_uri": entry.get(
                "canonical_uri",
                f"{KIT_INSTANCE_URL}/{urllib.parse.quote(ref.external_id, safe='')}",
            ),
            "provider_revision": entry.get("provider_revision", ref.provider_revision),
        }
        for name in FETCH_FIELDS:
            if name in entry and name not in fields:
                fields[name] = entry[name]
        return base.RawFetch.model_validate_json(
            json.dumps(
                {
                    "ref": ref.model_dump(mode="json"),
                    "data": data.decode("latin-1"),
                    "external_id": ref.external_id,
                    **fields,
                }
            )
        )

    def fetch_policy(self, config, ref):
        entry = observed.get(ref.external_id)
        if entry is None:
            return base.PolicyObservation(ref=ref, state="unknown")
        if isinstance(entry, base.PolicyObservation):
            chosen = entry
        else:
            sequence = list(entry)
            index = min(calls.get(ref.external_id, 0), len(sequence) - 1)
            calls[ref.external_id] = index + 1
            chosen = sequence[index]
        return chosen.model_copy(update={"ref": ref})

    subclass = type(
        f"_Replay{type(connector).__name__}",
        (type(connector),),
        {
            "__slots__": (),
            "__doc__": "A replay of one fixture case; `probe` and `emit` are the connector's own.",
            "list_changes": list_changes,
            "fetch": fetch,
            "fetch_policy": fetch_policy,
        },
    )
    replica = copy.copy(connector)
    # N7: a frozen or slotted connector refuses plain attribute assignment.
    object.__setattr__(replica, "__class__", subclass)
    return replica


# =========================================================================== contract assertions


def _refs(batch) -> list:
    refs = [node.ref for node in batch.nodes]
    for edge in batch.edges:
        refs.extend((edge.subject, edge.object))
    for alias in batch.aliases:
        refs.extend((alias.a, alias.b))
    for passage in batch.passages:
        if passage.node is not None:
            refs.append(passage.node)
    for unit in batch.units:
        refs.extend(unit.mentions)
    return refs


def _known_kind(context: AssertionContext, ref) -> bool:
    try:
        context.registry.object_kind(ref.kind)
    except Exception:
        return False
    return True


def _spans(batch) -> list:
    spans = [node.span for node in batch.nodes if node.span is not None]
    spans.extend(passage.span for passage in batch.passages if passage.span is not None)
    spans.extend(unit.span for unit in batch.units if unit.span is not None)
    for group in (*batch.edges, *batch.aliases):
        for support in group.support:
            spans.extend(support.spans)
    return spans


def assert_registered_vocabulary(batch: EmissionBatch, context: AssertionContext) -> None:
    registry = context.registry
    for ref in _refs(batch):
        if not _known_kind(context, ref):
            raise ContractViolation(
                "registered_vocabulary", f"Object kind {ref.kind!r} is not registered", record=ref.kind
            )
    for span in _spans(batch):
        try:
            registry.locator(span.locator_kind)
        except Exception as error:
            raise ContractViolation(
                "registered_vocabulary",
                f"Locator kind {span.locator_kind!r} is not registered",
                record=span.locator_kind,
            ) from error
    for edge in batch.edges:
        try:
            registry.predicate(edge.predicate)
        except Exception as error:
            raise ContractViolation(
                "registered_vocabulary",
                f"Predicate {edge.predicate!r} is not registered",
                record=edge.predicate,
            ) from error
    for record in (*batch.nodes, *batch.edges):
        try:
            registry.evidence_source(record.source)
        except Exception as error:
            raise ContractViolation(
                "registered_vocabulary",
                f"Evidence source {record.source!r} is not registered",
                record=record.source,
            ) from error


def assert_nodes_have_locator_and_policy(batch: EmissionBatch, context: AssertionContext) -> None:
    for node in batch.nodes:
        if node.span is None:
            raise ContractViolation(
                "nodes_have_locator_and_policy",
                "A node emission carries the span its claim is verified against",
                record=node.ref.kind,
            )
    if not context.revision.artifact.policy_id:
        raise ContractViolation(
            "nodes_have_locator_and_policy",
            "The revision's artifact names no AccessPolicy, so no node can be stored",
            record=context.revision.artifact.external_id,
        )


def assert_unknown_policy_is_deny(batch: EmissionBatch, context: AssertionContext) -> None:
    """What the runtime would store for an unknown observation must deny every reader.

    The plan's condition is `mode != "unknown"`. That half is unfalsifiable through S2, whose
    `policy_record` takes the mode straight from the state, so the rule also fires on the half
    that *is* reachable: `policy_record` copies the observation's principal lists whatever the
    state, so an unknown observation carrying principals becomes a deny-mode policy with allowed
    users. Recorded in `evidence-s4a.md`.
    """
    if context.policy.state != "unknown":
        return
    record = emit.policy_record(
        context.policy,
        connector=context.connector,
        workspace_id=context.connector.workspace_id,
        observed_at=context.clock_instant,
        expires_at=context.clock_instant + POLICY_TTL,
    )
    if record.mode != "unknown":
        raise ContractViolation(
            "unknown_policy_is_deny",
            f"An unknown policy must be stored as deny, not as {record.mode!r}",
            record=context.revision.artifact.external_id,
        )
    principals = record.allow_users + record.allow_groups + record.deny_users + record.deny_groups
    if principals:
        raise ContractViolation(
            "unknown_policy_is_deny",
            "An unknown policy carries no principals; the runtime stores it as deny",
            record=context.revision.artifact.external_id,
        )


def assert_edges_fully_attributed(batch: EmissionBatch, context: AssertionContext) -> None:
    for edge in batch.edges:
        try:
            # m18 / R63: the registry travels, so an extension source's class is reachable.
            emit.evidence_class(context.registry, edge.family, edge.source, edge.metadata_origin)
        except Exception as error:
            raise ContractViolation(
                "edges_fully_attributed",
                f"({edge.family}, {edge.source}, {edge.metadata_origin}) has no evidence class: {error}",
                record=edge.predicate,
            ) from error


def assert_aliases_name_a_rule(batch: EmissionBatch, context: AssertionContext) -> None:
    for alias in batch.aliases:
        if not (alias.rule or "").strip():
            raise ContractViolation(
                "aliases_name_a_rule",
                "An alias candidate names the rule that proposed it",
                record=f"{alias.a.kind}:{alias.b.kind}",
            )


def _ingested(instant, context: AssertionContext) -> bool:
    if instant is None:
        return False
    start, end = context.run_window
    return instant == context.clock_instant or start <= instant <= end


def assert_no_ingestion_time(batch: EmissionBatch, context: AssertionContext) -> None:
    stamps: list[tuple[Any, str]] = [(node.ts, f"node {node.ref.kind}") for node in batch.nodes]
    stamps.extend((passage.ts, f"passage {passage.key}") for passage in batch.passages)
    for edge in batch.edges:
        stamps.append((edge.valid_from, f"edge {edge.predicate} valid_from"))
        stamps.append((edge.valid_to, f"edge {edge.predicate} valid_to"))
    for instant, where in stamps:
        if _ingested(instant, context):
            raise ContractViolation(
                "no_ingestion_time",
                "A record's time is the provider's, never the moment this build ran",
                record=where,
            )


def _fact_templates(context: AssertionContext, kind: str) -> tuple[str, ...]:
    definition = context.registry.object_kind(kind)
    return tuple(f"{t.name}@{t.version}" for t in definition.fact_templates)


def assert_one_fact_per_unit(batch: EmissionBatch, context: AssertionContext) -> None:
    for unit in batch.units:
        if unit.span is None:
            continue
        try:
            text = emit.verify_span(context.revision.data, unit.span, artifact=context.revision.artifact)
        except Exception:
            continue  # spans_match_bytes owns an unverifiable span
        if unit.start is None or unit.end is None:
            continue
        if unit.start >= len(text) or unit.end > len(text):
            raise ContractViolation(
                "one_fact_per_unit",
                f"Unit offsets [{unit.start}, {unit.end}) fall outside its verified span of "
                f"{len(text)} characters",
                record=unit.key,
            )
    for node in batch.nodes:
        if node.span is None or not _known_kind(context, node.ref):
            continue
        definition = context.registry.object_kind(node.ref.kind)
        try:
            attrs = definition.attrs_model(**node.attrs)
            key = keys.canonical_key(context.registry, node.ref, instance=context.connector.instance_url)
            label = render.render_label(definition, attrs)
            rendered = render.render_facts(definition, attrs, label=label, key=key)
        except Exception:
            continue  # identities_from_builders owns an unbuildable key
        known = _fact_templates(context, node.ref.kind)
        for text in rendered:
            if text.template is not None and text.template not in known:
                raise ContractViolation(
                    "one_fact_per_unit",
                    f"Rendered fact uses template {text.template!r}, which {node.ref.kind} does not declare",
                    record=node.ref.kind,
                )


def assert_spans_match_bytes(batch: EmissionBatch, context: AssertionContext) -> None:
    for span in _spans(batch):
        try:
            text = emit.verify_span(context.revision.data, span, artifact=context.revision.artifact)
        except Exception as error:
            raise ContractViolation(
                "spans_match_bytes",
                f"A span over {span.locator_kind} does not verify against the revision bytes: {error}",
                record=json.dumps(span.locator, sort_keys=True),
            ) from error
        if span.text is not None and span.text != text:
            raise ContractViolation(
                "spans_match_bytes",
                "A span's quoted text differs from the bytes it names",
                record=json.dumps(span.locator, sort_keys=True),
            )


def assert_passages_within_token_bound(batch: EmissionBatch, context: AssertionContext) -> None:
    for passage in batch.passages:
        if passage.span is None:
            continue
        try:
            text = emit.verify_span(context.revision.data, passage.span, artifact=context.revision.artifact)
        except Exception:
            continue  # spans_match_bytes owns it
        counted = base.token_count(text)
        if counted > context.token_bound:
            raise ContractViolation(
                "passages_within_token_bound",
                f"Passage {passage.key} measures {counted} against a bound of {context.token_bound}; "
                "split it before emitting",
                record=passage.key,
            )


def assert_identities_from_builders(batch: EmissionBatch, context: AssertionContext) -> None:
    for ref in _refs(batch):
        if not _known_kind(context, ref):
            continue  # registered_vocabulary owns it
        definition = context.registry.object_kind(ref.kind)
        try:
            keys.check_key_parts(definition, ref)
            keys.canonical_key(context.registry, ref, instance=context.connector.instance_url)
        except Exception as error:
            raise ContractViolation(
                "identities_from_builders",
                f"{ref.kind} identity is the kit's to mint: {error}",
                record=ref.kind,
            ) from error


def assert_direction_and_ownership(batch: EmissionBatch, context: AssertionContext) -> None:
    for edge in batch.edges:
        try:
            emit.check_direction_and_ownership(
                context.registry,
                context.descriptor,
                edge.predicate,
                edge.subject.kind,
                edge.object.kind,
            )
        except Exception as error:
            raise ContractViolation("direction_and_ownership", str(error), record=edge.predicate) from error


def assert_parse_failures_counted(batch: EmissionBatch, context: AssertionContext) -> None:
    if not context.revision.data:
        return
    if batch.nodes or batch.passages or batch.units:
        return
    if batch.failures:
        return
    raise ContractViolation(
        "parse_failures_counted",
        "Non-empty bytes produced no record and no ParseFailure; a silent drop is a lost fact",
        record=context.revision.artifact.external_id,
    )


_CONTRACT_FUNCTIONS: Final = {
    "registered_vocabulary": assert_registered_vocabulary,
    "nodes_have_locator_and_policy": assert_nodes_have_locator_and_policy,
    "unknown_policy_is_deny": assert_unknown_policy_is_deny,
    "edges_fully_attributed": assert_edges_fully_attributed,
    "aliases_name_a_rule": assert_aliases_name_a_rule,
    "no_ingestion_time": assert_no_ingestion_time,
    "one_fact_per_unit": assert_one_fact_per_unit,
    "spans_match_bytes": assert_spans_match_bytes,
    "passages_within_token_bound": assert_passages_within_token_bound,
    "identities_from_builders": assert_identities_from_builders,
    "direction_and_ownership": assert_direction_and_ownership,
    "parse_failures_counted": assert_parse_failures_counted,
}


def check_contract(batch: EmissionBatch, context: AssertionContext) -> tuple[ContractViolation, ...]:
    """The twelve rules, in `CONTRACT_ASSERTIONS` order, collected rather than raised."""
    violations = []
    for name in CONTRACT_ASSERTIONS:
        try:
            _CONTRACT_FUNCTIONS[name](batch, context)
        except ContractViolation as violation:
            violations.append(violation)
    return tuple(violations)


def assert_contract(batch: EmissionBatch, registry: Registry, context: AssertionContext) -> None:
    """Deviation 2: the design's two arguments plus the context the rules need."""
    violations = check_contract(batch, context)
    if violations:
        raise violations[0]


# =========================================================================== purity


def assert_emit_pure(connector: Connector, revision: RevisionInput, mapping: TypeMapping) -> EmissionBatch:
    """Call `emit` twice under S3's per-thread guard; return the first batch."""
    from ..knowledge.identity import canonical_json

    batches = []
    for attempt in (1, 2):
        try:
            with purity_guard():
                batches.append(connector.emit(revision, mapping))
        except EmitSideEffect as error:
            raise ContractViolation("emit_pure", str(error)) from error
        except Exception as error:
            # N8: an `emit` that succeeds once and raises on the re-run is not deterministic.
            raise ContractViolation(
                "emit_deterministic",
                f"emit raised {type(error).__name__} on call {attempt}: {error}",
            ) from error
    first, second = batches
    if canonical_json(first.model_dump(mode="json")) != canonical_json(second.model_dump(mode="json")):
        raise ContractViolation(
            "emit_deterministic", "Two calls with the same revision produced different batches"
        )
    return first


# =========================================================================== capture


def _violation(assertion: str, message: str, record: str | None = None) -> ContractViolation:
    return ContractViolation(assertion, message, record=record)


def check_capture(
    connector: SyncConnector, config: BaseModel, *, sample: int
) -> tuple[ContractViolation, ...]:
    """The five capture rules over any `SyncConnector` (R1): no store, no HTTP of the kit's own."""
    if sample < 1:
        raise ValueError("check_capture needs a positive sample")
    violations: list[ContractViolation] = []
    collected: list = []
    cursor = None
    for _ in range(sample):
        try:
            page = connector.list_changes(config, cursor)
        except (pydantic.ValidationError, base.ContractError) as error:
            violations.append(
                _violation("change_page_single_partition", f"list_changes refused its own page: {error}")
            )
            break
        violations.extend(_check_page(page, cursor))
        collected.extend(page.changes)
        cursor = page.next_cursor
        if cursor is None or len(collected) >= sample:
            break
    collected = collected[:sample]

    for change in collected:
        if change.operation != "upsert":
            continue
        try:
            fetched = connector.fetch(config, change.ref)
        except (pydantic.ValidationError, base.ContractError) as error:
            violations.append(_violation("fetch_matches_ref", f"fetch refused its own record: {error}"))
            continue
        violations.extend(_check_fetch(fetched, change.ref))

    for change in collected:
        if change.operation not in ("upsert", "policy_change"):
            continue
        try:
            observed = connector.fetch_policy(config, change.ref)
        except (pydantic.ValidationError, base.ContractError) as error:
            violations.append(
                _violation(
                    "unknown_policy_carries_no_principals",
                    f"fetch_policy refused its own observation: {error}",
                )
            )
            continue
        violations.extend(_check_policy(observed, change.ref))

    violations.extend(_check_probe(connector, config))
    return tuple(violations)


def _check_page(page, cursor) -> list[ContractViolation]:
    found = []
    if cursor is not None and page.partition != cursor.partition:
        found.append(
            _violation(
                "change_page_single_partition",
                f"A follow-up page answered partition {page.partition!r} for cursor {cursor.partition!r}",
            )
        )
    for change in page.changes:
        if change.ref.partition != page.partition:
            found.append(
                _violation(
                    "change_page_single_partition",
                    f"A change page cannot mix partitions: {change.ref.partition!r} in a "
                    f"{page.partition!r} page",
                    change.ref.external_id,
                )
            )
    if page.next_cursor is not None and page.next_cursor.partition != page.partition:
        found.append(
            _violation(
                "change_page_single_partition",
                f"A page's next cursor names partition {page.next_cursor.partition!r}",
            )
        )
    return found


def _check_fetch(fetched, ref) -> list[ContractViolation]:
    found = []
    if fetched.ref != ref or fetched.external_id != ref.external_id:
        found.append(
            _violation(
                "fetch_matches_ref",
                f"fetch of {ref.external_id!r} answered {fetched.external_id!r}",
                ref.external_id,
            )
        )
    if ref.provider_revision is not None and fetched.provider_revision != ref.provider_revision:
        found.append(
            _violation(
                "fetch_matches_ref",
                f"fetch answered revision {fetched.provider_revision!r} for the change's "
                f"{ref.provider_revision!r}",
                ref.external_id,
            )
        )
    uri = fetched.canonical_uri
    parsed = urllib.parse.urlsplit(uri)
    if parsed.username is not None or parsed.password is not None:
        found.append(
            _violation(
                "canonical_uri_without_credentials",
                "A canonical URI carries userinfo",
                ref.external_id,
            )
        )
    elif credentials.redact_url(uri) != uri:
        found.append(
            _violation(
                "canonical_uri_without_credentials",
                "A canonical URI carries a secret in its query",
                ref.external_id,
            )
        )
    return found


def _check_policy(observed, ref) -> list[ContractViolation]:
    found = []
    if observed.ref != ref:
        found.append(
            _violation(
                "fetch_matches_ref",
                f"fetch_policy of {ref.external_id!r} answered a different ref",
                ref.external_id,
            )
        )
    principals = observed.allow_users + observed.allow_groups + observed.deny_users + observed.deny_groups
    if observed.state == "unknown" and (observed.mode is not None or principals):
        found.append(
            _violation(
                "unknown_policy_carries_no_principals",
                "An unknown policy carries no principals; the runtime stores it as deny",
                ref.external_id,
            )
        )
    return found


def _check_probe(connector, config) -> list[ContractViolation]:
    """M13: `probe` is a pure function of the descriptor, the config and the sampled bytes."""
    from ..knowledge.identity import canonical_json

    try:
        first = connector.probe(config, lambda: FIXED_INSTANT)
        second = connector.probe(config, lambda: SECOND_INSTANT)
    except (pydantic.ValidationError, base.ContractError) as error:
        return [_violation("probe_deterministic", f"probe refused its own classification: {error}")]
    if canonical_json(first.model_dump(mode="json")) != canonical_json(second.model_dump(mode="json")):
        return [
            _violation(
                "probe_deterministic",
                "Two probes an instant apart classified the same partition differently",
            )
        ]
    return []


# =========================================================================== the offline model


def hashed_embedding(text: str) -> np.ndarray:
    """Feature-hash words and character trigrams into a fixed-size unit vector.

    Moved here verbatim from `tests/fakes/fake_ollama.py` (m17). The kit ships it so `validate`
    and `sync --dry-run` never need a running Ollama, and the fake imports it so both produce
    byte-identical vectors.
    """
    text = re.sub(r"^(search_query: |search_document: )", "", text).lower()
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    words = re.findall(r"[a-z0-9]+", text)
    features = list(words)
    for word in words:
        padded = f" {word} "
        features.extend(padded[i : i + 3] for i in range(len(padded) - 2))
    for feature in features:
        digest = hashlib.md5(feature.encode()).digest()
        index = int.from_bytes(digest[:4], "little") % EMBEDDING_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign * (2.0 if feature in words else 1.0)
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


_OFFLINE_URL: Final = "http://connector-kit-model"
_CHAT_MODEL: Final = "kit-chat:latest"
_EMBED_MODEL: Final = "kit-embed:latest"


def _digest(model: str) -> str:
    """A stable SHA-256 spelling; the managed build refuses a model without one."""
    return hashlib.sha256(model.encode("utf-8")).hexdigest()


def _offline_handle(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/tags":
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": name, "model": name, "digest": _digest(name)}
                    for name in (_CHAT_MODEL, _EMBED_MODEL)
                ]
            },
        )
    if path == "/api/show":
        body = json.loads(request.content or b"{}")
        embedding = str(body.get("model", "")).startswith("kit-embed")
        return httpx.Response(200, json={"capabilities": ["embedding" if embedding else "completion"]})
    if path == "/api/embed":
        body = json.loads(request.content or b"{}")
        inputs = body.get("input") or []
        if isinstance(inputs, str):
            inputs = [inputs]
        return httpx.Response(
            200,
            json={
                "model": body.get("model", _EMBED_MODEL),
                "embeddings": [hashed_embedding(text).tolist() for text in inputs],
            },
        )
    if path == "/api/chat":
        return httpx.Response(500, json={"error": "the kit's offline model never generates prose"})
    return httpx.Response(404, json={"error": f"no such route {path}"})


def offline_ollama():
    """An `Ollama` over `httpx.MockTransport`: hashed vectors, and no prose at all."""
    from ..ollama import Ollama

    return Ollama(
        _OFFLINE_URL,
        _CHAT_MODEL,
        _EMBED_MODEL,
        num_ctx=8192,
        client=httpx.Client(base_url=_OFFLINE_URL, transport=httpx.MockTransport(_offline_handle)),
    )


# =========================================================================== scratch runs


def scratch_store(path: Path):
    """A temporary LadybugDB store (deviation 1, R7). Tests substitute the Fake."""
    from ..store.ladybug import LadybugStore

    # N9: the shipped configuration is the measured one.
    return LadybugStore(path, buffer_pool_bytes=256 * 2**20)


@contextmanager
def scratch_workspace(*, clock: Clock | None = None) -> Iterator[ScratchWorkspace]:
    """One temporary store, raw store and context, removed on every exit."""
    from ..config import Config
    from ..context import AppContext
    from ..knowledge.raw_artifacts import RawArtifactStore
    from .sync import SyncOptions

    directory = tempfile.TemporaryDirectory(prefix="hippo-connector-kit-")
    # `RawArtifactStore` refuses a root with symlinked components, and macOS puts /var under
    # /private/var, so the root is resolved before anything is built under it.
    root = Path(directory.name).resolve()
    store = None
    ctx = None
    try:
        store = scratch_store(root / "kit.lbug")
        store.ensure_schema()
        if clock is not None:
            store._generation_clock = clock  # the one clock of R27
        store.ensure_roles()
        # R64 / S3c gotcha 6: in open mode the store refuses an enabled provider connector, so a
        # scratch workspace always has one operator before `prepare_instance` runs.
        user_id = store.create_user(_KIT_OPERATOR, "connector-kit", "individual")
        store.set_meta("reviewed_mapping_authorities", ["local"])
        ctx = AppContext(config=Config(data_dir=root / "data"), store=store, ollama=offline_ollama())
        raw_store = RawArtifactStore(root / "raw", max_object_bytes=SyncOptions().max_fetch_bytes)
        yield ScratchWorkspace(root=root, ctx=ctx, raw_store=raw_store, user_id=user_id)
    finally:
        if ctx is not None:
            close = getattr(ctx, "close", None)
            if close is not None:
                close()
        if store is not None:
            store.close()
        directory.cleanup()
        shutil.rmtree(root, ignore_errors=True)


def kit_registry(descriptor: ConnectorDescriptor) -> Registry:
    """The built-ins plus this connector's own extension, frozen (N6 promotes it)."""
    from ..knowledge.registry import RegistrationError, Registry

    registry = Registry.with_builtins()
    registry.register(descriptor.extension, declared_families=descriptor.families)
    # N16: a named rule, rather than `Unknown connector kind` from a store write.
    if descriptor.name not in registry.connector_kinds():
        raise RegistrationError(
            "unregistered_connector_kind",
            f"Connector {descriptor.name} does not register its own connector kind; "
            "add it to the extension's connector_kinds",
        )
    registry.freeze()
    return registry


def prepare_instance(
    workspace: ScratchWorkspace,
    connector: Connector,
    config: BaseModel,
    *,
    clock: Clock,
    partitions: tuple[str, ...] | None = None,
) -> ScratchInstance:
    """R49's calls, in order: the enabled instance, the probe, the classification, the Sources."""
    from ..store.migrations import DEFAULT_WORKSPACE_ID
    from . import sync

    store = workspace.ctx.store
    descriptor = connector.descriptor
    # S3's entry refuses a row whose `instance_url` differs from a configuration that declares one
    # (`sync.py`), so a case's own instance wins and `KIT_INSTANCE_URL` is the default.
    row = sync.ensure_connector(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        kind=descriptor.name,
        instance_url=getattr(config, "instance_url", None) or KIT_INSTANCE_URL,
        config=config,
        enabled=True,  # explicit, because R51 makes False the default (M5)
    )
    classification = connector.probe(config, clock)
    row = sync.store_classification(store, connector=row, classification=classification)
    chosen = partitions or tuple(entry.partition for entry in classification.partitions)
    sources = {
        partition: sync.connector_source(
            store,
            connector=row,
            partition=partition,
            name=f"{descriptor.name} {partition}",
            owner_id=workspace.user_id,
        )
        for partition in chosen
    }
    return ScratchInstance(row=row, classification=classification, sources=sources)


def scratch_sync(
    workspace: ScratchWorkspace,
    connector: Connector,
    *,
    instance: ScratchInstance,
    config: BaseModel,
    partition: str,
    operation_id: str,
    options: SyncOptions | None = None,
    on_batch: Callable[[RevisionInput, EmissionBatch], None] | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> SyncReceipt:
    """One call of S3's entry, with its full signature (S3 section 4.7 + R49)."""
    from ..ingest.managed_activation import embedding_spec
    from ..knowledge.build_authority import BuildActor
    from . import sync

    return sync.sync_connector(
        workspace.ctx,
        connector,
        connector_id=instance.row.id,
        config=config,
        partition=partition,
        actor=BuildActor.trusted_local(),
        registry=base.current_registry(),
        options=options or sync.SyncOptions(emit_workers=1),
        raw_store=workspace.raw_store,
        embedding_spec=embedding_spec(workspace.ctx.ollama),
        operation_id=operation_id,
        should_stop=lambda: False,
        on_batch=on_batch,
        fault_hook=fault_hook,
    )


def dry_run_sync(
    connector: Connector, config: BaseModel, *, partition: str | None = None
) -> tuple[SyncReceipt, ...]:
    """`hippo connector sync --dry-run`: the real provider, read-only, into a scratch workspace."""
    registry = kit_registry(connector.descriptor)
    with base.use_registry(registry):
        with scratch_workspace() as workspace:
            instance = prepare_instance(
                workspace,
                connector,
                config,
                clock=workspace.ctx.store._now,
                partitions=(partition,) if partition else None,
            )
            return tuple(
                scratch_sync(
                    workspace,
                    connector,
                    instance=instance,
                    config=config,
                    partition=name,
                    operation_id=f"dry-run.{index}",
                )
                for index, name in enumerate(instance.sources)
            )


# =========================================================================== run_case


_CASE_ERRORS: Final = ("ConnectorSyncRefused", "ConnectorContractViolation")


def _case_error_classes():
    from . import sync

    return (
        sync.ConnectorSyncRefused,
        sync.ConnectorContractViolation,
        base.ContractError,
        pydantic.ValidationError,
    )


def run_case(connector: Connector, case: FixtureCase | Path, *, update_golden: bool = False) -> CaseResult:
    """Publish one case into a scratch workspace and diff it against `expected/`."""
    from ..knowledge.registry import RegistrationError

    if not isinstance(case, FixtureCase):
        case = load_case(Path(case))
    started = datetime.now(UTC)
    empty: Mapping[str, list] = {}
    try:
        registry = kit_registry(connector.descriptor)
    except RegistrationError as error:
        return CaseResult(case.name, None, empty, (), "", error=f"{type(error).__name__}: {error}")

    descriptor = connector.descriptor
    with base.use_registry(registry):
        try:
            config = descriptor.config_model.model_validate(case.config)
        except pydantic.ValidationError as error:
            return CaseResult(case.name, None, empty, (), "", error=f"ValidationError: {error}")
        replay = _replay_connector(connector, case)
        observed: list = []

        def record(revision, batch):
            # A raise here would fail the sync with an error naming no rule, so it only records.
            observed.append((revision, batch))

        try:
            with scratch_workspace(clock=lambda: FIXED_INSTANT) as workspace:
                instance = prepare_instance(
                    workspace,
                    replay,
                    config,
                    clock=lambda: FIXED_INSTANT,
                    partitions=(case.partition,),
                )
                receipt = scratch_sync(
                    workspace,
                    replay,
                    instance=instance,
                    config=config,
                    partition=case.partition,
                    operation_id=f"validate.{case.name}",
                    on_batch=record,
                )
                if receipt.outcome != "published":
                    return CaseResult(
                        case.name,
                        None,
                        empty,
                        (),
                        "",
                        error=f"The case published nothing: {receipt.outcome}",
                    )
                violations = _checks(observed, registry, descriptor, instance, case, started, replay)
                records = _golden_records(workspace.ctx.store, receipt.generation_id)
        except _case_error_classes() as error:
            return CaseResult(case.name, None, empty, (), "", error=f"{type(error).__name__}: {error}")

    diff = _diff_goldens(case.root / "expected", records, write=update_golden)
    return CaseResult(case.name, receipt.generation_id, records, violations, diff)


def _checks(observed, registry, descriptor, instance, case, started, replay):
    violations: list[ContractViolation] = []
    window = (started, datetime.now(UTC))
    for revision, batch in observed:
        policy = case.policies.get(revision.artifact.external_id) or base.PolicyObservation(
            ref=base.ExternalRef(
                partition=case.partition,
                artifact_kind=revision.artifact.kind,
                external_id=revision.artifact.external_id,
            ),
            state="unknown",
        )
        context = AssertionContext(
            registry=registry,
            descriptor=descriptor,
            connector=instance.row,
            revision=revision,
            policy=policy,
            clock_instant=FIXED_INSTANT,
            run_window=window,
        )
        violations.extend(check_contract(batch, context))
        try:
            assert_emit_pure(replay, revision, revision.mapping)
        except ContractViolation as violation:
            violations.append(violation)
    return tuple(violations)


# =========================================================================== the goldens


def _dump(record, *, drop=()) -> dict:
    payload = record.model_dump(mode="json")
    for name in drop:
        payload.pop(name, None)
    return payload


def _normalise(value, tokens: Mapping[str, str]):
    """Replace every run-local id with its stable token, structurally rather than textually."""
    if isinstance(value, str):
        return tokens.get(value, value)
    if isinstance(value, list):
        return [_normalise(item, tokens) for item in value]
    if isinstance(value, Mapping):
        return {name: _normalise(item, tokens) for name, item in value.items()}
    return value


def _tokens(store, generation_id, *, assertions, versions, supports, passages, units) -> dict[str, str]:
    """A golden must reproduce, and `store/base.py:147`'s `new_id()` is a `uuid4`.

    A `Source` id is therefore run-local, and so is a `Generation` id, and so is every id hashed
    over one of them: a `Passage`, a `RetrievalView`, a `Unit`, an `Assertion` (whose `scope_key`
    names the Source) and its versions and support rows. Each of those gets a stable token,
    numbered in an order derived only from content that does reproduce -- a span id, an ordinal,
    a canonical key. Every other id is a content hash of the record itself and is written whole.
    """
    generation = store._knowledge_get("Generation", generation_id)
    tokens = {generation_id: "<generation>"}
    if generation is not None:
        tokens[generation.source_id] = "<source>"
        source = store.get_source(generation.source_id) or {}
        connector_id = (source.get("meta") or {}).get("connector_id")
        if connector_id:
            tokens[connector_id] = "<connector>"
        # The inventory manifest revision is minted per Source, so it moves with the Source id.
        manifest = json.loads(generation.coverage_json or "{}").get("embedding_manifest_revision_id")
        if manifest:
            tokens[manifest] = "<manifest-revision>"
    for ordinal, row in enumerate(
        sorted(passages, key=lambda r: (r.get("span_id") or "", r.get("ordinal") or 0))
    ):
        tokens[row["id"]] = f"<passage-{ordinal}>"
        if row.get("retrieval_view_id"):
            tokens[row["retrieval_view_id"]] = f"<view-{ordinal}>"
    for ordinal, unit in enumerate(
        sorted(units, key=lambda u: (u.span_id or "", u.ordinal, u.content_hash or ""))
    ):
        tokens[unit.id] = f"<unit-{ordinal}>"
        tokens[unit.identity_key] = f"<unit-key-{ordinal}>"
    for ordinal, assertion in enumerate(assertions):
        tokens[assertion.id] = f"<edge-{ordinal}>"
        tokens[assertion.identity_key] = f"<edge-key-{ordinal}>"
        tokens[assertion.scope_key] = f"<scope-{ordinal}>"
        for index, version in enumerate(sorted(versions.get(assertion.id, ()), key=lambda r: r.id)):
            tokens[version.id] = f"<version-{ordinal}.{index}>"
            tokens[version.identity_key] = f"<version-key-{ordinal}.{index}>"
            for position, support in enumerate(sorted(supports.get(version.id, ()), key=lambda r: r.id)):
                tokens[support.id] = f"<support-{ordinal}.{index}.{position}>"
                tokens[support.identity_key] = f"<support-key-{ordinal}.{index}.{position}>"
    return tokens


def _golden_records(store, generation_id: str) -> dict[str, list]:
    """The seven golden lists, read back by generation id. No read checks vocabulary (R39)."""
    members = store._knowledge_rows("GenerationEvidenceMember", generation_id=generation_id)
    by_kind: dict[str, list] = {}
    for member in members:
        record = store._knowledge_get(member.record_kind, member.record_id)
        if record is not None:
            by_kind.setdefault(member.record_kind, []).append(record)

    # A `KnowledgeObject` is shared across generations and is never itself a member; the
    # generation's objects are the ones its member observations name.
    observations: dict[str, list] = {}
    for observation in by_kind.get("ObjectObservation", ()):
        observations.setdefault(observation.object_id, []).append(observation)
    objects = [store._knowledge_get("KnowledgeObject", object_id) for object_id in sorted(observations)]

    nodes = [
        {
            "id": obj.id,
            "kind": obj.kind,
            "canonical_key": obj.canonical_key,
            "observations": sorted(
                (_dump(o, drop=("recorded_to",)) for o in observations.get(obj.id, ())),
                key=lambda row: row["id"],
            ),
        }
        for obj in objects
        if obj is not None
    ]

    supports: dict[str, list] = {}
    for support in by_kind.get("AssertionSupport", ()):
        supports.setdefault(support.assertion_version_id, []).append(support)
    versions: dict[str, list] = {}
    for version in by_kind.get("AssertionVersion", ()):
        versions.setdefault(version.assertion_id, []).append(version)

    def edge_row(assertion) -> dict:
        own = sorted(versions.get(assertion.id, ()), key=lambda row: row.id)
        return {
            "id": assertion.id,
            "subject_id": assertion.subject_id,
            "predicate": assertion.predicate,
            "object_id": assertion.object_id,
            "scope_key": assertion.scope_key,
            "versions": [_dump(version, drop=("recorded_to",)) for version in own],
            "support": sorted(
                (_dump(support) for version in own for support in supports.get(version.id, ())),
                key=lambda row: row["id"],
            ),
        }

    assertions = [store._knowledge_get("Assertion", assertion_id) for assertion_id in sorted(versions)]
    assertions = [assertion for assertion in assertions if assertion is not None]
    # Sorted by their stable endpoints, so the tokens below number them the same way every run.
    assertions.sort(key=lambda a: (a.subject_id, a.predicate, a.object_id))

    # N4: `Passage` is a native row, not a knowledge record.
    passage_rows = [
        {
            "id": row["id"],
            "title": row.get("title"),
            "text": row.get("text"),
            "span_id": row.get("span_id"),
            "retrieval_view_id": row.get("retrieval_view_id"),
            "ordinal": row.get("ordinal"),
        }
        for row in store._native_rows("Passage", generation_id=generation_id)
    ]
    unit_rows = store._knowledge_rows("Unit", generation_id=generation_id)
    tokens = _tokens(
        store,
        generation_id,
        assertions=assertions,
        versions=versions,
        supports=supports,
        passages=passage_rows,
        units=unit_rows,
    )
    edges = [edge_row(a) for a in assertions if a.predicate != "SAME_OBJECT_AS"]
    aliases = [edge_row(a) for a in assertions if a.predicate == "SAME_OBJECT_AS"]
    passages = passage_rows
    units = [_dump(unit) for unit in unit_rows]

    generation = store._knowledge_get("Generation", generation_id)
    coverage = json.loads(generation.coverage_json or "{}")
    failures = [
        {"family": entry.get("family"), "parser": entry.get("parser"), "count": entry.get("count")}
        for entry in _parse_failures(coverage)
    ]
    records = {
        "nodes.json": nodes,
        "edges.json": edges,
        "passages.json": passages,
        "units.json": units,
        "aliases.json": aliases,
        "failures.json": failures,
        "coverage.json": coverage,
    }
    normalised = {name: _normalise(value, tokens) for name, value in records.items()}
    for name, value in normalised.items():
        if isinstance(value, list) and all(isinstance(row, Mapping) and "id" in row for row in value):
            normalised[name] = sorted(value, key=lambda row: row["id"])
        elif isinstance(value, list):
            normalised[name] = sorted(value, key=lambda row: json.dumps(row, sort_keys=True))
    return normalised


def _parse_failures(coverage) -> list[dict]:
    """What `ParseFailure` the generation counted, from S3c's own section of `coverage_json`.

    `sync._coverage_json` writes `EmissionCoverage.to_json()` under `emission`, which keys each
    count `family|parser|dialect` with `-` for a part the failure omits (`emit._count_failures`).
    The top-level keys are read after it for a coverage some other writer produced.
    """
    emission = coverage.get("emission") if isinstance(coverage.get("emission"), Mapping) else {}
    counted = emission.get("failures") or coverage.get("failures") or coverage.get("parse_failures") or []
    if isinstance(counted, Mapping):
        rows = []
        for name, count in counted.items():
            family, _, rest = str(name).partition("|")
            parser = rest.partition("|")[0]
            rows.append(
                {"family": family, "parser": parser if parser not in ("", "-") else None, "count": count}
            )
        return rows
    return [entry for entry in counted if isinstance(entry, Mapping)]


def _diff_goldens(expected: Path, records: Mapping[str, list], *, write: bool) -> str:
    from ..knowledge.identity import canonical_json

    chunks: list[str] = []
    for name in GOLDEN_FILES:
        actual = canonical_json(records[name])
        path = expected / name
        stored = path.read_text(encoding="utf-8") if path.exists() else ""
        if stored == actual:
            continue
        chunks.extend(
            difflib.unified_diff(
                stored.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )
        if write:
            expected.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8")
    return "".join(chunks)


# =========================================================================== runtime scenarios


def assert_runtime_resilience(
    connector: Connector,
    case: FixtureCase | Path,
    *,
    scenarios: tuple[str, ...] = RUNTIME_SCENARIOS,
) -> None:
    """S3 section 9's five boundaries, on replay variants of the case."""
    if not isinstance(case, FixtureCase):
        case = load_case(Path(case))
    upserts = [change.ref for page in case.pages for change in page.changes if change.operation == "upsert"]
    registry = kit_registry(connector.descriptor)
    config = connector.descriptor.config_model.model_validate(case.config)
    for scenario in scenarios:
        if len(upserts) < 2:
            raise ContractViolation(scenario, "runtime scenarios need a case with two upserted records")
        if scenario == "failed_inventory" and not connector.descriptor.capabilities.inventory:
            continue  # skipped by declaration, never by exception
        with base.use_registry(registry):
            _SCENARIOS[scenario](connector, case, config, upserts[0], upserts[1])


def _baseline(workspace, connector, case, config, instance):
    return scratch_sync(
        workspace,
        connector,
        instance=instance,
        config=config,
        partition=case.partition,
        operation_id="scenario-1",
    )


@dataclass(frozen=True)
class _World:
    """One scenario's scratch run: the workspace, the instance and G1's fingerprint."""

    workspace: ScratchWorkspace
    instance: ScratchInstance
    case: FixtureCase
    config: BaseModel
    connector: Any
    source_id: str
    generation_id: str
    checksums: Any
    cursor_json: str | None
    epoch: int
    policies: Mapping[str, str]
    operations: list

    @property
    def store(self):
        return self.workspace.ctx.store

    def run(self, scenario: str, *, pages=None, policies=None, fail_on_page=None, options=None, hook=None):
        """One more `scratch_sync` on a replay variant, an instant after the one before it.

        The clock advances a second per run. `AssertionVersion` identity carries `recorded_from`
        but not `unit_id`, and a later generation mints new `Unit` rows, so a second run at the
        *same* pinned instant re-emits an edge whose id matches a stored row with different
        contents and the store refuses it. One second also satisfies N11, which wants a replayed
        page to run late enough for a re-stamped row to be visible, and stays far inside R52's
        half-TTL window.
        """
        self.operations.append(scenario)
        elapsed = len(self.operations)
        self.store._generation_clock = lambda: FIXED_INSTANT + timedelta(seconds=elapsed)
        replay = _replay_connector(
            self.connector, self.case, pages=pages, policies=policies, fail_on_page=fail_on_page
        )
        return scratch_sync(
            self.workspace,
            replay,
            instance=self.instance,
            config=self.config,
            partition=self.case.partition,
            operation_id=f"scenario-{len(self.operations) + 1}",
            options=options,
            fault_hook=hook,
        )


class _Injected(RuntimeError):
    """The kit's own fault, so a scenario can tell an injection from a real failure."""


def _fault(label: str):
    def hook(point: str) -> None:
        if point == label:
            raise _Injected(f"injected fault at {label}")

    return hook


@contextmanager
def _scenario_world(connector, case, config, scenario: str) -> Iterator[_World]:
    replay = _replay_connector(connector, case)
    with scratch_workspace(clock=lambda: FIXED_INSTANT) as workspace:
        instance = prepare_instance(
            workspace, replay, config, clock=lambda: FIXED_INSTANT, partitions=(case.partition,)
        )
        receipt = _baseline(workspace, replay, case, config, instance)
        if receipt.generation_id is None:
            raise ContractViolation(scenario, f"{scenario}: the baseline run published nothing")
        store = workspace.ctx.store
        source_id = instance.sources[case.partition]
        world = _World(
            workspace=workspace,
            instance=instance,
            case=case,
            config=config,
            source_id=source_id,
            generation_id=receipt.generation_id,
            checksums=store.generation_checksums(receipt.generation_id),
            cursor_json=_cursor_json(store, instance, case),
            epoch=store.authorization_epoch(),
            policies=_span_policies(store),
            operations=[],
            connector=connector,
        )
        yield world


def _cursor_json(store, instance, case) -> str | None:
    from ..knowledge import model as k

    identity = k.SyncState(connector_id=instance.row.id, partition_key=case.partition).id
    state = store._knowledge_get("SyncState", identity)
    return None if state is None else state.cursor_json


def _span_policies(store) -> dict[str, str]:
    return {span.id: span.policy_id for span in store._knowledge_rows("EvidenceSpan")}


def _artifact(store, instance, external_id: str):
    for artifact in store._knowledge_rows("Artifact"):
        if artifact.connector_id == instance.row.id and artifact.external_id == external_id:
            return artifact
    return None


def _require(condition, scenario: str, what: str) -> None:
    if not condition:
        raise ContractViolation(scenario, f"{scenario}: {what}")


def _intact(world: _World, scenario: str) -> None:
    """G1 intact: the active pointer, the checksums, and a session that opens and closes."""
    from ..access import EVERYTHING
    from ..knowledge.query_access import query_session

    store = world.store
    source = store.get_source(world.source_id)
    _require(
        source.get("active_generation_id") == world.generation_id,
        scenario,
        "G1 is no longer the active generation",
    )
    _require(
        store.generation_checksums(world.generation_id) == world.checksums,
        scenario,
        "G1's checksums changed",
    )
    with query_session(world.workspace.ctx, EVERYTHING):
        pass


def _page_of(case, *changes, complete=False, scan=None):
    return base.ChangePage(
        partition=case.partition,
        changes=tuple(base.Change(ref=ref, operation=operation) for ref, operation in changes),
        next_cursor=(
            None
            if scan is None
            else base.SyncCursor(partition=case.partition, value=json.dumps({"page": 1}), scan=scan)
        ),
        complete=complete,
    )


def _injected(call, scenario: str, expected=_Injected):
    """Run a fault-injecting sync and require that the fault, and nothing else, came out."""
    try:
        call()
    except expected:
        return
    except ContractViolation:
        raise
    except Exception as error:
        raise ContractViolation(
            scenario, f"{scenario}: expected {expected.__name__}, got {type(error).__name__}: {error}"
        ) from error
    raise ContractViolation(scenario, f"{scenario}: the injected fault did not propagate")


def _members(store, generation_id) -> set[str]:
    return {
        member.artifact_revision_id
        for member in store._knowledge_rows("GenerationMember", generation_id=generation_id)
    }


def _published(world: _World, scenario: str, receipt) -> str:
    _require(receipt.outcome == "published", scenario, f"a later run answered {receipt.outcome}")
    return receipt.generation_id


def _scenario_crash_after_fetch(connector, case, config, a, b) -> None:
    scenario = "crash_after_fetch"
    with _scenario_world(connector, case, config, scenario) as world:
        page = (_page_of(case, (a, "delete")),)
        _injected(lambda: world.run(scenario, pages=page, hook=_fault("after_fetch")), scenario)
        _intact(world, scenario)
        artifact = _artifact(world.store, world.instance, a.external_id)
        _require(
            artifact is not None and artifact.deleted_at is None,
            scenario,
            "a crash before the checkpoint must leave no deletion behind",
        )
        _require(
            _cursor_json(world.store, world.instance, case) == world.cursor_json,
            scenario,
            "a crash before the checkpoint must not move the stored cursor",
        )
        second = _published(world, scenario, world.run(scenario, pages=page))
        _require(
            second != world.generation_id,
            scenario,
            "the run after the crash must publish a new generation",
        )
        deleted = _artifact(world.store, world.instance, a.external_id)
        _require(deleted is not None and deleted.deleted_at is not None, scenario, "A was not deleted")


def _scenario_replayed_page(connector, case, config, a, b) -> None:
    scenario = "replayed_page"
    with _scenario_world(connector, case, config, scenario) as world:
        page = (_page_of(case, (a, "delete")),)
        _injected(lambda: world.run(scenario, pages=page, hook=_fault("after_checkpoint")), scenario)
        after_two = (
            world.store.authorization_epoch(),
            _cursor_json(world.store, world.instance, case),
            _artifact(world.store, world.instance, a.external_id),
        )
        # N11: run 3 is an instant after run 2 (see `_World.run`), so a re-stamped row would show.
        _injected(lambda: world.run(scenario, pages=page, hook=_fault("after_checkpoint")), scenario)
        after_three = (
            world.store.authorization_epoch(),
            _cursor_json(world.store, world.instance, case),
            _artifact(world.store, world.instance, a.external_id),
        )
        _require(
            after_three == after_two,
            scenario,
            "a replayed page is a no-op by identity: the epoch, the cursor and the artifact all stand",
        )
        _intact(world, scenario)
        _published(world, scenario, world.run(scenario, pages=page))


def _scenario_failed_inventory(connector, case, config, a, b) -> None:
    scenario = "failed_inventory"
    from . import sync

    with _scenario_world(connector, case, config, scenario) as world:
        # Two pages, so the scan asks for page 1 and the provider refuses it there.
        pages = (
            _page_of(case, (a, "upsert"), complete=False, scan="inventory"),
            _page_of(case, (b, "upsert"), complete=True),
        )
        _injected(
            lambda: world.run(
                scenario,
                pages=pages,
                fail_on_page=1,
                options=sync.SyncOptions(emit_workers=1, reconcile=True),
            ),
            scenario,
            expected=ProviderTransientError,
        )
        for artifact in world.store._knowledge_rows("Artifact"):
            _require(
                artifact.deleted_at is None,
                scenario,
                "a failed inventory scan can confirm no absence, so it deletes nothing",
            )
        _intact(world, scenario)
        beyond = [
            generation
            for generation in world.store._knowledge_rows("Generation")
            if generation.source_id == world.source_id and generation.id != world.generation_id
        ]
        _require(not beyond, scenario, "a failed scan published a generation beyond G1")


def _scenario_policy_change_mid_page(connector, case, config, a, b) -> None:
    scenario = "policy_change_mid_page"
    with _scenario_world(connector, case, config, scenario) as world:
        before = _artifact(world.store, world.instance, a.external_id)
        # N12: the sequence narrows. A is read twice in one page: first as the case has it, then
        # as unknown, which the runtime stores as deny (S3 section 6.3, the narrowing half).
        known = case.policies.get(a.external_id) or base.PolicyObservation(
            ref=a, state="known", mode="workspace"
        )
        narrowing = dict(case.policies) | {
            a.external_id: [known, base.PolicyObservation(ref=a, state="unknown")]
        }
        page = (_page_of(case, (a, "upsert"), (a, "policy_change"), (b, "upsert")),)
        _injected(
            lambda: world.run(scenario, pages=page, policies=narrowing, hook=_fault("after_checkpoint")),
            scenario,
        )
        after = _artifact(world.store, world.instance, a.external_id)
        _require(
            after is not None and before is not None and after.policy_id != before.policy_id,
            scenario,
            "narrowing takes effect at the checkpoint, so A's artifact names the new policy",
        )
        _require(
            world.store.authorization_epoch() != world.epoch,
            scenario,
            "a narrowed policy moves the authorization epoch",
        )
        _intact(world, scenario)
        world.run(scenario, pages=page, policies=narrowing)
        for span_id, policy_id in world.policies.items():
            span = world.store._knowledge_get("EvidenceSpan", span_id)
            _require(
                span is not None and span.policy_id == policy_id,
                scenario,
                "R48: a stored span keeps its first capture's policy",
            )


def _scenario_delete_with_live_session(connector, case, config, a, b) -> None:
    scenario = "delete_with_live_session"
    from ..access import EVERYTHING
    from ..knowledge.access import AuthorizationChanged
    from ..knowledge.query_access import query_session

    with _scenario_world(connector, case, config, scenario) as world:
        manager = query_session(world.workspace.ctx, EVERYTHING)
        session = manager.__enter__()
        page = (_page_of(case, (a, "delete")),)
        try:
            _injected(lambda: world.run(scenario, pages=page, hook=_fault("after_checkpoint")), scenario)
            try:
                session.validate()
            except AuthorizationChanged:
                pass
            else:
                raise ContractViolation(
                    scenario, f"{scenario}: a deletion under a live session must invalidate it"
                )
        finally:
            # The exit raises the same refusal, which the kit catches; the generator is then closed
            # explicitly so an abandoned one never surfaces as an unraisable at interpreter exit.
            try:
                manager.__exit__(None, None, None)
            except AuthorizationChanged:
                pass
            finally:
                generator = getattr(manager, "gen", None)
                if generator is not None:
                    try:
                        generator.close()
                    except AuthorizationChanged:
                        pass
        with query_session(world.workspace.ctx, EVERYTHING):
            pass
        artifact = _artifact(world.store, world.instance, a.external_id)
        _require(
            artifact is not None and artifact.deleted_at is not None,
            scenario,
            "the checkpoint committed, so A is marked deleted",
        )
        _intact(world, scenario)
        second = _published(world, scenario, world.run(scenario, pages=page))
        revisions = _members(world.store, second)
        _require(
            all(
                world.store._knowledge_get("ArtifactRevision", revision).artifact_id != artifact.id
                for revision in revisions
            ),
            scenario,
            "the generation after the deletion still carries A",
        )


_SCENARIOS: dict[str, Callable] = {
    "crash_after_fetch": _scenario_crash_after_fetch,
    "replayed_page": _scenario_replayed_page,
    "failed_inventory": _scenario_failed_inventory,
    "policy_change_mid_page": _scenario_policy_change_mid_page,
    "delete_with_live_session": _scenario_delete_with_live_session,
}


# =========================================================================== the registry lock


def _body_hash(body) -> str:
    from ..knowledge.identity import canonical_json

    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _sorted(value):
    if isinstance(value, list):
        return sorted((_sorted(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, dict):
        return {name: _sorted(item) for name, item in value.items()}
    return value


def _kind_body(definition) -> dict:
    # N3: `model_dump(mode="json")` raises on `attrs_model`, which is a class. `fact_templates`
    # are excluded because each one is keyed and hashed under its own version, so bumping a
    # template's version does not have to bump the descriptor's.
    body = definition.model_dump(mode="json", exclude={"attrs_model", "fact_templates"})
    body["attrs"] = definition.attrs_model.model_json_schema(mode="validation")
    return _sorted(body)


def _locator_body(definition) -> dict:
    # A verifier is a callable, not vocabulary; the registry's own fingerprint does not read it
    # either (`knowledge/registry.py`, `LocatorKindDefinition.verifier`).
    model = definition.model
    return {
        "name": definition.name,
        "model": None if model is None else _sorted(model.model_json_schema(mode="validation")),
    }


def extension_lock(extension: TypeExtension, *, version: str) -> dict[str, str]:
    """Hash every template, kind, predicate and locator kind an extension registers."""
    lock: dict[str, str] = {}
    for kind in extension.object_kinds:
        lock[f"kind:{kind.name}@{version}"] = _body_hash(_kind_body(kind))
        for template in kind.fact_templates:
            key = f"template:{kind.name}/{template.name}@{template.version}"
            lock[key] = _body_hash(_sorted(template.model_dump(mode="json")))
    for predicate in extension.predicates:
        lock[f"predicate:{predicate.name}@{version}"] = _body_hash(_sorted(predicate.model_dump(mode="json")))
    for locator in extension.locator_kinds:
        lock[f"locator:{locator.name}@{version}"] = _body_hash(_locator_body(locator))
    return lock


def assert_registry_lock(extension: TypeExtension, *, version: str, lock_path: Path) -> None:
    """A key in both the lock and the extension must hash the same, or its version must move."""
    path = Path(lock_path)
    stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    current = extension_lock(extension, version=version)
    for key, digest in current.items():
        if key in stored and stored[key] != digest:
            raise ContractViolation(
                "registry_version_bump", f"{key} changed without a version bump", record=key
            )


def error_transport(error_class: str) -> httpx.MockTransport:
    """One canned response per error class, classified by S3's own client."""
    responses = {
        "authentication": lambda: httpx.Response(401, json={"error": "unauthenticated"}),
        "forbidden": lambda: httpx.Response(403, json={"error": "forbidden"}),
        "not_found": lambda: httpx.Response(404, json={"error": "not found"}),
        "throttled": lambda: httpx.Response(429, json={"error": "slow down"}, headers={"Retry-After": "1"}),
        "transient": lambda: httpx.Response(503, json={"error": "unavailable"}),
        "malformed": lambda: httpx.Response(
            200, content=b"{not json", headers={"content-type": "application/json"}
        ),
    }
    if error_class not in responses:
        raise ValueError(f"Unknown error class {error_class!r}; the classes are {ERROR_CLASSES}")
    return httpx.MockTransport(lambda request: responses[error_class]())


# =========================================================================== packages


def load_connector_package(
    target: str | Path, *, allowlist: frozenset[str] = frozenset()
) -> tuple[Connector, Path]:
    """Resolve a package directory or an installed connector name to `(connector, package_dir)`."""
    import importlib
    import importlib.util
    import sys

    from .loader import ConnectorLoadError

    path = Path(target)
    if path.exists() and path.is_dir():
        if not (path / "__init__.py").exists():
            raise ConnectorLoadError(f"{path} is not a package: it holds no __init__.py")
        here = Path(__file__).resolve().parent
        resolved = path.resolve()
        if resolved.is_relative_to(here):
            module = importlib.import_module("hippo.connectors." + ".".join(resolved.relative_to(here).parts))
        else:
            name = f"hippo_connector_under_test_{resolved.name}"
            # Two packages may share a directory name across runs, and a stale submodule would
            # answer for the wrong tree, so the whole name is dropped before it is rebuilt.
            for cached in [n for n in sys.modules if n == name or n.startswith(f"{name}.")]:
                del sys.modules[cached]
            spec = importlib.util.spec_from_file_location(
                name, resolved / "__init__.py", submodule_search_locations=[str(resolved)]
            )
            if spec is None or spec.loader is None:
                raise ConnectorLoadError(f"{resolved} cannot be imported as a package")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        factory = getattr(module, "Connector", None)
        if factory is None:
            raise ConnectorLoadError(
                f"{resolved} exports no Connector; design section 9 names that the entry point"
            )
        connector = factory()
        return connector, Path(sys.modules[type(connector).__module__].__file__).resolve().parent

    from . import loader

    for entry in loader.discover_connectors(allowlist=allowlist):
        if entry.name != str(target):
            continue
        if entry.connector_class is None:
            raise ConnectorLoadError(f"{target} is a built-in kind with no connector package")
        connector = entry.connector_class()
        module = sys.modules[type(connector).__module__]
        return connector, Path(module.__file__).resolve().parent
    raise ConnectorLoadError(f"No connector named {str(target)!r} is installed and trusted")


def registry_diff(extension: TypeExtension) -> tuple[str, ...]:
    """What an extension adds over `Registry.with_builtins()`, sorted and independent of the lock."""
    from ..knowledge.registry import Registry

    builtins = Registry.with_builtins()
    lines: list[str] = []
    for kind in extension.object_kinds:
        if kind.name not in builtins.object_kinds():
            lines.append(f"+ kind {kind.name}")
        for template in kind.fact_templates:
            lines.append(f"+ template {kind.name}/{template.name}@{template.version}")
    for predicate in extension.predicates:
        if predicate.name not in builtins.predicates():
            lines.append(f"+ predicate {predicate.name}")
    for locator in extension.locator_kinds:
        if locator.name not in builtins.locator_kinds():
            lines.append(f"+ locator {locator.name}")
    for name in extension.artifact_kinds:
        if name not in builtins.artifact_kinds():
            lines.append(f"+ artifact kind {name}")
    for name in extension.connector_kinds:
        if name not in builtins.connector_kinds():
            lines.append(f"+ connector kind {name}")
    return tuple(sorted(lines))


def validate_package(
    target: str | Path,
    *,
    update_golden: bool = False,
    runtime: bool = True,
    allowlist: frozenset[str] = frozenset(),
) -> ValidationReport:
    """`hippo connector validate`: the whole kit, pointed at one package."""
    from ..knowledge.registry import RegistrationError
    from .loader import ConnectorLoadError

    def failed(scope, error, *, connector="", version="", diff=()):
        return ValidationReport(connector, version, scope, tuple(diff), (), (), error=error)

    try:
        connector, package_dir = load_connector_package(target, allowlist=allowlist)
    except ConnectorLoadError as error:
        return failed("contract", f"{type(error).__name__}: {error}")
    descriptor = connector.descriptor
    try:
        registry = kit_registry(descriptor)
    except RegistrationError as error:
        return failed(
            "contract",
            f"{type(error).__name__}: {error}",
            connector=descriptor.name,
            version=descriptor.version,
        )

    diff = registry_diff(descriptor.extension)
    cases = discover_cases(package_dir)
    if not cases:
        return failed(
            "contract",
            f"No fixture cases under {package_dir / 'fixtures'}",
            connector=descriptor.name,
            version=descriptor.version,
            diff=diff,
        )

    violations: list[ContractViolation] = []
    with base.use_registry(registry):
        if descriptor.capabilities.derivation == "coordinator_lane":  # R1
            for case_dir in cases:
                case = load_case(case_dir)
                config = descriptor.config_model.model_validate(case.config)
                violations.extend(check_capture(connector, config, sample=10))
            return ValidationReport(
                descriptor.name, descriptor.version, "capture", diff, (), tuple(violations)
            )

        try:
            assert_registry_lock(
                descriptor.extension,
                version=descriptor.version,
                lock_path=package_dir / "fixtures" / "registry.lock.json",
            )
        except ContractViolation as violation:
            violations.append(violation)

        for case_dir in cases:
            case = load_case(case_dir)
            config = descriptor.config_model.model_validate(case.config)
            replay = _replay_connector(connector, case)
            violations.extend(check_capture(replay, config, sample=max(1, _change_count(case))))
            violations.extend(_contract_pass(replay, case, config, registry, descriptor))

    if not runtime:
        return ValidationReport(descriptor.name, descriptor.version, "contract", diff, (), tuple(violations))

    results = tuple(run_case(connector, load_case(path), update_golden=update_golden) for path in cases)
    for path in sorted(cases):
        case = load_case(path)
        if _change_count(case, operation="upsert") >= 2:
            try:
                assert_runtime_resilience(connector, case)
            except ContractViolation as violation:
                violations.append(violation)
            break
    return ValidationReport(descriptor.name, descriptor.version, "full", diff, results, tuple(violations))


def _change_count(case: FixtureCase, *, operation: str | None = None) -> int:
    return sum(
        1
        for page in case.pages
        for change in page.changes
        if operation is None or change.operation == operation
    )


def _contract_pass(replay, case, config, registry, descriptor) -> list[ContractViolation]:
    """Step 5: capture, emit and check every upsert with a raw store and no database."""
    from ..knowledge import model as k
    from ..knowledge.raw_artifacts import RawArtifactStore
    from ..store.migrations import DEFAULT_WORKSPACE_ID
    from .sync import SyncOptions

    violations: list[ContractViolation] = []
    classification = replay.probe(config, lambda: FIXED_INSTANT)
    mapping = next(
        (entry.mapping for entry in classification.partitions if entry.partition == case.partition),
        None,
    )
    if mapping is None:
        return [
            ContractViolation(
                "registered_vocabulary",
                f"probe classified no partition named {case.partition!r}",
                record=case.partition,
            )
        ]
    row = k.Connector(
        workspace_id=DEFAULT_WORKSPACE_ID,
        kind=descriptor.name,
        instance_url=KIT_INSTANCE_URL,
        config_json=config.model_dump_json(),
        enabled=True,
    )
    started = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="hippo-connector-kit-raw-") as directory:
        raw_store = RawArtifactStore(
            Path(directory).resolve(), max_object_bytes=SyncOptions().max_fetch_bytes
        )
        for page in case.pages:
            for change in page.changes:
                if change.operation != "upsert":
                    continue
                fetched = replay.fetch(config, change.ref)
                policy = replay.fetch_policy(config, change.ref)
                raw = raw_store.put_bytes(fetched.data)
                captured = emit.capture_records(
                    fetched,
                    policy,
                    connector=row,
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    source_id=f"kit-{case.name}",
                    raw_uri=raw.uri,
                    observed_at=FIXED_INSTANT,
                    policy_expires_at=FIXED_INSTANT + POLICY_TTL,
                )
                revision = base.RevisionInput(
                    partition=case.partition,
                    artifact=captured.artifact,
                    revision=captured.revision,
                    data=fetched.data,
                    config=config,
                    mapping=mapping,
                    registry=registry,
                    span_policy_id=captured.policy.id,  # R48
                )
                try:
                    batch = assert_emit_pure(replay, revision, mapping)
                except ContractViolation as violation:
                    violations.append(violation)
                    continue
                violations.extend(
                    check_contract(
                        batch,
                        AssertionContext(
                            registry=registry,
                            descriptor=descriptor,
                            connector=row,
                            revision=revision,
                            policy=policy,
                            clock_instant=FIXED_INSTANT,
                            run_window=(started, datetime.now(UTC)),
                        ),
                    )
                )
    return violations
