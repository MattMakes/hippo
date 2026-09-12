"""Git history binding: commits become artifacts, objects and rows with honest time.

One `History` from `codegraph.git_history.read_history` plus CC6's `CodeEvidenceBundle`
become `history_event` artifacts and revisions, commit knowledge objects and
observations, commit-message field spans, the rendered commit passage views, the
namespaced native `Commit` rows and the `MODIFIES`/`PRECEDES` shapes the staged writer
takes -- with every truncation recorded in coverage and no wall clock anywhere. Gate CD6.

No git runs here: a `History` is built directly, the way `read_history` returns one, so
the boundary is tested against its contract rather than against one machine's git. The
fixture follows plan section 6's order -- capture, settle the generation, extract under
its namespace, read history, chunk, bind -- because the commit passages CC6 passes
through unbound only exist once the history is attached to the graph the chunker reads.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path

import pytest

from hippo.codegraph.extract import extract_code
from hippo.codegraph.git_history import History
from hippo.codegraph.model import commit_id
from hippo.ingest.code_provenance import read_code_provenance
from hippo.ingest.prepared_code_chunks import CapturedCode, CodeChunkSettings, prepare_code_chunks
from hippo.ingest.repo_capture import capture_repository_inputs, repository_descriptor
from hippo.knowledge import code_binding
from hippo.knowledge.derivations import dependency_version
from hippo.knowledge.identity import canonical_json, make_identity
from hippo.knowledge.inputs import CaptureLimits
from hippo.knowledge.lifecycle import generation_namespace, generation_passage_id
from hippo.knowledge.raw_artifacts import RawArtifactStore

INSTANT = datetime(2026, 9, 12, 8, 30, tzinfo=UTC)
LATER = datetime(2026, 9, 13, 11, 0, tzinfo=UTC)
WORKSPACE = "workspace-cc7"
SOURCE = "source-cc7"
POLICY = "policy-cc7"
CLONE_URL = "https://git.example.com/acme/robots.git"
REPOSITORY_EXTERNAL_ID = "https://git.example.com/acme/robots"
HEAD = "4f1d2c8a9b7e6f5d4c3b2a1908f7e6d5c4b3a291"
DEPTH = 25
AUTHOR = "A Committer"

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

TREE = {"src/orders.py": ORDERS.encode(), "db/schema.sql": SCHEMA.encode()}

# (sha, raw `%aI` author date, message) -- newest first, which is `ordinal` 0 upwards.
# The middle commit carries a non-UTC offset on purpose: its original text and its offset
# have to survive the trip into `source_timestamp_original` and `source_timezone`.
COMMITS = [
    ("c3c3c3c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7", "2026-01-03T09:15:00+00:00", "Raise OrderError from save"),
    ("b2b2b2b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7", "2026-01-02T18:45:00+05:30", "Total the order in place"),
    ("a1a1a1a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7", "2026-01-01T00:00:00+00:00", "Add the order service"),
]

SHALLOW = ("a1a1a1a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7",)


@pytest.fixture
def api():
    return import_module("hippo.knowledge.code_history")


@pytest.fixture
def raw_store(tmp_path):
    return RawArtifactStore(tmp_path / "raw", max_object_bytes=2_000_000)


# ------------------------------------------------------------------ helpers


def limits():
    return CaptureLimits(
        max_input_bytes=200_000,
        max_total_bytes=2_000_000,
        max_inputs=200,
        max_manifest_bytes=200_000,
    )


def tree(root: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def identity_inputs(**changes):
    configuration = {"walker": {"rules": "walker-v1"}} | changes.pop("configuration", {})
    args = {
        "parent_id": None,
        "parser_version": "managed-code-v1",
        "linker_version": "managed-code-linker-v1",
        "embedding_profile": "embed-profile-fingerprint",
        "configuration": configuration,
        "policy_id": POLICY,
    }
    args.update(changes)
    return code_binding.CodeGenerationInputs(**args)


def history_of(facts, namespace, *, commits=COMMITS, skipped=0, truncated=False, modifies=None):
    """A `History` in exactly the shapes `read_history` returns, without running git."""
    touchable = [symbol for symbol in facts.symbols if symbol.kind != "module"]
    rows, built, kept = [], [], []
    for ordinal, (sha, date, message) in enumerate(commits):
        node_id = commit_id(SOURCE, sha, node_namespace=namespace)
        rows.append(
            {
                "id": node_id,
                "source_id": SOURCE,
                "sha": sha,
                "author": AUTHOR,
                "date": date,
                "message": message,
                "ordinal": ordinal,
            }
        )
        built.append(
            {
                "commit_id": node_id,
                "symbol_id": touchable[ordinal % len(touchable)].id,
                "omega": 1.0,
                "hunk": {"file": "src/orders.py", "old_range": [1, 0], "new_range": [16, 8], "churn": 8},
            }
        )
        kept.append(node_id)
    return History(
        commits=rows,
        modifies=built if modifies is None else modifies,
        precedes=list(zip(kept, kept[1:], strict=False)),
        skipped=skipped,
        truncated=truncated,
    )


def fixture(api, raw_store, root, *, files=None, history=True, observed_at=INSTANT, **history_changes):
    """Capture, settle, extract, attach a history, chunk and bind, as plan section 6 does."""
    captured = capture_repository_inputs(
        tree(root, files if files is not None else TREE),
        raw_store=raw_store,
        source_id=SOURCE,
        workspace_id=WORKSPACE,
        limits=limits(),
        configuration={"chunker": {"size": 1500}},
        observed_at=observed_at,
        provider_revision=HEAD,
        repository=repository_descriptor(CLONE_URL),
    )
    identity = identity_inputs(configuration={api.HISTORY_CONFIGURATION_KEY: api.CODE_HISTORY_RULE_VERSION})
    generation = code_binding.code_generation(
        captured,
        workspace_id=WORKSPACE,
        source_id=SOURCE,
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
        [item.unit.to_document() for item in units if item.unit], SOURCE, node_namespace=namespace
    )
    walked = history_of(facts, namespace, **history_changes) if history else History()
    facts.commits, facts.modifies, facts.precedes = walked.commits, walked.modifies, walked.precedes
    prepared = prepare_code_chunks(
        units,
        facts=facts,
        settings=CodeChunkSettings(size_chars=1500, overlap_chars=150),
        max_chunks=20_000,
    )
    bundle = code_binding.materialize_code_evidence(
        captured,
        prepared,
        facts,
        workspace_id=WORKSPACE,
        source_id=SOURCE,
        generation_identity_inputs=identity,
        observed_at=observed_at,
    )
    return bundle, walked, facts, captured


def bind(api, code_bundle, walked, *, observed_at=INSTANT, **changes):
    args = {
        "code_bundle": code_bundle,
        "repository": repository_descriptor(CLONE_URL),
        "workspace_id": WORKSPACE,
        "source_id": SOURCE,
        "generation_id": code_bundle.generation.id,
        "generation_namespace": generation_namespace(code_bundle.generation),
        "observed_at": observed_at,
        "history_depth": DEPTH,
        "shallow_boundary": SHALLOW,
    }
    args.update(changes)
    return api.bind_history(walked, **args)


def bound(api, raw_store, root, **changes):
    """The whole fixture plus its history bundle, which most tests want together."""
    observed_at = changes.pop("observed_at", INSTANT)
    bind_changes = {
        name: changes.pop(name) for name in ("history_depth", "shallow_boundary") if name in changes
    }
    code_bundle, walked, facts, captured = fixture(api, raw_store, root, observed_at=observed_at, **changes)
    history = bind(api, code_bundle, walked, observed_at=observed_at, **bind_changes)
    return history, code_bundle, walked, facts


def commit_of(history, sha):
    return next(item for item in history.commits if item.sha == sha)


# ------------------------------------------------------------------ purity


def test_the_code_history_module_exists():
    from importlib.util import find_spec

    assert find_spec("hippo.knowledge.code_history") is not None


def test_the_module_holds_no_store_model_or_clock(api):
    """CD6: no record calls a wall clock and no default instant appears anywhere."""
    source = Path(api.__file__).read_text()
    for forbidden in ("datetime.now", "utcnow", "utc_now", "now()", "time.time", "_now("):
        assert forbidden not in source, f"{forbidden} reaches the pure history boundary"
    assert "def bind_history" in source


def test_the_module_imports_no_ingest_module():
    """Ruling 12: a knowledge module never reaches back into `hippo.ingest`."""
    program = (
        "import sys\n"
        "import hippo.knowledge.code_history\n"
        "leaked = sorted(n for n in sys.modules if n.startswith('hippo.ingest'))\n"
        "print(leaked)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", result.stdout


def test_a_naive_capture_instant_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    with pytest.raises(ValueError, match="timezone-aware"):
        bind(api, code_bundle, walked, observed_at=datetime(2026, 9, 12, 8, 30))


def test_a_capture_instant_that_differs_from_the_generation_refuses(api, raw_store, tmp_path):
    """Plan section 9: one capture instant is threaded through every record."""
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    with pytest.raises(ValueError, match="one capture instant"):
        bind(api, code_bundle, walked, observed_at=LATER)


# ----------------------------------------------------- artifacts and revisions


def test_each_commit_becomes_one_history_event_artifact_and_revision(api, raw_store, tmp_path):
    history, code_bundle, walked, _ = bound(api, raw_store, tmp_path / "tree")
    assert [item.sha for item in history.commits] == [sha for sha, _, _ in COMMITS]
    assert len(history.artifacts) == len(history.revisions) == len(COMMITS)
    for artifact, revision in zip(history.artifacts, history.revisions, strict=True):
        assert artifact.kind == "history_event"
        assert (artifact.workspace_id, artifact.source_id) == (WORKSPACE, SOURCE)
        assert artifact.policy_id == code_bundle.repository_artifact.policy_id
        assert artifact.connector_id is None and artifact.provider_instance is None
        assert revision.artifact_id == artifact.id and revision.lifecycle == "active"


def test_the_history_event_external_id_names_the_repository_and_the_sha(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    assert code_bundle.repository_artifact.external_id == REPOSITORY_EXTERNAL_ID
    for item in history.commits:
        assert item.artifact.external_id == f"{REPOSITORY_EXTERNAL_ID}@{item.sha}"
        assert item.artifact.canonical_uri == item.artifact.external_id


def test_a_history_event_revision_carries_the_author_date_and_its_raw_text(api, raw_store, tmp_path):
    """CD6 and plan section 9's `history_event` row, field for field."""
    history, _, _, _ = bound(api, raw_store, tmp_path / "tree")
    item = commit_of(history, COMMITS[0][0])
    assert item.revision.provider_revision == COMMITS[0][0]
    assert item.revision.source_updated_at == datetime(2026, 1, 3, 9, 15, tzinfo=UTC)
    assert item.revision.source_timestamp_original == COMMITS[0][1]
    assert item.revision.source_timezone == "+00:00"
    assert item.revision.source_precision == "second"
    assert item.revision.observed_at == INSTANT


