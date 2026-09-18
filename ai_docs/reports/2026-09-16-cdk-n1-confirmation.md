# CK7: independent confirmation that n1-fix closed finding N1

**Reviewer:** `architect-reviewer-5` (herdr fleet). **Revision:** `0a248b5` on `rag-it-all-tibs`
(`wp/n1-fix` merged at `e2a6f48`), root tree, read-only apart from this file. **Date:**
2026-09-16. **Brief:** `ai_docs/handoffs/briefs/review-cdk-n1-fix.md`. **Finding:** N1, section 5
of `ai_docs/reports/2026-09-16-cdk-r7-confirmation.md`. **Fix:** commits `6952b41` and `9a89a90`,
evidence `ai_docs/gates/rag-it-all/cdk/evidence-n1-fix.md`, ruling R82.

**Verdict: N1 CLOSED.** `forbid_effects` now does what the finding's "The fix" paragraph says, word
for word. Each of the three new tests fails when the fix is undone in-process and passes at HEAD,
and `[M10c]` does both on Fake and on LadybugDB. The merge touches only the five files the fixer
names. No golden, lock, guide or scaffold file changed.

## 1 Checks

All pytest runs used `-W error` with no warning filter; none needed the `anyio` exception. No run
used Neo4j. My runs were strictly sequential. The orchestrator's gate-checker pytest (PID 49960,
started 00:55:13) was running in the same tree at every point I checked, as the brief allows. I sent no
signal to any process. So that I would not swap files under that run, I undid the fix only
in-process, with a pytest plugin, never by editing or stashing a file.

| # | Check | Result | What I ran |
| --- | --- | --- | --- |
| 1 | The fix matches the finding's "The fix" paragraph | **Yes.** The `propagating` flag is gone. `except BaseException as error: in_flight = error; raise` remembers the exception in flight (`guard.py:224-229`). The `finally` raises `EmitSideEffect(swallowed) from in_flight` when a record exists and `in_flight` is not an instance of `(EmitSideEffect, KeyboardInterrupt, SystemExit)` (`guard.py:236-239`). The enclosing record is still saved and restored, so nested guards are unchanged, as R82 requires | `git diff 57171f4 HEAD -- src/hippo/connectors/guard.py`, read against section 5 of the r7 confirmation |
| 2 | The two exclusions | **Present and effective.** After a swallowed refusal, an in-flight `KeyboardInterrupt` or `SystemExit` propagates as the same object with no cause. `ValueError`, `RuntimeError` and `StopIteration` each become `EmitSideEffect` caused by that exception. They match `sync._emit`'s own policy, which re-raises the same two classes at `sync.py:1033-1034` | the fixer's `/tmp/hippo-n1-fix-probe-exclusions.py`, rerun: `/tmp/hippo-n1-confirm-probe-exclusions.log`, exit 0, identical to the fixer's log apart from its `EXIT` line |
| 3 | The refusal is not raised a second time | **Yes.** At HEAD, a refusal that propagates unswallowed leaves the guard as the hook's own object, with no `__cause__`. With `EmitSideEffect` removed from the exclusions (mutation `n1_reraise_refusal`), it becomes a new `EmitSideEffect` caused by the original. See note 2 | `/tmp/hippo-n1-confirm-probe-mutants.py` → `/tmp/hippo-n1-confirm-probe-mutants.log`, exit 0 |
| 4 | Residual probe, case A | **Now raises `EmitSideEffect`** (it was `ValueError`). The one provider request is still there: it comes from the probe's retry, which runs after CPython has unset the profiler. That is F1's known gap, which N1 did not cover (note 3) | `/tmp/hippo-confirm-probe-residual.py` → `/tmp/hippo-n1-confirm-probe-residual.log`, exit 0; `diff` against `/tmp/hippo-confirm-probe-residual.log` shows only the two case-A lines `raised` and `is_emit_side_effect` |
| 5 | Residual probe, cases B and C | **Unchanged**, byte for byte, from the r7 reviewer's log | the same `diff` |
| 6 | Fix undone, the three test files on Fake | **Exit 1, exactly 3 failed** (190 passed, 1 skipped): the three new tests. The failure lines match the fixer's RED log: `ValueError` escapes the guard (`test_connector_guard.py:488`); `DID NOT RAISE ConnectorContractViolation` (`test_connector_sync.py:811`); `'emit_deterministic' == 'emit_pure'` (`test_connector_testing_kit.py:915`). Nothing else fails, so the mutation undoes N1 and not F1 | `HIPPO_N1_MUTATION=n1`, `test_connector_guard.py test_connector_sync.py test_connector_testing_kit.py` → `/tmp/hippo-n1-confirm-fake-mut-n1.log` |
| 7 | Fix undone, named tests | The three new tests **FAILED**. `test_an_unrelated_failure_inside_the_guard_still_propagates`, `test_a_propagating_violation_is_not_raised_a_second_time_on_the_way_out`, `test_a_swallowed_violation_still_leaves_the_guard` and `[M10b]` **PASSED** | `-v` on those seven node ids → `/tmp/hippo-n1-confirm-fake-named-n1.log`, exit 1, 3 failed, 4 passed |
| 8 | HEAD, the three test files on Fake | **Exit 0, 193 passed, 1 skipped.** 194 were collected, which matches the fixer's collection count | the same command with no mutation (plugin loaded, inactive) → `/tmp/hippo-n1-confirm-fake-mut-none.log` |
| 9 | HEAD, named tests | **All 7 PASSED** | `/tmp/hippo-n1-confirm-fake-named-none.log`, exit 0 |
| 10 | `[M10c]` on LadybugDB, fix undone | **Exit 1, 1 failed**: `DID NOT RAISE ConnectorContractViolation` | `HIPPO_N1_MUTATION=n1 HIPPO_TEST_STORE=ladybug ... "test_connector_sync.py::test_the_failure_matrix[M10c]"` → `/tmp/hippo-n1-confirm-ladybug-mut-n1.log` |
| 11 | `[M10c]` on LadybugDB, HEAD | **Exit 0, 1 passed** | the same, no mutation, `-v` → `/tmp/hippo-n1-confirm-ladybug-head.log` |
| 12 | The `from in_flight` cause is pinned | **Yes.** Without it (mutation `n1_no_cause`), exactly the new guard test fails | three files on Fake → `/tmp/hippo-n1-confirm-fake-mut-n1_no_cause.log`, exit 1, 1 failed, 192 passed, 1 skipped |
| 13 | Scope of the change | **The five files the fixer names.** `57171f4..e2a6f48` changes exactly `evidence-n1-fix.md`, `guard.py` and the three test files. `e2a6f48..0a248b5` changes only this review's brief (the orchestrator's commit). The merge's diff is byte-identical to the branch's own diff (`git diff 0f965c0 9a89a90`), and `0f965c0..57171f4` changes only the r7 report and `GATES.md`, as the evidence states | `/tmp/hippo-n1-confirm-scope.log` |
| 14 | No golden, lock, guide or scaffold output changed | **None changed.** `git diff --name-only 57171f4 HEAD` is empty for these paths: the 16 tracked `registry.lock.json` and `fixtures/basic/expected/*.json` files, `tests/fakes/fixture_connector`, `src/hippo/connectors/examples`, `src/hippo/connectors/scaffold` (templates included), `docs/spec/cdk-guide.md`, `test_connector_scaffold.py`, `sync.py`, `testing.py`, `GATES.md` and `cdk-rulings.md` | `/tmp/hippo-n1-confirm-scope.log` |
| 15 | Ruff on the fixer's four code files | **Clean.** `All checks passed!`, `4 files already formatted` | `/tmp/hippo-n1-confirm-ruff-fixer-files.log` |
| 16 | Working tree | `git status --porcelain` was empty before I wrote this file, and afterwards it lists only this file | `git status --porcelain` |

