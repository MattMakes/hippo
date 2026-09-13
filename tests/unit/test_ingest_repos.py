"""Tests for hippo.ingest.repos: URL validation, safe cloning, walking a checkout."""

from __future__ import annotations

import logging
import subprocess
import traceback
from pathlib import Path

import pytest

from hippo.ingest import readers, repos
from hippo.ingest.repos import RepoError, clone_repo, is_git_url, repo_name, walk_repo

# A URL `is_git_url` accepts and that carries a personal access token as userinfo. Nothing
# derived from it but its bare host may reach a message, a traceback or a log line.
CREDENTIALED_URL = "https://robot:ghp_s3cr3tT0ken@git.example.com/owner/private.git"
CREDENTIAL_PARTS = ("ghp_s3cr3tT0ken", "robot:", "owner/private")


def rendered(error: BaseException) -> str:
    """What `log.exception` writes for this error: its message and every chained cause."""
    return "".join(traceback.format_exception(error))


# ------------------------------------------------------------------ urls


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/robots",
        "https://github.com/acme/robots.git",
        "http://gitlab.example.com/group/sub/project.git",
        "ssh://git@github.com/acme/robots.git",
        "git@github.com:acme/robots.git",
        "  https://github.com/acme/robots  ",
    ],
)
def test_is_git_url_accepts_remote_forms(url: str) -> None:
    assert is_git_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "/home/user/repo",
        "./repo",
        "file:///home/user/repo",
        "ftp://host.com/repo",
        "https://",
        "https://localhost/repo",  # no dot in the host: almost certainly not a remote
        "git@github.com",  # scp-like form needs a path
        "-oProxyCommand=evil",  # would be read as a git option
        "--upload-pack=evil https://github.com/a/b",
        "https://github.com/a/b; rm -rf /",
        "https://github.com/a/b\nother",
    ],
)
def test_is_git_url_rejects_local_and_odd_forms(url: str) -> None:
    assert not is_git_url(url)


def test_repo_name_uses_owner_and_repo() -> None:
    assert repo_name("https://github.com/acme/robots.git") == "acme/robots"
    assert repo_name("https://github.com/acme/robots/") == "acme/robots"
    assert repo_name("git@github.com:acme/robots.git") == "acme/robots"
    assert repo_name("ssh://git@host.com/deep/path/to/thing") == "to/thing"


# --------------------------------------------------------------- cloning


def test_clone_rejects_bad_urls_before_running_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("git must not run for a bad URL")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RepoError, match="does not look like a git URL"):
        clone_repo("/local/path", tmp_path / "dest")
    with pytest.raises(RepoError):
        clone_repo("file:///local/path", tmp_path / "dest")


