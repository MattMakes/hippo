"""One code generation is written in fenced dependency groups, resumed and sealed.

Gate CD7. A captured checkout becomes accepted inputs, a settled generation, a code
graph, mapped chunks, bound evidence and bound history; this suite then writes that
inventory through `knowledge/staged_code.py` under a live fence, probes a reclaimed
attempt against the store's own rows, and seals an `IndexManifest` with the evidence,
dense and native representations.

The fixtures follow plan section 6's order, because a code generation's native IDs are
namespaced by the generation while its identity never depends on the graph: capture,
settle, extract, walk the history, chunk, bind, merge, install, embed, write.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from hippo.codegraph.extract import extract_code
from hippo.codegraph.git_history import History
from hippo.codegraph.model import commit_id
from hippo.ingest.code_provenance import read_code_provenance
from hippo.ingest.prepared_code_chunks import CapturedCode, CodeChunkSettings, prepare_code_chunks
from hippo.ingest.repo_capture import capture_repository_inputs, repository_descriptor
from hippo.knowledge import code_binding, code_history, generation_profiles
from hippo.knowledge import model as k
from hippo.knowledge.embedding_profile import EmbeddingSpec, StoredEmbeddingProfile, _fingerprint
from hippo.knowledge.identity import canonical_json, text_hash
from hippo.knowledge.inputs import CaptureLimits
from hippo.knowledge.lifecycle import generation_namespace
from hippo.knowledge.raw_artifacts import RawArtifactStore

INSTANT = datetime(2030, 1, 1, tzinfo=UTC)
LEASE = timedelta(minutes=5)
CLONE_URL = "https://git.example.com/acme/robots.git"
HEAD = "4f1d2c8a9b7e6f5d4c3b2a1908f7e6d5c4b3a291"
AUTHOR = "Ada"
COMMITS = (
    ("a" * 40, "2026-01-01T10:00:00+00:00", "Add the order service"),
    ("b" * 40, "2026-01-02T18:45:00+05:30", "Adjust the schema"),
)

ORDERS = '''"""Order handling."""

import os


class OrderService:
    """Places orders, and keeps a long enough docstring to be worth extracting here."""

    def place(self, order):
        total = order.total
        return total


def helper(value):
    return value + 1
'''

SCHEMA = "CREATE TABLE orders (\n  id INT\n);\n\nSELECT id FROM orders;\n"
TREE = {"src/orders.py": ORDERS.encode(), "db/schema.sql": SCHEMA.encode()}


def writer():
    try:
        return importlib.import_module("hippo.knowledge.staged_code")
    except ModuleNotFoundError:
        pytest.fail("Staged code writer is missing")


# ------------------------------------------------------------------ fixture


def limits():
    return CaptureLimits(
        max_input_bytes=200_000, max_total_bytes=2_000_000, max_inputs=200, max_manifest_bytes=200_000
    )


def history_of(facts, namespace, source_id):
    """A `History` in exactly the shapes `read_history` returns, without running git."""
    touchable = [symbol for symbol in facts.symbols if symbol.kind != "module"]
    rows, modifies, kept = [], [], []
    for ordinal, (sha, date, message) in enumerate(COMMITS):
        node = commit_id(source_id, sha, node_namespace=namespace)
        rows.append(
            {
                "id": node,
                "source_id": source_id,
                "sha": sha,
                "author": AUTHOR,
                "date": date,
                "message": message,
                "ordinal": ordinal,
            }
        )
        modifies.append(
            {
                "commit_id": node,
                "symbol_id": touchable[ordinal % len(touchable)].id,
                "omega": 1.0,
                "hunk": {"file": "src/orders.py", "old_range": [1, 0], "new_range": [16, 8], "churn": 8},
            }
        )
        kept.append(node)
    return History(
        commits=rows, modifies=modifies, precedes=list(zip(kept, kept[1:], strict=False)), skipped=0
    )


def capture(store, tmp_path, *, kind="repo", files=None, observed_at=INSTANT, profile_name="code"):
    """Everything plan section 6 produces before the first write, in its order."""
    source_id = store.create_source(kind, "robots")
    workspace = store.get_source(source_id)["workspace_id"]
    policy = k.AccessPolicy(workspace_id=workspace, mode="workspace", verified_at=INSTANT)
    store.put_knowledge(policy)
    spec = EmbeddingSpec(document_prefix="doc:", query_prefix="query:", dimensions=2)
    profile = spec.make_profile("embed:latest", "a" * 64, 2)
    embedding = StoredEmbeddingProfile(profile, spec, _fingerprint(profile))
    root = tmp_path / "checkout"
    for name, data in (files if files is not None else TREE).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    configuration = {
        "embedding_profile": embedding.descriptor(),
        "walker": {"rules": "walker-v1"},
        code_history.HISTORY_CONFIGURATION_KEY: code_history.CODE_HISTORY_RULE_VERSION,
    }
    if profile_name is not None:
        configuration[generation_profiles.GENERATION_PROFILE_KEY] = profile_name
    folded = dict(configuration) | {
        code_binding.CODE_BINDING_CONFIGURATION_KEY: {
            "binding": code_binding.CODE_BINDING_RULE_VERSION,
            "chunker": code_binding.EXPECTED_CODE_CHUNK_RULE_VERSION,
        }
    }
    raw_store = RawArtifactStore(tmp_path / "raw", max_object_bytes=2_000_000)
    captured = capture_repository_inputs(
        root,
        raw_store=raw_store,
        source_id=source_id,
        workspace_id=workspace,
        limits=limits(),
        configuration=folded,
        observed_at=observed_at,
        provider_revision=HEAD if kind == "repo" else None,
        repository=repository_descriptor(CLONE_URL) if kind == "repo" else None,
    )
    # `capture_repository_inputs` adds its own reserved `capture` key, and
    # `CodeGenerationInputs.folded` adds the code derivation key, so the configuration the
    # manifest records is exactly the one generation identity hashes only when the identity
    # inputs carry the capture key and the capture call carries the derivation key.
    manifest_configuration = json.loads(captured.accepted.configuration_json)
    identity = code_binding.CodeGenerationInputs(
        parent_id=None,
        parser_version="managed-code-v1",
        linker_version="managed-code-linker-v1",
        embedding_profile=embedding.fingerprint,
        configuration={
            key: value
            for key, value in manifest_configuration.items()
            if key != code_binding.CODE_BINDING_CONFIGURATION_KEY
        },
        policy_id=policy.id,
    )
    generation = code_binding.code_generation(
        captured,
        workspace_id=workspace,
        source_id=source_id,
        generation_identity_inputs=identity,
        observed_at=observed_at,
    )
    namespace = generation_namespace(generation)
    units = [
        CapturedCode(
            raw, read_code_provenance(raw, raw_store.read_bytes(raw.raw_artifact), name=raw.logical_path)
        )
        for raw in captured.accepted.inputs
    ]
    facts = extract_code(
        [item.unit.to_document() for item in units if item.unit], source_id, node_namespace=namespace
    )
    walked = history_of(facts, namespace, source_id) if kind == "repo" else History()
    facts.commits, facts.modifies, facts.precedes = walked.commits, walked.modifies, walked.precedes
    chunks = prepare_code_chunks(
        units,
        facts=facts,
        settings=CodeChunkSettings(size_chars=1500, overlap_chars=150),
        max_chunks=20_000,
    )
    state = SimpleNamespace(**locals())
    state.bundle = bind_at(state, observed_at)
    return state


def bind_at(state, observed_at):
    """Bind and merge the captured tree at one capture instant (plan section 9).

    `Generation.identity_fields` excludes `created_at`, so the same inputs at two
    instants are one generation with two different observation inventories -- which is
    exactly what design review B4 says a resume must never produce.
    """
    generation = code_binding.code_generation(
        state.captured,
        workspace_id=state.workspace,
        source_id=state.source_id,
        generation_identity_inputs=state.identity,
        observed_at=observed_at,
    )
    evidence = code_binding.materialize_code_evidence(
        state.captured,
        state.chunks,
        state.facts,
        workspace_id=state.workspace,
        source_id=state.source_id,
        generation_identity_inputs=state.identity,
        observed_at=observed_at,
    )
    bound_history = code_history.bind_history(
        state.walked,
        code_bundle=evidence,
        repository=repository_descriptor(CLONE_URL) if state.kind == "repo" else None,
        workspace_id=state.workspace,
        source_id=state.source_id,
        generation_id=generation.id,
        generation_namespace=state.namespace,
        observed_at=observed_at,
        history_depth=25 if state.kind == "repo" else 0,
        shallow_boundary=(),
    )
    return code_history.merge_code_bundles(evidence, bound_history)


def prepare(state, *, vector=(1.0, 0.0)):
    """Join the merged bundle with its vectors and the graph's relations."""
    module = writer()
    edges, definitions = module.code_relations(state.bundle, state.facts)
    return module.PreparedCodeIndex(
        bundle=state.bundle,
        dense=tuple(module.PreparedCodePassage(item, vector) for item in state.bundle.passages),
        native=tuple(
            module.PreparedNativeRow(row, () if row.native_kind == "Commit" else vector)
            for row in state.bundle.native_rows
        ),
        edges=edges,
        definitions=definitions,
    )


