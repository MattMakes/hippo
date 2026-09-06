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
