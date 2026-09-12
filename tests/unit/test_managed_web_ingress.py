"""Every web ingress route brings the real reader, and a managed failure stays private.

This is the web half of PA1 and PA6 for the source, page, user and API routes:
`web/app.py`, `web/auth.py` and `web/routes/{api,pages,sources,users}.py`.

Three contracts are under test.

1. **The actor is the boundary identity.** A signed-in reader pasting text or
   uploading a plain file has their own `BuildActor.reader(principal)` passed to
   the pipeline. Open mode and preview identities bring no actor at all, so they
   keep the legacy lane; web code never manufactures `trusted_local()`, and no
   job ever captures a Request, cookie or token.
2. **A managed failure reaches the client as a closed public code.** The body is
   `{"error": failure.message, "code": failure.code}` with the mapper's own HTTP
   status, and an unknown exception inside a managed path becomes
   `operation_failed` rather than its own words. A permission change keeps the
   sentence clients already read and carries `authorization_changed`, which is the
   word the managed lane already stores for that condition.
3. **One structural owner per response.** Each route acquires one graph, builds
   its DTO over it, and releases it once; a permission change between the DTO and
   the response is the existing 409.

The module imports `fastapi.testclient`, so every gate line that includes it
carries the command-line AnyIO ignore (form (b) in the rulebook).
"""

from __future__ import annotations

import io
import logging
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hippo import ask as ask_service
from hippo.access import Principal
from hippo.ingest import pipeline
from hippo.ingest.managed_activation import ManagedActorRequired
from hippo.knowledge.access import AuthorizationChanged
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.dense import DenseUnavailable
from hippo.knowledge.public_errors import (
    OPERATION_FAILED,
    REBUILD_REQUIRED,
    RETRIEVAL_UNAVAILABLE,
)
from hippo.ollama import OllamaError
from hippo.web import auth as web_auth
from hippo.web.app import create_app
from hippo.web.render import STOP_POLLING
from tests.unit.test_managed_pipeline_activation import (  # noqa: F401 - imported as fixtures
    FIRST_TEXT,
    lanes,
    setup,
    wait,
)

QUESTION = "who builds the thing?"

# Everything a leaked exception could carry, in one string. Each fragment is
# implausible on purpose: nothing a correct response contains can match it.
POISON = (
    "token=sk-live-DEADBEEF at /private/absolute/notes.md while reading "
    '"Bristlecone confidential passage" body={"error":"the model refused"}'
)
SECRETS = (
    "sk-live-DEADBEEF",
    "/private/absolute/notes.md",
    "Bristlecone confidential passage",
    "the model refused",
)

PERMISSION_RESPONSE = {
    "error": "Permissions changed; repeat the query",
    "code": "authorization_changed",
}


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def web(setup):  # noqa: F811 - the managed-pipeline fixture is the local reader and model
    """A signed-in reader, an admin, and a client over the real app."""
    w = setup
    store = w.ctx.store
    admin = store.create_user("keeper", "password1", "arch-admin")
    with TestClient(create_app(w.ctx), base_url="http://localhost") as client:
        yield SimpleNamespace(
            ctx=w.ctx,
            store=store,
            client=client,
            setup=w,
            actor=w.actor,
            reader=w.user,
            reader_headers={"Authorization": f"Bearer {store.get_user(w.user)['token']}"},
            admin=admin,
            admin_headers={"Authorization": f"Bearer {store.get_user(admin)['token']}"},
        )


@pytest.fixture
def open_client(ctx):
    """No user has ever existed, so every caller is the open principal."""
    ctx.store.ensure_schema()
    ctx.store.ensure_roles()
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        yield SimpleNamespace(ctx=ctx, client=client)


def spy(monkeypatch, name: str) -> list:
    """Record the `build_actor` of every call to one pipeline entry point."""
    seen: list = []
    real = getattr(pipeline, name)

    def recorded(ctx, *args, **kwargs):
        seen.append(kwargs.get("build_actor"))
        return real(ctx, *args, **kwargs)

    monkeypatch.setattr(pipeline, name, recorded)
    return seen


def raises(error: BaseException):
    def fail(*args, **kwargs):
        raise error

    return fail


def zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.md", FIRST_TEXT)
    return buffer.getvalue()


