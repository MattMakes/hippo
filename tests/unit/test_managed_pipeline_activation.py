"""Production ingestion dispatches eligible authenticated sources to the reviewed coordinator.

Everything else keeps legacy behaviour. A managed attempt never clears source-wide
evidence, never deletes raw or saved bytes, and never reports a private detail.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event, local
from types import SimpleNamespace

import httpx
import pytest

from hippo.access import EVERYTHING, Principal
from hippo.ingest import pipeline
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.query_access import query_session
from hippo.knowledge.source_lifecycle import tombstone_managed_source
from hippo.ollama import Ollama
from hippo.store.migrations import DEFAULT_WORKSPACE_ID
from tests.unit.test_prose_generation import Runtime

SETTLE_SECONDS = 60
FIRST_TEXT = "ACME builds Robot."
SECOND_TEXT = "ACME now builds Robot."
# Long enough to make several chunks, so every extract phase is observable.
LONG_TEXT = "ACME builds Robot. " * 200
OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def api():
    try:
        return importlib.import_module("hippo.ingest.managed_activation")
    except ModuleNotFoundError:
        pytest.fail("Managed activation adapter is missing")


def wait(ctx) -> None:
    ctx.jobs.wait_all(SETTLE_SECONDS)
    assert ctx.jobs.running_keys() == []


def knowledge_root(ctx) -> Path:
    return Path(ctx.config.data_dir).resolve() / "knowledge"


def raw_inventory(ctx) -> dict[str, bytes]:
    root = knowledge_root(ctx) / "raw-v1"
    if not root.is_dir():
        return {}
    return {path.name: path.read_bytes() for path in sorted(root.iterdir()) if path.is_file()}


def source_row(w) -> dict:
    # The backend lock counter is synchronization metadata, not serving state.
    return {key: value for key, value in w.store.get_source(w.source).items() if key != "generation_lock"}


def citations(ctx) -> set[str]:
    with query_session(ctx, EVERYTHING, structural=True) as session:
        return {c.text for c in session.graph.original_citations}


@pytest.fixture
def setup(ctx, tmp_path, monkeypatch):
    """An authenticated local reader, a local model and no source yet."""
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
    from hippo.knowledge import model as k

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
    runtime = Runtime(store, transaction_state)
    managed_ollama = Ollama(
        "http://local-model",
        "chat:latest",
        "embed:latest",
        num_ctx=8192,
        client=httpx.Client(base_url="http://local-model", transport=httpx.MockTransport(runtime.handle)),
    )
    ctx.ollama = managed_ollama

    class Setup(SimpleNamespace):
        @property
        def module(self):
            return api()

        def quiet_jobs(self):
            """Create sources without running their background job."""
            monkeypatch.setattr(self.ctx.jobs, "start", lambda key, work: True)

        def inline_jobs(self):
            """Run every submitted job in the caller's thread, in submission order.

            A bulk reindex submits several lanes at once; running them here keeps
            two managed builds off one mock transport and makes the order the test
            reads the order the pipeline chose.
            """
            started: list[str] = []

            def start(key, work):
                started.append(key)
                work()
                return True

            monkeypatch.setattr(self.ctx.jobs, "start", start)
            return started

        def held_jobs(self):
            """Capture each submitted job without running it, so a race can commit first."""
            held: list[tuple[str, object]] = []

            def start(key, work):
                held.append((key, work))
                return True

            monkeypatch.setattr(self.ctx.jobs, "start", start)
            return held

        def stage_text(self, text=FIRST_TEXT, name="Notes"):
            self.source = pipeline.add_text(self.ctx, name, text, owner_id=self.user)
            return self.source

        def stage_upload(self, filename, data):
            self.source = pipeline.add_upload(self.ctx, filename, data, owner_id=self.user)
            return self.source

        def build(self, source_id=None, operation="op-1"):
            pipeline.run_indexing(
                self.ctx, source_id or self.source, build_actor=self.actor, operation_id=operation
            )

    return Setup(**locals(), source=None)


# --------------------------------------------------------------- eligibility


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
        (row(kind="file", meta={"file": "notes.txt"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "notes.md"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "notes.markdown"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "notes.rst"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "notes.text"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "NOTES.MD"}), "eligible_legacy"),
        (row(kind="file", meta={"file": "paper.pdf"}), "unsupported"),
        (row(kind="file", meta={"file": "module.py"}), "unsupported"),
        (row(kind="file", meta={"file": "settings.yaml"}), "unsupported"),
        (row(kind="file", meta={"file": "LICENSE"}), "unsupported"),
        (row(kind="file", meta={"file": "notes.md.zip"}), "unsupported"),
        (row(kind="archive", meta={"file": "bundle.zip"}), "unsupported"),
        (row(kind="repo", meta={"url": "https://host/o/r"}), "unsupported"),
        (row(kind="sample", meta={"file": "acme_robotics.md"}), "unsupported"),
        (row(kind="archive", meta={"file": "bundle.zip"}, managed=True), "managed"),
        (row(kind="file", meta={"file": "paper.pdf"}, managed=True), "managed"),
        (row(managed=True, status="deleted", stage="tombstoned"), "tombstoned"),
        (row(status="deleted", stage="tombstoned"), "tombstoned"),
    ],
)
def test_eligibility_reads_the_saved_source_kind_and_stored_filename(setup, source, expected):
    assert setup.module.managed_eligibility(source) == expected


def test_eligibility_never_trusts_a_claimed_content_type(setup):
    """An uploaded name decides; an HTTP claim about the bytes does not."""
    module = setup.module
    claimed = row(kind="file", meta={"file": "paper.pdf", "content_type": "text/markdown"})
    assert module.managed_eligibility(claimed) == "unsupported"
    binary = row(kind="file", meta={"file": "notes.md", "content_type": "application/octet-stream"})
    assert module.managed_eligibility(binary) == "eligible_legacy"


def test_new_operation_id_is_bounded_unique_and_closed(setup):
    made = {setup.module.new_operation_id() for _ in range(50)}
    assert len(made) == 50
    assert all(OPERATION_ID.match(value) for value in made)


# ----------------------------------------------------------- dispatch matrix


def receipt(source_id, outcome="published"):
    from hippo.ingest.prose_generation import BuildReceipt

    return BuildReceipt(source_id, "g1", "e1", "h1", outcome)


def lanes(monkeypatch):
    """Record which lane one source entered without running either of them."""
    seen: list[tuple[str, str]] = []
    module = api()

    def legacy(ctx, source, *, should_stop):
        seen.append(("legacy", source["id"]))

    def managed(ctx, *, source_id, actor, operation_id, job_key):
        assert type(actor) is BuildActor and OPERATION_ID.match(operation_id)
        assert job_key == f"index:{source_id}"
        seen.append(("managed", source_id))
        return receipt(source_id)

    monkeypatch.setattr(pipeline, "_read_chunk_index", legacy)
    monkeypatch.setattr(module, "run_managed_build", managed)
    return seen


def test_new_pasted_text_with_an_actor_goes_to_managed_bootstrap(setup, monkeypatch):
    w = setup
    seen = lanes(monkeypatch)
    source = pipeline.add_text(w.ctx, "Notes", FIRST_TEXT, owner_id=w.user, build_actor=w.actor)
    wait(w.ctx)
    assert seen == [("managed", source)]


def test_new_pasted_text_without_an_actor_stays_legacy(setup, monkeypatch):
    w = setup
    seen = lanes(monkeypatch)
    source = pipeline.add_text(w.ctx, "Notes", FIRST_TEXT)
    wait(w.ctx)
    assert seen == [("legacy", source)]


@pytest.mark.parametrize("filename", ["notes.txt", "notes.md", "notes.rst"])
def test_an_eligible_plain_upload_without_an_actor_stays_legacy(setup, monkeypatch, filename):
    """The same file that opts in with an actor is an ordinary legacy upload without one."""
    w = setup
    seen = lanes(monkeypatch)
    source = w.stage_upload(filename, FIRST_TEXT.encode())
    wait(w.ctx)
    assert seen == [("legacy", source)]


@pytest.mark.parametrize("filename", ["notes.txt", "notes.md", "notes.markdown", "notes.rst", "notes.text"])
def test_eligible_plain_upload_with_an_actor_goes_to_managed_bootstrap(setup, monkeypatch, filename):
    w = setup
    seen = lanes(monkeypatch)
    source = pipeline.add_upload(w.ctx, filename, FIRST_TEXT.encode(), owner_id=w.user, build_actor=w.actor)
    wait(w.ctx)
    assert seen == [("managed", source)]


@pytest.mark.parametrize(
    "filename,data",
    [
        ("paper.pdf", b"%PDF-1.4 not really a pdf"),
        ("module.py", b"def f():\n    return 1\n"),
        ("settings.yaml", b"key: value\n"),
        ("bundle.zip", b"PK\x03\x04 not really a zip"),
    ],
)
def test_unsupported_upload_stays_legacy_even_with_an_actor(setup, monkeypatch, filename, data):
    w = setup
    seen = lanes(monkeypatch)
    source = pipeline.add_upload(w.ctx, filename, data, owner_id=w.user, build_actor=w.actor)
    wait(w.ctx)
    assert seen == [("legacy", source)]


def test_repo_and_sample_stay_legacy_even_with_an_actor(setup, monkeypatch):
    """`add_repo`/`add_sample` take no actor; one offered later still cannot convert them."""
    w = setup
    w.quiet_jobs()
    repo = pipeline.add_repo(w.ctx, "https://github.com/acme/robots")
    sample = pipeline.add_sample(w.ctx)
    seen = lanes(monkeypatch)
    pipeline.run_indexing(w.ctx, repo, build_actor=w.actor)
    pipeline.run_indexing(w.ctx, sample, build_actor=w.actor)
    assert seen == [("legacy", repo), ("legacy", sample)]


def test_an_existing_managed_source_without_an_actor_refuses_before_any_legacy_hook(setup, monkeypatch):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    w.store.begin_managed_source(source)
    before = source_row(w)
    seen = lanes(monkeypatch)
    for call in (
        lambda: pipeline.start_indexing(w.ctx, source),
        lambda: pipeline.run_indexing(w.ctx, source),
        lambda: pipeline.reindex(w.ctx, source),
    ):
        with pytest.raises(w.module.ManagedActorRequired):
            call()
    assert seen == [] and source_row(w) == before


def test_an_existing_managed_source_with_an_actor_refreshes_and_never_prepares_legacy(setup, monkeypatch):
    w = setup
    seen = lanes(monkeypatch)
    source = w.stage_text()
    wait(w.ctx)
    seen.clear()
    w.store.begin_managed_source(source)
    monkeypatch.setattr(
        pipeline, "_prepare_reindex", lambda *a, **k: pytest.fail("legacy preparation for a managed source")
    )
    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True
    wait(w.ctx)
    assert seen == [("managed", source)]


def test_a_tombstoned_source_is_skipped_without_mutation_or_resurrection(setup, monkeypatch):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    w.store.begin_managed_source(source)
    tombstone_managed_source(w.ctx, source_id=source, actor=BuildActor.trusted_local(), operation_id="del-1")
    before = source_row(w)
    assert before["status"] == "deleted" and before["stage"] == "tombstoned"
    seen = lanes(monkeypatch)
    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is False
    assert pipeline.start_indexing(w.ctx, source, build_actor=w.actor) is False
    assert pipeline.run_indexing(w.ctx, source, build_actor=w.actor) is None
    assert seen == [] and source_row(w) == before


def test_add_text_and_add_upload_reject_a_foreign_actor_before_creating_a_source(setup):
    w = setup
    before = len(w.store.list_sources())
    for call in (
        lambda: pipeline.add_text(w.ctx, "Notes", FIRST_TEXT, build_actor="reader"),
        lambda: pipeline.add_upload(w.ctx, "notes.md", FIRST_TEXT.encode(), build_actor=object()),
    ):
        with pytest.raises(ValueError):
            call()
    assert len(w.store.list_sources()) == before
    assert not knowledge_root(w.ctx).exists()


# ------------------------------------------------------- managed bootstrap


def test_authenticated_pasted_text_publishes_a_managed_generation(setup):
    w = setup
    source = pipeline.add_text(w.ctx, "Notes", FIRST_TEXT, owner_id=w.user, build_actor=w.actor)
    w.source = source
    wait(w.ctx)
    row_ = source_row(w)
    assert row_["managed"] and row_["status"] == "ready" and row_["stage"] == "ready"
    assert row_["active_generation_id"] and row_["error"] is None
    assert w.store.validate_generation_seal(row_["active_generation_id"]).ready
    assert FIRST_TEXT in citations(w.ctx)


def test_an_eligible_legacy_reindex_converts_atomically_and_serves_legacy_until_publish(setup, monkeypatch):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    w.store.add_passages(
        [
            {
                "id": "legacy",
                "source_id": source,
                "text": "Last good legacy",
                "title": "Legacy",
                "ordinal": 0,
                "embedding": [1.0, 0.0],
            }
        ]
    )
    monkeypatch.setattr(
        pipeline, "_clear_passages", lambda *a, **k: pytest.fail("managed conversion cleared legacy rows")
    )
    monkeypatch.setattr(
        pipeline, "_prepare_reindex", lambda *a, **k: pytest.fail("legacy preparation for a conversion")
    )
    seen = []

    def inspect(path, body):
        if path == "/api/chat":
            assert w.store.passage_ids_for_source(source) == ["legacy"]
            assert not w.store.get_source(source)["managed"]
            seen.append(True)

    w.runtime.hook = inspect
    w.inline_jobs()  # the conversion branch of `reindex` itself, not just the worker it submits
    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True
    assert seen
    row_ = source_row(w)
    assert row_["managed"] and row_["status"] == "ready" and row_["active_generation_id"]
    assert "legacy" in w.store.passage_ids_for_source(source), "the legacy rows outlive the publish"


def test_the_saved_logical_name_is_the_sanitized_stored_filename(setup, monkeypatch):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    captured = {}
    module = w.module
    original = module.build_plain_source

    def spy(ctx, **kwargs):
        captured.update(kwargs)
        return original(ctx, **kwargs)

    monkeypatch.setattr(module, "build_plain_source", spy)
    w.build(source)
    (single,) = captured["inputs"]
    assert single.logical_path == "text.md" and single.media_type == "text/plain"
    assert single.path.is_absolute() and single.path.name == "text.md"
    assert single.path == (pipeline.source_dir(w.ctx, source) / "text.md").resolve()


# --------------------------------------------------- ingress file discipline


@pytest.fixture
def staged(setup, monkeypatch):
    setup.quiet_jobs()
    setup.stage_text()
    return setup


def test_a_missing_ingress_file_is_refused_before_any_model_request(staged):
    w = staged
    (pipeline.source_dir(w.ctx, w.source) / "text.md").unlink()
    w.build()
    assert source_row(w)["status"] == "failed"
    assert not w.runtime.calls and not knowledge_root(w.ctx).exists()


def test_a_second_saved_file_is_refused_before_any_model_request(staged):
    w = staged
    (pipeline.source_dir(w.ctx, w.source) / "extra.md").write_bytes(b"more")
    w.build()
    assert source_row(w)["status"] == "failed" and not w.runtime.calls


def test_a_symlinked_ingress_file_is_refused(staged, tmp_path):
    w = staged
    target = tmp_path / "elsewhere.md"
    target.write_text(FIRST_TEXT)
    saved = pipeline.source_dir(w.ctx, w.source) / "text.md"
    saved.unlink()
    saved.symlink_to(target)
    w.build()
    assert source_row(w)["status"] == "failed" and not w.runtime.calls


def test_a_non_regular_ingress_file_is_refused(staged):
    w = staged
    saved = pipeline.source_dir(w.ctx, w.source) / "text.md"
    saved.unlink()
    os.mkfifo(saved)
    w.build()
    assert source_row(w)["status"] == "failed" and not w.runtime.calls


def test_an_ingress_name_that_escapes_the_source_directory_is_refused(staged):
    w = staged
    directory = pipeline.source_dir(w.ctx, w.source)
    (directory / "text.md").rename(directory / "..\\text.md")
    w.build()
    assert source_row(w)["status"] == "failed" and not w.runtime.calls


def test_an_oversized_ingress_file_is_refused(staged):
    w = staged
    w.ctx.config = replace(w.ctx.config, max_upload_bytes=4)
    w.build()
    assert source_row(w)["status"] == "failed" and not w.runtime.calls


def test_an_ingress_file_changed_during_capture_is_refused(staged, monkeypatch):
    w = staged
    module = w.module
    saved = pipeline.source_dir(w.ctx, w.source) / "text.md"
    original = module.RawArtifactStore

    class Racing(original):
        def put_stream(self, source):
            saved.write_bytes(FIRST_TEXT.encode() + b" changed")
            return super().put_stream(source)

    monkeypatch.setattr(module, "RawArtifactStore", Racing)
    w.build()
    row_ = source_row(w)
    assert row_["status"] == "failed" and not row_["managed"]


# ----------------------------------------------------- options and resources


def test_build_options_come_from_the_effective_configuration(setup, monkeypatch):
    w = setup
    w.quiet_jobs()
    w.ctx.config = replace(
        w.ctx.config,
        chunk_size_chars=900,
        chunk_overlap_chars=120,
        openie_workers=3,
        max_upload_bytes=1_234_567,
        max_text_chars=456_789,
    )
    w.store.update_settings({"synonymy_threshold": 0.55})
    source = w.stage_text()
    captured = {}
    module = w.module

    def spy(ctx, **kwargs):
        captured.update(kwargs)
        return receipt(kwargs["source_id"])

    monkeypatch.setattr(module, "build_plain_source", spy)
    w.build(source)
    options = captured["options"]
    assert (options.chunk_size_chars, options.chunk_overlap_chars) == (900, 120)
    assert options.synonymy_threshold == 0.55 and options.workers == 3
    assert options.max_decoded_chars == 456_789 and options.allow_empty is False
    limits = options.capture_limits
    assert limits.max_inputs == 1 and limits.max_input_bytes == 1_234_567
    assert limits.max_total_bytes == 1_234_567


@pytest.mark.parametrize(
    "fields",
    [
        {"chunk_size_chars": 10},
        {"chunk_size_chars": 900, "chunk_overlap_chars": 800},
        {"max_text_chars": 0},
        {"openie_workers": 0},
        {"max_upload_bytes": 0},
    ],
)
def test_out_of_contract_configuration_is_refused_rather_than_truncated(setup, fields):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    w.ctx.config = replace(w.ctx.config, **fields)
    w.build(source)
    assert source_row(w)["status"] == "failed"
    assert not w.runtime.calls and not knowledge_root(w.ctx).exists()


def test_the_raw_root_and_embedding_cache_appear_only_for_a_managed_build(setup, monkeypatch):
    w = setup
    monkeypatch.setattr(w.ctx, "ollama", w.legacy_ollama)
    legacy = pipeline.add_text(w.ctx, "Legacy", FIRST_TEXT)
    wait(w.ctx)
    assert pipeline.reindex(w.ctx, legacy) is True
    wait(w.ctx)
    citations(w.ctx)
    assert not knowledge_root(w.ctx).exists()

    monkeypatch.setattr(w.ctx, "ollama", w.managed_ollama)
    w.source = pipeline.add_text(w.ctx, "Managed", FIRST_TEXT, owner_id=w.user, build_actor=w.actor)
    wait(w.ctx)
    assert source_row(w)["managed"]
    assert (knowledge_root(w.ctx) / "raw-v1").is_dir()
    assert (knowledge_root(w.ctx) / "cache" / "embeddings-v1").is_dir()


def test_the_coordinator_is_called_outside_every_transaction_with_job_cancellation(setup, monkeypatch):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    captured = {}
    module = w.module

    def spy(ctx, **kwargs):
        assert not ctx.store.in_ambient_transaction()
        assert not getattr(w.transaction_state, "depth", 0)
        captured.update(kwargs)
        return receipt(kwargs["source_id"])

    monkeypatch.setattr(module, "build_plain_source", spy)
    w.build(source)
    assert captured["should_stop"]() is False
    w.ctx.jobs._cancelled[pipeline.job_key(source)] = Event()
    w.ctx.jobs._cancelled[pipeline.job_key(source)].set()
    assert captured["should_stop"]() is True


# -------------------------------------------------------- progress mapping


def record_updates(ctx) -> list[dict]:
    seen: list[dict] = []
    original = ctx.store.update_source

    def spy(source_id, **fields):
        seen.append(dict(fields))
        return original(source_id, **fields)

    ctx.store.update_source = spy
    return seen


def test_bootstrap_progress_is_mapped_to_source_presentation_only(setup):
    w = setup
    w.quiet_jobs()
    source = w.stage_text(LONG_TEXT)
    updates = record_updates(w.ctx)
    w.build(source)
    assert all(
        set(u) <= {"status", "stage", "progress_done", "progress_total", "error", "meta_json"}
        for u in updates
    )
    for update in updates:
        meta = json.loads(update.get("meta_json") or "{}")
        assert not {"status", "stage", "error", "progress_done", "progress_total"} & set(meta)
    stages = [u["stage"] for u in updates if "stage" in u]
    assert stages[0] == "capture" and stages[-1] == "ready"
    assert "extract" in stages and not any(s.startswith("refreshing") for s in stages)


def test_refresh_progress_keeps_the_source_ready_and_marks_the_refresh_stage(setup):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    w.build(source, operation="op-1")
    (pipeline.source_dir(w.ctx, source) / "text.md").write_text(LONG_TEXT)
    updates = record_updates(w.ctx)
    w.build(source, operation="op-2")
    refreshing = [u for u in updates if str(u.get("stage", "")).startswith("refreshing: ")]
    assert refreshing and all(u.get("status", "ready") == "ready" for u in updates)
    assert {u["stage"] for u in refreshing} <= {
        "refreshing: capture",
        "refreshing: extract",
        "refreshing: write",
        "refreshing: publish",
    }
    assert source_row(w)["status"] == "ready" and source_row(w)["stage"] == "ready"


def test_an_unchanged_refresh_restores_the_ready_presentation(setup):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    w.build(source, operation="op-1")
    published = source_row(w)
    w.build(source, operation="op-2")
    # The row really did enter a refresh, so its timestamp moves; nothing else may.
    served = {key: value for key, value in source_row(w).items() if key != "updated_at"}
    assert served == {key: value for key, value in published.items() if key != "updated_at"}


# ------------------------------------------------------- failure behaviour


def fail_at(w, path, status=400):
    def hook(request_path, body):
        if request_path == path:
            return httpx.Response(status, json={"error": "private provider detail"})

    w.runtime.hook = hook


@pytest.mark.parametrize("path", ["/api/tags", "/api/show", "/api/embed", "/api/chat"])
def test_a_refresh_failure_at_any_coordinator_boundary_keeps_g1(setup, path):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    w.build(source, operation="op-1")
    published = source_row(w)
    (pipeline.source_dir(w.ctx, source) / "text.md").write_text(SECOND_TEXT)
    fail_at(w, path)
    w.build(source, operation="op-2")
    row_ = source_row(w)
    assert row_["status"] == "ready" and row_["stage"] == "refresh_failed"
    assert row_["active_generation_id"] == published["active_generation_id"]
    assert row_["passages"] == published["passages"] and row_["meta"] == published["meta"]
    assert "private" not in (row_["error"] or "")
    assert FIRST_TEXT in citations(w.ctx)


def test_a_refresh_failure_at_publication_keeps_g1(setup, monkeypatch):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    w.build(source, operation="op-1")
    published = source_row(w)
    (pipeline.source_dir(w.ctx, source) / "text.md").write_text(SECOND_TEXT)

    def boom(*args, **kwargs):
        raise RuntimeError("private publication detail")

    monkeypatch.setattr(w.store, "publish_staged_generation", boom)
    w.build(source, operation="op-2")
    row_ = source_row(w)
    assert row_["status"] == "ready" and row_["stage"] == "refresh_failed"
    assert row_["active_generation_id"] == published["active_generation_id"]
    assert FIRST_TEXT in citations(w.ctx)


def test_an_initial_bootstrap_failure_fails_the_source_generically(setup):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    fail_at(w, "/api/chat")
    w.build(source)
    row_ = source_row(w)
    assert row_["status"] == "failed" and row_["stage"] == "failed"
    assert not row_["managed"] and row_["active_generation_id"] is None
    assert row_["error"] and "private" not in row_["error"]


def test_a_cancelled_refresh_during_a_blocked_model_call_keeps_g1(setup):
    w = setup
    source = pipeline.add_text(w.ctx, "Notes", FIRST_TEXT, owner_id=w.user, build_actor=w.actor)
    w.source = source
    wait(w.ctx)
    published = source_row(w)
    (pipeline.source_dir(w.ctx, source) / "text.md").write_text(SECOND_TEXT)
    reached, release = Event(), Event()

    def block(path, body):
        if path == "/api/chat":
            reached.set()
            release.wait(SETTLE_SECONDS)

    w.runtime.hook = block
    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True
    assert reached.wait(SETTLE_SECONDS)
    assert w.ctx.jobs.cancel(pipeline.job_key(source)) is True
    release.set()
    wait(w.ctx)
    row_ = source_row(w)
    assert row_["status"] == "ready" and row_["stage"] == "refresh_cancelled"
    assert row_["active_generation_id"] == published["active_generation_id"]
    assert FIRST_TEXT in citations(w.ctx)


def test_a_cancelled_bootstrap_fails_the_source_without_managed_state(setup):
    w = setup
    source = pipeline.add_text(w.ctx, "Notes", FIRST_TEXT, owner_id=w.user, build_actor=w.actor)
    w.source = source
    reached, release = Event(), Event()

    def block(path, body):
        if path == "/api/chat":
            reached.set()
            release.wait(SETTLE_SECONDS)

    w.runtime.hook = block
    assert reached.wait(SETTLE_SECONDS)
    assert w.ctx.jobs.cancel(pipeline.job_key(source)) is True
    release.set()
    wait(w.ctx)
    row_ = source_row(w)
    assert row_["status"] == "failed" and row_["stage"] == "cancelled"
    assert not row_["managed"]


def test_a_tombstone_observed_during_a_build_is_never_overwritten(setup):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    w.build(source, operation="op-1")
    (pipeline.source_dir(w.ctx, source) / "text.md").write_text(SECOND_TEXT)

    def tombstone(path, body):
        if path == "/api/chat":
            tombstone_managed_source(
                w.ctx, source_id=source, actor=BuildActor.trusted_local(), operation_id="del-1"
            )

    w.runtime.hook = tombstone
    w.build(source, operation="op-2")
    row_ = source_row(w)
    assert row_["status"] == "deleted" and row_["stage"] == "tombstoned"


def test_failure_mapping_is_closed_and_generation_aware(setup):
    module = setup.module
    from hippo.ingest.accepted_inputs import CaptureTooLarge
    from hippo.ingest.prose_generation import BuildBusy, BuildCancelled
    from hippo.ingest.provenance import UnsupportedProvenanceFormat
    from hippo.ingest.readers import TooLarge
    from hippo.knowledge.access import AuthorizationChanged
    from hippo.ollama import OllamaError

    poison = "sk-secret /private/var/data/text.md ACME builds Robot. {model body}"
    errors = [
        BuildCancelled(poison),
        BuildBusy(poison),
        AuthorizationChanged(poison),
        OllamaError(poison),
        TooLarge(poison),
        UnsupportedProvenanceFormat(poison),
        CaptureTooLarge(poison),
        ValueError(poison),
        RuntimeError(poison),
        KeyError(poison),
    ]
    codes = set()
    for error in errors:
        for active in (False, True):
            failure = module.map_build_failure(error, has_active_generation=active)
            assert type(failure) is module.ManagedFailure
            text = f"{failure.status} {failure.stage} {failure.code} {failure.message}"
            assert not any(part in text for part in ("sk-secret", "/private", "ACME", "model body"))
            assert len(failure.message) <= 200 and failure.code.isascii()
            if active:
                assert failure.status == "ready"
                assert failure.stage in ("refresh_failed", "refresh_cancelled")
            else:
                assert failure.status == "failed" and failure.stage in ("failed", "cancelled")
            codes.add(failure.code)
    assert module.map_build_failure(errors[-1], has_active_generation=False).code == "operation_failed"
    assert len(codes) > 1


def test_a_stale_embedding_profile_asks_for_a_rebuild_rather_than_a_retry(setup):
    """Both are `OllamaError`s, and reading the wider row first would store the retry code."""
    module = setup.module
    from hippo.knowledge.embedding_profile import (
        EmbeddingProfileChanged,
        EmbeddingProfileMismatch,
        EmbeddingProfileUnavailable,
    )
    from hippo.ollama import OllamaError

    for error in (EmbeddingProfileMismatch("stale"), EmbeddingProfileChanged("stale")):
        for active in (False, True):
            failure = module.map_build_failure(error, has_active_generation=active)
            assert failure.code == "retrieval_rebuild_required"
            assert failure.status == ("ready" if active else "failed")
    for error in (EmbeddingProfileUnavailable("offline"), OllamaError("offline")):
        assert module.map_build_failure(error, has_active_generation=False).code == "model_unavailable"


def test_a_refresh_that_meets_a_changed_profile_reads_back_as_the_rebuild_code(setup, monkeypatch):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    w.build(source, operation="op-1")
    (pipeline.source_dir(w.ctx, source) / "text.md").write_text(SECOND_TEXT)
    from hippo.knowledge.embedding_profile import EmbeddingProfileChanged

    def stale(ctx, **kwargs):
        raise EmbeddingProfileChanged("Installed embedding model identity changed")

    monkeypatch.setattr(w.module, "build_plain_source", stale)
    w.build(source, operation="op-2")
    row_ = source_row(w)
    assert (row_["status"], row_["stage"]) == ("ready", "refresh_failed")
    assert row_["error"].startswith("retrieval_rebuild_required: ")


def test_an_unknown_failure_never_reaches_the_source_row_or_the_logs(setup, monkeypatch, caplog):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    poison = "sk-live-secret /private/var/folders/data/sources/text.md ACME builds Robot. <model body>"

    def boom(ctx, **kwargs):
        raise RuntimeError(poison)

    monkeypatch.setattr(w.module, "build_plain_source", boom)
    with caplog.at_level("DEBUG", logger="hippo"):
        w.build(source)
    row_ = source_row(w)
    # `caplog.text`, not `record.getMessage()`: a message alone omits the formatted
    # traceback, which is exactly where a leaked exception string would appear.
    recorded = json.dumps(row_, default=str) + caplog.text
    for part in ("sk-live-secret", "/private/var", "ACME builds Robot.", "model body"):
        assert part not in recorded
    assert row_["status"] == "failed" and "operation_failed" in (row_["error"] or "")


# ------------------------------------------------- G1 through a live refresh


def test_a_refresh_serves_g1_until_the_new_generation_publishes(setup):
    w = setup
    source = pipeline.add_text(w.ctx, "Notes", FIRST_TEXT, owner_id=w.user, build_actor=w.actor)
    w.source = source
    wait(w.ctx)
    first = source_row(w)["active_generation_id"]
    seen = []

    def inspect(path, body):
        if path == "/api/chat":
            assert w.store.get_source(source)["active_generation_id"] == first
            seen.append(citations(w.ctx))

    with query_session(w.ctx, EVERYTHING, structural=True) as held:
        held_texts = {c.text for c in held.graph.original_citations}
        w.runtime.hook = inspect
        (pipeline.source_dir(w.ctx, source) / "text.md").write_text(SECOND_TEXT)
        assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True
        wait(w.ctx)
        assert {c.text for c in held.graph.original_citations} == held_texts
    assert seen and all(FIRST_TEXT in texts for texts in seen)
    second = source_row(w)["active_generation_id"]
    assert second != first and citations(w.ctx) == {SECOND_TEXT}


# ------------------------------------------- destructive-operation negatives


@pytest.fixture
def no_destruction(setup, monkeypatch):
    w = setup

    def boom(name):
        def refuse(*args, **kwargs):
            pytest.fail(f"managed attempt called {name}")

        return refuse

    for name in (
        "delete_source",
        "delete_passages_for_source",
        "delete_code_nodes_for_source",
        "remove_orphans",
        "discard_generation",
        "collect_generation",
    ):
        monkeypatch.setattr(w.store, name, boom(f"store.{name}"), raising=False)
    monkeypatch.setattr(pipeline, "_clear_passages", boom("pipeline._clear_passages"))
    monkeypatch.setattr(shutil, "rmtree", boom("shutil.rmtree"))
    return w


def test_managed_add_refresh_and_conversion_never_destroy_source_wide_evidence(no_destruction):
    w = no_destruction
    w.quiet_jobs()
    source = w.stage_text()
    w.store.add_passages(
        [
            {
                "id": "legacy",
                "source_id": source,
                "text": "Last good legacy",
                "title": "Legacy",
                "ordinal": 0,
                "embedding": [1.0, 0.0],
            }
        ]
    )
    w.build(source, operation="convert")
    assert source_row(w)["managed"]
    before = raw_inventory(w.ctx)
    (pipeline.source_dir(w.ctx, source) / "text.md").write_text(SECOND_TEXT)
    w.build(source, operation="refresh")
    assert source_row(w)["stage"] == "ready"
    after = raw_inventory(w.ctx)
    assert before and all(after.get(name) == data for name, data in before.items())
    assert (pipeline.source_dir(w.ctx, source) / "text.md").read_text() == SECOND_TEXT


def test_a_failed_managed_refresh_retains_every_raw_object_and_saved_byte(no_destruction):
    w = no_destruction
    w.quiet_jobs()
    source = w.stage_text()
    w.build(source, operation="op-1")
    before = raw_inventory(w.ctx)
    (pipeline.source_dir(w.ctx, source) / "text.md").write_text(SECOND_TEXT)
    fail_at(w, "/api/chat")
    w.build(source, operation="op-2")
    assert source_row(w)["stage"] == "refresh_failed"
    after = raw_inventory(w.ctx)
    assert before and all(after.get(name) == data for name, data in before.items())
    assert (pipeline.source_dir(w.ctx, source) / "text.md").read_text() == SECOND_TEXT


def test_a_failure_that_cannot_be_presented_still_reports_nothing_private(setup, monkeypatch, caplog):
    """A store outage while presenting a failure must not hand the job runner the traceback."""
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    poison = "sk-live-secret /private/var/folders/data/sources/text.md ACME builds Robot. <model body>"
    original = w.module.present

    def boom(ctx, **kwargs):
        raise RuntimeError(poison)

    def flaky(ctx, source_id, **fields):
        if fields.get("status") == "failed":
            raise RuntimeError("the store went away")
        return original(ctx, source_id, **fields)

    monkeypatch.setattr(w.module, "build_plain_source", boom)
    monkeypatch.setattr(w.module, "present", flaky)
    with caplog.at_level("DEBUG", logger="hippo"):
        w.build(source)  # must not raise: `Jobs.start` would log the whole chained traceback
    recorded = caplog.text  # includes any formatted traceback, not just the message
    for part in ("sk-live-secret", "/private/var", "ACME builds Robot.", "model body"):
        assert part not in recorded


# ------------------------------------------------ stored settings and restarts


@pytest.mark.parametrize("stored", [1.5, -0.1, "0.8", None, float("nan"), True])
def test_an_out_of_contract_stored_synonym_threshold_is_refused(setup, monkeypatch, stored):
    """The threshold reaches the profile the build's authority is bound to; it is not a hint."""
    w = setup
    monkeypatch.setattr(w.store, "get_settings", lambda: {"synonymy_threshold": stored})
    with pytest.raises(w.module.ManagedConfigurationError):
        w.module.build_options(w.ctx)


