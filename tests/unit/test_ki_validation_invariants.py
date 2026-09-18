"""T5 invariant checks for the knowledge inventory and domain confirmation feature.

Plan `ai_docs/plans/2026-09-18-knowledge-inventory-domain-plan.md` sections 4 and 6 (T5).

- I1: reading the Library makes no model call, starts no job, loads no connector package and writes
  nothing.
- I5: a v8 LadybugDB store with existing sources reopens at v9, and the Library shows every one of
  them as `auto` with the family the lane rule chose.
- D1: a confirm on a source whose correction is already built keeps it `corrected`.
- D3: a confirm while the connector's families are unknown keeps a valid correction.

Like the neighbouring modules, each test that needs a test client imports it inside the function
and carries the per-test marker of rulebook form (a).
"""

from __future__ import annotations

import pytest

from tests.unit.test_connector_sync import _TwoFamilySpyConnector, ctx, registry  # noqa: F401
from tests.unit.test_source_inventory import (  # noqa: F401
    ANYIO,
    _client,
    _load,
    _row_html,
    _TwoFamilyConnector,
    inventory,
)

INFERENCE_PATHS = ("/api/chat", "/api/generate", "/api/embed", "/api/embeddings", "/api/pull")
INFERENCE_METHODS = ("chat_text", "chat_json", "embed", "embed_one", "embed_explicit")
STATE_KINDS = ("Generation", "SyncState", "SyncRun", "MaintenanceJob")


def _snapshot(store):
    return {
        "sources": store.list_sources(),
        **{kind: sorted(row.id for row in store._knowledge_rows(kind)) for kind in STATE_KINDS},
    }


# ------------------------------------------------------------------ I1


def _spies(context, monkeypatch):
    """Record every model call, job start and connector load, and still run the real one."""
    from hippo.connectors import loader

    model_calls, requests, starts, loads = [], [], [], []
    for name in INFERENCE_METHODS:
        real = getattr(context.ollama, name)

        def spy(*args, _name=name, _real=real, **kwargs):
            model_calls.append(_name)
            return _real(*args, **kwargs)

        monkeypatch.setattr(context.ollama, name, spy)
    real_request = context.ollama._request
    monkeypatch.setattr(
        context.ollama,
        "_request",
        lambda method, path, **kwargs: (
            requests.append((method, path)) or real_request(method, path, **kwargs)
        ),
    )
    real_start = context.jobs.start
    monkeypatch.setattr(context.jobs, "start", lambda key, work: starts.append(key) or real_start(key, work))
    real_load = loader.load_connectors
    monkeypatch.setattr(
        loader, "load_connectors", lambda *args, **kwargs: loads.append(args) or real_load(*args, **kwargs)
    )
    return model_calls, requests, starts, loads


@pytest.mark.filterwarnings(ANYIO)
def test_i1_the_spies_see_a_model_call_a_job_a_connector_load_and_a_write(ctx, monkeypatch):  # noqa: F811
    """Positive control: the I1 test below is only worth its green if these spies can go red."""
    from hippo.connectors import loader

    ctx.store.ping()
    model_calls, requests, starts, loads = _spies(ctx, monkeypatch)
    before = _snapshot(ctx.store)
    ctx.ollama.embed(["control"])
    assert ctx.jobs.start("control", lambda: None) is True
    ctx.jobs.wait("control", timeout=10)
    loader.load_connectors(ctx)
    ctx.store.create_source("text", "control")
    assert model_calls == ["embed"] and ("POST", "/api/embed") in requests
    assert starts == ["control"]
    assert len(loads) == 1
    assert _snapshot(ctx.store) != before


@pytest.mark.filterwarnings(ANYIO)
def test_i1_reading_the_library_makes_no_model_call_starts_no_job_writes_nothing(inventory, monkeypatch):  # noqa: F811
    inv = inventory
    context = inv.ctx
    client = _client(inv)
    model_calls, requests, starts, loads = _spies(context, monkeypatch)

    embedded = list(context.embed_recorder.embedded)
    running = list(context.jobs.running_keys())
    before = _snapshot(inv.store)
    paths = (
        "/",
        "/partials/sources",
        "/api/sources",
        f"/sources/{inv.text}",
        f"/sources/{inv.upload}",
        f"/sources/{inv.connector}",
    )
    for path in paths:
        response = client.get(path)
        assert response.status_code in (200, 286), (path, response.status_code)

    assert model_calls == [], model_calls
    assert [pair for pair in requests if pair[1] in INFERENCE_PATHS] == [], requests
    assert context.embed_recorder.embedded == embedded
    assert starts == [], starts
    assert list(context.jobs.running_keys()) == running
    assert loads == [], "the listing loaded connector packages on a request"
    assert _snapshot(inv.store) == before, "reading the Library changed the store"


# ------------------------------------------------------------------ I5

