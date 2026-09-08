# R1 — Store layer, schema, GraphIndex, access (worker: sonnet-1)

Read `00-shared-context.md` first. Output file: `docs/plans/hippo-for-code/research/R1-store-graph.md`.

Files in scope: `src/hippo/store/base.py`, `store/memory.py`, `store/ladybug.py`, `store/changesets.py`,
`store/evals.py`, `store/users.py`, `src/hippo/hipporag/graph_index.py`, `src/hippo/hipporag/text.py`,
`src/hippo/access.py`, `tests/fakes/fake_store.py`, `tests/unit/test_store*.py`, `tests/unit/test_graph_index.py`,
`tests/unit/test_access.py`, `docs/CONTRACTS.md` (store and graph_index rows only).

Verify each claim below. Cite `file:line` for everything.

- **R1.1** What each store module actually is. `store/base.py`: is it an abstract base / Protocol? List EVERY
  method name with its signature (one line each). `store/memory.py`: is it the Neo4j backend, an in-memory
  store, or both? (B §1 says "`store/base.py`+`memory.py`" is the Neo4j path; A speaks of "LadybugDB, Neo4j,
  FakeStore".) `tests/fakes/fake_store.py`: what it mirrors and how tests select a backend.
- **R1.2** Node and rel tables. From `ladybug.py` `ensure_schema` (or equivalent), list every node table and
  rel table with all columns and types, and every rel's FROM/TO. Do the same for the Neo4j constraints/indexes.
  Is there any `schema_version` or migration mechanism today? Any `ALTER TABLE` usage?
- **R1.3** `remove_orphans`. B §1 cites `memory.py:175` and `ladybug.py:525`. Confirm the actual lines, quote
  the query, and state precisely: which node labels it deletes, under what condition, and whether it would
  delete (a) an Entity that only has `TUNED` edges, (b) an Entity reached only by a hypothetical `DEFINES`
  rel, (c) `SYNONYM`-only entities. Also: is `remove_orphans` called from `reindex`/`delete_source`/both?
- **R1.4** Row shapes. `load_entities`, `load_facts`, `load_passages` (or whatever they are called): exact
  dict keys returned, and the `_rows_with_good_vectors` guard B mentions. Would an extra column with a
  default break any consumer (grep the consumers of these rows in `graph_index.py`, `retriever.py`)?
- **R1.5** `GraphIndex` vertex model. How entities and passages become igraph vertices (name attrs, id → vertex
  maps), the `Edge` dataclass fields, the exact `weight` rule (quote it), `load()`, `scoped()`, `graph_with_edits()`,
  how `graph_version` triggers a rebuild, and how `entity_passage_count` / node specificity is computed.
  Does anything in `GraphIndex` care about a node's label beyond Entity vs Passage? Could a `kind`
  column ride along with zero changes to the vertex model (B's D1 claim)?
- **R1.6** Access. `access.py`: how `ACCESS_WHERE` (or equivalent) is built, how entity visibility follows from
  passage visibility (via `MENTIONS`?), and what `GraphIndex.scoped()` does with it. Quote the pattern.
- **R1.7** Settings. `DEFAULT_SETTINGS` and `SETTING_RULES` in `store/base.py` (or wherever): list every
  key, default, min/max. A §3.1 claims the settings page hard-codes `max="1"`; find the template
  (`src/hippo/web/templates/settings.html`?) and quote the input markup for one setting.
- **R1.8** Ids. `make_id` (or equivalent) in `hipporag/text.py`: exact formula for entity ids, fact ids, passage
  ids. A proposes `symbol-` + md5(`source_id:path:qualname`); B proposes md5(`repo_source_id:qualname`).
  State whether any existing id scheme would collide with either, and whether ids are namespaced by source.
- **R1.9** Existing "side tables". How `store/changesets.py`, `store/evals.py`, `store/users.py` add their
  tables (node tables in LadybugDB? separate SQLite? JSON files?). This tells the synthesizer how a new
  `Override` / `Unresolved` / `BindingRule` table would conventionally be added. Also: how eval results store
  the per-question trace (full `Trace`? which fields?).
- **R1.10** Full-text search. Is there any FTS index or substring search on either backend today
  (LadybugDB FTS extension, Neo4j fulltext index)? How does the Graph page or any picker search entities by name?
- **R1.11** `TUNED` and `SYNONYM` persistence. Where they are written, read, and whether `reindex` of a source
  clears them. This grounds B's "Overrides that survive re-indexing: Gap" row.
- **R1.12** Neo4j parity. For every LadybugDB write path you list in R1.2/R1.4, confirm the Neo4j equivalent
  exists with the same method name and row shape (A and B both require name-for-name parity).

Gotchas to look for specifically: label-vs-property patterns, any `UNION`/multi-label queries that would need
a new label added, hard-coded lists of rel types (e.g. in `scoped()` or the Graph page), the two LadybugDB
binding quirks named in the `ladybug.py` docstring.
