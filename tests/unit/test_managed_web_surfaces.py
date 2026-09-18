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
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from markupsafe import escape

from hippo.access import EVERYTHING
from hippo.hipporag.indexer import Chunk, index_source
from hippo.ingest.managed_activation import record_build_failure
from hippo.knowledge import dense_session
from hippo.knowledge.dense import DenseUnavailable
from hippo.knowledge.projection import ProjectionError
from hippo.knowledge.public_errors import public_failure_for_code
from hippo.knowledge.query_access import query_session
from hippo.ollama import OllamaError
from hippo.status import source_view
from hippo.web.app import create_app
from hippo.web.routes import analyze as analyze_routes
from hippo.web.routes import code as code_routes
from hippo.web.routes import graph as graph_routes
from tests.fakes.fake_ollama import DIM, embed_text
from tests.unit.test_converting_source_serving import MANAGED_TEXT, stage
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


def watch(ctx, monkeypatch) -> Watch:
    """Count acquisitions, heartbeats, finalizers and the dense mode each surface dispatched.

    One patch point for every surface, the same seam
    `test_managed_route_activation.watch` uses. The two route modules used to import the
    dispatcher by name, so each needed a patch of its own; they now reach it through
    `dense_session` at call time exactly as the four promoted library callers do, so
    patching the module attribute observes all six.
    `test_every_dispatching_surface_reaches_the_rule_through_the_module` is what keeps a
    future direct import from going unseen here.
    """
    from hippo.knowledge import dense_session as dense_session_module
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

    dispatch = dense_session_module.retrieval_session

    @contextmanager
    def observed(*args, **kwargs):
        with dispatch(*args, **kwargs) as session:
            # A pass-through is not a dispatch: `retrieval_session` hands an already routed
            # session straight back, and the empty-corpus surfaces below re-enter over the
            # owner the route already dispatched. Counting that would read as a second
            # route chosen for the same owner. Same rule as `test_managed_route_activation`.
            if session is not kwargs.get("session"):
                record.dispatched.append(session.graph.dense_capability.mode)
            yield session

    monkeypatch.setattr(dense_session_module, "retrieval_session", observed)
    return record


def test_every_dispatching_surface_reaches_the_rule_through_the_module():
    """The two web surfaces look the dispatcher up the way the four promoted callers do.

    `watch` above patches one attribute on `dense_session`. That observes a caller only
    while the caller resolves the name at call time; a module that did
    `from ...knowledge.dense_session import retrieval_session` would bind it at import and
    dispatch unseen, which is the per-module patch point this file used to carry. Pinned as
    an absence, so re-introducing the direct import fails here rather than silently
    weakening every count below.
    """
    for module in (graph_routes, analyze_routes):
        assert not hasattr(module, "retrieval_session"), module.__name__
        assert module.dense_session is dense_session


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
    record = watch(ctx, monkeypatch)
    payload = graph_routes.light_up(internal_request(ctx), graph_routes.LightUpBody(question=QUESTION))
    record.once()
    assert record.dispatched == ["verified"]
    assert body_of(payload)["question"] == QUESTION
    # The question went through the profiled adapter, not the raw client.
    assert any(call["input"] for call in server.embeds())


def test_light_up_over_tag_compatible_legacy_dispatches_tag_compatible_once(ctx, monkeypatch):
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    headers = reader(ctx)
    record = watch(ctx, monkeypatch)
    with web(ctx, headers) as client:
        response = client.post("/api/graph/light-up", json={"question": QUESTION})
    assert response.status_code == 200, response.text
    record.once()
    assert record.dispatched == ["tag_compatible"]


def test_simulate_dispatches_dense_over_the_one_owner_the_route_holds(ctx, monkeypatch):
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    headers = reader(ctx)
    record = watch(ctx, monkeypatch)
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
    record = watch(ctx, monkeypatch)
    with web(ctx, headers) as client:
        response = client.post("/api/graph/light-up", json={"question": QUESTION})
    assert response.status_code == 200, response.text
    record.once()
    assert record.dispatched == ["tag_compatible"]


# The two model surfaces and what an empty answer from each still carries. Both are
# parametrized because an empty authorized corpus is the one composition that dispatches
# `legacy`, which is not one of the routed modes `retrieval_session` passes through: the
# route hands `run_simulation` the owner it already dispatched and the dispatch rule
# re-enters over it. The re-entry must borrow -- one acquisition, one release, and still
# no model call.
#
# `simulate` expects the re-entry as a second `legacy` reading, and that is the whole
# point: `run_simulation` calls the rule again over the route's own session, and because
# `legacy` is not a routed mode the rule cannot hand it straight back -- it re-activates
# over the *same* owner instead. One patch point sees both calls, so the list says so.
# `record.once()` beside it is what proves the re-entry borrowed rather than acquired.
EMPTY_SURFACES = {
    "light-up": ("/api/graph/light-up", ["legacy"], lambda payload: payload["seeds"]),
    "simulate": ("/api/simulate", ["legacy", "legacy"], lambda payload: payload["trace"]["passages"]),
}


@pytest.mark.parametrize("surface", sorted(EMPTY_SURFACES))
def test_an_empty_authorized_corpus_answers_without_one_model_call(ctx, monkeypatch, surface):
    url, dispatched, emptied = EMPTY_SURFACES[surface]
    empty_published(ctx.store, "empty", profile=ctx.ollama.embed_model)
    headers = reader(ctx)
    record = watch(ctx, monkeypatch)
    with web(ctx, headers) as client, offline(ctx):
        response = client.post(url, json={"question": QUESTION, "overrides": {}})
    assert response.status_code == 200, response.text
    record.once()
    assert record.dispatched == dispatched
    assert emptied(response.json()) == []


