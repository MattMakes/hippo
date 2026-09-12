"""Analysis, evaluation and question generation over one held structural owner.

This file is the evaluation half of PA6. `test_managed_route_activation.py`
covers the `ask.py` half; the two share its `watch()` recorder, so "one
acquisition, one heartbeat per pinned snapshot, one finalizer, one dispatch"
means the same thing on both sides.

Three contracts are under test:

* the model/dense owners in this slice -- the analysis simulation, the
  evaluation runner and the static RAG-all evaluator -- reach their model
  through `retrieval_session` over the one owner they hold or borrow, and the
  layer below them never reacquires a graph;
* the graph-only owners -- `EvalAccess`, `ChangesetAccess` and the question
  maker's passage reads -- hold a *structural* session through DTO, save and
  render, and keep working while the model is unreachable;
* a corpus that cannot be routed, or a permission that changes mid-operation,
  fails before any model text and releases its pin.

Nothing here imports a transport, so the module stays clean under a bare
`-W error`.
"""

import sys
from contextlib import contextmanager

import numpy as np
import pytest

from hippo import ask as ask_module
from hippo.access import EVERYTHING
from hippo.analysis.simulate import Overrides, simulate
from hippo.evals import runner as runner_module
from hippo.evals.question_maker import generate_questions
from hippo.evals.runner import run_question, start_run
from hippo.hipporag.indexer import Chunk, index_source
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.changeset_access import ChangesetAccess
from hippo.knowledge.citations import resolve_citations
from hippo.knowledge.dense_session import DenseSessionUnavailable, retrieval_session
from hippo.knowledge.eval_access import EvalAccess
from hippo.knowledge.public_errors import public_failure
from hippo.knowledge.query_access import query_session
from tests.fakes.fake_ollama import DIM
from tests.unit.test_dense_session import verified
from tests.unit.test_managed_route_activation import watch
from tests.unit.test_managed_source_inventory import empty_published
from tests.unit.test_structural_loading import published, unembedded_code

QUESTION = "who builds the thing?"


# ------------------------------------------------------------------ fixtures


def managed(ctx, key="managed", **kwargs):
    """One published managed generation the configured embedding tag can read."""
    kwargs.setdefault("dimension", DIM)
    return published(ctx.store, key, profile=ctx.ollama.embed_model, **kwargs)


def legacy_sample(ctx, sample_text):
    """The sample corpus indexed the legacy way: passages, no generation."""
    source_id = ctx.store.create_source("sample", "Acme Robotics")
    chunks = []
    for ordinal, section in enumerate(sample_text.split("## ")[1:]):
        title, _, body = section.partition("\n")
        chunks.append(Chunk(ordinal, title.strip(), body.strip()))
    index_source(ctx.store, ctx.ollama, source_id, chunks, workers=2)
    ctx.store.update_source(source_id, status="ready")
    return source_id


def visible_passage_ids(ctx):
    """The passage ids the current audience can prove, read before any recorder is installed."""
    with query_session(ctx, EVERYTHING) as session:
        return [passage.id for passage in session.graph.passages]


def visible_node_ids(ctx):
    with query_session(ctx, EVERYTHING) as session:
        return list(session.graph.node_ids)


def order(ctx, monkeypatch):
    """Record graph acquisition, store transactions and release in the order they happen."""
    events = []
    acquire, transaction = ctx.graph_for, ctx.store.transaction

    def graph_for(*args, **kwargs):
        events.append("acquire")
        graph = acquire(*args, **kwargs)
        close = getattr(graph, "close_snapshot", lambda: None)

        def release():
            # Recorded after the real release, whose own snapshot write is a transaction too.
            close()
            events.append("close")

        graph.close_snapshot = release
        return graph

    @contextmanager
    def transact(*args, **kwargs):
        events.append("transaction")
        with transaction(*args, **kwargs):
            yield

    monkeypatch.setattr(ctx, "graph_for", graph_for)
    monkeypatch.setattr(ctx.store, "transaction", transact)
    return events


def live_saved_references(ctx):
    return [
        row
        for row in ctx.store._knowledge_rows("SnapshotReference")
        if row.released_at is None and row.kind == "saved"
    ]


def live_references(ctx):
    return [row for row in ctx.store._knowledge_rows("SnapshotReference") if row.released_at is None]


class Offline:
    """Any attribute read is a model call this operation was not allowed to make."""

    def __getattribute__(self, name):
        pytest.fail(f"a graph-only operation reached the model through {name}")


def question_row(text=QUESTION, gold=(), expected=""):
    return {"id": "q-1", "text": text, "expected_answer": expected, "gold_passage_ids": list(gold)}


