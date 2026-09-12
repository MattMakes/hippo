"""One repository becomes a managed generation, refreshes, resumes and publishes.

Gate CD8. The coordinator under test is `hippo.ingest.code_generation`; the fixture is a
real git checkout with three commits and files in two walker languages, plus the two
kinds of text file a repository always has -- a `README.md`, which is
`readers.PROSE_EXTENSIONS`, and an extensionless `NOTES`, which is not.

What this suite is for is the part no other slice can prove: that a *composition* of
capture, extraction, history, chunking, binding, staged writing and publication holds
the plan's guarantees end to end. The legacy graph keeps answering every query until the
publication transaction commits; a refresh keeps G1 selected through every batch and
through a fault; a crash resumes the same generation at the same capture instant; a long
build survives an unrelated authorization change and aborts on a real one; and no
destructive operation is ever reached.

Model I/O is a real HTTP transport (`httpx.MockTransport`), as the prose coordinator's
suite does, so "no code text reaches a chat model" is a fact about the wire rather than
about a mock's call list.
"""

from __future__ import annotations

import importlib
import json
import logging
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from threading import local
from types import SimpleNamespace

import httpx
import pytest

from hippo.access import EVERYTHING, Principal
from hippo.ask import search
from hippo.codegraph import syntax_cache
from hippo.ingest import repo_capture
from hippo.knowledge import code_binding, code_history, staged_code
from hippo.knowledge import model as k
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.embedding_profile import EmbeddingSpec
from hippo.knowledge.raw_artifacts import RawArtifactStore
from hippo.ollama import Ollama
from tests.conftest import git_env

CLONE_URL = "https://git.example.com/acme/robots.git"

ORDERS_V1 = '''"""Order handling for the sample service."""

import os


class OrderService:
    """Places orders and keeps a docstring long enough to be worth reading here."""

    def place(self, order):
        total = order.total
        return total

    def save(self, order):
        return os.path.join("orders", order.id)


def helper(value):
    return value + 1
'''

ORDERS_V2 = ORDERS_V1.replace("        total = order.total\n", "        total = order.total * 2\n")

INDEX_TS = """export class OrderClient {
  constructor(readonly base: string) {}

  submit(order: string): string {
    return `${this.base}/${order}`;
  }
}

export function describeOrder(order: string): string {
  return order.toUpperCase();
}
"""

SCHEMA_SQL = "CREATE TABLE orders (\n  id INT\n);\n\nSELECT id FROM orders;\n"
READ_ME = "# Robots\n\nACME builds robots, and this file is plain prose inside a code tree.\n"
NOTES = "Release notes, with no extension at all, so no reader names a grammar for it.\n"
RUBY = "class Unsupported\nend\n"

TREE = {
    "src/orders.py": ORDERS_V1,
    "db/schema.sql": SCHEMA_SQL,
    "README.md": READ_ME,
    "NOTES": NOTES,
    "tools/build.rb": RUBY,
    # One exclusion of each shape the walk can record beside `.git`: a name no reader
    # knows, and a name one does whose bytes are not text.
    "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d",
    "data/blob.json": b"\x00\x01\x02\x00binary\x00",
}


def api():
    try:
        return importlib.import_module("hippo.ingest.code_generation")
    except ModuleNotFoundError:
        pytest.fail("Managed code generation coordinator is missing")


# ------------------------------------------------------------------ the checkout


def _commit(checkout, message, ordinal):
    env = git_env(
        GIT_AUTHOR_NAME="Hippo Fixture", GIT_AUTHOR_EMAIL="fixture@hippo.test",
        GIT_AUTHOR_DATE=f"2026-01-0{ordinal + 1}T09:00:00+00:00",
        GIT_COMMITTER_NAME="Hippo Fixture", GIT_COMMITTER_EMAIL="fixture@hippo.test",
        GIT_COMMITTER_DATE=f"2026-01-0{ordinal + 1}T09:00:00+00:00",
    )  # fmt: skip
    subprocess.run(["git", "-C", str(checkout), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(checkout), "commit", "-q", "-m", message], check=True, env=env)


def make_checkout(tmp_path, files=None, name="checkout"):
    """A real three-commit repository: two walker languages, SQL, prose and an unparsed file."""
    checkout = tmp_path / name
    for path, text in (files if files is not None else TREE).items():
        target = checkout / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode() if isinstance(text, str) else text)
    subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True, env=git_env())
    _commit(checkout, "Add the order service", 0)
    (checkout / "src" / "orders.py").write_text(ORDERS_V2)
    _commit(checkout, "Double the order total", 1)
    (checkout / "web").mkdir(parents=True, exist_ok=True)
    (checkout / "web" / "index.ts").write_text(INDEX_TS)
    _commit(checkout, "Add the order client", 2)
    return checkout


def head_of(checkout):
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=git_env(),
    )
    return result.stdout.strip()


# ------------------------------------------------------------------ the world


