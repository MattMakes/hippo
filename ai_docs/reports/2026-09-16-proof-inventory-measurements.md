# Proof inventory reuse: acceptance evidence

The proof-local raw-reader change preserves the complete authorized evidence while reducing repeated storage work. Retain this performance slice. Full answer-quality acceptance remains a separate pending evaluation.

The parent ran `/private/tmp/hippo-proof-ab-luGnJKiC/run_measurement.py` after all observed test/export processes were terminal. It compared exact commit `4c2232266b378c1f9def55bc16c1fdd8aa218ea3`, extracted with `git archive`, against the current source in separate subprocesses with explicit, verified import paths. Each used its own fresh copy of the same captured corpus and a 512 MiB Ladybug buffer. Source hashes remained unchanged during measurement. No model calls, services or production data were involved.

| Measurement | Baseline | Candidate | Reduction |
|---|---:|---:|---:|
| SQL operations per proof, every repetition | 726 | 320 | 55.92% |
| First proof in a new store | 0.648077 s | 0.504514 s | 22.15% |
| Median of three subsequent proofs | 0.338153 s | 0.201975 s | 40.27% |

Baseline warm samples were 0.342476, 0.338153 and 0.331669 seconds; candidate samples were 0.199865, 0.203817 and 0.201975 seconds. These are a small local paired measurement, not a claim about every workload or disk-cold behavior. End-to-end query measurements will be reported with the complete answer evaluation.

All eight full canonical `AuthorizedEvidence` values are exactly identical, including all collection contents, rather than only counts. Common SHA-256: `919befe42ab72412b678ca6e84fe277707fa0bf915297e170cbb6f38c663f948`. The driver exited 0. Private artifacts, imported-source paths, source hashes, SQL counts and complete proof values are preserved under `/private/tmp/hippo-proof-ab-run-74duca14`; the parent command log/exit are under `/private/tmp/hippo-proof-ab-luGnJKiC/parent-run.*`.

Final-source parent G1 passed 15 tests on Ladybug with warnings treated as errors. G2 passed 138 with four expected skips in 218.56 seconds. The implementer separately passed G1 on fake and final fake G2 (142 tests). Independent review passed all source requirements, including complete nonmember dependency enumeration, exact membership before cache lookup, identical-store ownership, constructor validation order, private-secondary-input filtering, and fresh readers on separate proofs. Two minor injected-branch coverage gaps are recorded in the independent review; neither is a source defect. Ruff, compileall and whitespace checks passed in the implementation/review evidence.

The full fake unit suite also passed 5,525 tests with 35 skips. It includes this final proof implementation, but predates the separate answer-context correction; later answer tests are recorded separately. The earlier parent G2 process killed by a 120-second harness timeout is excluded from acceptance and superseded by the successful adequate-timeout run. No Neo4j claim is made.

G1, G2 and G3 are met for proof inventory reuse. The implementation meets its plan and its in-process runtime comparison. The remaining overall task is complete grounded answers across the fixed evaluation set, followed by end-to-end performance reporting and acceptance of the separate selector/answer changes.
