"""
The store: everything hippo remembers lives in a graph database, and every
Cypher query lives in this package. There are two interchangeable backends:

    ladybug.py     LadybugDB, an embedded database in one file under data/ (the default:
                   nothing to install or run)
    base.py        Neo4j: connecting, running queries, constraints, settings, stats
    memory.py        sources, passages, entities, facts and the links between them
    code.py          symbols, data objects, commits and the typed edges between them
    evals.py         question sets, evaluation runs and their results
    changesets.py    saved graph edits and how they are applied
    users.py         roles, users and which role may see each source

`Store` combines the six Neo4j groups into one object; `LadybugStore` has the
very same methods. `open_store(config)` picks one from HIPPO_STORE, so the rest
of the app writes `store.add_passages(...)` or `store.create_run(...)` without
caring which database, or which file, the query is in.

The graph looks like this (with Neo4j, open http://localhost:7474 to browse it):

    (Source)<-[:FROM]-(Passage)-[:MENTIONS]->(Entity)
                        |
                        [:STATES]->(Fact)-[:SUBJECT]->(Entity)
                                        -[:OBJECT]->(Entity)
    (Entity|Symbol|DataObject)-[:SYNONYM {score}]->(...)   similar names, e.g. "usa" ~ "united states"
    (Entity|Passage|Symbol|DataObject)-[:TUNED {weight}]->(...)   a weight you pinned on purpose (from a changeset); wins over the computed one

    (Symbol|DataObject)-[:CODE_EDGE {kind, omega, provenance, extra}]->(Symbol|DataObject)  directed
    (Symbol|DataObject|Commit)-[:DEFINED_IN]->(Passage)    where the code node is written down
    (Passage)-[:REFERS_TO {omega, token}]->(Symbol|DataObject)   prose naming a symbol
    (Commit)-[:MODIFIES {omega, hunk}]->(Symbol)           (Commit)-[:PRECEDES]->(Commit)  first-parent

    (QuestionSet)-[:HAS]->(Question)           evaluation questions, optionally [:ABOUT]->(Source)
    (EvalRun)-[:OF]->(QuestionSet)
    (EvalRun)-[:RESULT]->(EvalResult)-[:FOR]->(Question)
    (Changeset)                                a saved set of edits, applied or still a draft
    (User)-[:HAS_ROLE]->(Role)                 who may sign in, and their place on the access ladder
    (Source {access_role_id, min_rank, owner_id})   the lowest role that may see a source (see hippo/access.py)
    (Settings {id: 'global'})                  retrieval knobs + the graph version counter
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import Neo4jBase
from .changesets import ChangesetQueries
from .code import CodeQueries
from .evals import EvalQueries
from .generations import GenerationQueries
from .knowledge import KnowledgeQueries
from .ladybug import LadybugStore, StoreLockedError
from .memory import MemoryQueries
from .snapshots import SnapshotQueries
from .users import UserQueries

if TYPE_CHECKING:
    from ..config import Config

log = logging.getLogger(__name__)


class Store(
    KnowledgeQueries,
    GenerationQueries,
    SnapshotQueries,
    MemoryQueries,
    CodeQueries,
    EvalQueries,
    ChangesetQueries,
    UserQueries,
    Neo4jBase,
):
    """All of hippo's Neo4j queries behind one object."""

    def on_first_connection(self) -> None:
        """Runs once, the first time Neo4j answers: create the schema, then tidy up after any crash."""
        self.ensure_schema()
        self.ensure_roles()
        interrupted = self.mark_interrupted_jobs()
        if interrupted:
            log.warning("%d job(s) were interrupted by the last shutdown and are marked failed", interrupted)


AnyStore = Store | LadybugStore
"""What the rest of the app is handed: either backend (or, in tests, the in-memory fake)."""


def open_store(config: Config) -> AnyStore:
    """The store HIPPO_STORE asks for. Neo4j is connected lazily; LadybugDB opens (and locks) its file now."""
    if config.store_backend == "neo4j":
        return Store(config.neo4j_uri, config.neo4j_user, config.neo4j_password)
    return LadybugStore(config.database_path)


__all__ = ["AnyStore", "LadybugStore", "Store", "StoreLockedError", "open_store"]
