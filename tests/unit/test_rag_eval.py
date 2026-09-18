"""The combined-corpus evaluator measures retrieved evidence, never supplied answers."""

from __future__ import annotations

import importlib.util
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/rag_all"
SCRIPT = ROOT / "scripts/rag_eval.py"


def api():
    assert importlib.util.find_spec("hippo.evals.rag_all") is not None, "combined evaluator is missing"
    from hippo.evals import rag_all

    return rag_all


def test_fixture_has_six_balanced_slices_and_disjoint_artifact_groups():
    fixture = api().load_fixture(FIXTURE)
    assert len(fixture.questions) == 24
    assert {s: sum(q["slice"] == s for q in fixture.questions) for s in api().SLICES} == dict.fromkeys(
        api().SLICES, 4
    )
    assert set(q["artifact_group"] for q in fixture.questions if q["split"] == "dev").isdisjoint(
        q["artifact_group"] for q in fixture.questions if q["split"] == "holdout"
    )
    assert {x["family"] for x in fixture.sources} >= {
        "code",
        "ddl",
        "prd",
        "jira",
        "tuleap",
        "github",
        "gitlab",
        "manifest",
        "backstage",
        "openapi",
    }
    assert fixture.manifest["review_status"] == "hand_authored_pending_human_review"


@pytest.fixture
def copied(tmp_path):
    target = tmp_path / "fixture"
    shutil.copytree(FIXTURE, target)
    return target


def change(path, name, mutate):
    file = path / name
    data = json.loads(file.read_text())
    mutate(data)
    file.write_text(json.dumps(data))


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda q: q.append(q[0]), "duplicate question"),
        (lambda q: q[0].update(alternative_evidence_sets=[["missing"]]), "missing evidence"),
        (lambda q: q[0].update(alternative_evidence_sets=[[]]), "alternative"),
        (
            lambda q: q[0].update(alternative_evidence_sets=[["e-commerce-route", "e-commerce-route"]]),
            "alternative",
        ),
        (lambda q: q[0].update(split="holdout"), "artifact group"),
        (lambda q: q[0].update(principal="unknown"), "principal"),
        (lambda q: q[0].update(snapshot="unknown"), "snapshot"),
    ],
)
def test_rejects_invalid_gold(copied, mutation, match):
    api()
    change(copied, "gold/questions.json", mutation)
    with pytest.raises(ValueError, match=match):
        api().load_fixture(copied)


def test_gold_cannot_be_an_indexed_source(copied):
    api()
    change(copied, "manifest.json", lambda m: m["sources"][0].update(path="gold/questions.json"))
    with pytest.raises(ValueError, match="corpus"):
        api().load_fixture(copied)


def test_gold_copy_in_corpus_is_rejected(copied):
    api()
    shutil.copy(copied / "gold/questions.json", copied / "corpus/leaked.json")
    change(copied, "manifest.json", lambda m: m["sources"][0].update(path="corpus/leaked.json"))
    with pytest.raises(ValueError, match="gold"):
        api().load_fixture(copied)


def test_evidence_quote_must_exist(copied):
    api()
    change(copied, "gold/evidence.json", lambda e: e[0].update(quote="invented evidence"))
    with pytest.raises(ValueError, match="quote"):
        api().load_fixture(copied)


def test_metrics_known_rankings_alternatives_and_empty_gold():
    from hippo.evals import metrics

    assert hasattr(metrics, "evidence_set_metrics"), "required evidence metrics are missing"
    scores = metrics.evidence_set_metrics([["a", "b"], ["c"]], ["x", "a", "a", "b"], ks=(1, 2, 3))
    assert scores["mrr"] == 0.5
    assert scores["evidence_recall@2"] == 0.5
    assert scores["all_required_set_success@2"] == 0
    assert scores["all_required_set_success@3"] == 1
    assert scores["any_hit@2"] == 1
    assert scores["ndcg@10"] == pytest.approx(
        (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3) + 1 / math.log2(4))
    )
    assert metrics.evidence_set_metrics([["a", "b"], ["c"]], ["c"])["all_required_set_success@5"] == 1
    assert metrics.evidence_set_metrics([], ["x"]) == {}
    assert metrics.evidence_set_metrics([["a"]], [])["mrr"] == 0
    assert metrics.recall_at_k([], ["a"]) == {}  # inherited contract
    assert metrics.gold_rank([], ["a"]) is None


