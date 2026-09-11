"""Analysis uses one live snapshot until the last response field is built."""

import pytest

from hippo.access import EVERYTHING
from hippo.analysis.simulate import Overrides, simulate
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.query_access import query_session
from tests.unit.test_query_session import observed  # noqa: F401
from tests.unit.test_query_snapshots import build


def live_references(ctx):
    return [r for r in ctx.store._knowledge_rows("SnapshotReference") if r.released_at is None]


@pytest.fixture
def managed(ctx, monkeypatch):
    generation, span = build(ctx, text="first revision.")
    acquired = []
    original = ctx.graph_for

    def graph_for(*args, **kwargs):
        graph = original(*args, **kwargs)
        acquired.append(graph)
        return graph

    monkeypatch.setattr(ctx, "graph_for", graph_for)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *args, **kwargs: [1.0, 0.0])
    return generation, span, acquired


def test_simulation_holds_one_generation_through_answer_then_releases(ctx, managed, monkeypatch):
    generation, span, acquired = managed
    published = []

    def embed(*args, **kwargs):
        if not published:
            published.append(build(ctx, parent=generation, text="second revision."))
        assert ctx.store.collect_generation(generation.id).blocked_reason == "snapshot_reference"
        return [1.0, 0.0]

    monkeypatch.setattr(ctx.ollama, "embed_one", embed)
    outcome = simulate(ctx, "What was the first revision?", Overrides(reanswer=True), access=EVERYTHING)
    assert outcome.answer.passage_ids == [span.id]
    assert outcome.trace.snapshot_ids == acquired[0].snapshot_ids
    assert outcome.baseline.snapshot_ids == acquired[0].snapshot_ids
    assert len(acquired) == 1
    assert not live_references(ctx)


@pytest.mark.parametrize("failure", ["model", "revocation"])
def test_simulation_failure_releases_pin(ctx, managed, monkeypatch, failure):
    def fail(*args, **kwargs):
        if failure == "revocation":
            ctx.store._bump_authorization_epoch()
        raise RuntimeError("model failed")

    monkeypatch.setattr(ctx.ollama, "embed_one", fail)
    with pytest.raises(AuthorizationChanged if failure == "revocation" else RuntimeError):
        simulate(ctx, "revision", Overrides(), access=EVERYTHING)
    assert not live_references(ctx)


def test_simulation_borrows_callers_snapshot_and_captured_settings(ctx, managed):
    _, _, acquired = managed
    with query_session(ctx, EVERYTHING, settings={"qa_top_k": 1}) as session:
        ctx.store.update_settings({"qa_top_k": 3})
        outcome = simulate(ctx, "revision", Overrides(), access=EVERYTHING, session=session)
        assert outcome.trace.settings["qa_top_k"] == 1
        assert live_references(ctx)
        assert len(acquired) == 1
    assert not live_references(ctx)


def test_reused_baseline_rebinds_snapshot_without_mutating_saved_trace(ctx, managed):
    first = simulate(ctx, "revision", Overrides(), access=EVERYTHING)
    saved_ids = first.trace.snapshot_ids
    ctx.store.update_settings({"qa_top_k": 1})
    second = simulate(ctx, "revision", Overrides(), baseline=first.trace, access=EVERYTHING)
    assert second.baseline.snapshot_ids == second.trace.snapshot_ids
    assert second.trace.snapshot_ids != saved_ids
    assert first.trace.snapshot_ids == saved_ids
    assert second.baseline.settings == first.trace.settings
    assert not live_references(ctx)


