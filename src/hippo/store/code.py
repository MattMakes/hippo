"""
The code graph: symbols, data objects, commits and the typed edges between them.

This file holds three things:

* the vocabulary every backend shares (`SYMBOL_KINDS`, `CODE_EDGE_KINDS`, `CODE_EDGE_PAIRS`, ...),
* the row shapers that give a stored node the same keys on every backend (`_symbol_row` and
  friends, exactly like `_passage_row` in store/memory.py), and
* `CodeQueries`, the **Neo4j** half of the code graph. `LadybugStore` and the test `FakeStore`
  implement the very same method names and row shapes themselves, because `store/base.py` is the
  Neo4j backend's base class rather than a shared interface (R1.1). `tests/unit/test_store_code.py`
  runs against all three, and a parity test compares the three files' method names.

Two rules the writers here follow, and the other two backends follow with them:

1. **A node's label comes from its id prefix, never from a query** (`hipporag.text.label_of`, S2.2).
   Ids are prefixed md5s (`symbol-`, `data-`, `commit-`, `entity-`, `passage-`), so the label is a
   pure function of the id and each write can be bound to one concrete label pair - which is what
   LadybugDB requires and what stops the `:A:B` (LadybugDB) versus `:A|B` (Neo4j) dialect trap.
   An id whose prefix is unknown, or whose label a relationship does not accept, is skipped: the
   same thing Neo4j's `MATCH` does when it finds nothing.
2. **Direction is stored, not implied.** `CODE_EDGE`, `MODIFIES`, `PRECEDES`, `DEFINED_IN` and
   `REFERS_TO` are all directed; the undirected igraph that PPR runs on is built later, in
   `hipporag/graph_index.py`.
"""

from __future__ import annotations

import json
from typing import Any

from ..access import ACCESS_WHERE, Access, access_params
from ..hipporag.text import label_of, split_identifier
from .base import Neo4jBase, now_iso, with_defaults

CODE_BATCH = 5000  # rows per UNWIND write (measured in research/S0-spikes.md spike 3)

SYMBOL_KINDS = ("module", "class", "function", "method")
DATA_KINDS = ("table", "column", "collection", "label", "rel_type")

CODE_EDGE_KINDS = (
    "CONTAINS",
    "IMPORTS",
    "INHERITS",
    "OVERRIDES",
    "INVOKES",
    "RAISES",
    "CATCHES",
    "TESTED_BY",
    "READS",
    "WRITES",
)

# Which incoming edges damp a code node's seed weight (S2.4): being called or read from makes a
# symbol less specific. MODIFIES is deliberately absent - a function touched by 150 of 200 commits
# would otherwise be crushed.
SPECIFICITY_KINDS = ("INVOKES", "READS", "WRITES")

# The concrete label pairs a CODE_EDGE may join. `(DataObject, DataObject)` is table -> column.
CODE_EDGE_PAIRS = {("Symbol", "Symbol"), ("Symbol", "DataObject"), ("DataObject", "DataObject")}

# Which labels each widened relationship accepts. SYNONYM is the 9 ordered pairs of the named
# kinds; TUNED is the 16 ordered pairs of everything a user can pin a weight between (no Commit);
# `boost` is a column on the three named kinds only.
SYNONYM_LABELS = ("Entity", "Symbol", "DataObject")
TUNED_LABELS = ("Entity", "Passage", "Symbol", "DataObject")
BOOSTABLE_LABELS = ("Entity", "Symbol", "DataObject")
CODE_NODE_LABELS = ("Symbol", "DataObject", "Commit")
DEFINABLE_LABELS = ("Symbol", "DataObject", "Commit")  # what may point at a Passage with DEFINED_IN
REFERABLE_LABELS = ("Symbol", "DataObject")  # what a passage may REFERS_TO


