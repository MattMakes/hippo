"""
The fakes themselves: FakeOllama's parsers and rules must behave predictably,
because every other unit test trusts them.
"""

from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from hippo import prompts
from tests.fakes.fake_ollama import (
    DIM,
    FakeOllama,
    content_words,
    embed_text,
    parse_entities,
    parse_triples,
    sentences,
)
from tests.fakes.fake_store import FakeStore

# ---------------------------------------------------------------- the parsers


def test_the_sample_yields_34_triples(sample_text: str) -> None:
    triples = parse_triples(sample_text)
    assert len(triples) == 34
    assert ["Acme Robotics", "is headquartered in", "Boulder"] in triples
    assert ["Marcus Lee", "studied at", "Colorado School of Mines"] in triples


def test_a_founding_sentence_splits_into_a_year_and_a_founder() -> None:
    assert parse_triples("Acme Robotics was founded in 2015 by Priya Natarajan.") == [
        ["Acme Robotics", "was founded in", "2015"],
        ["Acme Robotics", "was founded by", "Priya Natarajan"],
    ]


def test_a_leading_the_is_stripped_from_subjects_and_objects() -> None:
    assert parse_triples("The Orion arm runs Nimbus. Nimbus depends on the Halo library.") == [
        ["Orion arm", "runs", "Nimbus"],
        ["Nimbus", "depends on", "Halo library"],
    ]


def test_sentences_without_a_known_relation_give_no_triples() -> None:
    assert parse_triples("Robots are fun. Nobody knows why.") == []


def test_the_longest_relation_wins() -> None:
    # "is the flagship product of" must not be cut down to "is ... of" or similar.
    assert parse_triples("The Orion arm is the flagship product of Acme Robotics.") == [
        ["Orion arm", "is the flagship product of", "Acme Robotics"]
    ]


def test_sample_entities_include_multi_word_names_and_years(sample_text: str) -> None:
    entities = parse_entities(sample_text)
    assert "Colorado School of Mines" in entities
    assert "Priya Natarajan" in entities
    assert "2015" in entities
    assert "The" not in entities
    assert len(entities) == len(set(entities))


def test_parse_entities_of_one_sentence() -> None:
    assert parse_entities("Marcus Lee studied at Colorado School of Mines.") == [
        "Marcus Lee",
        "Colorado School of Mines",
    ]


def test_sentences_splits_on_terminators() -> None:
    assert sentences("One thing. Another thing! Third?\nFourth.") == [
        "One thing.",
        "Another thing!",
        "Third?",
        "Fourth.",
    ]


def test_content_words_drop_stopwords() -> None:
    assert content_words("Where is the company headquartered?") == {"headquartered"}


# ------------------------------------------------------------------ embeddings


def test_embed_text_is_a_deterministic_unit_vector() -> None:
    vector = embed_text("Acme Robotics")
    assert vector.shape == (DIM,)
    assert np.isclose(np.linalg.norm(vector), 1.0)
    assert np.array_equal(vector, embed_text("Acme Robotics"))


def test_embed_text_ignores_case_and_the_ollama_prefixes() -> None:
    plain = embed_text("acme robotics")
    assert np.array_equal(embed_text("search_query: Acme Robotics"), plain)
    assert np.array_equal(embed_text("search_document: ACME ROBOTICS"), plain)


def test_similar_names_get_similar_vectors() -> None:
    same_ish = float(embed_text("Acme Robotics") @ embed_text("Acme Robotics Inc"))
    different = float(embed_text("Boulder") @ embed_text("Denver"))
    assert same_ish > 0.6
    assert different < 0.3


def test_embed_text_of_nothing_is_the_zero_vector() -> None:
    assert not embed_text("").any()


# ----------------------------------------------------------------- the rules


def test_filter_keeps_facts_that_share_a_content_word_with_the_question() -> None:
    fake = FakeOllama()
    candidates = [
        ["acme robotics", "is headquartered in", "boulder"],
        ["lyra gripper", "is made of", "aluminium"],
        ["boulder", "is located in", "colorado"],
    ]
    user = prompts.fact_filter_messages("Where is Acme Robotics headquartered?", candidates)[-1]["content"]
    assert fake.filter_facts(user) == [candidates[0]]


def test_filter_keeps_at_most_four_facts() -> None:
    fake = FakeOllama()
    candidates = [["boulder", "is", f"thing {i}"] for i in range(6)]
    user = prompts.fact_filter_messages("What about Boulder?", candidates)[-1]["content"]
    assert fake.filter_facts(user) == candidates[:4]


