"""Activation dispatch for code sources: repositories, archives and code files (gate CD8).

CC9b proved the code coordinator on a checkout it was handed. This suite proves the part in
front of it. The saved Source row decides the lane. An authenticated actor's `add_repo`,
`add_upload`, `reindex`, `reindex_all` and `delete_source` reach `build_code_source` by kind,
with a checkout this lane owns. Actorless callers and unsupported kinds stay exactly
legacy. And a managed or converting code source never reaches a legacy cleanup:
`_prepare_reindex`, `_clear_passages`, the store's source-wide deletes, `remove_orphans`,
generation collection, `shutil.rmtree` on the source directory, or a raw unlink.

Real builds are few on purpose -- one repository bootstrap, one repository conversion, one
archive conversion and one code file -- because CC9b measured ~45 s per build on LadybugDB.
Everything that is about *which* coordinator is reached spies `build_code_source` instead.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import zipfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event, local
from types import SimpleNamespace

import httpx
import pytest

from hippo.access import Principal
from hippo.ingest import managed_activation, pipeline, repos
from hippo.ingest.build_run import BuildProgress, BuildReceipt
from hippo.ingest.code_generation import CodeBuildOptions, CodeBuildRefused, CodeTreeInput
from hippo.ingest.repo_capture import CaptureRefused, repository_descriptor
from hippo.knowledge import model as k
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.embedding_cache import EmbeddingCache
from hippo.knowledge.public_errors import INVALID_SOURCE_TYPE, OPERATION_FAILED
from hippo.knowledge.raw_artifacts import RawArtifactStore
from hippo.ollama import Ollama
from hippo.status import _public_error
from hippo.store.migrations import DEFAULT_WORKSPACE_ID
from tests.conftest import git_env
from tests.unit.test_code_generation import ORDERS_V1, Runtime, head_of, make_checkout, served

SETTLE_SECONDS = 60
CLONE_URL = "https://git.example.com/acme/robots.git"
# `is_git_url` accepts userinfo; this token may reach nothing but the legacy row's own meta
# (ruled out of scope for this slice and recorded for Task 16).
TOKEN = "ghp_s3cr3tT0ken"
CREDENTIALED_URL = f"https://robot:{TOKEN}@git.example.com/acme/private.git"
LICENSE = b"Permission is hereby granted, free of charge, to Zed Corp.\n"


def zip_of(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return buffer.getvalue()


ARCHIVE = zip_of(
    {
        "src/orders.py": ORDERS_V1.encode(),
        "README.md": b"# Robots\n\nACME builds robots, and this file is prose inside an archive.\n",
    }
)
# The saved row of each code kind, as `add_repo`/`add_upload` would leave it.
CODE_KINDS = {
    "repo": ("repo", None, None),
    "archive": ("archive", "bundle.zip", ARCHIVE),
    "file": ("file", "orders.py", ORDERS_V1.encode()),
}


# ------------------------------------------------------------------ the world


@pytest.fixture
def world(ctx, tmp_path, monkeypatch):
    """A signed-in builder, the local model on a mock transport, and an origin repository."""
    store = ctx.store
    transaction_state = local()
    original_transaction = store.transaction

    @contextmanager
    def transaction():
        with original_transaction():
            transaction_state.depth = getattr(transaction_state, "depth", 0) + 1
            try:
                yield
            finally:
                transaction_state.depth -= 1

    monkeypatch.setattr(store, "transaction", transaction)
    store.ensure_schema()
    store.ensure_roles()
    user = store.create_user("builder", "password", "individual")
    store.put_knowledge(
        k.WorkspaceMembership(
            workspace_id=DEFAULT_WORKSPACE_ID,
            principal_id=user,
            mapping_authority="local",
            enabled=True,
            policy_epoch=1,
        )
    )
    store.set_meta("reviewed_mapping_authorities", ["local"])
    actor = BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual")))
    legacy_ollama = ctx.ollama
    runtime = Runtime(transaction_state)
    managed_ollama = Ollama(
        "http://local-model",
        "chat:latest",
        "embed:latest",
        num_ctx=8192,
        client=httpx.Client(base_url="http://local-model", transport=httpx.MockTransport(runtime.handle)),
    )
    ctx.ollama = managed_ollama
    origin = make_checkout(tmp_path, name="origin")
    clones: list[tuple[str, Path, int]] = []
    real_clone = repos.clone_repo

    def clone_locally(url, dest, timeout=300, depth=1):
        """`is_git_url` refuses a local path, so the saved remote URL is cloned from the origin."""
        clones.append((url, Path(dest), depth))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "-q",
                "--depth",
                str(depth),
                "--single-branch",
                "--",
                f"file://{origin}",
                str(dest),
            ],
            check=True,
            env=git_env(),
        )
        return dest

    monkeypatch.setattr(repos, "clone_repo", clone_locally)

    class World(SimpleNamespace):
        def inline_jobs(self):
            """Run each submitted job in the caller's thread, so a test reads its outcome at once."""

            def start(key, work):
                work()
                return True

            monkeypatch.setattr(self.ctx.jobs, "start", start)

        def quiet_jobs(self):
            monkeypatch.setattr(self.ctx.jobs, "start", lambda key, work: True)

    return World(**locals())


