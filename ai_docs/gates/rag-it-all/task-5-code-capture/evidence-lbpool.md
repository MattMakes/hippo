# LBPOOL evidence — every LadybugDB store opens with a bounded buffer pool

Branch `wp/lbpool`, worktree `.worktrees/lbpool`, base `df05bac` (the KSCOPE merge).
Not a plan slice: the follow-up CC11 named after finding LadybugDB's default buffer pool behind the
CD9 acceptance run's climbing RSS (`caae8ba` and `c851c2a` on `wp/cc11`).

## The driver contract, read rather than guessed

`.venv/lib/python3.12/site-packages/real_ladybug/database.py`, real_ladybug 0.15.3:

```text
def __init__(self, database_path=None, *, buffer_pool_size: int = 0, max_num_threads: int = 0, ...)

    buffer_pool_size : int
        The maximum size of buffer pool in bytes. Defaults to ~80% of system memory.
```

This matches the docstring CC11 quoted, so no BLOCKED was needed on the signature. `init_database`
hands `self.buffer_pool_size` to `_lbug.Database`, and the Python object keeps the value as
`Database.buffer_pool_size`, which the tests read back.

At the base, `src/hippo/store/ladybug.py:270` opened `lb.Database(str(self.path))`, so the pool
limit was 0, meaning about 80% of memory. The RED run showed this on the dev machine (128 GiB): a
clean process that opens `LadybugStore(path)` prints `buffer_pool_size` as `0`, and a store opened
in a test body reads back `0`.

## What changed

| File | Change | Ownership |
| --- | --- | --- |
| `src/hippo/store/ladybug.py` | `LadybugStore(path, *, buffer_pool_bytes=None)`. None means `default_buffer_pool_bytes()`. A value of 0 or less raises `ValueError` before the directory, the lock file or the driver is touched. The open is now `lb.Database(str(self.path), buffer_pool_size=self.buffer_pool_bytes)`, which is the only `Database` open in `src/`. New module-level `MAX_DEFAULT_BUFFER_POOL_BYTES` (4 GiB), `physical_memory_bytes()`, `bounded_buffer_pool_bytes(physical_bytes)`, `default_buffer_pool_bytes()`, and `import os`. | brief (the open call) |
| `src/hippo/config.py` | Field `Config.ladybug_buffer_pool_bytes` (int or None, default None), `parse_buffer_pool_bytes(text)`, and `load_config` reads `HIPPO_LADYBUG_BUFFER_POOL_BYTES`. | brief (one field) |
| `src/hippo/store/__init__.py` | `open_store` passes `buffer_pool_bytes=config.ladybug_buffer_pool_bytes`. | **orchestrator-approved addition 1** |
| `tests/conftest.py` | The `store` fixture passes `buffer_pool_bytes=LADYBUG_TEST_BUFFER_POOL_BYTES` (256 MiB). A new autouse fixture, `ladybug_buffer_pool_cap`, monkeypatches `hippo.store.ladybug.default_buffer_pool_bytes` to return 256 MiB. | fixture: brief; autouse: **orchestrator-approved addition 2** |
| `README.md` | A Configuration table row for `HIPPO_LADYBUG_BUFFER_POOL_BYTES`. | brief (the settings documentation line) |
| `.env.example` | A commented `HIPPO_LADYBUG_BUFFER_POOL_BYTES=` entry beside `HIPPO_DB_PATH`. | **orchestrator-approved addition 3** |
| `tests/unit/test_ladybug_buffer_pool.py` | New module with 23 tests. | brief |

The orchestrator approved all three additions in writing (`horch tell`, 2026-09-13), and also asked
for a test proving the cap never overrides an explicit value
(`test_the_pytest_cap_never_overrides_an_explicit_size`).

## The rules as shipped

* **Setting.** `HIPPO_LADYBUG_BUFFER_POOL_BYTES` becomes `Config.ladybug_buffer_pool_bytes`. It
  accepts a whole positive byte count in ASCII digits. An empty or unset value means None, which
  selects the default. `0`, `-1`, `1.5`, `lots`, `4GiB` and a lone space are refused with
  `ValueError: HIPPO_LADYBUG_BUFFER_POOL_BYTES must be a positive number of bytes, not '0'`.
