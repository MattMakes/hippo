# CK7: independent confirmation that r7-fix closed the review's code findings

**Reviewer:** `architect-reviewer-4` (herdr fleet). **Revision:** `ce653d3` on `rag-it-all-tibs`,
root tree, read-only apart from this file. `git diff 7c8f132 HEAD -- src tests` is empty, so every
result below is also a result for the merge. **Date:** 2026-09-16. **Brief:**
`ai_docs/handoffs/briefs/review-cdk-r7-fix.md`.

**Verdict: CK7's review findings F1, F2, F3, F5, F10, F11, F14 (test half) and F15 are CLOSED.**
Each fix matches the "exact fix" column of `ai_docs/reports/2026-09-15-cdk-code-review.md`
section 9, and each new test fails when its fix is undone in-process. Both standing rules of CK7's
CRITERIA are enforced by tests at this HEAD. This review adds one new MINOR finding, **N1**
(section 5). It sits next to F1 and does not reopen it: a refusal the connector swallows is thrown
away if `emit` then raises an ordinary error. The sync then publishes and counts the revision as a
parse failure. The exact fix is in section 5.

## 1 What was read and what was run

I read the eight findings and sections 6.1, 6.2 and 9 of the CK7 review, `evidence-r7-fix.md`,
and `git diff c863e03 HEAD`: 23 files, 8 of them under `src` and 6 under `tests`. I also read the
guard, the emit loop, `assert_emit_pure`, `keys.canonical_key` and the new tests in full.

All runs used `-W error` and form (a); no line needed the `anyio` filter. No run used Neo4j. My runs
were sequential, apart from one early overlap whose runs I then repeated one at a time. I also sent
one mistaken `kill`. Section 7 records both.

| Line | Exit | Result | Log |
| --- | --- | --- | --- |
| CK1 Fake, verbatim | 0 | 305 passed, 9 skipped | `/tmp/hippo-confirm-ck1-fake.log` |
| CK1 LadybugDB, verbatim | 0 | 174 passed | `/tmp/hippo-confirm-ck1-ladybug.log` |
| CK2 Fake, verbatim | 0 | 294 passed | `/tmp/hippo-confirm-ck2-fake.log` |
| CK3 Fake, verbatim | 0 | 308 passed, 2 skipped | `/tmp/hippo-confirm-ck3-fake.log` |
| CK3 LadybugDB, verbatim | 0 | 114 passed (282 s) | `/tmp/hippo-confirm-ck3-ladybug.log` |
| CK4 Fake, verbatim | 0 | 167 passed | `/tmp/hippo-confirm-ck4-fake.log` |
| CK7 Ruff (`check` and `format --check`), verbatim | 0 | all checks passed; 51 files already formatted | `/tmp/hippo-confirm-ck7-ruff.log` |
| r7-fix rows on LadybugDB (`-k "M10b or M11 or re_ensuring or new_connector_instance or failure_counted"`) | 0 | 6 passed, 54 deselected | `/tmp/hippo-confirm-r7rows-ladybug.log` |
| Unmutated baseline for the mutation suites (guard, sync, kit, emit, registry, keys, CLI, scaffold) | 0 | 521 passed, 1 skipped | `/tmp/hippo-confirm-seq-mut-none.log` |

The counts equal the fixer's at every line `evidence-r7-fix.md` records (CK1 305/9, CK2 294, CK3
308/2 and 114, CK4 167). CK5 and CK6 were not re-run: no finding in scope touches their files, and
section 4 shows that every golden and lock they compare is byte-identical to `c863e03`.

The probes and mutations are scratch files under `/tmp`. None of them edits the repository.

- `/tmp/hippo-review-probe3.py` and `probe5.py` are the first reviewer's probes, re-run unchanged.
- `/tmp/hippo_confirm_probe3_test.py` drives probe 3's `emit` shape through `sync_connector` (the
  `world` fixture of `test_connector_sync.py`) and through `assert_emit_pure`, with both catch
  shapes. A mock transport records every model request that reaches it.
