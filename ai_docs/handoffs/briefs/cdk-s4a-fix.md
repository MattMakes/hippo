# Brief: CDK S4a-fix — three kit defects found by S4b (ruling R77)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s4a-fix`
(branch `wp/s4a-fix`, base = the `rag-it-all-tibs` HEAD named in the spawn message). Read
`ai_docs/gates/rag-it-all/cdk/evidence-s4b.md` (findings 1–3 and its gotchas about the committed
goldens and the guide's marked regions) and `evidence-s4a.md` first.

GOAL: three separately committed fixes, each green:
1. `testing._parse_failures` reads S3c's `coverage["emission"]["failures"]` (see `sync._coverage_json`
   in `src/hippo/connectors/sync.py`), so a case with a malformed record writes its `ParseFailure`
   rows to `failures.json`. Test: a copy of the fixture package under `tmp_path` with one malformed
   input record yields a non-empty `failures.json` naming the parser and the record.
2. `validate_package(update_golden=True)` also rewrites `fixtures/registry.lock.json` from
   `testing.extension_lock`, so a re-goldened package never keeps a stale lock. Test: change the
   extension in a `tmp_path` copy, re-golden, and assert the lock moved and `assert_registry_lock`
   passes.
3. `tests/fakes/fixture_connector/connector.py` declares `descriptor` as a class attribute
   (keeping the instance behaviour), so `loader._imported` can read it off the class. Test: the
   fixture connector loads through a fake entry point in `tests/unit/test_connector_loader.py`.
Then regenerate nothing unless a golden moves (it must not: the basic case has no failures and its
extension is unchanged; assert the committed goldens and lock are byte-identical after your change)
and confirm the guide test still passes (the marked regions must not change; add the class
attribute outside them).

FILES:
  - own: `src/hippo/connectors/testing.py` (the two functions), `tests/unit/test_connector_testing_kit.py`,
    `tests/fakes/fixture_connector/connector.py` (the class attribute only, outside the
    `# cdk-guide:` marked regions), `tests/unit/test_connector_loader.py` (one test); new
    `ai_docs/gates/rag-it-all/cdk/evidence-s4a-fix.md`.
  - do NOT touch: anything else; especially `sync.py`, `emit.py`, `loader.py`, the scaffold
    templates, the committed goldens, `docs/spec/cdk-guide.md`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). Per item RED, GREEN,
commit. Then the CK4 CHECK line and the CK3 Fake CHECK line of `ai_docs/gates/rag-it-all/cdk/GATES.md`
verbatim, the kit file on LadybugDB, and the CK7 Ruff lines. Evidence file: RED and GREEN log paths
and counts, and the byte-identity check of the committed goldens and lock.

CONSTRAINTS: the rulebook (pytest form with `-W error` and logs, never Neo4j, never `pkill -f`,
stage only owned files, never push, rebase or merge). No duration language.

DONE WHEN: three commits green; the CK4 and CK3 lines, the LadybugDB kit run and Ruff exit 0; the
committed goldens, lock and guide test unchanged; `horch done` names the commits, counts and logs.

REPORT: `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a question the brief and the
evidence files do not answer.
