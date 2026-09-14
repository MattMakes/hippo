# cc11b evidence: the full-size CD9 LadybugDB run and the final code-capture gate runs

Worker `backend-developer-28`, 2026-09-13. Branch `wp/cc11b`, worktree `.worktrees/cc11b`, base
`14d0a37` on `rag-it-all-tibs` (CC11 merged at `f9537ae`, lbpool at `c4ba26e`, qscope at `14d0a37`).
Brief `ai_docs/handoffs/briefs/cc11b-full-size-cd9.md`.

`GATES.md` is not touched, no checkbox is set and no `EVIDENCE:` line is written. The only file this
slice adds is this one. No harness fix was committed: the committed acceptance test and fixture are
unchanged. The memory attribution runs use two scratch copies of the acceptance test. They are never
committed, and were moved out of the tree to `/tmp/hippo-cc11b-probes/` after the runs.

## Orchestrator rulings taken during this slice (2026-09-13)

| Question | Ruling |
| --- | --- |
| N=8 passed with a 25.6 GiB peak RSS, about 0.51 GiB per accepted file, which projects past the machine at N=48 | Do NOT launch N=48. After N=16, attribute the N=8 memory: (A) one run with the read recorder and the timings knob off (harness retention against production), (B) one with tracemalloc snapshots per phase, top 15 allocation sites diffed across the build and dense phases. Record N=16 as the largest completed size meanwhile. A fix slice follows if the retention is production code |
| Recorder state for B | Off, as in A: the question is production retention, not harness retention. Add a probe pair around a `store.close()` and reopen, so native memory that survives a close shows as RSS `gc.collect()` cannot reduce. Report per phase the RSS delta, the traced delta and the top growth sites |
| N=16 was stopped by the guard while its live footprint was 6.4 GiB and most of its RSS was reclaimable | Keep `unused < 4 GB` as the stop rule. Report `phys_footprint` per phase as the attribution signal; do not guard on it. If a run stalls on swap before the guard trips, stop it by PID and report the phase |
| The driver probe reproduces the retention directly: every parameterised `Connection.execute` retains native memory until the connection closes | Skip B at N=8: the driver-level reproduction is the attribution. Finish the payload-size cases and the N=2 B smoke, and record the result as the finding "native per-statement retention in real_ladybug 0.15.3 `Connection.execute` with parameters, freed only by close", with the per-call numbers. A fix slice, lbconn (connection recycling at safe boundaries in `LadybugStore`), is being briefed; do not attempt it |
| How to record the sizes, since N=16 did not complete | N=8 (50 files) is the largest completed size; N=16 (94 files) the largest attempted, completed through the dense dispatch and stopped by the guard in the refresh build. CD9's EXPECT carries no counts, and its multi-hundred-file clause is marked not yet evidenced pending lbconn |

N=16 did not complete (below), so the first ruling's "record N=16 as the largest completed size" was
not applied; the orchestrator was told at once and confirmed the wording in the last row.

## Environment

- `.venv/bin/python` 3.12.11 in the worktree, real_ladybug 0.15.3, pytest 9.1.1, `mcp==2.1.1` pinned
  as the rules require.
- **Ruff pinned to 0.16.6.** The worktree install resolved 0.16.7; the root venv and the rules name
  0.16.6, and the orchestrator's checker runs CD10 from root, so the worktree was pinned with
  `uv pip install --python .venv/bin/python 'ruff==0.16.6'` before CD10 ran.
- The machine: 18 cores, 128 GiB. The orchestrator's Neo4j parity run and the activation ledger's
  checker ran throughout (two other pytest processes, up to 1.7 GiB RSS), and the load average was
  about 11 when the N=8 step started. Every duration below is wall clock under that contention and
  makes no claim about production time.
- **Memory guard.** Each LadybugDB step ran under `/tmp/hippo-cc11b-ladybug-run.sh` (N=8) or
  `/tmp/hippo-cc11b-ladybug-run2.sh` (later steps). The script starts pytest under `/usr/bin/time -l`
  (whose "maximum resident set size" is the peak RSS reported here), watches only that run's python
  PID (args `.../.worktrees/cc11b/.venv/bin/python .venv/bin/pytest ...`), samples `top`'s PhysMem
  "unused" figure (CC11's guard metric) every 30 s at N=8 and every 10 s afterwards, and sends TERM to
  that one PID if unused memory drops below 4 GB (KILL if it survives one more sample). Each step's
  samples are in `/tmp/hippo-cc11b-ladybug-<step>-guard.log`.
- **Later runs and samplers.** Attribution run A and the B smoke ran under
  `/tmp/hippo-cc11b-ladybug-run3.sh`, which can leave the timings knob unset and otherwise guards the
  same way. `/tmp/hippo-cc11b-footprint.sh` (every 300 s) and `/tmp/hippo-cc11b-footprint2.sh` (every
  60 s or 30 s) run `/usr/bin/footprint` against the pytest PID, read-only.
  `/tmp/hippo-cc11b-swapwatch.sh` and `-swapwatch2.sh` log `vm.swapusage` and pageouts every 30 s and
  alert at 2 GB of swap growth. The first attached to the `/usr/bin/time` wrapper rather than python,
  so its RSS column is the wrapper's. The second's RSS column also shows a 2.7 MB process rather than
  python. Only the system-wide swap figure is meaningful in either log. No swap alert fired: swap use
  grew by 0 MB during run A and fell by 104 MB during the B smoke (`/tmp/hippo-cc11b-swapwatch-a8.log`,
  `-b2.log`).

## LadybugDB step-up (brief item 1)

Every step runs CC11's scenario unmodified on LadybugDB with bare `-W error`,
`HIPPO_CODE_ACCEPTANCE_TIMINGS=/tmp/hippo-cc11b-timings-ladybug-<step>.json` and, below the ledger
size, `HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=<N>`. The pool is the scenario's default, 4 GiB
(`MAX_DEFAULT_BUFFER_POOL_BYTES`), unless a row says otherwise. Peak RSS is `/usr/bin/time -l`'s
"maximum resident set size"; the footprint is its "peak memory footprint".

### Per-size results

| Step | Files per language | Accepted files | Symbols | Passages | Pool | Result | Peak RSS | Peak footprint | Lowest unused memory | Knowledge reads (build threads) | Native reads per batch, max (crash / resume / refresh) | Logs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CC11, for reference (merged tree before qscope) | 2 | 20 | 41 | — | 4 GiB | `2 passed in 455.06s` | 10.2 GiB | — | — | 183,041 | 20 / 18 / 20 | `/tmp/hippo-cc11-ladybug-2.log` |
| N=8 | 8 | 50 | 173 | 179 | 4 GiB | `2 passed in 1615.56s (0:26:55)`, EXIT 0, guard not tripped | 27,510,325,248 B (25.6 GiB) | 16,930,459,520 B (15.8 GiB) | 11.0 GB | 737,385 | 10 / 12 / 12 | `/tmp/hippo-cc11b-ladybug-n8.log`, `-n8-guard.log`, `/tmp/hippo-cc11b-timings-ladybug-n8.json` (with `.progress`) |
| N=16 | 16 | 94 | not recorded | not recorded | 4 GiB | **Stopped by the guard** at 17:17:42, 3.5 min into the refresh build (unused 3,687 MB < 4,096 MB), EXIT 143. Did not complete | 35,555,377,152 B (33.1 GiB) | 17,724,036,648 B (16.5 GiB) | 3.6 GB | not recorded | not recorded | `/tmp/hippo-cc11b-ladybug-n16.log`, `-n16-guard.log`, `/tmp/hippo-cc11b-timings-ladybug-n16.json.progress`, `/tmp/hippo-cc11b-footprint2-n16.log` (60 s), `/tmp/hippo-cc11b-footprint-n16.log` (300 s) |
| N=48, the CD9 line | 48 | 270 | | | | **Not run.** The orchestrator ruled against launching it after N=8 and N=16 (see "Orchestrator rulings") | | | | | | — |

The scenario writes its timings JSON only when it finishes, so the stopped N=16 run has no symbol,
passage or read totals; its `.progress` file carries the phases below. The accepted-file counts come
from `build_code_capture_repository` at each size: 20, 50, 94 and 270 files (2,538, 9,212, 18,430 and
55,478 bytes).

**The largest completed size is N=8 (50 accepted files).** The ledger size, N=48 (270 files), was
not run, and N=16 (94 files) did not complete under the guard.

The first N=16 launch never started pytest: the v2 runner script was not executable (`permission
denied`, no log written). It was relaunched unchanged.

### Phases

Wall-clock seconds from the scenario's recorder. The N=2 column predates qscope, so its projection
and dense dispatch include the query-time whole-table reads qscope removed.

| Phase or build | CC11 N=2 | qscope after, N=8 (`a68ff39`) | cc11b N=8 | cc11b N=16 | cc11b N=48 |
| --- | --- | --- | --- | --- | --- |
| bootstrap that crashes after three batches | 53.3 | 159.9 | 154.6 | 299.6 | not run |
| reopen during staging | 1.1 | 2.7 | 2.6 | 5.5 | |
| resumed bootstrap to publication | 41.6 | 342.6 | 431.7 | 805.3 | |
| reopen after publication | 0.7 | 6.9 | 6.3 | 14.1 | |
| seal validation and checksums | 4.5 | 22.5 | 28.5 | 38.9 | |
| projection, arrows and source row | 39.6 | 69.6 | 90.7 | 121.2 | |
| verified dense dispatch | 163.8 | 244.0 | 363.7 | 469.5 | |
| refresh under the held snapshot | 76.8 | 347.6 | 378.2 | stopped by the guard 207 s in (17:14:15 to 17:17:42) | |
| reopen after refresh | 5.0 | 13.9 | 14.4 | not reached | |
| pytest wall clock | 455.06 | 1,322.46 | 1,615.56 | 2,050.18 to the stop (`time -l` real) | |

**Conditions at N=8.** The step started at 16:14:47 with a load average of about 11. The orchestrator's
two pytest processes ran throughout. This slice's Fake CD lines and the full Fake suite (about 16:22 to
16:37) ran beside the resumed bootstrap, both reopens, the seal, the projection, the dense dispatch
and the start of the refresh. qscope's after-run shared its machine with a second LadybugDB run
instead. The N=8 phases here are slower than qscope's after-run under that load. They are not a
regression claim: the per-kind read counts match (below), and none of these durations is asserted.

