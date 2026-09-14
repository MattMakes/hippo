"""Code evidence and object binding: the plan's section 4 inventory, closed exactly.

One code generation's captured files and mapped passages become artifacts, revisions,
original spans, rendered views, knowledge objects, observations, namespaced native rows
and bindings -- with nothing invented, nothing duplicated and no orphan binding. Gate
CD5. Pure: no persistence handle, no model client, no clock beyond the injected instant.

Every fixture follows the plan's section 6 order, because the code graph's native IDs are
namespaced by the generation while generation identity does not depend on the graph:
capture, settle the generation, extract under its namespace, chunk, then bind.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from zipfile import ZipFile

import pytest

from hippo.codegraph.extract import extract_code
from hippo.codegraph.model import DATA_KINDS, CodeGraph, data_id, symbol_id
from hippo.ingest.code_provenance import read_code_provenance
from hippo.ingest.prepared_code_chunks import CapturedCode, CodeChunkSettings, prepare_code_chunks
from hippo.ingest.repo_capture import capture_repository_inputs, repository_descriptor
from hippo.knowledge import model as k
from hippo.knowledge.identity import canonical_json, make_identity, repository_key, symbol_key
from hippo.knowledge.inputs import MANIFEST_EXTERNAL_ID, CaptureLimits, RawInput
from hippo.knowledge.lifecycle import generation_namespace, generation_passage_id
from hippo.knowledge.raw_artifacts import RawArtifactStore

INSTANT = datetime(2026, 9, 12, 8, 30, tzinfo=UTC)
WORKSPACE = "workspace-cc6"
SOURCE = "source-cc6"
OTHER_SOURCE = "source-cc6-other"
POLICY = "policy-cc6"
CLONE_URL = "https://git.example.com/acme/robots.git"
REPOSITORY_INSTANCE = "https://git.example.com"
REPOSITORY_ID = "acme/robots"
HEAD = "4f1d2c8a9b7e6f5d4c3b2a1908f7e6d5c4b3a291"
OTHER_HEAD = "aaaa2c8a9b7e6f5d4c3b2a1908f7e6d5c4b3a291"

ORDERS = """\
\"\"\"Order handling.\"\"\"

import os


class OrderService:
    \"\"\"Places orders, and keeps a long enough docstring to be worth extracting here.\"\"\"

    def place(self, order):
        total = order.total
        return total

    def save(self, order):
        return os.stat(order.path)


def helper(value):
    return value + 1
"""

SCHEMA = "CREATE TABLE orders (\n  id INT\n);\n\nSELECT id FROM orders;\n"

READ_ME = "Acme\n\nA paragraph about the project.\n\nAnother paragraph about it.\n"

OVERLOADS = """\
namespace Acme
{
    public class Robot
    {
        public int Move(int steps) { return steps; }

        public int Move(string steps) { return 1; }
    }
}
"""


def _long_move(parameter):
    body = "\n".join(
        f"            total += {n}; // long enough that the method splits into windows" for n in range(60)
    )
    return f"        public int Move({parameter} steps)\n        {{\n            var total = 0;\n{body}\n            return total;\n        }}"


# The same two overloads, each longer than one 1500-character window, so each is split into windows
# that all name the one native ID the overloads share.
LONG_OVERLOADS = (
    "namespace Acme\n{\n    public class Robot\n    {\n"
    + "\n\n".join(_long_move(parameter) for parameter in ("int", "string"))
    + "\n    }\n}\n"
)

TREE = {"src/orders.py": ORDERS.encode(), "db/schema.sql": SCHEMA.encode()}


@pytest.fixture
def api():
    return import_module("hippo.knowledge.code_binding")


@pytest.fixture
def raw_store(tmp_path):
    return RawArtifactStore(tmp_path / "raw", max_object_bytes=2_000_000)


# ------------------------------------------------------------------ helpers


def limits(**changes):
    return CaptureLimits(
        **(
            {
                "max_input_bytes": 200_000,
                "max_total_bytes": 2_000_000,
                "max_inputs": 200,
                "max_manifest_bytes": 200_000,
            }
            | changes
        )
    )


def tree(root: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def capture(raw_store, root, **changes):
    args = {
        "raw_store": raw_store,
        "source_id": SOURCE,
        "workspace_id": WORKSPACE,
        "limits": limits(),
        "configuration": {"chunker": {"size": 1500}},
        "observed_at": INSTANT,
        "provider_revision": HEAD,
        "repository": repository_descriptor(CLONE_URL),
    }
    args.update(changes)
    return capture_repository_inputs(root, **args)


def units_of(captured, raw_store):
    """Re-read every accepted input from the captured raw object, as the coordinator will."""
    out = []
    for raw in captured.accepted.inputs:
        data = raw_store.read_bytes(raw.raw_artifact)
        out.append(CapturedCode(raw, read_code_provenance(raw, data, name=raw.logical_path)))
    return out


def loose(data: bytes, path: str) -> CapturedCode:
    """A decoded file that belongs to no accepted inventory."""
    digest = sha256(data).hexdigest()
    raw = RawInput(
        input_key="raw-input:" + path,
        logical_path=path,
        media_type="text/plain",
        raw_uri="hippo-raw:sha256:" + digest,
        raw_hash=digest,
        byte_length=len(data),
    )
    return CapturedCode(raw, read_code_provenance(raw, data, name=path))


def chunks_of(units, *, facts, size=1500, overlap=150):
    return prepare_code_chunks(
        units,
        facts=facts,
        settings=CodeChunkSettings(size_chars=size, overlap_chars=overlap),
        max_chunks=20_000,
    )


def identity_inputs(api, **changes):
    args = {
        "parent_id": None,
        "parser_version": "managed-code-v1",
        "linker_version": "managed-code-linker-v1",
        "embedding_profile": "embed-profile-fingerprint",
        "configuration": {"walker": {"rules": "walker-v1"}},
        "policy_id": POLICY,
    }
    args.update(changes)
    return api.CodeGenerationInputs(**args)


def bind(api, captured, prepared, facts, *, source_id=SOURCE, **changes):
    args = {
        "workspace_id": WORKSPACE,
        "source_id": source_id,
        "generation_identity_inputs": identity_inputs(api),
        "observed_at": INSTANT,
    }
    args.update(changes)
    return api.materialize_code_evidence(captured, prepared, facts, **args)


def prepared_of(api, raw_store, captured, *, source_id=SOURCE, size=1500, overlap=150, extra=()):
    """Settle identity, extract under its namespace, then chunk (plan section 6)."""
    generation = api.code_generation(
        captured,
        workspace_id=WORKSPACE,
        source_id=source_id,
        generation_identity_inputs=identity_inputs(api),
        observed_at=INSTANT,
    )
    units = [*units_of(captured, raw_store), *extra]
    facts = extract_code(
        [item.unit.to_document() for item in units if item.unit],
        source_id,
        node_namespace=generation_namespace(generation),
    )
    return chunks_of(units, facts=facts, size=size, overlap=overlap), facts


def bundle_of(api, raw_store, root, *, files=None, source_id=SOURCE, **capture_changes):
    captured = capture(
        raw_store,
        tree(root, files if files is not None else TREE),
        source_id=source_id,
        **capture_changes,
    )
    prepared, facts = prepared_of(api, raw_store, captured, source_id=source_id)
    return bind(api, captured, prepared, facts, source_id=source_id), captured, prepared, facts


def spans_by_id(bundle):
    return {span.id: span for span in bundle.spans}


def path_of(bundle, span):
    for item in bundle.accepted:
        if item.revision.id == span.revision_id:
            return item.logical_path
    return None


# ------------------------------------------------------------------ purity


def test_the_code_binding_module_exists():
    from importlib.util import find_spec

    assert find_spec("hippo.knowledge.code_binding") is not None, "code evidence binding is missing"


def test_the_module_holds_no_store_model_or_clock(api):
    text = Path(api.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "datetime.now",
        "utcnow",
        "time.time",
        "import time",
        "Ollama",
        "ctx.store",
        "AppContext",
        "_now(",
        "embed_texts",
    ):
        assert forbidden not in text, f"pure binding must not reach for {forbidden}"


def test_the_module_imports_no_ingest_module():
    """Ruled option B: this boundary validates structurally and stays above ingest."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, hippo.knowledge.code_binding\n"
            "print([n for n in sys.modules if n.startswith('hippo.ingest')])\n",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "[]", result.stdout


