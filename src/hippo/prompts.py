"""
Every prompt the app sends to the language model, in one place.

The HippoRAG prompts (NER, triple extraction, fact filter, QA reading) are
carried over from the reference implementation so the technique is the same:
https://github.com/OSU-NLP-Group/HippoRAG/tree/main/src/hipporag/prompts

Two adaptations for a small local model:
* We ask Ollama to *constrain* the model's output to a JSON schema (its
  "structured outputs" feature), so the demos below show pure JSON instead of
  the DSPy `[[ ## field ## ]]` markers the reference used with GPT-4.
* Prompts we added ourselves (making sample questions, judging answers) are
  marked "hippo's own".

Each `*_messages(...)` function returns a chat conversation (a list of
{"role", "content"} dicts) ready to send. The matching `*_SCHEMA` says what
JSON we expect back.
"""

from __future__ import annotations

import json

# ============================================================== 1. NER (HippoRAG)

NER_SYSTEM = "Your task is to extract named entities from the given paragraph.\nRespond with a JSON list of entities.\n"

ONE_SHOT_PARAGRAPH = """Radio City
Radio City is India's first private FM radio station and was started on 3 July 2001.
It plays Hindi, English and regional songs.
Radio City recently forayed into New Media in May 2008 with the launch of a music portal - PlanetRadiocity.com that offers music related news, videos, songs, and other music-related features."""

ONE_SHOT_NER_OUTPUT = json.dumps(
    {
        "named_entities": [
            "Radio City",
            "India",
            "3 July 2001",
            "Hindi",
            "English",
            "May 2008",
            "PlanetRadiocity.com",
        ]
    }
)

NER_SCHEMA = {
    "type": "object",
    "properties": {"named_entities": {"type": "array", "items": {"type": "string"}}},
    "required": ["named_entities"],
}


def ner_messages(passage: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": NER_SYSTEM},
        {"role": "user", "content": ONE_SHOT_PARAGRAPH},
        {"role": "assistant", "content": ONE_SHOT_NER_OUTPUT},
        {"role": "user", "content": passage},
    ]


# ============================================= 2. Triple extraction (HippoRAG)

TRIPLES_SYSTEM = """Your task is to construct an RDF (Resource Description Framework) graph from the given passages and named entity lists.
Respond with a JSON list of triples, with each triple representing a relationship in the RDF graph.

Pay attention to the following requirements:
- Each triple should contain at least one, but preferably two, of the named entities in the list for each passage.
- Clearly resolve pronouns to their specific names to maintain clarity.

"""

TRIPLES_FRAME = """Convert the paragraph into a JSON dict, it has a named entity list and a triple list.
Paragraph:
```
{passage}
```

{named_entity_json}
"""

ONE_SHOT_TRIPLES_OUTPUT = json.dumps(
    {
        "triples": [
            ["Radio City", "located in", "India"],
            ["Radio City", "is", "private FM radio station"],
            ["Radio City", "started on", "3 July 2001"],
            ["Radio City", "plays songs in", "Hindi"],
            ["Radio City", "plays songs in", "English"],
            ["Radio City", "forayed into", "New Media"],
            ["Radio City", "launched", "PlanetRadiocity.com"],
            ["PlanetRadiocity.com", "launched in", "May 2008"],
            ["PlanetRadiocity.com", "is", "music portal"],
            ["PlanetRadiocity.com", "offers", "news"],
            ["PlanetRadiocity.com", "offers", "videos"],
            ["PlanetRadiocity.com", "offers", "songs"],
        ]
    }
)

TRIPLES_SCHEMA = {
    "type": "object",
    "properties": {
        "triples": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
        }
    },
    "required": ["triples"],
}


def triples_messages(passage: str, named_entities: list[str]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": TRIPLES_SYSTEM},
        {
            "role": "user",
            "content": TRIPLES_FRAME.format(
                passage=ONE_SHOT_PARAGRAPH, named_entity_json=ONE_SHOT_NER_OUTPUT
            ),
        },
        {"role": "assistant", "content": ONE_SHOT_TRIPLES_OUTPUT},
        {
            "role": "user",
            "content": TRIPLES_FRAME.format(
                passage=passage, named_entity_json=json.dumps({"named_entities": named_entities})
            ),
        },
    ]


