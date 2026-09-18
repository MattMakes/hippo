# WP2 (pure half) — `codegraph/` extractors, the fixture tree, `test_codegraph.py`

Read `impl/00-impl-context.md` first. Worktree `.worktrees/wp2`, branch `wp/wp2`.
Neo4j test container (only to prove the whole suite still passes at the end): name `hippo-neo4j-wp2`,
port **17692**. Your code is pure — no store, no LLM — so most of your loop is
`.venv/bin/python -m pytest tests/unit/test_codegraph.py -q`.

Your spec is PLAN.md **WP2 sections 2.1, 2.2, 2.2a, 2.2b, 2.2c (lines 263-336)**, the **Test fixture plan
(lines 416-473)**, the Design summary's graph model + ω table (lines 61-98) and Decision Log D3, D4, D7,
D9, D20, D24, D25. Evidence: `research/R2-ingest-evals-tests.md` (readers, documents, chunker, tests
conventions) and `research/R4-spike-results.md` T9 (tree-sitter API facts) and T11 (git/toolchain).
WP1 (store + GraphIndex) is being built in parallel by another worker; you import nothing from the store
and touch none of its files. The chunker/indexer/pipeline integration (PLAN 2.3-2.5) is a LATER worker's
job that consumes your `CodeGraph` — so your public shapes are an interface: document them.

## Scope

1. **Dependencies** (2.1): append the four packages to `pyproject.toml` `dependencies` with exactly the
   plan's version ranges; `uv pip install -e '.[dev,neo4j]'` again; `test_grammars_load`. Confirm cp311
   wheels exist for all four (`uv pip download --python-version 3.11 ...` into /tmp, or check PyPI) and
   record it in the ledger — `requires-python` is `>=3.11`.
2. **`src/hippo/codegraph/`** — `__init__.py`, `model.py`, `treesitter.py`, `python.py`, `typescript.py`,
   `resolve.py`, `data_access.py`, `extract.py`. NOT `git_history.py` (WP2b). Imports: stdlib,
   `tree_sitter*`, `sqlglot`, `hippo.hipporag.text` (`make_id`, `split_identifier`) only.
   - `model.py`: `Symbol`, `DataObject`, `CodeEdge`, `FileFacts`, `FileGraph`, `CodeGraph` dataclasses;
     `symbol_id`, `data_id`, `commit_id`, `name_text`; the three constants `code_max_files = 5_000`,
     `code_max_file_bytes = 512 * 1024`, `code_max_symbols_per_source = 50_000` (2.2c — spell them as the
     plan does, or as UPPER_CASE module constants if that is what `MAX_CHUNKS` does; check and match).
     `Symbol` carries everything the store row needs (WP1.3 table, line 218: `id, source_id, name,
     qualname, kind, lang, path, line_start, line_end, signature, doc, is_test, raises`) PLUS what the
     chunker will need: the **display qualname** (`module.qualname`, 2.2a), the **body's top-level
     statement start lines** (for splitting oversized passages at statement boundaries), and for a
     module/class the header range (the lines before the first member). `CodeEdge` = `(a, b, kind, omega,
     provenance, extra: dict)`; name it `CodeEdge` — `GraphIndex` has its own `DirectedEdge`.
     `CodeGraph.stats()` returns the dict that becomes `Source.meta["code"]`: counts of symbols, data
     objects, edges by kind, files parsed / skipped (and why: too big, unsupported, parse error),
     **unresolved calls per file** (D15), `truncated`.
   - `extract_code(docs, source_id) -> CodeGraph` takes the `Document` list `ingest/readers.read_source`
     produces (read `readers.py` for the shape — `path`, `text`, `is_code`, ...). Each file in its own
     `try/except`; a failed file is recorded in `stats` and left for the line-window chunker. One
     `Parser` per call (thread safety). A repo-relative path is what `Document` carries — verify.
   - Everything in 2.2 / 2.2a / 2.2b is the spec: qualname grammar, the ω/provenance per construct, the
     `FUZZY_STOPLIST` + unique-match rule, BFS-MRO ≤ 5, `arg_binding` truncated at 60 chars, wildcard 0.60,
     `classify_literal` checking Cypher before SQL, `sqlglot.parse(..., error_level=IGNORE)` in try/except,
     data objects deduped across DDL / literal / `__tablename__`, "no edge" rows as positive assertions,
     builtin exceptions to `Symbol.raises` not an edge, TESTED_BY's three provenances.