def test_answer_picks_the_best_sentence_and_returns_its_object() -> None:
    fake = FakeOllama()
    passages = [
        ("The company", "Acme Robotics is headquartered in Boulder. Priya Natarajan lives in Denver.")
    ]
    user = prompts.qa_messages("Where is Acme Robotics headquartered?", passages)[-1]["content"]
    thought, answer = prompts.split_answer(fake.answer(user))
    assert answer == "Boulder"
    assert "Acme Robotics is headquartered in Boulder." in thought


@pytest.mark.parametrize(
    ("expected", "actual", "verdict"),
    [
        ("Boulder", "It is Boulder.", "correct"),
        ("boulder", "BOULDER", "correct"),
        ("Boulder Colorado", "Colorado", "partially_correct"),
        ("Boulder", "Denver", "incorrect"),
        ("Boulder", "", "incorrect"),
    ],
)
def test_judge_rules(expected: str, actual: str, verdict: str) -> None:
    user = prompts.judge_messages("Where?", expected, actual)[-1]["content"]
    result = FakeOllama().judge(user)
    assert result["verdict"] == verdict
    assert result["reason"]


def test_questions_come_from_the_passage_triples() -> None:
    user = prompts.question_gen_messages("The company", "Acme Robotics is headquartered in Boulder.", 1)[-1][
        "content"
    ]
    assert FakeOllama().questions(user) == [
        {"question": "Acme Robotics is headquartered in what?", "answer": "Boulder"}
    ]


def test_multihop_question_chains_two_passages_on_the_shared_entity() -> None:
    user = prompts.multihop_gen_messages(
        "boulder",
        ("The company", "Acme Robotics is headquartered in Boulder."),
        ("Where things are", "Boulder is located in Colorado."),
    )[-1]["content"]
    result = FakeOllama().multihop_question(user)
    assert result["answer"] == "Colorado"
    assert result["question"].startswith("Acme Robotics is headquartered in something that")


def test_multihop_question_is_empty_when_no_chain_exists() -> None:
    user = prompts.multihop_gen_messages("boulder", ("A", "Nothing here."), ("B", "Nor here."))[-1]["content"]
    assert FakeOllama().multihop_question(user)["question"] == ""


# ------------------------------------------------------------ the transport


def test_transport_serves_tags_show_and_unknown_paths() -> None:
    fake = FakeOllama()
    with fake.client() as client:
        tags = client.get("/api/tags").json()
        assert [m["name"] for m in tags["models"]] == ["qwen3:8b", "nomic-embed-text:latest"]
        assert client.post("/api/show", json={"model": "qwen3:8b"}).json()["capabilities"] == [
            "completion",
            "thinking",
        ]
        assert client.post("/api/show", json={"model": "nope"}).status_code == 404
        assert client.get("/api/nothing").status_code == 404


def test_transport_records_chat_calls_and_answers_unknown_prompts() -> None:
    fake = FakeOllama()
    with fake.client() as client:
        response = client.post(
            "/api/chat", json={"model": "qwen3:8b", "messages": [{"role": "user", "content": "hi"}]}
        )
    assert response.status_code == 200
    assert json.loads(response.json()["message"]["content"]) == {"reply": "I am a fake model."}
    assert len(fake.calls) == 1


def test_transport_rejects_chat_and_embed_for_uninstalled_models() -> None:
    fake = FakeOllama(installed=[])
    with fake.client() as client:
        assert client.post("/api/chat", json={"model": "qwen3:8b", "messages": []}).status_code == 404
        assert (
            client.post("/api/embed", json={"model": "nomic-embed-text", "input": ["x"]}).status_code == 404
        )


def test_transport_pull_installs_the_model_with_a_default_tag() -> None:
    fake = FakeOllama(installed=[])
    with fake.client() as client:
        response = client.post("/api/pull", json={"model": "nomic-embed-text"})
    assert response.status_code == 200
    assert fake.installed == ["nomic-embed-text:latest"]
    assert isinstance(fake.transport(), httpx.MockTransport)


def test_fake_store_starts_empty() -> None:
    store = FakeStore()
    assert store.stats() == {
        "sources": 0,
        "passages": 0,
        "entities": 0,
        "facts": 0,
        "synonym_edges": 0,
        "mention_edges": 0,
        "question_sets": 0,
        "eval_runs": 0,
        "changesets": 0,
        "users": 0,
        "roles": 0,
    }
    assert store.graph_version() == 0
    assert store.ping()
