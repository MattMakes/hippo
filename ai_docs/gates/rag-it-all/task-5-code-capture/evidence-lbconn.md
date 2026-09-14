# LBCONN evidence: LadybugStore recycles its driver connection so the driver's per-statement memory stays bounded

Branch `wp/lbconn`, worktree `.worktrees/lbconn`, base `2f7c168`. Not a plan slice. It fixes cc11b's
finding "native per-statement retention" (`evidence-cc11b.md` on `wp/cc11b`;
`/tmp/hippo-cc11b-retention-cases.log`, `/tmp/hippo-cc11b-conn-probe.out`).

## What real_ladybug 0.15.3 keeps, measured

cc11b's matrix showed that every `Connection.execute(query, parameters)` keeps native memory until the
connection closes. A keyed read keeps 4.7 KB, `RETURN $x` 1.8 KB, a literal query 0. A 10 KB string
parameter keeps 13.2 KB, a 100 KB string 114.7 KB, and an `UNWIND` over 1,000 ids 125.4 KB.
`gc.collect()` frees none of it. The driver's `execute` prepares a statement whenever it is given
parameters (`real_ladybug/connection.py:127-139`), and that path is the one that retains.

Before choosing the budget unit, lbconn measured which query shapes retain how much. The probe is
`/tmp/hippo-lbconn-probes/retention_probe.py <case>`, one fresh process per case, 1,000 warm-up
calls. The figures are the `phys_footprint` growth across the measured calls (from `proc_pid_rusage`,
which agrees with `/usr/bin/footprint` to within 1 MB), after `gc.collect()`, and what closing the
connection gave back. Log: `/tmp/hippo-lbconn-retention-probe.log`.

| Statement | Calls | Kept per call | Freed by `Connection.close()` | Time per call |
| --- | ---: | ---: | --- | ---: |
| `RETURN $x AS x` | 40,000 | 1,833 B | 48.1 of 69.9 MB | 133 µs |
| the same with 1,000 trailing spaces | 20,000 | 1,845 B | 16.0 of 35.2 MB | 176 µs |
| the same after a 1,000-character `//` comment | 20,000 | 1,857 B | 16.0 of 35.4 MB | 166 µs |
| `RETURN $x + 1 + … + 40 AS x` | 20,000 | 68,060 B | 1,034.5 of 1,298.1 MB | 1,478 µs |
| keyed read `MATCH (n:Item {id: $id}) RETURN n.id, n.v` | 40,000 | 4,900 B | 112.0 of 186.9 MB | 125 µs |
| a long read (`OPTIONAL MATCH`, `CASE`, `ORDER BY`, three parameters) | 10,000 | 43,093 B | 239.4 of 411.0 MB | 857 µs |
| the same long read with literals and no parameters | 10,000 | 44 B | 0 | 705 µs |
| `UNWIND $ids` over 1,000 integers | 4,000 | 125,506 B | 508.4 of 478.8 MB | 827 µs |
| `UNWIND $ids` over 1,000 short strings | 4,000 | 125,420 B | 507.3 of 478.4 MB | 872 µs |
| `UNWIND $rows` over 100 maps of four fields | 4,000 | 118,256 B | 495.3 of 451.1 MB | 1,147 µs |
| `RETURN size($v)` with a 768-float list | 4,000 | 97,440 B | 239.4 of 371.7 MB | 526 µs |
| `RETURN size($s)` with 1,000 ASCII characters | 20,000 | 3,666 B | 47.9 of 69.9 MB | 167 µs |
| the same with 1,000 two-byte characters | 20,000 | 4,662 B | 47.9 of 88.9 MB | 173 µs |
| a write: `CREATE (:Doc {id: $id, body: $body})` with a 1,000-character body | 20,000 | 6,914 B | 112.8 of 131.9 MB | 7,372 µs |
| one `PreparedStatement` (the keyed read), executed again | 40,000 | 11 B | 0 | 93 µs |
| close a connection and open a new one, nothing retained | 5,000 | 20 B | n/a | 1.5 µs |

What it shows:

1. **The plan dominates, and its size cannot be read off the query text.** Padding and comments
   change nothing. A 40-term expression keeps 37 times what `RETURN $x` keeps; a long read keeps 43 KB.