def wait(ctx) -> None:
    ctx.jobs.wait_all(SETTLE_SECONDS)
    assert ctx.jobs.running_keys() == []


def data_dir(w) -> Path:
    return Path(w.ctx.config.data_dir).resolve()


def files_of(w) -> dict[str, bytes]:
    root = data_dir(w)
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def raw_objects(w) -> int:
    root = managed_activation.raw_root(w.ctx)
    return sum(1 for p in root.rglob("*") if p.is_file()) if root.is_dir() else 0


def row_of(w, source_id) -> dict:
    # The backend lock counter is synchronization metadata, not presentation.
    return {key: value for key, value in w.store.get_source(source_id).items() if key != "generation_lock"}


def saved_source(w, kind, name, data, *, url=CLONE_URL, owner=None) -> str:
    """A Source row and its saved bytes, exactly as the ingress leaves them, with no job run."""
    owner = w.user if owner is None else owner
    if kind == "repo":
        source = w.store.create_source("repo", repos.repo_name(url), {"url": url}, owner_id=owner)
        pipeline.source_dir(w.ctx, source).mkdir(parents=True, exist_ok=True)
        return source
    source = w.store.create_source(kind, name, {"file": name, "bytes": len(data)}, owner_id=owner)
    target = pipeline.source_dir(w.ctx, source) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return source


def converting(w, kind, *, owner=None) -> str:
    """A code source mid-conversion, with nothing built.

    It has an untagged legacy passage, its saved bytes (and, for a repository, the legacy
    checkout), and the managed flag, which flips at staging start (ruling 9).
    """
    source = saved_source(w, *CODE_KINDS[kind], owner=owner)
    if kind == "repo":
        legacy_checkout = pipeline.source_dir(w.ctx, source) / pipeline.REPO_DIR / "src"
        legacy_checkout.mkdir(parents=True)
        (legacy_checkout / "orders.py").write_text(ORDERS_V1)
    w.store.add_passages(
        [
            {
                "id": f"{source}:legacy",
                "source_id": source,
                "text": "The legacy passage keeps answering until publication.",
                "title": "Legacy",
                "ordinal": 0,
                "embedding": [0.0, 1.0],
            }
        ]
    )
    w.store.update_source(source, status="ready", stage="ready")
    w.store.begin_managed_source(source)
    return source


def legacy_indexed(w, monkeypatch, add) -> str:
    """One source indexed by the legacy pipeline with the rule-based model, as today."""
    monkeypatch.setattr(w.ctx, "ollama", w.legacy_ollama)
    try:
        source = add()
        wait(w.ctx)
    finally:
        monkeypatch.setattr(w.ctx, "ollama", w.managed_ollama)
    row_ = w.store.get_source(source)
    assert row_["status"] == "ready", row_["error"]
    assert not row_["managed"] and w.store.passage_ids_for_source(source)
    return source


# ------------------------------------------------------------------ spies

STORE_CLEANUP = (
    "delete_source",
    "delete_passages_for_source",
    "delete_code_nodes_for_source",
    "remove_orphans",
    "_collect_generation",
)
# The legacy lane's clears and its whole read path: a managed attempt reaches none of them.
PIPELINE_LEGACY = ("_prepare_reindex", "_clear_passages", "_read_chunk_index", "_read_history", "read_source")


def arm_spies(w, monkeypatch):
    """Record every destructive or legacy-lane operation CD8 names.

    `shutil.rmtree` still runs, so a build's own checkout really is removed; every path it
    was given is recorded and only one `discard_checkout` named is forgiven. A raw unlink is
    an absolute path under the raw root: the raw store's own temporary-file cleanup unlinks
    a bare name relative to a directory descriptor and is not one.
    """
    calls: list[str] = []
    removed: list[Path] = []
    discarded: list[Path] = []

    def record(name):
        def spy(*args, **kwargs):
            calls.append(name)

        return spy

    for name in STORE_CLEANUP:
        monkeypatch.setattr(w.store, name, record(f"store.{name}"))
    for name in PIPELINE_LEGACY:
        monkeypatch.setattr(pipeline, name, record(f"pipeline.{name}"))

    real_rmtree = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        removed.append(Path(os.path.realpath(path)))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    real_discard = managed_activation.discard_checkout

    def discard(ctx, source_id, operation_id):
        discarded.append(
            Path(os.path.realpath(managed_activation.checkout_directory(ctx, source_id, operation_id)))
        )
        return real_discard(ctx, source_id, operation_id)

    monkeypatch.setattr(managed_activation, "discard_checkout", discard)
    raw = Path(os.path.realpath(managed_activation.raw_root(w.ctx)))

    def guarded(name):
        real = getattr(os, name)

        def guard(path, *args, **kwargs):
            if isinstance(path, (str, os.PathLike)) and Path(path).is_absolute():
                resolved = Path(os.path.realpath(path))
                if resolved == raw or raw in resolved.parents:
                    calls.append(f"os.{name}")
            return real(path, *args, **kwargs)

        return guard

    for name in ("unlink", "remove"):
        monkeypatch.setattr(os, name, guarded(name))

    def destroyed() -> list[str]:
        """Everything destructive that ran, except a build removing its own checkout."""
        return calls + [str(path) for path in removed if path not in discarded]

    return SimpleNamespace(calls=calls, removed=removed, discarded=discarded, destroyed=destroyed)