def test_the_rule_versions_are_frozen_and_travel_with_the_bundle(api, raw_store, tmp_path):
    assert api.CODE_BINDING_RULE_VERSION == "code-binding-v1"
    assert api.EXPECTED_CODE_CHUNK_RULE_VERSION == "code-chunks-v1"
    bundle, _, prepared, _ = bundle_of(api, raw_store, tmp_path / "repo")
    assert bundle.rule_version == api.CODE_BINDING_RULE_VERSION
    assert bundle.chunk_rule_version == prepared.rule_version
    with pytest.raises(FrozenInstanceError):
        bundle.rule_version = "other"


def test_the_same_inputs_twice_produce_a_byte_identical_bundle(api, raw_store, tmp_path):
    first, captured, prepared, facts = bundle_of(api, raw_store, tmp_path / "repo")
    assert first == bind(api, captured, prepared, facts)


# ------------------------------------------------------------- accepted inputs


def test_every_accepted_file_becomes_one_local_artifact_and_revision(api, raw_store, tmp_path):
    bundle, captured, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    accepted = {item.raw_input.logical_path: item for item in bundle.accepted}
    assert sorted(accepted) == ["db/schema.sql", "src/orders.py"]
    for raw in captured.accepted.inputs:
        item = accepted[raw.logical_path]
        assert item.artifact.kind == "file"
        assert (item.artifact.workspace_id, item.artifact.source_id) == (WORKSPACE, SOURCE)
        assert item.artifact.external_id == raw.logical_path
        assert item.artifact.canonical_uri == f"source:{SOURCE}/{raw.logical_path}"
        assert item.artifact.policy_id == POLICY
        assert item.artifact.connector_id is None and item.artifact.provider_instance is None
        assert item.artifact.id == make_identity("artifact", [WORKSPACE, SOURCE, "file", raw.logical_path])
        assert (item.revision.content_hash, item.revision.raw_uri) == (raw.raw_hash, raw.raw_uri)
        assert item.revision.provider_revision == raw.provider_revision
        assert item.revision.observed_at == INSTANT
        assert item.revision.source_updated_at is None
        assert item.revision.lifecycle == "active"


def test_the_repository_artifact_carries_the_full_clone_path_and_the_head_sha(api, raw_store, tmp_path):
    bundle, captured, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    artifact, revision = bundle.repository_artifact, bundle.repository_revision
    assert artifact.kind == "repository"
    assert artifact.external_id == f"{REPOSITORY_INSTANCE}/{REPOSITORY_ID}"
    assert artifact.connector_id is None and artifact.provider_instance is None
    assert revision.provider_revision == HEAD
    assert (revision.content_hash, revision.raw_uri) == (
        captured.accepted.manifest.sha256,
        captured.accepted.manifest.uri,
    )
    assert revision.observed_at == INSTANT and revision.lifecycle == "active"


