# arXiv papers that apply to hippo

This page lists the arXiv papers whose ideas hippo uses, adapts, or has a written plan to adopt. For each paper it says why the paper matters here, which of its ideas hippo already implements, which it does not, and what adopting the rest would buy.

How this page was checked:

* Every arXiv id was fetched from its abstract page on 2026-09-13. Each entry names the version that was read. Statements about a paper's method come from that version's abstract or, where the entry says "full text", from the paper itself.
* Every statement about hippo was checked against the repository at commit `9770c00` (branch `rag-it-all-tibs`). Pointers are written `(path:line)` from the repository root.
* The branch head moved to `1f3d524` while this page was being written. Of the files cited here, only `src/hippo/knowledge/code_binding.py` changed. The `RetrievalView` construction cited from it moved from lines 575-585 to 596-606, and the code itself is unchanged.
* "Not yet" means no code at that commit implements the idea. The planned hybrid retrieval package `src/hippo/retrieval/`, which Tasks 13 and 14 create (docs/rag_it_all.md:1464, docs/rag_it_all.md:1487), does not exist yet.
* The standing project rules that "Possibly new features" are checked against are the invariants in docs/rag_it_all.md:212-229:
  * every claim points to authorized source evidence (I1);
  * parser facts, declarations and model inferences stay distinguishable (I3);
  * the legacy ranking stays available and measurable (I10);
  * missing context is reported, never silently dropped (I11);
  * the time axes stay distinct (I12);
  * every derived view has a tested invalidation path (I13).
  
  Two further rules come from the design documents. LadybugDB is the default backend (docs/FIDELITY.md:123-125). Retrieval runs over managed, pinned generations (docs/rag_it_all.md:221).

## Index

