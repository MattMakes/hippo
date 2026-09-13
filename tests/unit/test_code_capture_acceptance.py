"""Gate CD9: a multi-hundred-file repository converts, reopens, projects, refreshes and retires.

The acceptance backend is LadybugDB; the file is GREEN on Fake first, like every gate. The
repository is `tests/fakes/code_capture_repo.py`'s: several hundred files across the five walker
languages plus SQL and config, a README, extensionless files, an ignored `node_modules`, one
oversized file, one binary, one symlink and a handful of real commits.

One scenario rather than one build per test, because every phase needs the state the previous
one left and a LadybugDB code build over this tree costs minutes: a bootstrap crashes mid-batch,
the store is closed and reopened, the same generation resumes and publishes, the store is
reopened again, the published generation is projected and dispatched, and a refresh publishes
over it while a query still holds the first generation.

What this file does NOT claim (design review M4 and M5; CC2, CC9b):

* The fixture stays far below `CODE_MAX_SYMBOLS_PER_SOURCE` (50,000). The CD1 linearity proof at
  that ceiling is CC2's synthetic Fake test
  (`test_generation_scoped_reads.py::test_sealing_at_the_symbol_ceiling_completes` and
  `::test_sealing_is_linear_in_the_generation`), not this run.
* The index-backed half of the CD1 bound is proven on Neo4j (root parity run 2). LadybugDB 0.15.3
  has no secondary-index DDL, so on the acceptance backend the bound is the recorded read scopes
  and the query predicates only.
* No wall-clock time is asserted. The evidence file records how long the run took.
"""

from __future__ import annotations

import importlib
import json
import os
from contextlib import contextmanager
from dataclasses import replace
from threading import local
from types import SimpleNamespace

import httpx
import pytest

from hippo.access import EVERYTHING, Principal
from hippo.codegraph.model import CODE_MAX_FILE_BYTES, CODE_MAX_FILES, CODE_MAX_SYMBOLS_PER_SOURCE
from hippo.ingest import repo_capture
from hippo.ingest.pipeline import MAX_CHUNKS
from hippo.knowledge import model as k
from hippo.knowledge import staged_code
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.dense_session import dense_session, retrieval_session
from hippo.knowledge.embedding_profile import EmbeddingSpec
from hippo.knowledge.query_access import query_session
from hippo.knowledge.raw_artifacts import RawArtifact, RawArtifactStore
from hippo.ollama import Ollama
from tests.unit.test_code_generation import Runtime

CLONE_URL = "https://git.example.com/acme/fleet.git"

# The size the ledger's CD9 line runs. The override exists for sizing a scratch run only.
FILES_PER_LANGUAGE = int(os.environ.get("HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE", "48"))

NATIVE_KINDS = ("Symbol", "DataObject", "Commit")


def builder():
    try:
        return importlib.import_module("tests.fakes.code_capture_repo")
    except ModuleNotFoundError:
        pytest.fail("The multi-hundred-file code capture fixture builder is missing")


# ------------------------------------------------------------------ the fixture itself


def test_the_fixture_repository_is_deterministic_and_holds_every_capture_shape(tmp_path):
    fixture = builder()
    first = fixture.build_code_capture_repository(tmp_path / "one", files_per_language=FILES_PER_LANGUAGE)
    second = fixture.build_code_capture_repository(tmp_path / "two", files_per_language=FILES_PER_LANGUAGE)

    assert first.commits == second.commits and len(first.commits) >= 4, "pinned identities and dates"
    assert first.files == second.files
    if FILES_PER_LANGUAGE == 48:
        assert len(first.accepted) >= 250, "the ledger's run is several hundred files"
    assert set(first.languages) == {"python", "typescript", "go", "csharp", "rust", "sql"}
    assert all(len(paths) >= FILES_PER_LANGUAGE for name, paths in first.languages.items() if name != "sql")
    assert {"ignored_path", "too_large", "binary", "symlink", "unsupported_language"} <= set(first.excluded)
    assert first.prose and first.unparsed and "go.mod" in first.unparsed
    assert (first.root / next(iter(first.excluded["symlink"]))).is_symlink()
    oversized = next(iter(first.excluded["too_large"]))
    assert (first.root / oversized).stat().st_size > repo_capture.readers.MAX_FILE_BYTES
    assert all(
        len(first.files[path]) <= CODE_MAX_FILE_BYTES
        for name in first.languages
        for path in first.languages[name]
    )


