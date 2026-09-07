"""
The store: everything hippo remembers lives in Neo4j, and every Cypher query
lives in this package.

    base.py        connecting, running queries, constraints, settings, stats
    memory.py      sources, passages, entities, facts and the links between them
    evals.py       question sets, evaluation runs and their results
    changesets.py  saved graph edits and how they are applied
    users.py       roles, users and which role may see each source

`Store` simply combines those four groups of queries into one object, so the
rest of the app writes `store.add_passages(...)` or `store.create_run(...)`
without caring which file the query is in.

The graph looks like this (open http://localhost:7474 to browse it):

    (Source)<-[:FROM]-(Passage)-[:MENTIONS]->(Entity)
                        |
                        [:STATES]->(Fact)-[:SUBJECT]->(Entity)
                                        -[:OBJECT]->(Entity)
    (Entity)-[:SYNONYM {score}]->(Entity)      similar names, e.g. "usa" ~ "united states"
    (Entity|Passage)-[:TUNED {weight}]->(Entity|Passage)   a weight you pinned on purpose (from a changeset); wins over the computed one

    (QuestionSet)-[:HAS]->(Question)           evaluation questions, optionally [:ABOUT]->(Source)
    (EvalRun)-[:OF]->(QuestionSet)
    (EvalRun)-[:RESULT]->(EvalResult)-[:FOR]->(Question)
    (Changeset)                                a saved set of edits, applied or still a draft
    (User)-[:HAS_ROLE]->(Role)                 who may sign in, and their place on the access ladder
    (Source {access_role_id, min_rank, owner_id})   the lowest role that may see a source (see hippo/access.py)
    (Settings {id: 'global'})                  retrieval knobs + the graph version counter
"""

import logging

from .base import Neo4jBase
from .changesets import ChangesetQueries
from .evals import EvalQueries
from .memory import MemoryQueries
from .users import UserQueries

log = logging.getLogger(__name__)


class Store(MemoryQueries, EvalQueries, ChangesetQueries, UserQueries, Neo4jBase):
    """All of hippo's Neo4j queries behind one object."""

    def on_first_connection(self) -> None:
        """Runs once, the first time Neo4j answers: create the schema, then tidy up after any crash."""
        self.ensure_schema()
        self.ensure_roles()
        interrupted = self.mark_interrupted_jobs()
        if interrupted:
            log.warning("%d job(s) were interrupted by the last shutdown and are marked failed", interrupted)


__all__ = ["Store"]