def ordered_pairs(labels: tuple[str, ...]) -> list[tuple[str, str]]:
    """Every ordered (from, to) pair of `labels` - the endpoint list a widened rel table declares."""
    return [(a, b) for a in labels for b in labels]


def node_label(node_id: Any, allowed: tuple[str, ...]) -> str | None:
    """
    The concrete label to bind this id to, or None when it is not a node `allowed` accepts.

    None means "write nothing", which is what Neo4j's `MATCH` already does for an id no node has.
    Without the `allowed` check a commit id would reach `MERGE (a)-[:TUNED]->(b)`, whose table has
    no Commit endpoint - a binder error on LadybugDB rather than a quiet no-op.
    """
    try:
        label = label_of(node_id)
    except ValueError:
        return None
    return label if label in allowed else None


def check_edge_kind(kind: Any) -> str:
    """A CODE_EDGE kind, or ValueError. Unknown kinds are a caller bug, not data to store."""
    if kind not in CODE_EDGE_KINDS:
        raise ValueError(f"unknown code edge kind {kind!r}; expected one of {list(CODE_EDGE_KINDS)}")
    return str(kind)


# ------------------------------------------------------------- write rows
# One normaliser per node kind, shared by all three backends: plain Python types in, plain Python
# types out. LadybugDB wraps the free-text fields in `text()` afterwards; the others store them
# as they are.


def symbol_write_row(row: dict[str, Any]) -> dict[str, Any]:
    """`{id, source_id, name, qualname, kind, lang, path, line_start, line_end, signature, doc,
    is_test, raises, embedding}` -> the stored shape, with `name_tokens` filled in here."""
    name = str(row.get("name") or "")
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "name": name,
        "qualname": str(row.get("qualname") or ""),
        "kind": str(row.get("kind") or ""),
        "lang": str(row.get("lang") or ""),
        "path": str(row.get("path") or ""),
        "line_start": int(row.get("line_start") or 0),
        "line_end": int(row.get("line_end") or 0),
        "signature": str(row.get("signature") or ""),
        "doc": str(row.get("doc") or ""),
        "is_test": bool(row.get("is_test")),
        "raises": [str(x) for x in (row.get("raises") or [])],
        "name_tokens": split_identifier(name),
        "embedding": [float(x) for x in (row.get("embedding") or [])],
    }


def data_object_write_row(row: dict[str, Any]) -> dict[str, Any]:
    """`{id, source_id, name, qualname, kind, dialect, embedding}` -> the stored shape."""
    name = str(row.get("name") or "")
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "name": name,
        "qualname": str(row.get("qualname") or ""),
        "kind": str(row.get("kind") or ""),
        "dialect": str(row.get("dialect") or ""),
        "name_tokens": split_identifier(name),
        "embedding": [float(x) for x in (row.get("embedding") or [])],
    }


def commit_write_row(row: dict[str, Any]) -> dict[str, Any]:
    """`{id, source_id, sha, author, date, message, ordinal}` -> the stored shape."""
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "sha": str(row.get("sha") or ""),
        "author": str(row.get("author") or ""),
        "date": str(row.get("date") or ""),
        "message": str(row.get("message") or ""),
        "ordinal": int(row.get("ordinal") or 0),
    }


