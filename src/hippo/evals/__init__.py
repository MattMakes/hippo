"""
Evaluations: asking hippo a list of questions and grading the answers.

This is how you find out whether the memory actually works, and whether a
settings change made it better or worse. The pieces, in the order you use them:

    question_maker.py  makes sample questions about one source (single-hop: one passage
                       answers it; multi-hop: you need two passages that share an entity;
                       code and commit: built from the code graph with no model call)
    runner.py          runs every question of a set: search -> answer -> judge -> metrics,
                       stores one result per question and a summary on the run, and
                       compares a set with code retrieval on against the same set with it off
    judge.py           asks the LLM whether an answer means the same as the expected one
    metrics.py         exact match / F1 (MRQA style, as in the HippoRAG paper) and
                       recall@k / gold rank for the retrieval side

Runs are history: once a run is done it is never changed, so you can compare
runs made before and after a tweak on the Evals page.
"""

from .judge import Verdict, judge
from .metrics import exact_match, f1, gold_rank, normalize_answer, recall_at_k
from .question_maker import code_questions, commit_questions, generate_questions, start_generation_job
from .runner import BASELINE_SETTINGS, compare_with_baseline, run_question, start_run, summarize

__all__ = [
    "BASELINE_SETTINGS",
    "Verdict",
    "code_questions",
    "commit_questions",
    "compare_with_baseline",
    "exact_match",
    "f1",
    "generate_questions",
    "gold_rank",
    "judge",
    "normalize_answer",
    "recall_at_k",
    "run_question",
    "start_generation_job",
    "start_run",
    "summarize",
]