* **Production default**, worked out once per open: `min(physical memory // 4, 4 GiB)`, where
  physical memory is `os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")`. When the OS won't
  report it (no `os.sysconf`, as on Windows, or an error, or a non-positive answer), the default is
  the 4 GiB cap. On the 128 GiB dev machine the default is now 4 GiB; before, it was about 80% of
  memory.
* **Precedence.** An explicit `buffer_pool_bytes=` or a Config value always wins over the default.
  `open_store(Config(ladybug_buffer_pool_bytes=0))` is refused through the same `LadybugStore` check.
* **Pytest cap.** Every store opened under pytest without a size gets 256 MiB. That includes the
  bare `LadybugStore(path)` reopen calls in test bodies (lifecycle, activation, migrations,
  inventory and others) and `open_store(Config())`. An explicit size still wins.
* **What the cap does not reach.**
  * Ladybug files opened by child processes that a test spawns get the production default, bounded
    at 4 GiB, because conftest does not run in those processes.
  * Direct `real_ladybug.Database` calls in test files bypass the store:
    * `tests/unit/test_rag_store_capabilities.py`, twice, already passes 64 MiB.
    * `tests/unit/test_store_migrations.py:225` opens `lb.Database(str(path))` with no size. It is a
      short read-back of one row; the file is not owned here and was left as it is.

## Tests in `tests/unit/test_ladybug_buffer_pool.py`

A spy fixture (`opens`) replaces `real_ladybug.Database` with a function that records the keyword
arguments and then delegates to the real class. Every open therefore still really happens.

| Group | Tests |
| --- | --- |
| The size reaching the driver | explicit `192 MiB` reaches `buffer_pool_size`; a store opened without a size passes whatever `default_buffer_pool_bytes()` returns (`160 MiB` patched in); `0` and `-1` are refused with no driver call and no directory created; `open_store` passes a Config value (`144 MiB`); `open_store` refuses a Config `0` |
| The default rule | 1 GiB→256 MiB, 8 GiB→2 GiB, 16 GiB→4 GiB and 128 GiB→4 GiB; with `os.sysconf` unavailable, `physical_memory_bytes()` is None and the rule gives 4 GiB; a clean child process (no conftest) opens `LadybugStore(path)` with exactly `min(sysconf memory // 4, 4 GiB)` |
| The setting | unset means None and `536870912` is read as 512 MiB; `0`, `-1`, `1.5`, `lots`, `4GiB` and a space are refused with a message naming the variable |
| The pytest cap | the `store` fixture's database is 256 MiB (skipped off Ladybug); a store opened in a test body is 256 MiB; the cap never overrides an explicit keyword (1 GiB) or a Config value (512 MiB) |
| A real build on a small pool | a managed prose build (`hippo.ingest.prose_generation.build_plain_source`, reusing `Runtime` and `build` from `tests/unit/test_prose_generation.py`) on a 128 MiB store publishes, the generation seal validates, and the original citation is served |

The module does not import `fastapi.testclient`, so no anyio warning filter was used anywhere in this
evidence: every command below is plain `-W error`.

## RED and GREEN

