"""
Neo4j drops properties whose value is null, so a node created with `error: null` comes back
without an `error` key. The row-shaping helpers must fill those in, so that the real store
and the in-memory FakeStore hand callers the same keys.
"""

from __future__ import annotations

from hippo.store.changesets import _changeset_row
from hippo.store.code import (
    _commit_row,
    _data_object_row,
    _symbol_row,
    code_edge_write_rows,
    commit_write_row,
    data_object_write_row,
    symbol_write_row,
)
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


def test_code_rows_fill_in_every_key_a_caller_reads():
    symbol = _symbol_row({"id": "symbol-1", "name": "place"})
    assert (symbol["qualname"], symbol["path"], symbol["signature"], symbol["doc"]) == ("", "", "", "")
    assert (symbol["line_start"], symbol["line_end"], symbol["in_degree"]) == (0, 0, 0)
    assert symbol["boost"] == 1.0 and symbol["community"] is None and symbol["is_test"] is False
    assert symbol["raises"] == [] and symbol["name_tokens"] == [] and symbol["passage_ids"] == []

    data = _data_object_row({"id": "data-1", "name": "orders", "kind": "table"})
    assert (data["dialect"], data["source_name"], data["boost"]) == ("", "", 1.0)

    commit = _commit_row({"id": "commit-1", "sha": "abc"})
    assert (commit["author"], commit["date"], commit["message"], commit["ordinal"]) == ("", "", "", 0)


def test_code_rows_coerce_the_types_a_backend_might_hand_back():
    symbol = _symbol_row({"id": "symbol-1", "name": "x", "line_start": "3", "community": "7", "boost": 2})
    assert (symbol["line_start"], symbol["community"], symbol["boost"]) == (3, 7, 2.0)


def test_write_rows_normalise_free_text_and_fill_in_name_tokens():
    row = symbol_write_row({"id": "symbol-1", "source_id": "s", "name": "OrderService", "doc": None})
    assert row["doc"] == "" and row["signature"] == ""  # a bare None breaks LadybugDB's decode()
    assert row["name_tokens"] == ["order", "service"]
    assert row["raises"] == [] and row["embedding"] == []
    assert data_object_write_row({"id": "data-1", "source_id": "s", "name": "order_lines"})[
        "name_tokens"
    ] == ["order", "lines"]
    assert commit_write_row({"id": "commit-1", "source_id": "s", "ordinal": "4"})["ordinal"] == 4


def test_code_edge_write_rows_dedupe_to_the_best_omega_and_drop_bad_pairs():
    rows = code_edge_write_rows(
        [
            {"a": "symbol-1", "b": "symbol-2", "kind": "INVOKES", "omega": 0.5, "provenance": "fuzzy_name"},
            {"a": "symbol-1", "b": "symbol-2", "kind": "INVOKES", "omega": 1.0, "provenance": "same_file"},
            {"a": "symbol-1", "b": "symbol-1", "kind": "INVOKES", "omega": 1.0},  # self loop
            {"a": "data-1", "b": "symbol-2", "kind": "READS", "omega": 0.8},  # not a CODE_EDGE pair
            {"a": "entity-1", "b": "symbol-2", "kind": "INVOKES", "omega": 1.0},  # not a code node
        ]
    )
    assert len(rows) == 1
    assert (rows[0]["omega"], rows[0]["provenance"]) == (1.0, "same_file")
    assert (rows[0]["label_a"], rows[0]["label_b"]) == ("Symbol", "Symbol")
    assert rows[0]["extra"] == "{}"  # JSON text, through the same decode() path as any free text


def test_stored_values_win_over_defaults():
    row = _source_row(
        {
            "s": {"id": "s1", "status": "failed", "error": "boom", "stage": "reading"},
            "passages": 0,
            "fact_links": 0,
        }
    )
    assert row["error"] == "boom" and row["stage"] == "reading"