2. **Parameters add by size**: about 125 B per list element whatever its type, about 1.2 KB per
   four-field map (about 300 B per field), and about 1.1 to 1.8 times a string's bytes on top of the
   plan.
3. **Preparing once and executing again keeps nothing (11 B per call).** The retention is
   prepare-per-execute. See the deferred prepared-statement cache below.
4. **Closing the connection gives back most or all of it right away**: 58-100% of the growth, and
   the rest is reused, as the next section shows.

## Does recycling only the connection keep the footprint flat?

cc11b reported that closing the connection gave back nothing for 100 KB strings, while closing the
whole store gave back 15 GiB. The orchestrator ruled: keep the connection-only recycle if it stays
flat over 8 cycles, 100 KB strings included, and add a database recycle if it grows.
`/tmp/hippo-lbconn-probes/cycle_probe.py <shape> <mode>` runs 8 cycles of statements sized to keep
about 60 MB each. After every cycle, mode `none` does nothing, `conn` closes and reopens the
connection, and `db` closes the connection and the database and reopens both on the same path. One
process per run. Log: `/tmp/hippo-lbconn-cycle-probe.log`.

| Shape (statements per cycle) | Mode | Footprint growth after cycles 1..8 (MB) | Slowest recycle |
| --- | --- | --- | ---: |
| `RETURN size($s)`, 100 KB string (550) | none | +62 +124 +186 +247 +309 +371 +432 +494 | n/a |
| | conn | +62 +62 +62 +62 +66 +66 +66 +66 | 0.6 ms |
| | db | +66 +70 +70 +70 +71 +71 +71 +71 | 50.9 ms |
| `UNWIND $ids`, 1,000 integers (500) | none | +60 +120 +180 +239 +299 +359 +419 +479 | n/a |
| | conn | +12 −16 −16 −16 −16 −16 −16 −16 | 12.6 ms |
| | db | +17 −14 −14 −14 −14 −14 −14 −14 | 60.6 ms |
| the long read (1,500) | none | +62 +123 +185 +247 +308 +370 +432 +493 | n/a |
| | conn | +14 +14 +14 +14 +14 +14 +14 +14 | 25.0 ms |
| | db | +19 −7 −7 −7 −7 −7 −7 −7 | 81.2 ms |
| keyed read (13,000) | none | +61 +122 +182 +244 +304 +364 +425 +487 | n/a |
| | conn | +13 +13 +13 +13 +13 +13 +13 +13 | 35.8 ms |
| | db | +20 +20 +20 +20 +20 +20 +20 +20 | 79.5 ms |

Recycling the connection alone holds the footprint flat for every shape. For 100 KB strings, what
the first close leaves behind is reused by every later cycle, not accumulated. The database recycle
is no flatter and costs 51-81 ms a time instead of 0.6-36 ms, plus a write-ahead-log checkpoint and a
cold buffer pool. **The fix recycles the connection only** (orchestrator ruling, 2026-09-13).

**Cost per recycle: 0.6-36 ms**, growing with how much the closed connection had kept (the 36 ms
is a close that frees about 60 MB). At the default budget that is one recycle every 4,096
parameterised statements. The cheapest of those, a 125 µs keyed read, take at least 0.5 s together,
and hippo's real statements are slower.

## Calibration on hippo's own statements

`/tmp/hippo-lbconn-probes/lbconn_calibrate2.py` is a pytest plugin that turns recycling off (store
default `10**12`). It reads `phys_footprint` before each parameterised `execute` and after its result
closes, and sums the growth per query text. It ran over `tests/unit/test_code_generation.py -k publish`
on LadybugDB (`2 passed, 31 deselected in 197.64s`,
`/tmp/hippo-lbconn-calibration2-codegen-publish.log`; report
`/tmp/hippo-lbconn-calibration2-codegen-publish.txt`). Growth lands on the statement that needed
new pages, so one call's figure is noisy while a sum over many calls is not. Large result rows count
too, so the figures are upper bounds.

* 224,703 parameterised statements, 48,724 without parameters, 210 distinct shapes. The process
  footprint grew 1,339 MB across them, **6.0 KB per parameterised statement net**. The mean growth
  measured inside a statement was 19.0 KB; the mean charge under the rule below was 66.2 KB.
