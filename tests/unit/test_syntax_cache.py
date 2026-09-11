"""Syntax reuse preserves fresh source-wide resolution and native identity."""

from dataclasses import asdict
from inspect import signature
from types import SimpleNamespace

import pytest

from hippo.codegraph import extract


def doc(path, text):
    return SimpleNamespace(title=path, path=path, text=text, is_code=True)


def test_cache_hit_skips_walk_but_resolves_again(tmp_path, monkeypatch):
    assert "syntax_cache" in signature(extract.extract_code).parameters
    from hippo.codegraph.syntax_cache import SyntaxCache

    cache = SyntaxCache(tmp_path)
    docs = [doc("a.py", "def a(x):\n    return x\n")]
    first = extract.extract_code(docs, "source", syntax_cache=cache)
    resolutions = []
    original = extract._resolve

    def resolve(*args):
        resolutions.append(True)
        return original(*args)

    def no_walk(*args, **kwargs):
        raise AssertionError("cache hit must skip the parser walk")

    monkeypatch.setattr(extract, "_walk", no_walk)
    monkeypatch.setattr(extract, "_resolve", resolve)
    second = extract.extract_code(docs, "source", syntax_cache=cache)
    assert asdict(first) == asdict(second)
    assert resolutions == [True]


def test_changed_or_deleted_callee_reresolves_cached_caller(tmp_path, monkeypatch):
    from hippo.codegraph.syntax_cache import SyntaxCache

    cache = SyntaxCache(tmp_path)
    caller = doc("a.py", "from b import target\ndef a():\n    return target()\n")
    callee = doc("b.py", "def target():\n    return 1\n")
    first = extract.extract_code([caller, callee], "s", syntax_cache=cache)
    assert any(e.kind == "INVOKES" for e in first.edges)
    walked = []
    walk = extract._walk

    def track(path, *args, **kwargs):
        walked.append(path)
        return walk(path, *args, **kwargs)

    monkeypatch.setattr(extract, "_walk", track)
    for docs in ([caller, doc("b.py", "def other():\n    pass\n")], [caller]):
        graph = extract.extract_code(docs, "s", syntax_cache=cache)
        assert not any(e.kind == "INVOKES" for e in graph.edges)
        assert graph.unresolved_calls == {"a.py": 1}
        assert walked == (["b.py"] if len(docs) == 2 else [])
        assert asdict(graph) == asdict(extract.extract_code(docs, "s"))
        walked.clear()


def test_go_configuration_changes_are_seen_on_all_syntax_hits(tmp_path, monkeypatch):
    from hippo.codegraph.syntax_cache import SyntaxCache

    cache = SyntaxCache(tmp_path)
    docs = [
        doc("go.mod", "module example.com/app\n"),
        doc("main.go", 'package main\nimport "example.com/app/billing"\nfunc Main() { billing.Invoice() }\n'),
        doc("billing/billing.go", "package billing\nfunc Invoice() {}\n"),
    ]
    first = extract.extract_code(docs, "s", syntax_cache=cache)
    assert any(e.kind == "INVOKES" for e in first.edges)
    docs[0] = doc("go.mod", "module changed.example/app\n")
    expected = extract.extract_code(docs, "s")
    original_setup = extract._source_state
    observed = []

    def setup(current_docs, files):
        state = original_setup(current_docs, files)
        observed.append(state)
        return state

    monkeypatch.setattr(extract, "_source_state", setup)
    monkeypatch.setattr(extract, "_walk", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("walk")))
    actual = extract.extract_code(docs, "s", syntax_cache=cache)
    assert asdict(actual) == asdict(expected)
    assert observed[0]["go"] == {"changed.example/app": ""}


