# Independent design and plan review: the Connector Developer Kit (CK1–CK6)

**Reviewer:** architect-reviewer-1 (herdr fleet, root tree, read-only).
**Subject:** the six implementation plans `ai_docs/plans/cdk-s1-registry.md`, `cdk-s2-contract.md`,
`cdk-s3-runtime.md`, `cdk-s4-kit.md`, `cdk-s5-port.md` and `cdk-s6-exemplar.md`, as amended by
`ai_docs/plans/cdk-rulings.md` R1–R38. They are reviewed against gates CK1–CK6 of
`ai_docs/gates/rag-it-all/cdk/GATES.md`, the design `docs/spec/connector-developer-kit.md`, sections 3,
4, 6 and 13.1 of `docs/spec/enterprise-graph-rag-v1.md`, and sections 4.2, 5 and 7 of
`docs/rag_it_all.md`. HEAD is `aeafd6b` on `rag-it-all-tibs`. The working HEAD moved to `bd6ee9a`
during the review. Its two commits add only the implementer briefs `ai_docs/handoffs/briefs/cdk-s1a.md`,
`cdk-s1b.md` and `cdk-s2a.md`, which "Briefs at `bd6ee9a`" below checks against these findings.
**Method:** I read each contract against the seams it cites. I wrote no code and ran no tests or Neo4j.
Every claim cites `file:line` evidence read at `aeafd6b`. The plans' anchors were written at `ef143b1`
or `f7b14ee`, and `src` and `tests` have not changed since. Every anchor I opened holds to within two
lines (see "Anchor verification").

## VERDICT: APPROVED WITH CHANGES

The kit's architecture holds up against the code:

- One registry opens today's closed vocabularies and registers every built-in value.
- A pure binder sits in `hippo.connectors`, above `knowledge`.
- A third coordinator reuses `BuildRun`, `BuildAuthority` and the store's claim, seal and publication
  compare.
- The two byte-identity paths run as coordinator lanes (R1).
- `emit` runs under a per-thread guard.

S1 splits its work along the persisted schema, which is right, and so is freezing the v7 descriptor
before the v8 bump. S3's twenty-row failure matrix is the most complete runtime proof this repository
has planned.

Four defects stop plans from meeting their gates as written. A fifth issue is a design decision to take
before any production sync:

- **B1.** The port cannot build. The pre-kit lanes compare whole `Generation` records with recomputations
  that lack the new fingerprint, and those comparisons sit in files no slice may touch.
- **B2.** After one policy change on an unchanged artifact, its partition can never sync again. The binder
  re-mints each span with the new `policy_id` under the span's old id.
- **B3.** S4's purity guard patches `time.monotonic` for the whole process. S6's validate route and MCP
  tool run it inside `hippo serve`, underneath the event loop.
- **B4.** S4's `run_case` calls a runtime entry that S3 does not provide. The signature, the stored
  classification and the failpoints all differ.
- **M1 (decision).** Every store read re-validates vocabulary against the registry. Rows written with an
  extension's vocabulary are unreadable in any process that has not loaded that extension.

**Counts:** 4 blockers, 16 majors, 22 minors (42 findings).

**Per plan:** S1, S2, S3, S5 and S6 are APPROVED WITH CHANGES. S4 is REJECTED: re-plan its §3.1
runtime, guard and failpoints, add the registry loader, then re-review §3.1. S4's scaffold, commands and
guide sections stand.

**Rulings with findings:** R1 (M12), R5 (m19), R6 (M6), R8 (inherits B3), R9 (M11, m12), R15 (M1,
M2), R16 (m20), R17 (m2), R19 (m14), R24 (m6), R25 (M14), R29 (M8), R30 (M9), R31 (M10), R32 (m7), R34
(defeated by B2) and R38 (the loader of M2 must merge before its callers). Six of them contradict the
design, spec §3 or an invariant, rather than leaving a gap: R17, R24, R25, R29, R30 and R31.

**Briefs already drafted:** `cdk-s1a.md`, `cdk-s1b.md` and `cdk-s2a.md` predate this review and conflict
with B1, B2, M1, M6, M8, M9, M10, m2 and m6. See "Briefs at `bd6ee9a`" before spawning.

---

## Findings

