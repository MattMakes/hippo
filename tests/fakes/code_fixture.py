"""
The code-graph shapes `tests/fixtures/code_sample/` cannot produce, written through the store.

Everything else moved to the real thing when WP2 and WP2i landed: `code_index` (and `mixed_index`)
in `tests/conftest.py` index the checked-in tree through the actual pipeline, so the symbols, edges,
omegas and provenances the retrieval tests assert are the extractor's, not a hand-written guess.

What is left here is the three cases a fixed tree of ten files genuinely cannot express:

* **history** - `Commit` nodes, `MODIFIES` and `PRECEDES`. A nested `.git` cannot be checked in, so
  WP2b builds these from a repository created at test time; until that lands, `write_commit_history`
  writes the same three commits by hand on top of an already-indexed source. `GraphIndex` has loaded
  commits since WP1, so `paths.history()` and the block's `Commits:` lines need nothing from WP2b.
* **a name that means too many things** - S2.13 drops a token matching more than ten symbols, and
  the fixture tree's most ambiguous name (`log`) means three. `many_symbols` writes as many
  same-named functions as a test asks for.
* **a symbol busy enough to crowd the answer block** - the tree's busiest function makes three
  calls, and QA1 defect 1 needs ten of them plus one caller before `code_triples_chars` bites.
  `call_hub` writes that shape, plus a second unrelated seed to watch the round-robin with.
* **symbols in a language the tree has no walker for yet** - `find_anchors` resolves a stack frame
  by path and line and never asks what language wrote it, so the Go / .NET / Rust frame shapes can
  be tested before those walkers land. `polyglot_symbols` writes the `.go`/`.cs`/`.rs` half of the
  order-service story `ai_docs/add_langs.md` describes, at the paths and line ranges its fixture
  trees will have.
"""

from __future__ import annotations

from hippo.codegraph.model import commit_id, symbol_id
from hippo.hipporag.indexer import Chunk, index_source, passage_id
from hippo.hipporag.paths import module_of

# Ordinals well past the tree's own passages, so the two sets never interleave in `load_passages`.
FIRST_COMMIT_ORDINAL = 900

# (sha, ISO date, subject, path, qualname) - newest first, which is `ordinal` 0 upwards.
COMMITS: list[tuple[str, str, str, str, str]] = [
    (
        "c3c3c3c",
        "2026-01-03T00:00:00+00:00",
        "Raise OrderError from save",
        "pyapp/orders.py",
        "OrderService.save",
    ),
    (
        "b2b2b2b",
        "2026-01-02T00:00:00+00:00",
        "Total the order in place",
        "pyapp/orders.py",
        "OrderService.place",
    ),
    ("a1a1a1a", "2026-01-01T00:00:00+00:00", "Add the order service", "pyapp/orders.py", "OrderService"),
]


def write_commit_history(ctx, source_id: str) -> list[str]:
    """
    Three commits, their passages, `MODIFIES` and the first-parent `PRECEDES` chain.

    Shaped exactly as WP2b writes them: the passage text is the message plus a `Touched:` line, the
    commit node is `DEFINED_IN` it, and `PRECEDES` runs newest to older. Returns the shas, newest
    first. Call `ctx.invalidate_graph()` (or reload the index) afterwards.
    """
    chunks = [
        Chunk(
            FIRST_COMMIT_ORDINAL + ordinal,
            f"commit {sha}: {subject}",
            f"{subject}\n\nTouched: {qualname}",
        )
        for ordinal, (sha, _date, subject, _path, qualname) in enumerate(COMMITS)
    ]
    index_source(ctx.store, ctx.ollama, source_id, chunks)

    rows, modifies, definitions = [], [], []
    for ordinal, (sha, date, subject, path, qualname) in enumerate(COMMITS):
        node_id = commit_id(source_id, sha)
        rows.append(
            {
                "id": node_id,
                "source_id": source_id,
                "sha": sha,
                "author": "A Committer",
                "date": date,
                "message": subject,
                "ordinal": ordinal,
            }
        )
        modifies.append(
            {
                "commit_id": node_id,
                # `OrderService` is the class, the other two are its methods. Only a *module's*
                # kind changes the id, so what matters here is that none of these is one.
                "symbol_id": symbol_id(source_id, path, qualname, "method" if "." in qualname else "class"),
                "omega": 1.0,
                "hunk": {"file": path, "old_range": [1, 0], "new_range": [16, 8], "churn": 8},
            }
        )
        definitions.append((node_id, passage_id(source_id, chunks[ordinal])))
    ctx.store.add_commits(rows)
    ctx.store.add_modifies(modifies)
    ctx.store.add_precedes(
        [
            (commit_id(source_id, a[0]), commit_id(source_id, b[0]))
            for a, b in zip(COMMITS, COMMITS[1:], strict=False)
        ]
    )
    ctx.store.link_definitions(definitions)
    ctx.invalidate_graph()
    return [sha for sha, *_ in COMMITS]


