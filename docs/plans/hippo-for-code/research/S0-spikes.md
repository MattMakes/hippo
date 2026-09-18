# S0 — the three pre-WP1 spikes

Run 2026-09-07 in the root tree (`code-graph`), read-only; every script lives under `/tmp/hippo-s0/` and is
quoted in full below. `PLAN.md` §"Pre-WP1 spikes (V2.7)" lines 408-414 is the brief.

| Spike | Verdict | The number that decides it |
|---|---|---|
| 1 — bare-word anchors on prose | **FAIL as planned. Ship fallback (b): a bare word anchors only in a qualified, backticked or multi-case surface form.** The stoplist is the wrong mechanism and becomes unnecessary. | Plain rule + stoplist fires on **16% of prose questions** against django's symbol set (4% against hippo's own). Fallback (b) fires on **0/118 for all four repos tested**, at a cost of 5 of 18 bare-identifier questions. |
| 2 — symbol↔entity synonyms under nomic-embed-text | **Threshold is safe; the generic-name risk is real. Ship remedy 2: a cross-kind SYNONYM needs ≥ 2 split tokens on the symbol side. Do NOT raise the threshold.** | **40% of the 20 cross-kind pairs ≥ 0.80 are nonsense**, and raising the threshold to 0.85 makes it **43%** while costing a known-good pair. The ≥ 2-token rule takes it to 27% and drops **zero** of 10 known-good pairs. |
| 3 — where a real repo lands on the write curve | **No change needed. 5 000-row batches are enough, and the `NOT EXISTS` guard that stands in for `MERGE` is free.** `MAX_CHUNKS` binds long before the curve turns bad. | The **largest source hippo will accept** — 20 000 symbols, 100 000 relationships — writes in **87 s**, and the guarded shape costs the same (**85.8 s**). django-shaped (12 317 symbols) is **23.5 s**. The real cost is 117 MiB of vectors reloaded on every graph-version bump, not the write. |

---

## Spike 1 — do lexical anchors fire on ordinary prose?

### Method

Four ingredients, each a script below.

1. **The symbol-name set.** An `ast` walk of `src/hippo` collecting module stems, classes, functions and
   methods by `name` (not qualname): **807 symbols, 644 distinct lowercased names**. The same walk was run
   over three cloned reference repos so the rate could be measured against a symbol set larger than hippo's.
2. **The question corpus, 118 prose questions in three buckets** kept separate because they behave
   differently: **29 harvested** (every quoted `…?` string in `tests/`, `README.md`, `docs/`, `samples/`,
   `src/`), **34 generated** (exactly what `FakeOllama.questions()` produces from `samples/acme_robotics.md`,
   i.e. the eval question set the suite really exercises), and **55 hand-written** about the sample document,
   written naturally and deliberately *not* avoiding words that happen to be hippo symbol names. Plus
   **22 identifier questions** a developer would actually type about hippo's own code, including seven that
   name a single-token lowercase symbol bare ("what does run do", "where is search implemented").
3. **The tokenizer.** Backticked spans and dotted spans (`GraphIndex.load`) stay whole, because S2.13 says a
   path-qualified match is never split and fallback (b) is defined on that surface. Everything else splits on
   non-word characters.
4. **The rules.** The plain rule (token ≥ 3 chars, not stoplisted, exact lowercase `name` hit) with a 290-word
   stoplist (NLTK's 179 English stopwords inlined, plus ~110 obvious code words), plus the plan's two
   fallbacks and one extra variant priced for comparison. S2.13's ambiguity rule (drop a token matching > 10
   symbols) is applied on top, since that is what WP3 actually ships.

### Numbers

False-anchor rate = prose questions producing ≥ 1 anchor. Every cell is `fired / 118`.

Against **hippo's own** 807 symbols:

| Rule | Stoplist | harvested | generated | hand-written | ALL | identifier questions kept |
|---|---|---|---|---|---|---|
| plain | off | 1/29 | 1/34 | 10/55 | **12/118 (10%)** | 21/22 |
| plain | on | 0/29 | 1/34 | 4/55 | **5/118 (4%)** | 18/22 |
| (a) ≥ 2 split tokens | on | 0/29 | 0/34 | 0/55 | **0/118 (0%)** | 13/22 |
| (b) qualified surface | on | 0/29 | 0/34 | 0/55 | **0/118 (0%)** | 13/22 |
| (c) not an English word | on | 0/29 | 0/34 | 0/55 | **0/118 (0%)** | 15/22 |

S2.13's ambiguity rule changes nothing here: **no hippo name matches more than 10 symbols**, so it never
fires. It is not a defence against this failure mode.

The rate is a function of the indexed repo's size, which is the part that settles the verdict. Same corpus,
same rules, symbol set swapped (stoplist on, ambiguity applied, and the ≥ 3-character test on the matched
name segment per finding 2 below — without that fix (a) and (b) each leave one residual on django and
pandas):

| Repo | symbols | distinct names | plain | (a) | (b) | (c) | plain, no stoplist |
|---|---|---|---|---|---|---|---|
| hippo `src/hippo` | 807 | 644 | 4% | 0% | 0% | 0% | 10% |
| flask `src` | 464 | 322 | 2% | 0% | 0% | 0% | 3% |
| django `django` | 12 317 | 6 475 | **16%** | 0% | 0% | 1% | **36%** |
| pandas `pandas` | 33 975 | 26 091 | 7% | 0% | 0% | 2% | 25% |

