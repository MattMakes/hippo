"""Actual local model HTTP and disposable storage prove complete source publication."""

import importlib
import json
from contextlib import contextmanager
from dataclasses import replace
from threading import local

import httpx
import pytest

from hippo.access import EVERYTHING, Principal
from hippo.ingest.accepted_inputs import ByteInput, ExcludedInput
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.embedding_profile import EmbeddingSpec
from hippo.knowledge.query_access import query_session
from hippo.knowledge.raw_artifacts import RawArtifactStore
from hippo.ollama import Ollama, OllamaError

RENEWAL_THREAD = "hippo-lease-renewal"


def api():
    try:
        return importlib.import_module("hippo.ingest.prose_generation")
    except ModuleNotFoundError:
        pytest.fail("Plain prose generation coordinator is missing")


class Runtime:
    def __init__(self, store, transaction_state):
        self.store, self.calls, self.hook = store, [], None
        self.transaction_state = transaction_state
        self.dim = 2
        self.digest = "a" * 64

    def handle(self, request):
        assert not getattr(self.transaction_state, "depth", 0), "HTTP inside caller transaction"
        path, body = request.url.path, json.loads(request.content or "{}")
        self.calls.append((path, body))
        if self.hook:
            result = self.hook(path, body)
            if result is not None:
                return result
        if path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "embed:latest", "digest": self.digest},
                        {"name": "chat:latest", "digest": "b" * 64},
                    ]
                },
            )
        if path == "/api/show":
            return httpx.Response(
                200,
                json={"capabilities": ["embedding"] if body["model"] == "embed:latest" else ["completion"]},
            )
        if path == "/api/embed":
            return httpx.Response(
                200,
                json={
                    "model": "embed:latest",
                    "embeddings": [[1.0] + [0.0] * (self.dim - 1) for _ in body["input"]],
                },
            )
        if path == "/api/chat":
            result = (
                {"named_entities": ["ACME", "Robot"]}
                if "named_entities" in body["format"].get("properties", {})
                else {"triples": [["ACME", "builds", "Robot"]]}
            )
            return httpx.Response(
                200, json={"model": "chat:latest", "message": {"content": json.dumps(result)}}
            )
        pytest.fail(path)

    @property
    def chats(self):
        return [body for path, body in self.calls if path == "/api/chat"]


@pytest.fixture
def setup(ctx, tmp_path, monkeypatch):
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
    source = store.create_source("text", "Notes", {"file": "notes.md"}, owner_id=user)
    workspace = store.get_source(source)["workspace_id"]
    store.put_knowledge(
        k.WorkspaceMembership(
            workspace_id=workspace, principal_id=user, mapping_authority="local", enabled=True, policy_epoch=1
        )
    )
    store.set_meta("reviewed_mapping_authorities", ["local"])
    actor = BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual")))
    runtime = Runtime(store, transaction_state)
    ctx.ollama = Ollama(
        "http://local-model",
        "chat:latest",
        "embed:latest",
        num_ctx=8192,
        client=httpx.Client(base_url="http://local-model", transport=httpx.MockTransport(runtime.handle)),
    )
    raw = RawArtifactStore(tmp_path / "raw", max_object_bytes=2_000_000)
    from types import SimpleNamespace

    class Setup(SimpleNamespace):
        @property
        def module(self):
            return api()

    return Setup(**locals())


def build(w, *, text="ACME builds Robot.", inputs=None, operation="op", **kwargs):
    return w.module.build_plain_source(
        w.ctx,
        source_id=w.source,
        actor=kwargs.pop("actor", w.actor),
        inputs=tuple(inputs) if inputs is not None else (ByteInput("notes.md", text.encode()),),
        options=kwargs.pop("options", w.module.PlainBuildOptions()),
        raw_store=w.raw,
        embedding_spec=EmbeddingSpec(),
        operation_id=operation,
        should_stop=kwargs.pop("should_stop", lambda: False),
        **kwargs,
    )


def serving_source(w):
    # The backend lock counter is synchronization metadata, not serving state.
    return {key: value for key, value in w.store.get_source(w.source).items() if key != "generation_lock"}


def active_rows(w):
    identity = w.store.get_source(w.source).get("active_generation_id")
    return [row for row in w.store.load_passages() if row.get("generation_id") == identity]


def test_bootstrap_uses_real_http_and_publishes_complete_bound_originals(setup):
    w = setup
    before = w.store.authorization_epoch()
    result = build(w)
    source = w.store.get_source(w.source)
    assert result.outcome == "published" and source["active_generation_id"] == result.generation_id
    assert source["managed"] and source["status"] == "ready"
    assert len(w.runtime.chats) == 2
    gen = w.store._generation(result.generation_id)
    assert w.store.validate_generation_seal(gen.id).ready
    assert json.loads(gen.coverage_json)["embedding_mode"] == "verified_v1"
    assert w.store.authorization_epoch() > before
    assert len(w.store._knowledge_rows("ProseExtraction")) == 1
    assert {a.kind for a in w.store._knowledge_rows("Artifact")} == {"file", "manifest"}
    assert len(w.store._knowledge_rows("GenerationMember")) == 2
    assert set(vars(result)) == {"source_id", "generation_id", "event_id", "accepted_input_hash", "outcome"}
    with query_session(w.ctx, EVERYTHING, structural=True) as session:
        assert any(c.text == "ACME builds Robot." for c in session.graph.original_citations)
        assert session.graph.facts[0].predicate == "builds"