def install(store, state, *, job_key="cc8", owner="worker", at=INSTANT):
    """Persist the generation and its accepted inventory, then bind the verified profile."""
    gen = state.bundle.generation
    store.put_knowledge(gen)
    store._generation_clock = lambda: at
    job = store.claim_generation_build(
        gen.id, job_key=job_key, lease_owner=owner, lease_expires_at=at + LEASE
    )
    credentials = dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)
    with store.generation_write(gen.id, **credentials):
        for artifact, revision in (*state.bundle.accepted_pairs, *state.bundle.history_pairs):
            store.put_knowledge(artifact)
            store.put_knowledge(revision)
        for member in state.bundle.revision_members:
            store.put_knowledge(member)
    store.bind_generation_embedding_profile(gen.id, state.bundle.manifest_revision.id, **credentials)
    return job, dict(
        **credentials,
        expected_authorization_epoch=store.authorization_epoch(),
        expected_suppression_epoch=store.suppression_epoch(),
    )


@pytest.fixture
def built(store, tmp_path):
    """A captured, installed code generation ready for its first staged write."""
    state = capture(store, tmp_path.resolve())
    prepared = prepare(state)
    job, credentials = install(store, state)
    return SimpleNamespace(state=state, prepared=prepared, job=job, credentials=credentials, store=store)


