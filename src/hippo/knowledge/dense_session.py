"""Activate dense retrieval from one held, authorized structural graph.

Call outside an ambient store transaction, and keep model calls outside such
transactions. The existing query session owns leases and its local heartbeat;
this module owns only the scoped model and execution matrices.
"""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import replace

import numpy as np

from ..ollama import EMBED_PREFIXES, _base_name
from ..store.base import validate_settings
from .dense import DenseCapability, DenseUnavailable, validate_dense_graph
from .embedding_profile import (
    EmbeddingProfileChanged,
    EmbeddingProfileMismatch,
    EmbeddingSpec,
    ProfiledEmbeddings,
    ResolvedEmbeddingProfile,
    resolve_embedding_profile,
    validate_profile_descriptor,
)
from .generation_profiles import embedding_mode, validate_generation_profile
from .query_access import AuthorizedModel, QuerySession, query_session


class DenseSessionUnavailable(DenseUnavailable):
    """A held candidate inventory cannot satisfy the requested dense route."""

    def __init__(self, reason: str, message: str):
        if reason not in {
            "mixed_modes",
            "mixed_profiles",
            "dimension_mismatch",
            "unverified",
            "invalid_binding",
            "no_dense_dimension",
            "invalid_borrow",
        }:
            raise ValueError("Unknown dense session failure")
        self.reason = reason
        super().__init__(message)


def _contributors(graph):
    """Read only retained support; snapshot bundle membership is not eligibility."""
    passages = {p.id: p for p in graph.passages}
    generations = {}

    def add(generation, source):
        if generations.setdefault(generation, source) != source:
            raise DenseSessionUnavailable("invalid_binding", "Conflicting retained generation binding")

    for row in graph.retrieval_evidence:
        add(row.generation_id, passages[row.passage_id].source_id)
    for row in graph.structural_code_evidence:
        add(row.generation_id, row.source_id)
    for row in graph.structural_relations:
        for source, generation in row.source_generations:
            add(generation, source)
    # Structural typed-object provenance is added by the structural loader.
    objects = graph.structural_object_evidence
    for row in objects:
        add(row.generation_id, row.source_id)

    legacy = bool(graph.legacy_dense_vectors)
    supported_code = {row.node_id for row in graph.structural_code_evidence}
    for node in graph.code_nodes:
        definitions = {graph.node_ids[v] for v in graph.defining_passages(graph.idx_of[node.id])}
        if definitions - graph.managed_passage_ids:
            legacy = True
        if node.id not in supported_code and not definitions & graph.managed_passage_ids:
            legacy = True
    supported_entities = {row.node_id for row in objects}
    prose_facts = {row.fact_id for row in graph.prose_provenance}
    for fact in graph.facts:
        if fact.id in prose_facts:
            supported_entities.update((fact.subject_id, fact.object_id))
    for (a, b), edge in graph.edges.items():
        if edge.mention:
            left, right = graph.node_ids[a], graph.node_ids[b]
            if left in graph.managed_passage_ids:
                supported_entities.add(right)
            if right in graph.managed_passage_ids:
                supported_entities.add(left)
    if set(graph.entity_names) - supported_entities:
        legacy = True
    return generations, legacy


def _classification(ctx, owner):
    graph = owner.graph
    validate_dense_graph(graph)
    if graph.dense_capability.mode == "legacy" and (graph.num_nodes or graph.facts):
        raise DenseSessionUnavailable("invalid_borrow", "Borrowed graph requires structural vector bindings")
    generations, legacy = _contributors(graph)
    vector_profiles = {row.generation_id: row.profile for row in graph.dense_vectors}
    profiles, tags = [], set()
    owner.validate()
    try:
        with ctx.store.transaction():
            for generation_id, source_id in sorted(generations.items()):
                generation = ctx.store._generation(generation_id)
                if generation.source_id != source_id or generation.status not in ("active", "retired"):
                    raise ValueError("Generation does not match selected evidence")
                if embedding_mode(generation) == "verified_v1":
                    profiles.append(validate_generation_profile(ctx.store, generation).profile)
                else:
                    tags.add(generation.embedding_profile)
                if (
                    vector_profiles.get(generation_id, generation.embedding_profile)
                    != generation.embedding_profile
                ):
                    raise ValueError("Vector profile disagrees with generation")
    except ValueError as error:
        raise DenseSessionUnavailable(
            "invalid_binding", "Selected embedding profile binding is invalid"
        ) from error
    finally:
        owner.validate()
    if profiles and (tags or legacy):
        raise DenseSessionUnavailable("mixed_modes", "Verified and tag-compatible evidence cannot be mixed")
    if profiles and any(profile != profiles[0] for profile in profiles[1:]):
        raise DenseSessionUnavailable("mixed_profiles", "Dense evidence requires one verified profile")
    if profiles and any(row.dimension != profiles[0].profile.dimension for row in graph.dense_vectors):
        raise DenseSessionUnavailable(
            "dimension_mismatch", "Selected vector dimension disagrees with its profile"
        )
    return profiles[0] if profiles else None, tags, legacy


def _activate(owner, capability, validate):
    graph = owner.graph
    rows = {
        (row.lane, row.projected_id): row.values
        for row in (*graph.dense_vectors, *graph.legacy_dense_vectors)
    }
    dimension = capability.dimension or 0

    def matrix(lane, items):
        return np.asarray([rows[lane, item.id] for item in items], dtype=np.float32).reshape(
            len(items), dimension
        )

    activated = replace(
        graph,
        dense_capability=capability,
        passage_embeddings=matrix("passage", graph.passages),
        fact_embeddings=matrix("fact", graph.facts),
        authorization_check=validate,
    )
    activated.snapshot_ids = tuple(getattr(graph, "snapshot_ids", ()))
    if hasattr(graph, "snapshot_renewal_interval"):
        activated.snapshot_renewal_interval = graph.snapshot_renewal_interval
    return activated


