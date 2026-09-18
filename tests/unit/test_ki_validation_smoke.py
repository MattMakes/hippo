"""T5 smoke: the Library, the source page and a confirm, one source per lane, through the test client only.

Plan `ai_docs/plans/2026-09-18-knowledge-inventory-domain-plan.md` task T5. The sources are T2's
`inventory` fixture: legacy pasted text, a managed plain-prose upload and a fixture-connector
partition after one real sync (plus a managed repository for the form route). No live server, no
Ollama and no user data are involved. The test client is imported inside each function, and each
test carries the per-test marker of rulebook form (a), like its neighbours.
"""

from __future__ import annotations

import pytest

from tests.unit.test_connector_sync import ctx, registry  # noqa: F401
from tests.unit.test_source_inventory import ANYIO, _client, _row_html, inventory  # noqa: F401

LANES = ("text", "upload", "connector")
EXPECTED = {
    "text": ("legacy", "prose"),
    "upload": ("managed", "prose"),
    "connector": ("connector", "custom"),
}


def _card(html: str) -> str:
    return html.split("<h3>Domain</h3>", 1)[1].split("</section>", 1)[0]


@pytest.mark.filterwarnings(ANYIO)
def test_smoke_pages_render_and_a_confirm_reads_back_as_confirmed_on_every_lane(inventory):  # noqa: F811
    inv = inventory
    client = _client(inv)
    ids = {name: getattr(inv, name) for name in LANES}

    for path in ("/", "/partials/sources"):
        response = client.get(path)
        assert response.status_code in (200, 286), (path, response.status_code)
        for source_id in ids.values():
            assert f'href="/sources/{source_id}"' in response.text, (path, source_id)

    before = {}
    for name, source_id in ids.items():
        page = client.get(f"/sources/{source_id}")
        assert page.status_code == 200, name
        assert "<h3>Domain</h3>" in page.text and "<h3>Sync</h3>" in page.text, name
        row = client.get(f"/api/sources/{source_id}").json()
        assert (row["lane"], row["domain"]) == EXPECTED[name], name
        assert row["domain_state"] == "auto" and row["domain_confirmed_at"] is None, name
        before[name] = row

    for name, source_id in ids.items():
        response = client.put(f"/api/sources/{source_id}/domain", json={"family": None})
        assert response.status_code == 200, (name, response.text)
        body = response.json()
        assert body["source"]["domain_state"] == "confirmed", name
        assert body["rebuild"] == {"needed": False, "started": False, "command": None}, name

    for name, source_id in ids.items():
        row = client.get(f"/api/sources/{source_id}").json()
        assert row["domain_state"] == "confirmed", name
        assert row["domain"] == before[name]["domain"], name
        assert row["domain_confirmed_at"] and row["domain_confirmed_by"] == inv.user, name
        page = client.get(f"/sources/{source_id}")
        assert page.status_code == 200 and "confirmed" in _card(page.text), name
        for path in ("/", "/partials/sources"):
            library = client.get(path)
            assert library.status_code in (200, 286)
            assert "confirmed" in _row_html(library.text, source_id), (path, name)
            assert f'action="/sources/{source_id}/domain"' not in _row_html(library.text, source_id)


@pytest.mark.filterwarnings(ANYIO)
def test_smoke_the_library_row_form_confirms_a_managed_repository(inventory):  # noqa: F811
    inv = inventory
    client = _client(inv)
    row = _row_html(client.get("/").text, inv.repo)
    assert f'action="/sources/{inv.repo}/domain"' in row
    response = client.post(
        f"/sources/{inv.repo}/domain", data={"family": "", "back": "/"}, follow_redirects=False
    )
    assert response.status_code == 303 and response.headers["location"] == "/"
    after = client.get(f"/api/sources/{inv.repo}").json()
    assert (after["lane"], after["domain"], after["domain_state"]) == ("managed", "code", "confirmed")
    assert f'action="/sources/{inv.repo}/domain"' not in _row_html(
        client.get("/partials/sources").text, inv.repo
    )
