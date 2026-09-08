# R4 — LadybugDB and toolchain feasibility spike (worker: codex-sol-1)

Read `00-shared-context.md` first. Output file: `docs/plans/hippo-for-code/research/R4-spike-results.md`.

This is the architectural tiebreaker. Plan B (D1) adds COLUMNS to existing `Entity`/`Fact`/`Passage` node tables
via `ALTER TABLE … ADD` and wants `STRING[]` columns and FTS. Plan A adds NEW tables instead and needs one rel
table spanning several node-label pairs. Which is feasible on `real_ladybug` 0.15.x decides the schema.

## Rules

- Work in a SCRATCH venv and a temp directory. Never touch `/Users/mascott/projects/hippo/data/`, `.venv/`,
  or any running process. Suggested: `python3 -m venv /tmp/hippo-spike && /tmp/hippo-spike/bin/pip install
  "real_ladybug>=0.15.3,<0.16" tree-sitter tree-sitter-python tree-sitter-typescript igraph`.
  First check the exact installed version in the project: `/Users/mascott/projects/hippo/.venv/bin/pip show real_ladybug`
  and install THAT version in the scratch venv.
- Read `src/hippo/store/ladybug.py` docstring and `ensure_schema` first so your DDL matches the project's
  style (how it opens the DB, `text(x or "")`/`decode()` quirks, how it declares tables). Do NOT modify it.
- Do NOT redo what Plan A "Verified on this machine" already covers (tree-sitter/sqlglot versions, the five
  LadybugDB quirks listed there) except where marked "re-verify" below.
- Every test: create DB file in a temp dir → run DDL/DML → CLOSE the database → REOPEN → query → assert.
  "Works in memory" is not a pass. Record the exact statement that worked or the exact error text.

## Tests (each gets a PASS / FAIL / PARTIAL row with the exact Cypher/Python that ran)

- **T1** Node-table `ALTER TABLE Entity ADD <col> <TYPE> DEFAULT <v>` on a table WITH existing rows. Reopen.
  Existing rows return the default? Idempotent re-run (`ADD IF NOT EXISTS`, or how to guard)? Try STRING,
  INT64, DOUBLE, BOOLEAN.
- **T2** `STRING[]` column: create with it, insert, read back, `UNWIND`, and also add via `ALTER TABLE`.
- **T3** FTS: is a full-text search extension available in this binding (`INSTALL FTS; LOAD EXTENSION FTS;
  CALL CREATE_FTS_INDEX(...)` kuzu-style, or anything else)? Any `CONTAINS`/`=~` regex substring on STRING and
  its timing on 100k rows.
- **T4** Adding NEW node and rel tables to an existing DB with `CREATE NODE TABLE IF NOT EXISTS` /
  `CREATE REL TABLE IF NOT EXISTS`. Reopen. Then verify rows written before the DDL are intact.
- **T5** A rel table with properties `(kind STRING, omega DOUBLE, provenance STRING, line INT64, in_branch BOOLEAN,
  arg_binding STRING)` between Entity→Entity: `MERGE` semantics on (a,b,kind); "best omega per (a,b)" query
  timing with ~100k rels; `MATCH (a)-[r:STRUCT]->(b) RETURN a.id, b.id, r.kind, r.omega` full-scan timing.
- **T6** RE-VERIFY (A's open item): `ALTER TABLE <rel> ADD IF NOT EXISTS FROM A TO B` on a closed-and-reopened file.
- **T7** Multi-pair rel table at CREATE time: `CREATE REL TABLE CODE_EDGE (FROM Symbol TO Symbol, FROM Symbol TO
  DataObject, FROM DataObject TO Symbol, kind STRING, omega DOUBLE)` — supported? Can you `MATCH` across all
  pairs in one query? Can you `CREATE` a rel with a multi-label pattern (A says no; confirm).
- **T8** Row-count scale: insert 50k Entity rows and 200k rels in batches via `UNWIND $rows`; report seconds
  and file size. This bounds "hippo indexes itself" and a 50k-line repo.
- **T9** tree-sitter 0.26 API check: parse one Python file with a `Query` for function definitions and calls
  (note whether `QueryCursor` is required in this version), and parse an ERROR-TOLERANT fragment such as
  `kept, raw = filter_fn(question, candidate_triples) if sent else ([], "")` (B's anchors need names from
  partial snippets). TS: `language_typescript()` and `language_tsx()`; confirm tsx parses plain JS.
- **T10** igraph: `Graph.get_shortest_paths` / `get_all_shortest_paths` on a directed graph of 10k nodes /
  40k edges (timing), and whether `community_leiden` is available in the installed igraph (A wants Leiden).
- **T11** git: on the hippo repo itself (read-only!), time `git blame --line-porcelain <file>` for the 5
  largest `.py` files, `git log --first-parent -n 200 --numstat --format=...`, and `git show -U0 --format= <sha>`
  for hunk ranges. Report seconds. Is `pyright`/`tsserver`/`node` on PATH? Just report.

## Output

`R4-spike-results.md`: the PASS/FAIL table first; then per test the exact code that ran (a fenced block, so
the synthesizer can paste it into the plan), timings, and error text verbatim. Close with a short
"What this decides" paragraph: can B's D1 (columns on existing tables) work on this binding, yes or no; can
A's multi-pair `CODE_EDGE` work, yes or no. Clean up `/tmp/hippo-spike` only if you want; leave the repo untouched.
