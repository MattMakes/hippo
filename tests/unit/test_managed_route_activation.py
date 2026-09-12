"""Production readers hold one structural owner and every model path dispatches dense.

This file covers the query-session and `ask.py` half of PA6. The web, MCP, CLI
and evaluation halves are appended by the later activation parts; nothing here
imports a transport, so the module stays clean under a bare `-W error`.

Two contracts are under test. First, `query_access`/`query_session` select
structural generations by default, so no production reader has to remember to
ask. Second, `ask.search`/`ask.ask`/`ask.answer_from_trace` reach their model
through `retrieval_session` over that same single owner: one acquisition, one
heartbeat, one finalizer, and a dispatch chosen from the evidence the audience
actually proved.
"""

from contextlib import contextmanager
from datetime import UTC, datetime

import numpy as np
import pytest

from hippo import ask as ask_module
from hippo.access import EVERYTHING
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.dense_session import DenseSessionUnavailable
from hippo.knowledge.embedding_profile import EmbeddingProfileChanged
from hippo.knowledge.projection import ProjectionError
from hippo.knowledge.public_errors import public_failure
from hippo.knowledge.query_access import query_session
from hippo.knowledge.snapshots import QuerySnapshotUnavailable
from hippo.ollama import OllamaError
from tests.fakes.fake_ollama import DIM
from tests.unit.test_dense_session import verified
from tests.unit.test_managed_source_inventory import empty_published
from tests.unit.test_structural_loading import published, shared_pair, unembedded_code

QUESTION = "who builds the thing?"

# Everything a leaked exception could carry, in one string.
POISON = (
    "token=sk-live-DEADBEEF /Users/someone/data/private/notes.md "
    '\'Acme Robotics is headquartered in Boulder.\' {"model":"embed:latest"}'
)


# --------------------------------------------------------------------- watching


class Watch:
    """One record of what a single call did to the session machinery."""

    def __init__(self):
        self.acquired = []
        self.closed = []
        self.heartbeats = []
        self.dispatched = []

    def once(self, heartbeats=1):
        """One acquisition, one finalizer, and one lease heartbeat per pinned snapshot.

        A managed generation pins a snapshot, so its owner runs a heartbeat; a
        purely legacy corpus pins nothing and must not start one.
        """
        assert len(self.acquired) == 1, f"expected one acquisition, saw {len(self.acquired)}"
        assert self.closed == self.acquired, "the acquired owner was not released exactly once"
        assert len(self.heartbeats) == heartbeats, (
            f"expected {heartbeats} heartbeat(s), saw {len(self.heartbeats)}"
        )


def watch(ctx, monkeypatch) -> Watch:
    """Count acquisitions, heartbeats, finalizers and the dense mode a model path dispatched."""
    from hippo.knowledge import dense_session as dense_session_module
    from hippo.knowledge.lease_heartbeat import LeaseHeartbeat

    record = Watch()
    acquire = ctx.graph_for

    def graph_for(*args, **kwargs):
        graph = acquire(*args, **kwargs)
        record.acquired.append(graph)
        close = getattr(graph, "close_snapshot", lambda: None)

        def release():
            record.closed.append(graph)
            close()

        graph.close_snapshot = release
        return graph

    monkeypatch.setattr(ctx, "graph_for", graph_for)

    start = LeaseHeartbeat.start

    def counted(self):
        record.heartbeats.append(self)
        return start(self)

    monkeypatch.setattr(LeaseHeartbeat, "start", counted)

    # One patch point for every promoted caller. `ask`, `analysis.simulate`, `evals.runner`
    # and `evals.rag_all` all reach the public rule through the module object at call time,
    # so patching the module attribute observes all four; a route module that imported the
    # name directly binds it at import and needs its own patch (see
    # `test_managed_web_surfaces.watch`). `getattr` fails loudly if the name moves.
    dispatch = getattr(dense_session_module, "retrieval_session")  # noqa: B009

    @contextmanager
    def observed(*args, **kwargs):
        with dispatch(*args, **kwargs) as session:
            # A pass-through is not a dispatch: `retrieval_session` hands an already routed
            # session straight back, and counting that would read as a second route chosen
            # for the same owner. Only a real activation yields a new session.
            if session is not kwargs.get("session"):
                record.dispatched.append(session.graph.dense_capability.mode)
            yield session

    monkeypatch.setattr(dense_session_module, "retrieval_session", observed)
    return record


def hide(store, workspace, target_kind, target_id, scope_key):
    store.put_knowledge(
        k.Suppression(
            workspace_id=workspace,
            target_kind=target_kind,
            target_id=target_id,
            scope_key=scope_key,
            created_at=datetime.now(UTC),
            reason="access_loss",
            view_applicability="all_history",
            epoch=1,
            restoration_barrier="review",
        )
    )


