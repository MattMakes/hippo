# R1 — Store layer, schema, GraphIndex, access: verification report

## Verdict table

| id | claim (short) | verdict | key file:line |
|---|---|---|---|
| R1.1 | `store/base.py` is an abstract base/Protocol shared by all backends | Contradicted | `store/base.py:108` |
| R1.2 | Full node/rel schema is as A describes, with a migration mechanism already in place | Partial | `store/ladybug.py:67-115` |
| R1.3 | `remove_orphans` sweeps mention-less/state-less nodes only, ignoring TUNED/SYNONYM | Built | `store/ladybug.py:525-527` |
| R1.4 | Row shapes are plain dicts; an extra column is safe everywhere | Partial | `hipporag/graph_index.py:125-172` |
| R1.5 | Entity vs Passage is the only label `GraphIndex` knows; a `kind` column rides along free | Partial | `hipporag/graph_index.py:31-32,104` |
| R1.6 | `ACCESS_WHERE` + `scoped()` is the two-place access rule | Built | `access.py:123`, `hipporag/graph_index.py:297-397` |
| R1.7 | Settings page hard-codes `max="1"` on a float input | Built | `web/templates/settings.html:76` |
| R1.8 | Existing id schemes wouldn't collide with A's/B's symbol id proposals | Built | `hipporag/text.py:27-39` |
| R1.9 | Side tables (changesets/evals/users) show the conventional way to add a table | Built | `store/changesets.py:1-14`, `store/evals.py:14-32` |
| R1.10 | There is an FTS index or extension backing entity/name search today | Missing | `store/ladybug.py:663-677` |
| R1.11 | TUNED/SYNONYM do not survive a source losing its last mention | Built | `store/ladybug.py:525-527` |
| R1.12 | Every LadybugDB method has a name-identical Neo4j (`memory.py`) and FakeStore counterpart today | Built | `store/memory.py` vs `store/ladybug.py` vs `tests/fakes/fake_store.py` |

---

### R1.1: `store/base.py` is an abstract base/Protocol shared by all three backends
**Source:** A §(Context, "LadybugDB, Neo4j, FakeStore"); B §1 ("`store/base.py`+`memory.py`" is the Neo4j path)
**Evidence:** `src/hippo/store/base.py:108` — `class Neo4jBase:` (docstring: `"""Connecting to Neo4j, running queries, and the handful of global records (settings, stats)."""`, line 1). `src/hippo/store/__init__.py:54` — `class Store(MemoryQueries, EvalQueries, ChangesetQueries, UserQueries, Neo4jBase):`
**Verdict:** Contradicted
**Implication for the plan:** `store/base.py` is not a Protocol/ABC — it is the Neo4j connection/settings/stats class that every Neo4j-side mixin (`memory.py`, `evals.py`, `changesets.py`, `users.py`) inherits from. `LadybugStore` (in `ladybug.py`) is a wholly separate, self-contained class implementing every method itself (not inheriting from `Neo4jBase` or any shared interface) — parity across the two real backends and `FakeStore` is enforced only by convention and by `tests/unit/test_store*.py` running against all three, not by any type-level contract. Any WP1 module (e.g. a `CodeQueries` mixin) added to `Store`'s bases in `store/__init__.py` must be written twice more, once verbatim into `LadybugStore` and once into `FakeStore`, exactly as A's WP1.1 already assumes.

### R1.2: Node/rel schema and a migration mechanism
**Source:** A §1.2 (`NODE_TABLES`/`REL_TABLES` growth, `ALTER TABLE ... ADD IF NOT EXISTS`, `schema_version` contingency); B §11 (`ensure_schema` guarded by a `schema_version` meta key)
**Evidence:**
```
store/ladybug.py:67   NODE_TABLES: dict[str, str] = {
store/ladybug.py:98   REL_TABLES: list[tuple[str, str, str]] = [
store/ladybug.py:270  def ensure_schema(self) -> None:
store/ladybug.py:274      self.run(f"CREATE NODE TABLE IF NOT EXISTS {name}({columns})")
store/ladybug.py:276      self.run(f"CREATE REL TABLE IF NOT EXISTS {name}({pairs}{extra})")
```
Full current tables: `Source, Passage, Entity, Fact, QuestionSet, Question, EvalRun, EvalResult, Changeset, Settings, Role, User` (12 node tables, `ladybug.py:67-95`); rels `FROM, MENTIONS, STATES, SUBJECT, OBJECT, SYNONYM, TUNED, ABOUT, HAS, OF, RESULT, FOR` (`ladybug.py:98-115`). `grep -rn "ALTER TABLE\|schema_version" src/hippo tests` returns **zero** hits anywhere in the repo.
**Verdict:** Partial
**Implication for the plan:** Every table/column A and B want to add is additive to a real, fully-enumerable schema (good news for both). But neither an `ALTER TABLE ... ADD IF NOT EXISTS` pattern nor a `schema_version`-gated rebuild exists today in either store — `ensure_schema` only ever does `CREATE ... IF NOT EXISTS`. A's WP1.2 contingency plan (rename/create-wide/copy/drop) and B's "`ALTER TABLE … ADD` guarded by a `schema_version` meta key" are both **new mechanisms**, not extensions of something already proven; A's own "Verified on this machine" note that `ALTER TABLE` is untested across a close/reopen is the accurate framing — this needs its own first test (as A's WP1.5 already says: "write first").

