"""
The `hippo` command line.

    hippo serve                 start the web app (and the MCP server at /mcp)
    hippo mcp                   run the MCP server over stdio, for clients that spawn it
    hippo pull-models           download the Ollama models hippo needs, showing progress
    hippo index <path-or-url>   remember a file, a folder, or a public git repo, and wait for it
    hippo ask "<question>"      ask the memory a question
    hippo sources               list what is in the memory
    hippo settings              show the retrieval settings and where things are

Every command builds its `AppContext` from environment variables (see
config.py and .env.example), exactly like the web app does, so the CLI and the
UI always see the same memory.
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .config import load_config
from .context import AppContext

WAIT_SECONDS = 3600.0  # a big repo on a slow CPU model really can take an hour


# ------------------------------------------------------------ arguments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hippo", description="A portable HippoRAG memory.")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the web app and the MCP endpoint")
    serve.add_argument(
        "--host",
        default=None,
        help="bind address (default: HIPPO_HOST or 127.0.0.1; hippo has no login, so open it up only behind a proxy)",
    )
    serve.add_argument("--port", type=int, default=None, help="port (default: HIPPO_PORT or 8000)")

    sub.add_parser("mcp", help="run the MCP server over stdio")
    sub.add_parser("pull-models", help="download the Ollama models hippo needs")

    index = sub.add_parser("index", help="remember a file, folder, or git URL and wait for indexing")
    index.add_argument("target", help="a file path, a folder path, or a public git URL")
    index.add_argument("--name", default=None, help="what to call this source in the library")

    ask = sub.add_parser("ask", help="ask the memory a question")
    ask.add_argument("question")

    sub.add_parser("sources", help="list the sources in the memory")
    sub.add_parser("settings", help="show the retrieval settings")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # stdio MCP owns stdout, so all logging goes to stderr for every command (simplest rule).
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    handlers = {
        "serve": cmd_serve,
        "mcp": cmd_mcp,
        "pull-models": cmd_pull_models,
        "index": cmd_index,
        "ask": cmd_ask,
        "sources": cmd_sources,
        "settings": cmd_settings,
    }
    return handlers[args.command](args)


# ------------------------------------------------------------- commands


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn  # heavy import; only the server needs it

    config = load_config()
    host = args.host or config.host
    port = args.port or config.port
    print(f"hippo is starting at http://{host}:{port}  (MCP at http://{host}:{port}/mcp)")
    # The web app is imported lazily by uvicorn so `hippo ask` does not pay for FastAPI + Jinja.
    uvicorn.run("hippo.web.app:create_app", factory=True, host=host, port=port)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import run_stdio

    run_stdio(AppContext.from_env())
    return 0


def cmd_pull_models(args: argparse.Namespace) -> int:
    ctx = AppContext.from_env()
    if not ctx.ollama.is_up():
        print(f"Ollama at {ctx.config.ollama_url} is not reachable.", file=sys.stderr)
        return 1
    missing = ctx.ollama.missing_models()
    if not missing:
        print("All models are installed: " + ", ".join(ctx.ollama.required_models()))
        return 0
    for model in missing:
        print(f"Pulling {model} ...")
        ctx.ollama.ensure_model(model, on_progress=_print_pull_event)
        print(f"{model} is ready")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from .ingest import pipeline, repos

    ctx = AppContext.from_env()
    target: str = args.target
    if repos.is_git_url(target):
        source_id = pipeline.add_repo(ctx, target)
    else:
        path = Path(target)
        if not path.exists():
            print(f"{target} does not exist and is not a git URL", file=sys.stderr)
            return 1
        source_id = pipeline.add_upload(ctx, *_upload_for_path(path))
    if args.name:
        ctx.store.update_source(source_id, name=args.name)

    print(f"Indexing {target} as source {source_id} ...")
    ctx.jobs.wait_all(WAIT_SECONDS)
    source = ctx.store.get_source(source_id) or {}
    print(f"status: {source.get('status')} ({source.get('stage')}), passages: {source.get('passages', 0)}")
    if source.get("error"):
        print(f"error: {source['error']}", file=sys.stderr)
        return 1
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from .ask import ask

    ctx = AppContext.from_env()
    trace, answer = ask(ctx, args.question)
    print(answer.answer)
    if answer.thought:
        print(f"\nThought: {answer.thought}")
    print("\nTop passages:")
    for p in trace.passages[:5]:
        print(f"  {p.rank:>2}. {p.score:.4f}  {p.title}  [{p.source_name}]")
    if trace.used_dpr_fallback:
        print(f"\n(no facts matched, fell back to embedding search: {trace.fallback_reason})")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    ctx = AppContext.from_env()
    rows = ctx.store.list_sources()
    if not rows:
        print("The memory is empty. Try: hippo index <file>")
        return 0
    print_table(
        ["id", "name", "kind", "status", "stage", "passages", "facts", "created"],
        [
            [
                r["id"],
                r["name"],
                r["kind"],
                r["status"],
                r.get("stage") or "",
                r.get("passages", 0),
                r.get("fact_links", 0),
                (r.get("created_at") or "")[:19],
            ]
            for r in rows
        ],
    )
    return 0


def cmd_settings(args: argparse.Namespace) -> int:
    ctx = AppContext.from_env()
    config = ctx.config
    print("Where things are:")
    print(f"  neo4j_uri    = {config.neo4j_uri}")
    print(f"  ollama_url   = {config.ollama_url}")
    print(f"  llm_model    = {config.llm_model}")
    print(f"  embed_model  = {config.embed_model}")
    print(f"  data_dir     = {config.data_dir}")
    print("\nRetrieval settings (change them on the Settings page):")
    for key, value in sorted(ctx.store.get_settings().items()):
        print(f"  {key} = {value}")
    return 0


# -------------------------------------------------------------- helpers


def _print_pull_event(event: dict[str, Any]) -> None:
    status = event.get("status", "")
    if "completed" in event and "total" in event and event["total"]:
        percent = 100 * int(event["completed"]) // int(event["total"])
        print(f"  {status} {percent}%", end="\r", flush=True)
    else:
        print(f"  {status}")


def _upload_for_path(path: Path) -> tuple[str, bytes]:
    """What to hand to pipeline.add_upload: a file as-is, a folder zipped in memory."""
    if path.is_file():
        return path.name, path.read_bytes()
    return path.name + ".zip", _zip_folder(path)


def _zip_folder(folder: Path) -> bytes:
    """Zip a folder so it can go through the same 'archive' path as an uploaded .zip."""
    from .ingest.readers import IGNORED_DIRS, MAX_FILE_BYTES

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(folder.rglob("*")):
            relative = file.relative_to(folder)
            # Skip .git, node_modules, hidden folders and huge files: the readers would ignore them anyway,
            # and leaving them out keeps the zip small.
            parts = relative.parts[:-1]
            if any(p in IGNORED_DIRS or p.startswith(".") for p in parts):
                continue
            if file.is_file() and file.stat().st_size <= MAX_FILE_BYTES:
                zf.write(file, str(relative))
    return buffer.getvalue()


def print_table(headers: list[str], rows: Iterable[list[Any]]) -> None:
    """A plain aligned text table; no dependency needed."""
    rows = [[str(cell) for cell in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row, strict=True)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)))


if __name__ == "__main__":
    sys.exit(main())
