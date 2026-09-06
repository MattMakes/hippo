"""
The HippoRAG part of hippo.

HippoRAG (Gutiérrez et al., NeurIPS '24 and ICML '25) is a way to give a
language model long-term memory that works a bit like the human brain:

* The **neocortex** holds the raw experiences. For us that is the text
  passages you upload.
* The **hippocampus** holds a light-weight *index* of those experiences: the
  names of things and how they relate. For us that is a graph of entities
  (phrase nodes) and facts (triples like `["Radio City", "located in", "India"]`).
* Remembering is **spreading activation**: you think of a few things, and
  activation flows along the links to related memories. For us that is
  Personalized PageRank (PPR) started from the entities in the question.

The modules in this package follow the paper's pipeline, in order:

    text.py         small helpers shared by everything (cleaning, ids, normalising)
    openie.py       step 1: the LLM reads each passage and extracts entities + facts
    indexer.py      step 2: those become nodes and edges in Neo4j (with synonym links)
    graph_index.py  step 3: the graph is loaded into memory so PPR is fast
    retriever.py    step 4: question -> facts -> LLM filter -> PPR -> ranked passages
    answerer.py     step 5: the LLM reads the top passages and answers

Everything is written to match the reference implementation at
https://github.com/OSU-NLP-Group/HippoRAG (HippoRAG 2). Where we had to
adapt something for a small local model, the code says so in a comment.
"""
