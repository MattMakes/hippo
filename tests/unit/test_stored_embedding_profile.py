"""Stored profile metadata is a closed identity contract, with no transport state."""

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from hippo.knowledge import embedding_profile as api
from tests.unit.test_embedding_profile import Server


@pytest.fixture
def descriptor():
    server = Server()
    ollama = server.client()
    resolved = api.resolve_embedding_profile(ollama, spec=api.EmbeddingSpec())
    yield resolved.descriptor(), server, resolved
    ollama.client.close()


def test_stored_descriptor_reconstructs_identity_without_http(descriptor):
    raw, server, resolved = descriptor
    before = len(server.calls)
    stored = api.validate_profile_descriptor(raw)
    assert stored.profile == resolved.profile
    assert stored.spec == resolved.spec
    assert stored.fingerprint == resolved.fingerprint
    assert stored.descriptor() == raw
    assert len(server.calls) == before
    assert not hasattr(stored, "_client") and not hasattr(stored, "endpoint_identity")
    raw["spec"]["query_prefix"] = "changed"
    assert stored.spec.query_prefix != "changed"
    fresh = stored.descriptor()
    fresh["profile"]["model"] = "other"
    assert stored.descriptor()["profile"]["model"] == resolved.profile.model
    with pytest.raises(FrozenInstanceError):
        stored.fingerprint = "changed"


def test_stored_descriptor_retains_explicit_prefix_options_and_dimension():
    server = Server()
    ollama = server.client()
    spec = api.EmbeddingSpec(
        query_prefix="query: ",
        document_prefix="document: ",
        options_json='{"num_ctx":512,"seed":0}',
        dimensions=3,
    )
    try:
        resolved = api.resolve_embedding_profile(ollama, spec=spec)
        stored = api.validate_profile_descriptor(resolved.descriptor())
        assert stored.spec == spec
        assert stored.profile == spec.make_profile(ollama.embed_model, server.digest, 3)
    finally:
        ollama.client.close()


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "bool_version",
        "extra",
        "missing",
        "profile_extra",
        "spec_extra",
        "fingerprint",
        "digest",
        "dimension",
        "bool_dimension",
        "prefix",
        "options",
        "noncanonical_options",
        "normalization",
        "truncate",
        "model",
        "requested_dimension",
        "mutable_type",
        "not_dict",
    ],
)
def test_stored_descriptor_rejects_malformed_or_inconsistent_metadata(descriptor, change):
    original, server, _ = descriptor
    raw = deepcopy(original)
    if change == "version":
        raw["profile_schema"] = 2
    elif change == "bool_version":
        raw["profile_schema"] = True
    elif change == "extra":
        raw["endpoint_identity"] = ["not accepted", "not accepted"]
    elif change == "missing":
        del raw["spec"]
    elif change == "profile_extra":
        raw["profile"]["token"] = "not accepted"
    elif change == "spec_extra":
        raw["spec"]["token"] = "not accepted"
    elif change == "fingerprint":
        raw["fingerprint"] = "f" * 64
    elif change == "digest":
        raw["profile"]["model_digest"] = "mutable-tag"
    elif change == "dimension":
        raw["profile"]["dimension"] += 1
    elif change == "bool_dimension":
        raw["profile"]["dimension"] = True
    elif change == "prefix":
        raw["spec"]["document_prefix"] = "different: "
    elif change == "options":
        raw["spec"]["options_json"] = '{"a":1,"a":2}'
    elif change == "noncanonical_options":
        raw["spec"]["options_json"] = "{ }"
    elif change == "normalization":
        raw["spec"]["normalization"] = "none"
    elif change == "truncate":
        raw["spec"]["truncate"] = True
    elif change == "model":
        raw["profile"]["model"] = " name with padding "
    elif change == "requested_dimension":
        # Even a self-consistent hash cannot attest an unsupported output shape.
        spec = api.EmbeddingSpec(dimensions=7)
        profile = spec.make_profile("nomic-embed-text", "a" * 64, 3)
        raw = api.ResolvedEmbeddingProfile(
            profile, api._fingerprint(profile), "nomic-embed-text", spec, ("local", "local"), object()
        ).descriptor()
    elif change == "mutable_type":
        raw["spec"]["query_prefix"] = []
    else:
        raw = []
    before = len(server.calls)
    with pytest.raises(ValueError):
        api.validate_profile_descriptor(raw)
    assert len(server.calls) == before
