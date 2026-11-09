"""Ports of Effect's ``packages/ai/cloudflare/test/CloudflareDecisionModel.test.ts``.
Each docstring is the Effect test title; the invalid-answer table is one
parametrized test. A structured rate level ``{label, description}`` is an
entry of a mapping criteria."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import model as M
from pyfect.ai.cloudflare import client
from pyfect.ai.cloudflare import decision_model as cdm
from pyfect.http import url
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, body_json, json_response


class Message(TypedDict):
    message: str


team = D.classify(
    instructions="Which team should handle this request?",
    criteria={"billing": "Payments", "technical": "Outages"},
)
severity = D.rate(instructions="How severe is the impact?", criteria=["Minor", "Major", "Critical"])
urgent = D.probability(
    instructions="Does this need immediate attention?",
    criteria={"false": "Can wait", "true": "Act now"},
)
TRIAGE = D.make(
    input=S.Struct(Message), decisions={"team": team, "severity": severity, "urgent": urgent}
)
INPUT: Message = {"message": "Checkout is down"}

ANSWERS: dict[str, Any] = {
    "team": {
        "type": "choice",
        "choice": "technical",
        "confidence": 0.9,
        "probabilities": {"billing": 0.1, "technical": 0.9},
    },
    "severity": {
        "type": "score",
        "score": 1.75,
        "confidence": 0.8,
        "probabilities": {"0": 0.05, "1": 0.15, "2": 0.8},
        "legend": {"0": "Minor", "1": "Major", "2": "Critical"},
    },
    "urgent": {"type": "noul", "noul": 0.99},
}

structured = D.rate(
    instructions=["How severe?"], criteria={"Minor": "Minor", "Critical": {"impact": "outage"}}
)
STRUCTURED = D.make(input=S.String, decisions={"severity": structured})


def http(
    answers: object,
    on_request: Callable[[HttpClientRequest], None] = lambda _: None,
    model: str = "clef",
) -> MockHttp:
    def respond(request: HttpClientRequest) -> Any:
        on_request(request)
        result = {
            "model": model,
            "answers": answers,
            "usage": {"input_tokens": 120, "output_tokens": 0},
        }
        return fx.succeed(json_response(request, {"success": True, "result": result}))

    return MockHttp(respond)


def provided[A](
    effect: fx.Effect[A, Any, Any], mock: MockHttp, layer: Any = None
) -> fx.Effect[A, Any, Any]:
    return (
        effect.pipe(fx.provide(cdm.layer(model="clef") if layer is None else layer))
        .pipe(fx.provide(client.layer(account_id="test-account", api_key=redact("test-token"))))
        .pipe(fx.provide(mock.layer))
    )


@testing.effect
def test_questions_and_answers():
    """CloudflareDecisionModel / sends every decision as a question and maps the answers"""
    mock = http(ANSWERS)
    program = DM.decide(TRIAGE, input=INPUT).zip(M.ProviderName()).zip(M.ModelName())
    (result, provider), model_name = yield from provided(program, mock, cdm.model("clef").layer)
    assert provider == "cloudflare"
    assert model_name == "clef"
    answers = result.answers
    assert answers[team].label == "technical"
    assert dict(answers[team].probabilities) == {"billing": 0.1, "technical": 0.9}
    assert answers[team].confidence == 0.9
    assert answers[severity].label == "Critical"
    assert answers[severity].rating == 1.75
    assert dict(answers[severity].probabilities) == {"Minor": 0.05, "Major": 0.15, "Critical": 0.8}
    assert answers[urgent].probability == 0.99
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 0
    assert mock.bodies[0] == {
        "model": "clef",
        "state": INPUT,
        "questions": {
            "team": {
                "type": "choice",
                "instructions": team.instructions,
                "criteria": dict(team.criteria),
            },
            "severity": {
                "type": "score",
                "instructions": severity.instructions,
                "criteria": ["Minor", "Major", "Critical"],
            },
            "urgent": {
                "type": "noul",
                "instructions": urgent.instructions,
                "criteria": urgent.criteria,
            },
        },
    }


@testing.effect
def test_arbitrary_model():
    """CloudflareDecisionModel / sends an arbitrary model identifier through the decision
    request"""
    model = "clef-next"
    mock = http(ANSWERS, model=model)
    program = DM.decide(TRIAGE, input=INPUT).zip(M.ModelName())
    result, model_name = yield from provided(program, mock, cdm.model(model).layer)
    assert model_name == model
    assert result.answers[urgent].probability == 0.99
    assert mock.requests[0].url == (
        f"https://api.cloudflare.com/client/v4/accounts/test-account/ai/run/@cf/cloudflare/{model}"
    )
    assert mock.bodies[0]["model"] == model


@testing.effect
def test_four_decimal_drift():
    """CloudflareDecisionModel / accepts probabilities with four-decimal rounding drift"""
    answers = {
        **ANSWERS,
        "severity": {
            **ANSWERS["severity"],
            "score": 1,
            "confidence": 0.3333,
            "probabilities": {"0": 0.3333, "1": 0.3333, "2": 0.3333},
        },
    }
    result = yield from provided(DM.decide(TRIAGE, input=INPUT), http(answers))
    assert result.answers[severity].label == "Minor"
    assert math.isclose(result.answers[severity].probabilities["Minor"], 1 / 3, abs_tol=1e-10)


@pytest.mark.parametrize(
    "invalid",
    [
        pytest.param({"team": ANSWERS["team"], "severity": ANSWERS["severity"]}, id="missing"),
        pytest.param(
            {**ANSWERS, "severity": {**ANSWERS["severity"], "probabilities": {"0": 0.2, "2": 0.8}}},
            id="skipped level",
        ),
        pytest.param(
            {
                **ANSWERS,
                "team": {**ANSWERS["team"], "probabilities": {"billing": 0.1, "technical": 0.89}},
            },
            id="drift",
        ),
    ],
)
@testing.effect
def test_invalid_output(invalid: dict[str, Any]):
    """CloudflareDecisionModel / fails with InvalidOutputError for a missing answer / a skipped
    rating level / drift beyond four decimals"""
    error = yield from provided(DM.decide(TRIAGE, input=INPUT).flip(), http(invalid))
    assert isinstance(error.reason, E.InvalidOutputError)


class Screenshot(TypedDict):
    message: str
    shots: list[DM.Image]


class Photo(TypedDict):
    photo: DM.Image


@testing.effect
def test_images():
    """CloudflareDecisionModel / sends byte arrays, base64 strings, and data URLs as images
    listed by reference in the state"""
    data_url = "data:image/webp;base64,UklGRg=="
    screenshots = D.make(
        input=S.Struct(Screenshot, shots=S.Array(D.Image)), decisions=TRIAGE.decisions
    )
    shots = [
        DM.Image("image/png", bytes([137, 80, 78, 71])),
        DM.Image("image/jpeg", "/9j/4AAQ"),
        DM.Image("image/webp", url.parse(data_url)),
    ]
    mock = http(ANSWERS)
    value: Screenshot = {**INPUT, "shots": shots}
    result = yield from provided(DM.decide(screenshots, input=value), mock)
    assert result.answers[urgent].probability == 0.99
    body = body_json(mock.requests[0])
    state: str = body["state"]
    png, jpeg, webp = json.loads(state[state.index("{") :])["shots"]
    assert state == (
        f"Image 1: {png}\nImage 2: {jpeg}\nImage 3: {webp}\n\n"
        + json.dumps({**INPUT, "shots": [png, jpeg, webp]}, separators=(",", ":"))
    )
    assert body["images"] == [
        {"content_type": "image/png", "base64": "iVBORw=="},
        {"content_type": "image/jpeg", "base64": "/9j/4AAQ"},
        data_url,
    ]


@testing.effect
def test_rejects_remote_urls():
    """CloudflareDecisionModel / rejects remote image URLs without sending a request"""
    photo = D.make(input=S.Struct(Photo, photo=D.Image), decisions=TRIAGE.decisions)
    mock = http(ANSWERS)
    value: Photo = {"photo": DM.Image("image/png", url.parse("https://example.com/cat.png"))}
    error = yield from provided(DM.decide(photo, input=value).flip(), mock)
    assert isinstance(error.reason, E.InvalidUserInputError)
    assert mock.requests == []


@testing.effect
def test_structured_descriptions():
    """CloudflareDecisionModel / sends structured descriptions and maps score indices to
    labels"""
    mock = http(
        {
            "severity": {
                "type": "score",
                "score": 0.9,
                "probabilities": {"0": 0.1, "1": 0.9},
                "confidence": 0.9,
                "legend": {"0": "Minor", "1": {"impact": "outage"}},
            }
        }
    )
    result = yield from provided(DM.decide(STRUCTURED, input="Checkout is down"), mock)
    assert result.answers[structured].label == "Critical"
    assert dict(result.answers[structured].probabilities) == {"Minor": 0.1, "Critical": 0.9}
    assert mock.bodies[0]["questions"] == {
        "severity": {
            "type": "score",
            "instructions": ["How severe?"],
            "criteria": ["Minor", {"impact": "outage"}],
        }
    }
