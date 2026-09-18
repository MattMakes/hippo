# S0 — The three pre-WP1 spikes (PLAN.md §"Pre-WP1 spikes (V2.7)", lines ~408-414)

You are a RESEARCH worker, not an implementer: you edit nothing under `src/`, `tests/`, `docs/*.md`,
`data/` or `.venv/`. Work in the root tree (`/Users/mascott/projects/hippo`, branch `code-graph`) with
scratch scripts under `/tmp/hippo-s0/` only. Output: ONE file,
`docs/plans/hippo-for-code/research/S0-spikes.md`. Read `PLAN.md` lines 1-165 (Context, Decision Log,
Design summary) and 408-414 (the spikes) before starting; skim WP3.1 (`anchors.py`, line ~374) and
WP2.4 `find_synonyms` (line ~340) so you test what will actually be built.

Do not start docker, Neo4j or the app. Never touch port 7687 / 7474 / 8000 or `data/`. Ollama IS running
on the host (`http://localhost:11434`) and may be used read-only for spike 2. Use `.venv/bin/python`.

Each spike is pure Python, no LLM except spike 2's embedder. Budget: ~3 hours total. Results feed the WP2
and WP3 briefings, so precision matters more than polish. Every number you report must be reproducible
from a script you quote in the file.

## Spike 1 — do lexical anchors fire on ordinary prose? (~1 h)

The risk: WP3's bare-word anchor rule (a question token ≥ 3 chars, not in a stoplist, exact `Symbol.name`
hit) would anchor on hippo's own symbol names like `status`, `index`, `config`, `source`, `run`, `ask`,
`stats`, `search`, `answer`, `settings` — ordinary English.

1. Build the symbol-name set for `src/hippo` with an `ast` walk: every module name (file stem), class,
   function and method name (`name`, not qualname). Report the count and the 40 most English-looking names.
2. Build the question corpus: every question string you can find in the repo — eval question sets in
   `tests/unit/test_evals_*.py`, `tests/unit/test_retriever.py`, `test_ask.py`, `samples/`, the README's
   example questions, `docs/`. Also generate ~50 plausible prose questions about `samples/acme_robotics.md`
   yourself (varied: who/what/where/when, 5-20 words). Report the corpus size.
3. Implement the planned tokenizer + rule as a scratch function: split on whitespace/punctuation, keep
   tokens ≥ 3 chars, lowercase exact match against the lowercase name set (that is what WP3.1 says:
   "an exact `name` hit"), with a first-cut English stoplist (NLTK-style ~150 words + the obvious code
   words). Count prose questions producing ≥ 1 anchor, with and without the stoplist, and list which
   tokens fired.
4. Repeat with the two alternative rules the plan names as fallbacks: (a) require ≥ 2 tokens of a split
   identifier to match (`split_identifier` is in `hipporag/text.py`... if it is not there yet, use a
   scratch camelCase/snake splitter), or (b) require a qualified (`a.b`) or backticked form for a
   bare-word anchor, PascalCase/snake_case/camelCase surface form counting as qualified.
5. Verdict: is the false-anchor rate near zero under the plain rule? If not, which fallback gets it there
   with the least loss on genuine identifier questions (test with ~20 real identifier questions you write,
   e.g. "where is ensure_schema called", "what does GraphIndex.load do", "why does index_source fail")?

## Spike 2 — symbol↔entity synonyms under the REAL embedder (~1 h)

D7 rests on `name_text()` for a symbol (its name plus its split tokens, e.g. `"OrderService order service"`)
reaching the prose entity `order service` at ≥ the synonym threshold. Under `FakeOllama` that is feature
hashing; the real model may link generic names (`run`, `save`, `main`, `total`, `get`) to nonsense.

1. Find the configured embedding model: `HIPPO_EMBED_MODEL` in `.env` / `src/hippo/config.py` /
   `ollama.py`, and confirm it is pulled (`curl localhost:11434/api/tags`). If it is not pulled, STOP and
   `horch tell orchestrator` — do not pull a model.
2. Find the synonym threshold and the exact similarity used by `find_synonyms` (`hipporag/indexer.py` and
   the store's `find_synonyms`/`load_entity_embeddings`; read `ollama.py:embed*` for the call shape).
3. Build ~200 `name_text()` strings for hippo symbols (from spike 1's walk; include generic ones) and an
   entity set: the entity names the fixture's `samples/acme_robotics.md` produces (index it with the real
   pipeline into a scratch LadybugDB in `/tmp/hippo-s0/` using `FakeOllama` for OpenIE — or simply take
   `tests/unit/test_indexer.py`'s expected entity list — plus ~100 generic English noun phrases you write
   ("order service", "billing", "customer", "the total", "run", "main office", "save file"...).
4. Embed both sides with the real model through hippo's own `ollama.py` embed call, compute cosine
   similarity the way `find_synonyms` does, and report: the number of pairs ≥ threshold, the number of
   pairs ≥ 0.8, and hand-label the top 40 pairs as sensible / nonsense. Report the nonsense rate.
5. Verdict: is the cross-kind threshold safe as-is? If not, recommend one of the plan's two remedies (a
   higher threshold for cross-kind pairs — give the number — or requiring ≥ 2 split tokens) with evidence.

## Spike 3 — where does a real repo land on the write-cost curve? (~30 min)

R4 measured T5 (100k rels over 10k nodes: 13.6 s) and T8 (200k rels over 50k nodes: 537 s) for the
`UNWIND` + two-`MATCH` write shape.

1. Count hippo's own functions/classes/methods/modules (spike 1's walk) — the plan estimates ~900.
2. Estimate stored vectors (one passage embedding + one name vector per symbol) and edges (~4 per symbol
   plus DEFINED_IN, plus 200 commits × ~5 MODIFIES) for hippo itself; then for three reference repos by
   size — pick public numbers you can defend (e.g. a 20k-LOC, 100k-LOC and 500k-LOC Python/TS project;
   `git clone --depth 1` into `/tmp/hippo-s0/` and count with the same walk if you want real numbers).
3. Place each on the T5 → T8 curve and state where WP1's 5,000-row batch and the `MAX_CHUNKS = 20_000`
   cap bind first. Read `research/R4-spike-results.md` T5/T8 for the exact shapes measured.
4. Verdict: does WP1 need anything beyond 5,000-row batches for repos hippo can index before
   `MAX_CHUNKS` binds? If yes, name the change (e.g. indexed lookup, MERGE by internal id) precisely
   enough for WP1 to build it.

## Output format

`research/S0-spikes.md`: a 3-row verdict table at the top (spike, verdict in one line, the number that
decides it), then one section per spike with method, the script (fenced, runnable), the numbers, and a
**Recommendation for WP2/WP3** paragraph written so the orchestrator can paste it into a briefing.
When done: `horch tell orchestrator "[<role>] DONE: research/S0-spikes.md — <the three one-line verdicts>"`,
record the summary in the ledger, close your pane.