**Read counts at N=8.** The build threads made 737,385 knowledge reads. That is qscope's after-run
total (743,987) less its 6,602 whole `KnowledgeObject` reads, which the empty-lookup guard merged in
`a816767` removed; it equals qscope's before-run total. The most frequent kinds, as the recorder labels
them (`kind:scope`): `EvidenceSpan:where` 276,723, `ArtifactRevision:where` 121,024,
`Artifact:where` 67,965, `Generation:where` 54,881, `AccessPolicy:where` 32,804,
`DerivedRecord:where` 25,184, `DerivedDependency:where` 22,892, `MaintenanceJob:where` 19,897. The
whole-table reads are the authorization tables (`Suppression` 9,905, `WorkspaceMembership` 9,903,
`Workspace` 9,903, `AccessPolicy` 6,602, `GroupMembership` 6,602) and 7 of `MaintenanceJob`; none is a
`GENERATION_SIZED` kind, and the scenario's `assert_cd1_bound` passed. Native reads per write batch
stayed at 10, 12 and 12, the same as qscope's N=8 runs and below N=2's 20, 18 and 20. So the
per-batch bound does not grow with the corpus.

### Memory

RSS by phase at N=8, from the guard's 30 s samples (the sample nearest each boundary):

| Point | RSS |
| --- | --- |
| crash bootstrap ended, resume started | 5.4 GiB |
| resumed bootstrap published, reopen after publication | 10.7 GiB |
| projection started, dense dispatch started | 10.7 GiB |
| dense dispatch ended | 13.2 GiB |
| refresh started | 14.2 GiB |
| refresh ended | 24.7 GiB |
| reopen after refresh | 25.6 GiB |

The database directory the N=8 run left behind (`hippo.lbug`) is 96 MB, so file-mapped database pages
cannot account for the RSS. RSS grows during every build and during the dense dispatch, and it does
not come back down between phases. The refresh, which writes the same corpus a second time, added
more (about 10.5 GiB) than the resumed bootstrap (about 5.3 GiB).

Peak RSS per accepted file is about 0.51 GiB at both N=2 (10.2 GiB over 20 files) and N=8 (25.6 GiB
over 50 files). If that held, N=16 (94 files) would need about 48 GiB and N=48 (270 files) about
138 GiB, more than the machine's 128 GiB.

**RSS is not the live-memory signal.** From 16:44, a read-only sampler ran `/usr/bin/footprint` on
the N=16 process, every 300 s at first and every 60 s from 16:56. On macOS, RSS includes pages
libmalloc has freed but not yet returned to the kernel, which the tool reports as "reclaimable".
Those pages come back only under memory pressure. `phys_footprint` is the live figure, and
the orchestrator ruled that it is the one to report per phase. At 16:54:16, for example, RSS was
12.2 GiB and `phys_footprint` 923 MB: `MALLOC_SMALL` held 595 MB dirty and 11 GB reclaimable.

N=16, the maximum of the 60 s samples in each phase (`/tmp/hippo-cc11b-attribution.py footprint
/tmp/hippo-cc11b-footprint2-n16.log`, which assigns a sample to the newest start in the `.progress`
file before it; the 60 s samples begin inside the resumed bootstrap):