@pytest.mark.parametrize(
    "fault",
    ["Generation", "ArtifactRevision", "EvidenceSpan", "ProseExtraction", "IndexManifest", "IndexEvent"],
)
def test_bootstrap_any_install_failure_rolls_back_legacy_serving_state(setup, monkeypatch, fault):
    w = setup
    w.store.add_passages(
        [
            {
                "id": "legacy",
                "source_id": w.source,
                "text": "Last good legacy",
                "title": "Legacy",
                "ordinal": 0,
                "embedding": [1.0, 0.0],
            }
        ]
    )
    before = serving_source(w), w.store.authorization_epoch(), w.store.graph_version()
    original = w.store._write_knowledge

    def fail(record, **kwargs):
        result = original(record, **kwargs)
        if type(record).__name__ == fault:
            raise RuntimeError("injected install failure")
        return result

    monkeypatch.setattr(w.store, "_write_knowledge", fail)
    with pytest.raises(RuntimeError, match="injected"):
        build(w)
    assert (serving_source(w), w.store.authorization_epoch(), w.store.graph_version()) == before
    assert [row["id"] for row in w.store.load_passages()] == ["legacy"]
    assert w.store._knowledge_rows("Artifact") == [] and w.store._knowledge_rows("Generation") == []


def test_refresh_keeps_g1_during_model_work_and_reuses_original_revisions(setup):
    w = setup
    first = build(w)
    revisions = {
        r.id: r for r in w.store._knowledge_rows("ArtifactRevision") if not json.loads(r.metadata_json)
    }
    seen = []

    def inspect(path, body):
        if path == "/api/chat":
            assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id
            assert len(active_rows(w)) == 1
            seen.append(True)

    w.runtime.hook = inspect
    second = build(w, operation="different-config", options=w.module.PlainBuildOptions(chunk_size_chars=500))
    assert second.generation_id != first.generation_id and seen
    assert w.store._generation(first.generation_id).status == "retired"
    assert {r.id: r for r in w.store._knowledge_rows("ArtifactRevision") if r.id in revisions} == revisions


def test_identical_input_is_noop_and_reordered_descriptors_have_same_identity(setup):
    w = setup
    inputs = (ByteInput("b.md", b"ACME builds Robot."), ByteInput("a.md", b"ACME builds Robot."))
    first = build(w, inputs=inputs)
    count = len(w.runtime.chats)
    second = build(w, inputs=inputs[::-1], operation="retry")
    assert second.outcome == "already_current" and second.generation_id == first.generation_id
    assert len(w.runtime.chats) == count and len(w.store._knowledge_rows("Generation")) == 1


def test_trusted_local_actor_publishes_without_a_reader_identity(setup):
    w = setup
    result = build(w, actor=BuildActor.trusted_local())
    assert result.outcome == "published"
    assert w.store.get_source(w.source)["active_generation_id"] == result.generation_id
    assert w.store.validate_generation_seal(result.generation_id).ready


def test_removed_workspace_membership_denies_the_build_before_any_model_request(setup):
    w = setup
    membership = next(m for m in w.store._knowledge_rows("WorkspaceMembership") if m.principal_id == w.user)
    w.store.update_knowledge(membership.replace(enabled=False, policy_epoch=2))
    with pytest.raises(AuthorizationChanged):
        build(w)
    assert not w.runtime.calls and not w.store.get_source(w.source).get("managed")


def test_input_named_like_the_manifest_keeps_a_distinct_artifact_kind(setup):
    w = setup
    from hippo.knowledge.generation_profiles import MANIFEST_EXTERNAL_ID

    result = build(w, inputs=(ByteInput(MANIFEST_EXTERNAL_ID, b"ACME builds Robot."),))
    artifacts = [a for a in w.store._knowledge_rows("Artifact") if a.external_id == MANIFEST_EXTERNAL_ID]
    assert {a.kind for a in artifacts} == {"file", "manifest"}
    assert len({a.id for a in artifacts}) == 2
    assert result.outcome == "published"
    with query_session(w.ctx, EVERYTHING, structural=True) as session:
        assert any(c.text == "ACME builds Robot." for c in session.graph.original_citations)


@pytest.mark.parametrize(
    "inputs",
    [
        (ByteInput("code.py", b"print('x')"),),
        (ByteInput("doc.pdf", b"rich"),),
        (ByteInput("binary.txt", b"\x00binary"),),
        (ExcludedInput("notes.md"),),
    ],
)
def test_unsupported_or_all_excluded_input_never_converts_source(setup, inputs):
    w = setup
    with pytest.raises(ValueError):
        build(w, inputs=inputs, options=w.module.PlainBuildOptions(allow_empty=True))
    assert not w.store.get_source(w.source).get("managed")
    assert not w.runtime.chats


