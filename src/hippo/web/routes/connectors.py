"""
Connectors over HTTP: what is installed, what an instance holds, and whether a kind still validates.

    GET  /api/connectors                          every connector this process can see
    GET  /api/connectors/{connector_id}/classification   the stored probe result of one instance
    POST /api/connectors/{connector_id}/probe     probe that instance and store what it answered
    POST /api/connectors/kinds/{name}/validate    the contract validation of an installed kind

Every endpoint is behind `manage_sources`: a connector names a provider instance and, once probed,
the shape of somebody's incident tracker.

Two narrowings the design leaves open, ratified as ruling R8:

* **Probe runs on the instance's stored configuration and takes no request body.** This connector
  family reads local paths (the incidents exemplar's `export_path` is one), so a caller-supplied
  configuration would let an HTTP request make the server read an arbitrary file. The stored value
  is the one an operator wrote with `hippo connector enable`.
* **Validate returns the `contract`-scope report**, not the golden run. A full run opens a scratch
  LadybugDB and rebuilds every fixture case, which costs minutes and gigabytes and does not belong
  inside a request. `hippo connector validate` keeps the full run.

The payload builders are plain functions, because `mcp_server.py` serves the same three answers as
the `hippo_connectors` tool and calls these to do it - the HTTP and MCP shapes are the same objects,
not two descriptions of one shape that could drift apart. `web/routes/code.py` uses the same
arrangement for the code tools.

Failures follow finding m11. `knowledge/public_errors.py` cannot name `hippo.connectors` classes, so
the four connector vocabularies are mapped here: a credential failure, a provider failure, a
descriptor asking for vocabulary nobody registered, and a sync the runtime refused. Every one of
them can carry an instance URL that a mistaken configuration gave credentials to, so none of their
messages is ever interpolated into a response - the code is the answer, and the sentence is this
module's own.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request

from ..auth import require
from ..render import coded_response, ctx_of

api = APIRouter(prefix="/api/connectors")

NOT_FOUND = "not_found"
# One bounded sentence per connector failure vocabulary. The raised message is never read: a
# provider error names the URL it called, and a mistaken configuration can put a token in it.
CONNECTOR_FAILURES: tuple[tuple[str, str, str, int], ...] = (
    ("CredentialError", "credential_unavailable", "This connector's credential is not available.", 409),
    ("ProviderError", "provider_unavailable", "The provider did not answer this request.", 502),
    (
        "RegistrationRequired",
        "registration_required",
        "This connector names vocabulary nothing has registered; run hippo connector validate.",
        409,
    ),
    ("ConnectorSyncRefused", "connector_refused", "This connector instance cannot run right now.", 409),
)


class ConnectorNotFound(LookupError):
    """An instance or a kind this process cannot see.

    `message` is a bounded sentence written here, naming the caller's own input and nothing that was
    read on the way to not finding it. The route answers with that attribute rather than with the
    exception's own words, which is the rule `render.py` states for the whole web layer and
    `tests/unit/test_managed_web_surfaces.py` enforces by counting every site that prints one.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------- payload builders
# Pure apart from the store reads they name: a context in, JSON-friendly dicts out.
# `mcp_server.py` calls these too, so the MCP and HTTP answers are the same shape.


def connectors_payload(ctx, load=None) -> list[dict[str, Any]]:
    """Every discovered connector with its instances: the `ConnectorSummary` list of S4 section 3.3.

    Rows are keyed on `(origin, name)`, not on `name`: an in-repo package and an entry point it
    shadows legitimately share a name, and both are shown with their own `error` (ruling R64). The
    two error spellings a reader meets are an exception class name and `"frozen"`, which means the
    kind was enabled after this process froze its registry and will register at the next restart.

    `load` is the server's own `LoadResult`, held on `app.state.connector_load` by the lifespan.
    Passing none loads afresh, which is what the CLI does and what a test does.
    """
    from ...connectors import loader

    load = loader.load_connectors(ctx) if load is None else load
    instances: dict[str, list[dict[str, Any]]] = {}
    for row in ctx.store._knowledge_rows("Connector"):
        stored = json.loads(row.classification_json or "{}")
        instances.setdefault(row.kind, []).append(
            {
                "id": row.id,
                "enabled": row.enabled,
                "partitions": [
                    {"partition": entry["partition"], "family": entry["family"]}
                    for entry in stored.get("partitions", ())
                ],
            }
        )
    summaries = []
    for entry in load.entries:
        # A built-in kind has no package and therefore no descriptor; it is still listed, with the
        # empty version an operator reads as "nothing to enable here" (ruling R69).
        descriptor = getattr(entry.connector_class, "descriptor", None)
        summaries.append(
            {
                "name": entry.name,
                "version": getattr(descriptor, "version", ""),
                "families": list(getattr(descriptor, "families", ())),
                "origin": entry.origin,
                "enabled": entry.enabled,
                "error": entry.error,
                "instances": instances.get(entry.name, []),
            }
        )
    return summaries


