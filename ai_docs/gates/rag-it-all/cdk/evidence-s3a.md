# CDK S3a evidence: the emit guard, the bounded HTTP client and credentials

Worker `backend-developer-5`, branch `wp/s3a`, base `96eda9f` (the `rag-it-all-tibs` HEAD after S2a
merged; S1a merged at `d0bd052`). Contract: Task S3a of `ai_docs/plans/cdk-s3-runtime.md` section 12,
with sections 4.1–4.3 and 10 as the specification, amended by the rulings the brief
`ai_docs/handoffs/briefs/cdk-s3a.md` names: B3/R49 (one guard, no process-wide patching), review
minor m20 (the widened forbidden set), B4 (the transports are specified once, here) and R27 (the
store clock is the one clock). S2a's surface is read from `evidence-s2a.md` beside this file; the S4
re-export list is `ai_docs/plans/cdk-s4-kit.md` section 3.1 and its R-S3-4 to R-S3-6.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `00cd6f4` | Add the connector emit guard, bounded HTTP client and credential references (CDK S3a) | `connectors/guard.py`, `connectors/http.py`, `connectors/credentials.py`, `tests/unit/test_connector_guard.py`, `test_connector_http.py`, `test_connector_credentials.py` (all new, 1705 lines) |
| 2 | (this commit) | Record the S3a evidence | this file (new) |

No file outside the brief's "own" list was modified: `git show --stat 00cd6f4` is exactly the six
new files. `connectors/__init__.py` is untouched, so its module list does not yet name the three new
modules; whoever owns that file may want to add them.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| The three test files before any implementation | `/tmp/hippo-s3a-red.log` | exit 2; three collection errors, each `ModuleNotFoundError: No module named 'hippo.connectors.{guard,http,credentials}'` — the shape the plan's step 1 predicts |

Because the plan's RED is a collection failure, it proves the modules are absent but not that each
assertion bites. Two further runs close that gap.

- The first implementation run (`/tmp/hippo-s3a-green1.log`, exit 1, 4 failed / 75 passed) failed on
  real assertions: three guard cases whose expected name was wrong (see override 6 below) and one
  test-side defect (`httpx`'s `json=` writes compact separators, so the recorded body was
  `{"id":"1"}`, not `json.dumps({"id": "1"})`). The three guard failures were fixed in the code, the
  byte comparison in the test.
- A mutation run emptied the guard's matcher tables in a live interpreter
  (`_FORBIDDEN_FUNCTIONS`, `_FORBIDDEN_CODE`, `_SOCKET_METHODS`, `_DATE_CONSTRUCTORS`) and re-ran
  `test_connector_guard.py`: `/tmp/s3a-mutation.log`, exit 1, **31 failed, 3 passed**. All 28
  refusal cases and the three behavioural cases fail; the three that still pass are the ones that do
  not depend on the tables (pure computation, the `FORBIDDEN_CALLS` table itself, and the
  no-patching check). No refusal case passes vacuously.

## GREEN (final tree, `00cd6f4`)

| Line | Log | Result |
| --- | --- | --- |
| Plan step 2 / the S3a line: Fake, `test_connector_guard.py test_connector_http.py test_connector_credentials.py` | `/tmp/hippo-s3a-green.log` | exit 0, **79 passed** |
| Plan step 3 lint: Ruff `check` then `format --check` over the six files | `/tmp/hippo-s3a-ruff.log` | exit 0 and exit 0; "All checks passed!", "6 files already formatted" |
| The CK7 CHECK line of `GATES.md` as spelled, less the two files no slice has created yet | `/tmp/hippo-s3a-ck7.log` | exit 0; "All checks passed!", "20 files already formatted" |
| Regression: Fake, `test_layering.py test_import_order.py test_connector_contract.py test_connector_keys.py test_connector_classify.py` | `/tmp/hippo-s3a-regress.log` | exit 1, 135 passed, **1 failed** — one pre-existing defect in an S2a test, finding F1 below |

Counts per file: guard 34, http 37, credentials 8. Counts per backend: Fake 79. No LadybugDB line
and no Neo4j run: S3a opens no store, persists no column and touches no store path (plan section 12
gives S3a no store work; the rulebook forbids a Neo4j run without a written grant).

The CK7 line names `src/hippo/knowledge/staged_records.py` and `tests/unit/test_staged_records.py`,
which are S3b's and do not exist at this commit, so Ruff would refuse the path rather than the code.
Everything else in the line ran verbatim.

Every line ran with `-W error` alone. **No anyio filter was needed and no warning was suppressed**:
none of the three test files imports `fastapi.testclient`. One case is worth naming, because a
reviewer will look for it: `test_the_guard_refuses[datetime_utcnow]` calls
`datetime.datetime.utcnow()`, which raises a `DeprecationWarning` — but the guard refuses the call
on the `c_call` event, *before* the C function runs, so the warning never fires. If that case ever
reports a `DeprecationWarning` instead of an `EmitSideEffect`, the trap has stopped working; it is
not a filter problem.

