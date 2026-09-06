"""
Getting text into hippo.

    readers.py    files (pdf, docx, epub, html, text, code, zip) -> Document(title, text, path, is_code)
    html_text.py  the small HTML tag stripper used by the html and epub readers
    chunker.py    Document -> Chunk(ordinal, title, text) pieces the indexer can handle
    repos.py      git URLs: validation, shallow cloning, walking the files
    pipeline.py   the add_* functions, the background indexing job, delete and reindex

The web routes, the MCP server and the CLI all call pipeline.add_* and never
touch the store's Source rows directly.
"""

from .chunker import chunk_document, chunk_documents
from .pipeline import add_repo, add_sample, add_text, add_upload, delete_source, reindex, start_indexing
from .readers import Document, is_supported, read_file, read_zip
from .repos import RepoError, clone_repo, is_git_url, walk_repo

__all__ = [
    "Document",
    "RepoError",
    "add_repo",
    "add_sample",
    "add_text",
    "add_upload",
    "chunk_document",
    "chunk_documents",
    "clone_repo",
    "delete_source",
    "is_git_url",
    "is_supported",
    "read_file",
    "read_zip",
    "reindex",
    "start_indexing",
    "walk_repo",
]
