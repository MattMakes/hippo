"""Detached plain-prose model preparation; no store access or publication.

Captured profiles describe accepted semantics, not remote attestation. Callers
must supply guarded runtimes and keep their build authorization/lease live.
"""

from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import asdict, dataclass, field
from threading import Lock

from .. import prompts
from ..hipporag import openie, preparation
from ..hipporag.text import entity_id, fact_id, fact_text
from . import model as k
from .derivations import dependency_version, prose_fingerprint
from .embedding_profile import StoredEmbeddingProfile, validate_profile_descriptor
from .identity import canonical_json, text_hash
from .input_binding import BoundPassage, PreparedEvidence
from .lifecycle import generation_for_inputs

PROSE_RULE = "plain-openie-v1"


def _prompt_fingerprint():
    return text_hash(
        canonical_json(
            [
                prompts.ner_messages("<input>"),
                prompts.NER_SCHEMA,
                prompts.triples_messages("<input>", ["<entity>"]),
                prompts.TRIPLES_SCHEMA,
            ]
        )
    )


@dataclass(frozen=True, slots=True)
class OpenIEProfile:
    wire_model: str
    model_digest: str
    num_ctx: int
    prompt_fingerprint: str = field(default_factory=_prompt_fingerprint)
    normalization_version: str = "hipporag-clean-phrase-triples-v1"
    response_parser_version: str = "ollama-json-object-v1"
    ner_max_tokens: int = 512
    triples_max_tokens: int = 2048
    temperature: float = 0.0
    thinking_policy: str = "disable-if-capable-v1"

    def __post_init__(self):
        if any(
            type(value) is not str
            for value in (
                self.wire_model,
                self.model_digest,
                self.prompt_fingerprint,
                self.normalization_version,
                self.response_parser_version,
                self.thinking_policy,
            )
        ):
            raise ValueError("OpenIE profile requires immutable string identities")
        if (
            type(self.wire_model) is not str
            or not self.wire_model.strip()
            or self.wire_model != self.wire_model.strip()
            or type(self.model_digest) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", self.model_digest)
            or type(self.num_ctx) is not int
            or self.num_ctx <= 0
            or self.prompt_fingerprint != _prompt_fingerprint()
            or self.normalization_version != "hipporag-clean-phrase-triples-v1"
            or self.response_parser_version != "ollama-json-object-v1"
            or type(self.ner_max_tokens) is not int
            or self.ner_max_tokens != openie.NER_MAX_TOKENS
            or type(self.triples_max_tokens) is not int
            or self.triples_max_tokens != openie.TRIPLES_MAX_TOKENS
            or type(self.temperature) is not float
            or self.temperature != 0.0
            or self.thinking_policy != "disable-if-capable-v1"
        ):
            raise ValueError("OpenIE profile differs from supported captured semantics")

    def descriptor(self):
        return {"schema_version": 1, **asdict(self)}

    @property
    def fingerprint(self):
        return text_hash(canonical_json(self.descriptor()))


def prose_configuration(embedding_profile, extractor_profile, *, synonymy_threshold=0.8, allow_empty=False):
    if type(embedding_profile) is not StoredEmbeddingProfile or type(extractor_profile) is not OpenIEProfile:
        raise ValueError("Configuration requires immutable captured profiles")
    if (
        type(allow_empty) is not bool
        or type(synonymy_threshold) not in (int, float)
        or not 0 <= synonymy_threshold <= 1
    ):
        raise ValueError("Invalid plain prose policy")
    return {
        "embedding_profile": embedding_profile.descriptor(),
        "openie_profile": extractor_profile.descriptor(),
        "prose": {
            "rule": PROSE_RULE,
            "synonymy_threshold": synonymy_threshold,
            "synonym_rule": "hipporag-cosine-top100-v1",
            "code": "empty",
            "history": "excluded",
            "allow_empty": allow_empty,
        },
    }


def _typed_tuple(value, kind):
    if type(value) is not tuple or any(type(item) is not kind for item in value):
        raise ValueError(f"Expected immutable tuple of {kind.__name__}")


