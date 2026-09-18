# CDK n1-fix evidence: a swallowed refusal outranks a later ordinary exception

Worker `backend-developer-20`, branch `wp/n1-fix`, base `0f965c0` (the `rag-it-all-tibs` HEAD named in
the spawn message). Contract: finding N1 in section 5 of
`ai_docs/reports/2026-09-16-cdk-r7-confirmation.md`, ruling R82 in `ai_docs/plans/cdk-rulings.md`,
and the brief `ai_docs/handoffs/briefs/cdk-n1-fix.md`. The report was read from the root tree,
because at `0f965c0` it was still uncommitted. `rag-it-all-tibs` has since moved to `57171f4`
through two commits that touch only that report and the Status line of `GATES.md`, so the CK3 and
CK4 CHECK lines are the same at both revisions.

Closed here: **N1.** Nested guards are unchanged, as R82 and the report's note 1 require.

## Commits

| # | Hash | What | Files |
| --- | --- | --- | --- |
| 1 | `6952b41` | N1: the fix and its three tests | `src/hippo/connectors/guard.py`, `tests/unit/test_connector_guard.py`, `tests/unit/test_connector_sync.py`, `tests/unit/test_connector_testing_kit.py` |
| 2 | (this commit) | evidence | this file |

## The fix

In `forbid_effects`, the `propagating` flag is gone. The guard now remembers the exception in flight
(`except BaseException as error: in_flight = error; raise`). In the `finally`, it raises
`EmitSideEffect(swallowed) from in_flight` whenever a refusal was recorded and `in_flight` is neither
an `EmitSideEffect` nor a `KeyboardInterrupt`/`SystemExit`. When nothing is in flight, the result is
the same as before: the refusal is raised with no cause. The module docstring and the
`forbid_effects` docstring now say that the refusal outranks an ordinary exception.

The two existing tests the brief names were not edited (the diff of `test_connector_guard.py` only
adds lines), and they pass unchanged:
`::test_an_unrelated_failure_inside_the_guard_still_propagates` and
`::test_a_propagating_violation_is_not_raised_a_second_time_on_the_way_out`.

## The three new tests

| File | Test | What it pins |
| --- | --- | --- |
| `tests/unit/test_connector_guard.py` | `::test_a_swallowed_refusal_outranks_a_later_ordinary_failure` | the `EmitSideEffect` is raised, it names `time.time`, its `__cause__` is the body's `ValueError`, and the profiler is removed |
| `tests/unit/test_connector_sync.py` | `::test_the_failure_matrix[M10c]` with helper `_SwallowThenRaiseConnector` | for revision `n2`, `emit` makes one `Ollama.embed` call, swallows the refusal with `except BaseException`, then raises `ValueError`. The sync raises `ConnectorContractViolation` naming `Ollama.embed`, no `Generation` is written, the connector saw exactly one `EmitSideEffect`, and its own recording transport received no request |
| `tests/unit/test_connector_testing_kit.py` | `::test_a_swallowed_refusal_followed_by_an_ordinary_raise_is_reported_as_emit_pure` with helper `_SwallowsTheRefusalThenFails` | `assert_emit_pure` raises `ContractViolation` with `assertion == "emit_pure"` (it used to be `emit_deterministic`), the message names `Ollama.embed`, and the transport received no request |

The `[M10c]` connector deliberately makes a single model call, without a retry. In the reviewer's
case A, the retry runs after CPython has unset the profiler, so it reaches the transport, and this
fix cannot change that (it is the gap F1 already describes). With a retry, the row could not also
assert that the refused request never reached the transport. The kit test is a standalone test, not
a second `VIOLATIONS` entry, because `test_every_assertion_has_exactly_one_negative_fixture` allows
exactly one fixture per assertion.

## RED (before the fix)

Command, run from `.worktrees/n1-fix` with the three tests written and `guard.py` untouched:

