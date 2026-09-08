# Fidelity to the HippoRAG reference

This page compares hippo's `src/hippo/hipporag/` with the reference
implementation, `hipporag/HippoRAG.py`, `rerank.py`, `prompts/` and
`utils/config_utils.py` in https://github.com/OSU-NLP-Group/HippoRAG
(the HippoRAG 2 code). "Exact" means the same rule and the same numbers;
"adapted" means we changed something on purpose, and says why.

## Exact matches

### Defaults (`utils/config_utils.py` vs `store/base.py: DEFAULT_SETTINGS`)

| Knob | Reference | hippo |
| --- | --- | --- |
| `linking_top_k` | 5 | 5 |
| `passage_node_weight` | 0.05 | 0.05 |
| `damping` | 0.5 | 0.5 |
| `synonymy_edge_sim_threshold` | 0.8 | `synonymy_threshold` 0.8 |
| `retrieval_top_k` | 200 | 200 |
| `qa_top_k` | 5 | 5 |
| synonym neighbours per entity | 100 (`num_nns >= 100`) | `SYNONYM_MAX_NEIGHBOURS = 100` |
| `openie_ner_max_tokens` / `openie_triple_max_tokens` | 512 / 2048 | 512 / 2048 |
| filter `max_new_tokens` | 512 | 512 |

### Text normalisation and ids

* `text.clean_phrase` is the reference's `text_processing`: casefold, replace
  every non-alphanumeric character with a space, collapse whitespace.
* Entity ids are `entity-` + md5(cleaned phrase), exactly `compute_mdhash_id(phrase, "entity-")`.
* `min_max_normalize` returns all ones when every score is identical, as the reference does.
* Only phrases with more than two letters/digits get synonym edges (the reference:
  `len(re.sub('[^A-Za-z0-9]', '', entity)) > 2`; hippo counts Unicode letters/digits too, see adaptation 14).

### OpenIE (`openie.py` vs `information_extraction/openie_openai.py` + `prompts/templates/ner.py`, `triple_extraction.py`)

* NER first, then triple extraction with the NER list as a hint, one passage per call.
* The same system prompts and the same one-shot demonstration (Radio City).
* Invalid triples (not three parts) are dropped and duplicates removed
  (`filter_invalid_triples`); graph nodes are the subjects and objects of the
  triples, not the NER list (`extract_entity_nodes`).

### Graph construction (`indexer.py`, `graph_index.py` vs `add_fact_edges`, `add_passage_edges`, `add_synonymy_edges`, `add_new_edges`)

* Undirected graph.
* Edge between two entities: +1 per triple that joins them, counted per passage
  (`node_to_node_stats[edge] += 1`).
* Passage to entity edge: weight 1.0 for every entity the passage's triples mention.
* Synonym edge: cosine similarity when it is at least the threshold; when an
  edge already exists the weight is `max(existing, score)`.
* Synonym search is incremental: only the *new* entities are compared with all
  entities, as the reference does with `_pending_synonymy_entity_ids`.
* Node specificity data (`ent_node_to_chunk_ids`): how many passages mention an
  entity, computed from the same MENTIONS links.

### Retrieval (`retriever.py` vs `retrieve`, `get_fact_scores`, `rerank_facts`, `graph_search_with_fact_entities`, `run_ppr`, `dense_passage_retrieval`)

