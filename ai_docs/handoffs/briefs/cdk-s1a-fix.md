# Brief: CDK S1a-fix — apply the plan review to branch `wp/s1a`

Read `ai_docs/handoffs/fleet-worker-rules.md` first, then `ai_docs/handoffs/briefs/cdk-s1a.md` whole,
especially its final section "Review amendments", which is your task list. Work in the EXISTING
worktree `/Users/mascott/projects/hippo/.worktrees/s1a` on branch `wp/s1a` (HEAD `5930626`, five
commits on `ffb075e`, venv already built). Do not recreate the worktree, do not rebase, do not merge.
Add follow-up commits on the same branch.

GOAL: `wp/s1a` satisfies the S1a brief as amended by the review: no read-time vocabulary validators,
`Registry.check_record`, projection and citation exclusion with counts, extension evidence sources
registered with their class, the restored `pager_feed` fixture, `custom` among `ALIAS_OF`'s owners,
the m5 and m22 tests, and the two accessors below; every GREEN line of the S1a evidence still exit 0.

PRIOR WORK (the S1a worker's completion summary; evidence in
`ai_docs/gates/rag-it-all/cdk/evidence-s1a.md`): commits `5039b46` (leaf modules), `dc10058`
(registry), `7a074b2` (built-ins, `test_registry.py`), `938d657` (registry-backed validators in
`model.py`, `projection.py:656`, `answer_evidence.py`), `5930626` (evidence). Fake GREEN 110 passed;
Fake regression set 717 passed / 10 skipped, identical to baseline; LadybugDB line 133 passed / 1
skipped; CK1 Fake CHECK 255 passed / 7 skipped. `len(PREDICATES) == 32` (33 registered with
`SAME_OBJECT_AS`). Built-in fingerprint `8c13f085…`. The worker implemented R29 as a fixed table
`builtin_types.EVIDENCE_CLASS_DERIVATION` keyed `(family, source, metadata_origin)` with a refusal
`underivable_evidence_source`, dropped `pager_feed` from the fixture, added
`LocatorKindDefinition.verifier` (built-ins none, not in the fingerprint), pinned R20 and R22 by test,
and added a `malformed_template` refusal, an RLock with re-entrancy error, and TypeError guards.
Its open questions: (a) no accessor returns a `LocatorKindDefinition`; (b) a fixed table means an
extension can never register a new evidence source; (c) two fact templates with one name on one kind
are not refused; (e) a nested attribute model's class name enters the fingerprint via `$defs`.

REQUIRED, in this order (each its own commit, each green):
1. **M1 / R39.** Remove the `Annotated[..., AfterValidator(...)]` registry lookups from every model
   field commit `938d657` added (`KnowledgeObject.kind`, `Artifact.kind`, `Connector.kind`,
   `EvidenceSpan.locator_kind`, `QueryRequest.kinds`, and any other); the fields are plain `Code`
   again. Add `Registry.check_record(record) -> None` raising the same messages. Make projection and
   citations exclude and count rows of unregistered vocabulary instead of raising. Add
   `test_a_row_of_an_unregistered_kind_reads_back_outside_its_registry` and
   `test_check_record_refuses_an_unregistered_kind`. Keep every other test green; adapt only the
   tests in your two test files that asserted read-time refusal, and say which in the evidence.
2. **M8 / R40 (answers your question b).** `EvidenceSourceDefinition(name, family, evidence_class)`
   with `evidence_class` never `model_inferred` or `human_verified`; registration refuses a source
   with no class or an excluded class, and no longer refuses a source absent from the built-in table.
   Built-in sources keep their table rows. Restore `pager_feed` to `incident_extension()` with its
   class. Keep `EVIDENCE_CLASS_DERIVATION` for built-ins; document its key shape in the evidence.
3. **Accessors (your question a, and c).** `Registry.locator_kind(name) -> LocatorKindDefinition`
   beside `Registry.locator(name)`; refuse two fact templates with one name on one kind
   (`duplicate_template`), with tests.
4. **m14, m5, m22, m1** as the S1a brief's amendment section states, including the granted
   `knowledge/dense.py:182-198` edit so the structural loader skips identity predicates.
5. Rerun every GREEN line of the evidence file (Fake pair, Fake regression set, LadybugDB line, CK1
   Fake and LadybugDB CHECK lines, import-order and layering, Ruff) and append a "Review
   amendments" section to `evidence-s1a.md`: commits, log paths, counts, the tests adapted and why,
   and the new built-in fingerprint.

FILES:
  - own: the S1a brief's own list, plus `src/hippo/knowledge/dense.py` at the m22 lines only.
  - do NOT touch: everything the S1a brief forbids; `store/*`, `ingest/*`, `tests/fakes/*`; existing
    test files other than your two.

CONSTRAINTS: the S1a brief's constraints hold (pytest form with `-W error` and logs, never Neo4j,
never `pkill -f`, stage only owned files, never push, rebase or merge). `CURRENT_SCHEMA_VERSION`
stays 7 and the v7 checksum unchanged; `len(PREDICATES) == 32`; the legacy endpoint digest and span
id pins still pass. No duration language.

DONE WHEN: five commits green in order; the evidence section written; `horch done` names the
commits, counts per line, log paths, tests adapted, the new fingerprint and open questions.

REPORT: `horch note` after each commit; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a
question the briefs, the plan, the rulings and the review do not answer.
