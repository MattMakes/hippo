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

# The one denial every surface prints, spelled out rather than composed from the constants
# under test: `web/app.py` answers 409 with this sentence and this code, and the point of the
# assertion is that MCP and the CLI say the same words, not that they agree with themselves.
DENIAL = "authorization_changed: Permissions changed; repeat the query"

# The four code-graph tools and an argument list each, so a failure contract can be
# parametrised over the whole surface rather than over `blast_radius_tool` alone.
CODE_TOOLS = ("explain_path", "blast_radius", "exception_path", "history")
CODE_ARGS = {
    "explain_path": ("a_symbol", "b_symbol"),
    "blast_radius": ("a_symbol",),
    "exception_path": ("a_symbol", "SomeError"),
    "history": ("a_symbol",),
}


def code_tool(ctx, name: str, principal: Principal):
    """Call one of the four code-graph tools with the arguments it wants."""
    return getattr(mcp_server, f"{name}_tool")(ctx, *CODE_ARGS[name], principal=principal)


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


def test_a_gated_local_index_really_reaches_the_managed_lane(cli_ctx, tmp_path, monkeypatch, capsys):
    """Not just "the actor was passed": the pipeline really dispatches on it.

    Every other ingress test stops at the spy, so this is the one that runs the command
    through. The consequence of the actor is the whole point: the same `.md` that open
    mode indexes legacy now goes to the coordinator, which needs embedding metadata the
    legacy lane never asked for. The shared fake serves none, so what this proves is the
    dispatch and the presentation of its failure - a stable code, a bounded sentence, and
    no exception text. The coordinator's own happy path is
    `test_managed_pipeline_activation.py`'s.
    """
    admin, _ = users(cli_ctx)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, admin["token"])
    note = tmp_path / "zed.md"
    note.write_text("Zed Labs is located in Lisbon. Zed Labs builds drones.\n")
    assert cli.main(["index", str(note), "--name", "Zed notes"]) == 1
    captured = capsys.readouterr()
    source = cli_ctx.store.list_sources()[0]
    assert source["name"] == "Zed notes"
    # The managed lane's own closed mapping, stored on the row in the same `code: message`
    # shape a ToolError and the CLI's own stderr line use, and printed as-is.
    assert source["error"] == "model_unavailable: The local model service was unavailable during the build."
    assert captured.err.strip() == f"error: {source['error']}"
    assert "status: failed" in captured.out
    assert_clean(captured.out + captured.err)


@pytest.mark.parametrize(
    "code",
    ["model_unavailable", "retrieval_rebuild_required", "build_interrupted", "authorization_changed"],
)
def test_cli_index_prints_a_closed_stored_error_unchanged(cli_ctx, tmp_path, monkeypatch, capsys, code):
    """Every code `managed_activation` can store is already the public rendering.

    `authorization_changed` is the one the public table maps to `None` on purpose;
    `retrieval_rebuild_required` is the tenth, added when the managed table learned to tell
    a stale embedding profile from an unreachable model; and `build_interrupted` is the
    eleventh, which the store's restart sweep writes with no exception behind it at all.
    None of them may be swallowed -- each one tells the reader what to do next.
    """
    stored = f"{code}: The build could not be completed."
    note = _failing_index(cli_ctx, tmp_path, monkeypatch, stored)
    assert cli.main(["index", str(note)]) == 1
    assert capsys.readouterr().err.strip() == f"error: {stored}"


def test_cli_index_never_prints_an_unclosed_stored_error(cli_ctx, tmp_path, monkeypatch, capsys):
    """F3: the legacy lane stores `f"{type(err).__name__}: {err}"`, which is not a rendering.

    `map_build_failure` never sees a legacy build, so the row can hold a model's reply body,
    an absolute path or a sentence of the source itself. `cmd_index` printed it verbatim.
    """
    stored = f"OllamaError: {POISON}"
    note = _failing_index(cli_ctx, tmp_path, monkeypatch, stored)
    assert cli.main(["index", str(note)]) == 1
    captured = capsys.readouterr()
    source_id = cli_ctx.store.list_sources()[0]["id"]
    assert captured.err.strip() == f"error: indexing failed; inspect local logs for source {source_id}"
    assert_clean(captured.err + captured.out)


