# Exact-content prose decoding measurements

## Outcome

The isolated Q3 replay completed in **120.311612 seconds**, down from the
record-cache result of **298.610555 seconds**: **59.7095% lower latency** and a
**2.48198x speedup**. The complete answer object was byte-for-byte equivalent as
decoded JSON, including answer, thought, raw response, context, citation passage
IDs, and retrieval passage IDs. All checked stable trace fields were exactly
equal. Only the expected ephemeral `snapshot_ids` and `timing_ms` differed.

The main thread performed exactly **230,646 SQL calls** and **304 proof builds**
in both runs. The decoder optimization therefore improves CPU work without
removing current storage reads or proof boundaries.

## Environment and method

- Measurement start: 2026-09-17T03:37:33Z; completion: 2026-09-17T03:43:52Z.
- Branch and HEAD: `rag-it-all-tibs`, `1ff6a3788e341a5682b6d065447bc88d572b0f41`.
- Source SHA-256: `knowledge.py` `488f5076f03d5fa782dd45eaf7888e0e183e737664cf93b5e28242f0c217a542`;
  decoder tests `d002a681a91f03f37807e925d3693acde51462d31ff4e9eaf99fbc9903efa621`.
- Source diff SHA-256: `862c4a5920200247bc12f12244821ba1d6224e5d08ee821d44fe192b7fbcc443`.
- Python 3.12.11, `real_ladybug` 0.15.3, Ladybug backend, 512 MiB replay
  buffer pool, `qwen3:8b`, `nomic-embed-text`, context window 8192.
- The orchestrator's permission-enabled process snapshot found no live pytest,
  replay, proof/query profile, selector probe, or model-request process. Existing
  application services remained running but idle; they were not restarted or
  reconfigured.
- The replay copied the original corpus into a new directory. It did not ingest
  sources or modify the original corpus, production data, or model settings.

Replay command:

```text
.venv/bin/python /private/tmp/hippo-speed-round1-FfTJFE/replay.py \
  --output /private/tmp/hippo-decode-measure-BPYYk2/replay-q3-escalated \
  --ids Q3
```

The first sandboxed invocation used the separate `replay-q3` directory and was
preserved after localhost access failed at `GET /api/tags` with `Operation not
permitted`. It produced no answer and was never reused. The command above was
then run once with the required local-socket permission and exited zero.

## Replay results and exact comparison

| Measure | Record cache | Decoder cache |
|---|---:|---:|
| Wall time | 298.610555 s | 120.311612 s |
| Main-thread SQL | 230,646 | 230,646 |
| Main-thread proof builds | 304 | 304 |
| HTTP calls | 29 | 29 |
| HTTP elapsed | 7.142946 s | 9.876763 s |

The new run's HTTP time comprised 3 chat calls in 9.524306 seconds, 2 embedding
calls in 0.305145 seconds, 2 model-metadata calls in 0.003962 seconds, and 22
model-list calls in 0.043349 seconds. Model HTTP was slower than in the prior
run, so it does not explain the wall-time improvement.

Exact equality passed for the full answer object and these stable trace
components: passages; entity, passage, and symbol seeds; paths; tests; history;
evidence fingerprint; fact candidates; top nodes; settings; expansions; filter;
selection; code-seed and fallback flags; fallback reason; question partitions;
and graph version. The explicit comparison listed every trace difference:
`snapshot_ids` and `timing_ms` only.

For historical scale, the original instrumented result was 415.103487 seconds,
making this run 71.0% lower. That is not an isolated controlled comparator: the
original run overlapped focused pytest work, whereas the present replay did not.
The earlier uninstrumented baseline was 388.861 seconds. The controlled claim in
this report is therefore the comparison with the saved 298.610555-second
record-cache replay, plus deterministic equality and unchanged main-thread
counts.

## Cold and warm proof profile

One fresh copied store was opened once. A cold evidence build was immediately
followed by a warm build in that same store; every build retained its 726 SQL
calls. No application monkeypatch changed behavior. The scratch profiler only
counted `LadybugStore.run` calls and captured cProfile data.

| Measure | Cold | Warm |
|---|---:|---:|
| Wall time | 0.964455 s | 0.429614 s |
| Profiled CPU time | 0.974 s | 0.435 s |
| Function calls | 4,764,731 | 718,506 |
| SQL calls | 726 | 726 |
| Decoder-cache entries | 12 | 12 |
| Serialized cache-key bytes | 4,709,741 | 4,709,741 |

Cold cumulative costs were `_knowledge_records` 0.669 seconds,
`_decode_knowledge_record` 0.651 seconds, Pydantic JSON validation 0.467 seconds,
prose payload binding 0.301 seconds, vector validation 0.185 seconds, and prepared
statements 0.100 seconds. Warm cumulative costs fell to 0.143, 0.126, 0.065,
zero in the top 20, zero in the top 20, and 0.093 seconds respectively. The
cache-key helper itself cost 0.014 seconds warm. Full top-20 cumulative and
self-time tables are retained with both pstats files.

The 4,709,741-byte figure counts serialized keys only, not decoded models or
Python object overhead.

## Remaining bottlenecks

The warm proof still takes about 0.43 seconds and Q3 still builds 304 proofs.
Those builds retain 230,646 main-thread SQL calls, about 726 per isolated proof.
Warm `_knowledge_records` remains the largest named cumulative Python cost at
0.143 seconds because 1,915 non-prose records still take the ordinary decode
path. Prepared-statement construction costs 0.093 seconds per warm proof, and
canonical JSON plus validation of non-prose records remains material. Repeating
fresh proof storage reads and non-prose decoding now dominates more clearly than
prose payload/vector binding.

The Q3 trace records 14.633 seconds in embedding, 20.574 seconds in filtering,
and 62.296 seconds total, while complete wall time was 120.312 seconds. The gap
and the isolated warm profile are consistent with substantial proof/storage work
outside model HTTP time. Authorization caching or removal of fresh reads was not
tested and is not implied by these results.

## Artifacts and limits

All private artifacts are under `/private/tmp/hippo-decode-measure-BPYYk2`:

- successful replay: `replay-q3-escalated/results.json`, `replay-escalated.log`,
  and `replay-escalated.exit`;
- exact sanitized comparison: `comparison-summary.json` and `comparison.exit`;
- valid profiles: `proof-profile-2/cold.pstats`, `warm.pstats`, `summary.json`,
  and four top-20 text tables;
- environment evidence: `source.diff`, `source-diff.sha256`,
  `preflight-process-check.txt`, and `post-process-lsof.txt`;
- preserved failed attempts: `replay.log`, `replay.exit`, `replay-q3/`,
  `profile.log`, `profile.exit`, and `proof-profile/cold.pstats`.

The first profile attempt completed a cold build but failed while rendering its
table because `pstats.Stats` rejected a `Path`; it is excluded. The corrected
profile used a new copied store and fresh output directory. These are single
replays/profiles, not statistical samples. No all-12 replay, source ingestion,
Neo4j run, authorization-cache experiment, or application-source change was
performed as part of this measurement.
