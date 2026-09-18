"""The `incidents_ndjson` connector: an NDJSON incident export, one JSON object per line.

This is the shape every incident tool exports and webhooks: PagerDuty, incident.io and FireHydrant
all hand out one object per line. One line is one record, so a record's span is one `file_lines`
line and the kit needs no locator kind of its own.

A connector has two halves, and the split is the whole design:

* **The sync half** (`probe`, `list_changes`, `fetch`, `fetch_policy`) talks to the provider. Here
  the provider is a file: this connector reads files only and opens no transport, so it commits no
  `http/` recording (ruling R75).
* **`emit` is pure.** Bytes in, records out. No network, no model, no store and no clock: the
  runtime runs it inside a guard that refuses all four, so a second run of the same revision
  produces byte-identical output and a rebuild can be trusted.

Every time in the graph comes from the record. `ts` is the incident's `started_at`, the `AFFECTS`
window is `started_at` to `resolved_at`, and the three intervals are differences between the
record's own stamps. The clock `probe` is handed is used for nothing: two probes an hour apart are
equal, which is what lets the kit replay one.

The ACL comes from the record too. `visibility` is `{"mode": "workspace"}` or `{"mode":
"restricted", "allow_users": [...], "allow_groups": [...]}`; anything else, or a missing field, is
`state="unknown"`, which the runtime stores as a policy nobody passes. The provider's own principal
ids are returned unmapped: `emit.policy_record` applies the instance's `principal_map` (rulings R44
and R61), so an unmapped principal denies rather than leaks.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from hippo.connectors import base, classify
from hippo.connectors.base import current_registry
from hippo.connectors.http import ProviderNotFoundError

from .types import (
    AFFECTS,
    EXTENSION,
    FAMILY,
    INCIDENT_KIND,
    INCIDENT_RECORD,
    SERVICE_KIND,
)

# One export file is one partition: an instance exports one stream of incidents.
PARTITION = "incidents"
# How many records `probe` reads before it decides what this partition holds. An export smaller
# than this is sampled whole, which is the case for every fixture here.
PROBE_SAMPLE = 10
PARSER = base.ParserVersion.parse("json@1")
# The fields a record must carry to be an incident at all. Anything else is a counted failure.
REQUIRED = ("id", "number", "title", "severity", "status", "service", "started_at")
# The provider types this connector reports to the classifier, and the kinds they map to. `None`
# is `custom/unclassified`: a line the exporter truncated is counted, never dropped.
UNPARSED = "unparsed"
KINDS = (
    base.KindMapping(provider_type="incident", kind=INCIDENT_KIND),
    base.KindMapping(provider_type="service", kind=SERVICE_KIND),
    base.KindMapping(provider_type=UNPARSED, kind=None),
)


class IncidentsExportConfig(BaseModel):
    """One instance's configuration, stored as JSON on its `Connector` row.

    `extra="forbid"` means a typo in a configuration file is refused rather than ignored. Never put
    a secret here: name a credential in the descriptor and reference it instead. This connector
    needs none, because it reads a file the operator already has.

    * `export_path` is the NDJSON export. The probe route reads it through the **stored** value and
      never through a request body, so an HTTP caller cannot make the server read an arbitrary path.
    * `instance_url` is the incident tool (m8): `ensure_connector` requires an HTTP(S) instance, and
      the kit fills the `instance` part of every incident key from it.
    * `catalog_instance` is the service catalog that names the services this tool reports against
      (ruling R53 / M6). The `AFFECTS` endpoint is keyed by it, so the catalog's own connector and
      this one mint the same `service` object.
    * `principal_map` maps this tool's user and group ids to local ones (rulings R44, R61). An
      unmapped principal is dropped from an allow list and counted; a list the mapping empties
      becomes unknown, which is deny.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    export_path: str
    instance_url: str
    catalog_instance: str
    principal_map: base.PrincipalMap = base.PrincipalMap()


DESCRIPTOR = base.ConnectorDescriptor(
    name="incidents_ndjson",
    version="1",
    families=(FAMILY,),
    # `service` is declared because this connector emits the endpoint of an edge it owns, not
    # because it owns the service family: an endpoint node is an observation (R-S2-6).
    kinds=(INCIDENT_KIND, SERVICE_KIND),
    predicates=(AFFECTS,),
    artifact_kinds=(INCIDENT_RECORD,),
    locator_kinds=("file_lines",),
    # M15: the export is an inventory (a walk from no cursor sees the whole partition) and the
    # records carry their own ACLs.
    capabilities=base.ConnectorCapabilities(acls=True, inventory=True),
    config_model=IncidentsExportConfig,
    credentials=(),
    parsers=(PARSER,),
    extension=EXTENSION,
)


