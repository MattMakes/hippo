"""
An in-memory stand-in for `hippo.store.Store`.

It implements the same methods with the same row shapes, using dicts and
sets instead of Cypher. Tests run against this locally; in CI the same tests
also run against a real Neo4j (see tests/conftest.py), which keeps the two in
step. If you add a query to the real store, add it here too.
"""

from __future__ import annotations

import json
from typing import Any

from hippo.store.base import DEFAULT_SETTINGS, new_id, now_iso


class FakeStore:
    def __init__(self) -> None:
        self.sources: dict[str, dict[str, Any]] = {}
        self.passages: dict[str, dict[str, Any]] = {}
        self.entities: dict[str, dict[str, Any]] = {}
        self.facts: dict[str, dict[str, Any]] = {}
        self.mentions: set[tuple[str, str]] = set()  # (passage_id, entity_id)
        self.statements: set[tuple[str, str]] = set()  # (passage_id, fact_id)
        self.synonyms: dict[tuple[str, str], dict[str, Any]] = {}  # (a, b) a<b -> {score, manual}
        self.tuned: dict[tuple[str, str], float] = {}
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.meta: dict[str, Any] = {}
        self._graph_version = 0
        self.question_sets: dict[str, dict[str, Any]] = {}
        self.questions: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.results: dict[str, dict[str, Any]] = {}
        self.changesets: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------- base
    def close(self) -> None:
        pass

    def ping(self) -> bool:
        return True

    def ensure_schema(self) -> None:
        pass

    def get_settings(self) -> dict[str, Any]:
        return {k: self.settings.get(k, d) for k, d in DEFAULT_SETTINGS.items()}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        self.settings.update({k: v for k, v in changes.items() if k in DEFAULT_SETTINGS})
        return self.get_settings()

    def get_meta(self, key: str) -> Any:
        return self.meta.get(key)

    def set_meta(self, key: str, value: Any) -> None:
        self.meta[key] = value

    def graph_version(self) -> int:
        return self._graph_version

    def bump_graph_version(self) -> int:
        self._graph_version += 1
        return self._graph_version

    def stats(self) -> dict[str, int]:
        return {
            "sources": len(self.sources),
            "passages": len(self.passages),
            "entities": len(self.entities),
            "facts": len(self.facts),
            "synonym_edges": len(self.synonyms),
            "mention_edges": len(self.mentions),
            "question_sets": len(self.question_sets),
            "eval_runs": len(self.runs),
            "changesets": len(self.changesets),
        }

    # ---------------------------------------------------------- sources
    def create_source(self, kind: str, name: str, meta: dict[str, Any] | None = None) -> str:
        sid = new_id()
        self.sources[sid] = {
            "id": sid,
            "kind": kind,
            "name": name,
            "status": "queued",
            "stage": "queued",
            "progress_done": 0,
            "progress_total": 0,
            "error": None,
            "meta_json": json.dumps(meta or {}),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        return sid

    def update_source(self, source_id: str, **fields: Any) -> None:
        allowed = {"status", "stage", "progress_done", "progress_total", "error", "name", "meta_json"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown source fields: {sorted(bad)}")
        self.sources[source_id].update(fields, updated_at=now_iso())

    def _source_row(self, source: dict[str, Any]) -> dict[str, Any]:
        row = dict(source)
        row["meta"] = json.loads(row.pop("meta_json") or "{}")
        pids = [pid for pid, p in self.passages.items() if p["source_id"] == source["id"]]
        row["passages"] = len(pids)
        row["fact_links"] = sum(1 for pid, _ in self.statements if pid in pids)
        return row

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        s = self.sources.get(source_id)
        return self._source_row(s) if s else None

    def list_sources(self) -> list[dict[str, Any]]:
        return [
            self._source_row(s)
            for s in sorted(self.sources.values(), key=lambda s: s["created_at"], reverse=True)
        ]

    def delete_source(self, source_id: str) -> None:
        pids = {pid for pid, p in self.passages.items() if p["source_id"] == source_id}
        for pid in pids:
            del self.passages[pid]
        self.mentions = {m for m in self.mentions if m[0] not in pids}
        self.statements = {s for s in self.statements if s[0] not in pids}
        self.tuned = {k: v for k, v in self.tuned.items() if k[0] not in pids and k[1] not in pids}
        self.sources.pop(source_id, None)
        self.remove_orphans()

    def remove_orphans(self) -> None:
        stated = {fid for _, fid in self.statements}
        for fid in [f for f in self.facts if f not in stated]:
            del self.facts[fid]
        mentioned = {eid for _, eid in self.mentions}
        for eid in [e for e in self.entities if e not in mentioned]:
            del self.entities[eid]
            self.synonyms = {k: v for k, v in self.synonyms.items() if eid not in k}
            self.tuned = {k: v for k, v in self.tuned.items() if eid not in k}

    # --------------------------------------------------------- passages
    def add_passages(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            assert row["source_id"] in self.sources, "MATCH (s:Source) would find nothing"
            existing = self.passages.get(row["id"], {})
            self.passages[row["id"]] = {
                **existing,
                "id": row["id"],
                "source_id": row["source_id"],
                "ordinal": row["ordinal"],
                "title": row["title"],
                "text": row["text"],
                "embedding": list(row["embedding"]),
            }

    def save_extraction(
        self, passage_id: str, entities: list[str], triples: list[list[str]], error: str | None
    ) -> None:
        self.passages[passage_id].update(
            entities_json=json.dumps(entities), triples_json=json.dumps(triples), extraction_error=error
        )

    def _passage_row(self, p: dict[str, Any]) -> dict[str, Any]:
        s = self.sources[p["source_id"]]
        return {
            "id": p["id"],
            "title": p["title"],
            "text": p["text"],
            "ordinal": p["ordinal"],
            "source_id": s["id"],
            "source_name": s["name"],
            "entities": json.loads(p.get("entities_json") or "[]"),
            "triples": json.loads(p.get("triples_json") or "[]"),
            "extraction_error": p.get("extraction_error"),
        }

    def get_passages(self, ids: list[str]) -> list[dict[str, Any]]:
        return [self._passage_row(self.passages[i]) for i in ids if i in self.passages]

    def passages_for_source(self, source_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = sorted(
            (p for p in self.passages.values() if p["source_id"] == source_id), key=lambda p: p["ordinal"]
        )
        return [self._passage_row(p) for p in rows[offset : offset + limit]]

    def passage_ids_for_source(self, source_id: str) -> list[str]:
        rows = sorted(
            (p for p in self.passages.values() if p["source_id"] == source_id), key=lambda p: p["ordinal"]
        )
        return [p["id"] for p in rows]

    # --------------------------------------------------------- entities
    def existing_entity_ids(self, ids: list[str]) -> set[str]:
        return {i for i in ids if i in self.entities}

    def add_entities(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            e = self.entities.setdefault(row["id"], {"id": row["id"], "name": row["name"], "boost": None})
            e["embedding"] = list(row["embedding"])

    def _passage_count(self, eid: str) -> int:
        return sum(1 for _, e in self.mentions if e == eid)

    def get_entities(self, ids: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "id": i,
                "name": self.entities[i]["name"],
                "boost": self.entities[i].get("boost") or 1.0,
                "passage_count": self._passage_count(i),
            }
            for i in ids
            if i in self.entities
        ]

    def search_entities(self, text: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = [
            {"id": e["id"], "name": e["name"], "passage_count": self._passage_count(e["id"])}
            for e in self.entities.values()
            if text.lower() in e["name"]
        ]
        rows.sort(key=lambda r: (-r["passage_count"], r["name"]))
        return rows[:limit]

    def load_entity_embeddings(self) -> tuple[list[str], list[list[float]]]:
        ids = list(self.entities)
        return ids, [self.entities[i]["embedding"] for i in ids]

    # ------------------------------------------------------------ facts
    def existing_fact_ids(self, ids: list[str]) -> set[str]:
        return {i for i in ids if i in self.facts}

    def add_facts(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            assert row["subject_id"] in self.entities and row["object_id"] in self.entities, (
                "MATCH (a:Entity),(b:Entity) would find nothing"
            )
            f = self.facts.setdefault(
                row["id"],
                {
                    "id": row["id"],
                    "subject": row["subject"],
                    "predicate": row["predicate"],
                    "object": row["object"],
                    "subject_id": row["subject_id"],
                    "object_id": row["object_id"],
                },
            )
            f["embedding"] = list(row["embedding"])

    def _fact_row(self, f: dict[str, Any], with_embedding: bool) -> dict[str, Any]:
        row = {k: f[k] for k in ("id", "subject", "predicate", "object", "subject_id", "object_id")}
        row["passage_ids"] = [pid for pid, fid in self.statements if fid == f["id"]]
        if with_embedding:
            row["embedding"] = f["embedding"]
        return row

    def get_facts(self, ids: list[str]) -> list[dict[str, Any]]:
        return [self._fact_row(self.facts[i], False) for i in ids if i in self.facts]

    # ------------------------------------------------------------ links
    def link_passage_facts(self, pairs: list[tuple[str, str]]) -> None:
        for p, f in pairs:
            if p in self.passages and f in self.facts:
                self.statements.add((p, f))

    def link_passage_entities(self, pairs: list[tuple[str, str]]) -> None:
        for p, e in pairs:
            if p in self.passages and e in self.entities:
                self.mentions.add((p, e))

    def add_synonyms(self, rows: list[tuple[str, str, float]], manual: bool = False) -> None:
        for a, b, score in rows:
            if a == b or a not in self.entities or b not in self.entities:
                continue
            key = (min(a, b), max(a, b))
            current = self.synonyms.setdefault(key, {"score": None, "manual": False})
            if current["score"] is None or current["score"] < score:
                current["score"] = float(score)
            current["manual"] = current["manual"] or manual

    # ------------------------------------------------------- graph loads
    def load_entities(self) -> list[dict[str, Any]]:
        return [
            {
                "id": e["id"],
                "name": e["name"],
                "boost": e.get("boost") or 1.0,
                "passage_count": self._passage_count(e["id"]),
            }
            for e in self.entities.values()
        ]

    def load_passages(self) -> list[dict[str, Any]]:
        return [
            {
                "id": p["id"],
                "title": p["title"],
                "text": p["text"],
                "ordinal": p["ordinal"],
                "embedding": p["embedding"],
                "source_id": p["source_id"],
                "source_name": self.sources[p["source_id"]]["name"],
            }
            for p in self.passages.values()
        ]

    def load_facts(self) -> list[dict[str, Any]]:
        return [self._fact_row(f, True) for f in self.facts.values()]

    def load_fact_edges(self) -> list[dict[str, Any]]:
        counts: dict[tuple[str, str], int] = {}
        for _, fid in self.statements:
            f = self.facts[fid]
            if f["subject_id"] != f["object_id"]:
                key = (f["subject_id"], f["object_id"])
                counts[key] = counts.get(key, 0) + 1
        return [{"a": a, "b": b, "weight": w} for (a, b), w in counts.items()]

    def load_mentions(self) -> list[dict[str, Any]]:
        return [{"passage_id": p, "entity_id": e} for p, e in self.mentions]

    def load_synonyms(self) -> list[dict[str, Any]]:
        return [
            {"a": a, "b": b, "score": v["score"], "manual": v["manual"]}
            for (a, b), v in self.synonyms.items()
        ]

    def load_tuned_edges(self) -> list[dict[str, Any]]:
        return [{"a": a, "b": b, "weight": w} for (a, b), w in self.tuned.items()]

    # ---------------------------------------------------- question sets
    def create_question_set(self, name: str, source_id: str | None = None, origin: str = "manual") -> str:
        sid = new_id()
        self.question_sets[sid] = {
            "id": sid,
            "name": name,
            "origin": origin,
            "status": "ready",
            "stage": "",
            "progress_done": 0,
            "progress_total": 0,
            "error": None,
            "created_at": now_iso(),
            "source_id": source_id,
        }
        return sid

    def update_question_set(self, set_id: str, **fields: Any) -> None:
        allowed = {"status", "stage", "progress_done", "progress_total", "error", "name"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown question set fields: {sorted(bad)}")
        self.question_sets[set_id].update(fields)

    def add_questions(self, set_id: str, questions: list[dict[str, Any]]) -> list[str]:
        offset = sum(1 for q in self.questions.values() if q["set_id"] == set_id)
        ids = []
        for i, q in enumerate(questions):
            qid = new_id()
            self.questions[qid] = {
                "id": qid,
                "set_id": set_id,
                "text": q["text"],
                "expected_answer": q.get("expected_answer", ""),
                "gold_passage_ids": list(q.get("gold_passage_ids") or []),
                "kind": q.get("kind", "single"),
                "notes": q.get("notes", ""),
                "ordinal": offset + i,
            }
            ids.append(qid)
        return ids

    def delete_question(self, question_id: str) -> None:
        self.questions.pop(question_id, None)
        for rid in [r for r, res in self.results.items() if res["question_id"] == question_id]:
            del self.results[rid]

    def delete_question_set(self, set_id: str) -> None:
        for qid in [q for q, v in self.questions.items() if v["set_id"] == set_id]:
            self.delete_question(qid)
        for rid in [r for r, v in self.runs.items() if v["set_id"] == set_id]:
            self.delete_run(rid)
        self.question_sets.pop(set_id, None)

    def _set_row(self, qs: dict[str, Any]) -> dict[str, Any]:
        row = dict(qs)
        src = self.sources.get(qs.get("source_id") or "")
        row["source_name"] = src["name"] if src else None
        row["question_count"] = sum(1 for q in self.questions.values() if q["set_id"] == qs["id"])
        row["run_count"] = sum(1 for r in self.runs.values() if r["set_id"] == qs["id"])
        return row

    def get_question_set(self, set_id: str) -> dict[str, Any] | None:
        qs = self.question_sets.get(set_id)
        return self._set_row(qs) if qs else None

    def list_question_sets(self) -> list[dict[str, Any]]:
        return [
            self._set_row(qs)
            for qs in sorted(self.question_sets.values(), key=lambda s: s["created_at"], reverse=True)
        ]

    def _question_row(self, q: dict[str, Any]) -> dict[str, Any]:
        return {
            k: q[k] for k in ("id", "text", "expected_answer", "gold_passage_ids", "kind", "notes", "ordinal")
        }

    def list_questions(self, set_id: str) -> list[dict[str, Any]]:
        rows = sorted(
            (q for q in self.questions.values() if q["set_id"] == set_id), key=lambda q: q["ordinal"]
        )
        return [self._question_row(q) for q in rows]

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        q = self.questions.get(question_id)
        if not q:
            return None
        row = self._question_row(q)
        row["set_id"] = q["set_id"]
        row["set_name"] = self.question_sets[q["set_id"]]["name"]
        return row

    # ------------------------------------------------------------- runs
    def create_run(self, set_id: str, name: str, settings: dict[str, Any]) -> str:
        rid = new_id()
        self.runs[rid] = {
            "id": rid,
            "set_id": set_id,
            "name": name,
            "status": "running",
            "started_at": now_iso(),
            "finished_at": None,
            "settings_json": json.dumps(settings),
            "summary_json": "{}",
            "progress_done": 0,
            "progress_total": sum(1 for q in self.questions.values() if q["set_id"] == set_id),
            "error": None,
        }
        return rid

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "finished_at", "summary_json", "progress_done", "error", "name"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown run fields: {sorted(bad)}")
        self.runs[run_id].update(fields)

    def _run_row(self, r: dict[str, Any]) -> dict[str, Any]:
        row = dict(r)
        row["settings"] = json.loads(row.pop("settings_json") or "{}")
        row["summary"] = json.loads(row.pop("summary_json") or "{}")
        row["set_name"] = self.question_sets[r["set_id"]]["name"]
        return row

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        r = self.runs.get(run_id)
        return self._run_row(r) if r else None

    def list_runs(self, set_id: str | None = None) -> list[dict[str, Any]]:
        rows = [r for r in self.runs.values() if set_id is None or r["set_id"] == set_id]
        return [self._run_row(r) for r in sorted(rows, key=lambda r: r["started_at"], reverse=True)]

    def delete_run(self, run_id: str) -> None:
        for rid in [r for r, res in self.results.items() if res["run_id"] == run_id]:
            del self.results[rid]
        self.runs.pop(run_id, None)

    # ---------------------------------------------------------- results
    def add_result(self, run_id: str, question_id: str, result: dict[str, Any]) -> str:
        rid = new_id()
        self.results[rid] = {
            "id": rid,
            "run_id": run_id,
            "question_id": question_id,
            "answer": result.get("answer", ""),
            "thought": result.get("thought", ""),
            "verdict": result.get("verdict", ""),
            "judge_score": result.get("judge_score"),
            "judge_reason": result.get("judge_reason", ""),
            "exact_match": result.get("exact_match"),
            "f1": result.get("f1"),
            "recall_json": json.dumps(result.get("recall", {})),
            "gold_rank": result.get("gold_rank"),
            "latency_ms": result.get("latency_ms"),
            "trace_json": json.dumps(result.get("trace", {})),
            "error": result.get("error"),
            "created_at": now_iso(),
        }
        return rid

    def _result_row(self, res: dict[str, Any], with_trace: bool) -> dict[str, Any]:
        row = dict(res)
        row["recall"] = json.loads(row.pop("recall_json") or "{}")
        trace_json = row.pop("trace_json")
        row["trace"] = json.loads(trace_json or "{}") if with_trace else None
        q = self.questions[res["question_id"]]
        row.update(
            question=q["text"],
            expected_answer=q["expected_answer"],
            kind=q["kind"],
            gold_passage_ids=q["gold_passage_ids"],
            ordinal=q["ordinal"],
            run_name=self.runs[res["run_id"]]["name"],
        )
        return row

    def list_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = [r for r in self.results.values() if r["run_id"] == run_id]
        rows.sort(key=lambda r: self.questions[r["question_id"]]["ordinal"])
        return [self._result_row(r, False) for r in rows]

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        r = self.results.get(result_id)
        return self._result_row(r, True) if r else None

    def results_for_question(self, question_id: str) -> list[dict[str, Any]]:
        rows = [r for r in self.results.values() if r["question_id"] == question_id]
        return [self._result_row(r, False) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]

    # ------------------------------------------------------- changesets
    def create_changeset(
        self, name: str, ops: list[dict[str, Any]], from_result_id: str | None = None, note: str = ""
    ) -> str:
        cid = new_id()
        self.changesets[cid] = {
            "id": cid,
            "name": name,
            "note": note,
            "status": "draft",
            "ops_json": json.dumps(ops),
            "created_at": now_iso(),
            "applied_at": None,
            "from_result_id": from_result_id,
        }
        return cid

    def _changeset_row(self, c: dict[str, Any]) -> dict[str, Any]:
        row = dict(c)
        row["ops"] = json.loads(row.pop("ops_json") or "[]")
        return row

    def get_changeset(self, changeset_id: str) -> dict[str, Any] | None:
        c = self.changesets.get(changeset_id)
        return self._changeset_row(c) if c else None

    def list_changesets(self) -> list[dict[str, Any]]:
        return [
            self._changeset_row(c)
            for c in sorted(self.changesets.values(), key=lambda c: c["created_at"], reverse=True)
        ]

    def delete_changeset(self, changeset_id: str) -> None:
        self.changesets.pop(changeset_id, None)

    def mark_applied(self, changeset_id: str) -> None:
        self.changesets[changeset_id].update(status="applied", applied_at=now_iso())

    def set_node_boost(self, entity_id: str, boost: float) -> None:
        if entity_id in self.entities:
            self.entities[entity_id]["boost"] = float(boost)

    def set_edge_weight(self, a: str, b: str, weight: float) -> None:
        known = set(self.entities) | set(self.passages)
        if a in known and b in known:
            self.tuned[(min(a, b), max(a, b))] = float(weight)

    def clear_edge_weight(self, a: str, b: str) -> None:
        self.tuned.pop((min(a, b), max(a, b)), None)
