"""
From "here is something to remember" to "it is in the graph".

Every way of adding memory (pasted text, an uploaded file or zip, a git URL,
the built-in sample) does the same three things:

1. create a Source row in the store (status 'queued')
2. save the raw bytes under <data_dir>/sources/<source_id>/ so we can re-read
   them later (reindex) and show where a passage came from
3. start a background job "index:<source_id>" that reads the files, chunks
   them, and hands the chunks to hipporag.indexer.index_source

While the job runs, the Source row is the progress bar: status goes
'reading' -> 'indexing' -> 'ready' (or 'failed' with the error text kept),
and stage/progress_done/progress_total follow the indexer's callbacks.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from ..context import AppContext
from ..hipporag.indexer import index_source
from . import readers, repos
from .chunker import chunk_documents
from .readers import Document

log = logging.getLogger(__name__)

SAMPLE_FILE = "acme_robotics.md"
SAMPLE_NAME = "Acme Robotics (sample)"
TEXT_FILE = "text.md"  # pasted text is stored as markdown
REPO_DIR = "repo"


# ------------------------------------------------------------- adding


def add_text(ctx: AppContext, name: str, text: str) -> str:
    """Remember a pasted text. The name is what the library shows."""
    name = name.strip() or "Untitled text"
    if not text.strip():
        raise ValueError("the text is empty")
    source_id = ctx.store.create_source("text", name, {"file": TEXT_FILE, "chars": len(text)})
    _write_bytes(source_dir(ctx, source_id) / TEXT_FILE, text.encode("utf-8"))
    start_indexing(ctx, source_id)
    return source_id


def add_upload(ctx: AppContext, filename: str, data: bytes) -> str:
    """Remember an uploaded file. A .zip becomes an 'archive' source; anything else a 'file'."""
    safe_name = _safe_filename(filename)
    if not data:
        raise ValueError(f"{safe_name} is empty")
    is_zip = safe_name.lower().endswith(".zip")
    if not is_zip and not readers.is_supported_name(safe_name):
        if Path(safe_name).suffix or readers.is_probably_binary(data):
            raise ValueError(
                f"{safe_name} is not a supported file type (text, code, pdf, docx, epub, html, zip)"
            )
    kind = "archive" if is_zip else "file"
    source_id = ctx.store.create_source(kind, safe_name, {"file": safe_name, "bytes": len(data)})
    _write_bytes(source_dir(ctx, source_id) / safe_name, data)
    start_indexing(ctx, source_id)
    return source_id


def add_repo(ctx: AppContext, url: str) -> str:
    """Remember a public git repository. Cloning happens inside the background job."""
    url = url.strip()
    if not repos.is_git_url(url):
        raise repos.RepoError(
            f"'{url}' does not look like a git URL. Use https://host/owner/repo, "
            "ssh://git@host/owner/repo or git@host:owner/repo."
        )
    source_id = ctx.store.create_source("repo", repos.repo_name(url), {"url": url})
    source_dir(ctx, source_id).mkdir(parents=True, exist_ok=True)
    start_indexing(ctx, source_id)
    return source_id


def add_sample(ctx: AppContext) -> str:
    """Load samples/acme_robotics.md, the tiny corpus used by the docs and tests."""
    sample = find_sample_path()
    source_id = ctx.store.create_source("sample", SAMPLE_NAME, {"file": SAMPLE_FILE})
    _write_bytes(source_dir(ctx, source_id) / SAMPLE_FILE, sample.read_bytes())
    start_indexing(ctx, source_id)
    return source_id


def find_sample_path() -> Path:
    """The sample lives in the repo's samples/ folder; in Docker it is copied to /app/samples."""
    candidates = [
        Path(__file__).resolve().parents[3] / "samples" / SAMPLE_FILE,  # src/hippo/ingest -> repo root
        Path.cwd() / "samples" / SAMPLE_FILE,
        Path("/app/samples") / SAMPLE_FILE,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"samples/{SAMPLE_FILE} was not found next to the hippo code")


# ----------------------------------------------------------- indexing


def start_indexing(ctx: AppContext, source_id: str) -> bool:
    """Start the background job for one source. False if it is already running."""
    return ctx.jobs.start(f"index:{source_id}", lambda: run_indexing(ctx, source_id))


