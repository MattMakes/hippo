"""
hipporag/openie.py: the LLM reads a passage and hands back entities and triples.

FakeOllama plays the LLM. It only understands "X <relation> Y." sentences, so
these tests use the sample corpus and short sentences in that shape.
"""

from __future__ import annotations

from hippo.hipporag.openie import Extraction, clean_triples, extract, extract_many, valid_triples
from hippo.ollama import Ollama
from tests.fakes.fake_ollama import FakeOllama

COMPANY_PARAGRAPH = (
    "Acme Robotics was founded in 2015 by Priya Natarajan. Acme Robotics is headquartered in Boulder. "
    "Acme Robotics builds robot arms for small factories. Priya Natarajan lives in Denver."
)


# --------------------------------------------------------------- valid_triples


def test_valid_triples_keeps_only_three_part_lists_or_tuples() -> None:
    raw = [
        ["a", "b", "c"],
        ("d", "e", "f"),
        ["too", "short"],
        ["one", "two", "three", "four"],
        "not a triple",
        None,
        42,
        {"s": "a"},
    ]
    assert valid_triples(raw) == [["a", "b", "c"], ["d", "e", "f"]]


def test_valid_triples_turns_every_part_into_a_string() -> None:
    assert valid_triples([["Orion arm", "lifts", 12], [2019, "is", None]]) == [
        ["Orion arm", "lifts", "12"],
        ["2019", "is", "None"],
    ]


def test_valid_triples_drops_exact_duplicates_but_keeps_first_seen_order() -> None:
    raw = [["a", "b", "c"], ["x", "y", "z"], ["a", "b", "c"], ("x", "y", "z")]
    assert valid_triples(raw) == [["a", "b", "c"], ["x", "y", "z"]]


def test_valid_triples_of_nothing_is_nothing() -> None:
    assert valid_triples([]) == []


# --------------------------------------------------------------- clean_triples


def test_clean_triples_normalises_every_part() -> None:
    assert clean_triples([["Acme-Robotics", "Is Headquartered In", "  Boulder!  "]]) == [
        ("acme robotics", "is headquartered in", "boulder")
    ]


def test_clean_triples_drops_triples_whose_subject_or_object_vanishes() -> None:
    assert clean_triples([["!!!", "is", "boulder"], ["boulder", "is", "???"], ["boulder", "is", "nice"]]) == [
        ("boulder", "is", "nice")
    ]


def test_clean_triples_keeps_a_triple_with_an_empty_predicate() -> None:
    # Only the subject and object become graph nodes, so an empty predicate is odd but harmless.
    assert clean_triples([["boulder", "", "colorado"]]) == [("boulder", "", "colorado")]


def test_clean_triples_dedupes_after_cleaning() -> None:
    triples = [["Boulder", "is located in", "Colorado"], ["boulder", "is located in", "colorado"]]
    assert clean_triples(triples) == [("boulder", "is located in", "colorado")]


def test_clean_triples_returns_tuples() -> None:
    (only,) = clean_triples([["a", "b", "c"]])
    assert isinstance(only, tuple)


# ------------------------------------------------------------------ Extraction


def test_entity_names_are_unique_subjects_and_objects_in_first_seen_order() -> None:
    extraction = Extraction(
        passage_id="p",
        clean_triples=[
            ("acme robotics", "is headquartered in", "boulder"),
            ("boulder", "is located in", "colorado"),
            ("acme robotics", "was founded by", "priya natarajan"),
        ],
    )
    assert extraction.entity_names == ["acme robotics", "boulder", "colorado", "priya natarajan"]


def test_entity_names_of_an_empty_extraction_is_empty() -> None:
    assert Extraction(passage_id="p").entity_names == []


# --------------------------------------------------------------------- extract


def test_extract_on_a_sample_paragraph_yields_entities_and_cleaned_triples(ollama: Ollama) -> None:
    extraction = extract(ollama, "passage-1", COMPANY_PARAGRAPH)

    assert extraction.passage_id == "passage-1"
    assert extraction.error is None
    assert extraction.entities[:2] == ["Acme Robotics", "Priya Natarajan"]
    assert "Boulder" in extraction.entities
    # Raw triples keep the LLM's spelling; the founding sentence becomes two facts.
    assert extraction.triples == [
        ["Acme Robotics", "was founded in", "2015"],
        ["Acme Robotics", "was founded by", "Priya Natarajan"],
        ["Acme Robotics", "is headquartered in", "Boulder"],
        ["Acme Robotics", "builds", "robot arms for small factories"],
        ["Priya Natarajan", "lives in", "Denver"],
    ]
    assert extraction.clean_triples[2] == ("acme robotics", "is headquartered in", "boulder")
    assert all(part == part.lower() for triple in extraction.clean_triples for part in triple)
    assert extraction.entity_names == [
        "acme robotics",
        "2015",
        "priya natarajan",
        "boulder",
        "robot arms for small factories",
        "denver",
    ]


def test_extract_passes_the_entities_to_the_triple_prompt(fake_ollama: FakeOllama, ollama: Ollama) -> None:
    extract(ollama, "p", "Boulder is located in Colorado.")
    ner_call, triple_call = fake_ollama.calls
    assert ner_call["messages"][-1]["content"] == "Boulder is located in Colorado."
    assert '"named_entities": ["Boulder", "Colorado"]' in triple_call["messages"][-1]["content"]


def test_extract_of_a_passage_with_no_facts_is_empty_but_not_an_error(ollama: Ollama) -> None:
    extraction = extract(ollama, "p", "Nothing here matches a known relation.")
    assert extraction.error is None
    assert extraction.triples == []
    assert extraction.clean_triples == []


def test_extract_records_the_error_when_the_model_is_missing(fake_ollama: FakeOllama) -> None:
    broken = Ollama("http://fake-ollama", "missing:1b", "nomic-embed-text", client=fake_ollama.client())

    extraction = extract(broken, "passage-1", COMPANY_PARAGRAPH)  # must not raise

    assert extraction.error is not None
    assert "is the model installed" in extraction.error
    assert extraction.entities == []
    assert extraction.triples == []
    assert extraction.clean_triples == []


# ---------------------------------------------------------------- extract_many


def test_extract_many_keeps_the_input_order_and_reports_progress(ollama: Ollama) -> None:
    passages = [
        ("p-a", "Boulder is located in Colorado."),
        ("p-b", "Denver is located in Colorado."),
        ("p-c", "Portland is located in Oregon."),
    ]
    progress: list[tuple[int, int]] = []

    results = extract_many(
        ollama, passages, workers=2, on_progress=lambda done, total: progress.append((done, total))
    )

    assert [r.passage_id for r in results] == ["p-a", "p-b", "p-c"]
    assert [r.clean_triples[0][0] for r in results] == ["boulder", "denver", "portland"]
    assert sorted(progress) == [(1, 3), (2, 3), (3, 3)]


def test_extract_many_with_zero_workers_still_runs(ollama: Ollama) -> None:
    results = extract_many(ollama, [("p", "Boulder is located in Colorado.")], workers=0)
    assert len(results) == 1
    assert results[0].clean_triples == [("boulder", "is located in", "colorado")]


def test_extract_many_of_nothing_returns_nothing(ollama: Ollama) -> None:
    assert extract_many(ollama, []) == []