# ------------------------------------------------------------------ the world


def instrument(w, store):
    """Count transaction depth (the model endpoint refuses HTTP inside one) and native read scopes."""
    original_transaction = store.transaction

    @contextmanager
    def transaction():
        with original_transaction():
            w.transaction_state.depth = getattr(w.transaction_state, "depth", 0) + 1
            try:
                yield
            finally:
                w.transaction_state.depth -= 1

    native_rows, relationships = store._native_rows, store._native_relationships

    def scoped_native_rows(kind, **scope):
        if w.recording:
            w.native_reads.append((kind, {key: value is not None for key, value in scope.items()}))
        return native_rows(kind, **scope)

    def scoped_relationships(**scope):
        if w.recording:
            w.relationship_reads.append({key: value is not None for key, value in scope.items()})
        return relationships(**scope)

    # Plain functions, never bound methods, as instance attributes: the Fake store deep-copies
    # its own attributes at every transaction, and a bound method would copy the store inside it.
    store.transaction = transaction
    store._native_rows = scoped_native_rows
    store._native_relationships = scoped_relationships


def make_world(ctx, tmp_path):
    store = ctx.store
    w = SimpleNamespace(ctx=ctx, tmp_path=tmp_path, transaction_state=local(), reopened=[])
    w.recording, w.native_reads, w.relationship_reads, w.batches = False, [], [], []
    instrument(w, store)
    store.ensure_schema()
    store.ensure_roles()
    w.user = store.create_user("builder", "password", "individual")
    w.source = store.create_source("repo", "fleet", {"url": CLONE_URL}, owner_id=w.user)
    workspace = store.get_source(w.source)["workspace_id"]
    store.put_knowledge(
        k.WorkspaceMembership(
            workspace_id=workspace,
            principal_id=w.user,
            mapping_authority="local",
            enabled=True,
            policy_epoch=1,
        )
    )
    store.set_meta("reviewed_mapping_authorities", ["local"])
    w.actor = BuildActor.reader(Principal.for_user(store.get_user(w.user), store.get_role("individual")))
    w.runtime = Runtime(w.transaction_state)
    ctx.ollama = Ollama(
        "http://local-model",
        "chat:latest",
        "embed:latest",
        num_ctx=8192,
        client=httpx.Client(base_url="http://local-model", transport=httpx.MockTransport(w.runtime.handle)),
    )
    # The activation adapter's cap: every raw object is a captured file or the manifest.
    w.raw = RawArtifactStore(tmp_path / "raw", max_object_bytes=32_000_000)
    w.repo = builder().build_code_capture_repository(
        tmp_path / "fleet", files_per_language=FILES_PER_LANGUAGE
    )
    w.module = importlib.import_module("hippo.ingest.code_generation")
    w.tree = w.module.CodeTreeInput(
        root=w.repo.root.resolve(),
        kind="repo",
        repository=repo_capture.repository_descriptor(CLONE_URL),
        head_revision=w.repo.head,
    )
    # Every ceiling at the reviewed default. Only the lease is lengthened: it is operational,
    # outside identity, and a slow LadybugDB seal must not turn into a lost fence.
    w.options = w.module.CodeBuildOptions(lease_duration_seconds=3600.0, renewal_interval_seconds=120.0)
    return w


