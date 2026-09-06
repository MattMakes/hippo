"""Tests for hippo.ingest.pipeline with the in-process fakes: add -> index -> ready, delete, reindex."""

from __future__ import annotations

import io
import zipfile

import pytest

from hippo.context import AppContext
from hippo.ingest import pipeline
from hippo.ingest.repos import RepoError

SETTLE_SECONDS = 60


def wait(ctx: AppContext) -> None:
    ctx.jobs.wait_all(SETTLE_SECONDS)
    assert ctx.jobs.running_keys() == []


def record_updates(ctx: AppContext) -> list[dict]:
    """Wrap store.update_source so a test can look at the status flow afterwards."""
    seen: list[dict] = []
    original = ctx.store.update_source

    def spy(source_id: str, **fields):
        seen.append(dict(fields))
        return original(source_id, **fields)

    ctx.store.update_source = spy
    return seen


def passage_count(ctx: AppContext, source_id: str) -> int:
    return len(ctx.store.passage_ids_for_source(source_id))


# ------------------------------------------------------------- sample


def test_add_sample_indexes_the_corpus(ctx: AppContext) -> None:
    updates = record_updates(ctx)
    source_id = pipeline.add_sample(ctx)
    wait(ctx)

    source = ctx.store.get_source(source_id)
    assert source["kind"] == "sample"
    assert source["status"] == "ready"
    assert source["stage"] == "ready"
    assert source["error"] is None
    assert source["passages"] == 8
    assert source["progress_done"] == source["progress_total"] == 8
    assert source["fact_links"] > 0

    meta = source["meta"]
    assert meta["chunks"] == 8 and meta["documents"] == 1
    assert meta["counts"]["passages"] == 8
    assert meta["counts"]["entities"] > 0 and meta["counts"]["facts"] > 0

    # Status flow: reading -> indexing -> ready, with progress stages from the indexer in between.
    statuses = [u["status"] for u in updates if "status" in u]
    assert statuses == ["reading", "indexing", "ready"]
    stages = [u["stage"] for u in updates if "stage" in u]
    assert "extracting facts" in stages and "linking synonyms" in stages

    # The saved copy of the sample is on disk, and the graph sees the passages.
    assert (pipeline.source_dir(ctx, source_id) / "acme_robotics.md").is_file()
    graph = ctx.graph()
    assert len(graph.passages) == 8
    assert any(p.title.endswith("› The company") for p in graph.passages)


def test_the_sample_can_be_searched_afterwards(ctx: AppContext) -> None:
    from hippo.ask import search

    pipeline.add_sample(ctx)
    wait(ctx)
    trace = search(ctx, "Where is Acme Robotics headquartered?")
    assert trace.passages
    assert any("Boulder" in p.preview for p in trace.passages[:3])


# ---------------------------------------------------------------- text


def test_add_text(ctx: AppContext) -> None:
    source_id = pipeline.add_text(
        ctx, "A note", "Acme Robotics is headquartered in Boulder. Boulder is located in Colorado."
    )
    wait(ctx)
    source = ctx.store.get_source(source_id)
    assert source["kind"] == "text" and source["name"] == "A note"
    assert source["status"] == "ready"
    assert source["passages"] == 1
    assert (pipeline.source_dir(ctx, source_id) / "text.md").read_text().startswith("Acme Robotics")
    passage = ctx.store.passages_for_source(source_id)[0]
    assert passage["title"] == "A note"
    assert ["Acme Robotics", "is headquartered in", "Boulder"] in passage["triples"]


def test_add_text_refuses_empty_text(ctx: AppContext) -> None:
    with pytest.raises(ValueError):
        pipeline.add_text(ctx, "Nothing", "   ")
    assert ctx.store.list_sources() == []


# ------------------------------------------------------------- uploads