# ================================ 3. Fact filter / "recognition memory" (HippoRAG)
# The reference calls this the DSPy filter. Its job: look at the handful of
# facts that embedding search found for a question, and keep only the ones
# that actually help answer it.

FACT_FILTER_SYSTEM = (
    "You are a critical component of a high-stakes question-answering system used by top researchers and "
    "decision-makers worldwide. Your task is to filter facts based on their relevance to a given query, ensuring "
    "that the most crucial information is presented to these stakeholders. The query requires careful analysis and "
    "possibly multi-hop reasoning to connect different pieces of information. You must select up to 4 relevant facts "
    "from the provided candidate list that have a strong connection to the query, aiding in reasoning and providing "
    'an accurate answer. The output should be in JSON format, e.g., {"fact": [["s1", "p1", "o1"], ["s2", "p2", "o2"]]}, '
    'and if no facts are relevant, return an empty list, {"fact": []}. The accuracy of your response is paramount, '
    "as it will directly impact the decisions made by these high-level stakeholders. You must only use facts from the "
    "candidate list and not generate new facts. The future of critical decision-making relies on your ability to "
    "accurately filter and present relevant information."
)

FACT_FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "fact": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
        }
    },
    "required": ["fact"],
}

# Ten worked examples from the reference (question, candidate facts, facts to keep).
FACT_FILTER_DEMOS: list[tuple[str, list[list[str]], list[list[str]]]] = [
    (
        "Are Imperial River (Florida) and Amaradia (Dolj) both located in the same country?",
        [
            ["imperial river", "is located in", "florida"],
            ["imperial river", "is a river in", "united states"],
            ["imperial river", "may refer to", "south america"],
            ["amaradia", "flows through", "ro ia de amaradia"],
            ["imperial river", "may refer to", "united states"],
        ],
        [
            ["imperial river", "is located in", "florida"],
            ["imperial river", "is a river in", "united states"],
            ["amaradia", "flows through", "ro ia de amaradia"],
        ],
    ),
    (
        "When is the director of film The Ancestor 's birthday?",
        [
            ["jean jacques annaud", "born on", "1 october 1943"],
            ["tsui hark", "born on", "15 february 1950"],
            ["pablo trapero", "born on", "4 october 1971"],
            ["the ancestor", "directed by", "guido brignone"],
            ["benh zeitlin", "born on", "october 14  1982"],
        ],
        [["the ancestor", "directed by", "guido brignone"]],
    ),
    (
        "In what geographic region is the country where Teafuone is located?",
        [
            ["teafuaniua", "is on the", "east"],
            ["motuloa", "lies between", "teafuaniua"],
            ["motuloa", "lies between", "teafuanonu"],
            ["teafuone", "is", "islet"],
            ["teafuone", "located in", "nukufetau"],
        ],
        [["teafuone", "is", "islet"], ["teafuone", "located in", "nukufetau"]],
    ),
    (
        "When did the director of film S.O.B. (Film) die?",
        [
            ["allan dwan", "died on", "28 december 1981"],
            ["s o b", "written and directed by", "blake edwards"],
            ["robert aldrich", "died on", "december 5  1983"],
            ["robert siodmak", "died on", "10 march 1973"],
            ["bernardo bertolucci", "died on", "26 november 2018"],
        ],
        [["s o b", "written and directed by", "blake edwards"]],
    ),
    (
        "Do both films: Gloria (1980 Film) and A New Life (Film) have the directors from the same country?",
        [
            ["sebasti n lelio watt", "received acclaim for directing", "gloria"],
            ["gloria", "is", "1980 american thriller crime drama film"],
            ["a brand new life", "is directed by", "ounie lecomte"],
            ["gloria", "written and directed by", "john cassavetes"],
            ["a new life", "directed by", "alan alda"],
        ],
        [
            ["gloria", "is", "1980 american thriller crime drama film"],
            ["gloria", "written and directed by", "john cassavetes"],
            ["a new life", "directed by", "alan alda"],
        ],
    ),
    (
        "What is the date of death of the director of film The Old Guard (1960 Film)?",
        [
            ["the old guard", "is", "1960 french comedy film"],
            ["gilles grangier", "directed", "the old guard"],
            ["the old guard", "directed by", "gilles grangier"],
            ["the old fritz", "directed by", "gerhard lamprecht"],
            ["oswald albert mitchell", "directed", "old mother riley series of films"],
        ],
        [
            ["the old guard", "is", "1960 french comedy film"],
            ["gilles grangier", "directed", "the old guard"],
            ["the old guard", "directed by", "gilles grangier"],
        ],
    ),
    (
        "When is the composer of film Aulad (1968 Film) 's birthday?",
        [
            ["aulad", "has music composed by", "chitragupta shrivastava"],
            ["aadmi sadak ka", "has music by", "ravi"],
            ["ravi shankar sharma", "composed music for", "hindi films"],
            ["gulzar", "was born on", "18 august 1934"],
            ["aulad", "is a", "1968 hindi language drama film"],
        ],
        [
            ["aulad", "has music composed by", "chitragupta shrivastava"],
            ["aulad", "is a", "1968 hindi language drama film"],
        ],
    ),
    (
        "How many households were in the city where Angelical Tears located?",
        [
            ["dow city", "had", "219 households"],
            ["tucson", "had", "229 762 households"],
            ["atlantic city", "has", "15 504 households"],
            ["angelical tears", "located in", "oklahoma city"],
            ["atlantic city", "had", "15 848 households"],
        ],
        [["angelical tears", "located in", "oklahoma city"]],
    ),
    (
        "Did the movies In The Pope'S Eye and Virgin Mountain, originate from the same country?",
        [
            ["virgin mountain", "released in", "icelandic cinemas"],
            ["virgin mountain", "directed by", "dagur k ri"],
            ["virgin mountain", "icelandic title is", "f si"],
            ["virgin mountain", "won", "2015 nordic council film prize"],
            ["virgin mountain", "is a", "2015 icelandic drama film"],
        ],
        [
            ["virgin mountain", "released in", "icelandic cinemas"],
            ["virgin mountain", "directed by", "dagur k ri"],
            ["virgin mountain", "icelandic title is", "f si"],
            ["virgin mountain", "won", "2015 nordic council film prize"],
            ["virgin mountain", "is a", "2015 icelandic drama film"],
        ],
    ),
    (
        "Which film has the director who died earlier, The Virtuous Model or Bulldog Drummond'S Peril?",
        [
            ["the virtuous model", "is", "1919 american silent drama film"],
            ["bulldog drummond s peril", "directed by", "james p  hogan"],
            ["the virtuous model", "directed by", "albert capellani"],
            ["bulldog drummond s revenge", "directed by", "louis king"],
            ["bulldog drummond s peril", "is", "american film"],
        ],
        [
            ["the virtuous model", "is", "1919 american silent drama film"],
            ["bulldog drummond s peril", "directed by", "james p  hogan"],
            ["the virtuous model", "directed by", "albert capellani"],
            ["bulldog drummond s peril", "is", "american film"],
        ],
    ),
]


