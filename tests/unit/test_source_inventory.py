"""The Library inventory: origin, domain, last sync and last error on every source row.

Plan `ai_docs/plans/2026-09-18-knowledge-inventory-domain-plan.md` task T2, table 3.4, acceptance
A1, A2, A9, A10 and A13; design D1, D6 and D10. `status.source_view` adds the fields in one pass
over records it reads once per kind, so the Library's 3 s poll costs the same for one source as for
twenty (invariant I1). An unproven managed row reveals none of them (P1).

The connector source is a real fixture-connector sync (`test_connector_sync.World`), so its
`Connector`, `SyncState` and published `Generation` are the rows production writes. Every test that
needs a test client imports it inside the function and carries the per-test marker of rulebook form
(a), so this module imports no test client at collection time.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from markupsafe import escape

from hippo.knowledge import model as k
from hippo.knowledge.lifecycle import generation_passage_id
from hippo.knowledge.query_access import query_session
from hippo.status import source_view
from tests.fakes.fixture_connector import FixtureConnector
from tests.unit.test_connector_sync import World, ctx, registry  # noqa: F401

ANYIO = "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"

# Table 3.4, in its order; `kind` is the one existing key whose meaning changes.
INVENTORY_KEYS = (
    "origin",
    "origin_detail",
    "lane",
    "domain",
    "domain_origin",
    "domain_state",
    "domain_allowed",
    "domain_fixed_reason",
    "domain_confirmed_at",
    "domain_confirmed_by",
    "last_sync_at",
    "last_sync_label",
    "last_error",
    "resync_command",
)
UNKNOWN_FAMILIES = "This process does not know the connector's declared domains."
UNKNOWN_FAMILIES_HTML = str(escape(UNKNOWN_FAMILIES))  # the page escapes the apostrophe


# ------------------------------------------------------------------ harness


def _publish(store, source_id, key, *, parser_version):
    """Publish one managed generation for an existing Source; `test_structural_loading.published`
    builds the same records, but always for a new `text` source."""
    now = datetime.now(UTC)
    workspace = store.get_source(source_id)["workspace_id"]
    policy = k.AccessPolicy(
        workspace_id=workspace, origin="local_curated", scope_key=key, mode="workspace", verified_at=now
    )
    artifact = k.Artifact(
        workspace_id=workspace,
        source_id=source_id,
        kind="file",
        external_id=key,
        canonical_uri=key,
        policy_id=policy.id,
    )
    revision = k.ArtifactRevision(
        artifact_id=artifact.id, content_hash=key, raw_uri="blob:" + key, observed_at=now, lifecycle="active"
    )
    span = k.EvidenceSpan(
        revision_id=revision.id,
        locator_kind="file_lines",
        locator_json='{"kind":"file_lines","path":"a.txt","start":1,"end":1}',
        text=key,
        policy_id=policy.id,
    )
    gen = k.Generation(
        source_id=source_id,
        status="staging",
        parser_version=parser_version,
        linker_version="l",
        embedding_profile="p",
        created_at=now,
        manifest_hash=key,
    )
    for row in (policy, artifact, gen):
        store.put_knowledge(row)
    job = store.claim_generation_build(
        gen.id, job_key=key, lease_owner="inventory", lease_expires_at=now + timedelta(minutes=5)
    )
    authority = dict(job_id=job.id, lease_owner=job.lease_owner, fencing_token=job.fencing_token)
    with store.generation_write(gen.id, **authority):
        for row in (
            revision,
            span,
            k.GenerationMember(generation_id=gen.id, artifact_revision_id=revision.id),
            k.GenerationEvidenceMember(generation_id=gen.id, record_kind="EvidenceSpan", record_id=span.id),
        ):
            store.put_knowledge(row)
        store.add_passages(
            [
                dict(
                    id=generation_passage_id(gen.id, revision.id, span.id, 0),
                    source_id=source_id,
                    generation_id=gen.id,
                    artifact_revision_id=revision.id,
                    span_id=span.id,
                    embedding_profile="p",
                    text=key,
                    title=key,
                    ordinal=0,
                    embedding=[1.0, 0.0],
                )
            ]
        )
    manifest = k.IndexManifest(
        generation_id=gen.id,
        profile_fingerprint="p",
        config_fingerprint="c",
        required_representations=("evidence", "dense", "native"),
        checksums=store.generation_checksums(gen.id),
        ready=True,
    )
    store.seal_generation(gen.id, manifest, **authority)
    store.publish_staged_generation(
        gen.id,
        expected_parent_id=None,
        expected_suppression_epoch=store.suppression_epoch(),
        published_at=now,
        **authority,
    )
    return gen.id


@pytest.fixture
def inventory(ctx, tmp_path, registry):  # noqa: F811
    """One source per lane, all visible to the World's signed-in operator.

    - `text`: pasted text in the legacy lane, never indexed.
    - `file`: a plain-prose upload with a published managed generation.
    - `repo`: a repository with a published managed code generation.
    - `connector`: the fixture connector's partition Source after one real sync.
    """
    world = World(ctx, tmp_path, registry)
    try:
        receipt = world.sync()
        assert receipt.outcome == "published"
        store = world.store
        text = store.create_source("text", "Pasted notes", {}, owner_id=world.user)
        upload = store.create_source("file", "notes.md", {"file": "notes.md"}, owner_id=world.user)
        repo = store.create_source("repo", "billing repo", {}, owner_id=world.user)
        upload_generation = _publish(store, upload, "notes-md", parser_version="mapped-prose-v1")
        repo_generation = _publish(store, repo, "billing-repo", parser_version="managed-code-v1")
        yield NS(
            world=world,
            ctx=ctx,
            store=store,
            user=world.user,
            text=text,
            upload=upload,
            upload_generation=upload_generation,
            repo=repo,
            repo_generation=repo_generation,
            connector=world.source,
            connector_generation=receipt.generation_id,
        )
    finally:
        world.close_sessions()


def _principal(inv):
    return inv.world.reader()


def _rows(inv, **keys):
    access = _principal(inv).access
    with query_session(inv.ctx, access) as session:
        view = source_view(inv.ctx, access, session=session, **keys)
        rows = {row["id"]: row for row in view.sources}
        view.validate()
    return rows


def _client(inv, *, connector_load=None):
    """A client without the lifespan, so `app.state.connector_load` is exactly what a test sets."""
    from fastapi.testclient import TestClient

    from hippo.web.app import create_app

    app = create_app(inv.ctx)
    if connector_load is not None:
        app.state.connector_load = connector_load
    client = TestClient(app, base_url="http://localhost")
    client.headers["Authorization"] = "Bearer " + inv.store.get_user(inv.user)["token"]
    return client


def _row_html(html: str, source_id: str) -> str:
    """The one Library table row that links to `source_id`."""
    rows = [
        chunk.split("</tr>")[0] for chunk in html.split("<tr>") if f'href="/sources/{source_id}"' in chunk
    ]
    assert len(rows) == 1, f"{source_id} is not exactly one Library row"
    return rows[0]


def _shown(instant: str) -> str:
    return instant[:16].replace("T", " ")


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _load(connector_class):
    from hippo.connectors import loader
    from hippo.knowledge.registry import Registry

    entry = loader.ConnectorEntry(
        name="fixture",
        origin="in-repo",
        target=None,
        trusted=True,
        enabled=True,
        registered=connector_class is not None,
        connector_class=connector_class,
        error=None if connector_class is not None else "not allowlisted",
    )
    return loader.LoadResult(registry=Registry(), entries=(entry,))


class _TwoFamilyConnector(FixtureConnector):
    descriptor = FixtureConnector.descriptor.model_copy(update={"families": ("service", "custom")})


# ------------------------------------------------------------------ A1: the Library shows each value


@pytest.mark.filterwarnings(ANYIO)
@pytest.mark.parametrize("path", ["/", "/partials/sources"])
def test_library_and_partial_show_inventory_columns(inventory, path):
    inv = inventory
    rows = _rows(inv)
    response = _client(inv).get(path)
    assert response.status_code in (200, 286)
    html = response.text
    assert "<th>Domain</th>" in html and "<th>Last sync</th>" in html

    text = _row_html(html, inv.text)
    assert '<span class="badge">text</span>' in text
    assert ">prose<" in text and "auto" in text
    assert "last activity" in text and _shown(rows[inv.text]["last_sync_at"]) in text

    upload = _row_html(html, inv.upload)
    assert '<span class="badge">file</span>' in upload
    assert 'class="pill small">managed</span>' in upload
    assert ">prose<" in upload and "auto" in upload
    assert "published" in upload and _shown(rows[inv.upload]["last_sync_at"]) in upload
    assert "Plain-text files are always built as prose." in upload

    connector = _row_html(html, inv.connector)
    assert '<span class="badge">connector</span>' in connector
    assert f"fixture · {inv.world.row.id} · {inv.world.partition}" in connector
    assert ">custom<" in connector and "auto" in connector
    assert "synced" in connector and _shown(rows[inv.connector]["last_sync_at"]) in connector
    # The Library passes no descriptor families, so the connector's domain reads as fixed (plan 2.5).
    assert UNKNOWN_FAMILIES_HTML in connector


# ------------------------------------------------------------------ A2: true kind, lane marker


def test_managed_rows_show_true_kind_and_a_lane_marker(inventory):
    inv = inventory
    rows = _rows(inv)
    for key in (inv.text, inv.upload, inv.repo, inv.connector):
        assert set(INVENTORY_KEYS) <= set(rows[key]), key
    assert (rows[inv.text]["kind"], rows[inv.text]["origin"], rows[inv.text]["lane"]) == (
        "text",
        "text",
        "legacy",
    )
    assert (rows[inv.upload]["kind"], rows[inv.upload]["origin"], rows[inv.upload]["lane"]) == (
        "file",
        "file",
        "managed",
    )
    assert (rows[inv.repo]["kind"], rows[inv.repo]["origin"], rows[inv.repo]["lane"]) == (
        "repo",
        "repo",
        "managed",
    )
    assert (rows[inv.connector]["kind"], rows[inv.connector]["origin"], rows[inv.connector]["lane"]) == (
        "connector",
        "connector",
        "connector",
    )
    # `managed` is a control flag, never a kind: it stays on every managed-lane row.
    assert all(rows[key]["managed"] is True for key in (inv.upload, inv.repo, inv.connector))
    assert all(row["kind"] != "managed" for row in rows.values())

    repo = rows[inv.repo]
    assert (repo["domain"], repo["domain_origin"], repo["domain_state"]) == ("code", "lane", "auto")
    assert repo["domain_allowed"] == ["code"]
    assert repo["domain_fixed_reason"] == "Repositories are always built as code."
    assert repo["domain_confirmed_at"] is None and repo["domain_confirmed_by"] is None

    connector = rows[inv.connector]
    assert connector["origin_detail"] == f"fixture · {inv.world.row.id} · {inv.world.partition}"
    # The fixture probe declares its family, so the origin is `declared` (plan 3.2).
    assert (connector["domain"], connector["domain_origin"], connector["domain_state"]) == (
        "custom",
        "declared",
        "auto",
    )
    assert connector["domain_allowed"] == ["custom"]
    assert connector["domain_fixed_reason"] == UNKNOWN_FAMILIES
    assert all(rows[key]["origin_detail"] is None for key in (inv.text, inv.upload, inv.repo))


def test_an_unproven_managed_row_reveals_no_inventory_field(ctx, monkeypatch):  # noqa: F811
    """P1: without a proven pair, the row exists only because some evidence is visible."""
    from hippo.access import EVERYTHING
    from hippo.hipporag.graph_index import Passage
    from tests.unit.test_evidence_projection import graph

    ctx.store.ping()
    sid = ctx.store.create_source("repo", "SECRET repo", {"file": "SECRET.py"})
    projected = graph([], [Passage("allowed-span", "Allowed title", "Allowed body", sid, "", 0)])
    monkeypatch.setattr(ctx, "graph_for", lambda access, **kwargs: projected)
    original = ctx.store._knowledge_rows
    monkeypatch.setattr(
        ctx.store,
        "_knowledge_rows",
        lambda kind, **keys: [NS(source_id=sid)] if kind == "Artifact" else original(kind, **keys),
    )
    row = next(row for row in source_view(ctx, EVERYTHING).sources if row["id"] == sid)
    assert row["kind"] == "managed" and row["managed"] is True
    assert row["domain_allowed"] == []
    assert all(row[key] is None for key in INVENTORY_KEYS if key != "domain_allowed")
    assert "SECRET" not in repr(row)


# ------------------------------------------------------------------ A9: last sync per lane


def test_last_sync_per_lane(inventory):
    inv = inventory
    rows = _rows(inv)
    state = inv.world.sync_state()
    assert rows[inv.connector]["last_sync_at"] == _iso(state.last_success_at)
    assert rows[inv.connector]["last_sync_label"] == "synced"
    for source, generation in ((inv.upload, inv.upload_generation), (inv.repo, inv.repo_generation)):
        published = inv.store._knowledge_get("Generation", generation).published_at
        assert rows[source]["last_sync_at"] == _iso(published)
        assert rows[source]["last_sync_label"] == "published"
    assert rows[inv.text]["last_sync_at"] == inv.store.get_source(inv.text)["updated_at"]
    assert rows[inv.text]["last_sync_label"] == "last activity"

    assert rows[inv.connector]["resync_command"] == (
        f"hippo connector sync {inv.world.row.id} --partition {inv.world.partition}"
    )
    assert all(rows[key]["resync_command"] is None for key in (inv.text, inv.upload, inv.repo))
    assert all(rows[key]["last_error"] is None for key in (inv.text, inv.upload, inv.repo, inv.connector))


def test_a_connector_sync_error_code_is_the_rows_last_error(inventory):
    inv = inventory
    state = inv.world.sync_state()
    inv.store.update_knowledge(state.replace(error_code="provider_unavailable"))
    row = _rows(inv)[inv.connector]
    assert row["last_error"] == "provider_unavailable"
    assert row["last_sync_at"] == _iso(state.last_success_at)


def test_a_generation_id_with_no_record_gives_no_last_sync(inventory, monkeypatch):
    inv = inventory
    access = _principal(inv).access
    original = inv.store._knowledge_rows
    with query_session(inv.ctx, access) as session:
        monkeypatch.setattr(
            inv.store,
            "_knowledge_rows",
            lambda kind, **keys: [
                row
                for row in original(kind, **keys)
                if kind != "Generation" or row.id != inv.upload_generation
            ],
        )
        view = source_view(inv.ctx, access, session=session)
        row = next(row for row in view.sources if row["id"] == inv.upload)
    assert row["kind"] == "file" and row["lane"] == "managed"
    assert row["last_sync_at"] is None and row["last_sync_label"] is None


def test_a_connector_row_whose_connector_record_is_gone_does_not_raise(ctx):  # noqa: F811
    from hippo.access import EVERYTHING

    ctx.store.ping()
    orphan = ctx.store.create_source(
        "connector", "orphan", {"connector_id": "connector-gone", "partition": "p"}
    )
    row = next(row for row in source_view(ctx, EVERYTHING).sources if row["id"] == orphan)
    assert (row["kind"], row["origin"], row["lane"]) == ("connector", "connector", "connector")
    assert row["origin_detail"] is None
    assert (row["domain"], row["domain_origin"], row["domain_state"]) == ("custom", "fallback", "auto")
    assert row["last_sync_at"] is None and row["last_sync_label"] is None
    # There is no instance to sync, so there is no command to print.
    assert row["resync_command"] is None


@pytest.mark.filterwarnings(ANYIO)
def test_an_empty_store_renders(ctx):  # noqa: F811
    from fastapi.testclient import TestClient

    from hippo.access import EVERYTHING
    from hippo.web.app import create_app

    ctx.store.ping()
    assert source_view(ctx, EVERYTHING).sources == []
    client = TestClient(create_app(ctx), base_url="http://localhost")
    for path in ("/", "/partials/sources"):
        response = client.get(path)
        assert response.status_code in (200, 286), path
        assert "Nothing here yet" in response.text, path


# ------------------------------------------------------------------ A10: batched reads


def test_inventory_reads_are_batched(ctx, monkeypatch):  # noqa: F811
    """The same `_knowledge_rows` calls for 1 and for 20 connector sources, each new one by `ids=`."""
    from hippo.access import EVERYTHING

    ctx.store.ping()
    calls = []
    recording = NS(on=False)
    original = ctx.store._knowledge_rows

    # One patch for the whole test: the Fake store's transaction deep-copies its instance
    # attributes, and a function copies as itself where a restored bound method does not.
    def counted(kind, **keys):
        if recording.on:
            calls.append((kind, len(keys.get("ids") or ())))
        return original(kind, **keys)

    monkeypatch.setattr(ctx.store, "_knowledge_rows", counted)

    def reads(count):
        existing = sum(1 for row in ctx.store.list_sources() if row["kind"] == "connector")
        for index in range(existing, count):
            ctx.store.create_source(
                "connector",
                f"partition {index}",
                {"connector_id": f"connector-{index}", "partition": f"p{index}"},
            )
        with query_session(ctx, EVERYTHING) as session:
            calls.clear()
            recording.on = True
            try:
                view = source_view(ctx, EVERYTHING, session=session)
            finally:
                recording.on = False
        assert len(view.sources) == count
        return list(calls)

    one, twenty = reads(1), reads(20)
    assert len(one) == len(twenty)
    assert [kind for kind, _ in one] == [kind for kind, _ in twenty]
    assert ("Connector", 1) in one and ("SyncState", 1) in one
    assert ("Connector", 20) in twenty and ("SyncState", 20) in twenty
    assert sum(kind in ("Connector", "SyncState") for kind, _ in twenty) == 2


def test_the_new_reads_are_skipped_without_connector_sources(ctx, monkeypatch):  # noqa: F811
    from hippo.access import EVERYTHING

    ctx.store.ping()
    ctx.store.create_source("text", "notes")
    kinds = []
    original = ctx.store._knowledge_rows
    with query_session(ctx, EVERYTHING) as session:
        monkeypatch.setattr(
            ctx.store, "_knowledge_rows", lambda kind, **keys: kinds.append(kind) or original(kind, **keys)
        )
        source_view(ctx, EVERYTHING, session=session)
    assert "Connector" not in kinds and "SyncState" not in kinds


# ------------------------------------------------------------------ the source page cards


@pytest.mark.filterwarnings(ANYIO)
def test_the_source_page_shows_a_domain_card_and_a_sync_card(inventory):
    inv = inventory
    row = _rows(inv)[inv.connector]
    page = _client(inv).get(f"/sources/{inv.connector}")
    assert page.status_code == 200
    html = page.text
    domain = html.split("<h3>Domain</h3>", 1)[1].split("</section>", 1)[0]
    assert "custom" in domain and row["domain_origin"] in domain and "auto" in domain
    assert UNKNOWN_FAMILIES_HTML in domain
    coverage = json.loads(inv.store._knowledge_get("Generation", inv.connector_generation).coverage_json)
    for family, count in coverage["emission"]["nodes_by_family"].items():
        assert f"{family} {count}" in domain
    sync_card = html.split("<h3>Sync</h3>", 1)[1].split("</section>", 1)[0]
    assert "synced" in sync_card and _shown(row["last_sync_at"]) in sync_card
    assert f"<code>{row['resync_command']}</code>" in sync_card
    generation = inv.store._knowledge_get("Generation", inv.connector_generation)
    assert generation.parser_version in sync_card and "active" in sync_card


@pytest.mark.filterwarnings(ANYIO)
def test_the_source_page_names_the_connector_families_it_knows(inventory):
    inv = inventory
    one = _client(inv, connector_load=_load(FixtureConnector)).get(f"/sources/{inv.connector}").text
    assert "The fixture connector declares only the custom domain." in one
    assert UNKNOWN_FAMILIES_HTML not in one
    two = _client(inv, connector_load=_load(_TwoFamilyConnector)).get(f"/sources/{inv.connector}").text
    assert "declares only" not in two and UNKNOWN_FAMILIES_HTML not in two
    # An entry that is not loaded is a `ConnectorLoadError`, which reads as "families unknown".
    missing = _client(inv, connector_load=_load(None)).get(f"/sources/{inv.connector}").text
    assert UNKNOWN_FAMILIES_HTML in missing


def test_descriptor_families_widen_the_allowed_domains(inventory):
    inv = inventory
    rows = _rows(inv, descriptor_families={"fixture": ("service", "custom")})
    assert rows[inv.connector]["domain_allowed"] == ["service", "custom"]
    assert rows[inv.connector]["domain_fixed_reason"] is None
    # Coordinator rows ignore connector families.
    assert rows[inv.upload]["domain_allowed"] == ["prose"]


@pytest.mark.filterwarnings(ANYIO)
def test_a_legacy_source_page_renders_without_a_generation(inventory):
    inv = inventory
    html = _client(inv).get(f"/sources/{inv.text}").text
    domain = html.split("<h3>Domain</h3>", 1)[1].split("</section>", 1)[0]
    assert "prose" in domain and "Pasted text is always built as prose." in domain
    sync_card = html.split("<h3>Sync</h3>", 1)[1].split("</section>", 1)[0]
    assert "last activity" in sync_card and "<code>" not in sync_card


# ------------------------------------------------------------------ A13: CLI and MCP parity


def test_cli_and_mcp_rows_carry_the_inventory_fields(inventory, monkeypatch, capsys):
    from hippo import cli, mcp_server
    from hippo.context import AppContext

    inv = inventory
    rows = _rows(inv)
    monkeypatch.setattr(AppContext, "from_env", classmethod(lambda cls, ollama=None: inv.ctx))
    monkeypatch.setenv(mcp_server.TOKEN_ENV, inv.store.get_user(inv.user)["token"])
    assert cli.main(["sources"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == [
        "id",
        "name",
        "kind",
        "status",
        "stage",
        "passages",
        "facts",
        "domain",
        "last",
        "sync",
        "created",
    ]
    connector = next(line for line in lines if line.startswith(inv.connector))
    assert "custom (auto)" in connector
    assert f"{rows[inv.connector]['last_sync_at'][:19]} (synced)" in connector
    upload = next(line for line in lines if line.startswith(inv.upload))
    assert " file " in upload and "prose (auto)" in upload and "(published)" in upload

    listed = {row["id"]: row for row in mcp_server.sources_tool(inv.ctx, _principal(inv))}
    keys = ("origin", "domain", "domain_origin", "domain_state", "last_sync_at", "last_sync_label")
    for source in (inv.text, inv.upload, inv.repo, inv.connector):
        assert {key: listed[source][key] for key in keys} == {key: rows[source][key] for key in keys}
    assert listed[inv.connector]["kind"] == "connector"
    assert listed[inv.connector]["last_sync_label"] == "synced"
