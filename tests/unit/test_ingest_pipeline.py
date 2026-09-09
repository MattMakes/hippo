"""Tests for hippo.ingest.pipeline with the in-process fakes: add -> index -> ready, delete, reindex."""

from __future__ import annotations

import io
import subprocess
import zipfile

import pytest

from hippo.context import AppContext
from hippo.ingest import pipeline
from hippo.ingest.repos import RepoError
from hippo.store.base import DEFAULT_SETTINGS
from tests.conftest import CODE_CHECKOUT_SUBJECTS, git_env, make_code_checkout

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
    assert titles == ["docs/places.md", "src/tool.py :: src.tool.lift (lines 1-2)"]


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

    def fake_clone(url: str, dest, timeout: int = 300, depth: int = 1):
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
    assert titles == ["README.md", "src/app.py :: src.app.lift (lines 1-2)"]


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


# ------------------------------------------------------- a source with code


def test_a_code_archive_is_parsed_chunked_by_symbol_and_recorded_in_meta(code_index) -> None:
    ctx, source_id = code_index
    source = ctx.store.get_source(source_id)
    code = source["meta"]["code"]

    assert (code["symbols"], code["data_objects"], code["edges"]) == (54, 12, 110)
    assert code["edges_by_kind"] == {
        "CATCHES": 1,
        "CONTAINS": 43,
        "IMPORTS": 18,
        "INHERITS": 3,
        "INVOKES": 19,
        "OVERRIDES": 2,
        "RAISES": 3,
        "READS": 10,
        "TESTED_BY": 7,
        "WRITES": 4,
    }
    assert code["files_parsed"] == 17  # six Python, three TypeScript, six Rust, one .sql, one Go
    assert code["files_skipped"] == {"parse_error": 0, "too_big": 0, "unsupported": 1}  # build.rb
    assert code["truncated"] is False
    # Calls that resolve to nothing in the repo -- builtins included -- are counted per file, so
    # phase 2 has a baseline to work from (D15). Only parsed files can have any.
    assert set(code["unresolved_calls"]) <= set(code_sample_paths())
    assert code["unresolved_calls_total"] == sum(code["unresolved_calls"].values())
    assert source["meta"]["counts"]["symbols"] == 54


def test_a_code_archive_gets_symbol_titled_passages(code_index) -> None:
    ctx, source_id = code_index
    titles = [p["title"] for p in ctx.store.passages_for_source(source_id, limit=500)]
    assert "pyapp/orders.py :: pyapp.orders.OrderService.place (lines 16-23)" in titles
    # Rust writes a type's methods outside it, so the struct's own passage is its own lines (L3).
    assert "rsapp/src/orders.rs :: rsapp.src.orders.OrderService (lines 7-9)" in titles
    assert "rsapp/src/orders.rs :: rsapp.src.orders.OrderService.place (lines 19-24)" in titles
    assert "schema/orders.sql (lines 1-2)" in titles  # no symbols to cut by; windows as before
    assert "tools/build.rb (lines 1-3)" in titles  # no grammar; windows as before
    assert "tools/build.go :: tools.build.main (lines 3-3)" in titles  # Go parses now
    assert not any(t == "pyapp/orders.py (lines 1-40)" for t in titles)


def test_deleting_a_code_source_removes_its_symbols_and_data_objects(code_index) -> None:
    ctx, source_id = code_index
    assert len(ctx.store.load_symbols()) == 54

    pipeline.delete_source(ctx, source_id)

    assert ctx.store.load_symbols() == []
    assert ctx.store.load_data_objects() == []
    assert ctx.store.load_code_edges() == []


def code_sample_paths() -> list[str]:
    """Every file of the fixture tree, as the archive titles it."""
    from tests.conftest import CODE_SAMPLE_PATH

    return [
        p.relative_to(CODE_SAMPLE_PATH).as_posix()
        for p in CODE_SAMPLE_PATH.rglob("*")
        if p.is_file() and p.name != "expected.json"
    ]


# ------------------------------------------------------ repo history (WP2b)


