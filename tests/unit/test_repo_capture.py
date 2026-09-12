"""Repository, archive and single-file capture is bounded, canonical and order-independent."""

import json
import os
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from zipfile import ZipFile

import pytest

from hippo.knowledge.raw_artifacts import RawArtifactStore

INSTANT = datetime(2026, 9, 12, 8, 30, tzinfo=UTC)
OTHER_INSTANT = datetime(2031, 1, 1, 0, 0, tzinfo=UTC)


@pytest.fixture
def api():
    return import_module("hippo.ingest.repo_capture")


@pytest.fixture
def raw_store(tmp_path):
    return RawArtifactStore(tmp_path / "raw", max_object_bytes=2_000_000)


def limits(api, **changes):
    return api.CaptureLimits(
        **(
            {
                "max_input_bytes": 200_000,
                "max_total_bytes": 2_000_000,
                "max_inputs": 200,
                "max_manifest_bytes": 200_000,
            }
            | changes
        )
    )


def capture(api, raw_store, root, **changes):
    args = {
        "raw_store": raw_store,
        "source_id": "source-one",
        "workspace_id": "workspace-one",
        "limits": limits(api),
        "configuration": {"chunker": {"size": 1200}},
        "observed_at": INSTANT,
    }
    args.update(changes)
    return api.capture_repository_inputs(root, **args)