def write(built, *, check=None, **kwargs):
    def outside():
        assert not getattr(built.store, "_transaction_depth", 0)
        assert getattr(built.store, "_transaction", None) is None
        if check:
            check()

    return writer().write_staged_code(
        built.store, built.prepared, check=outside, **built.credentials, **kwargs
    )


def reclaim(built, *, key="cc8-resume", owner="resumed"):
    """Expire the holder and take the generation back without collecting its rows."""
    store, gen = built.store, built.prepared.generation
    later = INSTANT + timedelta(minutes=30)
    store._generation_clock = lambda: later
    job = store.reclaim_generation_build(
        gen.id,
        job_key=key,
        lease_owner=owner,
        lease_expires_at=later + LEASE,
        expected_manifest_hash=gen.manifest_hash,
    )
    built.job = job
    built.credentials = dict(
        job_id=job.id,
        lease_owner=job.lease_owner,
        fencing_token=job.fencing_token,
        expected_authorization_epoch=store.authorization_epoch(),
        expected_suppression_epoch=store.suppression_epoch(),
    )
    return job


def write_only(built, *, batch_size=4, stop_after=None):
    """Run the batch loop without sealing, so the generation stays reclaimable."""
    module = writer()
    for index, batch in enumerate(module._write_batches(built.prepared, batch_size=batch_size)):
        if stop_after is not None and index == stop_after:
            return
        module._write_batch(built.store, built.prepared, batch, **built.credentials)


def groups_of(prepared):
    return list(writer()._groups(prepared))


def native_rows(store, generation_id, kind="Passage"):
    return store._native_rows(kind, generation_id=generation_id)


# ------------------------------------------------------------------ module shape


def test_the_staged_code_writer_module_exists():
    from importlib.util import find_spec

    assert find_spec("hippo.knowledge.staged_code") is not None, "the staged code writer is missing"


def test_the_writer_reaches_no_model_clock_or_filesystem():
    text = Path(writer().__file__).read_text(encoding="utf-8")
    for forbidden in ("datetime.now", "utcnow", "time.time", "open(", "Path(", "embed_texts", "Ollama"):
        assert forbidden not in text, f"the staged writer must not reach for {forbidden}"


def test_the_writer_never_dereferences_a_history_event_raw_uri(built):
    """CC7 finding 4: `hippo-commit:<sha>` names a commit, not a stored raw object."""
    text = Path(writer().__file__).read_text(encoding="utf-8")
    assert "raw_uri" not in text
    assert all(
        revision.raw_uri.startswith(code_history.COMMIT_RAW_URI_SCHEME)
        for _, revision in built.state.bundle.history_pairs
    )


# ------------------------------------------------------------------ batch planning


def test_write_batches_is_pure_and_keeps_no_store_callback_or_model(built):
    first = [
        tuple(type(r).__name__ for r in batch)
        for batch in writer()._write_batches(built.prepared, batch_size=4)
    ]
    second = [
        tuple(type(r).__name__ for r in batch)
        for batch in writer()._write_batches(built.prepared, batch_size=4)
    ]
    assert first == second and first


@pytest.mark.parametrize("value", [0, -1, "4"])
def test_write_batches_refuses_an_invalid_batch_size(built, value):
    with pytest.raises(ValueError, match="prepared output and positive batch size"):
        list(writer()._write_batches(built.prepared, batch_size=value))


def test_write_batches_refuses_an_input_that_is_not_prepared_code(built):
    with pytest.raises(ValueError, match="prepared output and positive batch size"):
        list(writer()._write_batches(built.state.bundle, batch_size=4))