def coordinators(w, monkeypatch) -> list[tuple[str, dict]]:
    """Spy both coordinators: record what each was handed and publish nothing."""
    seen: list[tuple[str, dict]] = []

    def code(ctx, **kwargs):
        tree = kwargs["tree"]
        assert not ctx.store.in_ambient_transaction() and not getattr(w.transaction_state, "depth", 0)
        # The coordinator reads its tree while it runs, so the tree must exist now.
        assert tree.root.exists()
        files = (
            sorted(p.relative_to(tree.root).as_posix() for p in tree.root.rglob("*.py"))
            if tree.root.is_dir()
            else None
        )
        seen.append(("code", dict(kwargs, python_files=files)))
        return BuildReceipt(kwargs["source_id"], "g1", "e1", "h1", "published")

    def plain(ctx, **kwargs):
        seen.append(("plain", dict(kwargs)))
        return BuildReceipt(kwargs["source_id"], "g1", "e1", "h1", "published")

    monkeypatch.setattr(managed_activation, "build_code_source", code)
    monkeypatch.setattr(managed_activation, "build_plain_source", plain)
    return seen


# ------------------------------------------------------------------ eligibility


def row(**fields) -> dict:
    base = {
        "id": "s1",
        "kind": "text",
        "name": "Notes",
        "meta": {"file": "text.md"},
        "status": "ready",
        "stage": "ready",
        "managed": False,
        "active_generation_id": None,
    }
    return base | fields


@pytest.mark.parametrize(
    "source,expected",
    [
        (row(), "eligible_legacy"),
        (row(kind="file", meta={"file": "notes.md"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "orders.py"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "client.TSX"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "schema.sql"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "settings.yaml"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "go.mod"}), "unsupported"),  # a known text name, not a code name
        (row(kind="file", meta={"file": "LICENSE"}), "unsupported"),
        (row(kind="file", meta={"file": "paper.pdf"}), "unsupported"),
        (row(kind="file", meta={"file": "book.epub"}), "unsupported"),
        (row(kind="file", meta={"file": "page.html"}), "unsupported"),
        (row(kind="file", meta={"file": "orders.py.zip"}), "unsupported"),
        (row(kind="file", meta={}), "unsupported"),
        (row(kind="archive", meta={"file": "bundle.zip"}), "eligible_legacy"),
        (row(kind="archive", meta={"file": "BUNDLE.ZIP"}), "eligible_legacy"),
        (row(kind="archive", meta={"file": "bundle.tar"}), "unsupported"),
        (row(kind="repo", meta={"url": CLONE_URL}), "eligible_legacy"),
        # Decided on the row alone: the build, not eligibility, refuses a credentialed URL.
        (row(kind="repo", meta={"url": CREDENTIALED_URL}), "eligible_legacy"),
        (row(kind="sample", meta={"file": "acme_robotics.md"}), "unsupported"),
        (row(kind="connector", meta={}), "unsupported"),
        (row(kind="repo", meta={"url": CLONE_URL}, managed=True), "managed"),
        (row(kind="archive", meta={"file": "bundle.zip"}, managed=True), "managed"),
        (
            row(kind="repo", meta={"url": CLONE_URL}, managed=True, status="deleted", stage="tombstoned"),
            "tombstoned",
        ),
    ],
)
def test_eligibility_admits_repositories_archives_and_code_files_by_the_saved_row_alone(source, expected):
    assert managed_activation.managed_eligibility(source) == expected


@pytest.mark.parametrize(
    "kind,meta",
    [
        ("repo", {"url": CLONE_URL}),
        ("archive", {"file": "bundle.zip"}),
        ("file", {"file": "orders.py"}),
        ("file", {"file": "settings.yaml"}),
    ],
)
def test_an_actorless_caller_stays_legacy_and_a_managed_code_source_needs_an_actor(kind, meta):
    actor = BuildActor.trusted_local()
    assert managed_activation.plan_dispatch(row(kind=kind, meta=meta)).mode == "legacy"
    offered = managed_activation.plan_dispatch(row(kind=kind, meta=meta), actor=actor, operation_id="op-1")
    assert (offered.mode, offered.eligibility, offered.operation_id) == ("managed", "eligible_legacy", "op-1")
    with pytest.raises(managed_activation.ManagedActorRequired):
        managed_activation.plan_dispatch(row(kind=kind, meta=meta, managed=True))
    unsupported = row(kind="file", meta={"file": "LICENSE"})
    assert managed_activation.plan_dispatch(unsupported, actor=actor).mode == "legacy"


# ------------------------------------------------------------ dispatch by kind