# ------------------------------------------------- the structural default itself


def test_query_session_selects_structural_generations_by_default(ctx):
    """A managed generation built under another embedding tag is no longer a routing failure.

    The non-structural lane requires every selected generation's profile to
    equal `ctx.ollama.embed_model`. That coupling is exactly what the default
    flip removes, so the same corpus that raises on the explicit legacy lane
    must load cleanly on the default one.
    """
    published(ctx.store, "other tag", profile="q", dimension=3)
    with query_session(ctx, EVERYTHING) as session:
        assert session.graph.selected_managed_generations
        assert {row.profile for row in session.graph.dense_vectors} == {"q"}
    # The legacy lane refuses it at whichever gate it reaches first: snapshot
    # acquisition compares the generation's profile to the configured tag, and
    # `_current_generations` compares it again during projection.
    with pytest.raises((ProjectionError, QuerySnapshotUnavailable)):
        with query_session(ctx, EVERYTHING, structural=False):
            pytest.fail("the explicit legacy lane still refuses a foreign profile")


def test_an_explicit_legacy_opt_out_is_still_honoured(ctx):
    """`structural=False` must reach `query_access`, not be swallowed by the default."""
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    with query_session(ctx, EVERYTHING, structural=False) as session:
        assert session.graph.passage_embeddings.shape[1] == DIM
    with query_session(ctx, EVERYTHING) as session:
        assert session.graph.passage_embeddings.shape[1] == 0
        assert {row.dimension for row in session.graph.dense_vectors} == {DIM}


def test_the_low_level_graph_default_stays_legacy(ctx):
    """`AppContext.graph_for` is the documented low-level legacy entry point."""
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    graph = ctx.graph_for(EVERYTHING)
    try:
        assert graph.passage_embeddings.shape[1] == DIM
        assert not graph.dense_vectors
    finally:
        close = getattr(graph, "close_snapshot", None)
        if close is not None:
            close()


# ------------------------------------------------------------- dense dispatch


def test_ask_over_verified_managed_evidence_dispatches_verified_dense_once(ctx, tmp_path, monkeypatch):
    prepared, server = verified(ctx, tmp_path)
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *args, **kwargs: {"triples": []})
    record = watch(ctx, monkeypatch)
    trace = ask_module.search(ctx, QUESTION, access=EVERYTHING)
    record.once()
    assert record.dispatched == ["verified"]
    assert trace.snapshot_ids
    # The query went through the profiled adapter, not the raw client.
    assert any(call["input"] for call in server.embeds())
    assert prepared.inputs.embedding_profile.fingerprint


def test_search_over_tag_compatible_legacy_dispatches_tag_compatible_once(ctx, monkeypatch):
    _, span = published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    record = watch(ctx, monkeypatch)
    trace = ask_module.search(ctx, QUESTION, access=EVERYTHING)
    record.once()
    assert record.dispatched == ["tag_compatible"]
    assert [p.passage_id for p in trace.passages] == [span.id]


def test_a_purely_legacy_corpus_still_ranks_its_passages(ctx, monkeypatch, sample_text):
    from tests.unit.test_ask import index_sample

    index_sample(ctx, sample_text)
    record = watch(ctx, monkeypatch)
    trace = ask_module.search(ctx, "Where is Acme Robotics headquartered?")
    record.once(heartbeats=0)
    assert record.dispatched == ["tag_compatible"]
    assert trace.passages[0].title == "The company"
    assert not trace.used_dpr_fallback


@pytest.mark.parametrize("enrich", [unembedded_code, shared_pair], ids=["code", "relation"])
def test_code_only_and_relation_only_support_do_not_change_dispatch(ctx, monkeypatch, enrich):
    published(ctx.store, "support", profile=ctx.ollama.embed_model, dimension=2, enrich=enrich)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *a, **k: np.array([1.0, 0.0], dtype=np.float32))
    record = watch(ctx, monkeypatch)
    trace = ask_module.search(ctx, QUESTION, access=EVERYTHING)
    record.once()
    assert record.dispatched == ["tag_compatible"]
    assert trace.graph_version


def test_an_empty_authorized_corpus_falls_back_without_one_model_call(ctx, monkeypatch):
    empty_published(ctx.store, "empty", profile=ctx.ollama.embed_model)

    class Offline:
        def __getattribute__(self, name):
            pytest.fail(f"an empty corpus reached the model through {name}")

    record = watch(ctx, monkeypatch)
    monkeypatch.setattr(ctx, "ollama", Offline())
    trace = ask_module.search(ctx, QUESTION, access=EVERYTHING)
    record.once()
    assert record.dispatched == ["legacy"]
    assert trace.used_dpr_fallback and trace.fallback_reason == "the memory is empty"


