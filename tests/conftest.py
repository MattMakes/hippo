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
