# CDK S1b-fix evidence: B1, the evidence-source accessor, the exclusions one-liner

Worker `backend-developer-8`, branch `wp/s1b-fix`, base `89ff6ac` (the `rag-it-all-tibs` HEAD named
in the spawn message; S1b merged at `9e5b93c`). Contract:
`ai_docs/handoffs/briefs/cdk-s1b-fix.md`, which carries out the three items of
`ai_docs/gates/rag-it-all/cdk/evidence-s1b.md` "Handed off, not done here" under rulings R39, R40,
R47 and R62 of `ai_docs/plans/cdk-rulings.md` and finding B1 of
`ai_docs/reports/2026-09-15-cdk-plan-review.md`.

**Status: complete.** All three items landed, each as its own commit, each green.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `3e17044` | Carry the registry fingerprint through both lane comparisons | `knowledge/prose_preparation.py`, `knowledge/staged_code.py`, `tests/unit/test_prose_preparation_fingerprint.py` (new), `tests/unit/test_staged_code_fingerprint.py` (new) |
| 2 | `083926b` | Return an evidence source's registered definition from the registry | `knowledge/registry.py`, `tests/unit/test_registry.py` |
| 3 | `62f3bc5` | Count no exclusion section a projection never excluded | `knowledge/projection.py`, `tests/unit/test_registry_model.py` |

No identity field changed; no schema version, checksum or migration step was touched. The v7 and v8
checksums S1b published stand unchanged, which the CK1 lines below re-prove.

## Item 1 — B1 / R47, the fingerprint-tolerant comparisons

Two edits, exactly the lines the ruling names:

- `knowledge/prose_preparation.py`, in `PlainProseInputs.__post_init__`: the
  `generation_for_inputs(...)` call that builds `wanted` now passes
  `registry_fingerprint=gen.registry_fingerprint`. S1b had already added the keyword to
  `knowledge/lifecycle.py:26`, so this is the caller half only.
- `knowledge/staged_code.py`, in `_local`: the compare is now
  `current.replace(coverage_json=gen.coverage_json, registry_fingerprint=None) != gen.replace(registry_fingerprint=None)`,
  the normalization the handoff proposed. The bundle copy is re-settled without the fingerprint at
  `code_binding.py:1037-1046`, and the field is outside `identity_fields` and immutable, so
  ignoring it is sound.

Each test file holds the review's positive test and a negative that proves the compare stayed
strict:

| Test | Proves |
| --- | --- |
| `test_a_fingerprinted_generation_passes_prose_preparation` | a generation carrying a fingerprint, with its passages bound to it, is accepted; its id and `manifest_hash` are the unfingerprinted generation's |
| `test_prose_preparation_still_refuses_a_generation_of_another_identity` | the same inputs with `embedding_profile` changed still raise "Generation differs from accepted revision/configuration identity" |
| `test_a_fingerprinted_generation_passes_the_code_writer` | the persisted row carries the fingerprint, `prepared.generation` does not, and the writer seals: `write(...) == store.validate_generation_seal(gen.id)` |
| `test_the_code_writer_still_refuses_a_persisted_generation_of_another_capture` | a persisted row that also differs in `created_at` still raises "Persisted generation differs from accepted preparation" |

Two choices worth recording:

- **Which field the negatives perturb.** On the prose side `embedding_profile` is the identity field
  the recomputation takes from the stored profile rather than from the generation, so changing it is
  a difference the compare itself must see; changing `parent_id`, by contrast, is copied into
  `wanted` and would only trip the `evidence.generation_id != gen.id` clause. On the code side an
  identity-field change renames the generation, and `store._generation(gen.id)` would then refuse
  for "no such row" rather than at the compare, so the negative uses `created_at`: compared, outside
  identity, and the field design review B4 is about. Between them the two halves show the
  normalization reaches `registry_fingerprint` and nothing else.
- **Where the tests live.** New files, not `tests/unit/test_prose_generation.py` or
  `tests/unit/test_code_generation.py`. Those two are end-to-end coordinator suites (real
  `httpx.MockTransport` wires, a real git checkout) for `hippo.ingest.*`; these are unit tests of
  two comparisons in `hippo.knowledge.*`, and the fixtures they need are
  `tests/unit/test_staged_prose_writer.py` / `test_staged_code_writer.py`, which this brief does not
  own. Both new files import their fixtures the way `test_registry_model.py` already does.

The code-side fixture reaches `install` through a `SimpleNamespace` holding only the five bundle
fields `install` reads, so the generation that is *persisted* carries the fingerprint while the
merged bundle the writer prepares does not. That is the shape the S5 seam produces, without editing
the writer suite.

| Stage | Log | Result |
| --- | --- | --- |
| RED, both files before either edit | `/tmp/hippo-s1b-fix-b1-red.log` | exit 1, 2 failed, 2 passed |
| GREEN, both files | `/tmp/hippo-s1b-fix-b1-green.log` | exit 0, 4 passed |
| Regression, the two writer suites and managed prose preparation | `/tmp/hippo-s1b-fix-b1-writers.log` | exit 0, 110 passed |

RED failed on exactly the two refusals: `ValueError: Generation differs from accepted
revision/configuration identity` at `prose_preparation.py:176` and `ValueError: Persisted generation
differs from accepted preparation` at `staged_code.py:311`. Both negatives passed in RED, for the
pre-fix reason; they discriminate only once the positives pass.