@pytest.mark.parametrize("kind", ["repo", "archive", "file"])
def test_run_managed_build_hands_each_code_kind_a_tree_this_lane_owns(world, monkeypatch, kind):
    w = world
    source = saved_source(w, *CODE_KINDS[kind])
    folder = pipeline.source_dir(w.ctx, source)
    before = files_of(w)
    if kind == "repo":  # a repository converted from the legacy lane still has its checkout
        (folder / pipeline.REPO_DIR).mkdir()
        (folder / pipeline.REPO_DIR / "kept.py").write_text("x = 1\n")
        before = files_of(w)
    seen = coordinators(w, monkeypatch)
    spies = arm_spies(w, monkeypatch)

    receipt = managed_activation.run_managed_build(
        w.ctx, source_id=source, actor=w.actor, operation_id="op-1", job_key=pipeline.job_key(source)
    )

    assert receipt.outcome == "published"
    [(lane, call)] = seen
    tree = call["tree"]
    assert lane == "code" and type(tree) is CodeTreeInput
    assert (tree.kind, tree.paths) == (kind, None)
    assert (call["source_id"], call["actor"], call["operation_id"]) == (source, w.actor, "op-1")
    assert type(call["options"]) is CodeBuildOptions
    assert call["options"] == managed_activation.code_build_options(w.ctx)
    assert type(call["raw_store"]) is RawArtifactStore and type(call["embedding_cache"]) is EmbeddingCache
    if kind == "repo":
        checkout = managed_activation.checkout_directory(w.ctx, source, "op-1")
        assert checkout == folder / "checkouts" / "op-1"
        assert tree.root == checkout.resolve()
        assert call["python_files"] == ["src/orders.py"], "the coordinator was not handed the clone"
        assert tree.repository == repository_descriptor(CLONE_URL)
        assert tree.head_revision == head_of(w.origin)
        [(url, dest, depth)] = w.clones
        assert (url, dest, depth) == (CLONE_URL, checkout, pipeline._clone_depth(w.ctx))
        assert not checkout.exists(), "the build's own checkout outlived the build"
        assert spies.discarded and set(spies.removed) <= set(spies.discarded)
    else:
        assert tree.root == (folder / CODE_KINDS[kind][1]).resolve()
        assert (tree.repository, tree.head_revision) == (None, None)
        assert w.clones == [] and spies.removed == []
    assert files_of(w) == before, "a saved byte or the legacy checkout changed, or a clone was left behind"
    assert spies.destroyed() == []


def test_a_plain_prose_source_still_goes_to_the_plain_coordinator(world, monkeypatch):
    w = world
    source = saved_source(w, "file", "notes.md", b"ACME builds Robot.\n")
    seen = coordinators(w, monkeypatch)
    managed_activation.run_managed_build(
        w.ctx, source_id=source, actor=w.actor, operation_id="op-1", job_key=pipeline.job_key(source)
    )
    assert [lane for lane, _ in seen] == ["plain"] and w.clones == []


def test_the_code_lane_is_cancelled_by_its_own_job_and_presents_bounded_stages(world, monkeypatch):
    w = world
    source = saved_source(w, *CODE_KINDS["file"])
    seen = coordinators(w, monkeypatch)
    managed_activation.run_managed_build(
        w.ctx, source_id=source, actor=w.actor, operation_id="op-1", job_key=pipeline.job_key(source)
    )
    [(_, call)] = seen
    assert call["should_stop"]() is False
    w.ctx.jobs._cancelled[pipeline.job_key(source)] = Event()
    w.ctx.jobs._cancelled[pipeline.job_key(source)].set()
    assert call["should_stop"]() is True

    tokens = {
        phase: managed_activation._stage_token(BuildProgress(phase))
        for phase in ("capture", "reading", "history", "extract", "chunk", "bind", "embed", "write", "seal")
    }
    assert tokens == {
        "capture": "capture",
        "reading": "capture",
        "history": "extract",
        "extract": "extract",
        "chunk": "extract",
        "bind": "extract",
        "embed": "extract",
        "write": "write",
        "seal": "write",
    }
    call["on_progress"](BuildProgress("write", 2, 5))
    presented = w.store.get_source(source)
    assert (presented["stage"], presented["progress_done"], presented["progress_total"]) == ("write", 2, 5)


def test_code_build_options_are_the_settings_the_legacy_lane_reads(world):
    w = world
    base = dict(chunk_size_chars=900, chunk_overlap_chars=120, openie_workers=3, max_text_chars=456_789)
    w.ctx.config = replace(w.ctx.config, **base)
    w.store.update_settings(
        {
            "synonymy_threshold": 0.55,
            "code_history_depth": 7,
            "code_git_timeout_s": 11,
            "code_history_total_s": 90,
        }
    )

    options = managed_activation.code_build_options(w.ctx)

    assert (options.chunk_size_chars, options.chunk_overlap_chars, options.synonymy_threshold) == (
        900,
        120,
        0.55,
    )
    assert (options.history_depth, options.git_timeout_seconds, options.history_total_seconds) == (7, 11, 90)
    assert (options.workers, options.max_decoded_chars, options.allow_empty, options.exclusions) == (
        3,
        456_789,
        False,
        (),
    )
    reviewed = CodeBuildOptions()
    for name in ("capture_limits", "max_files", "max_file_bytes", "max_symbols", "max_chunks", "batch_size"):
        assert getattr(options, name) == getattr(reviewed, name), name
    w.store.update_settings({"code_history_depth": 0})
    assert managed_activation.code_build_options(w.ctx).history_depth == 0
    for fields in (
        {"chunk_size_chars": 10},
        {"chunk_overlap_chars": 800},
        {"openie_workers": 0},
        {"max_text_chars": 0},
    ):
        w.ctx.config = replace(w.ctx.config, **(base | fields))
        with pytest.raises(managed_activation.ManagedConfigurationError):
            managed_activation.code_build_options(w.ctx)


