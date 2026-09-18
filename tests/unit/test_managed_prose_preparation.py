"""Managed plain-prose computation uses real shared OpenIE with guarded fake HTTP boundaries."""

import importlib
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import numpy as np
import pytest

from hippo import prompts
from hippo.hipporag.text import fact_text
from hippo.knowledge.embedding_profile import EmbeddingSpec, StoredEmbeddingProfile, _fingerprint
from hippo.knowledge.identity import canonical_json
from hippo.knowledge.lifecycle import generation_for_inputs
from tests.unit.test_generation_store import NOW
from tests.unit.test_managed_input_binding import accepted


def api():
    try:
        return importlib.import_module("hippo.knowledge.prose_preparation")
    except ModuleNotFoundError:
        pytest.fail("Managed prose preparation is missing")


def inputs(
    text="ACME builds Robot.", *, source="source", workspace="workspace", policy="policy", parent=None
):
    module = api()
    binding_api = importlib.import_module("hippo.knowledge.input_binding")
    binding, chunks = accepted(binding_api, text, source=source, workspace=workspace, policy=policy)
    spec = EmbeddingSpec(document_prefix="doc:", query_prefix="query:", dimensions=2)
    profile = spec.make_profile("embed:latest", "a" * 64, 2)
    embedding = StoredEmbeddingProfile(profile, spec, _fingerprint(profile))
    extractor = module.OpenIEProfile(wire_model="chat:latest", model_digest="b" * 64, num_ctx=8192)
    configuration = module.prose_configuration(embedding, extractor, allow_empty=not chunks)
    pairs = ((binding.artifact, binding.revision),)
    generation = generation_for_inputs(
        pairs,
        workspace_id=workspace,
        source_id=source,
        parent_id=parent,
        parser_version="plain-v1",
        linker_version="plain-v1",
        embedding_profile=embedding.fingerprint,
        configuration=configuration,
        created_at=NOW,
    )
    evidence = binding_api.materialize_chunk_evidence(
        chunks,
        generation,
        workspace_id=workspace,
        bindings=(binding,),
    )
    return module.PlainProseInputs(
        generation,
        evidence,
        pairs,
        canonical_json(configuration),
        embedding,
        extractor,
    )


class Embeddings:
    def __init__(self, profile):
        self.resolved = profile
        self.calls = []
        self.after = lambda: None

    def validate(self):
        self.after()

    def embed(self, texts, *, kind):
        self.calls.append((tuple(texts), kind))
        self.after()
        return np.asarray([[1.0, 0.0] for text in texts], dtype=np.float32).reshape(-1, 2)


class Chat:
    def __init__(self, profile, triples=None):
        self.profile = profile
        self.calls = []
        self.triples = (
            triples if triples is not None else [["ACME!", "Builds", "Robot"], ["acme", "builds", "robot"]]
        )
        self.after = lambda: None

    def validate(self):
        pass

    def chat_json(self, messages, schema, *, max_tokens, request_guard):
        request_guard()
        self.calls.append((messages, schema, max_tokens))
        self.after()
        request_guard()
        return (
            {"named_entities": ["ACME", "Robot", "NER-only"]}
            if schema == prompts.NER_SCHEMA
            else {"triples": self.triples}
        )


def prepare(value, *, chat=None, embeddings=None, check=lambda: None, **kwargs):
    return api().prepare_plain_prose(
        value,
        chat=chat or Chat(value.extractor_profile),
        embeddings=embeddings or Embeddings(value.embedding_profile),
        check=check,
        workers=1,
        **kwargs,
    )


def test_short_plain_prose_runs_actual_two_stage_openie_and_exact_scoped_embeddings():
    value = inputs()
    chat, embeddings = Chat(value.extractor_profile), Embeddings(value.embedding_profile)
    result = prepare(value, chat=chat, embeddings=embeddings)
    assert [call[2] for call in chat.calls] == [512, 2048]
    assert chat.calls[0][0] == prompts.ner_messages("ACME builds Robot.")
    assert chat.calls[1][0] == prompts.triples_messages("ACME builds Robot.", ["ACME", "Robot", "NER-only"])
    assert embeddings.calls == [
        (("ACME builds Robot.",), "document"),
        (("acme", "robot"), "document"),
        ((fact_text("acme", "builds", "robot"),), "document"),
    ]
    (extraction,) = result.extractions
    assert [row.name for row in extraction.payload.entities] == ["acme", "robot"]
    assert len(extraction.payload.triples) == 1
    assert extraction.support_passage_ids == (value.evidence.passages[0].id,)
    assert result.coverage.successful_extraction_ids == (extraction.id,)
    assert result.coverage.skipped == () and result.coverage.native == "empty"
    assert result.dense[0].native_row()["text"] == "ACME builds Robot."


