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
  rest are set to 0.
* Passage seed weights: min-max normalised DPR score times `passage_node_weight`.
* Reset vector = entity weights + passage weights; NaN or negative entries become 0.
* PPR: `graph.personalized_pagerank(vertices=range(n), damping=damping, directed=False,
  weights="weight", reset=reset, implementation="prpack")`, character for character.
* Passages ranked by their PPR score; when no fact survives the filter the ranking is
  plain dense passage retrieval (`No facts found after reranking, return DPR results`).

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
12. **Single-step retrieval only.** The reference also offers IRCoT-style multi-step
    retrieval (`retrieve_ircot`); hippo implements the default single step
    (`max_qa_steps = 1`).
13. **Evaluation.** Exact match and F1 use the reference's MRQA-style normalisation
    (`evals/metrics.py`). The LLM judge, question generation, simulations and
    changesets are hippo's own and have no counterpart in the reference.
14. **Synonym gate counts Unicode letters.** The reference's regex `[^A-Za-z0-9]` strips every
    non-ASCII character, so a name like `東京都` or `москва` never gets synonym edges. hippo uses
    `str.isalnum`, which counts letters and digits in any script, so non-Latin names are linked
    like Latin ones. For English text the two rules agree exactly.