def test_a_mixed_profile_corpus_denies_before_any_model_text_dispatch(ctx, tmp_path, monkeypatch):
    _, server = verified(ctx, tmp_path)
    published(ctx.store, "tag managed", profile=ctx.ollama.embed_model)
    before = list(server.calls)
    with pytest.raises(DenseSessionUnavailable) as caught:
        ask_module.ask(ctx, QUESTION, access=EVERYTHING)
    assert caught.value.reason == "mixed_modes"
    failure = public_failure(caught.value)
    assert (failure.code, failure.http_status) == ("retrieval_rebuild_required", 409)
    assert server.calls == before, "a mixed corpus must not reach /api/show, /api/embed or /api/chat"


def test_hidden_wrong_profile_evidence_cannot_change_routing(ctx, tmp_path, monkeypatch):
    prepared, server = verified(ctx, tmp_path)
    for span in prepared.inputs.evidence.spans:
        hide(ctx.store, prepared.inputs.evidence.workspace_id, "span", span.id, "hidden original")
    _, visible = published(ctx.store, "tag visible", profile=ctx.ollama.embed_model, dimension=2)
    before = len(server.calls)
    record = watch(ctx, monkeypatch)
    trace = ask_module.search(ctx, QUESTION, access=EVERYTHING)
    record.once()
    assert record.dispatched == ["tag_compatible"]
    assert [p.passage_id for p in trace.passages] == [visible.id]
    added = server.calls[before:]
    assert not [path for path, _ in added if path == "/api/show"], (
        "hidden verified evidence must not make the tag lane resolve a profile"
    )


# ------------------------------------------------ denial between owner and output


def test_authorization_change_during_output_denies_and_keeps_its_own_response(ctx, monkeypatch):
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    original = ask_module._answer_from_trace

    def revoke(graph, model, trace):
        ctx.store._bump_authorization_epoch()
        return original(graph, model, trace)

    monkeypatch.setattr(ask_module, "_answer_from_trace", revoke)
    with pytest.raises(AuthorizationChanged) as caught:
        ask_module.ask(ctx, QUESTION, access=EVERYTHING)
    assert public_failure(caught.value) is None, "authorization keeps the existing permission response"


def test_embedding_tag_change_during_output_denies_with_a_rebuild_code(ctx, monkeypatch):
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    original = ask_module._answer_from_trace

    def retag(graph, model, trace):
        ctx.ollama.embed_model = "some-other-tag"
        return original(graph, model, trace)

    monkeypatch.setattr(ask_module, "_answer_from_trace", retag)
    with pytest.raises(EmbeddingProfileChanged) as caught:
        ask_module.ask(ctx, QUESTION, access=EVERYTHING)
    failure = public_failure(caught.value)
    assert (failure.code, failure.http_status) == ("retrieval_rebuild_required", 409)


# ----------------------------------------------------------- offline model paths


@pytest.mark.parametrize("blocked", ["/api/show", "/api/embed", "chat"])
def test_a_blocked_model_endpoint_is_unavailable_and_never_public_text(ctx, tmp_path, monkeypatch, blocked):
    _, server = verified(ctx, tmp_path)

    def block(path, body):
        if path == blocked:
            raise OllamaError(POISON)
        return None

    if blocked == "chat":
        # The metadata server answers embeddings only, so block the chat surface
        # on the client rather than pretending it serves /api/chat.
        def refuse(*args, **kwargs):
            raise OllamaError(POISON)

        monkeypatch.setattr(ctx.ollama, "chat_json", refuse)
        monkeypatch.setattr(ctx.ollama, "chat_text", refuse)
    server.hook = block
    with pytest.raises(OllamaError) as caught:
        ask_module.ask(ctx, QUESTION, access=EVERYTHING)
    failure = public_failure(caught.value)
    assert (failure.code, failure.message, failure.http_status) == (
        "retrieval_unavailable",
        "Retrieval service is unavailable",
        503,
    )
    rendered = failure.code + failure.message
    for secret in ("sk-live-DEADBEEF", "/Users/someone", "Acme Robotics", "embed:latest"):
        assert secret not in rendered


def test_a_graph_only_reader_still_works_while_the_model_is_blocked(ctx, monkeypatch):
    """Structural selection is the default, so a graph read must not touch the model."""
    _, span = published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)

    class Offline:
        def __getattribute__(self, name):
            pytest.fail(f"a graph-only reader touched the model through {name}")

    monkeypatch.setattr(ctx, "ollama", Offline())
    with query_session(ctx, EVERYTHING) as session:
        assert [p.id for p in session.graph.passages] == [span.id]
        session.validate()


