"""The contract test kit (CDK S4a): `hippo.connectors.testing`.

Plan `ai_docs/plans/cdk-s4-kit.md` section 3.1 and section 5 "S4a", amended by rulings R42, R49,
R57, R63, R64, R65 and R73 and by the re-review's findings N3, N4, N6, N7, N8, N9, N10, N11, N12,
N16 and m18 (`ai_docs/reports/2026-09-15-cdk-s4-replan-review.md`).

Every assertion the kit names has exactly one negative fixture in `VIOLATIONS` that fires it, and
the fixture connector's `fixtures/basic` case is the positive fixture that passes all of them.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from pydantic import BaseModel, ConfigDict

from hippo.connectors import base, emit, guard, http
from hippo.connectors import testing as kit
from hippo.connectors.testing import ContractViolation
from hippo.knowledge import model as k
from hippo.knowledge.identity import canonical_json
from hippo.knowledge.registry import FactTemplate, Registry, use_registry
from hippo.ollama import OllamaError
from hippo.store.migrations import DEFAULT_WORKSPACE_ID
from tests.conftest import LADYBUG_TEST_BUFFER_POOL_BYTES, store_backend
from tests.fakes import fake_ollama
from tests.fakes.fake_store import FakeStore
from tests.fakes.fixture_connector import BASIC_CASE, DESCRIPTOR, FixtureConfig, FixtureConnector
from tests.fakes.fixture_connector.types import (
    FIXTURE_FAMILY,
    FIXTURE_LINKS,
    FIXTURE_NOTE_KIND,
    fixture_extension,
    fixture_links_predicate,
    fixture_note_kind,
)

PARTITION = "notes"
EXPIRES = timedelta(minutes=10)
PACKAGE_DIR = BASIC_CASE.parent.parent
LOCK_PATH = PACKAGE_DIR / "fixtures" / "registry.lock.json"
ERROR_TYPES = {
    "authentication": http.ProviderAuthenticationError,
    "forbidden": http.ProviderForbiddenError,
    "not_found": http.ProviderNotFoundError,
    "throttled": http.ProviderThrottledError,
    "transient": http.ProviderTransientError,
    "malformed": http.ProviderMalformedError,
}


# --------------------------------------------------------------------------- the backend seam


@pytest.fixture(autouse=True)
def scratch_store(monkeypatch):
    """Plan section 5: the kit's scratch store is the backend `HIPPO_TEST_STORE` names."""
    backend = store_backend()
    if backend == "fake":
        monkeypatch.setattr(kit, "scratch_store", lambda path: FakeStore())
    elif backend == "ladybug":
        from hippo.store.ladybug import LadybugStore

        monkeypatch.setattr(
            kit,
            "scratch_store",
            lambda path: LadybugStore(path, buffer_pool_bytes=LADYBUG_TEST_BUFFER_POOL_BYTES),
        )
    else:  # pragma: no cover - the kit's scratch store is never a server
        pytest.skip(f"the kit's scratch store is not {backend}")


# --------------------------------------------------------------------------- shared fixtures


@pytest.fixture
def registry():
    return kit.kit_registry(DESCRIPTOR)


@pytest.fixture
def connector():
    return FixtureConnector()


@pytest.fixture
def case():
    return kit.load_case(BASIC_CASE)


@dataclass(frozen=True)
class Bench:
    """What a negative fixture is handed: the seams it needs and nothing else."""

    registry: Registry
    monkeypatch: Any
    tmp_path: Path

    @property
    def connector(self) -> FixtureConnector:
        return FixtureConnector()

    @property
    def case(self):
        return kit.load_case(BASIC_CASE)


@pytest.fixture
def bench(registry, monkeypatch, tmp_path):
    return Bench(registry=registry, monkeypatch=monkeypatch, tmp_path=tmp_path)


# --------------------------------------------------------------------------- record builders


def _replace(model, **fields):
    """`model_construct` keeping the model's own nested objects, where a validator would refuse."""
    data = {name: getattr(model, name) for name in type(model).model_fields}
    return type(model).model_construct(**(data | fields))


def _config() -> FixtureConfig:
    return FixtureConfig(instance_url=kit.KIT_INSTANCE_URL, partition=PARTITION)


def _mapping() -> base.TypeMapping:
    return base.TypeMapping(
        family=FIXTURE_FAMILY,
        kinds=(base.KindMapping(provider_type="note", kind=FIXTURE_NOTE_KIND),),
        predicates=(FIXTURE_LINKS,),
    )


def _row() -> k.Connector:
    return k.Connector(
        workspace_id=DEFAULT_WORKSPACE_ID,
        kind=DESCRIPTOR.name,
        instance_url=kit.KIT_INSTANCE_URL,
        config_json=_config().model_dump_json(),
        enabled=True,
    )


NOTE = {
    "id": "n1",
    "title": "First note",
    "body": "Alpha runs nightly. Beta follows alpha.",
    "updated": "2026-09-10T08:00:00Z",
    "url": f"{kit.KIT_INSTANCE_URL}/notes/n1",
    "links": ["n2"],
    "same_as": [],
}


def _ref(external_id: str = "n1") -> base.ExternalRef:
    return base.ExternalRef(partition=PARTITION, artifact_kind="document", external_id=external_id)


def _fetch(data: bytes, *, external_id: str = "n1", canonical_uri: str | None = None) -> base.RawFetch:
    return base.RawFetch(
        ref=_ref(external_id),
        data=data,
        content_type="application/json",
        external_id=external_id,
        canonical_uri=canonical_uri or f"{kit.KIT_INSTANCE_URL}/notes/{external_id}",
    )


def _known(external_id: str = "n1") -> base.PolicyObservation:
    return base.PolicyObservation(ref=_ref(external_id), state="known", mode="workspace")