def managed_source(web) -> str:
    """One real managed source, published through the coordinator over HTTP."""
    response = web.client.post(
        "/api/sources/text", json={"name": "Notes", "text": FIRST_TEXT}, headers=web.reader_headers
    )
    assert response.status_code == 200, response.text
    source_id = response.json()["source_id"]
    wait(web.ctx)
    row = web.store.get_source(source_id)
    assert row["managed"] and row["active_generation_id"]
    return source_id


def say_nothing_private(*texts: str) -> None:
    for text in texts:
        for secret in SECRETS:
            assert secret not in text, f"{secret!r} reached a public surface"


# ------------------------------------------------- the actor at every ingress


INGRESS = {
    "page_text": lambda c, h: c.post(
        "/sources/text", data={"name": "Notes", "text": FIRST_TEXT}, headers=h, follow_redirects=False
    ),
    "api_text": lambda c, h: c.post(
        "/api/sources/text", json={"name": "Notes", "text": FIRST_TEXT}, headers=h
    ),
    "page_upload": lambda c, h: c.post(
        "/sources/upload",
        files={"files": ("notes.md", FIRST_TEXT.encode(), "text/markdown")},
        headers=h,
        follow_redirects=False,
    ),
    "api_upload": lambda c, h: c.post(
        "/api/sources/upload",
        files={"file": ("notes.md", FIRST_TEXT.encode(), "text/markdown")},
        headers=h,
    ),
}


@pytest.mark.parametrize("route", sorted(INGRESS))
def test_a_signed_in_reader_brings_their_own_build_actor(web, monkeypatch, route):
    web.setup.quiet_jobs()
    seen = spy(monkeypatch, "add_text") if "text" in route else spy(monkeypatch, "add_upload")
    response = INGRESS[route](web.client, web.reader_headers)
    assert response.status_code in (200, 303), response.text
    assert seen == [web.actor]
    assert seen[0].kind == "reader" and seen[0].user_id == web.reader


@pytest.mark.parametrize("route", sorted(INGRESS))
def test_open_mode_ingress_keeps_the_legacy_lane(open_client, monkeypatch, route):
    seen = lanes(monkeypatch)
    response = INGRESS[route](open_client.client, {})
    assert response.status_code in (200, 303), response.text
    wait(open_client.ctx)
    assert [lane for lane, _ in seen] == ["legacy"]


def test_open_and_preview_identities_bring_no_actor(web):
    reader = Principal.for_user(web.store.get_user(web.reader), web.store.get_role("individual"))
    assert web_auth.build_actor_of(reader) == web.actor
    assert web_auth.build_actor_of(Principal.open()) is None
    assert web_auth.build_actor_of(reader.as_role(web.store.get_role("local-admin"))) is None


def test_web_code_never_manufactures_a_trusted_local_actor(web, monkeypatch):
    """The trusted-local actor is for explicit internal calls, never an authentication fallback."""
    web.setup.quiet_jobs()
    monkeypatch.setattr(
        BuildActor, "trusted_local", classmethod(lambda cls: pytest.fail("web code built trusted_local"))
    )
    for route in sorted(INGRESS):
        assert INGRESS[route](web.client, web.reader_headers).status_code in (200, 303)


@pytest.mark.parametrize(
    "filename,data",
    [
        ("paper.pdf", b"%PDF-1.4 not really a pdf"),
        ("module.py", b"print('hello')\n"),
        ("bundle.zip", None),
    ],
)
def test_an_unsupported_upload_stays_legacy_for_a_signed_in_reader(web, monkeypatch, filename, data):
    seen = lanes(monkeypatch)
    payload = zip_bytes() if data is None else data
    response = web.client.post(
        "/api/sources/upload",
        files={"file": (filename, payload, "text/markdown")},  # a claimed type never decides
        headers=web.reader_headers,
    )
    assert response.status_code == 200, response.text
    wait(web.ctx)
    assert seen == [("legacy", response.json()["source_id"])]