def build(w, *, operation, tree=None, on_progress=None):
    # Native read counts at the start of the build and after every write batch: the per-batch
    # bound is measured inside one build, never across the projection reads between builds.
    marks = [len(w.native_reads)]
    if w.recording:
        w.batches.append(marks)

    def progress(update):
        if update.phase == "write":
            marks.append(len(w.native_reads))
        if on_progress is not None:
            on_progress(update)

    return w.module.build_code_source(
        w.ctx,
        source_id=w.source,
        actor=w.actor,
        tree=tree or w.tree,
        options=w.options,
        raw_store=w.raw,
        embedding_spec=EmbeddingSpec(dimensions=2),
        operation_id=operation,
        should_stop=lambda: False,
        on_progress=progress,
    )


def reopen(w):
    """Close the store and open the same database again. The Fake store has no second life."""
    store = w.ctx.store
    if store.knowledge_backend == "fake":
        return
    store.close()
    if store.knowledge_backend == "ladybug":
        from hippo.store.ladybug import LadybugStore

        fresh = LadybugStore(store.path)
    else:
        from hippo.store import Store

        fresh = Store(
            os.environ["NEO4J_URI"],
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "hippo-password"),
        )
    w.reopened.append(fresh)
    instrument(w, fresh)
    w.ctx.store = fresh
    w.ctx.invalidate_graph()


# ------------------------------------------------------------------ what must survive


def durable_state(w, generation_id):
    """Everything CD9 names as surviving a close and reopen, read back through the store."""
    store = w.ctx.store
    source = store.get_source(w.source)
    generation = store._knowledge_get("Generation", generation_id)
    evidence = store._knowledge_rows("GenerationEvidenceMember", generation_id=generation_id)
    revisions = store._knowledge_rows("GenerationMember", generation_id=generation_id)
    jobs = store._knowledge_rows("MaintenanceJob", where={"input_fingerprint": generation_id})
    return {
        "pointers": {
            key: source.get(key)
            for key in ("active_generation_id", "managed", "status", "build_fencing_token", "active_build_id")
        },
        "generation": generation.model_dump(mode="json"),
        "coverage": json.loads(generation.coverage_json),
        "revision_members": sorted(m.model_dump_json() for m in revisions),
        "evidence_members": sorted(m.model_dump_json() for m in evidence),
        "bindings": sorted(
            b.model_dump_json() for b in store._knowledge_rows("NativeBinding", generation_id=generation_id)
        ),
        "manifests": sorted(
            m.model_dump_json() for m in store._knowledge_rows("IndexManifest", generation_id=generation_id)
        ),
        "jobs": sorted(j.model_dump_json() for j in jobs),
        "native": {
            kind: sorted(
                json.dumps(row, sort_keys=True, default=str)
                for row in store._native_rows(kind, generation_id=generation_id)
            )
            for kind in (*NATIVE_KINDS, "Passage")
        },
        "relations": json.dumps(store._native_relationships(generation_id=generation_id), default=str),
        "raw": sorted(
            store._knowledge_get("ArtifactRevision", m.artifact_revision_id).raw_uri for m in revisions
        ),
    }


def file_revisions(w, generation_id):
    """Accepted file path -> its revision, for one generation."""
    store = w.ctx.store
    found = {}
    for member in store._knowledge_rows("GenerationMember", generation_id=generation_id):
        revision = store._knowledge_get("ArtifactRevision", member.artifact_revision_id)
        artifact = store._knowledge_get("Artifact", revision.artifact_id)
        if artifact.kind == "file":
            found[artifact.external_id] = revision
    return found


def assert_raw_references_resolve(w, generation_id):
    for path, revision in file_revisions(w, generation_id).items():
        artifact = RawArtifact.from_uri(revision.raw_uri, byte_length=len(w.repo.files[path]))
        assert w.raw.read_bytes(artifact) == w.repo.files[path], f"raw object for {path} does not read back"


# ------------------------------------------------------------------ the phases


