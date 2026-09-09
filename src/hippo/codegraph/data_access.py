"""
What the code talks to: tables, columns, collections, graph labels and relationship types.

Everything here reads *in-repo* text only -- a SQL string a function holds, a Mongo call
chain, a Cypher literal, an in-repo `.sql` file. No external DDL is ingested (D9), so a
data object exists only because some file in this source names it.

Two ordering rules that are not obvious and are load-bearing:

* **Cypher is checked before SQL.** `MERGE (s:Settings {id: 1})` starts with a keyword SQL
  also has, so a SQL-first classifier would claim it. A Cypher literal is recognised by its
  node/relationship patterns, which SQL has no syntax for.
* **SQL is only attempted when the literal starts with a SQL statement keyword.** `sqlglot`
  is happy to parse almost any word as an identifier, so handing it every string in a repo
  would turn docstrings into tables.

`sqlglot.parse(..., error_level=IGNORE)` still raises on some inputs, so every call is
wrapped: a literal that does not parse is simply not a data access.
"""

from __future__ import annotations

import logging
import re

from .model import LiteralFact

# sqlglot logs a warning whenever it falls back to parsing something as an opaque command.
# We hand it arbitrary in-repo strings on purpose, so those warnings are noise about our own
# probing, not about the user's data; the result is checked either way.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

# A literal is only handed to sqlglot when it opens with a full statement head. A bare
# keyword prefix is not enough: "Create, edit and remove users." starts with CREATE.
SQL_START = re.compile(
    r"^\s*("
    r"SELECT\s|"
    r"INSERT\s+INTO\s|"
    r"UPDATE\s+\S+\s+SET\b|"
    r"DELETE\s+FROM\s|"
    r"CREATE\s+(OR\s+REPLACE\s+)?(TEMP\s+|TEMPORARY\s+)?(TABLE|VIEW|INDEX|MATERIALIZED\s+VIEW)\s|"
    r"DROP\s+(TABLE|VIEW|INDEX)\s|"
    r"ALTER\s+TABLE\s|"
    r"TRUNCATE\s+(TABLE\s+)?\S|"
    r"REPLACE\s+INTO\s|"
    r"MERGE\s+INTO\s|"
    r"WITH\s+\w+\s+AS\s*\("
    r")",
    re.IGNORECASE,
)
SQL_WRITE_START = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|REPLACE|MERGE)\b", re.IGNORECASE
)

# Cypher: a clause keyword *and* a node or relationship pattern. Either alone is ambiguous.
CYPHER_CLAUSE = re.compile(
    r"\b(OPTIONAL\s+MATCH|DETACH\s+DELETE|MATCH|MERGE|CREATE|UNWIND|RETURN|SET|REMOVE|DELETE)\b"
)
CYPHER_WRITE = re.compile(r"\b(CREATE|MERGE|SET|DELETE|REMOVE)\b")
CYPHER_NODE = re.compile(r"\(\s*\w*\s*:\s*([A-Za-z_]\w*)")
CYPHER_REL = re.compile(r"\[\s*\w*\s*:\s*([A-Za-z_]\w*)")

# Mongo/Mongoose method names: snake_case (pymongo, the Rust `mongodb` crate), camelCase
# (mongoose) and PascalCase (the Go driver, `MongoDB.Driver`). Deliberately narrow: `save`,
# `remove` and `create` are left out because they are ordinary method names everywhere else
# and would invent edges. A trailing `Async` is stripped before the lookup, not spelled out
# here -- `FindAsync` and `InsertOneAsync` are the same two names with C# ceremony on them.
MONGO_READS = frozenset(
    {
        "find", "find_one", "findOne", "aggregate", "distinct", "count_documents",
        "countDocuments", "estimated_document_count", "estimatedDocumentCount", "findById",
        "Find", "FindOne", "Aggregate", "CountDocuments", "Distinct",
    }
)  # fmt: skip
MONGO_WRITES = frozenset(
    {
        "insert_one", "insert_many", "insertOne", "insertMany", "update_one", "update_many",
        "updateOne", "updateMany", "delete_one", "delete_many", "deleteOne", "deleteMany",
        "replace_one", "replaceOne", "bulk_write", "bulkWrite", "find_one_and_update",
        "findOneAndUpdate", "find_one_and_delete", "findOneAndDelete", "findByIdAndUpdate",
        "InsertOne", "InsertMany", "UpdateOne", "UpdateMany", "DeleteOne", "DeleteMany",
        "ReplaceOne", "BulkWrite",
    }
)  # fmt: skip