- `/tmp/hippo-confirm-probe-residual.py` is a guard-level probe for the paths section 5 describes.
- `/tmp/hippo_confirm_mutations.py` is a pytest plugin. It undoes one fix at `pytest_configure`,
  either by rebinding a module attribute or by recompiling a function from its own source with the
  fixed statement replaced; the rewrite asserts the replaced text occurs exactly once. Selected with
  `HIPPO_CONFIRM_MUTATION=<name>`. Logs are `/tmp/hippo-confirm-mut-<name>.log`; for `f1a`, `f1b`,
  `f2_builtins`, `f2_backstop`, `f5` and probe 3 under `f1b`, use the sequential reruns,
  `/tmp/hippo-confirm-seq-*.log` (section 7).
- `/tmp/hippo_mutation_plugin.py` is the first reviewer's harness, re-run for `direction` and
  `guard_model` to confirm that the standing-rule tests still bite at this HEAD.

## 2 Per finding

| Finding | Verdict | The test that proves it | What I ran | Result |
| --- | --- | --- | --- | --- |
| F1 | **CLOSED** | `test_connector_guard.py::test_the_refusal_is_not_an_ordinary_exception`, `::test_a_swallowed_violation_still_leaves_the_guard`, `::test_a_swallowed_violation_fails_assert_emit_pure`; `test_connector_sync.py::test_the_failure_matrix[M10b]` | probe 3 unchanged; probe 3 through the sync and the kit with `except Exception` and `except BaseException`, on Fake and (sync) LadybugDB; mutations `f1a`, `f1b`, and probe 3 under `f1b` | Probe 3 stops at the first call with `EmitSideEffect` (exit 1). Through the sync, both shapes raise `ConnectorContractViolation` naming `Ollama.embed` and write no `Generation`. Through the kit, both are `emit_pure`. `f1a`: exactly 2 failed. `f1b`: 8 failed, and probe 3's `except BaseException` shape publishes and gets past the purity check. Section 3.1 has the details |
| F2 | **CLOSED** | `test_connector_emit.py::test_no_builtin_predicate_admits_the_reviewed_source`, `::test_a_builtin_edge_with_source_reviewed_is_refused_at_bind`, `::test_an_extension_predicate_that_declares_reviewed_is_refused_anyway`; `test_registry.py:454` | probe 5; mutations `f2_builtins`, `f2_builtins_all`, `f2_backstop` | Probe 5: 0 of 33 built-ins admit `reviewed`; both derivation rows are still `human_verified`. `f2_builtins_all`: 3 failed, and the bind test now reads the backstop's message. `f2_backstop`: exactly the extension test failed. Section 3.2 has the details |
| F3 | **CLOSED** | `test_connector_guard.py::test_the_guard_reports_one_violation_per_emit_call` (the real test); the three clock names in `EXPECTED_FORBIDDEN_CALLS` (`test_connector_guard.py:83-86`), pinned by `::test_the_forbidden_set_is_the_plans_names_plus_m20s`, with executed refusal rows at `:231-233` | read; searched `tests/` for the old test; mutation `f1b` | The misnamed sync test is gone, and the only test with that name is the guard's. Its body swallows `time.time`'s refusal, makes a second forbidden call that runs unguarded, and asserts that the report names `time.time` and not `datetime`. It fails under `f1b` (`DID NOT RAISE`) |
| F5 | **CLOSED** | `test_connector_sync.py::test_re_ensuring_a_connector_leaves_its_enabled_flag_alone_unless_asked`, `::test_a_new_connector_instance_is_created_disabled_whether_or_not_enabled_is_passed` | mutation `f5` (`sync.py:244` back to `enabled=bool(enabled)`); both tests on LadybugDB | `f5`: exactly the re-ensure test failed (`assert False is True`); the create test holds under the mutation, as R51 requires. Green on LadybugDB |
| F10 | **CLOSED** | `test_connector_keys.py::test_a_symbol_with_no_signature_mints_the_code_lanes_identity`, `::test_a_null_key_part_is_refused_where_the_identity_helper_does_not_declare_one` | mutations `f10_nullable` (`keys._NULLABLE_PARTS` emptied) and `f10_database` (the null check in `_database_parts` removed) | Each failed exactly its own test: `Key part signature of symbol cannot be null`, and `... is a plain value` in place of the named refusal |
| F11 | **CLOSED** | `test_cli_connector.py::test_connector_new_requires_a_family`; the updated first row of `::test_connector_arguments_parse` | mutation `f11` (`required=True` back to `default="custom"`) | Exactly the new test failed (`DID NOT RAISE SystemExit`). The scaffold pins and the guide need no change and pass under the mutation |
| F14 (test half) | **CLOSED** | `test_connector_sync.py::test_the_failure_matrix[M11]` | mutation `f14`, which makes the failed revision keep its records (the design's pre-amendment reading) while still counting the failure; the same mutation against the **pre-fix** `[M11]` from `c863e03` | The new `[M11]` fails at `test_connector_sync.py:833` (`assert not any("/n2" ...)`); `[M11b]` holds. The pre-fix `[M11]` **passes** under the same mutation, which shows the new row pins DV1 where the old one did not |
| F15 | **CLOSED** | `test_connector_sync.py::test_the_failure_matrix[M11b]`, `::test_a_failure_counted_without_a_classified_family_is_counted_as_unknown` | mutation `f15` (`_failure_family` back to `descriptor.families[0]`); both on LadybugDB | `f15`: exactly those two failed (`{'service': 1} == {'custom': 1}`). Green on LadybugDB |

## 3 Findings F1 and F2 in detail

### 3.1 F1

**The class.** `guard.py:106` is `class EmitSideEffect(BaseException)`.
`test_the_refusal_is_not_an_ordinary_exception` asserts
`not issubclass(EmitSideEffect, Exception)` and that an `except Exception` inside the guard catches
nothing.

**The record.** `_hook` stores the refusal on `_state.violation` before it raises (`guard.py:194`).
`forbid_effects` saves and restores an enclosing guard's record, and on the way out raises the
record when the body completed (`guard.py:228`). Whether an exception is propagating is tracked by a
flag set after `yield`, not by `sys.exc_info()`, which is the right choice. The fix is the review's
text.

**The two entry points, by name.** A search of `src/hippo` finds exactly two places that enter the
guard:

- `sync._emit_one` (`sync.py:991`). The pool future is read in `sync._emit`, where
  `except (guard.EmitSideEffect, ContractError)` at `sync.py:1030` comes before the broad
  `except BaseException` at `:1032`.
- `testing.assert_emit_pure` (`testing.py:792`), where `except EmitSideEffect` at `:794` comes
  before `except Exception` at `:796`.

`ThreadPoolExecutor`'s work item catches `BaseException` and stores it on the future (checked in the
venv's `concurrent/futures/thread.py`), so the refusal crosses the pool unchanged.

**Probe 3, re-run against the rebased guard.** Unchanged, it now ends at the first `Ollama.embed`
with `EmitSideEffect: emit called hippo.ollama.Ollama.embed; ...`. Exit 1, no JSON printed, so the
`except Exception` retry never runs (`/tmp/hippo-confirm-probe3.log`). Driven through the runtime
and the kit (`/tmp/hippo-confirm-probe3-results-fake.jsonl`; LadybugDB sync rows in
`-ladybug.jsonl`):

| Path | Catch in `emit` | Outcome | Model requests that reached the transport |
| --- | --- | --- | --- |
| `sync_connector` | `except Exception` | `ConnectorContractViolation`, no `Generation` written | none |
| `sync_connector` | `except BaseException` | `ConnectorContractViolation`, no `Generation` written | one per revision (2 revisions) |
| `assert_emit_pure` | `except Exception` | `ContractViolation("emit_pure", ...)` | none |
| `assert_emit_pure` | `except BaseException` | `ContractViolation("emit_pure", ...)` | one |

The `except BaseException` rows show what the fix does and does not promise. CPython unsets the
profiler when the hook raises, so the second call is unguarded and does reach the provider; what the
fix guarantees is that the sync fails and nothing that call produced is published. The guard's
module docstring says so, and `[M10b]` pins it (`reached_the_second_call is True` for the
`BaseException` leg). This follows from how the guard works, so I record it as a note, not a
finding. The guard protects against mistakes; it is not a sandbox (design section 10).

**Mutations.**

- `f1a` makes `EmitSideEffect` a `RuntimeError` again and keeps the record half. It fails exactly
  `test_the_refusal_is_not_an_ordinary_exception` and `[M10b]`, whose `Exception` leg now reaches
  the second call.
- `f1b` restores the pre-fix `forbid_effects` and keeps the `BaseException` half. It fails 8 tests:
  `test_a_swallowed_violation_still_leaves_the_guard`, `::test_the_guard_reports_one_violation_per_emit_call`,
  `::test_a_swallowed_violation_does_not_leak_into_the_next_guard`,
  `::test_a_swallowed_violation_fails_assert_emit_pure`,
  `::test_a_nested_guard_does_not_clear_the_enclosing_guards_record`, the two updated lifecycle
  tests (`::test_the_guard_affects_only_the_entering_thread`,
  `::test_the_guard_nests_and_restores_a_previous_profiler`), and `[M10b]`.
- Under `f1b`, probe 3's `except BaseException` shape publishes (`DID NOT RAISE`), and
  `assert_emit_pure` returns the swallowing connector's batch to the determinism comparison.

The two halves are therefore each independently pinned.

**The one-violation test is real.** See F3 in section 2.

### 3.2 F2

`predicates.py:58-61` drops `reviewed` from the four source strings, and `predicates.py:182` drops it
from `SAME_OBJECT_AS`. Probe 5 at this HEAD prints `predicates_admitting_reviewed: []` and
`total_builtin_predicates: 33`. Both `evidence_class(..., "reviewed", None)` rows are still
`human_verified`, which keeps Task 12's acceptance writer possible, as the review asked.

**Refused for every built-in.** I argue this from the code, backed by one executed bind per path:

- The 32 non-identity built-ins no longer list `reviewed`, so `_bind_edges` refuses it at the
  `sources_allowed` check (`emit.py:842-846`). Executed for `DEPENDS_ON` by
  `test_a_builtin_edge_with_source_reviewed_is_refused_at_bind`.
- `SAME_OBJECT_AS` is refused before `sources_allowed` is read, because
  `check_direction_and_ownership` refuses an identity predicate as an edge. Executed by
  `test_identity_predicate_is_refused_as_an_edge`, which the first reviewer's `direction` mutation
  still fails at this HEAD.
- Behind both checks, the backstop at `emit.py:847` refuses `source == "reviewed"` for any predicate
  whatever its `sources_allowed`.

**The backstop is live, not decorative.**

- `f2_backstop` recompiles `_Binder._bind_edges` with the backstop's condition set to `False`. It
  fails exactly `test_an_extension_predicate_that_declares_reviewed_is_refused_anyway`.
- `f2_builtins_all` puts `reviewed` back into every built-in, including in the installed `REGISTRY`
  that `extension_scope` yields. It fails 3 tests: `test_no_builtin_predicate_admits_the_reviewed_source`,
  `test_registry.py::test_builtin_predicates_carry_owner_families_sources_and_verb_phrases`, and
  `test_a_builtin_edge_with_source_reviewed_is_refused_at_bind`.
- That last test now reads the backstop's message
  (`DEPENDS_ON: reviewed is the reconciliation queue's source (spec 4.3); ...`) in place of the
  generic one. So even with the source back in the built-ins, no `human_verified` edge binds.
- The first variant, `f2_builtins`, reset only `Registry.with_builtins`. Its third failure was a
  fingerprint mismatch between the two registries, an artifact of the partial mutation, which is why
  `f2_builtins_all` exists.

`test_registry.py:454` is the only edit to that file, and CK1 is green on both backends.

## 4 Byte-identity with `c863e03`

The comparison covers:

- the seven committed goldens of the fixture connector (`tests/fakes/fixture_connector/fixtures/basic/expected/*.json`);
- the seven of the exemplar (`src/hippo/connectors/examples/incidents_ndjson/fixtures/basic/expected/*.json`);
- both `registry.lock.json` files;
- `docs/spec/cdk-guide.md`;
- the two files that hold the guide's marked regions (`tests/fakes/fixture_connector/connector.py`,
  `types.py`, `# cdk-guide: begin/end` markers).

