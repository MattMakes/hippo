# CDK S2b-fix evidence: an emitted label on an identity-only foreign endpoint (ruling R70)

Worker `backend-developer-13`, branch `wp/s2b-fix`, base `312df9a` (the `rag-it-all-tibs` HEAD that
carries the merged S2b binder and the R70 ruling). Brief: `ai_docs/handoffs/briefs/cdk-s2b-fix.md`.
Ruling R70 (1) of `ai_docs/plans/cdk-rulings.md`: a connector may give an identity-only foreign
endpoint a label, the minimal observation stores it, and the edge statement reads it when present.

R70 (1) supersedes the first of S2b's "Two decisions S2b took that the plan leaves open"
(`evidence-s2b.md`), which read that such an endpoint stores no label at all. The re-derivability
argument that decision rests on is unchanged: the label is now one more key of `attributes_json`, so
the statement is still a function of the records that were stored, and the emitted attributes are
still discarded.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | (this commit) | Carry an emitted label on identity-only foreign endpoints | `connectors/base.py`, `connectors/emit.py`, `tests/unit/test_connector_contract.py`, `tests/unit/test_connector_emit.py`, this file (new) |

`connectors/render.py` and `tests/unit/test_connector_render.py` are in the brief's "own" list and
are **not touched**; see "Why render.py needs no change" below. Nothing outside the "own" list was
staged.

## The change

- `base.NodeRef` gains `label: Text | None = None`. `Text` is
  `Annotated[str, Field(min_length=1, pattern=r"\S")]`, so an empty or all-whitespace label is
  refused by the type and needs no validator of its own.
- `emit._bind_nodes`, the identity-only branch only: `attributes` carries `label` when the emission's
  reference declares one, and the binder's `labels` entry for the object is that label, else the
  readable canonical key as before. `edge_statement` is called with `labels[...]` already, so the
  statement follows.

Nothing else changed: no signature moved, no refusal was added or removed, `SPEC_FIELDS` and the
47-row totality table are untouched (a label on a reference is `Node.label` supplied by the
connector, not a new specification field of `Edge`), and the binder is still a pure, deterministic
function of its inputs.

## Four decisions the ruling leaves open, and how they were settled

| Question | Settled as | Why |
| --- | --- | --- |
| Which reference is read | The `NodeEmission`'s reference, in the identity-only branch, and nowhere else | Only that branch writes an observation. A label read off an edge or alias reference would be stored by nothing, so a statement carrying it could not be re-derived from the records |
| A label on a node whose family the connector **owns** | Not read; `label_template` still renders the label | R70 is about the endpoint a connector does not own. Refusing the field instead would be a new refusal path the brief's "Nothing else changes" excludes. Recorded here so the orchestrator can rule for a refusal later if the exemplar wants one |
| The same object emitted twice in one batch | First emission wins (`labels.setdefault`, unchanged) | `EmissionBatch.nodes` is an ordered tuple, so this is deterministic, and it is exactly the rule that was already in force |
| Where the key stays visible | `attributes_json` always carries `key`; `label` is an additional key | The canonical key is what makes the endpoint identifiable across connectors (R53); the label is prose |

## Why render.py needs no change

The brief allows "`render.edge_statement` (or the binder's call into it)". `edge_statement` already
takes `(definition, label)` pairs and has no access to a canonical key or to a reference, so the
choice between the emitted label and the readable key belongs to the binder, which holds both. The
binder makes that choice once, in `_bind_nodes`, and every later reader — the edge statement, the
alias statement, the rendered-edge unit title — reads the one `labels` entry. Putting the choice in
`render.py` would mean passing the key into a function that would then have to re-derive which
spelling was stored.

## RED

| Stage | Log | Result |
| --- | --- | --- |
| The CK2 CHECK line, three new tests, no source change | `/tmp/hippo-s2b-fix-red.log` | exit 1; 2 failed, 280 passed. Both failures are `extra_forbidden` on `NodeRef.label` |
| The CK2 CHECK line, with the `NodeRef` field added and no binder change | `/tmp/hippo-s2b-fix-red-binder.log` | exit 1; 1 failed, 281 passed. The one failure is behavioural: `attributes_json` is `{"key": ...}` where the test wants `{"key": ..., "label": "checkout"}` |

The second stage exists because a bare `extra_forbidden` error is a weak RED for a binder test: it
proves the field is missing, not that the binder ignores the label. With the field alone, the emit
test fails on the stored record, which is the behaviour under test.

The third test, `test_an_identity_only_endpoint_without_a_label_is_still_named_by_its_readable_key`,
**passes at both RED stages by design**. The brief asks for it as a pin on the behaviour that must
not change: no emitted label, so the observation is `{"key": ...}` alone and the statement names the
endpoint by its readable canonical key. It is a regression pin, not a TDD step.

## GREEN (final tree)

| Line | Log | Result |
| --- | --- | --- |
| The CK2 CHECK line of `GATES.md`, verbatim, Fake | `/tmp/hippo-s2b-fix-green.log` | exit 0, 282 passed |
| The CK7 Ruff line of `GATES.md`, verbatim | `/tmp/hippo-s2b-fix-ck7.log` | exit 0; "All checks passed!", "28 files already formatted" |
| Regression, Fake: the suites that bind through `connectors` or read the registry | `/tmp/hippo-s2b-fix-regress.log` | exit 0, 184 passed, 1 skipped |

Counts: 282 on the CK2 line, of which 3 are new — one in `test_connector_contract.py`
(`test_node_reference_may_carry_an_emitted_label_and_refuses_a_blank_one`) and two in
`test_connector_emit.py` (the labelled endpoint and the unlabelled pin). The other 279 are S2b's 279,
which pass unchanged. The regression line is `test_managed_input_binding.py`, `test_code_binding.py`,
`test_staged_records.py` and `test_registry.py`, all pre-existing and all green.

Unlike S2b's run, the CK7 line ran with no path omitted: `src/hippo/knowledge/staged_records.py` and
`tests/unit/test_staged_records.py` exist at this base, so all 28 files were checked and formatted.

Every line ran with `-W error` alone (form (a) of the rulebook's warnings rule; no anyio filter was
needed, because none of the five CK2 files imports `fastapi.testclient`). No warning was suppressed.
No LadybugDB line and no Neo4j run: this change adds no persisted column and touches no store path —
`attributes_json` is an existing column of `ObjectObservation` and the label is one more key inside
the canonical JSON it already holds.

## Notes for whoever comes next

- S6's exemplar can now emit `NodeRef(kind="service", key=..., instance=..., label="checkout")` on
  the `NodeEmission` of the foreign endpoint and get the `AFFECTS` statement "… affects service
  checkout". The label must be on the node emission's reference; on the edge's reference it is
  accepted by the contract and read by nothing.
- `connectors/__init__.py`'s module list and the fresh-interpreter import parametrization in
  `tests/unit/test_connector_contract.py` still name only `base`, `keys` and `classify`. R70 (2)
  grants both edits to S3c; this slice left them alone.
- The `Claude-Session` trailer carries this worker's own herdr session id, per R70 (3).
