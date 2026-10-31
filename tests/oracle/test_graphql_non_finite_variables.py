"""Non-finite variables are sent as ``JSON.stringify`` writes them,
``null``, over POST, GET and graphql-ws (QA ai-workflow GQL-1), and a
``NaN`` token from the server is not JSON (GQL-2). Effect 4.0.6 under
Node: ``{"variables":{"n":null}}``; ``JSON.parse("NaN")`` throws."""

from __future__ import annotations

import pytest

from pyfect.graphql import _http, _ws, _ws_messages
from pyfect.graphql.protocol import GraphQLRequest
from pyfect.http import headers as H
from pyfect.http import url_params as U


def _request(value: float) -> GraphQLRequest:
    return GraphQLRequest(
        kind="query",
        query="query Q{x}",
        operation_name="Q",
        variables={"n": value},
        headers=H.from_input({}),
        url_params=U.from_input({}),
    )


VALUES = [float("nan"), float("inf"), float("-inf")]


@pytest.mark.parametrize("value", VALUES, ids=["nan", "inf", "-inf"])
def test_a_post_body_writes_non_finite_variables_as_null(value: float) -> None:
    request = _http._post("http://h/graphql", _request(value), "application/json")  # pyright: ignore[reportPrivateUsage]
    body = request.body
    assert b'"variables":{"n":null}' in getattr(body, "body", b"")


@pytest.mark.parametrize("value", VALUES, ids=["nan", "inf", "-inf"])
def test_get_params_write_non_finite_variables_as_null(value: float) -> None:
    request = _http._get("http://h/graphql", _request(value), "application/json")  # pyright: ignore[reportPrivateUsage]
    assert ("variables", '{"n":null}') in request.url_params.params


def test_a_ws_subscribe_frame_writes_non_finite_variables_as_null() -> None:
    payload = _http.request_body(_request(float("nan")))
    frame = _ws._encode({"id": "1", "type": "subscribe", "payload": payload})  # pyright: ignore[reportPrivateUsage]
    assert '"variables":{"n":null}' in frame


def test_a_ws_frame_with_a_nan_token_is_invalid() -> None:
    parsed = _ws_messages.parse('{"type":"next","id":"1","payload":{"data":{"n":NaN}}}')
    assert isinstance(parsed, _ws_messages.Invalid)
