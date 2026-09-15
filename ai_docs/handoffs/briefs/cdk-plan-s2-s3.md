# Brief: implementation plans for CDK slices S2 (contract, classify, keys, render, emit) and S3 (runtime)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. You work in the ROOT tree
(`/Users/mascott/projects/hippo`) at the HEAD named in the spawn message. You write TWO files and
nothing else: `ai_docs/plans/cdk-s2-contract.md` and `ai_docs/plans/cdk-s3-runtime.md`. No code, no
tests, no commits (the orchestrator commits). Two other planners are writing `cdk-s1-registry.md`
and `cdk-s4-kit.md`/`cdk-s5-port.md`/`cdk-s6-exemplar.md` in parallel; do not write those. Program
against the registry API the design's section 3 gives verbatim; where you need something S1 does not
promise, list it under "requires from S1" rather than inventing it.

GOAL: two step-by-step implementation plans, executable by workers who have never seen the
repository, for gates CK2 and CK3 of `ai_docs/gates/rag-it-all/cdk/GATES.md`: the connector contract
with classification, canonical keys, rendering and emission-to-records (S2), and the sync runtime with
the generic staged writer, bounded HTTP and credentials (S3).

CONTEXT (read completely, in this order): `docs/spec/connector-developer-kit.md` (all; sections 1,
2, 4, 5, 6, 7, 12, 13 are your contract), `docs/spec/enterprise-graph-rag-v1.md` sections 3, 4, 5.2,
5.3 and 13.1, `docs/rag_it_all.md` sections 4.2, 5, 7.1, 7.2, 7.3, 7.6 and 9.3, the code-capture plan
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` (the FORM your plans must take) and the
prose coordinator plan `ai_docs/plans/rag-it-all-task-5-prose-coordinator.md` (the transaction and
fencing rules the runtime must keep), plus `ai_docs/reports/2026-09-12-code-capture-plan-review.md`
(what gets a plan rejected). Then the code, all of it: `src/hippo/ingest/prose_generation.py`
(`build_plain_source` and its `_capture`/`_prepare`/`_materialize`/`_install`/`_publish` shape),
`src/hippo/ingest/code_generation.py` (`build_code_source`, `CodeTreeInput`, `_write`, `_rebaseline`),
`src/hippo/ingest/managed_activation.py` (dispatch, options, ingress, failures, receipts),
`src/hippo/ingest/accepted_inputs.py`, `src/hippo/ingest/repo_capture.py`, `src/hippo/ingest/readers.py`,
`src/hippo/ingest/chunker.py`, `src/hippo/ingest/pipeline.py`, `src/hippo/ingest/build_run.py`,
`src/hippo/knowledge/build_authority.py`, `input_binding.py`, `staged_prose.py`, `staged_code.py`,
`raw_artifacts.py`, `inputs.py`, `identity.py`, `lifecycle.py`, `source_lifecycle.py`,
`generation_profiles.py`, `embedding_cache.py`, `prose_preparation.py`, `code_binding.py`, and
`src/hippo/store/generations.py` (`claim_generation_build`, `reclaim_generation_build`, the
publication compare, `IndexEvent`, `SyncState`, `LeasedWork`). Cite `file:line` at HEAD for every
claim about existing code.

DECISIONS THE S2 PLAN MUST MAKE AND STATE:
1. The exact emission records (`NodeEmission`, `EdgeEmission`, `PassageEmission`, `UnitEmission`,
   `AliasEmission`, `ParseFailure`, `EmissionBatch`, `RevisionInput`, `TypeMapping`,
   `Classification`, `ChangePage`, `Change`, `RawFetch`, `PolicyObservation`, `ExternalRef`,
   `SyncCursor`, `ConnectorDescriptor`, `ConnectorCapabilities`, `CredentialRequirement`,
   `ParserVersion`) as Pydantic `Contract`s with validators and error messages.
2. `connectors/keys.py`: the builder generated from `key_template`/`key_prefix`, its relationship to
   `knowledge/identity.py` helpers (reuse, never duplicate), the provider-instance scoping rules.
3. `connectors/classify.py`: the declaration → content → name order as code, each detector named
   with the existing function it reuses (`readers.lang_of`, `is_code_name`, `is_plain_prose_name`,
   `is_probably_binary`, SQLGlot parse), the `custom/unclassified` outcome, and the purity test.
4. `connectors/render.py`: `FactTemplate` evaluation, the edge statement rule, `embed_text` prefixes,
   `content_hash`, template versions in the fingerprint.
5. `connectors/emit.py`: the batch → records binder: identity computation, span verification against
   bytes, the evidence-class derivation table, owner-family and direction refusal messages,
   `AssertionSupport` grouping, `Unit` rows, alias candidates and the guarded kind pairs, coverage
   counts. Prove totality with the table-driven test the ledger's CK2 CRITERIA names.
6. The reverse-view hint: what a connector emits instead of a reverse edge, and how the kit records it.

DECISIONS THE S3 PLAN MUST MAKE AND STATE:
7. `connectors/sync.py`: the nine steps of the design's section 7 as named functions with their
   failpoints (reuse the coordinator's failpoint mechanism if one exists; name it), the lease on
   `SyncState`/`LeasedWork`, the cursor checkpoint rule, worker-pool `emit` with the guard that
   raises on socket, `httpx`, Ollama, subprocess and clock use, the bind step, and how the runtime
   reuses `BuildRun`/`BuildReceipt`, `build_authority`, `generation_for_inputs` and the publication
   compare instead of re-implementing them.
8. `knowledge/staged_records.py`: the generic staged writer's contract relative to `staged_prose.py`
   and `staged_code.py` (what is shared, what is new), fencing, seal, resume, and what CK3's byte
   checks measure.
9. Deletions and policy changes: the tombstone path reused (`source_lifecycle.py`), the policy epoch,
   the inventory-completeness rule, and the tests that a failed page never deletes.
10. `connectors/http.py` and `connectors/credentials.py`: the bounded client (timeout, size, retry with
    jitter, `Retry-After`, attempt and duration caps), the six error classes, `MockTransport`
    recording and replay, credential references (environment and file first), URL redaction.
11. The fixture connector CK3 tests use (in-repo, under `tests/fakes/` or `src/hippo/connectors/testing`;
    decide) and the failure-injection matrix.
12. Sizing: S2 and S3 are each one worker; if either exceeds that, split and say where.

FILES:
  - own: `ai_docs/plans/cdk-s2-contract.md`, `ai_docs/plans/cdk-s3-runtime.md` (both new).
  - do NOT touch: anything else.

DONE WHEN: both plans exist with the code-capture plan's form (goal, contract with exact signatures,
file-by-file steps with `file:line` anchors, RED test list with names, GREEN commands, the CK2/CK3
CHECK lines confirmed or replacements proposed, worktree names `s2`/`s3`, merge order, do-not-touch
lists, "requires from S1", "decisions taken", "design deviations" if any, open questions); `ruff
format --check` clean on both; `horch done` names both paths, the counts of decisions taken, and open
questions.

REPORT: `horch note` per section written; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for
a contract question the design does not answer and you cannot decide safely.
