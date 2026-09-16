"""The scaffold behind `hippo connector new`, and the developer guide (CDK S4b).

Plan `ai_docs/plans/cdk-s4-kit.md` sections 3.2 and 3.4 and section 5 "S4b", amended by ruling M16
(the generated `emit` writes no `instance` key part; the kit fills it), R46 (the descriptor carries
its `extension`), B4 (the extension registers the connector kind) and R64 (the descriptor name, the
registered connector kind and `__init__.py`'s `Connector` re-export are one name).

Two rules hold here:

* **`render_package` runs the whole kit.** It calls `validate_package(..., update_golden=True)`, so
  a rendered package arrives with its registry lock and its seven goldens already computed. Every
  test that renders therefore points `testing.scratch_store` at the backend `HIPPO_TEST_STORE`
  names, exactly as `test_connector_testing_kit.py` does; the shipped default is a temporary
  LadybugDB.
* **Nothing here registers into `REGISTRY`.** `render_package` builds its own registry through
  `testing.kit_registry`, and the tests that look a family or a kind up read
  `Registry.with_builtins()` (re-review N1).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from hippo.connectors import base, emit, scaffold
from hippo.connectors import testing as kit
from hippo.knowledge import model as k
from hippo.store.migrations import DEFAULT_WORKSPACE_ID
from tests.conftest import LADYBUG_TEST_BUFFER_POOL_BYTES, store_backend
from tests.fakes.fake_store import FakeStore

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "spec" / "cdk-guide.md"
FIXTURE_PACKAGE = Path(__file__).resolve().parents[1] / "fakes" / "fixture_connector"
PINNED = scaffold.ScaffoldRequest(name="incidents_ndjson", family="incident", kinds=("incident",))
EXPIRES = kit.POLICY_TTL


# --------------------------------------------------------------------------- the backend seam


def _point_scratch_store(monkeypatch) -> None:
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


@pytest.fixture(autouse=True)
def scratch_store(monkeypatch):
    _point_scratch_store(monkeypatch)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> Path:
    """One rendering of the pinned request, shared by the tests that only read it.

    `render_package` runs the full `validate_package`, which opens a scratch store and publishes a
    generation, so it is paid once per module. A test that changes the tree copies it first.
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        _point_scratch_store(monkeypatch)
        dest = tmp_path_factory.mktemp("scaffold")
        scaffold.render_package(PINNED, dest)
    return dest / PINNED.name


# --------------------------------------------------------------------------- the written package


def test_new_writes_the_documented_package_files(tmp_path):
    """Plan section 3.2's table, file for file, plus the lock and goldens the kit computes."""
    written = scaffold.render_package(PINNED, tmp_path)
    package = tmp_path / PINNED.name
    assert package.is_dir()
    relative = sorted(str(path.relative_to(package)) for path in written)
    assert relative == [
        "__init__.py",
        "connector.py",
        "fixtures/basic/changes.json",
        "fixtures/basic/config.json",
        "fixtures/basic/expected/aliases.json",
        "fixtures/basic/expected/coverage.json",
        "fixtures/basic/expected/edges.json",
        "fixtures/basic/expected/failures.json",
        "fixtures/basic/expected/nodes.json",
        "fixtures/basic/expected/passages.json",
        "fixtures/basic/expected/units.json",
        "fixtures/basic/inputs/record-1",
        "fixtures/basic/inputs/record-2",
        "fixtures/basic/policies.json",
        "fixtures/registry.lock.json",
        "templates.py",
        "tests/test_connector.py",
        "types.py",
    ]
    assert sorted(p for p in written if p.exists()) == sorted(written)
    assert json.loads((package / "fixtures" / "basic" / "config.json").read_text()) == {
        "export_dir": ".",
        "partition": "export",
    }
    exported = (package / "__init__.py").read_text()
    assert "from .connector import IncidentsNdjsonConnector as Connector" in exported