@pytest.mark.parametrize("mode", ["bm25", "dense", "hybrid", "all"])
def test_cli_rejects_unimplemented_modes_without_output(tmp_path, mode):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fixture",
            str(FIXTURE),
            "--mode",
            mode,
            "--retrieval-only",
            "--output",
            str(tmp_path / "report.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert "mode not implemented" in result.stderr
    assert result.returncode != 0
    assert not (tmp_path / "report.json").exists()


def test_cli_requires_retrieval_only_and_approved_targets(tmp_path):
    for extra, message in [
        ([], "answer evaluation not implemented"),
        (["--retrieval-only", "--check-targets"], "approved release targets"),
    ]:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--fixture",
                str(FIXTURE),
                "--mode",
                "legacy",
                "--output",
                str(tmp_path / "report.json"),
                *extra,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert message in result.stderr


def test_real_legacy_pipeline_is_deterministic_and_not_gold_driven(tmp_path):
    api()
    spec = importlib.util.spec_from_file_location("rag_eval_cli", SCRIPT)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    fixture = api().load_fixture(FIXTURE)
    reports = []
    for run in range(2):
        with cli.fake_context(tmp_path / str(run)) as ctx:
            reports.append(api().evaluate(fixture, ctx, split="dev", model_profile="fake-hash128-v1"))
    assert reports[0] == reports[1]
    report = reports[0]
    assert report["question_count"] == 12
    assert report["evaluated_count"] > 0
    assert report["coverage_gaps"]
    assert report["index_counts"]["symbols"] > 0
    assert report["index_counts"]["passages"] > 0
    ranked = [q for q in report["questions"] if q["status"] == "evaluated"]
    assert any(q["ranked_evidence_ids"] for q in ranked)
    assert all("scores" in q for q in ranked)
    # Alter only gold expectations: the query and actual retrieved candidates must stay identical.
    fixture.questions[0]["alternative_evidence_sets"] = [["e-commerce-schema"]]
    with cli.fake_context(tmp_path / "changed-gold") as ctx:
        changed = api().evaluate(fixture, ctx, split="dev", model_profile="fake-hash128-v1")
    assert changed["questions"][0]["ranked_evidence_ids"] == report["questions"][0]["ranked_evidence_ids"]
    assert all(
        candidate["passage_id"] and candidate["source_id"]
        for question in ranked
        for candidate in question["candidates"]
    )


def test_original_passage_cutoffs_keep_unlabelled_and_duplicate_candidates():
    from hippo.evals import metrics

    assert hasattr(metrics, "passage_evidence_metrics"), "passage-level metrics are missing"
    score = metrics.passage_evidence_metrics(
        [["a", "b"]], [[], ["a"], ["a"], ["b"]], total_relevant_passages=3, ks=(1, 2, 3, 4)
    )
    assert score["mrr"] == 0.5
    assert score["evidence_recall@3"] == 0.5
    assert score["all_required_set_success@3"] == 0
    assert score["all_required_set_success@4"] == 1
    assert score["ndcg@10"] == pytest.approx(
        (1 / math.log2(3) + 1 / math.log2(4) + 1 / math.log2(5)) / (1 + 1 / math.log2(3) + 1 / math.log2(4))
    )
    assert metrics.passage_evidence_metrics([], [[]], total_relevant_passages=0) == {}


def test_gold_object_and_path_ids_are_validated(copied):
    api()
    change(copied, "gold/questions.json", lambda q: q[0].update(required_object_ids=["missing-object"]))
    with pytest.raises(ValueError, match="object"):
        api().load_fixture(copied)


def test_gold_temporal_selectors_are_explicit(copied):
    fixture = api().load_fixture(copied)
    historical = [q for q in fixture.questions if q["query_mode"] != "current"]
    assert historical
    assert all(q["query_mode"] in {"as_of", "compare"} and q["temporal"] for q in historical)


def test_holdout_is_materially_distinct_from_development():
    fixture = api().load_fixture(FIXTURE)
    dev = {q["question"] for q in fixture.questions if q["split"] == "dev"}
    holdout = {q["question"] for q in fixture.questions if q["split"] == "holdout"}
    assert dev.isdisjoint(holdout)
    holdout_schema = next(s for s in fixture.sources if s["id"] == "fulfillment-schema")
    assert "warehouse_id" in (fixture.root / holdout_schema["path"]).read_text()
    assert "commerce.orders" not in (fixture.root / holdout_schema["path"]).read_text()


def test_one_passage_can_support_multiple_units_without_extra_rank_slots():
    from hippo.evals.metrics import passage_evidence_metrics

    scores = passage_evidence_metrics([["a", "b"]], [[], ["a", "b"]], total_relevant_passages=1, ks=(1, 2))
    assert scores["evidence_recall@1"] == 0
    assert scores["all_required_set_success@2"] == 1
    assert scores["mrr"] == 0.5


def test_prose_headings_and_cross_file_imports_are_measured(tmp_path):
    spec = importlib.util.spec_from_file_location("rag_eval_cli", SCRIPT)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with cli.fake_context(tmp_path) as ctx:
        result = api().evaluate(
            api().load_fixture(FIXTURE), ctx, split="dev", model_profile="fake-hash128-v1"
        )
    assert result["evaluated_count"] == 7
    assert result["index_counts"]["invokes_edges"] >= 1
    requirement = next(q for q in result["questions"] if q["id"] == "commerce-q07")
    assert "e-commerce-prd" in requirement["ranked_evidence_ids"]


def test_ndcg_ideal_counts_relevant_passages_missing_from_results():
    from hippo.evals.metrics import passage_evidence_metrics

    score = passage_evidence_metrics([["a", "b"]], [["a"]], total_relevant_passages=2)
    assert score["ndcg@10"] == pytest.approx(1 / (1 + 1 / math.log2(3)))
    assert score["evidence_recall@5"] == 0.5


def test_no_evaluable_questions_cannot_be_empty_success(tmp_path):
    fixture = api().load_fixture(FIXTURE)
    for question in fixture.questions:
        question["requires"] = ["not_implemented"]
    spec = importlib.util.spec_from_file_location("rag_eval_cli", SCRIPT)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with cli.fake_context(tmp_path) as ctx, pytest.raises(ValueError, match="no evaluable"):
        api().evaluate(fixture, ctx, split="dev", model_profile="fake-hash128-v1")


def test_restricted_supported_sources_never_become_public(tmp_path):
    fixture = api().load_fixture(FIXTURE)
    for source in fixture.sources:
        if source["id"] == "commerce-owners":
            source["audience"] = "operators"
    spec = importlib.util.spec_from_file_location("rag_eval_cli", SCRIPT)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with cli.fake_context(tmp_path) as ctx:
        result = api().evaluate(fixture, ctx, split="dev", model_profile="fake-hash128-v1")
        assert not any(s["name"] == "commerce-owners" for s in ctx.store.list_sources())
    assert next(q for q in result["questions"] if q["id"] == "commerce-q02")["status"] == "coverage_gap"


@pytest.mark.parametrize("gold_file", ["questions", "evidence", "objects", "permission_cases"])
@pytest.mark.parametrize("embedded", [False, True])
def test_every_gold_file_is_excluded_even_when_copied_or_embedded(copied, gold_file, embedded):
    payload = (copied / f"gold/{gold_file}.json").read_text()
    if embedded:
        payload = (
            "# Accidental debug export\n\n```json\n"
            + json.dumps({"labels": json.loads(payload)}, separators=(",", ":"))
            + "\n```"
        )
    (copied / "corpus/leaked.md").write_text(payload)
    change(
        copied,
        "manifest.json",
        lambda m: m["sources"].append(
            {
                "id": "leak",
                "path": "corpus/leaked.md",
                "family": "prd",
                "artifact_group": "commerce",
                "audience": "public",
                "snapshots": ["after"],
            }
        ),
    )
    with pytest.raises(ValueError, match="gold"):
        api().load_fixture(copied)


def test_permission_cases_must_parse(copied):
    (copied / "gold/permission_cases.json").write_text("broken JSON")
    with pytest.raises(ValueError):
        api().load_fixture(copied)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows[0].update(principal="missing"),
        lambda rows: rows[0].update(forbidden_evidence_ids=["missing"]),
        lambda rows: rows[0].update(visible_sources=["missing"]),
        lambda rows: rows[0].update(
            forbidden_paths=[{"subject": "missing", "predicate": "DEPENDS_ON", "object": "missing"}]
        ),
    ],
)
def test_permission_case_references_are_validated(copied, mutation):
    change(copied, "gold/permission_cases.json", mutation)
    with pytest.raises(ValueError, match="permission"):
        api().load_fixture(copied)


