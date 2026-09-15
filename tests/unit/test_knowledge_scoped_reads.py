"""Knowledge-table reads on the managed write path: scoped by generation or by an exact key.

CC2 scoped the native reads and gave `_knowledge_rows` a closed allow-list, but the checks a managed
write makes on the *knowledge* tables were still whole-table reads, several per record written.
CC11 measured it on a code build: about three unscoped reads per evidence member, so 10 files took
1.1 s and 160 files 109.5 s. This module covers the reads that replaced them:

* `_check_knowledge_write`'s sealed-interpretation guard enumerated every member of every
  non-staging generation on *every* write. It now asks the one question it needs -- is this record
  a member of a non-staging generation -- by `record_id`, and only when the answer can refuse.
* The member-revision and exact-member tests on a `GenerationEvidenceMember` or `NativeBinding`
  write read both member tables whole. Both member kinds carry content identities, so each test is
  a primary-key lookup.
* `derivations._Inventory` read both member tables whole once per rendered passage. It is scoped
  by generation and built once per write call, and a derived record's dependencies are read by
  `derived_record_id`.

Three kinds of assertion, as in `test_generation_scoped_reads`: equal results against the unscoped
form, no whole-table read of a generation-sized kind, and CPU linear in the generation.
"""

from __future__ import annotations

import threading
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import timedelta
from pprint import pformat
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hippo.access import Principal
from hippo.context import AppContext
from hippo.ingest import repo_capture
from hippo.knowledge import model as k
from hippo.knowledge import staged_code
from hippo.knowledge.build_authority import BuildActor, BuildAuthority
from hippo.knowledge.embedding_profile import EmbeddingSpec
from hippo.knowledge.identity import canonical_json, text_hash
from hippo.knowledge.lifecycle import generation_passage_id
from hippo.knowledge.raw_artifacts import RawArtifactStore
from hippo.store import migrations
from tests.fakes.fake_store import FakeStore
from tests.unit import test_code_generation as code_generation
from tests.unit.test_build_authority import join_group
from tests.unit.test_code_generation import TREE, head_of, make_checkout
from tests.unit.test_derived_generation_store import rendered, setup_view
from tests.unit.test_generation_scoped_reads import ReadLog
from tests.unit.test_generation_store import (
    NOW,
    authority,
    claim,
    evidence,
    generation,
    native_fixture,
    passage,
    publish,
    seal,
)

# The kinds whose row count grows with the generations a store holds. A whole-table read of any of
# them on the write path is work proportional to the corpus. The authorization tables a build also
# reads whole (`AccessPolicy`, `WorkspaceMembership`, `GroupMembership`, `Workspace`,
# `Suppression`, via `build_authority` and `knowledge.access`) grow with principals and policies,
# not with evidence, and are recorded as a finding in `evidence-kscope.md` rather than asserted.
# `KnowledgeObject`, `Artifact` and `ArtifactRevision` grow with every symbol, file and commit
# (R21-M2): a proof looks a group or an observed object up in `KnowledgeObject`, and reads the
# accepted originals from the other two.
GENERATION_SIZED = frozenset(
    {
        "GenerationEvidenceMember",
        "GenerationMember",
        "NativeBinding",
        "DerivedDependency",
        "DerivedRecord",
        "RetrievalView",
        "EvidenceSpan",
        "ObjectObservation",
        "IndexManifest",
        "IndexEvent",
        "KnowledgeObject",
        "Artifact",
        "ArtifactRevision",
    }
)

# The code coordinator's authorized builder and checkout, shared with its suite rather than copied.
world = code_generation.world

# The v6 checksum recorded by every store CC2 migrated; v7 must leave it verifiable.
V6_CHECKSUM = "4b639a6ba1b60516f2cf31d74bd1aeb0e59295d3aaf7e1fd7825e85d5d95137d"


# --------------------------------------------------------------- equal results


