| id | claim (short) | verdict | key result |
|---|---|---|---|
| T1 | Add scalar columns to populated node table | PASS | Defaults survived two reopens; `ADD IF NOT EXISTS` is idempotent |
| T2 | Create/alter/read/unwind `STRING[]` | PASS | Created and altered list columns survived reopen |
| T3 | FTS or substring search | PARTIAL | FTS install could not use its default extension directory in the scratch-only sandbox; `CONTAINS` and regex work |
| T4 | Add new node/rel tables to existing DB | PASS | Old row and new relationship survived reopen; both DDL statements are idempotent |
| T5 | Typed `STRUCT`, MERGE, 100k-rel queries | PASS | MERGE keyed by `(a,b,kind)`; 100,001-row scan in 0.061 s |
| T6 | Add rel endpoint pair after reopen | PASS | First add and idempotent re-add survived a second reopen |
| T7 | Multi-pair relationship table | PARTIAL | Table and cross-pair reads work; multi-label-pattern `CREATE` is rejected |
| T8 | 50k nodes / 200k rels | PASS | Persisted counts exact; 536.62 s total; 15,249,408 bytes |
| T9 | tree-sitter 0.26 APIs and tolerant parses | PASS | `QueryCursor` required; Python fragment, TS, and TSX/JSX parse cleanly |
| T10 | igraph paths and Leiden | PASS | Directed paths work; `community_leiden` present |
| T11 | git history tools and resolver executables | PASS | All git commands succeed; tsserver/node present, pyright absent |

Environment: macOS arm64, Python 3.12 scratch venv, `real_ladybug==0.15.3`, `tree-sitter==0.26.0`,
`tree-sitter-python==0.25.0`, `tree-sitter-typescript==0.23.2`, and `igraph==1.0.0`.
The requested project command `.venv/bin/pip show real_ladybug` could not run because this uv-created venv
has no `pip` executable. The read-only equivalent `.venv/bin/python -c 'import importlib.metadata as m;
print(m.version("real_ladybug"))'` returned `0.15.3`, which is what the scratch venv installed.
Every database test used a fresh file below `/tmp/hippo-r4-*`, explicitly closed both connection and
database, reopened the same file, queried, and asserted/recorded the persisted result. Nothing under
`data/` or `.venv/` was written.

### T1: scalar `ALTER TABLE` on a populated node table

```python
stmts = [
    "CREATE NODE TABLE Entity(id STRING PRIMARY KEY, name STRING)",
    "CREATE (e:Entity {id: 'e1', name: 'before'})",
    "ALTER TABLE Entity ADD s STRING DEFAULT 'x'",
    "ALTER TABLE Entity ADD i INT64 DEFAULT 7",
    "ALTER TABLE Entity ADD d DOUBLE DEFAULT 1.5",
    "ALTER TABLE Entity ADD b BOOLEAN DEFAULT true",
]
for stmt in stmts: execute(conn, stmt)
close_db(db, conn)
db, conn = reopen(path)
execute(conn, "MATCH (e:Entity {id: 'e1'}) RETURN e.s AS s, e.i AS i, e.d AS d, e.b AS b")
execute(conn, "ALTER TABLE Entity ADD IF NOT EXISTS s STRING DEFAULT 'x'")
close_db(db, conn)
db, conn = reopen(path)
execute(conn, "MATCH (e:Entity {id: 'e1'}) RETURN e.s AS s, e.i AS i, e.d AS d, e.b AS b")
```

Both reopened reads returned `{"s":"x","i":7,"d":1.5,"b":true}`. The guarded re-run succeeded and
returned `Entity table already has property s.` Total wall time: 0.229 s. B's stated need for a
`schema_version` guard because LadybugDB lacks `ADD IF NOT EXISTS` is contradicted by this 0.15.3 binding.

### T2: `STRING[]`

```python
for stmt in [
    "CREATE NODE TABLE N(id STRING PRIMARY KEY, tags STRING[])",
    "CREATE (n:N {id: 'n1', tags: ['alpha', 'beta']})",
    "CREATE NODE TABLE M(id STRING PRIMARY KEY)",
    "CREATE (m:M {id: 'm1'})",
    "ALTER TABLE M ADD tags STRING[] DEFAULT ['legacy']",
]: execute(conn, stmt)
close_db(db, conn)
db, conn = reopen(path)
read = execute(conn, "MATCH (n:N) RETURN n.id AS id, n.tags AS tags")
unwound = execute(conn, "MATCH (n:N) UNWIND n.tags AS tag RETURN tag ORDER BY tag")
altered = execute(conn, "MATCH (m:M) RETURN m.tags AS tags")
```