| Run | Command | Result | Log |
| --- | --- | --- | --- |
| RED | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_ladybug_buffer_pool.py -q -o addopts='' -W error` | 22 failed, 1 skipped | `/tmp/hippo-lbpool-red.log` |
| GREEN Fake | same | **22 passed, 1 skipped** (the `store`-fixture cap test skips off Ladybug) | `/tmp/hippo-lbpool-green-fake.log` |
| GREEN Ladybug | `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_ladybug_buffer_pool.py tests/unit/test_store_ladybug.py -q -o addopts='' -W error` | **170 passed**, exit 0 (the `store`-fixture cap test runs here rather than skipping) | `/tmp/hippo-lbpool-green-ladybug.log` |

Every RED failure came from the missing feature:

* 5: `LadybugStore.__init__() got an unexpected keyword argument 'buffer_pool_bytes'`.
* 2: Config had no `ladybug_buffer_pool_bytes`.
* 6: the module had no `bounded_buffer_pool_bytes`, `default_buffer_pool_bytes` or `os`.
* 6: `DID NOT RAISE` (`load_config` ignored the variable).
* 1: `assert 0 == 4294967296` (the clean process's driver got 0).
* 1: `assert 0 == 268435456` (a store opened in a test body got 0).

`test_store_ladybug.py` is not named in the brief. It was added to the Ladybug line because it
tests `open_store` and `load_config`, which this change touches.

Ruff: `ruff check` and `ruff format --check` are clean on `src/hippo/config.py`,
`src/hippo/store/ladybug.py`, `src/hippo/store/__init__.py`, `tests/conftest.py` and
`tests/unit/test_ladybug_buffer_pool.py`. This document has no Python fences.

## RSS of one Ladybug test module, before and after

The measuring tool is `/usr/bin/time -l` (macOS), which gives the process's maximum resident set
size; it replaces the brief's example of `ps`. The command is
`HIPPO_TEST_STORE=ladybug /usr/bin/time -l .venv/bin/pytest tests/unit/test_managed_source_lifecycle.py -q -o addopts='' -W error`.

| Run | Tests | Maximum resident set size | Peak memory footprint | Log |
| --- | --- | --- | --- | --- |
| Before: base `df05bac` in this worktree, taken before any edit | 30 passed | 874,250,240 B (about 834 MiB) | 767,198,384 B | `/tmp/hippo-lbpool-rss-before.log` |
| After: the 256 MiB cap | 30 passed | 693,813,248 B (about 662 MiB) | 549,897,224 B | `/tmp/hippo-lbpool-rss-after.log` |

That is about 172 MiB less peak RSS for this module. The module opens many small, short-lived
stores, so it cannot show the cap's main effect, which is on one long-lived store (the CD9
scenario). CD9 was not run: `tests/unit/test_code_capture_acceptance.py` exists only on `wp/cc11`
and is not merged at `df05bac`. The "after" run shared the machine with another Ladybug pytest
process; peak RSS is measured per process, so the numbers are unaffected.

## Finding: the pool has a floor

A throwaway probe reran the body of `test_a_managed_prose_build_publishes_on_a_small_pool` at other
sizes, using resolved temporary directories:

| Pool | Result |
| --- | --- |
| 64, 72 and 80 MiB | `RuntimeError: Buffer manager exception: Unable to allocate memory! The buffer pool is full and no memory could be freed!` |
| 96, 128 and 256 MiB | the build publishes |

At 64 MiB the traceback runs `get_source` → `_source_counts` → `run` → `Connection.execute`. That
happens in the setup, after the schema, the roles, one user and one source exist and before the
build starts. So a fresh hippo schema alone needs roughly 80–96 MiB of pool on real_ladybug 0.15.3.

Consequences:

* The small-pool test uses 128 MiB. The spy tests use at least 144 MiB, so schema growth won't turn
  them red.
* As the brief asks, the setting refuses only 0 or less. An explicit value below the floor (under
  about 96 MiB today) opens the store and then fails at the first read with the engine message
  above. Whether hippo should refuse a minimum is a contract decision, and that minimum would move
  with the schema. It was not done here.
* **Open risk for CD9.** The message says pages could not be freed, so a workload that pins more
  pages than the pool holds fails; it does not grow the pool. Under pytest, CD9 will now run at the
  256 MiB autouse cap unless it passes its own size. CC11's acceptance test must be run at its
  committed size with this change merged. If it hits the floor, it should pass
  `buffer_pool_bytes=` (or set `Config.ladybug_buffer_pool_bytes`) explicitly; the cap is designed
  to give way to that. For production, the same run is the evidence that 4 GiB is enough for a
  large capture.

## Noticed, outside scope

* `docker-compose.yml` passes the app an explicit environment list, and it does not include this
  setting (nor `HIPPO_DB_PATH`, `HIPPO_MAX_UPLOAD_BYTES` and others). In the container the default
  rule applies. On Linux, `os.sysconf` reports the memory of the host or VM, not a cgroup limit.