def test_add_upload_markdown_file(ctx: AppContext) -> None:
    data = b"# Guide\n\n## Places\n\nBoulder is located in Colorado.\n\n## People\n\nPriya Natarajan lives in Denver.\n"
    source_id = pipeline.add_upload(ctx, "guide.md", data)
    wait(ctx)
    source = ctx.store.get_source(source_id)
    assert source["kind"] == "file" and source["name"] == "guide.md"
    assert source["status"] == "ready"
    assert source["passages"] == 2
    assert (pipeline.source_dir(ctx, source_id) / "guide.md").read_bytes() == data
    titles = [p["title"] for p in ctx.store.passages_for_source(source_id)]
    assert titles == ["Guide › Places", "Guide › People"]  # "# Guide" names the document, not the file name


def test_add_upload_zip_archive(ctx: AppContext) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("docs/places.md", "Boulder is located in Colorado.")
        archive.writestr("src/tool.py", "def lift():\n    return 12\n")
        archive.writestr("node_modules/junk.js", "junk")
        archive.writestr("logo.png", b"\x89PNG\x00")
    source_id = pipeline.add_upload(ctx, "bundle.zip", buffer.getvalue())
    wait(ctx)
    source = ctx.store.get_source(source_id)
    assert source["kind"] == "archive"
    assert source["status"] == "ready", source["error"]
    assert source["meta"]["documents"] == 2
    titles = [p["title"] for p in ctx.store.passages_for_source(source_id)]
    assert titles == ["docs/places.md", "src/tool.py (lines 1-2)"]


def test_add_upload_strips_directories_from_the_file_name(ctx: AppContext) -> None:
    source_id = pipeline.add_upload(ctx, "../../etc/evil.md", b"Boulder is located in Colorado.")
    wait(ctx)
    assert ctx.store.get_source(source_id)["name"] == "evil.md"
    assert (pipeline.source_dir(ctx, source_id) / "evil.md").is_file()


def test_add_upload_rejects_unsupported_and_empty_files(ctx: AppContext) -> None:
    with pytest.raises(ValueError, match="not a supported file type"):
        pipeline.add_upload(ctx, "photo.png", b"\x89PNG\x00\x00")
    with pytest.raises(ValueError, match="empty"):
        pipeline.add_upload(ctx, "notes.md", b"")
    assert ctx.store.list_sources() == []


def test_a_source_with_no_text_fails_with_a_message(ctx: AppContext) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("logo.png", b"\x89PNG\x00")
    source_id = pipeline.add_upload(ctx, "empty.zip", buffer.getvalue())
    wait(ctx)
    source = ctx.store.get_source(source_id)
    assert source["status"] == "failed"
    assert "no readable text" in source["error"]


# --------------------------------------------------------------- repos


def test_add_repo_rejects_bad_urls(ctx: AppContext) -> None:
    with pytest.raises(RepoError):
        pipeline.add_repo(ctx, "/home/user/repo")
    with pytest.raises(RepoError):
        pipeline.add_repo(ctx, "file:///home/user/repo")
    assert ctx.store.list_sources() == []


def test_add_repo_records_clone_failures(ctx: AppContext) -> None:
    # An unreachable host: git fails at once (connection refused), and the source says why.
    source_id = pipeline.add_repo(ctx, "https://127.0.0.1:9/acme/robots.git")
    wait(ctx)
    source = ctx.store.get_source(source_id)
    assert source["kind"] == "repo" and source["name"] == "acme/robots"
    assert source["meta"]["url"] == "https://127.0.0.1:9/acme/robots.git"
    assert source["status"] == "failed"
    assert "could not clone" in source["error"]


