# CC8 evidence: staged code writer and long-build authority (gate CD7)

Worker `backend-developer-21`, 2026-09-12. Branch `wp/cc8`, worktree `.worktrees/cc8`, base
`8f32ec4` (the merge of `wp/cc3`; CC1, CC2, CC3, CC4, CC5, CC6 and CC7 all landed). Contract:
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` sections 4, 8.2, 8.3 and 10, rulings 2, 9,
10 and 13; brief `ai_docs/handoffs/briefs/cc8-staged-code-writer.md`; `evidence-cc2.md`,
`evidence-cc3.md`, `evidence-cc6.md` and `evidence-cc7.md`; the design review
`ai_docs/reports/2026-09-12-code-capture-plan-review.md` (B3, B4, M2, M6, M7, question 4). No gate
checkbox is set here.

## Commits

| Hash | Subject |
| --- | --- |
| `bad2dfe` | Write one code generation in fenced dependency groups and seal it |
| `db7aa77` | Let a long repository build survive an unrelated authorization change |

## Files

| File | Change |
| --- | --- |
| NEW `src/hippo/knowledge/staged_code.py` | the writer, the prepared input type and the resume probe |
| NEW `tests/unit/test_staged_code_writer.py` | 44 test functions, 47 cases |
| `src/hippo/knowledge/generation_profiles.py` | the `code` accepted-input profile (item 4b) |
| `tests/unit/test_generation_profiles.py` | 3 added tests; the 33 existing cases are untouched |
| `src/hippo/knowledge/build_authority.py` | `rebaseline`, B3's kind allow-list and `managed` term, the accepted-artifact kinds and the closed planned-policy scope set |
| `tests/unit/test_build_authority.py` | 19 added test functions (25 cases); the 45 existing cases are untouched, and `world` gained a defaulted `kind=` keyword that changes no existing call |
| NEW `ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc8.md` | this file |

**`src/hippo/store/generations.py` was not touched.** The narrow grant on the evidence-membership
check inside `generation_checksums` turned out not to be needed; see "The narrow grant went unused"
below. `git show --stat` for the two commits names six files and that is the complete set.

## Public signatures, verbatim

```python
PAYLOAD_CEILING_BYTES = 64 * 1024 * 1024
NATIVE_KINDS = ("Symbol", "DataObject", "Commit")
RELATION_KINDS = ("CODE_EDGE", "DEFINED_IN", "MODIFIES", "PRECEDES")
CODE_EDGE_FIELDS = ("a", "b", "kind", "omega", "provenance", "extra")
CLEANUP = "explicit failed-generation cleanup"


def code_relations(
    bundle: MergedCodeBundle, facts
) -> tuple[tuple[_CodeEdge, ...], tuple[_Definition, ...]]: ...


def probe_staged_rows(store, prepared) -> ResumePlan: ...


def write_staged_code(
    store,
    prepared,
    *,
    job_id,
    lease_owner,
    fencing_token,
    expected_authorization_epoch,
    expected_suppression_epoch,
    check,
    batch_size=128,
    resume=None,
): ...
```

Frozen values: `PreparedCodePassage(passage, embedding)` with `id` / `native_row()`;
`PreparedNativeRow(row, embedding=())` with `native_kind` / `native_id` / `native_row()`;
`PreparedCodeIndex(bundle, dense, native, edges=(), definitions=())` with `generation` /
`relations`; `ResumePlan(generation_id, group_count, skipped)` with `skipped_groups`;
`_CodeEdge(row_json)`, `_Definition(node_id, passage_id)`, `_Precedes(newer, older)`. Every refusal
is a `ValueError`, as CC6's and CC7's are, except the epoch guard, which raises
`AuthorizationChanged` exactly as `staged_prose._epochs` does, and the ambient-transaction guard on
`rebaseline`, which raises `RuntimeError` exactly as `BuildAuthority.check` does.

In `build_authority.py`:

```python
BUILD_SOURCE_KINDS = frozenset({"text", "file", "repo", "archive"})
ACCEPTED_ARTIFACT_KINDS = frozenset({"file", "manifest", "repository", "history_event"})
PLAIN_PROSE_SCOPE = "plain-prose-v1"
MANAGED_CODE_SCOPE = "managed-code-v1"
PLANNED_POLICY_SCOPES = (PLAIN_PROSE_SCOPE, MANAGED_CODE_SCOPE)