def test_a_managed_repository_refuses_a_credentialed_url_before_any_clone_or_raw_root(
    world, monkeypatch, caplog
):
    """The legacy row may already hold such a URL; the managed lane re-checks before it clones."""
    w = world
    source = saved_source(w, "repo", None, None, url=CREDENTIALED_URL)
    seen = coordinators(w, monkeypatch)
    with caplog.at_level(logging.DEBUG, logger="hippo"):
        with pytest.raises(CaptureRefused) as info:
            managed_activation.run_managed_build(
                w.ctx, source_id=source, actor=w.actor, operation_id="op-1", job_key=pipeline.job_key(source)
            )
    assert seen == [] and w.clones == []
    assert not managed_activation.checkout_directory(w.ctx, source, "op-1").exists()
    assert not (data_dir(w) / managed_activation.KNOWLEDGE_DIR).exists()
    assert TOKEN not in str(info.value) and TOKEN not in caplog.text


def test_the_checkout_cleanup_removes_only_one_operations_own_clone(world, tmp_path):
    w = world
    source = saved_source(w, "repo", None, None)
    folder = pipeline.source_dir(w.ctx, source)
    (folder / pipeline.REPO_DIR).mkdir()
    (folder / pipeline.REPO_DIR / "kept.py").write_text("x = 1\n")
    checkout = managed_activation.checkout_directory(w.ctx, source, "op-1")
    (checkout / "src").mkdir(parents=True)
    (checkout / "src" / "a.py").write_text("y = 2\n")
    for bad in ("../repo", "", "repo/..", "a b", ".hidden"):
        with pytest.raises(managed_activation.ManagedDispatchError):
            managed_activation.checkout_directory(w.ctx, source, bad)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    link = managed_activation.checkout_directory(w.ctx, source, "op-2")
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(managed_activation.ManagedDispatchError):
        managed_activation.discard_checkout(w.ctx, source, "op-2")
    managed_activation.discard_checkout(w.ctx, source, "op-1")
    managed_activation.discard_checkout(w.ctx, source, "op-3")  # nothing there: a no-op

    assert not checkout.exists() and link.is_symlink() and (outside / "keep.txt").exists()
    assert (folder / pipeline.REPO_DIR / "kept.py").exists()


# ------------------------------------------------------------ add_repo and ingress


def test_add_repo_checks_its_actor_operation_and_managed_url_before_a_source_row(world, caplog):
    w = world
    w.quiet_jobs()
    with caplog.at_level(logging.DEBUG, logger="hippo"):
        for call, error in (
            (
                lambda: pipeline.add_repo(w.ctx, CLONE_URL, build_actor="reader"),
                managed_activation.ManagedDispatchError,
            ),
            (
                lambda: pipeline.add_repo(w.ctx, CLONE_URL, build_actor=w.actor, operation_id="not a token!"),
                managed_activation.ManagedDispatchError,
            ),
            (
                lambda: pipeline.add_repo(w.ctx, CREDENTIALED_URL, owner_id=w.user, build_actor=w.actor),
                CaptureRefused,
            ),
        ):
            with pytest.raises(error) as info:
                call()
            assert TOKEN not in str(info.value)
    assert w.store.list_sources() == [] and w.clones == []
    assert not (data_dir(w) / managed_activation.SOURCES_DIR).exists()
    assert TOKEN not in caplog.text
    # The legacy hint is kept word for word.
    with pytest.raises(repos.RepoError, match="does not look like a git URL"):
        pipeline.add_repo(w.ctx, "/home/user/repo", build_actor=w.actor)


def test_ingress_sends_code_sources_to_the_managed_lane_only_with_an_actor(world, monkeypatch):
    w = world
    seen: list[tuple[str, str, str | None]] = []

    def legacy(ctx, source, *, should_stop):
        seen.append(("legacy", source["id"], None))

    def managed(ctx, *, source_id, actor, operation_id, job_key):
        assert type(actor) is BuildActor and job_key == pipeline.job_key(source_id)
        seen.append(("managed", source_id, operation_id))
        return BuildReceipt(source_id, "g1", "e1", "h1", "published")

    monkeypatch.setattr(pipeline, "_read_chunk_index", legacy)
    monkeypatch.setattr(managed_activation, "run_managed_build", managed)
    w.inline_jobs()

    order = [
        (
            "managed",
            pipeline.add_repo(
                w.ctx, CLONE_URL, owner_id=w.user, build_actor=w.actor, operation_id="index.r1"
            ),
        ),
        ("legacy", pipeline.add_repo(w.ctx, CLONE_URL, owner_id=w.user)),
        ("managed", pipeline.add_upload(w.ctx, "bundle.zip", ARCHIVE, owner_id=w.user, build_actor=w.actor)),
        ("legacy", pipeline.add_upload(w.ctx, "bundle.zip", ARCHIVE, owner_id=w.user)),
        (
            "managed",
            pipeline.add_upload(w.ctx, "orders.py", ORDERS_V1.encode(), owner_id=w.user, build_actor=w.actor),
        ),
        ("legacy", pipeline.add_upload(w.ctx, "orders.py", ORDERS_V1.encode(), owner_id=w.user)),
        ("legacy", pipeline.add_upload(w.ctx, "LICENSE", LICENSE, owner_id=w.user, build_actor=w.actor)),
    ]

    assert [(lane, source) for lane, source, _ in seen] == order
    assert seen[0][2] == "index.r1"
    assert all(managed_activation.OPERATION_ID.match(op) for lane, _, op in seen if lane == "managed")
    repo = w.store.get_source(order[0][1])
    assert (repo["kind"], repo["name"], repo["meta"]) == ("repo", "acme/robots", {"url": CLONE_URL})


