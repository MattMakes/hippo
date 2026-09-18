# Performance improvements: final analysis

## Outcome

The retained implementation reduced the original 12 queries' summed durations from **4,245.602 seconds to 793.271 seconds**: an **81.315% reduction**, or **5.352x faster**. Median query duration fell from **327.079 seconds to 61.333 seconds** (81.248%, 5.333x). The 18 fixed cases' summed query durations were 1,189.347 seconds.

Final answer quality is **16/18 under the revised user acceptance**: the original set passed 11/12 and the supplemental set passed 5/6. One answer omitted a requested enumeration and one substituted a character in an exact Unicode value. This is an accepted bounded result, not 100% accuracy or a universal quality claim. See the [final measurements](2026-09-17-final-performance-measurements.md) and [independent quality review](2026-09-16-qa-profile-final-quality-review.md).

The optional grounded QA profile is enabled explicitly with:

```sh
HIPPO_QA_MODEL=qwen3.8:latest
```

Leaving `HIPPO_QA_MODEL` unset preserves the legacy answer protocol. The explicit profile uses the installed 27.3B QA model only for the final answer; the base 8B and embedding roles remain unchanged. It costs more model memory and final-answer time than inheriting the base model, and the default path was not assigned a new quality result.

## Why query time improved

The initial profile showed that repeated evidence-proof storage and decoding work, rather than PageRank or model HTTP, dominated the measured query. The retained changes reuse work only inside narrowly defined lifetimes: one generation, an exact immutable row, or one proof. They do not reuse authorization decisions. Fresh proof construction, live membership checks, revocation checks, original-evidence resolution, and result-release validation remain in place.

The final aggregate combines those storage improvements with later retrieval and answer-generation changes, so it cannot be attributed to one cache, one paper, or one model choice. The cross-run comparison also changes the final QA model. Component measurements establish each mechanism; the final run establishes the retained system result.

## Retained changes