def test_repo_and_sample_stay_legacy_for_a_signed_in_reader(web, monkeypatch):
    seen = lanes(monkeypatch)
    repo = web.client.post(
        "/api/sources/repo", json={"url": "https://example.com/owner/repo"}, headers=web.reader_headers
    )
    sample = web.client.post("/api/sources/sample", headers=web.reader_headers)
    assert (repo.status_code, sample.status_code) == (200, 200), (repo.text, sample.text)
    wait(web.ctx)
    assert seen == [("legacy", repo.json()["source_id"]), ("legacy", sample.json()["source_id"])]


def test_a_role_without_add_sources_is_refused_before_any_actor_exists(web, monkeypatch):
    role = web.store.create_role("Guest", 0, "reads only", [])
    guest = web.store.create_user("guest", "password1", role)
    headers = {"Authorization": f"Bearer {web.store.get_user(guest)['token']}"}
    seen = spy(monkeypatch, "add_text")
    response = web.client.post("/api/sources/text", json={"name": "N", "text": FIRST_TEXT}, headers=headers)
    assert response.status_code == 403 and "add_sources" in response.json()["detail"]
    assert seen == []


def test_pasted_text_from_a_signed_in_reader_publishes_a_managed_generation(web):
    source_id = managed_source(web)
    row = web.store.get_source(source_id)
    assert (row["status"], row["stage"]) == ("ready", "ready")
    listed = web.client.get("/api/sources", headers=web.reader_headers).json()
    assert [source["id"] for source in listed] == [source_id]


def test_reindexing_brings_the_authorized_managers_actor(web, monkeypatch):
    source_id = managed_source(web)
    seen = spy(monkeypatch, "reindex")
    web.setup.quiet_jobs()
    response = web.client.post(f"/api/sources/{source_id}/reindex", headers=web.reader_headers)
    assert response.status_code == 200, response.text
    assert seen == [web.actor]


def test_deleting_brings_the_authorized_managers_actor(web, monkeypatch):
    source_id = managed_source(web)
    seen = spy(monkeypatch, "delete_source")
    response = web.client.delete(f"/api/sources/{source_id}", headers=web.reader_headers)
    assert response.status_code == 200 and response.json() == {"deleted": source_id}
    assert seen == [web.actor]
    assert web.client.get(f"/api/sources/{source_id}", headers=web.reader_headers).status_code == 404


def test_bulk_reindex_brings_the_bulk_managers_actor(web, monkeypatch):
    managed_source(web)
    seen = spy(monkeypatch, "reindex_all")
    started = spy(monkeypatch, "start_indexing")
    response = web.client.post("/api/sources/reindex-all", headers=web.admin_headers)
    assert response.status_code == 200 and response.json() == {"accepted": True}
    assert [actor.kind for actor in seen] == ["reader"]
    assert seen[0].user_id == web.admin
    # `{"accepted": true}` has to mean something was accepted: the actor alone would stay
    # green on a bulk that silently started nothing (4b-i review F7).
    assert started, "the bulk acknowledged acceptance without submitting a lane"


# ------------------------------------------------------- closed public codes


@pytest.mark.parametrize(
    "error,failure",
    [
        (OllamaError(POISON), RETRIEVAL_UNAVAILABLE),
        (DenseUnavailable(POISON), REBUILD_REQUIRED),
        (RuntimeError(POISON), OPERATION_FAILED),
    ],
)
@pytest.mark.parametrize("path", ["/api/ask", "/api/search"])
def test_a_query_failure_reaches_the_client_as_one_closed_code(
    web, monkeypatch, caplog, error, failure, path
):
    monkeypatch.setattr(ask_service, "ask", raises(error))
    monkeypatch.setattr(ask_service, "search", raises(error))
    with caplog.at_level(logging.INFO):
        response = web.client.post(path, json={"question": QUESTION}, headers=web.reader_headers)
    assert response.status_code == failure.http_status
    assert response.json() == {"error": failure.message, "code": failure.code}
    say_nothing_private(response.text, str(dict(response.headers)), caplog.text)