def test_every_group_is_dependency_complete_and_leaves_no_dangling_endpoint(built):
    """No batch may reference a record, native row or endpoint an earlier one did not write."""
    module = writer()
    written, natives, passages, bound = set(), set(), set(), set()
    for group in groups_of(built.prepared):
        produced = set()
        for record in group.records:
            if record is None:
                continue
            if type(record) is module.PreparedCodePassage:
                produced.add(("Passage", record.id))
                passages.add(record.id)
            elif type(record) is module.PreparedNativeRow:
                produced.add((record.native_kind, record.native_id))
                natives.add(record.native_id)
            elif type(record) is module._CodeEdge:
                assert set(record.endpoints) <= natives, "a CODE_EDGE precedes one of its endpoints"
            elif type(record) is module._Definition:
                assert record.node_id in natives and record.passage_id in passages
            elif type(record) is code_history.NativeModifies:
                assert {record.commit_id, record.symbol_id} <= natives
            elif type(record) is module._Precedes:
                assert {record.newer, record.older} <= natives
            else:
                produced.add((type(record).__name__, record.id))
                if type(record) is k.NativeBinding:
                    bound.add((record.native_kind, record.native_id))
                    assert (record.native_kind, record.native_id) in written | produced
                if type(record) is k.GenerationEvidenceMember:
                    assert (record.record_kind, record.record_id) in written | produced
                if type(record) is k.ObjectObservation:
                    assert ("KnowledgeObject", record.object_id) in written | produced
                    assert ("EvidenceSpan", record.span_id) in written | produced
                if type(record) is k.RetrievalView:
                    assert ("DerivedRecord", record.derived_record_id) in written | produced
        written |= produced
    assert bound == {(row.native_kind, row.native_id) for row in built.state.bundle.native_rows}
    assert natives == {identity for _, identity in bound}, "every native row is written with its binding"


def test_batch_size_coalesces_groups_without_reordering(built):
    module = writer()
    one = [record for batch in module._write_batches(built.prepared, batch_size=1) for record in batch]
    many = [record for batch in module._write_batches(built.prepared, batch_size=7) for record in batch]
    assert one == many
    assert len(list(module._write_batches(built.prepared, batch_size=1))) == len(groups_of(built.prepared))


# ------------------------------------------------------------------ prepared input


def test_the_prepared_index_refuses_a_dense_passage_without_a_vector(built):
    with pytest.raises(ValueError, match="requires a vector"):
        writer().PreparedCodePassage(built.state.bundle.passages[0], ())


def test_the_prepared_index_refuses_a_code_edge_whose_endpoint_has_no_native_row(built):
    module, prepared = writer(), built.prepared
    stray = module._CodeEdge(
        canonical_json(
            {
                "a": prepared.native[0].native_id,
                "b": "symbol-missing",
                "kind": "CONTAINS",
                "omega": 1.0,
                "provenance": "syntax",
                "extra": "",
            }
        )
    )
    with pytest.raises(ValueError, match="CODE_EDGE endpoint is outside"):
        replace(prepared, edges=(*prepared.edges, stray))


def test_the_prepared_index_refuses_a_definition_outside_this_generation(built):
    module, prepared = writer(), built.prepared
    with pytest.raises(ValueError, match="DEFINED_IN pair is outside"):
        replace(prepared, definitions=(*prepared.definitions, module._Definition("symbol-x", "passage-y")))


def test_the_prepared_index_refuses_dense_or_native_inventory_that_differs(built):
    prepared = built.prepared
    with pytest.raises(ValueError, match="Dense inventory differs"):
        replace(prepared, dense=prepared.dense[:-1])
    with pytest.raises(ValueError, match="Native inventory differs"):
        replace(prepared, native=prepared.native[:-1])


def test_code_relations_drops_an_edge_whose_endpoint_the_chunker_never_rendered(built):
    """CC6 finding 10: a whitespace-only symbol body gets no passage and no native row."""
    module, state = writer(), built.state
    bound = {row.native_id for row in state.bundle.native_rows}
    facts = state.facts
    unbound = SimpleNamespace(
        edges=[
            *facts.edges,
            SimpleNamespace(
                a=next(iter(bound)),
                b="symbol-never-rendered",
                kind="CONTAINS",
                omega=1.0,
                provenance="syntax",
                extra="",
            ),
        ]
    )
    edges, _ = module.code_relations(state.bundle, unbound)
    assert len(edges) == len(module.code_relations(state.bundle, facts)[0])
    assert all(set(edge.endpoints) <= bound for edge in edges)


def test_every_relation_kind_this_lane_writes_is_planned(built):
    kinds = {relation[0] for relation in built.prepared.relations}
    assert kinds == {"CODE_EDGE", "DEFINED_IN", "MODIFIES", "PRECEDES"}


# ------------------------------------------------------------------ writing and sealing


