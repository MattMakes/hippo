# Brief: CDK S2a — the connector contract, canonical keys and classification

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s2a` (branch
`wp/s2a`, base = the `rag-it-all-tibs` HEAD named in the spawn message, which is S1a's merge). You
implement Task S2a of `ai_docs/plans/cdk-s2-contract.md` section 10 (its five steps) exactly as
written, with the plan's sections 4, 5 and 6 as the contract, amended by the rulings named below and
by any review findings the spawn message names.

GOAL: `src/hippo/connectors/` exists with `__init__.py`, `base.py` (every emission and protocol record
of the design's section 1 as Pydantic contracts with validators and messages, `token_count`, the
re-exported registry definitions), `keys.py` (the builder generated from `key_template` and
`key_prefix`, reusing `knowledge/identity.py`) and `classify.py` (declaration, content, name, in that
order, reusing `readers.py`; `custom/unclassified` counted; pure), with the S2a RED tests green.

CONTEXT: design `docs/spec/connector-developer-kit.md` sections 1, 2, 5; the plan's sections 0–6, 10
(Task S2a), 12–16; S1a's evidence `ai_docs/gates/rag-it-all/cdk/evidence-s1a.md`; the S3, S4 and S6
plans' "requires from S2" sections, which your signatures must meet character for character. Rulings
in `ai_docs/plans/cdk-rulings.md` that bind S2a: R11 and R26 (`base.token_count`, the chunker's
character measure, is the one counter), R16 (every registry check is against `current_registry()`),
R24 (`PASSAGE_CHAR_BOUND = 6000`), R28 (you add public `file_key`, `commit_key` and `resource_key` to
`knowledge/identity.py`, wrapping the spellings at the plan's section 6 anchors, and nothing else in
that file; this overrides the plan's section 12 do-not-touch entry for `identity.py`), R30 (the
instance configuration contract carries `principal_map`), R31 (you supply byte verifiers for the
built-in line and byte-range locator kinds through the `verifier` attribute S1a added). Where a
ruling and the plan differ, the ruling wins; say so in your evidence.

FILES:
  - own: the seven files the plan's Task S2a step 5 stages (`src/hippo/connectors/__init__.py`,
    `base.py`, `keys.py`, `classify.py` and their tests as the plan names them), plus the one R28 edit
    to `src/hippo/knowledge/identity.py`; new `ai_docs/gates/rag-it-all/cdk/evidence-s2a.md`.
  - do NOT touch: everything else in `src/hippo/knowledge/**`; `src/hippo/ingest/**`,
    `src/hippo/codegraph/**`, `src/hippo/store/**`, `cli.py`, `remote.py`; `tests/fakes/**`,
    `tests/unit/test_layering.py`, `tests/unit/test_import_order.py` (if either fails because
    `hippo.connectors` is new, report it as BLOCKED with the failing assertion; do not edit them);
    `docs/spec/*`, `docs/rag_it_all.md`, every gate ledger, the checkpoint, `data/`, `.rag-dev-data/`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). RED tests first (the plan's
Task S2a test list), failures recorded; then the plan's steps 1–4; then step 5's commit staging only
your files, with the plan's commit message. Run the plan's GREEN lines for S2a and the CK2 CHECK line's
S2a subset (`tests/unit/test_connector_contract.py`, `test_connector_keys.py`,
`test_connector_classify.py`) and the CK7 Ruff lines over `src/hippo/connectors`. Write the evidence
file: RED and GREEN log paths, counts, the purity test's interception list, and every
ruling-over-plan override.

CONSTRAINTS: pytest only as `HIPPO_TEST_STORE=fake .venv/bin/pytest <files> -q -o addopts='' -W error
> /tmp/hippo-s2a-<name>.log 2>&1; echo EXIT $?`; never Neo4j; never `pkill -f`; stage only your
files; never push, rebase or merge. `connectors` may import `knowledge` and `ingest`; `knowledge`
never imports `connectors`. `probe` and classification are pure functions of descriptor, config and
sampled bytes: no socket, `httpx`, Ollama, subprocess or clock. No duration language anywhere.

DONE WHEN: RED recorded, then GREEN with exit 0 on the S2a lines and the Ruff lines; every "requires
from S2" signature of the S3, S4 and S6 plans that names an S2a module is satisfied verbatim (list
them in the evidence with the file and line where each is defined); the evidence file exists;
`horch done` names the commit hash, counts, log paths, overrides and open questions.

REPORT: `horch note` after each plan step; `horch tell orchestrator "[<role>] BLOCKED: ..."` only for
a question the plan and the rulings do not answer.

## Review amendments (2026-09-15, `ai_docs/reports/2026-09-15-cdk-plan-review.md`; these override the text above)

- **B2 / R48.** `RevisionInput` gains `span_policy_id: str`; the binder (S2b) will use it for every
  span. Add its validator and test here.
- **M6 / R53.** `NodeRef` gains `instance: Text = None`, admitted only on identity-only foreign
  endpoints and normalized by `normalize_provider_url`; add
  `test_identity_only_endpoint_is_keyed_by_its_declared_instance` to the keys tests.
- **M10 / R45.** Delete the R31 instruction above: you supply NO built-in verifiers. Built-in
  verifiers are S2b's table in `connectors/emit.py`; only extension locator kinds set `verifier`.
  Use `Registry.locator_kind(name)` (S1a-fix) where you need the definition.
- **M9 / R44.** `policy_record` applies the instance `principal_map`: an unmapped principal in a deny
  list makes the observation `unknown`; an allow list the mapping empties becomes `unknown`;
  unmapped allow entries are dropped and counted. One test per rule.
- **m6 / R42.** The bound message interpolates `PASSAGE_CHAR_BOUND` and names it an approximation of
  the specification's 1,500 tokens.
- **m7 / R46.** `ConnectorDescriptor` gains `extension: TypeExtension`.
- **m21.** `test_keys_is_the_only_knowledge_object_constructor_in_connectors` also flags
  `KnowledgeObject.model_validate`, `.model_construct` and `.replace` outside `keys.py`.
- **M13** (`probe_deterministic`) and **M16** (the scaffold template) are S4's, not yours.
- Base your worktree on the HEAD named in the spawn message, which includes the S1a-fix commits.
