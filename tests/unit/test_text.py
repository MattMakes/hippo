"""
hipporag/text.py: the tiny helpers everything else leans on.

`clean_phrase` must produce the same node names as the reference's
`text_processing`, otherwise our graph would not match HippoRAG's. We pull that
function straight out of the reference source file (when it is on disk) and
compare, and we also keep hand-written expectations so the test still runs
without the reference checkout.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from hippo.hipporag.text import (
    clean_phrase,
    entity_id,
    fact_id,
    fact_text,
    is_meaningful_phrase,
    make_id,
    min_max_normalize,
)

REFERENCE_MISC_UTILS = Path("/home/user/osu-nlp-group/hipporag/src/hipporag/utils/misc_utils.py")

# Inputs that exercise every rule: case folding, punctuation -> space, whitespace collapse, non-strings.
PHRASES = [
    "Radio City",
    "Radio-City",
    "radio   city",
    "  The  QUICK brown_fox!! ",
    "PlanetRadiocity.com",
    "3 July 2001",
    "México's Straße",
    "a.b.c",
    "",
    "   ",
    "!!!",
    "Tab\tand\nnewline",
]


def reference_text_processing() -> Callable[[str], str]:
    """
    Load `text_processing` from the reference file without importing its package
    (the package pulls in heavy dependencies we do not install here).
    """
    module = ast.parse(REFERENCE_MISC_UTILS.read_text())
    function = next(
        node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "text_processing"
    )
    namespace: dict = {}
    exec(ast.unparse(function), namespace)  # noqa: S102 - trusted local file, test only
    return namespace["text_processing"]


# ----------------------------------------------------------------- clean_phrase


@pytest.mark.skipif(not REFERENCE_MISC_UTILS.exists(), reason="reference HippoRAG checkout not available")
@pytest.mark.parametrize("phrase", PHRASES + [42, 3.5, None])
def test_clean_phrase_matches_the_reference_text_processing(phrase) -> None:
    assert clean_phrase(phrase) == reference_text_processing()(phrase)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("Radio City", "radio city"),
        ("Radio-City", "radio city"),
        ("radio   city", "radio city"),
        ("  The  QUICK brown_fox!! ", "the quick brown fox"),
        ("PlanetRadiocity.com", "planetradiocity com"),
        ("3 July 2001", "3 july 2001"),
        ("a.b.c", "a b c"),
        ("", ""),
        ("   ", ""),
        ("!!!", ""),
        ("Tab\tand\nnewline", "tab and newline"),
    ],
)
def test_clean_phrase_examples(phrase: str, expected: str) -> None:
    assert clean_phrase(phrase) == expected


def test_clean_phrase_uses_casefold_so_german_sharp_s_becomes_ss() -> None:
    # casefold() is stronger than lower(): "ß" -> "ss". The reference does the same.
    assert clean_phrase("Straße") == "strasse"


def test_clean_phrase_accepts_non_strings() -> None:
    assert clean_phrase(2015) == "2015"
    assert clean_phrase(None) == "none"


def test_clean_phrase_is_idempotent() -> None:
    for phrase in PHRASES:
        once = clean_phrase(phrase)
        assert clean_phrase(once) == once


# -------------------------------------------------------------------------- ids


def test_make_id_is_prefix_plus_md5_like_the_reference_compute_mdhash_id() -> None:
    content = "acme robotics"
    assert make_id("entity-", content) == "entity-" + hashlib.md5(content.encode()).hexdigest()


def test_ids_are_stable_across_calls() -> None:
    assert entity_id("boulder") == entity_id("boulder")
    assert fact_id("a", "b", "c") == fact_id("a", "b", "c")


def test_entity_and_fact_ids_have_readable_prefixes() -> None:
    assert entity_id("boulder").startswith("entity-")
    assert fact_id("a", "b", "c").startswith("fact-")
    assert len(entity_id("boulder")) == len("entity-") + 32


def test_different_names_give_different_entity_ids() -> None:
    assert entity_id("boulder") != entity_id("denver")
    # Ids are made from the cleaned name, so cleaning must happen before calling entity_id.
    assert entity_id("Boulder") != entity_id("boulder")


def test_fact_id_depends_on_every_part_and_their_order() -> None:
    base = fact_id("acme robotics", "is headquartered in", "boulder")
    assert fact_id("acme robotics", "is located in", "boulder") != base
    assert fact_id("boulder", "is headquartered in", "acme robotics") != base
    # The parts are joined with a separator, so shifting text between parts changes the id.
    assert fact_id("a b", "c", "d") != fact_id("a", "b c", "d")


def test_fact_text_is_a_plain_sentence() -> None:
    assert (
        fact_text("acme robotics", "is headquartered in", "boulder")
        == "acme robotics is headquartered in boulder"
    )


# --------------------------------------------------------------- normalising


def test_min_max_normalize_scales_to_the_unit_interval() -> None:
    result = min_max_normalize(np.array([2.0, 4.0, 6.0]))
    assert result.tolist() == [0.0, 0.5, 1.0]


def test_min_max_normalize_constant_input_gives_all_ones() -> None:
    # Same rule as the reference: nothing separates the values, so treat them all as top.
    assert min_max_normalize(np.array([3.0, 3.0, 3.0])).tolist() == [1.0, 1.0, 1.0]


def test_min_max_normalize_single_value_gives_one() -> None:
    assert min_max_normalize(np.array([0.2])).tolist() == [1.0]


def test_min_max_normalize_empty_input_stays_empty() -> None:
    result = min_max_normalize(np.array([]))
    assert result.shape == (0,)


def test_min_max_normalize_accepts_plain_lists_and_returns_float64() -> None:
    result = min_max_normalize([1, 2, 3])
    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float64
    assert result.tolist() == [0.0, 0.5, 1.0]


def test_min_max_normalize_handles_negative_values() -> None:
    assert min_max_normalize(np.array([-1.0, 0.0, 1.0])).tolist() == [0.0, 0.5, 1.0]


def test_min_max_normalize_matches_the_reference_formula() -> None:
    values = np.array([0.1, 0.7, 0.4, 0.9])
    expected = (values - values.min()) / (values.max() - values.min())
    assert np.allclose(min_max_normalize(values), expected)


# --------------------------------------------------------- meaningful phrases


@pytest.mark.parametrize("phrase", ["a", "us", "12", "", "  ", "a-b", "!!"])
def test_tiny_phrases_are_not_meaningful(phrase: str) -> None:
    assert not is_meaningful_phrase(phrase)


@pytest.mark.parametrize("phrase", ["usa", "123", "a b c", "boulder", "2015"])
def test_phrases_with_more_than_two_letters_or_digits_are_meaningful(phrase: str) -> None:
    assert is_meaningful_phrase(phrase)