class BuildAuthority:
    def rebaseline(self) -> BuildAuthority: ...
```

In `generation_profiles.py`:

```python
GENERATION_PROFILE_KEY = "generation_profile"
PLAIN_PROSE_PROFILE = "plain_prose"
CODE_PROFILE = "code"
GENERATION_PROFILES = (PLAIN_PROSE_PROFILE, CODE_PROFILE)
```

## The prepared input is a new type, and why

The writer's input is `PreparedCodeIndex`, not CC7's `MergedCodeBundle` directly. The bundle is pure
evidence: it carries no vectors, no `CODE_EDGE` rows and no `DEFINED_IN` pairs, because CC6 and CC7
hold neither the embedding model nor the resolved `CodeGraph`. Something has to join the three, and
the join needs cross-checks (every dense row has a vector; every edge endpoint has a native row;
every `DEFINED_IN` pair names a row and a passage of this generation). Doing that join inside
`_write_batch` would put it inside a transaction and repeat it per batch; doing it in the
coordinator would leave the writer trusting an unchecked mapping. So it is a frozen dataclass that
validates once, outside every transaction, and `_write_batches` is a pure function of it.

`code_relations(bundle, facts)` is the pure helper that derives `edges` and `definitions` from the
graph, applying CC6's finding 10 set difference: an edge or a `DEFINED_IN` pair naming a node with
no native row is **dropped**, because a symbol whose rendered body is only whitespace is skipped by
the committed chunker and refusing the whole build over an empty function body would be wrong.
`PreparedCodeIndex` then **refuses** a dangling endpoint, so a caller that builds `edges` some other
way cannot smuggle one past the filter.

`MergedCodeBundle` is required as the bundle type even when the history is empty: CC7's
`merge_code_bundles` closes over a `CodeHistoryBundle` with no commits (`history_depth == 0` records
`history: "disabled"`), so there is exactly one input shape rather than two.

## The batch groups, in order

1. accepted preflight (`(None,)`) — `_accepted`, a read, never skipped by the probe
2. revision members, one group each
3. original spans, each with its `GenerationEvidenceMember`
4. **objects, each with its own `ObjectObservation`s** and their members
5. derived views: `DerivedRecord`, its `DerivedDependency`s, the `RetrievalView`, and their members
6. dense passages, one per `PreparedCodePassage`
7. native rows, each **with its own `NativeBinding`**
8. native relations: one group per `CODE_EDGE` row, then one per `DEFINED_IN` pair
9. history: one group per `MODIFIES` row, then one per `PRECEDES` pair

**Two deviations from the brief's stated order, both forced and both tested.**

1. **Objects move after spans.** The brief's list is "… revision members → repository/file/symbol/
   commit objects → original spans → …" and does not mention `ObjectObservation` at all. But every
   observation cites a span, so observations cannot precede spans; and an object carries nothing
   generation-scoped of its own, so an object group with no observation in it would not be
   recognisable from a scoped read — the probe would need one `_knowledge_get` per object on every
   build, fresh or resumed. Pairing each object with its observations solves both: the group is
   dependency-complete and one scoped `GenerationEvidenceMember` read decides it.
   `PreparedCodeIndex` refuses an object with no observation ("unreachable evidence", CC6's own
   rule) so the pairing is total.
2. **A `NativeBinding` travels with the native row it binds.** `put_knowledge` dereferences the row
   (`store/knowledge.py:696-701` reads `native["source_id"]`), so the binding cannot be written in
   an earlier group. `test_an_omitted_native_row_is_refused_by_its_own_binding` proves the store
   agrees: suppressing `add_symbols` makes the very same batch raise `Missing Symbol reference`.

`_write_batch` dispatches in a fixed order — evidence records, dense rows, native rows, bindings,
`CODE_EDGE`, `DEFINED_IN`, `MODIFIES`, `PRECEDES` — which is exactly the stage order, so coalescing
several groups into one batch never reorders a dependency. Rows of one kind inside a batch are
written in one call, so a batch of 128 groups costs one `add_symbols`, not 128.

## The probe's three outcomes

`probe_staged_rows` takes one scoped read per kind and nothing else:

```python
_knowledge_rows("GenerationMember",          generation_id=...)
_knowledge_rows("NativeBinding",             generation_id=...)
_knowledge_rows("GenerationEvidenceMember",  generation_id=...)
_native_rows(kind, generation_id=...)  for Passage, Symbol, DataObject, Commit
_native_relationships(generation_id=...)
```

`test_the_probe_reads_only_generation_scoped_and_identified_rows` wraps `_knowledge_rows` and
`_native_rows` and asserts that no call arrives without `generation_id`, `ids` or `where`, so CC2's
contract is enforced rather than claimed.

- **SKIP** when every probe key of the group is present *and* its payload equals what this attempt
  would write. Native rows are compared through `store._canonical_native`; `GenerationMember` and
  `NativeBinding` by record equality; every shared evidence record of a present group is re-read
  with `_knowledge_get` and compared. Never a sample: every key of the group is checked.
- **WRITE** when none of the group's keys is present.
- **FAIL CLOSED** — `ValueError` naming `explicit failed-generation cleanup` — when a group is
  partially present, when a present payload differs, or when any generation-scoped row exists that
  this attempt would not produce (the absence assertion, design review M2).

`ResumePlan.skipped_groups` is what `BuildReceipt.resumed_from_batches` reports.
`_write_batches(prepared, batch_size=..., resume=plan)` drops exactly the skipped groups before
coalescing, refuses a plan for another generation, and refuses a plan whose `group_count` differs
from the preparation it is handed.

**A fresh build already skips its revision-member groups**, because the coordinator installs the
accepted inventory and its members before it claims — the same thing the prose fixture does. That is
asserted exactly (`test_a_fresh_generation_probes_to_write_everything_but_its_installed_members`)
rather than waved at, because it is the same mechanism that recognises a resumed batch.

### Question 4's three cases

| Case | Answer |
| --- | --- |
| Sampling | Every row of the group is probed. `_Group.probes` carries one key per row and the verdict is `all()`/`any()` over the whole tuple. |
| `native_write`'s tolerant equality | The probe compares `_canonical_native` output itself. Worth recording precisely: in this codebase the tolerated columns (`boost`, `community`, `entities_json`, `triples_json`, `extraction_error`) are **not emitted by the canonical shapers at all** (`symbol_write_row`, `data_object_write_row`, `commit_write_row` and the `Passage` branch of `_canonical_native` all build closed dicts), so the gap the review feared cannot be reached through this comparison. The requirement is honoured as written and the conflict test uses a real payload difference (`doc`). |
| A relation group binding to another attempt's endpoints | Closed by B4 and M2 together. `test_a_resume_that_re_takes_the_capture_instant_fails_closed` builds the *same* generation at a fresh instant, proves the observation IDs all differ, and shows the probe refusing rather than writing a second set beside the first. |

## Design review B4, both halves

`Generation.identity_fields` excludes `created_at`, so the same inputs at two instants are one
generation with two different `ObjectObservation` inventories.

- The adopted instant reproduces every observation ID byte-identically:
  `test_a_reclaimed_generation_keeps_its_capture_instant_and_every_observation_id` writes part of a
  build, reclaims it, and compares the persisted `GenerationEvidenceMember` set for
  `ObjectObservation` against `bundle.observations` — equal.
- A fresh instant is detected as a conflict, not written as a duplicate: the test above.

Adopting the persisted `Generation.created_at` on reclaim is CC9b's, as the notes say; this slice
proves the store side behaves and that the probe catches the coordinator getting it wrong.

## Item 4b: the `code` accepted-input profile

`GENERATION_PROFILE_KEY = "generation_profile"` is a top-level key in the **accepted manifest's
configuration**, which is the dict `generation_for_inputs` hashes — so the selector is part of
generation identity and a generation cannot be re-labelled afterwards. Absent means
`plain_prose`; an unknown name raises `Unknown accepted generation profile`.

The `code` member set is exactly: one `manifest`, one `repository`, one `file` per accepted input,
and zero or more `history_event`.

| Member | What is checked |
| --- | --- |
| `manifest` | unchanged from plain prose |
| `repository` | `canonical_uri == external_id`; `id == make_identity("artifact", [ws, source, "repository", external_id])`; `(content_hash, raw_uri) == (accepted.manifest.sha256, accepted.manifest.uri)`, which is exactly the pair CC6's `_tree_records` writes. The head SHA is **not** separately checkable: it is not a field of the accepted manifest, and it enters identity as the repository revision's `provider_revision`, so the `generation_for_inputs` equality at the end is its only honest proof. No invented check was added. |
| `file` | the identical identity and raw-identity checks plain prose runs, factored into one shared `_accepted_file` so the two profiles cannot drift |
| `history_event` | `canonical_uri == external_id`; `id == make_identity("artifact", [ws, source, "history_event", external_id])`; a nonempty `provider_revision`; `external_id == f"{repository.external_id}@{provider_revision}"`, which is the containment check that stops a commit of another repository being smuggled in; and `raw_uri == COMMIT_RAW_URI_SCHEME + provider_revision`. **The `raw_uri` is asserted, never dereferenced** (CC7 finding 4): `hippo-commit:<sha>` names no stored object. |

The identity re-derivation excludes the `history_event` pairs (CC7 finding 1): `_code_members`
returns `[manifest, repository, *files]` and `generation_for_inputs` is called with exactly that,
while the membership check covers the larger set.

Plain prose is byte-identical: the same member rule, the same four error strings in the same order,
and `tests/unit/test_generation_profiles.py` (33 pre-existing cases),
`tests/unit/test_staged_prose_writer.py`, `test_generation_store.py` and `test_dense_session.py` are
all green unchanged.

One bounded read fix went with it: line 123's `_knowledge_rows("GenerationMember")` whole-table read
plus Python filter became `_knowledge_rows("GenerationMember", generation_id=generation.id)`, the
form `staged_prose._inventory` already uses. Same result, bounded, and it runs at query time through
`dense_session.py:~115`.

### The narrow grant went unused

The brief grants the evidence-membership check inside `generation_checksums`. It needed no change,
and the reason is worth recording so a reviewer does not go looking. The check is
`self._record_revisions(target) <= revisions` where `revisions = {m.artifact_revision_id for m in
members}` — **every** member's revision, including the repository and the `history_event`s. So a
span on a repository or commit revision was never the thing "Evidence outside raw manifest" refused.
What refused a code generation was `validate_generation_profile`'s member-set rule, one call
earlier, which is what item 4b fixes. `src/hippo/store/generations.py` is byte-identical to
`8f32ec4`.

### A contract note CC9b must have

`capture_repository_inputs` adds its own reserved `capture` key to the configuration it records in
the accepted manifest, and `CodeGenerationInputs.folded` adds `code_derivation` to the configuration
generation identity hashes. For the two to be the same dict — which
`validate_generation_profile:185-197` requires — the order is:

1. call `capture_repository_inputs(configuration=folded)` where `folded` is the base configuration
   plus `code_derivation` (CC7 finding 2 is right about this);
2. read `json.loads(captured.accepted.configuration_json)` back and **remove `code_derivation`**;
   that dict, which now carries `capture`, is `CodeGenerationInputs.configuration`;
3. `folded()` then re-adds `code_derivation` and reproduces the manifest's copy exactly.

Passing the same dict to both refuses: `capture_repository_inputs` rejects a configuration that
already carries `capture`, and `folded` rejects one that already carries `code_derivation`. The
fixture in `test_staged_code_writer.py::capture` does it the working way with a comment, and
`test_a_code_generation_validates_under_the_code_profile_at_query_time` is the proof.

## Item 3 and item 4: the authority

`rebaseline()` copies `bind_inputs`'s shape and adds the authorization lock, in the order
`generation_write` and `native_write` take them:

```
in_ambient_transaction() -> RuntimeError        (before any transaction is opened)
_latched()                                     (closed, or any sticky failure)
store.transaction():
    _lock_authorization(); _lock_source(source_id)
    suppression_epoch() == expected_suppression_epoch   else AuthorizationChanged
    _source_control(store, source_id) == self.source_control  else AuthorizationChanged
    child = BuildAuthority(store, actor, accepted, source_control,
                           (authorization_epoch(), expected_suppression_epoch), clock)
    child.check_local()    -> on failure: child.close(), latch on self, re-raise
    return child
