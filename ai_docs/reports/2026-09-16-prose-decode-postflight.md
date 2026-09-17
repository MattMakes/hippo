# Exact-content prose decoding: post-flight

Verdict: CLEAR for this performance slice. The overall response-time and answer-quality goal remains active.

G1 and G2 were independently run by the orchestrator against the current source: 19 focused cache tests and 101 existing evidence/snapshot tests passed on Ladybug. The finishing worker also ran fake: 18 passed/1 physical-backend skip, then 101 passed. Ruff, compileall and whitespace checks passed. A separate Codex reviewer inspected the actual diff and contracts and found no specification or code-quality issue.

G3 was completed through direct `ask()` against a fresh copy of the captured database and existing local models. Parent-owned process 92350 exited 0. Q3 took 120.311612 seconds versus 298.610555 seconds after the previous optimization, a 59.71% reduction. Main SQL and proof counts remain 230646 and 304. The complete answer object, ranked passages, seeds, facts, graph paths, history, settings and evidence fingerprint compare exactly. The answer still has the baseline completeness defect; no quality improvement is claimed from this cache.

Wiring and behavior match the plan: storage reads remain fresh; cache hits require the complete raw content; invalid, absent and oversized rows take the appropriate existing path; only deeply immutable prose models are reused; store-local locking and entry/byte bounds are present. No API, schema, dependency, model, configuration, credential or authorization policy changed. The real in-process replay verifies the production path; focused tests exercise corruption and deletion failures.

The broader fake suite from the recovered session verified the preceding proof-read slice, not this newer cache. A broad suite on the final combined candidate remains part of overall completion. No Neo4j parity or full security audit is claimed here. The installed security-sweep package was previously found incomplete; this slice instead has focused independent boundary review and existing access/lifetime regression coverage.

Lesson: preserve the number and placement of live evidence checks while making identical immutable parsing cheaper. Warm-proof profiling now shows 726 SQL calls and roughly 0.43 seconds per proof, so repeated storage operations and validation composition are the next measured targets. Do not interpret a single query speedup as corpus-wide evidence; all twelve original cases and supplemental checks remain outstanding.