def _revision(registry: Registry, *, data: bytes | None = None) -> base.RevisionInput:
    """One `RevisionInput` built with no database, the way `validate_package` step 5 does."""
    payload = json.dumps(NOTE, sort_keys=True).encode("utf-8") if data is None else data
    captured = emit.capture_records(
        _fetch(payload),
        _known(),
        connector=_row(),
        workspace_id=DEFAULT_WORKSPACE_ID,
        source_id="kit-basic",
        raw_uri=f"raw://kit/{hashlib.sha256(payload).hexdigest()}",
        observed_at=kit.FIXED_INSTANT,
        policy_expires_at=kit.FIXED_INSTANT + EXPIRES,
    )
    return base.RevisionInput(
        partition=PARTITION,
        artifact=captured.artifact,
        revision=captured.revision,
        data=payload,
        config=_config(),
        mapping=_mapping(),
        registry=registry,
        span_policy_id=captured.policy.id,
    )


def _context(
    registry: Registry,
    *,
    revision: base.RevisionInput | None = None,
    policy: base.PolicyObservation | None = None,
) -> kit.AssertionContext:
    revision = revision if revision is not None else _revision(registry)
    instant = kit.FIXED_INSTANT
    return kit.AssertionContext(
        registry=registry,
        descriptor=DESCRIPTOR,
        connector=_row(),
        revision=revision,
        policy=policy if policy is not None else _known(),
        clock_instant=instant,
        run_window=(instant - timedelta(hours=1), instant - timedelta(minutes=59)),
    )


def _batch(registry: Registry, revision: base.RevisionInput) -> base.EmissionBatch:
    return FixtureConnector().emit(revision, revision.mapping)


def _span(path: str, text: str | None = None) -> base.SpanRef:
    return base.SpanRef(locator_kind="field", locator={"kind": "field", "field_path": path}, text=text)


def _note_ref(external_id: str = "n1") -> base.NodeRef:
    return base.NodeRef(kind=FIXTURE_NOTE_KIND, key={"note_id": external_id})


# --------------------------------------------------------------------------- case directories


def _page(*changes, partition=PARTITION, complete=True, next_cursor=None) -> dict:
    return {
        "partition": partition,
        "changes": [
            {"ref": _ref(external_id).model_dump(mode="json"), "operation": operation}
            for external_id, operation in changes
        ],
        "next_cursor": next_cursor,
        "complete": complete,
        "warnings": [],
    }