def test_the_writer_seals_the_three_representations_without_publishing(built):
    store, gen = built.store, built.prepared.generation
    before = {key: store.get_meta(key) for key in ("embed_model", "embedding_dim", "graph_version")}
    manifest = write(built, batch_size=3)
    assert manifest == store.validate_generation_seal(gen.id)
    assert {row.kind for row in manifest.checksums} == {"evidence", "dense", "native"}
    assert all(row.ready and row.row_count for row in manifest.checksums)
    assert store._generation(gen.id).status == "ready"
    assert store.get_source(gen.source_id).get("active_generation_id") is None
    assert len(native_rows(store, gen.id)) == len(built.prepared.dense)
    assert {key: store.get_meta(key) for key in before} == before
    assert not store.load_entities() and not store.load_facts()


def test_the_sealed_generation_holds_every_native_row_binding_and_relation(built):
    store, prepared = built.store, built.prepared
    write(built)
    gen_id = prepared.generation.id
    for kind in ("Symbol", "DataObject", "Commit"):
        expected = {row.native_id for row in prepared.native if row.native_kind == kind}
        assert {row["id"] for row in native_rows(store, gen_id, kind)} == expected
    bindings = store._knowledge_rows("NativeBinding", generation_id=gen_id)
    assert {b.id for b in bindings} == {b.id for b in prepared.bundle.bindings}
    relations = {
        (entry[0], entry[1], entry[2])
        for entry in store._native_relationships(generation_id=gen_id)
        if entry[0] != "shared"
    }
    assert relations == prepared.relations


def test_a_code_generation_validates_under_the_code_profile_at_query_time(built):
    write(built)
    gen = built.store._generation(built.prepared.generation.id)
    bound = generation_profiles.validate_generation_profile(built.store, gen)
    assert bound.profile.fingerprint == gen.embedding_profile
    assert bound.config_fingerprint == text_hash(built.prepared.bundle.configuration_json)


def test_a_code_generation_without_the_code_profile_key_cannot_bind_or_seal(store, tmp_path):
    state = capture(store, tmp_path.resolve(), profile_name=None)
    with pytest.raises(ValueError, match="Accepted original revision inventory differs"):
        install(store, state)


def test_an_unknown_profile_name_refuses(store, tmp_path):
    state = capture(store, tmp_path.resolve(), profile_name="repository")
    with pytest.raises(ValueError, match="Unknown accepted generation profile"):
        install(store, state)


def test_an_identical_replay_of_every_batch_is_idempotent(built):
    """The batch plan is a pure function of the prepared output, so replaying it writes nothing new.

    The seal itself cannot be replayed through the public wrapper: `generation_write`
    admits only a `staging` generation, and the first seal leaves it `ready`. Resuming a
    sealed attempt is `reclaim_generation_build`'s job, not the writer's.
    """
    module, store, prepared = writer(), built.store, built.prepared
    gen_id = prepared.generation.id
    kinds = ("Passage", "Symbol", "DataObject", "Commit")

    def snapshot():
        return {
            kind: sorted(
                (store._canonical_native(kind, row) for row in native_rows(store, gen_id, kind)),
                key=canonical_json,
            )
            for kind in kinds
        } | {
            "members": sorted(
                r.id for r in store._knowledge_rows("GenerationEvidenceMember", generation_id=gen_id)
            )
        }

    for _ in range(2):
        for batch in module._write_batches(prepared, batch_size=5):
            module._write_batch(store, prepared, batch, **built.credentials)
        if _ == 0:
            first = snapshot()
    assert snapshot() == first
    manifest = module._seal(store, prepared, **built.credentials)
    assert manifest == store.validate_generation_seal(gen_id)


def test_an_omitted_native_row_is_refused_by_its_own_binding(built, monkeypatch):
    """The group is complete in the store's view too: the binding dereferences the row."""
    monkeypatch.setattr(built.store, "add_symbols", lambda rows: None)
    with pytest.raises(ValueError, match="Missing Symbol reference"):
        write(built)
    assert built.store._generation(built.prepared.generation.id).status == "staging"


def test_an_omitted_dense_passage_prevents_the_seal(built, monkeypatch):
    monkeypatch.setattr(built.store, "add_passages", lambda rows: None)
    with pytest.raises(ValueError, match="inventory differs from prepared coverage"):
        write(built)
    assert built.store._generation(built.prepared.generation.id).status == "staging"


def test_an_extra_exact_member_is_not_silently_accepted_or_deleted(built):
    store, prepared = built.store, built.prepared
    span = prepared.bundle.spans[0]
    extra = span.replace(text="extra text", text_hash=text_hash("extra text"))
    with store.generation_write(prepared.generation.id, **_authority(built)):
        store.put_knowledge(extra)
        store.put_knowledge(
            k.GenerationEvidenceMember(
                generation_id=prepared.generation.id, record_kind="EvidenceSpan", record_id=extra.id
            )
        )
    with pytest.raises(ValueError, match="inventory differs"):
        write(built)
    assert store._generation(prepared.generation.id).status == "staging"


