# E1F-b — Two Node idioms the territory-updater run showed the extractor misses

Read `impl/00-impl-context.md` first (rules, worktree + venv, three-store matrix, exit-code capture).
Worktree `.worktrees/e1fb`, branch `wp/e1fb`, from the CURRENT tip of `code-graph` (L0's language
registry is merged: `codegraph/languages.py`, per-language `LanguageRules`; the TS walker is
`codegraph/typescript.py`, the Mongo classifier `codegraph/data_access.py`). Neo4j test container:
name `hippo-neo4j-e1fb`, port **17708**. Three walker workers (Go, C#, Rust) run in parallel and do not
touch these two files; you touch only `typescript.py`, `data_access.py`, `test_codegraph.py` (or a new
`test_codegraph_node_idioms.py`) and, if a fixture row legitimately changes, `expected.json` via
`scripts/update_expected.py` with the diff read row by row.

Spec: `research/E1-territory-updater.md` **Defect 2** and the "destructured `require`" paragraph under
Q2 / the DONE summary. Both are reproduced with exact file:line evidence there.

1. **`db.collection('name').method(...)`** (the official Node driver, 130+ call sites in a real app;
   today only PyMongo's `db.name.method()` attribute chain classifies). Make `mongo_hit` (or the
   marker path L0 added for `Collection("x")` / `get_collection("x")`) recognise a receiver whose last
   segment is a collection-call with a string literal — `collection('x')`, `collection("x")`,
   `getCollection('x')`, `db.collection('x')` — and take the name from the literal, for both the direct
   chain `db.collection('territory').findOne(...)` and the bound form `const col =
   db.collection('territory'); col.updateOne(...)` (the existing `AssignFact` path). Check what
   receiver text the TS walker records for a call whose callee object is itself a call; if it drops the
   arguments, keep them for this shape. READS/WRITES ω 0.85 `mongo_chain` as today. Tests: inline
   Document cases for the direct chain, the bound variable, a template-literal or non-literal argument
   (→ no data object), and that PyMongo's attribute chain is unchanged.
2. **Destructured CommonJS `require`**: `const { runWorkerLoop, claimNextJob: claim } = require('./workerLoop')`
   produces no IMPORTS/INVOKES today. Emit one `ImportFact` per destructured name with the alias, the
   way `import { a, b as c } from './x'` already does, so `runWorkerLoop()` resolves to 0.90
   `via_import`. Cover `const x = require('./y')` (already works? — assert it) and the destructured form
   with and without aliases, plus a bare-specifier `require('express')` → no edge.

Done when three stores + lint green, `scripts/update_expected.py --check` clean (if `expected.json`
changed, say exactly which rows and why), no pinned assertion weakened, ledger summary,
`horch tell orchestrator "[<role>] DONE: wp/e1fb ..."`, close pane.
