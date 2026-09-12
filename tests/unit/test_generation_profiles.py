"""Controlled local profile metadata binds exactly the accepted immutable inputs."""

import importlib
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from hippo.ingest.accepted_inputs import ByteInput, CaptureLimits, capture_raw_inputs
from hippo.knowledge import model as k
from hippo.knowledge.embedding_profile import EmbeddingSpec, StoredEmbeddingProfile
from hippo.knowledge.identity import canonical_json, text_hash
from hippo.knowledge.lifecycle import generation_for_inputs, generation_passage_id
from hippo.knowledge.raw_artifacts import RawArtifactStore
from tests.unit.test_generation_store import NOW, authority, claim, generation, publish


def api():
    try:
        return importlib.import_module("hippo.knowledge.generation_profiles")
    except ModuleNotFoundError:
        pytest.fail("Generation profile binding is missing")


def descriptor(digest="a" * 64, dimension=2):
    spec = EmbeddingSpec(query_prefix="Q: ", document_prefix="D: ")
    profile = spec.make_profile("embed", digest, dimension)
    fingerprint = text_hash(canonical_json({"profile_schema": 1, "profile": asdict(profile)}))
    return StoredEmbeddingProfile(profile, spec, fingerprint).descriptor()


def prepared(store, tmp_path, *, fault=None, empty=False, digest="a" * 64, existing=None):
    api()
    source = existing.gen.source_id if existing else store.create_source("text", "Managed")
    workspace = store.get_source(source)["workspace_id"]
    config = {"embedding_profile": descriptor(digest), "prose": {"chunker": "v1"}}
    raw = RawArtifactStore(tmp_path / digest, max_object_bytes=20000)
    accepted = capture_raw_inputs(
        raw,
        source_id=source,
        workspace_id=workspace,
        inputs=[] if empty else [ByteInput("a.txt", b"Original evidence")],
        configuration=config,
        limits=CaptureLimits(1000, 2000, 10, 10000),
    )
    policy = k.AccessPolicy(
        workspace_id=workspace, origin="local_curated", scope_key=source, mode="workspace", verified_at=NOW
    )
    store.put_knowledge(policy)
    originals = []
    for item in accepted.inputs:
        artifact = k.Artifact(
            workspace_id=workspace,
            source_id=source,
            kind="file",
            external_id=item.logical_path,
            canonical_uri=f"source:{source}/{item.logical_path}",
            policy_id=policy.id,
        )
        revision = k.ArtifactRevision(
            artifact_id=artifact.id,
            provider_revision=item.provider_revision,
            content_hash=item.raw_hash,
            raw_uri=item.raw_uri,
            observed_at=NOW,
            lifecycle="active",
        )
        if existing:
            revision = store._knowledge_get("ArtifactRevision", revision.id)
        if fault == "original_hash":
            revision = revision.replace(content_hash="b" * 64, raw_uri="hippo-raw:sha256:" + "b" * 64)
        if fault == "original_uri":
            revision = revision.replace(raw_uri="file:/wrong")
        originals.append((artifact, revision))
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=source,
        kind="manifest" if fault != "manifest_kind" else "document",
        external_id="accepted-inputs-v1",
        canonical_uri=f"source:{source}/accepted-inputs-v1",
        policy_id=policy.id,
    )
    payload = json.loads(accepted.manifest_bytes)
    if fault == "unknown_key":
        payload["unexpected"] = True
    if fault == "bad_reason":
        payload["dispositions"][0]["reason"] = ["captured"]
    if fault == "descriptor":
        payload["configuration"]["embedding_profile"]["fingerprint"] = "f" * 64
    content_hash = text_hash(canonical_json(payload))
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        content_hash=content_hash,
        raw_uri="hippo-raw:sha256:" + content_hash,
        observed_at=NOW,
        lifecycle="active",
        metadata_json=canonical_json({"accepted_manifest_v1": payload}),
    )
    if fault == "manifest_uri":
        revision = revision.replace(raw_uri="file:/wrong")
    pairs = [*originals, (artifact, revision)]
    if fault == "extra":
        extra = originals[0][0].replace(external_id="extra.txt")
        extra_rev = originals[0][1].replace(artifact_id=extra.id)
        pairs.append((extra, extra_rev))
    if fault == "missing":
        pairs = [(artifact, revision)]
    gen = generation_for_inputs(
        pairs,
        workspace_id=workspace,
        source_id=source,
        parent_id=existing.gen.id if existing else None,
        parser_version="parser-v1",
        linker_version="link-v1",
        embedding_profile=config["embedding_profile"]["fingerprint"],
        configuration=config | ({"changed": True} if fault == "config" else {}),
        created_at=NOW,
    )
    store.put_knowledge(gen)
    store._generation_clock = lambda: NOW
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        for a, r in pairs:
            store.put_knowledge(a)
            store.put_knowledge(r)
            store.put_knowledge(k.GenerationMember(generation_id=gen.id, artifact_revision_id=r.id))
    return SimpleNamespace(
        gen=gen,
        job=job,
        manifest_revision=revision,
        originals=originals,
        config=config,
        profile=config["embedding_profile"],
        workspace=workspace,
        raw=raw,
    )


