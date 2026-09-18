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

# Which accepted-input shape a generation claims, read from the accepted manifest's own
# configuration so it is hashed into generation identity and cannot be changed afterwards.
# Absent means plain prose, which is what every generation written before this key existed
# carries, so their identities and checksums are unchanged.
GENERATION_PROFILE_KEY = "generation_profile"
PLAIN_PROSE_PROFILE = "plain_prose"
CODE_PROFILE = "code"
CONNECTOR_PROFILE = "connector"
GENERATION_PROFILES = (PLAIN_PROSE_PROFILE, CODE_PROFILE, CONNECTOR_PROFILE)

# A connector generation's inputs are remote, so they cannot be an `accepted-inputs-v1`
# manifest: that contract describes local files captured into the raw store. The connector
# runtime writes its own inventory manifest instead, and the branch below is chosen by this
# metadata key rather than by the configuration, which is the accepted manifest's own content
# and therefore unreadable until the manifest has already been interpreted.
CONNECTOR_MANIFEST_EXTERNAL_ID = "connector-inventory-v1"
CONNECTOR_MANIFEST_KEY = "connector_inventory_v1"


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


def _accepted_file(pair, item, *, workspace, source_id):
    """One accepted `file` artifact against its raw identity; shared by both profiles."""
    if pair is None:
        raise ValueError("Accepted original artifact is missing")
    a, r = pair
    if (
        a.kind != "file"
        or a.external_id != item.logical_path
        or item.input_key
        != local_input_key(workspace_id=workspace, source_id=source_id, logical_path=item.logical_path)
        or (r.content_hash, r.raw_uri, r.provider_revision)
        != (item.raw_hash, item.raw_uri, item.provider_revision)
    ):
        raise ValueError("Original revision differs from its accepted raw identity")


def _code_members(originals, accepted, generation, workspace):
    """The `code` member set, returning only the pairs that are identity inputs.

    Exactly one `repository` artifact for the captured tree, one `file` artifact per
    accepted input, and zero or more `history_event` artifacts -- one per commit the
    history walk bound. The `history_event` pairs are members but **not** identity
    inputs: plan section 6 settles the generation before `read_history` runs, so a
    commit can never be hashed into the ID the members must re-derive. The head SHA
    still enters identity as the repository revision's `provider_revision`.
    """
    from .code_history import COMMIT_RAW_URI_SCHEME

    by_kind = {}
    for artifact, revision in originals.values():
        by_kind.setdefault(artifact.kind, []).append((artifact, revision))
    repositories = by_kind.get("repository", [])
    files = by_kind.get("file", [])
    if (
        set(by_kind) - {"repository", "file", "history_event"}
        or len(repositories) != 1
        or len(files) != len(accepted.inputs)
    ):
        raise ValueError("Accepted original revision inventory differs")
    repository, repository_revision = repositories[0]
    if (
        repository.canonical_uri != repository.external_id
        or repository.id
        != make_identity("artifact", [workspace, generation.source_id, "repository", repository.external_id])
        or (repository_revision.content_hash, repository_revision.raw_uri)
        != (accepted.manifest.sha256, accepted.manifest.uri)
    ):
        raise ValueError("Captured tree identity differs from its accepted manifest")
    expected_ids = {repository.id}
    for item in accepted.inputs:
        identity = make_identity("artifact", [workspace, generation.source_id, "file", item.logical_path])
        expected_ids.add(identity)
        _accepted_file(originals.get(identity), item, workspace=workspace, source_id=generation.source_id)
    for artifact, revision in by_kind.get("history_event", []):
        expected_ids.add(artifact.id)
        # A commit names no stored raw object, so its `raw_uri` is never dereferenced:
        # it is asserted to be exactly the commit scheme instead.
        if (
            artifact.canonical_uri != artifact.external_id
            or artifact.id
            != make_identity(
                "artifact", [workspace, generation.source_id, "history_event", artifact.external_id]
            )
            or not revision.provider_revision
            or artifact.external_id != f"{repository.external_id}@{revision.provider_revision}"
            or revision.raw_uri != COMMIT_RAW_URI_SCHEME + revision.provider_revision
        ):
            raise ValueError("History event revision differs from its commit identity")
    if expected_ids != set(originals):
        raise ValueError("Generation has unaccepted original revisions")
    return [(a, r) for a, r in originals.values() if a.kind != "history_event"]


def _prose_members(originals, accepted, generation, workspace):
    if len(originals) != len(accepted.inputs):
        raise ValueError("Accepted original revision inventory differs")
    expected_ids = set()
    for item in accepted.inputs:
        identity = make_identity("artifact", [workspace, generation.source_id, "file", item.logical_path])
        expected_ids.add(identity)
        _accepted_file(originals.get(identity), item, workspace=workspace, source_id=generation.source_id)
    if expected_ids != set(originals):
        raise ValueError("Generation has unaccepted original revisions")
    return list(originals.values())