# ------------------------------------------------------------ real builds


def test_add_repo_with_an_actor_publishes_one_code_generation_and_then_refuses_every_legacy_path(
    world, monkeypatch
):
    w = world
    w.inline_jobs()
    spies = arm_spies(w, monkeypatch)

    source = pipeline.add_repo(
        w.ctx, CLONE_URL, owner_id=w.user, build_actor=w.actor, operation_id="index.boot"
    )

    published = row_of(w, source)
    assert published["managed"] and (published["status"], published["stage"], published["error"]) == (
        "ready",
        "ready",
        None,
    )
    generation = published["active_generation_id"]
    assert generation and w.store.validate_generation_seal(generation).ready
    assert {"repository", "manifest", "file", "history_event"} <= {
        a.kind for a in w.store._knowledge_rows("Artifact")
    }
    [(_, dest, _)] = w.clones
    assert dest == pipeline.source_dir(w.ctx, source) / "checkouts" / "index.boot" and not dest.exists()
    assert [path for path, _ in w.runtime.calls if path == "/api/chat"] == []
    passages, nodes = served(w)
    assert passages and nodes
    assert spies.destroyed() == []
    raw = raw_objects(w)

    # After publication an actorless caller refuses on every path, before any hook.
    for call in (
        lambda: pipeline.reindex(w.ctx, source),
        lambda: pipeline.delete_source(w.ctx, source),
        lambda: pipeline.reindex_all(w.ctx),
        lambda: pipeline.start_indexing(w.ctx, source),
        lambda: pipeline.run_indexing(w.ctx, source),
    ):
        with pytest.raises(managed_activation.ManagedActorRequired):
            call()
    assert row_of(w, source) == published

    # With an actor a reindex refreshes through the code lane and a delete tombstones.
    seen = coordinators(w, monkeypatch)
    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True
    assert [(lane, call["tree"].kind) for lane, call in seen] == [("code", "repo")]
    pipeline.delete_source(w.ctx, source, build_actor=w.actor, operation_id="delete.1")
    deleted = row_of(w, source)
    assert (deleted["status"], deleted["stage"]) == ("deleted", "tombstoned")
    assert deleted["active_generation_id"] == generation
    assert raw_objects(w) == raw and spies.destroyed() == []


def test_a_legacy_repository_converts_with_its_legacy_graph_serving_until_publication(world, monkeypatch):
    w = world
    source = legacy_indexed(w, monkeypatch, lambda: pipeline.add_repo(w.ctx, CLONE_URL, owner_id=w.user))
    legacy_passages = set(w.store.passage_ids_for_source(source))
    baseline = served(w)
    assert legacy_passages <= baseline[0] and baseline[1]
    legacy_checkout = pipeline.source_dir(w.ctx, source) / pipeline.REPO_DIR
    assert (legacy_checkout / "src" / "orders.py").is_file()
    w.inline_jobs()
    spies = arm_spies(w, monkeypatch)
    snapshots: list = []
    refused: list[str] = []
    present = managed_activation._present_progress

    def watch(ctx, source_id, progress, *, refresh):
        present(ctx, source_id, progress, refresh=refresh)
        if progress.phase not in ("write", "seal") or len(snapshots) >= 2:
            return
        snapshots.append(served(w))
        if refused:
            return
        # Mid-staging: the flag flipped at staging start and nothing is published yet, so every
        # actorless destructive path refuses before it touches anything (ruling 9).
        current = w.store.get_source(source)
        assert current["managed"] and not current["active_generation_id"]
        for name, call in (
            ("reindex", lambda: pipeline.reindex(w.ctx, source)),
            ("delete_source", lambda: pipeline.delete_source(w.ctx, source)),
            ("reindex_all", lambda: pipeline.reindex_all(w.ctx)),
        ):
            with pytest.raises(managed_activation.ManagedActorRequired):
                call()
            refused.append(name)

    monkeypatch.setattr(managed_activation, "_present_progress", watch)

    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True

    assert refused == ["reindex", "delete_source", "reindex_all"]
    assert snapshots and all(snapshot == baseline for snapshot in snapshots), "the legacy graph blinked"
    converted = w.store.get_source(source)
    assert converted["managed"] and converted["status"] == "ready" and converted["active_generation_id"]
    after = served(w)
    assert not legacy_passages & after[0] and after != baseline
    assert legacy_passages <= set(w.store.passage_ids_for_source(source)), (
        "legacy rows are unselected, not deleted"
    )
    assert (legacy_checkout / "src" / "orders.py").is_file()
    assert spies.destroyed() == []