Nothing in this slice reads `.rag-dev-data/`, a real credential or a real token. Every secret in the
tests is a made-up string placed in a `monkeypatch.setenv` variable or a `tmp_path` file the test
creates and `chmod`s itself.

## The full forbidden set

`guard.FORBIDDEN_CALLS` is one sorted tuple of 44 dotted names, the single source of truth: the
module resolves each name at import and sorts it into the matcher it needs, and
`test_the_forbidden_set_is_the_plans_names_plus_m20s` pins the tuple byte for byte. Plan section 10.1
supplies every name except the five marked **m20**.

```text
_posixsubprocess.fork_exec          os.execvpe                     time.clock_gettime        (m20)
_thread.start_new_thread            os.fork                        time.clock_gettime_ns     (m20)
datetime.date.today                 os.posix_spawn                 time.gmtime
datetime.datetime.now               os.posix_spawnp                time.localtime
datetime.datetime.utcnow            os.system                      time.monotonic
hippo.ollama.Ollama._chat           socket.getaddrinfo             time.monotonic_ns
hippo.ollama.Ollama.chat_json       socket.socket.connect          time.perf_counter
hippo.ollama.Ollama.chat_text       socket.socket.connect_ex       time.perf_counter_ns
hippo.ollama.Ollama.embed           sys.setprofile           (m20) time.process_time         (m20)
hippo.ollama.Ollama.embed_explicit  threading.Thread.start   (m20) time.sleep
hippo.ollama.Ollama.embed_one       threading.setprofile     (m20) time.time
hippo.ollama.Ollama.pull            os.execl  os.execle            time.time_ns
httpx.AsyncClient.send              os.execlp os.execlpe
httpx.Client.send                   os.execv  os.execve  os.execvp
```

m20 also names `time.sleep`, `os.fork`, `os.posix_spawn` and `time.localtime`, which plan section
10.1 already listed; they are in the set once. "Thread start" is read as both spellings,
`_thread.start_new_thread` (the C entry) and `threading.Thread.start` (the Python one), because a
connector reaches the second far more often than the first.

A name is matched one of three ways, decided at import from what it resolves to:

| Kind | Matched by | Names |
| --- | --- | --- |
| A module-level C callable | identity, on the `c_call` event | the `time`, `os`, `sys`, `_thread` and `_posixsubprocess` entries |
| A Python function | its code object, on the `call` event | `httpx.*.send`, the seven `Ollama` methods, `threading.setprofile`, `threading.Thread.start`, `socket.getaddrinfo`, the `os.execl*`/`os.execvp*` wrappers |
| A method bound to an instance or a type | name plus owner | `socket.connect`/`connect_ex` on any `socket.socket`; `now`/`utcnow`/`today` on **any subclass of `datetime.date`**, so a `class Yesterday(date)` defined inside `emit` is refused too (`test_the_guard_refuses[date_subclass_today]`) |

The third row exists because those objects are minted fresh per call and cannot be compared by
identity. The identity lookup is deliberately reached only when the callable's `__self__` is a module
or absent: `[].append.__hash__` raises `TypeError` (a list is unhashable), and the hook runs on every
C call in the guarded thread.

## Where a ruling or the review overrode the plan

1. **m20 over plan section 10.1's set.** Five names added: `time.clock_gettime`,
   `time.clock_gettime_ns`, `time.process_time`, `sys.setprofile`, `threading.setprofile`, plus
   `threading.Thread.start` for "thread start". Marked in the table above.
2. **`sys.setprofile` being forbidden forced the guard's shape.** The guard installs and removes
   itself with the call it refuses, so a thread-local `armed` flag brackets both `sys.setprofile`
   calls; the hook returns immediately while disarmed. Without it, *leaving* the guard would trip
   the guard. `test_the_guard_nests_and_restores_a_previous_profiler` pins that a nested guard
   re-arms the enclosing one on exit and that a pre-existing profiler is put back untouched.
3. **`ProviderError.__init__` gains a trailing `detail: str = ""` beyond plan section 4.3.** The
   plan's four keywords cannot say *why* a call was malformed, and B4 requires
   `replay_transport` to refuse an unexpected request as `ProviderMalformedError` — which has
   `status=None` and would otherwise carry no reason at all. `detail` is keyword-only with a
   default, so every construction the S4 plan's section 3.1 makes
   (`ProviderTransientError(url=..., status=503, attempts=1)`,
   `ProviderNotFoundError(url=..., status=404, attempts=1)`) is unchanged; both were run against
   this code. Nothing this module raises ever puts a response body in `detail`.
