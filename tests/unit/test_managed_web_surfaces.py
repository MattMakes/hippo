"""The web half of PA6: one structural owner per response, dense only where a model runs.

`test_managed_route_activation.py` covers the `query_session` and `ask.py` half.
This file covers the surfaces activation part 4b-ii owns: the analyze routes,
graph browse and light-up, the code endpoints, the render helper and `status`.

Three contracts are under test.

1. Every response is built from one acquisition of one structural owner, released
   exactly once, and the two model paths among these surfaces -- `POST
   /api/graph/light-up` and `POST /api/simulate` -- reach their model only through
   `retrieval_session` over that same owner. Nothing here preflights a graph,
   closes it and reacquires.
2. The graph, source, status and code surfaces answer while `/api/show`,
   `/api/embed` and chat are blocked, because none of them needs a model. The
   model paths answer with the stable public code and none of the provider's own
   words.
3. A managed Source row presents the failure its build lane already classified,
   read back through `public_failure_for_code`, never the text stored on the row.

The GET analyze pages are deliberately *not* dense owners: they render a cached or
stored trace and call no model, so dispatching them would make every page view on a
verified corpus resolve an embedding profile. `test_the_graph_source_status_and_code_surfaces_answer_with_the_model_blocked`
is the arbiter of that decision rather than a comment.
"""

from contextlib import contextmanager

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from hippo.access import EVERYTHING
from hippo.hipporag.indexer import Chunk, index_source
from hippo.ingest.managed_activation import record_build_failure
from hippo.knowledge.public_errors import public_failure_for_code
from hippo.knowledge.query_access import query_session
from hippo.ollama import OllamaError
from hippo.status import source_view
from hippo.web.app import create_app
from hippo.web.routes import analyze as analyze_routes
from hippo.web.routes import graph as graph_routes
from tests.fakes.fake_ollama import DIM
from tests.unit.test_dense_session import verified
from tests.unit.test_managed_source_inventory import empty_published
from tests.unit.test_structural_loading import published, shared_pair, unembedded_code

QUESTION = "Who designed the Orion arm?"

# Everything a leaked exception could carry, in one string.
POISON = (
    "token=sk-live-DEADBEEF /Users/someone/data/private/notes.md "
    '\'Acme Robotics is headquartered in Boulder.\' {"model":"embed:latest"}'
)
# The configured model's *name* is the operator's own setting and the status health card
# reports it on purpose, so only the provider's own words are secrets on every surface.
SECRETS = ("sk-live-DEADBEEF", "/Users/someone", "Acme Robotics")
MODEL_BODY = '{"model":"embed:latest"}'

# The surfaces that must keep working with no model at all. `/graph` and `/analyze`
# render a page, so they also exercise `render.render` and the status header.
GRAPH_ONLY_URLS = (
    "/graph",
    "/api/graph/full",
    "/api/code/symbols?q=orion",
    "/api/status",
)


# --------------------------------------------------------------------- watching


class Watch:
    """One record of what a single request did to the session machinery."""

    def __init__(self):
        self.acquired = []
        self.closed = []
        self.heartbeats = []
        self.dispatched = []

    def once(self, heartbeats=1):
        """One acquisition, one finalizer, and one lease heartbeat per pinned snapshot."""
        assert len(self.acquired) == 1, f"expected one acquisition, saw {len(self.acquired)}"
        assert self.closed == self.acquired, "the acquired owner was not released exactly once"
        assert len(self.heartbeats) == heartbeats, (
            f"expected {heartbeats} heartbeat(s), saw {len(self.heartbeats)}"
        )


def watch(ctx, monkeypatch, *modules) -> Watch:
    """Count acquisitions, heartbeats, finalizers and the dense mode each surface dispatched.

    Each route module is patched by name: the dispatcher is imported into the module,
    so patching `hippo.knowledge.dense_session.retrieval_session` would not be seen.
    `getattr` fails loudly until the module actually imports it, which is the assertion.
    """
    from hippo.knowledge.lease_heartbeat import LeaseHeartbeat

    record = Watch()
    acquire = ctx.graph_for

    def graph_for(*args, **kwargs):
        graph = acquire(*args, **kwargs)
        record.acquired.append(graph)
        close = getattr(graph, "close_snapshot", lambda: None)

        def release():
            record.closed.append(graph)
            close()

        graph.close_snapshot = release
        return graph

    monkeypatch.setattr(ctx, "graph_for", graph_for)

    start = LeaseHeartbeat.start

    def counted(self):
        record.heartbeats.append(self)
        return start(self)

    monkeypatch.setattr(LeaseHeartbeat, "start", counted)

    for module in modules:
        dispatch = module.retrieval_session

        @contextmanager
        def observed(*args, _dispatch=dispatch, **kwargs):
            with _dispatch(*args, **kwargs) as session:
                record.dispatched.append(session.graph.dense_capability.mode)
                yield session

        monkeypatch.setattr(module, "retrieval_session", observed)
    return record


