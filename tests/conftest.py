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
