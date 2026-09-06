"""
Step 1 of HippoRAG: Open Information Extraction (OpenIE).

The LLM reads one passage and produces:
  1. named entities  (people, places, dates, products, functions...)
  2. triples         [subject, predicate, object] facts, e.g. ["Radio City", "located in", "India"]

Exactly like the reference, entities are extracted first and handed to the
triple prompt as hints. The graph nodes come from the triples' subjects and
objects (not from the NER list), so a name only becomes a node if it takes
part in a fact.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .. import prompts
from ..ollama import Ollama, OllamaError
from .text import clean_phrase

log = logging.getLogger(__name__)

NER_MAX_TOKENS = 512  # same limits as the reference's openie_ner_max_tokens / openie_triple_max_tokens
TRIPLES_MAX_TOKENS = 2048


@dataclass
class Extraction:
    passage_id: str
    entities: list[str] = field(default_factory=list)  # as the LLM wrote them
    triples: list[list[str]] = field(default_factory=list)  # as the LLM wrote them
    clean_triples: list[tuple[str, str, str]] = field(
        default_factory=list
    )  # lowercased, punctuation stripped, deduped
    error: str | None = None

    @property
    def entity_names(self) -> list[str]:
        """Unique cleaned subjects and objects, in first-seen order. These become the graph's phrase nodes."""
        seen: dict[str, None] = {}
        for subject, _, obj in self.clean_triples:
            seen.setdefault(subject)
            seen.setdefault(obj)
        return list(seen)


def extract(ollama: Ollama, passage_id: str, text: str) -> Extraction:
    """Run NER then triple extraction on one passage. Never raises: problems land in `.error`."""
    result = Extraction(passage_id=passage_id)
    try:
        ner = ollama.chat_json(prompts.ner_messages(text), prompts.NER_SCHEMA, max_tokens=NER_MAX_TOKENS)
        result.entities = _unique_strings(ner.get("named_entities", []))
        triples = ollama.chat_json(
            prompts.triples_messages(text, result.entities),
            prompts.TRIPLES_SCHEMA,
            max_tokens=TRIPLES_MAX_TOKENS,
        )
        result.triples = valid_triples(triples.get("triples", []))
        result.clean_triples = clean_triples(result.triples)
    except OllamaError as exc:
        log.warning("OpenIE failed for passage %s: %s", passage_id, exc)
        result.error = str(exc)
    return result


class Stopped(RuntimeError):
    """Raised when the caller asked us to stop (the job was cancelled or the app is shutting down)."""


def extract_many(
    ollama: Ollama,
    passages: list[tuple[str, str]],
    workers: int = 2,
    on_progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[Extraction]:
    """
    Extract from many (passage_id, text) pairs with a few parallel workers. Results keep the input order.
    `should_stop()` is checked before each passage; when it returns True, `Stopped` is raised.
    """
    results: dict[str, Extraction] = {}

    def extract_unless_stopped(pid: str, text: str) -> Extraction:
        if should_stop and should_stop():
            raise Stopped(f"stopped before passage {pid}")
        return extract(ollama, pid, text)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(extract_unless_stopped, pid, text): pid for pid, text in passages}
        for done, future in enumerate(as_completed(futures), start=1):
            extraction = future.result()
            results[extraction.passage_id] = extraction
            if on_progress:
                on_progress(done, len(passages))
    return [results[pid] for pid, _ in passages]


def valid_triples(raw: list) -> list[list[str]]:
    """Keep only 3-part triples, as strings, without duplicates (the reference's `filter_invalid_triples`)."""
    seen: set[tuple[str, ...]] = set()
    kept: list[list[str]] = []
    for triple in raw:
        if not isinstance(triple, list | tuple) or len(triple) != 3:
            continue
        as_strings = tuple(str(part) for part in triple)
        if as_strings in seen:
            continue
        seen.add(as_strings)
        kept.append(list(as_strings))
    return kept


def clean_triples(triples: list[list[str]]) -> list[tuple[str, str, str]]:
    """Normalise every part with `clean_phrase`; drop triples whose subject or object vanished."""
    seen: set[tuple[str, str, str]] = set()
    kept: list[tuple[str, str, str]] = []
    for subject, predicate, obj in triples:
        cleaned = (clean_phrase(subject), clean_phrase(predicate), clean_phrase(obj))
        if not cleaned[0] or not cleaned[2] or cleaned in seen:
            continue
        seen.add(cleaned)
        kept.append(cleaned)
    return kept


def _unique_strings(values: list) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        text = str(value).strip()
        if text:
            seen.setdefault(text)
    return list(seen)