# ------------------------------------------------------------- borrowed owners


def test_ask_borrows_a_structural_owner_without_reacquiring_a_graph(ctx, monkeypatch):
    _, span = published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    record = watch(ctx, monkeypatch)
    with query_session(ctx, EVERYTHING) as owner:
        trace = ask_module.search(ctx, QUESTION, session=owner)
        answer = ask_module.answer_from_trace(ctx, trace, session=owner)
        assert answer.retrieval_passage_ids == [span.id]
    record.once()
    assert record.dispatched == ["tag_compatible", "tag_compatible"]


def test_an_already_dispatched_session_is_not_re_resolved(ctx, tmp_path, monkeypatch):
    """A caller that already holds a `retrieval_session` pays for no second profile probe."""
    from hippo.knowledge.dense_session import retrieval_session

    _, server = verified(ctx, tmp_path)
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *args, **kwargs: {"triples": []})
    with retrieval_session(ctx, EVERYTHING) as session:
        record = watch(ctx, monkeypatch)
        before = [path for path, _ in server.calls]
        trace = ask_module.search(ctx, QUESTION, session=session)
        assert trace.snapshot_ids == session.graph.snapshot_ids
        added = server.calls[len(before) :]
    assert record.acquired == []
    # `/api/tags` is the live-identity recheck every guarded model call already makes.
    # A re-resolution would show up as a fresh `/api/show` and a second probe embedding.
    assert not [path for path, _ in added if path == "/api/show"], (
        "an activated session must not re-resolve its profile"
    )
    assert not [
        body
        for path, body in added
        if path == "/api/embed" and any("probe" in text for text in body.get("input", ()))
    ]


def test_the_dispatch_rule_is_public_and_owns_every_borrow_decision(ctx, tmp_path, monkeypatch):
    """`retrieval_session` itself decides own, wrap or pass through -- no private helper.

    `ask._dispatch` used to hold this rule, and `analysis/simulate.py` and `evals/runner.py`
    imported it privately (the 4d review's finding 1). It was also weaker than the borrow
    checks it wrapped: its pass-through branch dropped the caller's `access` where
    `_session` refuses it. The rule now lives beside those checks, so a pass-through is
    subject to them too.
    """
    from hippo.knowledge.dense_session import retrieval_session

    _, server = verified(ctx, tmp_path)
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *args, **kwargs: {"triples": []})
    with retrieval_session(ctx, EVERYTHING) as session:
        before = len(server.calls)
        # Already routed: the same owner comes back, and no second profile is resolved.
        with retrieval_session(ctx, session=session) as again:
            assert again is session
        assert not [path for path, _ in server.calls[before:] if path == "/api/show"]

        # An audience alongside a borrow is refused even now that the borrow is a no-op.
        with pytest.raises(DenseSessionUnavailable) as caught:
            with retrieval_session(ctx, EVERYTHING, session=session):
                pytest.fail("a borrowed session must keep its own audience")
        assert caught.value.reason == "invalid_borrow"

        # And so are settings the held session never captured.
        with pytest.raises(DenseSessionUnavailable) as caught:
            with retrieval_session(ctx, settings={"qa_top_k": 1}, session=session):
                pytest.fail("a pass-through must not silently widen the held settings")
        assert caught.value.reason == "invalid_borrow"


def test_no_module_reaches_dense_dispatch_through_a_private_helper():
    """The promotion is only done when the private symbol is gone from every importer."""
    from hippo.analysis import simulate as simulate_module
    from hippo.evals import runner as runner_module

    assert not hasattr(ask_module, "_dispatch")
    for module in (ask_module, simulate_module, runner_module):
        assert not hasattr(module, "_dispatch"), module.__name__


def test_a_borrowed_legacy_session_fails_closed(ctx):
    """A non-structural owner cannot back a dense answer; it must not silently degrade."""
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    with query_session(ctx, EVERYTHING, structural=False) as owner:
        with pytest.raises(DenseSessionUnavailable) as caught:
            ask_module.search(ctx, QUESTION, session=owner)
        assert caught.value.reason == "invalid_borrow"
        assert public_failure(caught.value).code == "operation_failed"


def test_settings_that_disagree_with_the_held_session_are_refused(ctx):
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    with query_session(ctx, EVERYTHING) as owner:
        with pytest.raises(ValueError):
            ask_module.search(ctx, QUESTION, {"qa_top_k": 1}, session=owner)


def test_a_saved_input_guard_still_runs_at_every_model_boundary(ctx):
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    checks = []

    def guard():
        checks.append(len(checks))

    ask_module.search(ctx, QUESTION, authorization_check=guard)
    assert checks, "the caller's own authorization check must still be invoked"