@dataclass(frozen=True, slots=True)
class PlainProseInputs:
    generation: k.Generation
    evidence: PreparedEvidence
    artifacts_and_revisions: tuple[tuple[k.Artifact, k.ArtifactRevision], ...]
    configuration_json: str
    embedding_profile: StoredEmbeddingProfile
    extractor_profile: OpenIEProfile

    def __post_init__(self):
        for value, kind in (
            (self.generation, k.Generation),
            (self.evidence, PreparedEvidence),
            (self.embedding_profile, StoredEmbeddingProfile),
            (self.extractor_profile, OpenIEProfile),
        ):
            if type(value) is not kind:
                raise ValueError("Plain prose inputs require exact immutable values")
        _typed_tuple(self.artifacts_and_revisions, tuple)
        for pair in self.artifacts_and_revisions:
            if len(pair) != 2 or type(pair[0]) is not k.Artifact or type(pair[1]) is not k.ArtifactRevision:
                raise ValueError("Expected immutable Artifact/Revision pairs")
        if type(self.configuration_json) is not str:
            raise ValueError("Expected canonical configuration JSON")
        config = json.loads(self.configuration_json)
        if type(config) is not dict or canonical_json(config) != self.configuration_json:
            raise ValueError("Expected canonical configuration object")
        prose = config.get("prose", {})
        if type(prose) is not dict:
            raise ValueError("Configuration requires a prose object")
        expected = prose_configuration(
            self.embedding_profile,
            self.extractor_profile,
            synonymy_threshold=prose.get("synonymy_threshold"),
            allow_empty=prose.get("allow_empty"),
        )
        if any(config.get(key) != value for key, value in expected.items()):
            raise ValueError("Configuration differs from captured profiles and prose policy")
        gen, evidence = self.generation, self.evidence
        wanted = generation_for_inputs(
            self.artifacts_and_revisions,
            workspace_id=evidence.workspace_id,
            source_id=gen.source_id,
            parent_id=gen.parent_id,
            parser_version=gen.parser_version,
            linker_version=gen.linker_version,
            embedding_profile=self.embedding_profile.fingerprint,
            configuration=config,
            created_at=gen.created_at,
        )
        if gen.replace(coverage_json="{}") != wanted or evidence.generation_id != gen.id:
            raise ValueError("Generation differs from accepted revision/configuration identity")
        revisions = {r.id for _, r in self.artifacts_and_revisions}
        if revisions != {m.artifact_revision_id for m in evidence.revision_members}:
            raise ValueError("Accepted revisions differ from exact prepared membership")
        if not evidence.passages and not prose["allow_empty"]:
            raise ValueError("Authoritative empty source requires explicit policy")
        for passage in evidence.passages:
            if passage.generation != gen or passage.chunk.defines or passage.chunk.extract_text is not None:
                raise ValueError("Only bound plain prose chunks are supported")


def _vector(values, dimension=None):
    if type(values) is not tuple or not values or any(type(v) not in (int, float) for v in values):
        raise ValueError("Invalid vector values")
    if dimension is not None and len(values) != dimension:
        raise ValueError("Vector dimension differs from captured profile")
    try:
        result = tuple(struct.unpack("f", struct.pack("f", v))[0] for v in values)
    except (OverflowError, struct.error) as exc:
        raise ValueError("Vector cannot be represented as float32") from exc
    if not all(math.isfinite(v) for v in result) or not math.isclose(math.hypot(*result), 1.0, abs_tol=2e-6):
        raise ValueError("Vector is not finite and unit normalized")
    return result


@dataclass(frozen=True, slots=True)
class PreparedDensePassage:
    passage: BoundPassage
    embedding: tuple[float, ...]

    def __post_init__(self):
        if type(self.passage) is not BoundPassage:
            raise ValueError("Expected immutable bound passage")
        object.__setattr__(self, "embedding", _vector(self.embedding))

    def native_row(self):
        return {**self.passage.native_row(), "embedding": list(self.embedding)}