def crash_the_bootstrap(w, monkeypatch, *, after=3):
    original = staged_code._write_batch
    state = {"written": 0}

    def crash(store, prepared, batch, **authority):
        if state["written"] == after:
            raise RuntimeError("injected crash between batches")
        state["written"] += 1
        return original(store, prepared, batch, **authority)

    with monkeypatch.context() as patch:
        patch.setattr(staged_code, "_write_batch", crash)
        with pytest.raises(RuntimeError, match="injected crash"):
            build(w, operation="bootstrap")
    store = w.ctx.store
    (staged,) = store._knowledge_rows("Generation")
    assert staged.status == "failed" and store.get_source(w.source)["active_generation_id"] is None
    assert store._knowledge_rows("GenerationEvidenceMember", generation_id=staged.id), "staged rows retained"
    return staged, durable_state(w, staged.id)


def assert_exact_membership(w, generation_id):
    """The accepted inventory is the fixture's, file for file and reason for reason."""
    store = w.ctx.store
    repo = w.repo
    assert set(file_revisions(w, generation_id)) == repo.accepted
    coverage = json.loads(store._knowledge_get("Generation", generation_id).coverage_json)
    assert coverage["files_accepted"] == len(repo.accepted)
    for reason, paths in repo.excluded.items():
        assert coverage["files_excluded"].get(reason, 0) >= len(paths), reason
    reasons = coverage["openie_reasons"]
    assert all(reasons[path] == w.module.OPENIE_PROSE_DEFERRED for path in repo.prose)
    assert all(reasons[path] == w.module.OPENIE_UNPARSED for path in repo.unparsed)
    assert all(
        reasons[path] == w.module.OPENIE_CODE for name in repo.languages for path in repo.languages[name]
    )
    assert coverage["history"] == "read" and coverage["history_walk"] == "first_parent"
    assert coverage["history_commits"] == len(repo.commits)
    history = [
        a for a in store._knowledge_rows("Artifact") if a.kind == "history_event" and a.source_id == w.source
    ]
    assert len(history) >= len(repo.commits)


def assert_native_defined_in_support(w, generation_id, graph):
    """Exact DEFINED_IN support in the sealed native representation.

    Every native DEFINED_IN row of the generation joins a bound native node of the generation to
    a dense passage of the generation whose original spans include the node's binding span.
    """
    store = w.ctx.store
    bindings = {
        (b.native_kind, b.native_id): b
        for b in store._knowledge_rows("NativeBinding", generation_id=generation_id)
    }
    native = {
        row["id"]: kind
        for kind in NATIVE_KINDS
        for row in store._native_rows(kind, generation_id=generation_id)
    }
    passages = {row["id"] for row in store._native_rows("Passage", generation_id=generation_id)}
    originals = {row.passage_id: set(row.original_span_ids) for row in graph.retrieval_evidence}
    defined = [
        row for row in store._native_relationships(generation_id=generation_id) if row[0] == "DEFINED_IN"
    ]
    assert defined, "a code generation writes DEFINED_IN"
    for _rel, node, passage, _payload in defined:
        assert node in native and passage in passages
        assert bindings[(native[node], node)].span_id in originals[passage], (node, passage)
    attached = {row[1] for row in defined}
    symbols = [node for node, kind in native.items() if kind == "Symbol"]
    assert symbols and set(symbols) <= attached, "every bound symbol is written down in a passage"


