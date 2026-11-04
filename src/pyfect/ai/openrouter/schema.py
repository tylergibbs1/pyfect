"""OpenRouter's alpha Decisions API wire format (Effect's
``OpenRouterSchema``): the questions of a decisions request and the
answers of its response, as ``TypedDict`` types with their schemas.
Instructions and descriptions are strings, JSON objects or JSON arrays (a
choice's description may also be ``None``); an answer's probabilities and
confidence are optional."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, NotRequired, TypedDict

from pyfect import schema as S
from pyfect._json_value import JsonValue
from pyfect.ai.openrouter import generated as G
from pyfect.ai.openrouter.generated import types as GT

type Entry = str | Mapping[str, JsonValue] | Sequence[JsonValue]
"""Instructions or a description: a string, a JSON object or a JSON array."""

ENTRY = S.Union(S.String, S.JsonObject, S.Array(S.Json))


class ChoiceQuestion(TypedDict):
    type: Literal["choice"]
    instructions: Entry
    criteria: Mapping[str, Entry | None]


class ScoreQuestion(TypedDict):
    type: Literal["score"]
    instructions: Entry
    criteria: Sequence[Entry]


class NoulCriteria(TypedDict):
    true: Entry
    false: Entry


class NoulQuestion(TypedDict):
    type: Literal["noul"]
    instructions: Entry
    criteria: NotRequired[NoulCriteria]


type DecisionsQuestion = ChoiceQuestion | ScoreQuestion | NoulQuestion


class ChoiceAnswer(TypedDict):
    type: Literal["choice"]
    choice: str
    confidence: NotRequired[float]
    probabilities: NotRequired[Mapping[str, float]]


class ScoreAnswer(TypedDict):
    type: Literal["score"]
    score: float
    confidence: NotRequired[float]
    probabilities: NotRequired[Mapping[str, float]]
    """Probabilities by level index (``"0"``, ``"1"``, ...)."""
    legend: NotRequired[Mapping[str, JsonValue]]


class NoulAnswer(TypedDict):
    type: Literal["noul"]
    noul: float


type Answer = ChoiceAnswer | ScoreAnswer | NoulAnswer


class DecisionsOptions(TypedDict, total=False):
    """A decisions request's routing and tracing options."""

    provider: GT.ProviderPreferences
    session_id: str
    user: str
    trace: Mapping[str, object]


class DecisionsRequest(DecisionsOptions):
    model: str
    state: object
    questions: Mapping[str, DecisionsQuestion]


class Usage(TypedDict):
    input_tokens: int
    output_tokens: int
    cost: NotRequired[float]


class DecisionsResponse(TypedDict):
    model: str
    answers: Mapping[str, Answer]
    usage: Usage
    id: NotRequired[str]
    provider: NotRequired[str]


_PROBABILITIES = S.Record(S.String, S.Finite)

CHOICE_QUESTION = S.Struct(
    ChoiceQuestion, instructions=ENTRY, criteria=S.Record(S.String, S.NullOr(ENTRY))
)
SCORE_QUESTION = S.Struct(ScoreQuestion, instructions=ENTRY, criteria=S.Array(ENTRY))
NOUL_QUESTION = S.Struct(
    NoulQuestion,
    instructions=ENTRY,
    criteria=S.Struct(NoulCriteria, true=ENTRY, false=ENTRY),
)
DECISIONS_QUESTION = S.Union(CHOICE_QUESTION, SCORE_QUESTION, NOUL_QUESTION)
CHOICE_ANSWER = S.Struct(ChoiceAnswer, confidence=S.Finite, probabilities=_PROBABILITIES)
SCORE_ANSWER = S.Struct(
    ScoreAnswer,
    score=S.Finite,
    confidence=S.Finite,
    probabilities=_PROBABILITIES,
    legend=S.Record(S.String, S.Json),
)
NOUL_ANSWER = S.Struct(NoulAnswer, noul=S.Finite)
ANSWER = S.Union(CHOICE_ANSWER, SCORE_ANSWER, NOUL_ANSWER)
DECISIONS_REQUEST = S.Struct(
    DecisionsRequest,
    state=S.Unknown,
    questions=S.Record(S.String, DECISIONS_QUESTION),
    provider=G.ProviderPreferences,
    trace=S.Record(S.String, S.Unknown),
)
DECISIONS_RESPONSE = S.Struct(
    DecisionsResponse,
    answers=S.Record(S.String, ANSWER),
    usage=S.Struct(Usage, cost=S.Finite),
)


__all__ = [
    "ANSWER",
    "CHOICE_ANSWER",
    "CHOICE_QUESTION",
    "DECISIONS_QUESTION",
    "DECISIONS_REQUEST",
    "DECISIONS_RESPONSE",
    "ENTRY",
    "NOUL_ANSWER",
    "NOUL_QUESTION",
    "SCORE_ANSWER",
    "SCORE_QUESTION",
    "Answer",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "DecisionsOptions",
    "DecisionsQuestion",
    "DecisionsRequest",
    "DecisionsResponse",
    "Entry",
    "NoulAnswer",
    "NoulCriteria",
    "NoulQuestion",
    "ScoreAnswer",
    "ScoreQuestion",
    "Usage",
]
