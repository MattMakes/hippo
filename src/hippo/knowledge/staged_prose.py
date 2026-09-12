"""Fenced plain-prose writes and exact sealing, with no model or publication calls.

The public refresh wrapper requires no ambient transaction. Its callback-free
batch/seal core can also run inside a coordinator-owned bootstrap transaction.
"""

from contextlib import contextmanager

from . import model as k
from .access import AuthorizationChanged
from .identity import text_hash
from .prose_preparation import PreparedDensePassage, PreparedProseIndex


def _epochs(store, expected_authorization_epoch, expected_suppression_epoch):
    if (
        type(expected_authorization_epoch) is not int
        or expected_authorization_epoch < 0
        or type(expected_suppression_epoch) is not int
        or expected_suppression_epoch < 0
        or store.authorization_epoch() != expected_authorization_epoch
        or store.suppression_epoch() != expected_suppression_epoch
    ):
        raise AuthorizationChanged("Authorization or suppression epoch changed during staged writing")


@contextmanager
def _local(
    store,
    prepared,
    *,
    job_id,
    lease_owner,
    fencing_token,
    expected_authorization_epoch,
    expected_suppression_epoch,
):
    credentials = dict(job_id=job_id, lease_owner=lease_owner, fencing_token=fencing_token)
    gen = prepared.inputs.generation
    # generation_write takes the authorization lock before the source lock.
    with store.generation_write(gen.id, **credentials):
        _epochs(store, expected_authorization_epoch, expected_suppression_epoch)
        current = store._generation(gen.id)
        if current.replace(coverage_json=gen.coverage_json) != gen:
            raise ValueError("Persisted generation differs from accepted preparation")
        yield
        _epochs(store, expected_authorization_epoch, expected_suppression_epoch)
        store._check_build(gen.id, **credentials, states=("staging", "ready"))


def _accepted(store, prepared):
    from .generation_profiles import embedding_mode, validate_generation_profile

    generation = store._generation(prepared.inputs.generation.id)
    if embedding_mode(generation) != "verified_v1":
        raise ValueError("Managed prose writer requires a controlled verified profile binding")
    bound = validate_generation_profile(store, generation)
    if (bound.profile, bound.config_fingerprint) != (
        prepared.inputs.embedding_profile,
        text_hash(prepared.inputs.configuration_json),
    ):
        raise ValueError("Bound profile/configuration differs from prepared inputs")
    for artifact, revision in prepared.inputs.artifacts_and_revisions:
        for record in (artifact, revision):
            if store._knowledge_get(type(record).__name__, record.id) != record:
                raise ValueError("Persisted accepted artifact/revision inventory differs")


def _write_batches(prepared, *, batch_size):
    """Yield complete dependency groups; no store, callback or model is retained."""
    if type(prepared) is not PreparedProseIndex or type(batch_size) is not int or batch_size < 1:
        raise ValueError("Expected immutable prepared output and positive batch size")
    yield (None,)  # Accepted inventory preflight, before any mutation.
    evidence = prepared.inputs.evidence
    gen_id = prepared.inputs.generation.id
    seen = set()

    def selected(record):
        key = type(record).__name__, record.id
        if key in seen:
            return ()
        seen.add(key)
        return (
            record,
            k.GenerationEvidenceMember(generation_id=gen_id, record_kind=key[0], record_id=key[1]),
        )

    def groups():
        for member in evidence.revision_members:
            yield (member,)
        for span in evidence.spans:
            yield selected(span)
        derived = {r.id: r for r in evidence.derived_records}
        dependencies = {}
        for dep in evidence.derived_dependencies:
            dependencies.setdefault(dep.derived_record_id, []).append(dep)
        for dense in prepared.dense:
            group = []
            view = dense.passage.view
            if view is not None:
                group.extend(selected(derived[view.derived_record_id]))
                for dep in dependencies[view.derived_record_id]:
                    group.extend(selected(dep))
                group.extend(selected(view))
            yield (*group, dense)
        derived = {r.id: r for r in prepared.derived_records}
        dependencies = {}
        for dep in prepared.derived_dependencies:
            dependencies.setdefault(dep.derived_record_id, []).append(dep)
        for extraction in prepared.extractions:
            group = list(selected(derived[extraction.derived_record_id]))
            for dep in dependencies[extraction.derived_record_id]:
                group.extend(selected(dep))
            group.extend(selected(extraction))
            yield tuple(group)

    batch = []
    count = 0
    for group in groups():
        batch.extend(group)
        count += 1
        if count == batch_size:
            yield tuple(batch)
            batch, count = [], 0
    if batch:
        yield tuple(batch)


