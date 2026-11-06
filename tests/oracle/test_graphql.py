"""Ports of Effect's graphql/GraphQL.test.ts and
GraphQLClientError.test.ts. Each test's docstring is the Effect test title,
prefixed by its describe blocks."""

import json
from typing import Any

import pytest

from pyfect import schema as S
from pyfect.duration import Seconds
from pyfect.graphql import GraphQLMiddleware, enum_literals, other_typename, query
from pyfect.graphql._template import render_slices
from pyfect.graphql.client_error import (
    GRAPHQL_ERROR,
    GraphQLClientError,
    ResponseError,
    TransportError,
)
from pyfect.graphql.template import DocumentTemplate, Fragment, Selection, Variable
from pyfect.http import headers as H


class Auth(GraphQLMiddleware): ...


# A pull request lookup. Odd entries in a ``body`` are names renamed per
# slice: ``PR`` references ``$withBody``, so it is per-slice; ``Author`` is
# shared. The root ``__typename`` checks that joining keeps the printer's
# spacing.
PULL_REQUEST_TEMPLATE = DocumentTemplate(
    variables=(
        Variable("owner", "String!"),
        Variable("number", "Int!"),
        Variable("withBody", "Boolean!=false"),
    ),
    selections=(
        Selection(name="__typename", body=("",)),
        Selection(
            alias="repo",
            name="repository",
            body=(
                "(owner:$",
                "owner",
                ',name:"effect"){pullRequest(number:$',
                "number",
                "){...",
                "PR",
                "}}",
            ),
        ),
    ),
    fragments=(
        Fragment("PR", ("on PullRequest{title body@include(if:$", "withBody", ")...Author}")),
        Fragment("Author", ("on PullRequest{author{login}}",)),
    ),
)

EMPTY = S.Record(S.String, S.Unknown)


def test_middleware_returns_a_new_operation():
    """GraphQL / middleware returns a new operation and leaves the original unchanged"""
    viewer = query("Viewer", document="query Viewer{viewer{login}}", result=EMPTY)
    authed = viewer.middleware(Auth)
    assert authed.middlewares == (Auth,)
    assert viewer.middlewares == ()


def test_an_operation_built_from_a_template_sends_the_joined_document():
    """GraphQL / an operation built from a template sends the joined document"""
    pull_request = query("PullRequest", document=PULL_REQUEST_TEMPLATE, result=EMPTY)
    assert pull_request.document == (
        "query PullRequest($owner:String!$number:Int!$withBody:Boolean!=false){__typename "
        'repo:repository(owner:$owner,name:"effect"){pullRequest(number:$number){...PR}}}'
        "fragment PR on PullRequest{title body@include(if:$withBody)...Author}"
        "fragment Author on PullRequest{author{login}}"
    )
    assert pull_request.template is PULL_REQUEST_TEMPLATE


def test_render_slices_aliases_root_fields():
    """GraphQL / renderSlices aliases root fields and renames variables and per-slice fragments"""
    assert render_slices("query", "PullRequest", PULL_REQUEST_TEMPLATE, ["_0_", "_1_"]) == (
        "query PullRequest($_0_owner:String!$_0_number:Int!$_0_withBody:Boolean!=false"
        "$_1_owner:String!$_1_number:Int!$_1_withBody:Boolean!=false)"
        "{_0___typename:__typename "
        '_0_repo:repository(owner:$_0_owner,name:"effect"){pullRequest(number:$_0_number){..._0_PR}}'
        "_1___typename:__typename "
        '_1_repo:repository(owner:$_1_owner,name:"effect"){pullRequest(number:$_1_number){..._1_PR}}}'
        "fragment _0_PR on PullRequest{title body@include(if:$_0_withBody)...Author}"
        "fragment _1_PR on PullRequest{title body@include(if:$_1_withBody)...Author}"
        "fragment Author on PullRequest{author{login}}"
    )


