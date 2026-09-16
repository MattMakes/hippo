# Brief: CDK r7-fix — the code findings of the CK7 review (ruling R81)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `r7-fix`
(branch `wp/r7-fix`, base = the `rag-it-all-tibs` HEAD named in the spawn message). Read the
findings table and sections 6.1, 6.2 and 9 of `ai_docs/reports/2026-09-15-cdk-code-review.md`
first; each finding's "exact fix" column is your instruction, amended only as below.

GOAL: eight findings closed, one commit each in this order, each green on its own line before the
next: F1 with F3, F2, F5, F15, F14 (test half), F11, F10.
- **F1 / F3** (`src/hippo/connectors/guard.py`, `tests/unit/test_connector_guard.py`,
  `tests/unit/test_connector_sync.py`): in `_hook`, record the refusal in the thread-local state
  before raising; in `forbid_effects`'s `finally`, raise `EmitSideEffect` for a recorded violation
  when no exception is propagating, then clear it. Tests: a connector whose `emit` swallows the
  refusal with a broad `except` and calls a second forbidden function still fails the sync and
  still fails `assert_emit_pure`; rename or fold the misnamed test as F3 says and add the real
  one-violation-per-call test.
- **F2** (`src/hippo/knowledge/predicates.py` or `builtin_types.py`, `src/hippo/connectors/emit.py`,
  their tests): `reviewed` is removed from every built-in `sources_allowed`; `emit.evidence_class`
  refuses `source="reviewed"` from a connector; a test proves `EdgeEmission(source="reviewed")` is
  `BindRefused` for every built-in predicate; CK1's tests that pin `PREDICATES` (count 32) stay
  green; the fixture connector's goldens must not move (assert byte-identity; if they move, stop
  and report BLOCKED).
- **F5** (`src/hippo/connectors/sync.py`, `testing.py`, `src/hippo/cli.py`,
  `src/hippo/web/routes/connectors.py`, tests): `ensure_connector(..., enabled: bool | None = None)`
  with the semantics the review states; every caller passes what it means.
- **F15** (`sync.py`, `tests/unit/test_connector_sync.py`): the family of a counted failure comes
  from the revision's classification, else `"unknown"`; pin with a two-family fixture.
- **F14** (`tests/unit/test_connector_sync.py` `_m11`): a second sync asserts the failed
  revision's records are absent from the new generation and the previous generation stays
  queryable.
- **F11** (`src/hippo/cli.py`, `tests/unit/test_cli_connector.py`): `--family` required on
  `connector new`; the scaffold pins do not move.
- **F10** (`src/hippo/connectors/base.py`, `tests/unit/test_connector_keys.py`): `None` joins
  `KeyValue`, with one key test proving a `symbol` ref with no signature mints the code lane's
  identity (`knowledge/identity.py` `symbol_key`).

FILES:
  - own: the files named above and their tests; new `ai_docs/gates/rag-it-all/cdk/evidence-r7-fix.md`.
  - do NOT touch: anything else; the committed goldens and the guide's marked regions must not
    change (assert both).

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). Per finding RED, GREEN,
commit ("Close CK7 review Fn: ..."). Then the CK2, CK3, CK4 and CK6 CHECK lines of
`ai_docs/gates/rag-it-all/cdk/GATES.md` verbatim (both backends where the line has two), CK1's
Fake half, and the CK7 Ruff lines. Evidence file: per finding the RED and GREEN log paths and
counts, the byte-identity of goldens and guide regions, and anything a finding's fix could not do
as written.

CONSTRAINTS: the rulebook (pytest form with `-W error` and logs, never Neo4j, never `pkill -f`,
stage only owned files, never push, rebase or merge). No identity field, schema or checksum
changes. No duration language.

DONE WHEN: the commits are green; the CHECK lines and Ruff exit 0; `horch done` names the
commits, counts per line, log paths and anything left open.

REPORT: `horch note` per finding; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the review, the brief and the rulings do not answer.