def _write_batch(store, prepared, batch, **authority):
    """Callback-free local core; safe under an existing outer transaction."""
    with _local(store, prepared, **authority):
        for record in batch:
            if record is None:
                _accepted(store, prepared)
            elif type(record) is PreparedDensePassage:
                row = record.native_row()
                existing = store._knowledge_get("Passage", row["id"])
                if existing is not None and store._canonical_native(
                    "Passage", existing
                ) != store._canonical_native("Passage", row):
                    raise ValueError("Conflicting staged passage; explicit recovery required")
                store.add_passages([row])
            else:
                store.put_knowledge(record)


def _inventory(store, prepared):
    _accepted(store, prepared)
    inputs = prepared.inputs
    gen_id = inputs.generation.id

    def selected(kind):
        return {r.id: r for r in store._knowledge_rows(kind) if r.generation_id == gen_id}

    for kind, expected in (
        ("GenerationMember", inputs.evidence.revision_members),
        ("GenerationEvidenceMember", (*inputs.evidence.evidence_members, *prepared.evidence_members)),
    ):
        if selected(kind) != {r.id: r for r in expected}:
            raise ValueError(f"Exact {kind} inventory differs from prepared coverage")
    for record in (*inputs.evidence.records, *prepared.records):
        if store._knowledge_get(type(record).__name__, record.id) != record:
            raise ValueError("Persisted evidence payload differs from prepared inventory")
    expected_dense = {
        r.passage.id: store._canonical_native("Passage", r.native_row()) for r in prepared.dense
    }
    actual_dense = {
        r["id"]: store._canonical_native("Passage", r)
        for r in store._native_rows("Passage")
        if r.get("generation_id") == gen_id
    }
    if actual_dense != expected_dense:
        raise ValueError("Dense passage inventory differs from prepared coverage")
    # Prose rows carry generation ownership even before exact membership; reject
    # leftovers from a different attempt instead of accidentally selecting them.
    if selected("ProseExtraction") != {r.id: r for r in prepared.extractions}:
        raise ValueError("Prose input/result inventory differs from mandatory coverage")
    if (
        selected("NativeBinding")
        or any(
            row.get("generation_id") == gen_id
            for kind in ("Symbol", "DataObject", "Commit")
            for row in store._native_rows(kind)
        )
        or store._native_relationships(set(expected_dense))
    ):
        raise ValueError("Plain prose native code/relationship inventory must be empty")


def _seal(store, prepared, **authority):
    """Compare and seal inside one local transaction; never invoke callbacks."""
    with _local(store, prepared, **authority):
        _inventory(store, prepared)
        inputs = prepared.inputs
        manifest = k.IndexManifest(
            generation_id=inputs.generation.id,
            profile_fingerprint=inputs.embedding_profile.fingerprint,
            config_fingerprint=text_hash(inputs.configuration_json),
            required_representations=("evidence", "dense", "native"),
            checksums=store.generation_checksums(inputs.generation.id),
            ready=True,
        )
        store.seal_generation(
            inputs.generation.id,
            manifest,
            **{key: authority[key] for key in ("job_id", "lease_owner", "fencing_token")},
        )
        return manifest


def write_staged_prose(
    store,
    prepared,
    *,
    job_id,
    lease_owner,
    fencing_token,
    expected_authorization_epoch,
    expected_suppression_epoch,
    check,
    batch_size=128,
):
    """Write/seal a refresh outside ambient transactions; caller owns publication."""
    if store.in_ambient_transaction():
        raise ValueError("Staged refresh wrapper requires no outer transaction")
    if type(prepared) is not PreparedProseIndex or not callable(check):
        raise ValueError("Prepared output and live build check are required")
    authority = dict(
        job_id=job_id,
        lease_owner=lease_owner,
        fencing_token=fencing_token,
        expected_authorization_epoch=expected_authorization_epoch,
        expected_suppression_epoch=expected_suppression_epoch,
    )
    for batch in _write_batches(prepared, batch_size=batch_size):
        check()
        _write_batch(store, prepared, batch, **authority)
        check()
    check()
    manifest = _seal(store, prepared, **authority)
    check()
    return manifest
