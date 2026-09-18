"""Confirm and correct a source's domain: `POST /sources/{id}/domain` and `PUT /api/sources/{id}/domain`.

Plan `ai_docs/plans/2026-09-18-knowledge-inventory-domain-plan.md` task T3, section 3.5, acceptance
A4, A5 (its default, refused form: OD1 enables no coordinator transition), A7 and A8; A12 is in
`tests/unit/test_web_auth.py`. Design D4, D5 and D9. Every write goes through `set_source_domain`,
which never bumps `updated_at` (P2), and no route starts a build: a connector correction answers
with the exact `hippo connector sync` command instead.

The sources are T2's inventory (`test_source_inventory.inventory`): legacy pasted text, a managed
plain-prose upload, a managed repository and a fixture-connector partition after one real sync.
Like that module, every test that needs a test client imports it inside the function and carries
the per-test marker of rulebook form (a).
"""

from __future__ import annotations

import pytest
from markupsafe import escape

from hippo.status import WITHHELD_INVENTORY
from tests.fakes.fixture_connector import FixtureConnector
from tests.unit.test_connector_sync import _TwoFamilySpyConnector, ctx, registry  # noqa: F401
from tests.unit.test_source_inventory import (  # noqa: F401
    ANYIO,
    _client,
    _load,
    _TwoFamilyConnector,
    inventory,
)

DOMAIN_COLUMNS = ("domain_override", "domain_confirmed_at", "domain_confirmed_by")
QUESTION = "Is this the right domain?"


def _columns(store, source_id):
    row = store.get_source(source_id)
    return {column: row.get(column) for column in DOMAIN_COLUMNS}


def _card(html: str) -> str:
    """The source page's Domain card; the page has other forms and selects."""
    return html.split("<h3>Domain</h3>", 1)[1].split("</section>", 1)[0]


def _open_client(ctx):  # noqa: F811
    """No users at all: open mode, where the caller is the top role and has no user id."""
    from fastapi.testclient import TestClient

    from hippo.web.app import create_app

    return TestClient(create_app(ctx), base_url="http://localhost")


# ------------------------------------------------------------------ A4: confirm


@pytest.mark.filterwarnings(ANYIO)
def test_confirm_open_mode(ctx):  # noqa: F811
    ctx.store.ping()
    text = ctx.store.create_source("text", "Pasted notes", {})
    before = ctx.store.get_source(text)
    response = _open_client(ctx).put(f"/api/sources/{text}/domain", json={"family": None})
    assert response.status_code == 200, response.text
    body = response.json()
    source = body["source"]
    assert (source["id"], source["domain"], source["domain_state"]) == (text, "prose", "confirmed")
    assert source["domain_confirmed_at"] is not None and source["domain_confirmed_by"] is None
    assert body["rebuild"] == {"needed": False, "started": False, "command": None}
    stored = ctx.store.get_source(text)
    assert stored["domain_override"] is None and stored["domain_confirmed_by"] is None
    assert stored["domain_confirmed_at"] == source["domain_confirmed_at"]
    # P2: the domain write is not activity; the legacy lane's "last activity" stays put.
    assert stored["updated_at"] == before["updated_at"]


@pytest.mark.filterwarnings(ANYIO)
def test_confirm_signed_in(inventory):  # noqa: F811
    inv = inventory
    response = _client(inv).put(f"/api/sources/{inv.text}/domain", json={"family": None})
    assert response.status_code == 200, response.text
    source = response.json()["source"]
    assert (source["domain"], source["domain_state"]) == ("prose", "confirmed")
    assert source["domain_confirmed_by"] == inv.user
    assert _columns(inv.store, inv.text) == {
        "domain_override": None,
        "domain_confirmed_at": source["domain_confirmed_at"],
        "domain_confirmed_by": inv.user,
    }


@pytest.mark.filterwarnings(ANYIO)
def test_confirm_with_the_natural_family_named(inventory):  # noqa: F811
    """Naming the natural family is a confirm: it writes no override."""
    inv = inventory
    response = _client(inv).put(f"/api/sources/{inv.repo}/domain", json={"family": "code"})
    assert response.status_code == 200, response.text
    assert response.json()["source"]["domain_state"] == "confirmed"
    assert _columns(inv.store, inv.repo)["domain_override"] is None