The fixer's gate counts agree with the three added tests: CK3 Fake 308/2 → 310/2 (guard test and
`[M10c]`), CK3 LadybugDB 114 → 115 (`[M10c]`), CK4 167 → 168 (the kit test). I did not rerun
those gate lines. The orchestrator's checker owns them.

## 2 Notes, not findings

1. **The `KeyboardInterrupt`/`SystemExit` exclusion is untested** (the brief asked for this note).
   With it removed (mutation `n1_no_exit_exclusion`), no test in the three files fails
   (`/tmp/hippo-n1-confirm-fake-mut-n1_no_exit_exclusion.log`: exit 0, 193 passed, 1 skipped),
   although the mutants probe shows that a swallowed refusal followed by `KeyboardInterrupt` then
   leaves as `EmitSideEffect`. Only the scratch probes show the exclusion. A later slice could add
   a guard test parametrised over the two classes that asserts the in-flight object propagates
   unchanged.
2. **`test_a_propagating_violation_is_not_raised_a_second_time_on_the_way_out` does not check what
   its name says.** Under `n1_reraise_refusal` it still passes, and no test in the three files fails
   (`/tmp/hippo-n1-confirm-fake-mut-n1_reraise_refusal.log`: exit 0, 193 passed, 1 skipped). A
   second raise has the same class and message, so the sync and the kit give the same outcome, and
   the only visible difference is the extra link in the chain. The r7 confirmation said this test
   "stays green under that rule". That is true, but it also stays green without the rule. The test
   predates N1. An assertion that the raised object is the hook's own (for example
   `caught.value.__cause__ is None`) would pin it. This is harmless, so it is a note.
3. **F1's known gap is unchanged.** In residual case A, the retry after the swallowed refusal runs
   unguarded and reaches the transport. The fix makes that run fail, but it cannot stop the call.
   `[M10c]` makes a single model call, so it can also assert that the refused request never ran.
   The fixer's evidence explains why, and design section 10 covers this: the guard catches
   mistakes, it is not a sandbox.

## 3 Scratch files (not in the repo)

- `/tmp/hippo_n1_confirm_mutations.py` is a pytest plugin, loaded with
  `PYTHONPATH=/tmp ... -p hippo_n1_confirm_mutations` and selected with `HIPPO_N1_MUTATION=<name>`.
  At `pytest_configure` it recompiles `guard.forbid_effects` from its own source with one piece of
  text replaced, asserting that the text occurs exactly once. It binds the result as both
  `guard.forbid_effects` and `testing.purity_guard`, so `test_the_purity_guard_is_the_runtime_guard`
  stays honest. The `n1` mutation replaces the fixed tail with the `57171f4` tail, which was
  checked verbatim against `git show 57171f4:src/hippo/connectors/guard.py` before the runs.
  `n1_reraise_refusal`, `n1_no_exit_exclusion` and `n1_no_cause` each change one clause.
- `/tmp/hippo-n1-confirm-probe-mutants.py` reports, at HEAD and under the two exclusion mutations,
  how an unswallowed refusal propagates and what a swallowed refusal followed by
  `KeyboardInterrupt` becomes.
- The first reviewer's `/tmp/hippo-confirm-probe-residual.py` and the fixer's
  `/tmp/hippo-n1-fix-probe-exclusions.py` were rerun unchanged.

## 4 Verdict

**N1 CLOSED.** The fix is the finding's exact fix, all three new tests fail when it is undone
(`[M10c]` on both backends), the change stays within its five files, and no golden, lock, guide or
scaffold file moved. Nothing remains to fix. The two untested details in section 2 are notes for
a later slice.
