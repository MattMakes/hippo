"""Explicit-input computation plus a pre-refactor legacy call/output snapshot."""

import hashlib
import importlib
import json
from copy import deepcopy

import numpy as np
import pytest

from hippo.codegraph.model import CodeEdge, CodeGraph, DataObject, Symbol
from hippo.hipporag import indexer, openie
from hippo.hipporag.indexer import Chunk
from hippo.hipporag.text import entity_id, fact_id
from tests.fakes.fake_store import FakeStore


def preparation():
    try:
        return importlib.import_module("hippo.hipporag.preparation")
    except ModuleNotFoundError:
        pytest.fail("Shared index preparation is not implemented")


class Model:
    embed_model = "prepared-fixture"

    def __init__(self):
        self.embedded = []
        self.extracted = []

    def embed(self, texts, *, kind):
        self.embedded.append((list(texts), kind))
        return np.asarray([[len(text) / 100, 0.1, 0.3] for text in texts], dtype=np.float32).reshape(-1, 3)

    def chat_json(self, messages, schema, *, max_tokens):
        self.extracted.append(deepcopy(messages))
        return {"named_entities": ["ACME", "Robot"], "triples": [["ACME", "builds", "Robot"]]}


def code_fixture():
    return CodeGraph(
        source_id="source-prepared",
        symbols=[
            Symbol(
                id="symbol-service", source_id="source-prepared", name="OrderService", qualname="OrderService"
            ),
            Symbol(id="symbol-run", source_id="source-prepared", name="run", qualname="OrderService.run"),
        ],
        data_objects=[DataObject(id="data-orders", source_id="source-prepared", name="orders")],
        edges=[CodeEdge(a="symbol-service", b="symbol-run", kind="CONTAINS", omega=1.0)],
    )


def chunks_fixture():
    return [
        Chunk(3, "prose", "ACME builds Robot with `OrderService`."),
        Chunk(7, "body", "body must stay out of OpenIE", ["symbol-service"], ""),
        Chunk(8, "doc", "generated code body", ["symbol-run"], "ACME builds Robot. " * 5),
        Chunk(9, "tiny doc", "DDL or tiny doc body", ["data-orders"], "too short"),
    ]


def test_passage_preparation_uses_explicit_identity_and_preserves_text_and_order():
    model = Model()
    chunks = [Chunk(4, "first", " original \r\n"), Chunk(1, "second", "next")]
    result = preparation().prepare_passage_vectors(
        model, "source-managed", list(zip(["generation-p2", "generation-p1"], chunks, strict=True))
    )
    assert model.embedded == [([" original \r\n", "next"], "document")]
    assert [row["id"] for row in result.rows] == ["generation-p2", "generation-p1"]
    assert [row["ordinal"] for row in result.rows] == [4, 1]
    assert [row["text"] for row in result.rows] == [" original \r\n", "next"]
    assert all(row["source_id"] == "source-managed" for row in result.rows)
    np.testing.assert_array_equal(result.rows[0]["embedding"], result.vectors[0])
    chunks[0].text = "mutated caller chunk"
    assert result.rows[0]["text"] == " original \r\n"


def test_code_preparation_preserves_eligibility_history_definitions_and_detaches_rows():
    model = Model()
    code = code_fixture()
    code.commits = [{"id": "commit-one", "message": "retained message"}]
    code.modifies = [{"commit_id": "commit-one", "symbol_id": "symbol-run", "extra": {"lines": [1, 2]}}]
    code.precedes = [("commit-zero", "commit-one")]
    chunks = chunks_fixture()
    result = preparation().prepare_code_rows(model, code, [(f"prepared-{c.ordinal}", c) for c in chunks])
    assert model.embedded == [(["order service OrderService", "orders"], "document")]
    assert result.ids == ["symbol-service", "data-orders"]
    assert result.names == {"symbol-service": "order service OrderService", "data-orders": "orders"}
    assert result.symbols[1]["embedding"] == []
    assert result.definitions == [
        ("symbol-service", "prepared-7"),
        ("symbol-run", "prepared-8"),
        ("data-orders", "prepared-9"),
    ]
    assert result.commits == code.commits
    assert result.precedes == code.precedes
    code.modifies[0]["extra"]["lines"].append(3)
    code.symbols[0].raises.append("NewError")
    assert result.modifies[0]["extra"]["lines"] == [1, 2]
    assert result.symbols[0]["raises"] == []


def test_extraction_preparation_preserves_doc_gate_input_order_skip_rows_and_progress():
    model = Model()
    chunks = chunks_fixture()
    progress = []
    result = preparation().extract_chunk_prose(
        model,
        [(f"p-{c.ordinal}", c) for c in chunks],
        workers=1,
        on_progress=lambda done, total: progress.append((done, total)),
    )
    assert [row.passage_id for row in result] == ["p-3", "p-8", "p-7", "p-9"]
    assert result[0].clean_triples == [("acme", "builds", "robot")]
    assert result[2].triples == result[3].triples == []
    assert progress == [(1, 2), (2, 2)]
    messages = json.dumps(model.extracted)
    assert chunks[0].text in messages
    assert chunks[2].extract_text in messages
    assert "body must stay" not in messages
    assert "generated code body" not in messages
    assert "DDL or tiny doc body" not in messages


