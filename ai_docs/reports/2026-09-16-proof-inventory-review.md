# Proof inventory reuse: independent review and measurement preparation

Review base: `4c2232266b378c1f9def55bc16c1fdd8aa218ea3`

Scope: `src/hippo/knowledge/access.py`, `src/hippo/knowledge/derivations.py`,
`tests/unit/test_proof_inventory_reuse.py`, and the proof-reuse changes in
`tests/unit/test_derivation_read_reuse.py`. Unrelated concurrent worktree changes were excluded.
The implementation report was not read before this verdict.

## Specification verdict

**PASS.** The source change is narrow private plumbing, and inspection found no lost
membership, lineage, audience, lifetime, store-identity, or native-read boundary.

| Requirement | Verdict | Evidence |
|---|---|---|
| Inject the raw proof reader, not an audience-filtered inventory | PASS | `access.py:420-421` constructs `_ProofReads` for the build; `access.py:625-627` passes that same reader into derivation authorization; `access.py:281-292` injects it into per-generation `GenerationViews`. The injected object owns raw store rows and is separate from `spans`, `revisions`, and `bindings`, which remain audience-filtered inputs to `include` at `access.py:259-269`. |
| Preserve complete enumeration of nonmember dependencies | PASS | `derivations.py:179-187` scopes the raw reader by `derived_record_id`, not by generation or the selected interpretation. Each enumerated dependency then goes through the exact-member `record` check at `derivations.py:191-198`, so a persisted nonmember is refused. `test_proof_inventory_reuse.py:46-58` exercises this security case. |
| Enforce exact membership on every exact lookup | PASS | `derivations.py:147-151` performs the membership check before consulting either the inventory memo or raw reader, and `derivations.py:158-161` refuses absence. This preserves rejection after a prior non-exact read (`test_derivation_read_reuse.py:42-48`). |
| Keep one independent reader lifetime per proof | PASS | `access.py:413-420` creates a new `_ProofReads` inside every `EvidenceAccess.build`; the per-generation `inventories` map is also local to `_authorized_derivations` at `access.py:275`. `test_proof_inventory_reuse.py:72-78` confirms a second proof observes intervening corruption. |
| Enforce identical-store ownership | PASS | Both `_Inventory` and `GenerationViews` use identity checks and reject cross-store readers at `derivations.py:105-107` and `derivations.py:300-306`. `test_proof_inventory_reuse.py:81-86` covers the public injection point. |
| Preserve constructor validation order | PASS | `_Inventory` resolves the generation (`derivations.py:110-115`), validates derived capability (`derivations.py:116-117`), resolves and validates source/generation availability (`derivations.py:118-120`), and only then reads exact/revision membership (`derivations.py:121-132`). This matches the original order. |
| Preserve standalone behavior and fresh reads | PASS | The no-reader branches continue through native store generation/membership/record/dependency reads at `derivations.py:110-125`, `derivations.py:153-155`, and `derivations.py:181-183`; standalone entry points still construct fresh `_Inventory` objects at `derivations.py:327-334`. `test_derivation_read_reuse.py:61-72` verifies intervening corruption is seen. |
| Leave native and Passage reads direct | PASS | Native binding validation still uses direct `_knowledge_get` at `derivations.py:208`; Passage validation still uses direct `_knowledge_get` at `derivations.py:267`. Neither is routed through `_ProofReads`. |
| Preserve security filtering of complete lineage | PASS | Closure inclusion still requires every span, revision, binding, derived record, dependency, and view to be in the audience-visible sets at `access.py:259-269`. `test_proof_inventory_reuse.py:61-69` retains the private-secondary-input denial assertion rather than weakening it. |

## Findings

No correctness or security defects found.

Two minor test-evidence gaps do not change the source verdict:

1. `test_derivation_read_reuse.py:82-99` checks capability-before-membership ordering only through
   the standalone branch, while the newly introduced injected-reader branch is verified only by
   inspection. A future regression could reorder just the injected branch without this test failing.
2. The cached-nonexact/exact-membership test at `test_derivation_read_reuse.py:42-48` also uses a
   standalone `_Inventory`; there is no equivalent assertion with `_proof_reads` injected. The
   shared implementation currently checks membership before either cache path, so this is coverage
   debt rather than a present vulnerability.

## Quality grade

| Aspect | Grade | Reason |
|---|---:|---|
| Correctness | A | The implementation preserves all specified validation and authority boundaries. |
| Code quality | A | The optional private dependency is localized and the direct/reader branches are explicit. |
| User experience | A | There is no public API or proof-shape change. |
| Performance | A- | The reuse targets already-read typed rows and scoped memberships without broadening cache lifetime; paired measurement remains pending. |
| Robustness | A- | Security and lifetime cases are covered, with the two injected-branch test gaps noted above. |
| Documentation | A | Comments accurately state complete dependency enumeration and one-proof lifetime constraints. |

Overall: **A / PASS pending paired measurement.**

## Verification and measurement status

The benchmark was deliberately not executed because the orchestrator had not confirmed all tests
terminal. Harness path, command, syntax/lint results, and private artifact conventions are appended
after harness preparation.

Harness directory: `/private/tmp/hippo-proof-ab-luGnJKiC`

Run exactly once after the orchestrator confirms every test process is terminal:

```text
/Users/mascott/projects/hippo/.venv/bin/python /private/tmp/hippo-proof-ab-luGnJKiC/run_measurement.py
```

The driver creates a never-reused `/private/tmp/hippo-proof-ab-run-*` result root. It extracts
`4c2232266b378c1f9def55bc16c1fdd8aa218ea3` with `git archive` into a read-only baseline source
tree, imports the candidate directly from `/Users/mascott/projects/hippo/src`, and launches both
variants with the root `.venv` Python and an explicit per-variant `PYTHONPATH`. Each subprocess
verifies and reports its imported `hippo` path, uses its own fresh copy of the corpus data, opens a
512 MiB Ladybug buffer, and closes the store in `finally`.

Each result contains one cold and three warm `EvidenceAccess.build` measurements from the same
store, with `perf_counter` seconds and SQL-operation counts. Complete `AuthorizedEvidence`
dataclasses are written as canonical JSON (sorted sets and ISO datetimes) for every run. The worker
requires all four proofs to be byte-identical; the driver then requires baseline and candidate
proofs to be byte-identical. Source-tree and target-file SHA-256 values, corpus database SHA-256,
revision, import path, proof counts, proof digest, logs, and timings are preserved in the private
result root. The source tree is hashed before and after measurement and a change fails the run.

Preparation checks (benchmark not run):

- Harness Python syntax: PASS
- Driver `--help` dry invocation: PASS
- Ruff on both changed source files, both owned test files, and both harness scripts: PASS
- `git diff --check` plus explicit trailing-whitespace scan for untracked/scratch files: PASS
- Model calls: none
