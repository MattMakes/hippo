"""Exact match, F1, recall@k and gold rank: the pure scoring functions."""

from __future__ import annotations

import pytest

from hippo.evals.metrics import exact_match, f1, gold_rank, normalize_answer, recall_at_k

# ---------------------------------------------------------------- normalize


def test_normalize_lowercases_strips_punctuation_and_articles():
    assert normalize_answer("The Quick, brown Fox!") == "quick brown fox"


def test_normalize_collapses_whitespace_and_handles_empty():
    assert normalize_answer("  a   lot\tof   space ") == "lot of space"
    assert normalize_answer("") == ""
    assert normalize_answer("the") == ""


def test_normalize_only_removes_whole_word_articles():
    # "an" inside "Nathan" or "a" inside "Acme" must survive.
    assert normalize_answer("Nathan at Acme") == "nathan at acme"


# --------------------------------------------------------------- exact match


def test_exact_match_ignores_case_punctuation_and_articles():
    assert exact_match("Boulder", "boulder.") == 1.0
    assert exact_match("The University of Southampton", "university of southampton") == 1.0


def test_exact_match_is_strict_about_extra_words():
    assert exact_match("Boulder", "Boulder, Colorado") == 0.0


def test_exact_match_accepts_a_list_of_answers():
    assert exact_match(["Denver", "Boulder"], "boulder") == 1.0
    assert exact_match(["Denver", "Boulder"], "Portland") == 0.0
    assert exact_match([], "anything") == 0.0


# ----------------------------------------------------------------------- F1


def test_f1_is_one_for_the_same_words_in_any_order():
    assert f1("Priya Natarajan", "natarajan, priya") == 1.0


def test_f1_partial_overlap_matches_the_reference_formula():
    # gold: [university, of, southampton]; predicted: [southampton, university]
    # precision 2/2, recall 2/3 -> 0.8
    assert f1("University of Southampton", "Southampton University") == pytest.approx(0.8)


def test_f1_zero_without_common_words():
    assert f1("2015", "Boulder") == 0.0
    assert f1("", "Boulder") == 0.0
    assert f1("Boulder", "") == 0.0


def test_f1_takes_the_best_accepted_answer():
    assert f1(["Portland Oregon", "Boulder"], "Boulder") == 1.0


# ------------------------------------------------------------------ recall@k


def test_recall_at_k_counts_gold_passages_in_the_top_k():
    ranked = ["p1", "p2", "p3", "p4", "p5", "p6"]
    recall = recall_at_k(["p2", "p6"], ranked)
    assert recall == {
        "recall@1": 0.0,
        "recall@2": 0.5,
        "recall@5": 0.5,
        "recall@10": 1.0,
        "recall@20": 1.0,
    }


def test_recall_at_k_is_set_based_and_accepts_custom_ks():
    # Duplicates in the ranking do not count twice; gold not retrieved at all stays 0.
    assert recall_at_k(["p1"], ["p1", "p1", "p1"], ks=(1, 3)) == {"recall@1": 1.0, "recall@3": 1.0}
    assert recall_at_k(["p9"], ["p1", "p2"], ks=(1,)) == {"recall@1": 0.0}


def test_recall_at_k_without_gold_is_empty():
    assert recall_at_k([], ["p1", "p2"]) == {}


# ----------------------------------------------------------------- gold rank


def test_gold_rank_is_the_first_gold_position_one_based():
    assert gold_rank(["p3", "p5"], ["p1", "p2", "p3", "p4", "p5"]) == 3
    assert gold_rank(["p1"], ["p1"]) == 1


def test_gold_rank_is_none_when_missing_or_no_gold():
    assert gold_rank(["p9"], ["p1", "p2"]) is None
    assert gold_rank([], ["p1", "p2"]) is None
    assert gold_rank(["p1"], []) is None