class Runtime:
    """A real local-model endpoint. `/api/chat` fails the test if it is ever called."""

    def __init__(self, transaction_state):
        self.calls, self.transaction_state, self.dim, self.digest = [], transaction_state, 2, "a" * 64

    def handle(self, request):
        assert not getattr(self.transaction_state, "depth", 0), "HTTP inside caller transaction"
        path, body = request.url.path, json.loads(request.content or "{}")
        self.calls.append((path, body))
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "embed:latest", "digest": self.digest}]})
        if path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["embedding"]})
        if path == "/api/embed":
            return httpx.Response(
                200,
                json={
                    "model": "embed:latest",
                    "embeddings": [[1.0] + [0.0] * (self.dim - 1) for _ in body["input"]],
                },
            )
        pytest.fail(f"The code lane reached {path}")

    @property
    def embedded(self):
        return [text for path, body in self.calls if path == "/api/embed" for text in body["input"]]


@pytest.fixture
def world(ctx, tmp_path, monkeypatch):
    """An authorized builder, a legacy-indexed repo source and a real checkout."""
    store = ctx.store
    transaction_state = local()
    original_transaction = store.transaction

    @contextmanager
    def transaction():
        with original_transaction():
            transaction_state.depth = getattr(transaction_state, "depth", 0) + 1
            try:
                yield
            finally:
                transaction_state.depth -= 1

    monkeypatch.setattr(store, "transaction", transaction)
    store.ensure_schema()
    store.ensure_roles()
    user = store.create_user("builder", "password", "individual")
    source = store.create_source("repo", "robots", {"url": CLONE_URL}, owner_id=user)
    workspace = store.get_source(source)["workspace_id"]
    store.put_knowledge(
        k.WorkspaceMembership(
            workspace_id=workspace, principal_id=user, mapping_authority="local", enabled=True, policy_epoch=1
        )
    )
    store.set_meta("reviewed_mapping_authorities", ["local"])
    actor = BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual")))
    runtime = Runtime(transaction_state)
    ctx.ollama = Ollama(
        "http://local-model",
        "chat:latest",
        "embed:latest",
        num_ctx=8192,
        client=httpx.Client(base_url="http://local-model", transport=httpx.MockTransport(runtime.handle)),
    )
    raw = RawArtifactStore(tmp_path / "raw", max_object_bytes=2_000_000)
    checkout = make_checkout(tmp_path)
    module = api()
    tree = module.CodeTreeInput(
        root=checkout.resolve(),
        kind="repo",
        repository=repo_capture.repository_descriptor(CLONE_URL),
        head_revision=head_of(checkout),
    )
    return SimpleNamespace(**locals())


def options(w, **kwargs):
    return w.module.CodeBuildOptions(**{"batch_size": 8, "renewal_interval_seconds": 120.0, **kwargs})


def build(w, *, operation="op", **kwargs):
    return w.module.build_code_source(
        w.ctx,
        source_id=w.source,
        actor=kwargs.pop("actor", w.actor),
        tree=kwargs.pop("tree", w.tree),
        options=kwargs.pop("options", options(w)),
        raw_store=w.raw,
        embedding_spec=EmbeddingSpec(dimensions=2),
        operation_id=operation,
        should_stop=kwargs.pop("should_stop", lambda: False),
        **kwargs,
    )


def legacy_row(w, text="The legacy repository passage keeps answering until publication."):
    """One untagged passage: a `managed` source serves the legacy lane only if it has one."""
    w.store.add_passages(
        [
            {
                "id": f"{w.source}:legacy",
                "source_id": w.source,
                "text": text,
                "title": "Legacy",
                "ordinal": 0,
                "embedding": [0.0, 1.0],
            }
        ]
    )
    w.store.update_source(w.source, status="ready")
    return f"{w.source}:legacy"


def served(w):
    """What every query sees, through the lane a verified generation is served by.

    `structural=True` is the managed lane's own loader: it selects each generation's own
    `embedding_profile`, while the dense path compares the model name and therefore only
    ever matches a legacy-tagged generation.
    """
    graph = w.ctx.graph_for(EVERYTHING, structural=True)
    try:
        return {row.id for row in graph.passages}, {node.id for node in graph.code_nodes}
    finally:
        # A structural graph over a published generation holds a snapshot reference with
        # a lease; `context.graph_for` releases it on its own failure path and the caller
        # owns it otherwise. Leaving it open pins the generation and, on LadybugDB, the
        # next build's publication waits on it.
        close = getattr(graph, "close_snapshot", None)
        if close is not None:
            close()


def generation(w, identity):
    return w.store._generation(identity)


def coverage_of(w, identity):
    return json.loads(generation(w, identity).coverage_json)