def test_a_repo_source_indexes_its_git_history(git_index) -> None:
    ctx, source_id, _ = git_index
    code = ctx.store.get_source(source_id)["meta"]["code"]

    assert (code["commits"], code["history_skipped"]) == (3, 0)
    assert code["modifies"] > 0
    assert ctx.store.stats()["commits"] == 3
    # The whole point: a commit is reachable from the symbol it changed, on every backend.
    commits = {c["id"]: c for c in ctx.store.load_commits()}
    assert {c["ordinal"] for c in commits.values()} == {0, 1, 2}
    symbols = {s["id"]: s for s in ctx.store.load_symbols()}
    touched = {
        (commits[m["commit_id"]]["ordinal"], symbols[m["symbol_id"]]["qualname"])
        for m in ctx.store.load_modifies()
    }
    assert (1, "OrderService.place") in touched
    assert (1, "OrderService") not in touched  # innermost only, S2.9
    assert [(a["a"], a["b"]) for a in ctx.store.load_precedes()] == [
        (o[0], o[1])
        for o in zip(
            [c["id"] for c in sorted(commits.values(), key=lambda c: c["ordinal"])],
            [c["id"] for c in sorted(commits.values(), key=lambda c: c["ordinal"])][1:],
            strict=False,
        )
    ]


def test_a_commit_gets_a_passage_of_its_own(git_index) -> None:
    ctx, source_id, _ = git_index
    titles = [p["title"] for p in ctx.store.passages_for_source(source_id, limit=500)]
    assert "commit " in "".join(titles)
    subjects = sorted(t.split(": ", 1)[1] for t in titles if t.startswith("commit "))
    assert subjects == sorted(CODE_CHECKOUT_SUBJECTS)
    # DEFINED_IN: the commit node is reachable from its passage, like every other code node.
    passage_ids = {
        c["id"]: c["passage_ids"] for c in ctx.store.get_commits([c["id"] for c in ctx.store.load_commits()])
    }
    assert all(len(ids) == 1 for ids in passage_ids.values())


def test_the_history_depth_setting_reaches_git_and_zero_disables_history(ctx, tmp_path, monkeypatch) -> None:
    from hippo.ingest import pipeline, repos

    checkout = make_code_checkout(tmp_path / "origin")
    seen: list[int] = []

    def clone_locally(url, dest, timeout=300, depth=1):
        seen.append(depth)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "-q", "--depth", str(depth), "--single-branch", "--", url, str(dest)],
            check=True,
            env=git_env(),
        )
        return dest

    monkeypatch.setattr(repos, "clone_repo", clone_locally)
    ctx.store.update_settings({"code_history_depth": 0})
    source_id = ctx.store.create_source("repo", "no history", {"url": f"file://{checkout}"})
    pipeline.source_dir(ctx, source_id).mkdir(parents=True, exist_ok=True)
    pipeline.run_indexing(ctx, source_id)

    code = ctx.store.get_source(source_id)["meta"]["code"]
    assert (code["commits"], code["modifies"]) == (0, 0)
    assert ctx.store.stats()["commits"] == 0
    assert code["symbols"] > 0  # the code graph itself is unaffected
    assert seen == [1]  # history off still clones, but only the tip


def test_history_depth_clones_one_commit_deeper_than_it_reads(git_index) -> None:
    # A shallow clone's oldest commit reports no parent, so its diff would be taken against the
    # empty tree and it would look like the commit that added the whole repository. Fetching one
    # extra commit puts that boundary outside the walk instead.
    _, _, depths = git_index
    assert depths == [DEFAULT_SETTINGS["code_history_depth"] + 1]


def test_a_broken_history_read_does_not_fail_the_whole_index_job(
    ctx: AppContext, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # E1F-a / Defect 1's defence in depth: whatever `read_history` raises -- not just
    # `HistoryError` -- must degrade to a warning and an empty history, never a failed job
    # with the code graph and passages already written thrown away.
    from hippo.codegraph import git_history
    from hippo.ingest import pipeline, repos

    checkout = make_code_checkout(tmp_path / "origin")

    def clone_locally(url, dest, timeout=300, depth=1):
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "-q", "--depth", str(depth), "--single-branch", "--", url, str(dest)],
            check=True,
            env=git_env(),
        )
        return dest

    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(repos, "clone_repo", clone_locally)
    monkeypatch.setattr(git_history, "read_history", broken)
    source_id = ctx.store.create_source("repo", "broken history", {"url": f"file://{checkout}"})
    pipeline.source_dir(ctx, source_id).mkdir(parents=True, exist_ok=True)
    pipeline.run_indexing(ctx, source_id)

    source = ctx.store.get_source(source_id)
    assert source["status"] == "ready", source["error"]
    code = source["meta"]["code"]
    assert code["symbols"] > 0  # the code graph itself is unaffected
    assert (code["commits"], code["modifies"], code["history_skipped"]) == (0, 0, 0)
    assert ctx.store.stats()["commits"] == 0