def test_replay_rematerializes_ids_and_nested_mutation_cannot_leak(tmp_path):
    from hippo.codegraph.model import symbol_id
    from hippo.codegraph.syntax_cache import SyntaxCache, cache_key

    cache = SyntaxCache(tmp_path)
    docs = [doc("a.py", 'class A:\n    def run(self, x):\n        raise ValueError("bad")\n')]
    a = extract.extract_code(docs, "one", node_namespace="old", syntax_cache=cache)
    a.symbols[-1].params.append("poison")
    a.symbols[-1].raises.append("poison")
    key = cache_key("a.py", docs[0].text, "python")
    facts = cache.get(key, "one", node_namespace="old")
    facts.names["poison"] = [999]
    facts.symbols[-1].statement_lines.append(999)
    facts.calls.append(None)
    fresh = cache.get(key, "two", node_namespace="new")
    assert "poison" not in fresh.names
    assert 999 not in fresh.symbols[-1].statement_lines
    assert None not in fresh.calls
    b = extract.extract_code(docs, "two", node_namespace="new", syntax_cache=cache)
    c = extract.extract_code(docs, "one", node_namespace="new", syntax_cache=cache)
    assert asdict(b) == asdict(extract.extract_code(docs, "two", node_namespace="new"))
    assert {s.id for s in a.symbols}.isdisjoint(s.id for s in b.symbols)
    assert {s.id for s in a.symbols}.isdisjoint(s.id for s in c.symbols)
    for symbol in b.symbols:
        assert symbol.source_id == "two"
        assert symbol.id == symbol_id("two", symbol.path, symbol.qualname, symbol.kind, node_namespace="new")
    assert all(e.a in {s.id for s in b.symbols} and e.b in {s.id for s in b.symbols} for e in b.edges)
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_key_tracks_all_inputs_and_unknown_profile_disables_reuse(monkeypatch):
    from hippo.codegraph import syntax_cache as sc

    key = sc.cache_key("a.ts", "export function a() {}", "typescript")
    assert key == sc.cache_key("a.ts", "export function a() {}", "typescript")
    assert key != sc.cache_key("b.ts", "export function a() {}", "typescript")
    assert key != sc.cache_key("a.ts", "export function b() {}", "typescript")
    assert key.grammar == "typescript"
    assert sc.cache_key("a.tsx", "", "typescript").grammar == "tsx"
    monkeypatch.setattr(sc, "grammar_for", lambda *args: "tsx")
    assert key != sc.cache_key("a.ts", "export function a() {}", "typescript")
    monkeypatch.setattr(sc, "grammar_for", lambda *args: "typescript")
    monkeypatch.setattr(sc, "WALKER_RULES_VERSION", "next")
    assert key != sc.cache_key("a.ts", "export function a() {}", "typescript")
    monkeypatch.setattr(sc, "WALKER_RULES_VERSION", key.walker_rules_version)
    monkeypatch.setattr(sc.metadata, "version", lambda name: "next")
    assert key != sc.cache_key("a.ts", "export function a() {}", "typescript")
    monkeypatch.setattr(sc.metadata, "version", lambda name: "")
    assert sc.cache_key("a.ts", "", "typescript") is None


def test_malformed_entries_are_misses_and_reparsed(tmp_path):
    import hashlib
    import json

    from hippo.codegraph.syntax_cache import SyntaxCache, _json, cache_key

    cache = SyntaxCache(tmp_path)
    docs = [doc("a.py", "def a(x):\n    return a(x)\n")]
    expected = extract.extract_code(docs, "s", syntax_cache=cache)
    key = cache_key("a.py", docs[0].text, "python")
    path = tmp_path / f"{key.digest}.json"
    original = path.read_bytes()
    for mutation in ("checksum", "nested", "unknown", "bool_int", "tuple", "key", "identity"):
        envelope = json.loads(original)
        if mutation == "checksum":
            envelope["payload_hash"] = "bad"
        elif mutation == "nested":
            envelope["payload"]["calls"][0]["kwargs"] = {"x": ["invalid"]}
        elif mutation == "unknown":
            envelope["payload"]["symbols"][0]["extra"] = True
        elif mutation == "bool_int":
            envelope["payload"]["symbols"][0]["line_start"] = True
        elif mutation == "tuple":
            envelope["payload"]["models"] = [["binding", "collection"]]
        elif mutation == "key":
            envelope["key"]["schema_version"] = True
        else:
            envelope["payload"]["symbols"][0]["source_id"] = "old"
        if mutation != "checksum":
            envelope["payload_hash"] = hashlib.sha256(_json(envelope["payload"])).hexdigest()
        path.write_bytes(_json(envelope))
        assert cache.get(key, "s") is None, mutation
        assert asdict(extract.extract_code(docs, "s", syntax_cache=cache)) == asdict(expected)
    for raw in (b"not json", b"[]", b'{"key":{},"key":{}}', b"[" * 2000):
        path.write_bytes(raw)
        assert cache.get(key, "s") is None
    path.write_bytes(original)
    assert SyntaxCache(tmp_path, max_entry_bytes=20).get(key, "s") is None