def test_empty_success_has_real_extraction_but_authoritative_empty_has_no_model_calls():
    value = inputs()
    result = prepare(value, chat=Chat(value.extractor_profile, []))
    assert len(result.extractions) == 1 and result.extractions[0].payload.entities == ()
    empty = inputs("")
    chat, embeddings = Chat(empty.extractor_profile), Embeddings(empty.embedding_profile)
    result = prepare(empty, chat=chat, embeddings=embeddings)
    assert not result.extractions and not result.dense and not chat.calls and not embeddings.calls


@pytest.mark.parametrize("change", ["config", "profile", "revision", "mutable", "duplicates"])
def test_accepted_input_identity_and_immutable_types_are_not_labels(change):
    value = inputs()
    with pytest.raises(ValueError):
        if change == "config":
            replace(
                value,
                configuration_json=value.configuration_json.replace(
                    '"allow_empty":false', '"allow_empty":true'
                ),
            )
        elif change == "profile":
            replace(value, generation=value.generation.replace(embedding_profile="wrong"))
        elif change == "revision":
            a, r = value.artifacts_and_revisions[0]
            replace(value, artifacts_and_revisions=((a, r.replace(content_hash="changed")),))
        elif change == "mutable":
            replace(value, extractor_profile=SimpleNamespace(**value.extractor_profile.descriptor()))
        else:
            replace(value, artifacts_and_revisions=value.artifacts_and_revisions * 2)


@pytest.mark.parametrize("triples", [[["acme", "!!!", "robot"]]])
def test_unrepresentable_empty_predicate_fails_mandatory_coverage(triples):
    value = inputs()
    with pytest.raises(ValueError, match="predicate"):
        prepare(value, chat=Chat(value.extractor_profile, triples))


def test_error_and_revocation_never_become_empty_success():
    value = inputs()
    chat = Chat(value.extractor_profile)
    revoked = False

    def check():
        if revoked:
            raise PermissionError("revoked")

    def revoke():
        nonlocal revoked
        revoked = True

    chat.after = revoke
    with pytest.raises(PermissionError, match="revoked"):
        prepare(value, chat=chat, check=check)
    assert len(chat.calls) == 1


def test_cancellation_before_preparation_sends_nothing():
    value = inputs()
    chat, embeddings = Chat(value.extractor_profile), Embeddings(value.embedding_profile)
    with pytest.raises(Exception, match="stop|cancel"):
        prepare(value, chat=chat, embeddings=embeddings, should_stop=lambda: True)
    assert not chat.calls and not embeddings.calls


@pytest.mark.parametrize("vector", [[1.0], [0.0, 0.0], [float("nan"), 0.0], [2.0, 0.0]])
def test_vectors_must_match_captured_dimension_and_normalization(vector):
    value = inputs()
    embeddings = Embeddings(value.embedding_profile)
    embeddings.embed = lambda texts, **kwargs: np.asarray([vector for text in texts])
    with pytest.raises(ValueError, match="vector|dimension|norm"):
        prepare(value, embeddings=embeddings)


@pytest.mark.parametrize("field", ["extractions", "dense", "derived_dependencies", "evidence_members"])
def test_output_inventory_cannot_omit_required_rows(field):
    result = prepare(inputs())
    with pytest.raises(ValueError):
        replace(result, **{field: ()})


def test_complete_original_heading_closure_and_detached_native_rows():
    result = prepare(inputs("# Title\n\nACME builds Robot.\n"))
    assert len(result.inputs.evidence.spans) == 2
    assert {d.input_id for d in result.derived_dependencies} == {s.id for s in result.inputs.evidence.spans}
    row = result.dense[0].native_row()
    row["embedding"][0] = 99
    assert result.dense[0].embedding == (1.0, 0.0)
    with pytest.raises(FrozenInstanceError):
        result.dense[0].embedding = ()


