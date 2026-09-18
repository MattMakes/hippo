# S2 — Staff-engineer decisions to fold into PLAN.md (worker: opus-3, the plan's author)

These are binding decisions from the orchestrator's engineering review of your Decision Log and Design
summary. Apply every item to `docs/plans/hippo-for-code/PLAN.md` now. Where an item adds a rule, write it as
a table or a numbered rule in the section named, not as prose in the Decision Log. Where an item reverses
something already in the plan, update the Decision Log row and, if it touches an A user decision, the
"Confirm with user" list. Cite research ids as before. Keep the file under 600 lines.

Two reviewers (V1 mechanical, V2 judgment) are reading the current draft in parallel; you will receive
their findings after this. Apply S2 first, then wait for the next message.

## A. Data model: one graph, one enum, one truth file

**S2.1 Vertex kinds are one enum, defined once.** In `hipporag/graph_index.py`: `NodeKind = Literal["entity",
"passage", "symbol", "data", "commit"]` (or the existing constant style: `ENTITY`, `PASSAGE`, plus `SYMBOL`,
`DATA`, `COMMIT`). Add a WP1 checklist naming the seven consumers that compare against the old two values
(R6 gotcha 3): `evals/question_maker.py`, `analysis/explain.py`, `web/routes/graph.py`, `hipporag/retriever.py`,
`hipporag/graph_index.py`, `web/static/graph.js`, `web/static/analyze.js`. State that `web/routes/graph.py`'s
`node_details` else-branch (R6 gotcha 3) must branch on kind, with a test that a symbol id returns a
symbol-shaped payload.

**S2.2 Node label comes from the id prefix, never from a query.** Ids are already prefixed (`entity-`,
`fact-`, `passage-`; `hipporag/text.py:27-39`). Define `label_of(id) -> str` in `codegraph/model.py` (or
`hipporag/text.py`) mapping `entity-`→`Entity`, `passage-`→`Passage`, `symbol-`→`Symbol`, `data-`→`DataObject`,
`commit-`→`Commit`, raising on unknown. It replaces `_node_label` (`store/ladybug.py:1141-1144`) and the
`:Entity|Passage` pattern in `store/changesets.py:71` (R1 gotcha 2), and it is how every writer picks the
concrete label pair that LadybugDB requires (R4 T7). One helper, used by all three stores.

**S2.3 One table of which relations enter igraph and with what weight term.** Put it in "Retrieval rule":

| Rel | In igraph? | Weight term in the `max` | Direction kept for path tools? |
|---|---|---|---|
| MENTIONS, STATES-derived fact edges, SYNONYM, TUNED | yes (as today) | as today | no |
| CODE_EDGE | yes | ω × `code_structural_scale` | yes (`code_out`/`code_in`) |
| DEFINED_IN | yes | 1.0 (counts as a mention) | yes |
| REFERS_TO | yes | ω × `code_structural_scale` | yes |
| MODIFIES | yes | ω × `code_structural_scale` | yes |
| PRECEDES | **no** | — | side list only (`history` tool) |

**S2.4 Specificity per kind, computed in `GraphIndex.load` (one array), never branched in the retriever.**
entity: `1 / passages that mention`; symbol and data: `1 / (in_degree + 1)` counting INVOKES, READS, WRITES
only; commit: `1.0`; passage: never seeded. `scoped()` recomputes the same way from the visible subgraph.

**S2.5 Visibility per kind for `scoped()` (R3 gotchas 6–7).** symbol: kept iff at least one DEFINED_IN target
passage is visible; commit: kept iff its commit passage is visible; data: kept iff at least one DEFINED_IN
target passage is visible, and a DataObject gets a DEFINED_IN edge from **every** passage whose literal names it
(ω 1.0). Facts and code edges whose endpoints were dropped are dropped. Add a `test_access` case: a restricted
user cannot see, seed, or path through a symbol whose source is hidden.

## B. Extraction: the fixture's expected output is the spec

