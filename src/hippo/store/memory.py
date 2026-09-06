"""
Queries for the memory itself: sources, passages, entities, facts and their links.

Reading tip: the `load_*` functions at the bottom are what the in-memory
graph (hipporag/graph_index.py) uses to rebuild itself.
"""

from __future__ import annotations

import json
from typing import Any

from .base import Neo4jBase, new_id, now_iso

BATCH = 200  # rows per write query; keeps transactions small and progress visible


def _batches(rows: list[Any], size: int = BATCH):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


class MemoryQueries(Neo4jBase):
    # ============================================================== sources
    # A Source is one thing you uploaded: a file, a pasted text, a git repo.

    def create_source(self, kind: str, name: str, meta: dict[str, Any] | None = None) -> str:
        source_id = new_id()
        self.run(
            """
            CREATE (s:Source {id: $id, kind: $kind, name: $name, status: 'queued', stage: 'queued',
                              progress_done: 0, progress_total: 0, error: null,
                              meta_json: $meta_json, created_at: $now, updated_at: $now})
            """,
            id=source_id,
            kind=kind,
            name=name,
            meta_json=json.dumps(meta or {}),
            now=now_iso(),
        )
        return source_id

    def update_source(self, source_id: str, **fields: Any) -> None:
        """Update status/stage/progress/error on a source. Unknown keys are refused so typos are loud."""
        allowed = {"status", "stage", "progress_done", "progress_total", "error", "name", "meta_json"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown source fields: {sorted(bad)}")
        fields["updated_at"] = now_iso()
        self.run("MATCH (s:Source {id: $id}) SET s += $fields", id=source_id, fields=fields)

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        row = self.run_one(
            """
            MATCH (s:Source {id: $id})
            RETURN s AS s, count { (s)<-[:FROM]-(:Passage) } AS passages,
                   count { (s)<-[:FROM]-(:Passage)-[:STATES]->(:Fact) } AS fact_links
            """,
            id=source_id,
        )
        return _source_row(row) if row else None

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (s:Source)
            RETURN s AS s, count { (s)<-[:FROM]-(:Passage) } AS passages,
                   count { (s)<-[:FROM]-(:Passage)-[:STATES]->(:Fact) } AS fact_links
            ORDER BY s.created_at DESC
            """
        )
        return [_source_row(r) for r in rows]

    def delete_source(self, source_id: str) -> None:
        """Delete a source and its passages, then any entities/facts that nothing mentions any more."""
        while True:
            row = self.run_one(
                """
                MATCH (s:Source {id: $id})<-[:FROM]-(p:Passage)
                WITH p LIMIT 500
                DETACH DELETE p
                RETURN count(*) AS deleted
                """,
                id=source_id,
            )
            if not row or row["deleted"] == 0:
                break
        self.run("MATCH (s:Source {id: $id}) DETACH DELETE s", id=source_id)
        self.remove_orphans()

    def remove_orphans(self) -> None:
        self.run("MATCH (f:Fact) WHERE NOT (f)<-[:STATES]-() DETACH DELETE f")
        self.run("MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e")

    # ============================================================= passages

    def add_passages(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, source_id, ordinal, title, text, embedding}."""
        for batch in _batches(rows):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (s:Source {id: row.source_id})
                MERGE (p:Passage {id: row.id})
                SET p.title = row.title, p.text = row.text, p.ordinal = row.ordinal, p.chars = size(row.text)
                MERGE (p)-[:FROM]->(s)
                WITH p, row
                CALL db.create.setNodeVectorProperty(p, 'embedding', row.embedding)
                """,
                rows=batch,
            )

    def save_extraction(
        self, passage_id: str, entities: list[str], triples: list[list[str]], error: str | None
    ) -> None:
        """Keep what the LLM extracted from a passage, so you can look at it later."""
        self.run(
            """
            MATCH (p:Passage {id: $id})
            SET p.entities_json = $entities, p.triples_json = $triples, p.extraction_error = $error
            """,
            id=passage_id,
            entities=json.dumps(entities),
            triples=json.dumps(triples),
            error=error,
        )

    def get_passages(self, ids: list[str]) -> list[dict[str, Any]]:
        rows = self.run(
            """
            UNWIND $ids AS id
            MATCH (p:Passage {id: id})-[:FROM]->(s:Source)
            RETURN p.id AS id, p.title AS title, p.text AS text, p.ordinal AS ordinal,
                   s.id AS source_id, s.name AS source_name,
                   p.entities_json AS entities_json, p.triples_json AS triples_json, p.extraction_error AS extraction_error
            """,
            ids=ids,
        )
        return [_passage_row(r) for r in rows]

    def passages_for_source(self, source_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (p:Passage)-[:FROM]->(s:Source {id: $id})
            RETURN p.id AS id, p.title AS title, p.text AS text, p.ordinal AS ordinal,
                   s.id AS source_id, s.name AS source_name,
                   p.entities_json AS entities_json, p.triples_json AS triples_json, p.extraction_error AS extraction_error
            ORDER BY p.ordinal SKIP $offset LIMIT $limit
            """,
            id=source_id,
            limit=limit,
            offset=offset,
        )
        return [_passage_row(r) for r in rows]

    def passage_ids_for_source(self, source_id: str) -> list[str]:
        rows = self.run(
            "MATCH (p:Passage)-[:FROM]->(:Source {id: $id}) RETURN p.id AS id ORDER BY p.ordinal",
            id=source_id,
        )
        return [r["id"] for r in rows]

    # ============================================================= entities

    def existing_entity_ids(self, ids: list[str]) -> set[str]:
        rows = self.run("UNWIND $ids AS id MATCH (e:Entity {id: id}) RETURN e.id AS id", ids=ids)
        return {r["id"] for r in rows}

    def add_entities(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, name, embedding}. Callers pass only new ids (see existing_entity_ids); re-adding is harmless."""
        for batch in _batches(rows):
            self.run(
                """
                UNWIND $rows AS row
                MERGE (e:Entity {id: row.id})
                ON CREATE SET e.name = row.name, e.created_at = $now
                WITH e, row
                CALL db.create.setNodeVectorProperty(e, 'embedding', row.embedding)
                """,
                rows=batch,
                now=now_iso(),
            )

    def get_entities(self, ids: list[str]) -> list[dict[str, Any]]:
        rows = self.run(
            """
            UNWIND $ids AS id
            MATCH (e:Entity {id: id})
            RETURN e.id AS id, e.name AS name, coalesce(e.boost, 1.0) AS boost,
                   count { (e)<-[:MENTIONS]-() } AS passage_count
            """,
            ids=ids,
        )
        return rows

    def search_entities(self, text: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (e:Entity) WHERE e.name CONTAINS $text
            RETURN e.id AS id, e.name AS name, count { (e)<-[:MENTIONS]-() } AS passage_count
            ORDER BY passage_count DESC, e.name LIMIT $limit
            """,
            text=text.lower(),
            limit=limit,
        )
        return rows

    def load_entity_embeddings(self) -> tuple[list[str], list[list[float]]]:
        """Every entity's id and vector (used to find synonyms for new entities)."""
        rows = self.run("MATCH (e:Entity) RETURN e.id AS id, e.embedding AS embedding")
        return [r["id"] for r in rows], [r["embedding"] for r in rows]

    # ================================================================ facts

    def existing_fact_ids(self, ids: list[str]) -> set[str]:
        rows = self.run("UNWIND $ids AS id MATCH (f:Fact {id: id}) RETURN f.id AS id", ids=ids)
        return {r["id"] for r in rows}

    def add_facts(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, subject, predicate, object, subject_id, object_id, embedding}. Callers pass only new ids."""
        for batch in _batches(rows):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (a:Entity {id: row.subject_id}), (b:Entity {id: row.object_id})
                MERGE (f:Fact {id: row.id})
                ON CREATE SET f.subject = row.subject, f.predicate = row.predicate, f.object = row.object,
                              f.created_at = $now
                MERGE (f)-[:SUBJECT]->(a)
                MERGE (f)-[:OBJECT]->(b)
                WITH f, row
                CALL db.create.setNodeVectorProperty(f, 'embedding', row.embedding)
                """,
                rows=batch,
                now=now_iso(),
            )

    def get_facts(self, ids: list[str]) -> list[dict[str, Any]]:
        rows = self.run(
            """
            UNWIND $ids AS id
            MATCH (f:Fact {id: id})-[:SUBJECT]->(a:Entity), (f)-[:OBJECT]->(b:Entity)
            RETURN f.id AS id, f.subject AS subject, f.predicate AS predicate, f.object AS object,
                   a.id AS subject_id, b.id AS object_id,
                   [(p:Passage)-[:STATES]->(f) | p.id] AS passage_ids
            """,
            ids=ids,
        )
        return rows

    # ================================================================ links

    def link_passage_facts(self, pairs: list[tuple[str, str]]) -> None:
        rows = [{"passage_id": p, "fact_id": f} for p, f in pairs]
        for batch in _batches(rows, 1000):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (p:Passage {id: row.passage_id}), (f:Fact {id: row.fact_id})
                MERGE (p)-[:STATES]->(f)
                """,
                rows=batch,
            )

    def link_passage_entities(self, pairs: list[tuple[str, str]]) -> None:
        rows = [{"passage_id": p, "entity_id": e} for p, e in pairs]
        for batch in _batches(rows, 1000):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (p:Passage {id: row.passage_id}), (e:Entity {id: row.entity_id})
                MERGE (p)-[:MENTIONS]->(e)
                """,
                rows=batch,
            )

    def add_synonyms(self, rows: list[tuple[str, str, float]], manual: bool = False) -> None:
        """rows: (entity_id_a, entity_id_b, score). Stored once per pair (a < b), keeping the best score."""
        canonical = [
            {"a": min(a, b), "b": max(a, b), "score": float(score)} for a, b, score in rows if a != b
        ]
        for batch in _batches(canonical, 1000):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (a:Entity {id: row.a}), (b:Entity {id: row.b})
                MERGE (a)-[s:SYNONYM]->(b)
                SET s.score = CASE WHEN s.score IS NULL OR s.score < row.score THEN row.score ELSE s.score END,
                    s.manual = coalesce(s.manual, false) OR $manual
                """,
                rows=batch,
                manual=manual,
            )

    # ====================================================== loading the graph
    # These feed hipporag/graph_index.py. Each returns plain lists so that file
    # can build numpy arrays and an igraph without knowing about Neo4j.

    def load_entities(self) -> list[dict[str, Any]]:
        return self.run(
            """
            MATCH (e:Entity)
            RETURN e.id AS id, e.name AS name, coalesce(e.boost, 1.0) AS boost,
                   count { (e)<-[:MENTIONS]-() } AS passage_count
            """
        )

    def load_passages(self) -> list[dict[str, Any]]:
        return self.run(
            """
            MATCH (p:Passage)-[:FROM]->(s:Source)
            RETURN p.id AS id, p.title AS title, p.text AS text, p.ordinal AS ordinal, p.embedding AS embedding,
                   s.id AS source_id, s.name AS source_name
            """
        )

    def load_facts(self) -> list[dict[str, Any]]:
        return self.run(
            """
            MATCH (f:Fact)-[:SUBJECT]->(a:Entity), (f)-[:OBJECT]->(b:Entity)
            RETURN f.id AS id, f.subject AS subject, f.predicate AS predicate, f.object AS object,
                   a.id AS subject_id, b.id AS object_id, f.embedding AS embedding,
                   [(p:Passage)-[:STATES]->(f) | p.id] AS passage_ids
            """
        )

    def load_fact_edges(self) -> list[dict[str, Any]]:
        """Entity-entity edges: one count per (passage, fact) that connects the two entities."""
        return self.run(
            """
            MATCH (p:Passage)-[:STATES]->(f:Fact), (f)-[:SUBJECT]->(a:Entity), (f)-[:OBJECT]->(b:Entity)
            WHERE a.id <> b.id
            RETURN a.id AS a, b.id AS b, count(*) AS weight
            """
        )

    def load_mentions(self) -> list[dict[str, Any]]:
        return self.run(
            "MATCH (p:Passage)-[:MENTIONS]->(e:Entity) RETURN p.id AS passage_id, e.id AS entity_id"
        )

    def load_synonyms(self) -> list[dict[str, Any]]:
        return self.run(
            "MATCH (a:Entity)-[s:SYNONYM]->(b:Entity) RETURN a.id AS a, b.id AS b, s.score AS score, coalesce(s.manual, false) AS manual"
        )

    def load_tuned_edges(self) -> list[dict[str, Any]]:
        return self.run("MATCH (a)-[t:TUNED]->(b) RETURN a.id AS a, b.id AS b, t.weight AS weight")


# ------------------------------------------------------------- row shaping


def _source_row(row: dict[str, Any]) -> dict[str, Any]:
    source = dict(row["s"])
    source["meta"] = json.loads(source.pop("meta_json", None) or "{}")
    source["passages"] = int(row.get("passages", 0))
    source["fact_links"] = int(row.get("fact_links", 0))
    return source


def _passage_row(row: dict[str, Any]) -> dict[str, Any]:
    passage = dict(row)
    passage["entities"] = json.loads(passage.pop("entities_json", None) or "[]")
    passage["triples"] = json.loads(passage.pop("triples_json", None) or "[]")
    return passage
