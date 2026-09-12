"""
Getting text into hippo.

    readers.py    files (pdf, docx, epub, html, text, code, zip) -> Document(title, text, path, is_code)
    html_text.py  the small HTML tag stripper used by the html and epub readers
    chunker.py    Document -> Chunk(ordinal, title, text) pieces the indexer can handle
    repos.py      git URLs: validation, shallow cloning, walking the files
    pipeline.py   the add_* functions, the background indexing job, delete and reindex

The web routes, the MCP server and the CLI all call pipeline.add_* and never
touch the store's Source rows directly.

Every name below is bound on first use (PEP 562) rather than at import time, so
`import hippo.ingest` -- which is what importing any module in this package does
first -- costs nothing and reaches no other module. Importing the pipeline here
eagerly is what made this package a cycle: a knowledge module importing
`hippo.ingest.accepted_inputs` initialised this file, which pulled the pipeline
and the managed lane, which import `hippo.knowledge` straight back. Nothing about
the public surface changes: `from hippo.ingest import add_text` still works, and
so does `hippo.ingest.add_text`.
"""

from importlib import import_module

# name -> the submodule that defines it. The single source for `__all__` and for
# what `__getattr__` will import; nothing else in this file binds a public name.
_EXPORTS = {
    "Document": "readers",
    "RepoError": "repos",
    "add_repo": "pipeline",
    "add_sample": "pipeline",
    "add_text": "pipeline",
    "add_upload": "pipeline",
    "chunk_document": "chunker",
    "chunk_documents": "chunker",
    "clone_repo": "repos",
    "delete_source": "pipeline",
    "is_git_url": "repos",
    "is_supported": "readers",
    "read_file": "readers",
    "read_zip": "readers",
    "reindex": "pipeline",
    "start_indexing": "pipeline",
    "walk_repo": "repos",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f".{module}", __name__), name)


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})
