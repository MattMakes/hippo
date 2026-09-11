"""Deterministic accepted inputs for a staged source generation.

These constructors do not publish or write anything. The lifecycle coordinator
must authorize the inputs and acquire its build lease before persisting them.
Output checksums belong to IndexManifest, never to the generation's input hash.
"""

from collections.abc import Iterable
from datetime import datetime

from . import model as k
from .identity import canonical_json, make_identity, text_hash


def generation_for_inputs(
    inputs: Iterable[tuple[k.Artifact, k.ArtifactRevision]],
    *,
    workspace_id: str,
    source_id: str,
    parent_id: str | None,
    parser_version: str,
    linker_version: str,
    embedding_profile: str,
    configuration: dict,
    created_at: datetime,
) -> k.Generation:
    """Identify one current revision per artifact before producing native nodes.

    Observation timestamps and raw blob locations are deliberately excluded:
    replaying accepted inputs must not invent another generation. Input content,
    provider revision identities and extraction configuration do participate.
    """
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ValueError("A generation requires an explicit workspace")
    revisions = []
    seen = set()
    for artifact, revision in inputs:
        if artifact.source_id != source_id or artifact.workspace_id != workspace_id:
            raise ValueError("Generation inputs must belong to the source and workspace")
        if revision.artifact_id != artifact.id:
            raise ValueError("Revision does not belong to the accepted artifact")
        if artifact.id in seen:
            raise ValueError("A current generation accepts one revision per artifact")
        seen.add(artifact.id)
        revisions.append([artifact.id, revision.id, revision.content_hash])
    manifest = {
        "schema_version": 1,
        "workspace_id": workspace_id,
        "source_id": source_id,
        "revisions": sorted(revisions),
        "parser_version": parser_version,
        "linker_version": linker_version,
        "embedding_profile": embedding_profile,
        "configuration": configuration,
    }
    return k.Generation(
        source_id=source_id,
        parent_id=parent_id,
        status="staging",
        parser_version=parser_version,
        linker_version=linker_version,
        embedding_profile=embedding_profile,
        created_at=created_at,
        manifest_hash=text_hash(canonical_json(manifest)),
    )


def generation_namespace(generation: k.Generation) -> str:
    """A namespace for native rows; logical Source ownership remains unchanged."""
    return text_hash(canonical_json([generation.source_id, generation.id]))


def generation_passage_id(generation_id: str, revision_id: str, span_id: str, ordinal: int) -> str:
    """Bind native passage identity to immutable generation and original evidence."""
    if any(
        not isinstance(value, str) or not value.strip() for value in (generation_id, revision_id, span_id)
    ):
        raise ValueError("Passage identity requires generation, revision and span IDs")
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("Passage ordinal must be a nonnegative integer")
    return make_identity("passage", [generation_id, revision_id, span_id, ordinal])