def test_a_new_package_passes_validate(rendered):
    """Section 1's goal: a developer runs `new` then `validate` and the kit passes."""
    report = kit.validate_package(rendered)
    assert report.error is None, report.error
    assert report.violations == (), [v.assertion for v in report.violations]
    assert [case.diff for case in report.cases] == [""]
    assert report.passed
    assert report.scope == "full"
    assert f"+ connector kind {PINNED.name}" in report.registry_diff
    assert "+ kind incident" in report.registry_diff


def test_a_new_packages_own_test_passes(rendered):
    """The generated `tests/test_connector.py` is a real test, and it is green on arrival."""
    source = (rendered / "tests" / "test_connector.py").read_text()
    assert "validate_package" in source
    namespace: dict = {"__file__": str(rendered / "tests" / "test_connector.py")}
    exec(compile(source, str(rendered / "tests" / "test_connector.py"), "exec"), namespace)
    tests = [name for name in namespace if name.startswith("test_")]
    assert tests, "the generated package ships no test"
    for name in tests:
        namespace[name]()


@pytest.mark.parametrize(
    ("request_kwargs", "message"),
    [
        ({"name": "Incidents"}, "name"),
        ({"name": "9lives"}, "name"),
        ({"name": "x"}, "name"),
        ({"family": "nonesuch"}, "family"),
        ({"name": "local"}, "connector kind"),
        ({"kinds": ("Incident",)}, "kind"),
        ({"kinds": ("person",)}, "kind"),
    ],
)
def test_new_refuses_an_invalid_name_an_unknown_family_a_registered_kind_and_an_existing_directory(
    tmp_path, request_kwargs, message
):
    """The plan's section 3.3 exit-2 conditions, each named rather than raised as a traceback."""
    fields = {"name": PINNED.name, "family": PINNED.family, "kinds": PINNED.kinds} | request_kwargs
    with pytest.raises(scaffold.ScaffoldError) as refusal:
        scaffold.render_package(scaffold.ScaffoldRequest(**fields), tmp_path)
    assert message in str(refusal.value)
    assert not (tmp_path / fields["name"]).exists(), "a refused request left a directory behind"


def test_new_refuses_an_existing_target(tmp_path):
    (tmp_path / PINNED.name).mkdir()
    with pytest.raises(scaffold.ScaffoldError) as refusal:
        scaffold.render_package(PINNED, tmp_path)
    assert "exists" in str(refusal.value)


def test_the_scaffold_templates_ship_as_package_data():
    """They are read through `importlib.resources`, so the wheel carries them (plan section 2)."""
    import importlib.resources

    templates = importlib.resources.files("hippo.connectors.scaffold") / "templates"
    names = sorted(entry.name for entry in templates.iterdir())
    assert names == [
        "__init__.py.tmpl",
        "changes.json.tmpl",
        "config.json.tmpl",
        "connector.py.tmpl",
        "policies.json.tmpl",
        "record-1.tmpl",
        "record-2.tmpl",
        "templates.py.tmpl",
        "test_connector.py.tmpl",
        "types.py.tmpl",
    ]
    assert Path(scaffold.__file__).parent / "templates" / "connector.py.tmpl"


# --------------------------------------------------------------------------- M16