def bind(store, value, **kwargs):
    return store.bind_generation_embedding_profile(
        value.gen.id, value.manifest_revision.id, **(authority(value.job) | kwargs)
    )


def index_manifest(store, value, *, config_hash=None):
    return k.IndexManifest(
        generation_id=value.gen.id,
        profile_fingerprint=value.gen.embedding_profile,
        config_fingerprint=config_hash or text_hash(canonical_json(value.config)),
        required_representations=("evidence", "dense", "native"),
        checksums=store.generation_checksums(value.gen.id),
        ready=True,
    )


def test_bind_seal_publish_is_fenced_idempotent_and_only_changes_content_epoch(store, tmp_path):
    value = prepared(store, tmp_path)
    before = (store.content_epoch(), store.authorization_epoch(), store.suppression_epoch())
    result = bind(store, value)
    assert result.profile.fingerprint == value.gen.embedding_profile
    assert result.config_fingerprint == text_hash(canonical_json(value.config))
    assert set(vars(result)) == {"profile", "config_fingerprint"}
    assert (store.content_epoch(), store.authorization_epoch(), store.suppression_epoch()) == (
        before[0] + 1,
        *before[1:],
    )
    assert bind(store, value) == result
    assert store.content_epoch() == before[0] + 1
    stored = store._knowledge_get("Generation", value.gen.id)
    assert api().embedding_mode(stored) == "verified_v1"
    store.seal_generation(value.gen.id, index_manifest(store, value), **authority(value.job))
    publish(store, value.gen, value.job)
    assert store.validate_generation_seal(value.gen.id)
    with pytest.raises(ValueError):
        bind(store, value)


@pytest.mark.parametrize(
    "fault",
    [
        "original_hash",
        "original_uri",
        "manifest_kind",
        "manifest_uri",
        "unknown_key",
        "bad_reason",
        "descriptor",
        "extra",
        "missing",
        "config",
    ],
)
def test_binding_rejects_inconsistent_exact_inventory_and_configuration(store, tmp_path, fault):
    value = prepared(store, tmp_path, fault=fault)
    before = store.content_epoch()
    with pytest.raises(ValueError):
        bind(store, value)
    assert store.content_epoch() == before
    assert api().embedding_mode(store._knowledge_get("Generation", value.gen.id)) == "legacy_tag_v1"


@pytest.mark.parametrize(
    "coverage",
    [
        {"embedding_mode": "verified_v1"},
        {"embedding_mode": "verified_v1", "embedding_manifest_revision_id": "revision"},
        {"embedding_manifest_revision_id": "revision"},
        {"embedding_mode": "future"},
    ],
)
def test_generic_generation_cannot_preseed_verified_state(store, coverage):
    api()
    gen = generation(store)
    fresh = gen.replace(manifest_hash="other", coverage_json=canonical_json(coverage))
    with pytest.raises(ValueError):
        store.put_knowledge(fresh)