| ID | Sev | Plan and section, or `file:line` | Violates | Exact fix |
| --- | --- | --- | --- | --- |
| B1 | BLOCKER | S5 §3.2 seam, §7 S5a step 4 and S5b step 4; `knowledge/prose_preparation.py:164-176`; `knowledge/staged_code.py:305-311`, `:254-255`; `knowledge/code_binding.py:1037-1046` | CK5 | Grant S1b two edits: pass `registry_fingerprint=gen.registry_fingerprint` to `generation_for_inputs` at `prose_preparation.py:164-174`, and normalize the fingerprint on both sides of `staged_code.py:310`. Add `test_a_fingerprinted_prose_preparation_validates` and `test_a_fingerprinted_code_generation_writes_a_batch` |
| B2 | BLOCKER | S2 §8.1 step 3; S3 §6.3, §5.6 (DV1), §9 M8; `knowledge/model.py:420`; `store/knowledge.py:769-771` | CK3 "policy change mid-page"; R34 | `RevisionInput` gains `span_policy_id: str`, and `bind_batch` uses it for every span. S3 records the policy of a revision's first capture in `ArtifactRevision.metadata_json["span_policy_id"]`, where §5.4's whole-revision reuse keeps it, and passes it. Add matrix row M8b |
| B3 | BLOCKER | S4 §3.1 "Purity guard"; S6 §6.1 `POST /kinds/{name}/validate`, §6.2 `validate=` | CK4 (one guard, R-S3-5); CK6 (validate surfaces) | Set `testing.purity_guard = hippo.connectors.guard.forbid_effects` and delete the process-wide patch and its `*modules` argument. `test_the_purity_guard_refuses[...]` takes S3's list. S6 adds `test_post_validate_does_not_disturb_a_concurrent_request` |
| B4 | BLOCKER | S4 §3.1 `run_case` steps 2–4, `RUNTIME_FAILPOINTS`, the transports; S4 §9 R-S3-1, R-S3-2, R-S3-5; S3 §4.7, §5 entry, §9 | CK4 | Rewrite `run_case` step 4 to call `sync_connector` with S3's full signature after `store_classification`. S3 §4.7 gains `connector_id: str`. `RUNTIME_FAILPOINTS` becomes S3 §9's five scenarios on `_ReplayConnector`. S4 re-exports S3's transports (details below) |
| M1 | MAJOR | Design §3; S1 D8; R15; `store/knowledge.py:503-517` | I5; design §9 "listed, not skipped" | Decide in design §3: vocabulary is validated at write and at bind only. Reads accept any `Code`; projection and citations exclude rows of unregistered vocabulary and count them in coverage. S1a adds `test_a_row_of_an_unregistered_kind_reads_back_outside_its_registry` |
| M2 | MAJOR | R15; S4 §7, §9 R-S1-1; S5 §12 R-S1-2; S6 §11 R-S1-3; design §9 | CK4 `list`; design §9 allowlist and enablement | Add slice S4c, `connectors/loader.py`, with `load_registry(*, enabled_kinds, allowlist) -> LoadResult`: built-ins, then enabled in-repo packages, then allowlisted entry points, then `freeze()`. `cli.cmd_connector` and the `web/app.py` lifespan call it (grant those lines). Three tests |
| M3 | MAJOR | S3 §5.4 step 2, §9 M3/M4; `store/knowledge.py:814-819`; `store/authorization.py:188-193`; `knowledge/query_access.py:89-91` | CK3 "a replayed page changes nothing"; I6, I8 | Refresh a stored policy only when `expires_at - now < policy_ttl_seconds / 2`. Add M21: two syncs of unchanged content inside that window leave `authorization_epoch()` unchanged, and an open session still validates |
| M4 | MAJOR | S3 §5.5 step 2 | Design §3 ("a changed template is a new manifest and a rebuild"), §6 | Compute the candidate generation (steps 3–5) first. Return `no_changes` only when `gen.manifest_hash == parent.manifest_hash` and no policy changed. Add `test_a_template_version_bump_rebuilds_an_unchanged_partition` |
| M5 | MAJOR | S3 §5 entry checks, §4.7 `ensure_connector(enabled=True)` | Design §9, §10 ("only connector kinds the operator enabled run"); silently answers §14.3 | Add the entry refusal `ConnectorSyncRefused("Connector instance {id} is not enabled")`. Default `ensure_connector` to `enabled=False`. Add `test_a_disabled_connector_instance_is_refused` |
| M6 | MAJOR | S2 §6 steps 2–3; R6; S6 §3.3 `service` node | Spec §4.4; I2 | `NodeRef` gains `instance: Text = None`, admitted only on identity-only foreign endpoints and normalized by `normalize_provider_url`; the value comes from instance config. Add S2 test `test_identity_only_endpoint_is_keyed_by_its_declared_instance`. S6's config gains `catalog_instance` |
| M7 | MAJOR | Design §4 `Node.provenance` row; S2 §8.2 row `Node.provenance.observed_at` | Spec §3 "`observed_at`: RFC 3339 of the version"; I12 | Map `Provenance.observed_at` to `ArtifactRevision.source_updated_at`, with its original spelling, timezone and precision, and null when the provider gives none. `ArtifactRevision.observed_at` stays the kit's receipt clock. The totality row asserts the fetch's value |
| M8 | MAJOR | R29; S1 §5.5 fixture `incident_extension` (`pager_feed`); S2 §8.3 | Design §3 `TypeExtension.evidence_sources`; CK1 tests | Amend R29 so an extension source registers with its class, as `EvidenceSourceDefinition(name, family, evidence_class)` excluding `model_inferred` and `human_verified`. Keep S2's refusal of invalid (family, source) pairs. S1's fixture uses built-in `metadata` until then |
| M9 | MAJOR | R30 | "Unknown policy is deny"; design §10 | Amend R30: an unmapped principal in a deny list makes the observation `unknown`; an allow list the mapping empties becomes `unknown`; unmapped allow entries are dropped and counted. The map is applied in S2 `policy_record`, with a test |
| M10 | MAJOR | R31; S1 §5.3; S2 §8.4 | `knowledge` must not import `connectors` or `ingest` (`tests/unit/test_layering.py`) | Amend R31: only extension locator kinds set `verifier`. Built-in verifiers stay S2's table in `connectors/emit.py`, consulted first. A kind with neither is refused at bind and by `validate`. Drop "byte-range", which names no built-in kind |
| M11 | MAJOR | S5 decision 11, §3.2 step 1, §7 S5a step 5 | Layering: `connectors` above `ingest` | S5a pins the new edge in `tests/unit/test_layering.py` (grant it): `managed_activation` is the only ingest module that may import `hippo.connectors`, and `connectors.{lanes,local,git}` never import `managed_activation` or `pipeline`. `lanes.py` raises its own `LaneRefused`. The orchestrator ratifies the edge |
| M12 | MAJOR | R1 condition; CK5 CRITERIA (capture-side assertions); S4 §3.1 `ASSERTIONS`; S5 §8 | CK5 clause with no test and no defined assertion | S4a adds `check_capture(connector, config, *, sample)` with five named rules, each with a negative fixture. S5a and S5b each add a test that their connector passes `check_capture` |
| M13 | MAJOR | CK2 CRITERIA "probe is a pure function…"; S2 §11 (deferred to S4); S4 §3.1 | CK2 clause with no test for a connector's `probe` | S4a adds a `probe_deterministic` assertion: `probe` runs twice under the replay transport with two store-clock instants and must return equal `Classification`s; it needs a negative fixture. Amend the CK2 row to cite it, or move the clause to CK4 |
| M14 | MAJOR | R25; S5 §5; S3 §5 entry | S3's trusted-local rule; CK5 dispatch | Amend R25 so that until Task 15, `run_managed_build` refuses `kind="connector"` with `ManagedDispatchError`. S5a adds the branch and `test_a_connector_source_reindex_is_refused_by_dispatch` |
| M15 | MAJOR | S6 §3.3 capabilities and import list, §5 deletion test; S3 §6.4 | CK6 (the update fixture); R-S3-5 | S6's import allowlist admits `hippo.connectors.http` for `ProviderNotFoundError`; S2a's `base.py` merges before S3a's `http.py`, so it cannot re-export it. The exemplar declares `ConnectorCapabilities(acls=True, inventory=True)`, and its `fetch` raises `ProviderNotFoundError` for an id absent from the export. S4's `_ReplayConnector.fetch` raises it for an id with no `inputs/` file |
| M16 | MAJOR | S4 §3.2 `connector.py.tmpl`; S2 §6 step 2 | CK4 "`new` writes a package whose `validate` passes"; S6 starts from it | The template emits `NodeRef(kind="$primary_kind", key={"id": record["id"]})`, and the kit fills `instance`. Regenerate the pinned scaffold output |
| m1 | MINOR | S1 §5.2 "Behaviour" (`extension_scope()` described twice); D2; §10 S4 bullet | R16 | Delete the second `extension_scope()` bullet, which describes a new registry installed with `use_registry`, and the sentences saying S2's binder accepts only `REGISTRY` |
| m2 | MINOR | R17; S1 §6.3; `store/migrations.py:518-525` | LadybugDB 0.15.3 has no secondary-index DDL | Amend R17 to Neo4j only. S1b adds `CREATE INDEX` for `Unit.passage_id` and `Unit.content_hash` and updates `test_v8_schema_steps_are_exact_per_backend` |
| m3 | MINOR | CK1 CRITERIA "stored on every managed generation" | CK5's allowed difference (pre-kit lanes store none) | Reword to "on every generation built by the kit runtime or a coordinator lane". Evidence: S3c's fingerprint test and S5's retried-generation tests |
| m4 | MINOR | CK1 CRITERIA "a test proving the same input cannot reach `emit`"; S1 D7; S2 `test_unregistered_or_undeclared_type_at_bind_is_refused` | CK1 (per refusal reason) | Parametrize S2b's test over S1's `test_register_refuses` cases, importing the `incident_extension` variants |
| m5 | MINOR | S1 §5.5 test 4 `test_builtin_key_templates_match_the_identity_helpers` | Test honesty | Compare part names and order with the helper's parameters (`inspect.signature`), not only lengths |
| m6 | MINOR | R24; S2 §8.5 "split it at 1500"; S4 `TOKEN_BOUND = 1500` | Spec §3 "≤ 1,500 tokens" | R24 records the 6,000-character bound as an approximation of the spec, because code and CJK text exceed one token per four characters. S2's message interpolates `PASSAGE_CHAR_BOUND`, and S4 sets `TOKEN_BOUND = base.PASSAGE_CHAR_BOUND` |
| m7 | MINOR | R32; S2 §4.1 `ConnectorDescriptor` | Unimplementable as stated | `ConnectorDescriptor` gains `extension: TypeExtension`. S3 checks that each registered definition equals it |
| m8 | MINOR | S6 §3.3 code blocks | S1 §5.2, S2 §4.1, §4.6 | `FactTemplate` gets `consumes`. Use `ParserVersion.parse("json@1")`, including for `ParseFailure.parser`. Add `metadata_origin="catalog"` to nodes and edges with `source="metadata"`. The config gains an HTTP(S) `instance_url` for `ensure_connector` |
| m9 | MINOR | S5 §3.2 `connector: Connector`; §4 descriptors; §5 `default_registry()`; §8 `test_local_fetch_policy_equals_…` | S2 §4.1 `SyncConnector`, R1, R16 | Type the argument as `SyncConnector`, set `capabilities.derivation="coordinator_lane"`, and call `current_registry()`. The fetch-policy test compares a `mode="workspace"` observation, since `PolicyObservation` has no origin |
| m10 | MINOR | S3 §7.1 (`staged_code._epochs`, `_local`, `_Group`, `_immutable_native`); S2 §8.4 (`ingest.provenance._lines`) | Private cross-module coupling | Promote them to public names under an explicit grant, or re-export them from the owning module, and pin with an import test |
| m11 | MINOR | S6 §6.1 "Failures"; `knowledge/public_errors.py:118-140` | Error surfaces | `web/routes/connectors.py` maps `CredentialError`, `Provider*Error`, `RegistrationRequired` and `ConnectorSyncRefused` to coded responses with redacted messages, with tests. `knowledge` cannot list `connectors` classes |
| m12 | MINOR | S3 §12; R9 | `tests/unit/test_import_order.py` | S3c appends `hippo.connectors.sync`, `hippo.connectors.emit` and `hippo.knowledge.staged_records` to `MODULES`, serialized by R9 |
| m13 | MINOR | S3 §9 M20 against M9 | Test honesty | M20's spy ignores the `collect_generation(G1)` call that M9's own test makes |
| m14 | MINOR | R19; S1 §5.3 `ALIAS_OF`, `OWNED_BY` | Spec §6 owner column | Add `custom` to `ALIAS_OF`'s owners, since `SAME_OBJECT_AS` already admits it. Record that spec §6's `OWNED_BY → Team (work)` needs `ticket` subjects, which is Task 11's work |
| m15 | MINOR | S3 §5.4 step 4 (pending log), step 3 (artifact updates) | Row size; missed `canonical_uri` change | Keep the pending log in the raw store, as the seen set already is. Update `canonical_uri` when it changes (it is mutable, `store/knowledge.py:155`) |
| m16 | MINOR | S3 §9 (no CD2 row) | CD2 rule for connector sources | Add M22: between first capture and first publication, the partition Source contributes nothing to `query_session(ctx, EVERYTHING)` |
| m17 | MINOR | S4 §3.1 `offline_ollama` | Duplication with `tests/fakes/fake_ollama.py:146` | Move the hashed-vector algorithm into `connectors/testing.py` and make the fake import it |
| m18 | MINOR | S4 §3.1 `edges_fully_attributed`; design §8 against design §4 | Kit and binder disagree | Design §8 reads "a source with a deterministic row in the §4 table". The assertion calls `emit.evidence_class(...)` |
| m19 | MINOR | S4 §3.3 `sync <instance>` (not dry run); R5; `cli.py:257-267` | Wiring completeness | Either drop the non-dry-run `sync` from v1, or specify: `_require(principal, "manage_sources")`, then `BuildActor.trusted_local()`, then exit 2 when the instance has no stored classification, with a test |
| m20 | MINOR | S3 §5.6 thread pool; §10.1 forbidden set | S1 §10 thread-context note; design §8 guard | Run each worker in `contextvars.copy_context().run(...)`. Forbid `time.clock_gettime`, `time.clock_gettime_ns`, `time.process_time`, `sys.setprofile` and `threading.setprofile` |
| m21 | MINOR | S2 `test_keys_is_the_only_knowledge_object_constructor_in_connectors` | Test honesty | Also flag `KnowledgeObject.model_validate`, `.model_construct` and `.replace` outside `keys.py` |
| m22 | MINOR | CK1 "never traversed"; S1 D10; `knowledge/dense.py:182-198` | CK1 clause, structural lane | S1a adds a test: a stored `SAME_OBJECT_AS` assertion is absent from projection and structural relations, and loading them raises nothing. `dense.py:197` raises for a predicate outside `PREDICATES` |

