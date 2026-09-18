# Brief: CDK S4c-fix — seed the loader tests' connector kinds through the registry

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s4c-fix`
(branch `wp/s4c-fix`, base = the `rag-it-all-tibs` HEAD named in the spawn message, the merge of
S4c on top of S1b).

GOAL: the three tests of `tests/unit/test_connector_loader.py` that fail on that HEAD
(`test_enabled_kinds_come_from_enabled_instances_and_the_allowlist_from_the_environment`,
`test_load_connectors_reads_the_enabled_kinds_and_the_allowlist`,
`test_serve_startup_installs_a_frozen_registry`) pass without weakening anything.

CONTEXT: S1b (merged at `9e5b93c`) made the store write path call `Registry.check_record` on every
knowledge write (ruling R39, `src/hippo/store/knowledge.py`, `src/hippo/knowledge/registry.py`
around line 280), so `seed_connectors` in the loader tests, which writes `Connector` rows of kinds
`acme` and `beta` that no registry knows, is refused with "Unknown connector kind". That refusal is
correct. Production will write such rows under the connector's own registry (`hippo connector
enable`, ruling R63 N5). The tests must therefore register the seeded kinds first: inside
`extension_scope()` (see `tests/unit/test_registry.py` and `test_connector_loader.py`'s own use of
it) with a throwaway `TypeExtension` declaring those connector kinds and their families, for the
duration of the test, never into the process default (re-review finding N1). Read the evidence
`ai_docs/gates/rag-it-all/cdk/evidence-s4c.md` and `evidence-s1b.md` first. Run the failing line to
see the traceback: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_loader.py -q -o
addopts='' -W error`.

FILES:
  - own: `tests/unit/test_connector_loader.py` only (the seeding helper and, if needed, fixtures).
  - do NOT touch: anything else. If the fix needs a source change, stop and report BLOCKED with the
    exact reason.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). Reproduce (RED log), fix,
then run `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_connector_loader.py
tests/unit/test_import_order.py tests/unit/test_layering.py tests/unit/test_registry.py
tests/unit/test_registry_model.py -q -o addopts='' -W error > /tmp/hippo-s4c-fix-green.log 2>&1;
echo EXIT $?` and the same loader file on `HIPPO_TEST_STORE=ladybug`; Ruff on the file; one commit
"Register the loader tests' seeded connector kinds through the registry". Append a short "S4c-fix"
section to `ai_docs/gates/rag-it-all/cdk/evidence-s4c.md` (that file is granted for the append).

CONSTRAINTS: the rulebook; never Neo4j; never `pkill -f`; stage only the two files; never push,
rebase or merge. Do not relax `check_record`, do not register into `REGISTRY`, do not skip tests.

DONE WHEN: both lines exit 0; `horch done` names the commit, the counts and the log paths.

REPORT: `horch tell orchestrator "[<role>] BLOCKED: ..."` if a source change is needed.
