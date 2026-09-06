"""
The Store interface, part 2: question sets, questions, evaluation runs, results
and changesets. Same fixture as test_store.py: FakeStore locally, Neo4j in CI.
"""

from __future__ import annotations

import pytest

QUESTIONS = [
    {"text": "Where is Acme?", "expected_answer": "Boulder", "gold_passage_ids": ["p1"], "kind": "single"},
    {"text": "Which state?", "expected_answer": "Colorado", "kind": "multihop", "notes": "two hops"},
]


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    """Make created_at timestamps distinct and controllable (the real clock only has seconds)."""
    ticks = iter(f"2026-01-01T00:00:{i:02d}+00:00" for i in range(60))
    tick = lambda: next(ticks)  # noqa: E731
    monkeypatch.setattr("hippo.store.evals.now_iso", tick)
    monkeypatch.setattr("tests.fakes.fake_store.now_iso", tick)
    return tick


# --------------------------------------------------------------- question sets


def test_create_and_get_question_set(store) -> None:
    source_id = store.create_source("text", "Src")
    set_id = store.create_question_set("Smoke", source_id=source_id, origin="generated")
    row = store.get_question_set(set_id)
    assert row["id"] == set_id
    assert (row["name"], row["origin"], row["status"], row["stage"]) == ("Smoke", "generated", "ready", "")
    assert (row["progress_done"], row["progress_total"], row["error"]) == (0, 0, None)
    assert (row["source_id"], row["source_name"]) == (source_id, "Src")
    assert (row["question_count"], row["run_count"]) == (0, 0)
    assert row["created_at"]


def test_a_question_set_without_a_source(store) -> None:
    set_id = store.create_question_set("Manual")
    row = store.get_question_set(set_id)
    assert row["origin"] == "manual"
    assert row["source_id"] is None and row["source_name"] is None
    assert store.get_question_set("nope") is None


def test_update_question_set_progress_and_unknown_fields(store) -> None:
    set_id = store.create_question_set("Gen")
    store.update_question_set(
        set_id, status="generating", stage="single-hop", progress_done=2, progress_total=5
    )
    row = store.get_question_set(set_id)
    assert (row["status"], row["stage"], row["progress_done"], row["progress_total"]) == (
        "generating",
        "single-hop",
        2,
        5,
    )
    store.update_question_set(set_id, status="failed", error="boom", name="Renamed")
    row = store.get_question_set(set_id)
    assert (row["status"], row["error"], row["name"]) == ("failed", "boom", "Renamed")
    with pytest.raises(ValueError, match="unknown question set fields"):
        store.update_question_set(set_id, colour="blue")


def test_list_question_sets_includes_counts(store) -> None:
    a = store.create_question_set("A")
    b = store.create_question_set("B")
    store.add_questions(b, QUESTIONS)
    store.create_run(b, "run", {})
    rows = {r["id"]: r for r in store.list_question_sets()}
    assert set(rows) == {a, b}
    assert (rows[b]["question_count"], rows[b]["run_count"]) == (2, 1)
    assert (rows[a]["question_count"], rows[a]["run_count"]) == (0, 0)


# ------------------------------------------------------------------ questions


def test_add_and_list_questions_keep_order_and_defaults(store) -> None:
    set_id = store.create_question_set("Q")
    ids = store.add_questions(set_id, QUESTIONS)
    assert len(ids) == 2 and len(set(ids)) == 2

    rows = store.list_questions(set_id)
    assert [r["id"] for r in rows] == ids
    assert [r["ordinal"] for r in rows] == [0, 1]
    assert rows[0] == {
        "id": ids[0],
        "text": "Where is Acme?",
        "expected_answer": "Boulder",
        "gold_passage_ids": ["p1"],
        "kind": "single",
        "notes": "",
        "ordinal": 0,
    }
    assert (rows[1]["kind"], rows[1]["notes"], rows[1]["gold_passage_ids"]) == ("multihop", "two hops", [])


def test_questions_added_later_continue_the_ordinals(store) -> None:
    set_id = store.create_question_set("Q")
    store.add_questions(set_id, QUESTIONS)
    (third,) = store.add_questions(set_id, [{"text": "Third?"}])
    rows = store.list_questions(set_id)
    assert [r["ordinal"] for r in rows] == [0, 1, 2]
    assert rows[2]["id"] == third and rows[2]["expected_answer"] == ""


def test_get_question_includes_its_set(store) -> None:
    set_id = store.create_question_set("Q")
    (qid, _) = store.add_questions(set_id, QUESTIONS)
    row = store.get_question(qid)
    assert row["text"] == "Where is Acme?"
    assert (row["set_id"], row["set_name"]) == (set_id, "Q")
    assert store.get_question("nope") is None


