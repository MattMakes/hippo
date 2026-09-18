"""Model-local selector IDs translate back to durable passage identities."""

from __future__ import annotations

from typing import Any

from hippo import prompts
from hippo.hipporag.retriever import RankedPassage, Retriever


class RecordingModel:
    def __init__(self, *replies: dict[str, Any]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list[dict[str, str]], dict[str, Any], int]] = []

    def chat_json(self, messages, schema, *, max_tokens):
        self.calls.append((messages, schema, max_tokens))
        return self.replies.pop(0)


def candidate(passage_id: str, rank: int) -> RankedPassage:
    return RankedPassage(
        passage_id=passage_id,
        rank=rank,
        score=1.0 / rank,
        dpr_rank=rank,
        dpr_score=1.0 / rank,
        title=f"Candidate {rank}",
        source_id="source",
        source_name="Source",
        preview=f"Preview {rank}",
    )


def test_prompt_uses_ordered_short_ids_and_results_restore_durable_ids() -> None:
    durable = [
        "passage-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "passage-fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
        "passage-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ]
    model = RecordingModel({"keep": ["2", "1"], "drop": ["3"], "expand": ["1"]})

    result = Retriever(None, model).llm_select(
        "Which candidate matters?", [candidate(pid, rank) for rank, pid in enumerate(durable, 1)]
    )

    assert result.keep == [durable[1], durable[0]]
    assert result.drop == [durable[2]]
    assert result.expand == [durable[0]]
    assert result.raw == "{'keep': ['2', '1'], 'drop': ['3'], 'expand': ['1']}"
    assert len(model.calls) == 1
    messages, schema, max_tokens = model.calls[0]
    assert schema is prompts.CODE_SELECT_SCHEMA
    assert max_tokens == 512
    prompt = messages[-1]["content"]
    assert [line for line in prompt.splitlines() if line.startswith("id: ")] == [
        "id: 1",
        "id: 2",
        "id: 3",
    ]
    assert all(pid not in prompt for pid in durable)


def test_unknown_malformed_and_duplicate_values_create_no_passage_ids() -> None:
    durable = ["passage-alpha-long-durable-id", "passage-beta-long-durable-id"]
    reply = {
        "keep": ["2", "unknown", None, 1, "2", "02", durable[0]],
        "drop": ["1", "1", {}, " 1"],
        "expand": [False, "2", "2.0", "2"],
    }
    model = RecordingModel(reply)

    result = Retriever(None, model).llm_select(
        "Select exactly", [candidate(pid, rank) for rank, pid in enumerate(durable, 1)]
    )

    assert result.keep == [durable[1]]
    assert result.drop == [durable[0]]
    assert result.expand == [durable[1]]
    assert result.raw == str(reply)


def test_each_call_builds_its_mapping_from_that_calls_candidate_order() -> None:
    first = candidate("passage-first-durable-id", 1)
    second = candidate("passage-second-durable-id", 2)
    model = RecordingModel({"keep": ["1"]}, {"keep": ["1"]})
    retriever = Retriever(None, model)

    first_result = retriever.llm_select("first call", [first, second])
    second_result = retriever.llm_select("second call", [second, first])

    assert first_result.keep == [first.passage_id]
    assert second_result.keep == [second.passage_id]
    assert "id: 1\nTitle: Candidate 1" in model.calls[0][0][-1]["content"]
    assert "id: 1\nTitle: Candidate 2" in model.calls[1][0][-1]["content"]


def test_empty_candidates_skip_the_model() -> None:
    model = RecordingModel({"keep": ["1"]})

    result = Retriever(None, model).llm_select("nothing to select", [])

    assert result.keep == [] and result.drop == [] and result.expand == [] and result.raw == ""
    assert model.calls == []