Results were `['alpha','beta']`, two UNWIND rows `alpha`/`beta`, and `['legacy']` on the pre-existing `M`
row. Total wall time: 0.136 s.

### T3: FTS and fallback string predicates

```python
execute(conn, "CREATE NODE TABLE Doc(id STRING PRIMARY KEY, text STRING)")
execute(conn, "INSTALL FTS")
execute(conn, "LOAD EXTENSION FTS")
execute(conn, "CALL CREATE_FTS_INDEX('Doc', 'doc_fts', ['text'])")
for batch in batches(100_000, 5_000):
    execute(conn, "UNWIND $rows AS row CREATE (:Doc {id: row.id, text: row.text})", rows=batch)
close_db(db, conn)
db, conn = reopen(path)
execute(conn, "MATCH (d:Doc) WHERE d.text CONTAINS 'needle' RETURN count(*) AS n")
execute(conn, "MATCH (d:Doc) WHERE d.text =~ '.*needle.*' RETURN count(*) AS n")
```

Exact extension errors, in order:

```text
RuntimeError: IO exception: Failed to create directory /Users/mascott/.lbdb/extension/0.15.0/osx_arm64/ due to: IO exception: Directory /Users/mascott/.lbdb/extension/0.15.0/osx_arm64 cannot be created. Check if it exists and remove it.
RuntimeError: Binder exception: Extension: fts is an official extension and has not been installed.
You can install it by: install fts.
RuntimeError: Catalog exception: function CREATE_FTS_INDEX is not defined. This function exists in the FTS extension. You can install and load the extension by running 'INSTALL FTS; LOAD EXTENSION FTS;'.
```

This establishes that the binding knows an official FTS extension, but scratch-only constraints prevented
installing it into its hard-coded user extension directory; FTS availability is therefore not proven.
The 100k insert took 0.870 s. After reopen, `CONTAINS` found 100 rows in 0.00449 s and regex found the same
100 in 0.00576 s.

### T4: additive tables in an existing database

```python
execute(conn, "CREATE NODE TABLE Existing(id STRING PRIMARY KEY, value STRING)")
execute(conn, "CREATE (n:Existing {id: 'old', value: 'intact'})")
close_db(db, conn)
db, conn = reopen(path)
execute(conn, "CREATE NODE TABLE IF NOT EXISTS Added(id STRING PRIMARY KEY)")
execute(conn, "CREATE REL TABLE IF NOT EXISTS LINK(FROM Existing TO Added, note STRING)")
execute(conn, "CREATE (n:Added {id: 'new'})")
execute(conn, "MATCH (a:Existing {id: 'old'}), (b:Added {id: 'new'}) CREATE (a)-[:LINK {note: 'ok'}]->(b)")
close_db(db, conn)
db, conn = reopen(path)
execute(conn, "MATCH (a:Existing)-[r:LINK]->(b:Added) RETURN a.value AS value, b.id AS id, r.note AS note")
```

The reopened result was `{"value":"intact","id":"new","note":"ok"}`. Re-running both guarded DDL
statements succeeded with `Table Added already exists.` and `Table LINK already exists.` Total: 0.197 s.

### T5: `STRUCT` properties, MERGE, and 100k relationships

```python
execute(conn, "CREATE NODE TABLE Entity(id STRING PRIMARY KEY)")
execute(conn, "CREATE REL TABLE STRUCT(FROM Entity TO Entity, kind STRING, omega DOUBLE, provenance STRING, line INT64, in_branch BOOLEAN, arg_binding STRING)")
for batch in node_batches(10_000, 5_000):
    execute(conn, "UNWIND $rows AS row CREATE (:Entity {id: row.id})", rows=batch)
for batch in rel_batches(100_000, 5_000):
    execute(conn, "UNWIND $rows AS row MATCH (a:Entity {id: row.a}), (b:Entity {id: row.b}) CREATE (a)-[:STRUCT {kind: decode(row.kind), omega: row.omega, provenance: decode(row.provenance), line: row.line, in_branch: row.in_branch, arg_binding: decode(row.arg_binding)}]->(b)", rows=batch)
merge = "MATCH (a:Entity {id: 'e0'}), (b:Entity {id: 'e1'}) MERGE (a)-[r:STRUCT {kind: 'special'}]->(b) ON CREATE SET r.omega = 0.4, r.provenance = 'first', r.line = 1, r.in_branch = false, r.arg_binding = '{}' ON MATCH SET r.omega = CASE WHEN r.omega < 0.9 THEN 0.9 ELSE r.omega END"
execute(conn, merge); execute(conn, merge)
close_db(db, conn)
db, conn = reopen(path)
execute(conn, "MATCH (:Entity {id:'e0'})-[r:STRUCT {kind:'special'}]->(:Entity {id:'e1'}) RETURN count(*) AS n, max(r.omega) AS omega")
execute(conn, "MATCH (a:Entity)-[r:STRUCT]->(b:Entity) WITH a.id AS a, b.id AS b, max(r.omega) AS omega RETURN count(*) AS pairs, max(omega) AS max_omega")
execute(conn, "MATCH (a:Entity)-[r:STRUCT]->(b:Entity) RETURN a.id AS a, b.id AS b, r.kind AS kind, r.omega AS omega")
```

