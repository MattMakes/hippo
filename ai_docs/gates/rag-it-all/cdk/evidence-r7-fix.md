# CDK r7-fix evidence: the eight code findings of the CK7 review

Worker `backend-developer-19`, branch `wp/r7-fix`, base `c863e03` (the `rag-it-all-tibs` HEAD after
every CDK slice merged and the orchestrator applied F6, F7, F8 and F14's design wording). Contract:
the findings table and sections 6.1, 6.2 and 9 of `ai_docs/reports/2026-09-15-cdk-code-review.md`,
ruling R81, and the brief `ai_docs/handoffs/briefs/cdk-r7-fix.md`. The review was read at `1493963`
(the reviewer's final revisions, a documentation-only commit on top of the base).

Closed here: **F1, F2, F3, F5, F10, F11, F14's test half, F15.** R81 assigns F4 and F12 to Task 15,
F9 to the writer-retirement slice, F13 to Task 11; F6, F7, F8 and F14's design wording were the
orchestrator's and landed at `c863e03`.

## Commits

| # | Hash | Finding | Files |
| --- | --- | --- | --- |
| 1 | `3f27fa6` | F1, F3 | `connectors/guard.py`, `tests/unit/test_connector_guard.py`, `tests/unit/test_connector_sync.py` |
| 2 | `c0b1d11` | F2 | `connectors/emit.py`, `knowledge/predicates.py`, `tests/unit/test_connector_emit.py`, `tests/unit/test_registry.py` |
| 3 | `22f81b5` | F5 | `connectors/sync.py`, `connectors/testing.py`, `cli.py`, `tests/unit/test_connector_sync.py` |
| 4 | `ba74ac5` | F15 | `connectors/sync.py`, `tests/unit/test_connector_sync.py` |
| 5 | `fa2f1e6` | F14 (test half) | `tests/unit/test_connector_sync.py` |
| 6 | `ab6832c` | F11 | `cli.py`, `tests/unit/test_cli_connector.py` |
| 7 | `8bb3847` | F10 | `connectors/base.py`, `connectors/keys.py`, `tests/unit/test_connector_keys.py` |
| 8 | (this commit) | — | this file |

Two files are outside the brief's per-finding lists, each argued below:
`tests/unit/test_registry.py` (F2, one assertion, confirmed by the orchestrator) and
`src/hippo/connectors/keys.py` (F10, which names only `base.py` and its key test). Nothing under "do
NOT touch" was edited — `git diff --name-only c863e03..HEAD` names no golden, no guide, no fixture
connector file, nothing under `docs/`, and neither `GATES.md` nor the checkpoint — and no identity
field, schema or checksum changed.

## Per finding: RED, GREEN and what the fix could not do as written

### F1 and F3 — a swallowed emit refusal still fails the sync (`3f27fa6`)

The brief's F1 bullet and R81 both describe only the thread-local half of the review's exact fix.
The orchestrator confirmed mid-slice that the finding is **both** halves, plus a check that the two
call sites catch `EmitSideEffect` explicitly, all three pinned by test. That is what landed.

| Stage | Command | Log | Result |
| --- | --- | --- | --- |
| RED, guard | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_guard.py -q -o addopts='' -W error` | `/tmp/hippo-r7-f1-red.log` | exit 1, **5 failed, 39 passed** |
| RED, runtime | the `[M10b]` row against the pre-fix `guard.py` | `/tmp/hippo-r7-f1-sync-red.log` | exit 1, `DID NOT RAISE ConnectorContractViolation` |
| GREEN | both files | `/tmp/hippo-r7-f1-sync-green.log` | exit 0, **100 passed, 1 skipped** |

The five RED failures fail for the right reasons: `assert not issubclass(EmitSideEffect, Exception)`
is `assert not True`, three `DID NOT RAISE EmitSideEffect`, and `assert_emit_pure` returning the
swallowing connector's batch instead of refusing it.

The runtime RED was produced by copying the fixed `guard.py` aside, `git checkout`ing the file, and
running `[M10b]` against the pre-fix guard — so the row is shown to bite at the level F1 is about,
not only at the guard's own level. The file was restored from the copy before GREEN.

The guard gained eight tests in all. Seven were written before the fix; the eighth,
`::test_a_nested_guard_does_not_clear_the_enclosing_guards_record`, was written after GREEN, once
the fix's save-and-restore of an enclosing guard's record existed to be pinned. It was never seen to
fail before the fix, so it was mutation-checked instead: replacing `_state.violation = enclosing`
with `_state.violation = None` in `forbid_effects` fails exactly that test and no other
(`/tmp/hippo-r7-f1-nested-mutation.log`, exit 1, **1 failed, 44 passed**), and the file was
restored from a copy afterwards.

Of the seven written first, two passed in RED and are named honestly here:
`::test_a_propagating_violation_is_not_raised_a_second_time_on_the_way_out` and
`::test_an_unrelated_failure_inside_the_guard_still_propagates`. They cannot fail before the feature
exists; they are the pins for the fix's "then clear it" and "only when no exception is propagating"
clauses, and each fails if that clause is written wrongly.

What the fix does:

- `_hook` records `f"emit called {refused}; {REFUSAL}"` on `_state.violation` before raising, so the
  record survives CPython unsetting the profiler.
- `forbid_effects` saves and restores an enclosing guard's record, and raises the record on the way
  out when the body completed without an exception. "No exception is propagating" is tracked by a
  flag set after the `yield`, not by `sys.exc_info()`, which would also see an unrelated exception
  the caller happened to be handling around the `with`.
- `EmitSideEffect` is a `BaseException`.

**Guard entry points.** `grep -rn "purity_guard\|forbid_effects" src/hippo` finds exactly two places
that enter the guard: `sync.py:991` (`_emit_one`) and `testing.py:792` (`assert_emit_pure`). Both
already name `EmitSideEffect` in an `except` that precedes their broad handler, so neither call site
changed; `[M10b]` and `::test_a_swallowed_violation_fails_assert_emit_pure` pin both. No scaffold
template and no example connector enters the guard.

F3: the misnamed `test_connector_sync.py::test_the_guard_reports_one_violation_per_emit_call` is
**folded**, not renamed. Its three `FORBIDDEN_CALLS` memberships are already pinned byte for byte by
`test_connector_guard.py::test_the_forbidden_set_is_the_plans_names_plus_m20s`, and its
`issubclass(EmitSideEffect, RuntimeError)` assertion is superseded by
`::test_the_refusal_is_not_an_ordinary_exception`. The real one-violation-per-call test lands beside
the guard: it swallows the first refusal, makes a second forbidden call that CPython leaves
unguarded, and asserts the reported violation names the first.

Two existing guard tests swallowed a refusal inside a guard through the `_refuses` helper and exited
normally, so the fix makes them fail. Both were updated to the new contract rather than worked
around: `::test_the_guard_affects_only_the_entering_thread` records the re-raise in its `seen` dict,
and `::test_the_guard_nests_and_restores_a_previous_profiler` wraps its outer guard in
`pytest.raises` and still asserts the previous profiler is restored — the `finally` restores it
before it raises.

Left as-is, outside this brief's files: `ai_docs/plans/cdk-s3-runtime.md:159` and
`ai_docs/plans/cdk-s4-kit.md:1749` still write `class EmitSideEffect(RuntimeError)`.

### F2 — a connector cannot emit `source="reviewed"` (`c0b1d11`)

| Stage | Command | Log | Result |
| --- | --- | --- | --- |
| RED | `... pytest tests/unit/test_connector_emit.py -q -o addopts='' -W error -k reviewed` | `/tmp/hippo-r7-f2-red.log` | exit 1, **3 failed, 2 passed** |
| GREEN | `... pytest tests/unit/test_connector_emit.py ...` | `/tmp/hippo-r7-f2-green.log` | exit 0, **161 passed** |

The third RED failure is the load-bearing one: `DID NOT RAISE BindRefused` for an extension
predicate that lists `reviewed` in its own `sources_allowed` — the edge bound and stored
`human_verified`.

**Deviation from the review's literal wording, confirmed by the orchestrator.** The review's exact
fix says "drop `reviewed` from the four source strings in `predicates.py`", which is 32 of the 33
built-in predicates; `SAME_OBJECT_AS` carries its own inline `"rule reviewed"`. The brief and R81
both say "every built-in `sources_allowed`". Taken as "every", because the review's own Task 12
sentence — the acceptance writer "must then write the accepted alias through `update_knowledge`
rather than through `_bind_edges`, since `sources_allowed` will no longer admit `reviewed`" — only
holds if `SAME_OBJECT_AS` loses it too. The orchestrator confirmed: "'Every' is right: drop reviewed
from SAME_OBJECT_AS too."

The cost is one CK1 assertion: `tests/unit/test_registry.py:454`,
`same.sources_allowed == {"rule", "reviewed"}` becomes `{"rule"}`. That is the only line of
`test_registry.py` touched. CK1 stays green and `len(predicates.PREDICATES)` is still 32.

`SAME_OBJECT_AS` was already unreachable from a connector's edge path —
`check_direction_and_ownership` refuses an identity predicate before `sources_allowed` is read — so
this half is belt-and-braces, and Task 12 is not blocked: `sources_allowed` is enforced at exactly
one place, `emit.py`'s `_bind_edges`, and `update_knowledge` does not consult it.

The backstop sits **after** the `sources_allowed` check, as the review writes it. That makes it dead
for built-ins by construction and live for extension predicates, which write their own
`sources_allowed` and may list any registered evidence source. A built-in emitting `reviewed`
therefore gets the generic `does not accept source reviewed; allowed: [...]` message, and an
extension gets the named one.

Kept for Task 12, as the review asks: `reviewed` stays a registered evidence source, and both
`EVIDENCE_CLASS_DERIVATION` rows (`deterministic`/`probabilistic` → `human_verified`) stay. Pinned
by `::test_no_builtin_predicate_admits_the_reviewed_source`.

**Goldens.** The registry fingerprint moves; no committed golden or lock carries it. The fourteen
golden files of the fixture connector and the exemplar are byte-identical before and after, checked
twice — on disk, and again after CK4 and CK6 regenerated and compared them.

### F5 — re-ensuring a connector no longer disables it (`22f81b5`)

| Stage | Log | Result |
| --- | --- | --- |
| RED | `/tmp/hippo-r7-f5-red.log` | exit 1, `assert False is True` — the re-ensure had disabled the row |
| GREEN | `/tmp/hippo-r7-f5-green2.log` | exit 0, **205 passed, 1 skipped** |

`enabled: bool | None = None`. `None` creates a row disabled (R51 unchanged, `bool(enabled)` on the
create path) and leaves an existing row's flag alone; `True` and `False` are explicit.

The brief lists `src/hippo/web/routes/connectors.py` among F5's files. **It needed no change**: it
never calls `ensure_connector`, only reads `row.enabled` for its responses. This matches the review,
which notes that R73's "S6's routes pass `enabled=` deliberately" names `POST /api/connectors`, a
route that is Task 15's and does not exist yet.

Both callers that pass the argument today mean `True` and still say so; their comments were updated
to the new semantics.

### F15 — an emit failure is counted against the family that failed (`ba74ac5`)

| Stage | Log | Result |
| --- | --- | --- |
| RED | `/tmp/hippo-r7-f15-red.log` | exit 1, `assert {'service': 1} == {'custom': 1}` |
| GREEN | `/tmp/hippo-r7-f15-green2.log` | exit 0, **59 passed, 1 skipped** |

`_failure_family(target)` returns `getattr(target.mapping, "family", None) or "unknown"`. The
two-family fixture is `[M11b]`: `_TwoFamilyFailingConnector` declares `("service", "custom")` while
the partition is classified `custom`, so the pre-fix code counted the failure against `service`.

The `"unknown"` fallback is unreachable through `sync_connector`, because `_Target.mapping` is a
required `TypeMapping` and `TypeMapping.family` is a required non-empty `Family`. Rather than leave
it untested, the counting rule was lifted into the named module function `_failure_family`, which
`::test_a_failure_counted_without_a_classified_family_is_counted_as_unknown` drives directly. This
is the one structural liberty taken beyond the finding's letter, and it changes no behaviour.

### F14's test half — `[M11]` pins DV1, not the design's reading (`fa2f1e6`)

`[M11]` now publishes a clean generation first, so the failing revision has records to lose, then
provokes the second sync with a change to a **different** note, so `n2` is unchanged and is
re-emitted only because DV1 re-emits every member revision. It asserts `n2` is still a
`GenerationMember` of the new generation and holds no unit in it, and that the previous generation
keeps every unit it was published with and still collects.

There is no production change here, so there is no RED in the usual sense. The assertions were shown
to bite by mutation: flipping `assert not any("/n2" in text ...)` to `assert any(...)` — the design's
original reading — fails the row (`/tmp/hippo-r7-f14-mutation.log`, exit 1, `assert False`). An
untouched second sync returns `no_changes` and publishes no generation, which is why the row provokes
one with a provider change; that was measured, not assumed.

GREEN: `/tmp/hippo-r7-f14-ck3.log`, exit 0, **308 passed, 2 skipped**.

### F11 — `hippo connector new` requires `--family` (`ab6832c`)

| Stage | Log | Result |
| --- | --- | --- |
| RED | `/tmp/hippo-r7-f11-red.log` | exit 1, `DID NOT RAISE SystemExit` |
| GREEN | `/tmp/hippo-r7-f11-green.log` | exit 0, **61 passed** |

`required=True`, `args.family or "custom"` becomes `args.family`, and the `hippo --help` epilog
writes the command as design section 9 does. The existing `["connector", "new", "incidents"]` parse
case became `[..., "--family", "incident"]` and a new test pins the exit code 2.

**The scaffold pins do not move.** They call `scaffold.ScaffoldRequest` with an explicit family and
never touch the parser, so `test_connector_scaffold.py::test_scaffold_output_for_a_fixed_request_is_pinned`
passes untouched. The developer guide already writes `hippo connector new incidents_ndjson --family
incident --kinds incident`, so it needed no change either.

**Marked regions, byte-identity.** `git diff --stat c863e03 -- docs/spec/cdk-guide.md
tests/fakes/fixture_connector/` is empty at HEAD. SHA-256:

```text
99524374c0186555eb289220be9df30c89d59956e6b6e79f36cdc25531e183a5  docs/spec/cdk-guide.md
0ff8ee5c7d78dd0c1a4721d3b2783563c45207f7945ca19be380f4bd261ada65  tests/fakes/fixture_connector/types.py
9501a6e26e6d1fd4cd8dda6de1f26c6903c2a8e3198678a2232882f46d994669  tests/fakes/fixture_connector/connector.py
```

### F10 — `None` joins `KeyValue` (`8bb3847`)

| Stage | Log | Result |
| --- | --- | --- |
| RED | `/tmp/hippo-r7-f10-red.log` | exit 1, `ValidationError: key.signature ... Input should be a valid string` |
| GREEN | `/tmp/hippo-r7-f10-green.log` | exit 0, **35 passed** |

**A file outside the brief's list.** F10 names `connectors/base.py` and `test_connector_keys.py`, but
widening `KeyValue` alone does not close it: `keys._check_plain` refuses every non-string plain part,
so a null signature was refused with the misleading "SqlPart values belong to database kinds". The
finding's own required test cannot pass without touching `connectors/keys.py`, so it was touched,
and only in `_check_plain`, `_database_parts` and one new constant.

`KeyValue = Text | SqlPart | tuple[SqlPart, ...] | None`, and `keys._NULLABLE_PARTS` names the parts
whose identity helper declares them optional — today only `("symbol", "signature")`. Every other
plain part and every database part refuses a null by name, so widening the type opened nothing:
`check_key_parts` still requires every template part to be present, and `None` is never a stand-in
for a missing one.

The key test proves the claim the finding makes, at both levels: the canonical key equals
`symbol_key(..., None, kind="function")` and the minted `KnowledgeObject.id` equals
`symbol_identity(..., None, kind="function", workspace=WORKSPACE)` — which also exercises
`keys.knowledge_object`'s own identity check with a null part for the first time.

**Beyond the review.** The review says `""` "would mint a different identity from the code lane's
`None`". It is worse than that: `NodeRef`'s `key_parts` validator already refuses an empty-string key
part ("A node reference needs its key parts"), so before this change the part could not be expressed
at all — neither as `None` nor as `""`. The test pins both facts.

## The gate CHECK lines

Run verbatim from `ai_docs/gates/rag-it-all/cdk/GATES.md` at HEAD, from the worktree root, one pytest
process at a time, never against Neo4j. The `-W error` form is (a) throughout: no CHECK line in this
set needed the command-line `anyio` filter, and none was added.

| Line | Backend | Exit | Result | Log |
| --- | --- | --- | --- | --- |
| CK1 | Fake | 0 | 305 passed, 9 skipped | `/tmp/hippo-r7-gate-ck1-fake.log` |
| CK2 | Fake | 0 | 294 passed | `/tmp/hippo-r7-gate-ck2-fake.log` |
| CK3 | Fake | 0 | 308 passed, 2 skipped | `/tmp/hippo-r7-gate-ck3-fake.log` |
| CK3 | LadybugDB | 0 | 114 passed | `/tmp/hippo-r7-gate-ck3-ladybug.log` |
| CK4 | Fake | 0 | 167 passed | `/tmp/hippo-r7-gate-ck4-fake.log` |
| CK6 | Fake | 0 | 42 passed | `/tmp/hippo-r7-gate-ck6-fake.log` |
| CK6 | LadybugDB | 0 | 42 passed | `/tmp/hippo-r7-gate-ck6-ladybug.log` |
| CK7 `ruff check` | — | 0 | all checks passed | `/tmp/hippo-r7-gate-ck7-ruff-check.log` |
| CK7 `ruff format --check` | — | 0 | 51 files already formatted | `/tmp/hippo-r7-gate-ck7-ruff-format.log` |

CK2's Fake line and both CK7 Ruff lines were re-run after the F10 commit was amended with the
`knowledge_object` identity assertion; every other line was run once, at the same tree.

### Counts against the review's baseline at `0d50887`

| Line | Review | Here | Difference |
| --- | --- | --- | --- |
| CK1 Fake | 305 passed, 9 skipped | 305 passed, 9 skipped | none; F2 edited one assertion, added no test |
| CK2 Fake | 289 passed | 294 passed | +5: three F2 tests and two F10 tests |
| CK3 Fake | 296 passed, 2 skipped | 308 passed, 2 skipped | +12: eight new guard tests, `[M10b]`, `[M11b]`, two F5 tests, F15's fallback test, less the folded misnamed one |
| CK4 Fake | 166 passed | 167 passed | +1: F11's `::test_connector_new_requires_a_family` |
| CK6 Fake | 42 passed | 42 passed | none; CK6 is the exemplar, which no finding touches |

## Anything a finding's fix could not do as written

1. **F1** — the brief and R81 scope the finding to the thread-local half only; the review's exact fix
   also rebases `EmitSideEffect` on `BaseException`. Resolved by the orchestrator mid-slice in favour
   of both halves. Nothing was left undone.
2. **F2** — "the four source strings" in the review is 32 predicates; the brief, R81 and the
   orchestrator all say every built-in, which is 33. Taken as 33; one CK1 assertion edited.
3. **F2** — the backstop's placement after the `sources_allowed` check, which the review specifies,
   means a built-in emitting `reviewed` reads the generic refusal rather than the named one.
4. **F5** — `web/routes/connectors.py`, named in the brief, needed no change.
5. **F15** — the `"unknown"` fallback is unreachable through the public path; the counting rule was
   lifted into `_failure_family` so it can be driven directly rather than left untested.
6. **F14** — no production change, so the row was mutation-checked instead of RED/GREEN.
7. **F10** — the fix needed `connectors/keys.py`, which the brief does not name; see F10.
8. Two plan documents still describe `EmitSideEffect` as a `RuntimeError`; both are outside this
   brief's files.