def test_a_build_refuses_a_stored_threshold_generically_and_without_a_model_call(setup, monkeypatch):
    w = setup
    w.quiet_jobs()
    source = w.stage_text()
    monkeypatch.setattr(w.store, "get_settings", lambda: {"synonymy_threshold": 2})
    w.build(source)
    row_ = source_row(w)
    assert row_["status"] == "failed" and row_["error"].startswith("invalid_configuration: ")
    assert not w.runtime.calls and not knowledge_root(w.ctx).exists()


def test_a_refresh_interrupted_by_a_restart_is_retired_without_losing_g1(setup):
    """A crash mid-refresh must not leave `refreshing: ...` on the row for ever.

    The stage is taken from a real refresh in flight rather than invented, then written
    back as the row a restart would find.
    """
    w = setup
    source = managed_source(w)
    seen: list[dict] = []

    def inspect(path, body):
        if path == "/api/chat" and not seen:
            seen.append(row_of(w, source))

    (pipeline.source_dir(w.ctx, source) / "text.md").write_text(SECOND_TEXT)
    w.runtime.hook = inspect
    assert pipeline.reindex(w.ctx, source, build_actor=w.actor) is True
    wait(w.ctx)
    w.runtime.hook = None
    (in_flight,) = seen
    assert in_flight["status"] == "ready" and in_flight["stage"].startswith("refreshing: ")
    generation = row_of(w, source)["active_generation_id"]

    w.store.update_source(source, status="ready", stage=in_flight["stage"], error=None)
    assert w.store.mark_interrupted_jobs() == 1

    recovered = row_of(w, source)
    assert (recovered["status"], recovered["stage"]) == ("ready", "refresh_failed")
    assert recovered["active_generation_id"] == generation
    code, _, message = recovered["error"].partition(": ")
    assert code == "build_interrupted"
    assert code.isascii() and 0 < len(message) <= w.module.MAX_MESSAGE_CHARS
    assert citations(w.ctx) == {SECOND_TEXT}  # the published generation never stopped serving