def stored_set(ctx, questions):
    """A manual question set owned by this audience, created before the corpus is watched."""
    evaluation = EvalAccess(ctx, EVERYTHING)
    set_id = evaluation.create_question_set("managed questions")
    evaluation.add_questions(set_id, questions)
    return set_id


# --------------------------------------------------------- analysis simulation


def test_simulation_over_verified_managed_evidence_dispatches_verified_dense_once(ctx, tmp_path, monkeypatch):
    prepared, server = verified(ctx, tmp_path)
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *args, **kwargs: {"triples": []})
    record = watch(ctx, monkeypatch)
    outcome = simulate(ctx, QUESTION, Overrides(), access=EVERYTHING)
    record.once()
    assert record.dispatched == ["verified"]
    assert outcome.trace.snapshot_ids
    assert outcome.trace.evidence_fingerprint
    assert any(call["input"] for call in server.embeds())
    assert prepared.inputs.embedding_profile.fingerprint


def test_simulation_over_tag_compatible_managed_evidence_dispatches_once(ctx, monkeypatch):
    _, span = managed(ctx)
    record = watch(ctx, monkeypatch)
    outcome = simulate(ctx, QUESTION, Overrides(), access=EVERYTHING)
    record.once()
    assert record.dispatched == ["tag_compatible"]
    assert [p.passage_id for p in outcome.trace.passages] == [span.id]


def test_a_mixed_profile_simulation_denies_before_any_model_text(ctx, tmp_path):
    _, server = verified(ctx, tmp_path)
    published(ctx.store, "tag managed", profile=ctx.ollama.embed_model)
    before = list(server.calls)
    with pytest.raises(DenseSessionUnavailable) as caught:
        simulate(ctx, QUESTION, Overrides(reanswer=True), access=EVERYTHING)
    assert caught.value.reason == "mixed_modes"
    failure = public_failure(caught.value)
    assert (failure.code, failure.http_status) == ("retrieval_rebuild_required", 409)
    assert server.calls == before, "a mixed corpus must not reach /api/show, /api/embed or /api/chat"
    assert not live_references(ctx), "a refused dispatch must not leave a pin behind"


def test_an_empty_corpus_simulation_makes_no_model_call(ctx, monkeypatch):
    empty_published(ctx.store, "empty", profile=ctx.ollama.embed_model)
    record = watch(ctx, monkeypatch)
    monkeypatch.setattr(ctx, "ollama", Offline())
    outcome = simulate(ctx, QUESTION, Overrides(), access=EVERYTHING)
    record.once()
    assert record.dispatched == ["legacy"]
    assert outcome.trace.used_dpr_fallback and outcome.trace.fallback_reason == "the memory is empty"


def test_code_only_support_does_not_change_the_simulation_dispatch(ctx, monkeypatch):
    published(ctx.store, "support", profile=ctx.ollama.embed_model, dimension=2, enrich=unembedded_code)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *a, **k: np.array([1.0, 0.0], dtype=np.float32))
    record = watch(ctx, monkeypatch)
    outcome = simulate(ctx, QUESTION, Overrides(), access=EVERYTHING)
    record.once()
    assert record.dispatched == ["tag_compatible"]
    assert outcome.trace.graph_version


def test_a_simulation_borrowing_a_dispatched_session_reacquires_nothing(ctx, tmp_path, monkeypatch):
    """The caller already paid for a profile; simulating must not probe for it again."""
    _, server = verified(ctx, tmp_path)
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *args, **kwargs: {"triples": []})
    with retrieval_session(ctx, EVERYTHING) as session:
        record = watch(ctx, monkeypatch)
        before = len(server.calls)
        outcome = simulate(ctx, QUESTION, Overrides(), session=session)
        added = server.calls[before:]
    assert record.acquired == []
    assert outcome.trace.snapshot_ids == session.graph.snapshot_ids
    assert not [path for path, _ in added if path == "/api/show"], (
        "an activated session must not re-resolve its profile"
    )


def test_a_simulation_borrowing_a_structural_owner_keeps_its_captured_settings(ctx, monkeypatch):
    managed(ctx)
    record = watch(ctx, monkeypatch)
    with query_session(ctx, EVERYTHING, settings={"qa_top_k": 1}) as owner:
        ctx.store.update_settings({"qa_top_k": 3})
        outcome = simulate(ctx, QUESTION, Overrides(), session=owner)
        assert outcome.trace.settings["qa_top_k"] == 1
    record.once()
    assert record.dispatched == ["tag_compatible"]