def test_delete_question_and_delete_question_set(store) -> None:
    set_id = store.create_question_set("Q")
    q1, q2 = store.add_questions(set_id, QUESTIONS)
    run_id = store.create_run(set_id, "run", {})
    store.add_result(run_id, q1, {"answer": "Boulder"})

    store.delete_question(q2)
    assert [r["id"] for r in store.list_questions(set_id)] == [q1]
    assert store.get_question(q2) is None

    store.delete_question_set(set_id)
    assert store.get_question_set(set_id) is None
    assert store.get_question(q1) is None
    assert store.get_run(run_id) is None
    assert store.list_results(run_id) == []
    assert store.list_runs() == []


# ----------------------------------------------------------------------- runs


def test_create_and_get_run(store) -> None:
    set_id = store.create_question_set("Q")
    store.add_questions(set_id, QUESTIONS)
    run_id = store.create_run(set_id, "Baseline", {"damping": 0.5})
    row = store.get_run(run_id)
    assert row["id"] == run_id
    assert (row["name"], row["status"], row["finished_at"], row["error"]) == (
        "Baseline",
        "running",
        None,
        None,
    )
    assert row["settings"] == {"damping": 0.5}
    assert row["summary"] == {}
    assert (row["progress_done"], row["progress_total"]) == (0, 2)
    assert (row["set_id"], row["set_name"]) == (set_id, "Q")
    assert row["started_at"]
    assert store.get_run("nope") is None


def test_update_run_fields_and_unknown_fields(store) -> None:
    set_id = store.create_question_set("Q")
    run_id = store.create_run(set_id, "R", {})
    store.update_run(
        run_id,
        progress_done=1,
        status="done",
        finished_at="2026-01-01T00:00:00+00:00",
        summary_json='{"accuracy": 1.0}',
    )
    row = store.get_run(run_id)
    assert (row["progress_done"], row["status"], row["finished_at"]) == (
        1,
        "done",
        "2026-01-01T00:00:00+00:00",
    )
    assert row["summary"] == {"accuracy": 1.0}
    store.update_run(run_id, status="failed", error="boom", name="Renamed")
    row = store.get_run(run_id)
    assert (row["status"], row["error"], row["name"]) == ("failed", "boom", "Renamed")
    with pytest.raises(ValueError, match="unknown run fields"):
        store.update_run(run_id, colour="blue")


def test_list_runs_for_one_set_or_all(store, clock) -> None:
    a, b = store.create_question_set("A"), store.create_question_set("B")
    run_a = store.create_run(a, "ra", {})
    run_b = store.create_run(b, "rb", {})
    assert [r["id"] for r in store.list_runs(a)] == [run_a]
    assert [r["id"] for r in store.list_runs(b)] == [run_b]
    assert [r["id"] for r in store.list_runs()] == [run_b, run_a]  # newest first


def test_delete_run_removes_its_results(store) -> None:
    set_id = store.create_question_set("Q")
    (qid, _) = store.add_questions(set_id, QUESTIONS)
    run_id = store.create_run(set_id, "R", {})
    result_id = store.add_result(run_id, qid, {"answer": "x"})
    store.delete_run(run_id)
    assert store.get_run(run_id) is None
    assert store.get_result(result_id) is None
    assert store.results_for_question(qid) == []
    assert store.get_question_set(set_id)["run_count"] == 0


# -------------------------------------------------------------------- results


def full_result(trace: dict) -> dict:
    return {
        "answer": "Boulder",
        "thought": "It says so.",
        "verdict": "correct",
        "judge_score": 1.0,
        "judge_reason": "matches",
        "exact_match": 1.0,
        "f1": 1.0,
        "recall": {"recall@1": 1.0, "recall@5": 1.0},
        "gold_rank": 1,
        "latency_ms": 12.5,
        "trace": trace,
        "used_dpr_fallback": bool(trace.get("used_dpr_fallback", False)),
        "error": None,
    }


def test_add_result_and_get_result_round_trip_the_trace(store) -> None:
    set_id = store.create_question_set("Q")
    (qid, _) = store.add_questions(set_id, QUESTIONS)
    run_id = store.create_run(set_id, "R", {})
    trace = {
        "question": "Where is Acme?",
        "settings": {"damping": 0.5, "node_specificity": True},
        "passages": [{"passage_id": "p1", "rank": 1, "score": 0.25}],
        "fact_candidates": [{"triple": ["acme", "in", "boulder"], "kept": True}],
        "used_dpr_fallback": False,
    }

    result_id = store.add_result(run_id, qid, full_result(trace))
    row = store.get_result(result_id)

    assert row["id"] == result_id
    assert (row["answer"], row["thought"], row["verdict"]) == ("Boulder", "It says so.", "correct")
    assert (row["judge_score"], row["judge_reason"], row["exact_match"], row["f1"]) == (
        1.0,
        "matches",
        1.0,
        1.0,
    )
    assert row["recall"] == {"recall@1": 1.0, "recall@5": 1.0}
    assert (row["gold_rank"], row["latency_ms"], row["error"]) == (1, 12.5, None)
    assert row["trace"] == trace
    assert row["used_dpr_fallback"] is False
    assert (row["question_id"], row["question"], row["expected_answer"]) == (qid, "Where is Acme?", "Boulder")
    assert (row["kind"], row["gold_passage_ids"], row["ordinal"]) == ("single", ["p1"], 0)
    assert (row["run_id"], row["run_name"]) == (run_id, "R")
    assert row["created_at"]
    assert store.get_result("nope") is None