def tree(root: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def accepted_paths(result) -> list[str]:
    return [item.logical_path for item in result.inputs]


def reasons(result) -> dict[str, str]:
    return {item.logical_path: item.reason for item in result.exclusions}


def raw_object_count(store_root: Path) -> int:
    return sum(1 for path in Path(store_root).rglob("*") if path.is_file())


# ------------------------------------------------------------- inventory


def test_inventory_is_normalized_sorted_and_classified(api, tmp_path):
    root = tree(
        tmp_path / "repo",
        {
            "z/last.py": b"print(1)\n",
            "a/first.py": b"print(2)\n",
            "README": b"hello\n",
            "conf/app.yaml": b"a: b\n",
        },
    )
    inventory = api.walk_tree(root)
    assert inventory.kind == "repo"
    assert [item.logical_path for item in inventory.inputs] == [
        "README",
        "a/first.py",
        "conf/app.yaml",
        "z/last.py",
    ]
    assert all(item.path.is_absolute() for item in inventory.inputs)
    assert inventory.exclusions == ()
    with pytest.raises(FrozenInstanceError):
        inventory.kind = "archive"


def test_walk_order_does_not_change_the_accepted_identity(api, raw_store, tmp_path, monkeypatch):
    files = {"a/one.py": b"one\n", "b/two.py": b"two\n", "c/three.py": b"three\n", "top.md": b"# top\n"}
    first = capture(api, raw_store, tree(tmp_path / "repo", files))

    class _Reversed:
        def __init__(self, entries):
            self._entries = entries

        def __enter__(self):
            return iter(self._entries)

        def __exit__(self, *unused):
            return False

    real_scandir = os.scandir

    def reversed_scandir(path):
        with real_scandir(path) as entries:
            return _Reversed(list(reversed(sorted(entries, key=lambda item: item.name))))

    monkeypatch.setattr(api.os, "scandir", reversed_scandir)
    other_store = RawArtifactStore(tmp_path / "other-raw", max_object_bytes=2_000_000)
    second = capture(api, other_store, tree(tmp_path / "again", files))
    assert accepted_paths(second) == accepted_paths(first)
    assert second.accepted.manifest.sha256 == first.accepted.manifest.sha256


def test_two_captures_of_the_same_tree_share_one_identity(api, raw_store, tmp_path):
    files = {"pkg/mod.py": b"x = 1\n", "docs/readme.md": b"hi\n"}
    first = capture(api, raw_store, tree(tmp_path / "one", files))
    second = capture(api, raw_store, tree(tmp_path / "two", files))
    assert first.accepted.manifest == second.accepted.manifest
    assert first.accepted.manifest_bytes == second.accepted.manifest_bytes


def test_capture_instant_and_head_revision_are_carried_but_never_hashed(api, raw_store, tmp_path):
    files = {"pkg/mod.py": b"x = 1\n"}
    first = capture(api, raw_store, tree(tmp_path / "one", files), provider_revision="a" * 40)
    second = capture(
        api,
        raw_store,
        tree(tmp_path / "two", files),
        observed_at=OTHER_INSTANT,
        provider_revision="b" * 40,
    )
    assert first.observed_at == INSTANT and first.provider_revision == "a" * 40
    assert second.observed_at == OTHER_INSTANT and second.provider_revision == "b" * 40
    assert first.accepted.manifest.sha256 == second.accepted.manifest.sha256
    assert all(item.provider_revision is None for item in first.accepted.inputs)


def test_exclusion_policy_enters_the_accepted_identity(api, raw_store, tmp_path):
    files = {"keep.py": b"x = 1\n", "drop/skip.py": b"y = 2\n"}
    plain = capture(api, raw_store, tree(tmp_path / "one", files))
    filtered = capture(api, raw_store, tree(tmp_path / "two", files), exclusions=("drop",))
    assert accepted_paths(filtered) == ["keep.py"]
    assert reasons(filtered) == {"drop": "configured_exclusion"}
    assert filtered.accepted.manifest.sha256 != plain.accepted.manifest.sha256
    configuration = json.loads(filtered.accepted.configuration_json)
    assert configuration["capture"]["exclusions"] == ["drop"]
    assert configuration["capture"]["kind"] == "repo"
    assert configuration["chunker"] == {"size": 1200}


def test_exclusion_policy_order_and_duplicates_do_not_change_identity(api, raw_store, tmp_path):
    files = {"keep.py": b"x = 1\n", "drop/skip.py": b"y = 2\n", "also/skip.py": b"z = 3\n"}
    first = capture(api, raw_store, tree(tmp_path / "one", files), exclusions=("drop", "also"))
    second = capture(api, raw_store, tree(tmp_path / "two", files), exclusions=("also/", "drop", "also"))
    assert first.accepted.manifest.sha256 == second.accepted.manifest.sha256


def test_reserved_configuration_key_is_refused(api, raw_store, tmp_path):
    root = tree(tmp_path / "repo", {"a.py": b"x = 1\n"})
    with pytest.raises(api.CaptureRefused) as error:
        capture(api, raw_store, root, configuration={"capture": {"kind": "repo"}})
    assert error.value.reason == "reserved_configuration"


def test_manifest_records_only_relative_logical_paths(api, raw_store, tmp_path):
    root = tree(tmp_path / "repo", {"pkg/mod.py": b"x = 1\n", "node_modules/dep.js": b"y\n"})
    result = capture(api, raw_store, root)
    manifest = result.accepted.manifest_bytes
    assert str(tmp_path).encode() not in manifest
    assert b"hippo-raw:" not in manifest
    payload = json.loads(manifest)
    assert [item["logical_path"] for item in payload["inputs"]] == ["pkg/mod.py"]
    assert {item["logical_path"] for item in payload["dispositions"]} == {"pkg/mod.py", "node_modules"}


# ------------------------------------------------------------ exclusions


def test_every_exclusion_reason_is_recorded_with_its_own_name(api, tmp_path):
    root = tree(
        tmp_path / "repo",
        {
            "keep.py": b"x = 1\n",
            "node_modules/dep.js": b"y = 2\n",
            ".hidden.py": b"z = 3\n",
            "drop/skip.py": b"w = 4\n",
            "image.png": b"\x89PNG\r\n",
            "bin.py": b"\x00\x01\x02",
            "huge.py": b"x" * 64,
            "sub/.git": b"gitdir: ../.git/modules/sub\n",
            "sub/inner.py": b"v = 5\n",
        },
    )
    (root / "link.py").symlink_to(root / "keep.py")
    os.mkfifo(root / "pipe.py")
    inventory = api.walk_tree(root, exclusions=("drop",), max_file_bytes=32)
    assert [item.logical_path for item in inventory.inputs] == ["keep.py"]
    assert reasons(inventory) == {
        ".hidden.py": "ignored_path",
        "bin.py": "binary",
        "drop": "configured_exclusion",
        "huge.py": "too_large",
        "image.png": "unsupported_language",
        "link.py": "symlink",
        "node_modules": "ignored_path",
        "pipe.py": "not_regular",
        "sub": "submodule",
    }
    assert set(reasons(inventory).values()) <= set(api.EXCLUSION_REASONS)


def test_exclusion_reasons_are_a_closed_set(api):
    assert api.EXCLUSION_REASONS == (
        "binary",
        "configured_exclusion",
        "ignored_path",
        "not_regular",
        "submodule",
        "symlink",
        "too_large",
        "unsupported_language",
    )
    with pytest.raises(ValueError, match="exclusion reason"):
        api.ExcludedFile("a.py", "because-i-said-so")


def test_an_ignored_directory_is_recorded_once_and_never_descended(api, tmp_path):
    root = tree(
        tmp_path / "repo",
        {f"node_modules/pkg{index}/index.js": b"x\n" for index in range(5)} | {"a.py": b"x = 1\n"},
    )
    inventory = api.walk_tree(root)
    assert reasons(inventory) == {"node_modules": "ignored_path"}


def test_a_symlinked_directory_is_excluded_rather_than_followed(api, tmp_path):
    root = tree(tmp_path / "repo", {"pkg/mod.py": b"x = 1\n"})
    outside = tree(tmp_path / "outside", {"secret.py": b"secret = 1\n"})
    (root / "away").symlink_to(outside, target_is_directory=True)
    inventory = api.walk_tree(root)
    assert [item.logical_path for item in inventory.inputs] == ["pkg/mod.py"]
    assert reasons(inventory) == {"away": "symlink"}


def test_an_extensionless_text_file_is_accepted_and_a_binary_one_is_excluded(api, tmp_path):
    root = tree(tmp_path / "repo", {"TOOLS": b"a text note\n", "blob": b"\x00\x01binary"})
    inventory = api.walk_tree(root)
    assert [item.logical_path for item in inventory.inputs] == ["TOOLS"]
    assert reasons(inventory) == {"blob": "binary"}


# -------------------------------------------------------------- refusals


def test_the_file_rail_refuses_before_any_raw_write(api, raw_store, tmp_path):
    root = tree(tmp_path / "repo", {f"mod{index}.py": b"x = 1\n" for index in range(4)})
    before = raw_object_count(tmp_path / "raw")
    with pytest.raises(api.CaptureRefused) as error:
        capture(api, raw_store, root, max_files=3)
    assert error.value.reason == "too_many_files"
    assert raw_object_count(tmp_path / "raw") == before


def test_the_total_byte_rail_refuses_before_any_raw_write(api, raw_store, tmp_path):
    root = tree(tmp_path / "repo", {f"mod{index}.py": b"x" * 40 for index in range(4)})
    before = raw_object_count(tmp_path / "raw")
    with pytest.raises(api.CaptureRefused) as error:
        capture(api, raw_store, root, limits=limits(api, max_total_bytes=100))
    assert error.value.reason == "total_bytes"
    assert raw_object_count(tmp_path / "raw") == before


def test_the_per_input_byte_rail_refuses_before_any_raw_write(api, raw_store, tmp_path):
    root = tree(tmp_path / "repo", {"small.py": b"x\n", "big.py": b"x" * 80})
    before = raw_object_count(tmp_path / "raw")
    with pytest.raises(api.CaptureRefused) as error:
        capture(api, raw_store, root, limits=limits(api, max_input_bytes=40))
    assert error.value.reason == "input_bytes"
    assert raw_object_count(tmp_path / "raw") == before


@pytest.mark.parametrize("locked", ["locked", "shut"])
def test_an_unreadable_file_or_directory_refuses_rather_than_becoming_an_exclusion(api, tmp_path, locked):
    root = tree(tmp_path / "repo", {"locked": b"text\n", "shut/inner.py": b"x = 1\n"})
    os.chmod(root / locked, 0o000)
    try:
        if os.access(root / locked, os.R_OK):  # pragma: no cover - only when running as root
            pytest.skip("the test user can read a mode 000 entry")
        with pytest.raises(api.CaptureRefused) as error:
            api.walk_tree(root)
        assert error.value.reason == "unreadable"
    finally:
        os.chmod(root / locked, 0o700)


def test_a_name_with_no_portable_spelling_refuses_without_claiming_an_escape(api, tmp_path):
    root = tree(tmp_path / "repo", {"ok.py": b"x = 1\n"})
    (root / "weird\\name.py").write_bytes(b"y = 2\n")
    with pytest.raises(api.CaptureRefused) as error:
        api.walk_tree(root)
    assert error.value.reason == "unportable_path"
    assert "unportable_path" in api.REFUSAL_REASONS and "escaping_path" in api.REFUSAL_REASONS


def test_two_archive_members_claiming_one_logical_path_refuse(api, tmp_path):
    archive = tmp_path / "bundle.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("pkg/mod.py", "x = 1\n")
        package.writestr("pkg//mod.py", "x = 2\n")
    with pytest.raises(api.CaptureRefused) as error:
        api.walk_tree(archive)
    assert error.value.reason == "duplicate_path"


def test_a_missing_or_unsupported_root_refuses(api, tmp_path):
    with pytest.raises(api.CaptureRefused) as error:
        api.walk_tree(tmp_path / "nowhere")
    assert error.value.reason == "unsupported_root"
    prose = tree(tmp_path / "one", {"notes.md": b"hi\n"}) / "notes.md"
    with pytest.raises(api.CaptureRefused) as other:
        api.walk_tree(prose)
    assert other.value.reason == "unsupported_root"


def test_walk_refuses_rather_than_returning_a_partial_inventory(api, tmp_path):
    root = tree(tmp_path / "repo", {f"mod{index}.py": b"x = 1\n" for index in range(4)})
    with pytest.raises(api.CaptureRefused):
        api.walk_tree(root, max_files=2)


# -------------------------------------------------- archives and one file


def test_an_archive_goes_through_the_same_function(api, raw_store, tmp_path):
    archive = tmp_path / "bundle.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("pkg/mod.py", "x = 1\n")
        package.writestr("node_modules/dep.js", "y = 2\n")
        package.writestr("pkg/logo.png", "\x89PNG")
    result = capture(api, raw_store, archive)
    assert result.kind == "archive"
    assert accepted_paths(result) == ["pkg/mod.py"]
    assert reasons(result) == {"node_modules/dep.js": "ignored_path", "pkg/logo.png": "unsupported_language"}
    assert json.loads(result.accepted.configuration_json)["capture"]["kind"] == "archive"


def test_an_archive_member_that_escapes_the_root_refuses(api, tmp_path):
    archive = tmp_path / "bundle.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("../escape.py", "x = 1\n")
    with pytest.raises(api.CaptureRefused) as error:
        api.walk_tree(archive)
    assert error.value.reason == "escaping_path"


def test_an_archive_inside_an_archive_refuses(api, raw_store, tmp_path):
    archive = tmp_path / "bundle.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("pkg/mod.py", "x = 1\n")
        package.writestr("pkg/inner.zip", "PK\x03\x04")
    with pytest.raises(api.CaptureRefused) as error:
        capture(api, raw_store, archive)
    assert error.value.reason == "nested_archive"


def test_a_single_code_file_goes_through_the_same_function(api, raw_store, tmp_path):
    path = tree(tmp_path / "repo", {"solo.py": b"x = 1\n"}) / "solo.py"
    result = capture(api, raw_store, path)
    assert result.kind == "file"
    assert accepted_paths(result) == ["solo.py"]
    assert result.exclusions == ()
    assert json.loads(result.accepted.configuration_json)["capture"]["kind"] == "file"


def test_every_accepted_file_is_readable_from_the_captured_raw_object(api, raw_store, tmp_path):
    files = {"pkg/mod.py": b"x = 1\n", "conf/app.yaml": b"a: b\n", "README": b"hello\n"}
    result = capture(api, raw_store, tree(tmp_path / "repo", files))
    assert {
        item.logical_path: raw_store.read_bytes(item.raw_artifact) for item in result.accepted.inputs
    } == files


# --------------------------------------------- provisional repository identity


def test_the_full_repository_path_is_kept_so_subgroups_do_not_collide(api):
    alpha = api.repository_descriptor("https://gitlab.example.com/alpha/team/api")
    beta = api.repository_descriptor("https://gitlab.example.com/beta/team/api")
    assert alpha.provider_repository_id == "alpha/team/api"
    assert beta.provider_repository_id == "beta/team/api"
    assert alpha.provider_instance == beta.provider_instance == "https://gitlab.example.com"
    assert alpha != beta
    with pytest.raises(FrozenInstanceError):
        alpha.provider_instance = "https://elsewhere"


def test_the_two_segment_legacy_name_is_the_collision_this_replaces(api):
    from hippo.ingest.repos import repo_name

    first, second = (
        "https://gitlab.example.com/alpha/team/api",
        "https://gitlab.example.com/beta/team/api",
    )
    assert repo_name(first) == repo_name(second) == "team/api"
    assert api.repository_descriptor(first) != api.repository_descriptor(second)


@pytest.mark.parametrize(
    "url",
    [
        "https://GitHub.com/Acme/Robots.git",
        "https://github.com/acme/robots",
        "https://github.com/acme/robots/",
        "ssh://git@github.com/acme/robots.git",
        "ssh://git@github.com:2222/acme/robots.git",
        "git@github.com:acme/robots.git",
        "http://github.com/acme/robots.git",
        "http://github.com:80/acme/robots",
        "https://github.com:443/acme/robots",
    ],
)
def test_transport_host_case_and_git_suffix_all_fold_to_one_identity(api, url):
    descriptor = api.repository_descriptor(url)
    assert descriptor.provider_instance == "https://github.com"
    assert descriptor.provider_repository_id == "acme/robots"


def test_a_nondefault_port_stays_part_of_the_provider_instance(api):
    descriptor = api.repository_descriptor("https://forge.example.com:8443/team/api.git")
    assert descriptor.provider_instance == "https://forge.example.com:8443"
    assert api.repository_descriptor("https://forge.example.com:443/team/api").provider_instance == (
        "https://forge.example.com"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com",
        "https://github.com/",
        "https://github.com/acme/../robots",
        "https://github.com/acme/./robots",
        "/local/path/repo",
        "file:///local/repo",
        "-oProxyCommand=evil",
        "https://github.com/acme/robots?x=1",
        "",
    ],
)
def test_a_url_with_no_honest_repository_path_refuses(api, url):
    with pytest.raises(api.CaptureRefused) as error:
        api.repository_descriptor(url)
    assert error.value.reason == "unsupported_repository_url"


