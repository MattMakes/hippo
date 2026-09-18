"""Immutable raw bytes, tested only under temporary caller-selected roots."""

import hashlib
import importlib
import io
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, asdict
from threading import Event

import pytest


def module():
    try:
        return importlib.import_module("hippo.knowledge.raw_artifacts")
    except ModuleNotFoundError:
        pytest.fail("Raw artifact primitive is not implemented")


def storage(tmp_path, *, limit=1024):
    return module().RawArtifactStore(tmp_path / "raw", max_object_bytes=limit)


def overwrite(path, data):
    path.chmod(0o600)
    path.write_bytes(data)


def test_reference_is_portable_immutable_and_content_addressed(tmp_path):
    raw = storage(tmp_path)
    value = b"\x00original\r\n\xff"
    artifact = raw.put_bytes(value)
    assert artifact.sha256 == hashlib.sha256(value).hexdigest()
    assert artifact.byte_length == len(value)
    assert artifact.uri == "hippo-raw:sha256:" + artifact.sha256
    assert str(tmp_path) not in str(asdict(artifact))
    assert module().RawArtifact.from_uri(artifact.uri, byte_length=len(value)) == artifact
    with pytest.raises(FrozenInstanceError):
        artifact.byte_length = 0
    assert raw.read_bytes(artifact) == value
    assert module().RawArtifactStore(tmp_path / "another", max_object_bytes=1024).put_bytes(value) == artifact


def test_empty_bytes_are_real_content_and_duplicates_do_not_replace_inode(tmp_path):
    raw = storage(tmp_path)
    artifact = raw.put_bytes(b"")
    path = tmp_path / "raw" / artifact.sha256
    before = path.stat()
    assert raw.put_stream(io.BytesIO(b"")) == artifact
    after = path.stat()
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)
    assert raw.read_bytes(artifact) == b""
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("limit", [True, 1.0, "1024", 0, -1, None])
def test_object_limit_requires_an_explicit_positive_integer(tmp_path, limit):
    with pytest.raises(ValueError):
        storage(tmp_path, limit=limit)


@pytest.mark.parametrize(
    "uri",
    [
        "../payload",
        "file:///etc/passwd",
        "hippo-raw:sha256:" + "A" * 64,
        "hippo-raw:sha256:" + "a" * 64 + "/../x",
        "hippo-raw:sha256:" + "a" * 64 + "\n",
        "hippo-raw:sha256:%2f",
    ],
)
def test_reference_parser_never_interprets_arbitrary_paths(uri):
    with pytest.raises(ValueError):
        module().RawArtifact.from_uri(uri, byte_length=1)