def test_a_purely_legacy_corpus_lights_up_and_pins_no_snapshot(ctx, monkeypatch, prose):
    record = watch(ctx, monkeypatch)
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
    # The page carries the mapper's status as well as its sentence: a failure rendered at
    # 200 tells a client, a cache and a crawler that the question was answered.
    assert response.status_code == 503, response.text
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


# ------------------------------------------ a view that cannot be composed at all

PRIVATE = "SELECTED GENERATION INTERNALS"

# The two structural-loading failures `ctx.graph_for` raises, with the public row each
# maps to. They differ in status on purpose: a surface that answered both at 500 would be
# discarding the mapper's own status rather than carrying it.
UNLOADABLE = {
    "projection": (
        ProjectionError,
        500,
        {"error": "Operation failed; inspect local logs by operation ID", "code": "operation_failed"},
    ),
    "profile": (
        DenseUnavailable,
        409,
        {"error": "Rebuild compatible sources before retrieval", "code": "retrieval_rebuild_required"},
    ),
}

# Every route in these files that composes a view. `light_up` and the `/api/code/*` group
# already mapped theirs; these are the ones that answered `500 text/plain`.
JSON_SURFACES = ("/api/graph/full", "/api/graph/node/passage-0", "/api/code/symbols?q=orion")
PAGE_SURFACES = ("/graph", "/changesets", "/analyze?question=x", "/analyze/result-0")


def unloadable(ctx, monkeypatch, kind):
    """No view composes at all, the way an incoherent generation selection fails.

    `ctx.graph_for` is the single acquisition point every one of these routes reaches
    through `query_session`, so patching it puts the failure exactly where
    `GraphIndex.__post_init__` puts a bare `ValueError` from
    `canonical_selected_generations`: inside the `with`, before any payload exists.
    """

    def refuse(*args, **kwargs):
        raise kind(PRIVATE)

    monkeypatch.setattr(ctx, "graph_for", refuse)


@pytest.mark.parametrize("url", JSON_SURFACES)
@pytest.mark.parametrize("failure", sorted(UNLOADABLE))
def test_a_view_that_cannot_be_composed_is_the_closed_json_body_on_every_json_route(
    ctx, monkeypatch, failure, url
):
    kind, status, body = UNLOADABLE[failure]
    unloadable(ctx, monkeypatch, kind)
    with web(ctx) as client:
        response = client.get(url)
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json"), response.text
    assert response.json() == body
    assert PRIVATE not in response.text


@pytest.mark.parametrize("url", PAGE_SURFACES)
@pytest.mark.parametrize("failure", sorted(UNLOADABLE))
def test_a_view_that_cannot_be_composed_is_the_bounded_sentence_on_every_page(ctx, monkeypatch, failure, url):
    """A page says the mapper's sentence at the mapper's status, never a bare 500."""
    kind, status, body = UNLOADABLE[failure]
    unloadable(ctx, monkeypatch, kind)
    with web(ctx) as client:
        response = client.get(url)
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("text/html"), response.text
    assert body["error"] in response.text
    assert PRIVATE not in response.text


def test_the_analyze_form_answers_the_bounded_sentence_when_no_view_composes(ctx, monkeypatch):
    """POST /analyze maps the failure itself, then `render` must survive its own acquisition.

    The form's `except` renders a page with no session of its own, so `render` opens one
    (`render.py:118`) and meets the same failure a second time. That second site is the
    reason this goes through the form rather than through a GET.
    """
    unloadable(ctx, monkeypatch, ProjectionError)
    with web(ctx) as client:
        response = client.post("/analyze", data={"question": QUESTION}, follow_redirects=False)
    assert response.status_code == 500, response.text
    assert "Operation failed; inspect local logs by operation ID" in response.text
    assert PRIVATE not in response.text


def test_a_code_payload_failure_is_a_public_code_and_not_the_callers_fault(ctx, monkeypatch, code_index):
    """`_answer`'s 400 vocabulary is separated from the public mapper by type, not by timing.

    Every structural failure fires at acquisition today, so `_answer`'s `except ValueError`
    never sees one. A payload builder that touched a lazily composed path would make an
    incoherent view a 400 that blames the request; the separation must not depend on that.
    """
    context, _ = code_index

    def refuse(*args, **kwargs):
        raise ProjectionError(PRIVATE)

    monkeypatch.setattr(code_routes, "symbol_rows", refuse)
    with web(context) as client:
        response = client.get("/api/code/symbols?q=place")
    assert response.status_code == 500, response.text
    assert response.json() == {
        "error": "Operation failed; inspect local logs by operation ID",
        "code": "operation_failed",
    }
    assert PRIVATE not in response.text


def test_an_out_of_range_stored_setting_does_not_blame_the_caller_or_quote_itself(ctx, monkeypatch, prose):
    """Light-up's 400 pre-validation checks the caller's own values, not the operator's.

    `validate_settings` names the value it refused. On the merged dict that value can be a
    *stored* knob the caller never sent, so a 400 would blame the request and print the
    operator's configuration back at it.
    """
    stored = dict(ctx.store.get_settings())
    monkeypatch.setattr(ctx.store, "get_settings", lambda *a, **k: {**stored, "damping": 5.0})
    with web(ctx) as client:
        response = client.post("/api/graph/light-up", json={"question": QUESTION})
    assert response.status_code == 500, response.text
    assert response.json() == {
        "error": "Operation failed; inspect local logs by operation ID",
        "code": "operation_failed",
    }
    assert "damping" not in response.text and "5.0" not in response.text