def assert_projection(w, generation_id):
    """StructuralCodeEvidence with exact original spans, and citations with real line locators."""
    store = w.ctx.store
    with query_session(w.ctx, EVERYTHING, structural=True) as session:
        graph = session.graph
        assert graph.selected_managed_generations == ((w.source, generation_id),)
        nodes = {node.id: node for node in graph.code_nodes}
        assert {"symbol", "commit", "data"} <= {node.kind for node in nodes.values()}
        citations = {row.id: row for row in graph.original_citations}
        defined = {
            graph.node_ids[a.src] for rows in graph.code_out.values() for a in rows if a.kind == "DEFINED_IN"
        }
        sidecar = {row.node_id: row for row in graph.structural_code_evidence}
        assert set(nodes) <= defined | set(sidecar), "every code node carries structural support"
        observed = {}
        for member in store._knowledge_rows("GenerationEvidenceMember", generation_id=generation_id):
            if member.record_kind == "ObjectObservation":
                row = store._knowledge_get("ObjectObservation", member.record_id)
                observed.setdefault(row.object_id, set()).add(row.span_id)
        for node_id, row in sidecar.items():
            assert (row.generation_id, row.source_id) == (generation_id, w.source)
            assert set(row.original_span_ids) == observed[node_id], "exact original spans"
            assert set(row.original_span_ids) <= set(citations)
        located = 0
        for citation in citations.values():
            if citation.locator_kind != "file_lines":
                continue
            locator = json.loads(citation.locator_json)
            lines = w.repo.files[locator["path"]].decode().splitlines()
            assert 1 <= locator["start"] <= locator["end"] <= len(lines), locator
            window = "\n".join(lines[locator["start"] - 1 : locator["end"]])
            assert citation.text.strip() == window.strip(), locator
            located += 1
        assert located >= len(w.repo.accepted) // 2, "code citations are real line ranges"
        symbol_spans = {
            span for node in nodes.values() if node.kind == "symbol" for span in observed[node.id]
        }
        assert all(citations[span].locator_kind == "file_lines" for span in symbol_spans)
        assert_native_defined_in_support(w, generation_id, graph)
        return {node.id for node in nodes.values()}, {row.id for row in graph.passages}


def assert_verified_dense_dispatch(w, generation_id):
    with retrieval_session(w.ctx, EVERYTHING) as session:
        assert session.graph.dense_capability.mode == "verified"
        session.graph.require_dense(session.model.profile_fingerprint)
        assert {row.generation_id for row in session.graph.dense_vectors} == {generation_id}
    with dense_session(w.ctx, EVERYTHING) as session:
        assert session.graph.dense_capability.mode == "verified"
    assert [path for path, _ in w.runtime.calls if path == "/api/chat"] == []


def refresh_under_a_live_snapshot(w, first, before):
    """A refresh retires G1 while a held query still reconstructs it exactly."""
    store = w.ctx.store
    changed = w.repo.refresh()
    tree = replace(w.tree, head_revision=changed.head)
    with query_session(w.ctx, EVERYTHING, structural=True) as held:
        second = build(w, operation="refresh", tree=tree)
        held.validate()
        assert store._knowledge_get("Generation", first).status == "retired"
        assert store.get_source(w.source)["active_generation_id"] == second.generation_id
        assert held.graph.selected_managed_generations == ((w.source, first),)
        assert (
            {node.id for node in held.graph.code_nodes},
            {row.id for row in held.graph.passages},
        ) == before
        assert {row.generation_id for row in held.graph.structural_code_evidence} == {first}
    with query_session(w.ctx, EVERYTHING, structural=True) as current:
        assert current.graph.selected_managed_generations == ((w.source, second.generation_id),)
    return second, changed


def assert_retired_generation_reconstructs(w, generation_id, published):
    store = w.ctx.store
    manifest = store.validate_generation_seal(generation_id)
    assert store.generation_checksums(generation_id) == manifest.checksums
    state = durable_state(w, generation_id)
    for key in (
        "revision_members",
        "evidence_members",
        "bindings",
        "manifests",
        "native",
        "relations",
        "raw",
    ):
        assert state[key] == published[key], key
    assert_raw_references_resolve(w, generation_id)


def assert_refresh_reuses_immutable_revisions(w, first, second, changed):
    old, new = file_revisions(w, first), file_revisions(w, second)
    assert old.keys() == new.keys() == w.repo.accepted
    assert old[changed.changed] != new[changed.changed]
    unchanged = w.repo.accepted - {changed.changed}
    assert all(old[path] == new[path] for path in unchanged), "one record, first observed_at kept"
    shared = {
        m.artifact_revision_id for m in w.ctx.store._knowledge_rows("GenerationMember", generation_id=first)
    } & {
        m.artifact_revision_id for m in w.ctx.store._knowledge_rows("GenerationMember", generation_id=second)
    }
    assert len(shared) >= len(unchanged) + len(w.repo.commits), "unchanged files and prior commits are reused"


