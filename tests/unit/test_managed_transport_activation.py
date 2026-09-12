"""MCP, the local CLI and the remote client: who is building, who is asking, and what a failure says.

This file is the transport half of PA1 and PA6. `test_managed_route_activation.py`
proved the library contracts (`query_session` selects structural generations,
`ask.py` dispatches dense over one owner); everything here proves that the three
non-web ingresses reach those contracts with the right identity and give a client
nothing but the closed public code.

Four things are under test:

* **Ingress actors.** HTTP MCP builds only as the principal its `AuthGate` resolved
  and never reads the process `HIPPO_TOKEN`; stdio MCP builds as the token's reader;
  local `hippo index` resolves the same token with `principal_from_bearer` and fails
  before a Source row exists when the token is missing or invalid. No transport ever
  manufactures `trusted_local`.
* **One owner per operation.** MCP ask/search and CLI ask hold a single dispatched
  owner: one acquisition, one finalizer, one heartbeat. MCP sources/code and the CLI's
  code and source listing hold one structural `query_session` instead of the
  unrestricted graph.
* **The CLI principal rule.** Gated local commands see managed evidence as the token's
  reader; never-gated open mode keeps the open audience, which proves legacy evidence
  only.
* **Closed failures.** A `ToolError`, a CLI stderr line and a remote client error all
  carry the same `code` and the same bounded sentence, and none of them carries the
  secrets, paths, source text or model bodies the injected exceptions are stuffed with.
"""

from __future__ import annotations

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from hippo import cli, mcp_server
from hippo.access import Principal, top_role
from hippo.context import AppContext
from hippo.ingest import pipeline
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.public_errors import OPERATION_FAILED
from hippo.ollama import OllamaError
from hippo.remote import RemoteAmbiguous, RemoteError, RemoteHippo
from tests.fakes.fake_ollama import DIM
from tests.unit.test_managed_route_activation import POISON, watch
from tests.unit.test_structural_loading import published

QUESTION = "who builds the thing?"
SECRETS = ("sk-live-DEADBEEF", "/Users/someone", "Acme Robotics", "embed:latest")


def anyone(ctx) -> Principal:
    """The open principal an ungated transport resolves."""
    return Principal.open(top_role(ctx.store.list_roles()))


def assert_clean(text: str) -> None:
    """Nothing a leaked exception could have carried survived into `text`."""
    for secret in SECRETS:
        assert secret not in text, f"{secret!r} reached a public surface: {text!r}"


# ------------------------------------------------------------------ fixtures


def users(ctx: AppContext):
    """An admin and a plain reader, which is what closes open mode."""
    ctx.store.ping()
    admin = ctx.store.create_user("transport-admin", "secret1", "arch-admin")
    reader = ctx.store.create_user("transport-reader", "secret1", "individual")
    return ctx.store.get_user(admin), ctx.store.get_user(reader)


