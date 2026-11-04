"""Cloudflare's Clef wire format (Effect's ``CloudflareSchema``): the
questions and images of a decisions request and the answers of its
response, as ``TypedDict`` types with their schemas."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, NotRequired, TypedDict

from pyfect import schema as S
from pyfect._json_value import JsonValue

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
    criteria: Sequence[JsonValue]


class NoulCriteria(TypedDict):
    false: JsonValue
    true: JsonValue


class NoulQuestion(TypedDict):
    type: Literal["noul"]
    instructions: Entry
    criteria: NotRequired[NoulCriteria]


type Question = ChoiceQuestion | ScoreQuestion | NoulQuestion


class Base64Image(TypedDict):
    content_type: Literal["image/png", "image/jpeg", "image/webp"] | str
    base64: str


type Image = str | Base64Image
"""A ``data:`` URL or base64 data with its media type."""


class DecisionsRequest(TypedDict):
    model: Literal["clef", "clef-flash"] | str
    state: JsonValue
    questions: Mapping[str, Question]
    images: NotRequired[Sequence[Image]]


class ChoiceAnswer(TypedDict):
    type: Literal["choice"]
    choice: str
    probabilities: Mapping[str, float]
    confidence: float


class ScoreAnswer(TypedDict):
    type: Literal["score"]
    score: float
    probabilities: Mapping[str, float]
    """Probabilities by level index (``"0"``, ``"1"``, ...)."""
    confidence: float
    legend: Mapping[str, JsonValue]


class NoulAnswer(TypedDict):
    type: Literal["noul"]
    noul: float


type Answer = ChoiceAnswer | ScoreAnswer | NoulAnswer


class Usage(TypedDict):
    input_tokens: int
    output_tokens: int


class DecisionsResponse(TypedDict):
    model: str
    answers: Mapping[str, Answer]
    usage: Usage


CHOICE_QUESTION = S.Struct(
    ChoiceQuestion, instructions=ENTRY, criteria=S.Record(S.String, S.NullOr(ENTRY))
)
SCORE_QUESTION = S.Struct(ScoreQuestion, instructions=ENTRY)
NOUL_QUESTION = S.Struct(NoulQuestion, instructions=ENTRY)
QUESTION = S.Union(CHOICE_QUESTION, SCORE_QUESTION, NOUL_QUESTION)
IMAGE = S.Union(S.String, S.Struct(Base64Image, content_type=S.String))
DECISIONS_REQUEST = S.Struct(
    DecisionsRequest,
    model=S.String,
    questions=S.Record(S.String, QUESTION),
    images=S.Array(IMAGE),
)
CHOICE_ANSWER = S.Struct(ChoiceAnswer)
SCORE_ANSWER = S.Struct(ScoreAnswer)
NOUL_ANSWER = S.Struct(NoulAnswer)
ANSWER = S.Union(CHOICE_ANSWER, SCORE_ANSWER, NOUL_ANSWER)
DECISIONS_RESPONSE = S.Struct(DecisionsResponse, answers=S.Record(S.String, ANSWER))


__all__ = [
    "ANSWER",
    "CHOICE_ANSWER",
    "CHOICE_QUESTION",
    "DECISIONS_REQUEST",
    "DECISIONS_RESPONSE",
    "ENTRY",
    "IMAGE",
    "NOUL_ANSWER",
    "NOUL_QUESTION",
    "QUESTION",
    "SCORE_ANSWER",
    "SCORE_QUESTION",
    "Answer",
    "Base64Image",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "DecisionsRequest",
    "DecisionsResponse",
    "Entry",
    "Image",
    "NoulAnswer",
    "NoulCriteria",
    "NoulQuestion",
    "Question",
    "ScoreAnswer",
    "ScoreQuestion",
    "Usage",
]