The tokens that fire on hippo are `library` ×4 ("Who maintains the Halo library?") and `check` ×1; without
the stoplist also `can`, `sources`, `status`, `main`, `start`, `describe`, `source`. On django they are
`country` ×4, `library` ×4, `city` ×2, `date`, `language`, `tell`, `connection`, `difference`, `site`,
`serve`, `dates`, `quality` — ordinary English nouns, one per model class.

**Three findings the numbers surfaced that the plan does not state.**

1. **The stoplist cannot be both safe and useful.** Adding the code words that suppress the false anchors
   (`status`, `run`, `search`, `source`, `index`, `config`) also kills three of the 22 genuine identifier
   questions — "how does status work", "what does run do", "where is search implemented" — because those are
   the same words. Growing the stoplist to cover django's `country`/`city`/`date` makes it a general English
   dictionary, which is variant (c).
2. **The `≥ 3 characters` test must apply to the segment matched against `Symbol.name`, not to the raw
   token.** As written it is checked on the whole token, so the dotted prose token `S.O.B.` (from a harvested
   question about a film) falls through to its last segment `b` and anchors on django's `DateFormat.b`. With
   the test moved onto the matched segment, both fallbacks go to **0/118 on all four repos**, django and
   pandas included. This is a one-line fix in WP3.1 and it is what makes the 0% claim hold at scale.
3. **A prose abbreviation with internal periods is parsed as a dotted qualified identifier.** `S.O.B.`,
   `U.S.A.`, `e.g.` all reach the qualified branch, which is exempt from every bare-word defence. Require
   each dot-separated part to be ≥ 2 characters before treating a dotted token as qualified.

**What fallback (b) costs.** Of the 18 identifier questions that anchor under the plain rule, 5 stop
anchoring: "explain how settings are validated", "what does load do in the graph index", "what does the ask
command do", "what does the retriever module do", "where does the indexer save entities". All five name a
**single-token lowercase** symbol with no qualification. **156 of hippo's 650 distinct names are single-token
under the landed `split_identifier`, 100 of them lowercase alphabetic**, so this is a real class, not an edge
case. Those questions do not fail — the code
passage can still arrive by dense seeding — they just do not flip `used_code_seeds`, so they get no select
pass, no path block and no `timing["paths"]`. Typing ``what does `load` do`` or `GraphIndex.load` restores
all of it.

Fallback (a) and fallback (b) scored identically on every corpus and every repo. They coincide because a bare
lowercase token cannot yield two split tokens, so (a) is also a surface-form test once you read it as
splitting the *typed token* rather than the symbol name. (b) is the better spelling of the same rule: it is
defined on what the user typed, so it is independent of the indexed repo's naming, and it is directly
testable. Variant (c) — accept a bare token that is not in the system English word list — keeps 2 more
identifier questions but reintroduces 1-2% false anchors on django and pandas and would need a wordlist
shipped with hippo. Not worth it.

### Recommendation for WP3