@dataclass(frozen=True, slots=True)
class InferenceGroup:
    input_kind: str
    input_id: str
    input_version: str
    input_text_hash: str
    extractor_profile: str
    support_passage_ids: tuple[str, ...]
    original_span_ids: tuple[str, ...]

    def __post_init__(self):
        for value in (self.support_passage_ids, self.original_span_ids):
            _typed_tuple(value, str)
            if not value or len(set(value)) != len(value):
                raise ValueError("Inference requires unique complete support/originals")
        if self.input_kind not in ("span", "view") or any(
            type(v) is not str or not v
            for v in (
                self.input_id,
                self.input_version,
                self.input_text_hash,
                self.extractor_profile,
            )
        ):
            raise ValueError("Invalid inference identity")


def _groups(inputs):
    groups = {}
    by_chunk = {p.chunk.chunk_key: p for p in inputs.evidence.passages}
    for item in inputs.evidence.extraction_inputs:
        passage = by_chunk[item.chunk_key]
        if preparation._openie_text(passage.to_chunk()) != item.text:
            raise ValueError("Shared OpenIE gate differs from exact extraction input")
        key = item.input_kind, item.input_id, inputs.extractor_profile.fingerprint
        group = InferenceGroup(
            item.input_kind,
            item.input_id,
            item.input_version,
            item.input_text_hash,
            key[2],
            tuple(sorted(item.support_passage_ids)),
            tuple(sorted(item.original_span_ids)),
        )
        if key in groups:
            previous = groups[key]
            if (previous.input_version, previous.input_text_hash, previous.original_span_ids) != (
                group.input_version,
                group.input_text_hash,
                group.original_span_ids,
            ):
                raise ValueError("Conflicting inference inputs")
            group = InferenceGroup(
                group.input_kind,
                group.input_id,
                group.input_version,
                group.input_text_hash,
                group.extractor_profile,
                tuple(sorted(set(previous.support_passage_ids + group.support_passage_ids))),
                group.original_span_ids,
            )
        groups[key] = group
    return tuple(groups.values())


@dataclass(frozen=True, slots=True)
class ProseCoverage:
    dense_passage_ids: tuple[str, ...]
    expected_inference: tuple[InferenceGroup, ...]
    successful_extraction_ids: tuple[str, ...]
    skipped: tuple = ()
    native: str = "empty"

    def __post_init__(self):
        for value in (self.dense_passage_ids, self.successful_extraction_ids):
            _typed_tuple(value, str)
            if len(set(value)) != len(value):
                raise ValueError("Duplicate coverage identity")
        _typed_tuple(self.expected_inference, InferenceGroup)
        if type(self.skipped) is not tuple or self.skipped or self.native != "empty":
            raise ValueError("Plain prose requires successful inference and empty native code")


def _inference_records(inputs, group, payload):
    spans = {s.id: s for s in inputs.evidence.spans}
    dependencies = tuple(
        ("span", identity, dependency_version(spans[identity])) for identity in group.original_span_ids
    )
    payload_hash = text_hash(canonical_json(payload.model_dump(mode="json")))
    fields = dict(
        generation_id=inputs.generation.id,
        input_kind=group.input_kind,
        input_id=group.input_id,
        input_text_hash=group.input_text_hash,
        support_passage_ids=group.support_passage_ids,
        extractor_profile=group.extractor_profile,
        embedding_profile=inputs.embedding_profile.fingerprint,
        payload=payload,
        payload_hash=payload_hash,
    )
    fingerprint = prose_fingerprint(
        rule_version=PROSE_RULE,
        model_version=group.extractor_profile,
        dependencies=dependencies,
        **{key: value for key, value in fields.items() if key not in ("generation_id", "payload")},
    )
    derived = k.DerivedRecord(
        workspace_id=inputs.evidence.workspace_id,
        view_kind="projection",
        rule_version=PROSE_RULE,
        model_version=group.extractor_profile,
        input_revision_ids=tuple(sorted({spans[i].revision_id for i in group.original_span_ids})),
        dependency_fingerprint=fingerprint,
        state="ready",
    )
    deps = tuple(
        k.DerivedDependency(
            derived_record_id=derived.id, input_kind=kind, input_id=identity, input_version=version
        )
        for kind, identity, version in dependencies
    )
    extraction = k.ProseExtraction(derived_record_id=derived.id, **fields)
    return derived, deps, extraction


def _members(gen_id, records):
    return tuple(
        k.GenerationEvidenceMember(generation_id=gen_id, record_kind=type(r).__name__, record_id=r.id)
        for r in records
    )