def test_evidence_members_scoped_by_record_id_return_the_unscoped_records(store):
    """A span reused by a refresh is a member of both generations, and the key must see both."""
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
        store.add_passages([passage(gen, revision, span)])
    seal(store, gen, job)
    publish(store, gen, job)
    refresh = generation(store, "two", gen)
    refresh_job = claim(store, refresh, key="job-2")
    with store.generation_write(refresh.id, **authority(refresh_job)):
        evidence(store, refresh)

    unscoped = store._knowledge_rows("GenerationEvidenceMember")
    scoped = store._knowledge_rows("GenerationEvidenceMember", where={"record_id": span.id})
    assert sorted(scoped, key=lambda m: m.id) == sorted(
        (m for m in unscoped if m.record_id == span.id), key=lambda m: m.id
    )
    assert {m.generation_id for m in scoped} == {gen.id, refresh.id}


def test_dependencies_scoped_by_derived_record_return_the_unscoped_records(store):
    _, _, _, _, derived, dependency, _ = setup_view(store)
    unscoped = store._knowledge_rows("DerivedDependency")
    scoped = store._knowledge_rows("DerivedDependency", where={"derived_record_id": derived.id})
    assert scoped == [d for d in unscoped if d.derived_record_id == derived.id] == [dependency]


def test_the_new_scoped_fields_are_allowed_only_on_the_kind_that_is_indexed(store):
    """`RetrievalView` and `ProseExtraction` declare `derived_record_id` too, unindexed."""
    assert store._knowledge_rows("GenerationEvidenceMember", where={"record_id": "absent"}) == []
    assert store._knowledge_rows("DerivedDependency", where={"derived_record_id": "absent"}) == []
    for name in ("RetrievalView", "ProseExtraction"):
        with pytest.raises(ValueError, match="not a scoped field"):
            store._knowledge_rows(name, where={"derived_record_id": "absent"})


# ------------------------------------------------------- preserved refusals


def test_the_sealed_derivation_guards_read_only_the_record_they_guard(store):
    gen, job, span, _, derived, _, _ = setup_view(store)
    seal(store, gen, job)
    publish(store, gen, job)
    extra = k.DerivedDependency(
        derived_record_id=derived.id, input_kind="revision", input_id=span.revision_id, input_version="new"
    )
    with ReadLog(store) as log:
        with pytest.raises(ValueError, match="Sealed derivation cannot gain dependencies"):
            store.put_knowledge(extra)
        with pytest.raises(ValueError, match="Published interpretation is immutable"):
            store.update_knowledge(derived.replace(state="retired"))
    assert log.knowledge_whole_table(GENERATION_SIZED) == []
    assert ("knowledge", "GenerationEvidenceMember", {"where": {"record_id": derived.id}}) in log.calls


def test_the_sealed_proof_guards_read_only_the_record_they_guard(store):
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
        store.add_passages([passage(gen, revision, span)])
        workspace = store.get_source(gen.source_id)["workspace_id"]
        obj = k.KnowledgeObject(workspace_id=workspace, kind="table", canonical_key='["db","t"]')
        assertion = k.checked_assertion(obj, "CONTRADICTS", obj, scope_key="test")
        version = k.AssertionVersion(
            assertion_id=assertion.id,
            evidence_class="declared",
            rule_version="r",
            confidence=0.9,
            status="active",
            recorded_from=NOW,
        )
        support = k.AssertionSupport(
            assertion_version_id=version.id, span_id=span.id, derivation_group="proof"
        )
        for record in (obj, assertion, version, support):
            store.put_knowledge(record)
        for record in (version, support):
            store.put_knowledge(
                k.GenerationEvidenceMember(
                    generation_id=gen.id, record_kind=type(record).__name__, record_id=record.id
                )
            )
    seal(store, gen, job)
    publish(store, gen, job)
    with ReadLog(store) as log:
        with pytest.raises(ValueError, match="Sealed assertion proof group cannot gain support"):
            store.put_knowledge(support.replace(derivation_group="new-proof"))
        with pytest.raises(ValueError, match="Published interpretation is immutable"):
            store.update_knowledge(version.replace(recorded_to=NOW + timedelta(days=1)))
    assert log.knowledge_whole_table(GENERATION_SIZED) == []
    assert ("knowledge", "GenerationEvidenceMember", {"where": {"record_id": version.id}}) in log.calls


# --------------------------------------------------------------- bounded work


def test_writing_evidence_and_bindings_reads_no_generation_sized_table_whole(store):
    gen = generation(store)
    job = claim(store, gen)
    with ReadLog(store) as log:
        native_fixture(store, gen, job)
    assert log.knowledge_whole_table(GENERATION_SIZED) == []