@pytest.fixture
def cli_ctx(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> AppContext:
    """Every CLI command builds its context with `AppContext.from_env`; point it here."""
    monkeypatch.setattr(AppContext, "from_env", classmethod(lambda cls, ollama=None: ctx))
    return ctx


class Spy:
    """What an ingress actually handed the ingest pipeline.

    `delegate=False` stops before the real `add_*`, because a reader actor over an
    eligible input starts a managed coordinator build in a background job: the test
    would then be asserting on the coordinator rather than on the ingress.
    """

    def __init__(self):
        self.actors: list[BuildActor | None] = []
        self.calls = 0

    def install(self, monkeypatch, name: str, *, delegate: bool = True):
        original = getattr(pipeline, name)

        def record(*args, build_actor=None, **kwargs):
            self.calls += 1
            self.actors.append(build_actor)
            if not delegate:
                return "spied-source"
            return original(*args, build_actor=build_actor, **kwargs)

        monkeypatch.setattr(pipeline, name, record)
        return self


class WatchedEnv(dict):
    """A process environment that records every key read, so a leak is visible."""

    def __init__(self, real):
        super().__init__(real)
        self.reads: list[str] = []

    def get(self, key, default=None):
        self.reads.append(key)
        return super().get(key, default)


def watched_environ(monkeypatch, **values) -> WatchedEnv:
    """Replace the process environment `mcp_server` reads with a recording mapping."""
    import os as real_os
    from types import SimpleNamespace

    env = WatchedEnv(values)
    monkeypatch.setattr(mcp_server, "os", SimpleNamespace(environ=env, **_os_passthrough(real_os)))
    return env


def _os_passthrough(real_os) -> dict:
    """`mcp_server` only uses `os.environ`; keep the rest reachable all the same."""
    return {name: getattr(real_os, name) for name in ("getenv", "path", "sep")}


def headers_for(user) -> dict[str, str]:
    return {"authorization": f"Bearer {user['token']}"}


class Ctx:
    """The minimum `mcp.Context` the HTTP caller path inspects: request headers."""

    def __init__(self, headers):
        self.headers = headers


# --------------------------------------------------- 1. ingress build actors


def test_http_mcp_remember_builds_as_the_bearer_reader(ctx, monkeypatch):
    admin, reader = users(ctx)
    spy = Spy().install(monkeypatch, "add_text", delegate=False)
    # The ambient process token is the admin's; the request's bearer is the reader's.
    watched_environ(monkeypatch, **{mcp_server.TOKEN_ENV: admin["token"]})
    principal = mcp_server.caller(ctx, Ctx(headers_for(reader)))
    mcp_server.remember_tool(ctx, "Note", "Zed Labs is located in Lisbon.", principal=principal)
    assert [a.kind for a in spy.actors] == ["reader"]
    assert spy.actors[0].user_id == reader["id"]


def test_http_mcp_never_reads_the_process_token(ctx, monkeypatch):
    """The request's own credential decides; the ambient admin token is never consulted."""
    admin, reader = users(ctx)
    env = watched_environ(monkeypatch, **{mcp_server.TOKEN_ENV: admin["token"]})
    principal = mcp_server.caller(ctx, Ctx(headers_for(reader)))
    assert principal.user_id == reader["id"]
    with pytest.raises(ToolError, match="sign in required"):
        mcp_server.caller(ctx, Ctx({}))
    assert mcp_server.TOKEN_ENV not in env.reads


def test_stdio_mcp_does_read_the_process_token(ctx, monkeypatch):
    """The counterpart of the test above: the stdio transport's credential *is* the env var."""
    _, reader = users(ctx)
    env = watched_environ(monkeypatch, **{mcp_server.TOKEN_ENV: reader["token"]})
    assert mcp_server.caller(ctx, None, transport="stdio").user_id == reader["id"]
    assert mcp_server.TOKEN_ENV in env.reads


def test_stdio_mcp_builds_as_the_process_token_reader(ctx, monkeypatch):
    _, reader = users(ctx)
    spy = Spy().install(monkeypatch, "add_text", delegate=False)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, reader["token"])
    principal = mcp_server.caller(ctx, None, transport="stdio")
    mcp_server.remember_tool(ctx, "Note", "Zed Labs is located in Lisbon.", principal=principal)
    assert [a.kind for a in spy.actors] == ["reader"]
    assert spy.actors[0].user_id == reader["id"]


def test_open_mcp_remember_stays_legacy(ctx, monkeypatch):
    """No users: the open identity cannot prove managed evidence, so it passes no actor."""
    spy = Spy().install(monkeypatch, "add_text")
    principal = mcp_server.caller(ctx, Ctx({}))
    assert principal.is_open
    mcp_server.remember_tool(ctx, "Note", "Zed Labs is located in Lisbon.", principal=principal)
    assert spy.actors == [None]