def test_an_interrupted_refresh_is_retired_by_the_next_ladybug_open(setup):
    if setup.store.knowledge_backend != "ladybug":
        pytest.skip("real Ladybug close/reopen contract")
    from hippo.store.ladybug import LadybugStore

    w = setup
    source = managed_source(w)
    generation = row_of(w, source)["active_generation_id"]
    w.store.update_source(source, status="ready", stage="refreshing: extract", error=None)
    w.store.close()

    reopened = LadybugStore(w.store.path)
    try:
        w.ctx.store = reopened
        reopened.on_first_connection()  # what a restart does before serving anything
        recovered = row_of(w, source)
        assert (recovered["status"], recovered["stage"]) == ("ready", "refresh_failed")
        assert recovered["error"].startswith("build_interrupted: ")
        assert recovered["active_generation_id"] == generation
        assert citations(w.ctx) == {FIRST_TEXT}
    finally:
        reopened.close()


# --------------------------------------------------------- managed delete


def row_of(w, source_id) -> dict:
    return {key: value for key, value in w.store.get_source(source_id).items() if key != "generation_lock"}


def rows_of(w) -> dict[str, dict]:
    return {source["id"]: row_of(w, source["id"]) for source in w.store.list_sources()}


def data_inventory(ctx) -> dict[str, bytes]:
    """Every saved byte below the data directory: ingress files, raw objects, cache entries."""
    root = Path(ctx.config.data_dir)
    if not root.is_dir():
        return {}
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def suppressions(w, source_id) -> list:
    return [
        r
        for r in w.store._knowledge_rows("Suppression")
        if r.target_kind == "source" and r.target_id == source_id
    ]


