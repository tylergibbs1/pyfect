"""Ports of Effect's ``packages/ai/typesafe/test/TypeSafeDecisionModel.test.ts``.
Each docstring is the Effect test title; a title Effect writes in a loop is
one parametrized test. A structured rate level ``{label, description}`` is
an entry of a mapping criteria; ``Infinity``, which ``JSON.stringify``
writes as ``null``, is sent as ``null``. The ``__proto__`` /
``constructor`` / ``toString`` titles check that such keys are ordinary
keys, in order."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import model as M
from pyfect.ai.typesafe import client
from pyfect.ai.typesafe import decision_model as tdm
from pyfect.http import url
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, body_json, json_response


class Ticket(TypedDict):
    message: str
    orderId: str


department = D.classify(
    instructions="Which team should handle this",
    criteria={
        "billing": "Payment or subscription issues",
        "technical": "Bugs or integration problems",
        "sales": "Pricing or account questions",
    },
)
frustration = D.rate(
    instructions="How frustrated the customer appears",
    criteria=["Calm, just stating facts", "Frustrated but civil", "Very angry, strong language"],
)
urgent = D.probability(
    instructions="The message conveys urgency or time-sensitivity",
    criteria={"false": "No time pressure", "true": "Needs action now"},
)
DECISIONS: dict[str, D.AnyDecision] = {
    "department": department,
    "frustration": frustration,
    "urgent": urgent,
}
TRIAGE = D.make(input=S.Struct(Ticket), decisions=DECISIONS)

TICKET: Ticket = {
    "message": "Hi, I've been trying to connect my Stripe account for 3 days and it keeps "
    "failing. Please help ASAP.",
    "orderId": "A-104",
}

RESPONSE: dict[str, Any] = {
    "model": "jev-latest",
    "answers": {
        "department": {
            "type": "choice",
            "choice": "billing",
            "probabilities": {"billing": 0.84, "technical": 0.159, "sales": 0.001},
            "confidence": 0.596,
        },
        "frustration": {
            "type": "score",
            "score": 1.6,
            "legend": {
                "0": "Calm, just stating facts",
                "1": "Frustrated but civil",
                "2": "Very angry, strong language",
            },
            "probabilities": {"0": 0.05, "1": 0.3, "2": 0.65},
            "confidence": 0.78,
        },
        "urgent": {"type": "noul", "noul": 0.999},
    },
    "usage": {"input_tokens": 312, "output_tokens": 48},
}

structured = D.rate(
    instructions=["How severe?"], criteria={"Minor": "Minor", "Critical": {"impact": "outage"}}
)
STRUCTURED = D.make(input=S.String, decisions={"severity": structured})


def http(handler: Callable[[HttpClientRequest], HttpClientResponse]) -> MockHttp:
    return MockHttp(lambda request: fx.succeed(handler(request)))


def answering(body: object, check: Callable[[Any], None] = lambda _: None) -> MockHttp:
    def handle(request: HttpClientRequest) -> HttpClientResponse:
        check(body_json(request))
        return json_response(request, body)

    return http(handle)


def provided[A](
    effect: fx.Effect[A, Any, Any], mock: MockHttp, layer: Any = None
) -> fx.Effect[A, Any, Any]:
    return (
        effect.pipe(fx.provide(tdm.layer(model="jev-latest") if layer is None else layer))
        .pipe(fx.provide(client.layer(api_key=redact("ts-test-key"))))
        .pipe(fx.provide(mock.layer))
    )


def one_choice() -> D.Definition[str, Any]:
    choice = D.classify(instructions="Pick", criteria={"a": "A", "b": "B"})
    return D.make(input=S.String, decisions={"choice": choice})


def choice_body(probabilities: object) -> dict[str, Any]:
    return {
        "model": "jev-latest",
        "answers": {
            "choice": {
                "type": "choice",
                "choice": "a",
                "probabilities": probabilities,
                "confidence": 0.5,
            }
        },
    }


@testing.effect
def test_rounded_choice_total():
    """TypeSafeDecisionModel / accepts rounded choice probabilities that total 0.99"""
    neutral3 = D.classify(
        instructions="Choose a sentiment",
        criteria={"negative": "Negative", "neutral": "Neutral", "positive": "Positive"},
    )
    definition = D.make(input=S.String, decisions={"neutral3": neutral3})
    body = {
        "model": "jev-latest",
        "answers": {
            "neutral3": {
                "type": "choice",
                "choice": "neutral",
                "probabilities": {"negative": 0.02, "neutral": 0.93, "positive": 0.04},
                "confidence": 0.93,
            }
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    result = yield from provided(DM.decide(definition, input="It is fine"), answering(body))
    assert result.answers[neutral3].label == "neutral"
    assert math.isclose(sum(result.answers[neutral3].probabilities.values()), 1, abs_tol=1e-6)


@testing.effect
def test_normalizes_score():
    """TypeSafeDecisionModel / normalizes rounded score probabilities"""
    score = D.rate(instructions="Rate", criteria=["low", "mid", "high"])
    definition = D.make(input=S.String, decisions={"score": score})
    body = {
        "model": "jev-latest",
        "answers": {
            "score": {
                "type": "score",
                "score": 1,
                "probabilities": {"0": 0.1, "1": 0.7, "2": 0.19},
                "confidence": 0.7,
            }
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    result = yield from provided(DM.decide(definition, input="test"), answering(body))
    assert math.isclose(sum(result.answers[score].probabilities.values()), 1, abs_tol=1e-6)


@testing.effect
def test_rejects_beyond_two_decimals():
    """TypeSafeDecisionModel / rejects a distribution outside two-decimal rounding"""
    body = choice_body({"a": 0.49, "b": 0.49})
    error = yield from provided(DM.decide(one_choice(), input="test").flip(), answering(body))
    assert isinstance(error.reason, E.InvalidOutputError)


@pytest.mark.parametrize(
    ("probabilities", "reason"),
    [
        pytest.param({"a": 1.01, "b": -0.02}, E.InvalidOutputError, id="out-of-range"),
        pytest.param({"a": 0, "b": 0}, E.InvalidOutputError, id="all-zero"),
        pytest.param({"a": 0.5}, E.InvalidOutputError, id="missing label"),
        # `Infinity` serializes as `null`, which the client response schema rejects
        pytest.param({"a": None, "b": 0.5}, E.InvalidResponseError, id="non-finite"),
    ],
)
@testing.effect
def test_rejects_choice_probabilities(probabilities: dict[str, Any], reason: type[Any]):
    """TypeSafeDecisionModel / rejects out-of-range / all-zero / missing label / non-finite
    choice probabilities"""
    body = choice_body(probabilities)
    error = yield from provided(DM.decide(one_choice(), input="test").flip(), answering(body))
    assert isinstance(error.reason, reason)


@testing.effect
def test_omits_absent_criteria():
    """TypeSafeDecisionModel / omits absent probability criteria from the encoded question"""
    needs = D.probability(instructions="Needs action now")
    definition = D.make(input=S.String, decisions={"urgent": needs})

    def check(body: Any) -> None:
        assert body["questions"]["urgent"] == {"type": "noul", "instructions": "Needs action now"}

    body = {
        "model": "jev-latest",
        "answers": {"urgent": {"type": "noul", "noul": 0.75}},
        "usage": {"input_tokens": 20, "output_tokens": 4},
    }
    result = yield from provided(DM.decide(definition, input="Help ASAP"), answering(body, check))
    assert result.answers[needs] == D.ProbabilityAnswer(0.75)


KEYS = ["__proto__", "constructor", "toString"]


@pytest.mark.parametrize("key", KEYS)
@testing.effect
def test_classification_label_key(key: str):
    """TypeSafeDecisionModel / round trips a classification label named __proto__ / constructor
    / toString"""
    category = D.classify(
        instructions="Choose a category",
        criteria={key: "Special category", "ordinary": "Ordinary category"},
    )
    definition = D.make(input=S.String, decisions={"category": category})

    def check(body: Any) -> None:
        criteria = body["questions"]["category"]["criteria"]
        assert list(criteria) == [key, "ordinary"]
        assert criteria[key] == "Special category"

    body = {
        "model": "jev-latest",
        "answers": {
            "category": {
                "type": "choice",
                "choice": key,
                "probabilities": {key: 0.75, "ordinary": 0.25},
                "confidence": 0.5,
            }
        },
    }
    result = yield from provided(DM.decide(definition, input="Help"), answering(body, check))
    answer = result.answers[category]
    assert list(answer.probabilities) == [key, "ordinary"]
    assert answer.probabilities == {key: 0.75, "ordinary": 0.25}
    assert answer.label == key


@pytest.mark.parametrize("key", KEYS)
@testing.effect
def test_score_level_key(key: str):
    """TypeSafeDecisionModel / maps a score distribution to a rate level named __proto__ /
    constructor / toString"""
    intensity = D.rate(instructions="How intense", criteria=["low", key, "high"])
    definition = D.make(input=S.String, decisions={"intensity": intensity})

    def check(body: Any) -> None:
        assert body["questions"]["intensity"]["criteria"] == ["low", key, "high"]

    body = {
        "model": "jev-latest",
        "answers": {
            "intensity": {
                "type": "score",
                "score": 1.1,
                "legend": {"0": "low", "1": key, "2": "high"},
                "probabilities": {"0": 0.1, "1": 0.7, "2": 0.2},
                "confidence": 0.5,
            }
        },
    }
    result = yield from provided(DM.decide(definition, input="Help"), answering(body, check))
    answer = result.answers[intensity]
    assert list(answer.probabilities) == ["low", key, "high"]
    assert answer.probabilities == {"low": 0.1, key: 0.7, "high": 0.2}
    assert answer.label == key
    assert answer.rating == 1.1


@pytest.mark.parametrize("key", KEYS)
@testing.effect
def test_question_key(key: str):
    """TypeSafeDecisionModel / sends an own enumerable question named __proto__ / constructor /
    toString"""
    decision = D.probability(
        instructions="Needs action now", criteria={"false": "No", "true": "Yes"}
    )
    definition = D.make(input=S.String, decisions={key: decision})

    def check(body: Any) -> None:
        assert list(body["questions"]) == [key]
        assert body["questions"][key] == {
            "type": "noul",
            "instructions": "Needs action now",
            "criteria": {"false": "No", "true": "Yes"},
        }

    body = {
        "model": "jev-latest",
        "answers": {key: {"type": "noul", "noul": 0.75}},
        "usage": {"input_tokens": 20, "output_tokens": 4},
    }
    result = yield from provided(DM.decide(definition, input="Help"), answering(body, check))
    assert list(result.answers) == [key]
    assert result.answers[key] == D.ProbabilityAnswer(0.75)


@testing.effect
def test_model_metadata():
    """TypeSafeDecisionModel / model provides DecisionModel with typesafe provider metadata"""

    def noop(*_: object) -> fx.Effect[Any, Any]:
        return fx.die(RuntimeError("noop"))

    noop_client = client.Service(None, noop, noop)  # pyright: ignore[reportArgumentType]
    program = M.ProviderName().zip(M.ModelName()).zip(DM.DecisionModel())
    (provider, model_name), model = yield from program.pipe(
        fx.provide(tdm.model("jev-latest").layer)
    ).pipe(fx.provide_service(client.TypeSafeClient, noop_client))
    assert provider == "typesafe"
    assert model_name == "jev-latest"
    assert model.decide is not None


@testing.effect
def test_one_request():
    """TypeSafeDecisionModel / sends the encoded input as state and every decision as a question
    in one request"""
    mock = answering(RESPONSE)
    yield from provided(DM.decide(TRIAGE, input=TICKET), mock)
    assert len(mock.requests) == 1
    request = mock.requests[0]
    assert request.method == "POST"
    assert request.url == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["authorization"] == "Bearer ts-test-key"
    assert body_json(request) == {
        "state": {"message": TICKET["message"], "orderId": "A-104"},
        "model": "jev-latest",
        "questions": {
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this",
                "criteria": {
                    "billing": "Payment or subscription issues",
                    "technical": "Bugs or integration problems",
                    "sales": "Pricing or account questions",
                },
            },
            "frustration": {
                "type": "score",
                "instructions": "How frustrated the customer appears",
                "criteria": [
                    "Calm, just stating facts",
                    "Frustrated but civil",
                    "Very angry, strong language",
                ],
            },
            "urgent": {
                "type": "noul",
                "instructions": "The message conveys urgency or time-sensitivity",
                "criteria": {"false": "No time pressure", "true": "Needs action now"},
            },
        },
    }


@testing.effect
def test_maps_answers():
    """TypeSafeDecisionModel / maps choice, score, and noul answers onto classify, rate, and
    probability answers"""
    result = yield from provided(DM.decide(TRIAGE, input=TICKET), answering(RESPONSE))
    answers = result.answers
    assert answers[department].label == "billing"
    assert answers[department].probabilities == {
        "billing": 0.84,
        "technical": 0.159,
        "sales": 0.001,
    }
    assert answers[department].confidence == 0.596
    assert answers[frustration].rating == 1.6
    assert answers[frustration].label == "Very angry, strong language"
    assert answers[frustration].probabilities == {
        "Calm, just stating facts": 0.05,
        "Frustrated but civil": 0.3,
        "Very angry, strong language": 0.65,
    }
    assert answers[frustration].confidence == 0.78
    assert answers[urgent] == D.ProbabilityAnswer(0.999)
    assert result.usage.input_tokens == 312
    assert result.usage.output_tokens == 48


class OptionalTicket(TypedDict):
    message: str
    orderId: NotRequired[str | None]


@testing.effect
def test_explicit_none_as_null():
    """TypeSafeDecisionModel / encodes an explicitly undefined optional input field as JSON
    null"""
    definition = D.make(
        input=S.Struct(OptionalTicket, orderId=S.NullOr(S.String)), decisions=DECISIONS
    )
    mock = answering(RESPONSE)
    result = yield from provided(
        DM.decide(definition, input={"message": TICKET["message"], "orderId": None}), mock
    )
    assert len(mock.requests) == 1
    assert mock.bodies[0]["state"] == {"message": TICKET["message"], "orderId": None}
    assert result.answers[urgent].probability == 0.999


@pytest.mark.parametrize(
    ("extra", "input_tokens", "output_tokens"),
    [
        pytest.param({}, None, None, id="absent usage"),
        pytest.param({"usage": {}}, None, None, id="empty usage"),
        pytest.param({"usage": {"input_tokens": 312}}, 312, None, id="input tokens only"),
        pytest.param({"usage": {"output_tokens": 48}}, None, 48, id="output tokens only"),
    ],
)
@testing.effect
def test_usage_variants(extra: dict[str, Any], input_tokens: int | None, output_tokens: int | None):
    """TypeSafeDecisionModel / preserves answers with absent usage / empty usage / input tokens
    only / output tokens only"""
    body = {**{k: v for k, v in RESPONSE.items() if k != "usage"}, **extra}
    result = yield from provided(DM.decide(TRIAGE, input=TICKET), answering(body))
    assert result.answers[department].label == "billing"
    assert result.answers[frustration].rating == 1.6
    assert result.answers[urgent].probability == 0.999
    assert result.usage.input_tokens == input_tokens
    assert result.usage.output_tokens == output_tokens


@testing.effect
def test_pinned_model():
    """TypeSafeDecisionModel / sends a pinned model id through unchanged"""
    mock = answering({**RESPONSE, "model": "jev-1.13.0"})
    program = DM.decide(TRIAGE, input=TICKET).and_then(M.ModelName())
    model_name = yield from provided(program, mock, tdm.model("jev-1.13.0").layer)
    assert model_name == "jev-1.13.0"
    assert mock.bodies[0]["model"] == "jev-1.13.0"


def _urgent_only() -> tuple[D.Probability, dict[str, Any]]:
    decision = D.probability(
        instructions="The message conveys urgency",
        criteria={"false": "No time pressure", "true": "Needs action now"},
    )
    body = {
        "model": "jev-latest",
        "answers": {"urgent": {"type": "noul", "noul": 0.93}},
        "usage": {"input_tokens": 20, "output_tokens": 4},
    }
    return decision, body


@testing.effect
def test_string_state():
    """TypeSafeDecisionModel / passes a string input through as a string state"""
    decision, body = _urgent_only()
    sentiment = D.make(input=S.String, decisions={"urgent": decision})
    mock = answering(body)
    yield from provided(DM.decide(sentiment, input="My card was charged twice."), mock)
    assert mock.bodies[0]["state"] == "My card was charged twice."


@testing.effect
def test_array_state():
    """TypeSafeDecisionModel / passes an array input through as an array state"""
    decision, body = _urgent_only()
    conversation = D.make(input=S.Array(S.String), decisions={"urgent": decision})
    mock = answering(body)
    messages = ("Hi", "My customer number is TS1337.", "My card was charged twice.")
    yield from provided(DM.decide(conversation, input=messages), mock)
    assert mock.bodies[0]["state"] == list(messages)


def _with_answers(**answers: Any) -> dict[str, Any]:
    return {**RESPONSE, "answers": {**RESPONSE["answers"], **answers}}


@testing.effect
def test_mismatched_answer_type():
    """TypeSafeDecisionModel / fails with InvalidOutputError when an answer type does not match
    the decision"""
    body = _with_answers(
        urgent={
            "type": "choice",
            "choice": "true",
            "probabilities": {"true": 0.9, "false": 0.1},
            "confidence": 0.8,
        }
    )
    error = yield from provided(DM.decide(TRIAGE, input=TICKET).flip(), answering(body))
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_missing_answer():
    """TypeSafeDecisionModel / fails with InvalidOutputError when an answer is missing"""
    answers = {k: v for k, v in RESPONSE["answers"].items() if k != "urgent"}
    error = yield from provided(
        DM.decide(TRIAGE, input=TICKET).flip(), answering({**RESPONSE, "answers": answers})
    )
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_score_without_probabilities():
    """TypeSafeDecisionModel / fails with a non-retryable InvalidResponseError when a score
    answer omits probabilities"""
    score = {k: v for k, v in RESPONSE["answers"]["frustration"].items() if k != "probabilities"}
    error = yield from provided(
        DM.decide(TRIAGE, input=TICKET).flip(), answering(_with_answers(frustration=score))
    )
    assert isinstance(error.reason, E.InvalidResponseError)
    assert not error.is_retryable


@testing.effect
def test_skipped_level():
    """TypeSafeDecisionModel / fails with InvalidOutputError when a score distribution skips a
    level index"""
    score = {**RESPONSE["answers"]["frustration"], "probabilities": {"0": 0.35, "2": 0.65}}
    error = yield from provided(
        DM.decide(TRIAGE, input=TICKET).flip(), answering(_with_answers(frustration=score))
    )
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_client_errors():
    """TypeSafeDecisionModel / surfaces client errors through decide"""
    mock = http(
        lambda request: json_response(
            request, {"message": "Rate limit exceeded"}, status=429, headers={"retry-after": "3"}
        )
    )
    error = yield from provided(DM.decide(TRIAGE, input=TICKET).flip(), mock)
    assert isinstance(error.reason, E.RateLimitError)


@testing.effect
def test_structured_descriptions():
    """TypeSafeDecisionModel / sends structured descriptions and maps score indices to labels"""

    def check(body: Any) -> None:
        assert body["questions"] == {
            "severity": {
                "type": "score",
                "instructions": ["How severe?"],
                "criteria": ["Minor", {"impact": "outage"}],
            }
        }

    body = {
        "model": "jev-latest",
        "answers": {
            "severity": {
                "type": "score",
                "score": 0.9,
                "probabilities": {"0": 0.1, "1": 0.9},
                "confidence": 0.9,
                "legend": {"0": "Minor", "1": {"impact": "outage"}},
            }
        },
    }
    result = yield from provided(
        DM.decide(STRUCTURED, input="Checkout is down"), answering(body, check)
    )
    assert result.answers[structured].label == "Critical"
    assert dict(result.answers[structured].probabilities) == {"Minor": 0.1, "Critical": 0.9}


class Listing(TypedDict):
    message: str
    photo: DM.Image
    gallery: list[DM.Image]


present = D.probability(instructions="`photo` shows a coffee mug")
mug = D.locate(image="photo", instructions="the coffee mug")
FIND_MUG = D.make(
    input=S.Struct(Listing, photo=D.Image, gallery=S.Array(D.Image)),
    decisions={"present": present, "mug": mug},
)


@testing.effect
def test_images_as_assets():
    """TypeSafeDecisionModel / images / sends images as assets keyed by their state references
    and maps box answers onto locate answers"""
    value: Listing = {
        "message": "Kitchen counter",
        "photo": DM.Image("image/png", bytes([137, 80, 78, 71])),
        "gallery": [
            DM.Image("image/jpeg", "/9j/4AAQ"),
            DM.Image(
                "application/octet-stream",
                url.parse("data:image/png;base64,iVBORw0KGgo%2B%2FA%3D%3D#preview"),
            ),
        ],
    }
    body = {
        "model": "jev-1.14.0",
        "answers": {
            "present": {"type": "noul", "noul": 0.97},
            "mug": {
                "type": "box",
                "box": {"top": 0.25, "bottom": 0.82, "left": 0.44, "right": 0.84},
                "confidence": 0.92,
            },
        },
        "usage": {"input_tokens": 290, "output_tokens": 21},
    }
    mock = answering(body)
    result = yield from provided(
        DM.decide(FIND_MUG, input=value), mock, tdm.layer(model="jev-preview")
    )
    assert result.answers[present] == D.ProbabilityAnswer(0.97)
    assert result.answers[mug] == D.LocateAnswer(D.BoundingBox(0.44, 0.25, 0.84, 0.82), 0.92)
    sent = body_json(mock.requests[0])
    photo, jpeg, data_url = [sent["state"]["photo"], *sent["state"]["gallery"]]
    assert sent == {
        "model": "jev-preview",
        "state": {"message": "Kitchen counter", "photo": photo, "gallery": [jpeg, data_url]},
        "questions": {
            "present": {"type": "noul", "instructions": "`photo` shows a coffee mug"},
            "mug": {"type": "box", "instructions": "the coffee mug in `photo`"},
        },
        "assets": {
            photo: {"type": "image", "format": "png", "data_base64": "iVBORw=="},
            jpeg: {"type": "image", "format": "jpg", "data_base64": "/9j/4AAQ"},
            data_url: {"type": "image", "format": "png", "data_base64": "iVBORw0KGgo+/A=="},
        },
    }


@pytest.mark.parametrize(
    "image",
    [
        pytest.param(
            DM.Image("image/png", url.parse("https://example.com/mug.png")), id="a remote URL"
        ),
        pytest.param(
            DM.Image("image/png", url.parse("data:image/png,%89PNG")),
            id="a data URL without base64",
        ),
        pytest.param(DM.Image("image/webp", "UklGRg=="), id="a WebP image"),
    ],
)
@testing.effect
def test_rejects_invalid_images(image: DM.Image):
    """TypeSafeDecisionModel / images / rejects a remote URL / a data URL without base64 / a
    WebP image with InvalidUserInputError before sending"""
    mock = MockHttp(lambda _: fx.die(RuntimeError("Invalid images must not be sent")))
    value: Listing = {"message": "", "photo": image, "gallery": []}
    error = yield from provided(
        DM.decide(FIND_MUG, input=value).flip(), mock, tdm.layer(model="jev-preview")
    )
    assert isinstance(error.reason, E.InvalidUserInputError)
