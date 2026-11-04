"""Ports of Effect's ``packages/ai/typesafe/test/TypeSafeSchema.test.ts``.
Each docstring is the Effect test title; an ``it.each`` title is one
parametrized test."""

from __future__ import annotations

import json
from typing import Any

import pytest

from pyfect import schema as S
from pyfect.ai.typesafe import schema as W

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


def _json(value: object) -> Any:
    return json.loads(json.dumps(value))


def test_request_round_trip():
    """TypeSafeSchema / encodes a systemone request with every question type"""
    request = {
        "state": {"message": "My card was charged twice.", "order_id": "A-104"},
        "model": "jev-latest",
        "questions": {
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this",
                "criteria": {
                    "billing": "Payment or subscription issues",
                    "technical": "Bugs or integration problems",
                },
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
    decoded = S.decode_unknown_sync(W.SYSTEM_ONE_REQUEST)(request)
    encoded = S.encode_sync(W.SYSTEM_ONE_REQUEST)(decoded)
    assert _json(encoded) == request


def test_noul_without_criteria():
    """TypeSafeSchema / accepts a noul question without criteria"""
    decoded = S.decode_unknown_sync(W.NOUL_QUESTION)(
        {"type": "noul", "instructions": "The message conveys urgency"}
    )
    assert decoded["type"] == "noul"
    assert "criteria" not in decoded


def test_response():
    """TypeSafeSchema / decodes a systemone response with choice, score, and noul answers"""
    response = {
        "model": "jev-latest",
        "answers": {
            "department": CHOICE_ANSWER,
            "frustration": SCORE_ANSWER,
            "urgent": NOUL_ANSWER,
        },
        "usage": {"input_tokens": 312, "output_tokens": 48},
    }
    assert _json(S.decode_unknown_sync(W.SYSTEM_ONE_RESPONSE)(response)) == response


def test_score_without_legend():
    """TypeSafeSchema / decodes a score answer without a legend"""
    without = {k: v for k, v in SCORE_ANSWER.items() if k != "legend"}
    decoded = S.decode_unknown_sync(W.SCORE_ANSWER)(without)
    assert decoded["score"] == 1.6
    assert decoded["probabilities"] == {"0": 0.05, "1": 0.3, "2": 0.65}


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(
            {"type": "score", "score": 1.6, "confidence": 0.78},
            id="score answer without probabilities",
        ),
        pytest.param(
            {"type": "score", "probabilities": {"0": 1}, "confidence": 1},
            id="score answer without score",
        ),
        pytest.param(
            {"type": "choice", "choice": "billing", "confidence": 1},
            id="choice answer without probabilities",
        ),
        pytest.param(
            {"type": "choice", "probabilities": {"billing": 1}, "confidence": 1},
            id="choice answer without choice",
        ),
        pytest.param({"type": "noul"}, id="noul answer without noul"),
        pytest.param({"type": "rank", "rank": []}, id="answer with an unknown type"),
    ],
)
def test_rejects_answer(answer: dict[str, Any]):
    """TypeSafeSchema / rejects a $name"""
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(W.ANSWER)(answer)


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({}, id="absent usage"),
        pytest.param({"usage": {}}, id="empty usage"),
        pytest.param({"usage": {"input_tokens": 312}}, id="input tokens only"),
        pytest.param({"usage": {"output_tokens": 48}}, id="output tokens only"),
    ],
)
def test_response_usage(extra: dict[str, Any]):
    """TypeSafeSchema / decodes a response with $name"""
    response = {"model": "jev-latest", "answers": {"urgent": NOUL_ANSWER}, **extra}
    assert _json(S.decode_unknown_sync(W.SYSTEM_ONE_RESPONSE)(response)) == response


@pytest.mark.parametrize(
    "model",
    [
        pytest.param({"name": "jev-latest"}, id="neither optional field"),
        pytest.param({"name": "jev-latest", "description": "Latest Jev"}, id="description only"),
        pytest.param({"name": "jev-latest", "release_date": "2026-08-01"}, id="release date only"),
    ],
)
def test_model(model: dict[str, Any]):
    """TypeSafeSchema / decodes a model with $name"""
    response = {"models": [model]}
    assert _json(S.decode_unknown_sync(W.LIST_MODELS_RESPONSE)(response)) == response


def test_models_list():
    """TypeSafeSchema / decodes a models list response"""
    response = {
        "models": [{"name": "jev-1.13.0", "description": "Jev 1.13", "release_date": "2026-08-01"}]
    }
    assert _json(S.decode_unknown_sync(W.LIST_MODELS_RESPONSE)(response)) == response
