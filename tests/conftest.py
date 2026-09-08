"""
Shared pytest fixtures.

* `store`  - chosen by HIPPO_TEST_STORE: `ladybug` (the default: a real embedded LadybugDB in a
             temporary file), `fake` (the in-memory FakeStore) or `neo4j` (a real Neo4j at NEO4J_URI,
             which CI does). Either way it starts empty for every test.
* `ollama` - the rule-based FakeOllama behind the real `Ollama` client class.
* `ctx`    - an AppContext wired to the two above, with a temporary data directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from hippo.config import Config  # noqa: E402
from hippo.context import AppContext  # noqa: E402
from hippo.ollama import Ollama  # noqa: E402
from tests.fakes.fake_ollama import FakeOllama  # noqa: E402
from tests.fakes.fake_store import FakeStore  # noqa: E402

SAMPLE_PATH = ROOT / "samples" / "acme_robotics.md"
CODE_SAMPLE_PATH = ROOT / "tests" / "fixtures" / "code_sample"


def code_sample_docs(root: Path = CODE_SAMPLE_PATH) -> list:
    """
    The `code_sample` tree as `Document`s, read the way a repo source is read: one document
    per file, titled by its repo-relative path. `expected.json` is the spec beside the tree,
    not part of it.
    """
    from hippo.ingest import readers

    docs = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "expected.json":
            docs.extend(readers.read_path(path, path.relative_to(root).as_posix()))
    return docs


# ------------------------------------------------- the fixture tree, as a git repository
#
# A nested `.git` cannot be checked in, so the history the code graph reads is replayed at
# test time from the same tree `code_sample_docs` reads. Three commits, exactly as PLAN.md's
# test fixture plan lists them:
#
#   0  everything except `place`'s and `save`'s final bodies, and without tsapp/index.ts
#   1  `place` gets its final body
#   2  `save` gets its final body, and tsapp/index.ts is added
#
# so HEAD is the fixture byte for byte and `expected.json`'s pinned line numbers hold.
#
# Identity and dates are pinned, and every git call runs with the user's global and system
# config switched off, so the SHAs are the same on every machine -- which is belt and braces
# for S2.17's real rule that nothing is ever keyed on a SHA.

CODE_CHECKOUT_IDENTITY = ("Hippo Fixture", "fixture@hippo.test")
CODE_CHECKOUT_DATES = (
    "2024-01-01T09:00:00+00:00",
    "2024-01-02T09:00:00+00:00",
    "2024-01-03T09:00:00+00:00",
)
# Kept under 80 characters on purpose: a commit passage's `extract_text` is the message, and
# the MIN_OPENIE_DOC_CHARS rule then skips OpenIE for it, so the fixture's LLM call count
# stays a function of its files alone.
CODE_CHECKOUT_SUBJECTS = (
    "Add the order service",
    "Total, invoice and log in place",
    "Raise on save, add the ts app",
)

# The two edits, as (final text, earlier text). Written as replacements against the checked-in
# file rather than as whole copies, so a change to the fixture cannot silently leave a stale
# duplicate behind: `_earlier` raises if the final text is not there exactly once.
_PLACE_FINAL = """\
        amount = billing.total(order)
        try: invoice(order)
        except OrderError: raise ValueError("bad order")
        self.log(os.path.join("a", "b"))
        print(amount)
        return amount
"""
_PLACE_EARLIER = """\
        amount = billing.total(order)
        return amount
"""
_SAVE_FINAL = """\
        self.run("INSERT INTO orders (id, total) VALUES (?, ?)")
        raise OrderError("nope")
"""
_SAVE_EARLIER = """\
        self.run("INSERT INTO orders (id, total) VALUES (?, ?)")