---

## Blockers

### B1: the lanes cannot build a fingerprinted generation

**Binds:** S5 §3.2 (the seam), §7 S5a step 4 and S5b step 4; S1b D21. **Gate:** CK5.

S5's seam sets `Generation.registry_fingerprint` on the generation each coordinator creates. Two
comparisons downstream compare that whole record with a copy recomputed without the fingerprint:

- **Prose.** Preparation recomputes `wanted = generation_for_inputs(...)` without the fingerprint and
  refuses `if gen.replace(coverage_json="{}") != wanted` with "Generation differs from accepted
  revision/configuration identity" (`knowledge/prose_preparation.py:164-176`). Every prose build
  through the lane refuses.
- **Code.** `materialize_code_evidence` re-settles the generation from its inputs
  (`knowledge/code_binding.py:1037-1046`), so the merged bundle carries a copy without the fingerprint.
  `PreparedCodeIndex.generation` returns that copy (`knowledge/staged_code.py:254-255`, built at
  `ingest/code_generation.py:571-572`). The writer then refuses
  `if current.replace(coverage_json=gen.coverage_json) != gen` against the persisted, fingerprinted row
  with "Persisted generation differs from accepted preparation" (`staged_code.py:305-311`).

S1 §10 names the prose half as an S3/S5 hand-off, but no slice owns the fix: S1b, S3 and S5 all list
`src/hippo/knowledge/**`, or these files, as do-not-touch. S5's byte-identity tests would fail at world
B's first build. Two nearby comparisons are safe: `generation_profiles.py:264-276` compares only `id`
and `manifest_hash`, and `staged_prose.py:44` compares the coordinator's own generation with its
persisted copy.

**Fix.** S1b introduces the field, so grant it both edits and both tests in the findings table. With the
fix, the code path's normalized comparison accepts the stored fingerprint, which is sound because the
fingerprint is outside identity and cannot be updated (S1 D21).

### B2: a policy change on an unchanged artifact stops its partition syncing

**Binds:** S2 §8.1 step 3; S3 §6.3, §5.6, §9 M8; R34. **Gate:** CK3 "policy change mid-page".

1. S2 binds every span with `policy_id = revision.artifact.policy_id`, the artifact's policy at bind
   time.
2. `EvidenceSpan` identity is `(revision_id, locator_json, text_hash)` (`knowledge/model.py:420`), so
   the policy is not part of the id.
3. S3 re-emits every member revision on every run (§5.6, DV1, ratified by R37).
4. After a `policy_change` updates `Artifact.policy_id` (§5.4 step 3), the next build binds a span with
   the stored span's id and a different `policy_id`.
5. `put_knowledge` refuses it with "Immutable record already exists with different contents"
   (`store/knowledge.py:769-771`), and `probe_staged_records` fails closed on the differing payload
   (S3 §7.1).
6. The failure path keeps G1, and every later sync of that partition fails the same way until the
   artifact's content changes.

S3 §6.3 says "the stored span is reused with its original `policy_id`", but neither S2's `bind_batch`
nor S3's `_bind`/`RecordBundle` has a step that does this. Matrix row M8 ("G2 publishes A under the new
policy") therefore cannot pass.

R34's rule is right, and the code supports it: narrowing takes effect through the artifact policy check
(`knowledge/access.py:514`), and widening waits because the span keeps its policy (`:529`). The re-bind
defeats it.

**Fix.** `RevisionInput` gains `span_policy_id: str`, and `bind_batch` uses it for every
`EvidenceSpan.policy_id`. At capture, S3 records the artifact's current policy in
`ArtifactRevision.metadata_json["span_policy_id"]`. §5.4 step 1 reuses a stored revision whole, so the
value keeps the first capture's policy, and S3 passes it into `RevisionInput`.

Add matrix row **M8b**. After a policy-only change, two more syncs publish; every stored span keeps its
`policy_id`; a reader removed by narrowing loses A at the checkpoint; and a reader added by widening
sees A only after a new revision.

### B3: S4's purity guard patches the whole process under `hippo serve`

**Binds:** S4 §3.1 "Purity guard"; S6 §6.1, §6.2; R-S3-5, R8. **Gates:** CK4, CK6.

While held, S4's guard patches these module attributes for the whole process: `time.time`,
`time.time_ns`, `time.monotonic`, `time.perf_counter`, `socket.socket.connect`, `httpx.Client.send`,
Ollama's methods and `subprocess.Popen.__init__`. Its safety argument is that `run_case` holds it "only
when no build is in flight … so no store thread can trip it".

That holds in a CLI process, but not inside a server. S6 calls `validate_package(name, runtime=False)`
from `POST /api/connectors/kinds/{name}/validate` and from the `hippo_connectors` tool, and
`validate_package` runs `assert_emit_pure` (S4 §3.1, step 4). Inside `hippo serve`, the route runs on a
worker thread while other threads keep calling the patched functions:

- the asyncio loop thread calls `time.monotonic()`, which is the loop's own clock;
- other requests call `httpx`;
- lease heartbeats read the clock.

Each of those calls raises `PurityViolation` in a thread that is not running `emit`. The CK6 surface
tests go through `TestClient`, whose portal thread runs the same loop, so they fail the same way.

S3 §10.1 already designs the right guard: a per-thread `sys.setprofile` hook, checked against the root
venv while planning. S3 says S4 re-exports it (R-S3-5). S4 plans a second guard instead, and its
forbidden set lacks `time.sleep`, thread start, `os.fork`, `os.posix_spawn` and `time.localtime`. The
kit could therefore pass a connector that the runtime then refuses, which breaks S4's own promise that
"the two can never disagree because they are one function".

**Fix.** Apply the table fix. Then run `assert_emit_pure`'s two `emit` calls inside `forbid_effects()`
on the calling thread.

### B4: S4's `run_case` calls a runtime entry S3 does not provide

**Binds:** S4 §3.1 `run_case`, `RUNTIME_FAILPOINTS`, `record_transport`/`replay_transport`; S4 §9
R-S3-1, R-S3-2, R-S3-5; S3 §4.7, §5, §9. **Gate:** CK4.

`run_case` step 4 calls the entry S4 §9 proposed:
`sync_partition(ctx, connector, *, config, partition, actor, registry, clock, fault_hook=None, on_batch=None)`,
returning a generation id. S4 §9 says S3's spelling wins, but the plans differ in behaviour, not only
in names:

1. **Signature.** S3's `sync_connector` (§4.7) also requires `options`, `raw_store`, `embedding_spec`,
   `operation_id` and `should_stop`. It takes no `clock` (R27) and returns a `SyncReceipt`. Its body
   uses a `connector_row`, but its signature gives it no way to find one: the row cannot be derived
   from `connector` and `config`.