# The last link of a collection chain when it is a *call* rather than an attribute:
# `client.Database("app").Collection("orders")` (Go), `GetCollection<Order>("orders")` (C#),
# `collection::<Order>("orders")` (Rust), `db.get_collection("orders")` (pymongo). Only
# consulted when the plain `db.orders` shape did not already name the collection.
COLLECTION_MARKER = re.compile(
    r"^(?:get_collection|getCollection|GetCollection|Collection|collection)"
    r"(?:::)?(?:<[^<>]*>)?\(\s*[\"'`]([A-Za-z_]\w*)[\"'`]\s*(?:,[^)]*)?\)$"
)

READS, WRITES = "READS", "WRITES"


class Hit:
    """One data access a literal or call chain implies. Plain class: it is a tuple with names."""

    __slots__ = ("kind", "qualname", "dialect", "access", "provenance", "line")

    def __init__(self, kind: str, qualname: str, dialect: str, access: str, provenance: str, line: int = 0):
        self.kind = kind
        self.qualname = qualname
        self.dialect = dialect
        self.access = access
        self.provenance = provenance
        self.line = line

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Hit({self.kind}, {self.qualname!r}, {self.access}, {self.provenance})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Hit) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def _key(self):
        return (self.kind, self.qualname, self.dialect, self.access, self.provenance, self.line)


# --------------------------------------------------------------- Cypher


def cypher_objects(text: str) -> list[Hit]:
    """Labels and relationship types in a Cypher literal, in first-seen order."""
    if not (CYPHER_NODE.search(text) or CYPHER_REL.search(text)) or not CYPHER_CLAUSE.search(text):
        return []
    access = WRITES if CYPHER_WRITE.search(text) else READS
    hits: list[Hit] = []
    seen: set[tuple[str, str]] = set()
    for pattern, kind in ((CYPHER_NODE, "label"), (CYPHER_REL, "rel_type")):
        for match in pattern.finditer(text):
            name = match.group(1)
            if (kind, name) in seen:
                continue
            seen.add((kind, name))
            hits.append(Hit(kind, name, "cypher", access, "cypher_literal"))
    return hits


# ------------------------------------------------------------------ SQL


def sql_tables(text: str) -> list[Hit]:
    """
    Tables a SQL literal reads or writes. Returns [] for anything that does not open with a
    SQL statement keyword or does not parse -- both are ordinary, not errors.
    """
    if not SQL_START.match(text) or _reads_like_a_sentence(text):
        return []
    statements = _parse_sql(text)
    if not statements:
        return []
    default = WRITES if SQL_WRITE_START.match(text) else READS
    hits: list[Hit] = []
    seen: set[tuple[str, str]] = set()
    for statement in statements:
        for name, access in _tables_of(statement, default):
            if (name, access) in seen:
                continue
            seen.add((name, access))
            hits.append(Hit("table", name, "sql", access, "sql_literal"))
    return hits


def _reads_like_a_sentence(text: str) -> bool:
    """
    The second half of the SQL guard. "Select a source from the list." clears the statement
    head *and* parses -- sqlglot reads `the list` as a table with an alias -- so the table
    `the` would appear in a user's graph. A SQL literal ends with `;` or with nothing; it
    does not end with a full stop.
    """
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in ".!?"


def _parse_sql(text: str):
    """`sqlglot.parse` with errors ignored, and wrapped: IGNORE is not "never raises"."""
    try:
        import sqlglot
        from sqlglot.errors import ErrorLevel

        return [s for s in sqlglot.parse(text, error_level=ErrorLevel.IGNORE) if s is not None]
    except Exception:  # noqa: BLE001 - an unparseable literal is not a data access
        return []


def _tables_of(statement, default: str) -> list[tuple[str, str]]:
    """
    Every table in one statement, with the access it gets. An INSERT/UPDATE/DELETE writes its
    target and reads everything else it joins, so `INSERT INTO a SELECT * FROM b` is honest.
    """
    from sqlglot import exp

    try:
        target = ""
        if isinstance(statement, exp.Insert | exp.Update | exp.Delete):
            into = statement.this
            table = into.find(exp.Table) if isinstance(into, exp.Expression) else None
            target = table.name if table is not None else ""
        found: list[tuple[str, str]] = []
        for table in statement.find_all(exp.Table):
            name = table.name
            if not name:
                continue
            found.append((name, (WRITES if name == target else READS) if target else default))
        return found
    except Exception:  # noqa: BLE001 - a half-parsed statement is not a data access
        return []


def read_sql_file(text: str) -> list[Hit]:
    """
    A whole in-repo `.sql` file: its `CREATE TABLE`s become tables, their declared columns
    become `table.column` data objects. Line numbers are the statement's line in the file.
    """
    hits: list[Hit] = []
    seen: set[tuple[str, str]] = set()
    for statement, line in _statements_with_lines(text):
        for parsed in _parse_sql(statement):
            hits.extend(_ddl_hits(parsed, line, seen))
    return hits