```

The parent's own `check_local()` is **never** called (design review M6(a)): it refuses on an epoch
mismatch as its first act, which is the very condition a rebaseline exists to clear.

**The suppression epoch is frozen and any change refuses**, which subsumes M7's reachable-closure
question and the docstring says so: `publish_staged_generation` re-checks the same epoch against the
generation's whole reachable closure and would refuse at the end anyway, so continuing is wasted
work. `source_control` is frozen too, so a changed `access_role_id`, `min_rank` or `owner_id`
refuses even though the actor kept every capability (M6(b)).

**A finding CC9b must act on.** `check_local()` latches its own refusal, and ruling 2 forbids a
rebaseline after a sticky failure. So a coordinator that notices the epoch change *by calling
`check()`* can never rebaseline: the failure is already latched. The coordinator must compare
`store.authorization_epoch()` with `guard.expected_authorization_epoch` between batches and call
`rebaseline()` **before** its next external check. Pinned by
`test_a_rebaseline_must_precede_the_failing_check_not_follow_it`.

B3's first half, as the orchestrator ruled on 2026-09-12 (both halves widened, closed sets, prose
byte-identical, the scope constant exported for CC9b):

- `BUILD_SOURCE_KINDS` adds `repo` and `archive`; the denial text for everything else is unchanged
  and asserted anchored (`match="^Build actor cannot manage source$"`), so the refusal stays a
  non-oracle.
- `managed` is now `bool(source["managed"] or source["active_generation_id"])`. The
  Artifact/Generation presence scan and the `meta["managed"]` term are gone.
  `test_the_managed_term_is_the_row_alone_and_reads_no_record_table` wraps `_knowledge_rows` and
  asserts neither `Artifact` nor `Generation` is read — this scan ran inside `check_local`, which
  the writer calls between every batch. **No existing test depended on the presence scan**: all 45
  pre-existing cases pass untouched, and the answer for a source holding an Artifact row is the same
  anyway, because ruling 9 keeps the store's own flag flipping at staging start. What changed is
  that the flag is read from the Source row instead of rediscovered.
- `ACCEPTED_ARTIFACT_KINDS` admits `repository` and `history_event`; `PLANNED_POLICY_SCOPES` is the
  closed pair `("plain-prose-v1", "managed-code-v1")` and anything else still raises
  `Planned policy is not an explicit local source grant`.

`tests/unit/test_build_authority.py` keeps its 21 existing test functions (45 cases) unchanged. The
shared `world` helper gained a defaulted `kind="file"` keyword; every existing call site is
unaffected.

## Results

All runs from `.worktrees/cc8` with `.venv/bin/python` (3.12.11, `mcp==2.1.1` pinned).

| Run | Command | Result | Log |
| --- | --- | --- | --- |
| Baseline before RED | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_staged_prose_writer.py tests/unit/test_build_authority.py tests/unit/test_generation_resume.py tests/unit/test_generation_failure.py tests/unit/test_code_binding.py tests/unit/test_code_history.py -q -o addopts='' -W error` | 208 passed | `/tmp/hippo-cc8-baseline.log` |
| RED | `tests/unit/test_staged_code_writer.py` with `staged_code.py` removed and `generation_profiles.py` reverted | 6 failed, 39 errors, `ModuleNotFoundError: No module named 'hippo.knowledge.staged_code'` | `/tmp/hippo-cc8-red.log` |
| RED, authority | `tests/unit/test_build_authority.py` before the `build_authority.py` change | 24 failed, 45 passed | `/tmp/hippo-cc8-authority-red.log` |
| GREEN, **the CD7 command** | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_staged_code_writer.py tests/unit/test_generation_resume.py tests/unit/test_generation_failure.py -q -o addopts='' -W error` | **83 passed** | `/tmp/hippo-cc8-cd7.log` |
| GREEN, authority and profiles | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_build_authority.py tests/unit/test_generation_profiles.py -q -o addopts='' -W error` | **106 passed** | `/tmp/hippo-cc8-authority.log` |
| GREEN, wide Fake regression | the CD7 and CD1 files plus `test_staged_prose_writer.py test_generation_store.py test_generation_scoped_reads.py test_generation_counts.py test_code_binding.py test_code_history.py test_dense_session.py test_layering.py test_import_order.py` | 449 passed | `/tmp/hippo-cc8-green-fake.log` |
| GREEN, authority consumers | `test_transaction_ownership.py test_prose_generation.py test_ingest_concurrency.py test_managed_source_lifecycle.py test_build_run.py test_local_workspace_membership.py test_managed_input_binding.py` | 227 passed, 2 skipped | `/tmp/hippo-cc8-consumers.log` |
| GREEN, activation and web | `test_managed_pipeline_activation.py test_managed_transport_activation.py test_managed_web_ingress.py test_managed_source_inventory.py test_status_access.py` | 294 passed, 3 skipped | `/tmp/hippo-cc8-web.log` |
| **GREEN, Ladybug** | `HIPPO_TEST_STORE=ladybug .venv/bin/pytest tests/unit/test_staged_code_writer.py tests/unit/test_build_authority.py -q -o addopts='' -W error` | **117 passed** (153.77s) | `/tmp/hippo-cc8-ladybug.log` |