**S2.6 Qualname grammar (WP2, one table).** module: repo-relative path, `/`→`.`, extension stripped, `__init__`
kept (`src.hippo.store.__init__`); class: `Class`; method: `Class.method`; function: `func`; nested classes:
`Outer.Inner`; nested functions, lambdas, comprehensions: **not symbols**, they stay inside the enclosing
passage. TS/JS: same; arrow functions assigned to a `const` at module or class scope are functions/methods
named by the binding; anonymous callbacks are not symbols.

**S2.7 What OpenIE sees: `Chunk.extract_text` is the only gate.** function passage: the docstring/doc-comment
iff ≥ 80 chars, else `None`; module and class header passages: same rule on their docstring; markdown, README,
commit-message passages: whole text; function bodies, DDL, `.sql` files: never. `indexer.index_source` skips
`openie.extract` when `extract_text is None` and `test_indexer.py` asserts the `FakeOllama` chat count for the
fixture equals the number of passages with `extract_text` set.

**S2.8 Resolver support table per language (WP2, one row per construct).** Columns: construct · example ·
edge kind · ω · provenance · or "no edge". Python rows at minimum: `import a.b`, `from a import b`,
`from . import x`, `from .. import x`, `from a import *`, `__init__` re-export, `self.m()`, `cls.m()`,
`super().m()`, `Class.m()`, `obj.m()` where `obj` was assigned `Class(...)` in the same function
(via_import/same_file if unique, else `fuzzy_name` 0.50 if the bare name is unique in the source, else no edge),
`x.y.z()` unresolvable chain (no edge), decorators (`@app.route` → INVOKES the decorator symbol if resolvable),
`raise X`, `except X`. TS/JS rows: `import {a} from './b'` (extension-less, `index.ts` re-export),
`import x from`, `export default`, `require()`, `this.m()`, `super.m()`, `new Class()`, class `extends`,
`throw new X`, `catch (e)`. Every row in this table must be exercised by a file in `tests/fixtures/code_sample/`
and appear in `expected.json` (S2.17).

**S2.9 MODIFIES intersects hunks with symbol ranges AT THAT COMMIT, not at HEAD.** This reverses the "Stated
approximation" in WP2 (`PLAN.md` ~line 281). Reason: the commit eval (WP4.5) uses these edges as gold, so a
HEAD-range shortcut makes the eval measure its own error on every commit older than a few edits. Rule: for each
of the `depth` first-parent commits, for each touched file in a supported language, run `git show <sha>:<path>`,
parse it with tree-sitter (R4 T9: ~ms per file), intersect the hunk's **new** ranges with that parse's symbol
ranges, and map each hit to the HEAD symbol by `(path, qualname)`; symbols absent at HEAD produce no edge.
`-M` (rename detection) is **off**; history before a rename is ignored in phase 1 (state in Known limitations).
`extra`/`hunk` JSON keeps `{file, old_range, new_range, churn}`. Budget: `git show` per commit under a
`code_git_timeout_s` (default 10); a timeout skips that commit and is counted in `Source.meta.history_skipped`.

**S2.10 Determinism vs Leiden.** The CI gate "index twice → identical multisets" conflicts with Leiden's
randomness. Rule: seed igraph's RNG (`igraph.set_random_number_generator(random.Random(0))` or the equivalent
the installed version exposes; R4 T10 verified `community_leiden` exists), relabel communities by the
lexicographically smallest member qualname, and **exclude `community` from the multiset comparison**. The
determinism test lists exactly which fields it compares.