def test_no_transport_ever_manufactures_a_trusted_local_actor(ctx, monkeypatch):
    _, reader = users(ctx)
    spy = Spy().install(monkeypatch, "add_text", delegate=False)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, reader["token"])
    mcp_server.remember_tool(
        ctx, "Note", "text here", principal=mcp_server.caller(ctx, None, transport="stdio")
    )
    mcp_server.remember_tool(ctx, "Open", "text here", principal=Principal.open())
    assert not [actor for actor in spy.actors if actor is not None and actor.kind == "trusted_local"]


def test_local_index_builds_as_the_token_reader(cli_ctx, tmp_path, monkeypatch, capsys):
    _, reader = users(cli_ctx)
    spy = Spy().install(monkeypatch, "add_upload", delegate=False)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, reader["token"])
    note = tmp_path / "zed.md"
    note.write_text("Zed Labs is located in Lisbon. Zed Labs builds drones.\n")
    assert cli.main(["index", str(note)]) == 0
    capsys.readouterr()
    assert [a.kind for a in spy.actors] == ["reader"]
    assert spy.actors[0].user_id == reader["id"]


@pytest.mark.parametrize("token", [None, "hippo_not-a-real-token"])
def test_local_index_without_a_valid_token_fails_before_a_source_row(
    cli_ctx, tmp_path, monkeypatch, capsys, token
):
    users(cli_ctx)
    spy = Spy().install(monkeypatch, "add_upload")
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)
    if token is not None:
        monkeypatch.setenv(mcp_server.TOKEN_ENV, token)
    note = tmp_path / "zed.md"
    note.write_text("Zed Labs is located in Lisbon.\n")
    assert cli.main(["index", str(note)]) == 2
    err = capsys.readouterr().err
    assert mcp_server.TOKEN_ENV in err
    assert spy.calls == 0, "the pipeline was reached despite a refused identity"
    assert cli_ctx.store.list_sources() == [], "a Source row was created before the identity check"


def test_open_mode_local_index_preserves_legacy_indexing(cli_ctx, tmp_path, monkeypatch, capsys):
    """Never-gated open mode: no users, no token, no actor, legacy behaviour unchanged."""
    spy = Spy().install(monkeypatch, "add_upload")
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)
    note = tmp_path / "zed.md"
    note.write_text("Zed Labs is located in Lisbon. Zed Labs builds drones.\n")
    assert cli.main(["index", str(note)]) == 0
    assert "status: ready" in capsys.readouterr().out
    assert spy.actors == [None]


def test_local_index_requires_add_sources(cli_ctx, tmp_path, monkeypatch, capsys):
    users(cli_ctx)
    reader = cli_ctx.store.get_user(cli_ctx.store.create_user("no-writes", "secret1", "individual"))
    spy = Spy().install(monkeypatch, "add_upload")
    monkeypatch.setattr(Principal, "can", lambda self, capability: capability != "add_sources")
    monkeypatch.setenv(mcp_server.TOKEN_ENV, reader["token"])
    note = tmp_path / "zed.md"
    note.write_text("Zed Labs is located in Lisbon.\n")
    assert cli.main(["index", str(note)]) == 2
    assert "add sources" in capsys.readouterr().err
    assert spy.calls == 0
    assert cli_ctx.store.list_sources() == []


# ------------------------------------------------- 2. one owner per operation


def test_mcp_ask_and_search_hold_one_dispatched_owner(ctx, monkeypatch):
    """A real reader over a managed corpus: one acquisition, one heartbeat, one dispatch."""
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    admin, _ = users(ctx)
    principal = mcp_server.caller(ctx, Ctx(headers_for(admin)))
    for tool in (mcp_server.search_tool, mcp_server.ask_tool):
        record = watch(ctx, monkeypatch)
        payload = tool(ctx, QUESTION, principal=principal)
        record.once()
        assert record.dispatched == ["tag_compatible"]
        assert payload


