"""Pure local-file preparation binds to strict schema-5 originals and views."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from hashlib import sha256
from importlib import import_module
from types import SimpleNamespace

import pytest

from hippo.ingest.prepared_chunks import prepare_prose_chunks
from hippo.ingest.provenance import RawInput, read_plain_provenance
from hippo.knowledge import model as k
from hippo.knowledge.derivations import dependency_version, validate_view
from hippo.knowledge.lifecycle import generation_passage_id
from tests.unit.test_generation_store import NOW, authority, claim, generation, publish, seal


@pytest.fixture
def api():
    return import_module("hippo.knowledge.input_binding")


def test_materializer_api_exists():
    from importlib.util import find_spec

    assert find_spec("hippo.knowledge.input_binding") is not None, "pure input materializer is missing"


def accepted(
    api, text, *, source="source", workspace="workspace", path="notes.md", policy="policy", size=100
):
    data = text.encode()
    digest = sha256(data).hexdigest()
    raw = RawInput(
        api.local_input_key(workspace_id=workspace, source_id=source, logical_path=path),
        path,
        "text/plain",
        "hippo-raw:sha256:" + digest,
        digest,
        len(data),
        "provider-v1",
    )
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=source,
        kind="file",
        external_id=path,
        canonical_uri=f"source:{source}/{path}",
        policy_id=policy,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        provider_revision=raw.provider_revision,
        content_hash=digest,
        raw_uri=raw.raw_uri,
        observed_at=NOW,
        lifecycle="active",
    )
    binding = api.AcceptedArtifactBinding(raw, artifact, revision)
    docs = read_plain_provenance(raw, data).documents
    return binding, prepare_prose_chunks(docs, size_chars=size, overlap_chars=0)


def gen(source="source"):
    return k.Generation(
        source_id=source,
        status="staging",
        parser_version="reader-v1",
        linker_version="1",
        embedding_profile="p",
        created_at=NOW,
        manifest_hash="accepted",
    )


def materialize(api, binding, chunks, generation=None):
    return api.materialize_chunk_evidence(
        chunks,
        generation or gen(binding.artifact.source_id),
        workspace_id=binding.artifact.workspace_id,
        bindings=(binding,),
    )


def test_exact_original_preserves_existing_native_identity_and_extraction_input(api):
    binding, chunks = accepted(api, "Exactly original.")
    built = materialize(api, binding, chunks)
    assert len(built.spans) == len(built.passages) == len(built.extraction_inputs) == 1
    assert not built.views and not built.derived_records and not built.derived_dependencies
    span, passage, extraction = built.spans[0], built.passages[0], built.extraction_inputs[0]
    assert span.text == "Exactly original."
    assert passage.id == generation_passage_id(gen().id, binding.revision.id, span.id, 0)
    assert passage.retrieval_view_id is None
    assert passage.to_chunk() == chunks[0].to_chunk()
    row = passage.native_row()
    assert "embedding" not in row
    assert row["span_id"] == span.id and row["text"] == span.text
    row["text"] = "changed"
    assert passage.native_row()["text"] == span.text
    assert extraction.input_kind == "span" and extraction.input_id == span.id
    assert extraction.input_version == dependency_version(span)
    assert extraction.original_span_ids == (span.id,)
    assert extraction.support_passage_ids == (passage.id,)
    assert extraction.text == span.text and extraction.input_text_hash == span.text_hash


def test_trim_heading_and_hardcuts_bind_honest_originals_with_distinct_views(api):
    binding, chunks = accepted(api, "\ufeff\r\n# Title\r\n\r\n" + "x" * 120 + "\r\n ", size=50)
    built = materialize(api, binding, chunks)
    assert len(built.passages) == len(built.views) == 3
    assert len(built.spans) == 2  # title and one full long line, shared by all cuts
    assert {span.text for span in built.spans} == {"# Title\r\n", "x" * 120 + "\r\n"}
    assert len({view.id for view in built.views}) == 3
    assert all(p.retrieval_view_id for p in built.passages)
    assert all(set(e.original_span_ids) == {s.id for s in built.spans} for e in built.extraction_inputs)
    assert all(e.input_kind == "view" for e in built.extraction_inputs)
    assert all(v.vector_profile == "p" for v in built.views)
    assert binding.revision.metadata_json == "{}"
    assert all(record.model_version is None for record in built.derived_records)
    assert not any(type(record) is k.ProseExtraction for record in built.records)
    assert built == materialize(api, binding, chunks)


def test_members_are_exact_and_original_span_dedup_is_generation_independent(api):
    binding, chunks = accepted(api, "word " * 40, size=50)
    one = materialize(api, binding, chunks)
    two = materialize(api, binding, chunks, gen().replace(parent_id="parent", manifest_hash="next"))
    assert one.spans == two.spans
    assert {p.id for p in one.passages}.isdisjoint(p.id for p in two.passages)
    assert {(m.record_kind, m.record_id) for m in one.evidence_members} == {
        (type(r).__name__, r.id) for r in one.records
    }
    assert len(one.evidence_members) == len(one.records)
    assert one.revision_members == (
        k.GenerationMember(generation_id=gen().id, artifact_revision_id=binding.revision.id),
    )


@pytest.mark.parametrize(
    "change", ["hash", "uri", "provider", "path", "scope_key", "artifact", "container", "remote", "mutable"]
)
def test_invalid_accepted_binding_rejects(api, change):
    binding, _ = accepted(api, "original")
    with pytest.raises(ValueError):
        if change == "hash":
            replace(binding, revision=binding.revision.replace(content_hash="foreign"))
        elif change == "uri":
            replace(binding, revision=binding.revision.replace(raw_uri="other:uri"))
        elif change == "provider":
            replace(binding, revision=binding.revision.replace(provider_revision="changed"))
        elif change == "path":
            replace(binding, raw_input=replace(binding.raw_input, logical_path="other.txt"))
        elif change == "scope_key":
            replace(binding, raw_input=replace(binding.raw_input, input_key="unscoped"))
        elif change == "artifact":
            replace(binding, revision=binding.revision.replace(artifact_id="other"))
        elif change == "container":
            replace(binding, raw_input=replace(binding.raw_input, container_chain=("archive.zip",)))
        elif change == "remote":
            replace(
                binding,
                artifact=binding.artifact.replace(
                    connector_id="remote", provider_instance="https://example.com"
                ),
            )
        else:
            replace(
                binding,
                raw_input=SimpleNamespace(
                    **{name: getattr(binding.raw_input, name) for name in binding.raw_input.__slots__}
                ),
            )


@pytest.mark.parametrize(
    "change", ["source", "workspace", "active", "missing", "duplicates", "ordinal", "unit"]
)
def test_materializer_rejects_foreign_or_inconsistent_inventory(api, change):
    binding, chunks = accepted(api, "one " * 50, size=50)
    with pytest.raises(ValueError):
        if change == "source":
            materialize(api, binding, chunks, gen("other"))
        elif change == "workspace":
            api.materialize_chunk_evidence(chunks, gen(), workspace_id="other", bindings=(binding,))
        elif change == "active":
            materialize(api, binding, chunks, gen().replace(status="active", published_at=NOW))
        elif change == "missing":
            api.materialize_chunk_evidence(chunks, gen(), workspace_id="workspace", bindings=())
        elif change == "duplicates":
            api.materialize_chunk_evidence(
                chunks, gen(), workspace_id="workspace", bindings=(binding, binding)
            )
        elif change == "ordinal":
            materialize(api, binding, (chunks[0], chunks[0]))
        else:
            unit = chunks[0].original_units[0]
            changed = replace(unit, unit_key="foreign")
            fake_chunk = SimpleNamespace(original_units=(changed,))
            materialize(api, binding, (fake_chunk,))


def test_empty_input_is_inventory_without_fabricated_evidence(api):
    binding, chunks = accepted(api, " \r\n ")
    built = materialize(api, binding, chunks)
    assert built.records == built.passages == built.extraction_inputs == ()
    assert len(built.revision_members) == 1


def test_materialized_values_are_immutable(api):
    binding, chunks = accepted(api, "text")
    result = materialize(api, binding, chunks)
    with pytest.raises(FrozenInstanceError):
        result.passages = ()
    with pytest.raises(ValueError):
        replace(result, passages=(SimpleNamespace(id="foreign"),))
    with pytest.raises(ValueError):
        replace(result.extraction_inputs[0], support_passage_ids=[[]])


@pytest.mark.parametrize("text", ["Exactly original.", "# Title\n\nChosen body.\nsecond line"])
def test_strict_store_seals_and_projects_prepared_originals(store, api, text):
    from tests.unit.test_derived_projection import project

    generation_row = generation(store)
    workspace = store.get_source(generation_row.source_id)["workspace_id"]
    policy = k.AccessPolicy(workspace_id=workspace, mode="workspace", verified_at=NOW)
    binding, chunks = accepted(
        api, text, source=generation_row.source_id, workspace=workspace, policy=policy.id
    )
    result = materialize(api, binding, chunks, generation_row)
    job = claim(store, generation_row)
    with store.generation_write(generation_row.id, **authority(job)):
        for record in (
            policy,
            binding.artifact,
            binding.revision,
            *result.revision_members,
            *result.records,
            *result.evidence_members,
        ):
            store.put_knowledge(record)
        store.add_passages([{**passage.native_row(), "embedding": [1.0, 0.0]} for passage in result.passages])
    for view in result.views:
        assert validate_view(store, generation_row.id, view).span_ids == frozenset(s.id for s in result.spans)
    seal(store, generation_row, job)
    publish(store, generation_row, job)
    graph = project(store, generation_row)
    assert [p.text for p in graph.passages] == [c.text for c in chunks]
    assert {c.text for c in graph.original_citations} == {s.text for s in result.spans}
    assert not graph.facts and not graph.entity_names
    if result.views:
        title = next(span for span in result.spans if span.text.startswith("# Title"))
        store.put_knowledge(
            k.Suppression(
                workspace_id=workspace,
                target_kind="span",
                target_id=title.id,
                scope_key="input-binding-review",
                created_at=NOW,
                reason="access_loss",
                view_applicability="all_history",
                epoch=1,
                restoration_barrier="review",
            )
        )
        hidden = project(store, generation_row)
        assert not hidden.passages and not hidden.original_citations


def test_extraction_cannot_drop_a_title_original_from_its_proof(api):
    binding, chunks = accepted(api, "# Title\n\nBody.")
    result = materialize(api, binding, chunks)
    extraction = replace(result.extraction_inputs[0], original_span_ids=(result.spans[-1].id,))
    with pytest.raises(ValueError):
        replace(result, extraction_inputs=(extraction,))


def test_bound_evidence_rejects_an_incomplete_derived_dependency_group(api):
    binding, chunks = accepted(api, "# Title\n\nBody.")
    result = materialize(api, binding, chunks)
    omitted = result.derived_dependencies[0]
    with pytest.raises(ValueError):
        replace(
            result,
            derived_dependencies=result.derived_dependencies[1:],
            evidence_members=tuple(
                member for member in result.evidence_members if member.record_id != omitted.id
            ),
        )


def test_real_immutable_unit_with_wrong_reader_identity_rejects(api):
    binding, chunks = accepted(api, "text")
    chunk = chunks[0]
    unit = replace(chunk.original_units[0], input_key="different-input")
    altered = replace(chunk, original_units=(unit,))
    with pytest.raises(ValueError):
        materialize(api, binding, (altered,))


@pytest.mark.parametrize(
    "change",
    [
        "missing_revision",
        "duplicate_revision",
        "duplicate_passage",
        "active_generation",
        "generation_mismatch",
        "multiple_units",
    ],
)
def test_output_contract_rejects_lost_membership_and_duplicate_or_stale_passages(api, change):
    binding, chunks = accepted(api, "one " * 50, size=50)
    result = materialize(api, binding, chunks)
    with pytest.raises(ValueError):
        if change == "missing_revision":
            replace(result, revision_members=())
        elif change == "duplicate_revision":
            replace(result, revision_members=result.revision_members * 2)
        elif change == "duplicate_passage":
            replace(
                result,
                passages=result.passages + result.passages[:1],
                extraction_inputs=result.extraction_inputs + result.extraction_inputs[:1],
            )
        elif change == "active_generation":
            passage = result.passages[0]
            replace(passage, generation=passage.generation.replace(status="active", published_at=NOW))
        elif change == "generation_mismatch":
            passage = result.passages[0]
            changed = replace(
                passage, generation=passage.generation.replace(created_at=NOW + timedelta(seconds=1))
            )
            replace(result, passages=(changed, *result.passages[1:]))
        else:
            passage = result.passages[0]
            unit = passage.chunk.original_units[0]
            changed = replace(passage.chunk, original_units=(unit, replace(unit, unit_key="extra")))
            replace(passage, chunk=changed)


def test_zero_text_accepted_revision_remains_in_mixed_inventory(api):
    binding, chunks = accepted(api, "Text.")
    empty, no_chunks = accepted(api, " \n ", path="empty.txt")
    result = api.materialize_chunk_evidence(
        chunks + no_chunks, gen(), workspace_id="workspace", bindings=(binding, empty)
    )
    assert {member.artifact_revision_id for member in result.revision_members} == {
        binding.revision.id,
        empty.revision.id,
    }
    assert len(result.passages) == len(result.spans) == 1