* Fact scores: dot product of the question vector with every fact vector, min-max normalised.
* The top `linking_top_k` facts go to the filter (the reference's `rerank_facts`).
* The filter prompt is the reference's DSPy program: the same instruction text and the
  same ten demonstrations from `prompts/filter_default_prompt.py` (`best_dspy_prompt`),
  in the same order.
* Triples the LLM returns are mapped back to candidates by exact match, otherwise
  by `difflib.get_close_matches(..., n=1, cutoff=0.0)` (`rerank.py: DSPyFilter.rerank`);
  the kept list is cut to `linking_top_k`.
* A filter error keeps no facts, which means the DPR fallback, as in the reference
  (`except Exception: generated_facts = []`).
* Seed weights (`graph_search_with_fact_entities`): for each kept fact, each of its
  subject and object gets the fact score, divided by the number of passages that
  mention the entity when that number is > 0 (node specificity); the sums are
  divided by the number of occurrences (`np.divide(..., where=number_of_occurs != 0)`);
  only the top `linking_top_k` entities keep their weight (`get_top_k_weights`), the
  rest are set to 0. Symbol seeds, which the reference has no counterpart for, are
  budgeted separately and do not take part in that cut (adaptation 15).
* Passage seed weights: min-max normalised DPR score times `passage_node_weight`.
* Reset vector = entity weights + passage weights, plus code weights for a memory that holds a
  code source (adaptation 15); NaN or negative entries become 0. With no code node in the graph —
  or with `code_seed_weight` at 0 — the code term is an array of zeros and the sum is the
  reference's exactly.
* PPR: `graph.personalized_pagerank(vertices=range(n), damping=damping, directed=False,
  weights="weight", reset=reset, implementation="prpack")`, character for character.
* Passages ranked by their PPR score; when no fact survives the filter the ranking is
  plain dense passage retrieval (`No facts found after reranking, return DPR results`) —
  unless a lexical anchor fired, in which case the question named something the graph knows
  and PPR runs from that instead (adaptation 15). A question that names no code takes the
  reference's path, and a dense code seed deliberately does not count here.

### Reading (`answerer.py` vs `qa` + `prompts/templates/rag_qa_musique.py`)

* The same `rag_qa` system prompt, the same "Thought:" / "Answer:" protocol and the
  same one-shot demonstration (Neville A. Stanton, answer 1862).
* The top `qa_top_k` passages, best first, followed by `Question: ...\nThought: `.
* The answer is the text after "Answer:"; the reference falls back to the whole
  reply when the marker is missing, and so do we.

## Adaptations

1. **JSON structured outputs instead of DSPy markers.** The reference formats the
   filter as DSPy fields (`[[ ## question ## ]]`, `[[ ## fact_after_filter ## ]]`,
   `[[ ## completed ## ]]`) and parses them back. hippo sends the same instruction
   and demonstrations as ordinary chat turns (`Question: ...` / `Candidate facts
   (JSON): ...`) and asks Ollama to constrain the reply to a JSON schema
   (`FACT_FILTER_SCHEMA`). Same for NER and triples. Reason: an 8B local model
   follows a schema far more reliably than it follows prose formatting rules, and
   Ollama can enforce the schema. For `qwen3` we also switch thinking off
   (`think: false`) so replies are short.
2. **Fact embedding text.** The reference embeds `str(tuple)` of the triple, e.g.
   `('radio city', 'located in', 'india')`; hippo embeds `radio city located in india`
   (`text.fact_text`). A plain sentence matches questions better with a small
   embedding model, and the punctuation carried no meaning. As a consequence fact
   ids are `fact-` + md5(`s\tp\to`) rather than md5 of the tuple string.
3. **Passage ids per source.** The reference's chunk id is `chunk-` + md5(text), so the
   same text in two documents is one node. hippo's is `passage-` + md5(`source_id:ordinal:text`)
   so a source can be deleted or re-indexed without touching another source that
   happens to contain the same paragraph. Titles ("Doc › Heading (part 2)") are
   stored on the passage and shown in the QA prompt as `Title: ...`, where the
   reference writes `Wikipedia Title: <whole passage>`.
4. **Synonyms via numpy over store-held vectors.** The reference runs `retrieve_knn`
   (k = 2047) over its parquet embedding store. hippo loads every entity vector out
   of the store, multiplies the new entities' vectors against all of them, and keeps the
   top 100 above the threshold. Same neighbours, no separate vector store; fine for
   tens of thousands of entities, and the place to optimise first if a graph gets
   much larger.
5. **A graph database instead of pickled igraph + parquet.** The reference keeps the graph in a
   pickled igraph and embeddings in parquet files under `save_dir`. hippo keeps
   everything in a graph database (LadybugDB by default, or Neo4j; see `store/__init__.py` for the shape) and rebuilds the
   in-memory igraph plus the numpy embedding matrices (`GraphIndex.load`) whenever a
   `graph_version` counter changes. Edge weights are recomputed at load time with the
   same `max(fact count, 1.0 if mention, synonym score)` rule, plus a fourth term for
   the code graph: `max(fact count, 1.0 if mention, entity–entity synonym score,
   best code ω × code_structural_scale)` (`Edge.weight_at`, adaptation 15). On a memory
   with no code source that fourth term is 0.0, which cannot raise a max, so the rule is
   the reference's exactly. Two things the
   reference does not have: a `TUNED` edge weight that replaces that number, and a
   per-entity `boost` multiplier on seed weights. Both are 1:1 / absent unless you
   apply a changeset, so a fresh memory behaves like the reference. Every graph version bump (each index job, including every `hippo_remember` call, and every
   applied changeset) triggers a full reload whose cost grows with the number of stored vectors;
   while one thread reloads, other callers keep using the previous graph (the trace records
   which `graph_version` it used).
6. **No query-instruction prefixes beyond the embedding model's own.** With
   NV-Embed-v2 the reference embeds the question twice, with different instructions
   for facts (`Given a question, retrieve relevant triplet facts...`) and for
   passages (`...retrieve relevant documents...`). hippo embeds the question once with
   only the prefix the embedding model itself expects (`search_query: ` for
   nomic-embed-text, `search_document: ` for everything stored) and uses that one
   vector for both fact and passage similarity. This is what the reference also does
   for models whose `query_instruction_mode` is `shared` or `ignored`.
7. **Chunking.** The reference's default is one chunk per document (or token-based
   splitting); hippo splits by characters (1500, overlap 150) on headings,
   paragraphs and sentence ends (`ingest/chunker.py`) so that five passages fit the
   8k context of a local model.