@pytest.mark.parametrize(
    "error,failure",
    [
        (OllamaError(POISON), RETRIEVAL_UNAVAILABLE),
        (DenseUnavailable(POISON), REBUILD_REQUIRED),
        (RuntimeError(POISON), OPERATION_FAILED),
    ],
)
def test_the_html_ask_form_shows_the_same_closed_code(web, monkeypatch, caplog, error, failure):
    monkeypatch.setattr(ask_service, "ask", raises(error))
    with caplog.at_level(logging.INFO):
        response = web.client.post(
            "/ask", data={"question": QUESTION}, headers={**web.reader_headers, "HX-Request": "true"}
        )
    # htmx ignores a 500 body, so the fragment itself is the error and the status stays 200.
    assert response.status_code == 200
    assert "callout bad" in response.text
    assert failure.message in response.text and failure.code in response.text
    say_nothing_private(response.text, caplog.text)


def test_a_failure_outside_a_route_handler_is_mapped_by_the_app(web, monkeypatch):
    """`web/app.py` maps a known failure that no route caught, without a 502."""
    source_id = managed_source(web)
    monkeypatch.setattr(pipeline, "reindex", raises(OllamaError(POISON)))
    response = web.client.post(f"/api/sources/{source_id}/reindex", headers=web.reader_headers)
    assert response.status_code == RETRIEVAL_UNAVAILABLE.http_status
    assert response.json() == {
        "error": RETRIEVAL_UNAVAILABLE.message,
        "code": RETRIEVAL_UNAVAILABLE.code,
    }
    say_nothing_private(response.text)


def test_a_managed_operation_without_an_actor_reads_as_the_permission_response(web, monkeypatch):
    source_id = managed_source(web)
    monkeypatch.setattr(pipeline, "reindex", raises(ManagedActorRequired(POISON)))
    response = web.client.post(f"/api/sources/{source_id}/reindex", headers=web.reader_headers)
    assert response.status_code == 409
    assert response.json() == PERMISSION_RESPONSE
    say_nothing_private(response.text)


def test_a_delete_retry_on_an_unavailable_source_says_only_that_it_is_missing(web, monkeypatch):
    """A reader's own retry must not disclose whether a tombstoned source exists."""
    source_id = managed_source(web)
    monkeypatch.setattr(pipeline, "delete_source", raises(AuthorizationChanged(POISON)))
    response = web.client.delete(f"/api/sources/{source_id}", headers=web.reader_headers)
    assert response.status_code == 404
    assert response.json() == {"detail": "no such source"}
    say_nothing_private(response.text)


def test_the_permission_answer_carries_its_code_and_none_of_the_exception(web, monkeypatch, caplog):
    """Every JSON answer has a code, and a denial's own sentence is never the raised one."""
    source_id = managed_source(web)
    monkeypatch.setattr(pipeline, "reindex", raises(AuthorizationChanged(POISON)))
    with caplog.at_level(logging.INFO):
        response = web.client.post(f"/api/sources/{source_id}/reindex", headers=web.reader_headers)
    assert response.status_code == 409
    assert response.json() == PERMISSION_RESPONSE
    say_nothing_private(response.text, str(dict(response.headers)), caplog.text)


def test_legacy_validation_routes_keep_their_own_messages(web):
    empty = web.client.post("/api/sources/text", json={"name": "N", "text": ""}, headers=web.reader_headers)
    assert empty.status_code == 422  # the body model's own bound, unchanged
    settings = web.client.put("/api/settings", json={"damping": 9}, headers=web.admin_headers)
    assert settings.status_code == 400 and "damping" in settings.json()["detail"]
    repo = web.client.post("/api/sources/repo", json={"url": "not a url"}, headers=web.reader_headers)
    assert repo.status_code == 400 and "does not look like a git URL" in repo.json()["error"]


def test_a_background_managed_failure_never_reaches_any_surface(web, monkeypatch, caplog):
    """An unknown build failure carrying every private thing stays out of every response."""
    from hippo.ingest import managed_activation

    monkeypatch.setattr(managed_activation, "run_managed_build", raises(RuntimeError(POISON)))
    with caplog.at_level(logging.INFO):
        response = web.client.post(
            "/api/sources/text", json={"name": "Notes", "text": FIRST_TEXT}, headers=web.reader_headers
        )
        source_id = response.json()["source_id"]
        wait(web.ctx)
        surfaces = [
            web.client.get("/api/sources", headers=web.reader_headers),
            web.client.get(f"/api/sources/{source_id}", headers=web.reader_headers),
            web.client.get("/", headers=web.reader_headers),
            web.client.get(f"/sources/{source_id}", headers=web.reader_headers),
            web.client.get("/api/status", headers=web.reader_headers),
        ]
    row = web.store.get_source(source_id)
    say_nothing_private(
        *[page.text for page in surfaces],
        *[str(dict(page.headers)) for page in surfaces],
        caplog.text,
        str(row),
    )