def _failing_index(cli_ctx, tmp_path, monkeypatch, stored: str):
    """An open-mode `hippo index` whose source row ends up carrying `stored`."""
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)
    note = tmp_path / "zed.md"
    note.write_text("Zed Labs is located in Lisbon. Zed Labs builds drones.\n")
    original = cli_ctx.jobs.wait_all

    def fail_the_build(*args, **kwargs):
        original(*args, **kwargs)
        source = cli_ctx.store.list_sources()[0]
        cli_ctx.store.update_source(source["id"], status="failed", stage="failed", error=stored)

    monkeypatch.setattr(cli_ctx.jobs, "wait_all", fail_the_build)
    return note


def test_a_gated_local_index_is_owned_by_its_creator_and_kept_to_their_tier(
    cli_ctx, tmp_path, monkeypatch, capsys
):
    """F4: `hippo index` resolves an identity and then has to use it for visibility too.

    `hippo_remember` passes `owner_id` and `access_role_id`; `cmd_index` passed neither, so
    both defaulted to `None` and `min_rank` fell to `EVERYONE_RANK`. A low tier's own file
    was therefore published to every role, and its creator could not manage what they made.
    """
    cli_ctx.store.ensure_roles()
    creator = cli_ctx.store.get_user(cli_ctx.store.create_user("assistant", "secret1", "local-assistant"))
    below = cli_ctx.store.get_user(cli_ctx.store.create_user("everyone-else", "secret1", "individual"))
    monkeypatch.setenv(mcp_server.TOKEN_ENV, creator["token"])
    note = tmp_path / "zed.md"
    note.write_text("Zed Labs is located in Lisbon.\n")
    # 1, for the same reason as `test_a_gated_local_index_really_reaches_the_managed_lane`:
    # a reader actor over an eligible input dispatches the managed lane, which the shared
    # fake cannot serve. The row it left behind is what this test is about.
    assert cli.main(["index", str(note)]) == 1
    capsys.readouterr()

    row = cli_ctx.store.list_sources()[0]
    assert row["owner_id"] == creator["id"]
    assert row["min_rank"] == 10, "the row did not take the creator's own tier"

    them = Principal.for_user(creator, cli_ctx.store.get_role("local-assistant"))
    lower = Principal.for_user(below, cli_ctx.store.get_role("individual"))
    assert them.may_manage_source(row), "the creator cannot manage what they indexed"
    assert them.access.can_see_source(row)
    assert not lower.access.can_see_source(row), "a tier below the creator was shown their file"
    assert not lower.may_manage_source(row)


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


# The four code tools were outside the mapper entirely (4c review F2): they called
# `_code_graph` bare, so everything `query_session` does on acquisition and release, and
# `_code_answer`'s two `validate()` calls, escaped with their own text. Each test below is
# one of those escapes.


@pytest.mark.parametrize("tool", CODE_TOOLS)
def test_mcp_code_tool_session_acquisition_failure_is_a_stable_code(ctx, monkeypatch, tool):
    """Acquiring the view is inside the mapper: this is the half of F2 that really leaked."""

    def explode(*args, **kwargs):
        raise OllamaError(POISON)

    monkeypatch.setattr(ctx, "graph_for", explode)
    with pytest.raises(ToolError) as caught:
        code_tool(ctx, tool, anyone(ctx))
    message = str(caught.value)
    assert message == "retrieval_unavailable: Retrieval service is unavailable"
    assert_clean(message)


@pytest.mark.parametrize("tool", CODE_TOOLS)
def test_mcp_code_tool_denial_before_the_build_reads_as_the_shared_denial(code_index, monkeypatch, tool):
    """`_code_answer`'s leading `validate()` used to sit outside the try and escape raw."""
    code_ctx, _ = code_index
    original = code_ctx.graph_for

    def revoke_after_acquiring(*args, **kwargs):
        graph = original(*args, **kwargs)
        code_ctx.store._bump_authorization_epoch()
        return graph

    monkeypatch.setattr(code_ctx, "graph_for", revoke_after_acquiring)
    with pytest.raises(ToolError) as caught:
        code_tool(code_ctx, tool, anyone(code_ctx))
    assert str(caught.value) == DENIAL