def test_mcp_sources_and_code_tools_hold_one_structural_session(ctx, monkeypatch, code_index):
    code_ctx, _ = code_index
    record = watch(code_ctx, monkeypatch)
    mcp_server.sources_tool(code_ctx, principal=anyone(code_ctx))
    record.once(heartbeats=0)
    assert record.dispatched == [], "a source listing must not dispatch a dense route"

    record = watch(code_ctx, monkeypatch)
    mcp_server.blast_radius_tool(code_ctx, "pyapp.billing.total", 1, principal=anyone(code_ctx))
    record.once(heartbeats=0)
    assert record.dispatched == []


def test_cli_ask_holds_one_dispatched_owner(cli_ctx, monkeypatch, capsys):
    """Gated `hippo ask`: the token's reader proves the corpus, over one dispatched owner."""
    published(cli_ctx.store, "managed", profile=cli_ctx.ollama.embed_model, dimension=DIM)
    admin, _ = users(cli_ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    record = watch(cli_ctx, monkeypatch)
    assert cli.main(["ask", QUESTION]) == 0
    capsys.readouterr()
    record.once()
    assert record.dispatched == ["tag_compatible"]


def test_cli_code_listing_uses_a_structural_session_not_the_whole_graph(code_index, monkeypatch, capsys):
    code_ctx, _ = code_index
    monkeypatch.setattr(AppContext, "from_env", classmethod(lambda cls, ollama=None: code_ctx))

    def refuse():
        pytest.fail("a CLI presentation command read the unrestricted graph")

    monkeypatch.setattr(code_ctx, "graph", refuse)
    record = watch(code_ctx, monkeypatch)
    assert cli.main(["blast", "pyapp.billing.total", "--depth", "1"]) == 0
    assert "Level 1: pyapp.billing" in capsys.readouterr().out
    record.once(heartbeats=0)


def test_cli_source_listing_uses_the_shared_source_view(cli_ctx, monkeypatch, capsys):
    """The listing is audience evidence, so it comes from the shared view over one held session."""
    import hippo.status as status

    published(cli_ctx.store, "managed", profile=cli_ctx.ollama.embed_model, dimension=DIM)
    admin, _ = users(cli_ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])

    views = []
    original = status.source_view

    def recorded(ctx, access, *, session=None):
        views.append((access, session))
        return original(ctx, access, session=session)

    monkeypatch.setattr(status, "source_view", recorded)
    record = watch(cli_ctx, monkeypatch)
    assert cli.main(["sources"]) == 0
    record.once()
    assert len(views) == 1, "the listing did not go through the shared source view"
    access, session = views[0]
    assert session is not None, "the view was not given the command's own held session"
    assert access.audience_kind == "reader"
    out = capsys.readouterr().out
    assert out.splitlines()[0].split() == [
        "id",
        "name",
        "kind",
        "status",
        "stage",
        "passages",
        "facts",
        "created",
    ]


# -------------------------------------------------- 3. the CLI principal rule


def test_gated_cli_query_proves_managed_evidence_for_the_token_reader(cli_ctx, monkeypatch, capsys):
    """Gated mode: the same `principal_from_bearer` rule as `hippo index`, for reads too."""
    published(cli_ctx.store, "managed", profile=cli_ctx.ollama.embed_model, dimension=DIM)
    admin, _ = users(cli_ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    assert cli.main(["sources"]) == 0
    assert "managed" in capsys.readouterr().out, "a real reader proves the managed generation"


def test_gated_cli_listing_is_scoped_to_the_token_reader(cli_ctx, monkeypatch, capsys):
    """The listing is that reader's evidence: a tier above them is not in it.

    Reading the Store's unrestricted Source rows would show the restricted source to
    both tokens, which is exactly the presentation the plan replaces.
    """
    admin, reader = users(cli_ctx)
    cli_ctx.store.create_source("text", "everyone-notes")
    cli_ctx.store.create_source("text", "admins-only", access_role_id="arch-admin")

    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    assert cli.main(["sources"]) == 0
    out = capsys.readouterr().out
    assert "admins-only" in out and "everyone-notes" in out

    monkeypatch.setenv(mcp_server.TOKEN_ENV, reader["token"])
    assert cli.main(["sources"]) == 0
    out = capsys.readouterr().out
    assert "everyone-notes" in out
    assert "admins-only" not in out, "a denied tier was listed a source above it"


def test_open_mode_cli_query_uses_the_open_audience_and_proves_legacy_only(
    cli_ctx, sample_text, monkeypatch, capsys
):
    """Never gated: the open audience reads legacy evidence and cannot prove a managed generation."""
    from tests.unit.test_ask import index_sample

    index_sample(cli_ctx, sample_text)
    published(cli_ctx.store, "managed", profile=cli_ctx.ollama.embed_model, dimension=DIM)
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)
    assert cli.main(["sources"]) == 0
    out = capsys.readouterr().out
    assert "Acme Robotics" in out, "the legacy source is the open audience's own evidence"
    assert "managed" not in out, "the open audience proved a managed generation"