> **Ship fallback (b), not the stoplist.** In `anchors.py`, a bare word anchors only when its surface form is
> qualified (`a.b.c`), backticked, or carries an internal case or underscore boundary — PascalCase
> (`OrderService`), camelCase (`getUser`), snake_case (`ensure_schema`) or ALL_CAPS (`MAX_CHUNKS`). A bare
> all-lowercase single-token word never anchors, whatever the stoplist says. This measured **0 false anchors
> on 118 prose questions against all four symbol sets tested**, including django's 12 317 symbols and pandas'
> 33 975, where the planned rule fires on 16% and 7% of prose questions respectively.
>
> Two corrections go with it, both one-liners, and the 0% number depends on the first: apply the ≥ 3-character
> minimum to the segment actually matched against `Symbol.name` rather than to the raw token (otherwise the
> prose token `S.O.B.` anchors on a one-character method name), and require each dot-separated part of a
> token to be ≥ 2 characters before treating it as qualified (otherwise abbreviations enter through the
> qualified branch, which bypasses every bare-word defence).
>
> Keep a small stoplist only for the qualified branch if you want; on this corpus it becomes inert once (b) is
> in, and `test_anchors.py`'s "prose → `[]`" case should assert that with the stoplist emptied, which is a
> stronger test than the one the plan describes.
>
> Accept the cost and document it: a question naming a single-token lowercase symbol bare ("what does run
> do", "where is search implemented") produces no lexical anchor, so `used_code_seeds` stays False and the
> select pass, path block and `timing["paths"]` do not run. 100 of hippo's 644 names are in that class. The
> passage can still arrive by dense seeding; backticks or a qualname restore anchoring. This belongs in
> `docs/FIDELITY.md`'s adaptation 15 and in the Ask page hint text.
>
> S2.13's ambiguity rule (> 10 matches → drop) is **not** a defence against prose anchoring and should not be
> credited as one: no hippo symbol name matches more than 10 symbols, so it never fires on this corpus. It
> earns its place on large repos for a different reason — 100 django names and 148 pandas names exceed the
> threshold.

### Scripts

`/tmp/hippo-s0/symbols.py` — the shared `ast` walk (spikes 2 and 3 reuse its output):

```python
import ast, json, sys
from collections import Counter
from pathlib import Path

def walk(root: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        stem = path.stem
        if stem != "__init__":
            out.append({"name": stem, "kind": "module", "qualname": rel[:-3].replace("/", "."),
                        "path": rel, "line": 1})
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        modq = rel[:-3].replace("/", ".")

        def visit(node: ast.AST, prefix: str, in_class: bool) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    q = f"{prefix}.{child.name}"
                    out.append({"name": child.name, "kind": "class", "qualname": q,
                                "path": rel, "line": child.lineno})
                    visit(child, q, True)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    q = f"{prefix}.{child.name}"
                    out.append({"name": child.name, "kind": "method" if in_class else "function",
                                "qualname": q, "path": rel, "line": child.lineno})
                    visit(child, q, False)
                else:
                    visit(child, prefix, in_class)   # nested defs inside if/try/with

        visit(tree, modq, False)
    return out

if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "src/hippo").resolve()
    symbols = walk(root)
    Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/hippo-s0/symbols.json").write_text(json.dumps(symbols, indent=1))
    print(f"symbols={len(symbols)} kinds={dict(Counter(s['kind'] for s in symbols))}")
```

`/tmp/hippo-s0/spike1_anchors.py` — the tokenizer, the scratch `split_identifier`, and the four rules
(`corpus.py`, which harvests the 118 questions, is quoted in the appendix):

```python
import json, re
from collections import Counter

SYMBOLS = json.load(open("/tmp/hippo-s0/symbols.json"))
NAME_HITS = Counter(s["name"].lower() for s in SYMBOLS)      # pre-cap match count, per S2.13
QUALNAMES = {s["qualname"].lower() for s in SYMBOLS}
SUFFIXES = set()                                              # every dotted suffix of every qualname
for s in SYMBOLS:
    parts = s["qualname"].lower().split(".")
    for i in range(len(parts)):
        SUFFIXES.add(".".join(parts[i:]))

STOPLIST = set(NLTK_179_STOPWORDS) | set(CODE_STOPWORDS)      # 290 words, inlined, no nltk dependency
STRICT_LENGTH = False        # True = apply the >=3 test to the matched name segment (finding 2)

BACKTICKED = re.compile(r"`([^`\n]+)`")
QUALIFIED  = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
BARE       = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PASCAL  = re.compile(r"^[A-Z][a-z0-9]*(?:[A-Z][a-z0-9]*)+$")
CAMEL   = re.compile(r"^[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+$")
SNAKE   = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$")
ALLCAPS = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")

def tokenize(question: str) -> list[tuple[str, str]]:
    """-> [(token, surface)]; surface is backtick | qualified | bare. Qualified and backticked
    spans stay whole (S2.13: a path-qualified match is never split)."""
    out = []
    for m in BACKTICKED.finditer(question):
        out.append((m.group(1).strip(), "backtick"))
    rest = BACKTICKED.sub(" ", question)
    spans = []
    for m in QUALIFIED.finditer(rest):
        out.append((m.group(0), "qualified"))
        spans.append(m.span())
    masked = list(rest)
    for a, b in spans:
        for i in range(a, b):
            masked[i] = " "
    for m in BARE.finditer("".join(masked)):
        out.append((m.group(0), "bare"))
    return out

# The scratch splitter: hipporag/text.py had no split_identifier() when this ran. WP0 landed the
# real one mid-run; the two agree on all 650 hippo names (see the appendix). Prefer the real one.
SPLIT_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+|[0-9]+")

def split_identifier(name: str) -> list[str]:
    parts = []
    for chunk in re.split(r"[._\-/\s]+", name):
        for piece in SPLIT_RE.findall(chunk or ""):
            parts.extend(p for p in re.split(r"(\d+)", piece) if p)
    return [p.lower() for p in parts]

def anchors_plain(question, *, use_stoplist, apply_ambiguity):
    """WP3.1 as written: token >= 3 chars, not stoplisted, exact lowercase `name` hit."""
    hits = []
    for token, surface in tokenize(question):
        low = token.lower()
        if len(low) < 3:
            continue
        if surface in ("qualified", "backtick") and (low in QUALNAMES or low in SUFFIXES):
            hits.append({"token": token, "surface": surface, "n": 1})
            continue
        base = low.split(".")[-1]
        if STRICT_LENGTH and len(base) < 3:
            continue
        if use_stoplist and base in STOPLIST:
            continue
        n = NAME_HITS.get(base, 0)
        if n == 0 or (apply_ambiguity and n > 10):   # S2.13: >10 matches -> dropped as ambiguous
            continue
        hits.append({"token": token, "surface": surface, "n": n})
    return hits

def anchors_two_token(question, **kw):      # fallback (a)
    return [h for h in anchors_plain(question, **kw)
            if h["surface"] != "bare" or len(split_identifier(h["token"])) >= 2]

def anchors_qualified(question, **kw):      # fallback (b) -- the recommendation
    out = []
    for h in anchors_plain(question, **kw):
        t = h["token"]
        if h["surface"] != "bare" or PASCAL.match(t) or CAMEL.match(t) or SNAKE.match(t) or ALLCAPS.match(t):
            out.append(h)
    return out

def anchors_not_a_word(question, **kw):     # variant (c), not in the plan, priced for comparison
    words = {w.strip().lower() for w in open("/usr/share/dict/words")}
    out = []
    for h in anchors_plain(question, **kw):
        t = h["token"]
        if (h["surface"] != "bare" or PASCAL.match(t) or CAMEL.match(t) or SNAKE.match(t)
                or ALLCAPS.match(t) or t.lower() not in words):
            out.append(h)
    return out

def measure(questions, rule, **kw):
    fired, tokens = 0, Counter()
    for q in questions:
        hits = rule(q, **kw)
        if hits:
            fired += 1
            for h in hits:
                tokens[h["token"].lower()] += 1
    return fired, tokens
```

`/tmp/hippo-s0/spike1_scale.py` swaps `SYMBOLS`/`NAME_HITS`/`QUALNAMES`/`SUFFIXES` for each cloned repo
(`git clone --depth 1` of flask, django and pandas into `/tmp/hippo-s0/repos/`) and re-runs `measure` over
the same corpus. That is the whole of it.

---

## Spike 2 — symbol↔entity synonyms under the real embedder

### Method

The configured model is `nomic-embed-text` (`config.py:50`, `.env.example:35`; `.env` sets nothing, so the
default stands). It is pulled: `curl localhost:11434/api/tags` lists `nomic-embed-text:latest`, 137 M, 768
dimensions. The threshold is `synonymy_threshold = 0.8` from `DEFAULT_SETTINGS` (`store/base.py:18`),
enforced in `find_synonyms` (`indexer.py:247-279`) as a **plain dot product of unit vectors** —
`new_vectors @ keys.T`, no separate cosine step, because `Ollama.embed` L2-normalises every row
(`ollama.py:188-192`). So reproducing the score exactly means embedding both sides through
`Ollama.embed(..., kind="document")`, which is what `indexer.py:143` does for entity names and what A's plan
(line 148) specifies for symbols; that applies nomic's `search_document: ` prefix
(`ollama.py:31-34`) to both sides.

Both sides were built the way the shipped code would build them:

- **Symbol side, 200 `name_text()` strings.** `name_text(name)` per A §model.py is the split tokens plus the
  original spelling when it differs (`OrderService → "order service OrderService"`). Every distinct name from
  spike 1's walk, sampled with `random.Random(0)`, with 20 deliberately generic names forced in (`run`,
  `save`, `main`, `total`, `get`, `load`, `close`, `start`, `status`, `search`, `index`, `answer`, `ask`,
  `check`, `library`, `source`, `settings`, `stats`, `config`, `render`).
- **Entity side, 132 phrases in two buckets.** 30 real entity names from `samples/acme_robotics.md`, produced
  by running the real chunker plus `FakeOllama`'s NER through `clean_phrase` and `is_meaningful_phrase` with
  no store; plus **102 generic English noun phrases written by hand** as an adversarial set ("order service",
  "billing", "the total", "run", "main office", "save file", "quality check", "the library", "the supplier"…).
- **10 known-good cross-kind pairs** whose scores any recommended threshold must keep.

26 400 pairs scored. `is_meaningful_phrase` gates the symbol side, exactly as `find_synonyms` does.

### Numbers

| Band | pairs | share of 26 400 |
|---|---|---|
| ≥ 0.90 | 4 | 0.015% |
| ≥ 0.85 | 7 | 0.027% |
| **≥ 0.80 (shipped threshold)** | **20** | **0.076%** |
| ≥ 0.75 | 68 | 0.258% |
| ≥ 0.70 | 406 | 1.538% |

**Volume is not the problem: 0.10 pairs per symbol at the shipped threshold.** Two things about the 20 pairs
matter more than the count.

**First, all 20 came from the invented generic phrases. Zero came from the sample document's real entities.**
The acme corpus's entities are proper nouns — Acme Robotics, Priya Natarajan, Boulder, Orion arm — and no
hippo symbol reaches 0.80 against any of them. So on the shipped fixture and on any prose memory whose
entities are named things, D7 costs nothing. The risk is specific to prose about *generic business nouns*,
which is what a mixed code-and-docs memory actually contains.

**Second, hand-labelling the 20** ("sensible" = a reader would accept them as the same thing) gives
**8 nonsense, 40%**. The nonsense is exactly what the plan predicted, generic single-word names:

| score | symbol | prose phrase | |
|---|---|---|---|
| 0.9376 | `library` | the library | hippo's eval-library module vs a software library |
| 0.8698 | `run_form` | run | a web form handler pulled by a bare noun |
| 0.8600 | `main` | main office | |
| 0.8442 | `RunBody` | run | a request-body dataclass |
| 0.8361 | `check` | quality check | |
| 0.8139 | `run_stdio` | run | starts the MCP stdio server |
| 0.8086 | `ask` | search results | |
| 0.8040 | `source` | the supplier | |

**Raising the threshold does not work, and this is the finding that settles the verdict.** The nonsense is
concentrated at the *top* of the ranking, because a one-word symbol name embeds almost identically to a short
phrase containing that word.

| Remedy | pairs kept | nonsense | known-good pairs lost |
|---|---|---|---|
| threshold 0.80 (as shipped) | 20 | 8 (**40%**) | 1 — `read_history ~ commit history` (0.7223) |
| threshold 0.85 | 7 | 3 (**43%**) | 1 |
| threshold 0.90 | 4 | 1 (25%) | **3** — also `find_synonyms ~ synonyms` (0.8732), `build_igraph ~ igraph` (0.8637) |
| **≥ 2 split tokens on the symbol side, threshold stays 0.80** | 11 | 3 (**27%**) | **0** |
| ≥ 2 tokens on both sides | 6 | 0 (**0%**) | 0 pairs, but 2 entity phrases (`synonyms`, `igraph`) become unreachable |

The ≥ 2-token rule drops exactly the nine one-word symbols — `run`, `library`, `save`, `search`, `main`,
`check`, `ask`, `lookup`, `source` — and **all ten known-good symbols survive it**, including D7's motivating
case `OrderService ~ order service` at 0.9368. The three surviving nonsense pairs (`run_form`, `RunBody`,
`run_stdio`, all pulled by the single-word prose entity "run") are what the symmetric version would remove,
at the cost of single-word domain entities.

Known-good scores, for the record: `chunk_document ~ document chunk` 0.9680, `RemoteHippo ~ remote hippo`
0.9599, `GraphIndex ~ graph index` 0.9461, `OrderService ~ order service` 0.9368, `EmbeddingMismatch ~
embedding mismatch` 0.9297, `index_source ~ source index` 0.9292, `answer_question ~ question answering`
0.9151, `find_synonyms ~ synonyms` 0.8732, `build_igraph ~ igraph` 0.8637, `read_history ~ commit history`
0.7223. Nine of the ten clear 0.85; the fixture's pinned 0.87 under `FakeOllama` is in the right place, so
that expectation does not need re-pinning for the real model.

### Recommendation for WP2

> **Keep `synonymy_threshold` at 0.8 for cross-kind pairs. Do not add a separate, higher cross-kind
> threshold** — measured on 26 400 pairs, raising it to 0.85 leaves the nonsense rate *higher* (43% vs 40%)
> because generic one-word symbol names score at the very top, and 0.90 costs three of ten known-good pairs
> including `find_synonyms ~ synonyms`.
>
> **Ship the plan's second remedy instead: a symbol or data object participates in a cross-kind SYNONYM edge
> only when `split_identifier(name)` yields ≥ 2 tokens.** In `indexer.py`'s `find_synonyms`, apply it where
> the code side is added to the `names` map, beside the existing `is_meaningful_phrase` gate — the same shape,
> one extra condition, and it is what `is_meaningful_phrase` would be if it knew about identifiers. This drops
> the nonsense rate from 40% to 27% and costs **zero** of the ten known-good pairs. `OrderService ~ order
> service`, the pair D7 exists for, scores 0.9368 and is unaffected.
>
> Test it with the pair that fails without it: hippo's own `library` module reaches "the library" at **0.9376**,
> higher than `GraphIndex ~ graph index`. A unit test asserting that a one-token symbol name forms no
> cross-kind synonym even at similarity 0.95 is the right regression, and it needs no Ollama — pass the
> vectors in.
>
> Two things WP2 can rely on rather than worry about. Volume is small: 0.10 cross-kind pairs per symbol at
> 0.80, so `SYNONYM_MAX_NEIGHBOURS = 100` is nowhere near binding. And **no pair ≥ 0.80 involved a real entity
> from `samples/acme_robotics.md`** — proper nouns do not collide with code names, so the mixed-memory test in
> WP3.5 will not see synonym leakage from the fixture. That also means the fixture cannot *prove* the guard
> works; the regression above has to construct the case.
>
> **Apply the guard to `Symbol` only, not to `DataObject`.** This spike measured functions, classes, methods
> and modules; it did not measure data objects, and the rule would be actively wrong for them. Real table and
> collection names are single nouns — `orders`, `users`, `payments` — so a ≥ 2-token rule makes
> `table orders ~ "orders"` impossible, which is the exact link D9 exists to create. Either exempt
> `DataObject` or measure it separately before gating it.
>
> **Gate both sides, not just the query side.** `find_synonyms` applies `is_meaningful_phrase` to the *new*
> ids only (`indexer.py:268`), and under WP2.4 the key matrix becomes `load_entity_embeddings() ⊕
> load_code_embeddings()`. So a prose entity indexed *after* the code — "the library" arriving on a later
> source — is a new id scored against the existing `library` key and links anyway. The one-token filter has to
> remove those symbols from the key matrix too, or the pairs must be filtered after scoring using `label_of`
> plus the token count. Half of this fix does nothing.
>
> Residual, worth a line in the docs rather than more mechanism: three nonsense pairs survive the guard
> (`run_form`, `RunBody`, `run_stdio` against the prose entity "run"), all caused by a single-word *entity*
> rather than a single-word symbol. Requiring ≥ 2 words on both sides takes the nonsense rate to 0% but makes
> single-word entities like "synonyms" and "igraph" unreachable. Leave that lever for WP4's eval set.
>
> On sample size, stated plainly: 40% is 8 of 20 and 27% is 3 of 11. The counts are small because the
> phenomenon is rare (20 pairs in 26 400). The direction is what the numbers support — raising the threshold
> does not remove the nonsense, and the token rule does — not the second decimal place.

### Scripts

`/tmp/hippo-s0/spike2_synonyms.py` (abridged: the phrase lists are data):

```python
import json, random, sys
from pathlib import Path
ROOT = Path("/Users/mascott/projects/hippo")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT)); sys.path.insert(0, "/tmp/hippo-s0")

from hippo.hipporag.text import clean_phrase, is_meaningful_phrase
from hippo.ollama import Ollama
from spike1_anchors import split_identifier

THRESHOLD = 0.8                      # store/base.py:18

def name_text(name: str) -> str:     # A §model.py
    tokens = " ".join(split_identifier(name))
    return f"{tokens} {name}" if tokens != name else name

def sample_entities() -> list[str]:
    """The entity names samples/acme_robotics.md really produces: real chunker + FakeOllama NER, no store."""
    from hippo.ingest.chunker import chunk_document
    from hippo.ingest.readers import Document
    from tests.fakes.fake_ollama import parse_entities
    doc = Document(title="acme_robotics", text=(ROOT / "samples" / "acme_robotics.md").read_text(),
                   path="samples/acme_robotics.md", is_code=False)
    names = {}
    for chunk in chunk_document(doc, 1500, 200):
        for raw in parse_entities(chunk.text):
            cleaned = clean_phrase(raw)
            if cleaned and is_meaningful_phrase(cleaned):
                names.setdefault(cleaned)
    return list(names)

ollama = Ollama(base_url="http://localhost:11434", llm_model="qwen3:8b", embed_model="nomic-embed-text")
symbols  = json.load(open("/tmp/hippo-s0/symbols.json"))
distinct = sorted({s["name"] for s in symbols})
forced   = ["run", "save", "main", "total", "get", "load", "close", "start", "status", "search",
            "index", "answer", "ask", "check", "library", "source", "settings", "stats", "config", "render"]
forced   = [n for n in forced if n in distinct]
chosen   = forced + random.Random(0).sample([n for n in distinct if n not in forced], 200 - len(forced))

ent_side = [(e, "sample_entity") for e in sample_entities()] + [(g, "generic") for g in GENERIC]
sym_vec  = ollama.embed([name_text(n) for n in chosen], kind="document")
ent_vec  = ollama.embed([e for e, _ in ent_side],       kind="document")
sims     = sym_vec @ ent_vec.T       # find_synonyms' own score: Ollama.embed returns unit rows

pairs = sorted(((float(sims[i, j]), n, ename, src)
                for i, n in enumerate(chosen) if is_meaningful_phrase(name_text(n))
                for j, (ename, src) in enumerate(ent_side)), reverse=True)
for b in (0.90, 0.85, 0.80, 0.75, 0.70):
    print(f"  >= {b:.2f}: {sum(1 for p in pairs if p[0] >= b):>6}")
```

`/tmp/hippo-s0/spike2_verdict.py` holds the 20 hand labels as a literal `LABELS` dict — so the 40% is
auditable, not asserted — and applies each remedy as a filter over `spike2_pairs.json`:

```python
def rate(kept):
    labels = [LABELS[(p["symbol"], p["entity"])] for p in kept if (p["symbol"], p["entity"]) in LABELS]
    bad = sum(1 for x in labels if x == "nonsense")
    return f"{len(kept)} pairs, {bad} nonsense ({100 * bad / max(len(labels), 1):.0f}%)"

at_80 = [p for p in PAIRS if p["score"] >= 0.80]
for t in (0.80, 0.85, 0.90):                                     # remedy 1
    print(t, rate([p for p in at_80 if p["score"] >= t]),
          [k for k, v in KNOWN_GOOD_SCORES.items() if v < t])
kept = [p for p in at_80 if len(split_identifier(p["symbol"])) >= 2]     # remedy 2
print(rate(kept), [s for s in KNOWN_GOOD_SYMBOLS if len(split_identifier(s)) < 2])
print(rate([p for p in kept if len(p["entity"].split()) >= 2]))          # remedy 2b
```

---

## Spike 3 — where does a real repo land on the write-cost curve?

### Method

Two questions, measured separately.

**How big is a real repo, in the units WP1 writes?** The spike-1 `ast` walk, run over hippo and three
`git clone --depth 1` reference repos, counting one passage *and* one name vector per symbol (PLAN.md:414),
~4 code edges per symbol plus one `DEFINED_IN`, plus `code_history_depth` (200) commits × ~5 `MODIFIES`.

**What does that cost to write?** R4 T5 and T8 timed a bare `UNWIND … MATCH … CREATE`. WP1's
`add_code_edges` must MERGE by `(a, b, kind)`, and `store/ladybug.py:377-380` records that LadybugDB 0.15
cannot `MERGE` a relationship under `UNWIND` — so the shipped shape is `_link`'s
`WHERE NOT EXISTS { MATCH (a)-[r:CODE_EDGE]->(b) WHERE r.kind = … }` guard, which is a per-row edge probe and
has never been timed. Both shapes were run at four scales and two batch sizes against `real_ladybug` 0.15.3,
with free text passed as bytes and read back through `decode()`, as `ladybug.py` requires. Throwaway
databases under `/tmp/hippo-s0/db/`; `data/` untouched.

### Numbers — where the repos sit

| Repo | LOC | symbols | passages | stored vectors | vector MiB | code edges | + DEFINED_IN | + MODIFIES | total rels | vs `MAX_CHUNKS` |
|---|---|---|---|---|---|---|---|---|---|---|
| hippo `src/hippo` | 12 463 | 807 | 807 | 1 614 | 4.7 | 3 228 | 807 | 1 000 | 5 035 | 4% |
| flask `src` | 9 513 | 464 | 464 | 928 | 2.7 | 1 856 | 464 | 1 000 | 3 320 | 2% |
| django `django` | 165 439 | 12 317 | 12 317 | 24 634 | 72.2 | 49 268 | 12 317 | 1 000 | 62 585 | 62% |
| pandas `pandas` | 688 275 | 33 975 | 33 975 | 67 950 | 199.1 | 135 900 | 33 975 | 1 000 | 170 875 | **rejected** |

hippo's estimate of ~900 symbols is right: **807**. The plan's "one passage per symbol makes more documents
than 1500-char windows" is right too, and the factor is ~2.4-3×: hippo goes from ~335 windows today to 807
passages, django from ~3 946 to 12 317, pandas from ~15 781 to 33 975.

**`MAX_CHUNKS` is a hard wall, not a truncation.** `pipeline.py:256` raises `TooLarge` and the source is
rejected outright. So pandas cannot be indexed as one source at all once WP2 lands, where today it just
fits — that is a **behaviour change on existing corpora** and belongs in the release notes. The largest
source hippo will accept is 20 000 passages: **20 000 symbols, 40 000 vectors (117 MiB), ~101 000
relationships.**

### Numbers — the write cost

All timings are relationship-insert wall time, `real_ladybug` 0.15.3, this machine.

| Shape | nodes | rels | batch | nodes (s) | rels (s) | rels/s |
|---|---|---|---|---|---|---|
| `CREATE` | 1 000 | 5 000 | 1 000 | 0.024 | 0.126 | 39 580 |
| `CREATE` | 1 000 | 5 000 | 5 000 | 0.016 | **0.088** | 56 677 |
| `CREATE` | 10 000 | 50 000 | 1 000 | 0.146 | 12.444 | 4 018 |
| `CREATE` | 10 000 | 50 000 | 5 000 | 0.082 | 12.038 | 4 153 |
| `CREATE` | 20 000 | 100 000 | 5 000 | 0.137 | **87.153** | 1 147 |
| `NOT EXISTS` | 1 000 | 5 000 | 5 000 | 0.017 | 0.094 | 53 128 |
| `NOT EXISTS` | 10 000 | 50 000 | 1 000 | 0.142 | 13.000 | 3 846 |
| `NOT EXISTS` | 10 000 | 50 000 | 5 000 | 0.082 | 12.276 | 4 073 |
| `NOT EXISTS` | 20 000 | 100 000 | 5 000 | 0.171 | **85.813** | 1 165 |

At the django shape (12 317 nodes / 62 585 rels, batch 5 000), including the write-ahead log fold that
`db.close()` performs:

| Shape | nodes | rels | close (WAL fold) | total | on disk |
|---|---|---|---|---|---|
| `CREATE` | 0.125 s | 23.52 s | 0.08 s | **23.7 s** | 6.9 MB |
| `NOT EXISTS` | 0.094 s | 23.76 s | 0.09 s | **23.9 s** | 6.9 MB |

**Three results, and two of them contradict what the shape suggested.**

1. **The `NOT EXISTS` guard is free.** 85.8 s versus 87.2 s at the worst scale, 23.76 s versus 23.52 s at
   django scale — inside run-to-run noise, and the guarded run was faster at the largest size. The per-row
   edge probe was the thing worth fearing and it does not cost anything measurable, so WP1 can write
   `add_code_edges` exactly like `_link` and get MERGE-by-`(a,b,kind)` semantics for nothing.
2. **The batch size is not load-bearing.** 1 000 versus 5 000 rows is 12.44 s versus 12.04 s at 10k/50k, a 3%
   difference. The plan's 5 000 is fine; so is the store's existing `BATCH = 500` for nodes and 1 000 for
   links. This is worth knowing because it means the batch size is *not* the lever if anything ever does get
   slow.
3. **Cost is driven by node count, not relationship count**, which is what R4 concluded at its line 195 and
   this confirms independently: 4 100 rels/s at 10 000 nodes, 1 150 at 20 000, and R4 T8's 373 at 50 000.
   Doubling the nodes cut throughput 3.6×. Calibrating against R4: T5 wrote 100 000 rels over 10 000 nodes in
   13.6 s (7 353 rels/s) where this bench managed 4 153 rels/s on the same node count, so **these numbers are
   the conservative side of R4's** and the verdict does not depend on the difference.

Placing the repos on that curve: hippo **0.13 s**, flask under 0.1 s, django **23.5 s**, and the
`MAX_CHUNKS` ceiling **87 s**. T8's 537 s is unreachable — it needs 50 000 nodes, and hippo refuses a source
at 20 000.

### Recommendation for WP1

> **Nothing beyond 5 000-row batches is needed, and the batch size barely matters.** The largest source hippo
> will accept is 20 000 passages (`MAX_CHUNKS`, `pipeline.py:256`, which raises `TooLarge` rather than
> truncating), which is ~101 000 relationships over 20 000 nodes and writes in **87 s** measured. django,
> the largest real repo that fits, is **23.5 s**. R4 T8's 537 s needs 50 000 nodes and is unreachable through
> the pipeline. No indexed lookup, no MERGE-by-internal-id, no `COPY` bulk path.
>
> **Write `add_code_edges` with `_link`'s `WHERE NOT EXISTS { … }` guard** (`store/ladybug.py:377-392`) rather
> than working around LadybugDB 0.15's inability to `MERGE` a relationship under `UNWIND` some other way. The
> guard was the suspect item in this spike and it measured **free**: 85.8 s versus 87.2 s unguarded at the
> worst scale. Extend the inner `MATCH` with `WHERE r.kind = decode(row.kind)` so identity is `(a, b, kind)`
> as D3 requires. This is LadybugDB only — Neo4j can `MERGE` under `UNWIND` and was not measured here, so
> nothing in this spike bears on the Neo4j backend.
>
> Be precise about what the guard gives you, because it is not all of `MERGE`: it is **create-if-absent, with
> no `ON MATCH SET`**. The dedupe half was verified incidentally — a first run whose synthetic `(a, b, kind)`
> triples collided wrote 1 000 of 2 000 rows, exactly the duplicates skipped. The missing half does not matter
> here: PLAN.md:98 has the extractor collapse repeated call sites into one row (highest ω, first `call_line`,
> the rest in `extra.call_lines`) **before the store sees them**, so there is no second row whose ω would need
> to win a comparison. If that ever changes, the guard silently keeps the first ω rather than the highest, and
> that is the line to revisit.
>
> **The number worth watching is vectors, not write time.** One passage embedding plus one name vector per
> symbol is 24 634 vectors (72 MiB) for django and 40 000 (117 MiB) at the `MAX_CHUNKS` ceiling, and
> `docs/FIDELITY.md:124-127` says every graph-version bump — each index job, each `hippo_remember`, each
> applied changeset through `ctx.invalidate_graph()` — triggers a full reload whose cost grows with the
> stored-vector count. Code indexing roughly triples the vector count for a given repo versus today's
> line-window chunking. That is a `GraphIndex.load` concern, not an `add_code_edges` one, and it is the thing
> to measure in WP4 rather than to pre-optimise now.
>
> **One behaviour change to write down.** A repo that indexes today can be rejected after WP2, because one
> passage per symbol produces 2.4-3× more passages than 1500-char windows for the same source: pandas goes
> from ~15 781 windows (fits) to 33 975 symbol passages (`TooLarge`). Say so in the release notes and in the
> "too large" error text, which currently just advises splitting the source.

### Script

`/tmp/hippo-s0/spike3_write.py`, in full but for the driver loop:

```python
import shutil, time
from pathlib import Path
import real_ladybug as lb

DB_DIR = Path("/tmp/hippo-s0/db")

def run(conn, query, **params):
    return conn.execute(query, params) if params else conn.execute(query)

def batches(rows, size):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]

