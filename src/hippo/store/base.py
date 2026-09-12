"""Connecting to Neo4j, running queries, and the handful of global records (settings, stats)."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .authorization import metadata_mutation

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
    # The code graph. Every one of these is inert on a memory with no code source indexed, and
    # `code_structural_scale = 0` (plus zero seed weights) turns code back off on one that has.
    "code_seed_weight": 1.0,  # anchor seed mass; 0 = ignore symbols named in the question
    "code_structural_scale": 1.0,  # multiplier on every code-touching weight term
    "code_theta": 0.5,  # minimum omega for the path tools and the answer block (never PPR)
    "code_dense_seeds": 5,  # code passages similar to the question that also seed their symbol
    "code_triples_chars": 1500,  # size cap of the Code graph block
    "code_community_boost": 0.0,  # post-PPR bonus for passages in a seed's community
    "code_select": True,  # the LLM keep/drop/expand pass, when code seeds fired
    "code_expand_max": 10,  # neighbours fetched per "expand"
    "code_history_depth": 200,  # first-parent commits read per repo source; 0 disables history
    "code_git_timeout_s": 10,  # per-commit `git show` budget
    "code_history_total_s": 120,  # whole-pass budget for reading history
}

# Type and allowed range of every setting: (type, lowest, highest). None means "no bound".
SETTING_RULES: dict[str, tuple[type, float | None, float | None]] = {
    "linking_top_k": (int, 0, 100),
    "passage_node_weight": (float, 0.0, 10.0),
    "damping": (float, 0.0, 1.0),
    "node_specificity": (bool, None, None),
    "synonymy_threshold": (float, 0.0, 1.0),
    "retrieval_top_k": (int, 1, 5000),
    "qa_top_k": (int, 1, 50),
    "code_seed_weight": (float, 0.0, 10.0),
    # Capped at 3.0 so a code edge can at most *tie* three facts, never outrank them: that is what
    # keeps "prose behaves as it does today" literally true rather than true-below-some-value.
    "code_structural_scale": (float, 0.0, 3.0),
    "code_theta": (float, 0.0, 1.0),
    "code_dense_seeds": (int, 0, 20),
    "code_triples_chars": (int, 0, 8000),
    "code_community_boost": (float, 0.0, 1.0),
    "code_select": (bool, None, None),
    "code_expand_max": (int, 0, 20),
    "code_history_depth": (int, 0, 2000),
    "code_git_timeout_s": (int, 1, 120),
    "code_history_total_s": (int, 10, 3600),
}


def validate_settings(changes: dict[str, Any]) -> dict[str, Any]:
    """
    Check and coerce a dict of settings. Unknown keys, wrong types and out-of-range
    values raise ValueError with a message a person can act on. Every entry point
    (API, form, MCP, simulations) goes through this, so a typo can never poison the
    stored settings and break every later search.
    """
    unknown = set(changes) - set(SETTING_RULES)
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    clean: dict[str, Any] = {}
    for key, value in changes.items():
        kind, low, high = SETTING_RULES[key]
        if kind is bool:
            if isinstance(value, str):
                value = value.strip().lower() in ("1", "true", "yes", "on")
            clean[key] = bool(value)
            continue
        if isinstance(value, bool):
            raise ValueError(f"{key} must be a number, not true/false")
        try:
            number = kind(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a {kind.__name__}, got {value!r}") from exc
        if kind is int and float(value) != number:
            raise ValueError(f"{key} must be a whole number, got {value!r}")
        if (low is not None and number < low) or (high is not None and number > high):
            raise ValueError(f"{key} must be between {low} and {high}, got {value!r}")
        clean[key] = number
    return clean


CONSTRAINTS = [
    "CREATE CONSTRAINT source_id IF NOT EXISTS FOR (n:Source) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT passage_id IF NOT EXISTS FOR (n:Passage) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (n:Fact) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT question_set_id IF NOT EXISTS FOR (n:QuestionSet) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT question_id IF NOT EXISTS FOR (n:Question) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT eval_run_id IF NOT EXISTS FOR (n:EvalRun) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT eval_result_id IF NOT EXISTS FOR (n:EvalResult) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT symbol_id IF NOT EXISTS FOR (n:Symbol) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT data_object_id IF NOT EXISTS FOR (n:DataObject) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT commit_id IF NOT EXISTS FOR (n:Commit) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX symbol_source IF NOT EXISTS FOR (n:Symbol) ON (n.source_id)",
    "CREATE INDEX data_object_source IF NOT EXISTS FOR (n:DataObject) ON (n.source_id)",
    "CREATE INDEX commit_source IF NOT EXISTS FOR (n:Commit) ON (n.source_id)",
    "CREATE CONSTRAINT changeset_id IF NOT EXISTS FOR (n:Changeset) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT settings_id IF NOT EXISTS FOR (n:Settings) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT role_id IF NOT EXISTS FOR (n:Role) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (n:User) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT user_username IF NOT EXISTS FOR (n:User) REQUIRE n.username IS UNIQUE",
    "CREATE CONSTRAINT user_token IF NOT EXISTS FOR (n:User) REQUIRE n.token IS UNIQUE",
    # A TEXT index (not the default RANGE one) is what `CONTAINS` searches can use.
    "CREATE TEXT INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
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
    knowledge_backend = "neo4j"

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        try:
            from neo4j import GraphDatabase  # optional dependency: `pip install 'hippo[neo4j]'`
        except ImportError as exc:  # pragma: no cover - depends on what is installed
            raise RuntimeError(
                "HIPPO_STORE=neo4j needs the neo4j driver: pip install 'hippo[neo4j]' (or pip install neo4j)"
            ) from exc
        # Short timeouts: when Neo4j is unreachable a page should say so in seconds, not hang for a minute.
        # Notifications off: on a fresh database Neo4j warns that e.g. `owner_id` "does not exist" for
        # every query that mentions a property no node has yet, which would flood the log on each poll.
        self.driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=5.0,
            connection_acquisition_timeout=10.0,
            notifications_min_severity="OFF",
        )
        self.database = database
        self._lock = threading.RLock()
        self._transaction = None
        self._transaction_owner = None
        self._schema_checked = False
        self._migration_blocked = False
        self._migrating = False
        self._bootstrapped = False  # schema created and interrupted jobs cleaned, once per process

    def close(self) -> None:
        self.driver.close()

    # ------------------------------------------------------------ running

    def run(self, query: str, **params: Any) -> list[dict[str, Any]]:
        """Run one Cypher query in its own transaction and return the rows as dicts."""
        with self._lock:
            if not self._schema_checked and not self._migrating:
                self.ensure_schema()
            if self._migration_blocked and not self._migrating:
                raise RuntimeError("Store migration is incomplete; application access is disabled")
            if self._transaction is not None:
                if self._transaction_failed:
                    raise RuntimeError("Transaction failed; roll back before issuing another statement")
                try:
                    return [record.data() for record in self._transaction.run(query, params)]
                except BaseException:
                    self._transaction_failed = True
                    raise
            result = self.driver.execute_query(query, parameters_=params, database_=self.database)
            return [record.data() for record in result.records]

    def run_one(self, query: str, **params: Any) -> dict[str, Any] | None:
        rows = self.run(query, **params)
        return rows[0] if rows else None

    def ping(self) -> bool:
        """
        Is Neo4j reachable? The first time it is, the schema is created and jobs interrupted
        by the last shutdown are marked failed. That makes startup order irrelevant: Neo4j may
        come up minutes after the app and everything still gets set up on the first page load.
        """
        try:
            self.driver.verify_connectivity()
        except Exception as exc:  # noqa: BLE001 - any driver error means "not reachable"
            log.warning("Neo4j not reachable: %s", exc)
            return False
        if not self._bootstrapped:
            try:
                self.on_first_connection()
                self._bootstrapped = True
            except Exception as exc:  # noqa: BLE001 - try again on the next ping
                log.warning("Neo4j is up but bootstrapping failed, will retry: %s", exc)
                return False
        return True

    def on_first_connection(self) -> None:
        """What to do once Neo4j is reachable. Store extends this (see store/__init__.py)."""
        self.ensure_schema()

    # ------------------------------------------------------------- schema

    def in_ambient_transaction(self) -> bool:
        """True only when the calling thread has an open transaction on this store."""
        # Deliberately lock-free: the holder keeps `_lock` for its whole transaction body, so
        # taking it here would block every other thread instead of answering them.
        return self._transaction_owner == threading.get_ident()

    @contextmanager
    def transaction(self):
        with self._lock:
            if not self._schema_checked and not self._migrating:
                self.ensure_schema()
            if self._migration_blocked and not self._migrating:
                raise RuntimeError("Store migration is incomplete; transaction refused")
            if self._transaction is not None:
                try:
                    yield self
                except BaseException:
                    self._transaction_failed = True
                    raise
                return
            with self.driver.session(database=self.database) as session:
                with session.begin_transaction() as transaction:
                    self._transaction = transaction
                    self._transaction_failed = False
                    self._transaction_owner = threading.get_ident()
                    try:
                        yield self
                        if self._transaction_failed:
                            raise RuntimeError("Nested transaction failed; outer transaction must roll back")
                        transaction.commit()
                    except BaseException:
                        try:
                            transaction.rollback()
                        except Exception:
                            log.error("Neo4j rollback failed while handling a transaction error")
                        raise
                    finally:
                        self._transaction = None
                        self._transaction_failed = False
                        self._transaction_owner = None

    def ensure_schema(self) -> None:
        from .migrations import migrate_store

        migrate_store(self)

    def _ensure_legacy_schema(self) -> None:
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
        """Change some settings. Raises ValueError for unknown keys, wrong types or out-of-range values."""
        clean = validate_settings(changes)
        if clean:
            self.run(
                "MERGE (s:Settings {id: 'global'}) ON CREATE SET s += $defaults, s.graph_version = 0 SET s += $changes",
                defaults=DEFAULT_SETTINGS,
                changes=clean,
            )
        return self.get_settings()

    def get_meta(self, key: str) -> Any:
        """Free-form bookkeeping stored on the Settings node (e.g. which embedding model built the graph)."""
        row = self.run_one("MATCH (s:Settings {id: 'global'}) RETURN s[$key] AS value", key=key)
        return row["value"] if row else None

    @metadata_mutation
    def set_meta(self, key: str, value: Any) -> None:
        # `SET s += $map` works on every Neo4j 5.x (the dynamic `s[$key] = ...` form needs 5.24+).
        self.run(
            "MERGE (s:Settings {id: 'global'}) ON CREATE SET s += $defaults, s.graph_version = 0 SET s += $change",
            defaults=DEFAULT_SETTINGS,
            change={key: value},
        )

    # ------------------------------------------------- graph version counter
    # The in-memory graph is rebuilt whenever this number changes.

    def graph_version(self) -> int:
        row = self.run_one("MATCH (s:Settings {id: 'global'}) RETURN coalesce(s.graph_version, 0) AS v")
        return int(row["v"]) if row else 0

    def bump_graph_version(self) -> int:
        # MERGE rather than MATCH so the counter can never be silently missing (e.g. the app
        # started before Neo4j did): a missing Settings node is created on the spot.
        row = self.run_one(
            """
            MERGE (s:Settings {id: 'global'}) ON CREATE SET s += $defaults, s.graph_version = 0
            SET s.graph_version = coalesce(s.graph_version, 0) + 1
            RETURN s.graph_version AS v
            """,
            defaults=DEFAULT_SETTINGS,
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
                   count { (:Symbol) } AS symbols,
                   count { (:DataObject) } AS data_objects,
                   count { ()-[:CODE_EDGE]->() } AS code_edges,
                   count { (:Commit) } AS commits,
                   count { ()-[:SYNONYM]->() } AS synonym_edges,
                   count { ()-[:MENTIONS]->() } AS mention_edges,
                   count { (:QuestionSet) } AS question_sets,
                   count { (:EvalRun) } AS eval_runs,
                   count { (:Changeset) } AS changesets,
                   count { (:User) } AS users,
                   count { (:Role) } AS roles
            """
        )
        return {k: int(v) for k, v in (row or {}).items()}