def run_indexing(ctx: AppContext, source_id: str) -> None:
    """The job body: read -> chunk -> index. Runs in a thread; reports through the Source row."""
    source = ctx.store.get_source(source_id)
    if source is None:
        log.warning("index job: source %s no longer exists", source_id)
        return
    try:
        _set_status(ctx, source_id, "reading", "reading files")
        docs = read_source(ctx, source)
        config = ctx.config
        chunks = chunk_documents(docs, config.chunk_size_chars, config.chunk_overlap_chars)
        if not chunks:
            raise ValueError("no readable text was found in this source")

        _set_status(ctx, source_id, "indexing", "indexing", total=len(chunks))
        counts = index_source(
            ctx.store,
            ctx.ollama,
            source_id,
            chunks,
            synonymy_threshold=float(ctx.store.get_settings()["synonymy_threshold"]),
            workers=config.openie_workers,
            on_progress=lambda stage, done, total: ctx.store.update_source(
                source_id, stage=stage, progress_done=done, progress_total=total
            ),
        )
        meta = dict(source.get("meta") or {})
        meta.update({"chunks": len(chunks), "documents": len(docs), "counts": counts})
        ctx.store.update_source(
            source_id,
            status="ready",
            stage="ready",
            progress_done=len(chunks),
            progress_total=len(chunks),
            error=None,
            meta_json=json.dumps(meta),
        )
    except Exception as err:  # noqa: BLE001 - whatever went wrong, the user must see it in the UI
        log.exception("Indexing source %s failed", source_id)
        ctx.store.update_source(
            source_id, status="failed", stage="failed", error=f"{type(err).__name__}: {err}"
        )


def read_source(ctx: AppContext, source: dict[str, Any]) -> list[Document]:
    """Read the saved files of a source into Documents, according to its kind."""
    kind = source["kind"]
    folder = source_dir(ctx, source["id"])
    meta = source.get("meta") or {}
    if kind == "text":
        text = (folder / meta.get("file", TEXT_FILE)).read_text(encoding="utf-8")
        return [Document(title=source["name"], text=text.strip(), path=str(folder), is_code=False)]
    if kind in ("file", "sample"):
        return readers.read_file(folder / meta["file"])
    if kind == "archive":
        return readers.read_zip(folder / meta["file"], meta["file"])
    if kind == "repo":
        ctx.store.update_source(source["id"], stage="cloning")
        checkout = folder / REPO_DIR
        shutil.rmtree(checkout, ignore_errors=True)  # a reindex should see the latest commit
        repos.clone_repo(meta["url"], checkout)
        return repos.walk_repo(checkout)
    raise ValueError(f"unknown source kind '{kind}'")


# -------------------------------------------------- deleting, reindexing


def delete_source(ctx: AppContext, source_id: str) -> None:
    """Forget a source: its passages, orphaned entities/facts, and its files on disk."""
    ctx.store.delete_source(source_id)
    ctx.store.bump_graph_version()
    shutil.rmtree(source_dir(ctx, source_id), ignore_errors=True)


def reindex(ctx: AppContext, source_id: str) -> bool:
    """Drop this source's passages and index its saved files again. False if a job is already running."""
    if ctx.jobs.is_running(f"index:{source_id}") or ctx.store.get_source(source_id) is None:
        return False
    _clear_passages(ctx, source_id)
    ctx.store.update_source(
        source_id, status="queued", stage="queued", progress_done=0, progress_total=0, error=None
    )
    return start_indexing(ctx, source_id)


def _clear_passages(ctx: AppContext, source_id: str) -> None:
    """Remove the passages of a source while keeping the Source row (see docs/CONTRACTS.md deviations)."""
    clear = getattr(ctx.store, "delete_passages_for_source", None)
    if clear is not None:
        clear(source_id)
    else:
        # Passage ids are content hashes, so re-indexing unchanged text overwrites the same nodes.
        # Passages whose text changed since last time will linger until the store learns to delete them.
        log.warning("store has no delete_passages_for_source; stale passages may remain after reindex")
    ctx.store.bump_graph_version()


# -------------------------------------------------------------- helpers


def source_dir(ctx: AppContext, source_id: str) -> Path:
    return Path(ctx.config.data_dir) / "sources" / source_id


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _safe_filename(filename: str) -> str:
    """Keep only the base name; refuse anything that could walk out of the source folder."""
    name = Path(filename.replace("\\", "/")).name.strip()
    if name in ("", ".", ".."):
        raise ValueError("the upload needs a file name")
    return name


def _set_status(ctx: AppContext, source_id: str, status: str, stage: str, *, total: int = 0) -> None:
    ctx.store.update_source(
        source_id, status=status, stage=stage, progress_done=0, progress_total=total, error=None
    )