Per file on Fake: `test_staged_code_writer.py` 47, `test_build_authority.py` 70,
`test_generation_profiles.py` 36.

The CD7 CHECK line as the ledger spells it runs from `/Users/mascott/projects/hippo`; the command
above is byte-identical but was run from `.worktrees/cc8`, so the gate checker's own run passes only
once `wp/cc8` lands on `rag-it-all-tibs`.

The activation and web run is the one that needs the sanctioned anyio filter, form **(b)**, because
those modules import `fastapi.testclient` at module level: `-W error -W "ignore:The anyio.abc.
BlockingPortal alias is deprecated:DeprecationWarning"`. Every other run above is plain `-W error`
with no marker and no filter; the CD7 line itself needs neither.

Ruff, over every file changed and over this document:

```
.venv/bin/ruff check src/hippo/knowledge/staged_code.py src/hippo/knowledge/build_authority.py \
  src/hippo/knowledge/generation_profiles.py tests/unit/test_staged_code_writer.py \
  tests/unit/test_build_authority.py tests/unit/test_generation_profiles.py
.venv/bin/ruff format --check <the same six> \
  ai_docs/gates/rag-it-all/task-5-code-capture/evidence-cc8.md
```

`All checks passed!` and `already formatted`.

## Query shapes added (for the root's Neo4j parity run)