@dataclass(frozen=True, slots=True)
class PreparedProseIndex:
    inputs: PlainProseInputs
    dense: tuple[PreparedDensePassage, ...]
    extractions: tuple[k.ProseExtraction, ...]
    derived_records: tuple[k.DerivedRecord, ...]
    derived_dependencies: tuple[k.DerivedDependency, ...]
    evidence_members: tuple[k.GenerationEvidenceMember, ...]
    coverage: ProseCoverage

    def __post_init__(self):
        if type(self.inputs) is not PlainProseInputs or type(self.coverage) is not ProseCoverage:
            raise ValueError("Prepared index requires immutable inputs/coverage")
        for value, kind in (
            (self.dense, PreparedDensePassage),
            (self.extractions, k.ProseExtraction),
            (self.derived_records, k.DerivedRecord),
            (self.derived_dependencies, k.DerivedDependency),
            (self.evidence_members, k.GenerationEvidenceMember),
        ):
            _typed_tuple(value, kind)
        if tuple(r.passage for r in self.dense) != self.inputs.evidence.passages:
            raise ValueError("Dense inventory differs from prepared evidence")
        dimension = self.inputs.embedding_profile.profile.dimension
        for row in self.dense:
            _vector(row.embedding, dimension)
        groups = _groups(self.inputs)
        if len(groups) != len(self.extractions):
            raise ValueError("Mandatory prose extraction coverage is incomplete")
        derived, deps = [], []
        shared_vectors = {}
        for group, extraction in zip(groups, self.extractions, strict=True):
            for row in (*extraction.payload.entities, *extraction.payload.triples):
                _vector(row.embedding, dimension)
                key = (
                    ("entity", row.name)
                    if type(row) is k.ProseEntity
                    else ("fact", row.subject, row.predicate, row.object)
                )
                previous = shared_vectors.setdefault(key, row.embedding)
                if previous != row.embedding:
                    raise ValueError("Conflicting vectors for one source-local entity/fact profile")
            dr, edges, expected = _inference_records(self.inputs, group, extraction.payload)
            if extraction != expected:
                raise ValueError("Extraction identity/provenance differs from exact inference input")
            derived.append(dr)
            deps.extend(edges)
        if tuple(derived) != self.derived_records or tuple(deps) != self.derived_dependencies:
            raise ValueError("Inference derivation closure differs")
        if self.evidence_members != _members(self.inputs.generation.id, self.records):
            raise ValueError("Inference exact membership differs")
        expected = ProseCoverage(
            tuple(r.passage.id for r in self.dense), groups, tuple(e.id for e in self.extractions)
        )
        if self.coverage != expected:
            raise ValueError("Declared coverage differs from complete prepared output")

    @property
    def records(self):
        return (*self.derived_records, *self.derived_dependencies, *self.extractions)


class _Guard:
    def __init__(self, check, should_stop):
        if not callable(check):
            raise ValueError("Live build check is required")
        self.callback, self.should_stop = check, should_stop
        self.lock, self.failure, self.closed = Lock(), None, False

    def fail(self, exc):
        with self.lock:
            if self.failure is None:
                self.failure = exc

    def _latched(self):
        with self.lock:
            failure, closed = self.failure, self.closed
        if failure is not None:
            raise failure
        if closed:
            raise RuntimeError("Preparation is closed")

    def check(self):
        self._latched()
        try:
            self.callback()
            if self.should_stop and self.should_stop():
                raise openie.Stopped("Preparation cancelled")
        except BaseException as exc:
            self.fail(exc)
            raise
        self._latched()