def _authority(built):
    return {key: built.credentials[key] for key in ("job_id", "lease_owner", "fencing_token")}


# ------------------------------------------------------------------ fence and epochs


@pytest.mark.parametrize("epoch", ["authorization", "suppression"])
def test_an_epoch_change_during_a_batch_rolls_it_back_and_never_seals(built, monkeypatch, epoch):
    store = built.store
    original = store.put_knowledge

    def revoke(record):
        from hippo.store.authorization import bump_epoch

        result = original(record)
        if type(record) is k.EvidenceSpan:
            bump_epoch(store, epoch + "_epoch")
        return result

    monkeypatch.setattr(store, "put_knowledge", revoke)
    with pytest.raises(Exception, match="epoch|Authorization|authorization|suppression"):
        write(built, batch_size=1)
    assert store._generation(built.prepared.generation.id).status == "staging"
    assert not native_rows(store, built.prepared.generation.id)


def test_a_lost_fence_prevents_every_further_write_and_the_seal(built):
    store, gen = built.store, built.prepared.generation
    calls = 0

    def expire():
        nonlocal calls
        calls += 1
        if calls == 4:
            store._generation_clock = lambda: INSTANT + timedelta(minutes=6)

    with pytest.raises(ValueError, match="lease|fence"):
        write(built, check=expire, batch_size=1)
    assert store._generation(gen.id).status == "staging"
    with pytest.raises(ValueError, match="lease|fence"):
        writer()._seal(store, built.prepared, **built.credentials)


def test_an_expired_lease_prevents_the_very_first_write(built):
    built.store._generation_clock = lambda: INSTANT + timedelta(minutes=6)
    with pytest.raises(ValueError, match="lease|fence"):
        write(built, batch_size=1)
    assert not native_rows(built.store, built.prepared.generation.id)


def test_the_wrapper_refuses_a_transaction_the_caller_owns(built):
    calls = []
    with built.store.transaction():
        with pytest.raises(ValueError, match="requires no outer transaction"):
            writer().write_staged_code(
                built.store, built.prepared, check=lambda: calls.append("called"), **built.credentials
            )
    assert calls == []


def test_the_local_core_is_callback_free_inside_an_existing_transaction(built):
    module = writer()
    with built.store.transaction():
        for batch in module._write_batches(built.prepared, batch_size=5):
            module._write_batch(built.store, built.prepared, batch, **built.credentials)
        manifest = module._seal(built.store, built.prepared, **built.credentials)
    assert manifest == built.store.validate_generation_seal(built.prepared.generation.id)


def test_the_writer_requires_a_controlled_verified_profile_before_any_mutation(store, tmp_path):
    state = capture(store, tmp_path.resolve())
    prepared = prepare(state)
    gen = state.bundle.generation
    store.put_knowledge(gen)
    store._generation_clock = lambda: INSTANT
    job = store.claim_generation_build(
        gen.id, job_key="cc8", lease_owner="worker", lease_expires_at=INSTANT + LEASE
    )
    credentials = dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)
    with store.generation_write(gen.id, **credentials):
        for artifact, revision in (*state.bundle.accepted_pairs, *state.bundle.history_pairs):
            store.put_knowledge(artifact)
            store.put_knowledge(revision)
        for member in state.bundle.revision_members:
            store.put_knowledge(member)
    with pytest.raises(ValueError, match="verified profile binding"):
        writer().write_staged_code(
            store,
            prepared,
            check=lambda: None,
            **credentials,
            expected_authorization_epoch=store.authorization_epoch(),
            expected_suppression_epoch=store.suppression_epoch(),
        )
    assert not native_rows(store, gen.id)


# ------------------------------------------------------------------ payload ceiling


def test_the_per_batch_payload_ceiling_refuses_before_the_transaction_opens(built, monkeypatch):
    module = writer()
    monkeypatch.setattr(module, "PAYLOAD_CEILING_BYTES", 64)
    with pytest.raises(ValueError, match="payload is .* bytes; the ceiling is 64"):
        write(built, batch_size=4)
    assert not native_rows(built.store, built.prepared.generation.id)
    assert not built.store._knowledge_rows(
        "GenerationEvidenceMember", generation_id=built.prepared.generation.id
    )


# ------------------------------------------------------------------ resume probe


def test_a_fresh_generation_probes_to_write_everything_but_its_installed_members(built):
    """The coordinator installs the accepted inventory and its members before it claims.

    So the writer's revision-member stage is already satisfied on a *fresh* build, and the
    probe says so. Recognising that is the same mechanism that recognises a resumed batch,
    which is why it is asserted exactly rather than waved at.
    """
    plan = writer().probe_staged_rows(built.store, built.prepared)
    members = len(built.prepared.bundle.revision_members)
    assert plan.skipped == frozenset(range(1, 1 + members))
    assert plan.group_count == len(groups_of(built.prepared))
    assert plan.generation_id == built.prepared.generation.id