@pytest.mark.parametrize("inputs", [(), (ByteInput("empty.md", b""),), (ByteInput("empty.md", b" \n "),)])
def test_authoritative_empty_requires_explicit_policy_and_complete_manifest(setup, inputs):
    w = setup
    with pytest.raises(ValueError):
        build(w, inputs=inputs)
    result = build(w, inputs=inputs, options=w.module.PlainBuildOptions(allow_empty=True))
    assert not active_rows(w) and not w.runtime.chats
    assert w.store.validate_generation_seal(result.generation_id).ready


@pytest.mark.parametrize(
    "option,value", [("max_bootstrap_rows", 1), ("max_bootstrap_bytes", 1), ("max_chunks", 1)]
)
def test_bootstrap_bound_excess_leaves_no_managed_state(setup, option, value):
    w = setup
    options = replace(w.module.PlainBuildOptions(), **{option: value})
    with pytest.raises(ValueError):
        build(
            w,
            inputs=(ByteInput("a.md", b"ACME builds Robot."), ByteInput("b.md", b"ACME builds Robot.")),
            options=options,
        )
    assert not w.store.get_source(w.source).get("managed")
    assert not w.store._knowledge_rows("Generation")


def test_refresh_model_failure_preserves_last_good_generation(setup):
    w = setup
    first = build(w)

    def fail(path, body):
        if path == "/api/chat":
            return httpx.Response(400, json={"error": "private provider detail"})

    w.runtime.hook = fail
    with pytest.raises(OllamaError):
        build(w, text="ACME now builds Robot.", operation="failure")
    assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id
    assert len(active_rows(w)) == 1
    failed = [j for j in w.store._knowledge_rows("MaintenanceJob") if j.status == "failed"]
    assert len(failed) == 1 and failed[0].error_code == "build_failed"
    assert "private" not in (w.store.get_source(w.source).get("error") or "")


def test_revocation_during_source_request_blocks_followup_and_publication(setup):
    w = setup

    def revoke(path, body):
        if path == "/api/chat":
            w.store.update_user(w.user, disabled=True)

    w.runtime.hook = revoke
    with pytest.raises(AuthorizationChanged):
        build(w)
    assert len(w.runtime.chats) == 1 and not w.store.get_source(w.source).get("managed")


def test_callback_runs_outside_transaction_and_can_cancel_bootstrap(setup):
    w = setup
    cancelled = [False]

    def progress(value):
        assert not getattr(w.transaction_state, "depth", 0)
        cancelled[0] = True

    with pytest.raises(w.module.BuildCancelled):
        build(w, should_stop=lambda: cancelled[0], on_progress=progress)
    assert not w.store.get_source(w.source).get("managed")


def test_postcommit_release_revocation_does_not_mark_published_generation_failed(setup, monkeypatch):
    w = setup
    original = w.store.transaction
    from contextlib import contextmanager

    changed = False

    @contextmanager
    def transaction():
        nonlocal changed
        with original():
            yield
        if (
            not changed
            and not getattr(w.store, "_transaction_depth", 0)
            and getattr(w.store, "_transaction", None) is None
            and w.store.get_source(w.source).get("active_generation_id")
        ):
            changed = True
            w.store.update_user(w.user, disabled=True)

    monkeypatch.setattr(w.store, "transaction", transaction)
    with pytest.raises(AuthorizationChanged):
        build(w)
    identity = w.store.get_source(w.source)["active_generation_id"]
    assert w.store._generation(identity).status == "active"
    assert all(j.status == "completed" for j in w.store._knowledge_rows("MaintenanceJob"))


def test_setup_cannot_rebase_an_unrelated_authorization_change(setup, monkeypatch):
    w = setup
    other = w.store.create_user("unrelated", "password", "individual")
    original = w.store._write_knowledge
    changed = False

    def change(record, **kwargs):
        nonlocal changed
        result = original(record, **kwargs)
        if type(record) is k.AccessPolicy and not changed:
            changed = True
            w.store.update_user(other, display_name="unrelated mutation")
        return result

    monkeypatch.setattr(w.store, "_write_knowledge", change)
    with pytest.raises(AuthorizationChanged):
        build(w)
    assert not w.store.get_source(w.source).get("managed")


def test_changed_source_control_during_inference_never_installs_bootstrap(setup):
    w = setup

    def change(path, body):
        if path == "/api/chat":
            w.store.update_source(w.source, meta_json='{"file":"different.md"}')

    w.runtime.hook = change
    with pytest.raises(AuthorizationChanged):
        build(w)
    assert len(w.runtime.chats) == 1
    assert not w.store.get_source(w.source).get("managed")