def spies(w, monkeypatch):
    """Every destructive operation CD8 names, recorded rather than allowed."""
    from hippo.ingest import pipeline

    calls = []

    def record(name, result=None):
        def spy(*args, **kwargs):
            calls.append(name)
            return result

        return spy

    for name in (
        "delete_passages_for_source",
        "delete_code_nodes_for_source",
        "remove_orphans",
        "delete_source",
        "_collect_generation",
    ):
        monkeypatch.setattr(type(w.store), name, record(name), raising=True)
    monkeypatch.setattr(pipeline, "_clear_passages", record("_clear_passages"))
    monkeypatch.setattr(shutil, "rmtree", record("rmtree"))
    return calls


def prepared_files(w, identity):
    return [
        a
        for m in w.store._knowledge_rows("GenerationMember", generation_id=identity)
        if (r := w.store._knowledge_get("ArtifactRevision", m.artifact_revision_id))
        and (a := w.store._knowledge_get("Artifact", r.artifact_id)).kind == "file"
    ]


def raw_objects(w):
    """How many captured raw objects exist. No raw unlink is spied:
    `RawArtifactStore._unlink_owned` is `put_bytes`' own temporary-file cleanup, so
    intercepting it would break capture rather than prove anything. What plan section 10
    actually promises is that no *captured* object is removed, which is a count."""
    return sum(1 for item in (w.tmp_path / "raw").rglob("*") if item.is_file())


# ------------------------------------------------------------------ the public types


def test_the_three_public_types_are_frozen_and_validated(world):
    w = world
    tree, opts = w.tree, options(w)
    assert (tree.kind, tree.paths, tree.is_repository) == ("repo", None, True)
    with pytest.raises(ValueError, match="absolute root"):
        w.module.CodeTreeInput(root="checkout")
    with pytest.raises(ValueError, match="Unknown capture source kind"):
        w.module.CodeTreeInput(root=w.checkout.resolve(), kind="text")
    with pytest.raises(ValueError, match="repository descriptor"):
        w.module.CodeTreeInput(root=w.checkout.resolve(), kind="archive", head_revision="a" * 40)
    with pytest.raises(ValueError, match="normalized, ordered and unique"):
        w.module.CodeTreeInput(root=w.checkout.resolve(), paths=("b.py", "a.py"))
    with pytest.raises(ValueError, match="positive integer"):
        w.module.CodeBuildOptions(batch_size=0)
    with pytest.raises(ValueError, match="payload ceiling"):
        w.module.CodeBuildOptions(max_batch_payload_bytes=staged_code.PAYLOAD_CEILING_BYTES + 1)
    with pytest.raises(ValueError, match="Build renewal must precede lease expiry"):
        w.module.CodeBuildOptions(lease_duration_seconds=10.0, renewal_interval_seconds=9.0)
    assert opts.chunk_settings.effective_overlap <= opts.chunk_settings.effective_size // 3
    # CC4 finding 10: every declined file is a disposition in the canonical manifest, so
    # both manifest rails must be sized for accepted PLUS excluded entries.
    assert opts.capture_limits.max_inputs > opts.max_files


def test_the_grammar_table_fails_closed_on_a_seventh_grammar(world):
    assert set(world.module.CODE_GRAMMARS) == set(syntax_cache._DISTRIBUTIONS)


# ------------------------------------------------------------------ bootstrap


def test_a_bootstrap_publishes_one_code_generation_and_flips_the_lane(world):
    w = world
    legacy = legacy_row(w)
    before = w.store.authorization_epoch()

    result = build(w)

    source = w.store.get_source(w.source)
    assert (result.outcome, result.resumed_from_batches, result.rebaselines) == ("published", 0, 0)
    assert source["active_generation_id"] == result.generation_id
    assert source["managed"] and source["status"] == "ready" and source["stage"] == "ready"
    gen = generation(w, result.generation_id)
    assert gen.status == "active" and w.store.validate_generation_seal(gen.id).ready
    assert json.loads(gen.coverage_json)["embedding_mode"] == "verified_v1"
    assert {a.kind for a in w.store._knowledge_rows("Artifact")} == {
        "repository",
        "manifest",
        "file",
        "history_event",
    }
    # The managed flip is the staging-start one (ruling 9); publication adds none.
    assert w.store.authorization_epoch() > before
    passages, nodes = served(w)
    assert legacy not in passages and nodes
    # The legacy rows are never deleted, only unselected: plan section 10 forbids any
    # cleanup, and the tombstone/restore path depends on them still being there.
    assert any(row["id"] == legacy for row in w.store.load_passages())
    assert raw_objects(w) >= len(prepared_files(w, gen.id))
    assert not w.store._knowledge_rows("ProseExtraction")
    assert [path for path, _ in w.runtime.calls if path == "/api/chat"] == []


