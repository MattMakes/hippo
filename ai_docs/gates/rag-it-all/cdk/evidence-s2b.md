# CDK S2b evidence: rendering and the batch-to-records binder

Worker `backend-developer-10`, branch `wp/s2b`, base `4c0f49d` (the `rag-it-all-tibs` HEAD naming
S1a, S1b, S1b-fix, S2a, S3a and S4c as merged). Contract: Task S2b of
`ai_docs/plans/cdk-s2-contract.md` section 10, with sections 4.4, 4.5, 7, 8 and 9, amended by the
rulings and review findings the brief `ai_docs/handoffs/briefs/cdk-s2b.md` names and by its
"Amendment from the S4 re-review (ruling R63)" section.

The brief's spawn message said "both amendment sections"; the orchestrator confirmed in writing that
the one R63 section is the whole brief and that nothing else was pending, adding R62
(`evidence_source_definition`, landed in S1b-fix at `335d4e3`) and R66 (ii) (the binder never reads a
unit back by id). Both are applied below.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `ab4a7c7` | Bind connector emission batches to knowledge records (CDK S2b) | `connectors/render.py`, `connectors/emit.py`, `tests/unit/test_connector_render.py`, `tests/unit/test_connector_emit.py` (new); `connectors/keys.py` |
| 2 | `c919b51` | Record the S2b evidence | this file (new) |
| 3 | (this commit) | Read the guarded alias pairs from `predicates.SCHEMA`; make the m4 and R39 tests prove their claims | `connectors/emit.py`, `tests/unit/test_connector_emit.py`, this file |

The `keys.py` edit is three things, all required by the one granted change: `KeyPartsRefused` now
subclasses `BindRefused`, the module imports that name from `emit`, and the class docstring drops
the stale "(S2b re-parents it on BindRefused)" parenthetical and says why the re-parenting matters.
No other line of that file, and no other S2a file, is touched.

`git show --stat ab4a7c7` is exactly those five files, and commit 3 touches two of them plus this file. Nothing outside the brief's "own" list was
touched: no other S2a file, no `docs/spec`, no gate ledger checkbox, no `connectors/__init__.py`
(see "Left for S3c" below).

## RED

| Stage | Log | Result |
| --- | --- | --- |
| The CK2 CHECK line before any implementation | `/tmp/hippo-s2b-red.log` | exit 2; two collection errors, `ImportError: cannot import name 'emit'` and `... 'render' from 'hippo.connectors'` — the shape the plan's step 1 predicts |
| S2a's three files alone, at the same tree | `/tmp/hippo-s2b-red-s2a.log` | exit 0, 105 passed; the CK2 line's collection failure is the two new modules and nothing else |

The second line exists because a collection error interrupts the whole CK2 run, so the plan's
"S2a's three files pass" cannot be read off the first log.

Three test-side defects surfaced while going green and were fixed in the tests, not the code: the
totality table read a whole JSON column where it meant one key of it (the reader now takes a
`column:key` spelling); the locator messages were written with `json.dumps` spacing where
`canonical_json` is compact; and the purity scan matched the word `subprocess` in the module
docstring that says the module uses none (it now parses the source and drops the docstring first).

## GREEN (final tree)

| Line | Log | Result |
| --- | --- | --- |
| Plan step 2 / the CK2 CHECK line of `GATES.md`, verbatim, Fake | `/tmp/hippo-s2b-green.log` | exit 0, 279 passed |
| Plan step 3 regression: S2a's step 3 set plus `test_managed_input_binding.py` and `test_code_binding.py`, Fake | `/tmp/hippo-s2b-regress.log` | exit 0, 292 passed |
| Plan step 4 / the CK7 Ruff line, less the two files no slice has created yet | `/tmp/hippo-s2b-ck7.log` | exit 0; "All checks passed!", "26 files already formatted" |

Counts: 279 on the CK2 line, of which 174 are new (18 in `test_connector_render.py`, 156 in
`test_connector_emit.py`) and 105 are S2a's, which pass unchanged and match the 105 S2a recorded.
292 regression, all pre-existing.

The CK7 line names `src/hippo/knowledge/staged_records.py` and `tests/unit/test_staged_records.py`,
which are S3's and do not exist at this commit, so Ruff refuses the path rather than the code;
`git log` shows S2a hit the same two paths. Everything else in the line ran verbatim, both `check`
and `format --check`. No LadybugDB line: S2b adds no persisted column and touches no store path
(plan section 11). No Neo4j run; the rulebook forbids one without a written grant.

Every line ran with `-W error` alone (form (a) of rulebook line 19; no anyio filter was needed,
because none of the five CK2 files imports `fastapi.testclient`). No warning was suppressed.

## The totality table