@pytest.mark.parametrize(
    "temporal",
    [
        {"valid_at": None, "known_at": "banana"},
        {"valid_at": "2026-05-01", "known_at": "2026-05-10T00:00:00Z"},
        {"valid_at": "2026-05-01T00:00:00", "known_at": "2026-05-10T00:00:00Z"},
        {"valid_at": "2026-05-01T00:00:00Z"},
    ],
)
def test_temporal_selectors_require_aware_timestamps(copied, temporal):
    change(copied, "gold/questions.json", lambda q: q[10].update(temporal=temporal))
    with pytest.raises(ValueError, match="temporal"):
        api().load_fixture(copied)


def test_compare_nested_selectors_are_validated(copied):
    change(copied, "gold/questions.json", lambda q: q[11]["temporal"].update(right={"known_at": "banana"}))
    with pytest.raises(ValueError, match="temporal"):
        api().load_fixture(copied)


def test_snapshot_timestamps_are_validated(copied):
    change(copied, "manifest.json", lambda m: m["snapshots"]["before"].update(valid_at=None))
    with pytest.raises(ValueError, match="temporal"):
        api().load_fixture(copied)


def test_insufficiency_is_boolean(copied):
    change(copied, "gold/questions.json", lambda q: q[0].update(expected_insufficiency="false"))
    with pytest.raises(ValueError, match="boolean"):
        api().load_fixture(copied)