## Item 2 — R62, `Registry.evidence_source_definition`

`knowledge/registry.py` gains one method beside `evidence_source`, returning
`self._lookup("evidence_sources", name)` unchanged, so an unknown name raises the registry's own
`UnregisteredName("Unknown evidence source: '<name>'")` like every other lookup. Its docstring
carries the Q3 wording: a built-in carries `family=None` and `evidence_class=None`, and callers read
`builtin_types.EVIDENCE_CLASS_DERIVATION` by `(family, source, metadata_origin)`, because one class
cannot be returned for `metadata`, which derives two, or for `reviewed`, which spans both families.

Three tests in `tests/unit/test_registry.py`:

| Test | Proves |
| --- | --- |
| `test_the_definition_of_an_extension_evidence_source_carries_its_family_and_class` | the registered `PAGER_FEED` comes back whole, `("deterministic", "catalog_observed")` |
| `test_the_definition_of_a_builtin_evidence_source_carries_neither` | every built-in equals `EvidenceSourceDefinition(name=name)`, and the derivation table really does give `metadata` two classes and `reviewed` two families |
| `test_lookups_of_unregistered_names_raise_unregistered_name[evidence_source_definition]` | a new case in the existing parametrization: `UnregisteredName`, a `KeyError`, message `Unknown evidence source: 'pager'` |

| Stage | Log | Result |
| --- | --- | --- |
| RED, `tests/unit/test_registry.py` | `/tmp/hippo-s1b-fix-r62-red.log` | exit 1, 3 failed, 71 passed (`AttributeError: 'Registry' object has no attribute 'evidence_source_definition'`) |
| GREEN | `/tmp/hippo-s1b-fix-r62-green.log` | exit 0, 74 passed |

The other half of R62, `check_record` checking `AssertionVersion.source`, landed in S1b as granted
edit Q2 and is not re-done here.

## Item 3 — the projection exclusions one-liner

`knowledge/projection.py`: both `unregistered_spans=frozenset(excluded["locator_kinds"])` reads
(the `_safe_vectors` call and the `_project_prose` call) become
`excluded.get("locator_kinds", ())`. `excluded` is a `defaultdict(set)`, so the subscript — not the
`.add` at the exclusion site — was creating the section, and `exclusions.update({section: len(...)})`
then wrote `locator_kinds: 0`. Both reads run on every projection, so both had to change; a comment
at the `defaultdict` says why.

The test in `tests/unit/test_registry_model.py` is
`test_a_projection_that_excludes_nothing_counts_no_section`: the registered-extension world, whose
projection leaves nothing out, asserting `list(exclusions.items()) == []`.

**Why this was invisible.** The two neighbouring tests already assert `exclusions == Counter()`, and
they passed throughout: since Python 3.10 `Counter.__eq__` reads a missing key as zero, so
`Counter({"locator_kinds": 0}) == Counter()` is `True`. Only a caller walking `.items()`,
`.most_common()` or `len()` sees the spurious entry, which is what the new test does. Where the
counts surface in `Generation.coverage_json` remains S3's decision.

| Stage | Log | Result |
| --- | --- | --- |
| RED, `tests/unit/test_registry_model.py` | `/tmp/hippo-s1b-fix-proj-red.log` | exit 1, 1 failed, 71 passed (`assert [('locator_kinds', 0)] == []`) |
| GREEN | `/tmp/hippo-s1b-fix-proj-green.log` | exit 0, 72 passed |

## Gate lines at the final tree (`62f3bc5`)

| Line | Log | Result |
| --- | --- | --- |
| CK1 Fake, verbatim | `/tmp/hippo-s1b-fix-ck1-fake.log` | exit 0, 305 passed, 9 skipped |
| CK1 LadybugDB, verbatim | `/tmp/hippo-s1b-fix-ck1-ladybug.log` | exit 0, 174 passed |
| `tests/unit/test_prose_generation.py tests/unit/test_code_generation.py` on Fake | `/tmp/hippo-s1b-fix-ingest-fake.log` | exit 0, 106 passed, 1 skipped |
| Ruff over the eight files this branch touched | `/tmp/hippo-s1b-fix-ruff.log` | exit 0, all checks passed, 8 files already formatted |
| CK7 Ruff over its paths that exist today | `/tmp/hippo-s1b-fix-ck7-partial.log` | exit 0, all checks passed, 11 files already formatted |

Every pytest line is the rulebook form:
`HIPPO_TEST_STORE=<backend> .venv/bin/pytest <files> -q -o addopts='' -W error > <log> 2>&1; echo EXIT $?`.
No anyio `BlockingPortal` filter was needed anywhere: none of these files imports
`fastapi.testclient`, and no warning fired under `-W error`. No Neo4j was run.

## Findings

1. **The CK7 CHECK line cannot run verbatim at this HEAD.** It names
   `src/hippo/knowledge/staged_records.py`, `tests/unit/test_staged_records.py` and
   `tests/unit/test_connector_*.py`, none of which exist yet (S2/S3 create them), so Ruff exits 1
   with `E902 No such file or directory`. Pre-existing and outside this brief; recorded so the
   orchestrator does not read it as a regression. The subset that exists is clean.
2. **The two open questions S1b recorded are untouched** and still belong to S3 and Task 15: closing
   a recorded interval needs the extension registered, and a collected generation's `unit_id`
   dangles. Nothing here changes either.