4. **`guard.FORBIDDEN_CALLS` and `http.DEFAULT_LIMITS` are public beyond plan sections 4.1 and 4.3.**
   `FORBIDDEN_CALLS` is the contract in a readable form and is what the pinning test and this
   evidence read. `DEFAULT_LIMITS` exists because Ruff's `B008` refuses `limits: HttpLimits =
   HttpLimits()` in a signature; the semantics are identical (a default argument is evaluated once).
   S4's re-export list is unaffected: it takes only `forbid_effects`, `EmitSideEffect`,
   `ERROR_CLASSES`, `record_transport`, `replay_transport`, the `ProviderError` classes,
   `ProviderClient`, `resolve` and `redact_url`, and all nine were imported and exercised.
5. **`socket.getaddrinfo` is not a C callable on this interpreter.** Plan section 10.1 lists it under
   "C callables"; in CPython 3.12.11 `socket.getaddrinfo` is a Python wrapper over
   `_socket.getaddrinfo`, so it is matched by code object. The refusal is the same either way, and
   it fires earlier (at the wrapper) than it would at the C entry.
6. **A refusal names the `FORBIDDEN_CALLS` spelling, not the runtime module.** `os.fork.__module__`
   is `posix`, `os.system`'s is `posix`, and `httpx.Client.send`'s frame reports
   `httpx._client.Client.send`. The message says `emit called os.fork; ...` so that an operator can
   look the name up in the table. Owner-matched calls (row three above) keep the real object's
   qualified name instead, because the point there is *which* socket or *which* date subclass.
7. **R27, one clock: no argument added.** `ProviderClient` keeps the plan's injectable `wall_clock`
   (used only to age an HTTP-date `Retry-After`) and `monotonic` (used only for the elapsed budget).
   `wall_clock` defaults to `knowledge.access.utc_now`, the repository's only `utc_now`; the runtime
   passes the store clock. No new clock parameter exists anywhere in S3a.
8. **B3/R49, no process-wide patching.** `test_the_guard_never_patches_a_module_attribute` compares
   ten of the named callables before, during and after a guarded block and requires them identical,
   and `test_the_guard_affects_only_the_entering_thread` reads the clock on the main thread *while*
   a worker thread is inside the guard. The guard's state is a `threading.local`, not a
   `ContextVar`, because `sys.setprofile` is per thread and a `copy_context()` (which S3c's emit
   workers use, m20) can be run on a thread that never entered the guard.
9. **B4, one recording format.** `http/NNNN.json` is written from `0000.json` upward, one file per
   exchange: `request` carries the method, the redacted URL, whichever of `accept` and
   `content-type` were sent, and `body_sha256`; `response` carries the status, whichever of
   `content-type`, `retry-after` and `link` came back, and `body_base64`. `replay_transport` answers
   in file order and raises `ProviderMalformedError` on an unexpected method, URL or body hash, and
   on a request after the recording runs out.

## Findings and open questions

**F1 (blocking a clean regression run, not owned by S3a).**
`tests/unit/test_connector_keys.py:463` reads

```text
assert [path.name for path in modules] >= ["__init__.py", "base.py", "classify.py", "keys.py"]
```

which is a *list* comparison and therefore lexicographic, not the superset check its context means.
Any new module under `hippo/connectors` whose filename sorts before `keys.py` fails it: with
`credentials.py`, `guard.py` and `http.py` present the left list compares less at index 3. The
assertion the test exists for (`offenders == {}`, no `KnowledgeObject` built outside `keys.py`)
still passes — none of S3a's three modules constructs one. S3b, S3c and S4 will all hit this. The
one-line fix is a set: `assert {path.name for path in modules} >= {...}`. The file is S2a's and is
not in S3a's "own" list, so this was raised with the orchestrator rather than edited.

**Q1. `time.process_time_ns`, `time.thread_time`, `time.thread_time_ns` are absent.** Every other
clock in the set is present in both its float and its `_ns` spelling. m20 named `process_time` alone,
and the plan's set is closed, so the set was not widened past the two documents. If the reviewer
reads m20 as "the process and thread clocks", three names should be added and this evidence and the
pinning test updated with it.

**Q2. A caught violation leaves the rest of that `emit` call unguarded.** CPython unsets the profiler
for a thread when a profile hook raises, so a connector that swallows `EmitSideEffect` inside `emit`
and keeps going is no longer watched until the context manager exits. The plan names this behaviour
(section 10.1) and the runtime contains it — plan section 5.6 fails the whole sync on
`EmitSideEffect` rather than continuing — but S3c should not assume a second violation in the same
call will be reported.

**Q3. `refuse_inline_secrets` inspects the configuration model's own declared fields only.** Plan
section 10.3 says "a config model field whose name contains …", which is what is implemented. A
secret hidden in a *nested* `BaseModel` field would not be refused. Recursing is a one-line change if
S4's `check_capture` wants it.

**Q4. `ProviderClient` is not thread-safe by construction.** It wraps one `httpx.Client`, which is;
but the injected `rng`, `sleep` and the attempt counters assume one caller. The runtime calls a
connector's sync half from the main thread only (plan section 5.3), so this holds today, and a
connector that shares one client across its own threads would need its own lock.

**Q5. Recording numbering restarts at `0000.json`.** A `record_transport` over a case directory that
already holds a recording overwrites it from the start rather than appending, so re-recording a case
whose exchange count shrank leaves stale higher-numbered files that `replay_transport` would then
serve. S4a generates the goldens and can clear the directory; naming it here so that it is a decision
and not a surprise.
