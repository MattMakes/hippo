"""The staged code writer accepts a persisted generation that carries the fingerprint (B1, R47).

`materialize_code_evidence` re-settles the generation from its inputs, so the merged bundle the
writer prepares holds a copy without `registry_fingerprint` while the row the coordinator stored
holds it. The field is outside `identity_fields` and cannot be updated, so the writer's compare
has to ignore it -- and nothing else.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from hippo.knowledge.identity import text_hash
from tests.unit.test_staged_code_writer import INSTANT, capture, install, prepare, write

FINGERPRINT = text_hash("registry-v1")


def stored(state, **changes):
    """Just the fields `install` reads, with the generation it persists changed."""
    bundle = state.bundle
    return SimpleNamespace(
        bundle=SimpleNamespace(
            generation=bundle.generation.replace(**changes),
            accepted_pairs=bundle.accepted_pairs,
            history_pairs=bundle.history_pairs,
            revision_members=bundle.revision_members,
            manifest_revision=bundle.manifest_revision,
        )
    )


def staged(store, tmp_path, **changes):
    """A captured code generation whose persisted row differs from the prepared copy."""
    state = capture(store, tmp_path.resolve())
    prepared = prepare(state)
    job, credentials = install(store, stored(state, **changes))
    return SimpleNamespace(state=state, prepared=prepared, job=job, credentials=credentials, store=store)


def test_a_fingerprinted_generation_passes_the_code_writer(store, tmp_path):
    built = staged(store, tmp_path, registry_fingerprint=FINGERPRINT)
    gen = built.prepared.generation
    assert gen.registry_fingerprint is None
    assert store._generation(gen.id).registry_fingerprint == FINGERPRINT

    manifest = write(built, batch_size=3)

    assert manifest == store.validate_generation_seal(gen.id)
    assert store._generation(gen.id).registry_fingerprint == FINGERPRINT


def test_the_code_writer_still_refuses_a_persisted_generation_of_another_capture(store, tmp_path):
    # `created_at` is compared but outside identity, so the same inputs at another instant are the
    # same generation with another observation inventory (design review B4). Tolerating the
    # fingerprint must not tolerate that.
    built = staged(store, tmp_path, registry_fingerprint=FINGERPRINT, created_at=INSTANT + timedelta(hours=1))

    with pytest.raises(ValueError, match="Persisted generation differs from accepted preparation"):
        write(built, batch_size=3)