def test_a_write_the_sealed_guard_cannot_refuse_reads_no_membership(store):
    """The guard used to enumerate every sealed member before learning it had nothing to check."""
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        evidence(store, gen)
        obj = k.KnowledgeObject(
            workspace_id=store.get_source(gen.source_id)["workspace_id"],
            kind="symbol",
            canonical_key='["a","g"]',
        )
        with ReadLog(store) as log:
            store.put_knowledge(obj)
    assert [call for call in log.calls if call[1] == "GenerationEvidenceMember"] == []


def rendered_rows(store, gen, count, *, start=0):
    """`count` rendered passages over distinct spans of one revision, their derivations staged."""
    revision, base = evidence(store, gen)
    rows = []
    for index in range(start, start + count):
        span = k.EvidenceSpan(
            revision_id=revision.id,
            locator_kind="file_lines",
            locator_json=canonical_json(
                {"end": index + 2, "kind": "file_lines", "path": "a.txt", "start": index + 2}
            ),
            text=f"line {index}",
            policy_id=base.policy_id,
        )
        store.put_knowledge(span)
        store.put_knowledge(
            k.GenerationEvidenceMember(generation_id=gen.id, record_kind="EvidenceSpan", record_id=span.id)
        )
        view, _, _ = rendered(store, gen, span, text=f"rendered card {index}")
        row = passage(gen, revision, span)
        row.update(
            retrieval_view_id=view.id,
            text=view.text,
            id=generation_passage_id(gen.id, revision.id, span.id, 0, retrieval_view_id=view.id),
        )
        rows.append(row)
    return rows


def test_rendered_passages_validate_against_one_inventory_per_write(store):
    """`validate_view` built a fresh `_Inventory` -- two member-table reads -- for every passage."""
    gen = generation(store)
    job = claim(store, gen)
    counts = {}
    with store.generation_write(gen.id, **authority(job)):
        for size, start in ((4, 0), (16, 100)):
            rows = rendered_rows(store, gen, size, start=start)
            with ReadLog(store) as log:
                store.add_passages(rows)
            counts[size] = len(
                [c for c in log.calls if c[1] in ("GenerationEvidenceMember", "GenerationMember")]
            )
    assert counts[16] == counts[4], f"member reads per write: {counts[4]} for 4 passages, {counts[16]} for 16"


def test_sealing_and_publishing_a_rendered_generation_reads_no_generation_sized_table_whole(store):
    gen, job, *_ = setup_view(store)
    with ReadLog(store) as log:
        seal(store, gen, job)
        publish(store, gen, job)
    assert log.knowledge_whole_table(GENERATION_SIZED) == []


# ------------------------------------------------------------ the code build

MODULE = '''"""Module {i}."""


class Service{i}:
    """Service number {i}."""

    def place(self, order):
        return helper_{i}(order)

    def save(self, order):
        return order


def helper_{i}(value):
    return value + {i}
'''


def build_synthetic(w, tmp_path, count, *, batch_size=128):
    """Build a new repository source of `count` generated modules plus the fixture tree.

    `w` is `world` or a `fresh_builder`: anything carrying a store, its context, an authorized
    user and actor, a raw store and the coordinator module.
    """
    from hippo.ingest.code_generation import CodeBuildOptions, CodeTreeInput

    url = f"https://git.example.com/acme/synthetic-{count}.git"
    source = w.store.create_source("repo", f"synthetic-{count}", {"url": url}, owner_id=w.user)
    files = {**TREE, **{f"pkg/mod{i}.py": MODULE.format(i=i) for i in range(count)}}
    checkout = make_checkout(tmp_path, files=files, name=f"synthetic-{count}")
    tree = CodeTreeInput(
        root=checkout.resolve(),
        kind="repo",
        repository=repo_capture.repository_descriptor(url),
        head_revision=head_of(checkout),
    )
    return w.module.build_code_source(
        w.ctx,
        source_id=source,
        actor=w.actor,
        tree=tree,
        options=CodeBuildOptions(
            batch_size=batch_size, renewal_interval_seconds=120.0, lease_duration_seconds=3600.0
        ),
        raw_store=w.raw,
        embedding_spec=EmbeddingSpec(dimensions=2),
        operation_id=f"synthetic-{count}",
        should_stop=lambda: False,
    )