def test_a_repo_source_still_links_its_prose_to_its_code(git_index) -> None:
    # The README names `OrderService.place` in backticks and "the order service" in words. Both
    # become REFERS_TO, at the two omegas the table gives -- a repo source is a code source and a
    # prose source at once, and reading its history must not have cost it the prose half.
    ctx, source_id, _ = git_index
    symbols = {s["id"]: s["qualname"] for s in ctx.store.load_symbols()}
    titles = {p["id"]: p["title"] for p in ctx.store.passages_for_source(source_id, limit=500)}
    found = {
        (titles[r["passage_id"]], symbols[r["node_id"]], r["omega"], r["token"])
        for r in ctx.store.load_refers_to()
        if r["node_id"] in symbols and r["passage_id"] in titles
    }
    assert ("Code sample", "OrderService.place", 0.85, "OrderService.place") in found
    assert ("Code sample", "OrderService", 0.6, "order service") in found


def test_a_commit_passage_is_scanned_for_the_symbols_its_message_names(git_index) -> None:
    # `_is_prose` counts a commit passage as prose, so "Add the order service" is scanned exactly
    # as the README is -- and reaches `OrderService` by the same split-token rule, at 0.60. That
    # is the whole reason a commit becomes a passage rather than only a node.
    ctx, source_id, _ = git_index
    commit_ids = {c["id"] for c in ctx.store.load_commits()}
    commit_passages = {
        p["id"]: p["title"]
        for p in ctx.store.passages_for_source(source_id, limit=500)
        if p["title"].startswith("commit ")
    }
    assert len(commit_passages) == 3
    assert commit_ids and all(
        set(c["passage_ids"]) <= set(commit_passages) for c in ctx.store.get_commits(sorted(commit_ids))
    )

    symbols = {s["id"]: s["qualname"] for s in ctx.store.load_symbols()}
    from_commits = {
        (commit_passages[r["passage_id"]].split(": ", 1)[1], symbols[r["node_id"]], r["omega"], r["token"])
        for r in ctx.store.load_refers_to()
        if r["passage_id"] in commit_passages and r["node_id"] in symbols
    }
    assert ("Add the order service", "OrderService", 0.6, "order service") in from_commits
    # And only from the message. The `Touched:` line is hippo's own writing, built from this
    # source's MODIFIES edges: scanning it back out would invent a REFERS_TO for every pair
    # MODIFIES already has, at a lower omega than the edge it was derived from.
    assert not [row for row in from_commits if row[3].startswith("pyapp.")]


def test_a_symbol_carries_the_commits_that_touched_it_all_the_way_to_an_answer(git_index) -> None:
    """The whole chain on a real repository: git -> store -> GraphIndex -> the answer block.

    WP3's three tests use `tests/fakes/code_fixture.write_commit_history`, a store-built stand-in
    with seven-character shas. That is the cleaner test for the block's grammar, and it stays --
    but nothing there would notice if a real 40-character sha reached the page whole, or if an
    ISO date did. This is the test that would.
    """
    from hippo import ask

    ctx, source_id, _ = git_index
    # Fully qualified: `OrderService.place` is a qualname in `pyapp/orders.py` and in
    # `rsapp/src/orders.rs`, and a dotted name is never split (S2.13), so the short form would
    # seed both trees and fill the block with Rust relations before the commits were reached.
    trace = ask.search(ctx, "What does pyapp.orders.OrderService.place do?")
    assert trace.used_code_seeds
    assert trace.history, "a seeded symbol with MODIFIES edges must carry its commits"
    row = trace.history[0]
    # The trace keeps the real, whole sha -- it is what a reader would paste into `git show`.
    assert len(row["sha"]) == 40
    assert row["date"] == "2024-01-02"  # the day, not the full ISO timestamp
    assert row["subject"] == "Total, invoice and log in place"

    answer = ask.answer_from_trace(ctx, trace)
    line = next(ln for ln in answer.context_block.splitlines() if ln.startswith("Commits: "))
    assert line == f"Commits: {row['sha'][:7]} 2024-01-02 Total, invoice and log in place"
    assert row["sha"] not in answer.context_block  # shortened for the page, whole in the trace
