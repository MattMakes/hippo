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

Two rules keep the graph consistent while jobs run (see also
hipporag/indexer.py, GRAPH_WRITE_LOCK):

* Deleting or re-indexing a source ends with `remove_orphans`, which drops
  every entity/fact with no link. An index job that is between "entity
  written" and "entity linked" would lose its work, so delete and reindex
  refuse with `Busy` while any *other* index job runs, and take the write
  lock so they cannot overlap with a job's write phase either.
* Deleting a source whose own job is running cancels that job first and
  waits for it to stop. If the row is gone by the time a job finishes
  (whatever the reason), the job sweeps orphans itself.

Sizes are capped in one place, here, so the web forms, the JSON API and the
MCP tool all get the same limits: bytes per upload, characters of text per
source, and passages per source.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from ..context import AppContext
from ..hipporag import openie
from ..hipporag.indexer import GRAPH_WRITE_LOCK, index_source
from . import readers, repos
from .chunker import chunk_documents
from .readers import Document, TextBudget, TooLarge

log = logging.getLogger(__name__)

SAMPLE_FILE = "acme_robotics.md"
SAMPLE_NAME = "Acme Robotics (sample)"
TEXT_FILE = "text.md"  # pasted text is stored as markdown
REPO_DIR = "repo"

# Defaults for the limits, used when Config does not have the fields (HIPPO_MAX_UPLOAD_BYTES,
# HIPPO_MAX_TEXT_CHARS) yet. One upload or pasted text: 50 MB. Text per source: see readers.
DEFAULT_MAX_UPLOAD_BYTES = 50_000_000
DEFAULT_MAX_TEXT_CHARS = readers.MAX_TEXT_CHARS
# Passages per source. 20 M chars / 1500 is ~13,000 passages; anything past this would keep
# the OpenIE workers busy for days and starve every other source.
MAX_CHUNKS = 20_000

CANCEL_WAIT_SECONDS = 60  # how long delete_source waits for the source's own job to stop


class Busy(ValueError):
    """Another source is being indexed; deleting or re-indexing now could damage its graph. Try again later."""


# ------------------------------------------------------------- adding


def add_text(ctx: AppContext, name: str, text: str) -> str:
    """Remember a pasted text. The name is what the library shows."""
    name = name.strip() or "Untitled text"
    if not text.strip():
        raise ValueError("the text is empty")
    data = text.encode("utf-8")
    _check_upload_size(ctx, name, len(data))
    source_id = ctx.store.create_source("text", name, {"file": TEXT_FILE, "chars": len(text)})
    _write_bytes(source_dir(ctx, source_id) / TEXT_FILE, data)
    start_indexing(ctx, source_id)
    return source_id


def add_upload(ctx: AppContext, filename: str, data: bytes) -> str:
    """Remember an uploaded file. A .zip becomes an 'archive' source; anything else a 'file'."""
    safe_name = _safe_filename(filename)
    if not data:
        raise ValueError(f"{safe_name} is empty")
    _check_upload_size(ctx, safe_name, len(data))
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


# -------------------------------------------------------------- limits


def max_upload_bytes(ctx: AppContext) -> int:
    return int(ctx.config.max_upload_bytes)


def max_text_chars(ctx: AppContext) -> int:
    return int(ctx.config.max_text_chars)


def _check_upload_size(ctx: AppContext, name: str, size: int) -> None:
    limit = max_upload_bytes(ctx)
    if size > limit:
        raise ValueError(
            f"{name} is too big ({size:,} bytes); the limit is {limit:,} bytes (HIPPO_MAX_UPLOAD_BYTES). "
            "Split it into smaller parts."
        )


# ----------------------------------------------------------- indexing


def start_indexing(ctx: AppContext, source_id: str) -> bool:
    """Start the background job for one source. False if it is already running."""
    return ctx.jobs.start(f"index:{source_id}", lambda: run_indexing(ctx, source_id))


def job_key(source_id: str) -> str:
    return f"index:{source_id}"


def run_indexing(ctx: AppContext, source_id: str) -> None:
    """
    The job body: read -> chunk -> index. Runs in a thread; reports through the Source row.

    Whatever happens, it ends in one of three ways: 'ready', 'failed' (with the passages it
    wrote cleared, so nothing half-done stays behind), or cancelled (someone deleted the source
    while it ran). If the Source row is gone by the end, it sweeps the orphans it may have left.
    """
    source = ctx.store.get_source(source_id)
    if source is None:
        log.warning("index job: source %s no longer exists", source_id)
        return
    key = job_key(source_id)
    try:
        _read_chunk_index(ctx, source, should_stop=lambda: ctx.jobs.is_cancelled(key))
    except openie.Stopped as err:
        log.info("Indexing source %s was cancelled: %s", source_id, err)
        if not _sweep_if_deleted(ctx, source_id):
            _clear_passages(ctx, source_id)
            ctx.store.update_source(
                source_id,
                status="failed",
                stage="cancelled",
                error="cancelled before it finished; use Reindex to run it again",
            )
    except Exception as err:  # noqa: BLE001 - whatever went wrong, the user must see it in the UI
        log.exception("Indexing source %s failed", source_id)
        if not _sweep_if_deleted(ctx, source_id):
            _clear_passages(ctx, source_id)
            ctx.store.update_source(
                source_id, status="failed", stage="failed", error=f"{type(err).__name__}: {err}"
            )
    else:
        _sweep_if_deleted(ctx, source_id)


