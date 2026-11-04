"""Ports of Effect's ``packages/ai/openrouter/test/OpenRouterSchema.test.ts``.
Each docstring is the Effect test title (with its ``describe``)."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
import json
from typing import Any

import pytest

from pyfect import schema as S
from pyfect.ai.openrouter import schema as W

CHOICE_ANSWER = {
    "type": "choice",
    "choice": "billing",
    "probabilities": {"billing": 0.84, "technical": 0.159, "sales": 0.001},
    "confidence": 0.596,
}
SCORE_ANSWER = {
    "type": "score",
    "score": 1.6,
    "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
    "probabilities": {"0": 0.05, "1": 0.3, "2": 0.65},
    "confidence": 0.78,
}
NOUL_ANSWER = {"type": "noul", "noul": 0.999}
URGENT = {"urgent": {"type": "noul", "instructions": "Urgent"}}


def _decode(schema: Any, value: object) -> Any:
    return S.decode_unknown_sync(schema)(value)


def test_encodes_every_question_type():
    """OpenRouterSchema / encodes a decisions request with every question type"""
    request = {
        "model": "openai/gpt-4o-mini",
        "state": {"message": "My card was charged twice.", "orderId": "A-104"},
        "questions": {
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this",
                "criteria": {"billing": "Payment issues", "technical": "Bugs"},
            },
            "frustration": {
                "type": "score",
                "instructions": "How frustrated the customer appears",
                "criteria": ["Calm", "Frustrated", "Very angry"],
            },
            "urgent": {
                "type": "noul",
                "instructions": "The message conveys urgency",
                "criteria": {"false": "No time pressure", "true": "Needs action now"},
            },
        },
    }
    decoded = _decode(W.DECISIONS_REQUEST, request)
    encoded = S.encode_sync(W.DECISIONS_REQUEST)(decoded)
    assert json.loads(json.dumps(encoded)) == request


def test_routing_and_tracing_options():
    """OpenRouterSchema / accepts a request carrying routing and tracing options"""
    decoded = _decode(
        W.DECISIONS_REQUEST,
        {
            "model": "openai/gpt-4o-mini",
            "state": "hello",
            "questions": URGENT,
            "provider": {"order": ["openai"]},
            "session_id": "session-1",
            "user": "user-1",
        },
    )
    assert decoded["session_id"] == "session-1"
    assert decoded["user"] == "user-1"


def test_noul_without_criteria():
    """OpenRouterSchema / accepts a noul question without criteria"""
    decoded = _decode(
        W.NOUL_QUESTION, {"type": "noul", "instructions": "The message conveys urgency"}
    )
    assert decoded["type"] == "noul"
    assert "criteria" not in decoded


@pytest.mark.parametrize(
    "state",
    ["a plain string", {"message": "hi", "orderId": "A-1"}, ["first", "second"]],
    ids=["string", "object", "array"],
)
def test_accepts_state(state: object):
    """OpenRouterSchema / accepts a $name state"""
    decoded = _decode(
        W.DECISIONS_REQUEST, {"model": "openai/gpt-4o-mini", "state": state, "questions": URGENT}
    )
    assert decoded["state"] == state


def test_decodes_every_answer():
    """OpenRouterSchema / decodes a response with choice, score and noul answers"""
    response = {
        "id": "dec_123",
        "model": "openai/gpt-4o-mini",
        "provider": "OpenAI",
        "answers": {
            "department": CHOICE_ANSWER,
            "frustration": SCORE_ANSWER,
            "urgent": NOUL_ANSWER,
        },
        "usage": {"input_tokens": 312, "output_tokens": 48, "cost": 0.00042},
    }
    decoded = _decode(W.DECISIONS_RESPONSE, response)
    assert json.loads(json.dumps(decoded)) == response


def test_response_without_optional_fields():
    """OpenRouterSchema / decodes a response without id, provider or cost"""
    decoded = _decode(
        W.DECISIONS_RESPONSE,
        {
            "model": "openai/gpt-4o-mini",
            "answers": {"urgent": NOUL_ANSWER},
            "usage": {"input_tokens": 10, "output_tokens": 2},
        },
    )
    assert "id" not in decoded
    assert "provider" not in decoded
    assert "cost" not in decoded["usage"]


@pytest.mark.parametrize(
    "answer",
    [
        {"type": "choice", "choice": "billing"},
        {"type": "choice", "choice": "billing", "probabilities": {}},
        {"type": "score", "score": 1.6},
        {"type": "score", "score": 1.6, "probabilities": {"0": 1}},
    ],
    ids=[
        "choice answer without probabilities",
        "choice answer without confidence",
        "score answer without probabilities",
        "score answer without legend",
    ],
)
def test_optional_answer_fields(answer: dict[str, Any]):
    """OpenRouterSchema / decodes a $name, since the field is optional upstream"""
    assert _decode(W.ANSWER, answer)["type"] == answer["type"]


@pytest.mark.parametrize(
    "answer",
    [
        {"type": "choice", "probabilities": {"billing": 1}},
        {"type": "score", "probabilities": {"0": 1}},
        {"type": "noul"},
        {"type": "rank", "rank": []},
    ],
    ids=[
        "choice answer without choice",
        "score answer without score",
        "noul answer without noul",
        "answer with an unknown type",
    ],
)
def test_rejects_answer(answer: dict[str, Any]):
    """OpenRouterSchema / rejects a $name"""
    with pytest.raises(S.SchemaError):
        _decode(W.ANSWER, answer)


def test_rejects_response_without_usage():
    """OpenRouterSchema / rejects a response without usage"""
    with pytest.raises(S.SchemaError):
        _decode(
            W.DECISIONS_RESPONSE,
            {"model": "openai/gpt-4o-mini", "answers": {"urgent": NOUL_ANSWER}},
        )