def test_live_duplicate_operation_cannot_adopt_running_owner(setup):
    w = setup
    first = build(w)
    inspected = []

    def duplicate(path, body):
        if path == "/api/chat" and not inspected:
            inspected.append(True)
            with pytest.raises(w.module.BuildBusy):
                build(w, text="ACME now builds Robot.", operation="same-operation")
            assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id

    w.runtime.hook = duplicate
    result = build(w, text="ACME now builds Robot.", operation="same-operation")
    assert result.generation_id != first.generation_id
    assert all(j.lease_owner != "same-operation" for j in w.store._knowledge_rows("MaintenanceJob"))


def test_failed_refresh_retry_cleans_only_failed_generation_before_rebuild(setup):
    w = setup
    first = build(w)

    def fail(path, body):
        if path == "/api/chat":
            return httpx.Response(400, json={"error": "failure"})

    w.runtime.hook = fail
    with pytest.raises(OllamaError):
        build(w, text="ACME now builds Robot.", operation="retryable")
    failed = next(g for g in w.store._knowledge_rows("Generation") if g.status == "failed")
    w.runtime.hook = None
    result = build(w, text="ACME now builds Robot.", operation="retryable")
    assert result.generation_id == failed.id
    assert w.store._generation(first.generation_id).status == "retired"
    assert w.store.validate_generation_seal(result.generation_id).ready


def test_operation_retry_returns_original_retired_receipt_without_moving_head(setup):
    w = setup
    first = build(w, operation="first")
    second = build(w, text="ACME now builds Robot.", operation="second")
    count = len(w.runtime.chats)
    retry = build(w, operation="first")
    assert retry.outcome == "already_published"
    assert (retry.generation_id, retry.event_id) == (first.generation_id, first.event_id)
    assert w.store.get_source(w.source)["active_generation_id"] == second.generation_id
    assert len(w.runtime.chats) == count
    assert len(w.store._knowledge_rows("Generation")) == 2


def test_operation_identity_cannot_be_retargeted_to_different_inputs(setup):
    w = setup
    first = build(w)
    count = len(w.runtime.chats)
    with pytest.raises(ValueError, match="operation"):
        build(w, text="ACME now builds Robot.")
    assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id
    assert len(w.runtime.chats) == count


def test_refresh_heartbeat_renews_during_blocked_model_past_original_expiry(setup, monkeypatch):
    from datetime import timedelta
    from threading import Event

    w = setup
    first = build(w)
    clock = [w.store._now()]
    w.store._generation_clock = lambda: clock[0]
    entered, renewed = Event(), Event()
    original = w.store.renew_generation_build
    original_expiry = []

    def renew(*args, **kwargs):
        result = original(*args, **kwargs)
        if entered.is_set():
            renewed.set()
        return result

    def blocked(path, body):
        if path == "/api/chat" and not original_expiry:
            job = next(j for j in w.store._knowledge_rows("MaintenanceJob") if j.status == "running")
            original_expiry.append(job.lease_expires_at)
            clock[0] = job.lease_expires_at - timedelta(seconds=0.02)
            entered.set()
            assert renewed.wait(3), "renewal must proceed while model HTTP is blocked"
            clock[0] = original_expiry[0] + timedelta(seconds=0.01)
            assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id

    monkeypatch.setattr(w.store, "renew_generation_build", renew)
    w.runtime.hook = blocked
    result = build(
        w,
        text="ACME now builds Robot.",
        operation="renew",
        options=w.module.PlainBuildOptions(lease_duration_seconds=2, renewal_interval_seconds=0.01),
    )
    assert renewed.is_set() and result.generation_id != first.generation_id


def test_refresh_sticky_renewal_failure_denies_followup_and_keeps_g1(setup, monkeypatch):
    from threading import Event

    w = setup
    first = build(w)
    failed, entered = Event(), Event()
    before = len(w.runtime.chats)
    original = w.store.renew_generation_build

    def fail(*args, **kwargs):
        if not entered.is_set():
            return original(*args, **kwargs)
        failed.set()
        raise RuntimeError("renewal unavailable")

    def blocked(path, body):
        if path == "/api/chat":
            entered.set()
            assert failed.wait(3), "renewal must run during inference"

    monkeypatch.setattr(w.store, "renew_generation_build", fail)
    w.runtime.hook = blocked
    with pytest.raises(AuthorizationChanged):
        build(
            w,
            text="ACME now builds Robot.",
            operation="renew-failure",
            options=w.module.PlainBuildOptions(renewal_interval_seconds=0.01),
        )
    assert len(w.runtime.chats) == before + 1
    assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id


def test_bootstrap_lease_expiry_inside_commit_rolls_back_all_state(setup, monkeypatch):
    from datetime import timedelta

    w = setup
    clock = [w.store._now()]
    w.store._generation_clock = lambda: clock[0]
    original = w.store._write_knowledge

    def expire(record, **kwargs):
        result = original(record, **kwargs)
        if type(record) is k.EvidenceSpan:
            clock[0] += timedelta(seconds=1000)
        return result

    monkeypatch.setattr(w.store, "_write_knowledge", expire)
    with pytest.raises(ValueError, match="lease|fence"):
        build(w)
    assert not w.store.get_source(w.source).get("managed")
    assert not w.store._knowledge_rows("Generation")