2. **Stored classification.** S3 refuses before capture when the partition has no stored classification
   ("Probe the connector before syncing partition {partition}", §5 entry). `run_case` never probes or
   stores one, and `_ReplayConnector` "keeps the real `probe`", which may call the provider. That
   refusal stops every golden run, a full-scope `validate`, `hippo connector new` (whose
   `render_package` calls `run_case`), `sync --dry-run` and the runtime assertions.
3. **Failpoints.** `RUNTIME_FAILPOINTS` (`after_fetch_before_checkpoint`, `replayed_page`,
   `failed_inventory`, `policy_change_mid_page`, `delete_with_live_session`) are not S3's
   `FAULT_POINTS`. Four of the five are provider scenarios in S3 §9's table (replay page N, fail page 2
   of an inventory, a policy change inside a page, a delete with an open session), not a `fault_hook`
   raise. `assert_runtime_resilience`, as specified with "S3's `fault_hook` raising at that failpoint",
   cannot produce them.
4. **Recording.** Recording and replay are specified twice with different errors. S3's
   `http.replay_transport` raises `ProviderMalformedError` on an unexpected request (§10.2); S4's
   `testing.replay_transport` raises `ContractViolation("provider_recording", ...)` (§3.1).

**Fix.**

- **S3 §4.7:** add the keyword `connector_id: str`.
- **S4 `run_case` step 4, in this order:**
  1. `ensure_connector(...)` and `connector_source(...)`;
  2. `_ReplayConnector.probe`, whose `list_changes` and `fetch` are the replay, then
     `store_classification(...)`;
  3. `sync_connector(ctx, replay, connector_id=row.id, config=..., partition=...,
     actor=BuildActor.trusted_local(), registry=current_registry(), options=SyncOptions(emit_workers=1),
     raw_store=..., embedding_spec=embedding_spec(ctx.ollama), operation_id=f"validate.{case}",
     should_stop=lambda: False, on_batch=..., fault_hook=...)`;
  4. read `receipt.generation_id`.
- **Failpoints:** replace `RUNTIME_FAILPOINTS` with S3 §9's five boundary rows, each a
  `_ReplayConnector` scenario that uses S3's labels.
- **Transports:** `testing` re-exports S3's `record_transport` and `replay_transport`.

---

## Majors

### M1: stored extension vocabulary is unreadable where the extension is not registered

S1 D8 turns these fields into `Annotated[Code, AfterValidator(<registry lookup>)]`:
`KnowledgeObject.kind`, `Artifact.kind`, `Connector.kind`, `EvidenceSpan.locator_kind`,
`QueryRequest.kinds`, and from S1b `AssertionVersion.source`. Every store read builds its records with
`model.model_validate_json` (`store/knowledge.py:503-517`), so those validators run on reads as well as
writes.

A process that has not registered the vocabulary a row was written with raises `Unknown object kind` on
reading that row. That covers:

- the MCP stdio server;
- `hippo ask` against a local store;
- evaluation scripts;
- startup recovery (`recover_generation_builds`, seal validation) before any loader has run;
- a `hippo serve` whose connector package failed to import, which design §9 says is "listed with its
  error, not skipped".

The failure is not confined to connector evidence. Access proofs read objects by id
(`knowledge/access.py:537`) and projection reads the authorized set (`knowledge/projection.py:498`), so
one such row fails the whole query.

No CK gate catches this, because every test registers and reads in one process. The only v1 path that
writes extension rows into a configured store is S4's non-dry-run `hippo connector sync <instance>`
(§3.3), which m19 finds under-specified. If that command survives m19, then `hippo ask`, the MCP stdio
server and `hippo serve` after a restart all raise `Unknown object kind` on reads of that store. M1's
decision therefore gates S4b, not only Task 15's sync route. S1a implements D8 either way, so record the
decision before S1a spawns.

### M2: the loader R15 assigns to S4 is in no plan

R15 gives design §9's `Registry.load()` to S4 and has "the `hippo connector` commands and `hippo serve`
startup call the loader". S4's plan predates R15. It has no loader module, no entry-point discovery, no
trusted-kind allowlist (design §9: "empty by default for third-party entry points"), no freeze policy
and no startup wiring. The startup hook is the `web/app.py` lifespan (`web/app.py:61-70`), which S6 owns
and S4 may not touch.

Three other plans depend on the loader:

- S4's `test_list_shows_an_entry_point_that_fails_to_import_with_its_error`;
- S5's `default_registry()`, specified as "built-ins plus in-repo packages";
- S6's R-S1-3 ("discovered but not registered until enabled").

S4a is already at the size of CC6 without it. Add S4c as the table says, with three tests:
`test_loader_lists_a_failing_entry_point_and_continues`,
`test_loader_skips_an_entry_point_missing_from_the_allowlist` and
`test_serve_startup_installs_a_frozen_registry`. State that enabling a kind takes effect at restart,
because the loaded registry is frozen.

### M3: every policy refresh moves the global authorization epoch

S3 §5.4 step 2 calls `update_knowledge(verified_at=now, expires_at=now + ttl)` on every stored policy a
page sees again. `AccessPolicy` is an authorization record (`store/authorization.py:113-114`).
`update_knowledge` calls `record_mutation` whenever any field changed (`store/knowledge.py:814-819`),
and `record_mutation` bumps the authorization epoch (`authorization.py:188-193`).

Three consequences follow:

1. A replayed page carries a later `now`, so M3 and M4's expectation that "the rerun changes no row, no
   epoch" is false as specified.
2. Any sync that sees one known artifact again invalidates every open query session on the instance
   ("Permissions changed; repeat the query", `knowledge/query_access.py:89-91`) and forces every running
   build to rebaseline.
3. With the default 600-second policy TTL, a polling connector does this continuously.

### M4: `no_changes` ignores configuration and templates

S3 §5.5 step 2 returns `no_changes` when the member set equals the parent's and no policy changed,
before steps 4 and 5 compute the configuration and the generation. Several changes leave member sets
unchanged:

- a connector version bump;
- a fact template version bump, which S1 D25 carries into `descriptor_configuration`;
- a `TypeMapping` changed by a re-probe;
- a derivation version change.

After any of these, an unchanged partition keeps its old generation until some artifact changes. Design
§3 says the opposite: "a changed template is a new manifest and a rebuild rather than a silent
re-reading of old evidence".

### M5: the runtime runs connectors no operator enabled

S3 §5's entry checks never read `Connector.enabled`, no plan checks a trusted-kind allowlist, and
`ensure_connector` defaults to `enabled=True`. Design §10 says "only connector kinds the operator
enabled run". Readers stay protected, because `knowledge/access.py:462-470` denies a disabled
connector's artifacts, but the connector's own code still runs. This quietly answers design §14.3
"trusted".

### M6: foreign endpoints are keyed by the emitting connector's instance

S2 §6 fills every instance part (`instance`, `provider_instance`, `catalog_instance`) from the emitting
connector's `Connector.instance_url`, and refuses an instance part inside a `NodeRef`. R6 makes
identity-only foreign endpoints "how cross-domain edges get endpoints".

For a built-in kind whose key starts with an instance, that does not work. `service` is keyed
`catalog_instance, reference` (S1 D13). The incidents connector's `service` object is therefore
`[incidents instance, reference]`, which never equals Backstage's `[catalog instance, reference]`, so
`AFFECTS` points at a node no other source shares. That breaks spec §4.4, where a cross-domain edge is
stored once and read in reverse over the same nodes, and I2, where names are scoped by the provider
instance that minted them. S6 §3.3 hides the problem by keying `service` "from
`(tool_instance, service)`", which S2 would refuse. S6's retrieval test does not catch it, because it
reads only the exemplar's own facts.

### M7: `Provenance.observed_at` lands in the receipt clock

Spec §3 defines `observed_at` as "RFC 3339 of the version": the time of the commit, migration,
revision or snapshot named by `version`. Design §4 and S2 §8.2 map it to
`ArtifactRevision.observed_at`, which is when hippo received the bytes. `docs/rag_it_all.md` §5.5 says
that clock "must not be interpreted as" when the source's claims became true.

The totality test would pass, because it checks where the value lands, not what it means. S2's
`RawFetch` already carries `source_updated_at` with its original spelling, timezone and precision, so
the correct mapping costs nothing.

### M8: R29 makes `TypeExtension.evidence_sources` unusable and breaks S1's fixture

R29 moves the design §4 derivation table into `knowledge/builtin_types.py` as fixed data, and refuses
any evidence source with no row in it. That has two effects:

- Every `TypeExtension.evidence_sources` entry is refused, so the design §3 field can never be used.
- S1's shared fixture `incident_extension()` registers `pager_feed` (S1 §5.5), so it is refused too,
  and most of `test_registry.py` and `test_registry_model.py` fail at setup.