def test_a_revocation_during_simulation_output_denies_and_releases_its_pin(ctx, monkeypatch):
    managed(ctx)
    original = ask_module._answer_from_trace

    def revoke(index, model, trace):
        ctx.store._bump_authorization_epoch()
        return original(index, model, trace)

    # `hippo.analysis` re-exports the `simulate` function over its own submodule name, so
    # the module object has to come from `sys.modules` rather than from attribute lookup.
    monkeypatch.setattr(sys.modules["hippo.analysis.simulate"], "_answer_from_trace", revoke)
    with pytest.raises(AuthorizationChanged) as caught:
        simulate(ctx, QUESTION, Overrides(reanswer=True), access=EVERYTHING)
    assert public_failure(caught.value) is None, "authorization keeps the existing permission response"
    assert not live_references(ctx)


# ------------------------------------------------------------ evaluation runner


def test_one_evaluation_question_holds_one_owner_and_dispatches_dense_once(ctx, monkeypatch):
    _, span = managed(ctx)
    record = watch(ctx, monkeypatch)
    result = run_question(ctx, question_row(gold=[span.id]), ctx.store.get_settings(), EVERYTHING)
    record.once()
    assert record.dispatched == ["tag_compatible"], (
        "search, answer and grading share the runner's one dispatched owner"
    )
    assert result["error"] is None
    assert [p["passage_id"] for p in result["trace"]["passages"]] == [span.id]
    assert result["trace"]["snapshot_ids"]


def test_a_stored_run_result_retains_its_snapshot_reference(ctx, monkeypatch):
    managed(ctx)
    gold = visible_passage_ids(ctx)
    set_id = stored_set(ctx, [{"text": QUESTION, "expected_answer": "", "gold_passage_ids": gold}])
    record = watch(ctx, monkeypatch)
    run_id = start_run(ctx, set_id, access=EVERYTHING)
    ctx.jobs.wait_all()
    run = ctx.store.get_run(run_id)
    assert run["status"] == "done"
    results = ctx.store.list_results(run_id)
    assert len(results) == 1 and results[0]["error"] is None
    retained = live_saved_references(ctx)
    assert retained, "a saved evaluation result must keep its generation snapshot alive"
    assert all(row.reference_key.startswith("eval_result:") for row in retained)
    # A whole run owns more than one view: the set is proved before the run starts and
    # again inside it. What must hold is that each one is released, and that the one
    # question dispatched dense exactly once.
    assert record.closed == record.acquired
    assert record.dispatched == ["tag_compatible"]


def test_a_mixed_profile_corpus_fails_its_questions_without_ending_the_run(ctx, tmp_path):
    """A corpus that cannot be routed is per-question trouble, not a store failure."""
    _, server = verified(ctx, tmp_path)
    published(ctx.store, "tag managed", profile=ctx.ollama.embed_model)
    set_id = stored_set(ctx, [{"text": QUESTION, "expected_answer": ""}])
    before = list(server.calls)
    run_id = start_run(ctx, set_id, access=EVERYTHING)
    ctx.jobs.wait_all()
    run = ctx.store.get_run(run_id)
    assert run["status"] == "done"
    assert run["summary"]["errors"] == 1
    stored = ctx.store.list_results(run_id)[0]
    assert "DenseSessionUnavailable" in stored["error"]
    assert not stored["answer"]
    assert server.calls == before, "a mixed corpus must not reach /api/show, /api/embed or /api/chat"


def test_an_empty_corpus_question_makes_no_model_call(ctx, monkeypatch):
    empty_published(ctx.store, "empty", profile=ctx.ollama.embed_model)
    record = watch(ctx, monkeypatch)
    monkeypatch.setattr(ctx, "ollama", Offline())
    result = run_question(ctx, question_row(), ctx.store.get_settings(), EVERYTHING)
    record.once()
    # An empty view has nothing to activate, so the lower layers re-wrap it; every one of
    # those is the documented no-op that touches no model and acquires no second graph.
    assert set(record.dispatched) == {"legacy"}
    assert result["error"] is None
    assert result["used_dpr_fallback"] is True


def test_a_revocation_during_a_question_denies_and_stores_no_answer(ctx, monkeypatch):
    _, span = managed(ctx)
    original = runner_module.answer_from_trace

    def revoke(*args, **kwargs):
        ctx.store._bump_authorization_epoch()
        return original(*args, **kwargs)

    monkeypatch.setattr(runner_module, "answer_from_trace", revoke)
    result = run_question(ctx, question_row(gold=[span.id]), ctx.store.get_settings(), EVERYTHING)
    assert "AuthorizationChanged" in result["error"]
    assert result["answer"] == "" and result["trace"] == {}
    assert not live_references(ctx)