@pytest.mark.filterwarnings(ANYIO)
def test_confirm_form_redirects(inventory):  # noqa: F811
    inv = inventory
    client = _client(inv)
    response = client.post(
        f"/sources/{inv.text}/domain", data={"family": "", "back": "/"}, follow_redirects=False
    )
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert _columns(inv.store, inv.text)["domain_confirmed_by"] == inv.user
    page = f"/sources/{inv.upload}"
    response = client.post(
        f"/sources/{inv.upload}/domain", data={"family": "", "back": page}, follow_redirects=False
    )
    assert response.status_code == 303 and response.headers["location"] == page
    # The access form's open-redirect guard: anything but a local path goes to the Library.
    for back in ("https://evil.example/", "//evil.example/x", "evil"):
        response = client.post(
            f"/sources/{inv.repo}/domain", data={"family": "", "back": back}, follow_redirects=False
        )
        assert response.status_code == 303 and response.headers["location"] == "/", back


@pytest.mark.filterwarnings(ANYIO)
def test_confirm_twice_restamps_only(inventory):  # noqa: F811
    inv = inventory
    client = _client(inv)
    first = client.put(f"/api/sources/{inv.text}/domain", json={"family": None}).json()["source"]
    stored = inv.store.get_source(inv.text)
    second = client.put(f"/api/sources/{inv.text}/domain", json={"family": None}).json()["source"]
    again = inv.store.get_source(inv.text)
    assert second["domain_confirmed_at"] > first["domain_confirmed_at"]
    assert again["domain_confirmed_at"] == second["domain_confirmed_at"]
    assert {key: value for key, value in again.items() if key != "domain_confirmed_at"} == {
        key: value for key, value in stored.items() if key != "domain_confirmed_at"
    }
    assert {key: value for key, value in second.items() if key != "domain_confirmed_at"} == {
        key: value for key, value in first.items() if key != "domain_confirmed_at"
    }


# ------------------------------------------------------------------ A7, A5: only allowed families


@pytest.mark.filterwarnings(ANYIO)
def test_out_of_set_family_is_refused_without_a_write(inventory):  # noqa: F811
    inv = inventory
    client = _client(inv)
    before = _columns(inv.store, inv.text)
    response = client.put(f"/api/sources/{inv.text}/domain", json={"family": "db"})
    assert response.status_code == 400
    assert response.json()["code"] == "domain_not_allowed" and response.json()["error"]
    assert _columns(inv.store, inv.text) == before
    # The form answers the same refusal on the page it came from.
    page = f"/sources/{inv.text}"
    response = client.post(
        f"/sources/{inv.text}/domain", data={"family": "db", "back": page}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"{page}?error=")
    assert _columns(inv.store, inv.text) == before


@pytest.mark.filterwarnings(ANYIO)
def test_coordinator_correction_is_refused_and_fixed(inventory):  # noqa: F811
    inv = inventory
    client = _client(inv)
    before = _columns(inv.store, inv.upload)
    response = client.put(f"/api/sources/{inv.upload}/domain", json={"family": "code"})
    assert response.status_code == 400 and response.json()["code"] == "domain_not_allowed"
    assert _columns(inv.store, inv.upload) == before
    card = _card(client.get(f"/sources/{inv.upload}").text)
    assert "Plain-text files are always built as prose." in card
    assert QUESTION in card and "Yes, confirm" in card
    assert "<select" not in card and "Apply" not in card


# ------------------------------------------------------------------ A8: connector correction