def many_symbols(ctx, source_id: str, name: str, how_many: int) -> list[str]:
    """
    `how_many` functions in different files that all answer to the same bare name.

    Each gets a passage and a `DEFINED_IN`, so it is visible to a scoped index the same way every
    other symbol is. Returns their node ids. Call `ctx.invalidate_graph()` afterwards.
    """
    rows, chunks = [], []
    for i in range(how_many):
        path = f"pkg/mod{i}.py"
        rows.append(
            {
                "id": symbol_id(source_id, path, name, "function"),
                "source_id": source_id,
                "name": name,
                "qualname": name,
                "kind": "function",
                "lang": "python",
                "path": path,
                "line_start": 1,
                "line_end": 2,
            }
        )
        chunks.append(
            Chunk(800 + i, f"{path} :: pkg.mod{i}.{name} (lines 1-2)", f"def {name}():\n    return {i}")
        )
    ctx.store.add_symbols(rows)
    index_source(ctx.store, ctx.ollama, source_id, chunks)
    ctx.store.link_definitions(
        [(row["id"], passage_id(source_id, chunk)) for row, chunk in zip(rows, chunks, strict=True)]
    )
    ctx.invalidate_graph()
    return [row["id"] for row in rows]


# (lang, path, qualname, kind, line_start, line_end) - the shape `add_symbols` rows take. The paths
# and the story are `ai_docs/add_langs.md`'s; the line ranges are a plausible layout of those files,
# chosen so a class spans its methods and a frame has an unambiguous innermost symbol.
POLYGLOT: list[tuple[str, str, str, str, int, int]] = [
    ("go", "goapp/orders/service.go", "Service", "class", 12, 40),
    ("go", "goapp/orders/service.go", "Service.Place", "method", 16, 24),
    ("go", "goapp/orders/service.go", "Service.ListOpen", "method", 26, 30),
    ("go", "goapp/cmd/main.go", "main", "function", 5, 9),
    ("csharp", "csapp/Orders/OrderService.cs", "OrderService", "class", 10, 60),
    ("csharp", "csapp/Orders/OrderService.cs", "OrderService.Place", "method", 14, 24),
    ("csharp", "csapp/Orders/OrderService.cs", "OrderService.Save", "method", 26, 34),
    ("csharp", "csapp/Orders/OrderService.cs", "OrderService.ListOpen", "method", 36, 40),
    ("csharp", "csapp/Store/Base.cs", "InvalidOrderException", "class", 12, 14),
    ("rust", "rsapp/src/orders.rs", "OrderService", "class", 6, 10),
    ("rust", "rsapp/src/orders.rs", "OrderService.log", "method", 14, 16),
    ("rust", "rsapp/src/orders.rs", "OrderService.place", "method", 18, 26),
    ("rust", "rsapp/src/main.rs", "main", "function", 3, 8),
]

# Ordinals of their own, between `call_hub`'s 700s and `many_symbols`' 800s.
FIRST_POLYGLOT_ORDINAL = 600