def test_the_legacy_graph_answers_every_query_until_the_publication_commits(world):
    w = world
    legacy = legacy_row(w)
    baseline = served(w)
    assert legacy in baseline[0]
    assert search(w.ctx, "legacy repository passage").passages
    seen, batches = [], []

    def watch(progress):
        if progress.phase not in ("write", "seal"):
            return
        batches.append(progress.phase)
        # Loading the whole served graph is the expensive part of this assertion, so it
        # is sampled rather than repeated per batch: the claim is that the legacy lane
        # never changes while staging runs, and the batch counter below proves the
        # staging really did span many transactions.
        if len(seen) < 3:
            seen.append((progress.phase, served(w)))

    result = build(w, on_progress=watch, options=options(w, batch_size=4, checkpoint_interval=1))

    assert batches.count("write") > 2, "a bootstrap stages over many transactions"
    assert all(snapshot == baseline for _, snapshot in seen), "the legacy graph blinked during staging"
    after = served(w)
    assert legacy not in after[0] and after != baseline
    assert w.store.get_source(w.source)["active_generation_id"] == result.generation_id


def test_a_bootstrap_reaches_no_destructive_operation(world, monkeypatch):
    w = world
    legacy_row(w)
    calls = spies(w, monkeypatch)
    assert build(w).outcome == "published"
    assert calls == []


def test_an_archive_without_a_repository_builds_through_the_same_path(world, tmp_path):
    w = world
    archive = tmp_path / "tree.zip"
    shutil.make_archive(str(archive.with_suffix("")), "zip", w.checkout / "src")
    w.store._source_fields(w.source, kind="archive")
    tree = w.module.CodeTreeInput(root=archive.resolve(), kind="archive")

    result = build(w, tree=tree)

    assert result.outcome == "published"
    coverage = coverage_of(w, result.generation_id)
    assert coverage["capture_kind"] == "archive" and coverage["history"] == "disabled"
    assert not [a for a in w.store._knowledge_rows("Artifact") if a.kind == "history_event"]


# ------------------------------------------------------------------ identity


def identity_of(w, **kwargs):
    result = build(w, **kwargs)
    return result.generation_id


def accepted_configuration(w, identity):
    """The configuration `generation_for_inputs` hashed, read back from the manifest."""
    for member in w.store._knowledge_rows("GenerationMember", generation_id=identity):
        revision = w.store._knowledge_get("ArtifactRevision", member.artifact_revision_id)
        artifact = w.store._knowledge_get("Artifact", revision.artifact_id)
        if artifact.kind == "manifest":
            return json.loads(revision.metadata_json)["accepted_manifest_v1"]["configuration"]
    raise AssertionError("the generation has no accepted manifest member")


def test_the_head_sha_the_walker_rules_and_the_grammar_profiles_are_identity(world):
    w = world
    first = identity_of(w)
    configuration = accepted_configuration(w, first)
    code = configuration[w.module.CODE_CONFIGURATION_KEY]

    assert code["walker_rules_version"] == syntax_cache.WALKER_RULES_VERSION
    assert code["syntax_schema_version"] == syntax_cache.SCHEMA_VERSION
    assert code["parser_profiles"]["python"] == [list(item) for item in syntax_cache.parser_profile("python")]
    assert configuration[code_history.HISTORY_CONFIGURATION_KEY] == code_history.CODE_HISTORY_RULE_VERSION
    assert configuration["generation_profile"] == "code"
    assert configuration[code_binding.CODE_BINDING_CONFIGURATION_KEY] == {
        "binding": code_binding.CODE_BINDING_RULE_VERSION,
        "chunker": code_binding.EXPECTED_CODE_CHUNK_RULE_VERSION,
    }
    # CC4's reserved key, which this lane never sets itself.
    assert configuration["capture"]["kind"] == "repo"
    # The head SHA enters identity as the repository revision's provider revision.
    repository = next(
        r
        for a in w.store._knowledge_rows("Artifact")
        if a.kind == "repository"
        for r in w.store._knowledge_rows("ArtifactRevision")
        if r.artifact_id == a.id
    )
    assert repository.provider_revision == w.tree.head_revision


def test_a_changed_derivation_version_is_a_different_generation(world, monkeypatch):
    """Ruling 10: a derivation rule version is hashed, so a bump cannot be resumed into."""
    w = world
    first = identity_of(w)
    monkeypatch.setattr(code_history, "CODE_HISTORY_RULE_VERSION", "code-history-v2")

    second = build(w, operation="second")

    assert second.generation_id != first and second.resumed_from_batches == 0
    assert w.store.get_source(w.source)["active_generation_id"] == second.generation_id
    assert generation(w, first).status == "retired"
    configuration = json.loads(w.store._knowledge_get("Generation", second.generation_id).coverage_json)
    assert configuration["embedding_mode"] == "verified_v1"


