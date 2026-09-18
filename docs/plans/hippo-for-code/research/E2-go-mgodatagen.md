# E2 — hippo on mgodatagen (Go, real repo, real Ollama)

Run 2026-09-09/10 on `code-graph` tip `8121e9f` (worktree `.worktrees/e2go`, branch `wp/e2go`, only
this report committed there). Real Ollama on the host throughout: `qwen3.8:latest` (chat) and
`nomic-embed-text` (embeddings). Scratch server on port 8015, `HIPPO_DATA_DIR=/tmp/hippo-e2go/data`,
`HIPPO_STORE=ladybug` (default). Never touched port 8000/7687/7474, `data/`, or the containers
`hippo-app-1`/`hippo-neo4j-1`. The server was started **before** the source was added, per the brief,
and stayed up for the whole task.

Repo: `/Users/mascott/projects/mgodatagen`, a MongoDB pseudo-random-data generator, 37 `.go` files.
The working tree has the user's own uncommitted local modifications to most tracked files (not
inspected — out of scope for this run), plus two untracked scratch files `.DS_Store`/`config.txt` —
**none of that was read**: indexing went through a local `git clone` (see Methodology), which only
ever sees the last commit's committed content, never the working tree's modifications or untracked
files.

## Verdict

Indexing a real, idiomatic Go CLI tool works well and finishes fast (15.4 minutes, a third of the
45-minute budget), and the question with a genuine lexical anchor (a pasted panic trace) came back
correct and impressively so — it correctly diagnosed an empty-slice index panic three call frames
removed from the crash site, citing the exact struct-embedding relationship the resolver found. But
four of the five questions showed no Code graph card at all (`used_code_seeds=False`); one of those
four (e) is genuine prose with nothing to anchor on and is graded on its own merits below, but the
other three (a, b, d) all asked about the same central identifier, `Generate`, typed in plain English
the way the brief's row phrases them ("What does X do?") rather than backticked the way the brief's own
worked example shows it. Go's own naming convention (`Generate`, `Run`, `New` — one capitalized word,
no internal case boundary) is the textbook case the bare-word anchor heuristic was built to exclude,
and it excludes it totally for exactly those three questions. Re-asking two of them with backticks, as
the brief's template implies, immediately fixed both. Two independent, well-evidenced defects survive
that correction, both found by digging past the Ask page into the graph directly: **`main.go`'s module symbol and its
`func main` collide on the same generated id and one is silently destroyed** (confirmed by an exact
symbol-count mismatch: the extractor counted 230 symbols, the store holds 229), and **the MongoDB
data-access extractor cannot see any of this tool's real writes**, not because of a missed idiom (Go's
`.Collection("literal")` call shape is explicitly handled) but because every real call site passes a
*variable* collection name — the one thing a tool whose entire purpose is generic, config-driven data
generation will always do. A third, smaller defect: **git history tracking does not follow file
renames**, so a symbol's true authorship commit is invisible to `hippo history` whenever it predates a
rename of the file that now contains it, even though the commit is well within the read depth.

## The five questions

| # | Question (typed exactly as shown, no backticks unless shown) | Verdict | `used_code_seeds` | Timing |
|---|---|---|---|---|
| a | What does Generate do? | **Correct** (no Code graph card; see Surprise 1) | False | 7989 ms |
| b | Where is Generate called? | **Correct, but ungrounded** — right answer, wrong evidence path (see Q2) | False | 1869 ms |
| c | Panic trace ending in `EncodeValue` — why would this happen? | **Correct** causal diagnosis; the literal index in my synthetic trace isn't quite reachable (see Q3) | True | 11555 ms |
| d | Which commits touched Generate? | **Wrong**; **Correct** once re-asked as `` Which commits touched `Generate`? `` (see Q4 and Defect 3) | False → True | 1714 ms / 10752 ms |
| e | Which code writes the generated documents to a MongoDB collection? | **Wrong** — names the orchestrator file, not the inserter (see Defect 2) | False | 1582 ms |

Questions a, b and d were typed without backticks, in the plain-English style the brief's row text
uses ("What does X do?"); the brief's own worked example shows the identifier backticked. That
difference is the whole story of Surprise 1: re-asking a and d with backticks (variants, same
question, not new ones) flips `used_code_seeds` from False to True both times. (e) is the fifth
question with no Code graph card, but for an unrelated, legitimate reason — it is pure prose with no
identifier to anchor on — and is graded independently in Defect 2.

Central function: `Generate` (`func Generate(options *Options, out io.Writer) error` at
`datagen/generate.go:30-32`), display `datagen.generate.Generate` — the package's one exported
top-level entry point, called from `main.go:39`.

---

### Q1 (a) — "What does Generate do?"

**Answer** (`shots/q1-generate-what.jpg`): *"Generate creates a database from options and sends logs
and progress to the output writer."* — matches the function's own doc comment
(`datagen/generate.go:29`, `// Generate creates a database from options. Logs and progress are send
to out`) almost verbatim. **Correct.**