def _connector_members(originals, payload, generation, workspace):
    """The `connector` member set: every original is a remote input this manifest lists.

    The inventory manifest is the identity record of a remote capture, the way
    `accepted-inputs-v1` is for a local one. It names each member by artifact, revision, raw
    identity and provider revision, and the comparison is exact in both directions, so neither
    a member the manifest never saw nor a manifest entry the generation dropped survives.
    """
    connector_id, instance = payload["connector_id"], payload["instance"]
    if (payload["source_id"], payload["workspace_id"]) != (generation.source_id, workspace):
        raise ValueError("Connector manifest belongs to another source or workspace")
    for artifact, _ in originals.values():
        if (artifact.connector_id, artifact.provider_instance) != (connector_id, instance):
            raise ValueError("Connector generation members differ from their inventory manifest")
    if type(payload["members"]) is not list:
        raise ValueError("Connector manifest inventory must be an ordered array")
    fields = ("artifact_id", "revision_id", "content_hash", "raw_uri", "provider_revision")
    expected = sorted(tuple(_closed(item, fields)[field] for field in fields) for item in payload["members"])
    actual = sorted(
        (a.id, r.id, r.content_hash, r.raw_uri, r.provider_revision) for a, r in originals.values()
    )
    if actual != expected:
        raise ValueError("Connector generation members differ from their inventory manifest")
    return list(originals.values())


def _connector_manifest(artifact, revision, generation, workspace):
    """The one local `manifest` artifact a connector generation binds, and its closed payload."""
    if (
        artifact.external_id != CONNECTOR_MANIFEST_EXTERNAL_ID
        or artifact.connector_id is not None
        or artifact.id
        != make_identity(
            "artifact", [workspace, generation.source_id, "manifest", CONNECTOR_MANIFEST_EXTERNAL_ID]
        )
        or revision.provider_revision is not None
    ):
        raise ValueError("Connector manifest identity differs from its local convention")
    metadata = _closed(json.loads(revision.metadata_json), (CONNECTOR_MANIFEST_KEY,))
    payload = _closed(
        metadata[CONNECTOR_MANIFEST_KEY],
        (
            "version",
            "source_id",
            "workspace_id",
            "connector_id",
            "instance",
            "partition",
            "configuration",
            "members",
        ),
    )
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("Unsupported connector manifest version")
    return payload


def _connector_manifest_key(store, manifest_revision_id) -> bool:
    """Whether this manifest revision is a connector inventory, read before any other check."""
    revision = store._knowledge_get("ArtifactRevision", manifest_revision_id)
    if revision is None:
        return False
    metadata = json.loads(revision.metadata_json)
    return type(metadata) is dict and CONNECTOR_MANIFEST_KEY in metadata


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
    members = store._knowledge_rows("GenerationMember", generation_id=generation.id)
    selected = {row.artifact_revision_id for row in members}
    if len(selected) != len(members) or manifest_revision_id not in selected:
        raise ValueError("Accepted manifest is outside exact generation membership")
    # Which manifest contract this generation binds, decided before any original is read: the
    # local-artifact refusal below belongs to the accepted-inputs path alone (plan section 7.2).
    connector = _connector_manifest_key(store, manifest_revision_id)
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
        if not connector and (artifact.connector_id is not None or artifact.provider_instance is not None):
            raise ValueError("Profile binding currently requires local artifacts")
        if revision.lifecycle != "active":
            raise ValueError("Accepted revision must be active")
        pairs.append((artifact, revision))
    manifests = [(a, r) for a, r in pairs if a.kind == "manifest"]
    if len(manifests) != 1 or manifests[0][1].id != manifest_revision_id:
        raise ValueError("Generation requires exactly one accepted manifest revision")
    artifact, revision = manifests[0]
    originals = {a.id: (a, r) for a, r in pairs if a.kind != "manifest"}
    if len(originals) != len(pairs) - 1:
        raise ValueError("Accepted original revision inventory differs")
    if connector:
        payload = _connector_manifest(artifact, revision, generation, workspace)
        configuration = payload["configuration"]
        if configuration.get(GENERATION_PROFILE_KEY) != CONNECTOR_PROFILE:
            raise ValueError("Connector manifest does not claim the connector generation profile")
        configuration_json = canonical_json(configuration)
        identity_pairs = [
            manifests[0],
            *_connector_members(originals, payload, generation, workspace),
        ]
    else:
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
        configuration = json.loads(accepted.configuration_json)
        configuration_json = accepted.configuration_json
        shape = configuration.get(GENERATION_PROFILE_KEY, PLAIN_PROSE_PROFILE)
        if shape not in GENERATION_PROFILES:
            raise ValueError("Unknown accepted generation profile")
        if shape == CONNECTOR_PROFILE:
            raise ValueError("The connector profile requires a connector inventory manifest")
        members = _code_members if shape == CODE_PROFILE else _prose_members
        identity_pairs = [manifests[0], *members(originals, accepted, generation, workspace)]
    descriptor = validate_profile_descriptor(configuration.get("embedding_profile"))
    if descriptor.fingerprint != generation.embedding_profile:
        raise ValueError("Generation and accepted embedding profiles differ")
    expected = generation_for_inputs(
        identity_pairs,
        workspace_id=workspace,
        source_id=generation.source_id,
        parent_id=generation.parent_id,
        parser_version=generation.parser_version,
        linker_version=generation.linker_version,
        embedding_profile=generation.embedding_profile,
        configuration=configuration,
        created_at=generation.created_at,
        # S1 section 10: recorded on the generation, never hashed, so this changes no identity;
        # it keeps the re-derived record equal to the stored one field for field.
        registry_fingerprint=generation.registry_fingerprint,
    )
    if expected.id != generation.id or expected.manifest_hash != generation.manifest_hash:
        raise ValueError("Generation identity differs from its accepted input manifest")
    return GenerationProfile(descriptor, text_hash(configuration_json))