```text
HIPPO_TEST_STORE=fake .venv/bin/pytest \
  "tests/unit/test_connector_guard.py::test_a_swallowed_refusal_outranks_a_later_ordinary_failure" \
  "tests/unit/test_connector_sync.py::test_the_failure_matrix[M10c]" \
  "tests/unit/test_connector_testing_kit.py::test_a_swallowed_refusal_followed_by_an_ordinary_raise_is_reported_as_emit_pure" \
  -q -o addopts='' -W error
HIPPO_TEST_STORE=ladybug .venv/bin/pytest "tests/unit/test_connector_sync.py::test_the_failure_matrix[M10c]" \
  -q -o addopts='' -W error
```

Log `/tmp/hippo-n1-fix-red.log`: Fake **exit 1, 3 failed**, LadybugDB **exit 1, 1 failed**. Each
failure is the one N1 predicts: the guard lets the `ValueError` escape, the sync publishes
(`DID NOT RAISE ConnectorContractViolation`), and the kit reports `emit_deterministic`. The failure
lines and summaries, verbatim:

```text
== fake: (the three tests above)
FFF                                                                      [100%]
>               raise ValueError("the connector's own parse failure")
E               ValueError: the connector's own parse failure
tests/unit/test_connector_guard.py:488: ValueError
>       with pytest.raises(sync.ConnectorContractViolation, match=r"Ollama\.embed;"):
E       Failed: DID NOT RAISE ConnectorContractViolation
tests/unit/test_connector_sync.py:811: Failed
>       assert caught.value.assertion == "emit_pure"
E       AssertionError: assert 'emit_deterministic' == 'emit_pure'
E         - emit_pure
E         + emit_deterministic
tests/unit/test_connector_testing_kit.py:915: AssertionError
FAILED tests/unit/test_connector_guard.py::test_a_swallowed_refusal_outranks_a_later_ordinary_failure
FAILED tests/unit/test_connector_sync.py::test_the_failure_matrix[M10c] - Fai...
FAILED tests/unit/test_connector_testing_kit.py::test_a_swallowed_refusal_followed_by_an_ordinary_raise_is_reported_as_emit_pure
3 failed in 0.42s
EXIT 1
== ladybug: [M10c]
F                                                                        [100%]
>       with pytest.raises(sync.ConnectorContractViolation, match=r"Ollama\.embed;"):
E       Failed: DID NOT RAISE ConnectorContractViolation
tests/unit/test_connector_sync.py:811: Failed
FAILED tests/unit/test_connector_sync.py::test_the_failure_matrix[M10c] - Fai...
1 failed in 3.86s
EXIT 1
```

## GREEN (after the fix)

The same selection, plus the two existing guard tests the brief names. Log
`/tmp/hippo-n1-fix-green.log`, verbatim:

```text
0f965c0
(working tree: fix applied, uncommitted)
== fake: tests/unit/test_connector_guard.py::test_a_swallowed_refusal_outranks_a_later_ordinary_failure tests/unit/test_connector_guard.py::test_an_unrelated_failure_inside_the_guard_still_propagates tests/unit/test_connector_guard.py::test_a_propagating_violation_is_not_raised_a_second_time_on_the_way_out tests/unit/test_connector_sync.py::test_the_failure_matrix[M10c] tests/unit/test_connector_testing_kit.py::test_a_swallowed_refusal_followed_by_an_ordinary_raise_is_reported_as_emit_pure
.....                                                                    [100%]
5 passed in 0.16s
EXIT 0
== ladybug: [M10c]
.                                                                        [100%]
1 passed in 0.99s
EXIT 0
```

## Gate lines

These ran on the working tree that became `6952b41` (the committed files are byte-identical to it),
one pytest process at a time, with no Neo4j. No warning filter was needed: none of these runs used
form (a) or form (b) of the anyio exception.

