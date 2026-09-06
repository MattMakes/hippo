"""
Size limits on what can be added: bytes per upload or pasted text, text per source,
passages per source, and the zip/epub/docx budgets, as seen from the pipeline.

A 300 KB epub or zip can unpack into hundreds of millions of characters, and every
1500 of them cost two LLM calls, so the limits sit in pipeline.py (one place for the web
forms, the JSON API and the MCP tool) and in the readers (which count text as they go).
"""

from __future__ import annotations

import dataclasses
import io
import zipfile
from types import SimpleNamespace

import pytest

from hippo.context import AppContext
from hippo.ingest import pipeline, readers

WAIT = 30


def with_limits(ctx: AppContext, **limits: int) -> None:
    """Give ctx a config with these limit fields, whether or not Config knows them yet."""
    fields = {f.name: getattr(ctx.config, f.name) for f in dataclasses.fields(ctx.config)}
    ctx.config = SimpleNamespace(**{**fields, **limits})


def build_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def failed_source(ctx: AppContext, source_id: str) -> dict:
    ctx.jobs.wait_all(WAIT)
    source = ctx.store.get_source(source_id)
    assert source["status"] == "failed", source
    assert source["error"].startswith("TooLarge: too large"), source["error"]
    assert source["passages"] == 0
    return source


# ------------------------------------------------------------ byte cap


def test_the_limits_come_from_config_and_default_to_50mb_and_20m_chars(ctx: AppContext) -> None:
    assert (
        pipeline.max_upload_bytes(ctx)
        == ctx.config.max_upload_bytes
        == pipeline.DEFAULT_MAX_UPLOAD_BYTES
        == 50_000_000
    )
    assert pipeline.max_text_chars(ctx) == ctx.config.max_text_chars == readers.MAX_TEXT_CHARS == 20_000_000


def test_uploads_over_the_byte_cap_are_refused_before_anything_is_saved(ctx: AppContext) -> None:
    with_limits(ctx, max_upload_bytes=100)
    with pytest.raises(ValueError, match="too big"):
        pipeline.add_upload(ctx, "big.md", b"x" * 101)
    assert ctx.store.list_sources() == []
    assert not (ctx.config.data_dir / "sources").exists()
    pipeline.add_upload(ctx, "ok.md", b"Boulder is located in Colorado.")  # under the cap: fine
    ctx.jobs.wait_all(WAIT)
    assert ctx.store.list_sources()[0]["status"] == "ready"


def test_pasted_text_over_the_byte_cap_is_refused(ctx: AppContext) -> None:
    with_limits(ctx, max_upload_bytes=100)
    with pytest.raises(ValueError, match="too big"):
        pipeline.add_text(ctx, "long", "y" * 101)
    assert ctx.store.list_sources() == []


def test_the_mcp_remember_tool_shares_the_same_cap(ctx: AppContext) -> None:
    from mcp.server.mcpserver.exceptions import ToolError

    from hippo.mcp_server import remember_tool

    with_limits(ctx, max_upload_bytes=100)
    with pytest.raises(ToolError, match="too big"):
        remember_tool(ctx, "long", "z" * 101)
    assert ctx.store.list_sources() == []


# -------------------------------------------------------- text budget


def test_a_source_with_more_text_than_the_budget_fails_as_too_large(ctx: AppContext) -> None:
    with_limits(ctx, max_text_chars=50)
    source_id = pipeline.add_text(ctx, "long", "Boulder is located in Colorado. " * 10)
    source = failed_source(ctx, source_id)
    assert "HIPPO_MAX_TEXT_CHARS" in source["error"]


def test_the_budget_counts_every_file_of_a_zip_together(ctx: AppContext) -> None:
    with_limits(ctx, max_text_chars=60)
    members = {f"note{i}.md": b"Boulder is located in Colorado." for i in range(3)}  # 31 chars each
    source_id = pipeline.add_upload(ctx, "notes.zip", build_zip(members))
    failed_source(ctx, source_id)  # not swallowed as "one broken member"


def test_a_zip_with_too_many_readable_members_fails(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readers, "MAX_ZIP_MEMBERS", 2)
    members = {f"n{i}.md": b"Boulder is located in Colorado." for i in range(3)}
    members["logo.png"] = b"\x89PNG\x00"  # not readable: does not count
    source_id = pipeline.add_upload(ctx, "many.zip", build_zip(members))
    source = failed_source(ctx, source_id)
    assert "3 readable files" in source["error"]


def test_a_zip_that_unpacks_too_big_fails_without_reading_it(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(readers, "MAX_ZIP_TOTAL_BYTES", 100)
    reads: list[str] = []
    real_read_bytes = readers.read_bytes
    monkeypatch.setattr(readers, "read_bytes", lambda *a, **k: reads.append(a[1]) or real_read_bytes(*a, **k))
    members = {"a.md": b"x" * 60, "b.md": b"y" * 60}
    source_id = pipeline.add_upload(ctx, "fat.zip", build_zip(members))
    source = failed_source(ctx, source_id)
    assert "unpack to 120 bytes" in source["error"]
    assert reads == [], "the zip table already says it is too big; no member should be inflated"


# ------------------------------------------------------ passage ceiling


def test_a_source_with_too_many_passages_fails_before_any_llm_call(
    ctx: AppContext, fake_ollama, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "MAX_CHUNKS", 2)
    text = "\n\n".join(f"## Part {i}\n\nBoulder is located in Colorado." for i in range(4))
    source_id = pipeline.add_upload(ctx, "parts.md", text.encode())
    source = failed_source(ctx, source_id)
    assert "4 passages" in source["error"] and "limit is 2" in source["error"]
    assert fake_ollama.calls == []
    assert ctx.store.stats()["passages"] == 0