### R1.3: `remove_orphans` — what it deletes and when it runs
**Source:** B §1 ("Overrides that survive re-indexing: Gap", citing `memory.py:175`, `ladybug.py:525`)
**Evidence:**
```
store/memory.py:175   def remove_orphans(self) -> None:
store/memory.py:176       self.run("MATCH (f:Fact) WHERE NOT (f)<-[:STATES]-() DETACH DELETE f")
store/memory.py:177       self.run("MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e")

store/ladybug.py:525   def remove_orphans(self) -> None:
store/ladybug.py:526       self.run("MATCH (f:Fact) WHERE NOT EXISTS { MATCH (f)<-[:STATES]-(:Passage) } DETACH DELETE f")
store/ladybug.py:527       self.run("MATCH (e:Entity) WHERE NOT EXISTS { MATCH (e)<-[:MENTIONS]-(:Passage) } DETACH DELETE e")
```
B's line numbers are exact. The predicate checks **only** `MENTIONS`/`STATES` — `TUNED` and `SYNONYM` never appear in either query.
**Verdict:** Built
**Implication for the plan:** (a) an Entity with only a `TUNED` edge and no `MENTIONS` **is deleted** (`DETACH DELETE` also drops its `TUNED` edges); (b) a hypothetical `DEFINES`-only entity would likewise be swept, since only `MENTIONS` counts; (c) a `SYNONYM`-only entity is swept too. `remove_orphans` is called from **both** `delete_source` (`memory.py:122`, `ladybug.py:493`) and `delete_passages_for_source` (`memory.py:138`, `ladybug.py:498`), and `ingest/pipeline.py:396` confirms `reindex` goes through `delete_passages_for_source` — so re-indexing a source *does* run `remove_orphans` today. A's plan text "`remove_orphans` is unchanged (never sweeps code nodes or commits)" is correct only because Symbol/DataObject/Commit would be separate labels the query never matches; it does **not** protect an `Entity` used as a symbol (B's D1 shape) unless `remove_orphans` itself is changed to also check `DEFINES`.

### R1.4: Row shapes and the `_rows_with_good_vectors` guard
**Source:** B §11 ("`load_entities`/`load_facts` return the new columns... The `_rows_with_good_vectors` guard already tolerates rows without embeddings")
**Evidence:**
```
hipporag/graph_index.py:125  entity_rows = sorted(store.load_entities(), key=lambda r: (r.get("created_at") or "", r["id"]))
hipporag/graph_index.py:130  passage_rows = _rows_with_good_vectors(passage_rows, "passage")
hipporag/graph_index.py:423  def _rows_with_good_vectors(rows: list[dict], kind: str) -> list[dict]:
```
`load_entities` returns `{id, name, boost, passage_count, created_at}` (`memory.py:401-408`); `load_passages` returns `{id, title, text, ordinal, embedding, source_id, source_name}` (`memory.py:410-417`); `load_facts` returns `{id, subject, predicate, object, subject_id, object_id, embedding, passage_ids}` (`memory.py:419-427`). All consumption in `graph_index.py` is by dict key (`r["id"]`, `r.get("boost")`), never positional or exhaustive-key.
**Verdict:** Partial
**Implication for the plan:** Runtime code tolerates an extra column with a default fine — no positional access or key-set assertions exist in `graph_index.py`/`retriever.py`. But the test suite does assert exact key sets on **other** aggregate dicts that a code-graph addition would grow: `tests/unit/test_store.py:107` — `assert set(store.stats()) == keys` (11 keys today) — and `tests/unit/test_indexer.py` has **six** exact-equality assertions on `index_source`'s returned counts dict (lines 55, 98, 212-222, 238, 317: `{"passages", "entities", "facts", "synonyms"}`), not the "two" A's plan estimates. Every one of these must be updated when `stats()`/`index_source()` grow new keys.