class IncidentsNdjsonConnector:
    """The `incidents_ndjson` connector. Construct it with no arguments: the kit does."""

    # A class attribute, not an instance one: the loader reads `descriptor` off the class before it
    # constructs anything (ruling R77, `hippo.connectors.loader`).
    descriptor = DESCRIPTOR

    # ------------------------------------------------------------ the sync half

    def probe(self, config: IncidentsExportConfig, clock) -> base.Classification:
        """What this partition holds, sampled through this connector's own methods.

        Sampling through `list_changes` and `fetch` rather than through a private path is what lets
        the kit replay a probe exactly. Nothing here reads `clock`: `probe` is a pure function of
        the descriptor, the configuration and the sampled bytes, so two calls an hour apart are
        equal and `probe_deterministic` holds.
        """
        items: list[classify.SampledItem] = []
        cursor: base.SyncCursor | None = None
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
                        provider_type="incident" if _parsed(fetched.data) else UNPARSED,
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
            kinds=KINDS,
        )

    def list_changes(self, config: IncidentsExportConfig, cursor: base.SyncCursor | None) -> base.ChangePage:
        """Every non-empty line of the export, as one complete page.

        `capabilities.inventory` is true, which promises that a walk from `cursor=None` sees the
        whole partition; the page is marked complete because a file walk always does. The runtime
        withdraws what a *complete* walk did not return, so a real provider that pages must mark
        only its last page complete.

        The cursor is the SHA-256 of the file's bytes, so an export nobody re-exported answers with
        an empty page and the run ends in `no_changes` without reading a record.
        """
        data = _read(config)
        digest = hashlib.sha256(data).hexdigest()
        next_cursor = base.SyncCursor(
            partition=PARTITION, value=json.dumps({"sha256": digest}, sort_keys=True)
        )
        if cursor is not None and _digest_of(cursor) == digest:
            return base.ChangePage(partition=PARTITION, changes=(), next_cursor=next_cursor, complete=True)
        changes = tuple(
            base.Change(
                ref=base.ExternalRef(
                    partition=PARTITION,
                    artifact_kind=INCIDENT_RECORD,
                    external_id=_external_id(line),
                    provider_revision=_updated_at(line),
                ),
                operation="upsert",
            )
            for line in _lines(data)
        )
        return base.ChangePage(partition=PARTITION, changes=changes, next_cursor=next_cursor, complete=True)

    def fetch(self, config: IncidentsExportConfig, ref: base.ExternalRef) -> base.RawFetch:
        """One record's line, exactly as the export holds it, without its newline.

        The bytes are returned unchanged: they are hashed, stored and re-parsed later, so a
        normalisation here would make a rebuild differ from the first build. An id the export no
        longer holds is `ProviderNotFoundError` (M15), which is the confirmation the runtime needs
        before it infers a deletion.
        """
        line = _line_of(config, ref.external_id)
        if line is None:
            raise ProviderNotFoundError(url=_uri(config, ref.external_id), status=404, attempts=1)
        updated = _updated_at(line)
        return base.RawFetch(
            ref=ref,
            data=line.encode("utf-8"),
            content_type="application/x-ndjson",
            external_id=ref.external_id,
            # Never a URL carrying a token or a password: this is stored and shown.
            canonical_uri=_uri(config, ref.external_id),
            provider_revision=updated,
            source_updated_at=_instant(updated),
            source_timestamp_original=updated,
            source_timezone="UTC" if updated else None,
            source_precision="second" if updated else "unknown",
            parser=PARSER,
        )

    def fetch_policy(self, config: IncidentsExportConfig, ref: base.ExternalRef) -> base.PolicyObservation:
        """Who may see this record, read off its own `visibility` field.

        Two shapes are known and everything else is unknown, which is deny: a mode this connector
        does not recognise is a tool it has not been taught, not a record everyone may read. The
        principals are the provider's own ids; the instance's `principal_map` is applied downstream
        by `emit.policy_record`, so an unmapped principal denies rather than leaks (R44, R61).
        """
        record = _parsed_line(_line_of(config, ref.external_id))
        visibility = record.get("visibility") if isinstance(record, dict) else None
        mode = visibility.get("mode") if isinstance(visibility, dict) else None
        if mode == "workspace":
            return base.PolicyObservation(ref=ref, state="known", mode="workspace")
        if mode == "restricted":
            return base.PolicyObservation(
                ref=ref,
                state="known",
                mode="restricted",
                allow_users=tuple(visibility.get("allow_users") or ()),
                allow_groups=tuple(visibility.get("allow_groups") or ()),
            )
        return base.PolicyObservation(ref=ref, state="unknown")

    # ------------------------------------------------------------ the pure half

    def emit(self, revision: base.RevisionInput, mapping: base.TypeMapping) -> base.EmissionBatch:
        """One export line to one incident, one service endpoint and one dated edge.

        Pure: no clock, no network, no model, no store. A line this connector cannot read becomes a
        counted `ParseFailure` rather than an exception, because one bad record must not fail a
        partition and a failure nobody counted is a silent gap in the memory.

        The kit renders both fact templates and the edge statement (design section 6); nothing here
        writes statement text or a rendered unit.
        """
        record = _parsed_line(revision.data.decode("utf-8"))
        if not isinstance(record, dict) or any(record.get(field) is None for field in REQUIRED):
            return base.EmissionBatch(
                failures=(base.ParseFailure(family=FAMILY, reason="invalid_incident", parser=PARSER),)
            )
        span = _span(revision)
        started, resolved = _instant(record["started_at"]), _instant(record.get("resolved_at"))
        incident = base.NodeRef(kind=INCIDENT_KIND, key={"incident_id": str(record["id"])})
        service = base.NodeRef(
            kind=SERVICE_KIND,
            key={"reference": str(record["service"])},
            # R53: the endpoint carries the catalog that minted its name, so the catalog's own
            # connector and this one write the same object. R71: and the label the statement reads.
            instance=revision.config.catalog_instance,
            label=str(record["service"]),
        )
        return base.EmissionBatch(
            nodes=(
                base.NodeEmission(
                    ref=incident,
                    attrs=_attributes(record),
                    span=span,
                    source="metadata",
                    metadata_origin="catalog",
                    ts=started,
                    ts_original=record["started_at"],
                    ts_timezone="UTC",
                    ts_precision="second",
                ),
                base.NodeEmission(
                    # Identity only: this connector observes the service, it does not own it, so
                    # the attributes are discarded and the label is what names it (R6, R71).
                    ref=service,
                    attrs={},
                    span=span,
                    source="metadata",
                    metadata_origin="catalog",
                ),
            ),
            edges=(
                base.EdgeEmission(
                    subject=incident,
                    predicate=AFFECTS,
                    object=service,
                    family="deterministic",
                    source="metadata",
                    metadata_origin="catalog",
                    weight=1.0,
                    support=(base.SupportEmission(spans=(span,)),),
                    # The window is the incident's own: open while it is unresolved.
                    valid_from=started,
                    valid_to=resolved,
                    window_precision="second",
                ),
            ),
        )


