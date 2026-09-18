# Brief: the arXiv bibliography that applies to hippo

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree (`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message; you create ONE new document and edit nothing else. No worktree is needed (no code, no tests).

GOAL: `docs/research/arxiv-bibliography.md` documents every arXiv paper that applies to this project, so a reader can see, per paper, why it matters here, which of its ideas hippo has already implemented (with file pointers), which it has not, and what adopting the rest would buy. Requested by the project owner on 2026-09-13.

CONTEXT: hippo is a HippoRAG-style knowledge graph retrieval system (OpenIE triples, entity/passage graph, PPR-style structural retrieval, dense retrieval sessions, managed generations with exact evidence, temporal facts, and code-graph capture of repositories). Start from what the repository already cites: `README.md`, `docs/rag_it_all.md`, `docs/rag_it_all_remaining_tasks.md`, `docs/CONTRACTS.md`, `docs/FIDELITY.md`, `docs/design/*.md`, `docs/plans/hippo-for-code/**` (its `research/` folder cites retrieval papers), `ai_docs/plans/*.md`, and `rg -i "arxiv|et al\.|hipporag|graphrag|lightrag|raptor|colbert|openie|personalized pagerank|ppr|rerank|hyde|self-rag|memgpt|mem0|zep|a-mem|temporal knowledge graph|code graph|codebert|graphcodebert|repocoder|swe-bench"` over `docs/`, `ai_docs/`, `src/` and `evals/`. Then add the obvious adjacent papers the code clearly draws on even where it does not cite them (the HippoRAG and HippoRAG 2 papers, OpenIE, PPR, GraphRAG, LightRAG, RAPTOR, dense/hybrid retrieval and reranking, temporal KG and memory papers, and code-graph / repository-level retrieval papers), each only if you can point at the hippo module or design section it applies to.

REQUIRED CONTENT, one section per paper, in this order of fields:
1. Title, authors, year, arXiv id as a link (`https://arxiv.org/abs/<id>`), and the version you read. Verify every id by fetching the abstract page; never cite from memory alone. If two candidates exist (e.g. HippoRAG v1 vs the NeurIPS revision), cite the one whose method hippo follows and mention the other.
2. "Why it is included": two to five sentences on the specific mechanism and where it touches hippo (`src/hippo/<module>` or a design/plan document), or "why it should be included" if hippo does not draw on it yet.
3. "Features implemented": a bulleted list of the paper's ideas hippo has actually implemented or deliberately adapted, each with a file or doc pointer you verified by reading the code (`src/hippo/hipporag/*`, `src/hippo/knowledge/*`, `src/hippo/ingest/*`, `src/hippo/codegraph/*`, `src/hippo/retrieval*`, `evals/*`). Say "none" when nothing is implemented. Do not invent an implementation from a name resemblance.
4. "Possibly new features": the paper's ideas hippo has not taken, each with one line on what it would change here and any conflict with a standing project rule (exact evidence, no silent truncation, LadybugDB as primary backend, managed generations, temporal correctness).
5. "What we would get": two or three sentences on the concrete benefit (retrieval quality, cost, latency, provenance, maintainability) and the cost or risk, stated qualitatively. No time-based estimates, no priorities by time.

Also produce, at the top: a short index table (paper, arXiv id, status = implemented / partially / not yet), and at the bottom: a "Summary of what adopting the rest would buy" section grouping the not-yet items by theme (retrieval quality, memory/temporal, code understanding, evaluation), two or three sentences per theme.

CONSTRAINTS: aim for the papers that genuinely apply (likely 12 to 25), not a survey; every claim about hippo must be verified against the code or docs at HEAD, and cite the pointer; every arXiv id must be fetched and confirmed; do not edit any existing file; do not touch `data/`, `.rag-dev-data/`, the dev server on port 8011 or Ollama; run `.venv/bin/ruff format --check docs/research/arxiv-bibliography.md` before finishing (the CI Ruff job formats fenced Python in Markdown; avoid fenced Python unless needed). No commits: the orchestrator commits.

FILES:
  - own: NEW `docs/research/arxiv-bibliography.md` (create the `docs/research/` directory).
  - do NOT touch: anything else.

DONE WHEN: the document exists with the index table, every paper section in the required shape, the closing summary, all ids verified, ruff format clean; `horch done` lists the paper count, the implemented/partial/not-yet counts, and any paper you considered and excluded with the reason.

REPORT: `horch note` after the citation inventory and after each ~5 papers; `horch tell orchestrator "[<role>] BLOCKED: ..."` only if web access is unavailable.