def test_a_complete_generation_probes_to_skip_every_writable_group(built):
    write(built)
    plan = writer().probe_staged_rows(built.store, built.prepared)
    assert plan.skipped_groups == plan.group_count - 1  # the accepted preflight is never skipped
    assert list(writer()._write_batches(built.prepared, batch_size=4, resume=plan)) == [(None,)]


def test_a_crash_mid_build_resumes_the_same_generation_and_skips_what_it_wrote(built):
    store, prepared = built.store, built.prepared
    stop = []

    def crash():
        stop.append(1)
        if len(stop) == 40:
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        write(built, check=crash, batch_size=1)
    written = {
        member.record_id
        for member in store._knowledge_rows("GenerationEvidenceMember", generation_id=prepared.generation.id)
    }
    assert written, "the crash must land after at least one committed batch"
    reclaim(built)
    assert store._generation(prepared.generation.id).status == "staging"
    plan = writer().probe_staged_rows(store, prepared)
    members = len(prepared.bundle.revision_members)
    assert members < plan.skipped_groups < plan.group_count
    manifest = write(built, resume=plan)
    assert manifest == store.validate_generation_seal(prepared.generation.id)
    assert writer().probe_staged_rows(store, prepared).skipped_groups == plan.group_count - 1


def test_a_reclaimed_generation_keeps_its_capture_instant_and_every_observation_id(built):
    """Design review B4: a resumed build adopts the persisted instant, never a fresh one."""
    store, prepared = built.store, built.prepared
    write_only(built, batch_size=2)
    reclaim(built)
    assert store._generation(prepared.generation.id).created_at == INSTANT
    persisted = {
        member.record_id
        for member in store._knowledge_rows("GenerationEvidenceMember", generation_id=prepared.generation.id)
        if member.record_kind == "ObjectObservation"
    }
    assert persisted == {row.id for row in prepared.bundle.observations}


def test_a_resume_that_re_takes_the_capture_instant_fails_closed(built):
    """Design review B4: the same inputs at a fresh instant are the same generation.

    `Generation.identity_fields` excludes `created_at`, so a resume that takes a new
    instant keeps the generation ID but mints a whole new `ObjectObservation` inventory.
    Without the absence assertion that would be written as a silent duplicate set; with
    it the probe refuses and names the remediation.
    """
    store, state = built.store, built.state
    write_only(built, batch_size=2)
    reclaim(built)
    fresh = bind_at(state, INSTANT + timedelta(hours=1))
    assert fresh.generation.id == state.bundle.generation.id
    assert {row.id for row in fresh.observations} != {row.id for row in state.bundle.observations}
    stale = replace(
        built.prepared,
        bundle=fresh,
        dense=tuple(writer().PreparedCodePassage(item, (1.0, 0.0)) for item in fresh.passages),
        native=tuple(
            writer().PreparedNativeRow(row, () if row.native_kind == "Commit" else (1.0, 0.0))
            for row in fresh.native_rows
        ),
    )
    with pytest.raises(ValueError, match="this build would not produce; explicit failed-generation cleanup"):
        writer().probe_staged_rows(store, stale)


def test_an_extra_generation_scoped_row_fails_the_resume(built):
    store, prepared = built.store, built.prepared
    write_only(built, batch_size=2)
    reclaim(built)
    span = prepared.bundle.spans[0]
    orphan = span.replace(text="a different derivation", text_hash=text_hash("a different derivation"))
    with store.generation_write(prepared.generation.id, **_authority(built)):
        store.put_knowledge(orphan)
        store.put_knowledge(
            k.GenerationEvidenceMember(
                generation_id=prepared.generation.id, record_kind="EvidenceSpan", record_id=orphan.id
            )
        )
    with pytest.raises(ValueError, match="this build would not produce; explicit failed-generation cleanup"):
        writer().probe_staged_rows(store, prepared)


def test_a_partially_present_group_fails_the_resume(built):
    """A native row without its binding is half a dependency group and never a skip."""
    store, prepared = built.store, built.prepared
    module = writer()
    row = next(item for item in prepared.native if item.native_kind == "Symbol")
    module._write_batch(store, prepared, (None,), **built.credentials)
    with store.generation_write(prepared.generation.id, **_authority(built)):
        store.add_symbols([row.native_row()])
    reclaim(built)
    with pytest.raises(ValueError, match="incomplete; explicit failed-generation cleanup"):
        module.probe_staged_rows(store, prepared)


def test_a_conflicting_persisted_native_payload_fails_the_resume(built):
    store, prepared = built.store, built.prepared
    module = writer()
    row = next(item for item in prepared.native if item.native_kind == "Symbol")
    with store.generation_write(prepared.generation.id, **_authority(built)):
        store.add_symbols([{**row.native_row(), "doc": "a different docstring"}])
    reclaim(built)
    with pytest.raises(ValueError, match="Symbol row differs from this build; explicit failed"):
        module.probe_staged_rows(store, prepared)


