"""Task 5.1 / section 7.3 namespace requirements (G5NS).

1. Legacy identity formulas and omitted namespace calls remain compatible.
2. Managed native IDs hash canonical natural-key arrays and reject empty namespaces.
3. Five walkers preserve semantics and logical ownership across disjoint generations.
4. Resolver data, SQL containment, code endpoints and chunk definitions agree.
5. Git history, renamed historical blobs, MODIFIES and PRECEDES use one namespace.

Syntax cache rematerialization and writer validation are separate Task 5 increments.
"""

from dataclasses import asdict
from pathlib import Path

import pytest

from hippo.codegraph import extract, extract_code, git_history, resolve
from hippo.codegraph.languages import RULES
from hippo.codegraph.model import CodeGraph, commit_id, data_id, lang_of, symbol_id
from hippo.codegraph.treesitter import grammar_for, new_parser
from hippo.ingest import repos
from hippo.ingest.chunker import chunk_documents
from hippo.knowledge.identity import make_identity
from tests.conftest import CODE_SAMPLE_PATH, make_code_checkout
from tests.unit.test_git_history import AUDIT, add_commit, git_out, modified

SOURCE = "fixture"
LANGUAGES = ("python", "typescript", "go", "rust", "csharp")


@pytest.mark.parametrize(
    ("factory", "args", "frozen"),
    [
        (
            symbol_id,
            (SOURCE, "pyapp/orders.py", "OrderService.place", "method"),
            "symbol-65100dbff9dc8f41e3ac79ac692d86e3",
        ),
        (symbol_id, (SOURCE, "foo.py", "foo", "module"), "symbol-a26a2b8b74905c986df20827f7598e6e"),
        (data_id, (SOURCE, "table", "orders"), "data-89b7bc7122b6b1b7067425ad1303dabb"),
        (commit_id, (SOURCE, "0123456789abcdef"), "commit-fb5e2b5efcbb19413b5c5d0f6110453c"),
    ],
)
def test_legacy_ids_are_frozen(factory, args, frozen):
    assert factory(*args) == frozen
    assert factory(*args, node_namespace=None) == frozen


@pytest.mark.parametrize(
    ("factory", "args", "prefix", "key"),
    [
        (symbol_id, (SOURCE, "foo.py", "foo", "module"), "symbol", ["foo.py", "module:foo"]),
        (symbol_id, (SOURCE, "foo.py", "foo", "function"), "symbol", ["foo.py", "foo"]),
        (data_id, (SOURCE, "table", "orders"), "data", ["table", "orders"]),
        (commit_id, (SOURCE, "ABCdef"), "commit", ["ABCdef"]),
    ],
)
def test_managed_ids_hash_canonical_components(factory, args, prefix, key):
    actual = factory(*args, node_namespace="generation:α")
    assert actual == make_identity(prefix, [SOURCE, "generation:α", *key])
    assert actual != factory(*args, node_namespace="generation:β")
    assert actual != factory("other", *args[1:], node_namespace="generation:α")
    with pytest.raises(ValueError, match="namespace"):
        factory(*args, node_namespace="")


def test_managed_symbol_keys_preserve_component_boundaries_and_case():
    assert symbol_id("s", "a:b", "c", "function", node_namespace="n") != symbol_id(
        "s", "a", "b:c", "function", node_namespace="n"
    )
    assert symbol_id("s", "A.py", "Run", "function", node_namespace="n") != symbol_id(
        "s", "a.py", "Run", "function", node_namespace="n"
    )


@pytest.fixture(scope="module")
def fixture_docs():
    return list(repos.walk_repo(CODE_SAMPLE_PATH))


def semantic_node(node):
    row = asdict(node)
    row.pop("id")
    return row


def semantic_edges(graph):
    names = {s.id: ("symbol", s.path, s.qualname, s.kind) for s in graph.symbols}
    names.update({d.id: ("data", d.kind, d.qualname) for d in graph.data_objects})
    return sorted((names[e.a], names[e.b], e.kind, e.omega, e.provenance, repr(e.extra)) for e in graph.edges)


@pytest.mark.parametrize("language", LANGUAGES)
def test_all_walkers_keep_three_argument_calls_and_namespace_all_symbols(fixture_docs, language):
    documents = [doc for doc in fixture_docs if lang_of(doc.title) == language]
    assert documents
    for doc in documents:
        tree = new_parser(grammar_for(doc.title, language)).parse(doc.text.encode())
        walk = RULES[language].walk
        legacy = walk(doc.title, tree.root_node, SOURCE)
        first = walk(doc.title, tree.root_node, SOURCE, node_namespace="one")
        second = walk(doc.title, tree.root_node, SOURCE, node_namespace="two")
        assert first.node_namespace == "one"
        assert first.symbols
        assert {s.id for s in first.symbols}.isdisjoint(s.id for s in second.symbols)
        assert [semantic_node(s) for s in legacy.symbols] == [semantic_node(s) for s in first.symbols]
        assert [semantic_node(s) for s in first.symbols] == [semantic_node(s) for s in second.symbols]
        assert {s.source_id for s in first.symbols} == {SOURCE}
        for symbol in first.symbols:
            assert symbol.id == symbol_id(
                SOURCE, symbol.path, symbol.qualname, symbol.kind, node_namespace="one"
            )


