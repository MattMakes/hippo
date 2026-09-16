"""`hippo connector new|list|validate|probe|sync|enable` (CDK S4b).

Plan `ai_docs/plans/cdk-s4-kit.md` section 3.3 and section 5 "S4b", amended by ruling R58
(`cmd_connector` is the slice that calls `load_registry`), R59 and R73 (`hippo connector enable`,
which passes `enabled=True` deliberately on every `ensure_connector` call), R64 (open mode refuses
an enabled non-`local` kind, and `enable` exits 2 with the store's own sentence), M5 (a disabled
instance and a kind that is not enabled are both exit 2) and m19 (the non-dry-run `sync` order).

Three rules hold here:

* **No test client.** Forwarding is proved against `httpx.MockTransport`, so no module here imports
  `fastapi.testclient` or `starlette.testclient` and the GREEN line needs no warning filter.
* **Nothing registers into `REGISTRY`.** Every test runs under `use_registry(Registry.with_builtins())`
  (re-review N1), and the tests that seed `Connector` rows of the fixture kind register that kind in
  an `extension_scope()` first, because the write path checks vocabulary (S4c-fix, R64).
* **The entry point stand-in carries a class-level `descriptor`.** `loader._imported` reads
  `descriptor` off the *class*, and S3c's `FixtureConnector` sets it in `__init__`, so the stand-in
  is a one-line subclass that publishes it. A shipped connector must do the same; the scaffold does.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from hippo import cli
from hippo.connectors import loader, sync
from hippo.connectors import testing as kit
from hippo.context import AppContext
from hippo.knowledge.registry import Registry, TypeExtension, extension_scope, use_registry
from hippo.remote import RemoteError, RemoteHippo
from hippo.store import StoreLockedError
from hippo.store.migrations import DEFAULT_WORKSPACE_ID
from tests.conftest import LADYBUG_TEST_BUFFER_POOL_BYTES, store_backend
from tests.fakes.fake_store import FakeStore
from tests.fakes.fixture_connector import BASIC_CASE, DESCRIPTOR, FixtureConfig, FixtureConnector
from tests.fakes.fixture_connector.types import FIXTURE_FAMILY, fixture_extension

PACKAGE = BASIC_CASE.parent.parent
FIXTURE_KIND = DESCRIPTOR.name
FIXTURE_PARTITION = "notes"


class FixtureEntryPoint(FixtureConnector):
    """`loader._imported` reads `descriptor` off the class; S3c's connector sets it per instance."""

    descriptor = DESCRIPTOR


class _Point:
    """The `importlib.metadata` shape the loader uses: `name`, `value` and `load()`."""

    def __init__(self, name: str, load, value: str = "tests.fakes.fixture_connector:FixtureConnector"):
        self.name, self.value, self._load = name, value, load

    def load(self):
        return self._load()


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def registry():
    """N1: this file registers extensions, and none of them may outlive their test."""
    with use_registry(Registry.with_builtins()) as scoped:
        yield scoped


@pytest.fixture(autouse=True)
def scratch_store(monkeypatch):
    """The kit's scratch store is the backend `HIPPO_TEST_STORE` names (plan section 5)."""
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


@pytest.fixture
def cli_ctx(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> AppContext:
    """Every command builds its context with `AppContext.from_env()`; point that at the fixture."""
    monkeypatch.setattr(AppContext, "from_env", classmethod(lambda cls, ollama=None: ctx))
    ctx.store.ping()
    return ctx


@pytest.fixture
def operator(cli_ctx, monkeypatch: pytest.MonkeyPatch) -> AppContext:
    """A signed-in installation, which an enabled provider connector requires (R64).

    `store/authorization.py` refuses `enabled=True` for any kind but `local` while `count_users()`
    is zero, so every test that seeds or writes an enabled row needs a user — and, once one exists,
    a token, because `_principal` refuses an anonymous caller.
    """
    cli_ctx.store.ensure_roles()
    user_id = cli_ctx.store.create_user("operator", "operator-password", _top_role(cli_ctx), "Operator")
    monkeypatch.setenv("HIPPO_TOKEN", cli_ctx.store.get_user(user_id)["token"])
    return cli_ctx


@pytest.fixture
def entry_point(monkeypatch: pytest.MonkeyPatch):
    """Make the fixture connector discoverable and trusted, as plan section 5 prescribes."""
    monkeypatch.setattr(loader, "_entry_points", lambda: [_Point(FIXTURE_KIND, lambda: FixtureEntryPoint)])
    monkeypatch.setenv(loader.ALLOWLIST_ENV, FIXTURE_KIND)


def _config_file(tmp_path: Path, **overrides) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(json.loads(FixtureConfig(**overrides).model_dump_json())))
    return path