**None.** Every store call this slice makes already existed: `generation_write`, `_check_build`,
`_generation`, `_knowledge_get`, `put_knowledge`, `add_passages`, `add_symbols`,
`add_data_objects`, `add_commits`, `add_code_edges`, `link_definitions`, `add_modifies`,
`add_precedes`, `seal_generation`, `generation_checksums`, `_canonical_native`, and CC2's
`_native_rows(kind, ids=…|generation_id=…)`, `_knowledge_rows(kind, generation_id=…)` and
`_native_relationships(generation_id=…)`. No Cypher was written, no schema step added, no index
declared. The Neo4j parity run for CD7 is therefore a re-run of the same files, not a new shape
review.

## How each CD7 criterion is covered

| CD7 criterion | Test |
| --- | --- |
| batches are complete dependency groups, no dangling endpoint, no unbound native row | `test_every_group_is_dependency_complete_and_leaves_no_dangling_endpoint` (replays the whole plan and refuses any forward reference), `test_batch_size_coalesces_groups_without_reordering`, `test_an_omitted_native_row_is_refused_by_its_own_binding` |
| every batch revalidates lease, fence, authorization and suppression in its own short transaction | `test_an_epoch_change_during_a_batch_rolls_it_back_and_never_seals[authorization|suppression]`, `test_a_lost_fence_prevents_every_further_write_and_the_seal`, `test_an_expired_lease_prevents_the_very_first_write` |
| no callback, model call or filesystem access inside a transaction | the shared `write()` helper's `check` asserts the store holds no transaction on every call; `test_the_writer_reaches_no_model_clock_or_filesystem` greps the module; `test_the_local_core_is_callback_free_inside_an_existing_transaction`; `test_the_wrapper_refuses_a_transaction_the_caller_owns` |
| missing, extra or conflicting rows refuse the seal | `test_an_omitted_dense_passage_prevents_the_seal`, `test_an_extra_exact_member_is_not_silently_accepted_or_deleted`, `test_a_conflicting_native_payload_is_never_overwritten_by_a_write` |
| the seal writes an `IndexManifest` with the evidence, dense and native representations and matching checksums | `test_the_writer_seals_the_three_representations_without_publishing`, `test_the_sealed_generation_holds_every_native_row_binding_and_relation` |
| identical replay is idempotent | `test_an_identical_replay_of_every_batch_is_idempotent` |
| a conflicting persisted payload fails closed | `test_a_conflicting_persisted_native_payload_fails_the_resume`, `test_a_present_knowledge_payload_is_compared_and_not_taken_on_trust` |
| a lost fence or expired lease prevents every write and the seal | the two fence tests above, which also call `_seal` directly after the fence is lost |
| a resumed build adopts the persisted capture instant and reproduces every observation ID (B4) | `test_a_reclaimed_generation_keeps_its_capture_instant_and_every_observation_id`, `test_a_resume_that_re_takes_the_capture_instant_fails_closed` |
| a crashed build resumes the same generation and reports the skipped count | `test_a_crash_mid_build_resumes_the_same_generation_and_skips_what_it_wrote` |
| a staged generation holding a record the current derivation would not produce fails the resume (M2) | `test_an_extra_generation_scoped_row_fails_the_resume` |
| the probe checks every row of a group, never a sample, never tolerant equality | `test_a_partially_present_group_fails_the_resume`, the two conflict tests, `test_the_probe_reads_only_generation_scoped_and_identified_rows` |
| the per-batch payload ceiling refuses before the transaction opens | `test_the_per_batch_payload_ceiling_refuses_before_the_transaction_opens` |
| a sealed code generation validates under the `code` profile at seal, checksum and query time (ruling 13) | `test_a_code_generation_validates_under_the_code_profile_at_query_time`, `test_a_code_generation_without_the_code_profile_key_cannot_bind_or_seal`, `test_an_unknown_profile_name_refuses`, `test_a_sealed_code_generation_survives_close_and_reopen` |
| the plain-prose profile and every existing checksum are byte-identical | the 33 pre-existing `test_generation_profiles.py` cases, `test_staged_prose_writer.py`, `test_generation_store.py`, `test_dense_session.py`, plus `test_the_profile_selector_is_part_of_generation_identity` and `test_an_absent_profile_key_is_plain_prose_and_changes_no_existing_identity` |
| repo and archive sources capture authority | `test_every_managed_capture_kind_can_hold_build_authority[repo|archive]`, `test_an_archive_capture_without_a_repository_still_writes_and_seals` |
| `rebaseline` accepts an unrelated authorization epoch and refuses after a capability loss, a suppression change, a `SourceControl` change, a sticky failure and inside a transaction (CD8's clauses) | `test_rebaseline_adopts_an_unrelated_authorization_epoch_and_freezes_the_rest`, `test_rebaseline_refuses_after_a_capability_loss_and_latches`, `test_rebaseline_refuses_any_suppression_epoch_change`, `test_rebaseline_refuses_a_changed_source_control_even_with_every_capability[access_role_id|min_rank|owner_id]`, `test_rebaseline_refuses_after_a_sticky_failure`, `test_rebaseline_refuses_inside_an_ambient_transaction`, `test_rebaseline_refuses_on_a_closed_authority`, `test_rebaseline_holds_the_authorization_and_source_locks`, `test_a_failed_rebaseline_closes_the_child_it_built` |

## What a reviewer must not read as proven

1. **The fixture is a two-file tree and two hand-built commits.** `src/orders.py` plus
   `db/schema.sql`, four symbols, two data objects, two commits, seven passages, eight native rows,
   68 dependency groups. It exercises every group kind and every relation kind, but it is not the
   multi-hundred-file fixture CD9 asks for and no ceiling behaviour is measured here. The 64 MiB
   ceiling is proved by lowering the constant to 64 bytes, not by building a 64 MiB batch.
2. **No throughput or query-count bound is claimed.** CD1's counter belongs to CC2; this slice only
   proves the probe issues no unscoped read. Whether a 50,000-symbol generation's probe is fast
   enough is CD9's measurement.
3. **`resumed_from_batches` counts groups, not batches.** The plan and the receipt field both say
   "batches"; the number `ResumePlan.skipped_groups` returns is the number of skipped dependency
   *groups*, which is the only stable unit — the batch boundaries move with `batch_size`. CC9b
   should either put this number in the field as-is (recommended: it is the honest count of work
   not redone) or rename the field. Named here rather than decided.
4. **The Ladybug run is the acceptance backend; Neo4j is the root's.** CD9's line re-runs these
   files under Ladybug together with the rest; nothing here is backend-sensitive and no new query
   shape exists to review.

## Findings for CC9b, CC11 and the reviewer

1. **The configuration round trip.** See "A contract note CC9b must have" above. This is the one
   thing that will silently produce `Generation identity differs from its accepted input manifest`
   if done in the obvious order.
2. **Rebaseline must precede the failing check.** `check_local()` latches. The coordinator compares
   epochs itself between batches. See the authority section.
3. **Plan section 4's community label cannot be written by this lane, and CC6's finding 4 should be
   closed as "drop the claim".** `store.code.symbol_write_row` builds a closed dict with no
   `community` key and `add_symbols`' Cypher has no `SET n.community`, so a `community` value in a
   row is dropped before it reaches the database — and `_canonical_native` therefore never sees it
   either. Writing it needs a `store/code.py` change, which is nobody's in this wave. Routed to
   CC11: either drop "written in the `Symbol` row before the seal" from plan section 4, or open a
   `store/code.py` slice. The ban on a *post-seal* `set_symbol_communities` is unaffected and this
   lane calls nothing of the kind.
4. **`content_kind` is left unset on code passages** (CC6 finding 7). Nothing reads it
   (`generations.py:1226-1277` does not), `_canonical_native` emits it as `None` for prose too, and
   inventing a vocabulary here would change every code passage's canonical payload for no reader.
   If CC11 wants code passages distinguishable in the native table, that is a one-line addition to
   `PreparedCodePassage.native_row()` plus a checksum note.
5. **No writer rule version was folded into generation identity.** Ruling 10's first half names the
   *derivation* modules' rule versions (chunker, binding, history), and CC6/CC7 own those keys. The
   writer's batch grouping affects no record's identity — only the order rows are written in — so a
   changed grouping cannot produce a row a resume would mistake for another. M2's real risk is
   closed by the absence assertion, which this slice implements. If CC11 disagrees, adding
   `staged_code` to the `code_derivation` key is a CC6 change, not a CC8 one.
6. **`validate_generation_profile` still reads two whole tables per call** —
   `_knowledge_get("ArtifactRevision", …)` and `_knowledge_get("Artifact", …)` are bounded, but the
   function runs at query time through `dense_session.py:~115` and once per `generation_checksums`.
   The `GenerationMember` read is now scoped; the per-member `_knowledge_get` pair is O(members),
   which for a 1,000-file repository is 1,002 bounded reads on every query that touches the
   generation. Named for CC11: a `_knowledge_rows("ArtifactRevision", where=…)` batch form would
   need CC2's allow-list to grow, which is outside this slice's grant.
7. **`_write_batches` yields groups, and the accepted preflight is one of them.** A `batch_size` of
   1 therefore opens one transaction per group, which is what the fence tests use. CC9b should not
   read `batch_size` as "records per transaction": it is *groups* per transaction, and a group can
   be five records (a view) or two (a native row and its binding).
8. **A `ResumePlan` is not bound to the `PreparedCodeIndex` it was probed against.** It pins the
   generation ID and the group count, but not the group *order*. Group order is a pure function of
   the prepared output — `code_relations` preserves `facts.edges` order and every other stage walks
   a bundle tuple — so re-deriving `prepared` between the probe and the write with a differently
   ordered `facts.edges` would shift group indexes and skip the wrong ones silently. CC9b must probe
   and write with the same `PreparedCodeIndex` object. If CC11 would rather have that enforced than
   disciplined, the fix is one fingerprint field on `ResumePlan` over the group keys.
9. **`PreparedCodeIndex` refuses an object with no observation.** CC6's merged bundle does not
   enforce that, and CC6's own reasoning says such an object is unreachable evidence. If a future
   binding legitimately produces one, this refusal is the thing to revisit — it exists so that every
   object group is decidable from one scoped read.
