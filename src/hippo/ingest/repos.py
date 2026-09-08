"""
Getting a git repository onto disk and reading its files.

Security first: the URL a user types is handed to `git` as one argument in an
argument list (never through a shell), it must look like a real remote URL
(no local paths, no file://), and it may not start with "-" so it can never be
mistaken for a git option. Cloning is shallow -- `--depth 1` by default, because
usually we only want the current files -- and it has a timeout so a dead host
cannot hang a background job forever. A repo source that reads its git history
asks for a deeper clone: only the commits on disk can be read.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from . import readers
from .readers import Document

log = logging.getLogger(__name__)

# git@github.com:owner/repo.git  (scp-like syntax; no scheme)
SCP_LIKE_RE = re.compile(r"^git@[A-Za-z0-9.\-]+:[A-Za-z0-9._\-/~]+$")
URL_SCHEMES = {"https", "http", "ssh"}


class RepoError(ValueError):
    """Something went wrong with a repository, explained in plain words."""


def is_git_url(url: str) -> bool:
    """Accept https://, http://, ssh:// and git@host:path forms only. Anything local is refused."""
    url = url.strip()
    if not url or any(ch.isspace() for ch in url) or url.startswith("-"):
        return False
    if SCP_LIKE_RE.match(url):
        return True
    parsed = urlparse(url)
    if parsed.scheme not in URL_SCHEMES or not parsed.netloc:
        return False
    return "." in parsed.hostname if parsed.hostname else False


def repo_name(url: str) -> str:
    """'https://github.com/acme/robots.git' -> 'acme/robots'. Used as the source name."""
    path = url.strip().rstrip("/")
    path = path.split(":", 1)[1] if SCP_LIKE_RE.match(path) else urlparse(path).path
    parts = [p for p in path.split("/") if p]
    if parts and parts[-1].endswith(".git"):
        parts[-1] = parts[-1][: -len(".git")]
    return "/".join(parts[-2:]) if parts else url


def clone_repo(url: str, dest: Path, timeout: int = 300, depth: int = 1) -> Path:
    """
    Shallow-clone `url` into `dest`. Raises RepoError with a message a user can act on.

    `depth` is how many commits to fetch. The default of 1 is "the current files only",
    which is what every source wanted until the code graph started reading history: with
    `code_history_depth` set, only the commits that were cloned can be read, so the pipeline
    passes that setting through. A depth below 1 is clamped to 1 -- `--depth 0` is a *full*
    clone, which is the opposite of what "no history" should cost.
    """
    url = url.strip()
    depth = max(1, depth)
    if not is_git_url(url):
        raise RepoError(
            f"'{url}' does not look like a git URL. Use https://host/owner/repo, "
            "ssh://git@host/owner/repo or git@host:owner/repo."
        )
    if dest.exists() and any(dest.iterdir()):
        raise RepoError(f"the folder {dest} already exists and is not empty")
    dest.parent.mkdir(parents=True, exist_ok=True)
    command = ["git", "clone", "--depth", str(depth), "--single-branch", "--", url, str(dest)]
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # never wait for a username/password prompt
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as err:
        raise RepoError("git is not installed on this machine, so repositories cannot be cloned") from err
    except subprocess.TimeoutExpired as err:
        raise RepoError(f"cloning {url} took longer than {timeout} seconds and was stopped") from err
    if result.returncode != 0:
        raise RepoError(_explain_git_failure(url, result.stderr))
    return dest


def _explain_git_failure(url: str, stderr: str) -> str:
    """Translate git's stderr into one friendly sentence, keeping git's last line for the curious."""
    lower = stderr.lower()
    if "could not resolve host" in lower or "could not read from remote" in lower:
        reason = "the host could not be reached"
    elif (
        "authentication failed" in lower
        or "permission denied" in lower
        or "terminal prompts disabled" in lower
    ):
        reason = "it needs credentials (only public repositories can be cloned)"
    elif "not found" in lower or "does not exist" in lower or "repository not found" in lower:
        reason = "no repository was found at that address"
    else:
        reason = "git reported an error"
    last_line = stderr.strip().splitlines()[-1] if stderr.strip() else ""
    return (
        f"could not clone {url}: {reason}. git said: {last_line}"
        if last_line
        else f"could not clone {url}: {reason}."
    )


def walk_repo(root: Path, budget: readers.TextBudget | None = None) -> list[Document]:
    """
    Read every supported text file under `root`. Titles are paths relative to the root.
    `budget` caps the text of the whole checkout (see readers.TextBudget); the default is MAX_TEXT_CHARS.
    """
    root = root.resolve()
    if not root.is_dir():
        raise RepoError(f"{root} is not a folder")
    budget = budget or readers.TextBudget()
    docs: list[Document] = []
    for path in _walk_files(root):
        try:
            docs.extend(readers.read_path(path, path.relative_to(root).as_posix(), budget))
        except readers.TooLarge:
            raise  # the whole repo is over budget; do not treat it as one bad file
        except Exception as err:  # noqa: BLE001 - one unreadable file must not sink the repo
            log.warning("Skipping %s: %s", path, err)
    return docs


def _walk_files(root: Path) -> list[Path]:
    """Files worth reading, in a stable (sorted) order. Skips junk dirs, hidden things, big files, binaries."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in readers.IGNORED_DIRS and not d.startswith("."))
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if filename.startswith(".") or path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_size > readers.MAX_FILE_BYTES:
                continue
            if readers.is_supported(path):
                found.append(path)
    return found