| Slice | What, why, and mechanism | Measured impact | Origin |
| --- | --- | --- | --- |
| [Generation-local derivation inventory](2026-09-16-proof-performance-results.md) (`6a5e1e6`) | A proof revisited the same lineage records for several derived views. One short-lived inventory reuses those records within a generation while checking exact membership on every access. | Q3 fell from 415.103 to 298.611 seconds; main-thread SQL fell from 530,135 to 230,646 with 304 proofs and stable answer/evidence. The first timing overlapped tests, so the SQL reduction is stronger evidence than the elapsed comparison. | Local profiling and repository contracts. |
| [Exact immutable prose decode](2026-09-16-prose-decode-measurements.md) (`4c22322`) | Freshly read, unchanged prose rows were repeatedly parsed. A bounded per-store cache keyed by the complete raw row reuses only the immutable decoded value; changed, malformed, missing, or oversized rows cannot hit it. | Isolated Q3 fell from 298.610555 to 120.311612 seconds, **59.7095% lower**, with the exact full answer and 21 stable trace fields equal; only `timing_ms` and `snapshot_ids` differ. SQL/proof counts were unchanged. | Local profiling and exact-content memoization. |
| [Proof-local raw reader](2026-09-16-proof-inventory-measurements.md) (`51e1525`) | A proof re-read records already fetched for its inventory. Reusing the same store-bound reader removes duplication only within that proof; each later proof gets a fresh reader. | SQL fell from 726 to 320; warm median fell from 338.153 to 201.975 ms (**40.27%**); all eight canonical proofs were equal. | Local profiling and explicit proof lifetime. |
| [Compact selector IDs](2026-09-16-compact-selector-implementation.md) (`18233aa`) | Long passage identifiers could consume the selector's entire response budget. Each request now exposes decimal labels and maps them back only through its exact authorized candidates ([retriever.py](../../src/hippo/hipporag/retriever.py#L235)). | Five production probes stopped normally in 47–49 tokens with exact authorized membership; the earlier Q3 selector had truncated at 512 tokens. | Local protocol diagnosis; no direct paper origin. |
| [Bounded original code evidence](2026-09-16-answer-evidence-implementation.md) | Ranked context could contain a relevant entry point but omit required helper or initializer bodies. A deterministic typed walk adds whole original-evidence groups, limited to two call hops, 64 visited symbols, 10 supplemental originals, and 6,000 novel original characters ([answer_context.py](../../src/hippo/hipporag/answer_context.py#L11)). Existing resolution and authorization remain authoritative ([ask.py](../../src/hippo/ask.py#L136)). | Focused tests and independent review cover bounds, fan-out, cycles, whole-group budgets, citations, and authorization. The final fixed evaluation passes Q3; the interim contrary finding was retracted after applying the frozen semantic scope. | Local implementation, broadly motivated by economical multi-hop retrieval. |
| [Explicit grounded QA profile](2026-09-16-dedicated-qa-implementation.md) | Source coverage did not guarantee that every requested comparison, ordered step, or evidence limitation appeared in the public answer. The opt-in profile makes one direct call with two messages, `think=false`, temperature 0, and a 4,096-token limit, and rejects abnormal, truncated, or empty finals ([answerer.py](../../src/hippo/hipporag/answerer.py#L52), [ollama.py](../../src/hippo/ollama.py#L203)). | The retained full run completed all 18 cases and passed 16. Final-QA HTTP time was 94.442 seconds in total. The profile is configured locally through `HIPPO_QA_MODEL` ([config.py](../../src/hippo/config.py#L126)). | Local quality experiments and fixed source-backed criteria; no direct paper origin. |

These percentages have different comparators and must not be added. Proof latency, selector completion, and QA HTTP time are component measurements; the final query table is the end-to-end `ask()` comparison.

## Relationship to research

[HippoRAG 2 — *From RAG to Memory* (2502.14802)](https://arxiv.org/abs/2502.14802) is the basis of the existing retrieval architecture, including Personalized PageRank, passage integration, and online model use. It is not the source of the three storage optimizations, compact identifiers, or the optional QA profile.

[EfficientRAG (2408.04259)](https://arxiv.org/abs/2408.04259) provides broad motivation for gathering multi-hop evidence without an LLM call at every hop. Hippo's deterministic walk over existing typed code edges is a local adaptation; it is not a reproduction of EfficientRAG's learned retriever.

[RAGChecker (2408.08067)](https://arxiv.org/abs/2408.08067) is related to the decision to diagnose retrieval and generation separately. This project uses fixed questions, exported authorized sources, and independent review; it does not implement the RAGChecker framework.

[CacheBlend (2405.16444)](https://arxiv.org/abs/2405.16444) operates at a different layer, reusing model KV state during serving. It is not the origin of the application-level inventory or decode caches, and its reported speedups are not estimates for Hippo.

[Self-Refine (2303.17651)](https://arxiv.org/abs/2303.17651) supplied only a broad draft-and-revision principle for rejected bounded experiments. Those experiments repeated omissions or introduced errors. No always-on second-call pipeline was retained. The optional QA choice and its prompt are local experiments. The Qwen3 paper numbered 2505.09388 describes the older 8B family and is not evidence about the `qwen3.8:latest` weights used here.

## Remaining quality misses and proposed follow-up

### Requested names were supplied but omitted

The Q8 evidence contained the requested group members, but the final answer did not enumerate them. A generic instruction about named groups did not reliably repair this: a later QA-only diagnostic still omitted them and regressed other details. A 27B review call also retained the omission.

**Proposed, not implemented:** represent specifically requested groups as source-grounded structured items and run a bounded coverage check before release. The check should require every requested member that appears in the authorized evidence, without hard-coding benchmark names or emitting unrelated entities. Regression coverage should include exact member preservation, abstention when the source lacks a member, preservation of the other 16 accepted cases, and a fresh whole evaluation.

### Exact accented character was substituted

The S4 source context carries structured text containing JSON Unicode escapes, and the model substituted punctuation for the exact character. A later QA-only diagnostic, observed by the parent, rendered the accent correctly but still omitted the requested names; it added 101.085514 seconds across 18 revisions. This limited observation is neither a full independent semantic grade nor a retained two-call feature, and it does not prove a general fix.

**Proposed, not implemented:** decode structured JSON fields with a schema-aware path before prompt display, or deterministically copy exact structured values while keeping the original evidence and citation as authority. Do not apply `unicode_escape` blindly to arbitrary text. Tests should cover NFC and NFD, escaped Unicode, literal backslashes, non-Latin scripts, punctuation, and exact value/citation preservation, followed by a fresh whole evaluation. The single corrected diagnostic does not justify an always-on second call.

## Rejected approaches and evidence limits

Prompt-only variants, native-thinking trials, alternate sampling, larger-model direct answers, earlier failed binding variants, explicit-item instructions, and bounded revision passes each fixed some omissions but either left others, introduced unsupported claims, or regressed previously correct answers. The final profile retains its M binding prompt and the best bounded single-call result rather than presenting any rejected variant as a guaranteed remedy.

The performance result is one before/after capture on one fixed developmental corpus: 12 comparable original cases plus six candidate-only supplemental cases. There were no repeated timing trials or error bars. Baseline queries used the base 8B answer role; the retained run used the 27.3B QA role while keeping the base 8B and embedding model unchanged. Candidate identities and digests were pinned, but the baseline did not capture installed-model digests. No service, production environment, model installation, corpus, Neo4j deployment, or full production topology changed for this evaluation.

All 5,607 final collected unit cases are accounted for across the full run and focused reruns: 5,572 passed and 35 skipped. This is not a claim that one final full-suite command was green; see the [unit validation report](2026-09-16-dedicated-qa-unit-validation.md). Historical failed reviews remain valid records of rejected candidates, while the measurements and 16/18 decision above supersede stale pending or assigned status in this report.