class Offline:
    """A model client that fails on any attribute access at all."""

    def __getattribute__(self, name):
        pytest.fail(f"a surface that needs no model reached it through {name}")


@contextmanager
def offline(ctx):
    """No model at all, for exactly one request.

    `web/app.py:97` pings the model on startup and `status._health` pings it for every
    page header, both legitimately, so the sentinel is installed after the app is up and
    removed before it shuts down. Only JSON surfaces that render no header can use it.
    """
    real = ctx.ollama
    ctx.ollama = Offline()
    try:
        yield
    finally:
        ctx.ollama = real


def internal_request(ctx):
    """A request carrying the internal audience, for the verified-evidence cases.

    `tests/unit/test_staged_prose_writer.setup` is the only fixture that builds verified
    evidence, and it stamps its `AccessPolicy` `legacy_unknown`, which
    `knowledge/access.py:370` refuses for every audience except the internal one -- by
    design, since an unverified provenance origin is not authorization evidence. So the
    verified lane reaches these routes as a direct call rather than over HTTP. The
    transport itself is covered by the tag-compatible, legacy, empty and offline cases,
    all of which a signed-in reader can prove.
    """
    from types import SimpleNamespace

    from hippo.access import ALL_CAPABILITIES, DEFAULT_ROLES, Principal

    role = {**DEFAULT_ROLES[0], "capabilities": sorted(ALL_CAPABILITIES)}
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)),
        state=SimpleNamespace(principal=Principal(user=None, role=role, access=EVERYTHING)),
    )


def body_of(response):
    """The JSON a route returned, whether it answered with a dict or a `JSONResponse`."""
    import json

    return json.loads(response.body) if hasattr(response, "body") else response


def blocked(ctx, monkeypatch, server):
    """Block `/api/show`, `/api/embed` and chat; leave `/api/tags` so health still answers."""

    def refuse(path, body):
        if path in ("/api/show", "/api/embed"):
            raise OllamaError(POISON)
        return None

    def refuse_chat(*args, **kwargs):
        raise OllamaError(POISON)

    server.hook = refuse
    monkeypatch.setattr(ctx.ollama, "chat_json", refuse_chat)
    monkeypatch.setattr(ctx.ollama, "chat_text", refuse_chat)


def reader(ctx) -> dict[str, str]:
    """Sign a real reader in.

    Managed evidence needs an identity with a workspace membership behind it. The open
    audience the unauthenticated client gets cannot prove a selected generation, so a
    managed corpus would simply come back empty and every dispatch would read `legacy` --
    correct behaviour, but it would prove nothing about these surfaces.
    """
    ctx.store.ensure_roles()
    user = ctx.store.create_user("web-reader", "secret1", "arch-admin")
    return {"Authorization": "Bearer " + ctx.store.get_user(user)["token"]}


@contextmanager
def web(ctx, headers=None, *, raising=False):
    with TestClient(
        create_app(ctx), base_url="http://localhost", raise_server_exceptions=raising
    ) as connected:
        connected.headers.update(headers or {})
        yield connected


@pytest.fixture
def client(ctx):
    with web(ctx) as connected:
        yield connected


@pytest.fixture
def prose(ctx):
    """One ordinary legacy source, so the graph surfaces have something to draw."""
    ctx.store.ensure_roles()
    source = ctx.store.create_source("text", "Public guide")
    index_source(
        ctx.store,
        ctx.ollama,
        source,
        [Chunk(0, "Orion", "The Orion arm was designed by Mira Chen at Aster Labs.")],
    )
    return source


# ------------------------------------------------------------- one owner, dispatched


