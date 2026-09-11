"""
Shared pytest fixtures.

* `store`  - chosen by HIPPO_TEST_STORE: `ladybug` (the default: a real embedded LadybugDB in a
             temporary file), `fake` (the in-memory FakeStore) or `neo4j` (a real Neo4j at NEO4J_URI,
             which CI does). Either way it starts empty for every test.
* `ollama` - the rule-based FakeOllama behind the real `Ollama` client class.
* `ctx`    - an AppContext wired to the two above, with a temporary data directory.
* `code_index` - the `code_sample` tree zipped and indexed through the real pipeline, so a test
             can ask questions of a memory that holds a code graph. Yields `(ctx, source_id)`.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import zipfile
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
        # Fixture reset intentionally precedes application bootstrapping. Migration
        # tests may leave an unsupported version behind; normal Store.run must
        # refuse that database, but the next disposable test still needs isolation.
        try:
            real.driver.execute_query("MATCH (n) DETACH DELETE n", database_=real.database)
            # Nodes alone do not reset a disposable database: managed constraints
            # without their migration journal correctly prevent application startup.
            # Drop constraints first, which also removes their backing indexes.
            for catalog, kind in (("CONSTRAINTS", "CONSTRAINT"), ("INDEXES", "INDEX")):
                result = real.driver.execute_query(
                    f"SHOW {catalog} YIELD name RETURN name", database_=real.database
                )
                for record in result.records:
                    name = record["name"].replace("`", "``")
                    real.driver.execute_query(f"DROP {kind} `{name}` IF EXISTS", database_=real.database)
            real.ensure_schema()
            yield real
        finally:
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


def code_sample_zip() -> bytes:
    """
    The fixture tree as an archive a user could upload.

    Member paths are relative to the tree's root with no folder above them, because that is what
    a repository looks like: a root folder would end up in every module qualname and no title
    would match `expected.json`. `expected.json` itself stays out -- it is the spec beside the
    tree, not part of it.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(CODE_SAMPLE_PATH.rglob("*")):
            if path.is_file() and path.name != "expected.json":
                archive.writestr(path.relative_to(CODE_SAMPLE_PATH).as_posix(), path.read_bytes())
    return buffer.getvalue()


def index_code_sample(ctx: AppContext) -> str:
    """Index the fixture tree through the real pipeline (parse, chunk, code graph and all)."""
    from hippo.ingest import pipeline

    source_id = pipeline.add_upload(ctx, "code_sample.zip", code_sample_zip())
    ctx.jobs.wait_all(60)
    source = ctx.store.get_source(source_id)
    assert source["status"] == "ready", source["error"]
    return source_id


def sample_chunks(text: str) -> list:
    """`samples/acme_robotics.md` as one passage per '## ' section."""
    from hippo.hipporag.indexer import Chunk

    chunks = []
    for ordinal, section in enumerate(text.split("## ")[1:]):
        title, _, body = section.partition("\n")
        chunks.append(Chunk(ordinal, title.strip(), body.strip()))
    return chunks


def index_prose_sample(ctx: AppContext) -> str:
    """Index `samples/acme_robotics.md`, the prose corpus every fidelity claim is measured against."""
    from hippo.hipporag.indexer import index_source

    source_id = ctx.store.create_source("sample", "Acme Robotics")
    index_source(ctx.store, ctx.ollama, source_id, sample_chunks(SAMPLE_PATH.read_text()))
    ctx.store.update_source(source_id, status="ready")
    return source_id


@pytest.fixture
def code_index(ctx: AppContext):
    """The fixture tree indexed through the real pipeline with FakeOllama: `(ctx, source_id)`."""
    yield ctx, index_code_sample(ctx)


@pytest.fixture
def mixed_index(ctx: AppContext):
    """
    Prose *and* code in **one** memory: `(ctx, prose_source_id, code_source_id)`.

    Every other "prose behaves as it does today" assertion in the suite runs on a prose-only
    corpus, which is exactly why the two fidelity defects V2.5 found were invisible. The prose goes
    in first, so a test can search before the code arrives and compare.
    """
    prose_source_id = index_prose_sample(ctx)
    code_source_id = index_code_sample(ctx)
    yield ctx, prose_source_id, code_source_id


@pytest.fixture
def git_index(ctx: AppContext, tmp_path, monkeypatch: pytest.MonkeyPatch):
    """
    The fixture tree as a *repository* source, indexed with its history: `(ctx, source_id)`.

    `repos.is_git_url` refuses a local path -- deliberately, so a typed URL can never reach the
    filesystem -- while `git clone` is perfectly happy with one. So the source is created
    directly rather than through `add_repo`, and `clone_repo` is replaced by a real local clone
    that keeps the `depth` it was given. Everything after the clone is the production path:
    `walk_repo`, `extract_code`, `read_history`, the chunker and the indexer.

    `depths` on the fixture records what `clone_repo` was asked for, so a test can check that
    `code_history_depth` really reaches git.
    """
    from hippo.ingest import pipeline, repos

    checkout = make_code_checkout(tmp_path / "origin")
    depths: list[int] = []

    def clone_locally(url: str, dest: Path, timeout: int = 300, depth: int = 1) -> Path:
        depths.append(depth)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "-q", "--depth", str(depth), "--single-branch", "--", url, str(dest)],
            check=True,
            env=git_env(),
        )
        return dest

    monkeypatch.setattr(repos, "clone_repo", clone_locally)
    source_id = ctx.store.create_source("repo", "code_sample", {"url": f"file://{checkout}"})
    pipeline.source_dir(ctx, source_id).mkdir(parents=True, exist_ok=True)
    pipeline.run_indexing(ctx, source_id)
    source = ctx.store.get_source(source_id)
    assert source["status"] == "ready", source["error"]
    yield ctx, source_id, depths


def pytest_addoption(parser: pytest.Parser) -> None:
    """
    `--update-expected` rewrites `tests/fixtures/code_sample/expected.json` from this run.

    That file is the spec for the code graph, so a regeneration diff is a change to what hippo
    promises about a repository and is read like a source change. Never run it to make a red
    build green, and never in CI -- `pytest_configure` refuses it there.
    """
    parser.addoption(
        "--update-expected",
        action="store_true",
        default=False,
        help="rewrite tests/fixtures/code_sample/expected.json from this run, then read the diff",
    )


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--update-expected") and os.environ.get("CI"):
        raise pytest.UsageError(
            "--update-expected is refused in CI: expected.json is the spec the tests argue with, "
            "so it is regenerated on a developer's machine and reviewed as a change."
        )