def code_edge_write_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    `{a, b, kind, omega, provenance, extra}` rows, deduped to the best omega per `(a, b, kind)`.

    Self-loops and endpoint pairs `CODE_EDGE` does not accept are dropped. The dedupe happens here,
    in Python, because a `NOT EXISTS` guard under `UNWIND` cannot see rows created by its own
    statement - and because the guarded write is create-if-absent, so a second row for the same
    triple would otherwise keep the *first* omega rather than the best one.
    """
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        kind = check_edge_kind(row.get("kind"))
        a, b = row["a"], row["b"]
        if a == b:
            continue
        label_a, label_b = node_label(a, ("Symbol", "DataObject")), node_label(b, ("Symbol", "DataObject"))
        if label_a is None or label_b is None or (label_a, label_b) not in CODE_EDGE_PAIRS:
            continue
        shaped = {
            "a": a,
            "b": b,
            "kind": kind,
            "omega": float(row.get("omega") or 0.0),
            "provenance": str(row.get("provenance") or ""),
            "extra": json.dumps(row.get("extra") or {}, sort_keys=True),
            "label_a": label_a,
            "label_b": label_b,
        }
        current = best.get((a, b, kind))
        if current is None or current["omega"] < shaped["omega"]:
            best[(a, b, kind)] = shaped
    return list(best.values())


def modifies_write_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`{commit_id, symbol_id, omega, hunk}` rows, one per `(commit, symbol)`, best omega kept."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        commit_id, symbol_id = row["commit_id"], row["symbol_id"]
        if node_label(commit_id, ("Commit",)) is None or node_label(symbol_id, ("Symbol",)) is None:
            continue
        shaped = {
            "commit_id": commit_id,
            "symbol_id": symbol_id,
            "omega": float(row.get("omega") if row.get("omega") is not None else 1.0),
            "hunk": json.dumps(row.get("hunk") or {}, sort_keys=True),
        }
        current = best.get((commit_id, symbol_id))
        if current is None or current["omega"] < shaped["omega"]:
            best[(commit_id, symbol_id)] = shaped
    return list(best.values())


def refers_to_write_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`{passage_id, node_id, omega, token}` rows, one per pair, best omega kept."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        passage_id, node_id = row["passage_id"], row["node_id"]
        label = node_label(node_id, REFERABLE_LABELS)
        if label is None or node_label(passage_id, ("Passage",)) is None:
            continue
        shaped = {
            "passage_id": passage_id,
            "node_id": node_id,
            "omega": float(row.get("omega") or 0.0),
            "token": str(row.get("token") or ""),
            "label": label,
        }
        current = best.get((passage_id, node_id))
        if current is None or current["omega"] < shaped["omega"]:
            best[(passage_id, node_id)] = shaped
    return list(best.values())


# ------------------------------------------------------------- row shaping
# Neo4j drops null properties, LadybugDB hands back None for a column never written, and the
# FakeStore has whatever the writer put in its dict - so every read goes through one of these.

SYMBOL_DEFAULTS: dict[str, Any] = {
    "source_id": "",
    "source_name": "",
    "name": "",
    "qualname": "",
    "kind": "",
    "lang": "",
    "path": "",
    "line_start": 0,
    "line_end": 0,
    "signature": "",
    "doc": "",
    "is_test": False,
    "raises": [],
    "community": None,
    "name_tokens": [],
    "boost": 1.0,
    "created_at": "",
    "passage_ids": [],
    "in_degree": 0,
}

DATA_OBJECT_DEFAULTS: dict[str, Any] = {
    "source_id": "",
    "source_name": "",
    "name": "",
    "qualname": "",
    "kind": "",
    "dialect": "",
    "name_tokens": [],
    "boost": 1.0,
    "created_at": "",
    "passage_ids": [],
    "in_degree": 0,
}

COMMIT_DEFAULTS: dict[str, Any] = {
    "source_id": "",
    "source_name": "",
    "sha": "",
    "author": "",
    "date": "",
    "message": "",
    "ordinal": 0,
    "created_at": "",
    "passage_ids": [],
}


def _shape(row: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    shaped = with_defaults({k: v for k, v in row.items() if v is not None}, defaults)
    for key in ("line_start", "line_end", "ordinal", "in_degree"):
        if key in shaped:
            shaped[key] = int(shaped[key] or 0)
    if "boost" in shaped:
        shaped["boost"] = float(shaped["boost"])
    if "community" in shaped and shaped["community"] is not None:
        shaped["community"] = int(shaped["community"])
    for key in ("raises", "name_tokens", "passage_ids"):
        if key in shaped:
            shaped[key] = list(shaped[key] or [])
    return shaped


def _symbol_row(row: dict[str, Any]) -> dict[str, Any]:
    return _shape(row, SYMBOL_DEFAULTS)


def _data_object_row(row: dict[str, Any]) -> dict[str, Any]:
    return _shape(row, DATA_OBJECT_DEFAULTS)


def _commit_row(row: dict[str, Any]) -> dict[str, Any]:
    return _shape(row, COMMIT_DEFAULTS)


def _json_field(value: Any) -> dict[str, Any]:
    """`extra`/`hunk` come back as JSON text (or nothing at all); callers always get a dict."""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _batches(rows: list[Any], size: int = CODE_BATCH):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def grouped_by_labels(
    best: dict[tuple[str, str], float], allowed: tuple[str, ...]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Canonical (a, b) -> score pairs, grouped by the concrete label pair they write to (S2.2)."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for (a, b), score in best.items():
        label_a, label_b = node_label(a, allowed), node_label(b, allowed)
        if label_a is None or label_b is None:
            continue
        grouped.setdefault((label_a, label_b), []).append({"a": a, "b": b, "score": score})
    return grouped


def _by_label(rows: list[dict[str, Any]], key: str, allowed: tuple[str, ...]) -> dict[str, list[dict]]:
    """Group rows by the concrete label of `row[key]`, dropping ids no `allowed` label covers."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = node_label(row[key], allowed)
        if label is not None:
            grouped.setdefault(label, []).append(row)
    return grouped


