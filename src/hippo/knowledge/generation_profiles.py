"""Local identity validation for an accepted generation embedding profile.

This module performs no raw I/O or remote verification and grants no access.
Readers must select authorized evidence before inspecting a generation profile.
Only the safe descriptor/config fingerprint leaves this boundary; the accepted
manifest can contain hidden inventory and is not an audience fingerprint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields

from .embedding_profile import StoredEmbeddingProfile, validate_profile_descriptor
from .identity import canonical_json, make_identity, text_hash
from .input_binding import local_input_key
from .inputs import (
    MANIFEST_EXTERNAL_ID,
    AcceptedInputs,
    CaptureLimits,
    InputDisposition,
    RawInput,
)
from .lifecycle import generation_for_inputs
from .raw_artifacts import RawArtifact

# `MANIFEST_EXTERNAL_ID` belongs to the accepted-input contract now, and importing
# it here keeps this module's existing import path working for its callers.

PROFILE_POINTER = "embedding_manifest_revision_id"


@dataclass(frozen=True)
class GenerationProfile:
    profile: StoredEmbeddingProfile
    config_fingerprint: str


def embedding_mode(generation) -> str:
    coverage = json.loads(generation.coverage_json)
    if type(coverage) is not dict:
        raise ValueError("Generation profile coverage must be an object")
    mode = coverage.get("embedding_mode", "legacy_tag_v1")
    if mode not in ("legacy_tag_v1", "verified_v1"):
        raise ValueError("Unknown generation embedding mode")
    if mode == "verified_v1":
        pointer = coverage.get(PROFILE_POINTER)
        if type(pointer) is not str or not pointer:
            raise ValueError("Verified generation requires an accepted manifest binding")
    elif PROFILE_POINTER in coverage:
        raise ValueError("Legacy generation cannot carry a verified manifest pointer")
    return mode


def _closed(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("Accepted manifest has missing or unknown fields")
    return value


def _accepted(payload, revision) -> AcceptedInputs:
    _closed(
        payload, ("version", "source_id", "workspace_id", "inputs", "dispositions", "configuration", "limits")
    )
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("Unsupported accepted manifest version")
    if type(payload["inputs"]) is not list or type(payload["dispositions"]) is not list:
        raise ValueError("Accepted manifest inventory must be ordered arrays")
    inputs = []
    for item in payload["inputs"]:
        _closed(
            item,
            (
                "input_key",
                "logical_path",
                "media_type",
                "raw_hash",
                "byte_length",
                "provider_revision",
                "container_chain",
            ),
        )
        if type(item["container_chain"]) is not list or item["container_chain"]:
            raise ValueError("Profile binding currently requires plain local file inputs")
        if type(item["raw_hash"]) is not str:
            raise ValueError("Accepted raw hash must be text")
        inputs.append(RawInput(**(item | {"raw_uri": "hippo-raw:sha256:" + item["raw_hash"]})))
    dispositions = []
    for item in payload["dispositions"]:
        _closed(item, (f.name for f in fields(InputDisposition)))
        if type(item["reason"]) is not str:
            raise ValueError("Accepted disposition reason must be text")
        dispositions.append(InputDisposition(**item))
    limits = CaptureLimits(**_closed(payload["limits"], (f.name for f in fields(CaptureLimits))))
    data = canonical_json(payload).encode("utf-8")
    return AcceptedInputs(
        payload["source_id"],
        payload["workspace_id"],
        tuple(inputs),
        dispositions,
        canonical_json(payload["configuration"]),
        limits,
        RawArtifact(revision.raw_uri, revision.content_hash, len(data)),
    )


def validate_generation_profile(store, generation, manifest_revision_id=None) -> GenerationProfile:
    """Validate exact accepted metadata; explicit revision is for staging bind only."""
    mode = embedding_mode(generation)
    pointer = json.loads(generation.coverage_json).get(PROFILE_POINTER)
    if manifest_revision_id is None:
        if mode != "verified_v1":
            raise ValueError("Generation has no verified profile binding")
        manifest_revision_id = pointer
    elif mode == "verified_v1" and manifest_revision_id != pointer:
        raise ValueError("Generation profile binding conflicts")
    if type(manifest_revision_id) is not str or not manifest_revision_id:
        raise ValueError("Accepted manifest revision must be a nonempty immutable ID")
    source = store.get_source(generation.source_id)
    if source is None:
        raise ValueError("Generation source is unavailable")
    workspace = source["workspace_id"]
    members = [row for row in store._knowledge_rows("GenerationMember") if row.generation_id == generation.id]
    selected = {row.artifact_revision_id for row in members}
    if len(selected) != len(members) or manifest_revision_id not in selected:
        raise ValueError("Accepted manifest is outside exact generation membership")
    pairs = []
    for identity in selected:
        revision = store._knowledge_get("ArtifactRevision", identity)
        artifact = store._knowledge_get("Artifact", revision.artifact_id) if revision else None
        if (
            revision is None
            or artifact is None
            or (artifact.source_id, artifact.workspace_id) != (generation.source_id, workspace)
        ):
            raise ValueError("Accepted revision crosses generation source or workspace")
        if artifact.connector_id is not None or artifact.provider_instance is not None:
            raise ValueError("Profile binding currently requires local artifacts")
        if revision.lifecycle != "active":
            raise ValueError("Accepted revision must be active")
        pairs.append((artifact, revision))
    manifests = [(a, r) for a, r in pairs if a.kind == "manifest"]
    if len(manifests) != 1 or manifests[0][1].id != manifest_revision_id:
        raise ValueError("Generation requires exactly one accepted manifest revision")
    artifact, revision = manifests[0]
    if (
        artifact.external_id != MANIFEST_EXTERNAL_ID
        or artifact.id
        != make_identity("artifact", [workspace, generation.source_id, "manifest", MANIFEST_EXTERNAL_ID])
        or revision.provider_revision is not None
    ):
        raise ValueError("Accepted manifest identity differs from its local convention")
    metadata = _closed(json.loads(revision.metadata_json), ("accepted_manifest_v1",))
    accepted = _accepted(metadata["accepted_manifest_v1"], revision)
    if (accepted.source_id, accepted.workspace_id) != (generation.source_id, workspace):
        raise ValueError("Accepted manifest belongs to another source or workspace")
    originals = {a.id: (a, r) for a, r in pairs if a.kind != "manifest"}
    if len(originals) != len(pairs) - 1 or len(originals) != len(accepted.inputs):
        raise ValueError("Accepted original revision inventory differs")
    expected_ids = set()
    for item in accepted.inputs:
        identity = make_identity("artifact", [workspace, generation.source_id, "file", item.logical_path])
        expected_ids.add(identity)
        pair = originals.get(identity)
        if pair is None:
            raise ValueError("Accepted original artifact is missing")
        a, r = pair
        if (
            a.kind != "file"
            or a.external_id != item.logical_path
            or item.input_key
            != local_input_key(
                workspace_id=workspace, source_id=generation.source_id, logical_path=item.logical_path
            )
            or (r.content_hash, r.raw_uri, r.provider_revision)
            != (item.raw_hash, item.raw_uri, item.provider_revision)
        ):
            raise ValueError("Original revision differs from its accepted raw identity")
    if expected_ids != set(originals):
        raise ValueError("Generation has unaccepted original revisions")
    configuration = json.loads(accepted.configuration_json)
    descriptor = validate_profile_descriptor(configuration.get("embedding_profile"))
    if descriptor.fingerprint != generation.embedding_profile:
        raise ValueError("Generation and accepted embedding profiles differ")
    expected = generation_for_inputs(
        pairs,
        workspace_id=workspace,
        source_id=generation.source_id,
        parent_id=generation.parent_id,
        parser_version=generation.parser_version,
        linker_version=generation.linker_version,
        embedding_profile=generation.embedding_profile,
        configuration=configuration,
        created_at=generation.created_at,
    )
    if expected.id != generation.id or expected.manifest_hash != generation.manifest_hash:
        raise ValueError("Generation identity differs from its accepted input manifest")
    return GenerationProfile(descriptor, text_hash(accepted.configuration_json))