def assert_within_ceilings(w, generation_ids):
    options = w.options
    assert (options.max_files, options.max_symbols, options.max_chunks) == (
        CODE_MAX_FILES,
        CODE_MAX_SYMBOLS_PER_SOURCE,
        MAX_CHUNKS,
    )
    assert options.max_batch_payload_bytes == staged_code.PAYLOAD_CEILING_BYTES == 64 * 1024 * 1024
    for generation_id in generation_ids:
        coverage = json.loads(w.ctx.store._knowledge_get("Generation", generation_id).coverage_json)
        assert coverage["files_accepted"] <= CODE_MAX_FILES
        assert 0 < coverage["symbols"] < CODE_MAX_SYMBOLS_PER_SOURCE, "far below the ceiling, by design"
        assert sum(coverage["passages"].values()) <= MAX_CHUNKS
        assert coverage["code_truncated"] is False


# CC2's shape (`test_batched_writes_do_a_constant_number_of_reads_per_batch`): native reads per
# write batch are a constant of the batch plan, not of the corpus. Measured on this fixture at no
# more than 20 per batch with 2 files per language and 12 with 8; a read per row or per dependency
# group would be hundreds.
NATIVE_READS_PER_BATCH = 32


def assert_cd1_bound(w):
    """CD1 as CC2 proves it: no whole-table native read, no unscoped relationship read, and a
    per-batch native read count that does not grow with the corpus."""
    whole = [(kind, scope) for kind, scope in w.native_reads if not any(scope.values())]
    assert whole == [], f"whole-table native reads during a managed build: {whole[:5]}"
    assert w.relationship_reads and all(any(scope.values()) for scope in w.relationship_reads)
    per_batch = [
        later - earlier for marks in w.batches for earlier, later in zip(marks, marks[1:], strict=False)
    ]
    assert len(per_batch) > 3, "the builds staged over many transactions"
    assert max(per_batch) <= NATIVE_READS_PER_BATCH, f"native reads per write batch: {per_batch}"


# ------------------------------------------------------------------ the scenario


def test_a_multi_hundred_file_repository_holds_every_cd9_guarantee(ctx, tmp_path, monkeypatch):
    w = make_world(ctx, tmp_path)
    try:
        w.recording = True
        staged, crashed_state = crash_the_bootstrap(w, monkeypatch)

        reopen(w)
        assert durable_state(w, staged.id) == crashed_state, "resumable staging state survives reopen"
        assert w.ctx.store.source_serves_legacy(w.ctx.store.get_source(w.source)) is True

        first = build(w, operation="bootstrap")
        assert (first.generation_id, first.outcome) == (staged.id, "published")
        assert first.resumed_from_batches >= 1
        store = w.ctx.store
        assert store._knowledge_get("Generation", staged.id).created_at == staged.created_at
        assert {m for m in crashed_state["evidence_members"]} <= set(
            durable_state(w, staged.id)["evidence_members"]
        )
        published = durable_state(w, first.generation_id)
        assert published["pointers"]["active_generation_id"] == first.generation_id

        reopen(w)
        assert durable_state(w, first.generation_id) == published, "a published generation survives reopen"
        store = w.ctx.store
        manifest = store.validate_generation_seal(first.generation_id)
        assert store.generation_checksums(first.generation_id) == manifest.checksums
        assert_raw_references_resolve(w, first.generation_id)
        assert_exact_membership(w, first.generation_id)

        before = assert_projection(w, first.generation_id)
        assert_verified_dense_dispatch(w, first.generation_id)

        second, changed = refresh_under_a_live_snapshot(w, first.generation_id, before)
        w.recording = False

        reopen(w)
        assert_retired_generation_reconstructs(w, first.generation_id, published)
        assert_refresh_reuses_immutable_revisions(w, first.generation_id, second.generation_id, changed)
        assert_within_ceilings(w, (first.generation_id, second.generation_id))
        assert_cd1_bound(w)
    finally:
        # `reopen` closed every earlier store; the `store` fixture closes the first one again.
        if w.reopened:
            w.ctx.store.close()