def _fact_filter_input(question: str, facts: list[list[str]]) -> str:
    return f"Question: {question}\n\nCandidate facts (JSON): {json.dumps({'fact': facts})}\n\nReturn the relevant facts as JSON."


def fact_filter_messages(question: str, candidate_facts: list[list[str]]) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": FACT_FILTER_SYSTEM}]
    for demo_question, before, after in FACT_FILTER_DEMOS:
        messages.append({"role": "user", "content": _fact_filter_input(demo_question, before)})
        messages.append({"role": "assistant", "content": json.dumps({"fact": after})})
    messages.append({"role": "user", "content": _fact_filter_input(question, candidate_facts)})
    return messages


# ========================================= 4. Reading & answering (HippoRAG)
# The reference's one-shot "rag_qa" prompt: think out loud, then give a short answer after "Answer:".

QA_SYSTEM = (
    "As an advanced reading comprehension assistant, your task is to analyze text passages and corresponding "
    'questions meticulously. Your response start after "Thought: ", where you will methodically break down the '
    'reasoning process, illustrating how you arrive at conclusions. Conclude with "Answer: " to present a concise, '
    "definitive response, devoid of additional elaborations."
)

ONE_SHOT_QA_PASSAGES = (
    "Title: The Last Horse\nThe Last Horse (Spanish:El último caballo) is a 1950 Spanish comedy film directed by "
    "Edgar Neville starring Fernando Fernán Gómez.\n\n"
    "Title: Southampton\nThe University of Southampton, which was founded in 1862 and received its Royal Charter as a "
    "university in 1952, has over 22,000 students. The university is ranked in the top 100 research universities in "
    "the world in the Academic Ranking of World Universities 2010.\n\n"
    "Title: Stanton Township, Champaign County, Illinois\nStanton Township is a township in Champaign County, "
    "Illinois, USA. As of the 2010 census, its population was 505 and it contained 202 housing units.\n\n"
    "Title: Neville A. Stanton\nNeville A. Stanton is a British Professor of Human Factors and Ergonomics at the "
    "University of Southampton. Prof Stanton is a Chartered Engineer (C.Eng), Chartered Psychologist (C.Psychol) and "
    "Chartered Ergonomist (C.ErgHF). He has written and edited over a forty books and over three hundered "
    "peer-reviewed journal papers on applications of the subject.\n\n"
    "Title: Finding Nemo\nFinding Nemo Theatrical release poster Directed by Andrew Stanton Produced by Graham "
    "Walters Screenplay by Andrew Stanton Bob Peterson David Reynolds Story by Andrew Stanton Starring Albert Brooks "
    "Ellen DeGeneres Alexander Gould Willem Dafoe Music by Thomas Newman Release date May 30, 2003 Running time 100 "
    "minutes Country United States Language English\n\n"
)