def test_a_non_utc_author_offset_keeps_its_original_text_and_offset(api, raw_store, tmp_path):
    history, _, _, _ = bound(api, raw_store, tmp_path / "tree")
    item = commit_of(history, COMMITS[1][0])
    assert item.revision.source_timestamp_original == "2026-01-02T18:45:00+05:30"
    assert item.revision.source_timezone == "+05:30"
    # The stored instant is the same moment, normalized; the original text is what proves
    # the repository's own spelling was not silently rewritten.
    assert item.revision.source_updated_at == datetime(
        2026, 1, 2, 18, 45, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    assert item.observation.valid_from == item.revision.source_updated_at


def test_an_author_date_without_an_offset_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    walked.commits[1]["date"] = "2026-01-02T18:45:00"
    with pytest.raises(ValueError, match="offset"):
        bind(api, code_bundle, walked)


def test_an_unparseable_author_date_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    walked.commits[0]["date"] = "last thursday"
    with pytest.raises(ValueError, match="author date"):
        bind(api, code_bundle, walked)


# --------------------------------------------------------- objects and spans


def test_each_commit_becomes_one_commit_object_keyed_by_repository_and_sha(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    assert len(history.objects) == len(COMMITS)
    for item in history.commits:
        assert item.knowledge_object.kind == "commit"
        assert item.knowledge_object.workspace_id == WORKSPACE
        assert json.loads(item.knowledge_object.canonical_key) == [
            code_bundle.repository_object.id,
            item.sha,
        ]


def test_a_commit_message_becomes_one_field_span_on_its_history_event_revision(api, raw_store, tmp_path):
    """CD6 and plan section 4: a real locator from the closed set, never a whole-file span."""
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    assert len(history.spans) == len(COMMITS)
    assert {span.locator_kind for span in history.spans} == {"field"}
    for item, (_, _, message) in zip(history.commits, COMMITS, strict=True):
        assert item.span.revision_id == item.revision.id
        assert item.span.text == message
        assert json.loads(item.span.locator_json) == {
            "kind": "field",
            "field_path": api.COMMIT_MESSAGE_FIELD_PATH,
        }
        assert item.span.policy_id == code_bundle.repository_artifact.policy_id


def test_no_commit_span_claims_a_line_of_any_captured_file(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    file_revisions = {item.revision.id for item in code_bundle.accepted}
    assert not {span.revision_id for span in history.spans} & file_revisions


def test_a_commit_observation_carries_the_section_nine_temporal_row(api, raw_store, tmp_path):
    history, _, _, _ = bound(api, raw_store, tmp_path / "tree")
    assert len(history.observations) == len(COMMITS)
    for item in history.commits:
        row = item.observation
        assert (row.object_id, row.revision_id, row.span_id) == (
            item.knowledge_object.id,
            item.revision.id,
            item.span.id,
        )
        assert row.valid_from == item.revision.source_updated_at and row.valid_to is None
        assert row.validity_kind == "explicit_interval"
        assert row.temporal_basis == "commit"
        assert row.temporal_precision == "second"
        assert row.recorded_from == INSTANT and row.recorded_to is None
        assert row.evidence_class == api.COMMIT_EVIDENCE_CLASS == "declared"
        assert row.source_timestamp_original == item.revision.source_timestamp_original
        assert row.source_timezone == item.revision.source_timezone


def test_a_commit_observation_records_the_attributes_a_reader_renders(api, raw_store, tmp_path):
    history, _, _, _ = bound(api, raw_store, tmp_path / "tree")
    item = commit_of(history, COMMITS[2][0])
    assert json.loads(item.observation.attributes_json) == {
        "sha": COMMITS[2][0],
        "author": AUTHOR,
        "ordinal": 2,
    }


# ---------------------------------------------------------- views and passages


def test_a_commit_passage_becomes_a_view_over_its_message_span(api, raw_store, tmp_path):
    """CD6/plan section 4: a synthesized commit passage is a projection over its original."""
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    assert len(code_bundle.commit_chunks) == len(COMMITS)
    assert len(history.views) == len(history.derived_records) == len(COMMITS)
    assert len(history.derived_dependencies) == len(COMMITS)
    for item in history.commits:
        passage = item.passage
        assert passage is not None and passage.chunk.commit_sha == item.sha
        view = passage.view
        assert view.view_kind == "projection"
        assert view.span_id == item.span.id and view.source_revision_id == item.revision.id
        assert view.text == passage.chunk.text
        assert view.vector_profile == code_bundle.generation.embedding_profile
        assert view.derivation_version == api.CODE_HISTORY_RULE_VERSION
        assert view.derived_record_id == passage.derived_record.id
        assert passage.derived_record.rule_version == api.CODE_HISTORY_RULE_VERSION
        assert passage.derived_record.input_revision_ids == (item.revision.id,)
        assert passage.derived_record.state == "ready"
        edge = passage.derived_dependencies[0]
        assert (edge.input_kind, edge.input_id) == ("span", item.span.id)
        assert edge.input_version == dependency_version(item.span)


def test_a_commit_passage_row_names_its_generation_view_and_span(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    item = commit_of(history, COMMITS[0][0])
    passage = item.passage
    assert passage.id == generation_passage_id(
        code_bundle.generation.id,
        item.revision.id,
        item.span.id,
        passage.chunk.ordinal,
        retrieval_view_id=passage.view.id,
    )
    assert passage.native_row() == {
        "id": passage.id,
        "source_id": SOURCE,
        "generation_id": code_bundle.generation.id,
        "artifact_revision_id": item.revision.id,
        "span_id": item.span.id,
        "retrieval_view_id": passage.view.id,
        "embedding_profile": code_bundle.generation.embedding_profile,
        "ordinal": passage.chunk.ordinal,
        "title": passage.chunk.title,
        "text": passage.chunk.text,
    }


def test_a_commit_with_no_passage_still_binds_its_artifact_object_and_row(api, raw_store, tmp_path):
    """A commit the chunker never rendered is still a commit; only its view is absent."""
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    extra_sha = "f0f0f0f01234567890abcdef1234567890abcdef"
    namespace = generation_namespace(code_bundle.generation)
    walked.commits.append(
        {
            "id": commit_id(SOURCE, extra_sha, node_namespace=namespace),
            "source_id": SOURCE,
            "sha": extra_sha,
            "author": AUTHOR,
            "date": "2025-12-31T23:00:00+00:00",
            "message": "An older commit the chunker never saw",
            "ordinal": 3,
        }
    )
    history = bind(api, code_bundle, walked)
    item = commit_of(history, extra_sha)
    assert item.passage is None
    assert item.span is not None and item.native_row is not None and item.binding is not None
    assert len(history.views) == len(COMMITS)
    assert len(history.spans) == len(COMMITS) + 1


def test_a_commit_chunk_naming_a_commit_the_history_never_walked_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    dropped = walked.commits.pop(0)["id"]
    walked.modifies = [row for row in walked.modifies if row["commit_id"] != dropped]
    walked.precedes = [pair for pair in walked.precedes if dropped not in pair]
    with pytest.raises(ValueError, match="commit this history does not hold"):
        bind(api, code_bundle, walked)


# --------------------------------------------------------- native rows and bindings


def test_every_commit_gets_a_namespaced_native_row_carrying_the_generation(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    namespace = generation_namespace(code_bundle.generation)
    assert {row.native_kind for row in history.native_rows} == {"Commit"}
    for ordinal, (item, (sha, date, message)) in enumerate(zip(history.commits, COMMITS, strict=True)):
        assert item.native_row.native_id == commit_id(SOURCE, sha, node_namespace=namespace)
        assert item.native_row.row == {
            "id": item.native_row.native_id,
            "source_id": SOURCE,
            "generation_id": code_bundle.generation.id,
            "sha": sha,
            "author": AUTHOR,
            "date": date,
            "message": message,
            "ordinal": ordinal,
        }


def test_every_commit_native_row_has_a_binding_to_its_object_and_span(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    assert len(history.bindings) == len(history.native_rows) == len(COMMITS)
    for item in history.commits:
        binding = item.binding
        assert binding.generation_id == code_bundle.generation.id
        assert binding.native_kind == "Commit"
        assert binding.native_id == item.native_row.native_id
        assert binding.object_id == item.knowledge_object.id
        assert binding.span_id == item.span.id


def test_a_native_commit_id_that_does_not_match_the_generation_namespace_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    walked.commits[0]["id"] = commit_id(SOURCE, COMMITS[0][0], node_namespace="another-namespace")
    with pytest.raises(ValueError, match="generation namespace"):
        bind(api, code_bundle, walked)


def test_only_the_five_exact_evidence_kinds_are_produced(api, raw_store, tmp_path):
    """CD5's rule holds here too: no assertion, synonym or community record exists."""
    history, _, _, _ = bound(api, raw_store, tmp_path / "tree")
    kinds = {type(record).__name__ for record in history.records}
    assert kinds == {
        "EvidenceSpan",
        "DerivedRecord",
        "DerivedDependency",
        "RetrievalView",
        "ObjectObservation",
    }
    assert {row.native_kind for row in history.native_rows} == {"Commit"}


# ------------------------------------------------------------- MODIFIES / PRECEDES


def test_modifies_rows_keep_their_hunks_and_bind_only_to_symbols_of_this_generation(api, raw_store, tmp_path):
    history, code_bundle, walked, _ = bound(api, raw_store, tmp_path / "tree")
    symbols = {row.native_id for row in code_bundle.native_rows if row.native_kind == "Symbol"}
    commits = {item.native_row.native_id for item in history.commits}
    assert [row.row for row in history.modifies] == walked.modifies
    for row in history.modifies:
        assert row.commit_id in commits and row.symbol_id in symbols
        assert row.row["hunk"] == {
            "file": "src/orders.py",
            "old_range": [1, 0],
            "new_range": [16, 8],
            "churn": 8,
        }


def test_a_modifies_edge_to_a_symbol_outside_this_generation_refuses(api, raw_store, tmp_path):
    """CD6: refused, never dropped -- a silent drop would lose history without saying so."""
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    walked.modifies[1]["symbol_id"] = make_identity("symbol", ["another", "generation", "x.py", "x"])
    with pytest.raises(ValueError, match="symbol outside this generation"):
        bind(api, code_bundle, walked)


def test_a_modifies_edge_from_an_unbound_commit_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    walked.modifies[0]["commit_id"] = commit_id(SOURCE, "deadbeef" * 5, node_namespace="other")
    with pytest.raises(ValueError, match="commit outside this history"):
        bind(api, code_bundle, walked)


def test_precedes_pairs_chain_the_bound_commits_newest_to_oldest(api, raw_store, tmp_path):
    history, _, walked, _ = bound(api, raw_store, tmp_path / "tree")
    chain = [item.native_row.native_id for item in history.commits]
    assert history.precedes == tuple(zip(chain, chain[1:], strict=False))
    assert list(history.precedes) == walked.precedes


def test_a_precedes_pair_naming_an_unbound_commit_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    walked.precedes[0] = (walked.precedes[0][0], commit_id(SOURCE, "cafe" * 10, node_namespace="other"))
    with pytest.raises(ValueError, match="commit outside this history"):
        bind(api, code_bundle, walked)


# ------------------------------------------------------------------ coverage


def test_coverage_records_the_walk_depth_skipped_truncated_and_the_shallow_boundary(api, raw_store, tmp_path):
    """CD6 and design review m4: a first-parent walk is never a complete history."""
    history, _, _, _ = bound(api, raw_store, tmp_path / "tree", skipped=4, truncated=True)
    assert history.coverage == {
        "history": "read",
        "history_walk": "first_parent",
        "history_depth": DEPTH,
        "history_commits": len(COMMITS),
        "history_skipped": 4,
        "history_truncated": True,
        "history_shallow_boundary": list(SHALLOW),
        "history_renames": "not_reported",
    }
    assert json.loads(history.coverage_json) == history.coverage


def test_a_disabled_history_produces_no_history_event_and_records_disabled(api, raw_store, tmp_path):
    history, _, _, _ = bound(api, raw_store, tmp_path / "tree", history=False, history_depth=0)
    assert history.commits == () and history.artifacts == () and history.revisions == ()
    assert history.spans == () and history.observations == () and history.native_rows == ()
    assert history.evidence_members == () and history.revision_members == ()
    assert history.coverage["history"] == "disabled"
    assert history.coverage["history_depth"] == 0
    assert history.coverage["history_walk"] == "first_parent"


def test_a_disabled_history_that_still_walked_commits_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    with pytest.raises(ValueError, match="disabled"):
        bind(api, code_bundle, walked, history_depth=0)


def test_a_history_longer_than_its_configured_depth_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    with pytest.raises(ValueError, match="configured depth"):
        bind(api, code_bundle, walked, history_depth=2)


# ------------------------------------------------------------ membership closure


def test_every_history_event_revision_is_a_generation_member(api, raw_store, tmp_path):
    """Ruling 13: history_event revisions ARE members, and carry the commit spans."""
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    assert {member.artifact_revision_id for member in history.revision_members} == {
        item.revision.id for item in history.commits
    }
    assert {member.generation_id for member in history.revision_members} == {code_bundle.generation.id}


def test_the_evidence_member_closure_is_exactly_the_records_produced(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    assert len(history.evidence_members) == len(history.records)
    assert {(member.record_kind, member.record_id) for member in history.evidence_members} == {
        (type(record).__name__, record.id) for record in history.records
    }
    assert {member.generation_id for member in history.evidence_members} == {code_bundle.generation.id}


def test_every_referenced_identity_resolves_inside_the_history_bundle(api, raw_store, tmp_path):
    history, _, _, _ = bound(api, raw_store, tmp_path / "tree")
    revisions = {revision.id for revision in history.revisions}
    spans = {span.id for span in history.spans}
    objects = {item.id for item in history.objects}
    records = {record.id for record in history.derived_records}
    for row in history.observations:
        assert row.object_id in objects and row.span_id in spans and row.revision_id in revisions
    for view in history.views:
        assert view.span_id in spans and view.derived_record_id in records
        assert view.source_revision_id in revisions
    for edge in history.derived_dependencies:
        assert edge.derived_record_id in records and edge.input_id in spans


# ------------------------------------------------------------------ determinism


def test_two_runs_with_the_same_inputs_produce_identical_ids(api, raw_store, tmp_path):
    first, code_bundle, walked, _ = bound(api, raw_store, tmp_path / "tree")
    second = bind(api, code_bundle, walked)
    assert [record.id for record in first.records] == [record.id for record in second.records]
    assert [item.artifact.id for item in first.commits] == [item.artifact.id for item in second.commits]
    assert [item.revision.id for item in first.commits] == [item.revision.id for item in second.commits]
    assert first.coverage_json == second.coverage_json


def test_a_different_capture_instant_changes_only_the_observation_identities(api, raw_store, tmp_path):
    """B4's known property, owned by the coordinator: assert it so nobody is surprised."""
    first, _, _, _ = bound(api, raw_store, tmp_path / "tree")
    second, _, _, _ = bound(api, raw_store, tmp_path / "later", observed_at=LATER)
    assert [item.revision.id for item in first.commits] == [item.revision.id for item in second.commits]
    assert [span.id for span in first.spans] == [span.id for span in second.spans]
    assert [view.id for view in first.views] == [view.id for view in second.views]
    assert [row.id for row in first.observations] != [row.id for row in second.observations]
    assert {row.recorded_from for row in second.observations} == {LATER}


# ------------------------------------------------------- rule version and configuration


def test_the_history_rule_version_is_pinned(api, raw_store, tmp_path):
    assert api.CODE_HISTORY_RULE_VERSION == "code-history-v1"
    history, _, _, _ = bound(api, raw_store, tmp_path / "tree")
    assert history.rule_version == api.CODE_HISTORY_RULE_VERSION


def test_the_expected_binding_rule_version_is_pinned_to_the_one_cc6_produces(api):
    """A CC6 bump must bump this module too, rather than binding a derivation it never saw."""
    assert api.EXPECTED_CODE_BINDING_RULE_VERSION == code_binding.CODE_BINDING_RULE_VERSION


def test_the_history_configuration_key_sits_outside_the_binding_reserved_key(api):
    assert api.HISTORY_CONFIGURATION_KEY != code_binding.CODE_BINDING_CONFIGURATION_KEY
    assert api.HISTORY_CONFIGURATION_KEY == "code_history_derivation"


def test_a_generation_whose_configuration_omits_the_history_rule_version_refuses(api, raw_store, tmp_path):
    """Ruling 10: the derivation version is hashed into generation identity, or nothing binds."""
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    stripped = json.loads(code_bundle.configuration_json)
    del stripped[api.HISTORY_CONFIGURATION_KEY]
    naked = replace(code_bundle, configuration_json=canonical_json(stripped))
    with pytest.raises(ValueError, match=api.HISTORY_CONFIGURATION_KEY):
        bind(api, naked, walked)


def test_a_generation_carrying_another_history_rule_version_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    other = json.loads(code_bundle.configuration_json) | {api.HISTORY_CONFIGURATION_KEY: "code-history-v9"}
    with pytest.raises(ValueError, match=api.HISTORY_CONFIGURATION_KEY):
        bind(api, replace(code_bundle, configuration_json=canonical_json(other)), walked)


# ------------------------------------------------------------------ scope refusals


def test_a_generation_id_or_namespace_that_differs_from_the_bundle_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    with pytest.raises(ValueError, match="generation"):
        bind(api, code_bundle, walked, generation_id="generation-elsewhere")
    with pytest.raises(ValueError, match="namespace"):
        bind(api, code_bundle, walked, generation_namespace="namespace-elsewhere")


def test_a_workspace_or_source_that_differs_from_the_bundle_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    with pytest.raises(ValueError, match="workspace"):
        bind(api, code_bundle, walked, workspace_id="workspace-elsewhere")
    with pytest.raises(ValueError, match="source"):
        bind(api, code_bundle, walked, source_id="source-elsewhere")


def test_a_repository_that_differs_from_the_bound_one_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    with pytest.raises(ValueError, match="repository"):
        bind(
            api,
            code_bundle,
            walked,
            repository=repository_descriptor("https://git.example.com/acme/other.git"),
        )


def test_a_code_bundle_that_is_not_cc6s_refuses(api, raw_store, tmp_path):
    _, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    with pytest.raises(ValueError, match="code evidence bundle"):
        api.bind_history(
            walked,
            code_bundle=object(),
            repository=repository_descriptor(CLONE_URL),
            workspace_id=WORKSPACE,
            source_id=SOURCE,
            generation_id="generation-anything",
            generation_namespace="namespace-anything",
            observed_at=INSTANT,
            history_depth=DEPTH,
            shallow_boundary=SHALLOW,
        )


def test_a_history_that_is_not_read_historys_refuses(api, raw_store, tmp_path):
    code_bundle, _, _, _ = fixture(api, raw_store, tmp_path / "tree")
    with pytest.raises(ValueError, match="History"):
        bind(api, code_bundle, object())


def test_a_duplicate_commit_sha_refuses(api, raw_store, tmp_path):
    code_bundle, walked, _, _ = fixture(api, raw_store, tmp_path / "tree")
    walked.commits.append(dict(walked.commits[0], ordinal=3))
    with pytest.raises(ValueError, match="Duplicate"):
        bind(api, code_bundle, walked)


# ------------------------------------------------------------------ the merge


def test_the_merged_bundle_unions_both_inventories(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    merged = api.merge_code_bundles(code_bundle, history)
    assert merged.generation == code_bundle.generation
    assert merged.workspace_id == WORKSPACE
    assert merged.rule_version == code_binding.CODE_BINDING_RULE_VERSION
    assert merged.history_rule_version == api.CODE_HISTORY_RULE_VERSION
    assert len(merged.spans) == len(code_bundle.spans) + len(history.spans)
    assert len(merged.objects) == len(code_bundle.objects) + len(history.objects)
    assert len(merged.observations) == len(code_bundle.observations) + len(history.observations)
    assert len(merged.views) == len(code_bundle.views) + len(history.views)
    assert len(merged.native_rows) == len(code_bundle.native_rows) + len(history.native_rows)
    assert len(merged.bindings) == len(code_bundle.bindings) + len(history.bindings)
    assert len(merged.revision_members) == len(code_bundle.revision_members) + len(history.revision_members)
    assert len(merged.evidence_members) == len(code_bundle.evidence_members) + len(history.evidence_members)
    assert merged.modifies == history.modifies and merged.precedes == history.precedes


def test_the_merged_bundle_binds_every_commit_chunk(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    merged = api.merge_code_bundles(code_bundle, history)
    assert merged.commit_chunks == ()
    assert len(merged.passages) == len(code_bundle.passages) + len(COMMITS)
    ordinals = [passage.chunk.ordinal for passage in merged.passages]
    assert sorted(ordinals) == list(range(len(ordinals)))


def test_merge_validation_refuses_a_duplicate_record(api, raw_store, tmp_path):
    """The merged inventory re-runs CC6's checks rather than trusting two closed halves."""
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    merged = api.merge_code_bundles(code_bundle, history)
    with pytest.raises(ValueError, match="Duplicate"):
        replace(merged, spans=merged.spans + (merged.spans[0],))
    with pytest.raises(ValueError, match="Duplicate"):
        replace(merged, observations=merged.observations + (merged.observations[0],))


def test_merge_refuses_a_history_bundle_from_another_generation(api, raw_store, tmp_path):
    history, _, _, _ = bound(api, raw_store, tmp_path / "tree")
    other_bundle, _, _, _ = fixture(
        api,
        raw_store,
        tmp_path / "other",
        files={"src/only.py": b"def only():\n    return 1\n"},
        history=False,
    )
    with pytest.raises(ValueError, match="generation"):
        api.merge_code_bundles(other_bundle, history)


def test_the_merged_bundle_keeps_every_modifies_and_precedes_endpoint_present(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "tree")
    merged = api.merge_code_bundles(code_bundle, history)
    natives = {(row.native_kind, row.native_id) for row in merged.native_rows}
    for row in merged.modifies:
        assert ("Commit", row.commit_id) in natives and ("Symbol", row.symbol_id) in natives
    for newer, older in merged.precedes:
        assert ("Commit", newer) in natives and ("Commit", older) in natives


def test_a_merged_bundle_with_no_history_at_all_still_closes(api, raw_store, tmp_path):
    history, code_bundle, _, _ = bound(api, raw_store, tmp_path / "empty", history=False, history_depth=0)
    merged = api.merge_code_bundles(code_bundle, history)
    assert merged.modifies == () and merged.precedes == ()
    assert len(merged.revision_members) == len(code_bundle.revision_members)
    assert merged.coverage["history"] == "disabled"
