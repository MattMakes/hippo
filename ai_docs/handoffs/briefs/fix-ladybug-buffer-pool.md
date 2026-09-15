# Brief: bound LadybugDB's buffer pool (production default and test cap)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `lbpool` (branch `wp/lbpool`, base = the `rag-it-all-tibs` HEAD named in the spawn message).

GOAL: Every embedded LadybugDB store hippo opens has an explicit, configured `buffer_pool_size`, with a bounded production default and a small cap under pytest, so a single store can no longer claim ~80% of system memory. Found by CC11 (`evidence-cc11.md` finding): `src/hippo/store/ladybug.py:~270` opens `lb.Database(str(self.path))` with no `buffer_pool_size`, and real_ladybug 0.15.3's `Database(buffer_pool_size=0)` means "~80% of system memory" per its own docstring (~100 GB on the dev machine), which explains the acceptance run's RSS climbing ~1 GB/min and an earlier OS memory kill. Committed on `wp/lbpool`.

CONTEXT: `src/hippo/store/ladybug.py` (the `Database` open, any second open path such as snapshots/reopen), the settings module hippo already uses for store configuration (find how `HIPPO_*` store settings reach `LadybugStore`; add `ladybug_buffer_pool_bytes` beside them, env `HIPPO_LADYBUG_BUFFER_POOL_BYTES`), `tests/conftest.py` (the `store` fixture that builds the Ladybug store per test: cap it), `docs/CONTRACTS.md` or the settings documentation if there is a settings table, real_ladybug 0.15.3's `Database` signature (`.venv/lib/python3.12/site-packages/real_ladybug/...`; read the docstring, do not guess). Rules: never touch `data/`, `.rag-dev-data/`, the dev server on port 8011; no time-based sizing.

REQUIRED BEHAVIOR:
1. `LadybugStore` passes `buffer_pool_size=<configured bytes>` on every `Database(...)` open. Production default: a bounded value derived once at open time as `min(25% of physical memory, 4 GiB)` unless the setting overrides it; document the rule where settings are documented. The setting must accept an explicit byte count and refuse zero or negative (zero would silently mean "80% of memory" again).
2. Under pytest, the `store` fixture (and any helper that opens a Ladybug path in tests) caps the pool at 256 MiB unless a test sets the setting explicitly; every existing Ladybug test still passes with that cap (run the lifecycle and pipeline-activation files to prove it, and CC11's acceptance test at its committed size if it is merged by the time you start).
3. A unit test proves the argument reaches the driver (monkeypatch `lb.Database` and assert the kwarg) for the default, an override, and the refusal of zero; a Ladybug test opens a store with a small pool and performs a managed prose build to show it still works.
4. Record the measured RSS of one Ladybug test module before and after the cap in the evidence (a rough number from `ps`, no time claims).

FILES:
  - own: `src/hippo/store/ladybug.py` (the open calls only), the settings module (one field), `tests/conftest.py` (the Ladybug fixture only), NEW `tests/unit/test_ladybug_buffer_pool.py`, the settings documentation line, NEW `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-lbpool.md`.
  - do NOT touch: anything else (CC11 is live on the acceptance test, fixtures, the code-capture plan and evidence; never `GATES.md`).

STEPS: worktree + venv (`mcp==2.1.1` pin); read the driver's `Database` docstring; RED (the kwarg is absent); implement; GREEN Fake for the unit test; GREEN Ladybug on `tests/unit/test_managed_source_lifecycle.py tests/unit/test_managed_pipeline_activation.py tests/unit/test_ladybug_buffer_pool.py`; Ruff; evidence; one or two commits.

DONE WHEN: green; the default rule documented; evidence written with the RSS numbers; `horch done` lists the setting name, the default rule, the test cap and logs.

REPORT: `horch note` per step; `horch tell orchestrator "[<role>] BLOCKED: ..."` if the driver's signature differs from the docstring CC11 quoted.