ONE_SHOT_QA_INPUT = (
    ONE_SHOT_QA_PASSAGES + "Question: When was Neville A. Stanton's employer founded?\nThought: "
)
ONE_SHOT_QA_OUTPUT = (
    "The employer of Neville A. Stanton is University of Southampton. The University of Southampton was founded in 1862. "
    "\nAnswer: 1862."
)


def qa_messages(question: str, passages: list[tuple[str, str]]) -> list[dict[str, str]]:
    """`passages` is a list of (title, text) pairs, best first."""
    context = "".join(f"Title: {title}\n{text}\n\n" for title, text in passages)
    return [
        {"role": "system", "content": QA_SYSTEM},
        {"role": "user", "content": ONE_SHOT_QA_INPUT},
        {"role": "assistant", "content": ONE_SHOT_QA_OUTPUT},
        {"role": "user", "content": context + f"Question: {question}\nThought: "},
    ]


def split_answer(response: str) -> tuple[str, str]:
    """Split a QA reply into (thought, answer). If the model forgot 'Answer:', the whole reply is the answer."""
    if "Answer:" in response:
        thought, answer = response.rsplit("Answer:", 1)
        return thought.strip(), answer.strip()
    return "", response.strip()


# ================================================ 4b. The code graph (hippo's own)
# Two things that only exist when a question named code. Neither touches `rag_qa` above: the block
# rides in as one more `Title:`/text pair, which is why `qa_messages` stays byte-identical (D19).

CODE_GRAPH_HEADER = (
    "Relations read from the code graph, not from prose. INVOKES = calls, IMPORTS = imports, "
    "INHERITS = subclasses, OVERRIDES = replaces, CONTAINS = defines, RAISES / CATCHES = throws or "
    "handles, TESTED_BY = is covered by, READS / WRITES = uses or changes a table or collection. "
    "The number in brackets is a confidence between 0 and 1."
)

