"""
The embedded store: the same graph as the Neo4j store, kept in one LadybugDB file.

LadybugDB (https://ladybugdb.com, the community continuation of Kùzu) is an
in-process graph database: no server, no password, no container. `hippo` opens
the `.lbug` file directly, so a laptop install is `pip install` + Ollama.

Every method here matches `hippo.store.Store` (the Neo4j one) name for name and
row for row; tests/unit/test_store*.py run against both. The Cypher differs in
places because LadybugDB is strictly typed and speaks a smaller dialect:

* Tables are declared up front (`CREATE NODE TABLE ...`), so every property has a
  fixed type and missing values come back as None rather than as absent keys.
* No `count { pattern }` subqueries, `SET n += map` or pattern comprehensions;
  the same results come from `OPTIONAL MATCH` + aggregation and from building the
  SET list in Python.
* Settings and free-form meta live as JSON text on one Settings row, because the
  schema cannot grow a column per key.
* Access (hippo/access.py) works exactly as in the Neo4j store: every read that
  hands back sources, passages, entities or facts takes an `access` and adds the
  ACCESS_WHERE predicate. Users point at their role through `role_id` (no HAS_ROLE
  edge; the joins are on the id), and username/token uniqueness is checked here
  because LadybugDB only enforces the primary key.

Two rules of the road for anyone editing the queries:

1. Text goes in as bytes and through `decode()`. The Python binding (real_ladybug
   0.15.3) parses any string parameter that starts with `{` or `[` as a struct or
   list; inside a parameter list it becomes an empty string. Passages of code or
   JSON, LLM output and every `*_json` column would all be mangled. Bytes are left
   alone, and `decode(blob)` turns them back into a STRING inside the query, so
   every free-text parameter is wrapped with `text()` here and `decode(...)` there.
   Ids, timestamps and fixed status words are safe and are passed as plain strings.
2. One process may open the file at a time, and one writer at a time inside that
   process, so every query goes through one connection behind one lock.
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..access import (
    ACCESS_WHERE,
    DEFAULT_ROLES,
    EVERYONE_RANK,
    Access,
    access_params,
    hash_password,
    new_token,
    verify_password,
)
from .base import DEFAULT_SETTINGS, new_id, now_iso, validate_settings
from .changesets import _changeset_row
from .code import (
    BOOSTABLE_LABELS,
    CODE_BATCH,
    CODE_NODE_LABELS,
    DEFINABLE_LABELS,
    REFERABLE_LABELS,
    SPECIFICITY_KINDS,
    SYNONYM_LABELS,
    TUNED_LABELS,
    _commit_row,
    _data_object_row,
    _json_field,
    _symbol_row,
    code_edge_write_rows,
    commit_write_row,
    data_object_write_row,
    grouped_by_labels,
    modifies_write_rows,
    node_label,
    ordered_pairs,
    refers_to_write_rows,
    symbol_write_row,
)
from .evals import _result_row, _run_row, _set_row
from .generations import GenerationQueries
from .knowledge import KnowledgeQueries
from .memory import _passage_row, _source_row
from .migrations import DEFAULT_WORKSPACE_ID
from .users import _role_row, _user_row, clean_capabilities, clean_rank, clean_username, slug

log = logging.getLogger(__name__)

BATCH = 500  # rows per write statement

# Node tables: every property the Neo4j store ever sets, with its type.
NODE_TABLES: dict[str, str] = {
    "Source": """id STRING PRIMARY KEY, kind STRING, name STRING, status STRING, stage STRING,
                 progress_done INT64, progress_total INT64, error STRING, meta_json STRING,
                 created_at STRING, updated_at STRING,
                 owner_id STRING, access_role_id STRING, min_rank INT64""",
    "Passage": """id STRING PRIMARY KEY, title STRING, text STRING, ordinal INT64, chars INT64,
                  embedding FLOAT[], entities_json STRING, triples_json STRING, extraction_error STRING""",
    "Entity": "id STRING PRIMARY KEY, name STRING, boost DOUBLE, embedding FLOAT[], created_at STRING",
    "Fact": """id STRING PRIMARY KEY, subject STRING, predicate STRING, object STRING,
               embedding FLOAT[], created_at STRING""",
    "QuestionSet": """id STRING PRIMARY KEY, name STRING, origin STRING, status STRING, stage STRING,
                      progress_done INT64, progress_total INT64, error STRING, created_at STRING""",
    "Question": """id STRING PRIMARY KEY, text STRING, expected_answer STRING, gold_passage_ids STRING[],
                   kind STRING, notes STRING, ordinal INT64""",
    "EvalRun": """id STRING PRIMARY KEY, name STRING, status STRING, started_at STRING, finished_at STRING,
                  settings_json STRING, summary_json STRING, progress_done INT64, progress_total INT64,
                  error STRING""",
    "EvalResult": """id STRING PRIMARY KEY, answer STRING, thought STRING, verdict STRING, judge_score DOUBLE,
                     judge_reason STRING, exact_match DOUBLE, f1 DOUBLE, recall_json STRING, gold_rank INT64,
                     latency_ms DOUBLE, trace_json STRING, used_dpr_fallback BOOLEAN, error STRING,
                     created_at STRING""",
    "Changeset": """id STRING PRIMARY KEY, name STRING, note STRING, status STRING, ops_json STRING,
                    created_at STRING, applied_at STRING, from_result_id STRING""",
    "Symbol": """id STRING PRIMARY KEY, source_id STRING, name STRING, qualname STRING, kind STRING,
                 lang STRING, path STRING, line_start INT64, line_end INT64, signature STRING,
                 doc STRING, is_test BOOLEAN, raises STRING[], community INT64, name_tokens STRING[],
                 boost DOUBLE, embedding FLOAT[], created_at STRING""",
    "DataObject": """id STRING PRIMARY KEY, source_id STRING, name STRING, qualname STRING,
                     kind STRING, dialect STRING, name_tokens STRING[], boost DOUBLE,
                     embedding FLOAT[], created_at STRING""",
    "Commit": """id STRING PRIMARY KEY, source_id STRING, sha STRING, author STRING, date STRING,
                 message STRING, ordinal INT64, created_at STRING""",
    "Settings": "id STRING PRIMARY KEY, settings_json STRING, meta_json STRING, graph_version INT64",
    "Role": """id STRING PRIMARY KEY, name STRING, rank INT64, description STRING, capabilities STRING[],
               builtin BOOLEAN""",
    "User": """id STRING PRIMARY KEY, username STRING, display_name STRING, password_hash STRING, token STRING,
               role_id STRING, disabled BOOLEAN, created_at STRING""",
}

# Relationship tables: (name, [(from label, to label), ...], extra properties). A table with more
# than one pair is grown in place on an existing file by `ensure_schema` (see the ALTER there), so
# adding an endpoint pair here is all a migration needs.
REL_TABLES: list[tuple[str, list[tuple[str, str]], str]] = [
    ("FROM", [("Passage", "Source")], ""),
    ("MENTIONS", [("Passage", "Entity")], ""),
    ("STATES", [("Passage", "Fact")], ""),
    ("SUBJECT", [("Fact", "Entity")], ""),
    ("OBJECT", [("Fact", "Entity")], ""),
    ("SYNONYM", ordered_pairs(SYNONYM_LABELS), ", score DOUBLE, manual BOOLEAN"),
    ("TUNED", ordered_pairs(TUNED_LABELS), ", weight DOUBLE, updated_at STRING"),
    (
        "CODE_EDGE",
        [("Symbol", "Symbol"), ("Symbol", "DataObject"), ("DataObject", "DataObject")],
        ", kind STRING, omega DOUBLE, provenance STRING, extra STRING",
    ),
    ("DEFINED_IN", [(label, "Passage") for label in DEFINABLE_LABELS], ""),
    ("REFERS_TO", [("Passage", label) for label in REFERABLE_LABELS], ", omega DOUBLE, token STRING"),
    ("MODIFIES", [("Commit", "Symbol")], ", omega DOUBLE, hunk STRING"),
    ("PRECEDES", [("Commit", "Commit")], ""),
    ("ABOUT", [("QuestionSet", "Source")], ""),
    ("HAS", [("QuestionSet", "Question")], ""),
    ("OF", [("EvalRun", "QuestionSet")], ""),
    ("RESULT", [("EvalRun", "EvalResult")], ""),
    ("FOR", [("EvalResult", "Question")], ""),
]

# Numeric fields, so a value arriving as the wrong Python type is coerced (LadybugDB will not
# cast a parameter, and an `int` where a DOUBLE column expects a float is common).
INT_FIELDS = {
    "progress_done",
    "progress_total",
    "ordinal",
    "gold_rank",
    "min_rank",
    "rank",
    "line_start",
    "line_end",
    "community",
}
FLOAT_FIELDS = {"judge_score", "exact_match", "f1", "latency_ms", "boost", "score", "weight", "omega"}


class StoreLockedError(RuntimeError):
    """Another hippo process has the database file open (LadybugDB allows one at a time)."""


def text(value: Any) -> bytes | None:
    """A free-text parameter, as bytes. Pair with `decode($name)` in the query (see the module docstring)."""
    if value is None:
        return None
    return str(value).encode("utf-8")


def _batches(rows: list[Any], size: int = BATCH):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _node(value: dict[str, Any] | None) -> dict[str, Any]:
    """A node returned whole, as the dict the row shapers expect: no internal keys, no null properties."""
    if not value:
        return {}
    return {k: v for k, v in value.items() if not k.startswith("_") and v is not None}


def _coerce(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in INT_FIELDS:
        return int(value)
    if key in FLOAT_FIELDS:
        return float(value)
    return value


def _in_asked_order(rows: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    """Rows in the order their ids were asked for (what UNWIND gives the Neo4j store); unknown ids are skipped."""
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def _vector(values: Any) -> list[float]:
    return [float(x) for x in values]


def _symbol_params(row: dict[str, Any]) -> dict[str, Any]:
    """A shaped symbol row with its free text as bytes (see the module docstring, rule 1)."""
    return {
        **row,
        **{k: text(row[k]) for k in ("name", "qualname", "kind", "lang", "path", "signature", "doc")},
    }


def _data_object_params(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, **{k: text(row[k]) for k in ("name", "qualname", "kind", "dialect")}}


def _by_label_pairs(
    pairs: list[tuple[str, str]], allowed: tuple[str, ...]
) -> dict[str, list[tuple[str, str]]]:
    """(node id, other id) pairs grouped by the concrete label of the first id (S2.2)."""
    grouped: dict[str, list[tuple[str, str]]] = {}
    for a, b in pairs:
        label = node_label(a, allowed)
        if label is not None:
            grouped.setdefault(label, []).append((a, b))
    return grouped


class LadybugStore(KnowledgeQueries, GenerationQueries):
    knowledge_backend = "ladybug"
    """All of hippo's queries against an embedded LadybugDB file. Same interface as `Store`."""

    def __init__(self, path: str | Path):
        import real_ladybug as lb  # imported here so `hippo.store` loads without the package installed

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = self._take_lock()
        try:
            self._db = lb.Database(str(self.path))
        except Exception as exc:  # noqa: BLE001 - the driver raises a plain RuntimeError
            self._release_lock()
            if "lock" in str(exc).lower():
                raise StoreLockedError(self._locked_message()) from exc
            if "wal" in str(exc).lower():
                raise RuntimeError(
                    f"could not open {self.path}: {exc}. If another program has the file open (say, an older "
                    "hippo), stop it and try again; otherwise its write-ahead log ({self.path}.wal) is damaged."
                ) from exc
            raise
        self._conn = lb.Connection(self._db)
        self._lock = threading.RLock()
        self._bootstrapped = False
        self._transaction_depth = 0
        self._migration_blocked = False
        self._migrating = False
        try:
            self.ensure_schema()
        except BaseException:
            self.close()
            raise

    def _locked_message(self) -> str:
        return (
            f"{self.path} is already open in another hippo process (LadybugDB allows one at a time). "
            "Stop it, or talk to the running server instead: the web UI, /api or /mcp."
        )

    def _take_lock(self):
        """
        Hold an advisory lock on `<file>.lock` for as long as the store is open.

        LadybugDB has its own file lock, but a second opener reads the write-ahead log *before*
        checking it and, while the first process is mid-write, fails with a scary "Corrupted wal
        file" instead of a plain "locked" (the files are not harmed; it only reads). Taking our
        own lock first means a second hippo never touches the database and gets a clear message.
        Uses fcntl, so on Windows this is a no-op and LadybugDB's own lock is what you get.
        """
        try:
            import fcntl
        except ImportError:  # pragma: no cover - Windows
            return None
        handle = open(self.path.with_name(self.path.name + ".lock"), "a+")  # noqa: SIM115 - kept open on purpose
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise StoreLockedError(self._locked_message()) from exc
        return handle

    def _release_lock(self) -> None:
        handle = getattr(self, "_lock_file", None)
        if handle is not None:
            try:
                handle.close()  # closing releases the flock
            finally:
                self._lock_file = None

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
                self._db.close()  # folds the write-ahead log into the .lbug file
            except Exception:  # noqa: BLE001 - closing twice is not worth an error
                pass
            self._release_lock()

    # ------------------------------------------------------------ running

    def run(self, query: str, **params: Any) -> list[dict[str, Any]]:
        """Run one Cypher statement (auto-committed) and return the rows as dicts keyed by column alias."""
        with self._lock:
            if self._migration_blocked and not self._migrating:
                raise RuntimeError("Store migration is incomplete; application access is disabled")
            if self._transaction_depth and self._transaction_failed and query.strip().upper() != "ROLLBACK":
                raise RuntimeError("Transaction failed; roll back before issuing another statement")
            result = None
            try:
                try:
                    result = self._conn.execute(query, params) if params else self._conn.execute(query)
                    columns = result.get_column_names()
                    rows = []
                    while result.has_next():
                        rows.append(dict(zip(columns, result.get_next(), strict=True)))
                    return rows
                finally:
                    if result is not None:
                        result.close()
            except BaseException:
                # Ladybug can auto-abort a failed statement. Without poisoning
                # the enclosing scope, its next write would silently autocommit.
                if self._transaction_depth:
                    self._transaction_failed = True
                raise

    def run_one(self, query: str, **params: Any) -> dict[str, Any] | None:
        rows = self.run(query, **params)
        return rows[0] if rows else None

    def ping(self) -> bool:
        """Always reachable (it is a file). The first call tidies up after any crash, like the Neo4j store."""
        if not self._bootstrapped:
            self.on_first_connection()
            self._bootstrapped = True
        return True

    def on_first_connection(self) -> None:
        self.ensure_schema()
        self.ensure_roles()
        interrupted = self.mark_interrupted_jobs()
        if interrupted:
            log.warning("%d job(s) were interrupted by the last shutdown and are marked failed", interrupted)

    # ------------------------------------------------------------- schema

    def ensure_schema(self) -> None:
        from .migrations import migrate_store

        migrate_store(self)

    @contextmanager
    def transaction(self):
        with self._lock:
            outer = self._transaction_depth == 0
            if outer:
                self.run("BEGIN TRANSACTION")
                self._transaction_failed = False
            self._transaction_depth += 1
            try:
                yield self
                if outer:
                    if self._transaction_failed:
                        raise RuntimeError("Nested transaction failed; outer transaction must roll back")
                    self.run("COMMIT")
            except BaseException:
                self._transaction_failed = True
                if outer:
                    try:
                        self.run("ROLLBACK")
                    except Exception:
                        pass  # Driver errors may already have aborted; preserve the cause.
                raise
            finally:
                self._transaction_depth -= 1
                if outer:
                    self._transaction_failed = False

    def _ensure_legacy_schema(self) -> None:
        """
        Create the tables and the Settings row. Safe to call on every start.

        A relationship table that gained endpoint pairs since the file was written is grown in
        place with `ALTER TABLE ... ADD IF NOT EXISTS FROM X TO Y`, which R4 T6 and WP1's own
        test 1.5a prove survives a close/reopen on a populated, property-bearing table. Only the
        missing pairs are altered, so a database that is already wide costs one `show_connection`
        per multi-pair table and nothing else.
        """
        with self._lock:
            for name, columns in NODE_TABLES.items():
                self.run(f"CREATE NODE TABLE IF NOT EXISTS {name}({columns})")
            for name, pairs, extra in REL_TABLES:
                declared = ", ".join(f"FROM {a} TO {b}" for a, b in pairs)
                self.run(f"CREATE REL TABLE IF NOT EXISTS {name}({declared}{extra})")
                if len(pairs) > 1:  # a one-pair table was just declared and cannot be missing it
                    for a, b in sorted(set(pairs) - self.connection_pairs(name)):
                        self.run(f"ALTER TABLE {name} ADD IF NOT EXISTS FROM {a} TO {b}")
            self.run(
                """
                MERGE (s:Settings {id: 'global'})
                ON CREATE SET s.settings_json = decode($settings), s.meta_json = '{}', s.graph_version = 0
                """,
                settings=text(json.dumps(DEFAULT_SETTINGS)),
            )

    def connection_pairs(self, rel_table: str) -> set[tuple[str, str]]:
        """The (from label, to label) pairs a relationship table currently accepts."""
        return {
            (row["source table name"], row["destination table name"])
            for row in self.run(f"CALL show_connection('{rel_table}') RETURN *")
        }

    # ----------------------------------------------------------- settings

    def _settings_row(self) -> dict[str, Any]:
        row = self.run_one(
            "MATCH (s:Settings {id: 'global'}) RETURN s.settings_json AS settings, s.meta_json AS meta, "
            "s.graph_version AS version"
        )
        return row or {"settings": "{}", "meta": "{}", "version": 0}

    def get_settings(self) -> dict[str, Any]:
        stored = json.loads(self._settings_row()["settings"] or "{}")
        return {key: stored.get(key, default) for key, default in DEFAULT_SETTINGS.items()}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        clean = validate_settings(changes)
        if clean:
            with self._lock:
                stored = json.loads(self._settings_row()["settings"] or "{}")
                stored.update(clean)
                self.run(
                    "MATCH (s:Settings {id: 'global'}) SET s.settings_json = decode($settings)",
                    settings=text(json.dumps(stored)),
                )
        return self.get_settings()

    def get_meta(self, key: str) -> Any:
        return json.loads(self._settings_row()["meta"] or "{}").get(key)

    def set_meta(self, key: str, value: Any) -> None:
        with self._lock:
            meta = json.loads(self._settings_row()["meta"] or "{}")
            meta[key] = value
            self.run(
                "MATCH (s:Settings {id: 'global'}) SET s.meta_json = decode($meta)",
                meta=text(json.dumps(meta)),
            )

    def graph_version(self) -> int:
        return int(self._settings_row()["version"] or 0)

    def bump_graph_version(self) -> int:
        row = self.run_one(
            """
            MATCH (s:Settings {id: 'global'})
            SET s.graph_version = coalesce(s.graph_version, 0) + 1
            RETURN s.graph_version AS v
            """
        )
        return int(row["v"]) if row else 0

    # -------------------------------------------------------------- stats

    def stats(self) -> dict[str, int]:
        def count(pattern: str) -> int:
            row = self.run_one(f"MATCH {pattern} RETURN count(*) AS n")
            return int(row["n"]) if row else 0

        return {
            "sources": count("(:Source)"),
            "passages": count("(:Passage)"),
            "entities": count("(:Entity)"),
            "facts": count("(:Fact)"),
            "symbols": count("(:Symbol)"),
            "data_objects": count("(:DataObject)"),
            "code_edges": count("()-[:CODE_EDGE]->()"),
            "commits": count("(:Commit)"),
            "synonym_edges": count("()-[:SYNONYM]->()"),
            "mention_edges": count("()-[:MENTIONS]->()"),
            "question_sets": count("(:QuestionSet)"),
            "eval_runs": count("(:EvalRun)"),
            "changesets": count("(:Changeset)"),
            "users": count("(:User)"),
            "roles": count("(:Role)"),
        }

    # ------------------------------------------------------- generic update

    def _set(self, label: str, node_id: str, fields: dict[str, Any]) -> None:
        """`SET n += $fields` for an already-validated set of keys. Strings travel as bytes (see `text`)."""
        params: dict[str, Any] = {"id": node_id}
        assignments = []
        for key, value in fields.items():
            value = _coerce(key, value)
            if isinstance(value, str):
                params[key] = text(value)
                assignments.append(f"n.{key} = decode(${key})")
            else:
                params[key] = value
                assignments.append(f"n.{key} = ${key}")
        self.run(f"MATCH (n:{label} {{id: $id}}) SET {', '.join(assignments)}", **params)

    # -------------------------------------------------------- linking nodes

    def _link(self, rel: str, from_label: str, to_label: str, pairs: list[tuple[str, str]]) -> None:
        """
        `MERGE (a)-[:REL]->(b)` for many (a_id, b_id) pairs at once. Written as "create the edge unless it
        exists" because LadybugDB 0.15 cannot MERGE a relationship under UNWIND (and one statement per pair
        costs ~10 ms, far too slow for the tens of thousands of MENTIONS links a big source makes).
        """
        rows = [{"a": a, "b": b} for a, b in dict.fromkeys(pairs)]  # dedupe, keep order
        for batch in _batches(rows, 1000):
            self.run(
                f"""
                UNWIND $rows AS row
                MATCH (a:{from_label} {{id: row.a}}), (b:{to_label} {{id: row.b}})
                WHERE NOT EXISTS {{ MATCH (a)-[:{rel}]->(b) }}
                CREATE (a)-[:{rel}]->(b)
                """,
                rows=batch,
            )

    # ============================================================== sources

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
        with self._lock:
            role = self.get_role(access_role_id) if access_role_id else None
            self.run(
                """
                CREATE (s:Source {id: $id, kind: decode($kind), name: decode($name), status: 'queued', stage: 'queued',
                                  progress_done: 0, progress_total: 0, meta_json: decode($meta_json),
                                  created_at: $now, updated_at: $now,
                                  owner_id: $owner_id, access_role_id: $access_role_id, min_rank: $min_rank})
                """,
                id=source_id,
                kind=text(kind),
                name=text(name),
                meta_json=text(json.dumps(meta or {})),
                now=now_iso(),
                owner_id=owner_id,
                access_role_id=role["id"] if role else None,
                min_rank=int(role["rank"]) if role else EVERYONE_RANK,
            )
        if getattr(self, "_schema_checked", False):
            self.run(
                "MATCH (s:Source {id:$id}) SET s.workspace_id=$workspace, s.generation_version=0",
                id=source_id,
                workspace=DEFAULT_WORKSPACE_ID,
            )
        return source_id

    def update_source(self, source_id: str, **fields: Any) -> None:
        allowed = {"status", "stage", "progress_done", "progress_total", "error", "name", "meta_json"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown source fields: {sorted(bad)}")
        fields["updated_at"] = now_iso()
        self._set("Source", source_id, fields)

    def _source_counts(self, source_id: str | None = None) -> tuple[dict[str, int], dict[str, int]]:
        """Passages and (passage, fact) links per source id, for one source or for all of them."""
        where = "WHERE s.id = $id" if source_id else ""
        passages = {
            r["id"]: int(r["n"])
            for r in self.run(
                f"MATCH (s:Source)<-[:FROM]-(p:Passage) {where} RETURN s.id AS id, count(p) AS n",
                id=source_id,
            )
        }
        links = {
            r["id"]: int(r["n"])
            for r in self.run(
                f"MATCH (s:Source)<-[:FROM]-(:Passage)-[:STATES]->(:Fact) {where} RETURN s.id AS id, count(*) AS n",
                id=source_id,
            )
        }
        return passages, links

    def _shape_source(
        self, row: dict[str, Any], counts: tuple[dict[str, int], dict[str, int]]
    ) -> dict[str, Any]:
        source = _node(row["s"])
        passages, links = counts
        return _source_row(
            {
                "s": source,
                "access_role_name": row.get("access_role_name"),
                "owner_name": row.get("owner_name"),
                "passages": passages.get(source["id"], 0),
                "fact_links": links.get(source["id"], 0),
            }
        )

    _SOURCE_QUERY = f"""
        MATCH (s:Source) WHERE {{where}} {ACCESS_WHERE}
        OPTIONAL MATCH (r:Role {{{{id: s.access_role_id}}}})
        OPTIONAL MATCH (u:User {{{{id: s.owner_id}}}})
        RETURN s AS s, r.name AS access_role_name, u.username AS owner_name
        ORDER BY s.created_at DESC
    """

    def get_source(self, source_id: str, access: Access | None = None) -> dict[str, Any] | None:
        row = self.run_one(
            self._SOURCE_QUERY.format(where="s.id = $id AND"), id=source_id, **access_params(access)
        )
        return self._shape_source(row, self._source_counts(source_id)) if row else None

    def list_sources(self, access: Access | None = None) -> list[dict[str, Any]]:
        rows = self.run(self._SOURCE_QUERY.format(where=""), **access_params(access))
        counts = self._source_counts()
        return [self._shape_source(r, counts) for r in rows]

    def delete_source(self, source_id: str) -> None:
        with self._lock:
            self.delete_code_nodes_for_source(source_id)
            self.run("MATCH (s:Source {id: $id})<-[:FROM]-(p:Passage) DETACH DELETE p", id=source_id)
            self.run("MATCH (s:Source {id: $id}) DETACH DELETE s", id=source_id)
            self.remove_orphans()

    def delete_passages_for_source(self, source_id: str) -> None:
        with self._lock:
            self.delete_code_nodes_for_source(source_id)
            self.run("MATCH (s:Source {id: $id})<-[:FROM]-(p:Passage) DETACH DELETE p", id=source_id)
            self.remove_orphans()

    def mark_interrupted_jobs(self) -> int:
        message = text("interrupted by a restart; run it again")
        now = now_iso()
        total = 0
        for label, condition, sets in (
            (
                "Source",
                "n.status IN ['reading', 'indexing']",
                "n.status = 'failed', n.error = decode($message), n.updated_at = $now",
            ),
            (
                "EvalRun",
                "n.status = 'running'",
                "n.status = 'failed', n.error = decode($message), n.finished_at = $now",
            ),
            ("QuestionSet", "n.status = 'generating'", "n.status = 'failed', n.error = decode($message)"),
        ):
            with self._lock:
                row = self.run_one(f"MATCH (n:{label}) WHERE {condition} RETURN count(n) AS n")
                count = int(row["n"]) if row else 0
                if count:
                    self.run(f"MATCH (n:{label}) WHERE {condition} SET {sets}", message=message, now=now)
                total += count
        return total

    def remove_orphans(self) -> None:
        self.run("MATCH (f:Fact) WHERE NOT EXISTS { MATCH (f)<-[:STATES]-(:Passage) } DETACH DELETE f")
        self.run("MATCH (e:Entity) WHERE NOT EXISTS { MATCH (e)<-[:MENTIONS]-(:Passage) } DETACH DELETE e")

    # ============================================================= passages

    def add_passages(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, source_id, ordinal, title, text, embedding}."""
        shaped = [
            {
                "id": r["id"],
                "source_id": r["source_id"],
                "ordinal": int(r.get("ordinal") or 0),
                "title": text(r.get("title") or ""),
                "text": text(r.get("text") or ""),
                "embedding": _vector(r["embedding"]),
            }
            for r in rows
        ]
        # The nodes first, then their links (see _link for why not in one statement).
        for batch in _batches(shaped):
            with self._lock:
                self.run(
                    """
                    UNWIND $rows AS row
                    MATCH (s:Source {id: row.source_id})
                    MERGE (p:Passage {id: row.id})
                    SET p.title = decode(row.title), p.text = decode(row.text), p.ordinal = row.ordinal,
                        p.chars = size(decode(row.text)), p.embedding = row.embedding
                    """,
                    rows=batch,
                )
                self._link("FROM", "Passage", "Source", [(r["id"], r["source_id"]) for r in batch])

    def save_extraction(
        self, passage_id: str, entities: list[str], triples: list[list[str]], error: str | None
    ) -> None:
        self.run(
            """
            MATCH (p:Passage {id: $id})
            SET p.entities_json = decode($entities), p.triples_json = decode($triples),
                p.extraction_error = decode($error)
            """,
            id=passage_id,
            entities=text(json.dumps(entities)),
            triples=text(json.dumps(triples)),
            error=text(error),
        )

    _PASSAGE_COLUMNS = """p.id AS id, p.title AS title, p.text AS text, p.ordinal AS ordinal,
                   s.id AS source_id, s.name AS source_name,
                   p.entities_json AS entities_json, p.triples_json AS triples_json,
                   p.extraction_error AS extraction_error"""

    def get_passages(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        if not ids:
            return []
        rows = self.run(
            f"""
            MATCH (p:Passage)-[:FROM]->(s:Source) WHERE p.id IN $ids AND {ACCESS_WHERE}
            RETURN {self._PASSAGE_COLUMNS}
            """,
            ids=list(ids),
            **access_params(access),
        )
        return _in_asked_order([_passage_row(_node(r)) for r in rows], ids)

    def passages_for_source(
        self, source_id: str, limit: int = 50, offset: int = 0, access: Access | None = None
    ) -> list[dict[str, Any]]:
        rows = self.run(
            f"""
            MATCH (p:Passage)-[:FROM]->(s:Source {{id: $id}}) WHERE {ACCESS_WHERE}
            RETURN {self._PASSAGE_COLUMNS}
            ORDER BY p.ordinal SKIP $offset LIMIT $limit
            """,
            id=source_id,
            limit=int(limit),
            offset=int(offset),
            **access_params(access),
        )
        return [_passage_row(_node(r)) for r in rows]

    def passage_ids_for_source(self, source_id: str) -> list[str]:
        rows = self.run(
            "MATCH (p:Passage)-[:FROM]->(:Source {id: $id}) RETURN p.id AS id ORDER BY p.ordinal",
            id=source_id,
        )
        return [r["id"] for r in rows]

    # ============================================================= entities

    def existing_entity_ids(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        rows = self.run("MATCH (e:Entity) WHERE e.id IN $ids RETURN e.id AS id", ids=list(ids))
        return {r["id"] for r in rows}

    def add_entities(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, name, embedding}. Re-adding an existing id is harmless."""
        shaped = [
            {"id": r["id"], "name": text(r.get("name") or ""), "embedding": _vector(r["embedding"])}
            for r in rows
        ]
        for batch in _batches(shaped):
            self.run(
                """
                UNWIND $rows AS row
                MERGE (e:Entity {id: row.id})
                ON CREATE SET e.name = decode(row.name), e.created_at = $now, e.embedding = row.embedding
                """,
                rows=batch,
                now=now_iso(),
            )

    # An entity is visible when a visible passage mentions it, and its passage_count counts visible
    # passages only. Unrestricted reads keep entities nothing mentions yet (the indexer looks them up
    # before linking them).
    _VISIBLE_MENTIONS = f"""
        OPTIONAL MATCH (e)<-[:MENTIONS]-(p:Passage)-[:FROM]->(s:Source) WHERE {ACCESS_WHERE}
        WITH e, count(p) AS passage_count
        WHERE $acc_all OR passage_count > 0
    """

    def get_entities(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        if not ids:
            return []
        rows = self.run(
            f"""
            MATCH (e:Entity) WHERE e.id IN $ids
            {self._VISIBLE_MENTIONS}
            RETURN e.id AS id, e.name AS name, coalesce(e.boost, 1.0) AS boost, passage_count
            """,
            ids=list(ids),
            **access_params(access),
        )
        return _in_asked_order(rows, ids)

    def search_entities(
        self, text_: str, limit: int = 20, access: Access | None = None
    ) -> list[dict[str, Any]]:
        return self.run(
            f"""
            MATCH (e:Entity) WHERE e.name CONTAINS decode($needle)
            {self._VISIBLE_MENTIONS}
            RETURN e.id AS id, e.name AS name, passage_count
            ORDER BY passage_count DESC, name LIMIT $limit
            """,
            needle=text(text_.lower()),
            limit=int(limit),
            **access_params(access),
        )

    def load_entity_embeddings(self) -> tuple[list[str], list[list[float]]]:
        rows = self.run("MATCH (e:Entity) RETURN e.id AS id, e.embedding AS embedding")
        return [r["id"] for r in rows], [r["embedding"] for r in rows]

    # ================================================================ facts

    def existing_fact_ids(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        rows = self.run("MATCH (f:Fact) WHERE f.id IN $ids RETURN f.id AS id", ids=list(ids))
        return {r["id"] for r in rows}

    def add_facts(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, subject, predicate, object, subject_id, object_id, embedding}."""
        shaped = [
            {
                "id": r["id"],
                "subject": text(r.get("subject") or ""),
                "predicate": text(r.get("predicate") or ""),
                "object": text(r.get("object") or ""),
                "subject_id": r["subject_id"],
                "object_id": r["object_id"],
                "embedding": _vector(r["embedding"]),
            }
            for r in rows
        ]
        for batch in _batches(shaped):
            with self._lock:
                self.run(
                    """
                    UNWIND $rows AS row
                    MATCH (a:Entity {id: row.subject_id}), (b:Entity {id: row.object_id})
                    MERGE (f:Fact {id: row.id})
                    ON CREATE SET f.subject = decode(row.subject), f.predicate = decode(row.predicate),
                                  f.object = decode(row.object), f.created_at = $now, f.embedding = row.embedding
                    """,
                    rows=batch,
                    now=now_iso(),
                )
                self._link("SUBJECT", "Fact", "Entity", [(r["id"], r["subject_id"]) for r in batch])
                self._link("OBJECT", "Fact", "Entity", [(r["id"], r["object_id"]) for r in batch])

    def _fact_rows(
        self, where: str, with_embedding: bool, access: Access | None = None, **params: Any
    ) -> list[dict[str, Any]]:
        """Facts with the passages that state them; only visible passages are listed, and a fact
        nobody visible states is left out (unless the read is unrestricted)."""
        embedding = "f.embedding AS embedding," if with_embedding else ""
        rows = self.run(
            f"""
            MATCH (f:Fact)-[:SUBJECT]->(a:Entity), (f)-[:OBJECT]->(b:Entity) {where}
            OPTIONAL MATCH (p:Passage)-[:STATES]->(f), (p)-[:FROM]->(s:Source) WHERE {ACCESS_WHERE}
            WITH f, a, b, count(p) AS visible, collect(p.id) AS passage_ids
            WHERE $acc_all OR visible > 0
            RETURN f.id AS id, f.subject AS subject, f.predicate AS predicate, f.object AS object,
                   a.id AS subject_id, b.id AS object_id, {embedding}
                   passage_ids
            """,
            **params,
            **access_params(access),
        )
        for row in rows:
            row["passage_ids"] = [pid for pid in (row["passage_ids"] or []) if pid is not None]
        return rows

    def get_facts(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        if not ids:
            return []
        return _in_asked_order(
            self._fact_rows("WHERE f.id IN $ids", with_embedding=False, access=access, ids=list(ids)), ids
        )

    # ================================================================ links

    def link_passage_facts(self, pairs: list[tuple[str, str]]) -> None:
        self._link("STATES", "Passage", "Fact", list(pairs))

    def link_passage_entities(self, pairs: list[tuple[str, str]]) -> None:
        self._link("MENTIONS", "Passage", "Entity", list(pairs))

    def add_synonyms(self, rows: list[tuple[str, str, float]], manual: bool = False) -> None:
        """
        rows: (node_id_a, node_id_b, score). Stored once per pair (a < b), keeping the best score.

        Either id may be an entity, a symbol or a data object; the label comes from the id prefix
        (`label_of`, S2.2) and each write is bound to one concrete label pair, which is what
        LadybugDB requires. A pair SYNONYM has no endpoint for is skipped, exactly as a `MATCH`
        that finds nothing would be.
        """
        best: dict[tuple[str, str], float] = {}
        for a, b, score in rows:
            if a != b:
                key = (min(a, b), max(a, b))
                best[key] = max(best.get(key, 0.0), float(score))
        for (label_a, label_b), group in grouped_by_labels(best, SYNONYM_LABELS).items():
            for batch in _batches(group, 1000):
                with self._lock:
                    # Existing edges: raise the score if the new one is better, and remember a manual link.
                    self.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (a:{label_a} {{id: row.a}})-[s:SYNONYM]->(b:{label_b} {{id: row.b}})
                        SET s.score = CASE WHEN s.score IS NULL OR s.score < row.score
                                           THEN row.score ELSE s.score END,
                            s.manual = coalesce(s.manual, false) OR $manual
                        """,
                        rows=batch,
                        manual=bool(manual),
                    )
                    self.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (a:{label_a} {{id: row.a}}), (b:{label_b} {{id: row.b}})
                        WHERE NOT EXISTS {{ MATCH (a)-[:SYNONYM]->(b) }}
                        CREATE (a)-[:SYNONYM {{score: row.score, manual: $manual}}]->(b)
                        """,
                        rows=batch,
                        manual=bool(manual),
                    )

    # =========================================================== code graph
    # Same names and row shapes as store/code.py (Neo4j) and tests/fakes/fake_store.py.
    # Every write is bound to one concrete label pair, because LadybugDB refuses to create a
    # relationship whose endpoints are bound by several labels (R4 T7).

    def add_symbols(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, source_id, name, qualname, kind, lang, path, line_start, line_end, signature,
        doc, is_test, raises, embedding}. Re-adding updates in place; an unknown source is skipped."""
        shaped = [symbol_write_row(r) for r in rows]
        for batch in _batches(shaped, CODE_BATCH):
            with self._lock:
                self.run(
                    """
                    UNWIND $rows AS row
                    MATCH (src:Source {id: row.source_id})
                    MERGE (n:Symbol {id: row.id})
                    ON CREATE SET n.created_at = $now
                    SET n.source_id = row.source_id, n.name = decode(row.name),
                        n.qualname = decode(row.qualname), n.kind = decode(row.kind),
                        n.lang = decode(row.lang), n.path = decode(row.path),
                        n.line_start = row.line_start, n.line_end = row.line_end,
                        n.signature = decode(row.signature), n.doc = decode(row.doc),
                        n.is_test = row.is_test, n.raises = row.raises, n.name_tokens = row.name_tokens
                    """,
                    rows=[_symbol_params(r) for r in batch],
                    now=now_iso(),
                )
                self._set_embeddings("Symbol", batch)

    def add_data_objects(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, source_id, name, qualname, kind, dialect, embedding}."""
        shaped = [data_object_write_row(r) for r in rows]
        for batch in _batches(shaped, CODE_BATCH):
            with self._lock:
                self.run(
                    """
                    UNWIND $rows AS row
                    MATCH (src:Source {id: row.source_id})
                    MERGE (n:DataObject {id: row.id})
                    ON CREATE SET n.created_at = $now
                    SET n.source_id = row.source_id, n.name = decode(row.name),
                        n.qualname = decode(row.qualname), n.kind = decode(row.kind),
                        n.dialect = decode(row.dialect), n.name_tokens = row.name_tokens
                    """,
                    rows=[_data_object_params(r) for r in batch],
                    now=now_iso(),
                )
                self._set_embeddings("DataObject", batch)

    def _set_embeddings(self, label: str, rows: list[dict[str, Any]]) -> None:
        """Vectors in their own pass: LadybugDB cannot type an empty FLOAT[] literal, and a symbol
        may legitimately arrive without one (the indexer embeds names, tests often do not)."""
        with_vectors = [{"id": r["id"], "embedding": _vector(r["embedding"])} for r in rows if r["embedding"]]
        for batch in _batches(with_vectors, CODE_BATCH):
            self.run(
                f"UNWIND $rows AS row MATCH (n:{label} {{id: row.id}}) SET n.embedding = row.embedding",
                rows=batch,
            )

    def add_commits(self, rows: list[dict[str, Any]]) -> None:
        """rows: {id, source_id, sha, author, date, message, ordinal}."""
        shaped = [commit_write_row(r) for r in rows]
        for batch in _batches(shaped, CODE_BATCH):
            self.run(
                """
                UNWIND $rows AS row
                MATCH (src:Source {id: row.source_id})
                MERGE (n:Commit {id: row.id})
                ON CREATE SET n.created_at = $now
                SET n.source_id = row.source_id, n.sha = decode(row.sha), n.author = decode(row.author),
                    n.date = decode(row.date), n.message = decode(row.message), n.ordinal = row.ordinal
                """,
                rows=[
                    {
                        **r,
                        "sha": text(r["sha"]),
                        "author": text(r["author"]),
                        "date": text(r["date"]),
                        "message": text(r["message"]),
                    }
                    for r in batch
                ],
                now=now_iso(),
            )

    def add_code_edges(self, rows: list[dict[str, Any]]) -> None:
        """rows: {a, b, kind, omega, provenance, extra}. Directed, one per (a, b, kind); re-adding
        raises omega and never lowers it. Unknown kinds raise; self-loops and bad pairs are dropped."""
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in code_edge_write_rows(rows):
            grouped.setdefault((row["label_a"], row["label_b"]), []).append(
                {
                    "a": row["a"],
                    "b": row["b"],
                    "kind": row["kind"],  # a fixed vocabulary word: safe as a plain string
                    "omega": row["omega"],
                    "provenance": text(row["provenance"]),
                    "extra": text(row["extra"]),
                }
            )
        for (label_a, label_b), group in grouped.items():
            for batch in _batches(group, CODE_BATCH):
                with self._lock:
                    # LadybugDB 0.15 cannot MERGE a relationship under UNWIND (see _link), so this
                    # is the same two-statement shape: raise omega on what is there, create the rest.
                    self.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (a:{label_a} {{id: row.a}})-[r:CODE_EDGE]->(b:{label_b} {{id: row.b}})
                        WHERE r.kind = row.kind AND r.omega < row.omega
                        SET r.omega = row.omega, r.provenance = decode(row.provenance),
                            r.extra = decode(row.extra)
                        """,
                        rows=batch,
                    )
                    self.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (a:{label_a} {{id: row.a}}), (b:{label_b} {{id: row.b}})
                        WHERE NOT EXISTS {{ MATCH (a)-[r:CODE_EDGE]->(b) WHERE r.kind = row.kind }}
                        CREATE (a)-[:CODE_EDGE {{kind: row.kind, omega: row.omega,
                                                 provenance: decode(row.provenance),
                                                 extra: decode(row.extra)}}]->(b)
                        """,
                        rows=batch,
                    )

    def link_definitions(self, pairs: list[tuple[str, str]]) -> None:
        """(node_id, passage_id) -> DEFINED_IN. The node may be a symbol, data object or commit."""
        for label, group in _by_label_pairs(pairs, DEFINABLE_LABELS).items():
            self._link("DEFINED_IN", label, "Passage", group)

    def add_modifies(self, rows: list[dict[str, Any]]) -> None:
        """rows: {commit_id, symbol_id, omega, hunk}. One edge per (commit, symbol)."""
        shaped = [{**r, "hunk": text(r["hunk"])} for r in modifies_write_rows(rows)]
        for batch in _batches(shaped, CODE_BATCH):
            with self._lock:
                self.run(
                    """
                    UNWIND $rows AS row
                    MATCH (c:Commit {id: row.commit_id})-[r:MODIFIES]->(s:Symbol {id: row.symbol_id})
                    SET r.omega = row.omega, r.hunk = decode(row.hunk)
                    """,
                    rows=batch,
                )
                self.run(
                    """
                    UNWIND $rows AS row
                    MATCH (c:Commit {id: row.commit_id}), (s:Symbol {id: row.symbol_id})
                    WHERE NOT EXISTS { MATCH (c)-[:MODIFIES]->(s) }
                    CREATE (c)-[:MODIFIES {omega: row.omega, hunk: decode(row.hunk)}]->(s)
                    """,
                    rows=batch,
                )

    def add_precedes(self, pairs: list[tuple[str, str]]) -> None:
        """(a, b) -> PRECEDES, the first-parent chain. Never reaches igraph; the history tool reads it."""
        chain = [
            (a, b) for a, b in pairs if a != b and node_label(a, ("Commit",)) and node_label(b, ("Commit",))
        ]
        self._link("PRECEDES", "Commit", "Commit", chain)

    def add_refers_to(self, rows: list[dict[str, Any]]) -> None:
        """rows: {passage_id, node_id, omega, token}. A prose or commit passage naming a code node."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in refers_to_write_rows(rows):
            grouped.setdefault(row["label"], []).append({**row, "token": text(row["token"])})
        for label, group in grouped.items():
            for batch in _batches(group, CODE_BATCH):
                with self._lock:
                    self.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (p:Passage {{id: row.passage_id}})-[r:REFERS_TO]->(n:{label} {{id: row.node_id}})
                        WHERE r.omega < row.omega
                        SET r.omega = row.omega, r.token = decode(row.token)
                        """,
                        rows=batch,
                    )
                    self.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (p:Passage {{id: row.passage_id}}), (n:{label} {{id: row.node_id}})
                        WHERE NOT EXISTS {{ MATCH (p)-[:REFERS_TO]->(n) }}
                        CREATE (p)-[:REFERS_TO {{omega: row.omega, token: decode(row.token)}}]->(n)
                        """,
                        rows=batch,
                    )

    def set_symbol_communities(self, mapping: dict[str, int]) -> None:
        """{symbol_id: community}. The Leiden label, shown as the subsystem name."""
        rows = [{"id": sid, "community": int(value)} for sid, value in mapping.items()]
        for batch in _batches(rows, CODE_BATCH):
            self.run(
                "UNWIND $rows AS row MATCH (n:Symbol {id: row.id}) SET n.community = row.community",
                rows=batch,
            )

    # ------------------------------------------------------- reading code nodes

    def _code_nodes(self, label: str, ids: list[str], access: Access | None) -> list[dict[str, Any]]:
        """A code node is visible exactly when its source is: `source_id` is a property, so this is
        the same one-hop property check every other access-aware read makes (R1.6)."""
        if not ids:
            return []
        rows = self.run(
            f"""
            MATCH (n:{label}) WHERE n.id IN $ids
            MATCH (s:Source {{id: n.source_id}}) WHERE {ACCESS_WHERE}
            OPTIONAL MATCH (n)-[:DEFINED_IN]->(p:Passage)
            WITH n, s, collect(p.id) AS passage_ids
            RETURN n AS n, s.name AS source_name, passage_ids
            """,
            ids=list(ids),
            **access_params(access),
        )
        return [
            {
                **_node(r["n"]),
                "source_name": r["source_name"] or "",
                "passage_ids": [pid for pid in (r["passage_ids"] or []) if pid is not None],
            }
            for r in rows
        ]

    def get_symbols(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        return _in_asked_order([_symbol_row(r) for r in self._code_nodes("Symbol", ids, access)], ids)

    def get_data_objects(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        return _in_asked_order(
            [_data_object_row(r) for r in self._code_nodes("DataObject", ids, access)], ids
        )

    def get_commits(self, ids: list[str], access: Access | None = None) -> list[dict[str, Any]]:
        return _in_asked_order([_commit_row(r) for r in self._code_nodes("Commit", ids, access)], ids)

    # ------------------------------------------------- loading the code graph

    def _code_in_degrees(self) -> dict[str, int]:
        """Incoming CODE_EDGE of SPECIFICITY_KINDS per node id (S2.4: MODIFIES is excluded)."""
        return {
            r["id"]: int(r["n"])
            for r in self.run(
                """
                MATCH (a)-[r:CODE_EDGE]->(b) WHERE r.kind IN $kinds
                RETURN b.id AS id, count(r) AS n
                """,
                kinds=list(SPECIFICITY_KINDS),
            )
        }

    def load_symbols(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (n:Symbol)
            OPTIONAL MATCH (s:Source {id: n.source_id})
            RETURN n AS n, s.name AS source_name
            """
        )
        degrees = self._code_in_degrees()
        return [
            _symbol_row(
                {
                    **_node(r["n"]),
                    "source_name": r["source_name"] or "",
                    "in_degree": degrees.get(_node(r["n"])["id"], 0),
                }
            )
            for r in rows
        ]

    def load_data_objects(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (n:DataObject)
            OPTIONAL MATCH (s:Source {id: n.source_id})
            RETURN n AS n, s.name AS source_name
            """
        )
        degrees = self._code_in_degrees()
        return [
            _data_object_row(
                {
                    **_node(r["n"]),
                    "source_name": r["source_name"] or "",
                    "in_degree": degrees.get(_node(r["n"])["id"], 0),
                }
            )
            for r in rows
        ]

    def load_commits(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (n:Commit)
            OPTIONAL MATCH (s:Source {id: n.source_id})
            RETURN n AS n, s.name AS source_name
            """
        )
        return [_commit_row({**_node(r["n"]), "source_name": r["source_name"] or ""}) for r in rows]

    def load_code_edges(self) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (a)-[r:CODE_EDGE]->(b)
            RETURN a.id AS a, b.id AS b, r.kind AS kind, r.omega AS omega,
                   r.provenance AS provenance, r.extra AS extra
            """
        )
        return [
            {
                "a": r["a"],
                "b": r["b"],
                "kind": r["kind"],
                "omega": float(r["omega"] or 0.0),
                "provenance": r["provenance"] or "",
                "extra": _json_field(r["extra"]),
            }
            for r in rows
        ]

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
        ids: list[str] = []
        vectors: list[list[float]] = []
        for label in ("Symbol", "DataObject"):
            for row in self.run(f"MATCH (n:{label}) RETURN n.id AS id, n.embedding AS embedding"):
                if row["embedding"]:
                    ids.append(row["id"])
                    vectors.append(list(row["embedding"]))
        return ids, vectors

    def delete_code_nodes_for_source(self, source_id: str) -> None:
        """
        Every code node of one source, as **three per-label statements**.

        Do not collapse these into `MATCH (n:Symbol:DataObject:Commit)`: that is LadybugDB's
        disjunction but Neo4j's *conjunction*, so the same chained query would match nothing on
        Neo4j and silently leak every code node (R1 gotcha 2).
        """
        with self._lock:
            for label in CODE_NODE_LABELS:
                self.run(f"MATCH (n:{label}) WHERE n.source_id = $id DETACH DELETE n", id=source_id)

    # ====================================================== loading the graph

    def load_entities(self) -> list[dict[str, Any]]:
        return self.run(
            """
            MATCH (e:Entity)
            OPTIONAL MATCH (e)<-[:MENTIONS]-(p:Passage)
            RETURN e.id AS id, e.name AS name, coalesce(e.boost, 1.0) AS boost, count(p) AS passage_count,
                   e.created_at AS created_at
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
        return self._fact_rows("", with_embedding=True)

    def load_fact_edges(self) -> list[dict[str, Any]]:
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
        # Unlabelled, like load_tuned_edges: SYNONYM now joins entities, symbols and data objects,
        # and a labelled MATCH would silently drop every cross-kind row.
        return self.run(
            "MATCH (a)-[s:SYNONYM]->(b) "
            "RETURN a.id AS a, b.id AS b, s.score AS score, coalesce(s.manual, false) AS manual"
        )

    def load_tuned_edges(self) -> list[dict[str, Any]]:
        return self.run("MATCH (a)-[t:TUNED]->(b) RETURN a.id AS a, b.id AS b, t.weight AS weight")

    # ======================================================== question sets

    def create_question_set(self, name: str, source_id: str | None = None, origin: str = "manual") -> str:
        set_id = new_id()
        with self._lock:
            self.run(
                """
                CREATE (qs:QuestionSet {id: $id, name: decode($name), origin: decode($origin), status: 'ready',
                                        stage: '', progress_done: 0, progress_total: 0, created_at: $now})
                """,
                id=set_id,
                name=text(name),
                origin=text(origin),
                now=now_iso(),
            )
            if source_id:
                self.run(
                    "MATCH (qs:QuestionSet {id: $id}), (s:Source {id: $source_id}) MERGE (qs)-[:ABOUT]->(s)",
                    id=set_id,
                    source_id=source_id,
                )
        return set_id

    def add_questions(self, set_id: str, questions: list[dict[str, Any]]) -> list[str]:
        with self._lock:
            start = self.run_one(
                "MATCH (:QuestionSet {id: $id})-[:HAS]->(q:Question) RETURN count(q) AS n", id=set_id
            )
            offset = int(start["n"]) if start else 0
            rows = [
                {
                    "id": new_id(),
                    "text": text(q["text"]),
                    "expected_answer": text(q.get("expected_answer") or ""),
                    "gold_passage_ids": [str(pid) for pid in (q.get("gold_passage_ids") or [])],
                    "kind": text(q.get("kind") or "single"),
                    "notes": text(q.get("notes") or ""),
                    "ordinal": offset + i,
                }
                for i, q in enumerate(questions)
            ]
            for batch in _batches(rows):
                self.run(
                    """
                    MATCH (qs:QuestionSet {id: $set_id})
                    UNWIND $rows AS row
                    CREATE (qs)-[:HAS]->(q:Question {id: row.id, text: decode(row.text),
                                                     expected_answer: decode(row.expected_answer),
                                                     gold_passage_ids: row.gold_passage_ids, kind: decode(row.kind),
                                                     notes: decode(row.notes), ordinal: row.ordinal})
                    """,
                    set_id=set_id,
                    rows=batch,
                )
        return [r["id"] for r in rows]

    def update_question_set(self, set_id: str, **fields: Any) -> None:
        allowed = {"status", "stage", "progress_done", "progress_total", "error", "name"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown question set fields: {sorted(bad)}")
        self._set("QuestionSet", set_id, fields)

    def delete_question(self, question_id: str) -> None:
        self.run("MATCH (q:Question {id: $id}) DETACH DELETE q", id=question_id)

    def delete_question_set(self, set_id: str) -> None:
        with self._lock:
            self.run(
                "MATCH (:QuestionSet {id: $id})<-[:OF]-(:EvalRun)-[:RESULT]->(res:EvalResult) DETACH DELETE res",
                id=set_id,
            )
            self.run("MATCH (:QuestionSet {id: $id})<-[:OF]-(r:EvalRun) DETACH DELETE r", id=set_id)
            self.run("MATCH (:QuestionSet {id: $id})-[:HAS]->(q:Question) DETACH DELETE q", id=set_id)
            self.run("MATCH (qs:QuestionSet {id: $id}) DETACH DELETE qs", id=set_id)

    def _set_rows(self, where: str, **params: Any) -> list[dict[str, Any]]:
        rows = self.run(
            f"""
            MATCH (qs:QuestionSet) {where}
            OPTIONAL MATCH (qs)-[:ABOUT]->(s:Source)
            RETURN qs AS qs, s.id AS source_id, s.name AS source_name
            ORDER BY qs.created_at DESC
            """,
            **params,
        )
        questions = {
            r["id"]: int(r["n"])
            for r in self.run("MATCH (qs:QuestionSet)-[:HAS]->(q:Question) RETURN qs.id AS id, count(q) AS n")
        }
        runs = {
            r["id"]: int(r["n"])
            for r in self.run("MATCH (r:EvalRun)-[:OF]->(qs:QuestionSet) RETURN qs.id AS id, count(r) AS n")
        }
        shaped = []
        for r in rows:
            qs = _node(r["qs"])
            shaped.append(
                _set_row(
                    {
                        "qs": qs,
                        "source_id": r["source_id"],
                        "source_name": r["source_name"],
                        "question_count": questions.get(qs["id"], 0),
                        "run_count": runs.get(qs["id"], 0),
                    }
                )
            )
        return shaped

    def get_question_set(self, set_id: str) -> dict[str, Any] | None:
        rows = self._set_rows("WHERE qs.id = $id", id=set_id)
        return rows[0] if rows else None

    def list_question_sets(self) -> list[dict[str, Any]]:
        return self._set_rows("")

    _QUESTION_COLUMNS = """q.id AS id, q.text AS text, q.expected_answer AS expected_answer,
                   q.gold_passage_ids AS gold_passage_ids, q.kind AS kind, q.notes AS notes, q.ordinal AS ordinal"""

    def list_questions(self, set_id: str) -> list[dict[str, Any]]:
        return self.run(
            f"MATCH (:QuestionSet {{id: $id}})-[:HAS]->(q:Question) RETURN {self._QUESTION_COLUMNS} ORDER BY q.ordinal",
            id=set_id,
        )

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        return self.run_one(
            f"""
            MATCH (qs:QuestionSet)-[:HAS]->(q:Question {{id: $id}})
            RETURN {self._QUESTION_COLUMNS}, qs.id AS set_id, qs.name AS set_name
            """,
            id=question_id,
        )

    # ================================================================ runs

    def create_run(self, set_id: str, name: str, settings: dict[str, Any]) -> str:
        run_id = new_id()
        with self._lock:
            total = self.run_one(
                "MATCH (:QuestionSet {id: $id})-[:HAS]->(q:Question) RETURN count(q) AS n", id=set_id
            )
            self.run(
                """
                MATCH (qs:QuestionSet {id: $set_id})
                CREATE (r:EvalRun {id: $id, name: decode($name), status: 'running', started_at: $now,
                                   settings_json: decode($settings_json), summary_json: '{}', progress_done: 0,
                                   progress_total: $total})
                MERGE (r)-[:OF]->(qs)
                """,
                set_id=set_id,
                id=run_id,
                name=text(name),
                now=now_iso(),
                settings_json=text(json.dumps(settings)),
                total=int(total["n"]) if total else 0,
            )
        return run_id

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "finished_at", "summary_json", "progress_done", "error", "name"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown run fields: {sorted(bad)}")
        self._set("EvalRun", run_id, fields)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.run_one(
            "MATCH (r:EvalRun {id: $id})-[:OF]->(qs:QuestionSet) RETURN r AS r, qs.id AS set_id, qs.name AS set_name",
            id=run_id,
        )
        return _run_row({**row, "r": _node(row["r"])}) if row else None

    def list_runs(self, set_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.run(
            """
            MATCH (r:EvalRun)-[:OF]->(qs:QuestionSet)
            WHERE $set_id IS NULL OR qs.id = $set_id
            RETURN r AS r, qs.id AS set_id, qs.name AS set_name
            ORDER BY r.started_at DESC
            """,
            set_id=set_id,
        )
        return [_run_row({**r, "r": _node(r["r"])}) for r in rows]

    def delete_run(self, run_id: str) -> None:
        with self._lock:
            self.run("MATCH (:EvalRun {id: $id})-[:RESULT]->(res:EvalResult) DETACH DELETE res", id=run_id)
            self.run("MATCH (r:EvalRun {id: $id}) DETACH DELETE r", id=run_id)

    # ============================================================= results

    def add_result(self, run_id: str, question_id: str, result: dict[str, Any]) -> str:
        result_id = new_id()
        self.run(
            """
            MATCH (r:EvalRun {id: $run_id}), (q:Question {id: $question_id})
            CREATE (res:EvalResult {id: $id, answer: decode($answer), thought: decode($thought),
                                    verdict: decode($verdict), judge_score: $judge_score,
                                    judge_reason: decode($judge_reason), exact_match: $exact_match, f1: $f1,
                                    recall_json: decode($recall_json), gold_rank: $gold_rank,
                                    latency_ms: $latency_ms, trace_json: decode($trace_json),
                                    used_dpr_fallback: $used_dpr_fallback, error: decode($error),
                                    created_at: $now})
            MERGE (r)-[:RESULT]->(res)
            MERGE (res)-[:FOR]->(q)
            """,
            run_id=run_id,
            question_id=question_id,
            id=result_id,
            now=now_iso(),
            answer=text(result.get("answer") or ""),
            thought=text(result.get("thought") or ""),
            verdict=text(result.get("verdict") or ""),
            judge_score=_coerce("judge_score", result.get("judge_score")),
            judge_reason=text(result.get("judge_reason") or ""),
            exact_match=_coerce("exact_match", result.get("exact_match")),
            f1=_coerce("f1", result.get("f1")),
            recall_json=text(json.dumps(result.get("recall", {}))),
            gold_rank=_coerce("gold_rank", result.get("gold_rank")),
            latency_ms=_coerce("latency_ms", result.get("latency_ms")),
            trace_json=text(json.dumps(result.get("trace", {}))),
            used_dpr_fallback=bool(result.get("used_dpr_fallback", False)),
            error=text(result.get("error")),
        )
        return result_id

    _RESULT_COLUMNS = """res AS res, q.id AS question_id, q.text AS question, q.expected_answer AS expected_answer,
                   q.kind AS kind, q.gold_passage_ids AS gold_passage_ids, q.ordinal AS ordinal"""

    def list_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.run(
            f"""
            MATCH (:EvalRun {{id: $id}})-[:RESULT]->(res:EvalResult)-[:FOR]->(q:Question)
            RETURN {self._RESULT_COLUMNS}
            ORDER BY q.ordinal
            """,
            id=run_id,
        )
        return [_result_row({**r, "res": _node(r["res"])}, with_trace=False) for r in rows]

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        row = self.run_one(
            f"""
            MATCH (r:EvalRun)-[:RESULT]->(res:EvalResult {{id: $id}})-[:FOR]->(q:Question)
            RETURN {self._RESULT_COLUMNS}, r.id AS run_id, r.name AS run_name
            """,
            id=result_id,
        )
        return _result_row({**row, "res": _node(row["res"])}, with_trace=True) if row else None

    def results_for_question(self, question_id: str) -> list[dict[str, Any]]:
        rows = self.run(
            f"""
            MATCH (r:EvalRun)-[:RESULT]->(res:EvalResult)-[:FOR]->(q:Question {{id: $id}})
            RETURN {self._RESULT_COLUMNS}, r.id AS run_id, r.name AS run_name
            ORDER BY res.created_at DESC
            """,
            id=question_id,
        )
        return [_result_row({**r, "res": _node(r["res"])}, with_trace=False) for r in rows]

    # ========================================================== changesets

    def create_changeset(
        self, name: str, ops: list[dict[str, Any]], from_result_id: str | None = None, note: str = ""
    ) -> str:
        changeset_id = new_id()
        self.run(
            """
            CREATE (c:Changeset {id: $id, name: decode($name), note: decode($note), status: 'draft',
                                 ops_json: decode($ops_json), created_at: $now, from_result_id: $from_result_id})
            """,
            id=changeset_id,
            name=text(name),
            note=text(note or ""),
            ops_json=text(json.dumps(ops)),
            now=now_iso(),
            from_result_id=from_result_id,
        )
        return changeset_id

    def get_changeset(self, changeset_id: str) -> dict[str, Any] | None:
        row = self.run_one("MATCH (c:Changeset {id: $id}) RETURN c AS c", id=changeset_id)
        return _changeset_row({"c": _node(row["c"])}) if row else None

    def list_changesets(self) -> list[dict[str, Any]]:
        rows = self.run("MATCH (c:Changeset) RETURN c AS c ORDER BY c.created_at DESC")
        return [_changeset_row({"c": _node(r["c"])}) for r in rows]

    def delete_changeset(self, changeset_id: str) -> None:
        self.run("MATCH (c:Changeset {id: $id}) DELETE c", id=changeset_id)

    def mark_applied(self, changeset_id: str) -> None:
        self.run(
            "MATCH (c:Changeset {id: $id}) SET c.status = 'applied', c.applied_at = $now",
            id=changeset_id,
            now=now_iso(),
        )

    def set_node_boost(self, entity_id: str, boost: float) -> None:
        """A boost on an entity, symbol or data object. The label comes from the id prefix (S2.2)."""
        label = node_label(entity_id, BOOSTABLE_LABELS)
        if label is None:
            return  # Neo4j's MATCH finds nothing and writes nothing; same here
        self.run(f"MATCH (n:{label} {{id: $id}}) SET n.boost = $boost", id=entity_id, boost=float(boost))

    def set_edge_weight(self, a: str, b: str, weight: float) -> None:
        lo, hi = min(a, b), max(a, b)
        label_a, label_b = node_label(lo, TUNED_LABELS), node_label(hi, TUNED_LABELS)
        if label_a is None or label_b is None:
            return
        with self._lock:
            self.run(
                f"""
                MATCH (a:{label_a} {{id: $a}}), (b:{label_b} {{id: $b}})
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
        label_a, label_b = node_label(lo, TUNED_LABELS), node_label(hi, TUNED_LABELS)
        if label_a is None or label_b is None:
            return
        self.run(f"MATCH (a:{label_a} {{id: $a}})-[t:TUNED]->(b:{label_b} {{id: $b}}) DELETE t", a=lo, b=hi)

    # ================================================================ roles
    # Same behaviour as store/users.py (UserQueries); read that file for the rules.

    def ensure_roles(self) -> None:
        """Seed the default ladder. Existing roles are left exactly as the user edited them."""
        rows = [
            {
                "id": role["id"],
                "name": text(role["name"]),
                "rank": int(role["rank"]),
                "description": text(role["description"]),
                "capabilities": list(role["capabilities"]),
            }
            for role in DEFAULT_ROLES
        ]
        self.run(
            """
            UNWIND $roles AS role
            MERGE (r:Role {id: role.id})
            ON CREATE SET r.name = decode(role.name), r.rank = role.rank, r.description = decode(role.description),
                          r.capabilities = role.capabilities, r.builtin = true
            """,
            roles=rows,
        )

    def _role_counts(self) -> tuple[dict[str, int], dict[str, int]]:
        users = {
            r["id"]: int(r["n"])
            for r in self.run("MATCH (u:User) RETURN u.role_id AS id, count(u) AS n")
            if r["id"]
        }
        sources = {
            r["id"]: int(r["n"])
            for r in self.run("MATCH (s:Source) RETURN s.access_role_id AS id, count(s) AS n")
            if r["id"]
        }
        return users, sources

    def _shape_role(
        self, node: dict[str, Any], counts: tuple[dict[str, int], dict[str, int]]
    ) -> dict[str, Any]:
        role = _node(node)
        users, sources = counts
        return _role_row(
            {"r": role, "users": users.get(role["id"], 0), "sources": sources.get(role["id"], 0)}
        )

    def list_roles(self) -> list[dict[str, Any]]:
        rows = self.run("MATCH (r:Role) RETURN r AS r ORDER BY r.rank DESC, r.name")
        counts = self._role_counts()
        return [self._shape_role(r["r"], counts) for r in rows]

    def get_role(self, role_id: str | None) -> dict[str, Any] | None:
        if not role_id:
            return None
        row = self.run_one("MATCH (r:Role {id: $id}) RETURN r AS r", id=role_id)
        return self._shape_role(row["r"], self._role_counts()) if row else None

    def create_role(
        self, name: str, rank: int, description: str = "", capabilities: list[str] | None = None
    ) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("the role needs a name")
        with self._lock:
            role_id = slug(name)
            if self.get_role(role_id) is not None:
                role_id = f"{role_id}-{new_id()[:4]}"
            self.run(
                """
                CREATE (r:Role {id: $id, name: decode($name), rank: $rank, description: decode($description),
                                capabilities: $capabilities, builtin: false})
                """,
                id=role_id,
                name=text(name),
                rank=clean_rank(rank),
                description=text((description or "").strip()),
                capabilities=clean_capabilities(capabilities),
            )
        return role_id

    def update_role(self, role_id: str, **fields: Any) -> dict[str, Any]:
        """Edit name/rank/description/capabilities. A rank change is copied onto the role's sources."""
        allowed = {"name", "rank", "description", "capabilities"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown role fields: {sorted(bad)}")
        with self._lock:
            if self.get_role(role_id) is None:
                raise ValueError("no such role")
            changes: dict[str, Any] = {}
            if "name" in fields:
                changes["name"] = str(fields["name"]).strip()
                if not changes["name"]:
                    raise ValueError("the role needs a name")
            if "rank" in fields:
                changes["rank"] = clean_rank(fields["rank"])
            if "description" in fields:
                changes["description"] = str(fields["description"] or "").strip()
            if "capabilities" in fields:
                changes["capabilities"] = clean_capabilities(fields["capabilities"])
            if changes:
                self._set("Role", role_id, changes)
            if "rank" in changes:
                self.run(
                    "MATCH (s:Source {access_role_id: $id}) SET s.min_rank = $rank",
                    id=role_id,
                    rank=changes["rank"],
                )
            return self.get_role(role_id)  # type: ignore[return-value]

    def delete_role(self, role_id: str) -> None:
        """Remove a role nobody uses. Refused while a user or a source still names it."""
        with self._lock:
            role = self.get_role(role_id)
            if role is None:
                raise ValueError("no such role")
            if role["users"] or role["sources"]:
                raise ValueError(
                    f"'{role['name']}' is still used by {role['users']} user(s) and {role['sources']} source(s); "
                    "move them to another role first"
                )
            if len(self.list_roles()) <= 1:
                raise ValueError("cannot delete the last role")
            self.run("MATCH (r:Role {id: $id}) DETACH DELETE r", id=role_id)

    # ================================================================ users

    def count_users(self) -> int:
        row = self.run_one("MATCH (u:User) RETURN count(u) AS n")
        return int(row["n"]) if row else 0

    _USER_QUERY = """
        MATCH (u:User) WHERE {where}
        OPTIONAL MATCH (r:Role {{id: u.role_id}})
        OPTIONAL MATCH (s:Source {{owner_id: u.id}})
        RETURN u AS u, r.name AS role_name, coalesce(r.rank, 0) AS rank, count(s) AS sources
        ORDER BY rank DESC, u.username
    """

    def _users(self, where: str, **params: Any) -> list[dict[str, Any]]:
        rows = self.run(self._USER_QUERY.format(where=where), **params)
        return [_user_row({**r, "u": _node(r["u"])}) for r in rows]

    def list_users(self) -> list[dict[str, Any]]:
        return self._users("true")

    def get_user(self, user_id: str | None) -> dict[str, Any] | None:
        if not user_id:
            return None
        rows = self._users("u.id = $value", value=user_id)
        return rows[0] if rows else None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        rows = self._users("u.username = decode($value)", value=text((username or "").strip().lower()))
        return rows[0] if rows else None

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        rows = self._users("u.token = decode($value)", value=text(token))
        return rows[0] if rows else None

    def create_user(self, username: str, password: str, role_id: str, display_name: str = "") -> str:
        username = clean_username(username)
        with self._lock:
            if self.get_user_by_username(username) is not None:
                raise ValueError(f"the username '{username}' is taken")
            if self.get_role(role_id) is None:
                raise ValueError("no such role")
            user_id = new_id()
            self.run(
                """
                CREATE (u:User {id: $id, username: decode($username), display_name: decode($display_name),
                                password_hash: decode($password_hash), token: decode($token), role_id: $role_id,
                                disabled: false, created_at: $now})
                """,
                id=user_id,
                username=text(username),
                display_name=text((display_name or "").strip()),
                password_hash=text(hash_password(password)),
                token=text(new_token()),
                role_id=role_id,
                now=now_iso(),
            )
        return user_id

    def update_user(self, user_id: str, **fields: Any) -> dict[str, Any]:
        """Edit display_name, role_id, disabled or password. Unknown keys are refused."""
        allowed = {"display_name", "role_id", "disabled", "password"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown user fields: {sorted(bad)}")
        with self._lock:
            if self.get_user(user_id) is None:
                raise ValueError("no such user")
            changes: dict[str, Any] = {}
            if "display_name" in fields:
                changes["display_name"] = str(fields["display_name"] or "").strip()
            if "disabled" in fields:
                changes["disabled"] = bool(fields["disabled"])
            if "password" in fields:
                changes["password_hash"] = hash_password(str(fields["password"]))
            if "role_id" in fields:
                if self.get_role(fields["role_id"]) is None:
                    raise ValueError("no such role")
                changes["role_id"] = fields["role_id"]
            if changes:
                self._set("User", user_id, changes)
            return self.get_user(user_id)  # type: ignore[return-value]

    def rotate_token(self, user_id: str) -> str:
        token = new_token()
        self.run("MATCH (u:User {id: $id}) SET u.token = decode($token)", id=user_id, token=text(token))
        return token

    def delete_user(self, user_id: str) -> None:
        """Remove a user. Their sources stay, ownerless (visible by their tier alone)."""
        with self._lock:
            self.run("MATCH (s:Source {owner_id: $id}) SET s.owner_id = NULL", id=user_id)
            self.run("MATCH (u:User {id: $id}) DETACH DELETE u", id=user_id)

    def check_password(self, username: str, password: str) -> dict[str, Any] | None:
        """The user row when the username/password pair is right and the user is not disabled, else None."""
        user = self.get_user_by_username(username)
        if user is None or user.get("disabled"):
            return None
        return user if verify_password(password, user.get("password_hash")) else None

    # ======================================================= source access

    def set_source_access(self, source_id: str, role_id: str | None, owner_id: str | None = ...) -> None:
        """
        Who may see a source: the lowest role (None = everyone) and, optionally, a new owner.
        Pass owner_id to change it (None removes it); leave it out to keep the current owner.
        """
        with self._lock:
            if role_id:
                role = self.get_role(role_id)
                if role is None:
                    raise ValueError("no such role")
                min_rank = int(role["rank"])
            else:
                min_rank = EVERYONE_RANK
            changes: dict[str, Any] = {
                "access_role_id": role_id,
                "min_rank": min_rank,
                "updated_at": now_iso(),
            }
            if owner_id is not ...:
                changes["owner_id"] = owner_id
            self._set("Source", source_id, changes)


__all__ = ["LadybugStore", "StoreLockedError", "text"]
