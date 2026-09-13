"""
Every LadybugDB store opens with a bounded buffer pool.

real_ladybug 0.15.3's `Database(buffer_pool_size=0)` means "about 80% of system memory", so a
store opened without a size could grow toward tens of gigabytes during one long build. These
tests check that a size reaches the driver on every open (the default rule, an override and the
pytest cap), that zero is refused rather than quietly meaning 80% again, and that a real managed
prose build still publishes on a small pool.

They open real Ladybug files under `tmp_path` whatever HIPPO_TEST_STORE says, except the one
test that inspects the `store` fixture itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
from threading import local
from types import SimpleNamespace

import httpx
import pytest
import real_ladybug

from hippo.access import EVERYTHING, Principal
from hippo.config import Config, load_config
from hippo.context import AppContext
from hippo.ingest import prose_generation
from hippo.knowledge import model as k
from hippo.knowledge.build_authority import BuildActor
from hippo.knowledge.query_access import query_session
from hippo.knowledge.raw_artifacts import RawArtifactStore
from hippo.ollama import Ollama
from hippo.store import ladybug, open_store
from hippo.store.ladybug import LadybugStore
from tests.unit.test_prose_generation import Runtime, build

MiB = 2**20
GiB = 2**30
SETTING = "HIPPO_LADYBUG_BUFFER_POOL_BYTES"


@pytest.fixture
def opens(monkeypatch):
    """The keyword arguments of every `real_ladybug.Database(...)` call, still opened for real."""
    calls: list[dict] = []
    real = real_ladybug.Database

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(real_ladybug, "Database", spy)
    return calls


def sizes(opens: list[dict]) -> list[int | None]:
    return [call.get("buffer_pool_size") for call in opens]


# ------------------------------------------------------------------ the size reaching the driver


def test_an_explicit_size_reaches_the_driver(tmp_path, opens):
    LadybugStore(tmp_path / "hippo.lbug", buffer_pool_bytes=192 * MiB).close()
    assert sizes(opens) == [192 * MiB]


def test_a_store_opened_without_a_size_passes_the_default_to_the_driver(tmp_path, opens, monkeypatch):
    monkeypatch.setattr(ladybug, "default_buffer_pool_bytes", lambda: 160 * MiB)
    LadybugStore(tmp_path / "hippo.lbug").close()
    assert sizes(opens) == [160 * MiB]


@pytest.mark.parametrize("size", [0, -1])
def test_a_zero_or_negative_size_is_refused_before_the_file_is_touched(tmp_path, opens, size):
    path = tmp_path / "nested" / "hippo.lbug"
    with pytest.raises(ValueError, match="positive number of bytes"):
        LadybugStore(path, buffer_pool_bytes=size)
    assert opens == []
    assert not path.parent.exists()


def test_open_store_passes_the_configured_size(tmp_path, opens):
    open_store(Config(data_dir=tmp_path / "data", ladybug_buffer_pool_bytes=144 * MiB)).close()
    assert sizes(opens) == [144 * MiB]


def test_open_store_refuses_a_configured_zero(tmp_path, opens):
    with pytest.raises(ValueError, match="positive number of bytes"):
        open_store(Config(data_dir=tmp_path / "data", ladybug_buffer_pool_bytes=0))
    assert opens == []


# ------------------------------------------------------------------ the default rule


@pytest.mark.parametrize(
    ("physical", "expected"),
    [(1 * GiB, 256 * MiB), (8 * GiB, 2 * GiB), (16 * GiB, 4 * GiB), (128 * GiB, 4 * GiB)],
)
def test_the_default_is_a_quarter_of_physical_memory_up_to_4_gib(physical, expected):
    assert ladybug.bounded_buffer_pool_bytes(physical) == expected


def test_unknown_physical_memory_falls_back_to_the_4_gib_cap(monkeypatch):
    def unavailable(name):
        raise ValueError(f"unrecognized configuration name {name}")

    monkeypatch.setattr(ladybug.os, "sysconf", unavailable)
    assert ladybug.physical_memory_bytes() is None
    assert ladybug.bounded_buffer_pool_bytes(None) == 4 * GiB


@pytest.mark.skipif(not hasattr(os, "sysconf"), reason="physical memory is read through os.sysconf")
def test_a_process_outside_pytest_opens_with_the_default_rule(tmp_path):
    """conftest caps every store under pytest, so the production default is checked in a clean process."""
    script = (
        "import sys\n"
        "from hippo.store.ladybug import LadybugStore\n"
        "store = LadybugStore(sys.argv[1])\n"
        "print(store._db.buffer_pool_size)\n"
        "store.close()\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "hippo.lbug")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    physical = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    assert int(done.stdout.strip()) == min(physical // 4, 4 * GiB)


# ------------------------------------------------------------------ the setting


def test_the_setting_is_a_byte_count_and_unset_means_the_default(monkeypatch):
    monkeypatch.delenv(SETTING, raising=False)
    assert load_config().ladybug_buffer_pool_bytes is None
    monkeypatch.setenv(SETTING, "536870912")
    assert load_config().ladybug_buffer_pool_bytes == 512 * MiB


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "lots", "4GiB", " "])
def test_the_setting_refuses_anything_but_a_positive_byte_count(monkeypatch, value):
    monkeypatch.setenv(SETTING, value)
    with pytest.raises(ValueError, match=SETTING):
        load_config()


# ------------------------------------------------------------------ the pytest cap


def test_the_store_fixture_is_capped_at_256_mib(store):
    if not isinstance(store, LadybugStore):
        pytest.skip("the cap is a Ladybug buffer pool")
    assert store._db.buffer_pool_size == 256 * MiB


def test_a_store_a_test_opens_itself_is_capped_at_256_mib(tmp_path):
    store = LadybugStore(tmp_path / "hippo.lbug")
    try:
        assert store._db.buffer_pool_size == 256 * MiB
    finally:
        store.close()


def test_the_pytest_cap_never_overrides_an_explicit_size(tmp_path, opens):
    LadybugStore(tmp_path / "keyword.lbug", buffer_pool_bytes=1 * GiB).close()
    open_store(Config(data_dir=tmp_path / "data", ladybug_buffer_pool_bytes=512 * MiB)).close()
    assert sizes(opens) == [1 * GiB, 512 * MiB]


# ------------------------------------------------------------------ a real build on a small pool


def test_a_managed_prose_build_publishes_on_a_small_pool(tmp_path):
    # Half the pytest cap. The pool has a floor: on real_ladybug 0.15.3 this build fails at 80 MiB
    # ("the buffer pool is full") before any passage is written, and publishes from 96 MiB up.
    store = LadybugStore(tmp_path / "hippo.lbug", buffer_pool_bytes=128 * MiB)
    try:
        store.ensure_roles()
        user = store.create_user("builder", "password", "individual")
        source = store.create_source("text", "Notes", {"file": "notes.md"}, owner_id=user)
        store.put_knowledge(
            k.WorkspaceMembership(
                workspace_id=store.get_source(source)["workspace_id"],
                principal_id=user,
                mapping_authority="local",
                enabled=True,
                policy_epoch=1,
            )
        )
        store.set_meta("reviewed_mapping_authorities", ["local"])
        runtime = Runtime(store, local())
        ollama = Ollama(
            "http://local-model",
            "chat:latest",
            "embed:latest",
            num_ctx=8192,
            client=httpx.Client(base_url="http://local-model", transport=httpx.MockTransport(runtime.handle)),
        )
        ctx = AppContext(
            config=Config(data_dir=tmp_path / "data", openie_workers=2), store=store, ollama=ollama
        )
        w = SimpleNamespace(
            module=prose_generation,
            ctx=ctx,
            source=source,
            actor=BuildActor.reader(Principal.for_user(store.get_user(user), store.get_role("individual"))),
            raw=RawArtifactStore(tmp_path / "raw", max_object_bytes=2_000_000),
        )

        result = build(w)

        assert store._db.buffer_pool_size == 128 * MiB
        assert store.validate_generation_seal(result.generation_id).ready
        with query_session(ctx, EVERYTHING, structural=True) as session:
            assert any(row.text == "ACME builds Robot." for row in session.graph.original_citations)
    finally:
        store.close()
