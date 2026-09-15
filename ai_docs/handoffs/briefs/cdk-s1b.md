# Brief: CDK S1b — `Unit`, the widened columns and schema v8

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s1b` (branch
`wp/s1b`, base = the `rag-it-all-tibs` HEAD named in the spawn message, which is S1a's merge). You
implement section 6 of `ai_docs/plans/cdk-s1-registry.md` exactly as written, amended by the rulings
named below and by any review findings the spawn message names.

GOAL: schema v8 on Fake, LadybugDB and Neo4j (Neo4j DDL written, run only by the orchestrator): the
`Unit` record with its indexes, the six `AssertionVersion` columns (`family`, `source`, `rule`,
`weight`, `statement`, `unit_id`, outside `identity_fields`), `Generation.registry_fingerprint`,
`Connector.classification_json` (default `"{}"`, backfilled), the frozen v7 literal with the v1–v7
history intact, existing row identities unchanged, and units staged, checksummed and collected with
their generation.

CONTEXT: design `docs/spec/connector-developer-kit.md` sections 3 (store impact) and 4; the plan's
sections 3, 6, 9–12; S1a's evidence `ai_docs/gates/rag-it-all/cdk/evidence-s1a.md` (what landed, and
any ruling-over-plan override). Rulings in `ai_docs/plans/cdk-rulings.md` that bind S1b: R12
(`Connector.classification_json` is yours), R17 (v8 indexes `Unit.generation_id`, `Unit.passage_id`,
`Unit.content_hash` on LadybugDB and Neo4j), R23 (`Unit` lands here with the v8 bump in one commit;
the schema-version pins move to 8), R2 (you do not edit `ingest/*`). The design's `Unit` record
(section 4) is normative: `content_hash` is the identity hash, `embed_hash` the vector key, `prefix`
recorded. Where a ruling and the plan differ, the ruling wins; say so in your evidence.

FILES:
  - own: `src/hippo/knowledge/model.py` (the plan's section 6.1 records only), `knowledge/lifecycle.py`,
    `src/hippo/store/migrations.py`, `store/knowledge.py`, `store/authorization.py`,
    `store/generations.py`, `store/snapshots.py` (each at the plan's section 6.2 anchors);
    `tests/unit/test_registry_model.py`, `test_store_migrations.py`, `test_generation_store.py`, and
    only the named assertion lines of `test_policy_migration.py`, `test_knowledge_scoped_reads.py`,
    `test_derived_generation_store.py`; new `ai_docs/gates/rag-it-all/cdk/evidence-s1b.md`.
  - do NOT touch: S1a's `registry.py`, `builtin_types.py`, `predicates.py`, `contract.py`,
    `locators.py`; `store/ladybug.py`, `store/memory.py`, `tests/fakes/*`, `src/hippo/ingest/*`;
    `knowledge/prose_preparation.py`, `code_binding.py`, `code_history.py`, `input_binding.py`,
    `staged_prose.py`, `staged_code.py`, `embedding_cache.py`, `projection.py`, `dense.py`, `access.py`;
    `docs/spec/*`, `GATES.md`, the checkpoint, `data/`, `.rag-dev-data/`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). Baseline the plan's
section 6.5 Fake lines and record counts. RED tests of section 6.4 first, failures recorded. Then the
three commits of section 6.5 in order with the plan's messages: freeze v7 as literals (version stays
7, everything green); add v8 in one commit; stage, checksum and collect units. Run every section 6.5
GREEN line (two Fake lines, the LadybugDB line, the Ruff line) and write the evidence file: RED and
GREEN log paths, counts per backend, the anyio filter form, the v7 literal checksum, the v8 checksum,
proof that an existing generation's `generation_checksums` is unchanged across the migration, and
every ruling-over-plan override. If the budget runs short, stop at the plan's fallback split (after
commit 2) and say so.

CONSTRAINTS: pytest only as `HIPPO_TEST_STORE=<fake|ladybug> .venv/bin/pytest <files> -q -o
addopts='' -W error > /tmp/hippo-s1b-<name>.log 2>&1; echo EXIT $?`; never Neo4j (write the Cypher,
do not run it); never `pkill -f`; stage only the files you own; never push, rebase or merge. The new
`AssertionVersion` fields are not in `identity_fields`; `Generation.registry_fingerprint` and
`Connector.classification_json` are not in `identity_fields`; sealed generations re-verify (the plan's
`_evidence_row` rule). No duration language anywhere.

DONE WHEN: RED recorded, then GREEN with exit 0 on every section 6.5 line; the frozen-history test
and the LadybugDB reopen test pass; the evidence file exists; `horch done` names the commit hashes,
the counts per backend, the log paths, the two checksums, every override, the fallback point if used,
and open questions.

REPORT: `horch note` after each commit; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan and the rulings do not answer.