def test_a_legacy_archive_converts_from_its_saved_zip_without_extracting_it(world, monkeypatch):
    w = world
    source = legacy_indexed(
        w, monkeypatch, lambda: pipeline.add_upload(w.ctx, "bundle.zip", ARCHIVE, owner_id=w.user)
    )
    folder = pipeline.source_dir(w.ctx, source)
    saved = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))
    w.inline_jobs()
    spies = arm_spies(w, monkeypatch)

    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True

    converted = w.store.get_source(source)
    assert converted["managed"] and converted["status"] == "ready", converted["error"]
    coverage = json.loads(w.store._generation(converted["active_generation_id"]).coverage_json)
    assert coverage["capture_kind"] == "archive"
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) == saved == ["bundle.zip"]
    assert w.clones == [] and spies.destroyed() == []


def test_an_authenticated_code_file_upload_publishes_a_managed_generation(world, monkeypatch):
    w = world
    w.inline_jobs()
    spies = arm_spies(w, monkeypatch)

    source = pipeline.add_upload(w.ctx, "orders.py", ORDERS_V1.encode(), owner_id=w.user, build_actor=w.actor)

    published = w.store.get_source(source)
    assert published["managed"] and published["status"] == "ready", published["error"]
    generation = w.store._generation(published["active_generation_id"])
    assert json.loads(generation.coverage_json)["capture_kind"] == "file"
    assert w.store.validate_generation_seal(generation.id).ready
    assert w.clones == [] and spies.destroyed() == []


# ------------------------------------------------------------ destructive operations


@pytest.mark.parametrize("kind", ["repo", "archive", "file"])
def test_an_actorless_caller_never_reaches_cleanup_for_a_converting_code_source(world, monkeypatch, kind):
    w = world
    source = converting(w, kind)
    before_row, before_files = row_of(w, source), files_of(w)
    spies = arm_spies(w, monkeypatch)

    for call in (
        lambda: pipeline.reindex(w.ctx, source),
        lambda: pipeline.delete_source(w.ctx, source),
        lambda: pipeline.reindex_all(w.ctx),
        lambda: pipeline.start_indexing(w.ctx, source),
        lambda: pipeline.run_indexing(w.ctx, source),
    ):
        with pytest.raises(managed_activation.ManagedActorRequired):
            call()

    assert spies.destroyed() == []
    assert row_of(w, source) == before_row and files_of(w) == before_files
    assert w.store.passage_ids_for_source(source) == [f"{source}:legacy"]


def test_a_bulk_by_an_actor_who_cannot_build_a_converting_code_source_clears_nothing(world, monkeypatch):
    w = world
    converting(w, "repo", owner="somebody-else")
    legacy = saved_source(w, "file", "LICENSE", LICENSE)  # a legacy lane the bulk would clear first
    before = files_of(w)
    spies = arm_spies(w, monkeypatch)

    with pytest.raises(managed_activation.ManagedPreflightRefused):
        pipeline.reindex_all(w.ctx, build_actor=w.actor)

    assert spies.destroyed() == [] and files_of(w) == before
    assert w.store.get_source(legacy)["status"] == "queued"


@pytest.mark.parametrize("kind", ["repo", "archive", "file"])
def test_an_actor_refreshes_or_tombstones_a_converting_code_source_without_cleanup(world, monkeypatch, kind):
    w = world
    source = converting(w, kind)
    before = files_of(w)
    w.inline_jobs()
    seen = coordinators(w, monkeypatch)
    spies = arm_spies(w, monkeypatch)

    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True
    pipeline.delete_source(w.ctx, source, build_actor=w.actor, operation_id="delete.1")

    assert [(lane, call["tree"].kind) for lane, call in seen] == [("code", kind)]
    deleted = w.store.get_source(source)
    assert (deleted["status"], deleted["stage"]) == ("deleted", "tombstoned")
    assert spies.destroyed() == []
    assert w.store.passage_ids_for_source(source) == [f"{source}:legacy"]
    assert files_of(w) == before, "a saved byte, the legacy checkout or a clone was left or lost"


# ------------------------------------------------------------ privacy and failure mapping


def test_a_legacy_clone_failure_keeps_a_credential_out_of_the_logs_and_the_row_presentation(
    world, monkeypatch, caplog
):
    """Review m6 at the pipeline: git's stderr echoes the URL it was handed, token and all."""
    w = world
    monkeypatch.setattr(repos, "clone_repo", w.real_clone)
    stderr = f"fatal: Authentication failed for '{CREDENTIALED_URL}/'\nfatal: could not read /Users/ops/.git-credentials\n"
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 128, "", stderr)
    )
    with caplog.at_level(logging.DEBUG, logger="hippo"):
        source = pipeline.add_repo(w.ctx, CREDENTIALED_URL, owner_id=w.user)
        wait(w.ctx)

    failed = w.store.get_source(source)
    assert (
        failed["status"] == "failed" and failed["error"] == "RepoError: indexing failed; inspect local logs"
    )
    # `meta.url` keeps what the legacy lane was given: ruled out of scope here (Task 16).
    presented = json.dumps({key: failed[key] for key in ("name", "status", "stage", "error")})
    for part in (TOKEN, "robot:", ".git-credentials"):
        assert part not in presented and part not in caplog.text