`git diff --name-only c863e03 HEAD` over these paths, the whole `tests/fakes/fixture_connector` tree
and `src/hippo/connectors/examples` is empty, and so is the diff of the working tree against HEAD.
The git blob ids of the guide, both lock files and both region files are equal at `c863e03` and
HEAD. The SHA-256 values of the guide (`99524374...`), `types.py` (`0ff8ee5c...`) and
`connector.py` (`9501a6e2...`) equal those in `evidence-r7-fix.md`. No golden or lock contains
`registry_fingerprint`, so F2's fingerprint change reaches none of them.

One observation, not a problem: `docs/spec/connector-developer-kit.md` (the design, not the guide)
gained seven lines after `c863e03`, in the orchestrator's `ce653d3`. The plan documents' stale
`class EmitSideEffect(RuntimeError)`, which `evidence-r7-fix.md` left open, was corrected in
`8206795`; nothing in `ai_docs/plans`, `src` or `docs` still spells it that way.

## 5 New finding

| id | Sev | file:line | Rule | The exact fix |
| --- | --- | --- | --- | --- |
| N1 | MINOR | `src/hippo/connectors/guard.py:218-229` | Standing rule 1; F1's "a swallowed violation still fails the sync" | See below |

**The defect.** `forbid_effects` raises the recorded refusal only when no exception is propagating,
which is the review's own wording. An `emit` that swallows the refusal (with `except BaseException`
or a bare `except:`) and then raises an ordinary error for its own reason loses the record. For
example, a retry loop that falls through to a `None` and then an `AttributeError`, or a parse
failure. That error reaches `sync._emit`'s broad handler, which counts it as `emit_failed` and
continues, so the sync **publishes**.