* Every shape with at least 200 calls kept less than the 64 KiB charge. The heaviest was
  `MATCH (s:Source) WHERE s.id = $id AND (…access…) OPTIONAL MATCH …` at 49.1 KB mean over 27,803
  calls, then a relationship count over `Source<-FROM-Passage-STATES->Fact` at 30.9 KB over 27,803,
  a `User` lookup at 26.0 KB and a `MaintenanceJob` keyed read at 23.6 KB.
* Heavier shapes are rare: a `CODE_EDGE` kind count (10 calls, 1.9 MB mean, most of it its result),
  role seeding (2 calls) and `UNWIND` reads that return passages with embeddings (48 calls, 185 KB
  mean including the rows).

So at the default, one connection's statements keep about 25 MB on the net figure (4,096 × 6.0 KB)
or about 76 MB on the in-statement mean before a recycle. If every statement were the heaviest
frequent shape, it would be 196 MB. All stay under the 256 MiB budget.

## What changed

| File | Change | Ownership |
| --- | --- | --- |
| `src/hippo/store/ladybug.py` | Module constants `STATEMENT_RETAINED_BYTES` (64 KiB), `VALUE_RETAINED_BYTES` (128), `CONNECTION_RETAINED_BUDGET_BYTES` (256 MiB), `DEFAULT_CONNECTION_RECYCLE_STATEMENTS` (their quotient, 4,096) and `parameter_retained_bytes(value)`, with the measurements in a comment (`:291-331`). `LadybugStore(path, *, buffer_pool_bytes=None, connection_recycle_statements=None)`: None means the default, and 0 or less raises `ValueError` before the directory, the lock file or the driver is touched (`:337-368`). New public attributes `connection_recycle_statements` and `connection_recycles`. `run` charges each parameterised statement before executing it and checks for a due recycle in its `finally` (`:443-476`). New `_recycle_connection_if_due` (`:482-516`). `transaction()` checks again after the outermost transaction ends (`:575`). | brief |
| `src/hippo/config.py` | Field `Config.ladybug_connection_recycle_statements` (int or None, default None), `parse_connection_recycle_statements(text)`, and `load_config` reads `HIPPO_LADYBUG_CONNECTION_RECYCLE_STATEMENTS`. | brief (one field) |
| `src/hippo/store/__init__.py` | `open_store` passes `connection_recycle_statements=config.ladybug_connection_recycle_statements`. | **orchestrator-approved addition** (`horch tell`, 2026-09-13) |
| `README.md` | One Configuration table row for the setting. | brief |
| `.env.example` | One entry: a comment line and `HIPPO_LADYBUG_CONNECTION_RECYCLE_STATEMENTS=`, after the buffer-pool entry. | brief |
| `tests/unit/test_ladybug_connection_recycle.py` | New module, 25 tests. | brief |

## The rules as shipped

* **Setting.** `HIPPO_LADYBUG_CONNECTION_RECYCLE_STATEMENTS` becomes
  `Config.ladybug_connection_recycle_statements`. It accepts a whole positive number of statements in
  ASCII digits. Empty or unset means None, which selects the default. `0`, `-1`, `1.5`, `lots`, `1e3`
  and a lone space are refused with `ValueError: HIPPO_LADYBUG_CONNECTION_RECYCLE_STATEMENTS must be
  a positive whole number of statements, not '0'`. `LadybugStore` itself refuses 0 or less.
* **Default: 4,096**, which is 256 MiB divided by a 64 KiB charge per statement. Derivation: the plan
  a statement keeps ranges from 1.8 KB to 68 KB in the probe, and hippo's frequent statements keep at
  most 49 KB (calibration above). 64 KiB therefore covers every frequent hippo statement and every
  probe shape except the synthetic 40-term expression.