def test_light_up_over_verified_managed_evidence_dispatches_verified_dense_once(ctx, tmp_path, monkeypatch):
    _, server = verified(ctx, tmp_path)
    # The metadata server answers embeddings only; the fact filter is a chat call.
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *args, **kwargs: {"triples": []})
    record = watch(ctx, monkeypatch, graph_routes)
    payload = graph_routes.light_up(internal_request(ctx), graph_routes.LightUpBody(question=QUESTION))
    record.once()
    assert record.dispatched == ["verified"]
    assert body_of(payload)["question"] == QUESTION
    # The question went through the profiled adapter, not the raw client.
    assert any(call["input"] for call in server.embeds())


def test_light_up_over_tag_compatible_legacy_dispatches_tag_compatible_once(ctx, monkeypatch):
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    headers = reader(ctx)
    record = watch(ctx, monkeypatch, graph_routes)
    with web(ctx, headers) as client:
        response = client.post("/api/graph/light-up", json={"question": QUESTION})
    assert response.status_code == 200, response.text
    record.once()
    assert record.dispatched == ["tag_compatible"]


def test_simulate_dispatches_dense_over_the_one_owner_the_route_holds(ctx, monkeypatch):
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    headers = reader(ctx)
    record = watch(ctx, monkeypatch, analyze_routes)
    with web(ctx, headers) as client:
        response = client.post("/api/simulate", json={"question": QUESTION, "overrides": {}})
    assert response.status_code == 200, response.text
    record.once()
    assert record.dispatched == ["tag_compatible"]


@pytest.mark.parametrize("enrich", [unembedded_code, shared_pair], ids=["code", "relation"])
def test_code_only_and_relation_only_support_do_not_change_light_up_dispatch(ctx, monkeypatch, enrich):
    published(ctx.store, "support", profile=ctx.ollama.embed_model, dimension=2, enrich=enrich)
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *a, **k: np.array([1.0, 0.0], dtype=np.float32))
    headers = reader(ctx)
    record = watch(ctx, monkeypatch, graph_routes)
    with web(ctx, headers) as client:
        response = client.post("/api/graph/light-up", json={"question": QUESTION})
    assert response.status_code == 200, response.text
    record.once()
    assert record.dispatched == ["tag_compatible"]


def test_an_empty_authorized_corpus_lights_up_without_one_model_call(ctx, monkeypatch):
    empty_published(ctx.store, "empty", profile=ctx.ollama.embed_model)
    headers = reader(ctx)
    record = watch(ctx, monkeypatch, graph_routes)
    with web(ctx, headers) as client, offline(ctx):
        response = client.post("/api/graph/light-up", json={"question": QUESTION})
    assert response.status_code == 200, response.text
    record.once()
    assert record.dispatched == ["legacy"]
    assert response.json()["seeds"] == []


def test_a_purely_legacy_corpus_lights_up_and_pins_no_snapshot(ctx, monkeypatch, prose):
    record = watch(ctx, monkeypatch, graph_routes)
    with web(ctx) as client:
        response = client.post("/api/graph/light-up", json={"question": QUESTION})
    assert response.status_code == 200, response.text
    record.once(heartbeats=0)
    assert record.dispatched == ["tag_compatible"]


# ------------------------------------------------------- failing before model text


def _call(ctx, surface):
    request = internal_request(ctx)
    if surface == "light-up":
        return graph_routes.light_up(request, graph_routes.LightUpBody(question=QUESTION))
    return analyze_routes.simulate(request, analyze_routes.SimulateBody(question=QUESTION))


@pytest.mark.parametrize("surface", ["light-up", "simulate"])
def test_a_mixed_profile_corpus_denies_before_any_model_text(ctx, tmp_path, surface):
    _, server = verified(ctx, tmp_path)
    published(ctx.store, "tag managed", profile=ctx.ollama.embed_model)
    before = list(server.calls)
    response = _call(ctx, surface)
    assert response.status_code == 409
    assert body_of(response) == {
        "error": "Rebuild compatible sources before retrieval",
        "code": "retrieval_rebuild_required",
    }
    assert server.calls == before, "a mixed corpus must not reach /api/show, /api/embed or /api/chat"