CODE_SELECT_SYSTEM = (
    "You are helping a code search tool decide what an engineer should read. You are given a "
    "question and a numbered list of passages, each with an id, a title and the first lines of its "
    'text. Return JSON with three lists of passage ids: "keep" for the passages that help answer '
    'the question, "drop" for the ones that do not, and "expand" for a passage whose immediate '
    "callees or subclasses would probably help too. Use only ids from the list. When in doubt, keep."
)

CODE_SELECT_SCHEMA = {
    "type": "object",
    "properties": {
        "keep": {"type": "array", "items": {"type": "string"}},
        "drop": {"type": "array", "items": {"type": "string"}},
        "expand": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["keep"],
}


def code_select_messages(question: str, passages: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    """`passages` is a list of (passage_id, title, preview), best first."""
    listed = "".join(f"id: {pid}\nTitle: {title}\n{preview}\n\n" for pid, title, preview in passages)
    return [
        {"role": "system", "content": CODE_SELECT_SYSTEM},
        {"role": "user", "content": f"Question: {question}\n\n{listed}Return the JSON."},
    ]


# ============================== 5. Making sample evaluation questions (hippo's own)

QUESTION_GEN_SYSTEM = (
    "You write evaluation questions for a question-answering system. Given a passage, write questions that a "
    "careful reader could answer from this passage alone. Rules:\n"
    "- Each question must be specific and self-contained: name the things it is about, never say 'the passage', "
    "'this document', 'the author' or 'the code above'.\n"
    "- The answer must be short (a name, number, date, phrase or one sentence) and appear in the passage.\n"
    "- Prefer questions about concrete facts: who, what, when, where, which, how many.\n"
    "- Do not invent anything that is not in the passage."
)

QUESTION_GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
                "required": ["question", "answer"],
            },
        }
    },
    "required": ["questions"],
}


def question_gen_messages(title: str, passage: str, how_many: int) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": QUESTION_GEN_SYSTEM},
        {
            "role": "user",
            "content": f"Passage title: {title}\n\nPassage:\n{passage}\n\nWrite {how_many} question/answer pairs as JSON.",
        },
    ]


MULTIHOP_GEN_SYSTEM = (
    "You write multi-hop evaluation questions. You are given TWO passages that share a common topic, and a hint "
    "about what they share. Write ONE question whose answer needs information from BOTH passages (for example: a "
    "fact from passage A identifies something, and passage B tells you a detail about it). Rules:\n"
    "- The question must be specific and self-contained; never mention 'the passages'.\n"
    "- The answer must be short and appear in the passages.\n"
    "- Explain in `reasoning` which fact from each passage is needed.\n"
    "- If no sensible two-passage question exists, return an empty question."
)

MULTIHOP_GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "answer": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["question", "answer", "reasoning"],
}


def multihop_gen_messages(
    shared_entity: str, passage_a: tuple[str, str], passage_b: tuple[str, str]
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": MULTIHOP_GEN_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Both passages mention: {shared_entity}\n\n"
                f"Passage A ({passage_a[0]}):\n{passage_a[1]}\n\n"
                f"Passage B ({passage_b[0]}):\n{passage_b[1]}\n\n"
                "Write one two-hop question as JSON."
            ),
        },
    ]


# ========================================= 6. Judging an answer (hippo's own)

JUDGE_SYSTEM = (
    "You grade answers from a question-answering system. Compare the system's answer with the expected answer. "
    "Judge meaning, not wording: 'the University of Southampton' and 'Southampton University' are the same. "
    "Verdicts:\n"
    "- correct: the system's answer contains the expected answer's meaning, possibly with extra correct detail.\n"
    "- partially_correct: it gets part of it right, or is right but too vague or mixed with a mistake.\n"
    "- incorrect: it is wrong, contradicts the expected answer, or says it does not know.\n"
    "Give a one-sentence reason."
)

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "partially_correct", "incorrect"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}


def judge_messages(question: str, expected: str, actual: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": JUDGE_SYSTEM},
        {
            "role": "user",
            "content": f"Question: {question}\nExpected answer: {expected}\nSystem's answer: {actual}\n\nGrade it as JSON.",
        },
    ]