"""


def git_env(**extra: str) -> dict[str, str]:
    """
    The environment every git call in the tests runs under.

    The user's global and system config are switched off: a `diff.noprefix`, a
    `core.excludesFile` or a commit template on the developer's machine would otherwise
    change what the tests see, and CI would disagree with a laptop for reasons no one
    would find. `GIT_DIR`/`GIT_WORK_TREE` are dropped for the same reason -- pytest can
    be run from inside a git hook.
    """
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    env.update(extra)
    for leaked in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(leaked, None)
    return env


def make_code_checkout(tmp_path) -> Path:
    """
    The `code_sample` tree as a real three-commit git repository, returned as its path.

    Modelled on `make_checkout` in `tests/unit/test_ingest_repos.py`, the only other place
    in the suite that runs git for real. `expected.json` is left out: it is the spec beside
    the tree, not part of it, and `.json` is a supported extension, so a copy would turn up
    as a passage the moment the checkout is indexed.
    """
    checkout = Path(tmp_path) / "checkout"
    shutil.copytree(CODE_SAMPLE_PATH, checkout, ignore=shutil.ignore_patterns("expected.json"))

    orders = checkout / "pyapp" / "orders.py"
    index_ts = checkout / "tsapp" / "index.ts"
    final_orders, final_index = orders.read_text(), index_ts.read_text()
    index_ts.unlink()

    subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True, env=git_env())
    orders.write_text(
        _earlier(_earlier(final_orders, _PLACE_FINAL, _PLACE_EARLIER), _SAVE_FINAL, _SAVE_EARLIER)
    )
    _commit(checkout, 0)
    orders.write_text(_earlier(final_orders, _SAVE_FINAL, _SAVE_EARLIER))
    _commit(checkout, 1)
    orders.write_text(final_orders)
    index_ts.write_text(final_index)
    _commit(checkout, 2)
    return checkout


def _earlier(text: str, final: str, earlier: str) -> str:
    """Roll one edit back. Raises if the fixture moved under us rather than editing nothing."""
    if text.count(final) != 1:
        raise AssertionError(f"tests/fixtures/code_sample no longer contains exactly one:\n{final}")
    return text.replace(final, earlier)


def _commit(checkout: Path, ordinal: int) -> None:
    """Commit the working tree as commit `ordinal`, with its pinned identity and date."""
    name, email = CODE_CHECKOUT_IDENTITY
    date = CODE_CHECKOUT_DATES[ordinal]
    env = git_env(
        GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_AUTHOR_DATE=date,
        GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email, GIT_COMMITTER_DATE=date,
    )  # fmt: skip
    subprocess.run(["git", "-C", str(checkout), "add", "-A"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "-q", "-m", CODE_CHECKOUT_SUBJECTS[ordinal]],
        check=True,
        env=env,
    )


def store_backend() -> str:
    """Which store the `store` fixture builds. NEO4J_URI alone also means neo4j, as it did before."""
    chosen = os.environ.get("HIPPO_TEST_STORE", "").strip().lower()
    if chosen:
        return chosen
    return "neo4j" if os.environ.get("NEO4J_URI") else "ladybug"


@pytest.fixture
def store(tmp_path):
    backend = store_backend()
    if backend == "neo4j":
        from hippo.store import Store

        real = Store(
            os.environ["NEO4J_URI"],
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "hippo-password"),
        )
        real.run("MATCH (n) DETACH DELETE n")
        real.ensure_schema()
        yield real
        real.close()
    elif backend == "ladybug":
        from hippo.store.ladybug import LadybugStore

        embedded = LadybugStore(tmp_path / "hippo.lbug")
        yield embedded
        embedded.close()
    elif backend == "fake":
        yield FakeStore()
    else:
        raise ValueError(f"HIPPO_TEST_STORE must be ladybug, fake or neo4j, not {backend!r}")


@pytest.fixture
def fake_ollama() -> FakeOllama:
    return FakeOllama()


@pytest.fixture
def ollama(fake_ollama: FakeOllama) -> Ollama:
    return Ollama("http://fake-ollama", "qwen3:8b", "nomic-embed-text", client=fake_ollama.client())


@pytest.fixture
def ctx(store, ollama, tmp_path) -> AppContext:
    config = Config(data_dir=tmp_path / "data", openie_workers=2)
    return AppContext(config=config, store=store, ollama=ollama)


@pytest.fixture
def sample_text() -> str:
    return SAMPLE_PATH.read_text()