def build(n_nodes, n_rels, batch, shape):
    """shape: 'create' = R4 T5/T8's bare CREATE; 'not_exists' = ladybug.py:_link's idempotent guard."""
    path = DB_DIR / f"{shape}-{n_nodes}-{n_rels}-{batch}"
    shutil.rmtree(path, ignore_errors=True)
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db = lb.Database(str(path)); conn = lb.Connection(db)
    run(conn, "CREATE NODE TABLE Symbol(id STRING PRIMARY KEY, name STRING)")
    run(conn, "CREATE REL TABLE CODE_EDGE(FROM Symbol TO Symbol, kind STRING, omega DOUBLE,"
              " provenance STRING, extra STRING)")

    nodes = [{"id": f"symbol-{i:07d}", "name": f"n{i}".encode()} for i in range(n_nodes)]
    t0 = time.perf_counter()
    for b in batches(nodes, batch):
        run(conn, "UNWIND $rows AS row CREATE (:Symbol {id: row.id, name: decode(row.name)})", rows=b)
    t_nodes = time.perf_counter() - t0

    # unique (a, b, kind) per row: a = i mod N, offset = i div N + 1, so (a, b) never repeats
    kinds = ("INVOKES", "IMPORTS", "CONTAINS", "INHERITS")
    rels = []
    for i in range(n_rels):
        a = i % n_nodes
        rels.append({"a": f"symbol-{a:07d}", "b": f"symbol-{(a + 1 + i // n_nodes) % n_nodes:07d}",
                     "kind": kinds[i % 4].encode(), "omega": 0.9, "provenance": b"same_file",
                     "extra": b'{"call_line": 18}'})

    guard = ("WHERE NOT EXISTS { MATCH (a)-[r:CODE_EDGE]->(b) WHERE r.kind = decode(row.kind) }"
             if shape == "not_exists" else "")
    q = f"""
        UNWIND $rows AS row
        MATCH (a:Symbol {{id: row.a}}), (b:Symbol {{id: row.b}})
        {guard}
        CREATE (a)-[:CODE_EDGE {{kind: decode(row.kind), omega: row.omega,
                                provenance: decode(row.provenance), extra: decode(row.extra)}}]->(b)
        """
    t0 = time.perf_counter()
    for b in batches(rels, batch):
        run(conn, q, rows=b)
    t_rels = time.perf_counter() - t0

    written = run(conn, "MATCH (a:Symbol)-[r:CODE_EDGE]->() RETURN count(r) AS n").get_next()[0]
    t0 = time.perf_counter(); conn.close(); db.close(); t_close = time.perf_counter() - t0
    return {"t_nodes": t_nodes, "t_rels": t_rels, "t_close": t_close, "written": written}