`TOTALITY` in `tests/unit/test_connector_emit.py` has **47 rows** and
`{row.spec_field for row in TOTALITY} == SPEC_FIELDS`, asserted by
`test_the_totality_table_names_every_spec_section_3_field`. `SPEC_FIELDS` is the literal transcription
of `docs/spec/enterprise-graph-rag-v1.md:212-261`: `Node` 8 fields, `Edge` 12, `Passage` 7, `Unit` 8,
`AliasCandidate` 5, `Provenance` 7.

One spelling reconciliation, not an override: the plan's section 8.2 writes the seven provenance rows
as `Node.provenance.<field>` and closes with a `Provenance.*` row reading "the same columns; one
mapping for all four records". Transcribed literally, `provenance` is one field of `Node` and the
seven are the fields of `Provenance`, so the table carries `Node.provenance` (asserting
`ObjectObservation.span_id` is the node's verified span) plus the seven `Provenance.<field>` rows.
The plan's pairs `Edge.src`/`Edge.dst`, `Edge.valid_from`/`Edge.valid_to` and `AliasCandidate.a`/`.b`
are split into one row each for the same reason. No mapping in the plan was dropped or changed.

## Rulings and findings applied, with every override of the plan

| # | What the plan says | What was implemented, and why |
| --- | --- | --- |
| R48 / B2 | Section 8.1 step 3: a span's `policy_id` is `revision.artifact.policy_id` | **Override.** `RevisionInput.span_policy_id`, per R48. `test_span_and_artifact_share_the_revision_policy` gives the artifact a *different* policy id from the span policy, so the test fails if the plan's line is implemented |
| R42 / m6 | Section 8.5: `Passage {key} has {count} characters; split it at 1500 before emitting` | **Override.** The message interpolates `PASSAGE_CHAR_BOUND` (6,000), which is what m6 asks for; the plan's literal `1500` is the specification's token bound, not the counter's |
| R63 / m18 | Section 4.5: `evidence_class(family, source, metadata_origin=None)` | **Override**, and the brief's amendment: `evidence_class(registry, family, source, metadata_origin=None)`. Built-ins are read from `builtin_types.EVIDENCE_CLASS_DERIVATION`; an extension source's class comes from `Registry.evidence_source_definition` (R40, R62) and must agree with the emitted family |
| R29 vs the plan | R29: "bind has no evidence-class refusal path" | The brief keeps the plan's refusal of invalid `(family, source)` pairs, so it is implemented: `deterministic`/`similarity`, `probabilistic`/`parser` and a registered source outside the table all refuse. R29 is superseded by R40 and the brief on this point |
| R45 / M10 | R31: S2a supplies built-in verifiers | **Override.** `emit.BUILTIN_VERIFIERS` (`file_lines`, `field`, `table_cell`) is consulted first, then an extension kind's `LocatorKindDefinition.verifier`; a kind with neither refuses. There is no byte-range built-in kind |
| R53 / M6 | — | An identity-only foreign endpoint is keyed by its declared `NodeRef.instance`, so both sources mint one object (`test_identity_only_endpoint_...` binds the same id from two connector instances) |
| M7 | Section 8.2: `Node.provenance.observed_at` → `ArtifactRevision.observed_at` | **Override.** `Provenance.observed_at` is `ArtifactRevision.source_updated_at`, the fetch's value, asserted by the totality row. `ArtifactRevision.observed_at` stays the runtime's receipt instant, which S3 passes in |
| R61 / R44 / M9 | Section 8.9 does not mention the principal map | `policy_record` reads `config_json["principal_map"]` into `base.PrincipalMap` and applies `base.map_principals` before building the `AccessPolicy` |
| R16, R39 | — | `bind_batch` refuses any registry but the frozen `current_registry()`, and `Registry.check_record` runs on every `EvidenceSpan`, `KnowledgeObject`, `ObjectObservation` and `Assertion` the binder builds |
| R66 (ii) | — | `AssertionVersion.unit_id` is written from a batch-local handle resolved against the units this batch built. The binder never looks a unit up by id, so a collected unit dangling is not its problem |
| m4 | — | `test_unregistered_or_undeclared_type_at_bind_is_refused` is parametrized over S1's 31 `REFUSALS` triples, imported from `tests/unit/test_registry.py`. Each case runs the refused registration in a fresh `use_registry(Registry.with_builtins())`, then binds a batch naming `incident_fixture`, `AFFECTS_FIXTURE` and `pager_feed`, and asserts bind refuses **exactly when** one of those names is absent. Thirty cases take the refusal branch; `duplicate_name`, whose first registration succeeds, takes the binding branch, so both halves are exercised |
| R6 | — | Every rendered fact and rendered edge gets one `Unit` and one derived `Passage` over the record span, as a `projection` view in `input_binding._view`'s shape; a foreign-family endpoint binds identity-only |
| Section 8.8 | "any of `predicates.SCHEMA` (`predicates.py:65`) with `resource`" | `GUARDED_ALIAS_PAIRS` is built from `predicates.SCHEMA` (which is at `predicates.py:53`, not `:65`), so all eight database kinds are guarded with `resource`, not just `schema`. `test_the_guarded_pairs_are_the_schema_kinds_with_resource` pins it |

## Two decisions S2b took that the plan leaves open

1. **The label of an identity-only endpoint in a statement.** A foreign-family endpoint stores no
   label (section 8.7), so `edge_statement` names it by its readable canonical key, not by a label
   rendered from attributes the binder discards. The statement therefore stays re-derivable from the
   records that were stored: the key is in `attributes_json`, the emitted attributes are not.
2. **`EmissionCoverage` gains `nodes_by_family` and `facts_skipped`.** Section 4.5's dataclass lists
   neither, but section 8.2's `Node.domain` row names `coverage["nodes_by_family"]` and section 7
   names `coverage["facts_skipped"][template]`. Both are counted, sorted, and in `to_json()`.

## What S3, S4 and S6 require from S2, and where it is

`test_the_surface_s3_s4_and_s6_require_from_s2_is_present_by_name` pins each of these by name, and
pins the six signatures verbatim, so a rename breaks this gate rather than a sibling slice.

| Requirement | Plan | Satisfied by |
| --- | --- | --- |
| `bind_batch`, `merge_bound`, `BindContext`, `BoundBatch`, `BoundPassageRow`, `CapturedRevision`, `EmissionCoverage`, `BINDER_VERSION` | S3 section 3 "From S2" | `emit.py`, all exported |
| `capture_records`, `policy_record` | S3 section 3; S4 R-S2-6, R-S2-7 | `emit.py`, signatures as the S4 plan spells them |
| `RENDER_RULE_VERSION` | S3 section 3 | `render.py` |
| `render_label`, `render_facts`, `unit_text` | S4 R-S2-3 (call site `assert_one_fact_per_unit`) | `render.py`, signatures verbatim |
| `verify_span` | S4 R-S2-4 (`assert_spans_match_bytes`) | `emit.py`, signature verbatim |
| `check_direction_and_ownership` | S4 R-S2-5 (`assert_direction_and_ownership`) | `emit.py`, signature verbatim |
| `evidence_class` | S4 R-S2-9 / m18 (`assert_edges_fully_attributed`) | `emit.py`, with R63's registry argument; the S4 plan anticipated it ("If so, the kit passes `context.registry`") |
| A fact template with a `None` consumed attribute renders nothing and errors nothing | S6 R-S2-5 | `render.render_facts`; `render.skipped_fact_templates` names the omission and `coverage.facts_skipped` counts it |
| A node of a family the connector does not declare binds as an endpoint | S6 R-S2-6 | `_bind_nodes`'s identity-only path (R6) |
| `file_lines` as an emission locator value | S6 R-S2-4 | `BUILTIN_VERIFIERS["file_lines"]`, over `ingest.provenance._lines` with terminators kept |

## The import cycle, and how it is resolved

`keys.KeyPartsRefused` must subclass `emit.BindRefused`, so `keys` imports `emit`. Two rules keep
that acyclic at runtime:

- `emit.py` defines `BindRefused` **above** `from . import keys, render  # noqa: E402`. Importing
  them earlier would leave the name unbound whenever `emit` is the first module of the cycle.
- `render.py` imports `CanonicalKey` under `TYPE_CHECKING` only. It needs the type and not the
  module, and an attribute import from a partially initialized `keys` is what actually fails.

`test_connectors_modules_import_first_in_a_fresh_interpreter` covers `hippo.connectors`, `.base`,
`.keys` and `.classify`; `.render` and `.emit` were checked the same way by hand (a fresh
interpreter per module, all six exit 0). That parametrize list is S2a's file, which S2b does not own,
so extending it to the two new modules is left to whoever owns `test_connector_contract.py` next.

## The verifier call shape S2b defines

Ruling R45 leaves the extension verifier's call to S2. `emit.verify_span` calls it as

```python
verifier(data, locator, artifact=artifact) -> str
```

where `locator` is the parsed canonical locator payload (a `dict`, `kind` included) and the return is
the span's exact text. A `ValueError` becomes a `BindRefused` naming the locator and never quoting
either text. This is recorded in `emit.py`'s module docstring because S3c's fixture connector and
S6's exemplar both register locator kinds against it.

## Left for S3c, and one thing to watch

- `connectors/__init__.py`'s module list still names only `base`, `keys` and `classify`. It is not in
  S2b's "own" list, and the S3c brief already says to add "the S2b modules ... if S2b has not", so it
  is left there. Nothing pins that docstring, so no test fails meanwhile.
- The `Claude-Session` trailer on `ab4a7c7` carries this worker's herdr session id
  (`ed2058fe-811f-450a-bfb6-92ac151c97cb`), which is the only session identifier available inside the
  pane; it is not in the orchestrator's `session_01...` spelling.
