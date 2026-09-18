"""
Queries for the memory itself: sources, passages, entities, facts and their links.

Reading tip: the `load_*` functions at the bottom are what the in-memory
graph (hipporag/graph_index.py) uses to rebuild itself.

Access: every read that hands back sources, passages, entities or facts takes
an `access` (hippo/access.py). `None` means "unrestricted" (the indexer, the
graph loader and the CLI); a web or MCP request passes the caller's Access and
the ACCESS_WHERE predicate keeps hidden sources, and everything only they
support, out of the result. Entities and facts are shared between sources, so
they count as visible when at least one visible passage mentions/states them,
and their passage counts only count visible passages.
"""

from __future__ import annotations

import json
from typing import Any

from ..access import ACCESS_WHERE, Access, access_params
from .authorization import permission_mutation
from .base import Neo4jBase, new_id, now_iso, with_defaults
from .code import SYNONYM_LABELS, grouped_by_labels
from .generations import (
    INTERRUPTED_REFRESH_ERROR,
    INTERRUPTED_REFRESH_STAGE,
    REFRESHING_PREFIX,
    legacy_source_cleanup,
    native_mutation,
    native_write,
)
from .migrations import DEFAULT_WORKSPACE_ID

BATCH = 200  # rows per write query; keeps transactions small and progress visible


def _batches(rows: list[Any], size: int = BATCH):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