class CodeQueries(Neo4jBase):
    """The Neo4j code graph. `LadybugStore` and `FakeStore` mirror every method name and row shape."""

    # ============================================================== writing

    def add_symbols(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, source_id, name, qualname, kind, lang, path, line_start, line_end, signature,
        doc, is_test, raises, embedding}. Re-adding updates in place; an unknown source is skipped."""
        shaped = [symbol_write_row(r) for r in rows]
        for batch in _batches(shaped):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (src:Source {id: row.source_id})
                MERGE (n:Symbol {id: row.id})
                ON CREATE SET n.created_at = $now
                SET n.source_id = row.source_id, n.name = row.name, n.qualname = row.qualname,
                    n.kind = row.kind, n.lang = row.lang, n.path = row.path,
                    n.line_start = row.line_start, n.line_end = row.line_end,
                    n.signature = row.signature, n.doc = row.doc, n.is_test = row.is_test,
                    n.raises = row.raises, n.name_tokens = row.name_tokens
                WITH n, row WHERE size(row.embedding) > 0
                CALL db.create.setNodeVectorProperty(n, 'embedding', row.embedding)
                """,
                rows=batch,
                now=now_iso(),
            )

    def add_data_objects(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, source_id, name, qualname, kind, dialect, embedding}."""
        shaped = [data_object_write_row(r) for r in rows]
        for batch in _batches(shaped):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (src:Source {id: row.source_id})
                MERGE (n:DataObject {id: row.id})
                ON CREATE SET n.created_at = $now
                SET n.source_id = row.source_id, n.name = row.name, n.qualname = row.qualname,
                    n.kind = row.kind, n.dialect = row.dialect, n.name_tokens = row.name_tokens
                WITH n, row WHERE size(row.embedding) > 0
                CALL db.create.setNodeVectorProperty(n, 'embedding', row.embedding)
                """,
                rows=batch,
                now=now_iso(),
            )

    def add_commits(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, source_id, sha, author, date, message, ordinal}."""
        shaped = [commit_write_row(r) for r in rows]
        for batch in _batches(shaped):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (src:Source {id: row.source_id})
                MERGE (n:Commit {id: row.id})
                ON CREATE SET n.created_at = $now
                SET n.source_id = row.source_id, n.sha = row.sha, n.author = row.author,
                    n.date = row.date, n.message = row.message, n.ordinal = row.ordinal
                """,
                rows=batch,
                now=now_iso(),
            )

    def add_code_edges(self, rows: list[dict[str, Any]]) -> None:
        """rows: {a, b, kind, omega, provenance, extra}. Directed, one per (a, b, kind); re-adding
        raises omega and never lowers it. Unknown kinds raise; self-loops and bad pairs are dropped."""
        shaped = code_edge_write_rows(rows)
        for (label_a, label_b), group in _group_pairs(shaped).items():
            for batch in _batches(group):
                # Two statements, the same shape LadybugDB needs: raise omega on what is there,
                # then create what is missing (see the module docstring).
                self.run(
                    f"""
                    UNWIND $rows AS row
                    MATCH (a:{label_a} {{id: row.a}})-[r:CODE_EDGE]->(b:{label_b} {{id: row.b}})
                    WHERE r.kind = row.kind AND r.omega < row.omega
                    SET r.omega = row.omega, r.provenance = row.provenance, r.extra = row.extra
                    """,
                    rows=batch,
                )
                self.run(
                    f"""
                    UNWIND $rows AS row
                    MATCH (a:{label_a} {{id: row.a}}), (b:{label_b} {{id: row.b}})
                    WHERE NOT EXISTS {{ MATCH (a)-[r:CODE_EDGE]->(b) WHERE r.kind = row.kind }}
                    CREATE (a)-[:CODE_EDGE {{kind: row.kind, omega: row.omega,
                                             provenance: row.provenance, extra: row.extra}}]->(b)
                    """,
                    rows=batch,
                )

    def link_definitions(self, pairs: list[tuple[str, str]]) -> None:
        """(node_id, passage_id) -> DEFINED_IN. The node may be a symbol, data object or commit."""
        rows = [{"a": a, "b": b} for a, b in dict.fromkeys(pairs)]
        for label, group in _by_label(rows, "a", DEFINABLE_LABELS).items():
            for batch in _batches(group):
                self.run(
                    f"""
                    UNWIND $rows AS row
                    MATCH (n:{label} {{id: row.a}}), (p:Passage {{id: row.b}})
                    MERGE (n)-[:DEFINED_IN]->(p)
                    """,
                    rows=batch,
                )

    def add_modifies(self, rows: list[dict[str, Any]]) -> None:
        """rows: {commit_id, symbol_id, omega, hunk}. One edge per (commit, symbol)."""
        for batch in _batches(modifies_write_rows(rows)):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (c:Commit {id: row.commit_id}), (s:Symbol {id: row.symbol_id})
                MERGE (c)-[r:MODIFIES]->(s)
                SET r.omega = row.omega, r.hunk = row.hunk
                """,
                rows=batch,
            )

    def add_precedes(self, pairs: list[tuple[str, str]]) -> None:
        """(a, b) -> PRECEDES, the first-parent chain. Never reaches igraph; the history tool reads it."""
        rows = [
            {"a": a, "b": b}
            for a, b in dict.fromkeys(pairs)
            if a != b and node_label(a, ("Commit",)) and node_label(b, ("Commit",))
        ]
        for batch in _batches(rows):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (a:Commit {id: row.a}), (b:Commit {id: row.b})
                MERGE (a)-[:PRECEDES]->(b)
                """,
                rows=batch,
            )

    def add_refers_to(self, rows: list[dict[str, Any]]) -> None:
        """rows: {passage_id, node_id, omega, token}. A prose or commit passage naming a code node."""
        shaped = refers_to_write_rows(rows)
        for label, group in _by_label(shaped, "node_id", REFERABLE_LABELS).items():
            for batch in _batches(group):
                self.run(
                    f"""
                    UNWIND $rows AS row
                    MATCH (p:Passage {{id: row.passage_id}}), (n:{label} {{id: row.node_id}})
                    MERGE (p)-[r:REFERS_TO]->(n)
                    SET r.omega = CASE WHEN r.omega IS NULL OR r.omega < row.omega
                                       THEN row.omega ELSE r.omega END,
                        r.token = CASE WHEN r.omega IS NULL OR r.omega <= row.omega
                                       THEN row.token ELSE r.token END
                    """,
                    rows=batch,
                )

    def set_symbol_communities(self, mapping: dict[str, int]) -> None:
        """{symbol_id: community}. The Leiden label, shown as the subsystem name."""
        rows = [{"id": sid, "community": int(value)} for sid, value in mapping.items()]
        for batch in _batches(rows):
            self.run(
                "UNWIND $rows AS row MATCH (n:Symbol {id: row.id}) SET n.community = row.community",
                rows=batch,
            )

    # ============================================================== reading

    def _code_nodes(self, label: str, ids: list[str], access: Access | None) -> list[dict[str, Any]]:
        """A code node is visible exactly when its source is: `source_id` is a property, so the
        access check is the same one-hop property comparison every other read makes (R1.6)."""
        if not ids:
            return []
        return self.run(
            f"""
            UNWIND $ids AS id
            MATCH (n:{label} {{id: id}})
            MATCH (s:Source {{id: n.source_id}}) WHERE {ACCESS_WHERE}
            RETURN n AS n, s.name AS source_name,
                   [(n)-[:DEFINED_IN]->(p:Passage) | p.id] AS passage_ids
            """,
            ids=list(ids),
            **access_params(access),
        )

    def get_symbols(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        return [
            _symbol_row({**dict(r["n"]), "source_name": r["source_name"], "passage_ids": r["passage_ids"]})
            for r in self._code_nodes("Symbol", ids, access)
        ]

    def get_data_objects(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        return [
            _data_object_row(
                {**dict(r["n"]), "source_name": r["source_name"], "passage_ids": r["passage_ids"]}
            )
            for r in self._code_nodes("DataObject", ids, access)
        ]

    def get_commits(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        return [
            _commit_row({**dict(r["n"]), "source_name": r["source_name"], "passage_ids": r["passage_ids"]})
            for r in self._code_nodes("Commit", ids, access)
        ]

    # ------------------------------------------------------ loading the graph

    def load_symbols(self) -> list[dict[str, Any]]:
        rows = self.run("MATCH (n:Symbol) RETURN n AS n")
        return self._with_source_and_degree([dict(r["n"]) for r in rows], _symbol_row)

    def load_data_objects(self) -> list[dict[str, Any]]:
        rows = self.run("MATCH (n:DataObject) RETURN n AS n")
        return self._with_source_and_degree([dict(r["n"]) for r in rows], _data_object_row)

    def load_commits(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (n:Commit)
            OPTIONAL MATCH (s:Source {id: n.source_id})
            RETURN n AS n, s.name AS source_name
            """
        )
        return [_commit_row({**dict(r["n"]), "source_name": r["source_name"] or ""}) for r in rows]

    def _with_source_and_degree(self, nodes: list[dict[str, Any]], shaper) -> list[dict[str, Any]]:
        """`in_degree` counts incoming CODE_EDGE of SPECIFICITY_KINDS only (S2.4)."""
        if not nodes:
            return []
        names = {r["id"]: r["name"] for r in self.run("MATCH (s:Source) RETURN s.id AS id, s.name AS name")}
        degrees = {
            r["id"]: int(r["n"])
            for r in self.run(
                """
                MATCH ()-[r:CODE_EDGE]->(n) WHERE r.kind IN $kinds
                RETURN n.id AS id, count(r) AS n
                """,
                kinds=list(SPECIFICITY_KINDS),
            )
        }
        return [
            shaper(
                {
                    **node,
                    "source_name": names.get(node.get("source_id") or "", ""),
                    "in_degree": degrees.get(node["id"], 0),
                }
            )
            for node in nodes
        ]

    def load_code_edges(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (a)-[r:CODE_EDGE]->(b)
            RETURN a.id AS a, b.id AS b, r.kind AS kind, r.omega AS omega,
                   r.provenance AS provenance, r.extra AS extra
            """
        )
        return [_code_edge_read_row(r) for r in rows]

    def load_definitions(self) -> list[dict[str, Any]]:
        return self.run("MATCH (n)-[:DEFINED_IN]->(p:Passage) RETURN n.id AS node_id, p.id AS passage_id")

    def load_modifies(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (c:Commit)-[r:MODIFIES]->(s:Symbol)
            RETURN c.id AS commit_id, s.id AS symbol_id, r.omega AS omega, r.hunk AS hunk
            """
        )
        return [
            {
                "commit_id": r["commit_id"],
                "symbol_id": r["symbol_id"],
                "omega": float(r["omega"] or 0.0),
                "hunk": _json_field(r["hunk"]),
            }
            for r in rows
        ]

    def load_precedes(self) -> list[dict[str, Any]]:
        # Sorted here rather than in Cypher: `RETURN a.id AS a ... ORDER BY a.ordinal` binds `a` to
        # the returned string, not the node, on both dialects. A graph promises no row order, so
        # the commit ordinal is what makes this reproducible.
        rows = self.run(
            """
            MATCH (a:Commit)-[:PRECEDES]->(b:Commit)
            RETURN a.id AS a, b.id AS b, a.ordinal AS a_ordinal, b.ordinal AS b_ordinal
            """
        )
        rows.sort(key=lambda r: (int(r["a_ordinal"] or 0), int(r["b_ordinal"] or 0)))
        return [{"a": r["a"], "b": r["b"]} for r in rows]

    def load_refers_to(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (p:Passage)-[r:REFERS_TO]->(n)
            RETURN p.id AS passage_id, n.id AS node_id, r.omega AS omega, r.token AS token
            """
        )
        return [
            {
                "passage_id": r["passage_id"],
                "node_id": r["node_id"],
                "omega": float(r["omega"] or 0.0),
                "token": r["token"] or "",
            }
            for r in rows
        ]

    def load_code_embeddings(self) -> tuple[list[str], list[list[float]]]:
        """Every symbol's and data object's name vector (used to find cross-kind synonyms)."""
        rows = self.run(
            """
            MATCH (n:Symbol) WHERE n.embedding IS NOT NULL RETURN n.id AS id, n.embedding AS embedding
            UNION ALL
            MATCH (n:DataObject) WHERE n.embedding IS NOT NULL RETURN n.id AS id, n.embedding AS embedding
            """
        )
        return [r["id"] for r in rows], [list(r["embedding"]) for r in rows]

    # ------------------------------------------------------------- deleting

    def delete_code_nodes_for_source(self, source_id: str) -> None:
        """
        Every code node of one source, as **three per-label statements**.

        Do not collapse these into `MATCH (n:Symbol:DataObject:Commit)`: that is LadybugDB's
        disjunction but Neo4j's *conjunction* (a node carrying all three labels), so on Neo4j it
        would match nothing and silently leak every code node (R1 gotcha 2).
        """
        for label in CODE_NODE_LABELS:
            while True:
                row = self.run_one(
                    f"""
                    MATCH (n:{label}) WHERE n.source_id = $id
                    WITH n LIMIT 500
                    DETACH DELETE n
                    RETURN count(*) AS deleted
                    """,
                    id=source_id,
                )
                if not row or row["deleted"] == 0:
                    break


def _code_edge_read_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "a": row["a"],
        "b": row["b"],
        "kind": row["kind"],
        "omega": float(row["omega"] or 0.0),
        "provenance": row["provenance"] or "",
        "extra": _json_field(row["extra"]),
    }


def _group_pairs(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """CODE_EDGE rows grouped by their concrete (from label, to label) pair (R4 T7)."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["label_a"], row["label_b"]), []).append(row)
    return grouped