def test_the_scaffold_emits_node_refs_without_an_instance_key_part(rendered, tmp_path):
    """M16: the template emits `key={"id": ...}` and the kit fills `instance` (S2 section 6 step 2)."""
    connector, _package = kit.load_connector_package(rendered)
    descriptor = connector.descriptor
    registry = kit.kit_registry(descriptor)
    kind = registry.object_kind(PINNED.kinds[0])
    assert kind.key_template[0] == "instance", "the generated kind still declares the instance part"

    payload = json.dumps({"id": "record-1", "title": "First record"}, sort_keys=True).encode()
    ref = base.ExternalRef(partition="export", artifact_kind="document", external_id="record-1")
    captured = emit.capture_records(
        base.RawFetch(
            ref=ref,
            data=payload,
            content_type="application/json",
            external_id="record-1",
            canonical_uri=f"{kit.KIT_INSTANCE_URL}/records/record-1",
        ),
        base.PolicyObservation(ref=ref, state="known", mode="workspace"),
        connector=k.Connector(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind=descriptor.name,
            instance_url=kit.KIT_INSTANCE_URL,
            config_json=descriptor.config_model(export_dir=".").model_dump_json(),
            enabled=True,
        ),
        workspace_id=DEFAULT_WORKSPACE_ID,
        source_id="kit-basic",
        raw_uri=f"raw://kit/{hashlib.sha256(payload).hexdigest()}",
        observed_at=kit.FIXED_INSTANT,
        policy_expires_at=kit.FIXED_INSTANT + EXPIRES,
    )
    # A real export directory, so the generated `list_changes` and `fetch` run too: the kit
    # replaces both with a replay, so this is the only place their real bodies are exercised.
    export = tmp_path / "export"
    export.mkdir()
    (export / "record-1.json").write_bytes(payload)
    with base.use_registry(registry):
        classification = connector.probe(
            descriptor.config_model(export_dir=str(export)), lambda: kit.FIXED_INSTANT
        )
        mapping = classification.partitions[0].mapping
        batch = connector.emit(
            base.RevisionInput(
                partition="export",
                artifact=captured.artifact,
                revision=captured.revision,
                data=payload,
                config=descriptor.config_model(export_dir="."),
                mapping=mapping,
                registry=registry,
                span_policy_id=captured.policy.id,
            ),
            mapping,
        )
    assert [node.ref.key for node in batch.nodes] == [{"id": "record-1"}]
    assert all(node.ref.instance is None for node in batch.nodes)
    # The emitted ref names no instance part; the word survives only in prose and in the kind.
    source = (rendered / "connector.py").read_text()
    assert 'base.NodeRef(kind=PRIMARY_KIND, key={"id": identifier})' in source
    assert '"instance"' not in source


# --------------------------------------------------------------------------- the pinned output


def test_scaffold_output_for_a_fixed_request_is_pinned(rendered):
    """A kit or template change that alters scaffold output fails here, not in a developer's package.

    Every file is pinned by SHA-256, and the short ones the contract turns on — the `Connector`
    re-export (R64) and the fixture case — are pinned byte for byte as well. Regenerate both maps
    with `python tests/unit/test_connector_scaffold.py`, and read the diff before you paste it: a
    changed digest here means every scaffolded package changes.
    """
    actual = {
        str(path.relative_to(rendered)): path.read_bytes()
        for path in sorted(rendered.rglob("*"))
        # Bytecode is not scaffold output: a later test imports the package and leaves some.
        if path.is_file() and "__pycache__" not in path.parts
    }
    for name, expected in PINNED_SOURCES.items():
        assert actual[name].decode() == expected, name
    digests = {name: hashlib.sha256(body).hexdigest() for name, body in actual.items()}
    changed = sorted(set(digests) ^ set(PINNED_DIGESTS)) + sorted(
        name for name in digests if name in PINNED_DIGESTS and digests[name] != PINNED_DIGESTS[name]
    )
    assert digests == PINNED_DIGESTS, f"scaffold output changed: {changed}"