def managed_source(w, text=FIRST_TEXT, name="Notes") -> str:
    """One published managed source, built through the coordinator."""
    source = pipeline.add_text(w.ctx, name, text, owner_id=w.user, build_actor=w.actor)
    wait(w.ctx)
    assert w.store.get_source(source)["managed"], "the source was not built as managed evidence"
    return source


def legacy_source(w, monkeypatch, name="Legacy", text="Zed Corp is located in Austin.") -> str:
    """One ordinary legacy source with real passages, indexed by the legacy pipeline."""
    monkeypatch.setattr(w.ctx, "ollama", w.legacy_ollama)
    try:
        source = pipeline.add_text(w.ctx, name, text)
        wait(w.ctx)
    finally:
        monkeypatch.setattr(w.ctx, "ollama", w.managed_ollama)
    assert w.store.passage_ids_for_source(source)
    return source


@pytest.fixture
def refuse_destruction(setup, monkeypatch):
    """Every destructive operation raises. A managed delete must reach none of them.

    The store's own cleanup and `shutil.rmtree` are refused for the whole test; a
    managed build calls neither. File removal is only refused inside `w.refusing()`,
    because an ordinary capture does unlink its own staging spool below the data
    directory -- so the window is exactly the delete under test.
    """
    w = setup
    destroyed: list[str] = []
    w.destroyed = destroyed
    root = Path(w.ctx.config.data_dir).resolve()
    armed: list[bool] = []

    def boom(name):
        def refuse(*args, **kwargs):
            destroyed.append(name)
            raise RuntimeError(f"a managed delete never calls {name}")

        return refuse

    for name in (
        "delete_source",
        "delete_passages_for_source",
        "delete_code_nodes_for_source",
        "remove_orphans",
        "discard_generation",
        "collect_generation",
    ):
        monkeypatch.setattr(w.store, name, boom(f"store.{name}"), raising=False)
    monkeypatch.setattr(pipeline, "_clear_passages", boom("pipeline._clear_passages"))
    monkeypatch.setattr(shutil, "rmtree", boom("shutil.rmtree"))

    def guarded(name):
        original = getattr(os, name)
        refuse = boom(f"os.{name}")

        def maybe(path, *args, **kwargs):
            # Disarmed, this must not even look at the argument: a capture's own spool
            # cleanup passes a bare name with a `dir_fd`, which does not resolve here.
            if not armed:
                return original(path, *args, **kwargs)
            resolved = Path(path).resolve()
            if resolved == root or root in resolved.parents:
                return refuse(path, *args, **kwargs)
            return original(path, *args, **kwargs)

        return maybe

    for name in ("unlink", "remove", "rmdir"):  # `Path.unlink`/`Path.rmdir` reach os too
        monkeypatch.setattr(os, name, guarded(name))

    @contextmanager
    def refusing():
        armed.append(True)
        try:
            yield destroyed
        finally:
            armed.clear()

    w.refusing = refusing
    return w