* **The charge.** A statement without parameters is free, since it keeps nothing. A parameterised
  statement is charged `STATEMENT_RETAINED_BYTES + parameter_retained_bytes(params)`.
  `parameter_retained_bytes` charges 128 B per value (the parameter map, each list element, each map
  field, plus the field name's length) and a quarter on top of a string's size, with a non-ASCII
  character counted as three bytes. A list whose first element is a number or a boolean is charged
  128 B per element without being walked, since the driver's lists hold one type. Checks against the
  probe: 1,000 integers 128 KB charged against 125.5 KB kept, 768 floats 98 KB against 97 KB, 100
  four-field maps 118 KB against 118 KB.
* **When a recycle is due**: once the charges on one connection reach
  `connection_recycle_statements × 64 KiB`. That is at most `connection_recycle_statements`
  parameterised statements per connection, and fewer when their parameters are large. The failing
  statement of a failed `run` is charged too, since it was prepared.
* **Safe boundaries only.**
  1. **Under the store's lock.** `run` holds `_lock` for the statement and the check.
     `transaction()` holds it for the whole transaction body. No other thread can run a statement,
     start a transaction or close the store while a recycle happens.
  2. **Never while a result is open.** The check runs in `run`'s outer `finally`, after the inner
     `finally` has closed the `QueryResult`. `run` is the only place hippo holds one.
  3. **Never inside a transaction.** `_recycle_connection_if_due` returns while
     `_transaction_depth > 0`. The outermost `transaction()` checks again in its `finally`, after
     `COMMIT` or `ROLLBACK` and after the depth, the failure flag and the owner are reset. A recycle
     that came due inside a transaction therefore happens right after it commits or rolls back.
     Nested transactions leave it to the outer one.
  4. **After a statement that raised, outside a transaction.** The check runs there too. That is safe:
     the result is closed, no transaction is open, and the driver aborted the failed auto-commit
     statement.
  5. `BEGIN TRANSACTION`, `COMMIT` and `ROLLBACK` have no parameters, so they never trigger a check
     in `run`. `grep` at `b22d8de`: no code in `src/` issues them outside `transaction()`
     (`ladybug.py:551-565`), and nothing touches `_conn` outside `__init__`, `close`, `run` and the
     recycle itself, or `_db` outside `ladybug.py`.
* **The swap.** `lb.Connection(self._db)` opens the fresh connection *before* the stale one closes,
  so `_conn` never holds a closed connection. The counters reset, and `connection_recycles` goes up
  by one. It is the same `Database` object: same path, same `buffer_pool_size`, no second
  `ensure_schema` or migration, and nothing pending is lost, since no transaction is open.
* **Failures.** If the fresh connection cannot open, the store keeps the connection it has. It logs
  one warning for that connection, naming only the exception type, and tries again at the next
  parameterised statement outside a transaction. If closing the stale connection fails, a warning is
  logged and the store carries on with the fresh one. The statement that triggered the check has
  already succeeded, so neither failure raises to its caller.
* **Logs.** One `DEBUG` line per recycle (`recycled the LadybugDB connection after N parameterised
  statements`) and the two warnings above. None names the database path or quotes a driver message.
  hippo's logs carry neither, and the managed activation suite checks that (see the stress run below,
  which caught the first version doing both).

## Tests

`tests/unit/test_ladybug_connection_recycle.py` opens real Ladybug files under `tmp_path` whatever
`HIPPO_TEST_STORE` says. A `connections` fixture replaces `real_ladybug.Connection` with a recording
subclass that is still a real connection. `settle(store)` runs `RETURN $k` until a recycle happens,
so each test then counts from zero.

| Group | Tests |
| --- | --- |
| The setting | a statement count where unset means None; six refused values; 0 and -1 refused before the file is touched; `open_store` passes the configured value; a bare store takes the default; the default budget lies in (128 MiB, 256 MiB] |
| When a recycle happens | the third statement, not the second, recycles at threshold 3, closing the stale connection and opening a live one on the same `Database`; twenty statements without parameters never bring one closer; one statement with a 10,000-integer list recycles a threshold-10 store; across three recycles a read returns the same rows, `_db` and its pool size are unchanged and `migrate_store` is never called |
| Safe boundaries | a recycle due inside `transaction()` waits for the commit (no close inside; one recycle after; all 5 writes visible), waits for a rollback (no writes visible) and waits for the outer of two nested transactions; a due recycle waits for an open result: a reader thread's `get_next` is held on an event while a writer thread tries to write, the writer stays blocked, the stale connection stays open, and after release the order is "result closed" then "connection closed" with the reader's rows intact; a real `LeaseHeartbeat` renewing every millisecond in a transaction while the main thread runs 300 write-and-read transactions and 300 auto-commit updates at threshold 4: `heartbeat.check()` raises nothing, renewals counted equal renewals stored, 300 items, at least 100 recycles |
| Closing and failures | a recycled store closes and reopens with its data; a fresh connection that cannot open leaves the store on its connection (two failed attempts, one warning naming `RuntimeError`), and the next statement recycles once opening works; recycle logs name neither the database path nor a driver message, through recycles, a close that raises and an open that raises |
| The footprint | two fresh processes run 6,000 `RETURN size($s) + $k` statements with a 10 KB string through `open_store(load_config())` (the full env → config → store path), one with the setting at `10**12`, one at `100`; the first must grow at least 48 MiB, the second at most 24 MiB and a quarter of the first. The footprint is `phys_footprint` on macOS (`proc_pid_rusage`), `RssAnon` on Linux |