def test_a_managed_clone_failure_is_presented_by_its_closed_code_alone(world, monkeypatch, caplog):
    w = world
    monkeypatch.setattr(repos, "clone_repo", w.real_clone)
    stderr = "fatal: repository 'https://git.example.com/acme/robots.git/' not found\nfatal: /Users/ops/.git-credentials\n"
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 128, "", stderr)
    )
    w.inline_jobs()
    with caplog.at_level(logging.DEBUG, logger="hippo"):
        source = pipeline.add_repo(
            w.ctx, CLONE_URL, owner_id=w.user, build_actor=w.actor, operation_id="index.c1"
        )

    failed = w.store.get_source(source)
    assert (failed["status"], failed["stage"]) == ("failed", "failed")
    assert failed["error"].startswith("operation_failed: ")
    assert _public_error(failed) == OPERATION_FAILED.message
    for part in ("acme/robots.git", ".git-credentials", "/Users/ops", "not found", str(data_dir(w))):
        assert part not in failed["error"] and part not in caplog.text
    assert not managed_activation.checkout_directory(w.ctx, source, "index.c1").exists()
    assert not (data_dir(w) / managed_activation.KNOWLEDGE_DIR).exists()


def test_a_capture_refusal_is_presented_as_an_invalid_source_without_a_path(world, monkeypatch, caplog):
    w = world
    w.inline_jobs()
    nested = zip_of({"src/orders.py": ORDERS_V1.encode(), "vendor-secret/inner.zip": ARCHIVE})
    with caplog.at_level(logging.DEBUG, logger="hippo"):
        source = pipeline.add_upload(w.ctx, "bundle.zip", nested, owner_id=w.user, build_actor=w.actor)

    failed = w.store.get_source(source)
    assert (failed["status"], failed["stage"]) == ("failed", "failed")
    assert failed["error"].startswith("invalid_source: ") and "plain prose" not in failed["error"]
    assert _public_error(failed) == INVALID_SOURCE_TYPE.message
    for part in ("inner.zip", "vendor-secret", str(data_dir(w))):
        assert part not in failed["error"] and part not in caplog.text


def test_the_code_lane_failures_map_to_closed_generation_aware_codes(world):
    poison = f"{CREDENTIALED_URL} /private/var/data/sources/s1/checkouts/op-1 fatal: bad object"
    cases = (
        (CaptureRefused(poison, reason="nested_archive"), "invalid_source"),
        (CodeBuildRefused(poison), "invalid_source"),
        (repos.RepoError(poison), "operation_failed"),
    )
    for error, code in cases:
        for active in (False, True):
            failure = managed_activation.map_build_failure(error, has_active_generation=active)
            text = f"{failure.status} {failure.stage} {failure.code} {failure.message}"
            assert failure.code == code, type(error).__name__
            assert failure.status == ("ready" if active else "failed")
            assert (
                "plain prose" not in failure.message and failure.message != managed_activation.UNKNOWN_MESSAGE
            )
            for part in (TOKEN, "/private", "fatal", "checkouts"):
                assert part not in text


# ------------------------------------------------------------ rows routed from the PA8 re-sign


@pytest.mark.parametrize(
    "kind,saved,on_disk",
    [
        ("file", "notes.md", "paper.pdf"),
        ("file", "orders.py", "orders.pyc"),
        ("archive", "bundle.zip", "other.zip"),
    ],
)
def test_a_saved_file_not_named_as_its_row_says_is_refused_before_any_build(
    world, monkeypatch, kind, saved, on_disk
):
    """PA3a-6: eligibility was decided on `meta["file"]`, so the one saved file must carry that name."""
    w = world
    source = saved_source(w, kind, saved, ARCHIVE if kind == "archive" else b"ACME builds Robot.\n")
    folder = pipeline.source_dir(w.ctx, source)
    (folder / saved).rename(folder / on_disk)
    seen = coordinators(w, monkeypatch)

    with pytest.raises(managed_activation.ManagedIngressError):
        managed_activation.run_managed_build(
            w.ctx, source_id=source, actor=w.actor, operation_id="op-1", job_key=pipeline.job_key(source)
        )

    assert seen == [] and not (data_dir(w) / managed_activation.KNOWLEDGE_DIR).exists()


def test_one_lane_that_cannot_start_never_strands_the_bulk_lanes_behind_it(world, monkeypatch, caplog):
    """W15: per-lane containment covers every cause, not only a lane change after the plan."""
    w = world
    w.quiet_jobs()
    first = saved_source(w, "file", "LICENSE", LICENSE)
    second = saved_source(w, "file", "NOTICE", b"Notice: Zed Corp builds drones.\n")
    submitted: list[str] = []
    original = pipeline.start_indexing
    poison = "store unavailable at /private/var/hippo/secret"

    def submit(ctx, source_id, **kwargs):
        if source_id == first:
            raise RuntimeError(poison)
        submitted.append(source_id)
        return original(ctx, source_id, **kwargs)

    monkeypatch.setattr(pipeline, "start_indexing", submit)
    with caplog.at_level(logging.DEBUG, logger="hippo"):
        assert pipeline.reindex_all(w.ctx) == 1

    assert submitted == [second], "the lane after the failing one was stranded"
    assert first in caplog.text and poison not in caplog.text
