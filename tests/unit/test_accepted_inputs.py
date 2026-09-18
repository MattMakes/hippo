"""Accepted raw inputs use only explicit bytes and temporary local files."""

import importlib
import json
import os
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256

import pytest

from hippo.knowledge.raw_artifacts import RawArtifactStore


def api():
    try:
        return importlib.import_module("hippo.ingest.accepted_inputs")
    except ModuleNotFoundError:
        pytest.fail("Accepted raw input capture is not implemented")


def limits(**changes):
    return api().CaptureLimits(
        **(
            {"max_input_bytes": 1024, "max_total_bytes": 2048, "max_inputs": 8, "max_manifest_bytes": 10000}
            | changes
        )
    )


def capture(raw_store, inputs=(), **changes):
    args = {
        "source_id": "source-one",
        "workspace_id": "workspace-one",
        "inputs": inputs,
        "configuration": {"reader": {"profile": "plain-v1"}, "chunker": {"size": 1200}},
        "limits": limits(),
    }
    args.update(changes)
    return api().capture_raw_inputs(raw_store, **args)


@pytest.fixture
def raw_store(tmp_path):
    return RawArtifactStore(tmp_path / "raw", max_object_bytes=20000)


def test_capture_keeps_original_bytes_before_strip_and_stores_canonical_manifest(raw_store):
    data = b"\xef\xbb\xbf \r\noriginal\r\n\t"
    accepted = capture(raw_store, [api().ByteInput("text.md", data, media_type="text/markdown")])
    (item,) = accepted.inputs
    assert raw_store.read_bytes(item.raw_artifact) == data
    assert item.raw_hash == sha256(data).hexdigest() and item.byte_length == len(data)
    assert item.logical_path == "text.md" and item.provider_revision is None
    assert raw_store.read_bytes(accepted.manifest) == accepted.manifest_bytes
    manifest = json.loads(accepted.manifest_bytes)
    assert manifest["inputs"][0]["raw_hash"] == item.raw_hash
    assert manifest["source_id"] == "source-one"
    assert manifest["workspace_id"] == "workspace-one"
    assert accepted.outcome == "accepted"
    assert accepted.dispositions[0].outcome == "accepted"
    assert b"hippo-raw:" not in accepted.manifest_bytes
    with pytest.raises(FrozenInstanceError):
        accepted.source_id = "changed"


def test_root_path_and_configuration_dictionary_order_do_not_affect_identity(raw_store, tmp_path):
    first_path = tmp_path / "first.txt"
    second_path = tmp_path / "elsewhere.txt"
    first_path.write_bytes(b"same\r\n")
    second_path.write_bytes(b"same\r\n")
    first = capture(
        raw_store,
        [api().FileInput("notes.txt", first_path)],
        configuration={"reader": {"profile": "v1"}, "chunker": {"overlap": 2, "size": 20}},
    )
    other_store = RawArtifactStore(tmp_path / "other-root", max_object_bytes=20000)
    second = capture(
        other_store,
        [api().FileInput("notes.txt", second_path)],
        configuration={"chunker": {"size": 20, "overlap": 2}, "reader": {"profile": "v1"}},
    )
    assert first == second
    assert str(tmp_path).encode() not in first.manifest_bytes
    assert b"mtime" not in first.manifest_bytes and b"timestamp" not in first.manifest_bytes


def test_repeated_bytes_share_storage_but_keep_ordered_logical_and_source_identity(raw_store):
    inputs = [api().ByteInput("a.txt", b"same"), api().ByteInput("b.txt", b"same")]
    first = capture(raw_store, inputs)
    assert first.inputs[0].raw_artifact == first.inputs[1].raw_artifact
    assert first.inputs[0].input_key != first.inputs[1].input_key
    reversed_order = capture(raw_store, reversed(inputs))
    other_source = capture(raw_store, inputs, source_id="source-two")
    other_workspace = capture(raw_store, inputs, workspace_id="workspace-two")
    assert (
        len({result.manifest.sha256 for result in (first, reversed_order, other_source, other_workspace)})
        == 4
    )
    assert (
        first.inputs[0].input_key != other_source.inputs[0].input_key != other_workspace.inputs[0].input_key
    )


def test_reader_profile_changes_manifest_but_not_raw_input_identity(raw_store):
    inputs = [api().ByteInput("a.txt", b"content", provider_revision="upload-revision")]
    first = capture(raw_store, inputs, configuration={"reader": {"profile": "v1"}})
    second = capture(raw_store, inputs, configuration={"reader": {"profile": "v2"}})
    assert first.inputs == second.inputs
    assert first.manifest != second.manifest
    assert first.inputs[0].provider_revision == "upload-revision"


