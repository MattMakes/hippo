# Brief: CDK S1a — the ontology registry and the registry-backed validators

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s1a` (branch
`wp/s1a`, base = the `rag-it-all-tibs` HEAD named in the spawn message). You implement section 5 of
`ai_docs/plans/cdk-s1-registry.md` exactly as written, amended by the rulings named below and by any
review findings the spawn message names. The plan is the instruction; this brief tells you what binds
it and what "done" means.

GOAL: `hippo.knowledge` gains the ontology registry (`registry.py`), its leaf modules (`contract.py`,
`locators.py`, `builtin_types.py`), the built-in registrations of every kind, predicate, locator,
family, connector kind and evidence source that is a `Literal` or frozenset member today, and
registry-backed validation in `model.py`, with no persisted column change: `CURRENT_SCHEMA_VERSION`
stays 7 and `MIGRATION_CHECKSUM` stays `73720e1eaeed7c148033c269de3a7e3af0d0c167fd87e580622f5c57537787f3`.

CONTEXT: design `docs/spec/connector-developer-kit.md` sections 3 and 4 (normative API); the plan's
sections 1–5 and 9–12; the S2 plan's section 3 ("requires from S1") and the S3 plan's section 3, which
S1a must satisfy character for character. Rulings in `ai_docs/plans/cdk-rulings.md` that bind S1a:
R2 (you do not edit `ingest/prose_generation.py` or `ingest/code_generation.py`), R13 (built-in
kinds are exactly today's `OBJECT_KINDS`; no `incident`), R15 (no loader or entry-point discovery in
`knowledge`; supply `Registry.with_builtins()`, `register(..., declared_families=...)`, `freeze()`,
`use_registry()`), R16 (one current registry: `current_registry()`, `use_registry()`,
`extension_scope()` extending in place), R19 (owner-family sets as the plan's table), R20 (the
fingerprint hashes the full canonical definition), R22 (`SAME_OBJECT_AS` subject by code-point
order), R23, R29 (the evidence-class derivation table of design section 4 lives in
`builtin_types.py`; registering an evidence source with no row is refused), R31
(`LocatorKindDefinition` gains an optional `verifier` attribute; you register built-ins without one).
Where a ruling and the plan differ, the ruling wins; say so in your evidence.

FILES:
  - own: new `src/hippo/knowledge/contract.py`, `locators.py`, `registry.py`, `builtin_types.py`;
    modified `src/hippo/knowledge/predicates.py`, `model.py`, `projection.py` (the two anchors the plan
    names), `answer_evidence.py` (the three anchors); new `tests/unit/test_registry.py`,
    `tests/unit/test_registry_model.py`; new `ai_docs/gates/rag-it-all/cdk/evidence-s1a.md`.
  - do NOT touch: `src/hippo/store/*`, `src/hippo/ingest/*`, `tests/fakes/*`, `knowledge/dense.py`,
    `code_binding.py`, `code_history.py`, `lifecycle.py`, `embedding_cache.py`; every existing test
    file; in `model.py`, `_RECORD_CLASSES`, any `identity_fields`, any field whose `migrations._type`
    would change; `docs/spec/*`, `GATES.md`, the checkpoint, `data/`, `.rag-dev-data/`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). Baseline the plan's
regression set (section 5.6, the `grep -rln` set) on Fake and record the counts. Write the RED tests
of section 5.5 first and record their failures. Then the four commits of section 5.6 in order, each
green on its targeted tests, with the plan's commit messages. Run the section 5.6 GREEN lines (Fake
registry tests, the Fake regression set unchanged, the LadybugDB line) and the Ruff line. Write the
evidence file: RED and GREEN log paths, test counts per backend, the anyio filter form used, the
`PREDICATES` count (32), the checksum guard result, and every place a ruling overrode the plan. If
the budget runs short, stop at the plan's fallback split (after commit 3) and say so.

CONSTRAINTS: pytest only as `HIPPO_TEST_STORE=<fake|ladybug> .venv/bin/pytest <files> -q -o
addopts='' -W error > /tmp/hippo-s1a-<name>.log 2>&1; echo EXIT $?`; never Neo4j; never `pkill -f`;
stage only the files you own; never push, rebase or merge. Existing row identities and every existing
`Literal` value stay valid; `test_knowledge_contracts.py` and `test_code_binding.py` pass unchanged.
Refusals happen at `Registry.register`, never at emit; the S2 and S3 "requires from S1" signatures are
met verbatim. No duration language anywhere.

DONE WHEN: RED recorded, then GREEN with exit 0 on every section 5.6 line and the Ruff line; the
checksum guard and the `PREDICATES` count pass; the evidence file exists; `horch done` names the
commit hashes in order, the test counts per backend, the log paths, every ruling-over-plan override,
the fallback point if used, and open questions.

REPORT: `horch note` after each commit; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the plan and the rulings do not answer.

## Review amendments (2026-09-15, `ai_docs/reports/2026-09-15-cdk-plan-review.md`; these override the plan and the rulings above)

- **M1 (design decision, ruling R39).** Vocabulary is validated at registration, at bind (S2b) and at
  store write (S1b wires it), never on read. Do NOT implement the plan's D8 `Annotated[Code,
  AfterValidator(...)]` fields: `KnowledgeObject.kind`, `Artifact.kind`, `Connector.kind`,
  `EvidenceSpan.locator_kind` and `QueryRequest.kinds` stay plain `Code`. Instead expose
  `Registry.check_record(record) -> None` in `registry.py`, raising the same developer-facing messages
  the validators would have raised, for the binder and the store write path to call. Projection and
  citations (`projection.py`, `answer_evidence.py`, both yours) exclude rows whose kind, locator kind
  or predicate is not registered in the current registry and count them, instead of raising. Add
  `test_a_row_of_an_unregistered_kind_reads_back_outside_its_registry` (a row written under an
  extension is read back, without error, in a registry that lacks it) and a test that
  `check_record` refuses that row. Commit 4's title becomes "Check kinds, locators and predicates
  through the registry at bind and write".
- **M8 (R29 amended by R40).** An extension evidence source registers with its class:
  `EvidenceSourceDefinition(name, family, evidence_class)`, `evidence_class` never `model_inferred` or
  `human_verified`. Registration refuses a source whose definition lacks a class or names an excluded
  one, not a source absent from the built-in table. Built-in sources keep their rows in
  `builtin_types.py`'s table. The plan's shared fixture `incident_extension()` keeps `pager_feed`,
  registered with its class. If your commit 2 already refuses sources absent from the table, fix it
  before commit 3.
- **m14.** Add `custom` to `ALIAS_OF`'s owner families. Record in the evidence that spec §6's
  `OWNED_BY → Team (work)` needs `ticket` subjects, which is Task 11's work.
- **m5.** `test_builtin_key_templates_match_the_identity_helpers` compares part names and order with
  the helper's parameters through `inspect.signature`, not only lengths.
- **m22.** Add a test that a stored `SAME_OBJECT_AS` assertion is absent from projection and from
  structural relations and that loading them raises nothing; `knowledge/dense.py:182-198` raises for a
  predicate outside `PREDICATES`, so make the structural loader skip identity predicates rather than
  raise (that edit to `dense.py` is granted to you for those lines only).
- **m1.** Ignore the plan's second description of `extension_scope()`; R16 stands as written.
- The fallback split after commit 3 still exists; use it if the added scope needs it, and say so.