def _ddl_hits(statement, line: int, seen: set[tuple[str, str]]) -> list[Hit]:
    from sqlglot import exp

    try:
        return _ddl_rows(statement, line, seen, exp)
    except Exception:  # noqa: BLE001 - a half-parsed statement is not a schema
        return []


def _ddl_rows(statement, line: int, seen: set[tuple[str, str]], exp) -> list[Hit]:
    hits: list[Hit] = []
    is_create = isinstance(statement, exp.Create)
    for table in statement.find_all(exp.Table):
        name = table.name
        if not name or ("table", name) in seen:
            continue
        seen.add(("table", name))
        hits.append(Hit("table", name, "sql", WRITES, "sql_literal", line))
        if not is_create:
            continue
        schema = statement.this
        if not isinstance(schema, exp.Schema):
            continue
        for column in schema.expressions:
            column_name = column.name if hasattr(column, "name") else ""
            if not column_name or ("column", f"{name}.{column_name}") in seen:
                continue
            seen.add(("column", f"{name}.{column_name}"))
            hits.append(Hit("column", f"{name}.{column_name}", "sql", WRITES, "sql_literal", line))
    return hits


def _statements_with_lines(text: str) -> list[tuple[str, int]]:
    """Split a `.sql` file on `;`, keeping each statement's 1-based start line."""
    statements: list[tuple[str, int]] = []
    line, start = 1, 0
    for index, char in enumerate(text):
        if char != ";":
            continue
        chunk = text[start : index + 1]
        stripped = chunk.strip()
        if stripped:
            statements.append((stripped, line + _leading_blank_lines(chunk)))
        line += chunk.count("\n")
        start = index + 1
    tail = text[start:].strip()
    if tail:
        statements.append((tail, line + _leading_blank_lines(text[start:])))
    return statements


def _leading_blank_lines(chunk: str) -> int:
    return len(chunk) - len(chunk.lstrip("\n")) if chunk.startswith("\n") else 0


# ---------------------------------------------------------------- Mongo


def mongo_method(name: str) -> str:
    """
    The driver method a call name means. `InsertOneAsync` is `InsertOne` with C# ceremony on
    it, so the `Async` comes off before the sets are consulted rather than being spelled
    twice in them.
    """
    return name.removesuffix("Async") if name.endswith("Async") else name


def collection_of(receiver: str) -> str:
    """
    The collection the last link of a chain names: `db.archive_orders` -> `archive_orders`,
    `client.Database("app").Collection("archive_orders")` -> `archive_orders`. "" when the
    chain does not name one, which is every ordinary `a.b()` call.
    """
    if "." not in receiver:
        return ""
    last = receiver.rsplit(".", 1)[1]
    if last.isidentifier():
        return last
    found = COLLECTION_MARKER.match(last)
    return found.group(1) if found is not None else ""


def mongo_hit(receiver: str, name: str, line: int = 0) -> Hit | None:
    """
    `db.archive_orders.insert_one(...)` -> the collection `archive_orders`, written.
    The receiver must be a chain (`a.b`), so a bare `x.find()` invents nothing.
    """
    collection = collection_of(receiver)
    if not collection:
        return None
    method = mongo_method(name)
    if method in MONGO_WRITES:
        return Hit("collection", collection, "mongo", WRITES, "mongo_chain", line)
    if method in MONGO_READS:
        return Hit("collection", collection, "mongo", READS, "mongo_chain", line)
    return None


def mongoose_hit(collection: str, name: str, line: int = 0) -> Hit | None:
    """A call on a known `mongoose.model("Order", ...)` binding: `OrderModel.find({})`."""
    method = mongo_method(name)
    if method in MONGO_WRITES:
        return Hit("collection", collection, "mongo", WRITES, "mongoose_model", line)
    if method in MONGO_READS:
        return Hit("collection", collection, "mongo", READS, "mongoose_model", line)
    return None


# ------------------------------------------------------------- literals


def classify_literal(text: str) -> list[Hit]:
    """
    What one string literal names, if anything. **Cypher first** -- see the module docstring.
    Returns [] for the overwhelming majority of strings, which is the point.
    """
    hits = cypher_objects(text)
    return hits if hits else sql_tables(text)


def collect(literals: list[LiteralFact]) -> list[tuple[str, Hit]]:
    """`(caller qualname, hit)` for every literal in a file that names something."""
    found: list[tuple[str, Hit]] = []
    for literal in literals:
        for hit in classify_literal(literal.text):
            hit.line = literal.line
            found.append((literal.caller, hit))
    return found