def test_bounded_reads_and_short_writes_preserve_binary_content(tmp_path):
    value = bytes(range(256)) * 3
    requests = []

    class ShortReader(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 1025
            requests.append(size)
            return super().read(min(size, 7))

    class ShortWriter(io.BytesIO):
        def write(self, value):
            return super().write(value[:3])

    raw = storage(tmp_path)
    artifact = raw.put_stream(ShortReader(value))
    sink = ShortWriter()
    assert raw.copy_to(artifact, sink) == len(value)
    assert sink.getvalue() == value
    assert len(requests) > 1


def test_over_limit_or_failed_input_leaves_no_published_or_staging_file(tmp_path):
    raw = storage(tmp_path, limit=4)
    with pytest.raises(module().RawArtifactTooLarge):
        raw.put_stream(io.BytesIO(b"12345"))

    class BrokenReader:
        def __init__(self):
            self.calls = 0

        def read(self, size):
            self.calls += 1
            if self.calls == 1:
                return b"12"
            raise OSError("source vanished")

    with pytest.raises(OSError):
        raw.put_stream(BrokenReader())
    assert list((tmp_path / "raw").iterdir()) == []


def test_nonbinary_source_is_rejected_without_leaving_files(tmp_path):
    raw = storage(tmp_path)
    with pytest.raises(ValueError):
        raw.put_stream(io.StringIO("not bytes"))
    assert list((tmp_path / "raw").iterdir()) == []


def test_corrupt_existing_object_is_never_overwritten_or_emitted(tmp_path):
    raw = storage(tmp_path)
    artifact = raw.put_bytes(b"original")
    path = tmp_path / "raw" / artifact.sha256
    overwrite(path, b"corrupted")
    sink = io.BytesIO()
    with pytest.raises(module().RawArtifactCorrupt):
        raw.copy_to(artifact, sink)
    assert sink.getvalue() == b""
    with pytest.raises(module().RawArtifactCorrupt):
        raw.put_bytes(b"original")
    assert path.read_bytes() == b"corrupted"
    assert list(path.parent.iterdir()) == [path]


def test_same_length_corruption_and_wrong_length_metadata_emit_nothing(tmp_path):
    raw = storage(tmp_path)
    artifact = raw.put_bytes(b"original")
    wrong = module().RawArtifact.from_uri(artifact.uri, byte_length=1)
    sink = io.BytesIO()
    with pytest.raises(module().RawArtifactCorrupt):
        raw.copy_to(wrong, sink)
    overwrite(tmp_path / "raw" / artifact.sha256, b"altered!")
    with pytest.raises(module().RawArtifactCorrupt):
        raw.copy_to(artifact, sink)
    assert sink.getvalue() == b""


def test_object_symlink_is_never_followed_for_read_or_duplicate_write(tmp_path):
    raw = storage(tmp_path)
    value = b"outside"
    outside = tmp_path / "outside"
    outside.write_bytes(value)
    digest = hashlib.sha256(value).hexdigest()
    link = tmp_path / "raw" / digest
    link.symlink_to(outside)
    artifact = module().RawArtifact.from_uri("hippo-raw:sha256:" + digest, byte_length=len(value))
    with pytest.raises(ValueError):
        raw.read_bytes(artifact)
    with pytest.raises(ValueError):
        raw.put_bytes(value)
    assert outside.read_bytes() == value
    assert link.is_symlink()


def test_root_and_ancestor_symlinks_are_refused_without_creating_outside_files(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        module().RawArtifactStore(link / "raw", max_object_bytes=10)
    assert list(outside.iterdir()) == []
    with pytest.raises(ValueError):
        module().RawArtifactStore(link, max_object_bytes=10)


def test_replaced_root_cannot_redirect_an_existing_store(tmp_path):
    raw = storage(tmp_path)
    artifact = raw.put_bytes(b"value")
    (tmp_path / "raw").rename(tmp_path / "original-root")
    (tmp_path / "raw").mkdir()
    with pytest.raises(ValueError):
        raw.put_bytes(b"value")
    with pytest.raises(ValueError):
        raw.read_bytes(artifact)
    assert list((tmp_path / "raw").iterdir()) == []


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_nonregular_object_never_becomes_readable_content(tmp_path, kind):
    raw = storage(tmp_path)
    digest = hashlib.sha256(b"value").hexdigest()
    path = tmp_path / "raw" / digest
    if kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    artifact = module().RawArtifact.from_uri("hippo-raw:sha256:" + digest, byte_length=5)
    with pytest.raises(ValueError):
        raw.read_bytes(artifact)


def test_concurrent_identical_writers_publish_one_complete_object(tmp_path):
    raw = storage(tmp_path)
    value = b"concurrent" * 100
    with ThreadPoolExecutor(max_workers=4) as pool:
        artifacts = list(pool.map(raw.put_bytes, [value] * 4))
    assert len(set(artifacts)) == 1
    assert raw.read_bytes(artifacts[0]) == value
    assert len(list((tmp_path / "raw").iterdir())) == 1


def test_incomplete_writer_is_not_visible_before_atomic_publication(tmp_path):
    raw = storage(tmp_path)
    waiting, release = Event(), Event()

    class PausedReader(io.BytesIO):
        def read(self, size=-1):
            if self.tell() == 2:
                waiting.set()
                assert release.wait(10)
            return super().read(min(size, 2))

    artifact = module().RawArtifact.from_uri(
        "hippo-raw:sha256:" + hashlib.sha256(b"data").hexdigest(), byte_length=4
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(raw.put_stream, PausedReader(b"data"))
        try:
            assert waiting.wait(10)
            with pytest.raises(ValueError):
                raw.read_bytes(artifact)
        finally:
            release.set()
        assert writer.result(timeout=10) == artifact
    assert raw.read_bytes(artifact) == b"data"


def test_read_delivers_verified_spool_even_if_backing_object_changes_during_output(tmp_path):
    raw = storage(tmp_path)
    value = b"original" * 100
    artifact = raw.put_bytes(value)

    class MutatingWriter(io.BytesIO):
        def write(self, data):
            overwrite(tmp_path / "raw" / artifact.sha256, b"changed")
            return super().write(data)

    sink = MutatingWriter()
    assert raw.copy_to(artifact, sink) == len(value)
    assert sink.getvalue() == value


def test_atomic_publication_failure_removes_only_owned_staging(tmp_path, monkeypatch):
    raw = storage(tmp_path)
    prior = raw.put_bytes(b"keep")

    def fail(*args, **kwargs):
        raise OSError("injected publication failure")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(OSError):
        raw.put_bytes(b"new")
    assert raw.read_bytes(prior) == b"keep"
    assert {p.name for p in (tmp_path / "raw").iterdir()} == {prior.sha256}


def test_exact_limit_succeeds_and_smaller_reader_emits_nothing(tmp_path):
    raw = storage(tmp_path, limit=4)
    artifact = raw.put_stream(io.BytesIO(b"1234"))
    assert raw.read_bytes(artifact) == b"1234"
    smaller = storage(tmp_path, limit=3)
    sink = io.BytesIO()
    with pytest.raises(module().RawArtifactTooLarge):
        smaller.copy_to(artifact, sink)
    assert sink.getvalue() == b""


@pytest.mark.parametrize("length", [True, -1, 1.0, "1", None])
def test_reference_length_is_strict(length):
    with pytest.raises(ValueError):
        module().RawArtifact.from_uri("hippo-raw:sha256:" + "a" * 64, byte_length=length)


def test_reference_digest_cannot_disagree_with_uri():
    with pytest.raises(ValueError):
        module().RawArtifact(uri="hippo-raw:sha256:" + "a" * 64, sha256="b" * 64, byte_length=0)


@pytest.mark.parametrize("result", [None, 0, -1, True, 999])
def test_invalid_short_write_fails_without_altering_artifact(tmp_path, result):
    raw = storage(tmp_path)
    artifact = raw.put_bytes(b"value")

    class InvalidWriter:
        def write(self, data):
            return result

    with pytest.raises(ValueError):
        raw.copy_to(artifact, InvalidWriter())
    assert raw.read_bytes(artifact) == b"value"
    assert {p.name for p in (tmp_path / "raw").iterdir()} == {artifact.sha256}


def test_unbounded_input_response_is_rejected_without_publication(tmp_path):
    raw = storage(tmp_path, limit=4)

    class InvalidReader:
        def read(self, size):
            return b"x" * (size + 1)

    with pytest.raises(ValueError):
        raw.put_stream(InvalidReader())
    assert list((tmp_path / "raw").iterdir()) == []


def test_failed_write_preserves_unrelated_staging_file(tmp_path):
    raw = storage(tmp_path, limit=4)
    unrelated = tmp_path / "raw" / ".pending-unrelated"
    unrelated.write_bytes(b"belongs to another operation")
    with pytest.raises(module().RawArtifactTooLarge):
        raw.put_bytes(b"large")
    with pytest.raises(module().RawArtifactTooLarge):
        raw.put_stream(io.BytesIO(b"large"))
    assert unrelated.read_bytes() == b"belongs to another operation"
    assert list(unrelated.parent.iterdir()) == [unrelated]


@pytest.mark.parametrize("root", ["relative/root", "/private/../tmp/raw"])
def test_root_requires_explicit_absolute_location_without_parent_traversal(root):
    with pytest.raises(ValueError):
        module().RawArtifactStore(root, max_object_bytes=1)


def test_substituted_staging_name_never_returns_success_or_deletes_substitute(tmp_path, monkeypatch):
    raw = storage(tmp_path)
    real_link = os.link
    substituted = []

    def replace_before_link(source, destination, **kwargs):
        staged = tmp_path / "raw" / source
        staged.unlink()
        staged.write_bytes(b"wrong!!")
        substituted.append(staged)
        real_link(source, destination, **kwargs)

    monkeypatch.setattr(os, "link", replace_before_link)
    with pytest.raises(module().RawArtifactCorrupt):
        raw.put_bytes(b"correct")
    assert substituted[0].read_bytes() == b"wrong!!"


def test_source_failure_does_not_clean_substituted_staging_name(tmp_path):
    raw = storage(tmp_path)
    substituted = []

    class ReplacingReader:
        def read(self, size):
            (staged,) = (tmp_path / "raw").iterdir()
            staged.unlink()
            staged.write_bytes(b"unowned")
            substituted.append(staged)
            raise OSError("source failed after substitution")

    with pytest.raises(OSError, match="source failed"):
        raw.put_stream(ReplacingReader())
    assert substituted[0].read_bytes() == b"unowned"