| Run | Command | Log | Result |
| --- | --- | --- | --- |
| CK3, Fake | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_sync.py tests/unit/test_connector_http.py tests/unit/test_staged_records.py tests/unit/test_connector_credentials.py tests/unit/test_connector_guard.py tests/unit/test_generation_profiles.py tests/unit/test_build_authority.py tests/unit/test_build_run.py -q -o addopts='' -W error` | `/tmp/hippo-n1-fix-gates-ck3-fake.log` | exit 0, **310 passed, 2 skipped** |
| CK3, LadybugDB | `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_connector_sync.py tests/unit/test_staged_records.py tests/unit/test_generation_profiles.py -q -o addopts='' -W error` | `/tmp/hippo-n1-fix-gates-ck3-ladybug.log` | exit 0, **115 passed** |
| CK4, Fake | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_testing_kit.py tests/unit/test_connector_scaffold.py tests/unit/test_cli_connector.py tests/unit/test_connector_loader.py -q -o addopts='' -W error` | `/tmp/hippo-n1-fix-gates-ck4-fake.log` | exit 0, **168 passed** |
| Exemplar, Fake | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_exemplar.py -q -o addopts='' -W error` | `/tmp/hippo-n1-fix-gates-exemplar-fake.log` | exit 0, **21 passed** |
| Exemplar, LadybugDB | `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_connector_exemplar.py -q -o addopts='' -W error` | `/tmp/hippo-n1-fix-gates-exemplar-ladybug.log` | exit 0, **21 passed** |

The CK3 line is two commands joined by `&&` in `GATES.md`. They were run one after the other with
separate logs, and both exited 0. CK4 names only Fake. The brief names no backend for the exemplar
file, so it ran on both. A collection run (`/tmp/hippo-n1-fix-collect.log`, exit 0, 194 collected
across the three edited test files) shows that all three new tests are collected by these gate files.

## Ruff

```text
.venv/bin/ruff check src/hippo/connectors/guard.py tests/unit/test_connector_guard.py tests/unit/test_connector_sync.py tests/unit/test_connector_testing_kit.py
All checks passed!                      (exit 0)
.venv/bin/ruff format --check src/hippo/connectors/guard.py tests/unit/test_connector_guard.py tests/unit/test_connector_sync.py tests/unit/test_connector_testing_kit.py
4 files already formatted               (exit 0)
```

This file is also checked with `ruff format --check` (its fences are `text`, so it has no Python
blocks to format). The result is recorded in the DONE report.

## Scratch probes (not in the repo)

- The reviewer's `/tmp/hippo-confirm-probe-residual.py`, rerun against the fix
  (`/tmp/hippo-n1-fix-probe-residual.log`, exit 0). Case A now raises `EmitSideEffect` (it was
  `ValueError` in `/tmp/hippo-confirm-probe-residual.log`). Its one provider request is still there,
  because that request comes from the probe's retry, which runs unguarded (F1's known gap, unchanged
  and out of scope). Cases B and C are byte-identical to the reviewer's log, so nested guards behave
  exactly as before.
- `/tmp/hippo-n1-fix-probe-exclusions.py` (`/tmp/hippo-n1-fix-probe-exclusions.log`, exit 0) covers
  the exclusions the three tests do not pin. After a swallowed refusal, an in-flight
  `KeyboardInterrupt` or `SystemExit` propagates as the same object, with no cause. `ValueError`,
  `RuntimeError` and `StopIteration` each become `EmitSideEffect` with that exception as the cause.
  With nothing in flight, the refusal is raised with no cause and no context, as before. The
  profiler is `None` afterwards in every case.

## Scope

```text
git diff --stat 0f965c0 6952b41
 src/hippo/connectors/guard.py            | 20 ++++++++++----
 tests/unit/test_connector_guard.py       | 20 ++++++++++++++
 tests/unit/test_connector_sync.py        | 47 ++++++++++++++++++++++++++++++++
 tests/unit/test_connector_testing_kit.py | 43 ++++++++++++++++++++++++++++-
 4 files changed, 124 insertions(+), 6 deletions(-)
```

Together with this file, that makes five paths: the four above and
`ai_docs/gates/rag-it-all/cdk/evidence-n1-fix.md`. The DONE report records
`git diff --name-only 0f965c0 HEAD` after the evidence commit. The changes to
`test_connector_sync.py` are the `[M10c]` row, its `_MATRIX` entry and the
`_SwallowThenRaiseConnector` helper. No golden, lock, guide, scaffold output, `sync.py`,
`testing.py`, ledger, ruling or `GATES.md` changed.

## Open items and deviations

- None from the brief.
- Not pinned by a repo test: the `KeyboardInterrupt`/`SystemExit` exclusion (the brief asks for
  exactly three tests). It is shown only by the scratch probe above. A later slice could add a
  guard test for it.