# ------------------------------------------------------------------ reading the export
# Every function below is pure: bytes and strings in, values out. `emit` calls only the ones that
# take a line, because the guard would refuse a file read inside it.


def _read(config: IncidentsExportConfig) -> bytes:
    return Path(config.export_path).read_bytes()


def _lines(data: bytes) -> list[str]:
    return [line for line in data.decode("utf-8").split("\n") if line.strip()]


def _parsed(data: bytes) -> dict | None:
    return _parsed_line(data.decode("utf-8"))


def _parsed_line(line: str | None) -> dict | None:
    if line is None:
        return None
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _external_id(line: str) -> str:
    """The record's own id, or a content address for a line that is not a JSON object.

    A truncated line still gets a change, so `emit` can count it rather than the export silently
    holding one record fewer than the tool exported.
    """
    record = _parsed_line(line)
    if record is not None and record.get("id") is not None:
        return str(record["id"])
    return "line-sha256:" + hashlib.sha256(line.encode("utf-8")).hexdigest()


def _updated_at(line: str) -> str | None:
    record = _parsed_line(line)
    updated = record.get("updated_at") if record is not None else None
    return str(updated) if updated is not None else None


def _line_of(config: IncidentsExportConfig, external_id: str) -> str | None:
    for line in _lines(_read(config)):
        if _external_id(line) == external_id:
            return line
    return None


def _uri(config: IncidentsExportConfig, external_id: str) -> str:
    return f"{config.instance_url}/incidents/{external_id}"


def _digest_of(cursor: base.SyncCursor) -> str | None:
    try:
        return json.loads(cursor.value).get("sha256")
    except ValueError:
        return None


def _instant(spelling: str | None) -> datetime | None:
    if not spelling:
        return None
    try:
        return datetime.fromisoformat(str(spelling).replace("Z", "+00:00"))
    except ValueError:
        return None


def _minutes(record: dict, field: str) -> int | None:
    """Whole minutes from `started_at` to `field`, or None when the tool has not reported it.

    None is the honest answer, and it is what keeps `incident_resolution` from being rendered at
    all: `render_facts` skips a template whose consumed attribute is None (R-S2-5).
    """
    start, end = _instant(record.get("started_at")), _instant(record.get(field))
    if start is None or end is None or end < start:
        return None
    return int((end - start).total_seconds() // 60)


def _attributes(record: dict) -> dict:
    return {
        "number": int(record["number"]),
        "title": str(record["title"]),
        "severity": str(record["severity"]),
        "status": str(record["status"]),
        "service": str(record["service"]),
        "started_at": str(record["started_at"]),
        "resolved_at": str(record["resolved_at"]) if record.get("resolved_at") else None,
        "mttd_minutes": _minutes(record, "detected_at"),
        "mttm_minutes": _minutes(record, "mitigated_at"),
        "mttr_minutes": _minutes(record, "resolved_at"),
    }


def _span(revision: base.RevisionInput) -> base.SpanRef:
    """The whole revision: one NDJSON line is one line of one file.

    The path names the export the line came from. It is not checked against the revision, because
    an `incident_record` is not a `file`; it is there so a reader of the span knows which export
    the line was read out of.
    """
    text = revision.data.decode("utf-8")
    return base.SpanRef(
        locator_kind="file_lines",
        locator={"kind": "file_lines", "path": Path(revision.config.export_path).name, "start": 1, "end": 1},
        text=text,
    )