R29 also says "bind has no evidence-class refusal path". That is false. Invalid (family, source) pairs
such as `deterministic`/`similarity` or `probabilistic`/`parser` still need S2 §8.3's refusal and its
test.

### M9: R30 drops unmapped deny principals

R30 drops unmapped provider principals "from allow lists (deny by omission)" but says nothing about
deny lists. Dropping an unmapped `deny_groups` entry from a `mode="workspace"` policy grants the whole
workspace, including that group's local members. Separately, a restricted allow list that mapping
empties trips S2's refusal "A known restricted policy needs at least one allowed principal".

### M10: R31's built-in verifiers cross the layering rule

R31 adds `LocatorKindDefinition.verifier` (S1a) and has "S2a supply verifiers for the built-in line and
byte-range kinds". Four facts rule that out:

1. Built-in registrations live in `knowledge/builtin_types.py`, which may not import
   `hippo.connectors` (S1 test 18; S2's `test_knowledge_package_never_imports_connectors`).
2. S2's `file_lines` verifier uses `ingest.provenance._lines` (S2 §8.4), which a knowledge module may
   not import either (`tests/unit/test_layering.py` `ALLOWED`).
3. The registry swaps its state whole and freezes (S1 §5.2 "State"), so S2 cannot attach verifiers after
   install.
4. There is no "byte-range" built-in locator kind among the seven (`knowledge/model.py:168-245`).

### M11: S5 makes `ingest` and `connectors` import each other

S5 decision 11 has `ingest/managed_activation.py` import `connectors.lanes`, `connectors.local.connector`
and `connectors.git.connector` at module level, while `connectors.local` imports `ingest.repo_capture`
and `ingest.readers`. The brief's rule is one-directional: `connectors` may import `ingest`, not the
reverse. S5 proves the edge acyclic only through `test_import_order` entries; nothing pins which modules
are allowed on it.

`lanes.py` §3.2 also contradicts itself: step 1 refuses with `ManagedDispatchError`, which lives in
`managed_activation.py`, while the same section says `lanes.py` "imports nothing from
`hippo.ingest.managed_activation`".

### M12: CK5's capture-side kit assertions exist in no plan

R1 conditions the lanes on "the kit's capture-side assertions run on both connectors", and CK5's
CRITERIA require that "the kit's capture-side contract assertions (probe, list_changes, fetch,
fetch_policy) pass on both connectors". S4's `ASSERTIONS` cover only emission batches, purity, runtime
resilience and the registry lock, and no S5 test runs capture assertions. The clause has neither a
definition nor a test.

S4a should define five rules, each with a negative fixture: `change_page_single_partition`,
`fetch_matches_ref`, `canonical_uri_without_credentials`, `unknown_policy_carries_no_principals` and
`probe_deterministic` (shared with M13).

### M13: nothing tests that a connector's `probe` is pure

CK2 requires "`probe` is a pure function of descriptor, config and sampled bytes". S2 tests only
`classify` and defers "a concrete connector's `probe`" to S4's kit (S2 §11). S4 has no probe assertion.
Design §2 says "the test kit asserts that `probe` is a pure function".

### M14: R25 routes connector sources through an actor S3 refuses

R25 has S5a route `kind="connector"` from `run_managed_build` to `sync_connector`. Three things block
that:

- `run_managed_build` receives the requesting user's actor. The CLI builds it with
  `BuildActor.reader(principal)` (`cli.py:257-267`), and S3 refuses any actor that is not trusted-local
  (§5 entry).
- It holds no frozen registry, connector class or stored connector config.
- S5 §5 plans no such branch and no test.

### M15: the exemplar cannot withdraw a missing incident

S6's `test_an_update_page_republishes_and_a_complete_scan_withdraws_the_missing_incident` relies on
S3 §6.4, which infers a deletion only when two conditions hold:

- the descriptor declares `capabilities.inventory=True`, which the exemplar's
  `ConnectorCapabilities(acls=True)` does not;
- a confirming `fetch` raises `ProviderNotFoundError`, which lives in `connectors/http.py`, a module
  outside the exemplar's permitted imports (S6 §3.3).

Any other error only counts `reconcile_unconfirmed`, so the incident is never withdrawn.

### M16: the scaffold emits a key part S2 refuses