def test_clone_passes_the_url_as_one_argument_after_a_double_dash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    url = "https://github.com/acme/robots.git"
    dest = tmp_path / "dest"
    assert clone_repo(url, dest, timeout=7) == dest
    command = seen["command"]
    assert isinstance(command, list)  # never a shell string
    assert command[:2] == ["git", "clone"]
    assert "--depth" in command and "--single-branch" in command
    assert command[command.index("--depth") + 1] == "1"  # shallow unless history is asked for
    assert command[command.index("--") + 1] == url  # "--" stops git from reading the URL as an option
    assert command[-1] == str(dest)
    assert seen["kwargs"].get("shell") is not True
    assert seen["kwargs"]["timeout"] == 7
    assert seen["kwargs"]["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_clone_deepens_when_history_is_wanted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # `code_history_depth` commits of history need `code_history_depth` commits on disk. Depth is
    # clamped up to 1, never to 0: a depth-0 clone is a full clone, which is not what "no history"
    # should cost.
    seen: list[list[str]] = []

    def fake_run(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    url = "https://github.com/acme/robots.git"
    clone_repo(url, tmp_path / "a", depth=200)
    clone_repo(url, tmp_path / "b", depth=0)
    clone_repo(url, tmp_path / "c", depth=-5)
    assert [c[c.index("--depth") + 1] for c in seen] == ["200", "1", "1"]


def test_clone_explains_timeouts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(RepoError, match="longer than 5 seconds"):
        clone_repo("https://github.com/acme/robots", tmp_path / "dest", timeout=5)


def test_a_clone_timeout_names_no_url_even_in_its_chained_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`TimeoutExpired` quotes the whole git command line, credentialed URL included.

    The legacy job logs a failure with `log.exception`, which prints the chained cause, so
    the timeout's own message and its `__cause__` both have to be free of the URL.
    """

    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(RepoError, match="longer than 5 seconds") as info:
        clone_repo(CREDENTIALED_URL, tmp_path / "dest", timeout=5)
    for part in (*CREDENTIAL_PARTS, "git.example.com"):
        assert part not in rendered(info.value)


def test_clone_explains_missing_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_git(command, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    with pytest.raises(RepoError, match="git is not installed"):
        clone_repo("https://github.com/acme/robots", tmp_path / "dest")


def test_clone_explains_git_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The reason is ours and is the whole of what reaches the user or the log.

    A `RepoError` message is answered as a 400 by `/api/sources/repo` and stored on the
    Source row by the legacy lane, so it may carry no server path, no proxy and no
    credential-helper banner -- all of which git writes to stderr. The four reason
    clauses are what a user can act on, and they are this module's own sentences.

    Review m6 (CC10): git's stderr used to be logged whole "for the operator", and so was
    the URL. Both can carry a credential, so the log now gets the closed reason and the
    bare host, and nothing else from the failure.
    """
    noise = "fatal: repository not found\nfatal: could not read /Users/ops/.git-credentials\n"

    def failing(command, **kwargs):
        return subprocess.CompletedProcess(command, 128, stdout="", stderr=noise)

    monkeypatch.setattr(subprocess, "run", failing)
    with caplog.at_level(logging.WARNING, logger="hippo.ingest.repos"):
        with pytest.raises(RepoError) as info:
            clone_repo("https://github.com/acme/missing", tmp_path / "dest")
    assert "no repository was found" in str(info.value)
    assert "git said" not in str(info.value)
    assert "repository not found" not in str(info.value)
    assert ".git-credentials" not in str(info.value)
    # Adapted for m6: this line used to assert the operator's log DID hold git's stderr.
    assert ".git-credentials" not in caplog.text and "repository not found" not in caplog.text
    assert "acme/missing" not in str(info.value) and "acme/missing" not in caplog.text
    assert "no repository was found" in caplog.text and "github.com" in caplog.text


def test_a_credentialed_clone_failure_keeps_the_token_out_of_the_message_and_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`is_git_url` accepts userinfo, so the failure path is what keeps a token private.

    git quotes the remote it was handed, credentials and all, in several of its failure
    lines; that is the stderr this test feeds back.
    """

    def failing(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 128, stdout="", stderr=f"fatal: Authentication failed for '{CREDENTIALED_URL}/'\n"
        )

    monkeypatch.setattr(subprocess, "run", failing)
    assert is_git_url(CREDENTIALED_URL)  # unchanged: the managed lane refuses it before cloning
    with caplog.at_level(logging.DEBUG, logger="hippo.ingest.repos"):
        with pytest.raises(RepoError) as info:
            clone_repo(CREDENTIALED_URL, tmp_path / "dest")
    assert "it needs credentials" in str(info.value)
    for part in CREDENTIAL_PARTS:
        assert part not in rendered(info.value) and part not in caplog.text
    assert "git.example.com" in caplog.text  # the host, with the userinfo stripped


def test_clone_really_runs_git_and_reports_unreachable_hosts(tmp_path: Path) -> None:
    # Port 9 (discard) refuses connections immediately, so this is quick and needs no network.
    with pytest.raises(RepoError, match="could not clone"):
        clone_repo("https://127.0.0.1:9/acme/robots.git", tmp_path / "dest", timeout=60)


def test_clone_refuses_a_non_empty_destination(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "old.txt").write_text("x")
    with pytest.raises(RepoError, match="not empty") as info:
        clone_repo("https://github.com/acme/robots", dest)
    assert str(tmp_path) not in str(info.value)  # an absolute path is not a user's to read


# ------------------------------------------------------------ head revision


def commit_all(checkout: Path, message: str = "init") -> None:
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message],
        check=True,
    )


def test_head_revision_reads_the_checkouts_own_head_commit(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "hello.txt").write_text("Hello from git.")
    commit_all(tmp_path)
    expected = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert repos.head_revision(tmp_path) == expected


def test_head_revision_refuses_a_repository_with_no_commit(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(RepoError) as info:
        repos.head_revision(tmp_path)
    assert str(tmp_path) not in str(info.value)


def test_head_revision_never_reads_an_enclosing_repository(tmp_path: Path) -> None:
    """A checkout that is not a repository must not borrow the HEAD of a folder above it.

    The data directory can live inside a git working tree (a development checkout does),
    so git's upward discovery would otherwise hand back the wrong project's commit.
    """
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(["git", "init", "-q", str(outer)], check=True)
    (outer / "hello.txt").write_text("the enclosing project")
    commit_all(outer)
    inner = outer / "sources" / "checkout"
    inner.mkdir(parents=True)
    (inner / "app.py").write_text("def main():\n    return 1\n")
    with pytest.raises(RepoError) as info:
        repos.head_revision(inner)
    assert str(tmp_path) not in str(info.value)


# --------------------------------------------------------------- walking


def make_checkout(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def main():\n    return 1\n")
    (root / "src" / "notes.md").write_text("# Notes\n\nThe app is small.")
    (root / "README").write_text("An extensionless readme.")
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x00\x00")
    (root / "src" / "data.bin").write_bytes(bytes(range(256)))
    (root / ".env").write_text("SECRET=1")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("junk")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "x.txt").write_text("hidden")
    (root / "build").mkdir()
    (root / "build" / "out.txt").write_text("built")


def test_walk_repo_reads_the_right_files(tmp_path: Path) -> None:
    make_checkout(tmp_path)
    docs = walk_repo(tmp_path)
    assert [d.title for d in docs] == ["README", "src/app.py", "src/notes.md"]
    by_title = {d.title: d for d in docs}
    assert by_title["src/app.py"].is_code is True
    assert by_title["src/notes.md"].is_code is False
    assert by_title["README"].text == "An extensionless readme."


def test_walk_repo_skips_big_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_checkout(tmp_path)
    monkeypatch.setattr(readers, "MAX_FILE_BYTES", 24)
    titles = [d.title for d in walk_repo(tmp_path)]
    assert "README" in titles  # exactly 24 bytes: at the limit is still fine
    assert "src/app.py" not in titles  # 25 bytes: over the limit


def test_walk_repo_logs_a_skipped_file_by_its_path_inside_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Review m6: the warning names the file the way the Library does, never where it lives."""
    make_checkout(tmp_path)
    original = readers.read_path

    def unreadable(path, title, budget=None):
        if title == "src/app.py":
            raise readers.ReadError(f"could not read {path}")  # a reader's words can hold the path
        return original(path, title, budget)

    monkeypatch.setattr(readers, "read_path", unreadable)
    with caplog.at_level(logging.WARNING, logger="hippo.ingest.repos"):
        titles = [d.title for d in walk_repo(tmp_path)]
    assert titles == ["README", "src/notes.md"]
    assert "Skipping src/app.py" in caplog.text
    assert str(tmp_path) not in caplog.text and str(tmp_path.resolve()) not in caplog.text


def test_walk_repo_on_a_real_git_checkout(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "hello.txt").write_text("Hello from git.")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        check=True,
    )
    docs = walk_repo(tmp_path)
    assert [d.title for d in docs] == ["hello.txt"]  # nothing from .git/


def test_walk_repo_needs_a_folder(tmp_path: Path) -> None:
    with pytest.raises(RepoError) as info:
        walk_repo(tmp_path / "missing")
    assert str(tmp_path) not in str(info.value)


def test_ignored_dirs_match_the_contract() -> None:
    assert repos.readers.IGNORED_DIRS == {
        ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target", ".idea",
        ".vscode", "vendor",
    }  # fmt: skip