Free text in parameter lists used bytes plus `decode()`, exactly as `ladybug.py` requires. The 100k insert
took 13.591 s. Repeated MERGE left one `special` edge with omega 0.9, showing `(a,b,kind)` identity. The
best-omega query returned 10,000 endpoint pairs and max 1.0 in 0.00610 s. Materializing the full 100,001
rows took 0.0606 s.

### T6: add a relationship endpoint pair after reopen

```python
execute(conn, "CREATE NODE TABLE A(id STRING PRIMARY KEY)")
execute(conn, "CREATE NODE TABLE B(id STRING PRIMARY KEY)")
execute(conn, "CREATE NODE TABLE C(id STRING PRIMARY KEY)")
execute(conn, "CREATE REL TABLE R(FROM A TO B)")
close_db(db, conn)
db, conn = reopen(path)
execute(conn, "ALTER TABLE R ADD IF NOT EXISTS FROM A TO C")
execute(conn, "ALTER TABLE R ADD IF NOT EXISTS FROM A TO C")
execute(conn, "CREATE (a:A {id:'a'}), (c:C {id:'c'})")
execute(conn, "MATCH (a:A {id:'a'}), (c:C {id:'c'}) CREATE (a)-[:R]->(c)")
close_db(db, conn)
db, conn = reopen(path)
execute(conn, "MATCH (a:A)-[:R]->(x:C) RETURN a.id AS a, x.id AS c")
```

The two ALTER results were `A->C added to table R.` and `A->C already exists in R table.` The second
reopen returned `{a:'a', c:'c'}`. Total: 0.200 s.

### T7: one relationship table spanning multiple node-label pairs

```python
execute(conn, "CREATE NODE TABLE Symbol(id STRING PRIMARY KEY)")
execute(conn, "CREATE NODE TABLE DataObject(id STRING PRIMARY KEY)")
execute(conn, "CREATE REL TABLE CODE_EDGE (FROM Symbol TO Symbol, FROM Symbol TO DataObject, FROM DataObject TO Symbol, kind STRING, omega DOUBLE)")
execute(conn, "MATCH (a:Symbol {id:'s1'}), (b:Symbol {id:'s2'}) CREATE (a)-[:CODE_EDGE {kind:'ss',omega:1.0}]->(b)")
execute(conn, "MATCH (a:Symbol {id:'s1'}), (b:DataObject {id:'d'}) CREATE (a)-[:CODE_EDGE {kind:'sd',omega:0.9}]->(b)")
execute(conn, "MATCH (a:DataObject {id:'d'}), (b:Symbol {id:'s2'}) CREATE (a)-[:CODE_EDGE {kind:'ds',omega:0.8}]->(b)")
execute(conn, "MATCH (a:Symbol|DataObject), (b:Symbol|DataObject) WHERE a.id = 's1' AND b.id = 'd' CREATE (a)-[:CODE_EDGE {kind:'multi',omega:0.7}]->(b)")
close_db(db, conn)
db, conn = reopen(path)
execute(conn, "MATCH (a)-[r:CODE_EDGE]->(b) RETURN label(a) AS a_label, a.id AS a, label(b) AS b_label, b.id AS b, r.kind AS kind ORDER BY kind")
```

The exact requested multi-pair DDL succeeded. All three concrete-label writes persisted and the unlabeled
MATCH returned all three pairs in one query. The multi-label-pattern write failed exactly with:
`RuntimeError: Binder exception: Create rel  bound by multiple node labels is not supported.` Therefore A's
table shape works, but its writer must group rows and issue one statement per concrete label pair.

### T8: row-count scale

