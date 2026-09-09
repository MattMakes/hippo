# E1 — hippo on territory-updater (real repo, real Ollama)

Run 2026-09-08/09 on `code-graph` tip `39e46de` (worktree `.worktrees/e1`, branch `wp/e1`, only this
report committed there). Real Ollama on the host throughout: `qwen3.8:latest` (chat) and
`nomic-embed-text` (embeddings). Scratch server on port 8014, `HIPPO_DATA_DIR=/tmp/hippo-e1/data`,
`HIPPO_STORE=ladybug`, `HIPPO_OPENIE_WORKERS=1`. Never touched port 8000/7687/7474, `data/`, or the
containers `hippo-app-1`/`hippo-neo4j-1`. Per the orchestrator's request mid-run, the server was
brought up **before** the source was added (so indexing progress was watchable on the Sources page
the whole time) and was left running for the entire task.

## Verdict

Asking this repository questions works, and for a straight "what does X do" / "where is X called" /
"trace this error" question against an identifier or a pasted stack trace it is genuinely
impressive: every one of five such questions (1, 2, 3, 9, 10a) came back with the exact right
function, the exact right caller, or a multi-step root-cause trace that correctly identified the one
line and the one variable responsible for a synthetic `TypeError`, citing the commit message that
explained the surrounding feature along the way. The system also did the right thing on the two
questions it had no business answering: a pure-prose README question (8) showed no Code graph card
and no anchored chips, and a question about the *external* Maricopa County Assessor website's own UI
behavior (10b, mine) was honestly refused rather than hallucinated. But two questions land badly, and
both trace to real, reproducible causes rather than bad luck: "which commits touched the export
worker" (4) only surfaces one of two commits that actually touched those files, because a purely
descriptive phrase never anchors on a symbol and the dedicated commit-history machinery therefore
never engages — arguably a UX gap rather than a bug, since it is the documented, deliberate boundary
of the feature. "Which code reads or writes the `territory` collection" (6) is flatly wrong: it
answers with a test helper, because the extractor's MongoDB classifier only recognizes the PyMongo
attribute-chain idiom (`db.archive_orders.insert_one(...)`) and this app uses the official Node
driver's call-based idiom (`db.collection('territory').findOne(...)`) everywhere, so the graph holds
essentially zero READS/WRITES edges for a real Node/MongoDB app. Along the way, indexing this
repository's git history hit a second, more serious defect: a legacy commit that once vendored a
prebuilt binary library crashes the *entire* indexing job with an uncaught `UnicodeDecodeError`
instead of being skipped like a slow commit would be — confirmed and worked around for this run only
in a scratch script, never in `src/` or `tests/`.

## The ten questions

| # | Question | Verdict | Timing |
|---|---|---|---|
| 1 | What does `runWorkerLoop` do? | **Correct** | 9199 ms |
| 2 | Where is `runWorkerLoop` called? | **Correct** | 12313 ms |
| 3 | Stack trace ending `TypeError: ... 'territoryType'` — why would this happen? | **Correct**, impressive | 11527 ms |
| 4 | Which commits touched the export worker? | **Partial** | 1643 ms |
| 5 | How does the export queue keep the worker alive? | **Correct** | 2472 ms |
| 6 | Which code reads or writes the `territory` collection? | **Wrong** | 14102 ms |
| 7 | What tests cover the NWS export? | **Correct** (not exhaustive) | 2711 ms |
| 8 | How do I seed an admin user? | **Correct** | 2617 ms |
| 9 | What does the DNC lookup do when the assessor site returns nothing? | **Correct**, impressive | 12218 ms |
| 10a | What does `claimNextJob` do? (mine — expected to nail) | **Correct** | 12214 ms |
| 10b | What does the Maricopa County Assessor's website show for multiple owners? (mine — expected to miss) | **Refused**, correctly | 3159 ms |

Screenshots: `shots/00-source-page-code-graph.jpg` (Source page, used in place of a Status-page code
card: `GET /api/status` does return a populated `code` key, built by `status.py`'s `_code_card`
(`symbols`, `data_objects`, `code_edges`, `commits`, `languages`, `unresolved_calls`,
`history_skipped`), but the 17-line `status.html` partial never renders it — confirmed by grep, no
`code`/`symbols`/`code_edges` reference in the template. Not filed as a Defect since nothing is wrong
functionally, just an unrendered field; worth a UI-polish note alongside the Ask-page summary-line one
below) and `shots/q<N>-*.jpg` (one or more per question — Answer + expanded "How the model reasoned" /
"The relations the model read"). Trace
JSON for every question (via a no-op `/api/simulate` replay of the real trace, see Methodology) is in
`traces/q<N>.json`; the four baseline re-asks are in `traces/baseline/`.

### Methodology note: how the trace JSON was captured