def test_a_malformed_client_request_keeps_its_own_bounded_400(ctx, client, prose):
    """The public mapper must not swallow the caller's own mistakes into `operation_failed`.

    All three vocabularies meet inside these routes: a bad setting, a bad simulation
    override and a blank required argument are the request's fault and say so, while an
    incoherent view is not and does not.
    """
    response = client.post(
        "/api/graph/light-up", json={"question": QUESTION, "settings": {"damping": "not a number"}}
    )
    assert response.status_code == 400, response.text
    overridden = client.post(
        "/api/simulate", json={"question": QUESTION, "overrides": {"settings": {"damping": 5}}}
    )
    assert overridden.status_code == 400, overridden.text
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
        record = watch(ctx, monkeypatch)
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


def test_a_converting_sources_page_keeps_its_legacy_facts_and_shows_no_staged_row(ctx, client, prose):
    """R21-M7 and CD2: until it publishes, a converting source's page is its legacy page.

    The first staged row sets the `managed` flag, so a page that branched on that flag drew
    the legacy passages with no facts and no entities. The source is in the legacy lane
    (ruling 14), and that lane serves untagged rows only, so the staged passage must not
    appear either: reading every passage of the source would show it.
    """
    legacy = ctx.store.passages_for_source(prose)
    assert len(legacy) == 1 and legacy[0]["triples"] and legacy[0]["entities"]
    staged = stage(ctx.store, prose, profile=ctx.ollama.embed_model, vector=embed_text(MANAGED_TEXT))
    assert ctx.store.get_source(prose)["managed"]

    page = client.get(f"/sources/{prose}")

    assert page.status_code == 200, page.text
    facts = legacy[0]["triples"]
    assert f"{len(facts)} facts" in page.text
    assert all(str(escape(subject)) in page.text for subject, _predicate, _object in facts)
    assert all(str(escape(entity)) in page.text for entity in legacy[0]["entities"])
    assert MANAGED_TEXT not in page.text and staged.passage_id not in page.text


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
    record = watch(ctx, monkeypatch)
    with web(ctx, headers) as client:
        assert client.post("/api/graph/light-up", json={"question": QUESTION}).status_code == 200
    record.once()
    assert record.dispatched == ["tag_compatible"]


# ------------------------------- 4e: a 4xx `detail` comes from an exact validator type


# Every managed, retrieval and ingest failure is a `ValueError` *subclass*, and several of
# them name a path or quote stored text by construction. `RepoError` stands for the whole
# family here: it is a `ValueError` the closed table does not list, so a route that catches
# `ValueError` by isinstance prints it, and a route that catches the exact validator type
# hands it to the mapper.
LEAKY_PATH = "/Users/someone/checkout/.git"


def test_a_code_payload_value_error_subclass_is_mapped_rather_than_printed_as_a_400(
    ctx, monkeypatch, code_index
):
    """`_answer`'s 400 is for the caller's own mistake, which is an exact `ValueError`.

    `test_a_code_payload_failure_is_a_public_code_and_not_the_callers_fault` proves the
    same thing for a subclass the closed table knows. This one uses a subclass it does
    *not* know, which is what separates an exact-type catch from asking the table.
    """
    from hippo.ingest.repos import RepoError

    context, _ = code_index

    def refuse(*args, **kwargs):
        raise RepoError(LEAKY_PATH)

    monkeypatch.setattr(code_routes, "symbol_rows", refuse)
    with web(context) as client:
        response = client.get("/api/code/symbols?q=place")
    assert response.status_code == 500, response.text
    assert response.json() == {
        "error": "Operation failed; inspect local logs by operation ID",
        "code": "operation_failed",
    }
    assert LEAKY_PATH not in response.text


def test_a_blank_required_code_argument_is_still_the_callers_mistake(ctx, code_index):
    """The exact-type catch must not take the 400 vocabulary with it."""
    context, _ = code_index
    with web(context) as client:
        response = client.get("/api/code/blast-radius?symbol=%20")
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "symbol is required"


@pytest.mark.parametrize(
    "kind,status,code",
    [("projection", 500, "operation_failed"), ("read", 400, "invalid_source")],
    ids=["projection", "read"],
)
def test_a_settings_write_that_fails_is_mapped_rather_than_quoted_back_as_a_400(
    ctx, monkeypatch, kind, status, code
):
    """`PUT /api/settings` answers the validator's own message and nothing else's.

    The caller's numbers are refused with the store validator's sentence, which the plan
    protects. Anything the *write* raises is a storage failure carrying whatever it was
    reading, so it belongs to the closed table.
    """
    from hippo.ingest.readers import ReadError

    failure = ProjectionError if kind == "projection" else ReadError

    def refuse(changes):
        raise failure(LEAKY_PATH)

    monkeypatch.setattr(ctx.store, "update_settings", refuse)
    with web(ctx) as client:
        response = client.put("/api/settings", json={"damping": 0.6})
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    assert LEAKY_PATH not in response.text


def test_an_invalid_setting_keeps_the_store_validators_own_sentence(ctx):
    """The one 4xx `detail` the plan protects: the caller's own number, named."""
    with web(ctx) as client:
        response = client.put("/api/settings", json={"damping": 9})
    assert response.status_code == 400, response.text
    assert "damping must be between" in response.json()["detail"]