def test_a_present_knowledge_payload_is_compared_and_not_taken_on_trust(built, monkeypatch):
    """The exact member being present is never enough; the record itself is re-read.

    `EvidenceSpan.identity_fields` is `(revision_id, locator_json, text_hash)`, so its
    `policy_id` can drift without changing the ID -- a re-pointed policy is exactly the
    payload difference a resume must not write over. `put_knowledge` would refuse to
    persist it, which is why the drift is injected at the read.
    """
    store, prepared = built.store, built.prepared
    write_only(built, batch_size=4)
    reclaim(built)
    span = prepared.bundle.spans[0]
    original = store._knowledge_get

    def altered(kind, identity):
        record = original(kind, identity)
        if kind == "EvidenceSpan" and identity == span.id:
            return record.replace(policy_id="policy-repointed")
        return record

    assert writer().probe_staged_rows(store, prepared).skipped_groups > 0
    monkeypatch.setattr(store, "_knowledge_get", altered)
    with pytest.raises(ValueError, match="EvidenceSpan payload differs from this build; explicit failed"):
        writer().probe_staged_rows(store, prepared)


def test_a_conflicting_native_payload_is_never_overwritten_by_a_write(built):
    store, prepared = built.store, built.prepared
    row = next(item for item in prepared.native if item.native_kind == "Symbol")
    with store.generation_write(prepared.generation.id, **_authority(built)):
        store.add_symbols([{**row.native_row(), "doc": "a different docstring"}])
    with pytest.raises(ValueError, match="Conflicting staged Symbol row|immutable"):
        write(built, batch_size=64)


def test_a_resume_plan_belongs_to_the_preparation_it_was_probed_against(built):
    module = writer()
    plan = module.probe_staged_rows(built.store, built.prepared)
    other = module.ResumePlan("generation-other", plan.group_count, frozenset())
    with pytest.raises(ValueError, match="belongs to the generation"):
        list(module._write_batches(built.prepared, batch_size=4, resume=other))
    with pytest.raises(ValueError, match="names a group the preparation does not have"):
        module.ResumePlan(built.prepared.generation.id, 2, frozenset({99}))


def test_the_probe_reads_only_generation_scoped_and_identified_rows(built, monkeypatch):
    """CC2's contract: no whole-table read may reach the probe."""
    store = built.store
    write(built, batch_size=4)
    unscoped = []
    original_rows, original_native = store._knowledge_rows, store._native_rows

    def rows(kind, **kwargs):
        if not kwargs.get("generation_id") and not kwargs.get("where"):
            unscoped.append(kind)
        return original_rows(kind, **kwargs)

    def native(kind, **kwargs):
        if not kwargs.get("generation_id") and kwargs.get("ids") is None:
            unscoped.append(kind)
        return original_native(kind, **kwargs)

    monkeypatch.setattr(store, "_knowledge_rows", rows)
    monkeypatch.setattr(store, "_native_rows", native)
    writer().probe_staged_rows(store, built.prepared)
    assert unscoped == []


# ------------------------------------------------------------------ other source kinds


def test_an_archive_capture_without_a_repository_still_writes_and_seals(store, tmp_path):
    state = capture(store, tmp_path.resolve(), kind="archive")
    built = SimpleNamespace(store=store, state=state, prepared=prepare(state))
    built.job, built.credentials = install(store, state)
    manifest = write(built, batch_size=4)
    assert manifest == store.validate_generation_seal(state.bundle.generation.id)
    assert not [row for row in state.bundle.native_rows if row.native_kind == "Commit"]


def test_a_sealed_code_generation_survives_close_and_reopen(tmp_path):
    from hippo.store.ladybug import LadybugStore

    path = tmp_path.resolve() / "code.lbug"
    store = LadybugStore(path)
    try:
        state = capture(store, tmp_path.resolve())
        built = SimpleNamespace(store=store, state=state, prepared=prepare(state))
        built.job, built.credentials = install(store, state)
        manifest = write(built, batch_size=4)
    finally:
        store.close()
    reopened = LadybugStore(path)
    try:
        gen_id = state.bundle.generation.id
        assert reopened.validate_generation_seal(gen_id) == manifest
        assert (
            generation_profiles.validate_generation_profile(
                reopened, reopened._generation(gen_id)
            ).profile.fingerprint
            == state.embedding.fingerprint
        )
        assert reopened.generation_checksums(gen_id) == manifest.checksums
        for kind in ("Symbol", "DataObject", "Commit"):
            assert reopened._native_rows(kind, generation_id=gen_id)
        assert writer().probe_staged_rows(reopened, built.prepared).skipped_groups
    finally:
        reopened.close()
