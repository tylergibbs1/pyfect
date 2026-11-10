"""Ports of Effect's ``http/ProblemDetails.test.ts``. Each test's docstring is
the Effect test title."""

from pyfect import run_sync
from pyfect import schema as S
from pyfect.http import problem_details


def test_decode_drops_wrong_typed_members() -> None:
    """decode drops wrong-typed members, defaults type and keeps extensions"""
    decoded = S.decode_unknown_sync(problem_details.Schema)(
        {"title": 123, "status": 404, "detail": "No such user", "traceId": "abc-123"}
    )
    assert decoded == {
        "type": "about:blank",
        "status": 404,
        "detail": "No such user",
        "traceId": "abc-123",
    }


def test_encode_always_emits_type() -> None:
    """encode always emits type"""
    encoded = S.encode_sync(problem_details.Schema)(
        {"type": "about:blank", "title": "Not Found", "status": 404}
    )
    assert encoded == {"type": "about:blank", "title": "Not Found", "status": 404}


def test_to_response_uses_the_status_or_500() -> None:
    """``toResponse``: the problem's status, else 500, as ``application/problem+json``."""
    found = problem_details.to_response({"type": "about:blank", "status": 404})
    assert found.status == 404
    assert found.headers.get("content-type") == "application/problem+json"
    assert problem_details.to_response({"type": "about:blank"}).status == 500
    assert run_sync(S.decode_unknown_effect(problem_details.Schema)({}).or_die()) == {
        "type": "about:blank"
    }