| # | Paper | arXiv id | Status |
| --- | --- | --- | --- |
| 1 | HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models | [2405.14831](https://arxiv.org/abs/2405.14831) | implemented |
| 2 | From RAG to Memory: Non-Parametric Continual Learning for Large Language Models (HippoRAG 2) | [2502.14802](https://arxiv.org/abs/2502.14802) | implemented |
| 3 | Dense Passage Retrieval for Open-Domain Question Answering | [2004.04906](https://arxiv.org/abs/2004.04906) | partially |
| 4 | Nomic Embed: Training a Reproducible Long Context Text Embedder | [2402.01613](https://arxiv.org/abs/2402.01613) | implemented |
| 5 | From Louvain to Leiden: guaranteeing well-connected communities | [1810.08473](https://arxiv.org/abs/1810.08473) | implemented |
| 6 | SQuAD: 100,000+ Questions for Machine Comprehension of Text | [1606.05250](https://arxiv.org/abs/1606.05250) | implemented |
| 7 | Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions (IRCoT) | [2212.10509](https://arxiv.org/abs/2212.10509) | not yet |
| 8 | From Local to Global: A Graph RAG Approach to Query-Focused Summarization (GraphRAG) | [2404.16130](https://arxiv.org/abs/2404.16130) | not yet |
| 9 | LightRAG: Simple and Fast Retrieval-Augmented Generation | [2410.05779](https://arxiv.org/abs/2410.05779) | not yet |
| 10 | RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval | [2401.18059](https://arxiv.org/abs/2401.18059) | not yet |
| 11 | NodeRAG: Structuring Graph-based RAG with Heterogeneous Nodes | [2504.11544](https://arxiv.org/abs/2504.11544) | partially |
| 12 | G-Retriever: Retrieval-Augmented Generation for Textual Graph Understanding and Question Answering | [2402.07630](https://arxiv.org/abs/2402.07630) | not yet |
| 13 | Breaking the Static Graph: Context-Aware Traversal for Robust Retrieval-Augmented Generation (CatRAG) | [2602.01965](https://arxiv.org/abs/2602.01965) | not yet |
| 14 | Cross-Granularity Hypergraph Retrieval-Augmented Generation for Multi-hop Question Answering (HGRAG) | [2508.11247](https://arxiv.org/abs/2508.11247) | not yet |
| 15 | VDGR-RAG: Vectors, Directories, Graphs, and Reflection Are All You Need for Unified Reasoning over Hierarchical Enterprise Knowledge | [2608.07994](https://arxiv.org/abs/2608.07994) | not yet |
| 16 | Re2G: Retrieve, Rerank, Generate | [2207.06300](https://arxiv.org/abs/2207.06300) | not yet |
| 17 | Late Chunking: Contextual Chunk Embeddings Using Long-Context Embedding Models | [2409.04701](https://arxiv.org/abs/2409.04701) | not yet |
| 18 | Zep: A Temporal Knowledge Graph Architecture for Agent Memory | [2501.13956](https://arxiv.org/abs/2501.13956) | partially |
| 19 | RAG Meets Temporal Graphs: Time-Sensitive Modeling and Retrieval for Evolving Knowledge (TG-RAG) | [2510.13590](https://arxiv.org/abs/2510.13590) | partially |
| 20 | RepoCoder: Repository-Level Code Completion Through Iterative Retrieval and Generation | [2303.12570](https://arxiv.org/abs/2303.12570) | not yet |
| 21 | GraphCoder: Enhancing Repository-Level Code Completion via Code Context Graph-based Retrieval and Language Model | [2406.07003](https://arxiv.org/abs/2406.07003) | not yet |
| 22 | GraphCodeAgent: Dual Graph-Guided LLM Agent for Retrieval-Augmented Repo-Level Code Generation (v1: CodeRAG) | [2504.10046](https://arxiv.org/abs/2504.10046) | not yet |
| 23 | RASL: Retrieval Augmented Schema Linking for Massive Database Text-to-SQL | [2507.23104](https://arxiv.org/abs/2507.23104) | not yet |
| 24 | RAGChecker: A Fine-grained Framework for Diagnosing Retrieval-Augmented Generation | [2408.08067](https://arxiv.org/abs/2408.08067) | not yet |

Totals: 5 implemented, 4 partially, 15 not yet.

## 1. HippoRAG

* **Authors:** Bernal Jiménez Gutiérrez, Yiheng Shu, Yu Gu, Michihiro Yasunaga, Yu Su
* **Year:** 2024 (NeurIPS 2024)
* **arXiv:** [2405.14831](https://arxiv.org/abs/2405.14831). Version read: v3 (14 Jan 2025), full text. Earlier versions: v1 (23 May 2024), v2 (19 Dec 2024).
* **Which paper to cite:** hippo's code follows the reference implementation of the follow-up paper, HippoRAG 2 (entry 2) (src/hippo/hipporag/__init__.py:33-35, docs/FIDELITY.md:3-6). Entry 2 is therefore the main citation. This entry covers the ideas the first paper introduced. The README credits both papers (README.md:419-420).

### Why it is included

HippoRAG built the architecture hippo is named after. Offline, an LLM extracts an open knowledge graph from passages. At query time, Personalized PageRank spreads activation from seed nodes and ranks passages by what it reaches. The package docstring maps hippo's modules onto that pipeline step by step (src/hippo/hipporag/__init__.py:4-23). The paper picks its seeds by extracting "query named entities" and linking them to graph nodes. hippo keeps the offline half and the PPR step, but seeds the way HippoRAG 2 does.

### Features implemented

* LLM OpenIE: named entities first, then triples with the entity list as a hint, one passage per call (src/hippo/hipporag/openie.py:1-11, src/hippo/hipporag/openie.py:52, docs/FIDELITY.md:34-40).
* Graph nodes come from triple subjects and objects, with ids derived from the cleaned phrase (src/hippo/hipporag/text.py:15, src/hippo/hipporag/text.py:33, docs/FIDELITY.md:27-29).
* Synonymy edges between entities whose embedding similarity is at least 0.8, capped at 100 neighbours per entity (src/hippo/hipporag/indexer.py:13-14, src/hippo/hipporag/indexer.py:89, src/hippo/store/base.py:22).
* Node specificity: an entity's seed weight is divided by the number of passages that mention it. The paper describes this as an IDF-like signal (src/hippo/hipporag/retriever.py:413-414, src/hippo/store/base.py:21).
* Personalized PageRank over the undirected weighted graph, using the reference's exact igraph call (src/hippo/hipporag/graph_index.py:715-732, docs/FIDELITY.md:79-80).
* Single-step retrieval. The paper compares this against iterative retrieval, and it is the path hippo implements (docs/FIDELITY.md:164-166).

### Possibly new features

* **Query named-entity seeding (NER-to-node).** HippoRAG 2 replaced this with query-to-triple matching, and hippo follows HippoRAG 2 (src/hippo/hipporag/retriever.py:317-331). Bringing it back would only make sense as a named comparison mode, because I10 requires every new ranking to be a measurable, reversible change (docs/rag_it_all.md:225).
* **HippoRAG inside an IRCoT loop.** The paper reports further gains from this combination. hippo is single-step by design; see entry 7.

### What we would get

Very little beyond what HippoRAG 2 already provides. The NER-to-node route is mostly useful as a regression baseline on entity-heavy corpora, which is how the plan already treats this paper (docs/rag_it_all.md:107). The cost is one more ranking mode to maintain and evaluate.

## 2. From RAG to Memory: Non-Parametric Continual Learning for Large Language Models (HippoRAG 2)

* **Authors:** Bernal Jiménez Gutiérrez, Yiheng Shu, Weijian Qi, Sizhe Zhou, Yu Su
* **Year:** 2025 (ICML 2025)
* **arXiv:** [2502.14802](https://arxiv.org/abs/2502.14802). Version read: v2 (19 Jun 2025), full text (HTML). Earlier version: v1 (20 Feb 2025).

### Why it is included

hippo's prose retrieval is a step-for-step port of the HippoRAG 2 reference implementation. It uses the same defaults, the same filter prompt, the same PPR call and the same edge-weight rule, and docs/FIDELITY.md records every match and every deliberate deviation (docs/FIDELITY.md:9-273). The paper makes three changes to HippoRAG:

* passage nodes joined to their phrases by "context" edges;
* query-to-triple matching in place of NER-to-node linking;
* an LLM "recognition memory" filter over the retrieved triples.

It also returns plain dense results when no triple survives the filter. These are the stages of `retrieve` in hippo's retriever (src/hippo/hipporag/retriever.py:256-513).

### Features implemented

* **Passage nodes** linked to every entity their triples mention, at weight 1.0 (src/hippo/hipporag/indexer.py:11-12, src/hippo/hipporag/graph_index.py:21-23, docs/FIDELITY.md:47).
* **Query-to-triple matching.** The question vector is dot-multiplied with every fact vector, the scores are min-max normalised, and the top `linking_top_k` = 5 facts go to the filter (src/hippo/hipporag/retriever.py:317-323, src/hippo/store/base.py:18).
* **Recognition memory.** The LLM filter uses the reference's instruction and ten demonstrations, sent as chat turns with a JSON schema instead of DSPy markers (src/hippo/hipporag/retriever.py:221-233, src/hippo/prompts.py:151, src/hippo/prompts.py:307, docs/FIDELITY.md:97-105).
* **Dense fallback** when no fact survives the filter and the question named no code (src/hippo/hipporag/retriever.py:385-400).
* **Passage seed weight** equal to the normalised dense score times `passage_node_weight` = 0.05 (src/hippo/hipporag/retriever.py:444-446, src/hippo/store/base.py:19).
* **Entity seeds** averaged over occurrences and cut to the top `linking_top_k` (src/hippo/hipporag/retriever.py:402-442).
* **PPR** with damping 0.5 (src/hippo/store/base.py:20, src/hippo/hipporag/graph_index.py:715-732).
* **Answering** with the reference's one-shot `rag_qa` prompt over the top `qa_top_k` = 5 passages (src/hippo/prompts.py:317-319, src/hippo/prompts.py:353, src/hippo/hipporag/answerer.py:31, src/hippo/store/base.py:24).
* **Incremental synonymy.** Only newly added entities are compared against all entities (src/hippo/hipporag/indexer.py:221, docs/FIDELITY.md:50-51).
* **Deliberate adaptations**, each documented:
  * facts are embedded as plain sentences (src/hippo/hipporag/text.py:43, docs/FIDELITY.md:106-110);
  * passage ids are scoped per source (docs/FIDELITY.md:111-116);
  * the graph lives in a database, LadybugDB by default, instead of pickles (docs/FIDELITY.md:123-138);
  * code edges add a fourth weight term, which has no effect on prose-only memories (src/hippo/hipporag/graph_index.py:157-166, docs/FIDELITY.md:263-273).

### Possibly new features

* **Separate query instructions for facts and for passages.** The reference does this with NV-Embed-v2. hippo embeds the question once, with only the embedding model's own prefix (docs/FIDELITY.md:139-146). Adopting it needs an instruction-following embedding model and a second embedding call per question. It conflicts with no rule.
* **The paper's three evaluation axes** (factual memory, sense-making, associativity) on its public datasets, run as a regression slice for the legacy route. The plan is clear that public benchmarks do not replace an enterprise gold set (docs/rag_it_all.md:127).
* **The reference's iterative `retrieve_ircot` mode** (docs/FIDELITY.md:164-166); see entry 7.

### What we would get

The core of this paper is already implemented. The remaining ideas mainly buy comparability: the ability to show that hippo reproduces the published numbers on the paper's datasets. The cost is running larger embedding models locally, plus more evaluation to keep green.

## 3. Dense Passage Retrieval for Open-Domain Question Answering

* **Authors:** Vladimir Karpukhin, Barlas Oğuz, Sewon Min, Patrick Lewis, Ledell Wu, Sergey Edunov, Danqi Chen, Wen-tau Yih
* **Year:** 2020 (EMNLP 2020)
* **arXiv:** [2004.04906](https://arxiv.org/abs/2004.04906). Version read: v3 (30 Sep 2020), abstract. Earlier versions: v1 (10 Apr 2020), v2 (2 May 2020).

### Why it is included

HippoRAG 2's fallback path, which hippo reproduces, is named after this paper: the trace records `used_dpr_fallback`, and every ranking keeps a `dpr_rank` (src/hippo/hipporag/retriever.py:154-155, src/hippo/hipporag/retriever.py:179, docs/FIDELITY.md:81-83). DPR showed that question and passage embeddings from a dual encoder, compared by inner product, can replace sparse retrieval. hippo applies that scoring pattern to vectors from an off-the-shelf embedding model served by Ollama (src/hippo/config.py:50, src/hippo/hipporag/retriever.py:313). On the managed path, the dense session binds those vectors to one exact embedding profile (src/hippo/knowledge/dense_session.py:1-5, src/hippo/knowledge/dense.py:1-5).

### Features implemented

* Inner-product scoring of the question against precomputed passage vectors. It is used as the fallback ranking and as the passage seed signal for PPR (src/hippo/hipporag/retriever.py:313-315, src/hippo/hipporag/retriever.py:444-446).
* Passages stay reachable through dense retrieval when OpenIE fails on them (docs/FIDELITY.md:161-163).

### Possibly new features

* **Training a dual encoder** on hippo's own question and evidence pairs, as DPR does. This needs training infrastructure and model hosting beyond Ollama. The plan requires any new model dependency to show a measured advantage on its target slice and to have a rollback (docs/rag_it_all.md:847).
* **An approximate nearest-neighbour index** in place of exact matrix products. Today every vector is loaded into memory (docs/rag_it_all.md:89). The plan allows LadybugDB's native vector search only after correctness, isolation and recall checks pass (docs/rag_it_all.md:913-917). Approximate search can miss evidence without saying so, so it would have to disclose that its results are approximate to satisfy I11 (docs/rag_it_all.md:226).

### What we would get

A domain-trained encoder could raise recall on vocabulary that general models handle poorly, such as identifiers, ticket ids and internal product names. An approximate index would cut memory use and latency on large memories. The costs are training data and a model lifecycle for the encoder, and a recall loss for the index that must be measured and reported.

## 4. Nomic Embed: Training a Reproducible Long Context Text Embedder

* **Authors:** Zach Nussbaum, John X. Morris, Brandon Duderstadt, Andriy Mulyar
* **Year:** 2024 (TMLR)
* **arXiv:** [2402.01613](https://arxiv.org/abs/2402.01613). Version read: v2 (3 Feb 2025), full text. Earlier version: v1 (2 Feb 2024).

### Why it is included

`nomic-embed-text` is hippo's default embedding model (src/hippo/config.py:50). The paper defines the task prefixes that model expects: `search_query` for the question and `search_document` for the text being searched. hippo prepends exactly those two prefixes (src/hippo/ollama.py:29-34). FIDELITY records the choice to use only the model's own prefixes rather than HippoRAG 2's per-target instructions (docs/FIDELITY.md:139-146).

### Features implemented

* The `search_query: ` prefix on questions and `search_document: ` on everything stored (src/hippo/ollama.py:32, src/hippo/hipporag/retriever.py:310).
* The managed dense session reads the same prefix table, so stored and query vectors are always encoded under matching prefixes (src/hippo/knowledge/dense_session.py:14).

### Possibly new features

* **Longer embedding inputs.** The model accepts 8192-token inputs. hippo cuts passages at 1500 characters to fit the answering model's 8k window, not the embedder's limit (src/hippo/ingest/chunker.py:4-7, docs/FIDELITY.md:147-150). A separate, longer view per section or per symbol could be embedded without changing what the answering model reads. That view is a derived view and falls under I13 (docs/rag_it_all.md:228).
* **The `clustering` prefix** for grouping related text, as an input to the grouped summaries the plan describes for broad questions (docs/rag_it_all.md:804).

### What we would get

The main idea is already implemented. Longer embedding views could keep a long function or section in one vector instead of several partial ones, which should help dense recall on long units. The cost is coarser vectors and more re-embedding work whenever a long unit changes.

## 5. From Louvain to Leiden: guaranteeing well-connected communities

* **Authors:** Vincent Traag, Ludo Waltman, Nees Jan van Eck
* **Year:** 2018 on arXiv (Scientific Reports 9:5233, 2019)
* **arXiv:** [1810.08473](https://arxiv.org/abs/1810.08473). Version read: v3 (30 Oct 2019), abstract. Earlier versions: v1 (19 Oct 2018), v2 (16 Aug 2019).

### Why it is included

hippo groups code modules into subsystems with igraph's `community_leiden` (src/hippo/hipporag/indexer.py:561-573), called from the indexing job (src/hippo/hipporag/indexer.py:275). The resulting label names subsystems in answers and on the Graph page. It also drives an optional ranking prior that ships switched off (src/hippo/store/base.py:32, docs/FIDELITY.md:232-236). The paper's guarantee that every community is internally connected is what makes a community usable as a "subsystem".

### Features implemented

* A module-level projection: one vertex per module, weighted by how many relations cross between two modules, partitioned by Leiden with the modularity objective (src/hippo/hipporag/indexer.py:534-558, src/hippo/hipporag/indexer.py:571-573).
* Deterministic runs. The random number generator is seeded under a lock, and community numbers are relabelled by the smallest module name in each community (src/hippo/hipporag/indexer.py:561-584).
* Each community's display label is its lexicographically smallest member qualname (src/hippo/hipporag/graph_index.py:1202-1212).
* A post-PPR boost for passages whose symbols share a community with a kept seed, default 0.0 (src/hippo/hipporag/retriever.py:622-635, src/hippo/store/base.py:32).
* A caveat: when the managed structural projection has no stored statistics, it assigns communities from the connected components of the code subgraph, not from Leiden (src/hippo/knowledge/projection.py:871-881).

### Possibly new features

* **Leiden in the managed projection** in place of connected components, so subsystem labels agree between the legacy and managed paths. It must stay deterministic, because view fingerprints depend on stable output.
* **Hierarchical (recursive) Leiden** for nested subsystem labels, the way GraphRAG partitions its graph (entry 8). Every level is a derived view under I13 (docs/rag_it_all.md:228).
* **Turning the community prior on**, once an evaluation set shows it helps. FIDELITY leaves that decision to an eval (docs/FIDELITY.md:236).

### What we would get

Consistent subsystem labels on both paths, and possibly a ranking signal for code questions that stay inside one subsystem. The costs are keeping labels deterministic across rebuilds, and the risk that a community prior favours large subsystems.

## 6. SQuAD: 100,000+ Questions for Machine Comprehension of Text

* **Authors:** Pranav Rajpurkar, Jian Zhang, Konstantin Lopyrev, Percy Liang
* **Year:** 2016 (EMNLP 2016)
* **arXiv:** [1606.05250](https://arxiv.org/abs/1606.05250). Version read: v3 (11 Oct 2016), full text. Earlier versions: v1 (16 Jun 2016), v2 (7 Oct 2016).

### Why it is included

hippo's answer metrics are the ones this paper defined. Exact match and macro-averaged F1 are both computed after normalisation that "ignore[s] punctuations and articles". hippo takes the normalisation steps, in the same order, from the HippoRAG reference (src/hippo/evals/metrics.py:37-53, docs/FIDELITY.md:172-174). The LLM judge exists because these two metrics penalise harmless rewording (src/hippo/evals/judge.py:1-14).

### Features implemented

* `normalize_answer`: lowercase, strip punctuation, remove articles, collapse whitespace (src/hippo/evals/metrics.py:37-53).
* Exact match, taking the best score over all accepted answers (src/hippo/evals/metrics.py:63-68).
* Token-overlap F1, taking the best score over all accepted answers (src/hippo/evals/metrics.py:71-86).

### Possibly new features

* **A second-annotator ceiling.** The paper estimates human performance by treating a second answer as a prediction. hippo's gold sets could record a second reviewed answer for each question, to tell ambiguous gold answers apart from system errors. The plan already requires LLM judgments to be calibrated against a human-reviewed sample (docs/rag_it_all.md:1100).

### What we would get

The metrics are already implemented. A second-annotator ceiling would show whether a low exact-match score reflects the system or the gold data, and would give the judge a human reference point. The cost is annotation effort per question.

## 7. Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions (IRCoT)

* **Authors:** Harsh Trivedi, Niranjan Balasubramanian, Tushar Khot, Ashish Sabharwal
* **Year:** 2022 on arXiv (ACL 2023)
* **arXiv:** [2212.10509](https://arxiv.org/abs/2212.10509). Version read: v2 (23 Jun 2023), abstract. Earlier version: v1 (20 Dec 2022).

### Why it is included

IRCoT alternates retrieval with chain-of-thought steps, so that "what to retrieve depends on what has already been derived". The HippoRAG paper uses IRCoT as its iterative baseline and reports further gains from running HippoRAG inside it (entry 1). The HippoRAG 2 reference also ships an IRCoT-style multi-step mode. hippo implements only the single-step path and never goes back to the graph for more facts (docs/FIDELITY.md:164-171). The plan adopts a bounded version: at most three declared evidence needs and one follow-up round of at most three subqueries (docs/rag_it_all.md:123, docs/rag_it_all.md:770, docs/rag_it_all.md:1496).

### Features implemented

None. The code keep/drop/expand pass is a second LLM step, but it runs over passages already ranked. It does not retrieve anything based on intermediate reasoning (src/hippo/hipporag/retriever.py:504-506, docs/FIDELITY.md:237-246).

### Possibly new features

* **An interleaved retrieve-and-reason loop in the prose route.** This would break FIDELITY's single-step guarantee, so it would have to run as a named mode beside the legacy one (docs/FIDELITY.md:164-171, docs/rag_it_all.md:225).
* **The plan's bounded follow-up**, which consists of:
  * an evidence-needs ledger;
  * one follow-up round sharing the original budget;
  * stop rules for no new evidence, a repeated query, the deadline or the token limit;
  * unresolved dependencies marked as unresolved rather than filled with invented identifiers.
  
  (docs/rag_it_all.md:770, docs/rag_it_all.md:1496)

### What we would get

Better recall on questions whose second hop can only be named after reading the first, such as "who owns the service that writes this table". The costs are more model calls and latency per question. There is also the risk that a reasoning step steers retrieval toward identifiers that do not exist, which is what the plan's bounds and validation are meant to contain.

## 8. From Local to Global: A Graph RAG Approach to Query-Focused Summarization (GraphRAG)

* **Authors:** Darren Edge, Ha Trinh, Newman Cheng, Joshua Bradley, Alex Chao, Apurva Mody, Steven Truitt, Dasha Metropolitansky, Robert Osazuwa Ness, Jonathan Larson
* **Year:** 2024
* **arXiv:** [2404.16130](https://arxiv.org/abs/2404.16130). Version read: v2 (19 Feb 2025), full text. Earlier version: v1 (24 Apr 2024).

### Why it is included

GraphRAG works in three stages:

* it extracts an entity graph and partitions it with Leiden "in a hierarchical manner";
* it generates community summaries from the bottom of the hierarchy up;
* it answers global questions by map-reduce: each community summary yields a partial answer, and the partial answers are then combined.

The plan cites it for corpus-wide synthesis and puts it behind scoped, grouped summaries that keep their original citations (docs/rag_it_all.md:109, docs/rag_it_all.md:804, docs/rag_it_all.md:843). hippo does run Leiden over code modules, but only to label subsystems. Nothing in hippo summarises a community (src/hippo/hipporag/indexer.py:534-558, src/hippo/hipporag/graph_index.py:1202-1212).

### Features implemented

None. The Leiden subsystem labels come from entry 5, not from GraphRAG's summarisation method.

### Possibly new features

* **Per-group summaries** (service, domain, subsystem) for broad questions: the plan's `group_summary` experiment, currently off. Each summary would keep its contributors and membership fingerprint and be invalidated on edits, deletions and policy changes (docs/rag_it_all.md:843, docs/rag_it_all.md:228). A summary can never replace the original citations (docs/rag_it_all.md:109, docs/rag_it_all.md:216).
* **Map-reduce answering over those summaries.** Each partial answer must carry the original evidence it summarises; otherwise the answer breaks I1.
* **Hierarchical communities over prose entities**, not only over code modules.
* Exact counts and complete lists are not a summarisation problem. The plan sends them to scoped typed queries instead (docs/rag_it_all.md:802).

### What we would get

Answers to corpus-wide questions, such as "what are the main subsystems and what does each own", which top-k passage retrieval handles poorly. The costs:

* a large LLM bill at indexing time;
* summaries that go stale on every edit and must be invalidated;
* a derived artifact that can guide retrieval but can never be cited as evidence.

## 9. LightRAG: Simple and Fast Retrieval-Augmented Generation

* **Authors:** Zirui Guo, Lianghao Xia, Yanhua Yu, Tu Ao, Chao Huang
* **Year:** 2024
* **arXiv:** [2410.05779](https://arxiv.org/abs/2410.05779). Version read: v3 (28 Apr 2025), full text (HTML). Earlier versions: v1 (8 Oct 2024), v2 (7 Nov 2024).

### Why it is included

LightRAG combines two levels of retrieval:

* **Low-level:** "specific entities along with their associated attributes or relationships", found by matching local keywords to entities.
* **High-level:** "broader topics and overarching themes", found by matching global keywords to relations whose index keys include LLM-generated themes.

It updates its graph incrementally by "taking the union of the node sets and edge sets", and merges identical entities and relations across chunks. The plan borrows the comparison between a local lookup route and a broader relationship route, without adopting the framework itself (docs/rag_it_all.md:110).

### Features implemented

None. Two things in hippo look similar but do not come from LightRAG:

* The incremental synonym pass over new entities comes from HippoRAG 2 (docs/FIDELITY.md:50-51).
* Identical entity names merge because entity ids are a hash of the cleaned phrase, as in the HippoRAG reference (docs/FIDELITY.md:27-29).

### Possibly new features

* **Query keywords split into local and global sets**, with a relation-level route for thematic questions. This would be one more channel in the planned fusion (docs/rag_it_all.md:712-719) and adds a model call per question.
* **LLM-generated index keys and summaries on relations.** These are model inferences: they must stay labelled as such and be invalidated with their inputs (docs/rag_it_all.md:218, docs/rag_it_all.md:228).
* **Union-style incremental updates to the in-memory index** instead of a full reload. Today every graph version bump reloads the whole index (docs/FIDELITY.md:135-138). An incremental path must keep the pinned-snapshot guarantee (docs/rag_it_all.md:221).

### What we would get

A route for thematic questions that do not name any entity, and cheaper refreshes on large memories. The costs: changing the in-memory index in place complicates fingerprints and snapshot pinning, and generated relation keys add indexing cost plus more derived text to invalidate.

## 10. RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval

* **Authors:** Parth Sarthi, Salman Abdullah, Aditi Tuli, Shubh Khanna, Anna Goldie, Christopher D. Manning
* **Year:** 2024
* **arXiv:** [2401.18059](https://arxiv.org/abs/2401.18059). Version read: v1 (31 Jan 2024), abstract. This is the only version.

### Why it is included

RAPTOR "recursively embed[s], cluster[s], and summarize[s] chunks of text, constructing a tree with differing levels of summarization from the bottom up", and retrieves across the levels of that tree. The plan cites it for long requirement documents. It starts, though, from real headings and parent expansion, and leaves a generated hierarchy to a switched-off experiment (docs/rag_it_all.md:111, docs/rag_it_all.md:843). hippo's chunker already keeps the author's structure: it splits on markdown headings, titles each section "Doc › Heading" and numbers the parts of long sections (src/hippo/ingest/chunker.py:9-16, src/hippo/ingest/chunker.py:226-243).

### Features implemented

None. Passage titles built from headings are the document's own structure, not a RAPTOR tree.

### Possibly new features

* **Heading and breadcrumb search** with bounded expansion to parent and child sections. This is the plan's non-generated alternative to a summary tree (docs/rag_it_all.md:1477).
* **A generated summary tree over sections**: the plan's `section_summary` experiment, currently off. Each summary keeps contributor fingerprints and is invalidated on edits (docs/rag_it_all.md:843). Summaries are derived views, so I3 and I13 apply (docs/rag_it_all.md:218, docs/rag_it_all.md:228).

### What we would get

Better answers when the evidence is spread over several chunks of one long section, for example a requirement stated across several paragraphs. The costs are summary generation for every document and re-summarisation after edits. A tree built by clustering can also cut across the author's own headings, which hippo already records.

## 11. NodeRAG: Structuring Graph-based RAG with Heterogeneous Nodes

* **Authors:** Tianyang Xu, Haojie Zheng, Chengze Li, Haoxiang Chen, Yixin Liu, Ruoxi Chen, Lichao Sun
* **Year:** 2025
* **arXiv:** [2504.11544](https://arxiv.org/abs/2504.11544). Version read: v1 (15 Apr 2025), full text (HTML). This is the only version.

### Why it is included

NodeRAG's graph gives information seven node types: entity, relationship, semantic unit (an "independent event unit in a paraphrased form"), attribute, high-level element, high-level overview, and the original text. Search works in three stages:

* it enters the graph by exact matching on title nodes plus vector similarity;
* it spreads with a shallow Personalized PageRank that stops early;
* it treats the base layer of an HNSW index as extra semantic edges.

High-level elements come from Leiden communities.

The plan calls NodeRAG a central design influence for three things: heterogeneous identities, relationship records, and distinct search views. It keeps parser facts authoritative and generated summaries derived (docs/rag_it_all.md:135, docs/rag_it_all.md:161). hippo's managed knowledge model follows that direction in its schema.

### Features implemented

* **Relationships as records of their own**, not bare edges:
  * An `Assertion` holds the stable subject–predicate–object identity.
  * Each `AssertionVersion` carries its own evidence class, confidence, status and time axes.
  * An `AssertionSupport` ties a version to the spans that support it.
  
  (src/hippo/knowledge/model.py:511-517, src/hippo/knowledge/model.py:548-553, src/hippo/knowledge/model.py:576-580)
* **Typed object identities across many roles**: services, APIs, owners, repositories, symbols, commits, tables, columns, requirements, tickets, decisions and documents (src/hippo/knowledge/model.py:56-87).
* **A separate retrieval-view record.** It points back to an original span and source revision and carries a dependency fingerprint for invalidation (src/hippo/knowledge/model.py:1008-1028).
  * The view vocabulary names exact, lexical, dense, passage, schema-card, symbol signature, body and documentation, section and summary views (src/hippo/knowledge/model.py:842-863).
  * At this commit, only `projection` views are actually materialised, for code inputs and prose inputs (src/hippo/knowledge/code_binding.py:575-585, src/hippo/knowledge/input_binding.py:334-344).
* **Evidence classes** that keep parser observations, declarations, discussion claims and model inferences apart. The plan relies on them to keep any generated node type marked as derived (src/hippo/knowledge/model.py:46-48, docs/rag_it_all.md:218).

### Possibly new features

* **Semantic-unit nodes**: LLM-paraphrased event units, stored as a `model_inferred` view that always links back to its original spans (docs/rag_it_all.md:135, docs/rag_it_all.md:218).
* **Attribute, high-level element and overview nodes** built from community summaries (see entry 8), and invalidated whenever their members change (docs/rag_it_all.md:228).
* **The declared views that are not built yet**: exact, lexical, dense, section and symbol views as separate searchable representations (docs/rag_it_all.md:442, docs/rag_it_all.md:1470, docs/rag_it_all.md:1477).
* **NodeRAG's search stages.** This means dual entry (exact title match plus vector search), shallow PPR with early stopping, and HNSW-proximity edges. Two rules constrain it. hippo's legacy PPR must stay the reference's exact call (docs/FIDELITY.md:79-80). LadybugDB's native vector index is allowed only after correctness and recall checks (docs/rag_it_all.md:913-917).

### What we would get

A search representation tuned to each kind of thing (a symbol's signature, a table card, a document section), so a question can match the kind of object it asks about, and every hit still resolves to an original span. The costs:

* more views to build, embed and invalidate for each source revision;
* extra LLM spend for the generated node types (semantic units, attributes, overviews);
* those generated nodes must never be cited in place of the original text.

## 12. G-Retriever: Retrieval-Augmented Generation for Textual Graph Understanding and Question Answering

* **Authors:** Xiaoxin He, Yijun Tian, Yifei Sun, Nitesh V. Chawla, Thomas Laurent, Yann LeCun, Xavier Bresson, Bryan Hooi
* **Year:** 2024
* **arXiv:** [2402.07630](https://arxiv.org/abs/2402.07630). Version read: v3 (27 May 2024), full text (HTML). Earlier versions: v1 (12 Feb 2024), v2 (14 Mar 2024).

### Why it is included

G-Retriever works in three steps:

* It retrieves the graph nodes and edges most similar to the query.
* It extracts a connected subgraph by solving a Prize-Collecting Steiner Tree (PCST) problem. The top-k items get prizes from k down to 1, and every edge has an adjustable cost that controls the subgraph's size.
* It gives a frozen LLM both a graph-encoder token and a text rendering of the subgraph.

The plan adopts the objective of packing small connected evidence paths. It starts from bounded deterministic traversal, though, with no GNN training (docs/rag_it_all.md:112). hippo's code path tools already walk bounded directed paths. They render those paths as typed relation lines in a "Code graph" block, most confident first (src/hippo/hipporag/paths.py:201-239, src/hippo/hipporag/paths.py:350, docs/FIDELITY.md:247-253). Those walks are breadth-first searches, not PCST.

### Features implemented

None.

### Possibly new features

* **PCST-style selection inside the evidence packer.** Prizes would come from fused rank and each edge would carry a cost, so a pack keeps the connecting path between relevant facts (docs/rag_it_all.md:1493). A pack that cannot fit the required connected evidence must say so rather than cut it (docs/rag_it_all.md:759, docs/rag_it_all.md:226).
* **Prize-weighted subgraph extraction over the prose entity/passage graph**, as an alternative to taking the top passages after PPR.
* **A graph-encoder token passed as a soft prompt.** This needs a trained encoder and a model that accepts soft prompts. hippo talks to its local chat model through plain text messages (src/hippo/hipporag/answerer.py:45), so this conflicts with the local-model setup.

### What we would get

Evidence packs that keep the path between facts instead of isolated top passages. That matters for "how does A reach B" questions when the answering model reads only five passages (src/hippo/store/base.py:24). The costs are an approximate solver and careful calibration of prizes and edge costs, and a budgeted solver must never silently cut a required join or path.

## 13. Breaking the Static Graph: Context-Aware Traversal for Robust Retrieval-Augmented Generation (CatRAG)

* **Authors:** Kwun Hang Lau, Fangyuan Zhang, Boyu Ruan, Yingli Zhou, Qintian Guo, Ruiyuan Zhang, Xiaofang Zhou
* **Year:** 2026
* **arXiv:** [2602.01965](https://arxiv.org/abs/2602.01965). Version read: v1 (2 Feb 2026), abstract. This is the only version. The plan calls it CatRAG (docs/rag_it_all.md:139).

### Why it is included

The paper names a "Static Graph Fallacy" in HippoRAG: one fixed set of edge weights serves every query. It adds three mechanisms:

* symbolic anchoring for entity constraints;
* query-dependent edge weighting;
* passage weight enhancement, which anchors the random walk to likely evidence.

hippo's PPR runs over weights fixed when the graph loads, the same for every question (src/hippo/hipporag/graph_index.py:157-166, src/hippo/hipporag/retriever.py:476-477). The plan registers `query_weighted_ppr`, request-local weights on the prose projection, as a switched-off experiment (docs/rag_it_all.md:841).

### Features implemented

None. hippo's lexical code anchors do seed PPR from identifiers named in the question (src/hippo/hipporag/anchors.py:295, docs/FIDELITY.md:215-226), which looks like symbolic anchoring. They are hippo's own code-graph adaptation, however, and they never change edge weights.

### Possibly new features

* **Request-local edge weights on the authorized prose projection.** Edge ids are validated, the route falls back to static PPR, and stored weights never change (docs/rag_it_all.md:841). It must stay a named mode so the legacy PPR call remains exactly the reference's (docs/FIDELITY.md:79-80, docs/rag_it_all.md:225).
* **Passage weight enhancement**: raising the passage seed weight per query for passages judged likely to be evidence. The paper's own ablation shows this hurts one structured dataset (docs/rag_it_all.md:139).
* **Weak entity seeds** taken from the question, with boosts kept off the schema, code and catalog routes (docs/rag_it_all.md:841).

### What we would get

Better multi-hop recall when static weights send activation through hub entities that have nothing to do with the question. The costs: model judgments about edges add latency and tokens to every query, and query-dependent weights make a ranking harder to replay. hippo's simulation tools rely on replaying a recorded trace (src/hippo/hipporag/retriever.py:269-274).

## 14. Cross-Granularity Hypergraph Retrieval-Augmented Generation for Multi-hop Question Answering (HGRAG)

* **Authors:** Changjian Wang, Weihong Deng, Weili Guan, Quan Lu, Ning Jiang
* **Year:** 2025
* **arXiv:** [2508.11247](https://arxiv.org/abs/2508.11247). Version read: v1 (15 Aug 2025), abstract. This is the only version.

### Why it is included

HGRAG builds an entity hypergraph in which "fine-grained entities serve as nodes and coarse-grained passages as hyperedges". It then retrieves by a diffusion process that combines entity and passage similarity. The plan registers a matching `prose_incidence` experiment: passage–entity membership stored in LadybugDB, sparse diffusion computed in memory, and dense and exact candidates protected (docs/rag_it_all.md:143, docs/rag_it_all.md:839). hippo already stores the membership such a route needs: every passage links to the entities it mentions (src/hippo/hipporag/indexer.py:11-12). Passage similarity also already seeds PPR (src/hippo/hipporag/retriever.py:444-446).

### Features implemented

None.

### Possibly new features

* **Passage–entity incidence diffusion as its own prose route**, keeping dense hits that are not connected to the graph (docs/rag_it_all.md:839). LadybugDB nodes and membership edges are enough; no hypergraph database is needed (docs/rag_it_all.md:143).
* **The tests the plan lists for it**: missing entities, hubs, passages with zero degree, and finite non-negative weights (docs/rag_it_all.md:839).

### What we would get

A prose route that treats a passage as one unit tying all its entities together. It can surface passages whose entities are only weakly linked in the triple graph. The costs are another ranking to tune, compared at equal evidence budgets. The paper's gains also vary by dataset and by the final evidence count (docs/rag_it_all.md:143).

## 15. VDGR-RAG: Vectors, Directories, Graphs, and Reflection Are All You Need for Unified Reasoning over Hierarchical Enterprise Knowledge

* **Authors:** Wenqi Chen, Haofei Yang, Rui Yang, Fangming Li
* **Year:** 2026
* **arXiv:** [2608.07994](https://arxiv.org/abs/2608.07994). Version read: v2 (18 Aug 2026), abstract. Earlier version: v1 (8 Aug 2026).

### Why it is included

VDGR-RAG builds a hierarchical, heterogeneous knowledge graph from document chunks that keeps the chunks' structural relationships. It then uses four tools:

* routing guided by the table of contents;
* multi-route vector and graph retrieval;
* backtracking to correct localisation errors;
* a reflection step that sequences the retrieval phases.

The plan adopts real heading and breadcrumb search with bounded parent/child expansion. It rejects the paper's global name-only deduplication and its discarding of low-level engineering identifiers (docs/rag_it_all.md:136, docs/rag_it_all.md:1477). hippo's passages already carry breadcrumb titles for prose sections and "path :: module.qualname (lines a-b)" titles for code symbols (src/hippo/ingest/chunker.py:9-16, src/hippo/ingest/chunker.py:23-30). Nothing searches or routes by those titles yet.

### Features implemented

None.

### Possibly new features

* **A hierarchy channel** that searches section headings and breadcrumbs, then expands to the original children and parents within a shared budget (docs/rag_it_all.md:719, docs/rag_it_all.md:1477).
* **Backtracking and reflection.** These fit the plan only if they count against its cap on retrieval invocations (docs/rag_it_all.md:812).
* **Keeping low-level identifiers**, and never deduplicating by name alone across the whole corpus (docs/rag_it_all.md:136).

### What we would get

Better localisation in long manuals and runbooks, where the heading tree says more than chunk similarity does. The costs: the paper's evidence is an internal telecom evaluation with LLM-judged outcomes and uneven benefit from deeper backtracking (docs/rag_it_all.md:136), and reflection adds model calls.

## 16. Re2G: Retrieve, Rerank, Generate

* **Authors:** Michael Glass, Gaetano Rossiello, Md Faisal Mahbub Chowdhury, Ankita Rajaram Naik, Pengshan Cai, Alfio Gliozzo
* **Year:** 2022 (NAACL 2022)
* **arXiv:** [2207.06300](https://arxiv.org/abs/2207.06300). Version read: v1 (13 Jul 2022), abstract. This is the only version.

### Why it is included

Re2G builds neural retrieval and reranking into a BART-based generator, and trains all three parts end to end by knowledge distillation from the target sequences alone. The plan adds reranking after the lexical, dense and graph candidates are combined, using an adapter at inference time with no end-to-end training (docs/rag_it_all.md:122, docs/rag_it_all.md:774). hippo has no passage reranker today:

* The reference step named `rerank_facts` is actually the LLM recognition filter over five facts (src/hippo/hipporag/retriever.py:319-331).
* The code keep/drop/expand pass moves dropped passages down the list without scoring anything (docs/FIDELITY.md:237-246).

### Features implemented

None.

### Possibly new features

* **A pluggable reranker** (cross-encoder or constrained LLM) over at most 40 combined evidence units, falling back to the combined order on failure. An LLM reranker returns candidate ids only, and unknown ids are rejected (docs/rag_it_all.md:774, docs/rag_it_all.md:1494).
* **One scale for candidates from different retrievers.** The plan uses weighted reciprocal rank fusion rather than comparing cosine, BM25 and PPR scores directly (docs/rag_it_all.md:721-724). Re2G's reranker is another way to do this.
* **Distillation training** of retriever and reranker from answer labels. The plan defers this (docs/rag_it_all.md:122).

### What we would get

Higher precision in the passages that reach the answering model, which matters when it reads only five (src/hippo/store/base.py:24). The costs are a reranking model and its latency on every question, plus per-slice evaluation (code, schema, prose) to choose that model (docs/rag_it_all.md:774).

## 17. Late Chunking: Contextual Chunk Embeddings Using Long-Context Embedding Models

* **Authors:** Michael Günther, Isabelle Mohr, Daniel James Williams, Bo Wang, Han Xiao
* **Year:** 2024
* **arXiv:** [2409.04701](https://arxiv.org/abs/2409.04701). Version read: v3 (7 Jul 2025), abstract. Earlier versions: v1 (7 Sep 2024), v2 (2 Oct 2024).

### Why it is included

Late chunking splits text into chunks after the transformer runs and before mean pooling. Each chunk's vector therefore captures "the full contextual information" of its document. hippo chunks first and embeds each passage on its own (src/hippo/hipporag/indexer.py:6, src/hippo/ingest/chunker.py:9-16). To compensate, it adds heading titles and a whole-sentence overlap between neighbouring chunks (src/hippo/ingest/chunker.py:13-15). The plan notes that late chunking needs token-level embedding output, which ordinary Ollama pooled vectors cannot provide (docs/rag_it_all.md:124, docs/rag_it_all.md:847).

### Features implemented

None.

### Possibly new features

* **A late-chunked embedding path** on a runtime that exposes token embeddings. It changes every passage vector, so it amounts to a new embedding profile with a full re-embed. The managed dense session already resolves and checks embedding profiles, so vectors from the two methods would never be mixed (src/hippo/knowledge/dense_session.py:17-25).
* **Invalidating the whole document on any edit.** Each chunk vector depends on its surrounding text (docs/rag_it_all.md:228).

### What we would get

Better dense recall for passages whose meaning depends on earlier text, such as pronouns or context set at the start of a section. The costs are an embedding runtime other than Ollama's pooled endpoint, long-context encoding for every document, and re-embedding a whole document whenever any part of it changes.

## 18. Zep: A Temporal Knowledge Graph Architecture for Agent Memory

* **Authors:** Preston Rasmussen, Pavlo Paliychuk, Travis Beauvais, Jack Ryan, Daniel Chalef
* **Year:** 2025
* **arXiv:** [2501.13956](https://arxiv.org/abs/2501.13956). Version read: v1 (20 Jan 2025), full text (HTML). This is the only version.

### Why it is included

Zep's Graphiti engine uses a bi-temporal model with two timelines:

* **T, the timeline of events.** Each edge records `t_valid` and `t_invalid`.
* **T′, the timeline of ingestion.** Each edge records `t'_created` and `t'_expired`.

Raw "episodes" are kept as a non-lossy store, and episodic edges link every extracted fact back to the episodes it came from. When new information contradicts an overlapping edge, Graphiti invalidates the old edge and "consistently prioritizes new information".

The plan adopts the two time axes and the links from claims to their evidence. It explicitly rejects newest-wins: delayed imports and lower-authority comments must not overwrite current declarations (docs/rag_it_all.md:153). hippo's Task 5A implements this model in the managed knowledge layer (ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md:1-19).

### Features implemented

* **Two independent time axes on every temporal record.** Effective time is `valid_from`/`valid_to` and recorded time is `recorded_from`/`recorded_to`, both half-open intervals. Each record also keeps its validity kind, its precision, and the provider's original timestamp text and time zone (src/hippo/knowledge/model.py:466-487, src/hippo/knowledge/temporal.py:57).
* **Relationship versions linked to evidence.** Each relationship version carries both axes and links to the evidence spans that support it. This is the counterpart of Zep's episodic edges (src/hippo/knowledge/model.py:548-553, src/hippo/knowledge/model.py:576-580, src/hippo/knowledge/model.py:412).
* **Query selectors** for current, as-of, during, changes and atemporal reads, each with an optional knowledge cutoff `known_at` (src/hippo/knowledge/model.py:1221-1266). They are evaluated by pure predicates (src/hippo/knowledge/temporal.py:224-326), and history selection uses them for pinned snapshots (src/hippo/knowledge/temporal.py:530, src/hippo/knowledge/snapshots.py:245-247).
* **Append-only corrections.** Publication may close a version's `recorded_to` exactly once, and appends the corrected historical segments (ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md:18, src/hippo/knowledge/temporal.py:658).
* **Newest-wins deliberately rejected.** Arrival order never proves source order. Only an adapter-declared monotonic order can replace an earlier claim from the same source. Claims from independent sources that disagree are kept side by side in a `ConflictSet` (ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md:15-16, src/hippo/knowledge/conflicts.py:110, src/hippo/knowledge/conflicts.py:163, src/hippo/knowledge/conflicts.py:265-283, src/hippo/knowledge/model.py:1154).
* **Chronological replay** of recorded temporal events into a real store, used to exercise the plan's temporal scenarios (src/hippo/evals/rag_all_temporal.py:1-20).

### Possibly new features

* **Hybrid search over the temporal graph**: BM25, cosine similarity and breadth-first search, reranked by RRF, MMR or a cross-encoder. In hippo these would arrive as Task 13 and Task 14 channels, and temporal eligibility has to apply before every channel (docs/rag_it_all.md:1478, docs/rag_it_all.md:823).
* **LLM contradiction detection** to find the edges a new fact invalidates. Under Task 5A a model's conflict suggestion is a read-only candidate: it cannot close versions or pick winners (ai_docs/plans/rag-it-all-task-5a-temporal-conflicts.md:19).
* **Community detection by label propagation**, extended as new nodes arrive, as an incremental alternative to re-running Leiden (entry 5). The communities are derived views under I13 (docs/rag_it_all.md:228).

### What we would get

Hybrid channels that respect time from the start, and faster conflict triage because a model proposes the candidate conflicts. Incrementally maintained communities would also avoid a full re-partition on every change. The risk is the part of Zep that hippo deliberately does not copy: a model suggestion or a recency rule turning into an authoritative invalidation.

## 19. RAG Meets Temporal Graphs: Time-Sensitive Modeling and Retrieval for Evolving Knowledge (TG-RAG)

* **Authors:** Jiale Han, Austin Cheung, Yubai Wei, Zheng Yu, Xusheng Wang, Bing Zhu, Yi Yang
* **Year:** 2025
* **arXiv:** [2510.13590](https://arxiv.org/abs/2510.13590). Version read: v1 (15 Oct 2025), abstract. This is the only version. The plan calls it TG-RAG (docs/rag_it_all.md:154).

### Why it is included

TG-RAG models knowledge as a two-level temporal graph: timestamped relations plus a hierarchy of time structures. It generates temporal summaries of key events and trends at several granularities, updates incrementally, and retrieves a subgraph that matches the question's temporal and semantic scope. The plan adopts temporal eligibility and the rebuilding of summaries an update affects. It also notes that the paper's evaluation covers corpus growth, not deletions or retroactive corrections (docs/rag_it_all.md:154). hippo's managed layer has the timestamped relations and time-scoped selectors, but no time hierarchy and no temporal summaries.

### Features implemented

* **Timestamped relations.** Every relationship version is a temporal record (src/hippo/knowledge/model.py:548).
* **Time-scoped selection**: as-of instants, and during intervals with an explicit `overlaps` or `throughout` predicate (src/hippo/knowledge/model.py:1229-1240, src/hippo/knowledge/temporal.py:238-275).
* **Precision-aware matching.** A record whose effective time is unknown or imprecise comes back as contextual evidence, not as a proven match (src/hippo/knowledge/temporal.py:238-252).

### Possibly new features

* **A time hierarchy** (for example year, quarter and month groupings) over events. It may use only source-supported times, never dates taken from a model's background knowledge (docs/rag_it_all.md:822).
* **Time-scoped summaries of events and trends**, rebuilt when a covered interval changes. They are derived views under I13 (docs/rag_it_all.md:228) and must also handle retroactive corrections, which the paper does not test (docs/rag_it_all.md:154).
* **Temporal prefiltering inside retrieval**, before candidates are generated, so historical evidence that an unfiltered top-k would miss is still found (docs/rag_it_all.md:823, docs/rag_it_all.md:1478).

### What we would get

Questions like "what changed in the second quarter" or "who owned X in May" answered through the normal retrieval route, at the right time granularity. The costs are summaries per time bucket to generate and invalidate, and every retrieval channel having to apply the same time predicates.

## 20. RepoCoder: Repository-Level Code Completion Through Iterative Retrieval and Generation

* **Authors:** Fengji Zhang, Bei Chen, Yue Zhang, Jacky Keung, Jin Liu, Daoguang Zan, Yi Mao, Jian-Guang Lou, Weizhu Chen
* **Year:** 2023 (EMNLP 2023)
* **arXiv:** [2303.12570](https://arxiv.org/abs/2303.12570). Version read: v3 (20 Oct 2023), abstract. Earlier versions: v1 (22 Mar 2023), v2 (3 Apr 2023).

### Why it is included

RepoCoder combines a similarity-based retriever with a code language model in an iterative retrieval–generation loop for repository-level completion. The plan takes one bounded follow-up retrieval for unresolved symbols and dependencies from it, and never indexes generated code as observed evidence (docs/rag_it_all.md:118). hippo's code-select pass can "expand" a chosen passage to its graph neighbours (src/hippo/hipporag/retriever.py:693, src/hippo/store/base.py:34). Those neighbours are appended at score 0.0 and never cited (docs/FIDELITY.md:244-246). That is a structural expansion, not retrieval driven by generated code.

### Features implemented

None.

### Possibly new features

* **Generate-then-retrieve for code questions**: draft the likely code, then search with the draft. The draft is only a search string, never evidence (docs/rag_it_all.md:118, docs/rag_it_all.md:218).
* **A follow-up retrieval for symbols the first pass could not resolve**, inside the plan's single bounded round (docs/rag_it_all.md:770).

### What we would get

Better recall for code questions worded in terms that don't match the identifiers in the code. The costs are a generation call before retrieval, and the risk that a draft invents names, which must be treated as unresolved.

## 21. GraphCoder: Enhancing Repository-Level Code Completion via Code Context Graph-based Retrieval and Language Model

* **Authors:** Wei Liu, Ailun Yu, Daoguang Zan, Bo Shen, Wei Zhang, Haiyan Zhao, Zhi Jin, Qianxiang Wang
* **Year:** 2024
* **arXiv:** [2406.07003](https://arxiv.org/abs/2406.07003). Version read: v2 (13 Sep 2024), abstract. Earlier version: v1 (11 Jun 2024).

### Why it is included

GraphCoder builds a code context graph whose edges are control flow, data dependence and control dependence between individual statements, and retrieves from it coarse-to-fine. hippo's code graph works at the level of symbols instead: modules, classes, functions and methods, joined by ten relation kinds extracted with tree-sitter (src/hippo/codegraph/model.py:44-57, docs/FIDELITY.md:179-190). The plan states that this symbol graph is not a statement-level context graph and must not be called a reproduction (docs/rag_it_all.md:119, docs/rag_it_all.md:847).

### Features implemented

None.

### Possibly new features

* **Statement-level control- and data-dependence graphs** for very large functions. This needs per-language dataflow analysis for all five supported languages (docs/FIDELITY.md:254-258), and the symbol graph cannot stand in for it (docs/rag_it_all.md:166).
* **Coarse-to-fine retrieval**: find the symbol first, then the statements inside it.

### What we would get

Precise context for questions about the inside of long functions, such as "where is this value set before it is written". The costs are dataflow analysis for each language, much larger graphs, and parser coverage that must be reported wherever it is incomplete (docs/rag_it_all.md:768).

## 22. GraphCodeAgent: Dual Graph-Guided LLM Agent for Retrieval-Augmented Repo-Level Code Generation (v1: CodeRAG)

* **Authors (v2):** Jia Li, Xianjie Shi, Kechi Zhang, Ge Li, Zhi Jin, Lei Li, Huangzhao Zhang, Jia Li, Fang Liu, Yuwei Zhang, Zhengwei Tao, Yihong Dong, Yuqi Zhu, Chongyang Tao
* **Authors (v1):** Jia Li, Xianjie Shi, Kechi Zhang, Lei Li, Ge Li, Zhengwei Tao, Jia Li, Fang Liu, Chongyang Tao, Zhi Jin
* **Year:** 2025
* **arXiv:** [2504.10046](https://arxiv.org/abs/2504.10046). The two versions have different titles:
  * v2 (18 Nov 2025), abstract read: "GraphCodeAgent: Dual Graph-Guided LLM Agent for Retrieval-Augmented Repo-Level Code Generation".
  * v1 (14 Apr 2025), title and authors confirmed: "CodeRAG: Supportive Code Retrieval on Bigraph for Real-World Code Generation".
  
  hippo follows neither version. The plan asks for the version to be pinned when comparing methods (docs/rag_it_all.md:120). This entry describes v2.

### Why it is included

GraphCodeAgent builds a Requirement Graph and a Structural-Semantic Code Graph, and uses both to guide an LLM agent through multi-hop retrieval of code context. The plan uses it for linking observed requirements to implementation evidence, while keeping generated descriptions apart from approved requirements (docs/rag_it_all.md:120).

hippo's closest mechanism is `REFERS_TO`, which links a prose passage to the symbols it names, at most 20 per passage (src/hippo/hipporag/indexer.py:17, src/hippo/hipporag/indexer.py:91, src/hippo/hipporag/indexer.py:462-500). That is a naming link, not a requirement graph. The managed model already declares `requirement`, `criterion`, `ticket` and `decision` object kinds (src/hippo/knowledge/model.py:56-87). The plan's cross-source linking task is what would populate them (docs/rag_it_all.md:1440).

### Features implemented

None.

### Possibly new features

* **Requirement nodes and requirement-to-code links** built from PRDs and tickets. Every link must carry supporting spans, and a mention never counts as an implementation (docs/rag_it_all.md:168).
* **Generated functional descriptions of code**, kept as a separate `model_inferred` view with the model and prompt version recorded (docs/rag_it_all.md:442, src/hippo/knowledge/model.py:46-48).
* **Graph-guided agentic retrieval**, inside the plan's bounded controller (docs/rag_it_all.md:812).

### What we would get

Traceable answers to "which code implements requirement R" and "which requirement does this function serve". The costs are link-extraction quality, the cost of the agent loop, and generated descriptions that go stale on every code change.

## 23. RASL: Retrieval Augmented Schema Linking for Massive Database Text-to-SQL

* **Authors:** Jeffrey Eben, Aitzaz Ahmad, Stephen Lau
* **Year:** 2025
* **arXiv:** [2507.23104](https://arxiv.org/abs/2507.23104). Version read: v1 (30 Jul 2025), abstract. This is the only version.

### Why it is included

RASL breaks database schemas and their metadata into separately indexed semantic units. It identifies tables first, using column-level retrieval to stay within context limits. The plan's schema route follows this shape: separate retrieval views for table and column names, aliases, descriptions and constraints, capped per table, followed by declared foreign-key closure (docs/rag_it_all.md:115, docs/rag_it_all.md:755-757).

What hippo has today:

* It extracts the tables, columns, collections and graph labels that code names in SQL, Mongo and Cypher literals, as data objects with READS and WRITES edges (src/hippo/codegraph/data_access.py:1-6, src/hippo/codegraph/model.py:44-57).
* The managed model declares table, column and constraint "card" view kinds (src/hippo/knowledge/model.py:842-863).

There is no schema retrieval route, and no external DDL is ingested (src/hippo/codegraph/data_access.py:4-6).

### Features implemented

None.

### Possibly new features

* **Separate table, column, description and constraint views**, with a cap per table (docs/rag_it_all.md:755). This needs the DDL and catalog ingestion of Task 7 (docs/rag_it_all.md:1330).
* **Mapping matched columns to their tables, then a bounded foreign-key closure** that never drops one member of a composite key (docs/rag_it_all.md:756-758). Similar names alone never create a foreign key (docs/rag_it_all.md:760).
* **Learned weights for the views**, which need training labels (docs/rag_it_all.md:755).

### What we would get

Answers to "which tables hold X and how do they join" on schemas too large to fit in the context window. The costs: Task 7's DDL and catalog ingestion has to exist first, and schema retrieval does not guarantee that generated SQL will run (docs/rag_it_all.md:762).

## 24. RAGChecker: A Fine-grained Framework for Diagnosing Retrieval-Augmented Generation

* **Authors:** Dongyu Ru, Lin Qiu, Xiangkun Hu, Tianhang Zhang, Peng Shi, Shuaichen Chang, Cheng Jiayang, Cunxiang Wang, Shichao Sun, Huanyu Li, Zizhao Zhang, Binjie Wang, Jiarong Jiang, Tong He, Zhiguo Wang, Pengfei Liu, Yue Zhang, Zheng Zhang
* **Year:** 2024
* **arXiv:** [2408.08067](https://arxiv.org/abs/2408.08067). Version read: v2 (17 Aug 2024), full text. Earlier version: v1 (15 Aug 2024).

### Why it is included

RAGChecker is "based on claim-level entailment checking". It extracts claims from both the response and the ground-truth answer, then checks each claim against the other text and against the retrieved chunks. It scores each side separately:

* **Retriever:** claim recall and chunk-level context precision.
* **Generator:** context utilisation, relevant and irrelevant noise sensitivity, hallucination and self-knowledge.

The plan cites it for scoring evidence retrieval, claim support and answer completeness separately (docs/rag_it_all.md:126, docs/rag_it_all.md:1079). hippo already scores retrieval separately from answers, but it grades each answer as a whole rather than claim by claim.

### Features implemented

None. hippo does score retrieval separately from answers: evidence recall, all-required-set success, MRR and nDCG over exact gold evidence quotes, in a retrieval-only fixture evaluation (src/hippo/evals/metrics.py:117-146, src/hippo/evals/rag_all.py:1-5, src/hippo/evals/rag_all.py:211-213). It grades answers as a whole, by exact match and F1 plus a three-way LLM verdict (src/hippo/evals/judge.py:1-14). Neither step extracts claims or checks entailment, and that is the paper's mechanism.

### Possibly new features

* **Claim extraction and entailment.** Claims would be extracted from each answer and checked against the retrieved evidence, giving claim support precision, context utilisation, noise sensitivity and hallucination rates. The plan already lists claim support precision and valid citation rate among its generation metrics (docs/rag_it_all.md:1079). LLM judgments need a pinned prompt and model plus a human-reviewed sample (docs/rag_it_all.md:1100).
* **Chunk-level context precision** as a retrieval diagnostic next to evidence recall.

### What we would get

A way to tell whether a bad answer came from retrieval missing evidence, or from the generator ignoring or misusing evidence it was given. That is the question an evidence-first design most needs answered. The costs are an entailment model or LLM calls for every claim, and calibrating the judge against human review.

## Considered and not included

The papers below are cited in docs/rag_it_all.md. Each arXiv id was fetched and confirmed on 2026-09-13, like the ones above. None of them gets its own entry, for one of these reasons:

* nothing in hippo implements it or has a code touchpoint for it;
* it is cited only as an evaluation caveat, a benchmark, or a switched-off experiment;
* an included paper already carries the mechanism.

| Paper | arXiv id (latest version) | Reason |
| --- | --- | --- |
| CRUSH4SQL: Collective Retrieval Using Schema Hallucination For Text2SQL | [2311.01173](https://arxiv.org/abs/2311.01173) (v1) | The schema route is not built. Hypothetical schema terms appear only in a switched-off search-hint experiment (docs/rag_it_all.md:113, docs/rag_it_all.md:845). RASL (entry 23) carries the schema retrieval mechanism. |
| CHESS: Contextual Harnessing for Efficient SQL Synthesis | [2405.16755](https://arxiv.org/abs/2405.16755) (v3) | Its value retrieval and SQL execution workflow go beyond the DDL-only scope (docs/rag_it_all.md:114). |
| CRED-SQL: Enhancing Real-world Large Scale Database Text-to-SQL Parsing through Cluster Retrieval and Execution Description | [2508.12769](https://arxiv.org/abs/2508.12769) (v3) | Only a switched-off attribute-discrimination comparison, with no code touchpoint (docs/rag_it_all.md:116, docs/rag_it_all.md:845). |
| Spider 2.0: Evaluating Language Models on Real-World Enterprise Text-to-SQL Workflows | [2411.07763](https://arxiv.org/abs/2411.07763) (v2) | An SQL workflow benchmark. hippo measures evidence retrieval, not SQL accuracy (docs/rag_it_all.md:117). |
| CodeRAG-Bench: Can Retrieval Augment Code Generation? | [2406.14497](https://arxiv.org/abs/2406.14497) (v2) | A benchmark that no hippo evaluation uses (docs/rag_it_all.md:121). |
| BRIGHT: A Realistic and Challenging Benchmark for Reasoning-Intensive Retrieval | [2407.12883](https://arxiv.org/abs/2407.12883) (v4) | A benchmark. The plan says public results do not replace an enterprise gold set (docs/rag_it_all.md:127). |
| Beyond Chunk-Then-Embed: A Comprehensive Taxonomy and Evaluation of Document Chunking Strategies for Information Retrieval | [2602.16974](https://arxiv.org/abs/2602.16974) (v1) | Argues for measuring chunking on each corpus. It offers no mechanism to adopt (docs/rag_it_all.md:125). |
| PAR²-RAG: Planned Active Retrieval and Reasoning for Multi-Hop Question Answering | [2603.29085](https://arxiv.org/abs/2603.29085) (v1) | Cited for the bounded evidence-needs ledger, which entry 7 already covers (docs/rag_it_all.md:137). |
| Do We Still Need GraphRAG? Benchmarking RAG and GraphRAG for Agentic Search Systems | [2604.09666](https://arxiv.org/abs/2604.09666) (v1) | An evaluation caveat (ablate backend and controller together), not a mechanism (docs/rag_it_all.md:138). |
| LivingRAG: Augmenting Graph RAG with Experience | [2608.25960](https://arxiv.org/abs/2608.25960) (v1) | The `experience_prior` experiment, which is gated on chronological replay and has no code touchpoint (docs/rag_it_all.md:140, docs/rag_it_all.md:844). |
| Relink: Constructing Query-Driven Evidence Graph On-the-Fly for GraphRAG | [2601.07192](https://arxiv.org/abs/2601.07192) (v1) | The `query_link_repair` experiment, an inference-only adaptation with no code touchpoint (docs/rag_it_all.md:141, docs/rag_it_all.md:842). |
| Think Parallax: Solving Multi-Hop Problems via Multi-View Knowledge-Graph-Based Retrieval-Augmented Generation | [2510.15552](https://arxiv.org/abs/2510.15552) (v4) | Needs learned retrieval heads, deferred until labels exist. Pooled Ollama embeddings cannot reproduce it (docs/rag_it_all.md:142, docs/rag_it_all.md:847). |
| SAG: SQL-Retrieval Augmented Generation with Query-Time Dynamic Hyperedges | [2606.15971](https://arxiv.org/abs/2606.15971) (v2) | The `event_incidence` experiment for ticket and review threads. Those sources belong to connector Tasks 10 and 11 and are not ingested at this commit (docs/rag_it_all.md:145, docs/rag_it_all.md:840, docs/rag_it_all.md:1404, docs/rag_it_all.md:1422). |
| Agentic RAG with Knowledge Graphs for Complex Multi-Hop Reasoning in Real-World Applications | [2507.16507](https://arxiv.org/abs/2507.16507) (v1) | Illustrative scenarios, cited only to motivate the plan's typed read-only tools (docs/rag_it_all.md:146, docs/rag_it_all.md:814). |
| A Triple-Robustness Analysis of Retrieval-Augmented Generation for Multi-Hop Requirements Traceability | [2608.00705](https://arxiv.org/abs/2608.00705) (v1) | An evaluation-design caveat (score stages separately, stratify by artifact and hop count), not a mechanism (docs/rag_it_all.md:147). |

Also left out:

* **HiGraAgent and TimeR⁴.** The plan cites both from the ACL Anthology, and gives no arXiv id for either. For HiGraAgent it says outright that none was verified (docs/rag_it_all.md:144, docs/rag_it_all.md:155).
* **Personalized PageRank and classic Open Information Extraction.** Their original publications are not arXiv papers. hippo's PPR call and OpenIE prompts come to it through HippoRAG and HippoRAG 2 (entries 1 and 2).
* **DSPy.** hippo reuses only the text of the reference's compiled filter prompt, not the framework (docs/FIDELITY.md:97-105).
* **MemGPT, Mem0, A-MEM, ColBERT, HyDE, Self-RAG, CodeBERT, GraphCodeBERT and SWE-bench.** None is cited anywhere in the repository, and no hippo module or design section applies them.
* **"LARGER".** The plan lists this reference as unresolved (docs/rag_it_all.md:99).

## Summary of what adopting the rest would buy

### Retrieval quality

This is the largest group. Two of its ideas already appear in the plan as Task 13 and 14 steps (docs/rag_it_all.md:1477, docs/rag_it_all.md:1494):

* a reranker (Re2G);
* a heading hierarchy channel (RAPTOR, VDGR-RAG).

Between them they address the two weak points of the single legacy route: precision in a context that holds only five passages, and evidence spread across long sections.

Several graph ideas each promise better multi-hop or broad-question recall:

* G-Retriever's connected packing;
* CatRAG's query-local weights;
* HGRAG's incidence diffusion;
* NodeRAG's remaining node roles;
* the thematic routes of GraphRAG and LightRAG.

Each adds a ranking to evaluate at equal budgets. Where they generate text, they also add derived views that must be invalidated.

The last three trade something else for recall. Iterative retrieval (IRCoT) costs model calls. Trained or approximate dense retrieval (DPR) costs training data or disclosed approximation. Late chunking needs a different embedding runtime.

### Memory and temporal

hippo already has the hard part the temporal papers leave open: two time axes, append-only corrections, and conflict sets that never let the newest ingestion win. What remains:

* make retrieval itself time-aware, with TG-RAG's scope-aligned retrieval and temporal eligibility before every channel;
* add time-scoped summaries;
* borrow Zep's hybrid search, with its contradiction detection allowed only as read-only suggestions.

The benefit is historical and "what changed" questions answered through the normal route. The risk is a channel, summary or model suggestion bypassing the deterministic temporal rules.

### Code understanding

hippo's symbol graph, typed relations and path tools already cover call paths, blast radius, exception routes and history. The remaining papers push in three directions:

* **Finer granularity:** GraphCoder's statement-level dependence.
* **Wider linkage:** GraphCodeAgent's requirement graph and RASL's schema retrieval.
* **Generation-assisted retrieval:** RepoCoder.

Running Leiden in the managed projection would also make subsystem labels agree across both paths. Each direction needs new extraction work (dataflow analysis per language, DDL ingestion, requirement linking), and each must keep parser facts, declarations and model inferences distinguishable.

### Evaluation

Retrieval is already scored separately from answers, over exact gold quotes. Two additions would help:

* **Claim-level diagnostics (RAGChecker)** would show whether a wrong answer is a retrieval failure or a generation failure.
* **HippoRAG 2's public datasets as a legacy slice** would show the port still reproduces the reference.

A second reviewed answer per gold question (the SQuAD protocol) would calibrate both the metrics and the judge. The costs are LLM or entailment calls per claim, human review for calibration, and more suites to keep green.