def _write_case(root: Path, name: str = "basic", **overrides) -> Path:
    """A case in the documented layout, with any file replaced (`None` removes it)."""
    directory = root / "fixtures" / name
    (directory / "inputs").mkdir(parents=True, exist_ok=True)
    files = {
        "config.json": {"instance_url": kit.KIT_INSTANCE_URL, "partition": PARTITION},
        "changes.json": {"pages": [_page(("n1", "upsert"), ("n2", "upsert"))]},
        "policies.json": {"n1": {"state": "known", "mode": "workspace"}},
    }
    inputs = overrides.pop("inputs", {"n1": json.dumps(NOTE).encode(), "n2": b'{"id": "n2"}'})
    files.update(overrides)
    for filename, payload in files.items():
        if payload is None:
            continue
        (directory / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for external_id, data in inputs.items():
        (directory / "inputs" / external_id).write_bytes(data)
    return directory


def _copied_case(case, tmp_path: Path):
    """A writable copy of a case, so `--update-golden` never writes into the repository."""
    target = tmp_path / "fixtures" / case.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(case.root, target)
    return kit.load_case(target)


def _copied_package(tmp_path: Path, *, derivation=None, connector_kinds=None, verb_phrase=None) -> Path:
    """A writable copy of the fixture connector package, imported by file location."""
    target = tmp_path / "copied_connector"
    shutil.copytree(PACKAGE_DIR, target)
    if derivation is None and connector_kinds is None and verb_phrase is None:
        return target
    updates = []
    if derivation is not None:
        updates.append(f'"capabilities": _D.capabilities.model_copy(update={{"derivation": {derivation!r}}})')
    if connector_kinds is not None:
        updates.append(f'"extension": fixture_extension(connector_kinds={connector_kinds!r})')
    if verb_phrase is not None:
        # One vocabulary change under the same descriptor version: what a developer who edits
        # `types.py` and reruns `--update-golden` has, and what makes the committed lock stale.
        updates.append(
            '"extension": fixture_extension('
            f"predicates=(fixture_links_predicate(verb_phrase={verb_phrase!r}),))"
        )
    (target / "kit_patch.py").write_text(
        "from .connector import DESCRIPTOR as _D, FixtureConnector as _Base\n"
        "from .types import fixture_extension, fixture_links_predicate\n\n"
        f"PATCHED = _D.model_copy(update={{{', '.join(updates)}}})\n\n\n"
        "class Connector(_Base):\n"
        "    def __init__(self, *args, **kwargs):\n"
        "        super().__init__(*args, **kwargs)\n"
        "        self.descriptor = PATCHED\n",
        encoding="utf-8",
    )
    init = target / "__init__.py"
    init.write_text(
        init.read_text(encoding="utf-8") + "\nfrom .kit_patch import Connector as Connector  # noqa: E402\n",
        encoding="utf-8",
    )
    return target


def _add_a_malformed_record(package: Path, external_id: str = "n3") -> None:
    """One more upsert whose note carries no `body`, so `emit` counts a `ParseFailure`.

    The shape S4b's scaffolded case has by design: a change in the page, a policy of its own, and
    input bytes the connector can fetch but not parse.
    """
    case = package / "fixtures" / "basic"
    note = {"id": external_id, "title": "Third note", "url": f"https://fixture.example/notes/{external_id}"}
    (case / "inputs" / external_id).write_bytes(json.dumps(note).encode("utf-8"))
    changes = json.loads((case / "changes.json").read_text(encoding="utf-8"))
    changes["pages"][0]["changes"].append(
        {
            "ref": {"partition": PARTITION, "artifact_kind": "document", "external_id": external_id},
            "operation": "upsert",
        }
    )
    (case / "changes.json").write_text(json.dumps(changes, indent=2), encoding="utf-8")
    policies = json.loads((case / "policies.json").read_text(encoding="utf-8"))
    policies[external_id] = {"state": "known", "mode": "workspace"}
    (case / "policies.json").write_text(json.dumps(policies, indent=2), encoding="utf-8")


# =========================================================================== the negative table


def _fires(call) -> tuple[ContractViolation, ...]:
    """Run a negative fixture and collect the violations it produced."""
    try:
        result = call()
    except ContractViolation as violation:
        return (violation,)
    return tuple(result or ())


# --- contract negatives ------------------------------------------------------


def _one_bad_node(bench: Bench, build) -> tuple[ContractViolation, ...]:
    revision = _revision(bench.registry)
    batch = _batch(bench.registry, revision)
    broken = _replace(batch, nodes=(build(batch.nodes[0]),))
    return kit.check_contract(broken, _context(bench.registry, revision=revision))


def _one_bad_edge(bench: Bench, build) -> tuple[ContractViolation, ...]:
    revision = _revision(bench.registry)
    batch = _batch(bench.registry, revision)
    broken = _replace(batch, edges=(build(batch.edges[0]),))
    return kit.check_contract(broken, _context(bench.registry, revision=revision))


def _unregistered_vocabulary(bench: Bench) -> tuple[ContractViolation, ...]:
    return _one_bad_node(bench, lambda node: _replace(node, ref=_replace(node.ref, kind="fixture_ghost")))


def _node_without_span(bench: Bench) -> tuple[ContractViolation, ...]:
    return _one_bad_node(bench, lambda node: _replace(node, span=None))


def _unknown_policy_with_a_mode(bench: Bench) -> tuple[ContractViolation, ...]:
    revision = _revision(bench.registry)
    unknown = base.PolicyObservation.model_construct(
        ref=_ref(),
        state="unknown",
        mode=None,
        allow_users=("provider-user",),
        allow_groups=(),
        deny_users=(),
        deny_groups=(),
    )
    return kit.check_contract(
        _batch(bench.registry, revision),
        _context(bench.registry, revision=revision, policy=unknown),
    )


def _edge_without_an_evidence_row(bench: Bench) -> tuple[ContractViolation, ...]:
    return _one_bad_edge(bench, lambda edge: _replace(edge, source="similarity", metadata_origin=None))


def _alias_without_a_rule(bench: Bench) -> tuple[ContractViolation, ...]:
    revision = _revision(bench.registry)
    batch = _batch(bench.registry, revision)
    alias = base.AliasEmission.model_construct(
        a=_note_ref("n1"),
        b=_note_ref("n2"),
        rule="",
        support=(base.SupportEmission(spans=(_span("title", NOTE["title"]),)),),
    )
    return kit.check_contract(_replace(batch, aliases=(alias,)), _context(bench.registry, revision=revision))


def _node_stamped_with_the_clock(bench: Bench) -> tuple[ContractViolation, ...]:
    return _one_bad_node(
        bench,
        lambda node: _replace(node, ts=kit.FIXED_INSTANT, ts_original=kit.FIXED_INSTANT.isoformat()),
    )


def _unit_outside_its_text(bench: Bench) -> tuple[ContractViolation, ...]:
    revision = _revision(bench.registry)
    batch = _batch(bench.registry, revision)
    unit = _replace(batch.units[0], start=0, end=10_000)
    return kit.check_contract(_replace(batch, units=(unit,)), _context(bench.registry, revision=revision))


def _span_that_is_not_the_bytes(bench: Bench) -> tuple[ContractViolation, ...]:
    return _one_bad_node(
        bench, lambda node: _replace(node, span=_span("title", "a title this note never had"))
    )


def _passage_over_the_bound(bench: Bench) -> tuple[ContractViolation, ...]:
    body = "word " * kit.TOKEN_BOUND
    payload = json.dumps(dict(NOTE, body=body, links=[], same_as=[]), sort_keys=True).encode("utf-8")
    revision = _revision(bench.registry, data=payload)
    return kit.check_contract(_batch(bench.registry, revision), _context(bench.registry, revision=revision))


def _key_part_the_kind_never_declared(bench: Bench) -> tuple[ContractViolation, ...]:
    return _one_bad_node(
        bench,
        lambda node: _replace(
            node, ref=base.NodeRef.model_construct(kind=FIXTURE_NOTE_KIND, key={"wrong_part": "n1"})
        ),
    )


def _edge_pointing_the_wrong_way(bench: Bench) -> tuple[ContractViolation, ...]:
    """A registered predicate whose declared endpoints are not this connector's kinds."""
    return _one_bad_edge(bench, lambda edge: _replace(edge, predicate="DEPENDS_ON"))


def _silent_parse_failure(bench: Bench) -> tuple[ContractViolation, ...]:
    revision = _revision(bench.registry, data=b'{"id": "n1", "title": "no body"}')
    return kit.check_contract(base.EmissionBatch(), _context(bench.registry, revision=revision))


# --- purity negatives --------------------------------------------------------


class _Wobbly(FixtureConnector):
    """An `emit` whose second call answers differently."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def emit(self, revision, mapping):
        self.calls += 1
        batch = super().emit(revision, mapping)
        return batch if self.calls == 1 else _replace(batch, edges=())


class _Impure(FixtureConnector):
    """An `emit` that reads the clock."""

    def emit(self, revision, mapping):
        time.time()
        return super().emit(revision, mapping)


def _emit_is_not_deterministic(bench: Bench) -> tuple[ContractViolation, ...]:
    revision = _revision(bench.registry)
    return _fires(lambda: kit.assert_emit_pure(_Wobbly(), revision, revision.mapping))


def _emit_reads_the_clock(bench: Bench) -> tuple[ContractViolation, ...]:
    revision = _revision(bench.registry)
    return _fires(lambda: kit.assert_emit_pure(_Impure(), revision, revision.mapping))


# --- capture negatives -------------------------------------------------------


class _SampleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str = PARTITION


class _Sample:
    """The smallest `SyncConnector` the capture rules can be pointed at."""

    descriptor = DESCRIPTOR

    def probe(self, config, clock):
        return base.Classification(
            connector=DESCRIPTOR.name,
            connector_version=DESCRIPTOR.version,
            registry_fingerprint="fixture",
            partitions=(
                base.PartitionClassification(
                    partition=PARTITION,
                    family=FIXTURE_FAMILY,
                    mapping=_mapping(),
                    capabilities=DESCRIPTOR.capabilities,
                    sample_count=1,
                    counts={"note": 1},
                ),
            ),
        )

    def list_changes(self, config, cursor):
        if cursor is not None:
            return base.ChangePage(partition=PARTITION, changes=(), next_cursor=None, complete=True)
        return base.ChangePage(
            partition=PARTITION,
            changes=(base.Change(ref=_ref("n1"), operation="upsert"),),
            next_cursor=base.SyncCursor(partition=PARTITION, value=json.dumps({"page": 1})),
            complete=False,
        )

    def fetch(self, config, ref):
        return _fetch(json.dumps(NOTE, sort_keys=True).encode("utf-8"), external_id=ref.external_id)

    def fetch_policy(self, config, ref):
        return base.PolicyObservation(ref=ref, state="known", mode="workspace")


def _page_that_mixes_partitions(bench: Bench) -> tuple[ContractViolation, ...]:
    class Mixed(_Sample):
        def list_changes(self, config, cursor):
            other = base.ExternalRef(partition="other", artifact_kind="document", external_id="x1")
            return base.ChangePage.model_construct(
                partition=PARTITION,
                # A policy change, so the one rule under test is the page's own partition rule.
                changes=(base.Change(ref=other, operation="policy_change"),),
                next_cursor=None,
                complete=True,
                warnings=(),
            )

    return kit.check_capture(Mixed(), _SampleConfig(), sample=2)


def _fetch_that_answers_another_ref(bench: Bench) -> tuple[ContractViolation, ...]:
    class Crossed(_Sample):
        def fetch(self, config, ref):
            return _fetch(b'{"id": "n9"}', external_id="n9")

    return kit.check_capture(Crossed(), _SampleConfig(), sample=2)


def _canonical_uri_carrying_a_token(bench: Bench) -> tuple[ContractViolation, ...]:
    class Leaky(_Sample):
        def fetch(self, config, ref):
            return _fetch(
                b'{"id": "n1"}',
                external_id=ref.external_id,
                canonical_uri=f"{kit.KIT_INSTANCE_URL}/notes/{ref.external_id}?token=hunter2",
            )

    return kit.check_capture(Leaky(), _SampleConfig(), sample=2)


def _unknown_policy_with_principals(bench: Bench) -> tuple[ContractViolation, ...]:
    class Chatty(_Sample):
        def fetch_policy(self, config, ref):
            return base.PolicyObservation.model_construct(
                ref=ref,
                state="unknown",
                mode=None,
                allow_users=("u1",),
                allow_groups=(),
                deny_users=(),
                deny_groups=(),
            )

    return kit.check_capture(Chatty(), _SampleConfig(), sample=2)


def _probe_that_reads_the_clock(bench: Bench) -> tuple[ContractViolation, ...]:
    class Stamped(_Sample):
        def probe(self, config, clock):
            classification = super().probe(config, clock)
            partition = classification.partitions[0].model_copy(
                update={"warnings": (f"sampled_{int(clock().timestamp())}",)}
            )
            return classification.model_copy(update={"partitions": (partition,)})

    return kit.check_capture(Stamped(), _SampleConfig(), sample=2)


# --- runtime negatives -------------------------------------------------------


def _runtime_negative(bench: Bench, scenario: str, double) -> tuple[ContractViolation, ...]:
    """Install a `scratch_sync` double that breaks this scenario's invariant, then run it."""
    bench.monkeypatch.setattr(kit, "scratch_sync", double(kit.scratch_sync))
    return _fires(lambda: kit.assert_runtime_resilience(bench.connector, bench.case, scenarios=(scenario,)))


def _artifacts(workspace):
    return list(workspace.ctx.store._knowledge_rows("Artifact"))


def _crash_after_fetch_commits_the_checkpoint(bench: Bench) -> tuple[ContractViolation, ...]:
    def double(real):
        def moved(workspace, connector, **kwargs):
            hook = kwargs.get("fault_hook")
            if hook is not None:
                kwargs["fault_hook"] = lambda label: (
                    hook("after_fetch") if label == "after_checkpoint" else None
                )
            return real(workspace, connector, **kwargs)

        return moved

    return _runtime_negative(bench, "crash_after_fetch", double)


def _replay_that_moves_the_epoch(bench: Bench) -> tuple[ContractViolation, ...]:
    def double(real):
        def refreshing(workspace, connector, **kwargs):
            store = workspace.ctx.store
            for policy in list(store._knowledge_rows("AccessPolicy")):
                store.put_knowledge(policy.model_copy(update={"verified_at": store._now()}), closure=True)
            return real(workspace, connector, **kwargs)

        return refreshing

    return _runtime_negative(bench, "replayed_page", double)


def _failed_inventory_that_deletes(bench: Bench) -> tuple[ContractViolation, ...]:
    def double(real):
        def deleting(workspace, connector, **kwargs):
            try:
                return real(workspace, connector, **kwargs)
            except Exception:
                for artifact in _artifacts(workspace):
                    workspace.ctx.store.put_knowledge(
                        artifact.model_copy(update={"deleted_at": workspace.ctx.store._now()}),
                        closure=True,
                    )
                raise

        return deleting

    return _runtime_negative(bench, "failed_inventory", double)


def _policy_change_that_is_rolled_back(bench: Bench) -> tuple[ContractViolation, ...]:
    def double(real):
        def restoring(workspace, connector, **kwargs):
            before = {row.id: row.policy_id for row in _artifacts(workspace)}
            try:
                return real(workspace, connector, **kwargs)
            except Exception:
                for artifact in _artifacts(workspace):
                    if before.get(artifact.id) not in (None, artifact.policy_id):
                        workspace.ctx.store.put_knowledge(
                            artifact.model_copy(update={"policy_id": before[artifact.id]}), closure=True
                        )
                raise

        return restoring

    return _runtime_negative(bench, "policy_change_mid_page", double)


def _delete_that_is_undone(bench: Bench) -> tuple[ContractViolation, ...]:
    def double(real):
        def clearing(workspace, connector, **kwargs):
            try:
                return real(workspace, connector, **kwargs)
            except Exception:
                for artifact in _artifacts(workspace):
                    if artifact.deleted_at is not None:
                        workspace.ctx.store.put_knowledge(
                            artifact.model_copy(update={"deleted_at": None}), closure=True
                        )
                raise

        return clearing

    return _runtime_negative(bench, "delete_with_live_session", double)


# --- registry negative -------------------------------------------------------


def _moved_template(*, version: str) -> Any:
    return fixture_extension(
        object_kinds=(
            fixture_note_kind(
                fact_templates=(
                    FactTemplate(
                        name="note_summary",
                        version=version,
                        consumes=("title", "updated"),
                        text="Note {key} is titled {title}",
                    ),
                )
            ),
        )
    )


def _template_changed_without_a_bump(bench: Bench) -> tuple[ContractViolation, ...]:
    lock_path = bench.tmp_path / "registry.lock.json"
    lock_path.write_text(
        canonical_json(kit.extension_lock(DESCRIPTOR.extension, version=DESCRIPTOR.version)),
        encoding="utf-8",
    )
    return _fires(
        lambda: kit.assert_registry_lock(
            _moved_template(version="1"), version=DESCRIPTOR.version, lock_path=lock_path
        )
    )


VIOLATIONS: dict[str, Any] = {
    "registered_vocabulary": _unregistered_vocabulary,
    "nodes_have_locator_and_policy": _node_without_span,
    "unknown_policy_is_deny": _unknown_policy_with_a_mode,
    "edges_fully_attributed": _edge_without_an_evidence_row,
    "aliases_name_a_rule": _alias_without_a_rule,
    "no_ingestion_time": _node_stamped_with_the_clock,
    "one_fact_per_unit": _unit_outside_its_text,
    "spans_match_bytes": _span_that_is_not_the_bytes,
    "passages_within_token_bound": _passage_over_the_bound,
    "identities_from_builders": _key_part_the_kind_never_declared,
    "direction_and_ownership": _edge_pointing_the_wrong_way,
    "parse_failures_counted": _silent_parse_failure,
    "emit_deterministic": _emit_is_not_deterministic,
    "emit_pure": _emit_reads_the_clock,
    "change_page_single_partition": _page_that_mixes_partitions,
    "fetch_matches_ref": _fetch_that_answers_another_ref,
    "canonical_uri_without_credentials": _canonical_uri_carrying_a_token,
    "unknown_policy_carries_no_principals": _unknown_policy_with_principals,
    "probe_deterministic": _probe_that_reads_the_clock,
    "crash_after_fetch": _crash_after_fetch_commits_the_checkpoint,
    "replayed_page": _replay_that_moves_the_epoch,
    "failed_inventory": _failed_inventory_that_deletes,
    "policy_change_mid_page": _policy_change_that_is_rolled_back,
    "delete_with_live_session": _delete_that_is_undone,
    "registry_version_bump": _template_changed_without_a_bump,
}


# =========================================================================== completeness


def test_every_assertion_has_exactly_one_negative_fixture():
    assert set(VIOLATIONS) == set(kit.ASSERTIONS)
    assert len(kit.ASSERTIONS) == len(set(kit.ASSERTIONS)) == len(VIOLATIONS)


@pytest.mark.parametrize("assertion", kit.ASSERTIONS)
def test_a_negative_fixture_fires_its_own_assertion(assertion, bench):
    with use_registry(bench.registry):
        fired = VIOLATIONS[assertion](bench)
    assert assertion in {violation.assertion for violation in fired}, [v.message for v in fired]


@pytest.mark.parametrize("assertion", kit.CONTRACT_ASSERTIONS + kit.CAPTURE_ASSERTIONS)
def test_a_negative_fixture_fires_no_other_assertion_of_its_group(assertion, bench):
    with use_registry(bench.registry):
        fired = VIOLATIONS[assertion](bench)
    assert {violation.assertion for violation in fired} == {assertion}


def test_the_fixture_connector_passes_every_assertion(connector, case, registry):
    """The positive fixture (R10, R-S3-7): S3's connector and its `fixtures/basic` case."""
    with use_registry(registry):
        revision = _revision(registry)
        batch = kit.assert_emit_pure(connector, revision, revision.mapping)
        assert kit.check_contract(batch, _context(registry, revision=revision)) == ()
        replay = kit._replay_connector(connector, case)
        assert kit.check_capture(replay, _config(), sample=10) == ()
        kit.assert_registry_lock(DESCRIPTOR.extension, version=DESCRIPTOR.version, lock_path=LOCK_PATH)
    kit.assert_runtime_resilience(connector, case)
    # The committed `expected/` tree, read without `update_golden`: this is what fails when S2b's
    # binder, S3c's runtime or the fixture connector's `emit` changes what a case publishes.
    result = kit.run_case(connector, case)
    assert result.passed, (result.error, result.diff[:800])


def test_assert_contract_raises_the_first_violation_in_assertion_order(bench):
    """Deviation 2: `assert_contract` raises the first, in `CONTRACT_ASSERTIONS` order."""
    registry = bench.registry
    with use_registry(registry):
        revision = _revision(registry)
        batch = _batch(registry, revision)
        broken = _replace(
            batch,
            nodes=(_replace(batch.nodes[0], span=_span("title", "never written")),),
            aliases=(
                base.AliasEmission.model_construct(
                    a=_note_ref("n1"),
                    b=_note_ref("n2"),
                    rule="",
                    support=(base.SupportEmission(spans=(_span("title", NOTE["title"]),)),),
                ),
            ),
        )
        context = _context(registry, revision=revision)
        fired = kit.check_contract(broken, context)
        assert len(fired) > 1, "the fixture must break more than one rule for order to be observable"
        with pytest.raises(ContractViolation) as caught:
            kit.assert_contract(broken, registry, context)
    order = list(kit.CONTRACT_ASSERTIONS)
    assert caught.value.assertion == min((v.assertion for v in fired), key=order.index)


# =========================================================================== constants and seams


def test_token_bound_is_the_passage_character_bound():
    """m6 / R42: the kit reads the constant, never the number."""
    assert kit.TOKEN_BOUND == base.PASSAGE_CHAR_BOUND == 6000


def test_the_purity_guard_is_the_runtime_guard():
    """B3 / R49: one guard, S3's per-thread `forbid_effects`."""
    assert kit.purity_guard is guard.forbid_effects


def test_the_kit_re_exports_the_runtime_transports():
    """B4 / R49: one recording format, S3's."""
    assert kit.record_transport is http.record_transport
    assert kit.replay_transport is http.replay_transport
    assert kit.ERROR_CLASSES is http.ERROR_CLASSES


def test_assert_emit_pure_leaves_other_threads_alone(registry):
    """B3: the guard is per thread, so S6's route can validate inside a running server."""
    stop = threading.Event()
    failures: list[BaseException] = []
    started = threading.Event()

    def worker():
        client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
        try:
            while not stop.is_set():
                time.monotonic()
                client.get("http://neighbour.invalid/ping")
                started.set()
        except BaseException as error:  # pragma: no cover - the failure is the assertion
            failures.append(error)
        finally:
            client.close()

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        started.wait(timeout=5)
        with use_registry(registry):
            revision = _revision(registry)
            kit.assert_emit_pure(FixtureConnector(), revision, revision.mapping)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert failures == []


@pytest.mark.parametrize("error_class", http.ERROR_CLASSES)
def test_each_error_class_has_a_replayable_response(error_class):
    client = http.ProviderClient(
        kit.KIT_INSTANCE_URL,
        limits=http.HttpLimits(max_attempts=1, max_total_seconds=5.0),
        transport=kit.error_transport(error_class),
        sleep=lambda _seconds: None,
    )
    with pytest.raises(ERROR_TYPES[error_class]):
        client.get_json("anything")


# =========================================================================== the fixture layout


def test_load_case_reads_the_documented_layout(tmp_path):
    directory = _write_case(tmp_path)
    case = kit.load_case(directory)
    assert case.name == "basic"
    assert case.partition == PARTITION
    assert [change.ref.external_id for page in case.pages for change in page.changes] == ["n1", "n2"]
    assert set(case.inputs) == {"n1", "n2"}
    assert case.policies["n1"].state == "known"
    assert isinstance(case.pages[0], base.ChangePage)


def test_load_case_refuses_a_bad_case_name_an_unknown_file_a_missing_upsert_input_an_unquoted_name_and_two_partitions(
    tmp_path,
):
    bad_name = _write_case(tmp_path / "a", name="Not A Case")
    with pytest.raises(ValueError, match="Not A Case"):
        kit.load_case(bad_name)

    stray = _write_case(tmp_path / "b")
    (stray / "notes.txt").write_text("stray", encoding="utf-8")
    with pytest.raises(ValueError, match="notes.txt"):
        kit.load_case(stray)

    missing_input = _write_case(tmp_path / "c", inputs={"n1": b"{}"})
    with pytest.raises(ValueError, match="n2"):
        kit.load_case(missing_input)

    unquoted = _write_case(tmp_path / "d")
    (unquoted / "inputs" / "a b").write_bytes(b"{}")
    with pytest.raises(ValueError, match="a b"):
        kit.load_case(unquoted)

    two = _write_case(
        tmp_path / "e",
        **{
            "changes.json": {
                "pages": [
                    _page(("n1", "upsert"), complete=False),
                    _page(partition="other"),
                ]
            }
        },
    )
    with pytest.raises(ValueError, match="partition"):
        kit.load_case(two)

    no_config = _write_case(tmp_path / "f", **{"config.json": None})
    with pytest.raises(ValueError, match="config.json"):
        kit.load_case(no_config)


def test_load_case_refuses_a_fetches_entry_with_an_unknown_field_or_a_half_timestamp(tmp_path):
    """The plan's `fetches` field rule, plus N10's pair rule."""
    for name, fetches, message in (
        ("a", {"n1": {"invented": "x"}}, "invented"),
        ("b", {"n1": {"source_updated_at": "2026-01-01T00:00:00Z"}}, "original spelling"),
    ):
        directory = _write_case(tmp_path / name)
        payload = json.loads((directory / "changes.json").read_text(encoding="utf-8"))
        (directory / "changes.json").write_text(json.dumps(payload | {"fetches": fetches}), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            kit.load_case(directory)


def test_a_missing_policy_replays_as_unknown(tmp_path, connector):
    directory = _write_case(tmp_path)
    case = kit.load_case(directory)
    replay = kit._replay_connector(connector, case)
    observed = replay.fetch_policy(_config(), _ref("n2"))
    assert observed.state == "unknown"
    assert observed.ref == _ref("n2")


def test_the_replay_raises_provider_not_found_for_an_id_without_input(tmp_path, connector):
    """M15: a deletion is only inferred after the provider confirms the absence."""
    case = kit.load_case(_write_case(tmp_path))
    replay = kit._replay_connector(connector, case)
    with pytest.raises(http.ProviderNotFoundError):
        replay.fetch(_config(), _ref("n404"))


def test_the_replay_connector_keeps_the_real_probe_and_emit_and_replays_the_sync_half(
    case, connector, registry
):
    """B4: `probe` samples through the overridden methods, so it reads the case."""
    replay = kit._replay_connector(connector, case)
    assert isinstance(replay, FixtureConnector)
    assert replay.emit.__func__ is FixtureConnector.emit
    assert replay.probe.__func__ is FixtureConnector.probe
    with use_registry(registry):
        classification = replay.probe(_config(), lambda: kit.FIXED_INSTANT)
    assert classification.partitions[0].partition == case.partition
    assert connector.provider.requests == [], "the replay must not reach the real provider"


def test_discover_cases_lists_the_package_fixture_directories(tmp_path):
    _write_case(tmp_path, name="basic")
    _write_case(tmp_path, name="second")
    (tmp_path / "fixtures" / "registry.lock.json").write_text("{}", encoding="utf-8")
    assert [path.name for path in kit.discover_cases(tmp_path)] == ["basic", "second"]


# =========================================================================== run_case


@contextmanager
def _watching(monkeypatch, seen: list):
    real = kit.scratch_workspace

    @contextmanager
    def watching(**kwargs):
        with real(**kwargs) as workspace:
            seen.append(workspace)
            yield workspace

    monkeypatch.setattr(kit, "scratch_workspace", watching)
    yield


def test_run_case_creates_an_enabled_instance_stores_the_probe_and_calls_sync_connector_with_its_full_signature(
    monkeypatch, connector, case
):
    """B4 / M5: R49's entry, with `connector_id`, the trusted actor and one emit worker."""
    from hippo.connectors import sync
    from hippo.knowledge.registry import current_registry

    seen: dict[str, Any] = {}
    real = sync.sync_connector

    def spy(ctx, impl, **kwargs):
        seen.update(kwargs)
        seen["registry_is_current"] = kwargs["registry"] is current_registry()
        row = ctx.store._knowledge_get("Connector", kwargs["connector_id"])
        seen["enabled"] = row.enabled
        seen["classification"] = row.classification_json
        return real(ctx, impl, **kwargs)

    monkeypatch.setattr(sync, "sync_connector", spy)
    result = kit.run_case(connector, case)

    assert result.error is None, result.error
    assert seen["enabled"] is True
    assert seen["classification"] not in (None, "", "{}")
    assert seen["actor"].kind == "trusted_local"
    assert seen["registry_is_current"] is True
    assert seen["options"].emit_workers == 1
    assert seen["operation_id"] == "validate.basic"
    assert seen["partition"] == case.partition


def test_run_case_pins_the_store_clock_to_the_fixed_instant(connector, case, monkeypatch):
    seen: list = []
    with _watching(monkeypatch, seen):
        kit.run_case(connector, case)
    assert seen and all(workspace.ctx.store._now() == kit.FIXED_INSTANT for workspace in seen)


def test_run_case_records_a_sync_refusal_as_the_case_error(connector, case, monkeypatch):
    """B4: a refusal names its rule and becomes the case's error, never a traceback."""
    from hippo.connectors import sync

    def refusing(*args, **kwargs):
        raise sync.ConnectorSyncRefused("Connector instance is not enabled")

    monkeypatch.setattr(sync, "sync_connector", refusing)
    result = kit.run_case(connector, case)
    assert result.passed is False
    assert "ConnectorSyncRefused" in (result.error or "")
    assert result.generation_id is None


def test_run_case_diffs_published_records_against_the_goldens(connector, case, tmp_path):
    copy = _copied_case(case, tmp_path)
    first = kit.run_case(connector, copy, update_golden=True)
    assert first.error is None, first.error
    assert first.generation_id
    second = kit.run_case(connector, kit.load_case(copy.root))
    assert second.diff == ""
    assert second.passed is True


def test_update_golden_rewrites_the_seven_files_and_returns_the_diff(connector, case, tmp_path):
    copy = _copied_case(case, tmp_path)
    kit.run_case(connector, copy, update_golden=True)
    assert sorted(path.name for path in (copy.root / "expected").iterdir()) == sorted(kit.GOLDEN_FILES)
    (copy.root / "expected" / "nodes.json").write_text("[]", encoding="utf-8")
    again = kit.run_case(connector, kit.load_case(copy.root), update_golden=True)
    assert "nodes.json" in again.diff


def test_goldens_are_canonical_json_sorted_by_id_without_job_or_event_payload(connector, case, tmp_path):
    copy = _copied_case(case, tmp_path)
    kit.run_case(connector, copy, update_golden=True)
    for name in kit.GOLDEN_FILES:
        text = (copy.root / "expected" / name).read_text(encoding="utf-8")
        payload = json.loads(text)
        assert text == canonical_json(payload)
        if isinstance(payload, list) and payload and "id" in payload[0]:
            assert [row["id"] for row in payload] == sorted(row["id"] for row in payload)
        assert "MaintenanceJob" not in text and "lease_owner" not in text


def test_dry_run_sync_publishes_into_a_scratch_workspace_only(connector, tmp_path, monkeypatch):
    """B4: a dry run touches no configured store and leaves nothing behind."""
    seen: list = []
    with _watching(monkeypatch, seen):
        receipts = kit.dry_run_sync(connector, _config(), partition=PARTITION)
    assert receipts and all(receipt.partition == PARTITION for receipt in receipts)
    assert seen and not any(workspace.root.exists() for workspace in seen)


# =========================================================================== capture and purity


def test_check_capture_bounds_its_reads_by_sample():
    """M12: `sample` bounds the pages listed and the changes fetched."""

    class Counting(_Sample):
        def __init__(self) -> None:
            self.pages = 0
            self.fetches = 0

        def list_changes(self, config, cursor):
            self.pages += 1
            page = self.pages
            return base.ChangePage(
                partition=PARTITION,
                changes=(base.Change(ref=_ref(f"n{page}"), operation="upsert"),),
                next_cursor=base.SyncCursor(partition=PARTITION, value=json.dumps({"page": page})),
                complete=False,
            )

        def fetch(self, config, ref):
            self.fetches += 1
            return _fetch(json.dumps(NOTE, sort_keys=True).encode("utf-8"), external_id=ref.external_id)

    counting = Counting()
    assert kit.check_capture(counting, _SampleConfig(), sample=2) == ()
    assert counting.pages <= 2
    assert counting.fetches <= 2


def test_check_capture_accepts_a_sync_connector_without_emit():
    """M12 / R1: a coordinator-lane connector is a `SyncConnector` and nothing more."""
    sample = _Sample()
    assert not hasattr(sample, "emit")
    assert isinstance(sample, base.SyncConnector)
    assert kit.check_capture(sample, _SampleConfig(), sample=2) == ()


# =========================================================================== runtime scenarios


@pytest.mark.parametrize("scenario", kit.RUNTIME_SCENARIOS)
def test_runtime_resilience_holds_for_the_fixture_connector(scenario, connector, case):
    """B4: S3 section 9's five boundaries, on replay variants of the case."""
    kit.assert_runtime_resilience(connector, case, scenarios=(scenario,))


# =========================================================================== the registry lock


def test_the_registry_lock_accepts_a_bumped_template_version(tmp_path):
    lock_path = tmp_path / "registry.lock.json"
    lock_path.write_text(
        canonical_json(kit.extension_lock(DESCRIPTOR.extension, version=DESCRIPTOR.version)),
        encoding="utf-8",
    )
    kit.assert_registry_lock(_moved_template(version="2"), version=DESCRIPTOR.version, lock_path=lock_path)


def test_the_lock_keys_name_kinds_predicates_and_templates():
    lock = kit.extension_lock(DESCRIPTOR.extension, version=DESCRIPTOR.version)
    assert f"kind:{FIXTURE_NOTE_KIND}@{DESCRIPTOR.version}" in lock
    assert f"predicate:{FIXTURE_LINKS}@{DESCRIPTOR.version}" in lock
    assert f"template:{FIXTURE_NOTE_KIND}/note_summary@1" in lock


# =========================================================================== the offline model


def test_the_offline_model_embeds_deterministically_and_refuses_chat():
    ollama = kit.offline_ollama()
    first = ollama.embed_one("ACME builds Robot.")
    second = ollama.embed_one("ACME builds Robot.")
    assert np.allclose(first, second)
    assert len(first) == kit.EMBEDDING_DIM
    with pytest.raises(OllamaError):
        ollama.chat_text([{"role": "user", "content": "write me some prose"}])


def test_the_fake_ollama_embeds_with_the_kit_algorithm():
    """m17: the algorithm moved into the kit; the fake's vectors are byte-identical."""
    vector = fake_ollama.embed_text("ACME builds Robot.")
    assert (
        hashlib.sha256(vector.tobytes()).hexdigest()
        == "db6b9cdc99c6fa294a2c150dea0958df2d8ce940d7d6d9f274c924c12a852290"
    )
    assert np.array_equal(vector, kit.hashed_embedding("ACME builds Robot."))
    assert fake_ollama.DIM == kit.EMBEDDING_DIM


# =========================================================================== validate_package


def test_validate_package_reports_the_registry_diff(tmp_path):
    report = kit.validate_package(_copied_package(tmp_path), runtime=False)
    assert report.error is None, report.error
    assert f"+ kind {FIXTURE_NOTE_KIND}" in report.registry_diff
    assert f"+ predicate {FIXTURE_LINKS}" in report.registry_diff
    assert f"+ connector kind {DESCRIPTOR.name}" in report.registry_diff
    assert report.scope == "contract"


def test_validate_package_contract_scope_runs_no_sync(tmp_path, monkeypatch):
    from hippo.connectors import sync

    def refusing(*args, **kwargs):  # pragma: no cover - the assertion is that it never runs
        raise AssertionError("contract scope must not sync")

    monkeypatch.setattr(sync, "sync_connector", refusing)
    report = kit.validate_package(_copied_package(tmp_path), runtime=False)
    assert report.passed is True, [v.message for v in report.violations]
    assert report.to_json()["scope"] == "contract"


def test_validate_package_of_a_coordinator_lane_connector_runs_capture_only(tmp_path):
    """R1: a lane connector has no `emit`, so only the capture rules apply."""
    package = _copied_package(tmp_path, derivation="coordinator_lane")
    report = kit.validate_package(package, runtime=False)
    assert report.scope == "capture"
    assert report.passed is True, [v.message for v in report.violations]


def test_validate_package_names_a_connector_whose_extension_omits_its_kind(tmp_path):
    """N16: a named rule, not `Unknown connector kind` from `ensure_connector`."""
    package = _copied_package(tmp_path, connector_kinds=())
    report = kit.validate_package(package, runtime=False)
    assert report.passed is False
    assert DESCRIPTOR.name in (report.error or "")


def test_a_malformed_record_fills_failures_json(tmp_path):
    """R77 finding 1: S3c counts a `ParseFailure` under `coverage["emission"]["failures"]`.

    The kit read `coverage["failures"]`, a key S3c never writes, so `failures.json` stayed `[]` for
    a case that exercises a `ParseFailure` (S4b's scaffolded package, whose `record-2` is malformed
    by design) and R75(4)'s "it fills once a fixture exercises one" could not hold.
    """
    package = _copied_package(tmp_path)
    _add_a_malformed_record(package)

    report = kit.validate_package(package, update_golden=True)

    assert report.error is None, report.error
    assert [violation.message for violation in report.violations] == []
    assert [case.error for case in report.cases] == [None]
    expected = package / "fixtures" / "basic" / "expected"
    coverage = json.loads((expected / "coverage.json").read_text(encoding="utf-8"))
    # S3c keys the counter `family|parser|dialect`, writing `-` for a part the failure omits.
    assert coverage["emission"]["failures"] == {f"{FIXTURE_FAMILY}|-|-": 1}
    assert json.loads((expected / "failures.json").read_text(encoding="utf-8")) == [
        {"family": FIXTURE_FAMILY, "parser": None, "count": 1}
    ]


def test_update_golden_rewrites_a_stale_registry_lock(tmp_path):
    """R77 finding 2: a re-goldened package never keeps a lock its vocabulary has moved past.

    `assert_registry_lock` only ever read the lock, so `--update-golden` recomputed the seven
    goldens and left the eighth committed file stale. It is written from `extension_lock` on the
    update run instead of asserted, which is what `render_package` already did for itself.
    """
    moved = fixture_extension(predicates=(fixture_links_predicate(verb_phrase="links onward to"),))
    package = _copied_package(tmp_path, verb_phrase="links onward to")
    lock_path = package / "fixtures" / "registry.lock.json"
    stale = lock_path.read_text(encoding="utf-8")
    with pytest.raises(ContractViolation) as refusal:
        kit.assert_registry_lock(moved, version=DESCRIPTOR.version, lock_path=lock_path)
    assert refusal.value.assertion == "registry_version_bump"
    assert refusal.value.record == f"predicate:{FIXTURE_LINKS}@{DESCRIPTOR.version}"

    report = kit.validate_package(package, update_golden=True)

    assert report.error is None, report.error
    assert [violation.message for violation in report.violations] == []
    rewritten = lock_path.read_text(encoding="utf-8")
    assert rewritten != stale
    assert rewritten == canonical_json(kit.extension_lock(moved, version=DESCRIPTOR.version))
    kit.assert_registry_lock(moved, version=DESCRIPTOR.version, lock_path=lock_path)