V8_SOURCES = (
    ("text", "pasted notes", {}, "prose"),
    ("prose file", "notes.md", {"file": "notes.md"}, "prose"),
    ("code file", "app.py", {"file": "app.py"}, "code"),
    ("rich file", "report.pdf", {"file": "report.pdf"}, "prose"),
    ("archive", "project.zip", {"file": "project.zip"}, "code"),
    ("repo", "billing repo", {}, "code"),
    ("sample", "Acme Robotics", {}, "prose"),
)
V8_KINDS = {
    "text": "text",
    "prose file": "file",
    "code file": "file",
    "rich file": "file",
    "archive": "archive",
    "repo": "repo",
    "sample": "sample",
}


@pytest.mark.filterwarnings(ANYIO)
def test_i5_a_v8_ladybug_store_reopens_as_v9_and_the_library_shows_every_source_as_auto(
    tmp_path, ollama, monkeypatch
):
    from fastapi.testclient import TestClient

    from hippo.access import EVERYTHING
    from hippo.config import Config
    from hippo.context import AppContext
    from hippo.knowledge.query_access import query_session
    from hippo.status import source_view
    from hippo.store import migrations as m
    from hippo.store.ladybug import LadybugStore
    from hippo.web.app import create_app

    path = tmp_path / "version8.lbug"
    ids = {}
    with monkeypatch.context() as patch:
        patch.setattr(m, "CURRENT_SCHEMA_VERSION", 8)
        store = LadybugStore(path)
        assert store.schema_version()["version"] == 8
        for label, name, meta, _ in V8_SOURCES:
            ids[label] = store.create_source(V8_KINDS[label], name, meta)
            store.update_source(ids[label], status="ready", stage="done")
        ids["connector"] = store.create_source(
            "connector", "orphan partition", {"connector_id": "gone", "partition": "p1"}
        )
        stored = {label: store.get_source(source_id) for label, source_id in ids.items()}
        store.close()

    reopened = LadybugStore(path)
    try:
        assert reopened.schema_version() == {
            "version": 9,
            "checksum": m.MIGRATION_CHECKSUM,
            "state": "complete",
            "step": len(m.schema_steps(reopened, version=9)),
        }
        context = AppContext(config=Config(data_dir=tmp_path / "data"), store=reopened, ollama=ollama)
        expected = {label: family for label, _, _, family in V8_SOURCES} | {"connector": "custom"}
        with query_session(context, EVERYTHING) as session:
            view = source_view(context, EVERYTHING, session=session)
            rows = {row["id"]: row for row in view.sources}
            view.validate()
        assert set(rows) == set(ids.values()), "a v8 source is missing from the Library"
        for label, source_id in ids.items():
            row = rows[source_id]
            assert row["domain"] == expected[label], label
            assert row["domain_state"] == "auto", label
            assert (row["domain_confirmed_at"], row["domain_confirmed_by"]) == (None, None), label
            assert row["domain_origin"] == ("fallback" if label == "connector" else "lane"), label
            # I5: v9 rewrote no data, so the row a v8 store held reads back as it was.
            after = reopened.get_source(source_id)
            assert {key: after[key] for key in stored[label]} == stored[label], label
            assert after["domain_override"] is None, label

        html = TestClient(create_app(context), base_url="http://localhost").get("/").text
        for label, source_id in ids.items():
            row_html = _row_html(html, source_id)
            assert "auto" in row_html and expected[label] in row_html, label
            assert f'action="/sources/{source_id}/domain"' in row_html, label
    finally:
        reopened.close()


# ------------------------------------------------------------------ D1, D3: a confirm keeps a correction


@pytest.mark.filterwarnings(ANYIO)
def test_d1_a_confirm_after_a_built_correction_keeps_the_state_corrected(inventory):  # noqa: F811
    inv = inventory
    client = _client(inv, connector_load=_load(_TwoFamilyConnector))
    url = f"/api/sources/{inv.connector}/domain"
    assert client.put(url, json={"family": "service"}).status_code == 200
    receipt = inv.world.sync(connector=_TwoFamilySpyConnector(inv.world.connector_impl, []))
    assert receipt.outcome == "published"
    built = client.get(f"/api/sources/{inv.connector}").json()
    assert (built["domain"], built["domain_state"]) == ("service", "corrected")

    confirmed = client.put(url, json={"family": None})
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert (body["source"]["domain"], body["source"]["domain_state"]) == ("service", "corrected")
    assert body["rebuild"]["needed"] is False


@pytest.mark.filterwarnings(ANYIO)
def test_d3_a_confirm_without_the_connector_families_keeps_a_valid_correction(inventory):  # noqa: F811
    inv = inventory
    url = f"/api/sources/{inv.connector}/domain"
    assert (
        _client(inv, connector_load=_load(_TwoFamilyConnector))
        .put(url, json={"family": "service"})
        .status_code
        == 200
    )
    before = inv.store.get_source(inv.connector)["domain_override"]
    assert before == "service"

    # No connector load: this server cannot list the connector's families, so a confirm must not
    # decide that the stored correction is invalid. Either it keeps it, or it refuses without a write.
    _client(inv).put(url, json={"family": None})
    assert inv.store.get_source(inv.connector)["domain_override"] == "service"