def test_the_worker_count_progress_and_capture_instant_stay_out_of_identity(world):
    """The operational group changes nothing a generation *is* (plan section 5).

    Clone depth has no field here at all: cloning is the activation adapter's, and this
    coordinator is handed a checkout. What it does own -- workers, batch size, the
    checkpoint interval, the ceilings, the leases and the progress callback -- is proved
    absent from the hashed configuration and unable to mint a second generation.
    """
    w = world
    first = build(w)
    configuration = accepted_configuration(w, first.generation_id)
    assert not {
        "batch_size",
        "checkpoint_interval",
        "workers",
        "max_chunks",
        "max_files",
        "lease_duration_seconds",
        "renewal_interval_seconds",
        "max_batch_payload_bytes",
    } & set(configuration) | ({"batch_size", "workers"} & set(configuration[w.module.CODE_CONFIGURATION_KEY]))

    again = build(
        w,
        operation="second",
        options=options(w, workers=4, batch_size=3, checkpoint_interval=2, max_chunks=999),
        on_progress=lambda progress: None,
    )
    assert (again.generation_id, again.outcome) == (first.generation_id, "already_current")


def test_a_smaller_history_depth_is_a_different_generation(world):
    w = world
    first = build(w)
    assert build(w, operation="probe", options=options(w, history_depth=1)).generation_id != (
        first.generation_id
    )


# ------------------------------------------------------------------ idempotence


def test_an_operation_id_replay_returns_the_first_receipt_without_inference(world):
    w = world
    first = build(w)
    embedded = len(w.runtime.embedded)
    again = build(w)
    assert (again.generation_id, again.outcome) == (first.generation_id, "already_published")
    assert again.event_id == first.event_id
    # Only the profile probe embedded anything: no passage and no symbol name was
    # inferred again, which is what "without inference or writes" means.
    new = w.runtime.embedded[embedded:]
    assert new and not any("OrderService" in text or text.startswith("# Robots") for text in new)


def test_an_unchanged_tree_under_a_new_operation_is_already_current(world):
    w = world
    first = build(w)
    again = build(w, operation="second")
    assert (again.generation_id, again.outcome) == (first.generation_id, "already_current")
    assert w.store.get_source(w.source)["active_generation_id"] == first.generation_id


# ------------------------------------------------------------------ refresh


def refreshed(w, **kwargs):
    """A published generation, then a changed tree ready for its refresh."""
    first = build(w)
    (w.checkout / "src" / "orders.py").write_text(ORDERS_V1.replace("return value + 1", "return value + 2"))
    _commit(w.checkout, "Adjust the helper", 3)
    tree = replace(w.tree, head_revision=head_of(w.checkout))
    return first, tree


def test_a_refresh_keeps_g1_selected_through_every_batch_and_publishes_atomically(world):
    w = world
    first, tree = refreshed(w)
    served_first = served(w)
    during, sampled = [], []

    def watch(progress):
        if progress.phase != "write":
            return
        # The pointer is read on every batch; the graph it selects is sampled, because
        # loading it is what costs.
        during.append(w.store.get_source(w.source)["active_generation_id"])
        if len(sampled) < 2:
            sampled.append(served(w))

    second = build(w, operation="refresh", tree=tree, on_progress=watch, options=options(w, batch_size=4))

    assert second.generation_id != first.generation_id
    assert len(during) > 2 and all(active == first.generation_id for active in during)
    assert sampled and all(snapshot == served_first for snapshot in sampled)
    assert generation(w, second.generation_id).parent_id == first.generation_id
    assert w.store.get_source(w.source)["active_generation_id"] == second.generation_id
    assert served(w) != served_first


def test_a_refresh_over_an_unchanged_file_reuses_its_immutable_revision(world):
    """An `ArtifactRevision` is written once, and `observed_at` is when its content was
    first observed -- the rule `prose_generation._pair` already keeps.

    Without the reuse a refresh could not write at all: most files of a repository are
    unchanged, `observed_at` is outside `identity_fields`, and both the build guard and
    `put_knowledge` refuse a differing payload under an existing ID.
    """
    w = world
    first, tree = refreshed(w)
    before = {r.id: r for r in w.store._knowledge_rows("ArtifactRevision")}

    second = build(w, operation="refresh", tree=tree)

    after = {r.id: r for r in w.store._knowledge_rows("ArtifactRevision")}
    shared = set(before) & set(after)
    assert shared and all(before[key] == after[key] for key in shared)
    members = [
        {m.artifact_revision_id for m in w.store._knowledge_rows("GenerationMember", generation_id=identity)}
        for identity in (first.generation_id, second.generation_id)
    ]
    # The unchanged files and every commit G1 already held are members of both
    # generations, as one record each rather than two.
    assert members[0] & members[1]
    assert len(after) == len(before) + len(members[1] - members[0])