def test_gated_cli_query_without_a_token_is_refused(cli_ctx, monkeypatch, capsys):
    published(cli_ctx.store, "managed", profile=cli_ctx.ollama.embed_model, dimension=DIM)
    users(cli_ctx)
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)
    assert cli.main(["sources"]) == 2
    assert mcp_server.TOKEN_ENV in capsys.readouterr().err


def test_administrative_commands_keep_their_unrestricted_store_reads(cli_ctx, monkeypatch, capsys):
    """`hippo users` is administration, not query evidence: it still reads the store directly."""
    users(cli_ctx)
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)
    assert cli.main(["users"]) == 0
    out = capsys.readouterr().out
    assert "transport-admin" in out and "transport-reader" in out


# ------------------------------------------------------------ 4. safe failures


def poisoned(ctx, monkeypatch):
    """Make every model call raise an exception stuffed with everything private."""

    def explode(*args, **kwargs):
        raise OllamaError(POISON)

    for name in ("embed_one", "embed_many", "chat_json", "chat_text"):
        if hasattr(ctx.ollama, name):
            monkeypatch.setattr(ctx.ollama, name, explode)


@pytest.mark.parametrize("tool", ["search", "ask"])
def test_mcp_model_failure_is_a_stable_code_with_no_private_text(ctx, monkeypatch, tool):
    published(ctx.store, "managed", profile=ctx.ollama.embed_model, dimension=DIM)
    admin, _ = users(ctx)
    principal = mcp_server.caller(ctx, Ctx(headers_for(admin)))
    poisoned(ctx, monkeypatch)
    call = mcp_server.search_tool if tool == "search" else mcp_server.ask_tool
    with pytest.raises(ToolError) as caught:
        call(ctx, QUESTION, principal=principal)
    message = str(caught.value)
    assert message == "retrieval_unavailable: Retrieval service is unavailable"
    assert_clean(message)