@pytest.mark.parametrize("surface", ["light-up", "simulate"])
def test_a_blocked_model_is_unavailable_and_never_public_provider_text(ctx, tmp_path, monkeypatch, surface):
    _, server = verified(ctx, tmp_path)
    blocked(ctx, monkeypatch, server)
    response = _call(ctx, surface)
    assert response.status_code == 503
    assert body_of(response) == {
        "error": "Retrieval service is unavailable",
        "code": "retrieval_unavailable",
    }
    for secret in (*SECRETS, MODEL_BODY):
        assert secret not in str(response.body)


def test_the_analyze_form_reports_an_unavailable_model_without_its_words(ctx, monkeypatch, prose):
    def refuse(*args, **kwargs):
        raise OllamaError(POISON)

    monkeypatch.setattr(ctx.ollama, "chat_text", refuse)
    monkeypatch.setattr(ctx.ollama, "chat_json", refuse)
    with web(ctx) as client:
        response = client.post("/analyze", data={"question": QUESTION}, follow_redirects=False)
    assert response.status_code == 200, response.text
    assert "Retrieval service is unavailable" in response.text
    for secret in (*SECRETS, MODEL_BODY):
        assert secret not in response.text


def test_a_bare_selection_failure_is_operation_failed_not_a_client_error(ctx, monkeypatch, prose):
    """`canonical_selected_generations` raises a bare `ValueError`; it may not read as a 400."""
    from hippo.hipporag import graph_index

    def refuse(rows):
        raise ValueError("SELECTED GENERATION INTERNALS")

    monkeypatch.setattr(graph_index, "canonical_selected_generations", refuse)
    with web(ctx) as client:
        response = client.post("/api/graph/light-up", json={"question": QUESTION})
    assert response.status_code == 500, response.text
    assert response.json()["code"] == "operation_failed"
    assert "SELECTED GENERATION INTERNALS" not in response.text


def test_a_malformed_client_request_keeps_its_own_bounded_400(ctx, client, prose):
    """The public mapper must not swallow the caller's own mistakes into `operation_failed`."""
    response = client.post(
        "/api/graph/light-up", json={"question": QUESTION, "settings": {"damping": "not a number"}}
    )
    assert response.status_code == 400, response.text
    assert client.get("/api/code/path?a=&b=x").status_code == 400


# -------------------------------------------------------------- offline surfaces


@pytest.mark.parametrize("url", GRAPH_ONLY_URLS)
def test_the_graph_source_status_and_code_surfaces_answer_with_the_model_blocked(
    ctx, tmp_path, monkeypatch, url
):
    _, server = verified(ctx, tmp_path)
    blocked(ctx, monkeypatch, server)
    with web(ctx, reader(ctx)) as client:
        response = client.get(url)
    assert response.status_code == 200, response.text
    for secret in SECRETS:
        assert secret not in response.text


def test_a_node_detail_panel_answers_with_the_model_blocked(ctx, tmp_path, monkeypatch, prose):
    _, server = verified(ctx, tmp_path)
    blocked(ctx, monkeypatch, server)
    with query_session(ctx, EVERYTHING) as session:
        node_id = session.graph.passages[0].id
    with web(ctx, reader(ctx)) as client:
        response = client.get("/api/graph/node/" + node_id)
    assert response.status_code == 200, response.text


def test_the_analyze_page_renders_a_cached_trace_without_resolving_a_profile(ctx, tmp_path, monkeypatch):
    """The GET pages are structural owners, not dense ones.

    This is the arbiter of that classification. The page is reached the way a browser
    reaches it -- POST /analyze, then follow the redirect -- so the cached entry belongs
    to this reader and matches this view by construction. If the GET ever resolves a
    profile, a fresh `/api/show` appears and this fails.
    """
    _, server = verified(ctx, tmp_path)
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *a, **kw: {"triples": []})
    monkeypatch.setattr(ctx.ollama, "chat_text", lambda *a, **kw: "Answer: Mira Chen")
    with web(ctx) as client:
        submitted = client.post("/analyze", data={"question": QUESTION}, follow_redirects=False)
        assert submitted.status_code == 303, submitted.text
        record = watch(ctx, monkeypatch, analyze_routes)
        before = len(server.calls)
        response = client.get(submitted.headers["location"])
        added = server.calls[before:]
    assert response.status_code == 200, response.text
    record.once()
    assert record.dispatched == [], "a cached analysis must not dispatch dense retrieval"
    assert not [path for path, _ in added if path in ("/api/show", "/api/embed")], (
        "reading a stored analysis must resolve no embedding profile"
    )