def test_hidden_wrong_profile_evidence_cannot_change_evaluation_routing(ctx, tmp_path, monkeypatch):
    from tests.unit.test_managed_route_activation import hide

    prepared, server = verified(ctx, tmp_path)
    for span in prepared.inputs.evidence.spans:
        hide(ctx.store, prepared.inputs.evidence.workspace_id, "span", span.id, "hidden original")
    _, visible = published(ctx.store, "tag visible", profile=ctx.ollama.embed_model, dimension=2)
    # The metadata server answers embeddings only; the answer's own chat is not the subject here.
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *args, **kwargs: {"triples": []})
    monkeypatch.setattr(ctx.ollama, "chat_text", lambda *args, **kwargs: "an answer")
    before = len(server.calls)
    record = watch(ctx, monkeypatch)
    result = run_question(ctx, question_row(gold=[visible.id]), ctx.store.get_settings(), EVERYTHING)
    record.once()
    assert record.dispatched == ["tag_compatible"]
    assert [p["passage_id"] for p in result["trace"]["passages"]] == [visible.id]
    added = server.calls[before:]
    assert not [path for path, _ in added if path == "/api/show"], (
        "hidden verified evidence must not make the tag lane resolve a profile"
    )


# ------------------------------------------------------- graph-only evaluation owners


def test_eval_access_reads_hold_a_structural_session_with_the_model_offline(ctx, monkeypatch):
    """A generation built under another embedding tag is evidence, not a routing failure."""
    published(ctx.store, "other tag", profile="q", dimension=3)
    evaluation = EvalAccess(ctx, EVERYTHING)
    set_id = evaluation.create_question_set("questions")
    monkeypatch.setattr(ctx, "ollama", Offline())
    with evaluation.read_scope() as scope:
        assert scope.graph().selected_managed_generations
        assert scope.require_set(set_id)["id"] == set_id
    assert [row["id"] for row in EvalAccess(ctx, EVERYTHING).list_question_sets()] == [set_id]
    assert not live_references(ctx)


def test_changeset_reads_and_mutations_hold_a_structural_session(ctx, monkeypatch, sample_text):
    """The mutation acquires its evidence before the transaction and closes it after."""
    legacy_sample(ctx, sample_text)
    published(ctx.store, "other tag", profile="q", dimension=3)
    node_id = next(
        name for name in visible_node_ids(ctx) if name.startswith("entity-") or name.startswith("passage-")
    )
    events = order(ctx, monkeypatch)
    access = ChangesetAccess(ctx, EVERYTHING)
    identity = access.save("boost", [{"op": "set_node_boost", "entity_id": node_id, "boost": 1.5}])
    assert (events[0], events[-1]) == ("acquire", "close"), events
    assert "transaction" in events[1:-1], "the mutation must open its transaction inside the held scope"
    assert [row["id"] for row in ChangesetAccess(ctx, EVERYTHING).list()] == [identity]
    assert not live_references(ctx)


def test_question_generation_reads_originals_without_a_dense_dispatch(ctx, monkeypatch):
    # A managed corpus, not the legacy sample: a generated set re-proves its stored evidence
    # fingerprint on every read, and LadybugDB returns extracted facts in an arbitrary order,
    # so a fact-bearing corpus makes that fingerprint move between two loads. See the finding
    # in `evidence-pa4d.md`; it is not this slice's to fix and it is not what this test is about.
    generation, span = managed(ctx, "managed notes")
    source_id = generation.source_id
    evaluation = EvalAccess(ctx, EVERYTHING)
    set_id = evaluation.create_question_set("generated", source_id, origin="generated")
    prompts = []
    chat_json = ctx.ollama.chat_json

    def record_prompt(messages, schema, **kwargs):
        prompts.append(messages)
        return chat_json(messages, schema, **kwargs)

    monkeypatch.setattr(ctx.ollama, "chat_json", record_prompt)
    record = watch(ctx, monkeypatch)
    generate_questions(ctx, source_id, set_id=set_id, max_single=2, max_multihop=1, access=EVERYTHING)
    record.once()
    assert record.dispatched == [], "question generation reads passages; it never scores dense candidates"
    with query_session(ctx, EVERYTHING) as session:
        originals = {
            citation.text
            for passage in session.graph.passages
            if passage.source_id == source_id
            for citation in resolve_citations(session.graph, (passage.id,)).citations
        }
    assert originals, "the held view must resolve the passage back to its original evidence"
    rendered = "\n".join(message["content"] for prompt in prompts for message in prompt)
    assert [text for text in originals if text in rendered], (
        "the question maker must prompt with the original citation text"
    )
    assert span.text in rendered
    assert ctx.store.get_question_set(set_id)["status"] == "ready"