def test_a_code_build_reads_no_generation_sized_table_whole(world, tmp_path):
    w = world
    with ReadLog(w.store) as log:
        result = build_synthetic(w, tmp_path, 10)
    assert w.store._knowledge_rows("GenerationEvidenceMember", generation_id=result.generation_id)
    assert log.knowledge_whole_table(GENERATION_SIZED) == []


def test_a_group_member_code_build_reads_no_generation_sized_table_whole(world, tmp_path):
    """R21-M2: a builder in any group read `KnowledgeObject` whole on every `check_local`.

    An unrelated generation is published first, so the table that read walked already holds another
    source's symbols, files and commits; the build's own proofs must look the group up by ID.
    """
    w = world
    build_synthetic(w, tmp_path, 3)
    group = join_group(w)
    with ReadLog(w.store) as log:
        result = build_synthetic(w, tmp_path, 10)
    assert result.outcome == "published"
    assert log.knowledge_whole_table(GENERATION_SIZED) == []
    assert ("knowledge", "KnowledgeObject", {"ids": [group.id]}) in log.calls


@contextmanager
def rows_by_batch(store):
    """Rows every store read returns during a build, by write batch and by reader, and each batch's size.

    Yields `(rows, written)`. A read made inside `BuildAuthority.check_local` is the authority's; any
    other is the writer's, the coordinator's own reads included. Batch `n` runs from the start of
    the `n`th `staged_code._write_batch` call to the start of the next, so it holds that batch's
    write and the rebaseline test and checks around it; `-1` is everything before the first.
    `written[n]` is the number of records batch `n` writes. `_knowledge_get` reads through
    `_knowledge_rows`, so counting that and `get_source` counts every knowledge and Source row a
    check or a write returns. Plain functions as instance attributes, removed on exit, for the
    reason `test_query_scoped_reads.knowledge_reads` gives.
    """
    local, batch, rows, written = threading.local(), [-1], defaultdict(Counter), {}
    knowledge_rows, get_source = store._knowledge_rows, store.get_source
    check_local, write_batch = BuildAuthority.check_local, staged_code._write_batch

    def reader():
        return "authority" if getattr(local, "depth", 0) else "writer"

    def counted_rows(name, **scope):
        result = knowledge_rows(name, **scope)
        key = ",".join(sorted(field for field, value in scope.items() if value is not None)) or "whole"
        rows[batch[0]][(reader(), name, key)] += len(result)
        return result

    def counted_source(identity):
        result = get_source(identity)
        rows[batch[0]][(reader(), "Source", "id")] += result is not None
        return result

    def counted_check(authority):
        local.depth = getattr(local, "depth", 0) + 1
        try:
            return check_local(authority)
        finally:
            local.depth -= 1

    def counted_batch(store, prepared, records, **authority):
        batch[0] += 1
        written[batch[0]] = len(records)
        return write_batch(store, prepared, records, **authority)

    store._knowledge_rows, store.get_source = counted_rows, counted_source
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(BuildAuthority, "check_local", counted_check)
            patch.setattr(staged_code, "_write_batch", counted_batch)
            yield rows, written
    finally:
        del store._knowledge_rows, store.get_source


def fresh_builder(w, tmp_path, count):
    """An authorized builder on its own empty Fake store, as CC11's probe had one per size.

    It shares only the model endpoint and configuration with `world`, so every timed build starts
    from nothing and its cost per member is comparable across sizes and with CC11's numbers.
    """
    store = FakeStore()
    store.ensure_schema()
    store.ensure_roles()
    user = store.create_user("builder", "password", "individual")
    store.put_knowledge(
        k.WorkspaceMembership(
            workspace_id=migrations.DEFAULT_WORKSPACE_ID,
            principal_id=user,
            mapping_authority="local",
            enabled=True,
            policy_epoch=1,
        )
    )
    store.set_meta("reviewed_mapping_authorities", ["local"])
    return SimpleNamespace(
        store=store,
        user=user,
        actor=BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual"))),
        ctx=AppContext(config=w.ctx.config, store=store, ollama=w.ctx.ollama),
        raw=RawArtifactStore(tmp_path / f"raw-{count}", max_object_bytes=2_000_000),
        module=w.module,
    )