@pytest.mark.parametrize("callback_kind", ["cancel", "progress"])
def test_coordinator_callback_failure_is_sticky_for_sibling_work(setup, callback_kind):
    w = setup
    armed = [True]

    def stop():
        if callback_kind != "cancel":
            return False
        value, armed[0] = armed[0], False
        return value

    def progress(value):
        if armed[0]:
            armed[0] = False
            raise RuntimeError("progress failed")

    run = w.module._Run(w.ctx, w.actor, w.source, w.module.PlainBuildOptions(), stop, progress)
    try:
        expected = w.module.BuildCancelled if callback_kind == "cancel" else RuntimeError
        with pytest.raises(expected):
            run.progress("work")
        with pytest.raises(expected):
            run.check()
    finally:
        run.close()


def test_pause_during_renewal_heartbeat_read_keeps_a_healthy_build_healthy(setup, monkeypatch):
    from threading import Event, current_thread

    w = setup
    entered, nulled = Event(), Event()

    class Racing:
        """Widen the one-bytecode window between _check's heartbeat test and its use.

        pause() clears the attribute before it joins the worker, so the renewal
        thread is still running when it becomes None. This descriptor holds the
        renewal thread's first read open until that has happened.
        """

        def __get__(self, run, owner=None):
            if run is None:
                return self
            worker = run.__dict__.get("heartbeat")
            if worker is not None and not entered.is_set() and current_thread().name == RENEWAL_THREAD:
                entered.set()
                nulled.wait(10)
            return worker

        def __set__(self, run, worker):
            run.__dict__["heartbeat"] = worker

    original_close = w.module.LeaseHeartbeat.close

    def close(worker):
        nulled.set()
        return original_close(worker)

    monkeypatch.setattr(w.module._Run, "heartbeat", Racing(), raising=False)
    run = w.module._Run(
        w.ctx,
        w.actor,
        w.source,
        w.module.PlainBuildOptions(renewal_interval_seconds=0.01),
        lambda: False,
        None,
    )
    try:
        run.start()
        assert entered.wait(10), "renewal worker must observe a live heartbeat"
        monkeypatch.setattr(w.module.LeaseHeartbeat, "close", close)
        run.pause()
        run.check()
    finally:
        nulled.set()
        run.close()


def test_two_detached_bootstrap_workers_admit_exactly_one_atomic_winner(setup):
    from threading import Barrier, Lock, Thread

    w = setup
    barrier, lock = Barrier(2), Lock()
    entered, outcomes = 0, []
    # A real backend serialises whole transactions under one lock; a single measured
    # Ladybug bootstrap is 18.59s, so two of them cannot finish inside a Fake-sized
    # budget. The barrier must also absorb the skew between the pre-inference phases.
    fake = w.store.knowledge_backend == "fake"
    rendezvous_budget, join_budget = (5, 10) if fake else (120, 300)

    def rendezvous(path, body):
        nonlocal entered
        if path == "/api/chat":
            with lock:
                entered += 1
                wait = entered <= 2
            if wait:
                barrier.wait(timeout=rendezvous_budget)

    def worker(operation):
        try:
            result = build(w, operation=operation)
        except BaseException as error:
            result = error
        with lock:
            outcomes.append(result)

    w.runtime.hook = rendezvous
    workers = [Thread(target=worker, args=(key,)) for key in ("one", "two")]
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join(join_budget)
        assert not thread.is_alive()
    assert sum(type(value) is w.module.BuildReceipt for value in outcomes) == 1, outcomes
    assert sum(isinstance(value, AuthorizationChanged) for value in outcomes) == 1, outcomes
    assert len(w.store._knowledge_rows("Generation")) == 1
    assert len(w.store._knowledge_rows("IndexEvent")) == 1
    assert w.store.validate_generation_seal(w.store.get_source(w.source)["active_generation_id"]).ready


def test_concurrent_build_is_not_rejected_by_another_threads_transaction(setup, monkeypatch):
    """Review finding 3: the entry probe must answer for the calling thread only.

    A process-global depth reads as "in a transaction" from every thread while any one
    thread holds one, so a build entered here was rejected with an ambient-transaction
    error the caller did not cause. The probe asks `store.in_ambient_transaction()`.
    """
    from threading import Event, Thread

    w = setup
    opened, release = Event(), Event()
    original_capture = w.module.capture_build_authority

    def capture(*args, **kwargs):
        release.set()  # The coordinator is past its ambient probe; free the other thread.
        return original_capture(*args, **kwargs)

    def holder():
        with w.store.transaction():
            opened.set()
            release.wait(60)

    monkeypatch.setattr(w.module, "capture_build_authority", capture)
    thread = Thread(target=holder)
    thread.start()
    try:
        assert opened.wait(10), "holder must own an open transaction"
        assert build(w).outcome == "published"
    finally:
        release.set()
        thread.join(60)
        assert not thread.is_alive()