def test_mcp_code_tool_denial_outranks_a_mapped_build_failure(code_index, monkeypatch):
    """A `finally` that raises replaces what is in flight, so the mapper has to see it.

    The build fails on a poisoned model error *and* the epoch moves. Before the fix the
    mapped `ToolError` was swallowed by the trailing `validate()` and the caller got a
    masked crash (`Error executing tool ...`) plus a full traceback in the server log.
    """
    code_ctx, _ = code_index

    def revoked_and_failed(*args, **kwargs):
        code_ctx.store._bump_authorization_epoch()
        raise OllamaError(POISON)

    monkeypatch.setattr(mcp_server, "path_payload", revoked_and_failed)
    with pytest.raises(ToolError) as caught:
        mcp_server.explain_path_tool(code_ctx, "a", "b", principal=anyone(code_ctx))
    message = str(caught.value)
    assert message == DENIAL
    assert_clean(message)


def test_mcp_code_tool_build_failure_survives_a_view_that_is_still_valid(code_index, monkeypatch):
    """Nothing moved, so the mapped code is what the caller gets: the denial does not win by default."""
    code_ctx, _ = code_index

    def explode(*args, **kwargs):
        raise OllamaError(POISON)

    monkeypatch.setattr(mcp_server, "blast_payload", explode)
    with pytest.raises(ToolError) as caught:
        mcp_server.blast_radius_tool(code_ctx, "a", principal=anyone(code_ctx))
    message = str(caught.value)
    assert message == "retrieval_unavailable: Retrieval service is unavailable"
    assert_clean(message)


def test_mcp_code_tool_ambiguity_still_carries_its_candidates(code_index):
    """The carve-out survives the nesting: a name and what it could have meant are the answer."""
    code_ctx, _ = code_index
    with pytest.raises(ToolError) as caught:
        mcp_server.history_tool(code_ctx, "log", principal=anyone(code_ctx))
    message = str(caught.value)
    assert "could mean any of" in message
    assert "pyapp.store.Base.log" in message


def test_mcp_source_listing_validates_its_view_like_the_cli(ctx, monkeypatch):
    """F7: `_sources_locally` calls `view.validate()` after building its rows; `sources_tool` did not.

    `source_view` keeps its own `authorization_epoch` comparison, which the session's exit
    check never runs, so skipping it is a real gap between two surfaces of the same slice.
    """
    import hippo.status as status

    ctx.store.create_source("text", "a note")
    calls = []
    original = status.source_view

    def recorded(app_ctx, access, *, session=None):
        view = original(app_ctx, access, session=session)
        inner = view.validate
        view.validate = lambda: (calls.append(len(view.sources)), inner())[1]
        return view

    monkeypatch.setattr(status, "source_view", recorded)
    rows = mcp_server.sources_tool(ctx, principal=anyone(ctx))
    assert calls == [len(rows)], "the MCP source listing did not validate the view it just rendered"