def test_deleting_a_managed_source_suppresses_it_and_removes_nothing(refuse_destruction):
    w = refuse_destruction
    source = managed_source(w)
    other = managed_source(w, SECOND_TEXT, "Other")
    generation = row_of(w, source)["active_generation_id"]
    before_other, before_files = row_of(w, other), data_inventory(w.ctx)

    with w.refusing():
        assert pipeline.delete_source(w.ctx, source, build_actor=w.actor) is None

    deleted = row_of(w, source)
    assert (deleted["status"], deleted["stage"]) == ("deleted", "tombstoned")
    assert deleted["active_generation_id"] == generation  # retained for authorized history
    assert w.store.validate_generation_seal(generation).ready
    (barrier,) = [s.restoration_barrier for s in suppressions(w, source)]
    assert OPERATION_ID.match(barrier)
    assert w.destroyed == []
    assert data_inventory(w.ctx) == before_files
    assert row_of(w, other) == before_other
    assert citations(w.ctx) == {SECOND_TEXT}  # the current view excludes it at once


def test_a_managed_delete_takes_the_supplied_operation_identity_or_a_fresh_bounded_one(setup):
    w = setup
    first, second = managed_source(w), managed_source(w, SECOND_TEXT, "Other")
    pipeline.delete_source(w.ctx, first, build_actor=w.actor, operation_id="delete.42")
    pipeline.delete_source(w.ctx, second, build_actor=w.actor)
    assert [s.restoration_barrier for s in suppressions(w, first)] == ["delete.42"]
    (generated,) = [s.restoration_barrier for s in suppressions(w, second)]
    assert OPERATION_ID.match(generated) and generated != "delete.42"