# --------------------------------------------------------- one held owner


OWNER_ROUTES = {
    "library": ("/", "reader"),
    "sources_partial": ("/partials/sources", "reader"),
    "source_page": ("/sources/{source_id}", "reader"),
    "source_status": ("/partials/sources/{source_id}/status", "reader"),
    "list_sources": ("/api/sources", "reader"),
    "get_source": ("/api/sources/{source_id}", "reader"),
    "me": ("/api/me", "reader"),
    "account": ("/account", "reader"),
    "ask_page": ("/ask", "reader"),
    "users_page": ("/users", "admin"),
    "list_users": ("/api/users", "admin"),
    "list_roles": ("/api/roles", "admin"),
}


def acquisitions(web, monkeypatch, *, closed: bool = False):
    """Every graph one response acquires, and optionally when each was released."""
    seen: list = []
    released: list = []
    original = web.ctx.graph_for

    def acquire(*args, **kwargs):
        graph = original(*args, **kwargs)
        seen.append(graph)
        release = getattr(graph, "close_snapshot", lambda: None)

        def record():
            released.append(graph)
            release()

        graph.close_snapshot = record
        return graph

    monkeypatch.setattr(web.ctx, "graph_for", acquire)
    return (seen, released) if closed else seen


def fetch(web, route: str, source_id: str):
    path, who = OWNER_ROUTES[route]
    headers = web.reader_headers if who == "reader" else web.admin_headers
    return web.client.get(path.format(source_id=source_id), headers=headers)


@pytest.mark.parametrize("route", sorted(OWNER_ROUTES))
def test_each_route_acquires_exactly_one_graph_for_its_response(web, monkeypatch, route):
    source_id = managed_source(web)
    seen = acquisitions(web, monkeypatch)
    response = fetch(web, route, source_id)
    # A polled partial answers STOP_POLLING once its source has settled; both are a response.
    assert response.status_code in (200, STOP_POLLING), response.text
    assert len(seen) == 1, f"{route} acquired {len(seen)} graphs"
    assert not [r for r in web.store._knowledge_rows("SnapshotReference") if r.released_at is None]


REVOKING_ROUTES = sorted(set(OWNER_ROUTES) - {"ask_page"})


@pytest.mark.parametrize("route", REVOKING_ROUTES)
def test_revoking_between_the_dto_and_the_response_is_the_existing_409(web, monkeypatch, route):
    source_id = managed_source(web)
    from hippo.web.routes import sources as source_routes

    real = source_routes.source_view

    def revoked(ctx, access, *, session=None):
        view = real(ctx, access, session=session)
        ctx.store._bump_authorization_epoch()
        return view

    monkeypatch.setattr(source_routes, "source_view", revoked)
    monkeypatch.setattr(web_auth, "source_view", revoked)
    from hippo.web.routes import users as user_routes

    monkeypatch.setattr(user_routes, "source_view", revoked)
    response = fetch(web, route, source_id)
    assert response.status_code == 409, f"{route} answered {response.status_code}"
    assert response.json() == PERMISSION_RESPONSE


def test_bulk_reindex_holds_one_owner_across_the_pipeline_call(web, monkeypatch):
    """The route used to validate a view it had released, then acquire a second one.

    The corpus is mixed, which is the case the plan cares about: one managed source whose
    refresh needs the caller's actor, and one legacy source that is prepared and re-indexed
    the old way. Both lanes run inside the one held owner.
    """
    managed_source(web)
    web.client.post("/api/sources/sample", headers=web.reader_headers)
    wait(web.ctx)
    seen, closed = acquisitions(web, monkeypatch, closed=True)
    during: list[tuple[int, int]] = []
    real = pipeline.reindex_all

    def watched(ctx, *args, **kwargs):
        during.append((len(seen), len(closed)))
        return real(ctx, *args, **kwargs)

    monkeypatch.setattr(pipeline, "reindex_all", watched)
    response = web.client.post("/api/sources/reindex-all", headers=web.admin_headers)
    assert response.status_code == 200 and response.json() == {"accepted": True}
    # One acquisition, still open while the pipeline ran, released exactly once afterwards.
    assert during == [(1, 0)]
    assert len(seen) == 1 and len(closed) == 1
    wait(web.ctx)


