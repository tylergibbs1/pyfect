"""Ports of Effect's ``packages/ai/openai/test/OpenAiDecisionModel.test.ts``.
Each docstring is the Effect test title. Responses are recorded JSON
answered by a mocked ``HttpClient``. A structured rate level
``{label, description}`` is an entry of a mapping criteria."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import model as M
from pyfect.ai.openai import client
from pyfect.ai.openai import decision_model as odm
from pyfect.http import url
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact
from pyfect.result import Err, Ok

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
    input=S.Struct(Message),
    decisions={"team": team, "severity": severity, "urgent": urgent},
)
urgency = D.probability(instructions="Does this need immediate attention?")
URGENCY = D.make(input=S.String, decisions={"urgent": urgency})

INPUT: Message = {"message": "Checkout is down"}

ANSWERS: list[dict[str, Any]] = [
    {
        "name": "team",
        "type": "choice",
        "choice": "technical",
        "probabilities": [
            {"value": "billing", "probability": 0.1},
            {"value": "technical", "probability": 0.9},
        ],
        "confidence": 0.9,
    },
    {
        "name": "severity",
        "type": "score",
        "score": 1.75,
        "probabilities": [
            {"value": 0, "label": "minor", "probability": 0.05},
            {"value": 1, "label": "major", "probability": 0.15},
            {"value": 2, "label": "critical", "probability": 0.8},
        ],
        "confidence": 0.8,
    },
    {"name": "urgent", "type": "predicate", "probability": 0.99},
]

_USAGE = {"usage": {"input_tokens": 120, "output_tokens": 0}}


def response(answers: list[Any], fields: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": "dec_123",
        "object": "decision",
        "model": "gpt-6-luna",
        "answers": answers,
        **(_USAGE if fields is None else fields),
    }


def http(
    body: object, on_request: Callable[[HttpClientRequest], None] = lambda _: None
) -> MockHttp:
    def respond(request: HttpClientRequest) -> Any:
        on_request(request)
        return fx.succeed(json_response(request, body))

    return MockHttp(respond)


def provided[A](
    effect: fx.Effect[A, Any, Any], mock: MockHttp, *, as_model: bool = False
) -> fx.Effect[A, Any, Any]:
    layer = odm.model("gpt-6-luna").layer if as_model else odm.layer(model="gpt-6-luna")
    return (
        effect.pipe(fx.provide(layer))
        .pipe(fx.provide(client.layer(api_key=redact("sk-test-key"))))
        .pipe(fx.provide(mock.layer))
    )


@testing.effect
def test_explicit_rate_labels():
    """OpenAiDecisionModel / keeps explicit Rate labels separate from their string descriptions"""
    level = D.rate(
        instructions="Severity?", criteria={"Minor": "Minor", "Critical": "Checkout unavailable"}
    )
    definition = D.make(input=S.String, decisions={"severity": level})
    body = response(
        [
            {
                "name": "severity",
                "type": "score",
                "score": 0.9,
                "confidence": 0.9,
                "probabilities": [
                    {"value": 0, "label": "ignored", "probability": 0.1},
                    {"value": 1, "label": "ignored", "probability": 0.9},
                ],
            }
        ]
    )
    mock = http(body)
    result = yield from provided(DM.decide(definition, input="Checkout is down"), mock)
    assert result.answers[level].label == "Critical"
    assert dict(result.answers[level].probabilities) == {"Minor": 0.1, "Critical": 0.9}
    assert mock.bodies[0]["questions"] == [
        {
            "type": "score",
            "name": "severity",
            "instructions": "Severity?",
            "levels": [
                {"label": "Minor", "description": "Minor"},
                {"label": "Critical", "description": "Checkout unavailable"},
            ],
        }
    ]


@testing.effect
def test_structured_descriptions():
    """OpenAiDecisionModel / serializes structured instructions and descriptions to strings,
    including null choices"""
    definition = D.make(
        input=S.String,
        decisions={
            "team": D.classify(
                instructions={"question": "Team?"},
                criteria={"billing": None, "technical": {"handles": "Outages"}},
            ),
            "severity": D.rate(
                instructions=["Severity?"],
                criteria={"Minor": "Minor", "Major": "Major", "Critical": ["outage"]},
            ),
            "urgent": D.probability(
                instructions={"question": "Urgent?"},
                criteria={"false": ["Can wait"], "true": {"action": "Act now"}},
            ),
        },
    )
    mock = http(response(ANSWERS))
    yield from provided(DM.decide(definition, input="Checkout is down"), mock)
    assert mock.bodies[0]["questions"] == [
        {
            "type": "choice",
            "name": "team",
            "instructions": '{"question":"Team?"}',
            "choices": [
                {"value": "billing", "description": "null"},
                {"value": "technical", "description": '{"handles":"Outages"}'},
            ],
        },
        {
            "type": "score",
            "name": "severity",
            "instructions": '["Severity?"]',
            "levels": [
                {"label": "Minor", "description": "Minor"},
                {"label": "Major", "description": "Major"},
                {"label": "Critical", "description": '["outage"]'},
            ],
        },
        {
            "type": "predicate",
            "name": "urgent",
            "instructions": (
                '{"question":"Urgent?"}\n\nfalse: ["Can wait"]\ntrue: {"action":"Act now"}'
            ),
        },
    ]


@testing.effect
def test_named_questions():
    """OpenAiDecisionModel / sends every decision as a named question and keys the answers by
    name"""
    mock = http(response(list(reversed(ANSWERS))))
    program = DM.decide(TRIAGE, input=INPUT).zip(M.ProviderName()).zip(M.ModelName())
    (result, provider), model_name = yield from provided(program, mock, as_model=True)
    assert provider == "openai"
    assert model_name == "gpt-6-luna"
    answers = result.answers
    assert answers[team].label == "technical"
    assert dict(answers[team].probabilities) == {"billing": 0.1, "technical": 0.9}
    assert answers[team].confidence == 0.9
    assert answers[severity].label == "Critical"
    assert answers[severity].rating == 1.75
    assert dict(answers[severity].probabilities) == {"Minor": 0.05, "Major": 0.15, "Critical": 0.8}
    assert answers[severity].confidence == 0.8
    assert answers[urgent].probability == 0.99
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 0
    request = mock.requests[0]
    assert request.method == "POST"
    assert request.url == "https://api.openai.com/v1/decisions"
    assert body_json(request) == {
        "model": "gpt-6-luna",
        "input": '{"message":"Checkout is down"}',
        "questions": [
            {
                "type": "choice",
                "name": "team",
                "instructions": "Which team should handle this request?",
                "choices": [
                    {"value": "billing", "description": "Payments"},
                    {"value": "technical", "description": "Outages"},
                ],
            },
            {
                "type": "score",
                "name": "severity",
                "instructions": "How severe is the impact?",
                "levels": [
                    {"label": "Minor", "description": "Minor"},
                    {"label": "Major", "description": "Major"},
                    {"label": "Critical", "description": "Critical"},
                ],
            },
            {
                "type": "predicate",
                "name": "urgent",
                "instructions": (
                    "Does this need immediate attention?\n\nfalse: Can wait\ntrue: Act now"
                ),
            },
        ],
    }


@testing.effect
def test_string_state_and_omitted_usage():
    """OpenAiDecisionModel / sends string state unchanged without images and leaves omitted usage
    undefined"""
    mock = http(response([ANSWERS[2]], {}))
    result = yield from provided(DM.decide(URGENCY, input="Checkout is down"), mock)
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert mock.bodies[0]["input"] == "Checkout is down"


@testing.effect
def test_missing_answer():
    """OpenAiDecisionModel / fails with InvalidOutputError when an answer is missing"""
    error = yield from provided(DM.decide(TRIAGE, input=INPUT).flip(), http(response(ANSWERS[:2])))
    assert isinstance(error.reason, E.InvalidOutputError)


REFUSAL = {"name": "severity", "type": "refusal", "refusal": "I can't help with that."}


@testing.effect
def test_refusal_beside_missing():
    """OpenAiDecisionModel / decide fails with ContentPolicyError when any answer is a refusal,
    even beside a missing answer"""
    error = yield from provided(
        DM.decide(TRIAGE, input=INPUT).flip(), http(response([REFUSAL, ANSWERS[2]]))
    )
    assert isinstance(error.reason, E.ContentPolicyError)
    assert "severity" in error.reason.description
    assert "team" not in error.reason.description


@testing.effect
def test_settled_refusal_and_mismatch():
    """OpenAiDecisionModel / decideSettled reports a refusal and a mismatched score per
    decision"""
    body = response([{**ANSWERS[1], "name": "team"}, REFUSAL, ANSWERS[2]])
    settled = yield from provided(DM.decide_settled(TRIAGE, input=INPUT), http(body))
    outcomes = settled.outcomes
    team_outcome = outcomes[team]
    assert isinstance(team_outcome, Err) and team_outcome.error.reason == "Invalid"
    severity_outcome = outcomes[severity]
    assert isinstance(severity_outcome, Err) and severity_outcome.error.reason == "Refused"
    assert outcomes[urgent] == Ok(D.ProbabilityAnswer(0.99))


@testing.effect
def test_refusal_outranks_later_answer():
    """OpenAiDecisionModel / a refusal outranks a later answer with the same name"""
    body = response(
        [
            {"name": "urgent", "type": "refusal"},
            {"name": "urgent", "type": "predicate", "probability": 0.99},
        ]
    )
    error = yield from provided(DM.decide(URGENCY, input="Checkout is down").flip(), http(body))
    assert isinstance(error.reason, E.ContentPolicyError)
    settled = yield from provided(DM.decide_settled(URGENCY, input="Checkout is down"), http(body))
    outcome = settled.outcomes[urgency]
    assert isinstance(outcome, Err) and outcome.error.reason == "Refused"


DATA_URL = "data:image/webp;base64,UklGRg=="
IMAGES = [
    DM.Image("image/png", bytes([137, 80, 78, 71])),
    DM.Image("image/jpeg", "/9j/4AAQ"),
    DM.Image("image/webp", url.parse(DATA_URL)),
]


def _assert_input(request: HttpClientRequest, text: str) -> None:
    body = body_json(request)
    assert len(body["input"]) == 1
    assert body["input"][0]["role"] == "user"
    assert body["input"][0]["content"] == [
        {"type": "input_text", "text": text},
        {"type": "input_image", "image_url": "data:image/png;base64,iVBORw=="},
        {"type": "input_image", "image_url": "data:image/jpeg;base64,/9j/4AAQ"},
        {"type": "input_image", "image_url": DATA_URL},
    ]


@testing.effect
def test_images():
    """OpenAiDecisionModel / sends string and JSON state with byte array, base64 string, and data
    URL images"""

    def check_urgency(request: HttpClientRequest) -> None:
        assert body_json(request)["questions"] == [
            {
                "type": "predicate",
                "name": "urgent",
                "instructions": "Does this need immediate attention?",
            }
        ]
        _assert_input(request, "Checkout is down")

    result = yield from provided(
        DM.decide(URGENCY, input="Checkout is down", images=IMAGES),
        http(response([ANSWERS[2]]), check_urgency),
    )
    assert result.answers[urgency].probability == 0.99
    json_result = yield from provided(
        DM.decide(TRIAGE, input=INPUT, images=IMAGES),
        http(response(ANSWERS), lambda r: _assert_input(r, '{"message":"Checkout is down"}')),
    )
    assert json_result.answers[urgent].probability == 0.99


@testing.effect
def test_rejects_remote_urls():
    """OpenAiDecisionModel / rejects remote image URLs without sending a request"""
    mock = http(response([ANSWERS[2]]))
    images = [DM.Image("image/png", url.parse("https://example.com/cat.png"))]
    error = yield from provided(
        DM.decide(URGENCY, input="Checkout is down", images=images).flip(), mock
    )
    assert isinstance(error.reason, E.InvalidUserInputError)
    assert mock.requests == []