Every question was asked through the real **Ask page** in a browser (Chrome, via the
claude-in-chrome MCP tools), which is what a user sees — screenshots come straight from that. The
Ask page itself does a normal server-rendered `POST /ask`, not a `fetch` to the JSON `/api/ask`
endpoint, so there is no network response to intercept. Re-asking each question a second time
through `/api/ask` to get JSON would have doubled the real-Ollama cost for no reason: instead, each
Ask page answer links to "Analyze this question", whose URL carries a `trace_key`
(`/analyze?key=...`), and `POST /api/simulate {"trace_key": ..., "overrides": {}}` replays that exact
stored trace with zero LLM calls beyond one embed (confirmed empirically: replay `timing_ms.total`
values are 1–2 orders of magnitude smaller than the original ask, e.g. Q2's original was 12313 ms,
its replay's `timing_ms` was 34.6 ms) and returns the full `trace.to_dict()`. This is the same seam
QA3 used to replay a trace for the settings-simulate check. The **displayed** timing in the table
above is always the real, first-ask wall time from the Ask page UI, never the replay's.

---

### Q1 — "What does `runWorkerLoop` do?"

**Answer**: "It runs a continuous, fault-tolerant loop that claims, processes, and marks jobs as
failed, ensuring the worker remains alive despite transient errors until explicitly stopped."

**Reasoning** (`shots/q1-runworkerloop-what.jpg`): a five-step walkthrough of `workerLoop.js`'s
`async function runWorkerLoop({...})`, correctly identifying the `while (!isStopping())` loop, the
`claimNextJob()`/`emit(job)`/`processJob(job, {emit})`/`markFailed` sequence, and even quoting the
module's own JSDoc ("The export worker's forever-loop... is never restarted... the loop must not be
able to exit").

**Seed chips**: anchored `runWorkerLoop` (identifier, weight 1.0); dense: `init`, `tests.queue-unit-tests`,
`_tickLoop`, `runWorker` (a *different*, same-named function in `server/logic/dnc-refresh-job.js` —
a real naming collision in this codebase that the dense-similarity chip correctly surfaced as a
neighbour, not a false anchor).

**Code graph block** (`Title: Code graph`, S2.15 grammar): `server.logic.queue.workerLoop
-[CONTAINS 1.00 syntax]-> server.logic.queue.workerLoop.runWorkerLoop`,
`server.services.exportQueueService -[IMPORTS 0.95 import_path]-> server.logic.queue.workerLoop`,
`server.services.exportQueueService.init -[INVOKES 1.00 same_file]-> server.services.exportQueueService._tickLoop`,
plus 15 more (truncated at `code_triples_chars`).

**Top-5 passages**: commit `221c6b42c7` (fix commit) · `workerLoop.js :: runWorkerLoop` · `workerLoop.js`
(module header) · `exportQueueService.js :: init` · `exportQueueService.js :: _tickLoop`.

**Facts kept**: 1 (`workerloop js` *calls* `markfailed`, score 0.90).

**Select pass**: ran (`code_select` gate: `used_code_seeds=True`) — kept 6, dropped 4, expanded 1
(`workerLoop.js :: runWorkerLoop` itself, appended after the kept list per S2.14).

**Evidence**: `server/logic/queue/workerLoop.js:22-54` (the function, verbatim matches the answer);
`server/logic/queue/workerLoop.js:1-15` (the JSDoc the model quoted).

---

### Q2 — "Where is `runWorkerLoop` called?"

**Answer**: `server.services.exportQueueService._tickLoop` — exactly right.

**Seed chips**: same anchor set as Q1 (identical question stem).

**Code graph block**: includes `server.services.exportQueueService.init -[INVOKES 1.00
same_file]-> server.services.exportQueueService._tickLoop` and the CONTAINS/IMPORTS chain connecting
`workerLoop` to `exportQueueService`, but **no `_tickLoop -[INVOKES]-> runWorkerLoop` edge exists at
all** — confirmed, not just truncated: `hippo path server.services.exportQueueService._tickLoop
server.logic.queue.workerLoop.runWorkerLoop` (run directly against the CLI after the fact) returns
only the CONTAINS/IMPORTS chain shown above, with no INVOKES hop, and `hippo blast
...runWorkerLoop --depth 2` (below) lists only modules at Level 1, never `_tickLoop` itself. Root
cause: `server/services/exportQueueService.js:7` imports via destructuring,
`const { runWorkerLoop } = require('../logic/queue/workerLoop')`, then calls it bare at line 39
(`await runWorkerLoop({...})`) — the same CommonJS pattern behind Defect 2's `db-service` calls in
the `hippo path` output below, all of which resolve at `0.50 fuzzy_name` rather than a proper
import-based edge. The resolver has no rule for a destructured `require` binding, so a bare call
through one never produces an INVOKES edge either. The answer was still exactly right, but it came
from the LLM reading the `#5 exportQueueService.js :: _tickLoop` passage's own source text
(`await runWorkerLoop({...})`, `server/services/exportQueueService.js:39`), not from the graph
knowing the caller — worth flagging as a second, smaller instance of the CommonJS-resolution gap
described in Defect 2.

**Facts kept**: 2 (`workerloop js` *calls* `markfailed`, 1.00; `workerloop js` *contains* `worker`,
0.87).

**Select pass**: kept 6, dropped 4, expanded 1 — same shape as Q1.

**Evidence**: `server/services/exportQueueService.js:35-51` (`_tickLoop`'s body), line 39
(`await runWorkerLoop({...})`).

---

### Q3 — Node stack trace, `TypeError: Cannot read properties of undefined (reading 'territoryType')`

Pasted question (5 frames + the error line, per the brief):
```
at processJob (server/logic/queue/processJob.js:99:56)
    at runWorkerLoop (server/logic/queue/workerLoop.js:42:13)
    at _tickLoop (server/services/exportQueueService.js:39:5)
    at init (server/services/exportQueueService.js:32:3)
    at Object.<anonymous> (server/index.js:12:3)
TypeError: Cannot read properties of undefined (reading 'territoryType')

Why would this happen?
```

**Answer** (`shots/q3-stacktrace-1.jpg`, `-2.jpg`): a five-step trace that (1) located line 99 exactly
and quoted the real ternary `const territoryType = isSelection ? resident.territoryType :
job.territoryType`, (2) enumerated both branches, (3) traced `job`'s and `resident`'s provenance back
through `runWorkerLoop` → `claimNextJob()` and `_residentsFor(job)` → `await _residentsFor(job)`, (4)
correctly reasoned from `job.kind === 'selection'` that a **selection** job stores the territory type
on the *resident*, not the *job*, and (5) concluded the likely cause is `resident` being `undefined`
because `_residentsFor(job)`/`TerritoryService.getAddressesByIds` returned an array containing an
unresolved entry. This is exactly the real root-cause shape: `processJob.js:99`'s ternary access is
the crash site, and `_residentsFor` (`processJob.js:62-67`)'s own docstring ("Ids that no longer
resolve are dropped rather than failing the job") is precisely the invariant that, if violated,
produces this crash.

**Seed chips**: all 5 stack frames anchored as `stack_trace` at decaying weight — `processJob.js:99`
(1.0), `workerLoop.js:42` (0.8), `exportQueueService.js:32` (0.512), `server/index.js:12` (0.4096),
`exportQueueService.js:39` (0.32) — plus one dense chip, `server.services.import-service`. `used_code_seeds=True`.

**Code graph block**: `server.logic.queue.processJob -[CONTAINS]-> ...processJob`,
`server.services.exportQueueService -[IMPORTS]-> server.logic.queue.workerLoop`,
`server.logic.queue.workerLoop -[CONTAINS]-> ...runWorkerLoop`, `server.logic.queue.processJob
-[IMPORTS]-> server.services.db-service`, `server.index -[IMPORTS]-> server.services.db-service`,
`server.services.exportQueueService -[CONTAINS]-> ..._tickLoop`, plus more.

**Top-5 passages**: `workerLoop.js :: runWorkerLoop` · `exportQueueService.js :: init` ·
`processJob.js :: processJob (part 1)` · `exportQueueService.js :: _tickLoop` · commit `221c6b42c7`.

**Facts kept**: 0 — the whole answer came from the code graph and lexical anchors, none from OpenIE
facts (`"Found through the graph: 0 fact(s) kept, 0 seed entities..."` — the UI's summary line only
counts *entity* seeds, so it reads as "0 seed entities" even though 5 symbol seeds fired; see
Surprises).

**Select pass**: kept 8, dropped 2, expanded 1.

**Evidence**: `server/logic/queue/processJob.js:99` (the exact line and ternary), `:62-67`
(`_residentsFor`'s selection/territory docstring).

---

### Q4 — "Which commits touched the export worker?"

**Answer**: `221c6b42c7` only.

**Reasoning**: the model explicitly scanned the retrieved text for commit hashes, found exactly one
(`221c6b42c7`), verified its description matched "the export worker", and explicitly noted it found
no *other* commit hash or history entry in what it was given — an honest, correctly-reasoned answer
given its input, just given incomplete input.

**No Code graph card at all** — confirmed via trace: `used_code_seeds=False`, `used_dpr_fallback=True`,
`trace.history == []`. "The export worker" is pure natural language with no identifier, stack frame,
exception name, fenced code or diff in it, so `find_anchors` returns nothing and the question falls
back to plain DPR over all 1056 passages, identical to how a prose-only memory would behave — **this
is the documented, deliberate fidelity boundary** (Ruling 1a/1b in `PLAN.md`), not a bug. Dense code
seeds exist (2 of them) but dense seeds never flip `used_code_seeds`, so the answer-block, `trace.history`
and the whole commit-history machinery never engage.

**Ground truth**: `git log --first-parent -- server/logic/queue/workerLoop.js
server/services/exportQueueService.js` lists **three** commits: `221c6b42c7` (HEAD), `344b80b57b`
("Territory import: dual-upload, tabulated diff, crash-safe commit (#16)"), and `e352238` (a 2026-04-14
merge that only ever appears in `.git` history, never in the working tree — see Defect 1; it was the
one commit `history_skipped` during indexing, confirmed below). Of the two commits that actually made
it into the graph, the trace's own retrieved passages (fetched via the same trace-key replay) show
`344b80b57b` **was** ranked among the passages the DPR fallback considered (score 0.80, 4th among
commit passages) but never reached the top-5 slice sent to the LLM, because two *non-commit*
documentation passages ranked higher by raw embedding similarity (1.0 and 0.96) than every commit
passage including the one that was used (0.91). So this is a genuine retrieval miss on top of the
by-design anchor gap: even within the DPR-fallback path, a highly-relevant commit passage lost the
`qa_top_k=5` cut to two unrelated docs.

**Evidence**: `git log --oneline --first-parent -- server/logic/queue/workerLoop.js
server/services/exportQueueService.js` → `221c6b42c7`, `344b80b57b`, `e352238`.

---

### Q5 — "How does the export queue keep the worker alive?"

**Answer**: "By moving the try/catch block inside the while loop so that errors are caught, logged,
and the loop continues after a 5-second backoff, rather than exiting the process." — correct, and
matches the real mechanism (`ERROR_WAIT_MS = 5_000` in `workerLoop.js:20`) exactly, including the
5-second figure.

**No Code graph card** — `used_code_seeds=False`, `used_dpr_fallback=False` (facts survived the
filter; PPR ran normally, just with no lexical code anchor). The answer's precision came entirely
from **prose OpenIE over the commit message** — the top-5 passages include the commit `221c6b42c7`
passage directly (rank 4) and three Operations Runbook sections; "Facts the model kept" are OpenIE
triples pulled straight from the commit body: `job` *goes out over* `export queue` (1.00), `worker
failed` *means* `export queue worker died on a job` (0.92), `running` *is a state of* `export queue
job` (0.90). This demonstrates the prose+commit-message side of the feature working well even without
ever touching the symbol graph.

**Evidence**: `server/logic/queue/workerLoop.js:20` (`ERROR_WAIT_MS = 5_000`), the HEAD commit message
(quoted verbatim in the passage: "On error: log, back off 5s, go round again. The loop can now only
exit via shutdown.").

---

### Q6 — "Which code reads or writes the `territory` collection?"

**Answer**: `tests.test-helper.seedTestData` — **wrong**. The real answer is
`server/services/territory-service.js`, `server/logic/import/applyRun.js`,
`server/logic/import/rollbackRun.js`, `server/services/backup-service.js`,
`server/services/import-service.js` and `server/services/db-init.js` (all confirmed by
`grep -rl "collection('territory')" server`), none of which the answer names.

**Root cause, confirmed precisely**: `meta["code"]["edges_by_kind"]` for this whole 433-symbol,
95-file repo is `{CATCHES: 2, CONTAINS: 338, IMPORTS: 176, INVOKES: 400, RAISES: 2, READS: 2}` — **zero
WRITES edges, two READS edges, in the entire codebase**, against 130+ real `db.collection('name').method()`
call sites (`grep -rn "db.collection(" server | wc -l` → 130). The Code graph block for this question
(`shots/q6-territory-collection-2.jpg`) confirms it directly: 21 relations shown (`+53 more`), every
single one CONTAINS/IMPORTS/INVOKES — not one READS or WRITES, even though `server.routes.api.territory
-[IMPORTS]-> server.services.territory-service` is right there in the block, meaning the graph knows
the two modules are connected but has no edge saying *what* `territory-service` does to the `territory`
collection. Because no `DataObject` node named `territory` exists at all (there is nothing to attach a
READS/WRITES edge to), the identifier anchor `territory` (weight 1.0) falls back to matching the
**module** `server.routes.api.territory` — the route *file*, which happens to share the literal name
— which is a coincidental, misleading match rather than the intended collection. This is Defect 2
below, and this question is its direct, reproducible symptom.

**Select pass**: kept 7, dropped 3, expanded 1 (all still wrong content, since the underlying graph
has nothing right to select).

**Evidence**: `src/hippo/codegraph/data_access.py:271-284` (`mongo_hit`, the root cause); real call
sites e.g. `server/services/territory-service.js` (multiple `db.collection('territory')...` calls).

---

### Q7 — "What tests cover the NWS export?"

**Answer**: "The NWS export is covered by unit tests in `tests/queue-unit-tests.js` (specifically
testing `nwsCsvBuilder` functions like `buildNwsCsv` and `mapRow` for postal code formatting and
capitalization) and integration tests in `tests/routes-integration-tests.js` (testing the `GET
/export-nws/:variant` endpoint)." **Verified accurate** against the repo: `tests/queue-unit-tests.js:16`
does `const { buildNwsCsv, mapRow } = require('../server/logic/nwsCsvBuilder')` and has ~14 tests
named `nwsCsvBuilder: ...`; `tests/routes-integration-tests.js:367` is literally titled `'GET
/export-nws/:variant: returns NWS-compliant CSVs'`, and `server/routes/api/territory.js:895` defines
`router.get('/export-nws/:variant', ...)`. **Not exhaustive** — the repo also has a second NWS test
surface the answer didn't mention (`tests/unit-tests.js:1145-1201`, testing `nwsExportBuilder.js`'s
`buildNwsCompleteCsv`/`buildNwsSimplifiedCsv`/`mapNwsStatus`, plus a second integration block at
`tests/routes-integration-tests.js:328` for `/territories/lookup/export`), but everything the model
*did* say is real and correctly cited, so the verdict is Correct rather than Partial.

**No Code graph card** — `used_code_seeds=False` (no literal identifier in the question); top-5
passages include the commit that introduced NWS export, `nwsCsvBuilder.js :: buildNwsCsv`, and both
of the test files it cited by exact line range.

---

### Q8 — "How do I seed an admin user?"

**Answer**: "Run `node scripts/seed-admin.js <email>` with `MONGODB_URI` set in the environment, then
enter a password when prompted." — matches `README.md:12-15` exactly.

**No Code graph card, no anchored chips** — confirmed via trace: `used_code_seeds=False`, 3 dense
symbol seeds exist (`scripts.seed-aspire-admin`, etc.) but, per design, dense-only seeds never flip
`used_code_seeds`, so no Code graph card renders. This is exactly the fidelity behavior the brief
asked to verify.

**Facts kept**: 4, all OpenIE triples about `scripts/seed-admin.js` from the docs (`creates admin
account` 1.00, `upserts row in users` 0.94, `is idempotent` 0.89, `requires mongodb uri` 0.89).

---

### Q9 — "What does the DNC lookup do when the assessor site returns nothing?"

**Answer**: "The lookup is marked as failed, the Current Owner column remains blank (showing a
dash), and the app stamps the time of the attempt, which can misleadingly result in a recent
'Enriched' time or a 'Valid DNC' chip." This is not a paraphrase — it is close to verbatim from
`server/docs-wiki/04_dnc_guide.md:202`: *"The lookup failed — nothing was read from the assessor's
website. Be careful with these: the app still stamps the time of the attempt, so a failed row can
show a recent 'Enriched' time and even a 'Valid DNC' chip. The giveaway is a dash in the Current
Owner column."* Confirmed correct against the actual current implementation too:
`server/logic/scraper/scrapeDncDetails.js:115-120` sets `apn: null, assessorOwner: null, mailingAddress:
null` on an empty result, and `server/services/dnc-service.js:98` unconditionally sets `enrichedAt: new
Date()` regardless of success — exactly the "stamps the time of the attempt" behavior the doc and the
answer both describe.

One nuance worth recording: this repo has **two** DNC-lookup implementations — a legacy standalone
Puppeteer script (`server/dnc-lookup/getAPN.js`, apparently unused/dead code alongside `src_old/`)
and the current, live-app path (`server/services/dnc-service.js` + `server/logic/scraper/scrapeDncDetails.js`
+ `server/routes/api/dnc.js`, documented in the docs-wiki). My own pre-run research (reading the code
before asking) targeted the legacy script; the graph correctly anchored on the *current* feature
instead, via the `DNC` identifier chip resolving to `server.routes.api.dnc`, and gave the more
accurate, more authoritative answer than my own hypothesis.

**Seed chips**: anchored `DNC` (identifier). **Select pass**: kept 2, dropped 8, expanded 1 (the two
kept passages are exactly the two doc sections quoted above).

---

### Q10 — mine

**(a) "What does `claimNextJob` do?"** — expected to nail; it did. **Answer**: "It atomically claims
the oldest queued export job by finding the first document in the `export_jobs` collection with
status 'queued', updating its status to 'running' and setting the `startedAt` timestamp, and
returning the updated document (or null if none exists)." Matches `server/logic/queue/claimNextJob.js:10-22`
exactly, including the atomicity point the function's own comment stresses (mongodb driver v6's
`findOneAndUpdate` returning the document directly).