**No Code graph card, `used_code_seeds=False`** (confirmed via `/api/simulate` replay of trace key
`5c4eca7b23f9`, `traces/q1.json`): all four seed symbols anchored `how: "dense"`, none `identifier` —
including `Generate` itself, at weight 0.0034, never promoted to an anchor. Two OpenIE facts survived
the filter (`generator generates random value` 1.00, `datagen has method generate` 0.92) and carried
the whole answer.

**Top-5 passages**: `generators.go :: Generator (lines 55-66)` (score 0.0038 — the `Generator`
*interface*, not the `Generate` function: dense similarity conflating two different, similarly-spelled
symbols, a small piece of evidence for Surprise 1) · commit `f2dafd3918: version 0.6.0` (0.0025) ·
`generate.go :: datagen.generate (lines 1-115)` (0.0018, the module chunk that actually has
`Generate`'s doc comment) · commit `21bca5d3be: add a generator for UUID` (0.0017) · commit
`3985ef3f62: improve error messages when creating generators` (0.0016).

**Variant (backticked)** — `` What does `Generate` do? `` (`shots/q1-variant-backticked.jpg`,
`traces/q1-variant.json`, trace key `ccdaf98acb33`): **Correct**, *"It generates millions of
pseudo-random BSON documents and inserts them into a MongoDB instance"* — this time sourced from the
package doc comment rather than the function's own doc comment, a different but equally correct
sentence. `used_code_seeds=True`, Code graph card renders (`Generate` chip, `identifier`), 11924 ms.
Backticking `` `Generate` `` resolves to **four** identifier hits, not one — `_name_hits` matches on
lowercased name, so it also catches the module `datagen.generate` (weight 0.25, the top hit — its
qualname is literally `generate`) and the method `dtg.generate` (0.125), alongside the intended
function `Generate` (0.018) and `DocumentGenerator.Generate` (0.028). All four are real, legitimately
same-named symbols; the ambiguity is inherent in the question, not a resolution bug.

### Q2 (b) — "Where is Generate called?"

**Answer** (`shots/q2-generate-called-1.jpg`): *"main.main"* — **correct**: `main.go:39` does
`err = datagen.Generate(&options, os.Stdout)`, confirmed by grep.

**But the answer is ungrounded**, and this is worth recording precisely (`traces/q2.json`,
trace key `90eff92c5183`): `used_code_seeds=False` again, and **`main.go` is not in the top-6 ranked
passages at all**. Reading the expanded reasoning (`shots/q2-generate-called-2-reasoning.jpg`), the
model explicitly says of the one passage it *did* see for `datagen/generate.go`, *"It does not show
`Generate` being called within this file,"* then pivots to a single piece of indirect evidence — the
commit message for `f2dafd3918` ("add package datagen with a single method `Generate`...") lists
`Touched: main.main` — and infers from Go convention that `main.main` "is standard practice" for
calling the package's entry point. The inference happens to be right, but it is not the same thing as
retrieving and reading `main.go:39`. Separately, the graph itself has the real edge:
`hippo path main datagen.generate.Generate` (below) returns
`main -[INVOKES 0.90 via_import]-> datagen.generate.Generate` directly — a correct, high-confidence
edge that the Ask flow never consulted, because the code-graph/path machinery that would have surfaced
it only engages when `used_code_seeds=True`, and (as in Q1) the bare word `Generate` never sets that
flag. Same root cause as Q1, a different, more consequential symptom: the graph had the right answer,
sitting one hop away, and the retrieval path that exists specifically to surface it never ran.

**Top-5 passages** (`traces/q2.json`): commit `f2dafd3918: version 0.6.0` (score 0.0027) ·
`generate.go :: datagen.generate (lines 1-115)` (0.0019) · commit `bbc45b9465: datagen, aggregators:
migrate to the official go driver` (0.0017) · `position_generator.go :: datagen.generators.position_generator
(lines 1-8)` (0.0016) · commit `f8d5e347cd: fake data generator: switch to gofakeit` (0.0016) —
`main.go` is not present anywhere in this list.

### Q3 (c) — panic trace ending in `EncodeValue`

Pasted question:
```
panic: runtime error: index out of range [3] with length 0

goroutine 12 [running]:
github.com/feliixx/mgodatagen/datagen/generators.(*fromArrayGenerator).EncodeValue(...)
	/Users/mascott/projects/mgodatagen/datagen/generators/from_array_generator.go:58
github.com/feliixx/mgodatagen/datagen/generators.(*DocumentGenerator).Generate(...)
	/Users/mascott/projects/mgodatagen/datagen/generators/generators.go:36
github.com/feliixx/mgodatagen/datagen.(*dtg).generateDocument(...)
	/Users/mascott/projects/mgodatagen/datagen/datagen.go:282

why would this happen?
```

**Answer** (`shots/q3-stacktrace-1.jpg`, `-2-reasoning.jpg`): *"The panic occurs because the
`fromArrayGenerator.EncodeValue` method attempts to access an index in a slice that has a length of 0.
This is likely caused by a configuration error or a logic flaw where the generator fails to produce
any valid values for the array, resulting in an empty slice, and the code does not handle this empty
state before attempting to read from it."* The five-step reasoning correctly traces
`generateDocument → DocumentGenerator.Generate → fromArrayGenerator.EncodeValue`, identifies
`g.bsonArray[g.randomIndex()]` (`from_array_generator.go:58`) as the exact panic line, and reasons
correctly about the empty-slice failure mode. **Correct** causal diagnosis.

**Caveat on my own synthetic trace, checked after the fact** (not in the model's reasoning — I built
this trace before reading `randomIndex()` closely): `randomIndex()` (`from_array_generator.go:69-80`)
has two paths. When `randomOrder` is false (the zero value, so the common case), it is a sequential
counter that resets to 0 whenever `g.index == g.size`; with `size == 0` that reset condition is true
on the very first call, so the real index would always be `[0]`, never `[3]`. When `randomOrder` is
true, the call is `g.base.pcg32.Bounded(uint32(g.size))` with `size == 0` — a call into the PCG32
library with a zero bound, which may panic with a different message entirely before ever reaching the
slice index. So `index out of range [3] with length 0` is not quite the panic this code would actually
produce for an empty `fromArrayGenerator`; a correct repro would read `[0]`. This does not change the
verdict — the model's diagnosis (empty slice, unhandled) is the right shape of answer to the
underlying bug class — but it is the same character of finding as QA1's own synthetic-traceback
caveat, and worth recording rather than overclaiming a "real bug found."

**Seed chips, all `stack_trace`, decaying by frame order then divided by node specificity**
(`traces/q3.json`, key `1704688db6a8`): `fromArrayGenerator.EncodeValue` (top frame, weight 1.0),
`dtg.generateDocument` (3rd frame, 0.8²=0.64, specificity 2 → 0.32), `DocumentGenerator.Generate` (2nd
frame, 0.8¹=0.8, specificity 9 → 0.0889) — the same layered arithmetic (`anchors.py`/`retriever.py`)
QA1 documented on a different repo; it checks out exactly here too, so not a new finding. `used_code_seeds=True`.

**Code graph block** (`shots/q3-stacktrace-3-codegraph.jpg`): includes
`datagen.generators.from_array_generator.fromArrayGenerator -[CONTAINS]->
...fromArrayGenerator.EncodeValue` and, notably,
`fromArrayGenerator -[INHERITS 0.90 resolved]-> datagen.generators.generators.base` — Go struct
embedding (`type fromArrayGenerator struct { base; ... }`) modeled as INHERITS, a deliberate design
choice (`codegraph/go.py:247-253`, "Struct embedding is Go's inheritance... INHERITS means here", D:
Go), not a bug — flagged in Surprises since it reads oddly to anyone expecting classical inheritance
from a language that doesn't have it.

**Top-5 passages** (`traces/q3.json`): commit `4772917881: make sure that bad config is handled
correctly` (score 0.0019) · `datagen.go :: dtg.insertDocumentFromChannel (lines 246-261) (part 2)`
(0.0019 — the chunk containing the real `c.InsertMany(...)` call, incidentally also the answer to Q5)
· commit `ebdae494c7: add --batchsize option` (0.0019) · commit `2481bcae93: fillCollection: fix a race
condition in the ...` (0.0018) · commit `9c49d6472c: config fail: fail if config contains unknown
fields` (0.0017).

### Q4 (d) — "Which commits touched Generate?"

**Bare-word ask** (`shots/q4-commits-1.jpg`, `-2-passages.jpg`, `traces/q4.json` key `1f7b10d53acf`):
**Wrong.** `used_code_seeds=False`, `used_dpr_fallback=True`, `trace.history=[]` — the dedicated
commit-history machinery never engages, exactly as in Q1/Q2. The model falls back to reading five
DPR-ranked commit passages and their `Touched:` lists, rambles through five commits weighing indirect
evidence, and **never reaches a clean conclusion** — the answer text is 600+ words of unterminated
`Thought:`-style reasoning that trails off mid-sentence ("...then `c178a80dce` and `3c4fea06e4` would
also touch it") with no `Answer:` line, the same `QA_MAX_TOKENS`-exhaustion shape QA1's Surprise 5
documented on a different question. None of the three commits it eventually leans toward
(`c178a80dce`, `f2dafd3918`, `3c4fea06e4`) is the right one.

**Top-5 passages** (`traces/q4.json`): commit `c178a80dce: release version 0.7.3` (score 1.0) ·
commit `c67b383706: gosimple: minor refactoring` (0.9797) · commit `3c4fea06e4: add go.mod` (0.9734) ·
commit `f2dafd3918: version 0.6.0` (0.9573) · commit `8e6d18c88b: constant genrators: allow to create
objectId` (0.9092) — all five are commit passages ranked by raw embedding similarity to the literal
word "Generate" in commit messages, none of them the actual answer.

**Backtick variant** (`shots/q4-variant-backticked.jpg`, `traces/q4-variant.json` key
`2c4781a63b10`): `` Which commits touched `Generate`? `` — **Correct.** `used_code_seeds=True`,
answer *"80173a35f3"*, matching `hippo history datagen.generate.Generate`'s `80173a3` exactly (the
backtick chip resolves ambiguously to every symbol literally named `Generate` — there are two,
`datagen.generate.Generate` and `DocumentGenerator.Generate` — so `trace.history` actually pools three
commits across both; the model correctly led with the one that is both most recent and unambiguously
the top-level function's). See Defect 3 for a deeper, ground-truth problem with even the "correct"
answer here.

### Q5 (e) — "Which code writes the generated documents to a MongoDB collection?"

**Answer** (`shots/q5-mongo-writes-1-reasoning.jpg`): *"datagen/generate.go"* — **Wrong.** The real
writer is `datagen/datagen.go:246`, inside `insertDocumentFromChannel`:
`_, err := c.InsertMany(ctx, docs, insertOpts)`, reached via `fillCollection` → goroutines →
`insertDocumentFromChannel`; `datagen/generate.go`'s `run()` only calls `fillCollection`, it never
calls `InsertMany` itself. The model's own reasoning (fully expanded) explicitly admits it is
guessing: *"While the specific implementation lines are omitted (`...`), the package `datagen` is
explicitly defined as the tool that performs the insertion. The `run` function typically orchestrates
the generation and insertion process"* — a plausible-sounding but wrong file, arrived at because
`datagen/datagen.go` (the file that actually has the answer) never reached the top-5 passages sent to
the model: `traces/q5.json` (key `2dd39090f8c5`) shows it ranked **6th** by embedding score (0.8786),
one slot below the `qa_top_k=5` cut (rank 5 was 0.8805) — the same near-miss shape E1's Q4 found for a
different repo and a different cutoff. Root cause and full account in Defect 2.

---

## `meta["code"]` and indexing cost

**Dry run** (`readers.walk_repo` → `extract_code` → `chunk_documents`, no store, no Ollama, on a
throwaway local clone): 66 documents, 371 chunks, **95 chunks needing a real OpenIE call** (78 prose +
17 code passages with a docstring ≥ 80 chars).

**Actual**: indexed as a real background job on the live scratch server (source created
2026-09-09T21:26:08Z, ready 21:41:32Z) — **15.4 minutes**, well under the 45-minute target (the small
95-chunk OpenIE load, not the 200-commit-deep history read, dominates: history reading is a local git
subprocess, not an Ollama call).

```
meta["code"] = {
  "symbols": 230, "data_objects": 1, "edges": 544,
  "edges_by_kind": {"CONTAINS": 192, "IMPORTS": 12, "INHERITS": 28, "INVOKES": 192,
                     "OVERRIDES": 12, "READS": 1, "TESTED_BY": 107},
  "languages": ["go"],
  "files_parsed": 37, "files_skipped": {"parse_error": 0, "too_big": 0, "unsupported": 25},
  "unresolved_calls_total": 945,
  "truncated": false,
  "commits": 200, "modifies": 526, "history_skipped": 0
}
```
`meta["counts"]` (whole-source): 571 passages, 567 entities, 773 facts, 3777 synonyms, 39 REFERS_TO.

**`symbols: 230` in the per-source `meta` is the extractor's own count, computed before the store
write; the live store only holds 229** (`GET /api/status` → `stats.symbols: 229`, `code.symbols: 229`,
confirmed twice, and the navbar's own "Code 229 symbols" pill agrees). The missing one is
`main.go`'s module symbol, silently destroyed by an id collision — see Defect 1, where this exact
count mismatch is the cleanest piece of evidence.

**`commits: 200` is a cap, not the repository's actual commit count.**
`git rev-list --first-parent --count HEAD` on the real repo returns **265**; `code_history_depth`'s
default of 200 (clone depth 201) means the newest 200 first-parent commits were read and the oldest 65
were never seen. `history_skipped: 0` is correct on its own terms (nothing *inside* the read window
failed), but it does not mean "full history" the way it read on `territory-updater` in E1 (a
74-commit-long repo, under the depth default). No large-binary-commit crash (E1's Defect 1) was hit
here — this repo's `.git` is 1.0 MiB total, nothing like `territory-updater`'s vendored PDF library.

**`unresolved_calls_total: 945` against `INVOKES: 192`** is a 17% resolve rate (192 / (192 + 945)).
Per-file, `datagen/generate_test.go` alone accounts for 256 of the 945 — consistent with this being a
real Go test file full of `t.Errorf`, `bson.M{...}` construction and stdlib/testing-framework calls,
all correctly out of the resolver's in-repo-only scope, the same category QA1's own fixture excludes
by design (`print`/`os.path.join`/`console.log`). A closer per-file audit of the remainder was out of
scope for this run.

## CLI (against the running server)

`HIPPO_DATA_DIR=/tmp/hippo-e2go/data HIPPO_HOST=127.0.0.1 HIPPO_PORT=8015 .venv/bin/hippo ...`, every
command printed `(the database is open in hippo serve; asking the server at http://127.0.0.1:8015)`:

```
$ hippo path main datagen.generate.Generate
How main reaches datagen.generate.Generate:
main -[INVOKES 0.90 via_import]-> datagen.generate.Generate
```
(Note: the display name is `main`, not `main.main` — see Defect 1; `main.main` returns a 404.)

```
$ hippo blast datagen.generate.Generate --depth 2
What depends on datagen.generate.Generate (depth 2):
Level 1: datagen.generate, datagen.generate_test.BenchmarkGenerate, datagen.generate_test.TestCollectionCompression,
  datagen.generate_test.TestCollectionContent, datagen.generate_test.TestCollectionContentWithAggregation,
  datagen.generate_test.TestCollectionWithIndexes, datagen.generate_test.TestCollectionWithRef,
  datagen.generate_test.TestCreateEmptyFile, datagen.generate_test.TestCreateEmptyFileOverwrite,
  datagen.generate_test.TestGenerate, datagen.generate_test.TestInvalidAggregatorOutput,
  datagen.generate_test.TestInvalidGeneratorOutput, datagen.generate_test.TestProgressOutput, main
Level 2: datagen.collection.Collection, datagen.generate_test, datagen.generators.docbuffer.DocBuffer.Bytes,
  datagen.generators.generators.base.Key, datagen.options.Configuration, datagen.options.Connection,
  datagen.options.General, datagen.options.Options, datagen.options.Template
Subsystems: datagen.collection: ... (19 symbols, includes "main")
Subsystems: datagen.generators.array_generator: datagen.generators.docbuffer.DocBuffer.Bytes, datagen.generators.generators.base.Key
```

```
$ hippo history datagen.generate.Generate
Commits that touched datagen.generate.Generate, newest first:
80173a3 2021-07-20 rename mgodatagen.go into generate.go and format imports
```
This is precise but incomplete — see Defect 3: the function's real authorship commit, `83f441b`
("refactoring: split mgodatagen.go in 3 separate files for more clarity", first-parent position #92,
well within the 200-commit read depth), is never returned.

## Defects

### Defect 1 (major) — `main.go`'s module symbol and its `func main` collide on the same id; the module symbol is silently destroyed

**Where**: `src/hippo/codegraph/model.py:83-86`, `symbol_id(source_id, path, qualname)` hashes only
`(source_id, path, qualname)`. `codegraph/go.py:76-97` gives the **module** symbol
`qualname = module_qualname(path)`; `codegraph/go.py:158-163` gives a **bare top-level function**
`qualname = name` (no receiver). Whenever a file's own base name (module_qualname, `.go` stripped)
equals one of its own top-level declared names, both symbols get `(path, qualname)` = the same pair,
so `symbol_id` returns the same id for two logically distinct `Symbol` objects. This is **not
Go-specific in principle** — a Python `foo.py` with a top-level `def foo():`, or a JS `utils.js` with
`function utils() {}`, hits the identical collision — but Go's own idiom makes `main.go` containing
`func main()` the single most common trigger in the whole language: virtually every Go program has
this exact file/function pairing.

**Confirmed, three independent ways:**
1. **Count mismatch.** `meta["code"]["symbols"]` (the extractor's own count, before the store write)
   is 230; `GET /api/status` reports 229, confirmed twice (`stats.symbols` and `code.symbols`), and
   the running server's own navbar pill says "Code 229 symbols." Exactly one symbol is missing.
2. **The missing symbol is identifiable.** `GET /api/code/symbols?q=main` returns **one** row for
   `main.go` (`code_kind: "function"`, `line_start: 20, line_end: 44` — `func main()`'s own range),
   never a second `code_kind: "module"` row. Every other file in the repo has both: e.g.
   `?q=Generate` returns both `datagen.generate` (`code_kind: "module"`, lines 1-242) and
   `datagen.generate.Generate` (`code_kind: "function"`, lines 30-32) as separate rows.
3. **The graph damage is visible.** `GET /api/graph/node/symbol-e70b24885545491f7ddf053ee83ad005`
   (the surviving `main` node) has **zero `CONTAINS` edges** — no other file's module symbol lacks a
   `CONTAINS` edge to its own top-level declarations (`datagen.generate`, for comparison, has six).
   Instead it has **two different `DEFINED_IN` edges to two different passages**:
   `main.go :: main (lines 1-19)` (the module-header chunk — package clause, imports) and
   `main.go :: main.main (lines 20-44)` (the function-body chunk) — both attached to the same node,
   which is exactly what "two symbols merged onto one id" looks like from the DEFINED_IN side. The
   second passage's own title, `main.main`, is what the extractor *originally* computed
   (`display=f"{module}.{qualname}"`, `go.py:174`) before the collision and the read-time collapse
   rule (`display_of`, `paths.py:95-97`: `if qualname == module: return qualname`) both apply —
   the two symbols were genuinely distinct at extraction time and only merged at the store write.

**Consequence for retrieval**: because the module symbol is gone, `main.go` — the file containing the
program's actual entry point and its one real `Generate(...)` call — has no `CONTAINS` edge a path
walk could use to relate "the file" to "the function," and no separate node a question about "the
`main` package" could land on distinct from a question about the `main` function itself.

**Suggested fix** (not applied — QA does not edit source): give the module symbol a namespaced
qualname distinct from any of its own top-level declarations before hashing — e.g.
`symbol_id(source_id, path, f"<module>:{module}")`, or detect the collision in `_declarations`
(`go.py`) and suffix one side. The same fix shape applies to every language's module-symbol
construction, not just `go.py`.

### Defect 2 (major) — the MongoDB data-access extractor cannot see any of this tool's real writes, because every real collection name is a variable, never a literal

**Where**: `src/hippo/codegraph/data_access.py:295-307`, `collection_of()`. The function *does*
explicitly handle Go's call-based collection idiom (`client.Database("app").Collection("archive_orders")`,
named in the module comment at line 87) via `COLLECTION_MARKER`
(`data_access.py:90-93`): `^(?:...|Collection|...)\(\s*["'`]([A-Za-z_]\w*)["'`]\s*(?:,[^)]*)?\)$` —
but that pattern requires the argument to be a *quoted string literal*. Every real production call
site in this repository is `d.session.Database(coll.DB).Collection(coll.Name)`
(`datagen/datagen.go:104,218,321,385`; `datagen/generators/aggregators.go:50,97,112`) — `coll.Name` is
a struct field holding a value parsed from the user's own JSON config at runtime, never a literal in
source. `collection_of` returns `""` for a non-literal argument by construction, so `mongo_hit` never
fires for any of these seven call sites, even though `InsertMany`/`CountDocuments`/`Aggregate` are all
correctly listed in `MONGO_WRITES`/`MONGO_READS` (`data_access.py:68-82`) — **the method-name
recognition is not the gap; the literal-only receiver match is.**

**Measured impact**: `meta["code"]["edges_by_kind"]` has **no `WRITES` key at all** — zero WRITES
edges across the whole 230-symbol repo — and exactly **one `READS`** edge, which traces to the single
literal collection name anywhere in the source: `session.Database("mgodatagen_test").Collection("test_bson")`,
in a *test* file (`datagen/generate_test.go:974`), not production code.

**This is a different, narrower failure than E1's Defect 2 on `territory-updater`.** There, the gap
was idiom coverage (a Node app's call-based idiom wasn't recognized at all). Here the call-based idiom
*is* recognized — the gap is categorical: **a tool whose entire purpose is generic, config-driven
data access will never have a literal collection name in its own source**, by definition of what makes
it generic. Any similarly-generic data-access library, ORM, or ETL tool in any language will hit the
same wall for the same reason, regardless of how complete the literal-matching regex is.

**User-facing symptom**: Q5 above answers with the wrong file (`datagen/generate.go`, the orchestrator,
not `datagen/datagen.go`, the inserter) because there is no `DataObject` node for any collection at all
to anchor the question on, and the real inserter file narrowly misses the top-5 passage cut (rank 6 of
score 0.8786 vs. the cutoff at rank 5's 0.8805).

**Suggested fix** (not applied): out of scope for a purely lexical/literal extractor — a fix would
need either symbolic tracking of what a variable's value *could* be (a much bigger feature) or
accepting the limitation and documenting it: this class of extractor is reliable for apps with a fixed,
literal schema (most business apps) and structurally blind for generic/parameterized data tools.

### Defect 3 (moderate) — git history tracking does not follow file renames; a symbol's true authorship commit is invisible across one

**Where**: `Generate`'s real origin is commit `83f441b` ("refactoring: split mgodatagen.go in 3
separate files for more clarity"), which created these exact three lines
(`func Generate(options *Options, out io.Writer) error { return run(options, out) }`) inside
`datagen/mgodatagen.go`. `git log -L30,32:datagen/generate.go` on the real repo confirms this directly
— it is the *only* commit that ever touched this line range's content. A later commit, `80173a3`
("rename mgodatagen.go into generate.go and format imports"), renamed the file with no content change
to these lines. `83f441b` is first-parent commit **#92** of 265 — comfortably inside the 200-commit
depth this run actually read (confirmed: `git log --oneline --first-parent | grep -n 83f441b` → line
92) — so this is not a depth-truncation artifact.

**But `hippo history datagen.generate.Generate` and `trace.history` both only ever return commits from
`80173a3` onward** — never `83f441b`. Root cause, confirmed directly:
`src/hippo/codegraph/git_history.py:76-78` sets `DIFF_OPTIONS` to include `"--no-renames"`, with the
comment *"-M off: history before a rename is ignored in phase 1"* — a deliberate, known limit, not an
oversight. Rename detection off means a rename-only commit's diff (like `80173a3`) is a delete of the
whole old path plus an add of the whole new path, which two things follow from directly: (1) MODIFIES
correlation, keyed on the symbol's *current* path, only ever sees commits from the point the file had
its current name onward — `83f441b`'s diff is against `datagen/mgodatagen.go`, a path that no longer
exists, so it is structurally invisible to any symbol now living in `datagen/generate.go`; (2) the
rename commit itself gets **over-attributed** as modifying *every* symbol the file contains, not just
the ones actually touched by the rename+reformat, because a whole-file add looks identical to a
whole-file rewrite. Confirmed directly against the running server:
```
$ hippo history datagen.generate.run
80173a3 2021-07-20 rename mgodatagen.go into generate.go and format imports
$ hippo history datagen.generate.connectToDB
431d2c5 2021-07-20 remove topology time from shard list details
80173a3 2021-07-20 rename mgodatagen.go into generate.go and format imports
```
`80173a3` shows up for `run` and `connectToDB` too — every top-level symbol in `generate.go` gets
credited with the rename commit, the predictable consequence of `--no-renames` turning a content-
preserving rename into what looks like a full rewrite.

**User-facing symptom**: Q4's "correct" backtick-variant answer, `80173a35f3`, is precise for "some
commit that touched a file named `generate.go` containing `Generate`" but is both under- and
over-inclusive for "the commit that wrote this function" — it misses the real originating commit
(`83f441b`, pre-rename) and would return the same rename commit for essentially every other symbol in
the file too, a user asking "which commits touched `Generate`" specifically would have no way to tell
this answer apart from the same answer for `run` or `connectToDB`.

**Suggested fix** (not applied): turn rename detection on (`-M` / drop `--no-renames`) so a
content-preserving rename diffs as a small rename entry rather than a full delete+add, which would fix
both symptoms — MODIFIES could then follow a symbol across its file's rename, and the rename commit
itself would stop being over-attributed to every symbol in the file.

## Surprises

1. **Go's own naming convention (one capitalized word, no internal hump — `Generate`, `Run`, `New`)
   is the textbook negative case of the bare-word anchor rule, and it bites hard and often.**
   `anchors.py:119`, `_PASCAL = re.compile(r"^[A-Z][a-z0-9]*(?:[A-Z][a-z0-9]*)+$")`, requires **two or
   more** capitalized humps; `_CAMEL`/`_SNAKE`/`_ALLCAPS` don't match a single title-cased word either.
   A bare, untyped "Generate" in a question is therefore never `_code_shaped` and never anchors —
   confirmed three separate times in this run (Q1, Q2, Q4's bare-word ask), every time landing on
   `used_code_seeds=False`. This is **not a defect**: `anchors.py:16` documents the rule precisely
   ("bare word anchors here only when its surface form is code-shaped: qualified (`a.b`), backticked,
   ...") and `anchors.py:491` only applies `_code_shaped` when `surface == "bare"` — a **backticked**
   token skips the shape check entirely. Re-asking Q1 and Q4 with backticks
   (`` What does `Generate` do? ``, `` Which commits touched `Generate`? ``) immediately flips
   `used_code_seeds` to `True` and produces a tighter, better-grounded answer both times (see Q1/Q4
   Variant). This is the documented Ruling 1a boundary working as designed — but it is worth a clear
   line in the docs for Go specifically: Python/JS/C#'s everyday naming style (`getUserById`,
   `snake_case_thing`) clears the bare-word bar effortlessly; idiomatic Go's single-word exported names
   almost never do, so a Go user typing a natural-language question without backticks will hit this
   boundary far more often than a Python or JS user asking the analogous question. The brief's own
   question template already uses backticks for exactly this reason; I initially typed the first pass
   without them, which is what surfaced this as clearly as it did.
2. **Struct embedding shows up as `INHERITS`.** `fromArrayGenerator -[INHERITS 0.90 resolved]->
   ...generators.base` (Q3's Code graph block) — a deliberate design choice
   (`codegraph/go.py:247-253`, "Struct embedding is Go's inheritance... INHERITS means here," D: Go),
   correctly reflecting that Go's embedding promotes methods the way inheritance would. Reads oddly on
   first sight to anyone expecting classical OOP inheritance from a language that has none, but it is
   the right modeling call given the graph's fixed edge-kind vocabulary. 28 INHERITS + 12 OVERRIDES
   edges across the whole repo, all from struct embedding, none a bug.
3. **The ambiguous-name resolution for the backtick variant of Q4 quietly does the right thing.**
   Two symbols in this repo are literally both named `Generate` (`datagen.generate.Generate` and
   `DocumentGenerator.Generate` in `generators.go`). The `` `Generate` `` identifier chip matches both;
   `trace.history` pools three commits across the two (`80173a35f3`, `e544cddd`, `7300dad`), and the
   model's final answer led with the one that is both newest and correctly the top-level function's —
   a reasonable resolution of a genuinely ambiguous question, not something to file as a defect.
4. **A shallow local clone through a `clone_repo` monkeypatch worked cleanly and left the real
   checkout untouched**, including its history: `git clone --depth 201 --single-branch -- <local path>
   <dest>` clones only committed content as of `HEAD`, so the user's own uncommitted whitespace edits
   and untracked scratch files in the real `/Users/mascott/projects/mgodatagen` were never read or
   risked. See Methodology.

## Methodology note: indexing a local repo as a "repo" source

The brief asks to index the repo "as a repo source" (so `meta["code"]["commits"]`/`modifies` populate,
unlike an upload/zip source), but `hippo`'s repo ingestion (`ingest/repos.py::clone_repo`,
`is_git_url`) only accepts a real `https://`/`ssh://`/`git@` URL and refuses anything that looks like a
local path — by design, so a user can never point the server at an arbitrary filesystem path. Following
E1's precedent, a scratch launcher ran the real `hippo.web.app` in-process and monkeypatched
`hippo.ingest.repos.clone_repo` to always `git clone` from the real local path regardless of the URL
string, before starting uvicorn — so the patch was active for every request from the first byte served.
The source was then added through the real `POST /api/sources/repo` with a syntactically-valid but
fake URL (`https://local.e2go/mascott/mgodatagen`, used only for `repos.is_git_url`'s validation and
the source's display name); the patched `clone_repo` ignored it and always cloned
`/Users/mascott/projects/mgodatagen`. This is a `git clone` of the **local** repository — it only ever
reads that repo's own `.git` objects up to its current `HEAD`, the same as cloning any other
repository from a filesystem path; it neither reads the working tree's uncommitted changes nor writes
anything back to the source repository. Script quoted in full (deleted with the rest of the scratch
data per the brief once this report was committed):

```python
# serve_with_local_clone.py
"""
E2-go launcher: runs the real hippo web app in-process (so we can monkeypatch
hippo.ingest.repos.clone_repo before any request arrives) on port 8015, data dir
/tmp/hippo-e2go/data, against the real host Ollama.

repos.clone_repo() normally shallow-clones a real git URL. mgodatagen lives on local disk
(/Users/mascott/projects/mgodatagen), not a remote, and is never to be written to -- so this
patches clone_repo to do a *local* `git clone` (git clone from a filesystem path only ever reads
the source repo's committed history; it does not touch or require write access to the source).
The fake URL used when adding the source (https://local.e2go/mascott/mgodatagen) exists only so
`repos.is_git_url` (unmodified) accepts it and the Source row has a sensible display name; the
patched clone_repo ignores it and always clones from LOCAL_REPO.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/Users/mascott/projects/hippo/.worktrees/e2go")
sys.path.insert(0, str(REPO_ROOT / "src"))

LOCAL_REPO = Path("/Users/mascott/projects/mgodatagen")

os.environ["HIPPO_DATA_DIR"] = "/tmp/hippo-e2go/data"
os.environ["HIPPO_STORE"] = "ladybug"
os.environ["HIPPO_OPENIE_WORKERS"] = "1"
os.environ["HIPPO_LLM_MODEL"] = "qwen3.8:latest"
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")

from hippo.ingest import repos  # noqa: E402


def _local_clone_repo(url: str, dest: Path, timeout: int = 300, depth: int = 1) -> Path:
    depth = max(1, depth)
    if dest.exists() and any(dest.iterdir()):
        raise repos.RepoError(f"the folder {dest} already exists and is not empty")
    dest.parent.mkdir(parents=True, exist_ok=True)
    command = ["git", "clone", "--depth", str(depth), "--single-branch", "--", str(LOCAL_REPO), str(dest)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as err:
        raise repos.RepoError(f"local clone of {LOCAL_REPO} took longer than {timeout}s") from err
    if result.returncode != 0:
        raise repos.RepoError(f"local clone of {LOCAL_REPO} failed: {result.stderr.strip()}")
    return dest


repos.clone_repo = _local_clone_repo  # patched before create_app/uvicorn ever see a request

import uvicorn  # noqa: E402

from hippo.web.app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8015, log_level="info")
```

Trace JSON for every question was captured the same way E1/QA1 did: each Ask-page answer links to
"Analyze this question" (`/analyze?key=<trace_key>`), and `POST /api/simulate
{"trace_key": ..., "overrides": {}}` replays the exact stored trace with no additional real-Ollama
cost (confirmed: replay `timing_ms.total` is one to three orders of magnitude smaller than the
original ask — e.g. Q1's original ask was 7989 ms, its replay was 37.9 ms). The **displayed** timing in
the table above is always the real, first-ask wall time from the Ask page UI, never the replay's.

## Cleanup

Server stopped after this report was written; `/tmp/hippo-e2go` removed except `shots/` and `traces/`.
No file under `src/` or `tests/` was edited — this is a QA/exploration report only.