### R1.5: `GraphIndex` vertex model, `Edge`, `weight`, node specificity
**Source:** A §"Reconciled interface decisions" (`specificity` alias `entity_passage_count`); B D1 ("no change to `GraphIndex`'s vertex model")
**Evidence:**
```
hipporag/graph_index.py:31-32   ENTITY = "entity"; PASSAGE = "passage"
hipporag/graph_index.py:69-73   @property
                                 def weight(self) -> float:
                                     if self.tuned is not None:
                                         return self.tuned
                                     return max(float(self.fact_count), 1.0 if self.mention else 0.0, self.synonym_score)
hipporag/graph_index.py:104     entity_passage_count: np.ndarray  # per vertex: how many passages mention this entity (node specificity)
```
`node_ids = entities... + passages...` (`load()`, line 133); vertex order is entities-then-passages, exactly as both plans assume. `grep -n "specificity" hipporag/graph_index.py` finds no field literally named `specificity` — only `entity_passage_count`; A's "alias property" framing describes a rename that has not happened yet, not something already there.
**Verdict:** Partial
**Implication for the plan:** `node_kind` genuinely has only two values today (confirmed: `web/routes/graph.py` branches everywhere with `if index.node_kind[v] == ENTITY else ...`, never a third case), so B's claim that a `kind` column can ride on an `Entity` row with zero change to the **igraph vertex/edge/weight** machinery is accurate. It is *not* true that this is "zero changes overall": `GraphIndex` currently exposes only `entity_names: dict[id, name]` per entity — there is no per-vertex slot for `kind`/`symbol_kind`/`path` etc. — so `routes/graph.py`'s "Kind filter" (`graph.py:140`: `if kind and index.node_kind[v] != kind`) filters on the *vertex* kind only and cannot distinguish a symbol-Entity from a phrase-Entity without new fields on `GraphIndex` itself (which B's own §9 UI section implicitly acknowledges by saying the filter "gains 'symbol'").

### R1.6: Access — `ACCESS_WHERE`, entity visibility via mentions, `scoped()`
**Source:** A/B assume the existing access rule extends unchanged to symbols
**Evidence:**
```
access.py:123   ACCESS_WHERE = "($acc_all OR s.owner_id = $acc_uid OR coalesce(s.min_rank, 0) <= $acc_rank)"
store/memory.py:280  WITH e, count { (e)<-[:MENTIONS]-(:Passage)-[:FROM]->(s:Source) WHERE {ACCESS_WHERE} } AS passage_count
hipporag/graph_index.py:317-327  # Entities stay only when a visible passage mentions them (a mention edge to a kept passage).
context.py:123  scoped = full.scoped(visible)
```
`Access.can_see_source` (`access.py:110-116`) mirrors `ACCESS_WHERE` in Python for the FakeStore/in-memory path. `context.py:106-128` (`AppContext.graph_for`) computes `visible = frozenset(row["id"] for row in self.store.list_sources(access))` then calls `full.scoped(visible)`.
**Verdict:** Built
**Implication for the plan:** The rule is genuinely "a node is visible iff a visible passage mentions/states it," enforced identically in Cypher (`ACCESS_WHERE` bound to `s:Source`, a property check, not a second join) and in `GraphIndex.scoped()` (mention-edge walk, `graph_index.py:318-327`). A symbol modeled as an Entity (B's D1) or via a new `source_id` property directly on `Symbol`/`DataObject` (A's WP1.2, "a property, not a FROM rel") both fit this pattern without a new join path — A's stated reason ("one-statement deletion, no second join path") matches how `ACCESS_WHERE` is written today.

### R1.7: Settings — `DEFAULT_SETTINGS`, `SETTING_RULES`, the hard-coded `max="1"`
**Source:** A §3.1 ("the settings page hard-codes `max=\"1\"`")
**Evidence:**
```
store/base.py:13-21   DEFAULT_SETTINGS = {"linking_top_k": 5, "passage_node_weight": 0.05, "damping": 0.5,
                        "node_specificity": True, "synonymy_threshold": 0.8, "retrieval_top_k": 200, "qa_top_k": 5}
store/base.py:24-32   SETTING_RULES = {"linking_top_k": (int, 0, 100), "passage_node_weight": (float, 0.0, 10.0),
                        "damping": (float, 0.0, 1.0), "node_specificity": (bool, None, None),
                        "synonymy_threshold": (float, 0.0, 1.0), "retrieval_top_k": (int, 1, 5000), "qa_top_k": (int, 1, 50)}
web/templates/settings.html:76   <input type="number" ... value="{{ value }}" min="0" max="1" step="0.01">
```
**Verdict:** Built
**Implication for the plan:** Confirmed exactly: every non-bool, non-integer setting gets the same `min="0" max="1"` input regardless of its real range in `SETTING_RULES`. Today this silently mis-scopes only `passage_node_weight` (real max 10.0) in the browser's spinner/slider (the backend `validate_settings` still enforces the real range server-side, so this is a UI-only clamp, not a data bug). Any new float setting the plan adds with a max above 1 (e.g. a `structural_scale` with headroom, or `omega_threshold` which happens to be 0-1 and would be unaffected) needs this template fixed or it inherits the same silent clamp.

### R1.8: Ids — `make_id`, `entity_id`, `fact_id`, `passage_id`, and collisions
**Source:** A ("`symbol-` + md5(`source_id:path:qualname`)"); B ("`symbol-` + md5(`repo_source_id:qualname`)")
**Evidence:**
```
hipporag/text.py:27-29   def make_id(prefix: str, content: str) -> str:
                             return prefix + hashlib.md5(content.encode("utf-8")).hexdigest()
hipporag/text.py:32-34   def entity_id(name: str) -> str:
                             return make_id("entity-", name)
hipporag/text.py:37-39   def fact_id(subject: str, predicate: str, obj: str) -> str:
                             return make_id("fact-", f"{subject}\t{predicate}\t{obj}")
hipporag/indexer.py:60-61   def passage_id(source_id: str, chunk: Chunk) -> str:
                                 return make_id("passage-", f"{source_id}:{chunk.ordinal}:{chunk.text}")
```
`grep -rn "split_identifier\|symbol_id\|data_id(" src/hippo` outside the plans finds nothing — none of these exist yet.
**Verdict:** Built
**Implication for the plan:** No collision either way: `entity-`/`fact-`/`passage-` prefixes are disjoint from the proposed `symbol-`/`data-`/`commit-` prefixes, and `make_id` is a plain string-prefixed md5 with no shared namespace to clash in. But note an asymmetry worth flagging to the synthesizer: `entity_id`/`fact_id` are **not** namespaced by source (identical phrases across two different sources hash to the same entity, which is intentional — entities are shared memory), while `passage_id` **is** namespaced by `source_id`. A's `symbol_id(source_id, path, qualname)` follows the passage convention (namespaced, never merges across repos); B's `symbol-` + md5(`repo_source_id:qualname`) does too. If B instead literally reuses the `Entity` table for symbols (D1), a symbol id being source-namespaced while ordinary phrase-entity ids are not is a real inconsistency within one node table that the synthesizer should decide on explicitly, not inherit by accident.

### R1.9: Side tables — changesets, evals, users
**Source:** A §1.1/1.2 (new `Override`/`Unresolved`/`BindingRule`-style tables); B §4.1 (same tables, as new node tables)
**Evidence:**
```
store/changesets.py:1-14   """... A changeset is a list of small operations, stored as JSON until you apply it: ..."""
store/changesets.py:31-33  CREATE (c:Changeset {id: $id, name: $name, note: $note, status: 'draft', ops_json: $ops_json, ...})
store/evals.py:1            """Queries for evaluation: question sets, runs, and per-question results (with their retrieval traces)."""
store/evals.py:17-19        CREATE (qs:QuestionSet {id: $id, name: $name, origin: $origin, status: 'ready', ...})
store/ladybug.py:1030-1059  def add_result(...): ... trace_json: decode($trace_json) ... trace_json=text(json.dumps(result.get("trace", {})))
```
`Trace.to_dict()` is `dataclasses.asdict(self)` (`hipporag/retriever.py:127-128`) — the **entire** `Trace` (question, settings, graph_version, fact_candidates, filter, seed_entities, seed_passages, top_nodes, passages, timing_ms) is what gets JSON-serialized into `EvalResult.trace_json`.
**Verdict:** Built
**Implication for the plan:** Two conventions already coexist in this codebase: `changesets.py` stores an arbitrary op list as one JSON blob on a single node (no new node table per op kind), while `evals.py`/`users.py` add genuine new node tables (`QuestionSet`, `Question`, `EvalRun`, `EvalResult`, `Role`, `User`) plus new rel tables (`ABOUT`, `HAS`, `OF`, `RESULT`, `FOR`) declared in `NODE_TABLES`/`REL_TABLES`/`CONSTRAINTS`. B's `Override`/`Unresolved`/`BindingRule` as dedicated node tables follows the evals.py/users.py precedent, not the changesets.py precedent — which is the more common pattern in this codebase for anything queried/filtered independently (as `Override`/`Unresolved` would be, per B's own leaderboard and stale-badge UI).