Runs:

| Run | Result | Log |
| --- | --- | --- |
| RED at `2f7c168` + the test file (24 tests) | `24 failed in 5.34s`: `TypeError` on the new keyword (13), `DID NOT RAISE ValueError` (6), missing Config field or default (3), missing attribute (1), and the footprint test: `never recycling grew 93.5 MiB (none recycles); recycling every 100 grew 93.6 MiB (none recycles)` | `/tmp/hippo-lbconn-red.log` |
| GREEN, first implementation (24 tests) | `24 passed` | `/tmp/hippo-lbconn-green-fake.log` (overwritten by the next run) |
| RED, log hygiene (the changed failed-open test and the new log test) | `2 failed, 23 deselected in 0.47s`: the path and `sk-live-secret` in `caplog.text` | `/tmp/hippo-lbconn-red-logs.log` |
| GREEN at `b22d8de`, `HIPPO_TEST_STORE=fake` | `25 passed in 12.11s` | `/tmp/hippo-lbconn-green-fake.log` |
| The footprint script outside pytest, three settings | `10**12`: +93.5 MiB, 0 recycles. `100`: +1.2 MiB, 77 recycles. Default: +0.08 MiB, 1 recycle | `/tmp/hippo-lbconn-footprint-green.txt` |

## The existing LadybugDB suites

**Stress run, every store recycling every 3 statements.**
`/tmp/hippo-lbconn-probes/lbconn_stress.py` is a pytest plugin that sets
`DEFAULT_CONNECTION_RECYCLE_STATEMENTS = 3`, so every store the suites open without a threshold
recycles about every three parameterised statements. It ran over the brief's six files with
`HIPPO_TEST_STORE=ladybug`. It found a real defect in `e2b916b`: two
`test_managed_pipeline_activation.py` tests (`test_an_unknown_failure_never_reaches_the_source_row_or_the_logs`,
`test_a_failure_that_cannot_be_presented_still_reports_nothing_private`) failed because the
recycle's debug line contained `/private/var/...hippo.lbug`. At the default threshold these tests
never recycle, so a plain run would have passed. Fixed in `b22d8de` (TDD, above). Both tests pass
under the stress plugin with the fix (`2 passed in 0.83s`, 22 recycles,
`/tmp/hippo-lbconn-stress3-single.log`). The full stress run loaded `e2b916b`: `2 failed, 206
passed, 2 skipped in 1348.45s`. Its only failures are those two tests. Across it, 198 stores
recycled 28,967 times (`/tmp/hippo-lbconn-stress3-ladybug.log`,
`/tmp/hippo-lbconn-stress3-recycles.txt`). Every other test in the brief's six files, including the
lifecycle, activation, scoped-read and migration tests, passed while its store swapped connections
about every three statements.

**Plain run at the default, `b22d8de`, no plugin.**

| Command | Result | Log |
| --- | --- | --- |
| `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_store_ladybug.py tests/unit/test_ladybug_buffer_pool.py tests/unit/test_generation_scoped_reads.py tests/unit/test_query_scoped_reads.py tests/unit/test_ladybug_connection_recycle.py -q -o addopts='' -W error` | `233 passed, 2 skipped in 1347.28s (0:22:27)`, EXIT 0 | `/tmp/hippo-lbconn-green-ladybug.log` |
| `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_code_generation.py -k publish -q -o addopts='' -W error` | `2 passed, 31 deselected in 127.02s (0:02:07)`, EXIT 0 | `/tmp/hippo-lbconn-green-ladybug-publish.log` |