@pytest.mark.filterwarnings(ANYIO)
def test_connector_correction_is_pending_until_sync(inventory):  # noqa: F811
    inv = inventory
    client = _client(inv, connector_load=_load(_TwoFamilyConnector))
    listed = client.get(f"/api/sources/{inv.connector}").json()
    command = listed["resync_command"]
    assert command and listed["domain"] == "custom"

    response = client.put(f"/api/sources/{inv.connector}/domain", json={"family": "service"})
    assert response.status_code == 200, response.text
    body = response.json()
    source = body["source"]
    assert body["rebuild"] == {"needed": True, "started": False, "command": command}
    assert (source["domain"], source["domain_origin"], source["domain_state"]) == (
        "service",
        "user",
        "pending_rebuild",
    )
    # The families come from the server's connector load, so the row says what the check used.
    assert source["domain_allowed"] == ["service", "custom"] and source["domain_fixed_reason"] is None
    assert _columns(inv.store, inv.connector) == {
        "domain_override": "service",
        "domain_confirmed_at": source["domain_confirmed_at"],
        "domain_confirmed_by": inv.user,
    }
    # I3: nothing was rebuilt; the generation that served before still serves.
    assert inv.store.get_source(inv.connector)["active_generation_id"] == inv.connector_generation

    card = _card(client.get(f"/sources/{inv.connector}").text)
    assert "pending rebuild" in card and f"<code>{command}</code>" in card

    # The connector kit's sync under the override advances `SyncState.last_success_at`.
    receipt = inv.world.sync(connector=_TwoFamilySpyConnector(inv.world.connector_impl, []))
    assert receipt.outcome == "published"
    assert inv.world.sync_state().last_success_at.isoformat() >= source["domain_confirmed_at"]
    again = client.get(f"/api/sources/{inv.connector}").json()
    assert (again["domain"], again["domain_state"]) == ("service", "corrected")

    # Naming the natural family again confirms it and clears the correction.
    back = client.put(f"/api/sources/{inv.connector}/domain", json={"family": "custom"})
    assert back.status_code == 200, back.text
    assert (back.json()["source"]["domain"], back.json()["source"]["domain_state"]) == ("custom", "confirmed")
    assert _columns(inv.store, inv.connector)["domain_override"] is None


@pytest.mark.filterwarnings(ANYIO)
def test_a_connector_family_is_refused_when_the_families_are_unknown(inventory):  # noqa: F811
    """Without the server's connector load the families are unknown, so only confirm is allowed."""
    inv = inventory
    before = _columns(inv.store, inv.connector)
    response = _client(inv).put(f"/api/sources/{inv.connector}/domain", json={"family": "service"})
    assert response.status_code == 400 and response.json()["code"] == "domain_not_allowed"
    assert _columns(inv.store, inv.connector) == before
    missing = _client(inv, connector_load=_load(None))
    response = missing.put(f"/api/sources/{inv.connector}/domain", json={"family": "service"})
    assert response.status_code == 400 and response.json()["code"] == "domain_not_allowed"
    assert missing.put(f"/api/sources/{inv.connector}/domain", json={"family": None}).status_code == 200


@pytest.mark.filterwarnings(ANYIO)
def test_a_confirm_clears_an_override_the_connector_no_longer_declares(inventory):  # noqa: F811
    """OD7: after an upgrade drops the family, the page shows the override outside the allowed set."""
    inv = inventory
    two = _client(inv, connector_load=_load(_TwoFamilyConnector))
    assert two.put(f"/api/sources/{inv.connector}/domain", json={"family": "service"}).status_code == 200
    one = _client(inv, connector_load=_load(FixtureConnector))
    stale = one.get(f"/sources/{inv.connector}")
    assert "The fixture connector declares only the custom domain." in _card(stale.text)
    response = one.put(f"/api/sources/{inv.connector}/domain", json={"family": None})
    assert response.status_code == 200, response.text
    source = response.json()["source"]
    assert (source["domain"], source["domain_state"]) == ("custom", "confirmed")
    assert response.json()["rebuild"]["needed"] is False
    assert _columns(inv.store, inv.connector)["domain_override"] is None


# ------------------------------------------------------------------ what the caller may not reach