@pytest.mark.parametrize("route", ["/api/ask", "/api/search"])
def test_a_settings_precheck_failure_that_is_not_the_validator_is_mapped(ctx, monkeypatch, route):
    """`checked_settings` guards the caller's numbers; it may not print a subclass's words."""
    from hippo.web.routes import api as api_routes

    def refuse(changes):
        raise ProjectionError(LEAKY_PATH)

    monkeypatch.setattr(api_routes, "validate_settings", refuse)
    with web(ctx) as client:
        response = client.post(route, json={"question": QUESTION, "settings": {"damping": 0.6}})
    assert response.status_code == 500, response.text
    assert response.json() == {
        "error": "Operation failed; inspect local logs by operation ID",
        "code": "operation_failed",
    }
    assert LEAKY_PATH not in response.text


@pytest.mark.parametrize("route", ["/api/ask", "/api/search"])
def test_a_callers_own_bad_setting_is_still_a_400_naming_it(ctx, route):
    with web(ctx) as client:
        response = client.post(route, json={"question": QUESTION, "settings": {"damping": 9}})
    assert response.status_code == 400, response.text
    assert "damping must be between" in response.json()["detail"]


# ------------- the last two isinstance 4xx catches: starting a run, and light-up's settings


def test_starting_a_run_on_an_unknown_set_is_a_404_that_reads_no_exception(ctx):
    """The status comes from the exception's type, not from a substring of its words.

    This route used to answer `404 if "unknown question set" in str(exc) else 400`, so
    rewording `EvalAccess.require_set`'s sentence would silently have turned the 404 into
    a 400 that blamed the request.
    """
    with web(ctx, reader(ctx)) as client:
        response = client.post("/api/evals/sets/nope/run", json={})
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "no such question set"
    assert "access denied" not in response.text


def test_starting_a_run_that_cannot_be_routed_is_mapped_not_blamed_on_the_request(ctx, monkeypatch):
    """`start_run` opens a session through `require_set`, so activation failures arrive here.

    `ProjectionError`, `DenseSessionUnavailable` and `QuerySnapshotUnavailable` are all
    `ValueError` subclasses. Printing one as a 400 tells the caller their request was
    wrong and reads a sentence this route never wrote.
    """
    from hippo.evals import runner as runner_module

    def refuse(*args, **kwargs):
        raise ProjectionError(LEAKY_PATH)

    monkeypatch.setattr(runner_module, "start_run", refuse)
    with web(ctx, reader(ctx)) as client:
        response = client.post("/api/evals/sets/whatever/run", json={})
    assert response.status_code == 500, response.text
    assert response.json() == {
        "error": "Operation failed; inspect local logs by operation ID",
        "code": "operation_failed",
    }
    assert LEAKY_PATH not in response.text


def test_starting_a_run_with_a_bad_setting_keeps_the_validators_own_sentence(ctx):
    """The exact-type catch must not take the 400 vocabulary with it, here either."""
    with web(ctx, reader(ctx)) as client:
        response = client.post("/api/evals/sets/whatever/run", json={"settings": {"damping": 9}})
    assert response.status_code == 400, response.text
    assert "damping must be between" in response.json()["detail"]


def test_light_up_maps_a_settings_check_that_is_not_the_validators_own_refusal(ctx, monkeypatch):
    """The web layer's last isinstance 4xx catch, closed the same way as the others."""
    from hippo.web.routes import graph as graph_module

    def refuse(changes):
        raise ProjectionError(LEAKY_PATH)

    monkeypatch.setattr(graph_module, "validate_settings", refuse)
    with web(ctx, reader(ctx)) as client:
        response = client.post("/api/graph/light-up", json={"question": QUESTION, "settings": {}})
    assert response.status_code == 500, response.text
    assert response.json()["code"] == "operation_failed"
    assert LEAKY_PATH not in response.text


def test_light_up_still_names_the_knob_the_caller_sent(ctx):
    with web(ctx, reader(ctx)) as client:
        response = client.post("/api/graph/light-up", json={"question": QUESTION, "settings": {"damping": 9}})
    assert response.status_code == 400, response.text
    assert "damping must be between" in response.json()["detail"]


# --------------- PA4d finding 2: the one guard the last unrestricted `ctx.graph()` is for


def test_a_changeset_naming_managed_evidence_is_refused_by_the_unrestricted_read(ctx):
    """`changeset_access.apply` reads the whole native graph for exactly one reason.

    `native_ids = set(self.ctx.graph().node_ids)` is the single remaining `ctx.graph()`
    under `src/hippo`, and it exists to refuse an op whose target is evidence rather than a
    writable legacy node. The 4d review proved the read cannot influence a response or a
    saved record, but nothing made the guard fire: `rg 'Managed evidence requires typed
    changes'` found the string only at its own `raise`, so the read had no observable
    purpose to defend.

    A managed span is exactly the shape the guard is written against. It is in the
    *authorized* graph -- so `_visible_ops` lets the draft save -- and not in the *native*
    one, which is the whole distinction: an audience may see evidence it may not hand-edit.
    The refusal is a fixed sentence naming nothing the caller sent.
    """
    from hippo.knowledge.changeset_access import ChangesetAccess

    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    service = ChangesetAccess(ctx, EVERYTHING)
    with service.read_scope():
        evidence = next(node for node in service.graph.idx_of if node.startswith("span-"))
    assert evidence not in set(ctx.graph().node_ids), "a managed span is not a native node"

    identity = service.save("hand edit", [{"op": "set_node_boost", "entity_id": evidence, "boost": 2.0}])
    version = ctx.store.graph_version()
    with pytest.raises(ValueError) as caught:
        ChangesetAccess(ctx, EVERYTHING).apply(identity)
    assert str(caught.value) == "Managed evidence requires typed changes, not legacy graph edits"
    assert evidence not in str(caught.value)
    # Refused ahead of `changesets.apply`: nothing was written and the draft is still a draft.
    assert ctx.store.graph_version() == version
    assert ctx.store.get_changeset(identity)["status"] == "draft"