# --------------------------------------------------- the managed row's own failure


def _row(ctx, source_id, access=EVERYTHING):
    with query_session(ctx, access) as session:
        view = source_view(ctx, access, session=session)
        return next((row for row in view.sources if row["id"] == source_id), None)


def test_a_managed_row_renders_its_stored_failure_code_not_the_stored_message(ctx):
    generation, _ = published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    failure = record_build_failure(
        ctx, source_id=generation.source_id, operation_id="op-1", error=OllamaError(POISON)
    )
    assert failure.code == "model_unavailable"
    row = _row(ctx, generation.source_id)
    assert row["error"] == public_failure_for_code("model_unavailable").message
    assert row["error"] == "Retrieval service is unavailable"
    for secret in SECRETS:
        assert secret not in row["error"]
    assert failure.message not in row["error"], "the build lane's own sentence is not the public one"


def test_a_managed_row_without_a_failure_shows_no_error(ctx):
    generation, _ = published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    assert _row(ctx, generation.source_id)["error"] == ""


def test_an_unmappable_stored_failure_still_never_shows_its_own_text(ctx):
    generation, _ = published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    ctx.store.update_source(generation.source_id, status="failed", error=POISON)
    row = _row(ctx, generation.source_id)
    assert row["error"] == "Operation failed; inspect local logs by operation ID"
    for secret in SECRETS:
        assert secret not in row["error"]


def test_a_legacy_row_keeps_its_own_error_text(ctx, prose):
    ctx.store.update_source(prose, status="failed", error="could not read chapter 4")
    assert _row(ctx, prose)["error"] == "could not read chapter 4"


# ------------------------------------------ revocation between the DTO and the response


def test_revocation_between_the_simulate_dto_and_its_response_discards_the_payload(
    ctx, client, monkeypatch, prose
):
    original = analyze_routes.explain

    def build(*args, **kwargs):
        result = original(*args, **kwargs)
        ctx.store.set_source_access(prose, "arch-admin")
        return result

    monkeypatch.setattr(analyze_routes, "explain", build)
    response = client.post("/api/simulate", json={"question": QUESTION, "overrides": {}})
    assert response.status_code == 409
    assert "Mira" not in response.text


def test_revocation_between_the_analyze_dto_and_its_render_discards_the_page(ctx, client, monkeypatch, prose):
    from hippo import ask as ask_service
    from hippo.web.adhoc import remember_adhoc

    trace = ask_service.search(ctx, QUESTION)
    key = remember_adhoc(trace, {"answer": "Mira Chen", "thought": ""})
    original = analyze_routes.explain

    def build(*args, **kwargs):
        result = original(*args, **kwargs)
        ctx.store.set_source_access(prose, "arch-admin")
        return result

    monkeypatch.setattr(analyze_routes, "explain", build)
    response = client.get("/analyze", params={"key": key})
    assert response.status_code == 409
    assert "Mira" not in response.text


def test_a_code_endpoint_holds_one_owner_through_its_payload(ctx, monkeypatch, code_index):
    context, _ = code_index
    record = watch(context, monkeypatch)
    with web(context) as client:
        response = client.get("/api/code/symbols?q=place")
    assert response.status_code == 200, response.text
    record.once(heartbeats=0)


def test_the_public_failure_response_helper_is_the_one_shape_every_surface_uses(ctx):
    """4b-i renders the same body from `app.py`; the helper is the single definition of it."""
    from hippo.knowledge.public_errors import REBUILD_REQUIRED
    from hippo.web.render import public_failure_response

    response = public_failure_response(REBUILD_REQUIRED)
    assert response.status_code == 409
    assert httpx.Response(200, content=response.body).json() == {
        "error": "Rebuild compatible sources before retrieval",
        "code": "retrieval_rebuild_required",
    }


def test_the_source_dropdown_a_light_up_returns_comes_from_the_same_held_owner(ctx, monkeypatch):
    """`_light_up_response` builds a source view; it must borrow, never acquire a second graph."""
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    headers = reader(ctx)
    record = watch(ctx, monkeypatch, graph_routes)
    with web(ctx, headers) as client:
        assert client.post("/api/graph/light-up", json={"question": QUESTION}).status_code == 200
    record.once()
    assert record.dispatched == ["tag_compatible"]