S4's `connector.py.tmpl` declares `key_template=("instance", "id")` and emits key parts
`(config.instance, record["id"])`. S2 §6 step 2 refuses any instance part inside a `NodeRef` ("The kit
fills {part} of {kind} from the connector's instance; do not emit it"). A freshly scaffolded package
therefore fails `validate`, which is CK4's second clause, and S6 starts from exactly that output.

---

## SPEC verdicts per gate

### CK1: PASS WITH CHANGES

| CRITERIA clause | Tests in the plan | Status |
| --- | --- | --- |
| every `Literal`/frozenset member today is a built-in; existing model tests pass unchanged except the v8 pins | S1 `test_builtins_register_every_value_the_closed_vocabularies_held`, `test_object_kind_literal_names_exactly_the_builtin_kinds`; §5.6 regression line; §6.4 adapted pins | covered |
| each design §3 refusal reason triggers at `Registry.register` | `test_register_refuses[...]` (19 rows) | covered; if R29 stands, its new refusal has no test (M8) |
| … and a test proving the same input cannot reach `emit` | S1 D7 record-validator proxy; S2 `test_unregistered_or_undeclared_type_at_bind_is_refused` (one case, on the CK2 line) | partial (m4) |
| `Registry.fingerprint()` stored on every managed generation, schema v8, outside identity, never in `configuration_json` | `test_generation_registry_fingerprint_is_a_sha256_outside_identity_and_the_manifest`, `test_registry_fingerprint_round_trips_outside_identity_and_cannot_change`, `test_connector_configuration_is_canonical_…` | field covered; "every managed generation" contradicted by CK5 (m3) |
| changes when a fact template changes, and the declaring connector's configuration changes with it | `test_a_changed_fact_template_changes_the_fingerprint_and_the_declaring_configuration` | covered |
| `SAME_OBJECT_AS` built-in identity predicate, any kind pair, exempt from ownership, never traversed | tests 11, 12 of `test_registry_model.py`; `test_projection_reads_predicate_definitions_through_the_registry` | partial: structural lane untested (m22) |
| `ALIAS_OF` keeps its `alias` subject rule | `test_alias_of_keeps_its_alias_subject_rule` | covered |
| v8 adds `Unit`, `registry_fingerprint`, `classification_json`, six `AssertionVersion` columns on three backends; frozen v1–v7; identities unchanged | `test_store_migrations.py` items 1–5; `test_v8_fields_leave_existing_identities_unchanged`; `test_a_v7_generation_keeps_its_published_evidence_checksum`; Neo4j parity file | covered (m2 for R17's indexes) |
| `EvidenceClass` gains `rule_derived`, `similarity_inferred` | `test_the_two_new_evidence_classes_validate_and_change_no_column` | covered |

### CK2: PASS WITH CHANGES

| CRITERIA clause | Tests | Status |
| --- | --- | --- |
| every spec §3 field lands in the record and column design §4 names | `test_every_spec_section_3_field_lands_in_its_design_section_4_column`, `test_the_totality_table_names_every_spec_section_3_field` | covered, but one row maps to the wrong column (M7) |
| `KnowledgeObject` identities only from `connectors/keys.py` | `test_keys_is_the_only_knowledge_object_constructor_in_connectors`, `test_object_id_equals_knowledge_object_identity` | covered (m21) |
| `evidence_class` follows the table; a connector cannot set it | four tests | covered; R29 conflict (M8) |
| non-owner or reverse-direction edge refused with the developer message | three tests | covered |
| every span verified against revision bytes at its locator | the `*_span_*` tests, `test_locator_kind_without_a_verifier_is_refused`, `test_unit_offsets_are_verified_within_the_unit_span` | covered; R31 hook (M10) |
| every rendered unit is one template output | three tests | covered |
| `probe` is a pure function of descriptor, config and sampled bytes | `test_classify_is_pure_under_reordering_clock_and_forbidden_io` only | **not covered** for a connector's `probe` (M13) |
| classification order declaration, content, name; `custom/unclassified` counted | five tests | covered |

**Totality (question 1, second half).** Mostly yes. Every field of `Node`, `Edge`, `Passage`, `Unit`,
`AliasCandidate` and `Provenance` has a row in S2 §8.2, and the rows agree with design §4 and with the
columns S1b adds. There are three exceptions:

- `Provenance.observed_at` goes to the receipt clock (M7).
- `Passage.ts` has no column (S2 DV1, ratified by R37). It is enforced equal to the node's `valid_from`
  or the revision's `source_updated_at`.
- `Node.domain` has no per-row column; it is derived from the kind's family (design §4).

### CK3: FAIL as written; PASS after B2, M3, M4

| CRITERIA clause | Tests | Status |
| --- | --- | --- |
| a fixture connector runs every step of §7 | `test_a_fixture_partition_syncs_through_every_step_and_publishes`, `test_every_fault_point_label_is_reachable` | covered |
| failure injection at the five durable boundaries | matrix M1–M9 | covered; M8 cannot pass (B2) |
| no deletion follows a failed inventory | M5, M6 | covered |
| a replayed page changes nothing | M3, M4 | asserted, but false as specified (M3) |
| publication uses the existing `BuildAuthority` compare | `test_publication_uses_the_build_authority_and_writes_one_published_index_event`, M15 | covered |
| the active generation is never deleted | M13, M19, M20 | covered (m13) |
| `IndexEvent` rows for the append lane | as above (DV2, R37) | covered |
| the runtime forbids network, model and clock inside `emit` | `test_the_guard_refuses[...]`, M10 | covered (m20) |
| same suite on LadybugDB with reopen proven | LadybugDB CHECK line; both reopen tests | covered |
| Neo4j parity recorded | `neo4j-parity.md` | root-owned |

### CK4: FAIL as written

| CRITERIA clause | Tests | Status |
| --- | --- | --- |
| every contract, purity, runtime and registry assertion has a negative and a positive fixture | `VIOLATIONS` table and its completeness test | shape right; purity guard wrong (B3), runtime assertions unbuildable (B4), capture and probe assertions missing (M12, M13) |
| `hippo connector new` writes a package whose `validate` passes | `test_a_new_package_passes_validate` | fails as planned (M16, B4) |
| `probe`, `list`, `sync --dry-run` run against the fixture connector | `test_probe_prints_family_and_mapping_per_partition`, `test_list_shows_built_in_in_repo_and_entry_point_connectors`, `test_sync_dry_run_prints_coverage_…` | `sync --dry-run` fails (B4); `list` needs the loader (M2) |
| `remote.py` forwards the commands (R7: `list` only) | `test_list_forwards_to_the_running_server_when_the_store_is_locked`, `test_remote_connectors_maps_a_401_and_a_coded_refusal` | covered |
| `docs/spec/cdk-guide.md` exists and its examples are the fixture connector | `test_the_guide_exists_and_every_python_example_is_the_fixture_connector` | covered |

### CK5: FAIL as written; PASS after B1, M12

| CRITERIA clause | Tests | Status |
| --- | --- | --- |
| `add_text`, `add_upload` (ZIP) and `add_repo` dispatch through `LocalConnector`/`GitConnector` and `connectors/lanes.py` | `test_add_text_and_a_prose_upload_dispatch_through_the_prose_lane`, `test_add_repo_and_code_uploads_dispatch_through_the_code_lane[repo\|archive\|file]` | covered |
| the kit's capture-side assertions pass on both connectors (R1) | none | **not covered** (M12) |
| checksums, spans, passages, native rows, receipts, coverage equal on the same fixture; configuration unchanged; only `registry_fingerprint` differs | the `*_is_byte_identical_*` tests, `test_registry_fingerprint_is_the_only_generation_field_that_differs` | asserted; cannot pass as written (B1) |
| CD1 and CD2 CHECK lines verbatim | S5b runs them | covered |
| LadybugDB acceptance at the recorded size | R4: CD9 at N=8 through the coordinator, runtime parity at N=2 | covered by ruling |

### CK6: FAIL as written; PASS after B3 (in S4) and M15

| CRITERIA clause | Tests | Status |
| --- | --- | --- |
| imports only `hippo.connectors` public modules and the knowledge model | `test_the_exemplar_imports_only_the_public_kit_and_the_knowledge_model` | covered (M15 needs a re-export) |
| registers a new kind with a fact template and a new predicate with an owner family | `test_the_extension_registers_a_new_kind_with_fact_templates_…` | covered (m8) |
| `hippo connector validate` passes | `test_validate_passes_the_exemplar_and_reports_its_registry_diff` | covered once B4 and M16 land |
| a fixture syncs into a scratch workspace | `test_a_fixture_syncs_into_a_scratch_workspace_and_publishes_one_generation` | covered |
| a query returns its rendered facts with citations resolving to its spans | `test_search_returns_the_rendered_fact_of_the_incident`, `test_every_citation_of_the_rendered_fact_resolves_to_the_record_span` | covered |
| probe and validate results visible through Task 15 routes and the MCP tool | `test_connector_surfaces.py` | validate fails as written (B3) |

---

## Invariants (question 2)

| Invariant | Verdict | Evidence |
| --- | --- | --- |
| Existing row identities stay stable (S1) | Holds | Every new field sits outside `identity_fields` (D18, D21, D22; `knowledge/model.py:368-375`, `:420`, `:554-566`). Built-in canonical locator JSON is pinned against the union adapter, and a span id literal is pinned. `generation_checksums` drops unset v8 fields (D19), so v7 seals verify. |
| Every value that is a `Literal` today stays valid (S1) | Holds | Built-ins are the thirty `OBJECT_KINDS`, twelve artifact kinds, eight connector kinds and seven locator kinds (`predicates.py:12-45`, `model.py:280`, `:294-307`, `:414`), pinned by test 1. |
| Refused at registration and unreachable at `emit` (S1, S2) | Holds, with m4 | S1's refusal table and D7's proxy; S2 §8.1 step 2 refuses unregistered or undeclared names at bind. |
| No connector path calls a model or the network inside `emit` (S2, S3, S4) | Holds for the runtime, with m20; broken in the kit by B3 | S3 §10.1 uses a per-thread guard. S2 is pure. Lane connectors have no `emit`: the coordinators' OpenIE and embedding calls run in the derivation half (R1, S5 §3.1 reason 4), outside connector methods. |
| The runtime never deletes the active generation (S3, S5) | Holds | S3 §5.10 never calls discard, collect or legacy cleanup, and M20 spies on those calls. S5 keeps the reviewed failure paths. |
| The runtime never deletes from a failed inventory (S3, S5) | Holds | S3 §6.4 has four conditions, pinned by M5 and M6. S5 lanes have no provider deletions. |
| The CD2 legacy-lane rule holds (S3, S5) | Holds by construction; no test (m16) | A connector Source gains an `Artifact` before any `Generation`, and `context.legacy_lane` then takes it out of the legacy lane (`context.py:54-84`). Once it has a generation, it serves only untagged rows, and it has none. S5 leaves `context.py` and `status.py` alone and reruns CD2. |
| `BuildAuthority` and the publication compare are reused, not re-implemented (S3) | Holds | `capture_build_authority`, `bind_inputs`, `rebaseline` (`knowledge/build_authority.py:378-465`); `publish_staged_generation` (`store/generations.py:1269`); S3b widens `_inventory` (`:248-293`) for `kind="connector"` only. |
| S5's byte-identity proof compares what the store checksums | Holds, but blocked by B1 | S5 §6 compares `generation_checksums` and every record it walks (`generations.py:966-1044`), native rows and relationships, the `Generation` row without the fingerprint (unhashed: `visit` skips `Generation` at `:982`), manifests, events and receipts. |
| Unknown policy is deny everywhere | Holds except R30 (M9) | S2 `policy_record` stores `mode="unknown"`. Readers are denied (`knowledge/access.py:460`); the open audience is not internal (`src/hippo/access.py:105`, `:120`). S3's authority admits unknown only for the build, as a trusted-local actor. |

---

## QUALITY verdict: NEEDS CHANGES

- **Layering.** Every new module keeps `knowledge` off `connectors`, and S2's
  `test_knowledge_package_never_imports_connectors` pins that. S3b's `staged_records`,
  `generation_profiles` and `build_authority` take knowledge records only. No plan grows
  `tests/unit/test_layering.py` `ALLOWED`. Three problems remain: R31's built-in verifiers (M10), S5's
  `ingest` → `connectors` edge (M11), and private cross-module imports (m10).
- **Import-order list.** `tests/unit/test_import_order.py` `MODULES` gains entries from S4a, S5a and S5b
  (R9), but none from S3 (m12). S4 keeps every `hippo.connectors` import in `cli.py` function-local, so
  `HELP_MUST_NOT_IMPORT` holds.
- **Duplication.** S3 imports `staged_code`'s fenced core and moves five helpers into `build_run.py`
  rather than copying them. S2 re-spells `input_binding._view`'s projection shape. It cannot reuse
  `BoundPassage`, which needs a `PreparedChunk` (S2 §2), and a test pins the shape. S4's offline model
  copies the fake's algorithm (m17).
- **Error surfaces.** `knowledge/public_errors.py` cannot list `connectors` classes, so connector
  refusals reach S6's routes as `operation_failed` (m11).
- **Determinism.** Binding is pure, derivation groups are hashed from sorted span ids, the only clock is
  the store clock (R27), and goldens exclude rows that carry uuids. Sound.
- **Test honesty.** M3 asserts a replay no-op that the specified behaviour cannot deliver. See also m5,
  m13, m21 and m22.
- **Sizing.** S1a/S1b, S2a/S2b and S3a/S3b/S3c are one worker each, with named fallback splits. S5b
  carries the CD9 run by design. S4a is already at CC6 size and cannot absorb the loader, hence M2's
  S4c.

---

## Cross-plan consistency (question 4)

| Consumer requires | Provider's contract | Agree |
| --- | --- | --- |
| S2 R1: `Registry`, `REGISTRY`, `current_registry`, `use_registry`, `extension_scope`, the definition classes, `CUSTOM_FAMILY`, `RESERVED_TEMPLATE_FIELDS`, `RegistrationError`, `UnregisteredName`, `connector_configuration` | S1 §5.2 module listing | yes |
| S2 R2 `Registry.frozen`; R3 `UnregisteredName(KeyError)` | S1 §5.2 | yes |
| S2 R4 `FactTemplate(name, version, consumes, text)` | S1 §5.2 | yes |
| S2 R5 `declared_template_versions(kinds)`, `connector_configuration(*, name, version, templates, parsers)` | S1 D25, §5.2 | yes |
| S2 R6 D13 key templates with `instance`, `provider_instance`, `catalog_instance` | S1 §5.3 table | yes |
| S2 R7 subject first by `(canonical_key, kind)` | S1 D12, §5.4 item 4 | yes |
| S2 R9 six `AssertionVersion` fields and `kit_provenance` rules | S1 §6.1 | yes |
| S2 R10 `Unit` (`embed_text == prefix + text`, `template` as `name@version`) | S1 §6.1, D15 | yes |
| S2 R12 `extension_scope()` extends in place | S1 §5.2: one bullet in place, one a new registry | no (m1); R16 settles it |
| S3 RS1-1 to RS1-6 | S1 §5.2, D16, D18, D21, D22 | yes |
| S3 calls `capture_records(fetch, policy, *, connector, workspace_id, source_id, raw_uri, observed_at, policy_expires_at)`, `policy_record(policy, *, connector, workspace_id, observed_at, expires_at)`, `bind_batch(BindContext(...), revision, batch)`, `merge_bound` | S2 §4.5 | yes |
| S3 `BINDER_VERSION`, `RENDER_RULE_VERSION`, `KEY_RULE_VERSION`, `CLASSIFIER_VERSION`; `RevisionInput(partition, artifact, revision, data, config, mapping, registry)` | S2 §4.1–§4.5 | yes |
| S3 `BoundBatch` fields into `RecordBundle`; `BoundPassageRow.native_row()` without `embedding` | S2 §4.5, §8.7, §13 | yes |
| S3's emit pool under the caller's registry | S1 §10 (`copy_context`) | no (m20) |
| S4 R-S1-1 `Registry.load()` | S1 deviation 9 declines; R15 gives it to S4 | unresolved (M2) |
| S4 R-S1-2 `FactTemplate` name, version, consumes | S1 §5.2 | yes |
| S4 R-S2-1 `base.py` records, `Family`, `Clock`, `RegistrationRequired` | S2 §4.1 | yes |
| S4 R-S2-2 to R-S2-7: `check_key_parts`, `canonical_key`, `render_facts`, `unit_text`, `verify_span`, `token_count`, `policy_record`, `check_direction_and_ownership` | S2 §13 | yes |
| S4 `TOKEN_BOUND = 1500` | S2 `PASSAGE_CHAR_BOUND` (R24: 6000) | no (m6) |
| S4 R-S2-8 re-exports | S2 decision 40 | yes |
| S4 R-S3-1 `sync_partition(..., clock, ...) -> generation id` | S3 `sync_connector(..., options, raw_store, embedding_spec, operation_id, should_stop, ...) -> SyncReceipt`; no clock (R27); needs a stored classification | no (B4) |
| S4 R-S3-2 failpoint names | S3 `FAULT_POINTS` and the §9 scenario table | no (B4) |
| S4 R-S3-3 transport injection, six classes | S3 §10.2 | yes |
| S4 R-S3-4 `credentials.redact_url`, `credentials.resolve` | S3 §4.2 | yes |
| S4 R-S3-5 one guard | S3 `guard.forbid_effects`; S4 plans its own | no (B3) |
| S4 R-S3-6 fixture path | S3 §11, R10 | yes |
| S4 R-S3-7 Connector and Source rows, `ctx.ollama` | S3 `ensure_connector`, `connector_source` | yes; `sync_connector` cannot name the row (B4) |
| S4 `record_transport`/`replay_transport` | S3 §10.2 (`ProviderMalformedError`) against S4 §3.1 (`ContractViolation`) | no (B4) |
| S5 R-S1-1 `Generation.registry_fingerprint`, optional | S1 D21 (64-hex pattern, default `None`) | yes |
| S5 R-S1-2 `default_registry()`, built-ins plus in-repo packages | S1 `current_registry()`; in-repo packages need the loader | no (m9, M2) |
| S5 R-S1-3 built-ins cover every kind the lanes write | S1 §5.3 | yes |
| S5 R-S2-1 an emit-less connector | S2 `SyncConnector`, `derivation="coordinator_lane"` | yes; S5 types `Connector` and omits `derivation` (m9) |
| S5 R-S2-2 to R-S2-4 | S2 §4.1, §5, §1 | yes |
| S5 R-S3 none; the `sync.py` re-export (R3) | S3 §15 | yes |
| R25's connector branch in `run_managed_build` | S5 §5 | not planned (M14) |
| S6 R-S1-1 `incident` a family, not a kind | S1 §5.3, R13 | yes |
| S6 R-S1-2 `FactTemplate(name, version, text)` | S1 requires `consumes` | no (m8) |
| S6 R-S1-3 discovery without registration | S1 declines; loader unplanned | no (M2) |
| S6 R-S2-1, R-S2-2 re-exports and records | S2 §4.1 | yes; `ParserVersion` used as a string (m8) |
| S6 R-S2-3 `service` key from `(tool_instance, service)` | S2 fills `catalog_instance` from the connector and refuses it in `NodeRef` | no (M6) |
| S6 R-S2-4 to R-S2-6 | S2 §8.4, §7, §8.7 | yes |
| S6 R-S3-1 to R-S3-4 | S3 §13 | yes |
| S6 R-S3-5 deletion from a completed inventory | S3 §6.4 needs `inventory=True` and `ProviderNotFoundError` | no (M15) |
| S6 R-S4-1 `new --dest`, `validate_package(runtime=False)`, `to_json`, `offline_ollama`, `assert_emit_pure`, `ConnectorSummary` | S4 §3 | names yes; behaviour blocked by B3, M16 |

---

## Design section 14 open decisions (question 5)

| Decision | Did a plan silently assume an answer? |
| --- | --- |
| 1. The stack | **No.** S3 DV4 embeds passages through `ctx.ollama`, and R6 sends rendered facts through today's passage retrieval; both are stated as interim and ratified (R37, R6). S5 keeps OpenIE running inside the prose lane (S5 §3.1 reason 4), which is existing behaviour, not a new choice. R17's content-hash index anticipates spec §7.2 without choosing a stack. |
| 2. Connector isolation | **Partly.** R36 states in-process for v1 and leaves the decision open. S4 §3.1's process-wide guard silently assumes `emit` never runs beside anything else in the process, which in-process serving contradicts (B3). |
| 3. Third-party trust | **Yes, in S3.** `ensure_connector(enabled=True)` and the absence of any enabled or allowlist check at sync entry answer "trusted" (M5). S6 decision 13 ("discovered but not registered until enabled") matches design §9's default, but the loader that would enforce it is unplanned (M2). |

---

## Rulings (question 6)

| Ruling | Contradicts the design, spec §3 or an invariant? |
| --- | --- |
| R1 lanes | No; design §11 permits wrapping. Its condition names assertions no plan defines (M12). |
| R2 ownership | No. |
| R3 `sync.py` re-export | No. |
| R4 LadybugDB at the recorded size | No; CD9's recorded size is N=8. |
| R5 no local/git `Connector` rows | No; it leaves the non-dry-run `sync` without a row (m19). |
| R6 derived passages; identity-only endpoints | No for passages. Its claim that identity-only endpoints give cross-domain edges their endpoints fails for built-in kinds keyed by instance (M6). |
| R7 S4 deviations | No. |
| R8 S6 narrowings | No; the validate route inherits B3. |
| R9 grants | No; misses S3's import-order entries (m12) and S5's layering pin (M11). |
| R10 fixture location | No. |
| R11, R26 one counter in `base.py` | No. |
| R12 `classification_json` | No. |
| R13 no built-in `incident` kind | No. |
| R14 tool name | No. |
| R15 loader in S4 | Not a contradiction, but it creates unplanned work (M2) and does not address readers outside `hippo serve` (M1). |
| R16 one current registry | No; thread-pool context (m20). |
| R17 `Unit` indexes on LadybugDB and Neo4j | Impossible on LadybugDB 0.15.3 (`store/migrations.py:518-525`) (m2). |
| R18 two identities for one table | No. |
| R19 multi-owner built-ins | Checked against spec §6: two gaps (m14). |
| R20 unversioned render text | No; the fingerprint covers it and the connector version covers configuration. |
| R21 write classification on change | No. |
| R22 code-point order | No. |
| R23 S1 deviations | No; each is justified by CK5 identity or the v7 checksum. |
| R24 6,000-character bound | Contradicts spec §3's 1,500-token upper bound for code and CJK text (m6). |
| R25 route `kind="connector"` to `sync_connector` | Contradicts S3's trusted-local rule; not planned (M14). |
| R27 the store clock | No. |
| R28 public key helpers | No. |
| R29 derivation table as registry data | Contradicts design §3 `TypeExtension.evidence_sources` and breaks S1's fixture; its no-refusal claim is false (M8). |
| R30 principal map | Fails open on deny lists (M9). |
| R31 locator verifier | Contradicts the layering rule; names a nonexistent kind (M10). |
| R32 extension registered | Unimplementable as stated (m7). |
| R33 reconcile interval | No. |
| R34 policy changes | Verified against S3 §6.3 and `knowledge/access.py:514`, `:529`; defeated by the span re-bind (B2). |
| R35 `ensure_connector` and the epoch | No. |
| R36 in-process `emit` | No. |
| R37 deviations | No. |
| R38 splits and order | No. The loader (M2) must merge before any caller of `load_registry`. |

---

## Briefs at `bd6ee9a`

The orchestrator committed three implementer briefs during this review. Each names rulings this
review finds against, and none carries a review finding yet. Before spawning, amend each brief, or name
the finding IDs in the spawn message as each brief allows:

| Brief | Conflicts with | What the brief says, and what must change |
| --- | --- | --- |
| `cdk-s1a.md` | M1, M8, m14; add m5, m22 | It implements D8's registry-backed validators, which run on every read, before M1 is decided. It binds R29, whose refusal rejects the plan's own shared fixture `incident_extension()` (`pager_feed`), so tell the worker to use built-in `metadata`, or amend R29 first. It binds R19's table as planned (m14). Its R31 line ("register built-ins without one") already matches M10's fix. Its R16 line settles m1. |
| `cdk-s1b.md` | B1, m2 | Its do-not-touch list names `knowledge/prose_preparation.py` and `staged_code.py`, the two files B1's fix edits. Grant `prose_preparation.py:164-174` and `staged_code.py:310` with the two tests. Its R17 line asks for `Unit` indexes on LadybugDB, whose 0.15.3 parser has no index DDL (`store/migrations.py:518-525`); make it Neo4j only. |
| `cdk-s2a.md` | B2, M6, M10, M9, m6; add m21 | `base.py` is S2a's, so `RevisionInput.span_policy_id` (B2) and `NodeRef.instance` (M6) land here. Its R31 line ("supply byte verifiers for the built-in line and byte-range locator kinds through the `verifier` attribute S1a added") cannot be done: S1a registers built-ins without a verifier in `knowledge`, the registry is frozen, "byte-range" names no built-in kind, and the `file_lines` verifier needs `ingest.provenance._lines`. Leave verifiers in S2b's `emit.py` table (M10). Its R30 line (`principal_map`) needs M9's deny-list rule. Its R24 line needs m6's interpolated message. |

## Per-plan verdicts

- **S1 (registry, schema v8): APPROVED WITH CHANGES.** Amend m1, m2 (with R17), m5 and m22. Take B1's
  two edits into S1b. Record M1's decision before S1a spawns, because it changes where D8's validators
  run. Swap the fixture's `pager_feed` (M8).
- **S2 (contract, classify, keys, render, emit): APPROVED WITH CHANGES.** Amend B2 (`span_policy_id`),
  M6 (foreign instance), M7 (`observed_at`), m4 and m21. Keep the pair refusal against R29 (M8), keep
  built-in verifiers against R31 (M10), and apply the R30 map in `policy_record` (M9).
- **S3 (runtime): APPROVED WITH CHANGES.** Amend B2 (capture records the span policy; add M8b), B4's
  `connector_id`, M3, M4, M5, m10, m12, m13, m15, m16 and m20.
- **S4 (kit, scaffold, commands): REJECTED.** Re-plan §3.1: the guard (B3), `run_case` and the runtime
  scenarios (B4), and the capture and probe assertions (M12, M13). Fix the scaffold key (M16) and add
  S4c's loader (M2). Then re-review §3.1 only. §3.2–§3.4, the commands table and the guide stand, apart
  from m6, m17, m18 and m19.
- **S5 (port): APPROVED WITH CHANGES.** B1's fix lands in S1b first. Amend M11, M12's lane tests, M14's
  refusal branch and m9.
- **S6 (exemplar, surfaces): APPROVED WITH CHANGES.** Depends on S4's B3 fix. Amend M6's
  `catalog_instance`, M15, m8 and m11.

---

## Anchor verification

Opened at `aeafd6b` and matching the plans to within two lines:

- `knowledge/model.py`: `:40-48`, `:55-87`, `:101-112`, `:168-252`, `:278-326`, `:357-445`, `:448-573`,
  `:640-719`, `:1490`
- `knowledge/predicates.py`, whole file
- `knowledge/identity.py`: function heads at `:40`–`:305`
- `knowledge/lifecycle.py:15-95`
- `knowledge/access.py:448-532`
- `knowledge/query_access.py:78-95`
- `knowledge/dense.py:180-200`
- `knowledge/projection.py:64-70`, `:645-660`, `:958-972`
- `knowledge/answer_evidence.py:1-30`
- `knowledge/code_binding.py:98-106`, `:415-432`, `:805-892`, `:1030-1062`
- `knowledge/code_history.py:938-962`, `:1010-1030`, `:1210-1222`
- `knowledge/build_authority.py`: heads, and `:248-295`
- `knowledge/generation_profiles.py`: heads, and `:255-280`
- `knowledge/prose_preparation.py:160-180`
- `knowledge/staged_code.py`: heads, `:254-255`, `:294-316`
- `knowledge/staged_prose.py:28-48`
- `knowledge/public_errors.py:20-30`, `:110-145`
- `knowledge/derivations.py:20-55`
- `knowledge/input_binding.py:1-40`
- `store/migrations.py:15-20`, `:80-148`, `:195-240`, `:490-540`, `:580-695`
- `store/knowledge.py:70-82`, `:150-172`, `:220-250`, `:417-440`, `:500-520`, `:756-825`, `:920-942`
- `store/generations.py`: method heads, `:520-690`, `:978-995`, `:1020-1095`, `:1125-1135`,
  `:1410-1430`, `:1475-1550`
- `store/snapshots.py`: heads, and `:290-310`
- `store/authorization.py:110-200`
- `ingest/readers.py:128-200`
- `ingest/provenance.py:285-300`
- `ingest/build_run.py`: heads
- `ingest/code_generation.py`: heads, `:490-520`, `:554-587`, `:965-980`
- `ingest/prose_generation.py`: heads
- `ingest/managed_activation.py`: heads, `:125-156`, `:624-676`
- `ingest/pipeline.py` and `ingest/chunker.py`: heads
- `context.py:54-84`
- `access.py:38-50`, `:105`, `:120`
- `cli.py`: heads, and `:255-270`
- `remote.py`: heads
- `web/app.py:61-103`
- `web/auth.py:210`
- `web/render.py:117`, `:129`
- `web/routes/code.py:60`
- `mcp_server.py:6`, `:179`, `:229-230`
- `knowledge/citations.py:97`
- `tests/unit/test_import_order.py`, whole file
- `tests/unit/test_layering.py`, whole file
- `tests/unit/test_mcp_server.py:10`, `:20-30`

Not opened:

- test-file line anchors other than the three files above;
- `docs/MCP.md`, `README.md`, `docs/CONTRACTS.md`;
- `codegraph/*`, `ollama.py`, `pyproject.toml`, `.github/workflows/ci.yml`.