# ---------- wrap-up finding 18 + residual C1: the last isinstance catches in the web layer


# Every user, role, account and settings write wraps a store validator that raises the
# *exact* `ValueError` -- "username is taken", "damping must be between 0 and 1" -- which is
# the caller's own field and the sentence they need, and which the plan's transport table
# protects by name. A `ValueError` *subclass* arriving at the same line came from further
# down and carries whatever it was reading. These were the last catches under `src/hippo/web`
# without `render.caller_error` in front of them, so the guard is the same one every other
# 4xx site applies rather than a new rule.
#
# `ProjectionError` stands in for the family: it is a `ValueError` subclass the closed table
# already knows, so the mapped answer is assertable rather than a bare 500.
@pytest.fixture
def ladder(ctx):
    """An arch-admin over the real app, plus one user below them to write to."""
    headers = reader(ctx)
    subject = ctx.store.create_user("subject", "secret1", "local-admin")
    with web(ctx, headers) as client:
        yield SimpleNamespace(client=client, ctx=ctx, subject=subject)


USER_AND_ROLE_WRITES = {
    "create_user": (
        "create_user",
        lambda c, w: c.post(
            "/api/users", json={"username": "neo", "password": "secret1", "role_id": "local-admin"}
        ),
    ),
    "update_user": (
        "update_user",
        lambda c, w: c.patch(f"/api/users/{w.subject}", json={"display_name": "Subject"}),
    ),
    "create_role": ("create_role", lambda c, w: c.post("/api/roles", json={"name": "Scouts", "rank": 5})),
    "update_role": (
        "update_role",
        lambda c, w: c.patch("/api/roles/local-admin", json={"description": "changed"}),
    ),
    "delete_role": ("delete_role", lambda c, w: c.delete("/api/roles/local-assistant")),
}


@pytest.mark.parametrize("case", sorted(USER_AND_ROLE_WRITES))
def test_a_user_or_role_write_that_fails_is_mapped_rather_than_quoted_back_as_a_400(
    ladder, monkeypatch, case
):
    """A store write's own words are not the caller's mistake, on these routes either."""
    method, call = USER_AND_ROLE_WRITES[case]

    def refuse(*args, **kwargs):
        raise ProjectionError(LEAKY_PATH)

    monkeypatch.setattr(ladder.ctx.store, method, refuse)
    response = call(ladder.client, ladder)
    assert LEAKY_PATH not in response.text
    assert response.status_code == 500, response.text
    assert response.json()["code"] == "operation_failed"


def test_the_role_form_still_shows_the_validators_sentence_but_not_a_subclasses(ladder, monkeypatch):
    """The two `getattr(exc, "detail", str(exc))` sites keep exactly three families.

    `RoleBody` is constructed inside the try, so an empty name is a pydantic
    `ValidationError` -- a `ValueError` subclass, but this form's own field rules and the
    only thing that tells the operator which box was wrong. A non-numeric rank is the bare
    `ValueError` from `int()`. Both stay; a subclass raised by the store write does not.
    This is the one place the batch needed more than `caller_error` alone.
    """
    empty_name = ladder.client.post("/roles", data={"name": ""}, follow_redirects=False)
    assert empty_name.status_code == 303, empty_name.text
    assert "error=" in empty_name.headers["location"]

    bad_rank = ladder.client.post("/roles", data={"name": "Scouts", "rank": "high"}, follow_redirects=False)
    assert bad_rank.status_code == 303 and "error=" in bad_rank.headers["location"]

    def refuse(*args, **kwargs):
        raise ProjectionError(LEAKY_PATH)

    monkeypatch.setattr(ladder.ctx.store, "create_role", refuse)
    leaked = ladder.client.post("/roles", data={"name": "Scouts", "rank": "5"}, follow_redirects=False)
    assert LEAKY_PATH not in leaked.text and LEAKY_PATH not in str(leaked.headers)
    assert leaked.status_code == 500, leaked.text


def test_a_password_change_that_fails_is_not_redirected_back_with_its_own_words(ladder, monkeypatch):
    """`auth.py:382` put `str(exc)` straight into the `/account?error=` query string."""

    def refuse(*args, **kwargs):
        raise ProjectionError(LEAKY_PATH)

    monkeypatch.setattr(ladder.ctx.store, "update_user", refuse)
    response = ladder.client.post(
        "/account/password",
        data={"current": "secret1", "new": "secret22", "again": "secret22"},
        follow_redirects=False,
    )
    assert LEAKY_PATH not in response.text and LEAKY_PATH not in str(response.headers)
    assert response.status_code == 500, response.text


def test_a_settings_form_write_that_fails_is_mapped_rather_than_rendered_into_the_page(ctx, monkeypatch):
    """Residual C1: the JSON twin's guard, on the page that shares its store call.

    `pages.py` renders `error=str(exc)` from a bare `except ValueError`, which the plan
    protects *for the validator's sentence* -- the knob the operator just typed and its
    range. A subclass raised by the write is not that sentence, and
    `test_a_settings_write_that_fails_is_mapped_rather_than_quoted_back_as_a_400` already
    guards the exact same shape one route over.
    """

    def refuse(changes):
        raise ProjectionError(LEAKY_PATH)

    monkeypatch.setattr(ctx.store, "update_settings", refuse)
    with web(ctx) as client:
        response = client.post("/settings", data={"damping": "0.6"}, follow_redirects=False)
    assert LEAKY_PATH not in response.text
    assert response.status_code == 500, response.text
    assert response.json()["code"] == "operation_failed"


