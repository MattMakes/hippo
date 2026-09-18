"""A generation carrying the registry fingerprint still passes prose preparation (B1, ruling R47).

The kit runtime records `Generation.registry_fingerprint` on every generation a coordinator
builds, while `PlainProseInputs.__post_init__` recomputes the accepted identity from the inputs
alone. The fingerprint is outside `identity_fields` and outside the manifest, so the recomputation
has to carry it rather than treat it as a difference.
"""

from __future__ import annotations

import importlib
from dataclasses import replace

import pytest

from hippo.knowledge.identity import text_hash
from tests.unit.test_managed_input_binding import accepted
from tests.unit.test_managed_prose_preparation import inputs

FINGERPRINT = text_hash("registry-v1")
TEXT = "ACME builds Robot."


def fingerprinted(**changes):
    """`inputs()` rebuilt so the generation, and the passages bound to it, carry the fingerprint.

    The passages are re-materialized because `__post_init__` compares each one's generation with
    the accepted one; binding them to the original would refuse for an unrelated reason.
    """
    binding_api = importlib.import_module("hippo.knowledge.input_binding")
    value = inputs(TEXT)
    binding, chunks = accepted(binding_api, TEXT)
    generation = value.generation.replace(registry_fingerprint=FINGERPRINT, **changes)
    evidence = binding_api.materialize_chunk_evidence(
        chunks, generation, workspace_id="workspace", bindings=(binding,)
    )
    return value, generation, evidence


def test_a_fingerprinted_generation_passes_prose_preparation():
    value, generation, evidence = fingerprinted()
    assert generation.id == value.generation.id  # the fingerprint renames no generation

    prepared = replace(value, generation=generation, evidence=evidence)

    assert prepared.generation.registry_fingerprint == FINGERPRINT
    assert prepared.generation.manifest_hash == value.generation.manifest_hash


def test_prose_preparation_still_refuses_a_generation_of_another_identity():
    # `embedding_profile` is an identity field the recomputation takes from the stored profile
    # rather than from the generation, so changing it is a difference the compare must still see.
    value, generation, evidence = fingerprinted(embedding_profile="another-profile")
    assert generation.id != value.generation.id

    with pytest.raises(ValueError, match="Generation differs from accepted"):
        replace(value, generation=generation, evidence=evidence)