**S2.11 Budgets, as numbers, in one table (WP2).** `code_max_files` 5000, `code_max_file_bytes` 512 KiB
(files above are indexed as today's line windows, not parsed), `code_max_symbols_per_source` 50 000
(above: extraction stops, `Source.meta.truncated = true`), `code_history_depth` 200 (A user decision; this
is the setting name, replace any other spelling), `code_git_timeout_s` 10. The cooperative cancellation check
(`jobs.py`, R2-10) runs between files and between commits. Add these to the Settings table with `SETTING_RULES`
bounds and `SETTING_HELP` lines, or state explicitly which are constants in `codegraph/model.py` and why.
Pick one; do not leave any budget unspecified.

## C. Retrieval: three rules the draft leaves open

**S2.12 Split the single Ask field internally.** Keep one field (D21) but define
`split_question(text) -> (prose: str, code: str)` in `hipporag/anchors.py`: fenced blocks, lines matching a
stack-frame pattern, diff hunks (`@@`, `+`/`-` prefixed lines) and lines that parse as code go to `code`.
`find_anchors` reads both. The question **embedding** and the **fact-filter prompt** receive `prose` only,
falling back to the full text when `prose` is empty. The QA prompt receives the full text. Trace records
both halves. Test: a 40-line traceback plus one sentence embeds only the sentence.

**S2.13 Anchor fan-out rule.** An identifier that matches several symbols seeds all of them with
`code_seed_weight / n_matches`, records `n_matches` and `matched_by` on the `SeedSymbol` trace entry, and is
**dropped** (recorded as `ambiguous`) when `n_matches > 10`. Path-qualified matches (`a.b.c`, stack frames
with a file path) are never split. Test both branches.

**S2.14 The select pass is an injected callable with a schema and a fallback.** `Retriever.retrieve` already
takes `fact_filter` as a callable (R3.1); add `select_fn: Callable[[str, list[RankedPassage]], SelectResult] | None`
the same way so tests inject a fake and the retriever never imports Ollama. Output schema (JSON):
`{"keep": [passage_id...], "drop": [passage_id...], "expand": [passage_id...]}`; unknown ids ignored; on any
LLM error or unparsable output the result is keep-all (mirrors the fact filter's fallback, R3.1). "expand"
fetches ≤ `code_expand_max` one-hop neighbours over INVOKES/OVERRIDES/RAISES with ω ≥ 0.75 and appends their
defining passages **after** the kept list with score 0.0 and `via_expand=True`; they are never re-ranked and
never counted toward `top_k` for the answer's citation list unless the answer cites them. Decisions land in
`Trace.select`. Gate: runs only when `used_code_seeds` and `code_select` is true.

**S2.15 Context block format is a fixed grammar.** One line per triple:
`<a.qualname> -[<KIND> <ω:.2f> <provenance>[ in_branch][ await]]-> <b.qualname>`; then a `Tests:` line per
TESTED_BY; then `Commits:` lines `<sha7> <date> <first line of message>`; cut at `code_triples_chars` on a
line boundary with a final `… (+N more)` line. `test_ask.py` asserts the exact string for the fixture.

**S2.16 Trace fields carry defaults and are never removed.** Every new field on `Trace`, `TopNode`,
`SeedEntity`/`SeedSymbol`, `RankedPassage` has a default (R3 gotcha 8, `trace_from_dict` is strict) and a
test loads a pre-change stored trace JSON (copy one from the existing eval tests) without error.

## D. Testing: one golden file kills most contradictions

**S2.17 A checked-in `tests/fixtures/code_sample/expected.json`** listing every symbol (id inputs, kind,
qualname, path, lines), every edge (a, b, kind, ω, provenance), every DataObject, every REFERS_TO and
DEFINED_IN, and the commit→symbol MODIFIES set for the tmp_path-built history. One parametrized test
(`test_store_code.py`, all three stores) indexes the fixture and asserts the loaded graph equals the file
(order-independent, `community` excluded). Every rule in S2.6–S2.9 is therefore checkable, and the file is
the spec juniors argue with. State how the file is regenerated (a `--update-expected` flag or a script) and
that regeneration diffs must be reviewed.

**S2.18 The pinned-test list, placed in the WP that breaks each.** `test_indexer.py:55, 98, 212-222, 238, 317`
(counts dict, R1 gotcha 4) + `test_store.py:107` (stats keys) → WP2; `test_ingest_pipeline.py:138, 205`
(chunk titles) → WP2; `test_retriever.py:135` (node kinds), `:136` (timing keys) → WP3;
`test_analysis_changesets.py:47` (VALID_OPS) → only if an op is added; `test_analysis_explain.py:114`
(edge kinds) → WP3; `test_mcp_server.py:17` (TOOL_NAMES) and `README.md:228` ("four") → WP4.

## When done

Re-run your self-check (every `src/hippo/...` path exists or is `new`). Then
`horch tell orchestrator "[opus-3] S2 applied: <n> items, PLAN.md <lines> lines"` and keep the pane open.