def test_mcp_remember_maps_an_unknown_failure_to_operation_failed(ctx, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError(POISON)

    monkeypatch.setattr(pipeline, "add_text", explode)
    with pytest.raises(ToolError) as caught:
        mcp_server.remember_tool(ctx, "Note", "some text", principal=Principal.open())
    message = str(caught.value)
    assert message == f"{OPERATION_FAILED.code}: {OPERATION_FAILED.message}"
    assert_clean(message)


def test_mcp_remember_keeps_its_own_validation_text(ctx):
    """Legacy input validation the client can act on is not a managed failure."""
    with pytest.raises(ToolError, match="empty"):
        mcp_server.remember_tool(ctx, "Note", "   ", principal=Principal.open())


def test_cli_ask_prints_the_stable_code_and_nothing_else(cli_ctx, monkeypatch, capsys):
    published(cli_ctx.store, "managed", profile=cli_ctx.ollama.embed_model, dimension=DIM)
    admin, _ = users(cli_ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    poisoned(cli_ctx, monkeypatch)
    assert cli.main(["ask", QUESTION]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "error: retrieval_unavailable: Retrieval service is unavailable"
    assert_clean(captured.err)


def test_cli_index_failure_is_a_stable_code(cli_ctx, tmp_path, monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise RuntimeError(POISON)

    monkeypatch.setattr(pipeline, "add_upload", explode)
    note = tmp_path / "zed.md"
    note.write_text("Zed Labs is located in Lisbon.\n")
    assert cli.main(["index", str(note)]) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == f"error: {OPERATION_FAILED.code}: {OPERATION_FAILED.message}"
    assert_clean(captured.err)


def test_cli_failures_reach_no_log_record(cli_ctx, monkeypatch, capsys, caplog):
    published(cli_ctx.store, "managed", profile=cli_ctx.ollama.embed_model, dimension=DIM)
    admin, _ = users(cli_ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    poisoned(cli_ctx, monkeypatch)
    with caplog.at_level(0):
        assert cli.main(["ask", QUESTION]) == 2
    capsys.readouterr()
    assert_clean("\n".join(record.getMessage() for record in caplog.records))


# ----------------------------------------------------------- the remote client


def remote_for(handler) -> RemoteHippo:
    """A `RemoteHippo` whose transport answers with whatever `handler` returns."""
    client = httpx.Client(base_url="http://server", transport=httpx.MockTransport(handler))
    return RemoteHippo("http://server", client=client, token="")


def test_remote_client_prints_the_servers_code_and_message(capsys):
    def handler(request):
        return httpx.Response(
            503, json={"error": "Retrieval service is unavailable", "code": "retrieval_unavailable"}
        )

    with pytest.raises(RemoteError) as caught:
        remote_for(handler).ask(QUESTION)
    assert str(caught.value) == "retrieval_unavailable: Retrieval service is unavailable"


def test_remote_client_never_dumps_a_response_body():
    def handler(request):
        return httpx.Response(500, text=f"<html><pre>{POISON}</pre></html>")

    with pytest.raises(RemoteError) as caught:
        remote_for(handler).sources()
    assert_clean(str(caught.value))


def test_remote_client_keeps_the_token_message_and_the_candidate_list():
    def unauthorized(request):
        return httpx.Response(401, json={"detail": "not signed in"})

    with pytest.raises(RemoteError) as caught:
        remote_for(unauthorized).sources()
    assert "HIPPO_TOKEN" in str(caught.value)

    def ambiguous(request):
        return httpx.Response(
            409, json={"detail": "'log' could mean any of", "candidates": ["a.log", "b.log"]}
        )

    with pytest.raises(RemoteAmbiguous) as caught:
        remote_for(ambiguous).code_history("log", 3)
    assert caught.value.candidates == ["a.log", "b.log"]


class Probe:
    """Records the keyword arguments the liveness probe passes to its client."""

    def __init__(self):
        self.kwargs: list[dict] = []
        self.headers: dict[str, str] = {}

    def get(self, path, **kwargs):
        self.kwargs.append(kwargs)
        return httpx.Response(200, json={}, request=httpx.Request("GET", f"http://server{path}"))


def test_the_liveness_probe_never_passes_a_timeout_to_an_injected_client():
    """A client handed in by a caller owns its own transport settings.

    This is what makes Starlette's `TestClient` usable as the CLI's transport: it
    raises `StarletteDeprecationWarning` for *any* per-request `timeout`, so the probe
    bounds the clients it builds itself and leaves the ones it is given alone.
    """
    probe = Probe()
    assert RemoteHippo("http://server", client=probe, token="").is_up()
    assert probe.kwargs == [{}], "a timeout argument reached an injected client"


def test_the_liveness_probe_still_bounds_a_client_it_built_itself():
    remote = RemoteHippo("http://server", timeout=600.0, token="")
    probe = Probe()
    remote._client = probe
    assert remote.is_up()
    assert probe.kwargs == [{"timeout": 3.0}]
