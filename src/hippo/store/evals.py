"""Queries for evaluation: question sets, runs, and per-question results (with their retrieval traces)."""

from __future__ import annotations

import json
from typing import Any

from .base import Neo4jBase, new_id, now_iso, with_defaults


class EvalQueries(Neo4jBase):
    # ======================================================== question sets

    def create_question_set(self, name: str, source_id: str | None = None, origin: str = "manual") -> str:
        set_id = new_id()
        self.run(
            """
            CREATE (qs:QuestionSet {id: $id, name: $name, origin: $origin, status: 'ready', stage: '',
                                    progress_done: 0, progress_total: 0, error: null, created_at: $now})
            """,
            id=set_id,
            name=name,
            origin=origin,
            now=now_iso(),
        )
        if source_id:
            self.run(
                "MATCH (qs:QuestionSet {id: $id}), (s:Source {id: $source_id}) MERGE (qs)-[:ABOUT]->(s)",
                id=set_id,
                source_id=source_id,
            )
        return set_id

    def add_questions(self, set_id: str, questions: list[dict[str, Any]]) -> list[str]:
        """questions: {text, expected_answer, gold_passage_ids?, kind?, notes?}. Returns the new ids."""
        start = self.run_one(
            "MATCH (qs:QuestionSet {id: $id}) RETURN count { (qs)-[:HAS]->(:Question) } AS n", id=set_id
        )
        offset = int(start["n"]) if start else 0
        rows = []
        for i, q in enumerate(questions):
            rows.append(
                {
                    "id": new_id(),
                    "text": q["text"],
                    "expected_answer": q.get("expected_answer", ""),
                    "gold_passage_ids": list(q.get("gold_passage_ids") or []),
                    "kind": q.get("kind", "single"),
                    "notes": q.get("notes", ""),
                    "ordinal": offset + i,
                }
            )
        self.run(
            """
            MATCH (qs:QuestionSet {id: $set_id})
            UNWIND $rows AS row
            CREATE (q:Question {id: row.id, text: row.text, expected_answer: row.expected_answer,
                                gold_passage_ids: row.gold_passage_ids, kind: row.kind, notes: row.notes,
                                ordinal: row.ordinal})
            MERGE (qs)-[:HAS]->(q)
            """,
            set_id=set_id,
            rows=rows,
        )
        return [r["id"] for r in rows]

    def update_question_set(self, set_id: str, **fields: Any) -> None:
        """Progress/status while questions are being generated in the background."""
        allowed = {"status", "stage", "progress_done", "progress_total", "error", "name"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown question set fields: {sorted(bad)}")
        self.run("MATCH (qs:QuestionSet {id: $id}) SET qs += $fields", id=set_id, fields=fields)

    def delete_question(self, question_id: str) -> None:
        self.run("MATCH (q:Question {id: $id}) DETACH DELETE q", id=question_id)

    def delete_question_set(self, set_id: str) -> None:
        self.run(
            """
            MATCH (qs:QuestionSet {id: $id})
            OPTIONAL MATCH (qs)-[:HAS]->(q:Question)
            OPTIONAL MATCH (r:EvalRun)-[:OF]->(qs)
            OPTIONAL MATCH (r)-[:RESULT]->(res:EvalResult)
            DETACH DELETE res, r, q, qs
            """,
            id=set_id,
        )

    def get_question_set(self, set_id: str) -> dict[str, Any] | None:
        row = self.run_one(
            """
            MATCH (qs:QuestionSet {id: $id})
            OPTIONAL MATCH (qs)-[:ABOUT]->(s:Source)
            RETURN qs AS qs, s.id AS source_id, s.name AS source_name,
                   count { (qs)-[:HAS]->(:Question) } AS question_count,
                   count { (:EvalRun)-[:OF]->(qs) } AS run_count
            """,
            id=set_id,
        )
        return _set_row(row) if row else None

    def list_question_sets(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (qs:QuestionSet)
            OPTIONAL MATCH (qs)-[:ABOUT]->(s:Source)
            RETURN qs AS qs, s.id AS source_id, s.name AS source_name,
                   count { (qs)-[:HAS]->(:Question) } AS question_count,
                   count { (:EvalRun)-[:OF]->(qs) } AS run_count
            ORDER BY qs.created_at DESC
            """
        )
        return [_set_row(r) for r in rows]

    def list_questions(self, set_id: str) -> list[dict[str, Any]]:
        return self.run(
            """
            MATCH (:QuestionSet {id: $id})-[:HAS]->(q:Question)
            RETURN q.id AS id, q.text AS text, q.expected_answer AS expected_answer, q.gold_passage_ids AS gold_passage_ids,
                   q.kind AS kind, q.notes AS notes, q.ordinal AS ordinal
            ORDER BY q.ordinal
            """,
            id=set_id,
        )

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        return self.run_one(
            """
            MATCH (qs:QuestionSet)-[:HAS]->(q:Question {id: $id})
            RETURN q.id AS id, q.text AS text, q.expected_answer AS expected_answer, q.gold_passage_ids AS gold_passage_ids,
                   q.kind AS kind, q.notes AS notes, q.ordinal AS ordinal, qs.id AS set_id, qs.name AS set_name
            """,
            id=question_id,
        )

    # ================================================================ runs

    def create_run(self, set_id: str, name: str, settings: dict[str, Any]) -> str:
        run_id = new_id()
        self.run(
            """
            MATCH (qs:QuestionSet {id: $set_id})
            CREATE (r:EvalRun {id: $id, name: $name, status: 'running', started_at: $now, finished_at: null,
                               settings_json: $settings_json, summary_json: '{}', progress_done: 0,
                               progress_total: count { (qs)-[:HAS]->(:Question) }, error: null})
            MERGE (r)-[:OF]->(qs)
            """,
            set_id=set_id,
            id=run_id,
            name=name,
            now=now_iso(),
            settings_json=json.dumps(settings),
        )
        return run_id

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "finished_at", "summary_json", "progress_done", "error", "name"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown run fields: {sorted(bad)}")
        self.run("MATCH (r:EvalRun {id: $id}) SET r += $fields", id=run_id, fields=fields)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.run_one(
            """
            MATCH (r:EvalRun {id: $id})-[:OF]->(qs:QuestionSet)
            RETURN r AS r, qs.id AS set_id, qs.name AS set_name
            """,
            id=run_id,
        )
        return _run_row(row) if row else None

    def list_runs(self, set_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (r:EvalRun)-[:OF]->(qs:QuestionSet)
            WHERE $set_id IS NULL OR qs.id = $set_id
            RETURN r AS r, qs.id AS set_id, qs.name AS set_name
            ORDER BY r.started_at DESC
            """,
            set_id=set_id,
        )
        return [_run_row(r) for r in rows]

    def delete_run(self, run_id: str) -> None:
        self.run(
            "MATCH (r:EvalRun {id: $id}) OPTIONAL MATCH (r)-[:RESULT]->(res:EvalResult) DETACH DELETE res, r",
            id=run_id,
        )

    # ============================================================= results

    def add_result(self, run_id: str, question_id: str, result: dict[str, Any]) -> str:
        """
        result: {answer, thought, verdict, judge_score, judge_reason, exact_match, f1, recall (dict), gold_rank,
                 latency_ms, trace (dict), error}
        """
        result_id = new_id()
        self.run(
            """
            MATCH (r:EvalRun {id: $run_id}), (q:Question {id: $question_id})
            CREATE (res:EvalResult {id: $id, answer: $answer, thought: $thought, verdict: $verdict,
                                    judge_score: $judge_score, judge_reason: $judge_reason,
                                    exact_match: $exact_match, f1: $f1, recall_json: $recall_json,
                                    gold_rank: $gold_rank, latency_ms: $latency_ms, trace_json: $trace_json,
                                    error: $error, created_at: $now})
            MERGE (r)-[:RESULT]->(res)
            MERGE (res)-[:FOR]->(q)
            """,
            run_id=run_id,
            question_id=question_id,
            id=result_id,
            now=now_iso(),
            answer=result.get("answer", ""),
            thought=result.get("thought", ""),
            verdict=result.get("verdict", ""),
            judge_score=result.get("judge_score"),
            judge_reason=result.get("judge_reason", ""),
            exact_match=result.get("exact_match"),
            f1=result.get("f1"),
            recall_json=json.dumps(result.get("recall", {})),
            gold_rank=result.get("gold_rank"),
            latency_ms=result.get("latency_ms"),
            trace_json=json.dumps(result.get("trace", {})),
            error=result.get("error"),
        )
        return result_id

    def list_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (:EvalRun {id: $id})-[:RESULT]->(res:EvalResult)-[:FOR]->(q:Question)
            RETURN res AS res, q.id AS question_id, q.text AS question, q.expected_answer AS expected_answer,
                   q.kind AS kind, q.gold_passage_ids AS gold_passage_ids, q.ordinal AS ordinal
            ORDER BY q.ordinal
            """,
            id=run_id,
        )
        return [_result_row(r, with_trace=False) for r in rows]

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        row = self.run_one(
            """
            MATCH (r:EvalRun)-[:RESULT]->(res:EvalResult {id: $id})-[:FOR]->(q:Question)
            RETURN res AS res, q.id AS question_id, q.text AS question, q.expected_answer AS expected_answer,
                   q.kind AS kind, q.gold_passage_ids AS gold_passage_ids, q.ordinal AS ordinal,
                   r.id AS run_id, r.name AS run_name
            """,
            id=result_id,
        )
        return _result_row(row, with_trace=True) if row else None

    def results_for_question(self, question_id: str) -> list[dict[str, Any]]:
        """Every past result for one question, newest first (to see how answers changed over runs)."""
        rows = self.run(
            """
            MATCH (r:EvalRun)-[:RESULT]->(res:EvalResult)-[:FOR]->(q:Question {id: $id})
            RETURN res AS res, q.id AS question_id, q.text AS question, q.expected_answer AS expected_answer,
                   q.kind AS kind, q.gold_passage_ids AS gold_passage_ids, q.ordinal AS ordinal,
                   r.id AS run_id, r.name AS run_name
            ORDER BY res.created_at DESC
            """,
            id=question_id,
        )
        return [_result_row(r, with_trace=False) for r in rows]


# ------------------------------------------------------------- row shaping


SET_DEFAULTS: dict[str, Any] = {
    "origin": "manual",
    "status": "ready",
    "stage": "",
    "progress_done": 0,
    "progress_total": 0,
    "error": None,
    "created_at": "",
}
RUN_DEFAULTS: dict[str, Any] = {
    "status": "done",
    "started_at": "",
    "finished_at": None,
    "settings_json": "{}",
    "summary_json": "{}",
    "progress_done": 0,
    "progress_total": 0,
    "error": None,
}
RESULT_DEFAULTS: dict[str, Any] = {
    "answer": "",
    "thought": "",
    "verdict": "",
    "judge_score": None,
    "judge_reason": "",
    "exact_match": None,
    "f1": None,
    "recall_json": "{}",
    "gold_rank": None,
    "latency_ms": None,
    "trace_json": "{}",
    "error": None,
    "created_at": "",
}


def _set_row(row: dict[str, Any]) -> dict[str, Any]:
    qs = with_defaults(dict(row["qs"]), SET_DEFAULTS)
    qs["source_id"] = row.get("source_id")
    qs["source_name"] = row.get("source_name")
    qs["question_count"] = int(row.get("question_count", 0))
    qs["run_count"] = int(row.get("run_count", 0))
    return qs


def _run_row(row: dict[str, Any]) -> dict[str, Any]:
    run = with_defaults(dict(row["r"]), RUN_DEFAULTS)
    run["settings"] = json.loads(run.pop("settings_json", None) or "{}")
    run["summary"] = json.loads(run.pop("summary_json", None) or "{}")
    run["set_id"] = row.get("set_id")
    run["set_name"] = row.get("set_name")
    return run


def _result_row(row: dict[str, Any], with_trace: bool) -> dict[str, Any]:
    res = with_defaults(dict(row["res"]), RESULT_DEFAULTS)
    res["recall"] = json.loads(res.pop("recall_json", None) or "{}")
    trace_json = res.pop("trace_json", None)
    res["trace"] = json.loads(trace_json or "{}") if with_trace else None
    for key in (
        "question_id",
        "question",
        "expected_answer",
        "kind",
        "gold_passage_ids",
        "ordinal",
        "run_id",
        "run_name",
    ):
        if key in row:
            res[key] = row[key]
    return res
