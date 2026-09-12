# CC9a evidence — the shared build run (gate CD8, last clause)

Worker `backend-developer-17`, worktree `.worktrees/cc9a`, branch `wp/cc9a`, base `7a0c719`.
Contract: `ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` section 3 ("the shared `_Run`
failure latch is factored into `src/hippo/ingest/build_run.py` so neither owns it"), design review
M9 and M11 (`ai_docs/reports/2026-09-12-code-capture-plan-review.md`), and gate CD8's last clause
("the reviewed prose coordinator suite is unchanged by the `_Run` extraction").
Every line number below is the file as it stood at base `7a0c719`.

## What moved

`src/hippo/ingest/build_run.py` is new and holds, verbatim including comments:

| Name in `prose_generation.py` | Name in `build_run.py` |
| --- | --- |
| `BuildCancelled` (`:53`) | `BuildCancelled` |
| `BuildBusy` (`:57`) | `BuildBusy` |
| `BuildProgress` (`:113`) | `BuildProgress` |
| `BuildReceipt` (`:120`) | `BuildReceipt` (+ two counters, below) |
| `_credentials` (`:128`) | `credentials` |
| `_authority_fields` (`:132`) | `authority_fields` |
| `_Run` (`:139-261`) | `BuildRun` |

Method bodies, lock discipline, the one-read heartbeat comment in `_check`, the ambient-transaction
reasoning, `renew`'s `except BuildCancelled: raise` and the `try/finally` in `close` are byte-for-byte
what they were; the only edits inside the moved code are `_credentials` → `credentials` at its three
call sites and the two message literals becoming attributes. `prose_generation.py` keeps every old
spelling bound (`_Run = BuildRun`, `_credentials = credentials`, `_authority_fields = authority_fields`,
plus the four re-exported types), so no consumer changed its imports: `managed_activation.py:41-45`
(`BuildBusy`, `BuildCancelled`, `BuildProgress`, `BuildReceipt`) and
`knowledge/public_errors.py:82` (`BuildBusy`, `BuildCancelled`) are untouched.

Everything from `_pair` (`:263`) down is prose-specific and stayed. `prose_generation.py` lost its
`RLock` and `uuid4` imports; it keeps `timedelta`, `AuthorizationChanged` and `capture_build_authority`
(still used by `_install` and `_publish`) and keeps `LeaseHeartbeat` and `BuildProgress` bound purely
as re-exports (`# noqa: F401`, explained in the module's "moved names" comment).

**`src/hippo/ingest/__init__.py` is unchanged.** Nothing imports these names through the package's
lazy table — `managed_activation` and `public_errors` import the module directly — so adding
`build_run` entries would have grown the public surface for no consumer.

## Three deliberate additions to the moved contract

**1. `BuildReceipt` gains two zero-defaulted counters** (plan section 3, ruling 2):

```python
@dataclass(frozen=True)
class BuildReceipt:
    source_id: str
    generation_id: str
    event_id: str
    accepted_input_hash: str
    outcome: str
    resumed_from_batches: int = 0
    rebaselines: int = 0
```

Positional construction at `prose_generation.py:382` and `:618` is unaffected, and every equality
assertion on a receipt keeps passing. Counts only: still no path, no text and no exception body.

**2. Two keyword-only message arguments**, so the shared run carries no lane's wording by force
(the full constructor, with addition 3 alongside them):

```python
class BuildRun:
    def __init__(
        self,
        ctx,
        actor,
        source_id,
        options,
        should_stop,
        on_progress,
        *,
        capture=capture_build_authority,
        cancelled_message="Plain source build cancelled",
        renewal_failed_message="Plain build lease renewal failed",
    ): ...
```

The brief required the first; the second is the same problem one line further down
(`renew`'s `AuthorizationChanged`), and the orchestrator confirmed it rather than leaving CC9b an
escalation. Both defaults are the exact prose strings, so the prose lane's text is unchanged.

**3. A `capture` keyword argument**, defaulting to `capture_build_authority`, which
`build_plain_source` passes explicitly:

```python
run = _Run(ctx, actor, source_id, options, should_stop, on_progress, capture=capture_build_authority)
```

This is not cosmetic, and it is the one addition the brief did not ask for.
`test_prose_generation.py:700-730`
(`test_concurrent_build_is_not_rejected_by_another_threads_transaction`) does
`monkeypatch.setattr(w.module, "capture_build_authority", capture)` and relies on the replacement
firing at the *run's* guard capture — its comment says "the coordinator is past its ambient probe;
free the other thread". Had `BuildRun.__init__` resolved the name from `build_run`'s globals instead,
that patch would have become a silent no-op. Measured both ways rather than argued:

| Call site | Test duration | Log |
| --- | --- | --- |
| with `capture=capture_build_authority` | **0.08 s**, passes | `/tmp/hippo-cc9a-seam.log` |
| without it (seam removed, then restored) | **60.11 s**, passes | `/tmp/hippo-cc9a-seam-counterfactual.log` |

Without the seam the holder thread keeps the FakeStore's process-wide transaction lock for its full
`release.wait(60)` and the assertion only succeeds after that timeout — green, but no longer
exercising the concurrent window it names. The seam keeps the reviewed test honest; it is also the
hook CC9b would otherwise have had to ask for.

## One reviewed test adapted, with authorisation

`tests/unit/test_prose_generation.py:173` asserted the receipt's exact field set:

```python
assert set(vars(result)) == {"source_id", "generation_id", "event_id", "accepted_input_hash", "outcome"}
```

`BuildReceipt` is a frozen dataclass without `slots`, so defaulted fields still land in `__dict__`
and this is the one assertion in the repo that addition 1 cannot satisfy (`asdict`, `astuple` and
`replace` are never applied to a receipt; `set(vars(...))` appears nowhere else for it). Reported as
BLOCKED; the orchestrator authorised amending that line alone. It now names all seven fields and
adds `assert (result.resumed_from_batches, result.rebaselines) == (0, 0)`, keeping the original
"no path, no text, no exception body" intent and pinning that prose fills in neither counter. No
other line of any existing test changed.

## One brief clause corrected against the code

The brief asked for a test of "`check` refusing under an ambient transaction the way `_check` does
today". `_check` does not refuse: it opens its own `store.transaction()` around local reads, and the
refusal lives in `BuildAuthority.check` (`build_authority.py:303`) and at `build_plain_source`'s
entry (`prose_generation.py:651` before the move). Verified against the pre-change code on Fake —
`run.check()` inside `with store.transaction():` returns normally. Adding a refusal would have been a
behaviour change, so `test_check_nests_its_own_transaction_rather_than_refusing_an_ambient_one` pins
what the code actually does, and says in its docstring why: it is what lets the renewal worker
checkpoint while another thread owns a transaction.

## New tests

`tests/unit/test_build_run.py`, 21 tests, real store and real `BuildAuthority`, no model, no raw
objects, no published generation. The options object is a two-field local dataclass, which is exactly
what `BuildRun` reads, so the shared module's suite does not import the prose lane.

Latch: the first failure is what every later checkpoint reports and the callback is never re-entered.
Cancellation: `should_stop` reaches the next checkpoint and not before; a closed run is cancelled for
everyone; the message is the lane's. Renewal: any lost lease becomes one `AuthorizationChanged` with
the original as `__cause__` (parametrised over both messages); `BuildCancelled` passes through
unwrapped; `start` runs a worker that `pause` joins without faulting the run. Guard handover: `adopt`
closes the guard it replaces; `close` closes the heartbeat *then* the guard (order asserted through
spies on `LeaseHeartbeat.close` and `BuildAuthority.close`) and still releases the guard when joining
the worker raises. Progress: one frozen `BuildProgress` per call, and a run without a callback is
still a cancellation checkpoint. Receipt: both counters default to zero, the record is frozen, and its
field set is asserted. Seams: `prose_generation` still answers to every moved name and `_Run is
BuildRun`; and `import hippo.ingest.build_run` in a fresh interpreter loads `hippo.ingest` and
`hippo.ingest.build_run` and nothing else — no coordinator, either lane's.

## Runs

Baseline before any edit, Fake — `226 passed, 3 skipped` (`/tmp/hippo-cc9a-baseline.log`).
RED — `tests/unit/test_build_run.py` fails collection with
`ImportError: cannot import name 'build_run' from 'hippo.ingest'` (`/tmp/hippo-cc9a-red.log`).

None of the files below imports `fastapi.testclient` at module level, so every command is a bare
`-W error` (form (a) was not needed either; no test raises the anyio alias warning).

| Backend | Command | Result | Log |
| --- | --- | --- | --- |
| Fake | the baseline command again, unchanged: `test_prose_generation.py test_managed_pipeline_activation.py test_managed_route_activation.py test_layering.py test_import_order.py` | **226 passed, 3 skipped — identical to the baseline** | `/tmp/hippo-cc9a-baseline-after.log` |
| Fake | that set plus `test_build_run.py test_public_errors.py` | 341 passed, 3 skipped | `/tmp/hippo-cc9a-green-fake.log` |
| Fake | `test_build_run.py` | 21 passed | `/tmp/hippo-cc9a-green-buildrun.log` |
| Ladybug | `test_build_run.py` | 21 passed | `/tmp/hippo-cc9a-ladybug-buildrun.log` |
| Ladybug | `test_prose_generation.py -k "reopen or publish"` | 9 passed, 58 deselected | `/tmp/hippo-cc9a-ladybug-prose.log` |

Invocation shape: `HIPPO_TEST_STORE=<backend> .venv/bin/pytest <files> -q -o addopts='' -W error`.
Row 1 is CD8's last clause directly: the same five files, the same command, the same
`226 passed, 3 skipped` before and after the extraction. Row 2's 341 is that 226 plus the 21 new
tests plus `test_public_errors.py`'s 94, added because it imports `BuildBusy` and `BuildCancelled`
from `prose_generation` and so exercises the re-exports.

Neo4j was not run: the container is root-owned and this slice adds no query. The store surface
`BuildRun` touches is `transaction`, `_now`, `_check_build` and `renew_generation_build`, all
pre-existing and all exercised unchanged by the prose suite on Ladybug.

`test_import_order.py::MODULES` does not list `hippo.ingest.build_run`. That list is the
orchestrator's to maintain, so it was left alone;
`test_build_run.py::test_the_shared_run_loads_without_either_coordinator` already imports the module
first in a fresh interpreter and asserts the exact set of `hippo.ingest` modules it pulls, which is
the stronger of the two checks. Adding the entry is still worth doing when the list is next touched.

Ruff — `.venv/bin/ruff check` and `.venv/bin/ruff format --check` clean over
`src/hippo/ingest/build_run.py`, `src/hippo/ingest/prose_generation.py`,
`tests/unit/test_build_run.py`, `tests/unit/test_prose_generation.py` and this file.

## For CC9b

`BuildRun` is constructible exactly as `_Run` was, positionally. Pass
`cancelled_message=` and `renewal_failed_message=` for the code lane's wording, and `capture=` only
if the code coordinator's own tests need to substitute the guard capture the way the prose ones do.
`BuildReceipt(source_id, generation_id, event_id, accepted_input_hash, outcome, resumed_from_batches,
rebaselines)` — fill the last two; prose leaves them zero. `credentials(job)` and
`authority_fields(guard)` are the public spellings.