8. **Shortened one-shot QA passages.** The Neville A. Stanton demonstration is kept but
   the Southampton and Stanton passages are trimmed to their first sentences, to save
   context on an 8k window. The instruction, question, thought and answer are unchanged.
9. **Fallback when every seed is zero.** The reference raises `StateConsistencyError`
   when the reset vector sums to 0. That can only happen in hippo when someone boosts
   every seed to 0 in a simulation, so we fall back to DPR and say so in the trace.
10. **Traces.** hippo records at least the top 20 candidate facts (exactly
    `max(20, linking_top_k)`, so every fact shown to the filter is in the trace) and the top
    40 PPR nodes for the Analyze page. Exactly the top `linking_top_k` are sent to the
    filter, as in the reference's `rerank_facts`; recording more changes nothing in the ranking.
11. **OpenIE failures.** If the model fails on one passage, hippo stores the passage
    with no facts (still reachable through dense retrieval) and records the error on
    it, instead of failing the whole index run.
12. **Single-step retrieval over facts, with an optional second pass over passages.** The
    reference also offers IRCoT-style multi-step retrieval (`retrieve_ircot`); hippo implements the
    default single step (`max_qa_steps = 1`), and never goes back to the graph for more facts. It
    does add one pass the reference does not have, and only when a question named code: with
    `code_select` on (the default) the model sees the passages it is about to read and says which
    to keep, drop or expand (adaptation 15). That is a second LLM step, and it is recorded here
    rather than tucked into adaptation 15 alone because it costs this guarantee its old, simpler
    form. Setting `code_select` to `False` restores it exactly.
13. **Evaluation.** Exact match and F1 use the reference's MRQA-style normalisation
    (`evals/metrics.py`). The LLM judge, question generation, simulations and
    changesets are hippo's own and have no counterpart in the reference.
14. **Synonym gate counts Unicode letters.** The reference's regex `[^A-Za-z0-9]` strips every
    non-ASCII character, so a name like `東京都` or `москва` never gets synonym edges. hippo uses
    `str.isalnum`, which counts letters and digits in any script, so non-Latin names are linked
    like Latin ones. For English text the two rules agree exactly.
