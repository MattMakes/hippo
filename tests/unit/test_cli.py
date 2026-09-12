"""The `hippo` command line: argument parsing for every subcommand, and the commands that run on the fakes.

The fourteen tests that reach a running server carry one filter marker each. Importing
`starlette.testclient` raises `DeprecationWarning: The anyio.abc.BlockingPortal alias is
deprecated` from anyio itself, and the import happens inside `behind_server`, so under
`-W error` it errors in fixture setup. The marker is the sanctioned per-test form; the
import stays local so the rest of the file needs nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hippo import cli
from hippo.context import AppContext
from hippo.hipporag.indexer import Chunk, index_source
from tests.fakes.code_fixture import write_commit_history


@pytest.fixture
def cli_ctx(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> AppContext:
    """Every command builds its context with AppContext.from_env(); point that at the test fixture."""
    monkeypatch.setattr(AppContext, "from_env", classmethod(lambda cls, ollama=None: ctx))
    return ctx


def index_sample(ctx: AppContext, sample_text: str) -> str:
    sections = sample_text.split("## ")[1:]
    chunks = [
        Chunk(i, s.splitlines()[0].strip(), "\n".join(s.splitlines()[1:]).strip())
        for i, s in enumerate(sections)
    ]
    source_id = ctx.store.create_source("sample", "Acme guide")
    index_source(ctx.store, ctx.ollama, source_id, chunks)
    return source_id


# ------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("argv", "command", "extra"),
    [
        (["serve"], "serve", {"host": None, "port": None}),
        (["serve", "--host", "127.0.0.1", "--port", "9000"], "serve", {"host": "127.0.0.1", "port": 9000}),
        (["mcp"], "mcp", {}),
        (["pull-models"], "pull-models", {}),
        (["index", "notes.md"], "index", {"target": "notes.md", "name": None}),
        (
            ["index", "https://github.com/a/b", "--name", "B"],
            "index",
            {"target": "https://github.com/a/b", "name": "B"},
        ),
        (["ask", "Who designed the Orion arm?"], "ask", {"question": "Who designed the Orion arm?"}),
        (["sources"], "sources", {}),
        (["settings"], "settings", {}),
        (["users"], "users", {}),
        (
            ["user", "add", "ann", "--role", "individual", "--password", "pw"],
            "user",
            {"user_command": "add", "username": "ann", "role": "individual"},
        ),
        (["user", "token", "ann", "--new"], "user", {"user_command": "token", "new": True}),
        (["user", "role", "ann", "local-admin"], "user", {"user_command": "role", "role_id": "local-admin"}),
        (["user", "remove", "ann"], "user", {"user_command": "remove"}),
        (["path", "a.b", "c.d"], "path", {"a": "a.b", "b": "c.d"}),
        (["blast", "OrderService.place"], "blast", {"symbol": "OrderService.place", "depth": 2}),
        (["blast", "place", "--depth", "3"], "blast", {"symbol": "place", "depth": 3}),
        (["raises", "save", "OrderError"], "raises", {"symbol": "save", "exception": "OrderError"}),
        (["history", "place"], "history", {"symbol": "place", "limit": 3}),
        (["history", "place", "--limit", "5"], "history", {"symbol": "place", "limit": 5}),
    ],
)
def test_parses_every_subcommand(argv, command, extra):
    args = cli.build_parser().parse_args(argv)
    assert args.command == command
    for key, value in extra.items():
        assert getattr(args, key) == value


def test_no_subcommand_is_an_error():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


# ------------------------------------------------------------ commands


def test_settings_prints_config_and_retrieval_settings(cli_ctx: AppContext, capsys):
    assert cli.main(["settings"]) == 0
    out = capsys.readouterr().out
    assert "ollama_url" in out and cli_ctx.config.ollama_url in out
    for key in cli_ctx.store.get_settings():
        assert key in out


def test_sources_on_an_empty_memory_says_so(cli_ctx: AppContext, capsys):
    assert cli.main(["sources"]) == 0
    assert "empty" in capsys.readouterr().out


def test_sources_prints_a_table(cli_ctx: AppContext, sample_text: str, capsys):
    source_id = index_sample(cli_ctx, sample_text)
    assert cli.main(["sources"]) == 0
    out = capsys.readouterr().out
    header, rows = out.splitlines()[0], out.splitlines()[2:]
    assert header.split() == ["id", "name", "kind", "status", "stage", "passages", "facts", "created"]
    assert len(rows) == 1
    assert source_id in rows[0] and "Acme guide" in rows[0] and "sample" in rows[0]


def test_ask_prints_the_answer_and_passages(cli_ctx: AppContext, sample_text: str, capsys):
    index_sample(cli_ctx, sample_text)
    assert cli.main(["ask", "Where is Acme Robotics headquartered?"]) == 0
    out = capsys.readouterr().out
    assert "Boulder" in out
    assert "Top passages:" in out
    assert "The company" in out


def test_index_a_file_waits_and_reports_ready(cli_ctx: AppContext, tmp_path: Path, capsys):
    note = tmp_path / "zed.md"
    note.write_text("Zed Labs is located in Lisbon. Zed Labs builds drones.\n")
    assert cli.main(["index", str(note), "--name", "Zed notes"]) == 0
    out = capsys.readouterr().out
    assert "status: ready" in out
    sources = cli_ctx.store.list_sources()
    assert len(sources) == 1
    assert sources[0]["name"] == "Zed notes"
    assert sources[0]["kind"] == "file"
    assert sources[0]["passages"] >= 1


def test_index_a_folder_is_zipped_and_indexed(cli_ctx: AppContext, tmp_path: Path, capsys):
    folder = tmp_path / "docs"
    (folder / ".git").mkdir(parents=True)
    (folder / ".git" / "junk.md").write_text("Nope is located in Nowhere.\n")
    (folder / "a.md").write_text("Zed Labs is located in Lisbon.\n")
    (folder / "b.md").write_text("Zed Labs builds drones.\n")
    assert cli.main(["index", str(folder)]) == 0
    assert "status: ready" in capsys.readouterr().out
    sources = cli_ctx.store.list_sources()
    assert sources[0]["kind"] == "archive"
    assert sources[0]["name"] == "docs.zip"
    assert sources[0]["passages"] == 2  # the .git file was left out


def test_index_missing_path_fails_cleanly(cli_ctx: AppContext, tmp_path: Path, capsys):
    assert cli.main(["index", str(tmp_path / "nope.md")]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_pull_models_reports_progress(cli_ctx: AppContext, fake_ollama, capsys):
    fake_ollama.installed.remove("nomic-embed-text:latest")
    assert cli.main(["pull-models"]) == 0
    out = capsys.readouterr().out
    assert "Pulling nomic-embed-text" in out
    assert "nomic-embed-text is ready" in out
    assert "100%" in out


def test_pull_models_when_everything_is_installed(cli_ctx: AppContext, capsys):
    assert cli.main(["pull-models"]) == 0
    assert "All models are installed" in capsys.readouterr().out


# ------------------------------------------------------- the code graph

# The same four answers have to come out of the local graph and out of a running server, so every
# test below is written once and run against both fixtures. Only the plumbing differs; if the two
# branches ever print different things, that is the bug these tests exist to catch.

PLACE = "pyapp.orders.OrderService.place"


@pytest.fixture
def code_cli_ctx(code_index, monkeypatch: pytest.MonkeyPatch) -> AppContext:
    """The code sample (plus three commits) in a memory this process can open."""
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    monkeypatch.setattr(AppContext, "from_env", classmethod(lambda cls, ollama=None: ctx))
    return ctx


@pytest.fixture
def code_cli_behind_server(code_index, monkeypatch: pytest.MonkeyPatch):
    """The same memory, but only `hippo serve` can open it: every answer comes over /api/code."""
    ctx, source_id = code_index
    write_commit_history(ctx, source_id)
    yield from behind_server(ctx, monkeypatch)


@pytest.fixture(params=["local", "remote"])
def code_cli(request):
    """Both branches of `_context_or_running_server`, one test body."""
    return request.getfixturevalue("code_cli_ctx" if request.param == "local" else "code_cli_behind_server")


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_path_prints_the_relations_that_connect_two_symbols(code_cli, capsys):
    assert cli.main(["path", "pyapp.cli.main", "pyapp.billing.total"]) == 0
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "pyapp.cli.main -[INVOKES 0.90 via_import]-> pyapp.orders.OrderService.place",
        "pyapp.orders.OrderService.place -[INVOKES 0.90 via_import]-> pyapp.billing.total",
    ]


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_path_says_so_when_nothing_connects_them(code_cli, capsys):
    assert cli.main(["path", PLACE, "table customers"]) == 0
    assert "No relations connect" in capsys.readouterr().out


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_blast_prints_the_levels_and_the_subsystems(code_cli, capsys):
    assert cli.main(["blast", "pyapp.billing.total", "--depth", "1"]) == 0
    out = capsys.readouterr().out
    assert "What depends on pyapp.billing.total (depth 1):" in out
    assert "Level 1: pyapp.billing, pyapp.orders.OrderService.place" in out


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_raises_prints_the_route_to_the_exception(code_cli, capsys):
    # Both names in full: the Rust tree has an `OrderService.save` and an `OrderError` too, and a
    # name that means several things is an error the CLI reports rather than a guess it makes.
    args = ["raises", "pyapp.orders.OrderService.save", "pyapp.store.OrderError"]
    assert cli.main(args) == 0
    assert (
        "pyapp.orders.OrderService.save -[RAISES 0.90 resolved]-> pyapp.store.OrderError"
        in capsys.readouterr().out
    )


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_history_prints_the_commits_that_touched_a_symbol(code_cli, capsys):
    assert cli.main(["history", PLACE]) == 0
    assert "b2b2b2b 2026-01-02 Total the order in place" in capsys.readouterr().out


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_history_of_an_untouched_symbol_says_so(code_cli, capsys):
    assert cli.main(["history", "pyapp.billing.send_invoice"]) == 0
    assert "No commits" in capsys.readouterr().out


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_an_ambiguous_name_exits_two_and_lists_the_candidates(code_cli, capsys):
    assert cli.main(["history", "log"]) == 2
    err = capsys.readouterr().err
    assert "could mean any of" in err
    for candidate in ("pyapp.orders.OrderService.log", "pyapp.store.Base.log", "tsapp.models.base.Base.log"):
        assert f"  {candidate}" in err


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_an_unknown_name_exits_two(code_cli, capsys):
    assert cli.main(["blast", "no_such_thing"]) == 2
    assert "no_such_thing" in capsys.readouterr().err


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_a_blank_name_exits_two(code_cli, capsys):
    assert cli.main(["path", "  ", PLACE]) == 2
    assert "required" in capsys.readouterr().err


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_the_remote_branch_really_went_to_the_server(code_cli_behind_server, capsys):
    assert cli.main(["history", PLACE]) == 0
    assert "asking the server at http://localhost" in capsys.readouterr().err


# ------------------------------------------- when `hippo serve` has the database


def behind_server(ctx: AppContext, monkeypatch: pytest.MonkeyPatch):
    """
    The embedded database is open in another process (the web server): AppContext.from_env() raises
    StoreLockedError, and the CLI must fall back to that server's JSON API. The "server" here is the real
    app on the test fixtures, reached through Starlette's TestClient (an httpx.Client).

    A TestClient refuses a per-request `timeout` argument, which is why `RemoteHippo` bounds
    the liveness probe only on the client it builds itself: a client handed in this way owns
    its own transport settings.
    """
    from starlette.testclient import TestClient

    from hippo.remote import RemoteHippo
    from hippo.store import StoreLockedError
    from hippo.web.app import create_app

    def locked(cls, ollama=None):
        raise StoreLockedError("data/hippo.lbug is already open in another hippo process")

    monkeypatch.setattr(AppContext, "from_env", classmethod(locked))
    with TestClient(create_app(ctx), base_url="http://localhost") as http:
        remote = RemoteHippo("http://localhost", client=http)
        monkeypatch.setattr(RemoteHippo, "for_config", classmethod(lambda cls, config: remote))
        yield ctx


@pytest.fixture
def cli_behind_server(ctx: AppContext, sample_text: str, monkeypatch: pytest.MonkeyPatch):
    index_sample(ctx, sample_text)
    yield from behind_server(ctx, monkeypatch)


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_ask_uses_the_running_server_when_the_database_is_locked(cli_behind_server, capsys):
    assert cli.main(["ask", "Where is Acme Robotics headquartered?"]) == 0
    captured = capsys.readouterr()
    assert "Boulder" in captured.out and "Top passages:" in captured.out
    assert "asking the server at http://localhost" in captured.err


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_sources_and_settings_use_the_running_server(cli_behind_server, capsys):
    assert cli.main(["sources"]) == 0
    assert "Acme guide" in capsys.readouterr().out
    assert cli.main(["settings"]) == 0
    out = capsys.readouterr().out
    assert "server       = http://localhost" in out and "damping = " in out


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_index_uploads_to_the_running_server(cli_behind_server: AppContext, tmp_path: Path, capsys):
    note = tmp_path / "zed.md"
    note.write_text("Zed Labs is located in Lisbon. Zed Labs builds drones.\n")
    assert cli.main(["index", str(note)]) == 0
    assert "status: ready" in capsys.readouterr().out
    names = [s["name"] for s in cli_behind_server.store.list_sources()]
    assert "zed.md" in names


def test_locked_database_and_no_server_is_a_clear_error(monkeypatch: pytest.MonkeyPatch, capsys):
    from hippo.remote import RemoteHippo
    from hippo.store import StoreLockedError

    def locked(cls, ollama=None):
        raise StoreLockedError("data/hippo.lbug is already open in another hippo process")

    monkeypatch.setattr(AppContext, "from_env", classmethod(locked))
    monkeypatch.setattr(RemoteHippo, "is_up", lambda self: False)
    assert cli.main(["sources"]) == 2
    assert "already open in another hippo process" in capsys.readouterr().err


def test_user_commands_manage_the_ladder(cli_ctx: AppContext, capsys):
    assert cli.main(["users"]) == 0
    out = capsys.readouterr().out
    assert "arch-admin" in out and "No users yet" in out
    assert cli.main(["user", "add", "Ann", "--password", "secret1", "--name", "Ann Lee"]) == 0
    out = capsys.readouterr().out
    assert "Created ann as Arch admin" in out and "hippo_" in out and "no longer open" in out
    assert cli.main(["user", "add", "bob", "--password", "secret1", "--role", "individual"]) == 0
    capsys.readouterr()
    assert cli.main(["user", "add", "bob", "--password", "secret1"]) == 2, "duplicate username"
    assert cli.main(["users"]) == 0
    out = capsys.readouterr().out
    assert "ann" in out and "bob" in out and "Individual" in out
    assert cli.main(["user", "token", "bob"]) == 0
    token = capsys.readouterr().out.strip()
    assert cli_ctx.store.get_user_by_token(token)["username"] == "bob"
    assert cli.main(["user", "token", "bob", "--new"]) == 0
    assert capsys.readouterr().out.strip() != token
    assert cli.main(["user", "role", "bob", "local-admin"]) == 0
    assert "Local admin" in capsys.readouterr().out
    assert cli.main(["user", "role", "bob", "ceo"]) == 2
    assert cli.main(["user", "remove", "bob"]) == 0
    assert cli_ctx.store.get_user_by_username("bob") is None
    assert cli.main(["user", "token", "nobody"]) == 2


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_user_commands_go_through_the_running_server(
    cli_behind_server: AppContext, monkeypatch: pytest.MonkeyPatch, capsys
):
    """While `hippo serve` holds the database file, the user commands use its /api/users, token and all."""
    from hippo.remote import RemoteHippo

    assert cli.main(["users"]) == 0
    assert "No users yet" in capsys.readouterr().out
    # The first user closes open mode; the server hands its token back once, and the CLI prints it.
    assert cli.main(["user", "add", "ann", "--password", "secret1"]) == 0
    out = capsys.readouterr().out
    assert "Created ann as Arch admin" in out and "no longer open" in out
    token = next(line.strip() for line in out.splitlines() if line.strip().startswith("hippo_"))
    # The server signed the creating client in with a cookie (so a browser is not locked out); a real CLI
    # run is a fresh process with no cookie jar, so drop it here to behave like one.
    remote = RemoteHippo.for_config(cli_behind_server.config)  # the fixture's one shared client
    remote._client.cookies.clear()
    # Now every call needs a token. Without one the error says where to get it...
    assert cli.main(["sources"]) == 2
    assert "set HIPPO_TOKEN" in capsys.readouterr().err
    # ...and with HIPPO_TOKEN the remote client sends it as a bearer token.
    monkeypatch.setenv("HIPPO_TOKEN", token)
    remote._client.headers["Authorization"] = f"Bearer {token}"
    assert cli.main(["sources"]) == 0
    assert "Acme guide" in capsys.readouterr().out
    assert cli.main(["user", "add", "bob", "--password", "secret1", "--role", "individual"]) == 0
    capsys.readouterr()
    assert cli.main(["users"]) == 0
    assert "bob" in capsys.readouterr().out
    assert cli.main(["user", "token", "bob"]) == 2  # the server never repeats a token
    assert "--new" in capsys.readouterr().err
    assert cli.main(["user", "token", "bob", "--new"]) == 0
    new_token = capsys.readouterr().out.strip()
    assert cli_behind_server.store.get_user_by_token(new_token)["username"] == "bob"
    assert cli.main(["user", "role", "bob", "local-admin"]) == 0
    assert "Local admin" in capsys.readouterr().out
    assert cli.main(["user", "remove", "bob"]) == 0
    assert cli_behind_server.store.get_user_by_username("bob") is None