### R1.10: Full-text / substring search on entity names
**Source:** B §11 (`search_symbols(q, access) -> rows ... FTS on both backends`)
**Evidence:**
```
store/base.py:82-83   # A TEXT index (not the default RANGE one) is what `CONTAINS` searches can use.
                       "CREATE TEXT INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)"
store/memory.py:292-303   MATCH (e:Entity) WHERE e.name CONTAINS $text ...
store/ladybug.py:663-677  def search_entities(self, text_: str, ...): MATCH (e:Entity) WHERE e.name CONTAINS decode($needle) ...
```
`web/routes/api.py:104-109` — `GET /entities` calls `store.search_entities(...)`, the only name-search entry point (Graph page picker, Ask page entity autocomplete).
**Verdict:** Missing
**Implication for the plan:** Neo4j has a declared `TEXT INDEX` to accelerate `CONTAINS`, but that is a plain substring scan speedup, not tokenized/fuzzy full-text search, and LadybugDB has **no** index at all backing its identical `CONTAINS` query (no `CREATE_FTS_INDEX`-style call anywhere in the file; `grep -rn "FTS\|fulltext"` across `src/hippo` returns nothing). B's proposed `search_symbols` with "FTS on both backends" is new work on both stores, not an extension of an existing FTS layer — today's "search" is a linear substring match with no ranking beyond `passage_count DESC, name`.