# The reads a write batch still makes that return the generation's whole membership. `native_write`
# builds one `GenerationViews` per call (`store/generations.py`), and its inventory reads both member
# tables by `generation_id` (`knowledge/derivations.py`) whenever the batch writes a rendered view.
# Carrying one inventory across a build's batches is the writer's (R21-M1, CD1 states it); when it
# lands the pin below fails and this set is emptied.
GENERATION_MEMBERSHIP_READS = frozenset(
    {("writer", "GenerationEvidenceMember", "generation_id"), ("writer", "GenerationMember", "generation_id")}
)

# A write batch's own reads are point reads per record it writes, and a batch of dependency groups
# holds as many records as its groups do: a commit touching every file is one group. So the writer is
# compared per record written, and the two corpora may differ by at most this factor.
BATCH_FACTOR = 1.25


def test_a_write_batch_proves_its_authority_in_rows_the_corpus_does_not_change(world, tmp_path):
    """R21-M1: every write batch at two corpus sizes, counted in rows returned rather than CPU time.

    Every `check_local` re-proved every accepted pair and span -- a stored-identity read per record
    and a Source read per artifact, twice -- and a batch makes six of them, so the authority's rows
    per batch grew with the corpus and a build's with members x batches: at most 762 rows in a batch
    at 10 files and 1,482 at 40 before. The CPU test this replaces admitted that with a 3.0 factor
    over a measured 1.9x. The peak over the write batches is compared, so no batch is chosen by hand.
    """
    if world.store.knowledge_backend != "fake":
        pytest.skip("the scale builds run on fresh Fake stores; CD9 owns the Ladybug fixture")
    measured = {}
    for count in (10, 40):
        builder = fresh_builder(world, tmp_path, count)
        with rows_by_batch(builder.store) as (rows, written):
            build_synthetic(builder, tmp_path, count, batch_size=16)
        # Every write batch but the last, which runs on through the seal and the publication.
        measured[count] = [(rows[index], written[index]) for index in range(max(rows))]

    def peak(count, keep, *, per_record=False):
        return max(
            sum(value for key, value in batch.items() if keep(key)) / (records if per_record else 1)
            for batch, records in measured[count]
        )

    def authority(key):
        return key[0] == "authority"

    def batch_own(key):
        return key[0] == "writer" and key not in GENERATION_MEMBERSHIP_READS

    def membership(key):
        return key in GENERATION_MEMBERSHIP_READS

    report = pformat(
        {
            count: {
                "authority rows": peak(count, authority),
                "writer rows per record": round(peak(count, batch_own, per_record=True), 2),
                "membership rows": peak(count, membership),
                "write batches": len(measured[count]),
            }
            for count in measured
        }
    )
    assert peak(40, authority) == peak(10, authority), report
    assert peak(40, batch_own, per_record=True) <= peak(10, batch_own, per_record=True) * BATCH_FACTOR, report
    # Pinned, not endorsed: the generation-sized read R21-M1 leaves to the writer.
    assert peak(40, membership) >= 3 * peak(10, membership), report


def test_the_fake_snapshot_shares_only_records_no_write_can_change(store):
    """`FakeStore.transaction()` copies `_knowledge_data` per kind and shares the records in it.

    That is sound only while every record is immutable and every write replaces a record rather
    than changing one, so both halves are asserted: no stored record can be mutated in place, and
    a rolled-back put and replace leave exactly the prior dicts holding the prior records.
    """
    if store.knowledge_backend != "fake":
        pytest.skip("the snapshot under test is the Fake store's rollback")
    assert all(model.model_config.get("frozen") is True for model in k.RECORD_TYPES.values())
    gen, job, *_ = setup_view(store)
    stored = [record for rows in store._knowledge_data.values() for record in rows.values()]
    assert {"Generation", "MaintenanceJob", "DerivedDependency", "GenerationEvidenceMember"} <= {
        type(record).__name__ for record in stored
    }
    for record in stored:
        with pytest.raises(ValidationError, match="frozen"):
            record.id = "changed"
    before = {kind: dict(rows) for kind, rows in store._knowledge_data.items()}
    workspace = store.get_source(gen.source_id)["workspace_id"]
    with pytest.raises(RuntimeError, match="injected"):
        with store.transaction():
            store.put_knowledge(
                k.KnowledgeObject(workspace_id=workspace, kind="symbol", canonical_key='["rollback","f"]')
            )
            store._write_knowledge(
                store._knowledge_get("MaintenanceJob", job.id).replace(lease_owner="other")
            )
            assert store._knowledge_data != before
            raise RuntimeError("injected")
    assert store._knowledge_data == before
    assert all(
        store._knowledge_data[kind][identity] is record
        for kind, rows in before.items()
        for identity, record in rows.items()
    )