def _tag_guard(ctx, owner, tag):
    def validate():
        owner.validate()
        try:
            if ctx.ollama.embed_model != tag:
                raise EmbeddingProfileChanged("The configured embedding tag changed during retrieval")
        finally:
            owner.validate()

    return validate


@contextmanager
def _session(
    ctx, access, *, settings, resolved_profile, spec, cache, session, verified
) -> Iterator[QuerySession]:
    if session is not None:
        if type(session) is not QuerySession or access is not None:
            raise DenseSessionUnavailable(
                "invalid_borrow", "Borrowed sessions retain their existing audience"
            )
        if settings is not None and validate_settings({**session.settings, **settings}) != dict(
            session.settings
        ):
            raise DenseSessionUnavailable("invalid_borrow", "Requested settings differ from the held session")
        owner_context = nullcontext(session)
    else:
        owner_context = query_session(ctx, access, settings=settings, structural=True)
    with owner_context as owner:
        adapter = None
        local = owner.validate
        try:
            owner.validate()
            profile, tags, legacy = _classification(ctx, owner)
            graph = owner.graph
            empty = not (
                graph.num_nodes or graph.facts or graph.original_citations or graph.structural_relations
            )
            strict = verified or resolved_profile is not None or spec is not None or profile is not None
            if strict:
                if tags or legacy:
                    raise DenseSessionUnavailable(
                        "unverified", "Dense mode requires rebuilt verified evidence"
                    )
                if spec is not None and type(spec) is not EmbeddingSpec:
                    raise ValueError("An immutable EmbeddingSpec is required")
                if resolved_profile is not None and type(resolved_profile) is not ResolvedEmbeddingProfile:
                    raise ValueError("An immutable resolved embedding profile is required")
                captured = profile.spec if profile is not None else spec
                if captured is None and resolved_profile is not None:
                    captured = resolved_profile.spec
                if captured is None:
                    query_prefix, document_prefix = EMBED_PREFIXES.get(
                        _base_name(ctx.ollama.embed_model), ("", "")
                    )
                    captured = EmbeddingSpec(query_prefix=query_prefix, document_prefix=document_prefix)
                if spec is not None and captured != spec:
                    raise EmbeddingProfileMismatch("Requested spec differs from selected evidence")
                if resolved_profile is not None:
                    stored = validate_profile_descriptor(resolved_profile.descriptor())
                    if stored.spec != captured or (profile is not None and stored != profile):
                        raise EmbeddingProfileMismatch("Resolved profile differs from selected evidence")
                resolved = resolved_profile or resolve_embedding_profile(
                    ctx.ollama, spec=captured, authorization_check=local
                )
                if profile is not None and validate_profile_descriptor(resolved.descriptor()) != profile:
                    raise EmbeddingProfileMismatch("Live embedding profile differs from selected evidence")
                dimension = resolved.profile.dimension
                if any(
                    row.dimension != dimension or row.profile != resolved.fingerprint
                    for row in graph.dense_vectors
                ):
                    raise DenseSessionUnavailable(
                        "dimension_mismatch", "Selected vector profile or dimension disagrees"
                    )
                adapter = ProfiledEmbeddings(ctx.ollama, resolved, cache=cache, authorization_check=local)
                adapter.validate()
                capability = DenseCapability("verified", resolved.fingerprint, dimension)
                model = AuthorizedModel(adapter, local)
            elif empty:
                capability = DenseCapability()
                model = owner.model
            else:
                tag = ctx.ollama.embed_model
                local = _tag_guard(ctx, owner, tag)
                local()
                if tags and tags != {tag}:
                    raise EmbeddingProfileMismatch(
                        "Selected evidence does not match the configured embedding tag"
                    )
                widths = {row.dimension for row in (*graph.dense_vectors, *graph.legacy_dense_vectors)}
                if len(widths) != 1:
                    reason = "dimension_mismatch" if widths else "no_dense_dimension"
                    raise DenseSessionUnavailable(
                        reason, "Tag-compatible evidence requires one positive vector dimension"
                    )
                capability = DenseCapability("tag_compatible", dimension=widths.pop())
                model = AuthorizedModel(owner.model, local)
            activated = _activate(owner, capability, local)
            local()
            yield QuerySession(activated, model, local, owner.settings)
        finally:
            try:
                if adapter is not None:
                    adapter.validate()
            finally:
                local()


@contextmanager
def dense_session(
    ctx, access=None, *, settings=None, resolved_profile=None, spec=None, cache=None, session=None
):
    """Require verified dense evidence; borrow or own one structural query session."""
    with _session(
        ctx,
        access,
        settings=settings,
        resolved_profile=resolved_profile,
        spec=spec,
        cache=cache,
        session=session,
        verified=True,
    ) as result:
        yield result


@contextmanager
def retrieval_session(
    ctx, access=None, *, settings=None, resolved_profile=None, spec=None, cache=None, session=None
):
    """Dispatch retained evidence to verified dense or explicit tag compatibility."""
    with _session(
        ctx,
        access,
        settings=settings,
        resolved_profile=resolved_profile,
        spec=spec,
        cache=cache,
        session=session,
        verified=False,
    ) as result:
        yield result