def test_empty_all_excluded_and_zero_byte_input_are_distinct_successes(raw_store):
    empty = capture(raw_store)
    excluded = capture(raw_store, [api().ExcludedInput("skip.txt")])
    zero = capture(raw_store, [api().ByteInput("empty.txt", b"")])
    assert [r.outcome for r in (empty, excluded, zero)] == ["empty_inventory", "all_excluded", "accepted"]
    assert empty.inputs == excluded.inputs == ()
    assert len(excluded.dispositions) == 1 and excluded.dispositions[0].reason == "configured_exclusion"
    assert zero.inputs[0].byte_length == 0
    assert len({r.manifest.sha256 for r in (empty, excluded, zero)}) == 3


@pytest.mark.parametrize("field", ["max_input_bytes", "max_total_bytes", "max_inputs", "max_manifest_bytes"])
@pytest.mark.parametrize("value", [True, 0, -1, 1.0, None])
def test_capture_limits_are_explicit_positive_integers(field, value):
    with pytest.raises(ValueError):
        limits(**{field: value})


def test_total_budget_charges_repeated_content_and_exclusions_charge_inventory_count(raw_store):
    inputs = [api().ByteInput("a.txt", b"123"), api().ByteInput("b.txt", b"123")]
    with pytest.raises(api().CaptureTooLarge):
        capture(raw_store, inputs, limits=limits(max_total_bytes=5))
    with pytest.raises(api().CaptureTooLarge):
        capture(raw_store, [api().ExcludedInput("a"), api().ExcludedInput("b")], limits=limits(max_inputs=1))
    good = capture(raw_store, inputs, limits=limits(max_total_bytes=6, max_input_bytes=3))
    assert good.total_bytes == 6


def test_duplicate_normalized_paths_reject_even_when_excluded(raw_store):
    with pytest.raises(ValueError, match="Duplicate"):
        capture(raw_store, [api().ByteInput("a/./b.txt", b"1"), api().ExcludedInput("a/b.txt")])


@pytest.mark.parametrize("name", ["a.zip", "a.tar", "a.tar.gz", "a.tgz", "a.7z"])
def test_container_input_is_explicitly_unsupported_not_an_empty_capture(raw_store, name):
    with pytest.raises(api().UnsupportedCaptureInput):
        capture(raw_store, [api().ByteInput(name, b"not a supported container")])


def test_rich_single_file_capture_retains_bytes_without_claiming_reader_coverage(raw_store):
    result = capture(raw_store, [api().ByteInput("a.pdf", b"raw PDF bytes", media_type="application/pdf")])
    assert raw_store.read_bytes(result.inputs[0].raw_artifact) == b"raw PDF bytes"
    assert b"page" not in result.manifest_bytes


def test_configuration_is_snapshotted_before_streaming_io(raw_store, tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"data")
    config = {"reader": {"profile": "original"}}

    class ChangingSink:
        def put_stream(self, stream):
            config["reader"]["profile"] = "changed during I/O"
            return raw_store.put_stream(stream)

        def put_bytes(self, data):
            return raw_store.put_bytes(data)

    accepted = capture(ChangingSink(), [api().FileInput("a.txt", path)], configuration=config)
    assert json.loads(accepted.configuration_json) == {"reader": {"profile": "original"}}
    assert b"changed during I/O" not in accepted.manifest_bytes


@pytest.mark.parametrize(
    "configuration",
    [
        {"bad": float("nan")},
        {"bad": float("inf")},
        {"bad": object()},
        {"bad": {1: "non-string key"}},
        '{"reader":1,"reader":2}',
    ],
)
def test_configuration_rejects_noncanonical_or_whole_object_inputs_before_io(
    raw_store, configuration, tmp_path
):
    with pytest.raises(ValueError):
        capture(raw_store, [api().ByteInput("a.txt", b"value")], configuration=configuration)
    assert list((tmp_path / "raw").iterdir()) == []


def test_manifest_configuration_and_descriptor_size_are_bounded_before_capture(raw_store, tmp_path):
    with pytest.raises(api().CaptureTooLarge):
        capture(
            raw_store,
            [api().ByteInput("a.txt", b"value")],
            configuration={"reader": "x" * 10000},
            limits=limits(max_manifest_bytes=1000),
        )
    assert list((tmp_path / "raw").iterdir()) == []