**Reproduced** (`/tmp/hippo-confirm-probe-residual.py` case A, and
`test_residual_swallow_then_raise_through_the_sync` in the scratch suite). A connector whose `emit`
swallows for revision `n2`, retries `Ollama.embed` and then raises `ValueError`, gives
`outcome: published`, `emit_failed: {"custom": 1}`, one `Generation` written, and one model request
at the transport. Through the kit, the same shape is reported as `emit_deterministic`
(`emit raised ValueError on call 1`) rather than `emit_pure`, so `hippo connector validate` points
the developer at the wrong rule.

**Why MINOR.** No output of the model call is published, because the revision's batch is discarded.
And the same call already reaches the provider in the path F1 fixed. What is lost is the failure
and the diagnosis: the rule is broken and nothing fails.

**The fix.** In `forbid_effects`, remember the exception in flight
(`except BaseException as error: in_flight = error; raise`) in place of the `propagating` flag. In
the `finally`, raise `EmitSideEffect(swallowed) from in_flight` whenever a record exists and
`in_flight` is neither an `EmitSideEffect` nor a `KeyboardInterrupt`/`SystemExit`. The existing
`::test_an_unrelated_failure_inside_the_guard_still_propagates` (no record) and
`::test_a_propagating_violation_is_not_raised_a_second_time_on_the_way_out` (the in-flight exception
is the refusal) stay green under that rule. Add three tests:

- a guard test in which a swallowed refusal outranks a later `ValueError`;
- a `[M10c]` row in which swallow-then-raise gives `ConnectorContractViolation` and no `Generation`;
- a kit test in which the same shape is `emit_pure`.

**Owner proposed:** an S3-fix on `connectors/guard.py` and its tests. It reruns CK3 and CK4.

**Notes that are not findings.**

1. **Nested guards.** A refusal that propagates out of a nested `forbid_effects` and is then
   swallowed inside the enclosing guard is not raised by the enclosing guard, because the inner
   guard restores the enclosing record, which is `None`. Nothing escapes: leaving the inner guard
   re-arms the outer one, and a further forbidden call is refused and reported (probe cases B and
   C). No connector enters the guard itself, and the only two entry points are single-level.
2. **`[M11]`'s last assertion.** `blocked_reason in (None, "snapshot_reference")` tolerates a
   blocked collection, which is weaker than `evidence-r7-fix.md`'s "still collects". The
   substantive claim, that the previous generation keeps every unit it was published with, is the
   assertion above it, and that one holds.
3. **Standing-rule suites still bite at this HEAD.** The first reviewer's `direction` mutation fails
   the same six tests as at `0d50887`. `guard_model` fails `test_the_guard_refuses[ollama_chat_json]`
   and `[ollama_embed]`, as before, plus `[M10b]`, whose first forbidden call is `Ollama.embed_one`
   (`/tmp/hippo-confirm-first-mut-*.log`).