def test_a_fault_mid_batch_leaves_g1_active_and_the_staged_inventory_retained(world, monkeypatch):
    w = world
    first, tree = refreshed(w)
    calls = spies(w, monkeypatch)
    original = staged_code._write_batch
    state = {"written": 0}

    def fault(store, prepared, batch, **authority):
        if state["written"] == 2:
            raise RuntimeError("injected staging fault")
        state["written"] += 1
        return original(store, prepared, batch, **authority)

    monkeypatch.setattr(staged_code, "_write_batch", fault)
    with pytest.raises(RuntimeError, match="injected staging fault"):
        build(w, operation="refresh", tree=tree, options=options(w, batch_size=1))

    source = w.store.get_source(w.source)
    assert source["active_generation_id"] == first.generation_id and source["status"] == "ready"
    staged = [g for g in w.store._knowledge_rows("Generation") if g.id != first.generation_id]
    assert len(staged) == 1 and staged[0].status == "failed"
    assert w.store._knowledge_rows("GenerationEvidenceMember", generation_id=staged[0].id)
    assert calls == []
    # The presentation of a failed refresh is the activation adapter's, and it is the
    # prose lane's own: the source stays ready because G1 is still serving.
    from hippo.ingest.managed_activation import map_build_failure

    failure = map_build_failure(RuntimeError("x"), has_active_generation=True)
    assert (failure.status, failure.stage) == ("ready", "refresh_failed")


# ------------------------------------------------------------------ resume


def crashed(w, monkeypatch, *, after=2, error=None):
    error = error if error is not None else RuntimeError("injected crash")
    original = staged_code._write_batch
    state = {"written": 0}

    def crash(store, prepared, batch, **authority):
        if state["written"] == after:
            raise error
        state["written"] += 1
        return original(store, prepared, batch, **authority)

    monkeypatch.setattr(staged_code, "_write_batch", crash)
    with pytest.raises(type(error)):
        build(w, options=options(w, batch_size=1))
    monkeypatch.setattr(staged_code, "_write_batch", original)
    return state["written"]


def test_a_crash_mid_batch_resumes_the_same_generation_and_reports_the_skipped_groups(world, monkeypatch):
    w = world
    legacy_row(w)
    written = crashed(w, monkeypatch)
    staged = next(g for g in w.store._knowledge_rows("Generation"))
    assert staged.status == "failed"
    observations = {
        m.record_id
        for m in w.store._knowledge_rows("GenerationEvidenceMember", generation_id=staged.id)
        if m.record_kind == "ObjectObservation"
    }

    result = build(w, options=options(w, batch_size=1))

    assert result.generation_id == staged.id and result.outcome == "published"
    # The first batch is the accepted preflight, which is a read and writes no row, so
    # the resumed count is one less than the batches the crashed attempt completed.
    assert result.resumed_from_batches == written - 1 >= 1
    assert generation(w, staged.id).created_at == staged.created_at
    # Design review B4: the adopted instant reproduces every observation ID, so the
    # resumed attempt writes no second set beside the first.
    after = {
        m.record_id
        for m in w.store._knowledge_rows("GenerationEvidenceMember", generation_id=staged.id)
        if m.record_kind == "ObjectObservation"
    }
    assert observations <= after


def test_a_resumed_build_adopts_the_persisted_capture_instant_even_at_a_new_clock(world, monkeypatch):
    w = world
    crashed(w, monkeypatch)
    staged = next(g for g in w.store._knowledge_rows("Generation"))
    later = staged.created_at + timedelta(hours=3)
    monkeypatch.setattr(type(w.store), "_now", lambda self: later)

    result = build(w, options=options(w, batch_size=1))

    assert result.generation_id == staged.id
    assert generation(w, staged.id).created_at == staged.created_at


def test_a_fresh_bootstrap_reports_no_resumed_batches_although_its_members_are_installed(world):
    """The probe recognises the revision members the install itself writes every time."""
    w = world
    assert build(w).resumed_from_batches == 0


def test_cancellation_between_batches_leaves_a_resumable_generation(world):
    w = world
    legacy_row(w)
    flag = {"stop": False}
    seen = []

    def watch(progress):
        if progress.phase == "write" and progress.completed >= 2:
            flag["stop"] = True
            seen.append(progress.completed)

    with pytest.raises(Exception) as failure:
        build(
            w,
            on_progress=watch,
            should_stop=lambda: flag["stop"],
            options=options(w, batch_size=1),
        )
    assert type(failure.value).__name__ == "BuildCancelled"
    assert str(failure.value) == w.module.CANCELLED_MESSAGE
    staged = next(g for g in w.store._knowledge_rows("Generation"))
    assert staged.status == "failed" and staged.published_at is None
    assert w.store.get_source(w.source)["active_generation_id"] is None
    assert legacy_served(w)

    result = build(w, options=options(w, batch_size=1))
    assert result.generation_id == staged.id and result.resumed_from_batches >= 1


def legacy_served(w):
    return any(row["id"] == f"{w.source}:legacy" for row in w.store.load_passages())