def _seed(store, *, enabled: bool = True, classified: bool = True):
    """One `Connector` row of the fixture kind, written under a throwaway extension (S4c-fix)."""
    with extension_scope() as scoped:
        scoped.register(fixture_extension(), declared_families=(FIXTURE_FAMILY,))
        row = sync.ensure_connector(
            store,
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind=FIXTURE_KIND,
            instance_url=FixtureConfig().instance_url,
            config=FixtureConfig(),
            enabled=enabled,
        )
        if classified:
            connector = FixtureConnector()
            registry = kit.kit_registry(DESCRIPTOR)
            with use_registry(registry):
                classification = connector.probe(FixtureConfig(), lambda: kit.FIXED_INSTANT)
            row = sync.store_classification(store, connector=row, classification=classification)
    return row


def _run(*argv: str) -> int:
    return cli.main(["connector", *argv])


# --------------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("argv", "sub", "extra"),
    [
        (
            ["connector", "new", "incidents"],
            "new",
            {"name": "incidents", "family": None, "kinds": [], "dest": None},
        ),
        (
            ["connector", "new", "incidents", "--family", "incident", "--kinds", "incident", "--dest", "/d"],
            "new",
            {"name": "incidents", "family": "incident", "kinds": ["incident"], "dest": "/d"},
        ),
        (["connector", "list"], "list", {}),
        (["connector", "validate", "./pkg"], "validate", {"target": "./pkg", "update_golden": False}),
        (
            ["connector", "validate", "fixture", "--update-golden"],
            "validate",
            {"target": "fixture", "update_golden": True},
        ),
        (["connector", "probe", "fixture", "--config", "c.json"], "probe", {"name": "fixture"}),
        (
            ["connector", "sync", "fixture", "--config", "c.json", "--dry-run"],
            "sync",
            {"instance": "fixture", "dry_run": True, "partition": None},
        ),
        (
            ["connector", "sync", "connector-1", "--partition", "notes"],
            "sync",
            {"instance": "connector-1", "dry_run": False, "partition": "notes"},
        ),
        (
            ["connector", "enable", "fixture", "https://fixture.example"],
            "enable",
            {"kind": "fixture", "instance_url": "https://fixture.example", "config": None},
        ),
    ],
    ids=[
        "new",
        "new_with_kinds_and_dest",
        "list",
        "validate",
        "validate_update_golden",
        "probe",
        "sync_dry_run",
        "sync_instance",
        "enable",
    ],
)
def test_connector_arguments_parse(argv, sub, extra):
    args = cli.build_parser().parse_args(argv)
    assert args.command == "connector"
    assert args.connector_command == sub
    for key, value in extra.items():
        assert getattr(args, key) == value, key


def test_the_connector_group_requires_a_subcommand():
    with pytest.raises(SystemExit) as exit:
        cli.build_parser().parse_args(["connector"])
    assert exit.value.code == 2