## 6 The two standing rules at this HEAD

| Rule | Verdict | Enforced by |
| --- | --- | --- |
| 1. No connector calls a language model | **Enforced by tests; N1 open (MINOR)** | 31 executed refusal rows in `test_the_guard_refuses[...]`, the 47-name pin, eight new F1 guard tests, `[M10]` and `[M10b]`, and `test_the_purity_guard_is_the_runtime_guard`. Both catch shapes of probe 3 fail the sync and the kit. N1 is the one path along which a swallowed refusal does not fail the sync |
| 2. No connector writes a relation label it did not earn | **Enforced by tests** | The review's five gates (section 6.2), unchanged at this HEAD (the `direction` mutation still bites), plus F2: no built-in admits `reviewed`, and the backstop refuses it for any predicate, pinned by three tests and two mutations |

## 7 Two process errors during this review

1. **A kill of a PID I did not start.** At about 00:25:36 MST I sent `kill` to PID 66284, believing
   it was the wrapper of my own CK3 LadybugDB run. It was the orchestrator's wrapper (shell snapshot
   `...q8w3ru`), whose child, pytest 66297, had been running the CK3 line on Neo4j. That pytest had
   already exited: the `kill 66297` I sent next failed with `no such process`, and its log
   (`/tmp/hippo-orch-ck3-neo4j-2.log`) was complete at 00:25:25 with 112 passed, 2 skipped. The
   orchestrator confirms the run finished with exit 0. So only the wrapper, which was already exiting,
   received a signal, and nothing was cut. The rule I take from this: never kill a PID you did not
   start.
2. **Overlapping pytest processes.** Believing my CK3 LadybugDB run had been stopped, I started the
   mutation runs at 00:26:00. That run (PID 77871, 00:22:31 to 00:27:13, 114 passed) was still
   going, so eight Fake runs overlapped it: `probe3-fake`, `mut-none`, `f1a`, `f1b`, probe 3 under
   `f1b`, `f2_builtins`, `f2_backstop` and the start of `f5`. No Neo4j was involved, and each run
   used its own `tmp_path`. All eight were then repeated strictly one at a time, with identical
   results except for `probe3-fake`. Its first run had one failure caused by a bug in my own probe
   (the residual connector swallowed on every revision), which I fixed before the rerun:
   - `probe3-fake-2`: 6 passed;
   - `seq-mut-none`: 521 passed, 1 skipped;
   - `seq-mut-f1a`: 2 failed;
   - `seq-mut-f1b`: 8 failed;
   - `seq-probe3-f1b`: 2 failed;
   - `seq-mut-f2_builtins`: 3 failed;
   - `seq-mut-f2_backstop`: 1 failed;
   - `seq-mut-f5`: 1 failed.

   The same tests failed as in the overlapped runs (`/tmp/hippo-confirm-seq-summary.log`). Every
   figure in this report is from a sequential run.

No repository file was touched by either.

## 8 Verdict

**CK7's review findings CLOSED:** F1, F2, F3, F5, F10, F11, F14 (test half) and F15, each with a
test that fails when its fix is undone. **New and open:** N1 (MINOR), a swallowed refusal followed
by an ordinary error publishes the sync. The exact fix is in section 5, and the proposed owner is an
S3-fix on `connectors/guard.py`.