### R1.11: `TUNED`/`SYNONYM` persistence across a re-index
**Source:** B §1 ("Overrides that survive re-indexing: Gap ... `TUNED` edges hang off entity nodes; `remove_orphans` ... `DETACH DELETE`s an entity that loses its last mention, taking its tuned edges with it")
**Evidence:** Same `remove_orphans` citations as R1.3. Writers: `set_edge_weight`/`clear_edge_weight` (`store/changesets.py:66-83`, `store/ladybug.py:1146-1168`); `add_synonyms` (`store/memory.py:379-395`, `store/ladybug.py:758-788`). Readers: `load_tuned_edges` (`memory.py:449-450`), `load_synonyms` (`memory.py:444-447`), both fed into `GraphIndex.load()` at `graph_index.py:191-198`.
**Verdict:** Built
**Implication for the plan:** `reindex` (via `delete_passages_for_source`, `ingest/pipeline.py:395-396`) never touches `TUNED`/`SYNONYM` directly — but it deletes the source's passages, and `remove_orphans` immediately after can delete an `Entity` (and thus its `TUNED`/`SYNONYM` edges by `DETACH DELETE`) if that entity loses its last `MENTIONS`. Confirmed: this is exactly the gap B describes, and it is real today for ordinary prose entities, not a hypothetical introduced by code. Whatever persistence model wins (A's per-node-kind widening, or B's separate `Override` table with re-application "at link time") needs a fix for this even without any code-graph work, since it already affects prose overrides.

### R1.12: LadybugDB/Neo4j/FakeStore method parity today
**Source:** A/B both require name-for-name parity going forward
**Evidence:** Automated diff of `def <name>(` at one-indent level across all three files finds **zero** methods present in `memory.py` but missing (by name) from `ladybug.py`, and **zero** missing from `tests/fakes/fake_store.py`. Representative set: `create_source, get_source, list_sources, delete_source, delete_passages_for_source, remove_orphans, add_passages, add_entities, get_entities, search_entities, load_entity_embeddings, add_facts, get_facts, link_passage_facts, link_passage_entities, add_synonyms, load_entities, load_passages, load_facts, load_fact_edges, load_mentions, load_synonyms, load_tuned_edges`.
**Verdict:** Built
**Implication for the plan:** The "name-for-name, row-for-row" parity A and B both assume as a starting condition is real today, mechanically checkable (a simple `def` name diff), and worth keeping as a CI-style sanity check once `add_symbols`/`add_code_edges`/etc. land on all three stores — it would have caught, cheaply, any of the three backends silently drifting.