@pytest.mark.parametrize("which", ["embedding", "chat"])
def test_runtime_profile_drift_after_call_is_rejected(which):
    value = inputs()
    embeddings, chat = Embeddings(value.embedding_profile), Chat(value.extractor_profile)
    if which == "embedding":

        def drift():
            embeddings.resolved = SimpleNamespace(descriptor=lambda: {})

        embeddings.after = drift
    else:
        chat.after = lambda: setattr(chat, "profile", replace(value.extractor_profile, model_digest="c" * 64))
    with pytest.raises(ValueError, match="profile|descriptor"):
        prepare(value, embeddings=embeddings, chat=chat)


def test_same_input_group_runs_once_with_all_declared_supports():
    from hippo.ingest.provenance import RawInput
    from hippo.knowledge.input_binding import AcceptedArtifactBinding, materialize_chunk_evidence

    value = inputs()
    passage = value.evidence.passages[0]
    # The materializer can bind two ordinals of the same exact original input.
    artifact, revision = value.artifacts_and_revisions[0]
    unit = passage.chunk.original_units[0]
    raw = RawInput(
        unit.input_key,
        artifact.external_id,
        "text/plain",
        revision.raw_uri,
        revision.content_hash,
        len(unit.text.encode()),
        revision.provider_revision,
    )
    evidence = materialize_chunk_evidence(
        (passage.chunk, replace(passage.chunk, ordinal=1)),
        value.generation,
        workspace_id=value.evidence.workspace_id,
        bindings=(AcceptedArtifactBinding(raw, artifact, revision),),
    )
    value = replace(value, evidence=evidence)
    chat = Chat(value.extractor_profile)
    result = prepare(value, chat=chat)
    assert len(chat.calls) == 2 and len(result.dense) == 2 and len(result.extractions) == 1
    assert set(result.extractions[0].support_passage_ids) == {p.id for p in evidence.passages}


def test_missing_or_duplicate_shared_extraction_results_fail(monkeypatch):
    from hippo.hipporag import preparation

    original = preparation.extract_chunk_prose
    for duplicate in (False, True):

        def incomplete(*args, duplicate=duplicate, **kwargs):
            results = original(*args, **kwargs)
            return results * 2 if duplicate else []

        monkeypatch.setattr(preparation, "extract_chunk_prose", incomplete)
        with pytest.raises(ValueError, match="missing|duplicate"):
            prepare(inputs())


def test_manifest_revision_participates_in_generation_identity_and_exact_membership():
    from hippo.knowledge import model as k

    value = inputs()
    original, _ = value.artifacts_and_revisions[0]
    manifest = k.Artifact(
        workspace_id=original.workspace_id,
        source_id=original.source_id,
        kind="manifest",
        external_id="accepted-inputs",
        canonical_uri="source:accepted-inputs",
        policy_id=original.policy_id,
    )
    revision = k.ArtifactRevision(
        artifact_id=manifest.id,
        content_hash="manifest-hash",
        raw_uri="raw:manifest",
        observed_at=NOW,
        lifecycle="active",
    )
    pairs = (*value.artifacts_and_revisions, (manifest, revision))
    import json

    generation = generation_for_inputs(
        pairs,
        workspace_id=original.workspace_id,
        source_id=original.source_id,
        parent_id=None,
        parser_version=value.generation.parser_version,
        linker_version=value.generation.linker_version,
        embedding_profile=value.embedding_profile.fingerprint,
        configuration=json.loads(value.configuration_json),
        created_at=NOW,
    )
    assert generation.id != value.generation.id
    # No chunk/source identity changes; physical passage IDs and exact members do.
    binding_api = importlib.import_module("hippo.knowledge.input_binding")
    binding, chunks = accepted(binding_api, "ACME builds Robot.")
    evidence = binding_api.materialize_chunk_evidence(
        chunks, generation, workspace_id=original.workspace_id, bindings=(binding,)
    )
    evidence = replace(
        evidence,
        revision_members=(
            *evidence.revision_members,
            k.GenerationMember(generation_id=generation.id, artifact_revision_id=revision.id),
        ),
    )
    result = prepare(replace(value, generation=generation, evidence=evidence, artifacts_and_revisions=pairs))
    assert len(result.inputs.evidence.revision_members) == 2