# ------------------------------------- 4e decision 1's own check, as a test rather than a grep


# Every `str(exc)` under `src/hippo/web`, with the disposition the Task 4 wrap-up review
# gave it (`ai_docs/reports/2026-09-12-pa4-wrapup-review.md`, "4e -- QUALITY", and
# `evidence-cleanup4.md`). Decision 1 asked for a grep that finds only sites something
# protects; a grep cannot say *why* a site is allowed, and it passes the moment a reviewer
# stops running it. The keys are file and source line -- not line numbers, which drift on
# any edit above them -- and the value is how many times that exact line may appear.
#
# Adding an unlisted `str(exc)` fails here, which is the point: the next one has to be
# classified before it ships.
STR_EXC_SITES = {
    # guarded: `render.caller_error` runs first, so only the exact `ValueError` the closed
    # input validators raise is printed. `add_repo`'s fourth copy is guarded by its own
    # exact-`RepoError` test instead (`test_only_the_exact_repo_error_is_printed...`).
    ("routes/sources.py", "return coded_response(str(exc), INVALID_SOURCE, 400)"): 4,
    # unguarded, as it was when it printed `{exc}` unquoted: the repo form's redirect. What
    # `pipeline.add_repo` raises synchronously today is its closed git-URL sentence or one of
    # `CaptureRefused`'s closed sentences; R21-M10 closed the first and percent-encodes both.
    ("routes/sources.py", 'return RedirectResponse(f"/?error={quote(str(exc))}", status_code=303)'): 1,
    ("routes/api.py", "raise HTTPException(400, str(exc)) from exc"): 1,
    ("routes/code.py", "raise HTTPException(400, str(exc)) from exc"): 1,
    # guarded by this cleanup batch: the last two isinstance 4xx catches in the web layer.
    ("routes/evals.py", "raise HTTPException(400, str(exc)) from exc"): 1,
    ("routes/graph.py", "raise HTTPException(400, str(exc)) from exc"): 1,
    # bounded: `Busy` is raised in one place with fixed text, and the plan's transport
    # table keeps the indexing preconditions' own sentence.
    ("routes/sources.py", "return coded_response(str(exc), INDEXING_BUSY, 409)"): 3,
    # intended: the exact `AmbiguousSymbol` / `UnknownSymbol`, whose words are the caller's
    # own symbol and whose candidates are the answer they asked for.
    (
        "routes/code.py",
        'return JSONResponse({"detail": str(exc), "candidates": exc.candidates}, status_code=409)',
    ): 1,
    ("routes/code.py", "raise HTTPException(404, str(exc)) from exc"): 1,
    # protected *and* guarded: the legacy settings form, which the plan's transport table
    # names. `validate_settings`' sentence is what is protected; the PA8 closure batch put
    # `caller_error` in front of the catch, so a subclass no longer reaches the page.
    ("routes/pages.py", "error=str(exc),"): 1,
    # guarded by the PA8 closure batch (wrap-up finding 18 and `evidence-cleanup4.md`'s
    # residual C1): the user, role and account writes. The store validators these wrap
    # raise the plain `ValueError` their own rules raise, which is the caller's own field;
    # a subclass is re-raised to the mapper. The two role forms carry one clause more,
    # because they build their pydantic model inside the `try` and a `ValidationError` is
    # that form's own field rules. `analyze.py`'s two below are still the deferred family.
    ("routes/users.py", "raise HTTPException(400, str(exc)) from exc"): 5,
    ("routes/users.py", 'return _back(getattr(exc, "detail", str(exc)))'): 2,
    ("auth.py", 'return RedirectResponse("/account?error=" + quote(str(exc)), status_code=303)'): 1,
    # bounded today, deferred with the same family: both raise `ChangesetUnavailable`
    # (caught first) or `changesets.validate`'s own sentence.
    ("routes/analyze.py", "raise HTTPException(400, str(exc)) from exc"): 2,
    # prose: the docstring that states the rule the sites above follow.
    ("render.py", "`HTTPException(4xx, str(exc))` prints any of them at the caller. The exact-type test"): 1,
}


def test_every_str_exc_in_the_web_layer_is_one_the_review_classified():
    """4e decision 1's check: nothing prints an exception's own words unaccounted for."""
    import collections
    import pathlib

    import hippo.web

    root = pathlib.Path(hippo.web.__file__).parent
    found: collections.Counter = collections.Counter()
    for path in sorted(root.rglob("*.py")):
        for line in path.read_text().splitlines():
            # A `#` comment prints nothing, and the sites above are commented *about*.
            # A docstring line is prose too, but it is kept and listed, because that is
            # where `render.py` states the rule these sites follow.
            if "str(exc)" in line and not line.strip().startswith("#"):
                found[(path.relative_to(root).as_posix(), line.strip())] += 1

    unlisted = sorted(site for site in found if site not in STR_EXC_SITES)
    assert not unlisted, f"unclassified `str(exc)` site(s): {unlisted}"
    stale = sorted(site for site in STR_EXC_SITES if site not in found)
    assert not stale, f"allow-listed site(s) that no longer exist: {stale}"
    assert dict(found) == STR_EXC_SITES


# --------------------- 4e: an incoherent selection is a mapped failure on every transport