# ------------------------------------------------------------------- schema v7


def test_schema_version_seven_journals_the_knowledge_scope_indexes(store):
    assert migrations.CURRENT_SCHEMA_VERSION == 8
    assert [*migrations.SUPPORTED_CHECKSUMS] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert migrations.SUPPORTED_CHECKSUMS[6] == V6_CHECKSUM
    assert migrations.SUPPORTED_CHECKSUMS[7] == migrations.V7_CHECKSUM != V6_CHECKSUM
    assert migrations.SUPPORTED_CHECKSUMS[8] == migrations.MIGRATION_CHECKSUM != migrations.V7_CHECKSUM
    steps = migrations.schema_steps(store, version=7)
    if store.knowledge_backend == "ladybug":
        # Probed by CC2 on real_ladybug 0.15.3: no secondary-index DDL exists in the dialect.
        assert steps == []
        return
    assert steps == [
        "CREATE INDEX knowledge_deriveddependency_derived_record_id IF NOT EXISTS "
        "FOR (n:DerivedDependency) ON (n.derived_record_id)",
        "CREATE INDEX knowledge_generationevidencemember_record_id IF NOT EXISTS "
        "FOR (n:GenerationEvidenceMember) ON (n.record_id)",
    ]


def test_the_v6_descriptor_and_step_list_are_frozen(store):
    """A v6 journal row counts eight steps; growing that list would refuse every v6 store."""
    assert text_hash(canonical_json(migrations._descriptor(6))) == V6_CHECKSUM
    steps = migrations.schema_steps(store, version=6)
    if store.knowledge_backend == "ladybug":
        assert steps == []
        return
    assert steps == [
        "CREATE INDEX symbol_generation IF NOT EXISTS FOR (n:Symbol) ON (n.generation_id)",
        "CREATE INDEX data_object_generation IF NOT EXISTS FOR (n:DataObject) ON (n.generation_id)",
        "CREATE INDEX commit_generation IF NOT EXISTS FOR (n:Commit) ON (n.generation_id)",
        "CREATE INDEX passage_generation IF NOT EXISTS FOR (n:Passage) ON (n.generation_id)",
        "CREATE INDEX knowledge_indexevent_aggregate_id IF NOT EXISTS FOR (n:IndexEvent) ON (n.aggregate_id)",
        "CREATE INDEX knowledge_maintenancejob_input_fingerprint IF NOT EXISTS "
        "FOR (n:MaintenanceJob) ON (n.input_fingerprint)",
        "CREATE INDEX knowledge_suppression_target_id IF NOT EXISTS FOR (n:Suppression) ON (n.target_id)",
        "CREATE INDEX knowledge_suppression_target_kind IF NOT EXISTS FOR (n:Suppression) ON (n.target_kind)",
    ]


def test_every_kind_scoped_field_is_indexed_by_exactly_one_journaled_step(store):
    from hippo.store.knowledge import KIND_SCOPED_FIELDS

    v6 = {(label, field) for _, label, field in migrations.NATIVE_INDEXES}
    v7 = {(label, field) for _, label, field in migrations.V7_INDEXES}
    declared = {(label, field) for label, fields in KIND_SCOPED_FIELDS.items() for field in fields}
    assert (
        declared
        == v6 - {(label, "generation_id") for label in ("Symbol", "DataObject", "Commit", "Passage")} | v7
    )
    assert not v6 & v7
    assert {("GenerationEvidenceMember", "record_id"), ("DerivedDependency", "derived_record_id")} == v7
