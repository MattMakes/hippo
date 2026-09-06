"""
Queries for changesets: edits to the graph you decided on while analysing a question.

A changeset is a list of small operations, stored as JSON until you apply it:

    {"op": "set_setting",    "name": "damping", "value": 0.7}
    {"op": "set_edge_weight","a": "<node id>", "b": "<node id>", "weight": 2.0}   (weight 0 removes the edge)
    {"op": "add_synonym",    "a": "<entity id>", "b": "<entity id>", "score": 0.9}
    {"op": "set_node_boost", "entity_id": "<entity id>", "boost": 1.5}

Applying writes them to Neo4j: settings onto the Settings node, boosts onto
Entity nodes, synonyms as SYNONYM edges, and weight changes as TUNED edges
(which win over the computed weight when the graph is loaded).
"""

from __future__ import annotations

import json
from typing import Any

from .base import Neo4jBase, new_id, now_iso


class ChangesetQueries(Neo4jBase):
    def create_changeset(
        self, name: str, ops: list[dict[str, Any]], from_result_id: str | None = None, note: str = ""
    ) -> str:
        changeset_id = new_id()
        self.run(
            """
            CREATE (c:Changeset {id: $id, name: $name, note: $note, status: 'draft', ops_json: $ops_json,
                                 created_at: $now, applied_at: null, from_result_id: $from_result_id})
            """,
            id=changeset_id,
            name=name,
            note=note,
            ops_json=json.dumps(ops),
            now=now_iso(),
            from_result_id=from_result_id,
        )
        return changeset_id

    def get_changeset(self, changeset_id: str) -> dict[str, Any] | None:
        row = self.run_one("MATCH (c:Changeset {id: $id}) RETURN c AS c", id=changeset_id)
        return _changeset_row(row) if row else None

    def list_changesets(self) -> list[dict[str, Any]]:
        rows = self.run("MATCH (c:Changeset) RETURN c AS c ORDER BY c.created_at DESC")
        return [_changeset_row(r) for r in rows]

    def delete_changeset(self, changeset_id: str) -> None:
        self.run("MATCH (c:Changeset {id: $id}) DELETE c", id=changeset_id)

    def mark_applied(self, changeset_id: str) -> None:
        self.run(
            "MATCH (c:Changeset {id: $id}) SET c.status = 'applied', c.applied_at = $now",
            id=changeset_id,
            now=now_iso(),
        )

    # ---------------------------------------------- the individual edits

    def set_node_boost(self, entity_id: str, boost: float) -> None:
        self.run("MATCH (e:Entity {id: $id}) SET e.boost = $boost", id=entity_id, boost=float(boost))

    def set_edge_weight(self, a: str, b: str, weight: float) -> None:
        """Pin the weight of the edge between two nodes (entities or passages). 0 removes the edge."""
        lo, hi = min(a, b), max(a, b)
        self.run(
            """
            MATCH (a:Entity|Passage {id: $a}), (b:Entity|Passage {id: $b})
            MERGE (a)-[t:TUNED]->(b)
            SET t.weight = $weight, t.updated_at = $now
            """,
            a=lo,
            b=hi,
            weight=float(weight),
            now=now_iso(),
        )

    def clear_edge_weight(self, a: str, b: str) -> None:
        lo, hi = min(a, b), max(a, b)
        self.run("MATCH (a {id: $a})-[t:TUNED]->(b {id: $b}) DELETE t", a=lo, b=hi)


def _changeset_row(row: dict[str, Any]) -> dict[str, Any]:
    changeset = dict(row["c"])
    changeset["ops"] = json.loads(changeset.pop("ops_json", None) or "[]")
    return changeset
