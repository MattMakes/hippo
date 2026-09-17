# Proof read reuse: first measured experiment

## Outcome

Q3 improved from **415.103 seconds to 298.611 seconds** (28.1% less time, 1.39x). Main-thread SQL calls fell from **530,135 to 230,646** (56.5%). All **304 proof builds** remained. This is a useful first improvement, not acceptable final latency.

The comparison asserted exact equality of the answer object (including full context and citation IDs), ranked passages, seeds, paths, tests, history and evidence fingerprint. Both runs returned the baseline's incomplete one-field final answer. The optimization preserves that result; it does not solve answer completeness.

## Method and limits

Same baseline data copied into separate fresh directories; same direct ask(), internal audience, qwen3:8b, nomic-embed-text and 512 MiB Ladybug buffer. The harness counts database statements and proof builds by thread, and records HTTP timings. It does not ingest or modify original notes, repositories or Mongo. No application instrumentation is committed.

Artifacts: `/private/tmp/hippo-speed-round1-FfTJFE/{baseline,record-cache}/results.json`, `replay.py`, `compare.py`. Original baseline: `/private/tmp/hippo-real-eval-YCrJeD`; original diagnostic: `/private/tmp/hippo-rag-research-qxBB5k`.

Single replay per revision, not a statistically controlled benchmark. Baseline overlapped some focused pytest runs; optimized replay had no concurrent test jobs. The earlier uninstrumented Q3 baseline was 388.861s, against which the improvement is 23.2%. SQL reduction is deterministic evidence independent of that timing confound. No full-corpus post-change claim yet.

## Verification

- New tests first failed on repeated reads (6 vs 1), shared-proof reads (6 vs 1), and missing generation mismatch rejection.
- Parent gate re-verification: 7 new tests passed in 8.99s; 94 existing derived-access/storage/snapshot/access tests passed in 50.25s.
- Ruff, compileall and diff whitespace checks passed.
- Independent spec/authorization review: PASS. Independent quality review: no findings at confidence >=80.
- Cross-store inventory injection with identical generation ID is not explicitly rejected; only production injection uses the inventory's own store. No reachable regression found.
- Full fake-store unit suite is running, not yet passed. Neo4j parity has not been run for this slice.
- Security-sweep setup could not complete because its installed package lacks referenced specialist agent definitions. See `ai_docs/security-sweep/runs/2026-09-17T03-05-31Z/INCOMPLETE.md`. Focused independent authorization review is not a full security audit.

## Remaining bottleneck

A standalone proof CPU profile after the change made 8,803,421 calls in 1.476 profiled seconds. Record deserialization/validation dominated: `_knowledge_records` 1.174s cumulative, Pydantic JSON validation 0.866s, ProseExtraction payload binding 0.593s, canonical JSON 0.616s (nested times overlap). 24 prose payload binds and 1,152 vector validations appear for one proof. Raw data/profile is at `/private/tmp/hippo-speed-round1-FfTJFE/proof-profile/proof.pstats`.

Next candidates: reuse already-loaded raw proof records for lineage validation; or bounded exact-content deserialization caching while still fetching current storage rows at every boundary. Both require new red/green mutation and cache-lifetime tests. Do not cache authorization verdicts by epoch alone. Then repair compact selector IDs and answer completeness, and rerun all 12 questions plus held-out cases.

## Post-flight status

G1/G2/G3 met for this bounded slice. Runtime equivalence verified in-process. Wiring, contracts, error checks, credentials and configuration unchanged. Full-suite verification remains pending; overall response-time/100%-evaluation-quality goal remains active. No full post-flight clearance or goal completion is claimed.