def test_extraction_preparation_retains_cancellation_before_any_model_call():
    model = Model()
    with pytest.raises(openie.Stopped):
        preparation().extract_chunk_prose(
            model, [("p1", Chunk(0, "title", "prose"))], workers=1, should_stop=lambda: True
        )
    assert model.extracted == []


def test_extraction_failure_remains_an_error_row():
    class BrokenModel(Model):
        def chat_json(self, messages, schema, *, max_tokens):
            raise ValueError("bad model response")

    result = preparation().extract_chunk_prose(BrokenModel(), [("p1", Chunk(0, "title", "prose"))], workers=1)
    assert len(result) == 1
    assert result[0].error == "ValueError: bad model response"
    assert result[0].clean_triples == []


def test_fact_payloads_preserve_normalized_endpoints_order_and_explicit_vector_subsets():
    extractions = [
        openie.Extraction("p2", entities=["not a graph node"], clean_triples=[("acme", "builds", "robot")]),
        openie.Extraction("p1", clean_triples=[("acme", "builds", "robot"), ("robot", "uses", "motor")]),
    ]
    payload = preparation().prepare_fact_payloads(extractions)
    acme, robot, motor = map(entity_id, ["acme", "robot", "motor"])
    builds, uses = fact_id("acme", "builds", "robot"), fact_id("robot", "uses", "motor")
    assert list(payload.names.items()) == [(acme, "acme"), (robot, "robot"), (motor, "motor")]
    assert payload.mentions == [("p2", acme), ("p2", robot), ("p1", acme), ("p1", robot), ("p1", motor)]
    assert payload.statements == [("p2", builds), ("p1", builds), ("p1", uses)]
    assert payload.entity_rows([motor], np.asarray([[1.0, 2.0]])) == [
        {"id": motor, "name": "motor", "embedding": [1.0, 2.0]}
    ]
    assert payload.fact_rows([uses], np.asarray([[3.0, 4.0]])) == [
        {
            "id": uses,
            "subject": "robot",
            "predicate": "uses",
            "object": "motor",
            "subject_id": robot,
            "object_id": motor,
            "embedding": [3.0, 4.0],
        }
    ]
    extractions[0].clean_triples.clear()
    assert payload.triples[builds] == ("acme", "builds", "robot")


def legacy_capture(monkeypatch):
    monkeypatch.setattr("tests.fakes.fake_store.new_id", lambda: "source-prepared")
    underlying = FakeStore()
    source = underlying.create_source("text", "prepared")
    calls = []
    writes = {
        "add_passages",
        "add_symbols",
        "add_data_objects",
        "add_commits",
        "add_modifies",
        "add_precedes",
        "add_code_edges",
        "link_definitions",
        "save_extraction",
        "add_entities",
        "link_passage_entities",
        "add_facts",
        "link_passage_facts",
        "add_synonyms",
        "add_refers_to",
        "set_symbol_communities",
        "set_meta",
        "bump_graph_version",
        "existing_entity_ids",
        "existing_fact_ids",
    }

    class Recorder:
        def __getattr__(self, name):
            target = getattr(underlying, name)
            if name not in writes:
                return target

            def call(*args, **kwargs):
                calls.append([name, deepcopy(args), deepcopy(kwargs)])
                return target(*args, **kwargs)

            return call

    model = Model()
    progress = []
    counts = []
    for _ in range(2):
        counts.append(
            indexer.index_source(
                Recorder(),
                model,
                source,
                chunks_fixture(),
                code=code_fixture(),
                synonymy_threshold=100.0,
                workers=1,
                on_progress=lambda *args: progress.append(args),
            )
        )
    return {
        "calls": calls,
        "model_inputs": model.embedded,
        "extraction_inputs": model.extracted,
        "progress": progress,
        "counts": counts,
    }


def test_legacy_mixed_source_write_and_model_trace_matches_pre_refactor_snapshot(monkeypatch):
    captured = legacy_capture(monkeypatch)
    assert captured["counts"] == [
        dict.fromkeys(indexer.COUNT_KEYS, 0)
        | {
            "passages": 4,
            "entities": 2,
            "facts": 1,
            "symbols": 2,
            "data_objects": 1,
            "code_edges": 1,
            "refers_to": 1,
        },
        dict.fromkeys(indexer.COUNT_KEYS, 0)
        | {"passages": 4, "symbols": 2, "data_objects": 1, "code_edges": 1, "refers_to": 1},
    ]
    # Captured before helper extraction: covers exact IDs, every row/vector, model
    # batch/text ordering, progress, existence queries, and the nine write counters.
    digest = hashlib.sha256(json.dumps(captured, sort_keys=True).encode()).hexdigest()
    assert digest == "6c5fcc9d729d26f7e7e92bf9b6a3f7969338b1e49bf99517552ea27e08521200"
