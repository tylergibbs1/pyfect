"""TypeSafe's System One wire format (Effect's ``TypeSafeSchema``): the
questions of a ``/systemone`` request, the answers of its response and the
``/models`` list, as ``TypedDict`` types with their schemas."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, NotRequired, TypedDict

from pyfect import schema as S
from pyfect._json_value import JsonValue

type Entry = str | Mapping[str, JsonValue] | Sequence[JsonValue] | None
"""Instructions or a description: a string, a JSON object, a JSON array or
``None``."""

ENTRY = S.NullOr(S.Union(S.String, S.JsonObject, S.Array(S.Json)))


class ChoiceQuestion(TypedDict):
    type: Literal["choice"]
    instructions: Entry
    criteria: Mapping[str, Entry]


class ScoreQuestion(TypedDict):
    type: Literal["score"]
    instructions: Entry
    criteria: Sequence[Entry]


class NoulCriteria(TypedDict):
    false: Entry
    true: Entry


class NoulQuestion(TypedDict):
    type: Literal["noul"]
    instructions: Entry
    criteria: NotRequired[NoulCriteria]


class BoxQuestion(TypedDict):
    """Finds where something is in an image; needs Jev 1.14 and the
    ``TypeSafe-Danger-Zone-Images: true`` header."""

    type: Literal["box"]
    instructions: Entry


type Question = ChoiceQuestion | ScoreQuestion | NoulQuestion | BoxQuestion


class ImageAsset(TypedDict):
    """A base64 PNG or JPEG image: the standard alphabet with ``=``
    padding, no whitespace and no ``data:`` prefix."""

    type: NotRequired[Literal["image"]]
    format: Literal["png", "jpg", "jpeg"]
    data_base64: str


class SystemOneRequest(TypedDict):
    """A batch of questions against encoded state. ``assets`` maps
    placeholder strings to images; the model sees each image wherever its
    placeholder appears in ``state``, instructions or criteria."""

    model: str
    state: JsonValue
    questions: Mapping[str, Question]
    assets: NotRequired[Mapping[str, ImageAsset]]


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
    legend: NotRequired[Mapping[str, JsonValue]]


class NoulAnswer(TypedDict):
    type: Literal["noul"]
    noul: float


class Box(TypedDict):
    top: float
    bottom: float
    left: float
    right: float


class BoxAnswer(TypedDict):
    """A bounding box whose edges are fractions of the image's width and
    height."""

    type: Literal["box"]
    box: Box
    confidence: float


type Answer = ChoiceAnswer | ScoreAnswer | NoulAnswer | BoxAnswer


class Usage(TypedDict):
    input_tokens: NotRequired[float]
    output_tokens: NotRequired[float]


class SystemOneResponse(TypedDict):
    model: str
    answers: Mapping[str, Answer]
    usage: NotRequired[Usage]


class ModelInfo(TypedDict):
    name: str
    description: NotRequired[str]
    release_date: NotRequired[str]


class ListModelsResponse(TypedDict):
    models: Sequence[ModelInfo]


_CRITERIA = S.Struct(NoulCriteria, false=ENTRY, true=ENTRY)

CHOICE_QUESTION = S.Struct(ChoiceQuestion, instructions=ENTRY, criteria=S.Record(S.String, ENTRY))
SCORE_QUESTION = S.Struct(ScoreQuestion, instructions=ENTRY, criteria=S.Array(ENTRY))
NOUL_QUESTION = S.Struct(NoulQuestion, instructions=ENTRY, criteria=_CRITERIA)
BOX_QUESTION = S.Struct(BoxQuestion, instructions=ENTRY)
QUESTION = S.Union(CHOICE_QUESTION, SCORE_QUESTION, NOUL_QUESTION, BOX_QUESTION)
IMAGE_ASSET = S.Struct(ImageAsset)
SYSTEM_ONE_REQUEST = S.Struct(
    SystemOneRequest,
    questions=S.Record(S.String, QUESTION),
    assets=S.Record(S.String, IMAGE_ASSET),
)
CHOICE_ANSWER = S.Struct(ChoiceAnswer)
SCORE_ANSWER = S.Struct(ScoreAnswer)
NOUL_ANSWER = S.Struct(NoulAnswer)
BOX_ANSWER = S.Struct(BoxAnswer)
ANSWER = S.Union(CHOICE_ANSWER, SCORE_ANSWER, NOUL_ANSWER, BOX_ANSWER)
SYSTEM_ONE_RESPONSE = S.Struct(SystemOneResponse, answers=S.Record(S.String, ANSWER))
LIST_MODELS_RESPONSE = S.Struct(ListModelsResponse)


__all__ = [
    "ANSWER",
    "BOX_ANSWER",
    "BOX_QUESTION",
    "CHOICE_ANSWER",
    "CHOICE_QUESTION",
    "ENTRY",
    "IMAGE_ASSET",
    "LIST_MODELS_RESPONSE",
    "NOUL_ANSWER",
    "NOUL_QUESTION",
    "QUESTION",
    "SCORE_ANSWER",
    "SCORE_QUESTION",
    "SYSTEM_ONE_REQUEST",
    "SYSTEM_ONE_RESPONSE",
    "Answer",
    "Box",
    "BoxAnswer",
    "BoxQuestion",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "Entry",
    "ImageAsset",
    "ListModelsResponse",
    "ModelInfo",
    "NoulAnswer",
    "NoulCriteria",
    "NoulQuestion",
    "Question",
    "ScoreAnswer",
    "ScoreQuestion",
    "SystemOneRequest",
    "SystemOneResponse",
    "Usage",
]