def _read_chunk_index(ctx: AppContext, source: dict[str, Any], *, should_stop) -> None:
    """The happy path of run_indexing, up to and including the 'ready' status."""
    source_id = source["id"]
    _set_status(ctx, source_id, "reading", "reading files")
    docs = read_source(ctx, source)
    config = ctx.config
    chunks = chunk_documents(docs, config.chunk_size_chars, config.chunk_overlap_chars)
    if not chunks:
        raise ValueError("no readable text was found in this source")
    if len(chunks) > MAX_CHUNKS:
        raise TooLarge(
            f"too large: this source makes {len(chunks):,} passages; the limit is {MAX_CHUNKS:,}. "
            "Split it into smaller sources."
        )

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
        should_stop=should_stop,
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


def _sweep_if_deleted(ctx: AppContext, source_id: str) -> bool:
    """
    True (after cleaning up) when the Source row is gone. delete_source already removed the
    passages, so any entity or fact this job wrote after that has no link: an orphan.
    """
    if ctx.store.get_source(source_id) is not None:
        return False
    log.info("Source %s was deleted while its index job ran; sweeping what the job left", source_id)
    with GRAPH_WRITE_LOCK:
        ctx.store.remove_orphans()
    ctx.store.bump_graph_version()
    return True


def read_source(ctx: AppContext, source: dict[str, Any]) -> list[Document]:
    """Read the saved files of a source into Documents, according to its kind."""
    kind = source["kind"]
    folder = source_dir(ctx, source["id"])
    meta = source.get("meta") or {}
    budget = TextBudget(limit=max_text_chars(ctx))
    if kind == "text":
        text = (folder / meta.get("file", TEXT_FILE)).read_text(encoding="utf-8").strip()
        budget.add(len(text), source["name"])
        return [Document(title=source["name"], text=text, path=str(folder), is_code=False)]
    if kind in ("file", "sample"):
        return readers.read_file(folder / meta["file"], budget)
    if kind == "archive":
        return readers.read_zip(folder / meta["file"], meta["file"], budget)
    if kind == "repo":
        ctx.store.update_source(source["id"], stage="cloning")
        checkout = folder / REPO_DIR
        shutil.rmtree(checkout, ignore_errors=True)  # a reindex should see the latest commit
        repos.clone_repo(meta["url"], checkout)
        return repos.walk_repo(checkout, budget)
    raise ValueError(f"unknown source kind '{kind}'")


# -------------------------------------------------- deleting, reindexing


def delete_source(ctx: AppContext, source_id: str) -> None:
    """
    Forget a source: its passages, orphaned entities/facts, and its files on disk.

    Raises Busy while another source is being indexed. If this source's own job is running,
    it is cancelled and given a moment to stop first.
    """
    key = job_key(source_id)
    _refuse_if_indexing(ctx, except_key=key)
    if ctx.jobs.cancel(key) and not ctx.jobs.wait(key, timeout=CANCEL_WAIT_SECONDS):
        # Probably stuck in one long model call. Go ahead: the job sweeps up after itself
        # when it finds the row gone (see run_indexing).
        log.warning(
            "index job for %s did not stop within %ss; deleting anyway", source_id, CANCEL_WAIT_SECONDS
        )
    with GRAPH_WRITE_LOCK:
        ctx.store.delete_source(source_id)
    ctx.store.bump_graph_version()
    shutil.rmtree(source_dir(ctx, source_id), ignore_errors=True)


def reindex_all(ctx: AppContext) -> int:
    """
    Forget every source's passages and index them all again, one background job per source.
    This is the way back after changing HIPPO_EMBED_MODEL: old and new vectors must never mix.
    Raises Busy while anything is being indexed.
    """
    _refuse_if_indexing(ctx)
    # Clear every source first, then start the jobs: once a job runs, no more orphan sweeps.
    sources = ctx.store.list_sources()
    for source in sources:
        _prepare_reindex(ctx, source["id"])
    return sum(1 for source in sources if start_indexing(ctx, source["id"]))


def reindex(ctx: AppContext, source_id: str) -> bool:
    """
    Drop this source's passages and index its saved files again.
    False if this source's job is already running or the source does not exist;
    Busy while another source is being indexed.
    """
    if ctx.jobs.is_running(job_key(source_id)) or ctx.store.get_source(source_id) is None:
        return False
    _refuse_if_indexing(ctx)
    _prepare_reindex(ctx, source_id)
    return start_indexing(ctx, source_id)


def _prepare_reindex(ctx: AppContext, source_id: str) -> None:
    _clear_passages(ctx, source_id)
    ctx.store.update_source(
        source_id, status="queued", stage="queued", progress_done=0, progress_total=0, error=None
    )


def _refuse_if_indexing(ctx: AppContext, except_key: str | None = None) -> None:
    """Raise Busy when an index job (other than `except_key`) is running."""
    busy = [k for k in ctx.jobs.running_keys() if k.startswith("index:") and k != except_key]
    if busy:
        raise Busy(
            f"wait for indexing to finish: {len(busy)} source(s) are being indexed, "
            "and deleting or re-indexing now could damage their graph"
        )


def _clear_passages(ctx: AppContext, source_id: str) -> None:
    """Remove the passages of a source while keeping the Source row, so it can be indexed again."""
    with GRAPH_WRITE_LOCK:  # the clear ends with remove_orphans: never during a job's write phase
        ctx.store.delete_passages_for_source(source_id)
    ctx.store.bump_graph_version()


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