@pytest.mark.parametrize("credentials", [{"lease_owner": "other"}, {"fencing_token": 999}])
def test_binding_rejects_stale_lease_even_for_idempotent_retry(store, tmp_path, credentials):
    value = prepared(store, tmp_path)
    bind(store, value)
    before = store.content_epoch()
    with pytest.raises(ValueError):
        bind(store, value, **credentials)
    assert store.content_epoch() == before


@pytest.mark.parametrize("point", ["before_binding", "after_binding"])
def test_binding_fault_rolls_back_marker_and_epoch(store, tmp_path, point):
    value = prepared(store, tmp_path)
    before = store.content_epoch()

    def fail(at):
        if at == point:
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        bind(store, value, fault_hook=fail)
    assert store.content_epoch() == before
    assert api().embedding_mode(store._knowledge_get("Generation", value.gen.id)) == "legacy_tag_v1"


def test_artifact_presentation_and_policy_changes_do_not_invalidate_sealed_identity(store, tmp_path):
    value = prepared(store, tmp_path)
    bind(store, value)
    seal = index_manifest(store, value)
    store.seal_generation(value.gen.id, seal, **authority(value.job))
    publish(store, value.gen, value.job)
    before_authorization = store.authorization_epoch()
    policy = k.AccessPolicy(
        workspace_id=value.workspace,
        origin="local_curated",
        scope_key="other",
        mode="restricted",
        verified_at=NOW,
    )
    store.put_knowledge(policy)
    for artifact, _ in [
        *value.originals,
        (store._knowledge_get("Artifact", value.manifest_revision.artifact_id), value.manifest_revision),
    ]:
        store.update_knowledge(
            artifact.replace(canonical_uri="changed-presentation", policy_id=policy.id, deleted_at=NOW)
        )
    assert store.authorization_epoch() > before_authorization
    assert store.validate_generation_seal(value.gen.id) == seal
    assert (
        api()
        .validate_generation_profile(store, store._knowledge_get("Generation", value.gen.id))
        .profile.fingerprint
        == value.gen.embedding_profile
    )


def test_wrong_index_configuration_hash_cannot_seal(store, tmp_path):
    value = prepared(store, tmp_path)
    bind(store, value)
    with pytest.raises(ValueError):
        store.seal_generation(
            value.gen.id, index_manifest(store, value, config_hash="wrong"), **authority(value.job)
        )


@pytest.mark.parametrize("dimension", [2, 3])
def test_descriptor_dimension_controls_passage_seal(store, tmp_path, dimension):
    value = prepared(store, tmp_path)
    bind(store, value)
    artifact, revision = value.originals[0]
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="file_lines",
        locator_json='{"kind":"file_lines","path":"a.txt","start":1,"end":1}',
        text="Original evidence",
        policy_id=artifact.policy_id,
    )
    with store.generation_write(value.gen.id, **authority(value.job)):
        store.put_knowledge(span)
        store.put_knowledge(
            k.GenerationEvidenceMember(
                generation_id=value.gen.id, record_kind="EvidenceSpan", record_id=span.id
            )
        )
        store.add_passages(
            [
                dict(
                    id=generation_passage_id(value.gen.id, revision.id, span.id, 0),
                    source_id=value.gen.source_id,
                    generation_id=value.gen.id,
                    artifact_revision_id=revision.id,
                    span_id=span.id,
                    embedding_profile=value.gen.embedding_profile,
                    title="Original",
                    text=span.text,
                    ordinal=0,
                    embedding=[1.0] * dimension,
                )
            ]
        )
    if dimension == 2:
        store.seal_generation(value.gen.id, index_manifest(store, value), **authority(value.job))
    else:
        with pytest.raises(ValueError):
            index_manifest(store, value)


def test_empty_inventory_and_config_only_rebuild_reuse_original_revisions(store, tmp_path):
    empty = prepared(store, tmp_path / "empty", empty=True)
    bind(store, empty)
    store.seal_generation(empty.gen.id, index_manifest(store, empty), **authority(empty.job))
    value = prepared(store, tmp_path / "first")
    bind(store, value)
    store.seal_generation(value.gen.id, index_manifest(store, value), **authority(value.job))
    publish(store, value.gen, value.job)
    newer = prepared(store, tmp_path / "next", digest="b" * 64, existing=value)
    assert value.originals[0][1] == newer.originals[0][1]
    assert value.manifest_revision.id != newer.manifest_revision.id and value.gen.id != newer.gen.id
    bind(store, newer)


