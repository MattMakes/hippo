# PA8 re-sign-off, round 4: PA2-4 and the ledger at `cbed8ca`

Reviewer `architect-reviewer-22`, written 2026-09-13 (the file carries the spawn message's date).
Root tree `/Users/mascott/projects/hippo`, branch `rag-it-all-tibs`, HEAD **`cbed8ca`** ("Merge
wp/lbconn: recycle the LadybugDB connection before the driver's per-statement memory passes a
budget"). HEAD was confirmed at the start, at 21:19 after run 5 finished, and again before this file
was written. Brief: `ai_docs/handoffs/briefs/review-pa8-resign.md`, ROUND 4 paragraph. Read-only
apart from this file: no source, test, plan, ledger or evidence document was edited. **No Neo4j was
used.**

Scope, per the brief: PA2-4, the do-not-fix items, and the ledger. Every other row keeps the
disposition the three earlier reports gave it (`2026-09-12-pa8-signoff.md`,
`2026-09-13-pa8-resign.md`, `2026-09-13-pa8-resign-round3.md`). Code was read by symbol at
`cbed8ca`; line numbers below are at `cbed8ca`.

## Verdict

**`PA8: NOT SIGNABLE (PA7)`**

No review row blocks any more. **PA2-4 is CLOSED** (section 1), so every row across the four rounds
is CLOSED, unreachable and pinned, or DEFERRED by the plan to a numbered task.

What blocks is round 3's precondition, which is not a row. PA7 needs a passing full `--reverify` at
the final HEAD, and **run 5's PA7 line at `cbed8ca` failed with exit 1** (section 2). The ledger now
reads `[ ] PA7 … EVIDENCE: pending`. lbconn changed persistence, and the ledger's own rule reruns PA7
and PA8 when persistence changes. A PA8 signature cannot stand on a failing PA7.

## Runs

Root tree at `cbed8ca`, `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6. Each command's
output was captured to a log, and results were read from the summary line.

| Line | Result | Log |
|---|---|---|
| PA2, verbatim from `GATES.md` (Fake, bare `-W error` as the line is written; five files, including `test_multi_generation_support.py` and, since `b2754f6`, `test_status_code_edges.py`) | **111 passed, 1 skipped in 5.34s, EXIT 0**. Same count as run 5's PA2 line | `/tmp/hippo-pa8r4-pa2.log` |
| PA8 static, verbatim, both commands in one subshell | **EXIT 0**. `All checks passed!` and `136 files already formatted` | `/tmp/hippo-pa8r4-pa8static.log` |
| Call-site sweep `rg -n 'query_session\(\|query_access\(\|graph_for\(\|ctx\.graph\(' src/hippo` | **58 rows**. With line numbers stripped, the set is identical to round 3's sweep at `492cb4c`, and through rounds 2 and 3 to `c893a95`, the revision `session-audit.md` classifies | `/tmp/hippo-pa8r4-callsites.log` |
| PA7 | **Not re-run**, per the brief. Run 5's line **failed** (section 2) | `/tmp/hippo-orch-pa-gates-5.log` |

## 1. PA2-4 at HEAD: CLOSED

| # | Sev | Commits | Tests (gate) | Verified at HEAD |
|---|---|---|---|---|
| PA2-4 | minor (latent) | `f0df1be` (fix and tests), merged `63aae1e`; `cd358d4` (docstring); `b2754f6` (test file onto the PA2 line) | `tests/unit/test_status_code_edges.py`, 6 tests (PA2) | The node-membership counter is gone, and the code-edge count is the proven pair's own native rows. Details below |

**What the review asked** (`2026-09-11-pa2-review.md`, finding 4). `_managed_source` counted every
`CODE_EDGE_KINDS` arrow in `graph.code_out` whose source vertex was in the row's contributed node
set, with no per-pair check. The relation counter below it was gated on
`pair in row.source_generations`. Proposed fix: gate the code-edge counter the same way, or record
why node membership is exact.

**What HEAD does.**

- `_managed_source` (`status.py:110`) no longer reads `graph.code_out`. Its only relation counter
  (`:136-140`) is the predicate counter, still gated on `pair in row.source_generations`.
- `source_view` (`:81-83`) takes the pair from `graph.selected_managed_generations` and passes its
  generation to `_with_code_edges` (`:179`). That function counts the `CODE_EDGE` rows whose `kind`
  is in `CODE_EDGE_KINDS` from `store._native_relationships(generation_id=...)`
  (`store/generations.py:878`). A row without a pair gets no read.
- The review's failure scenario cannot arise. Source B's count reads only B's generation's native
  rows. The read raises `Native relationship crosses generations` rather than return an edge whose
  far endpoint is another generation's row. The only rows outside the generation it admits are the
  shared Entity/Fact closure, and a `CODE_EDGE` never ends on one of those.
- `_managed_source` takes the first pair for the source and `source_view` builds a `dict` (the last
  pair). They agree while a view holds one pair per source. Within a lane, `_selected_pairs` enforces
  that (`knowledge/projection.py:385-386`). Across lanes, the comment at `:1066-1067` says
  composition's canonicalization rejects a source with two generations; I did not trace that check,
  and the verdict does not depend on it.
- `cd358d4` corrected `_with_code_edges`' docstring once `955cc11` began serving native code arrows.
  That was `evidence-codeproj.md` finding 2.

**Tests** (`test_status_code_edges.py`, on the PA2 CHECK line since `b2754f6`). The oracle is the
whole-table `load_code_edges()`, restricted to rows whose endpoints are the generation's own
symbols and data objects. It never goes through the read under test.

| Test | What it pins |
|---|---|
| `:69` `test_a_published_code_generation_counts_exactly_its_own_code_edge_rows` | The row equals the oracle for the published generation, and `edges` is the sum |
| `:81` `test_a_staged_second_generation_adds_nothing_until_it_publishes_and_then_replaces_the_count` | At the coordinator's `seal` step, G2 is fully staged and the row still shows G1's count. After publication it shows exactly G2's count, never the sum |
| `:107` `test_a_tombstoned_code_source_shows_no_code_edges` | Tombstone: no pair and no row, while the generation's edges are retained |
| `:121` `test_an_edge_straddling_two_generations_is_refused_and_never_counted` | A crossing write is refused and the count is unchanged |
| `:138` `test_an_arrow_on_the_sources_own_vertex_is_not_a_row_of_its_generation` | **The finding's own shape.** An `INVOKES` arrow injected onto two of the source's own vertices in the held graph leaves the count unchanged. Any reintroduced `code_out` walk fails it |
| `:161` `test_a_legacy_repository_keeps_the_count_its_source_row_has_always_presented` | A legacy row is unchanged, and `_native_relationships` is never called |

`evidence-pa2f4.md` records the RED at `9a474e4`: 5 failed and 1 passed, the legacy pin. The
vertex test failed with `{'INVOKES': 1} == {'CONTAINS': 7}`. I did not re-run the RED.

**Backend coverage of the read.** The bodies of `_native_relationships`, `_edges_touching` and
`_native_rows` are byte-identical between `f0df1be` and `cbed8ca` (extracted and diffed). pa2f4's
Ladybug run (`test_status_code_edges.py test_status_access.py`, 33 passed) therefore exercised
today's read. Neo4j parity run 7 (`df05bac`, `../task-5-code-capture/neo4j-parity.md`) included
`test_status_code_edges.py`: 122 passed, 6 skipped.

### `evidence-pa2f4.md` finding 3, addressed to this review: not a row

The count is exact to the generation, not to the view. Could a proven pair's generation hold
`CODE_EDGE` rows between objects this audience cannot see? A pair is proven when **any one** of the
generation's manifest revisions is authorized (`_selected_pairs`, `projection.py:391-395`). The
question is therefore whether authorization can split one code generation. At HEAD it cannot:

- **Not by policy.** `ingest/code_generation._policy` (`:588`, called at `:934`) mints one
  `local_curated`, `mode="workspace"` `AccessPolicy` per source. `CodeGenerationInputs.policy_id`
  puts it on every artifact and span the build writes (`knowledge/code_binding.py:158-163`). `grant`
  in `knowledge/access.py` therefore gives the same answer for every artifact and span of the
  generation.
- **Not by suppression, within this ledger.** `access.py` honours artifact, revision and span
  suppressions (`:495`, `:509`, `:514`). The only `k.Suppression` constructors in `src/hippo` are
  the source tombstone (`store/generations.py:209`) and the eval harness's source event
  (`evals/rag_all_temporal.py:699`). A source suppression removes the pair and the row (`:107`
  above). Revision and artifact barriers are read only as purge (`store/snapshots._purged_revisions`,
  `reason == "purge"`). Purge has no writer at HEAD, and the Scope line puts it outside this ledger.
- **Not by selection.** No production session narrows artifacts or revisions. A grep for
  `artifact_ids *=|revision_ids *=|selected_artifacts|selected_revisions` over `query_access.py`,
  `eval_access.py`, `changeset_access.py`, `dense_session.py` and `context.py` finds nothing.

It is not a row. Its trigger is a second policy inside one source (connectors) or an artifact,
revision or span suppression (purge/retention). Both are outside Task 5's scope, whereas PA2-4's
trigger, managed code generations, had already landed with CC10. The first ledger that introduces
either trigger owns the change. The count should intersect with `authorized.native_binding_ids`, as
`projection._native_code_relations` (`:323`) already does for the arrows.

### The deferred rows still stand

Later merges touched some of their files, so round 3's six DEFERRED rows were re-read at HEAD. All
six are unchanged, and their plan lines are unchanged:

- **PA2-2** (plan `:278` → Task 16): `_selected_pairs` still tests every revision once per
  generation.
- **PA3a-11** (`:280` → Task 14): `ollama.py`, `dense_session.py` and `managed_activation.py` are
  unchanged since `492cb4c`.
- **PA3b-6** (`:281` → Task 9A): `store/ladybug.py:871` still splices `REFRESHING_PREFIX` into the
  Cypher text, and `store/memory.py:209` still passes it as `$prefix`.
- **PA4b2-9** (`:282` → Task 9): `AppContext._build_structural_graph` (`context.py:396`) is still
  patched at `test_query_snapshots.py:202,211` and `test_query_authorization_boundary.py:225,232`.
- **D4 and D5** (`:271`, `:272` → Task 16): unchanged.

## 2. Does the ledger record what it claims?

**Run 5 ran at HEAD.** The checker (`gate-check.mjs --approve --reverify`, PID 77327) started at
18:38:25 -0700, after `cbed8ca` was committed (18:37:22). It wrote its summary at 21:18. HEAD was
`cbed8ca` before, during and after the run, and the working tree held no source edits. Every line,
PA7 included, therefore ran in a process started at `cbed8ca`, not at `c893a95` or `14d0a37`.

**Run 5's results** (`/tmp/hippo-orch-pa-gates-5.log`): `UNMET: 2 (met: 6, reran: 8, previously met
reverified: 7)`, naming `GATES:PA7, GATES:PA8`.

| Gate | Run 5 | Ledger (working tree, uncommitted checker edit) |
|---|---|---|
| PA1 | PASS, 187 passed, 2 skipped in 25.55s | `[x]`, EVIDENCE matches run 5 character for character |
| PA2 | PASS, 111 passed, 1 skipped in 4.74s | `[x]`, matches |
| PA3 | PASS, 190 passed, 3 skipped in 23.64s | `[x]`, matches |
| PA4 | PASS, 117 passed in 5.82s | `[x]`, matches |
| PA5 | PASS, 187 passed, 2 skipped in 27.02s | `[x]`, matches |
| PA6 | PASS, 730 passed in 72.38s | `[x]`, matches |
| **PA7** | **FAIL, exit=1** | **`[ ]`, `EVIDENCE: pending`**. The run-4 box and its 742-passed line were removed |
| PA8 | FAIL: prose EXPECT not matched, static output clean | `[ ]`, no EVIDENCE. Correct: the checker cannot sign a prose clause |

**Why PA7 failed is not recorded anywhere.** The checker keeps the first six and last two output
lines and cuts the result to 900 characters (`gate-check.mjs:581-589`). It saves no full transcript.
PA7's progress rows filled those 900 characters by 19%, so the failing test ids and the summary
line were dropped. This review did not re-run PA7, per the brief.

What narrows the cause:

- **Tests failed; nothing timed out or crashed.** The checker reports a timeout as `timed out
  after Ns` and a killed process with ` signal=` (`gate-check.mjs:482-496`, `:572`). PA7's line
  shows neither: `exit=1` is pytest's own code for at least one failed or errored test. How many
  is not known.
- **PA7 ran about twice as long as in run 4.** The checker started at 18:38 and wrote its summary
  at 21:18. PA1–PA6 took under three minutes of test time together, so PA7 ran for roughly 2h35m
  to 2h40m, whatever the line order. Run 4's PA7 took 1:20:04. Contention is a live explanation
  beside an lbconn regression, not only a hedge.
- Run 4's PA7 passed at `14d0a37` (742 passed). The only source difference between that run and
  run 5 is lbconn: `store/ladybug.py` (+113), the Ladybug branch of `store/__init__.open_store` and
  `config.py` (+19).
- The only test added since, `test_ladybug_connection_recycle.py`, is not on PA7's line. No file on
  PA7's line changed.
- Run 5 shared the machine with two other Ladybug workloads. The code-capture checker's CD lines
  (CD9 included) ran at the same HEAD and passed. `architect-reviewer-21` was running its own
  Ladybug runs, which were still going at 21:20.
- I cannot tell an lbconn regression from an environmental failure with what was saved.

**The Status line is stale and now contradicts the working tree.** It is committed and still says
"PA1–PA7 MET by … run 4 … at source revision `14d0a37`". The uncommitted ledger has PA7 `[ ]`. The
brief treated a stale revision name as a recording item; it cannot be updated honestly until PA7
passes at the final HEAD.

**Standing recording deviation** (rounds 2 and 3): EVIDENCE lines carry `path=b6bf9549d64b/37
entries` where the recording format asks for a revision. The Status line is the revision of record.

**Round 3's ledger amendments are in place** (`dc20ccb`). PA1's CRITERIA name CC10's opt-in set
(`:10`). The Scope line points repository, archive and code-file capture at the sibling ledger and
notes that CC10 widened PA1 (`:5`).

**Neo4j parity is current.** `git diff 14d0a37..cbed8ca -- src/hippo/store` touches `ladybug.py`
and only the Ladybug branch of `open_store`; the Neo4j branch is unchanged. Run 8 (at `14d0a37`)
therefore still covers the Neo4j store, and run 7 covers `test_status_code_edges.py`.

## 3. The do-not-fix items were left alone

None of their files changed after round 3. `git diff --stat 492cb4c..cbed8ca` over `cli.py`,
`mcp_server.py`, `web/app.py`, `web/routes/pages.py`, `web/routes/sources.py` and
`ingest/managed_activation.py` is empty. `git log -S'authorization_changed' 492cb4c..cbed8ca --
src/hippo` is empty. Re-read at HEAD:

| Item | Evidence at `cbed8ca` |
|---|---|
| W12, three `authorization_changed` spellings | `cli.py:75 DENIED_CODE`, `mcp_server.py:176 DENIED_CODE`, `web/app.py:58 AUTHORIZATION_CHANGED`. Pins present: `test_the_three_copies_of_the_denial_code_are_the_same_string` (`test_managed_transport_activation.py:839`), `test_hippo_help_imports_no_serving_machinery` (`test_import_order.py:61`) |
| 4b-i F2, traceback at DEBUG only | `pages.py:136` `log.debug("ask failure detail [%s]", operation, exc_info=True)` |
| 4b-i F6, delete's uniform 404 | `delete_source` (`sources.py:605`) maps `AuthorizationChanged` (`:615`) to `404 "no such source"` (`:618`) |
| PA3a-10, `present()`'s locked transaction per call | `present` (`managed_activation.py:455`) still opens `store.transaction()` and takes `_lock_source` |

## 4. Ruling on the clause

The rule: SIGNABLE only if every remaining row is CLOSED, DEFERRED by the plan to a numbered task,
or closed as unreachable with a pinned invariant. Round 3 added a precondition: a full `--reverify`
at the final HEAD.

- **CLOSED:** PA2-4 (this round). Round 3's six CLOSED rows and one unreachable-and-pinned row
  (PA4b2-7) stand, as do rounds 1 and 2's dispositions.
- **DEFERRED by the plan:** PA2-2, PA3a-11, PA3b-6, PA4b2-9, D4, D5, re-read above.
- **Rows outside all three:** none.
- **Precondition:** **not met.** PA7 failed at `cbed8ca` in run 5, and the ledger records it
  unticked.

**`PA8: NOT SIGNABLE (PA7)`**

What would make PA8 signable, in order:

1. **Find the PA7 failure.** Run PA7's CHECK line at `cbed8ca`, with its full output captured to a
   log rather than through the checker's 900-character summary, and with `-rf` so the failing ids
   are printed. Run it without concurrent Ladybug workloads. If the failures sit in lbconn's recycle
   path, fix them and merge. If a clean run passes, the failure was environmental; say so.
2. **Record PA7 at the final HEAD.** Re-run the checker so PA7 is `[x]` with EVIDENCE from a process
   started at that HEAD. Update the Status line to name the revision and the run, and commit the
   ledger. If step 1 changes source, the PA1–PA6 lines must be re-run too.
3. **A round-5 check can then be narrow:** PA7's EVIDENCE line and the Status line. No row work
   remains.

## Noticed along the way (not rows, not blocking)

- **The activation plan still reads PA2-4 as open.** Plan `:279` says `status.source_view` "must
  attribute code edges by generation membership", and `:276` still introduces it among five
  findings that are "correct today". `63aae1e` closed it. Round 3's other plan items are corrected:
  D1 and D2 are CLOSED (`:269`, `:270`), and the eligibility text is fixed (`:255`, `:262`).
- **`evidence-cc10.md` finding 1** (`:276-281`) still says PA2-4 "needs an owner". It is a
  historical record, and the plan names the owner that closed it.
- **`test_code_projection.py` is on no gate line** in either ledger. That includes `:304`
  `test_the_status_card_and_inventory_count_the_code_edges_the_source_row_counts`, the only pin
  that the status card equals the source row. This is for the orchestrator and CD10.
- **`test_status_code_edges.py` is on PA2 (Fake) only.** Its Ladybug evidence is pa2f4's run, which
  exercised today's read (section 1). It is not on PA7's line.
- **`evidence-codeproj.md` finding 3:** two overloads sharing one native id project as a cross
  product, so the card could exceed the row. This is a CD10 item, not a PA8 row.
- **`evidence-pa2f4.md` finding 2 (cost):** each `source_view` call makes one
  `_native_relationships` read per managed source that has a pair. This belongs to Task 16's
  performance work beside PA2-2.
- **The Status line** cites "`../task-5-code-capture/neo4j-parity.md` (runs 1–5)", but that file
  now has runs 1–8.
- **The concurrent code-capture checker** (`--approve`, no `--reverify`) left an uncommitted edit
  that ticks CD1–CD10. CD10 ("Lint, formatting and independent review") is ticked on a lint/format
  EVIDENCE line. Whether CD10's EXPECT intends that is for the CD10 reviewer.