def test_connector_help_imports_no_serving_machinery():
    """The `user` group's rule: every `hippo.connectors` import inside `cmd_connector` is local."""
    program = (
        "import io, sys, contextlib\n"
        "from hippo.cli import main\n"
        "with contextlib.redirect_stdout(io.StringIO()):\n"
        "    try:\n"
        "        main(['connector', '--help'])\n"
        "    except SystemExit:\n"
        "        pass\n"
        "heavy = ('hippo.connectors', 'hippo.ingest', 'hippo.knowledge.public_errors',"
        " 'fastapi', 'starlette')\n"
        "print(','.join(sorted(m for m in sys.modules if m.startswith(heavy))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=180, check=False
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "", result.stdout


# --------------------------------------------------------------------------- list


def test_list_shows_built_in_in_repo_and_entry_point_connectors(operator, entry_point, capsys):
    _seed(operator.store)
    assert _run("list") == 0
    out = capsys.readouterr().out
    assert "built-in" in out and "entry point" in out
    assert FIXTURE_KIND in out and "local" in out
    assert FIXTURE_PARTITION in out, "a classified partition is not shown"


def test_list_shows_an_entry_point_that_fails_to_import_with_its_error(cli_ctx, monkeypatch, capsys):
    def explode():
        raise ImportError("no module named 'acme_sdk'")

    monkeypatch.setattr(loader, "_entry_points", lambda: [_Point("acme", explode)])
    monkeypatch.setenv(loader.ALLOWLIST_ENV, "acme")
    assert _run("list") == 0
    out = capsys.readouterr().out
    assert "acme" in out and "ImportError" in out


def test_list_shows_an_entry_point_missing_from_the_allowlist(cli_ctx, monkeypatch, capsys):
    monkeypatch.setattr(loader, "_entry_points", lambda: [_Point("acme", lambda: FixtureEntryPoint)])
    monkeypatch.delenv(loader.ALLOWLIST_ENV, raising=False)
    assert _run("list") == 0
    assert "not allowlisted" in capsys.readouterr().out


def test_list_requires_manage_sources_when_users_exist(cli_ctx, monkeypatch, capsys):
    cli_ctx.store.ensure_roles()
    reader = _reader(cli_ctx)
    monkeypatch.setenv("HIPPO_TOKEN", reader["token"])
    assert _run("list") == 2
    assert "manage sources" in capsys.readouterr().err


def test_list_forwards_to_the_running_server_when_the_store_is_locked(monkeypatch, capsys):
    payload = [
        {
            "name": "incidents_ndjson",
            "version": "1",
            "families": ["incident"],
            "origin": "in-repo",
            "enabled": True,
            "error": None,
            "instances": [{"id": "connector-1", "enabled": True, "partitions": [{"partition": "export"}]}],
        }
    ]
    remote = _mock_remote({"/api/connectors": payload})
    monkeypatch.setattr(
        AppContext, "from_env", classmethod(lambda cls, ollama=None: _raise(StoreLockedError("locked")))
    )
    monkeypatch.setattr(cli.RemoteHippo, "for_config", classmethod(lambda cls, config: remote))
    assert _run("list") == 0
    assert "incidents_ndjson" in capsys.readouterr().out


def test_remote_connectors_maps_a_401_and_a_coded_refusal():
    with pytest.raises(RemoteError) as unauthorized:
        _mock_remote({"/api/connectors": (401, {})}).connectors()
    assert "HIPPO_TOKEN" in str(unauthorized.value)

    refused = _mock_remote({"/api/connectors": (403, {"code": "denied", "error": "you may not"})})
    with pytest.raises(RemoteError) as coded:
        refused.connectors()
    assert str(coded.value) == "denied: you may not"


# --------------------------------------------------------------------------- validate


def test_validate_passes_the_fixture_connector(cli_ctx, capsys):
    assert _run("validate", str(PACKAGE)) == 0
    out = capsys.readouterr().out
    assert "passed" in out
    assert "+ connector kind fixture" in out


def test_validate_prints_each_violation_and_exits_1(cli_ctx, monkeypatch, capsys):
    violations = (
        kit.ContractViolation(
            "spans_match_bytes", "the span quotes text the revision never held", record="n1"
        ),
        kit.ContractViolation("aliases_name_a_rule", "an alias names no rule"),
    )
    report = kit.ValidationReport("fixture", "1", "full", ("+ kind fixture_note",), (), violations)
    monkeypatch.setattr(kit, "validate_package", lambda *a, **kw: report)
    assert _run("validate", str(PACKAGE)) == 1
    out = capsys.readouterr().out
    assert "spans_match_bytes: the span quotes text the revision never held [n1]" in out
    assert "aliases_name_a_rule: an alias names no rule" in out


def test_validate_of_a_package_that_cannot_load_exits_2(cli_ctx, tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert _run("validate", str(tmp_path / "empty")) == 2
    assert "error:" in capsys.readouterr().err


def test_validate_update_golden_prints_the_diff_and_exits_0(cli_ctx, tmp_path, capsys):
    """S4a gotcha 7: the committed goldens are real, so `--update-golden` works on a copy."""
    import shutil

    copied = tmp_path / "fixture_connector"
    shutil.copytree(PACKAGE, copied)
    (copied / "fixtures" / "basic" / "expected" / "nodes.json").write_text("[]\n")
    assert _run("validate", str(copied), "--update-golden") == 0
    out = capsys.readouterr().out
    assert "nodes.json" in out
    assert json.loads((copied / "fixtures" / "basic" / "expected" / "nodes.json").read_text()) != []


# --------------------------------------------------------------------------- probe


def test_probe_prints_family_and_mapping_per_partition(cli_ctx, entry_point, tmp_path, capsys):
    assert _run("probe", FIXTURE_KIND, "--config", str(_config_file(tmp_path))) == 0
    out = capsys.readouterr().out
    assert FIXTURE_PARTITION in out
    assert FIXTURE_FAMILY in out
    assert "note" in out, "the provider type to kind mapping is not shown"
    assert "fingerprint" in out.lower()


def test_probe_with_an_invalid_config_exits_2(cli_ctx, entry_point, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"partition": "notes", "nonesuch": 1}))
    assert _run("probe", FIXTURE_KIND, "--config", str(bad)) == 2
    assert "error:" in capsys.readouterr().err