def test_a_managed_delete_refuses_an_unbounded_operation_identity_before_any_mutation(refuse_destruction):
    w = refuse_destruction
    source = managed_source(w)
    before, files = row_of(w, source), data_inventory(w.ctx)
    with w.refusing(), pytest.raises(w.module.ManagedDispatchError):
        pipeline.delete_source(w.ctx, source, build_actor=w.actor, operation_id="not a token!")
    assert w.destroyed == [] and suppressions(w, source) == []
    assert row_of(w, source) == before and data_inventory(w.ctx) == files


def test_deleting_a_managed_source_without_an_actor_refuses_before_any_legacy_hook(refuse_destruction):
    w = refuse_destruction
    source = managed_source(w)
    before, files = row_of(w, source), data_inventory(w.ctx)
    with w.refusing(), pytest.raises(w.module.ManagedActorRequired):
        pipeline.delete_source(w.ctx, source)
    assert w.destroyed == [] and suppressions(w, source) == []
    assert row_of(w, source) == before and data_inventory(w.ctx) == files
    assert citations(w.ctx) == {FIRST_TEXT}


@pytest.mark.parametrize("offered", [False, True])
def test_deleting_an_unmanaged_source_keeps_the_legacy_physical_delete(setup, monkeypatch, offered):
    """An actor never converts a delete: an unmanaged source is still forgotten outright."""
    w = setup
    source = legacy_source(w, monkeypatch)
    folder = pipeline.source_dir(w.ctx, source)
    assert folder.is_dir()
    version = w.store.graph_version()

    pipeline.delete_source(w.ctx, source, build_actor=w.actor if offered else None)

    assert w.store.get_source(source) is None
    assert w.store.passage_ids_for_source(source) == []
    assert w.store.stats()["entities"] == 0  # orphans swept, exactly as before
    assert not folder.exists() and w.store.graph_version() > version


