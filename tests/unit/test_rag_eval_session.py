"""Legacy fixture scoring uses the same held graph as retrieval."""

import importlib.util

import pytest

from hippo.knowledge.access import AuthorizationChanged
from tests.unit.test_rag_eval import FIXTURE, SCRIPT, api


@pytest.mark.parametrize("outcome", ["success", "error", "revoke"])
def test_fixture_candidates_and_metrics_share_retrieval_session(tmp_path, monkeypatch, outcome):
    spec = importlib.util.spec_from_file_location("rag_eval_cli", SCRIPT)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    evaluator = api()
    fixture = evaluator.load_fixture(FIXTURE)
    with cli.fake_context(tmp_path) as ctx:
        original = ctx.graph_for
        metrics = evaluator.passage_evidence_metrics
        active = set()
        acquired = []

        def graph_for(*args, **kwargs):
            graph = original(*args, **kwargs)
            token = len(acquired)
            acquired.append(graph)
            active.add(token)
            graph.close_snapshot = lambda: active.remove(token)
            return graph

        def score(*args, **kwargs):
            assert len(active) == 1, "metric/candidate assembly must retain the retrieval graph"
            if outcome == "error":
                raise RuntimeError("scoring failed")
            if outcome == "revoke":
                ctx.store._bump_authorization_epoch()
            return metrics(*args, **kwargs)

        monkeypatch.setattr(ctx, "graph_for", graph_for)
        monkeypatch.setattr(evaluator, "passage_evidence_metrics", score)
        if outcome == "success":
            report = evaluator.evaluate(fixture, ctx, split="dev", model_profile="fake-hash128-v1")
            assert len(acquired) == report["evaluated_count"]
        else:
            with pytest.raises(RuntimeError if outcome == "error" else AuthorizationChanged):
                evaluator.evaluate(fixture, ctx, split="dev", model_profile="fake-hash128-v1")
        assert not active