def test_probe_of_an_unregistered_kind_prints_the_type_extension_and_exits_1(
    cli_ctx, monkeypatch, tmp_path, capsys
):
    """A registration request is exit 1 and prints the `TypeExtension` the developer must paste."""

    class Unregistered(FixtureConnector):
        descriptor = DESCRIPTOR.model_copy(
            update={"extension": fixture_extension(object_kinds=(), predicates=())}
        )

        def __init__(self):
            super().__init__(descriptor_extension=fixture_extension(object_kinds=(), predicates=()))

    monkeypatch.setattr(loader, "_entry_points", lambda: [_Point(FIXTURE_KIND, lambda: Unregistered)])
    monkeypatch.setenv(loader.ALLOWLIST_ENV, FIXTURE_KIND)
    assert _run("probe", FIXTURE_KIND, "--config", str(_config_file(tmp_path))) == 1
    out = capsys.readouterr().out
    assert "TypeExtension(" in out


def test_probe_and_sync_dry_run_refuse_an_entry_point_missing_from_the_allowlist(
    cli_ctx, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(loader, "_entry_points", lambda: [_Point(FIXTURE_KIND, lambda: FixtureEntryPoint)])
    monkeypatch.delenv(loader.ALLOWLIST_ENV, raising=False)
    config = str(_config_file(tmp_path))
    assert _run("probe", FIXTURE_KIND, "--config", config) == 2
    assert _run("sync", FIXTURE_KIND, "--config", config, "--dry-run") == 2
    assert capsys.readouterr().err.count("error:") == 2


# --------------------------------------------------------------------------- sync --dry-run


def test_sync_dry_run_prints_coverage_and_writes_nothing_to_the_configured_store(
    cli_ctx, entry_point, tmp_path, capsys
):
    before = len(cli_ctx.store.list_sources())
    assert _run("sync", FIXTURE_KIND, "--config", str(_config_file(tmp_path)), "--dry-run") == 0
    out = capsys.readouterr().out
    assert FIXTURE_PARTITION in out
    assert "published" in out
    assert len(cli_ctx.store.list_sources()) == before
    assert cli_ctx.store._knowledge_rows("Connector") == []


# --------------------------------------------------------------------------- sync


def test_sync_refuses_with_exit_2_when_the_store_is_locked(monkeypatch, capsys):
    monkeypatch.setattr(
        AppContext, "from_env", classmethod(lambda cls, ollama=None: _raise(StoreLockedError("locked")))
    )
    assert _run("sync", "connector-1") == 2
    assert "stop it to sync, or use --dry-run" in capsys.readouterr().err


def test_sync_requires_manage_sources_when_users_exist(operator, monkeypatch, capsys):
    row = _seed(operator.store)
    monkeypatch.setenv("HIPPO_TOKEN", _reader(operator)["token"])
    assert _run("sync", row.id) == 2
    assert "manage sources" in capsys.readouterr().err


def test_sync_checks_manage_sources_then_runs_as_the_trusted_local_actor(
    operator, entry_point, monkeypatch, capsys
):
    """m19: the capability check, the loader, then S3's entry with the trusted local actor."""
    order: list[str] = []
    seen: dict = {}
    require = cli._require
    monkeypatch.setattr(cli, "_require", lambda p, c: (order.append(f"require:{c}"), require(p, c))[1])
    load_connectors = loader.load_connectors
    monkeypatch.setattr(
        loader, "load_connectors", lambda ctx: (order.append("load"), load_connectors(ctx))[1]
    )

    def spy(ctx, connector, **kwargs):
        order.append("sync")
        seen.update(kwargs)
        return sync.SyncReceipt(
            source_id="source-1",
            partition=kwargs["partition"],
            outcome="published",
            generation_id="generation-1",
            build=None,
            pages=1,
            changes=2,
            deleted=0,
            policy_updates=0,
            inventory="complete",
            coverage={},
        )

    monkeypatch.setattr(sync, "sync_connector", spy)
    row = _seed(operator.store)
    assert _run("sync", row.id) == 0
    assert order == ["require:manage_sources", "load", "sync"]
    assert seen["connector_id"] == row.id
    assert seen["actor"].kind == "trusted_local"
    assert seen["actor"].user_id is None
    assert seen["partition"] == FIXTURE_PARTITION
    assert seen["operation_id"]
    assert "published" in capsys.readouterr().out


def test_sync_without_a_stored_classification_exits_2(operator, entry_point, capsys):
    row = _seed(operator.store, classified=False)
    assert _run("sync", row.id) == 2
    assert "probe it first" in capsys.readouterr().err


def test_sync_of_an_unknown_instance_exits_2(cli_ctx, entry_point, capsys):
    assert _run("sync", "connector-nonesuch") == 2
    assert "error:" in capsys.readouterr().err


def test_sync_of_a_disabled_instance_exits_2(operator, entry_point, capsys):
    """M5. The kind is enabled by a second, enabled row, so this is the instance gate, not the kind."""
    disabled = _seed(operator.store, enabled=False)
    with extension_scope() as scoped:
        scoped.register(fixture_extension(), declared_families=(FIXTURE_FAMILY,))
        sync.ensure_connector(
            operator.store,
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind=FIXTURE_KIND,
            instance_url="https://other.example",
            config=FixtureConfig(instance_url="https://other.example"),
            enabled=True,
        )
    assert _run("sync", disabled.id) == 2
    assert "error:" in capsys.readouterr().err


def test_sync_of_a_kind_that_is_not_enabled_exits_2(operator, entry_point, capsys):
    """M5. No enabled row at all, so the loader registers nothing and the kind is unknown.

    The row is still written by a signed-in operator: open mode refuses a provider `Connector`
    row whatever its `enabled` value, because `safer_connector` permits only a narrowing of a row
    that already exists (`store/authorization.py`).
    """
    row = _seed(operator.store, enabled=False)
    assert _run("sync", row.id) == 2
    assert "is not enabled" in capsys.readouterr().err


# --------------------------------------------------------------------------- enable (R59, R64, R73)


def test_enable_creates_an_enabled_instance_probes_it_and_stores_the_classification(
    operator, entry_point, tmp_path, capsys
):
    cli_ctx = operator
    url = FixtureConfig().instance_url
    assert _run("enable", FIXTURE_KIND, url, "--config", str(_config_file(tmp_path))) == 0
    rows = cli_ctx.store._knowledge_rows("Connector")
    assert [(row.kind, row.enabled) for row in rows] == [(FIXTURE_KIND, True)]
    assert json.loads(rows[0].classification_json)["partitions"], "no classification was stored"
    assert FIXTURE_PARTITION in capsys.readouterr().out


def test_enable_re_ensures_an_existing_row_with_enabled_true(operator, entry_point, monkeypatch, tmp_path):
    """R73: `enabled=True` is passed deliberately, never left to `ensure_connector`'s default."""
    cli_ctx = operator
    _seed(cli_ctx.store, enabled=False, classified=False)
    assert [row.enabled for row in cli_ctx.store._knowledge_rows("Connector")] == [False]
    seen: dict = {}
    ensure = sync.ensure_connector
    monkeypatch.setattr(
        sync, "ensure_connector", lambda store, **kw: (seen.update(kw), ensure(store, **kw))[1]
    )
    url = FixtureConfig().instance_url
    assert _run("enable", FIXTURE_KIND, url, "--config", str(_config_file(tmp_path))) == 0
    assert seen["enabled"] is True
    assert [row.enabled for row in cli_ctx.store._knowledge_rows("Connector")] == [True]


def test_enable_in_open_mode_exits_2_with_the_stores_message(cli_ctx, entry_point, tmp_path, capsys):
    """R64: open mode refuses `enabled=True` for any kind but `local`, and `enable` says so."""
    assert cli_ctx.store.count_users() == 0
    url = FixtureConfig().instance_url
    assert _run("enable", FIXTURE_KIND, url, "--config", str(_config_file(tmp_path))) == 2
    assert "open mode" in capsys.readouterr().err
    assert cli_ctx.store._knowledge_rows("Connector") == []


def test_enable_of_an_unknown_connector_exits_2(cli_ctx, capsys):
    assert _run("enable", "nonesuch", "https://nonesuch.example") == 2
    assert "error:" in capsys.readouterr().err


# --------------------------------------------------------------------------- new


def test_new_writes_a_package_and_exits_0(cli_ctx, tmp_path, capsys):
    assert _run("new", "incidents_ndjson", "--family", "incident", "--dest", str(tmp_path)) == 0
    assert (tmp_path / "incidents_ndjson" / "connector.py").exists()
    assert "incidents_ndjson" in capsys.readouterr().out


def test_new_refuses_a_registered_connector_kind_with_exit_2(cli_ctx, tmp_path, capsys):
    assert _run("new", "local", "--family", "prose", "--dest", str(tmp_path)) == 2
    assert "error:" in capsys.readouterr().err
    assert not (tmp_path / "local").exists()


# --------------------------------------------------------------------------- helpers


def _raise(error: Exception):
    raise error


def _mock_remote(routes: dict) -> RemoteHippo:
    def handle(request: httpx.Request) -> httpx.Response:
        answer = routes.get(request.url.path)
        if answer is None:
            return httpx.Response(200, json={})
        if isinstance(answer, tuple):
            return httpx.Response(answer[0], json=answer[1])
        return httpx.Response(200, json=answer)

    base_url = "http://hippo.invalid"
    client = httpx.Client(base_url=base_url, transport=httpx.MockTransport(handle))
    return RemoteHippo(base_url, client=client, token="")


def _top_role(ctx: AppContext) -> str:
    from hippo.access import top_role

    return top_role(ctx.store.list_roles())["id"]


def _user(ctx: AppContext, username: str) -> dict:
    return ctx.store.get_user_by_username(username)


def _reader(ctx: AppContext) -> dict:
    """A user in the lowest role that may not manage sources."""
    roles = sorted(ctx.store.list_roles(), key=lambda role: role["rank"])
    role = next(role for role in roles if "manage_sources" not in role["capabilities"])
    ctx.store.create_user("reader", "reader-password", role["id"], "Reader")
    return _user(ctx, "reader")


def test_the_connector_command_is_not_an_evidence_command():
    """Plan section 4 step 3.4: its store reads are administration, gated by `manage_sources`."""
    assert "connector" not in cli.EVIDENCE_COMMANDS


def test_a_type_extension_is_importable_for_the_scaffold_test():
    """A guard on this module's imports: `TypeExtension` is the name the scaffold's types use."""
    assert TypeExtension().object_kinds == ()