def test_a_resume_after_a_changed_tree_supersedes_rather_than_resuming(world, monkeypatch):
    w = world
    crashed(w, monkeypatch)
    staged = next(g for g in w.store._knowledge_rows("Generation"))
    (w.checkout / "src" / "orders.py").write_text(ORDERS_V1.replace("return value + 1", "return value + 3"))
    tree = replace(w.tree, head_revision=head_of(w.checkout))

    result = build(w, operation="second", tree=tree, options=options(w, batch_size=1))

    assert result.generation_id != staged.id and result.resumed_from_batches == 0
    assert generation(w, staged.id).status == "failed"


# ------------------------------------------------------------------ long-build authority


def test_a_long_build_rebaselines_across_an_unrelated_authorization_change(world, monkeypatch):
    w = world
    from hippo.store.authorization import bump_epoch

    original = staged_code._write_batch
    state = {"written": 0}

    def bump_after_the_first_batch(store, prepared, batch, **authority):
        result = original(store, prepared, batch, **authority)
        state["written"] += 1
        if state["written"] == 1:
            with store.transaction():
                bump_epoch(store, "authorization_epoch")
        return result

    monkeypatch.setattr(staged_code, "_write_batch", bump_after_the_first_batch)
    result = build(w, options=options(w, batch_size=1))

    assert result.outcome == "published" and result.rebaselines == 1
    assert w.store.get_source(w.source)["active_generation_id"] == result.generation_id


def test_a_capability_loss_mid_build_aborts_and_never_rebaselines(world, monkeypatch):
    w = world
    legacy_row(w)
    calls = spies(w, monkeypatch)
    original = staged_code._write_batch
    state = {"written": 0}

    def revoke_after_the_first_batch(store, prepared, batch, **authority):
        result = original(store, prepared, batch, **authority)
        state["written"] += 1
        if state["written"] == 1:
            # The same two mutations `test_build_authority` uses for a capability loss,
            # plus the epoch change that takes the coordinator into `rebaseline()` at
            # all. `check_local()` must refuse there rather than adopt.
            store.update_role("individual", capabilities=[])
            store._source_fields(w.source, owner_id=None)
        return result

    monkeypatch.setattr(staged_code, "_write_batch", revoke_after_the_first_batch)
    with pytest.raises(AuthorizationChanged):
        build(w, options=options(w, batch_size=1))

    staged = next(g for g in w.store._knowledge_rows("Generation"))
    assert staged.status == "failed" and w.store.get_source(w.source)["active_generation_id"] is None
    assert calls == []


def test_a_suppression_change_mid_build_aborts_rather_than_rebaselining(world, monkeypatch):
    w = world
    from hippo.store.authorization import bump_epoch

    original = staged_code._write_batch
    state = {"written": 0}

    def suppress_after_the_first_batch(store, prepared, batch, **authority):
        result = original(store, prepared, batch, **authority)
        state["written"] += 1
        if state["written"] == 1:
            with store.transaction():
                bump_epoch(store, "suppression_epoch")
        return result

    monkeypatch.setattr(staged_code, "_write_batch", suppress_after_the_first_batch)
    with pytest.raises(AuthorizationChanged):
        build(w, options=options(w, batch_size=1))
    assert w.store.get_source(w.source)["active_generation_id"] is None


def test_a_live_holder_refuses_the_build_as_busy(world, monkeypatch):
    w = world
    original = staged_code._write_batch

    def stop(store, prepared, batch, **authority):
        raise RuntimeError("injected crash")

    monkeypatch.setattr(staged_code, "_write_batch", stop)
    with pytest.raises(RuntimeError):
        build(w)
    monkeypatch.setattr(staged_code, "_write_batch", original)
    staged = next(g for g in w.store._knowledge_rows("Generation"))
    job = next(iter(w.store._knowledge_rows("MaintenanceJob")))
    w.store._write_knowledge(
        job.replace(status="running", lease_expires_at=w.store._now() + timedelta(hours=1))
    )
    w.store._source_fields(w.source, active_build_id=job.id)
    with pytest.raises(Exception) as failure:
        build(w, operation="other")
    assert type(failure.value).__name__ == "BuildBusy"
    assert generation(w, staged.id).status in ("staging", "failed")


# ------------------------------------------------------------------ ceilings and refusals


def test_every_ceiling_refuses_before_it_installs_anything(world):
    w = world
    for kwargs, match in (
        ({"max_files": 2}, "too_many_files"),
        ({"max_symbols": 1}, "more symbols than"),
        ({"max_chunks": 1}, None),
        ({"max_batch_payload_bytes": 1}, "payload ceiling"),
    ):
        with pytest.raises(Exception) as failure:
            build(w, operation=f"ceiling-{next(iter(kwargs))}", options=options(w, **kwargs))
        if match is not None:
            assert match in str(failure.value) or getattr(failure.value, "reason", "") == match
    assert w.store.get_source(w.source)["active_generation_id"] is None
    assert all(g.status != "active" for g in w.store._knowledge_rows("Generation"))