@pytest.mark.parametrize("mode,snapshot", [("current", "before"), ("as_of", "after"), ("compare", "after")])
def test_temporal_gap_is_derived_even_without_requires(tmp_path, mode, snapshot):
    fixture = api().load_fixture(FIXTURE)
    fixture.questions[0].update(query_mode=mode, snapshot=snapshot, requires=[])
    spec = importlib.util.spec_from_file_location("rag_eval_cli", SCRIPT)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with cli.fake_context(tmp_path) as ctx:
        report = api().evaluate(fixture, ctx, split="dev", model_profile="fake-hash128-v1")
    assert report["questions"][0]["status"] == "coverage_gap"
    assert "bitemporal" in report["questions"][0]["missing_capabilities"]


def test_slice_reports_sample_count_for_each_metric(tmp_path):
    spec = importlib.util.spec_from_file_location("rag_eval_cli", SCRIPT)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with cli.fake_context(tmp_path) as ctx:
        report = api().evaluate(
            api().load_fixture(FIXTURE), ctx, split="dev", model_profile="fake-hash128-v1"
        )
    saw_omission = False
    for name, summary in report["per_slice"].items():
        rows = [q for q in report["questions"] if q["slice"] == name and q["status"] == "evaluated"]
        assert summary["metric_sample_counts"] == {
            key: sum(key in row["scores"] for row in rows) for key in summary["metrics"]
        }
        saw_omission |= summary["metric_sample_counts"].get("ndcg@10", 0) < summary["evaluated_count"]
    assert saw_omission


@pytest.mark.parametrize("value", ["bitemporal", [""], [None], [True]])
def test_requires_rejects_malformed_string_lists(copied, value):
    change(copied, "gold/questions.json", lambda rows: rows[0].update(requires=value))
    with pytest.raises(ValueError, match="requires"):
        api().load_fixture(copied)


def test_candidates_preserve_original_inspectable_references(tmp_path):
    spec = importlib.util.spec_from_file_location("rag_eval_cli", SCRIPT)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with cli.fake_context(tmp_path) as ctx:
        report = api().evaluate(
            api().load_fixture(FIXTURE), ctx, split="dev", model_profile="fake-hash128-v1"
        )
        evaluated = next(q for q in report["questions"] if q["status"] == "evaluated")
        assert "candidates" in evaluated
        candidates = evaluated["candidates"]
        assert len(candidates) == evaluated["retrieved_passage_count"]
        assert [c["rank"] for c in candidates] == list(range(1, len(candidates) + 1))
        for candidate in candidates:
            passage = ctx.graph().passage_by_id(candidate["passage_id"])
            assert candidate["source_id"] == passage.source_id
            assert candidate["title"] == passage.title
            assert candidate["locator"] == {"kind": "legacy_chunk_ordinal", "ordinal": passage.ordinal}
            assert "text" not in candidate
        assert any(not c["evidence_ids"] for c in candidates)