```python
for batch in node_batches(50_000, 5_000):
    execute(conn, "UNWIND $rows AS row CREATE (:Entity {id: row.id, name: row.name})", rows=batch)
for batch in rel_batches(200_000, 5_000):
    execute(conn, "UNWIND $rows AS row MATCH (a:Entity {id: row.a}), (b:Entity {id: row.b}) CREATE (a)-[:EDGE {kind: row.kind, omega: row.omega}]->(b)", rows=batch)
close_db(db, conn)
db, conn = reopen(path)
execute(conn, "MATCH (n:Entity) OPTIONAL MATCH (n)-[r:EDGE]->() RETURN count(DISTINCT n) AS nodes, count(r) AS rels")
```

Node insertion: 0.403 s. Relationship insertion: 536.221 s. Total: 536.623 s (8.94 min). Reopened counts
were exactly 50,000 nodes and 200,000 rels. The database files occupied 15,249,408 bytes (14.54 MiB).
The sharp difference from T5's 13.6 s for 100k rels over 10k nodes shows endpoint lookup/write cost is
highly scale-sensitive for this exact `UNWIND` + two `MATCH` ingestion shape.

### T9: tree-sitter 0.26

```python
py = Language(tree_sitter_python.language()); parser = Parser(py)
source = b"def outer(x):\n    return helper(x)\n"
query = Query(py, "(function_definition name: (identifier) @function) (call function: (identifier) @call)")
captures = QueryCursor(query).captures(parser.parse(source).root_node)
fragment = b"kept, raw = filter_fn(question, candidate_triples) if sent else ([], \"\")"
fragment_tree = parser.parse(fragment)
ts_tree = Parser(Language(tree_sitter_typescript.language_typescript())).parse(b"function f(x: number) { return g(x); }")
tsx_tree = Parser(Language(tree_sitter_typescript.language_tsx())).parse(b"const App = () => <div>{callMe()}</div>;")
```

Captures were function `outer` and call `helper`. `Query.captures(...)` raised
`AttributeError: 'tree_sitter.Query' object has no attribute 'captures'`, so `QueryCursor` is required.
The conditional fragment had no error and retained the names `kept`, `raw`, `filter_fn`, `question`,
`candidate_triples`, and `sent`. TypeScript and TSX parsing both had `root_node.has_error == False`; TSX
therefore parses plain JS/JSX. Total: 0.00167 s.

### T10: igraph

```python
g = ig.Graph(n=10_000, edges=edges_40k, directed=True)
g.get_shortest_paths(0, to=[2500, 5000, 7500, 9999], mode="out")
g.get_all_shortest_paths(0, to=5000, mode="out")
g.as_undirected().community_leiden(objective_function="modularity")
```

`get_shortest_paths` returned path lengths 9, 9, 9, 8 in 0.000170 s.
`get_all_shortest_paths` returned two paths in 0.00663 s. `community_leiden` is available and found 18
communities on this synthetic projection in 0.0266 s.

### T11: git and executable availability

```text
git blame --line-porcelain src/hippo/store/ladybug.py                 0.0463 s
git blame --line-porcelain tests/fakes/fake_store.py                 0.0210 s
git blame --line-porcelain tests/unit/test_web_auth.py               0.0211 s
git blame --line-porcelain src/hippo/prompts.py                       0.0141 s
git blame --line-porcelain src/hippo/store/memory.py                  0.0150 s
git log --first-parent -n 200 --numstat --format=%H%x09%P%x09%aI%x09%s  0.0416 s
git show -U0 --format= 172cefa03631f219acda8fb9bce83469fdfbe7ce     0.00985 s
```

The five largest tracked-worktree Python files were selected recursively by byte size, excluding `.git`
and `.venv`; every command exited 0. The `git show` output included the zero-context hunk range
`@@ -1 +1 @@`. PATH results: `pyright` absent; `tsserver` at `/usr/local/bin/tsserver`; `node` at
`/Users/mascott/.nvm/versions/node/v22.9.0/bin/node`.

## What this decides

B's D1 can add `STRING`, `INT64`, `DOUBLE`, `BOOLEAN`, and `STRING[]` columns to populated existing node
tables on `real_ladybug` 0.15.3; defaults persist, and `ALTER TABLE ... ADD IF NOT EXISTS` is directly
available and idempotent. FTS remains unproven under the scratch-only constraint, but both `CONTAINS` and
regex substring predicates work quickly on 100k rows. A's multi-pair `CODE_EDGE` table also works and can
be read across all endpoint pairs in one query. Its only confirmed restriction is that writes cannot bind
either endpoint through a multi-label pattern: the application must resolve/group concrete label pairs.