def test_extraction_resolver_edges_and_chunk_definitions_share_namespace(fixture_docs):
    legacy = extract_code(fixture_docs, SOURCE)
    assert legacy == extract_code(fixture_docs, SOURCE, node_namespace=None)
    first = extract_code(fixture_docs, SOURCE, node_namespace="one")
    second = extract_code(fixture_docs, SOURCE, node_namespace="two")
    assert first.source_id == SOURCE
    assert first.node_namespace == "one"
    assert {s.lang for s in first.symbols} == set(LANGUAGES)
    assert legacy.stats() == first.stats() == second.stats()
    assert semantic_edges(legacy) == semantic_edges(first) == semantic_edges(second)
    assert [semantic_node(d) for d in legacy.data_objects] == [semantic_node(d) for d in first.data_objects]
    assert {d.kind for d in first.data_objects} >= {"table", "column", "collection"}
    ids = {n.id for n in [*first.symbols, *first.data_objects]}
    assert ids.isdisjoint(n.id for n in [*second.symbols, *second.data_objects])
    for data in first.data_objects:
        assert data.source_id == SOURCE
        assert data.id == data_id(SOURCE, data.kind, data.qualname, node_namespace="one")
    assert all(edge.a in ids and edge.b in ids for edge in first.edges)
    chunks = chunk_documents(fixture_docs, 1200, 100, code=first)
    defined = {node_id for chunk in chunks for node_id in chunk.defines}
    assert defined == ids


def test_empty_namespace_is_rejected_even_without_nodes(tmp_path):
    with pytest.raises(ValueError, match="namespace"):
        extract_code([], SOURCE, node_namespace="")
    with pytest.raises(ValueError, match="namespace"):
        CodeGraph(source_id=SOURCE, node_namespace="")
    with pytest.raises(ValueError, match="namespace"):
        git_history.read_history(tmp_path, [], SOURCE, node_namespace="", depth=0, timeout_s=10, total_s=120)


def test_empty_namespace_is_rejected_for_empty_sql():
    with pytest.raises(ValueError, match="namespace"):
        resolve.sql_file_objects(SOURCE, "empty.sql", "", node_namespace="")


def test_omitted_namespace_supports_registered_three_argument_walkers(fixture_docs, monkeypatch):
    original = RULES["python"].walk

    def legacy_walk(path, root, source_id):
        return original(path, root, source_id)

    monkeypatch.setitem(extract.WALKERS, "python", legacy_walk)
    docs = [doc for doc in fixture_docs if lang_of(doc.title) == "python"]
    graph = extract_code(docs, SOURCE)
    assert graph.symbols
    assert graph.files_skipped == {}


def test_git_history_namespaces_commits_renames_old_blobs_and_chunk_definitions(tmp_path: Path):
    checkout = make_code_checkout(tmp_path)
    orders = checkout / "pyapp/orders.py"
    orders.write_text(
        orders.read_text().replace("class OrderService(Base):", AUDIT + "class OrderService(Base):")
    )
    add_commit(checkout, "Insert audit above service")
    orders.rename(checkout / "pyapp/service.py")
    add_commit(checkout, "Rename orders to service")
    docs = list(repos.walk_repo(checkout))
    graphs = [extract_code(docs, SOURCE, node_namespace=namespace) for namespace in ("one", "two")]
    histories = []
    for graph in graphs:
        history = git_history.read_history(
            checkout,
            graph.symbols,
            SOURCE,
            node_namespace=graph.node_namespace,
            depth=200,
            timeout_s=10,
            total_s=120,
        )
        histories.append(history)
        commit_ids = {c["id"] for c in history.commits}
        symbol_ids = {s.id for s in graph.symbols}
        assert history.skipped == 0
        assert len(history.commits) == 5
        for commit in history.commits:
            assert commit["source_id"] == SOURCE
            assert commit["id"] == commit_id(SOURCE, commit["sha"], node_namespace=graph.node_namespace)
        assert all(
            row["commit_id"] in commit_ids and row["symbol_id"] in symbol_ids for row in history.modifies
        )
        ids = [c["id"] for c in history.commits]
        assert history.precedes == list(zip(ids, ids[1:], strict=False))
        touched = modified(history, graph.symbols, key=lambda s: (s.path, s.qualname))
        assert touched[3] == {("pyapp/service.py", "OrderService.place")}
        sha = git_out(checkout, "rev-parse", "HEAD~3").strip()
        old = git_history._symbols_at(
            checkout,
            sha,
            "pyapp/orders.py",
            "pyapp/service.py",
            SOURCE,
            {},
            10,
            node_namespace=graph.node_namespace,
        )
        assert old and {s.id for s in old} <= symbol_ids
        assert {s.source_id for s in old} == {SOURCE}
        graph.commits, graph.modifies, graph.precedes = history.commits, history.modifies, history.precedes
        defined = {
            node_id for chunk in chunk_documents(docs, 1200, 100, code=graph) for node_id in chunk.defines
        }
        assert commit_ids <= defined
        assert defined <= symbol_ids | {d.id for d in graph.data_objects} | commit_ids
    assert {c["id"] for c in histories[0].commits}.isdisjoint(c["id"] for c in histories[1].commits)
    assert modified(histories[0], graphs[0].symbols) == modified(histories[1], graphs[1].symbols)
