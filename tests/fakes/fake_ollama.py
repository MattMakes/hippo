"""
A rule-based stand-in for Ollama, served through an `httpx.MockTransport`.

It speaks just enough of Ollama's HTTP API for hippo:
  GET  /api/tags   POST /api/show   POST /api/pull   POST /api/chat   POST /api/embed

Embeddings are deterministic (hashed words + character trigrams), so similar
texts get similar vectors. Chat replies are produced by small rules keyed on
the system prompt, tuned to the simple "X <relation> Y." sentences in
samples/acme_robotics.md. Nothing here is clever; it only has to be predictable.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import httpx
import numpy as np

DIM = 128
STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "was",
    "are",
    "were",
    "of",
    "in",
    "by",
    "to",
    "for",
    "and",
    "or",
    "what",
    "which",
    "who",
    "where",
    "when",
    "how",
    "does",
    "do",
    "did",
    "that",
    "this",
    "it",
    "its",
    "on",
    "at",
    "with",
    "as",
    "from",
    "company",
    "state",
    "city",
    "product",
    "person",
    "thing",
    "something",
}

# Relations the fake extractor understands, longest first so "was founded in" beats "in".
RELATIONS = [
    "is the flagship product of",
    "is headquartered in",
    "is an accessory for",
    "is maintained by",
    "was designed by",
    "was created by",
    "was released in",
    "was founded in",
    "was founded by",
    "is written in",
    "is located in",
    "is managed by",
    "is owned by",
    "reports to",
    "depends on",
    "studied at",
    "is made of",
    "lives in",
    "builds",
    "lifts",
    "runs",
    "uses",
]
_RELATION_RE = re.compile(
    r"^(?P<s>.+?) (?P<p>" + "|".join(re.escape(r) for r in RELATIONS) + r") (?P<o>.+?)$"
)
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]")


def _strip_the(text: str) -> str:
    text = text.strip().rstrip(".")
    return text[4:] if text.lower().startswith("the ") else text


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]


def parse_triples(text: str) -> list[list[str]]:
    """'Acme Robotics was founded in 2015 by Priya Natarajan.' -> two triples."""
    triples: list[list[str]] = []
    for sentence in sentences(text):
        m = _RELATION_RE.match(sentence.rstrip(".!?"))
        if not m:
            continue
        s, p, o = _strip_the(m.group("s")), m.group("p"), _strip_the(m.group("o"))
        year_by = re.match(r"^(\d{4}) by (.+)$", o)
        if p == "was founded in" and year_by:
            triples.append([s, "was founded in", year_by.group(1)])
            triples.append([s, "was founded by", year_by.group(2)])
        else:
            triples.append([s, p, o])
    return triples


def parse_entities(text: str) -> list[str]:
    found: dict[str, None] = {}
    for sentence in sentences(text):
        words = sentence.rstrip(".!?").split()
        run: list[str] = []
        for word in words:
            if word[0].isupper() or (run and word in ("of",)):
                run.append(word)
            else:
                if run and run[-1] != "of":
                    found.setdefault(" ".join(run))
                run = []
        if run and run[-1] != "of":
            found.setdefault(" ".join(run))
        for year in re.findall(r"\b\d{4}\b", sentence):
            found.setdefault(year)
    return [e for e in found if e.lower() != "the"]


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS}


def embed_text(text: str) -> np.ndarray:
    """Feature-hash words and character trigrams into a fixed-size unit vector."""
    text = re.sub(r"^(search_query: |search_document: )", "", text).lower()
    vec = np.zeros(DIM, dtype=np.float32)
    words = re.findall(r"[a-z0-9]+", text)
    features = list(words)
    for word in words:
        padded = f" {word} "
        features.extend(padded[i : i + 3] for i in range(len(padded) - 2))
    for feature in features:
        digest = hashlib.md5(feature.encode()).digest()
        index = int.from_bytes(digest[:4], "little") % DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign * (2.0 if feature in words else 1.0)
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


class FakeOllama:
    """Create one, then pass `transport()` into `httpx.Client(transport=...)`."""

    def __init__(self, installed: list[str] | None = None):
        self.installed = list(installed if installed is not None else ["qwen3:8b", "nomic-embed-text:latest"])
        self.calls: list[dict[str, Any]] = []  # every chat request, for assertions

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://fake-ollama", transport=self.transport())

    # ------------------------------------------------------------ routing

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content or b"{}") if request.method == "POST" else {}
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in self.installed]})
        if path == "/api/show":
            name = body.get("model", "")
            if not any(m.startswith(name.split(":")[0]) for m in self.installed):
                return httpx.Response(404, json={"error": f"model '{name}' not found"})
            caps = ["completion", "thinking"] if "qwen3" in name else ["completion"]
            return httpx.Response(200, json={"capabilities": caps})
        if path == "/api/pull":
            name = body["model"]
            self.installed.append(name if ":" in name else name + ":latest")
            lines = [
                {"status": "pulling manifest"},
                {"status": "downloading", "completed": 50, "total": 100},
                {"status": "downloading", "completed": 100, "total": 100},
                {"status": "success"},
            ]
            return httpx.Response(200, content="\n".join(json.dumps(line) for line in lines).encode())
        if path == "/api/embed":
            if not self._installed(body["model"]):
                return httpx.Response(404, json={"error": f"model '{body['model']}' not found"})
            return httpx.Response(200, json={"embeddings": [embed_text(t).tolist() for t in body["input"]]})
        if path == "/api/chat":
            if not self._installed(body["model"]):
                return httpx.Response(404, json={"error": f"model '{body['model']}' not found"})
            self.calls.append(body)
            reply = self.chat(body["messages"])
            return httpx.Response(
                200, json={"message": {"role": "assistant", "content": reply}, "done_reason": "stop"}
            )
        return httpx.Response(404, json={"error": f"unknown path {path}"})

    def _installed(self, name: str) -> bool:
        full = name if ":" in name else name + ":latest"
        return name in self.installed or full in self.installed

    # --------------------------------------------------------------- chat

    def chat(self, messages: list[dict[str, str]]) -> str:
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        user = messages[-1]["content"]
        if system.startswith("Your task is to extract named entities"):
            return json.dumps({"named_entities": parse_entities(user)})
        if system.startswith("Your task is to construct an RDF"):
            passage = user.split("```")[1] if "```" in user else user
            return json.dumps({"triples": parse_triples(passage)})
        if system.startswith("You are a critical component"):
            return json.dumps({"fact": self.filter_facts(user)})
        if system.startswith("As an advanced reading comprehension"):
            return self.answer(user)
        if system.startswith("You write multi-hop evaluation questions"):
            return json.dumps(self.multihop_question(user))
        if system.startswith("You write evaluation questions"):
            return json.dumps({"questions": self.questions(user)})
        if system.startswith("You grade answers"):
            return json.dumps(self.judge(user))
        return json.dumps({"reply": "I am a fake model."})

    def filter_facts(self, user: str) -> list[list[str]]:
        question = re.search(r"Question: (.*)", user).group(1)
        facts = json.loads(re.search(r"Candidate facts \(JSON\): (\{.*\})", user).group(1))["fact"]
        words = content_words(question)
        kept = [f for f in facts if content_words(f[0] + " " + f[2]) & words]
        return kept[:4]

    def answer(self, user: str) -> str:
        context, question = user.rsplit("Question: ", 1)
        question = question.replace("Thought:", "").strip()
        words = content_words(question)
        best, best_overlap = "", -1
        for sentence in sentences(context):
            if sentence.startswith("Title:"):
                continue
            overlap = len(content_words(sentence) & words)
            if overlap > best_overlap:
                best, best_overlap = sentence, overlap
        m = _RELATION_RE.match(best.rstrip(".")) if best else None
        answer = _strip_the(m.group("o")) if m else best
        return f"The most relevant sentence is: {best}\nAnswer: {answer}"

    def questions(self, user: str) -> list[dict[str, str]]:
        passage = user.split("Passage:\n", 1)[1].split("\n\nWrite", 1)[0]
        how_many = int(re.search(r"Write (\d+) question", user).group(1))
        out = []
        for s, p, o in parse_triples(passage)[:how_many]:
            out.append({"question": f"{s} {p} what?", "answer": o})
        return out

    def multihop_question(self, user: str) -> dict[str, str]:
        shared = re.search(r"Both passages mention: (.*)", user).group(1).strip()
        a_text = user.split("Passage A", 1)[1].split("Passage B", 1)[0]
        b_text = user.split("Passage B", 1)[1]
        first = next((t for t in parse_triples(a_text) if t[2].lower() == shared.lower()), None)
        second = next((t for t in parse_triples(b_text) if t[0].lower() == shared.lower()), None)
        if not first or not second:
            return {"question": "", "answer": "", "reasoning": "no chain found"}
        return {
            "question": f"{first[0]} {first[1]} something that {second[1]} what?",
            "answer": second[2],
            "reasoning": f"{first} then {second}",
        }

    def judge(self, user: str) -> dict[str, str]:
        expected = re.search(r"Expected answer: (.*)", user).group(1)
        actual = re.search(r"System's answer: (.*)", user).group(1)
        norm = lambda t: " ".join(re.findall(r"[a-z0-9]+", t.lower()))  # noqa: E731
        if norm(expected) and norm(expected) in norm(actual):
            return {"verdict": "correct", "reason": "the expected answer appears in the system's answer"}
        if content_words(expected) & content_words(actual):
            return {"verdict": "partially_correct", "reason": "some of the expected answer appears"}
        return {"verdict": "incorrect", "reason": "the expected answer does not appear"}
