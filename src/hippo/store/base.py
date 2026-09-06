"""Connecting to Neo4j, running queries, and the handful of global records (settings, stats)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from neo4j import GraphDatabase

log = logging.getLogger(__name__)

# The retrieval knobs, with the reference implementation's defaults (BaseConfig in HippoRAG 2).
DEFAULT_SETTINGS: dict[str, Any] = {
    "linking_top_k": 5,  # how many facts we pull for a question, and how many entities we seed PPR with
    "passage_node_weight": 0.05,  # how much the passages' own similarity to the question seeds PPR
    "damping": 0.5,  # PPR damping: lower = stay close to the seeds, higher = wander further
    "node_specificity": True,  # entities that appear in many passages get a smaller seed weight (like IDF)
    "synonymy_threshold": 0.8,  # cosine similarity above which two entity names are linked as synonyms
    "retrieval_top_k": 200,  # how many passages a retrieval returns (and we keep in traces)
    "qa_top_k": 5,  # how many passages the LLM reads when answering
}

CONSTRAINTS = [
    "CREATE CONSTRAINT source_id IF NOT EXISTS FOR (n:Source) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT passage_id IF NOT EXISTS FOR (n:Passage) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (n:Fact) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT question_set_id IF NOT EXISTS FOR (n:QuestionSet) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT question_id IF NOT EXISTS FOR (n:Question) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT eval_run_id IF NOT EXISTS FOR (n:EvalRun) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT eval_result_id IF NOT EXISTS FOR (n:EvalResult) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT changeset_id IF NOT EXISTS FOR (n:Changeset) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT settings_id IF NOT EXISTS FOR (n:Settings) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
]


def with_defaults(node: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """
    Neo4j does not store a property whose value is null, so a node created with `error: null`
    comes back without an `error` key at all. Every row-shaping function runs its node through
    this so callers (and the in-memory FakeStore) always see the same keys.
    """
    shaped = dict(defaults)
    shaped.update(node)
    return shaped


def new_id() -> str:
    """A short random id for app records (sources, runs, ...). Graph nodes use content hashes instead."""
    return uuid4().hex[:12]


def now_iso() -> str:
    # Microseconds so rows created in the same second still sort "newest first".
    return datetime.now(UTC).isoformat(timespec="microseconds")


class Neo4jBase:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self) -> None:
        self.driver.close()

    # ------------------------------------------------------------ running

    def run(self, query: str, **params: Any) -> list[dict[str, Any]]:
        """Run one Cypher query in its own transaction and return the rows as dicts."""
        result = self.driver.execute_query(query, parameters_=params, database_=self.database)
        return [record.data() for record in result.records]

    def run_one(self, query: str, **params: Any) -> dict[str, Any] | None:
        rows = self.run(query, **params)
        return rows[0] if rows else None

    def ping(self) -> bool:
        try:
            self.driver.verify_connectivity()
            return True
        except Exception as exc:  # noqa: BLE001 - any driver error means "not reachable"
            log.warning("Neo4j not reachable: %s", exc)
            return False

    # ------------------------------------------------------------- schema

    def ensure_schema(self) -> None:
        """Create constraints/indexes and the global Settings node. Safe to call on every start."""
        for statement in CONSTRAINTS:
            self.run(statement)
        self.run(
            "MERGE (s:Settings {id: 'global'}) ON CREATE SET s += $defaults, s.graph_version = 0",
            defaults=DEFAULT_SETTINGS,
        )

    # ----------------------------------------------------------- settings

    def get_settings(self) -> dict[str, Any]:
        row = self.run_one("MATCH (s:Settings {id: 'global'}) RETURN s AS s")
        stored = dict(row["s"]) if row else {}
        return {key: stored.get(key, default) for key, default in DEFAULT_SETTINGS.items()}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = {k: v for k, v in changes.items() if k in DEFAULT_SETTINGS}
        if allowed:
            self.run("MATCH (s:Settings {id: 'global'}) SET s += $changes", changes=allowed)
        return self.get_settings()

    def get_meta(self, key: str) -> Any:
        """Free-form bookkeeping stored on the Settings node (e.g. which embedding model built the graph)."""
        row = self.run_one("MATCH (s:Settings {id: 'global'}) RETURN s[$key] AS value", key=key)
        return row["value"] if row else None

    def set_meta(self, key: str, value: Any) -> None:
        self.run("MATCH (s:Settings {id: 'global'}) SET s[$key] = $value", key=key, value=value)

    # ------------------------------------------------- graph version counter
    # The in-memory graph is rebuilt whenever this number changes.

    def graph_version(self) -> int:
        row = self.run_one("MATCH (s:Settings {id: 'global'}) RETURN coalesce(s.graph_version, 0) AS v")
        return int(row["v"]) if row else 0

    def bump_graph_version(self) -> int:
        row = self.run_one(
            "MATCH (s:Settings {id: 'global'}) SET s.graph_version = coalesce(s.graph_version, 0) + 1 RETURN s.graph_version AS v"
        )
        return int(row["v"]) if row else 0

    # -------------------------------------------------------------- stats

    def stats(self) -> dict[str, int]:
        row = self.run_one(
            """
            RETURN count { (:Source) } AS sources,
                   count { (:Passage) } AS passages,
                   count { (:Entity) } AS entities,
                   count { (:Fact) } AS facts,
                   count { ()-[:SYNONYM]->() } AS synonym_edges,
                   count { ()-[:MENTIONS]->() } AS mention_edges,
                   count { (:QuestionSet) } AS question_sets,
                   count { (:EvalRun) } AS eval_runs,
                   count { (:Changeset) } AS changesets
            """
        )
        return {k: int(v) for k, v in (row or {}).items()}