15. **Code graph.** The reference has no notion of code: every passage is prose and every node in
    the graph is an OpenIE phrase or a passage. For a source that is a repository hippo adds three
    more kinds of node — `Symbol` (module, class, function, method), `DataObject` (a table,
    collection or graph label the code names) and `Commit` — written by a parser rather than by the
    model, with typed directed edges between them (`CONTAINS`, `IMPORTS`, `INVOKES`, `INHERITS`,
    `OVERRIDES`, `RAISES`, `CATCHES`, `TESTED_BY`, `READS`, `WRITES`), each carrying a confidence
    ω from 1.00 (syntax) down to 0.50 (a unique bare-name match) and the provenance that earned it.
    Reason: an engineer's question about code carries evidence a prose pipeline throws away — an
    identifier, a stack frame, a diff — and a parser knows what a function calls where a model
    guesses. Each part below is separately gated, and the last paragraph is what "gated" means.
    * **Edge weight.** The load-time rule gains a fourth term (adaptation 5). Every term that
      exists only because code was indexed is inside that multiplication — `CODE_EDGE`,
      `DEFINED_IN`, `REFERS_TO`, `MODIFIES` and cross-kind synonyms — and `code_structural_scale`
      is capped at 3.0, so a pair joined by three facts can at most be *tied* by a code edge and
      never beaten by one. `TUNED` is exempt, as it always is: a person set it.
    * **PPR itself is untouched.** `personalized_pagerank(...)` is still character for character
      the reference's call, still `directed=False`. Direction exists only outside igraph, in
      `code_out` / `code_in`, where the path tools read it; the graph PPR runs on never sees it.
    * **Node specificity per kind.** The reference divides a seed by the number of passages that
      mention its entity. A symbol has no `MENTIONS`, so that count would be 0 and the division
      would be skipped, leaving hub functions undamped. hippo puts `in_degree + 1` in the same
      shared array instead — over `INVOKES`, `READS` and `WRITES` only, since a function touched by
      150 of 200 commits would otherwise be crushed. The retriever is unchanged: it divides by
      whatever it finds in the array.
    * **Symbol seeds have their own budget.** The reference cuts entity seeds to `linking_top_k`
      (`get_top_k_weights`). Symbols the question named are not in that competition; they have
      `MAX_CODE_SEEDS = 20` of their own, by weight. The other two jobs `linking_top_k` does — how
      many facts reach the filter, and how far the kept list is cut — are untouched.
    * **The question is split before it is embedded.** The reference embeds the question verbatim.
      When a question contains a fenced block, a stack frame or a diff hunk, hippo embeds and
      filters on the *prose* half only, so a forty-line traceback cannot dominate one query vector;
      the QA prompt still receives the whole thing, and anchors are read from both halves. A
      question of one line with no fence splits to `(text, "")` and takes exactly the reference's
      path — that is this part's inert condition, and it is a test (`anchors.split_question`).
    * **A second way to seed.** Identifiers, stack frames, exception names, fenced blocks and diff
      hunks in the question seed PPR directly, at `code_seed_weight`. A code passage that scored
      well on plain similarity also seeds the symbols it defines, but at
      `code_seed_weight × passage_node_weight × its similarity`: `dpr_scores` are min-max
      normalised, so the full weight would put the top passage at exactly 1.0 and let it outrank an
      exact identifier match on every question. What someone typed has to beat what merely looked
      similar. Only a *lexical* anchor sets `used_code_seeds`, which is the single gate on
      everything else in this adaptation; a similarity seed adds reset mass and nothing more.
    * **A bare word anchors only when it was written as code.** `PascalCase`, `camelCase`,
      `snake_case` or `ALL_CAPS`, or backticked, or dotted, or inside a frame, fence or diff. A
      question whose words are ordinary English produces no anchor at all — including one
      containing a word that is also a symbol name here, like `status`, `config` or `run` — so it
      never opens the gate above and never reaches anything below it.
    * **A community prior, off by default.** Symbols are grouped into subsystems by Leiden over the
      file projection, and `code_community_boost` lifts a passage whose symbol shares a subsystem
      with a seed. It ships at 0.0, so today the grouping only labels: a `Subsystems:` line in the
      answer block and in a blast radius.
    * **A second LLM pass, over passages.** The reference filters *facts* once and stops
      (adaptation 12). When a question named code, hippo runs one more pass over the passages the
      model is about to read, keeping, dropping or expanding them (`code_select`, on by default).
      It judges a window *wider* than the slice the answer is built from, so that dropping a
      passage promotes one the model never saw into its place; judging exactly the slice would make
      a drop inert, reordering the same list. A dropped passage sinks below the kept ones and the
      unjudged ones alike, but is never removed — a wrong drop should cost a position, not erase
      evidence — and an unparsable or failing reply keeps everything, mirroring the fact filter's
      own fallback. Expanded neighbours are appended at score 0.0 and excluded from the `qa_top_k`
      slice, so they are never cited.
    * **A pseudo-passage of typed relations.** `rag_qa` is byte-identical: it formats
      `(title, text)` pairs and assumes nothing about a passage, so the code block is prepended as
      one more pair titled `Code graph`, inside `answer_question`. It never enters
      `Answer.passage_ids`. Its body is a fixed grammar — `a -[KIND ω provenance]-> b`, then
      `Tests:`, `Commits:`, `Subsystems:` — under a one-sentence legend, cut at
      `code_triples_chars` on a line boundary.
    * **OpenIE never reads code.** The model sees a symbol's docstring or doc-comment when it is at
      least 80 characters, README and markdown, and commit messages. Never a function body, never
      DDL. Structure comes from tree-sitter and sqlglot.
    * **Nothing lets the model author a graph query.** No reply is turned into Cypher, a path
      expression or a graph query. The path tools are ordinary walks over the same in-memory graph,
      and the model's role stays the reference's: filter, and read.

    With no code sources indexed nothing changes: no code vertex exists, and the fourth term in the
    edge-weight `max` is 0.0, which cannot raise a max. With code indexed,
    `code_structural_scale = 0` drops **every** pair that exists only because code was indexed —
    `CODE_EDGE`, `DEFINED_IN`, `REFERS_TO`, `MODIFIES` and cross-kind `SYNONYM` — out of igraph,
    because each is multiplied by that scale and `build_igraph` keeps only `weight > 0`; every code
    vertex therefore has degree 0 and cannot receive or pass PPR mass. Adding `code_seed_weight = 0`
    and `code_dense_seeds = 0` restores fact-only seeding and `code_select = False` removes the
    second LLM pass. Under those four settings a prose corpus indexed alongside code ranks
    identically to the same corpus indexed alone; the only surviving code-touching edge is a `TUNED`
    weight a person set by hand. Code passages remain ordinary passages and still receive DPR seed
    mass, as any passage does. That is a test on a mixed prose-and-code memory, not a claim.