# The real refusal `canonical_selected_generations` raises, driven through the real
# function. `test_a_bare_selection_failure_is_operation_failed_not_a_client_error` above
# patches the function out, so it cannot see the exception's type change; this drives it.
TWO_GENERATIONS_FOR_ONE_SOURCE = (("source-1", "generation-a"), ("source-1", "generation-b"))


def incoherent_selection(ctx, monkeypatch):
    """Acquisition fails the way `GraphIndex.__post_init__` fails on an incoherent selection."""
    from hippo.hipporag import graph_index

    def refuse(*args, **kwargs):
        return graph_index.canonical_selected_generations(TWO_GENERATIONS_FOR_ONE_SOURCE)

    monkeypatch.setattr(ctx, "graph_for", refuse)


def test_an_incoherent_selection_is_a_projection_failure_not_a_bare_value_error(ctx):
    """The type is the fix: a bare `ValueError` is what every transport has to special-case."""
    from hippo.hipporag.graph_index import canonical_selected_generations

    with pytest.raises(ProjectionError):
        canonical_selected_generations(TWO_GENERATIONS_FOR_ONE_SOURCE)
    with pytest.raises(ProjectionError):
        canonical_selected_generations(("not-a-pair",))


def test_an_incoherent_selection_is_the_closed_body_on_a_route_that_holds_no_catch(ctx, monkeypatch):
    """`/api/entities` composes a view and maps nothing of its own (4b-i).

    Before the type changed this answered a code-less 500 from the server itself, which a
    client cannot branch on and a page's JavaScript cannot read.
    """
    incoherent_selection(ctx, monkeypatch)
    with web(ctx) as client:
        response = client.get("/api/entities?q=orion")
    assert response.status_code == 500, response.text
    assert response.json() == {
        "error": "Operation failed; inspect local logs by operation ID",
        "code": "operation_failed",
    }


def test_an_incoherent_selection_keeps_its_mapped_body_on_a_route_that_holds_one(ctx, monkeypatch):
    """`/api/graph/full` already mapped it (4b-ii); the new type must not change that."""
    incoherent_selection(ctx, monkeypatch)
    with web(ctx) as client:
        response = client.get("/api/graph/full")
    assert response.status_code == 500, response.text
    assert response.json()["code"] == "operation_failed"


def test_an_incoherent_selection_reaches_an_mcp_code_tool_as_a_mapped_failure(ctx, monkeypatch):
    """MCP renders an exact `ValueError`'s own words on purpose, so the type is what protects it.

    `tool_failure` passes `type(exc) is ValueError` through verbatim for the closed input
    validators. A bare `ValueError` from the selection therefore reached an MCP client as
    its own internals; a `ProjectionError` is mapped by the closed table instead.
    """
    from mcp.server.mcpserver.exceptions import ToolError

    from hippo import mcp_server

    incoherent_selection(ctx, monkeypatch)
    # Since the Task 4c follow-up the code tools map their own acquisition, so the
    # ProjectionError never leaves the tool: the client sees the closed code only.
    with pytest.raises(ToolError) as raised:
        mcp_server.blast_radius_tool(ctx, "anything")
    assert str(raised.value) == "operation_failed: Operation failed; inspect local logs by operation ID"
    assert "one source twice" not in str(raised.value)


# ----------------------------- 4e: one definition of the settings a query actually runs on


def test_effective_settings_is_the_stored_knobs_under_the_callers_own(ctx):
    """`query_session` and light-up's pre-validation must merge and validate identically.

    Two copies of the same expression are only correct while they stay identical, and
    nothing made them; this is the one definition both now call.
    """
    from hippo.knowledge.query_access import effective_settings

    ctx.store.update_settings({"damping": 0.4})
    assert effective_settings(ctx, None)["damping"] == 0.4
    assert effective_settings(ctx, {"damping": 0.7})["damping"] == 0.7
    # Validated, not merely merged: an out-of-range value is refused here, not at search time.
    with pytest.raises(ValueError):
        effective_settings(ctx, {"damping": 9})


def test_light_up_and_query_session_agree_on_the_effective_settings(ctx, monkeypatch, prose):
    """Light-up's merged-dict pre-validation is the same call `query_session` makes."""
    from hippo.knowledge import query_access
    from hippo.web.routes import graph as graph_module

    assert graph_module.effective_settings is query_access.effective_settings


# ------- 4e addendum (4b-i review F1, F4): a page route answers a page, not a JSON blob


# The page routes 4b-i owns. None of them is under /api, and each one composes a view whose
# failure escapes to the app's own handler rather than to a catch of its own. `/partials/sources`
# is the sharpest: htmx polls it, so a transient failure would replace a fragment of the
# library page with a JSON blob.
OWNED_PAGE_ROUTES = ("/", "/sources/s1", "/account", "/ask", "/users", "/partials/sources")
BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


@pytest.mark.parametrize("url", OWNED_PAGE_ROUTES)
def test_a_browser_gets_a_page_when_a_mapped_failure_escapes_a_page_route(ctx, monkeypatch, url):
    """`forbidden_page` negotiates on `Accept`; the public-failure handler must too.

    A page route that answers `application/json` to a browser is a transport-shape defect
    even when nothing private leaks: the reader sees a JSON blob where the page was.
    """
    unloadable(ctx, monkeypatch, ProjectionError)
    with web(ctx) as client:
        response = client.get(url, headers=BROWSER)
    assert response.status_code == 500, response.text
    assert response.headers["content-type"].startswith("text/html"), response.text
    assert "Operation failed; inspect local logs by operation ID" in response.text
    assert PRIVATE not in response.text