def test_guards_run_before_cache_lookup_and_cancel_is_preserved(tmp_path, monkeypatch):
    from hippo.codegraph.syntax_cache import SyntaxCache

    cache = SyntaxCache(tmp_path)
    monkeypatch.setattr(cache, "get", lambda *args, **kw: (_ for _ in ()).throw(AssertionError("lookup")))
    docs = [doc("a.py", "x" * (extract.CODE_MAX_FILE_BYTES + 1)), doc("README.md", "hello")]
    result = extract.extract_code(docs, "s", syntax_cache=cache)
    assert result.files_skipped == {"a.py": "too_big", "README.md": "unsupported"}
    result = extract.extract_code([doc("a.py", "")], "s", syntax_cache=cache, should_stop=lambda: True)
    assert result.truncated and not result.files_parsed
    monkeypatch.setattr(extract, "CODE_MAX_FILES", 0)
    result = extract.extract_code([doc("a.py", "")], "s", syntax_cache=cache)
    assert result.truncated


def test_empty_parse_errors_and_sql_preserve_behavior(tmp_path):
    from hippo.codegraph.syntax_cache import SyntaxCache

    cache = SyntaxCache(tmp_path)
    docs = [
        doc("empty.py", ""),
        doc("bad.py", "def ( !!!"),
        doc("schema.sql", "CREATE TABLE users (id INT);"),
    ]
    expected = extract.extract_code(docs, "s", node_namespace="g")
    for _ in range(2):
        assert asdict(extract.extract_code(docs, "s", node_namespace="g", syntax_cache=cache)) == asdict(
            expected
        )
    assert expected.files_skipped == {"bad.py": "parse_error"}
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_five_language_fixture_graphs_and_chunks_match_on_replay(tmp_path, monkeypatch):
    from hippo.codegraph.syntax_cache import SyntaxCache
    from hippo.ingest.chunker import chunk_documents
    from tests.conftest import code_sample_docs

    docs = code_sample_docs()
    cache = SyntaxCache(tmp_path)
    expected = extract.extract_code(docs, "target", node_namespace="next")
    assert {s.lang for s in expected.symbols} == {"python", "typescript", "go", "csharp", "rust"}
    expected_chunks = chunk_documents(docs, 1200, 100, code=expected)
    extract.extract_code(docs, "original", node_namespace="old", syntax_cache=cache)
    monkeypatch.setattr(extract, "_walk", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("walk")))
    actual = extract.extract_code(docs, "target", node_namespace="next", syntax_cache=cache)
    assert asdict(actual) == asdict(expected)
    assert [asdict(c) for c in chunk_documents(docs, 1200, 100, code=actual)] == [
        asdict(c) for c in expected_chunks
    ]
    valid_ids = {s.id for s in actual.symbols} | {d.id for d in actual.data_objects}
    assert all(set(chunk.defines) <= valid_ids for chunk in expected_chunks)


