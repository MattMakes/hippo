"""`FixtureConnector`: the connector the runtime is proved against (plan section 11, ruling R10).

It is never shipped and never auto-registered. `FixtureConnector()` constructs with no arguments
and reads `fixtures/basic` (ruling R60 / R-S3-7), so the test kit can build one without knowing
anything about this package.

`emit` is pure: it reads the revision bytes and the stored mapping and touches nothing else, which
is what lets the runtime run it inside `guard.forbid_effects()`.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict

from hippo.connectors import base, classify
from hippo.connectors.http import HttpLimits, ProviderClient
from hippo.knowledge.registry import current_registry

from .provider import DEFAULT_INSTANCE, DEFAULT_PARTITION, FixtureProvider
from .types import (
    FIXTURE_CONNECTOR_KIND,
    FIXTURE_EXTENSION,
    FIXTURE_FAMILY,
    FIXTURE_LINKS,
    FIXTURE_NOTE_KIND,
)

BASIC_CASE = Path(__file__).resolve().parent / "fixtures" / "basic"
PROBE_SAMPLE = 10
# One attempt and no sleeping: a fixture provider's failure is the test's point, never a retry.
FIXTURE_LIMITS = HttpLimits(max_attempts=1, max_total_seconds=5.0)


class FixtureConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instance_url: str = DEFAULT_INSTANCE
    partition: str = DEFAULT_PARTITION


# cdk-guide: begin descriptor
DESCRIPTOR = base.ConnectorDescriptor(
    name=FIXTURE_CONNECTOR_KIND,
    version="1",
    families=(FIXTURE_FAMILY,),
    kinds=(FIXTURE_NOTE_KIND,),
    predicates=(FIXTURE_LINKS,),
    artifact_kinds=("document",),
    locator_kinds=("field",),
    capabilities=base.ConnectorCapabilities(changes_feed=True, deletion_feed=True, acls=True, inventory=True),
    config_model=FixtureConfig,
    credentials=(base.CredentialRequirement(name="fixture_token"),),
    parsers=(),
    extension=FIXTURE_EXTENSION,
)
# cdk-guide: end descriptor


def _instant(spelling: str | None) -> datetime | None:
    if not spelling:
        return None
    return datetime.fromisoformat(spelling.replace("Z", "+00:00"))


def _sentences(text: str) -> list[tuple[int, int]]:
    """Character offsets of each sentence, terminator included; no clock, no regex backtracking."""
    spans, start = [], 0
    for index, character in enumerate(text):
        if character == "." and (index + 1 == len(text) or text[index + 1] in " \n\t"):
            spans.append((start, index + 1))
            start = index + 2
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _field_span(path: str, text: str | None = None) -> base.SpanRef:
    return base.SpanRef(locator_kind="field", locator={"kind": "field", "field_path": path}, text=text)


def _note_ref(external_id: str) -> base.NodeRef:
    return base.NodeRef(kind=FIXTURE_NOTE_KIND, key={"note_id": external_id})


class FixtureConnector:
    """The sync half over `FixtureProvider`, plus a pure `emit`."""

    def __init__(self, provider: FixtureProvider | None = None, *, case=None, descriptor_extension=None):
        if provider is None:
            provider = FixtureProvider.from_case(Path(case or BASIC_CASE))
        self.provider = provider
        self.descriptor = DESCRIPTOR
        if descriptor_extension is not None:
            self.descriptor = DESCRIPTOR.model_copy(update={"extension": descriptor_extension})
        self.client = ProviderClient(
            provider.instance,
            limits=FIXTURE_LIMITS,
            transport=httpx.MockTransport(provider.handle),
            sleep=lambda _seconds: None,
        )

    # ------------------------------------------------------------------ the sync half

    # cdk-guide: begin sync_half
    def probe(self, config: BaseModel, clock) -> base.Classification:
        """Sample through this connector's own `list_changes` and `fetch` (ruling R60)."""
        items, cursor = [], None
        while len(items) < PROBE_SAMPLE:
            page = self.list_changes(config, cursor)
            for change in page.changes:
                if change.operation != "upsert" or len(items) >= PROBE_SAMPLE:
                    continue
                fetched = self.fetch(config, change.ref)
                items.append(
                    classify.SampledItem(
                        partition=change.ref.partition,
                        path=change.ref.external_id,
                        data=fetched.data,
                        provider_type="note",
                    )
                )
            cursor = page.next_cursor
            if page.complete or cursor is None:
                break
        return classify.classify(
            self.descriptor,
            config,
            items,
            current_registry(),
            spec=classify.classifier_spec(),
            capabilities=self.descriptor.capabilities,
            kinds=(base.KindMapping(provider_type="note", kind=FIXTURE_NOTE_KIND),),
        )

    def list_changes(self, config: BaseModel, cursor: base.SyncCursor | None) -> base.ChangePage:
        page = 0 if cursor is None else int(json.loads(cursor.value)["page"])
        scan = "inventory" if cursor is None else cursor.scan
        body, _headers = self.client.get_bytes(
            f"api/partitions/{quote(config.partition, safe='')}/changes",
            params={"page": str(page), "scan": scan},
        )
        # The contract models are strict, so the page is validated from JSON, never from a dict.
        return base.ChangePage.model_validate_json(body)

    def fetch(self, config: BaseModel, ref: base.ExternalRef) -> base.RawFetch:
        data, _headers = self.client.get_bytes(f"api/notes/{quote(ref.external_id, safe='')}")
        note = json.loads(data.decode("utf-8"))
        return base.RawFetch(
            ref=ref,
            data=data,
            content_type="application/json",
            external_id=ref.external_id,
            canonical_uri=note["url"],
            provider_revision=note.get("updated"),
            source_updated_at=_instant(note.get("updated")),
            source_timestamp_original=note.get("updated"),
            source_timezone="UTC",
            source_precision="second",
        )

    def fetch_policy(self, config: BaseModel, ref: base.ExternalRef) -> base.PolicyObservation:
        body, _headers = self.client.get_bytes(f"api/notes/{quote(ref.external_id, safe='')}/acl")
        payload = json.loads(body.decode("utf-8")) | {"ref": ref.model_dump(mode="json")}
        return base.PolicyObservation.model_validate_json(json.dumps(payload))

    # cdk-guide: end sync_half

    # ------------------------------------------------------------------ the pure half

    # cdk-guide: begin emit
    def emit(self, revision: base.RevisionInput, mapping: base.TypeMapping) -> base.EmissionBatch:
        note = json.loads(revision.data.decode("utf-8"))
        if "body" not in note:
            return base.EmissionBatch(
                failures=(base.ParseFailure(family=FIXTURE_FAMILY, reason="missing_body"),)
            )
        ref = _note_ref(note["id"])
        nodes = [
            base.NodeEmission(
                ref=ref,
                attrs={"title": note["title"], "updated": note.get("updated")},
                span=_field_span("title", note["title"]),
                source="metadata",
                metadata_origin="catalog",
                ts=_instant(note.get("updated")),
                ts_original=note.get("updated"),
                ts_timezone="UTC",
                ts_precision="second",
            )
        ]
        body = note["body"]
        passages = [base.PassageEmission(key="body", span=_field_span("body", body), title=note["title"])]
        units = [
            base.UnitEmission(
                key=f"sentence-{ordinal}",
                passage="body",
                ordinal=ordinal,
                kind="sentence",
                span=_field_span("body", body),
                start=start,
                end=end,
            )
            for ordinal, (start, end) in enumerate(_sentences(body))
        ]
        edges, aliases = [], []
        for index, target in enumerate(note.get("links", ())):
            path = f"links.{index}"
            nodes.append(self._endpoint(target, path))
            edges.append(
                base.EdgeEmission(
                    subject=ref,
                    predicate=FIXTURE_LINKS,
                    object=_note_ref(target),
                    family="deterministic",
                    source="metadata",
                    metadata_origin="catalog",
                    weight=1.0,
                    support=(base.SupportEmission(spans=(_field_span(path, target),)),),
                )
            )
        for index, target in enumerate(note.get("same_as", ())):
            path = f"same_as.{index}"
            nodes.append(self._endpoint(target, path))
            aliases.append(
                base.AliasEmission(
                    a=ref,
                    b=_note_ref(target),
                    rule="explicit_annotation",
                    support=(base.SupportEmission(spans=(_field_span(path, target),)),),
                )
            )
        return base.EmissionBatch(
            nodes=tuple(nodes),
            edges=tuple(edges),
            passages=tuple(passages),
            units=tuple(units),
            aliases=tuple(aliases),
        )

    @staticmethod
    def _endpoint(target: str, path: str) -> base.NodeEmission:
        """An endpoint this revision only names: its title is the id it was linked by.

        `updated` is absent, so `note_summary` renders nothing for it and the omission is counted
        rather than guessed (S6 R-S2-5).
        """
        return base.NodeEmission(
            ref=_note_ref(target),
            attrs={"title": target},
            span=_field_span(path, target),
            source="metadata",
            metadata_origin="catalog",
        )

    # cdk-guide: end emit