def classification_payload(ctx, connector_id: str) -> dict[str, Any]:
    """The classification a probe stored on this instance (design section 2, ruling R12)."""
    row = _instance(ctx, connector_id)
    if not row.classification_json:
        raise ConnectorNotFound(f"connector instance '{connector_id}' has no stored classification")
    return json.loads(row.classification_json)


def probe_payload(ctx, connector_id: str) -> dict[str, Any]:
    """Probe one instance against its **stored** configuration and store what it answered.

    The write runs under the connector's own scratch registry: a `Connector` row is vocabulary
    checked on the way into the store, and this process may not have loaded the kind (re-review
    N5, the reasoning `hippo connector enable` already follows). Ruling R21 means an unchanged
    result writes nothing.
    """
    from ...connectors import base, testing

    row = _instance(ctx, connector_id)
    connector, config = _instance_connector(ctx, row)
    with base.use_registry(testing.kit_registry(connector.descriptor)):
        return _probe_classification(ctx, row, connector, config)


def _probe_classification(ctx, row, connector, config) -> dict[str, Any]:
    from ...connectors import sync

    classification = connector.probe(config, _wall_clock())
    sync.store_classification(ctx.store, connector=row, classification=classification)
    return json.loads(classification.model_dump_json())


def validation_payload(name: str) -> dict[str, Any]:
    """`validate_package(name, runtime=False)`: registration, the registry lock and the contract.

    Scope `contract` covers the registry diff, the lock, the capture assertions and `check_contract`
    plus `assert_emit_pure` over every case. What it deliberately leaves out is the scratch build,
    for the reason in this module's docstring.
    """
    from ...connectors import loader, testing

    report = testing.validate_package(name, runtime=False, allowlist=loader.configured_allowlist())
    if report.error is not None and not report.connector:
        # The package could not be loaded at all, which for a name is "no such kind".
        raise ConnectorNotFound(f"no connector kind '{name}' is installed and trusted")
    return report.to_json()


def _instance(ctx, connector_id: str):
    row = ctx.store._knowledge_get("Connector", connector_id)
    if row is None:
        raise ConnectorNotFound(f"no connector instance '{connector_id}'")
    return row


def _instance_connector(ctx, row):
    """The connector class of a stored row, and the configuration that row carries.

    Trust, not enablement, is what a probe needs: it is an operator action against one instance the
    operator already created, and `sync` gates enablement at its own entry (R51).
    """
    from ...connectors import loader

    for entry in loader.discover_connectors(allowlist=loader.configured_allowlist()):
        if entry.name != row.kind:
            continue
        if entry.connector_class is None:
            raise ConnectorNotFound(f"connector kind '{row.kind}' has no installed package")
        connector = entry.connector_class()
        return connector, connector.descriptor.config_model.model_validate_json(row.config_json)
    raise ConnectorNotFound(f"no connector kind '{row.kind}' is installed and trusted")


def _wall_clock():
    from datetime import UTC, datetime

    return lambda: datetime.now(UTC)


def connector_failure(exc: BaseException):
    """m11: the four connector vocabularies as coded responses, with the raised text discarded.

    Returns None for anything this table does not name, so the caller re-raises and the app's own
    public-failure handler owns it.
    """
    names = {klass.__name__ for klass in type(exc).__mro__}
    for name, code, message, status in CONNECTOR_FAILURES:
        if name in names:
            return coded_response(message, code, status)
    return None


# ------------------------------------------------------------------- routes


def _answer(request: Request, build):
    require(request, "manage_sources")
    try:
        return build(ctx_of(request))
    except ConnectorNotFound as exc:
        return coded_response(exc.message, NOT_FOUND, 404)
    except Exception as exc:
        answered = connector_failure(exc)
        if answered is None:
            raise
        return answered


@api.get("")
def list_connectors(request: Request):
    load = getattr(request.app.state, "connector_load", None)
    return _answer(request, lambda ctx: connectors_payload(ctx, load))


@api.get("/{connector_id}/classification")
def connector_classification(request: Request, connector_id: str):
    return _answer(request, lambda ctx: classification_payload(ctx, connector_id))


@api.post("/{connector_id}/probe")
def probe_connector(request: Request, connector_id: str):
    # No request body is read: see the module docstring.
    return _answer(request, lambda ctx: probe_payload(ctx, connector_id))


@api.post("/kinds/{name}/validate")
def validate_connector(request: Request, name: str):
    return _answer(request, lambda _ctx: validation_payload(name))
