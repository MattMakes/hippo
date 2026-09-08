#!/usr/bin/env python
"""
Regenerate the extractor's sections of `tests/fixtures/code_sample/expected.json`.

`expected.json` is the *spec* for the code graph, not a snapshot of it. A diff here is a
change to what hippo promises about a repository, and is read like a source change --
never run to make a red build green. `tests/unit/test_codegraph.py` compares what
`extract_code` produces against this file, order-independently.

Usage, from the repo root:

    .venv/bin/python scripts/update_expected.py           # rewrite the file
    .venv/bin/python scripts/update_expected.py --check   # exit 1 if it would change

The file has seven top-level sections, and this script now owns all of them -- the last two
need a git repository, which it builds in a temporary directory from the same tree:

    symbols       [{path, qualname, display, kind, lang, line_start, line_end, header_end,
                    signature, doc, is_test, raises, params, statement_lines}]
                  Keyed by (path, qualname). `display` is the fully-qualified name
                  `module.qualname` that passage titles and the answer block use.
    data_objects  [{kind, qualname, name, dialect, mentions}]
                  Keyed by (kind, qualname) -- a table `orders` and a Cypher label `orders`
                  are different nodes. `mentions` is every (path, line) that names it, which
                  is what S2.5's DEFINED_IN edges are built from.
    edges         [{kind, omega, provenance, a, b, extra}]
                  `a` and `b` are ["symbol", path, qualname] or ["data", kind, qualname];
                  never node ids, which depend on the run's `source_id`. `extra` is present
                  only on INVOKES.
    definitions   [{node, passage}]
                  One DEFINED_IN pair per (node, passage title). A data object is defined by
                  every passage whose literal names it, not just by its declaration (S2.5).
    refers_to     [{passage, node, omega, token}]
                  A prose passage naming code: 0.85 for a backticked or dotted name, 0.60 for
                  a run of words matching a name's split tokens.
    commits       [] -- WP2b: keyed by (ordinal, subject), NEVER by sha (S2.17: a sha
                  hashes author, committer and timestamps, so it is not reproducible).
    modifies      [] -- WP2b: keyed by (ordinal, path, qualname).

Every list is sorted by its key and written with `sort_keys=True, indent=2`, so a
regeneration diff shows only what actually changed.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from hippo.codegraph import extract_code, read_history  # noqa: E402
from hippo.config import Config  # noqa: E402
from hippo.hipporag.indexer import passage_id, refers_to_rows  # noqa: E402
from hippo.ingest.chunker import chunk_documents  # noqa: E402
from tests.conftest import CODE_SAMPLE_PATH, code_sample_docs, make_code_checkout  # noqa: E402

EXPECTED = CODE_SAMPLE_PATH / "expected.json"
SOURCE_ID = "fixture"
OWNED = ("symbols", "data_objects", "edges", "definitions", "refers_to", "commits", "modifies")
LATER = ()


def build(source_id: str = SOURCE_ID) -> dict:
    """The three sections this script owns, from a fresh `extract_code` over the fixture."""
    graph = extract_code(code_sample_docs(), source_id)
    labels = {s.id: ["symbol", s.path, s.qualname] for s in graph.symbols}
    labels.update({d.id: ["data", d.kind, d.qualname] for d in graph.data_objects})
    symbols = [
        {
            "path": s.path,
            "qualname": s.qualname,
            "display": s.display,
            "kind": s.kind,
            "lang": s.lang,
            "line_start": s.line_start,
            "line_end": s.line_end,
            "header_end": s.header_end,
            "signature": s.signature,
            "doc": s.doc,
            "is_test": s.is_test,
            "raises": list(s.raises),
            "params": list(s.params),
            "statement_lines": list(s.statement_lines),
        }
        for s in graph.symbols
    ]
    data_objects = [
        {
            "kind": d.kind,
            "qualname": d.qualname,
            "name": d.name,
            "dialect": d.dialect,
            "mentions": [list(m) for m in d.mentions],
        }
        for d in graph.data_objects
    ]
    edges = [
        {
            "kind": e.kind,
            "omega": e.omega,
            "provenance": e.provenance,
            "a": labels[e.a],
            "b": labels[e.b],
            **({"extra": e.extra} if e.extra else {}),
        }
        for e in graph.edges
    ]
    # The chunker and the name scanner are pure, so the passage half of the spec needs no
    # store and no LLM: the same chunks the pipeline would build, at the same default sizes.
    chunks = chunk_documents(
        code_sample_docs(), Config.chunk_size_chars, Config.chunk_overlap_chars, code=graph
    )
    titles = {passage_id(source_id, c): c.title for c in chunks}
    definitions = [
        {"node": labels[node], "passage": chunk.title} for chunk in chunks for node in chunk.defines
    ]
    prose = [(passage_id(source_id, c), c.text) for c in chunks if c.extract_text is None]
    refers_to = [
        {
            "passage": titles[row["passage_id"]],
            "node": labels[row["node_id"]],
            "omega": row["omega"],
            "token": row["token"],
        }
        for row in refers_to_rows(graph, prose)
    ]
    commits, modifies = history(source_id, graph.symbols)
    return {
        "symbols": sorted(symbols, key=lambda s: (s["path"], s["qualname"])),
        "data_objects": sorted(data_objects, key=lambda d: (d["kind"], d["qualname"])),
        "edges": sorted(edges, key=lambda e: (e["kind"], e["a"], e["b"])),
        "definitions": sorted(definitions, key=lambda d: (d["node"], d["passage"])),
        "refers_to": sorted(refers_to, key=lambda r: (r["passage"], r["node"])),
        "commits": sorted(commits, key=lambda c: (c["ordinal"], c["subject"])),
        "modifies": sorted(modifies, key=lambda m: (m["ordinal"], m["path"], m["qualname"])),
    }


def history(source_id: str, head: list) -> tuple[list[dict], list[dict]]:
    """
    The `commits` and `modifies` sections, from a throwaway checkout of the same tree.

    **Nothing here is keyed on a SHA** (S2.17). A SHA hashes the author, the committer and both
    of their timestamps, and `commit_id` mixes in a `source_id` that is different on every run,
    so a file keyed on either could never match twice. `(ordinal, subject)` names a commit and
    `(ordinal, path, qualname)` names a MODIFIES row; the test maps this run's SHAs through the
    ordinal. `make_code_checkout` pins the identity and the dates too, so the SHAs happen to be
    stable as well -- but that is belt and braces, not the rule.

    The HEAD symbols are the ones already extracted from the checked-in tree rather than from
    the checkout: `make_code_checkout` asserts the two are byte-identical, so they are the same
    symbols with the same ids -- and re-reading the checkout would mean walking into its `.git`.
    """
    with tempfile.TemporaryDirectory() as scratch:
        checkout = make_code_checkout(Path(scratch))
        read = read_history(checkout, head, source_id, depth=200, timeout_s=30, total_s=300)
        ordinals = {c["id"]: c["ordinal"] for c in read.commits}
        symbols = {s.id: s for s in head}
        commits = [
            {
                "ordinal": c["ordinal"],
                "subject": (c["message"].splitlines() or [""])[0],
                "message": c["message"],
                "author": c["author"],
                "date": c["date"],
            }
            for c in read.commits
        ]
        modifies = [
            {
                "ordinal": ordinals[m["commit_id"]],
                "path": symbols[m["symbol_id"]].path,
                "qualname": symbols[m["symbol_id"]].qualname,
                "hunk": m["hunk"],
            }
            for m in read.modifies
        ]
        return commits, modifies


def render(sections: dict, existing: dict | None = None) -> str:
    """The owned sections merged into whatever the later work packages already wrote."""
    document = dict(existing or {})
    document.update(sections)
    for key in LATER:
        document.setdefault(key, [])
    ordered = {key: document[key] for key in (*OWNED, *LATER)}
    return json.dumps(ordered, indent=2, sort_keys=True) + "\n"


def main() -> int:
    existing = json.loads(EXPECTED.read_text()) if EXPECTED.exists() else None
    text = render(build(), existing)
    if "--check" in sys.argv:
        current = EXPECTED.read_text() if EXPECTED.exists() else ""
        if current == text:
            print(f"{EXPECTED.relative_to(ROOT)} is up to date")
            return 0
        print(f"{EXPECTED.relative_to(ROOT)} is STALE -- rerun without --check and read the diff")
        return 1
    EXPECTED.write_text(text)
    counts = {key: len(value) for key, value in build().items()}
    print(f"wrote {EXPECTED.relative_to(ROOT)}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