def test_all_fact_fields_roundtrip_and_fresh_nested_collections(tmp_path):
    from hippo.codegraph.model import (
        AssignFact,
        BaseFact,
        CallFact,
        FileFacts,
        ImportFact,
        LiteralFact,
        RaiseFact,
        Symbol,
    )
    from hippo.codegraph.syntax_cache import SyntaxCache, cache_key

    facts = FileFacts(
        path="a.py",
        lang="python",
        module="a",
        scope="scope",
        node_namespace="old",
        symbols=[
            Symbol(
                name="a",
                qualname="a",
                kind="module",
                path="a.py",
                params=["x"],
                statement_lines=[2],
                raises=["Error"],
                doc="doc",
                signature="a(x)",
                display="a",
                module="a",
                header_end=1,
                line_start=1,
                line_end=9,
                is_test=True,
            )
        ],
        imports=[
            ImportFact(module="b", name="B", alias="C", line=1, level=2, is_wildcard=True, is_default=True)
        ],
        calls=[
            CallFact(
                caller="a",
                caller_kind="module",
                receiver="c",
                name="call",
                line=2,
                in_branch=True,
                is_await=True,
                is_new=True,
                args=["x"],
                kwargs={"k": "v"},
            )
        ],
        bases=[BaseFact(cls="C", base="B", line=3)],
        exceptions=[RaiseFact(caller="a", caller_kind="module", name="Error", line=4, kind="catch")],
        assignments=[AssignFact(scope="a", scope_kind="module", target="x", value="C", line=5, chain="C()")],
        literals=[LiteralFact(caller="a", caller_kind="module", text="SELECT * FROM a", line=6)],
        table_names=[("C", "a", 7)],
        models=[("binding", "collection", 8)],
        names={"x": [1, 2]},
        reexports=[ImportFact(module="c", name="C")],
        default_export="C",
    )
    cache = SyntaxCache(tmp_path)
    key = cache_key("a.py", "", "python")
    cache.put(key, facts)
    first = cache.get(key, "source", node_namespace="next")
    assert first is not None
    expected = asdict(facts)
    expected["node_namespace"] = "next"
    expected["symbols"][0]["id"] = first.symbols[0].id
    expected["symbols"][0]["source_id"] = "source"
    assert asdict(first) == expected
    first.calls[0].args.append("poison")
    first.calls[0].kwargs["poison"] = "poison"
    first.names["x"].append(999)
    assert asdict(cache.get(key, "source", node_namespace="next")) == expected


def test_atomic_write_failure_preserves_previous_entry(tmp_path, monkeypatch):
    from hippo.codegraph import syntax_cache as sc

    cache = sc.SyntaxCache(tmp_path)
    docs = [doc("a.py", "def a():\n    pass\n")]
    extract.extract_code(docs, "s", syntax_cache=cache)
    key = sc.cache_key("a.py", docs[0].text, "python")
    original = cache.get(key, "s")
    changed = cache.get(key, "s")
    changed.symbols[-1].doc = "changed"
    monkeypatch.setattr(sc.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    cache.put(key, changed)
    assert asdict(cache.get(key, "s")) == asdict(original)
    assert len(list(tmp_path.iterdir())) == 1


def test_path_guard_and_unknown_metadata_reparse_without_lookup(tmp_path, monkeypatch):
    from hippo.codegraph import syntax_cache as sc

    cache = sc.SyntaxCache(tmp_path)
    monkeypatch.setattr(cache, "get", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("lookup")))
    long_path = "x" * sc.MAX_PATH_BYTES + ".py"
    assert extract.extract_code([doc(long_path, "")], "s", syntax_cache=cache).files_parsed == [long_path]
    monkeypatch.setattr(
        sc.metadata, "version", lambda name: (_ for _ in ()).throw(sc.metadata.PackageNotFoundError(name))
    )
    assert extract.extract_code([doc("a.py", "")], "s", syntax_cache=cache).files_parsed == ["a.py"]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("change", ["content", "path", "grammar", "profile", "walker", "schema"])
def test_extraction_reparses_on_each_key_change(tmp_path, monkeypatch, change):
    from hippo.codegraph import syntax_cache as sc

    cache = sc.SyntaxCache(tmp_path)
    docs = [doc("a.ts", "export function a() {}")]
    extract.extract_code(docs, "s", syntax_cache=cache)
    if change == "content":
        docs[0].text = "export function b() {}"
    elif change == "path":
        docs[0].title = "b.ts"
    elif change == "grammar":
        monkeypatch.setattr(sc, "grammar_for", lambda *args: "tsx")
        monkeypatch.setattr(extract, "grammar_for", lambda *args: "tsx")
    elif change == "profile":
        monkeypatch.setattr(sc.metadata, "version", lambda name: "next")
    elif change == "walker":
        monkeypatch.setattr(sc, "WALKER_RULES_VERSION", "next")
    else:
        monkeypatch.setattr(sc, "SCHEMA_VERSION", 2)
    walked = []
    original = extract._walk

    def walk(*args, **kwargs):
        walked.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(extract, "_walk", walk)
    extract.extract_code(docs, "s", syntax_cache=cache)
    assert walked == [docs[0].title]
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_hash_uses_the_exact_encoded_parser_input():
    import hashlib

    from hippo.codegraph.syntax_cache import cache_key

    text = "# \ud800\né"
    assert (
        cache_key("a.py", text, "python").input_hash
        == hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    )