3. **`ingest/readers.py`**: the language predicate the pipeline will branch on — name it `lang_of(name)
   -> str | None` (`"python"`, `"typescript"`, `"sql"`, else `None`), keyed on the SAME suffix sets
   `is_code_name`/`is_supported_name` use. `.js/.jsx/.mjs/.cjs` → `"typescript"` (tsx grammar). Test it in
   `test_ingest_readers.py`. Touch nothing else in `ingest/`.
4. **`tests/fixtures/code_sample/`** exactly as the Test fixture plan draws it (lines 420-469), every file,
   with `place`'s ≥ 80-char docstring, `Base` in `store.py`, the Go file, the README with its two sentences.
   Line numbers in the plan are targets; the final files decide, and your tests assert the final numbers.
   Make the tree a valid Python package so `pytest` never collects it (add it to pytest's `norecursedirs`
   / `testpaths` in `pyproject.toml` if `tests/fixtures/code_sample/tests/test_orders.py` would otherwise
   be collected — check). No `.git` inside it.
5. **`tests/fixtures/code_sample/expected.json`** (S2.17, line 471) — the sections your extractor
   produces: `symbols` (keyed by `(path, qualname)` with kind, line range, signature, doc, is_test,
   raises), `data_objects`, `edges` (`a`, `b` as `(path, qualname)` / data `(kind, qualname)`, kind, ω,
   provenance, and `extra` for INVOKES). Leave `definitions`, `refers_to`, `commits`, `modifies` as empty
   lists with a comment-free schema the later workers extend (JSON has no comments — document the schema
   in `scripts/update_expected.py`'s docstring). Write `scripts/update_expected.py` that regenerates YOUR
   sections from `extract_code` over the fixture (the pytest `--update-expected` hook is the integration
   worker's). Hand-verify every row of the file against the 2.2b table before committing it: the file is
   the spec, and a wrong row there is a wrong spec.
6. **`tests/unit/test_codegraph.py`** — everything in 2.6's first bullet (line 347): exact symbol set,
   every edge with ω + provenance, the eight no-edge rows, the INVOKES `extra` for `place → billing.total`,
   data-object dedup, classifier unit tests, determinism (extract twice → equal), the self-smoke over
   `src/hippo` under 5 s, `test_grammars_load`. Plus a test that `expected.json`'s symbol/edge/data
   sections equal what `extract_code` yields (order-independent) — this is the golden test's pure half.

## Toolchain facts (R4 T9, so you do not rediscover them)

`tree_sitter.Query` has no `.captures()` in 0.26 — use `QueryCursor(query).captures(tree.root_node)`;
`Language(tree_sitter_python.language())`; `tree_sitter_typescript.language_tsx()` parses plain JS/JSX
too; fragments parse tolerantly. Node text is `node.text.decode()`; lines are `start_point[0] + 1`.

## Done when (PLAN.md line 352, the pure parts)

`extract_code` over the fixture is deterministic across two runs, over `src/hippo` finishes under 5 s,
every 2.2b row has a passing test, `expected.json` is hand-verified, the FULL suite is green on all three
stores (nothing you did should change any existing test — if one breaks, that is a bug in your change) and
lint is green. Commit, ledger summary (every file; the public `CodeGraph`/`Symbol` field list; anything the
chunker/indexer worker must know), `horch tell orchestrator "[<role>] DONE: wp/wp2 ..."`, close pane.