---

## Surprises and gotchas for the synthesizer

1. **`store/base.py` naming is a trap.** Its docstring literally says "Connecting to Neo4j" — it is *the* Neo4j backend's base class, not a shared contract. A reader (or an agent) skimming file names alone will assume `base.py` is backend-agnostic; it is the opposite of `ladybug.py`, which is the one that duplicates everything.

2. **Hard-coded multi-label patterns already exist, not just hypothetically.** `store/ladybug.py:1141-1144` (`_node_label`, `MATCH (n:Entity:Passage {id: $id}) RETURN label(n)`) and `store/changesets.py:71` (`MATCH (a:Entity|Passage {id: $a}), (b:Entity|Passage {id: $b})`) are two different dialects (`:A:B` in LadybugDB vs `:A|B` in Neo4j) for the exact same "which of these known labels is this id" problem, and both would need a third/fourth label added the day `Symbol`/`DataObject` join `TUNED`. A's `_labels_of` helper (WP1.3) is the right fix; note it must be written once for LadybugDB and once (differently) for Neo4j — the syntax is not shared.

3. **The `None`-breaks-`decode()` LadybugDB quirk is already load-bearing, not just "verified on this machine."** Every current free-text write path (`add_passages`, `add_entities`, `add_facts`, `add_questions`, `add_result`, role/user fields) defensively does `text(r.get("field") or "")` before calling `text()`, never `text(r.get("field"))` bare — e.g. `ladybug.py:538-539,626,695-697`. Any new `_symbol_row`/`_data_object_row` writer must follow the identical `or ""` convention for `doc`, `signature`, etc., or it will hit exactly the bug A's "Verified on this machine" section warns about, on the very first `doc=None` row.

4. **The exact-equality test surface for `index_source`'s counts dict is bigger than A's plan states.** A's WP2.4 says "update the two exact-equality assertions in `test_indexer.py`"; there are actually **six** (`tests/unit/test_indexer.py:55, 98, 212-216, 218-222, 238, 317`), plus a seventh unrelated exact-equality assertion on `stats()`'s key set in `tests/unit/test_store.py:107`. None of this is hard to fix, but the plan's own count of the blast radius is off by a factor of 3, which matters for effort estimation.

5. **`FakeStore` hand-maintains relationship-deletion side effects that the real graphs get for free.** `remove_orphans` in `tests/fakes/fake_store.py:210-218` explicitly re-filters `self.synonyms`/`self.tuned` dicts when an entity is dropped, because Python dicts don't cascade like a real graph's `DETACH DELETE`. Every new edge-bearing dict the plan adds to `FakeStore` (`code_edges`, `modifies`, `precedes`, `refers_to` per A's WP1.2) needs the same explicit by-hand pruning wired into both `delete_source`/`delete_passages_for_source` *and* `remove_orphans` — it is easy to add the dict and forget the cascade, and nothing but a test would catch it since Python won't complain about a dangling key.

6. **The Graph page's "kind" filter and the vertex model are two different things.** `web/routes/graph.py:140` filters on `index.node_kind[v]`, which is `GraphIndex`'s own two-value enum (`"entity"`/`"passage"`), completely separate from any `kind` property B proposes storing on the `Entity` node itself. Loading a `kind='symbol'` column onto `Entity` in the store changes nothing about what `GraphIndex.load()` puts in `node_kind` — the page's "Kind filter gains 'symbol'" (B §9) requires new plumbing through `GraphIndex` (a per-vertex property array that doesn't exist today), not just a new stored column.

7. **`node_specificity`'s division only guards against a zero denominator, not a stale one.** `retriever.py:286-287`: `if node_specificity and index.entity_passage_count[v] > 0: w /= index.entity_passage_count[v]`. A's proposed code-node specificity (`1 / (in_degree + 1)`) is a different formula computed on a different quantity, loaded onto the same array — worth flagging that this is a *shared* numpy array across two conceptually different specificity measures (mention count vs. call/data in-degree) with no per-node-kind branch in the retriever today; whichever plan wins needs the retriever's `node_specificity` block to stay kind-agnostic (just divide by whatever's in the array) or grow an explicit branch.