def test_deleting_a_tombstoned_source_answers_like_an_unavailable_source(refuse_destruction):
    w = refuse_destruction
    source = managed_source(w)
    pipeline.delete_source(w.ctx, source, build_actor=w.actor, operation_id="delete.1")
    before, files = row_of(w, source), data_inventory(w.ctx)
    epochs = (w.store.suppression_epoch(), w.store.authorization_epoch())
    trusted = BuildActor.trusted_local()

    with w.refusing():
        with pytest.raises(AuthorizationChanged):  # a reader retry reveals nothing
            pipeline.delete_source(w.ctx, source, build_actor=w.actor, operation_id="delete.2")
        # An internal caller replaying its own operation is idempotent, and adds no epoch.
        assert pipeline.delete_source(w.ctx, source, build_actor=trusted, operation_id="delete.1") is None
        with pytest.raises(AuthorizationChanged):
            pipeline.delete_source(w.ctx, source, build_actor=trusted, operation_id="delete.9")

    assert (w.store.suppression_epoch(), w.store.authorization_epoch()) == epochs
    assert len(suppressions(w, source)) == 1
    assert w.destroyed == [] and row_of(w, source) == before and data_inventory(w.ctx) == files


def test_deleting_a_tombstoned_source_without_an_actor_refuses_like_any_managed_source(refuse_destruction):
    w = refuse_destruction
    source = managed_source(w)
    pipeline.delete_source(w.ctx, source, build_actor=w.actor, operation_id="delete.1")
    before, files = row_of(w, source), data_inventory(w.ctx)
    with w.refusing(), pytest.raises(w.module.ManagedActorRequired):
        pipeline.delete_source(w.ctx, source)
    assert w.destroyed == [] and row_of(w, source) == before and data_inventory(w.ctx) == files
    assert len(suppressions(w, source)) == 1


# ------------------------------------------------------- mixed bulk reindex


@pytest.fixture
def mixed(setup, monkeypatch):
    """One managed refresh, one eligible legacy conversion, one unsupported lane, one tombstone."""
    w = setup
    w.managed = managed_source(w, FIRST_TEXT, "Managed")
    w.tombstoned = managed_source(w, LONG_TEXT, "Tombstoned")
    tombstone_managed_source(
        w.ctx, source_id=w.tombstoned, actor=BuildActor.trusted_local(), operation_id="delete.1"
    )
    monkeypatch.setattr(w.ctx, "ollama", w.legacy_ollama)
    try:
        # The eligible source is this reader's own: a legacy source somebody else owns cannot
        # be converted by them, which `test_a_failed_managed_preflight...` is about.
        w.eligible = pipeline.add_text(w.ctx, "Eligible", "Zed Corp is located in Austin.", owner_id=w.user)
        w.unsupported = pipeline.add_upload(w.ctx, "module.py", b"def f():\n    return 1\n")
        wait(w.ctx)
    finally:
        monkeypatch.setattr(w.ctx, "ollama", w.managed_ollama)
    assert w.store.passage_ids_for_source(w.unsupported)
    return w


def bulk_lanes(monkeypatch) -> tuple[list[dict], list[str]]:
    """Record each lane, its operation identity, and everything cleared before it ran."""
    seen: list[dict] = []
    prepared: list[str] = []
    module = api()
    original = pipeline._prepare_reindex

    def prepare(ctx, source_id):
        prepared.append(source_id)
        return original(ctx, source_id)

    def legacy(ctx, source, *, should_stop):
        seen.append({"mode": "legacy", "source": source["id"], "operation": None, "cleared": tuple(prepared)})

    def managed(ctx, *, source_id, actor, operation_id, job_key):
        assert type(actor) is BuildActor and job_key == f"index:{source_id}"
        seen.append(
            {"mode": "managed", "source": source_id, "operation": operation_id, "cleared": tuple(prepared)}
        )
        return receipt(source_id)

    monkeypatch.setattr(pipeline, "_prepare_reindex", prepare)
    monkeypatch.setattr(pipeline, "_read_chunk_index", legacy)
    monkeypatch.setattr(module, "run_managed_build", managed)
    return seen, prepared