def test_a_scaffolded_package_is_ruff_clean(rendered):
    """CI runs `ruff check` and `ruff format --check` over the repository; a developer's does too."""
    files = sorted(str(path) for path in rendered.rglob("*.py"))
    assert files
    for argv in (["check", "--no-cache"], ["format", "--check", "--no-cache"]):
        result = subprocess.run(
            [sys.executable, "-m", "ruff", *argv, *files],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"ruff {argv[0]}:\n{result.stdout}\n{result.stderr}"


# --------------------------------------------------------------------------- the guide (3.4)


def _guide_examples() -> list[tuple[str, str]]:
    """Every `<!-- cdk-guide: example <name> -->` and the fenced Python block that follows it."""
    lines = GUIDE.read_text().splitlines(keepends=True)
    examples, index = [], 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("<!-- cdk-guide: example ") and line.endswith("-->"):
            name = line.removeprefix("<!-- cdk-guide: example ").removesuffix("-->").strip()
            assert lines[index + 1].rstrip("\n") == "```python", f"example {name} is not a python fence"
            end = index + 2
            while lines[end].rstrip("\n") != "```":
                end += 1
            examples.append((name, "".join(lines[index + 2 : end])))
            index = end
        index += 1
    return examples


def _marked_regions() -> dict[str, str]:
    """The `# cdk-guide: begin/end <name>` regions of the fixture connector (R-S3-7)."""
    regions: dict[str, str] = {}
    for source in sorted(FIXTURE_PACKAGE.glob("*.py")):
        lines = source.read_text().splitlines(keepends=True)
        starts: dict[str, int] = {}
        for index, line in enumerate(lines):
            marker = line.strip()
            if marker.startswith("# cdk-guide: begin "):
                starts[marker.removeprefix("# cdk-guide: begin ").strip()] = index + 1
            elif marker.startswith("# cdk-guide: end "):
                name = marker.removeprefix("# cdk-guide: end ").strip()
                # One trailing newline, no trailing blank line: ruff wants a blank line before the
                # end marker inside a class body, and refuses one at the end of a fenced block, so
                # the two rules meet here rather than in the guide.
                regions[name] = "".join(lines[starts[name] : index]).rstrip("\n") + "\n"
    return regions


def test_the_guide_exists_and_every_python_example_is_the_fixture_connector():
    """Plan section 3.4: an example is a marked region of the fixture connector, byte for byte.

    A region inside `class FixtureConnector` is not valid top-level Python, and `ruff format` would
    dedent and reflow it, so a fence that holds one carries the single class header line above it.
    The region itself is still byte-identical; the header is the only thing the guide adds.
    """
    assert GUIDE.exists(), f"{GUIDE} is missing"
    regions = _marked_regions()
    examples = _guide_examples()
    assert examples, "the guide has no marked examples"
    assert sorted(name for name, _ in examples) == ["descriptor", "emit", "sync_half", "types"]
    for name, block in examples:
        assert name in regions, f"the fixture connector has no region named {name}"
        region = regions[name]
        assert block in (region, f"class FixtureConnector:\n{region}"), name


def test_the_guide_documents_every_assertion():
    """Section 3.4 item 8: one row per name in `testing.ASSERTIONS`, with what trips it."""
    text = GUIDE.read_text()
    missing = [name for name in kit.ASSERTIONS if f"`{name}`" not in text]
    assert missing == []
    for scenario in kit.RUNTIME_SCENARIOS:
        assert f"`{scenario}`" in text
    for heading in (
        "hippo connector new",
        "hippo connector validate",
        "hippo connector probe",
        "hippo connector sync --dry-run",
        "hippo.connectors",
    ):
        assert heading in text, heading


def test_the_guide_carries_no_credential_and_no_user_data():
    """The brief's constraint: the guide quotes the fixture connector and nothing of the user's."""
    text = GUIDE.read_text()
    for forbidden in ("HIPPO_TOKEN=", "Bearer ", "smoke-credentials", ".rag-dev-data", "sha256:"):
        assert forbidden not in text, forbidden
    assert "password" not in text.lower()


def test_the_fixture_connector_markers_are_comments_only():
    """S4b's one edit to S3's package: comment lines, nothing else (plan section 7)."""
    for source in sorted(FIXTURE_PACKAGE.glob("*.py")):
        for line in source.read_text().splitlines():
            if "cdk-guide:" in line:
                assert line.strip().startswith("# cdk-guide: "), line
    assert set(_marked_regions()) == {"descriptor", "emit", "sync_half", "types"}


# --------------------------------------------------------------------------- the pins
#
# Filled from the first GREEN run of `render_package(PINNED, ...)`; regenerate with
# `python -m tests.unit.test_connector_scaffold` if the templates or the kit change.

PINNED_SOURCES: dict[str, str] = {
    "__init__.py": '"""The `incidents_ndjson` connector package.\n\n`Connector` is the name the loader and `hippo connector validate` resolve (design section 9,\nruling R64). It must be the class whose `descriptor.name` equals this package\'s directory name\nand the connector kind `types.py` registers: the loader refuses any disagreement.\n"""\n\nfrom .connector import IncidentsNdjsonConnector as Connector\n\n__all__ = ["Connector"]\n',
    "fixtures/basic/config.json": '{"export_dir": ".", "partition": "export"}\n',
    "fixtures/basic/changes.json": '{\n  "pages": [\n    {\n      "partition": "export",\n      "changes": [\n        {\n          "ref": {\n            "partition": "export",\n            "artifact_kind": "document",\n            "external_id": "record-1"\n          },\n          "operation": "upsert"\n        },\n        {\n          "ref": {\n            "partition": "export",\n            "artifact_kind": "document",\n            "external_id": "record-2"\n          },\n          "operation": "upsert"\n        }\n      ],\n      "next_cursor": null,\n      "complete": true,\n      "warnings": []\n    }\n  ],\n  "fetches": {\n    "record-1": {"content_type": "application/json"},\n    "record-2": {"content_type": "application/json"}\n  }\n}\n',
    "fixtures/basic/policies.json": '{\n  "record-1": {"state": "known", "mode": "workspace"},\n  "record-2": {"state": "known", "mode": "workspace"}\n}\n',
    "fixtures/basic/inputs/record-1": '{"id": "record-1", "title": "The first record"}\n',
    "fixtures/basic/inputs/record-2": '{"id": "record-2", "summary": "This record has no title, so `emit` counts it as a parse failure"}\n',
}

PINNED_DIGESTS: dict[str, str] = {
    "__init__.py": "697d85cc311046d9a18121e05114b204a14ed546b8e4283f1a8fec733efa31dc",
    "connector.py": "70580a63cae4e0bc8de3e3b8f30d49d09f3cc1c6d04480a8e44f45ea9adaf3d6",
    "fixtures/basic/changes.json": "9eea401a8ed3c2ac81e80612b22dffe488d030a79b40150b6b1869748d7f7f7a",
    "fixtures/basic/config.json": "9afbd12afa830563fbc928ee7fe4ddcfe3887111e6bac3aad06e17e7bb7689fb",
    "fixtures/basic/expected/aliases.json": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    "fixtures/basic/expected/coverage.json": "2aea408ebe59787eae9bc74954fc59fd67b4e57e0c5ad9955346aac073f03dd4",
    "fixtures/basic/expected/edges.json": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    "fixtures/basic/expected/failures.json": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    "fixtures/basic/expected/nodes.json": "24631b1b6260f63ea838646eb16782a04bc88c388dd3573e20d499d37366371c",
    "fixtures/basic/expected/passages.json": "25079825e2cdecdc90941abda55be540a87bb0d3f7036e67b7f7bfee98425f9c",
    "fixtures/basic/expected/units.json": "a5ec4a180f142dadb8124fb879cf6d88739ddef8d760ea9df2543e4d2d06e2df",
    "fixtures/basic/inputs/record-1": "29c85af4a3d667c54ccee0c29ab256129e154f8ce44cd3b2478b19d7d48ba22a",
    "fixtures/basic/inputs/record-2": "baed8ca31aff4eb1071f5cd6267bb9f75bf600a0bca43a8b1918ec3a09f85fc6",
    "fixtures/basic/policies.json": "10c3d41e58694f65b7da06c358f6ee10ad2370abae2e0129b760b0f96ee586fc",
    "fixtures/registry.lock.json": "428b518bec4ebec7cfa839fbd91cf48a0cdeb63fd8b127c5a2b73386b2dfcb9d",
    "templates.py": "689084670e6c0b4859473ed6eab24d2579a2e94069fd11b2dc49c5f6f7a8090b",
    "tests/test_connector.py": "303787687e73662a8b673cb8a3712db1d952766df65606cdfa80978515319fac",
    "types.py": "ac3b2721cb2717123eb414b9827a85b968aaa42048cf4809f72e192e4edacc31",
}