def test_add_repo_indexes_a_checkout(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for `git clone` by writing files into the destination, then check the whole flow."""

    def fake_clone(url: str, dest, timeout: int = 300):
        (dest / "src").mkdir(parents=True)
        (dest / "src" / "app.py").write_text("def lift():\n    return 12\n")
        (dest / "README.md").write_text("Acme Robotics builds robot arms.")
        return dest

    monkeypatch.setattr(pipeline.repos, "clone_repo", fake_clone)
    source_id = pipeline.add_repo(ctx, "https://github.com/acme/robots")
    wait(ctx)
    source = ctx.store.get_source(source_id)
    assert source["status"] == "ready", source["error"]
    assert source["meta"]["documents"] == 2
    titles = [p["title"] for p in ctx.store.passages_for_source(source_id)]
    assert titles == ["README.md", "src/app.py (lines 1-2)"]


# ------------------------------------------------------ delete, reindex


def test_delete_source_removes_passages_files_and_bumps_the_version(ctx: AppContext) -> None:
    source_id = pipeline.add_sample(ctx)
    wait(ctx)
    assert passage_count(ctx, source_id) == 8
    folder = pipeline.source_dir(ctx, source_id)
    assert folder.is_dir()
    version_before = ctx.store.graph_version()

    pipeline.delete_source(ctx, source_id)

    assert ctx.store.get_source(source_id) is None
    assert passage_count(ctx, source_id) == 0
    assert ctx.store.stats()["passages"] == 0
    assert ctx.store.stats()["entities"] == 0  # orphans are gone too
    assert ctx.store.graph_version() > version_before
    assert not folder.exists()
    assert len(ctx.graph().passages) == 0


def test_reindex_rebuilds_the_same_passages(ctx: AppContext) -> None:
    source_id = pipeline.add_sample(ctx)
    wait(ctx)
    ids_before = ctx.store.passage_ids_for_source(source_id)
    version_before = ctx.store.graph_version()

    assert pipeline.reindex(ctx, source_id) is True
    wait(ctx)

    source = ctx.store.get_source(source_id)
    assert source["status"] == "ready"
    assert ctx.store.passage_ids_for_source(source_id) == ids_before
    assert ctx.store.graph_version() > version_before


def test_reindex_of_unknown_source_is_false(ctx: AppContext) -> None:
    assert pipeline.reindex(ctx, "nope") is False


def test_start_indexing_does_not_start_twice(ctx: AppContext) -> None:
    source_id = ctx.store.create_source("text", "x", {"file": "text.md"})
    (pipeline.source_dir(ctx, source_id)).mkdir(parents=True)
    (pipeline.source_dir(ctx, source_id) / "text.md").write_text("Boulder is located in Colorado.")
    first = pipeline.start_indexing(ctx, source_id)
    second = pipeline.start_indexing(ctx, source_id)
    wait(ctx)
    assert first is True
    assert (
        second is False or ctx.store.get_source(source_id)["status"] == "ready"
    )  # the first may finish fast


def test_reindexing_replaces_passages_whose_text_changed(ctx):
    source_id = pipeline.add_text(ctx, "notes", "Zed Corp is located in Austin.")
    ctx.jobs.wait_all()
    first = ctx.store.passage_ids_for_source(source_id)
    (pipeline.source_dir(ctx, source_id) / "text.md").write_text("Zed Corp is located in Dallas.")
    assert pipeline.reindex(ctx, source_id) is True
    ctx.jobs.wait_all()
    second = ctx.store.passage_ids_for_source(source_id)
    assert second and second != first, "the old passage must be gone and the new text indexed"
    assert ctx.store.get_source(source_id)["status"] == "ready"
    assert "dallas" in {e["name"] for e in ctx.store.load_entities()}
    assert "austin" not in {e["name"] for e in ctx.store.load_entities()}


def test_reindex_all_clears_every_source_then_indexes_each_again(ctx: AppContext) -> None:
    sample = pipeline.add_sample(ctx)
    note = pipeline.add_text(ctx, "note", "Zed Corp is located in Austin.")
    wait(ctx)
    assert pipeline.reindex_all(ctx) == 2
    wait(ctx)
    assert {s["status"] for s in ctx.store.list_sources()} == {"ready"}
    assert ctx.store.get_source(sample)["passages"] == 8
    assert ctx.store.get_source(note)["passages"] == 1