@pytest.mark.parametrize("url", OWNED_PAGE_ROUTES)
def test_a_json_client_still_gets_the_closed_body_from_the_same_routes(ctx, monkeypatch, url):
    """Negotiation, not replacement: a script asking for JSON keeps the body it branches on."""
    unloadable(ctx, monkeypatch, ProjectionError)
    with web(ctx) as client:
        response = client.get(url, headers={"Accept": "application/json"})
    assert response.status_code == 500, response.text
    assert response.json() == {
        "error": "Operation failed; inspect local logs by operation ID",
        "code": "operation_failed",
    }


PARTIAL_ROUTES = ("/partials/sources", "/partials/sources/s1/status")


@pytest.mark.parametrize("url", PARTIAL_ROUTES)
def test_a_partial_route_answers_a_fragment_when_a_mapped_failure_escapes(ctx, monkeypatch, url):
    """htmx swaps a partial's body into the page that polls it, so a whole document is the
    wrong shape there (wrap-up review finding 20). The negotiation, the status, the bounded
    sentence and the code are the page routes' own; only the frame differs.
    """
    unloadable(ctx, monkeypatch, ProjectionError)
    with web(ctx) as client:
        response = client.get(url, headers=BROWSER)
        page = client.get("/", headers=BROWSER)
    assert response.status_code == 500, response.text
    assert response.headers["content-type"].startswith("text/html"), response.text
    assert "Operation failed; inspect local logs by operation ID" in response.text
    assert "operation_failed" in response.text
    assert PRIVATE not in response.text
    assert "<html" not in response.text.lower(), response.text
    assert page.status_code == 500 and "<html" in page.text.lower(), page.text


def test_the_two_domain_routes_are_writes_and_join_neither_get_list(ctx):
    """A14, invariant I6: the domain routes are a form POST and a JSON PUT, never a page or partial GET.

    `OWNED_PAGE_ROUTES` and `PARTIAL_ROUTES` list GET routes only. A GET on either domain path would
    need a row in one of them, so this fails first and names the route.
    """
    from hippo.web.routes import sources as source_routes

    expected = {
        "/sources/{source_id}/domain": {"POST"},
        "/api/sources/{source_id}/domain": {"PUT"},
    }
    # FastAPI 0.141 nests an included router behind a private wrapper, so `app.routes` shows no
    # page route at all. The OpenAPI paths are the public table of the assembled app, and the two
    # module-level routers are where the routes are declared.
    paths = create_app(ctx).openapi()["paths"]
    assert "/" in paths and "/partials/sources" in paths, "the OpenAPI table lost the page routes"
    assert {
        path: {m.upper() for m in ops} for path, ops in paths.items() if path.endswith("/domain")
    } == expected
    declared: dict[str, set[str]] = {}
    for router in (source_routes.router, source_routes.api):
        for route in router.routes:
            if route.path.endswith("/domain"):
                declared.setdefault(route.path, set()).update(route.methods)
    assert declared == expected
    assert not [url for url in (*OWNED_PAGE_ROUTES, *PARTIAL_ROUTES) if url.endswith("/domain")]


def test_the_api_routes_answer_json_even_to_a_browsers_accept_header(ctx, monkeypatch):
    """A browser's `Accept` must not turn an `/api` body into a page; the JS reads JSON."""
    unloadable(ctx, monkeypatch, ProjectionError)
    with web(ctx) as client:
        response = client.get("/api/graph/full", headers=BROWSER)
    assert response.status_code == 500, response.text
    assert response.headers["content-type"].startswith("application/json"), response.text


def test_the_app_handler_and_the_page_renderer_do_not_share_a_name(ctx):
    """Two `public_failure_page`s in adjacent modules, one an async handler and one a page
    renderer with a different signature, is one import line away from registering the wrong
    one as an exception handler -- and it would only surface when something actually failed.

    `app.py` now imports the renderer, so the two names must not collide at all: the
    handler is `public_failure_handler` and `app.public_failure_page` is render's own.
    """
    from hippo.web import app as app_module
    from hippo.web import render as render_module

    assert app_module.public_failure_page is render_module.public_failure_page
    assert app_module.public_failure_handler is not render_module.public_failure_page
    registered = create_app(ctx).exception_handlers
    assert set(registered.values()) >= {app_module.public_failure_handler}


def test_the_ask_fragments_failure_is_logged_at_warning_with_an_operation_id(ctx, monkeypatch, caplog):
    """The sentence promises an operation ID; the log has to be able to honour it.

    The server runs at INFO, so a DEBUG-only traceback is never emitted in production and
    an operator following "inspect local logs by operation ID" finds a class name and
    nothing to correlate it with.
    """
    import logging
    import re

    from hippo.knowledge.source_lifecycle import OPERATION_ID
    from hippo.web.routes import pages as pages_module

    def refuse(*args, **kwargs):
        raise RuntimeError(POISON)

    monkeypatch.setattr(pages_module.ask_service, "ask", refuse)
    with caplog.at_level(logging.INFO):
        with web(ctx, reader(ctx)) as client:
            response = client.post("/ask", data={"question": QUESTION})
    assert response.status_code == 200, response.text
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "ask failed" in r.message]
    assert warnings, caplog.text
    (record,) = warnings
    assert type(RuntimeError()).__name__ in record.getMessage()
    (operation,) = re.findall(r"index\.[0-9a-f]+|ask\.[0-9a-f]+", record.getMessage())
    assert OPERATION_ID.match(operation)
    # The reader is handed the same identity the log line carries, or the promise is empty.
    assert operation in response.text
    for secret in (*SECRETS, MODEL_BODY):
        assert secret not in response.text