def test_add_result_fills_in_defaults(store) -> None:
    set_id = store.create_question_set("Q")
    (qid, _) = store.add_questions(set_id, QUESTIONS)
    run_id = store.create_run(set_id, "R", {})
    row = store.get_result(store.add_result(run_id, qid, {"error": "timed out"}))
    assert (row["answer"], row["thought"], row["verdict"], row["judge_reason"]) == ("", "", "", "")
    assert row["judge_score"] is None and row["gold_rank"] is None and row["latency_ms"] is None
    assert row["recall"] == {} and row["trace"] == {}
    assert row["used_dpr_fallback"] is False
    assert row["error"] == "timed out"


def test_list_results_follows_question_order_without_traces(store) -> None:
    set_id = store.create_question_set("Q")
    q1, q2 = store.add_questions(set_id, QUESTIONS)
    run_id = store.create_run(set_id, "R", {})
    store.add_result(run_id, q2, full_result({"question": "second"}))
    store.add_result(run_id, q1, full_result({"question": "first"}))

    rows = store.list_results(run_id)

    assert [r["question_id"] for r in rows] == [q1, q2]
    assert [r["question"] for r in rows] == ["Where is Acme?", "Which state?"]
    assert all(r["trace"] is None for r in rows)
    assert rows[0]["recall"] == {"recall@1": 1.0, "recall@5": 1.0}
    assert store.list_results("nope") == []


def test_the_fallback_flag_survives_without_the_trace(store) -> None:
    set_id = store.create_question_set("Q")
    (qid, _) = store.add_questions(set_id, QUESTIONS)
    run_id = store.create_run(set_id, "R", {})
    store.add_result(
        run_id, qid, full_result({"used_dpr_fallback": True, "fallback_reason": "the memory is empty"})
    )
    (row,) = store.list_results(run_id)
    assert row["trace"] is None and row["used_dpr_fallback"] is True


def test_results_for_question_are_newest_first_across_runs(store, clock) -> None:
    set_id = store.create_question_set("Q")
    (qid, other) = store.add_questions(set_id, QUESTIONS)
    first_run = store.create_run(set_id, "first", {})
    second_run = store.create_run(set_id, "second", {})
    old = store.add_result(first_run, qid, full_result({}))
    store.add_result(first_run, other, full_result({}))
    new = store.add_result(second_run, qid, full_result({}))

    rows = store.results_for_question(qid)

    assert [r["id"] for r in rows] == [new, old]
    assert [r["run_name"] for r in rows] == ["second", "first"]
    assert all(r["trace"] is None for r in rows)
    assert store.results_for_question("nope") == []


# ----------------------------------------------------------------- changesets


OPS = [
    {"op": "set_setting", "name": "damping", "value": 0.7},
    {"op": "set_node_boost", "entity_id": "e1", "boost": 1.5},
]


def test_create_get_and_list_changesets(store) -> None:
    cid = store.create_changeset("Tweak", OPS, from_result_id="res-1", note="try it")
    row = store.get_changeset(cid)
    assert row["id"] == cid
    assert (row["name"], row["note"], row["status"], row["applied_at"]) == ("Tweak", "try it", "draft", None)
    assert row["ops"] == OPS
    assert row["from_result_id"] == "res-1"
    assert row["created_at"]
    assert [r["id"] for r in store.list_changesets()] == [cid]
    assert store.get_changeset("nope") is None


def test_changeset_defaults(store) -> None:
    row = store.get_changeset(store.create_changeset("Bare", []))
    assert row["ops"] == [] and row["note"] == "" and row["from_result_id"] is None


def test_mark_applied_and_delete_changeset(store) -> None:
    cid = store.create_changeset("Tweak", OPS)
    store.mark_applied(cid)
    row = store.get_changeset(cid)
    assert row["status"] == "applied"
    assert row["applied_at"]
    store.delete_changeset(cid)
    assert store.get_changeset(cid) is None
    assert store.list_changesets() == []
    assert store.stats()["changesets"] == 0


def test_list_changesets_newest_first(store, clock) -> None:
    first = store.create_changeset("first", [])
    second = store.create_changeset("second", [])
    assert [r["id"] for r in store.list_changesets()] == [second, first]