The two skips are `test_generation_scoped_reads.py:673` and `:695`, whose synthetic fixtures are
built through the Fake store's tables and skip on LadybugDB. They were skipped in the stress run
too. No command needed the AnyIO filter (form (b)), and no log holds a warning.

## CC11 acceptance at N=8 on LadybugDB, before and after

**Before (orchestrator ruling: reuse cc11b's run).** cc11b ran it at `14d0a37`, whose `src/` and
`tests/` equal this base: `git diff --stat 14d0a37 2f7c168` lists only `neo4j-parity.md`. Settings:
`HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=8`, the acceptance default pool (4 GiB,
`MAX_DEFAULT_BUFFER_POOL_BYTES`), `HIPPO_CODE_ACCEPTANCE_TIMINGS` set. Runner
`/tmp/hippo-cc11b-ladybug-run.sh` (its guard-log header, with no interval field, is that script's; guard at
`unused < 4 GB`), `/usr/bin/time -l`.

**After (lbconn, `b22d8de`), started 18:13:09 once the orchestrator said "cc11b done".** Same
settings. Runner `/tmp/hippo-lbconn-ladybug-run.sh n8 8 default tests/unit/test_code_capture_acceptance.py`:
a copy of cc11b's `run3`, which has the same guard and `/usr/bin/time -l`, pointed at this worktree
and adding `-p lbconn_count` (`/tmp/hippo-lbconn-probes/lbconn_count.py`). That plugin counts
stores, parameterised statements and recycles, and at session end records
`ri_lifetime_max_phys_footprint` and `ru_maxrss`. Sampler `/tmp/hippo-lbconn-footprint2.sh` (a copy
of cc11b's) ran every 60 s. The end of the stress run shared the machine for the first 4 minutes (it
ended 18:16:56), and the plain Ladybug GREEN run shared it for the whole run. Both are separate
processes of under 1 GB each, and footprint is per process. They can only have slowed the after-run,
which still finished 27% faster.

| Measure | Before (cc11b) | After (lbconn) |
| --- | --- | --- |
| Result | `2 passed in 1615.56s (0:26:55)` | `2 passed in 1177.21s (0:19:37)` |
| Peak memory footprint (`/usr/bin/time -l`) | 16,930,459,520 B (15.8 GiB) | **1,447,364,888 B (1.35 GiB)** |
| `ri_lifetime_max_phys_footprint` (plugin) | not recorded | 1,447,364,888 B, the same figure |
| Maximum resident set size (`/usr/bin/time -l`) | 27,510,325,248 B (25.6 GiB) | **3,087,351,808 B (2.88 GiB)** |
| Sampled peak RSS (guard, 10 s) | 26,864,432 KB | 2,994,496 KB |
| Largest 60 s `phys_footprint` sample | not sampled | 996 MB (18:18:14, resumed bootstrap write batch 2) |
| Stores opened / connection recycles | 5 / none | 5 / **225**, all at the default 4,096 |
| Parameterised statements through `LadybugStore.run` | not counted | 2,134,466 |
| Knowledge reads at the end of the refresh | 628,151 | 628,151 |
| Logs | `/tmp/hippo-cc11b-ladybug-n8.log`, `-n8-guard.log`, `/tmp/hippo-cc11b-timings-ladybug-n8.json` | `/tmp/hippo-lbconn-ladybug-n8.log`, `-n8-guard.log`, `/tmp/hippo-lbconn-footprint2-n8.log`, `/tmp/hippo-lbconn-count-n8.json`, `/tmp/hippo-lbconn-timings-ladybug-n8.json` |

Phase timings from the two `.progress` files (the acceptance test asserts none of them):

| Phase | Before | After |
| --- | ---: | ---: |
| build bootstrap (crash) | 154.6 s | 152.4 s |
| reopen during staging | 2.6 s | 0.2 s |
| build bootstrap (resume) | 431.7 s | 273.6 s |
| reopen after publication | 6.3 s | 0.3 s |
| seal validation and checksums | 28.5 s | 17.9 s |
| projection, arrows and source row | 90.7 s | 60.5 s |
| verified dense dispatch | 363.7 s | 241.3 s |
| build refresh | 378.2 s | 327.6 s |
| reopen after refresh | 14.4 s | 0.4 s |

What the after-run shows:

1. **The footprint no longer tracks the work.** The samples stayed between 263 MB and 996 MB for
   the whole run, and were 763 MB at the end of the refresh, which writes the corpus a second time.
   In cc11b's N=16 run the same resumed bootstrap reached 14.0 GiB. The peak footprint fell 11.7
   times and the peak RSS 8.9 times. The run was also 27% faster, most visibly in the reopens: a
   store close no longer has to free gigabytes of small allocations.
2. **A long transaction still holds its statements until it ends.** 225 recycles at 4,096
   statements each account for at most 921,600 of the 2,134,466 parameterised statements. The rest
   ran inside transactions that went past the budget, where the rule defers the recycle to the
   commit, or in a store's last partial budget before it closed. Between transactions the budget
   bounds what one connection keeps. Inside a transaction, the transaction's own size bounds it. The
   largest sample, 996 MB during a write batch, is consistent with that. Recycling inside a
   transaction would lose its uncommitted work, so this is the brief's rule, not a gap in the
   implementation. It is recorded here in case a build ever runs one very large transaction.

## Deferred: a per-connection prepared-statement cache

The orchestrator asked whether `LadybugStore` could prepare repeated statement shapes once per
connection, since a statement prepared once keeps 11 B per execute. It then deferred that to a
follow-up (2026-09-13). What lbconn established:

* The driver exposes it publicly and without warnings: `real_ladybug.PreparedStatement(connection,
  query)` is in `__all__`, and `Connection.execute(prepared, parameters)` takes it. The separate
  `Connection.prepare` is the one that emits a `DeprecationWarning`.
* A prepared statement answered like a fresh `execute` in all 43 calls of 11 sequences whose
  parameter types changed from call to call: int, string, None, float, list, map, datetime and
  boolean in turn, empty lists, map rows with `None` fields, `IN` lists, `SET` values, comparisons
  (`/tmp/hippo-lbconn-probes/prepared_safety_probe.py`, one process per sequence via
  `prepared_safety_each.py`, `/tmp/hippo-lbconn-prepared-safety.log`).
* **Unverified, for the follow-up:** (1) whether a cached plan stays correct after DDL, since
  migrations `ALTER` tables; (2) whether a failed execute leaves the prepared statement usable; (3)
  the cache bound, given 210 distinct shapes in one publish test, plans of up to about 50 KB, and a
  per-connection cache that must be dropped at every recycle.
* **A separate driver crash** turned up: a plain parameterised `WHERE n.v IN $vs` with `vs=None`
  kills the process with SIGSEGV (exit 139), with no prepared statement involved
  (`/tmp/hippo-lbconn-probes/in_none_segfault.py`, `/tmp/hippo-lbconn-in-none-segfault.out`).
  hippo's `IN` parameters today are built lists. The follow-up should check that `None` can never
  reach one.

## Draft upstream issue for real_ladybug (not filed)

> **Title:** `Connection.execute(query, parameters)` keeps every prepared statement until the
> connection closes (unbounded memory in long-lived connections)
>
> **Versions:** real_ladybug 0.15.3 (wheel `_lbug.cpython-312-darwin.so`), CPython 3.12.11, macOS
> 26.5.1 (Darwin 25.5.0, arm64).
>
> **What happens.** Every `Connection.execute(query, parameters)` with a non-empty `parameters`
> prepares a statement (`connection.py:127-139`), and the memory it uses stays allocated until the
> `Connection` closes. `gc.collect()` releases none of it, and `QueryResult.close()` does not help.
> A long-lived connection that runs parameterised statements grows without limit. In our application,
> one connection grew by about 2 GB a minute during a bulk build and reached a 15.8 GiB footprint
> with a 96 MB database. Closing and reopening the `Connection` releases the memory, which is our
> workaround.
>
> **How much**, `phys_footprint` growth per call, fresh process per case: `RETURN $x AS x` 1.8 KB;
> `MATCH (n:Item {id: $id}) RETURN n.id, n.v` 4.9 KB; a read with `OPTIONAL MATCH`, `CASE` and
> `ORDER BY` 43 KB; `RETURN $x + 1 + … + 40 AS x` 68 KB. Whitespace or comments in the query text
> change nothing, so the size follows the plan. Parameters add about 125 B per list element, about
> 300 B per map field and about 1.1-1.8 times a string's bytes. The same statement without
> parameters (literals in the text) keeps 44 B. A `PreparedStatement` created once and passed to
> `execute` 40,000 times keeps 11 B per call.
>
> **Repro** (prints peak RSS growth; `ru_maxrss` only rises, so a flat line means nothing new was
> kept):
>
> ```python
> import resource
> import sys
> import tempfile
> from pathlib import Path
>
> import real_ladybug as lb
>
>
> def peak_mib() -> float:
>     peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
>     return peak / 2**20 if sys.platform == "darwin" else peak / 2**10
>
>
> def drain(result) -> None:
>     while result.has_next():
>         result.get_next()
>     result.close()
>
>
> def measure(label: str, call, n: int = 40_000) -> None:
>     before = peak_mib()
>     for k in range(n):
>         drain(call(k))
>     print(f"{label:45s} peak RSS +{peak_mib() - before:6.1f} MiB over {n} calls")
>
>
> db = lb.Database(str(Path(tempfile.mkdtemp()) / "repro.lbug"), buffer_pool_size=256 * 2**20)
> conn = lb.Connection(db)
> measure("literal query, no parameters", lambda k: conn.execute(f"RETURN {k} AS x"))
> prepared = lb.PreparedStatement(conn, "RETURN $x AS x")
> measure("one PreparedStatement, executed again", lambda k: conn.execute(prepared, {"x": k}))
> measure("execute(query, parameters)", lambda k: conn.execute("RETURN $x AS x", {"x": k}))
> measure(
>     "execute(query, parameters), 40-term expression",
>     lambda k: conn.execute("RETURN $x " + "+ 1 " * 40 + "AS x", {"x": k}),
>     n=5_000,
> )
> conn.close()
> conn = lb.Connection(db)
> measure("execute(query, parameters) on a new connection", lambda k: conn.execute("RETURN $x AS x", {"x": k}))
> ```
>
> Output on the machine above (`/tmp/hippo-lbconn-upstream-repro.out`; the first line includes
> first-call warm-up):
>
> ```text
> literal query, no parameters                  peak RSS +   7.2 MiB over 40000 calls
> one PreparedStatement, executed again         peak RSS +   0.4 MiB over 40000 calls
> execute(query, parameters)                    peak RSS +  68.1 MiB over 40000 calls
> execute(query, parameters), 40-term expression peak RSS + 349.8 MiB over 5000 calls
> execute(query, parameters) on a new connection peak RSS +   0.0 MiB over 40000 calls
> ```
>
> **Expected:** a statement prepared implicitly by `execute(query, parameters)` is released when
> its `QueryResult` is closed, or at least when it is collected, rather than living as long as the
> connection.
>
> **Also found:** a parameterised `IN` with a `None` parameter crashes the process:
>
> ```python
> import tempfile
> from pathlib import Path
>
> import real_ladybug as lb
>
> db = lb.Database(str(Path(tempfile.mkdtemp()) / "s.lbug"), buffer_pool_size=64 * 2**20)
> conn = lb.Connection(db)
> conn.execute("CREATE NODE TABLE Item(id STRING, v INT64, PRIMARY KEY(id))")
> conn.execute("CREATE (:Item {id: 'i1', v: 1})")
> print(conn.execute("MATCH (n:Item) WHERE n.v IN $vs RETURN count(n)", {"vs": [1]}).get_next())  # [1]
> conn.execute("MATCH (n:Item) WHERE n.v IN $vs RETURN count(n)", {"vs": None})  # SIGSEGV, exit 139
> ```

## Ruff

Ruff 0.16.6 (the worktree venv had 0.16.7, so it was pinned with `uv pip install 'ruff==0.16.6'`,
`/tmp/hippo-lbconn-ruff-pin.log`), over `src/hippo/store/ladybug.py`, `src/hippo/store/__init__.py`,
`src/hippo/config.py`, `tests/unit/test_ladybug_connection_recycle.py` and this document: `ruff check`
gives `All checks passed!`, and `ruff format --check` gives `5 files already formatted`, EXIT 0
(`/tmp/hippo-lbconn-ruff.log`).

## Commits

| Commit | Subject |
| --- | --- |
| `e2b916b` | Recycle the LadybugDB connection before the driver's per-statement memory passes a budget |
| `b22d8de` | Keep the database path and driver messages out of the connection recycle logs |