@pytest.mark.filterwarnings(ANYIO)
def test_unknown_and_withheld_sources_are_404(inventory, monkeypatch):  # noqa: F811
    from hippo.web.routes import sources as routes

    inv = inventory
    client = _client(inv)
    assert client.put("/api/sources/no-such-source/domain", json={"family": None}).status_code == 404
    real = routes.source_view

    def withheld(*args, **kwargs):
        view = real(*args, **kwargs)
        for row in view.sources:
            if row["id"] == inv.upload:
                row.update(WITHHELD_INVENTORY, kind="managed")
        return view

    monkeypatch.setattr(routes, "source_view", withheld)
    before = _columns(inv.store, inv.upload)
    assert client.put(f"/api/sources/{inv.upload}/domain", json={"family": None}).status_code == 404
    form = client.post(
        f"/sources/{inv.upload}/domain", data={"family": "", "back": "/"}, follow_redirects=False
    )
    assert form.status_code == 404
    assert _columns(inv.store, inv.upload) == before


# ------------------------------------------------------------------ the two partials


@pytest.mark.filterwarnings(ANYIO)
def test_the_library_row_offers_confirm_only_while_auto(inventory):  # noqa: F811
    from tests.unit.test_source_inventory import _row_html

    inv = inventory
    client = _client(inv)
    row = _row_html(client.get("/").text, inv.text)
    assert f'action="/sources/{inv.text}/domain"' in row
    assert '<input type="hidden" name="family" value="">' in row
    assert '<input type="hidden" name="back" value="/">' in row
    assert ">Confirm<" in row
    client.put(f"/api/sources/{inv.text}/domain", json={"family": None})
    row = _row_html(client.get("/partials/sources").text, inv.text)
    assert f'action="/sources/{inv.text}/domain"' not in row


@pytest.mark.filterwarnings(ANYIO)
def test_the_library_row_confirm_waits_for_indexing(inventory, monkeypatch):  # noqa: F811
    from tests.unit.test_source_inventory import _row_html

    inv = inventory
    monkeypatch.setattr(inv.ctx.jobs, "running_keys", lambda: [f"index:{inv.text}"])
    row = _row_html(_client(inv).get("/").text, inv.text)
    confirm = row.split(f'action="/sources/{inv.text}/domain"', 1)[1].split("</form>", 1)[0]
    assert "disabled" in confirm


@pytest.mark.filterwarnings(ANYIO)
def test_the_source_page_offers_a_change_only_for_several_families(inventory):  # noqa: F811
    inv = inventory
    fixed = _card(_client(inv).get(f"/sources/{inv.connector}").text)
    assert QUESTION in fixed and "Yes, confirm" in fixed
    assert str(escape("This process does not know the connector's declared domains.")) in fixed
    assert "<select" not in fixed

    client = _client(inv, connector_load=_load(_TwoFamilyConnector))
    command = client.get(f"/api/sources/{inv.connector}").json()["resync_command"]
    card = _card(client.get(f"/sources/{inv.connector}").text)
    assert f'action="/sources/{inv.connector}/domain"' in card
    assert '<select name="family"' in card
    assert '<option value="service">service</option>' in card
    assert '<option value="custom" selected>custom</option>' in card
    assert "Apply" in card and "next sync" in card
    assert f"<code>{command}</code>" in card
    # The test store's config is the default, LadybugDB, which `hippo serve` holds open.
    assert "Stop <code>hippo serve</code> first." in card
    assert f'<input type="hidden" name="back" value="/sources/{inv.connector}">' in card


@pytest.mark.filterwarnings(ANYIO)
def test_the_domain_actions_are_hidden_from_a_reader_who_may_not_manage(inventory):  # noqa: F811
    inv = inventory
    reader = inv.store.create_user("reader", "password", "individual")
    inv.store.set_source_access(inv.text, None)
    client = _client(inv)
    client.headers["Authorization"] = "Bearer " + inv.store.get_user(reader)["token"]
    page = client.get(f"/sources/{inv.text}")
    assert page.status_code == 200
    card = _card(page.text)
    assert "prose" in card and QUESTION not in card and "<form" not in card
    row = client.get("/").text
    assert f'action="/sources/{inv.text}/domain"' not in row
    response = client.put(f"/api/sources/{inv.text}/domain", json={"family": None})
    assert response.status_code == 403