def polyglot_symbols(ctx, source_id: str) -> dict[str, str]:
    """
    The Go, C# and Rust half of the order-service story, written straight through the store.

    The walkers for those three languages are being built in parallel (`ai_docs/add_langs.md`);
    `find_anchors` needs none of them, because a stack frame resolves by `path_index` and a line
    range and a qualified name, none of which knows what language the symbol came from. Symbols get
    a passage and a `DEFINED_IN` like `many_symbols`, so the shape is one the real indexer could
    have written. Returns the display names, keyed `<lang>:<qualname>`.
    """
    rows, chunks = [], []
    for ordinal, (lang, path, qualname, kind, start, end) in enumerate(POLYGLOT):
        rows.append(
            {
                "id": symbol_id(source_id, path, qualname, kind),
                "source_id": source_id,
                "name": qualname.rsplit(".", 1)[-1],
                "qualname": qualname,
                "kind": kind,
                "lang": lang,
                "path": path,
                "line_start": start,
                "line_end": end,
            }
        )
        chunks.append(
            Chunk(
                FIRST_POLYGLOT_ORDINAL + ordinal,
                f"{path} :: {qualname} (lines {start}-{end})",
                f"{qualname} keeps orders in {path}.",
            )
        )
    ctx.store.add_symbols(rows)
    index_source(ctx.store, ctx.ollama, source_id, chunks)
    ctx.store.link_definitions(
        [(row["id"], passage_id(source_id, chunk)) for row, chunk in zip(rows, chunks, strict=True)]
    )
    ctx.invalidate_graph()
    return {
        f"{lang}:{qualname}": f"{module_of(path)}.{qualname}"
        for lang, path, qualname, _kind, _start, _end in POLYGLOT
    }


# The hub the real-model smoke tripped over (QA1 defect 1): `find_anchors` had sixteen outgoing
# calls and one resolved caller, and `code_triples_chars` fitted fourteen lines. The ten-file tree's
# busiest symbol makes three outgoing calls, so it cannot express the shape at all.
HUB_OUT_OMEGAS = (1.0, 1.0, 0.95, 0.95, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9)


def call_hub(ctx, source_id: str) -> dict[str, str]:
    """
    A well-connected function: ten outgoing `INVOKES` at ω 0.90-1.00 and one caller at ω 0.90.

    Also a second, unrelated seed (`pkg.other.other_seed`, one outgoing call) so a test can watch
    `code_paths_for` round-robin between two seeds instead of exhausting the busier one first.
    Returns the display names, keyed `hub` / `caller` / `other` / `step0`. Symbols get a passage and
    a `DEFINED_IN` like `many_symbols`, so the shape is one the real indexer could have written.
    """
    names = {  # (path, qualname) per symbol; the display name is `module_of(path) + "." + qualname`
        "hub": ("pkg/anchors.py", "find_anchors"),
        "caller": ("pkg/retriever.py", "Retriever.code_seeds"),
        "other": ("pkg/other.py", "other_seed"),
        "other_helper": ("pkg/other.py", "other_helper"),
        **{f"step{i}": ("pkg/anchors.py", f"_step{i}") for i in range(len(HUB_OUT_OMEGAS))},
    }
    rows, chunks = [], []
    for ordinal, (key, (path, qualname)) in enumerate(names.items()):
        rows.append(
            {
                "id": symbol_id(source_id, path, qualname, "function"),
                "source_id": source_id,
                "name": qualname.rsplit(".", 1)[-1],
                "qualname": qualname,
                "kind": "function",
                "lang": "python",
                "path": path,
                "line_start": 1,
                "line_end": 2,
            }
        )
        chunks.append(Chunk(700 + ordinal, f"{path} :: {qualname} (lines 1-2)", f"def {key}():\n    pass"))
    ids = {key: row["id"] for key, row in zip(names, rows, strict=True)}
    ctx.store.add_symbols(rows)
    index_source(ctx.store, ctx.ollama, source_id, chunks)
    ctx.store.link_definitions(
        [(row["id"], passage_id(source_id, chunk)) for row, chunk in zip(rows, chunks, strict=True)]
    )
    ctx.store.add_code_edges(
        [
            *(
                {
                    "a": ids["hub"],
                    "b": ids[f"step{i}"],
                    "kind": "INVOKES",
                    "omega": omega,
                    "provenance": "same_file",
                }
                for i, omega in enumerate(HUB_OUT_OMEGAS)
            ),
            # The one edge that answers "who calls find_anchors", at the same ω as six of the ten.
            {
                "a": ids["caller"],
                "b": ids["hub"],
                "kind": "INVOKES",
                "omega": 0.9,
                "provenance": "via_import",
            },
            {
                "a": ids["other"],
                "b": ids["other_helper"],
                "kind": "INVOKES",
                "omega": 0.9,
                "provenance": "same_file",
            },
        ]
    )
    ctx.invalidate_graph()
    return {
        "hub": "pkg.anchors.find_anchors",
        "caller": "pkg.retriever.Retriever.code_seeds",
        "other": "pkg.other.other_seed",
        "other_helper": "pkg.other.other_helper",
    }