def test_oversized_write_is_skipped_and_readonly_cache_is_optional(tmp_path):
    from hippo.codegraph.syntax_cache import SyntaxCache

    docs = [doc("a.py", "def a():\n    pass\n")]
    expected = extract.extract_code(docs, "s")
    tiny = SyntaxCache(tmp_path / "tiny", max_entry_bytes=10)
    assert asdict(extract.extract_code(docs, "s", syntax_cache=tiny)) == asdict(expected)
    assert not tiny.root.exists()
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    cache = SyntaxCache(blocker / "cache")
    assert asdict(extract.extract_code(docs, "s", syntax_cache=cache)) == asdict(expected)


def test_replaced_walker_disables_cache_reuse(tmp_path, monkeypatch):
    from hippo.codegraph.syntax_cache import SyntaxCache

    cache = SyntaxCache(tmp_path)
    docs = [doc("a.py", "def a():\n    pass\n")]
    extract.extract_code(docs, "s", syntax_cache=cache)
    original = extract.WALKERS["python"]
    walked = []

    def replacement(*args, **kwargs):
        facts = original(*args, **kwargs)
        facts.symbols[-1].doc = "replacement walker semantics"
        walked.append(True)
        return facts

    monkeypatch.setitem(extract.WALKERS, "python", replacement)
    actual = extract.extract_code(docs, "s", syntax_cache=cache)
    assert walked == [True]
    expected = extract.extract_code(docs, "s")
    assert asdict(actual) == asdict(expected)
    # Disabling reuse must also avoid replacing the canonical walker's entry.
    monkeypatch.setitem(extract.WALKERS, "python", original)
    canonical = extract.extract_code(docs, "s", syntax_cache=cache)
    assert canonical.symbols[-1].doc != "replacement walker semantics"


def test_unavailable_parser_does_not_replay_cache_when_metadata_exists(tmp_path, monkeypatch):
    from hippo.codegraph.syntax_cache import SyntaxCache, cache_key

    cache = SyntaxCache(tmp_path)
    docs = [doc("a.py", "def a():\n    pass\n")]
    extract.extract_code(docs, "s", syntax_cache=cache)
    assert cache_key(docs[0].title, docs[0].text, "python") is not None

    def unavailable(grammar):
        raise ImportError("installed metadata exists, but the parser runtime cannot load")

    monkeypatch.setattr(extract, "new_parser", unavailable)
    actual = extract.extract_code(docs, "s", syntax_cache=cache)
    assert actual.files_skipped == {"a.py": "parse_error"}
    assert asdict(actual) == asdict(extract.extract_code(docs, "s"))


def test_cache_hit_checks_one_parser_per_grammar_without_parsing(tmp_path, monkeypatch):
    from hippo.codegraph.syntax_cache import SyntaxCache

    cache = SyntaxCache(tmp_path)
    docs = [doc("a.py", "def a():\n    pass\n"), doc("b.py", "def b():\n    pass\n")]
    expected = extract.extract_code(docs, "s", syntax_cache=cache)
    constructed = []

    class ParserProbe:
        def parse(self, text):
            raise AssertionError("cache hits must not parse")

    def parser(grammar):
        constructed.append(grammar)
        return ParserProbe()

    monkeypatch.setattr(extract, "new_parser", parser)
    actual = extract.extract_code(docs, "s", syntax_cache=cache)
    assert asdict(actual) == asdict(expected)
    assert constructed == ["python"]