class MemoryQueries(Neo4jBase):
    # ============================================================== sources
    # A Source is one thing you uploaded: a file, a pasted text, a git repo.

    def create_source(
        self,
        kind: str,
        name: str,
        meta: dict[str, Any] | None = None,
        *,
        owner_id: str | None = None,
        access_role_id: str | None = None,
    ) -> str:
        """
        A new source. `access_role_id` names the lowest role that may see it (None = everyone);
        its rank is copied to min_rank so ACCESS_WHERE is one comparison. The owner always sees it.
        """
        source_id = new_id()
        self.run(
            """
            OPTIONAL MATCH (r:Role {id: $access_role_id})
            CREATE (s:Source {id: $id, kind: $kind, name: $name, status: 'queued', stage: 'queued',
                              progress_done: 0, progress_total: 0, error: null,
                              meta_json: $meta_json, created_at: $now, updated_at: $now,
                              owner_id: $owner_id, access_role_id: r.id, min_rank: coalesce(r.rank, 0)})
            """,
            id=source_id,
            kind=kind,
            name=name,
            meta_json=json.dumps(meta or {}),
            now=now_iso(),
            owner_id=owner_id,
            access_role_id=access_role_id,
        )
        if getattr(self, "_schema_checked", False):
            self.run(
                "MATCH (s:Source {id:$id}) SET s.workspace_id=$workspace, s.generation_version=0",
                id=source_id,
                workspace=DEFAULT_WORKSPACE_ID,
            )
            if self.schema_version()["version"] >= 4:
                self.run(
                    "MATCH (s:Source {id:$id}) SET s.managed=false, s.build_fencing_token=0", id=source_id
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

    def get_source(self, source_id: str, access: Access | None = None) -> dict[str, Any] | None:
        row = self.run_one(
            f"""
            MATCH (s:Source {{id: $id}}) WHERE {ACCESS_WHERE}
            OPTIONAL MATCH (r:Role {{id: s.access_role_id}})
            OPTIONAL MATCH (u:User {{id: s.owner_id}})
            RETURN s AS s, r.name AS access_role_name, u.username AS owner_name,
                   count {{ (s)<-[:FROM]-(:Passage) }} AS passages,
                   count {{ (s)<-[:FROM]-(:Passage)-[:STATES]->(:Fact) }} AS fact_links
            """,
            id=source_id,
            **access_params(access),
        )
        return _source_row(row) if row else None

    def list_sources(self, access: Access | None = None) -> list[dict[str, Any]]:
        rows = self.run(
            f"""
            MATCH (s:Source) WHERE {ACCESS_WHERE}
            OPTIONAL MATCH (r:Role {{id: s.access_role_id}})
            OPTIONAL MATCH (u:User {{id: s.owner_id}})
            RETURN s AS s, r.name AS access_role_name, u.username AS owner_name,
                   count {{ (s)<-[:FROM]-(:Passage) }} AS passages,
                   count {{ (s)<-[:FROM]-(:Passage)-[:STATES]->(:Fact) }} AS fact_links
            ORDER BY s.created_at DESC
            """,
            **access_params(access),
        )
        return [_source_row(r) for r in rows]

    @permission_mutation
    @legacy_source_cleanup
    def delete_source(self, source_id: str) -> None:
        """Delete a source and its passages, then any entities/facts that nothing mentions any more."""
        self.delete_code_nodes_for_source(source_id)  # CodeQueries; both are mixins of Store
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

    @legacy_source_cleanup
    def delete_passages_for_source(self, source_id: str) -> None:
        """Forget a source's passages (and whatever only they supported) but keep the Source row, for re-indexing."""
        self.delete_code_nodes_for_source(source_id)  # CodeQueries; both are mixins of Store
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
        self.remove_orphans()

    def mark_interrupted_jobs(self) -> int:
        """
        After a restart, nothing is running any more: sources still 'reading'/'indexing', runs still
        'running' and question sets still 'generating' are marked failed so the UI does not wait forever.

        A managed refresh is the one job that is not failed by this: it never stopped serving, so it
        keeps its status, its active generation and its counts, and only its stage is retired.
        """
        message = "interrupted by a restart; run it again"
        now = now_iso()
        sources = self.run_one(
            """
            MATCH (s:Source) WHERE s.status IN ['reading', 'indexing']
            SET s.status = 'failed', s.error = $message, s.updated_at = $now
            RETURN count(s) AS n
            """,
            message=message,
            now=now,
        )
        runs = self.run_one(
            """
            MATCH (r:EvalRun {status: 'running'})
            SET r.status = 'failed', r.error = $message, r.finished_at = $now
            RETURN count(r) AS n
            """,
            message=message,
            now=now,
        )
        sets = self.run_one(
            """
            MATCH (qs:QuestionSet {status: 'generating'})
            SET qs.status = 'failed', qs.error = $message
            RETURN count(qs) AS n
            """,
            message=message,
        )
        # Read the ids before the rewrite: past it the predicate no longer matches, and the
        # build holder each one is still carrying has to be released or the reindex the new
        # error asks for is refused with `BuildBusy` until its lease expires.
        refreshing = "s.status = 'ready' AND s.stage STARTS WITH $prefix"
        interrupted = [
            row["id"]
            for row in self.run(
                f"MATCH (s:Source) WHERE {refreshing} RETURN s.id AS id", prefix=REFRESHING_PREFIX
            )
        ]
        if interrupted:
            self.run(
                f"MATCH (s:Source) WHERE {refreshing} "
                "SET s.stage = $stage, s.error = $error, s.updated_at = $now",
                prefix=REFRESHING_PREFIX,
                stage=INTERRUPTED_REFRESH_STAGE,
                error=INTERRUPTED_REFRESH_ERROR,
                now=now,
            )
            for source_id in interrupted:
                self.release_interrupted_build(source_id)
        return len(interrupted) + sum(int((row or {}).get("n", 0)) for row in (sources, runs, sets))

    def remove_orphans(self) -> None:
        self.run("MATCH (f:Fact) WHERE NOT (f)<-[:STATES]-() DETACH DELETE f")
        self.run("MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e")

    # ============================================================= passages

    @native_write("Passage")
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

    @native_mutation
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

    def get_passages(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        rows = self.run(
            f"""
            UNWIND $ids AS id
            MATCH (p:Passage {{id: id}})-[:FROM]->(s:Source) WHERE {ACCESS_WHERE}
            RETURN p.id AS id, p.title AS title, p.text AS text, p.ordinal AS ordinal,
                   s.id AS source_id, s.name AS source_name,
                   p.entities_json AS entities_json, p.triples_json AS triples_json, p.extraction_error AS extraction_error
            """,
            ids=ids,
            **access_params(access),
        )
        return [_passage_row(r) for r in rows]

    def passages_for_source(
        self, source_id: str, limit: int = 50, offset: int = 0, access: Access | None = None
    ) -> list[dict[str, Any]]:
        rows = self.run(
            f"""
            MATCH (p:Passage)-[:FROM]->(s:Source {{id: $id}}) WHERE {ACCESS_WHERE}
            RETURN p.id AS id, p.title AS title, p.text AS text, p.ordinal AS ordinal,
                   s.id AS source_id, s.name AS source_name,
                   p.entities_json AS entities_json, p.triples_json AS triples_json, p.extraction_error AS extraction_error
            ORDER BY p.ordinal SKIP $offset LIMIT $limit
            """,
            id=source_id,
            limit=limit,
            offset=offset,
            **access_params(access),
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

    @native_mutation
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

    def get_entities(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        # An entity is visible when a visible passage mentions it, and its passage_count counts
        # visible passages only (a count over hidden passages would leak that they exist). Unrestricted
        # reads keep entities nothing mentions yet: the indexer looks them up before linking them.
        rows = self.run(
            f"""
            UNWIND $ids AS id
            MATCH (e:Entity {{id: id}})
            WITH e, count {{ (e)<-[:MENTIONS]-(:Passage)-[:FROM]->(s:Source) WHERE {ACCESS_WHERE} }} AS passage_count
            WHERE $acc_all OR passage_count > 0
            RETURN e.id AS id, e.name AS name, coalesce(e.boost, 1.0) AS boost, passage_count
            """,
            ids=ids,
            **access_params(access),
        )
        return rows

    def search_entities(
        self, text: str, limit: int = 20, access: Access | None = None
    ) -> list[dict[str, Any]]:
        rows = self.run(
            f"""
            MATCH (e:Entity) WHERE e.name CONTAINS $text
            WITH e, count {{ (e)<-[:MENTIONS]-(:Passage)-[:FROM]->(s:Source) WHERE {ACCESS_WHERE} }} AS passage_count
            WHERE $acc_all OR passage_count > 0
            RETURN e.id AS id, e.name AS name, passage_count
            ORDER BY passage_count DESC, e.name LIMIT $limit
            """,
            text=text.lower(),
            limit=limit,
            **access_params(access),
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

    @native_mutation
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

    def get_facts(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        # A fact is visible when a visible passage states it; only those passages are listed.
        rows = self.run(
            f"""
            UNWIND $ids AS id
            MATCH (f:Fact {{id: id}})-[:SUBJECT]->(a:Entity), (f)-[:OBJECT]->(b:Entity)
            WITH f, a, b,
                 [(p:Passage)-[:STATES]->(f) WHERE EXISTS {{ (p)-[:FROM]->(s:Source) WHERE {ACCESS_WHERE} }} | p.id] AS passage_ids
            WHERE $acc_all OR size(passage_ids) > 0
            RETURN f.id AS id, f.subject AS subject, f.predicate AS predicate, f.object AS object,
                   a.id AS subject_id, b.id AS object_id, passage_ids
            """,
            ids=ids,
            **access_params(access),
        )
        return rows

    # ================================================================ links

    @native_mutation
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

    @native_mutation
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

    @native_mutation
    def add_synonyms(self, rows: list[tuple[str, str, float]], manual: bool = False) -> None:
        """
        rows: (node_id_a, node_id_b, score). Stored once per pair (a < b), keeping the best score.

        Either id may be an entity, a symbol or a data object. The label comes from the id prefix
        (`label_of`, S2.2) so the write binds one concrete label pair here as it must on LadybugDB,
        and the two backends stay one query apart rather than one dialect apart.
        """
        best: dict[tuple[str, str], float] = {}
        for a, b, score in rows:
            if a != b:
                key = (min(a, b), max(a, b))
                best[key] = max(best.get(key, 0.0), float(score))
        for (label_a, label_b), group in grouped_by_labels(best, SYNONYM_LABELS).items():
            for batch in _batches(group, 1000):
                self.run(
                    f"""
                    UNWIND $rows AS row
                    MATCH (a:{label_a} {{id: row.a}}), (b:{label_b} {{id: row.b}})
                    MERGE (a)-[s:SYNONYM]->(b)
                    SET s.score = CASE WHEN s.score IS NULL OR s.score < row.score
                                       THEN row.score ELSE s.score END,
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
                   count { (e)<-[:MENTIONS]-() } AS passage_count, e.created_at AS created_at
            """
        )

    def load_passages(self) -> list[dict[str, Any]]:
        return self.run(
            """
            MATCH (p:Passage)-[:FROM]->(s:Source)
            RETURN p.id AS id, p.title AS title, p.text AS text, p.ordinal AS ordinal, p.embedding AS embedding, p.generation_id AS generation_id, p.retrieval_view_id AS retrieval_view_id,
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
        # Unlabelled, like load_tuned_edges: SYNONYM now joins entities, symbols and data
        # objects, and a labelled MATCH would silently drop every cross-kind row.
        return self.run(
            "MATCH (a)-[s:SYNONYM]->(b) RETURN a.id AS a, b.id AS b, s.score AS score, coalesce(s.manual, false) AS manual"
        )

    def load_tuned_edges(self) -> list[dict[str, Any]]:
        return self.run("MATCH (a)-[t:TUNED]->(b) RETURN a.id AS a, b.id AS b, t.weight AS weight")


# ------------------------------------------------------------- row shaping


SOURCE_DEFAULTS: dict[str, Any] = {
    "status": "queued",
    "stage": "",
    "progress_done": 0,
    "progress_total": 0,
    "error": None,
    "meta_json": "{}",
    "created_at": "",
    "updated_at": "",
    "owner_id": None,
    "workspace_id": DEFAULT_WORKSPACE_ID,
    "active_generation_id": None,
    "generation_version": 0,
    "managed": False,
    "active_build_id": None,
    "build_fencing_token": 0,
    "access_role_id": None,
    "min_rank": 0,
}


def _source_row(row: dict[str, Any]) -> dict[str, Any]:
    source = with_defaults(dict(row["s"]), SOURCE_DEFAULTS)
    source["meta"] = json.loads(source.pop("meta_json", None) or "{}")
    source["passages"] = int(row.get("passages", 0))
    source["fact_links"] = int(row.get("fact_links", 0))
    source["min_rank"] = int(source.get("min_rank") or 0)
    source["access_role_name"] = row.get("access_role_name") or (
        "Everyone" if not source.get("access_role_id") else source["access_role_id"]
    )
    source["owner_name"] = row.get("owner_name") or ""
    return source


def _passage_row(row: dict[str, Any]) -> dict[str, Any]:
    passage = with_defaults(dict(row), {"extraction_error": None, "title": "", "text": "", "ordinal": 0})
    passage["entities"] = json.loads(passage.pop("entities_json", None) or "[]")
    passage["triples"] = json.loads(passage.pop("triples_json", None) or "[]")
    return passage