def test_a_tree_with_no_clone_url_gets_a_source_scoped_tree_artifact(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo", repository=None, provider_revision=None)
    assert bundle.repository_artifact.kind == "repository"
    assert bundle.repository_artifact.external_id == f"source:{SOURCE}"
    assert bundle.repository_revision.provider_revision is None
    assert json.loads(bundle.repository_object.canonical_key) == [f"source:{SOURCE}"]


def test_the_accepted_manifest_is_its_own_artifact_and_revision(api, raw_store, tmp_path):
    bundle, captured, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    artifact, revision = bundle.manifest_artifact, bundle.manifest_revision
    assert artifact.kind == "manifest" and artifact.external_id == MANIFEST_EXTERNAL_ID
    assert artifact.id == make_identity("artifact", [WORKSPACE, SOURCE, "manifest", MANIFEST_EXTERNAL_ID])
    assert revision.provider_revision is None
    assert revision.content_hash == captured.accepted.manifest.sha256
    assert json.loads(revision.metadata_json) == {
        "accepted_manifest_v1": json.loads(captured.accepted.manifest_bytes)
    }


def test_every_accepted_revision_is_a_generation_member_exactly_once(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    members = [member.artifact_revision_id for member in bundle.revision_members]
    expected = [
        bundle.repository_revision.id,
        bundle.manifest_revision.id,
        *(item.revision.id for item in bundle.accepted),
    ]
    assert sorted(members) == sorted(expected)
    assert len(members) == len(set(members))
    assert all(member.generation_id == bundle.generation_id for member in bundle.revision_members)
    assert bundle.accepted_pairs[0] == (bundle.repository_artifact, bundle.repository_revision)


# --------------------------------------------------------------- generation


def test_the_generation_is_settled_before_extraction_from_the_tree_alone(api, raw_store, tmp_path):
    """The namespace the walkers need comes from a generation the graph cannot influence."""
    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    settled = api.code_generation(
        captured,
        workspace_id=WORKSPACE,
        source_id=SOURCE,
        generation_identity_inputs=identity_inputs(api),
        observed_at=INSTANT,
    )
    prepared, facts = prepared_of(api, raw_store, captured)
    bundle = bind(api, captured, prepared, facts)
    assert bundle.generation == settled
    assert generation_namespace(bundle.generation) == generation_namespace(settled)


def test_the_configuration_records_the_two_rule_versions_under_one_reserved_key(api, raw_store, tmp_path):
    bundle, _, prepared, _ = bundle_of(api, raw_store, tmp_path / "repo")
    assert bundle.configuration[api.CODE_BINDING_CONFIGURATION_KEY] == {
        "binding": api.CODE_BINDING_RULE_VERSION,
        "chunker": prepared.rule_version,
    }
    assert bundle.configuration["walker"] == {"rules": "walker-v1"}


def test_a_changed_binding_rule_version_is_a_different_generation(api, raw_store, tmp_path, monkeypatch):
    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    settled = api.code_generation(
        captured,
        workspace_id=WORKSPACE,
        source_id=SOURCE,
        generation_identity_inputs=identity_inputs(api),
        observed_at=INSTANT,
    )
    monkeypatch.setattr(api, "CODE_BINDING_RULE_VERSION", "code-binding-v2")
    other = api.code_generation(
        captured,
        workspace_id=WORKSPACE,
        source_id=SOURCE,
        generation_identity_inputs=identity_inputs(api),
        observed_at=INSTANT,
    )
    assert other.id != settled.id and other.manifest_hash != settled.manifest_hash


def test_a_caller_configuration_that_already_claims_the_reserved_key_refuses(api, raw_store, tmp_path):
    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    prepared, facts = prepared_of(api, raw_store, captured)
    with pytest.raises(ValueError, match="reserved"):
        bind(
            api,
            captured,
            prepared,
            facts,
            generation_identity_inputs=identity_inputs(
                api, configuration={api.CODE_BINDING_CONFIGURATION_KEY: {"binding": "mine"}}
            ),
        )


def test_two_captures_at_different_head_shas_are_different_generations(api, raw_store, tmp_path):
    first, _, _, _ = bundle_of(api, raw_store, tmp_path / "one")
    second, _, _, _ = bundle_of(api, raw_store, tmp_path / "two", provider_revision=OTHER_HEAD)
    assert first.generation.manifest_hash != second.generation.manifest_hash
    assert first.generation_id != second.generation_id


def test_the_generation_is_staging_and_takes_the_injected_instant(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    assert bundle.generation.status == "staging"
    assert bundle.generation.created_at == INSTANT
    assert bundle.generation.published_at is None
    assert bundle.generation.coverage_json == "{}"
    assert bundle.generation.parser_version == "managed-code-v1"
    assert bundle.generation.embedding_profile == "embed-profile-fingerprint"


# ------------------------------------------------------------ originals/views


def test_every_cited_original_line_range_becomes_one_span_with_real_locators(api, raw_store, tmp_path):
    bundle, _, prepared, _ = bundle_of(api, raw_store, tmp_path / "repo")
    revisions = {item.logical_path: item for item in bundle.accepted}
    expected = {bundle.repository_span.id: bundle.repository_span}
    for chunk in prepared.chunks:
        if chunk.kind == "commit":
            continue
        item = revisions[chunk.logical_path]
        for original in chunk.originals:
            span = k.EvidenceSpan(
                revision_id=item.revision.id,
                locator_kind="file_lines",
                locator_json=canonical_json(original.lines.locator.model_dump(mode="json")),
                text=original.lines.text,
                policy_id=POLICY,
            )
            expected[span.id] = span
    assert spans_by_id(bundle) == expected
    for span in bundle.spans:
        if span.locator_kind != "file_lines":
            continue
        locator = json.loads(span.locator_json)
        assert locator["start"] >= 1 and locator["end"] >= locator["start"]
        assert not Path(locator["path"]).is_absolute()
        assert span.text_hash and span.policy_id == POLICY


def test_a_passage_with_a_generated_segment_gets_a_view_over_its_originals(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    rendered = [passage for passage in bundle.passages if passage.view is not None]
    assert rendered, "no passage was rendered"
    views = {view.id: view for view in bundle.views}
    derived = {record.id: record for record in bundle.derived_records}
    spans = spans_by_id(bundle)
    for passage in rendered:
        view = views[passage.view.id]
        assert view.text == passage.chunk.text
        assert view.view_kind == "projection"
        assert (view.span_id, view.source_revision_id) == (passage.span.id, passage.span.revision_id)
        assert view.derivation_version == api.CODE_BINDING_RULE_VERSION
        assert view.vector_profile == bundle.generation.embedding_profile
        record = derived[view.derived_record_id]
        assert record.rule_version == api.CODE_BINDING_RULE_VERSION
        assert (record.state, record.model_version) == ("ready", None)
        assert record.workspace_id == WORKSPACE
        assert record.dependency_fingerprint == view.dependency_fingerprint
        edges = [edge for edge in bundle.derived_dependencies if edge.derived_record_id == record.id]
        assert edges and all(edge.input_kind == "span" for edge in edges)
        assert {edge.input_id for edge in edges} == {span.id for span in passage.spans}
        assert set(record.input_revision_ids) == {spans[edge.input_id].revision_id for edge in edges}


def test_a_passage_that_is_exactly_its_source_lines_needs_no_view(api, raw_store, tmp_path):
    """A file with no trailing newline whose one symbol is the whole passage."""
    body = b"def only(value):\n    return value"
    bundle, _, prepared, _ = bundle_of(api, raw_store, tmp_path / "repo", files={"only.py": body})
    plain = [passage for passage in bundle.passages if passage.view is None]
    assert plain, [chunk.requires_view for chunk in prepared.chunks]
    for passage in plain:
        assert passage.chunk.text == passage.span.text
        assert passage.retrieval_view_id is None
        assert len(passage.spans) == 1


def test_changing_the_binding_rule_version_changes_every_view_identity(api, raw_store, tmp_path, monkeypatch):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "one")
    monkeypatch.setattr(api, "CODE_BINDING_RULE_VERSION", "code-binding-v2")
    other, _, _, _ = bundle_of(api, raw_store, tmp_path / "two")
    assert bundle.views and other.views
    assert {view.id for view in bundle.views}.isdisjoint({view.id for view in other.views})
    assert {span.id for span in bundle.spans} == {span.id for span in other.spans}


def test_a_passage_identity_binds_generation_revision_span_and_view(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    assert bundle.passages
    for passage in bundle.passages:
        assert passage.id == generation_passage_id(
            bundle.generation_id,
            passage.span.revision_id,
            passage.span.id,
            passage.chunk.ordinal,
            retrieval_view_id=passage.retrieval_view_id,
        )
        row = passage.native_row()
        assert row["generation_id"] == bundle.generation_id
        assert row["embedding_profile"] == bundle.generation.embedding_profile
        assert row["text"] == passage.chunk.text
        assert row["span_id"] == passage.span.id
        assert row["artifact_revision_id"] == passage.span.revision_id
        assert "embedding" not in row
    identities = [passage.id for passage in bundle.passages]
    assert len(identities) == len(set(identities))


# ------------------------------------------------------------------ commits


def test_commit_chunks_pass_through_unbound_in_chunk_order(api, raw_store, tmp_path):
    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    generation = api.code_generation(
        captured,
        workspace_id=WORKSPACE,
        source_id=SOURCE,
        generation_identity_inputs=identity_inputs(api),
        observed_at=INSTANT,
    )
    units = units_of(captured, raw_store)
    facts = extract_code(
        [item.unit.to_document() for item in units if item.unit],
        SOURCE,
        node_namespace=generation_namespace(generation),
    )
    facts.commits = [
        {
            "id": f"commit-{index}",
            "source_id": SOURCE,
            "sha": str(index) * 40,
            "author": "Hippo Fixture",
            "date": f"2026-09-0{index + 1}T09:00:00+00:00",
            "message": f"Subject {index}\n\nA body paragraph for commit {index}.",
            "ordinal": index,
        }
        for index in range(2)
    ]
    prepared = chunks_of(units, facts=facts)
    commits = [chunk for chunk in prepared.chunks if chunk.kind == "commit"]
    assert [chunk.commit_id for chunk in commits] == ["commit-0", "commit-1"]
    bundle = bind(api, captured, prepared, facts)
    assert bundle.commit_chunks == tuple(commits)
    assert bundle.commit_chunks[0].ordinal < bundle.commit_chunks[1].ordinal
    assert {passage.chunk.chunk_key for passage in bundle.passages}.isdisjoint(
        {chunk.chunk_key for chunk in commits}
    )
    assert all(object_.kind != "commit" for object_ in bundle.objects)
    assert all(binding.native_kind != "Commit" for binding in bundle.bindings)
    assert all(view.text != commits[0].text for view in bundle.views)


# ------------------------------------------------------------------ objects


def test_the_repository_object_has_exactly_one_declared_observation_on_a_field_span(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    repository = bundle.repository_object
    assert repository in bundle.objects and repository.kind == "repository"
    assert json.loads(repository.canonical_key) == repository_key(REPOSITORY_INSTANCE, REPOSITORY_ID)
    observations = [row for row in bundle.observations if row.object_id == repository.id]
    assert len(observations) == 1
    observation = observations[0]
    assert observation.evidence_class == "declared"
    assert observation.span_id == bundle.repository_span.id
    assert observation.revision_id == bundle.repository_revision.id
    assert json.loads(observation.attributes_json)["head_revision"] == HEAD
    span = bundle.repository_span
    assert span.locator_kind == "field"
    assert json.loads(span.locator_json) == {
        "kind": "field",
        "field_path": api.REPOSITORY_FIELD_PATH,
    }
    assert span.text == f"{REPOSITORY_INSTANCE}/{REPOSITORY_ID}"
    assert span.revision_id == bundle.repository_revision.id
    assert all(row.span_id != span.id for row in bundle.observations if row is not observation)


def test_a_file_object_carries_one_catalog_observation_per_span_of_that_file(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    files = [object_ for object_ in bundle.objects if object_.kind == "file"]
    assert sorted(json.loads(object_.canonical_key)[-1] for object_ in files) == [
        "db/schema.sql",
        "src/orders.py",
    ]
    for object_ in files:
        path = json.loads(object_.canonical_key)[-1]
        assert json.loads(object_.canonical_key)[0] == bundle.repository_object.id
        observations = [row for row in bundle.observations if row.object_id == object_.id]
        assert observations
        assert {row.evidence_class for row in observations} == {"catalog_observed"}
        expected = {
            span.id
            for span in bundle.spans
            if span.locator_kind == "file_lines" and path_of(bundle, span) == path
        }
        assert {row.span_id for row in observations} == expected
        assert all(json.loads(row.attributes_json)["path"] == path for row in observations)


def test_a_symbol_object_is_keyed_by_repository_and_signature(api, raw_store, tmp_path):
    bundle, _, prepared, facts = bundle_of(api, raw_store, tmp_path / "repo")
    objects = {object_.id for object_ in bundle.objects if object_.kind == "symbol"}
    assert objects
    by_native = {symbol.id: symbol for symbol in facts.symbols}
    named = {chunk.symbol_id for chunk in prepared.chunks if chunk.symbol_id is not None}
    assert named
    for native in named:
        symbol = by_native[native]
        identity = make_identity(
            "object",
            [
                WORKSPACE,
                "symbol",
                symbol_key(
                    bundle.repository_object.id,
                    symbol.lang,
                    symbol.path,
                    symbol.qualname,
                    symbol.signature or None,
                    kind=symbol.kind,
                ),
            ],
        )
        assert identity in objects
        observations = [row for row in bundle.observations if row.object_id == identity]
        assert observations and {row.evidence_class for row in observations} == {"syntax_observed"}
        attributes = json.loads(observations[0].attributes_json)
        assert attributes["name"] == symbol.name and attributes["path"] == symbol.path
        assert attributes["kind"] == symbol.kind and attributes["lang"] == symbol.lang
        assert attributes["signature"] == symbol.signature
        assert attributes["is_test"] == symbol.is_test and attributes["doc"] == symbol.doc
        row = observations[0]
        assert row.validity_kind == "observed_snapshot" and row.temporal_basis == "observed"
        assert row.recorded_from == INSTANT and row.recorded_to is None
        assert row.valid_from is None and row.valid_to is None


def test_two_overloads_do_not_merge_into_one_knowledge_object(api, raw_store, tmp_path):
    bundle, _, _, facts = bundle_of(api, raw_store, tmp_path / "repo", files={"Robot.cs": OVERLOADS.encode()})
    natives = [symbol for symbol in facts.symbols if symbol.name == "Move"]
    assert len(natives) == 2, [symbol.qualname for symbol in facts.symbols]
    assert len({symbol.id for symbol in natives}) == 1, "codegraph symbol_id carries no signature"
    assert len({symbol.signature for symbol in natives}) == 2
    keys = {
        canonical_json(
            symbol_key(
                bundle.repository_object.id,
                symbol.lang,
                symbol.path,
                symbol.qualname,
                symbol.signature or None,
                kind=symbol.kind,
            )
        )
        for symbol in natives
    }
    assert len(keys) == 2
    objects = [object_ for object_ in bundle.objects if object_.canonical_key in keys]
    assert len(objects) == 2, "overloads merged into one knowledge object"
    rows = [row for row in bundle.native_rows if row.native_id == natives[0].id]
    assert len(rows) == 1, "one native id keeps one native row"
    bindings = [item for item in bundle.bindings if item.native_id == natives[0].id]
    assert {item.object_id for item in bindings} == {object_.id for object_ in objects}


def symbol_objects(bundle, symbols):
    """Each symbol by the knowledge object ID `materialize_code_evidence` gives it."""
    return {
        make_identity(
            "object",
            [
                WORKSPACE,
                "symbol",
                symbol_key(
                    bundle.repository_object.id,
                    symbol.lang,
                    symbol.path,
                    symbol.qualname,
                    symbol.signature or None,
                    kind=symbol.kind,
                ),
            ],
        ): symbol
        for symbol in symbols
    }


def line_range(bundle, span_id):
    locator = json.loads(spans_by_id(bundle)[span_id].locator_json)
    return locator["start"], locator["end"]


def test_each_overload_is_bound_and_observed_only_from_the_passage_holding_its_lines(
    api, raw_store, tmp_path
):
    """R21-M12: a passage naming a shared overload ID used to observe every overload behind it.

    `Move(string)` was observed and bound on `Move(int)`'s span and the reverse: six bindings and
    fourteen observations over three native rows, where four and twelve are exact.
    """
    bundle, _, _, facts = bundle_of(api, raw_store, tmp_path / "repo", files={"Robot.cs": OVERLOADS.encode()})
    overloads = symbol_objects(bundle, [symbol for symbol in facts.symbols if symbol.name == "Move"])
    expected = [("public int Move(int steps)", (5, 5)), ("public int Move(string steps)", (7, 7))]
    for rows in (bundle.bindings, bundle.observations):
        held = [
            (overloads[row.object_id].signature, line_range(bundle, row.span_id))
            for row in rows
            if row.object_id in overloads
        ]
        assert sorted(held) == expected
    assert (len(bundle.native_rows), len(bundle.bindings), len(bundle.observations)) == (3, 4, 12)


def test_a_split_overload_binds_each_window_only_to_the_overload_whose_lines_it_holds(
    api, raw_store, tmp_path
):
    bundle, _, prepared, facts = bundle_of(
        api, raw_store, tmp_path / "repo", files={"Robot.cs": LONG_OVERLOADS.encode()}
    )
    moves = [symbol for symbol in facts.symbols if symbol.name == "Move"]
    overloads = symbol_objects(bundle, moves)
    windows = [chunk for chunk in prepared.chunks if chunk.symbol_id == moves[0].id]
    assert len(moves) == 2 and len({symbol.id for symbol in moves}) == 1 and len(windows) > 2
    syntax = [row for row in bundle.observations if row.evidence_class == "syntax_observed"]
    for rows in (bundle.bindings, syntax):
        held = [
            (overloads[row.object_id], line_range(bundle, row.span_id))
            for row in rows
            if row.object_id in overloads
        ]
        assert len(held) == len(windows)
        for symbol, (start, end) in held:
            overlapping = [
                other.signature for other in moves if start <= other.line_end and other.line_start <= end
            ]
            assert overlapping == [symbol.signature]


def test_a_passage_naming_a_shared_id_that_holds_none_of_its_nodes_lines_refuses(api, raw_store, tmp_path):
    """Fail closed: such a passage cannot say which overload it observed."""
    captured = capture(raw_store, tree(tmp_path / "repo", {"Robot.cs": OVERLOADS.encode()}))
    prepared, facts = prepared_of(api, raw_store, captured)
    for symbol in facts.symbols:
        if symbol.name == "Move":
            symbol.line_start, symbol.line_end = symbol.line_start + 100, symbol.line_end + 100
    with pytest.raises(ValueError, match="holds none of the lines"):
        bind(api, captured, prepared, facts)


def test_a_symbol_alone_behind_its_native_id_binds_as_before_whatever_its_lines(api, raw_store, tmp_path):
    """Only a shared ID is narrowed, so every tree that could seal before binds the same records."""
    bundle, captured, prepared, facts = bundle_of(api, raw_store, tmp_path / "repo")
    for symbol in facts.symbols:
        symbol.line_start, symbol.line_end = symbol.line_start + 100, symbol.line_end + 100
    shifted = bind(api, captured, prepared, facts)
    assert {(row.object_id, row.span_id, row.native_id) for row in shifted.bindings} == {
        (row.object_id, row.span_id, row.native_id) for row in bundle.bindings
    }


def test_a_shared_canonical_symbol_from_two_sources_keeps_distinct_observations(api, raw_store, tmp_path):
    first, _, _, _ = bundle_of(api, raw_store, tmp_path / "one")
    second, _, _, _ = bundle_of(api, raw_store, tmp_path / "two", source_id=OTHER_SOURCE)
    assert first.repository_object.id == second.repository_object.id
    shared = {object_.id for object_ in first.objects if object_.kind == "symbol"} & {
        object_.id for object_ in second.objects if object_.kind == "symbol"
    }
    assert shared, "one repository must give two sources the same canonical symbols"
    left = {(row.object_id, row.span_id, row.revision_id) for row in first.observations}
    right = {(row.object_id, row.span_id, row.revision_id) for row in second.observations}
    assert left and right and left.isdisjoint(right)
    assert {row.native_id for row in first.native_rows}.isdisjoint(
        {row.native_id for row in second.native_rows}
    )


def test_a_data_object_is_bound_from_the_passage_that_names_it(api, raw_store, tmp_path):
    bundle, _, prepared, facts = bundle_of(api, raw_store, tmp_path / "repo")
    named = {identity for chunk in prepared.chunks for identity in chunk.data_object_ids}
    assert named, "the sql file must name its tables"
    assert {row.native_id for row in bundle.native_rows if row.native_kind == "DataObject"} == named
    by_native = {item.id: item for item in facts.data_objects}
    observed = {row.object_id for row in bundle.observations if row.evidence_class == "syntax_observed"}
    for identity in named:
        data = by_native[identity]
        bindings = [item for item in bundle.bindings if item.native_id == identity]
        assert bindings
        for item in bindings:
            assert item.object_id in observed
            object_ = next(o for o in bundle.objects if o.id == item.object_id)
            assert object_.kind == api.DATA_OBJECT_KINDS[data.kind]
            key = json.loads(object_.canonical_key)
            assert key == [bundle.repository_object.id, data.dialect, data.kind, data.qualname]


def test_the_data_object_kind_map_covers_every_codegraph_data_kind(api):
    assert set(api.DATA_OBJECT_KINDS) == set(DATA_KINDS)
    assert set(api.DATA_OBJECT_KINDS.values()) <= set(k.ObjectKind.__args__)
    assert api.DATA_OBJECT_KINDS["table"] == "table"
    assert api.DATA_OBJECT_KINDS["column"] == "column"
    assert {api.DATA_OBJECT_KINDS[kind] for kind in ("collection", "label", "rel_type")} == {"resource"}


# ------------------------------------------------------- native rows/bindings


def test_native_ids_equal_the_generation_namespaced_ids(api, raw_store, tmp_path):
    bundle, _, _, facts = bundle_of(api, raw_store, tmp_path / "repo")
    namespace = generation_namespace(bundle.generation)
    assert bundle.native_rows, "a parsed tree must produce native rows"
    symbols = {symbol.id: symbol for symbol in facts.symbols}
    data_objects = {item.id: item for item in facts.data_objects}
    for row in bundle.native_rows:
        assert row.row["generation_id"] == bundle.generation_id
        assert row.row["source_id"] == SOURCE
        assert row.row["id"] == row.native_id
        assert "embedding" not in row.row
        if row.native_kind == "Symbol":
            symbol = symbols[row.native_id]
            assert row.native_id == symbol_id(
                SOURCE, symbol.path, symbol.qualname, symbol.kind, node_namespace=namespace
            )
        else:
            data = data_objects[row.native_id]
            assert row.native_id == data_id(SOURCE, data.kind, data.qualname, node_namespace=namespace)


def test_every_native_row_has_a_binding_and_every_binding_has_an_observation(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    rows = {(row.native_kind, row.native_id) for row in bundle.native_rows}
    assert rows == {(binding.native_kind, binding.native_id) for binding in bundle.bindings}
    observed = {(row.object_id, row.span_id) for row in bundle.observations}
    spans = spans_by_id(bundle)
    for binding in bundle.bindings:
        assert binding.generation_id == bundle.generation_id
        assert (binding.object_id, binding.span_id) in observed
        assert binding.span_id in spans
    identities = [binding.id for binding in bundle.bindings]
    assert len(identities) == len(set(identities))


def test_a_repository_or_file_object_has_observations_and_no_native_row(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    unbound = {object_.id for object_ in bundle.objects if object_.kind in ("repository", "file")}
    assert unbound
    assert unbound.isdisjoint({binding.object_id for binding in bundle.bindings})
    assert unbound <= {row.object_id for row in bundle.observations}


def test_no_assertion_synonym_or_community_record_is_produced(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    names = {type(record).__name__ for record in bundle.records}
    assert names.isdisjoint({"Assertion", "AssertionVersion", "AssertionSupport", "Alias"})
    assert {member.record_kind for member in bundle.evidence_members} <= {
        "EvidenceSpan",
        "ObjectObservation",
        "RetrievalView",
        "DerivedRecord",
        "DerivedDependency",
    }
    assert all("community" not in row.row for row in bundle.native_rows)
    text = Path(api.__file__).read_text(encoding="utf-8")
    for forbidden in ("Assertion", "SYNONYM", "set_symbol_communities"):
        assert forbidden not in text, forbidden


# ------------------------------------------------------------------ closure


def test_the_evidence_member_closure_is_exactly_the_records_produced(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    expected = {(type(record).__name__, record.id) for record in bundle.records}
    actual = {(member.record_kind, member.record_id) for member in bundle.evidence_members}
    assert expected == actual
    assert len(actual) == len(bundle.evidence_members) == len(bundle.records)
    assert all(member.generation_id == bundle.generation_id for member in bundle.evidence_members)


def test_every_evidence_record_revision_is_a_selected_member(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    selected = {member.artifact_revision_id for member in bundle.revision_members}
    assert {span.revision_id for span in bundle.spans} <= selected
    assert {row.revision_id for row in bundle.observations} <= selected
    assert {view.source_revision_id for view in bundle.views} <= selected
    for record in bundle.derived_records:
        assert set(record.input_revision_ids) <= selected
        assert record.input_binding_ids == ()


def test_every_referenced_identity_resolves_inside_the_bundle(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    spans = spans_by_id(bundle)
    objects = {object_.id for object_ in bundle.objects}
    views = {view.id for view in bundle.views}
    records = {record.id for record in bundle.derived_records}
    for row in bundle.observations:
        assert row.object_id in objects and row.span_id in spans
        assert row.revision_id == spans[row.span_id].revision_id
    for view in bundle.views:
        assert view.span_id in spans and view.derived_record_id in records
    for edge in bundle.derived_dependencies:
        assert edge.derived_record_id in records and edge.input_id in spans
    for passage in bundle.passages:
        assert all(span.id in spans for span in passage.spans)
        assert passage.retrieval_view_id is None or passage.retrieval_view_id in views


def test_one_generation_per_bundle(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    assert {passage.generation.id for passage in bundle.passages} <= {bundle.generation_id}
    assert all(passage.generation == bundle.generation for passage in bundle.passages)
    assert {binding.generation_id for binding in bundle.bindings} <= {bundle.generation_id}


def test_every_cited_original_line_is_covered_by_exactly_one_span_per_passage(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    for passage in bundle.passages:
        ranges = sorted(
            (json.loads(span.locator_json)["start"], json.loads(span.locator_json)["end"])
            for span in passage.spans
        )
        for left, right in zip(ranges, ranges[1:], strict=False):
            assert left[1] < right[0], (left, right)
        assert len({span.id for span in passage.spans}) == len(passage.spans)


# ----------------------------------------------------------------- refusals


def test_a_chunk_rule_version_that_differs_from_the_pinned_one_refuses(api, raw_store, tmp_path, monkeypatch):
    import hippo.ingest.prepared_code_chunks as chunker

    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    monkeypatch.setattr(chunker, "CODE_CHUNK_RULE_VERSION", "code-chunks-v2")
    prepared, facts = prepared_of(api, raw_store, captured)
    assert prepared.rule_version == "code-chunks-v2"
    monkeypatch.undo()
    with pytest.raises(ValueError, match="rule version"):
        bind(api, captured, prepared, facts)


def test_a_chunk_naming_a_file_the_capture_excluded_refuses(api, raw_store, tmp_path):
    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    prepared, facts = prepared_of(
        api, raw_store, captured, extra=(loose(b"def stray():\n    return 1\n", "stray.py"),)
    )
    assert any(chunk.logical_path == "stray.py" for chunk in prepared.chunks)
    with pytest.raises(ValueError, match="never accepted"):
        bind(api, captured, prepared, facts)


def test_a_capture_from_another_source_or_workspace_refuses(api, raw_store, tmp_path):
    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    prepared, facts = prepared_of(api, raw_store, captured)
    with pytest.raises(ValueError, match="another source or workspace"):
        bind(api, captured, prepared, facts, source_id="source-elsewhere")
    with pytest.raises(ValueError, match="another source or workspace"):
        bind(api, captured, prepared, facts, workspace_id="workspace-elsewhere")


def test_a_naive_capture_instant_refuses(api, raw_store, tmp_path):
    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    prepared, facts = prepared_of(api, raw_store, captured)
    with pytest.raises(ValueError, match="timezone-aware"):
        bind(api, captured, prepared, facts, observed_at=datetime(2026, 9, 12, 8, 30))


def test_a_chunk_naming_a_symbol_the_code_graph_does_not_know_refuses(api, raw_store, tmp_path):
    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    prepared, facts = prepared_of(api, raw_store, captured)
    thinner = CodeGraph(
        source_id=facts.source_id,
        symbols=[],
        data_objects=list(facts.data_objects),
        edges=list(facts.edges),
        files_parsed=list(facts.files_parsed),
        node_namespace=facts.node_namespace,
    )
    with pytest.raises(ValueError, match="code graph does not know"):
        bind(api, captured, prepared, thinner)


def test_an_input_that_is_not_a_prepared_code_result_refuses(api, raw_store, tmp_path):
    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    prepared, facts = prepared_of(api, raw_store, captured)
    with pytest.raises(ValueError, match="Prepared code chunks is missing"):
        bind(api, captured, object(), facts)
    with pytest.raises(ValueError, match="Repository capture is missing"):
        bind(api, object(), prepared, facts)
    with pytest.raises(ValueError, match="identity inputs"):
        bind(api, captured, prepared, facts, generation_identity_inputs=object())


def test_a_bundle_with_a_duplicate_span_or_object_refuses(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    with pytest.raises(ValueError, match="Duplicate code evidence spans"):
        replace(bundle, spans=(*bundle.spans, bundle.spans[0]))
    with pytest.raises(ValueError, match="Duplicate code evidence objects"):
        replace(bundle, objects=(*bundle.objects, bundle.objects[0]))


def test_a_bundle_whose_membership_differs_from_its_records_refuses(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    with pytest.raises(ValueError, match="membership differs"):
        replace(bundle, evidence_members=bundle.evidence_members[:-1])
    with pytest.raises(ValueError, match="revision membership"):
        replace(bundle, revision_members=bundle.revision_members[:-1])


def test_a_bundle_whose_native_row_lost_its_binding_refuses(api, raw_store, tmp_path):
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    assert bundle.bindings
    with pytest.raises(ValueError, match="requires an evidence binding"):
        replace(bundle, bindings=bundle.bindings[:-1])


def without(bundle, field, record):
    """`bundle` without one of its records and without that record's exact evidence member."""
    return replace(
        bundle,
        **{field: tuple(item for item in getattr(bundle, field) if item.id != record.id)},
        evidence_members=tuple(member for member in bundle.evidence_members if member.record_id != record.id),
    )


def test_a_bundle_whose_references_leave_the_bundle_refuses(api, raw_store, tmp_path):
    """R21-m24: the closure refusals no test reached. Each case keeps membership exact, so the
    reference check -- not the membership check -- is the one that refuses."""
    bundle, _, _, _ = bundle_of(api, raw_store, tmp_path / "repo")
    binding = bundle.bindings[0]
    observation = next(
        row
        for row in bundle.observations
        if (row.object_id, row.span_id) == (binding.object_id, binding.span_id)
    )
    with pytest.raises(ValueError, match="lacks a selected observation"):
        without(bundle, "observations", observation)
    with pytest.raises(ValueError, match="cites an object or span outside the bundle"):
        replace(bundle, objects=tuple(item for item in bundle.objects if item.id != observation.object_id))
    view = bundle.views[0]
    derived = next(record for record in bundle.derived_records if record.id == view.derived_record_id)
    with pytest.raises(ValueError, match="view cites a span or derivation outside the bundle"):
        without(bundle, "derived_records", derived)
    dependency, *rest = bundle.derived_dependencies
    stale = dependency.replace(input_version="other")
    with pytest.raises(ValueError, match="differs from its exact original"):
        replace(
            bundle,
            derived_dependencies=(stale, *rest),
            evidence_members=tuple(
                member.replace(record_id=stale.id) if member.record_id == dependency.id else member
                for member in bundle.evidence_members
            ),
        )
    outside = k.GenerationEvidenceMember(
        generation_id=bundle.generation.id, record_kind="EvidenceSpan", record_id="span-outside"
    )
    with pytest.raises(ValueError, match="membership differs"):
        replace(bundle, evidence_members=(*bundle.evidence_members, outside))


@pytest.mark.parametrize("native_kind", ["symbols", "data_objects"])
def test_a_native_id_outside_the_generation_namespace_refuses(api, raw_store, tmp_path, native_kind):
    captured = capture(raw_store, tree(tmp_path / "repo", TREE))
    prepared, facts = prepared_of(api, raw_store, captured)
    named = {chunk.symbol_id for chunk in prepared.chunks} | {
        identity for chunk in prepared.chunks for identity in chunk.data_object_ids
    }
    node = next(item for item in getattr(facts, native_kind) if item.id in named)
    node.qualname += "_moved"
    with pytest.raises(ValueError, match="does not match the generation namespace"):
        bind(api, captured, prepared, facts)


def test_a_tree_with_no_code_graph_at_all_still_binds_its_windows_and_prose(api, raw_store, tmp_path):
    files = {"conf/app.yaml": b"a: b\nc: d\n", "README": READ_ME.encode()}
    captured = capture(raw_store, tree(tmp_path / "repo", files))
    prepared, _ = prepared_of(api, raw_store, captured)
    bundle = bind(api, captured, prepared, None)
    assert bundle.passages and bundle.spans
    assert bundle.native_rows == () and bundle.bindings == ()
    assert {object_.kind for object_ in bundle.objects} == {"repository", "file"}
    assert {chunk.kind for chunk in prepared.chunks} == {"window", "prose"}
    assert {passage.chunk.kind for passage in bundle.passages} == {"window", "prose"}


def test_the_windows_of_an_oversized_unparsed_file_partition_its_lines(api, raw_store, tmp_path):
    """`chunker.code_windows` takes no overlap, so no two code windows share a line.

    A configured `overlap_chars` reaches only the delegated prose lane: `code_windows`
    advances `start = end` and `_regroup` takes only a size, so every window and every
    symbol group of a code file is disjoint. That is why the per-passage span
    disjointness `_disjoint` asserts is never in tension with an overlap setting.
    """
    body = "".join(f"key{index:04d}: value{index:04d}\n" for index in range(300)).encode()
    captured = capture(raw_store, tree(tmp_path / "repo", {"conf/big.yaml": body}))
    prepared, facts = prepared_of(api, raw_store, captured, size=400, overlap=120)
    assert len(prepared.chunks) > 2 and all(chunk.kind == "window" for chunk in prepared.chunks)
    bundle = bind(api, captured, prepared, facts)
    assert all(len(passage.spans) == 1 for passage in bundle.passages)
    ranges = sorted(
        (json.loads(span.locator_json)["start"], json.loads(span.locator_json)["end"])
        for span in bundle.spans
        if span.locator_kind == "file_lines"
    )
    assert len(ranges) == len(bundle.passages)
    assert ranges[0][0] == 1 and ranges[-1][1] == 300
    for left, right in zip(ranges, ranges[1:], strict=False):
        assert right[0] == left[1] + 1, (left, right)


# --------------------------------------------------------- archive and file


def test_an_archive_capture_binds_its_members_with_a_source_scoped_tree(api, raw_store, tmp_path):
    archive = tmp_path / "bundle.zip"
    with ZipFile(archive, "w") as handle:
        for name, data in TREE.items():
            handle.writestr(name, data)
    captured = capture(raw_store, archive, repository=None, provider_revision=None)
    assert captured.kind == "archive" and captured.repository is None
    assert all(item.container_chain == () for item in captured.accepted.inputs)
    prepared, facts = prepared_of(api, raw_store, captured)
    bundle = bind(api, captured, prepared, facts)
    assert bundle.repository_artifact.kind == "repository"
    assert bundle.repository_artifact.external_id == f"source:{SOURCE}"
    assert json.loads(bundle.repository_object.canonical_key) == [f"source:{SOURCE}"]
    assert json.loads(bundle.repository_span.locator_json)["field_path"] == api.REPOSITORY_FIELD_PATH
    assert sorted(item.logical_path for item in bundle.accepted) == ["db/schema.sql", "src/orders.py"]
    assert bundle.native_rows and bundle.bindings and bundle.passages
    assert all(
        json.loads(row.attributes_json)["capture_kind"] == "archive"
        for row in bundle.observations
        if "capture_kind" in json.loads(row.attributes_json)
    )


def test_a_single_code_file_capture_binds_one_accepted_file(api, raw_store, tmp_path):
    root = tree(tmp_path / "one", {"only.py": b"def only(value):\n    return value + 1\n"})
    captured = capture(raw_store, root / "only.py", repository=None, provider_revision=None)
    assert captured.kind == "file"
    prepared, facts = prepared_of(api, raw_store, captured)
    bundle = bind(api, captured, prepared, facts)
    assert len(bundle.accepted) == 1 and bundle.accepted[0].logical_path == "only.py"
    assert bundle.repository_artifact.external_id == f"source:{SOURCE}"
    assert bundle.repository_artifact.id != bundle.accepted[0].artifact.id
    assert len(bundle.revision_members) == 3
    assert {object_.kind for object_ in bundle.objects} == {"repository", "file", "symbol"}


def test_every_graph_node_the_fixture_holds_gets_a_native_row(api, raw_store, tmp_path):
    """The complement is CC8's to filter: a node no passage names gets no row here.

    A symbol whose rendered body is only whitespace is dropped by the committed chunker
    (`_symbol_chunks` skips such a group), so it can sit in `facts.symbols` with no
    passage and therefore no native row. CC8 must subtract
    `{row.native_id for row in bundle.native_rows}` from the graph's node IDs before it
    writes `CODE_EDGE`, or an edge will dangle on an endpoint that was never persisted.
    """
    bundle, _, _, facts = bundle_of(api, raw_store, tmp_path / "repo")
    rows = {row.native_id for row in bundle.native_rows}
    assert {symbol.id for symbol in facts.symbols} - rows == set()
    assert {item.id for item in facts.data_objects} - rows == set()


# ------------------------------------------------- reusing an already stored revision


def test_a_stored_revision_for_unchanged_content_is_reused_rather_than_reminted(api, raw_store, tmp_path):
    """`observed_at` means *first* observed, exactly as `prose_generation._pair` treats it.

    `ArtifactRevision.identity_fields` is `(artifact_id, provider_revision, content_hash)`,
    so a second generation over an unchanged file derives the *same* revision ID with a
    later instant -- and the store refuses to rewrite an immutable record. The coordinator
    hands in what it already holds and this boundary binds that record instead.
    """
    bundle, captured, prepared, facts = bundle_of(api, raw_store, tmp_path)
    stored = {item.revision.id: item.revision for item in bundle.accepted}
    stored[bundle.manifest_revision.id] = bundle.manifest_revision
    stored[bundle.repository_revision.id] = bundle.repository_revision
    later = INSTANT + timedelta(days=2)

    fresh = bind(api, captured, prepared, facts, observed_at=later)
    reused = bind(api, captured, prepared, facts, observed_at=later, stored_revisions=stored)

    assert {item.revision.observed_at for item in fresh.accepted} == {later}
    assert {item.revision.observed_at for item in reused.accepted} == {INSTANT}
    assert [item.revision.id for item in reused.accepted] == [item.revision.id for item in fresh.accepted]
    assert reused.manifest_revision == bundle.manifest_revision
    assert reused.repository_revision == bundle.repository_revision
    # Identity never saw the instant, so reuse cannot move a generation.
    assert reused.generation.id == fresh.generation.id == bundle.generation.id
    assert reused.spans == fresh.spans and reused.evidence_members == fresh.evidence_members


def test_a_stored_revision_that_contradicts_this_capture_refuses(api, raw_store, tmp_path):
    bundle, captured, prepared, facts = bundle_of(api, raw_store, tmp_path)
    revision = bundle.accepted[0].revision
    # `raw_uri` is outside the identity tuple, so a contradicting record keeps the ID the
    # reuse would match -- which is exactly the case a blind reuse would bind.
    conflicting = revision.model_copy(update={"raw_uri": "hippo-raw:sha256:" + "f" * 64})

    with pytest.raises(ValueError, match="conflicts with this capture"):
        bind(api, captured, prepared, facts, stored_revisions={revision.id: conflicting})
    with pytest.raises(ValueError, match="mapping of revision id"):
        bind(api, captured, prepared, facts, stored_revisions=[revision])


@pytest.mark.parametrize("change", [{"metadata_json": '{"rule":"older"}'}, {"source_timezone": "UTC"}])
def test_a_stored_revision_differing_in_any_field_but_its_first_observation_refuses(
    api, raw_store, tmp_path, change
):
    """R21-m26: `_reuse` compared four fields, so a stored revision that differed in any other --
    metadata or a source time a changed rule spells differently -- was bound as if it were this one.
    (A stored revision in another lifecycle is refused before reuse is asked.)"""
    bundle, captured, prepared, facts = bundle_of(api, raw_store, tmp_path)
    revision = bundle.accepted[0].revision
    with pytest.raises(ValueError, match="conflicts with this capture"):
        bind(
            api, captured, prepared, facts, stored_revisions={revision.id: revision.model_copy(update=change)}
        )


def test_stored_revisions_change_no_generation_identity(api, raw_store, tmp_path):
    bundle, captured, prepared, facts = bundle_of(api, raw_store, tmp_path)
    stored = {item.revision.id: item.revision for item in bundle.accepted}
    settled = api.code_generation(
        captured,
        workspace_id=WORKSPACE,
        source_id=SOURCE,
        generation_identity_inputs=identity_inputs(api),
        observed_at=INSTANT + timedelta(days=2),
        stored_revisions=stored,
    )
    assert settled.id == bundle.generation.id
