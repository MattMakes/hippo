"""The `hippo` command line: argument parsing for every subcommand, and the commands that run on the fakes."""

from __future__ import annotations

from pathlib import Path

import pytest

from hippo import cli
from hippo.context import AppContext
from hippo.hipporag.indexer import Chunk, index_source


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


# ------------------------------------------- when `hippo serve` has the database


@pytest.fixture
def cli_behind_server(ctx: AppContext, sample_text: str, monkeypatch: pytest.MonkeyPatch):
    """
    The embedded database is open in another process (the web server): AppContext.from_env() raises
    StoreLockedError, and the CLI must fall back to that server's JSON API. The "server" here is the real
    app on the test fixtures, reached through Starlette's TestClient (an httpx.Client).
    """
    from starlette.testclient import TestClient

    from hippo.remote import RemoteHippo
    from hippo.store import StoreLockedError
    from hippo.web.app import create_app

    index_sample(ctx, sample_text)

    def locked(cls, ollama=None):
        raise StoreLockedError("data/hippo.lbug is already open in another hippo process")

    monkeypatch.setattr(AppContext, "from_env", classmethod(locked))
    with TestClient(create_app(ctx), base_url="http://localhost") as http:
        remote = RemoteHippo("http://localhost", client=http)
        monkeypatch.setattr(RemoteHippo, "for_config", classmethod(lambda cls, config: remote))
        yield ctx


def test_ask_uses_the_running_server_when_the_database_is_locked(cli_behind_server, capsys):
    assert cli.main(["ask", "Where is Acme Robotics headquartered?"]) == 0
    captured = capsys.readouterr()
    assert "Boulder" in captured.out and "Top passages:" in captured.out
    assert "asking the server at http://localhost" in captured.err


def test_sources_and_settings_use_the_running_server(cli_behind_server, capsys):
    assert cli.main(["sources"]) == 0
    assert "Acme guide" in capsys.readouterr().out
    assert cli.main(["settings"]) == 0
    out = capsys.readouterr().out
    assert "server       = http://localhost" in out and "damping = " in out


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