def test_mcp_remember_maps_an_unknown_failure_to_operation_failed(ctx, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError(POISON)

    monkeypatch.setattr(pipeline, "add_text", explode)
    with pytest.raises(ToolError) as caught:
        mcp_server.remember_tool(ctx, "Note", "some text", principal=Principal.open())
    message = str(caught.value)
    assert message == f"{OPERATION_FAILED.code}: {OPERATION_FAILED.message}"
    assert_clean(message)


def test_an_interrupt_is_not_a_public_failure(cli_ctx, monkeypatch):
    """Ctrl-C is the operator stopping the command, not hippo failing at it.

    Mapping it would print `operation_failed` and exit 2 for something that never went
    wrong, and would swallow the interrupt the shell is waiting for.
    """
    from hippo import ask as ask_module

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(ask_module, "ask", interrupt)
    with pytest.raises(KeyboardInterrupt):
        cli.main(["ask", QUESTION])


def test_an_interrupt_is_not_a_tool_error(ctx, monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    # `mcp_server` imported `ask` into its own namespace, so that is the binding to replace.
    monkeypatch.setattr(mcp_server, "ask", interrupt)
    with pytest.raises(KeyboardInterrupt):
        mcp_server.ask_tool(ctx, QUESTION, principal=anyone(ctx))


def test_a_tool_error_raised_inside_a_tool_is_passed_through(ctx, monkeypatch):
    """The mapper must not wrap a ToolError in itself, nor make it its own cause."""
    raised = ToolError("the question is empty")

    def explode(*args, **kwargs):
        raise raised

    monkeypatch.setattr(pipeline, "add_text", explode)
    with pytest.raises(ToolError) as caught:
        mcp_server.remember_tool(ctx, "Note", "some text", principal=Principal.open())
    assert caught.value is raised
    assert caught.value.__cause__ is not caught.value


def test_an_administrative_command_keeps_its_own_errors(cli_ctx, monkeypatch):
    """`pull-models` is not evidence, so a model outage there is not mapped to a code."""
    monkeypatch.setattr(cli_ctx.ollama, "is_up", lambda: True)
    monkeypatch.setattr(cli_ctx.ollama, "missing_models", lambda: ["nomic-embed-text:latest"])

    def explode(*args, **kwargs):
        raise OllamaError(POISON)

    monkeypatch.setattr(cli_ctx.ollama, "ensure_model", explode)
    with pytest.raises(OllamaError):
        cli.main(["pull-models"])


def test_an_authorization_change_reads_the_same_on_all_three_surfaces(ctx, monkeypatch, capsys):
    """One sentence and one code, and they are the web app's own (4c review F6).

    The three surfaces used to say three different things for the same condition: the web
    app answered 409 `Permissions changed; repeat the query`, MCP and the CLI shared a
    longer sentence of their own, and the remote client printed the URL and status on top.
    """
    from hippo import ask as ask_module
    from hippo.knowledge.access import AuthorizationChanged

    def revoked(*args, **kwargs):
        raise AuthorizationChanged(POISON)

    # The MCP tools bound `ask` at import; `cli.cmd_ask` imports it per call.
    monkeypatch.setattr(mcp_server, "ask", revoked)
    monkeypatch.setattr(ask_module, "ask", revoked)
    monkeypatch.setattr(AppContext, "from_env", classmethod(lambda cls, ollama=None: ctx))

    # The sentence is the web app's; the code is the managed lane's own for the same event.
    assert mcp_server.DENIED == cli.DENIED == "Permissions changed; repeat the query"
    assert mcp_server.DENIED_CODE == cli.DENIED_CODE == "authorization_changed"

    with pytest.raises(ToolError) as caught:
        mcp_server.ask_tool(ctx, QUESTION, principal=anyone(ctx))
    assert str(caught.value) == DENIAL

    assert cli.main(["ask", QUESTION]) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == f"error: {DENIAL}"
    assert_clean(captured.err)

    # ...and the third surface, from the body `web/app.py` sends for the same condition.
    def denied(request):
        return httpx.Response(409, json={"error": mcp_server.DENIED, "code": mcp_server.DENIED_CODE})

    with pytest.raises(RemoteError) as remote_caught:
        remote_for(denied).ask(QUESTION)
    assert str(remote_caught.value) == DENIAL


def test_a_code_tool_denial_reads_the_same_on_both_surfaces(code_index, monkeypatch, capsys):
    """The same contract on a code tool, where 4c pinned it for `ask_tool` alone."""
    from hippo.web.routes import code as code_routes

    code_ctx, _ = code_index
    monkeypatch.setattr(AppContext, "from_env", classmethod(lambda cls, ollama=None: code_ctx))

    def revoked(*args, **kwargs):
        code_ctx.store._bump_authorization_epoch()
        return {"found": False, "a": "a", "b": "b", "lines": []}

    monkeypatch.setattr(mcp_server, "path_payload", revoked)
    with pytest.raises(ToolError) as caught:
        mcp_server.explain_path_tool(code_ctx, "a", "b", principal=anyone(code_ctx))
    assert str(caught.value) == DENIAL

    monkeypatch.setattr(code_routes, "path_payload", revoked)
    assert cli.main(["path", "a", "b"]) == 2
    assert capsys.readouterr().err.strip() == f"error: {DENIAL}"


def test_a_closed_validators_own_text_reads_the_same_on_both_surfaces(cli_ctx, tmp_path, monkeypatch, capsys):
    """F5: an exact-type `ValueError` is closed input validation the caller can act on.

    `tool_failure` already passed it through; `cli._refusal` did not, so the same upload
    limit read as its own sentence over MCP and as `operation_failed` on the CLI.
    """
    bounded = "note.md is too big (9000000 bytes); the limit is 1000000 bytes (HIPPO_MAX_UPLOAD_BYTES)"

    def too_big(*args, **kwargs):
        raise ValueError(bounded)

    monkeypatch.setattr(pipeline, "add_text", too_big)
    monkeypatch.setattr(pipeline, "add_upload", too_big)
    with pytest.raises(ToolError) as caught:
        mcp_server.remember_tool(cli_ctx, "Note", "some text", principal=Principal.open())
    assert str(caught.value) == bounded

    note = tmp_path / "note.md"
    note.write_text("Zed Labs is located in Lisbon.\n")
    assert cli.main(["index", str(note)]) == 2
    assert capsys.readouterr().err.strip() == f"error: {bounded}"


def test_a_value_error_subclass_is_still_operation_failed_on_both_surfaces(
    cli_ctx, tmp_path, monkeypatch, capsys
):
    """The exact-type check is what keeps the managed `ValueError` subclasses out."""
    from hippo.knowledge.projection import ProjectionError

    def explode(*args, **kwargs):
        raise ProjectionError(POISON)

    monkeypatch.setattr(pipeline, "add_text", explode)
    monkeypatch.setattr(pipeline, "add_upload", explode)
    failed = f"{OPERATION_FAILED.code}: {OPERATION_FAILED.message}"
    with pytest.raises(ToolError) as caught:
        mcp_server.remember_tool(cli_ctx, "Note", "some text", principal=Principal.open())
    assert str(caught.value) == failed

    note = tmp_path / "note.md"
    note.write_text("Zed Labs is located in Lisbon.\n")
    assert cli.main(["index", str(note)]) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == f"error: {failed}"
    assert_clean(captured.err)


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
    assert str(caught.value) == f"{OPERATION_FAILED.code}: {OPERATION_FAILED.message} (HTTP 500)"


def test_remote_client_never_prints_a_code_less_server_error():
    """F1: a *parseable* body holding a raw `error` string is the shape that leaked.

    `/api/ask` still answers the pre-activation `{"error": str(exc)}` with no code, and an
    `OllamaError` carries 300 characters of the model's reply body by construction. The old
    `_refusal` fell through to `body.get("error")` and printed it.
    """
    for status in (502, 500, 503):

        def handler(request, status=status):
            return httpx.Response(status, json={"error": POISON})

        with pytest.raises(RemoteError) as caught:
            remote_for(handler).ask(QUESTION)
        message = str(caught.value)
        assert_clean(message)
        assert message == f"{OPERATION_FAILED.code}: {OPERATION_FAILED.message} (HTTP {status})"


def test_remote_client_never_prints_a_code_less_error_key_on_a_4xx_either():
    """A code-less `error` is the un-migrated route shape whatever its status; only `detail` is bounded."""

    def handler(request):
        return httpx.Response(409, json={"error": POISON})

    with pytest.raises(RemoteError) as caught:
        remote_for(handler).ask(QUESTION)
    message = str(caught.value)
    assert_clean(message)
    assert message == f"{OPERATION_FAILED.code}: {OPERATION_FAILED.message} (HTTP 409)"


def test_remote_client_keeps_a_legacy_validators_bounded_detail_on_a_4xx():
    """The symbol the caller named is the one actionable fact, and it is their own input.

    `/api/code` answers `HTTPException(404, str(UnknownSymbol))`, which FastAPI renders as a
    code-less `detail`. Printing it is what makes `hippo blast no_such_thing` read the same
    behind a server as it does locally.
    """

    def handler(request):
        return httpx.Response(404, json={"detail": "no_such_thing is not a symbol in this memory"})

    with pytest.raises(RemoteError) as caught:
        remote_for(handler).code_blast_radius("no_such_thing", 2)
    assert str(caught.value) == "no_such_thing is not a symbol in this memory"


def test_remote_ambiguity_is_never_an_empty_line():
    """F8: a 409 carrying `candidates` but neither text key printed a bare `error:` header."""

    def handler(request):
        return httpx.Response(409, json={"candidates": ["a.log", "b.log"]})

    with pytest.raises(RemoteAmbiguous) as caught:
        remote_for(handler).code_history("log", 3)
    assert str(caught.value).strip(), "the candidate list was printed under an empty message"
    assert caught.value.candidates == ["a.log", "b.log"]


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