| Phase | Samples | Max RSS | Max `phys_footprint` (at) | Max `MALLOC_SMALL` dirty | Max `MALLOC_SMALL` reclaimable | Max `VM_ALLOCATE` dirty (the pool's region) |
| --- | --- | --- | --- | --- | --- | --- |
| resumed bootstrap to publication | 6 | 25.7 GiB | 14.0 GiB (17:01:05) | 14.0 GiB | 11.0 GiB | 0.33 GiB |
| reopen after publication | 1 | 27.8 GiB | 17.0 GiB (17:02:06) | 16.0 GiB | 11.0 GiB | 0.36 GiB |
| projection, arrows and source row | 2 | 27.9 GiB | 1.5 GiB (17:04:08) | 0.8 GiB | 26.0 GiB | 0.40 GiB |
| verified dense dispatch | 9 | 30.7 GiB | 4.3 GiB (17:13:15) | 3.6 GiB | 26.0 GiB | 0.42 GiB |
| refresh under the held snapshot, to the stop | 4 | 32.7 GiB | 6.4 GiB (17:17:18) | 5.6 GiB | 26.0 GiB | 0.42 GiB |

What the samples show:

1. **Live memory grows during a build, in small malloc allocations.** In the resumed bootstrap the
   dirty `MALLOC_SMALL` rose about 2 GB a minute (3.1 GB at 16:56:01, 5.3 GB at 16:57:02, 9.4 GiB by
   16:59, 14.0 GiB at 17:01:05) to 16.0 GiB at the reopen after publication.
2. **Closing the store releases it.** The reopen after publication closes the `LadybugStore` and opens
   a new one on the same path. Across it the dirty `MALLOC_SMALL` fell from 16.0 GiB to 0.8 GiB and
   the reclaimable pages rose from 11 GiB to 26 GiB: about 15 GiB of live memory was held by the open
   store, either inside real_ladybug or in Python objects the store held. The driver probe below
   separates the two: it is real_ladybug.
3. **The buffer pool is not where it goes.** The pool's `VM_ALLOCATE` region stayed below 0.5 GiB
   dirty against the 4 GiB pool, and the N=8 database directory is 96 MB.
4. **The guard stopped N=16 on reclaimable pages.** At the stop the process's live footprint was
   6.4 GiB, but about 26 GiB of its 33.1 GiB RSS was reclaimable. Those pages still count against
   `top`'s "unused" figure, which is the guard's stop rule. The orchestrator kept that rule.

### Attribution: native per-statement retention in real_ladybug 0.15.3 `Connection.execute` with parameters

The footprint samples placed the growth in live small allocations held by the open store. A driver
probe outside pytest finds where. Every case below runs in its own fresh process
(`/tmp/hippo-cc11b-probes/ladybug_retention_case.py <case>`, never committed): a bare real_ladybug
database with a 256 MiB pool and, where a case reads rows, a 2,000-row `Item` table. Each case makes
2,000 warm-up calls and then the measured calls. The growth is `/usr/bin/footprint`'s `phys_footprint`
across the measured calls, after `gc.collect()`. "Freed by closing" is the drop in `phys_footprint`
when the connection closes while the database stays open (`/tmp/hippo-cc11b-retention-cases.log`).

| Case | Parameters | Calls | Rows returned | `phys_footprint` growth | Per call | `MALLOC_SMALL` dirty per call | Freed by closing |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `MATCH (n:Item {id: $id}) RETURN n.id, n.v`, on the connection that wrote the rows | yes | 40,000 | 40,000 | +187.0 MB | 4.79 KB | 4.76 KB | 112 MB |
| the same, on a new connection over rows another connection wrote | yes | 40,000 | 40,000 | +185.0 MB | 4.74 KB | 4.68 KB | 112 MB |
| the same, on a reopened database with no write on this connection | yes | 40,000 | 40,000 | +184.0 MB | 4.71 KB | 4.68 KB | 114 MB |
| the same, for ids that do not exist | yes | 40,000 | 0 | +186.0 MB | 4.76 KB | 4.76 KB | 112 MB |
| `MATCH (n:Item) WHERE n.id = 'i…' RETURN n.id, n.v`, the id in the query text | **no** | 40,000 | 40,000 | +0.0 MB | **0.00 KB** | 0.00 KB | 0 MB |
| `MATCH (n:Item) WHERE n.id = $id RETURN n.id, n.v` | yes | 40,000 | 40,000 | +200.0 MB | 5.12 KB | 5.07 KB | 112 MB |
| `MATCH (n:Item {id: $id}) RETURN 1` | yes | 40,000 | 40,000 | +148.0 MB | 3.79 KB | 3.79 KB | 111 MB |
| `RETURN $x AS x` | yes | 40,000 | 40,000 | +69.0 MB | 1.77 KB | 1.77 KB | 48 MB |
| `RETURN size($s) AS n`, a 100-byte string | yes | 40,000 | 40,000 | +103.0 MB | 2.64 KB | 2.61 KB | 48 MB |
| the same, a 10 KB string | yes | 10,000 | 10,000 | +130.0 MB | 13.31 KB | 13.21 KB | 99 MB |
| the same, a 100 KB string | yes | 2,000 | 2,000 | +225.0 MB | 115.20 KB | 114.69 KB | 0 MB |
| `RETURN size('…') AS n`, a 10 KB string in the query text | **no** | 10,000 | 10,000 | +0.0 MB | **0.00 KB** | 0.10 KB | 0 MB |
| `UNWIND $ids AS wanted MATCH (n:Item {id: wanted}) RETURN n.v`, 1,000 ids | yes | 2,000 | 2,000,000 | +247.0 MB | 126.46 KB | 125.44 KB | 239 MB |
| `CREATE (:Doc {id: $id, body: $body})`, a new id and a 1 KB body each call | yes | 20,000 | 0 | +132.0 MB | 6.76 KB | 6.50 KB | 113 MB |
| hippo's `LadybugStore.run("MATCH (n:ProbeItem {id: $id}) RETURN n.id AS id, n.v AS v", id=…)` on the hippo schema | yes | 40,000 | 40,000 | +187.0 MB | 4.79 KB | 4.76 KB | 262 MB (`LadybugStore.close`, which also closes the database and releases the schema migration's own) |

What it shows:

1. **Every `Connection.execute(query, parameters)` call keeps native memory for as long as the
   connection stays open.** In real_ladybug 0.15.3 that call prepares a statement and executes it
   (`real_ladybug/connection.py:127-139`). A call without parameters goes through `Connection.query`
   and keeps nothing, even with a 10 KB literal in the query text. None of these makes a difference:
   writes on the connection, a new connection, a reopened database, whether rows come back.
2. **The amount grows with the parameters.** A keyed read keeps about 4.7 KB, and a 100-byte string
   about 2.6 KB. Past that base it is roughly the parameter's own size: 13.3 KB for a 10 KB string,
   115 KB for a 100 KB string and 126 KB for a 1,000-id list. A `CREATE` with a 1 KB property keeps
   6.8 KB. Hippo's build statements carry JSON payloads and id lists, which is why the scenario's
   dirty footprint rose far faster (about 2 GB a minute in the N=16 resumed bootstrap) than its
   recorded keyed reads alone explain.
3. **Only closing the connection gives it back, and not always all of it.** `gc.collect()` frees
   nothing. Closing the connection freed 112 of about 185 MB for the keyed reads and 239 of 247 MB
   for the id lists. It freed none of the 225 MB kept by 2,000 calls with a 100 KB string, which
   stayed after the close while the database was open. In the scenario, each reopen closes both the
   connection and the database, and the dirty memory came back (N=16: 16.0 GiB to 0.8 GiB).
4. **hippo's store takes that path for almost every statement.** `LadybugStore` opens one
   `lb.Connection` for its whole life (`store/ladybug.py:321`), and `run` passes parameters whenever a
   statement has any (`:391`). It closes every result (`:399`) and caches nothing. A keyed
   `LadybugStore.run` keeps 4.79 KB, the same as the bare driver. The growth is therefore in the driver,
   per statement, until the store closes. That holds for a long-lived hippo server as much as for this
   scenario.
5. **An earlier single-process version of this matrix is superseded.** Run in one process, later
   cases reused memory that earlier cases had freed, which made a new connection and an empty table
   look flat (`/tmp/hippo-cc11b-retention-matrix.out`, `/tmp/hippo-cc11b-conn-probe.out`). The first
   fresh-process pass, which measured `MALLOC_SMALL` only (`/tmp/hippo-cc11b-retention-cases-v1.log`),
   agrees with the table above to within 0.1 KB per call where the two overlap.

### Attribution run A: the read recorder and the timings knob off

The scenario at N=8 with the 4 GiB pool, from the uncommitted copy
`tests/unit/test_zz_cc11b_norecorder_scratch.py`. That copy is the acceptance test with the
`_native_rows`, `_knowledge_rows` and `_native_relationships` wrappers removed and `assert_cd1_bound`
dropped. The transaction-depth wrapper stays, because the HTTP runtime refuses calls inside a
transaction. `HIPPO_CODE_ACCEPTANCE_TIMINGS` was unset, and the same guard ran. Logs:
`/tmp/hippo-cc11b-ladybug-a8.log` and `-a8-guard.log`; footprint every 30 s in
`/tmp/hippo-cc11b-footprint2-a8.log`; swap in `/tmp/hippo-cc11b-swapwatch-a8.log`.

| Run | Result | Peak RSS | Peak footprint | Lowest unused memory | Swap growth |
| --- | --- | --- | --- | --- | --- |
| N=8 as the ledger runs it (recorder and timings on) | `2 passed in 1615.56s (0:26:55)` | 27,510,325,248 B (25.6 GiB) | 16,930,459,520 B (15.8 GiB) | 11.0 GB | not watched |
| Run A (recorder and timings off) | `2 passed in 1269.94s (0:21:09)`, EXIT 0, guard not tripped | 27,198,291,968 B (25.3 GiB) | 16,786,312,848 B (15.6 GiB) | 13.0 GB | +0 MB |

