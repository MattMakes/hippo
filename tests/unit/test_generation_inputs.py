"""Generation identity is known before any output nodes or vectors exist."""

from datetime import UTC, datetime, timedelta

import pytest

from hippo.knowledge import model as k
from hippo.knowledge.lifecycle import generation_for_inputs, generation_namespace

NOW = datetime(2026, 9, 11, tzinfo=UTC)


def accepted(path="a.py", content_hash="content-a", *, source_id="source-a", workspace_id="workspace-a"):
    artifact = k.Artifact(
        workspace_id=workspace_id,
        source_id=source_id,
        kind="file",
        external_id=path,
        canonical_uri="source:" + source_id + "/" + path,
        policy_id="policy-a",
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id,
        provider_revision="r1",
        content_hash=content_hash,
        raw_uri="blob:" + content_hash,
        observed_at=NOW,
        lifecycle="active",
    )
    return artifact, revision


def build(inputs, **overrides):
    options = dict(
        workspace_id="workspace-a",
        source_id="source-a",
        parent_id=None,
        parser_version="parser-v1",
        linker_version="linker-v1",
        embedding_profile="embed-v1",
        configuration={"dialect": "postgres", "nested": {"b": 2, "a": 1}},
        created_at=NOW,
    )
    return generation_for_inputs(inputs, **(options | overrides))


def test_generation_identity_does_not_depend_on_enumeration_or_observation_time():
    first, second = accepted(), accepted("b.py", "content-b")
    original = build([first, second])
    updated = (first[0], first[1].replace(observed_at=NOW + timedelta(days=1), raw_uri="new:location"))
    replay = build([second, updated], created_at=NOW + timedelta(days=1))
    assert replay.id == original.id
    assert replay.manifest_hash == original.manifest_hash
    assert generation_namespace(replay) == generation_namespace(original)
    assert original.status == "staging"


@pytest.mark.parametrize("change", ["content", "parent", "parser", "linker", "profile", "config"])
def test_generation_identity_changes_with_accepted_inputs_or_build_configuration(change):
    original = build([accepted()])
    inputs = [accepted(content_hash="changed")] if change == "content" else [accepted()]
    overrides = {
        "parent": {"parent_id": "previous-generation"},
        "parser": {"parser_version": "parser-v2"},
        "linker": {"linker_version": "linker-v2"},
        "profile": {"embedding_profile": "embed-v2"},
        "config": {"configuration": {"dialect": "sqlserver"}},
    }.get(change, {})
    changed = build(inputs, **overrides)
    assert changed.id != original.id
    assert generation_namespace(changed) != generation_namespace(original)


@pytest.mark.parametrize("case", ["source", "workspace", "revision", "duplicate"])
def test_generation_rejects_mixed_or_duplicate_accepted_inputs(case):
    artifact, revision = accepted()
    inputs = {
        "source": [accepted(source_id="another-source")],
        "workspace": [accepted(workspace_id="another-workspace")],
        "revision": [(artifact, revision.replace(artifact_id="another-artifact"))],
        "duplicate": [(artifact, revision), (artifact, revision)],
    }[case]
    with pytest.raises(ValueError):
        build(inputs)


def test_empty_generation_is_still_identified_before_outputs_are_built():
    generation = build([])
    assert generation.id and generation.manifest_hash and generation_namespace(generation)
    assert generation_namespace(generation) != generation_namespace(build([], source_id="source-b"))


@pytest.mark.parametrize("workspace", ["", "  ", None, 42])
def test_empty_generation_still_requires_an_explicit_workspace(workspace):
    with pytest.raises(ValueError, match="workspace"):
        build([], workspace_id=workspace)


def test_generation_passage_identity_is_bound_to_all_selected_inputs():
    from hippo.knowledge.lifecycle import generation_passage_id

    identity = generation_passage_id("g1", "r1", "s1", 0)
    assert identity.startswith("passage-")
    assert (
        len(
            {
                identity,
                generation_passage_id("g2", "r1", "s1", 0),
                generation_passage_id("g1", "r2", "s1", 0),
                generation_passage_id("g1", "r1", "s2", 0),
                generation_passage_id("g1", "r1", "s1", 1),
            }
        )
        == 5
    )
    for args in [
        ("", "r", "s", 0),
        ("g", "", "s", 0),
        ("g", "r", "", 0),
        ("g", "r", "s", -1),
        ("g", "r", "s", True),
    ]:
        with pytest.raises(ValueError):
            generation_passage_id(*args)