**(b) "What does the Maricopa County Assessor's website show when a property has multiple owners on
the deed?"** — expected to miss, and it correctly refused rather than hallucinate: *"The provided
text does not specify what the Maricopa County Assessor's website shows when a property has multiple
owners on the deed."* This is genuinely external knowledge (the live website's own UI/data shape for
an edge case) that no file in the repository documents — the repo only contains code that *scrapes*
that site, never a description of what it shows. `used_code_seeds=False`; the four facts kept were
all about `maricopa county assessor`/`maricopa county assessor's website` as an entity, correctly
insufficient to answer the specific question, and the model said so rather than inventing an answer.

---

## Baseline comparison (questions 1, 2, 5, 6)

`PUT /api/settings {"code_seed_weight": 0, "code_dense_seeds": 0, "code_select": false,
"code_structural_scale": 0}`, then each question re-asked through `/api/ask`, then restored to
defaults (`code_seed_weight=1.0, code_dense_seeds=5, code_select=true, code_structural_scale=1.0`;
confirmed via `GET /api/settings` before and after).

| # | Default answer | Baseline answer | Changed? |
|---|---|---|---|
| 1 | "a continuous, fault-tolerant loop that claims, processes, and marks jobs as failed..." | "a continuous loop that claims, processes, and tracks jobs, handling individual job failures and transient system errors by logging and retrying..." | **Same quality** — both correct, near-identical content, phrased slightly differently. `used_code_seeds` was already `False` at default for the OpenIE-fact portion of this answer, so turning code seeding off cost it nothing. |
| 2 | `server.services.exportQueueService._tickLoop` | `server/services/exportQueueService.js :: server.services.exportQueueService._tickLoop` | **Same** — still exactly correct, just less terse. |
| 5 | "By moving the try/catch block inside the while loop... 5-second backoff..." | "By moving the try/catch block inside the while loop in workerLoop.js, so that errors... are caught, logged, and handled with a backoff instead of crashing the entire loop." | **Same** — both correct; this answer was always prose-fact-driven (`used_code_seeds=False` at default too), so it is unaffected by the four settings by construction. |
| 6 | `tests.test-helper.seedTestData` (confidently **wrong**) | A five-paragraph explicit non-answer: "none of them explicitly list a specific file path... there is a possibility that the question relies on implicit knowledge not present in the text" | **Different in kind, not in correctness** — both configurations fail to name the real answer (`territory-service.js` etc.), because the root cause is the missing READS/WRITES edges (Defect 2), which no amount of seed weight can route around. The baseline is honest about not knowing; the default gives a specific, confidently wrong module name because the bare identifier "territory" — with code seeding on — resolves to the coincidentally-named `routes/api/territory` module. Turning code seeding off removes that specific wrong path, at the cost of losing the (also wrong, but shorter) direct answer. |