def test_cross_extraction_conflicting_entity_vectors_are_rejected():
    from hippo.knowledge import model as k

    value = inputs("ACME builds Robot.\n\n" * 12)
    result = prepare(value)
    assert len(result.extractions) > 1
    extractions = list(result.extractions)
    payload = extractions[1].payload
    payload = k.ProseExtractionPayload(
        entities=tuple(row.model_copy(update={"embedding": (0.0, 1.0)}) for row in payload.entities),
        triples=payload.triples,
    )
    records, deps, replacement = api()._inference_records(
        value, result.coverage.expected_inference[1], payload
    )
    extractions[1] = replacement
    derived = tuple(records if i == 1 else dr for i, dr in enumerate(result.derived_records))
    dependencies = (
        tuple(d for d in result.derived_dependencies if d.derived_record_id != result.derived_records[1].id)
        + deps
    )
    # Build the expected ordered dependency groups for the changed payload.
    dependencies = tuple(d for dr in derived for d in dependencies if d.derived_record_id == dr.id)
    all_records = (*derived, *dependencies, *extractions)
    coverage = replace(result.coverage, successful_extraction_ids=tuple(e.id for e in extractions))
    with pytest.raises(ValueError, match="Conflicting|conflicting"):
        replace(
            result,
            extractions=tuple(extractions),
            derived_records=derived,
            derived_dependencies=dependencies,
            evidence_members=api()._members(value.generation.id, all_records),
            coverage=coverage,
        )


def test_inflight_call_cannot_dispatch_next_phase_after_preparation_closes():
    from threading import Event

    value = inputs("A" * 90 + "\n\n" + "B" * 90)
    slow_entered, release, slow_finished = Event(), Event(), Event()

    class BlockingChat(Chat):
        def chat_json(self, messages, schema, *, max_tokens, request_guard):
            request_guard()
            self.calls.append((messages, schema, max_tokens))
            if schema == prompts.NER_SCHEMA and messages[-1]["content"].startswith("B"):
                slow_entered.set()
                try:
                    assert release.wait(5)
                    request_guard()
                finally:
                    slow_finished.set()
            elif schema == prompts.NER_SCHEMA:
                assert slow_entered.wait(5)
            request_guard()
            return {"named_entities": []} if schema == prompts.NER_SCHEMA else {"triples": []}

    chat = BlockingChat(value.extractor_profile)

    def fail_progress(*args):
        raise RuntimeError("progress failed")

    try:
        with pytest.raises(RuntimeError, match="progress failed"):
            api().prepare_plain_prose(
                value,
                embeddings=Embeddings(value.embedding_profile),
                chat=chat,
                check=lambda: None,
                workers=2,
                on_progress=fail_progress,
            )
    finally:
        release.set()
    assert slow_finished.wait(5)
    assert len(chat.calls) == 3  # slow NER and fast NER+triples; no late slow triples


def test_profile_cannot_retain_mutable_value_that_compares_like_supported_version():
    class PretendsVersion:
        def __eq__(self, other):
            return True

    with pytest.raises(ValueError):
        replace(inputs().extractor_profile, normalization_version=PretendsVersion())


@pytest.mark.parametrize("prose", [None, [], "prose"])
def test_configuration_requires_prose_object(prose):
    import json

    value = inputs()
    config = json.loads(value.configuration_json)
    config["prose"] = prose
    with pytest.raises(ValueError, match="configuration|Configuration|prose"):
        replace(value, configuration_json=canonical_json(config))


@pytest.mark.parametrize("fail", [False, True])
def test_guard_rechecks_sticky_close_after_blocking_predispatch_callback(fail):
    from threading import Event, Thread

    value = inputs()
    entered, release = Event(), Event()
    checks = 0

    def check():
        nonlocal checks
        checks += 1
        if checks == 2:
            entered.set()
            assert release.wait(5)

    guard = api()._Guard(check, None)
    embeddings = Embeddings(value.embedding_profile)
    models = api()._Models(value, embeddings, Chat(value.extractor_profile), guard)
    errors = []

    def invoke():
        try:
            models.embed(["private input"], kind="document")
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=invoke)
    thread.start()
    try:
        assert entered.wait(5)
        if fail:
            guard.fail(PermissionError("revoked"))
        else:
            with guard.lock:
                guard.closed = True
    finally:
        release.set()
        thread.join(5)
    assert errors and not thread.is_alive()
    assert not embeddings.calls
