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
    seen = []

    def inspect(path, body):
        if path == "/api/chat":
            assert w.store.passage_ids_for_source(source) == ["legacy"]
            assert not w.store.get_source(source)["managed"]
            seen.append(True)

    w.runtime.hook = inspect
    w.build(source)
    assert seen
    row_ = source_row(w)
    assert row_["managed"] and row_["status"] == "ready" and row_["active_generation_id"]


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
    recorded = json.dumps(row_, default=str) + "\n".join(r.getMessage() for r in caplog.records)
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
    recorded = "\n".join(r.getMessage() for r in caplog.records)
    for part in ("sk-live-secret", "/private/var", "ACME builds Robot.", "model body"):
        assert part not in recorded