# ------------------------------------- 4e: a bulk that started nothing says so


def test_a_bulk_whose_managed_preflight_refuses_answers_a_closed_refusal_code(web, monkeypatch):
    """`{"accepted": true}` has to keep meaning that something was accepted.

    A refused preflight clears nothing and starts nothing, and the only trace used to be a
    local log line: an operator was told their bulk was accepted and had to read the server
    log to find out it was not. The refusal carries no source id and no count, so the body
    names the condition and nothing about the inventory.
    """
    from hippo.knowledge.access import AuthorizationChanged as Changed

    source_id = managed_source(web)
    before = web.store.get_source(source_id)["active_generation_id"]
    started = spy(monkeypatch, "start_indexing")
    # The real refusal, through the real `_preflight_managed` and the real route: the
    # authority this actor would need is gone. Nothing about `reindex_all` is patched.
    monkeypatch.setattr(pipeline, "capture_build_authority", raises(Changed("gone")))

    response = web.client.post("/api/sources/reindex-all", headers=web.admin_headers)

    assert response.status_code == 409, response.text
    assert response.json() == {"error": "Bulk reindex refused", "code": "bulk_refused"}
    wait(web.ctx)
    assert started == [], "a refused preflight must start nothing"
    assert web.store.get_source(source_id)["active_generation_id"] == before


def test_a_bulk_over_a_managed_inventory_with_no_actor_is_the_generic_permission_answer(web, monkeypatch):
    """A managed operation an identity may not perform is a permission answer, not a report."""

    def refuse(ctx, **kwargs):
        raise ManagedActorRequired("A managed source cannot be rebuilt without a build actor")

    monkeypatch.setattr(pipeline, "reindex_all", refuse)
    response = web.client.post("/api/sources/reindex-all", headers=web.admin_headers)
    assert response.status_code == 409, response.text
    assert response.json() == {
        "error": "Permissions changed; repeat the query",
        "code": "authorization_changed",
    }


# ------------- 4e addendum (4b-i review F3, F5, probes 5 and 6): every body carries its code


def test_every_json_failure_body_the_source_routes_answer_carries_its_code(web, monkeypatch):
    """`remote.py` branches on `code` first: an uncoded body loses its own sentence.

    The remote client prints `code: message` when both are present, a 4xx `detail` when it
    is, and the fixed `operation_failed` sentence for anything else. A 413 that says which
    knob to raise, with no `code` and no `detail`, therefore reaches the user as
    "Operation failed; inspect local logs by operation ID (HTTP 413)" -- the actionable
    half discarded because the server never classified it.
    """
    bodies = []

    # 1-2: the closed input validators the plan's `invalid_source` row names.
    over = "x" * 40
    monkeypatch.setattr(pipeline, "max_upload_bytes", lambda ctx: 4)
    bodies.append(
        (
            413,
            web.client.post(
                "/api/sources/upload",
                files={"file": ("big.md", over.encode(), "text/markdown")},
                headers=web.reader_headers,
            ),
        )
    )
    monkeypatch.undo()
    bodies.append(
        (
            400,
            web.client.post(
                "/api/sources/upload",
                files={"file": ("photo.png", b"\x89PNG\x00\x00", "image/png")},
                headers=web.reader_headers,
            ),
        )
    )
    # 3-4: the two legacy validators the plan protects; they keep their message and gain a code.
    bodies.append(
        (
            400,
            web.client.post(
                "/api/sources/text", json={"name": "N", "text": "   "}, headers=web.reader_headers
            ),
        )
    )
    bodies.append(
        (
            400,
            web.client.post("/api/sources/repo", json={"url": "not a url"}, headers=web.reader_headers),
        )
    )
    for status, response in bodies:
        assert response.status_code == status, response.text
        body = response.json()
        assert body["code"] == "invalid_source", body
        assert body["error"], body