@pytest.mark.parametrize("stage", ["pointer", "completed_job"])
def test_bootstrap_publication_tail_failure_rolls_back_source_and_job(setup, monkeypatch, stage):
    w = setup
    before = serving_source(w), w.store.authorization_epoch(), w.store.graph_version()
    if stage == "pointer":
        original = w.store._source_fields

        def fail(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs.get("active_generation_id"):
                raise RuntimeError("publication tail")
            return result

        monkeypatch.setattr(w.store, "_source_fields", fail)
    else:
        original = w.store._write_knowledge

        def fail(record, **kwargs):
            result = original(record, **kwargs)
            if type(record) is k.MaintenanceJob and record.status == "completed":
                raise RuntimeError("publication tail")
            return result

        monkeypatch.setattr(w.store, "_write_knowledge", fail)
    with pytest.raises(RuntimeError, match="publication tail"):
        build(w)
    assert (serving_source(w), w.store.authorization_epoch(), w.store.graph_version()) == before
    assert not w.store._knowledge_rows("Generation")
    assert not w.store._knowledge_rows("MaintenanceJob")


@pytest.mark.parametrize("changed", ["authorization", "suppression"])
def test_authority_change_after_publication_write_rolls_back_and_keeps_g1(setup, monkeypatch, changed):
    """Strict publication never reads the captured authorization epoch; the coordinator must."""
    from hippo.store.authorization import bump_epoch

    w = setup
    first = build(w)
    before = w.store.authorization_epoch()
    original_publish, original_update = w.store.publish_staged_generation, w.store.update_source
    updated = []

    def publish(*args, **kwargs):
        result = original_publish(*args, **kwargs)
        if changed == "authorization":
            w.store._bump_authorization_epoch()
        else:
            bump_epoch(w.store, "suppression_epoch")
        return result

    def update_source(*args, **kwargs):
        updated.append(kwargs)
        return original_update(*args, **kwargs)

    monkeypatch.setattr(w.store, "publish_staged_generation", publish)
    monkeypatch.setattr(w.store, "update_source", update_source)
    # The recheck between the publication write and the source presentation write is the
    # only guard for this window, so pin its message and prove the presentation never ran.
    with pytest.raises(AuthorizationChanged, match="during publication"):
        build(w, text="ACME now builds Robot.", operation="publication-race")
    assert not [call for call in updated if call.get("status") == "ready"], updated
    assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id
    assert w.store._generation(first.generation_id).status == "active"
    assert w.store.authorization_epoch() == before
    assert [e.generation_id for e in w.store._knowledge_rows("IndexEvent") if e.kind == "published"] == [
        first.generation_id
    ]
    job = next(j for j in w.store._knowledge_rows("MaintenanceJob") if j.job_key == "publication-race")
    assert job.status == "failed" and job.error_code == "build_failed"


def test_refresh_cancellation_marks_only_owned_job_cancelled(setup):
    w = setup
    first = build(w)
    stopped = [False]

    def progress(value):
        if value.phase == "extract":
            stopped[0] = True

    with pytest.raises(w.module.BuildCancelled):
        build(
            w,
            text="ACME now builds Robot.",
            operation="cancel",
            on_progress=progress,
            should_stop=lambda: stopped[0],
        )
    assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id
    job = next(j for j in w.store._knowledge_rows("MaintenanceJob") if j.job_key == "cancel")
    assert job.status == "cancelled" and job.error_code == "build_cancelled"
    assert w.store.get_source(w.source).get("active_build_id") is None


@pytest.mark.parametrize("phase", ["bootstrap", "refresh"])
@pytest.mark.parametrize("partial", [False, True])
def test_worker_start_failure_stops_and_joins_outside_transaction(setup, monkeypatch, phase, partial):
    w = setup
    if phase == "refresh":
        first = build(w)
    original_start, original_close = w.module.LeaseHeartbeat.start, w.module.LeaseHeartbeat.close
    starts, closed = [], []

    def start(worker):
        starts.append(worker)
        if phase == "bootstrap" or len(starts) == 2:
            if partial:
                original_start(worker)
            raise RuntimeError("thread start interrupted")
        return original_start(worker)

    def close(worker):
        assert not getattr(w.transaction_state, "depth", 0)
        result = original_close(worker)
        closed.append(worker)
        return result

    monkeypatch.setattr(w.module.LeaseHeartbeat, "start", start)
    monkeypatch.setattr(w.module.LeaseHeartbeat, "close", close)
    with pytest.raises(RuntimeError, match="thread start"):
        build(w, text="ACME now builds Robot.", operation="start")
    assert set(starts) <= set(closed)
    assert all(worker._thread is None or not worker._thread.is_alive() for worker in starts)
    if phase == "refresh":
        assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id
        assert (
            next(j for j in w.store._knowledge_rows("MaintenanceJob") if j.job_key == "start").status
            == "failed"
        )
    else:
        assert not w.store.get_source(w.source).get("managed")


@pytest.mark.parametrize("denial", ["suppression", "tombstone", "provider", "expired", "user"])
def test_published_receipt_still_requires_current_original_authority(setup, denial):
    from datetime import timedelta

    w = setup
    first = build(w)
    artifact = next(a for a in w.store._knowledge_rows("Artifact") if a.kind == "file")
    policy = w.store._knowledge_get("AccessPolicy", artifact.policy_id)
    if denial == "suppression":
        w.store.put_knowledge(
            k.Suppression(
                workspace_id=w.workspace,
                target_kind="artifact",
                target_id=artifact.id,
                scope_key="deny receipt",
                view_applicability="all_history",
                reason="access_loss",
                epoch=1,
                created_at=w.store._now(),
                restoration_barrier="review",
            )
        )
    elif denial == "tombstone":
        w.store.update_knowledge(artifact.replace(deleted_at=w.store._now()))
    elif denial == "provider":
        provider = policy.replace(origin="provider", scope_key="provider")
        w.store.put_knowledge(provider)
        w.store.update_knowledge(artifact.replace(policy_id=provider.id))
    elif denial == "expired":
        w.store.update_knowledge(
            policy.replace(
                verified_at=w.store._now() - timedelta(days=1),
                expires_at=w.store._now() - timedelta(seconds=1),
            )
        )
    else:
        w.store.update_user(w.user, disabled=True)
    count = len(w.runtime.chats)
    with pytest.raises(AuthorizationChanged):
        build(w)
    assert len(w.runtime.chats) == count
    assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id


def test_refresh_dimension_change_preserves_held_g1_and_conservative_raw_objects(setup, monkeypatch):
    w = setup
    first = build(w)
    blobs = {path: path.read_bytes() for path in w.tmp_path.joinpath("raw").rglob("*") if path.is_file()}
    for method in (
        "delete_source",
        "delete_passages_for_source",
        "delete_code_nodes_for_source",
        "remove_orphans",
    ):
        if hasattr(w.store, method):
            monkeypatch.setattr(w.store, method, lambda *a, **k: pytest.fail("source-wide deletion"))
    before_meta = w.store.get_meta("embedding_model")
    with query_session(w.ctx, EVERYTHING, structural=True) as held:
        w.runtime.dim = 3
        w.runtime.digest = "c" * 64
        second = build(w, text="ACME now builds Robot.", operation="profile-change")
        held.validate()
        assert {row.dimension for row in held.graph.dense_vectors} == {2}
        assert {row.generation_id for row in held.graph.dense_vectors} == {first.generation_id}
        assert w.store.get_source(w.source)["active_generation_id"] == second.generation_id
    with query_session(w.ctx, EVERYTHING, structural=True) as current:
        assert {row.dimension for row in current.graph.dense_vectors} == {3}
    assert all(path.read_bytes() == value for path, value in blobs.items())
    assert w.store.get_meta("embedding_model") == before_meta


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("same_inputs", [False, True])
def test_expired_attempt_recovery_is_source_scoped_and_uses_fresh_fence(
    setup, monkeypatch, ready, same_inputs
):
    from datetime import timedelta

    w = setup
    first = build(w)
    clock = [w.store._now()]
    w.store._generation_clock = lambda: clock[0]
    source = w.store.create_source("text", "Unrelated")
    other = k.Generation(
        source_id=source,
        status="staging",
        parser_version="1",
        linker_version="1",
        embedding_profile="tag",
        manifest_hash="other",
        created_at=clock[0],
    )
    w.store.put_knowledge(other)
    w.store.begin_managed_source(source)
    other_job = w.store.claim_generation_build(
        other.id, job_key="other", lease_owner="other-owner", lease_expires_at=clock[0] + timedelta(seconds=1)
    )
    original = w.module._seal if ready else w.module._write_batch

    def crash(store, prepared, *args, **kwargs):
        original(store, prepared, *args, **kwargs)
        job = store._knowledge_get("MaintenanceJob", kwargs["job_id"])
        clock[0] = job.lease_expires_at + timedelta(seconds=1)
        raise RuntimeError("simulated expired process")

    with monkeypatch.context() as patch:
        patch.setattr(w.module, "_seal" if ready else "_write_batch", crash)
        with pytest.raises(RuntimeError, match="simulated expired"):
            build(w, text="ACME now builds Robot.", operation="expired")
    expired = next(j for j in w.store._knowledge_rows("MaintenanceJob") if j.job_key == "expired")
    assert expired.status == "running"
    assert w.store._generation(expired.input_fingerprint).status == ("ready" if ready else "staging")
    result = build(
        w,
        text="ACME now builds Robot." if same_inputs else "ACME also builds Robot.",
        operation="expired" if same_inputs else "replacement",
    )
    assert w.store._knowledge_get("MaintenanceJob", other_job.id) == other_job
    assert w.store._generation(other.id).status == "staging"
    if same_inputs:
        new_job = w.store._knowledge_get("MaintenanceJob", expired.id)
        assert result.generation_id == expired.input_fingerprint
        assert new_job.fencing_token > expired.fencing_token and new_job.lease_owner != expired.lease_owner
    else:
        assert w.store._generation(expired.input_fingerprint).status == "failed"
        assert w.store._knowledge_get("MaintenanceJob", expired.id).status == "failed"
    assert w.store._generation(first.generation_id).status == "retired"


def test_operation_receipt_requires_its_original_publication_credentials(setup, monkeypatch):
    w = setup
    build(w)
    original = w.store._knowledge_rows

    def rows(kind):
        values = original(kind)
        return (
            [value.replace(payload_json='{"job_id":"wrong"}') for value in values]
            if kind == "IndexEvent"
            else values
        )

    monkeypatch.setattr(w.store, "_knowledge_rows", rows)
    with pytest.raises(ValueError, match="receipt|publication"):
        build(w)


def test_ladybug_reopen_preserves_receipt_original_closure_and_runtime_profile(setup):
    if setup.store.knowledge_backend != "ladybug":
        pytest.skip("real Ladybug close/reopen contract")
    from hippo.store.ladybug import LadybugStore

    w = setup
    result = build(w)
    w.store.close()
    reopened = LadybugStore(w.store.path)
    try:
        w.ctx.store = reopened
        assert reopened.validate_generation_seal(result.generation_id).ready
        with query_session(w.ctx, EVERYTHING, structural=True) as session:
            assert {row.generation_id for row in session.graph.dense_vectors} == {result.generation_id}
            assert any(row.text == "ACME builds Robot." for row in session.graph.original_citations)
            assert session.graph.facts[0].predicate == "builds"
        from hippo.knowledge.generation_profiles import validate_generation_profile

        assert (
            validate_generation_profile(
                reopened, reopened._generation(result.generation_id)
            ).profile.profile.dimension
            == 2
        )
    finally:
        reopened.close()


def test_inflight_model_return_waits_for_renewal_transaction_without_false_ambient_error(setup, monkeypatch):
    from threading import Event, Thread, current_thread

    w = setup
    build(w)
    inside, held, checking, release = Event(), Event(), Event(), Event()
    original_renew, original_check = w.store.renew_generation_build, w.module._Run.check

    def renew(*args, **kwargs):
        result = original_renew(*args, **kwargs)
        if inside.is_set() and not held.is_set():
            assert getattr(w.transaction_state, "depth", 0) > 0
            held.set()
            assert release.wait(10), "test must release renewal transaction"
        return result

    def check(run):
        if held.is_set() and not release.is_set() and current_thread().name != RENEWAL_THREAD:
            checking.set()
        return original_check(run)

    def model(path, body):
        if path == "/api/chat" and not held.is_set():
            inside.set()
            assert held.wait(10), "renewal must enter its transaction during model request"

    def unblock():
        # No wall clock: the rendezvous is what opens this window, and teardown below
        # always sets both events, so neither wait can outlive the build.
        held.wait()
        checking.wait()
        release.set()

    monkeypatch.setattr(w.store, "renew_generation_build", renew)
    monkeypatch.setattr(w.module._Run, "check", check)
    w.runtime.hook = model
    helper = Thread(target=unblock)
    helper.start()
    try:
        result = build(
            w,
            text="ACME now builds Robot.",
            operation="transaction-race",
            options=w.module.PlainBuildOptions(renewal_interval_seconds=0.01),
        )
        assert checking.is_set() and result.outcome == "published"
    finally:
        held.set()
        checking.set()
        release.set()
        helper.join(10)
        assert not helper.is_alive()


def test_large_source_input_metadata_rejects_before_model_requests_or_managed_write(setup):
    w = setup
    w.store.update_source(w.source, meta_json=json.dumps({"input_configuration": "x" * 100_000}))
    with pytest.raises(ValueError, match="budget"):
        build(w, options=w.module.PlainBuildOptions(max_bootstrap_bytes=50_000))
    assert not w.runtime.calls
    assert not w.store.get_source(w.source).get("managed")


@pytest.mark.parametrize("field,position", [("max_bootstrap_rows", 0), ("max_bootstrap_bytes", 1)])
@pytest.mark.parametrize("delta", [0, -1])
def test_bootstrap_canonical_admission_exact_boundary(setup, monkeypatch, field, position, delta):
    w = setup
    now = w.store._now()
    w.store._generation_clock = lambda: now
    original = w.module._bootstrap_bounds
    observed = []

    def capture(*args, **kwargs):
        observed.append(original(*args, **kwargs))
        raise RuntimeError("admission observation")

    with monkeypatch.context() as patch:
        patch.setattr(w.module, "_bootstrap_bounds", capture)
        with pytest.raises(RuntimeError, match="admission observation"):
            build(w)
    assert not w.store.get_source(w.source).get("managed")
    options = replace(w.module.PlainBuildOptions(), **{field: observed[0][position] + delta})
    if delta < 0:
        with pytest.raises(ValueError, match="budget"):
            build(w, options=options)
        assert not w.store.get_source(w.source).get("managed")
    else:
        assert build(w, options=options).outcome == "published"
