"""
What is specific to the embedded LadybugDB store: it is a file, it survives a restart,
one process owns it at a time, and `open_store` picks it by default.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from hippo.config import Config, load_config, parse_store_backend
from hippo.store import LadybugStore, Store, StoreLockedError, open_store


def test_data_survives_close_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "memory" / "hippo.lbug"  # the folder does not exist yet: the store creates it
    store = LadybugStore(path)
    source_id = store.create_source("text", "Notes")
    store.update_settings({"damping": 0.7})
    store.set_meta("embed_model", "nomic-embed-text")
    version = store.bump_graph_version()
    store.close()

    again = LadybugStore(path)
    try:
        assert again.get_source(source_id)["name"] == "Notes"
        assert again.get_settings()["damping"] == 0.7
        assert again.get_meta("embed_model") == "nomic-embed-text"
        assert again.graph_version() == version
    finally:
        again.close()


def test_a_second_process_cannot_open_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "hippo.lbug"
    store = LadybugStore(path)
    try:
        code = (
            "import sys\n"
            "from hippo.store import LadybugStore, StoreLockedError\n"
            "try:\n"
            f"    LadybugStore({str(path)!r})\n"
            "except StoreLockedError as exc:\n"
            "    print('locked:', exc)\n"
            "    sys.exit(0)\n"
            "sys.exit(1)\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        assert "already open in another hippo process" in result.stdout
    finally:
        store.close()


def test_the_lock_error_is_a_runtime_error_with_advice() -> None:
    assert issubclass(StoreLockedError, RuntimeError)


def test_ping_bootstraps_once_and_marks_interrupted_jobs(tmp_path: Path) -> None:
    store = LadybugStore(tmp_path / "hippo.lbug")
    try:
        stuck = store.create_source("text", "stuck")
        store.update_source(stuck, status="indexing")
        assert store.ping() is True
        assert store.get_source(stuck)["status"] == "failed"
        # A second ping does nothing new: a source that starts indexing after startup is left alone.
        running = store.create_source("text", "running")
        store.update_source(running, status="indexing")
        assert store.ping() is True
        assert store.get_source(running)["status"] == "indexing"
    finally:
        store.close()


def test_open_store_defaults_to_the_embedded_file_under_data_dir(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path / "data")
    assert config.store_backend == "ladybug"
    assert config.database_path == tmp_path / "data" / "hippo.lbug"
    assert config.store_location == str(tmp_path / "data" / "hippo.lbug")
    store = open_store(config)
    try:
        assert isinstance(store, LadybugStore)
        assert (tmp_path / "data" / "hippo.lbug").exists()
    finally:
        store.close()


def test_open_store_can_be_pointed_at_neo4j() -> None:
    pytest.importorskip("neo4j")
    config = Config(store_backend="neo4j", neo4j_uri="bolt://nowhere.invalid:7687")
    assert config.store_location == "bolt://nowhere.invalid:7687"
    store = open_store(config)  # connecting is lazy, so this succeeds without a server
    try:
        assert isinstance(store, Store)
    finally:
        store.close()


def test_store_env_vars_are_read_and_validated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HIPPO_STORE", "Ladybug")
    monkeypatch.setenv("HIPPO_DB_PATH", str(tmp_path / "elsewhere.lbug"))
    config = load_config()
    assert config.store_backend == "ladybug"
    assert config.database_path == tmp_path / "elsewhere.lbug"
    with pytest.raises(ValueError, match="HIPPO_STORE must be one of"):
        parse_store_backend("sqlite")