This matches the fidelity claim in `docs/FIDELITY.md` reasonably well for Q1/Q2/Q5, where the code
graph was never actually load-bearing for correctness — but Q6 shows the inertness claim is not
"free": even with the four settings at their fidelity-restoring values, the *underlying* graph defect
(no data-access edges) still shapes the answer's failure mode, just differently.

## CLI (against the running server)

`HIPPO_DATA_DIR=/tmp/hippo-e1/data HIPPO_HOST=127.0.0.1 HIPPO_PORT=8014 .venv/bin/hippo ...` — every
command printed `(the database is open in hippo serve; asking the server at http://127.0.0.1:8014)`
and correct output:

```
$ hippo path server.logic.queue.processJob.processJob server.logic.update-territory.UpdateTerritory.tryUpdateResidents
How server.logic.queue.processJob.processJob reaches server.logic.update-territory.UpdateTerritory.tryUpdateResidents:
server.logic.queue.processJob.processJob -[INVOKES 1.00 same_file in_branch await]-> server.logic.queue.processJob._getJob
server.logic.queue.processJob._getJob -[INVOKES 0.50 fuzzy_name await]-> server.services.db-service.DbService.connectToDB
server.services.territory-service.TerritoryService.updateResident -[INVOKES 0.50 fuzzy_name in_branch await]-> server.services.db-service.DbService.connectToDB
server.logic.update-territory.UpdateTerritory.tryUpdateResidents -[INVOKES 0.50 fuzzy_name in_branch await]-> server.services.territory-service.TerritoryService.updateResident
```
Note this is an *indirect* path (through the shared `DbService.connectToDB` dependency), not the
direct call `processJob` makes via its injected `runner` parameter (default
`UpdateTerritory.tryUpdateResidents`) — the resolver does not follow a parameter default through a
higher-order call, so no direct edge exists between them; the tool still found a real, if longer,
connecting path. Not a defect: `runner = scraperFn || UpdateTerritory.tryUpdateResidents` followed by
`runner(...)` is a dynamic dispatch the static resolver correctly declines to guess at (its own "no
edge on an unresolvable call" rule, applied correctly here).

```
$ hippo blast server.logic.queue.workerLoop.runWorkerLoop --depth 2
What depends on server.logic.queue.workerLoop.runWorkerLoop (depth 2):
Level 1: server.logic.queue.workerLoop
Level 2: server.services.exportQueueService, tests.queue-unit-tests
Subsystems: server.logic.nwsCsvBuilder: server.logic.queue.workerLoop, server.services.exportQueueService, tests.queue-unit-tests

$ hippo history server.logic.queue.workerLoop.runWorkerLoop
Commits that touched server.logic.queue.workerLoop.runWorkerLoop, newest first:
221c6b4 2026-08-31 fix(queue): keep the export worker alive, and show why a job failed

$ hippo raises server.services.geocoding-service.reverseGeocode GeocodingError
How server.services.geocoding-service.reverseGeocode reaches server.services.geocoding-service.GeocodingError:
server.services.geocoding-service.reverseGeocode -[CATCHES 0.90 resolved]-> server.services.geocoding-service.GeocodingError
```
`hippo history`'s single-commit answer for this *specific symbol* is correct and more precise than
Q4's broader "the export worker" phrasing — `344b80b` and `e352238` touched other symbols in the same
two files, not `runWorkerLoop`'s own line range.

## MCP

**Deviation from the brief, and why**: the brief says to call the MCP tools "over stdio"
(`hippo mcp`), the way QA3 did. But `hippo mcp` builds its own `AppContext.from_env()` directly and
needs the LadybugDB file exclusively (unlike the CLI's running-server fallback), which would have
required stopping the scratch server — and the orchestrator explicitly asked that the server stay up
for the whole task and not be stopped until this report was written. The same nine tools are also
served over streamable HTTP at `http://127.0.0.1:8014/mcp` by the same running process (`hippo
serve` mounts both transports), so this run exercised MCP that way instead, using the `mcp` Python
SDK's `streamable_http_client`. Same protocol, same tool implementations, different transport.

```
tools: ['hippo_ask', 'hippo_blast_radius', 'hippo_exception_path', 'hippo_explain_path',
        'hippo_history', 'hippo_remember', 'hippo_search', 'hippo_sources', 'hippo_whoami']
```
All nine present. `hippo_explain_path`, `hippo_blast_radius`, `hippo_exception_path` and
`hippo_history` were called with the same arguments as the CLI commands above and returned
structurally identical results (edges, `omega`, `provenance`, rendered `lines`) — the JSON is the same
data the CLI's text rendering comes from. The ambiguous-name case also matches QA3's finding exactly:
calling `hippo_explain_path(a="run", b=...)` (six symbols named `run` in this repo:
`server.dnc-lookup.index.run`, `server.src_old.create.index.run`, `server.src_old.index.run`,
`server.src_old.truepeoplesearch.run`, `tests.import-e2e-tests.run`, `tests.queue-e2e-tests.run`)
raised a tool error listing exactly those six candidates.

## `meta["code"]` and indexing cost

**Projection** (dry run: `readers.walk_repo` → `extract_code` → `chunk_documents`, no store, no
Ollama, on the prepared sparse checkout): 111 documents, 983 chunks, 239 chunks reaching OpenIE (210
prose + 29 code passages with a docstring ≥ 80 chars) → projected 64–84 minutes at 16–21 s/chunk,
under the 90-minute target.

**Actual**: indexing ran as a real background job on the live server (created 2026-09-08 22:21:06
UTC, ready 22:57:09 UTC) — **36.1 minutes**, comfortably inside the projection and the 90-minute
budget.

```
meta["code"] = {
  "symbols": 433, "data_objects": 2, "edges": 920,
  "edges_by_kind": {"CATCHES": 2, "CONTAINS": 338, "IMPORTS": 176, "INVOKES": 400, "RAISES": 2, "READS": 2},
  "languages": ["typescript"],
  "files_parsed": 95, "files_skipped": {"parse_error": 0, "too_big": 0, "unsupported": 1},
  "unresolved_calls_total": 5506,
  "truncated": false,
  "commits": 73, "modifies": 361, "history_skipped": 1
}
```
(`languages: ["typescript"]` is correct, not a bug — `.js` files use the TypeScript/JS walker, per
`lang_of`'s design.) `meta["counts"]` (the whole-source stats, code + prose together): 1056 passages,
1428 entities, 1806 facts, 6649 synonym edges, 84 REFERS_TO edges, on top of the code numbers above.

**`history_skipped: 1`** is precisely the same commit that caused Defect 1 (confirmed by diffing the
73 `Commit` node labels in the graph against `git log --first-parent`'s 74 SHAs — the one missing is
`e352238a659287a72dc31b368340cf63b6010d8d`). Once the crash itself was worked around (Defect 1), the
existing `code_git_timeout_s=10` per-commit budget did exactly its documented job and skipped this
one pathological commit cleanly — the *only* real bug here is the uncaught decode error; the timeout
safety net around it already works.

**5506 unresolved calls against 920 resolved edges** is a striking ratio on first glance, but it is
mostly explained rather than alarming: this is a real Express/MongoDB/Puppeteer app, so the large
majority of calls are to `axios`, `mongoose`, the native `mongodb` driver, `express`'s `req`/`res`,
Node builtins and array/string methods — all correctly outside the resolver's "in-repo only" scope,
the same rule that intentionally emits no edge for `print`/`os.path.join`/`console.log`/`sum` in the
plan's own fixture. Individual per-file counts (`server/routes/api/territory.js: 403`,
`tests/unit-tests.js: 614`) track file size and framework-call density, not obviously a resolver
failure — a closer per-file audit was out of scope for this run.

## Defects

### Defect 1 (critical) — a legacy binary-vendoring commit crashes the *entire* index job with an uncaught `UnicodeDecodeError`

**Where**: `src/hippo/codegraph/git_history.py:277`, inside `_hunks()`:
```python
command = ["diff", *DIFF_OPTIONS, parent, sha] if parent else ["show", *DIFF_OPTIONS, "--format=", sha]
result = _git(checkout, command, timeout_s)
```
`_git()` (`git_history.py:417`) defaults to `text=True`, a strict UTF-8 `subprocess.run` decode with
no `errors=` handling. Contrast with `_symbols_at()` (`:359-363`), which reads a blob at a specific
commit the *safe* way already established in the same file: `_git(..., text=False)` then
`.decode("utf-8", errors="replace")`. `_hunks()` is the one caller that doesn't follow that pattern.

**Reproduction** (found on this real repository, not constructed): commit
`e352238a659287a72dc31b368340cf63b6010d8d` ("Merge pull request #14 from
MattMakes/territory-management-map-vlKQt", 2026-04-14) vendored a prebuilt `poppler-0.62` binary
distribution under `other_files/s8-pdf-maker/node_modules/pdf-poppler/...`. Its diff against parent
`18d16f156345cdf6d6542501d86fe4199726a690` is **1,017,352,096 bytes** (~1 GB) and contains an invalid
UTF-8 continuation byte at offset 965842046, inside
`.../poppler-0.62/include/poppler/OutputDev.h`:
```
$ git -C <checkout> diff -U0 --no-renames --no-color --no-ext-diff --no-textconv \
    --src-prefix=a/ --dst-prefix=b/ 18d16f156345cdf6d6542501d86fe4199726a690 e352238a659287a72dc31b368340cf63b6010d8d \
    | python3 -c "import sys; sys.stdin.buffer.read().decode('utf-8')"
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe4 in position 965842046: invalid continuation byte
```
`subprocess.run(..., text=True)` raises this exception synchronously while decoding, *before*
`_git()` returns — so it is not a `subprocess.TimeoutExpired`, and the per-commit
`except subprocess.TimeoutExpired: history.skipped += 1; continue` guard in `read_history`'s loop
(`git_history.py:186`) does not catch it. It propagates through `read_history` →
`_read_history` (`ingest/pipeline.py:344-346`, which only catches `HistoryError`) →
`_read_chunk_index` → `run_indexing`'s generic `except Exception` (`ingest/pipeline.py:237-243`),
which sets **the whole source** to `status="failed"`, clears every passage already written, and
discards the entire code graph — not just the git history, which `_read_history`'s own docstring
promises should degrade gracefully ("A history that cannot be read is a warning, not a failed index
job... It is the one part of indexing where 'some of it' is a perfectly good answer").

**Confirmed on this run**: the first attempt (default settings, no workaround) failed exactly this
way after ~15 seconds, with the traceback ending in this exact `UnicodeDecodeError`. This is not a
one-off — the same repository being indexed with `code_history_depth` at its default (200, which
exceeds this repo's 74-long first-parent chain, so it always reaches this commit) will crash every
time, on any machine, since the byte in question is a permanent part of that commit's diff.

**Severity note on load-sensitivity**: this run's own `git diff` for that commit took 9.5 s wall time
— just under the `code_git_timeout_s=10` default. On a slower or busier machine the subprocess could
plausibly exceed 10 s first, in which case `subprocess.TimeoutExpired` *would* fire and this defect
would never be observed at all, masking it as "works fine" purely by chance. That is itself worth
flagging: the crash's reproducibility is timing-dependent at the margin, even though the root cause
(a decode call with no error handling) is deterministic.

**Workaround used for this run only** (not applied to `src/` or `tests/`): a scratch launcher script
(`/tmp/hippo-e1/scripts/serve_with_local_clone.py`, deleted with the rest of `/tmp/hippo-e1` per the
brief) monkeypatched `git_history._git` to always decode with `errors="replace"` — the same tolerance
`_symbols_at` already uses — purely so indexing could proceed with the real `code_history_depth`
default. With that workaround in place, the commit was cleanly skipped via the pre-existing,
correctly-functioning `code_git_timeout_s` path in the actual pipeline run (confirmed:
`history_skipped: 1`, and the one `Commit` node missing from the graph is exactly this SHA). Measured
in isolation, the diff subprocess alone took ~9.5 s and the Python-side `errors="replace"` decode +
hunk-regex parsing added another ~4.4 s on top — but `code_git_timeout_s` only bounds the subprocess
call itself (`_git`'s own `timeout_s=` argument to `subprocess.run`), not the Python-side parsing that
runs after it returns, so which of those two phases (or the surrounding per-file `_symbols_at`/`_modifies`
calls this commit also triggers, at up to 7,168 hunks) actually tripped the 10 s budget during the
real pipeline run was not isolated — only that the budget did trip, correctly, once the decode crash
itself was worked around. So the one and only defect filed here is the missing decode-error handling
at `git_history.py:277`; the timeout-based graceful degradation around it already works.

**Suggested fix** (not applied — QA does not edit source): make `_hunks`' `_git` call use the same
`text=False` + `errors="replace"` pattern `_symbols_at` already uses, or add `UnicodeDecodeError`
alongside `subprocess.TimeoutExpired` in the per-commit `except` at `git_history.py:186`.

### Defect 2 (major) — MongoDB READS/WRITES extraction misses the official Node driver's own idiom entirely

**Where**: `src/hippo/codegraph/data_access.py:271-284`, `mongo_hit()`:
```python
def mongo_hit(receiver: str, name: str, line: int = 0) -> Hit | None:
    """
    `db.archive_orders.insert_one(...)` -> the collection `archive_orders`, written.
    The receiver must be a chain (`a.b`), so a bare `x.find()` invents nothing.
    """
    if "." not in receiver:
        return None
    collection = receiver.rsplit(".", 1)[1]
    ...
```
This recognizes only the PyMongo-style attribute-chain idiom, where the collection name *is* the
last attribute of the receiver (`db.archive_orders`). It does not recognize the equally common, and
in this codebase the *only* used, idiom for the official Node MongoDB driver:
`db.collection('name').method(...)` — a call expression whose argument is the collection name, not an
attribute access. `grep -rn "db.collection(" server | wc -l` → **130** real call sites across
`territory-service.js`, `backup-service.js`, `import-service.js`, `exportQueueService.js`,
`claimNextJob.js`, `db-init.js` and more.

**Measured impact**: `meta["code"]["edges_by_kind"]` for the whole 433-symbol repo is `{..., "READS":
2, ...}` and has **no `WRITES` key at all** (i.e. zero WRITES edges in the entire codebase). The two
READS edges that do exist come from the one Mongoose-model usage in the (likely legacy)
`server/dnc-lookup/` scripts, which *is* the attribute-chain shape `mongo_hit`/`mongoose_hit`
recognize. Every actual, current, official-driver call site — the overwhelming majority of this
app's real database access — produces nothing.

**User-facing symptom**: Q6 above ("Which code reads or writes the `territory` collection?") answers
with a test helper instead of `territory-service.js`, and does so *confidently* rather than hedging,
because with no `DataObject` node named `territory` in the graph at all, the bare identifier
`territory` in the question resolves instead to the coincidentally same-named module
`server.routes.api.territory` (a route file), which is a misleading false-positive anchor rather than
a true miss.

**Suggested fix** (not applied): extend `mongo_hit` (or add a sibling classifier) to recognize a
`.collection('literal').method(...)` call chain and extract the collection name from the string
argument rather than the receiver's trailing attribute.

## Surprises

- **`git log --first-parent` reaches only 74 of this repository's 160 total commits.** Many commits
  live on non-first-parent branches later merged into `main`. `code_history_depth`'s default of 200
  therefore reads *all* first-parent history here regardless of its value ≥ 74 — "200 covers all 160
  commits" (my own pre-run assumption, inherited from the briefing) is not correct for a repository
  shaped like this one; first-parent depth is bounded by the first-parent chain length, not by total
  commit count.
- **The Ask page's summary line undercounts anchoring.** "Found through the graph: 0 fact(s) kept, 0
  seed entities..." (Q3) reads as if nothing anchored, when in fact 5 symbol seeds fired via stack
  traces and drove the entire correct answer — the line only counts *entity* seeds, a leftover from
  the prose-only path. Not filed as a Defect (nothing is functionally wrong — the Code graph card
  right below it does show the real anchors), but worth a UI polish note.
- **Two independent implementations of the same feature, doc-verified vs. not.** `server/dnc-lookup/`
  (a legacy Puppeteer script) and `server/services/dnc-service.js` + `scrapeDncDetails.js` +
  `server/routes/api/dnc.js` (the current, live-app path, documented in `04_dnc_guide.md`) both scrape
  the Maricopa County Assessor site. My own pre-run reading targeted the legacy script; the graph
  anchored on the current, documented one and gave the better answer (Q9).
- **A real naming collision the dense-seed mechanism handled correctly.** `runWorkerLoop`
  (`server/logic/queue/workerLoop.js`) and `runWorker` (`server/logic/dnc-refresh-job.js`) are
  different functions with similar names; `runWorker` showed up as a *dense* similarity chip on Q1/Q2
  (never as an anchor), which is exactly the intended behavior — a plausible neighbour surfaced, not
  a false lexical match.
- **The Status page's code card is populated server-side but never rendered.** `GET /api/status`
  returns a full `code` object (`symbols`, `code_edges`, `languages`, `unresolved_calls`,
  `history_skipped`, etc., built by `status.py::_code_card`), but `status.html` doesn't reference any
  of those fields — a live progress view of the code graph exists in the API and nowhere in the UI.
- **The one-worker OpenIE budget held with real margin.** 239 chunks needing OpenIE projected to
  64–84 minutes; the actual run (which also had to read git history, chunk 1056 passages and write
  the whole graph) finished in 36 minutes — under even the low end of the pure-OpenIE-only
  projection, suggesting the projection's 16–21 s/chunk figure (from the plan's own prior QA1 run) is
  a conservative upper bound for this model/machine combination, not a live bottleneck here.

## Cleanup

Server left running per the orchestrator's request until this report was committed, then stopped.
`/tmp/hippo-e1` removed except `shots/`, per the brief.
