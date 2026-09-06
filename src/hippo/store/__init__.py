"""
The store: everything hippo remembers lives in Neo4j, and every Cypher query
lives in this package.

    base.py        connecting, running queries, constraints, settings, stats
    memory.py      sources, passages, entities, facts and the links between them
    evals.py       question sets, evaluation runs and their results
    changesets.py  saved graph edits and how they are applied

`Store` simply combines those four groups of queries into one object, so the
rest of the app writes `store.add_passages(...)` or `store.create_run(...)`
without caring which file the query is in.

The graph looks like this (open http://localhost:7474 to browse it):

    (Source)<-[:FROM]-(Passage)-[:MENTIONS]->(Entity)
                        |
                        [:STATES]->(Fact)-[:SUBJECT]->(Entity)
                                        -[:OBJECT]->(Entity)
    (Entity)-[:SYNONYM {score}]->(Entity)      similar names, e.g. "usa" ~ "united states"
    (Entity)-[:TUNED {weight}]->(Entity)       a weight you changed on purpose (from a changeset)

    (QuestionSet)-[:HAS]->(Question)           evaluation questions, optionally [:ABOUT]->(Source)
    (EvalRun)-[:OF]->(QuestionSet)
    (EvalRun)-[:RESULT]->(EvalResult)-[:FOR]->(Question)
    (Changeset)                                a saved set of edits, applied or still a draft
    (Settings {id: 'global'})                  retrieval knobs + the graph version counter
"""

import logging

from .base import Neo4jBase
from .changesets import ChangesetQueries
from .evals import EvalQueries
from .memory import MemoryQueries

log = logging.getLogger(__name__)


class Store(MemoryQueries, EvalQueries, ChangesetQueries, Neo4jBase):
    """All of hippo's Neo4j queries behind one object."""

    def on_first_connection(self) -> None:
        """Runs once, the first time Neo4j answers: create the schema, then tidy up after any crash."""
        self.ensure_schema()
        interrupted = self.mark_interrupted_jobs()
        if interrupted:
            log.warning("%d job(s) were interrupted by the last shutdown and are marked failed", interrupted)


__all__ = ["Store"]