Removing the harness's read recorder lowered the peak RSS by 0.29 GiB and the peak footprint by
0.13 GiB. That is about what the recorder's list of some 737,000 `(kind, scope)` tuples at N=8 should
weigh. The retention is not the harness's.

The footprint over run A, every other 30 s sample:

| Time | `phys_footprint` | `MALLOC_SMALL` dirty | `MALLOC_SMALL` reclaimable |
| --- | --- | --- | --- |
| 17:17:53, start | 363 MB | 325 MB | 0 |
| 17:19:54 | 4,637 MB | 4,481 MB | 182 MB |
| 17:20:55 | 793 MB | 617 MB | 4,729 MB |
| 17:25:00 | 5,513 MB | 5,219 MB | 4,729 MB |
| 17:27:02 | 817 MB | 613 MB | 9,914 MB |
| 17:31:06 | 2,950 MB | 2,705 MB | 9,914 MB |
| 17:35:10 | 7,728 MB | 7,387 MB | 9,914 MB |
| 17:38:14 | 15 GB | 15 GB | 9,914 MB |

Run A writes no progress file, so its phases are inferred from the N=8 step's durations. The two
drops (17:20:55 and 17:27:02) fall where the scenario's first two reopens close the store: after the
crash bootstrap and after the resumed bootstrap publishes. Each time the dirty memory becomes
reclaimable. From the second reopen to the end, one store serves the projection, the dense dispatch and
the refresh, and the footprint climbs to its 15 GB peak just before the last reopen. The peak therefore
measures how many statements one open connection has executed. It does not measure what the process
holds live between closes.

### Attribution B smoke: tracemalloc probes at N=2, with the close and reopen pair

The scenario at N=2 (20 accepted files) with the 4 GiB pool, from the uncommitted copy
`tests/unit/test_zz_cc11b_tracemalloc_scratch.py`. That copy is run A's plus a probe at every build and
phase start and end, and around one extra close and reopen after the scenario. Each probe records:

- RSS;
- tracemalloc's traced memory, at 8 frames;
- `/usr/bin/footprint`;
- a census of gc-tracked objects;
- RSS before and after `gc.collect()`.

The probe log is `/tmp/hippo-cc11b-probe-b2.log`; the table below comes from
`/tmp/hippo-cc11b-attribution.py probe`. Once the driver probe had reproduced the retention, the
orchestrator ruled B at N=8 unnecessary, so this is the only B run.

Result: `2 passed in 1794.95s (0:29:54)`, EXIT 0. Peak RSS was 8,794,079,232 B (8.2 GiB) and peak
footprint 6,036,790,088 B (5.6 GiB). The guard did not trip, and swap use fell by 104 MB. Tracing and
the probes make this run far slower than CC11's untraced N=2 run (455 s), so its durations are not
comparable to the others.

Per probe, in GiB; each Δ is the change since the previous probe:

| Probe | RSS | ΔRSS | Traced (Python) | ΔTraced | `phys_footprint` | ΔFootprint | RSS after `gc.collect()` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 17:39:04 scenario start | 0.40 |  | 0.000 |  | 0.38 |  | 0.40 |
| 17:39:06 build bootstrap started | 0.45 | +0.05 | 0.002 | +0.00 | 0.25 | -0.13 | 0.45 |
| 17:41:29 build bootstrap ended after 143.5s | 2.99 | +2.54 | 0.015 | +0.01 | 2.82 | +2.57 | 3.02 |
| 17:41:35 phase reopen during staging started | 3.03 | +0.04 | 0.016 | +0.00 | 2.85 | +0.03 | 3.05 |
| 17:41:43 phase reopen during staging ended after 8.6s | 3.08 | +0.05 | 0.016 | +0.00 | 0.97 | -1.88 | 3.08 |
| 17:41:48 build bootstrap started | 3.08 | +0.00 | 0.016 | +0.00 | 0.98 | +0.01 | 3.08 |
| 17:44:14 build bootstrap ended after 146.4s | 3.04 | -0.04 | 0.020 | +0.00 | 0.54 | -0.43 | 3.05 |
| 17:44:23 phase reopen after publication started | 3.05 | +0.01 | 0.018 | -0.00 | 0.55 | +0.00 | 3.06 |
| 17:44:32 phase reopen after publication ended after 8.5s | 3.04 | -0.01 | 0.018 | +0.00 | 0.54 | -0.01 | 3.04 |
| 17:44:40 phase seal validation and checksums started | 3.06 | +0.02 | 0.018 | +0.00 | 0.52 | -0.02 | 3.05 |
| 17:45:20 phase seal validation and checksums ended after 39.8s | 3.03 | -0.03 | 0.020 | +0.00 | 0.46 | -0.06 | 3.03 |
| 17:45:31 phase projection, arrows and source row started | 3.03 | +0.00 | 0.018 | -0.00 | 0.46 | +0.00 | 3.03 |
| 17:47:45 phase projection, arrows and source row ended after 133.9s | 3.05 | +0.02 | 0.019 | +0.00 | 0.48 | +0.02 | 3.05 |
| 17:47:55 phase verified dense dispatch started | 3.05 | +0.00 | 0.019 | +0.00 | 0.48 | +0.00 | 3.05 |
| 17:57:02 phase verified dense dispatch ended after 547.4s | 4.30 | +1.25 | 0.021 | +0.00 | 1.75 | +1.26 | 4.32 |
| 17:59:04 build refresh started | 4.65 | +0.35 | 0.022 | +0.00 | 2.09 | +0.35 | 4.66 |
| 18:04:02 build refresh ended after 297.9s | 7.63 | +2.98 | 0.028 | +0.01 | 5.09 | +3.00 | 7.66 |
| 18:06:20 phase reopen after refresh started | 8.17 | +0.54 | 0.024 | -0.00 | 5.62 | +0.53 | 8.19 |
| 18:06:41 phase reopen after refresh ended after 21.0s | 8.16 | -0.01 | 0.024 | +0.00 | 1.38 | -4.24 | 8.15 |
| 18:07:31 scenario end | 8.10 | -0.06 | 0.025 | +0.00 | 0.76 | -0.62 | 8.10 |
| 18:07:53 close and reopen pair: before close | 8.10 | +0.00 | 0.024 | -0.00 | 0.76 | +0.00 | 8.10 |
| 18:08:15 close and reopen pair: after close, references dropped | 8.04 | -0.06 | 0.024 | +0.00 | 0.71 | -0.05 | 8.04 |
| 18:08:37 close and reopen pair: after reopen | 8.08 | +0.04 | 0.024 | +0.00 | 0.74 | +0.03 | 8.08 |

What it shows:

1. **Python allocations are not the growth.** tracemalloc's traced memory never passed 32 MB, while the
   footprint reached 5.6 GiB. In the phases that grew, traced memory rose by 0.01 GiB or less:
   - the crash bootstrap, +2.57 GiB footprint;
   - the dense dispatch, +1.26 GiB;
   - the refresh, +3.00 GiB.

   The largest traced growth sites are MiB-sized: `real_ladybug/query_result.py:98` (+2.1 MiB in 55,422
   blocks during the dense dispatch), pydantic model construction and the JSON encoder.
2. **`gc.collect()` never lowers RSS.** At every probe the RSS before and after the collection agree to
   within 0.03 GiB.
3. **A close gives the live memory back; the RSS stays.** The scenario's reopen after the refresh took
   the footprint from 5.62 to 1.38 GiB while RSS stayed at 8.16 GiB. The freed pages became
   reclaimable, rising from 2.54 to 6.75 GiB of reclaimable `MALLOC_SMALL`. The reopen during staging
   did the same (2.85 to 0.97 GiB). So native memory does not survive a close as live memory. What
   survives is RSS in freed pages, which `gc.collect()` cannot reduce and which the kernel takes back
   under pressure.
