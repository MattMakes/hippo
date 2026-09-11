"""
The numbers we put next to an answer.

Two of them grade the *answer text* and are copied from the reference
implementation (hipporag/evaluation/qa_eval.py, which follows the official
MRQA evaluation script):

* exact match (EM): 1.0 when the normalised answer equals a normalised
  expected answer, else 0.0
* F1: word overlap between the answer and the expected answer

"Normalised" means lowercase, no punctuation, no "a"/"an"/"the", single
spaces, so "The Boulder." and "boulder" count as the same thing.

Two of them grade the *retrieval*: did the passages we know hold the answer
(the "gold" passages) come out near the top of the ranking?

* recall@k: what share of the gold passages are in the top k
* gold rank: the position (1-based) of the first gold passage, or None

All functions are pure: no LLM, no store, no side effects.
"""

from __future__ import annotations

import re
import string
from collections import Counter
from collections.abc import Iterable, Sequence

# An expected answer, or several accepted spellings of it.
Expected = str | Sequence[str]

DEFAULT_KS = (1, 2, 5, 10, 20)


def normalize_answer(text: str) -> str:
    """Lowercase, drop punctuation and articles, collapse spaces. Same steps, same order as the reference."""

    def remove_articles(value: str) -> str:
        return re.sub(r"\b(a|an|the)\b", " ", value)

    def white_space_fix(value: str) -> str:
        return " ".join(value.split())

    def remove_punc(value: str) -> str:
        exclude = set(string.punctuation)
        return "".join(ch for ch in value if ch not in exclude)

    def lower(value: str) -> str:
        return value.lower()

    return white_space_fix(remove_articles(remove_punc(lower(text or ""))))


def _accepted(expected: Expected) -> list[str]:
    """One expected answer or a list of them -> always a list."""
    if isinstance(expected, str):
        return [expected]
    return [str(item) for item in expected]


def exact_match(expected: Expected, actual: str) -> float:
    """1.0 if the answer matches any accepted answer after normalisation, else 0.0."""
    predicted = normalize_answer(actual)
    scores = [1.0 if normalize_answer(gold) == predicted else 0.0 for gold in _accepted(expected)]
    # The reference aggregates over accepted answers with max: any one match is a hit.
    return max(scores) if scores else 0.0


def _f1_one(gold: str, predicted: str) -> float:
    gold_tokens = normalize_answer(gold).split()
    predicted_tokens = normalize_answer(predicted).split()
    common = Counter(predicted_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(predicted_tokens)
    recall = num_same / len(gold_tokens)
    return 2 * (precision * recall) / (precision + recall)


def f1(expected: Expected, actual: str) -> float:
    """Word-overlap F1 against the best-matching accepted answer (0.0 .. 1.0)."""
    scores = [_f1_one(gold, actual) for gold in _accepted(expected)]
    return max(scores) if scores else 0.0


def recall_at_k(
    gold_ids: Iterable[str], ranked_ids: Sequence[str], ks: Sequence[int] = DEFAULT_KS
) -> dict[str, float]:
    """
    {"recall@1": ..., "recall@5": ...}: the share of gold passages found in the top k.

    Set-based, so duplicates in either list do not count twice. With no gold
    passages there is nothing to measure and the result is an empty dict
    (the runner and summary treat "missing" differently from 0.0).
    """
    gold = set(gold_ids)
    if not gold:
        return {}
    ranked = list(ranked_ids)
    return {f"recall@{k}": len(gold & set(ranked[:k])) / len(gold) for k in ks}


def gold_rank(gold_ids: Iterable[str], ranked_ids: Iterable[str]) -> int | None:
    """The 1-based position of the first gold passage in the ranking, or None if none made it."""
    gold = set(gold_ids)
    if not gold:
        return None
    for position, passage_id in enumerate(ranked_ids, start=1):
        if passage_id in gold:
            return position
    return None


def evidence_set_metrics(
    alternatives: Sequence[Sequence[str]], ranked_ids: Sequence[str], ks: Sequence[int] = (5, 10, 20)
) -> dict[str, float]:
    """Score sufficient OR sets containing AND evidence, at unique-evidence ranks.

    Empty gold is unscorable ({}), not an automatic success or an abstention score.
    Recall is the best fraction of any sufficient set. MRR and binary nDCG use the
    union of relevant evidence; nDCG is a ranking diagnostic, not set sufficiency.
    """
    import math

    if not alternatives:
        return {}
    sets = [set(group) for group in alternatives]
    if any(not group for group in sets):
        raise ValueError("alternative evidence sets must be nonempty")
    if any(k <= 0 for k in ks):
        raise ValueError("metric cutoffs must be positive")
    gold = set().union(*sets)
    ranked = list(dict.fromkeys(ranked_ids))
    first = gold_rank(gold, ranked)
    dcg = sum(1 / math.log2(i + 2) for i, item in enumerate(ranked[:10]) if item in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(10, len(gold))))
    scores = {"mrr": 1 / first if first else 0.0, "ndcg@10": dcg / ideal}
    for k in ks:
        retrieved = set(ranked[:k])
        scores[f"any_hit@{k}"] = float(bool(retrieved & gold))
        scores[f"evidence_recall@{k}"] = max(len(retrieved & group) / len(group) for group in sets)
        scores[f"all_required_set_success@{k}"] = float(any(group <= retrieved for group in sets))
    return scores


def passage_evidence_metrics(
    alternatives: Sequence[Sequence[str]],
    ranked_candidates: Sequence[Sequence[str]],
    *,
    total_relevant_passages: int,
    ks: Sequence[int] = (5, 10, 20),
) -> dict[str, float]:
    """Coverage and binary nDCG at original passage ranks, including distractors.

    Each original passage occupies one slot, even when it contains several gold
    units or repeats evidence from a different passage. IDCG uses the number of
    relevant passages in the entire indexed universe, supplied independently of
    the returned ranking. Set sufficiency remains a separate metric.
    """
    import math

    if not alternatives:
        return {}
    groups = [set(group) for group in alternatives]
    if any(not group for group in groups):
        raise ValueError("alternative evidence sets must be nonempty")
    if any(k <= 0 for k in ks):
        raise ValueError("metric cutoffs must be positive")
    relevant = set().union(*groups)
    gains = [int(bool(set(candidate) & relevant)) for candidate in ranked_candidates]
    if total_relevant_passages < sum(gains) or total_relevant_passages < 0:
        raise ValueError("relevance universe smaller than retrieved relevant passages")
    first = next((i for i, gain in enumerate(gains, 1) if gain), None)
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains[:10]))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(10, total_relevant_passages)))
    scores = {"mrr": 1 / first if first else 0.0}
    if ideal:
        scores["ndcg@10"] = dcg / ideal
    # No indexed relevant passages means nDCG is undefined, while gold evidence
    # recall still correctly scores zero: an extraction miss is not a coverage gap.
    for k in ks:
        retrieved = set().union(*(set(c) for c in ranked_candidates[:k]))
        scores[f"any_hit@{k}"] = float(bool(retrieved & relevant))
        scores[f"evidence_recall@{k}"] = max(len(retrieved & group) / len(group) for group in groups)
        scores[f"all_required_set_success@{k}"] = float(any(group <= retrieved for group in groups))
    return scores