class _Models:
    def __init__(self, inputs, embeddings, chat, guard):
        self.inputs, self.embeddings, self.chat, self.guard = inputs, embeddings, chat, guard

    def validate(self, kind):
        self.guard.check()
        if kind == "embed":
            if (
                validate_profile_descriptor(self.embeddings.resolved.descriptor())
                != self.inputs.embedding_profile
            ):
                raise ValueError("Embedding runtime profile differs")
            self.embeddings.validate()
        else:
            if (
                type(self.chat.profile) is not OpenIEProfile
                or self.chat.profile != self.inputs.extractor_profile
            ):
                raise ValueError("OpenIE runtime profile differs")
            self.chat.validate()
        self.guard.check()

    def embed(self, texts, *, kind):
        try:
            self.validate("embed")
            result = self.embeddings.embed(texts, kind=kind)
            self.validate("embed")
            return result
        except BaseException as exc:
            self.guard.fail(exc)
            raise

    def chat_json(self, messages, schema, *, max_tokens):
        try:
            self.validate("chat")
            result = self.chat.chat_json(
                messages, schema, max_tokens=max_tokens, request_guard=lambda: self.validate("chat")
            )
            self.validate("chat")
            return result
        except BaseException as exc:
            self.guard.fail(exc)
            raise


def prepare_plain_prose(inputs, *, embeddings, chat, check, workers=2, on_progress=None, should_stop=None):
    if type(inputs) is not PlainProseInputs or type(workers) is not int or workers < 1:
        raise ValueError("Expected plain prose inputs and positive worker count")
    guard = _Guard(check, should_stop)
    models = _Models(inputs, embeddings, chat, guard)
    try:
        guard.check()
        models.validate("embed")
        models.validate("chat")
        passages = inputs.evidence.passages
        dense = ()
        if passages:
            vectors = preparation.prepare_passage_vectors(
                models, inputs.generation.source_id, [(p.id, p.to_chunk()) for p in passages]
            ).vectors
            dense = tuple(
                PreparedDensePassage(
                    p, _vector(tuple(v.tolist()), inputs.embedding_profile.profile.dimension)
                )
                for p, v in zip(passages, vectors, strict=True)
            )
        groups = _groups(inputs)
        by_id = {p.id: p for p in passages}
        representatives = [
            (g.support_passage_ids[0], by_id[g.support_passage_ids[0]].to_chunk()) for g in groups
        ]
        results = (
            preparation.extract_chunk_prose(
                models,
                representatives,
                workers=workers,
                on_progress=on_progress,
                should_stop=lambda: guard.check() or False,
            )
            if groups
            else []
        )
        guard.check()
        if [r.passage_id for r in results] != [pid for pid, _ in representatives]:
            raise ValueError("Mandatory prose results are missing, duplicate, or unexpected")
        for result in results:
            if result.error:
                raise ValueError(f"Mandatory prose failed for {result.passage_id}: {result.error}")
            if any(not predicate for _, predicate, _ in result.clean_triples):
                raise ValueError(f"Empty predicate for mandatory prose input {result.passage_id}")
        payloads = preparation.prepare_fact_payloads(results)
        names, triples = payloads.names, payloads.triples

        def embedded(values):
            if not values:
                return ()
            matrix = models.embed(values, kind="document")
            if len(matrix) != len(values):
                raise ValueError("Embedding result inventory differs")
            return tuple(
                _vector(tuple(v.tolist()), inputs.embedding_profile.profile.dimension) for v in matrix
            )

        entities = dict(zip(names, embedded(list(names.values())), strict=True))
        facts = dict(zip(triples, embedded([fact_text(*t) for t in triples.values()]), strict=True))
        records, dependencies, extractions = [], [], []
        for group, result in zip(groups, results, strict=True):
            payload = k.ProseExtractionPayload(
                entities=tuple(
                    k.ProseEntity(name=name, embedding=entities[entity_id(name)])
                    for name in result.entity_names
                ),
                triples=tuple(
                    k.ProseTriple(subject=s, predicate=p, object=o, embedding=facts[fact_id(s, p, o)])
                    for s, p, o in result.clean_triples
                ),
            )
            dr, deps, extraction = _inference_records(inputs, group, payload)
            records.append(dr)
            dependencies.extend(deps)
            extractions.append(extraction)
        result = PreparedProseIndex(
            inputs,
            dense,
            tuple(extractions),
            tuple(records),
            tuple(dependencies),
            _members(inputs.generation.id, (*records, *dependencies, *extractions)),
            ProseCoverage(tuple(p.id for p in passages), groups, tuple(e.id for e in extractions)),
        )
        models.validate("embed")
        models.validate("chat")
        return result
    except BaseException as exc:
        guard.fail(exc)
        raise
    finally:
        with guard.lock:
            guard.closed = True
