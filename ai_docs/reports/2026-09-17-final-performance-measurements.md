# Final retained performance measurements

## Result

The retained system completed all 18 fixed cases. Under the user's revised acceptance, quality is **16/18**: 11/12 original cases and 5/6 supplemental cases passed the independent semantic review. This report measures duration and completion; the [final quality review](2026-09-16-qa-profile-final-quality-review.md) owns the semantic verdict.

For the 12 cases with a baseline, summed query duration fell from **4,245.601865 to 793.270510 seconds**, a reduction of **81.315476%** and a speed ratio of **5.352023x**. Median duration fell from **327.078751 to 61.333367 seconds**, a reduction of **81.248135%** and a speed ratio of **5.332803x**.

## Aggregate measurements

| Scope | Baseline sum (s) | Retained sum (s) | Baseline median (s) | Retained median (s) | Final-QA HTTP sum (s) | Final-QA HTTP median (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original Q1–Q12 | 4,245.601865 | 793.270510 | 327.078751 | 61.333367 | 65.622136 | 4.511493 |
| Supplemental S1–S6 | — | 396.076905 | — | 65.416237 | 28.819378 | 3.378611 |
| All 18 retained | — | 1,189.347415 | — | 61.816695 | 94.441514 | 4.178004 |

`Final-QA HTTP` includes only the one request explicitly classified as final-answer generation for each case. Every retained case had one successful final-QA response with normal stop status and nonempty public content. Other HTTP calls are not relabeled as QA.

## Per-case measurements

| Case | Baseline query (s) | Retained query (s) | Final-QA HTTP (s) |
| --- | ---: | ---: | ---: |
| Q1 | 404.313 | 80.167 | 8.568 |
| Q2 | 388.299 | 68.266 | 3.056 |
| Q3 | 388.861 | 76.715 | 11.074 |
| Q4 | 388.730 | 70.001 | 4.453 |
| Q5 | 326.838 | 60.991 | 4.570 |
| Q6 | 327.036 | 61.405 | 5.277 |
| Q7 | 326.031 | 58.792 | 2.894 |
| Q8 | 326.984 | 59.625 | 3.319 |
| Q9 | 327.122 | 61.262 | 4.593 |
| Q10 | 325.841 | 58.713 | 2.627 |
| Q11 | 390.847 | 77.334 | 11.288 |
| Q12 | 324.701 | 60.000 | 3.903 |
| S1 | — | 70.731 | 4.702 |
| S2 | — | 68.604 | 3.232 |
| S3 | — | 60.953 | 2.613 |
| S4 | — | 62.229 | 2.335 |
| S5 | — | 73.254 | 12.412 |
| S6 | — | 60.307 | 3.525 |

Values in this table are displayed to three decimal places. Aggregate calculations use the raw values, not the displayed rounded values.

## Measurement method and provenance

The baseline harness placed `time.monotonic()` immediately around `ask()` for each query. The retained harness used `time.perf_counter()` around the same call boundary. The numbers are sums and medians of complete per-query durations; they are **not** a single whole-job wall-clock measurement. The authoritative baseline sum is 4,245.601865 seconds from the raw case records, not the earlier erroneous 4,245.345-second inventory sum.

The retained parent process exited successfully. All 18 ordered cases completed, application source remained frozen, configured model identities were stable, and every returned citation identifier resolved in the authorized export. The base model remained 8B and the embedding model remained unchanged. The retained profile used the installed 27.3B model for final QA; its configured identities and installed digests were pinned at the beginning and end of the run. The baseline did not capture installed-model digests.

No service, production environment, model installation, corpus, database configuration, or application source was modified by the measurement run. The raw retained artifacts remain private because they contain corpus material; the sanitized arithmetic source is `/private/tmp/hippo-final-metrics-yQtF2j/profile-m-candidate-metrics.json`.

## Interpretation limits

This is a single cross-run comparison on a fixed 18-case developmental set, with baseline data only for the original 12. There are no repeated trials, confidence intervals, or general benchmark claims. The runs also differ in final QA model role, so the aggregate cannot be attributed solely to the inventory cache, prose decode cache, proof-local reader, selector protocol, evidence walk, or QA profile.

The original 12 baseline timings do not establish a strict baseline quality score. An earlier informal 9/12 observation used the same 8B role but was not graded under the final fixed protocol. Leaving `HIPPO_QA_MODEL` unset still preserves that legacy protocol, but no new quality claim is attached to it.

The retained 16/18 verdict is bounded to these cases. It does not establish universal accuracy or 100% quality, and it does not hide the two known misses: one incomplete requested enumeration and one exact Unicode-character mismatch. Proposed remedies and component evidence are summarized in the [final analysis](2026-09-16-performance-improvements.md).