for shape in ("create", "not_exists"):
    for n, r, b in [(1_000, 5_000, 1_000), (1_000, 5_000, 5_000), (500, 2_000, 5_000),
                    (10_000, 50_000, 1_000), (10_000, 50_000, 5_000), (20_000, 100_000, 5_000)]:
        print(shape, n, r, b, build(n, r, b, shape))
```

`/tmp/hippo-s0/spike3_counts.py` is the same `walk` from spike 1 plus the arithmetic in the first table
(`DIM = 768`, `EDGES_PER_SYMBOL = 4`, `HISTORY_COMMITS = 200`, `MODIFIES_PER_COMMIT = 5`,
`MAX_CHUNKS = 20_000`). `/tmp/hippo-s0/spike3_django.py` is `build` at 12 317 / 62 585 with `db.close()`
timed separately.

---

## Appendix — the scratch splitter versus the one that landed mid-run

When these spikes started, `label_of` and `split_identifier` were absent from `src/hippo/hipporag/text.py`,
so spikes 1 and 2 used the scratch splitter quoted above, written to PLAN.md:153's three examples. WP0 merged
the real ones into `code-graph` while spike 3 was running (`5af16d9 Merge wp/wp0: label_of and
split_identifier in hipporag/text.py`), so the results were re-validated against the landed implementation
(`text.py:68-80`, one regex splitting on `::`, separators, digit/letter boundaries and camelCase).

**They agree on every case that matters: 0 disagreements across all 650 distinct hippo symbol names, and
identical output on all three PLAN.md:153 examples** plus `MAX_CHUNKS`, `_load_pipeline`, `RunBody`,
`build_igraph` and `database`. Both classify the same 156 names as single-token. Every number in spikes 1
and 2 therefore stands under the shipped code; nothing needs re-running.

One thing WP2 should know, because it is the input to the spike 2 recommendation: **156 of hippo's 650
distinct names split to a single token, 100 of them lowercase alphabetic**. Count these on the original
spelling — lowercasing a name first turns `GraphIndex` into `graphindex`, which is one token and inflates the
figure to 195.

The corpus harvester spikes 1 and 2 share is `/tmp/hippo-s0/corpus.py`: a `["\']([^"\'\n]{6,120}\?)["\']`
sweep over `tests/unit/*.py`, `tests/*.py`, `README.md`, `docs/*.md`, `samples/*.md` and
`src/hippo/**/*.py` for the 29 harvested questions, `FakeOllama.parse_triples` over
`samples/acme_robotics.md` for the 34 generated ones, and two literal lists for the 55 hand-written prose
questions and the 22 identifier questions.