@pytest.mark.parametrize("surface", ["adhoc", "stored", "simulate", "missing", "invalid"])
def test_analysis_routes_use_one_graph_through_dto_and_render(observed, monkeypatch, surface):  # noqa: F811
    from types import SimpleNamespace

    from fastapi import HTTPException

    from hippo import ask
    from hippo.access import Principal
    from hippo.knowledge.eval_access import EvalAccess
    from hippo.web import render
    from hippo.web.adhoc import remember_adhoc
    from hippo.web.routes import analyze

    ctx, acquired, released = observed
    principal = Principal.open()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)), state=SimpleNamespace(principal=principal)
    )
    if surface == "adhoc":
        trace, answer = ask.ask(ctx, "Who designed the Orion arm?")
        key = remember_adhoc(trace, {"answer": answer.answer, "thought": answer.thought})
    if surface == "stored":
        evaluation = EvalAccess(ctx, principal.access)
        set_id = evaluation.create_question_set("questions")
        question_id = evaluation.add_questions(set_id, [{"text": "Who designed the Orion arm?"}])[0]
        run_id = evaluation.create_run(set_id, "run", ctx.store.get_settings())
        result_id = ctx.store.add_result(run_id, question_id, {"trace": {}})
    # Legacy graph caching may return the same object; remove setup instrumentation.
    for graph in acquired:
        if hasattr(graph, "close_snapshot"):
            del graph.close_snapshot
    acquired.clear()
    released.clear()

    def materialize(request, template, context, **kwargs):
        assert not released
        return context

    original_explain = analyze.explain

    def explain(graph, trace):
        assert not released
        assert acquired == [graph]
        return original_explain(graph, trace)

    monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
    monkeypatch.setattr(analyze, "explain", explain)
    if surface == "adhoc":
        analyze.analyze_adhoc(request, key=key)
    elif surface == "stored":
        analyze.analyze_result(request, result_id)
    elif surface == "simulate":
        analyze.simulate(request, analyze.SimulateBody(question="Who designed the Orion arm?"))
    elif surface == "missing":
        analyze.analyze_adhoc(request, question="Where?", key="missing")
    else:
        with pytest.raises(HTTPException):
            analyze.simulate(request, analyze.SimulateBody(question=""))
    assert len(acquired) == 1
    assert released == acquired


@pytest.mark.parametrize("surface", ["stored", "simulate", "dto"])
def test_deleted_saved_result_is_withheld_during_analysis(ctx, monkeypatch, surface):
    from types import SimpleNamespace

    from hippo.access import Principal
    from hippo.knowledge.eval_access import EvalAccess
    from hippo.web import render
    from hippo.web.routes import analyze

    principal = Principal.open()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)), state=SimpleNamespace(principal=principal)
    )
    evaluation = EvalAccess(ctx, principal.access)
    set_id = evaluation.create_question_set("questions")
    question_id = evaluation.add_questions(set_id, [{"text": "saved question"}])[0]
    run_id = evaluation.create_run(set_id, "run", ctx.store.get_settings())
    result_id = ctx.store.add_result(run_id, question_id, {"trace": {}})
    if surface == "stored":

        def materialize(request, template, context, **kwargs):
            ctx.store.delete_question(question_id)
            return context

        monkeypatch.setattr(render.templates, "TemplateResponse", materialize)
        with pytest.raises(AuthorizationChanged):
            analyze.analyze_result(request, result_id)
    elif surface == "simulate":
        original = analyze.run_simulation

        def remove_then_simulate(*args, **kwargs):
            ctx.store.delete_question(question_id)
            return original(*args, **kwargs)

        monkeypatch.setattr(analyze, "run_simulation", remove_then_simulate)
        with pytest.raises(AuthorizationChanged):
            analyze.simulate(request, analyze.SimulateBody(result_id=result_id))
    else:
        original = analyze.explain

        def explain(*args, **kwargs):
            explanation = original(*args, **kwargs)
            serialize = explanation.to_dict

            def to_dict():
                result = serialize()
                ctx.store.delete_question(question_id)
                return result

            explanation.to_dict = to_dict
            return explanation

        monkeypatch.setattr(analyze, "explain", explain)
        with pytest.raises(AuthorizationChanged):
            analyze.simulate(request, analyze.SimulateBody(result_id=result_id))