@pytest.mark.parametrize(
    "route,method",
    [
        ("/api/sources/reindex-all", "post"),
        ("/api/sources/{id}", "delete"),
        ("/api/sources/{id}/reindex", "post"),
    ],
    ids=["bulk", "delete", "reindex"],
)
def test_the_three_indexing_preconditions_answer_a_coded_409(web, monkeypatch, route, method):
    """`Busy` is a bounded sentence with no code, so a client cannot branch on "try later".

    A legacy source, because a managed delete has no `Busy` precondition by design: it
    sweeps nothing, so waiting for an unrelated index job would only keep a source readable
    that its owner asked to withdraw (Task 3b decision 1).
    """
    created = web.client.post("/api/sources/sample", headers=web.reader_headers)
    assert created.status_code == 200, created.text
    source_id = created.json()["source_id"]
    wait(web.ctx)
    monkeypatch.setattr(pipeline, "_refuse_if_indexing", raises(pipeline.Busy("something else is indexing")))
    call = getattr(web.client, method)
    response = call(route.format(id=source_id), headers=web.admin_headers)
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "indexing_busy" and "indexing" in body["error"]


def test_an_ingress_route_reports_a_managed_dispatch_error_through_the_closed_table(web, monkeypatch):
    """`ManagedDispatchError` is a `ValueError`, so a broad catch would blame the caller.

    Latent today -- nothing on these two routes can raise it synchronously -- but the
    closed handlers have to keep ownership if it ever becomes reachable, and the rule is
    the same exact-type rule the 4xx catches elsewhere use.
    """
    from hippo.ingest.managed_activation import ManagedIngressError

    monkeypatch.setattr(pipeline, "add_text", raises(ManagedIngressError(POISON)))
    response = web.client.post(
        "/api/sources/text", json={"name": "N", "text": FIRST_TEXT}, headers=web.reader_headers
    )
    assert response.status_code == 500, response.text
    assert response.json() == {
        "error": "Operation failed; inspect local logs by operation ID",
        "code": "operation_failed",
    }
    say_nothing_private(response.text)


def test_an_actorless_delete_and_bulk_over_a_managed_inventory_answer_the_same_coded_409(web, monkeypatch):
    """Promoted from the 4b-i review's probe 5: end to end, not through a patched pipeline."""
    source_id = managed_source(web)
    from hippo.web.routes import sources as source_routes

    # The route imports the helper into its own namespace, so that is where it is replaced.
    monkeypatch.setattr(source_routes, "build_actor_of", lambda principal: None)
    deleted = web.client.delete(f"/api/sources/{source_id}", headers=web.admin_headers)
    bulk = web.client.post("/api/sources/reindex-all", headers=web.admin_headers)
    for response in (deleted, bulk):
        assert response.status_code == 409, response.text
        assert response.json() == {
            "error": "Permissions changed; repeat the query",
            "code": "authorization_changed",
        }
    # Nothing was suppressed and nothing was rebuilt.
    row = web.store.get_source(source_id)
    assert (row["status"], row["stage"]) != ("deleted", "tombstoned")


def test_the_index_job_closure_captures_nothing_request_scoped(web):
    """Promoted from the 4b-i review's probe 6: what a background job may hold.

    A closure that captured a `Request`, a cookie or a request-scoped token would outlive
    the request that made it and rebuild as whoever happened to be signed in.
    """
    submitted = []
    real = web.ctx.jobs.start

    def capture(key, fn, *args, **kwargs):
        submitted.append(fn)
        return real(key, fn, *args, **kwargs)

    web.ctx.jobs.start = capture
    try:
        response = web.client.post(
            "/api/sources/text", json={"name": "Notes", "text": FIRST_TEXT}, headers=web.reader_headers
        )
        assert response.status_code == 200, response.text
        wait(web.ctx)
    finally:
        web.ctx.jobs.start = real
    (job,) = submitted
    assert sorted(job.__code__.co_freevars) == ["actor", "ctx", "operation", "source_id"]
    captured = dict(
        zip(job.__code__.co_freevars, [cell.cell_contents for cell in job.__closure__], strict=True)
    )
    assert type(captured["actor"]).__name__ in ("BuildActor", "NoneType")
    assert isinstance(captured["source_id"], str) and isinstance(captured["operation"], str)