@pytest.mark.parametrize("coverage", [{}, {"embedding_mode": "legacy_tag_v1"}])
def test_digest_shaped_legacy_keeps_original_seal_checksums(store, coverage):
    api()
    gen = generation(store)
    before = store.generation_checksums(gen.id)
    changed = gen.replace(embedding_profile="a" * 64, coverage_json=canonical_json(coverage))
    store.put_knowledge(changed)
    assert api().embedding_mode(changed) == "legacy_tag_v1"
    assert store.generation_checksums(changed.id) == before


def test_binding_does_not_call_raw_storage_or_model_resolver(store, tmp_path, monkeypatch):
    value = prepared(store, tmp_path)
    from hippo.knowledge import embedding_profile

    def denied(*args, **kwargs):
        pytest.fail("Binding must perform local metadata validation only")

    monkeypatch.setattr(RawArtifactStore, "read_bytes", denied)
    monkeypatch.setattr(embedding_profile, "resolve_embedding_profile", denied)
    bind(store, value)


def test_generic_updates_cannot_remove_or_change_controlled_binding(store, tmp_path):
    value = prepared(store, tmp_path)
    bind(store, value)
    stored = store._knowledge_get("Generation", value.gen.id)
    for coverage in (
        {},
        {"embedding_mode": "legacy_tag_v1"},
        {"embedding_mode": "verified_v1", "embedding_manifest_revision_id": "other"},
    ):
        with pytest.raises(ValueError):
            store.update_knowledge(stored.replace(coverage_json=canonical_json(coverage)))
    assert api().embedding_mode(store._knowledge_get("Generation", value.gen.id)) == "verified_v1"
    with pytest.raises(ValueError):
        store.bind_generation_embedding_profile(
            value.gen.id, value.originals[0][1].id, **authority(value.job)
        )


def test_verified_and_previous_unmarked_seals_survive_ladybug_reopen(tmp_path):
    from hippo.store.ladybug import LadybugStore

    path = tmp_path / "profiles.lbug"
    store = LadybugStore(path)
    try:
        value = prepared(store, tmp_path / "raw")
        bind(store, value)
        store.seal_generation(value.gen.id, index_manifest(store, value), **authority(value.job))
        publish(store, value.gen, value.job)
        old = generation(store, "old-compatible")
        job = claim(store, old)
        checksums = tuple(
            k.RepresentationChecksum(kind=kind, checksum=text_hash("[]"), row_count=0, ready=True)
            for kind in ("evidence", "dense", "native")
        )
        old_manifest = k.IndexManifest(
            generation_id=old.id,
            profile_fingerprint=old.embedding_profile,
            config_fingerprint="old-opaque-config",
            required_representations=("evidence", "dense", "native"),
            checksums=checksums,
            ready=True,
        )
        store.seal_generation(old.id, old_manifest, **authority(job))
        publish(store, old, job)
    finally:
        store.close()
    reopened = LadybugStore(path)
    try:
        assert reopened.validate_generation_seal(value.gen.id)
        assert reopened.validate_generation_seal(old.id) == old_manifest
        profile = api().validate_generation_profile(
            reopened, reopened._knowledge_get("Generation", value.gen.id)
        )
        assert profile.profile.fingerprint == value.gen.embedding_profile
        assert api().embedding_mode(reopened._knowledge_get("Generation", old.id)) == "legacy_tag_v1"
    finally:
        reopened.close()


@pytest.mark.parametrize("pointer", [[], True, "", None])
def test_malformed_manifest_pointer_is_a_controlled_denial(store, tmp_path, pointer):
    value = prepared(store, tmp_path)
    before = store.content_epoch()
    with pytest.raises(ValueError):
        store.bind_generation_embedding_profile(value.gen.id, pointer, **authority(value.job))
    assert store.content_epoch() == before