def test_missing_input_fails_whole_capture_without_success_manifest(raw_store, tmp_path):
    with pytest.raises(api().InputCaptureError) as caught:
        capture(
            raw_store,
            [api().ByteInput("good.txt", b"good"), api().FileInput("missing.txt", tmp_path / "missing")],
        )
    assert caught.value.dispositions[-1].outcome == "failed"
    assert caught.value.dispositions[-1].reason == "unreadable"
    # Immutable blobs already captured are retained conservatively; no successful manifest exists.
    assert {p.name for p in (tmp_path / "raw").iterdir()} == {sha256(b"good").hexdigest()}


@pytest.mark.parametrize("kind", ["symlink", "ancestor_symlink", "directory", "fifo"])
def test_file_capture_refuses_symlink_traversal_and_nonregular_files(raw_store, tmp_path, kind):
    target = tmp_path / "actual.txt"
    target.write_bytes(b"retained")
    path = tmp_path / "input"
    if kind == "symlink":
        path.symlink_to(target)
    elif kind == "ancestor_symlink":
        folder = tmp_path / "actual"
        folder.mkdir()
        (folder / "input").write_bytes(b"retained")
        path.symlink_to(folder, target_is_directory=True)
        path = path / "input"
    elif kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    with pytest.raises(api().InputCaptureError):
        capture(raw_store, [api().FileInput("input.txt", path)])
    assert target.read_bytes() == b"retained"


def test_changed_descriptor_during_capture_fails_instead_of_attesting_mixed_bytes(raw_store, tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"first")

    class ChangingSink:
        def put_stream(self, stream):
            result = raw_store.put_stream(stream)
            path.write_bytes(b"other bytes")
            return result

        def put_bytes(self, data):
            return raw_store.put_bytes(data)

    with pytest.raises(api().InputCaptureError) as caught:
        capture(ChangingSink(), [api().FileInput("a.txt", path)])
    assert caught.value.dispositions[-1].reason == "changed_during_capture"


def test_cancellation_before_or_during_stream_never_returns_partial_success(raw_store, tmp_path):
    with pytest.raises(api().CaptureCancelled):
        capture(raw_store, [api().ByteInput("a.txt", b"value")], should_stop=lambda: True)
    path = tmp_path / "a.txt"
    path.write_bytes(b"content")
    cancelled = False

    class CancellingSink:
        def put_stream(self, stream):
            nonlocal cancelled
            cancelled = True
            return raw_store.put_stream(stream)

        def put_bytes(self, data):
            return raw_store.put_bytes(data)

    with pytest.raises(api().CaptureCancelled):
        capture(CancellingSink(), [api().FileInput("a.txt", path)], should_stop=lambda: cancelled)
    assert list((tmp_path / "raw").iterdir()) == []


def test_invalid_reference_or_mutable_nested_inventory_cannot_forge_accepted_values(raw_store):
    accepted = capture(raw_store, [api().ByteInput("a.txt", b"value")])
    with pytest.raises(ValueError):
        replace(accepted, source_id="another-source")
    with pytest.raises(ValueError):
        replace(accepted, manifest=accepted.inputs[0].raw_artifact)
    with pytest.raises(ValueError):
        replace(accepted, inputs=({"mutable": True},))


def test_manifest_limit_accepts_the_exact_canonical_byte_length(raw_store):
    inputs = [api().ByteInput("a.txt", b"value")]
    original = capture(raw_store, inputs)
    document = json.loads(original.manifest_bytes)
    bound = len(original.manifest_bytes)
    while document["limits"]["max_manifest_bytes"] != bound:
        document["limits"]["max_manifest_bytes"] = bound
        bound = len(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    accepted = capture(raw_store, inputs, limits=limits(max_manifest_bytes=bound))
    assert len(accepted.manifest_bytes) == bound


@pytest.mark.parametrize(("origin", "reason"), [("storage", "storage_failure"), ("source", "unreadable")])
def test_input_read_and_storage_write_errors_have_distinct_diagnostics(
    raw_store, tmp_path, monkeypatch, origin, reason
):
    from contextlib import contextmanager

    path = tmp_path / "a.txt"
    path.write_bytes(b"original")
    if origin == "storage":

        class FailedSink:
            def put_stream(self, stream):
                raise OSError("raw volume is full")

        sink = FailedSink()
    else:
        original_open = api()._open_file

        @contextmanager
        def broken_read(path):
            with original_open(path) as underlying:

                class FailedSource:
                    def fileno(self):
                        return underlying.fileno()

                    def read(self, size):
                        raise OSError("input device failed")

                yield FailedSource()

        monkeypatch.setattr(api(), "_open_file", broken_read)
        sink = raw_store
    with pytest.raises(api().InputCaptureError) as caught:
        capture(sink, [api().FileInput("a.txt", path)])
    assert caught.value.dispositions[-1].reason == reason
    assert list((tmp_path / "raw").iterdir()) == []