def test_other_typename_accepts_any_type_name_except_the_selected_ones():
    """GraphQL / otherTypename accepts any type name except the selected ones"""
    decode = S.decode_unknown_sync(other_typename(["Issue"]))
    assert decode("PullRequest") == "PullRequest"
    assert decode("AddedLater") == "AddedLater"
    with pytest.raises(S.SchemaError):
        decode("Issue")


def test_enum_literals_accepts_a_value_the_server_added_later():
    """GraphQL / enumLiterals accepts a value the server added later"""
    assert S.decode_unknown_sync(enum_literals(["OPEN", "CLOSED"]))("MERGED") == "MERGED"


# --- GraphQLClientError ---------------------------------------------------------------


def test_decoding_a_github_error_preserves_its_top_level_type():
    """GraphQLClientError / decoding a GitHub error preserves its top-level type"""
    error = {
        "type": "NOT_FOUND",
        "path": ["repository"],
        "locations": [{"line": 1, "column": 3}],
        "message": "Could not resolve to a Repository with the name 'Effect-TS/missing'.",
    }
    decoded = S.decode_unknown_sync(GRAPHQL_ERROR)(error)
    assert json.loads(json.dumps(decoded)) == error


def test_round_trips_both_error_headers_as_json_records():
    """GraphQLClientError / round trips both error headers as JSON records, encoding retryAfter as milliseconds"""  # noqa: E501
    headers = H.from_input({"X-RateLimit-Remaining": "0"})
    reasons = [
        TransportError(description="503", status=503, retry_after=Seconds(30), headers=headers),
        ResponseError(errors=({"message": "Rate limited"},), status=200, headers=headers),
    ]
    for reason in reasons:
        error = GraphQLClientError(operation="Viewer", reason=reason)
        encoded: Any = S.encode_sync(GraphQLClientError)(error)
        assert encoded["reason"]["headers"] == {"x-ratelimit-remaining": "0"}
        decoded = S.decode_unknown_sync(GraphQLClientError)(json.loads(json.dumps(encoded)))
        assert type(decoded.reason) is type(reason)
        assert isinstance(decoded.reason, TransportError | ResponseError)
        assert isinstance(decoded.reason.headers, H.Headers)
        assert decoded.reason.headers == headers
        if isinstance(reason, TransportError):
            assert encoded["reason"]["retryAfter"] == 30_000
            assert decoded.retry_after == Seconds(30)


def test_transport_error_is_retryable_for_429_5xx_and_non_fatal_close_codes():
    """GraphQLClientError / TransportError is retryable for 429, 5xx and non-fatal close codes"""
    assert TransportError(description="t", status=429).is_retryable
    assert TransportError(description="t", status=503).is_retryable
    assert not TransportError(description="t", status=400).is_retryable
    assert not TransportError(description="t", status=600).is_retryable
    assert TransportError(description="t", close_code=1006).is_retryable
    assert not TransportError(description="t", close_code=4401).is_retryable
    assert not TransportError(description="t", close_code=4500).is_retryable
    assert not TransportError(description="t", close_code=1011).is_retryable


def test_a_retry_after_that_is_neither_whole_seconds_nor_an_http_date_is_ignored():
    """GraphQLClientError / a Retry-After that is neither whole seconds nor an HTTP date is ignored"""  # noqa: E501
    for retry_after in ["1.5", "-1"]:
        reason = ResponseError(
            errors=({"message": "Bad request"},),
            status=400,
            headers=H.from_input({"retry-after": retry_after}),
        )
        assert reason.retry_after is None, retry_after
        assert not reason.is_retryable, retry_after


def test_a_403_with_retry_after_is_retryable():
    """GraphQLClientError / a 403 with Retry-After is retryable, and its status and headers are on the error"""  # noqa: E501
    headers = H.from_input({"retry-after": "30"})
    reasons = [
        ResponseError(errors=({"message": "Rate limited"},), status=403, headers=headers),
        TransportError(description="403", status=403, headers=headers, retry_after=Seconds(30)),
    ]
    for reason in reasons:
        error = GraphQLClientError(operation="Viewer", reason=reason)
        assert error.is_retryable
        assert error.status == 403
        assert error.headers == headers