4. **The extra close and reopen pair had nothing left to release.** It ran after the scenario's own
   last reopen, on a store that had executed few statements. The footprint went 0.76, 0.71, 0.74 GiB
   and RSS 8.10, 8.04, 8.08 GiB. Its gc census still counted five `LadybugStore`, `Database` and
   `Connection` objects after `w.reopened` was cleared, and four after the reopen: the `store` fixture
   and the instrumented transaction wrappers still refer to closed stores. They are closed, and the
   footprint shows no memory held by them.

## Gate runs on the final tree (brief item 2)

Every CHECK line was taken from the worktree's `GATES.md` at `14d0a37` by
`/tmp/hippo-cc11b-run-gates.sh`, which reads the `CHECK:` line under each gate, saves it to
`/tmp/hippo-cc11b-cd<N>.cmd` and evaluates it unchanged, with output to `/tmp/hippo-cc11b-cd<N>.log`
and `EXIT <rc>` appended. No line needed the AnyIO filter (form (b)); no log holds a warning.

| Gate | Backend | Command | Result line | EXIT | Log |
| --- | --- | --- | --- | --- | --- |
| CD1 | Fake | `GATES.md:18` verbatim | `93 passed in 19.53s` | 0 | `/tmp/hippo-cc11b-cd1.log` |
| CD2 | Fake | `GATES.md:23` verbatim (with `test_managed_code_activation.py`, applied at `4795c0e`) | `169 passed, 2 skipped in 15.61s` | 0 | `/tmp/hippo-cc11b-cd2.log` |
| CD3 | Fake | `GATES.md:28` verbatim | `152 passed in 2.54s` | 0 | `/tmp/hippo-cc11b-cd3.log` |
| CD4 | Fake | `GATES.md:33` verbatim | `95 passed in 2.72s` | 0 | `/tmp/hippo-cc11b-cd4.log` |
| CD5 | Fake | `GATES.md:38` verbatim | `89 passed in 1.12s` | 0 | `/tmp/hippo-cc11b-cd5.log` |
| CD6 | Fake | `GATES.md:43` verbatim | `91 passed in 14.48s` | 0 | `/tmp/hippo-cc11b-cd6.log` |
| CD7 | Fake | `GATES.md:48` verbatim | `83 passed in 16.75s` | 0 | `/tmp/hippo-cc11b-cd7.log` |
| CD8 | Fake | `GATES.md:53` verbatim | `306 passed, 3 skipped in 75.54s (0:01:15)` | 0 | `/tmp/hippo-cc11b-cd8.log` |
| CD9 | LadybugDB | `GATES.md:58` | **Not run.** The orchestrator ruled against the ledger-size run after N=8 and N=16 (see the step-up section and "Orchestrator rulings") | — | — |
| CD10 | — | `GATES.md:63` verbatim, Ruff 0.16.6 | `All checks passed!` / `10 files already formatted` | 0 | `/tmp/hippo-cc11b-cd10.log` |
| Full Fake suite | Fake | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"` | `4484 passed, 30 skipped in 900.68s (0:15:00)` | 0 | `/tmp/hippo-cc11b-full-fake.log` |

The full Fake suite ran on the final tree for the first time. CC11's last complete run, on the kscope
tree, was `1 failed, 4451 passed, 29 skipped`; the failure was CC11's own CD1 recorder, fixed in
`69976b4`. The difference since then is 33 passed and 1 skipped: lbpool's
`test_ladybug_buffer_pool.py` (23 tests, of which the `store`-fixture cap test skips off LadybugDB)
and qscope's `test_query_scoped_reads.py` (10). The suite includes the CD9 scenario at its default
size (48 files per language) on Fake. It carries no skip there, but its three reopen steps return
without reopening, because the Fake store has no second life (`reopen` in the test file).

The Fake counts equal CC11's runs at `9a474e4` gate for gate (CD2 against CC11's amended-line run),
so neither the fix merges nor qscope moved a Fake gate count.

The five skips in CD2 and CD8 are all LadybugDB reopen contracts that skip on Fake (the same modules
rerun with `-rs`, `/tmp/hippo-cc11b-skips.log`, `419 passed, 5 skipped`, EXIT 0):

- `test_converting_source_serving.py:366` and `test_managed_source_inventory.py:597`: "reopen is a
  LadybugDB persistence assertion";
- `test_managed_pipeline_activation.py:1155`, `:1584` and `test_prose_generation.py:1028`: "real
  Ladybug close/reopen contract".

**Proposed CD1 line, run as evidence for the proposal under "Ledger lines":** the CD1 CHECK plus
`tests/unit/test_knowledge_scoped_reads.py` and `tests/unit/test_query_scoped_reads.py`, Fake, bare
`-W error`: `118 passed in 58.69s`, EXIT 0, no warning (`/tmp/hippo-cc11b-cd1-amended.log`).

## Ledger lines (brief item 3)

Each gate below is a complete CHECK/CRITERIA/EXPECT set for the orchestrator to paste over the
current lines. `/tmp/hippo-cc11b-ledger-gen.py` generates the set. It copies every unchanged line from
the worktree's `GATES.md` and every CC11 correction verified against the final tree from
`evidence-cc11.md`, and it asserts that each CHECK and EXPECT it leaves alone equals root's. CC11
wrote its lines before qscope. Checked against the final tree:

- CD2's CHECK and CRITERIA amendments and CD9's CHECK amendment are already in `GATES.md` (`4795c0e`).
- CD3, CD4 and CD8: CC11's CRITERIA corrections hold as written.
- CD1: CC11's clause had drifted and is corrected. The CHECK gains the two test modules its CRITERIA
  cite; this is a proposal, run on Fake.
- CD5, CD6, CD7 and CD10 are unchanged.
- CD9: the CHECK is unchanged. The CRITERIA gains a cc11b clause stating that the multi-hundred-file
  clause is not evidenced on LadybugDB, and why. The EXPECT stays `passed` and carries no counts: the
  line was not run at the ledger size (orchestrator ruling), so there is no result to count. This
  slice's evidence cannot tick CD9.

**Ledger header** (not a gate line). CC11's proposed replacements for `GATES.md:3` and `:14-15` still
apply, with the status naming this slice:
`**Status:** implemented through CC11 and the fix slices kscope, codeproj, lbpool and qscope; acceptance evidence in evidence-cc11.md and evidence-cc11b.md; CD9 at the ledger size awaits the LadybugDB connection-recycling fix (lbconn); gates unticked until the checker runs.`
and `Every CHECK line runs from /Users/mascott/projects/hippo. Runnable checkboxes are set by the
orchestrator's gate checker, never by an implementer.`