def deny_one(w) -> str:
    """A saved eligible source this reader may not manage: its owner is somebody else."""
    foreign = w.store.create_source("text", "Foreign", {"file": "text.md"}, owner_id="somebody-else")
    directory = pipeline.source_dir(w.ctx, foreign)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "text.md").write_text(FIRST_TEXT)
    return foreign


def test_a_mixed_bulk_clears_only_legacy_lanes_and_submits_each_with_its_own_identity(mixed, monkeypatch):
    w = mixed
    before_tombstone = row_of(w, w.tombstoned)
    seen, prepared = bulk_lanes(monkeypatch)

    assert pipeline.reindex_all(w.ctx, build_actor=w.actor) == 3
    wait(w.ctx)

    assert prepared == [w.unsupported], "only the legacy lane may be cleared"
    lanes_by_source = {entry["source"]: entry for entry in seen}
    assert {source: entry["mode"] for source, entry in lanes_by_source.items()} == {
        w.managed: "managed",
        w.eligible: "managed",
        w.unsupported: "legacy",
    }
    operations = {entry["operation"] for entry in seen if entry["operation"]}
    assert len(operations) == 2 and all(OPERATION_ID.match(value) for value in operations)
    # Every lane saw the complete legacy clear: no job started before the last one.
    assert all(entry["cleared"] == (w.unsupported,) for entry in seen)
    assert row_of(w, w.tombstoned) == before_tombstone


def test_a_failed_managed_preflight_clears_nothing_and_starts_nothing(mixed, no_destruction, monkeypatch):
    w = mixed
    deny_one(w)
    before_rows, before_files = rows_of(w), data_inventory(w.ctx)
    seen, prepared = bulk_lanes(monkeypatch)

    assert pipeline.reindex_all(w.ctx, build_actor=w.actor) == 0

    wait(w.ctx)
    assert seen == [] and prepared == []
    assert rows_of(w) == before_rows and data_inventory(w.ctx) == before_files


def test_a_bulk_without_an_actor_refuses_before_clearing_a_managed_inventory(
    mixed, no_destruction, monkeypatch
):
    w = mixed
    before_rows, before_files = rows_of(w), data_inventory(w.ctx)
    seen, prepared = bulk_lanes(monkeypatch)

    with pytest.raises(w.module.ManagedActorRequired):
        pipeline.reindex_all(w.ctx)

    assert seen == [] and prepared == []
    assert rows_of(w) == before_rows and data_inventory(w.ctx) == before_files


def test_a_mixed_bulk_refreshes_managed_evidence_and_converts_without_a_legacy_clear(mixed, monkeypatch):
    w = mixed
    w.inline_jobs()
    monkeypatch.setattr(pipeline, "_read_chunk_index", lambda ctx, source, *, should_stop: None)
    first = row_of(w, w.managed)["active_generation_id"]
    (pipeline.source_dir(w.ctx, w.managed) / "text.md").write_text(SECOND_TEXT)

    assert pipeline.reindex_all(w.ctx, build_actor=w.actor) == 3

    assert row_of(w, w.managed)["active_generation_id"] not in (None, first)
    converted = row_of(w, w.eligible)
    assert converted["managed"] and converted["active_generation_id"]
    assert w.store.passage_ids_for_source(w.unsupported) == []  # the legacy lane was cleared
    assert row_of(w, w.tombstoned)["stage"] == "tombstoned"
    assert SECOND_TEXT in citations(w.ctx) and LONG_TEXT not in citations(w.ctx)


def test_one_lane_failing_asynchronously_leaves_every_other_source_intact(mixed, monkeypatch):
    w = mixed
    w.inline_jobs()
    monkeypatch.setattr(pipeline, "_read_chunk_index", lambda ctx, source, *, should_stop: None)
    (pipeline.source_dir(w.ctx, w.managed) / "text.md").write_text(SECOND_TEXT)
    first = row_of(w, w.managed)["active_generation_id"]
    before_raw = raw_inventory(w.ctx)

    def hook(path, body):
        if path == "/api/chat" and SECOND_TEXT in json.dumps(body):
            return httpx.Response(500, json={"error": "private provider detail"})

    w.runtime.hook = hook
    assert pipeline.reindex_all(w.ctx, build_actor=w.actor) == 3

    failed = row_of(w, w.managed)
    assert (failed["status"], failed["stage"]) == ("ready", "refresh_failed")
    assert failed["active_generation_id"] == first
    converted = row_of(w, w.eligible)
    assert converted["managed"] and converted["active_generation_id"]
    assert row_of(w, w.tombstoned)["stage"] == "tombstoned"
    assert FIRST_TEXT in citations(w.ctx)  # the failed lane's G1 still serves
    after = raw_inventory(w.ctx)
    assert before_raw and all(after.get(name) == data for name, data in before_raw.items())


# ------------------------------------------------ Ladybug close and reopen


def knowledge_rows(store, *kinds) -> dict[str, list]:
    return {kind: sorted(store._knowledge_rows(kind), key=lambda r: r.id) for kind in kinds}


def test_a_ladybug_reopen_preserves_pointers_manifests_raw_references_and_the_tombstone(setup):
    if setup.store.knowledge_backend != "ladybug":
        pytest.skip("real Ladybug close/reopen contract")
    from hippo.store.ladybug import LadybugStore

    w = setup
    published = managed_source(w, FIRST_TEXT, "Published")
    failed = managed_source(w, "Zed Corp is located in Austin.", "Failed")
    tombstoned = managed_source(w, LONG_TEXT, "Tombstoned")

    # A refresh that fails at the model leaves G1 active and the source ready.
    (pipeline.source_dir(w.ctx, failed) / "text.md").write_text(SECOND_TEXT)
    fail_at(w, "/api/chat")
    assert pipeline.reindex(w.ctx, failed, build_actor=w.actor) is True
    wait(w.ctx)
    w.runtime.hook = None
    assert row_of(w, failed)["stage"] == "refresh_failed"
    pipeline.delete_source(w.ctx, tombstoned, build_actor=w.actor, operation_id="delete.1")

    before_rows = rows_of(w)
    before_knowledge = knowledge_rows(w.store, "Artifact", "ArtifactRevision", "Suppression", "Generation")
    before_raw, before_texts = raw_inventory(w.ctx), citations(w.ctx)
    epochs = (w.store.authorization_epoch(), w.store.suppression_epoch())
    seals = {source: row_of(w, source)["active_generation_id"] for source in (published, failed, tombstoned)}

    w.store.close()
    reopened = LadybugStore(w.store.path)
    try:
        w.ctx.store = reopened
        assert rows_of(w) == before_rows
        assert knowledge_rows(reopened, "Artifact", "ArtifactRevision", "Suppression", "Generation") == (
            before_knowledge
        )
        assert (reopened.authorization_epoch(), reopened.suppression_epoch()) == epochs
        assert all(reopened.source_is_managed(source) for source in seals)
        assert all(reopened.validate_generation_seal(g).ready for g in seals.values())
        # Every sealed manifest still names a raw object that is on disk, unchanged.
        assert raw_inventory(w.ctx) == before_raw
        assert all(
            revision.raw_uri.rsplit(":", 1)[-1] in before_raw
            for revision in before_knowledge["ArtifactRevision"]
        )
        assert citations(w.ctx) == before_texts
        assert LONG_TEXT not in before_texts  # the tombstone stays out of the current view
    finally:
        reopened.close()
