"""
Neo4j drops properties whose value is null, so a node created with `error: null` comes back
without an `error` key. The row-shaping helpers must fill those in, so that the real store
and the in-memory FakeStore hand callers the same keys.
"""

from __future__ import annotations

from hippo.store.changesets import _changeset_row
from hippo.store.evals import _result_row, _run_row, _set_row
from hippo.store.memory import _passage_row, _source_row


def test_source_row_fills_in_keys_neo4j_left_out():
    row = _source_row(
        {"s": {"id": "s1", "kind": "text", "name": "n", "status": "ready"}, "passages": 2, "fact_links": 3}
    )
    assert row["error"] is None and row["stage"] == "" and row["progress_done"] == 0
    assert row["meta"] == {} and row["passages"] == 2


def test_run_result_set_and_changeset_rows_fill_in_missing_keys():
    run = _run_row({"r": {"id": "r1", "name": "run", "status": "running"}, "set_id": "q", "set_name": "set"})
    assert (
        run["finished_at"] is None and run["error"] is None and run["summary"] == {} and run["settings"] == {}
    )
    result = _result_row(
        {"res": {"id": "x", "answer": "a"}, "question_id": "q1", "question": "?"}, with_trace=True
    )
    assert (
        result["error"] is None
        and result["gold_rank"] is None
        and result["trace"] == {}
        and result["recall"] == {}
        and result["used_dpr_fallback"] is False  # results stored before the property existed
    )
    question_set = _set_row({"qs": {"id": "qs1", "name": "s"}, "question_count": 0, "run_count": 0})
    assert question_set["status"] == "ready" and question_set["error"] is None
    changeset = _changeset_row({"c": {"id": "c1", "name": "cs", "ops_json": "[]"}})
    assert changeset["applied_at"] is None and changeset["from_result_id"] is None and changeset["note"] == ""
    passage = _passage_row(
        {"id": "p", "title": "t", "text": "x", "ordinal": 1, "source_id": "s", "source_name": "n"}
    )
    assert passage["extraction_error"] is None and passage["entities"] == [] and passage["triples"] == []


def test_stored_values_win_over_defaults():
    row = _source_row(
        {
            "s": {"id": "s1", "status": "failed", "error": "boom", "stage": "reading"},
            "passages": 0,
            "fact_links": 0,
        }
    )
    assert row["error"] == "boom" and row["stage"] == "reading"