**CD1** (CHECK and CRITERIA amended. CC11's CRITERIA clause named `validate_view`, which no `src/` path calls any more (KSCOPE, `ccaa3e5`, put `GenerationViews` on the write and checksum paths; QSCOPE put it on the query path), and said the write checks read the generation's rows, where they read by key. The clause cites KSCOPE's knowledge-table bound and QSCOPE's query-time bound, whose tests are on no CD line; the CHECK gains both files, as CD2's CHECK gained the file its CRITERIA cited. Run on Fake: `118 passed`, EXIT 0, `/tmp/hippo-cc11b-cd1-amended.log`. If the CHECK amendment is not taken, drop the clause after the final semicolon and the two test names.)

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_scoped_reads.py tests/unit/test_generation_store.py tests/unit/test_generation_counts.py tests/unit/test_staged_prose_writer.py tests/unit/test_knowledge_scoped_reads.py tests/unit/test_query_scoped_reads.py -q -o addopts='' -W error
CRITERIA: parameterised `_native_rows`, `_native_relationships` and `_knowledge_rows` return exactly what the unscoped forms returned for the same selection; `native_write`, `native_mutation` and `generation_checksums` use them; a recorded query counter proves per-batch work is bounded by the batch rather than by corpus size; every existing representation checksum, seal and publication result is unchanged; the reviewed prose writer and counts suites stay green. (Amended 2026-09-12 by the design review: native_write and native_mutation scope by ids and native_mutation still raises 'Native relationship crosses generations' for an edge across two generations and still admits an edge to an untagged legacy row; the scoped read is index-backed on the backends that support one, evidenced by the schema statement and not only by the query counter; sealing a generation at the symbol ceiling is linear in the generation in CPU as well as in queries; the scoped edge enumeration still returns every edge with exactly one endpoint in the selection so the 'Native relationship crosses generations' and 'Missing shared graph endpoint' refusals survive, and the two-hop MENTIONS/STATES -> SUBJECT/OBJECT closure is computed by a second scoped pass, never a whole-table read.) (Amended 2026-09-13 by CC11, corrected by cc11b on the final tree: the per-batch bound covers the knowledge tables as well as the native ones — `_check_knowledge_write`'s membership and binding checks read by `generation_id`, by primary key or by a v7 key, and `derivations._Inventory` reads the generation's own `GenerationMember` and `GenerationEvidenceMember` rows and its `DerivedDependency` rows by `derived_record_id`, built once per generation for a `native_write` call or a checksum pass through `GenerationViews` rather than once per rendered passage through `validate_view`, so no generation-sized knowledge table is read whole per record written and a managed code build is linear in its corpus (KSCOPE, `test_knowledge_scoped_reads.py`, `evidence-kscope.md`, `evidence-cc11.md` finding 1); a query's proof, projection, snapshot, collection and retention reads are scoped to the generations it selects, so a session's open, lease renewal, validation, retrieval and dense dispatch read no generation-sized knowledge kind whole (QSCOPE, `test_query_scoped_reads.py`, `evidence-qscope.md`).)
EXPECT: passed
```

**CD2** (unchanged: both CC11 amendments are in `GATES.md` since `4795c0e`.)

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_converting_source_serving.py tests/unit/test_managed_source_inventory.py tests/unit/test_status_access.py tests/unit/test_structural_loading.py tests/unit/test_managed_code_activation.py -q -o addopts='' -W error
CRITERIA: `source_serves_legacy` is true for a source holding only staging Artifact/Generation rows and false once a generation is published or an all-principals suppression targets the source, independent of the managed flag, which flips at staging start (ruling 9); such a source keeps its complete legacy passages, code nodes and edges in every query and appears exactly once in source inventory with its legacy counts; with the converting source as the only managed source on the instance, no staged passage, symbol, data object or commit appears in any query result; publication flips lane, active pointer, counts and presentation in one transaction; an authorized empty published generation still appears with zero counts; a denied or tombstoned source appears in neither lane; only UNTAGGED rows ever serve the legacy lane, and a source holding a Generation row is presented in the legacy lane only while it owns at least one untagged passage, symbol, data object or commit, so a bootstrap-only managed source is absent from every graph surface, dropdown, eval label and count until publication (ruling 14, `evidence-cc1fix.md`); an actorless delete, reindex or bulk reindex of a converting source refuses rather than clearing it (`delete_source`, `delete_passages_for_source`, `delete_code_nodes_for_source`, `remove_orphans`, `_collect_generation`, `_prepare_reindex`, `_clear_passages`, `read_source` and `shutil.rmtree` outside the named per-operation checkout are never reached) and the source can still be tombstoned (store-level refusals CC1, pipeline-level spies CC10, `evidence-cc10.md`).
EXPECT: passed
```

**CD3** (CRITERIA corrected as CC11 proposed, verified on the final tree: `repo_capture.EXCLUSION_REASONS` holds `binary`, `not_regular`, `submodule` and `symlink`; `escaping_path` is a refusal reason; `accepted_inputs.py:166` and `:277` refuse a file changed during capture.)

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_repo_capture.py tests/unit/test_code_provenance.py tests/unit/test_accepted_inputs.py -q -o addopts='' -W error
CRITERIA: the tree inventory is normalized, sorted and identical under a reordered walk; ignored directories, oversized files, unsupported names, binary content, symlinks, submodules, non-regular files and explicit exclusions each carry a distinct recorded reason (ruling 7); a path escaping the root and a file changed during capture are refused rather than skipped; code and config decode with exact complete-line locators, Unicode byte mappings and the legacy trim behaviour; rich, archive-inside-archive and binary outcomes refuse in this seam; the accepted manifest excludes itself and contains no absolute path; every later read is from the captured raw object.
EXPECT: passed
```

**CD4** (CRITERIA corrected as CC11 proposed, verified: `evidence-cc5.md` finding 1; the chunker's `_mention_index` names data objects in a window and synthesizes no mention text.)

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_prepared_code_chunks.py tests/unit/test_ingest_chunker.py -q -o addopts='' -W error
CRITERIA: for seeded trees the prepared chunk text, order and `defines` equal the committed `chunk_documents(..., code=code)` output; every chunk maps to exact original line ranges plus explicitly marked generated segments for the context header and commit passages (the committed chunker synthesizes no data-object mention text, so none is mapped); oversized bodies split at statement boundaries as today; a chunk whose text is byte-identical to one original region carries no generated segment; remapped, rich and already-derived inputs reject.
EXPECT: passed
```

**CD5** (unchanged.)

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_binding.py tests/unit/test_managed_input_binding.py -q -o addopts='' -W error
CRITERIA: spans, rendered views, derived records and dependencies, knowledge objects, observations, native rows, bindings, revision members and evidence members form one closed inventory with no duplicate and no orphan *binding* — a `repository` or `file` knowledge object legitimately has observations and no native row, and must not be treated as an orphan; native IDs equal `symbol_id`/`data_id`/`commit_id` under the generation namespace; `symbol_key` carries the signature discriminator so overloads do not merge; a shared canonical symbol observed by two sources keeps distinct per-source observations; no `Assertion`, `AssertionVersion`, `AssertionSupport` or `SYNONYM` row is produced; the materialiser holds no store handle, model client or clock.
EXPECT: passed
```

**CD6** (unchanged.)

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_history.py tests/unit/test_git_history.py -q -o addopts='' -W error
CRITERIA: one `history_event` artifact and revision per commit carrying the author date in `source_updated_at`, the raw `%aI` text in `source_timestamp_original`, its offset in `source_timezone` and `source_precision="second"`; commit observations use `valid_from` = author date, `validity_kind="explicit_interval"`, `temporal_basis="commit"`, `recorded_from` = the one injected capture instant, `recorded_to` null; no record calls a wall clock and no default instant appears anywhere; `MODIFIES` hunks and `PRECEDES` pairs bind only to symbols of the same generation; `skipped`, `truncated`, the shallow boundary, renames and disabled history are recorded in coverage and never presented as a complete history; the first-parent restriction of the history walk is recorded in coverage beside `skipped`, `truncated` and the shallow boundary, so a first-parent history is never presented as the repository's complete history; every commit observation carries an explicit `evidence_class` (`declared`), its span is a `field` locator over the commit message on the history_event revision, and the history rule version enters generation identity through a top-level configuration key the merge refuses to do without (ruling 10, option 3).
EXPECT: passed
```

**CD7** (unchanged.)

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_staged_code_writer.py tests/unit/test_generation_resume.py tests/unit/test_generation_failure.py -q -o addopts='' -W error
CRITERIA: batches are complete dependency groups, so no batch leaves a dangling endpoint or an unbound native row; every batch revalidates lease, fence, authorization and suppression inside its own short transaction; no callback, model call or filesystem access occurs inside a transaction; missing, extra or conflicting rows refuse the seal; the seal writes an `IndexManifest` with the evidence, dense and native representations and matching checksums; `reclaim_generation_build` resumes a never-published attempt with an equal `manifest_hash` without collecting, a different manifest still collects, a published generation never reopens, and identical replay is idempotent while a conflicting persisted payload fails closed; a lost fence or expired lease prevents every write and the seal; a reclaim on a tombstoned source, on a source with a live holder, with an expired lease, or on a generation with any of the three publication proofs refuses without advancing the fence or installing a holder; a resumed build adopts the persisted capture instant, reproduces every `ObjectObservation` ID byte-identically and reports a nonzero `resumed_from_batches`; a staged generation holding a record the current derivation would not produce fails the resume rather than sealing; the resume probe checks every row of a group against its canonical payload, never a sample and never `native_write`'s tolerant equality, and a relation group binds only to endpoints this attempt would produce; a sealed code generation validates under the `code` generation profile (one manifest, one repository, one file per accepted input, zero or more history_event members, the history_event pairs excluded from identity) at seal, checksum and query time, and the plain-prose profile's member set and every existing checksum are byte-identical (ruling 13); a refresh over an unchanged file reuses its immutable revision, so one revision record is a member of both generations and its `observed_at` stays the instant it was first observed.
EXPECT: passed
```

**CD8** (CRITERIA corrected as CC11 proposed, verified: `BuildReceipt.resumed_from_batches` is `_resumed_batches` (`code_generation.py:859-868`), the `ResumePlan`'s skipped dependency groups whose index is past the revision-member groups the install writes before every attempt (`evidence-cc9b.md:392`).)

```text
CHECK: HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_code_generation.py tests/unit/test_managed_code_activation.py tests/unit/test_ingest_pipeline.py tests/unit/test_ingest_concurrency.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_prose_generation.py -q -o addopts='' -W error
CRITERIA: an authenticated actor converts an eligible `repo`, `archive` or code `file` and the legacy graph serves unchanged until publication; refresh keeps G1 selected through capture, extraction, every write batch and the seal, and after failure or cancellation; a crashed build resumes the same generation and reports the skipped dependency-group count (`resumed_from_batches`, excluding the revision-member groups every install writes); `already_current` returns without inference; the head SHA, walker rules version and per-grammar parser profile participate in generation identity while worker count, clone depth and progress do not; `BuildAuthority.rebaseline` accepts an unrelated authorization-epoch change and refuses after any capability loss, after any suppression-epoch change, when the Source row's `access_role_id`, `min_rank` or `owner_id` changed even though the actor kept every capability, after a sticky failure and inside a transaction, and never adopts a suppression epoch or a changed `SourceControl`; a bootstrap publication expects no authorization-epoch change in its window because the managed flip happened at staging start, and a genuine unrelated authorization change in the same window still refuses; open, preview and actorless callers and unsupported source kinds stay legacy; spies on `_clear_passages`, `delete_passages_for_source`, `delete_code_nodes_for_source`, `remove_orphans`, `store.delete_source`, `shutil.rmtree`, generation collection and raw unlink are never called for a managed attempt; the reviewed prose coordinator suite is unchanged by the `_Run` extraction.
EXPECT: passed
```

**CD9** (CHECK unchanged (the acceptance file is in `GATES.md` since `4795c0e`). CRITERIA and EXPECT: see the CD9 bullet at the top of this section.)

```text
CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_code_generation.py tests/unit/test_staged_code_writer.py tests/unit/test_generation_resume.py tests/unit/test_generation_scoped_reads.py tests/unit/test_converting_source_serving.py tests/unit/test_managed_code_activation.py tests/unit/test_code_history.py tests/unit/test_structural_loading.py tests/unit/test_dense_session.py tests/unit/test_code_capture_acceptance.py -q -o addopts='' -W error
CRITERIA: close and reopen preserves generation pointers, fences, exact membership, native code rows and relations, bindings, manifests, raw references, resumable staging state and coverage; a published code generation projects `StructuralCodeEvidence` with exact original spans and original citations with real line locators, its sealed native `DEFINED_IN` rows each join a bound node to a passage of the same generation whose original spans include the node's binding span, the structural graph's projected `DEFINED_IN`, `CODE_EDGE`, `MODIFIES` and `PRECEDES` arrows equal the selected generation's sealed native rows and `status.source_view`'s `edges_by_kind` equals its native `CODE_EDGE` rows (the managed lane writes no `REFERS_TO` and a declaration-only module stays unbound, as `evidence-codeproj.md` pins), and it routes through verified dense dispatch; a retired generation stays reconstructable under a live snapshot; a refresh over an unchanged file or commit reuses its immutable revision, and the shared record survives reopen unchanged; a representative multi-hundred-file fixture (`tests/fakes/code_capture_repo.py`, 270 accepted files at its default size) completes within the ceilings of the plan's §8.3 on a LadybugDB store opened with the production buffer pool (4 GiB, `MAX_DEFAULT_BUFFER_POOL_BYTES`), with the CD1 query bound holding for native reads and for the build's own knowledge reads. (Amended 2026-09-13 by CC11: the CD1 linearity bound at the 50,000-symbol ceiling is proven on Fake by CC2's synthetic fixture, and the index-backed half of the bound is proven on Neo4j (parity run 2), not on LadybugDB, which creates no secondary index; the multi-hundred-file fixture does not exercise the symbol ceiling and is not presented as doing so; the LadybugDB `IN <list>` engine defect on node string columns is guarded by `store.base.by_ids` and the static tripwire `test_no_query_builder_selects_node_rows_with_a_list_predicate`, `evidence-lbfix.md`.) (Amended 2026-09-13 by cc11b: the query-time half of the read bound, that a session over the published generation reads no generation-sized knowledge kind whole, is QSCOPE's and runs under CD1 (`test_query_scoped_reads.py`). The multi-hundred-file clause is not yet evidenced on LadybugDB: the ledger size was not run; 8 files per language (50 accepted files) is the largest size that completed on the production pool, and 16 (94 files) was stopped by the memory guard in its refresh build, because real_ladybug 0.15.3 retains native memory for every parameterised `Connection.execute` until the connection closes and `LadybugStore` keeps one connection open (`evidence-cc11b.md`). CD9 is run at the ledger size after the connection-recycling fix, lbconn.) Root records disposable-Neo4j parity for the same files here as an evidence note, run serially against the reserved container, never as a second concurrent pytest process.
EXPECT: passed
```

**CD10** (unchanged; ten files.)

```text
CHECK: .venv/bin/ruff check src/hippo/ingest/repo_capture.py src/hippo/ingest/code_provenance.py src/hippo/ingest/prepared_code_chunks.py src/hippo/ingest/code_generation.py src/hippo/ingest/build_run.py src/hippo/knowledge/code_binding.py src/hippo/knowledge/code_history.py src/hippo/knowledge/staged_code.py && .venv/bin/ruff format --check src/hippo/ingest/repo_capture.py src/hippo/ingest/code_provenance.py src/hippo/ingest/prepared_code_chunks.py src/hippo/ingest/code_generation.py src/hippo/ingest/build_run.py src/hippo/knowledge/code_binding.py src/hippo/knowledge/code_history.py src/hippo/knowledge/staged_code.py ai_docs/plans/rag-it-all-task-5-managed-code-capture.md ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md
CRITERIA: no lint findings; the formatter also checks the fenced Python in the plan and this ledger, which the CI Ruff job runs; independent SPEC and QUALITY reviews pass with every finding closed and each affected gate rerun afterwards.
EXPECT: 10 files already formatted
```

## Commands

Every command runs from `.worktrees/cc11b`. Scripts under `/tmp` are this slice's and are not
committed.

```bash
# Worktree and venv (the rules' recipe at base 14d0a37), then the two pins
git worktree add .worktrees/cc11b -b wp/cc11b 14d0a37
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e '.[dev,neo4j]'
uv pip install --python .venv/bin/python 'mcp==2.1.1'
uv pip install --python .venv/bin/python 'ruff==0.16.6'

# CD1-CD8 and CD10: each CHECK line read from GATES.md and evaluated unchanged
/tmp/hippo-cc11b-run-gates.sh   # /tmp/hippo-cc11b-cd<N>.log with EXIT; summary /tmp/hippo-cc11b-gates-summary.txt

# The proposed CD1 line (Fake)
HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_generation_scoped_reads.py tests/unit/test_generation_store.py tests/unit/test_generation_counts.py tests/unit/test_staged_prose_writer.py tests/unit/test_knowledge_scoped_reads.py tests/unit/test_query_scoped_reads.py -q -o addopts='' -W error > /tmp/hippo-cc11b-cd1-amended.log 2>&1; echo EXIT $? >> /tmp/hippo-cc11b-cd1-amended.log

# Skip reasons in CD2's and CD8's modules (the ten files of both lines, deduplicated, with -rs)
HIPPO_TEST_STORE=fake .venv/bin/pytest <the ten modules> -q -o addopts='' -W error -rs > /tmp/hippo-cc11b-skips.log 2>&1; echo EXIT $? >> /tmp/hippo-cc11b-skips.log

# The full Fake suite
HIPPO_TEST_STORE=fake .venv/bin/pytest tests -q -o addopts='' -W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning" > /tmp/hippo-cc11b-full-fake.log 2>&1; echo EXIT $? >> /tmp/hippo-cc11b-full-fake.log

# LadybugDB steps. The runner sets HIPPO_TEST_STORE=ladybug and HIPPO_CODE_ACCEPTANCE_TIMINGS, runs
# pytest under /usr/bin/time -l with the guard, and appends EXIT to /tmp/hippo-cc11b-ladybug-<tag>.log
/tmp/hippo-cc11b-ladybug-run.sh n8 8 default tests/unit/test_code_capture_acceptance.py
GUARD_INTERVAL=10 /tmp/hippo-cc11b-ladybug-run2.sh n16 16 default tests/unit/test_code_capture_acceptance.py

# Attribution: the scratch copies, run A and the B smoke (queued by /tmp/hippo-cc11b-attribution-chain.sh)
.venv/bin/python /tmp/hippo-cc11b-make-probes.py
TIMINGS=off GUARD_INTERVAL=10 /tmp/hippo-cc11b-ladybug-run3.sh a8 8 default tests/unit/test_zz_cc11b_norecorder_scratch.py
HIPPO_CC11B_TRACE_FRAMES=8 HIPPO_CC11B_MEMORY_PROBE=/tmp/hippo-cc11b-probe-b2.log PHASE_FILE=/tmp/hippo-cc11b-probe-b2.log TIMINGS=off GUARD_INTERVAL=10 /tmp/hippo-cc11b-ladybug-run3.sh b2 2 default tests/unit/test_zz_cc11b_tracemalloc_scratch.py

# The driver retention cases, one fresh process each
PROBE_READS=<calls> .venv/bin/python /tmp/hippo-cc11b-probes/ladybug_retention_case.py <case>

# Samplers, read-only
/tmp/hippo-cc11b-footprint2.sh <tag> <seconds> "<pgrep -f pattern>" [progress or probe file]
/tmp/hippo-cc11b-swapwatch2.sh <tag> "<pgrep -f pattern>"

# The ledger section and the memory tables
.venv/bin/python /tmp/hippo-cc11b-ledger-gen.py
.venv/bin/python /tmp/hippo-cc11b-attribution.py footprint /tmp/hippo-cc11b-footprint2-n16.log

# Ruff on this document
.venv/bin/ruff format --check ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc11b.md
```

## Findings

CC11's open findings 4 to 22 (`evidence-cc11.md`) are carried unchanged. cc11b did not re-verify
them; its own are below.

1. **CD1's CRITERIA cite bounds whose tests no CD line runs.** KSCOPE's knowledge-table bound
   (`tests/unit/test_knowledge_scoped_reads.py`) and QSCOPE's query-time bound
   (`tests/unit/test_query_scoped_reads.py`) are on no CHECK line in `GATES.md`, while CC11's CD1
   CRITERIA amendment claims the first. CC11 fixed the same gap for CD2. The proposed CD1 line under
   "Ledger lines" adds both files; on Fake it gives `118 passed`, EXIT 0.
2. **CC11's CD1 clause named a function no path calls.** `derivations.validate_view` still exists and
   two test modules call it (`test_derived_generation_store.py`, `test_managed_input_binding.py`), but every build, seal and query path in `src/` validates through
   `GenerationViews` (KSCOPE on the write and checksum paths, QSCOPE on the query path). The corrected
   clause says so.
3. **Two fix-slice test modules are on no CD line, and neither needs to be.** lbpool's
   `test_ladybug_buffer_pool.py` and CC11's `test_fake_store_threads.py` test a store setting and
   the Fake double. Both ran in the full Fake suite. Recorded so a reviewer does not have to look.
4. **A fresh worktree resolves Ruff 0.16.7; the rules and root use 0.16.6.** This worktree was pinned
   to 0.16.6 before CD10. Cached Ruff 0.16.7 gives the same CD10 result, `All checks passed!` and
   `10 files already formatted` (`/tmp/hippo-cc11b-cd10-ruff0167.log`), so the drift changes no
   gate today. The worktree recipe pins `mcp` and not `ruff`.

5. **Native per-statement retention in real_ladybug 0.15.3 `Connection.execute` with parameters,
   freed only by close.** Every parameterised `Connection.execute` keeps native memory until its
   connection closes, and a query without parameters keeps none. The amount per call:
   - 4.7 to 5.1 KB for a keyed read, whether or not rows come back, on any connection;
   - about the parameter's size on top of a base of about 2.6 KB: 13.3 KB for a 10 KB string, 115 KB
     for a 100 KB string, 126 KB for a 1,000-id `UNWIND` list;
   - 6.8 KB for a `CREATE` with a 1 KB property;
   - 4.79 KB for a keyed `LadybugStore.run`.

   `gc.collect()` frees none of it. `LadybugStore` keeps one connection for its whole life and
   parameterises almost every statement, so a store's native memory grows with every statement it
   executes. In the CD9 scenario that is 15.6 to 17.0 GiB of live footprint on one open store (N=8
   and N=16), given back at each reopen. The retention is production behaviour, not a harness effect:
   run A, without the read recorder, peaked within 0.3 GiB of the ledger run; tracemalloc in the B smoke
   saw at most 32 MB of Python allocations against a 5.6 GiB peak footprint; and a hippo server holds
   one store open. Routed to the fix slice lbconn, connection recycling at safe boundaries in
   `LadybugStore`, which the orchestrator is briefing. cc11b changed no production code.
6. **CD9 was not run at the ledger size, and N=16 did not complete.** The largest completed size is
   N=8 (50 accepted files). N=16 (94 files) completed through the dense dispatch and was stopped by
   the guard in its refresh build. N=48 (270 files) was not run, by ruling. Until lbconn lands, CD9's
   multi-hundred-file clause is not evidenced on LadybugDB; the proposed CD9 CRITERIA say so and its
   EXPECT carries no counts.
7. **RSS overstates live memory on macOS, and the guard's metric appears to count it.** Pages
   libmalloc freed but has not returned to the kernel stay in RSS. N=16 was stopped with a 6.4 GiB
   live footprint against a 33.1 GiB RSS, about 26 GiB of it reclaimable. That suggests those pages
   also count against `top`'s "unused" figure. The other processes on the machine used memory too, so
   this was not measured in isolation. The orchestrator kept `unused < 4 GB` as the stop rule
   and made `phys_footprint` the reported signal. A rerun of CD9 after lbconn should report both.
8. **The 4 GiB production pool was not the constraint at these sizes, and whether it suffices at the
   ledger size is still unanswered.** The pool's `VM_ALLOCATE` region stayed under 0.5 GiB dirty, and
   the N=8 database is 96 MB. lbpool's open question, whether 4 GiB is enough for a 270-file capture,
   waits for the CD9 run after lbconn.
9. **The per-batch native read bound does not grow with the corpus.** The maximum native reads per
   write batch were 20, 18 and 20 at N=2 and 10, 12 and 12 at N=8 (crash, resume, refresh), against
   `NATIVE_READS_PER_BATCH = 32`. `assert_cd1_bound` passed at N=8.