def test_a_requested_path_outside_the_walk_refuses_before_capture(world):
    w = world
    tree = replace(w.tree, paths=("src/missing.py", "src/orders.py"))
    with pytest.raises(w.module.CodeBuildRefused):
        build(w, tree=tree)
    assert not w.store._knowledge_rows("Generation")


def test_explicit_paths_capture_only_those_files_and_enter_identity(world):
    w = world
    whole = build(w)
    w.store._source_fields(w.source, active_generation_id=None)
    narrow = build(w, operation="narrow", tree=replace(w.tree, paths=("db/schema.sql", "src/orders.py")))
    assert narrow.generation_id != whole.generation_id
    paths = {
        a.external_id
        for a in w.store._knowledge_rows("Artifact")
        if a.kind == "file" and a.external_id in TREE
    }
    assert "README.md" in paths, "the wide build captured it"
    coverage = coverage_of(w, narrow.generation_id)
    assert coverage["files_accepted"] == 2


# ------------------------------------------------------------------ coverage and privacy


def test_coverage_records_what_this_generation_does_not_contain(world):
    w = world
    result = build(w)
    coverage = coverage_of(w, result.generation_id)

    assert coverage["openie"] == "skipped"
    assert coverage["openie_reasons"]["src/orders.py"] == w.module.OPENIE_CODE
    assert coverage["openie_reasons"]["NOTES"] == w.module.OPENIE_UNPARSED
    # Ruling 5's OpenIE half is a named deferral, recorded per file rather than implied.
    assert coverage["openie_reasons"]["README.md"] == w.module.OPENIE_PROSE_DEFERRED
    assert coverage["files_excluded"]["unsupported_language"] >= 1  # assets/logo.png
    assert coverage["files_excluded"]["binary"] >= 1  # data/blob.json
    assert coverage["files_excluded"]["ignored_path"] >= 1  # .git
    assert coverage["history"] == "read" and coverage["history_walk"] == "first_parent"
    assert coverage["history_commits"] == 3 and coverage["history_shallow_boundary"] == []
    assert coverage["history_renames"] == "not_reported"
    assert coverage["capture_kind"] == "repo"
    assert coverage["symbols"] and coverage["passages"]["prose"] >= 1
    assert coverage["code_truncated"] is False


def test_a_readme_inside_the_tree_is_evidence_but_never_reaches_a_chat_model(world):
    w = world
    result = build(w)
    revision = next(
        r
        for a in w.store._knowledge_rows("Artifact")
        if a.kind == "file" and a.external_id == "README.md"
        for r in w.store._knowledge_rows("ArtifactRevision")
        if r.artifact_id == a.id
    )
    spans = [s for s in w.store._knowledge_rows("EvidenceSpan") if s.revision_id == revision.id]
    assert spans and any("ACME builds robots" in s.text for s in spans)
    assert not w.store._knowledge_rows("ProseExtraction")
    assert [path for path, _ in w.runtime.calls if path == "/api/chat"] == []
    assert coverage_of(w, result.generation_id)["openie_reasons"]["README.md"] == (
        w.module.OPENIE_PROSE_DEFERRED
    )


def test_no_log_record_source_row_or_receipt_carries_a_path_url_or_source_text(world, caplog):
    w = world
    secret = "OrderService"
    w.before_row = w.store.get_source(w.source)
    with caplog.at_level(logging.DEBUG):
        result = build(w)
    forbidden = (str(w.checkout), CLONE_URL, "git.example.com", secret, "ACME builds robots")
    for record in caplog.records:
        message = record.getMessage()
        assert not any(item in message for item in forbidden), message
    # The Source row carried its own clone URL before this build started -- that is the
    # user's configuration, not something a build may add to. What the build must never
    # add is a checkout path or any source text.
    row = json.dumps(w.store.get_source(w.source), default=str)
    assert str(w.checkout) not in row
    assert row.count(CLONE_URL) == json.dumps(w.before_row, default=str).count(CLONE_URL)
    assert not any(item in json.dumps(vars(result)) for item in forbidden)


def test_a_refused_capture_never_names_the_path_it_refused(world):
    w = world
    with pytest.raises(Exception) as failure:
        build(w, options=options(w, max_files=2))
    assert str(w.checkout) not in str(failure.value)
    assert CLONE_URL not in str(failure.value)


# ------------------------------------------------------------------ the seam itself


def test_the_coordinator_refuses_an_ambient_transaction_and_a_wrong_options_type(world):
    w = world
    with pytest.raises(ValueError, match="no ambient transaction"):
        with w.store.transaction():
            build(w)
    with pytest.raises(ValueError, match="Explicit immutable code build"):
        build(w, options=object())
    with pytest.raises(ValueError, match="Stable operation identity"):
        build(w, operation="")


def test_the_source_kind_must_match_the_captured_tree(world):
    w = world
    w.store._source_fields(w.source, kind="archive")
    with pytest.raises(w.module.CodeBuildRefused, match="not this source's kind"):
        build(w)