def test_an_embedded_credential_refuses_and_never_reaches_the_message(api):
    with pytest.raises(api.CaptureRefused) as error:
        api.repository_descriptor("https://someone:s3cr3t-token@github.com/acme/robots.git")
    assert error.value.reason == "unsupported_repository_url"
    assert "s3cr3t-token" not in str(error.value) and "someone" not in str(error.value)


def test_an_archive_or_single_file_carries_no_repository_descriptor(api, raw_store, tmp_path):
    path = tree(tmp_path / "repo", {"solo.py": b"x = 1\n"}) / "solo.py"
    assert capture(api, raw_store, path).repository is None


def test_a_descriptor_on_something_that_is_not_a_checkout_refuses_before_any_raw_write(
    api, raw_store, tmp_path
):
    path = tree(tmp_path / "repo", {"solo.py": b"x = 1\n"}) / "solo.py"
    before = raw_object_count(tmp_path / "raw")
    with pytest.raises(api.CaptureRefused) as error:
        capture(
            api,
            raw_store,
            path,
            repository=api.repository_descriptor("https://github.com/acme/robots"),
        )
    assert error.value.reason == "repository_without_checkout"
    assert raw_object_count(tmp_path / "raw") == before


def test_the_repository_descriptor_is_carried_but_never_hashed(api, raw_store, tmp_path):
    files = {"pkg/mod.py": b"x = 1\n"}
    descriptor = api.repository_descriptor("https://github.com/acme/robots.git")
    plain = capture(api, raw_store, tree(tmp_path / "one", files))
    named = capture(api, raw_store, tree(tmp_path / "two", files), repository=descriptor)
    assert named.repository == descriptor
    assert plain.repository is None
    assert named.accepted.manifest.sha256 == plain.accepted.manifest.sha256


def test_the_descriptor_feeds_repository_identity_unchanged(api):
    from hippo.knowledge.identity import repository_identity

    descriptor = api.repository_descriptor("git@github.com:acme/robots.git")
    assert repository_identity(
        "workspace-one", descriptor.provider_instance, descriptor.provider_repository_id
    ) == repository_identity("workspace-one", "https://github.com", "acme/robots")
