# Brief: implementation plan for CDK slices S1a (registry and model) and S1b (schema v8)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree
(`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message. You write ONE file and
nothing else: `ai_docs/plans/cdk-s1-registry.md`. No code, no tests, no commits (the orchestrator
commits). Two other planners are writing `cdk-s2-contract.md`/`cdk-s3-runtime.md` and
`cdk-s4-kit.md`/`cdk-s5-port.md`/`cdk-s6-exemplar.md` in parallel; do not write those files.

GOAL: a step-by-step implementation plan, executable by a worker who has never seen the repository,
for the design's sections 3 and 4 as gate CK1 of `ai_docs/gates/rag-it-all/cdk/GATES.md`: the
ontology registry that replaces the closed vocabularies, the two new evidence classes, the `Unit`
record, the widened `AssertionVersion`, and the journaled schema v8 on all three backends.

CONTEXT (read completely, in this order): `docs/spec/connector-developer-kit.md` (all of it;
sections 3, 4, 12 and 13 are your contract), `docs/spec/enterprise-graph-rag-v1.md` section 3 and
section 6, `docs/rag_it_all.md` sections 5.1–5.3 and 7.3, the code-capture plan
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` (the FORM your plan must take: goals,
exact signatures, file-by-file changes, RED tests, CHECK lines, do-not-touch lists, ledger lines),
and its review `ai_docs/reports/2026-09-12-code-capture-plan-review.md` (the kind of blocker a plan
gets rejected for). Then the code: `src/hippo/knowledge/model.py` (every `Literal`, `Record`,
`identity_fields`, `LOCATOR_ADAPTER`, `GenerationEvidenceMember.record_kind`, `EvidenceClass`,
`AssertionVersion`, `ObjectObservation`), `src/hippo/knowledge/predicates.py`,
`src/hippo/knowledge/identity.py`, `src/hippo/store/base.py` (schema statements),
`src/hippo/store/migrations.py` (the journaled v1–v7 steps and frozen checksums),
`src/hippo/store/ladybug.py`, `src/hippo/store/memory.py`, `src/hippo/store/generations.py` (how
`AssertionVersion`, `ObjectObservation` and evidence members are written, read, checksummed and
collected), `src/hippo/store/snapshots.py`, `tests/fakes/fake_store.py`, and every test that names
`predicates`, `EvidenceClass`, `locator_kind`, `ObjectKind` or `test_store_migrations`
(`grep -rln` them under `tests/unit`). Cite `file:line` at HEAD for every claim about existing code.

DECISIONS THE PLAN MUST MAKE AND STATE (each with the reason and the test that pins it):
1. How a Pydantic `Literal` becomes a registry-backed validator without an import cycle: the registry
   module must not import `hippo.connectors`; built-ins are registered from a module the model can
   import; the frozen state and the test fixture that registers a throwaway extension and resets it.
2. The exact `Registry`, `ObjectKindDefinition`, `PredicateDefinition`, `TypeExtension`,
   `LocatorKindDefinition`, `FactTemplate` classes (fields, validators, error messages) matching the
   design's normative API in section 3 verbatim; where the design under-specifies, decide and mark
   it "decided by S1 plan".
3. How the existing `predicates.PREDICATES` mapping and `validate_endpoints` are preserved as
   built-ins (names unchanged), and how `owner_families`, `identity`, `canonical_direction`, `family_default`,
   `sources_allowed`, `verb_phrase` and `windowed` are filled for each existing predicate, plus the
   built-in `SAME_OBJECT_AS` identity predicate (design section 4, `AliasCandidate` row).
4. `Unit` persistence: table or label per backend, columns, the identity, membership in
   `GenerationEvidenceMember.record_kind`, how it is written, read by generation, checksummed and
   collected with its generation; how vectors key on `content_hash` through
   `knowledge/embedding_cache.py`.
5. `AssertionVersion` widening: the six new columns, their defaults for existing rows, and the rule
   that the new fields are NOT in `identity_fields` so existing ids stay stable (or, if you find that
   impossible, the migration that recomputes ids and every consumer it touches, named).
6. `EvidenceClass` gains `rule_derived` and `similarity_inferred`: every consumer of the class
   (traversal, support-group rules, status, projections) named with what changes, if anything.
7. Schema v8, including `Generation.registry_fingerprint` and `Connector.classification_json` (design
   section 2: `Json`, default `"{}"`, mutable, outside `identity_fields`, which S2 and S3 list under
   "requires from S1"): the exact DDL or Cypher per backend, the journaled migration step, what the Fake store
   needs, the reopen test on LadybugDB, and the frozen-history test.
8. The fingerprint: what is hashed, in what canonical order, the `Generation.registry_fingerprint`
   column (schema v8, outside `identity_fields`, never in `configuration_json`), how a kit connector's
   declared template and parser versions reach `configuration_json` (`prose_generation._configuration`
   and `code_generation._configuration` are the models), and the test that a template change changes
   both.
9. Sizing: S1a and S1b are each one worker; if either exceeds that, split and say where.

FILES:
  - own: `ai_docs/plans/cdk-s1-registry.md` (new).
  - do NOT touch: anything else.

DONE WHEN: the plan exists with the code-capture plan's form (goal, contract with exact signatures,
file-by-file steps with `file:line` anchors, RED test list with names, GREEN commands, CK1 CHECK line
confirmed or a replacement proposed, worktree names `s1a`/`s1b` and merge order, do-not-touch lists,
a "decisions taken" section, a "design deviations" section if any, and open questions); `ruff format
--check` is clean on it; `horch done` names the path, the count of decisions taken, and open
questions.

REPORT: `horch note` per section written; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for
a contract question the design does not answer and you cannot decide safely.
